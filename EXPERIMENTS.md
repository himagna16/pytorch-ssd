# Experiment Log

## Aug 28, 2026 (overnight) — Successor Run 1: David's model beaten (Sai)

Warm-start fine-tune of David's released checkpoint using HIS full recipe
(worktree `successor` branch: flip aug, weighted losses vis2.0/x1.0/size0.3/
res0.5, hard negatives from ep 4, visible-fraction 0.6) on full train2017,
20 epochs, lr 3e-4, batch 32, MPS.

**Result: new project best — peak F1 0.7958 (epoch 18, threshold 0.35) vs
David's released 0.7910.** Robust, not a lucky epoch: every checkpoint from
epoch 15 on beats 0.791 (ep15 .7923, ep16 .7927, ep17 .7942, ep19 .7937,
ep20 .7935). Calibration improved across the curve too: at threshold 0.50
the champion gives F1 0.773 @ FP rate 0.117 vs David's 0.757 @ 0.111, and at
0.55 it's 0.760 @ 0.090 vs his 0.740 @ 0.086 — ~+1.5-2 F1 points at matched
safety everywhere in the useful range.

Champion checkpoint (local): `training/successor_warmstart/plain_follow_epoch_018.pth`.
Note: his `follow_score` selection picked epoch 18 too — selection metrics
agree this round. Run 2 (from-scratch, 30 ep) still training; QAT fine-tune
of the champion is the queued follow-up, then FP->FQ drift audit + int8
export before calling it deployable.

## Aug 27, 2026 (night) — David's handoff verified + toolchain convergence (Sai)

David published the full reproduction material (`unstable` branch + private
data ZIP + separate crazyflie-ssd repo). Ingested tonight; `unstable` is
mounted as a sibling worktree (`../pytorch_ssd_unstable`) and preserved on
our fork as branch `david-unstable`. His SHA-256 integrity gate
(`tools/verify_plain_follow_handoff.py`): **PASS**.

**Reimplementation scorecard** (our thesis-text reconstruction vs his originals):

