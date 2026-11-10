"""The calibration card of the Calibration tab: the objectives added from the comparison above, what is calibrated (for
now the temperature offsets of chosen cells), how (sampler, trials, runs at a time), Run, Cancel and Resume, and the
progress: the objectives trial by trial and the best trial against the data (calibration_engine.py)."""

import asyncio
import os
from dataclasses import replace
from types import SimpleNamespace

import netCDF4
import numpy as np
import pandas as pd
import xarray as xr
import plotly.graph_objects as go
from shiny import reactive, render, ui
from sqlalchemy.exc import SQLAlchemyError

from .calibration_engine import (
    OLD_CALIBRATION, SAMPLER_LINKS, SAMPLERS, CalibrationError, best_trials, calibration_label, calibrations_dir, create_calibration,
    is_running, list_calibrations, read_calibration, resumable, run_calibration, status_of, trial_comparison, trial_folder, trials_table,
)
from .calibration_data import DataError
from .calibration_model import DRIVER_PERIODS, DRIVERS, driver_panel
from .calibration_results import FIGURES, ResultsError, figure_help, results_figure
from .calibration_steps import STATISTICS
from .config import ConfigError
from .cells import cell_areas
from .driving import LAT_NAMES, LON_NAMES, climatology, first_name, open_field
from .layout import HA_BELOW_ONE, OUTPUT_FLAGS, UNIT_LABELS, parameter_label, sections, with_tip
from .plots import calibration_history_figure, comparison_figure, message_figure, regions_figure, send_figure
from .region import region_ranges
from .runner import NETCDF_LOCK
from .shapes import ShapeError, areas, outlines, read_shapes
from .sensitivity import SampledParameter
from .sensitivity_runs import StudyState
from .outcome import run_name_problem

DRIVER_FLAGS = ("out_vect", "out_vecinfc")  # Written by every run of a calibration, for its possible drivers
MAX_CELLS = 20  # Temperature offsets are calibrated for at most this many cells or regions
MAX_SIMULATED = 5000  # And the cells of the setup, grouped in regions or not, at most this many
REFRESH_SECONDS = 3  # How often the progress of a calibration is drawn again while it runs


def calibration_run_card():
    return ui.card(
        ui.card_header("Calibration with Optuna"),
        ui.p("Runs the model many times with the setup applied in tab 1, the HA and seed of the sidebar and the parameters of "
             "the sliders, each time with other values of what is calibrated, chosen by ",
             ui.a("Optuna", href="https://optuna.org/", target="_blank"),
             " from the trials before: every run is processed and compared with the data as each objective says, and Optuna "
             "looks for the values that do best on all the objectives together (the Pareto front).", class_="small text-muted mb-2"),
        ui.h6("Objectives"),
        ui.output_ui("cal_objectives"),
        ui.h6("What to calibrate", class_="mt-2"),
        ui.input_switch("cal_offsets", with_tip("Temperature offsets", "A shift dT of the temperature of each cell, or region of "
                        "cells, ticked, e.g. for the temperature where people live within a coarse cell. They keep the order of their "
                        "mean temperatures (coolest first): the first gets dT₁, each next one a gap of at least 0 above the one "
                        "before, so no trial changes which is warmer."), value=True),
        ui.panel_conditional("input.cal_offsets", ui.div(
            ui.input_radio_buttons("cal_regions", None, {"cells": "One offset per cell", "boxes": "One offset per region: the cells "
                                   "in each box of"}, selected="cells", inline=True),
            ui.panel_conditional("input.cal_regions === 'boxes'", ui.input_numeric("cal_region_size", None, value=0.5, min=0.01, step=0.05,
                                                                                     width="7rem"), ui.span("degrees", class_="small ms-1")),
            class_="d-flex flex-wrap align-items-center gap-2"),
            ui.output_ui("cal_cells"), ui.output_ui("cal_regions_shapes_switch"), ui.div(id="cal_regions_map", style="min-height: 420px;"),
            ui.layout_columns(
            ui.input_numeric("cal_dt_low", "dT₁ from [°C]", value=-3.0, step=0.5),
            ui.input_numeric("cal_dt_high", "dT₁ to [°C]", value=3.0, step=0.5),
            ui.output_ui("cal_gap_inputs"),
            col_widths=(3, 3, 6), fill=False), ui.output_ui("cal_order_switch"), ui.output_ui("cal_offset_equation")),
        ui.tags.strong(with_tip("Model parameters", "Tick a parameter to calibrate it within a range, sampled uniformly or "
                                "log-uniformly (for ranges over orders of magnitude), in the units of its slider; at first the range "
                                "of the slider. Those not ticked keep their slider value."), class_="small d-block mt-2"),
        ui.output_ui("cal_parameters"),
        ui.layout_columns(
            ui.div(
                ui.h6("Optuna"),
                ui.input_select("cal_sampler", "Sampler", {key: text.split(":")[0] for key, text in SAMPLERS.items()}, selected="tpe"),
                ui.output_ui("cal_sampler_info"),
                ui.input_numeric("cal_trials", "Trials", value=100, min=1, step=10),
                ui.input_numeric("cal_startup", with_tip("Start-up trials", "Drawn at random before the sampler starts to learn from "
                                 "the trials done (TPE)."), value=10, min=1, step=1),
            ),
            ui.div(
                ui.h6("Runs"),
                ui.input_numeric("cal_seeds", with_tip("Seeds per trial", "Each trial runs every seed, from the sidebar seed up; "
                                 "the objectives compare the median of the seeds, each processed."), value=1, min=1, step=1),
                ui.input_numeric("cal_threads", with_tip("Threads per run", "CPU threads of each run, at first those of the setup. "
                                 "Results depend on the number: it is kept with the calibration, and a resumed one uses it too."),
                                 value=1, min=1, step=1),
                ui.input_numeric("cal_parallel", with_tip("Runs at the same time", "Each with the threads per run above. The model "
                                 "is built once, by the first run."), value=1, min=1, step=1),
                ui.input_text("cal_name", "Calibration name (optional)", placeholder="e.g. two_cells_dT"),
            ),
            ui.div(
                ui.h6("Run"),
                ui.output_ui("cal_run_summary"),
                ui.div(
                    ui.input_task_button("cal_run", "Run calibration", label_busy="Running…", class_="btn-primary flex-fill"),
                    ui.input_action_button("cal_cancel", "Cancel", class_="flex-fill", disabled=True),
                    class_="d-flex gap-2 mt-2",
                ),
            ),
            col_widths=(4, 4, 4), class_="mt-2",
        ),
        ui.output_ui("cal_run_status"),
        ui.h6("Calibrations", class_="mt-3"),
        ui.p("The running one, or one chosen here: its trials are kept in its folder, and a cancelled one resumes where it stopped.",
             class_="small text-muted mb-1"),
        ui.layout_columns(
            ui.input_select("cal_previous", None, {}, width="100%"),
            ui.input_action_button("cal_resume", "Resume", class_="w-100"),
            col_widths=(10, 2),
        ),
        ui.output_ui("cal_previous_info"),
        ui.div(id="cal_history_plot", style="min-height: 380px;"),
        ui.output_ui("cal_front_sort_choice"),
        ui.output_ui("cal_front"),
        ui.div(
            ui.h6(with_tip("A trial of the Pareto front", "One of the best trade-offs so far (the first of the front at first), "
                           "against the data of an objective; with the possible drivers of its run below it, to see how they "
                           "differ from where the calibration started."), class_="mb-1"),
            ui.output_ui("cal_best_choice"),
            ui.tags.strong(with_tip("Possible drivers", "Rainfall and temperature as the run of this trial read them, and the vector "
                                    "densities it gave (the mean over its simulated cells), each processed on its own and drawn below, "
                                    "within the periods the model and the data share. All the panels zoom together."), class_="small"),
            *[driver_controls(name, "cal_best_driver") for name in DRIVERS],
            ui.output_ui("cal_best_problem"),
            ui.div(id="cal_best_plot", style="min-height: 380px;"),
            class_="border rounded p-2 mt-3",
        ),
        ui.div(
            ui.h6(with_tip("Where the calibration started", "Its first trial, with no temperature offset when the ranges allow it, "
                           "processed and scored like every trial, against the same data as the trial above; with the possible "
                           "drivers of its run below it, to see what the calibration changes."), class_="mb-1"),
            ui.tags.strong(with_tip("Possible drivers", "Rainfall and temperature as the run of the start trial read them, and the "
                                    "vector densities it gave (the mean over its simulated cells), each processed on its own and drawn "
                                    "below, within the periods the model and the data share. All the panels zoom together."),
                           class_="small"),
            *[driver_controls(name, "cal_start_driver") for name in DRIVERS],
            ui.output_ui("cal_start_problem"),
            ui.div(id="cal_start_plot", style="min-height: 380px;"),
            class_="border rounded p-2 mt-3",
        ),
        ui.div(
            ui.h6("Results", class_="mb-1"),
            ui.layout_columns(
                ui.input_select("cal_figure", "Figure", {kind: spec[0] for kind, spec in FIGURES.items()}, selected="distributions"),
                ui.output_ui("cal_figure_objective"),
                col_widths=(6, 6), fill=False,
            ),
            ui.output_ui("cal_figure_help"),
            ui.div(id="cal_results_plot", style="min-height: 480px;"),
            class_="border rounded p-2 mt-3",
        ),
        class_="mt-3",
    )


