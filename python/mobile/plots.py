"""Colours, figures and the messages that send them to the page."""

import json
import re

import numpy as np
import plotly.graph_objects as go
import xarray as xr
from plotly.subplots import make_subplots

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
        constrain="domain", constraintoward="center", **ticks, **allowed(lon),
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
    """The index of a map in each cell against the mean rainfall and temperature of the cell over the same days,
    with the median of the index in each tenth of the cells: how the sensitivity follows the climate."""
    values, title, _, _ = index_values(result, name, key)
    short = title.split(":")[0]
    climate = result["climate"]
    figure = make_subplots(rows=1, cols=max(1, len(climate)), shared_yaxes=True, horizontal_spacing=0.06)
    figure.update_layout(_base_layout(title=f"{title}, in each cell against its climate over the same days"))
    for column, (label, units, x) in enumerate(climate.values(), start=1):
        usable = np.isfinite(x) & np.isfinite(values)
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
        figure.update_xaxes(title_text=_with_units(label, units), gridcolor=GRID, row=1, col=column)
    figure.update_yaxes(title_text=short, gridcolor=GRID, row=1, col=1)
    figure.update_layout(plot_bgcolor="white", legend={"orientation": "h", "y": -0.25})
    if not climate:
        figure.add_annotation(text="The outputs have no rainfall or temperature to compare with.", showarrow=False, x=0.5, y=0.5, xref="paper", yref="paper")
    return figure


def monthly_figure(result, name, key):
    """An index of one parameter month by month: a box of its value in each cell, from the 10th to the 90th percentile
    across the cells with the 25th, 50th and 75th, and the index of the mean over the cells with its 95% confidence
    interval; with several seeds, that of each seed alone as dots."""
    j = result["parameters"].index(name)
    labels = [str(month)[:7] for month in result["months"]]
    spread = result["spread"][key][:, j]
    figure = go.Figure(layout=_base_layout(title=f"{key} of {name}, month by month: {result['description']}"))
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
        xaxis={"type": "category", "showgrid": False, "tickfont": {"size": AXIS_FONT}},
        yaxis={"title_text": f"{key}: share of the variance", "gridcolor": GRID, "zeroline": True, "zerolinecolor": INTERVAL,
               "range": [low - 0.02, high + 0.02]},
    )
    return figure
