"""The Sensitivity analysis card of the Parameters tab: which parameters to sample and how, the Sobol settings,
the runs, with their progress, Cancel and Resume, and the analysis of their outputs."""

import asyncio
import math
import os
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from shiny import reactive, render, ui

from .basemap import load_basemap
from .config import ConfigError
from .layout import HA_BELOW_ONE, OUTPUT_FLAGS, SALIB_URL, UNIT_LABELS, parameter_label, sections, with_tip
from .outcome import run_name_problem
from .plots import climate_figure, index_map_figure, indices_figure, monthly_figure, second_order_figure, send_figure
from .sensitivity import DISTRIBUTIONS, SampledParameter, design_problems, run_count_formula
from .sensitivity_results import (
    MONTHS, OPEN_BAND_MIDDLE, UNDER, age_note, analysable_variables, analyse_study, cell_dataset, first_run, indices_table,
    metric_from_entry, monthly_table, output_info,
)
from .sensitivity_runs import (
    OLD_STUDY, StudyState, create_study, describe_parameter, list_studies, read_study, run_study, studies_dir, study_label,
    study_parameters,
)

N_CHOICES = {str(2**k): f"{2**k:,}" for k in range(1, 15)}
DEFAULT_N = "256"
FIELDS = ("dist", "low", "high", "mean", "sd", "lnmean", "lnsd")

SA_STYLE = """
.sa-row { display: flex; align-items: center; gap: 0.5rem; min-height: 2.6rem; }
.sa-row .shiny-input-container { margin-bottom: 0; width: auto; }
.sa-row .sa-name { width: 11rem; flex: none; }
.sa-row .sa-name .form-check { margin-bottom: 0; }
.sa-row .sa-fields { display: flex; gap: 0.5rem; align-items: center; }
.sa-row select { width: 12rem; }
.sa-row input[type=number] { width: 7rem; }
.sa-head { display: flex; gap: 0.5rem; font-size: 0.8rem; color: var(--bs-secondary-color); margin-left: 11.5rem; }
.sa-head span { width: 7rem; } .sa-head span.sa-dist { width: 12rem; }
/* Stochastic analyses stand out: amber, as the seed band of single runs stands apart from one run */
.sa-stochastic { border-left: 4px solid #d97706; background: var(--bs-warning-bg-subtle); padding: 0.4rem 0.6rem; border-radius: 4px; }
.sa-stochastic .form-check-input:checked { background-color: #d97706; border-color: #d97706; }
.sa-count { font-family: var(--bs-font-monospace); }
.sa-count.stochastic { color: var(--bs-warning-text-emphasis); font-weight: 600; }
.sa-how summary { cursor: pointer; }
.sa-how ul { padding-left: 1.2rem; margin: 0.3rem 0; }
#sa_months .shiny-options-group { display: grid; grid-template-columns: repeat(3, 1fr); column-gap: 0.4rem; }
#sa_months .form-check { white-space: nowrap; margin-bottom: 0; }
.sa-table td, .sa-table th { padding: 0.15rem 0.6rem; text-align: right; }
.sa-table td:first-child, .sa-table th:first-child { text-align: left; }
"""
TIME_CHOICES = {"mean": "Mean", "sum": "Sum", "max": "Maximum"}
SPACE_CHOICES = {
    "mean": "Mean over the populated cells", "sum": "Sum over the populated cells", "none": "None: a map of the indices",
    "months": "None, month by month: the indices across the cells",
}
AGE_SPACE_CHOICES = {"ages": "None, age band by age band: the indices across the cells"}  # For an output by age band


def _fields_header():
    return ui.div(
        ui.span("Distribution", class_="sa-dist"), ui.span("Minimum"), ui.span("Maximum"), ui.span("Mean (or of ln x)"), ui.span("Sd (or of ln x)"),
        class_="sa-head",
    )


def _number(id_, value):
    return ui.input_numeric(id_, None, value=None if value is None else float(f"{value:.4g}"), step="any")


def _parameter_row(name, spec, value):
    """A checkbox to sample the parameter and, once ticked, its distribution: bounds always, mean and sd
    for normal, and those of ln x for log-normal."""
    low, high = spec["min"], spec["max"]
    positive = value > 0 and low > 0
    use = f"input.sa_use_{name}"
    dist = f"input.sa_dist_{name}"
    return ui.div(
        ui.div(ui.input_checkbox(f"sa_use_{name}", parameter_label(spec.get("label", name) + UNIT_LABELS.get(spec.get("display"), ""), spec),
                                 value=False), class_="sa-name"),
        ui.panel_conditional(
            use,
            ui.div(
                ui.input_select(f"sa_dist_{name}", None, {key: label for key, label in DISTRIBUTIONS.items()}, selected="uniform"),
                _number(f"sa_low_{name}", low),
                _number(f"sa_high_{name}", high),
                ui.panel_conditional(f"{dist} === 'normal'", ui.div(
                    _number(f"sa_mean_{name}", min(max(value, low), high)), _number(f"sa_sd_{name}", (high - low) / 4), class_="sa-fields")),
                ui.panel_conditional(f"{dist} === 'lognormal'", ui.div(
                    _number(f"sa_lnmean_{name}", math.log(value) if positive else None),
                    _number(f"sa_lnsd_{name}", (math.log(high) - math.log(low)) / 4 if low > 0 else 1.0), class_="sa-fields")),
                class_="sa-fields",
            ),
        ),
        ui.panel_conditional(f"!{use}", ui.span(f"Not sampled: {value:.4g}, as on its slider", class_="small text-muted")),
        class_="sa-row",
    )


