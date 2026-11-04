"""The analysis of the runs of a sensitivity analysis: the outputs read and reduced to the number (or map) analysed,
kept in the folder of the analysis, and their Sobol indices, for the mean over seeds and for each seed.

<analysis folder>/metrics/<key>/ holds, for one way of reducing the outputs (metric.json), the values of every run of
each seed (seed_<seed>.npy, one row per run) and, for maps, the cells they are of (cells.npy, flat indices on the
grid). Analysing them again in another way, or with the indices of another parameter on show, does not read the
runs again.
"""

import hashlib
import json
import time
from dataclasses import asdict
from pathlib import Path

import netCDF4
import numpy as np
import pandas as pd
import xarray as xr

from .driving import RAIN_NAMES, TEMP_NAMES
from .grid import mask_like, read_grid
from .results import load_run
from .sensitivity import Metric, analyse, analyse_cells, reduce_field
from .sensitivity_runs import RUNS, SAMPLES, run_finished, run_name, study_parameters

METRICS = "metrics"
CLIMATE_GROUP = "Climate"
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def sample_count(folder):
    return len(np.loadtxt(Path(folder) / SAMPLES, ndmin=2))


def complete_seeds(folder, record):
    """The seeds of the analysis whose runs have all finished: only these can be analysed."""
    runs, count = Path(folder) / RUNS, sample_count(folder)
    return [seed for seed in record["seeds"] if all(run_finished(runs / run_name(seed, index)) for index in range(count))]


def first_run(folder, record):
    """A finished run of the analysis, for its variables, days and grid; None if there is none."""
    runs = Path(folder) / RUNS
    for seed in record["seeds"]:
        for run_dir in sorted((runs / f"seed_{seed}").glob("sample_*")):
            if run_finished(run_dir):
                return run_dir
    return None


def output_info(run_dir):
    """{variables, time, lat, lon} of the output of a run, as RunResult.variables gives them."""
    result = load_run(run_dir)
    with xr.open_dataset(result.output_path) as root:
        coords = {name: root[name].values for name in ("time", "lat", "lon")}
    return {"variables": result.variables(), **coords}


def analysable_variables(variables):
    """{group: {name: label}} of the fields that change from run to run: not the climate, which every run reads."""
    choices = {}
    for name, info in variables.items():
        if info["group"] != CLIMATE_GROUP:
            choices.setdefault(info["group"], {})[name] = f"{info['long_name']} ({name})"
    return choices


def metric_key(metric):
    return hashlib.sha1(json.dumps(asdict(metric), sort_keys=True, default=list).encode()).hexdigest()[:12]


def describe_metric(metric, cells=None):
    """e.g. 'EIR, sum over the days from 2012-03-01 to 2012-05-31 in Mar, Apr, May, mean over the 4,120 populated cells'."""
    time = {"sum": "sum", "mean": "mean", "max": "maximum"}.get(metric.time)
    window = ""
    if metric.start or metric.end:
        window = f" from {metric.start or 'the first day'} to {metric.end or 'the last day'}"
    months = f" in {', '.join(MONTHS[month - 1] for month in sorted(metric.months))}" if metric.months else ""
    text = metric.variable + (f", {time} over the days{window}{months}" if time else f", every day{window}{months}")
    where = f"the {cells:,} populated cells" if cells else "the populated cells"
    if metric.space in ("mean", "sum"):
        text += f", {metric.space} over {where}"
    else:
        text += ", in each cell"
    return text


def _read(path, group, name, coords, first, last):
    """A field of a run output as a DataArray on the coordinates of the analysis, its days from first to last only."""
    with netCDF4.Dataset(path) as dataset:
        variable = dataset[f"{group}/{name}" if group else name]
        static = "time" not in variable.dimensions
        values = variable[:] if static else variable[first:last]
    values = np.ma.filled(np.ma.asarray(values, dtype="float64"), np.nan)
    if static:
        return xr.DataArray(values, dims=("lat", "lon"), coords={"lat": coords["lat"], "lon": coords["lon"]})
    return xr.DataArray(values, dims=("time", "lat", "lon"), coords={"time": coords["time"][first:last], "lat": coords["lat"], "lon": coords["lon"]})


def _days(times, metric):
    """First and last+1 day of the output in the window, to read only those."""
    times = np.asarray(times, dtype="datetime64[ns]")
    inside = np.ones(times.size, bool)
    if metric.start:
        inside &= times >= np.datetime64(metric.start)
    if metric.end:
        inside &= times < np.datetime64(metric.end) + np.timedelta64(1, "D")
    days = np.flatnonzero(inside)
    if days.size == 0:
        raise ValueError("No day of the output is in the time window.")
    return int(days[0]), int(days[-1]) + 1


