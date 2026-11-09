"""Colours, figures and the messages that send them to the page."""

import json
import re

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import xarray as xr
from plotly.colors import sample_colorscale
from plotly.subplots import make_subplots

from .basemap import PADDING_DEGREES, cell_size
from .grid import mask_like


SEQUENTIAL = ["#fee5d9", "#fcbba1", "#fc9272", "#fb6a4a", "#ef3b2c", "#cb181d", "#99000d"]
COLOUR_MAPS = {
    "Reds": SEQUENTIAL,
    "Blues": ["#eff3ff", "#c6dbef", "#9ecae1", "#6baed6", "#4292c6", "#2171b5", "#084594"],
    # matplotlib's coolwarm, at 11 points
    "Coolwarm": ["#3b4cc0", "#5977e3", "#7b9ff9", "#9ebeff", "#c0d4f5", "#dddcdc", "#f2cbb7", "#f7ac8e", "#ee8468", "#d65244", "#b40426"],
}
# Plotly's own scales, sampled at 11 points
COLOUR_MAPS.update({
    name: sample_colorscale(name, 11, colortype="rgb")
    for name in ("Viridis", "Plasma", "Inferno", "Magma", "Cividis", "YlOrRd", "YlGnBu", "Greens", "Purples", "Greys", "Spectral_r", "RdBu_r")
})
# The population density map of the Senegal figure: white, greens, yellow, orange, red, purple, black (sampled from its colour bar)
COLOUR_MAPS["Population density"] = ["#fffffe", "#ffffe7", "#e7f6c4", "#b9e09b", "#90c87b", "#d8e54f", "#f0cb44", "#ed8732", "#ea3624", "#a92317", "#791628", "#4e0a52", "#060006"]
GRID_STEPS = (0.05, 0.1, 0.2, 0.25, 0.5, 1, 2, 5, 10, 20)
GRATICULE = "rgba(11, 11, 11, 0.3)"
AXIS_FONT = 14
# Colour of each dot of the preview, on the map and in the plots; the first two are those of the cells
# selected in the results
DOT_COLOURS = ("#2a78d6", "#e34948", "#2a9d5c", "#d99a0b", "#8a4fd6", "#0f9aa8", "#d6559e", "#6b6a66")
MAX_DOTS = len(DOT_COLOURS)
CELL_COLOURS = DOT_COLOURS[:2]
BOX = "#0b0b0b"
CELL_BANDS = ("rgba(42, 120, 214, 0.2)", "rgba(227, 73, 72, 0.2)")
NO_DATA = "#e6e5e0"
# The water and land colours of cartopy.feature, whose ocean is the Natural Earth ocean painted here
OCEAN = "#97b6e1"
LAND = "#efefdb"
COAST = "#a9a8a2"
RIVER = "#7f97a8"
TERRAIN_DATA_OPACITY = 0.7
BORDER = "#52514e"
TEXT = "#52514e"
GRID = "#e6e5e0"


def next_cells(cells, lon, lat):
    """The selected cells after a click: at most two, the oldest leaving, its colour going to the new one."""
    if any(cell["lon"] == lon and cell["lat"] == lat for cell in cells):
        return cells
    kept = cells[-1:] if len(cells) == len(CELL_COLOURS) else cells
    used = {cell["colour"] for cell in kept}
    colour = next(index for index in range(len(CELL_COLOURS)) if index not in used)
    return [*kept, {"lon": lon, "lat": lat, "colour": colour}]


def add_dot(dots, lon, lat):
    """The dots with one more at a cell, in the first colour not in use; unchanged if the cell has one or there are
    MAX_DOTS."""
    if len(dots) >= MAX_DOTS or any(dot["lon"] == lon and dot["lat"] == lat for dot in dots):
        return dots
    colour = next(index for index in range(MAX_DOTS) if index not in {dot["colour"] for dot in dots})
    return [*dots, {"lon": lon, "lat": lat, "colour": colour}]


def move_dot(dots, index, lon, lat):
    """The dots with the one at `index` moved to a cell, keeping its colour; unchanged if another dot is there."""
    if not 0 <= index < len(dots) or any(i != index and dot["lon"] == lon and dot["lat"] == lat for i, dot in enumerate(dots)):
        return dots
    return [{**dot, "lon": lon, "lat": lat} if i == index else dot for i, dot in enumerate(dots)]


def remove_dot(dots, index):
    return [dot for i, dot in enumerate(dots) if i != index]


def default_dot(field):
    """The cell with data nearest to the middle of the cells with data in the first day of a field, as a dot."""
    first = field.isel(time=0) if "time" in field.dims else field
    values = first.values
    rows, columns = np.nonzero(np.isfinite(values))
    if rows.size == 0:
        return None
    lat, lon = first["lat"].values, first["lon"].values
    middle = np.argmin((lat[rows] - lat[rows].mean()) ** 2 + (lon[columns] - lon[columns].mean()) ** 2)
    return {"lon": float(lon[columns[middle]]), "lat": float(lat[rows[middle]]), "colour": 0}


def dot_label(dot):
    return f"{dot['lat']:.3f}°N, {dot['lon']:.3f}°E"


def cell_envelope(members):
    """Median, lowest and highest seed for each day, from the series of one cell for each seed."""
    members = np.asarray(members, dtype="float64")
    return np.median(members, axis=0), members.min(axis=0), members.max(axis=0)


def _superscript(exponent):
    return "<sup>" + exponent.replace("-", "−").lstrip("+") + "</sup>"


def units_label(units):
    """Units between square brackets, also when the file already has them so, with their exponents as
    superscripts (HTML, as Plotly draws it): day^-1, day-1 and m2 give day⁻¹ and m². Plotly text only."""
    units = units.strip()
    if units.startswith("[") and units.endswith("]"):
        units = units[1:-1].strip()
    units = re.sub(r"(?:\^|\*\*)\{?([+-]?\d+)\}?", lambda match: _superscript(match.group(1)), units)
    units = re.sub(r"(?<=[A-Za-z])(-\d)\b", lambda match: _superscript(match.group(1)), units)
    units = re.sub(r"\b([kcd]?m)([23])\b", lambda match: match.group(1) + _superscript(match.group(2)), units)
    return f"[{units}]" if units else ""


def _with_units(text, units):
    label = units_label(units)
    return f"{text} {label}" if label else text


def grid_step(span):
    """Spacing of the coordinate lines: about 5 to 10 lines across the grid."""
    return next((step for step in GRID_STEPS if span / step <= 10), GRID_STEPS[-1])


