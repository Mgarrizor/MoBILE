"""The Setup tab: choosing the driving files and previewing them."""

from shiny import ui

from .layout import player_controls
from .plots import COLOUR_MAPS
from .setup import OPTIONAL_FILES, REQUIRED_FILES


SUFFIX_NAMES = {"netcdf": ("netCDF (.nc)",), "text": ("text (.txt, .csv)",), "folder": ()}


FILE_LABELS = {key: label for key, label, _ in (*REQUIRED_FILES, *OPTIONAL_FILES)}
MODEL_CHOICES = {"1": "VECTRI-ABM (malaria)", "0": "Cholera"}


def _path_input(id, label, value, kind):
    """A box for a path, typed or chosen with the file browser of the GUI."""
    return ui.div(
        ui.input_text(id, label, value=value, width="100%"),
        ui.input_action_button(f"browse_{id}", "Browse", class_="btn-sm mb-3"),
        **{"data-kind": kind},
    )


def setup_value(config, key):
    value = config.inputs.get(key, "")
    return "" if value == "NONE" else str(value)


def setup_tab(config):
    """Everything a run needs that is not a parameter or an output: how to run, and where the data and
    results are. Applied, and checked, with its button."""
    run = config.run
    run_box = ui.card(
        ui.card_header("Run parameters"),
        ui.input_text("setup_project", "Project", value=config.project, width="100%"),
        ui.input_select("setup_disID", "Model", MODEL_CHOICES, selected=str(run["disID"])),
        ui.input_numeric("setup_nstep", "Days to simulate (0: all the driving data)", value=run["nstep"], min=0, step=1),
        ui.input_switch("setup_spin_up", "Spin-up to equilibrium", value=run["spin_up"] == 1),
        ui.input_numeric("setup_threads", "Threads (results depend on them)", value=run["threads"], min=1, step=1),
        _path_input("setup_runs_dir", "Results folder", str(config.runs_dir), "folder"),
        ui.p("The number of agents and the seed are set in the sidebar, as they often change between runs.", class_="small text-muted"),
    )
    files_box = ui.card(
        ui.card_header("Driving files"),
        *[_path_input(f"setup_{key}", label, setup_value(config, key), kind) for key, label, kind in REQUIRED_FILES],
        ui.accordion(
            ui.accordion_panel(
                "Optional files",
                *[_path_input(f"setup_{key}", label, setup_value(config, key), kind) for key, label, kind in OPTIONAL_FILES],
                ui.input_switch("setup_counterfactual", "Counterfactual demography", value=config.inputs.get("counterfactual") == 1),
            ),
            open=False,
        ),
    )
    return ui.div(
        ui.layout_columns(run_box, files_box, col_widths=(5, 7)),
        ui.div(
            ui.input_action_button("apply_setup", "Apply setup", class_="btn-primary"),
            ui.output_ui("setup_status"),
            class_="mt-2",
        ),
        _preview_box(),
        class_="mt-3",
    )


PREVIEW_FILES = {"rain_file": "Rainfall", "temp_file": "Temperature", "pop_file": "Population density", "age_file": "Age structure"}
DAILY_FILES = ("rain_file", "temp_file")
# Colour map and scale each map starts with
PREVIEW_STYLE = {"rain_file": ("Blues", "linear"), "temp_file": ("Coolwarm", "linear"), "pop_file": ("Reds", "log")}


def _preview_box():
    """A look at the driving files in the boxes above, before they are applied."""
    daily = " || ".join(f"input.preview_file === '{key}'" for key in DAILY_FILES)
    maps = " || ".join(f"input.preview_file === '{key}'" for key in PREVIEW_STYLE)
    return ui.card(
        ui.card_header("Preview driving files"),
        ui.p(
            "The files in the boxes above, as they are now, also before Apply. Each map is drawn on the grid of its "
            "file: a file whose grid differs from that of the population shows so.",
            class_="small text-muted mb-1",
        ),
        ui.layout_columns(
            ui.input_select("preview_file", "File", PREVIEW_FILES),
            ui.panel_conditional(
                daily,
                ui.input_slider("preview_day", ui.TagList("Day ", ui.tags.span(id="preview_day_date", class_="ms-1")), min=1, max=2, value=1, step=1, width="100%"),
                player_controls("preview_player"),
            ),
            col_widths=(3, 9),
        ),
        ui.panel_conditional(
            maps,
            ui.layout_columns(
                ui.input_select("preview_colour_map", "Colour map", list(COLOUR_MAPS), selected=PREVIEW_STYLE["rain_file"][0]),
                ui.input_radio_buttons("preview_scale", "Scale", {"linear": "Linear", "log": "Log"}, inline=True),
                ui.input_numeric("preview_vmin", "Minimum", value=None, step="any"),
                ui.input_numeric("preview_vmax", "Maximum", value=None, step="any"),
                ui.div(ui.input_action_button("preview_auto_range", "Automatic range", class_="btn-sm"), class_="pt-4"),
                col_widths=(2, 2, 2, 2, 3),
            ),
        ),
        ui.div(id="preview_map", style="height: 600px;"),
        ui.panel_conditional(daily, ui.div(id="preview_cell_plot", style="height: 300px;")),
        class_="mt-3",
    )


def setup_problems(error):
    """The problems of a setup, from a ConfigError, with the labels of the Setup panel."""
    lines = []
    for line in str(error).splitlines():
        for key, label in FILE_LABELS.items():
            line = line.replace(f"inputs: {key} ", f"{label}: ")
        lines.append(line.replace("inputs: ", "").replace("run: ", ""))
    return lines
