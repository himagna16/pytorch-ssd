#!/usr/bin/env bash
# Acceptance suite v2: the CORE matrix from scratchpad/simv2/spec_metrics.md section 6.2.
#
# run_acceptance.sh (the Sep 10 gate) is left untouched and still does exactly what it
# always did. This is a second, additive runner that flies the v2 scene suite across the
# axes that actually decide whether the first hardware flight is boring:
#
#   spine 1  "ships-as"  chip network + himax_typical camera + 6.5 Hz / 153 ms   6 scenes
#   spine 2  "proven"    float model  + clean camera        + full speed         5 scenes
#   deltas               one factor moved off spine 2, on the moving scene       3 cells
#
#   14 cells x 2 repeats = 28 flights, ~50 min.
#
# The CORE matrix only ever asks for two of camera_model.py's four sensor presets
# (clean and himax_typical), so himax_low_light and himax_color_bayer had no way in.
# --cameras is a separate 2-cell matrix that flies exactly those two, as the same
# float/full delta on the same moving scene as B.moving__delta_camera, so the three
# camera cells are directly comparable. CORE is untouched by it.
#
# Every flight is headless (the Mac screen may be asleep), runs alone behind the shared
# simulator lock, logs the simulator's ground truth for every subject, and is checked for
# validity the moment it lands; an INVALID flight is re-flown once. The lock is released
# and the simulator torn down after every flight, including on failure or Ctrl-C.
#
# Scoring is a separate step so it can be re-run offline:  scoreboard.py <out_dir>
#
# Usage:
#   ./run_acceptance2.sh                      # CORE matrix, 2 repeats, default out dir
#   ./run_acceptance2.sh --out DIR --repeats 2
#   ./run_acceptance2.sh --only 'B\.'         # regex filter on cell id
#   ./run_acceptance2.sh --list               # print the matrix and exit
#   ./run_acceptance2.sh --smoke              # one short flight per spine, for plumbing
#   ./run_acceptance2.sh --cameras            # the 2 never-flown presets (low light, Bayer)
#   ./run_acceptance2.sh --duration 20        # override every selected cell's duration
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DRONE_ROOT="$(cd "$HERE/../../.." && pwd)"
P="$DRONE_ROOT/trainenv/bin/python"
SCRATCH=/private/tmp/claude-501/-Users-saimaruvada-Downloads/90541ca8-cca5-4400-9855-79d1dde551f0/scratchpad
LOCK="$SCRATCH/sim.lock"
SCENES="$HERE/scenes_v2"

OUT="$HERE/follow_runs/acceptance2_$(date +%Y%m%d_%H%M%S)"
REPEATS=2
ONLY=""
LIST=0
SMOKE=0
CAMERAS=0
DUR_OVERRIDE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --out) OUT="$2"; shift 2;;
    --repeats) REPEATS="$2"; shift 2;;
    --only) ONLY="$2"; shift 2;;
    --list) LIST=1; shift;;
    --smoke) SMOKE=1; shift;;
    --cameras) CAMERAS=1; shift;;
    --duration) DUR_OVERRIDE="$2"
                case "$DUR_OVERRIDE" in ''|*[!0-9]*) echo "--duration wants whole seconds, got '$DUR_OVERRIDE'"; exit 2;; esac
                [ "$DUR_OVERRIDE" -ge 1 ] || { echo "--duration wants at least 1 second, got '$DUR_OVERRIDE'"; exit 2; }
                shift 2;;
    --lock) LOCK="$2"; shift 2;;
    -h|--help) sed -n '2,34p' "$0"; exit 0;;
    *) echo "unknown flag $1"; exit 2;;
  esac
done

