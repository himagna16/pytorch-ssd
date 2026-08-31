# Experiment Log

## Aug 31, 2026 — Independent reproduction (Grace)

Grace independently reproduced the promoted QAT champion's silicon-accurate
validation on a second machine: Intel Mac (`x86_64`), macOS 15.7.9. Environment
versions were Python 3.11.16, torch 2.2.2, torchvision 0.17.2 in both
`trainenv` and `nemoenv`. Command, from `pytorch_ssd_unstable` at corrected
`successor-release` commit `59a560e`:

```bash
PLAIN_FOLLOW_VERIFY_PYTHON=../nemoenv/bin/python3 bash run_plain_follow_app_val.sh
```

Exact required results:

```text
plain_follow handoff integrity check: PASS
PASS: 'final' matches exactly.
```

All nine GAP8 layer checks passed, and the 14-value GVSOC tensor matched the
checked-in golden tensor exactly. The first second-machine attempt also caught
a real handoff bug: `*.pth` ignore rules had omitted the checkpoint from commit
`de49ae1`. After the checkpoint was truly added in `59a560e`, the clean recovery
and exact-match validation passed without modifying the deployed
`application/`.

## Aug 28, 2026 — Stacking test: QAT-after-confuser DESTROYS the confuser win (Sai)

One QAT epoch (lr 5e-5, confuser manifest, on confuser-ep8 weights) fully
regressed the animate-false-alarm fix: confuser-slice FP 0.083 → **0.249**
@0.45 (back to the 0.239 pre-fix baseline) while peak F1 stayed ~0.795.
Clean negative result: the confuser resistance lives in decision-boundary
placement that fake-quant training noise erodes within one epoch, even when
training on the same skewed data. Ordering matters and this order is wrong.

Consequences: (1) the two-model choice stands — QAT champion (0.8008,
deployed) vs confuser ep8 (0.7947, 3x safer) — no have-it-all model exists
yet; (2) if the team wants one, the untested recipe is a SINGLE joint run:
QAT from scratch with the confuser manifest from epoch 1 (est. multi-hour,
deferred); (3) note the confuser model ships through the release path with
standard recalibration anyway, and its deployed-form numbers above already
reflect that — so "lacking QAT" costs it nothing at release time that we
haven't already measured.

Compute campaign closed: nothing running. Checkpoint:
training/successor_confuser_qat/plain_follow_epoch_001.pth (archived, not a candidate).

## Aug 28, 2026 — Confuser fine-tune: 3x fewer animate false alarms (Sai)

The confuser-skewed fine-tune (scratch-ep28 init, 8 epochs, negative pool
62% animate confusers via `--train-sample-manifest`) hit its pre-registered
target. All numbers in deployed (fake-quantized) form, epoch-8 checkpoint:

| metric | champion (QAT ep3) | confuser ep8 |
|---|---|---|
| Confuser-slice FP @0.45 | 0.239 | **0.083** (−65%) |
| Confuser-slice FP @0.55 | 0.171 | **0.052** (−70%) |
| Peak F1 | 0.8008 | 0.7947 |
| Overall no-person FP @ peak-F1 threshold | 0.241 (t=0.30) | 0.224 (t=0.30) |

Verdict: 0.6 points of peak F1 bought a **threefold reduction in the
drone-chases-the-cat rate** — for an indoor person-follower, pets and
mannequin-shaped objects are the dominant operational hazard, so this is
the better OPERATIONAL model even though the QAT champion keeps the
leaderboard crown. Decision on which ships is a team call (Sep 2 agenda):
leaderboard champion vs operational candidate, plus threshold.

Follow-up in flight: 1-epoch QAT chunk on confuser ep8 (per the MPS OOM ops
note) to test whether the quantization-robustness and confuser wins stack.
Checkpoint: `training/successor_confuser/plain_follow_epoch_008.pth`.

## Aug 28, 2026 — QAT2 continuation: no improvement; champion confirmed (Sai)

The quant-aware continuation (init from QAT ep3, lr 7e-5, batch 16) was
OOM-killed by macOS a second time, 71% into epoch 2 — NEMO QAT on MPS leaks
memory progressively; batch size does not save it, only wall-clock (~2.25 h)
changes. Yield: epoch 1 only, deployed-form peak F1 **0.7988** — below the
deployed champion's 0.8008. Prediction on record was ~0.803 (70% to beat);
wrong on direction: epoch 1's in-loop F1 (0.7990 @ 0.50) carried no
threshold-sweep bonus this time (its peak already sat at 0.50), and the OOM
removed any chance for epochs 2-3.

