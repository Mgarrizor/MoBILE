"""The "Run on LEONARDO (CINECA)" part of the Calibration tab: the settings of the cluster, each with what it is and what to put,
and for the calibration chosen under Calibrations: send it there, submit a job, refresh what it shows here, stop the job
(cluster.py does them, over ssh)."""

import asyncio
import datetime
from pathlib import Path

from shiny import reactive, render, ui

from .calibration_engine import CalibrationError, _clock, _seconds_since, read_calibration, read_cluster
from .cluster import (ClusterError, ClusterSettings, certificate, cluster_info, info_rows, job_cost, last_log, load_settings,
                      observation_files, refresh, remote_folder, runs_at_once, save_settings, send, stop, submit, wall_seconds)
from .config import MAX_THREADS
from .layout import with_tip

def _clock_now():
    return datetime.datetime.now().strftime("%H:%M")


DCGP_THREADS = 7  # Best on a LEONARDO DCGP node for Senegal 1998-2003 (9.85M agents): 16 runs of 7 threads, pinned; not general


def cluster_label():
    """A label after the title of the settings the jobs on the cluster use: kept on this computer, not with the calibration."""
    return ui.span("cluster", class_="badge rounded-pill fw-normal ms-1",
                   style="font-size: 0.68rem; background: #e7f1ff; color: #0a4b8c; border: 1px solid #6ea8fe;",
                   title="Used by the jobs on the cluster. Kept on this computer for every calibration sent from it, not "
                         "with the calibration.")


def _box(control, advice=None):
    """A setting with, below it, what to put, if there is advice."""
    return ui.div(control, ui.p(advice, class_="small text-muted mt-n2 mb-2") if advice else None)


def cluster_section():
    saved = load_settings()
    text, number = ui.input_text, ui.input_numeric
    settings = ui.div(
        ui.layout_columns(
            ui.div(
                _box(text("cl_host", with_tip("SSH host", "The name you log in with: `ssh leonardo` must work in a terminal "
                                              "without a password (a Host of ~/.ssh/config)."), value=saved.host),
                     "Log in first each day, e.g. `step ssh login <e-mail> --provisioner cineca-hpc` (12 h)."),
                _box(text("cl_folder", with_tip("Folder there", "Each calibration goes in a folder of its name inside it. "
                                                "~ and $VARIABLES are those of the cluster."), value=saved.folder),
                     "On $WORK or $FAST, not on scratch: files there are deleted after 40 days. Short: the paths of the runs "
                     "must stay under 160 characters."),
                _box(text("cl_mobile", with_tip("MoBILE there", "The clone the job builds the model from, at the same commit "
                                                "as here."), value=saved.mobile, placeholder="$MOBILE"),
                     "Empty: $MOBILE, as the setup lines set it (e.g. ~/mobile_env.sh)."),
                _box(ui.input_text_area("cl_setup", with_tip("Setup lines", "Run in the job before `mobile calibrate`: the "
                                        "compilers and netCDF of the model, then the Python environment with this package "
                                        "(this version)."), value=saved.setup, rows=4, width="100%"),
                     "On LEONARDO: unset PYTHONPATH after loading the python module, or it hides the packages of the venv."),
            ),
            ui.div(
                _box(text("cl_account", with_tip("Account", "The project the job is billed to (#SBATCH --account). "
                                                 "`saldo -b` there lists yours and what is left."), value=saved.account)),
                _box(text("cl_partition", with_tip("Partition", "The nodes the job runs on (#SBATCH --partition)."),
                          value=saved.partition), "dcgp_usr_prod: LEONARDO's CPU nodes, 112 cores each."),
                _box(text("cl_qos", with_tip("QOS", "The quality of service (#SBATCH --qos): its time limit and priority."),
                          value=saved.qos)),
                _box(text("cl_time", with_tip("Time limit (h:mm:ss)", "Of each job (#SBATCH --time). The calibration starts no "
                                              "trial that would not end 2 minutes before it, and stops there; submit again to "
                                              "go on."), value=saved.time),
                     "6 h is a good start: longer jobs may wait longer in the queue."),
            ),
            ui.div(
                _box(number("cl_cpus", with_tip("CPUs per job", "The cores the job asks for (#SBATCH --cpus-per-task), on one "
                                                "node."), value=saved.cpus, min=1, step=1), "112: a whole DCGP node."),
                _box(ui.input_checkbox("cl_exclusive", with_tip("Whole node (--exclusive)", "No other job on the node: runs are "
                                       "not slowed by others."), value=saved.exclusive),
                     "Yes with 112 CPUs: a DCGP node is billed whole."),
                _box(number("cl_parallel", ui.TagList(with_tip("Runs at the same time", "Each with the threads per run of the "
                                                               "calibration, set when it was made. 0: as many as fit in the CPUs."),
                                                      cluster_label()),
                            value=saved.parallel, min=0, step=1)),
                ui.output_ui("cl_fit"),
                _box(number("cl_trial_minutes", with_tip("A trial takes (minutes)", "A guess, used until 10 trials have "
                                                         "completed, to start no trial that would not end before the time "
                                                         "limit. 0: none, the first trials always start."),
                            value=saved.trial_minutes, min=0, step=1),
                     "From a run of the setup by hand, times the seeds per trial, plus a margin."),
            ),
            col_widths=(5, 4, 3),
        ),
    )
    return ui.div(
        ui.accordion(
            ui.accordion_panel(
                "Run on LEONARDO (CINECA)",
                ui.p("To run a calibration made here on a cluster, without this GUI: Create only (above), choose it under "
                     "Calibrations, Send it there, Submit a job; close the GUI if you like; later, Refresh to see how far it is. "
                     "Only what is drawn here is copied back, never the model output. While it runs there, the copy here only "
                     "shows it.", class_="small text-muted"),
                ui.accordion(
                    ui.accordion_panel(ui.TagList("Cluster settings", cluster_label()), settings, value="cl_settings"),
                    ui.accordion_panel(
                        "Cluster information",
                        ui.div(ui.input_action_button("cl_info", "Check", class_="btn-sm"),
                               ui.span("Budgets, projects, the QOS chosen, your jobs, how busy the nodes are: read-only "
                                       "commands, in one ssh call. About a minute: the budget and the project's usage are slow to ask.",
                                       class_="small text-muted"),
                               class_="d-flex gap-2 align-items-center mb-2"),
                        ui.output_ui("cl_info_table"),
                        value="cl_information"),
                    open=False, multiple=True),
                ui.output_ui("cl_chosen"),
                ui.div(
                    ui.input_action_button("cl_send", "Send", class_="btn-outline-primary"),
                    ui.input_action_button("cl_submit", "Submit job", class_="btn-outline-primary"),
                    ui.input_action_button("cl_refresh", "Refresh"),
                    ui.input_action_button("cl_stop", "Stop job"),
                    class_="d-flex gap-2 mt-2",
                ),
                ui.output_ui("cl_cost"),
                ui.output_ui("cl_busy"),
                ui.output_ui("cl_log"),
            ),
            open=False,
        ),
        class_="mt-3",
    )


