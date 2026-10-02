# Real-frame evaluation v1: splits, the clip, one metric, one guard

> **Status: PROPOSED. Needs Sai's sign-off.** Nothing in this file is a team decision
> until Sai signs it off and it gets a line in `DECISIONS.md`. The tools it describes
> (`tools/real_frames/index_frames.py`, `tools/real_frames/real_scoreboard.py`) work
> today. The baseline they produced is labelled **dev**, not test.

Written 2026-10-01 after two outside reviews (one ML, one systems). Both said the same
thing: the project's bottleneck is real data and a fixed real test set. Every number so
far comes from COCO, the simulator, or about 30 still clips of one person in one dorm
room. This file fixes how real frames are split, counted and scored, so that the next
real number can be compared with the one after it.

## 1. The unit of evidence is the clip

A **clip** is the frames of one recording: one `cpx_grab.py` call (same filename
labels, same folder, frame numbers increasing), or one Lighthouse session
(`tools/lighthouse/record_session.py`).

At ~2 fps with a still subject, consecutive frames differ by about 5 DN, which is
sensor noise. Seventeen frames of a still clip are much closer to one observation than
to seventeen. So:

- every count, rate, confidence interval and model comparison is over **clips**;
- per-frame numbers are diagnostics only and are never quoted as the result;
- a clip needs at least **5 scoreable frames** (2.5 s at 2 fps) to count. Shorter clips
  are link drops, not recordings. They are listed and skipped.

Clips in one run share one camera power-up, and the exposure is set once at power-up
(EXPERIMENTS.md, 2026-09-24 22:15). So clips in a run are not independent either. The
scoreboard reports a run-level bootstrap next to the clip-level one for this reason.

Open: a Lighthouse walking session (3-4 min, ~400 frames) is one clip in v1. Cutting
long sessions into fixed-length segments is a later decision.

## 2. Person-disjoint splits (`splits.json`)

- **Person IDs only.** p01 = Sai. New people get p02, p03, ... in the order they are
  first recorded. No names, emails or phone numbers in the repo, ever. The ID-to-name
  map stays on Sai's laptop.
- Each person has a **pool**: `test` or `train_dev`.
  - A **test** person never appears in anything a model learns from or is tuned on:
    training, fine-tuning, hard-negative mining, threshold choice, augmentation choice.
    If anyone looks at a test person's frames to make a modelling decision, that person
    moves to dev and a new test person is recruited.
  - **p01 is train_dev, permanently.** Every real-frame analysis so far has looked at
    his frames.
- A train_dev person's sessions are assigned to `train` or `dev` **one by one** in
  `train_dev_sessions` (person, then session date). A session that is not listed gets
  split `unassigned` and no scoreboard reads it. Nothing defaults to train.
- **No-person clips** (empty room, clutter) take the split of the people recorded in the
  same run. If the run has nobody, they take the split of the people recorded that
  session date. If that is ambiguous, or there is nobody, add a `runs` entry
  (`"<date>/<run folder>": "dev"`). A run that mixes a test person with a train_dev
  person gets split `conflict` and is scored by nobody until it is split by hand.
- `index_frames.py` writes the split (and the reason) into every index row. Only clips
  whose split is exactly `train`, `dev` or `test` are ever scored.

Today `splits.json` holds one person, p01, with both sessions (2026-09-22, 2026-09-24)
in **dev**. There is no test person yet, so **there is no test split yet.**

## 3. What the test split must cover before a test number is quoted

| requirement | why |
|---|---|
| >= 3 test people (eventually; until then every number says "n people = k") | one person is a case study, not a rate (DECISIONS 2026-09-15) |
| >= 2 backgrounds (locations) | the Sep 24 grid showed background contrast decides detection |
| both exposure regimes: **dim** (clip mean 15-65 DN) and **bright** (>= 65 DN) | exposure is random per power-up until the firmware is fixed; the champion behaves differently in each |
| empty-room clips **and** clutter clips (>= 1 of each per location) | the guard (section 5) needs something to bite on |
| each test person seen left, centre and right of the camera | the x head is what the follower steers on |

