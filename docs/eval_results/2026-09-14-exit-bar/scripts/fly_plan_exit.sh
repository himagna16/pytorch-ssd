#!/usr/bin/env bash
# Fly the interleaved exit-bar plan, one flight at a time.
#
# WHY THIS EXISTS INSTEAD OF run_acceptance2.sh
#   run_acceptance2.sh has NO way to pass a detection threshold through to
#   follow_person.py: it builds its argument list at line ~218 as
#     --duration <dur> --out <run> [--backend chip] [--rate-hz 6.5 --latency-ms 153]
#   and nothing else, so follow_person.py always takes its DEFAULTS
#   (vis_enter 0.75, confirm_frames 3, vis_exit 0.45).  `grep -n vis_exit
#   run_acceptance2.sh` returns nothing.  Rather than edit the harness -- the
#   brief forbids touching tools/ -- the fly() body below is a faithful copy of
#   the harness's own fly(), with exactly two deliberate changes, both of which
#   earlier agents in this repo also made (see
#   docs/eval_results/2026-09-13-champion-vs-confuser/scripts/fly_plan_models.sh):
#     - the order comes from the plan file, not from a nested cell x repeat loop,
#       so arms can be interleaved and repeat index decorrelated from time;
#     - load average is sampled immediately before and after every flight;
#   plus the one new thing this experiment needs:
#     - THE EXIT BAR IS A PARAMETER, passed to the repo's own follow_person.py
#       as --vis-exit.  --vis-enter 0.75 and --confirm-frames 3 are ALSO passed
#       explicitly, at their default values, so all three arms are constructed
#       identically and the enter bar is pinned on the command line rather than
#       inherited.  For the 0.45 control arm this command line is behaviourally
#       identical to the harness's (it passes the same values the defaults give).
#   run_acceptance2.sh, follow_person.py, camera_model.py, build_scene.py,
#   scoreboard.py and patch_crazysim.py are NOT modified.
#
# THE FLOOR IS ASSERTED PER FLIGHT, TWO WAYS, AND THE FLIGHT ABORTS IF IT IS WRONG:
#   the reflectance attribute in the scene.xml about to be flown, and
#   room.floor_reflectance in that scene's manifest.  Both are written into the
#   run dir.  Every cell here is matte (reflectance 0.0).
#
# THE THRESHOLDS ARE VERIFIED PER FLIGHT, AFTER THE FACT:
#   follow_person.py records vis_enter / vis_exit / confirm_frames into
#   summary.json.  The loop re-reads them and refuses to call a flight VALID if
#   they are not the ones this row asked for.  A flight that ran the wrong
#   threshold is not a valid flight however clean its dynamics were.
#
# Usage: fly_plan_exit.sh PLAN.tsv OUT_DIR SCENE_ROOT [START_ORDER] [STOP_EPOCH]
set -uo pipefail

PLAN=$1; OUT=$2; SCENE_ROOT=$3; START=${4:-1}; STOP_EPOCH=${5:-0}
PLAN=$(cd "$(dirname "$PLAN")" && pwd)/$(basename "$PLAN")
mkdir -p "$OUT"; OUT=$(cd "$OUT" && pwd)
SCENE_ROOT=$(cd "$SCENE_ROOT" && pwd)

HERE=/Users/saimaruvada/Downloads/drone/pytorch_ssd/tools/crazysim_macos
DRONE_ROOT=/Users/saimaruvada/Downloads/drone
P="$DRONE_ROOT/trainenv/bin/python"
SCRATCH=/private/tmp/claude-501/-Users-saimaruvada-Downloads/90541ca8-cca5-4400-9855-79d1dde551f0/scratchpad
# A DIFFERENT path from the workstream lock this agent holds for its whole run.
LOCK="$SCRATCH/sim_exit.lock"

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

