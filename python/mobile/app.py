"""Local Shiny interface: fixed grid and driving data, parameters on sliders, the real model behind Run."""

import asyncio
import json
import math
import os
import re
import signal
import threading
from dataclasses import dataclass, field, replace
from pathlib import Path

import numpy as np
import plotly.graph_objects as go
import plotly.offline
import xarray as xr
from shiny import App, reactive, render, run_app, ui

from .basemap import PADDING_DEGREES, load_basemap, load_terrain
from .config import SLIDER_GROUPS, ConfigError, read_params
from .results import list_runs, load_run, load_seed_band, write_seed_band
from .rundir import new_run_id
from .runner import Runner, RunnerBusy

MODEL_NAMES = {0: "Cholera", 1: "VECTRI-ABM"}  # By disID
# Tabs for each type of analysis, to be filled
ANALYSIS_TABS = (
    ("Time series", "Time series analysis, such as spectrograms: to come."),
    ("Demography", "Age-related analysis: to come."),
    ("Mobility", "Mobility analysis: to come. Mobility is not yet functional in MoBILE."),
    ("Sensitivity analysis", "Sensitivity analysis of the model parameters with SALib: to come."),
)
ASSETS = Path(__file__).parent / "assets"
LOGO_SUFFIXES = (".png", ".svg", ".jpg", ".jpeg")
FUNDER_PLACEHOLDERS = 3
CODE_DOCS_URL = "https://mgarrizor.github.io/MoBILE/"  # FORD, built from the source code
USER_DOCS_URL = "https://mobile-ictp.readthedocs.io/en/latest/"  # Sphinx, on Read the Docs
PREFERRED_VARIABLES = ("EIR", "V")
# A variable by age has a group of its own in the output file, of fields <name>_<age>
AGE_FIELD = re.compile(r"^.+_(bulk|\d+-\d+|\d+\+)$")
ALL_AGES = "bulk"
AGE_KEY = "age:"  # In the Variable menu: one entry for all the fields of a group
STATIC_MESSAGE = "This variable does not change over time: see the map."

# The flags of &OUTPUT: (flag, label, compiled-in default), by the group of the output file they write to
OUTPUT_FLAGS = {
    "Human": [
        ("out_pop", "Population density", True),
        ("out_age", "Age structure (not a map)", True),
        ("out_N", "Agents per cell", True),
        ("out_HA", "Humans per agent", True),
        ("out_S", "Susceptible", False),
        ("out_E", "Exposed", False),
        ("out_I", "Symptomatic", True),
        ("out_I_new", "New symptomatic cases", True),
        ("out_A", "Asymptomatic", False),
        ("out_R", "Recovered", False),
        ("out_EIR", "Entomological inoculation rate", True),
        ("out_P1", "Probability of an infective bite", True),
        ("out_hbr", "Human biting rate", False),
        ("out_imm", "Immunity", True),
    ],
    "Human, by age (one field per age band, large output)": [
        ("out_Ia", "Symptomatic", False),
        ("out_Ia_new", "New symptomatic cases", False),
        ("out_Aa", "Asymptomatic", False),
        ("out_imm_a", "Immunity", False),
        ("out_N_a", "Agents", False),
    ],
    "Vector": [
        ("out_vect", "Vector density", True),
        ("out_vecinfc", "Infective vector density", True),
        ("out_larv", "Larval density", False),
    ],
    "Hydro": [
        ("out_wpond", "Pond fraction", True),
        ("out_wperm", "Permanent water fraction", True),
        ("out_wurbn", "Urban water fraction", False),
    ],
}

SEQUENTIAL = ["#fee5d9", "#fcbba1", "#fc9272", "#fb6a4a", "#ef3b2c", "#cb181d", "#99000d"]
COLOUR_MAPS = {
    "Reds": SEQUENTIAL,
    # matplotlib's coolwarm, at 11 points
    "Coolwarm": ["#3b4cc0", "#5977e3", "#7b9ff9", "#9ebeff", "#c0d4f5", "#dddcdc", "#f2cbb7", "#f7ac8e", "#ee8468", "#d65244", "#b40426"],
}
GRID_STEPS = (0.05, 0.1, 0.2, 0.25, 0.5, 1, 2, 5, 10, 20)
GRATICULE = "rgba(11, 11, 11, 0.3)"
AXIS_FONT = 14
# Colour of each selected cell, on the map and in the plots
CELL_COLOURS = ("#2a78d6", "#e34948")
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

POP_NAMES = ["pop", "population", "population density", "Band1"]  # As pop_names in mo_control.f90
LAT_NAMES = ["lat", "latitude", "Y"]
LON_NAMES = ["lon", "longitude", "X"]

