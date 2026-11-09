"""A calibration on disk, run with Optuna: <results folder>/calibration/<name>/ holds

  calibration.json  what is calibrated, against what, with which setup, sampler and number of trials
  optuna.db         the Optuna study (SQLite): every trial, its values and objectives; a calibration resumes from it
  inputs/           the driving files cut to the region and period of the setup, once for all the trials
  bin/mobile.out    the model, built by the first run and run as it is by all the others (mobile.sh -E)
  trials/trial_<n>/ one folder per trial: its temperature file, if offset, and a run folder per seed

A trial samples the parameters, runs the model for each seed, processes the output as each objective says and compares
it with the observations of the objective: the values of the metrics are the objectives Optuna optimises.

Temperature offsets (dT) shift the temperature of chosen cells, e.g. to stand for the temperature where people live
within a coarse cell. The cells are given from the coolest to the warmest, as they must stay: the first gets an offset
dT_1, and each next one a gap of at least 0 above the one before (in the means over the simulated period), so that
the order of their temperatures holds in every trial without any trial being wasted.
"""

import datetime
import json
import shutil
from dataclasses import replace
from pathlib import Path

import netCDF4
import numpy as np
import optuna

from .calibration_data import DataError, read_observations
from .calibration_metrics import DIRECTIONS, pair, metrics
from .calibration_model import SPACES, model_members, seed_spread
from .calibration_steps import apply_steps
from .config import MAX_PATH_LENGTH, ConfigError
from .driving import LAT_NAMES, LON_NAMES, TEMP_NAMES, first_name
from .grid import pop_coordinates
from .parameters import to_model
from .region import cut_inputs
from .results import _md5
from .rundir import new_run_id, period_steps
from .runner import NETCDF_LOCK, BuildOnce, RunCancelled, Runner
from .setup import from_fields, to_dict

FOLDER = "calibration"
RECORD = "calibration.json"
DATABASE = "optuna.db"
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
    """{dT name: offset} of each cell from the sampled values: dT_1 for the first (coolest) cell, and for each next one
    the gap above the one before, in their means: mean_k + dT_k = mean_(k-1) + dT_(k-1) + gap_k."""
    cells, means = temperature["cells"], temperature["means"]
    offsets = [values["dT_1"]]
    for k in range(1, len(cells)):
        offsets.append(means[k - 1] + offsets[k - 1] + values[f"gap_{k + 1}"] - means[k])
    return {f"dT_{k + 1}": offset for k, offset in enumerate(offsets)}


def offset_temperature(source, target, cells, offsets):
    """Write a copy of the temperature file with each cell shifted by its offset (°C), the others as they are."""
    shutil.copyfile(source, target)
    with netCDF4.Dataset(target, "a") as data:
        lat, lon = _coordinates(data)
        field = data[first_name(TEMP_NAMES, data.variables)]
        for k, cell in enumerate(cells):
            i, j = _cell(lat, lon, cell)
            field[:, i, j] = field[:, i, j] + offsets[f"dT_{k + 1}"]
        data.mobile_offsets = json.dumps({f"{cell['lat']},{cell['lon']}": round(offsets[f"dT_{k + 1}"], 6)
                                          for k, cell in enumerate(cells)})


# ---------------------------------------------------------------- creating

