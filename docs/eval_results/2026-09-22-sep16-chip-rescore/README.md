# The Sep 16 bearing work, re-read on the chip arm

2026-09-22. Item 2.2 of `docs/hardware/before_the_next_session.md`. Rendered
frames only: nothing here was flown or measured on hardware.

**Headline.** Most of the Sep 16 conclusions survive on the chip arm, the one the
drone flies. **What does not survive is the Sep 17 correction that flagged them.**
Its `rescore_chip.py` ran the image preprocess twice, so its "chip" numbers came
from a blurred copy of each frame. On the real chip arm the gap to float is
**-0.020 in mean confidence and -0.043 in the fraction of frames above the 0.75
bar**. Sep 17 reported -0.124 and -0.239. The two arms still disagree cell by
cell, with 45 of 325 cells moving by 0.25 or more, so scoring on the chip arm by
default was still the right fix.

## What was done

1. **The frames had to be re-created.** The 13,003 Sep 16 PNGs sat in a
   session scratchpad that was empty by Sep 22, and only their float scores
   were committed. `scripts/render_grid_frames.py` calls the same
   `mock_streamer.bank_from_scene()` with the same arguments (40-frame bank,
   `himax_typical`, seed 7) on scenes rebuilt from the committed defs. It runs
   in-process, with no sockets and no simulator flight.
   **Checked, not assumed:** scored on the float arm, **13,000 of 13,000 frames
   match the Sep 16 per-frame confidence to 4 dp**, and 322 of 325 cells match
   Sep 16's mean and fraction exactly. The other 3 cells are the ones where Sep
   16's grab caught 41 frames (one repeat). The largest cell difference is 0.0017
   and the aggregate is 0.7065 in both.
2. **Scored on both arms** with `tools/real_frames/score_real_frames.py`, which
   as of this branch takes `--backend {float,chip}` and defaults to chip:
   `model_id_dory.onnx`, sha1 `d90555c8462b…`, eps `2.009823510888964e-4` from
   the release, follower replayed on raw integers with enter >= 5467, lost < -998
   and confirm 3. Each `scores_*.json` records which arm scored it.
3. **The Sep 17 script, unmodified, was re-run** on the same frames.

## The Sep 17 correction was wrong in size, though right in direction

`rescore_chip.py` calls `ChipPerception(firmware_preprocess(g))`, and
`ChipPerception` runs `firmware_preprocess` again, so the network saw a
2x2-blurred copy of what the chip sees. The flights never had this bug: they
call `ChipPerception` on the raw frame.

- Re-running `rescore_chip.py` reproduces the Sep 17 table on **322 of 325 cells**,
  and its "cells moving by 0.25" count is **122**, the same as Sep 17 reported.
- It agrees with the real chip arm on **7 of 13,000 frames**.
- `test_score_real_frames.py` pins the mechanism down frame by frame. Its
  output is reproduced exactly (51/51) only by preprocessing twice. Once is the
  flight path, and the scorer's chip backend equals that on all 14 int32
  outputs.

| 13,000 frames | float | Sep 17 "chip" (preprocessed twice) | **chip (real)** |
|---|---|---|---|
| mean confidence | 0.7065 | 0.5826 | **0.6865** |
| fraction >= 0.75 | 0.5384 | 0.2989 | **0.4956** |
| cells moving >= 0.25 vs float | | 122 of 325 | **45 of 325** |

The flights had already contradicted the Sep 17 table. It put 374369 at 0.250
above the bar on axis at 3.5 m, 266409 at 0.400 and 161875 at 0.000, yet all
three latched 8/8 in the on-axis flights. The real chip arm gives 0.975, 0.975
and 0.950.

The largest real float-to-chip moves are 250127 at 2.0 m, b0 (0.925 to 0.100);
157365 at 1.5 m, b-10 (0.800 to 0.150); and the control at 3.5 m, b+25 (0.325 to
0.875). The moves go in both directions and are not a constant offset.

## Which Sep 16 conclusions survive

"Frac" means the fraction of frames at or above the 0.75 enter bar.

