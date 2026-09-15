#!/usr/bin/env python3
"""Split the fidelity study's un-interrogated `occluded_or_truncated` stratum
into TRUNCATION and OCCLUSION, and grade how much of the body is in frame.

NOTHING IS RE-SCORED. Every confidence in this directory is read out of
  docs/eval_results/2026-09-15-sim-person-fidelity/tables/real_people.csv
  docs/eval_results/2026-09-15-sim-person-fidelity/tables/real_people_himax.csv
which already carry the RESOLUTION-MATCHED control column (`*_via244`) that the
fidelity study validated in its section 2. Re-deriving the strata is a join on
COCO's annotations, not a new scoring path, so the two sides of every comparison
below travel through exactly the same resampling chain by construction.

WHAT COCO LETS US SEPARATE
  v == 2  labelled and visible
  v == 1  labelled but NOT visible  -> COCO's own OCCLUSION annotation
  v == 0  not labelled at all       -> ambiguous: out of frame, or unannotatable

  truncation is therefore read GEOMETRICALLY, not from v:
    edge_trunc  the box touches the image border (2 px) - the photographer cut them
    crop_trunc  the box is not wholly inside the CENTRE SQUARE CROP - the same
                operation the firmware performs, so this is the closest analogue
                in COCO to a drone crop cutting a person off
    crop_vis_frac  the fraction of the box AREA that survives the centre crop,
                which is the graded version of crop_trunc and the quantity
                "how much of the person is in frame" actually means here

  occlusion is read from v == 1:
    occl_kp     at least one of the 17 keypoints is labelled-but-occluded

The 2x2 (trunc x occl) plus a `no_kp` bucket for the annotations COCO gave no
keypoints at all (num_keypoints == 0), which must not be silently counted as
"unoccluded" - there is no evidence either way for them.

Usage: nemoenv/bin/python strata.py <outdir>
"""
import csv
import json
import sys
from pathlib import Path

FID = Path("/Users/saimaruvada/Downloads/drone/pytorch_ssd/docs/eval_results/"
           "2026-09-15-sim-person-fidelity")
sys.path.insert(0, str(FID / "scripts"))
from shared_arms import INSTANCES, KEYPOINTS, CHAMPION_ARMS_SHA256  # noqa: E402

EDGE_MARGIN = 2.0


