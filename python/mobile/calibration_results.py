"""The results views of a calibration: Optuna's figures of its study, and the distributions of the offsets over the trials
(how well the data tell each offset). Optuna samples dT_1 and the gaps; the offsets of the cells follow from them
(calibration_engine.offsets_from), and the distributions are of the offsets."""

import warnings

import numpy as np
import optuna
import optuna.visualization as vis
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from .calibration_engine import open_study, read_calibration
from .plots import COMPARED, GRID, MODELLED, OBSERVED, _base_layout

# Said by Optuna whenever a target is given to PED-ANOVA; ours is given the right way (results_figure)
warnings.filterwarnings("ignore", message="PedAnovaImportanceEvaluator computes the importances of params to achieve low")
DOCS = "https://optuna.readthedocs.io/en/stable/reference/visualization/generated/optuna.visualization.{}.html"
# {kind: (label, what it shows, Optuna's function or None for ours, whether it is of one objective)}
FIGURES = {
    "distributions": ("Distributions of the offsets", "The offset of each cell in all the trials (grey), in the best tenth of them "
                      "by the objective chosen (blue) and on the Pareto front (red). A narrow spread of the best means the data "
                      "tell the offset well; a wide one, that they hardly do (it is not identified).", None, True),
    "pareto": ("Pareto front", "Each trial by its objectives (two or three, the first ones): the front, the trials no other beats "
               "on every objective, are the best trade-offs.", "plot_pareto_front", False),
    "importances": ("Parameter importances", "How much each sampled parameter matters for doing well on the objective: how "
                    "differently its values are spread in the best trials than in all of them (PED-ANOVA, Optuna's default). The "
                    "importances add up to 1.", "plot_param_importances", True),
    "slice": ("Slice", "The objective against each sampled parameter, trial by trial; the colour is the trial number, so the "
              "later trials show where the sampler converges.", "plot_slice", True),
    "parallel": ("Parallel coordinates", "Each trial a line across the sampled parameters, coloured by its objective.",
                 "plot_parallel_coordinate", True),
    "contour": ("Contour", "The objective over each pair of sampled parameters, interpolated between the trials.", "plot_contour", True),
    "rank": ("Rank", "Each pair of sampled parameters, the trials coloured by the rank of their objective.", "plot_rank", True),
    "edf": ("Empirical distribution (EDF)", "The share of the trials with at most each value of the objective: a curve rising early "
            "and steeply means many trials do well.", "plot_edf", True),
    "timeline": ("Timeline", "When each trial ran, how long, and how it ended (completed, failed).", "plot_timeline", False),
}
BEST_SHARE = 0.1  # The best tenth of the trials, in the distributions
HEIGHT = 520


class ResultsError(ValueError):
    """A figure that cannot be drawn for this calibration yet, saying why."""


def figure_help(kind):
    """(what the figure shows, its Optuna documentation or None)."""
    _, text, function, _ = FIGURES[kind]
    return text, DOCS.format(function) if function else None


def results_figure(folder, kind, index=0):
    """The figure `kind` of FIGURES for a calibration, of objective `index` where it is of one."""
    record = read_calibration(folder)
    study = open_study(folder, record)
    objectives = record["objectives"]
    names = [objective["name"] for objective in objectives]
    complete = study.get_trials(deepcopy=False, states=(optuna.trial.TrialState.COMPLETE,))
    if len(complete) < 2:
        raise ResultsError("the figures need at least two completed trials")
    name = names[index]
    sampled = sorted({parameter for trial in complete for parameter in trial.params})
    if kind == "distributions":
        figure = distributions_figure(record, complete, index, {trial.number for trial in study.best_trials})
    elif kind == "pareto":
        if len(names) < 2:
            raise ResultsError("the Pareto front needs two objectives or more; with one, the best trial is its front")
        shown = names[:3]
        figure = vis.plot_pareto_front(study, targets=lambda trial: tuple(trial.values[:len(shown)]), target_names=shown)
    elif kind == "contour" and len(sampled) < 2:
        raise ResultsError("a contour needs two sampled parameters or more")
    elif kind == "rank" and len(sampled) < 2:
        raise ResultsError("the rank plot needs two sampled parameters or more")
    elif kind == "timeline":
        figure = vis.plot_timeline(study)
    elif kind == "importances":
        # Optuna's PED-ANOVA looks at what gives the lowest values: an objective maximised is given to it negated, so that
        # its importances are of what gives the best values either way
        sign = -1.0 if objectives[index]["direction"] == "maximize" else 1.0
        figure = vis.plot_param_importances(study, target=lambda trial: sign * trial.values[index], target_name=name)
    else:
        function = getattr(vis, FIGURES[kind][2])
        figure = function(study, target=lambda trial: trial.values[index], target_name=name)
    title = FIGURES[kind][0] + (f": {name}" if FIGURES[kind][3] else "")
    figure.update_layout(title=title, height=HEIGHT, font={"size": 13})
    if kind != "distributions":
        figure.update_layout(template="plotly_white")  # Optuna's figures, on the white of the other figures of the GUI
    return figure


