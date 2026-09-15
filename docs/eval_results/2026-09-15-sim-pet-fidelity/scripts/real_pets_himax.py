#!/usr/bin/env python3
"""REAL side, second arm: the same real dog and cat photographs, put through the
SAME himax_typical sensor model the flown `__ships` cells see.

Why this exists. The sim frames pass through camera_model.py; the photographs in
real_pets.py do not. A sim-vs-real gap could therefore be the CARD (flat cutout,
matte panel, painted background, MuJoCo shading) or it could be the CAMERA
(blur, noise, AE, vignetting). Putting the photographs through the same sensor
model separates the two:

    real raw  ->  real himax     = what the camera model alone costs
    real himax -> sim himax      = what the card alone costs

Method, chosen so that apparent size is untouched: the photograph's centre
square crop - the same crop real_pets.py measures its px128_h in - is resized to
244x244, which is the height of the AI-deck frame and the size of the square the
network's crop takes out of it, and CameraModel('himax_typical', 244, 244) is
run on that square. The sim frame's own chain is 324x244 -> centre 244 square,
so both sides reach the network through a 244-px square degraded by the same
sensor model at the same scale. The one thing that differs is the vignette
field, which camera_model normalises to the frame it is constructed with: on a
244x244 square the corners are nearer the centre than on a 324x244 frame, so the
photographs get very slightly less corner falloff than the renders do.

DRAWS independent seeds per image, each after WARMUP frames to settle the AE
loop, exactly as sim_render.py does.

Usage: nemoenv/bin/python real_pets_himax.py <out_csv> [cat1,cat2,...]
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
from real_pets import slice_rows  # noqa: E402

IMG = ROOT / "data/coco/images/val2017"
WARMUP, DRAWS = 20, 3
OUT = Path(sys.argv[1])
WANT = set(sys.argv[2].split(",")) if len(sys.argv) > 2 else {"dog", "cat"}


def square244(path: Path) -> np.ndarray:
    img = Image.open(path).convert("RGB")
    w, h = img.size
    s = min(w, h)
    left, top = (w - s) // 2, (h - s) // 2
    return np.asarray(img.crop((left, top, left + s, top + s)).resize((244, 244), Image.BILINEAR),
                      np.uint8)


def main():
    arms = Arms(("float", "fq", "chip"))
    print("arms:", json.dumps(arms.info)[:300], flush=True)
    rows = []
    src = [r for r in slice_rows() if r["subject_cat"] in WANT]
    print(f"{len(src)} images with subject in {sorted(WANT)}", flush=True)
    for n, r in enumerate(src):
        rgb = square244(IMG / r["file_name"])
        for k in range(DRAWS):
            camm = cm.CameraModel("himax_typical", 244, 244, seed=1234 + k)
            for _ in range(WARMUP):
                g = camm.apply(rgb, omega=np.zeros(3), dt=0.153)
            g = camm.apply(rgb, omega=np.zeros(3), dt=0.153)
            row = {kk: r[kk] for kk in ("img_id", "file_name", "subject_cat", "px128_h", "px128_w")}
            row["seed"] = 1234 + k
            row["frame_mean_dn"] = round(float(g.mean()), 2)
            row.update({kk: (round(v, 4) if isinstance(v, float) else v) for kk, v in arms(g).items()})
            rows.append(row)
        if (n + 1) % 50 == 0:
            print(f"  {n + 1}/{len(src)} images", flush=True)
    arms.close()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    for arm in ("float", "fq", "chip"):
        v = np.array([x[arm] for x in rows])
        print(f"  {arm:6s} himax: >=0.45 {np.mean(v >= 0.45):.3f}  >=0.75 {np.mean(v >= 0.75):.3f}  "
              f"mean {v.mean():.3f}  n={len(v)}", flush=True)
    print("wrote", OUT, flush=True)


if __name__ == "__main__":
    main()
