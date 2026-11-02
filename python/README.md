# mobile

Run MoBILE from Python or a terminal, and explore it in a GUI in your browser.
It fills in a copy of MoBILE's `utils/run_MOBILE.sh` for each run, so the model runs exactly as it does by hand.

## Install

MoBILE needs `gfortran`, `make` and netCDF-Fortran (`nf-config`, `nc-config`), which pip cannot install.

    git clone https://github.com/Mgarrizor/MoBILE.git
    export MOBILE=$PWD/MoBILE            # add to ~/.zshrc or ~/.bashrc to keep it

    python3.11 -m venv mobile-env        # Python 3.11 or newer
    source mobile-env/bin/activate
    pip install $MOBILE/python           # pip also installs the Python dependencies

## Use

From any folder outside the MoBILE repository:

    mobile gui      # opens the GUI in your browser, with MoBILE's example; close it with its Close GUI button
    mobile help     # all commands, and how to use your own configuration

Documentation: the model and its use at https://mobile-ictp.readthedocs.io, the source code at
https://mgarrizor.github.io/MoBILE/.

In the GUI, press Run, then click a cell on the map to see its time series. Earlier runs in the `runs/` folder of the
current folder, including seed bands, can be loaded again from the list in the sidebar, which also sets the sliders to
their values.

The first time the GUI opens with a connection, it downloads the map background (land, lakes, rivers, borders) from
[Natural Earth](https://www.naturalearthdata.com/) to `~/.cache/mobile`, and the relief from ETOPO 2022 when its Terrain
switch is first turned on. Without a connection, it shows a plain map.
