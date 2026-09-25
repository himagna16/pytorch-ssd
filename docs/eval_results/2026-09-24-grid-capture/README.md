# Grid capture, run 1: first real-person detection grid (partial), 2026-09-24 18:31

`tools/real_frames/grid_capture.sh`, run by Sai alone with spoken cues, in his dorm.
Drone 1 (...09) sat on a chair at the window end with the lens about 0.8 m up, facing the
door. One subject (Sai), room lights, chip arm (`model_id_dory.onnx` d90555c8,
eps 2.0098e-4, enter 5467 / lost -998 / confirm 3). The frames stay on Sai's laptop
(`~/drone_frames/2026-09-24/grid_capture_183109/`); only the numbers are here.

**Partial:** the empty clip and 5 of the 9 positions were captured. Clip 6 (2.13 m RIGHT)
received 0 frames after about 5 min of streaming. The connection opened but no frames
came, which matches the AI-deck browning out on a flat battery (it goes before the
mainboard). Clips 6-9, including the whole 1.52 m row, are still to do.

| position | frames | median conf | frames >= 0.75 | follower locked | x-bins seen (expected) |
|---|---|---|---|---|---|
| empty room | 26 | 0.54 (max 0.65) | 0 | **0 / 26** | 7 x26 (-) |
| 2.44 m LEFT (-14.0 deg) | 17 | **0.88** | most | **88%** | 1 x9, 2 x7, 7 x1 (2) |
| 2.44 m CENTRE (0) | 17 | 0.52 | few | **0%** | 7 x16, 4 x1 (4) |
| 2.44 m RIGHT (+14.0 deg) | 17 | **0.87** | most | **88%** | 4 x9, 6 x3, 7 x5 (6) |
| 2.13 m LEFT (-15.9 deg) | 17 | **0.77** | most | **71%** | 2 x13, 7 x3, 1 x1 (2) |
| 2.13 m CENTRE (0) | 17 | 0.66 | some | **0%** | 7 x17 (4) |

