#!/bin/zsh
# Real-person detection grid, ONE drone, ONE subject, no internet needed.
#
# The project's top open question: where do REAL people's detection margins sit?
# This records a 3 x 3 grid of clips (3 distances x left/centre/right) plus an empty-room
# clip, with spoken cues so the subject can run it alone, then scores everything on the
# chip network and prints a per-position table.
#
# Layout (Sai's dorm, 1 ft floor tiles; docs/hardware/dorm_grid_capture.svg):
#   drone on a chair at the window end, lens ~0.8 m up, above the joint between tile
#   rows 1 and 2, middle column, camera facing the door. Marks, counted in tiles from
#   the LENS toward the door, each in the middle of a column:
#       5 tiles (1.52 m)   7 tiles (2.13 m)   8 tiles (2.44 m, the existing green tape)
#       LEFT = col 1 (drone's left)   CENTRE = col 3   RIGHT = col 5   (2 tiles = 0.61 m)
#
# Usage:  zsh tools/real_frames/grid_capture.sh
#         GRID_SUBJECT=p02 zsh tools/real_frames/grid_capture.sh     (another person)
#         GRID_DRONE=09 | 05   (record which drone; its camera may matter, see 2026-09-24 night)
#         GRID_LIGHT=night-lights | day-sun | ...   (label the lighting; one per grid; '_' becomes '-')
#         CAMERA_CHECK_GRAB_ARGS=--mock zsh tools/real_frames/grid_capture.sh   (rehearsal)
#         GRID_DIR=<existing folder> GRID_START=6 zsh tools/real_frames/grid_capture.sh
#             (resume after a flat battery: skips the empty clip and clips < 6, adds to the
#              same folder, then re-scores everything in it)
# If a clip gets no frames (usually the battery), the script stops recording but STILL scores
# whatever it captured, and prints the resume command.
set -u
PY=~/Downloads/drone/trainenv/bin/python
REPO=~/Downloads/drone/pytorch_ssd
grab()  { $PY $REPO/tools/crazysim_macos/cpx_grab.py ${=CAMERA_CHECK_GRAB_ARGS:-} "$@"; }
score() { $PY $REPO/tools/real_frames/score_real_frames.py "$@"; }
speak() { [[ -z "${CAMERA_CHECK_QUIET:-}" ]] && command -v say >/dev/null && say "$@" & }
# 6 s clips + 6 s countdown (was 8 + 8): a full grid must fit one 350 mAh pack (~5 min of streaming)
COUNTDOWN=${CAMERA_CHECK_COUNTDOWN:-6}
SECS=${GRID_SECONDS:-6}
DRONE=${GRID_DRONE:-unknown}   # which drone: 09 or 05 (last two digits of its radio address)
SUBJ=${GRID_SUBJECT:-p01}
LIGHT=${GRID_LIGHT:-room}; LIGHT=${LIGHT//[^A-Za-z0-9-]/-}   # labels allow letters, digits, "-" only
SUBJ=${SUBJ//[^A-Za-z0-9-]/-}
ROOT=~/drone_frames; [[ -n "${CAMERA_CHECK_GRAB_ARGS:-}" ]] && ROOT=~/drone_frames/_rehearsal   # mock runs never land next to real data
D=${GRID_DIR:-$ROOT/$(date +%F)/grid_capture_$(date +%H%M%S)}
START=${GRID_START:-0}
STOPPED=""
mkdir -p "$D" || exit 1
exec > >(tee -a "$D/grid_capture.log") 2>&1
echo "== grid capture, $(date)  subject $SUBJ  light $LIGHT  drone $DRONE  folder: $D"

if [[ -z "${CAMERA_CHECK_GRAB_ARGS:-}" ]]; then
  echo "== waiting for the deck at 192.168.4.1:5000 (join WiFi 'WiFi streaming example')"
  for i in {1..60}; do nc -z -G 2 192.168.4.1 5000 2>/dev/null && break; sleep 2; done
  nc -z -G 2 192.168.4.1 5000 2>/dev/null || { echo "FAIL: deck not reachable. On the drone's WiFi? Battery in for 30 s?"; exit 2; }
  echo "   deck reachable"
fi

# --- pre-flight exposure check (added 2026-09-24 22:00, after a full run recorded only black noise):
# grab 5 frames; refuse to record if the camera is black, warn if it came up in the bright mode.
PRE=$(mktemp -d /tmp/grid_pre_XXXX)
grab --n 5 --every 1 --out "$PRE" >/dev/null 2>&1
B=$($PY -c "import glob,numpy as n;from PIL import Image;fs=glob.glob('$PRE/*.png')+glob.glob('$PRE/*.jpg');print(f'{n.mean([n.asarray(Image.open(f).convert(\"L\")).mean() for f in fs]):.0f}' if fs else '-1')")
rm -rf "$PRE"
echo "== camera exposure check: mean brightness $B (0-255)"
if (( B < 0 )); then echo "FAIL: no frames for the exposure check."; exit 5; fi
if (( B < 15 )); then
  echo "!! The camera is BLACK (it recorded nothing at this level on 2026-09-24)."
  echo "!! Unplug the battery, plug it back in with the drone already facing the room, wait 30 s,"
  echo "!! rejoin the WiFi and run this again. Nothing was recorded."
  speak "The camera is black. Unplug and replug the battery."
  exit 6
fi
(( B > 70 )) && echo "   note: bright exposure mode (~90). Detection was weaker in this mode on 2026-09-24. Recording anyway; it is labelled by brightness."
echo "$(date '+%F %T') drone=$DRONE brightness=$B source=grid_capture" >> ~/drone_frames/exposure_log.txt 2>/dev/null

countdown() { for ((s=COUNTDOWN; s>0; s--)); do printf "\r   %2d " $s; ((s<=5)) && speak "$s"; sleep 1; done
              speak "Recording. Stay still."; printf "\r   recording ${1} s...\n"; }

# --- empty room first, while you are behind the drone anyway
if (( START == 0 )); then
echo; echo "== clip 0 of 9: EMPTY ROOM. Stand BEHIND the drone."
read "?   press Enter, then stay out of view "
speak "Empty room. Stay behind the drone."; countdown 12
grab --seconds 12 --every 1 --vis 0 --subject empty --light "$LIGHT" --out "$D" || { echo "FAIL: empty clip"; exit 3; }
speak "Done."
fi

# --- 3 x 3 grid, far to near so you walk toward the drone
n=0
for spec in "8 2.44 14.0" "7 2.13 15.9" "5 1.52 21.8"; do
  set -- ${=spec}; tiles=$1; dist=$2; b=$3
  for side in LEFT CENTRE RIGHT; do
    n=$((n+1))
    (( n < START )) && continue
    [[ -n "$STOPPED" ]] && continue
    case $side in LEFT) bear=-$b; col="col 1";; CENTRE) bear=0; col="col 3";; RIGHT) bear=$b; col="col 5";; esac
    echo; echo "== clip $n of 9: ${tiles} tiles out, ${side} ($col), ${dist} m, bearing ${bear}. Face the drone."
    read "?   press Enter, then walk to the mark "
    speak "${tiles} tiles, ${side}."
    countdown $SECS
    if ! grab --seconds $SECS --every 1 --dist $dist --bearing $bear --vis 1 --subject "$SUBJ" --light "$LIGHT" --out "$D"; then
      echo "!! clip $n got no frames: most likely the BATTERY (the camera browns out first)."
      echo "!! Scoring what was captured. To finish later with a charged battery:"
      echo "!!   GRID_DIR=$D GRID_START=$n zsh ~/Downloads/drone/pytorch_ssd/tools/real_frames/grid_capture.sh"
      speak "No frames. The battery is probably flat. Scoring what we have."
      STOPPED=$n; continue
    fi
    speak "Done."
  done
