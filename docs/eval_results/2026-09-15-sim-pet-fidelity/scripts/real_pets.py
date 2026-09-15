#!/usr/bin/env python3
"""REAL side: the champion's confidence on real COCO pet photographs, with each
photo's subject apparent size measured in the network's own 128x128 input.

The slice is export/confuser_slice_eval.py's slice, verbatim: every val2017
image with NO person annotation and at least one annotation in categories
{16..25, 88} (bird cat dog horse sheep cow elephant bear zebra giraffe teddy
bear). n = 771 - the same n, and the same images, the published 0.239 / 0.171
figure is measured on.

APPARENT SIZE is measured in the only frame both sides share: the 128x128
tensor the network sees. The follower and the COCO val transform do the same
two operations - centre square crop, then resize to 128x128 - so a COCO box
maps into the input as

    crop  = min(W, H);  top = (H - crop)//2;  left = (W - crop)//2
    y1,y2 = clamp(box_y - top, 0, crop)            # the crop can cut the subject
    px128 = (y2 - y1) * 128 / crop

which is what utils/transforms.CenterCropSquare + ResizeImage do to a box. An
image's subject is its LARGEST confuser-category annotation by clamped height.

Usage: nemoenv/bin/python real_pets.py <out_csv> [--no-chip]
"""
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from champion_arms import Arms, ROOT  # noqa: E402

ANN = ROOT / "data/coco/annotations/instances_val2017.json"
IMG = ROOT / "data/coco/images/val2017"
PERSON = {1}
CONF = {16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 88}


def slice_rows():
    coco = json.loads(ANN.read_text())
    cats = {c["id"]: c["name"] for c in coco["categories"]}
    anns = defaultdict(list)
    for a in coco["annotations"]:
        anns[a["image_id"]].append(a)
    imgs = {i["id"]: i for i in coco["images"]}
    ids = sorted(i for i in imgs
                 if not ({a["category_id"] for a in anns.get(i, [])} & PERSON)
                 and ({a["category_id"] for a in anns.get(i, [])} & CONF))
    for iid in ids:
        info = imgs[iid]
        W, H = int(info["width"]), int(info["height"])
        crop = min(W, H)
        top, left = (H - crop) // 2, (W - crop) // 2
        best = None
        for a in anns[iid]:
            if a["category_id"] not in CONF:
                continue
            x, y, w, h = a["bbox"]
            y1, y2 = min(max(y - top, 0.0), crop), min(max(y + h - top, 0.0), crop)
            x1, x2 = min(max(x - left, 0.0), crop), min(max(x + w - left, 0.0), crop)
            px128 = (y2 - y1) * 128.0 / crop
            if best is None or px128 > best["px128_h"]:
                best = {"ann_id": a["id"], "cat": cats[a["category_id"]], "px128_h": px128,
                        "px128_w": (x2 - x1) * 128.0 / crop,
                        "px128_h_nocrop": h * 128.0 / crop,
                        "bbox": [round(float(v), 1) for v in a["bbox"]],
                        "iscrowd": int(a.get("iscrowd", 0))}
        yield {"img_id": iid, "file_name": info["file_name"], "W": W, "H": H, "crop": crop,
               "subject_cat": best["cat"], "subject_ann_id": best["ann_id"],
               "subject_bbox": json.dumps(best["bbox"]), "iscrowd": best["iscrowd"],
               "px128_h": round(best["px128_h"], 2), "px128_w": round(best["px128_w"], 2),
               "px128_h_nocrop": round(best["px128_h_nocrop"], 2),
               "n_conf_anns": sum(1 for a in anns[iid] if a["category_id"] in CONF),
               "cats_present": "|".join(sorted({cats[a["category_id"]] for a in anns[iid]}))}


def main():
    out = Path(sys.argv[1])
    want = ("float", "fq") if "--no-chip" in sys.argv else ("float", "fq", "chip")
    arms = Arms(want)
    print("arms:", json.dumps(arms.info)[:400], flush=True)
    rows = []
    for n, r in enumerate(slice_rows()):
        gray = np.asarray(Image.open(IMG / r["file_name"]).convert("L"), np.uint8)
        r.update({k: (round(v, 4) if isinstance(v, float) else v)
                  for k, v in arms(gray).items()})
        rows.append(r)
        if (n + 1) % 100 == 0:
            print(f"  {n + 1} images", flush=True)
    arms.close()
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"n = {len(rows)}", flush=True)
    for arm in [k for k in rows[0] if k in ("float", "float_via244", "fq", "fq_via244", "chip", "chip_via244")]:
        v = np.array([r[arm] for r in rows])
        print(f"  {arm:12s} FP@0.45 {np.mean(v >= 0.45):.3f}  @0.55 {np.mean(v >= 0.55):.3f}  "
              f"@0.75 {np.mean(v >= 0.75):.3f}  mean {v.mean():.3f}", flush=True)
    print("wrote", out, flush=True)


if __name__ == "__main__":
    main()
