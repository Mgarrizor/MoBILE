"""A part of the grid to simulate, a box of latitudes and longitudes, and the driving files cut to it.

The model takes its grid from the population file, so a run on a region is a run on copies of the
gridded driving files that hold only the cells of the region.
"""

from pathlib import Path

import netCDF4
import numpy as np

from .cells import add_bounds
from .driving import LAT_NAMES, LON_NAMES, TIME_NAMES

# In the order of the Copernicus data store
REGION_KEYS = ("north", "west", "south", "east")
# The driving files on the grid of the population file
GRIDDED_INPUTS = ("rain_file", "temp_file", "pop_file", "imm_forcing")
# The driving files with a day to a step in time
DAILY_INPUTS = ("rain_file", "temp_file", "imm_forcing")


def region_problems(region):
    """What is wrong with a region, as a list; a region is None (the whole grid) or {north, west, south, east}."""
    if region is None:
        return []
    if not isinstance(region, dict) or set(region) != set(REGION_KEYS):
        return [f"region: needs {', '.join(REGION_KEYS)} and nothing else"]
    if not all(isinstance(region[key], (int, float)) and not isinstance(region[key], bool) and np.isfinite(region[key])
               for key in REGION_KEYS):
        return ["region: north, west, south and east must be numbers"]
    problems = []
    if not -90 <= region["south"] <= region["north"] <= 90:
        problems.append("region: south must not be above north, and both between -90 and 90")
    if not -180 <= region["west"] <= region["east"] <= 360:
        problems.append("region: west must not be east of east, and both between -180 and 360")
    return problems


def axis_range(coords, low, high):
    """(first, last + 1) of the cells of one axis between low and high: those with their centre in it, or else,
    for a point or a range narrower than a cell, the cell nearest its middle. None if it misses the grid."""
    coords = np.asarray(coords, dtype="float64")
    inside = np.flatnonzero((coords >= low) & (coords <= high))
    if inside.size:
        return int(inside.min()), int(inside.max()) + 1
    half = abs(coords[1] - coords[0]) / 2 if coords.size > 1 else 0.5
    if high < coords.min() - half or low > coords.max() + half:
        return None
    nearest = int(np.argmin(np.abs(coords - (low + high) / 2)))
    return nearest, nearest + 1


def region_ranges(lon, lat, region):
    """(lon range, lat range) of a region as index ranges of the grid, or None if it misses the grid."""
    if region is None:
        return (0, len(lon)), (0, len(lat))
    lon_range = axis_range(lon, region["west"], region["east"])
    lat_range = axis_range(lat, region["south"], region["north"])
    return None if lon_range is None or lat_range is None else (lon_range, lat_range)


def _axis_name(names, available):
    return next(name for name in names if name in available)


def cut_file(source, target, lon_limits, lat_limits, steps=None):
    """Copy a netCDF file with only the cells whose coordinates are within the limits (None: all) and, if
    `steps` is (first, last), only those steps in time, keeping its format, attributes, fill values and types
    as they are. Returns the number of (lon, lat) cells kept."""
    with netCDF4.Dataset(source) as data, netCDF4.Dataset(target, "w", format=data.data_model) as cut:
        data.set_auto_maskandscale(False)
        lon_dim, lat_dim = _axis_name(LON_NAMES, data.dimensions), _axis_name(LAT_NAMES, data.dimensions)
        keep = {}
        for dim, limits in ((lon_dim, lon_limits), (lat_dim, lat_limits)):
            coords = np.asarray(data.variables[dim][:], dtype="float64")
            if limits is None:
                keep[dim] = np.arange(coords.size)
                continue
            # The files of a grid can differ in the last digits of their coordinates
            tolerance = abs(coords[1] - coords[0]) / 4 if coords.size > 1 else 1e-6
            keep[dim] = np.flatnonzero((coords >= limits[0] - tolerance) & (coords <= limits[1] + tolerance))
        time_dim = next((name for name in TIME_NAMES if name in data.dimensions), None)
        if steps is not None and time_dim is not None:
            if steps[1] >= len(data.dimensions[time_dim]):
                raise ValueError(f"{Path(source).name} has fewer days than the period needs")
            keep[time_dim] = np.arange(steps[0], steps[1] + 1)
        cut.setncatts({name: data.getncattr(name) for name in data.ncattrs()})
        for name, dim in data.dimensions.items():
            cut.createDimension(name, None if dim.isunlimited() else len(keep.get(name, range(len(dim)))))
        for name, variable in data.variables.items():
            attributes = {key: variable.getncattr(key) for key in variable.ncattrs()}
            fill = attributes.pop("_FillValue", None)
            copy = cut.createVariable(name, variable.datatype, variable.dimensions, fill_value=fill)
            copy.set_auto_maskandscale(False)
            copy.setncatts(attributes)
            values = variable[:]
            for axis, dim in enumerate(variable.dimensions):
                if dim in keep:
                    values = np.take(values, keep[dim], axis=axis)
            copy[:] = values
        return len(keep[lon_dim]), len(keep[lat_dim])


def cut_inputs(inputs, region, folder, pop_grid, steps=None):
    """Copies of the driving files cut to a region and, if `steps` is (first, last), to those steps in
    time, in folder: {key: path}. Without a region, only the files with time are copied. The cut population
    file gets the cell bounds of the whole grid, from which the model computes the cell areas.

    pop_grid is (lon, lat) of the population file, on which the region is chosen. Raises ValueError if a
    file is not on that grid.
    """
    limits = (None, None)
    expected = None
    if region is not None:
        ranges = region_ranges(*pop_grid, region)
        if ranges is None:
            raise ValueError("the region is outside the grid of the population file")
        (lon_first, lon_end), (lat_first, lat_end) = ranges
        lon, lat = (np.asarray(axis, dtype="float64") for axis in pop_grid)
        lon_kept, lat_kept = np.sort(lon[lon_first:lon_end]), np.sort(lat[lat_first:lat_end])
        limits = ((lon_kept[0], lon_kept[-1]), (lat_kept[0], lat_kept[-1]))
        expected = (len(lon_kept), len(lat_kept))
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    paths = {}
    for key in GRIDDED_INPUTS if region is not None else DAILY_INPUTS:
        source = inputs.get(key, "NONE")
        if source == "NONE":
            continue
        target = folder / f"{key}.nc"
        cells = cut_file(source, target, *limits, steps=steps if key in DAILY_INPUTS else None)
        if expected is not None and cells != expected:
            raise ValueError(f"{Path(source).name} is not on the grid of the population file")
        if key == "pop_file":
            add_bounds(source, target)  # The model computes the cell areas from them
        paths[key] = str(target)
    return paths
