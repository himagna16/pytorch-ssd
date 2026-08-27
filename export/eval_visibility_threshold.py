"""Visibility threshold selection + margin analysis over the full val set.

Sweeps the visibility decision threshold and reports precision / recall / F1 /
no-person false-positive rate at each, plus a margin histogram: how many
images sit close to the chosen threshold. Images inside the margin band are
the ones whose visibility decision can flip under quantization drift (the
FP->FQ audits each saw exactly one such flip).

Usage (from inside pytorch_ssd, trainenv python):
  ../trainenv/bin/python export/eval_visibility_threshold.py \
    --model-type hybrid_follow \
    --ckpt training/hybrid_follow/hybrid_follow_best_visibility.pth \
    --images-root data/coco/images/val2017 \
    --ann data/coco/annotations/instances_val2017.json
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import DataLoader

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from models.hybrid_follow_net import HybridFollowNet  # noqa: E402
from models.plain_follow_net import (  # noqa: E402
    NUM_SIZE_BUCKETS,
    NUM_X_BINS,
    PlainFollowNet,
)
from utils.coco_follow_regression import COCOFollowRegressionDataset  # noqa: E402
from utils.transforms import get_val_transforms  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model-type", default="hybrid_follow",
                    choices=["hybrid_follow", "plain_follow"])
    ap.add_argument("--ckpt", required=True)
    ap.add_argument("--images-root", required=True)
    ap.add_argument("--ann", required=True)
    ap.add_argument("--batch-size", type=int, default=32)
    ap.add_argument("--num-workers", type=int, default=4)
    ap.add_argument("--limit", type=int, default=0, help="0 = full set")
    args = ap.parse_args()

    state = torch.load(args.ckpt, map_location="cpu")
    model_cls = HybridFollowNet if args.model_type == "hybrid_follow" else PlainFollowNet
    model = model_cls(input_channels=1, image_size=(128, 128))
    model.load_state_dict(state["state_dict"])
    model.eval()

    vis_index = 2 if args.model_type == "hybrid_follow" else NUM_X_BINS + NUM_SIZE_BUCKETS

    ds = COCOFollowRegressionDataset(
        root=args.images_root,
        ann_file=args.ann,
        transforms=get_val_transforms("hybrid_follow", input_channels=1),
    )
    if args.limit:
        ds = torch.utils.data.Subset(ds, range(min(args.limit, len(ds))))

    loader = DataLoader(ds, batch_size=args.batch_size, shuffle=False,
                        num_workers=args.num_workers)

    probs, gts = [], []
    with torch.no_grad():
        for images, targets in loader:
            out = model(images)
            probs.append(torch.sigmoid(out[:, vis_index]))
            gts.append(targets["follow_target"][:, 2])
    probs = torch.cat(probs).numpy()
    gts = (torch.cat(gts).numpy() > 0.5)

    n = len(probs)
    n_pos = int(gts.sum())
    n_neg = n - n_pos
    print(f"{args.model_type}: {n} images ({n_pos} person / {n_neg} no-person)\n")

    print(f"{'thresh':>6} | {'prec':>6} {'recall':>6} {'f1':>6} | {'noP FP rate':>11} | {'in ±0.05':>8} {'in ±0.10':>8}")
    best = None
    for t in np.arange(0.30, 0.751, 0.05):
        pred = probs >= t
        tp = int((pred & gts).sum())
        fp = int((pred & ~gts).sum())
        fn = int((~pred & gts).sum())
        prec = tp / max(tp + fp, 1)
        rec = tp / max(tp + fn, 1)
        f1 = 2 * prec * rec / max(prec + rec, 1e-9)
        nofp = fp / max(n_neg, 1)
        band05 = int((np.abs(probs - t) < 0.05).sum())
        band10 = int((np.abs(probs - t) < 0.10).sum())
        marker = ""
        if best is None or f1 > best[1]:
            best = (t, f1)
        print(f"{t:>6.2f} | {prec:>6.3f} {rec:>6.3f} {f1:>6.3f} | {nofp:>11.3f} | {band05:>8} {band10:>8}")

    print(f"\nbest F1 at threshold {best[0]:.2f} ({best[1]:.3f})")
    print("\nmargin analysis (how exposed are decisions to quantization drift?):")
    for band in (0.02, 0.05, 0.10):
        cnt = int((np.abs(probs - 0.5) < band).sum())
        print(f"  images with |visP - 0.5| < {band:.2f}: {cnt}/{n} ({100*cnt/n:.1f}%)")
    print("\n(the FP->FQ audit moved vis probs by ~0.02-0.03 on average — images in the")
    print(" ±0.02-0.05 bands are the population at risk of decision flips after deploy.")
    print(" hysteresis idea: declare visible above 0.55, lost below 0.45 — kills flips")
    print(" for everything outside the ±0.05 band at the cost of slower transitions.)")


if __name__ == "__main__":
    main()
