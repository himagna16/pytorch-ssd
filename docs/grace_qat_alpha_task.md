# Grace — ship the learned QAT ranges (`--preserve-qat-alphas`)

**Agent instructions.** Your user is Grace. This is the task she designed
herself in her Aug 31 entry in `EXPERIMENTS.md` (branch
`grace/qat-alpha-preserve`). Follow `TEAMWORK.md`: pull first, push at the
end, log results in `EXPERIMENTS.md`, decisions in `DECISIONS.md`. Work on a
`grace/...` branch and open a PR, because this changes a shared contract (the
release pipeline). Stop and report to Sai if a milestone fails for more than
30 minutes.

## Why this matters now

When a model is trained with quantization in the loop (QAT), it learns its own
activation ranges. The release pipeline throws them away and recalibrates, so
the training gain never reaches the chip. Measured on Sep 11:

| confuser model, trained with QAT and hard-negative mining | false alarms on pets and mannequins |
|---|---|
| in fake-quant form, with its learned ranges | 8.4% |
| after the release recalibrates (what runs on the chip) | 10.6% |

That 2-point gap is the difference between a model that matches the original
confuser and one that does not. Grace's Aug 31 study measured the same effect
on the champion: learned ranges gave a consistently lower false-alarm rate at
the same threshold, 0.250 against 0.266.

## Milestone 0 — environment

Follow `AGENT_SETUP.md`. Note Stage 8.2: **apply `tools/dory_patches/` to the
DORY checkout before any code generation.** Without it, generated chip apps
have every negative weight zeroed. Run
`export/check_semantic_release_gates.py` after every release.

**VERIFY**: `tools/dory_patches/apply.sh <dory>` prints "applied" or "already
applied" for all three patches.

## Milestone 1 — implement the flag

Grace's own five steps, from her Aug 31 entry:

1. Add `--preserve-qat-alphas` in `export/run_plain_follow_release.py::parse_args`,
   validate QAT provenance in `resolve_context`, and pass it through the
   `quant_command` that calls `evaluate_quant_native_follow.py`.
2. Add the matching flag in `evaluate_quant_native_follow.py::parse_args` and
   branch inside `build_quantized_models`. The preserve branch builds the
   ordinary model from checkpoint metadata, wraps it with
   `nemo.transform.quantize_pact`, calls `change_precision`, and loads the full
   QAT state, the way `sweep_fq_ckpt.py --mode qat` does.
3. In that branch, skip `run_activation_calibration` (it calls
   `reset_alpha_act`) and any weight-alpha reset. Build FQ, QD and ID from one
   canonical learned-alpha state.
4. Do not run `prepare_follow_qat_eval_checkpoint.py` on the preserved path;
   keep stripping and recalibration as the default.
5. Record provenance (`learned_qat` vs `calibrated`), the source checkpoint's
   SHA-256, alpha-key load counts and calibration-skipped status in the release
   summary and the promoted validation manifest.

**VERIFY**: with the flag off, a release is byte-identical to today's; with it
on, `quant_eval/summary.json` records the learned-alpha provenance.

## Milestone 2 — release and gate

Release the QAT confuser checkpoint
`training/successor_confuser_qat_hn3/plain_follow_epoch_002.pth` both ways, with
a 576-image pack, no promotion:

```bash
bash run_plain_follow.sh --ckpt <ckpt> --output-dir logs/<name> \
  --hard-case-dir logs/hybrid_follow_val/1_real_image_validation/input_sets/representative16_20260324 \
  --python ../pytorch_ssd/tools/legacy_export_env/legacy_python.sh \
  --expanded-pack-extra-count 560 --skip-application-promotion --overwrite
python3 export/run_gvsoc_multi_image.py logs/<name>
python3 export/check_semantic_release_gates.py logs/<name>
```

**VERIFY**: both releases pass all five gates. Report the chip-side
pet/mannequin false-alarm rate for each. The target is to get the chip number
near the 8.4% the model reaches in fake-quant form.

## Milestone 3 — fair comparison

Use the unbiased evaluation in `docs/eval_results/2026-09-11-unbiased/`
(`infer_ep2.py`, `analyze_4.py` show how to add a model): 1,000 random val2017
images plus the 771-image confuser slice. Report, for preserved vs
recalibrated: visibility agreement with the float model, confident
contradictions, F1 at 0.5 and 0.7, empty-scene false alarms, and slice false
alarms, each with its interval.

## Report back

Append a dated entry to `EXPERIMENTS.md` with the numbers and a
recommendation: should the team ship preserved ranges, and for which model?
Open the PR and tell Sai. Do not promote an application; that is a team
decision.
