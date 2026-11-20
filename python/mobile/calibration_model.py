"""The model side of a calibration: an output of a finished run reduced over the cells of its region into a daily series,
in the same form as the observations (calibration_data.Observations), so that the same processing steps apply to both."""

import json
import warnings
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


PEOPLE_OUTPUTS = {"Nagent": "out_N", "HA": "out_HA"}  # The outputs that give the people of each cell each day (agents x HA)


def _counts(run_dir, name, variables):
    """(days, counts) of an output per person of one run as cases of the model's own population: each day the sum over
    the simulated cells of the value times the people the cell stands for that day (its agents x its humans per agent,
    which a growing population changes)."""
    run_dir = Path(run_dir)
    with netCDF4.Dataset(run_dir / "output" / "output.nc") as data:
        def field(key):
            info = variables[key]
            return np.ma.filled(data[f"{info['group']}/{key}" if info["group"] else key][:].astype("f8"), np.nan)
        values, agents, ratio = field(name), field("Nagent"), field("HA")
        time = data["time"]
        days = netCDF4.num2date(time[:], time.units, getattr(time, "calendar", "standard"), only_use_cftime_datetimes=False,
                                only_use_python_datetimes=True)
    if not values.shape == agents.shape == ratio.shape:
        raise DataError(f"{name}, the agents and the humans per agent of the run are not on the same days and cells")
    people = np.nan_to_num(agents) * np.nan_to_num(ratio)
    counts = np.nansum(np.where(np.isfinite(values), values, 0.0) * people, axis=(1, 2))
    return pd.to_datetime([day.isoformat() for day in days]).normalize(), counts


def model_count_members(folder, name, seed=None, aggregation=None):
    """The output of each run taken (as model_members), per person, made cases of the model's own population each day
    (_counts): what the observational model draws reported cases around. Needs the outputs Agents per cell (Nagent) and
    Humans per agent (HA)."""
    variables = run_variables(folder)
    if name not in variables or variables[name]["static"]:
        raise DataError(f"the run has no daily output {name!r}")
    missing = [key for key in PEOPLE_OUTPUTS if key not in variables or variables[key]["static"]]
    if missing:
        raise DataError("the observational model needs the outputs Agents per cell (Nagent) and Humans per agent (HA), "
                        f"for the model's own population: {', '.join(missing)} missing")
    info = {**variables[name], "units": "cases"}
    chosen = chosen_seeds(folder, seed)
    runs = [(Path(folder), "single run")] if chosen is None else [(Path(folder) / f"seed_{s}", f"seed {s}") for s in chosen]
    return [_as_observations(*_counts(run_dir, name, variables), folder, name, info, "sum", which, aggregation or "sum")
            for run_dir, which in runs]


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
    from .calibration_steps import EDGE, apply_steps

    processed = [apply_steps(member, steps, others) for member in members]
    first = processed[0]
    if any(not other.index.equals(first.index) for other in processed[1:]):
        raise DataError("the seeds do not give the same periods after the steps")
    values = np.array([member.values for member in processed])
    notes = (first_note or first.notes[0], *first.notes[1:],
             f"median over the {len(members)} seeds, each processed by the steps, with their range (lowest to highest) as a band")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)  # Periods missing in every seed stay missing
        extra = {**first.extra, BAND[0]: np.nanmin(values, axis=0), BAND[1]: np.nanmax(values, axis=0)}
        if any(EDGE in member.extra for member in processed):  # The values a filter cut at the ends: their median too
            extra[EDGE] = np.nanmedian([member.extra.get(EDGE, np.full(len(first), np.nan)) for member in processed], axis=0)
        return replace(first, values=np.nanmedian(values, axis=0), sd=None, extra=extra, notes=notes)


# Possible drivers of incidence, read from the same run: {name: (label, default statistic)}
DRIVERS = {"rain": ("Rainfall", "sum"), "t2m": ("Temperature", "mean"), "vectors": ("Vector densities", "mean")}
# The outputs each driver draws, with their labels: vector density on the left axis, infective vectors on a twin right one
DRIVER_VARIABLES = {"rain": {"rain": "Rainfall"}, "t2m": {"t2m": "Temperature"},
                    "vectors": {"V": "Vector density", "Vinf": "Infective vector density"}}
DRIVER_OUTPUTS = {"vectors": "tick Vector density and Infective vector density in the Outputs card, and run again"}
DRIVER_PERIODS = {"as_is": "As they are (days)", "week": "Week", "month": "Month", "season": "Season", "year": "Year"}


def driver_series(folder, name, period="month", how=None, by_month=False, first=None, last=None, seed=None):
    """A driver (rainfall, temperature) of a run, as the model read it (the mean over the simulated cells), processed on
    its own: within first and last (dates), into periods by a statistic, and optionally a climatology by month."""
    from .calibration_steps import apply_steps  # Not at the top: calibration_steps imports calibration_data only

    how = how or DRIVERS.get(name, (None, "mean"))[1]
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


