# Pose-to-label, validated against simulator truth (2026-09-22)

**Question.** Before any Lighthouse data is collected (plan:
`docs/hardware/before_the_next_session.md` §3.3a; conditions: `DECISIONS.md`
2026-09-20), does `tools/lighthouse/pose_to_label.py` turn two poses into the label
the network should output, with the left/right sign right end to end?

**Answer, for the simulator: yes.** On 267 archived CrazySim flights, labels
computed from the follower's logged pose plus the subject's true position put the
subject on the same side as the network in **99.0% of 4,224 clearly-left frames and
100.0% of 1,745 clearly-right frames**. Feeding the same data through a flipped yaw
sign, a flipped bearing sign, or a y-right room frame drops that to 0-38%, and the
guard raises. **None of this has touched hardware.** What only hardware can settle
is listed at the end.

No simulator was started. Everything here is recomputed from logs already in `docs/`.

```
~/Downloads/drone/trainenv/bin/python \
    docs/eval_results/2026-09-22-pose-to-label-sim-validation/scripts/validate_on_sim.py
```
(about 50 s; writes `results.json`, `flights.csv`; its printout is `validate_on_sim.log`)

## What was compared with what

For every frame the follower processed (`follow_log.csv`, one row per frame):

| input | source | why this is the right stand-in |
|---|---|---|
| follower pose | the row's `px, py, pz, roll, pitch, yaw` - the **firmware's own state estimate**, logged through cflib | it is the same variable (`stateEstimate` / `stabilizer`) a Lighthouse-fed Crazyflie logs, so real logs use the same input slot and the same conventions |
| head beacon | the subject's **true** position from `truth.csv`, lifted by half the panel height to the top of the head | this is where a beacon riding on the head would read |
| join | truth interpolated at the frame's **arrival wall time** (`wall - (t - t_proc) - frame_age`) | both files carry the wall clock. See "Joins" for what the wrong join does |
| camera | CrazySim's `fpv_cam`: 70 x 70 deg centre crop, lens 0.03 m forward, level | from `camera_model.py` and the drone MJCF (`pos="0.03 0 0"`, `fovy="70"`) |
| "what the network said" | the row's `x_bin`, `x_soft`, `size_bucket`, `conf` | the output the follower actually flew on |

**Honest caveat on "truth".** CrazySim logs no ground truth for the *drone*, only for
subjects. So the follower pose is the firmware estimate, which in SITL has no absolute
yaw reference (Lighthouse would give one). This is why the integrity gate below exists.

### Which flights (n)

953 flight logs with a person target were found in `docs/` (duplicates across
evidence folders removed): 234,743 processed frames. Pet, furniture and empty-room
scenes are excluded from the network comparison (the empty room is used for the
field-of-view check).

* **Primary set, 267 flights**: scenes with a manifest giving the subject's height -
  `s01_control_moving` (146 flights, subject sways +-1.2 m at 3 m), `s15_static_offset`
  (79, subject 1.0 m to the right at 3.5 m), `s07_occlusion_reappear` (42, subject
  sways +-1.6 m behind an occluder). Clean and himax cameras, float and chip networks.
* **Secondary set, 644 flights**: other person scenes whose scene folders were in a
  temporary directory that no longer exists (on-axis, no-shadow, deadlock, people-plural,
  typical-person). Height is **assumed** 1.7 m; x is unaffected by height on a level
  camera, so bins are comparable, size is not.
* **Empty-room control, 42 flights**, for the in-view flag.

Per-flight numbers: `flights.csv`.

### Integrity gate: 2,761 frames removed, and why

Two things in the logs make the follower pose stop being truth, and both produce
labels that *look mirrored*:

1. **Crash then estimator reset (11 flights, 2,517 frames).** The estimate tumbles
   (roll -110 deg, yaw jumping 60 deg between samples), then snaps to yaw 0.000 while
   the camera, now on the floor, keeps streaming for the rest of the flight.
   `first_pose_discontinuity` cuts the log at the first |roll| or |pitch| > 30 deg or
   yaw step > 120 deg/s.
