"""A calibration on disk, run with Optuna: <results folder>/calibration/<name>/ holds

  calibration.json  what is calibrated, against what, with which setup, sampler and number of trials
  optuna.db         the Optuna study (SQLite): every trial, its values and objectives; a calibration resumes from it
  status.json       written by the process running the calibration, with a heartbeat: whether it runs, where, and how far
  optuna.snapshot.db a consistent copy of the study, written with the status, that can be copied while the trials go on
  inputs/           the driving files cut to the region and period of the setup, once for all the trials
  bin/mobile.out    the model, built by the first run and run as it is by all the others (mobile.sh -E)
  trials/trial_<n>/ one folder per trial: its temperature file, if offset, a run folder per seed, and series/: the
                    model and the observations of each objective as compared, kept to be drawn without the output

Paths in calibration.json may be relative to its folder (a calibration sent to a cluster), and the MoBILE clone is that
of the record if it exists, else $MOBILE.

A trial samples the parameters, runs the model for each seed, processes the output as each objective says and compares
it with the observations of the objective: the values of the metrics are the objectives Optuna optimises.

Temperature offsets (dT) shift the temperature of chosen cells, e.g. to stand for the temperature where people live
within a coarse cell. The cells are given from the coolest to the warmest, as they must stay: the first gets an offset
dT_1, and each next one a gap of at least 0 above the one before (in the means over the simulated period), so that
the order of their temperatures holds in every trial without any trial being wasted.
"""

import datetime
import fcntl
import json
import math
import os
import shutil
import socket
import sqlite3
import subprocess
import threading
import time
from dataclasses import replace
from pathlib import Path

import netCDF4
import numpy as np
import optuna
import pandas as pd

from .calibration_data import DataError, drop_window, read_observations, select_window, write_observations
from .calibration_metrics import DIRECTIONS, pair, metrics
from .calibration_model import SPACES, model_members, process_both, seed_spread
from .calibration_steps import apply_steps
from .cells import cell_areas
from .config import MAX_PATH_LENGTH, ConfigError
from .driving import LAT_NAMES, LON_NAMES, POP_NAMES, TEMP_NAMES, first_name
from .grid import pop_coordinates
from .parameters import to_model
from .region import cut_inputs
from .results import _md5
from .rundir import new_run_id, period_steps
from .runner import NETCDF_LOCK, BuildOnce, RunCancelled, Runner
from .setup import from_fields, to_dict

# Raised when a change means calibrations made before cannot be resumed (e.g. 2: the first trial has no offset). They
# can still be looked at.
VERSION = 2
OLD_CALIBRATION = ("This calibration was made by an earlier version of the calibration engine: it can be looked at, but not "
                   "resumed. Start a new calibration.")
FOLDER = "calibration"
RECORD = "calibration.json"
DATABASE = "optuna.db"
LOCK = "running.lock"  # Held by the process running a calibration; the system lets go of it when that process ends
STATUS = "status.json"
SNAPSHOT = "optuna.snapshot.db"
CLUSTER = "cluster.json"  # In a calibration sent to a cluster (cluster.py): where, its jobs, and what the last refresh saw
SERIES = "series"
HEARTBEAT_SECONDS = 60  # The status is written this often while a calibration runs, and after every trial
STALE_SECONDS = 300  # A status not written for this long, on another computer without Slurm to ask, is of a process gone
SNAPSHOT_SECONDS = 30  # The snapshot of the study is written at most this often, and at the end
CRASH_RATE = 0.1  # The calibration stops when more trials fail than this share of the trials asked for (at least FAIL_FAST)
EXPECTED_FROM = 10  # The time a trial takes is the 95th percentile of the completed trials once there are this many
STUDY_NAME = "calibration"
INPUTS = "inputs"
TRIALS = "trials"
BINARY = Path("bin") / "mobile.out"
ATTEMPTS = 2  # A failed run is tried once more before its trial fails
FAIL_FAST = 3  # The calibration stops if this many trials fail before any completes: they would all fail alike
SAMPLERS = {
    "tpe": "TPE (Tree-structured Parzen Estimator): multivariate, with constant liar for trials run side by side",
    "random": "Random: every trial drawn independently, as a reference",
    "nsga2": "NSGA-II: genetic, for several objectives",
}
SAMPLER_LINKS = {
    "tpe": "https://optuna.readthedocs.io/en/stable/reference/samplers/generated/optuna.samplers.TPESampler.html",
    "random": "https://optuna.readthedocs.io/en/stable/reference/samplers/generated/optuna.samplers.RandomSampler.html",
    "nsga2": "https://optuna.readthedocs.io/en/stable/reference/samplers/generated/optuna.samplers.NSGAIISampler.html",
}
optuna.logging.set_verbosity(optuna.logging.WARNING)


class CalibrationError(ValueError):
    """A calibration that cannot be made or run as asked, with what is wrong."""


class TrialFailed(RuntimeError):
    """A run of the trial failed twice, or its output could not be compared: the trial fails, the others go on."""


def calibrations_dir(runs_dir):
    return Path(runs_dir) / FOLDER


def read_calibration(folder):
    return json.loads((Path(folder) / RECORD).read_text())


def write_calibration(folder, record):
    path = Path(folder) / RECORD
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(record, indent=2) + "\n")
    temporary.replace(path)


# ---------------------------------------------------------------- temperature offsets

def _coordinates(data):
    return (np.asarray(data[first_name(LAT_NAMES, data.variables)][:], dtype="f8"),
            np.asarray(data[first_name(LON_NAMES, data.variables)][:], dtype="f8"))