def driver_panel(folder, name, period="month", how=None, by_month=False, first=None, last=None, seed=None):
    """[(label, observations)] of the outputs a driver draws in its panel (two for the vector densities), each processed as
    driver_series does. Raises DataError saying which output to write if the run lacks one."""
    panel = []
    for variable, label in DRIVER_VARIABLES[name].items():
        try:
            panel.append((label, driver_series(folder, variable, period, how or DRIVERS[name][1], by_month, first, last, seed)))
        except DataError as error:
            hint = DRIVER_OUTPUTS.get(name)
            raise DataError(f"{error}{f': {hint}' if hint else ''}") from None
    return panel


def shared_span(model, data):
    """(first, last) dates both dated series cover, from the later start to the earlier end; None if either is not dated
    (e.g. observations imported as a climatology), when no common window can be cut."""
    if model.shape != "dated" or data.shape != "dated":
        return None
    first = max(pd.Timestamp(model.index["start"].min()), pd.Timestamp(data.index["start"].min()))
    last = min(pd.Timestamp(model.index["end"].max()), pd.Timestamp(data.index["end"].max()))
    if first > last:
        raise DataError("the model and the data share no period")
    return str(first.date()), str(last.date())


def validation_windows(validation):
    """[(first, last), ...] of a calibration's validation: none (None), one window [first, last], or several
    [[first, last], ...]."""
    if not validation:
        return []
    if isinstance(validation[0], str):
        return [tuple(validation)]
    return [tuple(window) for window in validation]


def validation_parts(validation):
    """The names of the parts scored on the validation windows, in their order: "validation" for one window,
    "validation_1", "validation_2", ... for several."""
    windows = validation_windows(validation)
    return ["validation"] if len(windows) == 1 else [f"validation_{k}" for k in range(1, len(windows) + 1)]


def process_observed(members, counts, model_steps, data, data_steps, observation, others=None, model_note=None, validation=None,
                     part=None):
    """(model, data, span, draws) with the observational model (observation.py). members: the runs' output per person
    (as model_members gives it), counts: the same as cases of the model's own population (model_count_members). The
    model's cases for each month (the counts through the model's steps up to the first that is not a preparing one,
    e.g. the monthly sums; the mean of the runs if several) are the mean counts reported cases are drawn around,
    Y ~ negative binomial(mean rho * cases, dispersion k), `observation` {rho, k, draws, seed}; each draw is then made
    per person as the data are (divided by the observations' population N of each month) and goes through the rest of
    the model's steps as process_both takes the model's series (the filter first, then the windows). model: the median
    of the processed draws (the series the metrics compare); draws: the processed draws (draws x values of model); data
    as process_both gives it."""
    from .calibration_data import select_window
    from .calibration_steps import PREPARING, apply_steps
    from .observation import DRAWS, draw, median_of, process_draws

    # Only the data and the span are taken here: the model's side of process_both (its runs per person, with no population
    # of their own) is not used, so a log offset in cases is taken per value there
    plain = [{**step, "offset_unit": "value"} if step.get("offset_unit") else step for step in model_steps]
    _, data_out, span = process_both(members, plain, data, data_steps, others, model_note, validation, part)
    first = next((i for i, step in enumerate(model_steps) if step.get("kind") not in PREPARING), len(model_steps))
    prepare, rest = model_steps[:first], model_steps[first:]
    if span is not None:
        counts = [select_window(member, *span) for member in counts]
        data = select_window(data, *span)
    monthly = [apply_steps(member, prepare) for member in counts]
    if any(not other.index.equals(monthly[0].index) for other in monthly[1:]):
        raise DataError("the runs do not give the same periods after the steps")
    mean = np.nanmean(np.array([np.asarray(m.values, dtype="f8") for m in monthly]), axis=0)  # Cases of the model, a month
    population = _population(monthly[0], data)
    # Per person, with the population of each month for the steps that need it (a log's offset in cases)
    base = replace(monthly[0], values=mean / population, units="cases per person", extra={**monthly[0].extra, "N": population})
    drawn = draw(mean, observation["rho"], observation["k"], observation.get("draws", DRAWS), observation.get("seed"))
    matrix = drawn / population  # Per person, as the data
    processed, shape = process_draws(base, matrix, rest, validation, part, others)
    return median_of(processed, shape), data_out, span, processed


def _period_words(series):
    """The typical period of a dated series' values, in words ("days", "weeks", "months", "years" ...), and its length in
    days (the median of the values' spans)."""
    days = float(np.median((pd.to_datetime(series.index["end"]) - pd.to_datetime(series.index["start"])).dt.days + 1))
    for words, low, high in (("days", 1, 1), ("weeks", 6, 8), ("months", 28, 31), ("quarters", 89, 92), ("years", 365, 366)):
        if low <= days <= high:
            return words, days
    return f"periods of about {days:.0f} days", days


