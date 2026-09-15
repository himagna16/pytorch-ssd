#!/usr/bin/env python3
"""REAL side, second arm: the same real person photographs put through the SAME
himax_typical sensor model the flown `__ships` cells see.

This is the pet study's `real_pets_himax.py` method, unchanged, applied to
people. Why it exists: a sim/real gap could be the CARD (flat cutout, matte
panel, painted background, MuJoCo shading) or it could be the CAMERA (blur,
noise, AE, vignetting). Putting the photographs through the same sensor model
separates the two.

Method, chosen so that apparent size is untouched: the photograph's centre
square crop - the crop `real_people.py` measures its px128_h in - is resized to
244x244, which is the height of the AI-deck frame and the size of the square
the network's crop takes out of it, and CameraModel('himax_typical', 244, 244)
runs on that square. So this arm is ALREADY resolution-matched: it reaches the
network through a 244-px square, like a render. That also means it carries the
resampling and the sensor TOGETHER, which is what the pet study's correction
0a.2 was about - the split is done in `control_resolution.py`, not here.

DRAWS independent seeds per image, each after WARMUP frames to settle the AE
loop, exactly as the sim render does.

Usage: nemoenv/bin/python real_people_himax.py <real_csv> <out_csv> [--stratum S]
"""
import csv
import json
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from shared_arms import Arms, IMG_DIR, ROOT, CHAMPION_ARMS_SHA256  # noqa: E402
sys.path.insert(0, str(ROOT / "tools/crazysim_macos"))
import camera_model as cm  # noqa: E402

WARMUP, DRAWS = 20, 3
REAL = Path(sys.argv[1])
OUT = Path(sys.argv[2])
STRATUM = sys.argv[sys.argv.index("--stratum") + 1] if "--stratum" in sys.argv else "whole_upright"

KEEP = ("img_id", "file_name", "px128_h", "px128_w", "whole_upright", "isolated", "wui",
        "is_sim_source", "n_person_anns", "aspect_hw", "n_kp_visible")


def square244(path: Path) -> np.ndarray:
    img = Image.open(path).convert("RGB")
    w, h = img.size
    s = min(w, h)
    left, top = (w - s) // 2, (h - s) // 2
    return np.asarray(img.crop((left, top, left + s, top + s)).resize((244, 244), Image.BILINEAR),
                      np.uint8)


def main():
    src = [r for r in csv.DictReader(open(REAL))
           if STRATUM == "all_people" or r[STRATUM] == "1"]
    print(f"champion_arms.py sha256 {CHAMPION_ARMS_SHA256}", flush=True)
    print(f"{len(src)} photographs in stratum '{STRATUM}' x {DRAWS} draws", flush=True)
    arms = Arms(("float", "fq", "chip"))
    print("arms:", json.dumps(arms.info)[:300], flush=True)
    rows = []
    t0 = time.time()
    for n, r in enumerate(src):
        rgb = square244(IMG_DIR / r["file_name"])
        for k in range(DRAWS):
            camm = cm.CameraModel("himax_typical", 244, 244, seed=1234 + k)
            for _ in range(WARMUP):
                g = camm.apply(rgb, omega=np.zeros(3), dt=0.153)
            g = camm.apply(rgb, omega=np.zeros(3), dt=0.153)
            row = {kk: r[kk] for kk in KEEP}
            row["seed"] = 1234 + k
            row["frame_mean_dn"] = round(float(g.mean()), 2)
            row.update({kk: (round(v, 4) if isinstance(v, float) else v)
                        for kk, v in arms(g).items()})
            rows.append(row)
        if (n + 1) % 50 == 0:
            print(f"  {n + 1}/{len(src)} images ({time.time() - t0:.0f} s)", flush=True)
    arms.close()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    for arm in ("float", "fq", "chip"):
        v = np.array([x[arm] for x in rows], float)
        print(f"  {arm:6s} himax: >=0.45 {np.mean(v >= 0.45):.3f}  >=0.75 {np.mean(v >= 0.75):.3f}  "
              f"<0.45 {np.mean(v < 0.45):.3f}  median {np.median(v):.3f}  n={len(v)}", flush=True)
    # A 244-px square reaches firmware_preprocess with no further resampling, so
    # this arm's own via244 column must be a no-op. Stated, not assumed.
    d = np.array([abs(float(x["chip"]) - float(x["chip_via244"])) for x in rows])
    print(f"  himax arm is natively 244: max |chip - chip_via244| = {d.max():.4f}", flush=True)
    print("wrote", OUT, flush=True)


if __name__ == "__main__":
    main()
