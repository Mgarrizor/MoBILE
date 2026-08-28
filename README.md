# VECTRI-ABM

VECTRI-ABM: an agent-based model of
disease transmission coupled to the [VECTRI](https://users.ictp.it/~tompkins/vectri/documentation/)
vector-ecology model. The framework resolves individual human agents on a
climate-driven grid, with age-structured diagnostics including
per-timestep symptomatic and asymptomatic incidence & age-dependent acquisition and
waning of immunity. Calibration tools - Sobol sensitivity analysis (SALiB), a genetic
algorithm (Tompkins et al. 2018) and an integration to the Optuna calibration suite are included. Agent
mobility is defined but not yet functional.
Developed at the Abdus Salam International Centre for Theoretical Physics (ICTP),
Trieste, Italy.

> **Mobility is not yet functional.** Agent mobility (gravity and radiation models) is
> defined in the source but not active; it is planned work pending funding.

> **On naming.** The underlying agent-based framework is called **MoBILE**
> (**Mo**bility-**B**ased **I**ntegrated **L**andscape **E**pidemiology), which remains
> the repository name and appears throughout the source (`mobile.sh`, `mobile.out`,
> `$MOBILE`). **VECTRI-ABM** is the disease model built on it — the coupling of that
> framework to VECTRI — and is the name used in the accompanying paper and for citation.

## Requirements

- A Fortran compiler with OpenMP support (gfortran)
- netCDF-Fortran, providing `nf-config` and `nc-config` on your `PATH`
- Optional, profiling only: [gperftools](https://github.com/gperftools/gperftools)

The build queries `nf-config` for the compiler and flags. If that is unavailable on your
system, set `FC`, `INC_FLAGS` and `INC_LIBS` directly at the top of the `Makefile`.

## Build

    make

This produces `mobile.out` in the repository root.

## Run the bundled example

`utils/test_run/` contains everything a run needs — driving data (`area.nc`, `pop.nc`,
`rain.nc`, `t2m.nc`), a parameter file, and `age_structure/cumm_age.txt`, the cumulative
age distribution derived from WorldPop age structures as described in the accompanying
paper — so the model can be exercised without preparing any input of your own:

    export MOBILE=$PWD
    mkdir -p run && cd run
    bash $MOBILE/utils/test_run/run_example.sh

One simulated year over a 140 x 100 grid with 10^6 agents, preceded by an automatic
spin-up. It takes roughly a minute on four threads and writes `example/example.nc`
(~430 MB) plus `example/example.info` recording the commit it was run from.

Output is grouped netCDF: `Human` (prevalence `I`, incident cases `Inew`, entomological
inoculation rate `EIR`, immunity `imm`, agents per cell `Nagent`, humans per agent `HA`),
plus `Vector`, `Hydro` and `Climate`.

The run prints one harmless message, `bash: fetch_age.sh: No such file or directory`.
`mobile.sh` calls that script to derive the cumulative age distribution from WorldPop
rasters; the example ships `age_structure/cumm_age.txt` instead, so the step is not
needed and the run completes normally.

This is a smoke test rather than a scientific configuration. In particular `nagent`
cannot be lowered much: agents are distributed across cells with a `ceiling()`, which
overshoots the allocation by roughly half the number of populated cells until the
per-cell population cap binds — below about 10^6 on this grid, initialisation fails.
`nagent` must scale with the population of the domain, and results depend on the
resulting agent-to-human ratio.

For your own runs, `utils/run_MOBILE.sh` is the general driver; edit the configuration
block at the top (output name, disease, seed, agents, timesteps, spin-up, and the paths
to your driving data). `params.txt` supplies the model parameters read into the `&CONST`
namelist. Thread count is set via `OMP_NUM_THREADS`.

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
| `utils/vectri/` | vendored VECTRI vector-ecology model |
| `utils/test_run/` | driving data for the bundled example |
| `utils/SA_Sobol/`, `utils/Optuna_calibration/` | sensitivity analysis and calibration tooling |

## Citing

See [`CITATION.cff`](CITATION.cff), or use the "Cite this repository" button on GitHub.

## License

GNU General Public License v3.0 — see [`LICENSE.md`](LICENSE.md).