# Plays the days at a chosen rate. Each day is sent once the previous map is drawn, so that
# asking for more than the machine can draw slows the playback rather than skipping days.
PLAYER = """
const player = {
  rates: [0.5, 1, 2, 3, 4, 5, 6, 8, 10, 15, 20],
  rate: 2,
  playing: false,
  sentAt: 0,
  lastDrawn: 0,
  actual: null,
  timer: null,
  watchdog: null,
  show() {
    document.getElementById('player_play').textContent = this.playing ? '⏸' : '▶';
    document.getElementById('player_play').title = this.playing ? 'Pause' : 'Play';
    const rate = this.rates[this.rate];
    const measured = this.playing && this.actual !== null ? ` (actual ${this.actual.toFixed(1)})` : '';
    document.getElementById('player_rate').textContent = `${rate} fps${measured}`;
    document.getElementById('player_slower').disabled = document.getElementById('player_much_slower').disabled = this.rate === 0;
    document.getElementById('player_faster').disabled = document.getElementById('player_much_faster').disabled = this.rate === this.rates.length - 1;
  },
  next() {
    const slider = $('#day').data('ionRangeSlider');
    const day = slider.result.from >= slider.result.max ? slider.result.min : slider.result.from + 1;
    slider.update({from: day});
    Shiny.setInputValue('day', day, {priority: 'event'});
    this.sentAt = performance.now();
    clearTimeout(this.watchdog);
    // Nothing is drawn before the first run, or if a map is lost
    this.watchdog = setTimeout(() => { if (this.playing) this.next(); }, 3000);
  },
  drawn() {
    if (!this.playing) return;
    clearTimeout(this.watchdog);
    const now = performance.now();
    if (this.lastDrawn) {
      const current = 1000 / (now - this.lastDrawn);
      this.actual = this.actual === null ? current : 0.7 * this.actual + 0.3 * current;
    }
    this.lastDrawn = now;
    this.show();
    clearTimeout(this.timer);
    const wait = Math.max(0, 1000 / this.rates[this.rate] - (now - this.sentAt));
    this.timer = setTimeout(() => this.next(), wait);
  },
  first() {
    const slider = $('#day').data('ionRangeSlider');
    slider.update({from: slider.result.min});
    Shiny.setInputValue('day', slider.result.min, {priority: 'event'});
  },
  toggle() {
    this.playing ? this.pause() : this.play();
  },
  play() {
    this.playing = true;
    this.lastDrawn = 0;
    this.actual = null;
    this.show();
    this.next();
  },
  pause() {
    this.playing = false;
    clearTimeout(this.timer);
    clearTimeout(this.watchdog);
    this.show();
  },
  change(steps) {
    this.rate = Math.min(this.rates.length - 1, Math.max(0, this.rate + steps));
    this.actual = null;
    this.lastDrawn = 0;
    this.show();
  },
};
$(document).on('click', '#player_first', () => player.first());
$(document).on('click', '#player_play', () => player.toggle());
$(document).on('click', '#player_much_slower', () => player.change(-3));
$(document).on('click', '#player_slower', () => player.change(-1));
$(document).on('click', '#player_faster', () => player.change(1));
$(document).on('click', '#player_much_faster', () => player.change(3));
// In the capture phase, as the Run button does not pass its clicks on
document.addEventListener('click', (event) => { if (event.target.closest('#run')) player.pause(); }, true);
$(document).on('shiny:sessioninitialized', () => player.show());
"""

PLOT_HANDLER = """
// Gaps between cells, showing as a grid, once the cells are large enough on screen
const GRID_MIN_PIXELS = 10;
const mapZoom = {};
function rememberZoom(event) {
  if (event['xaxis.autorange'] || event['yaxis.autorange']) {
    delete mapZoom.x;
    delete mapZoom.y;
  }
  if ('xaxis.range[0]' in event) mapZoom.x = [event['xaxis.range[0]'], event['xaxis.range[1]']];
  if ('yaxis.range[0]' in event) mapZoom.y = [event['yaxis.range[0]'], event['yaxis.range[1]']];
}
function updateCellGrid(plot) {
  const index = plot._fullData.findIndex(trace => trace.type === 'heatmap');
  if (index < 0) return;
  const trace = plot._fullData[index];
  const pixels = Math.abs(trace.x[1] - trace.x[0]) * plot._fullLayout.xaxis._m;
  const gap = pixels >= GRID_MIN_PIXELS ? 1 : 0;
  if ((trace.xgap || 0) !== gap) Plotly.restyle(plot, {xgap: gap, ygap: gap}, [index]);
}
// The colour bar just right of the map and as tall as it: the map keeps its shape, so it does not fill the plot
function placeColourBar(plot) {
  const index = plot._fullData.findIndex(trace => trace.type === 'heatmap');
  if (index < 0 || !plot._fullData[index].showscale) return;
  const x = plot._fullLayout.xaxis.domain[1] + 0.005;
  const [bottom, top] = plot._fullLayout.yaxis.domain;
  plot.colourBar = {x: x, y: bottom, len: top - bottom};
  const bar = plot._fullData[index].colorbar;
  if (Math.abs(bar.x - x) > 0.002 || Math.abs(bar.y - bottom) > 0.002 || Math.abs(bar.len - (top - bottom)) > 0.002) {
    Plotly.restyle(plot, {'colorbar.x': x, 'colorbar.y': bottom, 'colorbar.len': top - bottom}, [index]);
  }
}
// A plot drawn while its tab was hidden has no size: fit the plots when the Main tab is shown again
$(document).on('shown.bs.tab', function() {
  for (const id of ['map', 'cell_plot', 'envelope_plot']) {
    const plot = document.getElementById(id);
    if (plot && plot.data && plot.offsetParent !== null) Plotly.Plots.resize(plot);
  }
});
Shiny.addCustomMessageHandler('plot', function(message) {
  if (message.id === 'map') {
    const before = document.getElementById('map');
    if (before.colourBar) message.figure.data.filter(t => t.type === 'heatmap').forEach(t => { t.colorbar = {...(t.colorbar || {}), ...before.colourBar}; });
  }
  // A new figure from the server keeps the zoom of the map
  if (message.id === 'map' && mapZoom.x) message.figure.layout.xaxis.range = mapZoom.x;
  if (message.id === 'map' && mapZoom.y) message.figure.layout.yaxis.range = mapZoom.y;
  const drawing = Plotly.react(message.id, message.figure.data, message.figure.layout,
                               {responsive: true, displaylogo: false, doubleClick: 'reset'});
  if (message.id === 'map') {
    document.getElementById('day_date').textContent = (message.figure.layout.meta || {}).date || '';
    drawing.then(() => player.drawn());
  }
  const plot = document.getElementById(message.id);
  if (message.id === 'map') updateCellGrid(plot);
  if (message.id === 'map' && !plot.clickReported) {
    plot.clickReported = true;
    plot.on('plotly_relayout', function(event) { rememberZoom(event); updateCellGrid(plot); });
    plot.on('plotly_afterplot', function() { placeColourBar(plot); });
    // A double click resets the view, and must not select the cell under it
    let pendingClick = null;
    plot.on('plotly_click', function(event) {
      const point = event.points[0];
      clearTimeout(pendingClick);
      // The second click of a double click: the browser counts them
      if (event.event.detail > 1) return;
      pendingClick = setTimeout(function() {
        Shiny.setInputValue('cell', {lon: point.x, lat: point.y}, {priority: 'event'});
      }, 350);
    });
    plot.on('plotly_doubleclick', function() { clearTimeout(pendingClick); });
  }
});
"""


CLOSED_HANDLER = """
Shiny.addCustomMessageHandler('closed', function(message) {
  document.body.innerHTML = '<p style="margin: 2rem; font-family: sans-serif;">The app is closed. You can close this tab.</p>';
  window.close();
});
"""

