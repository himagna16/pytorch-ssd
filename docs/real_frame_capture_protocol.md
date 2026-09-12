# Real AI-deck frame capture: session protocol

**Goal.** Record the first real camera frames from our AI-deck while the drone
sits still, then check whether the model we fly in the simulator also works on
real images. Nothing flies today.

> **Read `docs/hardware/lab_session_runbook.md` first.** This document is the
> *method* — marks, labels, consent, what a clip must contain. The runbook is the
> *plan*: who brings what, what order the session runs in, what to do when
> something fails, and how long each step gets. Where the two differ on timing or
> packing, **the runbook wins**; it is the one that was checked against the clock.
> The other two siblings are `docs/hardware/flash_runbook.md` (building and
> flashing the GAP8 app — which **destroys the camera streamer this document
> depends on**, so it happens last) and
> `docs/hardware/camera_measurement_protocol.md` (measuring the sensor, not the
> model).
>
> **Every command below is absolute as of 2026-09-12.** The earlier version wrote
> them as `python pytorch_ssd/tools/...`, which fails two different ways on the
> capture Mac: there is no `python` on PATH at all (`command not found: python` —
> only `python3` exists), and the relative path only resolves if your shell
> happens to be sitting in `~/Downloads/drone`. From `~` it gives
> `can't open file '/Users/saimaruvada/pytorch_ssd/tools/crazysim_macos/cpx_grab.py'`.
> Both were reproduced by running them.

## 1. Safety and consent (read first)

- **Props off, drone on a tripod.** Remove all four propellers before powering
  on. The motors stay off. No flight scripts (`follow_person.py`, `flight_check.py`) are run.
- **Only teammates who agree to be recorded.** Ask each person out loud before
  their clips and write their ID (p01, p02, ...) on the log sheet, never their
  name in a filename. Anyone can ask later for their clips to be deleted.
  Wait for bystanders to leave the frame, or stop recording.
- **Frames never go into git** (not this repo, not a fork). See section 5.

## 2. Setup

- Mount the drone so the **camera lens is 0.8 m above the floor** (our flying
  height). Measure to the lens, not the tripod head. The camera should point
  level, straight down a taped **center line** on the floor.
- Tape marks on the floor. **Distance** is measured from the point under the
  lens. **Bearing** is the angle from the center line, as seen from
  behind the drone: **negative = the drone's LEFT**, positive = its right.

| Bearing | at 1.5 m: forward / sideways | at 2.5 m | at 3.5 m |
|---|---|---|---|
| 0° | 1.50 / 0 | 2.50 / 0 | 3.50 / 0 |
| ±10° | 1.48 / 0.26 | 2.46 / 0.43 | 3.45 / 0.61 |
| ±25° | 1.36 / 0.63 | 2.27 / 1.06 | 3.17 / 1.48 |

  (metres; sideways to the left for negative bearings). These five bearings
  land in the middle of the model's x-bins 1, 3, 4, 5, 7, so a few degrees of
  setup error does not change the right answer. The person stands with their
  **feet centered on the mark**, facing the drone.
- Laptop: join the AI-deck's WiFi network (the AI-deck must be flashed with
  Bitcraze's `wifi-img-streamer` in access-point mode), then use
  `~/Downloads/drone/trainenv/bin/python` for every command below.
- **Raw, not JPEG.** Set the streamer to send **raw frames (format 0)**. The
  GAP8 model runs on raw pixels, and JPEG adds compression artefacts it never
  sees, so JPEG clips are not valid for scoring. Raw is the streamer's
  default: in Bitcraze's `aideck-gap8-examples`, file
  `examples/other/wifi-img-streamer/wifi-img-streamer.c`, the line
  `StreamerMode_t streamerMode = RAW_ENCODING;` selects it. If someone changed
  it to `JPEG_ENCODING`, change it back and reflash. The streamer sends
  single-channel 324x244 frames and captures one each time it sends.
  `cpx_grab.py` warns when it receives JPEG.

## 3. Bench checks (before any real recording)

1. **Stream check.** Run:

   ```bash
   ~/Downloads/drone/trainenv/bin/python \
     ~/Downloads/drone/pytorch_ssd/tools/crazysim_macos/cpx_grab.py \
     --n 5 --every 1 --out ~/drone_frames/<date>/check
   ```

   It should print `connected to tcp://192.168.4.1:5000` and save 5 images.
   Each `saved` line must show **`fmt=0`** (raw, saved as `.png`). `fmt=1` means
   JPEG (`.jpg`): switch the streamer to raw before recording (section 2).
   Open one: people should be upright and sharp.
   A fine checkerboard texture means a color (Bayer) camera: add `--bayer` to
   **every** `cpx_grab.py` command from here on. (`--bayer` averages each 2x2
   cell, so it gives the same gray whatever the color pattern is.) Write
   "color camera" on the log sheet and tell the firmware team: the chip app's
   preprocessing also reads the frame as plain gray.

   If `cpx_grab.py` cannot connect, test the deck with Bitcraze's own viewer:

   ```bash
   ~/Downloads/drone/trainenv/bin/python \
     ~/Downloads/drone/aideck-gap8-examples/examples/other/wifi-img-streamer/opencv-viewer.py \
     -n 192.168.4.1 -p 5000
   ```

   There is a **second, different** `opencv-viewer.py` under
   `examples/image_processing/FaceDetection/` — not that one. This viewer
   converts raw frames to color, so use it only to see that the stream works;
   do not score its `--save` images. **It needs `cv2`, which is not installed in
   any venv on the capture Mac** — see `docs/hardware/lab_session_runbook.md`
   section 2.1, and install it before the lab. Its `import cv2` is at line 70,
   *after* the socket connect at line 58, so a missing cv2 will look like a deck
   fault: it connects, prints `Socket connected`, then dies on the import.
