#!/usr/bin/env bash
# Builds crazysim-mac:follow-app (CrazySim SITL firmware + the follow app) from the
# existing crazysim-mac:arm64 image (tools/crazysim_macos/setup.sh). The base image
# is not modified. ~1-2 min.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TAG="${FOLLOW_APP_IMAGE:-crazysim-mac:follow-app}"
docker image inspect crazysim-mac:arm64 >/dev/null 2>&1 || { echo "Base image missing: run tools/crazysim_macos/setup.sh"; exit 1; }
docker build -f "$HERE/Dockerfile.sitl" -t "$TAG" "$HERE/.."
echo "Built $TAG. Start it with $HERE/run_sim_follow_app.sh"
