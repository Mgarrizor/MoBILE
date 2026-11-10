"""Prepare a run folder, including the filled-in copy of utils/run_MOBILE.sh."""

import datetime
import re
import secrets
from pathlib import Path

from .checks import driving_days
from .config import MAX_PATH_LENGTH, ConfigError
from .grid import pop_coordinates
from .period import day_range, period_days
from .region import cut_inputs
from .worldpop import age_file_text, prepare

OUTPUT_NAME = "output"
INPUTS_NAME = "inputs"  # The driving files cut to the region of a run


def fill_template(template, values, threads, mobile):
    """Set the configuration lines of run_MOBILE.sh, failing on any line it cannot find exactly once."""
    filled = template
    for name, value in values.items():
        pattern = rf"^([ \t]*){name}=.*$"
        filled, count = re.subn(pattern, lambda m: f"{m.group(1)}{name}={value}", filled, flags=re.M)
        if count != 1:
            raise ValueError(f"run_MOBILE.sh: expected one line setting {name}, found {count}")

    # The first numeric assignment is the one in the parallel branch
    filled, count = re.subn(
        r"^([ \t]*)export OMP_NUM_THREADS=\d+[ \t]*$",
        lambda m: f"{m.group(1)}export OMP_NUM_THREADS={threads}",
        filled,
        count=1,
        flags=re.M,
    )
    if count != 1:
        raise ValueError("run_MOBILE.sh: no line setting OMP_NUM_THREADS")

    first_line, rest = filled.split("\n", 1)
    return f"{first_line}\n\nexport MOBILE={mobile}  # Added by the wrapper\n{rest}"


def new_run_id():
    return f"{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(2)}"


def period_steps(config):
    """(first, last) step of the period of a config in its driving files; None if it has none or covers them all."""
    if config.period is None:
        return None
    days = driving_days(config.inputs["rain_file"])
    try:
        steps = day_range(days, config.period)
    except ValueError as error:
        raise ConfigError(f"period: {error}") from None
    return None if steps == (0, len(days) - 1) else steps


def create_run_dir(config, name=None, prebuilt=None):
    """Create runs_dir/<name>/ and everything the scripts read from it. With prebuilt, the path of a model already
    built, the scripts run it (mobile.sh -E) instead of building one."""
    run_dir = Path(config.runs_dir) / (name or new_run_id())
    (run_dir / "age_structure").mkdir(parents=True)

    # Downloaded and analysed the first time a product, country and year is used (worldpop.py), then kept
    age = prepare(**config.age_choice())
    (run_dir / "age_structure" / "cumm_age.txt").write_text(age_file_text(age))
    params = "".join(f"{key}={value},\n" for key, value in config.final_params().items())
    (run_dir / "params.txt").write_text(params)

    output_file = "'NONE'"
    flags = config.output_flags()
    if flags is not None:
        lines = "".join(f"{key}={'.true.' if on else '.false.'},\n" for key, on in flags.items())
        (run_dir / "output.txt").write_text(lines)
        output_file = "'output.txt'"

    inputs = config.inputs
    steps = period_steps(config)
    if config.region is not None or steps is not None:
        inputs = {**inputs, **cut_inputs(inputs, config.region, run_dir / INPUTS_NAME, pop_coordinates(inputs["pop_file"]), steps)}
        too_long = [path for path in inputs.values() if len(str(path)) > MAX_PATH_LENGTH]
        if too_long:
            raise ConfigError(f"paths in the run folder longer than {MAX_PATH_LENGTH} characters: {too_long}")
    values = {
        "output_name": f"'{OUTPUT_NAME}'",
        "disID": config.run["disID"],
        "seed": config.run["seed"],
        "name_list": "'namelist.nml'",
        "mob": config.run["mob"],
        "nstep": config.run["nstep"] if config.period is None else period_days(config.period),
        "nagent": config.run["nagent"],
        "spin_up": config.run["spin_up"],
        "pop_file": f"'{inputs['pop_file']}'",
        "rain_file": f"'{inputs['rain_file']}'",
        "temp_file": f"'{inputs['temp_file']}'",
        "mortality_file": f"'{inputs.get('mortality_file', 'NONE')}'",
        "birthrate_file": f"'{inputs.get('birthrate_file', 'NONE')}'",
        "mortality_time_file": f"'{inputs.get('mortality_time_file', 'NONE')}'",
        "counterfactual": inputs["counterfactual"],
        "const": "'params.txt'",
        "output_file": output_file,
        "imm_forcing": f"'{inputs.get('imm_forcing', 'NONE')}'",
    }
    if prebuilt is not None:
        # Only then: a MoBILE from before -E has no such line, and its runs still build as they always did
        values["prebuilt"] = f"'{prebuilt}'"
    template = (Path(config.mobile) / "utils" / "run_MOBILE.sh").read_text()
    script = fill_template(template, values, config.run["threads"], config.mobile)
    (run_dir / "run_MOBILE.sh").write_text(script)
    return run_dir
