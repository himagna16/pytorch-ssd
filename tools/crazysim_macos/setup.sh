#!/usr/bin/env bash
# One-time setup: CrazySim (MuJoCo backend) on Apple Silicon macOS.
# Firmware (cf2) runs in a small arm64 Linux container; MuJoCo, the 3D viewer,
# and cflib run natively on the Mac. No NVIDIA GPU, no Ubuntu, no ROS/Gazebo.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DRONE_ROOT="$(cd "$HERE/../../.." && pwd)"
command -v docker >/dev/null || { echo "Install Docker Desktop first."; exit 1; }
docker info >/dev/null 2>&1 || { echo "Start Docker Desktop first."; exit 1; }
PY="$(command -v python3.11 || command -v python3.12 || command -v python3)"
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' \
  || { echo "Need Python >= 3.11 (crazysim.py uses tomllib)."; exit 1; }
echo "[1/3] Building firmware image crazysim-mac:arm64 (first run ~10 min)"
docker build -t crazysim-mac:arm64 "$HERE"
echo "[2/3] Copying MuJoCo simulator files to $DRONE_ROOT/crazysim_mujoco"
rm -rf "$DRONE_ROOT/crazysim_mujoco"
CID="$(docker create crazysim-mac:arm64)"
docker cp "$CID:/root/CrazySim/crazyflie-firmware/tools/crazyflie-simulation/simulator_files/mujoco" "$DRONE_ROOT/crazysim_mujoco"
docker rm "$CID" >/dev/null
echo "[3/3] Creating Mac venv $DRONE_ROOT/crazysimenv"
"$PY" -m venv "$DRONE_ROOT/crazysimenv"
"$DRONE_ROOT/crazysimenv/bin/pip" install -q --upgrade pip
"$DRONE_ROOT/crazysimenv/bin/pip" install -q mujoco numpy cflib pillow
echo "Setup complete. Next: ./run_sim_viewer.sh  (or ./run_sim.sh single for headless)"
