"""Per-image float (checkpoint) + integer (model_id_dory.onnx via ORT) inference for the unbiased eval.
doryenv. Imports release code read-only; writes only under OUT.
Usage: python infer.py <parity|full>
Float path  = compare_quant_native_follow_rep16_overlays.build_eval_inputs (convert('L') -> val transform), model(float_input)
Int path    = hybrid_follow_image_artifacts.preprocess_image_uint8 (runtime/app staging used by the release DORY sim)
              -> ORT(model_id_dory.onnx, ORT_DISABLE_ALL) raw ints; logits = raw * eps (semantic_output 'id')
Also stores ORT on the stage-06 staging (round(clamp(float_input)*255)) as a sensitivity/parity channel.
Labels      = repo AnnotationIndex + get_val_transforms + compute_follow_target (same as release compare/eval code).
"""
import sys, json, hashlib, time
from pathlib import Path
import numpy as np, torch, onnxruntime as ort
from PIL import Image

U = Path("/Users/saimaruvada/Downloads/drone/pytorch_ssd_unstable")
sys.path.insert(0, str(U)); sys.path.insert(0, str(U / "export"))
from models.follow_model_factory import build_follow_model_from_checkpoint, load_checkpoint_payload
from utils.transforms import get_val_transforms
from utils.coco_follow_regression import compute_follow_target
from hybrid_follow_image_artifacts import preprocess_image_uint8
from validate_follow_rep16_overlays import AnnotationIndex

OUT = Path("/private/tmp/claude-501/-Users-saimaruvada-Downloads/90541ca8-cca5-4400-9855-79d1dde551f0/scratchpad/unbiased_eval")
VAL = Path("/Users/saimaruvada/Downloads/drone/pytorch_ssd/data/coco/images/val2017")
ANN = Path("/Users/saimaruvada/Downloads/drone/pytorch_ssd/data/coco/annotations/instances_val2017.json")
PACK = U / "logs/plain_follow_eval576_qat/expanded_eval_manifest.json"
MODELS = {
    "champion": ("/Users/saimaruvada/Downloads/drone/pytorch_ssd_unstable/artifacts/successor_qat_ep3_eval.pth", U / "logs/plain_follow_prod_qat_final"),
    "confuser": ("/Users/saimaruvada/Downloads/drone/pytorch_ssd_unstable/artifacts/successor_confuser_ep8.pth", U / "logs/plain_follow_prod_confuser_final"),
    "confuser_qathn": ("/Users/saimaruvada/Downloads/drone/training/successor_confuser_ctrl_qat_hn/plain_follow_epoch_001_eval.pth", U / "logs/plain_follow_confuser_qathn_final"),
}
SEED = 20260911
CONFUSER_CATS = set(range(16, 26)) | {88}
torch.set_num_threads(2)

def extract_id(p):
    import re
    return int(re.search(r"(\d{12})", Path(p).stem).group(1))

def image_sets():
    files = sorted(p.name for p in VAL.iterdir() if p.suffix.lower() == ".jpg")
    assert len(files) == 5000, len(files)
    rng = np.random.default_rng(SEED)
    rand_idx = np.sort(rng.choice(len(files), size=1000, replace=False))
    random1000 = [str(VAL / files[i]) for i in rand_idx]
    a = json.loads(ANN.read_text())
    cats_by_img = {}
    for an in a["annotations"]:
        cats_by_img.setdefault(int(an["image_id"]), set()).add(int(an["category_id"]))
    confuser = sorted(str(VAL / im["file_name"]) for im in a["images"]
                      if 1 not in cats_by_img.get(int(im["id"]), set()) and cats_by_img.get(int(im["id"]), set()) & CONFUSER_CATS)
    man = json.loads(PACK.read_text())
    pack = [s["image_path"] for s in man["ordered_samples"] if s.get("selected_rank") is not None]
    return {"random1000": random1000, "confuser771": confuser, "pack560": pack}