def analysis_mask(record, info):
    """The simulated cells of the analysis on the coordinates of its outputs (lat, lon), as booleans."""
    grid = read_grid(record["inputs"]["pop_file"], record["inputs"]["area_file"], record["region"])
    if grid is None:
        raise ValueError("The region of the analysis is not on its population file any more.")
    template = xr.DataArray(np.zeros((info["lat"].size, info["lon"].size)), dims=("lat", "lon"), coords={"lat": info["lat"], "lon": info["lon"]})
    return mask_like(template, grid)


def extract(folder, record, metric, seeds, info, mask, progress=None):
    """{seed: values of every run, one row per run in the order of the samples}, from the outputs or, if read before,
    from metrics/; and the flat indices of the cells for a map (None for a number per run).

    progress, a StudyState, counts the runs read and is checked for a cancel between runs."""
    problems = metric.problems()
    if metric.time == "none":
        problems.append("Reduce over time: a series of days per run is not analysed yet.")
    if problems:
        raise ValueError(" ".join(problems))
    if metric.variable not in info["variables"]:
        raise ValueError(f"{metric.variable} is not in the outputs of this analysis.")
    store = Path(folder) / METRICS / metric_key(metric)
    store.mkdir(parents=True, exist_ok=True)
    (store / "metric.json").write_text(json.dumps(asdict(metric), indent=2, default=list) + "\n")
    cells = np.flatnonzero(mask.values) if metric.space == "none" else None
    if cells is not None:
        np.save(store / "cells.npy", cells)
    group = info["variables"][metric.variable]["group"]
    first, last = _days(info["time"], metric)
    count = sample_count(folder)
    todo = [seed for seed in seeds if not (store / f"seed_{seed}.npy").is_file()]
    if progress is not None:
        done = count * (len(seeds) - len(todo))  # Not begin(), which would forget a cancel pressed meanwhile
        progress.update(total=count * len(seeds), done=done, done_before=done, failed=0, started=time.time(), message="Reading")
    for seed in todo:
        values = []
        for index in range(count):
            if progress is not None and progress.cancelled:
                raise InterruptedError("Reading cancelled.")
            path = Path(folder) / RUNS / run_name(seed, index) / "output" / "output.nc"
            reduced = reduce_field(_read(path, group, metric.variable, info, first, last), metric, mask)
            values.append(reduced.values.ravel()[cells] if cells is not None else float(reduced))
            if progress is not None:
                progress.count("done")
        temporary = store / f"seed_{seed}.tmp.npy"
        np.save(temporary, np.asarray(values, dtype="float32" if cells is not None else "float64"))
        temporary.replace(store / f"seed_{seed}.npy")  # Only whole seeds are kept
    return {seed: np.load(store / f"seed_{seed}.npy").astype("float64") for seed in seeds}, cells


