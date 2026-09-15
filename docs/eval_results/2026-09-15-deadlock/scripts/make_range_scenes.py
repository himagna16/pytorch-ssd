#!/usr/bin/env python3
"""Scene definitions that move the person CLOSER, holding everything else.

WHY. follow_person.py:374-377 commands forward velocity only inside
`if vis_state:`; otherwise vx = 0. The drone does not approach until it has
latched. Meanwhile the static probe in docs/eval_results/2026-09-15-sim-person-fidelity
says the low-detectability subjects only reach the 0.75 enter bar below about
1.65-2.02 m, while the static scene starts the drone at 3.64 m. So the drone
cannot latch because it is too far away, and it cannot get closer because it has
not latched. A.static__124442__r1a1 shows exactly that: drone pose (0,0) at the
first frame and (0,0) at the last, dist_start 3.64 m, dist_end 3.64 m, tracking
0.000, for the whole 45 s.

THE TEST. Fly the same 13 subjects on the same static scene with the person
placed nearer. If the subjects that never latch at 3.64 m do latch at 1.6 m,
then the model can see them and the CONTROL LAW is what fails, which is a
different and much cheaper problem than a model that cannot see ordinary people.

Range is changed by SCALING the subject's position vector, so the bearing is held
exactly. s15_static_offset puts the person at [3.5, -1.0], which is 3.6401 m at
-15.945 deg. Every generated scene keeps that bearing to the digit.

All three ranges keep the whole body inside the 70 deg crop: the geometry in
docs/eval_results/2026-09-15-partial-people puts the head-truncation limit for a
1.7 m person at 1.285 m, below every range flown here.

Usage: nemoenv/bin/python make_range_scenes.py <outdir>
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
RANGES = (1.6, 2.2, 2.8)          # 3.64 m is the people-plural suite's own arm
TRUNC_LIMIT = 1.285               # head leaves the crop below this, partial-people study


def main():
    pool = json.loads((PLURAL / "tables/pool.json").read_text())
    base = json.loads((DEFS / f"{BASE}.json").read_text())
    assert len(base["subjects"]) == 1
    x0, y0 = base["subjects"][0]["pos"]
    r0 = math.hypot(x0, y0)
    brg = math.degrees(math.atan2(y0, x0))
    print(f"base {BASE}: pos [{x0}, {y0}] = {r0:.4f} m at {brg:.3f} deg")
    assert min(RANGES) > TRUNC_LIMIT, "a range would truncate the head"

    outdir = OUT / "scene_defs"
    outdir.mkdir(parents=True, exist_ok=True)
    made = []
    everyone = pool["keepers"] + [pool["control"]]
    for p in everyone:
        img, ann = int(p["img_id"]), int(p["ann_id"])
        for rng in RANGES:
            k = rng / r0
            pos = [round(x0 * k, 6), round(y0 * k, 6)]   # 6 dp: 4 dp moves the bearing by 0.002 deg
            chk_r = math.hypot(*pos)
            chk_b = math.degrees(math.atan2(pos[1], pos[0]))
            assert abs(chk_r - rng) < 1e-3, (chk_r, rng)
            assert abs(chk_b - brg) < 1e-3, (chk_b, brg)
            d = json.loads(json.dumps(base))
            sid = f"dl{int(rng*10):02d}_{img}"
            s = d["subjects"][0]
            d["scene_id"] = sid
            d["title"] = f"{base['title']} - COCO {img} at {rng:.1f} m"
            d["purpose"] = (
                f"Deadlock test, {rng:.1f} m arm. Same scene, same person, moved along "
                f"the same bearing so the drone starts {rng:.1f} m away instead of "
                f"{r0:.2f} m. The follower commands no forward velocity until it has "
                f"latched (follow_person.py:374-377), so at the stock range a subject "
                f"whose confidence only crosses 0.75 nearer than the drone starts can "
                f"never be acquired. This arm asks whether that is what happens."
            )
            s["coco"] = {"img_id": img, "ann_id": ann}
            s["pos"] = pos
            s["note"] = (
                f"DEADLOCK TEST, 2026-09-15. Two changes from {BASE}.json: the COCO "
                f"cutout is img {img}/ann {ann}, and the subject's pos is scaled from "
                f"[{x0}, {y0}] to {pos}, which is {rng:.2f} m at {chk_b:.3f} deg against "
                f"the base's {r0:.4f} m at {brg:.3f} deg. The bearing is held to better "
                f"than 0.001 deg, so range is the only geometric variable. Height stays "
                f"1.7 m and the panel width still follows this cutout's own aspect "
                f"({p['aspect_hw']} h/w -> {p['panel_w_m']} m). At {rng:.1f} m the whole "
                f"body is inside the 70 deg crop; the head-truncation limit for a 1.7 m "
                f"person is 1.285 m (docs/eval_results/2026-09-15-partial-people). "
                f"This subject's static chip confidence at the people-plural start range "
                f"is {p['conf_flown_range']}, and its detectability index is "
                f"{p['index_pct']}."
            )
            d["prediction"] = {
                "model": d["prediction"]["model"],
                "outcome": "unknown - this is the measurement",
                "rationale": (
                    "If a subject that never latches at 3.64 m latches here, the "
                    "perception system can see them and the control law's refusal to "
                    "approach before latching is the binding constraint. If it still "
                    "does not latch at 1.6 m, the model genuinely cannot see this "
                    "person and no control change would help."
                ),
            }
            # the base scene's gates assume the stock geometry; this is not an
            # acceptance scene, so do not carry a pass/fail claim into it
            d["expected_behaviour"] = dict(d["expected_behaviour"])
            d["expected_behaviour"]["gates"] = []
            out = outdir / f"{sid}.json"
            if out.exists():
                raise SystemExit(f"{out} exists")
            out.write_text(json.dumps(d, indent=2) + "\n")
            made.append((sid, img, rng, pos))

    print(f"wrote {len(made)} scene definitions to {outdir}")
    cells = []
    for sid, img, rng, pos in made:
        who = "control" if str(img) == str(pool["control"]["img_id"]) else str(img)
        cells.append(f"A.r{int(rng*10):02d}__{who}|{sid}|A|45")
    (OUT / "scripts/cells.txt").write_text("\n".join(cells) + "\n")
    print(f"wrote {len(cells)} cells")
    for sid, img, rng, pos in made[:6]:
        print(f"  {sid:<16} COCO {img:<8} {rng:.1f} m  pos {pos}")
    print("  ...")


if __name__ == "__main__":
    main()
