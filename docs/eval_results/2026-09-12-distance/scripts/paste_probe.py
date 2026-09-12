"""No simulator. Paste a masked COCO person into a 324x244 frame at an EXACTLY
known pixel height, with the same vertical placement the sim produces for a
1.7 m subject seen from the drone's eye line, and ask the size head.

If the over-read follows one particular cutout, it is a subject-appearance
problem. If it follows every cutout, it is the size head. If it appears only in
the MuJoCo render, it is the renderer.
"""
import argparse, math, sys
from pathlib import Path
import numpy as np
from PIL import Image, ImageFilter

COCO_ROOT = Path("/Users/saimaruvada/Downloads/drone/pytorch_ssd/data/coco")
UNSTABLE = Path("/Users/saimaruvada/Downloads/drone/pytorch_ssd_unstable")
FRAME_W, FRAME_H = 324, 244
FOCAL = (FRAME_H / 2) / math.tan(math.radians(35.0))     # 174.23
TAN = math.tan(math.radians(35.0))
EYE_Z, H_SUBJ = 0.8, 1.7
WALL = (158, 158, 168)

ap = argparse.ArgumentParser()
ap.add_argument("--anns", default="428692,1728930")
ap.add_argument("--n-random", type=int, default=0, help="extra random tall COCO persons")
ap.add_argument("--ckpt", default=str(UNSTABLE / "artifacts/successor_qat_ep3_eval.pth"))
ap.add_argument("--d0", type=float, default=1.8)
ap.add_argument("--d1", type=float, default=4.2)
ap.add_argument("--step", type=float, default=0.1)
ap.add_argument("--card", action="store_true", help="paste the opaque bbox card (sim-like) instead of the masked person")
ap.add_argument("--dump", default="")
a = ap.parse_args()

from pycocotools.coco import COCO                                      # noqa: E402
coco = COCO(str(COCO_ROOT / "annotations/instances_val2017.json"))

import torch                                                           # noqa: E402
sys.path.insert(0, str(UNSTABLE))
from models.follow_model_factory import build_follow_model_from_checkpoint   # noqa: E402
from utils.follow_task import decode_follow_outputs                          # noqa: E402
head = torch.load(a.ckpt, map_location="cpu").get("follow_head_type")
model = build_follow_model_from_checkpoint(Path(a.ckpt), torch.device("cpu")).eval()
CENTRES = np.array([0.125, 0.375, 0.625, 0.875])

def run(gray):
    s = min(gray.shape)
    y0, x0 = (gray.shape[0] - s) // 2, (gray.shape[1] - s) // 2
    crop = Image.fromarray(gray[y0:y0 + s, x0:x0 + s]).resize((128, 128), Image.BILINEAR)
    x = torch.from_numpy(np.asarray(crop, np.float32) / 255.0)[None, None]
    with torch.no_grad():
        o = model(x)
        dec = decode_follow_outputs(o, head)
    l = o.reshape(-1).numpy()[10:14]
    e = np.exp(l - l.max()); p = e / e.sum()
    return int(dec["size_bucket_index"]), float((p * CENTRES).sum()), float(dec["visibility_confidence"])

def cutout(ann_id):
    """make_cutout's masked composite, RGBA so we can paste only the subject."""
    ann = coco.loadAnns(ann_id)[0]
    info = coco.loadImgs(ann["image_id"])[0]
    rgb = np.asarray(Image.open(COCO_ROOT / "images/val2017" / info["file_name"]).convert("RGB"))
    mask = coco.annToMask(ann).astype(np.uint8) * 255
    x, y, w, h = [int(round(v)) for v in ann["bbox"]]
    m = Image.fromarray(mask).filter(ImageFilter.MinFilter(5))
    m = np.asarray(m.filter(ImageFilter.GaussianBlur(1)), np.float32)[..., None] / 255.0
    sub = rgb.astype(np.float32)[y:y + h, x:x + w]
    sm = m[y:y + h, x:x + w]
    comp = sub * sm + np.array(WALL, np.float32) * (1 - sm)
    alpha = (sm[..., 0] * 255).astype(np.uint8) if not a.card else np.full(sub.shape[:2], 255, np.uint8)
    out = np.dstack([comp.astype(np.uint8), alpha])
    return Image.fromarray(out, "RGBA"), ann, info

ann_ids = [int(v) for v in a.anns.split(",") if v]
if a.n_random:
    rng = np.random.default_rng(7)
    cands = []
    for aid in coco.getAnnIds(catIds=coco.getCatIds(catNms=["person"]), iscrowd=False):
        an = coco.loadAnns(aid)[0]
        x, y, w, h = an["bbox"]
        inf = coco.loadImgs(an["image_id"])[0]
        # tall, unclipped, dominant: a standing person fully inside the frame
        if h > 0.75 * inf["height"] and h / max(w, 1) > 1.8 and y > 2 and y + h < inf["height"] - 2:
            cands.append(aid)
    ann_ids += list(rng.choice(cands, size=min(a.n_random, len(cands)), replace=False))
    print(f"{len(cands)} candidate full-body COCO persons; sampled {a.n_random}")

dists = np.arange(a.d0, a.d1 + 1e-9, a.step)
print(f"\nmode: {'OPAQUE CARD (sim-like)' if a.card else 'masked person on flat wall'}")
print(f"true 1->2 bucket edge (size 0.500) = {H_SUBJ/(2*0.5*TAN):.3f} m\n")
summary = []
for aid in ann_ids:
    img, ann, info = cutout(int(aid))
    flips = []
    line = []
    for dist in dists:
        px_h = int(round(FOCAL * H_SUBJ / dist))
        px_w = max(1, int(round(px_h * img.width / img.height)))
        top = int(round(FRAME_H / 2 - FOCAL * (H_SUBJ - EYE_Z) / dist))
        frame = Image.new("RGB", (FRAME_W, FRAME_H), WALL)
        sc = img.resize((px_w, px_h), Image.LANCZOS)
        frame.paste(sc, ((FRAME_W - px_w) // 2, top), sc)
        gray = np.asarray(frame.convert("L"))
        b, soft, conf = run(gray)
        s_true = px_h / FRAME_H
        line.append((dist, s_true, b, soft, conf))
        if b >= 2:
            flips.append(dist)
        if a.dump and abs(dist - 3.0) < 1e-6:
            frame.save(Path(a.dump) / f"paste_{aid}_d3.0.png")
    outer = max(flips) if flips else None
    s_at = FOCAL * H_SUBJ / outer / FRAME_H if outer else float("nan")
    print(f"ann {aid:8d}  bbox {ann['bbox'][2]:.0f}x{ann['bbox'][3]:.0f} in {info['width']}x{info['height']}"
          f"  h/img={ann['bbox'][3]/info['height']:.2f}")
    print("   " + "  ".join(f"{d:.1f}m:{b}" for d, s, b, so, c in line))
    if outer:
        print(f"   outermost bucket>=2 at {outer:.2f} m (true size {s_at:.3f}) "
              f"-> boundary over-read {0.5/s_at:.2f}x, {outer-2.428:+.2f} m vs the 2.43 m ideal")
    else:
        print("   never reached bucket 2 in this range")
    summary.append((aid, outer, s_at))
    print()

vals = [s for _, o, s in summary if o]
if len(vals) > 1:
    print(f"across {len(vals)} cutouts: boundary over-read "
          f"median {np.median([0.5/v for v in vals]):.2f}x  "
          f"min {min(0.5/v for v in vals):.2f}x  max {max(0.5/v for v in vals):.2f}x")
