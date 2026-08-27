# Private Data Bundle

Unzip this archive at the root of the `pytorch_ssd` checkout. It preserves the
repository-relative paths expected by the historical scripts.

Included:

- `data/rep_images/`: representative NEMO calibration PNGs
- `logs/hybrid_follow_val/1_real_image_validation/input_sets/representative16_20260324/`:
  16 COCO val2017 diagnostic images
- `training/hybrid_follow/checkpoint_eval_best_follow_score_20260324_152203/`:
  retained checkpoint diagnostic reports and overlays

Not included:

- full COCO train2017/val2017 image archives
- full COCO annotations
- training epoch checkpoints other than the two handoff checkpoints committed
  under `artifacts/handoff_2026_08/checkpoints/`

The image files are derived from the local COCO working set. Keep this bundle
as project data rather than committing it to the source repository. Refer to
<https://cocodataset.org/> for the original dataset downloads and terms.
