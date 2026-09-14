#!/usr/bin/env bash
# Fly the interleaved latch-threshold plan, one flight at a time.
#
# WHY THIS EXISTS INSTEAD OF run_acceptance2.sh
#   run_acceptance2.sh walks cells x repeats in a fixed nested order with one
#   fixed latch configuration (follow_person.py's --vis-enter / --confirm-frames
#   defaults), so it can neither interleave four configurations nor decorrelate
#   repeat index from chronological position.  Rather than edit it -- it is one
#   of the things being measured -- the fly() body below is a faithful copy of
#   it, carrying the same deliberate changes the matte baseline, the stability
#   run, the pets A/B run and the champion-vs-confuser run all made:
#     - the order comes from the plan file, not from a nested loop;
#     - load average is sampled immediately before and after every flight;
#   plus the one new thing this experiment needs:
#     - THE LATCH RULE IS A PARAMETER.  --vis-enter, --confirm-frames and
#       --vis-exit are passed to the repo's own follow_person.py, which has
#       exposed all three as arguments since Sep 10.  No source file is edited,
#       no default is changed, nothing is patched at runtime.
#   run_acceptance2.sh, follow_person.py, perception_backends.py, build_scene.py,
#   camera_model.py and scoreboard.py are NOT modified.
#
# ONE MODEL THROUGHOUT: the champion.  This experiment is not a model comparison.
#
# THE FLOOR IS ASSERTED PER FLIGHT, TWO WAYS, AND THE FLIGHT ABORTS IF IT IS WRONG:
#   the reflectance attribute in the scene.xml about to be flown, and
#   room.floor_reflectance in that scene's manifest.  Both are written into the
#   run directory so every result carries the floor it was flown on.  Every cell
#   here is matte (reflectance 0.0).
#
# TWO THINGS ARE VERIFIED PER FLIGHT, AFTER THE FACT, FROM WHAT THE FLIGHT ITSELF
# RECORDED -- never from what the command line said:
#   1. THE MODEL.  follow_person.py records backend_info (onnx path, eps,
#      onnx_sha1) into summary.json; check_model.py refuses to call a flight
#      VALID unless it is the champion's ONNX and the champion's eps.
#   2. THE LATCH RULE.  summary.json does NOT record --vis-enter, so
#      check_threshold.py replays the follower's state machine over the logged
#      conf column and requires it to reproduce the logged streak and tracking
#      columns exactly.  A harness typo that flew every row at 0.70 would show
#      up here as 96 flights that all match t070; it cannot pass silently.
#
# Usage: fly_plan_thresholds.sh PLAN.tsv OUT_DIR SCENE_ROOT [START_ORDER]
set -uo pipefail

PLAN=$1; OUT=$2; SCENE_ROOT=$3; START=${4:-1}
# fly() does `cd "$HERE"` to run the follower, so every path the loop uses
# must be absolute or it breaks after the first flight.
PLAN=$(cd "$(dirname "$PLAN")" && pwd)/$(basename "$PLAN")
mkdir -p "$OUT"; OUT=$(cd "$OUT" && pwd)
SCENE_ROOT=$(cd "$SCENE_ROOT" && pwd)

HERE=/Users/saimaruvada/Downloads/drone/pytorch_ssd/tools/crazysim_macos
SCRIPTS=/Users/saimaruvada/Downloads/drone/pytorch_ssd/docs/eval_results/2026-09-13-champion-threshold/scripts
DRONE_ROOT=/Users/saimaruvada/Downloads/drone
P="$DRONE_ROOT/trainenv/bin/python"
SCRATCH=/private/tmp/claude-501/-Users-saimaruvada-Downloads/90541ca8-cca5-4400-9855-79d1dde551f0/scratchpad
# A DIFFERENT path from the workstream lock this agent holds for its whole run,
# so the per-flight lock cannot deadlock against it.
LOCK="$SCRATCH/sim_thresh.lock"

