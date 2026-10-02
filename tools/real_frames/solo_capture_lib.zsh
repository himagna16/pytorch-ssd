# Shared helpers for the SOLO capture scripts (fov_capture.sh, door_control.sh).
# Sourced, never run. The caller sets HERE=${0:A:h} first.
#
# Same conventions as grid_capture.sh, so nothing new to learn:
#   spoken cues with macOS `say`          CAMERA_CHECK_QUIET=1 silences them
#   rehearsal against mock_streamer.py    CAMERA_CHECK_GRAB_ARGS=--mock (frames then go under
#                                          ~/drone_frames/_rehearsal, never next to real data)
#   countdown length                      CAMERA_CHECK_COUNTDOWN (seconds)
#   brightness gate 30-60 (0-255)         GRID_MIN_BRIGHT / GRID_MAX_BRIGHT; GRID_ACCEPT_ANY=1
#                                          records anyway. Each check is appended to
#                                          <root>/exposure_log.txt (root = ~/drone_frames, or
#                                          ~/drone_frames/_rehearsal for a mock run)
#   drone / light labels                  GRID_DRONE=09|05, GRID_LIGHT=room|night-lights|...
#
# Paths come from where the script lives, so a script run from a git worktree uses that
# worktree's tools (the two venvs sit next to every checkout, in ~/Downloads/drone).
PY=~/Downloads/drone/trainenv/bin/python
REPO=${HERE:h:h}
grab()  { $PY $REPO/tools/crazysim_macos/cpx_grab.py ${=CAMERA_CHECK_GRAB_ARGS:-} "$@"; }
score() { $PY $REPO/tools/real_frames/score_real_frames.py "$@"; }
speak() { [[ -z "${CAMERA_CHECK_QUIET:-}" ]] && command -v say >/dev/null && say "$@" & }
DRONE=${GRID_DRONE:-unknown}
LIGHT=${GRID_LIGHT:-room}; LIGHT=${LIGHT//[^A-Za-z0-9-]/-}   # labels allow letters, digits, "-" only
ROOT=~/drone_frames; [[ -n "${CAMERA_CHECK_GRAB_ARGS:-}" ]] && ROOT=~/drone_frames/_rehearsal
MOCK=""; [[ -n "${CAMERA_CHECK_GRAB_ARGS:-}" ]] && MOCK=1

wait_for_deck() {
  [[ -n "$MOCK" ]] && return 0
  echo "== waiting for the deck at 192.168.4.1:5000 (join WiFi 'WiFi streaming example')"
  local i
  for i in {1..60}; do nc -z -G 2 192.168.4.1 5000 2>/dev/null && break; sleep 2; done
  nc -z -G 2 192.168.4.1 5000 2>/dev/null || {
    echo "FAIL: deck not reachable. On the drone's WiFi? Battery in for 30 s?"; exit 2; }
  echo "   deck reachable"
}

# Pre-flight exposure check, identical in effect to grid_capture.sh: grab 5 frames into
# $D/precheck, refuse to record if the camera is black (exit 6) or outside the band (exit 7).
# Exposure is set once per power-up (2026-09-24: 4 to 146 with nothing changed), and the
# differencing in fov_fit.py and the 2x2 comparison in door_control.sh both need ONE fixed
# exposure for the whole run. Sets BRIGHT. $1 = the script's name for the log.
exposure_gate() {
  local src=$1 pre="$D/precheck"
  grab --n 5 --every 1 --out "$pre" >/dev/null 2>&1
  BRIGHT=$($PY - "$pre" <<'PYEOF'
import glob, sys
import numpy as np
from PIL import Image
fs = glob.glob(sys.argv[1] + "/*.png") + glob.glob(sys.argv[1] + "/*.jpg")
print(f"{np.mean([np.asarray(Image.open(f).convert('L')).mean() for f in fs]):.0f}" if fs else "-1")
PYEOF
)
  [[ "$BRIGHT" == <-> || "$BRIGHT" == -1 ]] || BRIGHT=-1     # python failed: treat as no frames
  echo "== camera exposure check: mean brightness $BRIGHT (0-255)"
  if (( BRIGHT < 0 )); then echo "FAIL: no frames for the exposure check (battery? WiFi?)."; exit 5; fi
  if (( BRIGHT < 15 )); then
    echo "!! The camera is BLACK (it recorded nothing at this level on 2026-09-24)."
    echo "!! Unplug the battery, plug it back in with the drone already facing the room, wait 30 s,"
    echo "!! rejoin the WiFi and run this again. Nothing was recorded."
    speak "The camera is black. Unplug and replug the battery."
    echo "$(date '+%F %T') drone=$DRONE brightness=$BRIGHT source=$src rejected-black" >> "$ROOT/exposure_log.txt" 2>/dev/null
    exit 6
  fi
  local lo=${GRID_MIN_BRIGHT:-30} hi=${GRID_MAX_BRIGHT:-60}
  if (( BRIGHT < lo || BRIGHT > hi )) && [[ -z "${GRID_ACCEPT_ANY:-}" ]]; then
    echo "!! Brightness $BRIGHT is outside the target band $lo-$hi. Unplug and replug the battery, wait 30 s,"
    echo "!! rejoin the WiFi and run again (usually 1-3 tries). Nothing was recorded."
    echo "!! (GRID_ACCEPT_ANY=1 records anyway.)"
    speak "Brightness out of range. Unplug and replug the battery."
    echo "$(date '+%F %T') drone=$DRONE brightness=$BRIGHT source=$src rejected" >> "$ROOT/exposure_log.txt" 2>/dev/null
    exit 7
  fi
  echo "$(date '+%F %T') drone=$DRONE brightness=$BRIGHT source=$src" >> "$ROOT/exposure_log.txt" 2>/dev/null
}

# countdown <seconds> [what to say when recording starts]
countdown() {
  local s
  for ((s=$1; s>0; s--)); do printf "\r   %2d " $s; ((s<=5)) && speak "$s"; sleep 1; done
  speak "${2:-Recording. Stay still.}"; printf "\r   recording...          \n"
}
