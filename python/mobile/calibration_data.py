"""Observations to calibrate the model against: read from the standard netCDF file or imported from a table (CSV
or text), checked, processed, and written back to the standard file.

Calibration data is often not a dated series, so each set of observations says what its values are, its *shape*:

- ``dated``: values over periods of time, each with its first and last day (e.g. monthly cases);
- ``climatology``: one value per calendar month (1 to 12), e.g. the mean EIR of each month over several years;
- ``season``: one value per season, DJF, MAM, JJA and SON (1 to 4), e.g. the mean cases of each season;
- ``yearly``: one value per year;
- ``age``: one value per age band, from its first year of age to its last (None for an open band, e.g. 60 and over);
- ``single``: one value, e.g. the mean annual EIR.

Each also says how its values aggregate (``sum`` for counts, ``mean`` for rates and prevalences) and their units, and
may carry an uncertainty (``sd``) and other columns (e.g. the population ``N``), which processing can use.

The standard file is netCDF with a dimension ``obs``, the variable ``value`` (with ``units``, ``long_name`` and
``cell_methods``), the coordinates of the shape (``time`` with ``time_bnds`` for dated values, as in CF; ``month``;
``season``; ``year``; ``age_lower`` and ``age_upper``) and the global attribute ``mobile_shape``; the processing steps
that made it are in the global attribute ``mobile_steps`` (JSON, see calibration_steps.py).
"""

import csv
import io
import json
from dataclasses import dataclass, field, replace
from pathlib import Path

import netCDF4
import numpy as np
import pandas as pd

SHAPES = {
    "dated": "Dated: values over periods of time (e.g. monthly cases)",
    "climatology": "Climatology: one value per calendar month",
    "season": "Seasonal climatology: one value per season (DJF, MAM, JJA, SON)",
    "yearly": "Yearly: one value per year",
    "age": "Age profile: one value per age band",
    "single": "Single value",
}
AGGREGATIONS = {"sum": "Sum (counts, e.g. cases)", "mean": "Mean (rates, prevalences)"}
# Periods a single date stands for in a dated table: the period that contains it
PERIODS = {"day": "D", "week": "W", "month": "M", "year": "Y"}
SEASONS = ("DJF", "MAM", "JJA", "SON")  # Season 1 to 4; December belongs to the DJF of the next year
NA_VALUES = ["NA", "NaN", "nan", "", "-", "NULL", "null", "-999", "-9999"]
SEPARATORS = (",", ";", "\t")


class DataError(ValueError):
    """A table or file that cannot give observations, with what is wrong."""


@dataclass(frozen=True)
class Observations:
    """A set of observations. ``index`` holds the coordinates of the shape, one row per value: ``start`` and ``end``
    (datetime64[D], both included) for dated values, ``month``, ``year``, or ``age_lower`` and ``age_upper``."""
    shape: str
    values: np.ndarray
    index: pd.DataFrame
    aggregation: str = "sum"
    units: str = ""
    name: str = "value"
    sd: np.ndarray | None = None
    extra: dict = field(default_factory=dict)  # {column: values}, e.g. the population N
    notes: tuple = ()  # What was done on import or processing, for the user
    source: str = ""
    steps: tuple = ()  # The processing steps applied, as dicts (calibration_steps.py)

    def __len__(self):
        return len(self.values)

    def with_note(self, note):
        return replace(self, notes=(*self.notes, note))

    def frame(self):
        """A table of the observations: the coordinates, value, sd and the other columns."""
        table = self.index.copy()
        table[self.name] = self.values
        if self.sd is not None:
            table["sd"] = self.sd
        for column, values in self.extra.items():
            table[column] = values
        return table

    def label(self, i):
        """e.g. '1990-01', '1990-01-01 to 1990-01-07', 'Jan', '1995', '5-9', '60+'."""
        row = self.index.iloc[i]
        if self.shape == "dated":
            start, end = pd.Timestamp(row["start"]), pd.Timestamp(row["end"])
            if start.day == 1 and end == start + pd.offsets.MonthEnd(0):
                return start.strftime("%Y-%m")
            if start.month == 1 and start.day == 1 and end == start + pd.offsets.YearEnd(0):
                return start.strftime("%Y")
            if start.day == 1 and end == end + pd.offsets.MonthEnd(0):  # Whole months, e.g. a season or a quarter
                return f"{start:%Y-%m} to {end:%Y-%m}"
            return start.strftime("%Y-%m-%d") if start == end else f"{start:%Y-%m-%d} to {end:%Y-%m-%d}"
        if self.shape == "climatology":
            return pd.Timestamp(2000, int(row["month"]), 1).strftime("%b")
        if self.shape == "season":
            return SEASONS[int(row["season"]) - 1]
        if self.shape == "yearly":
            return str(int(row["year"]))
        if self.shape == "age":
            upper = row["age_upper"]
            return f"{int(row['age_lower'])}+" if pd.isna(upper) else f"{int(row['age_lower'])}-{int(upper)}"
        return self.name


