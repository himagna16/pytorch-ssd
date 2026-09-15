#!/usr/bin/env bash
# Render the 39 deadlock scene definitions. tools/ is not written to.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
D="$(cd "$HERE/.." && pwd)"
TOOLS=/Users/saimaruvada/Downloads/drone/pytorch_ssd/tools/crazysim_macos
P=/Users/saimaruvada/Downloads/drone/trainenv/bin/python
SCRATCH=/private/tmp/claude-501/-Users-saimaruvada-Downloads/90541ca8-cca5-4400-9855-79d1dde551f0/scratchpad
OUT="${1:-$SCRATCH/deadlock_scenes}"
mkdir -p "$OUT"; cd "$TOOLS"
"$P" build_scene.py --def "$D"/scene_defs/*.json --out "$OUT" --floor-reflectance 0.0 2>&1 | tail -5
n=$(ls "$OUT" | wc -l | tr -d ' ')
echo "scene dirs: $n"; [ "$n" = 39 ] || { echo "EXPECTED 39, GOT $n"; exit 1; }
echo ok
