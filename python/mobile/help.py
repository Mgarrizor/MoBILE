"""What `mobile help` and `mobile.help()` print."""

TEXT = """\
mobile: run MoBILE from Python or a terminal, and explore it in a local app.

BEFORE THE FIRST RUN
  1. gfortran, make, netCDF-Fortran (nf-config, nc-config) must be installed.
  2. Get the MoBILE source code and tell the package where it is:
         export MOBILE=/path/to/MoBILE
     Add that line to ~/.zshrc or ~/.bashrc to keep it.

IN A TERMINAL
  mobile app                 Open the app in your browser, using the example
                             bundled with MoBILE. Stop it with its Close app
                             button or Ctrl+C.
  mobile app my_config.yaml  The same with your own configuration.
  mobile run my_config.yaml  Run the model once, without the app.
      --set e_0=0.25            Change a parameter of &CONST
      --run seed=1 nagent=2000000
                                Change a run setting
      --name my_run             Name of the run folder
  mobile example my_config.yaml
                             Write a copy of the example configuration to edit:
                             driving data, run settings, sliders, output.
  mobile help                This text.

  Run these from any folder outside the MoBILE repository. Each run creates a
  folder runs/<date>-<id>/ under the current folder, with the output in
  output/output.nc, the log in run.log and the record of the run in run.json.
  A seed band from the app is one folder runs/seed_band_<date>-<id>/ with a
  folder seed_<seed>/ like that for each seed.
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

Results depend on the seed AND the number of threads. Keep both fixed to compare runs.
"""


def show():
    print(TEXT, end="")
