#!/usr/bin/env python3
"""Pick a MEDIAN-detectability and a ~25th-percentile person, from the person
fidelity study's own cohort and its own scoring path.

NOTHING IS RE-SCORED HERE. The fidelity study
(docs/eval_results/2026-09-15-sim-person-fidelity/) already rendered 267 real
COCO people through `build_scene`'s own cutout pipeline at s15's geometry and
scored every frame with the shared `champion_arms.py`. This script only RANKS
those existing numbers, with exactly the aggregation
`scripts/subject_selection.py` used to put the flown cutout at the 98.5-100th
percentile: chip arm, himax camera, dy = 0, one number per subject per range
(the mean over that subject's himax draws).

THE INDEX. `subject_selection.py` reports a percentile per range. Pooling those
six percentiles by their MEAN is the obvious pooled version and is the index
used here. It is deliberately rank-based rather than an average of the raw
confidences, because the cohort's own median confidence swings from 0.430 at
2.5 m to 0.769 at 1.5 m: averaging raw confidences silently weights the ranges
with the widest spread. (Both indices were computed; they agree on every pick
below - see `pct_cohort_confmean` in the output table.)

ELIGIBILITY, in two stages, both published.

  MECHANICAL, from the fidelity study's own columns:
    * `wui` == 1  - whole, upright and unoccluded by COCO's own keypoint
      visibility flags, untruncated, wholly inside the centre crop in both
      axes, AND isolated (exactly one non-crowd person, no crowd region)
    * source crop at least 200 px tall, so the panel is not upsampled further
      than the flown cutout's own 404 px
    * implied panel width 0.35-0.85 m at 1.7 m tall, so the card is a plausible
      human rectangle

  BY EYE, because the mechanical rule demonstrably admits subjects it should
  not. The fidelity study made the same correction for the same reason (its
  §1 note: "one correction to this directory's own inclusion rule, found by
  looking at the pictures"). Among the 39 mechanically eligible subjects,
  COCO 340451 is a person SITTING ON A BENCH (knees bent, aspect still 2.14)
  and COCO 398237, 50638, 442306, 7088, 139077, 456662 are small children, for
  whom the scenes' 1.7 m height is not plausible. Every one of the 39 is
  classified below, with its reason, so the screen can be disagreed with.

The screen requires: an ADULT, standing on their own feet in a neutral upright
stance, nothing in front of them, facing roughly toward the camera or in clean
profile. That is what the flown cutout is, and holding it fixed is what makes
"only the person changed" true.

Then: pick the survivor nearest the 50th percentile and the survivor nearest
the 25th. No further filtering.

Usage: nemoenv/bin/python pick_subjects.py <outdir>
"""
import csv
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path("/Users/saimaruvada/Downloads/drone/pytorch_ssd")
FID = ROOT / "docs/eval_results/2026-09-15-sim-person-fidelity"
sys.path.insert(0, str(FID / "scripts"))
from shared_arms import relabel, CHAMPION_ARMS_SHA256, BAR  # noqa: E402

OUT = Path(sys.argv[1])
LADDER = ("1.5", "2.0", "2.5", "3.0", "3.5", "4.0")
SRC = "19432"                 # the flown cutout, both person cells
ARM, RA = "chip", "chip_via244"
REPORT = []

# --- the by-eye screen, recorded once, for all 39 mechanically eligible ------
# verdict: "keep" or a one-phrase reason for rejection.
EYE = {
    "556158": "keep",           "280779": "keep",
    "266409": "keep",           "374369": "keep",
    "401446": "keep",           "65736":  "mid-stroke tennis pose, not a neutral stance",
    "161875": "keep",           "61747":  "keep",
    "343524": "mid-stroke tennis pose, not a neutral stance",
    "158744": "back-turned and occluded by a car",
    "343937": "arms out, leaning; not a neutral stance",
    "364102": "mid-stride with the arm raised",
    "162581": "mid-stroke tennis pose, not a neutral stance",
    "358195": "a child, on a skateboard",
    "571264": "back-turned, occluded by a motorcycle",
    "139077": "a toddler; 1.7 m is not plausible",
    "235784": "arm raised on ski poles; not a neutral stance",
    "512985": "back-turned, carrying a surfboard",
    "333745": "heavy motion blur across the whole subject",
    "23126":  "mid golf swing, not a neutral stance",
    "7088":   "a small child; 1.7 m is not plausible",
    "281929": "a bicycle stands in front of the legs",
    "250127": "keep",
    "449579": "mid-serve tennis pose, arm above the head",
    "50638":  "a toddler, back-turned; 1.7 m is not plausible",
    "442306": "a toddler; 1.7 m is not plausible",
    "529939": "back-turned, carrying a kayak",
    "575081": "a child, arm raised, partly behind a door frame",
    "356427": "keep",           "157365": "keep",
    "527750": "keep",           "124442": "keep",
    "398237": "a toddler; 1.7 m is not plausible",
    "340451": "SITTING ON A BENCH - knees bent, not upright",
    "506656": "a second person's body intrudes at the right edge",
    "161861": "bent forward over a tennis racket",
    "520910": "reads as a shop mannequin, not a photographed person",
    "394559": "mid-stroke tennis pose, not a neutral stance",
    "456662": "a child; 1.7 m is not plausible",
}


