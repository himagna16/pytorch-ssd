#!/usr/bin/env bash
# One-command simulator demo: the drone follows a person, then a scorecard.
#
#   ./demo.sh                    moving person, 3D viewer window (the main demo)
#   ./demo.sh --scene empty      empty room: the drone must stay put
#   ./demo.sh --scene freeze     camera freezes at 20 s: hover, then land
#   ./demo.sh --scene static     person standing still off to the side
#   ./demo.sh --headless         no 3D window (works with the screen locked)
#   ./demo.sh --stop             kill a leftover simulator from an earlier run
#
# Other options: --duration S (whole run; the first ~13 s are connect + takeoff),
# --out DIR (where logs go), --save-frames (keep every camera frame, for
# make_demo_video.py).
# Needs Docker Desktop running and ./setup.sh done once.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DRONE_ROOT="$(cd "$HERE/../../.." && pwd)"
PY="$DRONE_ROOT/trainenv/bin/python"
MJDIR="$DRONE_ROOT/crazysim_mujoco"
SCENE=moving HEADLESS=0 DURATION="" OUT="" SAVE_FRAMES=0

say()  { printf '%s\n' "$*"; }
fail() { printf '\nERROR: %s\n' "$1" >&2; shift; for l in "$@"; do printf '  %s\n' "$l" >&2; done; exit 1; }
usage() { sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }

sim_running() {
  docker ps -a --format '{{.Names}}' 2>/dev/null | grep -qx crazysim-mac && return 0
  pgrep -f "crazysim_mujoco/crazysim.py" >/dev/null && return 0
  pgrep -f "crazysim_macos/follow_person.py" >/dev/null && return 0
  return 1
}
stop_all() {
  pkill -f "crazysim_macos/follow_person.py" 2>/dev/null
  pkill -f "crazysim_mujoco/crazysim.py" 2>/dev/null
  docker rm -f crazysim-mac >/dev/null 2>&1
  sleep 1
}

while [ $# -gt 0 ]; do
  case "$1" in
    --scene) SCENE="${2:-}"; shift 2 ;;
    --scene=*) SCENE="${1#*=}"; shift ;;
    --headless) HEADLESS=1; shift ;;
    --duration) DURATION="${2:-}"; shift 2 ;;
    --out) OUT="${2:-}"; shift 2 ;;
    --save-frames) SAVE_FRAMES=1; shift ;;
    --stop) stop_all; sim_running && fail "Something is still running." "Quit Docker Desktop and reopen it." ; say "Stopped. Nothing from the simulator is running now."; exit 0 ;;
    -h|--help) usage 0 ;;
    *) say "Unknown option: $1"; usage 1 ;;
  esac
done

# scene -> scene folder, true person position (for scoring), seconds, extra follower flags
EXTRA=()
case "$SCENE" in
  moving) DIR=moving;        TX=3.0; TY=0.0;  DUR=50 ;;
  static) DIR=static_offset; TX=3.5; TY=-1.0; DUR=35 ;;
  empty)  DIR=empty;         TX=-2.5; TY=0.0;  DUR=25 ;;
  freeze) DIR=moving;        TX=3.0; TY=0.0;  DUR=45; EXTRA=(--simulate-stale-at 20) ;;
  *) fail "Unknown scene '$SCENE'." "Pick one of: moving, static, empty, freeze" ;;
esac
DUR="${DURATION:-$DUR}"
OUT="${OUT:-$HERE/follow_runs/demo_${SCENE}_$(date +%Y%m%d_%H%M%S)}"
mkdir -p "$OUT" || fail "Cannot create output folder $OUT"
OUT="$(cd "$OUT" && pwd)"

# ---------- preflight ----------
say "== Checking setup"
command -v docker >/dev/null || fail "Docker is not installed." "Install Docker Desktop, then run ./setup.sh once."
docker info >/dev/null 2>&1 || fail "Docker is not running." "Open Docker Desktop, wait until it says 'Engine running', then try again."
docker image inspect crazysim-mac:arm64 >/dev/null 2>&1 || fail "The simulator image crazysim-mac:arm64 is missing." "Run ./setup.sh once (about 10 minutes)."
[ -x "$PY" ] || fail "Python environment not found at $PY"
[ -f "$MJDIR/crazysim.py" ] && [ -x "$DRONE_ROOT/crazysimenv/bin/mjpython" ] || fail "Simulator files are missing." "Run ./setup.sh once."
[ -f "$DRONE_ROOT/pytorch_ssd_unstable/artifacts/successor_qat_ep3_eval.pth" ] || fail "Model checkpoint not found." "Expected $DRONE_ROOT/pytorch_ssd_unstable/artifacts/successor_qat_ep3_eval.pth"
if sim_running; then
  fail "A simulator (or follower) from an earlier run is still running." \
       "Stop it with:   ./demo.sh --stop" "then run this command again."
fi
if [ "$HEADLESS" = 0 ] && ioreg -n Root -d1 2>/dev/null | grep -q '"CGSSessionScreenIsLocked"=Yes'; then
  fail "The Mac screen is locked, and the 3D viewer window crashes on a locked screen." \
       "Unlock the screen, or run without the window:   ./demo.sh --headless"
fi
if [ "$HEADLESS" = 0 ]; then
  # mjpython (the viewer's Python) hangs, instead of failing, when macOS will not
  # give it a window: screen locked, display asleep, or no active desktop session.
  say "   checking that the 3D window can open..."
  if ! ( perl -e 'alarm shift; exec @ARGV' 15 "$DRONE_ROOT/crazysimenv/bin/mjpython" -c "pass"; exit $? ) >/dev/null 2>&1; then
    fail "The 3D viewer cannot open a window right now." \
         "This happens when the screen is locked, the display is asleep, or the Mac" \
         "is not being used at its own screen (e.g. over remote login)." \
         "Wake and unlock the Mac and try again, or run without the window:   ./demo.sh --headless"
  fi