def colour_values(values, limits, log=False):
    """(z, zmin, zmax, colour bar ticks) for a field and its colour limits.

    On a log scale, values at or under the lower limit, including zero and negative ones, take the
    lowest colour, so that they are not mistaken for cells that are not simulated.
    """
    lowest, highest = limits
    if not log:
        return values, lowest, highest, {}
    z = np.log10(np.clip(values, lowest, None))
    zmin, zmax = np.log10(lowest), np.log10(highest)
    powers = [float(p) for p in np.arange(np.floor(zmin), np.ceil(zmax) + 1)]
    marks = [p + np.log10(m) for p in powers for m in ((1,) if zmax - zmin > 2 else (1, 2, 5))]
    marks = [m for m in marks if zmin - 1e-9 <= m <= zmax + 1e-9]
    ticks = {"tickvals": marks, "ticktext": [f"{10 ** m:.3g}" for m in marks]}
    return z, zmin, zmax, ticks


def sig(value, digits=4):
    return float(f"{value:.{digits}g}")


def _base_layout(**layout):
    return go.Layout(
        paper_bgcolor="white",
        plot_bgcolor=NO_DATA,
        font={"color": TEXT, "size": 13},
        margin={"l": 60, "r": 20, "t": 44, "b": 50},
        **layout,
    )


def _add_basemap(figure, basemap, terrain=None):
    """Land, relief and lakes under the data, rivers and borders over it. Nothing without a basemap."""
    if basemap is None:
        return
    # Layout images are drawn under layout shapes, so with relief the land is only its outline
    land_fill = "rgba(0,0,0,0)" if terrain else LAND
    below = {"type": "path", "xref": "x", "yref": "y", "layer": "below"}
    figure.update_layout(
        plot_bgcolor=OCEAN,
        shapes=[
            *[{**below, "path": path, "fillcolor": land_fill, "line": {"color": COAST, "width": 0.5}} for path in basemap.land],
            *[{**below, "path": path, "fillcolor": OCEAN, "line": {"color": COAST, "width": 0.5}} for path in basemap.lakes],
        ],
        annotations=[{
            "text": "Natural Earth, ETOPO 2022" if terrain else "Natural Earth", "showarrow": False, "xref": "x domain", "yref": "y domain", "x": 1, "y": 0,
            "xanchor": "right", "yanchor": "bottom", "font": {"size": 10, "color": TEXT},
        }],
    )
    if terrain:
        figure.update_layout(images=[{
            "source": terrain.image, "xref": "x", "yref": "y", "x": terrain.west, "y": terrain.north,
            "sizex": terrain.width, "sizey": terrain.height, "sizing": "stretch", "layer": "below",
        }])
    for lines, color, width in ((basemap.rivers, RIVER, 0.8), (basemap.borders, BORDER, 1)):
        figure.add_trace(go.Scatter(x=lines["x"], y=lines["y"], mode="lines", line={"color": color, "width": width}, hoverinfo="skip", showlegend=False))


SHAPE_LINE, SHAPE_HALO = "#1f1f1f", "rgba(255, 255, 255, 0.85)"  # Dark on a light halo: reads over any colour of the data


def _add_shapes(figure, drawn):
    """The outlines of the areas of a shapefile over the data, each named on hovering a point inside it. drawn is the
    (lines, points) of shapes.outlines, or None."""
    if drawn is None:
        return
    lines, points = drawn
    for colour, width in ((SHAPE_HALO, 3), (SHAPE_LINE, 1.2)):
        figure.add_trace(go.Scatter(x=lines["x"], y=lines["y"], mode="lines", line={"color": colour, "width": width},
                                    hoverinfo="skip", showlegend=False))
    figure.add_trace(go.Scatter(x=points["x"], y=points["y"], text=points["text"], mode="markers", showlegend=False,
                                marker={"size": 12, "opacity": 0}, hovertemplate="%{text}<extra></extra>"))


def _cells(lat, lon, steps=None):
    """The coordinates of a heatmap of the grid. A stripe one cell wide gives its single coordinate as a start and a cell
    size (from the bounds of its file, steps, if any), as Plotly would otherwise make that cell one degree wide."""
    size = dict(zip("yx", cell_size(lat, lon, known=steps)))
    return {key: value for axis, values in (("y", lat), ("x", lon))
            for key, value in ({axis: values} if len(values) > 1 else {f"{axis}0": float(values[0]), f"d{axis}": size[axis]}).items()}


def _grid_step(lat, lon, shapes=None):
    """The step of the coordinate lines, from the extent of the grid and of the areas of a shapefile."""
    spans = []
    for values, drawn in ((lon, shapes[0]["x"] if shapes else []), (lat, shapes[0]["y"] if shapes else [])):
        values = [float(values.min()), float(values.max()), *[value for value in drawn if value is not None]]
        spans.append(max(values) - min(values))
    return grid_step(max(spans))


def _add_graticule(figure, lat, lon, shapes=None):
    """Coordinate lines over the data, where the lines of the axes, drawn under it, cannot be seen."""
    step = _grid_step(lat, lon, shapes)
    west, east = float(lon.min()) - PADDING_DEGREES, float(lon.max()) + PADDING_DEGREES
    south, north = float(lat.min()) - PADDING_DEGREES, float(lat.max()) + PADDING_DEGREES
    x, y = [], []
    for value in np.arange(np.ceil(west / step) * step, east + step / 2, step):
        x += [value, value, None]
        y += [south, north, None]
    for value in np.arange(np.ceil(south / step) * step, north + step / 2, step):
        x += [west, east, None]
        y += [value, value, None]
    figure.add_trace(go.Scatter(x=x, y=y, mode="lines", line={"color": GRATICULE, "width": 0.7}, hoverinfo="skip", showlegend=False))


def _axes(figure, lat, lon, shapes=None, steps=None):
    """Show the grid, and the areas of a shapefile if any (shapes.outlines). The view cannot leave the area of the
    basemap, and the plot, not the view, takes the shape that keeps degrees of longitude and latitude equal. Ticks fall
    on the coordinate lines."""
    def allowed(values):
        return {"minallowed": float(values.min()) - PADDING_DEGREES, "maxallowed": float(values.max()) + PADDING_DEGREES}

    def shown(values, size, drawn):
        """From the first to the last cell centre; a stripe one cell wide, that cell; and all the areas."""
        half = 0 if len(values) > 1 else size / 2
        first, last = float(values.min()) - half, float(values.max()) + half
        drawn = [value for value in drawn if value is not None]
        return [min(first, *drawn), max(last, *drawn)] if drawn else [first, last]

    lines = shapes[0] if shapes is not None else {"x": [], "y": []}

    size_lat, size_lon = cell_size(lat, lon, known=steps)
    ticks = {"tick0": 0, "dtick": _grid_step(lat, lon, shapes), "tickfont": {"size": AXIS_FONT}, "showgrid": False, "zeroline": False}
    figure.update_xaxes(
        title_text="Longitude [°E]", range=shown(lon, size_lon, lines["x"]),
        constrain="domain", constraintoward="center", **ticks, **allowed(lon),
    )
    figure.update_yaxes(
        title_text="Latitude [°N]", range=shown(lat, size_lat, lines["y"]),
        scaleanchor="x", scaleratio=1, constrain="domain", **ticks, **allowed(lat),
    )