# Labels only: the value of a slider stays as it is until the slider is moved
SLIDER_FORMAT = """
const sliderDecimals = %s;
function formatSlider(id) {
  $('#' + id).data('ionRangeSlider').update({
    prettify_enabled: true,
    prettify: function(value) { return value.toFixed(sliderDecimals[id]); }
  });
}
$(document).on('shiny:sessioninitialized', function() {
  Object.keys(sliderDecimals).forEach(formatSlider);
});
// An update from the server replaces the format
$(document).on('shiny:updateinput', function(event) {
  if (event.target.id in sliderDecimals) {
    setTimeout(function() { formatSlider(event.target.id); }, 0);
  }
});
"""


def _first(names, available):
    return next(name for name in names if name in available)


def load_grid(config):
    """Coordinates, simulated cells and total population of the fixed grid."""
    with xr.open_dataset(config.inputs["pop_file"]) as pop_data, xr.open_dataset(config.inputs["area_file"]) as area:
        pop = pop_data[_first(POP_NAMES, pop_data.variables)]
        lat = pop_data[_first(LAT_NAMES, pop_data.variables)].values
        lon = pop_data[_first(LON_NAMES, pop_data.variables)].values
        people = float((pop.values * area["cell_area"].values).astype("float64")[np.isfinite(pop.values)].sum())
        return {"lat": lat, "lon": lon, "mask": np.isfinite(pop.values), "people": people}


def next_cells(cells, lon, lat):
    """The selected cells after a click: at most two, the oldest leaving, its colour going to the new one."""
    if any(cell["lon"] == lon and cell["lat"] == lat for cell in cells):
        return cells
    kept = cells[-1:] if len(cells) == len(CELL_COLOURS) else cells
    used = {cell["colour"] for cell in kept}
    colour = next(index for index in range(len(CELL_COLOURS)) if index not in used)
    return [*kept, {"lon": lon, "lat": lat, "colour": colour}]


def cell_envelope(members):
    """Median, lowest and highest seed for each day, from the series of one cell for each seed."""
    members = np.asarray(members, dtype="float64")
    return np.median(members, axis=0), members.min(axis=0), members.max(axis=0)


MAX_LOADED_VARIABLES = 4
GROUP_ORDER = ("Human", "Vector", "Hydro", "Climate")
BY_AGE_HEADING = "By age"


@dataclass
class RunState:
    """Written by the worker thread, read by the session."""

    lock: threading.Lock = field(default_factory=threading.Lock)
    message: str = ""
    fraction: float | None = None
    member: int = 1
    members: int = 1
    runner: Runner | None = None
    cancelled: bool = False

    def update(self, **values):
        with self.lock:
            for key, value in values.items():
                setattr(self, key, value)

    def snapshot(self):
        with self.lock:
            return self.message, self.fraction, self.member, self.members


@dataclass
class Outcome:
    status: str
    loaded: bool = False
    run_dir: str = ""
    log: str = ""
    overrides: dict = field(default_factory=dict)
    nagent: int = 0
    seeds: list = field(default_factory=list)
    results: list = field(default_factory=list)    # RunResult of each seed
    variables: dict = field(default_factory=dict)  # As RunResult.variables
    days: int = 0
    loaded_fields: dict = field(default_factory=dict)
    colour_limits: dict = field(default_factory=dict)
    nonpositive: dict = field(default_factory=dict)  # {menu entry: share of the values at or under 0}

    def fields(self, name):
        """The field of each seed. Only those asked for are read, as a run can hold over 100 of them."""
        if name not in self.loaded_fields:
            if len(self.loaded_fields) >= MAX_LOADED_VARIABLES:
                self.loaded_fields.pop(next(iter(self.loaded_fields)))
            self.loaded_fields[name] = [result.open(name) for result in self.results]
        return self.loaded_fields[name]

    def describe(self, name):
        """(label, units) of a variable, from the attributes in the output file."""
        info = self.variables[name]
        label = info["long_name"]
        age = AGE_FIELD.match(name)
        if info["group"] in age_groups(self.variables) and age:
            label = f"{label}, {_age_label(age.group(1)).lower()}"
        return label, info["units"]


def run_model(config, seeds, state):
    """Run one seed after another with the same parameters, threads and binary."""
    outcome = Outcome(status="finished", overrides=dict(config.params), nagent=config.run["nagent"])
    band = f"seed_band_{new_run_id()}" if len(seeds) > 1 else None
    if band:
        outcome.run_dir = str(config.runs_dir / band)
    for member, seed in enumerate(seeds, start=1):
        if state.cancelled:
            outcome.status = "cancelled"
            break
        runner = Runner(config.with_run(seed=seed))
        state.update(runner=runner, member=member, members=len(seeds), message="Starting", fraction=None)

        def on_progress(event):
            state.update(message=event.message, fraction=event.fraction)

        try:
            result = runner.run(f"{band}/seed_{seed}" if band else None, on_progress=on_progress)
        except RunnerBusy as error:
            outcome.status, outcome.log = "failed", str(error)
            break
        if not band:
            outcome.run_dir = str(result.run_dir)
        if not result.ok:
            outcome.status, outcome.log = result.status, result.log_tail()
            break
        outcome.results.append(result)
        outcome.seeds.append(seed)
    if outcome.results:
        outcome.variables, outcome.days = outcome.results[0].variables(), outcome.results[0].days()
    if band and (config.runs_dir / band).is_dir():
        write_seed_band(config.runs_dir / band, outcome.status, seeds)
    return outcome


def load_outcome(run_dir, manifest):
    """A finished run or seed band read back from its folder."""
    seeds = manifest.get("seeds")
    results = load_seed_band(run_dir) if seeds else [load_run(run_dir)]
    outcome = Outcome(
        status="finished", loaded=True, run_dir=str(run_dir), overrides=manifest.get("param_overrides", {}),
        nagent=manifest["run"]["nagent"], seeds=seeds or [manifest["run"]["seed"]], results=results,
        variables=results[0].variables(), days=results[0].days(),
    )
    return outcome


def age_groups(variables):
    """{group: {age: variable}} of the groups of the output file that hold a variable by age."""
    groups = {}
    for name, info in variables.items():
        groups.setdefault(info["group"], {})[name] = AGE_FIELD.match(name)
    return {
        group: {match.group(1): name for name, match in fields.items()}
        for group, fields in groups.items()
        if all(fields.values()) and len(fields) > 1
    }