2. **Stalled pose (5 flights, 259 frames).** The firmware stopped; `fw_ts` froze but
   frames kept arriving (one such flight is `mirror_control_suite/.../B.moving__ships__r3a2`,
   which the scoreboard already marks INVALID). `stalled_pose_mask` drops frames whose
   pose stamp has not advanced for 0.5 s.

**Without this gate the correct convention fails the guard** (right side 89.9% of 1,946
frames). That is the most useful thing this validation found: on hardware, a Lighthouse
dropout or re-acquisition jump is the same failure, and it must drop frames, not be
interpolated across.

## Results (gated; frames the network calls visible, conf >= 0.5, and in view per the poses)

### (i) Against scoreboard.py's own truth bearing

`scoreboard.py` computes `atan2(dy, dx) - yaw` (counter-clockwise, i.e. **left-positive**).
`pose_to_label` is **left-negative**. On 224,357 frames:

* level camera, no lens offset: `pose_to_label == -scoreboard` to **2.8e-14 deg** (max).
* full model (3 cm lens offset, logged roll and pitch): median 0.05 deg, p99 0.31 deg,
  max 0.92 deg different.
* **the two agree in sign on 0.0% of frames**, which is correct. The opposite
  conventions are a trap. Anyone who compares the two without the minus sign would
  "find" a mirror.

### (ii) Against what the network output

| set | frames | flights | x-bin exact | within 1 bin | bearing err mean (net - pose) | median abs | p90 abs | size bucket exact (within 1) |
|---|---|---|---|---|---|---|---|---|
| primary | 81,368 | 267 | 0.758 | **1.000** | +1.62 deg | 1.82 | 3.83 | 0.543 (0.986) |
| s01 moving | 48,868 | 146 | 0.713 | 1.000 | +1.44 | 1.61 | 3.55 | 0.457 (0.982) |
| s15 static offset | 20,847 | 79 | 0.873 | 1.000 | +2.27 | 2.40 | 4.21 | 0.746 (0.992) |
| s07 occlusion | 11,653 | 42 | 0.741 | 1.000 | +1.18 | 1.57 | 3.92 | 0.539 (0.990) |
| primary, clean camera | 37,413 | 85 | 0.763 | 1.000 | +1.39 | 1.51 | 3.27 | 0.518 (0.982) |
| primary, himax camera | 41,759 | 178 | 0.758 | 1.000 | +1.79 | 2.15 | 4.11 | 0.558 (0.988) |
| primary, **matte floor** | 59,245 | 210 | 0.745 | 1.000 | +1.69 | 1.93 | 3.81 | **0.663 (0.998)** |
| primary, reflective floor (pre-Sep 12 bug) | 22,123 | 57 | 0.794 | 1.000 | +1.41 | 1.45 | 3.94 | 0.220 (0.954) |
| secondary (height assumed) | 79,837 | 644 | 0.918 | 1.000 | -0.59 | 1.29 | 3.71 | not meaningful |

At the follower's own 0.75 bar the primary numbers barely move (70,871 frames, bin
0.757, within-1 1.000, +1.61 deg).

Reading it:

* **Within one bin on every one of 81,368 frames** (0 frames off by two or more). An
  x-bin is 8.8 deg wide near the centre; a median error of 1.8 deg is a fifth of a bin.
* **There is a small systematic error, and it is not a mirror.** Near the centre
  (|bearing| < 8 deg, 75,399 frames) the network reads the subject **+1.6 deg to the right**
  of the geometric target. Off-centre it reads the subject **closer to the centre** than
  the geometry: +2.7 deg on clearly-left frames (4,224), -1.6 deg on clearly-right frames
  (1,745). So the error is an offset plus a mild pull toward the centre. A mirror would
  instead flip the sign and put errors at twice the bearing. The cause is **not
  established**. Candidates: the COCO cutout's figure not centred in its rectangular card
  (offset), and the network under-reading off-centre positions, or a true crop FOV a little
  wider than 70 deg (pull toward the centre). Look for the same pattern in real-hardware
  labels; do not assume it away.
