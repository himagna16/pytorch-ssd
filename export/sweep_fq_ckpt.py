"""Deployed-form (fake-quantized) visibility sweep on val2017.

Evaluates a checkpoint AS IT WOULD BEHAVE QUANTIZED — the number that
matters for the drone — in one of two modes:

  --mode qat    : checkpoint was saved from quant-aware training and already
                  contains learned PACT alphas; rebuild the wrapped model and
                  load them directly (no calibration).
  --mode calib  : plain FP checkpoint; wrap with NEMO and calibrate
                  activations on David's rep_images set (post-training quant).

Usage (nemoenv python, from inside pytorch_ssd):
  ../nemoenv/bin/python export/sweep_fq_ckpt.py --mode qat \
    --ckpt ~/Downloads/drone/training/successor_qat/plain_follow_epoch_003.pth
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import torch
import torchvision.transforms.functional as TF
from PIL import Image


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


def rep_preprocess(path: Path) -> torch.Tensor:
    img = Image.open(path).convert("L")
    w, h = img.size
    side = min(w, h)
    img = TF.crop(img, (h - side) // 2, (w - side) // 2, side, side)
    img = TF.resize(img, [128, 128])
    return TF.to_tensor(img).unsqueeze(0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ckpt", required=True)
    ap.add_argument("--mode", choices=["qat", "calib"], required=True)
    ap.add_argument("--unstable-root", default="../pytorch_ssd_unstable")
    ap.add_argument("--coco-root", default="data/coco")
    ap.add_argument("--calib-n", type=int, default=32)
    ap.add_argument("--bits", type=int, default=8)
    ap.add_argument("--batch-size", type=int, default=32)
    args = ap.parse_args()

    import nemo
    from copy import deepcopy

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
    print(f"[fq-sweep] {ckpt.name} mode={args.mode} head={head} epoch={payload.get('epoch')}")

    model = build_follow_model(**follow_model_kwargs_from_metadata(payload)).eval()
    patch_model_to_graph_compat()
    mq = nemo.transform.quantize_pact(
        deepcopy(model), dummy_input=torch.randn(1, 1, 128, 128)
    )
    mq.eval()
    mq.change_precision(bits=args.bits, scale_weights=True, scale_activations=True)

    if args.mode == "qat":
        missing, unexpected = mq.load_state_dict(payload["state_dict"], strict=False)
        print(f"[fq-sweep] loaded QAT state (missing={len(missing)}, unexpected={len(unexpected)})")
    else:
        base_missing, base_unexpected = model.load_state_dict(payload["state_dict"])
        mq2 = nemo.transform.quantize_pact(
            deepcopy(model), dummy_input=torch.randn(1, 1, 128, 128)
        )
        mq2.eval()
        mq2.change_precision(bits=args.bits, scale_weights=True, scale_activations=True)
        calib = [rep_preprocess(p) for p in sorted((root / "data/rep_images").glob("*.png"))[: args.calib_n]]
        with torch.no_grad():
            with mq2.statistics_act():
                for x in calib:
                    _ = mq2(x)
        mq2.reset_alpha_act()
        try:
            mq2.reset_alpha_weights()
        except Exception:
            pass
        mq = mq2
        print(f"[fq-sweep] calibrated on {len(calib)} rep_images")

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
            d = decode_follow_outputs(mq(images), head)
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
        tp = int((pred & gts).sum()); fpx = int((pred & ~gts).sum()); fnx = int((~pred & gts).sum())
        prec = tp / max(tp + fpx, 1); rec = tp / max(tp + fnx, 1)
        f1 = 2 * prec * rec / max(prec + rec, 1e-9)
        if f1 > best[1]:
            best = (t, f1)
        print(f"{t:>6.2f} | {prec:>6.3f} {rec:>6.3f} {f1:>6.3f} | "
              f"{int((pred & nops).sum()) / max(int(nops.sum()), 1):>11.3f}")
    print(f"\nDEPLOYED-FORM peak F1 = {best[1]:.4f} at threshold {best[0]:.2f}")


if __name__ == "__main__":
    main()
