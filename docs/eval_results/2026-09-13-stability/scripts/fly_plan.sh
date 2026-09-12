#!/usr/bin/env bash
# Fly a plan produced by make_plan.py, one flight at a time, alternating floor
# conditions.
#
# WHY THIS EXISTS INSTEAD OF run_acceptance2.sh
#   run_acceptance2.sh hardcodes SCENES="$HERE/scenes_v2" and walks cells x repeats
#   in a fixed nested order.  It therefore cannot (a) interleave two floor
#   conditions or (b) decorrelate repeat index from chronological position -- the
#   two design fixes this experiment exists to make.  The fly() body below is a
#   faithful copy of that script's fly(), with three deliberate changes:
#     - the scene root is a parameter, so matte and mirrored trees are separate
#       directories and no scene file is ever swapped under a running suite;
#     - load average is sampled immediately before and after every flight;
#     - the flight order comes from the plan file, not from a nested loop.
#   run_acceptance2.sh itself is NOT modified -- it is one of the things under
#   measurement.
#
# Usage: fly_plan.sh PLAN.tsv OUT_DIR MATTE_ROOT MIRROR_ROOT [START_ORDER]
set -uo pipefail

PLAN=$1; OUT=$2; MATTE_ROOT=$3; MIRROR_ROOT=$4; START=${5:-1}

HERE=/Users/saimaruvada/Downloads/drone/pytorch_ssd/tools/crazysim_macos
DRONE_ROOT=/Users/saimaruvada/Downloads/drone
P="$DRONE_ROOT/trainenv/bin/python"
SCRATCH=/private/tmp/claude-501/-Users-saimaruvada-Downloads/90541ca8-cca5-4400-9855-79d1dde551f0/scratchpad
# A DIFFERENT path from the workstream lock this agent holds for its whole run,
# so the per-flight lock cannot deadlock against it.
LOCK="$SCRATCH/sim_stability.lock"

mkdir -p "$OUT/runs"
PROGRESS="$OUT/progress.log"
FLIGHTS="$OUT/flights.jsonl"
log() { echo "[$(date +%H:%M:%S)] $*" | tee -a "$PROGRESS"; }

load1() { uptime | sed 's/.*load averages*: *//' | awk '{print $1}' | tr -d ','; }
load5() { uptime | sed 's/.*load averages*: *//' | awk '{print $2}' | tr -d ','; }
load15() { uptime | sed 's/.*load averages*: *//' | awk '{print $3}' | tr -d ','; }

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
    [ $((waited % 60)) = 0 ] && log "  waiting for the per-flight lock ($LOCK)"
    sleep 10; waited=$((waited + 10))
  done
  HAVE_LOCK=1
}
drop_lock() { if [ "$HAVE_LOCK" = 1 ]; then rmdir "$LOCK" 2>/dev/null; HAVE_LOCK=0; fi; }

