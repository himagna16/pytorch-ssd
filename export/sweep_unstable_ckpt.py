"""Visibility threshold sweep for any quant-native checkpoint (David's stack).

Loads a checkpoint through the unstable worktree's model factory and decode,
runs full val2017, and prints the precision/recall/F1/no-person-FP sweep —
the successor campaign's scoreboard.

Usage (trainenv python, from inside pytorch_ssd):
  ../trainenv/bin/python export/sweep_unstable_ckpt.py \
    --ckpt ~/Downloads/drone/training/successor_warmstart/plain_follow_best_follow_score.pth
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import DataLoader


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ckpt", required=True)
    ap.add_argument("--unstable-root", default="../pytorch_ssd_unstable")
    ap.add_argument("--coco-root", default="data/coco")
    ap.add_argument("--batch-size", type=int, default=32)
    ap.add_argument("--device", default=None, help="cpu|mps (default: mps if free)")
    args = ap.parse_args()

    root = Path(args.unstable_root).resolve()
    sys.path.insert(0, str(root))
    from models.follow_model_factory import build_follow_model_from_checkpoint
    from utils.follow_task import decode_follow_outputs
    from utils.coco_follow_regression import COCOFollowRegressionDataset
    from utils.transforms import get_val_transforms

    ckpt = Path(args.ckpt).expanduser().resolve()
    payload = torch.load(ckpt, map_location="cpu")
    head = payload.get("follow_head_type")
    print(f"[sweep] {ckpt.name} head={head} epoch={payload.get('epoch')} "
          f"{payload.get('best_metric')}={payload.get('best_metric_value')}")

    device = torch.device(
        args.device if args.device
        else ("mps" if torch.backends.mps.is_available() else "cpu")
    )
    model = build_follow_model_from_checkpoint(ckpt, torch.device("cpu")).eval().to(device)

    coco = Path(args.coco_root).resolve()
    ds = COCOFollowRegressionDataset(
        root=str(coco / "images/val2017"),
        ann_file=str(coco / "annotations/instances_val2017.json"),
        transforms=get_val_transforms("hybrid_follow", input_channels=1),
    )
    loader = DataLoader(ds, batch_size=args.batch_size, num_workers=0)

    probs, gts, nops = [], [], []
    with torch.no_grad():
        for images, targets in loader:
            d = decode_follow_outputs(model(images.to(device)).cpu(), head)
            probs.append(d["visibility_confidence"])
            gts.append(targets["follow_target"][:, 2])
            tnp = targets.get("true_no_person")
            nops.append(tnp.view(-1) if tnp is not None else torch.zeros(images.shape[0]))
    probs = torch.cat(probs).numpy()
    gts = torch.cat(gts).numpy() > 0.5
    nops = torch.cat(nops).numpy() > 0

    print(f"{'thresh':>6} | {'prec':>6} {'recall':>6} {'f1':>6} | {'noP FP rate':>11}")
    best = (0.0, 0.0)
    for t in np.arange(0.30, 0.751, 0.05):
        pred = probs >= t
        tp = int((pred & gts).sum()); fp = int((pred & ~gts).sum()); fn = int((~pred & gts).sum())
        prec = tp / max(tp + fp, 1); rec = tp / max(tp + fn, 1)
        f1 = 2 * prec * rec / max(prec + rec, 1e-9)
        if f1 > best[1]:
            best = (t, f1)
        print(f"{t:>6.2f} | {prec:>6.3f} {rec:>6.3f} {f1:>6.3f} | "
              f"{int((pred & nops).sum()) / max(int(nops.sum()), 1):>11.3f}")
    print(f"\npeak F1 = {best[1]:.4f} at threshold {best[0]:.2f}  (target to beat: 0.7910)")


if __name__ == "__main__":
    main()
