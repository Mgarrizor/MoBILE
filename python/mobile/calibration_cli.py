"""`mobile calibrate <folder>`: run or continue a calibration made in the GUI without the GUI, e.g. in a batch job on a
cluster. One line per trial on the standard output (the log of the job), a summary at the end, and an exit code a job
chain can act on (EXIT). It stops cleanly before the end of a Slurm job (SLURM_JOB_END_TIME, or --end-time), and on
SIGTERM or SIGINT (cancelling the runs going on); another job, or the GUI, then goes on from where it stopped."""

import datetime
import os
import signal
import socket
import sys
import threading
import time

import optuna

from .calibration_engine import CalibrationError, read_calibration, run_calibration
from .config import ConfigError
from .sensitivity_runs import StudyState

DEADLINE_MARGIN = 120  # Seconds before the end of the job by which the trials must have ended
EXIT = {"finished": 0, "stopped at deadline": 3, "cancelled": 3, "incomplete": 3, "stopped": 1}
EXIT_ERROR = 1  # Also when the calibration cannot run, e.g. it runs already
RESUMABLE = 3


def cores():
    """The cores this process may use (those of a batch job, not of the whole node)."""
    try:
        return len(os.sched_getaffinity(0))
    except AttributeError:  # macOS
        return os.cpu_count() or 1


def deadline_from(end_time=None, environ=os.environ):
    """Seconds since the epoch by which the trials must have ended: DEADLINE_MARGIN before --end-time (ISO, local time
    unless it says otherwise) or the end of the Slurm job; None without either."""
    if end_time:
        try:
            end = datetime.datetime.fromisoformat(end_time).timestamp()
        except ValueError:
            raise CalibrationError(f"--end-time {end_time!r}: give a date and time, e.g. 2026-11-12T08:00") from None
    elif environ.get("SLURM_JOB_END_TIME", "").strip().isdigit():
        end = float(environ["SLURM_JOB_END_TIME"])
    else:
        return None
    return end - DEADLINE_MARGIN


def _stamp(seconds=None):
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(seconds))


def _duration(seconds):
    seconds = int(round(seconds))
    return f"{seconds // 3600}h{seconds % 3600 // 60:02d}m" if seconds >= 3600 else f"{seconds // 60}m{seconds % 60:02d}s"


def _values(names, values):
    return ", ".join(f"{name} {value:.4g}" for name, value in zip(names, values))


def trial_line(study, trial, names, target):
    """One line about a trial that has just ended, or None for one not started (e.g. at the deadline)."""
    took = (trial.datetime_complete - trial.datetime_start).total_seconds() if trial.datetime_complete and trial.datetime_start else None
    took = f" in {_duration(took)}" if took is not None else ""
    if trial.state == optuna.trial.TrialState.COMPLETE:
        text = f"trial {trial.number} completed{took}: {_values(names, trial.values)}"
    elif trial.user_attrs.get("ended"):
        return None
    elif trial.user_attrs.get("cancelled"):
        text = f"trial {trial.number} cancelled"
    else:
        reason = (trial.user_attrs.get("failure") or "").strip().splitlines()
        text = f"trial {trial.number} failed{took}" + (f": {reason[-1][:200]}" if reason else "")
    complete = study.get_trials(deepcopy=False, states=(optuna.trial.TrialState.COMPLETE,))
    if complete:
        if len(names) == 1:
            best = study.best_trial
            text += f" | best {_values(names, best.values)} (trial {best.number})"
        else:
            text += f" | Pareto front {len(study.best_trials)} trials"
    return f"[{_stamp()}] {text} | {len(complete)} of {target} completed"


def calibrate(folder, parallel=None, trial_minutes=None, end_time=None, mobile=None, out=sys.stdout):
    """Run the calibration in a folder; returns the exit code (EXIT)."""
    def say(text):
        print(text, file=out, flush=True)

    try:
        record = read_calibration(folder)
    except (OSError, ValueError) as error:
        say(f"Not a calibration folder: {folder} ({error})")
        return EXIT_ERROR
    threads = record["setup"]["run"]["threads"]
    available = cores()
    if parallel is None:
        parallel = max(1, available // threads)
    if parallel < 1 or parallel * threads > available:
        say(f"{parallel} runs at a time × {threads} threads per run (those of the calibration) need {parallel * threads} cores; "
            f"this process may use {available}. Use --parallel {max(1, available // threads)} or fewer.")
        return EXIT_ERROR
    try:
        deadline = deadline_from(end_time)
    except CalibrationError as error:
        say(str(error))
        return EXIT_ERROR
    names = [objective["name"] for objective in record["objectives"]]
    target = record["n_trials"]
    where = socket.gethostname() + (f", job {os.environ['SLURM_JOB_ID']}" if os.environ.get("SLURM_JOB_ID") else "")
    say(f"[{_stamp()}] calibration {folder}: {record.get('completed', 0)} of {target} trials completed so far; "
        f"{parallel} runs at a time × {threads} threads on {where}"
        + (f"; no trial started after it could end past {_stamp(deadline)}" if deadline else ""))

    state = StudyState()
    signalled = []

    def on_signal(number, _frame):
        signalled.append(signal.Signals(number).name)
        # Not here: the handler may run while this thread holds the lock of the state
        threading.Thread(target=state.cancel, daemon=True).start()

    def on_trial(study, trial):
        line = trial_line(study, trial, names, target)
        if line:
            say(line)

    previous = {number: signal.signal(number, on_signal) for number in (signal.SIGTERM, signal.SIGINT)}
    started = time.time()
    try:
        record = run_calibration(folder, state, parallel, deadline=deadline,
                                 trial_seconds=trial_minutes * 60 if trial_minutes else None, on_trial=on_trial, mobile=mobile)
    except (CalibrationError, ConfigError) as error:
        say(f"[{_stamp()}] the calibration cannot run: {error}")
        return EXIT_ERROR
    finally:
        for number, handler in previous.items():
            signal.signal(number, handler)
    status = record["status"]
    say(f"[{_stamp()}] {status}" + (f" ({signalled[0]})" if signalled else "")
        + f" after {_duration(time.time() - started)}: {record['completed']} of {target} trials completed, "
          f"{record['failed']} failed in all")
    if status == "stopped" and record.get("failure"):
        say("The end of the log of a run that failed:\n" + record["failure"].rstrip())
    code = EXIT.get(status, EXIT_ERROR)
    say(f"exit {code}: " + {0: "done", RESUMABLE: "not done: run the same command again to go on"}.get(code, "see above"))
    return code