# cell_id|scene|class|backend|camera|speed|duration_s
# speed: full = no rate cap; chip = --rate-hz 6.5 --latency-ms 153 (the GAP8's measured pace)
read -r -d '' CORE <<'MATRIX'
A.static__ships|s15_static_offset|A|chip|himax_typical|chip|45
B.moving__ships|s01_control_moving|B|chip|himax_typical|chip|50
C.empty__ships|s02_control_empty|C|chip|himax_typical|chip|35
D.occlusion__ships|s07_occlusion_reappear|D|chip|himax_typical|chip|60
E.furniture__ships|s16_furniture_only|E|chip|himax_typical|chip|35
F.pets__ships|s03_pets_only|F|chip|himax_typical|chip|35
A.static__proven|s15_static_offset|A|float|clean|full|45
B.moving__proven|s01_control_moving|B|float|clean|full|50
C.empty__proven|s02_control_empty|C|float|clean|full|35
D.occlusion__proven|s07_occlusion_reappear|D|float|clean|full|60
E.furniture__proven|s16_furniture_only|E|float|clean|full|35
B.moving__delta_speed|s01_control_moving|B|float|clean|chip|50
B.moving__delta_camera|s01_control_moving|B|float|himax_typical|full|50
B.moving__delta_backend|s01_control_moving|B|chip|clean|full|50
MATRIX

read -r -d '' SMOKE_M <<'MATRIX'
B.moving__ships|s01_control_moving|B|chip|himax_typical|chip|20
C.empty__proven|s02_control_empty|C|float|clean|full|20
MATRIX

# The two presets the CORE matrix never asks for. Same scene/backend/speed as
# B.moving__delta_camera (float, full speed, s01) with only the camera moved, so
# these read as two more deltas off spine 2 rather than a different experiment.
read -r -d '' CAMERA_M <<'MATRIX'
B.moving__delta_lowlight|s01_control_moving|B|float|himax_low_light|full|50
B.moving__delta_bayer|s01_control_moving|B|float|himax_color_bayer|full|50
MATRIX

MATRIX_TXT="$CORE"
SUITE=core
if [ "$SMOKE" = 1 ] && [ "$CAMERAS" = 1 ]; then
  echo "--smoke and --cameras select different matrices; pick one"; exit 2
fi
if [ "$SMOKE" = 1 ]; then MATRIX_TXT="$SMOKE_M"; SUITE=smoke; REPEATS=1; fi
if [ "$CAMERAS" = 1 ]; then MATRIX_TXT="$CAMERA_M"; SUITE=cameras; fi
if [ -n "$ONLY" ]; then MATRIX_TXT="$(echo "$MATRIX_TXT" | grep -E "$ONLY")"; fi
[ -z "$MATRIX_TXT" ] && { echo "no cells match --only '$ONLY'"; exit 2; }
if [ -n "$DUR_OVERRIDE" ]; then
  MATRIX_TXT="$(echo "$MATRIX_TXT" | awk -F'|' -v d="$DUR_OVERRIDE" 'BEGIN{OFS="|"} NF>1{$7=d} {print}')"
fi

N_CELLS=$(echo "$MATRIX_TXT" | wc -l | tr -d ' ')
if [ "$LIST" = 1 ]; then
  echo "suite=$SUITE  cells=$N_CELLS  repeats=$REPEATS  flights=$((N_CELLS * REPEATS))"
  echo "$MATRIX_TXT" | awk -F'|' '{printf "  %-26s %-24s class %s  %-5s %-14s %-4s %3ss\n",$1,$2,$3,$4,$5,$6,$7}'
  exit 0
fi

mkdir -p "$OUT/runs"
PROGRESS="$OUT/progress.log"
STATUS="$OUT/progress.md"
T_START=$(date +%s)

log() { echo "[$(date +%H:%M:%S)] $*" | tee -a "$PROGRESS"; }

SIMPID=""
HAVE_LOCK=0
cleanup() {
  [ -n "$SIMPID" ] && kill "$SIMPID" 2>/dev/null
  pkill -f "crazysim_mujoco/crazysim.py" 2>/dev/null
  docker rm -f crazysim-mac >/dev/null 2>&1
  SIMPID=""
  if [ "$HAVE_LOCK" = 1 ]; then rmdir "$LOCK" 2>/dev/null; HAVE_LOCK=0; fi
}
trap 'echo; log "interrupted - tearing down"; cleanup; exit 130' INT TERM
trap 'cleanup' EXIT

take_lock() {
  local waited=0
  while ! mkdir "$LOCK" 2>/dev/null; do
    [ $((waited % 60)) = 0 ] && log "  waiting for the simulator lock ($LOCK)"
    sleep 10; waited=$((waited + 10))
  done
  HAVE_LOCK=1
}
drop_lock() { if [ "$HAVE_LOCK" = 1 ]; then rmdir "$LOCK" 2>/dev/null; HAVE_LOCK=0; fi; }

