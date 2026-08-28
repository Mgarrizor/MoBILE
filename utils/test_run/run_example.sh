#!/bin/bash
# Self-contained MoBILE example: one simulated year on the bundled driving data.
#
#   export MOBILE=/path/to/MoBILE
#   mkdir -p run && cd run
#   bash $MOBILE/utils/test_run/run_example.sh
#
# nagent must stay near 1e6: below that, agent initialisation overruns its allocation.

set -euo pipefail
[ -n "${MOBILE:-}" ] || { echo "set MOBILE first" >&2; exit 1; }

DATA="${MOBILE}/utils/test_run"

cp -f "${DATA}/params.txt" params.txt
mkdir -p age_structure
cp -f "${DATA}/age_structure/cumm_age.txt" age_structure/cumm_age.txt
echo "MoBILE example, commit $(git -C "${MOBILE}" rev-parse --short HEAD 2>/dev/null || echo unknown)" > example.info

export OMP_NUM_THREADS="${OMP_NUM_THREADS:-4}"

bash "${MOBILE}/mobile.sh" \
    -o example -d 1 -n 365 -s 12345 -u 1 -a 1000000 -m 0 \
    -r "${DATA}/rain.nc" -t "${DATA}/t2m.nc" \
    -p "${DATA}/pop.nc" -x "${DATA}/area.nc" \
    -c params.txt -l namelist.nml -i NONE -v 1
