"""Outcome of a run: its provenance record and access to its output."""

import datetime
import hashlib
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

import netCDF4
import xarray as xr

PROGRESS_LINE = re.compile(r"[\d.]+\s*%\s*$")  # In-place progress of the model, one line per update in the log


def _git(mobile, *args):
    done = subprocess.run(["git", "-C", str(mobile), *args], capture_output=True, text=True)
    return done.stdout.strip() if done.returncode == 0 else None


def _md5(path):
    return hashlib.md5(path.read_bytes()).hexdigest() if path.is_file() else None


@dataclass(frozen=True)
class RunResult:
    status: str  # finished, failed, cancelled
    run_dir: Path
    output_path: Path
    returncode: int
    wall_seconds: float
    spinup_years: int

    @property
    def ok(self):
        return self.status == "finished"

    def log_tail(self, lines=30):
        text = (self.run_dir / "run.log").read_text(errors="replace").splitlines()
        text = [line for line in text if not PROGRESS_LINE.search(line)]
        return "\n".join(text[-lines:])

    def variables(self):
        """{variable: {group, long_name, units, static}} of the fields on the grid in the output.

        Static fields are (lat, lon), the others (time, lat, lon).
        """
        found = {}

        def walk(group, path):
            for name, variable in group.variables.items():
                if variable.dimensions in (("time", "lat", "lon"), ("lat", "lon")):
                    found[name] = {
                        "group": path,
                        "long_name": getattr(variable, "long_name", name),
                        "units": getattr(variable, "units", ""),
                        "static": "time" not in variable.dimensions,
                    }
            for name, subgroup in group.groups.items():
                walk(subgroup, f"{path}/{name}".lstrip("/"))

        with netCDF4.Dataset(self.output_path) as dataset:
            walk(dataset, "")
        return found

    def days(self):
        with netCDF4.Dataset(self.output_path) as dataset:
            return dataset.dimensions["time"].size

    def open(self, name):
        """Load a field on the grid, e.g. EIR or V, as a DataArray with its coordinates."""
        if not self.ok:
            raise RuntimeError(f"Run {self.status}, no output to open: {self.run_dir}")
        variables = self.variables()
        if name not in variables:
            raise KeyError(f"{name} not in the output; available: {sorted(variables)}")
        # The coordinates are in the root group of the file, the fields in subgroups
        with xr.open_dataset(self.output_path) as root, xr.open_dataset(self.output_path, group=variables[name]["group"]) as data:
            field = data[name]
            coords = {dim: root[dim] for dim in field.dims}
            return field.assign_coords(coords).load()


def load_run(run_dir):
    """The RunResult of a run folder written earlier."""
    run_dir = Path(run_dir)
    manifest = json.loads((run_dir / "run.json").read_text())
    return RunResult(
        status=manifest["status"],
        run_dir=run_dir,
        output_path=run_dir / "output" / "output.nc",
        returncode=manifest["returncode"],
        wall_seconds=manifest["wall_seconds"],
        spinup_years=manifest["spinup_years"],
    )


def write_seed_band(band_dir, status, seeds):
    """Record a group of runs that differ only in their seed; each is a folder seed_<seed>/ in band_dir."""
    record = {"status": status, "date": datetime.datetime.now().isoformat(timespec="seconds"), "seeds": seeds}
    (Path(band_dir) / "seed_band.json").write_text(json.dumps(record, indent=2) + "\n")


def load_seed_band(band_dir):
    """The RunResults of a seed band, in the order of its seeds."""
    band_dir = Path(band_dir)
    record = json.loads((band_dir / "seed_band.json").read_text())
    return [load_run(band_dir / f"seed_{seed}") for seed in record["seeds"]]


def _read_finished(run_dir):
    """Manifest of a finished run that still has its output, otherwise None."""
    try:
        manifest = json.loads((run_dir / "run.json").read_text())
    except (OSError, json.JSONDecodeError):
        return None
    if manifest.get("status") != "finished" or not (run_dir / "output" / "output.nc").is_file():
        return None
    return manifest


def _read_seed_band(band_dir):
    """Manifest of the first seed plus the list of seeds, if the band and all its runs finished."""
    try:
        record = json.loads((band_dir / "seed_band.json").read_text())
    except (OSError, json.JSONDecodeError):
        return None
    if record.get("status") != "finished":
        return None
    manifests = [_read_finished(band_dir / f"seed_{seed}") for seed in record["seeds"]]
    if not all(manifests):
        return None
    return {**manifests[0], "date": record["date"], "seeds": record["seeds"]}


def read_run(folder):
    """Manifest of a finished run or seed band (that of its first seed, plus the list `seeds`) that still has its
    output, otherwise None: also for a folder that cannot be read."""
    folder = Path(folder)
    try:
        band = (folder / "seed_band.json").exists()
    except OSError:  # E.g. a folder without the permission to read it, next to the runs
        return None
    return _read_seed_band(folder) if band else _read_finished(folder)


def list_runs(runs_dir, pop_file=None):
    """Finished runs and seed bands that still have their output, newest first: {folder: manifest}.

    The manifest of a seed band is that of its first seed, plus the list `seeds`.
    With pop_file, only those on that population file, i.e. on that grid.
    """
    runs = {}
    root = Path(runs_dir)
    for folder in root.iterdir() if root.is_dir() else []:
        manifest = read_run(folder)
        if manifest is None:
            continue
        if pop_file is not None and manifest.get("inputs", {}).get("pop_file") != pop_file:
            continue
        runs[str(folder)] = manifest
    return dict(sorted(runs.items(), key=lambda item: item[1].get("date", ""), reverse=True))


def age_record(config, run_dir):
    """The age structure of a run: its WorldPop product, country and year, and the weights the model read."""
    try:
        weights = [float(value) for value in (Path(run_dir) / "age_structure" / "cumm_age.txt").read_text().split()]
    except OSError:
        weights = None
    return {**config.age_choice(), "weights": weights}


def write_manifest(config, result):
    """Record what is needed to compare or repeat the run (see "Comparing runs" in MoBILE's LLM.md)."""
    mobile = config.mobile
    manifest = {
        "status": result.status,
        "date": datetime.datetime.now().isoformat(timespec="seconds"),
        "wall_seconds": round(result.wall_seconds, 1),
        "returncode": result.returncode,
        "spinup_years": result.spinup_years,
        "mobile": str(mobile),
        "commit": _git(mobile, "rev-parse", "HEAD"),
        "dirty": bool(_git(mobile, "status", "--porcelain")),
        "binary_md5": _md5(result.run_dir / "output" / "mobile.out"),
        "run": config.run,
        "inputs": config.inputs,
        "region": config.region,
        "period": config.period,
        "age_structure": config.age_structure,
        "age_used": age_record(config, result.run_dir),
        "shapes": config.shapes,
        "param_overrides": config.params,
        "params": config.final_params(),
        "output": list(config.output) if config.output is not None else None,
    }
    (result.run_dir / "run.json").write_text(json.dumps(manifest, indent=2) + "\n")
