#!/usr/bin/env python3
"""Derive 24 scene definitions from s15_static_offset and s01_control_moving by
changing ONE thing each: which COCO person the cutout is.

Twelve subjects, two base scenes. Same edit as the typical-person study's
make_scene_defs.py, which produced four defs the same way and whose output is
committed; the difference is only that this covers the whole eligible pool
instead of two picks of it.

NOTHING UNDER tools/ IS WRITTEN. The typical-person study put its four defs in
tools/crazysim_macos/scene_defs/. These 24 go in this directory instead and are
handed to build_scene.py with --def, which takes arbitrary paths. Doubling a
shared directory for one experiment is not worth it.

Keys edited, all of which are the identity of the person or free text:
    scene_id, title, purpose      (new / free text)
    subjects[0].coco              img_id / ann_id  <- THE ONLY SUBSTANTIVE CHANGE
    subjects[0].note              free text
    prediction.outcome/rationale  free text; scoreboard.py never reads them

Everything else is carried over by reference: lighting, preview_cam_x, the
subject's name, role, height_m, pos, motion, the whole expected_behaviour block
including its gates and its target, scene_class, and prediction.model.

Usage: nemoenv/bin/python make_pool_scenes.py <outdir>
"""
import json
import sys
from pathlib import Path

ROOT = Path("/Users/saimaruvada/Downloads/drone/pytorch_ssd")
DEFS = ROOT / "tools/crazysim_macos/scene_defs"
OUT = Path(sys.argv[1])
POOL = json.loads((OUT / "tables/pool.json").read_text())
CTL = POOL["control"]

BASES = [("s15_static_offset", "pp15"), ("s01_control_moving", "pp01")]

NOTE = (
    "PEOPLE-PLURAL POOL, 2026-09-15. Identical to {base}.json except for the COCO "
    "cutout: img {img}/ann {ann} replaces img 19432/ann 428692. Same subject name, "
    "role, height_m 1.7, pos, motion, lighting, expected_behaviour (target and "
    "gates), scene_class and matte floor. The panel's WIDTH follows from this "
    "cutout's own bbox aspect ({asp} h/w -> {w} m at 1.7 m tall, against the flown "
    "cutout's 2.627 -> 0.6471 m). That is a property of which person it is rather "
    "than an independent change, and it is the only geometric consequence, but it "
    "is NOT held constant across the pool: width runs 0.5493-0.8004 m and "
    "correlates with the detectability index at Spearman +0.385, so the analysis "
    "must carry it as a covariate and not read the raw trend as a pure subject "
    "effect. "
    "WHY THIS PERSON: no reason particular to them. This scene is one of 12 built "
    "from every subject carrying eye_verdict == keep in the pre-registered screen "
    "of docs/eval_results/2026-09-15-typical-person (12 of 39 mechanically "
    "eligible, published there in full). Taking the whole pool is what removes "
    "subject selection from this experiment. This subject sits at the {idx}th "
    "percentile of the 266-person cohort of "
    "docs/eval_results/2026-09-15-sim-person-fidelity (per range {perrange}), "
    "against the flown cutout's 99.2nd; its own photograph scores {photo} on the "
    "chip arm through the resolution-matched chain. Pool derivation: "
    "scripts/pick_all_eligible.py, which imports the screen rather than restating "
    "it and reproduces the earlier study's three published subjects field for "
    "field. No score was re-computed for any subject."
)

RATIONALE = (
    "Unknown, and that is the measurement. Every published person tracking "
    "fraction (0.97-0.99) comes from one cutout that the fidelity study places at "
    "the 99.2nd percentile of rendered detectability. Flying the whole screened "
    "pool turns that single number into a distribution. Static frames cannot "
    "answer it: per-frame rates do not multiply into a loss-of-track fraction, "
    "because consecutive frames are correlated and the follower has hysteresis "
    "(3 frames at 0.75 to latch, below 0.45 to let go)."
)


def main():
    outdir = OUT / "scene_defs"
    outdir.mkdir(parents=True, exist_ok=True)
    made = []
    for base_id, pref in BASES:
        base = json.loads((DEFS / f"{base_id}.json").read_text())
        assert len(base["subjects"]) == 1, base_id
        assert base["subjects"][0]["coco"] == {"img_id": 19432, "ann_id": 428692}
        for p in POOL["keepers"]:
            img, ann = int(p["img_id"]), int(p["ann_id"])
            d = json.loads(json.dumps(base))          # deep copy, base untouched
            new_id = f"{pref}_{img}"
            s = d["subjects"][0]
            d["scene_id"] = new_id
            d["title"] = f"{base['title']} - pool subject COCO {img} (index {p['index_pct']})"
            d["purpose"] = (
                f"People-plural variant of {base_id}, one of 24. The published person "
                f"cells were built with COCO 19432/428692, which sits at the 99.2nd "
                f"percentile of rendered detectability among 266 real people. This is "
                f"that scene with a different screened person in it and nothing else "
                f"changed. Flown as part of a 13-arm suite so the answer is a "
                f"distribution rather than a second anecdote. Not part of the "
                f"acceptance matrix; run_acceptance2.sh does not reference it, and this "
                f"definition lives outside tools/."
            )
            s["coco"] = {"img_id": img, "ann_id": ann}
            s["note"] = NOTE.format(
                base=base_id, img=img, ann=ann, asp=p["aspect_hw"], w=p["panel_w_m"],
                idx=p["index_pct"], photo=p["photo_chip_via244"],
                perrange="/".join(str(p[f"pct_at_{r}m"]) for r in
                                  ("1.5", "2.0", "2.5", "3.0", "3.5", "4.0")))
            d["prediction"] = {"model": d["prediction"]["model"],
                               "outcome": "unknown - this is the measurement",
                               "rationale": RATIONALE}
            out = outdir / f"{new_id}.json"
            if out.exists():
                raise SystemExit(f"{out} exists - refusing to overwrite")
            out.write_text(json.dumps(d, indent=2) + "\n")
            made.append((base_id, new_id, img, p["index_pct"]))

    # the control arm reuses the ORIGINAL defs, unmodified and not copied
    print(f"wrote {len(made)} scene definitions to {outdir}")
    print(f"control arm flies {BASES[0][0]}.json and {BASES[1][0]}.json unchanged, "
          f"from tools/crazysim_macos/scene_defs/")
    print()
    for b, n, i, idx in made:
        print(f"  {n:<14} from {b:<20} COCO {i:<8} index {idx}")


if __name__ == "__main__":
    main()
