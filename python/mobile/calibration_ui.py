"""The Calibration tab: a Model box and a Data box side by side. For now, the Data box: load observations from the
standard netCDF file or import them from a table, process them with a pipeline of steps the user builds (see
calibration_steps.py), see them, and save them as standard netCDF. The Model box, the objectives and the calibration
with Optuna come next (see calibration-plan)."""

import datetime
import itertools
import re
from pathlib import Path

import numpy as np
import pandas as pd
from shiny import reactive, render, ui

from .calibration_data import AGGREGATIONS, PERIODS, SEASONS, SHAPES, DataError, import_table, read_observations, read_table, write_observations
from .calibration_steps import (
    AGGREGATE_PERIODS, COMBINATIONS, FILTER_MISSING, FILTERS, OPERATIONS, SELECTIONS, STATISTICS, STEP_KINDS, TIME_UNITS, TRANSFORMS, apply_steps,
    default_step,
)
from .layout import OPTUNA_URL, with_tip
from .plots import message_figure, observations_figure, send_figure
from .setup import typed_path

NONE = "__none__"  # Menu entry for "no column"
NETCDF = (".nc", ".nc4", ".cdf")
DATA_FOLDER = ("calibration", "data")  # In the results folder: the observations saved by the Data box
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
MONTH_NAMES = {str(m): datetime.date(2000, m, 1).strftime("%b") for m in range(1, 13)}
# The selections that apply to each shape of observations
SELECTIONS_OF_SHAPE = {"dated": ("window", "months", "years"), "yearly": ("window", "years"), "climatology": ("months",),
                       "season": ("seasons",), "age": ("bands",), "single": ()}
STEP_ACTION = ("Shiny.setInputValue('cal_step_action', {{uid: '{uid}', action: '{action}', at: Date.now()}}, "
               "{{priority: 'event'}})")


def calibration_tab():
    """The Calibration tab: what it is for, then the Model and the Data boxes."""
    return ui.div(
        ui.p("Calibration compares the model with observations: the Model box chooses a model output and processes it, the "
             "Data box loads observations and processes them the same way, and a metric compares the two. Several such "
             "objectives are then optimised together with ", ui.a("Optuna", href=OPTUNA_URL, target="_blank"),
             ". This tab is in development: for now, the Data box.", class_="text-muted"),
        ui.layout_columns(_model_box(), _data_box(), col_widths=(5, 7)),
        class_="mt-3",
    )


def _model_box():
    return ui.card(
        ui.card_header("Model"),
        ui.p("To come: choose a model output (e.g. new cases, EIR), reduce it over the cells of the site, and process it with "
             "the same steps as the data, to compare the two.", class_="text-muted mb-0"),
    )


