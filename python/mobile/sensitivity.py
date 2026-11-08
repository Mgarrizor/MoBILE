"""Sobol sensitivity analysis of the model parameters with SALib, for the Parameters tab.

The parameters are sampled by SALib as uniform on [0, 1], then mapped through the inverse of the cumulative
distribution of each, as in utils/Optuna_calibration/CA_methods.py: one way for the four distributions, of which
normal and log-normal are truncated to [low, high] so that no run gets a value out of range. The analysis needs
only the sample design and the model outputs, so it does not change with the distributions.
"""

import math
from dataclasses import dataclass

import numpy as np
from SALib.analyze import sobol as sobol_analyze
from SALib.analyze.sobol import first_order, total_order
from SALib.analyze.sobol import second_order as second_order_index
from SALib.sample import sobol as sobol_sample
from scipy.stats import truncnorm

# {name: label} of the distributions a parameter can be sampled from
DISTRIBUTIONS = {
    "uniform": "Uniform",
    "loguniform": "Log-uniform",
    "normal": "Normal (truncated)",
    "lognormal": "Log-normal (truncated)",
}
TIME_REDUCTIONS = ("sum", "mean", "max", "none")
SPACE_REDUCTIONS = ("mean", "sum", "none")
# Of the outputs by age band: each band analysed apart, or the age profile of the cases (counts from the rates
# per person in each band times the agents in it)
AGE_ANALYSES = ("bands", "under5", "mean_age")


@dataclass(frozen=True)
class SampledParameter:
    """A parameter to sample, between low and high. For normal, mean and sd are those of the parameter;
    for log-normal, those of its natural logarithm."""

    name: str
    distribution: str
    low: float
    high: float
    mean: float | None = None
    sd: float | None = None

    def problems(self):
        """What is wrong with the parameter, as sentences; empty if it can be sampled."""
        if self.distribution not in DISTRIBUTIONS:
            return [f"{self.name}: unknown distribution {self.distribution!r}"]
        values = [self.low, self.high] + ([self.mean, self.sd] if self.distribution in ("normal", "lognormal") else [])
        if any(value is None or not math.isfinite(value) for value in values):
            return [f"{self.name}: every bound{', mean and sd' if len(values) > 2 else ''} must be a number"]
        problems = []
        if not self.low < self.high:
            problems.append(f"{self.name}: the minimum must be below the maximum")
        if self.distribution in ("loguniform", "lognormal") and self.low <= 0:
            problems.append(f"{self.name}: a logarithmic distribution needs a minimum above 0")
        if self.distribution in ("normal", "lognormal") and self.sd <= 0:
            problems.append(f"{self.name}: the standard deviation must be above 0")
        if problems:
            return problems
        if self.distribution == "normal" and not self.low <= self.mean <= self.high:
            problems.append(f"{self.name}: the mean must be between the minimum and the maximum")
        if self.distribution == "lognormal" and not math.log(self.low) <= self.mean <= math.log(self.high):
            problems.append(
                f"{self.name}: the mean of ln(x) must be between ln(minimum) = {math.log(self.low):.4g} "
                f"and ln(maximum) = {math.log(self.high):.4g}"
            )
        return problems

    def from_unit(self, unit):
        """Values of the parameter for points of [0, 1], by the inverse of its cumulative distribution."""
        unit = np.asarray(unit, dtype="float64")
        if self.distribution == "uniform":
            return self.low + unit * (self.high - self.low)
        if self.distribution == "loguniform":
            return np.exp(math.log(self.low) + unit * (math.log(self.high) - math.log(self.low)))
        if self.distribution == "normal":
            return truncnorm.ppf(unit, (self.low - self.mean) / self.sd, (self.high - self.mean) / self.sd, loc=self.mean, scale=self.sd)
        low, high = math.log(self.low), math.log(self.high)
        return np.exp(truncnorm.ppf(unit, (low - self.mean) / self.sd, (high - self.mean) / self.sd, loc=self.mean, scale=self.sd))


def runs_per_sample(parameters, second_order=True):
    """Model runs for each of the N base samples: 2D + 2 with second-order indices, D + 2 without."""
    return (2 if second_order else 1) * len(parameters) + 2


