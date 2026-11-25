"""The age structure of a country from WorldPop: download the rasters of a product, analyse them as
utils/fetch_age.sh does, and keep the result, from which the age file of a run (age_structure/cumm_age.txt)
is written. The user chooses a product, a country and a year; the file is never an input.

A result is kept as JSON, a few kilobytes, in the settings folder (worldpop/<product>/<ISO3>_<year>.json);
the rasters, tens to hundreds of megabytes, are deleted once analysed. The result of the example that comes
with MoBILE is in the package, so that it runs without a connection.
"""

import json
import shutil
import tempfile
import urllib.error
import urllib.request
from functools import cache
from importlib import resources
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.interpolate import PchipInterpolator, make_interp_spline
from scipy.optimize import curve_fit

# The products, oldest first. url has {year}, {iso}, {iso_lower}, {sex} (f or m) and {age}, the code of an age
# group written with age_code; without lists the countries of COUNTRIES a product is not offered for
PRODUCTS = {
    "Global2000_2020": {
        "label": "WorldPop Global: age and sex structures, 2000–2020, 1 km, unconstrained (UN-adjusted)",
        "years": (2000, 2020),
        "source": "https://hub.worldpop.org/Global1_2000-2020_AgeSexStructures",
        "url": ("https://data.worldpop.org/GIS/AgeSex_structures/Global_2000_2020_1km/unconstrained/{year}/{iso}/"
                "{iso_lower}_{sex}_{age}_{year}_1km.tif"),
        "age_code": "{:d}",
        "without": (),
    },
    "R2025A": {
        "label": "WorldPop R2025A: age and sex structures, 2015–2030, 1 km, constrained",
        "years": (2015, 2030),
        "projected_from": 2025,  # 2015 to 2024 are estimates, 2025 to 2030 projections
        "source": "https://hub.worldpop.org/project/categories?id=8",
        "url": ("https://data.worldpop.org/GIS/AgeSex_structures/Global_2015_2030/R2025A/{year}/{iso}/v1/1km_ua/"
                "constrained/{iso_lower}_{sex}_{age}_{year}_CN_1km_R2025A_UA_v1.tif"),
        "age_code": "{:02d}",
        # Eritrea: its rasters are about 12 MB each (2020), 18 times those of Senegal, about 430 MB for a year
        "without": ("ERI",),
    },
}
DEFAULT_PRODUCT = "R2025A"  # Of a period from its first year on; before, the product covering its start (default_product)

# The World Bank's Sub-Saharan Africa region, where the model is meant to be used
COUNTRIES = {
    "AGO": "Angola", "BDI": "Burundi", "BEN": "Benin", "BFA": "Burkina Faso", "BWA": "Botswana",
    "CAF": "Central African Republic", "CIV": "Côte d'Ivoire", "CMR": "Cameroon", "COD": "Congo, Democratic Republic",
    "COG": "Congo, Republic", "COM": "Comoros", "CPV": "Cabo Verde", "ERI": "Eritrea", "ETH": "Ethiopia", "GAB": "Gabon",
    "GHA": "Ghana", "GIN": "Guinea", "GMB": "Gambia", "GNB": "Guinea-Bissau", "GNQ": "Equatorial Guinea", "KEN": "Kenya",
    "LBR": "Liberia", "LSO": "Lesotho", "MDG": "Madagascar", "MLI": "Mali", "MOZ": "Mozambique", "MRT": "Mauritania",
    "MUS": "Mauritius", "MWI": "Malawi", "NAM": "Namibia", "NER": "Niger", "NGA": "Nigeria", "RWA": "Rwanda",
    "SDN": "Sudan", "SEN": "Senegal", "SLE": "Sierra Leone", "SOM": "Somalia", "SSD": "South Sudan",
    "STP": "São Tomé and Príncipe", "SWZ": "Eswatini", "SYC": "Seychelles", "TCD": "Chad", "TGO": "Togo",
    "TZA": "Tanzania", "UGA": "Uganda", "ZAF": "South Africa", "ZMB": "Zambia", "ZWE": "Zimbabwe",
}

# The age groups of WorldPop: from 0 (under 1), 1 (1 to 4), 5 (5 to 9), ... to 80 (80 and over)
AGE_GROUPS = (0, 1, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 75, 80)
SEXES = ("f", "m")
HISTOGRAM_BINS = 20
HISTOGRAM_RANGE = (0.0, 0.5)
NODATA_TAG = 42113  # GDAL_NODATA, as text
FIT_START = (0.03, 1.0)  # Initial (A, gamma) of the exponential fit, as in fetch_age.sh
ANALYSIS = 1  # Version of the analysis below; a result made by another is made again


class WorldPopError(RuntimeError):
    """A product, country or year that does not exist, or a download that failed."""


