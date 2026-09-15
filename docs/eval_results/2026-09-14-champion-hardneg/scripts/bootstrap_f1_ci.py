"""Bootstrap a 95% CI for deployed-form peak F1, to set the recall-failure bar.

Same model construction and val set as export/sweep_fq_ckpt.py --mode qat, but
it caches per-image visibility probabilities and resamples images with
replacement to get the sampling spread of the peak-F1 statistic.

Usage (nemoenv python, from inside pytorch_ssd):
  ../nemoenv/bin/python docs/eval_results/2026-09-14-champion-hardneg/scripts/bootstrap_f1_ci.py <ckpt.pth>
"""
import sys
from copy import deepcopy
from pathlib import Path

import numpy as np
import torch

DRONE = Path(__file__).resolve().parents[5]
ROOT = DRONE / "pytorch_ssd_unstable"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(DRONE / "pytorch_ssd/export"))
from sweep_fq_ckpt import patch_model_to_graph_compat  # noqa: E402
import nemo  # noqa: E402
from models.follow_model_factory import build_follow_model, follow_model_kwargs_from_metadata  # noqa: E402
from utils.follow_task import decode_follow_outputs  # noqa: E402
from utils.coco_follow_regression import COCOFollowRegressionDataset  # noqa: E402
from utils.transforms import get_val_transforms  # noqa: E402
from torch.utils.data import DataLoader  # noqa: E402

THRESHOLDS = np.arange(0.30, 0.751, 0.05)


def peak_f1(probs, gts):
    best = 0.0
    for t in THRESHOLDS:
        pred = probs >= t
        tp = int((pred & gts).sum()); fp = int((pred & ~gts).sum()); fn = int((~pred & gts).sum())
        prec = tp / max(tp + fp, 1); rec = tp / max(tp + fn, 1)
        f1 = 2 * prec * rec / max(prec + rec, 1e-9)
        best = max(best, f1)
    return best


def main():
    ckpt = Path(sys.argv[1]).resolve()
    payload = torch.load(ckpt, map_location="cpu")
    head = payload["follow_head_type"]
    m = build_follow_model(**follow_model_kwargs_from_metadata(payload)).eval()
    patch_model_to_graph_compat()
    mq = nemo.transform.quantize_pact(deepcopy(m), dummy_input=torch.randn(1, 1, 128, 128)).eval()
    mq.change_precision(bits=8, scale_weights=True, scale_activations=True)
    mq.load_state_dict(payload["state_dict"], strict=False)

    coco = DRONE / "pytorch_ssd/data/coco"
    ds = COCOFollowRegressionDataset(
        root=str(coco / "images/val2017"), ann_file=str(coco / "annotations/instances_val2017.json"),
        transforms=get_val_transforms("hybrid_follow", input_channels=1))
    probs, gts = [], []
    with torch.no_grad():
        for images, targets in DataLoader(ds, batch_size=32, num_workers=0):
            probs.append(decode_follow_outputs(mq(images), head)["visibility_confidence"])
            gts.append(targets["follow_target"][:, 2])
    probs = torch.cat(probs).numpy()
    gts = torch.cat(gts).numpy() > 0.5

    point = peak_f1(probs, gts)
    rng = np.random.default_rng(0)
    n = len(probs)
    boot = np.array([peak_f1(probs[i], gts[i]) for i in (rng.integers(0, n, n) for _ in range(300))])
    lo, hi = np.percentile(boot, [2.5, 97.5])
    print(f"ckpt={ckpt.name} n={n} positives={int(gts.sum())}")
    print(f"peak F1 point estimate = {point:.4f}")
    print(f"bootstrap 95% CI = [{lo:.4f}, {hi:.4f}]  (300 resamples, seed 0)")
    print(f"CI half-width = {(hi - lo) / 2:.4f}; bootstrap sd = {boot.std():.4f}")


if __name__ == "__main__":
    main()
