"""The analysis of the runs of a sensitivity analysis: the outputs read and reduced to the number (or map) analysed,
kept in the folder of the analysis, and their Sobol indices, for the mean over seeds and for each seed.

<analysis folder>/metrics/<key>/ holds, for one way of reducing the outputs (metric.json), the values of every run of
each seed (seed_<seed>.npy, one row per run) and, for maps, the cells they are of (cells.npy, flat indices on the
grid), and month by month, the first day of the months (months.npy). Analysing them again in another way, or with the indices of another parameter on show, does not read the
runs again.
"""

import hashlib
import json
import time
import warnings
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
    days = "the days of each month" if metric.by_month else "the days"
    text = metric.variable + (f", {time} over {days}{window}{months}" if time else f", every day{window}{months}")
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


def _month_starts(times, metric, first, last):
    """The first day of each month of the window with days in the months of the metric, as resample gives them."""
    days = np.asarray(times[first:last], dtype="datetime64[D]")
    months = np.unique(days.astype("datetime64[M]"))
    chosen = set(metric.months or range(1, 13))
    return np.array([month for month in months if int(str(month)[5:7]) in chosen], dtype="datetime64[D]")


def analysis_mask(record, info):
    """The simulated cells of the analysis on the coordinates of its outputs (lat, lon), as booleans."""
    grid = read_grid(record["inputs"]["pop_file"], record["inputs"]["area_file"], record["region"])
    if grid is None:
        raise ValueError("The region of the analysis is not on its population file any more.")
    template = xr.DataArray(np.zeros((info["lat"].size, info["lon"].size)), dims=("lat", "lon"), coords={"lat": info["lat"], "lon": info["lon"]})
    return mask_like(template, grid)


def extract(folder, record, metric, seeds, info, mask, progress=None):
    """({seed: values of every run, one row per run in the order of the samples}, the flat indices of the cells for a
    map or month by month (None for a number per run), the first day of each month (None but month by month)), from
    the outputs or, if read before, from metrics/. Month by month, the values of a seed are (runs, months, cells),
    left on disk until used.

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
    months = _month_starts(info["time"], metric, first, last) if metric.by_month else None
    if months is not None:
        if months.size == 0:
            raise ValueError("No day of the output is in the months chosen.")
        np.save(store / "months.npy", months)
    count = sample_count(folder)
    todo = [seed for seed in seeds if not (store / f"seed_{seed}.npy").is_file()]
    if progress is not None:
        done = count * (len(seeds) - len(todo))  # Not begin(), which would forget a cancel pressed meanwhile
        progress.update(total=count * len(seeds), done=done, done_before=done, failed=0, started=time.time(), message="Reading")
    for seed in todo:
        temporary = store / f"seed_{seed}.tmp.npy"
        if months is not None:
            # Runs × months × cells can be gigabytes: written to disk as it is read
            values = np.lib.format.open_memmap(temporary, mode="w+", dtype="float32", shape=(count, months.size, cells.size))
        else:
            values = []
        for index in range(count):
            if progress is not None and progress.cancelled:
                del values
                temporary.unlink(missing_ok=True)
                raise InterruptedError("Reading cancelled.")
            path = Path(folder) / RUNS / run_name(seed, index) / "output" / "output.nc"
            reduced = reduce_field(_read(path, group, metric.variable, info, first, last), metric, mask)
            if months is not None:
                values[index] = reduced.values.reshape(months.size, -1)[:, cells]
            else:
                values.append(reduced.values.ravel()[cells] if cells is not None else float(reduced))
            if progress is not None:
                progress.count("done")
        if months is not None:
            values.flush()
            del values
        else:
            np.save(temporary, np.asarray(values, dtype="float32" if cells is not None else "float64"))
        temporary.replace(store / f"seed_{seed}.npy")  # Only whole seeds are kept
    if months is not None:
        return {seed: np.load(store / f"seed_{seed}.npy", mmap_mode="r") for seed in seeds}, cells, months
    return {seed: np.load(store / f"seed_{seed}.npy").astype("float64") for seed in seeds}, cells, None


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


PERCENTILES = (10, 25, 50, 75, 90)


def monthly_analysis(parameters, values, second_order, seed=None):
    """Indices month by month. values is a list over the seeds of (runs, months, cells). For each month, the indices of
    each cell for the mean over seeds, summed up by their PERCENTILES across the cells ('spread', (months, parameters,
    percentiles)); the indices of the mean over the cells with bootstrap confidence intervals ('line', (months,
    parameters)); with several seeds, those of each seed alone ('each', (months, seeds, parameters)); and the cells
    with an index ('cells_used')."""
    months, d = values[0].shape[1], len(parameters)
    spread = {key: np.full((months, d, len(PERCENTILES)), np.nan) for key in ("S1", "ST")}
    line = {key: np.full((months, d), np.nan) for key in ("S1", "S1_conf", "ST", "ST_conf")}
    each = {key: np.full((months, len(values), d), np.nan) for key in ("S1", "ST")}
    used = np.zeros(months, int)
    for m in range(months):
        Y = np.stack([np.asarray(seed_values[:, m, :], dtype="float64") for seed_values in values])
        mean = Y.mean(axis=0)
        cells = analyse_cells(parameters, mean, second_order)
        used[m] = int(np.isfinite(cells["ST"][0]).sum())
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)  # A month without any cell that changes
            for key in ("S1", "ST"):
                spread[key][m] = np.nanpercentile(cells[key], PERCENTILES, axis=1).T
            overall = np.nanmean(mean, axis=1)
            if np.ptp(overall) > 0:
                indices = analyse(parameters, overall, second_order, seed=seed)
                for key in line:
                    line[key][m] = indices[key]
            if len(values) > 1:
                for s, seed_Y in enumerate(Y):
                    alone = analyse_cells(parameters, np.nanmean(seed_Y, axis=1)[:, None], second_order)
                    for key in ("S1", "ST"):
                        each[key][m, s] = alone[key][:, 0]
    result = {"kind": "months", "spread": spread, "line": line, "cells_used": used}
    if len(values) > 1:
        result["each"] = each
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
    values, cells, months = extract(folder, record, metric, seeds, info, mask, progress)
    parameters = study_parameters(record)
    if months is not None:
        result = monthly_analysis(parameters, [values[seed] for seed in seeds], record["second_order"], seed=record["sample_seed"])
        result["months"] = months
        result["cells"] = cells
    elif cells is None:
        result = scalar_analysis(parameters, np.array([values[seed] for seed in seeds]), record["second_order"], seed=record["sample_seed"])
    else:
        Y = np.array([values[seed] for seed in seeds])
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


def monthly_table(result):
    """The indices month by month as rows of a CSV: one per month, parameter and index."""
    rows = []
    for m, month in enumerate(result["months"]):
        for j, name in enumerate(result["parameters"]):
            for key in ("S1", "ST"):
                row = {"month": str(month)[:7], "parameter": name, "index": key}
                row.update({f"p{p}_across_cells": value for p, value in zip(PERCENTILES, result["spread"][key][m, j])})
                row.update({"of_spatial_mean": result["line"][key][m, j], "of_spatial_mean_conf95": result["line"][f"{key}_conf"][m, j],
                            "cells": result["cells_used"][m]})
                if "each" in result:
                    row.update({f"of_spatial_mean_seed_{seed}": result["each"][key][m, s, j] for s, seed in enumerate(result["seeds"])})
                rows.append(row)
    return pd.DataFrame(rows)


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