# The one model.  A RELEASE DIRECTORY: the ONNX and the eps come from the same
# directory so they can never be mixed across releases.
CHAMPION_ONNX="$DRONE_ROOT/pytorch_ssd_unstable/logs/plain_follow_prod_qat_v3/quant_eval/model_id_dory.onnx"
CHAMPION_EPS=0.0002009823510888964

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

# fly <config> <cell> <scene> <class> <backend> <camera> <speed> <dur> <rep> <att> <ord> <enter> <cframes> <exit> <block> <slot>
fly() {
  local cfg=$1 cid=$2 scene=$3 cls=$4 backend=$5 camera=$6 speed=$7 dur=$8 rep=$9 att=${10} ord=${11}
  local enter=${12} cframes=${13} vexit=${14} block=${15} slot=${16}
  local onnx="$CHAMPION_ONNX" want_eps="$CHAMPION_EPS"
  local want=0                      # every cell here is flown on the matte floor
  local sdir="$SCENE_ROOT/$scene"
  local run="$OUT/runs/${cfg}__${cid}__r${rep}a${att}"
  rm -rf "$run"; mkdir -p "$run"

  if [ ! -f "$sdir/scene.xml" ]; then
    log "  [$cfg $cid r$rep a$att] SCENE MISSING: $sdir/scene.xml"
    echo '{"error":"scene missing"}' > "$run/flight_error.json"; return 1
  fi
  if [ ! -f "$onnx" ]; then
    log "  [$cfg $cid r$rep a$att] ONNX MISSING: $onnx"
    echo '{"error":"onnx missing"}' > "$run/flight_error.json"; return 1
  fi

  # Assert the floor of the scene actually about to be flown, two ways.  A
  # mismatch aborts rather than being flown and explained away later.
  local refl man_refl
  refl=$(grep -o 'reflectance="[^"]*"' "$sdir/scene.xml" | head -1 | sed 's/.*="//;s/"//')
  man_refl=$("$P" -c "import json,sys;print(json.load(open(sys.argv[1]))['room']['floor_reflectance'])" \
             "$sdir/manifest.json" 2>/dev/null)
  if [ "$(echo "$refl $want" | awk '{print ($1==$2)?"ok":"no"}')" != ok ] \
     || [ "$(echo "$man_refl $want" | awk '{print ($1==$2)?"ok":"no"}')" != ok ]; then
    log "  [$cfg $cid r$rep a$att] ABORT: floor is xml='$refl' manifest='$man_refl', wanted $want"
    echo "{\"error\":\"wrong floor: xml=$refl manifest=$man_refl want=$want\"}" > "$run/flight_error.json"
    return 1
  fi
  echo "$refl" > "$run/floor_reflectance.txt"
  echo "$man_refl" > "$run/floor_manifest.txt"
  echo "$onnx" > "$run/model_onnx.txt"

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
           "suite": "core", "model": "champion", "order": $ord,
           "config": "$cfg", "block": $block, "slot": $slot,
           "vis_enter": $enter, "confirm_frames": $cframes, "vis_exit": $vexit,
           "chip_onnx": "$onnx", "expected_eps": $want_eps,
           "floor_reflectance": float("$refl"),
           "floor_reflectance_manifest": float("$man_refl")},
          open(sys.argv[1], "w"), indent=2)
PYEOF

  if docker ps -a --format '{{.Names}}' | grep -qx crazysim-mac \
     || pgrep -f "crazysim_mujoco/crazysim.py" >/dev/null; then
    log "  [$cfg $cid r$rep a$att] a simulator is already running; tearing it down first"
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
    # The camera seed depends ONLY on the repeat index, so all four configs in a
    # matched block see the SAME himax noise draw.
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
    log "  [$cfg $cid r$rep a$att] SIM DID NOT START"
    kill "$SIMPID" 2>/dev/null; pkill -f "crazysim_mujoco/crazysim.py" 2>/dev/null
    docker rm -f crazysim-mac >/dev/null 2>&1; SIMPID=""
    echo '{"error":"sim did not start"}' > "$run/flight_error.json"; return 1
  fi
  sleep 2

  local args=(--duration "$dur" --out "$run"
              --vis-enter "$enter" --confirm-frames "$cframes" --vis-exit "$vexit")
  [ "$backend" = chip ] && args+=(--backend chip --chip-onnx "$onnx")
  [ "$speed" = chip ] && args+=(--rate-hz 6.5 --latency-ms 153)
  echo "follow_person.py ${args[*]}" > "$run/follow_cmd.txt"
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

