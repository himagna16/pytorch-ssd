#!/usr/bin/env bash
# scoreboard.py groups runs by cell_id, and all four latch configs share the same
# six cell ids, so scoring OUT_DIR directly would average the four arms together
# and produce one meaningless verdict per cell.  Build one suite directory per
# config (run dirs SYMLINKED, nothing copied and nothing edited) and score each
# with the unmodified scoreboard.py.  This is the champion-vs-confuser run's
# split_and_score.sh, unchanged except that the condition is the latch config
# rather than the model.
#
# NOTE ON READING THE PER-ARM SCOREBOARDS: scoreboard.py carries module constants
# VIS_ENTER=0.70 / CONFIRM_FRAMES=3.  The HARD gates (M6 drift, M8 episodes, M1
# tracking) are computed from the logged `tracking` column and so are correct for
# every arm.  A few REPORT lines compare against those constants and therefore
# still say 0.70 even in the 0.75 / 0.80 / cf4 scoreboards.  That is a label on
# the report text, not an error in the gate.
#
# Usage: split_and_score.sh OUT_DIR
set -euo pipefail
OUT=$(cd "$1" && pwd)
HERE=/Users/saimaruvada/Downloads/drone/pytorch_ssd/tools/crazysim_macos
P=/Users/saimaruvada/Downloads/drone/trainenv/bin/python

mkdir -p "$OUT/scoreboards"
for cfg in t070 t075 t080 t070cf4; do
  S="$OUT/scoreboards/${cfg}_suite"
  rm -rf "$S"; mkdir -p "$S/runs"
  for d in "$OUT/runs/${cfg}__"*/; do
    [ -d "$d" ] || continue
    # Skip attempts that never produced a flight (the one startup hang this
    # session saw, retried successfully as attempt 2).  scoreboard.py already
    # ignores them, but leaving them out keeps the committed suite unambiguous.
    [ -f "$d/summary.json" ] || { echo "  (skipping $(basename "$d"): no summary.json)"; continue; }
    # RELATIVE link, so the committed suite survives a clone or a move.
    ln -s "../../../runs/$(basename "$d")" "$S/runs/$(basename "$d" | sed "s/^${cfg}__//")"
  done
  echo "=== scoring $cfg ($(ls "$S/runs" | wc -l | tr -d ' ') runs) ==="
  "$P" "$HERE/scoreboard.py" "$S" --suite "thr_${cfg}" > "$S/scoreboard.txt" 2>&1 || true
  tail -4 "$S/scoreboard.txt"
done
echo "done: $OUT/scoreboards/{t070,t075,t080,t070cf4}_suite/scoreboard.json"
