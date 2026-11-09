"""Areas of a shapefile, such as districts or villages, in longitude and latitude: read from a shapefile (.shp with its
.shx, .dbf and .prj, or all of them in a .zip), reprojected from the coordinates of its .prj, named by a field of its
table and, optionally, merged by another (e.g. villages into their districts). The model does not use them: the GUI
draws them on its maps.
"""

import io
import zipfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
import pyproj
import shapefile
import shapely
from shapely.geometry import shape
from shapely.validation import make_valid

SHAPE_SUFFIXES = (".shp", ".zip")
PARTS = (".shp", ".shx", ".dbf", ".prj")
LONLAT = pyproj.CRS.from_epsg(4326)
GEOD = pyproj.Geod(ellps="WGS84")
# Merged areas keep holes and pieces of at least this size, in m²: areas that do not quite meet leave slivers between
# them when merged, typically of a few m², far smaller than any real area such as a village (of the order of 0.1 km²)
SLIVER_M2 = 1000.0


class ShapeError(ValueError):
    """The shapefile cannot be read, or used as asked."""


@dataclass(frozen=True)
class Shapes:
    geometries: tuple  # shapely polygons and multipolygons, in degrees of longitude and latitude
    records: tuple     # {field: value} of each, from the table of the shapefile
    fields: tuple      # Names of the fields of the table
    crs: str           # Name of the coordinates of the file, e.g. WGS 84 / UTM zone 37N
    note: str = ""     # Said when the coordinates were assumed, as without a .prj
    converted: bool = False  # Whether the coordinates of the file were converted to longitude and latitude


def _members(path):
    """{suffix: bytes} of the parts of a shapefile, from the .shp and its neighbours or from a .zip with one shapefile."""
    path = Path(path)
    if path.suffix.lower() == ".zip":
        try:
            with zipfile.ZipFile(path) as archive:
                names = [name for name in archive.namelist() if not name.startswith("__MACOSX")]
                shps = [name for name in names if name.lower().endswith(".shp")]
                if len(shps) != 1:
                    raise ShapeError(f"{path.name} holds {len(shps)} shapefiles (.shp): it should hold one")
                stem = shps[0][:-4]
                return {suffix: archive.read(name) for suffix in PARTS for name in names if name.lower() == (stem + suffix).lower()}
        except zipfile.BadZipFile as error:
            raise ShapeError(f"{path.name} is not a zip file that can be read") from error
    if path.suffix.lower() != ".shp":
        raise ShapeError(f"{path.name}: choose the .shp of the shapefile, or a .zip holding it")
    found = {}
    for suffix in PARTS:
        # The parts may be named in either case, e.g. .SHP with .dbf
        candidates = [path.with_suffix(suffix), path.with_suffix(suffix.upper())]
        part = next((candidate for candidate in candidates if candidate.is_file()), None)
        if part is not None:
            found[suffix] = part.read_bytes()
    return found


def _to_lonlat(geometries, prj):
    """(geometries in longitude and latitude, name of the coordinates of the file, note if these were assumed, whether
    they were converted)."""
    if prj is None:
        west, south, east, north = shapely.total_bounds(np.array(geometries, dtype=object))
        if -180 <= west and east <= 360 and -90 <= south and north <= 90:
            return geometries, "longitude and latitude (assumed)", (
                "The shapefile has no .prj, which says what its coordinates are: they are taken as longitude and latitude."), False
        raise ShapeError("the shapefile has no .prj, which says what its coordinates are, and they are not longitude and "
                         "latitude: add the .prj that came with it")
    try:
        crs = pyproj.CRS.from_user_input(prj.decode("utf-8", errors="replace"))
    except pyproj.exceptions.CRSError as error:
        raise ShapeError("the coordinates in the .prj cannot be read") from error
    if crs.is_geographic and crs.equals(LONLAT, ignore_axis_order=True):
        return geometries, crs.name, "", False
    transformer = pyproj.Transformer.from_crs(crs, LONLAT, always_xy=True)

    def project(coordinates):
        x, y = transformer.transform(coordinates[:, 0], coordinates[:, 1])
        return np.column_stack([x, y])

    return [shapely.transform(geometry, project) for geometry in geometries], crs.name, "", True