def driver_controls(name, prefix="cal_driver"):
    """A row of choices for one possible driver: show it, into which periods, by which statistic, and as a climatology.
    The ids are {prefix}_{name}, {prefix}_{name}_period, _how and _climatology."""
    label, how = DRIVERS[name]
    return ui.layout_columns(
        ui.input_switch(f"{prefix}_{name}", label, value=False),
        ui.input_select(f"{prefix}_{name}_period", None, DRIVER_PERIODS, selected="month"),
        ui.input_select(f"{prefix}_{name}_how", None, {key: STATISTICS[key] for key in ("sum", "mean", "min", "max")}, selected=how),
        ui.input_switch(f"{prefix}_{name}_climatology", "Climatology by month", value=False),
        col_widths=(3, 3, 3, 3), fill=False, class_="align-items-center",
    )


def driver_choices(input, prefix="cal_driver"):
    """{name: (period, how, climatology)} of the drivers switched on."""
    return {name: (input[f"{prefix}_{name}_period"](), input[f"{prefix}_{name}_how"](), input[f"{prefix}_{name}_climatology"]())
            for name in DRIVERS if f"{prefix}_{name}" in input and input[f"{prefix}_{name}"]()}


def paired_span(data, labels):
    """(first, last) dates of the dated periods the model and the data share, or (None, None) for other shapes."""
    if data.shape != "dated":
        return None, None
    shared = set(labels)
    rows = [i for i in range(len(data)) if data.label(i) in shared]
    return (str(pd.Timestamp(data.index["start"].iloc[rows[0]]).date()), str(pd.Timestamp(data.index["end"].iloc[rows[-1]]).date()))


CALIBRATED_DISTRIBUTIONS = {"uniform": "Uniform", "loguniform": "Log-uniform"}


def _parameter_row(name, spec, value):
    """A checkbox to calibrate the parameter and, once ticked, how it is sampled and within which range."""
    use = f"input.cal_use_{name}"
    return ui.div(
        ui.div(ui.input_checkbox(f"cal_use_{name}", parameter_label(spec.get("label", name) + UNIT_LABELS.get(spec.get("display"), ""), spec),
                                 value=False), class_="sa-name"),
        ui.panel_conditional(use, ui.div(
            ui.input_select(f"cal_dist_{name}", None, CALIBRATED_DISTRIBUTIONS, selected="uniform"),
            ui.input_numeric(f"cal_low_{name}", None, value=float(f"{spec['min']:.4g}"), step="any"),
            ui.input_numeric(f"cal_high_{name}", None, value=float(f"{spec['max']:.4g}"), step="any"),
            class_="sa-fields")),
        ui.panel_conditional(f"!{use}", ui.span(f"Not calibrated: {value:.4g}, as on its slider", class_="small text-muted")),
        class_="sa-row",
    )


