#!/usr/bin/env python3
"""Collate build_scene.py's own --preview probe for the six scenes.

`build_scene.py --preview` renders the drone's view from the eye line at a few
camera x positions and records the champion FLOAT model's confidence on a CLEAN
render (probe.json). It is not the flight - the flights are chip + himax - but it
is the repo's own build-time scene-drift detector, it needs no simulator, and at
cam_x = 0 it looks at exactly the pose each flight starts from. It is here as an
independent check that the new scenes are what they claim to be.

Run the preview first (holds no lock, but load the machine alone):
  trainenv/bin/python tools/crazysim_macos/build_scene.py --out <scene_root> \
      --preview --def <the six defs>

Usage: nemoenv/bin/python probe_scenes.py <scene_root> <outdir>
"""
import csv
import json
import sys
from pathlib import Path

SC = Path(sys.argv[1])
OUT = Path(sys.argv[2])
SCENES = [("s15_static_offset", "control"), ("tp15_static_median", "median"),
          ("tp15_static_p25", "p25"), ("s01_control_moving", "control"),
          ("tp01_moving_median", "median"), ("tp01_moving_p25", "p25")]
rows = [("scene", "subject", "cam_x", "range_m", "bearing_deg", "in_model_fov",
         "frame_mean_dn", "visibility_confidence", "size_bucket_index")]
print(f"{'scene':<22}{'subj':<9}{'cam_x':>7}{'range':>8}{'bearing':>9}"
      f"{'in_fov':>8}{'conf (float/clean)':>20}")
for s, role in SCENES:
    p = SC / s / "probe.json"
    if not p.exists():
        print(f"{s:<22} no probe.json - run build_scene.py --preview first")
        continue
    d = json.loads(p.read_text())
    for c in d["camera_positions"]:
        sub = list(c["subjects"].values())[0]
        rows.append((s, role, c["cam_x"], sub["range_m"], sub["bearing_deg"],
                     int(sub["in_model_fov"]), c["frame_mean_dn"],
                     c["model"]["visibility_confidence"], c["model"]["size_bucket_index"]))
        print(f"{s:<22}{role:<9}{c['cam_x']:>7.1f}{sub['range_m']:>8.2f}"
              f"{sub['bearing_deg']:>9.1f}{str(sub['in_model_fov']):>8}"
              f"{c['model']['visibility_confidence']:>20.3f}")
with open(OUT / "tables/scene_probe.tsv", "w", newline="") as f:
    csv.writer(f, delimiter="\t").writerows(rows)
print("wrote tables/scene_probe.tsv")
