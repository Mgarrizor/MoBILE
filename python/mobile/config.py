"""Run configuration: what is otherwise edited by hand at the top of run_MOBILE.sh."""

import os
import re
from dataclasses import dataclass, field, replace
from importlib import resources
from pathlib import Path

import yaml

from .region import region_problems

# The keys of a configuration file. Parameters, outputs and sliders are set in the GUI.
CONFIG_KEYS = {"mobile", "runs_dir", "project", "run", "inputs", "region"}
RUN_KEYS = {"disID", "mob", "nstep", "spin_up", "nagent", "seed", "threads"}
REQUIRED_INPUTS = {"rain_file", "temp_file", "pop_file", "area_file", "age_file", "const"}
OPTIONAL_INPUTS = {"mortality_file", "birthrate_file", "mortality_time_file", "imm_forcing"}
OPTIONAL_DEFAULTS = {"counterfactual": 0}

# The groups of the netCDF output
SLIDER_GROUPS = ("Human", "Vector", "Hydro", "Climate")

# character(len=200) in mo_control.f90; a namelist read truncates longer paths silently
MAX_PATH_LENGTH = 200


def default_sliders():
    """{name: {group, label, min, max}} of the sliders of the GUI, from sliders.yaml in the package."""
    return yaml.safe_load((Path(str(resources.files("mobile"))) / "sliders.yaml").read_text())["sliders"]


def default_params():
    """{name: value} of the compiled-in values of the slider parameters, from default_params.txt in the package."""
    return read_params(Path(str(resources.files("mobile"))) / "default_params.txt")


def example_config():
    """Path of the configuration shipped with the package: the example bundled with MoBILE."""
    return Path(str(resources.files("mobile") / "configs" / "test_run.yaml"))


class ConfigError(ValueError):
    """The configuration cannot give a valid run."""


def namelist_names(mobile, group):
    """Names in a namelist group, read from the source so they cannot go out of date."""
    source = (Path(mobile) / "src" / "mo_namelist.f90").read_text()
    statements = re.findall(
        rf"^\s*namelist\s*/{group}/((?:[^\n&]*&[^\n]*\n)*[^\n]*)", source, re.I | re.M
    )
    names = set()
    for statement in statements:
        code = " ".join(line.split("!")[0] for line in statement.splitlines())
        names.update(name for name in re.split(r"[,&\s]+", code) if name)
    return names


def read_params(path):
    """Read a params.txt file as {name: value}, keeping each value as written."""
    params = {}
    for line in Path(path).read_text().splitlines():
        line = line.split("!")[0].strip().rstrip(",").strip()
        if line:
            name, value = line.split("=", 1)
            params[name.strip()] = value.strip()
    return params


