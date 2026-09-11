#!/usr/bin/env bash
# Apply the team's DORY patches to a DORY checkout (default: ../../../dory next to the repo).
# Safe to re-run: already-applied patches are skipped.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
DORY="${1:-$HERE/../../../dory}"
cd "$DORY"
for p in "$HERE"/0*.patch; do
  if git apply --reverse --check -p1 "$p" 2>/dev/null; then
    echo "already applied: $(basename "$p")"
  else
    git apply -p1 "$p" && echo "applied: $(basename "$p")"
  fi
done
