"""Running the model for the GUI, and what a run or a loaded run holds."""

import re
import threading
from dataclasses import field
from pathlib import Path

from .results import load_run, load_seed_band, write_seed_band
from .rundir import new_run_id
from .runner import Runner, RunnerBusy
from .variables import AGE_FIELD, age_groups, age_label


MAX_LOADED_VARIABLES = 4


class RunState:
    """Written by the worker thread, read by the session."""

    lock: threading.Lock = field(default_factory=threading.Lock)
    message: str = ""
    fraction: float | None = None
    member: int = 1
    members: int = 1
    runner: Runner | None = None
    cancelled: bool = False

    def update(self, **values):
        with self.lock:
            for key, value in values.items():
                setattr(self, key, value)

    def snapshot(self):
        with self.lock:
            return self.message, self.fraction, self.member, self.members


class Outcome:
    status: str
    loaded: bool = False
    run_dir: str = ""
    log: str = ""
    overrides: dict = field(default_factory=dict)
    nagent: int = 0
    seeds: list = field(default_factory=list)
    results: list = field(default_factory=list)    # RunResult of each seed
    variables: dict = field(default_factory=dict)  # As RunResult.variables
    days: int = 0
    loaded_fields: dict = field(default_factory=dict)
    colour_limits: dict = field(default_factory=dict)
    nonpositive: dict = field(default_factory=dict)  # {menu entry: share of the values at or under 0}

    def fields(self, name):
        """The field of each seed. Only those asked for are read, as a run can hold over 100 of them."""
        if name not in self.loaded_fields:
            if len(self.loaded_fields) >= MAX_LOADED_VARIABLES:
                self.loaded_fields.pop(next(iter(self.loaded_fields)))
            self.loaded_fields[name] = [result.open(name) for result in self.results]
        return self.loaded_fields[name]

    def describe(self, name):
        """(label, units) of a variable, from the attributes in the output file."""
        info = self.variables[name]
        label = info["long_name"]
        age = AGE_FIELD.match(name)
        if info["group"] in age_groups(self.variables) and age:
            label = f"{label}, {age_label(age.group(1)).lower()}"
        return label, info["units"]


RUN_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")


def run_name_problem(name, runs_dir):
    """Why a run name typed in the GUI cannot be used, or None. Empty means the date-based default."""
    if not name:
        return None
    if not RUN_NAME.match(name):
        return (
            "Use letters, digits, '.', '_' and '-' only, starting with a letter or a digit, "
            "at most 80 characters: the run scripts do not allow spaces in paths."
        )
    if (Path(runs_dir) / name).exists():
        return f"A run named {name} already exists in {runs_dir}: choose another name."
    return None


def run_model(config, seeds, state, name=None):
    """Run one seed after another with the same parameters, threads and binary, in runs_dir/<name>
    (a date-based name by default)."""
    outcome = Outcome(status="finished", overrides=dict(config.params), nagent=config.run["nagent"])
    band = (name or f"seed_band_{new_run_id()}") if len(seeds) > 1 else None
    if band:
        outcome.run_dir = str(config.runs_dir / band)
    for member, seed in enumerate(seeds, start=1):
        if state.cancelled:
            outcome.status = "cancelled"
            break
        runner = Runner(config.with_run(seed=seed))
        state.update(runner=runner, member=member, members=len(seeds), message="Starting", fraction=None)

        def on_progress(event):
            state.update(message=event.message, fraction=event.fraction)

        try:
            result = runner.run(f"{band}/seed_{seed}" if band else name, on_progress=on_progress)
        except RunnerBusy as error:
            outcome.status, outcome.log = "failed", str(error)
            break
        if not band:
            outcome.run_dir = str(result.run_dir)
        if not result.ok:
            outcome.status, outcome.log = result.status, result.log_tail()
            break
        outcome.results.append(result)
        outcome.seeds.append(seed)
    if outcome.results:
        outcome.variables, outcome.days = outcome.results[0].variables(), outcome.results[0].days()
    if band and (config.runs_dir / band).is_dir():
        write_seed_band(config.runs_dir / band, outcome.status, seeds)
    return outcome


def load_outcome(run_dir, manifest):
    """A finished run or seed band read back from its folder."""
    seeds = manifest.get("seeds")
    results = load_seed_band(run_dir) if seeds else [load_run(run_dir)]
    outcome = Outcome(
        status="finished", loaded=True, run_dir=str(run_dir), overrides=manifest.get("param_overrides", {}),
        nagent=manifest["run"]["nagent"], seeds=seeds or [manifest["run"]["seed"]], results=results,
        variables=results[0].variables(), days=results[0].days(),
    )
    return outcome


def run_label(folder, manifest):
    changed = ", ".join(f"{k}={v:.4g}" for k, v in manifest.get("param_overrides", {}).items()) or "no changes"
    run = manifest["run"]
    seeds = f"seed band of {len(manifest['seeds'])} from seed {run['seed']}" if "seeds" in manifest else f"seed {run['seed']}"
    date = manifest.get("date", "?").replace("T", " ")
    # A run without a name has a folder named after its date, which says nothing more
    named = not re.match(r"^(seed_band_)?\d{8}-\d{6}-[0-9a-f]{4}$", Path(folder).name)
    when = f"{Path(folder).name} ({date})" if named else date
    return f"{when}: {run['nagent']:,} agents, {seeds}, {changed}"