done
[[ -z "$STOPPED" ]] && speak "All clips done. Come back to the laptop."

echo; echo "== scoring on the chip network (offline)"
score "$D" --json "$D/grid_scores.json" > "$D/grid_score.txt" 2>&1
grep -hE "^(EMPTY|MIRROR)" "$D/grid_score.txt"

echo; echo "== per-position table (chip network, follower enter bar 0.75)"
$PY - "$D" <<'PYEOF'
import csv, sys, statistics as st
from collections import defaultdict
rows = list(csv.DictReader(open(sys.argv[1] + "/scores.csv")))
cells = defaultdict(list)
for r in rows:
    key = ("empty", "") if r["vis"] == "0" else (f"{float(r['dist']):.2f} m", f"{float(r['bearing']):+.1f}")
    cells[key].append(r)
print(f"{'position':<22}{'frames':>7}{'median conf':>13}{'>=0.75':>8}{'locked':>8}{'x-bin (expected)':>19}")
for key in sorted(cells, key=lambda k: (k[0] == "empty", k)):
    rs = cells[key]; conf = [float(r["conf"]) for r in rs]
    hi = sum(c >= 0.75 for c in conf); lock = sum(r["tracking"] == "1" for r in rs)
    bins = [r["x_bin"] for r in rs if float(r["conf"]) >= 0.5]
    mode = max(set(bins), key=bins.count) if bins else "-"
    exp = rs[0].get("exp_bin", "") or "-"
    name = "EMPTY ROOM" if key[0] == "empty" else f"{key[0]} @ {key[1]} deg"
    print(f"{name:<22}{len(rs):>7}{st.median(conf):>13.2f}{hi:>5}/{len(rs):<3}{lock:>4}/{len(rs):<4}{mode:>9} ({exp})")
print("\nlocked = frames where the drone's follower would be tracking (3 in a row >= 0.75).")
print("For the EMPTY ROOM row, locked should be 0.")

# brightness guard: one grid = one lighting condition (added after the 2026-09-24 run, where
# a resumed half came out 2.3x brighter than the first half and could not be pooled)
import glob, os, re
import numpy as np
from PIL import Image
means = defaultdict(list)
for p in glob.glob(sys.argv[1] + "/*.png"):
    means[re.sub(r"_f\d+_t.*", "", os.path.basename(p))].append(np.asarray(Image.open(p).convert("L")).mean())
per = {k: float(np.mean(v)) for k, v in means.items()}
if per:
    lo, hi = min(per.values()), max(per.values())
    if lo < 15:
        print("!! NEAR-BLACK FRAMES (mean < 15): the camera is not exposing properly (battery dying?).")
        print("!! On 2026-09-24 near-black empty frames scored 0.83 and LOCKED: do not trust this run.")
    print(f"\nframe brightness per clip: {lo:.0f} to {hi:.0f} (0-255)")
    if lo > 0 and hi / lo > 1.3:
        print("!! BRIGHTNESS CHANGED during this grid (more than 30%). These clips are not one lighting")
        print("!! condition. Do not pool them; re-run the whole grid in one sitting.")
        for k, v in sorted(per.items(), key=lambda kv: kv[1]):
            print(f"   {v:6.1f}  {k}")
PYEOF
echo
echo "== done. Rejoin normal WiFi, then tell Claude:  grid done, folder $D"
echo "   Frames stay on this laptop; they show a real person, never commit them."