def grid_figure(grid, basemap=None, terrain=None, shapes=None):
    """The fixed grid before the first run."""
    z = np.where(grid["mask"], 1.0, np.nan)
    figure = go.Figure(
        go.Heatmap(**_cells(grid["lat"], grid["lon"], grid.get("steps")), z=z, colorscale=[[0, SEQUENTIAL[1]], [1, SEQUENTIAL[1]]], showscale=False, hoverinfo="skip"),
        layout=_base_layout(title="Simulated cells (red) on the fixed grid. Press Run to see results."),
    )
    _add_basemap(figure, basemap, terrain)
    _add_graticule(figure, grid["lat"], grid["lon"], shapes)
    _add_shapes(figure, shapes)
    _axes(figure, grid["lat"], grid["lon"], shapes, grid.get("steps"))
    figure.update_layout(uirevision="grid")
    return figure


def map_figure(data, grid, description, day, limits, cells=(), basemap=None, terrain=None, colour_map="Reds", log=False,
               selected=None, shapes=None):
    """A day of a field. With a grid, only its simulated cells; without, every cell of the field, as for a driving file.
    shapes: the outlines of the areas of a shapefile, from shapes.outlines."""
    label, units = description
    if "time" in data.dims:
        date = str(data["time"].values[day - 1])[:10]
        data_now = data.isel(time=day - 1)
    else:
        date, data_now = "", data
    if grid is not None:
        data_now = data_now.where(mask_like(data, grid))
    # The size of a single cell: from the bounds of the population file with a grid, else of the file of the field
    steps = grid.get("steps") if grid is not None else data.attrs.get("cell_steps")
    values = data_now.values.astype("float64")
    z, zmin, zmax, ticks = colour_values(values, limits, log)
    colours = COLOUR_MAPS[colour_map]
    figure = go.Figure(
        go.Heatmap(
            **_cells(data["lat"].values, data["lon"].values, steps),
            z=z,
            customdata=values,
            zmin=zmin,
            zmax=zmax,
            opacity=TERRAIN_DATA_OPACITY if terrain else 1,
            colorscale=[[i / (len(colours) - 1), colour] for i, colour in enumerate(colours)],
            colorbar={
                "title": {"text": units_label(units) + (" (log scale)" if log else ""), "side": "right"},
                "thickness": 24, "len": 1, "lenmode": "fraction", "y": 0, "yanchor": "bottom", "xpad": 4, "ypad": 0,
                "outlinewidth": 0, "tickfont": {"size": AXIS_FONT + 1},
                **ticks,
            },
            hovertemplate="%{y:.2f}°N, %{x:.2f}°E<br>%{customdata:.4g} " + units_label(units) + "<extra></extra>",
        ),
        layout=_base_layout(
            title=label
            + ("" if basemap else ". Grey: not simulated" if grid is not None else ". Grey: no data")
            + (". Terrain on: colours do not match the colour bar exactly" if terrain else "")
        ),
    )
    # Shown next to the Day slider when this map is drawn, so that the two stay together
    figure.update_layout(meta={"date": date})
    _add_basemap(figure, basemap, terrain)
    _add_graticule(figure, data["lat"].values, data["lon"].values, shapes)
    _add_shapes(figure, shapes)
    for index, cell in enumerate(cells):
        # A black box with a white fill shows over any colour of the data, and so does the X
        # inside it, which has the colour of the cell's lines; the selected dot is larger
        grow = 5 if index == selected else 0
        for symbol, size, fill, line in (("square", 15 + grow, "white", BOX), ("x-thin", 9 + grow, DOT_COLOURS[cell["colour"]], DOT_COLOURS[cell["colour"]])):
            figure.add_trace(
                go.Scatter(
                    x=[cell["lon"]], y=[cell["lat"]], mode="markers", hoverinfo="skip", showlegend=False,
                    marker={"symbol": symbol, "size": size, "color": fill, "line": {"width": 2.5, "color": line}},
                )
            )
    _axes(figure, data["lat"].values, data["lon"].values, shapes, steps)
    figure.update_layout(uirevision="map")
    return figure


def _cell_series(data, cell):
    return data.sel(lat=cell["lat"], lon=cell["lon"], method="nearest")


def _cell_label(series):
    return f"{float(series['lat']):.2f}°N, {float(series['lon']):.2f}°E"


def _time_series_layout(figure, units, from_zero=True):
    figure.update_layout(
        plot_bgcolor="white",
        hovermode="x unified",
        legend={"orientation": "h", "y": -0.3},
        xaxis={"title_text": "Date", "gridcolor": GRID},
        yaxis={"title_text": units_label(units), "gridcolor": GRID, "rangemode": "tozero" if from_zero else "normal"},
    )


def cell_figure(data, description, cells, day, seed=None, from_zero=True):
    """Daily series of the selected cells for one seed, with the day shown on the map marked."""
    label, units = description
    figure = go.Figure(layout=_base_layout(title=label + (f", seed {seed}" if seed is not None else "")))
    _time_series_layout(figure, units, from_zero)
    for cell in cells:
        series = _cell_series(data, cell)
        figure.add_trace(
            go.Scatter(
                x=data["time"].values, y=series.values.astype("float64"), mode="lines",
                line={"width": 2, "color": DOT_COLOURS[cell["colour"]]}, name=_cell_label(series),
                hovertemplate="%{y:.4g} " + units_label(units), showlegend=True,
            )
        )
    date = data["time"].values[day - 1]
    figure.add_shape(type="line", x0=date, x1=date, y0=0, y1=1, yref="paper", line={"color": TEXT, "width": 1, "dash": "dot"})
    return figure


