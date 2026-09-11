#!/usr/bin/env bash
# Viewer mode: cf2 firmware in the arm64 container, MuJoCo physics + 3D viewer
# natively on the Mac via mjpython. cf2 only accepts a dotted IP, so the Mac's
# address as seen from the container is resolved at runtime.
# Usage: ./run_sim_viewer.sh [extra crazysim.py flags, e.g. --sensor-noise]
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DRONE_ROOT="$(cd "$HERE/../../.." && pwd)"
VENV="${CRAZYSIM_VENV:-$DRONE_ROOT/crazysimenv}"
MJDIR="${CRAZYSIM_MUJOCO:-$DRONE_ROOT/crazysim_mujoco}"
[ -x "$VENV/bin/mjpython" ] && [ -f "$MJDIR/crazysim.py" ] || { echo "Run ./setup.sh first."; exit 1; }
docker rm -f crazysim-mac >/dev/null 2>&1 || true
docker run -d --name crazysim-mac crazysim-mac:arm64 sleep infinity >/dev/null
HOST_IP="$(docker exec crazysim-mac getent hosts host.docker.internal | awk '{print $1}')"
echo "Mac host IP from container: $HOST_IP"
cleanup() { pkill -f "$MJDIR/crazysim.py" 2>/dev/null || true; docker rm -f crazysim-mac >/dev/null 2>&1 || true; }
trap cleanup EXIT
"$VENV/bin/mjpython" -u "$MJDIR/crazysim.py" --model-type cf2x_T350 --port 19950 --host 0.0.0.0 --vis "$@" -- 0,0 &
SIM=$!
sleep 2
docker exec -d crazysim-mac bash -c "mkdir -p sitl_make/build/0 && cd sitl_make/build/0 && stdbuf -oL ../cf2 19950 $HOST_IP > out.log 2> error.log"
echo "Viewer up. cflib URI: udp://127.0.0.1:19850   (Ctrl-C to stop)"
echo "Note: the firmware locks after every landing; re-run this script between flights."
wait $SIM
