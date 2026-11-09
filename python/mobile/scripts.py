"""JavaScript and CSS the page loads: the theme, the day player, the plot handlers and the slider format."""


# Light, dark, or as the system: the choice is kept in the browser. Loaded first, so that the page
# is not drawn in the other theme before it.
THEME = """
const THEME_KEY = 'mobile-theme';
const darkQuery = window.matchMedia('(prefers-color-scheme: dark)');
function themeChoice() {
  try { return localStorage.getItem(THEME_KEY) || 'system'; } catch (error) { return 'system'; }
}
function shownTheme() {
  const choice = themeChoice();
  return choice === 'system' ? (darkQuery.matches ? 'dark' : 'light') : choice;
}
function applyTheme() {
  const theme = shownTheme();
  const changed = document.documentElement.getAttribute('data-bs-theme') !== theme;
  document.documentElement.setAttribute('data-bs-theme', theme);
  document.querySelectorAll('[data-theme-choice]').forEach(function(button) {
    const active = button.dataset.themeChoice === themeChoice();
    button.classList.toggle('active', active);
    button.setAttribute('aria-pressed', active);
  });
  if (changed && typeof themePlot === 'function') document.querySelectorAll('.js-plotly-plot').forEach(themePlot);
}
applyTheme();
$(document).on('click', '[data-theme-choice]', function() {
  try { localStorage.setItem(THEME_KEY, this.dataset.themeChoice); } catch (error) {}
  applyTheme();
});
darkQuery.addEventListener('change', applyTheme);
$(document).on('shiny:sessioninitialized', applyTheme);
"""
PAGE_STYLE = """
.logo { background: white; border-radius: 4px; padding: 2px; }
.sidebar-heading { font-size: 1.1rem; font-weight: 600;
                   color: var(--bs-primary); margin: 0.25rem 0 0; }
.bslib-sidebar-layout > .sidebar > .sidebar-content { gap: 0.7rem; padding: 1.1rem 1.1rem 1rem; }
/* Run and Cancel keep the same size whatever their label, as Run shows a spinner while busy.
   Cancel is pastel red while it can be used, that is while a run is going. */
.run-bar > * { width: 100%; white-space: nowrap; }
#cancel:not(:disabled) { background-color: #f4a6a6; border-color: #f4a6a6; color: #5c1a1a; }
#cancel:not(:disabled):hover { background-color: #ee8e8e; border-color: #ee8e8e; }
/* Sidebar entries are typed, without up and down buttons */
.bslib-sidebar-layout input[type=number] { -moz-appearance: textfield; appearance: textfield; }
.bslib-sidebar-layout input[type=number]::-webkit-inner-spin-button,
.bslib-sidebar-layout input[type=number]::-webkit-outer-spin-button { -webkit-appearance: none; margin: 0; }
/* The header, with the tabs in its second row, stays in view while the page scrolls */
.bslib-page-sidebar { height: auto; min-height: 100vh; }
.bslib-page-sidebar > .navbar { position: sticky; top: 0; z-index: 1030; flex-direction: column; align-items: stretch; padding-top: 0.3rem; padding-bottom: 0; }
.navbar .nav-tabs { flex-wrap: nowrap; border-bottom: 0; padding: 0.1rem 0.75rem 0; gap: 0.25rem; }
.navbar .nav-tabs .nav-link { color: var(--bs-link-color); background: transparent; border: 0; border-bottom: 3px solid transparent;
  border-radius: 0; padding: 0.3rem 1rem; font-weight: 500; }
.navbar .nav-tabs .nav-link:hover { color: var(--bs-link-hover-color); border-bottom-color: rgba(var(--bs-primary-rgb), 0.45); }
.navbar .nav-tabs .nav-link.active { color: var(--bs-emphasis-color); background: transparent; border-bottom-color: var(--bs-primary); }
/* The sidebar stays in view below the header */
@media (min-width: 992px) {
  /* The collapse button stays in view below the header, at the right edge of the sidebar, or at the left edge when it is collapsed */
  .bslib-page-sidebar .bslib-sidebar-layout > .collapse-toggle { position: sticky; top: calc(var(--header-height, 0px) + 0.5rem); right: auto;
    align-self: start; justify-self: end; margin: 0.5rem 1rem 0 0; }
  .bslib-page-sidebar .bslib-sidebar-layout.sidebar-collapsed > .collapse-toggle { top: calc(var(--header-height, 0px) + 0.5rem); right: auto;
    justify-self: start; margin: 0.5rem 0 0 0.5rem; }
  .bslib-sidebar-layout:not(.sidebar-collapsed) > .sidebar { position: sticky; top: var(--header-height, 0px); align-self: start;
    height: calc(100vh - var(--sidebar-top, 0px)); overflow-y: auto; overflow-x: hidden; }
}
.apply-bar { display: flex; flex-direction: column; align-items: center; margin: 1rem 0; }
/* North over West and East, South under them, as in the Copernicus data store */
.region-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 9rem)); column-gap: 0.75rem; }
.region-north { grid-area: 1 / 2; } .region-west { grid-area: 2 / 1; }
.region-east { grid-area: 2 / 3; } .region-south { grid-area: 3 / 2; }
"""




