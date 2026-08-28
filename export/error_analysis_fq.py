"""Error analysis for a deployed-form (QAT/fake-quant) checkpoint on val2017.

Answers "WHERE does the champion fail?" before we spend compute fixing it:
  - visibility recall bucketed by ground-truth person size (missing far people?)
  - false-positive rate on true no-person images
  - contact sheets: worst false negatives and worst false positives

Usage (nemoenv python, from inside pytorch_ssd):
  ../nemoenv/bin/python export/error_analysis_fq.py \
    --ckpt ~/Downloads/drone/training/successor_qat/plain_follow_epoch_003.pth
"""

import argparse
import sys
from copy import deepcopy
from pathlib import Path

import numpy as np
import torch
from PIL import Image, ImageDraw

TILE = 256


def patch_model_to_graph_compat():
    fn = getattr(torch.onnx.utils, "_model_to_graph", None)
    if fn is None or getattr(fn, "_nemo_compat_patched", False):
        return

    def wrapped(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except TypeError as exc:
            msg = str(exc)
            if "_retain_param_name" not in msg and "propagate" not in msg:
                raise
            kwargs = dict(kwargs)
            kwargs.pop("propagate", None)
            kwargs.pop("_retain_param_name", None)
            return fn(*args, **kwargs)

    wrapped._nemo_compat_patched = True
    torch.onnx.utils._model_to_graph = wrapped


def sheet(entries, ds, title, out_path):
    cols = 4
    rows = (len(entries) + cols - 1) // cols
    img_sheet = Image.new("RGB", (cols * TILE, rows * TILE), "black")
    d0 = ImageDraw.Draw(img_sheet)
    for k, (idx, prob, extra) in enumerate(entries):
        img, _ = ds[idx]
        tile = Image.fromarray((img[0].numpy() * 255).astype("uint8"), mode="L")
        tile = tile.resize((TILE, TILE), Image.NEAREST).convert("RGB")
        d = ImageDraw.Draw(tile)
        d.rectangle([0, 0, TILE, 18], fill=(0, 0, 0))
        d.text((4, 3), f"#{idx} P={prob:.2f} {extra}", fill=(255, 255, 255))
        img_sheet.paste(tile, ((k % cols) * TILE, (k // cols) * TILE))
    img_sheet.save(out_path)
    print(f"saved {title}: {out_path}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ckpt", required=True)
    ap.add_argument("--mode", choices=["qat", "calib"], default="qat")
    ap.add_argument("--unstable-root", default="../pytorch_ssd_unstable")
    ap.add_argument("--coco-root", default="data/coco")
    ap.add_argument("--vis-thresh", type=float, default=0.45)
    ap.add_argument("--bits", type=int, default=8)
    ap.add_argument("--out-dir", default="export/error_analysis")
    args = ap.parse_args()

    import nemo

    root = Path(args.unstable_root).resolve()
    sys.path.insert(0, str(root))
    from models.follow_model_factory import (
        build_follow_model,
        follow_model_kwargs_from_metadata,
    )
    from utils.follow_task import decode_follow_outputs
    from utils.coco_follow_regression import COCOFollowRegressionDataset
    from utils.transforms import get_val_transforms
    from torch.utils.data import DataLoader

    ckpt = Path(args.ckpt).expanduser().resolve()
    payload = torch.load(ckpt, map_location="cpu")
    head = payload.get("follow_head_type")

    model = build_follow_model(**follow_model_kwargs_from_metadata(payload)).eval()
    patch_model_to_graph_compat()
    mq = nemo.transform.quantize_pact(deepcopy(model), dummy_input=torch.randn(1, 1, 128, 128))
    mq.eval()
    mq.change_precision(bits=args.bits, scale_weights=True, scale_activations=True)
    if args.mode == "qat":
        mq.load_state_dict(payload["state_dict"], strict=False)
    else:
        raise SystemExit("calib mode not needed here; use sweep_fq_ckpt.py patterns")

    coco = Path(args.coco_root).resolve()
    ds = COCOFollowRegressionDataset(
        root=str(coco / "images/val2017"),
        ann_file=str(coco / "annotations/instances_val2017.json"),
        transforms=get_val_transforms("hybrid_follow", input_channels=1),
    )
    loader = DataLoader(ds, batch_size=32, num_workers=0)

    probs, gts, sizes, nops = [], [], [], []
    with torch.no_grad():
        for images, targets in loader:
            d = decode_follow_outputs(mq(images), head)
            probs.append(d["visibility_confidence"])
            ft = targets["follow_target"]
            gts.append(ft[:, 2]); sizes.append(ft[:, 1])
            tnp = targets.get("true_no_person")
            nops.append(tnp.view(-1) if tnp is not None else torch.zeros(images.shape[0]))
    probs = torch.cat(probs).numpy()
    gts = torch.cat(gts).numpy() > 0.5
    sizes = torch.cat(sizes).numpy()
    nops = torch.cat(nops).numpy() > 0

    t = args.vis_thresh
    pred = probs >= t
    print(f"\n=== error anatomy @ threshold {t} ({ckpt.name}) ===")
    print(f"overall: recall={float((pred & gts).sum())/max(gts.sum(),1):.3f}  "
          f"precision={float((pred & gts).sum())/max(pred.sum(),1):.3f}  "
          f"no-person FP rate={float((pred & nops).sum())/max(nops.sum(),1):.3f}")

    print("\nrecall by ground-truth person size (size_proxy quartile):")
    vis_idx = np.where(gts)[0]
    qs = np.quantile(sizes[vis_idx], [0.25, 0.5, 0.75])
    labels = [f"tiny <{qs[0]:.2f}", f"small {qs[0]:.2f}-{qs[1]:.2f}",
              f"medium {qs[1]:.2f}-{qs[2]:.2f}", f"large >{qs[2]:.2f}"]
    edges = [-1, qs[0], qs[1], qs[2], 10]
    for i in range(4):
        m = vis_idx[(sizes[vis_idx] > edges[i]) & (sizes[vis_idx] <= edges[i + 1])]
        r = float(pred[m].sum()) / max(len(m), 1)
        print(f"  {labels[i]:<22} n={len(m):>4}  recall={r:.3f}")

    out = Path(args.out_dir); out.mkdir(parents=True, exist_ok=True)
    fn_idx = [i for i in vis_idx if not pred[i]]
    fn_sorted = sorted(fn_idx, key=lambda i: probs[i])[:16]
    sheet([(i, probs[i], f"sz={sizes[i]:.2f} MISS") for i in fn_sorted], ds,
          "worst false negatives", out / "worst_false_negatives.png")
    fp_idx = [i for i in np.where(nops)[0] if pred[i]]
    fp_sorted = sorted(fp_idx, key=lambda i: -probs[i])[:16]
    sheet([(i, probs[i], "FALSE ALARM") for i in fp_sorted], ds,
          "worst false positives", out / "worst_false_positives.png")


if __name__ == "__main__":
    main()