def offset_cells(config):
    """[{lat, lon, mean, people}] of the simulated cells of a setup (people, and temperature), with their mean temperature
    over its period and their people as the model counts them, the coolest first; or a str saying why not."""
    inputs = config.inputs
    try:
        pop = open_field(inputs["pop_file"], "pop_file")
        lon, lat = pop["lon"].values, pop["lat"].values
        ranges = region_ranges(lon, lat, config.region)
        (lon_first, lon_end), (lat_first, lat_end) = ranges if ranges is not None else ((0, len(lon)), (0, len(lat)))
        pop = pop.isel(lat=slice(lat_first, lat_end), lon=slice(lon_first, lon_end))
        populated = np.isfinite(pop.values) & (np.nan_to_num(pop.values) > 0)
        if populated.sum() > MAX_SIMULATED:
            return (f"The setup simulates {int(populated.sum()):,} cells: temperature offsets are for a region of at most "
                    f"{MAX_SIMULATED:,} cells. Choose a subregion in Setup.")
        # The people of each cell, with the cell areas of the model (from the population file, which open_field sorts)
        areas = xr.DataArray(cell_areas(inputs["pop_file"]), dims=("lat", "lon"),
                             coords={"lat": _file_axis(inputs["pop_file"], "lat"), "lon": _file_axis(inputs["pop_file"], "lon")})
        areas = areas.sortby(["lat", "lon"])
        people = (pop * areas.sel(lat=pop["lat"], lon=pop["lon"])).values
        period = config.period or {}
        mean = climatology(inputs["temp_file"], "temp_file", period.get("start"), period.get("end"))
        mean = mean.sel(lat=pop["lat"], lon=pop["lon"], method="nearest")
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as error:
        return f"The cells cannot be read: {error}"
    cells = []
    for i, j in zip(*np.nonzero(populated)):
        value = float(mean.values[i, j])
        if np.isfinite(value):
            cells.append({"lat": float(pop["lat"].values[i]), "lon": float(pop["lon"].values[j]), "mean": value,
                          "people": float(people[i, j])})
    return sorted(cells, key=lambda cell: cell["mean"]) or "The setup has no simulated cell with a temperature."


def _file_axis(path, axis):
    """The coordinate of a file as it is stored (cell_areas follows the file's order)."""
    with netCDF4.Dataset(path) as data:
        return np.asarray(data[first_name(LAT_NAMES if axis == "lat" else LON_NAMES, data.variables)][:], dtype="f8")


def regions(cells, size=None):
    """The units whose temperature is offset: each cell (size None), or regions, the cells in each box of `size` degrees
    (edges on multiples of it), as {lat, lon (the centre of the box), members, mean (weighted by people), people, label},
    the coolest first."""
    if not size:
        return [{**cell, "label": f"{cell['lat']:g}°N, {cell['lon']:g}°E"} for cell in cells]
    boxes = {}
    for cell in cells:
        key = (int(np.floor(cell["lat"] / size + 1e-9)), int(np.floor(cell["lon"] / size + 1e-9)))
        boxes.setdefault(key, []).append(cell)
    found = []
    for (row, column), inside in boxes.items():
        people = np.array([cell["people"] for cell in inside])
        means = np.array([cell["mean"] for cell in inside])
        lat, lon = round((row + 0.5) * size, 6), round((column + 0.5) * size, 6)
        found.append({"lat": lat, "lon": lon, "members": [{"lat": c["lat"], "lon": c["lon"]} for c in inside],
                      "mean": float(np.average(means, weights=people)) if people.sum() > 0 else float(means.mean()),
                      "people": float(people.sum()), "label": f"box at {lat:g}°N, {lon:g}°E ({len(inside)} cells)"})
    return sorted(found, key=lambda region: region["mean"])


def _clock(seconds):
    seconds = int(round(seconds))
    return f"{seconds // 3600}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