AGE_OUTPUTS_NEEDED = ("For the sensitivity by age, the runs must write at least Agents (Na) and one more output under Human, "
                      "by age in the Outputs card, e.g. New symptomatic cases: tick them before running the analysis.")


def _how_age_calculated():
    """How the indices by age band and the age profile are computed: folded away until opened."""
    strong = ui.tags.strong
    return ui.tags.details(
        ui.tags.summary("How the age sensitivities are calculated"),
        ui.tags.ul(
            ui.tags.li(strong("Outputs needed. "), AGE_OUTPUTS_NEEDED),
            ui.tags.li(strong("Age bands. "), "The model writes the outputs by age band as a rate per person of each band (e.g. "
                       "the new symptomatic cases of the band over its agents), in bands of 0, 1, 2, 3, 4, 5, 6, 7, 8–9, 10–11, "
                       "12–14, 15–19, 20–29, 30–44, 45–59, 60–79 and 80 years and over."),
            ui.tags.li(strong("Age band by age band. "), "The rate of each band is reduced over the days as chosen, and the indices "
                       "computed in each cell for each band. A box spans the 10th to the 90th percentile of the indices across "
                       "the cells, its middle part the 25th to the 75th, with the median; the line is the index of the mean over "
                       "the cells, with its 95% interval, as month by month."),
            ui.tags.li(strong("Age profile. "), f"The cases of a band are its rate per person times its agents, day by day. The "
                       f"share of the cases under {UNDER} years old, and their mean age, are those of the cases summed (or "
                       f"averaged) over the days and cells chosen, not averages of shares. A band counts at the middle of its "
                       f"years (0.5 for age 0, 9 for 8–9), the last one at {OPEN_BAND_MIDDLE:g}. These are numbers per run, "
                       "analysed as any other: one number, a map, or month by month."),
            ui.tags.li(strong("Agents and people. "), "The agents of a cell stand for the same number of people (HA), so shares of "
                       "agents are shares of people."),
        ),
        class_="sa-how small text-muted mt-2",
    )


def _how_calculated():
    """What the indices are and how they are estimated: folded away until opened."""
    strong = ui.tags.strong
    return ui.tags.details(
        ui.tags.summary("How the indices are calculated"),
        ui.tags.ul(
            ui.tags.li(strong("The number analysed. "), "Each run gives one number: the variable on the chosen days and months, "
                       "summed, averaged or at its maximum, then averaged or summed over the populated cells. Without the cells "
                       "reduced, one number per cell, analysed cell by cell."),
            ui.tags.li(strong("S1"), " (first order): the share of the variance of that number over all the runs that one "
                       "parameter explains alone, i.e. how much the variance would drop, on average, if that parameter were known. ",
                       strong("ST"), " (total): the share it explains with all its interactions, i.e. the variance that would "
                       "remain, on average, if every other parameter were known. ", strong("ST − S1"), ": through interactions only. ",
                       strong("S2"), ": what a pair explains together, beyond each alone. The S1 add up to 1 only if no parameter "
                       "interacts with another."),
            ui.tags.li(strong("Estimates. "), ui.a("SALib", href=SALIB_URL, target="_blank"), "'s estimators (Saltelli 2010 for S1 and S2, Jansen 1999 for ST) on the "
                       "N(2D+2) or N(D+2) runs of the Sobol design. Whiskers are 95% confidence intervals from 100 bootstrap "
                       "resamples of the N samples. A small N gives wide intervals, and values a little below 0 or above 1: "
                       "a larger N narrows them."),
            ui.tags.li(strong("Stochastic. "), "The bars are the indices of the mean over the seeds of each sample: how the "
                       "parameters change the expected output. The dots are each seed analysed alone: their spread is how much "
                       "chance moves the indices. The share from chance is the variance across the seeds of the same sample, "
                       "averaged over the samples, over the variance of all the runs."),
            ui.tags.li(strong("Month by month. "), "The days of each month are reduced apart, and the indices computed in each "
                       "cell for each month. A box spans the 10th to the 90th percentile of the indices across the cells, its "
                       "middle part the 25th to the 75th, with the median; the line is the index of the mean over the cells, "
                       "with its 95% interval."),
            ui.tags.li(strong("Maps. "), "The same in each cell, without confidence intervals (a bootstrap for every cell would "
                       "take too long). A cell whose number is the same in every run has no index. The scatter plots compare the "
                       "index of each cell with its mean rainfall and temperature over the same days, as written in the runs, "
                       "and with its population density, from the population file of the analysis."),
        ),
        class_="sa-how small text-muted mt-2",
    )


