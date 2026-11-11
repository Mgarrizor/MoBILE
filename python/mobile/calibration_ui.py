"""The Calibration tab: a Model box and a Data box side by side, and their comparison below. The Data box loads
observations (the standard netCDF file, or a table to import); the Model box takes an output of a finished run, reduced
over the cells of its region. Each is processed by a pipeline of steps the user builds (calibration_steps.py), and the
comparison pairs the two on the periods they share and gives the metrics (calibration_metrics.py). The objectives and
the calibration with Optuna are in the card below them (calibration_run_ui.py)."""

import datetime
import itertools
import re
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
from shiny import reactive, render, ui

from .calibration_data import (
    AGGREGATIONS, PERIODS, SEASONS, SHAPES, DataError, import_table, read_observations, read_table, select_window,
    write_observations,
)
from .calibration_metrics import DIRECTIONS, METRICS, metrics, pair
from .calibration_model import (
    DRIVERS, SEED_MEAN, SPACES, chosen_seeds, default_aggregation, driver_panel, members_mean, model_members, process_both, run_choices,
    run_elsewhere, run_seeds, run_variables, seed_spread, shared_span,
)
from .calibration_run_ui import calibration_run_card, driver_controls, paired_span
from .calibration_steps import (
    AGGREGATE_PERIODS, COMBINATIONS, FILTER_MISSING, FILTERS, OPERATIONS, SELECTIONS, STATISTICS, STEP_KINDS, TIME_UNITS, TRANSFORMS, apply_steps,
    default_step, describe,
)
from .layout import OPTUNA_URL, with_tip
from .plots import comparison_figure, mark_windows, message_figure, observations_figure, send_figure
from .results import read_run
from .setup import typed_path

NONE = "__none__"  # Menu entry for "no column"
NETCDF = (".nc", ".nc4", ".cdf")
DATA_FOLDER = ("calibration", "data")  # In the results folder: the observations saved by the Data box
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
MONTH_NAMES = {str(m): datetime.date(2000, m, 1).strftime("%b") for m in range(1, 13)}
# The selections that apply to each shape of observations
SELECTIONS_OF_SHAPE = {"dated": ("window", "months", "years"), "yearly": ("window", "years"), "climatology": ("months",),
                       "season": ("seasons",), "age": ("bands",), "single": ()}
OBJECTIVE_REMOVE = "Shiny.setInputValue('cal_objective_remove', {{index: {index}, at: Date.now()}}, {{priority: 'event'}})"
STEP_ACTION = ("Shiny.setInputValue('{prefix}_step_action', {{uid: '{uid}', action: '{action}', at: Date.now()}}, "
               "{{priority: 'event'}})")
DATA, MODEL = "cal_data", "cal_model"  # The prefixes of the ids of the two boxes


def calibration_tab():
    """The Calibration tab: what it is for, the Model and the Data boxes, and their comparison."""
    return ui.div(
        ui.p("Calibration compares the model with observations: the Model box takes an output of a finished run and the "
             "Data box loads observations, each processed by steps you choose, and the comparison below pairs them on the "
             "periods they share and gives the metrics. Several such objectives are then optimised together with ",
             ui.a("Optuna", href=OPTUNA_URL, target="_blank"), ". Add each comparison you want to fit as an objective, then run the "
             "calibration in the last card. This tab is in development: the results views (Optuna's figures, the distributions of "
             "the parameters) come next.", class_="text-muted"),
        _how_to_calibrate(),
        ui.layout_columns(_model_box(), _data_box(), col_widths=(6, 6)),
        _comparison_card(),
        calibration_run_card(),
        class_="mt-3",
    )


def _how_to_calibrate():
    """The steps of a calibration, in the order of the tab."""
    steps = [
        ui.TagList(ui.tags.strong("Apply the setup"), " in tab 1: the driving files, region and period. The calibration runs "
                   "the model with it, the HA and seed of the sidebar, and the parameters of the sliders."),
        ui.TagList(ui.tags.strong("Run the model once"), " from the sidebar, with the output you want to compare ticked in the "
                   "Outputs card (e.g. New symptomatic cases). Any finished run with that output will do, also an earlier one or one "
                   "from another folder: it is only used to build the objectives and check them, and its outputs say which "
                   "outputs the runs of the calibration must write."),
        ui.TagList(ui.tags.strong("Model box"), ": choose that run and the output, and add the steps that make it comparable "
                   "(e.g. select 1990 to 2004, then sum by month)."),
        ui.TagList(ui.tags.strong("Data box"), ": load the observations, and process them likewise."),
        ui.TagList(ui.tags.strong("Model and data"), ": check the comparison and its metrics, then name it, choose a metric and "
                   "press ", ui.tags.em("Add as objective"), ". Repeat for each objective, e.g. with a climatology step in both "
                   "boxes for the season."),
        ui.TagList(ui.tags.strong("Calibration with Optuna"), ": tick the cells whose temperature to offset and set the ranges, "
                   "choose the sampler, the trials, the seeds per trial and the runs at the same time, then press ",
                   ui.tags.em("Run calibration"), "."),
        ui.TagList(ui.tags.strong("Follow it"), " below the card: the objectives trial by trial, the Pareto front and a trial "
                   "against the data. Cancel stops it; Resume, under Calibrations, goes on later. Everything is kept in "
                   "calibration/<name>/ in the results folder."),
    ]
    return ui.div(ui.h6("How to calibrate"), ui.tags.ol(*[ui.tags.li(step) for step in steps], class_="mb-0"),
                  class_="small border rounded p-2 mb-3")


def _model_box():
    return ui.card(
        ui.card_header("Model"),
        ui.p("An output of a finished run, reduced over the cells of its region into a daily series. Run the model from the "
             "sidebar first; its runs are listed here.", class_="small text-muted mb-2"),
        ui.div(ui.input_select(f"{MODEL}_run", "Run", {}, width="100%"),
               ui.input_action_button(f"{MODEL}_refresh", "Refresh", class_="btn-sm ms-2 mb-3", title="List the runs again"),
               class_="d-flex align-items-end"),
        ui.input_text(f"{MODEL}_folder", with_tip("Or a run in another folder", "Any finished run or seed band: the comparison "
                      "only reads its outputs, and the setup does not change."), placeholder="its folder", width="100%"),
        ui.div(ui.input_action_button(f"browse_{MODEL}_folder", "Browse", class_="btn-sm"),
               ui.input_action_button(f"{MODEL}_add", "Use this run", class_="btn-sm ms-2"), class_="mb-2"),
        ui.output_ui(f"{MODEL}_add_problem"),
        ui.output_ui(f"{MODEL}_options"),
        ui.output_ui(f"{MODEL}_status"),
        ui.output_ui(f"{MODEL}_pipeline"),
        ui.output_ui(f"{MODEL}_compare_choice"),
        ui.div(id=f"{MODEL}_plot", style="min-height: 380px;"),
    )


