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
The sidebar, always visible below the header, starts runs and loads earlier ones. The **Analysis (to come)** menu holds
work that is not implemented yet (Time series, Demography, Mobility), and the **Calibration (in development)** tab, so
far, its Data box; the sensitivity analysis is in **2. Parameters & SA**. **Help** has a short
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
- **What the driving files must be**, folded above the cards: the table of the README of MoBILE for the GUI (variable
  names, units, time axis, and how to put each file on the model grid with CDO), the coordinates, what the GUI does
  not need, and, under *Why these choices*, why conservative remapping and when `fracarea` or `destarea`. An amber note
  says that only a file you make with a single latitude or longitude needs cell bounds; regions cut in the GUI keep them.
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
- **Shapefile of areas (optional)**, in the same card: areas such as districts or villages, each named on hovering. They
  are drawn on the results map after Apply and, with the **Shapefile** switch that appears beside them once a shapefile
  is in the box (off at first), on the region map and the driving-files preview, also before Apply. Choose the `.shp` (with its `.shx`, `.dbf` and `.prj` next to
  it) or a `.zip` holding them. Any coordinates: they are converted to longitude and latitude with the `.prj` (pyproj);
  without one, coordinates in degrees are taken as longitude and latitude, with a note. **Areas named by** a field of
  the table (at first the one with the most different values) and, optionally, **Merged by** another, e.g. villages
  into their districts; merging drops the slivers under 1,000 m² left between areas that do not quite meet. The maps
  open on the grid and all the areas. The model does not use them; the setup and each run's `run.json` record them as
  `shapes: {file, name, merge}`, also in a configuration file. A shapefile moved since is left out, and the rest of the
  setup still loads.
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
   Run and an analysis cannot go on at the same time. The model is built once, by the first run, and kept in the
   analysis folder (`bin/mobile.out`, its checksum in `sa.json`); the other runs, and those of a resumed analysis,
   run it as it is (`mobile.sh -E`), side by side, without building again.

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
3. Click a cell on the map for its time series below (it is marked at the centre of the cell, wherever in it you click, also on the outline of an area of a shapefile). Click a second cell to compare. The dotted line marks the
   day on the map. Drag to zoom in, double-click to see the whole grid again.
4. With a seed band, pick which seed is on the map; a third plot shows the median and range across seeds.
5. **Map display** (closed at first): colour map, linear or log scale, and minimum and maximum. **Automatic range**
   goes back to the 1st to 99th percentile of the whole run. On a log scale, zeros show in the lowest colour.
   **Terrain** lays the relief over the map as a shading (slopes facing away from the light, from the northwest, darker; those facing it lighter; flat ground and the sea unchanged), so that it shows where there are data too; its detail follows the size of the area, so a small region gets as much as a large one.

The first time the GUI has a connection, it downloads the map background (Natural Earth) to `~/.cache/mobile`,
and the relief (ETOPO 2022) when Terrain is first turned on. Without a connection the map is plain.

### Calibration tab (in development)