fi

# ---------- scenes ----------
PERSON=(--img-id 19432 --ann-id 428692)
build() { # dir, args...
  local d=$1; shift
  [ -f "$HERE/scenes/$d/scene_person.xml" ] && return 0
  say "   building scene '$d' (one time, ~30 s)..."
  (cd "$HERE" && "$PY" build_person_scene.py "${PERSON[@]}" "$@" --out "scenes/$d") > "$OUT/build_$d.log" 2>&1 \
    || fail "Could not build scene '$d'." "It needs COCO val2017 and the pytorch_ssd_unstable worktree." "Details: $OUT/build_$d.log"
}
build static_offset --person-x 3.5 --person-y -1.0
build moving --person-x 3.0 --sway-amp 1.2 --sway-period 20
build empty --person-x -2.5
SCENE_XML="$HERE/scenes/$DIR/scene_person.xml"

# ---------- launch ----------
SIMPID="" FOLPID=""
cleanup() {
  trap - EXIT INT TERM
  [ -n "$FOLPID" ] && kill "$FOLPID" 2>/dev/null
  [ -n "$SIMPID" ] && kill "$SIMPID" 2>/dev/null
  pkill -f "crazysim_mujoco/crazysim.py" 2>/dev/null
  docker rm -f crazysim-mac >/dev/null 2>&1
}
on_interrupt() { say ""; say "Stopped by Ctrl-C. Shutting the simulator down..."; cleanup; say "Done. Nothing is left running."; exit 130; }
trap cleanup EXIT
trap on_interrupt INT TERM

export CRAZYSIM_TRUTH_LOG="$OUT/truth.csv"; rm -f "$CRAZYSIM_TRUTH_LOG"
if [ "$HEADLESS" = 1 ]; then
  say "== Starting the simulator (headless, no window) with scene '$SCENE'"
  "$HERE/run_sim_headless.sh" --camera --scene "$SCENE_XML" > "$OUT/sim.log" 2>&1 &
else
  say "== Starting the simulator with the 3D viewer, scene '$SCENE'"
  "$HERE/run_sim_viewer.sh" --camera --scene "$SCENE_XML" > "$OUT/sim.log" 2>&1 &
fi
SIMPID=$!
for i in $(seq 1 45); do
  grep -q "firmware connected" "$OUT/sim.log" 2>/dev/null && break
  kill -0 "$SIMPID" 2>/dev/null || break
  sleep 1
done
if ! grep -q "firmware connected" "$OUT/sim.log" 2>/dev/null; then
  tail -5 "$OUT/sim.log" >&2
  if [ "$HEADLESS" = 0 ]; then
    fail "The simulator did not start (log: $OUT/sim.log)." \
         "If the screen was locked or went to sleep, the viewer window cannot open:" \
         "unlock it and retry, or run   ./demo.sh --headless" "If Docker was just started, wait 20 s and retry."
  else
    fail "The simulator did not start (log: $OUT/sim.log)." "Make sure Docker Desktop is running, then retry."
  fi
fi
[ "$HEADLESS" = 0 ] && say "   The 3D window is open. Drag with the mouse to rotate the view."
sleep 2

# ---------- fly ----------
FARGS=(--duration "$DUR" --out "$OUT" "${EXTRA[@]}")
[ "$SAVE_FRAMES" = 1 ] && FARGS+=(--save-frames "$OUT/frames")
case "$SCENE" in
  moving) say "== Flying: the drone takes off, finds the person, and turns to follow them for $DUR s" ;;
  static) say "== Flying: the drone takes off, turns toward the person, and moves closer ($DUR s)" ;;
  empty)  say "== Flying: nobody is in front of the drone, so it should hover in place ($DUR s)" ;;
  freeze) say "== Flying: following the person; at 20 s the camera feed freezes on purpose" ;;
esac
( cd "$HERE" && PYTHONUNBUFFERED=1 exec perl -e 'alarm shift; exec @ARGV' $((DUR + 60)) "$PY" "$HERE/follow_person.py" "${FARGS[@]}" ) \
  > "$OUT/follower.log" 2>&1 &
FOLPID=$!
T0=$(date +%s); last=-1
while kill -0 "$FOLPID" 2>/dev/null; do
  el=$(( $(date +%s) - T0 ))
  if [ $((el / 5)) -ne "$last" ]; then
    last=$((el / 5))
    if grep -q "camera frames arriving" "$OUT/follower.log" 2>/dev/null; then
      printf "   %3d s  flying (connect, take off, then follow)...\n" "$el"
    else
      printf '   %3d s  loading the model and waiting for camera frames...\n' "$el"
    fi
  fi
  sleep 1
done
wait "$FOLPID"; FRC=$?; FOLPID=""
say "== Landed. Shutting the simulator down..."
cleanup
trap on_interrupt INT TERM
[ "$FRC" = 0 ] || { tail -8 "$OUT/follower.log" >&2; say "(follower exited with code $FRC; log: $OUT/follower.log)"; }

# ---------- score ----------
say ""
"$PY" "$HERE/demo_scorecard.py" "$OUT" "$SCENE" "$TX" "$TY" --truth "$OUT/truth.csv"
SRC=$?
"$PY" "$HERE/analyze_follow.py" "$OUT" "$TX" "$TY" --truth "$OUT/truth.csv" > "$OUT/analysis.txt" 2>&1
say " Full logs: $OUT"
[ "$FRC" = 0 ] && [ "$SRC" = 0 ]