(Per-frame values: `scores.csv`; the scorer's own table: `scorer_output.txt`.)

## The finding: background contrast, not position

Off to the sides, Sai is seen strongly and the follower locks on 71-88% of frames. Dead
centre, he is never locked, and the model answers bin 7 (the room's right-side
background pull, which also shows in the empty clip). The frames show why:

- **Centre** puts Sai directly in front of the **dark door**. His dark trousers and hair
  merge into it, and only the white shirt stands out, so there is no person-shaped
  outline.
- **Left and right** put him in front of the **bright wardrobe panels**. His whole
  silhouette (head, torso, legs) contrasts with the background.

So the champion's detection of a real person depends strongly on **subject/background
contrast**. This fits the Sep 22 run 2 frames, where the dim room also gave weak
detections.

**Confound, stated plainly:** in this room, position and background change together
(centre = door). One subject, one outfit, one session, 17 frames per cell. **The clean
test** is to stand at CENTRE with a light sheet or towel hung over the door (same
position, only the background changes), and ideally to repeat LEFT/RIGHT in dark
clothing.

## Other notes

- **The mirror check** printed FAIL ("sides disagree"). That is entirely the two CENTRE
  cells reading bin 7. The off-centre cells are on the correct side: LEFT bins 1-2,
  RIGHT bins 4-7.
- **Empty room:** 0 false locks. Confidence peaked at 0.65, lower than Sep 22's 0.71.
- **The aim is good this time.** The door sits centred in the frame (the Sep 22 run 2
  aim was a few degrees right).

---

## Run 1b (resumed at 18:46, `GRID_START=6`): 8 of 9 positions, BUT A LIGHTING CHANGE

The resume worked: clips 6-8 were added to the same folder and everything was re-scored.
Clip 9 (1.52 m RIGHT) got 0 frames, the same flat-battery signature. The script now
reports this, scores what it has, and prints the resume command, as designed.

**The frames are not one condition.** Mean frame brightness per clip (0-255):

| time | clips | mean brightness |
|---|---|---|
| 18:31-18:34 | empty; 2.44 L/C/R; 2.13 L/C | **38-42 (dim)** |
| 18:47 | 2.13 R; 1.52 L/C | **93-95 (bright)** |

Something between the two runs, such as a light switched on or auto-exposure settling
differently on a fresh battery, raised the brightness about 2.3x. The two groups must
not be pooled.

| position | condition | median conf | locked | x-bin (expected) |
|---|---|---|---|---|
| empty room | dim | 0.56 | **0 / 26** | 7 (-) |
| 2.44 m LEFT | dim | 0.90 | 15 / 17 | 1 (2) |
| 2.44 m CENTRE | dim | 0.51 | **0 / 17** | 7 (4) |
| 2.44 m RIGHT | dim | 0.87 | 15 / 17 | 4 (6) |
| 2.13 m LEFT | dim | 0.81 | 12 / 17 | 2 (2) |
| 2.13 m CENTRE | dim | 0.66 | **0 / 17** | 7 (4) |
| 2.13 m RIGHT | bright | 0.54 | **0 / 17** | 6 (6) |
| 1.52 m LEFT | bright | 0.78 | 14 / 17 | 1 (1) |
| 1.52 m CENTRE | bright | **0.93** | **14 / 17** | 3 (4) |
| 1.52 m RIGHT | - | not captured (battery) | | |

**What survives:**
- **Within the dim run:** off-centre is strongly detected and locked; dead centre, in
  front of the dark door, is never locked. That comparison is within one condition.
- **In the bright run, centre IS detected** at 1.52 m (0.93, locked 14/17). With the door
  lit, Sai's dark trousers and hair contrast against it. This is consistent with the
  contrast explanation, but distance (1.52 vs 2.1-2.4 m) and lighting changed at the
  same time, so it does not prove it.
- **2.13 m RIGHT in the bright run is weak** (0.54, never locked) even though its x-bin is
  right. Simple contrast does not obviously explain this. Sai stands between the lit
  door and the dark loft and ladder region. Unexplained, n = 17.
- **The empty room gave 0 false locks** (peak 0.65, dim run).

**Next:** a complete grid in **one sitting at one lighting level** (room lights on, fresh
battery), then the same grid with a light sheet over the door. Record which lights are
on.

---

## Night runs, 19:42-20:48: one clean dim grid, and two new findings

Four attempts. Per-run numbers are in the subfolders, which hold scores, logs and the
scorer JSON. The frames stay local.

| run | frames | brightness | what happened |
|---|---|---|---|
| `grid_capture_194556` (19:45) | 44 | **89-95** | empty + 2.44 L + 1 frame of 2.44 C, then the link dropped. **2.44 L median 0.29, 0 locked** in this bright mode |
| `grid_capture_204144` (20:41) | 21 | **7 (near-black)** | empty only, then dropped. **Near-black empty frames scored 0.83 and the follower LOCKED (19/21)** |
| 20:43 | 0 | - | no data |
| **`grid_capture_204502` (20:45)** | 145 | **38-41, consistent** | empty + **7 of 9** positions; clip 8 (1.52 C) got 0 frames (battery) |

### The clean dim grid (`grid_capture_204502`) vs the 18:31 dim run (same brightness level)

| position | 20:45 median / locked | 18:31 median / locked |
|---|---|---|
| 2.44 m LEFT | 0.86 / 15 of 17 | 0.90 / 15 |
| 2.44 m CENTRE | 0.54 / **0** | 0.51 / **0** |
| 2.44 m RIGHT | 0.78 / 3 | 0.87 / 15 |
| 2.13 m LEFT | 0.87 / 15 | 0.81 / 12 |
| 2.13 m CENTRE | 0.72 / **1** | 0.66 / **0** |
| 2.13 m RIGHT | 0.77 / 8 | (not in the dim run) |
| 1.52 m LEFT | 0.83 / 15 | (not in the dim run) |
| empty room | 0 locks, peak 0.79 (3 frames >= 0.75, never 3 in a row) | 0 locks, peak 0.65 |

- **It replicates.** In two separate dim runs, the left side is strongly detected and
  locked, and **dead centre at 2.1-2.4 m (in front of the dark door) is missed both
  times**. The right side is detected but less reliably. The mirror check read
  `WEAK: both sides mostly correct (84% / 94%), NOT mirrored`.
- The empty room still never locks. But in this run its peak (0.79) crossed the 0.75
  enter bar on single frames, so the margin is thin.

### Finding 1 (safety): near-black frames make the model see a person

In run `204144` the camera delivered frames at mean brightness **6.6**. *(At first this was put
down to a dying battery. That is WITHDRAWN at 22:05: run `215739` below produced near-black
frames for a complete run on a fully charged battery.)* The chip network scored the empty room at **median 0.83** and the
follower **locked on 19 of 21 frames**. A drone flying that frame stream would chase
nothing. **Recommended guard:** the firmware or follower should refuse to steer on
frames whose mean brightness is implausibly low, and count them as "no target".
`grid_capture.sh` now flags near-black runs. This is n = 1 clip and needs a deliberate
test (lens covered, full battery).

### Finding 2: the camera starts in one of two exposure modes, and it matters

Same room and same room lights, but the runs came out at mean **~40** (18:31, 20:45) or
**~90-95** (18:46 resumed, 19:45). In the bright mode, the one comparable cell (2.44 m
LEFT) dropped from **0.86-0.90 to 0.29**. Possible causes: **which drone** was used
(each has its own camera), or the auto-exposure state at power-up. **Test:**
`tools/real_frames/exposure_check.sh` records the brightness per drone and power-up in
`~/drone_frames/exposure_log.txt`. Run it on each drone over a few power cycles.
`grid_capture.sh` now takes `GRID_DRONE=09|05` to record the drone.

### Script changes

- Clips are now 6 s with a 6 s countdown (was 8 + 8), so a full grid fits one battery.
- A drone label, and a near-black frame warning.

---

## 21:57 run (`grid_capture_215739`, drone 09, full charge): all 9 clips recorded, every frame BLACK

The first complete grid in one sitting, on one battery. All 10 clips were recorded
(143 frames), but **every frame is near-black: mean 4.1, per-frame 2.4-10.3, max pixel
44**. Contrast-stretched, a frame shows only sensor noise and horizontal readout
banding. There is no scene in it. The most any frame differs from the first frame is
7.2 DN, so a person walking between 9 positions left no trace. **The camera captured
nothing for the whole run.**

The chip network still output **~0.84 and x-bin 6 on every frame** (the constant
answer), and the follower **locked on 24 of 26 empty-room frames** and 11 of 13 frames
at every position. The script's new near-black warning fired as intended.

### What this changes

1. **The safety finding is now solid.** Across two runs (`204144` and `215739`,
   **169 near-black frames**), the champion reads sensor noise as a confident person
   (0.83-0.84) and the follower locks on. A drone must refuse to steer on frames it
   cannot see. **Firmware guard, strongly recommended:** treat frames with mean
   brightness below a floor (e.g. 15 DN) as "no target".
2. **The "dying battery" explanation is withdrawn.** This run was on a full battery
   and completed.
3. **The cause is most likely camera exposure set once at power-up.** The stock
   `wifi-img-streamer` (aideck-gap8-examples, `open_pi_camera_himax`) calls
   `PI_CAMERA_CMD_AEG_INIT` **once at startup**, then starts and stops the sensor for
   every frame. Tonight, under the same room lights, power-ups came out at mean
   brightness **4, 7, 40 and 90**. **Hypothesis (unverified):** the exposure is fixed
   by whatever the camera sees during the first seconds after power-up (a hand, the
   ceiling light, the room) and never corrects itself.
4. **Test:** leave the drone untouched on the chair, facing the room, and only
   unplug and replug the battery 4-5 times, running `exposure_check.sh` each time. If
   the level still varies, it is startup randomness. If it is stable, what the camera
   sees at power-up is the driver. Either way, the durable fix is on the firmware
   side: a fixed manual exposure, or continuous auto-exposure.

### Valid data so far (the only single-condition dim grid is `204502`)

Only `204502` (7 of 9, brightness 38-41) and the dim half of `183109` are usable,
and they agree (see the night section). No valid complete 9-position grid exists yet.

---

## 22:12-22:16 power-cycle test: exposure is effectively RANDOM per power-up (`exposure_log_powercycle.txt`)

Drone 09 sat on the chair facing the room, at night with room lights only. Only the
battery was unplugged and replugged, 5 times in 4 minutes, with an 8-frame
`exposure_check.sh` after each power-up.

| power-up | 1 | 2 | 3 | 4 | 5 |
|---|---|---|---|---|---|
| mean brightness | **146** | 76 | **42** | 78 | 74 |

With the scene and light held fixed, the power-up alone moves brightness across a
**3.5x range**. Including tonight's grid runs, the range is **4 to 146**. The "two
modes (~40 / ~90)" framing above was too simple: **it is a continuum set at
power-up.** This confirms the mechanism read from the code: the stock streamer
runs `PI_CAMERA_CMD_AEG_INIT` once at start-up and starts and stops the sensor for
every frame.

**Our flight app has the same problem.** `crazyflie_ssd/src/camera_if.c` (lines 28-44,
83-88) copies the Bitcraze pattern exactly: `AEG_INIT` once, then start/stop per
frame. So a real flight would inherit a random exposure per power-up, including the
near-black case where the champion locks on noise. **For the firmware lane:** a fixed
manual exposure, or re-running or continuously updating AE, plus the brightness-floor
guard.

**For data collection now:** `grid_capture.sh` only records when the pre-flight
brightness is inside 30-60 (the band of the one clean grid). Otherwise it tells the
user to power-cycle and records nothing. Override with `GRID_ACCEPT_ANY=1`. Each check
is logged. `exposure_check.sh` now reports against the same band.
