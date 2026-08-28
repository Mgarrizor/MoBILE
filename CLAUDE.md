# Notes for AI assistants working on this repository

MoBILE is the agent-based framework; VECTRI-ABM is the vector-borne disease model built on it by coupling to VECTRI. The repository keeps the MoBILE name.

## Building and running

- **Do not build or run inside the repository.** `mobile.sh` compiles into the *run* directory, so a run launched from a scratch directory elsewhere leaves the repo clean. Running `make` at the repo root leaves `build/` and `mobile.out` behind.
- `utils/test_run/run_example.sh` is a self-contained smoke test: everything it reads is in `utils/test_run/`. Run it from a scratch directory with `MOBILE` exported.
- `mobile.sh` invokes `bash fetch_age.sh` unconditionally and it is normally absent from the run directory. The resulting "No such file or directory" is harmless when `age_structure/cumm_age.txt` is supplied.

## Configuration that will bite you

- **`nagent` is not a performance dial.** Results depend on the human-to-agent ratio `HA = pop_dens*A_cell/npeop`. Convergence needs HA close to 1; at HA ~ 1.9 the incidence in under-fives is ~18% too high. Lower `nagent` to save time and the answer changes.
- `nagent` also has a floor: agents are handed out per cell with a `ceiling()` in `agents_init`, which overshoots the budget by roughly half the number of populated cells until the per-cell population cap binds. Too low and initialisation runs past `people(nagent)`.
- Runs are **not** bit-identical for a fixed seed. Treat output as one realisation of a stochastic process. This is fixed in a developing branch, but still unfixed in main.

## Reading model output

- `Inew` and `Inew_<age>` count transitions into the **symptomatic** state only — clinical incidence, not all infections.
- `Na_<age>` is a raw **agent** count. Multiply by `HA` for people.
- `EIR` is per person per day; multiply by 365 for the conventional annual rate.
- Age blocks are the 16 non-overlapping bands in `age_blocks` (`mo_const.f90`), upper bounds 1,2,3,4,5,6,7,8,10,12,15,20,30,45,60,80.

## Comparing runs

Check provenance before comparing anything: `md5 mobile.out` in each run directory, and the number of timesteps. Runs from different builds or of different length are not comparable, and mixing them silently produces plausible nonsense.

## Style

- Comments describe the method, not its history. A few lines at most — no bug narratives, no benchmark numbers, no "previously this did X".
- Fortran doc comments use FORD's `!!` post-comment form, on the line after the entity. The docs build from `FORDDocs/` and publish automatically via `.github/workflows/docs.yml`.