def run_count(n, parameters, second_order=True, seeds=1):
    return n * runs_per_sample(parameters, second_order) * seeds


def run_count_formula(n, parameters, second_order=True, seeds=1):
    """The number of runs and where it comes from, e.g. 'N(2D+2) = 1024 × (2·6 + 2) = 14,336 runs'."""
    d = len(parameters)
    formula, numbers = ("N(2D+2)", f"{n:,} × (2·{d} + 2)") if second_order else ("N(D+2)", f"{n:,} × ({d} + 2)")
    if seeds > 1:
        formula, numbers = f"{formula} × seeds", f"{numbers} × {seeds}"
    return f"{formula} = {numbers} = {run_count(n, parameters, second_order, seeds):,} runs"


def design_problems(parameters, n, second_order=True):
    """What prevents sampling, as sentences; empty if nothing."""
    problems = []
    if len(parameters) < 2:
        problems.append("Choose at least two parameters to sample.")
    names = [parameter.name for parameter in parameters]
    if len(set(names)) != len(names):
        problems.append("A parameter is chosen twice.")
    for parameter in parameters:
        problems += parameter.problems()
    if not isinstance(n, int) or n < 2 or n & (n - 1):
        problems.append("N must be a power of 2, at least 2: Sobol sequences are balanced only then.")
    return problems


def unit_problem(parameters):
    """The problem as SALib sees it: every parameter on [0, 1], mapped to its distribution afterwards."""
    return {"num_vars": len(parameters), "names": [p.name for p in parameters], "bounds": [[0.0, 1.0]] * len(parameters)}


def sample(parameters, n, second_order=True, seed=None):
    """(points of [0, 1], parameter values): one row per run, one column per parameter, in the order SALib
    expects their outputs back."""
    problems = design_problems(parameters, n, second_order)
    if problems:
        raise ValueError(" ".join(problems))
    unit = sobol_sample.sample(unit_problem(parameters), n, calc_second_order=second_order, scramble=True, seed=seed)
    values = np.column_stack([parameter.from_unit(unit[:, j]) for j, parameter in enumerate(parameters)])
    return unit, values


@dataclass(frozen=True)
class Metric:
    """How a field of a run becomes the number, or the map or time series, analysed.

    The time window is the days from start to end (ISO dates, either open) and, if months is given, only those
    months of the year (1 to 12), so that wet and dry seasons can be analysed apart. With by_month, the days are
    reduced within each month of the window instead of over all of them, giving a value per month.

    With age, variable is a group of outputs by age band: "bands" analyses each band apart, keeping every cell;
    "under5" and "mean_age" analyse the share of the cases under 5 years old and their mean age."""

    variable: str
    time: str = "sum"
    space: str = "mean"
    start: str | None = None
    end: str | None = None
    months: tuple | None = None
    by_month: bool = False
    age: str | None = None

    def problems(self):
        problems = []
        if self.age is not None and self.age not in AGE_ANALYSES:
            problems.append(f"Unknown analysis by age {self.age!r}.")
        if self.age == "bands" and (self.time == "none" or self.space != "none" or self.by_month):
            problems.append("Age band by age band reduces the days and keeps every cell.")
        if self.age in ("under5", "mean_age") and self.time not in ("sum", "mean"):
            problems.append("The age profile of the cases needs their sum or mean over the days.")
        if self.time not in TIME_REDUCTIONS:
            problems.append(f"Unknown time reduction {self.time!r}.")
        if self.space not in SPACE_REDUCTIONS:
            problems.append(f"Unknown space reduction {self.space!r}.")
        if self.time == "none" and self.space == "none":
            problems.append("Reduce over time, space or both: a value for every cell and day cannot be analysed.")
        if self.by_month and (self.time == "none" or self.space != "none"):
            problems.append("Month by month reduces the days of each month and keeps every cell.")
        if self.months is not None and (not self.months or not set(self.months) <= set(range(1, 13))):
            problems.append("Months must be numbers from 1 to 12.")
        if self.start and self.end and np.datetime64(self.start) > np.datetime64(self.end):
            problems.append("The window starts after it ends.")
        return problems


