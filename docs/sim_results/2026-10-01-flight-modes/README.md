# First-flight safety modes and the kill switch in CrazySim, 2026-10-01

Evidence for branch `sai/flight-safety-modes`: the follow app's `yawOnly` and geofence modes
(`tools/stm32_follow_app/app/src/follow_app.c`) and `tools/hardware/kill_switch.py`, flown in
CrazySim (SITL firmware v1.2-alpha-24-gaa6571dc in the image `crazysim-mac:follow-app-safety`).
**Nothing here ran on a real Crazyflie.** `dryRun` was not flown in the simulator; it is covered
by the host tests only (`make app-test`).

Files: `summary.json` (follow-app flights, scored by
`tools/stm32_follow_app/sim/flight_modes_summary.py`), `<flight>_10hz.csv` (10 Hz traces:
pose, yaw, the person's true bearing, commands, setpoint kind, fence status, posVar),
`kill_switch_sitl.json` and `kill_switch_*_50hz.csv` (from `tools/hardware/kill_switch_sim_check.py`).
Raw logs (50 Hz app log, packets, truth, firmware console) are outside the repo in
`drone/demo/follow_app_runs/2026-10-01-flight-modes/` and `drone/logs/kill_switch_sitl/`.

## Setup

Each flight is a fresh headless sim (`sim/fly_app.sh`; the firmware locks after every landing)
with `gap8_emulator.py` as the AI-deck and the champion model on the Mac, scene `static_offset`
(one person standing 3.5 m ahead and 1.0 m to the right: true bearing -15.9 deg at take-off). The
host takes off to 0.8 m with hover setpoints, writes any `--app-param`, sets `followapp.enable = 1`
and then only watches. The sim ran beside another agent's simulator on its own ports
(`CRAZYSIM_PORT=19960`, `CRAZYSIM_CAM_PORT=5260`, container `crazysim-safety`); sim/wall
0.971-0.994. Re-fly, for example:

```sh
cd tools/stm32_follow_app
FOLLOW_APP_IMAGE=crazysim-mac:follow-app-safety ./sim/build_image.sh
CRAZYSIM_CONTAINER=crazysim-safety CRAZYSIM_PORT=19960 CRAZYSIM_CAM_PORT=5260 \
  FOLLOW_APP_IMAGE=crazysim-mac:follow-app-safety \
  ./sim/fly_app.sh yawonly static_offset 20 --app-param yawOnly=1
```

| flight | params | sim flags |
|---|---|---|
| `yawonly` | `yawOnly=1`, fence default (on) | none |
| `yawonly_turb` | `yawOnly=1`, fence default | `CRAZYSIM_EXTRA="--sensor-noise --turbulence light"` (IMU/baro noise, Dryden wind sigma 0.5 m/s) |
| `fence` | defaults (normal follow, fence on: +-1.0 m, z <= 1.2 m) | none |
| `noabs` | defaults | `CRAZYSIM_EXTRA="--flowdeck"` (no absolute position sent to the estimator) |

## Results

**yawOnly holds x/y and turns toward the person.** Numbers are over the 20 s the app was ACTIVE.

| | `yawonly` (no disturbance) | `yawonly_turb` (noise + light turbulence) |
|---|---|---|
| drift from the arming point, mean / p95 / max | 0.000 / 0.000 / 0.000 m | **0.045 / 0.115 / 0.123 m** |
| x range, y range | 0.000, 0.000 m | x -0.165..-0.012, y -0.027..0.060 m (arming point -0.052, 0.032) |
| height after the first 1 s, mean (min-max) | 0.809 (0.800-0.851) m | 0.810 (0.787-0.878) m |
| heading error at take-over | 15.9 deg | 16.2 deg |
| heading error after 5 s, mean / max | **1.25 / 1.46 deg** | **1.20 / 2.10 deg** |
| first yaw-rate command | -26.7 deg/s (clockwise: person on the right) | -26.7 deg/s |
| yaw-rate commands turning toward the person | 100% | 100% |
| forward command (vx sent, wVx) | 0.000 / 0.000 m/s | 0.000 / 0.000 m/s |
| setpoints | 989 position-hold | 986 position-hold |
| landing (operator, `enable = 0`) | ACTIVE -> DONE 2.82 s, z after 0.02 m | 2.97 s, z after 0.02 m |

The noise-free drift is zero to the logged precision (under 1e-10 m) because the simulated pose
is perfect and nothing pushes the drone; it only shows that the setpoint is the latched point. The turbulence flight is the
meaningful one: the PID position loop held the arming point to 12 cm worst case against
a 0.5 m/s random wind, while yawing 17 deg. For comparison, the `fence` flight below, the same
scene in normal follow mode, moved 1.0 m forward in 8.5 s.

**The fence lands the drone.** Normal follow mode; the follow law flies toward the person.

| | `fence` |
|---|---|
| ACTIVE | 8.45 s, x 0.000 -> 0.997 m (vx up to 0.20 m/s), heading error after 5 s 1.06 deg mean |
| LANDING state | at t = 15.490 s; logged x relative to the arming point 0.9993 m (the pose block is logged up to 20 ms apart from the app block); first logged sample with x > 1.0 m at 15.510 s. `landRsn` 3 (geofence), `fenceHit` 1 (outside x/y); firmware console `FOLLOW: landing (geofence)` |
| overshoot past the fence | 0.060 m (max x 1.060 m): the drone decelerates from 0.2 m/s under the zero-velocity landing setpoint |
| LANDING -> DONE | **2.88 s** (0.8 m at 0.3 m/s plus touchdown); z 0.044 m at DONE, 0.02 m after |

**No absolute position, no take-over.** `noabs`: with the simulator's pose stream off, the
Kalman x/y variance stayed at its initial 100 m^2 (`posVar` 99.99997-100.0); `enable = 1` gave
`armErr 22` (no valid position estimate) and `fence 5` (variance above `posVarMax`) for the full
10 s, the app sent nothing, and the host landed the drone itself. With the pose stream on, `posVar`
in flight was **1.1e-6 to 2.0e-6 m^2** (about 1.1-1.4 mm std), four orders of magnitude under the
default `posVarMax` of 0.01 m^2. That says nothing about Lighthouse on hardware.

## Kill switch (`kill_switch_sitl.json`)

Four checks, each on a fresh sim (`crazysim-killsw`, port 19970, no camera). CrazySim's firmware
reports CRTP protocol 7, so cflib 0.1.33 sends the legacy localization-port stop and watchdog
packets; firmware 2026.08 (protocol 12) gets the supervisor-port commands instead, **which the
SITL cannot exercise**.

| check | what happened |
|---|---|
| `key`: the real CLI in a pseudo-terminal, drone on the ground | banner shown, 22 watchdog pings, SPACE: the CLI showed "supervisor reports LOCKED" 0.1 s later; q exited with code 0; a second connection read `supervisor.info` = 68 (`auto-arm, LOCKED`); console `SUP: Locked, reboot required` |
| `deadman`: the real CLI killed with SIGKILL after 23 pings | it sent nothing; a second connection 5.8 s later read `supervisor.info` = 68 (LOCKED): the firmware's watchdog locked the drone on its own |
| `inflight`: hover at 0.63 m, kill switch embedded with `CflibKillLink.attach(cf)`, SPACE while the script **kept streaming hover setpoints** | `motor.m1` 0 after **0.022 s**, LOCKED logged after 0.062 s, z below 5 cm after **0.48 s**; stayed down for the 2 s of hover setpoints that followed |
| `silence`: the same hover, the pings simply stop (no stop sent) | `motor.m1` 0 **1.008 s** after the last ping (the firmware's 1.0 s timeout), LOCKED logged at 1.068 s, z below 5 cm at 1.47 s, while hover setpoints kept coming |

The trip time of the SIGKILL check is not measured (the second connection reads 5.8 s later); the
`silence` check is the timing measurement. Link loss on a real radio (cflib's `connection_lost`)
is covered only by the unit tests (`tools/hardware/test_kill_switch.py`).

## Not verified here

- Anything on hardware: the app has not been built for the cf2, the Lighthouse Kalman variance
  and its growth after a Lighthouse dropout are unmeasured (so `posVarMax` = 0.01 m^2 is a guess,
  to be calibrated at M4), and the supervisor-port (protocol 12) stop/watchdog packets are untested.
- `dryRun` in the simulator (host tests only), a Lighthouse dropout mid-flight (the SITL cannot
  stop its pose stream mid-flight), and the fence's y and z faces in flight (host tests only).
- The SITL estimator gets a perfect external pose; real position noise will make the yawOnly
  hold and the fence edge noisier than shown.
