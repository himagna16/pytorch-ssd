#!/usr/bin/env bash
# Acceptance suite for the simulator person follower (the Sep 10 gate).
# Builds the three test scenes if missing, then flies five tests, each on a
# fresh sim (the firmware locks after every landing), with the simulator
# logging the person's true position, and scores every run against it.
# Usage: ./run_acceptance.sh [out_dir]
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DRONE_ROOT="$(cd "$HERE/../../.." && pwd)"
P="$DRONE_ROOT/trainenv/bin/python"
OUT="${1:-$HERE/follow_runs/acceptance_$(date +%Y%m%d_%H%M%S)}"
mkdir -p "$OUT"
PERSON="--img-id 19432 --ann-id 428692"
cd "$HERE"
[ -f scenes/static_offset/scene_person.xml ] || "$P" build_person_scene.py $PERSON --person-x 3.5 --person-y -1.0 --out scenes/static_offset
[ -f scenes/moving/scene_person.xml ] || "$P" build_person_scene.py $PERSON --person-x 3.0 --sway-amp 1.2 --sway-period 20 --out scenes/moving
[ -f scenes/empty/scene_person.xml ] || "$P" build_person_scene.py $PERSON --person-x -2.5 --out scenes/empty

run_one() {
  local name=$1 scene=$2 dur=$3; shift 3
  export CRAZYSIM_TRUTH_LOG="$OUT/truth_$name.csv"; rm -f "$CRAZYSIM_TRUTH_LOG"
  ./run_sim_viewer.sh --camera --scene "$HERE/$scene" > "$OUT/viewer_$name.log" 2>&1 &
  local viewer=$!
  for i in $(seq 1 30); do grep -q "firmware connected" "$OUT/viewer_$name.log" 2>/dev/null && break; sleep 1; done
  sleep 2
  perl -e 'alarm shift; exec @ARGV' $((dur + 60)) "$P" follow_person.py --duration "$dur" --out "$OUT/run_$name" "$@" \
    > "$OUT/follower_$name.log" 2>&1
  echo "[$name] follower exit $?"
  kill "$viewer" 2>/dev/null; pkill -f "crazysim_mujoco/crazysim.py" 2>/dev/null; sleep 2
  docker rm -f crazysim-mac >/dev/null 2>&1
}

echo "== 1 person off to the side";  run_one static scenes/static_offset/scene_person.xml 35
"$P" analyze_follow.py "$OUT/run_static" 3.5 -1.0 --truth "$OUT/truth_static.csv" --brief
echo "== 2 moving person";          run_one moving scenes/moving/scene_person.xml 50
"$P" analyze_follow.py "$OUT/run_moving" 3.0 0.0 --truth "$OUT/truth_moving.csv" --brief
echo "== 3 moving, smooth steering"; run_one moving_soft scenes/moving/scene_person.xml 50 --soft-x
"$P" analyze_follow.py "$OUT/run_moving_soft" 3.0 0.0 --truth "$OUT/truth_moving_soft.csv" --brief
echo "== 4 empty room";             run_one empty scenes/empty/scene_person.xml 30
"$P" analyze_follow.py "$OUT/run_empty" -2.5 0.0 --brief
echo "== 5 camera freezes at 20 s";  run_one stale scenes/static_offset/scene_person.xml 45 --simulate-stale-at 20
"$P" analyze_follow.py "$OUT/run_stale" 3.5 -1.0 --truth "$OUT/truth_stale.csv" --brief
"$P" plot_follow.py "$OUT/moving_comparison.png" \
  "Winning-bin steering" "$OUT/run_moving" "$OUT/truth_moving.csv" \
  "Smooth steering" "$OUT/run_moving_soft" "$OUT/truth_moving_soft.csv"
echo "Suite done. Artifacts: $OUT"
