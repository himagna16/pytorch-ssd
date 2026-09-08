# Oaj — stand up the Crazyflie simulator (CrazySim) on the team's only capable machine

**Agent instructions.** Your user is Oaj. His Windows 11 / WSL2 machine with an
NVIDIA GPU is the **only team machine that can run MinHyuk Park's Crazyflie
simulator** (it requires Ubuntu/WSL2 + NVIDIA; the team's Macs cannot). Prof.
Mok requires simulator validation before any physical flight, so this task
gates the whole hardware phase. Source of truth for the simulator is
MinHyuk's repository and the meeting notes it came from — when in doubt,
his README wins over this document:
<https://github.com/dmz44/Crazyflie_Simulator_Container>

Follow TEAMWORK.md rules for the pytorch_ssd repo (pull first, push at
session end, log results). Work in milestones; each ends with a VERIFY.
Stop and report to Sai (with logs) if a milestone fails for >30 minutes.
Ask Oaj before any install that needs admin rights or a reboot.

## Milestone 0 — Prerequisites (host checks, WSL2 side)

Inside the WSL2 Ubuntu shell:

```bash
nvidia-smi                      # must list the GPU from inside WSL2
docker --version && docker compose version
docker run --rm --gpus all nvidia/cuda:12.4.0-base-ubuntu22.04 nvidia-smi
```

**VERIFY**: all three succeed (the last proves GPU passthrough into
containers). If the last fails, the NVIDIA Container Toolkit is missing —
follow NVIDIA's WSL2 install guide (needs sudo; ask Oaj), or if Oaj uses
Docker Desktop, enable "Use the WSL 2 based engine" + WSL integration for
his Ubuntu distro. Also: `echo $DISPLAY` should be non-empty (WSLg provides
GUI support; `xhost` may not exist on WSLg — if `xhost +local:root` errors,
skip it and continue; WSLg usually works without it).

Also append one line to `pytorch_ssd/DECISIONS.md`: Oaj's WSL2/NVIDIA
machine is the team's simulator host. Commit, push.

## Milestone 1 — Build the environment (one-time, slow)

Exactly MinHyuk's recipe:

```bash
mkdir -p ~/crazyflie_docker/my_code
cd ~/crazyflie_docker
git clone https://github.com/dmz44/Crazyflie_Simulator_Container.git
cp Crazyflie_Simulator_Container/Dockerfile .
cp Crazyflie_Simulator_Container/docker-compose.yml .
xhost +local:root 2>/dev/null || true
HOST_UID=$(id -u) USER_HOME=$HOME docker compose up -d --build
docker exec -it remote_pc_humble bash
```

The build downloads ROS 2, Gazebo, CrazySim, firmware, cflib, cfclient —
expect a long time and many GB. Run it in the background and poll; do not
kill it for being slow. After any reboot the normal start is the same two
commands without `--build`.

**VERIFY**: `docker exec -it remote_pc_humble bash -c "ls tools/crazyflie-simulation"`
lists the simulator files. Keep all team scripts in `~/crazyflie_docker/my_code`
(mounted as `/root/my_code`; survives container deletion).

## Milestone 2 — No-flight validation (demos 1–4)

Terminal 1 (inside the container) — one MuJoCo Crazyflie:

```bash
bash tools/crazyflie-simulation/simulator_files/mujoco/launch/sitl_singleagent.sh -m cf2x_T350 -x 0 -y 0
```

Terminal 2 (second `docker exec -it remote_pc_humble bash`): save the
repository's tutorial script as `/root/my_code/crazysim_cflib_tutorial.py`
(the README calls it `demo.py` in one place — use this name consistently),
then:

```bash
cd /root/my_code
python3 crazysim_cflib_tutorial.py list
python3 crazysim_cflib_tutorial.py 1    # connect, inspect firmware/params/logs
python3 crazysim_cflib_tutorial.py 2    # read/write runtime parameters
python3 crazysim_cflib_tutorial.py 3    # position telemetry (sync)
python3 crazysim_cflib_tutorial.py 4    # velocity telemetry (async)
```

Known quirk: if the script cannot connect with its default
`udp://0.0.0.0:19850`, use the explicit loopback `udp://127.0.0.1:19850`.

**VERIFY**: demos 1–4 complete without repeated firmware/estimator errors
and the simulator runs near real time. **This is the team milestone Prof.
Mok asked for** — record the exact outputs.

## Milestone 3 — Flight validation (demos 5–7)

Same setup; demo 5 is the first one that spins motors (the tutorial's
comment claiming demo 4 flies is wrong):

```bash
python3 crazysim_cflib_tutorial.py 5    # MotionCommander relative moves
python3 crazysim_cflib_tutorial.py 6    # PositionHlCommander absolute waypoints
python3 crazysim_cflib_tutorial.py 7    # fly + log -> trajectory.csv
```

**VERIFY**: clean takeoff, stable hover, bounded movement, landing, clean
disarm; `trajectory.csv` shows plausible commanded-vs-observed motion.
Copy `trajectory.csv` to `~/crazyflie_docker/my_code/` and later into
`pytorch_ssd/docs/sim_results/` (small file) with a dated note.

## Milestone 4 — Simulated AI-deck camera + frame capture for the backend

Terminal 1:

```bash
bash tools/crazyflie-simulation/simulator_files/mujoco/launch/sitl_camera.sh -s scene_obstacles.xml
```

Terminal 2:

```bash
python3 crazyflie-lib-python/examples/aideck/fpv.py tcp://127.0.0.1:5050
```

**VERIFY**: a live grayscale camera window from the simulated drone.

Then the hand-off the backend needs: write `/root/my_code/capture_frames.py`
— a copy of `fpv.py` that, instead of (or in addition to) displaying,
saves every Nth decoded frame as PNG to `/root/my_code/sim_frames/`
(target: 30–50 frames while the drone hovers/moves through the obstacle
scene, at the camera's native resolution, grayscale, filenames with a
frame index and timestamp). Also write `sim_frames/README.txt` recording
resolution, pixel format, approximate frame rate, and the exact launch
commands. Copy `sim_frames/` into `pytorch_ssd/docs/sim_frames_sample/`
(keep it under ~5 MB — downscale count, not resolution) and push. Sai uses
these to build the perception bridge (simulated camera → our person
detector → 14-value decode → cflib commands, per docs/firmware_contract.md)
so it plugs straight into this simulator.

## Report back

Append a dated "Simulator bring-up (Oaj)" entry to `pytorch_ssd/EXPERIMENTS.md`:
GPU/driver versions, build time, which milestones passed, any deviations
from MinHyuk's README (there are known inconsistencies: `demo.py` vs
`crazysim_cflib_tutorial.py`, the demo-4-flies comment, the `0.0.0.0` vs
`127.0.0.1` URI), and the frame-capture details. Commit and push. Then
the team decides on the perception-bridge integration session.

## Do not

- Do not modify anything under `tools/` inside the container except via
  the shared `my_code` folder — `docker compose down` erases it.
- Do not attempt physical-drone steps; this task is simulator-only.
- Do not commit the container image, ROS workspaces, or large logs.
