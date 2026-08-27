"""Compare FP vs FQ ONNX outputs on real COCO images (mini rep16-style audit).

Runs the floating-point and fake-quantized ONNX exports of hybrid_follow on
the same images and reports per-image and mean drift for the three decoded
outputs (x, size, visibility), using the project's stage-drift warning
thresholds: |dx| > 0.05, |dsize| > 0.05, |dvis-prob| > 0.10.

Usage (from the workspace root, nemoenv python):
  python pytorch_ssd/export/compare_fp_fq_drift.py \
    --fp-onnx  pytorch_ssd/export/hybrid_follow/trained_fp.onnx \
    --fq-onnx  pytorch_ssd/export/hybrid_follow/trained_fq.onnx \
    --images-root pytorch_ssd/data/coco/images/val2017 \
    --ann pytorch_ssd/data/coco/annotations/instances_val2017.json
"""

import argparse
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from utils.coco_follow_regression import COCOFollowRegressionDataset  # noqa: E402
from utils.transforms import get_val_transforms  # noqa: E402

X_SIZE_WARN = 0.05
VIS_WARN = 0.10


def sigmoid(v: float) -> float:
    return 1.0 / (1.0 + np.exp(-v))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fp-onnx", required=True)
    ap.add_argument("--fq-onnx", required=True)
    ap.add_argument("--images-root", required=True)
    ap.add_argument("--ann", required=True)
    ap.add_argument("--num-person", type=int, default=10)
    ap.add_argument("--num-noperson", type=int, default=6)
    ap.add_argument("--vis-thresh", type=float, default=0.5)
    args = ap.parse_args()

    import onnxruntime as ort

    sess_fp = ort.InferenceSession(args.fp_onnx, providers=["CPUExecutionProvider"])
    sess_fq = ort.InferenceSession(args.fq_onnx, providers=["CPUExecutionProvider"])
    in_fp = sess_fp.get_inputs()[0].name
    in_fq = sess_fq.get_inputs()[0].name

    ds = COCOFollowRegressionDataset(
        root=args.images_root,
        ann_file=args.ann,
        transforms=get_val_transforms("hybrid_follow", input_channels=1),
    )

    picked = []
    want_p, want_n = args.num_person, args.num_noperson
    for i in range(len(ds)):
        if want_p <= 0 and want_n <= 0:
            break
        img, target = ds[i]
        visible = float(target["follow_target"][2]) > 0.5
        if visible and want_p > 0:
            picked.append((i, img, target, True))
            want_p -= 1
        elif not visible and want_n > 0:
            picked.append((i, img, target, False))
            want_n -= 1

    rows = []
    for i, img, target, visible in picked:
        x = img.unsqueeze(0).numpy().astype(np.float32)
        fp = sess_fp.run(None, {in_fp: x})[0].reshape(-1)
        fq = sess_fq.run(None, {in_fq: x})[0].reshape(-1)
        fp_vis, fq_vis = sigmoid(fp[2]), sigmoid(fq[2])
        rows.append({
            "idx": i,
            "gt_vis": visible,
            "dx": abs(fp[0] - fq[0]),
            "dsize": abs(fp[1] - fq[1]),
            "dvis": abs(fp_vis - fq_vis),
            "fp": (fp[0], fp[1], fp_vis),
            "fq": (fq[0], fq[1], fq_vis),
            "vis_agree": (fp_vis >= args.vis_thresh) == (fq_vis >= args.vis_thresh),
        })

    print(f"{'idx':>6} {'gt':>3} | {'fp x':>7} {'fq x':>7} {'dx':>6} | "
          f"{'fp sz':>7} {'fq sz':>7} {'dsz':>6} | {'fp vP':>6} {'fq vP':>6} {'dvP':>6} | agree warn")
    n_warn = 0
    for r in rows:
        warn = r["dx"] > X_SIZE_WARN or r["dsize"] > X_SIZE_WARN or r["dvis"] > VIS_WARN
        n_warn += warn
        print(f"{r['idx']:>6} {('P' if r['gt_vis'] else '-'):>3} | "
              f"{r['fp'][0]:>7.3f} {r['fq'][0]:>7.3f} {r['dx']:>6.3f} | "
              f"{r['fp'][1]:>7.3f} {r['fq'][1]:>7.3f} {r['dsize']:>6.3f} | "
              f"{r['fp'][2]:>6.3f} {r['fq'][2]:>6.3f} {r['dvis']:>6.3f} | "
              f"{'yes' if r['vis_agree'] else 'NO':>5} {'WARN' if warn else '':>4}")

    n = len(rows)
    print(f"\nsummary over {n} images "
          f"({sum(1 for r in rows if r['gt_vis'])} person / {sum(1 for r in rows if not r['gt_vis'])} no-person):")
    print(f"  mean |dx|    = {np.mean([r['dx'] for r in rows]):.4f}")
    print(f"  mean |dsize| = {np.mean([r['dsize'] for r in rows]):.4f}")
    print(f"  mean |dvisP| = {np.mean([r['dvis'] for r in rows]):.4f}")
    print(f"  visibility decision agreement: {sum(r['vis_agree'] for r in rows)}/{n}")
    print(f"  images breaching FP->FQ warning thresholds: {n_warn}/{n}")


if __name__ == "__main__":
    main()
