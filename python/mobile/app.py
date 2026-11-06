"""Local Shiny interface: fixed grid and driving data, parameters on sliders, the real model behind Run."""

import asyncio
import os
import signal
import socket
from dataclasses import replace
from pathlib import Path

import plotly.graph_objects as go
import plotly.offline
from shiny import App, reactive, render, run_app, ui

from .basemap import load_basemap, load_terrain
from .config import ConfigError, default_params, default_sliders, read_params
from .driving import climatology, field_limits, open_field, read_age
from .grid import extent_key, load_grid, mask_like, read_grid
from .layout import (
    ANALYSIS_TABS, ASSETS, GUI_OUTPUT, HA_BELOW_ONE, OPTUNA_URL, OUTPUT_FLAGS, funders, help_tab, no_run_yet, output_groups, output_switch_id,
    page_header, page_title, parameter_legend, player_controls, slider_grid, slider_groups, with_tip,
)
from .outcome import RunState, load_outcome, run_label, run_model, run_name_problem
from .plots import (
    BOX, COLOUR_MAPS, LAND, age_figure, cell_figure, envelope_figure, grid_figure, map_figure, message_figure,
    MAX_DOTS, DOT_COLOURS, add_dot, default_dot, dot_label, move_dot, next_cells, remove_dot, send_figure, sig,
)
from .checks import driving_days, driving_problems
from .period import length_text, parse_day, period_days, spin_up_problem
from .region import region_problems
from .results import list_runs
from .sensitivity_ui import sensitivity_card, sensitivity_server
from .scripts import (
    BROWSER_HANDLER, CLOSED_HANDLER, DOTS_HANDLER, PARAMETER_STYLE, PLAYER, PLOT_HANDLER, SIDEBAR_FIT, SLIDER_FORMAT, THEME, PAGE_STYLE,
)
from .setup import (
    OPTIONAL_FILES, REQUIRED_FILES, from_fields, from_manifest, create_folder, list_folder, region_from_fields, region_mode,
    save_setup, start_folder, typed_path,
)
from .setup_ui import (
    DAILY_FILES, EXAMPLE_FOLDER, PREVIEW_FILES, PREVIEW_STYLE, REGION_BOXES, REGION_LAYERS, REGION_MONTHS, SUFFIX_NAMES, available_model, example_note_box, region_values,
    period_values, setup_problems, setup_tab, setup_value,
)
from .variables import (
    AGE_KEY, age_choices, age_groups, preferred_variable, resolve_variable, variable_choices,
)


STATIC_MESSAGE = "This variable does not change over time: see the map."
HUMANS_PER_AGENT_RANGE = (0.5, 2)  # Outside it, the sidebar suggests a number of agents
REGION_MAP_TITLES = {
    "all": "The whole grid is simulated",
    "box": "Drag a rectangle to choose the subregion",
    "point": "Click a cell to choose the point",
}


