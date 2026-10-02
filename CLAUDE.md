# Notes for AI assistants working on this repository

## Building and running

- **Do not build or run inside the repository.** `mobile.sh` compiles into the *run* directory, so a run launched from a scratch directory elsewhere leaves the repo clean. Running `make` at the repo root leaves `build/` and `mobile.out` behind.
- `utils/test_run/run_example.sh` is a self-contained run test: everything it reads is provided in `utils/test_run/`. Run it from a scratch directory with the `MOBILE` environmental variable exported.
- `mobile.sh` invokes `bash fetch_age.sh` unconditionally and it is normally absent from the run directory. The resulting "No such file or directory" is harmless when `age_structure/cumm_age.txt` is supplied, as is the case of the run test.

## Configuration

- **`nagent` is very important.** Results depend on the human-to-agent ratio `HA = pop_dens*A_cell/npeop`. Convergence needs HA close to 1; at HA ~ 1.9 the incidence in under-fives is ~18% too high. Lower `nagent` to save time and the answer changes. The model is not resolution independent (yet) - a "sub-agent" scheme needs to be developed. 
- `nagent` also has a floor: agents are handed out per cell with a `ceiling()` in `agents_init`, which overshoots the budget by roughly half the number of populated cells until the per-cell population cap binds. Too low and initialisation runs past `people(nagent)`.
- Runs are bit-identical for a fixed seed AND fixed number of threads.

## Reading model output

- `Inew` and `Inew_<age>` count transitions into the **symptomatic** state only — clinical incidence, not all infections.
- `Na_<age>` is a raw **agent** count. Multiply by `HA` for people.
- `EIR` is per person per day; multiply by 365 for the conventional annual rate.
- Age blocks are the 16 non-overlapping bands in `age_blocks` (`mo_const.f90`), upper bounds 1,2,3,4,5,6,7,8,10,12,15,20,30,45,60,80.

## Comparing runs

Check provenance before comparing anything: `md5 mobile.out` in each run directory, and the number of timesteps. Runs from different builds or of different length are not comparable.

## Style

- Source code comments should describe the method, not its history, unless this is needed to understand a particular method. A few lines at most — no bug narratives, no benchmark numbers, no "previously this did X".
- Fortran doc comments use FORD's `!!` post-comment form, on the line after the entity. The docs build from `FORDDocs/` and publish automatically via `.github/workflows/docs.yml`.

## Discussion and disagreement

- Argue a position on its merits, and drop it the moment it stops holding. When a criticism you made turns out to be wrong, say so in one line and move on. Do not restate it in a narrower form, do not defend the fragment that survives, do not explain how the text could have been read the way you read it. That is defensiveness, and it costs the reader time.
- Disagreement is welcome when it rests on something checkable — a number, a file, a definition. Verify it first, then state it once.
