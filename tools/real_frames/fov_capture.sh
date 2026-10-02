#!/bin/zsh
# SOLO field-of-view + aim measurement: one bottle, taped marks, no live view, no helper.
#
# Every label the project computes assumes the network's crop is 70 deg wide; nobody has
# measured it. The runbook's bottle FOV (lab_session_runbook.md 4.0a) needs a second person
# watching a live view. This records an EMPTY room, then the same room with a bottle on
# taped marks, one mark at a time, with spoken cues, and fov_fit.py finds the bottle by
# differencing and fits the lens. ~4 minutes, one battery, one power-up.
#
# Layout (dorm, 1 ft tiles; drone exactly as for grid_capture.sh: chair at the window end,
# lens ~0.8 m up above the row 1/row 2 line, middle column, facing the door):
#   ONE line of tape across the aisle, FOV_DIST = 1.00 m from the point under the lens
#   (= 3 ft 3 3/8 in = 3 tiles + 3 3/8 in, same as the Lighthouse +x offset), square to
#   the tape line. Marks on it, measured from the centre line (middle of col 3):
#       0, 0.25 m (9 7/8 in), 0.50 m (1 ft 7 5/8 in), 0.70 m (2 ft 3 1/2 in) each side.
#   SIGN: + = the drone's LEFT, seen from BEHIND the drone looking at the door (col 1/2
#   side of dorm_grid_capture.svg). Same as room/body +y in tools/lighthouse/README.md;
#   the repo's BEARINGS are the other way (negative = left), and fov_session.json carries both.
#   0.70 m is 2.5 in inside the 1.52 m aisle.
#
# Object: a dark, OPAQUE, MATTE bottle (black metal water bottle / thermos, 25 cm+), not a
#   book. A cylinder's outline is centred on its axis from every direction, so it does not
#   matter how it is turned; a book's face sits in front of the mark and turns with
#   placement, and it is 2x wider (more perspective bias). Not clear glass or plastic.
#   At 1 m the floor is just BELOW the picture (lens 0.8 m up, ~35 deg half-view), so a bottle
#   on the floor only shows its top part. If the first mark's check says NOT USABLE, stand
#   it on something NARROW and ROUND (an upturned round bin, a tall can) centred on the
#   mark, not a box: a wide stand's outline is biased outward at the side marks (fov_fit
#   ignores the wider rows, but a narrow stand is cleaner). Then press Enter to retake.
#   Centre it on each mark to ~5 mm: 1 cm of placement error per mark ~ 1 % in the result.
#
# Flow: precheck (brightness gate as grid_capture) -> EMPTY room (bottle out of view) ->
#   for each mark: the laptop SAYS which mark, you place the bottle, come back behind the
#   drone, press Enter, it says "step out of frame", counts 3, records 3 s, then CHECKS
#   the clip on the spot and says "got it" or "can't see it" (Enter = retake, s = skip)
#   -> EMPTY room again (bottle out of view) -> fit -> summary + folder.
#   Stand at the SAME spot behind the drone for every clip (your shadow cancels).
#
# Usage:  GRID_DRONE=09 zsh tools/real_frames/fov_capture.sh
#   FOV_DIST=1.0  FOV_OFFSETS="0 0.25 -0.25 0.5 -0.5 0.7 -0.7"  (metres, + = LEFT)
#   FOV_LENS_H=0.8  FOV_OBJECT=bottle  FOV_OBJECT_H=0.27 FOV_OBJECT_W=0.075 FOV_STAND_H=0.4
#   FOV_SECONDS=3 (per mark)  FOV_EMPTY_SECONDS=4  FOV_PRE=3 ("step out" countdown)
#   FOV_WAIT=0 (wait for Enter; N = every prompt is Enter OR start by itself after N s;
#               a failed check then SKIPS the mark after N s)  FOV_RETAKES=1
#   CAMERA_CHECK_GRAB_ARGS="--mock --port 5057" ...   rehearsal against mock_streamer.py
# No resume: a new battery is a new power-up, i.e. a new exposure, and the empty reference
# would no longer match. Re-run the whole thing (~4 min).
set -u
HERE=${0:A:h}
source "$HERE/solo_capture_lib.zsh" || exit 1
FIT="$HERE/fov_fit.py"
DIST=${FOV_DIST:-1.0}
OFFSETS=${FOV_OFFSETS:-"0 0.25 -0.25 0.5 -0.5 0.7 -0.7"}
LENS_H=${FOV_LENS_H:-0.8}
OBJ=${FOV_OBJECT:-bottle}; OBJ=${OBJ//[^A-Za-z0-9-]/-}
SECS=${FOV_SECONDS:-3}
EMPTY_SECS=${FOV_EMPTY_SECONDS:-4}
PRE=${FOV_PRE:-3}
WAIT=${FOV_WAIT:-0}
RETAKES=${FOV_RETAKES:-1}
D=$ROOT/$(date +%F)/fov_capture_$(date +%H%M%S)
mkdir -p "$D" || exit 1
exec > >(tee -a "$D/fov_capture.log") 2>&1
T0=$SECONDS
echo "== FOV capture, $(date)  drone $DRONE  light $LIGHT  object $OBJ  folder: $D"

extra=()
[[ -n "${FOV_OBJECT_H:-}" ]] && extra+=(--object-height "$FOV_OBJECT_H")
[[ -n "${FOV_OBJECT_W:-}" ]] && extra+=(--object-width "$FOV_OBJECT_W")
[[ -n "${FOV_STAND_H:-}" ]] && extra+=(--stand-height "$FOV_STAND_H")
[[ -n "$MOCK" ]] && extra+=(--mock)
PLAN=$($PY "$FIT" "$D" --init --dist="$DIST" --offsets="$OFFSETS" --lens-height="$LENS_H" \
        --object="$OBJ" --drone="$DRONE" --light="$LIGHT" "${extra[@]}") \
  || { echo "FAIL: FOV setup (message above). Nothing was recorded."; exit 1; }
plan=("${(@f)PLAN}")
echo "   marks on ONE tape line ${DIST} m out from the lens; + = the drone's LEFT seen from BEHIND it:"
for line in "${plan[@]}"; do parts=("${(@ps:\t:)line}"); echo "     ${parts[4]}"; done

wait_for_deck
exposure_gate fov_capture

# Enter, or (FOV_WAIT=N) Enter-or-N-seconds. $1 = prompt; the answer lands in $ans.
ask() {
  ans=""
  if (( WAIT > 0 )); then read -t $WAIT "ans?$1 (starts by itself in ${WAIT} s) " || { ans=""; echo; }
  else read "ans?$1 "; fi
}

STOPPED=""
echo
echo "== EMPTY ROOM reference: the $OBJ OUT of view (behind the drone), you behind the drone."
speak "Empty room first. Put the $OBJ behind the drone and stay there."
ask "   press Enter when the $OBJ and you are out of view"
countdown $PRE "Recording."
grab --seconds $EMPTY_SECS --every 1 --vis 0 --subject empty --light "$LIGHT" --out "$D/empty_start" \
  || { echo "FAIL: no frames for the empty reference (battery? WiFi?). Nothing usable was recorded."; exit 3; }

n=0
for line in "${plan[@]}"; do
  n=$((n+1))
  parts=("${(@ps:\t:)line}")
  dir=${parts[1]}; words=${parts[3]}; desc=${parts[4]}
  take=1
  while true; do
    echo
    echo "== mark $n of ${#plan}: $desc"
    (( take > 1 )) && echo "   (retake $take)"
    speak "Put the $OBJ on $words."
    ask "   put the $OBJ on the mark, come back behind the drone, press Enter"
    speak "Step out of frame."
    countdown $PRE "Recording."
    if ! grab --seconds $SECS --every 1 --vis 0 --subject "$OBJ" --light "$LIGHT" --take $take --out "$D/$dir"; then
      echo "!! no frames for this mark: most likely the BATTERY (the camera browns out first) or the WiFi."
      speak "No frames. The battery is probably flat."
      STOPPED=$n
      break 2
    fi
    if $PY "$FIT" "$D" --check "$dir"; then
      speak "Got it."
      break
    fi
    if (( take > RETAKES )); then
      speak "Still can't see it. Moving on."
      echo "   moving on (FOV_RETAKES=$RETAKES); the fit leaves this mark out"
      break
    fi
    speak "I can't see the $OBJ. Fix it, then press Enter to retake, or type s to skip."
    if (( WAIT > 0 )); then
      read -t $WAIT "ans?   Enter = retake this mark, s then Enter = skip it (skips by itself in ${WAIT} s): " || { ans=s; echo; }
    else
      ans=""; read "ans?   Enter = retake this mark, s then Enter = skip it: "
    fi
    [[ "$ans" == [sS]* ]] && { echo "   skipped"; break; }
    take=$((take+1))
  done
done

if [[ -z "$STOPPED" ]]; then
  echo
  echo "== EMPTY ROOM again: the $OBJ OUT of view, you behind the drone (checks nothing drifted)."
  speak "Last one. Take the $OBJ out of view and stay behind the drone."
  ask "   press Enter when the $OBJ and you are out of view"
  countdown $PRE "Recording."
  grab --seconds $EMPTY_SECS --every 1 --vis 0 --subject empty --light "$LIGHT" --out "$D/empty_end" \
    || echo "!! no frames for the closing empty clip; the fit uses the first one only"
  speak "All clips done."
fi

echo
echo "== fitting the lens (offline)"
$PY "$FIT" "$D" | tee "$D/fov_fit.txt"
RC=${pipestatus[1]}
if (( RC == 0 )); then
  CROP=$($PY -c "import json,sys;print(json.load(open(sys.argv[1]))['camera']['hfov_flight_crop_deg'])" "$D/fov_fit.json" 2>/dev/null)
  [[ -n "$CROP" ]] && speak "Field of view measured. The crop is $CROP degrees."
elif (( RC == 5 )); then
  speak "The fit is poor. Do not use it. Read the screen."
else
  speak "The fit did not work. Read the screen."
fi
echo
[[ -n "$STOPPED" ]] && echo "!! STOPPED at mark $STOPPED (no frames). Charge the battery and run the WHOLE thing again (~4 min):" \
                    && echo "!! a new power-up is a new exposure, so these clips cannot be finished later."
echo "== done in $(( SECONDS - T0 )) s (fit exit code $RC). Folder: $D"
echo "   Rejoin normal WiFi, then tell Claude:  fov done, folder $D"
echo "   The frames stay on this laptop (they show the room); fov_fit.json / fov_fit.txt are the numbers."
exit $RC