def envelope_figure(fields, seeds, description, cells):
    """Median, lowest and highest seed at the selected cells."""
    label, units = description
    time = fields[0]["time"].values
    template = "%{y:.4g} " + units_label(units)
    figure = go.Figure(layout=_base_layout(title=f"{label}: median and range across {len(seeds)} seeds"))
    _time_series_layout(figure, units)
    for cell in cells:
        series = [_cell_series(data, cell) for data in fields]
        median, lowest, highest = cell_envelope([values.values for values in series])
        place = _cell_label(series[0])
        group = f"{cell['lon']},{cell['lat']}"
        figure.add_trace(go.Scatter(x=time, y=highest, mode="lines", line={"width": 0}, showlegend=False, legendgroup=group, name=f"{place}, highest", hovertemplate=template))
        figure.add_trace(go.Scatter(x=time, y=lowest, mode="lines", line={"width": 0}, fill="tonexty", fillcolor=CELL_BANDS[cell["colour"]], legendgroup=group, name=f"{place}, lowest to highest", hovertemplate=template))
        figure.add_trace(go.Scatter(x=time, y=median, mode="lines", line={"width": 2, "color": CELL_COLOURS[cell["colour"]]}, legendgroup=group, name=f"{place}, median", hovertemplate=template))
    return figure


AGE_FRACTION = "#4682b4"  # As in the figures of fetch_age.sh
AGE_CUMULATIVE = "#e34948"


SEX_COLOURS = {"f": "#e34948", "m": "#2a78d6"}  # Female, male: the first two categorical colours
SEX_NAMES = {"f": "Female", "m": "Male"}


def age_group_label(groups, index):
    """'Under 1', '1-4', ..., '80 and over' for the age groups of WorldPop, which start at the ages in groups."""
    if index == 0:
        return "Under 1"
    if index == len(groups) - 1:
        return f"{groups[index]} and over"
    return f"{groups[index]}-{groups[index + 1] - 1}"


def _plain_axes(figure, x_title, y_title, y_log=False):
    figure.update_layout(plot_bgcolor="white", margin={"l": 70, "r": 30, "t": 44, "b": 50},
                         legend={"x": 0.98, "xanchor": "right", "y": 0.98, "bgcolor": "rgba(255,255,255,0.8)",
                                 "bordercolor": GRID, "borderwidth": 1})
    figure.update_xaxes(title_text=x_title, gridcolor=GRID, tickfont={"size": AXIS_FONT})
    figure.update_yaxes(title_text=y_title, gridcolor=GRID, tickfont={"size": AXIS_FONT}, type="log" if y_log else "linear")
    return figure


def age_heterogeneity_figure(summary, name):
    """For each age group and sex, how many 1 km cells have each share of the group in their people: one
    narrow peak means the same age structure everywhere, the assumption of the model."""
    groups = summary["age_groups"]
    edges = np.asarray(summary["histogram"]["edges"])
    middles = (edges[1:] + edges[:-1]) / 2
    figure = make_subplots(rows=6, cols=3, shared_xaxes=True, shared_yaxes=True, vertical_spacing=0.04,
                           horizontal_spacing=0.03, subplot_titles=[age_group_label(groups, i) for i in range(len(groups))])
    for i in range(len(groups)):
        row, col = i // 3 + 1, i % 3 + 1
        for sex in ("f", "m"):
            figure.add_trace(go.Bar(
                x=middles, y=summary["histogram"][sex][i], width=(edges[1] - edges[0]) * 0.45,
                offset=(-0.45 if sex == "f" else 0.0) * (edges[1] - edges[0]), marker={"color": SEX_COLOURS[sex]},
                name=SEX_NAMES[sex], legendgroup=sex, showlegend=i == 0,
                hovertemplate=f"{SEX_NAMES[sex]}, {age_group_label(groups, i)}: share %{{x:.3f}}, %{{y}} cells<extra></extra>",
            ), row=row, col=col)
    figure.update_layout(_base_layout(title=f"Spatial heterogeneity: {name}"), plot_bgcolor="white", bargap=0,
                         margin={"l": 70, "r": 30, "t": 70, "b": 50},
                         legend={"orientation": "h", "x": 1, "xanchor": "right", "y": 1.04, "yanchor": "bottom"})
    figure.update_xaxes(range=list(edges[[0, -1]]), gridcolor=GRID)
    figure.update_yaxes(type="log", gridcolor=GRID)
    figure.update_xaxes(title_text="Share of the age group in the people of a cell", row=6, col=2)
    figure.update_yaxes(title_text="Cells", row=3, col=1)
    figure.update_annotations(font={"size": 12})
    return figure


def age_sex_figure(summary, name):
    """The mean share of each age group in the people of a cell, female and male: the two are averaged for the model."""
    groups = summary["age_groups"]
    ends = summary["group_ends"]
    figure = go.Figure(layout=_base_layout(title=f"Sex structure (not used by the model yet): {name}"))
    for sex in ("f", "m"):
        shares = summary["mean_share"][sex][:-1]  # 80 and over is left out, as for the model
        figure.add_trace(go.Scatter(
            x=ends, y=shares, mode="lines+markers", line={"color": SEX_COLOURS[sex], "width": 2}, marker={"size": 8},
            name=SEX_NAMES[sex], customdata=[age_group_label(groups, i) for i in range(len(shares))],
            hovertemplate=f"{SEX_NAMES[sex]}, %{{customdata}}: %{{y:.4f}}<extra></extra>",
        ))
    return _plain_axes(figure, "Age [year], at the end of each age group", "Mean share of the people of a cell")


def age_cumulative_figure(summary, name):
    """The cumulative weights by year of age that the model reads, interpolated through those of WorldPop's age groups."""
    figure = go.Figure(layout=_base_layout(title=f"Cumulative weights: {name}"))
    figure.add_trace(go.Scatter(
        x=summary["ages"], y=summary["weights"], mode="lines+markers", line={"color": AGE_CUMULATIVE, "width": 2},
        marker={"size": 4}, name="Interpolated (PCHIP), read by the model",
        hovertemplate="Age %{x} or under: %{y:.4f}<extra></extra>",
    ))
    figure.add_trace(go.Scatter(
        x=summary["group_ends"], y=summary["cumulative_groups"], mode="markers",
        marker={"color": AGE_FRACTION, "size": 10, "line": {"color": "white", "width": 2}}, name="WorldPop age groups",
        hovertemplate="Age %{x} or under: %{y:.4f}<extra></extra>",
    ))
    figure = _plain_axes(figure, "Age [year]", "Cumulative weight (log scale)", y_log=True)
    # The curve rises to the top right corner: the legend goes in the empty bottom right
    figure.update_layout(legend={"x": 0.98, "xanchor": "right", "y": 0.04, "yanchor": "bottom"})
    return figure