The scoreboard prints this table for whatever split it scores and writes
"coverage met" or "coverage NOT met" into the scoreboard row. **The dev baseline does
not meet it** (one person, one location, no clutter clips), as expected.

Exposure regime of a clip, from its mean frame brightness (0-255 scale):
`near_black` < 15, `dim` 15 to < 65, `bright` >= 65. These are descriptive bands drawn
around what was recorded (dim ~35-42, bright ~89-95, near-black ~4-7).

## 4. The headline metric (one number)

**hit@0.75±1** = the mean over person clips of the fraction of the clip's labelled
frames where

- the chip network's visibility confidence is >= 0.75 (the follower's enter bar;
  on the chip this is the integer test `raw >= ceil(logit(0.75)/eps)`, 5467 for the
  champion), **and**
- `|argmax x-bin - label x-bin| <= 1`.

Each clip counts once, whatever its length. The per-clip fraction is the "share of the
time the drone would see the person and point within one bin of them".

Rules:

- **Near-black clips** (mean < 15 DN) carry no scene. They are left out of the
  headline and counted for the guard (section 5), because a lock on one is a lock on
  noise.
- Frames whose label says the person is out of view (`in_fov = 0` in a labels.csv) or
  that have no label are left out of that clip's fraction and counted.
- **Reported next to it, always:** the same metric with an exact bin
  (`exact-bin`: `|diff| = 0`). The ±1 tolerance is part of the definition, but a reader
  must be able to see how much of the score it buys, because the grid labels are
  provisional (section 7).
- **95% interval:** percentile bootstrap over clips (10,000 resamples, seed 0). A
  run-level (cluster) bootstrap is reported as a secondary interval, because clips in
  one run share a power-up.
- **Comparing two models:** paired, on the same clips. The scoreboard's
  `--baseline-json` bootstraps the per-clip difference.
- Per-condition breakdowns (exposure regime, session, run, side, distance, drone,
  location) are descriptive. Each prints its clip count.

## 5. The safety guard (pass/fail)

**No guard clip ever reaches 3 consecutive frames with confidence >= 0.75.**

Guard clips: every **empty-room** clip, every **clutter** clip, and every
**near-black** clip of any kind. Three in a row at the enter bar is exactly the
follower's confirm rule, so a guard failure means the drone would have started
following nothing. One failing clip fails the guard. The scoreboard names it, and
separates lit empty/clutter failures from near-black ones.

The champion is known to fail this on near-black clips (169 frames on Sep 24,
EXPERIMENTS.md 2026-09-24 22:00). The firmware brightness floor is the fix for the
system. The guard here scores the network alone, so it keeps reporting that failure
until a model stops locking on noise.

## 6. COCO F1: a non-regression check only

val2017 F1 (the evaluation that gave the champion 0.8008 in QAT form) is checked so
that a real-data fine-tune does not quietly break general detection. It is not a
target. The allowed drop is 0.005.

## 7. Labels

**Grid clips** (`grid_capture.sh`, `camera_check.sh`): the label is the intended
mark. The expected x-bin comes from the filename's bearing through the existing
geometry code (`score_real_frames.expected_x` and `x_to_bin`, pinhole, crop HFOV 70
deg, which is the simulator's value). **These labels are provisional: FOV/aim
unmeasured.**

- The real camera's field of view has never been measured
  (`tools/real_frames/measure_camera.py`).
- An outside review (2026-10-01) estimated the camera was aimed about 0.16 image-x
  (about 0.7 of a bin) left of centre on the Sep 24 runs 204502 and 183109. That is
  **not** corrected anywhere, on purpose. It is one reason the ±1 tolerance exists and
  why the exact-bin number is always printed next to it.
- The mark is where the subject was asked to stand. On Sep 22 run 2 the subject left
  the LEFT mark early (frames 15-22 have nobody in view, by hand analysis), and on
  Sep 22 run 1 the RIGHT clip ends with the subject walking back to the laptop. Grid
  labels do not know this. A labels.csv can correct it (below).

**labels.csv** overrides the grid label frame by frame, and is the only label source
for Lighthouse sessions. The scoreboard reads `labels.csv` from the clip's folder (and,
for a Lighthouse session, the session folder above `frames/`), plus any file passed
with `--labels`. Columns:

| column | required | meaning |
|---|---|---|
| `frame` | yes | the frame's file name (basename), e.g. `frame_00012_1790908391.330.png` |
| `x_bin` | yes (may be blank) | the true x-bin, 0 (left edge) to 8 (right edge). Blank = no label |
| `size_bucket` | no | the true size bucket 0-3. Diagnostic only in v1 |
| `in_fov` | no | 1 = the person is in the model's crop; 0 = not in view (frame is left out of the person metric and counted) |
| `drop_reason` | no | non-empty = the labeller rejected this frame (no pose, clock gap...); it is left out and counted |
| `clip_id` | no | only needed if two clips have a frame with the same basename |

Extra columns are ignored. This is a subset of what `tools/lighthouse/label_session.py`
writes, so its `labels.csv` plugs in unchanged. Frames a labels.csv does not list keep
the grid label (grid clips) or stay unlabelled (Lighthouse sessions).

## 8. Caveat: the stream is not yet the flight image path

Every real frame so far is **162 x 122, pixel values 0-191, ~2 fps over WiFi**, from
the stock streamer. The flight app's path is the **324 x 244 sensor image, centre-cropped**
on the GAP8. The chip preprocess takes a centre square of whatever it is given, so
162 x 122 is handled geometrically (122 px upsampled to 128), but it is a different
image from the one the drone flies on (binning, value range, exposure handling). Which
stream the dataset should standardise on is a **pending team decision**.

v1 therefore scores whatever was captured and records the stream format of every clip
(width, height, provenance, fps, pixel max) in the index. Numbers from different stream
formats must not be pooled. The scoreboard refuses to mix them in one row unless told
to (`--allow-mixed-streams`).

Also: the "chip" arm is onnxruntime running the integer `model_id_dory.onnx` with the
firmware's preprocessing (`perception_backends.ChipPerception`). It matches the GAP8 to
a rounding step. It is not the GAP8 itself.

## 9. First real fine-tune: pre-registration (PROPOSAL, not approved)

Written before any real-data training, so the success bar cannot move after the fact.

- **Init:** the champion (`plain_follow_prod_qat_v3`, QAT form), with the recipe of
  the Sep 26-27 CONTROL arm (5 QAT epochs, lr 2e-5) unless Sai picks another before the
  run.
- **Data:** real frames from `train`-split clips only, mixed with COCO train2017 at
  **1:1** per batch. Real clips are near-duplicate frames, so sample by clip, not by
  frame.
- **Success, all of these:**
  1. headline hit@0.75±1 improves by **>= +10 points** over the champion, paired on the
     same clips, and the paired clip-bootstrap 95% interval of the difference excludes 0;
  2. the **guard holds** on every guard clip of the scored split;
  3. COCO val2017 F1 drops by **<= 0.005**;
  4. on **both of 2 seeds**.
- **Where:** on the **test** split once it exists. If it does not exist yet when the run
  is done, the result is reported as dev-only and may not be called a success.
- Scored on the chip arm, after the release pipeline (NEMO, integer ONNX), not on the
  fake-quant form.

## 10. Tools

```
# 1. index everything under ~/drone_frames (read-only; writes ~/drone_frames/_index/index.csv)
~/Downloads/drone/trainenv/bin/python tools/real_frames/index_frames.py

# 2. score one split on the chip network; appends a row to docs/eval_results/REAL_SCOREBOARD.md
~/Downloads/drone/trainenv/bin/python tools/real_frames/real_scoreboard.py --split dev \
    --json docs/eval_results/<date>-<name>/scoreboard_dev.json

# tests (synthetic folders, no real frames, no chip needed)
~/Downloads/drone/trainenv/bin/python -m unittest tools/real_frames/test_index_frames.py \
    tools/real_frames/test_real_scoreboard.py
```

`docs/datasets/run_notes.csv` adds per-run facts that no file records (location, and
the drone when a README says which one). Values found in a run's own log or
`meta.json` win over it.
