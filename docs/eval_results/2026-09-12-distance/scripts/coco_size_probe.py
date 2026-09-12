"""Does the size head over-read on REAL images with exactly known pixel heights?

Uses COCO val2017 through the model's own validation pipeline
(CenterCropSquare -> Resize 128x128 -> gray), which is byte-for-byte how the
network was trained and evaluated. Ground truth is the label the trainer itself
computes: size = largest_person_box_height / image_height, after the crop.

Reports bucket confusion, signed bias, and - the number that actually drives the
drone - where the model's 1->2 decision boundary really sits.
"""
import argparse, json, math, sys
from pathlib import Path
import numpy as np
import torch

UNSTABLE = Path("/Users/saimaruvada/Downloads/drone/pytorch_ssd_unstable")
sys.path.insert(0, str(UNSTABLE))
from models.follow_model_factory import build_follow_model_from_checkpoint          # noqa: E402
from utils.follow_task import decode_follow_outputs, SIZE_BUCKET4_EDGES             # noqa: E402
from utils.coco_follow_regression import COCOFollowRegressionDataset                # noqa: E402
from utils.transforms import get_val_transforms                                     # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--ckpt", default=str(UNSTABLE / "artifacts/successor_qat_ep3_eval.pth"))
ap.add_argument("--root", default="/Users/saimaruvada/Downloads/drone/pytorch_ssd/data/coco/images/val2017")
ap.add_argument("--ann", default="/Users/saimaruvada/Downloads/drone/pytorch_ssd/data/coco/annotations/instances_val2017.json")
ap.add_argument("--limit", type=int, default=0)
ap.add_argument("--batch", type=int, default=64)
ap.add_argument("--out", default="")
a = ap.parse_args()

ds = COCOFollowRegressionDataset(a.root, a.ann,
                                 transforms=get_val_transforms("plain_follow", 1, (128, 128)),
                                 image_mode="L")
head = torch.load(a.ckpt, map_location="cpu").get("follow_head_type")
model = build_follow_model_from_checkpoint(Path(a.ckpt), torch.device("cpu")).eval()
print(f"ckpt {Path(a.ckpt).name}  head {head}  images {len(ds)}")

def collate(b):
    imgs = torch.stack([x[0] for x in b])
    tgt = torch.stack([x[1]["follow_target"] for x in b])
    return imgs, tgt

idx = list(range(len(ds)))
if a.limit:
    idx = idx[:a.limit]
sub = torch.utils.data.Subset(ds, idx)
dl = torch.utils.data.DataLoader(sub, batch_size=a.batch, shuffle=False, num_workers=0,
                                 collate_fn=collate)

gt_sizes, pred_sizes, pred_bkt, vis_conf, gt_vis = [], [], [], [], []
with torch.no_grad():
    for i, (imgs, tgt) in enumerate(dl):
        dec = decode_follow_outputs(model(imgs), head)
        gt_sizes.append(tgt[:, 1].numpy())
        gt_vis.append(tgt[:, 2].numpy())
        pred_sizes.append(dec["size_value"].numpy())
        pred_bkt.append(dec["size_bucket_index"].numpy())
        vis_conf.append(dec["visibility_confidence"].numpy())
        if i % 20 == 0:
            print(f"  batch {i}", flush=True)

gt = np.concatenate(gt_sizes); pv = np.concatenate(pred_sizes)
pb = np.concatenate(pred_bkt); vc = np.concatenate(vis_conf); gv = np.concatenate(gt_vis)
np.savez(a.out or "/dev/null", gt=gt, pred=pv, bkt=pb, conf=vc, vis=gv) if a.out else None

def bucketize(v):
    return np.clip(np.digitize(v, SIZE_BUCKET4_EDGES[1:-1], right=False), 0, 3)

def report(name, mask):
    g, p, b = gt[mask], pv[mask], pb[mask]
    if g.size == 0:
        print(f"{name}: no samples"); return
    gb = bucketize(g)
    print(f"\n=== {name}  (n={g.size}) ===")
    print(f"  bucket exact match : {np.mean(gb == b):.4f}")
    print(f"  mean GT size       : {g.mean():.4f}")
    print(f"  mean decoded size  : {p.mean():.4f}")
    print(f"  mean signed error  : {np.mean(p - g):+.4f}   (decoded - truth)")
    print(f"  median decoded/GT  : {np.median(p / np.maximum(g, 1e-6)):.4f}")
    print(f"  mean bucket offset : {np.mean(b.astype(float) - gb):+.4f}")
    print("  confusion  rows=GT bucket, cols=pred bucket")
    cm = np.zeros((4, 4), int)
    for i in range(4):
        for j in range(4):
            cm[i, j] = int(np.sum((gb == i) & (b == j)))
    print("            pred0  pred1  pred2  pred3    (row %)")
    for i in range(4):
        tot = cm[i].sum()
        pct = "  ".join(f"{100*cm[i,j]/tot:5.1f}" if tot else "   - " for j in range(4))
        print(f"     GT{i}  {cm[i,0]:6d} {cm[i,1]:6d} {cm[i,2]:6d} {cm[i,3]:6d}   {pct}")
    # where does the 1->2 boundary really sit? P(pred>=2) as a function of GT size
    print("  P(pred bucket >= 2) by true size decile-ish bin  (true edge is 0.500)")
    edges = np.arange(0.20, 0.85, 0.05)
    for lo, hi in zip(edges[:-1], edges[1:]):
        sel = (g >= lo) & (g < hi)
        if sel.sum() >= 10:
            print(f"     size {lo:.2f}-{hi:.2f}: n={sel.sum():5d}  P={np.mean(b[sel] >= 2):.3f}")
    # 50% crossing
    xs, ps = [], []
    for lo, hi in zip(edges[:-1], edges[1:]):
        sel = (g >= lo) & (g < hi)
        if sel.sum() >= 10:
            xs.append(0.5 * (lo + hi)); ps.append(np.mean(b[sel] >= 2))
    xs, ps = np.array(xs), np.array(ps)
    cross = None
    for k in range(len(xs) - 1):
        if ps[k] < 0.5 <= ps[k + 1]:
            cross = xs[k] + (0.5 - ps[k]) * (xs[k + 1] - xs[k]) / (ps[k + 1] - ps[k])
    if cross:
        print(f"  --> effective 1->2 boundary at true size {cross:.3f} "
              f"(nominal 0.500; over-read {0.500/cross:.3f}x)")
        print(f"      a 1.7 m person: model calls bucket 2 from {1.7/(2*cross*math.tan(math.radians(35))):.2f} m "
              f"(nominal 2.43 m)")

visible = gv > 0.5
report("all images with a person box", visible)
report("person box >= 25% of frame height (the follower's regime)", visible & (gt >= 0.25))
report("single dominant person, size 0.25-0.85", visible & (gt >= 0.25) & (gt <= 0.85))