def cluster_server(input, output, session, chosen, changed):
    """chosen(): the folder of the calibration chosen under Calibrations, or None. changed: bumped when the files of a
    calibration change here (e.g. after a refresh), for the views to be drawn again."""
    done = reactive.value(0)  # Bumped when an action ends

    def settings():
        return ClusterSettings(
            host=(input.cl_host() or "").strip(), folder=(input.cl_folder() or "").strip(), mobile=(input.cl_mobile() or "").strip(),
            account=(input.cl_account() or "").strip(), partition=(input.cl_partition() or "").strip(),
            qos=(input.cl_qos() or "").strip(), time=(input.cl_time() or "").strip(),
            cpus=int(input.cl_cpus() or 1), exclusive=bool(input.cl_exclusive()), parallel=int(input.cl_parallel() or 0),
            trial_minutes=float(input.cl_trial_minutes() or 0), setup=input.cl_setup() or "")

    def problems(given):
        found = []
        if not given.host:
            found.append("give the SSH host")
        if not given.folder:
            found.append("give the folder there")
        if not given.time.replace(":", "").replace("-", "").isdigit():
            found.append("give the time limit as h:mm:ss, e.g. 06:00:00")
        if given.cpus < 1:
            found.append("give the CPUs per job")
        return found

    def record():
        folder = chosen()
        if not folder:
            return None
        try:
            return read_calibration(folder)
        except (OSError, ValueError):
            return None

    @render.ui
    def cl_fit():
        """Runs × threads against the CPUs, for the calibration chosen, with the measured best on DCGP."""
        found = record()
        if found is None:
            return ui.p("Choose a calibration under Calibrations to see how its runs fit.", class_="small text-muted")
        threads = found["setup"]["run"]["threads"]
        try:
            given = settings()
        except (TypeError, ValueError):
            return None
        parallel = runs_at_once(given, threads)
        used = parallel * threads
        lines = [ui.p(f"{parallel} runs × {threads} thread{'s' if threads > 1 else ''} per run = {used} of {given.cpus} CPUs.",
                      class_="small mb-1" + (" text-danger" if used > given.cpus else ""))]
        if threads > MAX_THREADS:
            lines.append(ui.p(f"More than {MAX_THREADS} threads per run: the model does not allow it.", class_="small text-danger"))
        else:
            if used < given.cpus:
                lines.append(ui.p(f"{given.cpus - used} CPUs left unused.", class_="small text-muted mb-1"))
            if given.cpus == 112:
                lines.append(ui.p(f"For reference: on a DCGP node, 16 runs × {DCGP_THREADS} threads did best for Senegal "
                                  "1998–2003 (9.85 M agents); other setups may differ. The threads per run are set when a "
                                  "calibration is made, and results depend on them.", class_="small text-muted"))
        sampler = found.get("sampler") or {}
        startup = sampler.get("startup_trials")
        if sampler.get("name") == "tpe" and isinstance(startup, int) and startup < parallel:
            lines.append(ui.p(f"{startup} start-up trials, fewer than the {parallel} runs at the same time there: the sampler "
                              "would suggest trials while almost none have ended. They are kept with the calibration: make a "
                              f"new one from it (Use as template) with at least {parallel}.",
                              class_="small text-warning-emphasis mb-1"))
        return ui.TagList(*lines)

    @render.ui
    def cl_chosen():
        changed()
        done()
        folder = chosen()
        found = record()
        if found is None:
            return ui.p("Choose a calibration under Calibrations.", class_="small text-muted mt-2 mb-0")
        cluster = read_cluster(folder)
        if cluster is None:
            files = observation_files(folder)
            listed = [ui.tags.li(f"{path} ({size / 1e6:.2f} MB)" if size is not None else f"{path} (not found)") for path, size in files]
            return ui.div(
                ui.p(f"{Path(folder).name}: not sent. Send copies it to {remote_folder(settings(), folder)} on "
                     f"{settings().host or '?'}, with its driving files and its observations:", class_="small mb-1"),
                ui.tags.ul(*listed, class_="small mb-1"),
                ui.input_checkbox("cl_cleared", "These observations may be copied to the cluster", value=False),
                class_="mt-2")
        jobs = cluster.get("jobs", [])
        lines = [f"Sent to {cluster['host']}:{cluster['folder']}"]
        if jobs:
            lines.append("Jobs: " + ", ".join(f"{job['id']} {(job.get('state') or '?').lower()}" for job in jobs))
        else:
            lines.append("No job submitted yet: Submit job.")
        since = _seconds_since(cluster.get("refreshed"))
        lines.append(f"Refreshed {_clock(since)} ago" if since != float("inf") else "Not refreshed yet")
        return ui.tags.ul(*[ui.tags.li(line) for line in lines], class_="small mt-2 mb-0")

    @render.ui
    def cl_log():
        changed()
        done()
        folder = chosen()
        found = last_log(folder) if folder else None
        if not found:
            return None
        job, tail = found
        return ui.div(ui.p(f"The end of the log of job {job}, as of the last refresh:", class_="small mb-1"),
                      ui.tags.pre(tail, class_="small mb-0", style="max-height: 16rem; overflow: auto;"), class_="mt-2")

    copying = {"text": None}  # What a refresh is copying back, set from its thread; read by cl_busy while it runs

    @reactive.extended_task
    async def action(kind, folder, given, cleared):
        def work():
            copying["text"] = None
            if kind == "send":
                return f"Sent to {given.host}:{send(folder, given, cleared)}."
            if kind == "submit":
                job = submit(folder, given)
                after = read_cluster(folder)["jobs"][-1].get("after")
                return (f"Submitted job {job}" + (f", to start when job {after} ends" if after else "") +
                        ". Refresh to see how it goes.")
            if kind == "refresh":
                cluster = refresh(folder, say=lambda text: copying.update(text=text))
                return "Refreshed: " + (", ".join(f"job {job['id']} {(job.get('state') or '?').lower()}" for job in cluster["jobs"])
                                        or "no job yet") + "."
            job = stop(folder)
            return f"Asked job {job} to stop; Refresh to see it end." if job else "No job of it is queued or running."
        try:
            return await asyncio.to_thread(work)
        except (ClusterError, CalibrationError, OSError, ValueError) as error:
            return f"error: {error}"

    def start(kind):
        if action.status() == "running":
            ui.notification_show("Wait for the cluster action in progress.", type="warning")
            return
        folder = chosen()
        if not folder:
            ui.notification_show("Choose a calibration under Calibrations first.", type="warning")
            return
        given = settings()
        found = problems(given)
        if found:
            ui.notification_show("Cluster settings: " + "; ".join(found) + ".", type="error")
            return
        save_settings(given)
        cleared = bool(input.cl_cleared()) if "cl_cleared" in input else False
        action.invoke(kind, folder, given, cleared)

    def bind(kind):
        """Its button starts an action (a function per button: Shiny warns of a default argument)."""
        @reactive.effect
        @reactive.event(input[f"cl_{kind}"])
        def _():
            start(kind)

    for kind in ("send", "submit", "refresh", "stop"):
        bind(kind)

    asked = reactive.value(None)  # (when, sections, error) of the last Check

    @reactive.extended_task
    async def info_task(given, folder):
        try:
            return _clock_now(), await asyncio.to_thread(cluster_info, given, folder), None
        except (ClusterError, OSError, ValueError) as error:
            return _clock_now(), {}, str(error)

    @reactive.effect
    @reactive.event(input.cl_info)
    def _():
        given = settings()
        if not given.host:
            ui.notification_show("Cluster settings: give the SSH host.", type="error")
            return
        save_settings(given)
        folder = chosen()
        info_task.invoke(given, folder if folder and read_cluster(folder) else None)

    @reactive.effect
    def info_done():
        if info_task.status() in ("success", "error"):
            with reactive.isolate():
                asked.set(info_task.result() if info_task.status() == "success" else (_clock_now(), {}, "see the terminal"))

    @render.ui
    def cl_info_table():
        if info_task.status() == "running":
            return ui.p("Asking the cluster…", class_="small text-muted mb-0")
        _, said = certificate()
        found = asked()
        if found is None:
            return ui.p(f"Login certificate: {said}. Check to see the rest.", class_="small mb-0")
        when, sections, error = found
        if error:
            return ui.TagList(ui.p(f"Login certificate: {said}.", class_="small mb-1"),
                              ui.p(f"Could not ask the cluster ({when}): {error}", class_="small text-danger mb-0"))
        rows = info_rows(sections, settings(), record())
        rows.append(("Login certificate", said, "ssh-add here (no ssh)", said.startswith(("expired", "no certificate"))))
        body = [ui.tags.tr(ui.tags.td(what, class_="text-nowrap"),
                           ui.tags.td(value, class_="text-warning-emphasis" if warning else None),
                           ui.tags.td(source, class_="text-muted"))
                for what, value, source, warning in rows]
        return ui.TagList(
            ui.tags.table(ui.tags.thead(ui.tags.tr(ui.tags.th("What"), ui.tags.th("Now"), ui.tags.th("Said by"))),
                          ui.tags.tbody(*body), class_="table table-sm small mb-1"),
            ui.p(f"As of {when}. Core-hours: CPUs × hours of the jobs, as billed.", class_="small text-muted mb-0"))

    @render.ui
    def cl_cost():
        """What a job of these settings costs at most, and the time limit against the QOS's, if checked."""
        try:
            given = settings()
        except (TypeError, ValueError):
            return None
        most = job_cost(given)
        if most is None:
            return None
        lines = [f"A job asks for {given.cpus} CPUs × {given.time}: at most {most:,.0f} core-hours, less if it ends sooner"
                 + (" (a whole node is billed with --exclusive)" if given.exclusive else "") + "."]
        warn = False
        found = asked()
        for line in (found[1].get("qos", [])[:1] if found else []):
            name, maxwall = (line.split("|") + [""])[:2]
            if wall_seconds(maxwall) is not None and (wall_seconds(given.time) or 0) > wall_seconds(maxwall) and name == given.qos:
                lines.append(f"Longer than the {maxwall} that QOS {name} allows: sbatch would refuse it.")
                warn = True
        return ui.p(" ".join(lines), class_="small mt-2 mb-0 " + ("text-warning-emphasis" if warn else "text-muted"))

    @reactive.effect
    def collect():
        if action.status() in ("success", "error"):
            with reactive.isolate():
                message = action.result() if action.status() == "success" else "error: see the terminal"
                failed = message.startswith("error: ")
                ui.notification_show(message[len("error: "):] if failed else message, type="error" if failed else "message",
                                     duration=None if failed else 8)
                done.set(done() + 1)
                changed.set(changed() + 1)

    @render.ui
    def cl_busy():
        if action.status() == "running":
            reactive.invalidate_later(1)  # To show what a refresh copies, once it knows
            return ui.p(copying["text"] or "Working on the cluster…", class_="small text-muted mt-2 mb-0")
        return None

    @reactive.effect
    def enable():
        changed()
        done()
        folder = chosen()
        cluster = read_cluster(folder) if folder else None
        busy = action.status() == "running"
        ui.update_action_button("cl_send", disabled=busy or not folder or cluster is not None)
        for name in ("cl_submit", "cl_refresh"):
            ui.update_action_button(name, disabled=busy or cluster is None)
        listed = cluster is not None and any(job.get("listed") for job in cluster.get("jobs", []))
        ui.update_action_button("cl_stop", disabled=busy or not listed)
        ui.update_action_button("cl_info", disabled=info_task.status() == "running")
