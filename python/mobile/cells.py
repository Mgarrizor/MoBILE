"""The size of the cells of the grid, as the model computes it from the population file (cell_bounds in
src/mo_netcdf.f90): from the cell bounds of the coordinates if the file has them (CF `bounds` attribute, e.g.
lat_bnds), else with the edges halfway between the centres and the ends extrapolated, as cdo gridarea does."""

import netCDF4
import numpy as np

from .driving import LAT_NAMES, LON_NAMES, first_name

EARTH_RADIUS = 6371000.0  # m, Re_area in src/mo_const.f90, the radius of cdo gridarea


class CellSizeError(ValueError):
    """A coordinate with a single value and no cell bounds: the size of its cells cannot be known."""


def centre_edges(centres, axis="coordinate"):
    """(lower, upper) edges of the cells of an axis from their centres: halfway between them, the ends extrapolated."""
    centres = np.asarray(centres, dtype="float64")
    if centres.size < 2:
        raise CellSizeError(f"The population file has a single {axis} and no cell bounds: the cell area cannot be known. "
                            "Add the bounds of the coordinate (CF bounds attribute, e.g. lat_bnds, lon_bnds).")
    middle = (centres[1:] + centres[:-1]) / 2
    lower = np.concatenate([[centres[0] - (middle[0] - centres[0])], middle])
    upper = np.concatenate([middle, [centres[-1] + (centres[-1] - middle[-1])]])
    return lower, upper


def axis_edges(data, name, axis):
    """(lower, upper) edges of the cells of coordinate `name` of an open netCDF4 dataset, as the model takes them."""
    variable = data.variables[name]
    if "bounds" in variable.ncattrs():
        bounds = np.asarray(data.variables[variable.getncattr("bounds")][:], dtype="float64")
        return bounds[:, 0], bounds[:, 1]
    return centre_edges(variable[:], axis)


def file_edges(path):
    """{"lat": (lower, upper), "lon": (lower, upper)} of the cells of a population file."""
    with netCDF4.Dataset(path) as data:
        return {"lat": axis_edges(data, first_name(LAT_NAMES, data.variables), "latitude"),
                "lon": axis_edges(data, first_name(LON_NAMES, data.variables), "longitude")}


def cell_areas(path):
    """Area of each cell of a population file in m², (lat, lon) as the file, on a sphere of radius EARTH_RADIUS."""
    edges = file_edges(path)
    (south, north), (west, east) = edges["lat"], edges["lon"]
    band = np.abs(np.sin(np.radians(north)) - np.sin(np.radians(south)))
    return EARTH_RADIUS**2 * band[:, None] * np.abs(np.radians(east - west))[None, :]


def add_bounds(source, target):
    """Give the coordinates of `target`, a population file cut from `source`, the cell bounds of `source`, unless
    they have bounds: a cut of one cell or one row keeps the size of its cells, which its coordinates cannot tell."""
    full = file_edges(source)
    with netCDF4.Dataset(source) as whole, netCDF4.Dataset(target, "a") as cut:
        for axis, names in (("lat", LAT_NAMES), ("lon", LON_NAMES)):
            name = first_name(names, cut.variables)
            variable = cut.variables[name]
            if "bounds" in variable.ncattrs():
                continue
            centres = np.asarray(whole.variables[first_name(names, whole.variables)][:], dtype="float64")
            kept = np.abs(np.asarray(variable[:], dtype="float64")[:, None] - centres[None, :]).argmin(axis=1)
            if "bnds" not in cut.dimensions:
                cut.createDimension("bnds", 2)
            bounds = cut.createVariable(f"{axis}_bnds", "f8", (variable.dimensions[0], "bnds"))
            bounds[:] = np.stack([full[axis][0][kept], full[axis][1][kept]], axis=1)
            variable.setncattr("bounds", f"{axis}_bnds")
