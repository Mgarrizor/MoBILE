.. _gui:

Using the GUI
=============

MoBILE comes with a graphical user interface (GUI) that runs in your web browser, on your own computer.
It lets you change model parameters, run the model, and explore the results on a map and in time
series. Under the hood it runs MoBILE exactly as ``utils/run_MOBILE.sh`` does, so every run can also
be repeated from the command line.

Before you start
----------------

The GUI compiles and runs MoBILE on your computer, so first make sure that

- the :ref:`requirements <software>` are installed: a FORTRAN compiler, ``make`` and netCDF-Fortran
  (``nf-config`` and ``nc-config`` must work in a terminal);
- the ``MOBILE`` :ref:`environmental variable <env_var>` points to your copy of the MoBILE repository.

Installing the package
----------------------

The GUI is part of ``mobile``, a Python package (Python 3.11 or newer). We recommend installing it in
its own virtual environment:

.. code-block:: console

   python3 -m venv ~/mobile-env
   source ~/mobile-env/bin/activate
   pip install $MOBILE/python

``pip`` also installs the Python packages it needs. Check the installation with

.. code-block:: console

   mobile help

and open the GUI with the example bundled with MoBILE:

.. code-block:: console

   mobile gui

Your browser opens the GUI. Press **Run**: after about a minute, a map of the daily entomological
inoculation rate over Senegal appears. Close the GUI with its **Close GUI** button.

.. note::

   Activate the environment (``source ~/mobile-env/bin/activate``) in every new terminal before
   using ``mobile``.

Preparing your configuration
----------------------------

A configuration file (YAML) tells the GUI which driving data and settings to use. It replaces the
block of settings at the top of ``run_MOBILE.sh``.

Where to put it
^^^^^^^^^^^^^^^

Make a folder for your study, **outside the MoBILE repository**, and get a copy of the example
configuration in it:

.. code-block:: console

   mkdir -p ~/my_study && cd ~/my_study
   mobile example my_study.yaml

Keep your driving data in or next to this folder. Two rules about paths:

- paths of input files are relative to the folder of the configuration file (absolute paths work
  too, as do environmental variables such as ``$MOBILE``);
- ``runs_dir``, where results are saved, is relative to the folder **from which you start the GUI**.

Paths may not contain spaces, nor be longer than 200 characters.

What to fill in
^^^^^^^^^^^^^^^

.. code-block:: yaml

   runs_dir: runs
   project: My study            # shown at the top of the GUI

   run:
     disID: 1                   # 0: cholera, 1: malaria
     mob: 0                     # mobility, not functional yet
     nstep: 365                 # days to simulate; 0 = the whole driving record
     spin_up: 1                 # 0: none, 1: to tolerance
     nagent: 1000000
     seed: 12345
     threads: 4

   inputs:
     rain_file: data/rain.nc
     temp_file: data/t2m.nc
     pop_file: data/pop.nc
     area_file: data/area.nc
     age_file: data/cumm_age.txt
     const: params.txt

``run``
   As the flags of ``run_MOBILE.sh``. Two of them deserve care:

   - ``nagent``: results depend on the number of humans each agent represents (HA). In the GUI you enter
     HA, and the number of agents follows from it; below 1 there would be more agents than people, and the
     model stops at once. Raising HA to save time changes the answer.
   - ``threads``: a run is only reproducible with the same ``seed`` **and** the same number of threads.

``inputs``
   The four driving fields must follow the units and variable names in the README of MoBILE
   (`Driving data <https://github.com/Mgarrizor/MoBILE#driving-data>`_).
   ``age_file`` is the cumulative age distribution. ``const`` is your parameter file, as
   ``params.txt``: the GUI's parameter sliders start at its values, and a parameter not in it starts
   at the model's default, shown in grey. Optional: ``mortality_file``, ``birthrate_file``,
   ``mortality_time_file``, ``imm_forcing`` (``NONE`` when not used) and ``counterfactual`` (0 or 1).

``period``
   Optional: ``{start: 2013-01-01, end: 2013-12-31}``, the first and last day to simulate, within the days of
   ``rain_file``. Without it the whole driving record is simulated. It replaces ``nstep``.

Everything else, the parameters to change and the fields the model writes, is set in the GUI.

When *Apply setup* is pressed in the GUI, the driving files are checked against each other: the grid, the
days, and the units of rainfall (mm/day) and temperature (°C). Any difference is listed in a warning window.

When the GUI starts, it checks the configuration and lists any problem: a missing file, an unknown
setting, and so on.

Starting the GUI
----------------

From your study folder:

.. code-block:: console

   cd ~/my_study
   mobile gui my_study.yaml

Each run is saved in ``runs/`` there, and can be loaded again from the GUI's list of previous runs.

Where results are saved
-----------------------

Each run has its own folder, ``runs/<date>-<id>/``:

- ``output/output.nc``: the model output;
- ``run.json``: everything needed to compare or repeat the run (settings, parameters, the commit and
  build of MoBILE, the number of threads and the seed);
- ``run.log``: the messages of the model;
- ``run_MOBILE.sh``: the script that ran it. To repeat the run by hand, run ``bash run_MOBILE.sh`` in
  a copy of the folder.

The runs of a seed band are grouped in ``runs/seed_band_<date>-<id>/``.

A sensitivity analysis has its own folder, ``runs/sensitivity/<name>/``, apart from single runs:

- ``sa.json``: what was sampled and how, the setup, and how far the runs got;
- ``samples.txt``: the parameter values, one row per sample;
- ``runs/seed_<seed>/sample_<index>/``: one run folder, as above, for each sample and seed;
- ``metrics/``: what was read from the runs for each way of analysing them, so that analysing them again is quick.

Sensitivity analysis
--------------------

The **Sensitivity analysis (Sobol)** card, in the Parameters tab, runs the model for many combinations of the
parameters you tick, drawn from their distributions (uniform, log-uniform, or normal and log-normal truncated to
their bounds), with the setup applied in the Setup tab. It uses SALib's Sobol method: N base samples give N(2D+2)
runs for D parameters with second-order indices, N(D+2) without. With **Stochastic**, the whole analysis is
repeated for several seeds with the same samples.

The runs are kept: a cancelled analysis resumes where it stopped, and a finished one can be analysed again, for
another variable, period, months or reduction, without running again. The indices can be those of one number per
run (the variable summed, averaged or at its maximum over the days, then averaged or summed over the populated
cells), maps of the indices cell by cell compared with the rainfall and temperature of each cell, or indices month
by month across the cells. **How the indices are calculated**, in the card, explains the numbers. ``python/GUI.md``
in the repository describes every control.
