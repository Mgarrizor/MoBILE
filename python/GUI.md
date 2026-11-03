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

The tabs follow the order of the work: **1. Setup**, **2. Parameters**, **3. Results**. The GUI opens on Setup.
The sidebar, always visible, starts runs and loads earlier ones. The **Analysis (to come)** menu holds tabs that
are not implemented yet (Time series, Demography, Mobility, Sensitivity analysis), and **Help** has a short
guide and the documentation. Hover over ⓘ beside a setting for an explanation.

**Light**, **System** and **Dark** at the top right set the colours of the page and of the plots. *System*
follows the setting of the computer. The choice is kept by the browser. The colours of the data and of the map
are the same in both.

### 1. Setup tab

Everything a run needs that is not a parameter or an output.

- **Run parameters**: project name, model (VECTRI-ABM malaria or cholera), days to simulate (0: all the
  driving data), spin-up to equilibrium and threads.
- **Results folder**: where the runs are saved. It does not have to be the folder you started from. Type a path
  or use **Browse**, and to make a new folder, type its name under *New folder in the folder shown* and press
  **Create and open**. It then opens, and **Use this folder** selects it. Names use letters, digits, `.`, `_`
  and `-` only (no spaces), and the folder cannot be inside the MoBILE repository. It takes effect with
  **Apply setup**, and *Earlier runs* in the sidebar then lists the runs in that folder.
- **Driving files**: rainfall, temperature, population density, cell area, cumulative age structure and the
  parameter (`const`) file. Type a path or use **Browse**. Optional files (mortality, birth rate, immunity
  forcing, counterfactual demography) are under *Optional files*. The files filled in at first are the
  example that comes with MoBILE (`utils/test_run` in the GitHub repository): Senegal, 2012 to 2014, on a 0.05°
  grid (rainfall CHIRPS, temperature CHIRTS, population WorldPop 2020). A note says so while they are in use.
- **Apply setup**, at the bottom of the window, checks the settings and switches to the Parameters tab.
  Problems are listed under the button. It cannot be used while a run is in progress.
- **Preview driving files** draws a file as a map (rainfall and temperature by day, population density, age
  structure) before you apply it, so mismatched grids show up early. Click a cell for its daily values.
- **Region to simulate** (optional, in the preview): the model runs on the **Whole grid** by default. For a
  **Subregion**, type its North, West, South and East edges in degrees (as in the Copernicus data store), or
  press **Draw on the map** and drag a rectangle on the preview map. For a **Single point**, type its latitude
  and longitude, or click a cell on the map. The cells of the region are those with their centre inside it; a
  point, or a box narrower than a cell, gives the cell it falls in. The map outlines these cells, and the line
  beside the choice gives their number and their people. The region is part of the setup, applied with **Apply
  setup**, and the humans per agent in the sidebar are then those of the region. A smaller region has fewer
  people, so it needs fewer agents.

The settings are remembered for the next session in `~/.config/mobile/last_setup.json`.

### 2. Parameters tab

- **Model parameters**: sliders by group (Human, Vector, Hydro, Climate). A blue slider starts at its value in
  the parameter file, a grey one (marked *default*) at the model default. Only sliders you move are changed for
  the run. **Reset parameters** puts them all back. Slider ranges are placeholders (the example value ±50%).
  Hover over the name of a parameter (or move to it with Tab) for what it does, the formula it enters and
  where it comes from. The descriptions are in `info` and `source` of each slider in `sliders.yaml`.
- **Outputs**: which fields the next run writes. Age-resolved fields give large files.

### Sidebar

- **Run**: **Number of agents** and **Seed**. The line under the agents shows the mean humans per agent: results
  depend on it, so keep it close to 1 when comparing runs. **Seed band** runs several consecutive seeds with the
  same parameters, to see the spread between them. **Run name** (optional) is the name of the output folder,
  letters, digits, `.`, `_`, `-` only; without one, it is named after the date.
- **Run** starts the run and shows the Results tab. **Cancel** stops it, and can only be pressed during a run.
- **Earlier runs** and **Load run**: reload a run or seed band from the results folder, and show it in the Results
  tab. Its sliders, outputs and setup are restored.
- **Close GUI**, at the bottom, stops the GUI.

### 3. Results tab

Until there are results, the tab says how to get them.

1. Press **Run**. A progress bar above the tabs shows compiling, spin-up and the day being integrated.
2. Choose a **Variable** (and an **Age group** for variables by age) and move the **Day** slider, or play
   the days with the buttons beside it.
3. Click a cell on the map for its time series below. Click a second cell to compare. The dotted line marks the
   day on the map. Drag to zoom in, double-click to see the whole grid again.
4. With a seed band, pick which seed is on the map; a third plot shows the median and range across seeds.
5. **Map display** (closed at first): colour map, linear or log scale, and minimum and maximum. **Automatic range**
   goes back to the 1st to 99th percentile of the whole run. On a log scale, zeros show in the lowest colour.
   **Terrain** adds shaded relief.

The first time the GUI has a connection, it downloads the map background (Natural Earth) to `~/.cache/mobile`,
and the relief (ETOPO 2022) when Terrain is first turned on. Without a connection the map is plain.

## What a run leaves behind

`<results folder>/<name or date-id>/` (by default `runs/`) holds `output/output.nc` (the results), `run.log`, `run.json` (the record of the
run), `params.txt` and the filled-in `run_MOBILE.sh`. A run on a region also holds `inputs/`, the gridded driving
files cut to it, which `run_MOBILE.sh` reads. A seed band is `<results folder>/seed_band_<date-id>/seed_<seed>/`.
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
