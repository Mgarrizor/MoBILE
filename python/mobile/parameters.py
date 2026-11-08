"""The parameters of the &CONST namelist: defaults, slider ranges and groups, from parameters.yaml in the package.

Values are in the units of the model everywhere except on the sliders and in the sensitivity analysis, which use the
units shown (display): a rate per day is shown per year, and a tiny fraction as log10 of the value.
"""

import math
from functools import cache
from importlib import resources
from pathlib import Path

import yaml

# The tabs of the parameters, in order; the other groups are not shown and their parameters keep the compiled default
PARAMETER_GROUPS = ("Human", "Vector", "Hydro", "Demography", "Interventions")
DAYS_PER_YEAR = 365.0


@cache
def all_parameters():
    """{name: spec} of every parameter of &CONST, as in parameters.yaml."""
    return yaml.safe_load((Path(str(resources.files("mobile"))) / "parameters.yaml").read_text())["parameters"]


def shown_parameters():
    """{name: spec} of the parameters with a slider, in the order of the file."""
    return {name: spec for name, spec in all_parameters().items() if spec["group"] in PARAMETER_GROUPS}


def to_shown(name, value):
    """A value in the units of the model, in the units of its slider."""
    display = all_parameters()[name].get("display")
    if display == "per_year":
        return value * DAYS_PER_YEAR
    if display == "log10":
        return math.log10(value)
    return value


def to_model(name, value):
    """A value in the units of its slider, in the units of the model."""
    spec = all_parameters()[name]
    display = spec.get("display")
    if display == "per_year":
        value = value / DAYS_PER_YEAR
    elif display == "log10":
        value = 10.0**value
    return int(round(value)) if spec.get("type") == "integer" else float(value)


def slider_start(name):
    """Where the slider of a parameter starts, in the units shown: its default, or that of the parameter it follows."""
    spec = all_parameters()[name]
    followed = spec.get("starts_at")
    return to_shown(followed, all_parameters()[followed]["value"]) if followed else to_shown(name, spec["value"])


def namelist_value(name, value):
    """A value as written to the &CONST namelist: an integer for a Fortran integer, else a real."""
    if all_parameters()[name].get("type") == "integer":
        return str(int(round(value)))
    return repr(float(value))


def run_parameters(overrides):
    """{name: value as written} of a run: every shown parameter at its default, those in overrides at their value.
    The parameters not shown are left out, so that the model keeps their compiled default."""
    unknown = set(overrides) - set(shown_parameters())
    if unknown:
        raise ValueError(f"no such parameter in the GUI: {sorted(unknown)}")
    values = {name: spec["value"] for name, spec in shown_parameters().items()}
    values.update(overrides)
    return {name: namelist_value(name, value) for name, value in values.items()}
