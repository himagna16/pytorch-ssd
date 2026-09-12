#!/usr/bin/env bash
# Build the complete 14-cell MATTE baseline and score it with the UNMODIFIED
# scoreboard.py.
#
# Two things this script is careful about:
#   1. scoreboard.py WRITES metrics.json into every run directory it scores.
#      The Sep 13 stability run's runs/ are committed evidence, so they are
#      COPIED into a scratch suite, never scored in place.
#   2. scoreboard.py groups runs by cell_id.  The two halves use disjoint cell
#      ids (stability: A/B cells; this run: C/D/E/F cells), so a single suite
#      directory merges them correctly with no renaming.
#
# Usage: score_merged.sh WORK_DIR
#   WORK_DIR/runs/  is built from scratch; WORK_DIR must not be inside docs/.
set -euo pipefail
WORK=$1
REPO=/Users/saimaruvada/Downloads/drone/pytorch_ssd
HERE=$REPO/tools/crazysim_macos
P=/Users/saimaruvada/Downloads/drone/trainenv/bin/python
STAB=$REPO/docs/eval_results/2026-09-13-stability/data/matte_suite/runs
NEW=$REPO/docs/eval_results/2026-09-13-matte-baseline/runs

rm -rf "$WORK"; mkdir -p "$WORK/runs"
for d in "$STAB"/*/ "$NEW"/*/; do cp -R "$d" "$WORK/runs/$(basename "$d")"; done
echo "merged $(ls "$WORK/runs" | wc -l | tr -d ' ') run directories"

cat > "$WORK/suite_meta.json" <<'META'
{"suite":"core","note":"complete 14-cell MATTE baseline: 7 cells from the Sep 13 stability A/B matte arm + 7 cells from the Sep 13 matte completion run. Every flight on floor_reflectance 0.0. The same five tool files, sha256-identical across both runs.","repeats":4,"cells":14}
META

"$P" "$HERE/scoreboard.py" "$WORK" --suite matte_baseline_14
