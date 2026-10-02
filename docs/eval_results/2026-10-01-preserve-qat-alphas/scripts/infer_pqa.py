"""Per-image outputs for the --preserve-qat-alphas comparison (Oct 1, 2026).

Same images and preprocessing as docs/eval_results/2026-09-11-unbiased (image_sets.json,
seed 20260911): 1,000 random COCO val2017 images + the 771-image confuser slice.

Arms, all on the same images:
  float          the float checkpoint (QAT state stripped)
  qat_fq         the network exactly as QAT trained it: NEMO fake-quant with the learned
                 PACT ranges (how sweep_fq_ckpt.py --mode qat builds it)
  chip_<label>   ONNX Runtime on a release's quant_eval/model_id_dory.onnx, fed the
                 runtime staging (preprocess_image_uint8); logits = raw * the release's eps

nemoenv. Imports release code read-only; writes one .npz per model to OUT.
Usage: nemoenv/bin/python infer_pqa.py <model-key>
"""
import hashlib
import json
import sys
import time
from copy import deepcopy
from pathlib import Path

import numpy as np
import onnxruntime as ort
import torch
from PIL import Image

U = Path("/Users/saimaruvada/Downloads/drone/pytorch_ssd_unstable")
for extra in (U, U / "export", U / "nemo"):
    sys.path.insert(0, str(extra))
import nemo  # noqa: E402
from export_nemo_quant_core import patch_model_to_graph_compat  # noqa: E402
from hybrid_follow_image_artifacts import preprocess_image_uint8  # noqa: E402
from models.follow_model_factory import (  # noqa: E402
    build_follow_model,
    build_follow_model_from_checkpoint,
    follow_model_kwargs_from_metadata,
)
from utils.coco_follow_regression import compute_follow_target  # noqa: E402
from utils.transforms import get_val_transforms  # noqa: E402
from validate_follow_rep16_overlays import AnnotationIndex  # noqa: E402

HERE = Path(__file__).resolve().parent
SETS = Path("/Users/saimaruvada/Downloads/drone/pytorch_ssd/docs/eval_results/2026-09-11-unbiased/image_sets.json")
ANN = Path("/Users/saimaruvada/Downloads/drone/pytorch_ssd/data/coco/annotations/instances_val2017.json")
OUT = Path("/private/tmp/claude-501/-Users-saimaruvada-Downloads/d61d4b16-675d-4343-bf41-a6a63ecfbbe7/scratchpad/pqa_eval")
T = Path("/Users/saimaruvada/Downloads/drone/training")
MODELS = {
    "confuser_qathn3_ep2": {
        "qat": T / "successor_confuser_qat_hn3/plain_follow_epoch_002.pth",
        "float": T / "successor_confuser_qat_hn3/plain_follow_epoch_002_eval.pth",
        "chips": {
            "recal": U / "logs/pqa_qathn3_ep2_default",
            "preserve": U / "logs/pqa_qathn3_ep2_preserve",
        },
    },
    "champion": {
        "qat": T / "successor_qat/plain_follow_epoch_003.pth",
        "float": U / "artifacts/successor_qat_ep3_eval.pth",
        "chips": {
            "recal": U / "logs/plain_follow_prod_qat_final",
            "preserve": U / "logs/pqa_champion_preserve",
        },
    },
}
torch.set_num_threads(4)


def extract_id(p):
    import re

    return int(re.search(r"(\d{12})", Path(p).stem).group(1))


def build_eval_inputs(image_path, annotations, image_size):  # == 2026-09-11-unbiased/infer_ep2.py
    image_id = extract_id(image_path)
    boxes = annotations.boxes_for_image(image_id)
    target = {
        "boxes": boxes,
        "labels": torch.ones((boxes.shape[0],), dtype=torch.int64),
        "area": torch.zeros((boxes.shape[0],), dtype=torch.float32),
        "iscrowd": torch.zeros((boxes.shape[0],), dtype=torch.int64),
        "image_id": torch.tensor([image_id], dtype=torch.int64),
        "true_no_person": torch.tensor([1 if boxes.numel() == 0 else 0], dtype=torch.int64),
    }
    transform = get_val_transforms(model_type="plain_follow", input_channels=1, image_size=image_size)
    with Image.open(image_path) as image:
        tensor, transformed = transform(image.convert("L"), target)
    follow_target, _ = compute_follow_target(
        transformed["boxes"], image_height=int(tensor.shape[-2]), image_width=int(tensor.shape[-1])
    )
    return (
        tensor.unsqueeze(0).to(dtype=torch.float32),
        follow_target.to(torch.float32),
        int(transformed["true_no_person"].view(-1)[0]),
    )