# Plays the days of a map at a chosen rate. Each day is sent once the previous map is drawn, so that
# asking for more than the machine can draw slows the playback rather than skipping days.
PLAYER = """
function makePlayer(prefix, sliderId, dateId) {
  const element = (name) => document.getElementById(`${prefix}_${name}`);
  return {
  prefix: prefix,
  dateId: dateId,
  rates: [0.5, 1, 2, 3, 4, 5, 6, 8, 10, 15, 20],
  rate: 5,  // Index in rates: 5 fps
  playing: false,
  sentAt: 0,
  lastDrawn: 0,
  actual: null,
  timer: null,
  watchdog: null,
  show() {
    element('play').textContent = this.playing ? '⏸' : '▶';
    element('play').title = this.playing ? 'Pause' : 'Play';
    const rate = this.rates[this.rate];
    const measured = this.playing && this.actual !== null ? ` (actual ${this.actual.toFixed(1)})` : '';
    element('rate').textContent = `${rate} fps${measured}`;
    element('slower').disabled = element('much_slower').disabled = this.rate === 0;
    element('faster').disabled = element('much_faster').disabled = this.rate === this.rates.length - 1;
  },
  next() {
    const slider = $('#' + sliderId).data('ionRangeSlider');
    const day = slider.result.from >= slider.result.max ? slider.result.min : slider.result.from + 1;
    slider.update({from: day});
    Shiny.setInputValue(sliderId, day, {priority: 'event'});
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
    const slider = $('#' + sliderId).data('ionRangeSlider');
    slider.update({from: slider.result.min});
    Shiny.setInputValue(sliderId, slider.result.min, {priority: 'event'});
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
}
// By the plot each plays
const players = {map: makePlayer('player', 'day', 'day_date'), preview_map: makePlayer('preview_player', 'preview_day', 'preview_day_date')};
for (const player of Object.values(players)) {
  $(document).on('click', `#${player.prefix}_first`, () => player.first());
  $(document).on('click', `#${player.prefix}_play`, () => player.toggle());
  $(document).on('click', `#${player.prefix}_much_slower`, () => player.change(-3));
  $(document).on('click', `#${player.prefix}_slower`, () => player.change(-1));
  $(document).on('click', `#${player.prefix}_faster`, () => player.change(1));
  $(document).on('click', `#${player.prefix}_much_faster`, () => player.change(3));
}
// In the capture phase, as the Run button does not pass its clicks on
document.addEventListener('click', (event) => { if (event.target.closest('#run')) players.map.pause(); }, true);
// The dotted line of the preview's time series follows the day of the map in the browser, without a redraw
$(document).on('shiny:inputchanged', (event) => {
  if (event.name !== 'preview_day') return;
  const plot = document.getElementById('preview_cell_plot');
  const index = plot && plot.layout && plot.layout.shapes ? plot.layout.shapes.findIndex(s => s.type === 'line' && s.yref === 'paper') : -1;
  const dates = plot && plot.data && plot.data.length ? plot.data[0].x : null;
  if (index < 0 || !dates || !dates[event.value - 1]) return;
  Plotly.relayout(plot, {[`shapes[${index}].x0`]: dates[event.value - 1], [`shapes[${index}].x1`]: dates[event.value - 1]});
});
// Another file in the preview has other days, or none
$(document).on('shiny:inputchanged', (event) => { if (event.name === 'preview_file') players.preview_map.pause(); });
$(document).on('shiny:sessioninitialized', () => Object.values(players).forEach(player => player.show()));
"""
PLOT_HANDLER = """
// The colours around the data follow the theme; those of the data and of the map do not.
// The server sends the light ones; plain plots are those with a white plot area.
const PLOT_COLOURS = {
  light: {paper: 'white', text: '#52514e', grid: '#e6e5e0', legend: 'rgba(255,255,255,0.8)'},
  dark: {paper: '#212529', text: '#c9c8c2', grid: '#3b3f44', legend: 'rgba(33,37,41,0.8)'},
};
function plotColours() {
  return PLOT_COLOURS[document.documentElement.getAttribute('data-bs-theme') === 'dark' ? 'dark' : 'light'];
}
function isText(colour) {
  return colour === PLOT_COLOURS.light.text || colour === PLOT_COLOURS.dark.text;
}
function themeLayout(layout, plain) {
  const colours = plotColours();
  layout.paper_bgcolor = colours.paper;
  layout.font = {...(layout.font || {}), color: colours.text};
  if (plain) layout.plot_bgcolor = colours.paper;
  // Every axis, also those of plots side by side (xaxis2, yaxis2...)
  for (const axis of Object.keys(layout).filter(key => /^[xy]axis\\d*$/.test(key))) if (layout[axis]) layout[axis].gridcolor = colours.grid;
  if (layout.legend) layout.legend.bgcolor = colours.legend;
  (layout.shapes || []).forEach(function(shape) { if (shape.line && isText(shape.line.color)) shape.line.color = colours.text; });
  return layout;
}
// A plot already drawn, when the theme changes
function themePlot(plot) {
  if (!plot.layout) return;
  const axes = Object.keys(plot.layout).filter(key => /^[xy]axis\\d*$/.test(key));
  const update = themeLayout({font: plot.layout.font, legend: plot.layout.legend ? {} : undefined,
                              ...Object.fromEntries(axes.map(axis => [axis, {}])),
                              shapes: JSON.parse(JSON.stringify(plot.layout.shapes || []))}, plot.plain);
  const flat = {paper_bgcolor: update.paper_bgcolor, font: update.font, shapes: update.shapes};
  for (const axis of axes) flat[`${axis}.gridcolor`] = update[axis].gridcolor;
  if (plot.plain) flat.plot_bgcolor = update.plot_bgcolor;
  if (update.legend) flat['legend.bgcolor'] = update.legend.bgcolor;
  Plotly.relayout(plot, flat);
}
// Gaps between cells, showing as a grid, once the cells are large enough on screen
const GRID_MIN_PIXELS = 10;
const mapZoom = {map: {}, preview_map: {}};
// The input a click on each map sets
const cellInputs = {map: 'cell', preview_map: 'preview_cell'};
function rememberZoom(zoom, event) {
  if (event['xaxis.autorange'] || event['yaxis.autorange']) {
    delete zoom.x;
    delete zoom.y;
  }
  if ('xaxis.range[0]' in event) zoom.x = [event['xaxis.range[0]'], event['xaxis.range[1]']];
  if ('yaxis.range[0]' in event) zoom.y = [event['yaxis.range[0]'], event['yaxis.range[1]']];
}
function updateCellGrid(plot) {
  const index = plot._fullData.findIndex(trace => trace.type === 'heatmap');
  if (index < 0) return;
  const trace = plot._fullData[index];
  // A stripe one cell wide east-west has a start and a cell size instead of its single longitude
  const width = trace.x && trace.x.length > 1 ? Math.abs(trace.x[1] - trace.x[0]) : trace.dx;
  const pixels = width * plot._fullLayout.xaxis._m;
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
// A plot drawn while its tab was hidden has no size: fit the plots when their tab is shown again.
// A map playing in a tab that is now hidden stops.
$(document).on('shown.bs.tab', function() {
  for (const id of ['map', 'cell_plot', 'envelope_plot', 'preview_map', 'preview_cell_plot', 'region_map', 'sa_indices', 'sa_pairs', 'sa_map', 'sa_climate', 'sa_monthly', 'sa_ages']) {
    const plot = document.getElementById(id);
    if (plot && plot.data && plot.offsetParent !== null) Plotly.Plots.resize(plot);
  }
  for (const [id, player] of Object.entries(players)) {
    if (player.playing && document.getElementById(id).offsetParent === null) player.pause();
  }
});
Shiny.addCustomMessageHandler('plot', function(message) {
  const player = players[message.id];  // Only the maps have one
  const layout = message.figure.layout;
  const plain = layout.plot_bgcolor === 'white';
  themeLayout(layout, plain);
  if (player) {
    const before = document.getElementById(message.id);
    // Another grid, or another kind of plot, starts from its full view
    const view = (layout.meta || {}).view;
    if (before.view !== view) {
      mapZoom[message.id] = {};
      before.view = view;
    }
    if (before.colourBar) message.figure.data.filter(t => t.type === 'heatmap').forEach(t => { t.colorbar = {...(t.colorbar || {}), ...before.colourBar}; });
    // A new figure from the server keeps the zoom of the map
    const zoom = mapZoom[message.id];
    if (zoom.x) layout.xaxis.range = zoom.x;
    if (zoom.y) layout.yaxis.range = zoom.y;
  }
  // A figure that says how tall it is (e.g. two panels, or three with the drivers) sets the height of its container:
  // the responsive resizing of Plotly sizes a plot to its container, which would otherwise squeeze it back to the
  // container's minimum height when the window or the browser zoom changes. A later figure without one gives it back.
  const container = document.getElementById(message.id);
  if (layout.height) {
    container.style.height = layout.height + 'px';
    container.heightFromFigure = true;
  } else if (container.heightFromFigure) {
    container.style.height = '';
    container.heightFromFigure = false;
  }
  // On the region map, a way back to drawing after zooming
  const extra = message.id === 'region_map' ? {modeBarButtonsToAdd: ['drawrect'], modeBarButtonsToRemove: ['select2d', 'lasso2d']} : {};
  const drawing = Plotly.react(message.id, message.figure.data, layout,
                               {responsive: true, displaylogo: false, doubleClick: 'reset', ...extra});
  if (player) {
    document.getElementById(player.dateId).textContent = (layout.meta || {}).date || '';
    drawing.then(() => player.drawn());
  }
  const plot = document.getElementById(message.id);
  plot.plain = plain;
  // A map without a player, as those of the sensitivity analysis: its colour bar beside it too
  if (!player && (layout.meta || {}).colourBarBeside && !plot.colourBarPlaced) {
    plot.colourBarPlaced = true;
    plot.on('plotly_afterplot', function() { placeColourBar(plot); });
  }
  if (!player && (layout.meta || {}).colourBarBeside) drawing.then(() => placeColourBar(plot));
  if (player) updateCellGrid(plot);
  if (player && !plot.clickReported) {
    plot.clickReported = true;
    plot.on('plotly_relayout', function(event) { rememberZoom(mapZoom[message.id], event); updateCellGrid(plot); });
    plot.on('plotly_afterplot', function() { placeColourBar(plot); });
    // A double click resets the view, and must not select the cell under it
    let pendingClick = null;
    plot.on('plotly_click', function(event) {
      const point = event.points[0];
      clearTimeout(pendingClick);
      // The second click of a double click: the browser counts them
      if (event.event.detail > 1) return;
      pendingClick = setTimeout(function() {
        Shiny.setInputValue(cellInputs[message.id], {lon: point.x, lat: point.y}, {priority: 'event'});
      }, 350);
    });
    plot.on('plotly_doubleclick', function() { clearTimeout(pendingClick); });
  }
  if (message.id === 'region_map' && !plot.regionReported) {
    plot.regionReported = true;
    plot.on('plotly_relayout', function(event) { reportRegion(plot, event); });
    plot.on('plotly_click', function(event) {
      const point = event.points[0];
      Shiny.setInputValue('region_click', {lon: point.x, lat: point.y}, {priority: 'event'});
    });
  }
});
// The region map, for a subregion: the rectangle drawn on it. Only one rectangle is ever on the map: the one
// drawn is removed at once, and the server draws the region it gives, named 'region'.
function reportRegion(plot, event) {
  const shape = (event.shapes || []).filter(s => s.type === 'rect' && s.name !== 'region').pop();
  if (!shape) return;
  Plotly.relayout(plot, {shapes: plot.layout.shapes.filter(s => s.type !== 'rect' || s.name === 'region')});
  Shiny.setInputValue('region_drawn', {x0: shape.x0, x1: shape.x1, y0: shape.y0, y1: shape.y1}, {priority: 'event'});
}
"""


