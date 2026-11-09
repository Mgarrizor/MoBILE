"""How well the model matches the observations: the two are paired on the coordinates they share (the same periods, months,
seasons, years or age bands), pairs with a missing value on either side are left out, and metrics are computed on the
pairs. The scale-free metrics do not depend on the level of either series, e.g. on how many of the cases are reported:
the correlation compares their timing only; the RMSE of the series each divided by its mean also compares the size of
their swings. (The RMSE of standardised series is not given: it carries the same information as the correlation,
RMSE² = 2 (n − 1) / n × (1 − r).) Lower is better for the RMSEs and the size of the bias, higher for the correlation
(DIRECTIONS, for the objectives)."""

import numpy as np

from .calibration_data import SHAPES, DataError, period_kind

METRICS = {
    "rmse": "RMSE: root mean square of model − data, in the units of the data",
    "rmse_relative": "RMSE of the series each divided by its mean: scale-free, compares timing and the size of the swings",
    "correlation": "Correlation (Pearson): 1 for the same timing, 0 for none, −1 for the opposite: scale-free",
    "bias": "Bias: mean of model − data, in the units of the data",
}
DIRECTIONS = {"rmse": "minimize", "rmse_relative": "minimize", "correlation": "maximize", "bias": "zero"}
KEYS = {"dated": ("start", "end"), "climatology": ("month",), "season": ("season",), "yearly": ("year",),
        "age": ("age_lower", "age_upper"), "single": ()}


def _keys(observations):
    index = observations.index
    columns = KEYS[observations.shape]
    if not columns:
        return [()]
    return list(zip(*[index[column].astype(str) if column in ("start", "end") else index[column].astype(float).fillna(-1)
                      for column in columns]))


def pair(model, data):
    """(model values, data values, labels) on the coordinates the two share, without missing values. Raises DataError
    saying what to change when they cannot be paired."""
    if model.shape != data.shape:
        raise DataError(f"the model gives {SHAPES[model.shape].split(':')[0].lower()} values and the data "
                        f"{SHAPES[data.shape].split(':')[0].lower()} values: process them into the same shape")
    if model.shape == "dated":
        model_covers, data_covers = period_kind(model), period_kind(data)
        if model_covers != data_covers:
            raise DataError(f"the model gives values by {model_covers or 'mixed periods'} and the data by "
                            f"{data_covers or 'mixed periods'}: aggregate the {'model' if model_covers in ('day', 'week') else 'data'} "
                            f"into the periods of the other")
    data_at = {key: i for i, key in enumerate(_keys(data))}
    model_rows, data_rows = [], []
    for i, key in enumerate(_keys(model)):
        if key in data_at:
            model_rows.append(i)
            data_rows.append(data_at[key])
    if not model_rows:
        raise DataError("the model and the data have no period (or month, season, year, age band) in common")
    m, d = model.values[model_rows], data.values[data_rows]
    keep = np.isfinite(m) & np.isfinite(d)
    if not keep.any():
        raise DataError("every period in common has a missing value on one side")
    labels = [data.label(j) for j, k in zip(data_rows, keep) if k]
    return m[keep], d[keep], labels


def metrics(model_values, data_values):
    """{metric: value} of paired values. The relative RMSE is None (not defined) if a mean is not positive, the
    correlation if a series does not vary."""
    difference = model_values - data_values
    result = {"n": int(len(difference)), "rmse": float(np.sqrt(np.mean(difference**2))), "bias": float(np.mean(difference))}
    m_mean, d_mean = model_values.mean(), data_values.mean()
    result["rmse_relative"] = (float(np.sqrt(np.mean((model_values / m_mean - data_values / d_mean) ** 2)))
                               if m_mean > 0 and d_mean > 0 else None)
    varies = len(difference) > 1 and np.std(model_values) > 0 and np.std(data_values) > 0
    result["correlation"] = float(np.corrcoef(model_values, data_values)[0, 1]) if varies else None
    return result
