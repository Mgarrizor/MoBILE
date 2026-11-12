"""The "Run on LEONARDO (CINECA)" part of the Calibration tab: the settings of the cluster, each with what it is and what to put,
and for the calibration chosen under Calibrations: send it there, submit a job, refresh what it shows here, stop the job
(cluster.py does them, over ssh)."""

import asyncio
from pathlib import Path

from shiny import reactive, render, ui

from .calibration_engine import CalibrationError, _clock, _seconds_since, read_calibration, read_cluster
from .cluster import (ClusterError, ClusterSettings, last_log, load_settings, observation_files, refresh, remote_folder,
                      runs_at_once, save_settings, send, stop, submit)
from .config import MAX_THREADS
from .layout import with_tip

DCGP_THREADS = 7  # Best on a LEONARDO DCGP node for Senegal 1998-2003 (9.85M agents): 16 runs of 7 threads, pinned; not general


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
                _box(number("cl_parallel", with_tip("Runs at the same time", "Each with the threads per run of the calibration, "
                                                    "set when it was made. 0: as many as fit in the CPUs."),
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
                ui.accordion(ui.accordion_panel("Cluster settings", settings), open=False),
                ui.output_ui("cl_chosen"),
                ui.div(
                    ui.input_action_button("cl_send", "Send", class_="btn-outline-primary"),
                    ui.input_action_button("cl_submit", "Submit job", class_="btn-outline-primary"),
                    ui.input_action_button("cl_refresh", "Refresh"),
                    ui.input_action_button("cl_stop", "Stop job"),
                    class_="d-flex gap-2 mt-2",
                ),
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

    @reactive.extended_task
    async def action(kind, folder, given, cleared):
        def work():
            if kind == "send":
                return f"Sent to {given.host}:{send(folder, given, cleared)}."
            if kind == "submit":
                return f"Submitted job {submit(folder, given)}. Refresh to see how it goes."
            if kind == "refresh":
                cluster = refresh(folder)
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

    for kind in ("send", "submit", "refresh", "stop"):
        @reactive.effect
        @reactive.event(input[f"cl_{kind}"])
        def _(kind=kind):
            start(kind)

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
            return ui.p("Working on the cluster…", class_="small text-muted mt-2 mb-0")
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