# ---------------------------------------------------------------- reading tables

def read_table(path_or_text, nrows=None):
    """A table from a CSV or text file (or its text), separator found by itself: comma, semicolon, tab or blanks.
    Tables written by R, with row names and one header less than the columns, are read with the row names as index."""
    text = Path(path_or_text).read_text() if not isinstance(path_or_text, str) or "\n" not in path_or_text else path_or_text
    lines = [line for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]
    if not lines:
        raise DataError("the table is empty")
    sample = "\n".join(lines[:20])
    counts = {sep: [line.count(sep) for line in lines[:20]] for sep in SEPARATORS}
    separator = next((sep for sep, n in counts.items() if min(n) > 0 and len(set(n)) <= 2), None)
    try:
        if separator is None:
            table = pd.read_csv(io.StringIO("\n".join(lines)), sep=r"\s+", na_values=NA_VALUES, nrows=nrows)
        else:
            dialect = csv.Sniffer().sniff(sample, delimiters=separator)
            table = pd.read_csv(io.StringIO("\n".join(lines)), sep=dialect.delimiter, na_values=NA_VALUES, nrows=nrows, skipinitialspace=True)
    except (pd.errors.ParserError, csv.Error, ValueError) as error:
        raise DataError(f"the table cannot be read: {error}") from None
    table.columns = [str(column).strip().strip('"').strip("'") for column in table.columns]
    return table


def numbers(table, column):
    """A column as floats; text that is not a number, other than the usual missing-value codes, is an error."""
    values = pd.to_numeric(table[column], errors="coerce")
    bad = table[column][values.isna() & table[column].notna()]
    if len(bad):
        raise DataError(f"column {column!r} has values that are not numbers, e.g. {bad.iloc[0]!r} (row {bad.index[0]})")
    return values.to_numpy(dtype="float64")


# ---------------------------------------------------------------- importing tables