@lru_cache(maxsize=4)
def _read(path, modified):
    parts = _members(path)
    missing = [suffix for suffix in (".shp", ".shx", ".dbf") if suffix not in parts]
    if missing:
        raise ShapeError(f"{Path(path).name}: the shapefile needs its {', '.join(missing)} too, with the same name")
    try:
        reader = shapefile.Reader(shp=io.BytesIO(parts[".shp"]), shx=io.BytesIO(parts[".shx"]), dbf=io.BytesIO(parts[".dbf"]),
                                  encoding="utf-8", encodingErrors="replace")
        fields = tuple(field[0] for field in reader.fields[1:])
        geometries, records = [], []
        for item in reader.iterShapeRecords():
            if item.shape.shapeType == shapefile.NULL:
                continue
            if item.shape.shapeType not in (shapefile.POLYGON, shapefile.POLYGONZ, shapefile.POLYGONM):
                raise ShapeError("the shapefile holds points or lines: only areas (polygons) can be used")
            geometries.append(make_valid(shape(item.shape.__geo_interface__)))
            records.append(dict(zip(fields, item.record)))
    except shapefile.ShapefileException as error:
        raise ShapeError(f"{Path(path).name} cannot be read as a shapefile: {error}") from error
    if not geometries:
        raise ShapeError("the shapefile has no areas")
    geometries, crs, note, converted = _to_lonlat(geometries, parts.get(".prj"))
    return Shapes(geometries=tuple(geometries), records=tuple(records), fields=fields, crs=crs, note=note, converted=converted)


def read_shapes(path):
    """The Shapes of a shapefile, in longitude and latitude. Raises ShapeError saying why not."""
    path = Path(path)
    if not path.is_file():
        raise ShapeError(f"no file {path}")
    return _read(str(path.resolve()), path.stat().st_mtime_ns)


def name_field(shapes):
    """The field that names the areas best, as a start: the one with the most different values, preferring text."""
    def score(field):
        values = [record[field] for record in shapes.records]
        return (len(set(map(str, values))), isinstance(values[0], str))
    return max(shapes.fields, key=score) if shapes.fields else None


def areas(shapes, name=None, merge=None):
    """[(label, geometry)] of the areas to draw: each named by the field `name` (its number if None), or, with `merge`,
    those with the same value of that field joined into one, named by it."""
    for field in (name, merge):
        if field is not None and field not in shapes.fields:
            raise ShapeError(f"the shapefile has no field {field!r}; it has {', '.join(shapes.fields)}")
    if merge is None:
        return [(str(record[name]) if name else f"Area {i + 1}", geometry)
                for i, (record, geometry) in enumerate(zip(shapes.records, shapes.geometries))]
    groups = {}
    for record, geometry in zip(shapes.records, shapes.geometries):
        groups.setdefault(str(record[merge]), []).append(geometry)
    return [(label, _without_slivers(make_valid(shapely.union_all(members)))) for label, members in groups.items()]


def _square_metres(ring_or_polygon):
    return abs(GEOD.geometry_area_perimeter(shapely.Polygon(getattr(ring_or_polygon, "exterior", ring_or_polygon)))[0])


def _without_slivers(geometry):
    """A merged area without the holes and pieces smaller than SLIVER_M2 left between areas that do not quite meet."""
    kept = []
    for part in getattr(geometry, "geoms", [geometry]):
        if part.geom_type != "Polygon" or _square_metres(part) < SLIVER_M2:
            continue
        kept.append(shapely.Polygon(part.exterior, [ring for ring in part.interiors if _square_metres(ring) >= SLIVER_M2]))
    if not kept:
        return geometry
    return kept[0] if len(kept) == 1 else shapely.MultiPolygon(kept)


def outlines(labelled):
    """{"x", "y"} of the boundaries of the areas, separated by None, and {"x", "y", "text"} of a point inside each, to
    name it on hovering."""
    x, y = [], []
    points = {"x": [], "y": [], "text": []}
    for label, geometry in labelled:
        for part in getattr(geometry, "geoms", [geometry]):
            if part.geom_type != "Polygon":
                continue
            for ring in (part.exterior, *part.interiors):
                xs, ys = ring.xy
                x += [round(value, 5) for value in xs] + [None]
                y += [round(value, 5) for value in ys] + [None]
        if not geometry.is_empty:
            inside = geometry.representative_point()
            points["x"].append(round(inside.x, 5))
            points["y"].append(round(inside.y, 5))
            points["text"].append(label)
    return {"x": x, "y": y}, points


def choice_problems(choice):
    """What is wrong with the shapes of a setup, {file, name, merge}: [] if nothing."""
    if not choice:
        return []
    try:
        shapes = read_shapes(choice["file"])
        areas(shapes, choice.get("name"), choice.get("merge"))
    except (ShapeError, KeyError, OSError) as error:
        return [f"shapes: {error}"]
    return []