def build_qat_fq(qat_path):
    payload = torch.load(qat_path, map_location="cpu")
    model = build_follow_model(**follow_model_kwargs_from_metadata(payload)).eval()
    model_q = nemo.transform.quantize_pact(deepcopy(model), dummy_input=torch.randn(1, 1, 128, 128)).eval()
    model_q.change_precision(bits=8, scale_weights=True, scale_activations=True)
    model_q.load_state_dict(payload["state_dict"], strict=True)
    return model_q.eval()


def main():
    key = sys.argv[1]
    spec = MODELS[key]
    OUT.mkdir(parents=True, exist_ok=True)
    patch_model_to_graph_compat()
    sets = json.loads(SETS.read_text())
    paths = sorted(set(sets["random1000"]) | set(sets["confuser771"]))
    tags = {k: np.array([p in set(sets[k]) for p in paths]) for k in ("random1000", "confuser771")}
    annotations = AnnotationIndex(ANN)
    t0 = time.time()
    model_fp = build_follow_model_from_checkpoint(spec["float"], torch.device("cpu")).eval()
    model_fq = build_qat_fq(spec["qat"])
    so = ort.SessionOptions()
    so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_DISABLE_ALL
    so.intra_op_num_threads = 2
    chips = {}
    for label, rel in spec["chips"].items():
        onnx_path = rel / "quant_eval/model_id_dory.onnx"
        sess = ort.InferenceSession(str(onnx_path), so, providers=["CPUExecutionProvider"])
        eps = float(json.loads((rel / "release_summary.json").read_text())["id_output_eps"]["value"])
        chips[label] = (sess, eps, hashlib.sha1(onnx_path.read_bytes()).hexdigest(), str(rel))
    FP, FQ, TGT, TNP = [], [], [], []
    RAW = {label: [] for label in chips}
    for p in paths:
        fi, tgt, tnp = build_eval_inputs(p, annotations, (128, 128))
        with torch.no_grad():
            FP.append(model_fp(fi).numpy().reshape(-1).astype(np.float64))
            FQ.append(model_fq(fi).numpy().reshape(-1).astype(np.float64))
        xrt = preprocess_image_uint8(Path(p), 128, 128, model_type="plain_follow").astype(np.float32).reshape(1, 1, 128, 128)
        for label, (sess, _, _, _) in chips.items():
            iname, oname = sess.get_inputs()[0].name, sess.get_outputs()[0].name
            RAW[label].append(np.asarray(sess.run([oname], {iname: xrt})[0]).reshape(-1).astype(np.float64))
        TGT.append(tgt.numpy())
        TNP.append(tnp)
    out = {
        "paths": np.array(paths),
        "fp": np.array(FP),
        "qat_fq": np.array(FQ),
        "target": np.array(TGT),
        "true_no_person": np.array(TNP),
        **{f"tag_{k}": v for k, v in tags.items()},
    }
    for label, (_, eps, sha1, rel) in chips.items():
        out[f"raw_{label}"] = np.array(RAW[label])
        out[f"eps_{label}"] = eps
        out[f"onnx_sha1_{label}"] = sha1
        out[f"release_{label}"] = rel
    np.savez(OUT / f"{key}.npz", **out)
    print(key, "images", len(paths), "secs", round(time.time() - t0, 1),
          {label: (eps, sha1[:8]) for label, (_, eps, sha1, _) in chips.items()}, flush=True)


if __name__ == "__main__":
    main()
