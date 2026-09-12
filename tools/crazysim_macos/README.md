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

**Camera realism (opt-in)**

By default the simulator pushes the raw MuJoCo render, which is pixel-sharp,
noiseless, and far brighter than the real sensor: measured at mean 157–190 DN
with 23–32% of pixels clipped at 254, against the Himax's own auto-exposure
target of 60 DN. `camera_model.py` narrows that gap inside the simulator, so
every consumer — the follower, `gap8_emulator.py`, `cpx_grab.py --sim`,
`--save-frames`, the videos — sees the same degraded frames.

**It closes half of the gap, and only half.** Two different things are wrong
with the raw render, and the model can fix one of them:

- *Brightness and noise regime* — **fixed.** The AE loop drives the frame mean
  to the sensor's own 60 DN target and the shot/read/fixed-pattern noise is
  reproduced from the photon-transfer model, so the frame the network sees sits
  in the right exposure and SNR regime instead of a washed-out one.
- *Destroyed highlight detail* — **not fixed, and not fixable here.** On the
  control scene 25.8% of pixels leave the renderer with all three channels at
  ≥ 254. Those pixels carry one saturated value; the structure that was there is
  gone before `camera_model.py` ever sees the frame. Rescaling them to 60 DN
  makes the histogram look right without putting the information back: measured
  over the formerly-clipped region, the vignette-corrected spatial standard
  deviation is 2.32 DN against 1.80 DN for shot + read + quantisation noise
  alone — 1.29x, i.e. essentially just noise. A quarter of every frame is
  featureless grey where the real camera would resolve wall and highlight
  detail.

So **"0.0% of pixels saturated after the model" is not evidence the gap is
closed** — it only says nothing clips once the frame has been rescaled. Closing
the remaining half needs the renderer to stop over-exposing in the first place
(an opt-in scene-lighting change; see the open issues), not a better sensor
model.

It is off unless you ask for it, and it is set on the **simulator**, not the
follower:

```bash
CRAZYSIM_SENSOR_PRESET=himax_typical ./run_sim_headless.sh --camera \
  --scene scenes/moving/scene_person.xml
```

