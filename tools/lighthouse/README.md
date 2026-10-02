# tools/lighthouse — turning Lighthouse poses into training labels

Plan: `docs/hardware/before_the_next_session.md` §3. Decision and its conditions:
`DECISIONS.md`, 2026-09-20. Simulator validation:
`docs/eval_results/2026-09-22-pose-to-label-sim-validation/`.

## The idea in one paragraph

Two Crazyflies carry Lighthouse decks. The **follower** has the camera and flies.
The **beacon** has its props off, never arms its motors, and rides on the subject's
head. Both log where they are in the room. From the two positions, plus the direction
the follower faces, you can work out where the person was in the camera image when
each frame was taken, and so which x-bin (0-8) and size bucket (0-3) the network
*should* have output. Compare that with what the network *did* output. That works even
on frames where the network missed the person completely, which no other labelling
method we have can do.

| file | what it does |
|---|---|
| `pose_to_label.py` | two poses in, the label out: bearing, range, image x, x-bin, size bucket, "in view?" |
| `align_clocks.py` | lines up the frame timestamps with the pose timestamps (they come from different clocks) |
| `record_session.py` | **records a session**: both drones' poses + the follower's frames + `meta.json` (cfloaderenv) |
| `label_session.py` | turns a recorded session into `labels.csv` + `report.md` (trainenv) |
| `session_common.py` | the cue schedule, brightness gate, file layout and rate statistics both use |
| `run_pair_sim.sh`, `render_timeline.py` | the no-hardware rehearsal: two CrazySim drones, and frames of a scripted subject |
| `test_pose_to_label.py`, `test_align_clocks.py`, `test_record_session.py`, `test_label_session.py` | the tests; run them before trusting anything |
| `test_session_rehearsal.py` | the end-to-end rehearsal (opt-in, Docker, ~3 min) |

```
~/Downloads/drone/trainenv/bin/python -m unittest tools/lighthouse/test_pose_to_label.py tools/lighthouse/test_align_clocks.py
```
(about 25 s; the clock test really runs `mock_streamer.py` and `cpx_grab.py` over a local socket)

## The conventions, in plain English

Getting any one of these backwards does not crash anything. It quietly produces
labels that tell the drone to steer away from people. Each one has a test.

**The room.** Lighthouse gives positions in metres in a room-fixed frame: x and y
along the floor, z straight up. The frame is fixed when the base stations are calibrated:
the origin is where the Crazyflie sat for the "origin" sample, and +x points toward
the "x-axis" sample.

**Which way the drone faces (yaw).** Read it from `stabilizer.yaw` or
`stateEstimate.yaw`, in degrees. **Positive yaw means the nose has turned LEFT**
(counter-clockwise, seen from above). Yaw 0 means the nose points along room +x.
Pass the logged number straight in; do not flip it.

**Tilt (roll and pitch).** Pass the logged values straight in too.
Positive roll means the right side is down. Positive pitch means the **nose is up**.
Pitch is the one odd axis: the firmware flips its sign when it logs it (`kalman_core.c`:
`.pitch = -pitch`). `pose_to_label` flips it back for you. When the drone hovers, both
are nearly zero and barely matter.

**Left and right (bearing).** Stand behind the drone and look where it looks.
**A negative bearing means the person is on the drone's LEFT.** Positive means right.
This matches the capture protocol and `score_real_frames.py`, and it matches the
image: x-bin 0 is the left edge, 4 the centre, 8 the right edge.
*Watch out:* this is the **opposite** sense to yaw, and to the internal `bearing` in
`tools/crazysim_macos/scoreboard.py`. If you ever compare the two, one needs a
minus sign.

**Where the label points (the head-to-body offset).** The beacon sits on top of the
head, but the network was trained on COCO boxes. For a standing person, the box runs
from the top of the head to the feet, so its **centre is at half the person's height**:
around the hips, not the chest. So:

```
top of head  = beacon height - (how far the beacon's deck sits above the head)
feet         = top of head - the person's height
label target = feet + 0.5 x height        (target_frac = 0.5)
```

Measure each subject's height, and how high the beacon's deck sits above their
head, and write both down. With a level camera, the target's height does **not**
change x or the x-bin at all. It only matters when the drone tilts. The size bucket
uses the whole head-to-feet height: it is the person's height in the image divided
by the image height, split into 4 equal buckets (0 = small/far, 3 = big/near).

