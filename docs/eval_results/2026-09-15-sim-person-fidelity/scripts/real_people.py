#!/usr/bin/env python3
"""REAL side: the champion's confidence on real COCO PERSON photographs, with
each person's apparent size measured in the network's own 128x128 input.

APPARENT SIZE is computed by exactly the arithmetic the pet study's
`real_pets.py` uses, so the quantity is identical on both studies and on both
sides of this one:

    crop  = min(W, H);  top = (H - crop)//2;  left = (W - crop)//2
    y1,y2 = clamp(box_y - top, 0, crop)        # the centre crop can cut the subject
    px128 = (y2 - y1) * 128 / crop

which is what utils/transforms.CenterCropSquare + ResizeImage do to a box, and
what build_scene.run_model does to a frame. An image's subject is its LARGEST
non-crowd person annotation by clamped height.

THE INCLUSION RULE, and why. There are 2 693 val2017 images with a person, so
unlike the pet study this side can afford to be selective. Four nested sets are
written, every row carrying its flags so any of them can be rebuilt:

  all_people   every val2017 image with at least one non-crowd person
               annotation. The broad set: statistical weight, no pose control.
  whole_upright
               the subject is WHOLE, UNOCCLUDED, UNTRUNCATED and UPRIGHT:
                 * both shoulders, both hips, both knees and both ankles are
                   labelled v == 2 ("visible") in person_keypoints_val2017,
                   and at least one head keypoint is visible. v == 1 means
                   "labelled but occluded", so this is COCO's own occlusion
                   annotation and not a proxy invented here;
                 * the box does not touch the image border (2 px margin) - not
                   truncated by the photograph's own edge;
                 * the box lies wholly inside the CENTRE CROP in BOTH axes, so
                   px128_h is an unclamped height and the network is actually
                   shown the person (the sim side's `visible_fraction` ~ 1);
                 * box aspect h/w >= 2.0 AND the shoulder-to-ankle span is at
                   least 55% of the box height - standing, not seated or lying.
  wui          whole_upright AND ISOLATED: exactly one non-crowd person
               annotation in the image and no crowd person region. This is the
               closest real analogue to what the drone is meant to follow, and
               to what the simulator renders - one whole standing person, alone.
  occluded_or_truncated
               all_people minus whole_upright. Reported as its own stratum
               rather than discarded, because the drone will meet these too.

The simulator's own source photograph (COCO 19432 / ann 428692, the cutout BOTH
person cells of the CORE matrix use) is flagged `is_sim_source` and excluded
from every comparison set, so the sim is never compared against itself. It is
measured on its own in the same-image section.

Usage: nemoenv/bin/python real_people.py <out_csv> [--no-chip] [--limit N]
"""
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from shared_arms import (Arms, IMG_DIR, INSTANCES, KEYPOINTS,  # noqa: E402
                         SIM_SOURCE_ANN_ID, SIM_SOURCE_IMG_ID, CHAMPION_ARMS_SHA256)

PERSON = 1
SHOULDERS, HIPS, KNEES, ANKLES = [5, 6], [11, 12], [13, 14], [15, 16]
HEAD = [0, 1, 2, 3, 4]
EDGE_MARGIN = 2.0
MIN_AR = 2.0
MIN_SPAN = 0.55


def _v(kp, i):
    return kp[3 * i + 2]


def _y(kp, i):
    return kp[3 * i + 1]


