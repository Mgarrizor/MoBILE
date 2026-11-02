"""Prepare a run folder, including the filled-in copy of utils/run_MOBILE.sh."""

import datetime
import re
import secrets
import shutil
from pathlib import Path

OUTPUT_NAME = "output"


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


def create_run_dir(config, name=None):
    """Create runs_dir/<name>/ and everything the scripts read from it."""
    run_dir = Path(config.runs_dir) / (name or new_run_id())
    (run_dir / "age_structure").mkdir(parents=True)

    shutil.copy(config.inputs["age_file"], run_dir / "age_structure" / "cumm_age.txt")
    params = "".join(f"{key}={value},\n" for key, value in config.final_params().items())
    (run_dir / "params.txt").write_text(params)

    output_file = "'NONE'"
    flags = config.output_flags()
    if flags is not None:
        lines = "".join(f"{key}={'.true.' if on else '.false.'},\n" for key, on in flags.items())
        (run_dir / "output.txt").write_text(lines)
        output_file = "'output.txt'"

    inputs = config.inputs
    values = {
        "output_name": f"'{OUTPUT_NAME}'",
        "disID": config.run["disID"],
        "seed": config.run["seed"],
        "name_list": "'namelist.nml'",
        "mob": config.run["mob"],
        "nstep": config.run["nstep"],
        "nagent": config.run["nagent"],
        "spin_up": config.run["spin_up"],
        "pop_file": f"'{inputs['pop_file']}'",
        "rain_file": f"'{inputs['rain_file']}'",
        "temp_file": f"'{inputs['temp_file']}'",
        "area_file": f"'{inputs['area_file']}'",
        "mortality_file": f"'{inputs.get('mortality_file', 'NONE')}'",
        "birthrate_file": f"'{inputs.get('birthrate_file', 'NONE')}'",
        "mortality_time_file": f"'{inputs.get('mortality_time_file', 'NONE')}'",
        "counterfactual": inputs["counterfactual"],
        "const": "'params.txt'",
        "output_file": output_file,
        "imm_forcing": f"'{inputs.get('imm_forcing', 'NONE')}'",
    }
    template = (Path(config.mobile) / "utils" / "run_MOBILE.sh").read_text()
    script = fill_template(template, values, config.run["threads"], config.mobile)
    (run_dir / "run_MOBILE.sh").write_text(script)
    return run_dir
