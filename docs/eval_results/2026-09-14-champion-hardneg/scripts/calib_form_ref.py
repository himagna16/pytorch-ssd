"""Score a checkpoint in RECALIBRATED fake-quant form (learned PACT alphas discarded).

Why this exists: train.py's --init-ckpt loads the checkpoint into the *unwrapped*
model, so a QAT checkpoint's 59 PACT alpha/range tensors are dropped ("unexpected
keys"), and enable_quant_aware_finetune() then re-derives activation ranges by
calibrating on --qat-calib-batches of training data. So the state training
actually starts from is NOT the champion as measured by sweep_fq_ckpt.py --mode
qat. This script measures that starting state, so the epoch-1 delta is not
confounded with the alpha reset.

export/sweep_fq_ckpt.py --mode calib cannot do this: it load_state_dict()s
strictly and a QAT checkpoint has extra keys. Same model construction and the
same 32 rep_images calibration set otherwise.

Usage (nemoenv python, from inside pytorch_ssd):
  ../nemoenv/bin/python docs/eval_results/2026-09-14-champion-hardneg/scripts/calib_form_ref.py <ckpt.pth>
"""
import json
import sys
from collections import defaultdict
from copy import deepcopy
from pathlib import Path

import numpy as np
import torch

DRONE = Path(__file__).resolve().parents[5]
ROOT = DRONE / "pytorch_ssd_unstable"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(DRONE / "pytorch_ssd/export"))
from sweep_fq_ckpt import patch_model_to_graph_compat, rep_preprocess  # noqa: E402
import nemo  # noqa: E402
from models.follow_model_factory import build_follow_model, follow_model_kwargs_from_metadata  # noqa: E402
from utils.follow_task import decode_follow_outputs  # noqa: E402
from utils.coco_follow_regression import COCOFollowRegressionDataset  # noqa: E402
from utils.transforms import get_val_transforms  # noqa: E402
from torch.utils.data import DataLoader  # noqa: E402

PERSON = {1}
CONF = {16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 88}
COCO = DRONE / "pytorch_ssd/data/coco"
ANN = COCO / "annotations/instances_val2017.json"
IMG = COCO / "images/val2017"


def main():
    ckpt = Path(sys.argv[1]).resolve()
    payload = torch.load(ckpt, map_location="cpu")
    head = payload["follow_head_type"]
    model = build_follow_model(**follow_model_kwargs_from_metadata(payload)).eval()
    missing, unexpected = model.load_state_dict(payload["state_dict"], strict=False)
    print(f"[calib-ref] {ckpt.name}: loaded FP weights (missing={len(missing)}, "
          f"dropped {len(unexpected)} QAT alpha/range tensors)")
    patch_model_to_graph_compat()
    mq = nemo.transform.quantize_pact(deepcopy(model), dummy_input=torch.randn(1, 1, 128, 128)).eval()
    mq.change_precision(bits=8, scale_weights=True, scale_activations=True)
    calib = [rep_preprocess(p) for p in sorted((ROOT / "data/rep_images").glob("*.png"))[:32]]
    with torch.no_grad():
        with mq.statistics_act():
            for x in calib:
                mq(x)
    mq.reset_alpha_act()
    try:
        mq.reset_alpha_weights()
    except Exception:
        pass
    print(f"[calib-ref] recalibrated activations on {len(calib)} rep_images")

    ds = COCOFollowRegressionDataset(root=str(IMG), ann_file=str(ANN),
                                     transforms=get_val_transforms("hybrid_follow", input_channels=1))
    probs, gts = [], []
    with torch.no_grad():
        for images, targets in DataLoader(ds, batch_size=32, num_workers=0):
            probs.append(decode_follow_outputs(mq(images), head)["visibility_confidence"])
            gts.append(targets["follow_target"][:, 2])
    probs = torch.cat(probs).numpy(); gts = torch.cat(gts).numpy() > 0.5
    best = (0.0, 0.0)
    for t in np.arange(0.30, 0.751, 0.05):
        pred = probs >= t
        tp = int((pred & gts).sum()); fp = int((pred & ~gts).sum()); fn = int((~pred & gts).sum())
        prec = tp / max(tp + fp, 1); rec = tp / max(tp + fn, 1)
        f1 = 2 * prec * rec / max(prec + rec, 1e-9)
        if f1 > best[1]:
            best = (t, f1)
    print(f"[calib-ref] DEPLOYED-FORM peak F1 = {best[1]:.4f} at threshold {best[0]:.2f}")

    coco = json.loads(ANN.read_text())
    cats = defaultdict(set)
    for a in coco["annotations"]:
        cats[a["image_id"]].add(a["category_id"])
    negs = {i["id"] for i in coco["images"]
            if not (cats.get(i["id"], set()) & PERSON) and (cats.get(i["id"], set()) & CONF)}
    ds2 = COCOFollowRegressionDataset(root=str(IMG), ann_file=str(ANN),
                                      transforms=get_val_transforms("hybrid_follow", input_channels=1))
    ds2.img_ids = [i for i in ds2.img_ids if int(i) in negs]
    fp45 = fp55 = n = 0
    with torch.no_grad():
        for images, _ in DataLoader(ds2, batch_size=32, num_workers=0):
            p = decode_follow_outputs(mq(images), head)["visibility_confidence"]
            fp45 += int((p >= 0.45).sum()); fp55 += int((p >= 0.55).sum()); n += len(p)
    print(f"[calib-ref] confuser-slice FP: {fp45/n:.3f} @0.45, {fp55/n:.3f} @0.55 (n={n})")


if __name__ == "__main__":
    main()