def _population(model, data):
    """The observations' population N for each value of the model's series (dated, as the model's), matched to the
    observations' value of the same period (the nearest start, within half a period). Errors say what is wrong in
    general terms: no N, periods that differ (the model's series not yet in the observations' periods), or N missing."""
    if data.shape != "dated" or model.shape != "dated" or "N" not in data.extra:
        raise DataError("the observational model needs dated observations with their population for each value (a column "
                        "N), to make the reported cases it draws per person as the observations are")
    data_words, data_days = _period_words(data)
    model_words, model_days = _period_words(model)
    if not 0.75 <= model_days / data_days <= 1.33:
        raise DataError(f"the observational model draws reported cases for each period the observations are given in "
                        f"({data_words}), but the model's series is in {model_words} at that point: aggregate it into "
                        f"{data_words} first (an Aggregate step at the start of the model's steps)")
    known = pd.Series(np.asarray(data.extra["N"], dtype="f8"), index=pd.to_datetime(data.index["start"]))
    known = known[~known.index.duplicated()].sort_index()
    starts = pd.to_datetime(model.index["start"])
    matched = pd.Series(np.arange(len(known), dtype="f8"), index=known.index).reindex(
        starts, method="nearest", tolerance=pd.Timedelta(days=data_days / 2)).to_numpy()
    found = np.full(len(starts), np.nan)
    found[~np.isnan(matched)] = known.to_numpy()[matched[~np.isnan(matched)].astype(int)]
    def span(mask):
        dates = starts[mask]
        return f"{dates.min():%Y-%m-%d} to {dates.max():%Y-%m-%d}"
    if np.isnan(matched).any():
        raise DataError(f"{int(np.isnan(matched).sum())} of the model's {len(starts)} periods ({span(np.isnan(matched))}) "
                        "have no period of the observations to match: compare the model over the periods the "
                        "observations cover")
    bad = ~(found > 0)
    if bad.any():
        raise DataError(f"the observations' population N is missing or not above 0 for {int(bad.sum())} of the "
                        f"{len(starts)} periods compared ({span(bad)}): give N for them, or compare periods where it "
                        "is known")
    return found


def _split_at_filter(steps):
    """(steps up to and including the last time filter, the steps after it), or None without a filter."""
    last = max((i for i, step in enumerate(steps) if step.get("kind") == "filter"), default=None)
    return None if last is None else (steps[:last + 1], steps[last + 1:])


def process_both(members, model_steps, data, data_steps, others=None, model_note=None, validation=None, part=None):
    """(model, data, span): the model (each run taken, e.g. the seeds of a band) and the observations, both first cut to
    the period they share, then each processed by its own steps, so that the statistics of both, such as a climatology,
    cover the same years. For several runs, the median and range of the runs each processed (seed_spread). span is the
    (first, last) dates cut to, or None if they could not be cut (not dated).

    validation: the validation windows (validation_windows: one (first, last), or several), with part "calibration" for
    the shared period without any of them, a part of validation_parts (e.g. "validation", or "validation_2") for that
    window only, or None for the whole shared period. A side whose steps have a time filter is
    filtered over the whole shared period, up to and including its last filter, and only then cut to the part, the rest
    of its steps (e.g. an anomaly) applied to the part: the filter's unreliable ends are then only those of the whole
    period, and each part compares all its months the filter keeps, as a plot of the whole period shows them. Steps
    without a filter (e.g. a climatology) are applied to the part only, so that a statistic over the years does not mix
    the windows."""
    from .calibration_data import drop_window, select_window
    from .calibration_steps import apply_steps

    span = shared_span(members[0], data)
    if span is not None:
        members = [select_window(member, *span) for member in members]
        data = select_window(data, *span)
    if validation is None or part is None:
        model = apply_steps(members[0], model_steps) if len(members) == 1 else seed_spread(members, model_steps, None, model_note)
        return model, apply_steps(data, data_steps, others), span
    if span is None:
        raise DataError("a validation window needs dated observations")
    windows = validation_windows(validation)
    if part == "calibration":
        def cut(series):
            for window in windows:
                series = drop_window(series, *window)
            return series
    else:
        if part not in validation_parts(validation):
            raise DataError(f"no validation part {part!r}: the parts are {', '.join(validation_parts(validation))}")
        window = windows[validation_parts(validation).index(part)]

        def cut(series):
            return select_window(series, *window)
    model_split, data_split = _split_at_filter(model_steps), _split_at_filter(data_steps)
    if model_split is None:
        members, after = [cut(member) for member in members], model_steps
    else:
        before, after = model_split
        members = [cut(apply_steps(member, before)) for member in members]
    model = apply_steps(members[0], after) if len(members) == 1 else seed_spread(members, after, None, model_note)
    if data_split is None:
        data = apply_steps(cut(data), data_steps, others)
    else:
        before, after = data_split
        data = apply_steps(cut(apply_steps(data, before, others)), after, others)
    return model, data, span
