"""A sensitivity analysis on disk and its runs, apart from single runs: <results folder>/sensitivity/<name>/ holds

  sa.json      what was sampled, how, with which setup, and how far the runs got
  samples.txt  the parameter values, one row per sample, in the order SALib expects their outputs back
  inputs/      the driving files cut to the region of the setup, once for all the runs, if it has one
  runs/seed_<seed>/sample_<index>/   one run folder per sample and seed, as made by run_MOBILE.sh

The same samples are run for every seed. Finished runs are kept, so that a cancelled analysis resumes where it
stopped and its outputs can be analysed again in other ways without running again.
"""

import datetime
import json
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from pathlib import Path

import numpy as np

from .config import MAX_PATH_LENGTH, Config, ConfigError
from .grid import pop_coordinates
from .region import cut_inputs
from .rundir import OUTPUT_NAME, new_run_id
from .runner import RunCancelled, Runner
from .sensitivity import DISTRIBUTIONS, SampledParameter, run_count, sample

STUDIES_FOLDER = "sensitivity"
RECORD = "sa.json"
SAMPLES = "samples.txt"
RUNS = "runs"
INPUTS = "inputs"
ATTEMPTS = 2  # A failed run is tried once more before it counts as failed


def studies_dir(runs_dir):
    return Path(runs_dir) / STUDIES_FOLDER


def run_name(seed, index):
    return f"seed_{seed}/sample_{index:05d}"


def read_study(folder):
    return json.loads((Path(folder) / RECORD).read_text())


def write_study(folder, record):
    path = Path(folder) / RECORD
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(record, indent=2) + "\n")
    temporary.replace(path)  # Never half written, even if the GUI stops meanwhile


def study_parameters(record):
    return [SampledParameter(**parameter) for parameter in record["parameters"]]


def create_study(config, parameters, n, second_order, seeds, name=None, sample_seed=None):
    """Sample the parameters and write the folder of a new analysis; return the folder. config is the setup
    with the values of the parameters not sampled, the outputs to write, and the agents of the runs."""
    folder = studies_dir(config.runs_dir) / (name or new_run_id())
    _, values = sample(parameters, n, second_order, seed=sample_seed)
    folder.mkdir(parents=True)
    np.savetxt(folder / SAMPLES, values, fmt="%.17g", header=" ".join(parameter.name for parameter in parameters))
    run_inputs = dict(config.inputs)
    if config.region is not None:
        # Cut once here, not in each of the thousands of run folders
        run_inputs.update(cut_inputs(config.inputs, config.region, folder / INPUTS, pop_coordinates(config.inputs["pop_file"])))
        too_long = [path for path in run_inputs.values() if len(str(path)) > MAX_PATH_LENGTH]
        if too_long:
            shutil.rmtree(folder)
            raise ConfigError(f"paths in the analysis folder longer than {MAX_PATH_LENGTH} characters: {too_long}")
    record = {
        "status": "created",
        "date": datetime.datetime.now().isoformat(timespec="seconds"),
        "method": "sobol",
        "parameters": [asdict(parameter) for parameter in parameters],
        "n": n,
        "second_order": second_order,
        "seeds": list(seeds),
        "sample_seed": sample_seed,
        "runs": run_count(n, parameters, second_order, len(seeds)),
        "finished": 0,
        "failed": 0,
        "mobile": str(config.mobile),
        "project": config.project,
        "run": config.run,
        "inputs": config.inputs,
        "run_inputs": run_inputs,
        "region": config.region,
        "params": {key: float(value) for key, value in config.params.items()},
        "output": list(config.output) if config.output is not None else None,
    }
    write_study(folder, record)
    return folder


def study_config(folder, record):
    """The configuration of the runs of an analysis, before the values of its samples and seeds."""
    return Config(
        mobile=Path(record["mobile"]), runs_dir=Path(folder) / RUNS, run=dict(record["run"]), inputs=dict(record["run_inputs"]),
        params=dict(record["params"]), output=tuple(record["output"]) if record["output"] is not None else None,
        project=record["project"], region=None,
    )


def run_finished(run_dir):
    """True if the run folder holds a finished run with its output."""
    try:
        manifest = json.loads((Path(run_dir) / "run.json").read_text())
    except (OSError, json.JSONDecodeError):
        return False
    return manifest.get("status") == "finished" and (Path(run_dir) / OUTPUT_NAME / f"{OUTPUT_NAME}.nc").is_file()