def create_app(config):
    config, model_note = available_model(config)
    default_output = {flag for flags in OUTPUT_FLAGS.values() for flag, _, on in flags if on}
    initial_output = set(config.output) if config.output is not None else set(GUI_OUTPUT)
    missing = set(default_sliders()) - set(default_params())
    if missing:
        raise ConfigError(f"default_params.txt in the package has no value for the sliders {sorted(missing)}")

    app_ui = ui.page_sidebar(
        ui.sidebar(
            ui.div("Run simulation", class_="sidebar-heading"),
            ui.input_numeric(
                "ha", with_tip("Humans per agent (HA)", "People represented by one agent, which sets the number of agents. "
                               "Close to 1 is best for reliable results: more agents is slower but closer to the real population."),
                value=None, min=0, step="any",
            ),
            ui.div(ui.output_ui("humans_per_agent"), class_="small text-muted mb-2"),
            ui.input_numeric(
                "seed", with_tip("Seed", "Starting point of the random numbers. The same seed and threads give the same results."),
                value=config.run["seed"], min=1, step=1,
            ),
            ui.input_switch(
                "seed_band", with_tip("Seed band", "Run several consecutive seeds with the same parameters, to see how much the results vary by chance."),
                value=False,
            ),
            ui.panel_conditional("input.seed_band", ui.input_numeric("n_seeds", "Number of seeds", value=5, min=2, step=1)),
            ui.input_text("run_name", "Run name (optional)", placeholder="e.g. kenya_e0_high"),
            ui.div(
                ui.input_task_button("run", "Run", label_busy="Running…", class_="btn-primary"),
                ui.input_action_button("cancel", "Cancel", disabled=True),
                class_="run-bar d-flex flex-column gap-2",
            ),
            ui.div("Earlier runs", class_="sidebar-heading mt-4"),
            ui.input_select("previous_run", "Runs in the results folder", {}),
            ui.div(ui.output_text("runs_folder"), class_="small text-muted text-break mb-2"),
            ui.input_action_button("load", "Load run", class_="w-100"),
            ui.input_action_button("close", "Close GUI", class_="btn-sm w-100 mt-4"),
            width=300,
        ),
        ui.head_content(
            ui.tags.script(ui.HTML(THEME)),
            ui.tags.style(PAGE_STYLE),
            ui.tags.script(ui.HTML(plotly.offline.get_plotlyjs())),
            ui.tags.script(ui.HTML(PLAYER)),
            ui.tags.script(ui.HTML(PLOT_HANDLER)),
            ui.tags.script(ui.HTML(CLOSED_HANDLER)),
            ui.tags.style("#shiny-disconnected-overlay { display: none; }"),
            ui.tags.style(PARAMETER_STYLE),
            ui.tags.script(ui.HTML(SLIDER_FORMAT)),
            ui.tags.script(ui.HTML(BROWSER_HANDLER)),
            ui.tags.script(ui.HTML(SIDEBAR_FIT)),
            ui.tags.script(ui.HTML(DOTS_HANDLER)),
        ),
        ui.output_ui("status"),
        ui.navset_tab(
            ui.nav_panel("1. Setup", setup_tab(config), value="setup"),
            ui.nav_panel(
                "2. Parameters & SA",
                ui.layout_columns(
                    ui.card(
                        ui.card_header("Parameters for single runs"),
                        ui.p("Only the sliders you move are changed for the next run; the others keep their value.", class_="small text-muted mb-1"),
                        ui.output_ui("parameter_sliders"),
                        ui.div(ui.input_action_button("reset", "Reset parameters", class_="btn-lg"), class_="mt-3 text-center"),
                    ),
                    ui.card(
                        ui.card_header("Outputs"),
                        ui.p("What the next run writes. Rainfall and temperature are always written; fields by age give large files.",
                             class_="small text-muted mb-1"),
                        *output_groups(initial_output),
                    ),
                    col_widths=(7, 5),
                    class_="mt-3",
                ),
                sensitivity_card(),
                value="parameters",
            ),
            ui.nav_panel(
                "3. Results",
                ui.div(ui.output_ui("run_summary"), class_="mt-3"),
                ui.card(
                    ui.layout_columns(
                        ui.div(ui.input_select("variable", "Variable", {}), ui.output_ui("age_choice")),
                        ui.output_ui("seed_choice"),
                        ui.div(
                            ui.input_slider("day", ui.TagList("Day ", ui.tags.span(id="day_date", class_="ms-1")), min=1, max=max(config.run["nstep"], 2), value=1, step=1, width="100%"),
                            player_controls(),
                        ),
                        col_widths=(3, 2, 7),
                    ),
                    ui.accordion(
                        ui.accordion_panel(
                            "Map display: colours, range and terrain",
                            ui.layout_columns(
                                ui.input_select("colour_map", "Colour map", list(COLOUR_MAPS)),
                                ui.input_radio_buttons("scale", "Scale", {"linear": "Linear", "log": "Log"}, inline=True),
                                ui.input_numeric("vmin", "Minimum", value=None, step="any"),
                                ui.input_numeric("vmax", "Maximum", value=None, step="any"),
                                ui.div(ui.input_action_button("auto_range", "Automatic range", class_="btn-sm"), class_="pt-4"),
                                col_widths=(2, 2, 2, 2, 3),
                            ),
                            ui.input_switch("terrain", with_tip("Terrain", "Shaded relief under the map. Downloaded the first time it is used."), value=False),
                            ui.output_ui("terrain_status"),
                        ),
                        open=False,
                    ),
                    ui.p("Click a cell on the map for its time series below, and a second cell to compare. "
                         "Drag to zoom, double-click to see the whole grid again.", class_="small text-muted mb-0"),
                    ui.div(id="map", style="height: 680px;"),
                    ui.div(id="cell_plot", style="height: 300px;"),
                    ui.panel_conditional("input.seed_band", ui.div(id="envelope_plot", style="height: 340px;")),
                ),
                value="results",
            ),
            ui.nav_menu(
                "Analysis (to come)",
                *[ui.nav_panel(name, ui.p(text, class_="text-muted mt-3")) for name, text in ANALYSIS_TABS],
            ),
            ui.nav_panel("Calibration (to come)",
                         ui.p("Calibration of model parameters against observations, with the ", ui.a("Optuna", href=OPTUNA_URL, target="_blank"),
                              " parameter optimisation suite: to come.", class_="text-muted mt-3"),
                         value="calibration"),
            ui.nav_panel("Help", help_tab(), value="help"),
            id="tab",
            selected="setup",
        ),
        funders(),
        title=page_title(ui.output_ui("header")),
    )

    def server(input, output, session):
        current = reactive.value(None)
        selected_cells = reactive.value([])
        runs_changed = reactive.value(0)
        range_overrides = reactive.value({})  # {(menu entry, scale): (minimum, maximum)} set by hand
        state = RunState()
        setup = reactive.value(config)  # The applied settings of the Setup panel
        setup_problem = reactive.value(None)
        if model_note:
            ui.notification_show(model_note, type="warning", duration=None)
        browse = reactive.value(None)  # {"field", "kind", "folder"} of the open file browser

        @reactive.calc
        def grid():
            return load_grid(setup())

        @reactive.calc
        def slider_setup():
            """A slider starts at the value in the `const` file, or else at the value compiled into the model.
            Its range includes that value: a slider cannot start outside it."""
            in_const = read_params(setup().inputs["const"])
            compiled = default_params()
            defaults = {name: float(in_const.get(name, compiled.get(name))) for name in default_sliders()}
            sources = {name: "const" if name in in_const else "default" for name in default_sliders()}
            sliders = {
                name: {**spec, "min": min(spec["min"], defaults[name]), "max": max(spec["max"], defaults[name])}
                for name, spec in default_sliders().items()
            }
            return {"sliders": sliders, "defaults": defaults, "sources": sources, "const": Path(setup().inputs["const"]).name}

        # Made also while their tab is hidden: a run takes the values of the sliders, and those of a loaded
        # run are set on them, before the tab is ever opened
        @output(suspend_when_hidden=False)
        @render.ui
        def parameter_sliders():
            sliders = slider_setup()
            return ui.TagList(
                parameter_legend(sliders["const"]),
                *slider_groups(sliders["sliders"], sliders["defaults"], sliders["sources"]),
            )

        @reactive.effect
        async def send_slider_decimals():
            sliders = slider_setup()["sliders"]
            await session.send_custom_message("slider_decimals", {f"param_{n}": slider_grid(s)[3] for n, s in sliders.items()})

        @render.ui
        def header():
            return page_header(setup())

        def selected_output():
            flags = [flag for group in OUTPUT_FLAGS.values() for flag, _, _ in group]
            return tuple(flag for flag in flags if input[output_switch_id(flag)]())

        def overrides():
            """Sliders moved from their value in the `const` file; the others keep it as written there."""
            moved = {}
            sliders = slider_setup()
            for name, spec in sliders["sliders"].items():
                if f"param_{name}" not in input:
                    continue
                value = input[f"param_{name}"]()
                _, _, step, decimals = slider_grid(spec)
                # A slider starts at the value of the `const` file snapped to its step
                if abs(value - round(sliders["defaults"][name], decimals)) >= step / 2:
                    moved[name] = round(float(value), decimals)
            return moved

        def grid_key():
            return extent_key(grid()["lon"], grid()["lat"])

        analysis = sensitivity_server(
            input, output, session, setup, slider_setup, overrides, selected_output, lambda: run_task.status() == "running",
            lambda: agents(), lambda: input.ha(),  # agents is defined further down
        )

        basemap_for = reactive.value(None)  # The grid the basemap and the terrain were asked for
        terrain_for = reactive.value(None)

        @reactive.extended_task
        async def basemap_task(lon, lat):
            return await asyncio.to_thread(load_basemap, lon, lat)

        @reactive.effect
        def fetch_basemap():
            key = grid_key()
            with reactive.isolate():
                if basemap_for() == key:
                    return
                basemap_for.set(key)
                basemap_task.invoke(grid()["lon"], grid()["lat"])

        @reactive.extended_task
        async def terrain_task(lon, lat):
            return await asyncio.to_thread(load_terrain, lon, lat, LAND)

        @reactive.effect
        def fetch_terrain():
            if not input.terrain() or basemap() is None:
                return
            key = grid_key()
            with reactive.isolate():
                # Again for another grid, or when the last download failed
                failed = terrain_task.status() == "success" and terrain_task.result() is None
                if terrain_for() != key or failed:
                    terrain_for.set(key)
                    terrain_task.invoke(grid()["lon"], grid()["lat"])

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
            if input.terrain() and terrain_task.status() == "success" and terrain_for() == grid_key():
                return terrain_task.result()
            return None

        def basemap():
            """None until it is ready, and if it cannot be obtained: the map is then plain."""
            return basemap_task.result() if basemap_task.status() == "success" and basemap_for() == grid_key() else None

        @ui.bind_task_button(button_id="run")
        @reactive.extended_task
        async def run_task(run_config, seeds, name):
            return await asyncio.to_thread(run_model, run_config, seeds, state, name)

        @reactive.effect
        @reactive.event(input.run)
        def start_run():
            nagent, seed = agents(), input.seed()
            n_seeds = input.n_seeds() if input.seed_band() else 1
            if not all(isinstance(value, int) and value >= 1 for value in (nagent, seed, n_seeds)):
                ui.notification_show("HA must be positive, and the seed and number of seeds positive integers.", type="error")
                return
            if input.ha() < 1:
                ui.notification_show(HA_BELOW_ONE, type="error")
                return
            if analysis.running():
                ui.notification_show("A sensitivity analysis is running: wait for it, or cancel it, before a single run.", type="warning")
                return
            try:
                run_config = replace(setup(), params={**setup().params, **overrides()}, output=selected_output()).with_run(nagent=nagent, seed=seed)
            except ConfigError as error:
                ui.notification_show(str(error), type="error")
                return
            name = input.run_name().strip()
            problem = run_name_problem(name, setup().runs_dir)
            if problem:
                ui.notification_show(problem, type="error")
                return
            save_setup(run_config)
            state.update(cancelled=False, message="Starting", fraction=None, runner=None)
            run_task.invoke(run_config, [seed + i for i in range(n_seeds)], name or None)
            # So that the next run does not take the same name
            ui.update_text("run_name", value="")
            ui.update_navs("tab", selected="results")

        @reactive.effect
        def enable_cancel():
            ui.update_action_button("cancel", disabled=run_task.status() != "running")

        @reactive.effect
        @reactive.event(input.cancel)
        def cancel_run():
            state.update(cancelled=True)
            if state.runner is not None:
                state.runner.cancel()

        async def close_app():
            """Stop any run or analysis, tell the browser, then stop the server as Ctrl+C does."""
            analysis.cancel()
            state.update(cancelled=True)
            if state.runner is not None:
                state.runner.cancel()
            await session.send_custom_message("closed", {})
            asyncio.get_running_loop().call_later(0.5, os.kill, os.getpid(), signal.SIGINT)

        @reactive.effect
        @reactive.event(input.close)
        async def ask_to_close():
            if run_task.status() != "running" and not analysis.running():
                await close_app()
                return
            ui.modal_show(
                ui.modal(
                    "A run or sensitivity analysis is in progress. Closing the GUI will cancel it; an analysis can be resumed later.",
                    title="Close the GUI?",
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
            # Runs on any grid: loading one also restores the setup it was made with
            return list_runs(setup().runs_dir)

        @reactive.effect
        def refresh_previous_runs():
            runs_changed()
            ui.update_select(
                "previous_run",
                choices={folder: run_label(folder, manifest) for folder, manifest in available_runs().items()},
            )

        @render.text
        def runs_folder():
            return f"In {setup().runs_dir}"

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
                restored = from_manifest(manifest, setup())
            except ConfigError as error:
                ui.notification_show("Could not restore the setup of this run: " + "; ".join(setup_problems(error)), type="error")
                return
            try:
                outcome = load_outcome(folder, manifest)
            except (KeyError, OSError, RuntimeError) as error:
                ui.notification_show(f"Could not load this run: {error}", type="error")
                return
            restored, model_note_for_run = available_model(restored)
            adopt(restored, keep_outcome=True)
            if model_note_for_run:
                ui.notification_show(model_note_for_run, type="warning", duration=None)
            show(outcome)
            ui.update_navs("tab", selected="results")
            ui.update_numeric("ha", value=ha_for(outcome.nagent))
            ui.update_numeric("seed", value=outcome.seeds[0])
            ui.update_switch("seed_band", value=len(outcome.seeds) > 1)
            if len(outcome.seeds) > 1:
                ui.update_numeric("n_seeds", value=len(outcome.seeds))
            # After the sliders of the restored setup are made
            pending_sliders.set(dict(outcome.overrides))
            written = manifest.get("output")
            written = default_output if written is None else set(written)
            for group in OUTPUT_FLAGS.values():
                for flag, _, _ in group:
                    ui.update_switch(output_switch_id(flag), value=flag in written)

        @reactive.effect
        @reactive.event(input.reset)
        def reset_sliders():
            for name, value in slider_setup()["defaults"].items():
                ui.update_slider(f"param_{name}", value=value)

        pending_sliders = reactive.value(None)  # Values of a loaded run, set once its sliders exist

        @reactive.effect
        def restore_sliders():
            moved = pending_sliders()
            if moved is None:
                return
            sliders = slider_setup()
            if not all(f"param_{name}" in input for name in sliders["sliders"]):
                reactive.invalidate_later(0.2)
                return
            with reactive.isolate():
                pending_sliders.set(None)
            for name, value in sliders["defaults"].items():
                ui.update_slider(f"param_{name}", value=moved.get(name, value))

        def adopt(new, keep_outcome=False):
            """Apply a setup: the grid, map, sliders and runs follow it, and it is remembered."""
            old = setup()
            setup_problem.set(None)
            if new == old:
                return
            grid_changed = (old.inputs["pop_file"], old.inputs["area_file"], old.region) != (new.inputs["pop_file"], new.inputs["area_file"], new.region)
            setup.set(new)
            save_setup(replace(new, run={**new.run, "nagent": agents() or new.run["nagent"], "seed": input.seed() or new.run["seed"]}))
            show_setup_fields(new)
            if grid_changed and not keep_outcome:
                current.set(None)
                selected_cells.set([])
                range_overrides.set({})

        def show_setup_fields(config):
            ui.update_text("setup_project", value=config.project)
            ui.update_text("setup_runs_dir", value=str(config.runs_dir))
            for key, _, _ in (*REQUIRED_FILES, *OPTIONAL_FILES):
                ui.update_text(f"setup_{key}", value=setup_value(config, key))
            ui.update_select("setup_disID", selected=str(config.run["disID"]))
            values = period_values(config)
            if values is not None:
                first, last, start, end = values
                ui.update_date("setup_start", value=start, min=first, max=last)
                ui.update_date("setup_end", value=end, min=first, max=last)
            ui.update_switch("setup_spin_up", value=config.run["spin_up"] == 1)
            ui.update_numeric("setup_threads", value=config.run["threads"])
            mode, values = region_values(config)
            ui.update_radio_buttons("setup_region", selected=mode)
            for key, value in values.items():
                ui.update_numeric(f"setup_{key}", value=value)
            ui.update_switch("setup_counterfactual", value=config.inputs.get("counterfactual") == 1)

        @reactive.effect
        @reactive.event(input.apply_setup)
        def apply_setup():
            if run_task.status() == "running" or analysis.running():
                ui.notification_show("Wait for the run or analysis to finish, or cancel it, before changing the setup.", type="warning")
                return
            typed = typed_days()
            if typed is not None and typed[2]:
                setup_problem.set([f"Period: {typed[2]}"])
                return
            # Also the whole driving data, which the configuration does not count
            spin_up = spin_up_problem(int(input.setup_spin_up()), typed and (typed[1] - typed[0]).days + 1)
            if spin_up:
                setup_problem.set([f"Period: {spin_up}"])
                return
            period = None
            if typed is not None and (typed[0], typed[1]) != tuple(parse_day(day) for day in driving_span()):
                period = {"start": typed[0].isoformat(), "end": typed[1].isoformat()}
            run = {
                "disID": int(input.setup_disID()),
                "mob": setup().run["mob"],
                "nstep": 0 if period is None else period_days(period),
                "spin_up": 1 if input.setup_spin_up() else 0,
                "nagent": agents() or setup().run["nagent"],
                "seed": input.seed(),
                "threads": input.setup_threads(),
            }
            files = {key: input[f"setup_{key}"]() for key, _, _ in (*REQUIRED_FILES, *OPTIONAL_FILES)}
            files["counterfactual"] = 1 if input.setup_counterfactual() else 0
            try:
                new = from_fields(setup().mobile, input.setup_project(), input.setup_runs_dir(), run, files, typed_region(), period)
            except ConfigError as error:
                setup_problem.set(setup_problems(error))
                return
            problem = typed_region_grid()[2]
            if new.region is not None and problem:
                setup_problem.set([f"Region: {problem}"])
                return
            problems = driving_problems(new.inputs)
            if problems:
                pending_setup.set(new)
                ui.modal_show(ui.modal(
                    ui.p("The driving files may not work together:"),
                    ui.tags.ul(*[ui.tags.li(problem) for problem in problems]),
                    ui.p("A run with these files may stop, or give results in the wrong units.", class_="mb-0"),
                    title="Check the driving files",
                    footer=[ui.input_action_button("apply_anyway", "Apply anyway", class_="btn-warning"),
                            ui.modal_button("Go back and change the files")],
                    easy_close=True,
                ))
                return
            finish_apply(new)

        pending_setup = reactive.value(None)  # The setup waiting for an answer to the warning on the driving files

        @reactive.effect
        @reactive.event(input.apply_anyway)
        def apply_anyway():
            new = pending_setup()
            ui.modal_remove()
            if new is not None:
                pending_setup.set(None)
                finish_apply(new)

        def finish_apply(new):
            adopt(new)
            ui.notification_show("Setup applied.", type="message", duration=3)
            ui.update_navs("tab", selected="parameters")

        @reactive.calc
        def driving_span():
            """(first, last) day, as ISO dates, of the rainfall file in the box of the Setup tab; None if it has no days."""
            try:
                days = driving_days(typed_path(input.setup_rain_file()))
            except (OSError, ValueError, RuntimeError):
                return None
            return None if days is None or not len(days) else (str(days[0]), str(days[-1]))

        @reactive.effect
        def fit_period_to_driving():
            """The period of a new rainfall file starts as all of its days; that of the applied setup is kept."""
            span = driving_span()
            if span is None:
                return
            start, end = span
            with reactive.isolate():
                config = setup()
                if config.period is not None and str(typed_path(input.setup_rain_file())) == config.inputs["rain_file"]:
                    if span[0] <= config.period["start"] and config.period["end"] <= span[1]:
                        start, end = config.period["start"], config.period["end"]
            ui.update_date("setup_start", value=start, min=span[0], max=span[1])
            ui.update_date("setup_end", value=end, min=span[0], max=span[1])

        @reactive.effect
        @reactive.event(input.setup_period_reset)
        def reset_period():
            """Back to the default period: all the days of the rainfall file in the box."""
            span = driving_span()
            if span is None:
                ui.notification_show("The days of the rainfall file cannot be read.", type="warning")
                return
            ui.update_date("setup_start", value=span[0])
            ui.update_date("setup_end", value=span[1])

        @reactive.calc
        def typed_days():
            """(start, end, problem) as dates, of the period in the boxes of the Setup tab; None without driving days."""
            span = driving_span()
            if span is None:
                return None
            first, last = (parse_day(day) for day in span)
            start, end = parse_day(input.setup_start()) or first, parse_day(input.setup_end()) or last
            problem = None
            if end < start:
                problem = "the end is before the start."
            elif start < first or end > last:
                problem = f"the days must be within the driving data, {first} to {last}."
            return start, end, problem

        @render.ui
        def period_summary():
            typed = typed_days()
            if typed is None:
                return ui.p("The days of the rainfall file cannot be read: all of it is simulated.", class_="small text-muted mb-3")
            start, end, problem = typed
            if problem:
                return ui.p(problem.capitalize(), class_="small text-danger mb-3")
            days = (end - start).days + 1
            spin_up = spin_up_problem(int(input.setup_spin_up()), days)
            total = ui.p(ui.tags.strong("Total simulation time: "), length_text(days), class_="small " + ("mb-1" if spin_up else "mb-3"))
            return ui.TagList(total, ui.p(spin_up.capitalize(), class_="small text-danger mb-3")) if spin_up else total

        @render.ui
        def example_note():
            example = setup().mobile.joinpath(*EXAMPLE_FOLDER)
            typed = [input[f"setup_{key}"]().strip() for key, _, kind in REQUIRED_FILES if kind == "netcdf"]
            if any(value and typed_path(value).is_relative_to(example) for value in typed):
                return example_note_box()
            return None

        def typed_region():
            """The region in the boxes of the Setup tab, before Apply."""
            return region_from_fields(input.setup_region(), *[input[f"setup_{key}"]() for key in ("north", "west", "south", "east")],
                                      input.setup_point_lat(), input.setup_point_lon())

        @reactive.calc
        def typed_region_grid():
            """(region, its grid, what is wrong with it) as in the boxes of the Setup tab."""
            region = typed_region()
            problems = region_problems(region)
            if problems:
                return region, None, problems[0].removeprefix("region: ").capitalize() + "."
            try:
                region_grid = read_grid(typed_path(input.setup_pop_file()), typed_path(input.setup_area_file()), region)
            except (OSError, ValueError, KeyError, StopIteration, RuntimeError):
                return region, None, "The population or cell area file cannot be read."
            if region_grid is None:
                return region, None, "It is outside the grid of the population file."
            if not region_grid["populated"]:
                return region, region_grid, "It has no populated cell."
            return region, region_grid, None

        def degrees(value, positive, negative):
            return f"{abs(value):.3f}°{positive if value >= 0 else negative}"

        @render.ui
        def region_summary():
            region, region_grid, problem = typed_region_grid()
            if problem:
                return ui.p(problem, class_="small text-danger mb-0")
            rows, columns = region_grid["mask"].shape
            people = f"{region_grid['people']:,.0f} people"
            if region_mode(region) == "point":
                place = f"The cell at {degrees(region_grid['lat'][0], 'N', 'S')}, {degrees(region_grid['lon'][0], 'E', 'W')}"
                text = f": {people}."
            else:
                place = "Whole grid" if region is None else "Subregion"
                text = f": {columns} × {rows} cells, {region_grid['populated']:,} of them populated, {people}."
            applied = region == setup().region
            return ui.div(
                ui.p(ui.tags.strong(place), text, class_="small mb-1"),
                None if applied else ui.p("Not applied yet: press Apply setup.", class_="small text-warning-emphasis mb-0"),
            )

        def region_outline():
            """The edges of the cells of the region in the boxes, for the region map; None for the whole grid."""
            region, region_grid, _ = typed_region_grid()
            if region is None or region_grid is None:
                return None
            lon, lat = region_grid["full"]
            half_lon = abs(lon[1] - lon[0]) / 2 if len(lon) > 1 else 0.025
            half_lat = abs(lat[1] - lat[0]) / 2 if len(lat) > 1 else 0.025
            return (float(min(region_grid["lon"])) - half_lon, float(max(region_grid["lon"])) + half_lon,
                    float(min(region_grid["lat"])) - half_lat, float(max(region_grid["lat"])) + half_lat)

        regions_drawn = reactive.value(0)

        @reactive.effect
        @reactive.event(input.region_drawn)
        def region_drawn():
            regions_drawn.set(regions_drawn() + 1)
            box = input.region_drawn()
            values = {"north": max(box["y0"], box["y1"]), "west": min(box["x0"], box["x1"]),
                      "south": min(box["y0"], box["y1"]), "east": max(box["x0"], box["x1"])}
            for key, _ in REGION_BOXES:
                ui.update_numeric(f"setup_{key}", value=round(values[key], 3))
            ui.update_radio_buttons("setup_region", selected="box")

        @reactive.effect
        @reactive.event(input.region_click)
        def pick_point():
            if input.setup_region() == "point":
                cell = input.region_click()
                ui.update_numeric("setup_point_lat", value=round(cell["lat"], 3))
                ui.update_numeric("setup_point_lon", value=round(cell["lon"], 3))

        @reactive.calc
        def region_map_data():
            """The population density in the box of the Setup tab, on which the region is chosen; None if unreadable."""
            try:
                return open_field(typed_path(input.setup_pop_file()), "pop_file")
            except (OSError, ValueError, KeyError, StopIteration, TypeError, RuntimeError):
                return None

        def region_map_extent():
            data = region_map_data()
            return None if data is None else extent_key(data["lon"].values, data["lat"].values)

        region_basemap_for = reactive.value(None)

        @reactive.extended_task
        async def region_basemap_task(lon, lat):
            return await asyncio.to_thread(load_basemap, lon, lat)

        @reactive.effect
        def fetch_region_basemap():
            key = region_map_extent()
            if key is None:
                return
            with reactive.isolate():
                if region_basemap_for() == key:
                    return
                region_basemap_for.set(key)
                data = region_map_data()
                region_basemap_task.invoke(data["lon"].values, data["lat"].values)

        def region_basemap():
            ready = region_basemap_task.status() == "success" and region_basemap_for() == region_map_extent()
            return region_basemap_task.result() if ready else None

        region_climates = {}  # Mean rainfall or temperature computed in this session: {key: (field, problem)}
        region_climates_added = reactive.value(0)

        def climate_or_problem(wanted):
            path, key, start, end, choice = wanted
            try:
                return wanted, climatology(path, key, start, end, REGION_MONTHS[choice][1]), None
            except (OSError, ValueError, KeyError, StopIteration, TypeError, RuntimeError) as error:
                return wanted, None, str(error)

        @reactive.extended_task
        async def region_climate_task(wanted):
            return await asyncio.to_thread(climate_or_problem, wanted)

        @reactive.calc
        def region_climate_key():
            """(path, file key, start, end, choice of months) of the mean the region map shows; None for population.
            Over the period typed in Run parameters, or all the days of the file if it cannot be used."""
            key = input.region_layer()
            if key == "pop_file":
                return None
            typed = typed_days()
            start, end = (None, None) if typed is None or typed[2] else typed[:2]
            return str(typed_path(input[f"setup_{key}"]())), key, start, end, input.region_month()

        @reactive.effect
        def compute_region_climate():
            wanted = region_climate_key()
            if wanted is not None and wanted not in region_climates:
                region_climate_task.invoke(wanted)  # One at a time: a second waits for the first

        @reactive.effect
        def keep_region_climate():
            if region_climate_task.status() != "success":
                return
            wanted, field, problem = region_climate_task.result()
            region_climates[wanted] = (field, problem)
            with reactive.isolate():
                region_climates_added.set(region_climates_added() + 1)

        def region_climate_title(wanted, field):
            _, key, start, end, choice = wanted
            period = f"{start} to {end}" if start is not None else "all the days of the file"
            when = "" if REGION_MONTHS[choice][1] is None else f" in {REGION_MONTHS[choice][0]}"
            return f"Mean {REGION_LAYERS[key].lower()}{when}, {period} ({field.attrs['days']:,} days)"

        @reactive.effect
        async def draw_region_map():
            """The population, or the mean rainfall or temperature, and the region in the boxes. What a drag or a click does depends on the choice:
            nothing for the whole grid, a rectangle for a subregion, a cell for a point."""
            regions_drawn()  # A rectangle drawn is replaced by the region it gives
            data = region_map_data()
            if data is None:
                await send_figure(session, "region_map", message_figure("Choose a population density file in Driving files to see the grid."))
                return
            mode = input.setup_region()
            region, region_grid, _ = typed_region_grid()
            wanted = region_climate_key()
            if wanted is None:
                title = "Population density"
                figure = map_figure(data, None, (title, data.attrs.get("units", "")), 1, field_limits(data, log=True),
                                    (), region_basemap(), colour_map="Reds", log=True)
            else:
                region_climates_added()
                name = REGION_LAYERS[wanted[1]].lower()
                if wanted not in region_climates:
                    await send_figure(session, "region_map", message_figure(f"Computing the mean {name}…"))
                    return
                field, problem = region_climates[wanted]
                if problem is not None:
                    await send_figure(session, "region_map", message_figure(f"The mean {name} cannot be computed: {problem}."))
                    return
                title = region_climate_title(wanted, field)
                figure = map_figure(field, None, (title, field.attrs.get("units", "")), 1, field_limits(field),
                                    (), region_basemap(), colour_map=PREVIEW_STYLE[wanted[1]][0])
            outline = region_outline()
            if outline is not None:
                west, east, south, north = outline
                figure.add_shape(type="rect", name="region", x0=west, x1=east, y0=south, y1=north, layer="above",
                                 line={"color": BOX, "width": 2.5}, fillcolor="rgba(255, 255, 255, 0.15)")
            if mode == "point" and region_grid is not None:
                figure.add_trace(go.Scatter(x=[region_grid["lon"][0]], y=[region_grid["lat"][0]], mode="markers", hoverinfo="skip",
                                            marker={"symbol": "circle-open", "size": 18, "line": {"width": 3}, "color": BOX},
                                            showlegend=False))
            figure.update_layout(
                title=f"{title}<br><span style='font-size: 0.85em'>{REGION_MAP_TITLES[mode]}</span>",
                margin={"t": 66},  # Two lines of title
                dragmode="drawrect" if mode == "box" else "zoom",
                newshape={"line": {"color": BOX, "width": 2, "dash": "dot"}},
                # The zoom is kept while the grid is the same
                uirevision=str(region_map_extent()),
            )
            await send_figure(session, "region_map", figure)

        @render.ui
        def setup_status():
            problems = setup_problem()
            if not problems:
                return None
            return ui.div(
                ui.p("Not applied:", class_="mb-1 fw-semibold"),
                ui.tags.ul(*[ui.tags.li(problem) for problem in problems], class_="ps-3 mb-0"),
                class_="small text-danger mt-2",
            )

        def open_browser(field, kind):
            browse.set({"field": field, "kind": kind, "folder": start_folder(input[field]())})
            footer = [ui.modal_button("Cancel")]
            if kind == "folder":
                footer.insert(0, ui.input_action_button("browser_use_folder", "Use this folder", class_="btn-primary"))
            body = [ui.output_ui("browser")]
            if kind == "folder":
                body.append(ui.div(
                    ui.input_text("browser_new_name", "New folder in the folder shown", placeholder="e.g. kenya_2025", width="100%"),
                    ui.input_action_button("browser_new_folder", "Create and open", class_="mb-3"),
                    class_="d-flex gap-2 align-items-end border-top pt-3",
                ))
            ui.modal_show(ui.modal(*body, title="Choose a folder" if kind == "folder" else "Choose a file",
                                   footer=ui.TagList(*footer), size="l", easy_close=True))

        def browse_button(field, kind):
            @reactive.effect
            @reactive.event(input[f"browse_{field}"], ignore_init=True)
            def _():
                open_browser(field, kind)

        browse_button("setup_runs_dir", "folder")
        for key, _, kind in (*REQUIRED_FILES, *OPTIONAL_FILES):
            browse_button(f"setup_{key}", kind)

        @render.ui
        def browser():
            state_ = browse()
            if state_ is None:
                return None
            folder = state_["folder"]
            folders, files = list_folder(folder, state_["kind"])

            def entry(name, is_folder):
                return ui.tags.li(ui.tags.a(("📁 " if is_folder else "") + name, href="#", class_="browse-entry",
                                            **{"data-name": name, "data-folder": "1" if is_folder else "0"}))

            items = [entry("..", True)] if folder.parent != folder else []
            items += [entry(name, True) for name in folders] + [entry(name, False) for name in files]
            note = "" if state_["kind"] == "folder" else f"Showing {', '.join(SUFFIX_NAMES[state_['kind']])} files."
            return ui.div(
                ui.p(ui.tags.code(str(folder)), class_="mb-1"),
                ui.p(note, class_="small text-muted mb-2") if note else None,
                ui.tags.ul(*items, class_="list-unstyled", style="max-height: 50vh; overflow-y: auto;"),
            )

        @reactive.effect
        @reactive.event(input.browser_pick)
        def browser_pick():
            state_ = browse()
            pick = input.browser_pick()
            if state_ is None:
                return
            if pick["folder"]:
                folder = state_["folder"].parent if pick["name"] == ".." else state_["folder"] / pick["name"]
                browse.set({**state_, "folder": folder.resolve()})
                return
            ui.update_text(state_["field"], value=str(state_["folder"] / pick["name"]))
            ui.modal_remove()

        @reactive.effect
        @reactive.event(input.browser_new_folder)
        def browser_new_folder():
            state_ = browse()
            if state_ is None or state_["kind"] != "folder":
                return
            path, problem = create_folder(state_["folder"], input.browser_new_name())
            if problem:
                ui.notification_show(problem, type="error")
                return
            browse.set({**state_, "folder": path})
            ui.update_text("browser_new_name", value="")

        @reactive.effect
        @reactive.event(input.browser_use_folder)
        def browser_use_folder():
            state_ = browse()
            if state_ is not None:
                ui.update_text(state_["field"], value=str(state_["folder"]))
                ui.modal_remove()

        def ha_for(nagent):
            """HA, to 8 significant digits, that gives this number of agents."""
            return float(f"{grid()['people'] / nagent:.8g}")

        @reactive.calc
        def agents():
            """The number of agents for the HA set: the people of the simulated region over HA."""
            ha = input.ha()
            if not ha or ha <= 0:
                return None
            return max(round(grid()["people"] / ha), 1)

        # HA starts from the number of agents of the setup. After that it is the entry, and the number of
        # agents follows it, also when the region changes.
        started = reactive.value(False)

        @reactive.effect
        def initial_ha():
            grid()
            with reactive.isolate():
                if not started():
                    started.set(True)
                    ui.update_numeric("ha", value=ha_for(config.run["nagent"]))

        @render.ui
        def humans_per_agent():
            nagent = agents()
            if nagent is None:
                return None
            people = grid()["people"]
            text = f"{people:,.0f} people in the simulated region, {nagent:,} agents"
            # Far from 1, as after choosing a small region
            if not HUMANS_PER_AGENT_RANGE[0] <= people / nagent <= HUMANS_PER_AGENT_RANGE[1]:
                text += f". HA = 1 would be {max(round(people), 1):,} agents."
            if input.ha() < 1:
                return ui.TagList(text, ui.div(HA_BELOW_ONE, class_="text-danger"))
            return text

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
                return ui.card(ui.p("The app failed while running or reading the results. The terminal you started the GUI from shows why."), class_="border-danger")
            outcome = current()
            if outcome is None or outcome.status == "finished":
                return None
            if outcome.status == "cancelled":
                return ui.p("Run cancelled.", class_="mb-0")
            return ui.card(ui.p("The run failed. End of its log:"), ui.tags.pre(outcome.log), class_="border-danger")

        @render.ui
        def run_summary():
            """What the Results tab shows: guidance before the first results, then which run they are from."""
            outcome = current()
            if outcome is None:
                return None if run_task.status() == "running" else no_run_yet()
            if outcome.status != "finished":
                return None
            changed = ", ".join(f"{k}={v:.4g}" for k, v in outcome.overrides.items()) or "none"
            seeds = f"seed {outcome.seeds[0]}" if len(outcome.seeds) == 1 else f"seeds {outcome.seeds[0]} to {outcome.seeds[-1]}"
            return ui.p(
                f"{'Loaded' if outcome.loaded else 'Showing'}: {outcome.nagent:,} agents, {seeds}, changed parameters: {changed}. "
                f"Folder: {outcome.run_dir}",
                class_="small mb-2",
            )

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
                        data = data.where(mask_like(data, grid()))
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
            ui.update_numeric("vmin", value=sig(lowest))
            ui.update_numeric("vmax", value=sig(highest))

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
            if sig(lowest) == sig(shown[0]) and sig(highest) == sig(shown[1]):
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
                    f"Log scale: the automatic minimum, {sig(lowest)}, is the 1st percentile of the positive values. "
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
                await send_figure(session, "map", grid_figure(grid(), basemap(), terrain()))
                return
            name = shown_variable(outcome)
            data = outcome.fields(name)[shown_member(outcome)]
            day = min(input.day(), outcome.days)
            await send_figure(
                session, "map",
                map_figure(
                    data, grid(), outcome.describe(name), day, shown_limits(), selected_cells(), basemap(), terrain(),
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
                await send_figure(session, "cell_plot", message_figure("Press Run, then click a cell on the map to see its time series."))
                return
            if not cells:
                await send_figure(session, "cell_plot", message_figure("Click a cell on the map to see its time series, and a second one to compare."))
                return
            name = shown_variable(outcome)
            if outcome.variables[name]["static"]:
                await send_figure(session, "cell_plot", message_figure(STATIC_MESSAGE))
                return
            member = shown_member(outcome)
            data = outcome.fields(name)[member]
            seed = outcome.seeds[member] if len(outcome.seeds) > 1 else None
            await send_figure(session, "cell_plot", cell_figure(data, outcome.describe(name), cells, min(input.day(), outcome.days), seed))

        @reactive.effect
        async def draw_envelope():
            if not input.seed_band():
                return
            outcome = current()
            cells = selected_cells()
            if outcome is None or len(outcome.seeds) < 2:
                await send_figure(session, "envelope_plot", message_figure("Press Run to run the seeds with the same parameters."))
            elif not cells:
                await send_figure(session, "envelope_plot", message_figure("Click a cell on the map to see its range across seeds."))
            elif outcome.variables[shown_variable(outcome)]["static"]:
                await send_figure(session, "envelope_plot", message_figure(STATIC_MESSAGE))
            else:
                name = shown_variable(outcome)
                await send_figure(session, "envelope_plot", envelope_figure(outcome.fields(name), outcome.seeds, outcome.describe(name), cells))

        # Preview of the driving files, in the Setup panel
        preview_cells = reactive.value([])  # The dots on the map: {lon, lat, colour}
        preview_selected = reactive.value(0)  # Index of the dot that a click on the map moves
        preview_adding = reactive.value(False)  # The next click on the map adds a dot
        preview_dots_for = reactive.value(None)  # The grid the dots are on
        preview_ranges = reactive.value({})  # {(path, scale): (minimum, maximum)} set by hand

        @reactive.calc
        def preview_data():
            """(file key, path, what was read, why nothing was) of the file chosen for the preview, as in its box."""
            key = input.preview_file()
            typed = input[f"setup_{key}"]().strip()
            if not typed:
                return key, None, None, f"No {PREVIEW_FILES[key].lower()} file in the box above."
            path = typed_path(typed)
            try:
                data = read_age(path) if key == "age_file" else open_field(path, key)
            except (OSError, ValueError, KeyError, StopIteration, TypeError, RuntimeError) as error:
                return key, path, None, f"Cannot read {path}: {error or type(error).__name__}"
            return key, path, data, None

        def preview_map_data():
            """The field on the preview map, or None for the age structure or a file that cannot be read."""
            key, _, data, problem = preview_data()
            return None if problem or key not in PREVIEW_STYLE else data

        @reactive.effect
        @reactive.event(input.preview_file)
        def preview_style():
            key = input.preview_file()
            if key in PREVIEW_STYLE:
                colour_map, scale = PREVIEW_STYLE[key]
                ui.update_select("preview_colour_map", selected=colour_map)
                ui.update_radio_buttons("preview_scale", selected=scale)

        @reactive.effect
        def preview_days():
            data = preview_map_data()
            if data is not None and "time" in data.dims:
                days = data.sizes["time"]
                with reactive.isolate():
                    ui.update_slider("preview_day", max=max(days, 2), value=min(input.preview_day(), days))

        @reactive.calc
        def preview_auto_limits():
            return field_limits(preview_map_data(), input.preview_scale() == "log")

        def preview_range_key():
            return str(preview_data()[1]), input.preview_scale()

        def preview_limits():
            return preview_ranges().get(preview_range_key()) or preview_auto_limits()

        @reactive.effect
        def show_preview_range():
            if preview_map_data() is None:
                return
            lowest, highest = preview_limits()
            ui.update_numeric("preview_vmin", value=sig(lowest))
            ui.update_numeric("preview_vmax", value=sig(highest))

        @reactive.effect
        @reactive.event(input.preview_vmin, input.preview_vmax, ignore_init=True)
        def set_preview_range():
            lowest, highest = input.preview_vmin(), input.preview_vmax()
            if preview_map_data() is None or lowest is None or highest is None:
                return
            with reactive.isolate():
                shown = preview_limits()
                key = preview_range_key()
            # The boxes show the range rounded: that is not a change
            if sig(lowest) == sig(shown[0]) and sig(highest) == sig(shown[1]):
                return
            if lowest >= highest or (key[1] == "log" and lowest <= 0):
                ui.notification_show("Not applied: the minimum must be below the maximum, and above 0 on a log scale.", type="warning")
                return
            preview_ranges.set({**preview_ranges(), key: (float(lowest), float(highest))})

        @reactive.effect
        @reactive.event(input.preview_auto_range)
        def preview_automatic_range():
            ranges = dict(preview_ranges())
            ranges.pop(preview_range_key(), None)
            preview_ranges.set(ranges)

        preview_basemap_for = reactive.value(None)

        @reactive.extended_task
        async def preview_basemap_task(lon, lat):
            return await asyncio.to_thread(load_basemap, lon, lat)

        def preview_extent():
            data = preview_map_data()
            return None if data is None else extent_key(data["lon"].values, data["lat"].values)

        @reactive.effect
        def fetch_preview_basemap():
            key = preview_extent()
            # The basemap of the Runs map serves a file on the same grid
            if key is None or key == grid_key():
                return
            with reactive.isolate():
                if preview_basemap_for() == key:
                    return
                preview_basemap_for.set(key)
                data = preview_map_data()
                preview_basemap_task.invoke(data["lon"].values, data["lat"].values)

        def preview_basemap():
            key = preview_extent()
            if key == grid_key():
                return basemap()
            ready = preview_basemap_task.status() == "success" and preview_basemap_for() == key
            return preview_basemap_task.result() if ready else None

        def preview_description():
            key, path, data, _ = preview_data()
            return f"{PREVIEW_FILES[key]}: {path.name}", data.attrs.get("units", "")

        @reactive.effect
        async def draw_preview():
            key, path, data, problem = preview_data()
            if problem:
                await send_figure(session, "preview_map", message_figure(problem))
                return
            if key == "age_file":
                await send_figure(session, "preview_map", age_figure(*data, path.name))
                return
            day = min(input.preview_day(), data.sizes.get("time", 1))
            figure = map_figure(
                data, None, preview_description(), day, preview_limits(), preview_cells(), preview_basemap(),
                colour_map=input.preview_colour_map(), log=input.preview_scale() == "log", selected=preview_selected(),
            )
            # The zoom is kept while the grid is the same
            figure.update_layout(meta={"date": figure.layout.meta["date"], "view": str(preview_extent())})
            await send_figure(session, "preview_map", figure)

        @reactive.effect
        def start_preview_dots():
            """One dot, in the middle of the data, for each grid: the dots are kept while the file changes to another on the same grid."""
            extent = preview_extent()
            if extent is None:
                return
            # The files of a grid can differ in the last digits of their coordinates
            key = tuple(round(value, 3) for value in extent)
            with reactive.isolate():
                if preview_dots_for() == key:
                    return
                preview_dots_for.set(key)
                dot = default_dot(preview_map_data())
                preview_cells.set([dot] if dot else [])
                preview_selected.set(0)
                preview_adding.set(False)

        @reactive.effect
        @reactive.event(input.preview_add)
        def add_preview_dot():
            if preview_map_data() is None:
                return
            if len(preview_cells()) >= MAX_DOTS:
                ui.notification_show(f"At most {MAX_DOTS} dots: remove one to add another.", type="warning")
                return
            preview_adding.set(not preview_adding())

        @reactive.effect
        def show_preview_adding():
            adding = preview_adding()
            ui.update_action_button("preview_add", label="Click a cell on the map…" if adding else "Add dot")

        @reactive.effect
        @reactive.event(input.preview_cell)
        def select_preview_cell():
            with reactive.isolate():
                if preview_map_data() is None:
                    return
                cell = input.preview_cell()
                dots = preview_cells()
                if preview_adding() or not dots:
                    added = add_dot(dots, cell["lon"], cell["lat"])
                    preview_cells.set(added)
                    preview_selected.set(len(added) - 1)
                    preview_adding.set(False)
                else:
                    preview_cells.set(move_dot(dots, preview_selected(), cell["lon"], cell["lat"]))

        @reactive.effect
        @reactive.event(input.preview_dot_select)
        def select_preview_dot():
            preview_selected.set(input.preview_dot_select()["index"])

        @reactive.effect
        @reactive.event(input.preview_dot_remove)
        def remove_preview_dot():
            index = input.preview_dot_remove()["index"]
            dots = preview_cells()
            preview_cells.set(remove_dot(dots, index))
            selected = preview_selected()
            preview_selected.set(max(0, selected - 1) if index <= selected else selected)

        @render.ui
        def preview_dots():
            dots, selected = preview_cells(), preview_selected()
            if preview_adding():
                hint = "Click a cell on the map to place the new dot."
            elif not dots:
                hint = "No dots: press Add dot, then click a cell on the map."
            elif len(dots) == 1:
                hint = "Click a cell on the map to move the dot, or press Add dot to compare another cell."
            else:
                hint = "Click a cell on the map to move the highlighted dot. Click a row to highlight another."
            rows = [
                ui.div(
                    ui.span(class_="dot-swatch", style=f"background: {DOT_COLOURS[dot['colour']]};"),
                    ui.span(f"{index + 1}. {dot_label(dot)}"),
                    ui.tags.button("✕", type="button", class_="dot-remove btn btn-sm btn-link text-danger", title="Remove this dot",
                                   **{"data-index": index, "aria-label": f"Remove dot {index + 1}"}),
                    class_="dot-row" + (" selected" if index == selected else ""), tabindex="0", role="button",
                    **{"data-index": index, "aria-pressed": str(index == selected).lower()},
                )
                for index, dot in enumerate(dots)
            ]
            return ui.div(*rows, ui.p(hint, class_="small text-muted mt-1 mb-0"))

        @reactive.effect
        async def draw_preview_cells():
            key, _, _, problem = preview_data()
            data = preview_map_data()
            if key not in DAILY_FILES or problem:
                return
            if "time" not in data.dims:
                await send_figure(session, "preview_cell_plot", message_figure("This file has no days: see the map."))
                return
            if not preview_cells():
                await send_figure(session, "preview_cell_plot", message_figure("Add a dot on the map to see the daily values of its cell."))
                return
            # The line of the day is moved by the browser as the day changes, so the day is not a dependency
            with reactive.isolate():
                day = min(input.preview_day(), data.sizes["time"])
            figure = cell_figure(data, preview_description(), preview_cells(), day, from_zero=key == "rain_file")
            await send_figure(session, "preview_cell_plot", figure)

    return App(app_ui, server, static_assets={"/assets": ASSETS})


HOST = "127.0.0.1"
PORTS_TO_TRY = 20


def free_port(port, host=HOST, tries=PORTS_TO_TRY):
    """The first port from `port` on that nothing is listening on, e.g. another GUI still open."""
    for candidate in range(port, port + tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            try:
                probe.bind((host, candidate))
            except OSError:
                continue
            return candidate
    raise OSError(f"Ports {port} to {port + tries - 1} are all in use: close another GUI, or choose one with --port")


def launch(config, port=8000, browser=True):
    chosen = free_port(port)
    if chosen != port:
        print(f"Port {port} is in use, probably by another GUI: using {chosen}.", flush=True)
    print(f"GUI at http://{HOST}:{chosen}", flush=True)
    run_app(create_app(config), host=HOST, port=chosen, launch_browser=browser)
