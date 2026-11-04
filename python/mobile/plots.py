"""Colours, figures and the messages that send them to the page."""

import json

import numpy as np
import plotly.graph_objects as go

from .basemap import PADDING_DEGREES
from .driving import mean_age
from .grid import mask_like


SEQUENTIAL = ["#fee5d9", "#fcbba1", "#fc9272", "#fb6a4a", "#ef3b2c", "#cb181d", "#99000d"]
COLOUR_MAPS = {
    "Reds": SEQUENTIAL,
    "Blues": ["#eff3ff", "#c6dbef", "#9ecae1", "#6baed6", "#4292c6", "#2171b5", "#084594"],
    # matplotlib's coolwarm, at 11 points
    "Coolwarm": ["#3b4cc0", "#5977e3", "#7b9ff9", "#9ebeff", "#c0d4f5", "#dddcdc", "#f2cbb7", "#f7ac8e", "#ee8468", "#d65244", "#b40426"],
}
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


def units_label(units):
    """Units between square brackets, also when the file already has them so."""
    units = units.strip()
    if units.startswith("[") and units.endswith("]"):
        units = units[1:-1].strip()
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


def _grid_step(lat, lon):
    return grid_step(max(float(lon.max() - lon.min()), float(lat.max() - lat.min())))


def _add_graticule(figure, lat, lon):
    """Coordinate lines over the data, where the lines of the axes, drawn under it, cannot be seen."""
    step = _grid_step(lat, lon)
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


def _axes(figure, lat, lon):
    """Show the grid. The view cannot leave the area of the basemap, and the plot, not the view,
    takes the shape that keeps degrees of longitude and latitude equal. Ticks fall on the coordinate lines."""
    def allowed(values):
        return {"minallowed": float(values.min()) - PADDING_DEGREES, "maxallowed": float(values.max()) + PADDING_DEGREES}

    ticks = {"tick0": 0, "dtick": _grid_step(lat, lon), "tickfont": {"size": AXIS_FONT}, "showgrid": False, "zeroline": False}
    figure.update_xaxes(
        title_text="Longitude [°E]", range=[float(lon.min()), float(lon.max())],
        constrain="domain", constraintoward="left", **ticks, **allowed(lon),
    )
    figure.update_yaxes(
        title_text="Latitude [°N]", range=[float(lat.min()), float(lat.max())],
        scaleanchor="x", scaleratio=1, constrain="domain", **ticks, **allowed(lat),
    )


def grid_figure(grid, basemap=None, terrain=None):
    """The fixed grid before the first run."""
    z = np.where(grid["mask"], 1.0, np.nan)
    figure = go.Figure(
        go.Heatmap(x=grid["lon"], y=grid["lat"], z=z, colorscale=[[0, SEQUENTIAL[1]], [1, SEQUENTIAL[1]]], showscale=False, hoverinfo="skip"),
        layout=_base_layout(title="Simulated cells (red) on the fixed grid. Press Run to see results."),
    )
    _add_basemap(figure, basemap, terrain)
    _add_graticule(figure, grid["lat"], grid["lon"])
    _axes(figure, grid["lat"], grid["lon"])
    figure.update_layout(uirevision="grid")
    return figure


def map_figure(data, grid, description, day, limits, cells=(), basemap=None, terrain=None, colour_map="Reds", log=False,
               selected=None):
    """A day of a field. With a grid, only its simulated cells; without, every cell of the field, as for a driving file."""
    label, units = description
    if "time" in data.dims:
        date = str(data["time"].values[day - 1])[:10]
        data_now = data.isel(time=day - 1)
    else:
        date, data_now = "", data
    if grid is not None:
        data_now = data_now.where(mask_like(data, grid))
    values = data_now.values.astype("float64")
    z, zmin, zmax, ticks = colour_values(values, limits, log)
    colours = COLOUR_MAPS[colour_map]
    figure = go.Figure(
        go.Heatmap(
            x=data["lon"].values,
            y=data["lat"].values,
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
    _add_graticule(figure, data["lat"].values, data["lon"].values)
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
    _axes(figure, data["lat"].values, data["lon"].values)
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


def age_figure(ages, fraction, cumulative, name):
    """The fraction of the population at each year of age, with its mean, and on the right axis the
    cumulative fraction the model reads, on a log scale: the figures of fetch_age.sh in one."""
    mean = mean_age(ages, fraction)
    at_mean = float(np.interp(mean, ages, fraction))
    figure = go.Figure(layout=_base_layout(title=f"Age structure: {name}"))
    figure.add_trace(go.Scatter(
        x=ages, y=fraction, mode="lines+markers", line={"color": AGE_FRACTION, "width": 2}, marker={"size": 5},
        name="Fraction by year of age (left axis)", hovertemplate="Age %{x}: %{y:.4f}<extra></extra>",
    ))
    figure.add_trace(go.Scatter(
        x=[mean, mean], y=[0, at_mean], mode="lines", line={"color": BOX, "width": 1}, opacity=0.3,
        showlegend=False, hoverinfo="skip",
    ))
    figure.add_trace(go.Scatter(
        x=[mean], y=[at_mean], mode="markers", marker={"color": BOX, "size": 10}, name=f"Mean age: {mean:.1f} years",
        hovertemplate=f"Mean age: {mean:.1f} years<extra></extra>",
    ))
    figure.add_trace(go.Scatter(
        x=ages, y=cumulative, yaxis="y2", mode="lines+markers", line={"color": AGE_CUMULATIVE, "width": 2, "dash": "dot"},
        marker={"size": 4}, name="Cumulative fraction (right axis)", hovertemplate="Age %{x} or under: %{y:.4f}<extra></extra>",
    ))
    # Ticks at 1, 2 and 5 of each power of 10 covered: plotly labels a short log axis poorly
    positive = cumulative[cumulative > 0]
    ticks = [m * 10.0**p for p in range(int(np.floor(np.log10(positive.min()))), 1) for m in (1, 2, 5)]
    ticks = [tick for tick in ticks if tick <= positive.max() * 1.5]  # Those outside the range are not drawn
    figure.update_layout(
        plot_bgcolor="white",
        margin={"l": 70, "r": 70, "t": 44, "b": 50},
        legend={"x": 0.98, "xanchor": "right", "y": 0.5, "yanchor": "middle", "bgcolor": "rgba(255,255,255,0.8)", "bordercolor": GRID, "borderwidth": 1},
        xaxis={"title_text": "Age [year]", "gridcolor": GRID, "tickfont": {"size": AXIS_FONT}},
        yaxis={"title_text": "Fraction of the population", "gridcolor": GRID, "rangemode": "tozero", "tickfont": {"size": AXIS_FONT}},
        yaxis2={"title_text": "Cumulative fraction (log scale)", "overlaying": "y", "side": "right", "type": "log",
                "showgrid": False, "tickfont": {"size": AXIS_FONT}, "tickvals": ticks, "ticktext": [f"{tick:g}" for tick in ticks]},
        meta={"view": "age"},
    )
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