| Aspect | Ours | David's | Verdict |
|---|---|---|---|
| x bins | 9 uniform over [-1,1] | `linspace(-1,1,10)` | identical (centers match to fp32) |
| size buckets | 4 uniform over [0,1] | (0,.25,.5,.75,1) | identical |
| Output layout | x 0-8, size 9-12, vis 13 | **x 0-8, vis 9, size 10-13** | DIFFERENT — his is the deployed int32 contract |
| Backbone | 4 stages to 80ch (185K params) | 3 stages to 48ch, stem-mode variants | different scale, same straight-through idea |
| Loss | equal-weight sum | staged phases w/ active loss weights, x-residual + neg-vis terms | his is richer (DroNet-style weighting we'd flagged as missing) |

**Toolchain convergence test** — his released `plain_follow_best_follow_score.pth`
(epoch 28) through OUR drift audit, calibrated on HIS `data/rep_images`, on HIS
rep16 diagnostic set: x-bin preserved **15/16**, size bucket **16/16**,
visibility **16/16**. The thesis's own deploy-side audit reported 15/16 x-bin —
two independently built toolchains agree on the same artifact. The one flip
(`09_visible_000000436738.jpg`) jumps bin 4→1 (non-adjacent) — the known hard
image. `16_negative_000000006723.jpg` is a standing false positive (vis 0.56 on
a no-person image) in both FP and FQ.

**Head-to-head on val2017 visibility @ threshold 0.5** (same 5,000 images,
each model with its own decode):

| | precision | recall | F1 | no-person FP rate |
|---|---|---|---|---|
| David's released (ep 28, staged loss) | **0.870** | 0.669 | 0.757 | **0.111** |
| Ours full-COCO (ep 10, equal weights) | 0.792 | **0.765** | **0.778** | 0.222 |

Neither dominates: his model is the *safer* one (half the ghost-follow rate,
precision-leaning — consistent with `follow_score` checkpoint selection and
his negative-visibility loss term); ours is more *sensitive* (finds more
people, higher balanced F1). At a fixed default threshold these are different
operating points, not different quality tiers — a fair fight needs a
threshold sweep on both and comparison at matched FP rate — done, below.

**Matched sweeps** (val2017, both models, thresholds 0.30–0.75): peak F1 is
nearly identical — David's 0.791 (t=0.30) vs ours 0.785 (t=0.40) — but
David's curve is better *calibrated*: at any matched no-person FP rate his F1
is ~0.5–1 point higher, and his curve reaches FP rates (0.03–0.09) ours never
touches in range. Verdict: his released checkpoint is the honest baseline to
beat; our 10-epoch equal-weights run lands within ~1 point of a 28-epoch
staged-loss run, so adopting his loss recipe + more epochs should exceed it.
Next experiment: train with David's stack (his train.py + phases) on full
COCO — the "successor run."

**Environment ground truth (from David)**: validated deployment came from
Python 3.8.10 + torch 1.10.2 + pytorch-nemo 0.0.8 @ 5ea3338; torch 2.x is a
compatibility path — explains the residual-add tracer difference we patched.
GVSOC container pinned by digest in `application/validation/manifest.json`.

## Aug 27, 2026 — Full-dataset retrain + definitive drift audits (Sai)

Both models retrained on full COCO train2017 (118,287 images, 10 epochs,
batch 32, MPS ~8 it/s), validated on held-out val2017 — these replace the
Aug 26 bootstrap numbers, which were inflated by train/val leakage.

| | hybrid_follow (scalar) | plain_follow (bin) |
|---|---|---|
| Val visibility F1 | 0.765 (best ep 9) | **0.778** (best ep 10, still improving) |
| No-person FP rate | 0.225 | 0.222 |
| FP->FQ warning breaches | 4/16 images | decoded x-bin 15/16 exact, 16/16 adjacent |
| Size output under FQ | (part of breaches above) | bucket preserved 13/16 |
| Visibility agreement | 16/16 | 16/16 |

**Findings**

1. **plain_follow now beats hybrid_follow on task quality with 45% of the
   parameters** (186K vs 412K) — the "bin head trades accuracy for
   robustness" worry did not materialize at this scale.
2. **The bin-robustness result survives a properly trained model**: x-bin
   predictions now span 5 different bins across the 16 audit images (COCO
   subjects are genuinely center-biased, so bin 4 still dominates) and the
   decoded x command survived quantization on 15/16 exactly, 16/16 within
   one bin. The scalar model breached drift warnings on 4/16.
3. **New observation — coarse buckets are not automatically safe**: the
   4-bucket size output flipped on 3/16 images. Discrete outputs protect
   decisions only when predictions sit away from bucket BOUNDARIES; with
   only 4 wide buckets, boundary-adjacent predictions are common. Candidate
   fixes: more size bins, or boundary-aware training (margin loss), or
   hysteresis on the decoded size as well.
4. Visibility agreed 16/16 for both models this round — consistent with the
   threshold sweep: ~10% of images sit in the flip-risk band, so a 16-image
   sample sometimes contains zero flips. Population-level exposure is the
   right lens, not single audits.

**Artifacts**: `training/{plain,hybrid}_follow_full/` best checkpoints
(local), `export/overlays_{plain,hybrid}_full.png`,
`export/plain_follow/plain_follow_full_quant.onnx`,
`export/hybrid_follow/hybrid_follow_full_quant.onnx`,
`export/plain_follow/full_model_drift_audit.txt`.

## Aug 26, 2026 — Scalar vs bin head under fake quantization (Sai)

**Question**: does the thesis's core claim — bin-based follow heads preserve
decoded commands under quantization better than scalar heads — reproduce on
models we train ourselves?

**Setup**: both models trained 10 epochs on COCO val2017 (5,000 images, used
for train and val — a bootstrap-quality run, not a benchmark), batch 16,
SGD lr 1e-3 cosine, CPU. Drift measured FP -> FQ (8-bit, NEMO fake-quant,
32 real calibration images) with `export/compare_fp_fq_torch.py` on 16 fixed
images (10 person / 6 no-person), thresholds from the thesis: |dx|>0.05,
|dsize|>0.05, |dvisP|>0.10.

| | hybrid_follow (scalar, residual) | plain_follow (bin, straight-through) |
|---|---|---|
| Params / int8 size | 412K / 1.6 MB | 186K / 0.76 MB |
| Val visibility F1 (10 ep) | 0.836 | 0.693 |
| No-person FP rate | 0.166 | ~0.44 |
| NEMO ID export | needed eps_in_list seeding patch (8 residual adds unresolved) | clean — zero patches, zero warnings |
| FP->FQ drift | 6/16 images breach warning thresholds | decoded x-bin 16/16 preserved, size bucket 16/16 |
| Visibility decision agreement | 15/16 (one near-threshold flip) | 15/16 (one near-threshold flip) |

**Findings**

1. **Export cleanliness reproduces exactly.** The residual (hybrid) graph
   needed a custom patch to export at all on torch 2.x; the straight-through
   graph exported with zero special handling. Matches thesis Table 3's
   patch-burden contrast.
2. **Decoded bin commands survive quantization; continuous outputs drift.**
   Matches thesis Table 7 directionally.
3. **Visibility is the fragile output for BOTH heads** — each audit had
   exactly one image flip its visibility decision, both within ~0.03 of the
   0.5 threshold. This is the thesis's asymmetry: x/size decode through
   argmax, visibility still crosses a continuous threshold. Candidate fixes
   to discuss: temporal filtering on-device (PULP-DroNet low-pass, alpha=0.7),
   hysteresis (two thresholds), or a 2-class softmax visibility head.

**Caveats (important)**

- Our plain_follow is UNDERTRAINED and predicts the center x-bin on most
  images; low prediction entropy inflates "16/16 preserved". Retrain on full
  train2017 before quoting this number.
- plain_follow here is a REIMPLEMENTATION from the thesis text (David's
  original is not in the public repo). Bin/bucket edges assumed uniform;
  confirm against his code.
- 10 epochs, val2017-as-train: model quality numbers are not comparable to
  the thesis's.

**Artifacts**: `export/overlays_hybrid.png`, `export/overlays_plain.png`,
`export/hybrid_follow/hybrid_follow_quant_sim.onnx` (1.6 MB),
`export/plain_follow/plain_follow_quant_sim.onnx` (0.76 MB), audit tool
`export/compare_fp_fq_torch.py`, visualizer
`export/visualize_follow_predictions.py`.
