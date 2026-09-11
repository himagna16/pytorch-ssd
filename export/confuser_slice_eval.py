#!/usr/bin/env python3
"""Confuser-slice false-positive rate in fake-quant (FQ) form.

The confuser slice is every COCO val2017 image with no person but at least one
animal or mannequin-like object (categories 16-25 and 88: birds, cats, dogs,
horses, sheep, cows, elephants, bears, zebras, giraffes, teddy bears). The
number reported is the fraction the model calls "person visible" at 0.45 and
0.55. Baseline (David's released model and the QAT champion): 0.239 / 0.171.

QAT checkpoints (with PACT alphas) load their learned alphas; ordinary
checkpoints are calibrated on 32 rep_images first, like the release does.
Recovered from the Aug 28 scratch script that produced the EXPERIMENTS.md numbers.

Usage: ../nemoenv/bin/python export/confuser_slice_eval.py <ckpt.pth> [more.pth ...]
"""
import json
import sys
from collections import defaultdict
from copy import deepcopy
from pathlib import Path

import torch

DRONE = Path(__file__).resolve().parents[2]
ROOT = DRONE / "pytorch_ssd_unstable"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from sweep_fq_ckpt import patch_model_to_graph_compat, rep_preprocess  # noqa: E402
import nemo  # noqa: E402
from models.follow_model_factory import build_follow_model, follow_model_kwargs_from_metadata  # noqa: E402
from utils.follow_task import decode_follow_outputs  # noqa: E402
from utils.coco_follow_regression import COCOFollowRegressionDataset  # noqa: E402
from utils.transforms import get_val_transforms  # noqa: E402
from torch.utils.data import DataLoader  # noqa: E402

PERSON = {1}
CONF = {16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 88}
ANN = DRONE / "pytorch_ssd/data/coco/annotations/instances_val2017.json"
IMG = DRONE / "pytorch_ssd/data/coco/images/val2017"


def confuser_negatives():
    coco = json.loads(ANN.read_text())
    cats = defaultdict(set)
    for a in coco["annotations"]:
        cats[a["image_id"]].add(a["category_id"])
    return {i["id"] for i in coco["images"]
            if not (cats.get(i["id"], set()) & PERSON) and (cats.get(i["id"], set()) & CONF)}


def fq_model(payload):
    m = build_follow_model(**follow_model_kwargs_from_metadata(payload)).eval()
    is_qat = any("W_alpha" in k for k in payload["state_dict"])
    patch_model_to_graph_compat()
    if is_qat:
        mq = nemo.transform.quantize_pact(deepcopy(m), dummy_input=torch.randn(1, 1, 128, 128)).eval()
        mq.change_precision(bits=8, scale_weights=True, scale_activations=True)
        mq.load_state_dict(payload["state_dict"], strict=False)
        return mq, "learned QAT alphas"
    m.load_state_dict(payload["state_dict"])
    mq = nemo.transform.quantize_pact(deepcopy(m), dummy_input=torch.randn(1, 1, 128, 128)).eval()
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
    return mq, "calibrated on 32 rep_images"


def main():
    negs = confuser_negatives()
    for ck in sys.argv[1:]:
        payload = torch.load(ck, map_location="cpu")
        head = payload["follow_head_type"]
        mq, how = fq_model(payload)
        ds = COCOFollowRegressionDataset(root=str(IMG), ann_file=str(ANN),
                                         transforms=get_val_transforms("hybrid_follow", input_channels=1))
        ds.img_ids = [i for i in ds.img_ids if int(i) in negs]
        fp45 = fp55 = n = 0
        with torch.no_grad():
            for images, _ in DataLoader(ds, batch_size=32, num_workers=0):
                p = decode_follow_outputs(mq(images), head)["visibility_confidence"]
                fp45 += int((p >= 0.45).sum()); fp55 += int((p >= 0.55).sum()); n += len(p)
        print(f"{Path(ck).parent.name}/{Path(ck).name} [{how}] confuser-slice FP: "
              f"{fp45 / n:.3f} @0.45, {fp55 / n:.3f} @0.55 (n={n}) [baseline 0.239 / 0.171]", flush=True)


if __name__ == "__main__":
    main()
