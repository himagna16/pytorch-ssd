#!/usr/bin/env bash
# One-command person-following demo in the simulator (Apple Silicon Mac).
# Starts the viewer + simulated AI-deck camera with a person scene, runs the
# follower, then always cleans up (the firmware locks after every landing,
# so each demo needs a fresh sim anyway).
# Usage: ./run_follow_demo.sh [scene_dir] [follow_person.py flags...]
#   scene_dir defaults to scenes/static_offset; it must be the FIRST argument.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DRONE_ROOT="$(cd "$HERE/../../.." && pwd)"
SCENE_DIR="${1:-$HERE/scenes/static_offset}"
[ $# -gt 0 ] && shift
[ -f "$SCENE_DIR/scene_person.xml" ] || { echo "No scene at $SCENE_DIR; build one with build_person_scene.py (see README)."; exit 1; }
SCENE_XML="$(cd "$SCENE_DIR" && pwd)/scene_person.xml"
LOG="$(mktemp -t crazysim_viewer)"
"$HERE/run_sim_viewer.sh" --camera --scene "$SCENE_XML" > "$LOG" 2>&1 &
VIEWER=$!
cleanup() {
  kill "$VIEWER" 2>/dev/null || true
  pkill -f "crazysim_mujoco/crazysim.py" 2>/dev/null || true
  docker rm -f crazysim-mac >/dev/null 2>&1 || true
}
trap cleanup EXIT
for i in $(seq 1 30); do grep -q "firmware connected" "$LOG" && break; sleep 1; done
grep -q "firmware connected" "$LOG" || { echo "Simulator did not start; see $LOG"; exit 1; }
sleep 2
OUT="$HERE/follow_runs/$(date +%Y%m%d_%H%M%S)"
"$DRONE_ROOT/trainenv/bin/python" "$HERE/follow_person.py" --out "$OUT" "$@"
echo "Run artifacts (log, summary, annotated snapshots): $OUT"