A person who **leans** moves their head sideways but not their hips. At 10 deg of lean
the head moves about 0.15 m relative to the hips, and that becomes a label error. Ask
subjects to stand and walk upright.

**The camera.** The network sees the centre square of the image (244 x 244 of 324 x 244).
The simulator's square is 70 deg wide. **The real camera's has not been measured**
(`tools/real_frames/measure_camera.py`). Lighthouse reports where the *deck* is, not
the lens. Measure how far the lens sits in front of the deck's reported point and pass
it with `--mount` (the simulator uses 0.03 m forward).

## First thing to run on real hardware: the static taped-mark case (plan §3.5)

Do this before any other Lighthouse data. It takes about 10 minutes and needs no
second drone. It catches a mirrored or rotated frame, a wrong head offset, and a wrong
FOV. It **cannot** catch a clock offset, because nothing moves (see "Clocks" below).

1. **Set up the marks** as in `docs/real_frame_capture_protocol.md` §2: the lens is
   0.8 m above the floor, level, looking down a taped centre line. Distances are measured
   from the point under the lens.
2. **Put the room frame on the tape.** Easiest: when calibrating Lighthouse, take the
   *origin* sample on the point under the lens and the *x-axis* sample 1.000 m down the
   centre line. Then room x = distance forward and room y = distance to the LEFT (y is
   positive on the left). If the lab already has a saved calibration, instead place a
   Lighthouse Crazyflie on each taped mark and write down the x, y it reports.
3. **Log the follower's pose for 30 s** (`stateEstimate.x/y/z`, `stabilizer.roll/pitch/yaw`)
   while it sits still on its stand, and average it.
4. The subject stands with feet centred on a mark. The beacon's position is the mark's
   x, y, at z = floor + height + deck height above the head. If there is no second
   drone, type these numbers in.
5. Run:

```
~/Downloads/drone/trainenv/bin/python tools/lighthouse/pose_to_label.py \
    --follower X Y Z YAW [ROLL PITCH] --beacon BX BY BZ --height H --mount MX MY MZ
```

### The worked example: what you should see

The subject is 2.0 m ahead and **0.5 m to the LEFT**, 1.75 m tall. The lens is at
0.8 m, level, facing room +x. The pose is taken at the lens (`--mount 0 0 0`), so the
numbers are exact:

```
pose_to_label.py --follower 0 0 0.8 0 --beacon 2.0 0.5 1.75 --height 1.75 --mount 0 0 0
bearing   -14.04 deg (LEFT; negative = drone's left)
range     2.063 m (lens to target), depth 2.000 m
image x   -0.3570  (crop pixel 41.1 of 128)
x-bin     2  (0 = left .. 8 = right; 0.024 from the nearest bin edge)
size      0.6248 -> bucket 2
```

* The **bearing** is -atan(0.5 / 2.0) = **-14.04 deg**, to the left.
* **x-bin 2**, but only just. Bin 2 covers 0.467 m to 0.778 m to the left at 2.0 m
  ahead, so standing **3.3 cm** closer to the centre line gives bin 3. The protocol's own
  marks (e.g. 2.5 m at -25 deg: bin 1, 0.111 from an edge) sit mid-bin for exactly this
  reason. Use them for pass/fail. Use this example to check the arithmetic.
* **Size**: 1.75 / (2 x 2.0 x tan 35 deg) = 0.625, **bucket 2** (bucket 2 runs from
  2.50 m down to 1.67 m for a 1.75 m person).
* With the simulator's 3 cm lens offset (`--mount 0.03 0 0`, i.e. the pose is the
  body centre), the same case gives -14.24 deg, still bin 2, size 0.634.

**Then turn the follower 30 deg to its LEFT on the stand** (logged yaw about +30) and
run the same command with `--follower 0 0 0.8 30`. The person has not moved, but the
drone now faces past them, so they are on the **RIGHT**: **+15.96 deg, x-bin 6**. If the
tool says about -44 deg or "not in view", the yaw sign is backwards. **Stop.** This yawed
step is essential: the unyawed case cannot catch a yaw-sign error, because yaw is 0.
(The simulator validation found the same thing: flights where the drone never turned
pass even with the yaw negated.)

