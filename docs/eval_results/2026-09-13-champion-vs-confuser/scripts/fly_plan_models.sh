#!/usr/bin/env bash
# Fly the interleaved champion-vs-confuser plan, one flight at a time.
#
# WHY THIS EXISTS INSTEAD OF run_acceptance2.sh
#   run_acceptance2.sh walks cells x repeats in a fixed nested order with one
#   fixed model (the chip backend's DEFAULT_ONNX, i.e. the champion), so it can
#   neither interleave two models nor decorrelate repeat index from
#   chronological position.  Rather than edit it -- it is one of the things
#   being measured -- the fly() body below is a faithful copy of it, carrying
#   the same deliberate changes the matte baseline, the stability run and the
#   pets A/B run all made:
#     - the order comes from the plan file, not from a nested loop;
#     - load average is sampled immediately before and after every flight;
#   plus the one new thing this experiment needs:
#     - THE MODEL IS A PARAMETER.  It is passed to the repo's own
#       follow_person.py as --chip-onnx, which perception_backends.py already
#       supports, and the chip backend reads id_output_eps from the
#       release_summary.json sitting next to that ONNX.  No file is swapped,
#       nothing is symlinked over, and DEFAULT_ONNX is never touched.
#   run_acceptance2.sh, follow_person.py, perception_backends.py,
#   build_scene.py, camera_model.py and scoreboard.py are NOT modified.
#
# THE FLOOR IS ASSERTED PER FLIGHT, TWO WAYS, AND THE FLIGHT ABORTS IF IT IS WRONG:
#   the reflectance attribute in the scene.xml about to be flown, and
#   room.floor_reflectance in that scene's manifest.  Both are written into the
#   run directory so every result carries the floor it was flown on.  Every cell
#   here is matte (reflectance 0.0).
#
# THE MODEL IS VERIFIED PER FLIGHT, AFTER THE FACT:
#   follow_person.py records backend_info (onnx path, eps, onnx_sha1) into
#   summary.json.  The loop re-reads it and refuses to call a flight VALID if
#   the ONNX or the eps is not the one this row asked for.  Getting this wrong
#   would silently invalidate the whole experiment, so it is checked, not assumed.
#
# Usage: fly_plan_models.sh PLAN.tsv OUT_DIR SCENE_ROOT [START_ORDER]
set -uo pipefail

PLAN=$1; OUT=$2; SCENE_ROOT=$3; START=${4:-1}
# fly() does `cd "$HERE"` to run the follower, so every path the loop uses
# must be absolute or it breaks after the first flight.
PLAN=$(cd "$(dirname "$PLAN")" && pwd)/$(basename "$PLAN")
mkdir -p "$OUT"; OUT=$(cd "$OUT" && pwd)
SCENE_ROOT=$(cd "$SCENE_ROOT" && pwd)

HERE=/Users/saimaruvada/Downloads/drone/pytorch_ssd/tools/crazysim_macos
SCRIPTS=/Users/saimaruvada/Downloads/drone/pytorch_ssd/docs/eval_results/2026-09-13-champion-vs-confuser/scripts
DRONE_ROOT=/Users/saimaruvada/Downloads/drone
P="$DRONE_ROOT/trainenv/bin/python"
SCRATCH=/private/tmp/claude-501/-Users-saimaruvada-Downloads/90541ca8-cca5-4400-9855-79d1dde551f0/scratchpad
# A DIFFERENT path from the workstream lock this agent holds for its whole run,
# so the per-flight lock cannot deadlock against it.
LOCK="$SCRATCH/sim_models.lock"

# The two models.  Each is a RELEASE DIRECTORY; the ONNX and the eps come from
# the same directory so they can never be mixed across releases.
CHAMPION_ONNX="$DRONE_ROOT/pytorch_ssd_unstable/logs/plain_follow_prod_qat_v3/quant_eval/model_id_dory.onnx"
CONFUSER_ONNX="$DRONE_ROOT/pytorch_ssd_unstable/logs/plain_follow_eval576_confuser/quant_eval/model_id_dory.onnx"
CHAMPION_EPS=0.0002009823510888964
CONFUSER_EPS=0.00021179195027798414

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

# fly <model> <cell> <scene> <class> <backend> <camera> <speed> <dur> <rep> <att> <order>
fly() {
  local model=$1 cid=$2 scene=$3 cls=$4 backend=$5 camera=$6 speed=$7 dur=$8 rep=$9 att=${10} ord=${11}
  local onnx want_eps
  if [ "$model" = champion ]; then onnx="$CHAMPION_ONNX"; want_eps="$CHAMPION_EPS"
  else onnx="$CONFUSER_ONNX"; want_eps="$CONFUSER_EPS"; fi
  local want=0                      # every cell here is flown on the matte floor
  local sdir="$SCENE_ROOT/$scene"
  local run="$OUT/runs/${model}__${cid}__r${rep}a${att}"
  rm -rf "$run"; mkdir -p "$run"

  if [ ! -f "$sdir/scene.xml" ]; then
    log "  [$model $cid r$rep a$att] SCENE MISSING: $sdir/scene.xml"
    echo '{"error":"scene missing"}' > "$run/flight_error.json"; return 1
  fi
  if [ ! -f "$onnx" ]; then
    log "  [$model $cid r$rep a$att] ONNX MISSING: $onnx"
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
    log "  [$model $cid r$rep a$att] ABORT: floor is xml='$refl' manifest='$man_refl', wanted $want"
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
           "suite": "core", "model": "$model", "order": $ord,
           "chip_onnx": "$onnx", "expected_eps": $want_eps,
           "floor_reflectance": float("$refl"),
           "floor_reflectance_manifest": float("$man_refl")},
          open(sys.argv[1], "w"), indent=2)