def _cell(lat, lon, cell):
    """(i, j) of the cell of a grid whose centre is that of `cell` {lat, lon}."""
    i, j = int(np.argmin(np.abs(lat - cell["lat"]))), int(np.argmin(np.abs(lon - cell["lon"])))
    step = min([abs(float(values[1] - values[0])) for values in (lat, lon) if len(values) > 1] or [1.0])
    if abs(lat[i] - cell["lat"]) > step / 2 or abs(lon[j] - cell["lon"]) > step / 2:
        raise CalibrationError(f"no cell at {cell['lat']}°N, {cell['lon']}°E in the temperature file")
    return i, j


def cell_means(temp_file, cells):
    """The mean temperature of each cell over all the days of the file (that of a calibration is cut to its period)."""
    with netCDF4.Dataset(temp_file) as data:
        lat, lon = _coordinates(data)
        field = data[first_name(TEMP_NAMES, data.variables)]
        means = []
        for cell in cells:
            i, j = _cell(lat, lon, cell)
            values = np.ma.filled(field[:, i, j].astype("f8"), np.nan)
            if not np.isfinite(values).any():
                raise CalibrationError(f"the cell at {cell['lat']}°N, {cell['lon']}°E has no temperature")
            means.append(float(np.nanmean(values)))
    return means


def offsets_from(temperature, values):
    """{dT name: offset} of each cell from the sampled values: with the order kept, dT_1 for the first (coolest) cell, and
    for each next one the gap above the one before, in their means: mean_k + dT_k = mean_(k-1) + dT_(k-1) + gap_k; without,
    each dT_k as sampled."""
    cells, means = temperature["cells"], temperature["means"]
    if not temperature.get("ordered", True):
        return {f"dT_{k + 1}": values[f"dT_{k + 1}"] for k in range(len(cells))}
    offsets = [values["dT_1"]]
    for k in range(1, len(cells)):
        offsets.append(means[k - 1] + offsets[k - 1] + values[f"gap_{k + 1}"] - means[k])
    return {f"dT_{k + 1}": offset for k, offset in enumerate(offsets)}


def baseline(temperature):
    """The sampled values of no offset at all (dT_1 = 0 and each gap the difference of the cell means), or None if they are
    outside the ranges of the calibration."""
    means = temperature["means"]
    low, high = temperature["first"]
    if not temperature.get("ordered", True):
        return {f"dT_{k + 1}": 0.0 for k in range(len(means))} if low <= 0.0 <= high else None
    values = {"dT_1": 0.0, **{f"gap_{k + 1}": means[k] - means[k - 1] for k in range(1, len(means))}}
    inside = low <= 0.0 <= high and all(temperature["gap"][0] <= values[f"gap_{k + 1}"] <= temperature["gap"][1] for k in range(1, len(means)))
    return values if inside else None


def members(cell):
    """The cells a calibrated cell stands for: those of a region ({lat, lon, members}), or the cell itself."""
    return cell.get("members") or [{"lat": cell["lat"], "lon": cell["lon"]}]


def region_mean(temp_file, pop_file, cell):
    """The mean temperature of a cell, or of a region weighted by the people of its cells (by the cell areas of the model):
    where people live. A region without people takes the plain mean of its cells."""
    cells = members(cell)
    means = np.array(cell_means(temp_file, cells))
    if len(cells) == 1:
        return float(means[0])
    with netCDF4.Dataset(pop_file) as data:
        lat, lon = _coordinates(data)
        pop = np.ma.filled(data[first_name(POP_NAMES, data.variables)][:].astype("f8"), np.nan)
    areas = cell_areas(pop_file)
    people = np.array([np.nan_to_num(pop[_cell(lat, lon, member)]) * areas[_cell(lat, lon, member)] for member in cells])
    return float(np.average(means, weights=people)) if people.sum() > 0 else float(means.mean())


def offset_temperature(source, target, cells, offsets):
    """Write a copy of the temperature file with each cell, or every cell of each region, shifted by its offset (°C), the
    others as they are."""
    shutil.copyfile(source, target)
    with netCDF4.Dataset(target, "a") as data:
        lat, lon = _coordinates(data)
        field = data[first_name(TEMP_NAMES, data.variables)]
        for k, cell in enumerate(cells):
            for member in members(cell):
                i, j = _cell(lat, lon, member)
                field[:, i, j] = field[:, i, j] + offsets[f"dT_{k + 1}"]
        data.mobile_offsets = json.dumps({f"{cell['lat']},{cell['lon']}": round(offsets[f"dT_{k + 1}"], 6)
                                          for k, cell in enumerate(cells)})


# ---------------------------------------------------------------- creating

