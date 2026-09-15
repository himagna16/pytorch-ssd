#!/usr/bin/env python3
"""Emit the FULL eligible subject pool, not a pick of two.

docs/eval_results/2026-09-15-typical-person/scripts/pick_subjects.py applied a
two-stage screen to the 266-person cohort and published a verdict for all 39
mechanically eligible subjects. Exactly 12 carry "keep". That study then chose
two of them, the median and the ~25th percentile. This script takes all 12.

NOTHING IS RE-SCORED AND NOTHING IS RE-SCREENED. The eligibility rule and the
by-eye verdicts are imported from pick_subjects.py rather than restated, so they
cannot drift from the published ones. The aggregation is pick_subjects.py's own
(chip arm, himax camera, dy = 0, mean over a subject's draws at each of the six
ladder ranges, then the mean of the six percentiles).

VERIFICATION. The three subjects the earlier study published in
tables/subject_picks.tsv are re-derived here and compared field by field. Any
mismatch is a hard failure, because it would mean this script's pool is not the
pool that was screened.

Usage: nemoenv/bin/python pick_all_eligible.py <outdir>
"""
import csv
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path("/Users/saimaruvada/Downloads/drone/pytorch_ssd")
FID = ROOT / "docs/eval_results/2026-09-15-sim-person-fidelity"
TYP = ROOT / "docs/eval_results/2026-09-15-typical-person"
sys.path.insert(0, str(FID / "scripts"))
sys.path.insert(0, str(TYP / "scripts"))
from shared_arms import relabel, CHAMPION_ARMS_SHA256          # noqa: E402
from pick_subjects import EYE, LADDER, SRC, ARM, RA, per_subject, pct  # noqa: E402

OUT = Path(sys.argv[1])
FIELDS = ["img_id", "ann_id", "index_pct", "pct_cohort_confmean", "photo_chip_via244",
          "bbox_w_px", "bbox_h_px", "aspect_hw", "panel_w_m", "px128_h_photo",
          "file_name"] + [f"pct_at_{r}m" for r in LADDER]


def main():
    real = {r["img_id"]: r for r in csv.DictReader(open(FID / "tables/real_people.csv"))}
    coh = relabel(list(csv.DictReader(open(FID / "tables/sim_cohort.csv"))), real)

    vals = {rng: per_subject(coh, rng) for rng in LADDER}
    ids = sorted(set.intersection(*[set(v) for v in vals.values()]))
    peers = [i for i in ids if i != SRC]
    prank = {i: {r: pct([vals[r][k] for k in peers], vals[r][i]) for r in LADDER} for i in ids}
    index = {i: float(np.mean([prank[i][r] for r in LADDER])) for i in ids}
    confmean = {i: float(np.mean([vals[r][i] for r in LADDER])) for i in ids}
    pct_confmean = {i: pct([confmean[k] for k in peers], confmean[i]) for i in ids}

    keep = sorted([i for i in EYE if EYE[i] == "keep"], key=lambda k: index[k])
    print(f"cohort {len(ids)} subjects, {len(peers)} peers, {len(EYE)} screened by eye, "
          f"{len(keep)} kept")
    assert len(keep) == 12, f"expected 12 keepers, got {len(keep)}"

    def row(i):
        r = real[i]
        bb = json.loads(r["subject_bbox"])
        asp = float(r["aspect_hw"])
        d = {"img_id": i, "ann_id": r["subject_ann_id"],
             "index_pct": round(index[i], 1),
             "pct_cohort_confmean": round(pct_confmean[i], 1),
             "photo_chip_via244": round(float(r[RA]), 4),
             "bbox_w_px": round(bb[2], 1), "bbox_h_px": round(bb[3], 1),
             "aspect_hw": round(asp, 3), "panel_w_m": round(1.7 / asp, 4),
             "px128_h_photo": r.get("px128_h_photo", ""),
             "file_name": r.get("file_name", "")}
        for rr in LADDER:
            d[f"pct_at_{rr}m"] = round(prank[i][rr], 1)
        return d

    rows = [row(i) for i in keep]
    ctl = row(SRC)

    # ---- verification against the committed table --------------------------
    prev = {r["img_id"]: r for r in
            csv.DictReader(open(TYP / "tables/subject_picks.tsv"), delimiter="\t")}
    checked, bad = 0, []
    for iid, pr in prev.items():
        mine = ctl if iid == SRC else next((r for r in rows if r["img_id"] == iid), None)
        if mine is None:
            bad.append(f"{iid}: published subject is absent from this pool")
            continue
        for f in ("index_pct", "pct_cohort_confmean", "photo_chip_via244",
                  "aspect_hw", "panel_w_m", "ann_id") + tuple(f"pct_at_{r}m" for r in LADDER):
            a, b = str(mine[f]), str(pr[f])
            try:
                same = abs(float(a) - float(b)) < 5e-4
            except ValueError:
                same = a == b
            checked += 1
            if not same:
                bad.append(f"{iid}.{f}: this script {a!r} vs published {b!r}")
    if bad:
        raise SystemExit("VERIFICATION FAILED\n  " + "\n  ".join(bad))
    print(f"verification: {checked} fields across {len(prev)} published subjects "
          f"reproduce exactly")

    (OUT / "tables").mkdir(parents=True, exist_ok=True)
    with open(OUT / "tables/pool.tsv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, delimiter="\t")
        w.writeheader()
        for r in rows + [ctl]:
            w.writerow(r)
    json.dump({"keepers": rows, "control": ctl,
               "scorer_sha256": CHAMPION_ARMS_SHA256,
               "screen": "imported from typical-person/scripts/pick_subjects.py, not restated"},
              open(OUT / "tables/pool.json", "w"), indent=1)

    print()
    print(f"{'img_id':>8}{'ann_id':>10}{'index':>8}{'panel_w_m':>11}{'aspect':>8}  per-range")
    for r in rows:
        pr = "/".join(f"{r[f'pct_at_{x}m']:.0f}" for x in LADDER)
        print(f"{r['img_id']:>8}{r['ann_id']:>10}{r['index_pct']:>8.1f}"
              f"{r['panel_w_m']:>11.4f}{r['aspect_hw']:>8.3f}  {pr}")
    pr = "/".join(f"{ctl[f'pct_at_{x}m']:.0f}" for x in LADDER)
    print(f"{ctl['img_id']:>8}{ctl['ann_id']:>10}{ctl['index_pct']:>8.1f}"
          f"{ctl['panel_w_m']:>11.4f}{ctl['aspect_hw']:>8.3f}  {pr}   <- CONTROL (not screened)")


if __name__ == "__main__":
    main()