def age_fit_figure(summary, name):
    """The weight of each year of age with the exponential decay fitted to it, A exp(-γ age), and its mean age 1/γ."""
    ages = np.asarray(summary["ages"], dtype="float64")
    fit = summary["fit"]
    gamma, amplitude = fit["gamma"], fit["amplitude"]
    figure = go.Figure(layout=_base_layout(title=f"Age structure and fitted mortality: {name}"))
    figure.add_trace(go.Scatter(
        x=ages, y=summary["density"], mode="lines+markers", line={"color": AGE_FRACTION, "width": 2}, marker={"size": 5},
        name="Weight by year of age (WorldPop, interpolated)", hovertemplate="Age %{x}: %{y:.4f}<extra></extra>",
    ))
    figure.add_trace(go.Scatter(
        x=ages, y=amplitude * np.exp(-gamma * ages), mode="lines", line={"color": TEXT, "width": 2, "dash": "dash"},
        name=f"Fit A·exp(−γ·age): γ = {gamma:.4f} ± {fit['gamma_error']:.4f} per year",
        hovertemplate="Age %{x}: %{y:.4f}<extra></extra>",
    ))
    mean = 1.0 / gamma
    figure.add_trace(go.Scatter(
        x=[mean], y=[amplitude * np.exp(-gamma * mean)], mode="markers", marker={"color": AMBER, "size": 10},
        name=f"Mean age of the fit, 1/γ = {mean:.1f} years", hovertemplate=f"1/γ = {mean:.1f} years<extra></extra>",
    ))
    return _plain_axes(figure, "Age [year]", "Weight of the year of age")


OBSERVED = "#2a78d6"  # The first categorical colour: observations


COMPARED = "#8a8984"  # The stage compared with: a neutral grey, behind the result
X_TITLES = {"dated": "Time (each value at the middle of its period)", "climatology": "Calendar month", "season": "Season",
            "yearly": "Year", "age": "Age band [years]", "single": ""}
ONE_PANEL, TWO_PANELS = 380, 640  # Heights of the observations figure, in pixels


def _rgba(colour, alpha):
    colour = colour.lstrip("#")
    return f"rgba({int(colour[0:2], 16)}, {int(colour[2:4], 16)}, {int(colour[4:6], 16)}, {alpha})"


def _band(x, lower, upper, colour, label, what, factor=1.0):
    """A shaded band between lower and upper, as two traces: its top, then its bottom filled up to it."""
    return [go.Scatter(x=x, y=upper * factor, mode="lines", line={"width": 0}, hoverinfo="skip", showlegend=False, legendgroup=label),
            go.Scatter(x=x, y=lower * factor, mode="lines", line={"width": 0}, fill="tonexty", fillcolor=_rgba(colour, 0.2),
                       hoverinfo="skip", name=f"{label}: {what}", legendgroup=label)]


def _spread(observations, rows=None):
    """(lower, upper, what) of the uncertainty of observations, for a band: the range of a seed band (lowest to highest
    seed), else ±1 standard deviation; None if they have none. rows picks some of the values."""
    pick = (lambda values: values) if rows is None else (lambda values: values[rows])
    if "lowest" in observations.extra and "highest" in observations.extra:
        return pick(observations.extra["lowest"]), pick(observations.extra["highest"]), "range across seeds"
    if observations.sd is not None:
        values, sd = pick(observations.values), pick(observations.sd)
        return values - sd, values + sd, "±1 standard deviation"
    return None


def _observations_traces(observations, colour, label, faint=False):
    """The traces of observations: a line over time for dated values, with their uncertainty as a shaded band; bars for
    the other shapes, with error bars."""
    n = len(observations)
    labels = [observations.label(i) for i in range(n)]
    if observations.shape == "dated":
        start = pd.to_datetime(observations.index["start"]).to_numpy()
        end = pd.to_datetime(observations.index["end"]).to_numpy()
        x = start + (end - start) / 2
        spread = None if faint else _spread(observations)
        band = _band(x, spread[0], spread[1], colour, label, spread[2]) if spread else []
        return [*band, go.Scatter(x=x, y=observations.values, mode="lines+markers",
                                  line={"color": colour, "width": 1 if faint else 1.5}, marker={"size": 3 if faint or n > 60 else 6},
                                  customdata=labels, name=label, opacity=0.8 if faint else 1,
                                  hovertemplate=f"{label}, %{{customdata}}: %{{y:.4g}}<extra></extra>")]
    error = None if observations.sd is None or faint else {"type": "data", "array": observations.sd, "color": INTERVAL, "thickness": 1.5}
    return [go.Bar(x=labels, y=observations.values, marker={"color": colour}, error_y=error, name=label,
                   hovertemplate=f"{label}, %{{x}}: %{{y:.4g}}<extra></extra>")]


def observations_figure(observations, name, compare=None, compare_label=""):
    """Observations of any shape: over time for dated values (each at the middle of its period), by calendar month or
    season, by year, by age band, or a single value; with their uncertainty as error bars.

    With compare, an earlier stage of their processing (compare_label, e.g. 'Values loaded'): overlaid in grey if it
    has the same shape and units, else in a second panel below (sharing the time axis if both are dated), so that
    values in different units never share an axis."""
    title = f"{observations.name}: {name}"
    if compare is None:
        figure = go.Figure(_observations_traces(observations, OBSERVED, observations.name), layout=_base_layout(title=title))
        figure = _plain_axes(figure, X_TITLES[observations.shape], observations.units)
        figure.update_layout(showlegend=False, height=ONE_PANEL, meta={"view": "observations"})
        if observations.shape != "dated":
            figure.update_xaxes(type="category")
        return figure
    if compare.shape == observations.shape and compare.units == observations.units:
        figure = go.Figure([*_observations_traces(compare, COMPARED, compare_label, faint=True),
                            *_observations_traces(observations, OBSERVED, "After all steps")], layout=_base_layout(title=title))
        figure = _plain_axes(figure, X_TITLES[observations.shape], observations.units)
        # The legend below the axis title: above the plot it would cover the title
        figure.update_layout(showlegend=True, height=ONE_PANEL + 40, barmode="group", meta={"view": "observations"},
                             margin={"l": 70, "r": 30, "t": 44, "b": 90},
                             legend={"orientation": "h", "x": 0.5, "xanchor": "center", "y": -0.22, "yanchor": "top"})
        if observations.shape != "dated":
            figure.update_xaxes(type="category")
        return figure
    shared = observations.shape == compare.shape == "dated"
    figure = make_subplots(rows=2, cols=1, shared_xaxes=shared, vertical_spacing=0.16 if not shared else 0.1,
                           subplot_titles=[f"After all steps: {observations.name}", f"{compare_label}: {compare.name}"])
    for trace in _observations_traces(observations, OBSERVED, "After all steps"):
        figure.add_trace(trace, row=1, col=1)
    for trace in _observations_traces(compare, COMPARED, compare_label):
        figure.add_trace(trace, row=2, col=1)
    figure.update_layout(_base_layout(title=title), plot_bgcolor="white", showlegend=False, height=TWO_PANELS,
                         margin={"l": 70, "r": 30, "t": 70, "b": 50}, meta={"view": "observations"})
    for row, data in ((1, observations), (2, compare)):
        figure.update_yaxes(title_text=data.units, gridcolor=GRID, tickfont={"size": AXIS_FONT}, row=row, col=1)
        figure.update_xaxes(gridcolor=GRID, tickfont={"size": AXIS_FONT}, row=row, col=1,
                            title_text=X_TITLES[data.shape] if row == 2 or not shared else None,
                            type="category" if data.shape != "dated" else None)
    figure.update_annotations(font={"size": 12})
    return figure