def create_calibration(config, objectives, parameters=(), temperature=None, seeds=(12345,), n_trials=100,
                       sampler="tpe", startup_trials=10, sampler_seed=1, name=None, validation=None):
    """Write the folder of a new calibration and return it.

    config: the setup, with the parameters not calibrated and the outputs the objectives need.
    objectives: [{name, data (observations file), variable, space, aggregation, steps (applied to the model output),
    metric}]; each is minimised or maximised as its metric says (calibration_metrics.DIRECTIONS).
    parameters: SampledParameter of the model to calibrate (uniform or log-uniform), in the units of the sliders.
    temperature: {cells: [{lat, lon}, or {lat, lon, members: [{lat, lon}]} for a region whose cells share one offset] from
    the coolest to the warmest (regions by their mean weighted by people), first: (low, high) of dT_1 in °C, gap: (low,
    high) of each next gap, low at least 0, ordered: True (default) to keep their order, or False for each dT_k sampled on
    its own within the range of dT_1}, or None.
    validation: (first, last) dates of a validation window, or None: the objectives are calibrated on the period the model
    and the data share without it, and each trial is scored on it too, with the same metrics, kept with the trial."""
    if not objectives:
        raise CalibrationError("give at least one objective")
    if not parameters and not temperature:
        raise CalibrationError("give at least one parameter or temperature offset to calibrate")
    for objective in objectives:
        if objective["metric"] not in DIRECTIONS:
            raise CalibrationError(f"unknown metric {objective['metric']!r}: one of {', '.join(DIRECTIONS)}")
        if objective.get("space", "people") not in SPACES:
            raise CalibrationError(f"unknown space {objective['space']!r}: one of {', '.join(SPACES)}")
        read_observations(objective["data"])  # Raises DataError if it cannot be read
        if objective.get("data_raw"):
            read_observations(objective["data_raw"])
    if validation is not None:
        validation = _validation(validation, objectives)
    for parameter in parameters:
        if parameter.distribution not in ("uniform", "loguniform"):
            raise CalibrationError(f"{parameter.name}: only uniform and log-uniform ranges can be calibrated")
    if sampler not in SAMPLERS:
        raise CalibrationError(f"unknown sampler {sampler!r}: one of {', '.join(SAMPLERS)}")
    folder = calibrations_dir(config.runs_dir) / (name or new_run_id())
    if folder.exists():
        raise CalibrationError(f"{folder} exists already: choose another name")
    folder.mkdir(parents=True)
    try:
        run_inputs = dict(config.inputs)
        steps = period_steps(config)
        if config.region is not None or steps is not None:
            # Cut once here, not in each trial
            run_inputs.update(cut_inputs(config.inputs, config.region, folder / INPUTS, pop_coordinates(config.inputs["pop_file"]),
                                         steps))
        too_long = [path for path in run_inputs.values() if len(str(path)) > MAX_PATH_LENGTH - 40]
        if too_long:
            raise ConfigError(f"paths in the calibration folder longer than {MAX_PATH_LENGTH - 40} characters: {too_long}")
        if temperature:
            temperature = _temperature(temperature, run_inputs["temp_file"], run_inputs["pop_file"])
    except (ConfigError, CalibrationError, DataError):
        shutil.rmtree(folder)
        raise
    record = {
        "version": VERSION,
        "status": "created",
        "date": datetime.datetime.now().isoformat(timespec="seconds"),
        "setup": to_dict(config),
        "params": {key: float(value) for key, value in config.params.items()},
        "output": list(config.output) if config.output is not None else None,
        "run_inputs": run_inputs,
        "parameters": [{"name": p.name, "distribution": p.distribution, "low": p.low, "high": p.high} for p in parameters],
        "temperature": temperature,
        "validation": validation,
        "objectives": [{"space": "people", "aggregation": None, "steps": [], **objective, "data": str(Path(objective["data"]).resolve()),
                        **({"data_raw": str(Path(objective["data_raw"]).resolve())} if objective.get("data_raw") else {}),
                        "direction": DIRECTIONS[objective["metric"]]} for objective in objectives],
        "seeds": [int(seed) for seed in seeds],
        "n_trials": int(n_trials),
        "sampler": {"name": sampler, "startup_trials": int(startup_trials), "seed": sampler_seed},
        "completed": 0,
        "failed": 0,
    }
    write_calibration(folder, record)
    open_study(folder, record)  # The database exists from the start: the GUI may read it while the first trials run
    return folder


def _validation(validation, objectives):
    """[first, last] of a validation window, checked: within the observations of every objective, with some left out of it."""
    try:
        first, last = (pd.Timestamp(value) for value in validation)
    except (TypeError, ValueError):
        raise CalibrationError(f"the validation window needs a first and a last date: {validation!r}") from None
    if first > last:
        raise CalibrationError("the validation window must start before it ends")
    window = (str(first.date()), str(last.date()))
    for objective in objectives:
        if not objective.get("data_raw"):
            raise CalibrationError(f"{objective['name']}: a validation window needs the observations as loaded: add the objective again")
        data = read_observations(objective["data_raw"])
        if data.shape != "dated":
            raise CalibrationError(f"{objective['name']}: a validation window needs dated observations")
        try:
            select_window(data, *window)
            drop_window(data, *window)
        except DataError as error:
            raise CalibrationError(f"{objective['name']}: {error}") from None
    return list(window)


def _temperature(temperature, temp_file, pop_file):
    cells = [{"lat": float(cell["lat"]), "lon": float(cell["lon"]),
              **({"members": [{"lat": float(m["lat"]), "lon": float(m["lon"])} for m in cell["members"]]} if cell.get("members") else {})}
             for cell in temperature["cells"]]
    first, gap = [float(value) for value in temperature["first"]], [float(value) for value in temperature.get("gap", (0, 0))]
    ordered = bool(temperature.get("ordered", True))
    if first[0] >= first[1]:
        raise CalibrationError("the range of dT_1 needs its low below its high")
    if ordered and len(cells) > 1 and not 0 <= gap[0] < gap[1]:
        raise CalibrationError("the range of the gaps needs a low of at least 0, below its high")
    means = [region_mean(temp_file, pop_file, cell) for cell in cells]
    return {"cells": cells, "first": first, "gap": gap, "means": means, "ordered": ordered}


def _in_folder(folder, path):
    """A path of the record: as it is if absolute, else within the folder of the calibration. Other values (no file: "",
    "NONE", a number) as they are."""
    if not isinstance(path, str) or path.strip() in ("", "NONE") or Path(path).is_absolute():
        return path
    return str(Path(folder).resolve() / path)


def resolved(folder, record):
    """The record with the paths of its observations within its folder when they are relative (calibration sent to a cluster)."""
    return {**record, "objectives": [{**objective, **{key: _in_folder(folder, objective[key]) for key in ("data", "data_raw")
                                                      if objective.get(key)}} for objective in record["objectives"]]}


