# Champion + hard-negative mining: buying pet safety without losing the person

**Date:** 2026-09-14 · **Author:** Sai · **Status:** measurement complete, no model promoted

Configuration is exhausted for the champion's pet-chasing failure — both the follower's
confirmation threshold and its release threshold were swept in flight and neither closes
the 0.5 m safety gate (`docs/eval_results/2026-09-13-champion-threshold/`,
`docs/eval_results/2026-09-14-exit-bar/`). This run tests the remaining lever: **training**.
Five epochs of QAT fine-tuning from the champion, with hard-negative mining on from epoch 1,
on a half-skew confuser manifest.

**Result in one line (CORRECTED 2026-09-14 by independent verification — see §0):** at a
*matched operating point* this run bought **no measurable pet-safety gain**. The headline
"44–61% false-alarm cut" below compares each epoch's F1 at one threshold against its
false-alarm rate at a *different* threshold. Held at equal recall, every epoch sits on the
champion's own false-alarm curve. The recall cost, by contrast, is real.

> **Every number on this page is fake-quant (deployed form) PyTorch, not the chip.**
> See "What this run cannot show" below. The chip number awaits Grace's
> `--preserve-qat-alphas` flag on `grace/qat-alpha-preserve`.

---

## 0. Correction — independent verification, 2026-09-14

An independent agent re-ran every number on this page. **All 10 headline measurements
reproduce exactly** (champion 0.8008 / 0.239 / 0.171; all five epochs on both axes; the
manifest shares; the recalibrated reference; the epoch-4 grid clipping). The arithmetic is
sound and the process claims are all corroborated by the training log.

**The interpretation is not.** The table in §4 pairs each epoch's **peak F1**, achieved at
threshold 0.30–0.35, with its **slice FP**, measured at threshold **0.45**. Those are
different operating points. A drone runs at one threshold.

### 0.1 Both axes at a single threshold

| model | thr | F1 | recall | slice FP |
|---|---|---|---|---|
| champion | 0.45 | **0.8008** | 0.822 | **0.239** |
| epoch 2 | 0.30 (its peak-F1 thr) | 0.7964 | 0.841 | **0.263** ← *worse than champion* |
| epoch 2 | 0.45 (its quoted-FP thr) | **0.7751** ← *fails the 0.7948 bar badly* | 0.722 | 0.134 |
| epoch 4 | 0.25 (its wide-grid peak) | 0.7971 | 0.846 | **0.279** ← *worse than champion* |
| epoch 4 | 0.30 | 0.7946 | 0.800 | 0.202 |
| epoch 4 | 0.45 (its quoted-FP thr) | **0.7616** ← *fails the bar badly* | 0.676 | 0.093 |

At the threshold where an epoch earns its quoted F1, its slice FP is **worse** than the
champion's. At the threshold where it earns its quoted 0.093/0.134, its F1 is far below the
pre-registered recall bar. The advertised trade does not exist at any single setting.

### 0.2 Slice FP at matched recall — the apples-to-apples comparison

Same person-finding ability across a row; lower = genuinely safer.

| recall | 0.840 | 0.822 | 0.800 | 0.780 | 0.760 | 0.720 | 0.680 | 0.640 |
|---|---|---|---|---|---|---|---|---|
| champion | 0.285 | **0.239** | 0.213 | 0.189 | 0.171 | 0.135 | 0.108 | 0.093 |
| epoch 2 | 0.263 | **0.239** | 0.197 | 0.176 | 0.161 | 0.132 | 0.102 | 0.089 |
| epoch 4 | 0.266 | **0.240** | 0.204 | 0.183 | 0.171 | 0.123 | 0.093 | 0.078 |
| *confuser ep8* | *0.262* | *0.224* | *0.189* | *0.167* | *0.153* | *0.114* | *0.092* | *0.067* |

