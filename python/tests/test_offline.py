"""Checks that need no simulation: python -m unittest discover tests"""

import datetime
import hashlib
import json
import math
import os
import re
import shutil
import socket
import sys
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

import netCDF4
import numpy as np
import pandas as pd

from mobile.config import (
    Config,
    ConfigError,
    example_config,
    namelist_names,
    read_params,
)
from mobile.parameters import (
    PARAMETER_GROUPS, all_parameters, run_parameters, shown_parameters, slider_start, to_model, to_shown,
)
from mobile.rundir import create_run_dir, fill_template
from mobile.app import free_port
from mobile.layout import OUTPUT_FLAGS, logo_files, publications
from mobile.outcome import Outcome, RunState, run_label, run_name_problem
from mobile.plots import (
    MAX_DOTS, add_dot, cell_envelope, climate_figure, colour_values, default_dot, grid_step, index_map_figure,
    indices_figure, map_figure, monthly_figure, move_dot, next_cells, remove_dot, second_order_figure, units_label,
)
from mobile.setup_ui import AVAILABLE_MODEL, MODEL_TO_COME_NOTE, _model_select, available_model, setup_problems
from mobile.variables import age_choices, age_groups, preferred_variable, resolve_variable, variable_choices
from mobile.basemap import cell_size, load_basemap
from mobile.driving import climatology, field_limits, mean_age, open_field
from mobile.results import list_runs, load_run, load_seed_band, write_seed_band
from mobile.setup import (
    create_folder, from_fields, from_manifest, list_folder, load_setup, region_from_fields, region_mode, save_setup,
    start_folder,
)
from mobile.checks import driving_days, driving_problems
from mobile.period import SPIN_UP_DAYS, day_range, length_text, period_days, period_problems
from mobile.cells import EARTH_RADIUS, CellSizeError, cell_areas
from mobile.grid import pop_coordinates, read_grid
from mobile.region import axis_range, cut_file, cut_inputs, region_problems
from mobile.runner import ProgressParser, RunCancelled, Runner, RunnerBusy, macos_sdk, run_environment
from mobile.sensitivity_results import (
    PERCENTILES, age_note, analysable_variables, analyse_study, analysis_mask, cell_dataset, chance_share, complete_seeds,
    describe_metric, extract, first_run, indices_table, metric_from_entry, metric_key, monthly_table, output_info,
)
from mobile.sensitivity_runs import (
    RECORD, SAMPLES, StudyState, create_study, list_studies, read_study, run_finished, run_name, run_study, study_label, studies_dir,
    write_study,
)
from mobile.sensitivity import (
    Metric, SampledParameter, analyse, analyse_cells, design_problems, reduce_field, run_count, run_count_formula, sample,
)

CONFIG = example_config()


def fortran_defaults(mobile, model="malaria"):
    """Compiled-in values of the &CONST parameters, in the order the model sets them: the initial values of the
    declarations, const_disease before and in the case of the model, VECTRI's init_constants for the default vector
    (ivec=0), and the defaults set in namelist_const. Each assignment is evaluated in order."""
    def assignments(text):
        for line in text.splitlines():
            code = line.split("!")[0].strip()
            match = re.match(r"^([A-Za-z_]\w*)\s*=\s*(.+)$", code)
            if match:
                yield match.group(1), match.group(2)

    def declarations(text):
        for line in text.splitlines():
            code = line.split("!")[0]
            match = re.match(r"^\s*(?:real|integer)\b[^:]*::(.*)$", code, re.I)
            if match:
                for part in re.split(r",(?![^(]*\))", match.group(1)):
                    if "=" in part and "=>" not in part:
                        name, expression = part.split("=", 1)
                        yield name.strip(), expression.strip()

    const = Path(mobile, "src", "mo_const.f90").read_text()
    disease = const[const.index("subroutine const_disease"):]
    select = re.search(r"select\s+case\s*\(\s*idis\s*\)", disease, re.I)
    case = re.search(rf"case\s*\(\s*{ {'cholera': 0, 'malaria': 1}[model] }\s*\)", disease[select.end():], re.I)
    chosen = disease[select.end() + case.end():]
    chosen = chosen[:re.search(r"^\s*case\s*\(", chosen, re.I | re.M).start()]
    vectri = Path(mobile, "utils", "vectri", "mo_constants.f90").read_text()
    vectri = vectri[vectri.lower().index("subroutine init_constants"):]
    start = re.search(r"SELECT\s+CASE\s*\(\s*ivec\s*\)", vectri, re.I)
    case0 = vectri[start.end():]
    case0 = case0[re.search(r"CASE\s*\(\s*0\s*\)", case0, re.I).end():re.search(r"CASE\s*\(\s*1\s*\)", case0, re.I).start()]
    namelist = Path(mobile, "src", "mo_namelist.f90").read_text()
    namelist = namelist[namelist.lower().index("subroutine namelist_const"):]
    namelist = namelist[:re.search(r"read\s*\(\s*nml\s*=\s*CONST", namelist, re.I).start()]  # Defaults set before the read
    values = {}
    steps = (declarations(const[:const.lower().index("contains")]), assignments(disease[:select.start()]), assignments(chosen),
             assignments(vectri[:start.start()]), assignments(case0), assignments(namelist))
    for step in steps:
        for name, expression in step:
            try:
                values[name] = float(eval(expression.replace("log(", "math.log("), {"math": math}, dict(values)))
            except Exception:
                continue
    return values
MOBILE = os.environ["MOBILE"]


class TestPublications(unittest.TestCase):
    def test_pinned_first_then_by_year(self):
        entries = publications()
        self.assertEqual([entry["introduced"].split(":")[0] for entry in entries[:2]], ["VECTRI", "VECTRI-ABM"])
        rest = [entry["year"] for entry in entries if not entry.get("pinned")]
        self.assertEqual(rest, sorted(rest))
        for entry in entries:
            self.assertEqual(set(entry) - {"pinned"}, {"authors", "year", "title", "venue", "doi", "region", "domain", "side", "introduced"})
            self.assertIn(entry["domain"], ("Spatial", "Point"))
            self.assertIn(entry["side"], ("Vector", "Human", "Both", "Application"))
            self.assertRegex(entry["doi"], r"^10\.\d+/")
        # Whatever the order in the file
        shuffled = [{"year": 2030}, {"year": 2026, "pinned": 2}, {"year": 2020}, {"year": 2013, "pinned": 1}, {"year": 2024}]
        self.assertEqual([(entry["year"], entry.get("pinned")) for entry in publications(shuffled)],
                         [(2013, 1), (2026, 2), (2020, None), (2024, None), (2030, None)])


class TestConfig(unittest.TestCase):
    def setUp(self):
        # runs_dir is relative to the current folder and cannot be inside the repository
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(folder.name)
        self.config = Config.load(CONFIG)

    def test_namelist_names(self):
        const = namelist_names(MOBILE, "CONST")
        self.assertTrue({"e_0", "alph_min", "b_rate", "growth_ratio_ceiling"} <= const)
        self.assertNotIn("iip", const)
        output = namelist_names(MOBILE, "OUTPUT")
        self.assertEqual(len(output), 25)
        self.assertTrue({"out_EIR", "out_wperm"} <= output)
        self.assertNotIn("out_rain", output)

    def test_rejects_unknown_names(self):
        with self.assertRaises(ConfigError):
            self.config.with_params(iip=5.0)
        with self.assertRaises(ConfigError):
            self.config.with_run(unknown=1)

    def test_parameter_file(self):
        parameters = all_parameters()
        # Every parameter of &CONST, and only those: one added to the model must be added here too
        self.assertEqual(set(parameters), namelist_names(MOBILE, "CONST"))
        self.assertEqual(sum(spec["curated"] for spec in parameters.values()), 12)
        for name, spec in parameters.items():
            self.assertIn(spec["group"], (*PARAMETER_GROUPS, "Cholera", "Mobility"), name)
            self.assertLess(spec["min"], spec["max"], name)
            # Each is explained on hovering over it
            self.assertTrue(spec.get("info") and spec.get("source"), name)
        for name in shown_parameters():
            spec = parameters[name]
            self.assertTrue(spec["min"] <= slider_start(name) <= spec["max"], f"{name}: starts outside its range")
            self.assertAlmostEqual(to_shown(name, to_model(name, slider_start(name))), slider_start(name), msg=name)
        self.assertEqual(len(shown_parameters()), 48)

    def test_parameter_file_matches_the_source(self):
        malaria, cholera = fortran_defaults(MOBILE), fortran_defaults(MOBILE, "cholera")
        for name, spec in all_parameters().items():
            source = (cholera if spec["group"] == "Cholera" else malaria).get(name)
            self.assertIsNotNone(source, f"{name}: no default found in the source")
            self.assertTrue(math.isclose(spec["value"], source, rel_tol=1e-9, abs_tol=1e-12),
                            f"{name}: parameters.yaml {spec['value']}, source {source}")

    def test_run_parameters(self):
        written = run_parameters({})
        self.assertEqual(set(written), set(shown_parameters()))
        self.assertEqual(written["tau_chr"], "730")  # An integer in Fortran: 730.0 would stop the namelist read
        self.assertEqual(written["birth_rate"], "-1.0")  # The flag: equal to mu, whatever mu is
        self.assertEqual(float(written["mu"]), 0.0291 / 365)
        # Shown per year, written per day; shown as log10, written as the value
        self.assertAlmostEqual(slider_start("mu"), 0.0291)
        self.assertAlmostEqual(slider_start("birth_rate"), 0.0291)
        self.assertAlmostEqual(to_model("mu", 0.0365), 0.0001)
        self.assertAlmostEqual(to_model("wpond_min", -5.0), 1e-5)
        self.assertEqual(run_parameters({"tau_chr": 400.4})["tau_chr"], "400")
        # A parameter of the cholera model is not set for a malaria run
        self.assertNotIn("mu_B", written)
        with self.assertRaises(ValueError):
            run_parameters({"mu_B": 0.3})

    def test_refuses_a_parameter_file(self):
        with self.assertRaisesRegex(ConfigError, "const is no longer used"):
            replace(self.config, inputs={**self.config.inputs, "const": str(CONFIG)}).validate()

    def test_refuses_an_area_file(self):
        with self.assertRaisesRegex(ConfigError, "area_file is no longer used"):
            replace(self.config, inputs={**self.config.inputs, "area_file": str(CONFIG)}).validate()

    def test_fortran_defaults_detects_a_change(self):
        # Control: a default changed in a copy of the source is found
        with tempfile.TemporaryDirectory() as copy:
            for path in ("src/mo_const.f90", "utils/vectri/mo_constants.f90", "src/mo_namelist.f90"):
                (Path(copy) / path).parent.mkdir(parents=True, exist_ok=True)
                text = Path(MOBILE, path).read_text()
                if "mo_const.f90" in path:
                    text, count = re.subn(r"^(\s*k_star\s*=\s*)[0-9.eE+-]+", r"\g<1>12", text, count=1, flags=re.M)
                    self.assertEqual(count, 1)
                (Path(copy) / path).write_text(text)
            changed, source = fortran_defaults(copy), fortran_defaults(MOBILE)
            self.assertEqual(changed["k_star"], 12.0)
            self.assertNotEqual(source["k_star"], 12.0)
            self.assertEqual({k: v for k, v in changed.items() if k != "k_star"}, {k: v for k, v in source.items() if k != "k_star"})

    def test_configuration_has_only_the_essentials(self):
        path = Path(os.getcwd()) / "old.yaml"
        path.write_text(example_config().read_text() + "\nsliders: {}\noutput: [out_EIR]\n")
        with self.assertRaisesRegex(ConfigError, "set in the GUI"):
            Config.load(path)

    def test_override_keeps_other_values_at_default(self):
        base = self.config.final_params()
        final = self.config.with_params(e_0=0.25).final_params()
        self.assertEqual(final["e_0"], "0.25")
        del base["e_0"], final["e_0"]
        self.assertEqual(base, final)
        with self.assertRaisesRegex(ConfigError, "not available for this model"):
            self.config.with_params(mu_B=0.3)

    def test_threads_at_most_32(self):
        Config.load(CONFIG).with_run(threads=32).validate()
        with self.assertRaisesRegex(ConfigError, "threads must be at most 32"):
            Config.load(CONFIG).with_run(threads=33).validate()

    def test_spin_up_needs_a_year(self):
        # mo_spinup.f90 stops with less than 365 simulated days (ndays_year): 364 must be refused, 365 accepted
        self.assertEqual(SPIN_UP_DAYS, 365)
        source = Path(MOBILE, "src", "mo_spinup.f90").read_text()
        self.assertRegex(source, r"ndays_year\s*=\s*365")

        def setup(spin_up, end=None, nstep=0):
            period = None if end is None else {"start": "2012-01-01", "end": end}
            return replace(self.config, run={**self.config.run, "spin_up": spin_up, "nstep": nstep}, period=period)

        with self.assertRaisesRegex(ConfigError, "at least 365 days"):
            setup(1, "2012-12-29").validate()  # 364 days, a leap year
        setup(1, "2012-12-30").validate()  # 365
        setup(0, "2012-01-30").validate()  # Without spin-up, any length
        with self.assertRaisesRegex(ConfigError, "at least 365 days"):
            setup(1, nstep=200).validate()
        setup(1).validate()  # nstep 0: the length of the driving data, not known here

    def test_template_failure_is_loud(self):
        with self.assertRaises(ValueError):
            fill_template("#!/bin/bash\nseed=1\nseed=2\nexport OMP_NUM_THREADS=4\n", {"seed": 3}, 4, "/m")
        with self.assertRaises(ValueError):
            fill_template("#!/bin/bash\nexport OMP_NUM_THREADS=4\n", {"seed": 3}, 4, "/m")

    def test_run_dir_contents(self):
        with tempfile.TemporaryDirectory(dir=os.path.expanduser("~")) as tmp:
            config = Config.load(CONFIG)
            object.__setattr__(config, "runs_dir", Path(tmp))
            run_dir = create_run_dir(replace(config, output=("out_EIR", "out_vect")).with_params(e_0=0.25), "x")
            script = (run_dir / "run_MOBILE.sh").read_text()
            self.assertRegex(script, r"(?m)^\s*seed=12345$")
            self.assertRegex(script, r"(?m)^\s*const='params.txt'$")
            self.assertRegex(script, r"(?m)^\s*output_file='output.txt'$")
            self.assertRegex(script, r"(?m)^\s*counterfactual=0$")
            self.assertIn("e_0=0.25,", (run_dir / "params.txt").read_text())
            self.assertIn("out_EIR=.true.,", (run_dir / "output.txt").read_text())
            self.assertIn("out_I=.false.,", (run_dir / "output.txt").read_text())
            self.assertTrue((run_dir / "age_structure" / "cumm_age.txt").is_file())


class TestDots(unittest.TestCase):
    def test_added_in_the_first_free_colour_up_to_a_limit(self):
        dots = []
        for index in range(MAX_DOTS):
            dots = add_dot(dots, float(index), 0.0)
        self.assertEqual([dot["colour"] for dot in dots], list(range(MAX_DOTS)))
        self.assertEqual(add_dot(dots, 99.0, 0.0), dots)
        # A colour freed by removing a dot is used again
        dots = add_dot(remove_dot(dots, 2), 50.0, 0.0)
        self.assertEqual(dots[-1]["colour"], 2)
        self.assertEqual(len(dots), MAX_DOTS)

    def test_a_cell_has_one_dot(self):
        dots = add_dot(add_dot([], 1.0, 1.0), 2.0, 2.0)
        self.assertEqual(add_dot(dots, 1.0, 1.0), dots)
        self.assertEqual(move_dot(dots, 0, 2.0, 2.0), dots)

    def test_moved_dots_keep_their_colour_and_place_in_the_list(self):
        dots = add_dot(add_dot([], 1.0, 1.0), 2.0, 2.0)
        moved = move_dot(dots, 0, 3.0, 4.0)
        self.assertEqual(moved[0], {"lon": 3.0, "lat": 4.0, "colour": 0})
        self.assertEqual(moved[1], dots[1])
        self.assertEqual(move_dot(dots, 5, 3.0, 4.0), dots)
        self.assertEqual(remove_dot(dots, 0), [dots[1]])
        self.assertEqual(remove_dot([], 0), [])

    def test_default_dot_is_a_cell_with_data_near_the_middle(self):
        import numpy as np
        import xarray as xr

        values = np.full((5, 5), np.nan)
        values[0, 0] = values[4, 4] = values[2, 3] = 1.0
        field = xr.DataArray(values, dims=("lat", "lon"), coords={"lat": np.arange(5.0), "lon": np.arange(5.0) * 10})
        # The middle of the three cells is lat 2.0, lon 23.3: the cell at lat 2, lon 30 is the nearest
        self.assertEqual(default_dot(field), {"lon": 30.0, "lat": 2.0, "colour": 0})
        # The first day of a daily field
        daily = field.expand_dims(time=[0, 1])
        self.assertEqual(default_dot(daily), default_dot(field))
        self.assertIsNone(default_dot(field.where(False)))


class TestSeedEnvelope(unittest.TestCase):
    def test_median_lowest_highest_per_day(self):
        median, lowest, highest = cell_envelope([[1.0, 5.0], [3.0, 4.0], [2.0, 9.0]])
        self.assertEqual(median.tolist(), [2.0, 5.0])
        self.assertEqual(lowest.tolist(), [1.0, 4.0])
        self.assertEqual(highest.tolist(), [3.0, 9.0])


class TestOutputs(unittest.TestCase):
    def test_switches_match_the_model(self):
        flags = {flag: on for group in OUTPUT_FLAGS.values() for flag, _, on in group}
        self.assertEqual(set(flags), namelist_names(MOBILE, "OUTPUT"))
        # The example file of MoBILE lists the defaults
        example = dict(line.split("!")[0].strip().rstrip(",").split("=") for line in Path(MOBILE, "utils", "output.txt").read_text().splitlines() if line.startswith("out_"))
        self.assertEqual(flags, {flag: value == ".true." for flag, value in example.items()})

    def test_variable_menu(self):
        variables = {
            "rain": {"group": "Climate", "long_name": "Rainfall", "units": "mm/day", "static": False},
            "I_0-0": {"group": "I", "long_name": "Age 0", "units": "", "static": False},
            "EIR": {"group": "Human", "long_name": "EIR", "units": "day^-1", "static": False},
        }
        self.assertEqual(list(variable_choices(variables)), ["Human", "Climate", "I"])
        self.assertEqual(variable_choices(variables)["Human"]["EIR"], "EIR")
        self.assertEqual(preferred_variable(variables, "rain"), "rain")
        self.assertEqual(preferred_variable(variables, "V"), "EIR")
        self.assertEqual(preferred_variable({"rain": variables["rain"]}, "V"), "rain")


def work_in_a_scratch_folder(test):
    """Run a test in an empty folder outside the repository, as the example config puts its runs in the current one."""
    folder = tempfile.TemporaryDirectory()
    test.addCleanup(folder.cleanup)
    test.addCleanup(os.chdir, os.getcwd())
    os.chdir(folder.name)
    return Path(folder.name)


class TestPeriod(unittest.TestCase):
    def setUp(self):
        work_in_a_scratch_folder(self)
        self.rain = Config.load(CONFIG).inputs["rain_file"]

    def test_problems_and_length(self):
        self.assertEqual(period_problems(None), [])
        self.assertEqual(period_problems({"start": "2013-01-01", "end": "2013-12-31"}), [])
        self.assertTrue(period_problems({"start": "2013-02-01", "end": "2013-01-31"}))
        self.assertTrue(period_problems({"start": "soon", "end": "2013-01-31"}))
        self.assertTrue(period_problems({"start": "2013-01-01"}))
        self.assertEqual(period_days({"start": "2013-01-01", "end": "2013-12-31"}), 365)
        self.assertEqual(period_days({"start": "2013-01-01", "end": "2013-01-01"}), 1)
        self.assertEqual(length_text(1), "1 day")
        self.assertEqual(length_text(1096), "1,096 days (3.00 years)")

    def test_days_of_the_example_data(self):
        import numpy as np

        days = driving_days(self.rain)
        self.assertEqual((str(days[0]), str(days[-1]), len(days)), ("2012-01-01", "2014-12-31", 1096))
        self.assertEqual(day_range(days, {"start": "2012-01-01", "end": "2014-12-31"}), (0, 1095))
        self.assertEqual(day_range(days, {"start": "2013-01-01", "end": "2013-12-31"}), (366, 730))
        self.assertTrue(np.all(np.diff(days).astype(int) == 1))
        with self.assertRaises(ValueError):
            day_range(days, {"start": "2011-12-31", "end": "2013-12-31"})
        with self.assertRaises(ValueError):
            day_range(days, {"start": "2013-01-01", "end": "2015-01-01"})
        self.assertIsNone(driving_days("missing.nc"))

    def test_kept_in_the_config_and_checked(self):
        period = {"start": "2013-01-01", "end": "2013-12-31"}
        self.assertEqual(replace(Config.load(CONFIG), period=period).period, period)
        with self.assertRaises(ConfigError):
            replace(Config.load(CONFIG), period={"start": "2013-03-01", "end": "2013-01-01"}).validate()


class TestDrivingChecks(unittest.TestCase):
    def setUp(self):
        self.folder = work_in_a_scratch_folder(self)
        self.inputs = dict(Config.load(CONFIG).inputs)

    def changed(self, key, change):
        """The example inputs with one file rewritten by `change(dataset) -> dataset`."""
        import xarray as xr

        path = self.folder / f"{key}.nc"
        with xr.open_dataset(self.inputs[key]) as data:
            change(data.load()).to_netcdf(path)
        return {**self.inputs, key: str(path)}

    def test_the_example_data_agree(self):
        self.assertEqual(driving_problems(self.inputs), [])

    def test_units(self):
        flux = self.changed("rain_file", lambda d: d.assign(precip=(d.precip.dims, d.precip.values / 86400, {"units": "kg m-2 s-1"})))
        self.assertTrue(any("kg m-2 s-1" in text and "86400" in text for text in driving_problems(flux)))
        kelvin = self.changed("temp_file", lambda d: d.assign(temperature=(d.temperature.dims, d.temperature.values + 273.15, {"units": "K"})))
        self.assertTrue(any("273.15" in text for text in driving_problems(kelvin)))
        # Without units, the values tell
        bare = self.changed("temp_file", lambda d: d.assign(temperature=(d.temperature.dims, d.temperature.values + 273.15)))
        self.assertTrue(any("kelvin" in text for text in driving_problems(bare)))

    def test_grid_and_days(self):
        import numpy as np

        coarse = self.changed("temp_file", lambda d: d.isel(latitude=slice(0, 10)))
        self.assertTrue(any(text.startswith("Temperature") and "grid" in text for text in driving_problems(coarse)))
        short = self.changed("temp_file", lambda d: d.isel(time=slice(0, 1000)))
        self.assertTrue(any(text.startswith("Temperature") and "1000 days" in text for text in driving_problems(short)))
        later = self.changed("temp_file", lambda d: d.assign_coords(time=d.time.values + np.timedelta64(10, "D")))
        self.assertTrue(any("differ" in text for text in driving_problems(later)))

    def test_a_file_in_the_wrong_box(self):
        swapped = {**self.inputs, "rain_file": self.inputs["temp_file"]}
        problems = driving_problems(swapped)
        self.assertTrue(any(text.startswith("Rainfall: no variable named rain") and "temperature" in text for text in problems), problems)
        swapped = {**self.inputs, "temp_file": self.inputs["rain_file"]}
        self.assertTrue(any(text.startswith("Temperature: no variable named") and "'precip'" in text for text in driving_problems(swapped)))

    def test_unreadable_file(self):
        (self.folder / "bad.nc").write_text("not netCDF")
        problems = driving_problems({**self.inputs, "rain_file": str(self.folder / "bad.nc")})
        self.assertTrue(any(text.startswith("Rainfall: cannot be read") for text in problems))


class TestRunName(unittest.TestCase):
    def test_names(self):
        with tempfile.TemporaryDirectory() as runs:
            (Path(runs) / "taken").mkdir()
            self.assertIsNone(run_name_problem("", runs))
            self.assertIsNone(run_name_problem("kenya_e0-high.2", runs))
            for bad in ("with space", "-dash", "a/b", "é", "x" * 81):
                self.assertIsNotNone(run_name_problem(bad, runs), bad)
            self.assertIn("already exists", run_name_problem("taken", runs))

    def test_label_shows_a_chosen_name(self):
        manifest = {"date": "2026-11-02T21:05:12", "run": {"nagent": 1000, "seed": 1}, "param_overrides": {}}
        self.assertTrue(run_label("runs/kenya_e0", manifest).startswith("kenya_e0 (2026-11-02 21:05:12): "))
        self.assertTrue(run_label("runs/20261102-210512-ab12", manifest).startswith("2026-11-02 21:05:12: "))
        self.assertTrue(run_label("runs/seed_band_20261102-210512-ab12", {**manifest, "seeds": [1, 2]}).startswith("2026-11-02 21:05:12: "))


class TestClimatology(unittest.TestCase):
    """The mean rainfall or temperature of the region map, on a file whose value on a day is 10 times its
    month plus a number per cell (0 to 5): the means are known exactly."""

    def setUp(self):
        import xarray as xr

        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.days = np.arange("2012-01-01", "2014-01-01", dtype="datetime64[D]")
        months = (self.days.astype("datetime64[M]").astype(int) % 12 + 1).astype("float64")
        self.cells = np.arange(6.0).reshape(2, 3)
        rain = 10 * months[:, None, None] + self.cells
        self.path = Path(folder.name, "rain.nc")
        xr.Dataset({"rain": (("time", "lat", "lon"), rain, {"units": "mm/day"})},
                   coords={"time": self.days.astype("datetime64[ns]"), "lat": [10.0, 10.1], "lon": [-16.0, -15.9, -15.8]}).to_netcdf(self.path)

    def test_all_year(self):
        mean = climatology(self.path, "rain_file")
        months = self.days.astype("datetime64[M]").astype(int) % 12 + 1
        np.testing.assert_allclose(mean.values, 10 * months.mean() + self.cells)
        self.assertEqual(mean.attrs["days"], 731)
        self.assertEqual(mean.attrs["units"], "mm/day")

    def test_month_and_period(self):
        march = climatology(self.path, "rain_file", months=(3,))
        np.testing.assert_allclose(march.values, 30 + self.cells)
        self.assertEqual(march.attrs["days"], 62)
        start, end = datetime.date(2013, 2, 1), datetime.date(2013, 3, 31)
        both = climatology(self.path, "rain_file", start, end)
        np.testing.assert_allclose(both.values, (28 * 20 + 31 * 30) / 59 + self.cells)
        self.assertEqual(both.attrs["days"], 59)
        self.assertEqual(climatology(self.path, "rain_file", start, end, months=(2,)).attrs["days"], 28)

    def test_season(self):
        # December, January and February of 2012 and 2013: 62, 62 and 29 + 28 days, at 120, 10 and 20
        winter = climatology(self.path, "rain_file", months=(12, 1, 2))
        np.testing.assert_allclose(winter.values, (62 * 120 + 62 * 10 + 57 * 20) / 181 + self.cells)
        self.assertEqual(winter.attrs["days"], 181)

    def test_no_days(self):
        with self.assertRaisesRegex(ValueError, "no days in the period for these months"):
            climatology(self.path, "rain_file", datetime.date(2013, 2, 1), datetime.date(2013, 3, 31), months=(7,))


class TestModelChoice(unittest.TestCase):
    """The cholera model is listed as to come: not selectable, and a setup with it runs VECTRI-ABM in the GUI."""

    def setUp(self):
        work_in_a_scratch_folder(self)

    def test_model_to_come_falls_back(self):
        example = Config.load(CONFIG)
        cholera = replace(example, run={**example.run, "disID": 0})
        config, note = available_model(cholera)
        self.assertEqual(config.run["disID"], AVAILABLE_MODEL)
        self.assertEqual(note, MODEL_TO_COME_NOTE)
        self.assertEqual({key: value for key, value in config.run.items() if key != "disID"},
                         {key: value for key, value in cholera.run.items() if key != "disID"})

    def test_available_model_unchanged(self):
        example = Config.load(CONFIG)
        self.assertEqual(example.run["disID"], 1)
        self.assertEqual(available_model(example), (example, None))

    def test_menu_greys_out_cholera(self):
        menu = str(_model_select("1"))
        self.assertRegex(menu, r'<option value="0" disabled[^>]*>Cholera model \(to come\)</option>')
        self.assertNotRegex(menu, r'<option value="1"[^>]*disabled')


