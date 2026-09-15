#!/usr/bin/env python3
"""SIM side, step 2 of 2: score every rendered frame with champion_arms.py -
the SAME module, the SAME three networks and the SAME preprocessing the real
photographs went through in real_pets.py.

The rendered frames are read back from disk as uint8 grayscale, exactly as they
were written, so the only thing that differs between the two sides of this
comparison is the picture.

`float_bs` (build_scene.run_model's own answer, recorded at render time) is
checked against this script's `float` column; a mismatch would mean the two
paths are not the same network after all, and the run aborts.

Usage: nemoenv/bin/python sim_score.py <frames_dir> <render_csv> <out_csv>
"""
import csv
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from champion_arms import Arms  # noqa: E402

FRAMES = Path(sys.argv[1])
IN = Path(sys.argv[2])
OUT = Path(sys.argv[3])


def main():
    rows = list(csv.DictReader(open(IN)))
    arms = Arms(("float", "fq", "chip"))
    print("arms:", json.dumps(arms.info)[:400], flush=True)
    worst = 0.0
    for n, r in enumerate(rows):
        gray = np.asarray(Image.open(FRAMES / r["frame"]).convert("L"), np.uint8)
        assert gray.shape == (244, 324), gray.shape
        r.update({k: (round(v, 4) if isinstance(v, float) else v) for k, v in arms(gray).items()})
        worst = max(worst, abs(float(r["float"]) - float(r["float_bs"])))
        if (n + 1) % 200 == 0:
            print(f"  {n + 1}/{len(rows)}", flush=True)
    arms.close()
    assert worst < 5e-4, f"float arm disagrees with build_scene.run_model by {worst}"
    print(f"cross-check: max |float - build_scene.run_model| = {worst:.2e} over {len(rows)} frames", flush=True)
    with open(OUT, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print("wrote", OUT, flush=True)


if __name__ == "__main__":
    main()
