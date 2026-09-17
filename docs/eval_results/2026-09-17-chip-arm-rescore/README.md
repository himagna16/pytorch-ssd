# The reference table was scored on the wrong network, and so would tomorrow's real frames

2026-09-17, 02:20. Found by an adversarial check on an unrelated discrepancy.
**This is the most important thing in the last two days and it needs acting on
before the hardware session.**

## The defect

`tools/real_frames/score_real_frames.py` has no backend switch. It is hardwired to
the **float** arm: a PIL BILINEAR 244 to 128 resize and the float PyTorch
checkpoint `successor_qat_ep3_eval.pth` (lines 194-198 and 277-278).

Every flight this project has ever run used the **chip** arm: `"backend": "chip"`
in all 316 `cell.json` files across both flight suites, meaning the int8 export
`model_id_dory.onnx` plus the firmware's integer 2x2-block preprocess. That is
what the GAP8 runs and what the drone flies.

Those are different networks with different preprocessing. On the same 13,003
frames they disagree badly.

## How badly

| | float arm | chip arm | change |
|---|---|---|---|
| mean confidence | 0.7065 | 0.5826 | **-0.124** |
| fraction of frames at or above the 0.75 bar | 0.5383 | 0.2989 | **-0.239** |

**122 of 325 cells move by 0.25 or more.** It is not a constant offset and cannot
be corrected with one. Some cells collapse completely and a few go the other way:

| cell | float | chip |
|---|---|---|
| 374369 at 3.0 m, bearing 0 | 1.000 | **0.000** |
| 556158 at 3.5 m, bearing -10 | 1.000 | **0.000** |
| 161875 at 2.0 m, bearing -10 | 1.000 | 0.025 |
| 61747 at 2.5 m, bearing +25 | 0.075 | **0.550** |
| 250127 at 1.5 m, bearing +25 | 0.625 | 0.925 |

## Why it matters tomorrow, which is the point

The capture protocol tells the operator to score real frames with
`score_real_frames.py`. That would report what a float PyTorch model sees, not
what the drone does, and it would report it about 0.24 too high on the fraction of
frames above the enter bar.

Worse, the reference table those frames were going to be compared against was
built the same way, so a real person could look like they match the simulation
while both numbers are wrong in the same direction.

## What is now in the repo

`tables/reference_table_chip.tsv` carries **both arms for every one of the 325
cells**, so the comparison can be made against the arm the drone actually flies.
The corrected bearing-0 column, fraction of frames above the bar:

| subject | index | 1.5 m | 2.0 m | 2.5 m | 3.0 m | 3.5 m |
|---|---|---|---|---|---|---|
| 124442 | 28.4 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| 527750 | 34.3 | 0.100 | 0.000 | 0.000 | 0.000 | 0.000 |
| 157365 | 34.6 | 0.750 | 0.000 | 0.000 | 0.000 | 0.000 |
| 356427 | 37.8 | 0.325 | 0.000 | 0.000 | 0.000 | 0.000 |
| 250127 | 52.1 | 0.400 | 0.250 | 0.000 | 0.000 | 0.000 |
| 61747 | 86.8 | 1.000 | 0.825 | 0.000 | 0.000 | 0.000 |
| 161875 | 87.0 | 0.625 | 0.275 | 0.000 | 0.025 | 0.000 |
| 401446 | 88.8 | 1.000 | 1.000 | 1.000 | 0.275 | 1.000 |
| 374369 | 90.3 | 0.900 | 0.800 | 0.150 | 0.000 | 0.250 |
| 266409 | 92.1 | 1.000 | 1.000 | 0.275 | 0.025 | 0.400 |
| 280779 | 92.7 | 1.000 | 0.925 | 0.175 | 0.275 | 0.975 |
| 556158 | 93.9 | 1.000 | 1.000 | 0.125 | 0.200 | 0.900 |
| control | 99.2 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |

`scripts/rescore_chip.py` produces the chip column for any folder of captured
frames. It runs under `doryenv`, which is the only environment with onnxruntime,
and it does **not** modify anything under `tools/`.

```bash
~/Downloads/drone/doryenv/bin/python \
  docs/eval_results/2026-09-17-chip-arm-rescore/scripts/rescore_chip.py \
  ~/drone_frames/2026-09-17
```

13,003 frames took 23 seconds, so a real capture is seconds.

## What this invalidates

Every number in `2026-09-16-protocol-geometry` is the float arm. Its
subject-by-subject conclusions, the bearing cost table, and the 2.5 m rung
discussion all need re-reading against the chip column, and some of them will not
survive. That directory now carries a pointer here.

It does not touch the flight suites. Those ran the chip arm throughout and their
tracking numbers are what the drone did.

## The proper fix, not done here

`score_real_frames.py` should take a `--backend {float,chip}` and default to chip,
since chip is what ships. That is a change to a shared tool under `tools/`, which
per the repo's own rules goes on a branch with a PR, and it is not something to do
unreviewed a few hours before a hardware session. It should be the first thing
after the session.