def setup_config(folder, record, mobile=None):
    """The configuration of the runs of a calibration, before the values of a trial. mobile: the MoBILE clone, else that of
    the record if it exists, else $MOBILE."""
    setup = record["setup"]
    if mobile is None:
        mobile = os.path.expandvars(setup["mobile"] or "")
        if not (mobile and Path(mobile).is_dir()) and os.environ.get("MOBILE"):
            mobile = os.environ["MOBILE"]
    inputs = {key: _in_folder(folder, path) for key, path in setup["inputs"].items()}
    config = from_fields(mobile, setup["project"], setup["runs_dir"], setup["run"], inputs, None,
                         setup["period"], setup["age_structure"])
    return replace(config, inputs={key: _in_folder(folder, path) for key, path in record["run_inputs"].items()},
                   params=dict(record["params"]), output=tuple(record["output"]) if record["output"] is not None else None)


# ---------------------------------------------------------------- a trial

def suggest(trial, record):
    """{parameter: value in the units of the sliders} and {dT name: offset} of a trial."""
    values = {}
    for parameter in record["parameters"]:
        values[parameter["name"]] = trial.suggest_float(parameter["name"], parameter["low"], parameter["high"],
                                                        log=parameter["distribution"] == "loguniform")
    offsets = {}
    temperature = record["temperature"]
    if temperature and not temperature.get("ordered", True):
        # Each cell or region on its own, within the same range: no order kept
        offsets = offsets_from(temperature, {f"dT_{k}": trial.suggest_float(f"dT_{k}", *temperature["first"])
                                             for k in range(1, len(temperature["cells"]) + 1)})
    elif temperature:
        sampled = {"dT_1": trial.suggest_float("dT_1", *temperature["first"])}
        for k in range(2, len(temperature["cells"]) + 1):
            sampled[f"gap_{k}"] = trial.suggest_float(f"gap_{k}", *temperature["gap"])
        offsets = offsets_from(temperature, sampled)
    return values, offsets


def objective_series(objective, run_dirs, validation=None, part=None):
    """(model, data) of an objective for the runs of a trial (one per seed). With the raw observations and their steps
    (objectives made since: data_raw, data_steps), both are first cut to the period they share, then each processed by
    its own steps (calibration_model.process_both), so that e.g. a climatology covers the same years on both sides. With
    only the observations as processed (earlier objectives), those, and the model output processed by its steps (for
    several seeds, the median of the seeds each processed). validation and part as for process_both: with a validation
    window, part "calibration" leaves it out, "validation" keeps it only."""
    members = [member for run_dir in run_dirs
               for member in model_members(run_dir, objective["variable"], objective["space"], None, objective["aggregation"])]
    if objective.get("data_raw"):
        model, data, _ = process_both(members, objective["steps"], read_observations(objective["data_raw"]),
                                      objective.get("data_steps", []), validation=validation, part=part)
        return model, data
    model = apply_steps(members[0], objective["steps"]) if len(members) == 1 else seed_spread(members, objective["steps"])
    return model, read_observations(objective["data"])


def _series_files(folder, index, part):
    """(model, observations) files of objective `index` and a part of the period (None for the whole) kept in a folder."""
    name = f"objective_{index}_{part or 'whole'}"
    return Path(folder) / f"{name}_model.nc", Path(folder) / f"{name}_data.nc"


def _touched(path):
    """The path, with an empty file there: netCDF then writes it from a thread without HDF5 printing the error of looking for
    one (as it does when it does not exist), which would fill the log of a batch job."""
    Path(path).touch()
    return path


def _keep(folder, index, part, model, data):
    Path(folder).mkdir(parents=True, exist_ok=True)
    for series, path in zip((model, data), _series_files(folder, index, part)):
        write_observations(series, _touched(path))


def keep_series(objectives, run_dirs, folder, validation=None, part=None):
    """Keep in a folder the model and the observations of each objective as compared, for a part of the period (None for
    the whole), for the plots of a trial without its output. One that cannot be had is left out."""
    for index, objective in enumerate(objectives):
        try:
            _keep(folder, index, part, *objective_series(objective, run_dirs, validation, part))
        except DataError:
            continue


def evaluate(objectives, run_dirs, validation=None, part=None, strict=True, keep=None):
    """[value of each objective] of the runs of a trial (one per seed): the output and the observations as
    objective_series gives them (with a validation window: the part of the period, "calibration" or "validation"), paired
    and compared by the metric of the objective. Not strict, None for a value that cannot be had instead of an error.
    keep: a folder to keep the series compared in (keep_series)."""
    results = []
    for index, objective in enumerate(objectives):
        try:
            model, data = objective_series(objective, run_dirs, validation, part)
            if keep is not None:
                _keep(keep, index, part, model, data)
            model_values, data_values, _ = pair(model, data)
            value = metrics(model_values, data_values)[objective["metric"]]
            if value is None:
                raise DataError(f"{objective['name']}: {objective['metric']} is not defined for these values (e.g. a flat series)")
        except DataError:
            if strict:
                raise
            results.append(None)
            continue
        results.append(abs(value) if objective["direction"] == "zero" else value)
    return results


def trial_folder(folder, number):
    return Path(folder) / TRIALS / f"trial_{number:05d}"


# ---------------------------------------------------------------- running

def sampler_for(record):
    sampler = record["sampler"]
    if sampler["name"] == "tpe":
        return optuna.samplers.TPESampler(multivariate=True, constant_liar=True, n_startup_trials=sampler["startup_trials"],
                                          seed=sampler["seed"])
    if sampler["name"] == "nsga2":
        return optuna.samplers.NSGAIISampler(seed=sampler["seed"])
    return optuna.samplers.RandomSampler(seed=sampler["seed"])


