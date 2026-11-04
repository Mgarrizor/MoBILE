"""Checks of the driving files against each other and against the units the model expects: the grid, the
days and the physical units. They only read the coordinates, attributes and a sample of the days."""

import numpy as np
import xarray as xr

from .driving import LAT_NAMES, LON_NAMES, TIME_NAMES, first_name, open_field, sample_days
from .period import as_days

READ_ERRORS = (OSError, ValueError, KeyError, StopIteration, TypeError, RuntimeError)
LABELS = {"rain_file": "Rainfall", "temp_file": "Temperature", "pop_file": "Population density",
          "area_file": "Cell area", "imm_forcing": "Immunity forcing"}
GRIDDED = ("rain_file", "temp_file", "area_file", "imm_forcing")

RAIN_UNITS = {"mm/day", "mmday-1", "mm/d", "mmd-1"}
# Units met in rainfall and temperature files, with what to do to get those the model expects
RAIN_HINTS = {
    "kgm-2s-1": "multiply by 86400", "kg/m2/s": "multiply by 86400", "kgm-2": "a daily total in kg m-2 is mm/day",
    "m": "multiply by 1000", "m/day": "multiply by 1000", "mm/h": "multiply by 24", "mm/hr": "multiply by 24",
    "mmh-1": "multiply by 24", "mmhr-1": "multiply by 24",
}
CELSIUS = ("celsius", "celcius", "degc", "°c", "degreec", "degree_c")
TEMP_HINTS = {"k": "subtract 273.15", "kelvin": "subtract 273.15", "degf": "convert to °C", "fahrenheit": "convert to °C"}
AREA_UNITS = ("m2", "m^2", "m**2", "km2", "km^2", "km**2", "ha", "hectare")


def normal_units(units):
    return str(units or "").strip().lower().replace("^", "").replace("**", "").replace(" ", "").replace("per", "/")


def read_axes(path):
    """{lon, lat, days, steps} of a file: its sorted coordinates, its days (None if there are none or they cannot
    be read as dates) and its number of steps in time (None if it has no time)."""
    with xr.open_dataset(path) as data:
        axes = {name: np.sort(np.asarray(data[first_name(names, data.variables)].values, dtype="float64"))
                for name, names in (("lon", LON_NAMES), ("lat", LAT_NAMES))}
        time = next((name for name in TIME_NAMES if name in data.variables), None)
        axes["steps"] = None if time is None else int(data[time].size)
        axes["days"] = None if time is None else as_days(data[time].values)
        return axes


def driving_days(path):
    """The days of a driving file as datetime64[D]; None if it has no dates."""
    try:
        return read_axes(path)["days"]
    except READ_ERRORS:
        return None


def same_coordinates(first, second):
    if first.shape != second.shape:
        return False
    step = abs(first[1] - first[0]) / 4 if first.size > 1 else 1e-6
    return bool(np.allclose(first, second, rtol=0, atol=step))


def grid_text(axes):
    return f"{len(axes['lon'])} × {len(axes['lat'])} cells"


def day_text(axes):
    days = axes["days"]
    return f"{axes['steps']} steps" if days is None else f"{axes['steps']} days, {days[0]} to {days[-1]}"


def value_problems(key, path):
    """What is wrong with the units of a rainfall or temperature file, or with the values of a file whose units
    are missing or not those of its values."""
    field = open_field(path, key)
    units = field.attrs.get("units", "")
    unit = normal_units(units)
    values = np.asarray(sample_days(field).values, dtype="float64")
    values = values[np.isfinite(values)]
    problems = []
    if key == "rain_file":
        if units and unit not in RAIN_UNITS:
            hint = RAIN_HINTS.get(unit)
            problems.append(f"in {units!r}, not mm/day" + (f": {hint}" if hint else ""))
        elif values.size and values.min() < 0:
            problems.append("has negative rainfall")
        elif values.size and values.max() > 1500:
            problems.append(f"has up to {values.max():.0f} per day, too much for mm/day")
        elif values.size and values.max() < 0.01 and values.max() > 0:
            problems.append(f"has at most {values.max():.2g}: it looks like a rate per second, not mm/day")
        elif not units:
            problems.append("has no units attribute: mm/day is expected")
    else:
        celsius = any(name in unit for name in CELSIUS)
        if units and not celsius:
            hint = TEMP_HINTS.get(unit)
            problems.append(f"in {units!r}, not °C" + (f": {hint}" if hint else ""))
        elif values.size and values.mean() > 150:
            problems.append(f"has a mean of {values.mean():.0f}: it looks like kelvin, not °C")
        elif values.size and (values.min() < -90 or values.max() > 65):
            problems.append(f"has {values.min():.0f} to {values.max():.0f} °C, beyond what the Earth gives")
        elif not units:
            problems.append("has no units attribute: °C is expected")
    return problems


def driving_problems(inputs):
    """What is wrong with the driving files, as a list of sentences naming the files: unreadable files,
    grids that differ from that of the population file, different days, and units that are not those of the
    model. A file that is not set is not checked."""
    problems = []
    axes = {}
    for key, label in LABELS.items():
        path = inputs.get(key, "NONE")
        if not path or path == "NONE":
            continue
        try:
            axes[key] = read_axes(path)
        except READ_ERRORS as error:
            problems.append(f"{label}: cannot be read as a driving file ({error}).")
    pop = axes.get("pop_file")
    if pop is not None:
        for key in GRIDDED:
            other = axes.get(key)
            if other is not None and not (same_coordinates(pop["lon"], other["lon"]) and same_coordinates(pop["lat"], other["lat"])):
                problems.append(f"{LABELS[key]}: its grid, {grid_text(other)}, differs from that of the population file, {grid_text(pop)}.")
    rain = axes.get("rain_file")
    if rain is not None:
        for key in ("temp_file", "imm_forcing"):
            other = axes.get(key)
            if other is None:
                continue
            if other["steps"] != rain["steps"]:
                problems.append(f"{LABELS[key]}: {day_text(other)}, but rainfall has {day_text(rain)}.")
            elif other["days"] is not None and rain["days"] is not None and not np.array_equal(other["days"], rain["days"]):
                problems.append(f"{LABELS[key]}: its days, {day_text(other)}, differ from those of rainfall, {day_text(rain)}.")
        if rain["days"] is not None and len(rain["days"]) > 1 and not np.all(np.diff(rain["days"]).astype(int) == 1):
            problems.append("Rainfall: the days are not consecutive: the model takes one step a day.")
    for key in ("rain_file", "temp_file"):
        if key in axes:
            try:
                problems += [f"{LABELS[key]}: {text}." for text in value_problems(key, inputs[key])]
            except READ_ERRORS:
                pass  # Named in the first lines, or no variable the model knows
    area = inputs.get("area_file", "NONE")
    if "area_file" in axes:
        try:
            with xr.open_dataset(area) as data:
                units = normal_units(data["cell_area"].attrs.get("units", ""))
            if units and units not in AREA_UNITS:
                problems.append(f"Cell area: in {units!r}, not an area unit (m2).")
        except READ_ERRORS:
            problems.append("Cell area: has no variable named cell_area.")
    return problems
