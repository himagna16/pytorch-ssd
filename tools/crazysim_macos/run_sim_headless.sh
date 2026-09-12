#!/usr/bin/env bash
# Headless twin of run_sim_viewer.sh: same crazysim.py and flags, minus --vis
# (no 3D window), camera rendered offscreen via MUJOCO_GL=cgl. Use it when the
# Mac screen is locked (the viewer crashes then) or when no window is wanted.
# Camera runs at ~12.9 Hz here vs ~14.4 Hz with the viewer.
# Usage: ./run_sim_headless.sh [extra crazysim.py flags, e.g. --camera --scene /abs/scene.xml]
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DRONE_ROOT="$(cd "$HERE/../../.." && pwd)"
VENV="${CRAZYSIM_VENV:-$DRONE_ROOT/crazysimenv}"
MJDIR="${CRAZYSIM_MUJOCO:-$DRONE_ROOT/crazysim_mujoco}"
[ -x "$VENV/bin/python" ] && [ -f "$MJDIR/crazysim.py" ] || { echo "Run ./setup.sh first."; exit 1; }
docker rm -f crazysim-mac >/dev/null 2>&1 || true
docker run -d --name crazysim-mac crazysim-mac:arm64 sleep infinity >/dev/null
HOST_IP="$(docker exec crazysim-mac getent hosts host.docker.internal | awk '{print $1}')"
echo "Mac host IP from container: $HOST_IP"
cleanup() { pkill -f "$MJDIR/crazysim.py" 2>/dev/null || true; docker rm -f crazysim-mac >/dev/null 2>&1 || true; }
trap cleanup EXIT
MUJOCO_GL=cgl "$VENV/bin/python" -u "$MJDIR/crazysim.py" --model-type cf2x_T350 --port 19950 --host 0.0.0.0 "$@" -- 0,0 &
SIM=$!
sleep 2
docker exec -d crazysim-mac bash -c "mkdir -p sitl_make/build/0 && cd sitl_make/build/0 && stdbuf -oL ../cf2 19950 $HOST_IP > out.log 2> error.log"
echo "Headless sim up. cflib URI: udp://127.0.0.1:19850   (Ctrl-C to stop)"
wait $SIM
