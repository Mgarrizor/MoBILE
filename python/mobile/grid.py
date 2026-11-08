"""The fixed grid of the driving data."""

import numpy as np
import xarray as xr

from .cells import cell_areas
from .driving import FIELD_NAMES, LAT_NAMES, LON_NAMES, POP_NAMES, TIME_NAMES, first_name
from .region import region_ranges


def load_grid(config):
    """Coordinates, simulated cells and total population of the grid of a run: the fixed grid, or its region."""
    return read_grid(config.inputs["pop_file"], config.region, config.inputs["rain_file"], config.inputs["temp_file"])


def first_day(path, key):
    """The first day of a rainfall or temperature file, (lat, lon) as the population file: what the model masks with."""
    with xr.open_dataset(path) as data:
        field = data[first_name(FIELD_NAMES[key], data.data_vars)]
        time = next((name for name in TIME_NAMES if name in field.dims), None)
        return (field.isel({time: 0}) if time else field).values


def read_grid(pop_file, region=None, rain_file=None, temp_file=None):
    """As load_grid, from the files; None if the region misses the grid. `full` is (lon, lat) of the whole grid.

    `mask` is the populated cells. With the rainfall and temperature files, `simulated` is the number of cells the
    model simulates, those with population and with rain and temperature on the first day, and `people` the people in
    them, with the cell areas the model computes (cells.py). Raises CellSizeError if the population file has a
    single latitude or longitude and no cell bounds."""
    with xr.open_dataset(pop_file) as pop_data:
        pop = pop_data[first_name(POP_NAMES, pop_data.variables)].values
        lat = pop_data[first_name(LAT_NAMES, pop_data.variables)].values
        lon = pop_data[first_name(LON_NAMES, pop_data.variables)].values
    ranges = region_ranges(lon, lat, region)
    if ranges is None:
        return None
    (lon_first, lon_end), (lat_first, lat_end) = ranges
    cells = (slice(lat_first, lat_end), slice(lon_first, lon_end))
    populated = np.isfinite(pop) & (np.nan_to_num(pop) > 0)
    grid = {"lat": lat[cells[0]], "lon": lon[cells[1]], "mask": np.isfinite(pop[cells]), "populated": int(populated[cells].sum()),
            "full": (lon, lat)}
    if rain_file is not None and temp_file is not None:
        simulated = populated & np.isfinite(first_day(rain_file, "rain_file")) & np.isfinite(first_day(temp_file, "temp_file"))
        people = np.where(simulated, np.nan_to_num(pop).astype("float64") * cell_areas(pop_file), 0.0)
        grid["simulated"] = int(simulated[cells].sum())
        grid["people"] = float(people[cells].sum())
    return grid


def pop_coordinates(pop_file):
    """(lon, lat) of the population file, on which a region is chosen."""
    with xr.open_dataset(pop_file) as pop_data:
        return pop_data[first_name(LON_NAMES, pop_data.variables)].values, pop_data[first_name(LAT_NAMES, pop_data.variables)].values


def extent_key(lon, lat):
    """What a basemap is made for: the size and corners of a grid."""
    return (len(lon), len(lat), float(lon[0]), float(lon[-1]), float(lat[0]), float(lat[-1]))


def mask_like(data, grid):
    """The simulated cells on the coordinates of the output."""
    mask = xr.DataArray(grid["mask"], dims=("lat", "lon"), coords={"lat": grid["lat"], "lon": grid["lon"]})
    return mask.reindex(lat=data["lat"], lon=data["lon"], method="nearest")