| Sep 16 claim | float (as published) | chip | verdict |
|---|---|---|---|
| **Four subjects "fail on pose", not difficulty**: 161875, 374369, 266409, 401446 near 1.000 on axis at 3.5 m | 0.950, 1.000, 1.000, 1.000 | 0.950, 0.975, 0.975, 0.975 | **Survives** |
| **Four are genuinely hard**: 124442, 527750, 157365, 356427 at 0.000 on axis at every range past 2.0 m | 0.000 at 2.5, 3.0 and 3.5 m | 0.000 at 2.5, 3.0 and 3.5 m | **Survives** |
| ...but "at 1.5 m they all come back" (onaxis README) | 0.950, 1.000, 0.675, 0.800 | 0.750, 0.950, **0.400, 0.400** | **Weakened**: two of the four come back; 157365 and 356427 clear the bar on 40% of frames |
| **Bearing is nearly free up close, expensive far** (cost of +-25 deg vs b0) | 1.5 m: 0.071 / 0.065; 3.5 m: 0.330 / 0.263 | 1.5 m: 0.057 / 0.040; 3.5 m: **0.401** / 0.226 | **Survives** in shape. Still an upper bound, because of the card shadow |
| **Small left/right asymmetry, negative side better**, pooled | +0.021 at 10 deg, +0.059 at 25 deg | +0.017 at 10 deg, **-0.007** at 25 deg | **10 deg survives, 25 deg does not.** At 3.5 m the LEFT is worse at 25 deg (0.335 against 0.511), so "the flown scene sits on the better side" is not supported on the chip arm |
| **The 2.5 m dip is not clean**: pooled interior minimum at 3.0 m, not 2.5; 8 of 13 subjects dip at 2.5 m (b0) | minimum at 3.0 m; 8 of 13 | minimum at 3.0 m; **9 of 13** | **Survives**, slightly stronger. The 2.5 m rung is harder on chip: 161875 0.725 to 0.325, 374369 0.625 to 0.200 at b0 |
| **What a real person must beat** (3.5 m, b0): median 0.975, 4 of 13 at 0.000, bimodal | median 0.975, 4 at 0.000 | median 0.975, 4 at 0.000 | **Survives unchanged** |
| **Mirror check passes; bin accuracy 98-100%** | 100% / 100%, bin acc 99.25% | 100% of 3,850 L / 100% of 3,785 R, bin acc 99.26% | **Survives** |
| **(onaxis) Grid and simulator disagree by 0.44 for 250127** (grid 0.450, flown M1 0.007) | 0.450 | **0.175** | **Mostly an arm artefact.** On the arm that flew, the gap is 0.17 |
| **(onaxis) The grid tracks the on-axis flights** | mean abs gap to flown M1 0.066, max 0.443 (250127) | 0.046, max 0.337 (161875) | **Better on chip.** 161875's residual is the loss of track during approach that the onaxis README already describes, not acquisition |

**Not touched by this rescore**, because none of it depends on the scoring arm:

- **Every flight number.** Both flight suites ran `backend: chip` through
  `ChipPerception` on the raw frame, which is the correct path.
- **The card-shadow confound.** Every off-axis column is still an upper bound
  on the cost of bearing.
- **The rendered-cutout caveats.**

## What to compare real frames against now

Use the `frac_chip` and `mean_conf_chip` columns of `tables/cells_three_arms.tsv`,
bearing 0 only (the off-axis columns carry the shadow). That table puts every arm
side by side for each cell: Sep 16 float, float re-rendered, the Sep 17 table,
the Sep 17 script re-run, and chip.
`2026-09-17-chip-arm-rescore/tables/reference_table_chip.tsv` is **superseded**,
because its chip column came from the preprocess-twice script.

Score real frames with no flags:
`score_real_frames.py <folder>` now runs the chip arm. `rescore_chip.py` should
not be used again.

## Files

- `scripts/run_rescore.sh <scratch>`: runs everything end to end, in about 5 minutes.
- `scripts/render_grid_frames.py`: re-renders the frames.
- `scripts/analyze_rescore.py`: builds `tables/analysis.txt` and `tables/cells_three_arms.tsv`.
- `tables/scores_{chip,float}.csv.gz` and `.json`: the scorer's own output.
  `scores_chip.json` records `backend`, the ONNX path and sha1, the eps and the
  raw thresholds.
- `tables/sep17_rescore_chip_rerun.csv.gz`: the Sep 17 script's output on these
  frames.
- No frames are committed. They are re-rendered into a scratch dir, and the
  folder's `.gitignore` excludes `*.png`.

## Limits

- **The frames are re-renders.** They were verified identical on the float arm,
  per frame, but they are not the original files. The three duplicate frames
  Sep 16's grab caught are not reproduced.
- **The chip arm here is onnxruntime evaluating `model_id_dory.onnx`**, the
  same as every simulator flight. It reproduces the release's own gate
  decisions (96/96 visibility, 96/96 size, 95/96 x-bin), but it is not a
  bit-exact copy of the GAP8's integers (see the `perception_backends.py`
  docstring).
- **Every frac is computed from the CSV's 4-dp confidence.** No chip frame
  lands exactly on 0.7500 or 0.4500, so no frame is misclassified at the bars.
- **Rendered cutouts on opaque cards, one scene.** Everything in the Sep 16
  limits section still applies.