def _data_box():
    return ui.card(
        ui.card_header("Data"),
        ui.p("Observations to calibrate against: a file in the standard netCDF form of the GUI, or a table (CSV or text) to "
             "import. Values can be dated (e.g. monthly cases), a climatology of calendar months or of seasons, yearly, by age "
             "band, or a single value. Several files can be loaded, to combine them.", class_="small text-muted mb-2"),
        ui.p("When compared with the model, dated observations and the model output are first cut to the years both cover "
             "(e.g. data for 1975–2025 and a run for 1985–2004 are both cut to 1985–2004), and only then processed by the steps of their boxes, so that statistics "
             "such as a climatology use the same years on both sides; the steps below and the plot already show them cut, and say "
             "the period. Observations of a climatology or yearly ones are not cut, nor the data sets a Combine step takes; an "
             "objective with a Combine step keeps the observations as processed here.", class_="small text-muted mb-2"),
        ui.div(
            ui.input_text("cal_data_file", "File of observations", width="100%"),
            ui.div(ui.input_action_button("browse_cal_data_file", "Browse", class_="btn-sm"),
                   ui.input_action_button("cal_load", "Load", class_="btn-sm btn-primary ms-2"), class_="mb-3"),
        ),
        ui.output_ui("cal_dataset_choice"),
        ui.output_ui("cal_import_form"),
        ui.output_ui(f"{DATA}_status"),
        ui.output_ui(f"{DATA}_pipeline"),
        ui.output_ui(f"{DATA}_compare_choice"),
        ui.div(id=f"{DATA}_plot", style="min-height: 380px;"),
        ui.output_ui("cal_data_table"),
        ui.output_ui("cal_save_box"),
    )


def _comparison_card():
    return ui.card(
        ui.card_header("Model and data"),
        ui.input_switch("cal_scale_model", with_tip("Scale the model to the mean of the data, on the plot", "Only to compare "
                        "their timing by eye when their levels differ, e.g. because only part of the cases are reported. The "
                        "metrics are not changed."), value=False),
        ui.div(
            ui.tags.strong(with_tip("Possible drivers", "Rainfall and temperature as the model read them, and the vector densities "
                                    "it gave (each the mean over the simulated cells of the run in the Model box), each processed on its "
                                    "own and drawn below, within the periods the model and the data share. The infective vector density, "
                                    "much lower, has its own scale at the right. All the panels zoom together."), class_="small"),
            *[driver_controls(name) for name in DRIVERS],
            class_="border rounded p-2 mb-2",
        ),
        ui.output_ui("cal_drivers_problem"),
        ui.div(id="cal_comparison_plot", style="min-height: 380px;"),
        ui.output_ui("cal_comparison"),
        ui.div(
            ui.tags.strong(with_tip("Add as objective", "This comparison, as it is, becomes an objective of the calibration below: "
                                    "the observations as processed in the Data box, and the output, cells and steps of the Model box, "
                                    "applied to every run of the calibration, compared with the metric chosen here."), class_="small"),
            ui.layout_columns(
                ui.input_text("cal_objective_name", "Name", placeholder="e.g. timing", width="100%"),
                ui.input_select("cal_objective_metric", "Metric", {key: text.split(":")[0] for key, text in METRICS.items()},
                                selected="correlation", width="100%"),
                ui.div(ui.input_action_button("cal_add_objective", "Add as objective", class_="btn-sm btn-primary"), class_="pt-4"),
                col_widths=(5, 4, 3), fill=False,
            ),
            ui.output_ui("cal_objective_problem"),
            class_="border-top pt-2 mt-2",
        ),
        class_="mt-3",
    )


def _columns_menu(id, label, columns, selected=None, optional=False):
    choices = ({NONE: "(none)"} if optional else {}) | {column: column for column in columns}
    return ui.input_select(id, label, choices, selected=selected if selected in choices else next(iter(choices)), width="100%")


def guess_columns(table):
    """(date column, value column): the first column that reads as dates, and the first numeric column after it."""
    date = next((column for column in table.columns
                 if not pd.api.types.is_numeric_dtype(table[column])
                 and pd.to_datetime(table[column].dropna().head(20), errors="coerce").notna().all()), None)
    value = next((column for column in table.columns if column != date and pd.api.types.is_numeric_dtype(table[column])), None)
    return date, value


def import_form(table):
    """The form that says what the columns of a table are, with menus of its columns."""
    columns = [str(column) for column in table.columns]
    date, value = guess_columns(table)
    conditional = lambda shape, *children: ui.panel_conditional(f"input.cal_shape === '{shape}'", *children)
    return ui.div(
        ui.p(ui.tags.strong("Import a table: "), f"{len(table)} rows, columns {', '.join(columns)}. Say what the columns are.",
             class_="small mb-2"),
        ui.layout_columns(
            ui.input_select("cal_shape", "What the values are", SHAPES, width="100%"),
            _columns_menu("cal_value", "Values", columns, value),
            col_widths=(7, 5), fill=False,
        ),
        ui.layout_columns(
            ui.input_radio_buttons("cal_aggregation", with_tip("How they aggregate", "Sum for counts such as cases; mean for "
                                   "rates and prevalences. It is the default of the steps that put values together."), AGGREGATIONS),
            ui.input_text("cal_units", "Units", placeholder="e.g. cases", width="100%"),
            col_widths=(7, 5), fill=False,
        ),
        conditional("dated",
                    ui.input_radio_buttons("cal_dating", None, {"date": "One date per row", "span": "Start and end per row"}, inline=True),
                    ui.panel_conditional("input.cal_dating === 'date'", ui.layout_columns(
                        _columns_menu("cal_date", "Date", columns, date),
                        ui.input_select("cal_period", with_tip("Each date stands for", "The period that contains the date: "
                                        "a mid-month date stands for that month."), {key: key.capitalize() for key in PERIODS}, selected="month"),
                        col_widths=(6, 6), fill=False)),
                    ui.panel_conditional("input.cal_dating === 'span'", ui.layout_columns(
                        _columns_menu("cal_start", "First day", columns, date), _columns_menu("cal_end", "Last day", columns, date),
                        col_widths=(6, 6), fill=False))),
        conditional("climatology", _columns_menu("cal_month", "Month (1 to 12)", columns)),
        conditional("season", _columns_menu("cal_season", "Season (DJF, MAM, JJA, SON or 1 to 4)", columns)),
        conditional("yearly", _columns_menu("cal_year", "Year", columns)),
        conditional("age", ui.layout_columns(_columns_menu("cal_age_lower", "First year of age", columns),
                                             _columns_menu("cal_age_upper", "Last year of age (empty: open band)", columns, optional=True),
                                             col_widths=(6, 6), fill=False)),
        ui.layout_columns(
            _columns_menu("cal_sd", with_tip("Uncertainty", "A standard deviation of each value, if the table has one."), columns, optional=True),
            ui.input_selectize("cal_extra", with_tip("Other columns to keep", "e.g. the population, to divide the values by."),
                               [column for column in columns if column not in (date, value)], multiple=True, width="100%"),
            col_widths=(5, 7), fill=False,
        ),
        ui.input_action_button("cal_import", "Import", class_="btn-sm btn-primary mb-3"),
        class_="border rounded p-2 mb-3",
    )


