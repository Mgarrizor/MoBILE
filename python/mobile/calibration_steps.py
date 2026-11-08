"""Processing of observations as a pipeline of steps the user builds, in any order, shared by the Data box and (next)
the Model box. A step is a dict, kept in the standard netCDF file of the observations, so it records what was done and
can be applied again, e.g. to model output:

- ``aggregate``: values into longer periods (week, month, quarter, season, year, or a number of days) by sum, mean,
  median, min or max; with ``complete`` only periods the values cover entirely, else every period, with its coverage.
- ``arithmetic``: divide, multiply, add or subtract a column (e.g. the population) or a number.
- ``select``: a window of time, chosen months, seasons, years or age bands.
- ``climatology``: the mean of each calendar month or season over the years, with the spread over them as uncertainty.
- ``transform``: log, log10, standardise, anomaly from the mean, moving average.
- ``filter``: a frequency filter (low, high or band pass) of a regular series, with cut-offs as periods of time.
- ``combine``: with another set of observations of the same coordinates: sum, mean or difference.
"""

from dataclasses import replace

import numpy as np
import pandas as pd
from scipy import signal

from .calibration_data import SEASONS, DataError, Observations, combine, period_kind, select_window

STEP_KINDS = {
    "aggregate": "Aggregate into longer periods",
    "arithmetic": "Arithmetic with a column or a number",
    "select": "Select part of the values",
    "climatology": "Climatology (by month or season)",
    "transform": "Transform (log, standardise, anomaly, moving average)",
    "filter": "Frequency filter (low, high, band pass)",
    "combine": "Combine with other observations",
}
AGGREGATE_PERIODS = {"week": "Week", "month": "Month", "quarter": "Quarter", "season": "Season (DJF, MAM, JJA, SON)",
                     "year": "Year", "days": "Number of days"}
STATISTICS = {"sum": "Sum", "mean": "Mean (weighted by days)", "median": "Median", "min": "Minimum", "max": "Maximum"}
OPERATIONS = {"divide": "Divide by", "multiply": "Multiply by", "add": "Add", "subtract": "Subtract"}
SELECTIONS = {"window": "Window of time", "months": "Months", "seasons": "Seasons", "years": "Years", "bands": "Age bands"}
TRANSFORMS = {"log": "Natural log", "log10": "Log10", "standardise": "Standardise (mean 0, sd 1)",
              "anomaly": "Anomaly (minus the mean)", "moving_average": "Moving average"}
FILTERS = {"low": "Low pass: keep periods longer than", "high": "High pass: keep periods shorter than",
           "band": "Band pass: keep periods between"}
TIME_UNITS = {"days": 1.0, "months": 365.25 / 12, "years": 365.25}
FILTER_ORDER = 4  # Butterworth, applied forward and backward: no shift in time
COMBINATIONS = {"sum": "Sum", "mean": "Mean", "difference": "Difference (this minus the other)"}


def default_step(kind, observations):
    """A new step of a kind, pre-filled for these observations; every choice can be changed."""
    covers = period_kind(observations) if observations.shape == "dated" else None
    if kind == "aggregate":
        return {"kind": kind, "period": "year" if covers in ("month", "season", "quarter") else "month", "days": 7,
                "how": "sum" if observations.aggregation == "sum" else "mean", "complete": True}
    if kind == "arithmetic":
        column = next(iter(observations.extra), None)
        return {"kind": kind, "operation": "divide", "operand": "column" if column else "number", "column": column,
                "number": 1.0, "units": ""}
    if kind == "select":
        what = {"dated": "window", "yearly": "years", "climatology": "months", "season": "seasons", "age": "bands"}.get(observations.shape, "window")
        return {"kind": kind, "what": what, "first": None, "last": None, "items": []}
    if kind == "climatology":
        return {"kind": kind, "by": "month"}
    if kind == "transform":
        return {"kind": kind, "transform": "anomaly", "offset": 0.0, "window": 3}
    if kind == "filter":
        return {"kind": kind, "type": "low", "short": 1.0, "long": 2.0, "unit": "years", "missing": "interpolate", "max_gap": 3}
    if kind == "combine":
        return {"kind": kind, "other": None, "how": "sum"}
    raise DataError(f"no step {kind!r}")


