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

The tabs follow the order of the work: **1. Setup**, **2. Parameters & SA**, **3. Results**. The GUI opens on Setup.
The header with the tabs stays in view while the page scrolls, and a tab opens at its top.
The sidebar, always visible below the header, starts runs and loads earlier ones. The **Analysis (to come)** menu and the **Calibration (to come)** tab hold
work that is not implemented yet (Analysis: Time series, Demography, Mobility; Calibration: with the
[Optuna](https://optuna.org/) parameter optimisation suite); the sensitivity analysis is in **2. Parameters & SA**. **Help** has a short
guide, the documentation and the publications on VECTRI and VECTRI-ABM (listed in `mobile/publications.yaml`, where
new ones are added). Hover over ⓘ beside a setting for an explanation.

**Light**, **System** and **Dark** at the top right set the colours of the page and of the plots. *System*
follows the setting of the computer. The choice is kept by the browser. The colours of the data and of the map
are the same in both.

### 1. Setup tab

Everything a run needs that is not a parameter or an output.

- **Run parameters**: project name, model (VECTRI-ABM malaria or cholera), the period to simulate (a start and
  an end date, by default the first and last day of the rainfall file, to which **Reset** returns; the total time is
  printed below them),
  spin-up to equilibrium and threads. A period shorter than the driving data is run on copies of the
  rainfall, temperature and immunity forcing files cut to it, kept in the run folder.
- **Results folder**: where the runs are saved. It does not have to be the folder you started from. Type a path
  or use **Browse**, and to make a new folder, type its name under *New folder in the folder shown* and press
  **Create and open**. It then opens, and **Use this folder** selects it. Names use letters, digits, `.`, `_`
  and `-` only (no spaces), and the folder cannot be inside the MoBILE repository. It takes effect with
  **Apply setup**, and *Earlier runs* in the sidebar then lists the runs in that folder.
- **Driving files**: rainfall, temperature and population density. There is no parameter file: the parameters are
  set in tab 2, and no cell-area file: the model computes the cell areas from the grid of the population file.
- **Age structure (WorldPop)**, in the same card: a **Product**, a **Country** (Sub-Saharan Africa) and a **Year**.
  The products are WorldPop Global 2000–2020 (1 km, unconstrained: people in every land cell) and R2025A (2015–2030,
  1 km, constrained to settled cells; 2025 to 2030 are projections, marked so in the menu, and Eritrea is left out:
  its rasters are about 430 MB a year). By default both are chosen from the start of the period: 2000–2020 before 2015,
  R2025A from 2015, and the year closest to the start (2008 for a run from 2008, 2015 for a run from 2015); the line
  under the menus names them, and a link goes to the product's source. An amber note says that the model does not
  use the sex structure yet: female and male are averaged. The
  first time a country and year are used, **Apply setup** downloads the 36 rasters of WorldPop (18 age groups by sex)
  (2 MB for The Gambia, about 150 MB for Nigeria) and analyses them as `utils/fetch_age.sh` does, with progress and a Cancel button; the result, a few kilobytes, is
  kept in the settings folder (`worldpop/`) and the rasters are deleted. The age file the model reads is written into
  each run folder from it, and recorded in the run's `run.json`; it is never an input. The example's result
  (Senegal 2012, 2000–2020 product) comes with the package, so the example runs without a connection. Type a path or use **Browse**. Optional files (mortality, birth rate, immunity
  forcing, counterfactual demography) are under *Optional files*. The files filled in at first are the
  example that comes with MoBILE (`utils/test_run` in the GitHub repository): Senegal, 2012 to 2014, on a 0.05°
  grid (rainfall CHIRPS, temperature CHIRTS, population WorldPop 2020). A note says so while they are in use.
- **Apply setup**, centred above the region card, checks the settings and switches to the Parameters & SA tab. It also
  checks the driving files against each other (grid, days) and for the units of rainfall (mm/day) and temperature
  (°C); any difference opens a warning window, from which the setup can still be applied.
  Problems are listed under the button. It cannot be used while a run is in progress.
- **Region to simulate** (optional, its own card with its own map of the population density, or of the mean
  rainfall or temperature over the period (all year, a season such as JJA, or one month), to help choose the
  region): the model runs on the **Whole grid** by default, and the map is then only for looking. For a **Subregion**, type its North,
  West, South and East edges in degrees (as in the Copernicus data store), or drag a rectangle on the map; a new
  rectangle replaces the one before, and the draw button of the map toolbar (dotted square) brings drawing back
  after zooming. For a **Single point**, type its latitude and longitude, or click a cell on the map. The cells of
  the region are those with their centre inside it; a point, or a box narrower than a cell, gives the cell it falls
  in. The map outlines these cells (a ring marks a point), and the line under the choice gives their number, how many
  are simulated (with population, and rain and temperature on the first day) and the people in those, as the model counts
  them. The run of a region gets copies of the driving files cut to it; the cut population file keeps the cell bounds
  of the whole grid (`lat_bnds`, `lon_bnds`), from which the model computes the area of the cells of a point or a
  row. The region is part of the setup, applied with **Apply setup**, and the humans per agent in the
  sidebar are then those of the region.
- **Preview driving files** draws a file as a map (rainfall and temperature by day, population density) before you apply it, so mismatched grids show up early. **Dots on the map** mark cells whose daily
  values are plotted below the map, one line per dot. There is one dot to start with, near the middle of the data.
  A click on the map moves the highlighted dot; press **Add dot** and click the map to place another (up to 8,
  each in its own colour). The dots are listed with their coordinates: click a row to highlight its dot, and its
  cross to remove it. The dots stay while you switch between files on the same grid. The preview works while a run
  is in progress.
- **Age structure**, a card of the applied setup: the fitted mortality γ and four figures, as those of
  `utils/fetch_age.sh`: the weight of each year of age with the fit A·exp(−γ·age); the cumulative weights the model
  reads, through those of WorldPop's age groups; the mean share of each age group by sex; and, for each age group, the
  histograms of its share in the people of each 1 km cell (one narrow peak: the same structure everywhere, as the
  model assumes). *How the age structure is computed* gives the steps.

The settings are remembered for the next session in `~/.config/mobile/last_setup.json`.

### 2. Parameters & SA tab

- **Parameters for single runs**: every parameter of the model's `&CONST` namelist, in tabs (Human, Vector, Hydro,
  Demography, Interventions), each with folded sections by theme (e.g. *Immunity acquisition*, *Symptomatic
  probability*). A slider starts at the default compiled into the model. An amber dot marks a moved slider, its
  section and its tab, so a change in a folded section is not missed; **Reset parameters** puts them all back. Rates
  per day such as `mu` are shown per year, and tiny fractions (`wpond_min`, `wperm_default`) as log10 of the value;
  the label says so. Hover over the name of a parameter (or move to it with Tab) for what it does and where it
  comes from. All of this is in `mobile/parameters.yaml`: the default, the range (only 12 ranges are curated so far;
  the others are the default ±50%), the tab, the section and the description of each parameter. The tests compare its
  defaults with the Fortran source, so a default changed in the model, or a parameter added to `&CONST`, must be
  added there too. The parameters of the cholera model and of mobility are not shown and keep their default.
  Under the mortality `mu` (Demography), **Use the fitted mortality** sets it to the γ fitted to the age structure of
  the setup: with births equal to deaths, the default, a population with mortality γ has an age structure of that slope.
- **Outputs**: which fields the next run writes. Age-resolved fields give large files. A sensitivity analysis writes
  the same fields, and only these can be analysed afterwards.
- **Sensitivity analysis (Sobol)**, below: see the next section.

### Sensitivity analysis

How much of the variance of an output each parameter explains, from many runs with the parameters drawn from their
distributions ([SALib](https://salib.readthedocs.io/), Sobol). It uses the setup applied in tab 1, the HA and seed of the sidebar, and every
parameter not sampled at its slider value.

1. **Parameters to sample**: tick at least two, by group. Choose a distribution (uniform, log-uniform, normal or
   log-normal, the last two truncated to the minimum and maximum) and its bounds, which start at the range of the
   slider, in the same units. Normal needs a mean and sd; log-normal those of ln x.
2. **Sobol**: the base samples N, a power of 2, and whether to compute second-order indices (S2, for each pair).
   The number of runs is shown with its formula: N(2D+2) with S2, N(D+2) without, D the parameters sampled.
3. **Stochastic** (amber): repeat the analysis for several seeds, from the sidebar seed up, with the same samples,
   to see how much chance changes the indices. The number of runs is multiplied by the seeds.
4. **Runs at the same time**: each uses the threads of the setup; the line under the number of runs warns when
   they need more cores than the computer has. **Analysis name** (optional) names its folder.
5. **Run analysis** shows the progress (runs done, running, failed, time left); **Cancel** stops it. A single
   Run and an analysis cannot go on at the same time.

**Earlier analyses** lists the analyses in the results folder, with their parameters. **Resume** goes on with a
cancelled one, running only the runs left. The runs are kept, so a finished analysis can be analysed again in other
ways without running again. If the first 3 runs of an analysis all fail, it stops and shows the end of the log of
one: they would all fail alike. Fix the cause and press Resume.

**Analyse the runs** of the analysis chosen under Earlier analyses:

- **Variable**, **Days** (from, to) and **Months** (e.g. only those of the wet season).
- **Over the days**: mean, sum or maximum of each run.
- **Over the cells**:
  - *Mean* or *Sum over the populated cells*: one number per run. Bars of S1 (alone) with ST − S1 (with the others)
    stacked on top, so that the whole bar is ST, with 95% confidence intervals; S2 for each pair; a table and a CSV.
  - *None: a map of the indices*: indices cell by cell, a tab for each parameter, and the index of each cell against
    its mean rainfall and temperature over the same days and its population density (log scale); netCDF.
  - *None, month by month*: the days of each month reduced apart and the indices computed in each cell. For each
    month, a box of the indices of the cells (10th to 90th percentile, with the 25th, 50th and 75th) and a line
    for the indices of the mean over the cells, with 95% intervals; CSV.
- With several seeds, the indices are those of the mean over the seeds, and each seed alone shows as dots (or as
  its range across seeds, on the maps). The share of the variance from chance is the variance across the seeds of
  the same sample over the variance of all the runs.

**Sensitivity by age.** The runs must write at least **Agents** and one more output under *Human, by age* in the
Outputs card (e.g. *New symptomatic cases*): tick them before running the analysis. The Variable menu then has two
more groups:

- *By age band*: an output by age band (the model writes them as rates per person of each band), analysed
  *age band by age band*: the indices in each cell for each of the 17 bands (0, 1, … 8–9, … 80 and over), shown
  as month by month; CSV.
- *Age profile*: the share of the cases under 5 years old, and their mean age, as numbers per run that can be
  analysed in any of the ways above. The cases of a band are its rate times its agents, day by day.

**How the age sensitivities are calculated**, below How the indices are calculated, gives the details.

The first analysis of a variable reads every run, which for thousands of runs takes minutes; what is read is kept,
so analysing it again is quick. **How the indices are calculated**, under the choices, says what the numbers mean.

### Sidebar

- **Run simulation**: **HA** (humans per agent) and **Seed**. The number of agents follows from HA: the people of the simulated
  region over HA, shown under it. Results depend on HA, so keep it fixed when comparing runs. Below 1 there are more
  agents than people and the model stops at once: the line turns red, and Run and Run analysis refuse to start.
  **Seed band** runs several consecutive seeds with the
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

A sensitivity analysis is `<results folder>/sensitivity/<name or date-id>/`, apart from single runs:
`sa.json` (what was sampled and how, the setup, how far the runs got), `samples.txt` (the parameter values, one row
per sample), `inputs/` (the driving files cut once for all the runs, with a region or a period),
`runs/seed_<seed>/sample_<index>/` (one run folder per sample and seed, as above) and `metrics/` (what was read from
the runs for each way of analysing them).

## Good to know

- A run compiles the model, then simulates: the example takes minutes, large grids hours.
- `mobile.sh` modifies the shared `src/` while it compiles, so runs from the same MoBILE source tree compile one at
  a time; once compiled, the runs of an analysis go on side by side.
- With spin-up (`spin_up: 1`), the model needs at least 365 simulated days to build its spin-up climatology: the Setup
  tab says so under the period, and refuses a shorter one, until spin-up is turned off.
- Results depend on the seed and on the number of threads. Keep both fixed to compare runs.
- Mobility is not functional in the model yet.

## Troubleshooting

- *Not found, but needed to compile MoBILE*: install `gfortran`, `make` and netCDF-Fortran (`nf-config`,
  `nc-config`).
- *`ld: library 'System' not found`* at the end of the compilation, on a Mac: no library is missing. gfortran looks
  for the macOS SDK named after the macOS version (`MacOSX27.sdk`), and the Command Line Tools may not have it
  yet when macOS is newer (check with `ls /Library/Developer/CommandLineTools/SDKs`). The GUI and `mobile run`
  give the SDK that is installed (`xcrun --show-sdk-path`) to the run, unless `SDKROOT` is set. To run
  `mobile.sh` or `run_MOBILE.sh` by hand, set it yourself: `export SDKROOT=$(xcrun --show-sdk-path)`. Updating the
  Command Line Tools in System Settings, Software Update (or `xcode-select --install` if they are not installed)
  also helps.
- *runs_dir cannot be inside the MoBILE repository*: you started the GUI inside the repository. Leave it
  and start again from another folder, or choose a results folder outside it in the Setup tab.
- *MoBILE location unknown*: `export MOBILE=/path/to/MoBILE` in the terminal you start `mobile gui` from.
- *The run failed*: the end of its log is shown in the page, the whole log is `<results folder>/<run>/run.log`.
- *Analysis stopped: its first 3 runs all failed twice*: the end of the log of one is shown; the logs are in
  `runs/seed_<seed>/sample_<index>/run.log` of the analysis folder. Common causes: HA below 1 (*More agents than
  people*).
- *Terrain could not be downloaded*: check the connection and turn the switch on again.
- `mobile help` lists all commands, and the Python interface (`mobile.Runner`, `mobile.load_run`).