# fly <cond> <cell> <scene> <class> <backend> <camera> <speed> <dur> <rep> <att> <order>
fly() {
  local cond=$1 cid=$2 scene=$3 cls=$4 backend=$5 camera=$6 speed=$7 dur=$8 rep=$9 att=${10} ord=${11}
  local root="$MATTE_ROOT"; [ "$cond" = mirror ] && root="$MIRROR_ROOT"
  local sdir="$root/$scene"
  local run="$OUT/runs/${cond}__${cid}__r${rep}a${att}"
  rm -rf "$run"; mkdir -p "$run"

  if [ ! -f "$sdir/scene.xml" ]; then
    log "  [$cond $cid r$rep a$att] SCENE MISSING: $sdir/scene.xml"
    echo '{"error":"scene missing"}' > "$run/flight_error.json"; return 1
  fi

  local rate=0 lat=0
  if [ "$speed" = chip ]; then rate=6.5; lat=153; fi

  "$P" - "$run/cell.json" <<PYEOF
import json, sys
json.dump({"cell_id": "$cid", "scene": "$scene", "scene_class": "$cls",
           "backend": "$backend", "camera": "$camera", "speed": "$speed",
           "rate_hz": $rate, "latency_ms": $lat, "repeat": $rep, "attempt": $att,
           "duration_s": $dur, "scene_dir": "$sdir", "run_dir": "$run",
           "truth": "$run/truth.csv", "sensor_seed": $((1000 + rep)),
           "freeze_expected": False, "needs_truth": True,
           "suite": "stability", "condition": "$cond", "order": $ord},
          open(sys.argv[1], "w"), indent=2)
PYEOF

  if docker ps -a --format '{{.Names}}' | grep -qx crazysim-mac \
     || pgrep -f "crazysim_mujoco/crazysim.py" >/dev/null; then
    log "  [$cond $cid r$rep a$att] a simulator is already running; tearing it down first"
    pkill -f "crazysim_mujoco/crazysim.py" 2>/dev/null
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
    log "  [$cond $cid r$rep a$att] SIM DID NOT START"
    kill "$SIMPID" 2>/dev/null; pkill -f "crazysim_mujoco/crazysim.py" 2>/dev/null
    docker rm -f crazysim-mac >/dev/null 2>&1; SIMPID=""
    echo '{"error":"sim did not start"}' > "$run/flight_error.json"; return 1
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

log "stability A/B starting: plan=$PLAN out=$OUT start=$START"
T0=$(date +%s)

NPLAN=$(grep -vc '^#' "$PLAN")
# Process substitution, not a pipe: the loop must run in THIS shell so that the
# EXIT/INT trap can see SIMPID and tear the simulator down.
while IFS=$'\t' read -r ord cond cid scene cls backend camera speed dur rep pair; do
  [ -z "$ord" ] && continue
  [ "$ord" -lt "$START" ] && continue

  for att in 1 2; do
    lb1=$(load1); lb5=$(load5); lb15=$(load15)
    t_start=$(date +%s)
    log "flight $ord/$NPLAN  $cond  $cid  r$rep a$att  (load1 $lb1)"
    take_lock
    fly "$cond" "$cid" "$scene" "$cls" "$backend" "$camera" "$speed" "$dur" "$rep" "$att" "$ord"
    rc=$?
    drop_lock
    t_end=$(date +%s)
    la1=$(load1); la5=$(load5); la15=$(load15)
    run="$OUT/runs/${cond}__${cid}__r${rep}a${att}"

    verdict=NORUN; reason="exit $rc"
    if [ -f "$run/summary.json" ]; then
      chk="$("$P" "$HERE/scoreboard.py" --check-run "$run" 2>&1)"
      if echo "$chk" | head -1 | grep -q '^VALID'; then verdict=VALID; reason="";
      else verdict=INVALID; reason="$(echo "$chk" | tail -1 | cut -c1-160)"; fi
      echo "$chk" > "$run/check.txt"
    fi

    "$P" - "$FLIGHTS" "$run" "$ord" "$cond" "$cid" "$rep" "$att" "$verdict" \
        "$t_start" "$t_end" "$lb1" "$lb5" "$lb15" "$la1" "$la5" "$la15" "$pair" "$reason" \
        <<'PYEOF' | tee -a "$PROGRESS"
import json, sys, os, datetime
(_, out, run, ord_, cond, cid, rep, att, verdict,
 t0, t1, lb1, lb5, lb15, la1, la5, la15, pair, reason) = sys.argv
rec = {"order": int(ord_), "pair": int(pair), "condition": cond, "cell": cid,
       "repeat": int(rep), "attempt": int(att), "verdict": verdict,
       "reason": reason, "run_dir": run,
       "t_start_utc": datetime.datetime.fromtimestamp(int(t0), datetime.timezone.utc)
                      .strftime("%Y-%m-%dT%H:%M:%SZ"),
       "wall_s": int(t1) - int(t0),
       "load1_before": float(lb1), "load5_before": float(lb5), "load15_before": float(lb15),
       "load1_after": float(la1), "load5_after": float(la5), "load15_after": float(la15)}
sp = os.path.join(run, "summary.json")
if os.path.exists(sp):
    s = json.load(open(sp))
    for k in ("sim_wall_ratio", "processed_hz", "loop_hz", "tracking_fraction",
              "frames_processed", "torn_frames", "z_max", "end_reason", "step_gap_ms"):
        rec[k] = s.get(k)
with open(out, "a") as f:
    f.write(json.dumps(rec) + "\n")
print(f"  -> {verdict}  sim/wall {rec.get('sim_wall_ratio')}  "
      f"{rec.get('processed_hz')} Hz  track {rec.get('tracking_fraction')}  "
      f"load1 {la1}  {reason}")
PYEOF

    [ "$verdict" = VALID ] && break
    [ "$att" = 2 ] && log "  -> giving up on this flight after 2 attempts"
  done
done < <(grep -v '^#' "$PLAN")

T1=$(date +%s)
log "ALL FLIGHTS DONE in $(( (T1 - T0) / 60 )) min"