def chance_share(Y):
    """The share of the variance of the output over all runs that comes from the seed: the variance across the
    seeds of the same sample, averaged over the samples, over the variance of every run. Y is (seeds, runs, ...)."""
    within = np.var(Y, axis=0, ddof=1).mean(axis=0)
    total = np.var(Y.reshape(-1, *Y.shape[2:]), axis=0, ddof=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        return within / total


def scalar_analysis(parameters, Y, second_order, seed=None):
    """Indices of a number per run. Y is (seeds, runs). The indices, with bootstrap confidence intervals, are those of
    the mean over the seeds; with several seeds, those of each seed alone too ('each', arrays (seeds, parameters),
    without confidence intervals) and the share of the variance from chance."""
    mean = Y.mean(axis=0)
    if np.ptp(mean) == 0:
        raise ValueError(f"The output is {mean[0]:.4g} in every run: nothing to analyse. Check the variable and the days.")
    result = {"kind": "scalar", "mean": analyse(parameters, mean, second_order, seed=seed), "spread": float(np.std(mean))}
    if len(Y) > 1:
        each = [analyse_cells(parameters, y[:, None], second_order) for y in Y]
        result["each"] = {key: np.array([indices[key][:, 0] for indices in each]) for key in ("S1", "ST")}
        result["chance"] = float(chance_share(Y))
    return result


def cell_analysis(parameters, Y, second_order):
    """Indices of a map per run, cell by cell. Y is (seeds, runs, cells). 'mean' holds S1 and ST (parameters, cells) of the
    mean over seeds; with several seeds, 'range' holds their highest minus lowest value among the seeds, and 'chance'
    the share of the variance from chance in each cell."""
    result = {"kind": "cells", "mean": analyse_cells(parameters, Y.mean(axis=0), second_order)}
    if len(Y) > 1:
        each = [analyse_cells(parameters, y, second_order) for y in Y]
        result["range"] = {key: np.ptp(np.array([indices[key] for indices in each]), axis=0) for key in ("S1", "ST")}
        result["chance"] = chance_share(Y)
    return result


def climate_maps(run_dir, info, metric, cells):
    """{name: (label, units, values at the cells)} of the mean rainfall and temperature over the days of the metric,
    from the climate written in a run, which every run of the analysis reads."""
    maps = {}
    for names in (RAIN_NAMES, TEMP_NAMES):
        name = next((name for name in names if name in info["variables"]), None)
        if name is None:
            continue
        variable = info["variables"][name]
        first, last = _days(info["time"], metric)
        field = _read(load_run(run_dir).output_path, variable["group"], name, info, first, last)
        mean = reduce_field(field, Metric(name, "mean", "none", metric.start, metric.end, metric.months))
        maps[name] = (f"Mean {'rainfall' if names is RAIN_NAMES else 'temperature'}", variable["units"], mean.values.ravel()[cells])
    return maps


def analyse_study(folder, record, metric, progress=None):
    """Read the outputs (or what was read before) and compute the indices; the result for the page."""
    seeds = complete_seeds(folder, record)
    if not seeds:
        raise ValueError("No seed has all its runs finished: resume the analysis first.")
    run_dir = first_run(folder, record)
    info = output_info(run_dir)
    mask = analysis_mask(record, info)
    values, cells = extract(folder, record, metric, seeds, info, mask, progress)
    Y = np.array([values[seed] for seed in seeds])
    parameters = study_parameters(record)
    if cells is None:
        result = scalar_analysis(parameters, Y, record["second_order"], seed=record["sample_seed"])
    else:
        result = cell_analysis(parameters, Y, record["second_order"])
        result["cells"] = cells
        result["climate"] = climate_maps(run_dir, info, metric, cells)
        result["lat"], result["lon"] = info["lat"], info["lon"]
    populated = int(mask.values.sum())
    result.update(
        parameters=[parameter.name for parameter in parameters], seeds=seeds, all_seeds=list(record["seeds"]),
        second_order=record["second_order"], description=describe_metric(metric, populated), metric=metric,
        units=info["variables"][metric.variable]["units"],
    )
    return result


def indices_table(result):
    """The indices of a number per run as rows of a CSV: one per parameter."""
    mean = result["mean"]
    table = pd.DataFrame({
        "parameter": result["parameters"],
        "S1": mean["S1"], "S1_conf95": mean["S1_conf"], "ST": mean["ST"], "ST_conf95": mean["ST_conf"],
        "ST_minus_S1": mean["ST"] - mean["S1"],
    })
    if result["second_order"]:
        for k, name in enumerate(result["parameters"]):
            table[f"S2_with_{name}"] = [mean["S2"][min(j, k), max(j, k)] if j != k else np.nan for j in range(len(result["parameters"]))]
    if "each" in result:
        for key in ("S1", "ST"):
            for s, seed in enumerate(result["seeds"]):
                table[f"{key}_seed_{seed}"] = result["each"][key][s]
    return table


def cell_dataset(result):
    """The maps of indices as a netCDF dataset: S1 and ST (parameter, lat, lon), their range across seeds, the
    share from chance, and the climate they are compared with."""
    lat, lon = result["lat"], result["lon"]
    shape = (lat.size, lon.size)

    def on_grid(values):
        grid = np.full(lat.size * lon.size, np.nan)
        grid[result["cells"]] = values
        return grid.reshape(shape)

    coords = {"parameter": result["parameters"], "lat": lat, "lon": lon}
    data = {}
    for key in ("S1", "ST"):
        data[key] = (("parameter", "lat", "lon"), np.array([on_grid(row) for row in result["mean"][key]]))
        if "range" in result:
            data[f"{key}_seed_range"] = (("parameter", "lat", "lon"), np.array([on_grid(row) for row in result["range"][key]]))
    if "chance" in result:
        data["chance_share"] = (("lat", "lon"), on_grid(result["chance"]))
    for name, (label, units, values) in result["climate"].items():
        data[f"{name}_mean"] = (("lat", "lon"), on_grid(values), {"long_name": label, "units": units})
    dataset = xr.Dataset(data, coords=coords)
    dataset.attrs["description"] = result["description"]
    return dataset