# ---------------------------------------------------------------- the steps, as controls

def step_id(prefix, uid, name):
    return f"{prefix}_step_{uid}_{name}"


def item_choices(what, observations):
    """The choices of a selection of months, seasons, years or age bands of the observations."""
    if what == "months":
        return MONTH_NAMES
    if what == "seasons":
        return {name: name for name in SEASONS}
    if what == "years":
        if observations.shape == "yearly":
            years = observations.index["year"].to_numpy()
        elif observations.shape == "dated":
            years = pd.to_datetime(observations.index["start"]).dt.year.to_numpy()
        else:
            years = []
        return {str(y): str(y) for y in sorted(set(int(y) for y in years))}
    if what == "bands":
        return {observations.label(i): observations.label(i) for i in range(len(observations))}
    return {}


def _span(observations):
    """(first day, last day) of dated or yearly observations, as ISO dates; (None, None) otherwise."""
    if observations.shape == "dated":
        return str(pd.Timestamp(observations.index["start"].iloc[0]).date()), str(pd.Timestamp(observations.index["end"].iloc[-1]).date())
    if observations.shape == "yearly":
        return f"{int(observations.index['year'].iloc[0])}-01-01", f"{int(observations.index['year'].iloc[-1])}-12-31"
    return None, None


def step_controls(step, number, count, before, others, prefix=DATA):
    """The card of one step: its number and kind, its buttons, and its choices, filled with its values. before is the
    observations the step applies to (after the steps above it), for the choices that depend on them."""
    uid, kind = step["uid"], step["kind"]
    sid = lambda name: step_id(prefix, uid, name)
    when = lambda name, value, *children: ui.panel_conditional(f"input.{sid(name)} === '{value}'", *children)
    button = lambda action, text, title, disabled=False: ui.tags.button(
        text, type="button", class_="btn btn-sm btn-outline-secondary py-0 px-2 ms-1", title=title,
        onclick=STEP_ACTION.format(prefix=prefix, uid=uid, action=action), **({"disabled": ""} if disabled else {}))
    header = ui.div(
        ui.tags.strong(f"{number}. {STEP_KINDS[kind]}", class_="small"),
        ui.div(button("up", "↑", "Move up", number == 1), button("down", "↓", "Move down", number == count), button("remove", "×", "Remove")),
        class_="d-flex justify-content-between align-items-center mb-1",
    )
    columns = list(before.extra) if before is not None else []
    if kind == "aggregate":
        body = [ui.layout_columns(
            ui.input_select(sid("period"), "Into", AGGREGATE_PERIODS, selected=step["period"]),
            ui.input_select(sid("how"), "By", STATISTICS, selected=step["how"]),
            ui.input_switch(sid("complete"), with_tip("Complete periods only", "Off: also periods the values cover in part, "
                            "with their coverage as a column."), value=step["complete"]),
            col_widths=(4, 4, 4), fill=False),
            when("period", "days", ui.input_numeric(sid("days"), "Days", value=step["days"], min=1, step=1))]
    elif kind == "arithmetic":
        body = [ui.layout_columns(
            ui.input_select(sid("operation"), None, OPERATIONS, selected=step["operation"]),
            ui.input_radio_buttons(sid("operand"), None, {"column": "a column", "number": "a number"}, selected=step["operand"], inline=True),
            col_widths=(5, 7), fill=False),
            ui.layout_columns(
                ui.div(when("operand", "column", ui.input_select(sid("column"), "Column", {c: c for c in columns} or {NONE: "(no column kept)"},
                                                                 selected=step.get("column"))),
                       when("operand", "number", ui.input_numeric(sid("number"), "Number", value=step["number"]))),
                ui.input_text(sid("units"), "Units after", value=step.get("units", ""), placeholder="e.g. cases per person"),
                col_widths=(6, 6), fill=False)]
    elif kind == "select":
        shape = before.shape if before is not None else "dated"
        whats = {key: SELECTIONS[key] for key in SELECTIONS_OF_SHAPE.get(shape, ())} or {step["what"]: SELECTIONS[step["what"]]}
        start, end = _span(before) if before is not None else (None, None)
        body = [ui.input_select(sid("what"), None, whats, selected=step["what"] if step["what"] in whats else next(iter(whats))),
                *([when("what", "window", ui.input_date_range(sid("window"), "From, to", start=step.get("first") or start,
                                                              end=step.get("last") or end, format="yyyy-mm-dd"))] if "window" in whats else []),
                *[when("what", what, ui.input_selectize(sid(f"items_{what}"), "Keep", item_choices(what, before), multiple=True,
                                                         selected=[str(i) for i in step.get("items", [])] if step["what"] == what else []))
                  for what in ("months", "seasons", "years", "bands") if what in whats]]
    elif kind == "climatology":
        body = [ui.input_radio_buttons(sid("by"), with_tip("By", "The mean of each calendar month, or season, over the values "
                                       "in it, with their spread as the uncertainty. From monthly values, a season is the mean "
                                       "month of the season; for seasonal totals, aggregate into seasons (sum) first."),
                                       {"month": "Month", "season": "Season"}, selected=step["by"], inline=True)]
    elif kind == "transform":
        body = [ui.input_select(sid("transform"), None, TRANSFORMS, selected=step["transform"]),
                ui.panel_conditional(f"['log', 'log10'].includes(input.{sid('transform')})",
                                     ui.input_numeric(sid("offset"), with_tip("Offset", "Added before the log: 1 for counts with zeros."), value=step["offset"])),
                when("transform", "moving_average", ui.input_numeric(sid("window"), "Values in the window", value=step["window"], min=2, step=1))]
    elif kind == "filter":
        body = [ui.input_select(sid("type"), with_tip("Filter", "A Butterworth filter of order 4, run forward and backward, so "
                                "nothing shifts in time. The cut-off is gradual: at the cut-off period half the amplitude is kept, so "
                                "to remove the annual cycle with a low pass, cut at about 2 years. The filter starts up at each "
                                "end: values within about two of the longest periods kept from each end are less reliable, so a "
                                "band of several years needs a series of decades."), FILTERS, selected=step["type"]),
                ui.layout_columns(
                    ui.panel_conditional(f"input.{sid('type')} !== 'low'", ui.input_numeric(sid("short"), "Shorter period", value=step["short"])),
                    ui.panel_conditional(f"input.{sid('type')} !== 'high'", ui.input_numeric(sid("long"), "Longer period", value=step["long"])),
                    ui.input_select(sid("unit"), "In", {unit: unit for unit in TIME_UNITS}, selected=step["unit"]),
                    col_widths=(4, 4, 4), fill=False),
                ui.layout_columns(
                    ui.input_select(sid("missing"), with_tip("Missing values", "Interpolate short gaps: gaps of up to N values "
                                    "are filled by a straight line only for the filter to run, and put back as missing after; the "
                                    "notes say how many. Filter each stretch separately: no interpolation. Either way, longer gaps "
                                    "split the series into stretches filtered separately, and stretches too short for the cut-off "
                                    "stay missing."), FILTER_MISSING, selected=step.get("missing", "interpolate"), width="100%"),
                    when("missing", "interpolate", ui.input_numeric(sid("max_gap"), with_tip("N (values)", "The longest gap, in values "
                                                                    "(e.g. months), bridged for the filter only and left missing after. "
                                                                    "A longer gap splits the series into stretches filtered separately."),
                                                                    value=step.get("max_gap", 3), min=1, step=1)),
                    col_widths=(9, 3), fill=False)]
    else:
        body = [ui.layout_columns(
            ui.input_select(sid("other"), "With", {name: name for name in others} or {NONE: "(load another file first)"},
                            selected=step.get("other")),
            ui.input_select(sid("how"), "By", COMBINATIONS, selected=step["how"]),
            col_widths=(6, 6), fill=False)]
    return ui.div(header, *body, class_="border rounded px-2 pt-1 pb-0 mb-2")