MODELLED = "#e34948"  # The second categorical colour: the model, beside the observations in the first


DRIVER_COLOURS = {"rain": "#0f9aa8", "t2m": "#d99a0b"}  # Teal for rainfall, ochre for temperature


def _driver_trace(observations, colour, label):
    if observations.shape == "dated":
        start = pd.to_datetime(observations.index["start"]).to_numpy()
        end = pd.to_datetime(observations.index["end"]).to_numpy()
        x = start + (end - start) / 2
    else:
        x = [observations.label(i) for i in range(len(observations))]
    kind = go.Bar if observations.aggregation == "sum" else go.Scatter
    style = {"marker": {"color": colour}} if kind is go.Bar else {"mode": "lines+markers", "line": {"color": colour, "width": 1.5}, "marker": {"size": 3}}
    return kind(x=x, y=observations.values, name=label, hovertemplate=f"{label}: %{{y:.4g}} {observations.units}<extra></extra>", **style)


def comparison_figure(model, data, labels, model_values, data_values, scale=False, drivers=()):
    """The model and the observations on the periods (months, seasons, years, age bands) they share, as paired by
    calibration_metrics.pair. With scale, the model times the ratio of the means, to compare timing by eye; the legend
    says by how much. drivers are (name, label, observations) of possible drivers such as rainfall, each drawn in a panel
    below, sharing the time (or month) axis when they are on it too."""
    factor = float(np.mean(data_values) / np.mean(model_values)) if scale and np.mean(model_values) > 0 else 1.0
    middle = ", median across seeds" if "lowest" in model.extra else ""
    model_label = f"Model{middle} × {factor:.3g} (scaled to the mean of the data)" if factor != 1.0 else f"Model: {model.name}{middle}"
    if data.shape == "dated":
        middle = {data.label(i): pd.Timestamp(data.index["start"].iloc[i]) + (pd.Timestamp(data.index["end"].iloc[i])
                  - pd.Timestamp(data.index["start"].iloc[i])) / 2 for i in range(len(data))}
        x = [middle[label] for label in labels]
        spread = []
        model_at = {model.label(i): i for i in range(len(model))}
        found = _spread(model, [model_at[label] for label in labels])
        if found:  # A seed band: its spread over the seeds, on the paired periods
            spread = _band(x, found[0], found[1], MODELLED, "Model", found[2], factor)
        traces = [go.Scatter(x=x, y=data_values, mode="lines+markers", line={"color": OBSERVED, "width": 1.5}, marker={"size": 4},
                             name=f"Data: {data.name}", customdata=labels, hovertemplate="Data, %{customdata}: %{y:.4g}<extra></extra>"),
                  *spread,
                  go.Scatter(x=x, y=model_values * factor, mode="lines+markers", line={"color": MODELLED, "width": 1.5},
                             marker={"size": 4}, name=model_label, customdata=labels,
                             hovertemplate="Model, %{customdata}: %{y:.4g}<extra></extra>")]
    else:
        traces = [go.Bar(x=labels, y=data_values, marker={"color": OBSERVED}, name=f"Data: {data.name}"),
                  go.Bar(x=labels, y=model_values * factor, marker={"color": MODELLED}, name=model_label)]
    title = "Model and data, on the periods they share"
    if not drivers:
        figure = go.Figure(traces, layout=_base_layout(title=title))
        figure = _plain_axes(figure, X_TITLES[data.shape], data.units)
        figure.update_layout(showlegend=True, height=ONE_PANEL + 40, barmode="group", margin={"l": 70, "r": 30, "t": 44, "b": 90},
                             legend={"orientation": "h", "x": 0.5, "xanchor": "center", "y": -0.22, "yanchor": "top"})
        if data.shape != "dated":
            figure.update_xaxes(type="category")
        return figure
    rows = 1 + len(drivers)
    shared = all(observations.shape == data.shape for _, _, observations in drivers)
    figure = make_subplots(rows=rows, cols=1, shared_xaxes=shared, vertical_spacing=0.06 if shared else 0.1,
                           row_heights=[0.5] + [0.5 / len(drivers)] * len(drivers),
                           subplot_titles=[title, *[f"{label} ({observations.units})" for _, label, observations in drivers]])
    for trace in traces:
        figure.add_trace(trace, row=1, col=1)
    for row, (name, label, observations) in enumerate(drivers, start=2):
        figure.add_trace(_driver_trace(observations, DRIVER_COLOURS.get(name, INTERVAL), label), row=row, col=1)
    figure.update_layout(_base_layout(), plot_bgcolor="white", barmode="group", height=ONE_PANEL + 40 + 200 * len(drivers),
                         margin={"l": 70, "r": 30, "t": 50, "b": 90}, showlegend=True,
                         legend={"orientation": "h", "x": 0.5, "xanchor": "center", "y": -0.08, "yanchor": "top"})
    figure.update_yaxes(title_text=data.units, row=1, col=1)
    for row, (_, _, observations) in enumerate(drivers, start=2):
        figure.update_yaxes(title_text=observations.units, row=row, col=1)
    figure.update_xaxes(gridcolor=GRID, tickfont={"size": AXIS_FONT})
    figure.update_yaxes(gridcolor=GRID, tickfont={"size": AXIS_FONT})
    figure.update_xaxes(title_text=X_TITLES[data.shape], row=rows, col=1)
    if data.shape != "dated":
        figure.update_xaxes(type="category")
    figure.update_annotations(font={"size": 12})
    return figure


def message_figure(text):
    figure = go.Figure(layout=_base_layout())
    figure.update_layout(
        plot_bgcolor="white",
        xaxis={"visible": False},
        yaxis={"visible": False},
        annotations=[{"text": text, "showarrow": False, "x": 0.5, "y": 0.5, "xref": "paper", "yref": "paper"}],
    )
    return figure