PYEOF

  if docker ps -a --format '{{.Names}}' | grep -qx crazysim-mac \
     || pgrep -f "crazysim_mujoco/crazysim.py" >/dev/null; then
    log "  [$model $cid r$rep a$att] a simulator is already running; tearing it down first"
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
    # The camera seed depends ONLY on the repeat index, so the matched pair
    # (same cell, same repeat, two models) sees the SAME himax noise draw.
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
    log "  [$model $cid r$rep a$att] SIM DID NOT START"
    kill "$SIMPID" 2>/dev/null; pkill -f "crazysim_mujoco/crazysim.py" 2>/dev/null
    docker rm -f crazysim-mac >/dev/null 2>&1; SIMPID=""
    echo '{"error":"sim did not start"}' > "$run/flight_error.json"; return 1
  fi
  sleep 2

  local args=(--duration "$dur" --out "$run")
  [ "$backend" = chip ] && args+=(--backend chip --chip-onnx "$onnx")
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

log "champion-vs-confuser suite starting: plan=$PLAN out=$OUT scenes=$SCENE_ROOT start=$START"
log "  champion = $CHAMPION_ONNX (eps $CHAMPION_EPS)"
log "  confuser = $CONFUSER_ONNX (eps $CONFUSER_EPS)"
T0=$(date +%s)

NPLAN=$(grep -vc '^#' "$PLAN")
# Process substitution, not a pipe: the loop must run in THIS shell so the
# EXIT/INT trap can see SIMPID and tear the simulator down.
while IFS=$'\t' read -r ord model cid scene cls backend camera speed dur rep pair; do
  [ -z "$ord" ] && continue
  [ "$ord" -lt "$START" ] && continue

  for att in 1 2; do
    lb1=$(load1); lb5=$(load5); lb15=$(load15)
    t_start=$(date +%s)
    log "flight $ord/$NPLAN  $model  $cid  r$rep a$att  (pair $pair, load1 $lb1)"
    take_lock
    fly "$model" "$cid" "$scene" "$cls" "$backend" "$camera" "$speed" "$dur" "$rep" "$att" "$ord"
    rc=$?
    drop_lock
    t_end=$(date +%s)
    la1=$(load1); la5=$(load5); la15=$(load15)
    run="$OUT/runs/${model}__${cid}__r${rep}a${att}"

    verdict=NORUN; reason="exit $rc"
    if [ -f "$run/summary.json" ]; then
      # THE MODEL CHECK.  A flight that ran the wrong network is not a valid
      # flight, however clean its dynamics were.
      mchk="$("$P" "$SCRIPTS/check_model.py" "$run" 2>&1)"
      chk="$("$P" "$HERE/scoreboard.py" --check-run "$run" 2>&1)"
      echo "$chk" > "$run/check.txt"
      echo "$mchk" > "$run/model_check.txt"
      if ! echo "$mchk" | grep -q '^MODEL_OK'; then
        verdict=INVALID; reason="$(echo "$mchk" | cut -c1-160)"
      elif echo "$chk" | head -1 | grep -q '^VALID'; then verdict=VALID; reason=""
      else verdict=INVALID; reason="$(echo "$chk" | tail -1 | cut -c1-160)"; fi
    fi

    "$P" - "$FLIGHTS" "$run" "$ord" "$model" "$cid" "$rep" "$att" "$verdict" \
        "$t_start" "$t_end" "$lb1" "$lb5" "$lb15" "$la1" "$la5" "$la15" "$pair" "$reason" \
        <<'PYEOF' | tee -a "$PROGRESS"
import json, sys, os, datetime, csv
(_, out, run, ord_, model, cid, rep, att, verdict,
 t0, t1, lb1, lb5, lb15, la1, la5, la15, pair, reason) = sys.argv
rec = {"order": int(ord_), "model": model, "cell": cid,
       "repeat": int(rep), "attempt": int(att), "pair": int(pair),
       "verdict": verdict, "reason": reason, "run_dir": run,
       "t_start_utc": datetime.datetime.fromtimestamp(int(t0), datetime.timezone.utc)
                      .strftime("%Y-%m-%dT%H:%M:%SZ"),
       "wall_s": int(t1) - int(t0),
       "load1_before": float(lb1), "load5_before": float(lb5), "load15_before": float(lb15),
       "load1_after": float(la1), "load5_after": float(la5), "load15_after": float(la15)}
fr = os.path.join(run, "floor_reflectance.txt")
if os.path.exists(fr):
    rec["floor_reflectance"] = float(open(fr).read().strip())
fm = os.path.join(run, "floor_manifest.txt")
if os.path.exists(fm):
    rec["floor_reflectance_manifest"] = float(open(fm).read().strip())
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
print(f"  -> {verdict}  floor {rec.get('floor_reflectance')}  eps {rec.get('eps')}  "
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
