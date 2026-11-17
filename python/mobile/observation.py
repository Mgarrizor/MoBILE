"""The observational model: what surveillance records of the cases a model makes. Reported cases are drawn around a
reporting fraction of the model's cases, Y_t ~ negative binomial(mean rho C_t, dispersion k): a count, zeros allowed,
its variance rho C + (rho C)^2 / k (a reporting fraction that varies from month to month around rho, with a coefficient
of variation 1 / sqrt(k)). Many reported series are drawn from one model run, each processed exactly as the observations
are (the steps of an objective: log, climatology, filters, ...); their median is the model's series an objective's
metric compares, and their spread a band, scored against the observations by the CRPS and by coverage.

Plain functions on arrays and Observations, independent of the GUI and of a calibration: the engine uses them for each
trial, the GUI to show what the engine kept.

The draws go through the steps as one matrix (draws x months) for the steps the objectives use (log, anomaly,
climatology by month, a frequency filter with its ends cut or kept), on a series with no gap: every draw has the same
months, the same filter ends, the same cut. Other steps, or a series with gaps, go draw by draw through the steps
themselves. The first draw is always also processed by the steps themselves and must agree.
"""

import numpy as np
import pandas as pd
from dataclasses import replace
from scipy import signal

from .calibration_data import DataError, drop_window, select_window
from .calibration_steps import TIME_UNITS, _design, apply_steps, edge_error_of, edge_reach, regular_series

DRAWS = 500  # Reported series drawn from each model run, by default
LEVELS = (2.5, 50.0, 97.5)  # Percentiles of the band: its low end, the median, its high end
MODEL = "negbin"


def draw(counts, rho, k, draws=DRAWS, seed=None):
    """(draws x months) reported counts, each month Y ~ negative binomial(mean rho * counts, dispersion k), independent."""
    counts = np.asarray(counts, dtype="f8")
    if not (0 < rho <= 1):
        raise DataError(f"the reporting fraction must be above 0 and at most 1: {rho}")
    if not k > 0:
        raise DataError(f"the dispersion must be above 0: {k}")
    if np.any(counts[np.isfinite(counts)] < 0):
        raise DataError("the model's cases cannot be negative")
    mean = rho * np.nan_to_num(counts)
    generator = np.random.default_rng(seed)
    # numpy's negative binomial: successes n = k, probability p = k / (k + mean); a mean of 0 gives 0
    values = generator.negative_binomial(k, k / (k + mean), size=(int(draws), len(mean))).astype("f8")
    values[:, ~np.isfinite(counts)] = np.nan
    return values


def crps(draws, observed):
    """The continuous ranked probability score of each value observed against the draws of it (draws x values), in the
    units of the values: mean |X - y| - mean |X - X'| / 2 (Gneiting & Raftery 2007); 0 for a sure and right forecast,
    the absolute error for draws all equal. NaN where the observation or all the draws are missing."""
    draws, observed = np.asarray(draws, dtype="f8"), np.asarray(observed, dtype="f8")
    scores = np.full(observed.shape, np.nan)
    for j, value in enumerate(observed):
        sample = draws[:, j][np.isfinite(draws[:, j])]
        if not np.isfinite(value) or not len(sample):
            continue
        sample = np.sort(sample)
        n = len(sample)
        spread = 2.0 * np.sum((2 * np.arange(1, n + 1) - n - 1) * sample) / n ** 2  # mean |X - X'| over all pairs
        scores[j] = np.mean(np.abs(sample - value)) - spread / 2.0
    return scores


def band(draws, levels=LEVELS):
    """(len(levels) x values) percentiles of the draws at each value (NaN where all the draws are missing)."""
    draws = np.asarray(draws, dtype="f8")
    out = np.full((len(levels), draws.shape[1]), np.nan)
    present = np.isfinite(draws).any(axis=0)
    if present.any():
        out[:, present] = np.nanpercentile(draws[:, present], levels, axis=0)
    return out


def coverage(low, high, observed):
    """The share of the values observed (not missing, with a band) that lie within [low, high]; NaN if none."""
    low, high, observed = (np.asarray(a, dtype="f8") for a in (low, high, observed))
    usable = np.isfinite(low) & np.isfinite(high) & np.isfinite(observed)
    return float(np.mean((observed[usable] >= low[usable]) & (observed[usable] <= high[usable]))) if usable.any() else float("nan")


# ---------------------------------------------------------------- the draws through the steps of an objective

