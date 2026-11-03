"""Local Shiny interface: fixed grid and driving data, parameters on sliders, the real model behind Run."""

import asyncio
import os
import signal
import socket
from dataclasses import replace
from pathlib import Path

import plotly.offline
from shiny import App, reactive, render, run_app, ui

from .basemap import load_basemap, load_terrain
from .config import ConfigError, default_params, default_sliders, read_params
from .driving import field_limits, open_field, read_age
from .grid import extent_key, load_grid, mask_like
from .layout import (
    ANALYSIS_TABS, ASSETS, GUI_OUTPUT, OUTPUT_FLAGS, docs, funders, output_groups, output_switch_id,
    no_run_yet, page_header, parameter_legend, player_controls, slider_grid, slider_groups, with_tip,
)
from .outcome import RunState, load_outcome, run_label, run_model, run_name_problem
from .plots import (
    COLOUR_MAPS, LAND, age_figure, cell_figure, envelope_figure, grid_figure, map_figure, message_figure,
    next_cells, send_figure, sig,
)
from .results import list_runs
from .scripts import BROWSER_HANDLER, CLOSED_HANDLER, PARAMETER_STYLE, PLAYER, PLOT_HANDLER, SLIDER_FORMAT
from .setup import (
    OPTIONAL_FILES, REQUIRED_FILES, from_fields, from_manifest, create_folder, list_folder, save_setup, start_folder,
    typed_path,
)
from .setup_ui import (
    DAILY_FILES, PREVIEW_FILES, PREVIEW_STYLE, SUFFIX_NAMES, setup_problems, setup_tab, setup_value,
)
from .variables import (
    AGE_KEY, age_choices, age_groups, preferred_variable, resolve_variable, variable_choices,
)


STATIC_MESSAGE = "This variable does not change over time: see the map."


