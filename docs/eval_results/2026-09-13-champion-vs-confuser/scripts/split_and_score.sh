#!/usr/bin/env bash
# scoreboard.py groups runs by cell_id, and both models share the same six cell
# ids, so scoring OUT_DIR directly would average the two arms together and
# produce one meaningless verdict per cell.  Build one suite directory per model
# (run dirs SYMLINKED, nothing copied and nothing edited) and score each with the
# unmodified scoreboard.py.  This is the pets A/B run's split_and_score_ab.sh,
# unchanged except that the condition is the model rather than the floor.
#
# Usage: split_and_score.sh OUT_DIR
set -euo pipefail
OUT=$(cd "$1" && pwd)
HERE=/Users/saimaruvada/Downloads/drone/pytorch_ssd/tools/crazysim_macos
P=/Users/saimaruvada/Downloads/drone/trainenv/bin/python

mkdir -p "$OUT/scoreboards"
for model in champion confuser; do
  S="$OUT/scoreboards/${model}_suite"
  rm -rf "$S"; mkdir -p "$S/runs"
  for d in "$OUT/runs/${model}__"*/; do
    [ -d "$d" ] || continue
    # RELATIVE link, so the committed suite survives a clone or a move.
    ln -s "../../../runs/$(basename "$d")" "$S/runs/$(basename "$d" | sed "s/^${model}__//")"
  done
  echo "=== scoring $model ($(ls "$S/runs" | wc -l | tr -d ' ') runs) ==="
  "$P" "$HERE/scoreboard.py" "$S" --suite "cvc_${model}" > "$S/scoreboard.txt" 2>&1 || true
  tail -4 "$S/scoreboard.txt"
done
echo "done: $OUT/scoreboards/{champion,confuser}_suite/scoreboard.json"