def create_calibration(config, objectives, parameters=(), temperature=None, seeds=(12345,), n_trials=100,
                       sampler="tpe", startup_trials=10, sampler_seed=1, name=None):
    """Write the folder of a new calibration and return it.

    config: the setup, with the parameters not calibrated and the outputs the objectives need.
    objectives: [{name, data (observations file), variable, space, aggregation, steps (applied to the model output),
    metric}]; each is minimised or maximised as its metric says (calibration_metrics.DIRECTIONS).
    parameters: SampledParameter of the model to calibrate (uniform or log-uniform), in the units of the sliders.
    temperature: {cells: [{lat, lon}] from the coolest to the warmest, first: (low, high) of dT_1 in °C, gap: (low,
    high) of each next gap, low at least 0}, or None."""
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
            temperature = _temperature(temperature, run_inputs["temp_file"])
    except (ConfigError, CalibrationError, DataError):
        shutil.rmtree(folder)
        raise
    record = {
        "status": "created",
        "date": datetime.datetime.now().isoformat(timespec="seconds"),
        "setup": to_dict(config),
        "params": {key: float(value) for key, value in config.params.items()},
        "output": list(config.output) if config.output is not None else None,
        "run_inputs": run_inputs,
        "parameters": [{"name": p.name, "distribution": p.distribution, "low": p.low, "high": p.high} for p in parameters],
        "temperature": temperature,
        "objectives": [{"space": "people", "aggregation": None, "steps": [], **objective, "data": str(Path(objective["data"]).resolve()),
                        "direction": DIRECTIONS[objective["metric"]]} for objective in objectives],
        "seeds": [int(seed) for seed in seeds],
        "n_trials": int(n_trials),
        "sampler": {"name": sampler, "startup_trials": int(startup_trials), "seed": sampler_seed},
        "completed": 0,
        "failed": 0,
    }
    write_calibration(folder, record)
    return folder


def _temperature(temperature, temp_file):
    cells = [{"lat": float(cell["lat"]), "lon": float(cell["lon"])} for cell in temperature["cells"]]
    first, gap = [float(value) for value in temperature["first"]], [float(value) for value in temperature.get("gap", (0, 0))]
    if first[0] >= first[1]:
        raise CalibrationError("the range of dT_1 needs its low below its high")
    if len(cells) > 1 and not 0 <= gap[0] < gap[1]:
        raise CalibrationError("the range of the gaps needs a low of at least 0, below its high")
    means = cell_means(temp_file, cells)
    return {"cells": cells, "first": first, "gap": gap, "means": means}


def setup_config(folder, record):
    """The configuration of the runs of a calibration, before the values of a trial."""
    setup = record["setup"]
    config = from_fields(setup["mobile"], setup["project"], setup["runs_dir"], setup["run"], setup["inputs"], None,
                         setup["period"], setup["age_structure"])
    return replace(config, inputs=dict(record["run_inputs"]), params=dict(record["params"]),
                   output=tuple(record["output"]) if record["output"] is not None else None)


# ---------------------------------------------------------------- a trial

def suggest(trial, record):
    """{parameter: value in the units of the sliders} and {dT name: offset} of a trial."""
    values = {}
    for parameter in record["parameters"]:
        values[parameter["name"]] = trial.suggest_float(parameter["name"], parameter["low"], parameter["high"],
                                                        log=parameter["distribution"] == "loguniform")
    offsets = {}
    temperature = record["temperature"]
    if temperature:
        sampled = {"dT_1": trial.suggest_float("dT_1", *temperature["first"])}
        for k in range(2, len(temperature["cells"]) + 1):
            sampled[f"gap_{k}"] = trial.suggest_float(f"gap_{k}", *temperature["gap"])
        offsets = offsets_from(temperature, sampled)
    return values, offsets


def evaluate(objectives, run_dirs):
    """[value of each objective] of the runs of a trial (one per seed): the output processed by the steps of the
    objective (for several seeds, the median of the seeds each processed), compared with its observations."""
    results = []
    for objective in objectives:
        members = [member for run_dir in run_dirs
                   for member in model_members(run_dir, objective["variable"], objective["space"], None, objective["aggregation"])]
        model = (apply_steps(members[0], objective["steps"]) if len(members) == 1
                 else seed_spread(members, objective["steps"]))
        data = read_observations(objective["data"])
        model_values, data_values, _ = pair(model, data)
        value = metrics(model_values, data_values)[objective["metric"]]
        if value is None:
            raise DataError(f"{objective['name']}: {objective['metric']} is not defined for these values (e.g. a flat series)")
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


def open_study(folder, record):
    storage = optuna.storages.RDBStorage(f"sqlite:///{Path(folder) / DATABASE}", engine_kwargs={"connect_args": {"timeout": 60}})
    directions = ["maximize" if objective["direction"] == "maximize" else "minimize" for objective in record["objectives"]]
    return optuna.create_study(study_name=STUDY_NAME, storage=storage, directions=directions, sampler=sampler_for(record),
                               load_if_exists=True)