def read_step(step, value):
    """A step with its choices as the controls give them; value(name) is the value of a control, or None if absent."""
    kind, result = step["kind"], dict(step)

    def take(name, convert=lambda v: v):
        if value(name) is not None:
            result[name] = convert(value(name))

    if kind == "aggregate":
        take("period"), take("how"), take("complete", bool), take("days", lambda v: int(v) if v else 1)
    elif kind == "arithmetic":
        take("operation"), take("operand"), take("column", lambda v: None if v == NONE else v), take("number"), take("units")
    elif kind == "select":
        take("what")
        window = value("window")
        if window is not None:
            result["first"], result["last"] = (str(day) if day else None for day in window)
        items = value(f"items_{result['what']}")
        if items is not None:
            result["items"] = [int(i) if result["what"] in ("months", "years") else i for i in items]
    elif kind == "climatology":
        take("by")
    elif kind == "transform":
        take("transform"), take("offset", lambda v: v or 0.0), take("window", lambda v: int(v) if v else 0)
    elif kind == "filter":
        take("type"), take("short", lambda v: v or 0.0), take("long", lambda v: v or 0.0), take("unit")
        take("missing"), take("max_gap", lambda v: int(v) if v else 0)
    else:
        take("other", lambda v: None if v == NONE else v), take("how")
    return result


def without_uid(step):
    return {key: value for key, value in step.items() if key != "uid"}


def summary_text(observations):
    """e.g. 'Dated, 180 values from 1990-01 to 2004-12, in cases per person, counts (sum).'"""
    n = len(observations)
    span = f" from {observations.label(0)} to {observations.label(n - 1)}" if n > 1 else ""
    missing = int(np.isnan(observations.values).sum())
    return (f"{SHAPES[observations.shape].split(':')[0]}, {n} values{span}, in {observations.units or 'no units'}, "
            f"{'counts (sum)' if observations.aggregation == 'sum' else 'rates (mean)'}"
            f"{f', {missing} missing' if missing else ''}{', with uncertainty' if observations.sd is not None else ''}.")


def steps_before(raw, steps, others):
    """The observations each step applies to: raw, then after each step in turn (None after a step that fails)."""
    result, current = [], raw
    for step in steps:
        result.append(current)
        if current is not None:
            try:
                current = apply_steps(current, [without_uid(step)], others)
            except DataError:
                current = None
    return result


def metrics_table(values, model, data, parts=()):
    """The metrics as an HTML table: name, value and what it means; with parts [(title, values or None)], e.g. the
    calibration and validation years, a column for each after the whole period."""
    def shown(found, key):
        value = None if found is None else found[key]
        return "not defined" if value is None else f"{value:.4g}"

    rows = []
    for key, text in METRICS.items():
        name, meaning = text.split(": ", 1)
        if key in ("rmse", "bias"):
            meaning = meaning.replace("in the units of the data", f"in {data.units}")
        rows.append(ui.tags.tr(ui.tags.td(name), ui.tags.td(shown(values, key), class_="text-end"),
                               *[ui.tags.td(shown(found, key), class_="text-end") for _, found in parts],
                               ui.tags.td(meaning, class_="text-muted")))
    header = (ui.tags.thead(ui.tags.tr(ui.tags.th(""), ui.tags.th("All years", class_="text-end"),
                                       *[ui.tags.th(title, class_="text-end") for title, _ in parts], ui.tags.th("")))
              if parts else None)
    return ui.tags.table(header, ui.tags.tbody(*rows), class_="table table-sm small mb-1")


# ---------------------------------------------------------------- server