def _age_label(age):
    return "All ages" if age == ALL_AGES else f"Age {age}"


def age_choices(ages):
    return {age: _age_label(age) for age in sorted(ages, key=lambda age: age != ALL_AGES)}


def variable_choices(variables):
    """Choices of the Variable menu, by the group of the output file; a variable by age is one entry."""
    def order(group):
        return GROUP_ORDER.index(group) if group in GROUP_ORDER else len(GROUP_ORDER)

    by_age = age_groups(variables)
    choices = {}
    for name, info in variables.items():
        if info["group"] not in by_age:
            choices.setdefault(info["group"], {})[name] = info["long_name"]
    choices = {group: choices[group] for group in sorted(choices, key=order)}
    if by_age:
        choices[BY_AGE_HEADING] = {
            AGE_KEY + group: variables[next(name for age, name in ages.items() if age != ALL_AGES)]["long_name"]
            for group, ages in by_age.items()
        }
    return choices


def preferred_variable(variables, current=None):
    """The menu entry to show: the one on show if the output has it."""
    entries = [entry for group in variable_choices(variables).values() for entry in group]
    for entry in (current, *PREFERRED_VARIABLES):
        if entry in entries:
            return entry
    return entries[0]


def resolve_variable(variables, entry, age=None):
    """The field for a menu entry and an age group; All ages if that one is not available."""
    if not entry.startswith(AGE_KEY):
        return entry
    ages = age_groups(variables)[entry[len(AGE_KEY):]]
    return ages.get(age) or ages.get(ALL_AGES) or next(iter(ages.values()))


def _run_label(folder, manifest):
    changed = ", ".join(f"{k}={v:.4g}" for k, v in manifest.get("param_overrides", {}).items()) or "no changes"
    run = manifest["run"]
    seeds = f"seed band of {len(manifest['seeds'])} from seed {run['seed']}" if "seeds" in manifest else f"seed {run['seed']}"
    return f"{manifest.get('date', '?').replace('T', ' ')}: {run['nagent']:,} agents, {seeds}, {changed}"


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


def _sig(value, digits=4):
    return float(f"{value:.{digits}g}")


def _mask_like(data, grid):
    """The simulated cells on the coordinates of the output."""
    mask = xr.DataArray(grid["mask"], dims=("lat", "lon"), coords={"lat": grid["lat"], "lon": grid["lon"]})
    return mask.reindex(lat=data["lat"], lon=data["lon"], method="nearest")


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


def map_figure(data, grid, description, day, limits, cells=(), basemap=None, terrain=None, colour_map="Reds", log=False):
    label, units = description
    if "time" in data.dims:
        date = str(data["time"].values[day - 1])[:10]
        data_now = data.isel(time=day - 1)
    else:
        date, data_now = "", data
    values = data_now.where(_mask_like(data, grid)).values.astype("float64")
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
            + ("" if basemap else ". Grey: not simulated")
            + (". Terrain on: colours do not match the colour bar exactly" if terrain else "")
        ),
    )
    # Shown next to the Day slider when this map is drawn, so that the two stay together
    figure.update_layout(meta={"date": date})
    _add_basemap(figure, basemap, terrain)
    _add_graticule(figure, data["lat"].values, data["lon"].values)
    for cell in cells:
        # A black box with a white fill shows over any colour of the data, and so does the X
        # inside it, which has the colour of the cell's lines
        for symbol, size, fill, line in (("square", 15, "white", BOX), ("x-thin", 9, CELL_COLOURS[cell["colour"]], CELL_COLOURS[cell["colour"]])):
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


def _time_series_layout(figure, units):
    figure.update_layout(
        plot_bgcolor="white",
        hovermode="x unified",
        legend={"orientation": "h", "y": -0.3},
        xaxis={"title_text": "Date", "gridcolor": GRID},
        yaxis={"title_text": units_label(units), "gridcolor": GRID, "rangemode": "tozero"},
    )