# ---- one flight -----------------------------------------------------------
# fly <cell_id> <scene> <class> <backend> <camera> <speed> <duration> <repeat> <attempt>
fly() {
  local cid=$1 scene=$2 cls=$3 backend=$4 camera=$5 speed=$6 dur=$7 rep=$8 att=$9
  local sdir="$SCENES/$scene"
  local run="$OUT/runs/${cid}__r${rep}a${att}"
  rm -rf "$run"; mkdir -p "$run"

  if [ ! -f "$sdir/scene.xml" ]; then
    log "  [$cid r$rep a$att] SCENE MISSING: $sdir/scene.xml"
    echo '{"error":"scene missing"}' > "$run/flight_error.json"
    return 1
  fi

  local rate=0 lat=0
  if [ "$speed" = chip ]; then rate=6.5; lat=153; fi

  # cell.json is the scoreboard's only description of what this flight was
  "$P" - "$run/cell.json" <<PYEOF
import json, sys
json.dump({"cell_id": "$cid", "scene": "$scene", "scene_class": "$cls",
           "backend": "$backend", "camera": "$camera", "speed": "$speed",
           "rate_hz": $rate, "latency_ms": $lat, "repeat": $rep, "attempt": $att,
           "duration_s": $dur, "scene_dir": "$sdir", "run_dir": "$run",
           "truth": "$run/truth.csv", "sensor_seed": $((1000 + rep)),
           "freeze_expected": False, "needs_truth": True,
           "suite": "$SUITE"}, open(sys.argv[1], "w"), indent=2)
PYEOF

  if docker ps -a --format '{{.Names}}' | grep -qx crazysim-mac \
     || pgrep -f "crazysim_mujoco/crazysim.py" >/dev/null; then
    log "  [$cid r$rep a$att] a simulator is already running; tearing it down first"
    cleanup_sim_only=1; pkill -f "crazysim_mujoco/crazysim.py" 2>/dev/null
    docker rm -f crazysim-mac >/dev/null 2>&1; sleep 2
  fi

  export CRAZYSIM_TRUTH_LOG="$run/truth.csv"; rm -f "$CRAZYSIM_TRUTH_LOG"
  export CRAZYSIM_TRUTH_PREFIX=subj_
  if [ -f "$sdir/motion.json" ]; then export CRAZYSIM_SCENE_MOTION="$sdir/motion.json"
  else unset CRAZYSIM_SCENE_MOTION || true; fi
  if [ "$camera" = clean ]; then
    unset CRAZYSIM_SENSOR_PRESET CRAZYSIM_SENSOR_SEED CRAZYSIM_SENSOR_INFO || true
  else
    export CRAZYSIM_SENSOR_PRESET="$camera"
    export CRAZYSIM_SENSOR_SEED=$((1000 + rep))
    export CRAZYSIM_SENSOR_INFO="$run/camera_model.json"
  fi

  cd "$HERE"
  "$HERE/run_sim_headless.sh" --camera --scene "$sdir/scene.xml" > "$run/sim.log" 2>&1 &
  SIMPID=$!
  local i
  for i in $(seq 1 45); do
    grep -q "firmware connected" "$run/sim.log" 2>/dev/null && break
    sleep 1
  done
  if ! grep -q "firmware connected" "$run/sim.log" 2>/dev/null; then
    log "  [$cid r$rep a$att] SIM DID NOT START"; tail -4 "$run/sim.log" | sed 's/^/      /'
    kill "$SIMPID" 2>/dev/null; pkill -f "crazysim_mujoco/crazysim.py" 2>/dev/null
    docker rm -f crazysim-mac >/dev/null 2>&1; SIMPID=""
    echo '{"error":"sim did not start"}' > "$run/flight_error.json"
    return 1
  fi
  sleep 2

  local args=(--duration "$dur" --out "$run")
  [ "$backend" = chip ] && args+=(--backend chip)
  [ "$speed" = chip ] && args+=(--rate-hz 6.5 --latency-ms 153)
  perl -e 'alarm shift; exec @ARGV' $((dur + 90)) "$P" follow_person.py "${args[@]}" \
      > "$run/follower.log" 2>&1
  local rc=$?

  kill "$SIMPID" 2>/dev/null
  pkill -f "crazysim_mujoco/crazysim.py" 2>/dev/null
  sleep 2
  docker rm -f crazysim-mac >/dev/null 2>&1
  SIMPID=""
  sleep 1
  return $rc
}