def _batch_step(matrix, observations, step):
    """The matrix (draws x values, observations' index) through one step, as the step itself does each row: the result
    and the Observations of the first row as the step makes them (for the index), or None if the step is not one done
    here."""
    kind = step["kind"]
    if kind == "transform" and step.get("transform") in ("log", "log10", "anomaly"):
        if step["transform"] == "anomaly":
            return matrix - np.nanmean(matrix, axis=1, keepdims=True)
        offset = float(step.get("offset") or 0)
        log = np.log if step["transform"] == "log" else np.log10
        shifted = matrix + offset
        if np.any(shifted[np.isfinite(shifted)] <= 0):
            raise DataError("the log needs positive values: add an offset, e.g. 1 for counts with zeros")
        with np.errstate(divide="ignore", invalid="ignore"):
            return np.where(shifted > 0, log(np.where(shifted > 0, shifted, 1.0)), np.nan)
    if kind == "climatology" and step.get("by") == "month" and observations.shape == "dated":
        months = pd.to_datetime(observations.index["start"]).dt.month.to_numpy()
        return np.column_stack([np.nanmean(matrix[:, months == month], axis=1) for month in range(1, 13)])
    if kind == "filter" and observations.shape == "dated" and not np.isnan(matrix).any():
        series, positions, sample = regular_series(observations)
        if np.isnan(series).any() or len(positions) != matrix.shape[1]:
            return None  # Gaps: the steps themselves, draw by draw
        unit = TIME_UNITS[step["unit"]]
        short, long = float(step["short"]) * unit / sample, float(step["long"]) * unit / sample
        periods = {"low": (long,), "high": (short,), "band": (short, long)}.get(step["type"])
        if periods is None:
            return None
        sos = _design(step["type"], periods)
        n = matrix.shape[1]
        filtered = signal.sosfiltfilt(sos, matrix, axis=1)
        if step.get("edges", "keep") == "cut":
            start, end = edge_reach(step["type"], periods, n, edge_error_of(step))
            if n - start - end < 2 * max(periods):
                return None  # All cut: the steps themselves say so
            filtered[:, :start] = np.nan
            if end:
                filtered[:, n - end:] = np.nan
        return filtered
    return None


def _through(matrix, observations, steps, others=None):
    """(matrix after the steps, Observations of the first row after them): each step on all the rows at once where it
    can be done so, else row by row by the steps themselves. The first row is always also done by the steps themselves,
    for the index of the result, and must agree."""
    for step in steps:
        first = apply_steps(replace(observations, values=matrix[0].copy()), [step], others)
        batch = _batch_step(matrix, observations, step)
        if batch is None or batch.shape[1] != len(first.values):
            batch = np.vstack([first.values] + [apply_steps(replace(observations, values=row.copy()), [step], others).values
                                                for row in matrix[1:]])
        elif not np.allclose(batch[0], np.asarray(first.values, dtype="f8"), equal_nan=True, rtol=1e-9, atol=1e-12):
            raise DataError(f"the draws went through step {step['kind']} differently from the observations: please report it")
        matrix, observations = batch, first
    return matrix, observations


def _cut(matrix, observations, windows, part, parts):
    """The columns of the matrix (and its Observations) in a part of the period: the calibration (without any window)
    or one window."""
    index = observations.index.copy()
    keep = np.zeros(len(index), dtype=bool)
    marked = replace(observations, values=np.arange(len(index), dtype="f8"), extra={})
    if part == "calibration":
        for window in windows:
            marked = drop_window(marked, *window)
    else:
        marked = select_window(marked, *windows[parts.index(part)])
    keep[np.asarray(marked.values, dtype=int)] = True
    kept = replace(observations, values=np.asarray(observations.values)[keep], index=index[keep].reset_index(drop=True),
                   extra={key: np.asarray(value)[keep] for key, value in observations.extra.items()})
    return matrix[:, keep], kept


def process_draws(monthly, matrix, steps, validation=None, part=None, others=None):
    """The draws (draws x months, of the model's series `monthly`, an Observations whose steps so far made it so) through
    the rest of an objective's steps, as calibration_model.process_both does the model's series: with a time filter,
    filtered over the whole period up to its last filter, then cut to the part, the rest of the steps on the part;
    without, cut first. Returns (processed matrix, the Observations of the first draw processed: the index)."""
    from .calibration_model import _split_at_filter, validation_parts, validation_windows

    windows = validation_windows(validation)
    if not windows or part is None:
        return _through(matrix, replace(monthly, values=matrix[0].copy()), steps, others)
    parts = validation_parts(validation)
    split = _split_at_filter(steps)
    if split is None:
        cut_matrix, cut_obs = _cut(matrix, replace(monthly, values=matrix[0].copy()), windows, part, parts)
        return _through(cut_matrix, cut_obs, steps, others)
    before, after = split
    whole, whole_obs = _through(matrix, replace(monthly, values=matrix[0].copy()), before, others)
    cut_matrix, cut_obs = _cut(whole, whole_obs, windows, part, parts)
    return _through(cut_matrix, cut_obs, after, others)


def median_of(processed, observations):
    """The median series of the processed draws, as an Observations with their index (the model's series for a metric)."""
    with np.errstate(all="ignore"):
        middle = band(processed, (50.0,))[0]
    return replace(observations, values=middle, sd=None).with_note(f"median of {processed.shape[0]} reported series drawn "
                                                                    "from the model (observational model)")
