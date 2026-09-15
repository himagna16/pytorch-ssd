#!/usr/bin/env python3
"""Derive four NEW scene definitions from s15_static_offset and s01_control_moving
by changing ONE thing: which COCO person the cutout is.

The new defs are produced by loading each original def and editing exactly these
keys, all of which are either the identity of the person or free text:

    scene_id            (new, so nothing can be confused with the original)
    title, purpose      free text
    subjects[0].coco    img_id / ann_id  <- THE ONLY SUBSTANTIVE CHANGE
    subjects[0].note    free text

Everything else is carried over by reference from the original dict: lighting,
preview_cam_x, the subject's `name`, `role`, `height_m`, `pos`, `motion`, the
whole `expected_behaviour` block including its gates and its `target`, and
`prediction`.`model`. `prediction.outcome`/`rationale` are free text and are
rewritten, because copying "passes" into a scene built to test whether it passes
would be dishonest; `scoreboard.py` never reads them (it builds its gates from
`scene_class`), and it reads `expected_behaviour.target`, which is unchanged.

The originals are opened read-only and are not rewritten.

Usage: nemoenv/bin/python make_scene_defs.py <outdir>
"""
import json
import sys
from pathlib import Path

ROOT = Path("/Users/saimaruvada/Downloads/drone/pytorch_ssd")
DEFS = ROOT / "tools/crazysim_macos/scene_defs"
OUT = Path(sys.argv[1])

PICKS = json.loads((OUT / "tables/subject_picks.json").read_text())["picks"]

# base scene -> (new id suffix, which pick)
PLAN = [
    ("s15_static_offset", "tp15_static_median", "median"),
    ("s15_static_offset", "tp15_static_p25", "p25"),
    ("s01_control_moving", "tp01_moving_median", "median"),
    ("s01_control_moving", "tp01_moving_p25", "p25"),
]

ROLE_EN = {"median": "a MEDIAN-detectability person", "p25": "a ~25th-percentile person"}

NOTE = (
    "TYPICAL-PERSON VARIANT, 2026-09-15. Byte-identical to {base}.json except for "
    "the COCO cutout: img {img}/ann {ann} replaces img 19432/ann 428692. Same "
    "subject name, same role, same height_m 1.7, same pos, same motion, same "
    "lighting, same expected_behaviour (target and gates), same matte floor. "
    "The panel's WIDTH follows from the cutout's own bbox aspect "
    "({asp} h/w -> {w} m at 1.7 m tall, against the flown cutout's 2.627 -> "
    "0.647 m); that is a property of which person it is, not an independent "
    "change, and it is the only geometric consequence. "
    "WHY THIS PERSON: {role}. Rendered through build_scene's own cutout pipeline "
    "at s15's geometry it sits at the {idx}th percentile of the 266-person cohort "
    "of docs/eval_results/2026-09-15-sim-person-fidelity (per range "
    "{perrange}), against the flown cutout's 99.2nd. Its own photograph scores "
    "{photo} on the chip arm through the resolution-matched chain, the {ppct}th "
    "percentile of {npeers} size-matched whole-upright photographs. "
    "Selection is docs/eval_results/2026-09-15-typical-person/scripts/pick_subjects.py; "
    "no score was re-computed for it."
)


def main():
    made = []
    for base_id, new_id, role in PLAN:
        d = json.loads((DEFS / f"{base_id}.json").read_text())
        p = PICKS[role]
        img, ann = int(p["img_id"]), int(p["ann_id"])
        s = d["subjects"][0]
        assert len(d["subjects"]) == 1, base_id
        assert s["coco"] == {"img_id": 19432, "ann_id": 428692}, s["coco"]
        old_title = d["title"]
        d["scene_id"] = new_id
        d["title"] = f"{old_title} - {ROLE_EN[role]} (COCO {img})"
        d["purpose"] = (
            f"Typical-person variant of {base_id}. The published person cells were built "
            f"with COCO 19432/428692, which the 2026-09-15 person fidelity study places at "
            f"the 98.5-100th percentile of rendered detectability among 266 real people. "
            f"This scene is that scene with {ROLE_EN[role]} in it and nothing else changed, "
            f"so a flight against it measures how much of the published 0.97-0.99 tracking "
            f"fraction is a property of the subject rather than of the perception system. "
            f"Not part of the acceptance matrix; run_acceptance2.sh does not reference it."
        )
        s["coco"] = {"img_id": img, "ann_id": ann}
        s["note"] = NOTE.format(
            base=base_id, img=img, ann=ann, role=ROLE_EN[role],
            asp=p["aspect_hw"], w=p["panel_w_m"], idx=p["index_pct"],
            perrange="/".join(f"{p['pct_at_' + r + 'm']}" for r in
                              ("1.5", "2.0", "2.5", "3.0", "3.5", "4.0")),
            photo=p["photo_chip_via244"], ppct=p["photo_pct_sizematched"],
            npeers=p["n_photo_peers"])
        d["prediction"] = {
            "model": d["prediction"]["model"],
            "outcome": "unknown - this is the measurement",
            "rationale": (
                "The fidelity study's static-frame result predicts more time below the 0.45 "
                "exit bar than the flown cutout ever shows (0 of 282 frames), but it states "
                "explicitly that per-frame rates cannot be multiplied into a loss-of-track "
                "fraction, because consecutive frames are correlated and the follower has "
                "hysteresis. That is what this flight measures."
            ),
        }
        out = DEFS / f"{new_id}.json"
        if out.exists():
            raise SystemExit(f"{out} already exists - refusing to overwrite")
        out.write_text(json.dumps(d, indent=2) + "\n")
        (OUT / "scene_defs" / f"{new_id}.json").write_text(json.dumps(d, indent=2) + "\n")
        made.append((base_id, new_id, img, ann))
        print(f"wrote {out}")
    print()
    for b, n, i, a in made:
        print(f"  {n:<22} from {b:<20} subject COCO {i}/{a}")


if __name__ == "__main__":
    main()