def import_table(table, shape, value, aggregation, units, *, date=None, period="month", start=None, end=None, month=None,
                 season=None, year=None, age_lower=None, age_upper=None, sd=None, extra=(), source=""):
    """Observations from a table (a DataFrame) and what its columns are. The minimum: the shape, the column of values,
    how they aggregate, their units and the columns of the shape: for dated values a date column with the period each
    date stands for (the period that contains it: a mid-month date is that month), or start and end columns; month
    (1 to 12) for a climatology; year; age_lower and age_upper (empty for an open band); none for a single value.

    Rows repeated exactly are kept once, and said so; rows for the same period with different values are an error.
    Rows are sorted by their coordinates."""
    if shape not in SHAPES:
        raise DataError(f"shape must be one of {', '.join(SHAPES)}")
    if aggregation not in AGGREGATIONS:
        raise DataError("aggregation must be sum or mean")
    if not str(units).strip():
        raise DataError("units are needed, e.g. cases, cases per person, bites per person per day")
    for column in (value, date, start, end, month, season, year, age_lower, age_upper, sd, *extra):
        if column is not None and column not in table.columns:
            raise DataError(f"no column {column!r}; the columns are {', '.join(map(str, table.columns))}")
    index = _shape_index(table, shape, date=date, period=period, start=start, end=end, month=month, season=season, year=year,
                         age_lower=age_lower, age_upper=age_upper)
    data = index.copy()
    data["__value"] = numbers(table, value)
    if sd is not None:
        data["__sd"] = numbers(table, sd)
    for column in extra:
        data[f"__extra_{column}"] = numbers(table, column)
    keys = list(index.columns)
    notes = []
    if keys:
        repeated = data.duplicated(keep="first")
        if repeated.any():
            notes.append(f"in the file: {int(repeated.sum())} rows repeated exactly, kept once")
            data = data[~repeated]
        clash = data.duplicated(subset=keys, keep=False)
        if clash.any():
            first = data[clash].iloc[0]
            raise DataError(f"{int(clash.sum())} rows give different values for the same {', '.join(keys)}, "
                            f"e.g. {', '.join(f'{k}={first[k]}' for k in keys)}")
        data = data.sort_values(keys).reset_index(drop=True)
        if shape == "dated":
            overlap = (data["start"].to_numpy()[1:] <= data["end"].to_numpy()[:-1])
            if overlap.any():
                i = int(np.argmax(overlap))
                raise DataError(f"periods overlap: {data['start'].iloc[i].date()} to {data['end'].iloc[i].date()} and "
                                f"{data['start'].iloc[i + 1].date()} to {data['end'].iloc[i + 1].date()}")
    elif len(data) != 1:
        raise DataError(f"a single value needs one row, the table has {len(data)}")
    missing = int(np.isnan(data["__value"]).sum())
    if missing:
        notes.append(f"in the file: {missing} values missing")
    observations = Observations(
        shape=shape, values=data["__value"].to_numpy(), index=data[keys].reset_index(drop=True), aggregation=aggregation,
        units=str(units).strip(), name=str(value), sd=data["__sd"].to_numpy() if sd is not None else None,
        extra={column: data[f"__extra_{column}"].to_numpy() for column in extra}, notes=tuple(notes), source=str(source),
    )
    if shape == "dated":
        gaps = dated_gaps(observations)
        if gaps:
            observations = observations.with_note(f"in the file: {len(gaps)} gaps between periods, e.g. {gaps[0][0]} to {gaps[0][1]}")
    return observations


def _dates(table, column):
    days = pd.to_datetime(table[column], errors="coerce")
    bad = table[column][days.isna()]
    if len(bad):
        raise DataError(f"column {column!r} has values that are not dates, e.g. {bad.iloc[0]!r} (row {bad.index[0]})")
    return days.dt.normalize()


def _shape_index(table, shape, *, date, period, start, end, month, season, year, age_lower, age_upper):
    def needs(**columns):
        missing = [name for name, column in columns.items() if column is None]
        if missing:
            raise DataError(f"{SHAPES[shape].split(':')[0]} values need the column{'s' if len(missing) > 1 else ''} {' and '.join(missing)}")
    if shape == "dated":
        if start is not None or end is not None:
            needs(start=start, end=end)
            first, last = _dates(table, start), _dates(table, end)
            if (last < first).any():
                raise DataError("some periods end before they start")
        else:
            needs(date=date)
            if period not in PERIODS:
                raise DataError(f"period must be one of {', '.join(PERIODS)}")
            stamps = pd.PeriodIndex(_dates(table, date).dt.to_period(PERIODS[period]))
            first, last = stamps.start_time.normalize(), stamps.end_time.normalize()
        return pd.DataFrame({"start": np.asarray(first, dtype="datetime64[D]"), "end": np.asarray(last, dtype="datetime64[D]")})
    if shape == "climatology":
        needs(month=month)
        months = numbers(table, month)
        if not np.all(np.isin(months, np.arange(1, 13))):
            raise DataError("months must be whole numbers from 1 to 12")
        return pd.DataFrame({"month": months.astype(int)})
    if shape == "season":
        needs(season=season)
        names = table[season].astype(str).str.strip().str.upper()
        numbers_ = names.map({name: i + 1 for i, name in enumerate(SEASONS)} | {str(i): i for i in range(1, 5)} | {f"{i}.0": i for i in range(1, 5)})
        if numbers_.isna().any():
            raise DataError(f"seasons must be DJF, MAM, JJA, SON or 1 to 4, e.g. not {table[season][numbers_.isna()].iloc[0]!r}")
        return pd.DataFrame({"season": numbers_.to_numpy().astype(int)})
    if shape == "yearly":
        needs(year=year)
        years = numbers(table, year)
        if np.isnan(years).any() or not np.all(years == np.round(years)):
            raise DataError("years must be whole numbers")
        return pd.DataFrame({"year": years.astype(int)})
    if shape == "age":
        needs(age_lower=age_lower)
        lower = numbers(table, age_lower)
        upper = numbers(table, age_upper) if age_upper is not None else np.full(len(lower), np.nan)
        if np.isnan(lower).any() or np.any(upper[~np.isnan(upper)] < lower[~np.isnan(upper)]):
            raise DataError("age bands need a first year of age, not above their last")
        return pd.DataFrame({"age_lower": lower, "age_upper": upper})
    return pd.DataFrame(index=range(len(table)))