def _cell(record, k):
    cell = record["temperature"]["cells"][k]
    return f"{cell['lat']:g}°N, {cell['lon']:g}°E"


def distributions_figure(record, complete, index, front):
    """A histogram of each offset over the trials: all, the best tenth by objective `index`, and the Pareto front."""
    temperature = record.get("temperature")
    if not temperature:
        raise ResultsError("this calibration has no temperature offsets")
    objective = record["objectives"][index]
    maximize = objective["direction"] == "maximize"
    values = np.array([trial.values[index] for trial in complete])
    order = np.argsort(-values if maximize else values)
    best = {complete[i].number for i in order[:max(1, int(round(BEST_SHARE * len(complete))))]}
    keys = [f"dT_{k + 1}" for k in range(len(temperature["cells"]))]
    columns = min(3, len(keys))
    rows = -(-len(keys) // columns)
    figure = make_subplots(rows=rows, cols=columns, subplot_titles=[f"dT{k + 1}: {_cell(record, k)}, mean {temperature['means'][k]:.2f} °C"
                                                                    for k in range(len(keys))], vertical_spacing=0.18, horizontal_spacing=0.08)
    for k, key in enumerate(keys):
        row, column = k // columns + 1, k % columns + 1
        every = np.array([trial.user_attrs.get(key, np.nan) for trial in complete])
        edges = np.histogram_bin_edges(every[np.isfinite(every)], bins=20)
        bins = {"start": float(edges[0]), "end": float(edges[-1]), "size": float(edges[1] - edges[0])}
        for group, colour, label in ((None, COMPARED, "All trials"), (best, OBSERVED, f"Best {BEST_SHARE:.0%} by {objective['name']}")):
            shown = every if group is None else np.array([trial.user_attrs.get(key, np.nan) for trial in complete if trial.number in group])
            figure.add_trace(go.Histogram(x=shown, xbins=bins, histnorm="percent", marker={"color": colour}, opacity=0.6, name=label,
                                          legendgroup=label, showlegend=k == 0,
                                          hovertemplate=f"{label}: %{{y:.0f}}% of them at %{{x}} °C<extra></extra>"), row=row, col=column)
        on_front = [trial.user_attrs.get(key) for trial in complete if trial.number in front]
        figure.add_trace(go.Scatter(x=on_front, y=[0] * len(on_front), mode="markers", name="Pareto front",
                                    marker={"color": MODELLED, "size": 10, "symbol": "line-ns-open", "line": {"width": 3}},
                                    legendgroup="front", showlegend=k == 0, hovertemplate="Pareto front: %{x:.2f} °C<extra></extra>"),
                         row=row, col=column)
        figure.add_vline(x=0, line={"color": GRID, "dash": "dot"}, row=row, col=column)
        figure.update_xaxes(title_text="offset [°C]", gridcolor=GRID, row=row, col=column)
        figure.update_yaxes(title_text="% of the trials" if column == 1 else None, gridcolor=GRID, row=row, col=column)
    figure.update_layout(_base_layout(), plot_bgcolor="white", barmode="overlay", height=max(HEIGHT, 300 * rows + 120),
                         legend={"orientation": "h", "x": 0.5, "xanchor": "center", "y": -0.15, "yanchor": "top"})
    figure.update_annotations(font={"size": 12})
    return figure