def calibration_run_server(input, output, session, setup, objectives, overrides, selected_output, busy, agents, ha, slider_setup):
    """The server side of the card. objectives() are those added in the comparison card; busy() is true while a single run
    or an analysis goes on; slider_setup() the sliders, with their ranges and starts. Returns running() and cancel() for the
    rest of the app."""
    state = StudyState()

    @output(suspend_when_hidden=False)
    @render.ui
    def cal_parameters():
        sliders = slider_setup()
        groups = []
        for group, found in sections(sliders["sliders"]).items():
            rows = []
            for section, names in found.items():
                if section != group:
                    rows.append(ui.h6(section, class_="mt-2 mb-1 small fw-semibold"))
                rows += [_parameter_row(name, sliders["sliders"][name], sliders["defaults"][name]) for name in names]
            header = ui.div(ui.span("Sampled", class_="sa-dist"), ui.span("Minimum"), ui.span("Maximum"), class_="sa-head")
            groups.append(ui.accordion_panel(group, header, *rows))
        return ui.accordion(*groups, open=False, multiple=True)

    def chosen_parameters():
        """The parameters ticked, as typed: SampledParameter, in the units of their sliders."""
        found = []
        for name in slider_setup()["sliders"]:
            if f"cal_use_{name}" in input and input[f"cal_use_{name}"]():
                found.append(SampledParameter(name, input[f"cal_dist_{name}"](), input[f"cal_low_{name}"](), input[f"cal_high_{name}"]()))
        return found
    changed = reactive.value(0)
    last = reactive.value(None)  # The record of the last calibration run in this session, or "error"
    running_folder = reactive.value(None)
    to_select = reactive.value(None)

    @reactive.calc
    def cells():
        return offset_cells(setup())

    @reactive.calc
    def units():
        """The cells, or the regions, whose temperature can be offset; or a str saying why not."""
        found = cells()
        if isinstance(found, str):
            return found
        size = input.cal_region_size() if input.cal_regions() == "boxes" else None
        if input.cal_regions() == "boxes" and not (isinstance(size, (int, float)) and size > 0):
            return "Give the size of the boxes, in degrees."
        found = regions(found, size)
        if len(found) > MAX_CELLS:
            what = "regions" if size else "cells"
            return (f"The setup has {len(found):,} {what} to offset: at most {MAX_CELLS} can be calibrated. "
                    + ("Use larger boxes, or a subregion in Setup." if size else "Use regions (boxes of cells), or a subregion in Setup."))
        return found

    @render.ui
    def cal_cells():
        found = units()
        if isinstance(found, str):
            return ui.p(found, class_="small text-warning-emphasis")
        boxes = input.cal_regions() == "boxes"
        rows = [ui.tags.tr(ui.tags.td(ui.input_checkbox(f"cal_cell_{i}", None, value=True)), ui.tags.td(unit["label"]),
                           ui.tags.td(f"{unit['mean']:.2f} °C"), ui.tags.td(f"{unit['people']:,.0f}"))
                for i, unit in enumerate(found)]
        mean = "Mean temperature where people live (setup period)" if boxes else "Mean temperature (setup period)"
        return ui.div(
            ui.tags.table(ui.tags.thead(ui.tags.tr(ui.tags.th(""), ui.tags.th("Region" if boxes else "Cell"), ui.tags.th(mean),
                                                   ui.tags.th("People"))),
                          ui.tags.tbody(*rows), class_="table table-sm small mb-1"),
            ui.p("From the coolest to the warmest" + (", by the mean of their cells weighted by people. The cells of a region share "
                 "its offset, and keep their differences" if boxes else "") + ". With one ticked, only its offset dT₁ is calibrated; "
                 "with more, the first ticked gets dT₁ and each next one a gap above the one before, so the order is kept in every "
                 "trial. Those not ticked keep the temperatures of the file.", class_="small text-muted mb-1"),
        )

    def chosen_cells():
        found = units()
        if isinstance(found, str):
            return []
        return [unit for i, unit in enumerate(found) if f"cal_cell_{i}" in input and input[f"cal_cell_{i}"]()]

    @render.ui
    def cal_regions_shapes_switch():
        """The outlines of the shapefile of the applied setup on the map of the regions, if it has one."""
        if not setup().shapes:
            return None
        with reactive.isolate():
            on = input.cal_regions_shapes() if "cal_regions_shapes" in input else False
        return ui.input_switch("cal_regions_shapes", with_tip("Shapefile", "The areas of the shapefile of the applied setup, as named "
                               "and merged in Setup, over the cells: to see how the regions sit against them."), value=on)

    @reactive.calc
    def setup_outlines():
        choice = setup().shapes
        if not choice:
            return None
        try:
            return outlines(areas(read_shapes(choice["file"]), choice.get("name"), choice.get("merge")))
        except (ShapeError, OSError):
            return None

    @reactive.effect
    async def draw_regions_map():
        """The simulated cells coloured by the region they are in, ticked or not: to check the regions before running."""
        found, every = units(), cells()
        if not input.cal_offsets() or isinstance(found, str) or isinstance(every, str):
            await send_figure(session, "cal_regions_map", message_figure("The cells and regions to offset are drawn here."))
            return
        ticked = {id(unit) for unit in chosen_cells()}
        shown_shapes = setup_outlines() if "cal_regions_shapes" in input and input.cal_regions_shapes() else None
        await send_figure(session, "cal_regions_map", regions_figure(every, found, [id(unit) in ticked for unit in found],
                                                                     input.cal_region_size() if input.cal_regions() == "boxes" else None,
                                                                     shown_shapes))

    def keep_order():
        return input.cal_keep_order() if "cal_keep_order" in input else True

    def gaps_needed():
        return input.cal_offsets() and len(chosen_cells()) > 1 and keep_order()

    @render.ui
    def cal_order_switch():
        """With two or more cells or regions: whether their order is kept (dT₁ and gaps) or each offset sampled on its own."""
        if not input.cal_offsets() or len(chosen_cells()) < 2:
            return None
        with reactive.isolate():
            on = keep_order()
        unit = "regions" if input.cal_regions() == "boxes" else "cells"
        return ui.input_switch("cal_keep_order", with_tip(f"Keep the order of the {unit}", f"On: the {unit} stay in the order of their "
                               "mean temperatures in every trial (dT₁ and gaps of at least 0). Off: each offset is sampled on its own, "
                               "within the range of dT₁, so their order can change: to explore combinations the order rules out."),
                               value=on)

    @render.ui
    def cal_gap_inputs():
        """The range of the gaps, only with two cells or more ticked; keeping what was typed."""
        if not gaps_needed():
            return None
        with reactive.isolate():
            low = input.cal_gap_low() if "cal_gap_low" in input else 0.0
            high = input.cal_gap_high() if "cal_gap_high" in input else 5.0
        return ui.layout_columns(ui.input_numeric("cal_gap_low", "Gap from [°C]", value=low, min=0, step=0.5),
                                 ui.input_numeric("cal_gap_high", "Gap to [°C]", value=high, min=0, step=0.5), col_widths=(6, 6), fill=False)

    @render.ui
    def cal_offset_equation():
        """How the offsets are made from what is sampled, in general and with the cells ticked."""
        ticked = chosen_cells()
        if not input.cal_offsets() or not ticked:
            return None
        T = lambda k: ui.TagList("T̄", ui.tags.sub(str(k)))  # noqa: E731  The mean of cell k
        dT = lambda k: ui.TagList("dT", ui.tags.sub(str(k)))  # noqa: E731
        gap = lambda k: ui.TagList("gap", ui.tags.sub(str(k)))  # noqa: E731
        unit = "region" if input.cal_regions() == "boxes" else "cell"
        if input.cal_regions() == "boxes":
            daily = ui.p("Each day t, every cell c of region k gets the temperature of the file plus the offset of its region: T",
                         ui.tags.sub("c"), "(t) + ", dT("k"), ".", class_="mb-1")
        else:
            daily = ui.p("Each day t, cell k gets the temperature of the file plus its offset: T", ui.tags.sub("k"), "(t) + ", dT("k"), ".",
                         class_="mb-1")
        if len(ticked) == 1:
            return ui.div(daily, ui.p(dT(1), f" is sampled within its range: one {unit}, no order to keep.", class_="mb-0"),
                          class_="small text-muted border rounded p-2 mb-2")
        if not keep_order():
            return ui.div(daily, ui.p(f"Each {unit}'s ", dT("k"), " is sampled on its own within the range of ", dT(1),
                                      f" (the boxes above): the order of the {unit}s can change from one trial to another.",
                                      class_="mb-0"), class_="small text-muted border rounded p-2 mb-2")
        def difference(k):
            value = ticked[k - 1]["mean"] - ticked[k]["mean"]
            return f" {'−' if value < 0 else '+'} {abs(value):.2f} °C"

        here = [ui.tags.li(dT(k + 1), " = ", dT(k), " + ", gap(k + 1), difference(k),
                           f"   ({ticked[k]['label']}, mean {ticked[k]['mean']:.2f} °C, after {ticked[k - 1]['label']}, mean "
                           f"{ticked[k - 1]['mean']:.2f} °C)")
                for k in range(1, len(ticked))]
        return ui.div(
            daily,
            ui.p(f"The {'regions' if input.cal_regions() == 'boxes' else 'cells'} ticked, from the coolest to the warmest by their "
                 "means ", T("k"), " over the setup period" + (" (of their cells, weighted by people; every cell of a region gets "
                 "its offset)" if input.cal_regions() == "boxes" else "") + ": ", dT(1),
                 f" is sampled, and for each next {unit} k ≥ 2 a ", gap("k"), " ≥ 0, with", class_="mb-1"),
            ui.p(T("k"), " + ", dT("k"), " = ", T("k−1"), " + ", dT("k−1"), " + ", gap("k"), ui.tags.br(), "so  ", dT("k"), " = ",
                 dT("k−1"), " + ", gap("k"), " − (", T("k"), " − ", T("k−1"), ")", class_="mb-1 text-center", style="font-size: 1.05em;"),
            ui.p(f"{unit.capitalize()} k then stays at least as warm as {unit} k−1 in every trial. With the {unit}s ticked:", class_="mb-1"),
            ui.tags.ul(*here, class_="mb-0"),
            class_="small text-muted border rounded p-2 mb-2",
        )

    def gap_range():
        return (input.cal_gap_low(), input.cal_gap_high()) if gaps_needed() and "cal_gap_low" in input else (0.0, 5.0)

    @render.ui
    def cal_sampler_info():
        key = input.cal_sampler()
        return ui.p(SAMPLERS[key].split(":", 1)[1].strip(), " ", ui.a("Optuna documentation", href=SAMPLER_LINKS[key], target="_blank"),
                    class_="small text-muted")

    @reactive.effect
    def default_threads():
        ui.update_numeric("cal_threads", value=setup().run["threads"])

    def threads():
        value = input.cal_threads()
        return value if isinstance(value, int) and value >= 1 else None

    @reactive.effect
    def default_parallel():
        """As many runs at a time as fit in the cores with the threads per run."""
        if threads():
            ui.update_numeric("cal_parallel", value=max(1, (os.cpu_count() or 1) // threads()))

    def problems():
        found = []
        if not objectives():
            found.append("Add at least one objective (in Model and data, above).")
        parameters = chosen_parameters()
        for parameter in parameters:
            low, high = parameter.low, parameter.high
            if not all(isinstance(value, (int, float)) for value in (low, high)) or low >= high:
                found.append(f"{parameter.name}: its minimum must be below its maximum.")
            elif parameter.distribution == "loguniform" and low <= 0:
                found.append(f"{parameter.name}: a log-uniform range needs a minimum above 0.")
        if not input.cal_offsets():
            if not parameters:
                found.append("Nothing to calibrate: turn on Temperature offsets, or tick model parameters.")
            return found + counts_problems()
        if not chosen_cells():
            found.append("Tick at least one cell or region to calibrate its temperature offset, or turn the offsets off.")
        low, high = input.cal_dt_low(), input.cal_dt_high()
        if not all(isinstance(value, (int, float)) for value in (low, high)) or low >= high:
            found.append("dT₁ needs a low below its high.")
        if gaps_needed():
            gap_low, gap_high = gap_range()
            if not all(isinstance(value, (int, float)) for value in (gap_low, gap_high)) or not 0 <= gap_low < gap_high:
                found.append("The gaps need a low of at least 0, below their high.")
        return found + counts_problems()

    def counts_problems():
        found = []
        for key, label in (("cal_trials", "Trials"), ("cal_startup", "Start-up trials"), ("cal_seeds", "Seeds per trial"),
                           ("cal_threads", "Threads per run"), ("cal_parallel", "Runs at the same time")):
            if not isinstance(input[key](), int) or input[key]() < 1:
                found.append(f"{label} must be a positive whole number.")
        return found

    @render.ui
    def cal_run_summary():
        found = problems()
        if found:
            return ui.div(*[ui.p(problem, class_="small text-danger mb-1") for problem in found])
        trials, seeds, parallel = input.cal_trials(), input.cal_seeds(), input.cal_parallel()
        offsets = len(chosen_cells()) if input.cal_offsets() else 0
        per_run, cores = threads(), os.cpu_count() or 1
        if parallel * per_run > cores:
            use = ui.p(f"{parallel} at a time × {per_run} threads = {parallel * per_run} threads, more than the {cores} cores of this "
                       f"computer: the runs slow each other down. Use at most {max(1, cores // per_run)} at a time.",
                       class_="small text-warning-emphasis mb-1")
        else:
            use = ui.p(f"{parallel} at a time × {per_run} thread{'s' if per_run > 1 else ''} = {parallel * per_run} of the {cores} cores "
                       "of this computer.", class_="small text-muted mb-1")
        return ui.TagList(ui.p(f"{trials} trials × {seeds} seed{'s' if seeds > 1 else ''} = {trials * seeds} runs, "
                               f"{len(objectives())} objective{'s' if len(objectives()) > 1 else ''}, "
                               f"{offsets} offset{'s' if offsets != 1 else ''}, {len(chosen_parameters())} model parameter"
                               f"{'s' if len(chosen_parameters()) != 1 else ''}.", class_="mb-1"), use)

    @ui.bind_task_button(button_id="cal_run")
    @reactive.extended_task
    async def calibration_task(folder, parallel):
        return await asyncio.to_thread(run_calibration, folder, state, parallel)

    def running():
        return calibration_task.status() == "running"

    def start(folder, parallel=None):
        last.set(None)
        running_folder.set(str(folder))
        to_select.set(str(folder))
        changed.set(changed() + 1)
        calibration_task.invoke(str(folder), parallel or input.cal_parallel())

    @reactive.effect
    @reactive.event(input.cal_run)
    def start_calibration():
        if busy():
            ui.notification_show("A run or analysis is in progress: wait for it, or cancel it, before a calibration.", type="warning")
            return
        found = problems()
        nagent, seed = agents(), input.seed()
        if not all(isinstance(value, int) and value >= 1 for value in (nagent, seed)):
            found.append("HA must be positive and the seed a positive whole number.")
        elif ha() < 1:
            found.append(HA_BELOW_ONE)
        name = input.cal_name().strip()
        if run_name_problem(name, calibrations_dir(setup().runs_dir)):
            found.append(run_name_problem(name, calibrations_dir(setup().runs_dir)))
        if found:
            ui.notification_show(" ".join(found), type="error")
            return
        # The outputs of the Outputs card, those the objectives were made from, and the vector densities for the drivers
        wanted = (set(selected_output()) | {flag for objective in objectives() for flag in (objective.get("output") or [])}
                  | set(DRIVER_FLAGS))
        output = tuple(flag for group in OUTPUT_FLAGS.values() for flag, _, _ in group if flag in wanted)
        temperature = {"cells": [{"lat": u["lat"], "lon": u["lon"], **({"members": u["members"]} if "members" in u else {})}
                                 for u in chosen_cells()],
                       "first": (input.cal_dt_low(), input.cal_dt_high()), "gap": gap_range(),
                       "ordered": bool(keep_order())} if input.cal_offsets() else None
        parameters = chosen_parameters()
        calibrated = {parameter.name for parameter in parameters}
        fixed = {key: value for key, value in {**setup().params, **overrides()}.items() if key not in calibrated}
        try:
            config = replace(setup(), params=fixed, output=output).with_run(nagent=nagent, seed=seed,
                                                                                                       threads=threads())
            folder = create_calibration(config, [{k: v for k, v in o.items() if k not in ("output", "describe")} for o in objectives()],
                                        parameters=parameters, temperature=temperature, seeds=[seed + i for i in range(input.cal_seeds())],
                                        n_trials=input.cal_trials(), sampler=input.cal_sampler(), startup_trials=input.cal_startup(),
                                        sampler_seed=seed, name=name or None)
        except (ConfigError, CalibrationError, DataError, ValueError, OSError) as error:
            ui.notification_show(f"The calibration cannot start: {error}", type="error")
            return
        ui.update_text("cal_name", value="")
        start(folder)

    @reactive.effect
    @reactive.event(input.cal_resume)
    def resume_calibration():
        folder = input.cal_previous()
        if not folder:
            return
        if running() or busy():
            ui.notification_show("Wait for the run, analysis or calibration in progress, or cancel it, before resuming.", type="warning")
            return
        record = read_calibration(folder)
        if not resumable(record):
            ui.notification_show(OLD_CALIBRATION, type="error")
            return
        if record["status"] == "finished":
            ui.notification_show("This calibration has finished: all its trials are done.", type="message")
            return
        if is_running(folder):
            ui.notification_show("This calibration is running already, in another GUI or script: wait for it, or stop it there.",
                                 type="warning")
            return
        # Its runs keep the threads it was made with: as many at a time as fit in the cores with them
        threads_, cores = record["setup"]["run"]["threads"], os.cpu_count() or 1
        parallel = input.cal_parallel() if isinstance(input.cal_parallel(), int) and input.cal_parallel() >= 1 else 1
        if parallel * threads_ > cores:
            parallel = max(1, cores // threads_)
            ui.notification_show(f"Resumed {parallel} at a time: its runs use {threads_} threads each, and this computer has {cores} cores.",
                                 type="message", duration=8)
        start(folder, parallel)

    @reactive.effect
    def enable_buttons():
        ui.update_action_button("cal_cancel", disabled=not running())
        ui.update_action_button("cal_resume", disabled=running())

    @reactive.effect
    @reactive.event(input.cal_cancel)
    def cancel_calibration():
        state.cancel()

    @reactive.effect
    def collect():
        status = calibration_task.status()
        if status in ("success", "error"):
            with reactive.isolate():
                last.set(calibration_task.result() if status == "success" else "error")
                changed.set(changed() + 1)

    @render.ui
    def cal_run_status():
        if running():
            reactive.invalidate_later(1)
            done, total, failed, active, elapsed, left, message = state.snapshot()
            if message == "Starting":
                return ui.card(ui.p("Starting the calibration…", class_="mb-0"), class_="mt-3")
            text = f"Trials: {done:,} of {total:,} done, {active} runs going now" + (f", {failed:,} failed" if failed else "")
            text += f". Elapsed {_clock(elapsed)}" + (f", about {_clock(left)} left." if left is not None else ".")
            if state.cancelled:
                text = "Cancelling: stopping the runs in progress…"
            bar = ui.div(class_="progress-bar", style=f"width: {100 * done / max(total, 1):.1f}%;")
            return ui.card(ui.p(text, class_="mb-1"), ui.div(bar, class_="progress"), class_="mt-3")
        record = last()
        if record is None:
            return None
        if record == "error":
            return ui.card(ui.p("The calibration stopped with an error. The terminal you started the GUI from shows why."),
                           class_="border-danger mt-3")
        trials = f"{record['completed']:,} of {record['n_trials']:,} trials completed" + (f", {record['failed']} failed" if record["failed"] else "")
        if record["status"] == "finished":
            return ui.p(f"Calibration finished: {trials}.", class_="mt-3 mb-0")
        if record["status"] == "stopped":
            return ui.card(ui.p(f"Calibration stopped: its first {record['failed']} trials all failed, so the others would fail too. "
                                "The end of the log of a run:", class_="mb-1"),
                           ui.tags.pre(record.get("failure") or "", class_="small mb-1"),
                           ui.p("Fix the cause and press Resume.", class_="mb-0"), class_="border-danger mt-3")
        return ui.p(f"Calibration {record['status']}: {trials}. Choose it under Calibrations and press Resume to go on.", class_="mt-3 mb-0")

    @reactive.effect
    def refresh_calibrations():
        changed()
        found = list_calibrations(setup().runs_dir)
        with reactive.isolate():
            selected = to_select() or (input.cal_previous() if input.cal_previous() in found else next(iter(found), None))
            to_select.set(None)
        ui.update_select("cal_previous", choices={folder: calibration_label(folder, record) for folder, record in found.items()},
                         selected=selected)

    def shown():
        """The calibration shown below: the one running, else the one chosen."""
        return running_folder() if running() else input.cal_previous() or None

    @render.ui
    def cal_previous_info():
        changed()  # Drawn again when a calibration starts or ends, and while one runs, as its status changes
        if running():
            reactive.invalidate_later(REFRESH_SECONDS)
        folder = input.cal_previous()
        if not folder:
            return ui.p(f"None yet in {calibrations_dir(setup().runs_dir)}", class_="small text-muted")
        try:
            record = read_calibration(folder)
        except (OSError, ValueError):
            return None
        lines = [f"{o['name']}: {o['metric'].replace('_', ' ')} of {o['variable']}" for o in record["objectives"]]
        temperature = record.get("temperature")
        if temperature:
            lines.append(f"Temperature offsets of {len(temperature['cells'])} cells or regions: dT₁ in {temperature['first']} °C, gaps in "
                         f"{temperature['gap']} °C; means {', '.join(f'{m:.2f}' for m in temperature['means'])} °C")
        for parameter in record.get("parameters", []):
            lines.append(f"{parameter['name']}: {parameter['distribution']} from {parameter['low']:.4g} to {parameter['high']:.4g}")
        lines.insert(0, f"Status: {status_of(folder, record)}"
                     + (" (no process runs it any more, e.g. the GUI was closed: Resume goes on with it)"
                        if status_of(folder, record) == "interrupted" else ""))
        lines.append(f"Sampler {record['sampler']['name']}, {record['n_trials']} trials, seeds {record['seeds']}, "
                     f"{record['setup']['run']['threads']} thread{'s' if record['setup']['run']['threads'] > 1 else ''} per run")
        return ui.div(ui.tags.ul(*[ui.tags.li(line) for line in lines], class_="mb-1"), ui.p(f"Folder: {folder}", class_="mb-0"),
                      class_="small text-muted")

    @reactive.calc
    def progress():
        """(record, rows, front) of the calibration shown, read again every few seconds while it runs."""
        folder = shown()
        if running():
            reactive.invalidate_later(REFRESH_SECONDS)
        changed()
        if not folder:
            return None
        try:
            return read_calibration(folder), trials_table(folder), best_trials(folder)
        except (OSError, ValueError, KeyError, RuntimeError, SQLAlchemyError):
            return None  # Not readable yet, e.g. while the first trial is written

    @reactive.effect
    async def draw_history():
        found = progress()
        if found is None or not any(row["state"] == "COMPLETE" for row in found[1]):
            await send_figure(session, "cal_history_plot", message_figure("The objectives of each trial are drawn here once trials are done."))
            return
        record, rows, _ = found
        await send_figure(session, "cal_history_plot", calibration_history_figure(rows, record["objectives"]))

    @render.ui
    def cal_front():
        found = progress()
        if found is None or not found[2]:
            return None
        record, _, front = found
        names = [o["name"] for o in record["objectives"]]
        means = (record.get("temperature") or {}).get("means") or []
        parameters = [parameter["name"] for parameter in record.get("parameters", [])]
        header = ui.tags.tr(ui.tags.th("Trial"), *[ui.tags.th(name) for name in names],
                            *[ui.tags.th(f"dT{k + 1} → mean") for k in range(len(means))], *[ui.tags.th(name) for name in parameters])
        rows = [ui.tags.tr(ui.tags.td(str(row["number"])), *[ui.tags.td(f"{value:.4g}") for value in row["values"]],
                           *[ui.tags.td(f"{row['offsets'][f'dT_{k + 1}']:+.2f} → {means[k] + row['offsets'][f'dT_{k + 1}']:.2f} °C")
                             for k in range(len(means))],
                           *[ui.tags.td(f"{row['params'][name]:.4g}") for name in parameters])
                for row in sort_front(front)]
        return ui.div(ui.tags.strong(with_tip("Pareto front", "The trials no other trial beats on every objective: the best trade-offs "
                                              "between the objectives (for one objective, the best trial)."), class_="small"),
                      ui.tags.table(ui.tags.thead(header), ui.tags.tbody(*rows), class_="table table-sm small mb-1"), class_="mt-2")

    def sort_choices(record):
        choices = {"number": "Trial number"}
        for k, objective in enumerate(record["objectives"]):
            better = "high" if objective["direction"] == "maximize" else "low"
            for order, text in (("desc", "high to low"), ("asc", "low to high")):
                choices[f"{k}:{order}"] = f"{objective['name']}, {text}{' (best first)' if text.startswith(better) else ''}"
        return choices

    @render.ui
    def cal_front_sort_choice():
        found = progress()
        if found is None or not found[2]:
            return None
        choices = sort_choices(found[0])
        with reactive.isolate():
            selected = input.cal_front_sort() if "cal_front_sort" in input and input.cal_front_sort() in choices else "number"
        return ui.input_select("cal_front_sort", "Sort the Pareto front by", choices, selected=selected, width="22rem")

    def sort_front(front):
        """The trials of the front in the order chosen: by number, or by an objective, high to low or low to high."""
        key = input.cal_front_sort() if "cal_front_sort" in input else "number"
        if not key or key == "number" or ":" not in key:
            return sorted(front, key=lambda row: row["number"])
        index, order = key.split(":")
        return sorted(front, key=lambda row: row["values"][int(index)], reverse=order == "desc")

    @render.ui
    def cal_best_choice():
        found = progress()
        if found is None or not found[2]:
            return None
        record, _, front = found
        trials = {str(row["number"]): f"Trial {row['number']}" for row in sorted(front, key=lambda row: row["number"])}
        objectives_ = {str(k): o["name"] for k, o in enumerate(record["objectives"])}
        with reactive.isolate():
            trial = input.cal_best_trial() if "cal_best_trial" in input and input.cal_best_trial() in trials else next(iter(trials))
            objective = input.cal_best_objective() if "cal_best_objective" in input and input.cal_best_objective() in objectives_ else "0"
        return ui.layout_columns(ui.input_select("cal_best_trial", "Trial of the Pareto front", trials, selected=trial),
                                 ui.input_select("cal_best_objective", "Against the data of", objectives_, selected=objective),
                                 col_widths=(6, 6), fill=False)

    comparisons = {}  # (folder, trial, objective, drivers) -> (figure, problem with the drivers)

    @reactive.effect
    async def draw_best():
        found = progress()
        folder = shown()
        if found is None or not found[2] or "cal_best_trial" not in input or not input.cal_best_trial():
            await send_figure(session, "cal_best_plot", message_figure("A trial of the Pareto front, against the data, is drawn here."))
            return
        number, index = int(input.cal_best_trial()), int(input.cal_best_objective() or 0)
        figure, problem = trial_figure(folder, found[0], number, index, driver_choices(input, "cal_best_driver"))
        best_problem.set(problem)
        if isinstance(figure, str):
            await send_figure(session, "cal_best_plot", message_figure(figure))
            return
        figure.update_layout(title=f"Trial {number}, against {found[0]['objectives'][index]['name']} (model scaled to the mean of the data)")
        await send_figure(session, "cal_best_plot", figure)

    best_problem = reactive.value(None)

    @render.ui
    def cal_best_problem():
        return ui.p(best_problem(), class_="small text-danger mb-1") if best_problem() else None

    def trial_figure(folder, record, number, index, chosen):
        """(a figure of trial `number` against the data of objective `index`, with the drivers chosen of its run below, and
        what is wrong with any of the drivers), or (a str saying why there is no figure, None). The figures are kept: a
        trial does not change once done; each is given as a copy, for its own title."""
        key = (folder, number, index, tuple(sorted(chosen.items())))
        if key not in comparisons:
            try:
                model, data, m, d, labels = trial_comparison(folder, number, index)
            except (DataError, OSError, KeyError, ValueError) as error:
                return f"Trial {number} cannot be drawn: {error}.", None
            # The drivers of the run of the trial (its first seed), within the periods the model and the data share
            run_dir = trial_folder(folder, number) / f"seed_{record['seeds'][0]}"
            first, last = paired_span(data, labels)
            drivers, problems = [], []
            for name, (period, how, by_month) in chosen.items():
                try:
                    with NETCDF_LOCK:
                        drivers.append((name, DRIVERS[name][0], driver_panel(run_dir, name, period, how, by_month, first, last)))
                except (DataError, OSError, KeyError) as error:
                    problems.append(f"{DRIVERS[name][0]}: {error}")
            comparisons[key] = (comparison_figure(model, data, labels, m, d, scale=True, drivers=drivers), "; ".join(problems) or None)
        figure, problem = comparisons[key]
        return go.Figure(figure), problem

    start_problem = reactive.value(None)

    @render.ui
    def cal_start_problem():
        return ui.p(start_problem(), class_="small text-danger mb-1") if start_problem() else None

    @reactive.effect
    async def draw_start():
        """Where the calibration started: its trial with no offset (or, without one, its first trial), against the same data
        as the trial above, to see how far the calibration has come."""
        found = progress()
        folder = shown()
        if found is None or not found[2] or "cal_best_objective" not in input:
            await send_figure(session, "cal_start_plot", message_figure("Where the calibration started, against the data, is drawn here."))
            return
        record, rows, _ = found
        start = next((row for row in rows if row["baseline"] and row["state"] == "COMPLETE"), None)
        first = next((row for row in rows if row["number"] == 0 and row["state"] == "COMPLETE"), None)
        row = start or first
        if row is None:
            await send_figure(session, "cal_start_plot", message_figure("Where the calibration started is drawn here once its first trial is done."))
            return
        index = int(input.cal_best_objective() or 0)
        figure, problem = trial_figure(folder, record, row["number"], index, driver_choices(input, "cal_start_driver"))
        start_problem.set(problem)
        if isinstance(figure, str):
            await send_figure(session, "cal_start_plot", message_figure(figure))
            return
        what = "no temperature offset" if start else "the first trial (none without offsets)"
        values = ", ".join(f"{o['name']} {value:.3g}" for o, value in zip(record["objectives"], row["values"]))
        figure.update_layout(title=f"Start: trial {row['number']}, {what} ({values}), against {record['objectives'][index]['name']}")
        await send_figure(session, "cal_start_plot", figure)

    @render.ui
    def cal_figure_objective():
        found = progress()
        if found is None or not FIGURES[input.cal_figure()][3]:
            return None
        choices = {str(k): objective["name"] for k, objective in enumerate(found[0]["objectives"])}
        with reactive.isolate():
            selected = input.cal_figure_index() if "cal_figure_index" in input and input.cal_figure_index() in choices else "0"
        return ui.input_select("cal_figure_index", "Of the objective", choices, selected=selected)

    @render.ui
    def cal_figure_help():
        text, link = figure_help(input.cal_figure())
        names = ""
        found = progress()
        if found is not None and found[0].get("temperature") and input.cal_figure() not in ("distributions", "timeline"):
            names = (" Optuna's figures show what it samples: dT_1 and the gaps (gap_2, …), from which the offsets of the cells "
                     "follow (the equation above).")
        return ui.p(text + names, " ", ui.a("Optuna documentation", href=link, target="_blank") if link else None,
                    class_="small text-muted mb-1")

    results = {}  # (folder, trials done, figure, objective) -> figure

    @reactive.effect
    async def draw_results():
        found = progress()
        folder = shown()
        kind = input.cal_figure()
        index = int(input.cal_figure_index()) if FIGURES[kind][3] and "cal_figure_index" in input and input.cal_figure_index() else 0
        if found is None:
            await send_figure(session, "cal_results_plot", message_figure("Choose a calibration under Calibrations to see its results."))
            return
        done = sum(row["state"] == "COMPLETE" for row in found[1])
        key = (folder, done, kind, index)
        if key not in results:
            try:
                results[key] = results_figure(folder, kind, index)
            except ResultsError as error:
                await send_figure(session, "cal_results_plot", message_figure(f"Not yet: {error}."))
                return
            except (ValueError, RuntimeError, KeyError, ZeroDivisionError) as error:  # From Optuna's figures, e.g. too few trials
                await send_figure(session, "cal_results_plot", message_figure(f"{FIGURES[kind][0]} cannot be drawn: {error}."))
                return
        await send_figure(session, "cal_results_plot", results[key])

    return SimpleNamespace(running=running, cancel=state.cancel)
