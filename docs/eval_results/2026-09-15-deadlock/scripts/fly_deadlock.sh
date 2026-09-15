#!/usr/bin/env bash
# The deadlock suite reuses the people-plural harness verbatim. There is no
# second flight harness: fly_pool.sh takes OUT_DIR, CELLS_FILE and a scene root,
# so the lock protocol, the validity gate, the re-fly rule, the interleaving and
# the ships-as configuration are the same code that flew the main suite.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
D="$(cd "$HERE/.." && pwd)"
SCRATCH=/private/tmp/claude-501/-Users-saimaruvada-Downloads/90541ca8-cca5-4400-9855-79d1dde551f0/scratchpad
REPEATS="${1:-4}"
OUT_DIR="$D" CELLS_FILE="$HERE/cells.txt" \
  bash "$D/../2026-09-15-people-plural/scripts/fly_pool.sh" "$REPEATS" "$SCRATCH/deadlock_scenes"
