# Releasing with the ranges learned in QAT (`--preserve-qat-alphas`), Oct 1, 2026

**Question.** The release pipeline threw away the activation ranges a QAT model learns
and recalibrated them on 128 images. Does keeping them (Grace's Aug 31 design,
implemented on branch `sai/preserve-qat-alphas`, PR against `successor-release`)
change what the chip does?

**Answer.**
- **It makes the chip network a faithful copy of the network we trained, and it removes
  a known bias.** Recalibration made the champion's chip network read **+0.20 logit
  hotter** than its own QAT network. With the learned ranges kept, the gap is +0.02
  (interval includes 0). This is the cause of the unexplained "chip runs 0.13-0.19
  hotter" in `2026-09-11-unbiased`.
- **At the same threshold, false alarms fall a lot:**

  | false alarms | recalibrated | preserved |
  |---|---|---|
  | champion, pets/mannequins at 0.45 | 30.2% | 25.0% |
  | champion, pets/mannequins at the shipped 0.75 | 9.1% | 6.9% |
  | champion, empty scenes at 0.75 | 9.1% | 6.3% |
- **At matched recall, it is not a better detector.** Comparing at equal person-finding,
  the project rule, the false-alarm difference is 0.3 points with an interval spanning
  zero, for both models. Nearly all of the same-threshold gain is the removed bias,
  which acts like a confidence dial.

## Setup

Both models are QAT checkpoints, released twice each through the full pipeline (576-image
pack, DORY patched, GVSOC multi-image, the five semantic gates), with no app promotion:

| model | recalibrated release | preserved release |
|---|---|---|
| confuser, QAT + mining, epoch 2 | `pqa_qathn3_ep2_default` (re-run tonight) | `pqa_qathn3_ep2_preserve` |
| champion (shipped) | `plain_follow_prod_qat_final` (the shipped ONNX, d90555c8) | `pqa_champion_preserve` |

**All four releases pass all five gates.** The pipeline's own agreement gate (chip vs
float, 608 images):

| model | recalibrated | preserved |
|---|---|---|
| confuser | 91.1% | 92.3% |
| champion | 95.7% (shipped ONNX d90555c8, 608-image re-gate `plain_follow_eval576_qat`) | 97.0% |

**Flag off is unchanged.** Tonight's default re-release of the confuser reproduces Sep 11
as follows:
- Both ONNX files are byte-identical.
- All 57 generated app files have identical weights.
- The only differences are DORY's include order and a Python object address in a code
  comment; both are DORY nondeterminism, not ours.
- The reports are identical after path normalisation.

**The evaluation** (`scripts/infer_pqa.py`, `scripts/analyze_pqa.py`, `results.json`)
reuses the Sep 11 unbiased images: 1,000 random val2017 images (seed 20260911) plus the
771-image confuser slice (animals or teddy bears, no person). It uses the same chip
preprocessing as Sep 11.

There are four arms per model:
1. float;
2. the QAT network exactly as trained (fake-quant with the learned ranges);
3. the recalibrated chip;
4. the preserved chip.

The chip arms are ONNX Runtime on each release's `model_id_dory.onnx`, times that
release's eps.

**It reproduces Sep 11 exactly.** Recalibrated chip slice false alarms at 0.45: champion
233/771 = 30.2%, confuser 82/771 = 10.6%. QAT network: champion 23.9%, confuser 8.4%.

## Results

### Champion (the model we fly)

| | float | QAT net | chip, recalibrated | chip, preserved |
|---|---|---|---|---|
| F1 at 0.5 | 0.812 | 0.815 | 0.811 | 0.811 |
| recall at 0.75 | 0.625 | 0.617 | **0.651** | 0.613 |
| empty-scene false alarms at 0.75 | 5.9% | 5.9% | **9.1%** | 6.3% |
| pet/mannequin false alarms at 0.45 | 27.0% | 23.9% | **30.2%** | 25.0% |
| pet/mannequin false alarms at 0.75 | 8.2% | 7.7% | **9.1%** | 6.9% |
| chip − QAT vis logit, mean [95% CI] | | | +0.200 [+0.177, +0.224] | +0.017 [−0.006, +0.039] |
| agreement with QAT net, p = 0.5 | | | 95.2% | 97.2% |
| confident contradictions with QAT net | | | 1 / 834 | 0 / 834 |

**Same threshold, paired.** On the slice at 0.45, 43 images false-alarm only on the
recalibrated chip and 3 only on the preserved one (McNemar p = 5e-10). At 0.75 it is 17
vs 0 (p = 2e-5).

**Matched recall** (0.651, the recalibrated chip at the shipped 0.75):

| | threshold needed | slice false alarms | empty-scene false alarms |
|---|---|---|---|
| recalibrated chip | 0.750 | 9.1% | 9.1% |
| preserved chip | 0.710 | 8.8% | 8.3% |

Difference in slice false alarms: −0.26 points [−1.17, +1.04]. **No difference.**

### Confuser, QAT + mining epoch 2 (the motivating case in Grace's task)

| | float | QAT net | chip, recalibrated | chip, preserved |
|---|---|---|---|---|
| F1 at 0.5 | 0.749 | 0.740 | 0.740 | 0.745 |
| recall at 0.75 | 0.472 | 0.442 | 0.447 | 0.440 |
| pet/mannequin false alarms at 0.45 | 9.6% | **8.4%** | **10.6%** | **9.3%** |
| chip − QAT vis logit, mean [95% CI] | | | +0.163 [+0.131, +0.192] | +0.122 [+0.097, +0.148] |
| agreement with QAT net, p = 0.5 | | | 92.9% | 94.4% |
| confident contradictions with QAT net | | | 3 / 870 | 1 / 870 |

- **Same threshold:** preserving closes about 60% of the 8.4% → 10.6% gap at 0.45 (14 vs
  4 images, McNemar p = 0.03).
- **Matched recall** (0.447): 1.0% vs 1.3% slice false alarms, difference −0.26 points
  [−0.65, 0.00]. Not callable.
- **Only part of the bias goes away for this model** (+0.16 → +0.12). Candidate causes
  for the rest, untested:
  - The output layer's learned weight range, which NEMO's `PACT_Linear.harden_weights`
    resets at the QD stage either way (recorded in `qd_stage_weight_range_changes`).
  - The input staging.

## What this means

1. **Keep the option and make it the default policy for future QAT releases** (Sai's
   call). With it, fake-quant evaluation predicts the chip (bias +0.02 instead of +0.20
   on the champion). That removes a confound from every future model comparison and
   fine-tune.
2. **Do NOT swap the shipped champion app for its preserved twin now.**
   - At matched recall the two are the same detector.
   - Swapping would move the operating point: fewer false alarms and lower recall, exactly
     like raising the bar.
   - The 0.75 bar was tuned in closed-loop flights on the recalibrated chip.
   - The firmware's raw thresholds would also change ({5467, −998, 3} → {2516, −459, 3}
     for the preserved champion).
3. **The two-releases-of-one-model method generalises.** For any future QAT fine-tune,
   release it both ways (about 15 min each) and compare at matched recall.

## Caveats

- Two models, one image sample (the same 1,000 + 771 as Sep 11).
- Chip numbers are ONNX Runtime on the DORY-cleaned graph. The patched DORY/GVSOC match
  it within about 300 raw units (Sep 11), and the gates checked GVSOC-exact on 5 images
  per release.
- The output layer's weight range is not preserved, by NEMO design (see the caveat above).
