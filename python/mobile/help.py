"""What `mobile help` and `mobile.help()` print."""

TEXT = """\
mobile: run MoBILE from Python or a terminal, and explore it in a GUI in your browser.

BEFORE THE FIRST RUN
  1. gfortran, make, netCDF-Fortran (nf-config, nc-config) must be installed.
  2. Get the MoBILE source code and tell the package where it is:
         export MOBILE=/path/to/MoBILE
     Add that line to ~/.zshrc or ~/.bashrc to keep it.

IN A TERMINAL
  mobile gui                 Open the GUI in your browser, using the example
                             bundled with MoBILE. Stop it with its Close GUI
                             button or Ctrl+C.
  mobile gui my_config.yaml  The same with your own configuration.
  mobile run my_config.yaml  Run the model once, without the app.
      --set e_0=0.25            Change a parameter of &CONST
      --run seed=1 nagent=2000000
                                Change a run setting
      --name my_run             Name of the run folder
  mobile example my_config.yaml
                             Write a copy of the example configuration to edit:
                             driving data and run settings. Parameters and
                             outputs are then set in the GUI.
  mobile calibrate <folder>  Run or continue a calibration made in the GUI,
                             without it, e.g. in a batch job on a cluster:
                             one line per trial, a summary at the end.
      --parallel 16             Runs at the same time (default: the cores
                                this process may use / threads per run)
      --end-time 2026-11-12T08:00
                                Start no trial that cannot end 2 min before
                                then (default: the end of the Slurm job)
      --trial-minutes 20        How long a trial takes, until 10 have
      --mobile /path/to/MoBILE  The clone (default: the calibration's, else
                                $MOBILE)
                             Exit 0 when done; 3 when stopped before the
                             deadline or by SIGTERM/Ctrl+C (run it again to go
                             on); 1 on failures or errors. In a job script,
                             start it with `exec` so that it gets the signal.
  mobile help                This text.

  Run these from a folder OUTSIDE the MoBILE repository, never inside it: the
  results folder cannot be in the repository. Each run creates a
  folder runs/<date>-<id>/ under the current folder (in the GUI, another results
  folder can be chosen or made in the Setup tab), with the output in
  output/output.nc, the log in run.log and the record of the run in run.json.
  A seed band from the app is one folder runs/seed_band_<date>-<id>/ with a
  folder seed_<seed>/ like that for each seed. A sensitivity analysis from the
  app is runs/sensitivity/<name>/: sa.json (what was sampled and how),
  samples.txt (the values, one row per sample) and one run folder like that
  per sample and seed in runs/seed_<seed>/sample_<index>/.
  To repeat a run by hand, run `bash run_MOBILE.sh` in a copy of that folder.

IN PYTHON
  import mobile
  config = mobile.Config.load("my_config.yaml").with_params(e_0=0.25)
  result = mobile.Runner(config).run(on_progress=print)
  result.status              finished, failed or cancelled
  result.open("EIR")         xarray DataArray (time, lat, lon)
  mobile.list_runs("runs")   The finished runs and seed bands in a folder
  mobile.load_run("runs/<folder>")
                             A run from earlier, used like `result` above
  mobile.load_seed_band("runs/<seed_band_folder>")
                             A seed band from earlier: one such result per seed

  A sensitivity analysis from the app, analysed again:
  from mobile.sensitivity import Metric
  from mobile.sensitivity_runs import list_studies, read_study
  from mobile.sensitivity_results import analyse_study
  folder = next(iter(list_studies("runs")))       The newest analysis
  result = analyse_study(folder, read_study(folder), Metric("EIR", time="sum", space="mean"))
  result["parameters"], result["mean"]["S1"], result["mean"]["ST"]
                             Sobol indices, with S1_conf and ST_conf

Results depend on the seed AND the number of threads. Keep both fixed to compare runs.
"""


def show():
    print(TEXT, end="")
