#!/usr/bin/env bash
# scoreboard.py groups runs by cell_id, and both floor conditions share cell ids,
# so scoring OUT_DIR directly would average the two arms together.  Build one
# suite directory per condition (run dirs symlinked, nothing copied or edited)
# and score each separately with the unmodified scoreboard.py.
#
# Usage: split_and_score.sh OUT_DIR
set -euo pipefail
OUT=$1
HERE=/Users/saimaruvada/Downloads/drone/pytorch_ssd/tools/crazysim_macos
P=/Users/saimaruvada/Downloads/drone/trainenv/bin/python

for cond in matte mirror; do
  S="$OUT/${cond}_suite"
  rm -rf "$S"; mkdir -p "$S/runs"
  for d in "$OUT/runs/${cond}__"*/; do
    [ -d "$d" ] || continue
    ln -s "$(cd "$d" && pwd)" "$S/runs/$(basename "$d" | sed "s/^${cond}__//")"
  done
  [ -f "$OUT/suite_meta.json" ] && cp "$OUT/suite_meta.json" "$S/" || true
  echo "=== scoring $cond ($(ls "$S/runs" | wc -l | tr -d ' ') runs) ==="
  "$P" "$HERE/scoreboard.py" "$S" --suite "stability_${cond}" > "$S/scoreboard.txt" 2>&1 || true
  tail -3 "$S/scoreboard.txt"
done
echo "done: $OUT/{matte,mirror}_suite/scoreboard.json"
