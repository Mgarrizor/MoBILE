"""The settings of the GUI, set in its Setup panel instead of a configuration file: built from the
fields of the panel, remembered between sessions, and restored from the record of a run."""

import json
import os
import re
from pathlib import Path

from .config import OPTIONAL_DEFAULTS, Config, ConfigError

# (key, label, kind) of the files of a run, in the order of the Setup panel
REQUIRED_FILES = (
    ("rain_file", "Rainfall", "netcdf"),
    ("temp_file", "Temperature", "netcdf"),
    ("pop_file", "Population density", "netcdf"),
    ("area_file", "Cell area", "netcdf"),
    ("age_file", "Age structure (cumulative)", "text"),
)
OPTIONAL_FILES = (
    ("mortality_file", "Mortality by age", "text"),
    ("birthrate_file", "Birth rate by year", "text"),
    ("mortality_time_file", "Mortality by age and year", "text"),
    ("imm_forcing", "Immunity forcing", "netcdf"),
)
SUFFIXES = {
    "netcdf": (".nc", ".nc4", ".cdf"),
    "text": (".txt", ".csv", ".dat"),
    "folder": (),
}
SETUP_FILE = "last_setup.json"
FOLDER_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")


def settings_folder():
    return Path(os.environ.get("MOBILE_CONFIG_DIR", Path.home() / ".config" / "mobile"))


def typed_path(value):
    """A path as typed: `~` and environment variables expanded, relative to the current folder."""
    return Path(os.path.expandvars(os.path.expanduser(str(value).strip()))).resolve()


def from_fields(mobile, project, runs_dir, run, inputs, region=None, period=None):
    """The Config of the fields of the Setup panel. An empty optional file is not used.

    Raises ConfigError, listing every problem, as for a configuration file.
    """
    files = dict(OPTIONAL_DEFAULTS)
    for key, value in inputs.items():
        if key in OPTIONAL_DEFAULTS:
            files[key] = value
        elif value is None or not str(value).strip() or str(value).strip() == "NONE":
            # A required file left empty is reported by validate(), as not found
            files[key] = "NONE" if key in {name for name, _, _ in OPTIONAL_FILES} else ""
        else:
            files[key] = str(typed_path(value))
    numbers = {}
    for key, value in run.items():
        # Number boxes give 365.0 for 365
        numbers[key] = int(value) if isinstance(value, float) and value.is_integer() else value
    if not mobile:
        raise ConfigError("MoBILE location unknown: run `export MOBILE=/path/to/MoBILE` before `mobile gui`")
    config = Config(
        mobile=Path(mobile).expanduser().resolve(),
        runs_dir=typed_path(runs_dir or "runs"),
        run=numbers,
        inputs=files,
        project=str(project or "").strip(),
        region=region,
        period=period,
    )
    config.validate()
    return config


REGION_MODES = {"all": "Whole grid", "box": "Subregion", "point": "Single point"}


def region_from_fields(mode, north, west, south, east, lat, lon):
    """The region of the Setup panel: None for the whole grid. A point is a box of no size, which gives
    the cell it falls in."""
    if mode == "box":
        return {"north": north, "west": west, "south": south, "east": east}
    if mode == "point":
        return {"north": lat, "west": lon, "south": lat, "east": lon}
    return None


def region_mode(region):
    if region is None:
        return "all"
    return "point" if region["north"] == region["south"] and region["west"] == region["east"] else "box"


def to_dict(config):
    return {
        "mobile": str(config.mobile),
        "project": config.project,
        "runs_dir": str(config.runs_dir),
        "run": dict(config.run),
        "inputs": dict(config.inputs),
        "region": config.region,
        "period": config.period,
    }


def save_setup(config):
    """Remember the settings for the next session. Not being able to is not an error."""
    try:
        folder = settings_folder()
        folder.mkdir(parents=True, exist_ok=True)
        (folder / SETUP_FILE).write_text(json.dumps(to_dict(config), indent=2) + "\n")
    except OSError:
        pass


def load_setup(mobile=None):
    """The settings of the last session, or None if there are none or they are no longer valid,
    e.g. because a file was moved. `mobile` overrides the location of MoBILE saved with them."""
    try:
        saved = json.loads((settings_folder() / SETUP_FILE).read_text())
        return from_fields(mobile or saved["mobile"], saved["project"], saved["runs_dir"], saved["run"], saved["inputs"],
                           saved.get("region"), saved.get("period"))
    except (OSError, ValueError, KeyError, TypeError, ConfigError):
        return None


def from_manifest(manifest, current):
    """The settings with which a run was made, from its run.json, in the project and results
    folder of the current settings."""
    return from_fields(current.mobile, current.project, current.runs_dir, manifest["run"], manifest["inputs"],
                       manifest.get("region"), manifest.get("period"))


def list_folder(folder, kind):
    """(folders, files) in a folder, by name, for the file browser of the GUI: the files of the kind
    asked for, none for a folder. Hidden entries are left out."""
    folder = Path(folder)
    folders, files = [], []
    try:
        entries = sorted(folder.iterdir(), key=lambda path: path.name.lower())
    except OSError:
        return [], []
    for entry in entries:
        if entry.name.startswith("."):
            continue
        try:
            if entry.is_dir():
                folders.append(entry.name)
            elif kind != "folder" and entry.suffix.lower() in SUFFIXES[kind]:
                files.append(entry.name)
        except OSError:
            continue
    return folders, files


def start_folder(value):
    """Where the file browser opens: the folder of the path in the box, or the home folder."""
    if value and str(value).strip():
        path = typed_path(value)
        for candidate in (path, path.parent):
            if candidate.is_dir():
                return candidate
    return Path.home()


def create_folder(parent, name):
    """Make a folder in `parent` for the file browser: (its path, None), or (None, why it cannot be made)."""
    name = name.strip()
    if not FOLDER_NAME.match(name):
        return None, (
            "Use letters, digits, '.', '_' and '-' only, starting with a letter or a digit, at most 80 characters: "
            "the run scripts do not allow spaces in paths."
        )
    path = Path(parent) / name
    if path.exists():
        return None, f"{name} already exists in {parent}."
    try:
        path.mkdir()
    except OSError as error:
        return None, f"Could not create {name}: {error.strerror}."
    return path.resolve(), None
