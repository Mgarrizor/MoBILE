"""The model side of a calibration: an output of a finished run reduced over the cells of its region into a daily series,
in the same form as the observations (calibration_data.Observations), so that the same processing steps apply to both."""

import json
from dataclasses import replace
from pathlib import Path

import netCDF4
import numpy as np
import pandas as pd

from .calibration_data import DataError, Observations
from .cells import cell_areas
from .driving import LAT_NAMES, LON_NAMES, POP_NAMES, first_name
from .region import region_ranges
from .results import list_runs, load_run, read_run

SPACES = {"people": "Mean over the simulated cells, weighted by their people", "mean": "Mean over the simulated cells",
          "sum": "Sum over the simulated cells"}
SEED_MEAN = "mean"  # The seed choice of a seed band for all its seeds: their mean, or their median and range after the steps


def run_choices(runs_dir):
    """{folder: label} of the finished runs and seed bands in a results folder, the newest first."""
    return {folder: _label(folder, manifest) for folder, manifest in list_runs(runs_dir).items()}


def _label(folder, manifest):
    seeds = manifest.get("seeds")
    period = manifest.get("period") or {}
    when = f"{period.get('start', '')[:4]}–{period.get('end', '')[:4]}" if period else "all the driving data"
    what = f"{len(seeds)} seeds" if seeds else f"seed {manifest['run']['seed']}"
    return f"{Path(folder).name} ({when}, {what})"


def run_elsewhere(folder):
    """{folder: label} of a finished run or seed band in any folder, for the Model box; raises DataError saying why not."""
    folder = Path(folder).resolve()
    if not folder.is_dir():
        raise DataError(f"no folder {folder}")
    manifest = read_run(folder)  # This folder only: its neighbours may not even be readable
    if manifest is None:
        raise DataError(f"{folder.name} is not a finished run or seed band with its output (run.json, or seed_band.json, "
                        f"and output/output.nc)")
    return {str(folder): f"{_label(folder, manifest)}, in {folder.parent}"}


def run_seeds(folder):
    """The seeds of a seed band, or None for a single run."""
    band = Path(folder) / "seed_band.json"
    return json.loads(band.read_text())["seeds"] if band.is_file() else None


def run_variables(folder):
    """{name: {group, long_name, units, static}} of the outputs of a run (of the first seed of a band)."""
    seeds = run_seeds(folder)
    return load_run(Path(folder) / f"seed_{seeds[0]}" if seeds else folder).variables()


def default_aggregation(name, info):
    """How an output adds up over days: sum for amounts per day (new cases, bites), mean for states (prevalence)."""
    per_day = "day" in str(info.get("units", "")).replace(" ", "").lower() or "new" in name.lower() or name in ("EIR", "hbr")
    return "sum" if per_day else "mean"


def _people(run_dir, manifest, shape):
    """People in each cell of a run's grid (lat, lon), from its population file and region, as the model counts them."""
    pop_file = manifest["inputs"]["pop_file"]
    with netCDF4.Dataset(pop_file) as data:
        pop = np.ma.filled(data[first_name(POP_NAMES, data.variables)][:].astype("f8"), np.nan)
        lat = np.asarray(data[first_name(LAT_NAMES, data.variables)][:], dtype="f8")
        lon = np.asarray(data[first_name(LON_NAMES, data.variables)][:], dtype="f8")
    people = np.nan_to_num(pop) * cell_areas(pop_file)
    ranges = region_ranges(lon, lat, manifest.get("region"))
    if ranges is not None:
        (lon_first, lon_end), (lat_first, lat_end) = ranges
        people = people[lat_first:lat_end, lon_first:lon_end]
    if people.shape != shape:
        raise DataError("the population file of the run is not on the grid of its output any more")
    return people


def _series(run_dir, name, info, space):
    """(days, values) of an output of one run, reduced over its simulated cells."""
    run_dir = Path(run_dir)
    manifest = json.loads((run_dir / "run.json").read_text())
    with netCDF4.Dataset(run_dir / "output" / "output.nc") as data:
        variable = data[f"{info['group']}/{name}" if info["group"] else name]
        values = np.ma.filled(variable[:].astype("f8"), np.nan)  # (time, lat, lon)
        time = data["time"]
        days = netCDF4.num2date(time[:], time.units, getattr(time, "calendar", "standard"), only_use_cftime_datetimes=False,
                                only_use_python_datetimes=True)
    days = pd.to_datetime([day.isoformat() for day in days]).normalize()
    simulated = np.isfinite(values).any(axis=0)
    if not simulated.any():
        raise DataError(f"{name} has no value in any cell")
    if space == "people":
        weights = np.where(simulated, _people(run_dir, manifest, simulated.shape), 0.0)
        if weights.sum() <= 0:
            raise DataError("the simulated cells have no people")
        reduced = np.nansum(values * weights, axis=(1, 2)) / weights.sum()
    elif space == "mean":
        reduced = np.nanmean(values[:, simulated], axis=1)
    elif space == "sum":
        reduced = np.nansum(values[:, simulated], axis=1)
    else:
        raise DataError("choose how to reduce over the cells")
    return days, reduced