def _data_box():
    return ui.card(
        ui.card_header("Data"),
        ui.p("Observations to calibrate against: a file in the standard netCDF form of the GUI, or a table (CSV or text) to "
             "import. Values can be dated (e.g. monthly cases), a climatology of calendar months or of seasons, yearly, by age "
             "band, or a single value. Several files can be loaded, to combine them.", class_="small text-muted mb-2"),
        ui.div(
            ui.input_text("cal_data_file", "File of observations", width="100%"),
            ui.div(ui.input_action_button("browse_cal_data_file", "Browse", class_="btn-sm"),
                   ui.input_action_button("cal_load", "Load", class_="btn-sm btn-primary ms-2"), class_="mb-3"),
        ),
        ui.output_ui("cal_dataset_choice"),
        ui.output_ui("cal_import_form"),
        ui.output_ui("cal_data_status"),
        ui.output_ui("cal_pipeline"),
        ui.output_ui("cal_compare_choice"),
        ui.div(id="cal_data_plot", style="min-height: 380px;"),
        ui.output_ui("cal_data_table"),
        ui.output_ui("cal_save_box"),
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

def step_id(uid, name):
    return f"cal_step_{uid}_{name}"


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


def step_controls(step, number, count, before, others):
    """The card of one step: its number and kind, its buttons, and its choices, filled with its values. before is the
    observations the step applies to (after the steps above it), for the choices that depend on them."""
    uid, kind = step["uid"], step["kind"]
    sid = lambda name: step_id(uid, name)
    when = lambda name, value, *children: ui.panel_conditional(f"input.{sid(name)} === '{value}'", *children)
    button = lambda action, text, title, disabled=False: ui.tags.button(
        text, type="button", class_="btn btn-sm btn-outline-secondary py-0 px-2 ms-1", title=title,
        onclick=STEP_ACTION.format(uid=uid, action=action), **({"disabled": ""} if disabled else {}))
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
                                       {"month": "Month", "season": "Season"},
                                       selected=step["by"], inline=True)]
    elif kind == "transform":
        body = [ui.input_select(sid("transform"), None, TRANSFORMS, selected=step["transform"]),
                ui.panel_conditional(f"['log', 'log10'].includes(input.{sid('transform')})",
                                     ui.input_numeric(sid("offset"), with_tip("Offset", "Added before the log: 1 for counts with zeros."), value=step["offset"])),
                when("transform", "moving_average", ui.input_numeric(sid("window"), "Values in the window", value=step["window"], min=2, step=1))]
    elif kind == "filter":
        body = [ui.input_select(sid("type"), with_tip("Filter", "A Butterworth filter of order 4, run forward and backward, so "
                                "nothing shifts in time. The cut-off is gradual: at the cut-off period half the amplitude is kept, so "
                                "to remove the annual cycle with a low pass, cut at about 2 years. Needs a regular series without "
                                "gaps or missing values. The filter starts "
                                "up at each end: values within about two of the longest periods kept from each end are less "
                                "reliable, so a band of several years needs a series of decades."), FILTERS, selected=step["type"]),
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
                                    "stay missing."), FILTER_MISSING,
                                    selected=step.get("missing", "interpolate"), width="100%"),
                    when("missing", "interpolate", ui.input_numeric(sid("max_gap"), with_tip("N (values)", "The longest gap, in values (e.g. months), bridged "
                                                 "for the filter only and left missing after. A longer gap splits the series "
                                                 "into stretches filtered separately."), value=step.get("max_gap", 3), min=1, step=1)),
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


# ---------------------------------------------------------------- server