def default_product(start_year):
    """The product for a period starting in a year: R2025A from 2015, else the oldest product covering the year, else the oldest."""
    if int(start_year) >= PRODUCTS[DEFAULT_PRODUCT]["years"][0]:
        return DEFAULT_PRODUCT
    return next((key for key, spec in PRODUCTS.items() if spec["years"][0] <= int(start_year) <= spec["years"][1]), next(iter(PRODUCTS)))


def product_countries(product):
    """{ISO3: name} of the countries a product is offered for."""
    return {iso: name for iso, name in COUNTRIES.items() if iso not in PRODUCTS[product]["without"]}


def resolve_choice(choice, start_year):
    """{product, country, year} with the product and year left out or None chosen for a period starting in start_year."""
    product = choice.get("product") or default_product(start_year)
    year = choice.get("year")
    return {"product": product, "country": choice["country"], "year": default_year(start_year, product) if year is None else year}


def default_year(start_year, product=DEFAULT_PRODUCT):
    """The year of a product closest to the first year of the simulation period."""
    first, last = PRODUCTS[product]["years"]
    return min(max(int(start_year), first), last)


def is_projection(year, product=DEFAULT_PRODUCT):
    """True for a year the product projects rather than estimates."""
    projected_from = PRODUCTS[product].get("projected_from")
    return projected_from is not None and int(year) >= projected_from


def year_label(year, product=DEFAULT_PRODUCT):
    """e.g. '2020', or '2027 (projection)'."""
    return f"{year} (projection)" if is_projection(year, product) else str(year)


def choice_problems(choice):
    """What is wrong with an age structure choice {product, country, year}; product and year None (or left out) are
    chosen from the period. A year needs a product."""
    if not isinstance(choice, dict) or "country" not in choice or not set(choice) <= {"product", "country", "year"}:
        return ["age_structure: needs country, and optionally product and year"]
    problems = []
    product = PRODUCTS.get(choice.get("product")) if choice.get("product") is not None else None
    if choice.get("product") is not None and product is None:
        problems.append(f"age_structure: no product {choice['product']!r}; available: {', '.join(PRODUCTS)}")
    if choice["country"] not in COUNTRIES:
        problems.append(f"age_structure: no country {choice['country']!r}; use an ISO3 code, e.g. SEN")
    elif product is not None and choice["country"] in product["without"]:
        problems.append(f"age_structure: {COUNTRIES[choice['country']]} is not offered in {choice['product']}")
    year = choice.get("year")
    if year is not None and choice.get("product") is None:
        problems.append("age_structure: a year needs a product")
    if product is not None and year is not None:
        first, last = product["years"]
        if not isinstance(year, int) or isinstance(year, bool) or not first <= year <= last:
            problems.append(f"age_structure: year must be from {first} to {last}")
    return problems


def raster_urls(product, country, year):
    """{(sex, age group): url} of the rasters of a product, country and year."""
    template, code = PRODUCTS[product]["url"], PRODUCTS[product]["age_code"]
    return {(sex, age): template.format(year=year, iso=country, iso_lower=country.lower(), sex=sex, age=code.format(age))
            for sex in SEXES for age in AGE_GROUPS}


def read_raster(path):
    """The values of a single-band GeoTIFF of WorldPop, as float32 (as stored), with no data as NaN."""
    with Image.open(path) as image:
        values = np.array(image, dtype="float32")
        nodata = image.tag_v2.get(NODATA_TAG)
    if nodata is not None:
        values[values == float(str(nodata).strip("\x00 "))] = np.nan
    return values


