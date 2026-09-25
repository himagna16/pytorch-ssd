#!/bin/zsh
# 20-second camera exposure check: which brightness "mode" did this drone's camera start in?
#
# On 2026-09-24 the same room under the same lights came out at mean brightness ~40 in some
# runs and ~90 in others (and ~7 once, on a dying battery), and detection changed a lot with
# it. This grabs 8 frames, prints the mean brightness, and appends one line to a log so we can
# find out whether it depends on the drone or on each power-up.
#
# Usage (laptop on the drone's WiFi, room as for a grid, nobody in view):
#   GRID_DRONE=09 zsh ~/Downloads/drone/pytorch_ssd/tools/real_frames/exposure_check.sh
set -u
PY=~/Downloads/drone/trainenv/bin/python
REPO=~/Downloads/drone/pytorch_ssd
DRONE=${GRID_DRONE:-unknown}
T=$(mktemp -d /tmp/exposure_XXXX)
$PY $REPO/tools/crazysim_macos/cpx_grab.py ${=CAMERA_CHECK_GRAB_ARGS:-} --n 8 --every 1 --out "$T" >/dev/null 2>&1 \
  || { echo "FAIL: no frames (on the drone's WiFi? battery in for 30 s?)"; exit 2; }
M=$($PY -c "import glob,numpy as n;from PIL import Image;fs=glob.glob('$T/*.png')+glob.glob('$T/*.jpg');print(f'{n.mean([n.asarray(Image.open(f).convert(\"L\")).mean() for f in fs]):.1f} {len(fs)}')")
set -- ${=M}
MODE="in the grid band 30-60: OK to record"; (( ${1%.*} > 60 )) && MODE="too bright for the grid band: power-cycle"; (( ${1%.*} < 30 )) && MODE="too dark for the grid band: power-cycle"; (( ${1%.*} < 15 )) && MODE="NEAR-BLACK: do not record"
echo "drone $DRONE: mean brightness $1 over $2 frames -> $MODE"
mkdir -p ~/drone_frames && echo "$(date '+%F %T') drone=$DRONE brightness=$1 frames=$2 mode=$MODE" >> ~/drone_frames/exposure_log.txt
echo "logged to ~/drone_frames/exposure_log.txt"
rm -rf "$T"