def reduce_field(field, metric, mask=None):
    """The value analysed for one run, from its field on (time, lat, lon) or (lat, lon):
    a number if time and space are reduced, a (lat, lon) map if only time is, a (time) series if only space is.
    With by_month, time is reduced within each month: (time, ...) with the first day of each month as its time.
    Space reductions are over the cells of mask (lat, lon), the populated cells, when given."""
    problems = metric.problems()
    if problems:
        raise ValueError(" ".join(problems))
    if "time" in field.dims:
        field = field.sel(time=slice(metric.start, metric.end))
        if metric.months is not None:
            field = field.sel(time=field["time"].dt.month.isin(list(metric.months)))
        if field.sizes["time"] == 0:
            raise ValueError("No day of the output is in the time window.")
        if metric.by_month:
            field = getattr(field.resample(time="MS"), metric.time)(skipna=True)
            # Months of the window outside the months chosen come back empty from resample
            field = field.sel(time=field["time"].dt.month.isin(list(metric.months or range(1, 13))))
        elif metric.time != "none":
            field = getattr(field, metric.time)("time", skipna=True)
    if mask is not None:
        field = field.where(mask)
    if metric.space != "none":
        field = getattr(field, metric.space)(("lat", "lon"), skipna=True)
    return field


def _blocks(Y, d, second_order):
    """A, B, AB and BA of SALib's Sobol design, for outputs Y with one row per run (any columns)."""
    step = 2 * d + 2 if second_order else d + 2
    if Y.shape[0] % step:
        raise ValueError(f"{Y.shape[0]} outputs cannot come from a design of {d} parameters ({step} runs per sample).")
    A, B = Y[0::step], Y[step - 1::step]
    AB = [Y[j + 1::step] for j in range(d)]
    BA = [Y[j + 1 + d::step] for j in range(d)] if second_order else None
    return A, B, AB, BA


def analyse(parameters, Y, second_order=True, num_resamples=100, conf_level=0.95, seed=None):
    """Sobol indices of one output per run: {S1, S1_conf, ST, ST_conf} as arrays over the parameters, and
    with second order {S2, S2_conf} as matrices (upper triangle, NaN elsewhere). Confidence intervals by bootstrap."""
    Y = np.asarray(Y, dtype="float64")
    if not np.all(np.isfinite(Y)):
        raise ValueError(f"{int((~np.isfinite(Y)).sum())} of the {Y.size} outputs are not numbers.")
    indices = sobol_analyze.analyze(unit_problem(parameters), Y, calc_second_order=second_order,
                                    num_resamples=num_resamples, conf_level=conf_level, seed=seed)
    keys = ["S1", "S1_conf", "ST", "ST_conf"] + (["S2", "S2_conf"] if second_order else [])
    return {key: np.asarray(indices[key]) for key in keys}


def analyse_cells(parameters, Y, second_order=False):
    """Sobol indices of one output per run and cell, without confidence intervals (a bootstrap for every cell
    would take too long): {S1, ST} of shape (parameters, cells), and S2 of shape (parameters, parameters, cells).
    The estimators are SALib's, on outputs standardised cell by cell as SALib does; a cell whose output does not
    vary, or is not a number in every run, gets NaN."""
    Y = np.asarray(Y, dtype="float64")
    d = len(parameters)
    usable = np.all(np.isfinite(Y), axis=0) & (np.ptp(np.where(np.isfinite(Y), Y, 0), axis=0) > np.finfo(float).eps)
    cells = Y[:, usable]
    cells = (cells - cells.mean(axis=0)) / cells.std(axis=0)
    A, B, AB, BA = _blocks(cells, d, second_order)
    result = {"S1": np.full((d, Y.shape[1]), np.nan), "ST": np.full((d, Y.shape[1]), np.nan)}
    for j in range(d):
        result["S1"][j, usable] = first_order(A, AB[j], B)
        result["ST"][j, usable] = total_order(A, AB[j], B)
    if second_order:
        result["S2"] = np.full((d, d, Y.shape[1]), np.nan)
        for j in range(d):
            for k in range(j + 1, d):
                result["S2"][j, k, usable] = second_order_index(A, AB[j], AB[k], BA[j], B)
    return result
