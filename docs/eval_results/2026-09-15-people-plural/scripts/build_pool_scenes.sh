#!/usr/bin/env bash
# Render the 24 pool scene definitions plus the 2 originals into scene directories.
# build_scene.py takes --def with arbitrary paths, so the 24 generated defs stay in
# this evidence directory and tools/crazysim_macos/scene_defs/ is not written to.
#
# The two CONTROL scenes are built from the ORIGINAL committed defs, unmodified.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
D="$(cd "$HERE/.." && pwd)"
TOOLS=/Users/saimaruvada/Downloads/drone/pytorch_ssd/tools/crazysim_macos
P=/Users/saimaruvada/Downloads/drone/trainenv/bin/python
SCRATCH=/private/tmp/claude-501/-Users-saimaruvada-Downloads/90541ca8-cca5-4400-9855-79d1dde551f0/scratchpad
OUT="${1:-$SCRATCH/pool_scenes}"

mkdir -p "$OUT"
cd "$TOOLS"
echo "building 24 pool scenes + 2 controls into $OUT"
"$P" build_scene.py --def "$D"/scene_defs/*.json \
     scene_defs/s15_static_offset.json scene_defs/s01_control_moving.json \
     --out "$OUT" --floor-reflectance 0.0 2>&1 | tail -20
echo
echo "scene dirs:"; ls "$OUT" | sed 's/^/  /'
n=$(ls "$OUT" | wc -l | tr -d ' ')
[ "$n" = 26 ] || { echo "EXPECTED 26 SCENE DIRS, GOT $n"; exit 1; }
echo "ok: 26"
