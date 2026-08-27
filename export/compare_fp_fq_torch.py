"""FP vs FQ drift audit in pure PyTorch (no ONNX export needed).

Builds the fake-quantized (FQ) model from a checkpoint using the exact same
NEMO calls as export_nemo_quant.py (quantize_pact -> change_precision ->
statistics_act calibration -> reset_alpha), then compares FP vs FQ outputs
on real COCO images. This measures the thesis's first stage boundary
(FP -> FQ) directly at the PyTorch level.

Warning thresholds match the project's stage-drift criteria:
|dx| > 0.05, |dsize| > 0.05, |dvis-prob| > 0.10.

Usage (from inside pytorch_ssd, nemoenv python):
  ../nemoenv/bin/python export/compare_fp_fq_torch.py \
    --ckpt training/hybrid_follow/<checkpoint>.pth \
    --images-root data/coco/images/val2017 \
    --ann data/coco/annotations/instances_val2017.json
"""

import argparse
import sys
from copy import deepcopy
from pathlib import Path

import numpy as np
import torch

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from models.hybrid_follow_net import HybridFollowNet  # noqa: E402
from utils.coco_follow_regression import COCOFollowRegressionDataset  # noqa: E402
from utils.transforms import get_val_transforms  # noqa: E402

X_SIZE_WARN = 0.05
VIS_WARN = 0.10


def build_fq(model_fp: torch.nn.Module, calib_imgs, bits: int = 8) -> torch.nn.Module:
    import nemo

    # NEMO passes kwargs removed from modern torch.onnx internals; reuse the
    # compatibility shim from the export script.
    from export_nemo_quant import patch_model_to_graph_compat
    patch_model_to_graph_compat()

    dummy_input = torch.randn(1, 1, 128, 128)
    model_q = nemo.transform.quantize_pact(deepcopy(model_fp), dummy_input=dummy_input)
    model_q.eval()
    model_q.change_precision(bits=bits, scale_weights=True, scale_activations=True)
    with torch.no_grad():
        with model_q.statistics_act():
            for x in calib_imgs:
                _ = model_q(x.unsqueeze(0))
    model_q.reset_alpha_act()
    try:
        model_q.reset_alpha_weights()
    except Exception:
        pass
    return model_q


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ckpt", required=True)
    ap.add_argument("--images-root", required=True)
    ap.add_argument("--ann", required=True)
    ap.add_argument("--num-person", type=int, default=10)
    ap.add_argument("--num-noperson", type=int, default=6)
    ap.add_argument("--calib-batches", type=int, default=32)
    ap.add_argument("--bits", type=int, default=8)
    ap.add_argument("--vis-thresh", type=float, default=0.5)
    args = ap.parse_args()

    state = torch.load(args.ckpt, map_location="cpu")
    model_fp = HybridFollowNet(input_channels=1, image_size=(128, 128))
    model_fp.load_state_dict(state["state_dict"])
    model_fp.eval()

    ds = COCOFollowRegressionDataset(
        root=args.images_root,
        ann_file=args.ann,
        transforms=get_val_transforms("hybrid_follow", input_channels=1),
    )

    # Calibration images come AFTER the eval set to avoid reusing them.
    eval_picked, calib_imgs = [], []
    want_p, want_n = args.num_person, args.num_noperson
    for i in range(len(ds)):
        img, target = ds[i]
        visible = float(target["follow_target"][2]) > 0.5
        if visible and want_p > 0:
            eval_picked.append((i, img, True))
            want_p -= 1
        elif not visible and want_n > 0:
            eval_picked.append((i, img, False))
            want_n -= 1
        elif len(calib_imgs) < args.calib_batches:
            calib_imgs.append(img)
        if want_p <= 0 and want_n <= 0 and len(calib_imgs) >= args.calib_batches:
            break

    print(f"[drift] building FQ model ({args.bits} bits, {len(calib_imgs)} calib images)...")
    model_fq = build_fq(model_fp, calib_imgs, bits=args.bits)

    rows = []
    with torch.no_grad():
        for i, img, visible in eval_picked:
            x = img.unsqueeze(0)
            fp = model_fp(x).reshape(-1)
            fq = model_fq(x).reshape(-1)
            fp_vis = torch.sigmoid(fp[2]).item()
            fq_vis = torch.sigmoid(fq[2]).item()
            rows.append({
                "idx": i,
                "gt_vis": visible,
                "fp": (fp[0].item(), fp[1].item(), fp_vis),
                "fq": (fq[0].item(), fq[1].item(), fq_vis),
                "dx": abs(fp[0].item() - fq[0].item()),
                "dsize": abs(fp[1].item() - fq[1].item()),
                "dvis": abs(fp_vis - fq_vis),
                "vis_agree": (fp_vis >= args.vis_thresh) == (fq_vis >= args.vis_thresh),
            })

    print(f"\n{'idx':>6} {'gt':>3} | {'fp x':>7} {'fq x':>7} {'dx':>6} | "
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