def _as_observations(days, values, folder, name, info, space, which, aggregation):
    day = np.asarray(days.to_numpy(), dtype="datetime64[D]")
    return Observations(
        shape="dated", values=values, index=pd.DataFrame({"start": day, "end": day}),
        aggregation=aggregation or default_aggregation(name, info), units=info["units"], name=name,
        notes=(f"model: {info['long_name']} ({name}) of {Path(folder).name}, {which}, {SPACES[space].lower()}",),
        source=Path(folder).name,
    )


def model_members(folder, name, space="people", seed=None, aggregation=None):
    """The output of each run taken: every seed of a seed band (seed=None or SEED_MEAN), one seed of it, or the single
    run; each reduced over the simulated cells into dated daily values, in the form of the observations."""
    variables = run_variables(folder)
    if name not in variables or variables[name]["static"]:
        raise DataError(f"the run has no daily output {name!r}")
    info = variables[name]
    chosen = chosen_seeds(folder, seed)
    if chosen is None:
        return [_as_observations(*_series(folder, name, info, space), folder, name, info, space, "single run", aggregation)]
    return [_as_observations(*_series(Path(folder) / f"seed_{s}", name, info, space), folder, name, info, space, f"seed {s}", aggregation)
            for s in chosen]


def chosen_seeds(folder, seed=None):
    """The seeds taken from a seed band: all of them (seed None or SEED_MEAN) or one; None for a single run."""
    seeds = run_seeds(folder)
    if not seeds:
        return None
    return seeds if seed in (None, SEED_MEAN) else [int(seed)]


def model_series(folder, name, space="people", seed=None, aggregation=None):
    """An output of a finished run, or of a seed band (seed=None or SEED_MEAN for the mean over its seeds, else one
    seed), reduced over the simulated cells into dated daily values, in the form of the observations."""
    return members_mean(model_members(folder, name, space, seed, aggregation), chosen_seeds(folder, seed))


def members_mean(members, seeds):
    """The mean of the daily values of the seeds taken (the first member itself for one)."""
    if len(members) == 1:
        return members[0]
    return replace(members[0], values=np.mean([member.values for member in members], axis=0),
                   notes=(members[0].notes[0].replace(f"seed {seeds[0]}", f"seeds {', '.join(map(str, seeds))}"),))


BAND = ("lowest", "highest")  # The columns of the band over the seeds of a seed band, in the extra columns of the observations


def seed_spread(members, steps, others=None, first_note=None):
    """The steps applied to each seed, then the median and the range over the seeds of each value, as in the seed bands
    of the Results tab: the spread of the processed values (e.g. of monthly sums), not of the daily ones. The values are
    the medians, the lowest and highest seeds the columns of BAND."""
    from .calibration_steps import apply_steps

    processed = [apply_steps(member, steps, others) for member in members]
    first = processed[0]
    if any(not other.index.equals(first.index) for other in processed[1:]):
        raise DataError("the seeds do not give the same periods after the steps")
    values = np.array([member.values for member in processed])
    notes = (first_note or first.notes[0], *first.notes[1:],
             f"median over the {len(members)} seeds, each processed by the steps, with their range (lowest to highest) as a band")
    return replace(first, values=np.nanmedian(values, axis=0), sd=None,
                   extra={**first.extra, BAND[0]: np.nanmin(values, axis=0), BAND[1]: np.nanmax(values, axis=0)}, notes=notes)


# Possible drivers of incidence, read from the same run: {name: (label, default statistic)}
DRIVERS = {"rain": ("Rainfall", "sum"), "t2m": ("Temperature", "mean")}
DRIVER_PERIODS = {"as_is": "As they are (days)", "week": "Week", "month": "Month", "season": "Season", "year": "Year"}


def driver_series(folder, name, period="month", how=None, by_month=False, first=None, last=None, seed=None):
    """A driver (rainfall, temperature) of a run, as the model read it (the mean over the simulated cells), processed on
    its own: within first and last (dates), into periods by a statistic, and optionally a climatology by month."""
    from .calibration_steps import apply_steps  # Not at the top: calibration_steps imports calibration_data only

    how = how or DRIVERS[name][1]
    raw = model_series(folder, name, "mean", seed, aggregation="sum" if how == "sum" else "mean")
    steps = []
    if first is not None or last is not None:
        steps.append({"kind": "select", "what": "window", "first": first, "last": last, "items": []})
    if period != "as_is":
        steps.append({"kind": "aggregate", "period": period, "how": how, "complete": True, "days": 1})
    if by_month:
        steps.append({"kind": "climatology", "by": "month"})
    result = apply_steps(raw, steps)
    if how == "sum" and period != "as_is" and result.units.replace(" ", "").endswith("/day"):
        # A sum of an amount per day over a period is an amount per period, e.g. mm/day summed by month: mm per month
        result = replace(result, units=f"{result.units.replace(' ', '')[:-len('/day')]} per {period}")
    return result