| Preset | What it models | Cost/frame |
|---|---|---|
| `clean` (default) | nothing — the original code path runs verbatim, bytes unchanged | 0 ms |
| `himax_typical` | a normally lit room: AE to 60 DN, 1.5 px-FWHM optical blur, vignetting, shot/read/fixed-pattern noise, dead pixels, gyro-driven motion blur | ~1.8 ms |
| `himax_low_light` | the dim-corridor stress case: integration pinned at the 340-line ceiling, then **~8x total gain**, ~4.3 DN noise, LED row banding | ~1.9 ms |
| `himax_color_bayer` | the AI-deck 1.0 colour module: RGGB mosaic (the firmware's 2x2 average is then a fixed-weight `(R+2G+B)/4` luma) plus the halved luma sampling | ~1.1 ms |

**`himax_low_light` is specified by its total gain, not by the analog step.**
An earlier version of this table said "analog gain driven to 8x". It usually is
not: the gain the AE needs lands right on the 4x/8x analog boundary, so the
analog/digital split flips with the noise seed — a 20-seed sweep on one fixed
scene and viewpoint settled on analog 4x nine times and 8x eleven times, with
total gain 7.70–8.06x throughout. The split is physically inert in this
implementation (the noise model uses the *total* gain for both the shot and the
read term), so what the preset actually delivers — ~8x total gain and ~4.3 DN
noise, which is what the spec's low-light table was computed from — is correct
and stable. Only the stated mechanism was wrong.

**Motion blur, and what actually fires in flight.** Blur length is
`|omega| * t_exp * 174.23 px/rad`, taken from the drone's own gyro on the yaw
and pitch axes. At the exposure the control flight actually ran (137 lines =
4.257 ms) the follower's own 40 deg/s yaw cap is **0.52 px**, and the commanded
yaw rates over that flight give a mean of 0.06 px and a maximum of 0.35 px — so
in normal flight this effect is **entirely sub-pixel**. It only reaches
1.29 px at 40 deg/s if the AE is also pinned at its 10.56 ms ceiling.

That matters because sub-pixel blur used to be silently discarded. The kernel
sized its support as `ceil(L)`, so every length in `(0, 1]` px collapsed to the
single tap `[1.0]` — an exact identity — and the 0.5 px gate admitted lengths in
`(0.5, 1.0]` only to throw them away. Since 100% of real in-flight blur lives in
that band, the feature was a no-op on every flight ever flown with it. The
kernel now moment-matches the smear below ~1.1 px (a 0.7 px smear has variance
`L^2/12` = 0.0408 and moves ~5 DN across a hard edge) and uses the exact
area-overlap box above it, with a support wide enough that no tap is truncated.
`test_box_kernel_is_sane_across_every_regime` pins the behaviour from 0.05 px to
10 px.

**Measured (Sep 11), control `moving` scene, headless, 50 s, default follower
settings, one fresh sim each.** Both runs pass `analyze_follow.py` as valid.

| Flight | Tracked | True heading error | Camera rate | sim/wall | Sensor cost |
|---|---|---|---|---|---|
| `clean` | 99.7% | 2.8° mean, 5.2° p90, 8.7° max | 14.9 Hz | 0.995 | — |
| `himax_typical` | 99.6% | 2.8° mean, 5.4° p90, 8.8° max | 14.7 Hz | 0.993 | 2.2 ms/frame mean, 4.2 ms max |

**Sensor cost went up when the motion-blur no-op was fixed, and it now breaches
its own budget.** The row above is the pre-fix measurement. Across the 16
`himax_typical` flights flown after the fix the model costs **3.50 ms/frame on
average with a worst single frame of 7.27 ms, and 6 of those 16 runs had a
worst frame above the 5 ms cap** — because the blur convolutions now run on
every frame instead of never. The unit-test bench does not catch this (it
measures 1.8 ms in isolation; in flight the follower and the model share the
Mac). Nothing downstream broke — every one of those flights was valid at
sim/wall 0.997–1.000, which is what the cap actually exists to protect — but
the budget is a budget. The cheap fix, measured and not yet applied: skip the
convolution when the kernel's side tap is below ~0.0005, which at the observed
in-flight rates would skip 64.5% of frames while forgoing at most ~0.26 DN,
comfortably under the quantisation floor.

**The realistic camera does not make the follower worse.** Heading error is
unchanged to within 0.1°, tracking within 0.1 pp, no dropped or torn frames in
either run, and the `clean` flight reproduces the Sep 10 baseline (2.7°, 99.7%)
exactly, which is what says the comparison is sound. Perception degrades a
little without mattering: mean confidence 0.980 → 0.962 and the worst frame
0.748 → 0.787, never once below the 0.7 enter threshold, so the confirmation
logic is never stressed.

The one real behavioural difference is **distance keeping**: the drone closed to
2.64 m on `clean` but only 2.98 m on `himax_typical`, because the softer,
noisier image reads one size bucket smaller (bucket-3 frames 29 → 3). It holds
about 0.34 m further back — worth knowing before the first hardware flight, and
a reason to re-measure any distance-keeping number under a preset rather than
under `clean`.

`CRAZYSIM_SENSOR_SEED` (default 1234) makes a run reproducible;
`CRAZYSIM_SENSOR_INFO` says where to write the preset, seed, parameters, live
AE state and measured per-frame cost (default: `camera_model.json` next to
`CRAZYSIM_TRUTH_LOG`, so it lands in the run folder).

**`clean` is a pass-through, not "all effects zeroed"** — with the variable
unset the patched simulator takes its original line unchanged, so every
verified baseline above stays valid without re-running anything. Parameters
that are class estimates rather than measurements carry an `UNMEASURED` tag
that survives into `camera_model.json`; the design, the register evidence and
the plan for measuring them against real frames are in
`scratchpad/simv2/spec_camera.md`.

- `test_camera_model.py` checks each effect against the number the spec
  predicts (noise sigma vs intensity, blur width vs angular rate, AE target
  and lag, Bayer luma weights, byte-identical `clean`, cost under budget).
- `dump_camera_samples.py` writes a side-by-side contact sheet, clean next to
  each preset at several distances, for human review.

**Reproduce or extend**

- `./run_acceptance.sh` re-flies all five tests on fresh sims with the
  person's true position logged, scores each, and draws the chart.
- `analyze_follow.py` scores one run; `plot_follow.py` charts heading
  against the true direction to the person.
- `scan_people.py` re-scores COCO people to pick a different test subject.

## Simulator v2 (Sep 12, 2026): realistic camera, harder scenes, the chip's own network

Everything here is opt-in. Existing commands (`demo.sh`, `run_acceptance.sh`,
`follow_person.py`, `gap8_emulator.py` with no new flags) behave exactly as
before.

- **Scenes with more than one subject.** `build_scene.py` builds a scene from a
  JSON definition in `scene_defs/`: any number of subjects (people, pets,
  a teddy, a poster), each with its own motion, plus occluders, furniture and
  three lighting variants. Each scene ships a `manifest.json` saying which
  subject the drone should follow and which it must ignore, and the simulator's
  truth log now records every subject. `--preview` renders a contact sheet;
  `--check` verifies every COCO image id.
- **A realistic camera.** `camera_model.py`, wired into the simulator by
  `patch_crazysim.py`, applies what the real Himax sensor does: auto-exposure to
  its real target, shot and read noise, lens blur and vignetting, motion blur
  from the drone's own angular rate, and an optional colour (Bayer) mode. Choose
  with the environment variable `CRAZYSIM_SENSOR_PRESET`
  (`clean` is the default and is byte-identical to before; `himax_typical`,
  `himax_low_light`, `himax_color_bayer`). `dump_camera_samples.py` writes
  side-by-side frames, and `test_camera_model.py` checks each effect.
- **Fly the chip's network, not the laptop model.** `--backend chip` on
  `follow_person.py` or `gap8_emulator.py` runs the firmware's own preprocessing
  (2x2 box average) followed by the integer network the chip runs.
  `perception_backends.py` starts `chip_infer_server.py` automatically (it needs
  `../../../doryenv`). `--backend float` stays the default.
- **Acceptance suite v2.** `./run_acceptance2.sh` flies the matrix headless, one
  flight at a time, and `scoreboard.py` scores it with pass/fail thresholds
  including distance keeping, false-follow on distractor scenes, reacquire time
  and command smoothness. Results, with the findings, are in
  `docs/sim_results/2026-09-11-simv2/`.

**Gotchas found getting this working**

- macOS limits one UDP message to 9 KB; the simulator's 60 KB camera chunks
  were silently dropped. `setup.sh` shrinks them to 8 KB.
- MuJoCo does not honour texture alpha at all: it drops the channel at load
  time (`tex_nchannel` is 3 even for an RGBA PNG), so an alpha cutout renders
  its transparent texels as opaque colour rather than as background. Subjects
  are therefore composited onto an opaque background. `build_person_scene.py`
  uses one flat wall colour; `build_scene.py` matches the background to what is
  actually behind the panel (see the scene-suite section).
- Yaw sign: in this simulator a positive yaw-rate command turns left, so
  the follower uses sign −1. `cflib` flips the sign for older firmware, so
  re-check it on the real drone.
- The follower runs from `trainenv` and needs `cflib` 0.1.33 there; 0.1.27
  fails on macOS. `setup.sh` installs it.

## Scene suite v2 (`build_scene.py`)

`build_person_scene.py` builds one person on one panel. `build_scene.py` builds
a whole *scene* — any number of subjects, each a COCO cutout on its own panel
with its own motion, plus occluders, primitive clutter and a lighting variant —
from a definition in `scene_defs/`. It is a separate script, so `demo.sh`,
`run_acceptance.sh` and the published baselines are untouched.

```bash
../../../trainenv/bin/python build_scene.py --all --check      # verify COCO ids + cutouts
../../../trainenv/bin/python build_scene.py --all --preview    # build + contact sheets
../../../trainenv/bin/python build_scene.py --def scene_defs/s03_pets_only.json --preview
```

Each scene lands in `scenes_v2/<id>/` (gitignored, like `scenes/`) as
`scene.xml`, `manifest.json` (the ground-truth contract: every subject's body
name, role, COCO ids, size in metres and intended trajectory), one PNG per
subject, `preview.png` (a contact sheet of what the drone camera sees from
several distances, with the centre 244x244 crop the model actually sees drawn
on) and `probe.json`.

**Every subject is an opaque rectangular card, and that is a renderer limit.**
Worth knowing before reading any detection result off these scenes: the panel
shows a COCO cutout, but everything outside the mask is *painted wall colour*,
not transparency, so the network sees a rectangle as well as a person. This is
not a choice — MuJoCo 3.13 discards the alpha channel when it loads a PNG
(`tex_nchannel` comes back 3 for an RGBA file), so an alpha cutout renders its
transparent texels as opaque colour, and a mask-shaped mesh is not a way out
either: a flat silhouette fails to compile ("coplanar vertices, cannot compute
convex hull") and an extruded one rendered zero pixels. All three routes were
tried and measured.

**The card is measurably visible, mostly against the floor.** At the drone's eye
line, 2.5 m out, the edge step is **+39 to +108 DN against the floor** (a person
panel spans 119 image rows and 34 of them sit against floor rather than wall)
and −113 to +59 DN against the wall. The network is therefore partly keying on a
high-contrast rectangle, and this applies to every scene here and to the
September baselines, which `build_person_scene.py` composites the same way.

**A background-matching composite exists, was measured, and is deliberately not
the default.** `build_scene.py --background sampled` hides each panel, renders
what is really behind it, and repaints the cutout with that (divided by the
panel's own shading factor, which is per subject — measured 0.886 to 1.387).
It works where it was calibrated and not much further:

| | floor-side step | wall-side step |
|---|---|---|
| flat (default) | 50.3 DN mean on people/pets, up to 108 on furniture | 19.2 DN mean |
| sampled | **2.8–11.7 DN** on people/pets | 13.2 DN mean, but furniture gets *worse* (couch −74 → −95) |

It never reaches the ~5 DN target away from people and pets, and — the reason it
stays off — **it changes what the network reports**: on the furniture scene,
which exists precisely to confirm the drone ignores inanimate objects,
confidence rose from 0.755 to 0.957 at 2.5 m against a 0.70 latch threshold, and
on the control scene the size bucket moved 0.625 → 0.375 at 3.5 m, which feeds
the forward-velocity law and therefore the headline hold-distance metric.
Turning it on would quietly change the acceptance results it is meant to make
more realistic, so it is opt-in and unflown; the default cutouts are
byte-identical to the ones every published flight used. Each scene's
`manifest.json` records the mode and these caveats under
`subjects[].background`.

Subject bodies are named `subj_*`, which is also their key in the ground-truth
log. Two new environment variables, both unset by default:

| Variable | Effect |
|---|---|
| `CRAZYSIM_TRUTH_PREFIX` | unset = today's log exactly (body `person`, `wall,sim,x,y`). Set (the suite uses `subj_`) = a `#` header naming the bodies, then `wall,sim,` and `x,y,z` per body. `numpy.loadtxt` skips `#` lines and subject 1's x,y stay in columns 2 and 3, so `analyze_follow.py` reads the new format unmodified. |
| `CRAZYSIM_SCENE_MOTION` | points at a scene's `motion.json`; the patched simulator then drives that scene's scripted `drift` joints kinematically (constant velocity with a start time and end stops). MJCF alone cannot express this — a joint's initial velocity can only come from a `<keyframe>`, and keyframes do not survive CrazySim's drone attach. |

Motion is `static`, `spring` (pure MJCF, the mechanism the Sep 10 baselines
used) or `drift` (the patched drive above). The manifest records *intended*
motion; always score the *realised* path from the truth log.

## Acceptance suite v2 and the scoreboard (`run_acceptance2.sh`, `scoreboard.py`)

`run_acceptance.sh` is the Sep 10 gate and is unchanged: five viewer-based tests
that still do exactly what they always did. `run_acceptance2.sh` is a second,
additive runner that ties the v2 scenes, the chip perception backend and the
realistic camera together into one matrix, flies it headless, and scores it.

```bash
./run_acceptance2.sh --list                  # print the matrix, fly nothing
./run_acceptance2.sh                         # CORE matrix: 14 cells x 2 repeats = 28 flights
./run_acceptance2.sh --smoke                 # 2 short flights, plumbing only
./run_acceptance2.sh --only 'B\.' --repeats 3
../../../trainenv/bin/python scoreboard.py <out_dir>     # re-score offline, any time
```

The CORE matrix is **spine-plus-deltas**, not a fraction of a full factorial
(design: `scratchpad/simv2/spec_metrics.md` §6):

| Block | Configuration | Scenes |
|---|---|---|
| Spine 1, "ships-as" | chip network + `himax_typical` camera + 6.5 Hz / 153 ms | all 6 scene classes |
| Spine 2, "proven" | float model + clean camera + full speed | 5 classes (A–E) — the cells that must still match the September baselines |
| Deltas | one factor moved off Spine 2, on the moving scene | speed, camera, backend |

Every flight is headless, runs alone behind the shared simulator lock, logs
ground truth for every subject, and is checked for validity the moment it lands;
an INVALID flight is re-flown once. The simulator is torn down and the lock
released after every flight, including on failure or Ctrl-C. `progress.log` and
`progress.md` are written as it goes, so a long run can be inspected while it
flies.

`scoreboard.py` is a separate step and reads only what the flights already
wrote, so it can be re-run after the fact (and was, whenever a threshold moved).
It adds five things `analyze_follow.py` does not measure:

| ID | Measures | Gate |
|---|---|---|
| M7 | distance-keeping error in metres, against the hold distance derived from the camera FOV and the size buckets (1.94 m for a 1.7 m person; the whole 1.62–2.43 m band is the same bucket) | mean error ≤ 0.75 m, final inside the band ±10% |
| M8 | false follows: confirmations while no person is in view, and how far the drone flew because of one | hard zero on empty/furniture scenes; **characterised, never gated** on pet/teddy scenes |
| M9 | how long the track was lost, how long the drone stayed unlatched *after the target was genuinely back in view* (a line-of-sight test against the scene's declared occluder boxes, sampled across the target's width), and whether steering resumed before the 3-frame re-confirmation | re-confirmation is a hard boolean; `M9_gt_visible_to_relatch_s` ≤ 1.0 s (1.5 s at chip speed). `M9_reconfirm_latency_s` — the metric once called `M9_reacquire_s` — is **report-only**: it is structurally `2/R` plus a control tick and never measured reacquisition. `M9_track_outage_s` is reported and never gated, because it includes the deliberate occlusion |
| M10 | fraction of frames in the [0.45, 0.70) band where behaviour is decided by hysteresis alone | ≤ 0.05 clean, ≤ 0.15 on the degraded camera (provisional) |
| M11 | command smoothness: yaw-rate sign reversals per minute, saturation fraction | **provisional, report-only** until calibrated from the first sweep |

Two rules keep the scoreboard honest and are worth knowing before reading one:

- **Nothing is gated on a threshold that was guessed.** Metrics whose pass mark
  has no measured baseline (M11, and every relaxation for the degraded camera)
  are recorded with their values and marked `REPORT_ONLY`; they contribute no
  verdict. Every gate carries a `basis` string saying where its number came from.
- **A cell with fewer than 2 valid flights is INVALID, never PASS**, and an
  INVALID cell makes the whole suite INVALID. Safety metrics are scored on the
  worst repeat, quality metrics on the median.

Outputs land in the suite directory: `scoreboard.json` (machine record, every
run, every gate, every basis) and `scoreboard.md` (written for someone who has
never seen the project — plain scene names, degrees not x values, metres not
fractions).

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
