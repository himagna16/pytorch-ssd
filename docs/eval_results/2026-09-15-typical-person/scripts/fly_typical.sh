#!/usr/bin/env bash
# 18 flights: {static, moving} x {the flown 99th-percentile cutout as the CONTROL,
# a median-detectability person, a ~25th-percentile person} x 3 repeats.
#
# This is NOT a new harness. `fly()` below is run_acceptance2.sh's `fly()` with
# the matrix lifted out: same lock protocol, same run_sim_headless.sh, same env
# (CRAZYSIM_TRUTH_LOG / _PREFIX / _SCENE_MOTION / _SENSOR_*), same cell.json
# keys, same follow_person.py invocation, same scoreboard.py --check-run gate,
# same one re-fly on INVALID, same teardown on every exit path. run_acceptance2.sh
# could not be used directly because its CORE matrix is hard-coded and `--only`
# is a filter on that matrix, so it has no way to name a scene it does not list;
# tools/ is not edited here.
#
# SETUP: "ships-as" for every cell - chip network, himax_typical camera, the
# GAP8's 6.5 Hz / 153 ms - because the question is what the real drone does.
# NO --vis-enter / --vis-exit / --confirm-frames flag is passed anywhere, so the
# shipped defaults (0.75 / 0.45 / 3) are what flies; that is asserted afterwards
# against every summary.json.
#
# ORDER: the subjects are interleaved flight by flight and rotated each repeat, so
# no subject is systematically first or last and machine state cannot favour one.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
D="$(cd "$HERE/.." && pwd)"
TOOLS=/Users/saimaruvada/Downloads/drone/pytorch_ssd/tools/crazysim_macos
P=/Users/saimaruvada/Downloads/drone/trainenv/bin/python
SCRATCH=/private/tmp/claude-501/-Users-saimaruvada-Downloads/90541ca8-cca5-4400-9855-79d1dde551f0/scratchpad
LOCK="$SCRATCH/sim.lock"
SCENES="$SCRATCH/typical_scenes"
OUT="$D"
REPEATS=3

mkdir -p "$OUT/runs"
PROGRESS="$OUT/progress.log"
STATUS="$OUT/progress.md"
T_START=$(date +%s)
log() { echo "[$(date +%H:%M:%S)] $*" | tee -a "$PROGRESS"; }

# cell_id|scene|class|duration_s   (backend/camera/speed are ships-as for all)
read -r -d '' CELLS <<'MATRIX'
A.static__control|s15_static_offset|A|45
A.static__median|tp15_static_median|A|45
A.static__p25|tp15_static_p25|A|45
B.moving__control|s01_control_moving|B|50
B.moving__median|tp01_moving_median|B|50
B.moving__p25|tp01_moving_p25|B|50
MATRIX

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

