"""Background of the map: land, lakes, rivers and borders from Natural Earth, relief from ETOPO 2022.

Downloaded on first use and kept in the cache folder. Without a connection there is no basemap,
and the app shows the plain map.
"""

import base64
import hashlib
import io
import json
import math
import os
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

import netCDF4
import numpy as np
import shapefile
from PIL import Image
from shapely.geometry import box, shape
from shapely.validation import make_valid

BASE_URL = "https://naciscdn.org/naturalearth/10m"
LAYERS = {
    "land": ("physical", "ne_10m_land"),
    "lakes": ("physical", "ne_10m_lakes"),
    "rivers": ("physical", "ne_10m_rivers_lake_centerlines"),
    "borders": ("cultural", "ne_10m_admin_0_boundary_lines_land"),
}
ETOPO_URL = "https://coastwatch.pfeg.noaa.gov/erddap/griddap/ETOPO_2022_v1_15s.nc"
TERRAIN_EXAGGERATION = 5.0  # Relief at this scale is too flat to see otherwise
TIMEOUT_SECONDS = 60
PADDING_DEGREES = 2.0  # Around the grid, for zooming out
TERRAIN_SAMPLES = 800  # Elevations across the longer side of the terrain, at most: its resolution, from the size of the area
SHADOW_ALPHA, LIGHT_ALPHA = 0.55, 0.3  # The most a slope darkens or lightens the colours under it


@dataclass(frozen=True)
class Basemap:
    land: list    # SVG paths
    lakes: list   # SVG paths
    rivers: dict  # {"x": [...], "y": [...]}, lines separated by None
    borders: dict  # As rivers


def cache_folder():
    return Path(os.environ.get("MOBILE_CACHE_DIR", Path.home() / ".cache" / "mobile"))


def _download(layer):
    """Path of the zipped shapefile of a layer, downloaded if it is not in the cache."""
    category, name = LAYERS[layer]
    path = cache_folder() / f"{name}.zip"
    if not path.is_file():
        path.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(f"{BASE_URL}/{category}/{name}.zip", timeout=TIMEOUT_SECONDS) as response:
            data = response.read()
        temporary = path.with_suffix(".tmp")
        temporary.write_bytes(data)
        temporary.replace(path)
    return path


def _geometries(layer, area):
    """Geometries of a layer clipped to the area."""
    with zipfile.ZipFile(_download(layer)) as archive:
        name = LAYERS[layer][1]
        reader = shapefile.Reader(
            shp=io.BytesIO(archive.read(f"{name}.shp")),
            shx=io.BytesIO(archive.read(f"{name}.shx")),
            dbf=io.BytesIO(archive.read(f"{name}.dbf")),
        )
        clipped = []
        for record in reader.iterShapes():
            west, south, east, north = record.bbox if record.shapeType != shapefile.NULL else (0, 0, 0, 0)
            if record.shapeType == shapefile.NULL or not area.intersects(box(west, south, east, north)):
                continue
            geometry = make_valid(shape(record.__geo_interface__)).intersection(area)
            if not geometry.is_empty:
                clipped.append(geometry)
        return clipped


def _parts(geometry):
    return getattr(geometry, "geoms", [geometry])


def _paths(geometries, tolerance):
    """Filled areas as SVG paths; holes are rings of the same path."""
    paths = []
    for geometry in geometries:
        for part in _parts(geometry):
            if part.geom_type != "Polygon":
                continue
            part = part.simplify(tolerance)
            rings = [part.exterior, *part.interiors] if not part.is_empty else []
            path = " ".join(
                "M" + " L".join(f"{x:.4f},{y:.4f}" for x, y in ring.coords[:-1]) + " Z" for ring in rings
            )
            if path:
                paths.append(path)
    return paths


def _lines(geometries):
    """Lines at the full resolution of the source, separated by None."""
    x, y = [], []
    for geometry in geometries:
        for part in _parts(geometry):
            if part.geom_type != "LineString":
                continue
            for lon, lat in part.coords:
                x.append(round(lon, 4))
                y.append(round(lat, 4))
            x.append(None)
            y.append(None)
    return {"x": x, "y": y}


def cell_size(lat, lon, single=0.05, known=None):
    """(degrees of latitude, of longitude) of a grid cell. A single coordinate takes its size from known, the (latitude,
    longitude) sizes from the cell bounds of its file (cells.cell_steps), if any; else, a stripe one cell wide takes the
    size of the other direction, as the cells are square; a single cell without bounds, single."""
    known = known or (None, None)
    steps = [abs(float(values[1]) - float(values[0])) if len(values) > 1 else known[i] for i, values in enumerate((lat, lon))]
    fallback = next((step for step in steps if step), single)
    return tuple(step or fallback for step in steps)


def load_basemap(lon, lat):
    """The basemap of a grid, from its coordinates; None if it cannot be obtained."""
    west, east = float(min(lon)) - PADDING_DEGREES, float(max(lon)) + PADDING_DEGREES
    south, north = float(min(lat)) - PADDING_DEGREES, float(max(lat)) + PADDING_DEGREES
    # Filled areas only: a coast with every vertex slows each redraw, and this cannot be seen
    tolerance = cell_size(lat, lon)[1] / 50
    key = hashlib.sha256(f"{west:.3f},{east:.3f},{south:.3f},{north:.3f},{tolerance:.4f}".encode()).hexdigest()[:16]
    cached = cache_folder() / f"basemap_{key}.json"
    try:
        if cached.is_file():
            return Basemap(**json.loads(cached.read_text()))
        area = box(west, south, east, north)
        basemap = Basemap(
            land=_paths(_geometries("land", area), tolerance),
            lakes=_paths(_geometries("lakes", area), tolerance),
            rivers=_lines(_geometries("rivers", area)),
            borders=_lines(_geometries("borders", area)),
        )
        cached.write_text(json.dumps(basemap.__dict__))
        return basemap
    except (OSError, ValueError, zipfile.BadZipFile, shapefile.ShapefileException):
        return None


