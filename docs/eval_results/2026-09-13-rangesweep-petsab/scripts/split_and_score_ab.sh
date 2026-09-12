#!/usr/bin/env bash
# scoreboard.py groups runs by cell_id, and both floors share the cell id
# F.pets__ships, so scoring OUT_DIR directly would average the two arms
# together.  Build one suite directory per condition (run dirs SYMLINKED,
# nothing copied and nothing edited) and score each with the unmodified
# scoreboard.py.  This is the stability run's split_and_score.sh, unchanged
# except for the output directory names.
#
# Usage: split_and_score_ab.sh OUT_DIR
set -euo pipefail
OUT=$(cd "$1" && pwd)
HERE=/Users/saimaruvada/Downloads/drone/pytorch_ssd/tools/crazysim_macos
P=/Users/saimaruvada/Downloads/drone/trainenv/bin/python

mkdir -p "$OUT/scoreboards"
for cond in matte mirror; do
  S="$OUT/scoreboards/${cond}_suite"
  rm -rf "$S"; mkdir -p "$S/runs"
  for d in "$OUT/runs/${cond}__"*/; do
    [ -d "$d" ] || continue
    # RELATIVE link, so the committed suite survives a clone or a move.
    ln -s "../../../runs/$(basename "$d")" "$S/runs/$(basename "$d" | sed "s/^${cond}__//")"
  done
  echo "=== scoring $cond ($(ls "$S/runs" | wc -l | tr -d ' ') runs) ==="
  "$P" "$HERE/scoreboard.py" "$S" --suite "petsab_${cond}" > "$S/scoreboard.txt" 2>&1 || true
  tail -4 "$S/scoreboard.txt"
done
echo "done: $OUT/scoreboards/{matte,mirror}_suite/scoreboard.json"