Calibration compares the model with observations, to tune its parameters with [Optuna](https://optuna.org/). The tab
has a **Model** box and a **Data** box side by side, each with its own processing steps, and **Model and data** below,
which compares them (the objectives and Optuna come next).

**Steps**: a column at the right of the tab (on screens 992 px wide or more) shows the steps of a calibration as boxes joined by arrows, from Setup applied to Results, and stays in view as the page scrolls. Each box is grey while its step is to do, amber while it is going on or needs attention (e.g. a calibration interrupted, or not comparable yet) and green once it is done, says which in words, and gives a short note (e.g. "running on leonardo, 37 of 300 trials"). Clicking a box scrolls to its card; Setup applied opens tab 1. The steps from Calibration created on are those of the calibration running here, or else of the one chosen under Calibrations. A switch at the top says which calibration the steps follow: **This calibration** (the one chosen under Calibrations, or running: what it was made from is stored in it, so its steps up to What to calibrate are done, with notes from its record) or **A new one** (the steps of the form, as you prepare a calibration; Calibration created, Run and Results to do). Choosing a calibration under Calibrations makes them follow it; loading data, choosing a run in the Model box or adding an objective makes them follow a new one; the switch changes it by hand. Collapsed, a C or N above the squares says which. The » button at its top collapses it to the right into a narrow rail of numbered squares in the same colours (a step to do has a dashed border; hover a square for its title and state; « opens it again); the browser remembers the choice.

The **Model** box takes an output of a finished run from the results folder (**Refresh** lists runs made since), or of a
run in any other folder: type it under **Or a run in another folder**, or **Browse**, and press **Use this run** (the
comparison only reads its outputs, and the setup does not change; **Earlier runs** in the sidebar stays on the results
folder). Then choose the **Output** (as in the Results tab), how to put the cells together each day (**Over the cells
(each day)**: the mean weighted by the people of each cell, which gives the value per person of the whole region for
per-person outputs such as new cases; a plain mean; or a sum; a run on a point has one cell), and, for a seed band, one
seed or all of them. Over time, only the steps decide: an **Aggregate** step is pre-filled with the sum for amounts per
day (new cases, bites: summed by month they give the amount per month) and with the mean for states (prevalence,
densities), and its menu can change it. An amber note says when an amount per day is averaged, which gives an average
per day instead of the amount per period. An objective takes the steps exactly as they are then, and its description
lists them (e.g. "then sum by month"). It becomes a daily series in the same form as the data, processed by its own steps, as
below, with its own plot and **Compare with**. With all the seeds of a band, each seed is processed by the steps, and
the plot and the comparison show their **median** with their **range** (lowest to highest seed) as a shaded band, as the
seed bands of the Results tab (of the processed values, e.g. of monthly sums); the metrics use the median. Dated values with an uncertainty, in either box, show it as a shaded band too.

The **Data** box:

1. Type the path of a file of observations, or **Browse**, and press **Load**. A file in the standard netCDF form of the
   GUI loads at once; a table (CSV, or text separated by blanks, as written by R) opens an import form.
2. **Import**: say what the values are (dated, a climatology of calendar months or of seasons, yearly, by age band, or a single value),
   which column holds them, whether they add up (counts, e.g. cases) or are averaged (rates, prevalences), their units,
   and the columns of their shape: for dated values a date per row (standing for the period that contains it, e.g. a
   mid-month date for that month) or a first and last day. Optionally an uncertainty column, and other columns to keep,
   such as the population. Rows repeated exactly are kept once, rows giving different values for the same period are
   refused, and gaps and missing values are reported.
3. **Processing** is a list of steps you build, applied in order to the values loaded: choose a step under the list and
   press **Add step**; each step can be changed, moved up or down (↑ ↓) or removed (×), and the plot, the table and the
   notes follow at once. The steps:
   - **Aggregate into longer periods**: week, month, quarter, season (DJF, MAM, JJA, SON; December counts in the DJF of
     the next year), year, or a number of days, by sum, day-weighted mean, median, minimum or maximum. With **Complete
     periods only** (the default) a period the values do not cover entirely, or with a missing value, is left out;
     without it, it is kept with its coverage as a column.
   - **Arithmetic** with a kept column or a number: divide (e.g. cases per person, with the population, which takes
     away its growth: the model's population does not grow), multiply, add, subtract.
   - **Select**: a window of time, or chosen months, seasons, years or age bands (e.g. without June and July).
   - **Climatology** by calendar month or by season: the mean over the years, with their spread as error bars. From
     monthly values a season is the mean month of the season; for seasonal totals, aggregate into seasons (sum) first.
   - **Transform**: natural log or log10 (with an offset, e.g. 1 for counts with zeros), standardise, anomaly from the
     mean, moving average.
   - **Frequency filter**: low, high or band pass, with the cut-off periods in days, months or years (a Butterworth filter
     of order 4, run forward and backward, so nothing shifts in time). The cut-off is gradual: half the amplitude is kept
     at the cut-off period, so to remove the annual cycle cut at about 2 years. The filter starts up at each end: values
     within about two of the longest periods kept from each end are less reliable, and a note says how far. Missing
   values and missing periods do not stop it: **Interpolate short gaps** fills gaps of up to N values (3 at first) by a
   straight line only for the filter to run, and puts them back as missing after; **Filter each stretch separately**
   interpolates nothing. Either way longer gaps split the series into stretches filtered separately, stretches too
   short for the cut-off stay missing, and the notes and the step say what was done. Data are never filled in.
   - **Combine** with another loaded data set of the same coordinates: sum, mean or difference. Load several files to
     combine them; **Data set shown** picks the one whose steps are edited.
4. **Compare with**, above the plot, draws an earlier stage with the result: the values loaded, or after any step but
   the last. With the same shape and units it is overlaid in grey (e.g. before and after a filter); otherwise it is in a
   second panel below, sharing the time axis if both are dated (e.g. cases before dividing by the population, or the
   months before a climatology), so values in different units never share an axis.
5. The plot and the table show the result; **Save as standard netCDF** writes it to `calibration/data/` in the results
   folder. The standard file has the values with their units and how they add up, their periods (CF `time_bnds`),
   calendar months, seasons, years or age bands, any uncertainty and other columns, the notes of what was done and the
   steps themselves, so they can be seen and applied again (e.g. to the model output, next).

Once a run and dated observations are both loaded, the Model and Data boxes cut them, as loaded, to the years both
cover (e.g. data for 1975–2025 and a run for 1985–2004 are both cut to 1985–2004) before their steps, so that
statistics such as a climatology cover the same years on both sides; each box and the text under the comparison say
the period. (Observations loaded as a climatology or yearly are not cut, nor the data sets a Combine step takes.)

**Model and data** pairs the two on the periods (or months, seasons, years, age bands) they share, leaving out pairs
with a missing value on either side, and says what to change when they cannot be paired (e.g. monthly data and a daily
model output: aggregate the model by month). It plots both and gives the metrics, with the number of pairs:

| Metric | What it says |
|---|---|
| RMSE | root mean square of model − data, in the units of the data |
| RMSE of the series each divided by its mean | scale-free: the timing and the size of the swings, whatever the level (e.g. the share of cases reported) |
| Correlation | scale-free: the timing only; 1 for the same timing, 0 for none, −1 for the opposite |
| Bias | mean of model − data, in the units of the data |

The RMSE of standardised series is not given: it carries the same information as the correlation. **Scale the model
to the mean of the data** multiplies the model on the plot only, to compare timing by eye; the legend gives the factor.
If the units of the two differ by name, an amber note asks to check that they are the same quantity.

**Possible drivers** draws rainfall and temperature in panels below, as the model read them, and the vector densities
the run gave (each the mean over the simulated cells of the run chosen in the Model box), within the periods the model
and the data share and on the same time axis: zooming in one panel zooms them all. The vector density is at the left
of its panel and the infective vector density, much lower, on its own scale at the right; they need Vector density and
Infective vector density ticked in the Outputs card when the run is made. Each is processed on its own, on the spot: into periods (as they are, week, month, season or year), by a
statistic (sum, mean, minimum, maximum; monthly sums of rain are in mm per month), and optionally as a climatology by
month. They are for looking only: they do not enter the metrics.

**Add as objective**, under the comparison, makes it an objective of the calibration: the observations as loaded and the
steps of the Data box (saved in `calibration/data/` of the results folder, with the observations as processed now), the
output, cells and steps of the Model box, and a metric. Each trial cuts its output and the observations to the period
they share before the steps, as the comparison does. If a step of the Data box combines other data sets, only the
observations as processed now are kept, not cut again by each trial, and the objective's description says so.
The correlation is maximised, the RMSEs minimised, the size of the bias minimised. Add several, e.g. the monthly series with the correlation (timing), then, with a climatology step in both boxes, the relative RMSE (season).

**Calibration with Optuna** runs the model many times with the setup applied, the HA and seed of the sidebar and the
sliders, each time with other values of what is calibrated, and keeps the trials that do best on all the objectives
together (the Pareto front):

- **Validation window** (a switch under the objectives) splits the period the model and the data share in two, to
  test the calibrated model on years it did not see:
  - the **validation window**, a block of years given by its first and last day (at first the last five years). Its
    data are never used to calibrate: each trial is scored on it too, with the same metrics, only to show how well it
    does on years left out;
  - the **calibration window**, the rest of the period. The calibration uses only the data of these years: each trial
    is scored on them, and Optuna chooses the next trials from those scores.

  Both are cut before the steps of the Model and Data boxes, so e.g. a climatology objective is that of the
  calibration window only. With the switch on, the Model and data card gives the metrics of all the years and of each
  window, and marks both windows on its plot with the bars described below. It needs objectives that keep the observations as loaded (those added since the cut to the common period:
  add older ones again).
- **Temperature offsets**, **one per cell** or **one per region**, the cells in each box of a size you give (e.g. 0.5°,
  with edges on multiples of it: the cells of a coarser grid, as when finer driving files were made from coarser ones).
  The cells of a region share its offset and keep their differences; its mean is that of its cells weighted by their
  people (where people live). At most 20 cells or regions are calibrated, of a setup of at most 5,000 simulated cells.
  A map shows the cells in the colour of their region, numbered as in the table, grey if not ticked; with a
  **Shapefile** switch when the applied setup has one, to draw its areas over them. The table lists
  the cells or regions with their mean temperature over the setup period and their people, from the coolest to the
  warmest. The cells ticked are shifted: with one, by dT₁ only;
  with more, the first by dT₁ and each next one by a gap of at least 0 above the one before (the gap range is asked
  for then), so the order of their temperatures is kept in every trial. Cells not ticked keep the temperatures of the
  file. Each trial writes its own temperature file.
- **Model parameters**, by group as on the Parameters tab: tick a parameter to calibrate it, sampled uniformly or
  log-uniformly (for ranges over orders of magnitude) within a range in the units of its slider, at first the range of
  the slider; those not ticked keep their slider value. They can be calibrated with the offsets, or alone.
- **Optuna**: the sampler (TPE, random or NSGA-II, with a link to its documentation), the trials and the start-up
  trials drawn at random. **Runs**: seeds per trial (the objectives then compare the median of the seeds, each
  processed), threads per run (at first those of the setup; kept with the calibration, as results depend on them),
  runs at the same time (at first as many as fit in the cores), and a name. The runs write the outputs of the Outputs card and those the
  objectives were made from. The model is built once, by the first run.
- **Run calibration** shows the progress; **Cancel** stops it, and **Resume here**, under Calibrations, goes on with it on this computer,
  also in a new GUI and after the GUI was closed or crashed: it is then listed as **interrupted** (recorded as running,
  but no process runs it any more). A calibration runs in one process at a time: Resume refuses one that another GUI or
  script is running. A resumed calibration keeps its threads per run, and runs as many at a time as fit in the cores
  with them. **Where transmission dies out**: a trial whose model series does not vary (no cases, so e.g. a correlation
  is not defined) does not fail: it completes as **infeasible**, kept out of the Pareto front and of the best, drawn as
  grey rings in the plot of the objectives. A trial is infeasible when transmission died out (no positive value of the
  objectives' outputs in the last 365 days of the run, in more than half its seeds) or a model series did not vary.
  How far it is from persisting is given to Optuna with it (the share of the run after the last case: just above 0 if
  it died out at the very end, 1 if there were no cases at all), so the sampler learns where the boundary between dying
  out and persisting is and searches along it, instead of losing those trials. Its objectives get the values of a
  series that does not vary (correlation 0, the relative RMSE of a constant series). Every trial records when its last
  case was, in each seed. It goes on until as many trials have **completed** as asked for: a trial that fails is made up for by
  another. It stops if its first 3 trials all fail, or more than one in ten of the trials asked for (at least 3).
  Trials left running by a process that ended (the GUI closed, a job killed) are not counted as failures.
- **Without the GUI**, e.g. in a batch job on a cluster: `mobile calibrate <folder>` runs or continues it, one line per
  trial, and stops cleanly before the end of a Slurm job (no trial is started that would not end 2 minutes before it,
  judged by how long trials take) or on SIGTERM / Ctrl+C; run the same command again to go on (`mobile help` has the
  options and exit codes). The process running a calibration writes `status.json` in its folder, at least every
  minute: a calibration run by another process, on this computer or another, is shown as running ("by another
  process: job 123 on lrdn0042, last heard of 40 s ago, 17 of 100 trials completed") and drawn again as it goes on.
  On another computer it counts as running while Slurm lists its job, or, where Slurm cannot be asked, while its
  status is less than 5 minutes old.
  The calibration running, or the one chosen, is drawn below: each objective trial by trial with the best so far, the
  Pareto front with the offsets and parameters of each trial and the mean temperatures they give, and with a validation
  window its scores on it, in grey (sorted by trial, by an objective or by a validation score, high to low or low to
  high), in a box of its own a trial of the front against the data of an
  objective (the model scaled to the mean of the data) with its **Possible drivers**, and below it, in a box of its own, where the
  calibration started: its first trial, with no temperature offset (when the ranges allow it), processed and scored like
  every other trial, with its **Possible drivers** (rainfall, temperature and vector densities of its run, as in the
  Model and data card) in panels below that zoom together. The runs of a calibration always write the vector densities
  for this. With a validation window, semi-transparent bars along the top of these plots mark the calibration window
  (green) and the validation window (purple), and their titles give the trial's validation scores; an objective that
  is not a dated series, e.g. a climatology, is drawn for the calibration window only, as scored.
- **Create only** makes the calibration without running it, and chooses it under Calibrations: run it here with
  **Resume here**, send it to a cluster (below), or run it with `mobile calibrate`.
- **Use as template**, under Calibrations, fills the card and the objectives from the calibration chosen, for a new
  one: its objectives (those whose observations are still where they were), what it calibrates and the ranges (its
  cells or regions found again on the setup now), the validation window, the sampler, trials, start-up trials, seeds
  (the first one in the sidebar) and threads per run, and a new name (e.g. look_2). Change what you like, then Create
  only or Run calibration; the calibration chosen is not changed. It says what it could not fill: another setup
  (apply it in tab 1), sliders that differ from its fixed parameters, another number of agents.
- The settings **kept with the calibration** (and so used wherever it runs, here or on a cluster) are labelled so;
  **Runs at the same time**, labelled **this computer**, is not kept: a job on a cluster takes those of its Cluster
  settings. With TPE, fewer start-up trials than runs at the same time are warned of: the sampler would suggest trials
  while almost none have ended.
- **Run on LEONARDO (CINECA)**, under Calibrations, a Slurm cluster, for the calibration chosen there: **Send** copies its folder to the
  cluster (into the folder there of the Cluster settings), with the driving files and the observations it uses, its
  paths made relative to it, and its age structure (compute nodes have no internet); its observations are listed and
  copied only once you tick that they may be. **Submit job** writes a batch script there and submits it: one node,
  `mobile calibrate` with as many runs at a time as fit in the CPUs with the calibration's threads per run; a job
  submitted while another is listed waits for it (`--dependency=afterany`). Close the GUI if you like. **Refresh**
  copies back the status, a snapshot of the study, the series each trial compared and the job logs (never the model
  output), and asks Slurm about the jobs: the views below then show it as for a calibration run here, with the end of
  the log of the last job. **Stop job** asks a running job to stop as at its time limit (resumable: submit again), or
  cancels a queued one. While a calibration is on a cluster, the copy here only shows it: it is not run here. Every
  action uses `ssh -o BatchMode=yes <host>`: log in first (e.g. CINECA's certificate of the day), or it says so at
  once. The **Cluster settings** (host, folder there, MoBILE there, setup lines, account, partition, QOS, time limit,
  CPUs, whole node, runs at the same time, a guess of how long a trial takes) each have an ⓘ and what to put; they
  are kept for the next session. Defaults: CINECA LEONARDO, a DCGP node of 112 cores, where 16 runs × 7 threads per
  run did best for Senegal 1998–2003 (9.85 M agents); other setups may differ.
- **Results**, for the calibration running or chosen, its figure chosen from a menu, of the objective chosen where the
  figure is of one, with what it shows and a link to Optuna's documentation: the **distributions of the calibrated
  values**, each offset and model parameter (log-uniform ones on a log scale), over all the trials, the best tenth by the objective and the Pareto front (a narrow spread of the best means
  the data tell the offset well; a wide one, that they hardly do), and Optuna's figures: the **Pareto front**,
  **parameter importances** (PED-ANOVA, turned for objectives that are maximised), **slice**, **parallel
  coordinates**, **contour**, **rank**, the **empirical distribution** of the objective, and the **timeline** of the
  trials; and **epidemic or endemic**: where between the two the trials are, by two measures that do not depend on the
  number of cases or the site, from the new cases of each run (always written by a calibration), the median over its
  seeds: the **year-to-year variability** (coefficient of variation of the cases of each full calendar year: low when
  endemic, high when outbreak years alternate with quiet ones) and the **fade-out** share (months with no new case: 0
  when transmission never stops). Each against every calibrated value, and the trials over each pair of calibrated
  values coloured by their fade-out share; trials where transmission died out in red. They are recorded with every
  trial, not optimised: no regime is imposed on the calibration. Optuna's figures show what it samples, dT₁ and the gaps; the offsets of the cells follow from them. Its folder, `calibration/<name>/` in the
  results folder, holds `calibration.json`, the Optuna study (`optuna.db`, and `optuna.snapshot.db`, a copy that can be
  copied while it runs), `status.json`, the model (`bin/`) and the trials, each with the series its objectives compared
  (`series/`), from which its plots are drawn. A
  calibration made by an earlier version of the engine is listed with "earlier version: cannot be resumed": it can be
  looked at, not run further.

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