def slice_rows():
    """Every val2017 image with a non-crowd person, its subject, and its flags."""
    inst = json.loads(INSTANCES.read_text())
    imgs = {i["id"]: i for i in inst["images"]}
    per_img = defaultdict(list)
    for a in inst["annotations"]:
        if a["category_id"] == PERSON:
            per_img[a["image_id"]].append(a)

    kps = json.loads(KEYPOINTS.read_text())
    kp_by_ann = {a["id"]: a for a in kps["annotations"]}

    for iid in sorted(per_img):
        info = imgs[iid]
        W, H = int(info["width"]), int(info["height"])
        crop = min(W, H)
        top, left = (H - crop) // 2, (W - crop) // 2
        noncrowd = [a for a in per_img[iid] if not a.get("iscrowd", 0)]
        n_crowd = sum(1 for a in per_img[iid] if a.get("iscrowd", 0))
        if not noncrowd:
            continue
        best = None
        for a in noncrowd:
            x, y, w, h = a["bbox"]
            y1, y2 = min(max(y - top, 0.0), crop), min(max(y + h - top, 0.0), crop)
            x1, x2 = min(max(x - left, 0.0), crop), min(max(x + w - left, 0.0), crop)
            px128 = (y2 - y1) * 128.0 / crop
            if best is None or px128 > best["px128_h"]:
                best = {"ann": a, "px128_h": px128, "px128_w": (x2 - x1) * 128.0 / crop,
                        "px128_h_nocrop": h * 128.0 / crop}
        a = best["ann"]
        x, y, w, h = a["bbox"]
        kpa = kp_by_ann.get(a["id"])
        kp = kpa["keypoints"] if kpa else [0] * 51
        n_kp_vis = sum(1 for i in range(17) if _v(kp, i) == 2)
        whole = (all(_v(kp, i) == 2 for i in SHOULDERS + HIPS + KNEES + ANKLES)
                 and any(_v(kp, i) == 2 for i in HEAD))
        span = 0.0
        if whole:
            span = (np.mean([_y(kp, i) for i in ANKLES])
                    - np.mean([_y(kp, i) for i in SHOULDERS])) / max(h, 1e-9)
        touches_edge = (x <= EDGE_MARGIN or y <= EDGE_MARGIN
                        or x + w >= W - EDGE_MARGIN or y + h >= H - EDGE_MARGIN)
        # The centre square crop cuts in BOTH axes. Checking only the vertical
        # (px128_h == px128_h_nocrop) lets through a person standing at the left
        # or right edge of a landscape photograph whom the crop removes almost
        # entirely - COCO 197870 is one: box x 505-578 of a 640x425 image, whose
        # centre crop is x 107-532, so the network sees 27 px of a 73 px-wide
        # person and scores the bench beside them. Both axes, or the "whole
        # person" stratum is not whole.
        in_crop_v = abs(best["px128_h"] - best["px128_h_nocrop"]) < 1e-6
        in_crop_h = (x - left >= -1e-6) and (x + w - left <= crop + 1e-6)
        in_crop = bool(in_crop_v and in_crop_h)
        ar = h / max(w, 1e-9)
        upright = ar >= MIN_AR and span >= MIN_SPAN
        whole_upright = bool(whole and upright and not touches_edge and in_crop)
        isolated = len(noncrowd) == 1 and n_crowd == 0
        yield {
            "img_id": iid, "file_name": info["file_name"], "W": W, "H": H, "crop": crop,
            "subject_ann_id": a["id"],
            "subject_bbox": json.dumps([round(float(v), 1) for v in a["bbox"]]),
            "px128_h": round(best["px128_h"], 2), "px128_w": round(best["px128_w"], 2),
            "px128_h_nocrop": round(best["px128_h_nocrop"], 2),
            "n_person_anns": len(noncrowd), "n_crowd_person": n_crowd,
            "n_kp_visible": n_kp_vis, "aspect_hw": round(ar, 3),
            "shoulder_ankle_span": round(float(span), 3),
            "whole_unoccluded": int(bool(whole)), "touches_image_edge": int(bool(touches_edge)),
            "wholly_in_centre_crop": int(in_crop), "in_crop_vertical": int(in_crop_v),
            "in_crop_horizontal": int(in_crop_h), "upright": int(bool(upright)),
            "whole_upright": int(whole_upright), "isolated": int(isolated),
            "wui": int(whole_upright and isolated),
            "is_sim_source": int(iid == SIM_SOURCE_IMG_ID and a["id"] == SIM_SOURCE_ANN_ID),
        }


def main():
    out = Path(sys.argv[1])
    want = ("float", "fq") if "--no-chip" in sys.argv else ("float", "fq", "chip")
    limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else None
    print(f"champion_arms.py sha256 {CHAMPION_ARMS_SHA256}", flush=True)
    arms = Arms(want)
    print("arms:", json.dumps(arms.info)[:400], flush=True)
    rows = []
    for n, r in enumerate(slice_rows()):
        if limit is not None and n >= limit:
            break
        gray = np.asarray(Image.open(IMG_DIR / r["file_name"]).convert("L"), np.uint8)
        r.update({k: (round(v, 4) if isinstance(v, float) else v) for k, v in arms(gray).items()})
        rows.append(r)
        if (n + 1) % 200 == 0:
            print(f"  {n + 1} images", flush=True)
    arms.close()
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    print(f"\nn = {len(rows)} images with a non-crowd person", flush=True)
    for name, f in (("all_people", lambda r: True),
                    ("whole_upright", lambda r: r["whole_upright"]),
                    ("wui (whole+upright+isolated)", lambda r: r["wui"]),
                    ("occluded_or_truncated", lambda r: not r["whole_upright"])):
        sub = [r for r in rows if f(r)]
        print(f"  {name:30s} n = {len(sub)}", flush=True)
    print(f"  sim source photograph present: {sum(r['is_sim_source'] for r in rows)}", flush=True)
    print("\nwhole-slice rates (NOT the comparison - see analyze_person.py):", flush=True)
    for arm in [k for k in rows[0] if k in ("float", "float_via244", "fq", "fq_via244",
                                            "chip", "chip_via244")]:
        v = np.array([r[arm] for r in rows], float)
        print(f"  {arm:12s} >=0.45 {np.mean(v >= 0.45):.3f}  >=0.75 {np.mean(v >= 0.75):.3f}  "
              f"<0.45 {np.mean(v < 0.45):.3f}  median {np.median(v):.3f}", flush=True)
    print("wrote", out, flush=True)


if __name__ == "__main__":
    main()