* **Size buckets need the matte floor.** On flights the Sep 12 floor-mirror bug affected
  (identified by evidence folder name: `mirror_control_suite`, `stability/.../mirror_suite`,
  `sim_results/2026-09-11-simv2`), the network reads 0.82 of a bucket larger than the
  geometry (the reflection made subjects look 1.5-2x taller). On matte-floor flights: 66%
  exact, 99.8% within one, +0.17 bucket bias. Size labels have not been checked beyond this.

### Joins: the clock pitfall, reproduced

| join | primary: bin exact | within 1 | median abs bearing err | p90 |
|---|---|---|---|---|
| truth at the frame's arrival wall time | 0.758 | 1.000 | 1.82 deg | 3.83 |
| truth at the row's wall time (scoreboard.py's join) | 0.758 | 1.000 | 1.81 | 3.82 |
| **follower `t` against truth `sim_t` (the Sep 13 bug)** | 0.411 | 0.660 | 6.58 | 26.7 |
| same wrong join, s01 moving only | 0.139 | 0.466 | 14.2 | 29.1 |

The two wall-clock joins agree to 0.01 deg: at these speeds the 20-60 ms frame age does
not matter. The wrong clock is a 26-degree p90 error on a moving subject, which is the
same failure as the Sep 13 `conf_vs_range.py` bug. Fewer frames are scored under it
because `t` falls outside `sim_t`'s range for part of each flight.

## The yaw-sign chain, settled for the simulator

There are **two different yaw signs** in this project, and they are easy to confuse.

**1. The label chain** (poses -> label). Does `stateEstimate.yaw` mean counter-clockwise?

* Bitcraze's coordinate-system page: body x forward, y left, z up. A positive yaw
  turns the nose left. `kalman_core.c` computes yaw as the ordinary right-hand-rule
  heading and logs it unchanged. It **negates pitch** (`.pitch = -pitch*RAD_TO_DEG`), so
  a positive logged pitch means nose up. `pose_to_label` undoes that, and a test pins it.
* Data. Using logged yaw as counter-clockwise gives 99.0% and 100.0% side agreement.
  Negating it gives 37.9% and 28.9% over all frames. On the frames where the drone had
  actually turned at least 5 deg, it gives **24.3% and 20.0%, against 98.1% and 100.0%**
  (n = 2,201 left and 255 right). Before the drone turns (|yaw| < 1 deg; 1,564 left and
  1,278 right, all 100% agreement) yaw cannot matter, so those frames test the bearing
  sign alone.
* **Caveat, and it matters.** The yaw sign is only tested on flights where the drone
  actually turned. In `confuser__B.moving__ships__r4a1` the confuser never followed,
  yaw stayed near 0, and **a negated yaw passes that flight 100%/100%**. A real-hardware
  check must include a yawed follower. The static case in `tools/lighthouse/README.md`
  says how.

**2. The control chain** (network x -> yaw-rate command -> drone turns). This is what
the memory note "yaw sign -1 in SITL" is about. On 24,528 tracking frames with a
non-zero command, the logged yaw moved the way the command's sign says over the next
0.5 s in **99.86%** of them. A positive rate means yaw goes up, i.e. counter-clockwise.
Subjects left of the drone (per truth) got bin < 4 in 98.5% of 2,854 frames, a positive
command in 100% of 2,812, and a left turn in 99.9% of 2,849. Subjects on the right got
100%, 100% and 100% of 550. So in SITL, `--yaw-sign -1` turns the drone toward the person.

**End to end, in the simulator:** a subject physically to the drone's left (from truth)
gets a pose-derived label in bins 0-3, and the network puts it in bins 0-3. The follower
then commands a positive yaw rate, and the firmware turns the drone left. Every link
agrees in at least 98.5% of frames.

The cflib installed here (0.1.33) defines `start_turn_left` as `+rate` and only negates
yaw rate for legacy firmware (`protocol_version <= 8`, `TYPE_HOVER_LEGACY`). The comment
above `--yaw-sign` in `follow_person.py` says cflib names `+rate` "turn right". That does
not match this cflib version. The code works; the comment is probably from an older cflib.
Not changed here.