**At the champion's own deployment recall (0.822) the gain is +0.000 (epoch 2) and +0.001
(epoch 4) — exactly zero.** Elsewhere the epochs run 0.00–0.02 below the champion,
inconsistently and within noise. The confuser, by contrast, is genuinely below the champion at
*every* recall (−0.014 to −0.026), which shows real pet-specific learning is achievable by
this route — this run simply did not achieve much of it.

### 0.3 The control: the champion's own threshold dial reproduces the gain for free

Dial the champion to the same recall each epoch reaches at 0.45, with **no training at all**:

| epoch @0.45 | recall | its slice FP | champion dialed to same recall | champion's slice FP | training-attributable delta |
|---|---|---|---|---|---|
| ep1 | 0.762 | 0.179 | thr 0.542 | 0.173 | **+0.006** |
| ep2 | 0.722 | 0.134 | thr 0.622 | 0.136 | −0.003 |
| ep3 | 0.719 | 0.131 | thr 0.624 | 0.135 | −0.004 |
| ep4 | 0.676 | 0.093 | thr 0.682 | 0.106 | −0.013 |
| ep5 | 0.721 | 0.132 | thr 0.622 | 0.136 | −0.004 |

Epoch 4's celebrated 0.239 → 0.093 is a 0.146 drop, of which **0.133 is the threshold dial and
0.013 is training.** Paired McNemar on the same 771 slice images: epoch 4 p=0.087, epoch 2
p=0.856 — **neither is significant.** This matters because §1's premise is that configuration
was already exhausted in flight: the threshold dial is the lever the team *already swept and
rejected*, and it delivers essentially this entire result.

### 0.4 The recall cost, by contrast, is real

§5 judges each epoch against the champion's **marginal** bootstrap sd (0.0059). That is the
wrong scale — both models are scored on the *same* 5,000 images, so the decision-relevant
quantity is the **paired** difference, whose sd is roughly half as large:

| epoch | peak F1 | delta | paired sd | 95% CI of delta |
|---|---|---|---|---|
| ep1 | 0.7964 | −0.0045 | 0.0026 | [−0.0095, +0.0007] |
| ep2 | 0.7964 | −0.0044 | 0.0028 | [−0.0094, +0.0019] |
| ep3 | 0.7946 | −0.0062 | 0.0028 | [−0.0113, **−0.0005**] |
| ep4 | 0.7946 | −0.0062 | 0.0031 | [−0.0127, +0.0002] |
| ep5 | 0.7970 | −0.0038 | 0.0024 | [−0.0081, +0.0009] |

Epoch 3 is formally significant; the rest sit at p≈0.03–0.10, and 5/5 fall on the same side
(sign test p=0.031). **So the recall loss is better supported than the safety gain.**

### 0.5 Corrected verdict

On this evidence the run is **a small, real recall loss in exchange for a pet-safety gain that
is not measurable at the champion's operating point.** It does not show that "training moves
what configuration could not" — it shows this particular recipe mostly reproduced the
threshold dial. The design work in §1 (the manifest measurement, the 1.9x correction) and §3b
(the alpha-drop) stand and are valuable; the promotion case does not.

*Verification artifacts are scratch-only and not committed; all commands are reproducible from
the team scripts plus `export/confuser_slice_eval.fq_model`.*

---

## 1. The design decision: which data mix, and why not the confuser's

The Aug 28 confuser manifest (`export/confuser_train_manifest.json`) keeps every person
image, every confuser negative, and only 30% of the boring negatives. Applying it wholesale
was the obvious move and I rejected it, because eight epochs of exactly that recipe produced
the confuser — the model the team declined to ship because it **cannot follow a person at
all** in flight (`docs/eval_results/2026-09-13-champion-vs-confuser/`). The objective here is
"champion, but safer around pets", not "become the confuser".

First, a correction worth recording. I measured what these manifests actually do, and the
skew is milder than the "62% confusers" label suggests:

| negative pool | confuser share | note |
|---|---|---|
| full train2017 (what the champion trained on) | **0.3244** | 17,575 confuser vs 36,597 boring negatives |
| `confuser_train_manifest.json` | **0.6155** | only a **1.9x** enrichment, not 5x |
| this run (`champion_hardneg_mix48_manifest.json`) | **0.4800** | a **1.5x** enrichment |