log "latch-threshold suite starting: plan=$PLAN out=$OUT scenes=$SCENE_ROOT start=$START"
log "  model = $CHAMPION_ONNX (eps $CHAMPION_EPS) -- the champion, in every flight"
T0=$(date +%s)

NPLAN=$(grep -vc '^#' "$PLAN")
# Process substitution, not a pipe: the loop must run in THIS shell so the
# EXIT/INT trap can see SIMPID and tear the simulator down.
while IFS=$'\t' read -r ord cfg cid scene cls backend camera speed dur rep block slot enter cframes vexit; do
  [ -z "$ord" ] && continue
  [ "$ord" -lt "$START" ] && continue

  for att in 1 2; do
    lb1=$(load1); lb5=$(load5); lb15=$(load15)
    t_start=$(date +%s)
    log "flight $ord/$NPLAN  $cfg  $cid  r$rep a$att  (block $block slot $slot, enter $enter cf $cframes, load1 $lb1)"
    take_lock
    fly "$cfg" "$cid" "$scene" "$cls" "$backend" "$camera" "$speed" "$dur" "$rep" "$att" "$ord" \
        "$enter" "$cframes" "$vexit" "$block" "$slot"
    rc=$?
    drop_lock
    t_end=$(date +%s)
    la1=$(load1); la5=$(load5); la15=$(load15)
    run="$OUT/runs/${cfg}__${cid}__r${rep}a${att}"

    verdict=NORUN; reason="exit $rc"
    if [ -f "$run/summary.json" ]; then
      # THE MODEL CHECK and THE LATCH-RULE CHECK.  A flight that ran the wrong
      # network, or the wrong latch rule, is not a valid flight however clean
      # its dynamics were.
      mchk="$("$P" "$SCRIPTS/check_model.py" "$run" 2>&1)"
      tchk="$("$P" "$SCRIPTS/check_threshold.py" "$run" 2>&1)"
      chk="$("$P" "$HERE/scoreboard.py" --check-run "$run" 2>&1)"
      echo "$chk" > "$run/check.txt"
      echo "$mchk" > "$run/model_check.txt"
      echo "$tchk" > "$run/threshold_check.txt"
      if ! echo "$mchk" | grep -q '^MODEL_OK'; then
        verdict=INVALID; reason="$(echo "$mchk" | cut -c1-160)"
      elif ! echo "$tchk" | grep -q '^THRESH_OK'; then
        verdict=INVALID; reason="$(echo "$tchk" | cut -c1-160)"
      elif echo "$chk" | head -1 | grep -q '^VALID'; then verdict=VALID; reason=""
      else verdict=INVALID; reason="$(echo "$chk" | tail -1 | cut -c1-160)"; fi
    fi

    "$P" - "$FLIGHTS" "$run" "$ord" "$cfg" "$cid" "$rep" "$att" "$verdict" \
        "$t_start" "$t_end" "$lb1" "$lb5" "$lb15" "$la1" "$la5" "$la15" "$block" "$slot" "$reason" \
        <<'PYEOF' | tee -a "$PROGRESS"
import json, sys, os, datetime, csv
(_, out, run, ord_, cfg, cid, rep, att, verdict,
 t0, t1, lb1, lb5, lb15, la1, la5, la15, block, slot, reason) = sys.argv