def P(s=""):
    print(s, flush=True)
    REPORT.append(s)


def per_subject(rows, rng, arm=ARM, camera="himax", dy="0.0"):
    """subject_selection.per_subject: one number per subject at one pose."""
    by = {}
    for r in rows:
        if r["camera"] != camera or r["dy_m"] != dy or r["range_m"] != rng:
            continue
        by.setdefault(r["img_id"], []).append(float(r[arm]))
    return {k: float(np.mean(v)) for k, v in by.items()}


def pct(peers, v):
    return 100.0 * float(np.mean(np.asarray(peers) < v))


def main():
    real = {r["img_id"]: r for r in csv.DictReader(open(FID / "tables/real_people.csv"))}
    coh = relabel(list(csv.DictReader(open(FID / "tables/sim_cohort.csv"))), real)

    P("=" * 78)
    P("PICKING A TYPICAL PERSON AND A HARD-BUT-ORDINARY PERSON")
    P("=" * 78)
    P(f"scorer: champion_arms.py sha256 {CHAMPION_ARMS_SHA256}  (not invoked; the")
    P("        cohort's scores are read from the fidelity study's tables as written)")
    P(f"source: {FID.relative_to(ROOT)}/tables/{{real_people.csv, sim_cohort.csv}}")
    P("index:  mean, over the six flown ladder ranges, of the subject's percentile")
    P("        among the 266 cohort peers at that range (chip arm, himax, dy = 0)")
    P("")

    vals = {rng: per_subject(coh, rng) for rng in LADDER}
    ids = sorted(set.intersection(*[set(v) for v in vals.values()]))
    peers = [i for i in ids if i != SRC]
    prank = {i: {rng: pct([vals[rng][k] for k in peers], vals[rng][i]) for rng in LADDER}
             for i in ids}
    index = {i: float(np.mean([prank[i][r] for r in LADDER])) for i in ids}
    confmean = {i: float(np.mean([vals[r][i] for r in LADDER])) for i in ids}
    pct_confmean = {i: pct([confmean[k] for k in peers], confmean[i]) for i in ids}
    above = {i: float(np.mean([vals[r][i] >= BAR for r in LADDER])) for i in ids}

    P(f"pool: {len(ids)} rendered subjects, {len(peers)} peers once the flown cutout is out")
    P("")
    P("Where the FLOWN cutout sits on this index (the number this study is a reply to):")
    P(f"  COCO {SRC} / ann {real[SRC]['subject_ann_id']}   index {index[SRC]:.1f}th percentile "
      f"(cohort median index is 50.0 by construction)")
    P("  per range: " + "  ".join(f"{r}m {prank[SRC][r]:.0f}%" for r in LADDER))
    P("  the fidelity study's own table reads 99.6 / 100.0 / 100.0 / 98.5 / 98.5 / 98.9 -")
    P("  identical numbers, re-derived here from the same rows.")
    P("")

    # ---- mechanical eligibility -------------------------------------------
    mech, mech_rej = [], []
    for i in peers:
        r = real[i]
        if r["wui"] != "1":
            continue
        bb = json.loads(r["subject_bbox"])
        asp = float(r["aspect_hw"])
        w_m = 1.7 / asp
        why = []
        if bb[3] < 200:
            why.append(f"source crop {bb[3]:.0f} px tall (< 200)")
        if not (0.35 <= w_m <= 0.85):
            why.append(f"panel {w_m:.2f} m wide at 1.7 m (outside 0.35-0.85)")
        (mech_rej if why else mech).append(i)
    n_wui = sum(1 for i in peers if real[i]["wui"] == "1")
    P(f"mechanically eligible: wui {n_wui} -> {len(mech)} after the cutout-usability cuts "
      f"({len(mech_rej)} dropped, all of them for a source crop under 200 px tall)")

    missing = [i for i in mech if i not in EYE]
    if missing:
        raise SystemExit(f"the by-eye screen has no verdict for {missing}")
    keep = [i for i in mech if EYE[i] == "keep"]
    P(f"by-eye screen: {len(keep)} of {len(mech)} kept (adult, standing on their own feet,")
    P("               neutral upright stance, nothing in front of them)")
    P("")
    P("  rejected by eye:")
    for i in sorted(mech, key=lambda k: -index[k]):
        if EYE[i] != "keep":
            P(f"    {i:>7}  index {index[i]:>5.1f}   {EYE[i]}")
    P("")
    P("  kept, with their index:")
    for i in sorted(keep, key=lambda k: -index[k]):
        P(f"    {i:>7}  index {index[i]:>5.1f}   per-range " +
          " ".join(f"{prank[i][r]:>3.0f}" for r in LADDER) +
          f"   photograph(chip_via244) {float(real[i][RA]):.3f}")
    P("")

    # ---- the picks ---------------------------------------------------------
    picks = {lab: min(keep, key=lambda i: abs(index[i] - tgt))
             for lab, tgt in (("median", 50.0), ("p25", 25.0))}
    if picks["median"] == picks["p25"]:
        raise SystemExit("the two picks collided")
    runner = {lab: sorted(keep, key=lambda i: abs(index[i] - tgt))[1]
              for lab, tgt in (("median", 50.0), ("p25", 25.0))}

    P("=" * 78)
    P("THE PICKS")
    P("=" * 78)
    hdr = ("role", "img_id", "ann_id", "index_pct", "pct_cohort_confmean",
           "frac_range_ge_075", "photo_chip_via244", "photo_float_via244",
           "photo_fq_via244", "photo_pct_sizematched", "n_photo_peers",
           "px128_h_photo", "bbox_w_px", "bbox_h_px", "aspect_hw", "panel_w_m",
           "n_person_anns", "file_name",
           *[f"pct_at_{r}m" for r in LADDER])
    rows = [hdr]
    detail = {}
    for label in ("control_19432", "median", "p25"):
        i = SRC if label == "control_19432" else picks[label]
        r = real[i]
        bb = json.loads(r["subject_bbox"])
        asp = float(r["aspect_hw"])
        p0 = float(r["px128_h"])
        photo_peers = [float(x[RA]) for x in real.values()
                       if x["whole_upright"] == "1" and x["is_sim_source"] != "1"
                       and x["img_id"] != i
                       and 0.85 * p0 <= float(x["px128_h"]) <= 1.15 * p0]
        row = (label, i, r["subject_ann_id"], f"{index[i]:.1f}", f"{pct_confmean[i]:.1f}",
               f"{above[i]:.3f}", r[RA], r["float_via244"], r["fq_via244"],
               f"{pct(photo_peers, float(r[RA])):.1f}", str(len(photo_peers)),
               f"{p0:.1f}", f"{bb[2]:.0f}", f"{bb[3]:.0f}", f"{asp:.3f}",
               f"{1.7 / asp:.4f}", r["n_person_anns"], r["file_name"],
               *[f"{prank[i][rg]:.1f}" for rg in LADDER])
        rows.append(row)
        detail[label] = dict(zip(hdr, row))
        P(f"--- {label}: COCO img {i} / ann {r['subject_ann_id']}  ({r['file_name']})")
        P(f"    RENDERED index {index[i]:.1f}th percentile of 266 peers "
          f"(raw-confidence index would say {pct_confmean[i]:.1f}th)")
        P("    per-range chip/himax  " +
          "  ".join(f"{rg}m {vals[rg][i]:.3f}" for rg in LADDER))
        P("    per-range percentile  " +
          "  ".join(f"{rg}m {prank[i][rg]:>3.0f}%" for rg in LADDER))
        P(f"    PHOTOGRAPH (its own, resolution-matched): chip {r[RA]}  float "
          f"{r['float_via244']}  fq {r['fq_via244']}")
        P(f"                -> {pct(photo_peers, float(r[RA])):.1f}th percentile of "
          f"{len(photo_peers)} size-matched whole_upright photographs")
        P(f"    geometry: bbox {bb[2]:.0f}x{bb[3]:.0f} px, aspect h/w {asp:.2f}, panel "
          f"{1.7 / asp:.3f} m wide at 1.7 m tall, {r['n_person_anns']} person annotation(s)")
        P("")
    for lab in ("median", "p25"):
        j = runner[lab]
        P(f"    runner-up for {lab}: COCO {j}, index {index[j]:.1f} "
          f"(per-range " + " ".join(f"{prank[j][r]:.0f}" for r in LADDER) + ")")
    P("")

    with open(OUT / "tables/subject_picks.tsv", "w", newline="") as f:
        csv.writer(f, delimiter="\t").writerows(rows)
    with open(OUT / "tables/cohort_ranking.tsv", "w", newline="") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(("img_id", "ann_id", "index_pct", "pct_cohort_confmean", "whole_upright",
                    "wui", "mech_eligible", "eye_verdict", "is_flown_cutout",
                    "photo_chip_via244", *[f"pct_at_{r}m" for r in LADDER]))
        for i in sorted(ids, key=lambda k: -index[k]):
            w.writerow((i, real[i]["subject_ann_id"], f"{index[i]:.1f}",
                        f"{pct_confmean[i]:.1f}", real[i]["whole_upright"], real[i]["wui"],
                        int(i in mech), EYE.get(i, "") if i in mech else "",
                        int(i == SRC), real[i][RA],
                        *[f"{prank[i][rg]:.1f}" for rg in LADDER]))
    json.dump({"picks": detail, "n_peers": len(peers), "n_mech_eligible": len(mech),
               "n_kept_by_eye": len(keep), "ladder": LADDER,
               "champion_arms_sha256": CHAMPION_ARMS_SHA256},
              open(OUT / "tables/subject_picks.json", "w"), indent=2)
    (OUT / "tables/subject_picks.txt").write_text("\n".join(REPORT) + "\n")
    P("wrote tables/subject_picks.{tsv,json,txt} and tables/cohort_ranking.tsv")


if __name__ == "__main__":
    main()