def calibration_server(input, output, session, setup):
    """The server side of the tab. setup() is the applied setup, whose results folder holds the runs and the saved
    observations."""
    datasets = reactive.value({})  # {name: {"path", "table" (a table to import), "raw" (Observations), "steps": [step with uid]}}
    chosen = reactive.value(None)  # The name of the data set shown
    problem = reactive.value(None)
    saved = reactive.value(None)
    uids = itertools.count()

    def pipeline(prefix, raw, others, name, members=lambda: [], span=lambda: None):
        """The steps of one box, with their cards, the comparison with an earlier stage and the plot. raw() is the
        observations before the steps (or None), already cut to span() (the years the model and the data both cover, or
        None), others() the observations to combine with, name() the title. With several members() (the seeds of a seed
        band), each is processed by the steps, and the result is their mean with their standard deviation as the uncertainty."""
        steps = reactive.value([])

        def control(uid):
            def value(key):
                id = step_id(prefix, uid, key)
                return input[id]() if id in input else None
            return value

        @reactive.calc
        def live():
            return [read_step(step, control(step["uid"])) for step in steps()]

        def snapshot():
            """Keep the choices of the controls in the steps, before the controls are drawn again."""
            with reactive.isolate():
                steps.set(live())

        def draw_pipeline():
            observations = raw()
            if observations is None:
                return None
            current, other = steps(), others()
            befores = steps_before(observations, current, other)
            return ui.div(
                ui.tags.strong("Processing", class_="small"),
                ui.p("Steps applied in order. Add, change, move or remove them; the plot follows.", class_="small text-muted mb-1"),
                ui.p(f"Cut to {span()[0]} to {span()[1]}, the years the model and the data both cover, before the steps.",
                     class_="small mb-1", style="color: #2563eb;") if span() else None,
                *[step_controls(step, i + 1, len(current), befores[i], other, prefix) for i, step in enumerate(current)],
                ui.div(ui.input_select(f"{prefix}_add_kind", None, STEP_KINDS, width="24rem"),
                       ui.input_action_button(f"{prefix}_add_step", "Add step", class_="btn-sm ms-2 mb-3"),
                       class_="d-flex align-items-start"),
                class_="border rounded p-2 mb-3",
            )

        draw_pipeline.__name__ = f"{prefix}_pipeline"  # Shiny names an output after its function
        render.ui(draw_pipeline)

        @reactive.effect
        @reactive.event(input[f"{prefix}_add_step"])
        def add_step():
            observations = raw()
            if observations is None:
                return
            snapshot()
            try:
                before = apply_steps(observations, [without_uid(s) for s in steps()], others())
            except DataError:
                before = observations
            step = {"uid": str(next(uids)), **default_step(input[f"{prefix}_add_kind"](), before)}
            if step["kind"] == "combine":
                step["other"] = next(iter(others()), None)
            steps.set([*steps(), step])

        @reactive.effect
        @reactive.event(input[f"{prefix}_step_action"])
        def step_action():
            action = input[f"{prefix}_step_action"]()
            if not isinstance(action, dict):
                return
            snapshot()
            current = list(steps())
            i = next((k for k, step in enumerate(current) if step["uid"] == action.get("uid")), None)
            if i is None:
                return
            if action.get("action") == "remove":
                current.pop(i)
            elif action.get("action") == "up" and i > 0:
                current[i - 1], current[i] = current[i], current[i - 1]
            elif action.get("action") == "down" and i < len(current) - 1:
                current[i + 1], current[i] = current[i], current[i + 1]
            steps.set(current)

        @reactive.calc
        def processed():
            """(observations after the steps, or None, and what is wrong)."""
            observations = raw()
            if observations is None:
                return None, None
            try:
                seeds = members()
                if len(seeds) > 1:
                    return seed_spread(seeds, [without_uid(s) for s in live()], others(), observations.notes[0]), None
                return apply_steps(observations, [without_uid(s) for s in live()], others()), None
            except DataError as error:
                return None, str(error)

        def draw_compare_choice():
            """Which earlier stage to draw with the result: the values before the steps, or after one of them but the last."""
            if raw() is None or not steps():
                return None
            n = len(steps())
            choices = {"none": "Nothing", "0": "Before the steps", **{str(k): f"After step {k}" for k in range(1, n)}}
            id = f"{prefix}_compare"
            with reactive.isolate():
                previous = input[id]() if id in input else "none"
            return ui.input_select(id, with_tip("Compare with", "An earlier stage of the processing, drawn with the result: on "
                                   "the same axes if it has the same shape and units, else in a second panel below."),
                                   choices, selected=previous if previous in choices else "none", width="16rem")

        draw_compare_choice.__name__ = f"{prefix}_compare_choice"
        render.ui(draw_compare_choice)

        @reactive.calc
        def compared():
            id = f"{prefix}_compare"
            choice = input[id]() if id in input else "none"
            observations = raw()
            if observations is None or choice in (None, "none"):
                return None, ""
            k, current = int(choice), live()
            if k > len(current) - 1:
                return None, ""
            try:
                stage = apply_steps(observations, [without_uid(s) for s in current[:k]], others())
            except DataError:
                return None, ""
            return stage, "Before the steps" if k == 0 else f"After step {k}"

        @reactive.effect
        async def draw_plot():
            observations, error = processed()
            if observations is None:
                await send_figure(session, f"{prefix}_plot", message_figure(error or name()[1]))
                return
            await send_figure(session, f"{prefix}_plot", observations_figure(observations, name()[0], *compared()))

        return SimpleNamespace(steps=steps, live=live, snapshot=snapshot, processed=processed)

    # ---------------------------------------------------------------- data

    def current():
        return datasets().get(chosen()) if chosen() is not None else None

    def data_raw():
        entry = current()
        return None if entry is None else entry.get("raw")

    def others_for(name):
        """{name: processed observations} of the other data sets, to combine with."""
        result = {}
        for other, entry in datasets().items():
            if other != name and entry.get("raw") is not None:
                try:
                    result[other] = apply_steps(entry["raw"], [without_uid(s) for s in entry["steps"]])
                except DataError:
                    pass
        return result

    def data_name():
        entry = current()
        if entry is None:
            return "", "Load a file of observations to see them."
        return entry["path"].name, "Import the table to see it."

    @reactive.calc
    def common_span():
        """(first, last) dates the model output and the observations both cover, as loaded, or None: until both are
        loaded, if either is not dated (e.g. observations of a climatology), or if they share no period."""
        members, observations = model_members_or_error()[0], data_raw()
        if not members or observations is None:
            return None
        try:
            return shared_span(members[0], observations)
        except DataError:
            return None

    def cut(observations):
        """The observations within the years the model and the data both cover, so that the steps of the boxes, as the
        calibration, see only those."""
        span = common_span()
        return observations if observations is None or span is None else select_window(observations, *span)

    data = pipeline(DATA, lambda: cut(data_raw()), lambda: others_for(chosen()), data_name, span=common_span)

    def validation_window():
        """(first, last) dates of the validation window of the Calibration card, if it is on and both are given, else None."""
        if "cal_validation" not in input or not input.cal_validation() or "cal_validation_dates" not in input:
            return None
        dates = input.cal_validation_dates()
        if not dates or dates[0] is None or dates[1] is None:
            return None
        return str(dates[0]), str(dates[1])

    @reactive.effect
    def default_validation_window():
        """The last five years of the period the model and the data share, as a first validation window."""
        span = common_span()
        if span is None:
            return
        first, last = pd.Timestamp(span[0]), pd.Timestamp(span[1])
        start = max(first, last - pd.DateOffset(years=5) + pd.Timedelta(days=1))
        ui.update_date_range("cal_validation_dates", start=start.date(), end=last.date(), min=first.date(), max=last.date())

    def keep_steps():
        """Keep the steps of the data set shown with it, before another is shown."""
        if current() is not None:
            data.snapshot()
            with reactive.isolate():
                datasets.set({**datasets(), chosen(): {**datasets()[chosen()], "steps": data.steps()}})

    def show(name):
        chosen.set(name)
        data.steps.set(list(datasets()[name]["steps"]))

    @reactive.effect
    @reactive.event(input.cal_load)
    def load_file():
        problem.set(None)
        saved.set(None)
        typed = input.cal_data_file().strip()
        if not typed:
            problem.set("Type the path of a file, or use Browse.")
            return
        path = typed_path(typed)
        if not path.is_file():
            problem.set(f"No file {path}.")
            return
        try:
            entry = ({"path": path, "raw": read_observations(path)} if path.suffix.lower() in NETCDF
                     else {"path": path, "table": read_table(path), "raw": None})
        except (DataError, OSError, UnicodeDecodeError) as error:
            problem.set(str(error))
            return
        keep_steps()
        # A saved file already holds the steps that made it (in its notes); new steps start from it
        datasets.set({**datasets(), path.stem: {**entry, "steps": []}})
        show(path.stem)

    @render.ui
    def cal_dataset_choice():
        names = list(datasets())
        if len(names) < 2:
            return None
        return ui.input_select("cal_dataset", "Data set shown", {name: name for name in names}, selected=chosen(), width="100%")

    @reactive.effect
    @reactive.event(input.cal_dataset)
    def choose_dataset():
        if input.cal_dataset() in datasets() and input.cal_dataset() != chosen():
            keep_steps()
            show(input.cal_dataset())
            saved.set(None)

    @render.ui
    def cal_import_form():
        entry = current()
        return import_form(entry["table"]) if entry is not None and entry.get("table") is not None else None

    @reactive.effect
    @reactive.event(input.cal_import)
    def import_observations():
        entry = current()
        if entry is None or entry.get("table") is None:
            return
        column = lambda id: None if input[id]() in (None, NONE) else input[id]()
        shape = input.cal_shape()
        by_date = shape == "dated" and input.cal_dating() == "date"
        try:
            raw = import_table(
                entry["table"], shape, input.cal_value(), input.cal_aggregation(), input.cal_units(),
                date=column("cal_date") if by_date else None, period=input.cal_period(),
                start=column("cal_start") if shape == "dated" and not by_date else None,
                end=column("cal_end") if shape == "dated" and not by_date else None,
                month=column("cal_month") if shape == "climatology" else None, season=column("cal_season") if shape == "season" else None,
                year=column("cal_year") if shape == "yearly" else None,
                age_lower=column("cal_age_lower") if shape == "age" else None, age_upper=column("cal_age_upper") if shape == "age" else None,
                sd=column("cal_sd"), extra=tuple(input.cal_extra() or ()), source=entry["path"].name,
            )
        except DataError as error:
            problem.set(f"Not imported: {error}")
            return
        problem.set(None)
        datasets.set({**datasets(), chosen(): {**entry, "raw": raw, "steps": []}})
        data.steps.set([])

    def status(observations, error, title):
        if error:
            return ui.p(f"Processing, {error}", class_="small text-danger")
        if observations is None:
            return None
        notes = [ui.tags.li(note) for note in observations.notes]
        return ui.div(ui.p(ui.tags.strong(f"{title}: "), summary_text(observations), class_="small mb-1"),
                      ui.tags.ul(*notes, class_="small text-muted mb-2") if notes else None)

    def draw_data_status():
        if problem():
            return ui.p(problem(), class_="small text-danger")
        return status(*data.processed(), data_name()[0])

    draw_data_status.__name__ = f"{DATA}_status"
    render.ui(draw_data_status)

    @render.ui
    def cal_data_table():
        observations, _ = data.processed()
        if observations is None:
            return None
        frame = observations.frame()
        frame.insert(0, "", [observations.label(i) for i in range(len(observations))])
        frame = frame.drop(columns=[c for c in ("start", "end", "month", "season", "year", "age_lower", "age_upper") if c in frame.columns])
        shown = frame if len(frame) <= 12 else pd.concat([frame.head(6), frame.tail(6)])
        html = shown.to_html(index=False, float_format=lambda v: f"{v:.6g}", na_rep="missing", classes="table table-sm small mb-1")
        return ui.div(ui.HTML(html), ui.p(f"First and last 6 of {len(frame)} values." if len(frame) > 12 else "",
                                          class_="small text-muted"), class_="table-responsive")

    @render.ui
    def cal_save_box():
        observations, _ = data.processed()
        if observations is None:
            return None
        return ui.div(
            ui.layout_columns(
                ui.input_text("cal_save_name", "Save as", value=chosen(), width="100%"),
                ui.div(ui.input_action_button("cal_save", "Save as standard netCDF", class_="btn-sm"), class_="pt-4"),
                col_widths=(6, 6), fill=False,
            ),
            ui.p("The file keeps the steps and notes, so what was done can be seen and done again.", class_="small text-muted mb-1"),
            ui.output_ui("cal_saved"),
            class_="border-top pt-2",
        )

    @reactive.effect
    @reactive.event(input.cal_save)
    def save_observations():
        observations, _ = data.processed()
        name = input.cal_save_name().strip().removesuffix(".nc")
        if observations is None:
            return
        if not NAME.match(name):
            saved.set(("error", "Names use letters, digits, '.', '_' and '-' only (no spaces)."))
            return
        folder = Path(setup().runs_dir).joinpath(*DATA_FOLDER)
        try:
            folder.mkdir(parents=True, exist_ok=True)
            write_observations(observations, folder / f"{name}.nc")
        except OSError as error:
            saved.set(("error", f"Not saved: {error}"))
            return
        saved.set(("ok", str(folder / f"{name}.nc")))

    @render.ui
    def cal_saved():
        state = saved()
        if state is None:
            return None
        kind, text = state
        return ui.p(f"Saved: {text}" if kind == "ok" else text, class_="small " + ("text-success" if kind == "ok" else "text-danger"))

    # ---------------------------------------------------------------- model

    elsewhere = reactive.value({})  # {folder: label} of the runs added from other folders
    add_problem = reactive.value(None)
    to_select = reactive.value(None)

    @reactive.effect
    @reactive.event(input[f"{MODEL}_refresh"], setup, elsewhere)
    def list_model_runs():
        try:
            choices = run_choices(setup().runs_dir)
        except OSError:
            choices = {}
        choices = {**choices, **{folder: label for folder, label in elsewhere().items() if folder not in choices}}
        with reactive.isolate():
            previous = to_select() or input[f"{MODEL}_run"]()
            to_select.set(None)
        ui.update_select(f"{MODEL}_run", choices=choices or {NONE: "(no finished run in the results folder)"},
                         selected=previous if previous in choices else next(iter(choices), NONE))

    @reactive.effect
    @reactive.event(input[f"{MODEL}_add"])
    def add_model_run():
        typed = input[f"{MODEL}_folder"]().strip()
        if not typed:
            add_problem.set("Type the folder of a run, or use Browse.")
            return
        try:
            found = run_elsewhere(typed_path(typed))
        except DataError as error:
            add_problem.set(f"Not used: {error}.")
            return
        add_problem.set(None)
        to_select.set(next(iter(found)))
        elsewhere.set({**elsewhere(), **found})

    def draw_add_problem():
        return ui.p(add_problem(), class_="small text-danger") if add_problem() else None

    draw_add_problem.__name__ = f"{MODEL}_add_problem"
    render.ui(draw_add_problem)

    @reactive.calc
    def model_outputs():
        """(the run folder, {name: info} of its daily outputs), or (None, {})."""
        folder = input[f"{MODEL}_run"]()
        if folder in (None, "", NONE):
            return None, {}
        try:
            return folder, {name: info for name, info in run_variables(folder).items() if not info["static"]}
        except (OSError, KeyError, ValueError):
            return None, {}

    @render.ui
    def cal_model_options():
        folder, outputs = model_outputs()
        if folder is None:
            return None
        grouped = {}
        for name, info in outputs.items():
            grouped.setdefault(info["group"] or "Other", {})[name] = f"{info['long_name']} ({name})"
        with reactive.isolate():
            previous = input[f"{MODEL}_variable"]() if f"{MODEL}_variable" in input else None
        name = previous if previous in outputs else ("Inew" if "Inew" in outputs else next(iter(outputs)))
        seeds = run_seeds(folder)
        return ui.div(
            ui.input_select(f"{MODEL}_variable", "Output", grouped, selected=name, width="100%"),
            ui.input_select(f"{MODEL}_space", with_tip("Over the cells (each day)", "How the cells of the run are put together, "
                            "day by day, before the steps: for per-person outputs, the mean weighted by the people of each cell gives "
                            "the value per person of the whole region. A run on a single point has one cell. Over time, the steps "
                            "below decide, e.g. a sum by month."), SPACES, width="100%"),
            ui.input_select(f"{MODEL}_seed", "Seed", {SEED_MEAN: "All seeds: median and range", **{str(s): f"Seed {s}" for s in seeds}}) if seeds else None,
        )

    @reactive.calc
    def model_members_or_error():
        """(the daily series of each run taken: every seed of a band, one seed, or the single run, and what is wrong)."""
        folder, outputs = model_outputs()
        id = f"{MODEL}_variable"
        if folder is None or id not in input or input[id]() not in outputs:
            return [], None
        seed = input[f"{MODEL}_seed"]() if f"{MODEL}_seed" in input else None
        try:
            return model_members(folder, input[id](), input[f"{MODEL}_space"](), seed), None
        except (DataError, OSError, KeyError, ValueError) as error:
            return [], str(error)

    @reactive.calc
    def model_raw_or_error():
        members, error = model_members_or_error()
        if not members:
            return None, error
        seed = input[f"{MODEL}_seed"]() if f"{MODEL}_seed" in input else None
        return members_mean(members, chosen_seeds(model_outputs()[0], seed)), None

    def model_name():
        folder = input[f"{MODEL}_run"]()
        return (Path(folder).name if folder not in (None, "", NONE) else "",
                model_raw_or_error()[1] or "Choose a run and an output.")

    model = pipeline(MODEL, lambda: cut(model_raw_or_error()[0]), dict, model_name,
                     lambda: [cut(member) for member in model_members_or_error()[0]], span=common_span)

    def draw_model_status():
        shown = status(*model.processed(), model_name()[0])
        _, outputs = model_outputs()
        name = input[f"{MODEL}_variable"]() if f"{MODEL}_variable" in input else None
        averaged = [step for step in model.live() if step["kind"] == "aggregate" and step["how"] != "sum"]
        if name in outputs and default_aggregation(name, outputs[name]) == "sum" and averaged:
            # An amount per day averaged over periods is the average per day, not the amount per period
            note = ui.p(f"{name} is an amount per day (e.g. new cases per person per day): the {averaged[0]['how']} by "
                        f"{averaged[0]['period']} gives an average per day. Sum it to get the amount per {averaged[0]['period']}, "
                        "as in cases per month.", class_="small mb-1", style="color: #d97706;")
            return ui.TagList(shown, note)
        return shown

    draw_model_status.__name__ = f"{MODEL}_status"
    render.ui(draw_model_status)

    # ---------------------------------------------------------------- comparison

    @reactive.calc
    def paired():
        """(model values, data values, model, data, labels, metrics, span), or a message saying what is missing or wrong.
        Both boxes are cut to the years both cover (common_span) before their steps, as in the calibration
        (calibration_model.process_both), so that their statistics, e.g. a climatology, cover the same years."""
        model_values, _ = model.processed()
        data_values, _ = data.processed()
        if model_values is None or data_values is None:
            return "Choose a run and an output in the Model box, and load observations in the Data box: they are compared here."
        try:
            members, observations = model_members_or_error()[0], data_raw()
            if members and observations is not None:
                shared_span(members[0], observations)  # Raises DataError if they share no period
            m, d, labels = pair(model_values, data_values)
        except DataError as error:
            return f"Not comparable yet: {error}."
        return model_values, data_values, m, d, labels, metrics(m, d), common_span()

    @reactive.calc
    def split_metrics():
        """[(title, metrics or None)] of the calibration years and of the validation window, each cut before the steps as
        the calibration does, if the window of the Calibration card is on; else []. A part that cannot be had is None."""
        window, span = validation_window(), common_span()
        if window is None or span is None or isinstance(paired(), str):
            return []
        members, model_raw = model_members_or_error()[0], model_raw_or_error()[0]
        parts = []
        for part, title in (("calibration", "Calibration window"), ("validation", f"Validation window, {window[0]} to {window[1]}")):
            try:
                m, d, _ = process_both(members, [without_uid(s) for s in model.live()], data_raw(), [without_uid(s) for s in data.live()],
                                       others_for(chosen()), model_raw.notes[0], window, part)
                parts.append((title, metrics(*pair(m, d)[:2])))
            except DataError:
                parts.append((title, None))
        return parts

    @reactive.calc
    def drivers():
        """([(name, label, [(label, observations)])] of the drivers shown (two series for the vector densities), and what is
        wrong with any of them)."""
        result = paired()
        folder = model_outputs()[0]
        if isinstance(result, str) or folder is None:
            return [], None
        _, data_values, _, _, labels, _, _ = result
        first, last = paired_span(data_values, labels)
        seed = input[f"{MODEL}_seed"]() if f"{MODEL}_seed" in input else None
        shown, problems = [], []
        for name, (label, _) in DRIVERS.items():
            if not input[f"cal_driver_{name}"]():
                continue
            try:
                shown.append((name, label, driver_panel(folder, name, input[f"cal_driver_{name}_period"](), input[f"cal_driver_{name}_how"](),
                                                        input[f"cal_driver_{name}_climatology"](), first, last, seed)))
            except (DataError, OSError, KeyError) as error:
                problems.append(f"{label}: {error}")
        return shown, "; ".join(problems) or None

    @render.ui
    def cal_drivers_problem():
        problem_ = drivers()[1]
        return ui.p(problem_, class_="small text-danger") if problem_ else None

    @reactive.effect
    async def draw_comparison():
        result = paired()
        if isinstance(result, str):
            await send_figure(session, "cal_comparison_plot", message_figure(result))
            return
        model_values, data_values, m, d, labels, _, _ = result
        figure = comparison_figure(model_values, data_values, labels, m, d, input.cal_scale_model(), drivers()[0])
        window = validation_window()
        if window is not None and data_values.shape == "dated":
            # The calibration and validation windows of the Calibration card, as bars along the top
            mark_windows(figure, (str(data_values.index["start"].min().date()), str(data_values.index["end"].max().date())), window)
        await send_figure(session, "cal_comparison_plot", figure)

    # ---------------------------------------------------------------- objectives

    objectives = reactive.value([])  # [{name, data, variable, space, aggregation, steps, metric, direction, output}]
    objective_problem = reactive.value(None)

    @reactive.effect
    @reactive.event(input.cal_add_objective)
    def add_objective():
        result = paired()
        if isinstance(result, str):
            objective_problem.set(result)
            return
        name = input.cal_objective_name().strip() or f"objective_{len(objectives()) + 1}"
        if not NAME.match(name):
            objective_problem.set("Names use letters, digits, '.', '_' and '-' only (no spaces).")
            return
        if name in {objective["name"] for objective in objectives()}:
            objective_problem.set(f"There is an objective named {name} already.")
            return
        _, data_values, _, _, _, _, span = result
        folder = model_outputs()[0]
        manifest = read_run(folder) or {}
        # The observations as processed now, kept with the calibrations of the results folder, and as loaded with the steps of
        # the Data box, so that each trial cuts both to the period they share before the steps; not if a step combines other
        # data sets, which the calibration does not keep: then the observations as processed here, kept as they are
        stamp = f"{name}_{datetime.datetime.now():%Y%m%d-%H%M%S}"
        target = Path(setup().runs_dir).joinpath(*DATA_FOLDER) / f"objective_{stamp}.nc"
        data_steps = [without_uid(step) for step in data.live()]
        keep_raw = not any(step["kind"] == "combine" for step in data_steps)
        raw_target = target.with_name(f"objective_{stamp}_raw.nc")
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            write_observations(data_values, target)
            if keep_raw:
                write_observations(data_raw(), raw_target)
        except OSError as error:
            objective_problem.set(f"Not added: the observations cannot be saved ({error}).")
            return
        metric = input.cal_objective_metric()
        # The steps as the cards show them now, as for the comparison: not as they were when added
        steps = [without_uid(step) for step in model.live()]
        objectives.set([*objectives(), {
            "name": name, "data": str(target), "variable": input[f"{MODEL}_variable"](), "space": input[f"{MODEL}_space"](),
            "aggregation": None, "steps": steps, "metric": metric, "direction": DIRECTIONS[metric], "output": manifest.get("output"),
            **({"data_raw": str(raw_target), "data_steps": data_steps} if keep_raw else {}),
            "describe": f"{data_values.name} ({len(data_values)} values, {SHAPES[data_values.shape].split(':')[0].lower()}) against "
                        f"{input[f'{MODEL}_variable']()}, {SPACES[input[f'{MODEL}_space']()].lower()}, then "
                        f"{'; '.join(describe(step) for step in steps) or 'no step'}"
                        + (f"; both cut to the period they share ({span[0]} to {span[1]}) before the steps" if keep_raw and span else
                           "" if keep_raw else "; the data as processed here, not cut again by each trial (a step combines other data sets)"),
        }])
        objective_problem.set(None)
        ui.update_text("cal_objective_name", value="")

    @reactive.effect
    @reactive.event(input.cal_objective_remove)
    def remove_objective():
        index = int(input.cal_objective_remove()["index"])
        objectives.set([objective for i, objective in enumerate(objectives()) if i != index])

    @render.ui
    def cal_objective_problem():
        return ui.p(objective_problem(), class_="small text-danger mb-0") if objective_problem() else None

    @render.ui
    def cal_objectives():
        found = objectives()
        if not found:
            return ui.p("No objective yet: compare the model and the data above, then press Add as objective. Add several, e.g. the "
                        "monthly series with the correlation (timing) and their climatology with the relative RMSE (season).",
                        class_="small text-muted")
        rows = [ui.tags.tr(
            ui.tags.td(objective["name"]),
            ui.tags.td(METRICS[objective["metric"]].split(":")[0], f" ({'higher' if objective['direction'] == 'maximize' else 'lower'} is better)"),
            ui.tags.td(objective["describe"], class_="text-muted"),
            ui.tags.td(ui.tags.button("Remove", class_="btn btn-sm btn-outline-secondary py-0", onclick=OBJECTIVE_REMOVE.format(index=i))),
        ) for i, objective in enumerate(found)]
        return ui.tags.table(ui.tags.tbody(*rows), class_="table table-sm small mb-1")

    @render.ui
    def cal_comparison():
        result = paired()
        if isinstance(result, str):
            return None
        model_values, data_values, m, d, labels, values, span = result
        units = None
        if model_values.units.strip() != data_values.units.strip():
            units = ui.p(f"The units differ by name: model in {model_values.units or 'no units'}, data in {data_values.units or 'no units'}. "
                         "Check that they are the same quantity: the RMSE and the bias only mean something if they are.",
                         class_="small mb-1", style="color: #d97706;")
        return ui.div(
            ui.p((f"Both cut to the period they share, {span[0]} to {span[1]}, before the steps of their boxes. " if span else "")
                 + f"{values['n']} pairs, from {labels[0]} to {labels[-1]}: the periods the model and the data share, without a "
                 "missing value on either side.", class_="small mb-1"),
            units,
            ui.p("With the validation window of the Calibration card on: the metrics of all the years, then those of the "
                 "calibration window (the years the calibration uses) and of the validation window (left out of it), each cut "
                 "before the steps, as the calibration does.", class_="small mb-1") if split_metrics() else None,
            metrics_table(values, model_values, data_values, split_metrics()),
        )

    return SimpleNamespace(objectives=objectives)