def period_kind(observations):
    """What each dated value covers, if the same for all: day, week (7 days), month or year (calendar), else None."""
    start = pd.to_datetime(observations.index["start"])
    end = pd.to_datetime(observations.index["end"])
    days = (end - start).dt.days + 1
    if (days == 1).all():
        return "day"
    if (days == 7).all():
        return "week"
    if ((start.dt.day == 1) & (end == start + pd.offsets.MonthEnd(0))).all():
        return "month"
    if ((start.dt.dayofyear == 1) & (end == start + pd.offsets.YearEnd(0))).all():
        return "year"
    return None


def dated_gaps(observations):
    """(first, last) days between consecutive periods of dated observations that no period covers."""
    starts = observations.index["start"].to_numpy().astype("datetime64[D]")
    ends = observations.index["end"].to_numpy().astype("datetime64[D]")
    one = np.timedelta64(1, "D")
    return [(str(ends[i] + one), str(starts[i + 1] - one)) for i in range(len(starts) - 1) if starts[i + 1] > ends[i] + one]


# ---------------------------------------------------------------- the standard netCDF file

def write_observations(observations, path):
    """Write observations to the standard netCDF file."""
    with netCDF4.Dataset(path, "w") as data:
        data.mobile_shape = observations.shape
        data.source = observations.source
        data.notes = "; ".join(observations.notes)
        data.mobile_steps = json.dumps(list(observations.steps))
        data.createDimension("obs", len(observations))
        index = observations.index
        if observations.shape == "dated":
            data.createDimension("nv", 2)
            days = np.stack([index["start"].to_numpy(), index["end"].to_numpy()], axis=1).astype("datetime64[D]")
            epoch = np.datetime64("1900-01-01", "D")
            bounds = data.createVariable("time_bnds", "f8", ("obs", "nv"))
            # CF bounds: from the start of the first day to the end of the last, in days
            bounds[:] = np.stack([(days[:, 0] - epoch).astype(float), (days[:, 1] - epoch).astype(float) + 1.0], axis=1)
            time = data.createVariable("time", "f8", ("obs",))
            time[:] = bounds[:].mean(axis=1)
            time.units, time.calendar, time.bounds, time.standard_name = "days since 1900-01-01", "proleptic_gregorian", "time_bnds", "time"
        for column, kind in (("month", "i4"), ("season", "i4"), ("year", "i4"), ("age_lower", "f8"), ("age_upper", "f8")):
            if column in index.columns:
                variable = data.createVariable(column, kind, ("obs",), fill_value=np.nan if kind == "f8" else None)
                variable[:] = index[column].to_numpy()
        value = data.createVariable("value", "f8", ("obs",), fill_value=np.nan)
        value[:] = observations.values
        value.units, value.long_name = observations.units, observations.name
        value.cell_methods = f"{'time' if observations.shape in ('dated', 'climatology', 'season', 'yearly') else 'area'}: {observations.aggregation}"
        if observations.sd is not None:
            sd = data.createVariable("sd", "f8", ("obs",), fill_value=np.nan)
            sd[:] = observations.sd
            sd.units, sd.long_name = observations.units, f"standard deviation of {observations.name}"
        for column, values in observations.extra.items():
            variable = data.createVariable(f"extra_{column}", "f8", ("obs",), fill_value=np.nan)
            variable[:] = values
            variable.long_name = column