# ---- suite ----------------------------------------------------------------
"$P" - "$OUT/suite_meta.json" <<PYEOF
import json, sys, datetime
json.dump({"suite": "$SUITE", "repeats": $REPEATS, "cells": $N_CELLS,
           "started_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "duration_s": 0,
           "model": {"ckpt": "$DRONE_ROOT/pytorch_ssd_unstable/artifacts/successor_qat_ep3_eval.pth",
                     "onnx": "$DRONE_ROOT/pytorch_ssd_unstable/logs/plain_follow_prod_qat_v3/quant_eval/model_id_dory.onnx"}},
          open(sys.argv[1], "w"), indent=2)
PYEOF

log "acceptance2 suite=$SUITE cells=$N_CELLS repeats=$REPEATS flights=$((N_CELLS * REPEATS)) out=$OUT"
echo "# acceptance2 progress ($SUITE)" > "$STATUS"
echo "" >> "$STATUS"
echo "| # | cell | scene | setup | repeat | attempt | result | note |" >> "$STATUS"
echo "|---|---|---|---|---|---|---|---|" >> "$STATUS"

n=0
total=$((N_CELLS * REPEATS))
while IFS='|' read -r cid scene cls backend camera speed dur; do
  [ -z "$cid" ] && continue
  for rep in $(seq 1 "$REPEATS"); do
    n=$((n + 1))
    for att in 1 2; do
      log "flight $n/$total  $cid  repeat $rep attempt $att  ($scene, $backend/$camera/$speed, ${dur}s)"
      take_lock
      fly "$cid" "$scene" "$cls" "$backend" "$camera" "$speed" "$dur" "$rep" "$att"
      rc=$?
      drop_lock
      run="$OUT/runs/${cid}__r${rep}a${att}"
      if [ $rc -ne 0 ] && [ ! -f "$run/summary.json" ]; then
        log "  -> flight did not produce a run (exit $rc)"
        echo "| $n | $cid | $scene | $backend/$camera/$speed | $rep | $att | NO RUN | exit $rc |" >> "$STATUS"
        continue
      fi
      chk="$("$P" "$HERE/scoreboard.py" --check-run "$run" 2>&1)"
      if echo "$chk" | head -1 | grep -q '^VALID'; then
        log "  -> VALID"
        echo "$chk" | sed 's/^/      /' | tee -a "$PROGRESS" >/dev/null
        note=$("$P" - "$run" <<'PYEOF'
import json, sys
s = json.load(open(sys.argv[1] + "/summary.json"))
print(f"tracked {s.get('tracking_fraction')}, sim/wall {s.get('sim_wall_ratio')}, "
      f"{s.get('processed_hz')} Hz, end {s.get('end_reason')}")
PYEOF
)
        echo "| $n | $cid | $scene | $backend/$camera/$speed | $rep | $att | VALID | $note |" >> "$STATUS"
        break
      fi
      log "  -> INVALID: $(echo "$chk" | tail -1)"
      echo "| $n | $cid | $scene | $backend/$camera/$speed | $rep | $att | INVALID | $(echo "$chk" | tail -1 | cut -c1-120) |" >> "$STATUS"
      [ "$att" = 2 ] && log "  -> giving up on this repeat after 2 attempts"
    done
  done
done <<< "$MATRIX_TXT"

T_END=$(date +%s)
"$P" - "$OUT/suite_meta.json" $((T_END - T_START)) <<'PYEOF'
import json, sys
p = sys.argv[1]
d = json.load(open(p))
d["duration_s"] = int(sys.argv[2])
json.dump(d, open(p, "w"), indent=2)
PYEOF

log "all flights done in $(( (T_END - T_START) / 60 )) min; scoring"
"$P" "$HERE/scoreboard.py" "$OUT" | tee -a "$PROGRESS"
log "artifacts: $OUT"