def analyse(rasters, interpolation="pchip"):
    """The analysis of fetch_age.sh on {(sex, age group): people per cell}: the share of each age group in each
    cell, its histogram and mean over the cells by sex, the cumulative weights of each year of age from 0 to 79
    interpolated through the mean shares, and the exponential decay fitted to the weights by year of age.

    interpolation "pchip" is that of utils/fetch_age.sh; "spline", a cubic spline, that of its first version."""
    totals = {sex: sum(rasters[(sex, age)].astype("float64") for age in AGE_GROUPS) for sex in SEXES}
    mean_share = np.zeros((len(AGE_GROUPS), len(SEXES)))
    histograms = {sex: [] for sex in SEXES}
    for i, age in enumerate(AGE_GROUPS):
        for j, sex in enumerate(SEXES):
            with np.errstate(invalid="ignore", divide="ignore"):
                share = (rasters[(sex, age)].astype("float64") / totals[sex]).ravel()
            share = share[np.isfinite(share)]
            mean_share[i, j] = share.mean()
            counts, edges = np.histogram(share, bins=HISTOGRAM_BINS, range=HISTOGRAM_RANGE)
            histograms[sex].append(counts.tolist())
    # Each group at its last year of age (0, 4, 9, ..., 79); 80 and over is left out, as in fetch_age.sh
    group_ends = np.array(AGE_GROUPS[1:]) - 1
    cumulative_groups = np.cumsum(mean_share[:-1].mean(axis=1))
    ages = np.arange(int(group_ends.min()), int(group_ends.max()) + 1)
    if interpolation == "pchip":
        weights = PchipInterpolator(group_ends, cumulative_groups)(ages)
    else:
        weights = make_interp_spline(group_ends, cumulative_groups, k=3)(ages)
    density = np.insert(np.diff(weights), 0, weights[0])
    (amplitude, gamma), covariance = curve_fit(lambda x, a, b: a * np.exp(-b * x), ages, density, p0=FIT_START, check_finite=True)
    errors = np.sqrt(np.diag(covariance))
    populated = np.isfinite(totals["f"]) & np.isfinite(totals["m"]) & ((np.nan_to_num(totals["f"]) + np.nan_to_num(totals["m"])) > 0)
    return {
        "analysis": ANALYSIS,
        "interpolation": interpolation,
        "age_groups": list(AGE_GROUPS),
        "mean_share": {sex: mean_share[:, j].tolist() for j, sex in enumerate(SEXES)},
        "histogram": {"edges": edges.tolist(), **histograms},
        "group_ends": group_ends.tolist(),
        "cumulative_groups": cumulative_groups.tolist(),
        "ages": ages.tolist(),
        "weights": weights.tolist(),
        "density": density.tolist(),
        "fit": {"amplitude": float(amplitude), "gamma": float(gamma), "amplitude_error": float(errors[0]),
                "gamma_error": float(errors[1])},
        "people": {sex: float(np.nansum(totals[sex])) for sex in SEXES},
        "cells": int(populated.sum()),
    }


def summary_name(product, country, year):
    return f"{product}/{country}_{year}.json"


def cache_folder():
    from .setup import settings_folder  # Not at the top: setup imports config, which imports this module
    return settings_folder() / "worldpop"


@cache
def _packaged(name):
    path = Path(str(resources.files("mobile"))) / "age_structures" / name
    return json.loads(path.read_text()) if path.is_file() else None


def cached_summary(product, country, year):
    """The result of a product, country and year if made before, in the package or the settings folder; else None."""
    name = summary_name(product, country, year)
    for summary in (_packaged(name), _read(cache_folder() / name)):
        if summary is not None and summary.get("analysis") == ANALYSIS:
            return summary
    return None


def _read(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None


def prepare(product, country, year, progress=None, cancelled=None, timeout=60):
    """The result of a product, country and year: as made before, or downloaded and analysed now and kept.

    progress(done, total) is called after each raster; cancelled() is checked before each one, and the download
    stops with WorldPopError if it returns True. The rasters are deleted afterwards, whatever happens."""
    summary = cached_summary(product, country, year)
    if summary is not None:
        return summary
    urls = raster_urls(product, country, year)
    folder = Path(tempfile.mkdtemp(prefix="mobile-worldpop-"))
    try:
        rasters = {}
        for done, (key, url) in enumerate(urls.items()):
            if cancelled is not None and cancelled():
                raise WorldPopError("cancelled")
            path = folder / url.rsplit("/", 1)[1]
            try:
                with urllib.request.urlopen(url, timeout=timeout) as response, open(path, "wb") as out:
                    shutil.copyfileobj(response, out)
            except (urllib.error.URLError, OSError) as error:
                raise WorldPopError(f"cannot download {url}: {error}") from None
            rasters[key] = read_raster(path)
            path.unlink()
            if progress is not None:
                progress(done + 1, len(urls))
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    summary = {"product": product, "country": country, "year": year, **analyse(rasters)}
    target = cache_folder() / summary_name(product, country, year)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(summary))
    return summary


def age_file_text(summary):
    """The age file of a run, age_structure/cumm_age.txt, as fetch_age.sh writes it: a cumulative weight per year of age."""
    return "".join(f"{value:.4f}\n" for value in summary["weights"])


def fitted_mortality(summary):
    """The decay rate of the age structure fitted by year of age, per year: the mortality mu that, with births equal
    to deaths (the default of the model), gives a stable age structure of the same slope."""
    return summary["fit"]["gamma"]


def describe(summary):
    """e.g. 'Senegal 2015 (WorldPop R2025A)', or 'Kenya 2030 (projection) (WorldPop R2025A)'."""
    year = year_label(summary["year"], summary["product"]) if summary["product"] in PRODUCTS else summary["year"]
    return f"{COUNTRIES.get(summary['country'], summary['country'])} {year} (WorldPop {summary['product']})"

