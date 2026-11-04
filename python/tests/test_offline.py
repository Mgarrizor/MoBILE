"""Checks that need no simulation: python -m unittest discover tests"""

import json
import math
import os
import re
import socket
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

from mobile.config import (
    SLIDER_GROUPS,
    Config,
    ConfigError,
    default_params,
    default_sliders,
    example_config,
    namelist_names,
    read_params,
)
from mobile.rundir import create_run_dir, fill_template
from mobile.app import free_port
from mobile.layout import OUTPUT_FLAGS, logo_files
from mobile.outcome import Outcome, RunState, run_label, run_name_problem
from mobile.plots import (
    MAX_DOTS, add_dot, age_figure, cell_envelope, colour_values, default_dot, grid_step, map_figure, move_dot, next_cells,
    remove_dot, units_label,
)
from mobile.setup_ui import setup_problems
from mobile.variables import age_choices, age_groups, preferred_variable, resolve_variable, variable_choices
from mobile.basemap import load_basemap
from mobile.driving import field_limits, mean_age, open_field, read_age
from mobile.results import list_runs, load_run, load_seed_band, write_seed_band
from mobile.setup import (
    create_folder, from_fields, from_manifest, list_folder, load_setup, region_from_fields, region_mode, save_setup, start_folder,
)
from mobile.grid import pop_coordinates, read_grid
from mobile.region import axis_range, cut_inputs, region_problems
from mobile.runner import ProgressParser, macos_sdk, run_environment

CONFIG = example_config()


def fortran_defaults(mobile):
    """Compiled-in values of the slider parameters: the malaria case of const_disease, then VECTRI's
    init_constants for the default vector (ivec=0). Each assignment is evaluated in order."""
    def assignments(text):
        for line in text.splitlines():
            code = line.split("!")[0].strip()
            match = re.match(r"^([A-Za-z_]\w*)\s*=\s*(.+)$", code)
            if match:
                yield match.group(1), match.group(2)

    const = Path(mobile, "src", "mo_const.f90").read_text()
    malaria = const[const.index("subroutine const_disease"):]
    malaria = malaria[re.search(r"case\s*\(1\)", malaria).end():re.search(r"case\s*\(2\)", malaria).start()]
    vectri = Path(mobile, "utils", "vectri", "mo_constants.f90").read_text()
    vectri = vectri[vectri.index("SUBROUTINE init_constants") if "SUBROUTINE init_constants" in vectri else vectri.lower().index("subroutine init_constants"):]
    start = re.search(r"SELECT\s+CASE\s*\(\s*ivec\s*\)", vectri, re.I)
    case0 = vectri[start.end():]
    case0 = case0[re.search(r"CASE\s*\(\s*0\s*\)", case0, re.I).end():re.search(r"CASE\s*\(\s*1\s*\)", case0, re.I).start()]
    values = {}
    for text in (malaria, vectri[:start.start()], case0):
        for name, expression in assignments(text):
            try:
                values[name] = float(eval(expression.replace("log(", "math.log("), {"math": math}, dict(values)))
            except Exception:
                continue
    return values