def cell_figure(data, description, cells, day, seed=None):
    """Daily series of the selected cells for one seed, with the day shown on the map marked."""
    label, units = description
    figure = go.Figure(layout=_base_layout(title=label + (f", seed {seed}" if seed is not None else "")))
    _time_series_layout(figure, units)
    for cell in cells:
        series = _cell_series(data, cell)
        figure.add_trace(
            go.Scatter(
                x=data["time"].values, y=series.values.astype("float64"), mode="lines",
                line={"width": 2, "color": CELL_COLOURS[cell["colour"]]}, name=_cell_label(series),
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


def _message_figure(text):
    figure = go.Figure(layout=_base_layout())
    figure.update_layout(
        plot_bgcolor="white",
        xaxis={"visible": False},
        yaxis={"visible": False},
        annotations=[{"text": text, "showarrow": False, "x": 0.5, "y": 0.5, "xref": "paper", "yref": "paper"}],
    )
    return figure


def _send_figure(session, plot_id, figure):
    # to_json so that numpy arrays and dates are encoded as plotly.js expects
    return session.send_custom_message("plot", {"id": plot_id, "figure": json.loads(figure.to_json())})


def _slider_grid(spec):
    """(min, max, step, decimals) of a slider: 3 decimals, more if the range would have under 100 steps."""
    decimals = max(3, math.ceil(-math.log10((spec["max"] - spec["min"]) / 100)))
    step = 10.0**-decimals
    return (
        round(math.floor(spec["min"] / step) * step, decimals),
        round(math.ceil(spec["max"] / step) * step, decimals),
        step,
        decimals,
    )


def _slider(name, spec, value):
    low, high, step, _ = _slider_grid(spec)
    return ui.input_slider(f"param_{name}", spec.get("label", name), min=low, max=high, value=value, step=step)


def logo_files(folder, stem=None):
    """Images in a folder by name; with stem, only those with that name."""
    if not folder.is_dir():
        return []
    return sorted(
        path for path in folder.iterdir()
        if path.suffix.lower() in LOGO_SUFFIXES and (stem is None or path.stem.lower() == stem)
    )


def _logo_placeholder(text, **style):
    return ui.div(
        text,
        style="display: flex; align-items: center; justify-content: center; border: 1px dashed #a9a8a2; "
        "color: #52514e; font-size: 0.75rem; text-align: center; width: 140px; height: 56px;",
        class_="logo-placeholder",
        **style,
    )


def _logo(path, folder, height):
    return ui.img(src=f"/assets/{folder}{path.name}", alt=path.stem, style=f"height: {height}px; max-width: 220px; object-fit: contain;")


def _header(config):
    disease = config.run["disID"]
    ictp = logo_files(ASSETS, "ictp")
    return ui.div(
        ui.div(
            ui.div("MoBILE", style="font-size: 1.4rem; font-weight: 600; line-height: 1.2;"),
            ui.div(f"Model: {MODEL_NAMES.get(disease, f'disID {disease}')}", style="font-size: 0.95rem; font-weight: 400;"),
            ui.div(f"Project: {config.project or 'not set'}", style="font-size: 0.95rem; font-weight: 400;"),
        ),
        _logo(ictp[0], "", 56) if ictp else _logo_placeholder("ICTP logo", id="ictp_logo"),
        style="display: flex; align-items: center; justify-content: space-between; width: 100%;",
    )


def _funders():
    logos = logo_files(ASSETS / "funders")
    items = [_logo(path, "funders/", 48) for path in logos] or [
        _logo_placeholder(f"Funder logo {number}") for number in range(1, FUNDER_PLACEHOLDERS + 1)
    ]
    return ui.div(
        ui.div("Funded by", class_="small mb-2"),
        ui.div(*items, style="display: flex; flex-wrap: wrap; gap: 1rem; align-items: center;"),
        id="funders",
        class_="mt-3 pt-3 border-top",
    )


def _player_controls():
    def button(id, symbol, title):
        return ui.tags.button(symbol, id=id, type="button", title=title, class_="btn btn-sm btn-outline-secondary")

    return ui.div(
        button("player_first", "⏮\ufe0e", "Back to day 1"),
        button("player_much_slower", "«", "Much slower"),
        button("player_slower", "‹", "Slower"),
        button("player_play", "▶", "Play"),
        button("player_faster", "›", "Faster"),
        button("player_much_faster", "»", "Much faster"),
        ui.tags.span(id="player_rate", class_="small ms-2"),
        style="display: flex; align-items: center; gap: 0.25rem;",
    )


def _docs():
    """The documentation built with the package, readable offline; a placeholder until there is one."""
    code_docs = ui.p("Documentation of the source code: ", ui.a(CODE_DOCS_URL, href=CODE_DOCS_URL, target="_blank"), class_="small")
    online = ui.p("User documentation online: ", ui.a(USER_DOCS_URL, href=USER_DOCS_URL, target="_blank"), class_="small")
    if not (ASSETS / "docs" / "index.html").is_file():
        return ui.div(ui.p("The user documentation is not included in this installation.", class_="text-muted mt-3"), online, code_docs)
    return ui.div(
        ui.p(ui.a("Open in a new window", href="/assets/docs/index.html", target="_blank"), class_="small mt-3 mb-2"),
        ui.tags.iframe(src="/assets/docs/index.html", title="Documentation", style="width: 100%; height: 80vh; border: 1px solid #dee2e6;"),
        online,
        code_docs,
    )


def _output_switch_id(flag):
    return f"output_{flag}"


def _output_groups(selected):
    """One collapsible panel per group of the output file, with a switch per flag."""
    panels = [
        ui.accordion_panel(group, *[ui.input_switch(_output_switch_id(flag), label, value=flag in selected) for flag, label, _ in flags])
        for group, flags in OUTPUT_FLAGS.items()
    ]
    return panels


def _slider_groups(config, values):
    """One collapsible panel per group that has sliders."""
    panels = []
    for group in SLIDER_GROUPS:
        sliders = [_slider(name, spec, values[name]) for name, spec in config.sliders.items() if spec["group"] == group]
        if sliders:
            panels.append(ui.accordion_panel(group, *sliders))
    return panels


def create_app(config):
    grid = load_grid(config)
    default_output = {flag for flags in OUTPUT_FLAGS.values() for flag, _, on in flags if on}
    initial_output = set(config.output) if config.output is not None else default_output
    defaults = read_params(config.inputs["const"])
    missing = set(config.sliders) - set(defaults)
    if missing:
        raise ConfigError(f"sliders need a value in the `const` file: {sorted(missing)}")
    slider_defaults = {name: float(defaults[name]) for name in config.sliders}

    app_ui = ui.page_sidebar(
        ui.sidebar(
            ui.input_task_button("run", "Run", label_busy="Running…", class_="btn-primary"),
            ui.input_action_button("cancel", "Cancel"),
            ui.input_action_button("close", "Close app"),
            ui.input_numeric("nagent", "Number of agents", value=config.run["nagent"], min=1, step=100000),
            ui.output_text("humans_per_agent"),
            ui.input_numeric("seed", "Seed", value=config.run["seed"], min=1, step=1),
            ui.input_switch("seed_band", "Seed band", value=False),
            ui.panel_conditional("input.seed_band", ui.input_numeric("n_seeds", "Number of seeds", value=5, min=2, step=1)),
            ui.input_select("previous_run", f"Previous runs in {config.runs_dir}", {}),
            ui.input_action_button("load", "Load run"),
            ui.accordion(
                ui.accordion_panel(
                    "Parameters",
                    ui.input_action_button("reset", "Reset parameters", class_="mb-2 w-100"),
                    ui.accordion(*_slider_groups(config, slider_defaults), open=False, multiple=True),
                ),
                ui.accordion_panel(
                    "Outputs",
                    ui.p("What the next run writes. Rainfall and temperature are always written.", class_="small"),
                    ui.accordion(*_output_groups(initial_output), open=False, multiple=True),
                ),
                open=False,
                multiple=True,
            ),
            width=320,
        ),
        ui.head_content(
            ui.tags.script(ui.HTML(plotly.offline.get_plotlyjs())),
            ui.tags.script(ui.HTML(PLAYER)),
            ui.tags.script(ui.HTML(PLOT_HANDLER)),
            ui.tags.script(ui.HTML(CLOSED_HANDLER)),
            ui.tags.style("#shiny-disconnected-overlay { display: none; }"),
            ui.tags.script(ui.HTML(SLIDER_FORMAT % json.dumps({f"param_{n}": _slider_grid(s)[3] for n, s in config.sliders.items()}))),
        ),
        ui.output_ui("status"),
        ui.navset_tab(
            ui.nav_panel(
                "Main",
                ui.card(
                    ui.layout_columns(
                        ui.div(ui.input_select("variable", "Variable", {}), ui.output_ui("age_choice")),
                        ui.div(ui.output_ui("seed_choice"), ui.input_switch("terrain", "Terrain", value=False), ui.output_ui("terrain_status")),
                        ui.div(
                            ui.input_slider("day", ui.TagList("Day ", ui.tags.span(id="day_date", class_="ms-1")), min=1, max=max(config.run["nstep"], 2), value=1, step=1, width="100%"),
                            _player_controls(),
                        ),
                        col_widths=(3, 2, 7),
                    ),
                    ui.layout_columns(
                        ui.input_select("colour_map", "Colour map", list(COLOUR_MAPS)),
                        ui.input_radio_buttons("scale", "Scale", {"linear": "Linear", "log": "Log"}, inline=True),
                        ui.input_numeric("vmin", "Minimum", value=None, step="any"),
                        ui.input_numeric("vmax", "Maximum", value=None, step="any"),
                        ui.div(ui.input_action_button("auto_range", "Automatic range", class_="btn-sm"), class_="pt-4"),
                        col_widths=(2, 2, 2, 2, 3),
                    ),
                    ui.div(id="map", style="height: 680px;"),
                    ui.div(id="cell_plot", style="height: 300px;"),
                    ui.panel_conditional("input.seed_band", ui.div(id="envelope_plot", style="height: 340px;")),
                ),
            ),
            *[ui.nav_panel(name, ui.p(text, class_="text-muted mt-3")) for name, text in ANALYSIS_TABS],
            ui.nav_panel("Docs", _docs()),
            id="tab",
        ),
        _funders(),
        title=_header(config),
    )

    def server(input, output, session):
        current = reactive.value(None)
        selected_cells = reactive.value([])
        runs_changed = reactive.value(0)
        range_overrides = reactive.value({})  # {(menu entry, scale): (minimum, maximum)} set by hand
        state = RunState()

        def selected_output():
            flags = [flag for group in OUTPUT_FLAGS.values() for flag, _, _ in group]
            return tuple(flag for flag in flags if input[_output_switch_id(flag)]())

        def overrides():
            """Sliders moved from their value in the `const` file; the others keep it as written there."""
            moved = {}
            for name, spec in config.sliders.items():
                value = input[f"param_{name}"]()
                _, _, step, decimals = _slider_grid(spec)
                # A slider starts at the value of the `const` file snapped to its step
                if abs(value - round(slider_defaults[name], decimals)) >= step / 2:
                    moved[name] = round(float(value), decimals)
            return moved

        @reactive.extended_task
        async def basemap_task():
            return await asyncio.to_thread(load_basemap, grid["lon"], grid["lat"])

        basemap_task.invoke()

        @reactive.extended_task
        async def terrain_task():
            return await asyncio.to_thread(load_terrain, grid["lon"], grid["lat"], LAND)

        @reactive.effect
        def fetch_terrain():
            if not input.terrain() or basemap() is None:
                return
            with reactive.isolate():
                # A failed download is tried again the next time the switch is turned on
                if terrain_task.status() == "initial" or (terrain_task.status() == "success" and terrain_task.result() is None):
                    terrain_task.invoke()

        @reactive.effect
        def report_terrain():
            # Only when a download ends: the outcome of an earlier one must not stop a new attempt
            if terrain_task.status() == "success" and terrain_task.result() is None:
                with reactive.isolate():
                    if input.terrain():
                        terrain_unavailable()

        @reactive.effect
        def report_no_basemap():
            if input.terrain() and basemap_task.status() == "success" and basemap_task.result() is None:
                terrain_unavailable()

        def terrain_unavailable():
            ui.notification_show("Terrain could not be downloaded. Check the connection and try again.", type="warning")
            ui.update_switch("terrain", value=False)

        @render.ui
        def terrain_status():
            downloading = basemap_task.status() == "running" or terrain_task.status() == "running"
            if not input.terrain() or not downloading:
                return None
            return ui.div(
                ui.tags.span(class_="spinner-border spinner-border-sm me-1", role="status"),
                "Downloading terrain, about a minute…",
                class_="small",
            )

        def terrain():
            """Shaded relief when the switch is on and it is ready, otherwise None."""
            if input.terrain() and terrain_task.status() == "success":
                return terrain_task.result()
            return None

        def basemap():
            """None until it is ready, and if it cannot be obtained: the map is then plain."""
            return basemap_task.result() if basemap_task.status() == "success" else None

        @ui.bind_task_button(button_id="run")
        @reactive.extended_task
        async def run_task(run_config, seeds):
            return await asyncio.to_thread(run_model, run_config, seeds, state)

        @reactive.effect
        @reactive.event(input.run)
        def start_run():
            nagent, seed = input.nagent(), input.seed()
            n_seeds = input.n_seeds() if input.seed_band() else 1
            if not all(isinstance(value, int) and value >= 1 for value in (nagent, seed, n_seeds)):
                ui.notification_show("Agents, seed and number of seeds must be positive integers.", type="error")
                return
            try:
                run_config = replace(config, params={**config.params, **overrides()}, output=selected_output()).with_run(nagent=nagent)
            except ConfigError as error:
                ui.notification_show(str(error), type="error")
                return
            state.update(cancelled=False, message="Starting", fraction=None, runner=None)
            run_task.invoke(run_config, [seed + i for i in range(n_seeds)])

        @reactive.effect
        @reactive.event(input.cancel)
        def cancel_run():
            state.update(cancelled=True)
            if state.runner is not None:
                state.runner.cancel()

        async def close_app():
            """Stop any run, tell the browser, then stop the server as Ctrl+C does."""
            state.update(cancelled=True)
            if state.runner is not None:
                state.runner.cancel()
            await session.send_custom_message("closed", {})
            asyncio.get_running_loop().call_later(0.5, os.kill, os.getpid(), signal.SIGINT)

        @reactive.effect
        @reactive.event(input.close)
        async def ask_to_close():
            if run_task.status() != "running":
                await close_app()
                return
            ui.modal_show(
                ui.modal(
                    "A run is in progress. Closing the app will cancel it.",
                    title="Close the app?",
                    footer=ui.TagList(ui.modal_button("Keep running"), ui.input_action_button("close_confirmed", "Cancel run and close")),
                )
            )

        @reactive.effect
        @reactive.event(input.close_confirmed)
        async def close_confirmed():
            await close_app()

        @reactive.effect
        def collect_result():
            if run_task.status() == "success":
                outcome = run_task.result()
                with reactive.isolate():
                    show(outcome)
                    runs_changed.set(runs_changed() + 1)

        def show(outcome):
            current.set(outcome)
            if outcome.seeds:
                ui.update_slider("day", max=outcome.days, value=min(input.day(), outcome.days))
                ui.update_select(
                    "variable",
                    choices=variable_choices(outcome.variables),
                    selected=preferred_variable(outcome.variables, input.variable()),
                )

        def available_runs():
            return list_runs(config.runs_dir, config.inputs["pop_file"])

        @reactive.effect
        def refresh_previous_runs():
            runs_changed()
            ui.update_select("previous_run", choices={folder: _run_label(folder, manifest) for folder, manifest in available_runs().items()})

        @reactive.effect
        @reactive.event(input.load)
        def load_previous_run():
            if run_task.status() == "running":
                ui.notification_show("Wait for the run to finish, or cancel it, before loading another.", type="warning")
                return
            folder = input.previous_run()
            manifest = available_runs().get(folder)
            if manifest is None:
                ui.notification_show("No run selected, or its output is no longer there.", type="warning")
                return
            try:
                outcome = load_outcome(folder, manifest)
            except (KeyError, OSError, RuntimeError) as error:
                ui.notification_show(f"Could not load this run: {error}", type="error")
                return
            show(outcome)
            ui.update_numeric("nagent", value=outcome.nagent)
            ui.update_numeric("seed", value=outcome.seeds[0])
            ui.update_switch("seed_band", value=len(outcome.seeds) > 1)
            if len(outcome.seeds) > 1:
                ui.update_numeric("n_seeds", value=len(outcome.seeds))
            for name, value in slider_defaults.items():
                ui.update_slider(f"param_{name}", value=outcome.overrides.get(name, value))
            written = manifest.get("output")
            written = default_output if written is None else set(written)
            for group in OUTPUT_FLAGS.values():
                for flag, _, _ in group:
                    ui.update_switch(_output_switch_id(flag), value=flag in written)

        @reactive.effect
        @reactive.event(input.reset)
        def reset_sliders():
            for name, value in slider_defaults.items():
                ui.update_slider(f"param_{name}", value=value)

        @render.text
        def humans_per_agent():
            nagent = input.nagent()
            if not nagent or nagent < 1:
                return ""
            return f"Mean humans per agent: {grid['people'] / nagent:.2f} ({grid['people']:,.0f} people)"

        @render.ui
        def status():
            task = run_task.status()
            if task == "running":
                reactive.invalidate_later(0.5)
                message, fraction, member, members = state.snapshot()
                prefix = f"Seed {member} of {members}. " if members > 1 else ""
                if fraction is None:
                    bar = ui.div(class_="progress-bar progress-bar-striped progress-bar-animated", style="width: 100%;")
                else:
                    bar = ui.div(class_="progress-bar", style=f"width: {fraction * 100:.0f}%;")
                return ui.card(ui.p(prefix + message, class_="mb-1"), ui.div(bar, class_="progress"))
            if task == "error":
                return ui.card(ui.p("The app failed while reading the results; see the terminal."), class_="border-danger")
            outcome = current()
            if outcome is None:
                return None
            if outcome.status == "finished":
                changed = ", ".join(f"{k}={v:.4g}" for k, v in outcome.overrides.items()) or "none"
                seeds = f"seed {outcome.seeds[0]}" if len(outcome.seeds) == 1 else f"seeds {outcome.seeds[0]} to {outcome.seeds[-1]}"
                return ui.p(
                    f"{'Loaded' if outcome.loaded else 'Showing'}: {outcome.nagent:,} agents, {seeds}, changed parameters: {changed}. "
                    f"Folder: {outcome.run_dir}",
                    class_="small mb-0",
                )
            if outcome.status == "cancelled":
                return ui.p("Run cancelled.", class_="mb-0")
            return ui.card(ui.p("The run failed. End of its log:"), ui.tags.pre(outcome.log), class_="border-danger")

        @render.ui
        def seed_choice():
            outcome = current()
            if outcome is None or len(outcome.seeds) < 2:
                return None
            return ui.input_select("map_seed", "Seed", {str(i): str(seed) for i, seed in enumerate(outcome.seeds)})

        def shown_member(outcome):
            """Index of the seed on the map and in the upper plot."""
            if len(outcome.seeds) < 2:
                return 0
            index = int(input.map_seed()) if "map_seed" in input and input.map_seed() else 0
            return min(index, len(outcome.seeds) - 1)

        def shown_entry(outcome):
            """The menu is updated after the outcome, so it can briefly name a variable this run does not have."""
            return preferred_variable(outcome.variables, input.variable())

        def shown_variable(outcome):
            age = input.age_group() if "age_group" in input else None
            return resolve_variable(outcome.variables, shown_entry(outcome), age)

        @render.ui
        def age_choice():
            outcome = current()
            if outcome is None or not outcome.seeds or not shown_entry(outcome).startswith(AGE_KEY):
                return None
            ages = age_groups(outcome.variables)[shown_entry(outcome)[len(AGE_KEY):]]
            with reactive.isolate():
                previous = input.age_group() if "age_group" in input else None
            selected = previous if previous in ages else next(iter(age_choices(ages)))
            return ui.input_select("age_group", "Age group", age_choices(ages), selected=selected)

        @reactive.calc
        def colour_limits():
            """Automatic colour range, fixed over the run, the seeds, and the ages of a variable by age,
            so that colours can be compared. On a log scale, from the positive values only."""
            outcome = current()
            entry, log = shown_entry(outcome), input.scale() == "log"
            key = (entry, log)
            if key not in outcome.colour_limits:
                names = age_groups(outcome.variables)[entry[len(AGE_KEY):]].values() if entry.startswith(AGE_KEY) else [entry]
                lows, highs = [], []
                nonpositive, simulated = 0, 0
                for name in names:
                    for result in outcome.results:
                        data = result.open(name)
                        data = data.where(_mask_like(data, grid))
                        if log:
                            simulated += int(data.notnull().sum())
                            nonpositive += int((data <= 0).sum())
                            data = data.where(data > 0)
                        if bool(data.notnull().any()):
                            lows.append(float(data.quantile(0.01, skipna=True)))
                            highs.append(float(data.quantile(0.99, skipna=True)))
                if not highs:
                    limits = (0.001, 1.0) if log else (0.0, 1.0)
                else:
                    lowest = min(lows) if log else min(min(lows), 0.0)
                    highest = max(highs)
                    limits = (lowest, highest if highest > lowest else lowest * 10 if log else lowest + 1.0)
                outcome.colour_limits[key] = limits
                if log:
                    outcome.nonpositive[entry] = nonpositive / simulated if simulated else 0.0
            return outcome.colour_limits[key]

        def colour_key(outcome):
            return shown_entry(outcome), input.scale()

        def shown_limits():
            outcome = current()
            return range_overrides().get(colour_key(outcome)) or colour_limits()

        @reactive.effect
        def show_range():
            """The range in use, in the Minimum and Maximum boxes."""
            outcome = current()
            if outcome is None or not outcome.seeds:
                return
            lowest, highest = shown_limits()
            ui.update_numeric("vmin", value=_sig(lowest))
            ui.update_numeric("vmax", value=_sig(highest))

        @reactive.effect
        @reactive.event(input.vmin, input.vmax, ignore_init=True)
        def set_range():
            outcome = current()
            lowest, highest = input.vmin(), input.vmax()
            if outcome is None or not outcome.seeds or lowest is None or highest is None:
                return
            with reactive.isolate():
                shown = shown_limits()
                key = colour_key(outcome)
            # The boxes show the range rounded: that is not a change
            if _sig(lowest) == _sig(shown[0]) and _sig(highest) == _sig(shown[1]):
                return
            # Kept as typed, as the other box may be changed next to make the pair valid
            if lowest >= highest or (key[1] == "log" and lowest <= 0):
                ui.notification_show(
                    "Not applied: the minimum must be below the maximum, and above 0 on a log scale.", type="warning"
                )
                return
            range_overrides.set({**range_overrides(), key: (float(lowest), float(highest))})

        def warn_nonpositive(outcome):
            """On a log scale, the automatic range leaves out the values at or under 0: say so."""
            if input.scale() != "log":
                return
            lowest = colour_limits()[0]
            share = outcome.nonpositive.get(shown_entry(outcome), 0.0)
            if share > 0:
                ui.notification_show(
                    f"Log scale: the automatic minimum, {_sig(lowest)}, is the 1st percentile of the positive values. "
                    f"{share:.1%} of the values are 0 or less and show in the lowest colour, as do those under the minimum.",
                    type="warning",
                )

        @reactive.effect
        @reactive.event(input.auto_range)
        def automatic_range():
            outcome = current()
            if outcome is None or not outcome.seeds:
                return
            overrides = dict(range_overrides())
            overrides.pop(colour_key(outcome), None)
            range_overrides.set(overrides)
            warn_nonpositive(outcome)

        @reactive.effect
        @reactive.event(input.scale, ignore_init=True)
        def switched_scale():
            outcome = current()
            if outcome is None or not outcome.seeds or colour_key(outcome) in range_overrides():
                return
            warn_nonpositive(outcome)

        @reactive.effect
        async def draw_map():
            outcome = current()
            if outcome is None or not outcome.seeds:
                await _send_figure(session, "map", grid_figure(grid, basemap(), terrain()))
                return
            name = shown_variable(outcome)
            data = outcome.fields(name)[shown_member(outcome)]
            day = min(input.day(), outcome.days)
            await _send_figure(
                session, "map",
                map_figure(
                    data, grid, outcome.describe(name), day, shown_limits(), selected_cells(), basemap(), terrain(),
                    input.colour_map(), input.scale() == "log",
                ),
            )

        @reactive.effect
        @reactive.event(input.cell)
        def select_cell():
            with reactive.isolate():
                cell = input.cell()
                selected_cells.set(next_cells(selected_cells(), cell["lon"], cell["lat"]))

        @reactive.effect
        async def draw_cell_plot():
            outcome = current()
            cells = selected_cells()
            if outcome is None or not outcome.seeds:
                await _send_figure(session, "cell_plot", _message_figure("Press Run, then click a cell on the map to see its time series."))
                return
            if not cells:
                await _send_figure(session, "cell_plot", _message_figure("Click a cell on the map to see its time series, and a second one to compare."))
                return
            name = shown_variable(outcome)
            if outcome.variables[name]["static"]:
                await _send_figure(session, "cell_plot", _message_figure(STATIC_MESSAGE))
                return
            member = shown_member(outcome)
            data = outcome.fields(name)[member]
            seed = outcome.seeds[member] if len(outcome.seeds) > 1 else None
            await _send_figure(session, "cell_plot", cell_figure(data, outcome.describe(name), cells, min(input.day(), outcome.days), seed))

        @reactive.effect
        async def draw_envelope():
            if not input.seed_band():
                return
            outcome = current()
            cells = selected_cells()
            if outcome is None or len(outcome.seeds) < 2:
                await _send_figure(session, "envelope_plot", _message_figure("Press Run to run the seeds with the same parameters."))
            elif not cells:
                await _send_figure(session, "envelope_plot", _message_figure("Click a cell on the map to see its range across seeds."))
            elif outcome.variables[shown_variable(outcome)]["static"]:
                await _send_figure(session, "envelope_plot", _message_figure(STATIC_MESSAGE))
            else:
                name = shown_variable(outcome)
                await _send_figure(session, "envelope_plot", envelope_figure(outcome.fields(name), outcome.seeds, outcome.describe(name), cells))

    return App(app_ui, server, static_assets={"/assets": ASSETS})


def launch(config, port=8000, browser=True):
    run_app(create_app(config), port=port, launch_browser=browser)