CLOSED_HANDLER = """
Shiny.addCustomMessageHandler('closed', function(message) {
  document.body.innerHTML = '<p style="margin: 2rem; font-family: sans-serif;">The GUI is closed. You can close this tab.</p>';
  window.close();
});
"""
# Labels only: the value of a slider stays as it is until the slider is moved
SLIDER_FORMAT = """
// Decimals of each parameter slider, sent by the server whenever the sliders are made
const sliderDecimals = {};
Shiny.addCustomMessageHandler('slider_decimals', function(decimals) {
  Object.assign(sliderDecimals, decimals);
  Object.keys(decimals).forEach(function(id) { if ($('#' + id).data('ionRangeSlider')) formatSlider(id); });
});
$(document).on('shiny:bound', function(event) {
  if (event.target.id in sliderDecimals) setTimeout(function() { formatSlider(event.target.id); }, 0);
});
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


# The dots of the preview: a row selects its dot, its cross removes it
DOTS_HANDLER = """
$(document).on('click', '.dot-remove', function(event) {
  event.stopPropagation();
  Shiny.setInputValue('preview_dot_remove', {index: Number(this.dataset.index)}, {priority: 'event'});
});
$(document).on('click', '.dot-row', function() {
  Shiny.setInputValue('preview_dot_select', {index: Number(this.dataset.index)}, {priority: 'event'});
});
$(document).on('keydown', '.dot-row', function(event) {
  if ((event.key === 'Enter' || event.key === ' ') && event.target === this) {
    event.preventDefault();
    Shiny.setInputValue('preview_dot_select', {index: Number(this.dataset.index)}, {priority: 'event'});
  }
});
"""


BROWSER_HANDLER = """
$(document).on('click', '.browse-entry', function(event) {
  event.preventDefault();
  Shiny.setInputValue('browser_pick', {name: this.dataset.name, folder: this.dataset.folder === '1'}, {priority: 'event'});
});
"""


# The tabs move into the header, a tab opens at its top, and the sidebar is as high as the visible part of its column,
# so that one scroll reaches its last button
SIDEBAR_FIT = """
function fitSidebar() {
  const layout = document.querySelector('.bslib-sidebar-layout');
  const header = document.querySelector('.bslib-page-sidebar > .navbar');
  if (!layout || !header) return;
  const root = document.documentElement.style;
  root.setProperty('--header-height', header.offsetHeight + 'px');
  root.setProperty('--sidebar-top', Math.max(layout.getBoundingClientRect().top, header.offsetHeight) + 'px');
}
$(function() {
  const header = document.querySelector('.bslib-page-sidebar > .navbar');
  const tabs = document.querySelector('ul.nav.shiny-tab-input');
  if (header && tabs) header.appendChild(tabs);
  fitSidebar();
});
window.addEventListener('scroll', fitSidebar, {passive: true});
window.addEventListener('resize', fitSidebar);
// A main tab opens at its top, whatever the scroll position of the one before
document.addEventListener('shown.bs.tab', function(event) {
  if (event.target.closest('ul#tab')) window.scrollTo(0, 0);
});
$(document).on('shiny:connected shiny:value', fitSidebar);
"""


PARAMETER_STYLE = """
/* A dot on a moved slider, and on its section and tab: amber, which reads on the light and the dark theme */
.param-moved > .form-group .param-label::after, .param-sections .accordion-item.param-moved .accordion-title::after,
#param_tab .nav-link.param-moved::after { content: ""; display: inline-block; width: 0.5em; height: 0.5em; border-radius: 50%;
  background: #d97706; margin-left: 0.4em; vertical-align: middle; }
