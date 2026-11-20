"""A calibration on disk, run with Optuna: <results folder>/calibration/<name>/ holds

  calibration.json  what is calibrated, against what, with which setup, sampler and number of trials
  optuna.db         the Optuna study (SQLite): every trial, its values and objectives; a calibration resumes from it
  status.json       written by the process running the calibration, with a heartbeat: whether it runs, where, and how far
  optuna.snapshot.db a consistent copy of the study, written with the status, that can be copied while the trials go on
  inputs/           the driving files cut to the region and period of the setup, once for all the trials
  bin/mobile.out    the model, built by the first run and run as it is by all the others (mobile.sh -E)
  trials/trial_<n>/ one folder per trial: its temperature file, if offset, a run folder per seed, and series/: the
                    model and the observations of each objective as compared, and of each view (a comparison pinned
                    to be drawn, never optimised), kept to be drawn without the output

Paths in calibration.json may be relative to its folder (a calibration sent to a cluster), and the MoBILE clone is that
of the record if it exists, else $MOBILE.

A trial samples the parameters, runs the model for each seed, processes the output as each objective says and compares
it with the observations of the objective: the values of the metrics are the objectives Optuna optimises.

Temperature offsets (dT) shift the temperature of chosen cells, e.g. to stand for the temperature where people live
within a coarse cell. The cells are given from the coolest to the warmest, as they must stay: the first gets an offset
dT_1, and each next one a gap of at least 0 above the one before (in the means over the simulated period), so that
the order of their temperatures holds in every trial without any trial being wasted. Optionally a trend (dT_trend, °C per
decade, the same for all the cells offset) adds a warming or cooling that grows in time, centred on the middle of the
period so that it leaves the mean of each cell, and so the gaps and their order, as they are: it tests whether a steeper
(or gentler) warming than that of the driving files would match the observations.
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
from contextlib import closing
from dataclasses import replace
from functools import lru_cache
from pathlib import Path

import netCDF4
import numpy as np
import optuna
import pandas as pd

from .calibration_data import DataError, drop_window, read_observations, select_window, write_observations
from .calibration_metrics import DIRECTIONS, ENSEMBLE, pair, metrics
from .observation import band as _band, coverage as coverage_of, crps
from .calibration_model import PEOPLE_OUTPUTS, SPACES, model_count_members, model_members, process_both, process_observed, seed_spread, validation_parts, validation_windows
from .calibration_steps import IN_CASES, apply_steps
from .cells import cell_areas
from .config import MAX_PATH_LENGTH, ConfigError
from .driving import LAT_NAMES, LON_NAMES, POP_NAMES, TEMP_NAMES, TIME_NAMES, first_name
from .grid import pop_coordinates
from .parameters import to_model
from .region import cut_inputs
from .results import _md5
from .rundir import new_run_id, period_steps
from .runner import NETCDF_LOCK, RUN_PID, BuildOnce, RunCancelled, Runner, stop_left
from .setup import from_fields, to_dict

# Raised when a change means calibrations made before cannot be resumed (e.g. 2: the first trial has no offset; 3: a
# filtered objective is filtered over the whole period and only then cut to each window). They can still be looked at.
VERSION = 3
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
OBJECTIVE, VIEW = "objective", "view"  # The kinds of comparison kept in series/: optimised, or only drawn
HEARTBEAT_SECONDS = 60  # The status is written this often while a calibration runs, and after every trial
STALE_SECONDS = 300  # A status not written for this long, on another computer without Slurm to ask, is of a process gone
SNAPSHOT_SECONDS = 30  # The snapshot of the study is written at most this often, and at the end
CRASH_RATE = 0.1  # The calibration stops when more trials fail than this share of the trials asked for (at least FAIL_FAST)
EXPECTED_FROM = 10  # The time a trial takes is the 95th percentile of the completed trials once there are this many
CONSTRAINT = "constraint"  # Trial attribute: (violation,), <= 0 feasible (persistence); also given to Optuna
PERSISTENCE = "persistence"  # Trial attribute: how long transmission lasted in each seed (persistence)
OBSERVATION = "observation"  # Record: the observational model, {model, rho: [low, high], k: [low, high], draws}, or None
REPORTING = "reporting"  # Trial attribute: {rho, k} of the observational model, as sampled
COVERAGE = "coverage"  # Trial attribute: {part: [share of the data within the band of each objective, or None]}
LIMITS = "limits"  # Trial attribute: {objective: how far beyond its limit (> 0) or within it (<= 0)}, of those with a limit
INFEASIBLE = "infeasible"  # Trial attribute: why the trial is infeasible, for the user
DIED_OUT_DAYS = 365  # A seed whose output has no positive value in this many last days (or all, if shorter) died out
REGIME = "regime"  # Trial attribute: where between epidemic and endemic the runs are (regime)
CASES = "Inew"  # The output of new cases (out_I_new), from which the regime is measured
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
# Optuna's warnings include a message and a traceback for every failed trial: the engine records the failure with the
# trial (and `mobile calibrate` prints one line), so only its errors are let through
optuna.logging.set_verbosity(optuna.logging.ERROR)


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


DAYS_PER_DECADE = 3652.5


def _days(data):
    """The days of the time axis of a file, as numpy datetime64[D]."""
    time = data[first_name(TIME_NAMES, data.variables)]
    dates = netCDF4.num2date(time[:], time.units, getattr(time, "calendar", "standard"), only_use_cftime_datetimes=False,
                             only_use_python_datetimes=True)
    return np.array([np.datetime64(date.strftime("%Y-%m-%d")) for date in np.atleast_1d(dates)], dtype="datetime64[D]")


def trend_centre(temp_file):
    """The middle of the period of a temperature file (that of a calibration is cut to its period), the day where a
    trend offset is 0, as an ISO date."""
    with netCDF4.Dataset(temp_file) as data:
        days = _days(data)
    return str(days[0] + (days[-1] - days[0]) // 2)


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
    trend = {"dT_trend": values["dT_trend"]} if temperature.get("trend") else {}
    if not temperature.get("ordered", True):
        return {**{f"dT_{k + 1}": values[f"dT_{k + 1}"] for k in range(len(cells))}, **trend}
    offsets = [values["dT_1"]]
    for k in range(1, len(cells)):
        offsets.append(means[k - 1] + offsets[k - 1] + values[f"gap_{k + 1}"] - means[k])
    return {**{f"dT_{k + 1}": offset for k, offset in enumerate(offsets)}, **trend}


def baseline(temperature):
    """The sampled values of no offset at all (dT_1 = 0 and each gap the difference of the cell means), or None if they are
    outside the ranges of the calibration."""
    means = temperature["means"]
    low, high = temperature["first"]
    trend = temperature.get("trend")
    if trend and not trend[0] <= 0.0 <= trend[1]:
        return None
    no_trend = {"dT_trend": 0.0} if trend else {}
    if not temperature.get("ordered", True):
        return {**{f"dT_{k + 1}": 0.0 for k in range(len(means))}, **no_trend} if low <= 0.0 <= high else None
    values = {"dT_1": 0.0, **{f"gap_{k + 1}": means[k] - means[k - 1] for k in range(1, len(means))}, **no_trend}
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


def offset_temperature(source, target, cells, offsets, centre=None):
    """Write a copy of the temperature file with each cell, or every cell of each region, shifted by its offset (°C), the
    others as they are. With offsets["dT_trend"] (°C per decade) and the day it is 0 (centre, ISO date), the cells
    offset are also shifted by the trend times the decades from that day: 0 on average over a period centred there."""
    shutil.copyfile(source, target)
    with netCDF4.Dataset(target, "a") as data:
        lat, lon = _coordinates(data)
        field = data[first_name(TEMP_NAMES, data.variables)]
        trend = offsets.get("dT_trend") or 0.0
        if trend and centre is None:
            raise CalibrationError("a temperature trend needs the day where it is 0")
        drift = (trend * (_days(data) - np.datetime64(centre, "D")).astype("f8") / DAYS_PER_DECADE) if trend else 0.0
        for k, cell in enumerate(cells):
            for member in members(cell):
                i, j = _cell(lat, lon, member)
                field[:, i, j] = field[:, i, j] + offsets[f"dT_{k + 1}"] + drift
        data.mobile_offsets = json.dumps({f"{cell['lat']},{cell['lon']}": round(offsets[f"dT_{k + 1}"], 6)
                                          for k, cell in enumerate(cells)})
        if "dT_trend" in offsets:
            data.mobile_trend = json.dumps({"dT_trend": round(trend, 6), "unit": "°C per decade", "zero_on": centre})


# ---------------------------------------------------------------- creating

def create_calibration(config, objectives, parameters=(), temperature=None, seeds=(12345,), n_trials=100,
                       sampler="tpe", startup_trials=10, sampler_seed=1, name=None, validation=None, views=(), observation=None):
    """Write the folder of a new calibration and return it.

    config: the setup, with the parameters not calibrated and the outputs the objectives need.
    objectives: [{name, data (observations file), variable, space, aggregation, steps (applied to the model output),
    metric, limit (optional)}]; each is minimised or maximised as its metric says (calibration_metrics.DIRECTIONS). A
    limit makes it a hard constraint too: a trial beyond it (above it for a minimised one or a bias, below it for a
    maximised one) is infeasible, kept out of the Pareto front and graded by how far beyond; none by default.
    parameters: SampledParameter of the model to calibrate (uniform or log-uniform), in the units of the sliders.
    temperature: {cells: [{lat, lon}, or {lat, lon, members: [{lat, lon}]} for a region whose cells share one offset] from
    the coolest to the warmest (regions by their mean weighted by people), first: (low, high) of dT_1 in °C, gap: (low,
    high) of each next gap, low at least 0, ordered: True (default) to keep their order, or False for each dT_k sampled on
    its own within the range of dT_1, trend: (low, high) of dT_trend in °C per decade, or absent for none}, or None.
    validation: (first, last) dates of a validation window, several windows [(first, last), ...] (e.g. an episode the
    calibration should not be pressed to fit, and the last years), or None: the objectives are calibrated on the period
    the model and the data share without any of them, and each trial is scored on each window too, with the same
    metrics, kept with the trial.
    observation: the observational model (observation.py), or None: {"rho": (low, high), "k": (low, high), "draws": 500}:
    each trial samples a reporting fraction rho and a dispersion k (both log-uniform) and draws as many reported series
    (negative binomial) from its runs; each objective's metric then compares the median of them, processed as the data,
    and the band of them is kept with the trial, with its coverage of the data; the metric "crps" scores the band itself.
    views: comparisons pinned to be drawn for each trial and never optimised, as the objectives but without a metric
    ({name, data, variable, space, aggregation, steps, data_raw, data_steps}): their series are kept with each trial."""
    if not objectives:
        raise CalibrationError("give at least one objective")
    if not parameters and not temperature:
        raise CalibrationError("give at least one parameter or temperature offset to calibrate")
    for objective in objectives:
        if objective["metric"] not in DIRECTIONS:
            raise CalibrationError(f"unknown metric {objective['metric']!r}: one of {', '.join(DIRECTIONS)}")
        if objective.get("space", "people") not in SPACES:
            raise CalibrationError(f"unknown space {objective['space']!r}: one of {', '.join(SPACES)}")
        limit = objective.get("limit")
        if limit is not None and (isinstance(limit, bool) or not isinstance(limit, (int, float)) or not math.isfinite(limit)):
            raise CalibrationError(f"{objective['name']}: its limit must be a number, or none")
        if limit is not None and DIRECTIONS[objective["metric"]] != "maximize" and limit <= 0:
            raise CalibrationError(f"{objective['name']}: its limit must be above 0 ({objective['metric']} is at least 0)")
        read_observations(objective["data"])  # Raises DataError if it cannot be read
        if objective.get("data_raw"):
            read_observations(objective["data_raw"])
    for view in views:
        if view.get("space", "people") not in SPACES:
            raise CalibrationError(f"view {view.get('name')}: unknown space {view['space']!r}: one of {', '.join(SPACES)}")
        for key in ("data", "data_raw"):
            if view.get(key):
                read_observations(view[key])  # Raises DataError if it cannot be read
        if not (view.get("data") or view.get("data_raw")):
            raise CalibrationError(f"view {view.get('name')}: give its observations")
    observation = _observation(observation, objectives)
    if observation and config.output is not None and not set(PEOPLE_OUTPUTS.values()) <= set(config.output):
        raise CalibrationError("the observational model needs the outputs Agents per cell and Humans per agent (the model's "
                               "own population, which growth changes): tick them in the outputs")
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
        OBSERVATION: observation,
        "objectives": [{"space": "people", "aggregation": None, "steps": [], **objective, "data": str(Path(objective["data"]).resolve()),
                        **({"data_raw": str(Path(objective["data_raw"]).resolve())} if objective.get("data_raw") else {}),
                        "direction": DIRECTIONS[objective["metric"]]} for objective in objectives],
        "views": [{"space": "people", "aggregation": None, "steps": [],
                   **{key: value for key, value in view.items() if key not in ("metric", "direction")},
                   **{key: str(Path(view[key]).resolve()) for key in ("data", "data_raw") if view.get(key)}} for view in views],
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
    """The validation windows, checked: each with a first and a last date, within the observations of every objective;
    none overlapping; some of the period left out of all of them. One window as [first, last], several as
    [[first, last], ...] (as validation_windows reads them)."""
    try:
        given = [validation] if isinstance(validation[0], (str, pd.Timestamp, datetime.date)) else list(validation)
        windows = sorted((pd.Timestamp(first), pd.Timestamp(last)) for first, last in given)
    except (TypeError, ValueError, IndexError):
        raise CalibrationError(f"each validation window needs a first and a last date: {validation!r}") from None
    if not windows:
        raise CalibrationError("give at least one validation window, or none")
    for first, last in windows:
        if first > last:
            raise CalibrationError(f"the validation window {first.date()} to {last.date()} must start before it ends")
    for (_, last), (first, _) in zip(windows, windows[1:]):
        if first <= last:
            raise CalibrationError("the validation windows overlap")
    windows = [(str(first.date()), str(last.date())) for first, last in windows]
    for objective in objectives:
        if not objective.get("data_raw"):
            raise CalibrationError(f"{objective['name']}: a validation window needs the observations as loaded: add the objective again")
        data = read_observations(objective["data_raw"])
        if data.shape != "dated":
            raise CalibrationError(f"{objective['name']}: a validation window needs dated observations")
        try:
            rest = data
            for window in windows:
                select_window(data, *window)
                rest = drop_window(rest, *window)
        except DataError as error:
            raise CalibrationError(f"{objective['name']}: {error}") from None
    return list(windows[0]) if len(windows) == 1 else [list(window) for window in windows]


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
    trend = temperature.get("trend")
    if trend:
        trend = [float(value) for value in trend]
        if trend[0] >= trend[1]:
            raise CalibrationError("the range of the temperature trend needs its low below its high")
    means = [region_mean(temp_file, pop_file, cell) for cell in cells]
    size = temperature.get("size")  # Of the boxes of the regions, if any: kept for a calibration used as a template
    return {"cells": cells, "first": first, "gap": gap, "means": means, "ordered": ordered,
            **({"size": float(size)} if size else {}),
            **({"trend": trend, "trend_centre": trend_centre(temp_file)} if trend else {})}


def _observation(observation, objectives):
    """The observational model of a calibration, checked: the ranges of rho (in (0, 1]) and k (above 0), the draws; None
    if none (then no objective may use a metric of the band, CRPS, nor a log offset in cases on the model's side: the
    model's series has no population N of its own without it)."""
    if not observation:
        for objective in objectives:
            if objective["metric"] in ENSEMBLE:
                raise CalibrationError(f"{objective['name']}: {objective['metric']} needs the observational model")
            if any(step.get("offset_unit") == IN_CASES for step in objective.get("steps", [])):
                raise CalibrationError(f"{objective['name']}: a log offset in cases needs the observational model (the "
                                       "model's reported cases and their population)")
        return None
    try:
        rho = [float(value) for value in observation["rho"]]
        k = [float(value) for value in observation["k"]]
        draws = int(observation.get("draws", 500))
    except (KeyError, TypeError, ValueError):
        raise CalibrationError(f"the observational model needs a range of rho, a range of k and the draws: {observation!r}") from None
    if not 0 < rho[0] < rho[1] <= 1:
        raise CalibrationError("the reporting fraction rho needs a range above 0 and at most 1, its low below its high")
    if not 0 < k[0] < k[1]:
        raise CalibrationError("the dispersion k needs a range above 0, its low below its high")
    if draws < 20:
        raise CalibrationError("the observational model needs at least 20 draws (500 by default)")
    for objective in objectives:
        if not objective.get("data_raw"):
            raise CalibrationError(f"{objective['name']}: the observational model needs the observations as loaded: add the "
                                   "objective again")
        if "N" not in read_observations(objective["data_raw"]).extra:
            raise CalibrationError(f"{objective['name']}: the observational model needs the observations' population (a column N)")
    return {"model": "negbin", "rho": rho, "k": k, "draws": draws}


def _in_folder(folder, path):
    """A path of the record: as it is if absolute, else within the folder of the calibration. Other values (no file: "",
    "NONE", a number) as they are."""
    if not isinstance(path, str) or path.strip() in ("", "NONE") or Path(path).is_absolute():
        return path
    return str(Path(folder).resolve() / path)


def resolved(folder, record):
    """The record with the paths of the observations of its objectives and views within its folder when they are relative
    (calibration sent to a cluster)."""
    def inside(items):
        return [{**item, **{key: _in_folder(folder, item[key]) for key in ("data", "data_raw") if item.get(key)}} for item in items]
    return {**record, "objectives": inside(record["objectives"]), "views": inside(record.get("views") or [])}


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
        offsets = offsets_from(temperature, {**{f"dT_{k}": trial.suggest_float(f"dT_{k}", *temperature["first"])
                                                for k in range(1, len(temperature["cells"]) + 1)},
                                             **_trend_sampled(trial, temperature)})
    elif temperature:
        sampled = {"dT_1": trial.suggest_float("dT_1", *temperature["first"])}
        for k in range(2, len(temperature["cells"]) + 1):
            sampled[f"gap_{k}"] = trial.suggest_float(f"gap_{k}", *temperature["gap"])
        offsets = offsets_from(temperature, {**sampled, **_trend_sampled(trial, temperature)})
    if record.get(OBSERVATION):  # Of the reporting, not of the model: in the trial's params, not in its run
        trial.suggest_float("obs_rho", *record[OBSERVATION]["rho"], log=True)
        trial.suggest_float("obs_k", *record[OBSERVATION]["k"], log=True)
    return values, offsets


def trial_observation(record, trial):
    """The observational model of a trial, {rho, k, draws, seed} (its sampled rho and k; the draws' seed of the trial, so
    that every objective and part sees the same reported series), or None without one."""
    if not record.get(OBSERVATION):
        return None
    return {"rho": trial.params["obs_rho"], "k": trial.params["obs_k"], "draws": record[OBSERVATION]["draws"],
            "seed": int(record["sampler"]["seed"]) * 100003 + trial.number}


def _trend_sampled(trial, temperature):
    return {"dT_trend": trial.suggest_float("dT_trend", *temperature["trend"])} if temperature.get("trend") else {}


def observed_series(objective, run_dirs, validation=None, part=None, observation=None):
    """(model, data, draws) of an objective: as objective_series, and with the observational model (`observation`, as
    trial_observation gives it; objectives with the raw observations) the model is the median of the reported series
    drawn from the runs, processed as the data, and draws are those processed series (draws x values of model); None
    without."""
    if observation and objective.get("data_raw"):
        members = [member for run_dir in run_dirs
                   for member in model_members(run_dir, objective["variable"], objective["space"], None, objective["aggregation"])]
        counts = [member for run_dir in run_dirs for member in model_count_members(run_dir, objective["variable"])]
        model, data, _, draws = process_observed(members, counts, objective["steps"], read_observations(objective["data_raw"]),
                                                 objective.get("data_steps", []), observation, validation=validation, part=part)
        return model, data, draws
    return (*objective_series(objective, run_dirs, validation, part), None)


def objective_series(objective, run_dirs, validation=None, part=None):
    """(model, data) of an objective for the runs of a trial (one per seed). With the raw observations and their steps
    (objectives made since: data_raw, data_steps), both are first cut to the period they share, then each processed by
    its own steps (calibration_model.process_both), so that e.g. a climatology covers the same years on both sides. With
    only the observations as processed (earlier objectives), those, and the model output processed by its steps (for
    several seeds, the median of the seeds each processed). validation and part as for process_both: with a validation
    window, part "calibration" leaves them out, a part of validation_parts keeps that window only."""
    members = [member for run_dir in run_dirs
               for member in model_members(run_dir, objective["variable"], objective["space"], None, objective["aggregation"])]
    if objective.get("data_raw"):
        model, data, _ = process_both(members, objective["steps"], read_observations(objective["data_raw"]),
                                      objective.get("data_steps", []), validation=validation, part=part)
        return model, data
    model = apply_steps(members[0], objective["steps"]) if len(members) == 1 else seed_spread(members, objective["steps"])
    return model, read_observations(objective["data"])


def _series_files(folder, index, part, kind=OBJECTIVE):
    """(model, observations) files of objective (or view: kind VIEW) `index` and a part of the period (None for the whole)
    kept in a folder."""
    name = f"{kind}_{index}_{part or 'whole'}"
    return Path(folder) / f"{name}_model.nc", Path(folder) / f"{name}_data.nc"


def _touched(path):
    """The path, with an empty file there: netCDF then writes it from a thread without HDF5 printing the error of looking for
    one (as it does when it does not exist), which would fill the log of a batch job."""
    Path(path).touch()
    return path


def _keep(folder, index, part, model, data, kind=OBJECTIVE, draws=None):
    Path(folder).mkdir(parents=True, exist_ok=True)
    for series, path in zip((model, data), _series_files(folder, index, part, kind)):
        write_observations(series, _touched(path))
    if draws is not None:  # The band of the reported series (observational model): its median, low and high ends
        low, middle, high = band_of(draws)
        write_observations(replace(model, values=middle, sd=None, extra={"low": low, "high": high}),
                           _touched(_band_file(folder, index, part, kind)))


def band_of(draws):
    """(low, median, high) of the band of processed draws (observation.LEVELS)."""
    low, middle, high = _band(draws)
    return low, middle, high


def _band_file(folder, index, part, kind=OBJECTIVE):
    return Path(folder) / f"{kind}_{index}_{part or 'whole'}_band.nc"


def trial_band(folder, number, index=0, part=None, kind=OBJECTIVE):
    """(low, median, high) of the band of reported series of an objective (or view) for a trial, kept with it, on the
    values of its model series; None if it has none (no observational model)."""
    record = read_calibration(folder)
    path = _band_file(trial_folder(folder, number) / SERIES, index, part if record.get("validation") else None, kind)
    if not path.is_file():
        return None
    with NETCDF_LOCK:
        kept = read_observations(path)
    return np.asarray(kept.extra["low"]), np.asarray(kept.values), np.asarray(kept.extra["high"])


def keep_series(objectives, run_dirs, folder, validation=None, part=None, observation=None):
    """Keep in a folder the model and the observations of each objective as compared, for a part of the period (None for
    the whole), for the plots of a trial without its output (with the observational model, the band too). One that
    cannot be had is left out."""
    for index, objective in enumerate(objectives):
        try:
            model, data, draws = observed_series(objective, run_dirs, validation, part, observation)
            _keep(folder, index, part, model, data, draws=draws)
        except DataError:
            continue


def keep_views(views, run_dirs, folder, validation=None, observation=None):
    """Keep in a folder the model and the observations of each view (a comparison pinned to be drawn, never optimised): for
    the whole period, and with a validation window for each of its parts. One that cannot be had is left out: a view
    never fails a trial."""
    for part in (("calibration", *validation_parts(validation), None) if validation else (None,)):
        for index, view in enumerate(views):
            try:
                model, data, draws = observed_series(view, run_dirs, validation, part, observation)
                _keep(folder, index, part, model, data, kind=VIEW, draws=draws)
            except (DataError, ValueError, KeyError, OSError):
                continue


def flat_value(metric, data_values):
    """The value of a metric for a model series that does not vary (e.g. transmission died out), where the metric itself
    is not defined: what a model with no timing and no swings scores. The correlation 0 (no timing in common); the relative
    RMSE that of a constant series, the coefficient of variation of the data. None for the others (always defined)."""
    if metric == "correlation":
        return 0.0
    if metric == "rmse_relative" and data_values.mean() > 0:
        return float(np.sqrt(np.mean((1.0 - data_values / data_values.mean()) ** 2)))
    return None


def evaluate(objectives, run_dirs, validation=None, part=None, strict=True, keep=None, flat=None, observation=None,
             coverage=None):
    """[value of each objective] of the runs of a trial (one per seed): the output and the observations as
    objective_series gives them (with a validation window: the part of the period, "calibration" or "validation"), paired
    and compared by the metric of the objective. Not strict, None for a value that cannot be had instead of an error.
    keep: a folder to keep the series compared in (keep_series). flat: a list to which the index of each objective whose
    model series does not vary is added, scored then as flat_value says, instead of an error (the trial is then
    infeasible, see persistence). observation: the observational model of the trial (trial_observation): the metrics
    compare the median of the reported series drawn, "crps" their band; coverage: a list to which the share of the data
    within the band of each objective is added (None without the observational model)."""
    results = []
    for index, objective in enumerate(objectives):
        try:
            model, data, draws = observed_series(objective, run_dirs, validation, part, observation)
            if keep is not None:
                _keep(keep, index, part, model, data, draws=draws)
            model_values, data_values, _ = pair(model, data)
            if draws is not None:  # The draws on the same pairs as the median and the data
                columns = pair(replace(model, values=np.where(np.isfinite(model.values), np.arange(len(model.values), dtype="f8"),
                                                              np.nan)), data)[0].astype(int)
                low, _, high = band_of(draws[:, columns])
                if coverage is not None:
                    coverage.append(coverage_of(low, high, data_values))
            elif coverage is not None:
                coverage.append(None)
            if objective["metric"] in ENSEMBLE:
                if draws is None:
                    raise DataError(f"{objective['name']}: {objective['metric']} needs the observational model")
                value = float(np.nanmean(crps(draws[:, columns], data_values)))
            else:
                value = metrics(model_values, data_values)[objective["metric"]]
            if value is None and flat is not None and np.ptp(model_values) == 0:
                value = flat_value(objective["metric"], data_values)
                if value is not None:
                    flat.append(index)
            if value is None:
                why = (f"the mean of the model ({model_values.mean():.3g}) or of the data ({data_values.mean():.3g}) is not "
                       f"positive, e.g. after a log or an anomaly: use Correlation or RMSE" if objective["metric"] == "rmse_relative"
                       else "a series does not vary (a flat series)")
                raise DataError(f"{objective['name']}: {objective['metric']} is not defined for these values: {why}")
        except DataError:
            if strict:
                raise
            results.append(None)
            continue
        results.append(abs(value) if objective["direction"] == "zero" else value)
    return results


def limits_said(objectives, results):
    """[(name, value, limit, excess)] of the objectives with a limit: excess > 0 beyond it (above it for a minimised one or
    a |bias|, below it for a maximised one), <= 0 within it."""
    said = []
    for objective, value in zip(objectives, results):
        limit = objective.get("limit")
        if limit is None or value is None:
            continue
        excess = (limit - value) if objective["direction"] == "maximize" else (value - limit)
        said.append((objective["name"], value, limit, float(excess)))
    return said


def log_base(objective):
    """The base of the log an objective's model steps take, if it is measured in log units (a bias or an RMSE after a
    log: its values are log-ratios, read as factors), else None."""
    if objective.get("metric") not in ("bias", "rmse"):
        return None
    logs = [step["transform"] for step in objective.get("steps", []) if step.get("kind") == "transform"
            and step.get("transform") in ("log", "log10")]
    return (math.e if logs[-1] == "log" else 10.0) if logs else None


def limit_said(objective, value, limit):
    """How a value beyond an objective's limit is said: as factors for one in log units ("Decadal_level ×3.6 off, beyond
    ×3"; an RMSE "typically ×…"), else as numbers ("Seasonal_shape 0.42, beyond its limit 0.7")."""
    base = log_base(objective)
    if base is None:
        return f"{objective['name']} {value:.3g}, beyond its limit {limit:g}"
    factor, most = (round(base ** abs(number), 2) for number in (value, limit))
    if objective["metric"] == "bias":
        return f"{objective['name']} ×{factor:g} off, beyond ×{most:g}"
    return f"{objective['name']} typically ×{factor:g} off, beyond ×{most:g}"


def limits_exceeded(objectives, results):
    """{objective: excess} of the objectives with a limit (limits_said), each a constraint for the sampler."""
    return {name: excess for name, _, _, excess in limits_said(objectives, results)}


def persistence(objectives, run_dirs, flat=()):
    """How long transmission lasted in the runs of a trial, and whether the trial is feasible: {days, last: [day of the
    last positive value of each seed, -1 for none], died_out: seeds with no positive value in the last DIED_OUT_DAYS
    (or all, if the run is shorter), flat: names of the objectives whose model series did not vary, violation, reason}.

    Measured on the daily output of the variables of the objectives (the latest positive value of any of them), over the
    whole run. Infeasible (violation > 0) if more than half the seeds died out, or an objective's series was flat. The
    violation is graded, for the sampler to know how near the boundary between dying out and persisting a trial is: the
    share of the run after transmission ended (the mean over the seeds that died out), from just above 0 (died out at
    the very end) to 1 (none at all); 1 also for a flat series with transmission going on (nothing to grade it by). A
    feasible trial gets -1."""
    variables = {(objective["variable"], objective["space"], objective["aggregation"]) for objective in objectives}
    days, last = 0, []
    for run_dir in run_dirs:
        latest = -1
        for name, space, aggregation in sorted(variables, key=str):
            member = model_members(run_dir, name, space, None, aggregation)[0]
            values = np.asarray(member.values, dtype="f8")
            days = max(days, len(values))
            positive = np.flatnonzero(np.isfinite(values) & (values > 0))
            latest = max(latest, int(positive[-1]) if len(positive) else -1)
        last.append(latest)
    window = min(DIED_OUT_DAYS, days)
    died = [day for day in last if days - 1 - day >= window]
    flat_names = [objectives[index]["name"] for index in sorted(set(flat))]
    result = {"days": days, "last": last, "died_out": len(died), "flat": flat_names}
    if died and len(died) * 2 > len(last):
        result["violation"] = float(np.mean([(days - 1 - day) / days for day in died]))
        never = sum(day < 0 for day in died)
        result["reason"] = ("transmission died out: " + (f"no case at all in {never} of {len(last)} seeds" if never == len(died)
                            else f"no case in the last {min(days - 1 - day for day in died)}–{max(days - 1 - day for day in died)} "
                                 f"of {days} days in {len(died)} of {len(last)} seeds"
                            if len(died) > 1 else f"no case in the last {days - 1 - died[0]} of {days} days"))
    elif flat_names:
        result["violation"] = 1.0
        result["reason"] = f"the model series of {', '.join(flat_names)} does not vary"
    else:
        result["violation"] = -1.0
    return result


def regime(run_dirs):
    """Where between epidemic and endemic behaviour the runs of a trial are, by two measures that do not depend on the
    number of cases or the site (scale-free), from the daily new cases (CASES) of each run, over the whole run:

      annual_cv  the coefficient of variation of the cases of each full calendar year (standard deviation over the mean,
                 between years): low for endemic transmission, the same every year; high for epidemics, years of
                 outbreaks between years with few cases. None with fewer than two full years, or no cases.
      fade_out   the share of the full calendar months with no new case: 0 when transmission never stops; high when it
                 fades out between outbreaks (or died out).

    {annual_cv, fade_out: the median over the seeds, seeds: {annual_cv: [...], fade_out: [...]}}, or None if the runs
    have no output of new cases."""
    cvs, fades = [], []
    for run_dir in run_dirs:
        try:
            member = model_members(run_dir, CASES, "people", None, None)[0]
        except DataError:
            return None
        days = pd.to_datetime(member.index["start"].to_numpy())
        values = pd.Series(np.nan_to_num(np.asarray(member.values, dtype="f8")), index=days)
        full = lambda groups, length: groups.size()[groups.size() >= length]  # noqa: E731 - periods wholly in the run
        years = values.groupby(values.index.year)
        whole_years = full(years, 365).index
        annual = years.sum()[whole_years]
        cvs.append(float(annual.std(ddof=1) / annual.mean()) if len(annual) >= 2 and annual.mean() > 0 else None)
        months = values.groupby([values.index.year, values.index.month])
        whole = [key for key, size in months.size().items() if size >= pd.Period(f"{key[0]}-{key[1]:02d}").days_in_month]
        sums = months.sum()[whole]
        fades.append(float((sums <= 0).mean()) if len(sums) else None)
    median = lambda found: float(np.median([x for x in found if x is not None])) if any(x is not None for x in found) else None  # noqa: E731
    return {"annual_cv": median(cvs), "fade_out": median(fades), "seeds": {"annual_cv": cvs, "fade_out": fades}}


def trial_folder(folder, number):
    return Path(folder) / TRIALS / f"trial_{number:05d}"


def stop_runs_left(folder):
    """Stop the model runs of a calibration still running on this computer although the process that ran it died (e.g. a
    GUI closed or crashed): they would go on writing in the trial folders the calibration, resumed, makes again, and
    take the cores. Called once no process runs the calibration (its lock held). Returns how many were stopped."""
    return sum(stop_left(path.parent) for path in (Path(folder) / TRIALS).glob(f"*/*/{RUN_PID}"))


# ---------------------------------------------------------------- running

def sampler_for(record):
    """The sampler of a calibration. Each trial gives its feasibility to Optuna (trial.set_constraint, in the trial): the
    samplers keep infeasible trials (transmission died out) out of the Pareto front and rank them among themselves by how
    early it died out, so the search learns where the boundary is instead of losing those trials."""
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
    views = resolved(folder, record)["views"]
    stop_runs_left(folder)
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
    # A trial queued but never taken (the process that queued it ended first, e.g. killed before its first trial began) runs
    # on its own too, as a new one: else two workers side by side can both take it (SQLite has no row lock) and the one
    # makes again the folder the other writes in (Directory not empty; the flaky CI test of the handover's §6.3 item 17)
    queued = queued or bool(study.get_trials(deepcopy=False, states=(optuna.trial.TrialState.WAITING,)))
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
                offset_temperature(config.inputs["temp_file"], _touched(target_file), temperature["cells"], offsets,
                                   temperature.get("trend_centre"))
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
                flat = []
                observed = trial_observation(record, trial)
                covered = {}
                results = evaluate(objectives, run_dirs, window, "calibration" if window else None, keep=kept, flat=flat,
                                   observation=observed, coverage=covered.setdefault("calibration" if window else "whole", []))
                if window:  # Scored on each validation window too, kept with the trial; not optimised
                    scored = [{"window": list(span), "part": part,
                               "values": evaluate(objectives, run_dirs, window, part, strict=False, keep=kept,
                                                  observation=observed, coverage=covered.setdefault(part, []))}
                              for span, part in zip(validation_windows(window), validation_parts(window))]
                    trial.set_user_attr("validation", scored[0]["values"])  # The first window, as the views read it
                    trial.set_user_attr("validation_windows", scored)  # Every window: [{window, part, values}]
                    keep_series(objectives, run_dirs, kept, window, None, observation=observed)  # The whole period too
                keep_views(views, run_dirs, kept, window, observation=observed)
                if observed is not None:
                    trial.set_user_attr(REPORTING, {"rho": observed["rho"], "k": observed["k"]})
                    trial.set_user_attr(COVERAGE, covered)
                lasted = persistence(objectives, run_dirs, flat)
                measured = regime(run_dirs)
            if measured is not None:
                trial.set_user_attr(REGIME, measured)
            # Infeasible (transmission died out, or a series did not vary): completed, kept out of the front, and graded
            # for the sampler by how near persisting it came
            trial.set_user_attr(PERSISTENCE, {key: value for key, value in lasted.items() if key not in ("violation", "reason")})
            trial.set_constraint("transmission", lasted["violation"])
            beyond = limits_exceeded(objectives, results)
            for name, excess in beyond.items():
                trial.set_constraint(f"limit: {name}", excess)
            if beyond:
                trial.set_user_attr(LIMITS, beyond)
            violation = max([lasted["violation"], *beyond.values()])
            trial.set_user_attr(CONSTRAINT, (violation,))
            if violation > 0:
                said = {objective["name"]: objective for objective in objectives}
                trial.set_user_attr(INFEASIBLE, "; ".join([lasted.get("reason", "")] * (lasted["violation"] > 0) + [
                    limit_said(said[name], value, limit) for name, value, limit, excess in limits_said(objectives, results)
                    if excess > 0]))
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
    """[{number, state, values, params, offsets, seconds, failure, baseline, validation, validation_windows (each window's
    {window, part, values}), infeasible (why, or None),
    persistence, violation, regime}] of the trials of a calibration, in order."""
    record = read_calibration(folder)
    study = open_study(folder, record)
    rows = []
    for trial in study.get_trials(deepcopy=False):
        offsets = {key: value for key, value in trial.user_attrs.items() if key.startswith("dT_")}
        seconds = (trial.datetime_complete - trial.datetime_start).total_seconds() if trial.datetime_complete and trial.datetime_start else None
        rows.append({"number": trial.number, "state": trial.state.name, "values": trial.values, "params": dict(trial.params),
                     "offsets": offsets, "seconds": seconds, "failure": trial.user_attrs.get("failure"),
                     "baseline": bool(trial.user_attrs.get("baseline")), "validation": trial.user_attrs.get("validation"),
                     "validation_windows": trial.user_attrs.get("validation_windows"),
                     "infeasible": trial.user_attrs.get(INFEASIBLE), "persistence": trial.user_attrs.get(PERSISTENCE),
                     "violation": trial.user_attrs.get(CONSTRAINT, (None,))[0], "regime": trial.user_attrs.get(REGIME),
                     "limits": trial.user_attrs.get(LIMITS), "reporting": trial.user_attrs.get(REPORTING),
                     "coverage": trial.user_attrs.get(COVERAGE)})
    return rows


def trial_comparison(folder, number, index=0, part=None, kind=OBJECTIVE):
    """(model, data, model values, data values, labels) of objective `index` (or view, kind VIEW) for a completed trial:
    its runs processed as the objective says, and the observations, paired as for the metrics. With validation windows,
    part "calibration" or one of validation_parts (e.g. "validation", "validation_2") for one part of the period, None
    for the whole period the model and the data share."""
    record = read_calibration(folder)
    objective = resolved(folder, record)["objectives" if kind == OBJECTIVE else "views"][index]
    here = trial_folder(folder, number)
    run_dirs = [here / f"seed_{seed}" for seed in record["seeds"]]
    files = _series_files(here / SERIES, index, part if record.get("validation") else None, kind)
    with NETCDF_LOCK:
        if all(path.is_file() for path in files):  # Kept with the trial: drawn without its output
            model, data = (read_observations(path) for path in files)
        else:
            model, data = objective_series(objective, run_dirs, record.get("validation"), part)
    model_values, data_values, labels = pair(model, data)
    return model, data, model_values, data_values, labels


def set_trials(folder, n_trials):
    """Raise the number of trials a calibration runs to (it goes on to it when run again, e.g. a finished one), and return
    the record. Optuna keeps no target of its own: the study goes on from all its trials, as one longer run. Refused for
    a calibration made by an earlier version, one running now, or fewer than have completed already."""
    record = read_calibration(folder)
    if not resumable(record):
        raise CalibrationError(OLD_CALIBRATION)
    if isinstance(n_trials, bool) or not isinstance(n_trials, int) or n_trials < 1:
        raise CalibrationError(f"the number of trials must be a whole number above 0: {n_trials!r}")
    if is_running(folder):
        raise CalibrationError(f"this calibration is running: {running_where(folder)}; change its trials once it has stopped")
    completed = completed_trials(folder, record)
    if n_trials < completed:
        raise CalibrationError(f"{completed} trials have completed already: give at least that many")
    record = {**record, "n_trials": n_trials}
    write_calibration(folder, record)
    return record


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


@lru_cache(maxsize=128)
def _study_completed(path, _stamp):
    """The completed trials in a study database (read again when it changes), or None if it cannot be read."""
    try:
        with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as database:
            return int(database.execute("SELECT count(*) FROM trials WHERE state = 'COMPLETE'").fetchone()[0])
    except sqlite3.Error:
        return None


def completed_trials(folder, record):
    """The completed trials of a calibration, counted in its study: the record has them only from when a run last ended,
    so not while it runs, here or elsewhere (a cluster job, its study copied back by Refresh). The record's count if the
    study cannot be read."""
    path = Path(folder) / DATABASE
    try:
        stamp = path.stat().st_mtime_ns
    except OSError:
        return record.get("completed", 0)
    found = _study_completed(str(path), stamp)
    return record.get("completed", 0) if found is None else found


def calibration_label(folder, record):
    """e.g. 'dz_two_cells (finished, 100 of 100 trials completed, 2 objectives)'; '..., earlier version' if it cannot be resumed."""
    done = completed_trials(folder, record)
    return (f"{Path(folder).name} ({status_of(folder, record)}, {done} of {record['n_trials']} trials completed, "
            f"{len(record['objectives'])} objective{'s' if len(record['objectives']) > 1 else ''}"
            f"{'' if resumable(record) else ', earlier version: cannot be resumed'})")


def best_trials(folder):
    """The trials on the Pareto front (for one objective, the best), as rows of trials_table: feasible ones only."""
    record = read_calibration(folder)
    study = open_study(folder, record)
    rows = trials_table(folder)
    numbers = set(front(study, rows))
    return [row for row in rows if row["number"] in numbers]


def front(study, rows):
    """The numbers of the trials on the Pareto front among the feasible completed ones (rows of trials_table): those no
    other is at least as good as on every objective and better on one. Computed here rather than by Optuna, which keeps
    infeasible trials out only for samplers that take the constraints (not the random one)."""
    signs = np.array([-1.0 if direction == optuna.study.StudyDirection.MAXIMIZE else 1.0 for direction in study.directions])
    feasible = [row for row in rows if row["state"] == "COMPLETE" and not (row["violation"] is not None and row["violation"] > 0)]
    if not feasible:
        return []
    values = np.array([row["values"] for row in feasible], dtype="f8") * signs  # All minimised
    kept = []
    for i, row in enumerate(feasible):
        dominated = np.any(np.all(values <= values[i], axis=1) & np.any(values < values[i], axis=1))
        if not dominated:
            kept.append(row["number"])
    return kept


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