2. **Mirror check (must pass).** Record two 10 s clips into their own folder,
   with a teammate at **2.5 m, bearing −25° (drone's LEFT)** and then at
   **2.5 m, +25° (drone's RIGHT)**:

   ```bash
   ~/Downloads/drone/trainenv/bin/python \
     ~/Downloads/drone/pytorch_ssd/tools/crazysim_macos/cpx_grab.py --seconds 10 --every 1 \
     --dist 2.5 --bearing -25 --vis 1 --subject p01 --light room --out ~/drone_frames/<date>/mirror
   ~/Downloads/drone/trainenv/bin/python \
     ~/Downloads/drone/pytorch_ssd/tools/crazysim_macos/cpx_grab.py --seconds 10 --every 1 \
     --dist 2.5 --bearing 25 --vis 1 --subject p01 --light room --out ~/drone_frames/<date>/mirror
   ```

   Then score exactly that folder (section 6):

   ```bash
   ~/Downloads/drone/trainenv/bin/python \
     ~/Downloads/drone/pytorch_ssd/tools/real_frames/score_real_frames.py \
     ~/drone_frames/<date>/mirror
   ```

   The MIRROR
   CHECK line must say **PASS** with both LEFT and RIGHT counted. PASS means the
   model's argmax x-bin is **below 4** for the left clip and **above 4** for the
   right one (bins run 0 = far left to 8 = far right). **Anything other than
   PASS means stop and report:** MIRRORED (the image is flipped left-right, so every
   steering command would turn the wrong way), FAIL (inconsistent bins: check
   the marks and labels), or NO DATA (the model detected nobody in the frames). Write
   down the full MIRROR CHECK line and tell the team before anyone flies.
3. **Field-of-view check (recommended).** At 2.5 m, slide a bottle sideways
   until it just leaves the image on each side and measure the sideways distance to each edge
   (`s_left`, `s_right`). Full horizontal FOV = 2·atan(average s / 2.5).
   Pass it to the scorer as `--full-hfov <deg>`. Otherwise the scorer assumes the
   model's square crop spans 70°, the simulator value.

   > **There are two FOV methods in these documents, and they are not rivals.**
   > This bottle method takes about two minutes, needs no targets, and is good to
   > a few degrees — enough to stop the scorer using the simulator's 70°.
   > `docs/hardware/camera_measurement_protocol.md` section 5.2 measures the same
   > thing properly, from two tape marks 1.000 m apart shot at two tripod
   > distances, and subtracts to cancel the unknown entrance-pupil offset; it is
   > good to about 2% and also returns the pupil offset. It costs roughly ten
   > minutes and is a **Tier 2** item, which the runbook's time budget does not
   > fit into the first session. **Do the bottle today. Do 5.2 when there is a
   > session with time for it, and re-score the frames afterwards** — that is one
   > of the things capturing frames buys you.
4. **Record the yaw-sign chain** on the log sheet, one line per link.
   Check each link, or mark it "not checked":
   - camera: person on LEFT → x-bin < 4 → x < 0 (mirror check above)
   - follower: `yaw = yaw_sign · k_yaw · x`, `yaw_sign = −1` (so a person on
     the left gives a positive yaw command)
   - cflib version (`pip show cflib`; ours 0.1.33): MotionCommander passes
     the rate through unchanged, but `commander.py` **negates it for legacy
     firmware** (you'll see a "legacy" warning).
   - firmware version (cfclient → Connect → the version shows in the console)
   - firmware: in CrazySim a positive yaw-rate command turns LEFT
     (counter-clockwise from above). To check the real yaw direction, rotate
     the drone left by hand on the tripod and write down whether `stabilizer.yaw` increases in cfclient's plotter.
   Whoever runs the first real flight must re-check the whole chain.

## 4. What to record

Each clip is **30 s, drone still, subject still**:
`--seconds 30 --every 1`. Record in priority order, and stop when you run out of time.

| Priority | Subject (`--subject`) | Positions | Label |
|---|---|---|---|
| 1 | teammate `p01` | 3 distances × 5 bearings | `--vis 1` |
| 1 | empty room `empty` (point the drone at 3 different walls/corners, `take1..3`) | none | `--vis 0` |
| 1 | stuffed animal or pet `plush` / `pet` at 2.5 m, 0° | none | `--vis 0` (must NOT be tracked) |
| 1 | life-size poster of a person `poster` | 2.5 m at −25°, 0°, +25° | `--vis 1` |
| 2 | same as priority 1, in the other two lights | | |
| 3 | more teammates `p02`, `p03` | 3 distances × 0°, ±25° | `--vis 1` |

**Lighting** (`--light`): `room` (normal lights), `dim` (half the lights off,
blinds closed), `window` (bright window or lamp behind the subject). Priority 1
takes about 25 min in one light, so plan about 1.5 h for everything.

**Naming** is automatic. The labels you type become the filename, e.g.
`d2.5_b-25_vis1_subj-p01_light-room_take1_f00012_t1757530000.123.png`.
Use `--take 2` to redo a clip, and delete the bad take. `cpx_grab.py` refuses
to record a take that already exists in the folder, and tells you the next free
number. Always pass `--out ~/drone_frames/<date>` (the default for a real
AI-deck is `~/drone_frames/<today>`). Example:

```bash
~/Downloads/drone/trainenv/bin/python \
  ~/Downloads/drone/pytorch_ssd/tools/crazysim_macos/cpx_grab.py --seconds 30 --every 1 \
  --dist 2.5 --bearing -25 --vis 1 --subject p01 --light room --out ~/drone_frames/2026-09-12
```

If you would rather not retype that path fifteen times, paste the four-line
`grab` helper from `lab_session_runbook.md` section 4.0 into your terminal once.
Do **not** shorten it to `G="$P .../cpx_grab.py"` — a two-word command in a
variable works in bash and silently fails in zsh, which is this Mac's shell.

Each clip also writes a small `..._clip.json` (frame rate, dropped frames). On
the log sheet note the clip label, time, and anything odd (someone walked
through, the drone got bumped).

## 5. Where the frames go (NOT git)

Save to `~/drone_frames/<date>/` on the capture laptop (outside the repo).
After the session, copy the folder to the team's restricted shared drive
(members only) and post the path in the team chat. Never `git add` frames,
never upload them to a public site or dataset, and delete a teammate's clips if they ask.
One 30 s clip is roughly **390 frames** (the WiFi stream runs at about 13 fps) at
about 50 KB each — call it **20 MB a clip**, so the whole priority-1 set in one
light is under half a gigabyte. The 50 KB figure is an estimate; **nobody has
measured a real frame yet.** `lab_session_runbook.md` asks for 5 GB free, which
is deliberate slack.

## 6. Scoring

```bash
~/Downloads/drone/trainenv/bin/python \
  ~/Downloads/drone/pytorch_ssd/tools/real_frames/score_real_frames.py \
  ~/drone_frames/2026-09-12 [--full-hfov 86] [--ckpt other.pth]
```

(The scorer has **no `--bayer`** — checked, its `--help` does not mention it.
Bayer conversion happens at capture time in `cpx_grab.py`, so colour-camera clips
are already gray by the time they reach the scorer.)

It runs the same model and preprocessing as the simulator follower. It prints one row per
clip, then summaries by distance, bearing, light and subject, and writes
`scores.csv` (every frame) and `scores.json` into the folder. What to look at:

- **MIRROR CHECK** must be PASS. MIRRORED, FAIL or NO DATA means stop and report.
- **EMPTY / NO-PERSON**: *confirmed (false) tracks* must be **0**. Any track
  confirmed on an empty room or the stuffed animal would make the drone move.
- **vis acc** (person seen when a person is there): the simulator gets 100%.
- **bin acc / ±1**: does the x-bin match the bearing? ±1 bin is about ±8°.
  **bearing err** is the average left/right bias in degrees (sim: about ±2°).
- **size**: shown as the most common bucket vs the expected one, from `--person-height`
  (default 1.7 m). It is rough: 2.5 m sits right on a bucket edge, so read the ±1 column.

Synthetic check (Sep 10, **680** rendered sim frames): mirror PASS, 0 false
tracks, bin accuracy 96% (100% within ±1). A left-right flipped copy of the same frames is
correctly reported as MIRRORED.

*(This line said "660 rendered sim frames" until 2026-09-12, when it was changed to
680. **The 680 is second-hand and UNVERIFIED — nobody re-counted the frames.** The
change was applied on a reported correction, not on a recount. No artifact on disk
supports either number: grepping `EXPERIMENTS.md`, `DECISIONS.md`, `docs/progress/`,
`docs/sim_results/` and `docs/eval_results/` for the Sep 10 synthetic check returns
nothing, and this line is the only place the count appears. Re-deriving it needs a
simulator run. Treat the exact count as unconfirmed; the rest of the line — PASS,
0 false tracks, 96% / 100% — is unchanged and equally unre-verified this round.)*