_STORAGES = {}  # One connection to the database of each calibration in this process, shared by its readers and its run
_STORAGES_LOCK = threading.Lock()


def _storage(folder):
    path = str((Path(folder) / DATABASE).resolve())
    with _STORAGES_LOCK:
        if path not in _STORAGES:
            _STORAGES[path] = optuna.storages.RDBStorage(f"sqlite:///{path}", engine_kwargs={"connect_args": {"timeout": 60}})
        return _STORAGES[path]


def forget_storage(folder):
    """Close the connections to the study of a folder, e.g. after its database was replaced by a newer copy."""
    path = str((Path(folder) / DATABASE).resolve())
    with _STORAGES_LOCK:
        storage = _STORAGES.pop(path, None)
    if storage is not None:
        storage.engine.dispose()


def open_study(folder, record):
    storage = _storage(folder)
    directions = ["maximize" if objective["direction"] == "maximize" else "minimize" for objective in record["objectives"]]
    return optuna.create_study(study_name=STUDY_NAME, storage=storage, directions=directions, sampler=sampler_for(record),
                               load_if_exists=True)


def counts(study):
    """(completed, failed) trials; trials cancelled with the calibration do not count."""
    trials = study.get_trials(deepcopy=False)
    completed = sum(trial.state == optuna.trial.TrialState.COMPLETE for trial in trials)
    failed = sum(trial.state == optuna.trial.TrialState.FAIL and not trial.user_attrs.get("cancelled") for trial in trials)
    return completed, failed


def run_calibration(folder, state, parallel=1, threads=None, deadline=None, trial_seconds=None, on_trial=None, mobile=None):
    """Run the trials of a calibration until as many have completed as it asks for, parallel at a time, and return its
    record. A trial that fails is made up for by another.

    deadline: time (seconds since the epoch) by which the trials must have ended, e.g. before the end of a batch job: a
    trial is not started if the time trials take (EXPECTED_FROM) would take it past the deadline, or past then if fewer have
    completed, the longest of them and trial_seconds. on_trial(study, trial) is called after each trial. mobile: the MoBILE
    clone, as for setup_config.

    The status is finished when the trials asked for have completed; stopped if the first FAIL_FAST trials all failed, or
    more than CRASH_RATE of them (the record then holds the end of the log of a run, as failure); "stopped at deadline";
    cancelled; or incomplete. Raises CalibrationError if another process runs it (is_running)."""
    folder = Path(folder)
    record = read_calibration(folder)
    if not resumable(record):
        raise CalibrationError(OLD_CALIBRATION)
    cluster = read_cluster(folder)
    if cluster is not None:
        raise CalibrationError(f"this calibration was sent to {cluster.get('host')} ({cluster.get('folder')}): it runs there. "
                               "Refresh to see how far it is, and submit a job there to go on.")
    if is_running(folder):
        raise CalibrationError(f"this calibration is running already: {running_where(folder)}")
    with open(folder / LOCK, "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise CalibrationError("this calibration is running already, in this or another process") from None
        except OSError:
            pass  # A file system without locks, e.g. some of clusters: the status file tells
        return _run_locked(folder, record, state, parallel, threads, deadline, trial_seconds, on_trial, mobile)


def _now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def _seconds_since(stamp):
    try:
        return time.time() - datetime.datetime.fromisoformat(stamp).timestamp()
    except (TypeError, ValueError):
        return math.inf


def read_status(folder):
    """The status file of a calibration ({job, host, pid, started, heartbeat, state, completed, failed, target, deadline}),
    or None if it has none (never run, or made by an earlier version) or it cannot be read."""
    try:
        status = json.loads((Path(folder) / STATUS).read_text())
    except (OSError, ValueError):
        return None
    return status if isinstance(status, dict) else None


def _write_atomic(path, text):
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}")
    temporary.write_text(text)
    os.replace(temporary, path)