def calibration_server(input, output, session, setup):
    """The server side of the tab. setup() is the applied setup, whose results folder holds the saved observations."""
    datasets = reactive.value({})  # {name: {"path", "table" (a table to import), "raw" (Observations), "steps": [step with uid]}}
    chosen = reactive.value(None)  # The name of the data set shown
    problem = reactive.value(None)
    saved = reactive.value(None)
    uids = itertools.count()

    def update(name, **changes):
        datasets.set({**datasets(), name: {**datasets()[name], **changes}})

    def current():
        return datasets().get(chosen()) if chosen() is not None else None

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
        # A saved file already holds the steps that made it (in its notes); new steps start from it
        snapshot_steps()
        datasets.set({**datasets(), path.stem: {**entry, "steps": []}})
        chosen.set(path.stem)

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
            snapshot_steps()
            chosen.set(input.cal_dataset())
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
        update(chosen(), raw=raw, steps=[])

    def control_value(uid):
        def value(name):
            id = step_id(uid, name)
            return input[id]() if id in input else None
        return value

    @reactive.calc
    def live_steps():
        """The steps of the data set shown, with the choices of their controls."""
        entry = current()
        if entry is None:
            return []
        return [read_step(step, control_value(step["uid"])) for step in entry["steps"]]

    def snapshot_steps():
        """Keep the choices of the controls in the steps, before the controls are drawn again."""
        with reactive.isolate():
            if current() is not None:
                update(chosen(), steps=live_steps())

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

    @render.ui
    def cal_pipeline():
        entry = current()
        if entry is None or entry.get("raw") is None:
            return None
        steps = entry["steps"]
        others = others_for(chosen())
        befores = steps_before(entry["raw"], steps, others)
        cards = [step_controls(step, i + 1, len(steps), befores[i], others) for i, step in enumerate(steps)]
        return ui.div(
            ui.tags.strong("Processing", class_="small"),
            ui.p("Steps applied in order to the values loaded. Add, change, move or remove them; the plot follows.",
                 class_="small text-muted mb-1"),
            *cards,
            ui.div(ui.input_select("cal_add_kind", None, STEP_KINDS, width="24rem"),
                   ui.input_action_button("cal_add_step", "Add step", class_="btn-sm ms-2 mb-3"),
                   class_="d-flex align-items-start"),
            class_="border rounded p-2 mb-3",
        )

    @reactive.effect
    @reactive.event(input.cal_add_step)
    def add_step():
        if current() is None or current().get("raw") is None:
            return
        snapshot_steps()
        entry = current()
        others = others_for(chosen())
        try:
            before = apply_steps(entry["raw"], [without_uid(s) for s in entry["steps"]], others)
        except DataError:
            before = entry["raw"]
        step = {"uid": str(next(uids)), **default_step(input.cal_add_kind(), before)}
        if step["kind"] == "combine":
            step["other"] = next(iter(others), None)
        update(chosen(), steps=[*entry["steps"], step])

    @reactive.effect
    @reactive.event(input.cal_step_action)
    def step_action():
        action = input.cal_step_action()
        if current() is None or not isinstance(action, dict):
            return
        snapshot_steps()
        steps = list(current()["steps"])
        i = next((k for k, step in enumerate(steps) if step["uid"] == action.get("uid")), None)
        if i is None:
            return
        if action.get("action") == "remove":
            steps.pop(i)
        elif action.get("action") == "up" and i > 0:
            steps[i - 1], steps[i] = steps[i], steps[i - 1]
        elif action.get("action") == "down" and i < len(steps) - 1:
            steps[i + 1], steps[i] = steps[i], steps[i + 1]
        update(chosen(), steps=steps)

    @reactive.calc
    def processed():
        """(observations after the steps, or None, and what is wrong)."""
        entry = current()
        if entry is None or entry.get("raw") is None:
            return None, None
        try:
            return apply_steps(entry["raw"], [without_uid(s) for s in live_steps()], others_for(chosen())), None
        except DataError as error:
            return None, str(error)

    @render.ui
    def cal_compare_choice():
        """Which earlier stage to draw with the result: the values loaded, or after one of the steps but the last."""
        entry = current()
        if entry is None or entry.get("raw") is None or not entry["steps"]:
            return None
        n = len(entry["steps"])
        choices = {"none": "Nothing", "0": "Values loaded", **{str(k): f"After step {k}" for k in range(1, n)}}
        with reactive.isolate():
            previous = input.cal_compare() if "cal_compare" in input else "none"
        return ui.input_select("cal_compare", with_tip("Compare with", "An earlier stage of the processing, drawn with the "
                               "result: on the same axes if it has the same shape and units, else in a second panel below."),
                               choices, selected=previous if previous in choices else "none", width="16rem")

    @reactive.calc
    def compared():
        """(the stage chosen to compare with, its label), or (None, '')."""
        entry = current()
        choice = input.cal_compare() if "cal_compare" in input else "none"
        if entry is None or entry.get("raw") is None or choice in (None, "none"):
            return None, ""
        k = int(choice)
        steps = live_steps()
        if k > len(steps) - 1:
            return None, ""
        try:
            stage = apply_steps(entry["raw"], [without_uid(s) for s in steps[:k]], others_for(chosen()))
        except DataError:
            return None, ""
        return stage, "Values loaded" if k == 0 else f"After step {k}"

    @render.ui
    def cal_data_status():
        if problem():
            return ui.p(problem(), class_="small text-danger")
        entry = current()
        observations, error = processed()
        if error:
            return ui.p(f"Processing, {error}", class_="small text-danger")
        if observations is None:
            return None
        notes = [ui.tags.li(note) for note in observations.notes]
        return ui.div(
            ui.p(ui.tags.strong(f"{entry['path'].name}: "), summary_text(observations), class_="small mb-1"),
            ui.tags.ul(*notes, class_="small text-muted mb-2") if notes else None,
        )

    @reactive.effect
    async def draw_data():
        entry = current()
        observations, error = processed()
        if observations is None:
            text = error or ("Import the table to see it." if entry is not None else "Load a file of observations to see them.")
            await send_figure(session, "cal_data_plot", message_figure(text))
            return
        await send_figure(session, "cal_data_plot", observations_figure(observations, entry["path"].name, *compared()))

    @render.ui
    def cal_data_table():
        observations, _ = processed()
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
        observations, _ = processed()
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
        observations, _ = processed()
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
