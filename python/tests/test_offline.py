"""Checks that need no simulation: python -m unittest discover tests"""

import json
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

from mobile.config import Config, ConfigError, example_config, namelist_names, read_params
from mobile.rundir import create_run_dir, fill_template
from mobile.app import (
    OUTPUT_FLAGS,
    colour_values,
    grid_step,
    units_label,
    logo_files,
    age_choices,
    age_groups,
    cell_envelope,
    next_cells,
    preferred_variable,
    resolve_variable,
    variable_choices,
)
from mobile.basemap import load_basemap
from mobile.results import list_runs, load_run, load_seed_band, write_seed_band
from mobile.runner import ProgressParser

CONFIG = example_config()
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

    def test_slider_needs_a_known_group(self):
        self.assertEqual({spec["group"] for spec in self.config.sliders.values()}, {"Human", "Vector"})
        bad = replace(self.config, sliders={"e_0": {"group": "Other", "min": 0, "max": 1}})
        with self.assertRaises(ConfigError):
            bad.validate()

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
            run_dir = create_run_dir(config.with_params(e_0=0.25), "x")
            script = (run_dir / "run_MOBILE.sh").read_text()
            self.assertRegex(script, r"(?m)^\s*seed=12345$")
            self.assertRegex(script, r"(?m)^\s*const='params.txt'$")
            self.assertRegex(script, r"(?m)^\s*output_file='output.txt'$")
            self.assertRegex(script, r"(?m)^\s*counterfactual=0$")
            self.assertIn("e_0=0.25,", (run_dir / "params.txt").read_text())
            self.assertIn("out_EIR=.true.,", (run_dir / "output.txt").read_text())
            self.assertIn("out_I=.false.,", (run_dir / "output.txt").read_text())
            self.assertTrue((run_dir / "age_structure" / "cumm_age.txt").is_file())


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


if __name__ == "__main__":
    unittest.main()