MOBILE = os.environ["MOBILE"]


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

    def test_standard_sliders(self):
        sliders = default_sliders()
        self.assertEqual(len(sliders), 12)
        self.assertTrue(set(sliders) <= namelist_names(MOBILE, "CONST"))
        self.assertTrue(all(spec["group"] in SLIDER_GROUPS for spec in sliders.values()))
        self.assertTrue(all(spec["min"] < spec["max"] for spec in sliders.values()))
        # Each is explained on hovering over it
        self.assertTrue(all(spec.get("info") and spec.get("source") for spec in sliders.values()))

    def test_default_params_match_the_source(self):
        self.assertEqual(set(default_params()), set(default_sliders()))
        source = fortran_defaults(MOBILE)
        for name, value in default_params().items():
            self.assertAlmostEqual(float(value), source[name], msg=f"{name}: default_params.txt {value}, source {source[name]}")

    def test_fortran_defaults_detects_a_change(self):
        # Control: a default changed in a copy of the source is found
        with tempfile.TemporaryDirectory() as copy:
            for path in ("src/mo_const.f90", "utils/vectri/mo_constants.f90"):
                (Path(copy) / path).parent.mkdir(parents=True, exist_ok=True)
                text = Path(MOBILE, path).read_text()
                (Path(copy) / path).write_text(text.replace("k_star   = 10", "k_star   = 12") if "mo_const.f90" in path else text)
            self.assertEqual(fortran_defaults(copy)["k_star"], 12.0)
            self.assertEqual(fortran_defaults(copy)["e1"], 0.1)

    def test_configuration_has_only_the_essentials(self):
        path = Path(os.getcwd()) / "old.yaml"
        path.write_text(example_config().read_text() + "\nsliders: {}\noutput: [out_EIR]\n")
        with self.assertRaisesRegex(ConfigError, "set in the GUI"):
            Config.load(path)

    def test_override_keeps_other_values_verbatim(self):
        base = read_params(self.config.inputs["const"])
        final = self.config.with_params(e_0=0.25).final_params()
        self.assertEqual(final["e_0"], "0.25")
        del base["e_0"], final["e_0"]
        self.assertEqual(base, final)

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

    def test_fields_give_a_config(self):
        files = {**self.files, "mortality_file": "", "imm_forcing": "  "}
        config = from_fields(MOBILE, " Study ", "results", self.run, files)
        self.assertEqual(config.project, "Study")
        self.assertEqual(config.runs_dir, (self.folder / "results").resolve())
        self.assertEqual((config.inputs["mortality_file"], config.inputs["imm_forcing"]), ("NONE", "NONE"))
        # Number boxes give floats
        self.assertEqual(from_fields(MOBILE, "", "runs", {**self.run, "nstep": 365.0}, self.files).run["nstep"], 365)

    def test_problems_are_listed_with_the_labels_of_the_panel(self):
        with self.assertRaises(ConfigError) as caught:
            from_fields(MOBILE, "", "runs", self.run, {**self.files, "rain_file": "missing.nc", "pop_file": ""})
        problems = setup_problems(caught.exception)
        self.assertTrue(any(line.startswith("Rainfall: not found") for line in problems), problems)
        self.assertTrue(any(line.startswith("Population density: not found") for line in problems), problems)

    def test_remembered_between_sessions(self):
        self.assertIsNone(load_setup(MOBILE))
        config = from_fields(MOBILE, "Study", "runs", self.run, self.files)
        save_setup(config)
        self.assertEqual(load_setup(MOBILE), config)
        # Not valid any more, e.g. a file moved: as if there were none
        saved = self.folder / "settings" / "last_setup.json"
        saved.write_text(saved.read_text().replace("rain.nc", "moved.nc"))
        self.assertIsNone(load_setup(MOBILE))

    def test_restored_from_a_run(self):
        current = from_fields(MOBILE, "Study", "elsewhere", self.run, self.files)
        manifest = {"run": {**self.run, "nagent": 5000}, "inputs": self.files}
        restored = from_manifest(manifest, current)
        self.assertEqual(restored.run["nagent"], 5000)
        self.assertEqual((restored.project, restored.runs_dir), (current.project, current.runs_dir))

    def test_file_browser(self):
        (self.folder / "sub").mkdir()
        (self.folder / ".hidden").mkdir()
        for name in ("b.nc", "a.NC", "notes.txt", "data.csv"):
            (self.folder / name).touch()
        self.assertEqual(list_folder(self.folder, "netcdf"), (["settings", "sub"] if (self.folder / "settings").exists() else ["sub"], ["a.NC", "b.nc"]))
        self.assertEqual(list_folder(self.folder, "text")[1], ["data.csv", "notes.txt"])
        self.assertEqual(list_folder(self.folder, "folder")[1], [])
        self.assertEqual(start_folder(str(self.folder / "b.nc")), self.folder.resolve())
        self.assertEqual(start_folder(""), Path.home())

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
            from_fields(MOBILE, "Study", str(Path(MOBILE) / "runs"), self.run, self.files)


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

    def test_age_structure(self):
        import numpy as np
        ages, fraction, cumulative = read_age(self.example / "age_structure" / "cumm_age.txt")
        self.assertEqual((ages[0], ages[-1]), (0, len(cumulative) - 1))
        self.assertAlmostEqual(float(fraction.sum()), float(cumulative[-1]))
        self.assertEqual(fraction[0], cumulative[0])
        # As many people at each year of age from 0 to 9: a mean of 5 years
        self.assertAlmostEqual(mean_age(np.arange(10), np.full(10, 0.1)), 5.0)
        figure = age_figure(ages, fraction, cumulative, "cumm_age.txt")
        self.assertEqual(figure.layout.yaxis2.type, "log")
        self.assertEqual([trace.yaxis or "y" for trace in figure.data], ["y", "y", "y", "y2"])

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
        self.assertEqual(units_label("day^-1"), "[day^-1]")
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
        whole = read_grid(self.config.inputs["pop_file"], self.config.inputs["area_file"])
        part = read_grid(self.config.inputs["pop_file"], self.config.inputs["area_file"], self.box)
        self.assertEqual(part["mask"].shape, (12, 16))
        self.assertTrue(0 < part["people"] < whole["people"])
        point = read_grid(self.config.inputs["pop_file"], self.config.inputs["area_file"],
                          {"north": 14.69, "west": -17.44, "south": 14.69, "east": -17.44})
        self.assertEqual(point["mask"].shape, (1, 1))
        self.assertIsNone(read_grid(self.config.inputs["pop_file"], self.config.inputs["area_file"],
                                    {"north": 5.0, "west": 0.0, "south": 4.0, "east": 1.0}))

    def test_files_cut_to_a_region(self):
        import netCDF4
        import numpy as np
        import xarray as xr

        paths = cut_inputs(self.config.inputs, self.box, self.folder / "inputs", pop_coordinates(self.config.inputs["pop_file"]))
        self.assertEqual(set(paths), {"rain_file", "temp_file", "pop_file", "area_file"})
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
        config = from_fields(MOBILE, "Study", "runs", dict(self.config.run), files, self.box)
        save_setup(config)
        self.assertEqual(load_setup(MOBILE).region, self.box)
        manifest = {"run": dict(config.run), "inputs": files, "region": self.box}
        self.assertEqual(from_manifest(manifest, replace(config, region=None)).region, self.box)
        # Runs from before regions have none
        self.assertIsNone(from_manifest({"run": dict(config.run), "inputs": files}, config).region)
        written = self.folder / "with_region.yaml"
        written.write_text(CONFIG.read_text().replace("$MOBILE", MOBILE).replace("runs_dir: runs", "runs_dir: runs\nregion: {north: 14.6, west: -17.2, south: 14.0, east: -16.4}"))
        self.assertEqual(Config.load(written).region, self.box)


if __name__ == "__main__":
    unittest.main()