.dots { max-width: 40rem; margin: 0.5rem auto 1rem; }
.dot-row { display: flex; align-items: center; gap: 0.6rem; padding: 0.2rem 0.5rem; border: 1px solid transparent; border-radius: 4px; cursor: pointer; }
.dot-row:hover { background: var(--bs-tertiary-bg); }
.dot-row.selected { border-color: var(--bs-primary); background: var(--bs-tertiary-bg); }
.dot-swatch { width: 0.9em; height: 0.9em; border-radius: 2px; flex: none; }
.dot-remove { margin-left: auto; padding: 0 0.4rem; }
.param-label { cursor: help; }
.tooltip-inner:has(.param-info) { max-width: 360px; text-align: left; }
.param-source { margin-top: 0.4em; font-size: 0.85em; font-style: italic; }
.card > .card-header { font-size: 1.15rem; font-weight: 600; color: var(--bs-primary); letter-spacing: 0.02em;
  background: transparent; border-bottom: 2px solid rgba(var(--bs-primary-rgb), 0.35); }
.card.no-run-yet > .card-header { font-size: 1rem; }
"""


# Marks a moved slider, its section and its tab, so that a change in a folded section is not hidden
PARAMETER_MARKS = """
function markParameters() {
  document.querySelectorAll('.param-slider').forEach(function(box) {
    const input = box.querySelector('input.js-range-slider');
    if (!input) return;
    const value = parseFloat(input.value);
    const moved = Math.abs(value - parseFloat(box.dataset.start)) >= parseFloat(box.dataset.step) / 2;
    box.classList.toggle('param-moved', moved);
  });
  document.querySelectorAll('.param-sections .accordion-item').forEach(function(item) {
    item.classList.toggle('param-moved', item.querySelector('.param-slider.param-moved') !== null);
  });
  document.querySelectorAll('#param_tab .nav-link').forEach(function(link) {
    const pane = document.querySelector(`.tab-pane[data-value="${link.dataset.value}"]`);
    link.classList.toggle('param-moved', pane !== null && pane.querySelector('.param-slider.param-moved') !== null);
  });
}
$(document).on('shiny:inputchanged', function(event) { if (event.name.startsWith('param_')) setTimeout(markParameters, 0); });
$(document).on('shiny:value', function(event) { if (event.name === 'parameter_sliders') setTimeout(markParameters, 0); });
"""