Then check the network against it: record frames on both sides of the centre line and
run `tools/real_frames/score_real_frames.py`. Its mirror check and this tool must agree
on which side the person is.

## Clocks: the sync step at the start and end of every recording

Frames are stamped by the laptop when they arrive over WiFi (the `_t<time>` in each
`cpx_grab.py` filename). Poses come over the radio with the Crazyflie's own
timestamps. If the two clocks are off by `dt`, a person walking sideways at `v` m/s,
`d` m away, gets a label that is off by `atan(v x dt / d)`:

| offset | 0.5 m/s at 2 m | 1.0 m/s at 2 m | 1.5 m/s at 2 m | 1.0 m/s at 3 m |
|---|---|---|---|---|
| 0.05 s | 0.7 deg | 1.4 deg | 2.1 deg | 1.0 deg |
| 0.10 s | 1.4 deg | 2.9 deg | 4.3 deg | 1.9 deg |
| 0.25 s | 3.6 deg | 7.1 deg (0.8 bin) | 10.6 deg (1.2 bins) | 4.8 deg |
| 0.50 s | 7.1 deg | 14.0 deg (1.6 bins) | 20.6 deg (2.4 bins) | 9.5 deg |

A person standing still shows **zero** error, whatever the offset. So the static marks
look perfect even when the clocks are badly off. To keep a person walking at 1 m/s at
2 m within 2 deg, the clocks must agree to within 0.07 s.

**Protocol.** At the very start of a recording, the subject stands still for at least
2 s, then takes one quick sidestep, then stands still again. Do the same at the very
end. Then:

```python
import align_clocks as A
fit = A.align(frame_t, frame_x, pose_t, pose_x)   # frame_x: the network's x (or any image measure)
print(fit.summary())                               # offset, drift, and how well each event matched
poses_for_frames = A.sample_poses_at_frames(fit, frame_t, pose_t, [px, py, pz, yaw])
```

`pose_x` should be the **same quantity** as `frame_x`, i.e. where the subject is in the
image, so neither signal has a lag the other lacks. Compute it with `pose_to_label` from
the poses. `align` refuses rather than guesses: it raises if it cannot find the sync
steps, if the two streams do not show the same motion, or if the start and end offsets
disagree by more than any real clock drift. With the two events less than 60 s apart it
fits the offset only and says the drift was **not** measured.

In tests, a synthetic 5-minute run with a known offset is re-aligned to within 25 ms
everywhere (worst seen 15.7 ms). Frames really served by `mock_streamer.py` and stamped
by `cpx_grab.py` recover an injected offset to within a few ms. Real WiFi and radio
latency have **not** been measured. **Those numbers are at 10-15 fps. At the real deck's
~2 fps the rehearsal gives about +-40 ms** ("Recording a session", below).

## Dropouts and crashes: labels to throw away