def main():
    D = Path(sys.argv[1])
    print(f"the scorer that produced the confidences (not invoked here): "
          f"champion_arms.py sha256 {CHAMPION_ARMS_SHA256}", flush=True)

    real = list(csv.DictReader(open(FID / "tables/real_people.csv")))
    print(f"read {len(real)} rows from the fidelity study's real_people.csv", flush=True)

    kps = json.loads(KEYPOINTS.read_text())
    kp_by_ann = {a["id"]: a for a in kps["annotations"]}
    inst = json.loads(INSTANCES.read_text())
    imgs = {i["id"]: i for i in inst["images"]}

    out = []
    for r in real:
        iid = int(r["img_id"])
        aid = int(r["subject_ann_id"])
        W, H = int(r["W"]), int(r["H"])
        crop = int(r["crop"])
        top, left = (H - crop) // 2, (W - crop) // 2
        x, y, w, h = json.loads(r["subject_bbox"])

        # --- geometry: how much of the box survives the network's centre crop
        x1, x2 = min(max(x - left, 0.0), crop), min(max(x + w - left, 0.0), crop)
        y1, y2 = min(max(y - top, 0.0), crop), min(max(y + h - top, 0.0), crop)
        crop_vis_frac = ((x2 - x1) * (y2 - y1)) / max(w * h, 1e-9)
        crop_vis_h = (y2 - y1) / max(h, 1e-9)
        crop_vis_w = (x2 - x1) / max(w, 1e-9)

        edge_trunc = int(x <= EDGE_MARGIN or y <= EDGE_MARGIN
                         or x + w >= W - EDGE_MARGIN or y + h >= H - EDGE_MARGIN)
        crop_trunc = int(int(r["wholly_in_centre_crop"]) == 0)
        # which border the photograph cut, so "head cut off" can be told from
        # "legs cut off" - a drone at close range cuts the HEAD (geometry_fov.py)
        cut_top = int(y <= EDGE_MARGIN)
        cut_bottom = int(y + h >= H - EDGE_MARGIN)
        cut_side = int(x <= EDGE_MARGIN or x + w >= W - EDGE_MARGIN)

        # --- COCO's own occlusion annotation
        kpa = kp_by_ann.get(aid)
        kp = kpa["keypoints"] if kpa else [0] * 51
        n_lab = sum(1 for i in range(17) if kp[3 * i + 2] > 0)
        n_v2 = sum(1 for i in range(17) if kp[3 * i + 2] == 2)
        n_v1 = sum(1 for i in range(17) if kp[3 * i + 2] == 1)
        no_kp = int(n_lab == 0)
        occl_kp = int(n_v1 > 0)

        trunc_any = int(edge_trunc or crop_trunc)

        if no_kp:
            cls = "no_keypoints"
        elif trunc_any and occl_kp:
            cls = "trunc_and_occl"
        elif trunc_any:
            cls = "trunc_only"
        elif occl_kp:
            cls = "occl_only"
        else:
            cls = "clean_other"        # neither flag fires but still not whole_upright
        if int(r["whole_upright"]):
            cls = "whole_upright"

        out.append({
            "img_id": iid, "subject_ann_id": aid, "file_name": r["file_name"],
            "px128_h": r["px128_h"], "px128_w": r["px128_w"],
            "whole_upright": r["whole_upright"], "wui": r["wui"],
            "isolated": r["isolated"], "is_sim_source": r["is_sim_source"],
            "n_person_anns": r["n_person_anns"], "n_crowd_person": r["n_crowd_person"],
            "upright": r["upright"], "aspect_hw": r["aspect_hw"],
            "edge_trunc": edge_trunc, "crop_trunc": crop_trunc, "trunc_any": trunc_any,
            "cut_top": cut_top, "cut_bottom": cut_bottom, "cut_side": cut_side,
            "occl_kp": occl_kp, "no_kp": no_kp,
            "n_kp_labelled": n_lab, "n_kp_v2": n_v2, "n_kp_v1": n_v1,
            "kp_vis_frac": round(n_v2 / 17.0, 4),
            "kp_lab_frac": round(n_lab / 17.0, 4),
            "kp_unoccl_frac": round(n_v2 / n_lab, 4) if n_lab else "",
            "crop_vis_frac": round(crop_vis_frac, 4),
            "crop_vis_h": round(crop_vis_h, 4), "crop_vis_w": round(crop_vis_w, 4),
            "cls": cls,
            "float": r["float"], "float_via244": r["float_via244"],
            "fq": r["fq"], "fq_via244": r["fq_via244"],
            "chip": r["chip"], "chip_via244": r["chip_via244"],
        })

    with open(D / "tables/strata.csv", "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=list(out[0].keys()))
        wr.writeheader()
        wr.writerows(out)

    # --- the same join onto the himax table (3 sensor draws per photograph)
    him = list(csv.DictReader(open(FID / "tables/real_people_himax.csv")))
    by_img = {str(r["img_id"]): r for r in out}
    keep = ("cls", "edge_trunc", "crop_trunc", "trunc_any", "occl_kp", "no_kp",
            "cut_top", "cut_bottom", "cut_side", "kp_vis_frac", "kp_lab_frac",
            "crop_vis_frac", "n_kp_labelled")
    hout = []
    for r in him:
        s = by_img.get(r["img_id"])
        if s is None:
            continue
        hout.append({**r, **{k: s[k] for k in keep}})
    with open(D / "tables/strata_himax.csv", "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=list(hout[0].keys()))
        wr.writeheader()
        wr.writerows(hout)

    # --- census
    print("\nCENSUS (2 693 val2017 images with a non-crowd person)")
    tot = len(out)
    for c in ("whole_upright", "trunc_only", "occl_only", "trunc_and_occl",
              "no_keypoints", "clean_other"):
        n = sum(1 for r in out if r["cls"] == c)
        print(f"  {c:16s} {n:5d}  {100*n/tot:5.1f}%")
    ot = [r for r in out if not int(r["whole_upright"])]
    print(f"\n  occluded_or_truncated total {len(ot)} "
          f"(fidelity study reports 2488 after dropping the sim source)")
    print(f"    truncated in any way        {sum(r['trunc_any'] for r in ot):5d}")
    print(f"      by the image edge         {sum(r['edge_trunc'] for r in ot):5d}")
    print(f"      by the centre crop        {sum(r['crop_trunc'] for r in ot):5d}")
    print(f"        cut at the TOP edge     {sum(r['cut_top'] for r in ot):5d}")
    print(f"        cut at the BOTTOM edge  {sum(r['cut_bottom'] for r in ot):5d}")
    print(f"        cut at a SIDE edge      {sum(r['cut_side'] for r in ot):5d}")
    print(f"    occlusion-flagged (v==1)    {sum(r['occl_kp'] for r in ot):5d}")
    print(f"    no keypoints annotated      {sum(r['no_kp'] for r in ot):5d}")
    print(f"\nwrote {D/'tables/strata.csv'} ({len(out)} rows) and "
          f"strata_himax.csv ({len(hout)} rows)")


if __name__ == "__main__":
    main()
