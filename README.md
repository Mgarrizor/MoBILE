# VECTRI-ABM

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.22146187.svg)](https://doi.org/10.5281/zenodo.22146187)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)

VECTRI-ABM: an agent-based model of
disease transmission coupled to the [VECTRI](https://users.ictp.it/~tompkins/vectri/documentation/)
vector-ecology model. The framework resolves individual human agents on a
climate-driven grid, with age-structured diagnostics including
per-timestep symptomatic and asymptomatic incidence & age-dependent acquisition and
waning of immunity. Calibration tools - Sobol sensitivity analysis ([SALiB](https://salib.readthedocs.io/en/latest/)), a genetic
algorithm ([Tompkins et al. 2018](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0200638)) and an integration to the [Optuna](https://optuna.readthedocs.io/en/stable/) calibration suite are included. Agent
mobility is defined but not yet functional.  
Developed at the Abdus Salam International Centre for Theoretical Physics (ICTP),
Trieste, Italy.

> [!CAUTION]
> **Mobility is not yet functional.** Agent mobility (gravity and radiation models) is
> defined in the source but not active; it is planned work pending funding.

> [!NOTE]
> **On naming.** The underlying agent-based framework is called **MoBILE**
> (**Mo**bility-**B**ased **I**ntegrated **L**andscape **E**pidemiology), which remains
> the repository name and appears throughout the source (`mobile.sh`, `mobile.out`,
> `$MOBILE`). **VECTRI-ABM** is the vector-borne disease model built on it — the coupling of that
> framework to VECTRI — and is the name used in the accompanying paper and for citation.

## Requirements

- A Fortran compiler with OpenMP support (gfortran)
- netCDF-Fortran, providing `nf-config` and `nc-config` on your `PATH`
- Optional, profiling only: [gperftools](https://github.com/gperftools/gperftools)

The build requires `nf-config` for the compiler and flags. If that is unavailable on your system, set `FC`, `INC_FLAGS` and `INC_LIBS` directly at the top of the `Makefile`.


## VECTRI-ABM: run example

The `utils/test_run/` folder contains everything a run needs — driving data (`area.nc`, `pop.nc`, `rain.nc`, `t2m.nc`), a parameter file, and `age_structure/cumm_age.txt`, the cumulative age distribution derived from WorldPop age structures as described in the accompanying paper — so the model can be tested without preparing any input of your own. Go to the MoBILE folder and do

    export MOBILE=$PWD

then exit this folder and create a **different** one, outside the GitHub repo

    mkdir -p run && cd run

You can now launch the test run as

    bash $MOBILE/utils/test_run/run_example.sh

This is one simulated year over a 140 × 100 grid with 10⁶ agents, preceded by an automatic spin-up. It takes roughly a minute on four threads and writes `example/example.nc` (~430 MB) plus `example/example.info` recording the commit it was run from.

Output is grouped netCDF hierarchies: `Human` (prevalence `I`, incident cases `Inew`, entomological
inoculation rate `EIR`, immunity `imm`, agents per cell `Nagent`, humans per agent `HA`),
plus `Vector`, `Hydro` and `Climate`.

> [!NOTE]
> The run prints one harmless message, `bash: fetch_age.sh: No such file or directory`.
> `mobile.sh` calls that script to derive the cumulative age distribution from WorldPop
> rasters; the example ships `age_structure/cumm_age.txt` instead, so the step is not
> needed and the run completes normally.

> [!WARNING]
> This is a test rather than a realistic configuration. In particular `nagent`
> cannot be lowered much, as results depend on the
> agent-to-human ratio (HA).

For your own runs, `utils/run_MOBILE.sh` is the general driver; edit the configuration
block at the top (output name, disease, seed, agents, timesteps, spin-up, and the paths
to your driving data). `params.txt` supplies the model parameters read into the `&CONST`
namelist. Thread count is set via `OMP_NUM_THREADS`.

> [!CAUTION]
> **Stochasticity.** VECTRI-ABM is a stochastic agent-based model driven by a seeded random
> number generator. In this release, runs repeated with an identical seed are **not
> guaranteed to be bit-identical**: agent updates are distributed across OpenMP threads
> and some accumulations are order-dependent. Results should be interpreted as
> realisations of a stochastic process, and ensembles over seeds are recommended for
> quantitative comparison. Deterministic reproduction is planned work.

## Repository layout

| path | contents |
|---|---|
| `src/` | model source |
| `utils/vectri/` | VECTRI vector-ecology model source files |
| `utils/test_run/` | driving data for the run example |
| `utils/SA_Sobol/`, `utils/Optuna_calibration/` | sensitivity analysis and calibration tools |

## Citing

See [`CITATION.cff`](CITATION.cff), or use the "Cite this repository" button on GitHub.

Archived on Zenodo. The concept DOI [10.5281/zenodo.22146187](https://doi.org/10.5281/zenodo.22146187)
always resolves to the latest version; cite the version DOI
[10.5281/zenodo.22146188](https://doi.org/10.5281/zenodo.22146188) to pin to `v1.0.0`.

A paper describing VECTRI-ABM is in preparation. Until then, please cite the
software record above; this page will be updated with the article reference on
publication.

## License

GNU General Public License v3.0 — see [`LICENSE.md`](LICENSE.md).