def send_figure(session, plot_id, figure):
    # to_json so that numpy arrays and dates are encoded as plotly.js expects
    return session.send_custom_message("plot", {"id": plot_id, "figure": json.loads(figure.to_json())})


# Sensitivity analysis: S1, and the rest of ST (interactions) stacked on it, in one hue. Marks drawn over them in
# colours that stand out on the light and the dark theme alike (contrast over 3 on both): amber, as stochastic analyses
# in the card, and a mid grey; the dark ink of other figures cannot be seen on the dark theme.
S1_COLOUR = "#2a78d6"
INTERACTION_COLOUR = "#9ec2ee"
AMBER = "#d97706"
AMBER_FILL = "rgba(217, 119, 6, 0.3)"
INTERVAL = "#8a8984"


def indices_figure(result):
    """S1 and ST of each parameter, most influential first: a bar of S1 with the interactions (ST − S1) on top, so
    that the whole bar is ST, with the 95% confidence intervals of S1 (left) and ST (right); with several seeds, the
    indices of each seed alone as dots, S1 on the left and ST on the right."""
    mean = result["mean"]
    order = np.argsort(-np.nan_to_num(mean["ST"]))
    names = [result["parameters"][j] for j in order]
    x = np.arange(len(names))
    s1, st = mean["S1"][order], mean["ST"][order]
    figure = go.Figure(layout=_base_layout(title=f"Sobol indices of {result['description']}"))
    figure.add_trace(go.Bar(
        x=x, y=s1, name="S1: alone", marker={"color": S1_COLOUR, "cornerradius": 4}, width=0.6,
        customdata=np.column_stack([s1, mean["S1_conf"][order]]),
        hovertemplate="%{hovertext}<br>S1 = %{customdata[0]:.3f} ± %{customdata[1]:.3f}<extra></extra>", hovertext=names,
    ))
    figure.add_trace(go.Bar(
        x=x, y=st - s1, base=s1, name="ST − S1: with others", marker={"color": INTERACTION_COLOUR, "cornerradius": 4}, width=0.6,
        customdata=np.column_stack([st, mean["ST_conf"][order], st - s1]),
        hovertemplate="%{hovertext}<br>ST = %{customdata[0]:.3f} ± %{customdata[1]:.3f}<br>ST − S1 = %{customdata[2]:.3f}<extra></extra>", hovertext=names,
    ))
    # The intervals left (S1) and right (ST) of the middle of the bar, so that close ones do not hide each other
    for key, value, offset in (("S1", s1, -0.08), ("ST", st, 0.08)):
        figure.add_trace(go.Scatter(
            x=x + offset, y=value, mode="markers", marker={"size": 1, "color": INTERVAL}, showlegend=False, hoverinfo="skip",
            error_y={"type": "data", "array": mean[f"{key}_conf"][order], "color": INTERVAL, "thickness": 1.5, "width": 4},
        ))
    if "each" in result:
        seeds = result["seeds"]
        for key, symbol, offset in (("S1", "circle", -0.2), ("ST", "diamond-open", 0.2)):
            values = result["each"][key][:, order]
            figure.add_trace(go.Scatter(
                x=np.repeat(x + offset, len(seeds)), y=values.T.ravel(), mode="markers", name=f"{key} of each seed",
                marker={"symbol": symbol, "size": 8, "color": AMBER, "line": {"width": 1.5, "color": AMBER}},
                customdata=np.tile(seeds, len(names)), hovertext=np.repeat(names, len(seeds)),
                hovertemplate="%{hovertext}, seed %{customdata}<br>" + key + " = %{y:.3f}<extra></extra>",
            ))
    figure.update_layout(
        barmode="overlay", plot_bgcolor="white", bargap=0.3,
        legend={"orientation": "h", "y": -0.18},
        xaxis={"tickvals": x, "ticktext": names, "tickfont": {"size": AXIS_FONT}, "showgrid": False},
        yaxis={"title_text": "Share of the variance", "gridcolor": GRID, "zeroline": True, "zerolinecolor": INTERVAL,
               "range": [min(0.0, float(np.nanmin(s1 - mean["S1_conf"][order]))) - 0.02, max(1.0, float(np.nanmax(st + mean["ST_conf"][order]))) + 0.02]},
    )
    return figure


def second_order_figure(result):
    """S2 of each pair of parameters: the share of the variance they explain together, beyond each alone."""
    names = result["parameters"]
    s2, conf = result["mean"]["S2"], result["mean"]["S2_conf"]
    upper = np.triu(np.ones_like(s2, bool), 1)
    z = np.where(upper, s2, np.nan)
    text = np.where(upper, np.vectorize(lambda v: f"{v:.3f}")(np.nan_to_num(s2)), "")
    colours = COLOUR_MAPS["Blues"]
    figure = go.Figure(go.Heatmap(
        x=names, y=names, z=z, zmin=0, zmax=max(0.05, float(np.nanmax(z)) if upper.any() else 0.05),
        colorscale=[[i / (len(colours) - 1), colour] for i, colour in enumerate(colours)],
        text=text, texttemplate="%{text}", customdata=np.where(upper, conf, np.nan), xgap=2, ygap=2,
        colorbar={"title": {"text": "S2", "side": "right"}, "outlinewidth": 0, "thickness": 16},
        hovertemplate="%{y} with %{x}<br>S2 = %{z:.3f} ± %{customdata:.3f}<extra></extra>",
    ), layout=_base_layout(title="S2: what each pair explains together, beyond each alone"))
    figure.update_layout(plot_bgcolor="white", xaxis={"side": "bottom", "showgrid": False}, yaxis={"autorange": "reversed", "showgrid": False})
    return figure


def index_values(result, name, key):
    """(values at the cells, title, colour limits, colour map) of an index of one parameter on a map: S1 or ST of the
    mean over seeds ('S1', 'ST'), their range across seeds ('S1_range', 'ST_range'), or the share of the variance
    from chance ('chance', the same for every parameter)."""
    j = result["parameters"].index(name)
    if key == "chance":
        return result["chance"], "Share of the variance from chance (the seed)", (0, 1), "Reds"
    if key.endswith("_range"):
        index = key[: -len("_range")]
        values = result["range"][index][j]
        highest = float(np.nanmax(values)) if np.isfinite(values).any() else 1.0
        return values, f"{index} of {name}: highest minus lowest among the {len(result['seeds'])} seeds", (0, max(highest, 0.01)), "Reds"
    return result["mean"][key][j], f"{key} of {name}", (0, 1), "Blues"


