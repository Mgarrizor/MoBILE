"""Run configuration: what is otherwise edited by hand at the top of run_MOBILE.sh."""

import os
import re
from dataclasses import dataclass, field, replace
from importlib import resources
from pathlib import Path

import yaml

from .parameters import run_parameters, shown_parameters
from .period import period_days, period_problems, spin_up_problem
from .region import region_problems
from .worldpop import choice_problems, default_year

# The keys of a configuration file. Parameters, outputs and sliders are set in the GUI.
CONFIG_KEYS = {"mobile", "runs_dir", "project", "run", "inputs", "region", "period", "age_structure"}
RUN_KEYS = {"disID", "mob", "nstep", "spin_up", "nagent", "seed", "threads"}
REQUIRED_INPUTS = {"rain_file", "temp_file", "pop_file"}
# A parameter file is no longer an input: the parameters, their defaults and ranges are in parameters.yaml
NO_CONST = ("inputs: const is no longer used: the parameters are set in the GUI, or with `mobile run --set`, and start at "
            "the defaults compiled into the model. Remove `const` from the configuration.")
NO_AREA = ("inputs: area_file is no longer used: the model computes the cell areas from the grid of the population "
           "file. Remove `area_file` from the configuration.")
NO_AGE = ("inputs: age_file is no longer used: the age structure comes from WorldPop, chosen by product, country and "
          "year. Remove `age_file` and set `age_structure: {product: R2025A, country: SEN}` (year: optional).")
NO_AGE_STRUCTURE = "age_structure: missing; choose a WorldPop product and country, e.g. {product: R2025A, country: SEN}"
OPTIONAL_INPUTS = {"mortality_file", "birthrate_file", "mortality_time_file", "imm_forcing"}
OPTIONAL_DEFAULTS = {"counterfactual": 0}

# character(len=200) in mo_control.f90; a namelist read truncates longer paths silently
MAX_PATH_LENGTH = 200


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
    period: dict | None = None  # {start, end} days to simulate, as YYYY-MM-DD; None for all the driving data
    age_structure: dict | None = None  # {product, country, year} of WorldPop; year None for that of the period (worldpop.py)

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
            period=raw.get("period"),
            age_structure=raw.get("age_structure"),
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

    def age_choice(self):
        """{product, country, year} of the age structure, the year given or else that of the product closest to the
        first year simulated: of the period, or of the driving data."""
        choice = dict(self.age_structure)
        if choice.get("year") is None:
            if self.period is not None:
                start = int(str(self.period["start"])[:4])
            else:
                from .checks import driving_days  # Not at the top: checks reads the files, config does not
                days = driving_days(self.inputs["rain_file"])
                start = int(str(days[0])[:4]) if days is not None and len(days) else 0  # No dates: the first year
            choice["year"] = default_year(start, choice["product"])
        return choice

    def final_params(self):
        """Parameters of the run, as written to its &CONST: every parameter of the GUI at its default, overridden by `params`."""
        return run_parameters(self.params)

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
        problems = period_problems(self.period)
        errors += problems
        if not problems:
            days = period_days(self.period) if self.period is not None else self.run.get("nstep")
            problem = spin_up_problem(self.run.get("spin_up"), days)
            if problem:
                errors.append(f"run: {problem}")

        if "const" in self.inputs:
            errors.append(NO_CONST)
        if "area_file" in self.inputs:
            errors.append(NO_AREA)
        if "age_file" in self.inputs:
            errors.append(NO_AGE)
        errors += [NO_AGE_STRUCTURE] if self.age_structure is None else choice_problems(self.age_structure)
        allowed = REQUIRED_INPUTS | OPTIONAL_INPUTS | set(OPTIONAL_DEFAULTS) | {"const", "area_file", "age_file"}
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
            hidden = set(self.params) - unknown - set(shown_parameters())
            if hidden:
                errors.append(f"params: not available for this model: {sorted(hidden)}")
            if self.output is not None:
                unknown = set(self.output) - namelist_names(self.mobile, "OUTPUT")
                if unknown:
                    errors.append(f"output: not in &OUTPUT: {sorted(unknown)}")
        if errors:
            raise ConfigError("\n".join(errors))