def _results_section():
    """What to analyse in the runs of the analysis chosen under Earlier analyses, and the results."""
    return ui.TagList(
        ui.h6("Analyse the runs", class_="mt-3"),
        ui.p("Of the analysis chosen under Earlier analyses. The first time, every run is read, which for thousands of runs "
             "takes minutes; what is read is kept in the folder of the analysis, so that it is quick to analyse again.",
             class_="small text-muted mb-1"),
        ui.layout_columns(
            ui.div(
                ui.input_select("sa_variable", "Variable", {}),
                ui.output_ui("sa_age_note"),
                ui.input_date_range("sa_window", with_tip("Days", "From the first to the last day, both included."), separator=" to "),
            ),
            ui.input_checkbox_group("sa_months", with_tip("Months", "Only the days of these months, e.g. those of the wet season."),
                                    {str(m): name for m, name in enumerate(MONTHS, start=1)}, selected=[str(m) for m in range(1, 13)]),
            ui.div(
                ui.input_radio_buttons("sa_time", "Over the days", TIME_CHOICES, selected="mean", inline=True),
                ui.input_radio_buttons("sa_space", "Over the cells", SPACE_CHOICES, selected="mean"),
            ),
            ui.div(
                ui.div(
                    ui.input_task_button("sa_analyse", "Analyse", label_busy="Analysing…", class_="btn-primary flex-fill"),
                    ui.input_action_button("sa_analyse_cancel", "Cancel", class_="flex-fill", disabled=True),
                    class_="d-flex gap-2",
                ),
                ui.output_ui("sa_reading"),
            ),
            col_widths=(3, 3, 3, 3),
        ),
        _how_calculated(),
        _how_age_calculated(),
        ui.output_ui("sa_summary"),
        ui.output_ui("sa_map_tabs"),
        ui.navset_hidden(
            ui.nav_panel("none", value="none"),
            ui.nav_panel(
                "scalar",
                ui.div(id="sa_indices", style="height: 440px;"),
                ui.navset_hidden(
                    ui.nav_panel("no", value="no"), ui.nav_panel("yes", ui.div(id="sa_pairs", style="height: 380px;"), value="yes"),
                    id="sa_pairs_view", selected="no",
                ),
                ui.output_ui("sa_table"),
                ui.download_button("sa_download_csv", "Download the indices (CSV)", class_="btn-sm mt-2"),
                value="scalar",
            ),
            ui.nav_panel(
                "cells",
                ui.div(id="sa_map", style="height: 560px;"),
                ui.div(id="sa_climate", style="height: 380px;"),
                ui.download_button("sa_download_nc", "Download the maps (netCDF)", class_="btn-sm mt-2"),
                value="cells",
            ),
            ui.nav_panel(
                "months",
                ui.div(id="sa_monthly", style="height: 460px;"),
                ui.download_button("sa_download_months", "Download the indices by month (CSV)", class_="btn-sm mt-2"),
                value="months",
            ),
            ui.nav_panel(
                "ages",
                ui.div(id="sa_ages", style="height: 460px;"),
                ui.download_button("sa_download_ages", "Download the indices by age band (CSV)", class_="btn-sm mt-2"),
                value="ages",
            ),
            id="sa_view", selected="none",
        ),
    )


