#!/usr/bin/env bash
# Render every screened subject at the REAL capture protocol's own marks, through
# the same mock streamer -> cpx_grab -> score_real_frames chain the lab session
# uses. The point is that tomorrow's real numbers and tonight's simulated ones
# come out of the same tool, so the only difference between them is real pixels
# against rendered ones.
#
# Distances include 2.0 and 3.0 m, which the protocol does not use, because the
# fidelity study's static probe dips at its 2.5 m rung for every subject and the
# protocol puts a mark exactly there. If that dip is real it will show up here as
# a non-monotone row, measured on hundreds of frames per cell instead of on four
# binary flights.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
D="$(cd "$HERE/.." && pwd)"
ROOT=/Users/saimaruvada/Downloads/drone
P="$ROOT/trainenv/bin/python"
SCR=/private/tmp/claude-501/-Users-saimaruvada-Downloads/90541ca8-cca5-4400-9855-79d1dde551f0/scratchpad
POOL="$SCR/pool_scenes"
OUT="${1:-$SCR/protocol_grid}"
SECONDS_PER_CLIP="${2:-2}"
# bank >= frames captured, so every frame in a clip is a distinct render rather
# than the same 24 cycling. At 20 fps a 2 s clip is 40 frames; bank 40 matches it.
BANK=40
PORT=5311

DISTS=(1.5 2.0 2.5 3.0 3.5)
BEARINGS=(0 -10 10 -25 25)
SUBJECTS=(124442 527750 157365 356427 250127 61747 161875 401446 374369 266409 280779 556158 control)

mkdir -p "$OUT"
LOG="$D/progress.log"
log(){ echo "[$(date +%H:%M:%S)] $*" | tee -a "$LOG"; }
cleanup(){ pkill -f "mock_streamer.py --port $PORT" 2>/dev/null; }
trap cleanup EXIT INT TERM

total=$(( ${#SUBJECTS[@]} * ${#DISTS[@]} * ${#BEARINGS[@]} ))
log "protocol grid: ${#SUBJECTS[@]} subjects x ${#DISTS[@]} dists x ${#BEARINGS[@]} bearings = $total clips"
n=0
for subj in "${SUBJECTS[@]}"; do
  if [ "$subj" = "control" ]; then scene="$POOL/s15_static_offset/scene.xml"
  else scene="$POOL/pp15_${subj}/scene.xml"; fi
  if [ ! -f "$scene" ]; then log "MISSING SCENE for $subj: $scene"; continue; fi
  for d in "${DISTS[@]}"; do
    for b in "${BEARINGS[@]}"; do
      n=$((n+1))
      cleanup; sleep 0.4
      "$P" "$ROOT/pytorch_ssd/tools/real_frames/mock_streamer.py" \
          --port $PORT --scene "$scene" --dist "$d" --bearing "$b" \
          --preset himax_typical --fps 20 --bank $BANK > "$SCR/mock_grid.log" 2>&1 &
      sleep 4
      "$P" "$ROOT/pytorch_ssd/tools/crazysim_macos/cpx_grab.py" \
          --host 127.0.0.1 --port $PORT --seconds "$SECONDS_PER_CLIP" --every 1 \
          --out "$OUT" --dist "$d" --bearing "$b" --vis 1 \
          --subject "$subj" --light sim > /dev/null 2>&1
      rc=$?
      cleanup
      [ $rc -ne 0 ] && log "  [$n/$total] $subj d=$d b=$b  GRAB FAILED rc=$rc" \
                    || log "  [$n/$total] $subj d=$d b=$b  ok"
    done
  done
done
log "render done: $(ls "$OUT" | grep -c '\.png$') frames"
