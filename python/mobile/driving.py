"""The driving files of a run, read for their preview in the Setup panel, with the names of variables and
coordinates the model accepts (mo_control.f90)."""

import numpy as np
import xarray as xr

POP_NAMES = ["pop", "population", "population density", "Band1"]
RAIN_NAMES = ["rain", "rainfall", "precipitation", "tp", "precip"]
TEMP_NAMES = ["temperature", "t2m"]
LAT_NAMES = ["lat", "latitude", "Y"]
LON_NAMES = ["lon", "longitude", "X"]
TIME_NAMES = ["time", "valid_time"]
FIELD_NAMES = {"rain_file": RAIN_NAMES, "temp_file": TEMP_NAMES, "pop_file": POP_NAMES}
SAMPLE_DAYS = 100  # Days read for the colour range of a field


def first_name(names, available):
    return next(name for name in names if name in available)


def open_field(path, key):
    """The field of a driving file, on coordinates named lat, lon and, if it changes over time, time,
    in increasing order. Read lazily: a day at a time is enough for a map."""
    data = xr.open_dataset(path)
    names = FIELD_NAMES[key]
    try:
        name = first_name(names, data.data_vars)
    except StopIteration:
        raise ValueError(f"no variable named {', '.join(names)}") from None
    renames = {first_name(LAT_NAMES, data.variables): "lat", first_name(LON_NAMES, data.variables): "lon"}
    time = next((name for name in TIME_NAMES if name in data.dims), None)
    if time:
        renames[time] = "time"
    field = data[name].rename(renames)
    # A field that does not change, as population density, may have a time of one step
    if "time" in field.dims and field.sizes["time"] == 1:
        field = field.isel(time=0, drop=True)
    for axis in ("lat", "lon"):
        if not field.indexes[axis].is_monotonic_increasing:
            field = field.sortby(axis)
    # The size of the cells, which a single coordinate cannot tell: for the maps (plots.cell_size)
    from .cells import cell_steps  # Not at the top: cells imports this module
    try:
        field.attrs["cell_steps"] = cell_steps(path)
    except (OSError, ValueError, KeyError, StopIteration, RuntimeError):
        pass
    return field


def climatology(path, key, start=None, end=None, months=None):
    """The mean over time of the field of a daily driving file, cell by cell: over its days from start to end
    (dates, both included; all of them by default), and only those of the calendar months given (1 to 12), as
    (6, 7, 8) for June to August.
    Keeps the attributes of the field, as its units."""
    field = open_field(path, key)
    if "time" not in field.dims:
        raise ValueError("the file has no days")
    if not np.issubdtype(field["time"].dtype, np.datetime64):
        raise ValueError("the dates of the file cannot be read")
    field = field.sel(time=slice(None if start is None else str(start), None if end is None else str(end)))
    if months is not None:
        field = field.isel(time=np.isin(field["time"].dt.month.values, months))
    if field.sizes["time"] == 0:
        raise ValueError("no days in the period" + ("" if months is None else " for these months"))
    mean = field.mean("time", keep_attrs=True).load()
    mean.attrs["days"] = field.sizes["time"]
    return mean


def sample_days(field):
    """At most SAMPLE_DAYS days of a field, spread over the file."""
    if "time" in field.dims and field.sizes["time"] > SAMPLE_DAYS:
        return field.isel(time=np.unique(np.linspace(0, field.sizes["time"] - 1, SAMPLE_DAYS).round().astype(int)))
    return field


def field_limits(field, log=False):
    """Colour range of a field, fixed over its days: its 1st and 99th percentiles, from at most SAMPLE_DAYS
    days spread over the file. On a log scale, from the positive values only."""
    values = np.asarray(sample_days(field).values, dtype="float64")
    values = values[np.isfinite(values)]
    if log:
        values = values[values > 0]
    if values.size == 0:
        return (0.001, 1.0) if log else (0.0, 1.0)
    lowest, highest = (float(value) for value in np.quantile(values, [0.01, 0.99]))
    if highest <= lowest:
        highest = lowest * 10 if log else lowest + 1.0
    return lowest, highest


def mean_age(ages, fraction):
    """Mean age in years, the people at a year of age being on average half a year older."""
    return float(np.sum((ages + 0.5) * fraction) / np.sum(fraction))