def amount(number, unit):
    """e.g. '1 year', '2.5 years'."""
    return f"{number:g} {unit[:-1] if float(number) == 1 and unit.endswith('s') else unit}"


def describe(step):
    """One line saying what a step does, for the notes."""
    kind = step["kind"]
    if kind == "aggregate":
        period = f"{step['days']} days" if step["period"] == "days" else step["period"]
        return f"{STATISTICS[step['how']].split(' (')[0].lower()} by {period}{'' if step['complete'] else ', incomplete periods kept'}"
    if kind == "arithmetic":
        operand = step["column"] if step["operand"] == "column" else f"{step['number']:g}"
        return f"{OPERATIONS[step['operation']].lower()} {operand}"
    if kind == "select":
        if step["what"] == "window":
            return f"window {step.get('first') or 'start'} to {step.get('last') or 'end'}"
        return f"{step['what']} {', '.join(map(str, step['items']))}"
    if kind == "climatology":
        return f"climatology by {step['by']}"
    if kind == "transform":
        extra = f" of {step['window']}" if step["transform"] == "moving_average" else f" (offset {step['offset']:g})" if step["transform"] in ("log", "log10") and step["offset"] else ""
        return f"{TRANSFORMS[step['transform']].split(' (')[0].lower()}{extra}"
    if kind == "filter":
        if step["type"] == "band":
            what = f"band pass filter, periods of {step['short']:g} to {amount(step['long'], step['unit'])}"
        else:
            what = (f"{step['type']} pass filter, periods {'longer' if step['type'] == 'low' else 'shorter'} than "
                    f"{amount(step['long'] if step['type'] == 'low' else step['short'], step['unit'])}")
        if step.get("missing", "interpolate") == "interpolate":
            return f"{what}; gaps of up to {amount(int(step.get('max_gap') or 0), 'values')} interpolated for the filter only (left missing)"
        return f"{what}; each stretch without gaps filtered separately"
    return f"{step['how']} with {step['other']}"


def apply_steps(observations, steps, others=None):
    """The observations after each step in order. others is {name: Observations} for combine. Raises DataError naming
    the step that cannot be applied."""
    result = observations
    for i, step in enumerate(steps, start=1):
        before = result.notes
        try:
            result = STEP_FUNCTIONS[step["kind"]](result, step, others or {})
        except DataError as error:
            raise DataError(f"step {i} ({STEP_KINDS[step['kind']].split(' (')[0].lower()}): {error}") from None
        # The step, then what it says of itself
        added = result.notes[len(before):] if result.notes[:len(before)] == before else ()
        result = replace(result, steps=(*result.steps, dict(step)), notes=(*before, describe(step), *added))
    return result


# ---------------------------------------------------------------- aggregate

