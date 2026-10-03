#!/bin/zsh
# The DARK-DOOR CONTROL, solo: same CENTRE mark, only the background and the top change.
#
# The 2026-09-24 grids missed Sai dead centre at 2.1-2.4 m, in front of the dark door, in
# two separate dim runs, while the sides (bright wardrobe behind him) locked 71-88 %.
# Position and background changed together there. This holds the position fixed and
# changes one thing at a time:
#                       dark top        light top
#     door BARE         clip 1          clip 2
#     light SHEET       clip 4          clip 3        (order chosen: 1 sheet change, 2 top changes)
# plus an EMPTY clip before (door bare) and after (sheet still up), so the sheet's own
# effect on the empty-room confidence is measured too. Then it scores everything on the
# chip network and prints the 2 x 2 table. ~4 min, ONE battery, ONE power-up (exposure is
# set at power-up; the four cells are only comparable within one).
#
# Layout: exactly grid_capture.sh's (docs/hardware/dorm_grid_capture.svg). You stand on
# the CENTRE X at 7 tiles (2.13 m, the line where row 8 ends, middle of col 3), facing the
# drone. Laptop BEHIND the drone (you press Enter there, then walk to the X in the countdown).
#
# BEFORE you plug the battery in (the changes must be quick, the battery lasts ~5-7 min):
#   * the light sheet ready to cover the WHOLE door in one move: e.g. its top edge tucked
#     over the top of the door, the rest rolled up and held by one clip you can pull;
#   * wear the DARK top; the LIGHT top within reach (a light shirt that pulls on over the
#     dark one is fastest);
#   * no mirror uncovered, curtains as for the grid, same room lights as you will keep.
#
# Labels (what score_real_frames.py reads from the filename): d2.13 b0 vis1 subj-p01 and
#   light-<GRID_LIGHT>-door<bare|sheet>-top<dark|light>; the empty clips are vis0
#   subj-empty light-<GRID_LIGHT>-door<bare|sheet>. The condition rides in the `light`
#   token because that is the free-form condition slot the scorer groups by; the subject
#   stays exactly p01 so person-ID parsing (index_frames.py, PR #10) still works.
#   door_session.json repeats the plan with explicit door/top fields.
#
# Usage:  GRID_DRONE=09 zsh tools/real_frames/door_control.sh
#         GRID_SUBJECT=p01  GRID_LIGHT=room  DOOR_DIST=2.13  DOOR_SECONDS=6  DOOR_EMPTY_SECONDS=10
#         CAMERA_CHECK_COUNTDOWN=6 (walk-to-the-X countdown)
#         CAMERA_CHECK_GRAB_ARGS="--mock --port 5057" ...   rehearsal against mock_streamer.py
#         DOOR_DIR=<folder> DOOR_START=3 zsh .../door_control.sh   resume after a flat battery
#             (skips clips < 3, adds to the same folder, re-scores everything). A resume is a
#             NEW power-up: the per-clip brightness table says whether the halves can be pooled.
set -u
HERE=${0:A:h}
source "$HERE/solo_capture_lib.zsh" || exit 1
SUBJ=${GRID_SUBJECT:-p01}; SUBJ=${SUBJ//[^A-Za-z0-9-]/-}
DIST=${DOOR_DIST:-2.13}
SECS=${DOOR_SECONDS:-6}
EMPTY_SECS=${DOOR_EMPTY_SECONDS:-10}
COUNTDOWN=${CAMERA_CHECK_COUNTDOWN:-6}
START=${DOOR_START:-0}
D=${DOOR_DIR:-$ROOT/$(date +%F)/door_control_$(date +%H%M%S)}
C=$D/clips
STOPPED=""
mkdir -p "$C" || exit 1
exec > >(tee -a "$D/door_control.log") 2>&1
T0=$SECONDS
echo "== door control, $(date)  subject $SUBJ  light $LIGHT  drone $DRONE  folder: $D"
(( START > 0 )) && echo "!! RESUMING at clip $START: this is a new power-up; compare the brightness lines at the end."

# kind door top | what to do before the clip | what the laptop says
specs=(
  "empty bare -|EMPTY ROOM, door BARE. Stand BEHIND the drone (at the laptop) and stay there.|Empty room first. Stay behind the drone."
  "person bare dark|YOU on the CENTRE X (7 tiles), DARK top, door BARE. Face the drone.|Dark top, door bare. Walk to the centre mark."
  "person bare light|Put on the LIGHT top. The door stays BARE. Then the CENTRE X, face the drone.|Next: put on the light top. Door stays bare."
  "person sheet light|Hang the LIGHT SHEET over the WHOLE door. Keep the light top. Then the CENTRE X.|Next: hang the sheet over the door. Keep the light top."
  "person sheet dark|Take the light top OFF: DARK top. The sheet STAYS up. Then the CENTRE X.|Next: dark top again. The sheet stays up."
  "empty sheet -|EMPTY ROOM, sheet still UP. Stand BEHIND the drone and stay there.|Last one. Empty room, sheet still up. Stay behind the drone."
)

$PY - "$D" "$SUBJ" "$LIGHT" "$DRONE" "$DIST" "$SECS" "$EMPTY_SECS" "$START" "${MOCK:-0}" <<'PYEOF'
import json, sys, time
from pathlib import Path
d, subj, light, drone, dist, secs, esecs, start, mock = sys.argv[1:]
p = Path(d) / "door_session.json"
plan = [("empty", "bare", None), ("person", "bare", "dark"), ("person", "bare", "light"),
        ("person", "sheet", "light"), ("person", "sheet", "dark"), ("empty", "sheet", None)]
clips = []
for i, (kind, door, top) in enumerate(plan):
    lab = f"{light}-door{door}" + (f"-top{top}" if top else "")
    clips.append({"index": i, "kind": kind, "door": door, "top": top, "light_label": lab,
                  "vis": 1 if kind == "person" else 0, "subject": subj if kind == "person" else "empty",
                  "dist_m": float(dist) if kind == "person" else None,
                  "bearing_deg": 0.0 if kind == "person" else None,
                  "seconds": float(secs if kind == "person" else esecs)})
s = json.loads(p.read_text()) if p.exists() else {
    "tool": "door_control.sh", "created": time.strftime("%Y-%m-%d %H:%M:%S"), "subject": subj,
    "light": light, "drone": drone, "mark": "CENTRE X, 7 tiles = 2.13 m, bearing 0 (dorm grid layout)",
    "mock": mock == "1", "clips": clips, "runs": []}
s["runs"].append({"started": time.strftime("%Y-%m-%d %H:%M:%S"), "start_clip": int(start)})
p.write_text(json.dumps(s, indent=2))
PYEOF

wait_for_deck
exposure_gate door_control

for ((n=0; n<${#specs}; n++)); do
  (( n < START )) && continue
  [[ -n "$STOPPED" ]] && break
  spec=("${(@s:|:)specs[n+1]}")
  set -- ${=spec[1]}; kind=$1; door=$2; top=$3
  if [[ $kind == empty ]]; then lab="${LIGHT}-door${door}"; secs=$EMPTY_SECS
  else lab="${LIGHT}-door${door}-top${top}"; secs=$SECS; fi
  take=1   # a resumed clip that already has frames gets the next take, never an overwrite
  while true; do existing=($C/*_light-${lab}_take${take}_*(N)); (( ${#existing} )) || break; take=$((take+1)); done
  echo
  echo "== clip $n of 5: ${spec[2]}"
  speak "${spec[3]}"
  if [[ $kind == empty ]]; then
    read "?   press Enter, then stay out of view "
    speak "Stay behind the drone."
    countdown $COUNTDOWN "Recording. Stay out of view."
    grab --seconds $secs --every 1 --vis 0 --subject empty --light "$lab" --take $take --out "$C"; rc=$?
  else
    read "?   press Enter, then walk to the CENTRE X and face the drone "
    speak "Walk to the centre mark."
    countdown $COUNTDOWN
    grab --seconds $secs --every 1 --dist $DIST --bearing 0 --vis 1 --subject "$SUBJ" --light "$lab" --take $take --out "$C"; rc=$?
  fi
  if (( rc != 0 )); then
    echo "!! clip $n got no frames: most likely the BATTERY (the camera browns out first)."
    echo "!! Scoring what was captured. To finish later with a charged battery:"
    echo "!!   DOOR_DIR=$D DOOR_START=$n zsh $HERE/door_control.sh"
    echo "!! (a new battery is a new exposure: check the brightness lines before pooling)"
    speak "No frames. The battery is probably flat. Scoring what we have."
    STOPPED=$n
    break
  fi
  speak "Done."
done
[[ -z "$STOPPED" ]] && speak "All clips done. Scoring."

echo
echo "== scoring on the chip network (offline)"
score "$C" --backend chip --json "$D/door_scores.json" > "$D/door_score.txt" 2>&1
SRC=$?
grep -hE "^EMPTY" "$D/door_score.txt"   # (its MIRROR CHECK line is meaningless here: every clip is at bearing 0)
if (( SRC != 0 )) || [[ ! -s "$C/scores.csv" ]]; then
  echo "!! scoring failed (exit $SRC); the scorer said:"; tail -15 "$D/door_score.txt"
  echo "== frames are safe in $C; score later with: score_real_frames.py $C --backend chip"
  exit 4
fi

echo
echo "== the 2 x 2 (chip network; follower enter bar 0.75; person on the CENTRE mark, ${DIST} m, bearing 0)"
$PY - "$D" <<'PYEOF'
import csv, glob, os, re, statistics as st, sys
from collections import defaultdict
import numpy as np
from PIL import Image
D = sys.argv[1]
rows = list(csv.DictReader(open(D + "/clips/scores.csv")))
RX = re.compile(r"-door(bare|sheet)(?:-top(dark|light))?$")
cells, empties = defaultdict(list), defaultdict(list)
for r in rows:
    m = RX.search(r["light"])
    if not m:
        continue
    (empties[m.group(1)] if r["vis"] == "0" else cells[(m.group(1), m.group(2))]).append(r)

def stats(rs):
    conf = [float(r["conf"]) for r in rs]
    hi = sum(c >= 0.75 for c in conf)
    lock = sum(r["tracking"] == "1" for r in rs)
    bins = [r["x_bin"] for r in rs if float(r["conf"]) >= 0.5]
    mode = max(set(bins), key=bins.count) if bins else "-"
    return {"n": len(rs), "med": st.median(conf) if conf else float("nan"), "peak": max(conf) if conf else float("nan"),
            "hi": hi, "lock": lock, "bin": mode}

def cell_txt(rs):
    if not rs:
        return "not recorded"
    s = stats(rs)
    return f"med {s['med']:.2f}  >=.75 {s['hi']:>2}/{s['n']:<2}  lock {s['lock']:>2}  bin {s['bin']:<2}"

print(f"{'':14}{'DARK top':<42}{'LIGHT top'}")
for door in ("bare", "sheet"):
    print(f"{'door ' + door.upper():<14}{cell_txt(cells[(door, 'dark')]):<42}{cell_txt(cells[(door, 'light')])}")
print("   med = median confidence, >=.75 = frames at or over the follower's enter bar, lock = frames the")
print("   follower would be tracking (3 in a row >= 0.75), bin = most common x-bin when conf >= 0.5")
print("   (expected 4 for bearing 0; 5 if the camera is aimed ~6 deg left, see fov_fit.py)")
print()
for door, label in (("bare", "door bare, before"), ("sheet", "sheet up, after")):
    rs = empties[door]
    if rs:
        s = stats(rs)
        print(f"EMPTY ({label}): {s['n']} frames, median {s['med']:.2f}, PEAK {s['peak']:.2f}, "
              f">=0.75 {s['hi']}/{s['n']}, locked {s['lock']}/{s['n']}" +
              ("   !! the empty room reaches the enter bar" if s["peak"] >= 0.75 else ""))
    else:
        print(f"EMPTY ({label}): not recorded")

def med(k):
    rs = cells.get(k) or []
    return st.median([float(r["conf"]) for r in rs]) if rs else None
d_sheet = [(t, med(("sheet", t)), med(("bare", t))) for t in ("dark", "light")]
d_top = [(dr, med((dr, "light")), med((dr, "dark"))) for dr in ("bare", "sheet")]
print()
print("Read it: DOWN a column = the background's effect (same top); ALONG a row = the top's effect.")
for t, a, b in d_sheet:
    if a is not None and b is not None:
        print(f"   sheet minus bare, {t} top:  {a - b:+.2f} median confidence")
for dr, a, b in d_top:
    if a is not None and b is not None:
        print(f"   light minus dark top, door {dr}: {a - b:+.2f}")
both = [a - b for _, a, b in d_sheet if a is not None and b is not None]
if len(both) == 2:
    if min(both) >= 0.10:
        print("   -> the sheet raises confidence with EITHER top: the dark door (background contrast) is a cause.")
    elif max(both) <= 0.05:
        print("   -> the sheet does not help: the dark door does NOT explain the centre misses.")
    else:
        print("   -> mixed: the sheet helps with one top only (contrast between YOU and what is behind you).")
n_cell = min((len(v) for v in cells.values() if v), default=0)
print(f"   (n = {n_cell}+ frames per cell, one person, one session: a direction, not a proof)")

# brightness guard, as in grid_capture.sh: one run = one exposure
means = defaultdict(list)
for p in glob.glob(D + "/clips/*.png"):
    means[re.sub(r"_f\d+_t.*", "", os.path.basename(p))].append(np.asarray(Image.open(p).convert("L")).mean())
per = {k: float(np.mean(v)) for k, v in means.items()}
if per:
    print("\nframe brightness per clip (0-255):")
    for k, v in sorted(per.items()):
        print(f"   {v:6.1f}  {k}")
    lo, hi = min(per.values()), max(per.values())
    if lo < 15:
        print("!! NEAR-BLACK FRAMES (mean < 15): the camera is not exposing properly; do not trust this run.")
    if lo > 0 and hi / lo > 1.3:
        print("!! Brightness differs by more than 30% between clips. The sheet brightens the scene by")
        print("!! itself (compare the two EMPTY lines' clips); a change in the person clips beyond that")
        print("!! means the exposure changed (a resumed run?): do not pool across it.")
PYEOF
echo
echo "== done in $(( SECONDS - T0 )) s. Folder: $D"
echo "   Rejoin normal WiFi, then tell Claude:  door control done, folder $D"
echo "   Frames stay on this laptop; they show a real person, never commit them."
speak "Door control finished. The table is on the laptop."
[[ -n "$STOPPED" ]] && exit 3
exit 0