Decision: **champion stands** (QAT ep3, 0.8008, deployed and validated).
QAT2 is closed as plateau confirmation — the accuracy axis is squeezed;
further QAT continuations are a poor trade (CPU-only ~4 h/epoch for an
expected ~+0.1). Ops note for any future QAT round on this machine: run
1-epoch chunks with re-init between runs (fresh process = fresh memory), or
rent a Linux GPU box.

Still in flight: the confuser-negatives fine-tune (different axis — targets
the 24% animal false-alarm slice, not peak F1).

## Aug 28, 2026 (night) — CHAMPION DEPLOYED: full pipeline to silicon-accurate PASS (Sai)

The QAT champion (deployed-form F1 0.8008) was pushed through David's entire
release pipeline and is now the repo's promoted, validated GAP8 application —
`run_plain_follow_app_val.sh` (his own entry point, cold start) reports
integrity PASS and a bit-exact 14-value final-tensor match. Branch
`successor-release` on the fork holds the promoted app + all fixes.

The road there (7 pipeline runs, each failing one stage deeper — stage-aware
debugging applied to the pipeline itself):

1. doryenv built on macOS py3.11 with minimal pins (the Linux requirements
   file is unnecessary); +torchvision after run 1.
2. **torch-era ONNX incompatibility (the big one)**: DORY at add0d9c requires
   torch-1.10-style ONNX (numeric tensor names, Cast-chain requant). Fix:
   resurrected David's exact known-good env (py3.8.10 / torch 1.10.2 / nemo
   0.0.8) as a linux/amd64 Docker image (`nemo-legacy-export:py38`) with the
   workspace mounted at its identical host path, wired into the release
   driver via its `--python` seam through `legacy_export_env/legacy_python.sh`.
3. Driver patch: seed ORT-computed golden activations (out_layer*.txt) next
   to the DORY ONNX after quant eval — DORY's HW parser needs them for
   checksums; the legacy flow left them behind implicitly.
4. Portability bug in David's checked-in DORY config: absolute path from his
   WSL machine (`/mnt/c/Users/yxl21/...`). Fixed by pinning config onnx_file
   to the --onnx argument in generate_dory_io_artifacts.py.
5. pulp-nn submodule was at an empty-tree master HEAD; pinned to DORY's
   recorded 9ada4a9.
6. Promoted golden output.txt normalized to bare integers (the integrity
   gate rejects NEMO-style comment headers).

QAT checkpoint handling: David's own `prepare_follow_qat_eval_checkpoint.py`
strips PACT keys; the release path re-quantizes with fresh calibration (16
imgs) — learned alphas do not ship, QAT-shaped weights do. Release metrics
healthy (follow_score 0.354 vs released 0.340). Champion's chip tensor on the
golden image decodes as: visible, centered (x-bin 4), close (size bucket 3).

Every step of the thesis has now been reproduced AND exceeded on team
hardware: better model, same exactness guarantee, pipeline portable off
David's machine for the first time.

## Aug 28, 2026 (evening) — GVSOC validation reproduced: exact final-tensor PASS (Sai)

Installed Docker Desktop (Apple Silicon, Rosetta emulation), pulled David's
pinned image by digest, and ran `run_plain_follow_app_val.sh` on the
`unstable` worktree: integrity gate → container build of the shipped
`application/` → GVSOC simulated-GAP8 execution → tensor compare.

**Result: PASS — exact final-tensor agreement.** All 14 int32 outputs match
the golden file bit-for-bit:
`[4632, 13262, 4633, -2422, -3479, -5390, 2962, -1854, -11170, 5303, -7980, 3540, 4466, -43]`
Decoded per the contract (x-bins 0-8, vis 9, size 10-13): argmax x-bin = 1
(left of center), visibility logit 5303 > 0 (visible), size bucket = 2 —
"person visible, left of center, medium size."

Meaning: every result in the thesis is now independently reproduced on team
hardware, including the runtime endpoint. The Docker/GVSOC lane is proven on
this machine (logs in `pytorch_ssd_unstable/logs/plain_follow_app_validation/`).
Next frontier: push OUR champion (QAT ep3+) through export → DORY codegen →
app regen → this same validation — the step that makes 0.8008 flight-ready.

## Aug 28, 2026 (afternoon) — Error anatomy of the champion; the confuser problem (Sai)

Ran `export/error_analysis_fq.py` on the deployed champion (QAT ep3) over
val2017 @ threshold 0.45: recall 0.822 overall but strongly size-dependent —
**tiny persons 0.649, small 0.806, medium 0.919, large 0.912**. Gallery
inspection shows the misses are mostly tiny background people, partial
slivers, and photos-of-people — LOW operational value for a follow drone
whose target is medium/large in frame (where recall is already 0.91+).
Conclusion: do NOT chase tiny-person recall (would cost input resolution /
GAP8 compute for leaderboard vanity).

