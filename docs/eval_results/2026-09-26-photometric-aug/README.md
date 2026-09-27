# Photometric augmentation (PULP-Frontnet recipe) vs the Himax exposure problem, 2026-09-26

**Status: PRE-REGISTERED, training not yet started.** This section was written and committed
before either run launched. Results go below it; this section is not edited afterwards.

## Why

Sep 24: the AI-deck camera's exposure is random at every power-up (brightness 4-146 in one
room), and the champion's confidence swings with it (2.44 m LEFT: 0.88 dim, 0.29 bright).
PULP-Frontnet (Palossi et al. 2021, arXiv 2103.10873, Sec. IV-B) flies the same Himax
HM01B0 and handles "erratic auto exposure" at training time, with contrast, brightness,
gamma, vignetting and blur jitter. Our training applies only a horizontal flip.

Code: branch `sai/photometric-aug` (stacked on PR #3, `sai/qat-init-preserve-alphas`),
`train.py --photometric-aug frontnet`, `utils/transforms.py::RandomPhotometricHimax`,
tests `tests/test_photometric_aug.py` (14/14).

## Design

Two arms, identical except for the one flag. Both start from the champion
(`training/CHAMPION_qat_ep3_f1_8008.pth`, sha256 26384b31...), QAT with its learned ranges
preserved (PR #3 default), no manifest, hard-negative mining OFF in both
(`--hard-negative-start-epoch 99`), 5 epochs x 2,600 batches of 16, lr 2e-5, seed 0.

- **AUG**: `--photometric-aug frontnet`
- **CONTROL**: `--photometric-aug none`

The control exists because the Sep 14 lesson was that extra fine-tuning alone moves the
numbers. Any claim is AUG vs CONTROL, not AUG vs champion. Run sequentially (MPS memory).

**Epoch rule, fixed now:** each arm is judged at its final epoch (5). All epochs reported.

## Pre-registered tests

1. **No harm on clean images.** COCO val2017 peak F1, fake-quant (`export/sweep_fq_ckpt.py
   --mode qat`). HARM if AUG is below CONTROL by more than 0.005 (about twice the paired
   sd of 0.0024-0.0031 measured Sep 14).
2. **Robustness to exposure, on a distortion NOT used in training.** COCO val2017 with
   the exposure changed in linear light: pixel -> clip(k * pixel^2.2, 0, 1)^(1/2.2),
   re-quantised to 8 bits, for k in {0.25, 0.5, 2, 4}. Clipping at 1 (blown highlights)
   and crushing to 0 are not in the training augmentation. Same threshold as test 1's
   clean peak for each arm. SUCCESS if AUG's F1 averaged over the four k beats CONTROL's
   by more than 0.01.
3. **Real frames (descriptive, small n, one person, one room).** Sep 24 grid frames in
   `~/drone_frames/2026-09-24/`, split by frame brightness into dim (about 40) and bright
   (about 75-95). Per group: share of person frames at conf >= 0.75, median conf, and
   empty-room frames at >= 0.75. Near-black frames (mean < 15) reported separately and
   **expected not to improve**: they contain no scene; that is the firmware guard's job.
   No pass/fail: n is too small, and position and background are confounded.
4. **Pet safety check.** Confuser-slice false-positive rate (`export/confuser_slice_eval.py`),
   AUG vs CONTROL, at 0.45 and at matched recall. Reported, not gated.

Nothing here touches the chip. A winning checkpoint would still need the release pipeline
(NEMO -> DORY -> GVSOC) and the semantic gates before it could fly.