def _locked(folder):
    """Whether a process on this computer holds the lock of the calibration; None if this file system has no locks."""
    path = Path(folder) / LOCK
    if not path.exists():
        return False
    with open(path, "a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        except OSError:
            return None
        fcntl.flock(lock, fcntl.LOCK_UN)
        return False


def _alive(pid):
    try:
        os.kill(int(pid), 0)
    except (TypeError, ValueError, ProcessLookupError):
        return False
    except PermissionError:
        return True
    return True


_SQUEUE_CACHE = {}  # {job: (time asked, listed)}, not to ask Slurm every few seconds
_SQUEUE_SECONDS = 20


def in_squeue(job):
    """Whether Slurm still lists the job (queued or running); None if it cannot be asked here."""
    if not job or shutil.which("squeue") is None:
        return None
    asked, listed = _SQUEUE_CACHE.get(str(job), (0, None))
    if time.time() - asked < _SQUEUE_SECONDS:
        return listed
    try:
        result = subprocess.run(["squeue", "-h", "-j", str(job), "-o", "%A"], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode == 0:
        listed = bool(result.stdout.strip())
    elif "invalid job id" in result.stderr.lower():
        listed = False  # Ended long enough ago that Slurm forgot it
    else:
        return None  # e.g. the controller did not answer: not a reason to take over
    _SQUEUE_CACHE[str(job)] = (time.time(), listed)
    return listed


def read_cluster(folder):
    """{host, folder, sent, jobs: [{id, submitted, state, listed}], refreshed} of a calibration sent to a cluster (the local
    folder then mirrors the one there), or None."""
    try:
        cluster = json.loads((Path(folder) / CLUSTER).read_text())
    except (OSError, ValueError):
        return None
    return cluster if isinstance(cluster, dict) else None


def cluster_state(cluster):
    """'running' or 'queued' if the last refresh saw a job of the calibration so in Slurm, else None."""
    states = {job.get("state") for job in cluster.get("jobs", []) if job.get("listed")}
    return "running" if states & {"RUNNING", "COMPLETING"} else "queued" if states else None


def is_running(folder):
    """Whether a process runs the calibration now, in this one or another, on this computer or another.

    Sent to a cluster: whether the last refresh saw one of its jobs in Slurm, queued or running.

    By its status file: on this computer, the process holds the lock of the calibration (or, without locks, is alive); on
    another, Slurm still lists its job, or, where Slurm cannot be asked, it wrote the status less than STALE_SECONDS ago.
    Without a status file (calibrations of an earlier version), by the lock."""
    cluster = read_cluster(folder)
    if cluster is not None:
        return cluster_state(cluster) is not None
    status = read_status(folder)
    if status is None:
        return _locked(folder) is True
    if status.get("state") != "running":
        return False
    if status.get("host") == socket.gethostname():
        if status.get("job") and status.get("job") == os.environ.get("SLURM_JOB_ID"):
            return False  # This very job, started again (requeued): what it ran before has ended
        held = _locked(folder)
        return _alive(status.get("pid")) if held is None else held
    listed = in_squeue(status.get("job"))
    if listed is not None:
        return listed
    return _seconds_since(status.get("heartbeat")) < STALE_SECONDS


def running_where(folder):
    """e.g. 'job 123 on lrdn0042, last heard of 40 s ago, 17 of 100 trials completed', from its status file; for one sent
    to a cluster, as of the last refresh."""
    cluster = read_cluster(folder)
    status = read_status(folder) or {}
    if cluster is not None:
        jobs = [job for job in cluster.get("jobs", []) if job.get("listed")]
        parts = [f"on {cluster.get('host')}"] + [f"job {job['id']} {job.get('state', '').lower()}" for job in jobs]
        if status.get("target"):
            parts.append(f"{status.get('completed', 0)} of {status['target']} trials completed")
        refreshed = _seconds_since(cluster.get("refreshed"))
        if math.isfinite(refreshed):
            heard = _seconds_since(status.get("heartbeat")) - refreshed
            if jobs and math.isfinite(heard):
                parts.append(f"last heard of {_clock(heard)} before")
            parts.append(f"as of the refresh {_clock(refreshed)} ago")
        return ", ".join(parts)
    parts = [f"job {status['job']} on {status.get('host')}" if status.get("job") else f"process {status.get('pid')} on {status.get('host')}"]
    since = _seconds_since(status.get("heartbeat"))
    if math.isfinite(since):
        parts.append(f"last heard of {_clock(since)} ago")
    if status.get("target"):
        parts.append(f"{status.get('completed', 0)} of {status['target']} trials completed")
    return ", ".join(parts) if status else "in this or another process"


def _clock(seconds):
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds} s"
    if seconds < 3600:
        return f"{seconds // 60} min"
    return f"{seconds // 3600} h {seconds % 3600 // 60:02d} min"


class _Status:
    """The status file of a calibration while this process runs it: written at the start, after every trial, every
    HEARTBEAT_SECONDS from a thread of its own, and at the end; with a snapshot of the study (SNAPSHOT_SECONDS)."""

    def __init__(self, folder, target, deadline):
        self.folder, self.lock, self.snapshot_at = Path(folder), threading.Lock(), 0.0
        self.fields = {"job": os.environ.get("SLURM_JOB_ID"), "host": socket.gethostname(), "pid": os.getpid(), "started": _now(),
                       "heartbeat": None, "state": "running", "completed": 0, "failed": 0, "target": target,
                       "deadline": datetime.datetime.fromtimestamp(deadline, datetime.timezone.utc).isoformat(timespec="seconds")
                       if deadline else None}
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._beat, daemon=True)

    def start(self, **fields):
        self.write(**fields)
        self.thread.start()

    def _beat(self):
        while not self.stop.wait(HEARTBEAT_SECONDS):
            try:
                self.write()
            except OSError:
                pass  # e.g. the file system briefly away: the next beat tries again

    def write(self, snapshot=False, **fields):
        with self.lock:
            self.fields.update(fields, heartbeat=_now())
            _write_atomic(self.folder / STATUS, json.dumps(self.fields, indent=1) + "\n")
            if snapshot or time.time() - self.snapshot_at >= SNAPSHOT_SECONDS:
                self.snapshot_at = time.time()
                self._snapshot()

    def _snapshot(self):
        """A consistent copy of the study, which can be copied away while the trials write theirs (SQLite backup)."""
        target = self.folder / f".{SNAPSHOT}.{os.getpid()}"
        try:
            source, copy = sqlite3.connect(self.folder / DATABASE, timeout=60), sqlite3.connect(target)
            try:
                source.backup(copy)
            finally:
                source.close()
                copy.close()
            os.replace(target, self.folder / SNAPSHOT)
        except sqlite3.Error:
            target.unlink(missing_ok=True)

    def end(self, **fields):
        self.stop.set()
        if self.thread.is_alive():
            self.thread.join()
        self.write(snapshot=True, **fields)


def _expected_seconds(study, guess):
    """How long a trial takes: the 95th percentile of the completed ones once there are EXPECTED_FROM, else the longest of
    them and the guess (None if there is neither)."""
    seconds = [(trial.datetime_complete - trial.datetime_start).total_seconds()
               for trial in study.get_trials(deepcopy=False, states=(optuna.trial.TrialState.COMPLETE,))
               if trial.datetime_complete and trial.datetime_start]
    if len(seconds) >= EXPECTED_FROM:
        return float(np.percentile(seconds, 95))
    known = [value for value in (*seconds, guess) if value]
    return max(known) if known else None


