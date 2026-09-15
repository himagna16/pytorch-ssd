#!/usr/bin/env bash
# Score each arm with the repo's own scoreboard.py.
#
# scoreboard.py groups runs by cell_id, and both arms of a comparison share a
# cell_id, so scoring the suite in one pass would silently average the two arms
# together. docs/eval_results/2026-09-14-exit-bar solved this by giving each arm
# its own scoreboard directory whose runs/ are SYMLINKS into the real runs/;
# the same trick is used here. Nothing is copied and nothing under runs/ moves.
set -euo pipefail
D=/Users/saimaruvada/Downloads/drone/pytorch_ssd/docs/eval_results/2026-09-15-enter-bar-typical
P=/Users/saimaruvada/Downloads/drone/trainenv/bin/python
SB=/Users/saimaruvada/Downloads/drone/pytorch_ssd/tools/crazysim_macos/scoreboard.py

for arm in 0.70 0.75; do
  A="$D/scoreboards/arm_$arm"
  rm -rf "$A"; mkdir -p "$A/runs"
  for r in "$D"/runs/e${arm}__*; do
    [ -d "$r" ] || continue
    ln -s "$r" "$A/runs/$(basename "$r")"
  done
  n=$(ls "$A/runs" | wc -l | tr -d ' ')
  echo "=== arm $arm: $n runs"
  "$P" "$SB" "$A" --suite "enter-bar arm $arm" > "$A/scoreboard_stdout.log" 2>&1 || true
  tail -3 "$A/scoreboard_stdout.log"
done
