"""The results views of a calibration: Optuna's figures of its study, and the distributions of the offsets over the trials
(how well the data tell each offset). Optuna samples dT_1 and the gaps; the offsets of the cells follow from them
(calibration_engine.offsets_from), and the distributions are of the offsets."""

import warnings

import numpy as np
import optuna
import optuna.visualization as vis
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from .calibration_engine import CONSTRAINT, REGIME, front, open_study, read_calibration, trials_table
from .plots import COMPARED, GRID, MODELLED, OBSERVED, _base_layout

# Said by Optuna whenever a target is given to PED-ANOVA; ours is given the right way (results_figure)
warnings.filterwarnings("ignore", message="PedAnovaImportanceEvaluator computes the importances of params to achieve low")
DOCS = "https://optuna.readthedocs.io/en/stable/reference/visualization/generated/optuna.visualization.{}.html"
# {kind: (label, what it shows, Optuna's function or None for ours, whether it is of one objective)}
FIGURES = {
    "distributions": ("Distributions of the calibrated values", "Each offset and model parameter calibrated, in all the trials "
                      "(grey), in the best tenth of them by the objective chosen (blue) and on the Pareto front (red). A narrow "
                      "spread of the best means the data tell the value well; a wide one, that they hardly do (it is not "
                      "identified).", None, True),
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
    "boundary_cv": ("Epidemic or endemic: year-to-year variability", "Each calibrated value against the coefficient of "
                    "variation of the yearly cases of the trial (the median over its seeds): low when every year has about as "
                    "many cases (endemic), high when outbreak years alternate with quiet ones (epidemic). Scale-free, so it "
                    "compares sites. Trials where transmission died out in red.", None, False),
    "boundary_fade": ("Epidemic or endemic: fade-out", "Each calibrated value against the share of the months of the trial "
                      "with no new case (the median over its seeds): 0 when transmission never stops (endemic), high when it "
                      "fades out between outbreaks (epidemic) or dies out. Trials where transmission died out in red.", None, False),
    "boundary_pairs": ("Epidemic or endemic, by pairs", "The trials over each pair of calibrated values (the first five), "
                       "coloured by their fade-out share (darker: more months without cases); those where transmission died "
                       "out as red crosses. Where the colour changes is the transition between endemic and epidemic "
                       "behaviour, in two dimensions.", None, False),
}
INFEASIBLE_NOTE = ("Trials where transmission died out are included with the values a series that does not vary scores "
                   "(correlation 0, the relative RMSE of a constant series)")
BEST_SHARE = 0.1  # The best tenth of the trials, in the distributions
HEIGHT = 520


class ResultsError(ValueError):
    """A figure that cannot be drawn for this calibration yet, saying why."""


def figure_help(kind):
    """(what the figure shows, its Optuna documentation or None)."""
    _, text, function, _ = FIGURES[kind]
    if function and kind not in ("timeline", "pareto"):
        text = f"{text} {INFEASIBLE_NOTE}."
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
    feasible = [trial for trial in complete if trial.user_attrs.get(CONSTRAINT, (-1.0,))[0] <= 0]
    if kind == "distributions":
        figure = distributions_figure(record, feasible, index, set(front(study, trials_table(folder))), complete)
    elif kind in ("boundary_cv", "boundary_fade"):
        figure = boundary_figure(record, complete, "annual_cv" if kind == "boundary_cv" else "fade_out")
    elif kind == "boundary_pairs":
        figure = boundary_pairs_figure(record, complete)
    elif kind == "pareto":
        if len(names) < 2:
            raise ResultsError("the Pareto front needs two objectives or more; with one, the best trial is its front")
        shown = names[:3]
        # Infeasible trials (transmission died out) in grey, out of the front
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


def value_panels(record):
    """[(title, value of a trial, axis title, line at)] of each calibrated value: the offsets of the temperature in °C, the
    model parameters in the units of their sliders (log-uniform ones as log10)."""
    temperature = record.get("temperature")
    panels = []  # (title, value of a trial, axis title, line at)
    if temperature:
        for k in range(len(temperature["cells"])):
            key = f"dT_{k + 1}"
            panels.append((f"dT{k + 1}: {_cell(record, k)}, mean {temperature['means'][k]:.2f} °C",
                           lambda trial, key=key: trial.user_attrs.get(key, np.nan), f"dT{k + 1} [°C]", 0.0))
    for parameter in record.get("parameters", []):
        name, log = parameter["name"], parameter["distribution"] == "loguniform"
        panels.append((f"{name} ({'log-uniform' if log else 'uniform'}, {parameter['low']:.4g} to {parameter['high']:.4g})",
                       lambda trial, name=name, log=log: (np.log10(trial.params[name]) if log else trial.params[name])
                       if name in trial.params else np.nan, f"log10 of {name}" if log else name, None))
    if not panels:
        raise ResultsError("this calibration has nothing calibrated to show")
    return panels


