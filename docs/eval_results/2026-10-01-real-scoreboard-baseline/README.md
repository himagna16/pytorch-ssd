# Real-frame scoreboard, baseline row: the champion on dev (2026-10-01)

The first row of `docs/eval_results/REAL_SCOREBOARD.md`. It scores every real AI-deck clip
recorded so far with the metric and guard proposed in `docs/datasets/real_test_v1.md`
(**PROPOSED, needs Sai's sign-off**). All of it is p01 (Sai), so all of it is **dev**.
**This is not a test result and there is no test split yet.** No new data was recorded.
The frames stay on Sai's laptop; this folder holds numbers and file names only.

- Model: champion, chip arm (`plain_follow_prod_qat_v3/quant_eval/model_id_dory.onnx`,
  sha1 d90555c8, eps 2.0098e-4, enter raw >= 5467), through
  `score_real_frames.ChipModel` (firmware preprocess + onnxruntime).
- Data: `~/drone_frames/2026-09-22` and `2026-09-24`, indexed by
  `tools/real_frames/index_frames.py` (`index_snapshot.csv`, sha1 390a6505).
- Labels: the intended grid marks. **Provisional: FOV/aim unmeasured.**

## Numbers

| | value | 95% CI (clips) | 95% CI (runs) | n |
|---|---|---|---|---|
| **hit@0.75±1** (headline) | **36.5%** | [22.7, 50.6] | [16.7, 50.1] | 20 person clips |
| exact-bin | 20.9% | [11.0, 31.5] | | 20 |
| seen (>= 0.75, any bin; diagnostic) | 46.8% | [31.5, 62.0] | | 20 |
| **guard** | **FAIL** | | | 15 guard clips |

- The ±1 tolerance is worth 15.6 points (36.5 vs 20.9). On the 164 labelled frames
  the champion was confident on (>= 0.75): 73 had the exact bin, **43 were one bin to the
  left** of the label and 12 one bin to the right, and 36 were 2-5 bins off. Most of the
  2-5 bin misses are the known right-side pull (22 frames on left or centre marks read as
  bin 6-7) or right marks read as the centre bin 4 (10 frames). A one-bin leftward lean
  fits the outside review's aim estimate (about 0.7 bin). It is **not** corrected here,
  and these frames cannot separate an aim offset from an FOV error from a model bias.
- The run-level interval is wider than the clip-level one because clips in one run
  share a camera power-up. The 20 clips come from 6 power-ups.

### Guard

| guard clips | n | worst run of frames >= 0.75 | verdict |
|---|---|---|---|
| lit empty room (dim 37-42 DN: 3; bright 95 DN: 1) | 4 | 1 (run 204502: 3 frames >= 0.75, max 0.785, never 2 in a row) | pass |
| near-black (mean 4-7 DN), empty and "person" clips | 11 | 13-26, i.e. every frame | **FAIL** (all 11) |

The failure is entirely the known near-black lock-on (runs 204144 and 215739,
EXPERIMENTS.md 2026-09-24 22:00). On lit empty rooms the champion never reached the
confirm rule. Peaks were 0.60-0.79, and the 204502 empty room crossed 0.75 on single
frames, so the margin is thin.

### Breakdowns (person clips; descriptive)

| condition | hit@0.75±1 | 95% CI | exact | clips |
|---|---|---|---|---|
| dim (15-65 DN) | 40.2% | [23.9, 56.8] | 22.9% | 14 |
| bright (>= 65 DN) | 27.9% | [5.3, 53.3] | 16.4% | 6 |
| left marks | 49.1% | [26.9, 70.0] | 28.3% | 9 |
| centre marks | 16.5% | [0.0, 47.1] | 7.1% | 5 |
| right marks | 34.4% | [18.7, 47.5] | 21.4% | 6 |
| 1.52 m | 68.6% | [58.8, 76.5] | 54.9% | 3 |
| 2.13 m | 34.3% | [9.8, 62.7] | 19.6% | 6 |
| 2.44 m | 28.9% | [12.9, 46.9] | 12.4% | 11 |
| session 2026-09-22 | 19.3% | [6.8, 29.5] | 9.1% | 4 |
| session 2026-09-24 | 40.8% | [24.6, 57.0] | 23.9% | 16 |

These overlap heavily, and conditions are confounded (centre = the dark door; the
bright clips are mostly from other power-ups and other distances). They describe this
data. They do not establish effects. Per clip: `scoreboard_dev.json` (`clips`) and
`scoreboard_dev.txt`. Per frame: `frames_dev.csv`.

## What the index found (`index_snapshot.csv`)

- **38 clips, 656 frames**: 30 person clips, 6 empty-room clips, 2 unlabelled 5-frame
  stream checks (`camera_check_*/check`), and **0 clutter clips**.
- **Exposure regimes:** 18 dim (34-42 DN), 9 bright (89-95 DN), **11 near-black**
  (3.9-6.9 DN: all of run 215739 and the empty clip of 204144).
- Every clip is **162 x 122 raw at about 2 fps** (1.75-2.2 fps; the stock streamer).
  Pixel values top out at 191, and bright clips have about 10-14% of pixels at that code
  (saturated), against under 1% for dim clips.
- Within one folder, run 183109 is **two power-ups**: clips 0-5 dim, then clips 6-8
  bright after the battery swap. The index splits them by the log's start headers.
- The drone is recorded for 2 of 8 data runs only: 215739 from its log, and 183109 from
  the Sep 24 README (`run_notes.csv`). Both are drone 09.
- **No run logged a power-up brightness.** The pre-flight exposure check was added to
  `grid_capture.sh` after the last of these runs. The column fills from the next grid
  on.
- `2026-09-17/` is empty. Nothing under `_rehearsal/` was indexed.

## Data problems found (none corrected; each needs Sai's call)

1. **Grid labels say where the subject was asked to stand, not where he was.** On Sep 22
   run 2 (`camera_check_182858`), the LEFT clip has nobody in view for frames 15-22, by
   the hand analysis in `2026-09-22-first-real-frames/README.md`. On run 1
   (`181258`), the RIGHT clip ends with Sai walking back to the laptop. Both count as
   misses or wrong-bin frames here. A `labels.csv` (`in_fov = 0` for those frames) fixes
   this once someone checks the frames.
2. `grid_capture_194556`, 2.44 m CENTRE has **1 frame** (the link dropped). It is
   excluded under the 5-frame minimum.
3. **Light labels are inconsistent.** Lights the Sep 24 README calls the same room lights
   are labelled `light-room` at 18:31 and `light-night-lights` from 19:45 on, and run 183109 carries `light-room` across both of
   its power-ups (dim and bright). Nothing scores by this label. Use `exposure_regime`.
4. The unlabelled `check/` frames show Sai at the laptop in the right foreground. They
   are indexed but never scored.
5. Exposure varies by power-up (4 to 146 DN on Sep 24), so this "dev set" has two
   different cameras in effect, plus a dead one.

## Caveats (read before quoting anything)

- **One person, one room, one chair position, two nights.** This is a case study and a
  baseline for the tooling, not a detection rate for people.
- **Labels are provisional:** the crop FOV (70 deg) is the simulator's, the real camera
  is unmeasured, and the aim was not checked per run (section 7 of the proposal).
- **Still clips:** consecutive frames are near-duplicates, so the 360 labelled metric
  frames carry about 20 clips' worth of evidence, not 360 frames' worth.
- **Two exposure regimes, set at random by power-up.** Do not compare a dim number from
  one model with a bright number from another.
- **Not the flight image path:** 162 x 122 at ~2 fps from the stock streamer, not the
  324 x 244 crop the flight app uses (proposal section 8; team decision pending).
- The chip arm is onnxruntime on the integer ONNX. It matches the GAP8 to a rounding
  step. It is not the GAP8 itself.
- The definitions are PROPOSED. If Sai changes them, this row is re-run, not edited.

## Reproduce

```
cd ~/Downloads/drone/pytorch_ssd   # or the worktree
~/Downloads/drone/trainenv/bin/python tools/real_frames/index_frames.py
~/Downloads/drone/trainenv/bin/python tools/real_frames/real_scoreboard.py --split dev \
    --model-name "champion (plain_follow_prod_qat_v3)" --no-append \
    --json /tmp/sb.json --frames-csv /tmp/frames.csv
```

This takes about 2 s on the laptop. The bootstrap is seeded (seed 0, 10,000 resamples),
so the numbers reproduce exactly from the same index.