def _run_locked(folder, record, state, parallel, threads, deadline=None, trial_seconds=None, on_trial=None, mobile=None):
    config = setup_config(folder, record, mobile)
    if threads:
        config = replace(config, run={**config.run, "threads": threads})
    config.validate()
    objectives = resolved(folder, record)["objectives"]
    study = open_study(folder, record)
    for trial in study.get_trials(deepcopy=False, states=(optuna.trial.TrialState.RUNNING,)):
        # Left running by a process that ended without finishing it, e.g. the GUI closed or a job killed: done again, and
        # not counted as a failure
        study._storage.set_trial_user_attr(trial._trial_id, "cancelled", True)
        study._storage.set_trial_user_attr(trial._trial_id, "ended", "the process running it ended")
        study._storage.set_trial_state_values(trial._trial_id, optuna.trial.TrialState.FAIL)
    queued = False
    if record.get("temperature") and not study.get_trials(deepcopy=False):
        # The first trial has no offset (the temperatures of the file), if the ranges allow it: where the calibration starts
        # from. Its output is processed and scored as every trial's.
        start = baseline(record["temperature"])
        if start is not None:
            study.enqueue_trial(start, user_attrs={"baseline": True})
            queued = True
    target = record["n_trials"]
    completed, failed_before = counts(study)
    crash_limit = max(FAIL_FAST, CRASH_RATE * target)
    state.begin(target, completed)
    write_calibration(folder, {**record, "status": "running"})
    status = _Status(folder, target, deadline)
    status.start(completed=completed, failed=failed_before)
    at_deadline = threading.Event()

    def record_model(binary):
        with state.lock:
            write_calibration(folder, {**read_calibration(folder), "binary_md5": _md5(binary)})

    once = BuildOnce(folder / BINARY, record_model)

    def run_seed(trial, run_config, seed):
        """The run folder of a seed of the trial, finished; raises TrialFailed, or RunCancelled."""
        name = f"seed_{seed}"
        result = None
        for _ in range(ATTEMPTS):
            run_dir = run_config.runs_dir / name
            if run_dir.exists():
                shutil.rmtree(run_dir)  # Left by a failed attempt
            prebuilt = once.acquire(lambda: state.cancelled)
            if prebuilt is False:
                raise RunCancelled("Cancelled while the model was built")
            runner = Runner(replace(run_config, run={**run_config.run, "seed": seed}), prebuilt)
            if not state.add_runner(runner):
                if prebuilt is None:
                    once.release()
                raise RunCancelled("Cancelled")
            try:
                result = runner.run(name, wait=True, on_built=once.keep if prebuilt is None else None)
            finally:
                state.remove_runner(runner)
                if prebuilt is None:
                    once.release()
            if result.status == "cancelled":
                raise RunCancelled("Cancelled")
            if result.ok:
                return result.run_dir
        raise TrialFailed(result.log_tail(15))

    def not_started(trial, why):
        trial.set_user_attr("cancelled", True)
        trial.set_user_attr("ended", why)
        study.stop()
        raise RunCancelled(why)

    def objective(trial):
        if state.cancelled:
            trial.set_user_attr("cancelled", True)
            raise RunCancelled("Cancelled")
        if at_deadline.is_set():
            not_started(trial, "not started: the deadline was near")
        others = study.get_trials(deepcopy=False, states=(optuna.trial.TrialState.COMPLETE, optuna.trial.TrialState.RUNNING))
        if len(others) - 1 >= target:  # Without this one: enough trials have completed or are running
            not_started(trial, "not started: enough trials")
        if deadline is not None:
            expected = _expected_seconds(study, trial_seconds)
            if time.time() + (expected or 0) > deadline:
                at_deadline.set()
                not_started(trial, "not started: the deadline was near")
        values, offsets = suggest(trial, record)
        here = trial_folder(folder, trial.number)
        here.mkdir(parents=True, exist_ok=True)
        inputs = dict(config.inputs)
        if offsets:
            temperature = record["temperature"]
            target_file = here / "t2m.nc"
            with NETCDF_LOCK:
                offset_temperature(config.inputs["temp_file"], _touched(target_file), temperature["cells"], offsets)
            inputs["temp_file"] = str(target_file)
            for key, offset in offsets.items():
                trial.set_user_attr(key, offset)
        run_config = replace(config, runs_dir=here, inputs=inputs,
                             # Sampled in the units shown on the sliders, written in those of the model
                             params={**config.params, **{name: to_model(name, float(value)) for name, value in values.items()}})
        try:
            run_dirs = [run_seed(trial, run_config, seed) for seed in record["seeds"]]
            with NETCDF_LOCK:
                window = record.get("validation")
                kept = here / SERIES
                results = evaluate(objectives, run_dirs, window, "calibration" if window else None, keep=kept)
                if window:  # Scored on the validation window too, kept with the trial; not optimised
                    trial.set_user_attr("validation", evaluate(objectives, run_dirs, window, "validation", strict=False, keep=kept))
                    keep_series(objectives, run_dirs, kept, window, None)  # The whole period too, for the plots
        except RunCancelled:
            trial.set_user_attr("cancelled", True)
            raise
        except (TrialFailed, DataError) as error:
            trial.set_user_attr("failure", str(error)[-2000:])
            state.count("failed")
            with state.lock:
                state.failure = state.failure or str(error)
                systematic = state.failed >= FAIL_FAST and state.done == state.done_before
                crashing = failed_before + state.failed > crash_limit
            if systematic or crashing:
                state.update(message="stopped")
                state.cancel()
            raise TrialFailed(str(error)) from None
        state.count("done")
        return results

    def after_trial(study, trial):
        done, failed = counts(study)
        try:
            status.write(completed=done, failed=failed)
        except OSError:
            pass
        if on_trial is not None:
            try:
                on_trial(study, trial)
            except Exception:  # noqa: BLE001 - a report must not stop the calibration
                pass
        enough = len(study.get_trials(deepcopy=False, states=(optuna.trial.TrialState.COMPLETE, optuna.trial.TrialState.RUNNING)))
        if state.cancelled or at_deadline.is_set() or enough >= target:
            study.stop()

    state.update(message="Running")
    catch = (TrialFailed, RunCancelled)
    try:
        while not (state.cancelled or at_deadline.is_set()):
            completed, _ = counts(study)
            if completed >= target:
                break
            if queued:
                # The queued trial on its own: Optuna takes a queued trial with a row lock, which SQLite does not have, so
                # trials run side by side could both take it (it is the run that builds the model, which the others would
                # wait for anyway)
                study.optimize(objective, n_trials=1, n_jobs=1, catch=catch, callbacks=[after_trial], gc_after_trial=False)
                queued = False
                continue
            before = len(study.get_trials(deepcopy=False))
            # Until enough have completed or run; then once more if some of those running failed
            study.optimize(objective, n_trials=None, n_jobs=max(1, parallel), catch=catch, callbacks=[after_trial],
                           gc_after_trial=False)
            if len(study.get_trials(deepcopy=False)) == before:
                break
    finally:
        completed, failed = counts(study)
        if state.message == "stopped":
            outcome = "stopped"
        elif completed >= target:
            outcome = "finished"
        elif at_deadline.is_set():
            outcome = "stopped at deadline"
        else:
            outcome = "cancelled" if state.cancelled else "incomplete"
        record = {**read_calibration(folder), "status": outcome, "completed": completed, "failed": failed, "failure": state.failure}
        write_calibration(folder, record)
        status.end(state=outcome, completed=completed, failed=failed)
    state.update(message=outcome)
    return record