def read_observations(path):
    """Observations from the standard netCDF file. Raises DataError if it is not one."""
    try:
        with netCDF4.Dataset(path) as data:
            shape = getattr(data, "mobile_shape", None)
            if shape not in SHAPES:
                raise DataError(f"{Path(path).name} is not a file of observations: it has no mobile_shape attribute "
                                f"({', '.join(SHAPES)}); import it as a table instead")
            value = data["value"]
            method = getattr(value, "cell_methods", ": sum").split(":")[-1].strip()
            index = pd.DataFrame(index=range(len(data.dimensions["obs"])))
            if shape == "dated":
                epoch = np.datetime64("1900-01-01", "D")
                bounds = np.asarray(data["time_bnds"][:], dtype="float64")
                index["start"] = epoch + np.round(bounds[:, 0]).astype("int64").astype("timedelta64[D]")
                index["end"] = epoch + np.round(bounds[:, 1] - 1).astype("int64").astype("timedelta64[D]")
            for column in ("month", "season", "year", "age_lower", "age_upper"):
                if column in data.variables:
                    index[column] = np.ma.filled(data[column][:], np.nan) if column.startswith("age") else np.asarray(data[column][:])
            extra = {name[len("extra_"):]: np.ma.filled(data[name][:].astype("f8"), np.nan) for name in data.variables if name.startswith("extra_")}
            notes = tuple(note for note in getattr(data, "notes", "").split("; ") if note)
            steps = tuple(json.loads(getattr(data, "mobile_steps", "[]")))
            return Observations(
                shape=shape, values=np.ma.filled(value[:].astype("f8"), np.nan), index=index, aggregation=method,
                units=getattr(value, "units", ""), name=getattr(value, "long_name", "value"),
                sd=np.ma.filled(data["sd"][:].astype("f8"), np.nan) if "sd" in data.variables else None,
                extra=extra, notes=notes, source=getattr(data, "source", str(path)), steps=steps,
            )
    except (OSError, KeyError, IndexError, ValueError) as error:
        if isinstance(error, DataError):
            raise
        raise DataError(f"{Path(path).name} cannot be read as observations: {error}") from None


# ---------------------------------------------------------------- processing

def select_window(observations, first=None, last=None):
    """The dated observations whose periods are within first and last (dates, both included), or the yearly ones
    within those years."""
    if observations.shape == "dated":
        keep = np.ones(len(observations), dtype=bool)
        if first is not None:
            keep &= observations.index["start"].to_numpy() >= np.datetime64(pd.Timestamp(first).date(), "D")
        if last is not None:
            keep &= observations.index["end"].to_numpy() <= np.datetime64(pd.Timestamp(last).date(), "D")
    elif observations.shape == "yearly":
        years = observations.index["year"].to_numpy()
        keep = (years >= (pd.Timestamp(first).year if first is not None else -np.inf)) & (years <= (pd.Timestamp(last).year if last is not None else np.inf))
    else:
        raise DataError("only dated or yearly observations have a window in time")
    if not keep.any():
        raise DataError("no observations within the window")
    if keep.all():
        return observations
    return _subset(observations, keep).with_note(f"window {first or 'start'} to {last or 'end'}: {int(keep.sum())} values")


def _subset(observations, keep):
    return replace(
        observations, values=observations.values[keep], index=observations.index[keep].reset_index(drop=True),
        sd=observations.sd[keep] if observations.sd is not None else None,
        extra={column: values[keep] for column, values in observations.extra.items()},
    )


def combine(first, second, how="sum"):
    """Two sets of observations with the same coordinates and units, added or averaged value by value (e.g. EIR of
    two vector species, or two arms of a trial)."""
    if how not in ("sum", "mean"):
        raise DataError("observations are combined by sum or mean")
    if first.shape != second.shape or not first.index.equals(second.index):
        raise DataError("observations can only be combined if they have the same shape and the same coordinates")
    if first.units != second.units:
        raise DataError(f"observations in different units cannot be combined: {first.units} and {second.units}")
    values = first.values + second.values
    sd = None
    if first.sd is not None and second.sd is not None:
        sd = np.sqrt(first.sd**2 + second.sd**2)  # Independent errors of a sum
    if how == "mean":
        values, sd = values / 2, sd / 2 if sd is not None else None
    return replace(first, values=values, sd=sd, extra={}, name=f"{how} of {first.name} and {second.name}",
                   notes=(*first.notes, f"{how} with {second.source or second.name}"))
