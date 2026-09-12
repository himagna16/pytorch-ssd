#!/usr/bin/env bash
# One follow-app flight on a fresh HEADLESS sim (works with a locked screen): starts CrazySim with
# the follow-app firmware (crazysim-mac:follow-app) and the person's true-position log, runs
# gap8_emulator.py, saves the firmware console, and shuts the sim down. The firmware locks after
# every landing, so every flight needs its own sim.
# Usage: sim/fly_app.sh <name> <scene: static_offset|moving|empty> <duration_s> [gap8_emulator.py flags]
#   e.g. sim/fly_app.sh freeze5 moving 25 --freeze-at 10 --freeze-for 5
# Output: $FLY_OUT (default ../demo/follow_app_runs/<time> next to the repo)/{run_<name>/, truth_<name>.csv,
#   sim_<name>.log, emu_<name>.log, fw_<name>.log}. Score: analyze_follow_app.py run_<name> --truth truth_<name>.csv
# Set FLY_LOCK=/path/to/lockdir to serialize with other simulator users (mkdir lock).
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CS="$(cd "$HERE/../../crazysim_macos" && pwd)"
DRONE_ROOT="$(cd "$HERE/../../../.." && pwd)"
P="${FLY_PYTHON:-$DRONE_ROOT/trainenv/bin/python}"
OUT="${FLY_OUT:-$DRONE_ROOT/demo/follow_app_runs/$(date +%Y%m%d_%H%M%S)}"   # outside the repo
[ $# -ge 3 ] || { sed -n 2,11p "$0"; exit 2; }
name=$1 scene=$2 dur=$3; shift 3
[ -f "$CS/scenes/$scene/scene_person.xml" ] || { echo "No scene $CS/scenes/$scene (build it: see crazysim_macos/README.md)"; exit 2; }
mkdir -p "$OUT"
if [ -n "${FLY_LOCK:-}" ]; then
  until mkdir "$FLY_LOCK" 2>/dev/null; do sleep 10; done
  trap 'rmdir "$FLY_LOCK" 2>/dev/null' EXIT
fi
if docker ps -a --format '{{.Names}}' | grep -qx crazysim-mac || pgrep -f "crazysim_mujoco/crazysim.py" >/dev/null; then
  echo "A simulator is already running (container crazysim-mac or crazysim.py); stop it first."; exit 3; fi
export CRAZYSIM_TRUTH_LOG="$OUT/truth_$name.csv"; rm -f "$CRAZYSIM_TRUTH_LOG"; rm -rf "$OUT/run_$name"
cd "$CS"
"$HERE/run_sim_follow_app.sh" --camera --scene "$CS/scenes/$scene/scene_person.xml" > "$OUT/sim_$name.log" 2>&1 &
sim=$!
for i in $(seq 1 40); do grep -q "firmware connected" "$OUT/sim_$name.log" 2>/dev/null && break; sleep 1; done
sleep 2
perl -e 'alarm shift; exec @ARGV' $((${dur%.*} + 90)) "$P" gap8_emulator.py --duration "$dur" --out "$OUT/run_$name" "$@" \
  > "$OUT/emu_$name.log" 2>&1
rc=$?
docker exec crazysim-mac cat sitl_make/build/0/out.log > "$OUT/fw_$name.log" 2>/dev/null
kill "$sim" 2>/dev/null; pkill -f "crazysim_mujoco/crazysim.py" 2>/dev/null; sleep 2
docker rm -f crazysim-mac >/dev/null 2>&1
echo "[$name] emulator exit $rc; output in $OUT"
exit $rc