# ---------------------------------------------------------------- results

def trials_table(folder):
    """[{number, state, values, params, offsets, seconds}] of the trials of a calibration, in order."""
    record = read_calibration(folder)
    study = open_study(folder, record)
    rows = []
    for trial in study.get_trials(deepcopy=False):
        offsets = {key: value for key, value in trial.user_attrs.items() if key.startswith("dT_")}
        seconds = (trial.datetime_complete - trial.datetime_start).total_seconds() if trial.datetime_complete and trial.datetime_start else None
        rows.append({"number": trial.number, "state": trial.state.name, "values": trial.values, "params": dict(trial.params),
                     "offsets": offsets, "seconds": seconds, "failure": trial.user_attrs.get("failure"),
                     "baseline": bool(trial.user_attrs.get("baseline")), "validation": trial.user_attrs.get("validation")})
    return rows


def trial_comparison(folder, number, index=0, part=None):
    """(model, data, model values, data values, labels) of objective `index` for a completed trial: its runs processed
    as the objective says, and the observations, paired as for the metrics. With a validation window, part "calibration"
    or "validation" for one part of the period, None for the whole period the model and the data share."""
    record = read_calibration(folder)
    objective = resolved(folder, record)["objectives"][index]
    here = trial_folder(folder, number)
    run_dirs = [here / f"seed_{seed}" for seed in record["seeds"]]
    files = _series_files(here / SERIES, index, part if record.get("validation") else None)
    with NETCDF_LOCK:
        if all(path.is_file() for path in files):  # Kept with the trial: drawn without its output
            model, data = (read_observations(path) for path in files)
        else:
            model, data = objective_series(objective, run_dirs, record.get("validation"), part)
    model_values, data_values, labels = pair(model, data)
    return model, data, model_values, data_values, labels


def resumable(record):
    """Whether a calibration was made by this version of the engine, and so can be run further."""
    return record.get("version") == VERSION


def status_of(folder, record):
    """The status of a calibration as it is now: 'interrupted' for one recorded as running that no process runs any more,
    e.g. after the GUI was closed or crashed."""
    status = record.get("status", "?")
    cluster = read_cluster(folder)
    if cluster is not None:
        return cluster_state(cluster) or ("interrupted" if status == "running" else status)
    return "interrupted" if status == "running" and not is_running(folder) else status


def calibration_label(folder, record):
    """e.g. 'dz_two_cells (finished, 100 of 100 trials completed, 2 objectives)'; '..., earlier version' if it cannot be resumed."""
    done = record.get("completed", 0)
    return (f"{Path(folder).name} ({status_of(folder, record)}, {done} of {record['n_trials']} trials completed, "
            f"{len(record['objectives'])} objective{'s' if len(record['objectives']) > 1 else ''}"
            f"{'' if resumable(record) else ', earlier version: cannot be resumed'})")


def best_trials(folder):
    """The trials on the Pareto front (for one objective, the best), as rows of trials_table."""
    record = read_calibration(folder)
    study = open_study(folder, record)
    numbers = {trial.number for trial in study.best_trials}
    return [row for row in trials_table(folder) if row["number"] in numbers]


def list_calibrations(runs_dir):
    """{folder: record} of the calibrations in a results folder, the newest first."""
    found = {}
    root = calibrations_dir(runs_dir)
    for folder in root.iterdir() if root.is_dir() else []:
        try:
            found[str(folder)] = read_calibration(folder)
        except (OSError, json.JSONDecodeError):
            continue
    return dict(sorted(found.items(), key=lambda item: item[1].get("date", ""), reverse=True))