class StudyState:
    """Progress of an analysis, written by its worker threads and read by the session."""

    def __init__(self):
        self.lock = threading.Lock()
        self.cancelled = False
        self.runners = set()
        self.total = self.done = self.failed = self.done_before = 0
        self.started = time.time()
        self.message = ""

    def begin(self, total, done):
        with self.lock:
            self.cancelled = False
            self.total, self.done, self.done_before, self.failed = total, done, done, 0
            self.started = time.time()
            self.message = "Starting"

    def update(self, **values):
        with self.lock:
            for key, value in values.items():
                setattr(self, key, value)

    def count(self, key):
        with self.lock:
            setattr(self, key, getattr(self, key) + 1)

    def add_runner(self, runner):
        with self.lock:
            if self.cancelled:
                return False
            self.runners.add(runner)
            return True

    def remove_runner(self, runner):
        with self.lock:
            self.runners.discard(runner)

    def cancel(self):
        with self.lock:
            self.cancelled = True
            runners = list(self.runners)
        for runner in runners:
            runner.cancel()

    def snapshot(self):
        """(runs done, total, failed, running now, seconds elapsed, seconds left or None, message)."""
        with self.lock:
            elapsed = time.time() - self.started
            done_now = self.done - self.done_before
            left = elapsed / done_now * (self.total - self.done - self.failed) if done_now else None
            return self.done, self.total, self.failed, len(self.runners), elapsed, left, self.message


def run_study(folder, state, parallel=1, threads=None):
    """Run the samples of an analysis not yet finished, parallel at a time, and return its record.

    A run folder left by a cancelled or failed attempt is removed and made again. The status is finished
    when every run is, cancelled, or incomplete if some failed twice."""
    folder = Path(folder)
    record = read_study(folder)
    config = study_config(folder, record)
    if threads:
        config = replace(config, run={**config.run, "threads": threads})
    config.validate()
    names = [parameter["name"] for parameter in record["parameters"]]
    values = np.loadtxt(folder / SAMPLES, ndmin=2)
    jobs = [(seed, index) for seed in record["seeds"] for index in range(len(values))]
    todo = [job for job in jobs if not run_finished(config.runs_dir / run_name(*job))]
    state.begin(len(jobs), len(jobs) - len(todo))
    write_study(folder, {**record, "status": "running"})

    def one(job):
        seed, index = job
        run_config = replace(
            config,
            params={**config.params, **{name: float(value) for name, value in zip(names, values[index])}},
            run={**config.run, "seed": seed},
        )
        for _ in range(ATTEMPTS):
            run_dir = config.runs_dir / run_name(seed, index)
            if run_dir.exists():
                shutil.rmtree(run_dir)  # Left by a cancelled or failed attempt
            runner = Runner(run_config)
            if not state.add_runner(runner):
                return
            try:
                result = runner.run(run_name(seed, index), wait=True)
            except RunCancelled:
                return
            finally:
                state.remove_runner(runner)
            if result.status == "cancelled":
                return
            if result.ok:
                state.count("done")
                return
        state.count("failed")

    state.update(message="Running")
    with ThreadPoolExecutor(max_workers=max(1, parallel)) as pool:
        for _ in pool.map(one, todo):
            pass
    done, total, failed, *_ = state.snapshot()
    status = "cancelled" if state.cancelled and done + failed < total else "finished" if done == total else "incomplete"
    record = {**read_study(folder), "status": status, "finished": done, "failed": failed}
    write_study(folder, record)
    state.update(message=status)
    return record


def list_studies(runs_dir):
    """Analyses in the results folder, newest first: {folder: record}."""
    studies = {}
    folder = studies_dir(runs_dir)
    if not folder.is_dir():
        return {}
    for study in folder.iterdir():
        try:
            studies[str(study)] = read_study(study)
        except (OSError, json.JSONDecodeError, KeyError):
            continue
    return dict(sorted(studies.items(), key=lambda item: item[1].get("date", ""), reverse=True))


def study_label(folder, record):
    """e.g. 'wet_season (2026-11-04 12:00:01): 6 parameters, N = 1024, 5 seeds, 14,336 runs, finished'."""
    seeds = len(record["seeds"])
    status = record["status"]
    if status != "finished":
        status = f"{status}, {record['finished']:,} of {record['runs']:,} done"
    names = ", ".join(parameter["name"] for parameter in record["parameters"])
    seeds = f", {seeds} seeds" if seeds > 1 else ""
    date = record["date"].replace("T", " ")
    return f"{Path(folder).name} ({date}): {names}; N = {record['n']:,}{seeds}, {record['runs']:,} runs, {status}"


def describe_parameter(parameter):
    """e.g. 'b_rate: log-uniform from 0.2 to 20'."""
    text = f"{parameter.name}: {DISTRIBUTIONS[parameter.distribution].lower()} from {parameter.low:.4g} to {parameter.high:.4g}"
    if parameter.distribution == "normal":
        text += f", mean {parameter.mean:.4g}, sd {parameter.sd:.4g}"
    if parameter.distribution == "lognormal":
        text += f", ln x with mean {parameter.mean:.4g}, sd {parameter.sd:.4g}"
    return text
