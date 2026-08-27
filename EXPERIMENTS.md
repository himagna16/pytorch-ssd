# Experiment Log

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