So the confuser manifest is a 1.9x enrichment of a category that was already a third of
COCO's negatives. That reframes the risk: the confuser's recall collapse cannot be blamed on
the manifest alone — it came from eight epochs at a real learning rate from a different init.

**Decision: a half-skew manifest at 48% confuser negatives**, built by the same structure as
the Aug 28 tool but keeping 52% of the boring negatives instead of 30%.

Justification:

1. **Person images are untouched — all 64,115 of them.** Neither manifest subsamples people.
   The recall risk does not come from throwing away person data; it comes from the loss
   pushing visibility down on animate shapes and that generalizing to humans. A milder
   negative skew reduces that pressure without removing a single positive.
2. **Mining, not the manifest, is the active ingredient.** The Sep 10-11 controls are decisive
   on this: with the *same* confuser manifest, one QAT epoch scored 0.122 slice FP with mining
   and 0.263 without. The manifest only enriches the pool that mining then draws from, so the
   manifest can be diluted while keeping the mechanism that does the work.
3. **Halfway is a real experimental position**, not a hedge: 1.5x the champion's own pet
   exposure versus the confuser recipe's 1.9x.
4. Low learning rate (2e-5), the value that worked on this codebase in the Sep 11 run.

Cost of the choice: results are not directly comparable to the Sep 11 3-epoch table, which
used the full-skew manifest.

## 2. The recall constraint, pre-registered before training started

Recall is a hard constraint. "Materially below" was defined **before the run**, from a
bootstrap of the champion's own peak F1 (300 resamples, seed 0, `scripts/bootstrap_f1_ci.py`):

```
ckpt=CHAMPION_qat_ep3_f1_8008.pth n=5000 positives=2635
peak F1 point estimate = 0.8008
bootstrap 95% CI = [0.7887, 0.8113]  (300 resamples, seed 0)
CI half-width = 0.0113; bootstrap sd = 0.0059
```

> **Pre-registered rule: an epoch FAILS the recall constraint if its deployed-form peak F1
> falls below 0.7948** — one bootstrap standard deviation (0.0060) below the champion's
> 0.8008, measured on the team's standard 0.30–0.75 threshold grid.

That bar lands, by coincidence and usefully, within 0.0001 of the confuser's 0.7947. So it
reads plainly: **an epoch fails if its recall has degraded to confuser territory.**

On the other axis, a meaningful safety gain was set at slice FP @0.45 dropping below 0.20
(≈2 binomial sd below 0.239 at n=771).

## 3. Baseline, reproduced from the champion checkpoint itself

Both team scripts reproduce the published numbers exactly.

```
[fq-sweep] CHAMPION_qat_ep3_f1_8008.pth mode=qat head=xbin9_size_bucket4 epoch=3
[fq-sweep] loaded QAT state (missing=0, unexpected=0)
thresh |   prec recall     f1 | noP FP rate
  0.30 |  0.695  0.891  0.781 |       0.430
  0.35 |  0.724  0.868  0.790 |       0.362
  0.40 |  0.754  0.847  0.798 |       0.300
  0.45 |  0.781  0.822  0.801 |       0.250
  0.50 |  0.803  0.791  0.797 |       0.212
  0.55 |  0.825  0.758  0.790 |       0.176
  0.60 |  0.847  0.731  0.784 |       0.144
  0.65 |  0.872  0.699  0.776 |       0.113
  0.70 |  0.891  0.665  0.761 |       0.089
  0.75 |  0.911  0.619  0.737 |       0.068

DEPLOYED-FORM peak F1 = 0.8008 at threshold 0.45
```

```
training/CHAMPION_qat_ep3_f1_8008.pth [learned QAT alphas] confuser-slice FP:
0.239 @0.45, 0.171 @0.55 (n=771) [baseline 0.239 / 0.171]
```

**Baseline: peak F1 0.8008 @0.45, slice FP 0.239 @0.45 / 0.171 @0.55.** These are the two
numbers every epoch is judged against.