def sensitivity_card():
    return ui.card(
        ui.tags.style(SA_STYLE),
        ui.card_header("Sensitivity analysis (Sobol)"),
        ui.p(
            "Runs the model for many combinations of the parameters you tick, drawn from their distributions, with the setup ",
            "applied in tab 1, the HA (and so the agents) and seed of the sidebar, and every other parameter at its slider value above. ",
            "Sobol indices then say how much of the variance of an output each parameter explains, alone (S1) or with the others (ST).",
            class_="small text-muted mb-1",
        ),
        ui.h6("Parameters to sample", class_="mt-2"),
        ui.output_ui("sa_parameters"),
        ui.layout_columns(
            ui.div(
                ui.h6("Sobol"),
                ui.input_select("sa_n", with_tip("Base samples N", "A power of 2: Sobol sequences are balanced only then. "
                                "More samples give narrower confidence intervals."), N_CHOICES, selected=DEFAULT_N),
                ui.input_switch("sa_second_order", with_tip("Second-order indices", "S2: what each pair of parameters explains "
                                "together. Each sample then needs 2D + 2 runs instead of D + 2."), value=True),
                ui.div("Morris screening, which ranks many parameters with far fewer runs: a future development.",
                       class_="small text-muted border rounded p-2"),
            ),
            ui.div(
                ui.h6("Runs"),
                ui.div(
                    ui.input_switch("sa_stochastic", with_tip("Stochastic", "Repeat the whole analysis for several seeds, from the "
                                    "sidebar seed up, with the same samples. The indices of each seed show how much chance changes them."),
                                    value=False),
                    ui.panel_conditional("input.sa_stochastic", ui.input_numeric("sa_n_seeds", "Number of seeds", value=5, min=2, step=1)),
                    class_="sa-stochastic mb-2",
                ),
                ui.input_numeric("sa_parallel", with_tip("Runs at the same time", "Each uses the threads of the setup. Builds take "
                                 "turns; the built models run side by side."), value=1, min=1, step=1),
                ui.input_text("sa_name", "Analysis name (optional)", placeholder="e.g. wet_season_hbr"),
            ),
            ui.div(
                ui.h6("Number of runs"),
                ui.output_ui("sa_count"),
                ui.output_ui("sa_outputs"),
                ui.div(
                    ui.input_task_button("sa_run", "Run analysis", label_busy="Running…", class_="btn-primary flex-fill"),
                    ui.input_action_button("sa_cancel", "Cancel", class_="flex-fill", disabled=True),
                    class_="d-flex gap-2 mt-2",
                ),
            ),
            col_widths=(4, 4, 4),
            class_="mt-3",
        ),
        ui.output_ui("sa_status"),
        ui.h6("Earlier analyses", class_="mt-3"),
        ui.p("The runs of an analysis are kept in its folder: a cancelled analysis resumes where it stopped, and the outputs of "
             "a finished one can be analysed again in other ways (another variable, time window or reduction) without running again.",
             class_="small text-muted mb-1"),
        ui.layout_columns(
            ui.input_select("sa_previous", None, {}, width="100%"),
            ui.input_action_button("sa_resume", "Resume", class_="w-100"),
            col_widths=(10, 2),
        ),
        ui.output_ui("sa_previous_info"),
        _results_section(),
        class_="mt-3",
    )


def _value(input, id_):
    value = input[id_]()
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _percent(share):
    """e.g. 14.6%, or 0.031% for a small share, which would otherwise read 0.0%."""
    return f"{100 * share:.1f}%" if share >= 0.01 else f"{100 * share:.2g}%"


def _clock(seconds):
    seconds = int(round(seconds))
    return f"{seconds // 3600}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


