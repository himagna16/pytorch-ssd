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
# macOS caps UDP datagrams at 9216 bytes (net.inet.udp.maxdgram). crazysim.py
# sends 60 KB camera chunks and silently ignores the send error, so native
# camera frames never arrive. patch_crazysim.py shrinks the chunk size and adds
# an optional ground-truth log for tests.
"$PY" "$HERE/patch_crazysim.py" "$DRONE_ROOT/crazysim_mujoco/crazysim.py"
echo "[3/3] Creating Mac venv $DRONE_ROOT/crazysimenv"
"$PY" -m venv "$DRONE_ROOT/crazysimenv"
"$DRONE_ROOT/crazysimenv/bin/pip" install -q --upgrade pip
"$DRONE_ROOT/crazysimenv/bin/pip" install -q mujoco numpy cflib pillow
if [ -x "$DRONE_ROOT/trainenv/bin/pip" ]; then
  echo "[+] Person following: adding cflib 0.1.33 + mujoco to the team trainenv (numpy pinned)"
  # cflib 0.1.27's UDP driver calls sendto() on a connected socket, which macOS
  # rejects (EISCONN). 0.1.33 works. --no-deps keeps numpy < 2 for torch 2.2.2.
  "$DRONE_ROOT/trainenv/bin/pip" install -q --no-deps "cflib==0.1.33"
  "$DRONE_ROOT/trainenv/bin/pip" install -q pyusb libusb-package packaging mujoco "numpy==1.24.4"
fi
echo "Setup complete. Next: ./run_sim_viewer.sh  (or ./run_sim.sh single for headless)"
