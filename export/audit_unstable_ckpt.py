"""FP -> FQ drift audit for David's released quant-native checkpoints.

Runs OUR stage-drift methodology against HIS artifacts: his model classes,
checkpoint loader, and decode contract (imported from the `unstable`
worktree), his rep_images calibration set, and his representative-16
diagnostic images. Self-contained on purpose — imports nothing from this
repo's `models`/`utils` packages to avoid colliding with the worktree's
identically named packages.

Usage (nemoenv python):
  ../nemoenv/bin/python export/audit_unstable_ckpt.py \
    --unstable-root ../pytorch_ssd_unstable \
    --ckpt artifacts/plain_follow_best_follow_score.pth
"""

import argparse
import sys
from copy import deepcopy
from pathlib import Path

import torch
import torchvision.transforms.functional as TF
from PIL import Image

REP16_DEFAULT = (
    "logs/hybrid_follow_val/1_real_image_validation/input_sets/representative16_20260324"
)


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


def preprocess(path: Path) -> torch.Tensor:
    img = Image.open(path).convert("L")
    w, h = img.size
    side = min(w, h)
    img = TF.crop(img, (h - side) // 2, (w - side) // 2, side, side)
    img = TF.resize(img, [128, 128])
    return TF.to_tensor(img).unsqueeze(0)


def build_fq(model_fp, calib, bits):
    import nemo

    patch_model_to_graph_compat()
    mq = nemo.transform.quantize_pact(
        deepcopy(model_fp), dummy_input=torch.randn(1, 1, 128, 128)
    )
    mq.eval()
    mq.change_precision(bits=bits, scale_weights=True, scale_activations=True)
    with torch.no_grad():
        with mq.statistics_act():
            for x in calib:
                _ = mq(x)
    mq.reset_alpha_act()
    try:
        mq.reset_alpha_weights()
    except Exception:
        pass
    return mq


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--unstable-root", default="../pytorch_ssd_unstable")
    ap.add_argument("--ckpt", default="artifacts/plain_follow_best_follow_score.pth")
    ap.add_argument("--rep-dir", default=REP16_DEFAULT)
    ap.add_argument("--calib-dir", default="data/rep_images")
    ap.add_argument("--calib-n", type=int, default=32)
    ap.add_argument("--bits", type=int, default=8)
    ap.add_argument("--vis-thresh", type=float, default=0.5)
    args = ap.parse_args()

    root = Path(args.unstable_root).resolve()
    sys.path.insert(0, str(root))
    from models.follow_model_factory import build_follow_model_from_checkpoint
    from utils.follow_task import decode_follow_outputs

    ckpt_path = root / args.ckpt
    payload = torch.load(ckpt_path, map_location="cpu")
    head_type = payload.get("follow_head_type")
    print(f"[audit] ckpt={ckpt_path.name} head={head_type} "
          f"epoch={payload.get('epoch')} best={payload.get('best_metric')}="
          f"{payload.get('best_metric_value')}")

    model_fp = build_follow_model_from_checkpoint(ckpt_path, torch.device("cpu")).eval()

    calib_paths = sorted((root / args.calib_dir).glob("*.png"))[: args.calib_n]
    calib = [preprocess(p) for p in calib_paths]
    print(f"[audit] building FQ ({args.bits}-bit, {len(calib)} of David's calib images)...")
    model_fq = build_fq(model_fp, calib, args.bits)

    rep_paths = sorted((root / args.rep_dir).glob("*.jpg"))
    rows = []
    with torch.no_grad():
        for p in rep_paths:
            x = preprocess(p)
            gt_vis = "_visible_" in p.name
            d_fp = decode_follow_outputs(model_fp(x), head_type)
            d_fq = decode_follow_outputs(model_fq(x), head_type)
            if not rows:
                print("[audit] decode keys:", sorted(d_fp.keys()))
            row = {"name": p.name, "gt": gt_vis}
            for tag, d in (("fp", d_fp), ("fq", d_fq)):
                row[f"{tag}_xbin"] = int(d["x_bin_index"][0]) if "x_bin_index" in d else None
                row[f"{tag}_sb"] = int(d["size_bucket_index"][0]) if "size_bucket_index" in d else None
                row[f"{tag}_vis"] = float(d["visibility_confidence"][0])
            rows.append(row)

    print(f"\n{'image':<34} {'gt':>3} | {'fp xb':>5} {'fq xb':>5} {'ok':>3} | "
          f"{'fp sb':>5} {'fq sb':>5} {'ok':>3} | {'fp vP':>6} {'fq vP':>6} {'ok':>3}")
    x_exact = x_adj = sb_exact = vis_agree = 0
    for r in rows:
        xe = r["fp_xbin"] == r["fq_xbin"]
        xa = abs(r["fp_xbin"] - r["fq_xbin"]) <= 1
        se = r["fp_sb"] == r["fq_sb"]
        va = (r["fp_vis"] >= args.vis_thresh) == (r["fq_vis"] >= args.vis_thresh)
        x_exact += xe; x_adj += xa; sb_exact += se; vis_agree += va
        print(f"{r['name'][:34]:<34} {('P' if r['gt'] else '-'):>3} | "
              f"{r['fp_xbin']:>5} {r['fq_xbin']:>5} {('y' if xe else 'N'):>3} | "
              f"{r['fp_sb']:>5} {r['fq_sb']:>5} {('y' if se else 'N'):>3} | "
              f"{r['fp_vis']:>6.3f} {r['fq_vis']:>6.3f} {('y' if va else 'N'):>3}")

    n = len(rows)
    print(f"\nDavid's released checkpoint, FP->FQ over {n} rep16 images:")
    print(f"  decoded x-bin preserved exactly:  {x_exact}/{n}")
    print(f"  x-bin adjacent-or-better:         {x_adj}/{n}")
    print(f"  size bucket preserved:            {sb_exact}/{n}")
    print(f"  visibility decision agreement:    {vis_agree}/{n}")


if __name__ == "__main__":
    main()