def sensitivity_server(input, output, session, setup, slider_setup, overrides, selected_output, single_run_running, agents, ha):
    """The server side of the card. Returns running() and cancel() for the rest of the app."""
    state = StudyState()
    studies_changed = reactive.value(0)
    last = reactive.value(None)  # The record of the last analysis run in this session, or an error
    running_folder = reactive.value(None)
    to_select = reactive.value(None)  # A new analysis, to choose under Earlier analyses

    @output(suspend_when_hidden=False)
    @render.ui
    def sa_parameters():
        sliders = slider_setup()
        groups = []
        for group, found in sections(sliders["sliders"]).items():
            rows = []
            for section, names in found.items():
                if section != group:
                    rows.append(ui.h6(section, class_="mt-2 mb-1 small fw-semibold"))
                rows += [_parameter_row(name, sliders["sliders"][name], sliders["defaults"][name]) for name in names]
            groups.append(ui.accordion_panel(group, _fields_header(), *rows))
        return ui.accordion(*groups, open=False, multiple=True)

    @reactive.effect
    def default_parallel():
        """As many runs at a time as fit in the cores with the threads of the setup."""
        ui.update_numeric("sa_parallel", value=max(1, (os.cpu_count() or 1) // setup().run["threads"]))

    @reactive.calc
    def chosen():
        """The ticked parameters, as typed."""
        parameters = []
        for name in slider_setup()["sliders"]:
            if f"sa_use_{name}" not in input or not input[f"sa_use_{name}"]():
                continue
            distribution = input[f"sa_dist_{name}"]()
            mean, sd = {"normal": ("mean", "sd"), "lognormal": ("lnmean", "lnsd")}.get(distribution, (None, None))
            parameters.append(SampledParameter(
                name, distribution, _value(input, f"sa_low_{name}"), _value(input, f"sa_high_{name}"),
                _value(input, f"sa_{mean}_{name}") if mean else None, _value(input, f"sa_{sd}_{name}") if sd else None,
            ))
        return parameters

    def seeds_wanted():
        n_seeds = input.sa_n_seeds() if input.sa_stochastic() else 1
        return n_seeds if isinstance(n_seeds, int) and n_seeds >= 1 else None

    @render.ui
    def sa_count():
        parameters, n = chosen(), int(input.sa_n())
        if not parameters:
            return ui.p("Tick at least two parameters to sample.", class_="small text-muted")
        seeds = seeds_wanted()
        problems = design_problems(parameters, n, input.sa_second_order())
        if seeds is None:
            problems.append("The number of seeds must be a positive whole number.")
        if problems:
            return ui.div(*[ui.p(problem, class_="small text-danger mb-1") for problem in problems])
        stochastic = seeds > 1
        parallel = input.sa_parallel() or 1
        threads = setup().run["threads"]
        cores = os.cpu_count() or 1
        if parallel * threads > cores:
            use = ui.p(f"{parallel} at a time × {threads} threads = {parallel * threads} threads, more than the {cores} cores of this "
                       f"computer: the runs slow each other down. Use at most {max(1, cores // threads)} at a time.",
                       class_="small text-warning-emphasis mb-1")
        else:
            use = ui.p(f"{parallel} at a time × {threads} threads = {parallel * threads} of the {cores} cores of this computer.",
                       class_="small text-muted mb-1")
        return ui.TagList(
            ui.p(run_count_formula(n, parameters, input.sa_second_order(), seeds), class_="sa-count mb-1" + (" stochastic" if stochastic else "")),
            use,
        )

    @render.ui
    def sa_outputs():
        labels = {flag: label for flags in OUTPUT_FLAGS.values() for flag, label, _ in flags}
        chosen_outputs = [labels[flag] for flag in selected_output()]
        return ui.p(f"Each run writes the outputs chosen in the Outputs card ({', '.join(chosen_outputs) or 'none'}): "
                    "only these can be analysed afterwards. " + AGE_OUTPUTS_NEEDED, class_="small text-muted mb-0")

    @ui.bind_task_button(button_id="sa_run")
    @reactive.extended_task
    async def sa_task(folder, parallel):
        return await asyncio.to_thread(run_study, folder, state, parallel)

    def running():
        return sa_task.status() == "running"

    def start(folder):
        parallel = input.sa_parallel()
        if not isinstance(parallel, int) or parallel < 1:
            ui.notification_show("Runs at the same time must be a positive whole number.", type="error")
            return
        last.set(None)
        running_folder.set(str(folder))
        sa_task.invoke(str(folder), parallel)

    @reactive.effect
    @reactive.event(input.sa_run)
    def start_analysis():
        if single_run_running():
            ui.notification_show("A run is in progress: wait for it, or cancel it, before an analysis.", type="warning")
            return
        parameters, n, seeds = chosen(), int(input.sa_n()), seeds_wanted()
        problems = design_problems(parameters, n, input.sa_second_order())
        nagent, seed = agents(), input.seed()
        if not all(isinstance(value, int) and value >= 1 for value in (nagent, seed)) or seeds is None:
            problems.append("HA must be positive, and the seed and number of seeds positive whole numbers.")
        elif ha() < 1:
            # More agents than people: the model stops at once, so every run would fail
            problems.append(HA_BELOW_ONE)
        name = input.sa_name().strip()
        folder = studies_dir(setup().runs_dir)
        if name and (folder / name).exists():
            problems.append(f"An analysis named {name} already exists in {folder}: choose another name.")
        elif name:
            problems += [run_name_problem(name, folder)] if run_name_problem(name, folder) else []
        if problems:
            ui.notification_show(" ".join(problems), type="error")
            return
        sampled = {parameter.name for parameter in parameters}
        fixed = {key: value for key, value in {**setup().params, **overrides()}.items() if key not in sampled}
        try:
            config = replace(setup(), params=fixed, output=selected_output()).with_run(nagent=nagent, seed=seed)
            study = create_study(config, parameters, n, input.sa_second_order(), [seed + i for i in range(seeds)],
                                 name or None, sample_seed=seed)
        except (ConfigError, ValueError, OSError) as error:
            ui.notification_show(f"The analysis cannot start: {error}", type="error")
            return
        ui.update_text("sa_name", value="")
        to_select.set(str(study))
        studies_changed.set(studies_changed() + 1)
        start(study)

    @reactive.effect
    @reactive.event(input.sa_resume)
    def resume_analysis():
        folder = input.sa_previous()
        if not folder:
            return
        if running() or single_run_running():
            ui.notification_show("Wait for the run or analysis in progress, or cancel it, before resuming.", type="warning")
            return
        record = read_study(folder)
        if record["status"] == "finished":
            ui.notification_show("This analysis has finished: every run is done.", type="message")
            return
        if "const" in record["run_inputs"]:
            ui.notification_show(OLD_STUDY, type="error")
            return
        start(folder)

    @reactive.effect
    def enable_buttons():
        ui.update_action_button("sa_cancel", disabled=not running())
        ui.update_action_button("sa_resume", disabled=running())

    @reactive.effect
    @reactive.event(input.sa_cancel)
    def cancel_analysis():
        state.cancel()

    @reactive.effect
    def collect():
        status = sa_task.status()
        if status in ("success", "error"):
            with reactive.isolate():
                last.set(sa_task.result() if status == "success" else "error")
                studies_changed.set(studies_changed() + 1)

    @render.ui
    def sa_status():
        if running():
            reactive.invalidate_later(1)
            done, total, failed, active, elapsed, left, message = state.snapshot()
            if message == "Starting":
                return ui.card(ui.p("Starting the analysis…", class_="mb-0"), class_="mt-3")
            text = f"Runs: {done:,} of {total:,} done, {active} running now"
            text += f", {failed:,} failed" if failed else ""
            text += f". Elapsed {_clock(elapsed)}" + (f", about {_clock(left)} left." if left is not None else ".")
            if state.cancelled:
                text = "Cancelling: stopping the runs in progress…"
            bar = ui.div(class_="progress-bar", style=f"width: {100 * done / max(total, 1):.1f}%;")
            return ui.card(ui.p(text, class_="mb-1"), ui.div(bar, class_="progress"), class_="mt-3")
        record = last()
        if record is None:
            return None
        if record == "error":
            return ui.card(ui.p("The analysis stopped with an error. The terminal you started the GUI from shows why."),
                           class_="border-danger mt-3")
        runs = f"{record['finished']:,} of {record['runs']:,} runs done"
        if record["status"] == "finished":
            return ui.p(f"Analysis finished: {runs}.", class_="mt-3 mb-0")
        if record["status"] == "stopped":
            return ui.card(
                ui.p(f"Analysis stopped: its first {record['failed']} runs all failed twice, so the others would fail too. "
                     "The end of the log of one of them:", class_="mb-1"),
                ui.tags.pre(record.get("failure") or "", class_="small mb-1"),
                ui.p("Fix the cause and press Resume: the runs are tried again.", class_="mb-0"),
                class_="border-danger mt-3",
            )
        if record["status"] == "cancelled":
            return ui.p(f"Analysis cancelled: {runs}. Choose it under Earlier analyses and press Resume to go on.", class_="mt-3 mb-0")
        return ui.card(ui.p(f"{record['failed']:,} runs failed twice ({runs}): their run.log, in the runs folder of the analysis, "
                            "says why. Resume tries them again."), class_="border-danger mt-3")

    @reactive.effect
    def refresh_studies():
        studies_changed()
        studies = list_studies(setup().runs_dir)
        with reactive.isolate():
            selected = to_select() or (input.sa_previous() if input.sa_previous() in studies else None)
            to_select.set(None)
        ui.update_select("sa_previous", choices={folder: study_label(folder, record) for folder, record in studies.items()},
                         selected=selected)

    @render.ui
    def sa_previous_info():
        folder = input.sa_previous()
        if not folder:
            return ui.p(f"None yet in {studies_dir(setup().runs_dir)}", class_="small text-muted")
        try:
            record = read_study(folder)
        except (OSError, ValueError):
            return None
        lines = [describe_parameter(parameter) for parameter in study_parameters(record)]
        return ui.div(ui.tags.ul(*[ui.tags.li(line) for line in lines], class_="mb-1"),
                      ui.p(f"Folder: {folder}", class_="mb-0"), class_="small text-muted")

    # The analysis of the runs: what is read and computed, and its figures
    reading = StudyState()
    result = reactive.value(None)  # What Analyse gave: the indices, or {"error": text}
    study_info = reactive.value(None)  # Variables, days and grid of the outputs of the analysis chosen

    @reactive.effect
    def chosen_study():
        studies_changed()
        folder = input.sa_previous()
        result.set(None)
        info = None
        if folder:
            try:
                run_dir = first_run(folder, read_study(folder))
                info = output_info(run_dir) if run_dir else None
            except (OSError, ValueError, KeyError):
                info = None
        study_info.set(info)
        if info is None:
            ui.update_select("sa_variable", choices={})
            return
        choices = analysable_variables(info["variables"])
        names = [name for group in choices.values() for name in group]
        with reactive.isolate():
            current = input.sa_variable()
        selected = current if current in names else "EIR" if "EIR" in names else names[0] if names else None
        ui.update_select("sa_variable", choices=choices, selected=selected)
        first, last_day = str(info["time"][0])[:10], str(info["time"][-1])[:10]
        ui.update_date_range("sa_window", start=first, end=last_day, min=first, max=last_day)

    @render.ui
    def sa_age_note():
        info = study_info()
        note = age_note(info["variables"]) if info is not None else None
        return ui.p(note, class_="small text-muted mb-2") if note else None

    @reactive.effect
    def space_choices():
        """Age band by age band for an output by age band, and only that; the other choices for the rest."""
        by_age = (input.sa_variable() or "").startswith("age:")
        choices = AGE_SPACE_CHOICES if by_age else SPACE_CHOICES
        with reactive.isolate():
            current = input.sa_space()
        ui.update_radio_buttons("sa_space", choices=choices, selected=current if current in choices else next(iter(choices)))

    @ui.bind_task_button(button_id="sa_analyse")
    @reactive.extended_task
    async def analysis_task(folder, metric):
        def work():
            try:
                outcome = analyse_study(folder, read_study(folder), metric, reading)
            except InterruptedError:
                return {"error": "Analysis cancelled. What was read for whole seeds is kept."}
            except (ValueError, OSError, KeyError) as error:
                return {"error": f"The runs cannot be analysed: {error}"}
            if outcome["kind"] == "cells":
                outcome["basemap"] = load_basemap(outcome["lon"], outcome["lat"])
            return outcome

        return await asyncio.to_thread(work)

    @reactive.effect
    @reactive.event(input.sa_analyse)
    def analyse_runs():
        folder, info = input.sa_previous(), study_info()
        if not folder or info is None:
            ui.notification_show("Choose an analysis with finished runs under Earlier analyses.", type="warning")
            return
        if running() and running_folder() == folder:
            ui.notification_show("The runs of this analysis are in progress: analyse it when they finish, or cancel them.", type="warning")
            return
        months = tuple(sorted(int(month) for month in input.sa_months()))
        if not months:
            ui.notification_show("Tick at least one month.", type="error")
            return
        first, last_day = str(info["time"][0])[:10], str(info["time"][-1])[:10]
        start, end = (str(day) if day else None for day in (input.sa_window() or (None, None)))
        by_month = input.sa_space() == "months"
        metric = metric_from_entry(
            input.sa_variable(), input.sa_time(), "none" if input.sa_space() in ("months", "ages") else input.sa_space(),
            None if start in (None, first) else start, None if end in (None, last_day) else end, None if len(months) == 12 else months,
            by_month,
        )
        problems = metric.problems()
        if problems:
            ui.notification_show(" ".join(problems), type="error")
            return
        result.set(None)
        reading.begin(0, 0)  # Not the counts of the reading before
        analysis_task.invoke(folder, metric)

    @reactive.effect
    def enable_analysis_cancel():
        ui.update_action_button("sa_analyse_cancel", disabled=analysis_task.status() != "running")

    @reactive.effect
    @reactive.event(input.sa_analyse_cancel)
    def cancel_reading():
        reading.cancel()

    @reactive.effect
    def collect_analysis():
        status = analysis_task.status()
        if status == "success":
            result.set(analysis_task.result())
        elif status == "error":
            result.set({"error": "The analysis stopped with an error. The terminal you started the GUI from shows why."})

    @render.ui
    def sa_reading():
        if analysis_task.status() != "running":
            return None
        reactive.invalidate_later(1)
        done, total, _, _, elapsed, left, message = reading.snapshot()
        if message != "Reading" or total == 0:
            return ui.p("Starting…", class_="small text-muted mt-2 mb-0")
        if reading.cancelled:
            return ui.p("Cancelling…", class_="small text-muted mt-2 mb-0")
        if done == total:
            return ui.p("Computing the indices…", class_="small text-muted mt-2 mb-0")
        text = f"Reading the runs: {done:,} of {total:,}" + (f", about {_clock(left)} left" if left is not None else "")
        bar = ui.div(class_="progress-bar", style=f"width: {100 * done / total:.1f}%;")
        return ui.div(ui.p(text, class_="small text-muted mb-1"), ui.div(bar, class_="progress", style="height: 0.4rem;"), class_="mt-2")

    @render.ui
    def sa_summary():
        outcome = result()
        if outcome is None:
            return None
        if "error" in outcome:
            return ui.p(outcome["error"], class_="text-danger mt-2 mb-0")
        seeds, every = outcome["seeds"], outcome["all_seeds"]
        lines = [ui.tags.strong(outcome["description"][:1].upper() + outcome["description"][1:])]
        if len(seeds) > 1:
            lines.append(f"Indices of the mean over seeds {', '.join(map(str, seeds))}, and of each seed alone.")
        if len(seeds) < len(every):
            left = [seed for seed in every if seed not in seeds]
            lines.append(ui.span(f"Seeds {', '.join(map(str, left))} have runs left and are not included: resume the analysis "
                                 "to add them.", class_="text-warning-emphasis"))
        if "chance" in outcome:
            chance = outcome["chance"]
            if outcome["kind"] == "scalar":
                lines.append(f"Chance (the seed) makes {_percent(chance)} of the variance of this number over all the runs.")
            else:
                lines.append(f"Chance (the seed) makes {_percent(np.nanmedian(chance))} of the variance of the number of a cell over "
                             f"all the runs in the median cell, from {_percent(np.nanquantile(chance, 0.1))} to "
                             f"{_percent(np.nanquantile(chance, 0.9))} in 80% of the cells: see its map.")
        if outcome["kind"] in ("months", "ages"):
            layers = f"{len(outcome['months'])} months" if outcome["kind"] == "months" else f"{len(outcome['ages'])} age bands"
            lines.append(f"{layers}. Boxes: the index of each cell, from the 10th to the 90th percentile across "
                         "the cells; line: the index of the mean over the cells.")
            if np.any(outcome["cells_used"] < len(outcome["cells"])):
                lines.append("Cells whose number is the same in every run have no index and are left out of the boxes: hover "
                             "over a box for how many it holds.")
        return ui.div(*[ui.p(line, class_="mb-1") for line in lines], class_="small mt-2")

    @reactive.effect
    async def show_result():
        outcome = result()
        kind = outcome.get("kind") if outcome and "error" not in outcome else None
        ui.update_navs("sa_view", selected=kind or "none")
        if kind == "scalar":
            ui.update_navs("sa_pairs_view", selected="yes" if outcome["second_order"] else "no")
            await send_figure(session, "sa_indices", indices_figure(outcome))
            if outcome["second_order"]:
                await send_figure(session, "sa_pairs", second_order_figure(outcome))

    @render.ui
    def sa_map_tabs():
        """A tab for each parameter and the index to show, for maps, month by month and age band by age band."""
        outcome = result()
        if not outcome or outcome.get("kind") not in ("cells", "months", "ages"):
            return None
        choices = {"ST": "ST", "S1": "S1"}
        if "range" in outcome:
            choices.update({"ST_range": "ST: range across seeds", "S1_range": "S1: range across seeds", "chance": "Share from chance"})
        with reactive.isolate():
            index = input.sa_map_index() if "sa_map_index" in input and input.sa_map_index() in choices else "ST"
            name = input.sa_map_param() if "sa_map_param" in input and input.sa_map_param() in outcome["parameters"] else None
        return ui.TagList(
            ui.navset_pill(*[ui.nav_panel(parameter, value=parameter) for parameter in outcome["parameters"]], id="sa_map_param",
                           selected=name),
            ui.input_radio_buttons("sa_map_index", None, choices, selected=index, inline=True),
        )

    @reactive.effect
    async def show_map():
        outcome = result()
        if not outcome or outcome.get("kind") not in ("cells", "months", "ages") or "sa_map_index" not in input:
            return
        name = input.sa_map_param() if "sa_map_param" in input else None
        key = input.sa_map_index()
        if name not in outcome["parameters"]:
            name = outcome["parameters"][0]
        if outcome["kind"] in ("months", "ages"):
            plot = "sa_monthly" if outcome["kind"] == "months" else "sa_ages"
            await send_figure(session, plot, monthly_figure(outcome, name, key if key in ("ST", "S1") else "ST"))
            return
        if key not in ("ST", "S1") and "range" not in outcome:
            key = "ST"
        await send_figure(session, "sa_map", index_map_figure(outcome, name, key, outcome.get("basemap")))
        await send_figure(session, "sa_climate", climate_figure(outcome, name, key))

    @render.ui
    def sa_table():
        outcome = result()
        if not outcome or outcome.get("kind") != "scalar":
            return None
        mean = outcome["mean"]
        head = ["Parameter", "S1 ± 95% CI", "ST ± 95% CI", "ST − S1"]
        if "each" in outcome:
            head += ["S1 across seeds", "ST across seeds"]
        rows = []
        for j in np.argsort(-np.nan_to_num(mean["ST"])):
            row = [outcome["parameters"][j], f"{mean['S1'][j]:.3f} ± {mean['S1_conf'][j]:.3f}",
                   f"{mean['ST'][j]:.3f} ± {mean['ST_conf'][j]:.3f}", f"{mean['ST'][j] - mean['S1'][j]:.3f}"]
            if "each" in outcome:
                row += [f"{outcome['each'][key][:, j].min():.3f} to {outcome['each'][key][:, j].max():.3f}" for key in ("S1", "ST")]
            rows.append(ui.tags.tr(*[ui.tags.td(cell) for cell in row]))
        caption = ("Shares of the variance of the number over all the runs, from 0 to 1, without units. ± is the half-width of "
                   "the 95% confidence interval" + ("; across seeds, the lowest and highest of the seeds analysed alone." if "each" in outcome else "."))
        return ui.tags.table(
            ui.tags.caption(caption, class_="small text-muted", style="caption-side: top;"),
            ui.tags.thead(ui.tags.tr(*[ui.tags.th(cell) for cell in head])), ui.tags.tbody(*rows),
            class_="sa-table small mt-2",
        )

    def _download_name(suffix):
        outcome = result()
        metric = outcome["metric"] if outcome and "metric" in outcome else None
        study = Path(input.sa_previous() or "analysis").name
        return f"{study}_{metric.variable}_{suffix}" if metric else f"{study}_{suffix}"

    @render.download(filename=lambda: _download_name("indices.csv"))
    def sa_download_csv():
        outcome = result()
        if outcome and outcome.get("kind") == "scalar":
            yield f"# {outcome['description']}\n" + indices_table(outcome).to_csv(index=False)

    @render.download(filename=lambda: _download_name("indices_by_month.csv"))
    def sa_download_months():
        outcome = result()
        if outcome and outcome.get("kind") == "months":
            yield f"# {outcome['description']}\n" + monthly_table(outcome).to_csv(index=False)

    @render.download(filename=lambda: _download_name("indices_by_age.csv"))
    def sa_download_ages():
        outcome = result()
        if outcome and outcome.get("kind") == "ages":
            yield f"# {outcome['description']}\n" + monthly_table(outcome).to_csv(index=False)

    @render.download(filename=lambda: _download_name("index_maps.nc"))
    def sa_download_nc():
        outcome = result()
        if outcome and outcome.get("kind") == "cells":
            yield cell_dataset(outcome).to_netcdf()

    return SimpleNamespace(running=running, cancel=state.cancel)