@dataclass(frozen=True)
class Config:
    mobile: Path
    runs_dir: Path
    run: dict
    inputs: dict
    params: dict = field(default_factory=dict)
    output: tuple | None = None
    project: str = ""  # Name shown in the app
    region: dict | None = None  # {north, west, south, east} to simulate; None for the whole grid

    @classmethod
    def load(cls, path=None, mobile=None):
        path = Path(path).resolve() if path else example_config()
        if not path.is_file():
            raise ConfigError(f"Configuration file not found: {path}")
        raw = yaml.safe_load(path.read_text()) or {}
        unknown = set(raw) - CONFIG_KEYS
        if unknown:
            raise ConfigError(
                f"{path}: unknown {sorted(unknown)}; a configuration has only {sorted(CONFIG_KEYS)}. "
                "Parameters, outputs and sliders are set in the GUI."
            )
        mobile = mobile or raw.get("mobile") or os.environ.get("MOBILE")
        if not mobile:
            raise ConfigError("MoBILE location unknown: run `export MOBILE=/path/to/MoBILE` or set `mobile` in the config")
        mobile = Path(mobile).expanduser().resolve()

        def resolve(value):
            expanded = str(value).replace("$MOBILE", str(mobile)).replace("${MOBILE}", str(mobile))
            expanded = os.path.expanduser(os.path.expandvars(expanded))
            return (path.parent / expanded).resolve()

        inputs = dict(OPTIONAL_DEFAULTS)
        for key, value in raw.get("inputs", {}).items():
            inputs[key] = value if key in OPTIONAL_DEFAULTS or value == "NONE" else str(resolve(value))
        config = cls(
            mobile=mobile,
            runs_dir=Path(raw.get("runs_dir", "runs")).expanduser().resolve(),
            run=dict(raw.get("run", {})),
            inputs=inputs,
            project=str(raw.get("project") or ""),
            region=raw.get("region"),
        )
        config.validate()
        return config

    def with_params(self, **params):
        config = replace(self, params={**self.params, **params})
        config.validate()
        return config

    def with_run(self, **run):
        config = replace(self, run={**self.run, **run})
        config.validate()
        return config

    def final_params(self):
        """Parameters of the run: the `const` file overridden by `params`."""
        final = read_params(self.inputs["const"])
        final.update({name: repr(value) for name, value in self.params.items()})
        return final

    def output_flags(self):
        """{flag: value} for every &OUTPUT flag, or None for the default output."""
        if self.output is None:
            return None
        names = namelist_names(self.mobile, "OUTPUT")
        return {name: name in self.output for name in sorted(names)}

    def validate(self):
        errors = []
        missing = RUN_KEYS - set(self.run)
        if missing:
            errors.append(f"run: missing {sorted(missing)}")
        unknown = set(self.run) - RUN_KEYS
        if unknown:
            errors.append(f"run: unknown {sorted(unknown)}")
        for key, value in self.run.items():
            if not isinstance(value, int) or isinstance(value, bool):
                errors.append(f"run: {key} must be an integer, got {value!r}")

        errors += region_problems(self.region)

        allowed = REQUIRED_INPUTS | OPTIONAL_INPUTS | set(OPTIONAL_DEFAULTS)
        unknown = set(self.inputs) - allowed
        if unknown:
            errors.append(f"inputs: unknown {sorted(unknown)}")
        missing = REQUIRED_INPUTS - set(self.inputs)
        if missing:
            errors.append(f"inputs: missing {sorted(missing)}")
        for key, value in self.inputs.items():
            if key in OPTIONAL_DEFAULTS or value == "NONE":
                continue
            if not Path(value).is_file():
                errors.append(f"inputs: {key} not found: {value}")
            if len(value) > MAX_PATH_LENGTH:
                errors.append(f"inputs: {key} is longer than {MAX_PATH_LENGTH} characters: {value}")
        if self.inputs.get("counterfactual") == 1 and not any(
            self.inputs.get(key, "NONE") != "NONE"
            for key in ("mortality_file", "birthrate_file", "mortality_time_file")
        ):
            errors.append("inputs: counterfactual needs mortality_file, birthrate_file or mortality_time_file")

        # The scripts expand these unquoted, and mobile.sh refuses to run inside the repository
        for path in [self.mobile, self.runs_dir, *self.inputs.values()]:
            if " " in str(path):
                errors.append(f"paths cannot contain spaces: {path}")
        if self.runs_dir.is_relative_to(self.mobile):
            errors.append(f"runs_dir cannot be inside the MoBILE repository: {self.runs_dir}")

        if not (self.mobile / "utils" / "run_MOBILE.sh").is_file():
            errors.append(f"not a MoBILE repository: {self.mobile}")
        else:
            unknown = set(self.params) - namelist_names(self.mobile, "CONST")
            if unknown:
                errors.append(f"params: not in &CONST: {sorted(unknown)}")
            if self.output is not None:
                unknown = set(self.output) - namelist_names(self.mobile, "OUTPUT")
                if unknown:
                    errors.append(f"output: not in &OUTPUT: {sorted(unknown)}")
        if errors:
            raise ConfigError("\n".join(errors))
