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
THEME_STYLE = """
.logo { background: white; border-radius: 4px; padding: 2px; }
.sidebar-heading { font-size: 0.8rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.04em;
                   color: var(--bs-secondary-color); margin: 0.5rem 0 0.25rem; }
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
  rate: 2,
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
  for (const axis of ['xaxis', 'yaxis']) if (layout[axis]) layout[axis].gridcolor = colours.grid;
  if (layout.legend) layout.legend.bgcolor = colours.legend;
  (layout.shapes || []).forEach(function(shape) { if (shape.line && isText(shape.line.color)) shape.line.color = colours.text; });
  return layout;
}
// A plot already drawn, when the theme changes
function themePlot(plot) {
  if (!plot.layout) return;
  const update = themeLayout({font: plot.layout.font, legend: plot.layout.legend ? {} : undefined,
                              xaxis: {}, yaxis: {}, shapes: JSON.parse(JSON.stringify(plot.layout.shapes || []))}, plot.plain);
  const flat = {paper_bgcolor: update.paper_bgcolor, font: update.font, 'xaxis.gridcolor': update.xaxis.gridcolor,
                'yaxis.gridcolor': update.yaxis.gridcolor, shapes: update.shapes};
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
// A plot drawn while its tab was hidden has no size: fit the plots when their tab is shown again.
// A map playing in a tab that is now hidden stops.
$(document).on('shown.bs.tab', function() {
  for (const id of ['map', 'cell_plot', 'envelope_plot', 'preview_map', 'preview_cell_plot']) {
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
  const drawing = Plotly.react(message.id, message.figure.data, layout,
                               {responsive: true, displaylogo: false, doubleClick: 'reset'});
  if (player) {
    document.getElementById(player.dateId).textContent = (layout.meta || {}).date || '';
    drawing.then(() => player.drawn());
  }
  const plot = document.getElementById(message.id);
  plot.plain = plain;
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
});
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


BROWSER_HANDLER = """
$(document).on('click', '.browse-entry', function(event) {
  event.preventDefault();
  Shiny.setInputValue('browser_pick', {name: this.dataset.name, folder: this.dataset.folder === '1'}, {priority: 'event'});
});
"""


PARAMETER_STYLE = """
.param-default .irs--shiny .irs-bar, .param-default .irs--shiny .irs-single,
.param-default .irs--shiny .irs-handle { background: #8a8984; border-color: #8a8984; }
.param-default .irs--shiny .irs-single:before { border-top-color: #8a8984; }
.param-default label { color: var(--bs-secondary-color); }
.param-swatch { display: inline-block; width: 0.8em; height: 0.8em; border-radius: 2px; margin-right: 0.3em; }
.param-label { cursor: help; }
.tooltip-inner:has(.param-info) { max-width: 360px; text-align: left; }
.param-source { margin-top: 0.4em; font-size: 0.85em; font-style: italic; }
"""