# fly <vis_exit> <cell> <scene> <class> <backend> <camera> <speed> <dur> <rep> <att> <order>
fly() {
  local vexit=$1 cid=$2 scene=$3 cls=$4 backend=$5 camera=$6 speed=$7 dur=$8 rep=$9 att=${10} ord=${11}
  local venter=0.75 cframes=3
  local want=0                      # every cell here is flown on the matte floor
  local sdir="$SCENE_ROOT/$scene"
  local run="$OUT/runs/x${vexit}__${cid}__r${rep}a${att}"
  rm -rf "$run"; mkdir -p "$run"

  if [ ! -f "$sdir/scene.xml" ]; then
    log "  [x$vexit $cid r$rep a$att] SCENE MISSING: $sdir/scene.xml"
    echo '{"error":"scene missing"}' > "$run/flight_error.json"; return 1
  fi

  local refl man_refl
  refl=$(grep -o 'reflectance="[^"]*"' "$sdir/scene.xml" | head -1 | sed 's/.*="//;s/"//')
  man_refl=$("$P" -c "import json,sys;print(json.load(open(sys.argv[1]))['room']['floor_reflectance'])" \
             "$sdir/manifest.json" 2>/dev/null)
  if [ "$(echo "$refl $want" | awk '{print ($1==$2)?"ok":"no"}')" != ok ] \
     || [ "$(echo "$man_refl $want" | awk '{print ($1==$2)?"ok":"no"}')" != ok ]; then
    log "  [x$vexit $cid r$rep a$att] ABORT: floor is xml='$refl' manifest='$man_refl', wanted $want"
    echo "{\"error\":\"wrong floor: xml=$refl manifest=$man_refl want=$want\"}" > "$run/flight_error.json"
    return 1
  fi
  echo "$refl" > "$run/floor_reflectance.txt"
  echo "$man_refl" > "$run/floor_manifest.txt"

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
           "suite": "core", "order": $ord,
           "vis_enter": $venter, "vis_exit": $vexit, "confirm_frames": $cframes,
           "floor_reflectance": float("$refl"),
           "floor_reflectance_manifest": float("$man_refl")},
          open(sys.argv[1], "w"), indent=2)
PYEOF

  if docker ps -a --format '{{.Names}}' | grep -qx crazysim-mac \
     || pgrep -f "crazysim_mujoco/crazysim.py" >/dev/null; then
    log "  [x$vexit $cid r$rep a$att] a simulator is already running; tearing it down first"
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
    # The harness's own seed rule.  It depends ONLY on the repeat index, so the
    # three arms at the same repeat see the SAME himax noise draw.
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
    log "  [x$vexit $cid r$rep a$att] SIM DID NOT START"
    kill "$SIMPID" 2>/dev/null; pkill -f "crazysim_mujoco/crazysim.py" 2>/dev/null
    docker rm -f crazysim-mac >/dev/null 2>&1; SIMPID=""
    echo '{"error":"sim did not start"}' > "$run/flight_error.json"; return 1
  fi
  sleep 2

  local args=(--duration "$dur" --out "$run")
  [ "$backend" = chip ] && args+=(--backend chip)
  [ "$speed" = chip ] && args+=(--rate-hz 6.5 --latency-ms 153)
  args+=(--vis-enter "$venter" --confirm-frames "$cframes" --vis-exit "$vexit")
  echo "$P follow_person.py ${args[*]}" > "$run/follow_cmd.txt"
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

log "exit-bar suite starting: plan=$PLAN out=$OUT scenes=$SCENE_ROOT start=$START stop_epoch=$STOP_EPOCH"
T0=$(date +%s)
NPLAN=$(grep -vc '^#' "$PLAN")

while IFS=$'\t' read -r ord vexit cid scene cls backend camera speed dur rep block; do
  [ -z "$ord" ] && continue
  [ "$ord" -lt "$START" ] && continue
  if [ "$STOP_EPOCH" != 0 ] && [ "$(date +%s)" -ge "$STOP_EPOCH" ]; then
    log "STOP EPOCH REACHED before flight $ord - not starting it"; break
  fi

  for att in 1 2; do
    lb1=$(load1); lb5=$(load5); lb15=$(load15)
    t_start=$(date +%s)
    log "flight $ord/$NPLAN  vis_exit $vexit  $cid  r$rep a$att  (block $block, seed $((1000+rep)), load1 $lb1)"
    take_lock
    fly "$vexit" "$cid" "$scene" "$cls" "$backend" "$camera" "$speed" "$dur" "$rep" "$att" "$ord"
    rc=$?
    drop_lock
    t_end=$(date +%s)
    la1=$(load1); la5=$(load5); la15=$(load15)
    run="$OUT/runs/x${vexit}__${cid}__r${rep}a${att}"

    verdict=NORUN; reason="exit $rc"
    if [ -f "$run/summary.json" ]; then
      tchk="$("$P" -c "
