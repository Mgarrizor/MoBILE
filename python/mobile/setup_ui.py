"""The Setup tab: choosing the driving files and previewing them."""

from shiny import ui

from .grid import pop_coordinates
from .layout import player_controls, with_tip
from .plots import COLOUR_MAPS
from .setup import OPTIONAL_FILES, REGION_MODES, REQUIRED_FILES, region_mode


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
        ui.input_switch("setup_spin_up", with_tip("Spin-up to equilibrium", "Let the model settle to equilibrium before the simulated period starts."), value=run["spin_up"] == 1),
        ui.input_numeric("setup_threads", with_tip("Threads", "CPU threads used by the model. Results depend on the number: keep it fixed to compare runs."), value=run["threads"], min=1, step=1),
        _path_input("setup_runs_dir", "Results folder", str(config.runs_dir), "folder"),
        ui.p("The number of agents and the seed are set in the sidebar, as they often change between runs.", class_="small text-muted"),
    )
    files_box = ui.card(
        ui.card_header("Driving files"),
        ui.output_ui("example_note"),
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
        ui.p("Choose the model, the days to simulate, the driving data and, below, the region to simulate, then press ",
             ui.tags.strong("Apply setup"), ". Next, set the parameters in the Parameters tab and press Run in the sidebar.",
             class_="text-muted"),
        ui.layout_columns(run_box, files_box, col_widths=(5, 7)),
        _preview_box(config),
        # Stays at the bottom of the window while the tab is scrolled
        ui.div(
            ui.input_action_button("apply_setup", "Apply setup", class_="btn-primary"),
            ui.output_ui("setup_status"),
            class_="apply-bar",
        ),
        class_="mt-3",
    )


def region_values(config):
    """(mode, {box: value}) of the region boxes for a setup. Without a region, the boxes hold the
    edges and the middle of the grid, as a start."""
    region = config.region
    values = {}
    try:
        lon, lat = (sorted(axis) for axis in pop_coordinates(config.inputs["pop_file"]))
        values = {"north": lat[-1], "west": lon[0], "south": lat[0], "east": lon[-1],
                  "point_lat": lat[len(lat) // 2], "point_lon": lon[len(lon) // 2]}
    except (OSError, ValueError, KeyError, StopIteration, RuntimeError):
        pass
    if region is not None and region_mode(region) == "box":
        values.update(region)
    elif region is not None:
        values.update(point_lat=region["north"], point_lon=region["west"])
    return region_mode(region), {key: round(float(value), 3) for key, value in values.items()}


REGION_BOXES = (("north", "North [°N]"), ("west", "West [°E]"), ("east", "East [°E]"), ("south", "South [°N]"))


def _region_box(config):
    """The region to simulate: the whole grid, a box as in the Copernicus data store, or a point."""
    mode, values = region_values(config)
    boxes = [
        ui.div(ui.input_numeric(f"setup_{key}", label, value=values.get(key), step=0.05), class_=f"region-{key}")
        for key, label in REGION_BOXES
    ]
    return ui.div(
        ui.h6("Region to simulate", class_="mb-1"),
        ui.p("Optional: the model can run on part of the grid. Each run then uses copies of the driving files cut "
             "to it; the files themselves are not changed.", class_="small text-muted mb-2"),
        ui.layout_columns(
            ui.div(
                ui.input_radio_buttons("setup_region", None, REGION_MODES, selected=mode, inline=True),
                ui.panel_conditional(
                    "input.setup_region === 'box'",
                    ui.div(*boxes, class_="region-grid"),
                    ui.div(
                        ui.tags.button("Draw on the map", id="region_draw", type="button", class_="btn btn-sm btn-outline-primary"),
                        ui.span("then drag a rectangle on the map below.", class_="small text-muted ms-2"),
                    ),
                ),
                ui.panel_conditional(
                    "input.setup_region === 'point'",
                    ui.layout_columns(
                        ui.input_numeric("setup_point_lat", "Latitude [°N]", value=values.get("point_lat"), step=0.05),
                        ui.input_numeric("setup_point_lon", "Longitude [°E]", value=values.get("point_lon"), step=0.05),
                        col_widths=(6, 6),
                    ),
                    ui.p("Or click a cell on the map below. The model runs on the cell the point falls in.", class_="small text-muted mb-0"),
                ),
            ),
            ui.output_ui("region_summary"),
            col_widths=(7, 5),
        ),
        class_="border rounded p-3 mb-3",
    )


PREVIEW_FILES = {"rain_file": "Rainfall", "temp_file": "Temperature", "pop_file": "Population density", "age_file": "Age structure"}
DAILY_FILES = ("rain_file", "temp_file")
# Colour map and scale each map starts with
PREVIEW_STYLE = {"rain_file": ("Blues", "linear"), "temp_file": ("Coolwarm", "linear"), "pop_file": ("Reds", "log")}


def _preview_box(config):
    """A look at the driving files in the boxes above, before they are applied, and the region to simulate."""
    daily = " || ".join(f"input.preview_file === '{key}'" for key in DAILY_FILES)
    maps = " || ".join(f"input.preview_file === '{key}'" for key in PREVIEW_STYLE)
    return ui.card(
        ui.card_header("Preview driving files"),
        ui.p(
            "The files in the boxes above, as they are now, also before Apply. Each map is drawn on the grid of its "
            "file: a file whose grid differs from that of the population shows so.",
            class_="small text-muted mb-2",
        ),
        _region_box(config),
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


EXAMPLE_FOLDER = ("utils", "test_run")  # In the MoBILE repository


def example_note_box():
    """Said while the boxes hold the example files bundled with MoBILE."""
    return ui.div(
        ui.tags.strong("Example data for Senegal. "),
        "These files come with MoBILE, in utils/test_run of its GitHub repository: Senegal from 2012 to 2014 on a "
        "0.05° grid, with rainfall from CHIRPS, temperature from CHIRTS and population from WorldPop (2020). "
        "Choose your own files for another region or period.",
        class_="alert alert-info small py-2 mb-3",
    )


def setup_problems(error):
    """The problems of a setup, from a ConfigError, with the labels of the Setup panel."""
    lines = []
    for line in str(error).splitlines():
        for key, label in FILE_LABELS.items():
            line = line.replace(f"inputs: {key} ", f"{label}: ")
        lines.append(line.replace("inputs: ", "").replace("run: ", ""))
    return lines