*(Note on the task brief: it asked me to confirm `confuser_slice_eval.py` still reproduces
"0.083 / 0.239". Those are two different models' numbers — 0.239/0.171 is the champion,
0.083/0.052 is the confuser. The champion's pair reproduces exactly.)*

### 3b. The state training actually starts from is NOT the champion

Worth knowing before reading the epoch-1 row. `train.py --init-ckpt` loads the checkpoint into
the **unwrapped** model, so the champion's 59 PACT alpha/range tensors are dropped
(`Loaded init checkpoint: ... unexpected=59` in the training log), and
`enable_quant_aware_finetune()` then re-derives activation ranges by calibrating on 16 batches
of training data. Measured with `scripts/calib_form_ref.py`:

```
[calib-ref] CHAMPION_qat_ep3_f1_8008.pth: loaded FP weights (missing=0, dropped 59 QAT alpha/range tensors)
[calib-ref] recalibrated activations on 32 rep_images
[calib-ref] DEPLOYED-FORM peak F1 = 0.7991 at threshold 0.45
[calib-ref] confuser-slice FP: 0.258 @0.45, 0.184 @0.55 (n=771)
```

So the alpha reset alone costs ~0.0017 F1 and *adds* ~0.019 to the slice FP before a single
gradient step. Part of epoch 1's F1 drop is this reset, not learning. The epoch checkpoints
themselves do carry learned alphas and are scored with `--mode qat`, so the epoch-vs-champion
comparison is apples-to-apples in evaluation form — it is the *trajectory's* starting point
that differs. This is the same mechanism as Grace's chip-side problem, appearing here at init.

## 4. Per-epoch results

Five epochs, 2,600 batches each at batch size 16 (~41,600 samples/epoch), lr 2e-5 cosine,
mining from epoch 1, seed 0. Checkpoint saved every epoch.

> **Read §0 first.** The "peak F1" and "slice FP @0.45" columns below are measured at
> **different thresholds**, so no row describes a deployable configuration. Held at one
> threshold, the trade largely vanishes.

| checkpoint | peak F1 (0.30–0.75 grid) | @thr | slice FP @0.45 | @0.55 | recall bar 0.7948 |
|---|---|---|---|---|---|
| **champion (reference)** | **0.8008** | 0.45 | **0.239** | 0.171 | — |
| champion, recalibrated (training's real start) | 0.7991 | 0.45 | 0.258 | 0.184 | — |
| epoch 1 | 0.7964 | 0.35 | 0.179 | 0.109 | pass |
| **epoch 2** | **0.7964** | 0.30 | **0.134** | 0.096 | **pass** |
| epoch 3 | 0.7946 | 0.30 | 0.131 | 0.087 | fail by 0.0002 |
| **epoch 4** | 0.7946 (**0.7971** wide grid) | 0.30 (0.25) | **0.093** | 0.064 | fail by 0.0002 / pass on wide grid |
| epoch 5 | 0.7970 | 0.30 | 0.132 | 0.086 | pass |
| *confuser ep8 (context, not from this run)* | *0.7947* | — | *0.083* | *0.052* | — |

**The threshold-grid caveat, which matters.** Every fine-tuned epoch peaks at or near 0.30,
the bottom edge of the team's standard grid, while the champion peaks at 0.45 in the grid's
interior. That asymmetry can clip the fine-tunes' scores, so I re-swept from 0.05
(`scripts/extended_sweep.py`):

```
CHAMPION_qat_ep3_f1_8008.pth: narrow(0.30-0.75) peak F1=0.8008 @0.45 | wide(0.05-0.75) peak F1=0.8008 @0.45 (prec=0.781 rec=0.822)
plain_follow_epoch_001.pth:   narrow(0.30-0.75) peak F1=0.7964 @0.35 | wide(0.05-0.75) peak F1=0.7964 @0.35 (prec=0.764 rec=0.831)
plain_follow_epoch_002.pth:   narrow(0.30-0.75) peak F1=0.7964 @0.30 | wide(0.05-0.75) peak F1=0.7964 @0.30 (prec=0.756 rec=0.841)
plain_follow_epoch_003.pth:   narrow(0.30-0.75) peak F1=0.7946 @0.30 | wide(0.05-0.75) peak F1=0.7946 @0.30 (prec=0.758 rec=0.835)
plain_follow_epoch_004.pth:   narrow(0.30-0.75) peak F1=0.7946 @0.30 | wide(0.05-0.75) peak F1=0.7971 @0.25 (prec=0.753 rec=0.846)
plain_follow_epoch_005.pth:   narrow(0.30-0.75) peak F1=0.7970 @0.30 | wide(0.05-0.75) peak F1=0.7970 @0.30 (prec=0.760 rec=0.838)
```

Only **epoch 4** was clipped: its true optimum is 0.7971 at threshold 0.25. Note its recall at
that threshold (0.846) is *higher* than the champion's 0.822 — the F1 gap is precision, not
recall. But 0.25 is outside the grid the team selects deployment thresholds from, and the
in-flight confirm/release sweeps were run at higher values, so **this is not a free rescue**:
using epoch 4 at its true optimum means re-running the in-flight threshold work.

## 5. The trade, stated honestly

- **False-alarm reduction bought.** Best epoch (4): slice FP 0.239 → **0.093 @0.45** (−61%)
  and 0.171 → **0.064 @0.55** (−63%). That is within 0.010 of the confuser's 0.083 — the
  safety property the team wanted, on a model that still carries the champion's recall.
  Conservative pick (epoch 2): 0.239 → 0.134 (−44%).
- **Recall cost paid.** Every epoch landed below 0.8008. On the team's standard grid the cost
  is 0.0044 (epochs 1–2), 0.0062 (epochs 3–4), 0.0038 (epoch 5). All are inside the champion's
  own bootstrap sd of 0.0059, i.e. **the recall cost is small but consistently in one
  direction** — five of five epochs below baseline is not noise even when each gap is.
- **At which epoch.** The FP gain is not monotone: 0.179 → 0.134 → 0.131 → **0.093** → 0.132.
  Epoch 4 is a local best and epoch 5 gave most of it back. A 0.039 swing between adjacent
  epochs of a *seeded* run is ~2.5 binomial sd on n=771, so epoch-to-epoch wobble is larger
  than the measurement noise on either number. **Epoch 4's 0.093 should not be treated as a
  reproducible operating point on the strength of one run.**

**Best checkpoint under the pre-registered rule: epoch 2** (F1 0.7964, pass; FP 0.134, −44%).
~~**Strongest candidate overall: epoch 4**, which dominates epoch 2 on both axes once the
threshold grid is extended (0.7971 vs 0.7964 F1; 0.093 vs 0.134 FP)~~ — but it clears the recall
bar only on that wider grid, which is a post-hoc move I am flagging rather than leaning on.

> **CORRECTED (§0.1):** epoch 4 does *not* dominate on both axes. Its 0.7971 is at threshold
> **0.25** and its 0.093 is at threshold **0.45** — two different operating points. At 0.25 its
> slice FP is 0.279 (worse than the champion's 0.239); at 0.45 its F1 is 0.7616 (far below the
> bar). Neither epoch is a promotion candidate on this evidence.

~~**Verdict: the pet-chasing failure is reachable by training, cheaply, but not for free.**
Configuration could not move it at all; five short epochs moved it 44–61%.~~

> **CORRECTED (§0.5):** the 44–61% figure is threshold movement, not learning. At matched
> recall the gain is ~0 at the champion's operating point, and the champion's own threshold
> dial — already swept in flight and rejected — reproduces almost all of it. What this run
> established is a small but consistent **recall cost**, and that the confuser's genuine
> curve-level gain (§0.2) is the effect worth chasing with a different recipe.

## 6. What this run cannot show

**It cannot show what reaches the chip.** The release pipeline strips learned QAT ranges and
recalibrates from rep_images, which is exactly why the last QAT+mining model matched the plain
confuser on the chip despite a better fake-quant number (Sep 11 entry). Section 3b measures
that same mechanism costing 0.019 slice FP at init, in this run, before any training — so
there is every reason to expect it to eat into the gains above on the way to the chip.

Every number here is **fake-quant / deployed form**. Fixing the strip-and-recalibrate problem
is Grace's `--preserve-qat-alphas` task on `grace/qat-alpha-preserve`, not this one. **The chip
number awaits her flag.** Nothing here should be promoted or flown until it exists.

Also not shown: closed-loop behaviour. Whether a 61% per-frame false-alarm cut actually holds
the 0.5 m gate on the pet scene is a simulator question, and this run did not touch the
simulator.

## 7. Caveats

- **One seeded run.** `--seed 0` throughout, so this is reproducible, but it is a single point
  in seed space. The team's own Sep 11 rule — 3+ repeats before a training result goes in a
  report — is **not** satisfied here. Treat the epoch-4 number as provisional.
- **Short epochs.** 2,600 batches ≈ 41,600 samples ≈ 41% of a pass over the 100,729-image
  manifest, sized to fit the 100-minute budget. Not comparable to a full-manifest epoch.
- **Mining engages at epoch 2 for the sampler.** The loss-side hard-negative reweighting is
  active from epoch 1, but the sampler's boost needs EMA scores that only exist after one
  epoch (`boosted_true_no_person=0` at epoch 1, `13001` at epoch 2). Epoch 1 is therefore a
  weaker form of the recipe than epochs 2–5.
- **Not comparable to the Sep 11 table**, which used the full-skew manifest.
- Per-epoch wall-clock varied 7–20 min purely from CPU contention with the evaluation jobs
  running alongside. Every epoch ran the full 2,600 batches; only the clock differs.

## 8. Exact commands

Build the half-skew manifest:

```bash
cd /Users/saimaruvada/Downloads/drone/pytorch_ssd
../trainenv/bin/python docs/eval_results/2026-09-14-champion-hardneg/scripts/build_mixed_manifest.py \
  --ann data/coco/annotations/instances_train2017.json \
  --out /Users/saimaruvada/Downloads/drone/training/champion_hardneg_mix48_manifest.json \
  --target-confuser-share 0.48 --seed 0
```

Train (note: **nemoenv, not trainenv** — trainenv has no `nemo` package, and running from the
`pytorch_ssd_unstable` cwd otherwise picks up the local `nemo/` directory as a namespace
package and fails with `module 'nemo' has no attribute 'transform'`):

```bash
cd /Users/saimaruvada/Downloads/drone/pytorch_ssd_unstable
../nemoenv/bin/python train.py \
  --model-type plain_follow --follow-head-type xbin9_size_bucket4 \
  --init-ckpt /Users/saimaruvada/Downloads/drone/training/CHAMPION_qat_ep3_f1_8008.pth \
  --quant-aware-finetune --qat-bits 8 --qat-calib-batches 16 \
  --train-sample-manifest /Users/saimaruvada/Downloads/drone/training/champion_hardneg_mix48_manifest.json \
  --epochs 5 --batch_size 16 --num_workers 2 --lr 2e-5 \
  --hard-negative-start-epoch 1 --hard-negative-boost 1.5 --hard-negative-ema 0.70 \
  --seed 0 --max-train-batches 2600 --max-val-batches 25 \
  --output_dir /Users/saimaruvada/Downloads/drone/training/champion_hardneg_mix48
```

Evaluate one epoch on both axes (the team's own tools):

```bash
cd /Users/saimaruvada/Downloads/drone/pytorch_ssd
../nemoenv/bin/python export/sweep_fq_ckpt.py --mode qat \
  --ckpt /Users/saimaruvada/Downloads/drone/training/champion_hardneg_mix48/plain_follow_epoch_004.pth
../nemoenv/bin/python export/confuser_slice_eval.py \
  /Users/saimaruvada/Downloads/drone/training/champion_hardneg_mix48/plain_follow_epoch_004.pth
# wrapper over both: scripts/eval_epoch.sh <ckpt.pth> <outdir>
```

Supporting measurements:

```bash
../nemoenv/bin/python docs/eval_results/2026-09-14-champion-hardneg/scripts/bootstrap_f1_ci.py <ckpt>
../nemoenv/bin/python docs/eval_results/2026-09-14-champion-hardneg/scripts/calib_form_ref.py <ckpt>
../nemoenv/bin/python docs/eval_results/2026-09-14-champion-hardneg/scripts/extended_sweep.py <ckpt> [...]
```

## 9. Artifacts

Checkpoints live **outside the repo** (`*.pth` and `training/` are both gitignored), under
`/Users/saimaruvada/Downloads/drone/training/champion_hardneg_mix48/`. All 281,321 bytes.

| file | SHA-256 |
|---|---|
| `plain_follow_epoch_001.pth` | `5e1aefdb9f2e0c959e1d6e1e400c1bdc2466340a987af2853afc8a53b0b6ea1b` |
| `plain_follow_epoch_002.pth` | `8d78da8efc8bca6a290adeb488e1a151ab155bcbc025a9983b1ab4da1bedcae5` |
| `plain_follow_epoch_003.pth` | `7c0df5f5430dd3a572ea531ff1d2568625eb292b42584a95e94c9d97e0b1d668` |
| `plain_follow_epoch_004.pth` | `522161939d2996c09a9a81285e5091829d8f3b3cd32b4c3ec381c6e40fc1829e` |
| `plain_follow_epoch_005.pth` | `16e5e752b292703a8c6e4e256baa2e2f7876d760f31c17d06027e45e3d6b64ba` |

Inputs, for reproducibility:

| file | SHA-256 |
|---|---|
| `training/CHAMPION_qat_ep3_f1_8008.pth` (init) | `26384b31c672c0995c85be3718583f5c0269b8e2ade8dfb2294c2313ce87a968` |
| `training/champion_hardneg_mix48_manifest.json` | `349382e503407739d28844fb9808bc4214d4caac22f3028621844d8c7b238de7` |

The champion checkpoint is byte-identical to `training/successor_qat/plain_follow_epoch_003.pth`
(same SHA-256), confirming the right init was used.

`train.py` also wrote `plain_follow_best_x.pth` and `plain_follow_best_follow_score.pth` into the
run directory. **Ignore them** — they are selected on val x-error / follow-score, not on either
axis this run is about, and neither was evaluated.

### Committing this folder

`scripts/` and `README.md` commit normally. **Everything in `eval_logs/` is blocked by the
`*.log` rule in `.gitignore` (line 11) and needs `git add -f`:**

```bash
cd /Users/saimaruvada/Downloads/drone/pytorch_ssd
git add docs/eval_results/2026-09-14-champion-hardneg/README.md \
        docs/eval_results/2026-09-14-champion-hardneg/scripts/
git add -f docs/eval_results/2026-09-14-champion-hardneg/eval_logs/
```

The folder is deliberately named `eval_logs/`, not `logs/`: a bare `logs/` in `.gitignore`
matches at any depth and would have hidden the whole directory, the same class of mistake as
the `data/` incident noted at the top of `.gitignore`. Force-add only this folder — do not run
a blanket `git add -f` on the repo.

## 10. Suggested next steps

1. **Wait for `--preserve-qat-alphas`.** Every number here is fake-quant; the chip is the
   decision. Re-run epoch 2 and epoch 4 through the release path once Grace's flag lands.
2. **Repeat epoch 4 with 2 more seeds** before anyone quotes 0.093. The 0.093 → 0.132 bounce
   into epoch 5 says one run does not pin this down.
3. If epoch 4 survives both, **re-run the in-flight confirm/release sweep** for it, since its
   optimum sits at 0.25, below the grid the previous sweeps covered.
4. The pet scene in the simulator is the real test: per-frame false alarms are a proxy for the
   0.5 m gate, not the gate itself.