def create_app(config):
    default_output = {flag for flags in OUTPUT_FLAGS.values() for flag, _, on in flags if on}
    initial_output = set(config.output) if config.output is not None else set(GUI_OUTPUT)
    missing = set(default_sliders()) - set(default_params())
    if missing:
        raise ConfigError(f"default_params.txt in the package has no value for the sliders {sorted(missing)}")

    app_ui = ui.page_sidebar(
        ui.sidebar(
            ui.div(
                ui.input_task_button("run", "Run", label_busy="Running…", class_="btn-primary flex-fill"),
                ui.input_action_button("cancel", "Cancel", class_="flex-fill", disabled=True),
                class_="d-flex gap-2",
            ),
            ui.input_text("run_name", "Run name (optional)", placeholder="e.g. kenya_e0_high"),
            ui.input_numeric(
                "nagent",
                with_tip("Number of agents", "Simulated people. More agents is slower but closer to the real population: "
                         "keep the mean humans per agent close to 1 for reliable results."),
                value=config.run["nagent"], min=1, step=100000,
            ),
            ui.div(ui.output_text("humans_per_agent"), class_="small text-muted mb-3"),
            ui.input_numeric(
                "seed", with_tip("Seed", "Starting point of the random numbers. The same seed and threads give the same results."),
                value=config.run["seed"], min=1, step=1,
            ),
            ui.input_switch(
                "seed_band", with_tip("Seed band", "Run several consecutive seeds with the same parameters, to see how much the results vary by chance."),
                value=False,
            ),
            ui.panel_conditional("input.seed_band", ui.input_numeric("n_seeds", "Number of seeds", value=5, min=2, step=1)),
            ui.input_select("previous_run", f"Previous runs in {config.runs_dir}", {}),
            ui.input_action_button("load", "Load run", class_="w-100"),
            ui.accordion(
                ui.accordion_panel(
                    "Parameters",
                    ui.input_action_button("reset", "Reset parameters", class_="mb-2 w-100"),
                    ui.output_ui("parameter_sliders"),
                ),
                ui.accordion_panel(
                    "Outputs",
                    ui.p("What the next run writes. Rainfall and temperature are always written.", class_="small"),
                    ui.accordion(*output_groups(initial_output), open=False, multiple=True),
                ),
                open=False,
                multiple=True,
            ),
            ui.input_action_button("close", "Close GUI", class_="btn-sm btn-outline-secondary w-100 mt-3"),
            width=320,
        ),
        ui.head_content(
            ui.tags.script(ui.HTML(plotly.offline.get_plotlyjs())),
            ui.tags.script(ui.HTML(PLAYER)),
            ui.tags.script(ui.HTML(PLOT_HANDLER)),
            ui.tags.script(ui.HTML(CLOSED_HANDLER)),
            ui.tags.style("#shiny-disconnected-overlay { display: none; }"),
            ui.tags.style(PARAMETER_STYLE),
            ui.tags.script(ui.HTML(SLIDER_FORMAT)),
            ui.tags.script(ui.HTML(BROWSER_HANDLER)),
        ),
        ui.output_ui("status"),
        ui.navset_tab(
            ui.nav_panel("Setup", setup_tab(config)),
            ui.nav_panel(
                "Runs",
                ui.card(
                    ui.layout_columns(
                        ui.div(ui.input_select("variable", "Variable", {}), ui.output_ui("age_choice")),
                        ui.div(ui.output_ui("seed_choice"), ui.input_switch("terrain", with_tip("Terrain", "Shaded relief under the map. Downloaded the first time it is used."), value=False), ui.output_ui("terrain_status")),
                        ui.div(
                            ui.input_slider("day", ui.TagList("Day ", ui.tags.span(id="day_date", class_="ms-1")), min=1, max=max(config.run["nstep"], 2), value=1, step=1, width="100%"),
                            player_controls(),
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
            ui.nav_panel("Docs", docs()),
            id="tab",
            selected="Setup",
        ),
        funders(),
        title=ui.output_ui("header"),
    )

    def server(input, output, session):
        current = reactive.value(None)
        selected_cells = reactive.value([])
        runs_changed = reactive.value(0)
        range_overrides = reactive.value({})  # {(menu entry, scale): (minimum, maximum)} set by hand
        state = RunState()
        setup = reactive.value(config)  # The applied settings of the Setup panel
        setup_problem = reactive.value(None)
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

        @render.ui
        def parameter_sliders():
            sliders = slider_setup()
            return ui.TagList(
                parameter_legend(sliders["const"]),
                ui.accordion(*slider_groups(sliders["sliders"], sliders["defaults"], sliders["sources"]), open=False, multiple=True),
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
            nagent, seed = input.nagent(), input.seed()
            n_seeds = input.n_seeds() if input.seed_band() else 1
            if not all(isinstance(value, int) and value >= 1 for value in (nagent, seed, n_seeds)):
                ui.notification_show("Agents, seed and number of seeds must be positive integers.", type="error")
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
                    "A run is in progress. Closing the GUI will cancel it.",
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
                label=f"Previous runs in {setup().runs_dir}",
                choices={folder: run_label(folder, manifest) for folder, manifest in available_runs().items()},
            )

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
            adopt(restored, keep_outcome=True)
            show(outcome)
            ui.update_numeric("nagent", value=outcome.nagent)
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
            grid_changed = (old.inputs["pop_file"], old.inputs["area_file"]) != (new.inputs["pop_file"], new.inputs["area_file"])
            setup.set(new)
            save_setup(replace(new, run={**new.run, "nagent": input.nagent() or new.run["nagent"], "seed": input.seed() or new.run["seed"]}))
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
            ui.update_numeric("setup_nstep", value=config.run["nstep"])
            ui.update_switch("setup_spin_up", value=config.run["spin_up"] == 1)
            ui.update_numeric("setup_threads", value=config.run["threads"])
            ui.update_switch("setup_counterfactual", value=config.inputs.get("counterfactual") == 1)

        @reactive.effect
        @reactive.event(input.apply_setup)
        def apply_setup():
            if run_task.status() == "running":
                ui.notification_show("Wait for the run to finish, or cancel it, before changing the setup.", type="warning")
                return
            run = {
                "disID": int(input.setup_disID()),
                "mob": setup().run["mob"],
                "nstep": input.setup_nstep(),
                "spin_up": 1 if input.setup_spin_up() else 0,
                "nagent": input.nagent(),
                "seed": input.seed(),
                "threads": input.setup_threads(),
            }
            files = {key: input[f"setup_{key}"]() for key, _, _ in (*REQUIRED_FILES, *OPTIONAL_FILES)}
            files["counterfactual"] = 1 if input.setup_counterfactual() else 0
            try:
                new = from_fields(setup().mobile, input.setup_project(), input.setup_runs_dir(), run, files)
            except ConfigError as error:
                setup_problem.set(setup_problems(error))
                return
            adopt(new)
            ui.notification_show("Setup applied.", type="message", duration=3)
            ui.update_navs("tab", selected="Runs")

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

        @render.text
        def humans_per_agent():
            nagent = input.nagent()
            if not nagent or nagent < 1:
                return ""
            return f"Mean humans per agent: {grid()['people'] / nagent:.2f} ({grid()['people']:,.0f} people)"

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
            if outcome is None:
                return no_run_yet()
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
        preview_cells = reactive.value([])
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
                colour_map=input.preview_colour_map(), log=input.preview_scale() == "log",
            )
            # The zoom is kept while the grid is the same
            figure.update_layout(meta={"date": figure.layout.meta["date"], "view": str(preview_extent())})
            await send_figure(session, "preview_map", figure)

        @reactive.effect
        @reactive.event(input.preview_cell)
        def select_preview_cell():
            with reactive.isolate():
                if preview_map_data() is None:
                    return
                cell = input.preview_cell()
                preview_cells.set(next_cells(preview_cells(), cell["lon"], cell["lat"]))

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
                await send_figure(session, "preview_cell_plot", message_figure("Click a cell on the map to see its daily values, and a second one to compare."))
                return
            figure = cell_figure(
                data, preview_description(), preview_cells(), min(input.preview_day(), data.sizes["time"]),
                from_zero=key == "rain_file",
            )
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