class TestSetup(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(self.folder)
        patch = mock.patch.dict(os.environ, {"MOBILE_CONFIG_DIR": str(self.folder / "settings")})
        patch.start()
        self.addCleanup(patch.stop)
        self.example = Config.load(CONFIG)
        self.run = dict(self.example.run)
        self.files = {key: value for key, value in self.example.inputs.items()}
        self.age = self.example.age_structure

    def test_fields_give_a_config(self):
        files = {**self.files, "mortality_file": "", "imm_forcing": "  "}
        config = from_fields(MOBILE, " Study ", "results", self.run, files, age_structure=self.age)
        self.assertEqual(config.project, "Study")
        self.assertEqual(config.runs_dir, (self.folder / "results").resolve())
        self.assertEqual((config.inputs["mortality_file"], config.inputs["imm_forcing"]), ("NONE", "NONE"))
        # Number boxes give floats
        self.assertEqual(from_fields(MOBILE, "", "runs", {**self.run, "nstep": 365.0}, self.files, age_structure=self.age).run["nstep"], 365)

    def test_problems_are_listed_with_the_labels_of_the_panel(self):
        with self.assertRaises(ConfigError) as caught:
            from_fields(MOBILE, "", "runs", self.run, {**self.files, "rain_file": "missing.nc", "pop_file": ""})
        problems = setup_problems(caught.exception)
        self.assertTrue(any(line.startswith("Rainfall: not found") for line in problems), problems)
        self.assertTrue(any(line.startswith("Population density: not found") for line in problems), problems)

    def test_remembered_between_sessions(self):
        self.assertIsNone(load_setup(MOBILE))
        config = from_fields(MOBILE, "Study", "runs", self.run, self.files, age_structure=self.age)
        save_setup(config)
        self.assertEqual(load_setup(MOBILE), config)
        # Not valid any more, e.g. a file moved: as if there were none
        saved = self.folder / "settings" / "last_setup.json"
        saved.write_text(saved.read_text().replace("rain.nc", "moved.nc"))
        self.assertIsNone(load_setup(MOBILE))

    def test_shapes_remembered_and_dropped_when_moved(self):
        shapes = {"file": str(write_shapes(self.folder / "villages", TestShapes.SQUARES, "EPSG:32637")), "name": "village", "merge": None}
        config = from_fields(MOBILE, "Study", "runs", self.run, self.files, age_structure=self.age, shapes=shapes)
        save_setup(config)
        self.assertEqual(load_setup(MOBILE).shapes, shapes)
        with self.assertRaises(ConfigError) as caught:
            from_fields(MOBILE, "Study", "runs", self.run, self.files, age_structure=self.age, shapes={**shapes, "name": "region"})
        self.assertIn("no field 'region'", str(caught.exception))
        # A moved shapefile only draws on the maps: the rest of the setup still loads, and a run made with it too
        Path(shapes["file"]).rename(self.folder / "moved.shp")
        self.assertIsNone(load_setup(MOBILE).shapes)
        manifest = {"run": self.run, "inputs": self.files, "age_structure": self.age, "shapes": shapes}
        self.assertIsNone(from_manifest(manifest, from_fields(MOBILE, "Study", "runs", self.run, self.files, age_structure=self.age)).shapes)
        # In a configuration file, relative to it
        Path(self.folder / "moved.shp").rename(shapes["file"])
        yaml_file = self.folder / "with_shapes.yaml"
        yaml_file.write_text(CONFIG.read_text().replace("$MOBILE", str(MOBILE)).replace("./", str(CONFIG.parent) + "/")
                             + "shapes: {file: villages.shp, merge: district}\n")
        loaded = Config.load(yaml_file, mobile=MOBILE)
        self.assertEqual(loaded.shapes, {"file": str(Path(shapes["file"]).resolve()), "name": None, "merge": "district"})

    def test_restored_from_a_run(self):
        current = from_fields(MOBILE, "Study", "elsewhere", self.run, self.files, age_structure=self.age)
        manifest = {"run": {**self.run, "nagent": 5000}, "inputs": self.files, "age_structure": {**self.age, "product": "R2025A", "year": 2020}}
        restored = from_manifest(manifest, current)
        self.assertEqual(restored.run["nagent"], 5000)
        self.assertEqual(restored.age_structure["year"], 2020)
        self.assertEqual((restored.project, restored.runs_dir), (current.project, current.runs_dir))
        # A run made with an age file, before WorldPop was in the GUI, cannot be restored
        with self.assertRaisesRegex(ConfigError, "age_file is no longer used"):
            from_manifest({"run": self.run, "inputs": {**self.files, "age_file": str(CONFIG)}}, current)

    def test_file_browser(self):
        (self.folder / "sub").mkdir()
        (self.folder / ".hidden").mkdir()
        for name in ("b.nc", "a.NC", "notes.txt", "data.csv"):
            (self.folder / name).touch()
        self.assertEqual(list_folder(self.folder, "netcdf"), (["settings", "sub"] if (self.folder / "settings").exists() else ["sub"], ["a.NC", "b.nc"]))
        self.assertEqual(list_folder(self.folder, "text")[1], ["data.csv", "notes.txt"])
        self.assertEqual(list_folder(self.folder, "folder")[1], [])
        self.assertEqual(start_folder(str(self.folder / "b.nc")), self.folder.resolve())
        # Empty, or a path that does not exist: the folder the GUI was started in
        self.assertEqual(start_folder(""), Path.cwd())
        self.assertEqual(start_folder(str(self.folder / "nowhere" / "x.nc")), Path.cwd())

    def test_new_folder(self):
        path, problem = create_folder(self.folder, " kenya_2025 ")
        self.assertEqual((path, problem), ((self.folder / "kenya_2025").resolve(), None))
        self.assertTrue(path.is_dir())
        self.assertIsNone(create_folder(self.folder, "kenya_2025")[0])
        for name in ("", "two words", "../up", ".hidden", "a/b"):
            path, problem = create_folder(self.folder, name)
            self.assertIsNone(path)
            self.assertTrue(problem)
        self.assertIsNone(create_folder(self.folder / "missing", "x")[0])

    def test_results_folder_inside_the_repository(self):
        with self.assertRaises(ConfigError):
            from_fields(MOBILE, "Study", str(Path(MOBILE) / "runs"), self.run, self.files, age_structure=self.age)


def write_shapes(stem, squares, crs=None, kind="polygon"):
    """A shapefile of squares {(west, south, size): {field: value}} in degrees, written in the coordinates of crs
    (e.g. "EPSG:32637", UTM zone 37N, with its .prj), or in longitude and latitude without a .prj."""
    import pyproj
    import shapefile
    to = pyproj.Transformer.from_crs("EPSG:4326", crs, always_xy=True) if crs else None
    with shapefile.Writer(str(stem), shapeType=shapefile.POLYGON if kind == "polygon" else shapefile.POINT) as writer:
        fields = list(next(iter(squares.values())))
        for field in fields:
            writer.field(field, "C")
        for (west, south, size), record in squares.items():
            ring = [(west, south), (west, south + size), (west + size, south + size), (west + size, south), (west, south)]
            if to:
                ring = [to.transform(x, y) for x, y in ring]
            if kind == "polygon":
                writer.poly([ring])
            else:
                writer.point(*ring[0])
            writer.record(*[record[field] for field in fields])
    if crs:
        Path(f"{stem}.prj").write_text(pyproj.CRS(crs).to_wkt(pyproj.enums.WktVersion.WKT1_ESRI))
    return Path(f"{stem}.shp")


class TestShapes(unittest.TestCase):
    # Made-up villages in two made-up districts, in the highlands of the Horn of Africa (UTM zone 37N)
    SQUARES = {(38.8, 8.6, 0.1): {"village": "A", "district": "North"}, (38.9, 8.6, 0.1): {"village": "B", "district": "North"},
               (38.8, 8.5, 0.1): {"village": "C", "district": "South"}}

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)

    def test_projected_shapefile_in_longitude_and_latitude(self):
        import shapely
        from mobile.shapes import read_shapes
        shapes = read_shapes(write_shapes(self.folder / "villages", self.SQUARES, "EPSG:32637"))
        self.assertEqual(shapes.crs, "WGS 84 / UTM zone 37N")
        self.assertTrue(shapes.converted)
        self.assertEqual(shapes.fields, ("village", "district"))
        self.assertEqual([record["village"] for record in shapes.records], ["A", "B", "C"])
        # The corners come back where they were, to about a millimetre
        np.testing.assert_allclose(shapely.total_bounds(np.array(shapes.geometries, dtype=object)), [38.8, 8.5, 39.0, 8.7], atol=1e-8)

    def test_zip_and_longitude_latitude_without_prj(self):
        import zipfile
        from mobile.shapes import ShapeError, read_shapes
        shp = write_shapes(self.folder / "villages", self.SQUARES, "EPSG:32637")
        with zipfile.ZipFile(self.folder / "villages.zip", "w") as archive:
            for suffix in (".shp", ".shx", ".dbf", ".prj"):
                archive.write(shp.with_suffix(suffix), f"inside/villages{suffix}")
        self.assertEqual(len(read_shapes(self.folder / "villages.zip").geometries), 3)
        # Without a .prj: longitude and latitude are taken as such, with a note; metres cannot be
        plain = read_shapes(write_shapes(self.folder / "plain", self.SQUARES))
        self.assertFalse(plain.converted)
        self.assertIn("no .prj", plain.note)
        shp.with_suffix(".prj").unlink()
        with self.assertRaisesRegex(ShapeError, "no .prj"):
            read_shapes(shp)
        with self.assertRaisesRegex(ShapeError, "only areas"):
            read_shapes(write_shapes(self.folder / "points", self.SQUARES, kind="point"))
        shp.with_suffix(".dbf").unlink()
        with self.assertRaisesRegex(ShapeError, "needs its .dbf"):
            read_shapes(shp)

    def test_named_merged_and_outlined(self):
        from mobile.shapes import ShapeError, areas, choice_problems, name_field, outlines, read_shapes
        path = write_shapes(self.folder / "villages", self.SQUARES, "EPSG:32637")
        shapes = read_shapes(path)
        self.assertEqual(name_field(shapes), "village")  # The most different values
        self.assertEqual([label for label, _ in areas(shapes, "village")], ["A", "B", "C"])
        merged = dict(areas(shapes, "village", "district"))
        self.assertEqual(sorted(merged), ["North", "South"])
        # North is the two squares joined: one ring of their outline, with the area of both
        self.assertEqual(merged["North"].geom_type, "Polygon")
        self.assertAlmostEqual(merged["North"].area, 0.02, places=6)
        lines, points = outlines(areas(shapes, "village", "district"))
        self.assertEqual(lines["x"].count(None), 2)
        self.assertEqual(points["text"], ["North", "South"])
        self.assertTrue(all(merged[label].contains(__import__("shapely").Point(x, y))
                            for x, y, label in zip(points["x"], points["y"], points["text"])))
        with self.assertRaisesRegex(ShapeError, "no field 'region'"):
            areas(shapes, "region")
        self.assertEqual(choice_problems({"file": str(path), "name": "village", "merge": None}), [])
        self.assertIn("no file", choice_problems({"file": str(self.folder / "moved.shp")})[0])

    def test_single_cell_drawn_at_its_size(self):
        # One cell of 0.5°, with its bounds: drawn 0.5° wide, as the model takes it; without bounds, 0.05° as before
        from mobile.driving import field_limits, open_field
        from mobile.grid import read_grid
        from mobile.plots import grid_figure
        for bounds in (True, False):
            path = self.folder / f"one_{bounds}.nc"
            with netCDF4.Dataset(path, "w") as data:
                for axis, centre in (("lat", 8.75), ("lon", 38.75)):
                    data.createDimension(axis, 1)
                    variable = data.createVariable(axis, "f8", (axis,))
                    variable[:] = [centre]
                    if bounds:
                        data.createDimension("bnds", 2) if "bnds" not in data.dimensions else None
                        data.createVariable(f"{axis}_bnds", "f8", (axis, "bnds"))[:] = [[centre - 0.25, centre + 0.25]]
                        variable.bounds = f"{axis}_bnds"
                data.createVariable("pop", "f4", ("lat", "lon"))[:] = [[0.001]]
            size = 0.5 if bounds else 0.05
            field = open_field(path, "pop_file")
            region_map = map_figure(field, None, ("Population", ""), 1, field_limits(field, log=True), log=True)
            for figure in (region_map, grid_figure(read_grid(path))):
                self.assertEqual((figure.data[0].dx, figure.data[0].dy), (size, size))
                np.testing.assert_allclose(figure.layout.xaxis.range, [38.75 - size / 2, 38.75 + size / 2])

    def test_merged_without_slivers(self):
        # Areas that do not quite meet leave slivers when merged: holes and pieces under 1,000 m² go, a real hole stays
        import shapely
        from mobile.shapes import _square_metres, _without_slivers
        metre = 1 / 111_000  # About a metre, in degrees, near the equator
        outer = [(39, 8), (39.1, 8), (39.1, 8.1), (39, 8.1)]
        sliver = [(39.05, 8.05), (39.05 + 2 * metre, 8.05), (39.05 + 2 * metre, 8.05 + 2 * metre), (39.05, 8.05 + 2 * metre)]
        hole = [(39.01, 8.01), (39.02, 8.01), (39.02, 8.02), (39.01, 8.02)]  # About 1.2 km²
        crumb = shapely.box(39.2, 8, 39.2 + 3 * metre, 8 + 3 * metre)
        cleaned = _without_slivers(shapely.MultiPolygon([shapely.Polygon(outer, [sliver, hole]), crumb]))
        self.assertEqual(cleaned.geom_type, "Polygon")
        self.assertEqual(len(cleaned.interiors), 1)
        self.assertAlmostEqual(_square_metres(cleaned.interiors[0]) / 1e6, 1.2, delta=0.05)

    def test_drawn_on_the_maps(self):
        from mobile.shapes import areas, outlines, read_shapes
        drawn = outlines(areas(read_shapes(write_shapes(self.folder / "villages", self.SQUARES, "EPSG:32637")), "village"))
        grid = {"lat": np.array([8.55, 8.65]), "lon": np.array([38.85, 38.95]), "mask": np.ones((2, 2), bool)}
        from mobile.plots import grid_figure
        without, with_shapes = len(grid_figure(grid).data), grid_figure(grid, shapes=drawn)
        self.assertEqual(len(with_shapes.data), without + 3)  # Halo, line, and the names on hovering
        self.assertEqual(list(with_shapes.data[-1].text), ["A", "B", "C"])
        # The view shows all the areas, also beyond a grid of one cell
        one = grid_figure({"lat": np.array([8.55]), "lon": np.array([38.85]), "mask": np.ones((1, 1), bool)}, shapes=drawn)
        np.testing.assert_allclose([*one.layout.xaxis.range, *one.layout.yaxis.range], [38.8, 39.0, 8.5, 8.7], atol=1e-5)


class TestDrivingPreview(unittest.TestCase):
    def setUp(self):
        self.example = Path(MOBILE, "utils", "test_run")

    def test_example_files(self):
        rain = open_field(self.example / "rain.nc", "rain_file")
        temp = open_field(self.example / "t2m.nc", "temp_file")
        pop = open_field(self.example / "pop.nc", "pop_file")
        self.assertEqual(rain.dims, ("time", "lat", "lon"))
        self.assertEqual(rain.attrs["units"], "mm/day")
        self.assertEqual(temp.sizes["time"], rain.sizes["time"])
        self.assertEqual(pop.dims, ("lat", "lon"))
        self.assertEqual((rain.sizes["lat"], rain.sizes["lon"]), (pop.sizes["lat"], pop.sizes["lon"]))

    def test_names_order_and_one_step_of_time(self):
        import numpy as np
        import xarray as xr
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = Path(folder.name, "pop.nc")
        values = np.arange(6, dtype="float32").reshape(1, 2, 3)
        xr.Dataset(
            {"Band1": (("valid_time", "Y", "X"), values)},
            coords={"valid_time": [0], "Y": [1.0, 0.0], "X": [0.0, 1.0, 2.0]},
        ).to_netcdf(path)
        pop = open_field(path, "pop_file")
        self.assertEqual(pop.dims, ("lat", "lon"))
        self.assertEqual(pop["lat"].values.tolist(), [0.0, 1.0])
        # The row of latitude 1 was first in the file
        self.assertEqual(pop.values[1].tolist(), [0.0, 1.0, 2.0])
        with self.assertRaises(ValueError):
            open_field(path, "rain_file")

    def test_colour_range(self):
        import numpy as np
        import xarray as xr
        values = np.tile(np.arange(101.0), (300, 1))[:, :, None]  # 300 days, 101 x 1 cells
        field = xr.DataArray(values, dims=("time", "lat", "lon"))
        self.assertEqual(field_limits(field), (1.0, 99.0))
        field[:, 0, 0] = np.nan
        np.testing.assert_allclose(field_limits(field), (1.99, 99.01))
        # On a log scale, from the positive values only
        self.assertEqual(field_limits(xr.DataArray([-1.0, 0.0, 0.0, 10.0]), log=True), (10.0, 100.0))

    def test_mean_age(self):
        import numpy as np
        # As many people at each year of age from 0 to 9: a mean of 5 years
        self.assertAlmostEqual(mean_age(np.arange(10), np.full(10, 0.1)), 5.0)

    def test_driving_maps_are_not_masked(self):
        import numpy as np
        rain = open_field(self.example / "rain.nc", "rain_file")
        figure = map_figure(rain, None, ("Rainfall", "mm/day"), 1, (0.0, 20.0))
        shown = np.asarray(figure.data[0].customdata, dtype="float64")
        self.assertEqual(int(np.isnan(shown).sum()), int(np.isnan(rain.isel(time=0).values).sum()))
        self.assertEqual(figure.layout.meta["date"], "2012-01-01")


