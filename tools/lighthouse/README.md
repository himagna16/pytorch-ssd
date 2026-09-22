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
| `test_pose_to_label.py`, `test_align_clocks.py` | the tests; run them before trusting anything |

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
latency have **not** been measured.

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