def build_eval_inputs(image_path, annotations, image_size):  # == compare_quant_native_follow_rep16_overlays.build_eval_inputs
    image_id = extract_id(image_path)
    boxes = annotations.boxes_for_image(image_id)
    target = {"boxes": boxes, "labels": torch.ones((boxes.shape[0],), dtype=torch.int64),
              "area": torch.zeros((boxes.shape[0],), dtype=torch.float32),
              "iscrowd": torch.zeros((boxes.shape[0],), dtype=torch.int64),
              "image_id": torch.tensor([image_id], dtype=torch.int64),
              "true_no_person": torch.tensor([1 if boxes.numel() == 0 else 0], dtype=torch.int64)}
    transform = get_val_transforms(model_type="plain_follow", input_channels=1, image_size=image_size)
    with Image.open(image_path) as image:
        tensor, transformed = transform(image.convert("L"), target)
    follow_target, _ = compute_follow_target(transformed["boxes"], image_height=int(tensor.shape[-2]), image_width=int(tensor.shape[-1]))
    float_input = tensor.unsqueeze(0).to(dtype=torch.float32)
    staged06 = torch.round(torch.clamp(float_input, 0.0, 1.0) * 255.0).to(dtype=torch.float32)
    return float_input, staged06, follow_target.to(torch.float32), int(transformed["true_no_person"].view(-1)[0])

def main():
    mode = sys.argv[1]
    annotations = AnnotationIndex(ANN)
    if mode == "parity":
        paths_by_model = {m: [str(p) for p in sorted((rel / "input_sets/rep16").iterdir()) if p.suffix == ".jpg"] for m, (_, rel) in MODELS.items()}
        tags = None
    else:
        sets = image_sets()
        allp = sorted(set(sets["random1000"]) | set(sets["confuser771"]) | set(sets["pack560"]))
        tags = {k: [p in set(v) for p in allp] for k, v in sets.items()}
        json.dump({k: v for k, v in sets.items()}, open(OUT / "image_sets.json", "w"), indent=0)
        paths_by_model = {m: allp for m in MODELS}
    for m, (ckpt, rel) in MODELS.items():
        t0 = time.time()
        eps = float(json.loads((rel / "release_summary.json").read_text())["id_output_eps"]["value"])
        md = load_checkpoint_payload(ckpt, torch.device("cpu"))
        image_size = (int(md["height"]), int(md["width"]))
        model = build_follow_model_from_checkpoint(ckpt, torch.device("cpu")).eval()
        so = ort.SessionOptions(); so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_DISABLE_ALL
        so.intra_op_num_threads = 2
        onnx_path = rel / "quant_eval/model_id_dory.onnx"
        sess = ort.InferenceSession(str(onnx_path), so, providers=["CPUExecutionProvider"])
        iname, oname = sess.get_inputs()[0].name, sess.get_outputs()[0].name
        paths = paths_by_model[m]
        FP, RT, S06, TGT, TNP, SHA_RT = [], [], [], [], [], []
        for p in paths:
            fi, s06, tgt, tnp = build_eval_inputs(p, annotations, image_size)
            with torch.no_grad():
                FP.append(model(fi).numpy().reshape(-1).astype(np.float64))
            xrt = preprocess_image_uint8(Path(p), image_size[0], image_size[1], model_type="plain_follow")
            SHA_RT.append(hashlib.sha1(xrt.astype(np.uint8).tobytes()).hexdigest())
            RT.append(np.asarray(sess.run([oname], {iname: xrt.astype(np.float32).reshape(1, 1, *image_size)})[0]).reshape(-1))
            S06.append(np.asarray(sess.run([oname], {iname: s06.numpy().astype(np.float32)})[0]).reshape(-1))
            TGT.append(tgt.numpy()); TNP.append(tnp)
        out = dict(paths=np.array(paths), fp=np.array(FP), raw_rt=np.array(RT, dtype=np.float64), raw_06=np.array(S06, dtype=np.float64),
                   target=np.array(TGT), true_no_person=np.array(TNP), eps=eps, sha_rt=np.array(SHA_RT),
                   onnx_sha1=hashlib.sha1(onnx_path.read_bytes()).hexdigest(), ckpt=ckpt)
        if tags is not None:
            for k, v in tags.items():
                out["tag_" + k] = np.array(v)
        np.savez(OUT / f"{mode}_{m}.npz", **out)
        print(m, "images", len(paths), "eps", eps, "secs", round(time.time() - t0, 1), flush=True)

if __name__ == "__main__":
    main()
