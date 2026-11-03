# Using the GUI

The GUI runs on your computer and opens in your browser. It sets up a MoBILE run, runs the real model
(it fills in a copy of `utils/run_MOBILE.sh` for each run) and shows the results on a map. Install it first:
see [README.md](README.md).

## Start and stop

**Always start the GUI from a folder outside the MoBILE repository**, never from inside it:

    export MOBILE=/path/to/MoBILE
    mkdir -p ~/mobile-work && cd ~/mobile-work
    mobile gui

Why: each run compiles the model and writes its results into the results folder, and that folder cannot be
inside the MoBILE repository (the model's scripts refuse it, and it would fill the repository with output).
The folder you start from only sets the default, `runs/` in that folder. Started inside the repository,
the GUI stops with "runs_dir cannot be inside the MoBILE repository". You can pick any other results
folder in the Setup tab.

- The page opens at http://127.0.0.1:8000. If that port is busy, the next free one is used and printed.
- `mobile gui --port 8100` chooses the first port to try, `--no-browser` does not open a window.
- `mobile gui my_config.yaml` starts from a configuration file (`mobile example my_config.yaml` writes a copy
  of the bundled example to edit). Without one, the GUI starts with the settings of your last session, or the
  bundled example the first time.
- Close it with the **Close GUI** button, or Ctrl+C in the terminal. Closing the browser tab does not stop it.

## The page

The sidebar is always visible, and the GUI opens on the Setup tab. The tabs are Setup, Runs, four analysis tabs that are not implemented yet
(Time series, Demography, Mobility, Sensitivity analysis) and Docs.

### Setup tab

Everything a run needs that is not a parameter or an output.

- **Run parameters**: project name, model (VECTRI-ABM malaria or cholera), days to simulate (0: all the
  driving data), spin-up to equilibrium and threads.
- **Results folder**: where the runs are saved. It does not have to be the folder you started from. Type a path
  or use **Browse**, and to make a new folder, type its name under *New folder in the folder shown* and press
  **Create and open**. It then opens, and **Use this folder** selects it. Names use letters, digits, `.`, `_`
  and `-` only (no spaces), and the folder cannot be inside the MoBILE repository. It takes effect with
  **Apply setup**, and the *Previous runs* list then shows the runs in that folder.
- **Driving files**: rainfall, temperature, population density, cell area, cumulative age structure and the
  parameter (`const`) file. Type a path or use **Browse**. Optional files (mortality, birth rate, immunity
  forcing, counterfactual demography) are under *Optional files*.
- **Apply setup** checks the settings and switches to the Runs tab. Problems are listed under the button.
  It cannot be used while a run is in progress.
- **Preview driving files** draws a file as a map (rainfall and temperature by day, population density, age
  structure) before you apply it, so mismatched grids show up early. Click a cell for its daily values.

The settings are remembered for the next session in `~/.config/mobile/last_setup.json`.

### Sidebar

- **Run** and **Cancel** (only active during a run), and **Close GUI** at the bottom. Hover the (i) beside a
  setting for a short explanation. The Runs tab says what to do until there are results.
- **Run name** (optional): the output folder name, letters, digits, `.`, `_`, `-` only.
  Without one, it is named after the date.
- **Number of agents** and **Seed**. The line under the agents shows the mean humans per agent: results depend on
  it, so keep it close to 1 when comparing runs.
- **Seed band**: runs several consecutive seeds with the same parameters, to see the spread between them.
- **Previous runs** and **Load run**: reload a run or seed band from the results folder. Its sliders, outputs
  and setup are restored.
- **Parameters**: sliders by group (Human, Vector, Hydro, Climate). A blue slider starts at its value in the
  parameter file, a grey one (marked *default*) at the model default. Only sliders you move are changed for the
  run. **Reset parameters** puts them all back. Slider ranges are placeholders (the example value ±50%).
- **Outputs**: which fields the next run writes. Age-resolved fields give large files.

### Runs tab

1. Press **Run**. A progress bar shows compiling, spin-up and the day being integrated. **Cancel** stops it.
2. Choose a **Variable** (and an **Age group** for variables by age) and move the **Day** slider, or play
   the days with the buttons beside it.
3. Click a cell on the map for its time series below. Click a second cell to compare. The dotted line marks the
   day on the map.
4. With a seed band, pick which seed is on the map; a third plot shows the median and range across seeds.
5. Colour map, linear or log scale, and minimum and maximum can be set. **Automatic range** goes back to the
   1st to 99th percentile of the whole run. On a log scale, zeros show in the lowest colour.
6. **Terrain** adds shaded relief.

The first time the GUI has a connection, it downloads the map background (Natural Earth) to `~/.cache/mobile`,
and the relief (ETOPO 2022) when Terrain is first turned on. Without a connection the map is plain.

## What a run leaves behind

`<results folder>/<name or date-id>/` (by default `runs/`) holds `output/output.nc` (the results), `run.log`, `run.json` (the record of the
run), `params.txt` and the filled-in `run_MOBILE.sh`. A seed band is `<results folder>/seed_band_<date-id>/seed_<seed>/`.
To repeat a run by hand, run `bash run_MOBILE.sh` in a copy of that folder.

## Good to know

- A run compiles the model, then simulates: the example takes minutes, large grids hours.
- Only one run can use a MoBILE source tree at a time, because `mobile.sh` modifies the shared `src/`.
- Results depend on the seed and on the number of threads. Keep both fixed to compare runs.
- Mobility is not functional in the model yet.

## Troubleshooting

- *Not found, but needed to compile MoBILE*: install `gfortran`, `make` and netCDF-Fortran (`nf-config`,
  `nc-config`).
- *runs_dir cannot be inside the MoBILE repository*: you started the GUI inside the repository. Leave it
  and start again from another folder, or choose a results folder outside it in the Setup tab.
- *MoBILE location unknown*: `export MOBILE=/path/to/MoBILE` in the terminal you start `mobile gui` from.
- *The run failed*: the end of its log is shown in the page, the whole log is `<results folder>/<run>/run.log`.
- *Terrain could not be downloaded*: check the connection and turn the switch on again.
- `mobile help` lists all commands, and the Python interface (`mobile.Runner`, `mobile.load_run`).