@dataclass(frozen=True)
class Terrain:
    image: str  # PNG (grey and alpha) as a data URI: the shading of the land lit from the northwest, laid over the map; sea transparent
    west: float
    north: float
    width: float
    height: float


def _hillshade(elevation, lat, spacing):
    """Shading in [0, 1] of a (lat, lon) elevation field in metres, lit from the northwest at 45 degrees."""
    metres_per_degree = 111320.0
    dz_dy, dz_dx = np.gradient(elevation, spacing * metres_per_degree)
    dz_dx = dz_dx / np.maximum(np.cos(np.radians(lat))[:, None], 0.01)
    slope = np.arctan(np.hypot(dz_dx, dz_dy) * TERRAIN_EXAGGERATION)
    aspect = np.arctan2(-dz_dx, dz_dy)  # Downhill direction, clockwise from north, with lat increasing
    sun_azimuth, sun_altitude = np.radians(315.0), np.radians(45.0)
    shade = np.sin(sun_altitude) * np.cos(slope) + np.cos(sun_altitude) * np.sin(slope) * np.cos(sun_azimuth - aspect)
    return np.clip(shade, 0.0, 1.0)


def _shading(elevation, lats, lons, cached=None):
    """The Terrain of an elevation field (lat increasing): a grey and alpha image, black with an alpha growing as the
    ground is shaded below that of flat ground (0.71), white with an alpha as it is lit above it; transparent at sea."""
    shade = _hillshade(np.nan_to_num(elevation), lats, abs(float(lats[1] - lats[0])))
    flat = 0.71  # The shade of flat ground, lit from 45 degrees
    dark = np.clip((flat - shade) / flat, 0.0, 1.0) * SHADOW_ALPHA
    light = np.clip((shade - flat) / (1.0 - flat), 0.0, 1.0) * LIGHT_ALPHA
    grey = np.where(dark >= light, 0, 255).astype("uint8")
    alpha = (np.where(np.nan_to_num(elevation) > 0, np.maximum(dark, light), 0.0) * 255).astype("uint8")
    buffer = io.BytesIO()
    # An image has its first row at the top, so north first
    Image.fromarray(np.stack([grey, alpha], axis=2)[::-1], "LA").save(buffer, format="PNG", optimize=True)
    half_lat, half_lon = abs(float(lats[1] - lats[0])) / 2, abs(float(lons[1] - lons[0])) / 2
    terrain = Terrain(
        image="data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode(),
        west=float(lons[0]) - half_lon, north=float(lats[-1]) + half_lat,
        width=float(lons[-1] - lons[0]) + 2 * half_lon, height=float(lats[-1] - lats[0]) + 2 * half_lat,
    )
    if cached is not None:
        cached.write_text(json.dumps(terrain.__dict__))
    return terrain


def load_terrain(lon, lat, land_colour=None):
    """Shaded relief of a grid and the area around it (PADDING_DEGREES) from ETOPO 2022, as a shading to lay over the map:
    transparent on flat ground and at sea, darker on the slopes facing away from the light, lighter on those facing it;
    None if it cannot be obtained. Its resolution is set by the size of the area (about TERRAIN_SAMPLES across it, at
    most the 15 arc-seconds of the source), so a small area gets as much detail as a large one. land_colour: not used
    (the land keeps its colour under the shading), kept for the callers."""
    west, east = float(min(lon)) - PADDING_DEGREES, float(max(lon)) + PADDING_DEGREES
    south, north = float(min(lat)) - PADDING_DEGREES, float(max(lat)) + PADDING_DEGREES
    stride = max(1, math.ceil(max(east - west, north - south) / (15 / 3600) / TERRAIN_SAMPLES))
    key = hashlib.sha256(f"shade-2,{west:.3f},{east:.3f},{south:.3f},{north:.3f},{stride}".encode()).hexdigest()[:16]
    cached = cache_folder() / f"terrain_{key}.json"
    try:
        if cached.is_file():
            return Terrain(**json.loads(cached.read_text()))
        url = f"{ETOPO_URL}?z%5B({south}):{stride}:({north})%5D%5B({west}):{stride}:({east})%5D"
        with urllib.request.urlopen(url, timeout=TIMEOUT_SECONDS) as response:
            data = response.read()
        with netCDF4.Dataset("terrain", memory=data) as dataset:
            elevation = np.ma.filled(dataset["z"][:].astype("float64"), np.nan)
            lats = dataset["latitude"][:].astype("float64")
            lons = dataset["longitude"][:].astype("float64")
        if lats[0] > lats[-1]:
            elevation, lats = elevation[::-1], lats[::-1]
        return _shading(elevation, lats, lons, cached)
    except (OSError, ValueError, KeyError, IndexError, RuntimeError):
        return None