* `stalled_pose_mask`: frames whose pose stamp stopped advancing (a radio or Lighthouse
  dropout, or a person blocking the follower's deck from the base stations). No label.
* `first_pose_discontinuity`: from the first tilt past 30 deg, or yaw jump faster than
  120 deg/s, onward. After a crash the estimate can reset while the camera keeps
  streaming. In the simulator logs this produced labels that looked exactly like a
  mirror.
* `sample_poses_at_frames` returns NaN across a pose gap longer than 0.1 s instead of
  interpolating through it. Count the NaNs and report them.

`check_not_mirrored(bearings, network_bins)` is the last line of defence. Run it on
every labelled session before using the labels. It raises unless the poses and the
network agree on the side for at least 90% of clearly-left **and** clearly-right frames.

## Recording a session

`record_session.py` records everything a session needs in one unattended run;
`label_session.py` turns it into labels afterwards, offline. Neither ever arms a motor
or sends a setpoint: both drones get `tools/hardware/preflight.py`'s write guards before
anything is sent.

### Pre-flight checklist (every session)

1. **Beacon (drone 05): props OFF** (pinch the hub, pull straight up). Its motors are
   never armed by these tools, but a prop on a head is not worth the risk.
2. **Beacon: AI-deck unplugged or removed.** Both AI-decks run Bitcraze's stock
   `wifi-img-streamer`, which names its access point **`WiFi streaming example`**
   (`aideck-gap8-examples/examples/other/wifi-img-streamer/wifi-img-streamer.c`, line 179;
   open, no password, deck at `192.168.4.1:5000`). Two powered decks = two identical
   networks, and macOS will join (or roam to) either one: the frames could silently
   come from the **beacon's** camera. `record_session.py` reads the beacon's
   `deck.bcAI` and **refuses** if it reports an AI-deck (`--allow-beacon-aideck`
   overrides; then `--follower-deck-mac` is the only protection). Removing it also
   helps the battery: with the AI-deck powered, the beacon's 350 mAh pack lasts about
   5-7 min (`docs/hardware/powering_the_drone.md`); without it, longer (not measured).
3. **Know the follower's deck by its MAC.** Once, with ONLY drone 09 powered and the
   laptop on its WiFi, run `--identify-deck` (below) and write the MAC down. Pass it as
   `--follower-deck-mac` on every run: the recorder refuses if the deck at
   192.168.4.1 is a different one, and logs a warning if it changes mid-session.
   (Unverified on hardware: this reads the deck's soft-AP MAC from the Mac's ARP table.)
4. **Follower (drone 09) on its stand**, feet on their tape, camera level. It may run on
   the **USB hub cable instead of its battery**: `--follower-uri usb://0`. Then only the
   beacon uses the Crazyradio, so its log rate is not shared. (Unverified: that the
   AI-deck streams normally when the drone is powered from USB alone.)
5. **Both drones passed `tape_check.py`** against the geometry of record
   (`docs/hardware/lighthouse/dorm_lighthouse_2026-09-24.yaml`; its sha256 goes into
   `meta.json`, and that is all that is checked - the drones' stored geometry is not
   read back).
6. **Brightness band.** The recorder grabs 5 frames first and refuses outside **30-60**
   (exposure is random per power-up). Power-cycle the follower and run again (on USB:
   unplug the cable). `GRID_ACCEPT_ANY=1` records anyway; a black camera (< 15) is
   always refused.
7. **The laptop goes offline.** Joining the deck's WiFi drops the internet; turn off
   auto-join for `eduroam` / `utexas-iot`, plug the laptop in, volume up. Nobody touches
   it during a run: start the command, walk to the start mark, follow the voice.
8. **Measure and write down**: the subject's height (`--height`), the beacon deck's
   height above the top of the head (`--beacon-above-head`), and the lens position on
   the follower (`--mount`, body frame: x forward, y left, z up).

### What the subject does (the spoken cues)

`record_session.py` waits for the first frame, then says: **"Stand still"** (4 s) ->
**"Step"** (one quick sidestep, ~0.4 m) -> **"Stand still"** -> **"Walk around"** ->
... -> **"Stand still"** (4 s) -> **"Step"** -> **"Stand still"** -> **"Done"**. The end
block starts 10 s before the end. Before the recording starts it says "Get to your
start mark and stand still". `CAMERA_CHECK_QUIET=1` mutes all of it.

During "Walk around", **walk side to side across the camera's view, upright, between
about 1.5 and 3.5 m**, and go clearly left and clearly right of the centre line (the
left/right check needs at least 10 confident frames on each side). At ~2 fps the clock
alignment is carried by this sideways walking, not by the single sidestep.

### Commands (zsh; paste as is)

```zsh
R=~/Downloads/drone/pytorch_ssd           # until the PR is merged: R=~/Downloads/drone/wt_lh_recorder
CF=~/Downloads/drone/cfloaderenv/bin/python
TR=~/Downloads/drone/trainenv/bin/python
MOUNT=(0.03 0 0)                           # MEASURE IT: lens in the follower's body frame, m
DECK=aa:bb:cc:dd:ee:ff                     # from --identify-deck, drone 09 alone

# 0. once per drone, only that drone powered, laptop on its WiFi
$CF $R/tools/lighthouse/record_session.py --identify-deck

# 1. a session: 90 s, follower over the radio
$CF $R/tools/lighthouse/record_session.py --seconds 90 --subject p01 --height 1.75 \
    --beacon-above-head 0.02 --mount $MOUNT --follower-deck-mac $DECK
#    ... or with the follower on the hub cable (and battery out):
$CF $R/tools/lighthouse/record_session.py --follower-uri usb://0 --seconds 90 --subject p01 \
    --height 1.75 --beacon-above-head 0.02 --mount $MOUNT --follower-deck-mac $DECK

# 2. afterwards (offline is fine): labels + report. The folder is printed at the end of step 1.
$TR $R/tools/lighthouse/label_session.py ~/drone_frames/<date>/lh_session_<HHMMSS>
```

`zsh` does not split an unquoted `$VAR` into words, so multi-number options use an
array (`MOUNT=(0.03 0 0)`, then `--mount $MOUNT`).

The session folder (`~/drone_frames/<date>/lh_session_<HHMMSS>/`, never committed):

| file | contents |
|---|---|
| `poses_follower.csv`, `poses_beacon.csv` | one row per pose packet: `t_cf_ms` (the Crazyflie's own timestamp), `t_laptop` (receive time), `x y z roll pitch yaw`, then the latest status sample (`lighthouse_status`, `lighthouse_bs*`, `kalman_varP*`, `pm_vbat`, ... whatever the TOC has) and `status_t_cf_ms` |
| `frames/` | `frame_<n>_<unix arrival time>.png` from `cpx_grab.py` |
| `meta.json` | URIs, firmware tag/protocol/revision, decks, battery start/end/min, geometry sha256, subject/height/mount, rate probe and achieved rates, missing samples, link quality, cue times, deck SSID/MAC, brightness, tool git sha, why it stopped |
| `labels.csv`, `report.md`, `label_summary.json`, `network_chip.csv` | written by `label_session.py` |

**Rate.** Before recording, both links log poses together for 3 s per rate, fastest
first (100, 50, 33, 25, 20, 10 Hz), and the fastest one delivering >= 95% on both is
used. The achieved rate, missing samples (from gaps in the Crazyflie's own timestamps)
and receive jitter go into `meta.json`. **Two links on one Crazyradio has not been
measured**: in the rehearsal both links are UDP to the simulator, which says nothing
about the radio.

**Stopping.** At the end, on Ctrl-C, when either drone's link drops, or when a drone
sends nothing for 2 s (flat battery), it stops the grabber, closes both links cleanly
and still writes everything; `meta.json` says why (`stopped_because`). Voltages are
printed every 10 s; under 3.4 V it warns.

### The static taped-mark case with the new tool (plan section 3.5)

Follower only, on its stand, nobody touching it. `--static` logs it for 30 s, averages
the pose (circular mean for yaw) and, given the subject's mark in the room frame,
prints the label exactly as `pose_to_label.py` would:

```zsh
# unyawed: camera along the taped centre line
$CF $R/tools/lighthouse/record_session.py --static --follower-uri usb://0 \
    --mark 2.0 0.5 --height 1.75 --mount $MOUNT
# then turn the follower 30 deg to its LEFT on the stand, nothing else moved, and repeat
$CF $R/tools/lighthouse/record_session.py --static --follower-uri usb://0 \
    --mark 2.0 0.5 --height 1.75 --mount $MOUNT
```

`--mark X Y` is the subject's feet in the **Lighthouse room frame** (metres; the dorm
frame is the 2026-09-24 one: origin on the blue ORIGIN tape, +x toward the door, +y
toward the SIDE mark). The subject's head is taken as `height + beacon-above-head` above
z = 0 (in the dorm frame z = 0 is ~2 cm above the tile; irrelevant to the x-bin). With
the follower at the worked example's pose (lens at the origin, 0.8 m up, facing +x,
`--mount 0 0 0`), the first run prints **-14.04 deg, x-bin 2** and the yawed run must
print a **logged yaw about 30 deg HIGHER** and **+15.96 deg, x-bin 6** (the unit test
`test_record_session.py` checks the first number through this exact code path). Anywhere else in the
room the numbers differ, but the rule does not: **turning the drone LEFT must raise the
logged yaw by ~30 and move the subject ~30 deg to the RIGHT (bearing up).** If the yaw
went down, or the bearing went left / "not in view": the yaw sign is backwards. Stop.
Both runs leave a folder with `poses_follower.csv` and `meta.json` (`static_pose`).

### Rehearsal without hardware

```zsh
bash $R/tools/lighthouse/run_pair_sim.sh                 # two CrazySim drones (Docker)
CAMERA_CHECK_QUIET=1 $CF $R/tools/lighthouse/record_session.py --mock --seconds 90 \
    --height 1.75 --mount 0 0 0
$TR $R/tools/lighthouse/label_session.py ~/drone_frames/_rehearsal/<date>/lh_session_<HHMMSS>
bash $R/tools/lighthouse/run_pair_sim.sh stop
# the same, as a test that checks the clocks against the truth (~3 min):
LH_REHEARSAL=1 $TR -m unittest $R/tools/lighthouse/test_session_rehearsal.py -v
```

`--mock` uses the SITL follower over real cflib (read-only, the probe, the writers), a
**scripted beacon** (a SITL drone that never flies never moves, so it cannot make a
sync step; the scripted one has its own clock with a known 37.25 s boot offset, +50 ppm
drift and 2-8 ms receive latency, and walks the cue schedule), and `mock_streamer.py
--timeline` serving simulator renders of that subject at **2 fps, 162 x 122** (what the
real deck sent) **0.15 s late**, each stamped with the instant it shows.
`--mock-beacon sitl` uses both SITL drones instead (plumbing only: `label_session.py`
then refuses, correctly, because nothing moved). Mock runs go under
`~/drone_frames/_rehearsal/`.

**What the rehearsal measured** (2026-10-01, 90 s runs, current code):

| quantity | result |
|---|---|
| pose log rate, two links at once (SITL follower or scripted, scripted beacon) | 100 Hz requested, 99.87-100.00 Hz achieved; 29-210 samples "missing" per run from SITL stalls / thread timing (UDP, **not a radio**) |
| beacon's Crazyflie clock -> laptop clock | +2.2 ms everywhere (= the injected minimum latency); +50 ppm drift recovered as +49.6 to +50.9 |
| frame -> pose offset vs the stamped truth, 8 runs (2 with the SITL follower) | -35, -20, -19, -16, -7, -6, +5, +16 ms: **rms 18 ms, worst 35 ms** |
| same, 40 s recorded | +46 ms: too few walking frames |
| left/right check; x-bin exact / within one bin | PASS on all 8; 88-98% / 100% |
| size bucket | 0% agreement - the rendered person is not 1.75 m; meaningless in the rehearsal |

So at the deck's ~2 fps, **expect the clock offset to be good to about +-40 ms, not the
25 ms quoted above** (that was at 10-15 fps). 40 ms is 1.1 deg for a subject crossing at
1 m/s at 2 m, inside the 70 ms budget the "Clocks" table sets for 2 deg. Two things in
the rehearsal made it worse: a short recording (keep >= 60 s; 90 s is the default) and
alignment on weak detections (`label_session.py` uses confidence >= 0.5 frames and only
falls back to >= 0.3 if that finds no sync step; an earlier 0.3-only version was 43 ms
off). The start and end events agreeing with each other is **not** an error bar: in
that run they agreed to 0 ms and were both 43 ms off.

### What only hardware can settle (none of this was tested)

* Whether two links on one Crazyradio sustain 100 Hz poses each, and what drops.
* The Lighthouse status / quality variable names in firmware 2026.08: the recorder logs
  whatever of `lighthouse.status`, `lighthouse.bs*`, `kalman.varP*` the TOC has. SITL
  has no `lighthouse` group, so the status-based drops are tested on synthetic data only.
* Real WiFi + camera latency (the rehearsal injected 0.15 s) and its jitter.
* Whether the beacon on a head keeps both base stations in view, and how often the
  subject blocks the static follower's deck.
* The deck MAC check, the SSID read (recent macOS may hide it), and the follower
  streaming on USB power alone.

## What is not known yet (only hardware can settle it)

* The real camera's crop FOV and the lens position on the real drone.
* Whether the lab's saved Lighthouse calibration has z up and y to the left. It should
  (cflib's aligner only rotates and translates). The static case above checks it.
* The yaw-rate *command* sign on the lab drone's firmware. That belongs to the follower,
  not to these labels. It is -1 in the simulator, but older firmware makes cflib flip it:
  check `cf.platform.get_protocol_version()` (> 8 means the simulator's sign should carry
  over).
* Real clock offset, latency, jitter and drift.
* Whether `target_frac = 0.5` matches where the network actually centres real people.
* The simulator shows the network reading about 1.6 deg right of the geometry near
  the centre, and slightly toward the centre off-axis. Nobody knows whether real frames
  do the same.

This rig says **where** the person was, not whether they were **detectable**. A miss
it labels is a real miss. Why it was missed is a separate question.
