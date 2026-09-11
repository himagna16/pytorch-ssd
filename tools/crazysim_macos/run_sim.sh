#!/usr/bin/env bash
# Start CrazySim (MuJoCo backend) headless in the arm64 container and expose
# the cflib UDP port (19850) and AI-deck CPX camera port (5050) to the Mac.
# Usage: ./run_sim.sh [single|camera] [extra crazysim.py flags...]
set -euo pipefail
MODE="${1:-single}"; shift || true
docker rm -f crazysim-mac >/dev/null 2>&1 || true
docker run -d --name crazysim-mac -p 19850:19850/udp -p 5050:5050/tcp crazysim-mac:arm64 sleep infinity >/dev/null
M=tools/crazyflie-simulation/simulator_files/mujoco
docker exec -d crazysim-mac bash -c "mkdir -p sitl_make/build/0 && cd sitl_make/build/0 && stdbuf -oL ../cf2 19950 > out.log 2> error.log"
sleep 1
if [ "$MODE" = "camera" ]; then
  docker exec -d crazysim-mac bash -c "python3 -u $M/crazysim_cpx.py --cpx-port 5050 --cflib-port 19850 > /tmp/cpx.log 2>&1"
  docker exec -d crazysim-mac bash -c "python3 -u $M/crazysim.py --model-type cf2x_T350 --port 19950 --host 0.0.0.0 --scene scene_obstacles.xml --camera $* -- 0,0 > /tmp/sim.log 2>&1"
else
  docker exec -d crazysim-mac bash -c "python3 -u $M/crazysim.py --model-type cf2x_T350 --port 19950 --host 0.0.0.0 $* -- 0,0 > /tmp/sim.log 2>&1"
fi
echo "sim up: cflib URI udp://127.0.0.1:19850 | camera tcp://127.0.0.1:5050 (camera mode)"
