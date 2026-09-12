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
../../../crazysimenv/bin/python cpx_grab.py --sim --n 30       # camera mode: save frames
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

## Demo (one command)

```bash
./demo.sh                  # moving person, 3D viewer, then a plain-English scorecard
./demo.sh --scene freeze   # camera freezes mid-flight: hover, then land (also: static, empty)
./demo.sh --headless       # no window; use when the screen is locked
./demo.sh --stop           # clean up a simulator left over from an earlier run
```

It builds missing scenes, checks Docker and the screen lock, flies one
flight on a fresh sim with the person's true position logged, shuts
everything down, and prints the scorecard (`demo_scorecard.py`). Logs go to
`follow_runs/demo_<scene>_<time>/`. `run_sim_headless.sh` is the windowless
launcher it uses for `--headless`. `make_demo_video.py` renders a flight
flown with `--save-frames` into an MP4 (camera view with the model's output,
plus a top-down map). Talk track and backup videos: `docs/demo/`.

## Person following (closed loop)

Our deployed model flies the simulated drone: simulated AI-deck frames go
into the model, and its decoded output steers the drone through `cflib`.

**1. Build test scenes.** A real COCO person (masked, composited onto the
wall color) stands on a panel; the swaying variant moves on an undamped
spring, so no simulator code changes. Needs COCO val2017 and the
`pytorch_ssd_unstable` worktree.

```bash
../../../trainenv/bin/python build_person_scene.py --img-id 19432 --ann-id 428692 --person-x 3.5 --person-y -1.0 --out scenes/static_offset --preview --distances 3.5
```

```bash
../../../trainenv/bin/python build_person_scene.py --img-id 19432 --ann-id 428692 --person-x 3.0 --sway-amp 1.2 --sway-period 20 --out scenes/moving
```

```bash
../../../trainenv/bin/python build_person_scene.py --img-id 19432 --ann-id 428692 --person-x -2.5 --out scenes/empty
```

`--preview` renders the drone's view at each distance and prints what the
model sees. Person 19432 was picked by scoring 38 full-body COCO people:
confidence 1.00 at every distance from 1.5 to 3.5 m.

**2. Fly.** One command per flight (fresh sim each time):

```bash
./run_follow_demo.sh scenes/static_offset --duration 35
```

**Safety rules in the follower**, from MinHyuk's simulator exit criteria:
no motion unless a person is confirmed (confidence at least 0.7 on 3
consecutive frames; tracking drops below 0.45);
hover when the person is lost; hover if frames are older than 0.5 s and
land after 3 s; speed capped at 0.3 m/s and yaw at 40 deg/s; approach only
when the person is roughly centered. After any stale-frame hover the
follower drops the target, so it steers again only after 3 fresh confirming
frames, never on the first frame after a camera freeze.
`--simulate-stale-at SECONDS` freezes the feed mid-flight to test the
camera-loss rule; add `--simulate-stale-for SECONDS` to end the freeze and
test re-confirmation (e.g. `--simulate-stale-at 20 --simulate-stale-for 1.5`).

Without `--sim`, `cpx_grab.py` connects to a real AI-deck access point
(192.168.4.1, port 5000) and also accepts JPEG frames; see
`docs/real_frame_capture_protocol.md` for the real-camera session.

**Chip-speed emulation and recording** (added Sep 10)

- `--rate-hz 6.5` models the chip as a serial processor: it starts on the
  newest frame only when the previous inference is done, and never catches
  up on missed frames. The chip measures about 6.5 Hz on one core.
- `--latency-ms 153` applies each command 153 ms after its frame arrived.
  This counts from frame arrival, so it can be up to about one camera
  interval (70 ms) more optimistic than a chip that captures only when it
  becomes free. Fly a second run with `--latency-ms 220` to bound that.
- `--save-frames DIR` stores every processed frame with the model's raw 14
  outputs, the decoded values, the pose, and timestamps, as compressed npz.
- A torn-frame guard drops any frame whose chunks arrive out of order or
  incomplete, and counts them in the log.
- `analyze_follow.py` marks a run valid only when the sim ran at 0.8x real
  time or better, the achieved rate is at least 90% of `--rate-hz`, and no
  two processing starts are closer than 95% of the chip period.

**Results on this Mac (Sep 10, final settings)**

| Test | Result |
|---|---|
| Person 3.5 m out, 1 m right | tracked 99.4% of frames; true bearing error 1.1° average; closed to 2.3 m; clean landing |
| Empty room | never tracked, never moved |
| Camera frozen mid-flight | hovered, then landed |
| Person swaying ±1.2 m | tracked 99.7% of frames; true heading error 2.7° average, 7.7° worst |
| Person swaying, at chip speed (6.5 Hz, 153 ms) | tracked 99.2%; 3.1° average, 7.9° worst; no oscillation |
| Same, with 220 ms delay | tracked 99.2%; 3.2° average, 8.0° worst |
| Person 3.5 m out, at chip speed | tracked 98.7%; settles 4.8° off, inside the center bin |
| Empty room, at chip speed | never tracked, never moved; peak confidence 0.64 |

Full details: the Sep 10 entry in `EXPERIMENTS.md`. Raw logs, true-position
logs, and charts: `docs/sim_results/2026-09-10/` and, for the chip-speed
flights, `docs/sim_results/2026-09-10-chip/`.

**Reproduce or extend**

- `./run_acceptance.sh` re-flies all five tests on fresh sims with the
  person's true position logged, scores each, and draws the chart.
- `analyze_follow.py` scores one run; `plot_follow.py` charts heading
  against the true direction to the person.
- `scan_people.py` re-scores COCO people to pick a different test subject.

**Gotchas found getting this working**

- macOS limits one UDP message to 9 KB; the simulator's 60 KB camera chunks
  were silently dropped. `setup.sh` shrinks them to 8 KB.
- MuJoCo renders transparent texture pixels black, so the person is
  composited onto the wall color instead of using an alpha cutout.
- Yaw sign: in this simulator a positive yaw-rate command turns left, so
  the follower uses sign −1. `cflib` flips the sign for older firmware, so
  re-check it on the real drone.
- The follower runs from `trainenv` and needs `cflib` 0.1.33 there; 0.1.27
  fails on macOS. `setup.sh` installs it.

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