import json,sys
s=json.load(open(sys.argv[1]))
want=(float(sys.argv[2]),float(sys.argv[3]),int(sys.argv[4]))
got=(s.get('vis_enter'),s.get('vis_exit'),s.get('confirm_frames'))
if got[0]==want[0] and got[1]==want[1] and got[2]==want[2]:
    print('THRESH_OK enter=%s exit=%s cf=%s'%got)
else:
    print('THRESH_MISMATCH got enter=%s exit=%s cf=%s want enter=%s exit=%s cf=%s'%(got+want))
" "$run/summary.json" 0.75 "$vexit" 3 2>&1)"
      chk="$("$P" "$HERE/scoreboard.py" --check-run "$run" 2>&1)"
      echo "$chk" > "$run/check.txt"
      echo "$tchk" > "$run/thresh_check.txt"
      if ! echo "$tchk" | grep -q '^THRESH_OK'; then
        verdict=INVALID; reason="$(echo "$tchk" | cut -c1-160)"
      elif echo "$chk" | head -1 | grep -q '^VALID'; then verdict=VALID; reason=""
      else verdict=INVALID; reason="$(echo "$chk" | tail -1 | cut -c1-160)"; fi
    fi

    "$P" - "$FLIGHTS" "$run" "$ord" "$vexit" "$cid" "$rep" "$att" "$verdict" \
        "$t_start" "$t_end" "$lb1" "$lb5" "$lb15" "$la1" "$la5" "$la15" "$block" "$reason" \
        <<'PYEOF' | tee -a "$PROGRESS"
import json, sys, os, datetime, csv
(_, out, run, ord_, vexit, cid, rep, att, verdict,
 t0, t1, lb1, lb5, lb15, la1, la5, la15, block, reason) = sys.argv
rec = {"order": int(ord_), "vis_exit_planned": float(vexit), "cell": cid,
       "repeat": int(rep), "attempt": int(att), "block": int(block),
       "seed": 1000 + int(rep),
       "verdict": verdict, "reason": reason, "run_dir": run,
       "t_start_utc": datetime.datetime.fromtimestamp(int(t0), datetime.timezone.utc)
                      .strftime("%Y-%m-%dT%H:%M:%SZ"),
       "wall_s": int(t1) - int(t0),
       "load1_before": float(lb1), "load5_before": float(lb5), "load15_before": float(lb15),
       "load1_after": float(la1), "load5_after": float(la5), "load15_after": float(la15)}
for nm, key in (("floor_reflectance.txt", "floor_reflectance"),
                ("floor_manifest.txt", "floor_reflectance_manifest")):
    p = os.path.join(run, nm)
    if os.path.exists(p):
        rec[key] = float(open(p).read().strip())
sp = os.path.join(run, "summary.json")
if os.path.exists(sp):
    s = json.load(open(sp))
    for k in ("sim_wall_ratio", "processed_hz", "loop_hz", "tracking_fraction",
              "frames_processed", "frames_dropped", "torn_frames", "z_max",
              "end_reason", "step_gap_ms", "vis_enter", "vis_exit",
              "confirm_frames", "stale_events"):
        rec[k] = s.get(k)
    bi = s.get("backend_info") or {}
    rec["onnx_sha1"] = bi.get("onnx_sha1")
fl = os.path.join(run, "follow_log.csv")
FLOOR_M = 0.25
if os.path.exists(fl):
    mp = mr = 0.0; minz = None; ups = 0; below = 0; n = 0
    with open(fl) as f:
        for row in csv.DictReader(f):
            try:
                p = abs(float(row["pitch"])); r = abs(float(row["roll"])); z = float(row["pz"])
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
print(f"  -> {verdict}  floor {rec.get('floor_reflectance')}  "
      f"enter {rec.get('vis_enter')} exit {rec.get('vis_exit')} cf {rec.get('confirm_frames')}  "
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
