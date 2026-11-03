"""The fixed grid of the driving data."""

import numpy as np
import xarray as xr

from .driving import LAT_NAMES, LON_NAMES, POP_NAMES, first_name
from .region import region_ranges


def load_grid(config):
    """Coordinates, simulated cells and total population of the grid of a run: the fixed grid, or its region."""
    return read_grid(config.inputs["pop_file"], config.inputs["area_file"], config.region)


def read_grid(pop_file, area_file, region=None):
    """As load_grid, from the files; None if the region misses the grid. `full` is (lon, lat) of the whole grid."""
    with xr.open_dataset(pop_file) as pop_data, xr.open_dataset(area_file) as area:
        pop = pop_data[first_name(POP_NAMES, pop_data.variables)].values
        lat = pop_data[first_name(LAT_NAMES, pop_data.variables)].values
        lon = pop_data[first_name(LON_NAMES, pop_data.variables)].values
        ranges = region_ranges(lon, lat, region)
        if ranges is None:
            return None
        (lon_first, lon_end), (lat_first, lat_end) = ranges
        cells = (slice(lat_first, lat_end), slice(lon_first, lon_end))
        pop, cell_area = pop[cells], area["cell_area"].values[cells]
        people = float((pop * cell_area).astype("float64")[np.isfinite(pop)].sum())
        populated = int((np.isfinite(pop) & (np.nan_to_num(pop) > 0)).sum())
        return {"lat": lat[cells[0]], "lon": lon[cells[1]], "mask": np.isfinite(pop), "people": people, "populated": populated,
                "full": (lon, lat)}


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