def distributions_figure(record, complete, index, front, every_trial=None):
    """A histogram of each calibrated value over the trials: all, the best tenth by objective `index`, and the Pareto
    front. complete: the feasible completed trials, of which the best tenth is taken; every_trial: all the completed ones,
    feasible or not, for "all trials" (complete if None)."""
    panels = value_panels(record)
    every_trial = complete if every_trial is None else every_trial
    if not complete:
        raise ResultsError("no trial is feasible yet: in all of them transmission died out (see Where transmission dies out)")
    objective = record["objectives"][index]
    maximize = objective["direction"] == "maximize"
    values = np.array([trial.values[index] for trial in complete])
    order = np.argsort(-values if maximize else values)
    best = {complete[i].number for i in order[:max(1, int(round(BEST_SHARE * len(complete))))]}
    columns = min(3, len(panels))
    rows = -(-len(panels) // columns)
    figure = make_subplots(rows=rows, cols=columns, subplot_titles=[title for title, _, _, _ in panels], vertical_spacing=0.18,
                           horizontal_spacing=0.08)
    for k, (_, value_of, axis_title, line_at) in enumerate(panels):
        row, column = k // columns + 1, k % columns + 1
        every = np.array([value_of(trial) for trial in every_trial], dtype="f8")
        edges = np.histogram_bin_edges(every[np.isfinite(every)], bins=20)
        bins = {"start": float(edges[0]), "end": float(edges[-1]), "size": float(edges[1] - edges[0]) or 1.0}
        for group, colour, label in ((None, COMPARED, "All trials"), (best, OBSERVED, f"Best {BEST_SHARE:.0%} by {objective['name']}")):
            shown = every if group is None else np.array([value_of(trial) for trial in complete if trial.number in group], dtype="f8")
            figure.add_trace(go.Histogram(x=shown, xbins=bins, histnorm="percent", marker={"color": colour}, opacity=0.6, name=label,
                                          legendgroup=label, showlegend=k == 0,
                                          hovertemplate=f"{label}: %{{y:.0f}}% of them at %{{x}}<extra></extra>"), row=row, col=column)
        on_front = [value_of(trial) for trial in complete if trial.number in front]
        figure.add_trace(go.Scatter(x=on_front, y=[0] * len(on_front), mode="markers", name="Pareto front",
                                    marker={"color": MODELLED, "size": 10, "symbol": "line-ns-open", "line": {"width": 3}},
                                    legendgroup="front", showlegend=k == 0, hovertemplate="Pareto front: %{x:.4g}<extra></extra>"),
                         row=row, col=column)
        if line_at is not None:
            figure.add_vline(x=line_at, line={"color": GRID, "dash": "dot"}, row=row, col=column)
        figure.update_xaxes(title_text=axis_title, gridcolor=GRID, row=row, col=column)
        figure.update_yaxes(title_text="% of the trials" if column == 1 else None, gridcolor=GRID, row=row, col=column)
    figure.update_layout(_base_layout(), plot_bgcolor="white", barmode="overlay", height=max(HEIGHT, 300 * rows + 120),
                         legend={"orientation": "h", "x": 0.5, "xanchor": "center", "y": -0.15, "yanchor": "top"})
    figure.update_annotations(font={"size": 12})
    return figure



REGIME_AXES = {"annual_cv": "CV of the yearly cases", "fade_out": "share of months without cases"}
FADE_SCALE = [[0.0, "#cfe1f2"], [1.0, "#0b3c6e"]]  # One hue, light (never fades out) to dark (mostly faded out)


def _regime_trials(complete):
    known = [trial for trial in complete if trial.user_attrs.get(REGIME)]
    if not known:
        raise ResultsError("no trial records its regime: calibrations made since it was added do (they write the new cases)")
    return known


def _died(trial):
    return trial.user_attrs.get(CONSTRAINT, (-1.0,))[0] > 0


def boundary_figure(record, complete, measure):
    """Each calibrated value against a measure of the regime of the trials (calibration_engine.regime), those where
    transmission died out (infeasible) in red and the others in blue."""
    panels = value_panels(record)
    known = _regime_trials(complete)
    axis = REGIME_AXES[measure]
    columns = min(3, len(panels))
    rows = -(-len(panels) // columns)
    figure = make_subplots(rows=rows, cols=columns, subplot_titles=[title for title, _, _, _ in panels], vertical_spacing=0.2,
                           horizontal_spacing=0.08)
    groups = (([t for t in known if not _died(t)], OBSERVED, "Transmission persisted"),
              ([t for t in known if _died(t)], MODELLED, "Transmission died out (infeasible)"))
    for k, (_, value_of, axis_title, _) in enumerate(panels):
        row, column = k // columns + 1, k % columns + 1
        for trials, colour, label in groups:
            y = [trial.user_attrs[REGIME].get(measure) for trial in trials]
            figure.add_trace(go.Scatter(x=[value_of(trial) for trial in trials], y=[np.nan if v is None else v for v in y],
                                        mode="markers", name=label, legendgroup=label, showlegend=k == 0,
                                        marker={"color": colour, "size": 7, "opacity": 0.75},
                                        text=[f"trial {trial.number}" for trial in trials],
                                        hovertemplate=f"%{{text}}: {axis_title} %{{x:.4g}}, {axis} %{{y:.3g}}<extra>{label}</extra>"),
                             row=row, col=column)
        figure.update_xaxes(title_text=axis_title, gridcolor=GRID, row=row, col=column)
        figure.update_yaxes(title_text=axis if column == 1 else None, gridcolor=GRID, row=row, col=column,
                            **({"range": [-0.05, 1.05]} if measure == "fade_out" else {"rangemode": "tozero"}))
    figure.update_layout(_base_layout(), plot_bgcolor="white", height=max(HEIGHT, 300 * rows + 120),
                         legend={"orientation": "h", "x": 0.5, "xanchor": "center", "y": -0.15, "yanchor": "top"})
    figure.update_annotations(font={"size": 12})
    return figure


def boundary_pairs_figure(record, complete):
    """The trials over each pair of the first five calibrated values, coloured by their fade-out share; those where
    transmission died out as red crosses."""
    shown = value_panels(record)[:5]
    if len(shown) < 2:
        raise ResultsError("pairs need two calibrated values or more; see the fade-out against each value")
    known = _regime_trials(complete)
    alive, dead = [t for t in known if not _died(t)], [t for t in known if _died(t)]
    combos = [(a, b) for a in range(len(shown)) for b in range(a + 1, len(shown))]
    columns = min(3, len(combos))
    rows = -(-len(combos) // columns)
    figure = make_subplots(rows=rows, cols=columns, subplot_titles=[f"{shown[b][2]} against {shown[a][2]}" for a, b in combos],
                           vertical_spacing=0.2, horizontal_spacing=0.1)
    for k, (a, b) in enumerate(combos):
        row, column = k // columns + 1, k % columns + 1
        fade = [trial.user_attrs[REGIME].get("fade_out") for trial in alive]
        figure.add_trace(go.Scatter(
            x=[shown[a][1](t) for t in alive], y=[shown[b][1](t) for t in alive], mode="markers", name="Transmission persisted",
            legendgroup="alive", showlegend=k == 0, text=[f"trial {t.number}" for t in alive],
            marker={"color": [np.nan if v is None else v for v in fade], "colorscale": FADE_SCALE, "cmin": 0, "cmax": 1, "size": 8,
                    "line": {"color": "white", "width": 1},
                    **({"colorbar": {"title": {"text": "months<br>without cases", "font": {"size": 11}}, "thickness": 12}} if k == 0 else {})},
            hovertemplate=f"%{{text}}: {shown[a][2]} %{{x:.4g}}, {shown[b][2]} %{{y:.4g}}, fade-out %{{marker.color:.2f}}<extra></extra>"),
            row=row, col=column)
        figure.add_trace(go.Scatter(
            x=[shown[a][1](t) for t in dead], y=[shown[b][1](t) for t in dead], mode="markers",
            name="Transmission died out (infeasible)", legendgroup="dead", showlegend=k == 0, text=[f"trial {t.number}" for t in dead],
            marker={"color": MODELLED, "symbol": "x", "size": 8},
            hovertemplate=f"%{{text}}: died out, {shown[a][2]} %{{x:.4g}}, {shown[b][2]} %{{y:.4g}}<extra></extra>"), row=row, col=column)
        figure.update_xaxes(title_text=shown[a][2], gridcolor=GRID, row=row, col=column)
        figure.update_yaxes(title_text=shown[b][2], gridcolor=GRID, row=row, col=column)
    figure.update_layout(_base_layout(), plot_bgcolor="white", height=max(HEIGHT, 300 * rows + 120),
                         legend={"orientation": "h", "x": 0.5, "xanchor": "center", "y": -0.15, "yanchor": "top"})
    figure.update_annotations(font={"size": 12})
    return figure
