#!/usr/bin/env python3
"""Render person clips at the mirror check's own 8 deg boundary (+-8 at 2.5 and 3.5 m).

The scorer only counts frames with |bearing| >= 8 deg in the MIRROR CHECK, and a
person at exactly 8 deg sits one third of a bin from the centre bin. This is the
honest way to look for the in-between (WEAK) verdict with the real model: not
by corrupting frames, but by standing the subject where left/right is genuinely
marginal. Same renderer and sensor preset as render_clipset.py.
"""
import argparse
import json
import sys
from pathlib import Path

from PIL import Image

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "tools" / "crazysim_macos"))
sys.path.insert(0, str(REPO / "tools" / "real_frames"))
import mock_streamer as ms  # noqa: E402

ap = argparse.ArgumentParser(description=__doc__)
ap.add_argument("--out", type=Path, required=True)
ap.add_argument("--n", type=int, default=30)
ap.add_argument("--preset", default="himax_typical")
ap.add_argument("--bearings", type=float, nargs="+", default=[-8.0, 8.0])
ap.add_argument("--dists", type=float, nargs="+", default=[2.5, 3.5])
a = ap.parse_args()
scene = ms.resolve_scene("s15_static_offset")
man = {"preset": a.preset, "frames_per_clip": a.n, "clips": {}}
for d in a.dists:
    for b in a.bearings:
        name = f"person_d{d:g}_b{b:g}"
        bank, banner = ms.bank_from_scene(scene, a.n, dist=d, bearing=b, preset=a.preset,
                                          cam_height=0.8, seed=int(7 + 100 * d + b))
        (a.out / name).mkdir(parents=True, exist_ok=True)
        for k, g in enumerate(bank):
            Image.fromarray(g, "L").save(a.out / name / f"bank_{k:03d}.png")
        man["clips"][name] = {"scene": "s15_static_offset", "dist_m": d, "bearing_deg": b,
                              "vis": 1, "n": len(bank), "banner": banner}
        print(f"{name}: {len(bank)} frames  ({banner})", flush=True)
(a.out / "render_manifest.json").write_text(json.dumps(man, indent=2) + "\n")
