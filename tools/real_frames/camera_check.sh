#!/bin/zsh
# One-command camera + mirror check for ONE drone, runnable with no internet.
#
# Why this exists: joining the AI-deck's WiFi ("WiFi streaming example") takes the
# laptop off the internet, so nobody can talk you through it live. This script does
# the whole check offline and prints the verdict; send the output afterwards.
#
# What it does:
#   1. waits until the deck answers at 192.168.4.1:5000
#   2. grabs 5 frames (stream check: read fmt= on each line)
#   3. mirror check: two 10 s clips at 2.5 m, first on the drone's LEFT (-25 deg),
#      then its RIGHT (+25 deg), with a countdown so you can be the subject yourself
#   4. scores the mirror folder on the chip network and prints the MIRROR CHECK line
#
# Setup: drone on a stack of books or a chair, lens ~0.8 m up, level. Props may stay on:
# nothing here talks to the motors (no radio, no cfclient, WiFi camera only).
# "Drone's LEFT" = your left if you stand BEHIND the drone looking where it looks.
# At 2.5 m, 25 degrees is ~1.17 m to the side of the centre line.
#
# Usage:  zsh tools/real_frames/camera_check.sh            (real drone)
#         CAMERA_CHECK_GRAB_ARGS=--mock zsh tools/real_frames/camera_check.sh
#                                                          (rehearsal vs mock_streamer)
set -u
PY=~/Downloads/drone/trainenv/bin/python
REPO=~/Downloads/drone/pytorch_ssd
grab()  { $PY $REPO/tools/crazysim_macos/cpx_grab.py ${=CAMERA_CHECK_GRAB_ARGS:-} "$@"; }
score() { $PY $REPO/tools/real_frames/score_real_frames.py "$@"; }
COUNTDOWN=${CAMERA_CHECK_COUNTDOWN:-10}
D=~/drone_frames/$(date +%F)/camera_check_$(date +%H%M%S)
mkdir -p "$D" || exit 1
LOG="$D/camera_check.log"
exec > >(tee -a "$LOG") 2>&1
echo "== camera check, $(date)  folder: $D"

if [[ -z "${CAMERA_CHECK_GRAB_ARGS:-}" ]]; then
  echo "== 1. waiting for the deck at 192.168.4.1:5000 (join WiFi 'WiFi streaming example')"
  for i in {1..60}; do nc -z -G 2 192.168.4.1 5000 2>/dev/null && break; sleep 2; done
  nc -z -G 2 192.168.4.1 5000 2>/dev/null || { echo "FAIL: deck not reachable. Is the laptop on the drone's WiFi? Battery charged? Wait 30 s after plugging the battery in."; exit 2; }
  echo "   deck reachable"
fi

echo "== 2. stream check (5 frames)"
grab --n 5 --every 1 --out "$D/check" || { echo "FAIL: stream check. Send this log."; exit 3; }

clip() {  # $1 bearing  $2 words
  echo
  echo "== mirror clip: stand 2.5 m out, on the drone's $2 (bearing $1), facing the drone"
  read "?   press Enter, then walk to the mark (${COUNTDOWN} s countdown) "
  for ((s=COUNTDOWN; s>0; s--)); do printf "\r   %2d " $s; sleep 1; done; printf "\r   recording 10 s...\n"
  grab --seconds 10 --every 1 --dist 2.5 --bearing $1 --vis 1 --subject p01 \
       --light room --out "$D/mirror" || { echo "FAIL: clip $2"; exit 4; }
}
echo "== 3. mirror check"
clip -25 LEFT
clip 25 RIGHT

echo
echo "== 4. scoring on the chip network (offline)"
score "$D/mirror" --json "$D/mirror_scores.json" | tee "$D/mirror_score.txt"
echo
grep -h "MIRROR CHECK" "$D/mirror_score.txt" || echo "(no MIRROR CHECK line printed; send the log)"
echo
echo "== done. Rejoin normal WiFi, then tell Claude:  camera check done, folder $D"
echo "   PASS = left/right agree with reality. MIRRORED / FAIL / NO DATA = stop, don't retry blindly."
echo "   Frames stay on this laptop; they show real people, never commit them to the public repo."