def _group_key(start, period, days, first):
    """(key, first day, last day) of the period of each start date."""
    if period == "days":
        index = ((start - first).dt.days // int(days)).astype(int)
        lower = first + pd.to_timedelta(index * int(days), unit="D")
        return index, lower, lower + pd.to_timedelta(int(days) - 1, unit="D")
    if period == "season":
        year = start.dt.year + (start.dt.month == 12)
        season = (start.dt.month % 12) // 3  # 0 DJF, 1 MAM, 2 JJA, 3 SON
        key = year * 4 + season
        first_month = pd.to_datetime({"year": year - (season == 0), "month": np.where(season == 0, 12, season * 3), "day": 1})
        return key, first_month, first_month + pd.offsets.MonthBegin(3) - pd.Timedelta(days=1)
    stamps = start.dt.to_period({"week": "W", "month": "M", "quarter": "Q", "year": "Y"}[period])
    return stamps, stamps.dt.start_time.dt.normalize(), stamps.dt.end_time.dt.normalize()


def aggregate(observations, step, _others):
    if observations.shape != "dated":
        raise DataError("only dated values are aggregated into longer periods; use a climatology for calendar months")
    if step["period"] not in AGGREGATE_PERIODS or step["how"] not in STATISTICS:
        raise DataError("choose a period and a statistic")
    if step["period"] == "days" and not int(step.get("days") or 0) >= 1:
        raise DataError("the number of days must be at least 1")
    frame = observations.frame()
    start, end = pd.to_datetime(frame["start"]), pd.to_datetime(frame["end"])
    key, lower, upper = _group_key(start, step["period"], step.get("days"), start.min())
    end_key = _group_key(end, step["period"], step.get("days"), start.min())[0]
    if np.any(np.asarray(key) != np.asarray(end_key)):
        i = int(np.argmax(np.asarray(key) != np.asarray(end_key)))
        raise DataError(f"a value crosses from one {step['period'].rstrip('s')} to the next: {observations.label(i)}")
    frame["__key"], frame["__lower"], frame["__upper"] = np.asarray(key), lower.to_numpy(), upper.to_numpy()
    frame["__days"] = (end - start).dt.days + 1
    name, rows, dropped = observations.name, [], 0
    for _, group in frame.groupby("__key", sort=True):
        valid = group[~group[name].isna()]
        whole = (pd.Timestamp(group["__upper"].iloc[0]) - pd.Timestamp(group["__lower"].iloc[0])).days + 1
        coverage = valid["__days"].sum() / whole
        if step["complete"] and (coverage < 1 or len(valid) < len(group)):
            dropped += 1
            continue
        values, weights = valid[name].to_numpy(), valid["__days"].to_numpy()
        how = step["how"]
        value = (np.nan if not len(values) else values.sum() if how == "sum" else np.average(values, weights=weights) if how == "mean"
                 else np.median(values) if how == "median" else values.min() if how == "min" else values.max())
        row = {"start": group["__lower"].iloc[0], "end": group["__upper"].iloc[0], "value": value, "coverage": coverage}
        for column in observations.extra:
            row[column] = np.average(group[column], weights=group["__days"]) if group[column].notna().all() else np.nan
        rows.append(row)
    if not rows:
        raise DataError(f"no {step['period']} is covered entirely by the values; turn off 'complete periods only' to keep "
                        f"incomplete ones, with their coverage")
    table = pd.DataFrame(rows)
    extra = {column: table[column].to_numpy() for column in observations.extra}
    if not step["complete"]:
        extra["coverage"] = table["coverage"].to_numpy()
    result = Observations(
        shape="dated", values=table["value"].to_numpy(dtype="float64"),
        index=pd.DataFrame({"start": table["start"].to_numpy().astype("datetime64[D]"), "end": table["end"].to_numpy().astype("datetime64[D]")}),
        aggregation="sum" if step["how"] == "sum" else "mean", units=observations.units, name=name, extra=extra,
        notes=observations.notes, source=observations.source, steps=observations.steps,
    )
    return result.with_note(f"{dropped} incomplete {step['period']}s left out") if dropped else result


# ---------------------------------------------------------------- arithmetic

def arithmetic(observations, step, _others):
    operation = step["operation"]
    if operation not in OPERATIONS:
        raise DataError("choose an operation")
    if step["operand"] == "column":
        if step.get("column") not in observations.extra:
            raise DataError(f"no column {step.get('column')!r}; the columns are {', '.join(observations.extra) or 'none'}")
        operand, label = observations.extra[step["column"]], step["column"]
    else:
        try:
            operand = float(step["number"])
        except (TypeError, ValueError):
            raise DataError("the number is not a number") from None
        label = f"{operand:g}"
    if operation == "divide" and np.any(np.asarray(operand)[~np.isnan(np.asarray(operand, dtype=float))] == 0):
        raise DataError(f"division by zero: {label} has zeros")
    values, sd = observations.values, observations.sd
    if operation == "divide":
        values, sd = values / operand, None if sd is None else sd / np.abs(operand)
    elif operation == "multiply":
        values, sd = values * operand, None if sd is None else sd * np.abs(operand)
    elif operation == "add":
        values = values + operand
    else:
        values = values - operand
    symbol = {"divide": "/", "multiply": "×", "add": "+", "subtract": "−"}[operation]
    units = (step.get("units") or "").strip() or (f"{observations.units} per {label}" if operation == "divide" and step["operand"] == "column"
                                                   else observations.units if operation in ("add", "subtract") else f"{observations.units} {symbol} {label}")
    return replace(observations, values=values, sd=sd, units=units, name=f"{observations.name} {symbol} {label}")


# ---------------------------------------------------------------- select

def select(observations, step, _others):
    what = step["what"]
    if what == "window":
        return replace(select_window(observations, step.get("first"), step.get("last")), notes=observations.notes)
    items = list(step.get("items") or [])
    if not items:
        raise DataError(f"choose the {what} to keep")
    index = observations.index
    if what == "months":
        if observations.shape == "climatology":
            months = index["month"].to_numpy()
        elif observations.shape == "dated":
            months = pd.to_datetime(index["start"]).dt.month.to_numpy()
        else:
            raise DataError("months are selected in dated values or a climatology")
        keep = np.isin(months, [int(m) for m in items])
    elif what == "seasons":
        if observations.shape != "season":
            raise DataError("seasons are selected in a seasonal climatology")
        keep = np.isin(index["season"].to_numpy(), [SEASONS.index(s) + 1 if s in SEASONS else int(s) for s in items])
    elif what == "years":
        if observations.shape == "yearly":
            years = index["year"].to_numpy()
        elif observations.shape == "dated":
            years = pd.to_datetime(index["start"]).dt.year.to_numpy()
        else:
            raise DataError("years are selected in dated or yearly values")
        keep = np.isin(years, [int(y) for y in items])
    elif what == "bands":
        if observations.shape != "age":
            raise DataError("age bands are selected in an age profile")
        keep = np.isin([observations.label(i) for i in range(len(observations))], [str(b) for b in items])
    else:
        raise DataError("choose what to select")
    if not keep.any():
        raise DataError(f"none of the {what} chosen are in the values")
    return replace(observations, values=observations.values[keep], index=observations.index[keep].reset_index(drop=True),
                   sd=None if observations.sd is None else observations.sd[keep],
                   extra={column: values[keep] for column, values in observations.extra.items()})


# ---------------------------------------------------------------- climatology

def climatology(observations, step, _others):
    if observations.shape != "dated":
        raise DataError("a climatology is made from dated values")
    by = step["by"]
    frame = observations.frame()
    start, end = pd.to_datetime(frame["start"]), pd.to_datetime(frame["end"])
    if by == "month":
        if np.any((start.dt.year != end.dt.year) | (start.dt.month != end.dt.month)):
            raise DataError("some values cover more than one month; aggregate them into months first")
        key = start.dt.month
    elif by == "season":
        season = lambda days: (days.dt.month % 12) // 3 + 1
        same = (season(start) == season(end)) & ((end - start).dt.days < 100)
        if not same.all():
            raise DataError("some values cover more than one season; aggregate them into seasons first")
        key = season(start)
    else:
        raise DataError("a climatology is by month or by season")
    grouped = pd.Series(observations.values).groupby(key.to_numpy())
    means, sds, counts = grouped.mean(), grouped.std(ddof=1), grouped.count()
    expected = 12 if by == "month" else 4
    if len(means) != expected:
        raise DataError(f"the values cover {len(means)} of the {expected} {by}s")
    column = "month" if by == "month" else "season"
    return Observations(
        shape="climatology" if by == "month" else "season", values=means.to_numpy(), index=pd.DataFrame({column: means.index.to_numpy()}),
        aggregation=observations.aggregation, units=observations.units, name=observations.name, sd=sds.to_numpy(),
        notes=observations.notes, source=observations.source, steps=observations.steps,
    ).with_note(f"climatology over {int(counts.min())} to {int(counts.max())} values per {by}")


# ---------------------------------------------------------------- transform

def transform(observations, step, _others):
    kind, values, sd = step["transform"], observations.values, observations.sd
    if kind in ("log", "log10"):
        shifted = values + float(step.get("offset") or 0)
        if np.any(shifted[~np.isnan(shifted)] <= 0):
            raise DataError("the log needs positive values: add an offset, e.g. 1 for counts with zeros")
        log = np.log if kind == "log" else np.log10
        return replace(observations, values=log(shifted), sd=None, units=f"{kind}({observations.units})", name=f"{kind} {observations.name}")
    if kind in ("standardise", "anomaly"):
        mean, std = np.nanmean(values), np.nanstd(values, ddof=1)
        if kind == "anomaly":
            return replace(observations, values=values - mean, name=f"anomaly of {observations.name}")
        if not std > 0:
            raise DataError("the values do not vary: they cannot be standardised")
        return replace(observations, values=(values - mean) / std, sd=None if sd is None else sd / std,
                       units="standard deviations", name=f"standardised {observations.name}")
    if kind == "moving_average":
        window = int(step.get("window") or 0)
        if window < 2 or window > len(values):
            raise DataError(f"the window must be from 2 to the number of values, {len(values)}")
        smooth = pd.Series(values).rolling(window, center=True, min_periods=window).mean().to_numpy()
        return replace(observations, values=smooth, sd=None, name=f"moving average of {observations.name}")
    raise DataError("choose a transform")


# ---------------------------------------------------------------- filter

FILTER_MISSING = {"interpolate": "Interpolate short gaps (for the filter only)", "stretches": "Filter each stretch separately"}
STEPS_OF = {"day": pd.DateOffset(days=1), "week": pd.DateOffset(weeks=1), "month": pd.DateOffset(months=1), "year": pd.DateOffset(years=1)}
DAYS_OF = {"day": 1.0, "week": 7.0, "month": TIME_UNITS["months"], "year": TIME_UNITS["years"]}


def regular_series(observations):
    """(values on a regular series from the first value to the last, the position of each row in it, the length of a
    value in days). Periods with no row are missing in it. Dated values must each cover a day, a week, a month or a
    year; yearly values are already regular."""
    if observations.shape == "yearly":
        years = observations.index["year"].to_numpy()
        positions = years - years.min()
        series = np.full(positions.max() + 1, np.nan)
        series[positions] = observations.values
        return series, positions, DAYS_OF["year"]
    covers = period_kind(observations) if observations.shape == "dated" else None
    if covers is None:
        raise DataError("a filter needs regular values: each a day, a week, a month or a year (aggregate them first)")
    start = pd.to_datetime(observations.index["start"])
    grid = pd.date_range(start.iloc[0], start.iloc[-1], freq=STEPS_OF[covers])
    where = pd.Index(grid).get_indexer(start)
    if (where < 0).any():
        raise DataError(f"the values do not follow each other by whole {covers}s")
    series = np.full(len(grid), np.nan)
    series[where] = observations.values
    return series, where, DAYS_OF[covers]


def _runs(missing):
    """(first, last + 1) of each run of True."""
    edges = np.diff(np.r_[0, missing.astype(int), 0])
    return list(zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)))


