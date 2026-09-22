#!/usr/bin/env bash
# End to end, about 5 minutes: rebuild the 13 scenes, re-render the Sep 16 grid
# (13,000 frames, ~3.5 min), score it on both arms with score_real_frames.py
# (~25 s each), re-run the Sep 17 rescore_chip.py on the same frames (~25 s), then
# analyze. Frames and scenes go to a scratch directory and are NOT committed.
#
# Usage: run_rescore.sh <scratch_dir>
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
D="$(cd "$HERE/.." && pwd)"
REPO="$(cd "$D/../../.." && pwd)"
DRONE="$(cd "$REPO/.." && pwd)"
P="$DRONE/trainenv/bin/python"
DORY="$DRONE/doryenv/bin/python"
SCR="${1:?usage: run_rescore.sh <scratch_dir>}"
mkdir -p "$SCR"

cd "$REPO/tools/crazysim_macos"
"$P" build_scene.py --def "$REPO"/docs/eval_results/2026-09-15-people-plural/scene_defs/pp15_*.json \
     scene_defs/s15_static_offset.json --out "$SCR/pool_scenes" --floor-reflectance 0.0 | tail -2

"$P" "$HERE/render_grid_frames.py" "$SCR/pool_scenes" "$SCR/grid_frames"

S="$REPO/tools/real_frames/score_real_frames.py"
"$P" "$S" "$SCR/grid_frames" --backend chip  --csv "$D/tables/scores_chip.csv"  --json "$D/tables/scores_chip.json"  > "$SCR/score_chip.log"
"$P" "$S" "$SCR/grid_frames" --backend float --csv "$D/tables/scores_float.csv" --json "$D/tables/scores_float.json" > "$SCR/score_float.log"
grep -E "^BACKEND|^MIRROR" "$SCR/score_chip.log" "$SCR/score_float.log"

# The Sep 17 script, unmodified, on the same frames (it double-preprocesses; see README)
"$DORY" "$REPO/docs/eval_results/2026-09-17-chip-arm-rescore/scripts/rescore_chip.py" \
        "$SCR/grid_frames" "$SCR/sep17_rescore_chip.csv" | tail -1

"$P" "$HERE/analyze_rescore.py" "$SCR/sep17_rescore_chip.csv"
