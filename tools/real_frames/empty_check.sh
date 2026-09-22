#!/bin/zsh
# Empty-room false-alarm check for ONE drone, runnable with no internet.
#
# Records a 20 s clip with NOBODY in view and scores it on the chip network, so we
# can see whether the model calls furniture a person. Companion to camera_check.sh
# (same setup, same folder layout); results in docs/eval_results/2026-09-22-first-real-frames/.
#
# Before running: nobody in the camera's view. Easiest is to put the laptop BEHIND
# the drone so you can press Enter and stay out of frame.
#
# Usage:  zsh tools/real_frames/empty_check.sh
#         CAMERA_CHECK_GRAB_ARGS=--mock zsh tools/real_frames/empty_check.sh   (rehearsal)
set -u
PY=~/Downloads/drone/trainenv/bin/python
REPO=~/Downloads/drone/pytorch_ssd
grab()  { $PY $REPO/tools/crazysim_macos/cpx_grab.py ${=CAMERA_CHECK_GRAB_ARGS:-} "$@"; }
score() { $PY $REPO/tools/real_frames/score_real_frames.py "$@"; }
COUNTDOWN=${CAMERA_CHECK_COUNTDOWN:-10}
SECS=${EMPTY_CHECK_SECONDS:-20}
D=~/drone_frames/$(date +%F)/empty_check_$(date +%H%M%S)
mkdir -p "$D" || exit 1
exec > >(tee -a "$D/empty_check.log") 2>&1
echo "== empty-room check, $(date)  folder: $D"

if [[ -z "${CAMERA_CHECK_GRAB_ARGS:-}" ]]; then
  echo "== waiting for the deck at 192.168.4.1:5000 (join WiFi 'WiFi streaming example')"
  for i in {1..60}; do nc -z -G 2 192.168.4.1 5000 2>/dev/null && break; sleep 2; done
  nc -z -G 2 192.168.4.1 5000 2>/dev/null || { echo "FAIL: deck not reachable. On the drone's WiFi? Battery in for 30 s?"; exit 2; }
  echo "   deck reachable"
fi

echo
echo "== EMPTY ROOM: nobody in front of the camera. Stand BEHIND the drone."
read "?   press Enter, then get out of view (${COUNTDOWN} s countdown) "
for ((s=COUNTDOWN; s>0; s--)); do printf "\r   %2d " $s; sleep 1; done; printf "\r   recording ${SECS} s, stay out of view...\n"
grab --seconds $SECS --every 1 --vis 0 --subject empty --light room --out "$D/empty" \
  || { echo "FAIL: recording. Send this log."; exit 3; }
printf '\a'
echo
echo "== scoring on the chip network (offline)"
score "$D/empty" --json "$D/empty_scores.json" | tee "$D/empty_score.txt"
echo
grep -h "EMPTY / NO-PERSON" "$D/empty_score.txt" || echo "(no EMPTY line printed; send the log)"
echo
echo "== done. Rejoin normal WiFi, then tell Claude:  empty check done, folder $D"
echo "   'confirmed (false) tracks = 0' is what we want: the drone would not have locked on."