def frequency_filter(observations, step, _others):
    series, positions, sample = regular_series(observations)
    unit = TIME_UNITS[step["unit"]]
    kind = step["type"]
    short, long = float(step["short"]) * unit / sample, float(step["long"]) * unit / sample  # Periods in values
    if kind == "low":
        bounds, btype, periods = 2.0 / long, "lowpass", (long,)
    elif kind == "high":
        bounds, btype, periods = 2.0 / short, "highpass", (short,)
    elif kind == "band":
        if not short < long:
            raise DataError("the shorter period must be shorter than the longer one")
        bounds, btype, periods = [2.0 / long, 2.0 / short], "bandpass", (short, long)
    else:
        raise DataError("choose low, high or band pass")
    if any(period <= 2.0 for period in periods):
        raise DataError(f"a period must be longer than two values ({amount(2 * sample / unit, step['unit'])})")
    sos = signal.butter(FILTER_ORDER, bounds, btype=btype, output="sos")
    # The shortest stretch the filter runs on: longer than the longest period, and than what sosfiltfilt pads with
    shortest = max(int(np.ceil(max(periods))) + 1, 3 * (2 * len(sos) + 1) + 1)
    missing = np.isnan(series)
    working = series.copy()
    filled = []
    method = step.get("missing", "interpolate")
    if method == "interpolate":
        most = int(step.get("max_gap") or 0)
        for first, last in _runs(missing):
            if 0 < first and last < len(series) and last - first <= most:  # Interior gaps only, between two values
                working[first:last] = np.interp(np.arange(first, last), [first - 1, last], [series[first - 1], series[last]])
                filled.append(last - first)
    elif method != "stretches":
        raise DataError("choose how missing values are handled")
    result = np.full(len(series), np.nan)
    stretches, too_short = _runs(~np.isnan(working)), 0
    for first, last in stretches:
        if last - first < shortest:
            too_short += last - first - int(missing[first:last].sum())
            continue
        result[first:last] = signal.sosfiltfilt(sos, working[first:last])
    if np.isnan(result[~missing]).all():
        raise DataError(f"no stretch of the series is long enough for this filter: it needs at least {shortest} values "
                        f"({amount(shortest * sample / unit, step['unit'])}) without a longer gap")
    result[missing] = np.nan  # Interpolated or absent values are not data
    values = result[positions]
    used = sum(1 for first, last in stretches if last - first >= shortest)
    said = []
    if filled:
        said.append(f"{amount(len(filled), 'gaps')} of up to {amount(max(filled), 'values')} interpolated for the filter only, left missing after")
    if used > 1:
        said.append(f"{amount(used, 'stretches').replace('stretche ', 'stretch ')} without gaps filtered separately")
    if too_short:
        said.append(f"{amount(too_short, 'values')} in stretches shorter than {shortest} values left missing")
    longest = float(step["long"]) if kind in ("low", "band") else float(step["short"])
    # The filter starts up at each end of a stretch: measured on a 3 to 8 year band pass of a 5-year cycle, errors fall
    # below 4% of the amplitude only about two of the longest periods kept from each end (tests)
    said.append(f"values within about {amount(2 * longest, step['unit'])} of each end{' of a stretch' if used > 1 else ''} "
                f"are less reliable (the filter starts up there)")
    result_observations = replace(observations, values=values, sd=None, name=f"{kind}-pass {observations.name}")
    for note in said:
        result_observations = result_observations.with_note(note)
    return result_observations


# ---------------------------------------------------------------- combine

def combine_step(observations, step, others):
    other = others.get(step.get("other"))
    if other is None:
        raise DataError(f"no observations {step.get('other')!r} loaded to combine with")
    if step["how"] == "difference":
        negative = replace(other, values=-other.values)
        result = combine(observations, negative, "sum")
        return replace(result, name=f"{observations.name} minus {other.name}")
    return combine(observations, other, step["how"])


STEP_FUNCTIONS = {"aggregate": aggregate, "arithmetic": arithmetic, "select": select, "climatology": climatology,
                  "transform": transform, "filter": frequency_filter, "combine": combine_step}
