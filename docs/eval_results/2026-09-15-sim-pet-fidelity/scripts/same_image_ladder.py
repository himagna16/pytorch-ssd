#!/usr/bin/env python3
"""THE ONE MEASUREMENT WORTH MOST: the SAME dog, rendered and photographed, at
the SAME apparent size, across the sizes the drone actually flies.

The simulator's dog is COCO val2017 image 297830, annotation 11206, and its cat
is 131938 / 50735 - both members of the 771-image confuser slice. So the same
picture can be put through the model twice: once as the simulator renders it
(a flat card in a MuJoCo room, through the himax sensor model) and once as the
photograph it came from.

The obstacle, and what is done about it. In its own photograph the dog subtends
119.9 px of the 128-px network input. A 0.65 m dog seen from 1.0-4.0 m by a
camera flying at 0.8 m subtends 15-52 px. The two do meet at 119.9 px - and
that exact, invention-free pair is measured here as `native` - but every size
the drone actually flies is SMALLER than anything the photograph contains.
Shrinking the dog inside the frame needs field of view the photograph does not
have, so the missing surround has to be filled in. Three fillings are used and
reported separately, and the answer is only as good as their agreement:

    edge       the border pixel of the photograph repeated outwards
    symmetric  the photograph mirrored outwards (a plausible continuation of
               the same room)
    flat       the median colour of the photograph's own 8-px border

Everything else is held identical to the sim side: the canvas is centred on the
subject, resampled to 244x244 (the height of the AI-deck frame and the size of
the square the network's crop takes out of it), and optionally degraded by
CameraModel('himax_typical', 244, 244) with the same warm-up and seeds
sim_render.py uses. Apparent size is asserted, not assumed:

    px128 = subject box height in canvas px * 128 / canvas side

Usage: nemoenv/bin/python same_image_ladder.py <out_csv>
"""
import csv
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from champion_arms import Arms, ROOT  # noqa: E402
sys.path.insert(0, str(ROOT / "tools/crazysim_macos"))
import camera_model as cm  # noqa: E402

IMG = ROOT / "data/coco/images/val2017"
ANN = ROOT / "data/coco/annotations/instances_val2017.json"
WARMUP, DRAWS = 20, 3
TARGETS = [15, 20, 25, 30, 35, 40, 45, 50, 60, 80, 100, 120]
SUBJECTS = [("dog", 297830, 11206), ("cat", 131938, 50735)]
OUT = Path(sys.argv[1])


def canvas(rgb, box, side, mode):
    """A `side` x `side` RGB canvas centred on the subject box, the photograph
    pasted in at 1:1 and the rest filled by `mode`."""
    H, W = rgb.shape[:2]
    cx, cy = box[0] + box[2] / 2.0, box[1] + box[3] / 2.0
    left = int(round(side / 2.0 - cx))
    top = int(round(side / 2.0 - cy))
    right, bottom = side - W - left, side - H - top
    pads = [(max(top, 0), max(bottom, 0)), (max(left, 0), max(right, 0)), (0, 0)]
    if mode == "flat":
        b = np.concatenate([rgb[:8].reshape(-1, 3), rgb[-8:].reshape(-1, 3),
                            rgb[:, :8].reshape(-1, 3), rgb[:, -8:].reshape(-1, 3)])
        fill = np.median(b, axis=0)
        out = np.pad(rgb, pads, mode="constant")
        m = np.ones((H, W), bool)
        mm = np.pad(m, pads[:2], mode="constant")
        out[~mm] = fill
    else:
        out = np.pad(rgb, pads, mode=mode)
    # a negative pad means the canvas is smaller than the photo: crop instead
    y0 = max(-top, 0)
    x0 = max(-left, 0)
    out = out[y0:y0 + side, x0:x0 + side]
    assert out.shape[:2] == (side, side), (out.shape, side)
    return out, (box[1] + max(top, 0) - y0, box[3])       # box top, height in canvas coords


def main():
    coco = json.loads(ANN.read_text())
    anns = {a["id"]: a for a in coco["annotations"]}
    imgs = {i["id"]: i for i in coco["images"]}
    arms = Arms(("float", "fq", "chip"))
    rows = []
    for species, iid, aid in SUBJECTS:
        info = imgs[iid]
        rgb = np.asarray(Image.open(IMG / info["file_name"]).convert("RGB"), np.uint8)
        box = [float(v) for v in anns[aid]["bbox"]]
        for t in TARGETS:
            side = int(round(box[3] * 128.0 / t))
            for mode in ("edge", "symmetric", "flat"):
                cv, (by, bh) = canvas(rgb, box, side, mode)
                vis_h = min(by + bh, side) - max(by, 0)
                px128 = vis_h * 128.0 / side
                sq = np.asarray(Image.fromarray(cv).resize((244, 244), Image.BILINEAR), np.uint8)
                base = {"species": species, "coco_img_id": iid, "target_px128": t,
                        "canvas_side": side, "pad_mode": mode, "px128_h": round(px128, 2),
                        "native": int(side <= max(rgb.shape[:2]))}
                gray = np.asarray(Image.fromarray(sq).convert("L"), np.uint8)
                rows.append({**base, "camera": "direct", "seed": -1,
                             **{k: (round(v, 4) if isinstance(v, float) else v)
                                for k, v in arms(gray).items()}})
                for k in range(DRAWS):
                    camm = cm.CameraModel("himax_typical", 244, 244, seed=1234 + k)
                    for _ in range(WARMUP):
                        g = camm.apply(sq, omega=np.zeros(3), dt=0.153)
                    g = camm.apply(sq, omega=np.zeros(3), dt=0.153)
                    rows.append({**base, "camera": "himax", "seed": 1234 + k,
                                 **{kk: (round(v, 4) if isinstance(v, float) else v)
                                    for kk, v in arms(g).items()}})
            print(f"  {species} target {t:3d} px -> canvas {side} px "
                  f"(photo {rgb.shape[1]}x{rgb.shape[0]})", flush=True)
    arms.close()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print("wrote", OUT, flush=True)


if __name__ == "__main__":
    main()
