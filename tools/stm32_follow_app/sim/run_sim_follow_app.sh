#!/usr/bin/env bash
# CrazySim with the follow app compiled into the firmware (image crazysim-mac:follow-app,
# built by build_image.sh). Same as tools/crazysim_macos/run_sim_headless.sh and
# run_sim_viewer.sh, except for the firmware image. Headless by default (works with a
# locked screen); --viewer opens the MuJoCo window instead.
# Usage: ./run_sim_follow_app.sh [--viewer] [crazysim.py flags, e.g. --camera --scene /abs/scene.xml]
# Env (to run next to another simulator): CRAZYSIM_CONTAINER (default crazysim-mac),
#   CRAZYSIM_PORT (firmware port, default 19950; cflib URI = udp://127.0.0.1:<port - 100>),
#   CRAZYSIM_CAM_PORT (camera frame UDP port, default crazysim.py's 5200), FOLLOW_APP_IMAGE.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DRONE_ROOT="$(cd "$HERE/../../../.." && pwd)"
VENV="${CRAZYSIM_VENV:-$DRONE_ROOT/crazysimenv}"
MJDIR="${CRAZYSIM_MUJOCO:-$DRONE_ROOT/crazysim_mujoco}"
IMAGE="${FOLLOW_APP_IMAGE:-crazysim-mac:follow-app}"
CNAME="${CRAZYSIM_CONTAINER:-crazysim-mac}"
PORT="${CRAZYSIM_PORT:-19950}"
CAMARGS=()
[ -n "${CRAZYSIM_CAM_PORT:-}" ] && CAMARGS=(--cam-port "$CRAZYSIM_CAM_PORT")
VIEWER=0
if [ "${1:-}" = "--viewer" ]; then VIEWER=1; shift; fi
[ -x "$VENV/bin/python" ] && [ -f "$MJDIR/crazysim.py" ] || { echo "Run tools/crazysim_macos/setup.sh first."; exit 1; }
docker image inspect "$IMAGE" >/dev/null 2>&1 || { echo "Image $IMAGE missing: run $HERE/build_image.sh"; exit 1; }
docker rm -f "$CNAME" >/dev/null 2>&1 || true
docker run -d --name "$CNAME" "$IMAGE" sleep infinity >/dev/null
HOST_IP="$(docker exec "$CNAME" getent hosts host.docker.internal | awk '{print $1}')"
echo "Mac host IP from container: $HOST_IP (firmware image $IMAGE)"
cleanup() { pkill -f "$MJDIR/crazysim.py.*--port $PORT" 2>/dev/null || true; docker rm -f "$CNAME" >/dev/null 2>&1 || true; }
trap cleanup EXIT
if [ "$VIEWER" = 1 ]; then
  "$VENV/bin/mjpython" -u "$MJDIR/crazysim.py" --model-type cf2x_T350 --port "$PORT" --host 0.0.0.0 --vis ${CAMARGS[@]+"${CAMARGS[@]}"} "$@" -- 0,0 &
else
  MUJOCO_GL=cgl "$VENV/bin/python" -u "$MJDIR/crazysim.py" --model-type cf2x_T350 --port "$PORT" --host 0.0.0.0 ${CAMARGS[@]+"${CAMARGS[@]}"} "$@" -- 0,0 &
fi
SIM=$!
sleep 2
docker exec -d "$CNAME" bash -c "mkdir -p sitl_make/build/0 && cd sitl_make/build/0 && stdbuf -oL ../cf2 $PORT $HOST_IP > out.log 2> error.log"
echo "Sim up (follow app firmware). cflib URI: udp://127.0.0.1:$((PORT - 100))   (Ctrl-C to stop)"
wait $SIM