The actionable failure is the FALSE POSITIVES: the worst confident false
alarms are **mannequins (P=1.00), dressed teddy bears (0.97-0.98), cats
(0.97), a dog (0.96), cows (0.98)** — animate-shaped non-persons. For a
person-following drone these are the ghost-chase cases (it would follow the
family cat). New metric slice: **FP rate on val2017 confuser negatives
(no-person images containing bird/cat/dog/.../teddy bear, n=771): 0.239 @
0.45, 0.171 @ 0.55.**

Fix queued (runs after QAT2 finishes): retrain with a confuser-skewed
negative pool via David's `--train-sample-manifest` —
`export/build_confuser_manifest.py` keeps all 64k person images + all 17.6k
confuser negatives + 30% of boring negatives (negative pool now 62%
confusers). Success = confuser-FP slice drops materially with overall peak
F1 held. Galleries: `export/error_analysis/`.

## Aug 28, 2026 — QAT run: new deployed-form champion, 0.8008 (Sai)

QAT fine-tune of the F1-record model (scratch ep28) using David's
`--quant-aware-finetune` path: 8-bit PACT training on full train2017,
lr 1e-4. The OS killed the run at epoch 4 (memory pressure — QAT holds
extra model copies; also ~10x slower per step on MPS), but epochs 1-3
checkpointed and epoch 3 was sufficient.

New scoreboard — **deployed form** (fake-quantized, the form that flies),
val2017 peak F1 via `export/sweep_fq_ckpt.py`:

| model | FP form | deployed form | quantization cost |
|---|---|---|---|
| David's released | 0.7910 | 0.7885 | −0.25 |
| Warm-start ep18 | 0.7958 | 0.7958 | **0.00** |
| Scratch ep28 (FP record) | 0.8001 | 0.7946 | −0.55 |
| **QAT ep3 (champion)** | n/a | **0.8008** | gains by construction |

Findings:

1. **QAT ep3 is the overall champion: 0.8008 deployed-form F1**, +1.2 points
   over David's released model in deployed form. Its quantized score even
   exceeds the record model's unquantized 0.8001.
2. **The drift audits predicted the quantization costs exactly**: warm-start
   (16/16 audit) lost 0.00 under quantization; scratch (14/16) lost 0.55;
   David's (15/16) lost 0.25. The rep16 audit is a validated cheap proxy for
   full-set deployed degradation.
3. QAT checkpoints carry learned PACT alphas (load into a `quantize_pact`-
   wrapped model, no calibration needed) — `--mode qat` in the sweep tool.
4. Remaining to call it fully deployable: ONNX/DORY export of the QAT
   model's integer-deployable stage + GVSOC final-tensor check (needs the
   Docker lane), then rep16 overlays for the meeting.

Champion checkpoint (local): `training/successor_qat/plain_follow_epoch_003.pth`.

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

## Aug 28, 2026 (morning) — Campaign complete: both runs beat David; warm-start dominates

Run 2 (from-scratch, 30 ep, his full recipe) finished. Full standings on
val2017 peak F1, with the FP->FQ drift audit (rep16, his calibration set)
as the deployment gate:

| model | peak F1 | drift: x-bin / size / vis |
|---|---|---|
| David's released (ep 28) | 0.7910 | 15/16 / 16/16 / 16/16 |
| Warm-start ep 18 | 0.7958 | **16/16 / 16/16 / 16/16** |
| **From-scratch ep 28** | **0.8001** | 14/16 / 15/16 / 16/16 |

Findings:

1. **Warm-start ep 18 strictly dominates the released model** — higher F1
   AND a perfect quantization audit (more FQ-robust than the model it was
   initialized from). It is the current deployment candidate.
2. **From-scratch ep 28 is the accuracy record (0.8001)** but pays ~1-2
   audit images of FQ robustness. Its safety curve is the best measured:
   matches David's F1-at-0.50 at FP 0.087 vs his 0.111, reaches FP 0.020.
3. **F1-based checkpoint selection is worth real points**: `follow_score`
   picked scratch ep 25 (0.7947); F1 sweep finds ep 28 (0.8001). Selection
   metric choice alone = +0.5 F1.
4. Next moves: QAT fine-tune (`--quant-aware-finetune`) of scratch ep 28 to
   chase 0.80-with-perfect-audit; int8 export + GVSOC of whichever wins;
   overlays for the meeting.

Checkpoints (local): `training/successor_warmstart/plain_follow_epoch_018.pth`,
`training/successor_scratch/plain_follow_epoch_028.pth`. Runs logged in
`pytorch_ssd/training_successor_{warmstart,scratch}.log`.

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
