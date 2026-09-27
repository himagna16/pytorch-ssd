# Photometric augmentation (PULP-Frontnet recipe) vs the Himax exposure problem, 2026-09-26

**Status: DONE, both runs complete; results are at the end.** The section below was
written and committed (6f2abb8) before either run launched and has not been edited since,
apart from this status line.

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

---

# RESULTS (added after both runs, 2026-09-26 22:00)

**Verdict: the PULP-Frontnet augmentation, copied as-is, makes our model worse. It fails
both pre-registered tests, and on real frames it is worst on exactly the bright frames it was
meant to help.** Not recommended for the flight model. `--photometric-aug` stays an opt-in
flag (default `none`, PR #7) so variants can be tried.

Both runs completed 5/5 epochs (AUG 19:27-20:45, CONTROL 20:45-21:52), each log shows
`PRESERVED 59 learned PACT range tensors`, and the harness reproduces the champion's recorded
numbers exactly (clean peak F1 0.8008, pet FP 0.239 / 0.171) before scoring anything new.
Epoch-5 checkpoints (outside the repo): AUG `training/photaug_aug/plain_follow_epoch_005.pth`
(sha256 9c7227907b08d716...), CONTROL `training/photaug_control/plain_follow_epoch_005.pth`
(2b015ecc61edd09c...).

## Tests 1, 2, 4: COCO val2017 (n = 5,000), pre-registered form (learned QAT ranges)

| model | clean peak F1 | k=0.25 | k=0.5 | k=2 | k=4 | mean over k | pets FP @0.45 |
|---|---|---|---|---|---|---|---|
| champion (start point) | 0.8008 | 0.7782 | 0.7936 | 0.7863 | 0.7546 | 0.7782 | 0.239 |
| CONTROL epoch 5 | 0.8010 | 0.7777 | 0.7944 | 0.7805 | 0.7529 | 0.7764 | 0.283 |
| AUG epoch 5 | 0.7848 | 0.7739 | 0.7841 | 0.7730 | 0.7494 | 0.7701 | 0.316 |

AUG minus CONTROL, paired bootstrap over images (1,000 resamples, 95% interval):

- **Test 1, clean peak F1: -0.0162 [-0.0231, -0.0083] -> HARM** (bar was -0.005).
- **Test 2, mean F1 under exposure change: -0.0063 [-0.0124, -0.0007] -> NOT MET.** The
  bar was +0.01 in AUG's favour; the result is in the other direction, and the interval
  excludes zero. AUG does lose less from clean to distorted (0.015 vs 0.025), but only
  because it starts lower; it is below CONTROL at every k.
- **Test 4, pets:** AUG 0.316 vs CONTROL 0.283 at 0.45; at matched recall 0.316 vs 0.279.
  Worse, not gated.

Every AUG epoch (1-5) sits 0.013-0.020 below every CONTROL epoch on clean F1, so the epoch-5
rule did not pick an unlucky point. The release form (ranges recalibrated, as the chip
export does) gives the same picture: clean -0.0128 [-0.0189, -0.0051] HARM, mean over k
-0.0047 [-0.0109, +0.0012] NOT MET. Full tables: `results/report_qat.txt`,
`results/report_release.txt`.

## Test 3: Sep 24 real frames (descriptive; one person, one room, 515 frames, 31 clips)

Release form, which tracks the chip arm best (champion vs chip: corr 0.989, mean -0.051,
same side of 0.75 on 87% of frames; the QAT form manages 70%). Seen = conf >= 0.75; locked =
the follower's 3-frame rule.

| clips | champion seen / locked | AUG seen / locked | CONTROL seen / locked |
|---|---|---|---|
| dim (about 40), person, 204 frames | 45% / 40% | 39% / 39% | **55% / 52%** |
| bright (about 93), person, 69 frames | 38% / 41% | **16% / 4%** | 41% / 41% |
| dim + bright, empty room, 78 frames | 0% / 0% | 0% / 0% | 0% / 0% |
| near-black (about 4), 164 frames | 76% / 68-85% | 0% / 0% | 0% / 0% |

1. **AUG is worst on bright frames** (seen 38% -> 16%, locked 41% -> 4%), the case this was
   supposed to fix. Five clips, one session, so this is a direction, not a rate.
2. **The near-black lock-on disappears in BOTH fine-tuned models, not just AUG.** Median
   confidence on noise frames falls from 0.76-0.77 (champion) to 0.53-0.55 (AUG) and 0.34-0.37
   (CONTROL). So it comes from fine-tuning, not augmentation. Two cautions: it is fake-quant
   only (the champion in this form does reproduce the chip's lock-on, which is encouraging but
   not proof), and near-black frames carry no scene, so the champion's answer there was
   arbitrary and any retrain can move it either way. **The firmware brightness-floor guard is
   still required.**
3. CONTROL looks slightly better than the champion on dim frames (55% vs 45% seen). That was
   not the hypothesis, n is small, and it is one seed; do not read it as a result.

Per clip: `results/real_frames_report_release.txt` (and `_qat.txt`); per frame:
`results/real_frames_per_frame_*.csv` (numbers only; frames stay on the laptop).

## Why it might have failed (untested explanations, cheapest to check first)

- **The blur is too strong for our task.** sigma 2.4 px at 128 px, on half of all images.
  Frontnet sees one nearby person; COCO labels count small, distant people as "visible", and
  a blur that erases them leaves the label saying "person", which is label noise. AUG's loss
  of recall fits this.
- **Contrast/gamma about the mean is not what the Himax does.** Our bright failure is
  auto-exposure picking a different gain, which saturates highlights. The paper's
  augmentation never clips on purpose, and Test 2 (which does) shows no benefit.
- **Different regime.** Frontnet trained from scratch for 100 epochs on Himax frames; this is
  5 low-lr QAT epochs on COCO with a width-0.1 network that may not have spare capacity.

## Not done, and what it would take

- **One seed per arm.** Paired sd from Sep 14 is 0.0024-0.0031, and the clean gap is -0.016,
  about 5x that, so the harm is unlikely to be seed noise, but it is unreplicated.
- **Next candidate (proposed, not run):** the same two arms with blur off and a
  highlight-clipping exposure jitter in place of contrast, which addresses the first two
  explanations directly. About 2.5 h of laptop time.
- Nothing here ran on the chip. Any candidate would need the release pipeline and the
  semantic gates, and its black-frame behaviour checked on the chip arm.

---

# ROUND 2: PRE-REGISTRATION (written 2026-09-26 night, before any round-2 run launched)

Everything above this line is round 1 and is not edited. Round 2 asks two things: whether a
preset aimed at the Himax's actual failure helps, and whether round 1 replicates on a
second seed.

**New preset `exposure`** (`RandomExposureHimax`, branch `sai/photometric-aug`): with p=0.5 an
exposure gain k, log-uniform in [0.25, 4], applied in linear light (gamma 2.2), clipped at
white and re-quantised to 8 bits; with p=0.5 the same vignetting as `frontnet`. No blur, no
contrast or gamma about the mean.

**Runs**, queued in this order, identical to round 1 except for the flag and seed:
1. EXPO seed 0 (`--photometric-aug exposure --seed 0`)
2. CONTROL seed 1
3. EXPO seed 1
4. FRONTNET seed 1 (replication of round 1's AUG)

Epoch rule unchanged: each run judged at epoch 5.

**Tests.** Primary: EXPO s0 vs CONTROL s0 (round 1). Replication: the same test on s1.

1. **No harm on clean images:** HARM if EXPO is more than 0.005 below CONTROL on clean
   peak F1 (qat form).
2. **Exposure change (k in {0.25, 0.5, 2, 4}):** reported, but it is now **in-distribution**
   for EXPO, because this is the family it trains on. Not a pass/fail test.
2b. **Held-out distortion:** COCO val with contrast x0.7 and x2.0 (about each image's mean)
   and gamma 0.5 and 2.0. EXPO never trains on these. SUCCESS if EXPO beats CONTROL by more
   than 0.01, averaged over the four.
3. **Real frames, the target** (Sep 24, release form): on bright clips with a person
   (69 frames, 5 clips), EXPO should be *seen* (conf >= 0.75) at least 10 points more often
   than CONTROL, with no false locks on empty-room frames. Stated as a direction because
   n is small and it is one person.
4. **Pets:** reported, not gated.

**Replication of round 1:** FRONTNET s1 vs CONTROL s1, round 1's Tests 1 and 2 with round 1's
bars. **Near-black:** does CONTROL s1 also stop locking on noise frames (round 1: 0%)?

## Round 2, interim (EXPO seed 0 only, 2026-09-26 23:15; seed-1 runs still training)

EXPO s0 epoch 5 vs CONTROL s0 epoch 5, qat form: clean -0.0022 [-0.0052, +0.0025] (no
harm); exposure change +0.0042 [+0.0010, +0.0070] (in-distribution, not gated); held-out
contrast/gamma **-0.0053 [-0.0083, -0.0022], NOT MET**. Release form: -0.0014, +0.0047,
+0.0006 (NOT MET). Real frames (release form): person seen dim 74% vs 55%, bright 48% vs 41%
(+7 points, bar +10), but the dim empty-room clip from run 204502 now **false-locks 73% of
frames** (conf 0.76) where CONTROL and the champion never lock. **Test 3 NOT MET.** Reading:
EXPO is more willing to say "person" in dark scenes, including empty ones, which is what
training on darkened images that still contain people would teach. Not a fix. Seed 1 decides
whether any of this holds.

---

# ROUND 2 RESULTS (all four runs complete, 2026-09-27 02:30)

All runs finished 5/5 epochs from commit 1c5e30b, each with `PRESERVED 59` in its log.
Epoch-5 sha256 prefixes: CONTROL s1 af1515a6fec8ba45, EXPO s0 557a1a4a331077d6, EXPO s1
cd0504941cf73d87, FRONTNET s1 fdb69060037f57e9. Reports: `results/round2/`.

**Verdict: no camera augmentation we tried helps. The Frontnet recipe's harm replicates.
The exposure preset does no harm on COCO but passes none of its tests.** The one consistent
difference from the champion comes from plain fine-tuning, which neither round was designed
to test (see the end).

## COCO (qat form, the pre-registered one; release form in the reports agrees)

| comparison | Test 1 clean F1 | Test 2 exposure (k) | Test 2b held-out contrast/gamma |
|---|---|---|---|
| FRONTNET s0 - CONTROL s0 (round 1) | **-0.0162** [-0.0231, -0.0083] HARM | -0.0063 | -0.0055 |
| FRONTNET s1 - CONTROL s1 | **-0.0166** [-0.0223, -0.0089] HARM | -0.0076 [-0.0128, -0.0020] | -0.0064 |
| EXPO s0 - CONTROL s0 | -0.0022 [-0.0052, +0.0025] no harm | +0.0042 (in-distribution) | -0.0053 [-0.0083, -0.0022] NOT MET |
| EXPO s1 - CONTROL s1 | -0.0011 [-0.0048, +0.0035] no harm | +0.0035 (in-distribution) | -0.0037 [-0.0072, -0.0002] NOT MET |

- **Round 1 replicates.** FRONTNET costs 0.016-0.017 clean F1 on both seeds, and loses on
  both distortion families, including the contrast/gamma family it trains on.
- **EXPO** is harmless on clean images and gains about 0.004 on the exposure family it trains
  on, which is small and expected. On the held-out family it is slightly *worse* on both seeds.
  So it does not learn a general robustness, only a narrow one.
- Pets at 0.45: EXPO 0.284 / 0.291 vs CONTROL 0.283 / 0.300 (a wash); FRONTNET 0.316 / 0.333,
  worse on both seeds.

## Real frames (Sep 24, release form)

| model | person, dim: seen / locked | person, bright: seen / locked | empty rooms: false locks | near-black: locked (median conf) |
|---|---|---|---|---|
| champion | 45% / 40% | 38% / 41% | 0 | 68-85% (0.76-0.77) |
| CONTROL s0 / s1 | 55% / 52%, 57% / 57% | 41% / 41%, 45% / 42% | 0 / 0 | 0 / 0 (0.34-0.37, 0.53-0.58) |
| FRONTNET s0 / s1 | 39% / 39%, 60% / 50% | **16% / 4%, 25% / 4%** | 0 / 0 | 0 / 0 (0.53-0.54, 0.62) |
| EXPO s0 / s1 | 74% / 62%, 66% / 60% | 48% / 43%, 43% / 42% | **one clip 73%** / 0 | 0 / 0 (0.37-0.40, 0.46-0.48) |

- **Test 3 (EXPO, bright +10 points and no empty-room locks): NOT MET on either seed.** s0:
  +7 points but a false lock on the dim empty room (run 204502). s1: -2 points, no false locks.
  The s0 false lock did not replicate, and neither did any bright-frame gain.
- **FRONTNET's bright-frame loss replicates** (locked 4% on both seeds vs 41-42% for CONTROL).
- EXPO is ahead of CONTROL on dim frames on both seeds (74/66% vs 55/57% seen), but it also
  runs more confident on dim empty frames (seen 31% / 10% vs 0% / 4%). That looks more like a
  shift in how willing it is to say "person" in the dark than a better detector.

## What replicated that nobody designed for: plain fine-tuning

Both CONTROL seeds (5 more QAT epochs from the champion, no augmentation) match the champion on
COCO (0.8010 / 0.7991 vs 0.8008), see me more on dim frames (55% / 57% vs 45%), and **never lock
on the near-black noise frames** that the champion locks on 68-85% of the time. Every one of the
six fine-tuned models, augmented or not, stops that lock-on. Cautions, all important:

- Fake-quant only. The chip arm reads about 0.05 higher than this form, and the seed-1 medians
  on noise frames (0.53-0.62) leave less margin under 0.75 than seed 0 (0.34-0.40). A different
  calibration could bring the lock back. **The firmware brightness guard is still required.**
- The dim-frame gain is one person in one room, and it was not a pre-registered question.
- Why fine-tuning does this is unknown. The champion's QAT run was stopped at epoch 3 by an
  out-of-memory kill, so it may simply have been under-trained.

**Suggested next step (a decision for Sai, not run):** push CONTROL s0 through the release
pipeline (NEMO -> integer ONNX -> semantic gates) and score it on the chip arm, to check the
near-black result where it matters. That needs the Docker export lane, which is heavier than
laptop training and touches the release tooling.