rec = {"order": int(ord_), "config": cfg, "cell": cid,
       "repeat": int(rep), "attempt": int(att),
       "block": int(block), "slot": int(slot),
       "verdict": verdict, "reason": reason, "run_dir": run,
       "t_start_utc": datetime.datetime.fromtimestamp(int(t0), datetime.timezone.utc)
                      .strftime("%Y-%m-%dT%H:%M:%SZ"),
       "wall_s": int(t1) - int(t0),
       "load1_before": float(lb1), "load5_before": float(lb5), "load15_before": float(lb15),
       "load1_after": float(la1), "load5_after": float(la5), "load15_after": float(la15)}
cj = os.path.join(run, "cell.json")
if os.path.exists(cj):
    c = json.load(open(cj))
    for k in ("vis_enter", "confirm_frames", "vis_exit"):
        rec[k] = c.get(k)
fr = os.path.join(run, "floor_reflectance.txt")
if os.path.exists(fr):
    rec["floor_reflectance"] = float(open(fr).read().strip())
fm = os.path.join(run, "floor_manifest.txt")
if os.path.exists(fm):
    rec["floor_reflectance_manifest"] = float(open(fm).read().strip())
tc = os.path.join(run, "threshold_check.json")
if os.path.exists(tc):
    t = json.load(open(tc))
    rec["thresh_discriminating"] = t.get("discriminating")
    rec["thresh_also_consistent_with"] = t.get("also_consistent_with")
sp = os.path.join(run, "summary.json")
if os.path.exists(sp):
    s = json.load(open(sp))
    for k in ("sim_wall_ratio", "processed_hz", "loop_hz", "tracking_fraction",
              "frames_processed", "torn_frames", "z_max", "end_reason", "step_gap_ms"):
        rec[k] = s.get(k)
    bi = s.get("backend_info") or {}
    rec["onnx"] = bi.get("onnx"); rec["eps"] = bi.get("eps")
    rec["onnx_sha1"] = bi.get("onnx_sha1")
# Attitude upsets, straight off the flight log: |pitch| or |roll| > 30 deg, or
# the drone dropping below the flight floor while it was meant to be flying.
fl = os.path.join(run, "follow_log.csv")
FLOOR_M = 0.25
if os.path.exists(fl):
    mp = mr = 0.0; minz = None; ups = 0; below = 0; n = 0
    with open(fl) as f:
        for row in csv.DictReader(f):
            try:
                p = abs(float(row["pitch"])); r = abs(float(row["roll"]))
                z = float(row["pz"])
            except (KeyError, ValueError, TypeError):
                continue
            n += 1
            mp = max(mp, p); mr = max(mr, r)
            minz = z if minz is None else min(minz, z)
            if p > 30.0 or r > 30.0: ups += 1
            if z < FLOOR_M: below += 1
    rec["att_rows"] = n
    rec["abs_pitch_max_deg"] = round(mp, 3)
    rec["abs_roll_max_deg"] = round(mr, 3)
    rec["pz_min_m"] = None if minz is None else round(minz, 3)
    rec["attitude_upset_frames"] = ups
    rec["below_floor_frames"] = below
    rec["attitude_upset"] = bool(ups or below)
with open(out, "a") as f:
    f.write(json.dumps(rec) + "\n")
g = (rec.get("step_gap_ms") or {})
print(f"  -> {verdict}  floor {rec.get('floor_reflectance')}  enter {rec.get('vis_enter')}/"
      f"cf{rec.get('confirm_frames')}  disc {rec.get('thresh_discriminating')}  "
      f"sim/wall {rec.get('sim_wall_ratio')}  {rec.get('processed_hz')} Hz  "
      f"track {rec.get('tracking_fraction')}  "
      f"gap_max {g.get('max') if isinstance(g, dict) else g}  "
      f"upset {rec.get('attitude_upset')}  load1 {la1}  {reason}")
PYEOF

    [ "$verdict" = VALID ] && break
    [ "$att" = 2 ] && log "  -> giving up on this flight after 2 attempts"
  done
done < <(grep -v '^#' "$PLAN")

T1=$(date +%s)
log "ALL FLIGHTS DONE in $(( (T1 - T0) / 60 )) min"