# fly <cell_id> <scene> <class> <duration> <repeat> <attempt>
fly() {
  local cid=$1 scene=$2 cls=$3 dur=$4 rep=$5 att=$6
  local backend=chip camera=himax_typical speed=chip
  local sdir="$SCENES/$scene"
  local run="$OUT/runs/${cid}__r${rep}a${att}"
  rm -rf "$run"; mkdir -p "$run"

  if [ ! -f "$sdir/scene.xml" ]; then
    log "  [$cid r$rep a$att] SCENE MISSING: $sdir/scene.xml"
    echo '{"error":"scene missing"}' > "$run/flight_error.json"; return 1
  fi

  local rate=6.5 lat=153
  "$P" - "$run/cell.json" <<PYEOF
import json, sys
json.dump({"cell_id": "$cid", "scene": "$scene", "scene_class": "$cls",
           "backend": "$backend", "camera": "$camera", "speed": "$speed",
           "rate_hz": $rate, "latency_ms": $lat, "repeat": $rep, "attempt": $att,
           "duration_s": $dur, "scene_dir": "$sdir", "run_dir": "$run",
           "truth": "$run/truth.csv", "sensor_seed": $((1000 + rep)),
           "freeze_expected": False, "needs_truth": True,
           "suite": "typical_person"}, open(sys.argv[1], "w"), indent=2)
PYEOF

  if docker ps -a --format '{{.Names}}' | grep -qx crazysim-mac \
     || pgrep -f "crazysim_mujoco/crazysim.py" >/dev/null; then
    log "  [$cid r$rep a$att] a simulator is already running; tearing it down first"
    pkill -f "crazysim_mujoco/crazysim.py" 2>/dev/null
    docker rm -f crazysim-mac >/dev/null 2>&1; sleep 2
  fi

  export CRAZYSIM_TRUTH_LOG="$run/truth.csv"; rm -f "$CRAZYSIM_TRUTH_LOG"
  export CRAZYSIM_TRUTH_PREFIX=subj_
  if [ -f "$sdir/motion.json" ]; then export CRAZYSIM_SCENE_MOTION="$sdir/motion.json"
  else unset CRAZYSIM_SCENE_MOTION || true; fi
  export CRAZYSIM_SENSOR_PRESET="$camera"
  export CRAZYSIM_SENSOR_SEED=$((1000 + rep))
  export CRAZYSIM_SENSOR_INFO="$run/camera_model.json"

  cd "$TOOLS"
  "$TOOLS/run_sim_headless.sh" --camera --scene "$sdir/scene.xml" > "$run/sim.log" 2>&1 &
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
    echo '{"error":"sim did not start"}' > "$run/flight_error.json"; return 1
  fi
  sleep 2

  # NOTE: no --vis-enter / --vis-exit / --confirm-frames. The shipped defaults fly.
  perl -e 'alarm shift; exec @ARGV' $((dur + 90)) "$P" follow_person.py \
      --duration "$dur" --out "$run" --backend chip --rate-hz 6.5 --latency-ms 153 \
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

"$P" - "$OUT/suite_meta.json" <<PYEOF
import json, sys, datetime
json.dump({"suite": "typical_person", "repeats": $REPEATS, "cells": 6,
           "started_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "duration_s": 0,
           "setup": "ships-as for every cell: chip backend, himax_typical camera, 6.5 Hz / 153 ms",
           "latch_rule": "follow_person.py defaults, no flags: vis_enter 0.75, vis_exit 0.45, confirm_frames 3",
           "model": {"ckpt": "/Users/saimaruvada/Downloads/drone/pytorch_ssd_unstable/artifacts/successor_qat_ep3_eval.pth",
                     "onnx": "/Users/saimaruvada/Downloads/drone/pytorch_ssd_unstable/logs/plain_follow_prod_qat_v3/quant_eval/model_id_dory.onnx"}},
          open(sys.argv[1], "w"), indent=2)
PYEOF

log "typical-person suite: 6 cells x $REPEATS repeats = 18 flights, ships-as, out=$OUT"
echo "# typical-person progress" > "$STATUS"
echo "" >> "$STATUS"
echo "| # | cell | scene | repeat | attempt | result | note |" >> "$STATUS"
echo "|---|---|---|---|---|---|---|" >> "$STATUS"

# Build the interleaved order: within each repeat, the three subjects of a class
# are rotated so each takes first / second / third place exactly once.
ORDER=()
for rep in $(seq 1 "$REPEATS"); do
  for cls in A B; do
    idx=0
    while IFS='|' read -r cid scene c dur; do
      [ "$c" = "$cls" ] || continue
      ORDER+=("$idx|$cid|$scene|$c|$dur|$rep")
      idx=$((idx + 1))
    done <<< "$CELLS"
  done
done
# rotate each repeat's block of 3 by (rep-1)
ROT=()
for rep in $(seq 1 "$REPEATS"); do
  for cls in A B; do
    blk=()
    for e in "${ORDER[@]}"; do
      IFS='|' read -r i cid scene c dur r <<< "$e"
      [ "$r" = "$rep" ] && [ "$c" = "$cls" ] && blk+=("$e")
    done
    n=${#blk[@]}
    for k in $(seq 0 $((n - 1))); do
      ROT+=("${blk[$(( (k + rep - 1) % n ))]}")
    done
  done
done

n=0
total=${#ROT[@]}
for e in "${ROT[@]}"; do
  IFS='|' read -r i cid scene cls dur rep <<< "$e"
  n=$((n + 1))
  for att in 1 2; do
    log "flight $n/$total  $cid  repeat $rep attempt $att  ($scene, chip/himax_typical/chip, ${dur}s)"
    take_lock
    fly "$cid" "$scene" "$cls" "$dur" "$rep" "$att"
    rc=$?
    drop_lock
    run="$OUT/runs/${cid}__r${rep}a${att}"
    if [ $rc -ne 0 ] && [ ! -f "$run/summary.json" ]; then
      log "  -> flight did not produce a run (exit $rc)"
      echo "| $n | $cid | $scene | $rep | $att | NO RUN | exit $rc |" >> "$STATUS"
      continue
    fi
    chk="$("$P" "$TOOLS/scoreboard.py" --check-run "$run" 2>&1)"
    if echo "$chk" | head -1 | grep -q '^VALID'; then
      log "  -> VALID"
      note=$("$P" - "$run" <<'PYEOF'
import json, sys
s = json.load(open(sys.argv[1] + "/summary.json"))
print(f"tracked {s.get('tracking_fraction')}, vis_enter {s.get('vis_enter')}, "
      f"sim/wall {s.get('sim_wall_ratio')}, {s.get('processed_hz')} Hz, end {s.get('end_reason')}")
PYEOF
)
      log "     $note"
      echo "| $n | $cid | $scene | $rep | $att | VALID | $note |" >> "$STATUS"
      break
    fi
    log "  -> INVALID: $(echo "$chk" | tail -1)"
    echo "| $n | $cid | $scene | $rep | $att | INVALID | $(echo "$chk" | tail -1 | cut -c1-120) |" >> "$STATUS"
    [ "$att" = 2 ] && log "  -> giving up on this repeat after 2 attempts"
  done
done

T_END=$(date +%s)
"$P" - "$OUT/suite_meta.json" $((T_END - T_START)) <<'PYEOF'
import json, sys
p = sys.argv[1]; d = json.load(open(p)); d["duration_s"] = int(sys.argv[2])
json.dump(d, open(p, "w"), indent=2)
PYEOF
log "all flights done in $(( (T_END - T_START) / 60 )) min"