## The mirror test that must fail loudly

`check_not_mirrored` raises `MirroredLabelsError` unless both sides have at least 10
frames and each agrees at least 90%. A data set where agreement is 10% or less on both
sides is named `LABELS ARE MIRRORED`.

| convention fed in | left agree | right agree | guard |
|---|---|---|---|
| correct | 0.990 (4,224) | 1.000 (1,745) | PASS |
| yaw read as clockwise-positive | 0.379 | 0.289 | raises |
| room frame with y pointing right, yaw unchanged | 0.132 | 0.273 | raises |
| bearing sign flipped (left-positive into a right-positive x) | **0.000** | **0.000** | raises, "LABELS ARE MIRRORED" |

Over all person scenes (secondary included): correct 0.994 (6,918) / 1.000 (25,261);
flipped bearing 0.000 / 0.000.

The same checks run as unit tests on one archived flight
(`2026-09-13-champion-threshold/runs/t080__D.occlusion__ships__r4a1`, champion chip network,
himax camera), in `tools/lighthouse/test_pose_to_label.py`. Mutating the module's signs
on a copy makes the suite fail: image-x sign 8 failures, bearing sign 10, yaw sign 8,
pitch sign 1.

## In-view flag

* Empty-room control: its person stands behind the drone. 0 of 7,625 frames are flagged
  in view (min |bearing| 180 deg). The network was at or above 0.5 on 2,351 of them;
  those are false alarms, not misses, and the flag keeps them from being scored as misses.
* Person scenes: 1,684 of 224,357 frames flagged out of view. The network was at or
  above 0.5 on none of them.

## What is verified vs not

**Verified here, in simulation only:**
* the geometry (room -> body -> camera -> image x -> bin), against an independent scorer (i)
  and the rendered images the network saw (ii);
* the label-chain yaw and bearing signs, on flights where the drone turned;
* the control-chain yaw sign in SITL with cflib 0.1.33;
* that the guard catches three distinct convention errors, and that without the
  integrity gate a crash or stalled pose looks like a mirror.

**Not verified, and only hardware can settle it:**
* **The real AI-deck crop FOV.** The sim uses 70 deg. The datasheet figure of
  170.7 px/rad gives about 71 deg. Nobody has measured our unit
  (`tools/real_frames/measure_camera.py`; MinHyuk question 13).
* **The camera mount on the real drone**: the lens offset from the Lighthouse deck's
  reported point, and any tilt.
* **Whether the lab's Lighthouse frame is right-handed with z up.** It should be:
  cflib's aligner is a rotation plus translation, and it flips the solution so the base
  stations sit above the floor. But whatever calibration file the lab has must be
  checked with the static case, not trusted.
* **The control-chain yaw sign on the lab drone's firmware.** If the firmware is old
  enough for cflib to use `TYPE_HOVER_LEGACY`, cflib negates the yaw rate and the
  follower's -1 becomes wrong. Check `cf.platform.get_protocol_version()` at connect
  (it must be > 8 for SITL's sign to carry over), then do a hand-held yaw test.
* **The head-to-torso offset.** `target_frac = 0.5` (the COCO box centre of a standing
  person) is a geometric argument, not a measurement. On a level camera it does not
  affect x at all. It matters through roll and pitch, and through lean (see the tools README).
* **Real clock offset, latency and jitter** of WiFi frames against radio poses
  (`align_clocks.py` is tested on synthetic and mock-streamer data only).
* **Size labels on real people.** The simulator's subject is a flat card, and the
  matte-floor agreement (66% exact) is the only size evidence.
* **The +1.6 deg network bias.** Its cause is not established.

## Files

* `scripts/validate_on_sim.py`: the whole analysis.
* `results.json`: every number above. `flights.csv`: per flight. `validate_on_sim.log`: printout.
* `code_hashes.txt`: sha256 of the code that produced them.