def index_map_figure(result, name, key, basemap=None):
    """A map of an index of one parameter, cell by cell."""
    lat, lon = result["lat"], result["lon"]
    values, title, limits, colours = index_values(result, name, key)
    grid = np.full(lat.size * lon.size, np.nan)
    grid[result["cells"]] = values
    data = xr.DataArray(grid.reshape(lat.size, lon.size), dims=("lat", "lon"), coords={"lat": lat, "lon": lon})
    figure = map_figure(data, None, (title, ""), 1, limits, basemap=basemap, colour_map=colours)
    figure.update_layout(title=f"{title}. No colour: not simulated, or the output does not change", meta={"date": "", "colourBarBeside": True})
    return figure


def climate_figure(result, name, key):
    """The index of a map in each cell against the mean rainfall and temperature of the cell over the same days, and its
    population density (on a log scale), with the median of the index in each tenth of the cells: how the sensitivity
    follows the climate and the population."""
    values, title, _, _ = index_values(result, name, key)
    short = title.split(":")[0]
    climate = result["climate"]
    figure = make_subplots(rows=1, cols=max(1, len(climate)), shared_yaxes=True, horizontal_spacing=0.06)
    figure.update_layout(_base_layout(title=f"{title}, in each cell against its climate over the same days and its population"))
    for column, (name_x, (label, units, x)) in enumerate(climate.items(), start=1):
        log = name_x == "pop"
        usable = np.isfinite(x) & np.isfinite(values) & ((x > 0) if log else True)
        # WebGL only when SVG would be slow: some browsers have none
        points = go.Scattergl if usable.sum() > 5000 else go.Scatter
        figure.add_trace(points(
            x=x[usable], y=values[usable], mode="markers", marker={"size": 6, "color": S1_COLOUR, "opacity": 0.5},
            name="Cells", showlegend=column == 1, hovertemplate=f"{label}: %{{x:.3g}}<br>{short} = %{{y:.3f}}<extra></extra>",
        ), row=1, col=column)
        if usable.sum() >= 20:
            edges = np.unique(np.quantile(x[usable], np.linspace(0, 1, 11)))
            bins = np.clip(np.digitize(x[usable], edges[1:-1]), 0, len(edges) - 2)
            filled = [b for b in range(len(edges) - 1) if (bins == b).any()]
            figure.add_trace(go.Scatter(
                x=[np.median(x[usable][bins == b]) for b in filled], y=[np.median(values[usable][bins == b]) for b in filled],
                mode="lines+markers", line={"color": AMBER, "width": 2}, marker={"size": 8},
                name="Median in each tenth of the cells", showlegend=column == 1,
                hovertemplate=f"{label}: %{{x:.3g}}<br>median {short} = %{{y:.3f}}<extra></extra>",
            ), row=1, col=column)
        figure.update_xaxes(title_text=_with_units(label, units) + (" (log scale)" if log else ""), type="log" if log else "linear",
                            gridcolor=GRID, row=1, col=column)
    figure.update_yaxes(title_text=short, gridcolor=GRID, row=1, col=1)
    figure.update_layout(plot_bgcolor="white", legend={"orientation": "h", "y": -0.25})
    if not climate:
        figure.add_annotation(text="The outputs have no rainfall, temperature or population to compare with.", showarrow=False, x=0.5, y=0.5, xref="paper", yref="paper")
    return figure


def monthly_figure(result, name, key):
    """An index of one parameter month by month, or age band by age band: a box of its value in each cell, from the
    10th to the 90th percentile across the cells with the 25th, 50th and 75th, and the index of the mean over the cells
    with its 95% confidence interval; with several seeds, that of each seed alone as dots."""
    j = result["parameters"].index(name)
    by_age = result["kind"] == "ages"
    labels = [str(age) for age in result["ages"]] if by_age else [str(month)[:7] for month in result["months"]]
    spread = result["spread"][key][:, j]
    how = "age band by age band" if by_age else "month by month"
    figure = go.Figure(layout=_base_layout(title=f"{key} of {name}, {how}: {result['description']}"))
    figure.add_trace(go.Box(
        x=labels, lowerfence=spread[:, 0], q1=spread[:, 1], median=spread[:, 2], q3=spread[:, 3], upperfence=spread[:, 4],
        name="Cells: 10th, 25th, 50th, 75th, 90th percentiles", fillcolor=AMBER_FILL, line={"color": AMBER, "width": 1.5},
        width=0.5, hoverinfo="skip",
    ))
    figure.add_trace(go.Scatter(
        x=labels, y=spread[:, 2], mode="markers", marker={"size": 18, "opacity": 0}, showlegend=False,
        customdata=np.column_stack([spread, result["cells_used"]]),
        hovertemplate="%{x}, across %{customdata[5]} cells<br>90th: %{customdata[4]:.3f}<br>75th: %{customdata[3]:.3f}"
                      "<br>median: %{customdata[2]:.3f}<br>25th: %{customdata[1]:.3f}<br>10th: %{customdata[0]:.3f}<extra></extra>",
    ))
    line, conf = result["line"][key][:, j], result["line"][f"{key}_conf"][:, j]
    figure.add_trace(go.Scatter(
        x=labels, y=line, mode="lines+markers", line={"color": S1_COLOUR, "width": 2}, marker={"size": 8, "color": S1_COLOUR},
        error_y={"type": "data", "array": conf, "color": S1_COLOUR, "thickness": 1.5, "width": 4},
        name="Of the mean over the cells, ± 95% interval", customdata=conf,
        hovertemplate="%{x}<br>" + key + " of the mean over the cells = %{y:.3f} ± %{customdata:.3f}<extra></extra>",
    ))
    if "each" in result:
        seeds = result["seeds"]
        figure.add_trace(go.Scatter(
            x=np.repeat(labels, len(seeds)), y=result["each"][key][:, :, j].ravel(), mode="markers",
            marker={"symbol": "circle-open", "size": 9, "color": S1_COLOUR, "line": {"width": 1.5}},
            name="Of the mean over the cells, each seed", customdata=np.tile(seeds, len(labels)),
            hovertemplate="%{x}, seed %{customdata}<br>" + key + " = %{y:.3f}<extra></extra>",
        ))
    low = float(np.nanmin(np.r_[spread[:, 0], line - conf, 0.0]))
    high = float(np.nanmax(np.r_[spread[:, 4], line + conf, 1.0]))
    figure.update_layout(
        plot_bgcolor="white", legend={"orientation": "h", "y": -0.18},
        xaxis={"type": "category", "showgrid": False, "tickfont": {"size": AXIS_FONT},
               **({"title_text": "Age band [years]"} if by_age else {})},
        yaxis={"title_text": f"{key}: share of the variance", "gridcolor": GRID, "zeroline": True, "zerolinecolor": INTERVAL,
               "range": [low - 0.02, high + 0.02]},
    )
    return figure
