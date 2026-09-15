"""Peak F1 over a WIDER threshold grid than export/sweep_fq_ckpt.py uses.

sweep_fq_ckpt.py sweeps 0.30..0.75. Every checkpoint in this run peaked at
0.30 — the bottom edge of that grid — so its "peak F1" could be clipped: the
true optimum may sit below 0.30. The champion peaks at 0.45, in the grid's
interior, so a boundary-clipped comparison would understate the fine-tunes.
This sweeps 0.05..0.75 and reports both numbers.

Usage (nemoenv python, from inside pytorch_ssd):
  ../nemoenv/bin/python docs/eval_results/2026-09-14-champion-hardneg/scripts/extended_sweep.py <ckpt.pth> [more...]
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

COCO = DRONE / "pytorch_ssd/data/coco"


def scores(probs, gts, grid):
    out = []
    for t in grid:
        pred = probs >= t
        tp = int((pred & gts).sum()); fp = int((pred & ~gts).sum()); fn = int((~pred & gts).sum())
        prec = tp / max(tp + fp, 1); rec = tp / max(tp + fn, 1)
        out.append((t, prec, rec, 2 * prec * rec / max(prec + rec, 1e-9)))
    return out


def main():
    ds = COCOFollowRegressionDataset(
        root=str(COCO / "images/val2017"), ann_file=str(COCO / "annotations/instances_val2017.json"),
        transforms=get_val_transforms("hybrid_follow", input_channels=1))
    patch_model_to_graph_compat()
    for ck in sys.argv[1:]:
        payload = torch.load(ck, map_location="cpu")
        head = payload["follow_head_type"]
        m = build_follow_model(**follow_model_kwargs_from_metadata(payload)).eval()
        mq = nemo.transform.quantize_pact(deepcopy(m), dummy_input=torch.randn(1, 1, 128, 128)).eval()
        mq.change_precision(bits=8, scale_weights=True, scale_activations=True)
        mq.load_state_dict(payload["state_dict"], strict=False)
        probs, gts = [], []
        with torch.no_grad():
            for images, targets in DataLoader(ds, batch_size=32, num_workers=0):
                probs.append(decode_follow_outputs(mq(images), head)["visibility_confidence"])
                gts.append(targets["follow_target"][:, 2])
        probs = torch.cat(probs).numpy(); gts = torch.cat(gts).numpy() > 0.5
        narrow = max(scores(probs, gts, np.arange(0.30, 0.751, 0.05)), key=lambda r: r[3])
        wide = max(scores(probs, gts, np.arange(0.05, 0.751, 0.05)), key=lambda r: r[3])
        print(f"{Path(ck).name}: narrow(0.30-0.75) peak F1={narrow[3]:.4f} @{narrow[0]:.2f} | "
              f"wide(0.05-0.75) peak F1={wide[3]:.4f} @{wide[0]:.2f} "
              f"(prec={wide[1]:.3f} rec={wide[2]:.3f})", flush=True)


if __name__ == "__main__":
    main()