class TestPort(unittest.TestCase):
    def test_a_port_in_use_is_skipped(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as busy:
            busy.bind(("127.0.0.1", 0))
            busy.listen()
            taken = busy.getsockname()[1]
            self.assertNotEqual(free_port(taken), taken)
            self.assertGreater(free_port(taken), taken)

    def test_a_free_port_is_kept(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        self.assertEqual(free_port(port), port)


class TestMapScale(unittest.TestCase):
    def test_units_in_brackets_once(self):
        self.assertEqual(units_label("day^-1"), "[day<sup>−1</sup>]")
        self.assertEqual(units_label("probability day^-1"), "[probability day<sup>−1</sup>]")
        self.assertEqual(units_label("km^-2"), "[km<sup>−2</sup>]")
        self.assertEqual(units_label("kg m-2 s-1"), "[kg m<sup>−2</sup> s<sup>−1</sup>]")
        self.assertEqual(units_label("m**2"), "[m<sup>2</sup>]")
        self.assertEqual(units_label("m2"), "[m<sup>2</sup>]")
        self.assertEqual(units_label("mm/day"), "[mm/day]")
        self.assertEqual(units_label("[agents]"), "[agents]")
        self.assertEqual(units_label("[fraction]"), "[fraction]")
        self.assertEqual(units_label(" "), "")

    def test_grid_step(self):
        self.assertEqual(grid_step(6.95), 1)
        self.assertEqual(grid_step(1.2), 0.2)
        self.assertEqual(grid_step(40), 5)

    def test_linear_scale_keeps_values(self):
        import numpy as np
        values = np.array([0.0, 0.5, np.nan])
        z, zmin, zmax, ticks = colour_values(values, (0.0, 1.0))
        self.assertIs(z, values)
        self.assertEqual((zmin, zmax, ticks), (0.0, 1.0, {}))

    def test_log_scale(self):
        import numpy as np
        z, zmin, zmax, ticks = colour_values(np.array([0.0, -1.0, 0.01, 1.0, 100.0, np.nan]), (0.01, 100.0), log=True)
        # Zero and negative values take the lowest colour; cells that are not simulated stay empty
        self.assertEqual(z[:5].tolist(), [-2.0, -2.0, -2.0, 0.0, 2.0])
        self.assertTrue(np.isnan(z[5]))
        self.assertEqual((zmin, zmax), (-2.0, 2.0))
        self.assertEqual(ticks["ticktext"], ["0.01", "0.1", "1", "10", "100"])
        _, _, _, ticks = colour_values(np.array([0.5]), (0.2, 3.0), log=True)
        self.assertEqual(ticks["ticktext"], ["0.2", "0.5", "1", "2"])


class TestHeaderAndLogos(unittest.TestCase):
    def test_logo_files(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            for name in ("b.png", "a.SVG", "README.md", "ictp.jpg"):
                (folder / name).touch()
            self.assertEqual([p.name for p in logo_files(folder)], ["a.SVG", "b.png", "ictp.jpg"])
            self.assertEqual([p.name for p in logo_files(folder, "ictp")], ["ictp.jpg"])
            self.assertEqual(logo_files(folder / "missing"), [])

    def test_project_comes_from_the_configuration(self):
        with tempfile.TemporaryDirectory() as folder:
            cwd = os.getcwd()
            os.chdir(folder)
            try:
                self.assertEqual(Config.load(CONFIG).project, "MoBILE example")
            finally:
                os.chdir(cwd)


class TestAgeMenu(unittest.TestCase):
    variables = {
        "EIR": {"group": "Human", "long_name": "EIR", "units": "day^-1", "static": False},
        "I_bulk": {"group": "I", "long_name": "Prevalence", "units": "fraction", "static": False},
        "I_0-0": {"group": "I", "long_name": "Prevalence by age", "units": "fraction", "static": False},
        "I_60+": {"group": "I", "long_name": "Prevalence by age", "units": "fraction", "static": False},
        "Na_0-0": {"group": "Na", "long_name": "Count by age", "units": "[agents]", "static": False},
        "Na_60+": {"group": "Na", "long_name": "Count by age", "units": "[agents]", "static": False},
        "rain_rate": {"group": "Climate", "long_name": "Rain", "units": "mm/day", "static": False},
    }

    def test_bands_are_one_entry(self):
        choices = variable_choices(self.variables)
        self.assertEqual(choices["By age"], {"age:I": "Prevalence by age", "age:Na": "Count by age"})
        self.assertEqual(set(age_groups(self.variables)), {"I", "Na"})

    def test_all_ages_comes_first_only_if_the_file_has_it(self):
        self.assertEqual(age_choices(age_groups(self.variables)["I"]), {"bulk": "All ages", "0-0": "Age 0-0", "60+": "Age 60+"})
        self.assertEqual(list(age_choices(age_groups(self.variables)["Na"])), ["0-0", "60+"])

    def test_resolving_a_field(self):
        self.assertEqual(resolve_variable(self.variables, "EIR"), "EIR")
        self.assertEqual(resolve_variable(self.variables, "age:I", "60+"), "I_60+")
        self.assertEqual(resolve_variable(self.variables, "age:I", None), "I_bulk")
        self.assertEqual(resolve_variable(self.variables, "age:Na", "bulk"), "Na_0-0")
        self.assertEqual(preferred_variable(self.variables, "age:Na"), "age:Na")
        self.assertEqual(preferred_variable(self.variables, "I_bulk"), "EIR")


class TestCellSelection(unittest.TestCase):
    def test_third_cell_replaces_the_oldest_and_takes_its_colour(self):
        cells = next_cells([], 1.0, 1.0)
        cells = next_cells(cells, 2.0, 2.0)
        self.assertEqual([(c["lon"], c["colour"]) for c in cells], [(1.0, 0), (2.0, 1)])
        cells = next_cells(cells, 3.0, 3.0)
        self.assertEqual([(c["lon"], c["colour"]) for c in cells], [(2.0, 1), (3.0, 0)])
        cells = next_cells(cells, 4.0, 4.0)
        self.assertEqual([(c["lon"], c["colour"]) for c in cells], [(3.0, 0), (4.0, 1)])

    def test_clicking_a_selected_cell_changes_nothing(self):
        cells = next_cells(next_cells([], 1.0, 1.0), 2.0, 2.0)
        self.assertEqual(next_cells(cells, 1.0, 1.0), cells)
        self.assertEqual(next_cells(cells, 2.0, 2.0), cells)


class TestBasemap(unittest.TestCase):
    def test_no_connection_gives_no_basemap(self):
        with tempfile.TemporaryDirectory() as cache, mock.patch.dict(os.environ, {"MOBILE_CACHE_DIR": cache}):
            with mock.patch("urllib.request.urlopen", side_effect=OSError("no connection")):
                self.assertIsNone(load_basemap([0.0, 1.0], [0.0, 1.0]))


class TestCalibrationTemplate(unittest.TestCase):
    """A calibration used as a template: its offset cells or regions found again on the cells of the setup now."""

    CELLS = [{"lat": lat, "lon": lon, "mean": 15.0 + lat - 8, "people": 100.0}
             for lat in (8.05, 8.15, 8.25, 8.35) for lon in (38.55, 38.65, 38.75, 38.85)]

    def test_cells_and_regions(self):
        from mobile.calibration_run_ui import regions, template_regions

        # One offset per cell: the same cells
        self.assertEqual(template_regions([{"lat": 8.05, "lon": 38.55}, {"lat": 8.25, "lon": 38.75}], self.CELLS),
                         (None, {(8.05, 38.55), (8.25, 38.75)}))
        # Regions with their size kept, and without it (calibrations made before): the size found from their boxes
        boxes = regions(self.CELLS, 0.2)
        recorded = [{"lat": b["lat"], "lon": b["lon"], "members": b["members"]} for b in boxes[:2]]
        expected = {(round(b["lat"], 6), round(b["lon"], 6)) for b in boxes[:2]}
        self.assertEqual(template_regions(recorded, self.CELLS, 0.2), (0.2, expected))
        self.assertEqual(template_regions(recorded, self.CELLS), (0.2, expected))
        # Not those of the setup now (another grid): nothing matched
        self.assertIsNone(template_regions([{"lat": 10.05, "lon": 38.55}], self.CELLS))
        moved = [{**recorded[0], "members": recorded[0]["members"][:1]}]  # A box of other cells than now
        self.assertIsNone(template_regions(moved, self.CELLS))

    def test_new_name(self):
        from mobile.calibration_run_ui import unique_name

        self.assertEqual(unique_name("look", {"look"}), "look_2")
        self.assertEqual(unique_name("look", {"look", "look_2", "look_3"}), "look_4")


class TestMapPointsAndRelief(unittest.TestCase):
    def test_clicks_snap_to_the_cell_centres(self):
        from mobile.plots import snap_to_cell

        lat, lon = np.round(np.arange(8.05, 9.46, 0.1), 2), np.round(np.arange(38.55, 39.46, 0.1), 2)
        self.assertEqual(snap_to_cell(lat, lon, 38.7312, 8.6687), (38.75, 8.65))  # Anywhere in a cell: its centre
        self.assertEqual(snap_to_cell(lat, lon, 38.55, 8.05), (38.55, 8.05))
        self.assertEqual(snap_to_cell(lat, lon, 38.47, 8.0), (38.55, 8.05))  # Just outside the corner: the corner cell
        self.assertIsNone(snap_to_cell(lat, lon, 38.3, 8.6))  # More than a cell outside: nothing
        self.assertEqual(snap_to_cell([8.75], [38.75], 38.9, 8.7, steps=(0.5, 0.5)), (38.75, 8.75))  # One cell, its size known

    def test_relief_is_a_shading_over_the_data(self):
        import base64
        import io

        import xarray as xr
        from PIL import Image

        from mobile.basemap import LIGHT_ALPHA, SHADOW_ALPHA, Basemap, _shading
        from mobile.plots import map_figure

        # Flat land, sea, and a ridge running north-south: its west slope faces the light (northwest), its east one not
        lats, lons = np.arange(0.0, 1.0, 0.01), np.arange(0.0, 1.0, 0.01)
        elevation = np.full((len(lats), len(lons)), 500.0)
        elevation[:, :20] = -100.0  # Sea in the west
        ridge = 3000.0 * np.exp(-((lons - 0.6) / 0.05) ** 2)
        elevation[:, 20:] += ridge[20:]
        terrain = _shading(elevation, lats, lons)
        image = Image.open(io.BytesIO(base64.b64decode(terrain.image.split(",", 1)[1])))
        self.assertEqual(image.mode, "LA")
        grey, alpha = (np.asarray(image)[::-1][..., k] for k in (0, 1))  # Back to lat increasing
        self.assertEqual(alpha[:, :20].max(), 0)  # Sea: transparent
        self.assertEqual(alpha[50, 30], 0)  # Flat land: transparent, its colour as it is
        lit, shaded = alpha[50, 57], alpha[50, 63]  # West and east slopes of the ridge
        self.assertEqual((grey[50, 57], grey[50, 63]), (255, 0))  # Lighter on the lit slope, darker on the other
        self.assertTrue(0 < lit <= LIGHT_ALPHA * 255 + 1 and 0 < shaded <= SHADOW_ALPHA * 255 + 1, (lit, shaded))
        # Laid over the data, which keep their colours (full opacity)
        data = xr.DataArray(np.ones((1, 2, 2)), dims=("time", "lat", "lon"),
                            coords={"time": [np.datetime64("2000-01-01")], "lat": [0.25, 0.75], "lon": [0.25, 0.75]})
        basemap = Basemap(land=[], lakes=[], rivers={"x": [], "y": []}, borders={"x": [], "y": []})
        figure = map_figure(data, None, ("x", "1"), 1, (0.0, 2.0), basemap=basemap, terrain=terrain)
        self.assertEqual(figure.layout.images[0].layer, "above")
        self.assertIn(figure.data[0].opacity, (None, 1))


class TestListRuns(unittest.TestCase):
    def _run(self, root, name, status="finished", pop="p.nc", date="2026-01-01T00:00:00", output=True):
        folder = Path(root) / name
        (folder / "output").mkdir(parents=True)
        manifest = {"status": status, "date": date, "inputs": {"pop_file": pop}, "returncode": 0, "wall_seconds": 1, "spinup_years": 2}
        (folder / "run.json").write_text(json.dumps(manifest))
        if output:
            (folder / "output" / "output.nc").touch()

    def test_only_loadable_runs_newest_first(self):
        with tempfile.TemporaryDirectory() as root:
            self._run(root, "old")
            self._run(root, "new", date="2026-02-01T00:00:00")
            self._run(root, "failed", status="failed")
            self._run(root, "deleted", output=False)
            self._run(root, "other_grid", pop="q.nc")
            (Path(root) / "broken").mkdir()
            (Path(root) / "broken" / "run.json").write_text("{")
            self.assertEqual([Path(k).name for k in list_runs(root, "p.nc")], ["new", "old"])
            self.assertEqual(load_run(Path(root) / "new").spinup_years, 2)

    def test_seed_band_is_one_entry_only_if_complete(self):
        with tempfile.TemporaryDirectory() as root:
            for band, status in (("complete", "finished"), ("cancelled", "cancelled"), ("incomplete", "finished")):
                self._run(root, f"{band}/seed_1")
                self._run(root, f"{band}/seed_2", output=band != "incomplete")
                write_seed_band(Path(root) / band, status, [1, 2])
            runs = list_runs(root, "p.nc")
            self.assertEqual([Path(k).name for k in runs], ["complete"])
            self.assertEqual(next(iter(runs.values()))["seeds"], [1, 2])
            self.assertEqual(len(load_seed_band(Path(root) / "complete")), 2)


class TestProgress(unittest.TestCase):
    def test_lines_from_real_logs(self):
        parser = ProgressParser()
        self.assertEqual(parser.parse("0.- Compile module src/mo_grid.f90").stage, "compiling")
        event = parser.parse("Spin-up convergence 0.0460 <=? 0.0150   6628.44922       7162.73779")
        self.assertEqual((event.stage, event.fraction), ("spin-up", None))
        self.assertIn("year 1", event.message)
        event = parser.parse("Integrating   183 /   365 -  50.1 %")
        self.assertEqual(event.stage, "integrating")
        self.assertAlmostEqual(event.fraction, 0.501)
        self.assertIsNone(parser.parse("Pi = 3.1416"))


class TestRunEnvironment(unittest.TestCase):
    def test_sdk_is_given_on_a_mac_unless_set(self):
        with mock.patch("mobile.runner.macos_sdk", return_value="/sdk/MacOSX.sdk"):
            self.assertEqual(run_environment("/m", {})["SDKROOT"], "/sdk/MacOSX.sdk")
            self.assertEqual(run_environment("/m", {"SDKROOT": "/mine"})["SDKROOT"], "/mine")
        with mock.patch("mobile.runner.macos_sdk", return_value=None):
            self.assertNotIn("SDKROOT", run_environment("/m", {}))
        env = run_environment("/m", {"PATH": "/bin"})
        self.assertEqual((env["MOBILE"], env["PATH"]), ("/m", "/bin"))

    def test_sdk_only_where_xcrun_finds_one(self):
        with mock.patch("sys.platform", "linux"):
            self.assertIsNone(macos_sdk())
        with mock.patch("sys.platform", "darwin"), mock.patch("subprocess.run", side_effect=FileNotFoundError):
            self.assertIsNone(macos_sdk())
        with mock.patch("sys.platform", "darwin"), mock.patch("subprocess.run") as run:
            run.return_value = mock.Mock(returncode=0, stdout="/does/not/exist\n")
            self.assertIsNone(macos_sdk())
            run.return_value = mock.Mock(returncode=0, stdout=str(Path(__file__).parent) + "\n")
            self.assertEqual(macos_sdk(), str(Path(__file__).parent))


class TestRunState(unittest.TestCase):
    """What Run, Cancel and Load run rely on: both are dataclasses, with a lock and lists of their own."""

    def test_state_is_updated_and_read(self):
        state = RunState()
        state.update(message="Day 3 of 40", fraction=0.075, member=2, members=5, cancelled=True)
        self.assertEqual(state.snapshot(), ("Day 3 of 40", 0.075, 2, 5))
        self.assertTrue(state.cancelled)
        self.assertIsNot(state.lock, RunState().lock)

    def test_outcome_from_keywords(self):
        outcome = Outcome(status="finished", nagent=1000, seeds=[1])
        self.assertEqual((outcome.status, outcome.nagent, outcome.seeds, outcome.results), ("finished", 1000, [1], []))
        outcome.results.append("result")
        self.assertEqual(Outcome(status="finished").results, [])


class TestSensitivity(unittest.TestCase):
    """Sampling and Sobol indices, checked against the Ishigami function, whose indices are known exactly."""

    def ishigami(self, values):
        x1, x2, x3 = values.T
        return np.sin(x1) + 7 * np.sin(x2) ** 2 + 0.1 * x3 ** 4 * np.sin(x1)

    def setUp(self):
        self.ishigami_parameters = [SampledParameter(f"x{i}", "uniform", -math.pi, math.pi) for i in (1, 2, 3)]

    def test_distributions_stay_in_bounds(self):
        unit = np.linspace(0, 1, 1001)
        normal = SampledParameter("a", "normal", 0.0, 1.0, mean=0.1, sd=0.2)
        lognormal = SampledParameter("b", "lognormal", 1e-4, 1.0, mean=math.log(0.01), sd=2.0)
        for parameter in (normal, lognormal):
            values = parameter.from_unit(unit)
            self.assertTrue(np.all((values >= parameter.low) & (values <= parameter.high)), parameter.name)
        # Uniform and log-uniform: the ends and the middle
        self.assertEqual(list(SampledParameter("c", "uniform", 2.0, 4.0).from_unit([0, 0.5, 1])), [2.0, 3.0, 4.0])
        np.testing.assert_allclose(SampledParameter("d", "loguniform", 1e-5, 1e-1).from_unit([0, 0.5, 1]), [1e-5, 1e-3, 1e-1])
        # Truncated where the bounds are symmetric about the mean: the median is the mean (of ln x for log-normal)
        self.assertAlmostEqual(float(SampledParameter("e", "normal", 0.0, 1.0, mean=0.5, sd=0.3).from_unit(0.5)), 0.5)
        self.assertAlmostEqual(float(SampledParameter("f", "lognormal", 1e-3, 1e1, mean=math.log(0.1), sd=1.0).from_unit(0.5)), 0.1)
        # Truncation moves the mass inside: a quarter of N(0.1, 0.2) is below 0, none of the truncated one
        self.assertGreater(float(normal.from_unit(0.25)), 0.0)

    def test_problems(self):
        good = SampledParameter("a", "uniform", 0.0, 1.0)
        self.assertEqual(good.problems(), [])
        for bad in (SampledParameter("a", "uniform", 1.0, 1.0), SampledParameter("a", "loguniform", 0.0, 1.0),
                    SampledParameter("a", "normal", 0.0, 1.0, mean=2.0, sd=0.1), SampledParameter("a", "normal", 0.0, 1.0, mean=0.5, sd=0.0),
                    SampledParameter("a", "normal", 0.0, 1.0), SampledParameter("a", "lognormal", 0.1, 1.0, mean=0.5, sd=1.0),
                    SampledParameter("a", "gamma", 0.0, 1.0)):
            self.assertTrue(bad.problems(), bad)
        self.assertIn("ln(minimum)", SampledParameter("a", "lognormal", 0.1, 1.0, mean=0.5, sd=1.0).problems()[0])
        b = SampledParameter("b", "uniform", 0.0, 1.0)
        self.assertEqual(design_problems([good, b], 64), [])
        self.assertTrue(design_problems([good], 64))
        self.assertTrue(design_problems([good, b], 100))
        self.assertTrue(design_problems([good, good], 64))

    def test_run_count(self):
        six = [SampledParameter(f"p{i}", "uniform", 0.0, 1.0) for i in range(6)]
        self.assertEqual(run_count_formula(1024, six), "N(2D+2) = 1,024 × (2·6 + 2) = 14,336 runs")
        self.assertEqual(run_count_formula(1024, six, second_order=False), "N(D+2) = 1,024 × (6 + 2) = 8,192 runs")
        self.assertEqual(run_count_formula(1024, six, seeds=5), "N(2D+2) × seeds = 1,024 × (2·6 + 2) × 5 = 71,680 runs")
        self.assertEqual(run_count(1024, six, seeds=5), 71680)

    def test_sample(self):
        parameters = [SampledParameter("a", "uniform", 2.0, 4.0), SampledParameter("b", "loguniform", 1e-5, 1e-2),
                      SampledParameter("c", "normal", 0.0, 1.0, mean=0.1, sd=0.2)]
        unit, values = sample(parameters, 64, seed=3)
        self.assertEqual(values.shape, (run_count(64, parameters), 3))
        self.assertTrue(np.all((unit >= 0) & (unit <= 1)))
        for j, parameter in enumerate(parameters):
            self.assertTrue(np.all((values[:, j] >= parameter.low) & (values[:, j] <= parameter.high)), parameter.name)
        np.testing.assert_array_equal(values, sample(parameters, 64, seed=3)[1])
        with self.assertRaises(ValueError):
            sample(parameters[:1], 64)

    def test_ishigami_indices(self):
        # Exact: S1 = (0.3139, 0.4424, 0), ST = (0.5576, 0.4424, 0.2437), S13 = 0.2437
        _, values = sample(self.ishigami_parameters, 4096, seed=1)
        indices = analyse(self.ishigami_parameters, self.ishigami(values), seed=1)
        np.testing.assert_allclose(indices["S1"], [0.3139, 0.4424, 0.0], atol=0.03)
        np.testing.assert_allclose(indices["ST"], [0.5576, 0.4424, 0.2437], atol=0.03)
        self.assertAlmostEqual(indices["S2"][0, 2], 0.2437, delta=0.05)
        self.assertTrue(np.all(indices["ST_conf"] > 0))

    def test_cells_as_salib(self):
        """The indices of each cell are SALib's for that cell alone; a scaled output has the same indices, a
        constant one none."""
        _, values = sample(self.ishigami_parameters, 256, seed=2)
        y = self.ishigami(values)
        cells = analyse_cells(self.ishigami_parameters, np.column_stack([y, 2 * y + 5, np.ones_like(y)]), second_order=True)
        alone = analyse(self.ishigami_parameters, y, num_resamples=2)
        for key in ("S1", "ST"):
            np.testing.assert_allclose(cells[key][:, 0], alone[key])
            np.testing.assert_allclose(cells[key][:, 1], alone[key])
            self.assertTrue(np.all(np.isnan(cells[key][:, 2])))
        np.testing.assert_allclose(cells["S2"][0, 2, 0], alone["S2"][0, 2])

    def test_metric(self):
        import xarray as xr

        time = np.arange("2012-01-01", "2013-01-01", dtype="datetime64[D]")
        month = np.array([int(str(day)[5:7]) for day in time], dtype="float64")
        field = xr.DataArray(np.broadcast_to(month[:, None, None], (time.size, 2, 3)).copy(), dims=("time", "lat", "lon"),
                             coords={"time": time.astype("datetime64[ns]"), "lat": [10.0, 11.0], "lon": [1.0, 2.0, 3.0]})
        field[:, 0, 0] = 100.0  # Outside the mask
        mask = xr.DataArray(np.array([[False, True, True], [True, True, True]]), dims=("lat", "lon"), coords={"lat": [10.0, 11.0], "lon": [1.0, 2.0, 3.0]})
        wet = Metric("EIR", time="sum", space="mean", months=(6, 7))
        self.assertEqual(float(reduce_field(field, wet, mask)), 30 * 6 + 31 * 7)
        self.assertEqual(float(reduce_field(field, Metric("EIR", time="max", space="sum", start="2012-03-01", end="2012-04-30"), mask)), 4 * 5)
        cells = reduce_field(field, Metric("EIR", time="mean", space="none", months=(12,)), mask)
        self.assertEqual(cells.dims, ("lat", "lon"))
        self.assertTrue(np.isnan(cells[0, 0]) and float(cells[1, 2]) == 12)
        series = reduce_field(field, Metric("EIR", time="none", space="mean", months=(1, 2)), mask)
        self.assertEqual(series.sizes["time"], 31 + 29)
        self.assertEqual(float(reduce_field(field.isel(time=0), Metric("EIR"), mask)), 1)  # A static field
        with self.assertRaises(ValueError):
            reduce_field(field, Metric("EIR", start="2013-01-01"), mask)
        for bad in (Metric("EIR", time="none", space="none"), Metric("EIR", months=(13,)), Metric("EIR", start="2012-05-01", end="2012-04-01")):
            self.assertTrue(bad.problems(), bad)


class TestBuildLock(unittest.TestCase):
    """mobile.sh changes the shared src/ while it builds, so builds take turns; built models run side by side.
    A stand-in mobile.sh writes when its build starts and ends and when its run ends."""

    FAKE = """#!/bin/bash
run=$(basename $PWD)
echo "$run build-start" >> $EVENTS; sleep 0.6; echo "$run build-end" >> $EVENTS
echo '================= Running MoBILE ================='
sleep 1.5; echo "$run run-end" >> $EVENTS
echo 'Program finished successfully'
"""

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        root = Path(folder.name)
        fake = root / "MoBILE"
        (fake / "utils").mkdir(parents=True)
        (fake / "src").mkdir()
        (fake / "utils" / "run_MOBILE.sh").write_text((Path(MOBILE) / "utils" / "run_MOBILE.sh").read_text())
        (fake / "src" / "mo_namelist.f90").write_text((Path(MOBILE) / "src" / "mo_namelist.f90").read_text())
        (fake / "mobile.sh").write_text(self.FAKE)
        self.events = root / "events.txt"
        self.events.touch()
        patch = mock.patch.dict(os.environ, {"EVENTS": str(self.events)})
        patch.start()
        self.addCleanup(patch.stop)
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(root)
        self.config = replace(Config.load(CONFIG), mobile=fake, runs_dir=root / "runs")

    def start(self, name, wait):
        import threading

        runner = Runner(self.config)
        outcome = {}

        def target():
            try:
                outcome["result"] = runner.run(name, wait=wait)
            except Exception as error:
                outcome["error"] = error

        thread = threading.Thread(target=target)
        thread.start()
        return runner, thread, outcome

    def test_builds_take_turns_and_runs_overlap(self):
        import time

        _, first, a = self.start("a", wait=True)
        time.sleep(0.2)
        _, second, b = self.start("b", wait=True)
        first.join(20)
        second.join(20)
        self.assertEqual((a.keys(), b.keys()), ({"result"}, {"result"}))
        events = self.events.read_text().split("\n")
        order = {event: index for index, event in enumerate(events)}
        self.assertLess(order["a build-end"], order["b build-start"])  # Builds do not overlap
        self.assertLess(order["b build-start"], order["a run-end"])   # The second built while the first ran

    def test_prebuilt_run_needs_no_turn(self):
        # A model built beforehand runs at once, also while another run builds and holds the lock
        import time

        _, first, _ = self.start("a", wait=True)
        time.sleep(0.2)
        binary = self.config.runs_dir.parent / "mobile.out"
        binary.write_text("#!/bin/bash\n")
        result = Runner(self.config, prebuilt=binary).run("p")  # Not RunnerBusy, without waiting
        first.join(20)
        order = {event: index for index, event in enumerate(self.events.read_text().split("\n"))}
        self.assertLess(order["p build-start"], order["a build-end"])  # It started while a held the lock
        script = (result.run_dir / "run_MOBILE.sh").read_text()
        self.assertRegex(script, rf"(?m)^\s*prebuilt='{re.escape(str(binary))}'$")
        manifest = json.loads((result.run_dir / "run.json").read_text())
        self.assertEqual(manifest["prebuilt"], str(binary))
        self.assertEqual(manifest["binary_md5"], hashlib.md5(binary.read_bytes()).hexdigest())
        # Without one, the line keeps its default: the model is built, as by a MoBILE from before -E
        plain = (self.config.runs_dir / "a" / "run_MOBILE.sh").read_text()
        self.assertRegex(plain, r"(?m)^\s*prebuilt='NONE'$")

    def test_busy_or_cancelled_while_another_builds(self):
        import time

        _, first, _ = self.start("a", wait=True)
        time.sleep(0.2)
        with self.assertRaises(RunnerBusy):
            Runner(self.config).run("b")
        runner, waiting, outcome = self.start("c", wait=True)
        time.sleep(0.2)
        runner.cancel()
        waiting.join(5)
        self.assertIsInstance(outcome.get("error"), RunCancelled)
        self.assertFalse((self.config.runs_dir / "c").exists())
        first.join(20)


class TestStudyRuns(unittest.TestCase):
    """An analysis run through run_MOBILE.sh with a stand-in mobile.sh that only writes an empty output."""

    FAKE = """#!/bin/bash
sleep ${FAKE_SLEEP:-0}
echo '================= Running MoBILE ================='
[ -n "$FAKE_FAIL" ] && { echo ' More agents than people! --> STOP'; exit 0; }
mkdir -p output && touch output/output.nc
echo 'Program finished successfully'
"""

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        root = Path(folder.name)
        fake = root / "MoBILE"
        (fake / "utils").mkdir(parents=True)
        (fake / "src").mkdir()
        (fake / "utils" / "run_MOBILE.sh").write_text((Path(MOBILE) / "utils" / "run_MOBILE.sh").read_text())
        (fake / "src" / "mo_namelist.f90").write_text((Path(MOBILE) / "src" / "mo_namelist.f90").read_text())
        (fake / "mobile.sh").write_text(self.FAKE)
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(root)
        self.config = replace(Config.load(CONFIG), mobile=fake, runs_dir=root / "runs", params={"e_0": 0.2}, output=("out_EIR",))
        self.parameters = [SampledParameter("b_rate", "loguniform", 0.2, 20.0), SampledParameter("K_h", "uniform", 1e-5, 1e-3)]

    def test_runs_every_sample_and_seed(self):
        folder = create_study(self.config, self.parameters, 2, False, [7, 8], name="small", sample_seed=1)
        self.assertEqual(folder, studies_dir(self.config.runs_dir) / "small")
        record = run_study(folder, StudyState(), parallel=4)
        self.assertEqual((record["status"], record["finished"], record["runs"]), ("finished", 16, 16))
        values = np.loadtxt(folder / "samples.txt", ndmin=2)
        self.assertEqual(values.shape, (8, 2))
        run_dir = folder / "runs" / run_name(8, 5)
        manifest = json.loads((run_dir / "run.json").read_text())
        params = read_params(run_dir / "params.txt")
        # The sampled values, the fixed parameter of the sliders, the seed and the outputs reach the run
        self.assertEqual(float(params["b_rate"]), values[5, 0])
        self.assertEqual(float(params["K_h"]), values[5, 1])
        self.assertEqual(float(params["e_0"]), 0.2)
        self.assertEqual(manifest["run"]["seed"], 8)
        self.assertEqual(manifest["output"], ["out_EIR"])
        self.assertIn(str(folder), list_studies(self.config.runs_dir))
        self.assertIn("16 runs, finished", study_label(folder, read_study(folder)))
        # Not among the single runs
        self.assertEqual(list_runs(self.config.runs_dir), {})

    def test_samples_in_the_units_shown(self):
        # mu is sampled per year, as on its slider, and reaches the run per day
        parameters = [SampledParameter("mu", "uniform", 0.02, 0.04), SampledParameter("K_h", "uniform", 1e-5, 1e-3)]
        folder = create_study(self.config, parameters, 2, False, [3], name="units", sample_seed=1)
        run_study(folder, StudyState(), parallel=2)
        values = np.loadtxt(folder / "samples.txt", ndmin=2)
        params = read_params(folder / "runs" / run_name(3, 2) / "params.txt")
        self.assertTrue(0.02 <= values[2, 0] <= 0.04)
        self.assertAlmostEqual(float(params["mu"]), values[2, 0] / 365)

    def test_old_analysis_is_refused(self):
        folder = create_study(self.config, self.parameters, 2, False, [3], name="old", sample_seed=1)
        record = read_study(folder)
        write_study(folder, {**record, "run_inputs": {**record["run_inputs"], "const": "/old/params.txt"}})
        with self.assertRaisesRegex(ConfigError, "parameter file"):
            run_study(folder, StudyState(), parallel=2)

    def test_period_is_cut_once_for_all_runs(self):
        import xarray as xr

        config = replace(self.config, period={"start": "2013-01-01", "end": "2013-12-31"})
        folder = create_study(config, self.parameters, 2, False, [3], name="year", sample_seed=1)
        self.assertEqual(read_study(folder)["period"], config.period)
        with xr.open_dataset(folder / "inputs" / "rain_file.nc") as rain:
            self.assertEqual(rain.sizes["time"], 365)
        run_study(folder, StudyState(), parallel=2)
        script = (folder / "runs" / run_name(3, 0) / "run_MOBILE.sh").read_text()
        self.assertRegex(script, r"(?m)^\s*nstep=365$")
        self.assertIn(str(folder / "inputs" / "rain_file.nc"), script)
        self.assertFalse((folder / "runs" / run_name(3, 0) / "inputs").exists())

    def test_stops_when_runs_fail_alike(self):
        folder = create_study(self.config, self.parameters, 8, False, [1], sample_seed=1)  # 8 × 4 = 32 runs
        with mock.patch.dict(os.environ, {"FAKE_FAIL": "1"}):
            record = run_study(folder, StudyState(), parallel=1)
        self.assertEqual((record["status"], record["finished"], record["failed"]), ("stopped", 0, 3))
        self.assertIn("More agents than people", record["failure"])
        self.assertIn("stopped, 0 of 32 done", study_label(folder, record))
        # Fixed: resuming runs them all
        record = run_study(folder, StudyState(), parallel=4)
        self.assertEqual((record["status"], record["finished"]), ("finished", 32))

    # Builds the model unless given one with -E, and says which, with the name of its run folder
    BUILDING = """#!/bin/bash
prebuilt=""
while getopts ":ho:p:r:t:d:n:m:s:a:c:u:v:i:l:M:B:T:C:O:E:" flag; do
  case $flag in E) [ "$OPTARG" != "NONE" ] && prebuilt=$OPTARG ;; esac
done
if [ -n "$prebuilt" ]; then
  echo "$(basename $PWD) prebuilt $prebuilt" >> $EVENTS
else
  echo "$(basename $PWD) build" >> $EVENTS
  sleep ${FAKE_BUILD:-0.3}
  mkdir -p output && printf '#!/bin/bash\\n' > output/mobile.out && chmod +x output/mobile.out
fi
echo '================= Running MoBILE ================='
sleep ${FAKE_SLEEP:-0}
mkdir -p output && touch output/output.nc
echo 'Program finished successfully'
"""

    def building(self, **environ):
        (self.config.mobile / "mobile.sh").write_text(self.BUILDING)
        events = self.config.runs_dir.parent / "events.txt"
        events.write_text("")
        patch = mock.patch.dict(os.environ, {"EVENTS": str(events), **environ})
        patch.start()
        self.addCleanup(patch.stop)
        return events

    def test_model_built_once(self):
        events = self.building(FAKE_SLEEP="0.3")
        folder = create_study(self.config, self.parameters, 2, False, [1], name="once", sample_seed=1)  # 8 runs
        started = time.time()
        record = run_study(folder, StudyState(), parallel=4)
        wall = time.time() - started
        self.assertEqual((record["status"], record["finished"]), ("finished", 8))
        lines = events.read_text().split()
        binary = folder / "bin" / "mobile.out"
        self.assertEqual(events.read_text().count(" build"), 1)
        self.assertEqual(events.read_text().count(f" prebuilt {binary}"), 7)
        self.assertEqual(record["binary_md5"], hashlib.md5(binary.read_bytes()).hexdigest())
        manifest = json.loads((folder / "runs" / run_name(1, 7) / "run.json").read_text())
        self.assertEqual((manifest["prebuilt"], manifest["binary_md5"]), (str(binary), record["binary_md5"]))
        # Side by side: 0.3 s to build, then 8 runs of 0.3 s, 4 at a time, take well under 8 × 0.6 s
        self.assertLess(wall, 3.5, lines)
        # Resumed, the runs left use the model of the analysis: nothing is built again
        for index in (2, 5):
            shutil.rmtree(folder / "runs" / run_name(1, index))
        events.write_text("")
        record = run_study(folder, StudyState(), parallel=2)
        self.assertEqual((record["status"], record["finished"]), ("finished", 8))
        self.assertEqual(sorted(events.read_text().split("\n"))[1:], [f"{run_name(1, i).split('/')[-1]} prebuilt {binary}" for i in (2, 5)])

    def test_cancelled_while_the_model_is_built(self):
        import threading

        events = self.building(FAKE_BUILD="2")
        folder = create_study(self.config, self.parameters, 2, False, [1], name="cancel", sample_seed=1)
        state = StudyState()
        outcome = {}
        worker = threading.Thread(target=lambda: outcome.update(record=run_study(folder, state, parallel=4)))
        worker.start()
        time.sleep(0.5)
        state.cancel()
        worker.join(10)
        self.assertFalse(worker.is_alive())
        self.assertEqual(outcome["record"]["status"], "cancelled")
        # Only the run that built started; those waiting for its model never did
        self.assertEqual(len(events.read_text().split("\n")) - 1, 1)

    def test_cancel_and_resume(self):
        import threading
        import time

        folder = create_study(self.config, self.parameters, 2, True, [1], sample_seed=1)  # 2 x (2·2 + 2) = 12 runs
        state = StudyState()
        outcome = {}
        with mock.patch.dict(os.environ, {"FAKE_SLEEP": "1"}):
            thread = threading.Thread(target=lambda: outcome.update(record=run_study(folder, state, parallel=2)))
            thread.start()
            time.sleep(2.5)
            state.cancel()
            thread.join(30)
        self.assertEqual(outcome["record"]["status"], "cancelled")
        done = outcome["record"]["finished"]
        self.assertTrue(0 < done < 12, done)
        finished = {index for index in range(12) if run_finished(folder / "runs" / run_name(1, index))}
        self.assertEqual(len(finished), done)
        # Resume: only the others run again, and leftovers of cancelled runs are replaced
        state = StudyState()
        record = run_study(folder, state, parallel=4)
        self.assertEqual((record["status"], record["finished"]), ("finished", 12))
        self.assertEqual(state.done_before, done)


AGE_LABELS = ["0-0", "1-1", "2-2", "3-3", "4-4", "5-5", "6-6", "7-7", "8-9", "10-11", "12-14", "15-19", "20-29", "30-44", "45-59",
              "60-79", "80+"]


def known_age_rate(k, x1, x2, day):
    """Rate per person of new cases in age band k of the known model: S1 of x1 is (k + 1)² / ((k + 1)² + (17 - k)²) in
    the band, and the rate doubles on odd days."""
    return ((k + 1) * x1 + (17 - k) * x2 + 0.1) * (1 + day % 2)


def known_agents(k, day):
    """Agents in age band k of the known model: under 5 years old, more on even days, against the rate; older, more on
    odd days, with it. The share of the cases under 5 then differs from that of the mean rate times the mean agents."""
    return (20 - k) * ((2 - day % 2) if k < 5 else (1 + day % 2))


def write_known_study(root, n, seeds=(1,), second_order=False, noise=0.0, days=40, shape=(4, 5), hole=(0, 0), swap_day=None,
                      ages=None):
    """A sensitivity analysis on disk whose outputs come from a model with known indices, not from MoBILE: x1, x2, x3
    uniform on [0, 1], and EIR = a·x1 + b·x2 + noise in every populated cell and day, with a = rain / 10 and b = temperature / 10
    of the cell, so that S1 = a² / (a² + b²) for x1, b² / (a² + b²) for x2, and 0 for x3. From day swap_day on, x1 and
    x2 swap their weights. With ages, new cases by age band too (group Inew, known_age_rate), and with ages="agents"
    the agents by age band (group Na, known_agents). Returns (folder, a, b)."""
    root = Path(root).resolve()
    lat, lon = np.linspace(-1, 1, shape[0]), np.linspace(30, 32, shape[1])
    pop = np.full(shape, 100.0)
    if hole is not None:
        pop[hole] = np.nan  # Not simulated
    with netCDF4.Dataset(root / "pop.nc", "w") as dataset:
        dataset.createDimension("lat", lat.size)
        dataset.createDimension("lon", lon.size)
        dataset.createVariable("lat", "f8", ("lat",))[:] = lat
        dataset.createVariable("lon", "f8", ("lon",))[:] = lon
        dataset.createVariable("pop", "f8", ("lat", "lon"), fill_value=np.nan)[:] = pop
    rain = np.linspace(1, 9, pop.size).reshape(shape)
    temperature = np.linspace(30, 10, pop.size).reshape(shape)
    a, b = rain / 10, temperature / 10
    parameters = [SampledParameter(f"x{k}", "uniform", 0.0, 1.0) for k in (1, 2, 3)]
    folder = root / "runs" / "sensitivity" / "known"
    folder.mkdir(parents=True)
    _, values = sample(parameters, n, second_order, seed=3)
    np.savetxt(folder / SAMPLES, values, header="x1 x2 x3")
    noise_of = np.random.default_rng(0)
    for seed in seeds:
        for index, (x1, x2, x3) in enumerate(values):
            run_dir = folder / "runs" / run_name(seed, index)
            (run_dir / "output").mkdir(parents=True)
            eir = a * x1 + b * x2 + noise * noise_of.standard_normal(shape)
            if hole is not None:
                eir[hole] = 1000 * x3  # Would make x3 matter, were the cell without population counted
            daily = np.broadcast_to(eir, (days, *shape)).copy()
            if swap_day is not None:
                daily[swap_day:] = b * x1 + a * x2
                if hole is not None:
                    daily[swap_day:, hole[0], hole[1]] = 1000 * x3
            with netCDF4.Dataset(run_dir / "output" / "output.nc", "w") as dataset:
                for name, size in (("time", days), ("lat", lat.size), ("lon", lon.size)):
                    dataset.createDimension(name, size)
                time = dataset.createVariable("time", "f8", ("time",))
                time.units, time.calendar = "days since 2012-01-01", "standard"
                time[:] = np.arange(days)
                dataset.createVariable("lat", "f8", ("lat",))[:] = lat
                dataset.createVariable("lon", "f8", ("lon",))[:] = lon
                for group, name, field in (("Human", "EIR", daily), ("Climate", "rain", rain), ("Climate", "t2m", temperature)):
                    variable = dataset.createGroup(group).createVariable(name, "f4", ("time", "lat", "lon"))
                    variable.units = "day^-1"
                    variable[:] = np.broadcast_to(field, (days, *shape))
                by_age = []
                if ages:
                    by_age += [("Inew", f"Ia_new_{label}", "Age-disaggregated NEW symptomatic population per person", "fraction",
                                lambda k, day: known_age_rate(k, x1, x2, day)) for k, label in enumerate(AGE_LABELS)]
                    by_age.append(("Inew", "Inew_bulk", "NEW symptomatic population per person", "fraction", lambda k, day: 0.0))
                if ages == "agents":
                    by_age += [("Na", f"N_a_{label}", "Number of agents", "[agents]", lambda k, day: known_agents(k, day))
                               for k, label in enumerate(AGE_LABELS)]
                for k, (group, name, long_name, units, value) in enumerate(by_age):
                    k = AGE_LABELS.index(name.rsplit("_", 1)[1]) if not name.endswith("bulk") else 0
                    group = dataset[group] if group in dataset.groups else dataset.createGroup(group)
                    variable = group.createVariable(name, "f4", ("time", "lat", "lon"))
                    variable.units, variable.long_name = units, long_name
                    variable[:] = np.array([np.full(shape, value(k, day)) for day in range(days)])
            (run_dir / "run.json").write_text(json.dumps({"status": "finished", "returncode": 0, "wall_seconds": 1, "spinup_years": 0}))
    record = {
        "status": "finished", "date": "2026-11-04T12:00:00", "method": "sobol", "n": n, "second_order": second_order,
        "parameters": [{"name": p.name, "distribution": "uniform", "low": 0.0, "high": 1.0, "mean": None, "sd": None} for p in parameters],
        "seeds": list(seeds), "sample_seed": 3, "runs": run_count(n, parameters, second_order, len(seeds)), "region": None,
        "inputs": {"pop_file": str(root / "pop.nc")},
    }
    (folder / RECORD).write_text(json.dumps(record))
    return folder, a, b


class TestStudyResults(unittest.TestCase):
    """The analysis of the outputs of an analysis, on outputs of a model with known indices."""

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.populated = np.ones((4, 5), bool)
        self.populated[0, 0] = False

    def test_number_per_run(self):
        folder, a, b = write_known_study(self.root, 256, seeds=(1, 2), second_order=True, noise=0.3)
        record = read_study(folder)
        progress = StudyState()
        result = analyse_study(folder, record, Metric("EIR", "mean", "mean"), progress)
        mean_a, mean_b = a[self.populated].mean(), b[self.populated].mean()
        expected = [mean_a**2 / (mean_a**2 + mean_b**2), mean_b**2 / (mean_a**2 + mean_b**2), 0.0]
        np.testing.assert_allclose(result["mean"]["S1"], expected, atol=0.05)
        np.testing.assert_allclose(result["mean"]["ST"], expected, atol=0.05)
        self.assertEqual(result["each"]["S1"].shape, (2, 3))
        # The noise of the mean over 19 cells against the variance from the parameters, uniform on [0, 1]
        noise = 0.3**2 / self.populated.sum()
        self.assertAlmostEqual(result["chance"], noise / ((mean_a**2 + mean_b**2) / 12 + noise), delta=0.004)
        self.assertEqual(progress.snapshot()[:2], (2 * 256 * 8, 2 * 256 * 8))
        self.assertIn("mean over the 19 populated cells", result["description"])
        table = indices_table(result)
        self.assertEqual(list(table["parameter"]), ["x1", "x2", "x3"])
        self.assertIn("S2_with_x2", table)
        self.assertIn("ST_seed_2", table)
        for figure in (indices_figure(result), second_order_figure(result)):
            figure.to_json()
        # Read once: the second time, from metrics/
        again = StudyState()
        analyse_study(folder, record, Metric("EIR", "mean", "mean"), again)
        self.assertEqual(again.done_before, again.total)

    def test_map_per_parameter(self):
        folder, a, b = write_known_study(self.root, 128, seeds=(1,), second_order=False)
        metric = Metric("EIR", "sum", "none", start="2012-01-03", end="2012-01-20", months=(1,))
        result = analyse_study(folder, read_study(folder), metric)
        self.assertEqual(result["cells"].size, 19)  # Not the cell without population
        expected = (a**2 / (a**2 + b**2))[self.populated]
        np.testing.assert_allclose(result["mean"]["S1"][0], expected, atol=0.06)
        np.testing.assert_allclose(result["climate"]["rain"][2], (np.linspace(1, 9, 20).reshape(4, 5))[self.populated], rtol=1e-5)
        label, _, density = result["climate"]["pop"]  # From the population file of the analysis: 100 in every cell
        self.assertEqual(label, "Population density")
        np.testing.assert_array_equal(density, np.full(19, 100.0))
        self.assertNotIn("chance", result)
        maps = cell_dataset(result)
        self.assertEqual(maps["ST"].shape, (3, 4, 5))
        self.assertTrue(np.isnan(maps["ST"].values[:, 0, 0]).all())
        for figure in (index_map_figure(result, "x2", "ST"), climate_figure(result, "x2", "S1")):
            figure.to_json()
        self.assertEqual(climate_figure(result, "x2", "S1").layout.xaxis3.type, "log")  # Population density

    def test_age_bands(self):
        folder, _, _ = write_known_study(self.root, 128, days=4, ages="agents")
        record = read_study(folder)
        info = output_info(first_run(folder, record))
        choices = analysable_variables(info["variables"])
        self.assertIn("age:Inew", choices["By age band"])
        self.assertIn("Inew_bulk", choices["By age band"])
        self.assertEqual(set(choices["Age profile"]), {"under5:Inew", "meanage:Inew"})
        self.assertFalse(any(name.startswith("Ia_new_") for group in choices.values() for name in group))
        self.assertIsNone(age_note(info["variables"]))
        metric = metric_from_entry("age:Inew", "mean", "mean", None, None, None, False)
        self.assertEqual((metric.variable, metric.space, metric.age), ("Inew", "none", "bands"))
        result = analyse_study(folder, record, metric)
        self.assertEqual(result["kind"], "ages")
        self.assertEqual(list(result["ages"]), ["0", "1", "2", "3", "4", "5", "6", "7", "8–9", "10–11", "12–14", "15–19", "20–29",
                                                "30–44", "45–59", "60–79", "80+"])
        k = np.arange(17)
        expected = (k + 1) ** 2 / ((k + 1) ** 2 + (17 - k) ** 2)  # S1 of x1 in each band; x2 the rest
        np.testing.assert_allclose(result["line"]["S1"][:, 0], expected, atol=0.05)
        np.testing.assert_allclose(result["line"]["S1"][:, 1], 1 - expected, atol=0.05)
        np.testing.assert_allclose(result["spread"]["S1"][:, 0, 2], expected, atol=0.05)  # Every cell alike
        self.assertIn("in each age band", result["description"])
        table = monthly_table(result)
        self.assertEqual(table["age_band"].iloc[0], "0")
        self.assertEqual(len(table), 17 * 3 * 2)
        monthly_figure(result, "x1", "S1").to_json()

    def test_age_profile(self):
        # The cases of a band are rate × agents day by day: the share under 5 and the mean age of the known model,
        # computed here from the formulas, for every run
        folder, _, _ = write_known_study(self.root, 8, days=10, ages="agents")
        record = read_study(folder)
        info = output_info(first_run(folder, record))
        values = np.loadtxt(folder / SAMPLES, ndmin=2)
        middles = np.array([0.5, 1.5, 2.5, 3.5, 4.5, 5.5, 6.5, 7.5, 9, 11, 13.5, 17.5, 25, 37.5, 52.5, 70, 85])
        mask = analysis_mask(record, info)
        for entry, of_cases in (("under5:Inew", lambda cases: cases[:5].sum() / cases.sum()),
                                ("meanage:Inew", lambda cases: (cases * middles).sum() / cases.sum())):
            metric = metric_from_entry(entry, "sum", "mean", None, None, None, False)
            got, _, _ = extract(folder, record, metric, [1], info, mask)
            expected = [of_cases(np.array([sum(known_age_rate(k, x1, x2, day) * known_agents(k, day) for day in range(10))
                                           for k in range(17)])) for x1, x2, _ in values]
            np.testing.assert_allclose(got[1], expected, rtol=1e-5)
        self.assertEqual(analyse_study(folder, record, metric_from_entry("under5:Inew", "sum", "none", None, None, None, False))["kind"], "cells")

    def test_age_outputs_missing(self):
        folder, _, _ = write_known_study(self.root, 8, ages="rates")  # No agents by age
        info = output_info(first_run(folder, read_study(folder)))
        self.assertNotIn("Age profile", analysable_variables(info["variables"]))
        self.assertIn("Agents under Human, by age", age_note(info["variables"]))
        with self.assertRaisesRegex(ValueError, "agents by age band"):
            analyse_study(folder, read_study(folder), metric_from_entry("under5:Inew", "sum", "mean", None, None, None, False))
        (self.root / "plain").mkdir()
        folder, _, _ = write_known_study(self.root / "plain", 8)
        self.assertIn("tick an output under Human, by age", age_note(output_info(first_run(folder, read_study(folder)))["variables"]))
        self.assertIn("age band", Metric("Inew", "mean", "mean", age="bands").problems()[0])

    def test_map_single_cell(self):
        # A point simulation has no map: the reason, not a crash of the basemap, and month by month still works
        folder, _, _ = write_known_study(self.root, 64, days=4, shape=(1, 1), hole=None)
        with self.assertRaisesRegex(ValueError, "single grid cell"):
            analyse_study(folder, read_study(folder), Metric("EIR", "sum", "none"))
        result = analyse_study(folder, read_study(folder), Metric("EIR", "sum", "none", by_month=True))
        self.assertEqual(result["cells_used"].tolist(), [1])
        np.testing.assert_allclose(result["line"]["ST"][0], [0.01 / 9.01, 9 / 9.01, 0], atol=0.03)  # Only cell: a = 0.1, b = 3

    def test_map_stripe(self):
        # A stripe one cell wide is still a map: each direction one cell of the grid's size, not one degree or none
        for shape, (lat_range, lon_range) in (((1, 5), ([-1.25, -0.75], [30, 32])), ((4, 1), ([-1, 1], [30 - 1 / 3, 30 + 1 / 3]))):
            root = self.root / f"stripe{shape[0]}x{shape[1]}"
            root.mkdir()
            folder, _, _ = write_known_study(root, 8, days=4, shape=shape, hole=None)
            result = analyse_study(folder, read_study(folder), Metric("EIR", "sum", "none"))
            self.assertEqual(len(result["cells"]), shape[0] * shape[1])
            figure = index_map_figure(result, "x2", "ST")
            np.testing.assert_allclose(figure.layout.yaxis.range, lat_range)
            np.testing.assert_allclose(figure.layout.xaxis.range, lon_range)
            heatmap = figure.data[0]
            self.assertEqual((heatmap.dy, heatmap.dx), (0.5, None) if shape[0] == 1 else (None, 2 / 3))
        self.assertEqual(cell_size([0.0], [30.0, 30.5]), (0.5, 0.5))
        self.assertEqual(cell_size([0.0, 0.25], [30.0]), (0.25, 0.25))

    def test_month_by_month(self):
        # x1 and x2 swap their weights on 1 February: the indices of January and February swap too
        folder, a, b = write_known_study(self.root, 128, seeds=(1, 2), days=75, swap_day=31)
        metric = Metric("EIR", "sum", "none", months=(1, 2), by_month=True)
        result = analyse_study(folder, read_study(folder), metric)
        self.assertEqual([str(month) for month in result["months"]], ["2012-01-01", "2012-02-01"])
        self.assertEqual(list(result["cells_used"]), [19, 19])
        january = (a**2 / (a**2 + b**2))[self.populated]
        expected = np.percentile(january, PERCENTILES)
        np.testing.assert_allclose(result["spread"]["S1"][0, 0], expected, atol=0.03)  # x1 in January
        np.testing.assert_allclose(result["spread"]["S1"][1, 1], expected, atol=0.03)  # x2 in February
        mean_a, mean_b = a[self.populated].mean(), b[self.populated].mean()
        line = mean_a**2 / (mean_a**2 + mean_b**2)
        np.testing.assert_allclose(result["line"]["S1"][:, 0], [line, 1 - line], atol=0.03)
        self.assertEqual(result["each"]["S1"].shape, (2, 2, 3))
        table = monthly_table(result)
        self.assertEqual(len(table), 2 * 3 * 2)
        self.assertIn("of_spatial_mean_seed_2", table)
        monthly_figure(result, "x2", "ST").to_json()
        # Cancelled while reading: no half-written file is kept
        progress = StudyState()
        progress.cancel()
        with self.assertRaises(InterruptedError):
            analyse_study(folder, read_study(folder), Metric("EIR", "max", "none", by_month=True), progress)
        self.assertFalse(list((folder / "metrics").glob("*/*.tmp.npy")))
        self.assertTrue(Metric("EIR", "sum", "mean", by_month=True).problems())

    def test_only_seeds_with_every_run(self):
        folder, _, _ = write_known_study(self.root, 4, seeds=(5, 6))
        (folder / "runs" / run_name(6, 3) / "run.json").unlink()
        record = read_study(folder)
        self.assertEqual(complete_seeds(folder, record), [5])
        self.assertEqual(analyse_study(folder, record, Metric("EIR", "max", "sum"))["seeds"], [5])

    def test_nothing_to_analyse(self):
        folder, _, _ = write_known_study(self.root, 4)
        record = read_study(folder)
        with self.assertRaisesRegex(ValueError, "No day"):
            analyse_study(folder, record, Metric("EIR", "mean", "mean", months=(7,)))
        with self.assertRaisesRegex(ValueError, "not in the outputs"):
            analyse_study(folder, record, Metric("V", "mean", "mean"))

    def test_cancel_while_reading(self):
        folder, _, _ = write_known_study(self.root, 4)
        progress = StudyState()
        progress.cancel()
        with self.assertRaises(InterruptedError):
            analyse_study(folder, read_study(folder), Metric("EIR", "mean", "mean"), progress)
        self.assertFalse(list((folder / "metrics").glob("*/seed_*.npy")))  # Nothing half read is kept

    def test_chance_share_and_names(self):
        Y = np.array([[1.0, 2.0, 3.0], [1.0, 2.0, 3.0]])
        self.assertEqual(float(chance_share(Y)), 0.0)  # The same for every seed
        self.assertEqual(metric_key(Metric("EIR")), metric_key(Metric("EIR")))
        self.assertNotEqual(metric_key(Metric("EIR")), metric_key(Metric("EIR", months=(1,))))
        self.assertEqual(describe_metric(Metric("EIR", "max", "sum", start="2012-03-01", months=(3, 4)), 10),
                         "EIR, maximum over the days from 2012-03-01 to the last day in Mar, Apr, sum over the 10 populated cells")


class TestRegion(unittest.TestCase):
    """A part of the grid to simulate, on the example: Senegal on a 0.05 degree grid."""

    def setUp(self):
        folder = tempfile.TemporaryDirectory(dir=os.path.expanduser("~"))
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(self.folder)
        self.config = Config.load(CONFIG)
        self.box = {"north": 14.6, "west": -17.2, "south": 14.0, "east": -16.4}

    def test_cells_of_an_axis(self):
        coords = [0.0, 1.0, 2.0, 3.0]
        self.assertEqual(axis_range(coords, 0.5, 2.5), (1, 3))
        # A point, or a range narrower than a cell, gives the nearest cell
        self.assertEqual(axis_range(coords, 1.2, 1.2), (1, 2))
        self.assertEqual(axis_range(coords, 3.4, 3.4), (3, 4))
        self.assertIsNone(axis_range(coords, 5.0, 6.0))

    def test_problems(self):
        self.assertEqual(region_problems(None), [])
        self.assertEqual(region_problems(self.box), [])
        self.assertTrue(region_problems({**self.box, "south": 15.0}))
        self.assertTrue(region_problems({**self.box, "east": None}))
        self.assertTrue(region_problems({"north": 1}))
        with self.assertRaises(ConfigError):
            replace(self.config, region={**self.box, "west": -10.0}).validate()

    def test_fields(self):
        self.assertIsNone(region_from_fields("all", 1, 2, 3, 4, 5, 6))
        point = region_from_fields("point", None, None, None, None, 14.7, -17.4)
        self.assertEqual(point, {"north": 14.7, "west": -17.4, "south": 14.7, "east": -17.4})
        self.assertEqual([region_mode(region) for region in (None, self.box, point)], ["all", "box", "point"])

    def test_grid_of_a_region(self):
        inputs = self.config.inputs
        climate = (inputs["rain_file"], inputs["temp_file"])
        whole = read_grid(inputs["pop_file"], None, *climate)
        part = read_grid(inputs["pop_file"], self.box, *climate)
        self.assertEqual(part["mask"].shape, (12, 16))
        self.assertTrue(0 < part["people"] < whole["people"])
        point = read_grid(inputs["pop_file"], {"north": 14.69, "west": -17.44, "south": 14.69, "east": -17.44}, *climate)
        self.assertEqual(point["mask"].shape, (1, 1))
        self.assertIsNone(read_grid(inputs["pop_file"], {"north": 5.0, "west": 0.0, "south": 4.0, "east": 1.0}, *climate))
        # Without the climate files, the populated cells only (for the masks of the maps)
        self.assertNotIn("people", read_grid(inputs["pop_file"], self.box))

    def test_people_as_the_model_counts_them(self):
        # The model (main, PR #76) printed "Number of people in simulated region 13943334.0" on the example,
        # summed in single precision, and placed agents in 6472 cells
        inputs = self.config.inputs
        grid = read_grid(inputs["pop_file"], None, inputs["rain_file"], inputs["temp_file"])
        self.assertLess(abs(grid["people"] / 13943334.0 - 1), 1e-6)
        self.assertEqual(grid["simulated"], 6472)
        # Control: the populated cells without rain or temperature data hold people that would be counted otherwise
        # (15426841 printed by the model before, a single-precision sum with the areas of cdo: within 1e-5)
        self.assertEqual(grid["populated"], 6502)
        with netCDF4.Dataset(inputs["pop_file"]) as data:
            pop = np.ma.filled(data["pop"][:].astype("f8"), np.nan)
        everyone = float(np.nansum(pop * cell_areas(inputs["pop_file"])))
        self.assertLess(abs(everyone / 15426841.0 - 1), 1e-5)
        self.assertGreater(everyone / grid["people"], 1.1)

    def test_cell_areas_as_cdo(self):
        # cdo gridarea pop.nc, the area.nc of the example before the model computed it (git 5f04270)
        areas = cell_areas(self.config.inputs["pop_file"])
        cdo = {(0, 0): 30233882.400677443, (-1, -1): 29558652.66170948, (54, 10): 29896944.170571003}
        for cell, value in cdo.items():
            self.assertLess(abs(areas[cell] / value - 1), 1e-7, cell)
        self.assertLess(abs(areas.sum() / 418833.56920419214e6 - 1), 1e-7)
        # Control: the mean radius of the Earth in src/mo_const.f90 (6371.009 km) is off by 2.8e-6
        with mock.patch("mobile.cells.EARTH_RADIUS", 6371009.0):
            self.assertGreater(abs(cell_areas(self.config.inputs["pop_file"])[54, 10] / cdo[54, 10] - 1), 1e-6)
        self.assertEqual(EARTH_RADIUS, 6371000.0)

    def test_a_cut_keeps_the_cell_size(self):
        inputs = self.config.inputs
        whole = cell_areas(inputs["pop_file"])
        lon, lat = (np.asarray(axis, dtype="float64") for axis in pop_coordinates(inputs["pop_file"]))
        point = {"north": float(lat[54]), "west": float(lon[10]), "south": float(lat[54]), "east": float(lon[10])}
        row = {**point, "west": float(lon[0]), "east": float(lon[-1])}
        column = {**point, "south": float(lat.min()), "north": float(lat.max())}
        for name, region, cells in (("point", point, (54, 10)), ("row", row, (54, slice(None))),
                                    ("column", column, (slice(None), 10))):
            paths = cut_inputs(inputs, region, self.folder / name, (lon, lat))
            with netCDF4.Dataset(paths["pop_file"]) as cut:
                self.assertEqual((cut["latitude"].bounds, cut["longitude"].bounds), ("lat_bnds", "lon_bnds"), name)
            self.assertTrue(np.allclose(cell_areas(paths["pop_file"]).ravel(), np.ravel(whole[cells]), rtol=1e-12), name)
        # Control: a cut of one cell without the bounds gives no cell size
        cut_file(inputs["pop_file"], self.folder / "bare.nc", *((float(c), float(c)) for c in (lon[10], lat[54])))
        with self.assertRaisesRegex(CellSizeError, "single latitude"):
            cell_areas(self.folder / "bare.nc")

    def test_files_cut_to_a_region(self):
        import netCDF4
        import numpy as np
        import xarray as xr

        paths = cut_inputs(self.config.inputs, self.box, self.folder / "inputs", pop_coordinates(self.config.inputs["pop_file"]))
        self.assertEqual(set(paths), {"rain_file", "temp_file", "pop_file"})
        for key, path in paths.items():
            with xr.open_dataset(self.config.inputs[key]) as whole, xr.open_dataset(path) as part:
                name = next(iter(whole.data_vars))
                self.assertEqual((part.sizes["longitude"], part.sizes["latitude"]), (16, 12))
                same = whole[name].sel(latitude=part["latitude"], longitude=part["longitude"], method="nearest")
                self.assertTrue(np.array_equal(same.values, part[name].values, equal_nan=True), key)
                self.assertEqual(whole[name].attrs, part[name].attrs)
            with netCDF4.Dataset(self.config.inputs[key]) as whole, netCDF4.Dataset(path) as part:
                self.assertEqual(whole.data_model, part.data_model)
                self.assertEqual(getattr(whole.variables[name], "_FillValue", None), getattr(part.variables[name], "_FillValue", None))
        with netCDF4.Dataset(paths["rain_file"]) as rain:
            self.assertTrue(rain.dimensions["time"].isunlimited())
            self.assertEqual(len(rain.dimensions["time"]), 1096)

    def test_files_cut_to_a_period(self):
        import numpy as np
        import xarray as xr

        paths = cut_inputs(self.config.inputs, None, self.folder / "inputs", pop_coordinates(self.config.inputs["pop_file"]), (366, 730))
        self.assertEqual(set(paths), {"rain_file", "temp_file"})
        with xr.open_dataset(self.config.inputs["rain_file"]) as whole, xr.open_dataset(paths["rain_file"]) as part:
            self.assertEqual((part.sizes["time"], part.sizes["latitude"]), (365, whole.sizes["latitude"]))
            self.assertEqual((str(part.time.values[0])[:10], str(part.time.values[-1])[:10]), ("2013-01-01", "2013-12-31"))
            self.assertTrue(np.array_equal(part.precip.values[0], whole.precip.values[366], equal_nan=True))
        with self.assertRaises(ValueError):
            cut_inputs(self.config.inputs, None, self.folder / "more", pop_coordinates(self.config.inputs["pop_file"]), (366, 2000))

    def test_run_dir_of_a_period(self):
        config = replace(self.config, runs_dir=self.folder, period={"start": "2013-01-01", "end": "2013-12-31"})
        run_dir = create_run_dir(config, "x")
        script = (run_dir / "run_MOBILE.sh").read_text()
        self.assertRegex(script, rf"(?m)^\s*rain_file='{re.escape(str(run_dir / 'inputs' / 'rain_file.nc'))}'$")
        self.assertRegex(script, rf"(?m)^\s*pop_file='{re.escape(self.config.inputs['pop_file'])}'$")
        self.assertRegex(script, r"(?m)^\s*nstep=365$")
        # All the days of the data need no copy
        whole = replace(self.config, runs_dir=self.folder, period={"start": "2012-01-01", "end": "2014-12-31"})
        script = (create_run_dir(whole, "y") / "run_MOBILE.sh").read_text()
        self.assertRegex(script, rf"(?m)^\s*rain_file='{re.escape(self.config.inputs['rain_file'])}'$")
        self.assertRegex(script, r"(?m)^\s*nstep=1096$")
        outside = replace(self.config, runs_dir=self.folder, period={"start": "2010-01-01", "end": "2013-12-31"})
        with self.assertRaises(ConfigError):
            create_run_dir(outside, "z")

    def test_run_dir_of_a_region(self):
        config = replace(self.config, runs_dir=self.folder, region=self.box)
        run_dir = create_run_dir(config, "x")
        script = (run_dir / "run_MOBILE.sh").read_text()
        self.assertRegex(script, rf"(?m)^\s*pop_file='{re.escape(str(run_dir / 'inputs' / 'pop_file.nc'))}'$")
        self.assertRegex(script, rf"(?m)^\s*rain_file='{re.escape(str(run_dir / 'inputs' / 'rain_file.nc'))}'$")
        # Text files are used as they are
        self.assertRegex(script, r"(?m)^\s*mortality_file='NONE'$")

    def test_kept_with_the_setup_and_the_run(self):
        settings = mock.patch.dict(os.environ, {"MOBILE_CONFIG_DIR": str(self.folder / "settings")})
        settings.start()
        self.addCleanup(settings.stop)
        files = dict(self.config.inputs)
        config = from_fields(MOBILE, "Study", "runs", dict(self.config.run), files, self.box, age_structure=self.config.age_structure)
        save_setup(config)
        self.assertEqual(load_setup(MOBILE).region, self.box)
        manifest = {"run": dict(config.run), "inputs": files, "region": self.box, "age_structure": config.age_structure}
        self.assertEqual(from_manifest(manifest, replace(config, region=None)).region, self.box)
        # Runs from before regions and periods have none
        old = {"run": dict(config.run), "inputs": files, "age_structure": config.age_structure}
        self.assertIsNone(from_manifest(old, config).period)
        self.assertIsNone(from_manifest(old, config).region)
        written = self.folder / "with_region.yaml"
        written.write_text(CONFIG.read_text().replace("$MOBILE", MOBILE).replace("runs_dir: runs", "runs_dir: runs\nregion: {north: 14.6, west: -17.2, south: 14.0, east: -16.4}"))
        self.assertEqual(Config.load(written).region, self.box)



def write_raster(path, values, nodata=-99999.0):
    """A single-band float GeoTIFF as WorldPop's, with its no-data value."""
    from PIL import Image, TiffImagePlugin

    tags = TiffImagePlugin.ImageFileDirectory_v2()
    tags[42113] = str(int(nodata))
    Image.fromarray(np.where(np.isnan(values), nodata, values).astype("float32")).save(path, tiffinfo=tags, compression="tiff_lzw")


def exponential_rasters(gamma, shape=(4, 5), hole=(0, 0)):
    """{(sex, group): people per cell} with the same structure in every cell, that of a population whose density
    by age decays as exp(-gamma age): the people of a group are its integral, those of 80 and over to infinity."""
    from mobile.worldpop import AGE_GROUPS, SEXES

    starts = np.array(AGE_GROUPS, dtype="float64")
    ends = np.append(starts[1:], np.inf)
    shares = np.exp(-gamma * starts) - np.exp(-gamma * ends)
    people = np.linspace(100, 1000, np.prod(shape)).reshape(shape)
    people[hole] = np.nan  # A cell with no data
    return {(sex, age): people * share * (1.0 if sex == "f" else 0.97) for sex in SEXES for age, share in zip(AGE_GROUPS, shares)}, shares


class TestWorldPop(unittest.TestCase):
    """The age structure from WorldPop: the analysis of utils/fetch_age.sh, the files, the choice and the runs."""

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(self.folder)
        patch = mock.patch.dict(os.environ, {"MOBILE_CONFIG_DIR": str(self.folder / "settings")})
        patch.start()
        self.addCleanup(patch.stop)

    def test_packaged_example_as_fetch_age(self):
        from mobile.worldpop import age_file_text, cached_summary, fitted_mortality

        # tests/data/fetch_age_SEN_2015.txt: the cumm_age.txt of the Python of utils/fetch_age.sh, run unchanged on
        # the NetCDF files it made of WorldPop R2025A, Senegal 2015; it printed "Fitted mortality = 0.0337 / year"
        summary = cached_summary("R2025A", "SEN", 2015)
        reference = (Path(__file__).parent / "data" / "fetch_age_SEN_2015.txt").read_text().split()
        self.assertEqual(age_file_text(summary).split(), reference)
        self.assertEqual(f"{fitted_mortality(summary):.4f}", "0.0337")

    def test_analysis_of_a_known_structure(self):
        from mobile.worldpop import analyse

        rasters, shares = exponential_rasters(0.03)
        summary = analyse(rasters)
        # The same structure in every cell: the mean shares are the shares, every cell in one bin of the histogram
        for sex in ("f", "m"):
            self.assertTrue(np.allclose(summary["mean_share"][sex], shares, rtol=1e-12))
            self.assertTrue(all(sum(1 for count in counts if count) == 1 for counts in summary["histogram"][sex]))
        self.assertEqual(summary["cells"], 19)  # 20 cells, one with no data
        # The weights go through the cumulative shares at the end of each group, 80 and over left out, and never fall
        weights = np.array(summary["weights"])
        self.assertTrue(np.allclose(weights[summary["group_ends"]], np.cumsum(shares[:-1]), rtol=1e-12))
        self.assertTrue(np.all(np.diff(weights) > 0))
        self.assertLess(abs(weights[-1] - (1 - shares[-1])), 1e-12)
        # The fit gives back the decay rate (the interpolation between group ends costs a little)
        self.assertLess(abs(summary["fit"]["gamma"] / 0.03 - 1), 0.02)
        # Control: another decay rate is told apart
        self.assertGreater(abs(analyse(exponential_rasters(0.04)[0])["fit"]["gamma"] / 0.03 - 1), 0.2)

    def test_rasters_are_read_with_their_no_data(self):
        from mobile.worldpop import read_raster

        values = np.array([[1.5, np.nan], [2.0, 3.25]])
        write_raster(self.folder / "a.tif", values)
        read = read_raster(self.folder / "a.tif")
        self.assertTrue(np.array_equal(read, values, equal_nan=True))

    def test_downloaded_once_then_kept(self):
        import mobile.worldpop as worldpop

        rasters, _ = exponential_rasters(0.03)
        source = self.folder / "server"
        source.mkdir()
        for (sex, age), values in rasters.items():
            write_raster(source / f"{sex}_{age:02d}.tif", values)
        product = {"label": "Test", "years": (2015, 2030), "source": "", "url": f"file://{source}/{{sex}}_{{age}}.tif",
                   "age_code": "{:02d}", "without": ()}
        with mock.patch.dict(worldpop.PRODUCTS, {"TEST": product}):
            calls = []
            summary = worldpop.prepare("TEST", "SEN", 2020, progress=lambda done, total: calls.append((done, total)))
            self.assertEqual(calls[-1], (36, 36))
            self.assertTrue(np.allclose(summary["weights"], worldpop.analyse(rasters)["weights"], rtol=1e-6))
            self.assertTrue((self.folder / "settings" / "worldpop" / "TEST" / "SEN_2020.json").is_file())
            # Kept: not downloaded again, even with the source gone
            shutil.rmtree(source)
            self.assertEqual(worldpop.prepare("TEST", "SEN", 2020)["weights"], summary["weights"])
            # Cancelled, or a missing raster: an error, and nothing kept
            with self.assertRaisesRegex(worldpop.WorldPopError, "cancelled"):
                worldpop.prepare("TEST", "SEN", 2021, cancelled=lambda: True)
            with self.assertRaisesRegex(worldpop.WorldPopError, "cannot download"):
                worldpop.prepare("TEST", "SEN", 2022)
            self.assertFalse((self.folder / "settings" / "worldpop" / "TEST" / "SEN_2022.json").exists())

    def test_choice(self):
        from mobile.worldpop import COUNTRIES, choice_problems, default_product, default_year, product_countries, raster_urls, resolve_choice

        self.assertEqual([default_year(year) for year in (2008, 2015, 2021, 2035)], [2015, 2015, 2021, 2030])
        # The product from the start of the period: 2000-2020 before 2015, R2025A from 2015
        self.assertEqual([default_product(year) for year in (1995, 2008, 2014, 2015, 2040)],
                         ["Global2000_2020", "Global2000_2020", "Global2000_2020", "R2025A", "R2025A"])
        self.assertEqual(resolve_choice({"country": "KEN"}, 2008), {"product": "Global2000_2020", "country": "KEN", "year": 2008})
        self.assertEqual(resolve_choice({"country": "KEN"}, 1995)["year"], 2000)
        self.assertEqual(resolve_choice({"product": "R2025A", "country": "KEN"}, 2008)["year"], 2015)
        # Age codes as WorldPop writes them: zero-padded in R2025A only
        self.assertTrue(raster_urls("R2025A", "SEN", 2020)[("f", 5)].endswith("/sen_f_05_2020_CN_1km_R2025A_UA_v1.tif"))
        self.assertTrue(raster_urls("Global2000_2020", "SEN", 2012)[("m", 5)].endswith("/2012/SEN/sen_m_5_2012_1km.tif"))
        from mobile.setup_ui import year_choices
        from mobile.worldpop import year_label

        self.assertEqual([year_label(year) for year in (2024, 2025, 2030)], ["2024", "2025 (projection)", "2030 (projection)"])
        menu = year_choices("R2025A")
        self.assertEqual((list(menu["Estimates"])[0], list(menu["Estimates"])[-1]), ("2015", "2024"))
        self.assertEqual(list(menu["Projections"].values()), [f"{year} (projection)" for year in range(2025, 2031)])
        self.assertEqual(len(COUNTRIES), 48)  # Sub-Saharan Africa
        # Eritrea not in R2025A (rasters of about 430 MB a year), but in 2000-2020 (0.7 MB a raster)
        self.assertNotIn("ERI", product_countries("R2025A"))
        self.assertIn("ERI", product_countries("Global2000_2020"))
        self.assertTrue(choice_problems({"product": "R2025A", "country": "ERI"}))
        self.assertEqual(choice_problems({"product": "Global2000_2020", "country": "ERI", "year": 2005}), [])
        self.assertEqual(choice_problems({"country": "ERI"}), [])
        self.assertTrue(choice_problems({"country": "SEN", "year": 2010}))  # A year needs a product
        self.assertEqual(choice_problems({"product": "R2025A", "country": "SEN"}), [])
        self.assertEqual(choice_problems({"product": "R2025A", "country": "KEN", "year": 2030}), [])
        for wrong in ({"product": "R2025A", "country": "FRA"}, {"product": "X", "country": "SEN"},
                      {"product": "R2025A", "country": "SEN", "year": 2031}, {"product": "R2025A"},
                      {"product": "Global2000_2020", "country": "SEN", "year": 2021}):
            self.assertTrue(choice_problems(wrong), wrong)

    def test_config_and_run_folder(self):
        from mobile.worldpop import age_file_text, cached_summary

        config = replace(Config.load(CONFIG), runs_dir=self.folder / "runs")
        # Rain from 2012: the 2000-2020 product, 2012, whose result comes with the package
        self.assertEqual(config.age_choice(), {"product": "Global2000_2020", "country": "SEN", "year": 2012})
        self.assertEqual(replace(config, period={"start": "2014-01-01", "end": "2014-12-31"}).age_choice()["year"], 2014)
        chosen = replace(config, age_structure={"product": "R2025A", "country": "SEN"})
        self.assertEqual(chosen.age_choice(), {"product": "R2025A", "country": "SEN", "year": 2015})
        self.assertEqual(replace(config, age_structure={"product": "R2025A", "country": "SEN", "year": 2020}).age_choice()["year"], 2020)
        run_dir = create_run_dir(config, name="age")
        written = (run_dir / "age_structure" / "cumm_age.txt").read_text()
        self.assertEqual(written, age_file_text(cached_summary("Global2000_2020", "SEN", 2012)))
        with self.assertRaisesRegex(ConfigError, "age_file is no longer used"):
            replace(config, inputs={**config.inputs, "age_file": str(CONFIG)}).validate()
        with self.assertRaisesRegex(ConfigError, "age_structure: missing"):
            replace(config, age_structure=None).validate()
        with self.assertRaisesRegex(ConfigError, "no country"):
            replace(config, age_structure={"product": "R2025A", "country": "FRA"}).validate()

    def test_figures(self):
        from mobile.plots import age_cumulative_figure, age_fit_figure, age_heterogeneity_figure, age_sex_figure
        from mobile.worldpop import cached_summary

        summary = cached_summary("R2025A", "SEN", 2015)
        for draw in (age_cumulative_figure, age_fit_figure, age_heterogeneity_figure, age_sex_figure):
            figure = draw(summary, "Senegal 2015")
            self.assertTrue(figure.data, draw.__name__)
        fit = age_fit_figure(summary, "Senegal 2015")
        self.assertIn("γ = 0.0337", fit.data[1].name)
        self.assertNotIn("61", " ".join(trace.name or "" for trace in fit.data))  # No literature reference
        self.assertEqual(len(age_heterogeneity_figure(summary, "").data), 36)


class TestDrivingFilesHelp(unittest.TestCase):
    """The table of the driving files in the Setup tab lists the names the model accepts."""

    def test_names_as_the_model(self):
        from mobile.driving import LAT_NAMES, LON_NAMES, POP_NAMES, RAIN_NAMES, TEMP_NAMES, TIME_NAMES
        from mobile.setup_ui import driving_files_help

        source = Path(MOBILE, "src", "mo_control.f90").read_text()

        def model_names(array):
            line = re.search(rf"^\s*character\(len=\d+\)\s*::\s*{array}\(\d+\)\s*=\s*\[[^:]*::(.*)\]", source, re.M).group(1)
            return re.findall(r'"([^"]*)"', line)

        for names, array in ((POP_NAMES, "pop_names"), (RAIN_NAMES, "rain_names"), (TEMP_NAMES, "temp_names"),
                             (LAT_NAMES, "lat_names"), (LON_NAMES, "lon_names"), (TIME_NAMES, "time_names")):
            self.assertEqual(names, model_names(array), array)
        html = str(driving_files_help())
        for name in (*POP_NAMES, *RAIN_NAMES, *TEMP_NAMES, *LAT_NAMES, *LON_NAMES, *TIME_NAMES):
            self.assertIn(f"<code>{name}</code>", html)
        for unit in ("mm/day", "°C", "persons/m²"):
            self.assertIn(unit, html)
        # What the GUI does not need is said, and no file for it is asked
        self.assertIn("Not needed in the GUI", html)
        self.assertNotIn("area.nc", html)


class TestCalibrationData(unittest.TestCase):
    """Observations for calibration: tables of every shape, the standard netCDF file, checks and processing."""

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)

    def daily(self, first="2001-01-01", last="2001-12-31", value=None):
        """A dated table of daily counts, value i on day i (from 0) unless given."""
        import pandas as pd
        days = pd.date_range(first, last, freq="D")
        return pd.DataFrame({"day": days.strftime("%Y-%m-%d"), "cases": np.arange(len(days), dtype=float) if value is None else value,
                             "N": np.full(len(days), 1000.0)})

    def test_tables_of_any_separator(self):
        from mobile.calibration_data import read_table
        rows = [("date", "PF", "N"), ("2001-01-15", "7", "1200"), ("2001-02-15", "NA", "1210")]
        for separator in (",", ";", "\t"):
            table = read_table("\n".join(separator.join(row) for row in rows) + "\n")
            self.assertEqual(list(table.columns), ["date", "PF", "N"], separator)
            self.assertTrue(np.isnan(table["PF"].iloc[1]))
        # Written by R: quoted header, row names, blanks
        table = read_table('"date" "PF" "N"\n"1" 2001-01-15 7 1200\n"2" 2001-02-15 NA 1210\n')
        self.assertEqual(list(table.columns), ["date", "PF", "N"])
        self.assertEqual(float(table["N"].iloc[0]), 1200.0)

    def test_dated_import(self):
        import pandas as pd
        from mobile.calibration_data import DataError, import_table
        table = pd.DataFrame({"date": ["1990-03-15", "1990-01-15", "1990-01-15", "1990-04-15"], "PF": [3.0, 1.0, 1.0, np.nan],
                              "N": [100.0, 100.0, 100.0, 100.0]})
        observations = import_table(table, "dated", "PF", "sum", "cases", date="date", period="month", extra=("N",))
        # Sorted; a mid-month date stands for its month; the exact repeat kept once; the gap and the missing value said
        self.assertEqual([observations.label(i) for i in range(len(observations))], ["1990-01", "1990-03", "1990-04"])
        self.assertEqual(str(observations.index["start"].iloc[1].date()), "1990-03-01")
        self.assertEqual(str(observations.index["end"].iloc[1].date()), "1990-03-31")
        notes = " ".join(observations.notes)
        for said in ("1 rows repeated exactly", "1 values missing", "1 gaps between periods, e.g. 1990-02-01 to 1990-02-28"):
            self.assertIn(said, notes)
        # Different values for the same month, or overlapping periods: refused
        clash = pd.concat([table, pd.DataFrame({"date": ["1990-01-20"], "PF": [2.0], "N": [100.0]})])
        with self.assertRaisesRegex(DataError, "different values for the same start, end"):
            import_table(clash, "dated", "PF", "sum", "cases", date="date", period="month")
        spans = pd.DataFrame({"start": ["1990-01-01", "1990-01-05"], "end": ["1990-01-07", "1990-01-11"], "v": [1.0, 2.0]})
        with self.assertRaisesRegex(DataError, "periods overlap"):
            import_table(spans, "dated", "v", "sum", "cases", start="start", end="end")
        # The minimum information
        with self.assertRaisesRegex(DataError, "units are needed"):
            import_table(table, "dated", "PF", "sum", " ", date="date")
        with self.assertRaisesRegex(DataError, "need the column date"):
            import_table(table, "dated", "PF", "sum", "cases")
        with self.assertRaisesRegex(DataError, "no column 'cases'"):
            import_table(table, "dated", "cases", "sum", "cases", date="date")
        with self.assertRaisesRegex(DataError, "not dates"):
            import_table(pd.DataFrame({"date": ["soon"], "v": [1.0]}), "dated", "v", "sum", "cases", date="date")

    def test_other_shapes(self):
        import pandas as pd
        from mobile.calibration_data import DataError, import_table
        months = import_table(pd.DataFrame({"m": range(12, 0, -1), "eir": np.arange(12.0), "s": np.ones(12)}), "climatology", "eir",
                              "mean", "bites per person per day", month="m", sd="s")
        self.assertEqual([months.label(i) for i in (0, 11)], ["Jan", "Dec"])
        self.assertEqual(months.values[0], 11.0)
        with self.assertRaisesRegex(DataError, "months must be whole numbers from 1 to 12"):
            import_table(pd.DataFrame({"m": [13], "v": [1.0]}), "climatology", "v", "mean", "x", month="m")
        ages = import_table(pd.DataFrame({"lo": [0, 5, 60], "hi": [4, 59, None], "v": [1.0, 2.0, 3.0]}), "age", "v", "mean",
                            "attacks per person per year", age_lower="lo", age_upper="hi")
        self.assertEqual([ages.label(i) for i in range(3)], ["0-4", "5-59", "60+"])
        years = import_table(pd.DataFrame({"y": [1994, 1993], "aeir": [18.49, 59.8]}), "yearly", "aeir", "sum", "bites per person", year="y")
        self.assertEqual([years.label(i) for i in range(2)], ["1993", "1994"])
        one = import_table(pd.DataFrame({"aeir": [39.27], "sd": [28.5]}), "single", "aeir", "sum", "bites per person", sd="sd")
        self.assertEqual((len(one), one.sd[0]), (1, 28.5))
        with self.assertRaisesRegex(DataError, "a single value needs one row"):
            import_table(pd.DataFrame({"v": [1.0, 2.0]}), "single", "v", "sum", "x")

    def test_standard_file(self):
        import pandas as pd
        from mobile.calibration_data import DataError, import_table, read_observations, write_observations
        sets = [
            import_table(self.daily(), "dated", "cases", "sum", "cases", date="day", period="day", extra=("N",)),
            import_table(pd.DataFrame({"m": range(1, 13), "v": np.arange(12.0), "s": np.full(12, 0.5)}), "climatology", "v", "mean", "x", month="m", sd="s"),
            import_table(pd.DataFrame({"y": [1993, 1994], "v": [1.0, np.nan]}), "yearly", "v", "sum", "x", year="y"),
            import_table(pd.DataFrame({"lo": [0, 60], "hi": [59, None], "v": [1.0, 2.0]}), "age", "v", "mean", "x", age_lower="lo", age_upper="hi"),
            import_table(pd.DataFrame({"v": [39.27]}), "single", "v", "sum", "x"),
        ]
        for observations in sets:
            path = self.folder / f"{observations.shape}.nc"
            write_observations(observations, path)
            back = read_observations(path)
            self.assertEqual((back.shape, back.units, back.aggregation, back.notes), (observations.shape, observations.units,
                             observations.aggregation, observations.notes))
            self.assertTrue(np.array_equal(back.values, observations.values, equal_nan=True), observations.shape)
            self.assertEqual([back.label(i) for i in range(len(back))], [observations.label(i) for i in range(len(observations))])
            if observations.sd is not None:
                self.assertTrue(np.array_equal(back.sd, observations.sd))
        self.assertTrue(np.array_equal(read_observations(self.folder / "dated.nc").extra["N"], sets[0].extra["N"]))
        # CF time bounds of a day: from its start to the start of the next
        import netCDF4
        with netCDF4.Dataset(self.folder / "dated.nc") as data:
            self.assertEqual(list(data["time_bnds"][0]), [36890.0, 36891.0])  # 2001-01-01 in days since 1900-01-01
            self.assertEqual(data["time"].bounds, "time_bnds")
        # A driving file is not a file of observations
        with self.assertRaisesRegex(DataError, "not a file of observations"):
            read_observations(Path(MOBILE) / "utils" / "test_run" / "pop.nc")

    def test_processing_steps(self):
        import pandas as pd
        from mobile.calibration_data import DataError, import_table, period_kind, read_observations, write_observations
        from mobile.calibration_steps import STEP_KINDS, apply_steps, default_step
        days = import_table(self.daily(), "dated", "cases", "sum", "cases", date="day", period="day", extra=("N",))
        step = lambda kind, **changes: {**default_step(kind, days), **changes}
        # Aggregate: sums by month add up to the daily total (control), January holds days 0 to 30
        months = apply_steps(days, [step("aggregate", period="month")])
        self.assertEqual((len(months), months.values.sum(), months.values[0]), (12, days.values.sum(), sum(range(31))))
        self.assertEqual(period_kind(months), "month")
        self.assertEqual(list(months.extra["N"]), [1000.0] * 12)
        # 52 weeks from Monday 1 January (the 53rd starts on 31 December, incomplete); 36 complete 10-day periods
        for period, n in (("quarter", 4), ("year", 1), ("week", 52), ("days", 36)):
            self.assertEqual(len(apply_steps(days, [step("aggregate", period=period, days=10)])), n, period)
        # Seasons: December belongs to the DJF of the next year, so 2001 has MAM, JJA and SON entirely
        seasons = apply_steps(days, [step("aggregate", period="season")])
        self.assertEqual([seasons.label(i) for i in range(len(seasons))], ["2001-03 to 2001-05", "2001-06 to 2001-08", "2001-09 to 2001-11"])
        # Statistics, and incomplete periods kept with their coverage
        rates = import_table(self.daily(value=np.r_[np.full(31, 1.0), np.full(334, 3.0)]), "dated", "cases", "mean", "per day", date="day", period="day")
        self.assertEqual(list(apply_steps(rates, [{**default_step("aggregate", rates), "period": "year"}]).values), [(31 + 334 * 3.0) / 365])
        self.assertEqual(apply_steps(days, [step("aggregate", period="month", how="max")]).values[0], 30.0)
        part = import_table(self.daily("2001-01-01", "2001-02-10"), "dated", "cases", "sum", "cases", date="day", period="day")
        self.assertEqual(len(apply_steps(part, [{**default_step("aggregate", part), "period": "month"}])), 1)
        kept = apply_steps(part, [{**default_step("aggregate", part), "period": "month", "complete": False}])
        self.assertEqual(round(kept.extra["coverage"][1], 4), round(10 / 28, 4))
        with self.assertRaisesRegex(DataError, r"step 1 \(aggregate into longer periods\): no year is covered entirely"):
            apply_steps(part, [{**default_step("aggregate", part), "period": "year"}])
        # Arithmetic with a column or a number; select; climatology by month
        per = apply_steps(months, [{**default_step("arithmetic", months), "units": "cases per person"}])
        self.assertEqual((per.values[0], per.units), (sum(range(31)) / 1000, "cases per person"))
        self.assertEqual(apply_steps(months, [step("arithmetic", operand="number", operation="multiply", number=2.0)]).values[0], 2 * sum(range(31)))
        with self.assertRaisesRegex(DataError, "division by zero"):
            apply_steps(months, [step("arithmetic", operand="number", number=0.0)])
        summer = apply_steps(months, [{"kind": "select", "what": "months", "items": [6, 7, 8]}])
        self.assertEqual([summer.label(i) for i in range(3)], ["2001-06", "2001-07", "2001-08"])
        two = import_table(pd.DataFrame({"d": [f"{y}-{m:02d}-15" for y in (2001, 2002) for m in range(1, 13)],
                                         "v": [1.0, *[0.0] * 11, 3.0, *[0.0] * 11]}), "dated", "v", "sum", "cases", date="d", period="month")
        season = apply_steps(two, [{"kind": "climatology", "by": "month"}])
        self.assertEqual((season.shape, season.values[0], round(season.sd[0], 6)), ("climatology", 2.0, round(np.sqrt(2.0), 6)))
        by_season = apply_steps(two, [{"kind": "aggregate", "period": "season", "how": "sum", "complete": False, "days": 1},
                                      {"kind": "climatology", "by": "season"}])
        self.assertEqual([by_season.label(i) for i in range(4)], ["DJF", "MAM", "JJA", "SON"])
        with self.assertRaisesRegex(DataError, "more than one month"):
            apply_steps(months, [{"kind": "aggregate", "period": "quarter", "how": "sum", "complete": True, "days": 1}, {"kind": "climatology", "by": "month"}])
        # Transforms
        log = apply_steps(months, [{"kind": "transform", "transform": "log10", "offset": 1.0, "window": 3}])
        self.assertAlmostEqual(log.values[0], np.log10(sum(range(31)) + 1))
        z = apply_steps(months, [{"kind": "transform", "transform": "standardise", "offset": 0, "window": 3}])
        self.assertAlmostEqual(float(np.mean(z.values)), 0.0)
        self.assertAlmostEqual(float(np.std(z.values, ddof=1)), 1.0)
        smooth = apply_steps(months, [{"kind": "transform", "transform": "moving_average", "offset": 0, "window": 3}])
        self.assertTrue(np.isnan(smooth.values[0]))
        self.assertAlmostEqual(smooth.values[1], months.values[:3].mean())
        # Frequency filter on a monthly series of a 12-month cycle plus a 5-year cycle (control: each is kept or removed)
        n = 240
        t_ = np.arange(n)
        annual, five = np.sin(2 * np.pi * t_ / 12), 2 * np.sin(2 * np.pi * t_ / 60)
        series = import_table(pd.DataFrame({"d": pd.date_range("1980-01-15", periods=n, freq="MS").strftime("%Y-%m-15"), "v": annual + five}),
                              "dated", "v", "mean", "x", date="d", period="month")
        inner = slice(60, 180)  # Away from the ends
        low = apply_steps(series, [{"kind": "filter", "type": "low", "short": 1, "long": 2, "unit": "years"}])
        self.assertLess(np.max(np.abs(low.values[inner] - five[inner])), 0.1)
        high = apply_steps(series, [{"kind": "filter", "type": "high", "short": 2, "long": 10, "unit": "years"}])
        self.assertLess(np.max(np.abs(high.values[inner] - annual[inner])), 0.1)
        # A band pass rings longer: on 50 years, judged 15 years (about two of the longest periods) from each end
        n = 600
        t_ = np.arange(n)
        annual, five = np.sin(2 * np.pi * t_ / 12), 2 * np.sin(2 * np.pi * t_ / 60)
        long_series = import_table(pd.DataFrame({"d": pd.date_range("1960-01-15", periods=n, freq="MS").strftime("%Y-%m-15"), "v": annual + five}),
                                   "dated", "v", "mean", "x", date="d", period="month")
        band = apply_steps(long_series, [{"kind": "filter", "type": "band", "short": 3, "long": 8, "unit": "years"}])
        self.assertLess(np.max(np.abs(band.values[180:-180] - five[180:-180])), 0.1)
        # A step saved before the ends were cut has no "edges": kept, with a note of how far they reach
        self.assertRegex(" ".join(band.notes), r"ends kept, though the filter's start-up error exceeds 5% of a cycle it keeps within [\d.]+ years at the start")
        with self.assertRaisesRegex(DataError, "longer than two values"):
            apply_steps(series, [{"kind": "filter", "type": "high", "short": 1, "long": 2, "unit": "months"}])
        # Missing values and missing periods: interpolated for the filter only, and put back as missing (240 months again)
        from mobile.calibration_steps import describe
        n = 240
        t_ = np.arange(n)
        annual, five = np.sin(2 * np.pi * t_ / 12), 2 * np.sin(2 * np.pi * t_ / 60)
        low_step = {"kind": "filter", "type": "low", "short": 1, "long": 2, "unit": "years", "missing": "interpolate", "max_gap": 3}
        complete = apply_steps(series, [low_step]).values
        holes = import_table(pd.DataFrame({"d": pd.date_range("1980-01-15", periods=n, freq="MS").strftime("%Y-%m-15"),
                                           "v": np.where(np.isin(t_, [100, 101]), np.nan, annual + five)}).drop(index=150),
                             "dated", "v", "mean", "x", date="d", period="month")
        gappy = apply_steps(holes, [low_step])
        self.assertEqual(len(gappy), n - 1)  # The missing row is not added
        self.assertTrue(np.isnan(gappy.values[[100, 101]]).all())  # Interpolated values are not data
        rows = np.r_[60:95, 106:145, 156:180]  # Away from the gaps, in rows of the series without row 150
        self.assertLess(np.max(np.abs(gappy.values[rows] - complete[np.where(rows < 150, rows, rows + 1)])), 0.05)
        notes = " ".join(gappy.notes)
        self.assertIn("2 gaps of up to 2 values interpolated for the filter only, left missing after", notes)
        self.assertIn("gaps of up to 3 values interpolated for the filter only", describe(low_step))
        # A gap longer than N splits the series; filtering each stretch separately interpolates nothing
        long_gap = import_table(pd.DataFrame({"d": pd.date_range("1980-01-15", periods=n, freq="MS").strftime("%Y-%m-15"),
                                              "v": np.where((t_ >= 100) & (t_ < 110), np.nan, annual + five)}), "dated", "v", "mean", "x", date="d", period="month")
        self.assertIn("2 stretches without gaps filtered separately", " ".join(apply_steps(long_gap, [low_step]).notes))
        apart = apply_steps(holes, [{**low_step, "missing": "stretches"}])
        self.assertNotIn("interpolated", " ".join(apart.notes))
        self.assertIn("each stretch without gaps filtered separately", describe({**low_step, "missing": "stretches"}))
        # A stretch too short for the cut-off is left missing
        short_end = import_table(pd.DataFrame({"d": pd.date_range("1980-01-15", periods=n, freq="MS").strftime("%Y-%m-15"),
                                               "v": np.where((t_ >= 220) & (t_ < 230), np.nan, annual + five)}), "dated", "v", "mean", "x", date="d", period="month")
        tail = apply_steps(short_end, [low_step])
        self.assertTrue(np.isnan(tail.values[230:]).all())
        self.assertIn("10 values in stretches shorter than", " ".join(tail.notes))
        # Combine with other observations of the same coordinates
        a = import_table(pd.DataFrame({"m": range(1, 13), "v": np.ones(12), "s": np.full(12, 3.0)}), "climatology", "v", "mean", "x", month="m", sd="s")
        b = import_table(pd.DataFrame({"m": range(1, 13), "v": np.full(12, 2.0), "s": np.full(12, 4.0)}), "climatology", "v", "mean", "x", month="m", sd="s")
        both = apply_steps(a, [{"kind": "combine", "other": "b", "how": "sum"}], {"b": b})
        self.assertEqual((both.values[0], both.sd[0]), (3.0, 5.0))
        self.assertEqual(apply_steps(a, [{"kind": "combine", "other": "b", "how": "difference"}], {"b": b}).values[0], -1.0)
        with self.assertRaisesRegex(DataError, "same shape and the same coordinates"):
            apply_steps(a, [{"kind": "combine", "other": "m", "how": "sum"}], {"m": months})
        # The steps are kept with the observations, in the standard file too, and can be applied again
        chain = [step("aggregate", period="month"), {**default_step("arithmetic", months), "units": "cases per person"}]
        result = apply_steps(days, chain)
        self.assertEqual([s["kind"] for s in result.steps], ["aggregate", "arithmetic"])
        write_observations(result, self.folder / "steps.nc")
        back = read_observations(self.folder / "steps.nc")
        self.assertEqual(list(back.steps), chain)
        self.assertTrue(np.array_equal(apply_steps(days, list(back.steps)).values, result.values))
        self.assertEqual(set(STEP_KINDS), {"aggregate", "arithmetic", "select", "climatology", "transform", "filter", "combine"})
        # An earlier stage drawn with the result: overlaid if same shape and units, else in a panel below
        from mobile.plots import observations_figure
        alone = observations_figure(months, "file")
        self.assertEqual((len(alone.data), alone.layout.height), (1, 380))
        smoothed = apply_steps(months, [{"kind": "transform", "transform": "moving_average", "offset": 0, "window": 3}])
        overlay = observations_figure(smoothed, "file", months, "Values loaded")
        self.assertEqual([trace.name for trace in overlay.data], ["Values loaded", "After all steps"])
        self.assertIsNone(overlay.layout.xaxis2.domain if "xaxis2" in overlay.layout else None)
        per_person = observations_figure(per, "file", months, "After step 1")  # cases per person vs cases: two panels
        self.assertEqual((len(per_person.data), per_person.layout.height), (2, 640))
        self.assertEqual((per_person.layout.yaxis.title.text, per_person.layout.yaxis2.title.text), ("cases per person", "cases"))
        self.assertEqual(per_person.data[1].xaxis, "x2")
        # Every shape can be drawn (a seasonal climatology once had no axis title, and the plot kept the last one)
        quarters = observations_figure(by_season, "file")
        self.assertEqual((list(quarters.data[0].x), quarters.layout.xaxis.title.text), (["DJF", "MAM", "JJA", "SON"], "Season"))
        seasonal = observations_figure(season, "file", two, "Values loaded")  # a climatology vs the months: two panels, by category
        self.assertEqual((seasonal.layout.xaxis.type, seasonal.layout.xaxis2.type), ("category", None))


def fake_run(folder, values, pop, seed=1):
    """A finished run folder with an output Human/Inew (time, lat, lon) on a 2 x 2 grid and its population file."""
    folder = Path(folder)
    (folder / "output").mkdir(parents=True)
    lat, lon = np.array([10.0, 10.5]), np.array([30.0, 30.5])
    pop_file = folder / "pop.nc"
    with netCDF4.Dataset(pop_file, "w") as data:
        data.createDimension("lat", 2), data.createDimension("lon", 2)
        data.createVariable("lat", "f8", ("lat",))[:] = lat
        data.createVariable("lon", "f8", ("lon",))[:] = lon
        data.createVariable("pop", "f8", ("lat", "lon"), fill_value=np.nan)[:] = pop
    with netCDF4.Dataset(folder / "output" / "output.nc", "w") as data:
        for name, size in (("time", values.shape[0]), ("lat", 2), ("lon", 2)):
            data.createDimension(name, size)
        time = data.createVariable("time", "f8", ("time",))
        time.units, time.calendar = "days since 2001-1-1 0:0:0", "gregorian"
        time[:] = np.arange(values.shape[0])
        data.createVariable("lat", "f8", ("lat",))[:] = lat
        data.createVariable("lon", "f8", ("lon",))[:] = lon
        variable = data.createGroup("Human").createVariable("Inew", "f4", ("time", "lat", "lon"), fill_value=np.float32(np.nan))
        variable.units, variable.long_name = "fraction", "NEW symptomatic population per person"
        variable[:] = values
        climate = data.createGroup("Climate")
        for name, units, value in (("rain", "mm/day", 2.0), ("t2m", "celsius", 20.0)):
            field = climate.createVariable(name, "f4", ("time", "lat", "lon"), fill_value=np.float32(np.nan))
            field.units, field.long_name = units, name
            field[:] = np.where(np.isnan(values), np.nan, value + np.arange(values.shape[0])[:, None, None] * 0.0)
    (folder / "run.json").write_text(json.dumps({"status": "finished", "date": "2026-11-08T12:00:00", "returncode": 0, "wall_seconds": 1,
                                                 "spinup_years": 0, "run": {"seed": seed}, "inputs": {"pop_file": str(pop_file)},
                                                 "region": None, "period": None}))
    return folder


TOY_MODEL = """
import sys
from pathlib import Path
import netCDF4, numpy as np
args = dict(zip(sys.argv[1::2], sys.argv[2::2]))
with netCDF4.Dataset(args["-t"]) as data:
    t2m = np.ma.filled(data["temperature"][:].astype("f8"), np.nan)
    time = data["time"]
    days, units, calendar = time[:], time.units, getattr(time, "calendar", "standard")
    lat, lon = data["lat"][:], data["lon"][:]
with netCDF4.Dataset(args["-p"]) as data:
    pop = np.ma.filled(data["pop"][:].astype("f8"), np.nan)
inew = np.where(pop > 0, 1e-3 * np.maximum(t2m - 18.0, 0.0), np.nan)
out = Path(args["-o"])
out.mkdir(exist_ok=True)
with netCDF4.Dataset(out / "output.nc", "w") as data:
    for name, size in (("time", len(days)), ("lat", len(lat)), ("lon", len(lon))):
        data.createDimension(name, size)
    variable = data.createVariable("time", "f8", ("time",))
    variable[:], variable.units, variable.calendar = days, units, calendar
    data.createVariable("lat", "f8", ("lat",))[:] = lat
    data.createVariable("lon", "f8", ("lon",))[:] = lon
    field = data.createGroup("Human").createVariable("Inew", "f4", ("time", "lat", "lon"), fill_value=np.float32(np.nan))
    field.units, field.long_name = "fraction", "NEW symptomatic population per person"
    field[:] = inew
    climate = data.createGroup("Climate").createVariable("t2m", "f4", ("time", "lat", "lon"), fill_value=np.float32(np.nan))
    climate.units, climate.long_name = "celsius", "temperature"
    climate[:] = t2m
print("Program finished successfully")
"""


class TestFilterEdges(unittest.TestCase):
    """The ends of a frequency filter, where it starts up: measured on test cycles, cut by default, shown shaded."""

    @staticmethod
    def monthly(values, first="1990-01"):
        from mobile.calibration_data import Observations
        start = pd.date_range(first, periods=len(values), freq="MS")
        index = pd.DataFrame({"start": start.values.astype("datetime64[D]"),
                              "end": (start + pd.offsets.MonthEnd(0)).values.astype("datetime64[D]")})
        return Observations(shape="dated", values=np.asarray(values, float), index=index, units="cases", name="cases")

    def filtered(self, values, **choices):
        from mobile.calibration_steps import apply_steps, default_step
        series = self.monthly(values)
        step = {**default_step("filter", series), **choices}
        return apply_steps(series, [{key: value for key, value in step.items() if value is not None}])  # None: left out

    def test_cut_where_measured(self):
        from mobile.calibration_steps import EDGE, edge_reach
        t = np.arange(240)
        for choices, kind, periods in (({"type": "low", "long": 2}, "low", (24.0,)),
                                       ({"type": "high", "short": 18, "unit": "months"}, "high", (18.0,)),
                                       ({"type": "band", "short": 1, "long": 1.5}, "band", (12.0, 18.0))):
            result = self.filtered(np.cos(2 * np.pi * t / 12) + np.cos(2 * np.pi * t / 60), **choices)
            start, end = edge_reach(kind, periods, 240, 0.05)
            self.assertGreater(start, 0)
            kept = np.isfinite(result.values)
            # Missing exactly where cut, and the cut values kept in their own column for the plots
            self.assertTrue(kept[start:240 - end].all() and not kept[:start].any() and not kept[240 - end:].any(), choices)
            self.assertTrue(np.isfinite(result.extra[EDGE][~kept]).all() and np.isnan(result.extra[EDGE][kept]).all())
            self.assertIn("shaded in the plots and not compared", result.notes[-1])

    def test_kept_values_within_the_error(self):
        """Control: cycles kept by the filter, between its test cycles and at other phases, err by at most the share
        set at the values kept, and by more at those cut."""
        from scipy import signal
        from mobile.calibration_steps import EDGE, _design, test_cycles
        t = np.arange(480)
        for choices, kind, periods in (({"type": "low", "long": 2}, "low", (24.0,)),
                                       ({"type": "high", "short": 18, "unit": "months"}, "high", (18.0,)),
                                       ({"type": "band", "short": 1.5, "long": 3}, "band", (18.0, 36.0))):
            tests = np.log(test_cycles(kind, periods))
            kept_error = cut_error = 0.0
            for period in np.exp((tests[1:] + tests[:-1]) / 2):
                gain = abs(signal.sosfreqz(_design(kind, periods), worN=[2 * np.pi / period])[1][0]) ** 2
                for phase in np.linspace(0, 2 * np.pi, 7)[:-1]:
                    cycle = np.cos(2 * np.pi * t / period + phase)
                    result = self.filtered(cycle, **choices)
                    kept = np.isfinite(result.values)
                    kept_error = max(kept_error, np.abs(result.values[kept] - gain * cycle[kept]).max())
                    cut_error = max(cut_error, np.abs(result.extra[EDGE][~kept] - gain * cycle[~kept]).max())
            self.assertLessEqual(kept_error, 0.05, choices)
            self.assertGreater(cut_error, 0.05, choices)

    def test_too_short_refused(self):
        from mobile.calibration_data import DataError
        t = np.arange(240)
        with self.assertRaisesRegex(DataError, r"too short for this filter once its unreliable ends are cut.*needs about \d+ values \([\d.]+ years\)"):
            self.filtered(np.cos(2 * np.pi * t / 60), type="band", short=3, long=8)
        # Kept, the same filter runs, and says that every value is affected
        kept = self.filtered(np.cos(2 * np.pi * t / 60), type="band", short=3, long=8, edges="keep")
        self.assertTrue(np.isfinite(kept.values).all())
        self.assertIn("at every value", kept.notes[-1])
        # A larger error kept cuts less
        t = np.arange(360)
        strict, loose = (self.filtered(np.cos(2 * np.pi * t / 24), type="band", short=1.5, long=3, edge_error=share) for share in (0.02, 0.2))
        self.assertLess(np.isfinite(strict.values).sum(), np.isfinite(loose.values).sum())

    def test_later_steps_carry_the_cut(self):
        from mobile.calibration_metrics import pair
        from mobile.calibration_steps import EDGE, apply_steps
        t = np.arange(240)
        series = self.monthly(10 + np.cos(2 * np.pi * t / 12) + np.cos(2 * np.pi * t / 60))
        cut = self.filtered(series.values, type="high", short=18, unit="months")
        # Standardised by the mean and spread of the values kept; the cut ones by the same numbers
        z = apply_steps(cut, [{"kind": "transform", "transform": "standardise", "offset": 0, "window": 3}])
        mean, sd = np.nanmean(cut.values), np.nanstd(cut.values, ddof=1)
        self.assertTrue(np.allclose(z.extra[EDGE], (cut.extra[EDGE] - mean) / sd, equal_nan=True))
        # A year with a month cut is cut too, shown with its value
        years = apply_steps(cut, [{"kind": "aggregate", "period": "year", "how": "mean", "complete": True, "days": 7}])
        self.assertEqual(len(years), 20)
        self.assertTrue(np.isnan(years.values[[0, 1, -2, -1]]).all() and np.isfinite(years.values[2:-2]).all())
        self.assertTrue(np.isfinite(years.extra[EDGE][[0, 1, -2, -1]]).all())
        # Only the values kept are compared
        model_values, data_values, labels = pair(cut, cut)
        self.assertEqual(len(labels), int(np.isfinite(cut.values).sum()))
        # A seed band: the median of the cut values too
        from mobile.calibration_model import seed_spread
        step = {**cut.steps[0]}
        band = seed_spread([series, replace(series, values=series.values + 1)], [step])
        self.assertTrue(np.array_equal(np.isfinite(band.extra[EDGE]), np.isfinite(cut.extra[EDGE])))

    def test_plots_shade_the_cut(self):
        from mobile.calibration_metrics import pair
        from mobile.plots import comparison_figure, cut_spans, observations_figure
        t = np.arange(240)
        cut = self.filtered(np.cos(2 * np.pi * t / 12), type="high", short=18, unit="months")
        self.assertEqual(len(cut_spans(cut)), 2)
        figure = observations_figure(cut, "test")
        self.assertEqual(len([shape for shape in figure.layout.shapes if shape.fillcolor and "214, 40, 40" in shape.fillcolor]), 2)
        self.assertTrue(any(trace.name.endswith("cut at the ends") for trace in figure.data))
        self.assertTrue(all(a.hovertext and "filter starts up" in a.hovertext for a in figure.layout.annotations if a.text == "cut"))
        m, d, labels = pair(cut, cut)
        both = comparison_figure(cut, cut, labels, m, d)
        self.assertEqual(sum(trace.name.endswith("cut at the ends") for trace in both.data), 2)

    def test_old_steps_and_describe(self):
        from mobile.calibration_steps import EDGE, default_step, describe
        t = np.arange(240)
        old = self.filtered(np.cos(2 * np.pi * t / 60), type="low", long=2, edges=None)
        self.assertNotIn(EDGE, old.extra)
        step = default_step("filter", self.monthly(t))
        self.assertEqual((step["edges"], step["edge_error"]), ("cut", 0.05))
        self.assertIn("ends cut where the filter's start-up error exceeds 5% of a cycle it keeps", describe(step))
        self.assertNotIn("ends cut", describe({key: value for key, value in step.items() if key not in ("edges", "edge_error")}))


class TestSharedPeriod(unittest.TestCase):
    """Model and data are cut to the period they share before their steps, so that a climatology covers the same years."""

    @staticmethod
    def daily(first, last, value):
        from mobile.calibration_data import Observations

        day = np.arange(np.datetime64(first), np.datetime64(last) + 1)
        values = value(day.astype("datetime64[Y]").astype(int) + 1970) * np.ones(len(day))
        return Observations(shape="dated", values=values, index=pd.DataFrame({"start": day, "end": day}), aggregation="sum",
                            units="fraction", name="x")

    def test_climatology_over_the_shared_years_only(self):
        from mobile.calibration_data import DataError
        from mobile.calibration_metrics import pair
        from mobile.calibration_model import process_both, shared_span
        from mobile.calibration_steps import apply_steps

        steps = [{"kind": "aggregate", "period": "month", "how": "sum", "complete": True, "days": 1}, {"kind": "climatology", "by": "month"}]
        model = self.daily("2001-01-01", "2002-12-31", lambda year: 1.0)
        # The data are 1 a day in 2001-2002 and 10 a day in the years around them, monthly as loaded
        data = apply_steps(self.daily("1999-01-01", "2004-12-31", lambda year: np.where((year >= 2001) & (year <= 2002), 1.0, 10.0)),
                           steps[:1])
        self.assertEqual(shared_span(model, data), ("2001-01-01", "2002-12-31"))
        m, d, span = process_both([model], steps, data, steps[1:])
        self.assertEqual(span, ("2001-01-01", "2002-12-31"))
        m, d, _ = pair(m, d)
        np.testing.assert_allclose(m, d)  # Both 1 a day: the years around do not enter
        self.assertEqual(round(float(d[0]), 6), 31.0)
        # Without the cut the data's January would mix in the 10s: what the earlier objectives did
        self.assertGreater(float(apply_steps(data, steps[1:]).values[0]), 31.0)
        # Several seeds: each cut, then the median and range
        m2, _, _ = process_both([model, self.daily("2000-06-01", "2002-12-31", lambda year: 3.0)], steps, data, steps[1:])
        self.assertEqual(float(m2.values[0]), 62.0)  # Median of 31 and 93
        # Nothing shared
        with self.assertRaises(DataError):
            shared_span(self.daily("1990-01-01", "1990-12-31", lambda year: 1.0), data)
        # Not dated (a climatology loaded as such): nothing to cut
        self.assertIsNone(process_both([model], steps, apply_steps(data, steps[1:]), [])[2])

    def test_validation_window_kept_out_before_the_steps(self):
        from mobile.calibration_data import DataError, drop_window
        from mobile.calibration_model import process_both
        from mobile.calibration_steps import apply_steps

        steps = [{"kind": "aggregate", "period": "month", "how": "sum", "complete": True, "days": 1}, {"kind": "climatology", "by": "month"}]
        model = self.daily("2001-01-01", "2002-12-31", lambda year: np.where(year == 2001, 1.0, 2.0))
        data = apply_steps(model, steps[:1])  # Monthly: 1 a day in 2001, 2 a day in 2002
        window = ("2002-01-01", "2002-12-31")
        m, d, _ = process_both([model], steps, data, steps[1:], validation=window, part="calibration")
        self.assertEqual((float(m.values[0]), float(d.values[0])), (31.0, 31.0))  # January of 2001 only
        m, d, _ = process_both([model], steps, data, steps[1:], validation=window, part="validation")
        self.assertEqual((float(m.values[0]), float(d.values[0])), (62.0, 62.0))  # January of 2002 only
        m, d, _ = process_both([model], steps, data, steps[1:], validation=window)  # No part: the whole shared period
        self.assertEqual(float(d.values[0]), 46.5)
        # A month across the start of the window is left out of the calibration too
        self.assertEqual(len(drop_window(data, "2002-01-15", "2002-12-31")), 12)
        with self.assertRaises(DataError):
            drop_window(data, "2000-01-01", "2003-12-31")
        with self.assertRaises(DataError):  # Not dated: no window in time
            process_both([model], steps, apply_steps(data, steps[1:]), [], validation=window, part="calibration")

    def test_window_bars(self):
        import plotly.graph_objects as go

        from mobile.plots import CALIBRATION_WINDOW, VALIDATION_WINDOW, mark_windows

        span = ("1985-01-01", "2004-12-31")
        for window, colours in ((("2000-01-01", "2004-12-31"), [CALIBRATION_WINDOW, VALIDATION_WINDOW]),
                                (("1993-01-01", "1997-12-31"), [CALIBRATION_WINDOW, VALIDATION_WINDOW, CALIBRATION_WINDOW]),
                                (("1980-01-01", "1989-12-31"), [VALIDATION_WINDOW, CALIBRATION_WINDOW])):  # Clipped to the span
            figure = mark_windows(go.Figure(go.Scatter(x=["1985-01-15", "2004-12-15"], y=[0, 1])), span, window)
            self.assertEqual([shape.fillcolor for shape in figure.layout.shapes], colours)
            self.assertEqual(str(figure.layout.shapes[0].x0)[:10], "1985-01-01")
            self.assertEqual(str(figure.layout.shapes[-1].x1)[:10], "2004-12-31")


class TestCalibrationProgress(unittest.TestCase):
    """The steps at the right of the Calibration tab: every box links to a mark that exists in the tab."""

    def test_links_reach_the_tab(self):
        from mobile.calibration_progress import STEPS, step_box
        from mobile.calibration_ui import calibration_tab

        html = str(calibration_tab())
        for key, title, target in STEPS:
            box = str(step_box(key, title, target, "todo"))
            if target is None:  # Setup: opens tab 1
                self.assertIn("data-value=", box)
                self.assertIn("setup", box)
                continue
            self.assertIn(f'href="#{target}"', box)
            self.assertIn(f'id="{target}"', html, target)
        self.assertIn('class="cal-progress"', html)
        self.assertIn('id="cal_progress"', html)

    def test_states_are_said_in_words(self):
        from mobile.calibration_progress import WORDS, step_box

        for state, word in WORDS.items():
            box = str(step_box("run", "Run", "cal-step-calibrations", state, "running on leonardo"))
            self.assertIn(f'class="cal-step {state}"', box)
            self.assertIn(f">{word}<", box)  # Not by colour alone


class TestCalibrationEngine(unittest.TestCase):
    """A calibration with Optuna, on a toy model: new cases grow with the temperature above 18 °C. Observations made
    from it at known temperature offsets of two cells must be found again."""

    TRUTH = {"dT_1": 1.0, "dT_2": 0.3}  # West, then east: the east stays warmer (18.8 against 18.0 °C on average)
    # Builds unless given a model (-E), then runs the toy
    FAKE = """#!/bin/bash
prebuilt=""
while getopts ":ho:p:r:t:d:n:m:s:a:c:u:v:i:l:M:B:T:C:O:E:" flag; do
  case $flag in E) [ "$OPTARG" != "NONE" ] && prebuilt=$OPTARG ;; esac
done
if [ -z "$prebuilt" ]; then
  echo build >> $EVENTS
  mkdir -p output && printf '#!/bin/bash\\n' > output/mobile.out && chmod +x output/mobile.out
fi
echo '================= Running MoBILE ================='
[ -n "$FAKE_FAIL" ] && { echo ' More agents than people! --> STOP'; exit 0; }
if [ -n "$FAKE_COUNTER" ]; then  # Runs counted from 1: those in FAKE_FAIL_RUNS fail, and all from FAKE_FAIL_FROM on
  count=$(( $(cat "$FAKE_COUNTER" 2>/dev/null || echo 0) + 1 )); echo $count > "$FAKE_COUNTER"
  case " $FAKE_FAIL_RUNS " in *" $count "*) echo ' More agents than people! --> STOP'; exit 0 ;; esac
  [ -n "$FAKE_FAIL_FROM" ] && [ $count -ge $FAKE_FAIL_FROM ] && { echo ' More agents than people! --> STOP'; exit 0; }
fi
sleep ${FAKE_SLEEP:-0}
"$FAKE_PYTHON" "$FAKE_TOY" "$@"
"""

    def setUp(self):
        from mobile.config import Config

        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        root = self.root = Path(folder.name)
        fake = root / "MoBILE"
        (fake / "utils").mkdir(parents=True)
        (fake / "src").mkdir()
        (fake / "utils" / "run_MOBILE.sh").write_text((Path(MOBILE) / "utils" / "run_MOBILE.sh").read_text())
        (fake / "src" / "mo_namelist.f90").write_text((Path(MOBILE) / "src" / "mo_namelist.f90").read_text())
        (fake / "mobile.sh").write_text(self.FAKE)
        (root / "toy.py").write_text(TOY_MODEL)
        self.events = root / "events.txt"
        self.events.write_text("")
        patch = mock.patch.dict(os.environ, {"EVENTS": str(self.events), "FAKE_PYTHON": sys.executable, "FAKE_TOY": str(root / "toy.py")})
        patch.start()
        self.addCleanup(patch.stop)
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(root)
        # Two cells of 0.5°, two years: the west cooler, its seasons half a year from those of the east
        days = np.arange(np.datetime64("2001-01-01"), np.datetime64("2003-01-01"))
        doy = np.arange(len(days)) % 365
        self.t2m = np.stack([17.0 + 3 * np.sin(2 * np.pi * (doy - 100) / 365), 18.5 + 3 * np.sin(2 * np.pi * (doy - 280) / 365)], axis=1)[:, None, :]
        self.pop = np.array([[2e-4, 3e-4]])
        self.cells = [{"lat": 8.75, "lon": 38.75}, {"lat": 8.75, "lon": 39.25}]
        files = {}
        for key, name, values, units in (("rain_file", "rain", np.full_like(self.t2m, 3.0), "mm/day"), ("temp_file", "temperature", self.t2m, "celsius"),
                                         ("pop_file", "pop", self.pop, "persons/m2")):
            path = files[key] = root / f"{name}.nc"
            with netCDF4.Dataset(path, "w") as data:
                for axis, centres in (("lat", [8.75]), ("lon", [38.75, 39.25])):
                    data.createDimension(axis, len(centres))
                    variable = data.createVariable(axis, "f8", (axis,))
                    variable[:], variable.bounds = centres, f"{axis}_bnds"
                    data.createDimension(f"{axis}_nv", 2)
                    data.createVariable(f"{axis}_bnds", "f8", (axis, f"{axis}_nv"))[:] = [[c - 0.25, c + 0.25] for c in centres]
                dims = ("lat", "lon")
                if key != "pop_file":
                    data.createDimension("time", len(days))
                    time = data.createVariable("time", "f8", ("time",))
                    time[:], time.units, time.calendar = np.arange(len(days)), "days since 2001-01-01", "proleptic_gregorian"
                    dims = ("time", *dims)
                field = data.createVariable(name, "f4", dims, fill_value=np.float32(1e20))
                field[:], field.units = values, units
        example = Config.load(CONFIG)
        self.config = replace(example, mobile=fake, runs_dir=root / "runs", inputs={**example.inputs, **{k: str(v) for k, v in files.items()}},
                              run={**example.run, "nstep": 0, "spin_up": 0, "nagent": 100, "threads": 1}, region=None, period=None,
                              age_structure={"product": "Global2000_2020", "country": "SEN", "year": 2012}, output=("out_I_new",))
        self.data = root / "cases.nc"
        self.write_observations(self.TRUTH, self.data)

    def write_observations(self, offsets, path):
        """Monthly cases per person of the two cells together, people-weighted, computed here from the toy's rule."""
        from mobile.calibration_data import Observations, write_observations
        from mobile.calibration_steps import apply_steps
        from mobile.cells import cell_areas

        shifted = self.t2m + np.array([[offsets["dT_1"], offsets["dT_2"]]])
        inew = 1e-3 * np.maximum(shifted - 18.0, 0.0)
        people = self.pop * cell_areas(self.root / "pop.nc")
        daily = (inew * people).sum(axis=(1, 2)) / people.sum()
        day = np.arange(np.datetime64("2001-01-01"), np.datetime64("2003-01-01"))
        observations = Observations(shape="dated", values=daily, index=pd.DataFrame({"start": day, "end": day}), aggregation="sum",
                                    units="fraction", name="cases")
        write_observations(apply_steps(observations, self.MONTHLY), path)

    MONTHLY = [{"kind": "aggregate", "period": "month", "how": "sum", "complete": True, "days": 1}]

    def objectives(self):
        return [{"name": "timing", "data": str(self.data), "variable": "Inew", "steps": self.MONTHLY, "metric": "correlation"},
                {"name": "swings", "data": str(self.data), "variable": "Inew", "steps": self.MONTHLY, "metric": "rmse_relative"}]

    def temperature(self):
        return {"cells": self.cells, "first": (-2.0, 2.0), "gap": (0.0, 3.0)}

    def test_objectives_with_raw_data_are_cut_to_the_shared_period(self):
        from mobile.calibration_data import Observations, read_observations, write_observations
        from mobile.calibration_engine import objective_series
        from mobile.calibration_steps import apply_steps
        from mobile.runner import Runner

        result = Runner(self.config).run("cut")
        self.assertTrue(result.ok, result.log_tail())
        folder = result.run_dir
        loaded = read_observations(self.data)  # Monthly, 2001-2002
        # The same months with a year of big values before and after: loaded as such, not cut
        months = pd.date_range("2000-01-01", "2003-12-01", freq="MS")
        values = np.where((months.year >= 2001) & (months.year <= 2002), np.resize(loaded.values, len(months)), 1.0)
        index = pd.DataFrame({"start": months.values.astype("datetime64[D]"), "end": (months + pd.offsets.MonthEnd(0)).values.astype("datetime64[D]")})
        raw = self.root / "raw.nc"
        write_observations(Observations(shape="dated", values=values, index=index, aggregation="sum", units="fraction", name="cases"), raw)
        climatology = [{"kind": "climatology", "by": "month"}]
        objective = {"name": "season", "data": str(self.data), "variable": "Inew", "space": "people", "aggregation": None,
                     "steps": self.MONTHLY + climatology, "metric": "rmse_relative"}
        cut = objective_series({**objective, "data_raw": str(raw), "data_steps": climatology}, [folder])[1]
        np.testing.assert_allclose(cut.values, apply_steps(loaded, climatology).values)  # Only 2001-2002
        old = objective_series(objective, [folder])[1]  # Earlier objectives: the data as processed, read as they are
        np.testing.assert_allclose(old.values, loaded.values)

    def test_offsets_keep_the_order_of_the_cells(self):
        from mobile.calibration_engine import cell_means, offset_temperature, offsets_from

        means = cell_means(self.root / "temperature.nc", self.cells)
        np.testing.assert_allclose(means, self.t2m.mean(axis=0).ravel())
        temperature = {"cells": self.cells, "means": means}
        for dT_1, gap in ((-2.0, 0.0), (1.5, 0.0), (0.0, 2.5)):
            offsets = offsets_from(temperature, {"dT_1": dT_1, "gap_2": gap})
            self.assertAlmostEqual(means[1] + offsets["dT_2"] - (means[0] + offsets["dT_1"]), gap)  # East above west by the gap
        offsets = {"dT_1": 1.0, "dT_2": -0.5}
        offset_temperature(self.root / "temperature.nc", self.root / "shifted.nc", self.cells, offsets)
        with netCDF4.Dataset(self.root / "shifted.nc") as data:
            np.testing.assert_allclose(data["temperature"][:] - self.t2m, np.broadcast_to([[[1.0, -0.5]]], self.t2m.shape), atol=1e-5)

    def test_truth_gives_a_perfect_match(self):
        # The plumbing: the toy run at the true offsets, processed as the objectives say, matches the observations
        from mobile.calibration_engine import evaluate, offset_temperature
        from mobile.calibration_metrics import DIRECTIONS
        from mobile.runner import Runner

        offset_temperature(self.root / "temperature.nc", self.root / "true.nc", self.cells, self.TRUTH)
        result = Runner(replace(self.config, inputs={**self.config.inputs, "temp_file": str(self.root / "true.nc")})).run("truth")
        self.assertTrue(result.ok, result.log_tail())
        correlation, relative = evaluate([{**objective, "space": "people", "aggregation": None, "direction": DIRECTIONS[objective["metric"]]}
                                          for objective in self.objectives()], [result.run_dir])
        self.assertAlmostEqual(correlation, 1.0, places=5)
        self.assertLess(relative, 1e-4)

    def test_finds_the_offsets_again(self):
        from mobile.calibration_engine import best_trials, create_calibration, read_calibration, run_calibration, trials_table
        from mobile.sensitivity_runs import StudyState

        folder = create_calibration(self.config, self.objectives(), temperature=self.temperature(), n_trials=40, startup_trials=10,
                                    sampler_seed=1, name="toy")
        record = run_calibration(folder, StudyState(), parallel=4)
        self.assertEqual((record["status"], record["completed"], record["failed"]), ("finished", 40, 0))
        self.assertEqual(self.events.read_text().split(), ["build"])  # Built once, for all the trials
        self.assertEqual(record["binary_md5"], hashlib.md5((folder / "bin" / "mobile.out").read_bytes()).hexdigest())
        means = read_calibration(folder)["temperature"]["means"]
        rows = trials_table(folder)
        self.assertEqual(len(rows), 40)
        for row in rows:  # The east stays warmer in every trial
            self.assertGreaterEqual(means[1] + row["offsets"]["dT_2"], means[0] + row["offsets"]["dT_1"] - 1e-9)
        best = min(best_trials(folder), key=lambda row: row["values"][1])
        self.assertLess(best["values"][1], 0.15)
        for key, value in self.TRUTH.items():
            self.assertAlmostEqual(best["offsets"][key], value, delta=0.5, msg=(best, rows))

    def test_cancel_resume_and_failures(self):
        import threading

        from mobile.calibration_engine import counts, create_calibration, open_study, read_calibration, run_calibration
        from mobile.sensitivity_runs import StudyState

        folder = create_calibration(self.config, self.objectives(), temperature=self.temperature(), n_trials=12, name="resume")
        state = StudyState()
        outcome = {}
        with mock.patch.dict(os.environ, {"FAKE_SLEEP": "0.5"}):
            worker = threading.Thread(target=lambda: outcome.update(record=run_calibration(folder, state, parallel=2)))
            worker.start()
            time.sleep(2.0)
            state.cancel()
            worker.join(30)
        self.assertEqual(outcome["record"]["status"], "cancelled")
        done = outcome["record"]["completed"]
        self.assertLess(done, 12)
        record = run_calibration(folder, StudyState(), parallel=2)  # Resumed: only the trials left
        self.assertEqual((record["status"], record["completed"]), ("finished", 12))
        self.assertEqual(counts(open_study(folder, read_calibration(folder))), (12, 0))
        # Runs that all fail stop the calibration, with the end of a log
        failing = create_calibration(self.config, self.objectives(), temperature=self.temperature(), n_trials=10, name="failing")
        with mock.patch.dict(os.environ, {"FAKE_FAIL": "1"}):
            record = run_calibration(failing, StudyState(), parallel=1)
        self.assertEqual((record["status"], record["completed"], record["failed"]), ("stopped", 0, 3))
        self.assertIn("More agents than people", record["failure"])

    def test_what_the_tab_shows(self):
        from mobile.calibration_engine import (best_trials, calibration_label, create_calibration, read_calibration, run_calibration,
                                               trial_comparison, trials_table)
        from mobile.calibration_run_ui import offset_cells
        from mobile.plots import calibration_history_figure
        from mobile.sensitivity_runs import StudyState

        # The cells to offset, coolest first, with their means; too many for a big grid
        cells = offset_cells(self.config)
        self.assertEqual([(c["lat"], c["lon"]) for c in cells], [(8.75, 38.75), (8.75, 39.25)])
        np.testing.assert_allclose([c["mean"] for c in cells], self.t2m.mean(axis=0).ravel(), rtol=1e-6)
        with mock.patch("mobile.calibration_run_ui.MAX_SIMULATED", 1):
            self.assertIn("at most 1 cells", offset_cells(self.config))
        folder = create_calibration(self.config, self.objectives(), temperature=self.temperature(), n_trials=6, name="shown")
        record = run_calibration(folder, StudyState(), parallel=2)
        self.assertEqual(calibration_label(folder, record), "shown (finished, 6 of 6 trials completed, 2 objectives)")
        figure = calibration_history_figure(trials_table(folder), read_calibration(folder)["objectives"])
        self.assertEqual([len(trace.x) for trace in figure.data], [6, 6, 6, 6])  # Trials and best so far, for each objective
        # The first trial is the model as it is: no offset, both cells at the temperatures of the file
        first = trials_table(folder)[0]
        self.assertTrue(first["baseline"])
        self.assertAlmostEqual(first["offsets"]["dT_1"], 0.0)
        self.assertAlmostEqual(first["offsets"]["dT_2"], 0.0, places=6)
        self.assertEqual(sum(row["baseline"] for row in trials_table(folder)), 1)
        best = best_trials(folder)[0]
        model, data, m, d, labels = trial_comparison(folder, best["number"], 0)
        self.assertEqual((len(labels), labels[0], labels[-1]), (24, "2001-01", "2002-12"))
        self.assertAlmostEqual(float(np.corrcoef(m, d)[0, 1]), best["values"][0], places=6)  # The plot is what was scored

    def test_validation_window(self):
        from mobile.calibration_engine import (CalibrationError, create_calibration, evaluate, read_calibration, run_calibration,
                                               trial_comparison, trial_folder, trials_table)
        from mobile.sensitivity_runs import StudyState

        window = ("2002-07-01", "2002-12-31")
        objectives = [{**objective, "data_raw": str(self.data), "data_steps": []} for objective in self.objectives()]
        for given, why, wrong in ((self.objectives(), "add the objective again", window), (objectives, "no observations", ("1990-01-01", "1990-12-31")),
                                  (objectives, "start before", window[::-1])):
            with self.assertRaisesRegex(CalibrationError, why):
                create_calibration(self.config, given, temperature=self.temperature(), n_trials=2, validation=wrong)
        folder = create_calibration(self.config, objectives, temperature=self.temperature(), n_trials=4, name="validated", validation=window)
        record = run_calibration(folder, StudyState(), parallel=2)
        self.assertEqual(record["status"], "finished")
        record = read_calibration(folder)
        self.assertEqual(record["validation"], list(window))
        rows = trials_table(folder)
        self.assertTrue(all(len(row["validation"]) == 2 and all(isinstance(v, float) for v in row["validation"]) for row in rows))
        row = rows[0]
        run_dirs = [trial_folder(folder, row["number"]) / f"seed_{seed}" for seed in record["seeds"]]
        # Scored on the months outside the window; the window apart, kept with the trial
        np.testing.assert_allclose(row["values"], evaluate(record["objectives"], run_dirs, window, "calibration"))
        np.testing.assert_allclose(row["validation"], evaluate(record["objectives"], run_dirs, window, "validation"))
        self.assertFalse(np.allclose(row["values"], evaluate(record["objectives"], run_dirs)))
        self.assertEqual([len(trial_comparison(folder, row["number"], 0, part)[4]) for part in (None, "calibration", "validation")], [24, 18, 6])

    def test_results_views(self):
        from mobile.calibration_engine import create_calibration, run_calibration
        from mobile.calibration_results import FIGURES, ResultsError, results_figure
        from mobile.sensitivity_runs import StudyState

        folder = create_calibration(self.config, self.objectives(), temperature=self.temperature(), n_trials=12, name="views")
        run_calibration(folder, StudyState(), parallel=2)
        for kind in FIGURES:
            for index in (0, 1):
                figure = results_figure(folder, kind, index)
                self.assertTrue(figure.data, kind)
                self.assertTrue(figure.layout.title.text.startswith(FIGURES[kind][0]), kind)
        # The distributions: for each cell, all the trials, the best tenth, and the Pareto front
        figure = results_figure(folder, "distributions", 1)
        self.assertEqual([trace.name for trace in figure.data[:3]], ["All trials", "Best 10% by swings", "Pareto front"])
        self.assertEqual(sum(len(trace.x) for trace in figure.data if trace.name == "All trials"), 24)  # 12 trials × 2 cells
        # With one objective, no Pareto front to draw; with one cell, no pair of parameters
        single = create_calibration(self.config, self.objectives()[:1], temperature={**self.temperature(), "cells": self.cells[:1]},
                                    n_trials=4, name="single")
        run_calibration(single, StudyState(), parallel=2)
        for kind, why in (("pareto", "two objectives"), ("contour", "two sampled parameters"), ("rank", "two sampled parameters")):
            with self.assertRaisesRegex(ResultsError, why):
                results_figure(single, kind)

    def test_running_interrupted_and_one_at_a_time(self):
        import signal
        import subprocess
        import threading

        from mobile.calibration_engine import (CalibrationError, calibration_label, create_calibration, is_running, read_calibration,
                                               run_calibration, status_of)
        from mobile.sensitivity_runs import StudyState

        folder = create_calibration(self.config, self.objectives(), temperature=self.temperature(), n_trials=6, name="locked")
        self.assertFalse(is_running(folder))
        outcome = {}
        with mock.patch.dict(os.environ, {"FAKE_SLEEP": "0.5"}):
            worker = threading.Thread(target=lambda: outcome.update(record=run_calibration(folder, StudyState(), parallel=2)))
            worker.start()
            time.sleep(1.0)
            self.assertTrue(is_running(folder))
            self.assertEqual(status_of(folder, read_calibration(folder)), "running")
            with self.assertRaisesRegex(CalibrationError, "running already"):  # Not twice at once
                run_calibration(folder, StudyState())
            worker.join(60)
        self.assertEqual(outcome["record"]["status"], "finished")
        self.assertFalse(is_running(folder))
        # Run by another process that is killed (a GUI closed or crashed): recorded as running, but nothing runs it
        killed = create_calibration(self.config, self.objectives(), temperature=self.temperature(), n_trials=20, name="killed")
        code = ("import sys; sys.path[:0] = [sys.argv[1]]; from mobile.calibration_engine import run_calibration; "
                "from mobile.sensitivity_runs import StudyState; run_calibration(sys.argv[2], StudyState(), parallel=2)")
        other = subprocess.Popen([sys.executable, "-c", code, str(Path(MOBILE) / "python"), str(killed)], start_new_session=True,
                                 env={**os.environ, "FAKE_SLEEP": "0.5"}, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(100):  # Until it holds the lock and has recorded that it runs
            if is_running(killed) and read_calibration(killed)["status"] == "running":
                break
            time.sleep(0.1)
        self.assertTrue(is_running(killed))
        os.killpg(other.pid, signal.SIGKILL)
        other.wait()
        record = read_calibration(killed)
        self.assertEqual((record["status"], status_of(killed, record)), ("running", "interrupted"))
        self.assertIn("(interrupted,", calibration_label(killed, record))
        self.assertEqual(run_calibration(killed, StudyState(), parallel=2)["status"], "finished")  # And it goes on

    def test_status_file_snapshot_and_kept_series(self):
        import optuna

        from mobile.calibration_engine import (SERIES, SNAPSHOT, STATUS, create_calibration, objective_series, read_status, resolved,
                                               run_calibration, trial_comparison, trial_folder)
        from mobile.sensitivity_runs import StudyState

        window = ("2002-07-01", "2002-12-31")
        objectives = [{**objective, "data_raw": str(self.data), "data_steps": []} for objective in self.objectives()]
        folder = create_calibration(self.config, objectives, temperature=self.temperature(), n_trials=4, name="status",
                                    validation=window)
        self.assertIsNone(read_status(folder))  # Never run
        record = run_calibration(folder, StudyState(), parallel=2)
        status = read_status(folder)
        self.assertEqual((status["state"], status["completed"], status["failed"], status["target"]), ("finished", 4, 0, 4))
        self.assertEqual((status["host"], status["pid"]), (socket.gethostname(), os.getpid()))
        self.assertFalse(list(Path(folder).glob(f".{STATUS}*")))  # Written whole: no temporary file left
        # The snapshot is a study of its own, with every trial
        snapshot = optuna.load_study(study_name="calibration", storage=f"sqlite:///{Path(folder) / SNAPSHOT}")
        self.assertEqual(sum(t.state == optuna.trial.TrialState.COMPLETE for t in snapshot.trials), 4)
        # The series compared are kept with each trial, for the whole period and each part: the same as from the output
        objectives = resolved(folder, record)["objectives"]
        here = trial_folder(folder, 1)
        run_dirs = [here / f"seed_{seed}" for seed in record["seeds"]]
        self.assertEqual(len(list((here / SERIES).glob("*.nc"))), 2 * 2 * 3)  # 2 objectives x (model, data) x 3 parts
        for part in (None, "calibration", "validation"):
            model, data = objective_series(objectives[0], run_dirs, window, part)
            shutil.rmtree(run_dirs[0]) if part == "validation" else None  # The last without the output: from what was kept
            kept = trial_comparison(folder, 1, 0, part)
            np.testing.assert_allclose(kept[0].values, model.values)
            np.testing.assert_allclose(kept[1].values, data.values)
            self.assertTrue(kept[0].index.equals(model.index))

    def test_running_elsewhere_and_taking_over(self):
        from mobile.calibration_engine import (STATUS, CalibrationError, _SQUEUE_CACHE, counts, create_calibration, in_squeue,
                                               is_running, open_study, read_calibration, run_calibration, status_of)
        from mobile.sensitivity_runs import StudyState

        folder = create_calibration(self.config, self.objectives(), temperature=self.temperature(), n_trials=3, name="elsewhere")
        study = open_study(folder, read_calibration(folder))
        left = study.ask()  # A trial the other process was running when it ended
        write_calibration_status = lambda **fields: (Path(folder) / STATUS).write_text(json.dumps(
            {"host": "lrdn0042", "pid": 1, "state": "running", "target": 3, "completed": 0, **fields}))
        now = datetime.datetime.now(datetime.timezone.utc)
        # On another computer, without Slurm to ask: by the heartbeat
        write_calibration_status(heartbeat=now.isoformat())
        self.assertTrue(is_running(folder))
        with self.assertRaisesRegex(CalibrationError, "running already: process 1 on lrdn0042, last heard of"):
            run_calibration(folder, StudyState())
        write_calibration_status(heartbeat=(now - datetime.timedelta(minutes=10)).isoformat())
        self.assertFalse(is_running(folder))
        self.assertEqual(status_of(folder, {"status": "running"}), "interrupted")
        # With Slurm: by whether it still lists the job, whatever the heartbeat
        bin_dir = self.root / "slurm"
        bin_dir.mkdir()
        (bin_dir / "squeue").write_text('#!/bin/bash\nfor a in "$@"; do [ "$a" = 77 ] && { echo 77; exit 0; }; done\n'
                                        'echo "slurm_load_jobs error: Invalid job id specified" >&2; exit 1\n')
        (bin_dir / "squeue").chmod(0o755)
        with mock.patch.dict(os.environ, {"PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}):
            _SQUEUE_CACHE.clear()
            self.assertEqual((in_squeue("77"), in_squeue("78")), (True, False))
            write_calibration_status(job="77", heartbeat=(now - datetime.timedelta(hours=2)).isoformat())
            self.assertTrue(is_running(folder))  # Listed: running, though silent for long (e.g. a slow file system)
            write_calibration_status(job="78", heartbeat=now.isoformat())
            self.assertFalse(is_running(folder))  # Not listed: ended, though heard of just now
            record = run_calibration(folder, StudyState(), parallel=1)  # So this one takes over
        self.assertEqual((record["status"], record["completed"], record["failed"]), ("finished", 3, 0))
        ended = open_study(folder, record).trials[left.number]
        self.assertEqual((ended.state.name, ended.user_attrs.get("ended")), ("FAIL", "the process running it ended"))
        self.assertEqual(counts(open_study(folder, record)), (3, 0))  # Not a failure

    def test_failed_trials_are_made_up_for(self):
        from mobile.calibration_engine import create_calibration, run_calibration
        from mobile.sensitivity_runs import StudyState

        # One run at a time, so the runs come in order: the second trial fails twice (its two attempts), the others not
        counter = self.root / "count.txt"
        folder = create_calibration(self.config, self.objectives(), temperature=self.temperature(), n_trials=5, name="made_up")
        with mock.patch.dict(os.environ, {"FAKE_COUNTER": str(counter), "FAKE_FAIL_RUNS": "2 3"}):
            record = run_calibration(folder, StudyState(), parallel=1)
        self.assertEqual((record["status"], record["completed"], record["failed"]), ("finished", 5, 1))
        # Too many failures after a success (more than CRASH_RATE of the trials, at least FAIL_FAST): stopped
        counter.unlink()
        crashing = create_calibration(self.config, self.objectives(), temperature=self.temperature(), n_trials=10, name="crashing")
        with mock.patch.dict(os.environ, {"FAKE_COUNTER": str(counter), "FAKE_FAIL_FROM": "2"}):
            record = run_calibration(crashing, StudyState(), parallel=1)
        self.assertEqual((record["status"], record["completed"], record["failed"]), ("stopped", 1, 4))

    def test_deadline(self):
        from mobile.calibration_engine import create_calibration, read_status, run_calibration
        from mobile.sensitivity_runs import StudyState

        folder = create_calibration(self.config, self.objectives(), temperature=self.temperature(), n_trials=50, name="deadline")
        # A guess of how long a trial takes that does not fit: none starts
        record = run_calibration(folder, StudyState(), parallel=2, deadline=time.time() + 60, trial_seconds=120)
        self.assertEqual((record["status"], record["completed"], record["failed"]), ("stopped at deadline", 0, 0))
        self.assertEqual(read_status(folder)["state"], "stopped at deadline")
        # Then from the time the trials take: as many as fit, all ended by the deadline
        with mock.patch.dict(os.environ, {"FAKE_SLEEP": "0.3"}):
            deadline = time.time() + 4
            record = run_calibration(folder, StudyState(), parallel=2, deadline=deadline)
            ended = time.time()
        self.assertEqual(record["status"], "stopped at deadline")
        self.assertTrue(2 <= record["completed"] < 50, record["completed"])
        self.assertLess(ended, deadline + 0.5)
        record = run_calibration(folder, StudyState(), parallel=4)  # Without one: to the end
        self.assertEqual((record["status"], record["completed"]), ("finished", 50))

    def test_command_line(self):
        import signal
        import subprocess

        from mobile.calibration_engine import create_calibration, read_calibration, read_status

        folder = create_calibration(self.config, self.objectives(), temperature=self.temperature(), n_trials=8, name="batch")
        command = [sys.executable, "-m", "mobile", "calibrate", str(folder)]
        # No compiler: refused while the model is still to be built (a PATH with nothing on it, as the tools found in
        # /usr/bin differ between computers: GitHub's Ubuntu has gfortran there, not nf-config)
        bare = {**os.environ, "PYTHONPATH": str(Path(MOBILE) / "python"), "PATH": "/usr/bin:/bin"}
        nothing = self.root / "empty_path"
        nothing.mkdir()
        refused = subprocess.run(command, env={**bare, "PATH": str(nothing)}, capture_output=True, text=True, timeout=60)
        self.assertEqual(refused.returncode, 1)
        self.assertIn("needed to compile MoBILE: make, gfortran, nf-config, nc-config", refused.stderr)
        environment = {**bare, "PATH": f"{self.stand_in_compilers()}{os.pathsep}/usr/bin:/bin"}
        too_many = subprocess.run([*command, "--parallel", "100000"], env=environment, capture_output=True, text=True, timeout=60)
        self.assertEqual(too_many.returncode, 1)
        self.assertIn("Use --parallel", too_many.stdout)
        # Stopped by SIGTERM, as by Slurm before the end of a job: the runs cancelled, resumable, exit 3
        job = subprocess.Popen([*command, "--parallel", "1"], env={**environment, "FAKE_SLEEP": "0.5"}, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, text=True)
        for _ in range(300):
            if (read_status(folder) or {}).get("completed", 0) >= 1:
                break
            time.sleep(0.1)
        job.send_signal(signal.SIGTERM)
        output = job.communicate(timeout=60)[0]
        self.assertEqual(job.returncode, 3, output)
        self.assertRegex(output, r"trial 0 completed in \dm\d\ds: timing [-0-9.]+, swings [-0-9.e]+ \| Pareto front 1 trials \| 1 of 8 completed")
        self.assertIn("cancelled (SIGTERM)", output)
        self.assertEqual((read_calibration(folder)["status"], read_status(folder)["state"]), ("cancelled", "cancelled"))
        # The same command again goes on to the end: exit 0
        done = subprocess.run([*command, "--parallel", "2"], env=environment, capture_output=True, text=True, timeout=300)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("finished", done.stdout)
        self.assertEqual(read_calibration(folder)["completed"], 8)
        # Its model built and kept, a later run of it (e.g. another job) needs no compiler
        self.assertTrue((Path(folder) / "bin" / "mobile.out").is_file())
        again = subprocess.run(command, env={**bare, "PATH": str(nothing)}, capture_output=True, text=True, timeout=60)
        self.assertEqual(again.returncode, 0, again.stdout + again.stderr)
        self.assertIn("8 of 8 trials completed so far", again.stdout)

    def stand_in_compilers(self):
        """A folder of stand-ins for the tools `mobile` looks for before it builds: the stand-in mobile.sh builds nothing."""
        folder = self.root / "compilers"
        folder.mkdir(exist_ok=True)
        for name in ("make", "gfortran", "nf-config", "nc-config"):
            (folder / name).write_text("#!/bin/bash\n")
            (folder / name).chmod(0o755)
        return folder

    def test_moved_folder(self):
        # As sent to a cluster: the folder elsewhere, its paths relative to it, the observations in it, MoBILE from $MOBILE
        from mobile.calibration_engine import create_calibration, read_calibration, run_calibration, write_calibration
        from mobile.sensitivity_runs import StudyState

        folder = create_calibration(self.config, self.objectives(), temperature=self.temperature(), n_trials=2, name="moved")
        moved = self.root / "elsewhere" / "moved"
        shutil.copytree(folder, moved)
        (moved / "inputs").mkdir(exist_ok=True)
        (moved / "data").mkdir()
        record = read_calibration(moved)
        for key in ("rain_file", "temp_file", "pop_file"):
            shutil.copy(record["run_inputs"][key], moved / "inputs" / Path(record["run_inputs"][key]).name)
            record["run_inputs"][key] = record["setup"]["inputs"][key] = f"inputs/{Path(record['run_inputs'][key]).name}"
        shutil.copy(self.data, moved / "data" / "cases.nc")
        record["objectives"] = [{**objective, "data": "data/cases.nc"} for objective in record["objectives"]]
        record["setup"]["mobile"] = "/nowhere/MoBILE"
        write_calibration(moved, record)
        shutil.rmtree(folder)
        os.rename(self.root / "temperature.nc", self.root / "temperature_gone.nc")  # Not read from where it was
        with mock.patch.dict(os.environ, {"MOBILE": str(self.config.mobile)}):
            result = run_calibration(moved, StudyState(), parallel=1)
        self.assertEqual((result["status"], result["completed"]), ("finished", 2))

    def test_transmission_dying_out_is_infeasible_not_failed(self):
        # The toy has cases only above 18 °C: offsets of the west of -2 °C or lower (with a small gap) leave none anywhere
        from mobile.calibration_engine import (CONSTRAINT, DataError, INFEASIBLE, create_calibration, evaluate, open_study,
                                               read_calibration, resolved, run_calibration, trial_folder, trials_table, best_trials)
        from mobile.calibration_results import results_figure
        from mobile.sensitivity_runs import StudyState

        temperature = {"cells": self.cells, "first": (-5.0, 1.0), "gap": (0.0, 0.5)}
        folder = create_calibration(self.config, self.objectives(), temperature=temperature, n_trials=16, startup_trials=8, name="dying")
        record = run_calibration(folder, StudyState(), parallel=2)
        self.assertEqual((record["status"], record["completed"], record["failed"]), ("finished", 16, 0))  # None failed
        rows = [row for row in trials_table(folder) if row["state"] == "COMPLETE"]
        dead = [row for row in rows if row["infeasible"]]
        self.assertTrue(0 < len(dead) < len(rows), [row["offsets"] for row in rows])
        for row in rows:  # Died out exactly where the toy says (no day above 18 °C in the last year), graded by when
            shifted = self.t2m + np.array([[row["offsets"]["dT_1"], row["offsets"]["dT_2"]]])
            cases = np.flatnonzero((shifted > 18.0).any(axis=(1, 2)))
            last = int(cases[-1]) if len(cases) else -1
            died = len(self.t2m) - 1 - last >= 365
            self.assertEqual(bool(row["infeasible"]), died, row)
            self.assertEqual(row["persistence"]["last"], [last])
            self.assertAlmostEqual(row["violation"], (len(self.t2m) - 1 - last) / len(self.t2m) if died else -1.0)
        never = [row for row in dead if row["violation"] == 1.0]
        self.assertTrue(never, "some trials should have no case at all")
        self.assertEqual(never[0]["infeasible"], "transmission died out: no case at all in 1 of 1 seeds")
        self.assertEqual(never[0]["values"][0], 0.0)  # The correlation of a series that does not vary
        # Kept out of the front, which Optuna's own constraints also know of
        front = best_trials(folder)
        self.assertTrue(front and not any(row["infeasible"] for row in front))
        study = open_study(folder, read_calibration(folder))
        self.assertEqual(study.trials[never[0]["number"]].constraints, {"transmission": 1.0})
        # Control: as before (no flat series allowed), such a trial fails
        here = trial_folder(folder, never[0]["number"])
        with self.assertRaisesRegex(DataError, "not defined for these values"):
            evaluate(resolved(folder, read_calibration(folder))["objectives"], [here / "seed_12345"])
        # The regime of every trial: the toy repeats the same seasons, so the years are alike (CV ~0) while it persists
        self.assertEqual(never[0]["regime"]["fade_out"], 1.0)
        self.assertIsNone(never[0]["regime"]["annual_cv"])  # No cases: not defined
        alive = [row for row in rows if not row["infeasible"] and row["persistence"]["last"][0] == len(self.t2m) - 1]
        self.assertTrue(alive and all(row["regime"]["annual_cv"] < 0.05 for row in alive))
        for kind in ("boundary_cv", "boundary_fade", "boundary_pairs", "distributions", "pareto"):
            results_figure(folder, kind)

    def test_regime_measures(self):
        from mobile.calibration_data import DataError, Observations
        from mobile import calibration_engine

        def run(first, values):
            day = np.arange(np.datetime64(first), np.datetime64(first) + len(values))
            return Observations(shape="dated", values=np.asarray(values, dtype="f8"), index=pd.DataFrame({"start": day, "end": day}))

        def measured(*series):
            by_dir = {f"seed_{k}": member for k, member in enumerate(series)}
            with mock.patch.object(calibration_engine, "model_members", lambda folder, *args: [by_dir[folder]]):
                return calibration_engine.regime(list(by_dir))

        steady = run("2001-01-01", np.full(3 * 365, 1e-3))  # The same cases every day of three years
        self.assertAlmostEqual(measured(steady)["annual_cv"], 0.0)
        self.assertEqual(measured(steady)["fade_out"], 0.0)
        # Outbreaks in the first and third years only, each in its first three months: the second year has none
        days = np.arange(np.datetime64("2001-01-01"), np.datetime64("2004-01-01"))
        outbreaks = np.where(np.isin(days.astype("datetime64[Y]").astype(int) + 1970, (2001, 2003))
                             & ((days.astype("datetime64[M]").astype(int) % 12) < 3), 1e-3, 0.0)
        found = measured(run("2001-01-01", outbreaks))
        annual = np.array([outbreaks[:365].sum(), outbreaks[365:730].sum(), outbreaks[730:].sum()])
        self.assertAlmostEqual(found["annual_cv"], annual.std(ddof=1) / annual.mean())
        self.assertAlmostEqual(found["fade_out"], 30 / 36)  # 6 of the 36 months had cases
        # Only whole years and months: a run from mid-June 2001 to the end of 2003 has two full years, 30 full months
        partial = run("2001-06-15", np.full(len(np.arange(np.datetime64("2001-06-15"), np.datetime64("2004-01-01"))), 1e-3))
        self.assertAlmostEqual(measured(partial)["annual_cv"], 0.0)
        self.assertEqual(measured(steady, run("2001-01-01", outbreaks))["seeds"]["fade_out"], [0.0, 30 / 36])
        self.assertAlmostEqual(measured(steady, run("2001-01-01", outbreaks))["fade_out"], 15 / 36)  # The median of the seeds
        self.assertIsNone(measured(run("2001-01-01", np.full(400, 1e-3)))["annual_cv"])  # One full year: no CV
        with mock.patch.object(calibration_engine, "model_members", mock.Mock(side_effect=DataError("no output"))):
            self.assertIsNone(calibration_engine.regime(["seed_0"]))  # New cases not written

    def test_persistence_is_graded(self):
        from mobile.calibration_data import Observations
        from mobile import calibration_engine

        days = 1000

        def runs(*lasts):
            """Stand-in outputs: one daily series per run, with cases up to the day given (-1: none at all)."""
            by_dir = {}
            for k, last in enumerate(lasts):
                values = np.zeros(days)
                values[:last + 1] = 1e-3
                day = np.arange(np.datetime64("2001-01-01"), np.datetime64("2001-01-01") + days)
                by_dir[f"seed_{k}"] = Observations(shape="dated", values=values, index=pd.DataFrame({"start": day, "end": day}))
            return list(by_dir), lambda folder, *args: [by_dir[folder]]

        objectives = [{"name": "timing", "variable": "Inew", "space": "people", "aggregation": None}]
        for lasts, violation in (((999,), -1.0),             # To the end
                                 ((900,), -1.0),             # Ended 99 days before the end: less than a year, not died out
                                 ((500,), 499 / 1000),       # Died out half way: the share of the run after
                                 ((-1,), 1.0),               # None at all: the farthest
                                 ((500, 999), -1.0),         # One seed of two: not more than half
                                 ((500, 400, 999), np.mean([499 / 1000, 599 / 1000]))):  # Two of three: the mean of those
            folders, members = runs(*lasts)
            with mock.patch.object(calibration_engine, "model_members", members):
                found = calibration_engine.persistence(objectives, folders)
            self.assertAlmostEqual(found["violation"], violation, msg=lasts)
            self.assertEqual(found["last"], list(lasts))
        with mock.patch.object(calibration_engine, "model_members", runs(999)[1]):  # Persisting, but a series did not vary
            found = calibration_engine.persistence(objectives, ["seed_0"], flat=[0])
        self.assertEqual((found["violation"], found["reason"]), (1.0, "the model series of timing does not vary"))

    # A stand-in ssh: runs the command here, in a shell whose HOME is that of the cluster and whose PATH has its Slurm
    FAKE_SSH = """#!/bin/bash
while [ "$1" = "-o" ]; do shift 2; done
host=$1; shift
[ -n "$FAKE_SSH_DENY" ] && { echo "** WARNING: connection is not using a post-quantum key exchange algorithm." >&2;
                              echo "$host: Permission denied (publickey)." >&2; exit 255; }
echo "$*" >> "$FAKE_REMOTE_HOME/commands.txt"
HOME="$FAKE_REMOTE_HOME" PATH="$FAKE_REMOTE_BIN:$PATH" exec bash -c "$*"
"""
    # sbatch runs the job at once, to its end, then says its id; squeue lists what FAKE_SQUEUE says; sacct, that it completed
    FAKE_SLURM = {
        "sbatch": """#!/bin/bash
echo "$@" >> "$HOME/sbatch.txt"
script=${@: -2:1}; folder=${@: -1}
id=$(( $(cat "$HOME/next_id" 2>/dev/null || echo 1000) + 1 )); echo $id > "$HOME/next_id"
[ -z "$FAKE_SQUEUE" ] && SLURM_JOB_ID=$id bash "$script" "$folder" > "$folder/logs/$id.out" 2>&1
echo "$id;leonardo"
""",
        "squeue": """#!/bin/bash
[ -n "$FAKE_SQUEUE" ] && echo "$FAKE_SQUEUE"
true
""",
        "sacct": """#!/bin/bash
for job in $(echo "$5" | tr , ' '); do echo "$job|${FAKE_SACCT:-COMPLETED}"; done
""",
        "scancel": """#!/bin/bash
echo "$@" >> "$HOME/scancel.txt"
""",
    }

    def cluster(self):
        """Settings of a stand-in cluster here: ssh, Slurm and `mobile` in folders of their own."""
        from mobile.cluster import ClusterSettings

        home = self.root / "cluster_home"
        local_bin, remote_bin = self.root / "local_bin", self.root / "remote_bin"
        for folder in (home, local_bin, remote_bin):
            folder.mkdir(exist_ok=True)
        for tool in self.stand_in_compilers().iterdir():  # Those of the cluster, for `mobile calibrate` there
            shutil.copy(tool, remote_bin / tool.name)
        scripts = {local_bin / "ssh": self.FAKE_SSH, **{remote_bin / name: text for name, text in self.FAKE_SLURM.items()},
                   remote_bin / "mobile": f'#!/bin/bash\nPYTHONPATH={Path(MOBILE) / "python"} exec {sys.executable} -m mobile "$@"\n'}
        for path, text in scripts.items():
            path.write_text(text)
            path.chmod(0o755)
        config_dir = self.root / "config_here"
        cached = config_dir / "worldpop" / "Global2000_2020" / "SEN_2012.json"
        cached.parent.mkdir(parents=True)
        cached.write_text((Path(MOBILE) / "python" / "mobile" / "age_structures" / "Global2000_2020" / "SEN_2012.json").read_text())
        patch = mock.patch.dict(os.environ, {"PATH": f"{local_bin}{os.pathsep}{os.environ['PATH']}", "FAKE_REMOTE_HOME": str(home),
                                             "FAKE_REMOTE_BIN": str(remote_bin), "MOBILE_CONFIG_DIR": str(config_dir)})
        patch.start()
        self.addCleanup(patch.stop)
        return ClusterSettings(host="leonardo", folder="~/work/calibration", mobile=str(self.config.mobile), account="", partition="",
                               qos="", time="00:10:00", cpus=2, exclusive=False, setup="# the modules and the venv here"), home

    def test_cluster_send_submit_refresh(self):
        import sqlite3
        from contextlib import closing

        import optuna

        from mobile.calibration_engine import (CalibrationError, SERIES, create_calibration, forget_storage, is_running, open_study,
                                               read_calibration, read_cluster, run_calibration, status_of, trial_comparison,
                                               trial_folder)
        from mobile.cluster import ClusterError, last_log, observation_files, refresh, send, submit
        from mobile.sensitivity_runs import StudyState

        settings, home = self.cluster()
        folder = create_calibration(self.config, self.objectives(), temperature=self.temperature(), n_trials=3, name="sent")
        self.assertEqual(observation_files(folder), [(str(self.data.resolve()), self.data.stat().st_size)])
        with self.assertRaisesRegex(ClusterError, "tick that its observations may be copied"):
            send(folder, settings)
        there = Path(send(folder, settings, cleared=True))
        self.assertEqual(there, home / "work" / "calibration" / "sent")  # ~ as the shell there sees it
        record = json.loads((there / "calibration.json").read_text())
        self.assertEqual({objective["data"] for objective in record["objectives"]}, {"data/objective_0_data_cases.nc", "data/objective_1_data_cases.nc"})
        self.assertEqual(record["run_inputs"]["temp_file"], "inputs/external/temp_file_temperature.nc")
        self.assertTrue((there / "inputs" / "external" / "temp_file_temperature.nc").is_file())
        self.assertTrue((home / ".config" / "mobile" / "worldpop" / "Global2000_2020" / "SEN_2012.json").is_file())
        self.assertEqual(record["setup"]["runs_dir"], str(there))  # No paths of this computer there
        self.assertNotIn("shapes", record["setup"])
        with self.assertRaisesRegex(ClusterError, "sent already"):
            send(folder, settings, cleared=True)
        with self.assertRaisesRegex(CalibrationError, "sent to leonardo"):  # The folder here only mirrors it
            run_calibration(folder, StudyState())
        # The job: runs it there, from that folder alone (the data here moved away), to the end
        os.rename(self.data, self.root / "cases_away.nc")
        job = submit(folder, settings)
        self.assertEqual(job, "1001")
        script = (there / "job.sh").read_text()
        self.assertIn('exec mobile calibrate "$1" --parallel 2', script)
        self.assertIn(f"#SBATCH --output={there}/logs/%j.out", script)
        self.assertNotIn("--account", script)  # Empty: not given
        self.assertEqual(json.loads((there / "calibration.json").read_text())["completed"], 3)
        self.assertFalse((Path(folder) / "optuna.db").stat().st_size and open_study(folder, read_calibration(folder)).trials)
        # Refreshed: the study, the progress, the series of each trial and the log; never the output
        refresh(folder)
        record = read_calibration(folder)
        self.assertEqual((record["status"], record["completed"], status_of(folder, record), is_running(folder)), ("finished", 3, "finished", False))
        self.assertEqual(read_cluster(folder)["jobs"][0]["state"], "COMPLETED")  # As sacct says
        trials = open_study(folder, record).trials
        self.assertEqual(sum(trial.state == optuna.trial.TrialState.COMPLETE for trial in trials), 3)
        self.assertTrue((trial_folder(folder, 2) / SERIES).is_dir())
        self.assertFalse(list(Path(folder).glob("trials/*/seed_*")))
        model, data, *_ = trial_comparison(folder, 2, 0)  # Drawn here from the series kept there
        self.assertEqual(len(model), len(data))
        job_id, tail = last_log(folder)
        self.assertEqual(job_id, "1001")
        self.assertIn("exit 0: done", tail)
        # Refreshed again: the series of trials ended here are not copied again; those missing, or of a trial not ended in
        # the study here (maybe copied half-written), are
        said = []
        refresh(folder, say=said.append)
        self.assertRegex(said[-1], r"^Copying back 0 new trials and the study \([\d.]+ MB\)…$")
        shutil.rmtree(trial_folder(folder, 2) / SERIES)
        forget_storage(folder)
        with closing(sqlite3.connect(Path(folder) / "optuna.db")) as connection, connection:
            connection.execute("UPDATE trials SET state = 'RUNNING' WHERE number = 1")
        refresh(folder, say=said.append)
        self.assertRegex(said[-1], r"^Copying back 2 new trials ")
        self.assertTrue((trial_folder(folder, 2) / SERIES).is_dir())
        refresh(folder, say=said.append)  # The study copied back says trial 1 ended
        self.assertRegex(said[-1], r"^Copying back 0 new trials ")

    def test_cluster_jobs_and_login(self):
        from mobile.calibration_engine import create_calibration, is_running, read_calibration, read_cluster, running_where, status_of
        from mobile.cluster import ClusterError, ClusterSettings, job_script, refresh, send, stop, submit

        settings, home = self.cluster()
        folder = create_calibration(self.config, self.objectives(), temperature=self.temperature(), n_trials=3, name="queued")
        with mock.patch.dict(os.environ, {"FAKE_SSH_DENY": "1"}):
            with self.assertRaisesRegex(ClusterError, r"cannot connect to leonardo: log in to the cluster first.*\(leonardo: Permission denied \(publickey\)\.\)"):
                send(folder, settings, cleared=True)
        send(folder, settings, cleared=True)
        with mock.patch.dict(os.environ, {"FAKE_SQUEUE": "1001 PENDING"}):
            first = submit(folder, settings)
            refresh(folder)
            self.assertEqual((status_of(folder, read_calibration(folder)), is_running(folder)), ("queued", True))
            second = submit(folder, settings)  # After the first
        self.assertIn(f"--dependency=afterany:{first}", (home / "sbatch.txt").read_text().splitlines()[-1])
        self.assertEqual(read_cluster(folder)["jobs"][-1]["after"], first)
        with mock.patch.dict(os.environ, {"FAKE_SQUEUE": f"{second} RUNNING"}):
            refresh(folder)
            self.assertEqual(status_of(folder, read_calibration(folder)), "running")
            self.assertRegex(running_where(folder), rf"on leonardo, job {second} running, .*as of the refresh 0 s ago")
            self.assertEqual(stop(folder), second)
        self.assertEqual((home / "scancel.txt").read_text().strip(), f"--batch --signal=TERM {second}")
        # Submit asks squeue itself: the second has ended since the refresh that listed it, and only another job is listed
        with mock.patch.dict(os.environ, {"FAKE_SQUEUE": "9999 RUNNING"}):
            third = submit(folder, settings)
        self.assertNotIn("--dependency", (home / "sbatch.txt").read_text().splitlines()[-1])
        self.assertEqual([(job["listed"], job.get("after")) for job in read_cluster(folder)["jobs"]],
                         [(False, None), (False, first), (True, None)])
        refresh(folder)  # Ended: sacct says completed, and its status is as written there (not run here)
        self.assertEqual(is_running(folder), False)
        # Exit 3 (stopped before the end, resumable), which Slurm records as FAILED, is said as such; exit 1 is a failure
        logs = home / "work" / "calibration" / "queued" / "logs"
        (logs / f"{first}.out").write_text("Trial 2 failed\nexit 1: see above\n")
        (logs / f"{second}.out").write_text("stopped at deadline\nexit 3: not done: run the same command again to go on\n")
        with mock.patch.dict(os.environ, {"FAKE_SACCT": "FAILED"}):
            refresh(folder)
        self.assertEqual([job["state"] for job in read_cluster(folder)["jobs"]], ["FAILED", "STOPPED (RESUMABLE)", "FAILED"])
        # The script for LEONARDO's DCGP nodes, as the settings default to
        record = read_calibration(folder)
        record["setup"]["run"]["threads"] = 7
        script = job_script(ClusterSettings(), record, "/leonardo_work/try26_garrido/calibration/x")
        for line in ("#SBATCH --account=try26_garrido", "#SBATCH --partition=dcgp_usr_prod", "#SBATCH --cpus-per-task=112",
                     "#SBATCH --exclusive", "#SBATCH --signal=B:TERM@60", "unset PYTHONPATH",
                     "module load python/3.11.7 > /dev/null 2>&1",
                     'exec mobile calibrate "$1" --parallel 16'):
            self.assertIn(line, script)
        with self.assertRaisesRegex(ClusterError, "need 32 CPUs"):
            job_script(replace(ClusterSettings(), parallel=4, cpus=16), {**record, "setup": {**record["setup"], "run": {"threads": 8}}}, "/x")
        # A folder there with too long a path
        long = create_calibration(self.config, self.objectives(), temperature=self.temperature(), n_trials=3, name="long")
        with self.assertRaisesRegex(ClusterError, "choose a shorter folder there"):
            send(long, replace(settings, folder="~/" + "x" * 150), cleared=True)

    def test_cluster_information(self):
        from mobile import cluster
        from mobile.calibration_engine import create_calibration, read_calibration
        from mobile.cluster import ClusterSettings, certificate, cluster_info, info_rows, job_cost, wall_seconds

        settings, home = self.cluster()
        # What LEONARDO's commands said on 11 Nov 2026, in their formats (the usage made up to add to 571 core-hours)
        canned = {
            "saldo": """#!/bin/bash
echo "$*" >> "$HOME/saldo.txt"
echo "account                start         end         total        localCluster   totConsumed     totConsumed     monthTotal     monthConsumed"
echo "                                             (local h)   Consumed(local h)     (local h)               %      (local h)         (local h)"
echo "-----------------------------------------------------------------------------------------------------------------------------------------"
[ "$2" = "-a" ] && [ "$3" = "try26_garrido" ] &&  # Asked per user, it lists no project (LEONARDO, a new account)
echo "try26_garrido       20260923    20261125          7500                 555           555             7.4          3571                 135"
true
""",
            "sacctmgr": """#!/bin/bash
case "$*" in
  *assoc*) echo "try26_garrido||normal,dcgp_qos_dbg"; echo "try26_garrido|dcgp_usr_prod|dcgp_qos_lprod,dcgp_qos_bprod";;
  *qos*) echo "dcgp_qos_dbg|00:30:00|cpu=224,mem=988000M,node=2|1|2";;
esac
""",
            "sacct": """#!/bin/bash
case " $* " in
  *" -a "*) echo "$*" > "$HOME/sacct_usage.txt"; printf "2000000\n55600\n";;
  *) echo "64190103|FAILED|28440"; echo "64192142|FAILED|25920";;
esac
""",
            "sinfo": """#!/bin/bash
printf "idle 80\nmixed 408\nallocated 942\ndrained* 12\n"
""",
            "squeue": """#!/bin/bash
echo "64200001|cal_x|PENDING|0:00|20:00|(Priority)"
""",
        }
        for name, text in canned.items():
            path = self.root / "remote_bin" / name
            path.write_text(text)
            path.chmod(0o755)
        folder = create_calibration(self.config, self.objectives(), temperature=self.temperature(), n_trials=3, name="info")
        cluster._write_cluster(folder, {"host": "leonardo", "folder": "x", "jobs": [{"id": "64190103"}, {"id": "64192142"}]})
        given = replace(settings, account="try26_garrido", qos="dcgp_qos_dbg", partition="dcgp_usr_prod", time="01:00:00", cpus=32)
        sections = cluster_info(given, folder)
        self.assertIn("-S 2026-09-23 -E now", (home / "sacct_usage.txt").read_text())  # From the project's start, as saldo says
        record = {**read_calibration(folder), "completed": 78}
        rows = {what: (value, warning) for what, value, _, warning in info_rows(sections, given, record, today=datetime.date(2026, 11, 12))}
        self.assertEqual(rows["Budget of try26_garrido"], ("555 of 7,500 core-hours used (7.4 %); from 23 Sep 2026 to 25 Nov 2026, "
                                                          "13 days left", True))  # Less than 2 weeks left
        self.assertEqual(rows["Used now by try26_garrido"], ("571 core-hours since 23 Sep 2026: 6,929 left", False))
        # sacct over the whole project timing out (24 s of the earlier 25 on LEONARDO, 12 Nov): said, never as 0 core-hours
        timed = {what: value for what, value, *_ in info_rows({**sections, "usage": ["20260923", "sacct-exit: 124", "0"]}, given)}
        self.assertEqual(timed["Used now by try26_garrido"], "sacct did not answer within 120 s (it is slow over a whole project): Check again later")
        self.assertEqual(rows["Your projects and QOS"][0], "try26_garrido: dcgp_qos_bprod, dcgp_qos_dbg, dcgp_qos_lprod, normal")
        value, warning = rows["QOS dcgp_qos_dbg"]
        self.assertTrue(warning)
        self.assertIn("a job runs at most 00:30:00, you may use at most 224 CPUs, 965 GB of memory, 2 nodes at a time, run at most 1 job at a time, "
                      "queue at most 2. The time limit set, 01:00:00, is longer", value)
        self.assertEqual(rows["This calibration"], ("2 jobs, 15.1 core-hours; 0.19 per completed trial (78 completed, as of the last refresh)", False))
        self.assertEqual(rows["Your jobs"][0], "64200001 cal_x pending 0:00 of 20:00 (Priority)")
        self.assertEqual(rows["Nodes of dcgp_usr_prod"][0], "80 idle, 408 mixed, 942 allocated, 12 other (down, drained, reserved…)")
        # Without an account, QOS or partition: those parts are not asked, and the rest still said
        rows = {what for what, *_ in info_rows(cluster_info(replace(settings, account="", qos="", partition="")), settings)}
        self.assertEqual(rows, {"Budget of try26_garrido", "Your projects and QOS", "Your jobs"})
        self.assertIn("saldo-exit: 0", sections["saldo"])
        self.assertEqual((home / "saldo.txt").read_text().splitlines(), ["-b -a try26_garrido --dcgp", "-b -a try26_garrido"])  # By project, once a Check; --dcgp for a DCGP partition
        # saldo too slow (timeout's exit 124), or not there: said as such, and the usage that needs its start date too
        for code, said in (("124", "saldo did not answer within 120 s for your projects (it is often slow): Check again later"),
                           ("127", "saldo is not there (not CINECA?)")):
            rows = {what: value for what, value, *_ in info_rows({**sections, "saldo": [f"saldo-exit: {code}"], "usage": []}, given)}
            self.assertEqual((rows["Budget"], rows["Used now by try26_garrido"]), (said, "needs the start of the project, from saldo"))
        rows = {what: value for what, value, *_ in info_rows({**sections, "usage": []}, replace(given, account="other"))}  # Not in saldo: no usage
        self.assertEqual(rows["Used now by other"], "not in what saldo listed: is the Account right?")
        # Times and costs
        self.assertEqual([wall_seconds(text) for text in ("00:30:00", "1-00:00:00", "30", "10:00", "UNLIMITED", "")],
                         [1800, 86400, 1800, 600, None, None])
        self.assertEqual(job_cost(replace(settings, cpus=112, time="06:00:00")), 672)
        # The login certificate in the ssh agent, as ssh-keygen shows it
        def run(command, **_):
            out = {"ssh-add": "ssh-ed25519-cert-v01@openssh.com AAAA user\nssh-ed25519 AAAA plain\n",
                   "ssh-keygen": "        Valid: from 2026-11-12T09:00:00 to 2026-11-12T21:00:00\n"}[command[0]]
            return mock.Mock(stdout=out)
        with mock.patch.object(cluster.subprocess, "run", run):
            self.assertEqual(certificate(datetime.datetime(2026, 11, 12, 16, 50)), (4 * 3600 + 600, "valid until 21:00 (4 h 10 min left)"))
            self.assertEqual(certificate(datetime.datetime(2026, 11, 12, 22, 0))[1], "expired at 21:00: log in again")

    def test_regions_share_an_offset(self):
        from mobile.calibration_engine import create_calibration, read_calibration, region_mean, run_calibration, trials_table
        from mobile.calibration_run_ui import offset_cells, regions
        from mobile.plots import regions_figure
        from mobile.sensitivity_runs import StudyState

        # The two cells as one region of a 2° box (38-40°E, 8-10°N): one offset for both, its mean weighted by their people (2:3 here)
        cells = offset_cells(self.config)
        from mobile.cells import cell_areas
        self.assertEqual(round(sum(cell["people"] for cell in cells)), round(float((self.pop * cell_areas(self.root / "pop.nc")).sum())))
        found = regions(cells, 2.0)
        self.assertEqual(len(found), 1)
        region = found[0]
        self.assertEqual((region["lat"], region["lon"], len(region["members"])), (9.0, 39.0, 2))
        self.assertEqual([len(r["members"]) for r in regions(cells, 1.0)], [1, 1])  # Edges on whole degrees: 38-39 and 39-40
        means = self.t2m.mean(axis=0).ravel()
        people = np.array([cell["people"] for cell in sorted(cells, key=lambda c: c["lon"])])
        self.assertAlmostEqual(region["mean"], float(np.average(means, weights=people)), places=4)
        self.assertAlmostEqual(region_mean(self.root / "temperature.nc", self.root / "pop.nc", region), region["mean"], places=4)
        # Boxes of 0.5°: each cell its own region, as one offset per cell
        self.assertEqual([len(r["members"]) for r in regions(cells, 0.5)], [1, 1])
        figure = regions_figure(cells, found, [True], 2.0)
        self.assertEqual(int(np.nanmax(figure.data[0].z)), 0)  # Both cells coloured as region 1
        # With the areas of a shapefile over them: its outline (halo and line) and their names on hovering
        outline = ({"x": [38.6, 39.4, 39.4, 38.6, 38.6, None], "y": [8.6, 8.6, 8.9, 8.9, 8.6, None]}, {"x": [39.0], "y": [8.75], "text": ["A"]})
        with_shapes = regions_figure(cells, found, [True], 2.0, outline)
        self.assertEqual(len(with_shapes.data), len(figure.data) + 3)
        self.assertEqual(list(with_shapes.data[-1].text), ["A"])
        folder = create_calibration(self.config, self.objectives(), temperature={"cells": [region], "first": (-2.0, 2.0)}, n_trials=4,
                                    name="one_region")
        record = run_calibration(folder, StudyState(), parallel=2)
        self.assertEqual(record["status"], "finished")
        self.assertAlmostEqual(read_calibration(folder)["temperature"]["means"][0], region["mean"], places=4)
        row = next(row for row in trials_table(folder) if not row["baseline"])
        with netCDF4.Dataset(folder / "trials" / f"trial_{row['number']:05d}" / "t2m.nc") as data:
            shift = data["temperature"][:] - self.t2m
        np.testing.assert_allclose(shift, row["offsets"]["dT_1"], atol=1e-5)  # Every cell of the region moved by the same dT

    def test_model_parameters(self):
        from mobile.calibration_engine import create_calibration, read_calibration, run_calibration, trials_table
        from mobile.calibration_results import results_figure
        from mobile.sensitivity import SampledParameter
        from mobile.sensitivity_runs import StudyState

        # Calibrated with the offsets, in the units of their sliders: mu per year, b_rate on a log scale
        parameters = [SampledParameter("mu", "uniform", 0.02, 0.04), SampledParameter("b_rate", "loguniform", 0.2, 20.0)]
        folder = create_calibration(self.config, self.objectives(), parameters=parameters, temperature=self.temperature(), n_trials=6,
                                    name="parameters")
        record = run_calibration(folder, StudyState(), parallel=2)
        self.assertEqual(record["status"], "finished")
        self.assertEqual([p["name"] for p in read_calibration(folder)["parameters"]], ["mu", "b_rate"])
        for row in trials_table(folder):
            self.assertTrue(0.02 <= row["params"]["mu"] <= 0.04 and 0.2 <= row["params"]["b_rate"] <= 20.0)
            given = read_params(folder / "trials" / f"trial_{row['number']:05d}" / "seed_12345" / "params.txt")
            self.assertAlmostEqual(float(given["mu"]), row["params"]["mu"] / 365)  # Per day in the model
            self.assertAlmostEqual(float(given["b_rate"]), row["params"]["b_rate"])
        # The distributions: the two offsets, then the two parameters, b_rate on a log scale
        figure = results_figure(folder, "distributions", 0)
        titles = [annotation.text for annotation in figure.layout.annotations]
        self.assertEqual([title.split(":")[0].split(" (")[0] for title in titles], ["dT1", "dT2", "mu", "b_rate"])
        self.assertEqual(figure.layout.xaxis4.title.text, "log10 of b_rate")
        # Parameters alone, without offsets
        alone = create_calibration(self.config, self.objectives(), parameters=parameters[:1], n_trials=3, name="alone")
        self.assertEqual(run_calibration(alone, StudyState(), parallel=2)["status"], "finished")
        self.assertEqual(len(results_figure(alone, "distributions", 0).layout.annotations), 1)

    def test_independent_offsets(self):
        from mobile.calibration_engine import create_calibration, read_calibration, run_calibration, trials_table
        from mobile.sensitivity_runs import StudyState

        folder = create_calibration(self.config, self.objectives(), temperature={**self.temperature(), "first": (-3.0, 3.0), "ordered": False},
                                    n_trials=16, name="independent")
        self.assertEqual(run_calibration(folder, StudyState(), parallel=2)["status"], "finished")
        record = read_calibration(folder)
        self.assertFalse(record["temperature"]["ordered"])
        rows = trials_table(folder)
        start = next(row for row in rows if row["baseline"])
        self.assertEqual(start["offsets"], {"dT_1": 0.0, "dT_2": 0.0})
        self.assertEqual(sorted(start["params"]), ["dT_1", "dT_2"])  # Each sampled on its own, no gap
        means = record["temperature"]["means"]
        for row in rows:
            self.assertTrue(all(-3.0 <= row["offsets"][key] <= 3.0 for key in ("dT_1", "dT_2")))
        # The order can change: the east, warmer by 1.5 °C, cooler than the west in some trials
        self.assertTrue(any(means[1] + row["offsets"]["dT_2"] < means[0] + row["offsets"]["dT_1"] for row in rows))

    def test_earlier_versions_are_not_resumed(self):
        from mobile.calibration_engine import (CalibrationError, calibration_label, create_calibration, read_calibration, run_calibration,
                                               write_calibration)
        from mobile.sensitivity_runs import StudyState

        folder = create_calibration(self.config, self.objectives(), temperature=self.temperature(), n_trials=2, name="old")
        record = read_calibration(folder)
        self.assertNotIn("earlier version", calibration_label(folder, record))
        del record["version"]  # As made before versions
        write_calibration(folder, record)
        self.assertIn("earlier version: cannot be resumed", calibration_label(folder, record))
        with self.assertRaisesRegex(CalibrationError, "earlier version"):
            run_calibration(folder, StudyState())
        self.assertFalse((folder / "trials").exists())  # Nothing was run

    def test_no_start_trial_outside_the_ranges(self):
        from mobile.calibration_engine import baseline

        temperature = {"cells": self.cells, "means": [17.0, 19.0], "first": (-3.0, 3.0), "gap": (0.0, 5.0)}
        self.assertEqual(baseline(temperature), {"dT_1": 0.0, "gap_2": 2.0})
        self.assertIsNone(baseline({**temperature, "first": (0.5, 3.0)}))  # dT_1 = 0 is not allowed
        self.assertIsNone(baseline({**temperature, "gap": (0.0, 1.0)}))   # Their own difference is not allowed

    def test_refused(self):
        from mobile.calibration_engine import CalibrationError, create_calibration

        with self.assertRaisesRegex(CalibrationError, "at least one parameter"):
            create_calibration(self.config, self.objectives())
        with self.assertRaisesRegex(CalibrationError, "unknown metric"):
            create_calibration(self.config, [{**self.objectives()[0], "metric": "nse"}], temperature=self.temperature())
        with self.assertRaisesRegex(CalibrationError, "no cell"):
            create_calibration(self.config, self.objectives(), temperature={**self.temperature(), "cells": [{"lat": 0.0, "lon": 0.0}]},
                               name="nowhere")
        self.assertFalse((self.root / "runs" / "calibration" / "nowhere").exists())


class TestCalibrationModel(unittest.TestCase):
    """The model side of a calibration, and the metrics that compare it with the observations."""

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)

    def test_model_series(self):
        from mobile.calibration_model import default_aggregation, model_series, run_choices
        from mobile.calibration_steps import apply_steps
        from mobile.cells import cell_areas
        days = 59  # January and February 2001
        values = np.zeros((days, 2, 2))
        values[:, 0, 0], values[:, 0, 1], values[:, 1, 0] = 0.001, 0.003, 0.002
        values[:, 1, 1] = np.nan  # Not simulated
        pop = np.array([[100.0, 300.0], [50.0, 999.0]])
        run = fake_run(self.folder / "runs" / "one", values, pop)
        series = model_series(run, "Inew")
        self.assertEqual((series.shape, len(series), series.label(0), series.units, series.aggregation), ("dated", 59, "2001-01-01", "fraction", "sum"))
        # People-weighted over the simulated cells (control: by hand, without the cell that is not simulated)
        people = pop * cell_areas(run / "pop.nc")
        expected = (0.001 * people[0, 0] + 0.003 * people[0, 1] + 0.002 * people[1, 0]) / (people[0, 0] + people[0, 1] + people[1, 0])
        self.assertLess(abs(series.values[0] / (expected) - 1), 1e-6)
        self.assertLess(abs(model_series(run, "Inew", "mean").values[0] / (0.002) - 1), 1e-6)
        self.assertLess(abs(model_series(run, "Inew", "sum").values[0] / (0.006) - 1), 1e-6)
        # Daily amounts per person summed by month: cases per person per month
        months = apply_steps(series, [{"kind": "aggregate", "period": "month", "how": "sum", "complete": True, "days": 1}])
        self.assertLess(abs(months.values[0] / (31 * expected) - 1), 1e-6)
        self.assertEqual(default_aggregation("I", {"units": "fraction"}), "mean")
        # A seed band: one seed, or the mean over the seeds
        band = self.folder / "runs" / "band"
        fake_run(band / "seed_1", values, pop, 1), fake_run(band / "seed_2", values * 3, pop, 2)
        (band / "seed_band.json").write_text(json.dumps({"status": "finished", "date": "2026-11-08T13:00:00", "seeds": [1, 2]}))
        self.assertLess(abs(model_series(band, "Inew", seed=2).values[0] / (3 * expected) - 1), 1e-6)
        self.assertLess(abs(model_series(band, "Inew").values[0] / (2 * expected) - 1), 1e-6)
        # A seed band processed seed by seed: the median, with the range across seeds as a band (control: by hand)
        from mobile.calibration_model import model_members, seed_spread
        members = model_members(band, "Inew")
        spread = seed_spread(members, [{"kind": "aggregate", "period": "month", "how": "sum", "complete": True, "days": 1}])
        january = 31 * expected
        for got, want in ((spread.values[0], 2 * january), (spread.extra["lowest"][0], january), (spread.extra["highest"][0], 3 * january)):
            self.assertLess(abs(got / want - 1), 1e-6)
        self.assertIn("median over the 2 seeds", spread.notes[-1])
        from mobile.plots import comparison_figure, observations_figure
        drawn = observations_figure(spread, "band")
        self.assertEqual([trace.fill for trace in drawn.data], [None, "tonexty", None])
        self.assertIn("range across seeds", drawn.data[1].name)
        paired_labels = [spread.label(i) for i in range(2)]
        shown = comparison_figure(spread, spread, paired_labels, spread.values, spread.values)
        self.assertEqual(sum(trace.fill == "tonexty" for trace in shown.data), 1)
        self.assertIn("median across seeds", shown.data[-1].name)
        self.assertEqual(len(run_choices(self.folder / "runs")), 2)
        # Drivers from the same run, processed on their own: monthly sums of rain in mm per month, a climatology of temperature
        from mobile.calibration_model import driver_series
        rain = driver_series(run, "rain", "month")
        self.assertEqual((len(rain), rain.units), (2, "mm per month"))
        self.assertLess(abs(rain.values[0] / (31 * 2.0) - 1), 1e-6)  # Control: 31 days of 2 mm
        self.assertEqual(len(driver_series(run, "rain", "month", first="2001-02-01")), 1)
        temperature = driver_series(run, "t2m", "as_is")
        self.assertEqual((temperature.units, len(temperature), temperature.aggregation), ("celsius", 59, "mean"))
        from mobile.plots import comparison_figure
        months_model = apply_steps(series, [{"kind": "aggregate", "period": "month", "how": "sum", "complete": True, "days": 1}])
        figure = comparison_figure(months_model, months_model, [months_model.label(i) for i in range(2)], months_model.values, months_model.values,
                                   drivers=[("rain", "Rainfall", rain), ("t2m", "Temperature", driver_series(run, "t2m", "month"))])
        self.assertEqual(len(figure.data), 4)
        self.assertEqual((figure.data[2].xaxis, figure.data[3].xaxis, figure.layout.xaxis2.matches), ("x2", "x3", "x3"))
        self.assertEqual((figure.layout.yaxis2.title.text, figure.layout.yaxis3.title.text), ("mm per month", "celsius"))
        # A run in any folder, for the Model box; a folder that is not a finished run is refused, saying why
        from mobile.calibration_data import DataError
        from mobile.calibration_model import run_elsewhere
        found = run_elsewhere(run)
        self.assertEqual(list(found), [str(run.resolve())])
        self.assertIn(f"in {run.parent.resolve()}", found[str(run.resolve())])
        with self.assertRaisesRegex(DataError, "not a finished run"):
            run_elsewhere(self.folder)
        with self.assertRaisesRegex(DataError, "no folder"):
            run_elsewhere(self.folder / "nowhere")

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root reads any folder")
    def test_unreadable_neighbour(self):
        # A folder that cannot be read, next to the runs (as in /tmp), is skipped, not an error
        from mobile.calibration_model import run_elsewhere
        from mobile.results import list_runs
        pop = np.ones((2, 2))
        run = fake_run(self.folder / "runs" / "one", np.ones((3, 2, 2)), pop)
        locked = self.folder / "runs" / "locked"
        locked.mkdir()
        locked.chmod(0)
        try:
            self.assertEqual(list(list_runs(self.folder / "runs")), [str(run)])
            self.assertEqual(list(run_elsewhere(run)), [str(run.resolve())])
        finally:
            locked.chmod(0o755)

    def test_vector_densities_on_a_twin_axis(self):
        from mobile.calibration_data import DataError
        from mobile.calibration_model import driver_panel, model_series
        from mobile.calibration_steps import apply_steps
        from mobile.plots import comparison_figure
        days = 59
        run = fake_run(self.folder / "runs" / "one", np.full((days, 2, 2), 0.01), np.array([[1.0, 2.0], [3.0, 4.0]]))
        with self.assertRaisesRegex(DataError, "no daily output 'V'.*tick Vector density and Infective vector density"):
            driver_panel(run, "vectors")
        with netCDF4.Dataset(run / "output" / "output.nc", "a") as data:
            vector = data.createGroup("Vector")
            for name, value in (("V", 2.0), ("Vinf", 0.004)):  # Infective vectors, far fewer
                field = vector.createVariable(name, "f4", ("time", "lat", "lon"), fill_value=np.float32(np.nan))
                field.units, field.long_name = "m^-2", name
                field[:] = np.full((days, 2, 2), value)
        panel = driver_panel(run, "vectors", "month", "mean")
        self.assertEqual([label for label, _ in panel], ["Vector density", "Infective vector density"])
        np.testing.assert_allclose([series.values[0] for _, series in panel], [2.0, 0.004], rtol=1e-6)
        monthly = [{"kind": "aggregate", "period": "month", "how": "sum", "complete": True, "days": 1}]
        model = apply_steps(model_series(run, "Inew"), monthly)
        figure = comparison_figure(model, model, [model.label(i) for i in range(len(model))], model.values, model.values,
                                   drivers=[("t2m", "Temperature", driver_panel(run, "t2m", "month", "mean")), ("vectors", "Vector densities", panel)])
        axes = {trace.name: trace.yaxis for trace in figure.data}
        self.assertEqual(len({axes["Vector density"], axes["Infective vector density"], axes["Temperature"]}), 3)  # Its own scale
        right = figure.layout[axes["Infective vector density"].replace("y", "yaxis")]
        self.assertEqual(right.side, "right")
        # The panels zoom together: the time axes of the upper ones follow that of the bottom one
        self.assertEqual((figure.layout.xaxis.matches, figure.layout.xaxis2.matches, figure.layout.xaxis3.matches), ("x3", "x3", None))

    def test_metrics(self):
        import pandas as pd
        from mobile.calibration_data import DataError, import_table
        from mobile.calibration_metrics import metrics, pair
        months = lambda values, start="2001-01": import_table(pd.DataFrame({"d": pd.date_range(f"{start}-01", periods=len(values), freq="MS").strftime("%Y-%m-15"),
                                                                             "v": values}), "dated", "v", "sum", "cases per person", date="d", period="month")
        season = 1 + np.sin(2 * np.pi * np.arange(24) / 12)
        data = months(season)
        # A reporting fraction: scale-free metrics see no difference (control: the RMSE does)
        reported = metrics(*pair(months(0.3 * season), data)[:2])
        self.assertAlmostEqual(reported["rmse_relative"], 0.0)
        self.assertAlmostEqual(reported["correlation"], 1.0)
        self.assertGreater(reported["rmse"], 0.1)
        # The right timing with half the swing: correlation perfect, the relative RMSE is not
        half = metrics(*pair(months(1 + 0.5 * np.sin(2 * np.pi * np.arange(24) / 12)), data)[:2])
        self.assertAlmostEqual(half["correlation"], 1.0)
        self.assertGreater(half["rmse_relative"], 0.2)
        # Six months late: the timing is wrong
        self.assertLess(metrics(*pair(months(1 + np.sin(2 * np.pi * (np.arange(24) - 6) / 12)), data)[:2])["correlation"], -0.9)
        # Only the periods in common, without missing values
        m, d, labels = pair(months(np.r_[season[6:], np.nan]), data)
        self.assertEqual((len(m), labels[0]), (18, "2001-01"))  # 19 months in common, the last missing in the model
        self.assertIsNone(metrics(np.ones(5), np.arange(5.0))["correlation"])
        with self.assertRaisesRegex(DataError, "aggregate the model into the periods of the other"):
            days = import_table(pd.DataFrame({"d": pd.date_range("2001-01-01", periods=60).strftime("%Y-%m-%d"), "v": np.ones(60)}),
                                "dated", "v", "sum", "x", date="d", period="day")
            pair(days, data)
        with self.assertRaisesRegex(DataError, "process them into the same shape"):
            pair(import_table(pd.DataFrame({"y": [2001], "v": [1.0]}), "yearly", "v", "sum", "x", year="y"), data)

if __name__ == "__main__":
    unittest.main()
