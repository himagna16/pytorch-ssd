#!/usr/bin/env bash
# Two simulated Crazyflies for rehearsing record_session.py --mock (no hardware).
#
#   bash tools/lighthouse/run_pair_sim.sh          # start (prints the two cflib URIs)
#   bash tools/lighthouse/run_pair_sim.sh stop     # remove the container
#
# Same container image and headless crazysim.py as tools/crazysim_macos/run_sim.sh,
# with two agents: agent 0 = the follower at (0, 0), agent 1 = the beacon at (2.5, 0).
# cflib URIs: udp://127.0.0.1:19850 (follower) and udp://127.0.0.1:19851 (beacon).
# Nothing here flies: record_session.py never arms or sends setpoints, so both drones
# sit on the floor and their poses are constant. Restart the sim between runs anyway
# (the SITL firmware keeps state across connections).
set -euo pipefail
NAME=crazysim-lh-pair
docker rm -f "$NAME" >/dev/null 2>&1 || true
[ "${1:-start}" = "stop" ] && { echo "stopped $NAME"; exit 0; }
if docker ps --format '{{.Names}}' | grep -qx crazysim-mac; then
  echo "crazysim-mac (tools/crazysim_macos/run_sim.sh) is running and holds port 19850; stop it first:"
  echo "  docker rm -f crazysim-mac"; exit 1
fi
docker run -d --name "$NAME" -p 19850:19850/udp -p 19851:19851/udp crazysim-mac:arm64 sleep infinity >/dev/null
M=tools/crazyflie-simulation/simulator_files/mujoco
for i in 0 1; do
  docker exec -d "$NAME" bash -c "mkdir -p sitl_make/build/$i && cd sitl_make/build/$i && stdbuf -oL ../cf2 $((19950 + i)) > out.log 2> error.log"
done
sleep 1
docker exec -d "$NAME" bash -c "python3 -u $M/crazysim.py --model-type cf2x_T350 --port 19950 --host 0.0.0.0 -- 0,0 2.5,0 > /tmp/sim.log 2>&1"
echo "pair sim up: follower udp://127.0.0.1:19850  beacon udp://127.0.0.1:19851  (container $NAME)"
