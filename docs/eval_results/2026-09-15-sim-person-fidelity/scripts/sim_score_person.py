#!/usr/bin/env python3
"""SIM side, step 2 of 2: score every rendered frame through shared_arms - which
is the PET study's champion_arms.py, the same file on disk, so the rendered
frames and the COCO photographs reach the three networks by one code path and a
sim/real difference can never be a preprocessing difference.

`float_bs` (build_scene.run_model's own answer, recorded at render time) is
checked against this script's `float` column; a mismatch would mean the two
paths are not the same network after all, and the run aborts.

Usage: nemoenv/bin/python sim_score_person.py <frames_dir> <render_csv> <out_csv>
"""
import csv
import json
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from shared_arms import Arms, CHAMPION_ARMS_SHA256  # noqa: E402

FRAMES = Path(sys.argv[1])
IN = Path(sys.argv[2])
OUT = Path(sys.argv[3])


def main():
    rows = list(csv.DictReader(open(IN)))
    print(f"champion_arms.py sha256 {CHAMPION_ARMS_SHA256}", flush=True)
    arms = Arms(("float", "fq", "chip"))
    print("arms:", json.dumps(arms.info)[:400], flush=True)
    worst = 0.0
    t0 = time.time()
    for n, r in enumerate(rows):
        gray = np.asarray(Image.open(FRAMES / r["frame"]).convert("L"), np.uint8)
        assert gray.shape == (244, 324), gray.shape
        r.update({k: (round(v, 4) if isinstance(v, float) else v) for k, v in arms(gray).items()})
        worst = max(worst, abs(float(r["float"]) - float(r["float_bs"])))
        if (n + 1) % 400 == 0:
            print(f"  {n + 1}/{len(rows)}  ({time.time() - t0:.0f} s)", flush=True)
    arms.close()
    assert worst < 5e-4, f"float arm disagrees with build_scene.run_model by {worst}"
    print(f"cross-check: max |float - build_scene.run_model| = {worst:.2e} "
          f"over {len(rows)} frames", flush=True)

    # The resolution-matched control, on the side where it must be a NO-OP: a
    # rendered frame is natively a 244 crop, so chip and chip_via244 must agree
    # bit for bit. Anything else would mean the control itself perturbs frames.
    dc = np.array([abs(float(r["chip"]) - float(r["chip_via244"])) for r in rows])
    print(f"SIM-SIDE CONTROL: max |chip - chip_via244| = {dc.max():.4f} over {len(rows)} frames "
          f"({int((dc > 0).sum())} frames differ at all)", flush=True)

    with open(OUT, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print("wrote", OUT, flush=True)


if __name__ == "__main__":
    main()
