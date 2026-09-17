#!/usr/bin/env python3
"""The standing scene with the person straight ahead instead of 15.9 degrees off.

WHY. docs/eval_results/2026-09-16-protocol-geometry measured, on 13,003 rendered
frames, that moving a subject from 15.9 degrees off axis to straight ahead at the
same range takes four of the seven subjects that never latch in flight from about
0.000 to about 1.000 frames above the enter bar. That is a claim about
CONFIDENCE. Whether the drone then actually follows them is a claim about
FLIGHT, and confidence is not tracking: the follower has hysteresis, a
three-frame confirmation, and a control law that moves the drone once it latches.

This suite flies it. Same 13 subjects, same scene, same range, bearing zero.

GEOMETRY. s15_static_offset puts the person at [3.5, -1.0], which is 3.6401 m at
-15.945 degrees. These defs put them at [3.6401, 0.0]: the same 3.6401 m, at
0.000 degrees. Range is held to four decimals and bearing is the only thing that
changes, which is the mirror of the deadlock suite, where bearing was held and
range changed.

Usage: nemoenv/bin/python make_onaxis_scenes.py <outdir>
"""
import json
import math
import sys
from pathlib import Path

ROOT = Path("/Users/saimaruvada/Downloads/drone/pytorch_ssd")
DEFS = ROOT / "tools/crazysim_macos/scene_defs"
PLURAL = ROOT / "docs/eval_results/2026-09-15-people-plural"
OUT = Path(sys.argv[1])
BASE = "s15_static_offset"


def main():
    pool = json.loads((PLURAL / "tables/pool.json").read_text())
    base = json.loads((DEFS / f"{BASE}.json").read_text())
    x0, y0 = base["subjects"][0]["pos"]
    r0 = math.hypot(x0, y0)
    print(f"base {BASE}: [{x0}, {y0}] = {r0:.4f} m at "
          f"{math.degrees(math.atan2(y0, x0)):.3f} deg")
    pos = [round(r0, 6), 0.0]
    assert abs(math.hypot(*pos) - r0) < 1e-6
    assert abs(math.degrees(math.atan2(pos[1], pos[0]))) < 1e-9

    outdir = OUT / "scene_defs"
    outdir.mkdir(parents=True, exist_ok=True)
    cells, made = [], []
    for p in pool["keepers"] + [pool["control"]]:
        img, ann = int(p["img_id"]), int(p["ann_id"])
        is_ctl = str(img) == str(pool["control"]["img_id"])
        who = "control" if is_ctl else str(img)
        sid = f"oa_{who}"
        d = json.loads(json.dumps(base))
        s = d["subjects"][0]
        d["scene_id"] = sid
        d["title"] = f"{base['title']} - COCO {img}, ON AXIS"
        d["purpose"] = (
            f"On-axis variant of {BASE}. The person stands at the SAME range, "
            f"{r0:.4f} m, but straight ahead instead of 15.945 degrees off. "
            f"docs/eval_results/2026-09-16-protocol-geometry measured a large "
            f"confidence gain from exactly this change on rendered frames; this "
            f"scene is for flying it, because confidence is not tracking."
        )
        s["coco"] = {"img_id": img, "ann_id": ann}
        s["pos"] = pos
        s["note"] = (
            f"ON-AXIS VARIANT, 2026-09-16. Two changes from {BASE}.json for the "
            f"twelve pool subjects, one for the control: the COCO cutout is img "
            f"{img}/ann {ann} (unchanged for the control), and pos goes from "
            f"[{x0}, {y0}] to {pos}. Range is held at {r0:.4f} m to four decimals "
            f"and the bearing goes from -15.945 to 0.000 degrees, so bearing is the "
            f"only variable. This subject's flown tracking fraction at the off-axis "
            f"pose was {p.get('conf_flown_range', 'n/a')} predicted against what the "
            f"flight delivered; see 2026-09-16-one-frozen-pose for that gap. Height "
            f"stays 1.7 m and panel width still follows this cutout's own aspect."
        )
        d["prediction"] = {
            "model": d["prediction"]["model"],
            "outcome": "unknown - this is the measurement",
            "rationale": (
                "The rendered grid says these subjects clear the 0.75 bar on most "
                "frames when straight ahead. If the drone still does not follow "
                "them here, then confidence above the bar is not sufficient and "
                "something in the follower or the control law is the constraint. "
                "If it does follow them, the 29 percent standing latch rate in "
                "2026-09-15-people-plural is mostly a property of that scene's "
                "off-axis placement."
            ),
        }
        d["expected_behaviour"] = dict(d["expected_behaviour"])
        d["expected_behaviour"]["gates"] = []
        out = outdir / f"{sid}.json"
        if out.exists():
            raise SystemExit(f"{out} exists")
        out.write_text(json.dumps(d, indent=2) + "\n")
        made.append(sid)
        cells.append(f"A.onaxis__{who}|{sid}|A|45")
    (OUT / "scripts/cells.txt").write_text("\n".join(cells) + "\n")
    print(f"wrote {len(made)} defs and {len(cells)} cells; pos {pos}")


if __name__ == "__main__":
    main()
