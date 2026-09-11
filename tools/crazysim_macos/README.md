# CrazySim on macOS (Apple Silicon)

Runs MinHyuk Park's Crazyflie simulator on a Mac. No NVIDIA GPU, no Ubuntu,
no WSL. Verified on an M-series MacBook (Sep 10, 2026).

**How it works.** CrazySim is two processes that talk over UDP: the Crazyflie
firmware compiled for PC (`cf2`) and a MuJoCo physics script (`crazysim.py`).
MuJoCo, its 3D viewer, and `cflib` all run natively on macOS. The firmware
cannot, because its build uses a GNU linker script Apple's linker rejects, so
it runs in a small arm64 Linux container (~0.9 GB, no ROS, no Gazebo, no GPU).
Your `cflib` scripts connect to `udp://127.0.0.1:19850` exactly as they would
on Ubuntu, and switch to real hardware by changing only the URI.

## Setup (once)

Needs Docker Desktop running and Python 3.11+.

```bash
cd pytorch_ssd/tools/crazysim_macos
./setup.sh
```

## Run

| Mode | Command | What you get |
|---|---|---|
| Viewer | `./run_sim_viewer.sh` | 3D MuJoCo window on the Mac, drone at origin |
| Headless | `./run_sim.sh single` | No window; fastest |
| Camera | `./run_sim.sh camera` | Obstacle scene + simulated AI-deck camera on `tcp://127.0.0.1:5050` |

Then, in another terminal (use the venv setup created, `../../../crazysimenv`):

```bash
../../../crazysimenv/bin/python crazysim_cflib_tutorial.py 1   # connect
../../../crazysimenv/bin/python flight_check.py                # takeoff + supervisor trace
../../../crazysimenv/bin/python cpx_grab.py --n 30             # camera mode: save frames
```

Tutorial demos 1–4 don't fly; 5–7 fly.

## Measured results

| Check | Result |
|---|---|
| cflib connect, params, telemetry (demos 1–3) | pass |
| Takeoff (fresh sim) | climbs to 0.55 m, supervisor goes armed → flying |
| Fly-and-log (demo 7) | x 0 → 0.66 m, z 0.02 → 0.55 m |
| Speed | ~0.9x real time (21.2 s sim over 23.7 s wall), both modes |
| Camera | 324x244 grayscale at ~13 fps (target 20) |
| Our deployed model on sim frames | runs; empty room → person confidence 0.047 |

## Gotchas

- **The firmware locks after every landing** (`SUP: Locked, reboot required`).
  Restart the sim between flight scripts; each launcher takes ~5 s. This is
  firmware behavior and happens on Ubuntu too when demos run back to back.
- Only the **MuJoCo backend** works here. The Gazebo backend needs Gazebo and
  a GPU.
- `cflib` prints a "legacy TYPE_HOVER" deprecation warning; it's harmless.
- The viewer needs `mjpython` (installed by setup), not plain `python`.
- Camera mode renders on CPU (OSMesa), hence ~13 fps.

## Licensing

`crazysim_cflib_tutorial.py` is adapted from MinHyuk Park's repository (MIT).
CrazySim (GPLv3) is cloned into the image and copied to
`../../../crazysim_mujoco` at setup; it is not vendored into this repo.