def counts(study):
    """(completed, failed) trials; trials cancelled with the calibration do not count."""
    trials = study.get_trials(deepcopy=False)
    completed = sum(trial.state == optuna.trial.TrialState.COMPLETE for trial in trials)
    failed = sum(trial.state == optuna.trial.TrialState.FAIL and not trial.user_attrs.get("cancelled") for trial in trials)
    return completed, failed


def run_calibration(folder, state, parallel=1, threads=None):
    """Run the trials of a calibration not yet done, parallel at a time, and return its record.

    The status is finished when the trials asked for are done, cancelled, or stopped if the first FAIL_FAST trials
    all failed (the record then holds the end of the log of a run, as failure)."""
    folder = Path(folder)
    record = read_calibration(folder)
    config = setup_config(folder, record)
    if threads:
        config = replace(config, run={**config.run, "threads": threads})
    config.validate()
    study = open_study(folder, record)
    for trial in study.get_trials(deepcopy=False, states=(optuna.trial.TrialState.RUNNING,)):
        # Left running by a calibration that stopped without finishing it, e.g. the GUI closed: done again
        study._storage.set_trial_user_attr(trial._trial_id, "cancelled", True)
        study._storage.set_trial_state_values(trial._trial_id, optuna.trial.TrialState.FAIL)
    completed, failed = counts(study)
    todo = max(record["n_trials"] - completed - failed, 0)
    state.begin(record["n_trials"], completed + failed)
    write_calibration(folder, {**record, "status": "running"})

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

    def objective(trial):
        if state.cancelled:
            trial.set_user_attr("cancelled", True)
            raise RunCancelled("Cancelled")
        values, offsets = suggest(trial, record)
        here = trial_folder(folder, trial.number)
        here.mkdir(parents=True, exist_ok=True)
        inputs = dict(config.inputs)
        if offsets:
            temperature = record["temperature"]
            target = here / "t2m.nc"
            with NETCDF_LOCK:
                offset_temperature(config.inputs["temp_file"], target, temperature["cells"], offsets)
            inputs["temp_file"] = str(target)
            for key, offset in offsets.items():
                trial.set_user_attr(key, offset)
        run_config = replace(config, runs_dir=here, inputs=inputs,
                             # Sampled in the units shown on the sliders, written in those of the model
                             params={**config.params, **{name: to_model(name, float(value)) for name, value in values.items()}})
        try:
            run_dirs = [run_seed(trial, run_config, seed) for seed in record["seeds"]]
            with NETCDF_LOCK:
                results = evaluate(record["objectives"], run_dirs)
        except RunCancelled:
            trial.set_user_attr("cancelled", True)
            raise
        except (TrialFailed, DataError) as error:
            trial.set_user_attr("failure", str(error)[-2000:])
            state.count("failed")
            with state.lock:
                state.failure = state.failure or str(error)
                systematic = state.failed >= FAIL_FAST and state.done == state.done_before
            if systematic:
                state.update(message="stopped")
                state.cancel()
            raise TrialFailed(str(error)) from None
        state.count("done")
        return results

    def stop_when_cancelled(study, _trial):
        if state.cancelled:
            study.stop()

    state.update(message="Running")
    if todo:
        study.optimize(objective, n_trials=todo, n_jobs=max(1, parallel), catch=(TrialFailed, RunCancelled),
                       callbacks=[stop_when_cancelled], gc_after_trial=False)
    completed, failed = counts(study)
    if state.message == "stopped":
        status = "stopped"
    elif completed + failed >= record["n_trials"]:
        status = "finished"
    else:
        status = "cancelled" if state.cancelled else "incomplete"
    record = {**read_calibration(folder), "status": status, "completed": completed, "failed": failed, "failure": state.failure}
    write_calibration(folder, record)
    state.update(message=status)
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
                     "offsets": offsets, "seconds": seconds, "failure": trial.user_attrs.get("failure")})
    return rows


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

