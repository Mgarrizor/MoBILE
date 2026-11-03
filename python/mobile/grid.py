"""The fixed grid of the driving data."""

import numpy as np
import xarray as xr

from .driving import LAT_NAMES, LON_NAMES, POP_NAMES, first_name


def load_grid(config):
    """Coordinates, simulated cells and total population of the fixed grid."""
    with xr.open_dataset(config.inputs["pop_file"]) as pop_data, xr.open_dataset(config.inputs["area_file"]) as area:
        pop = pop_data[first_name(POP_NAMES, pop_data.variables)]
        lat = pop_data[first_name(LAT_NAMES, pop_data.variables)].values
        lon = pop_data[first_name(LON_NAMES, pop_data.variables)].values
        people = float((pop.values * area["cell_area"].values).astype("float64")[np.isfinite(pop.values)].sum())
        return {"lat": lat, "lon": lon, "mask": np.isfinite(pop.values), "people": people}


def extent_key(lon, lat):
    """What a basemap is made for: the size and corners of a grid."""
    return (len(lon), len(lat), float(lon[0]), float(lon[-1]), float(lat[0]), float(lat[-1]))


def mask_like(data, grid):
    """The simulated cells on the coordinates of the output."""
    mask = xr.DataArray(grid["mask"], dims=("lat", "lon"), coords={"lat": grid["lat"], "lon": grid["lon"]})
    return mask.reindex(lat=data["lat"], lon=data["lon"], method="nearest")
