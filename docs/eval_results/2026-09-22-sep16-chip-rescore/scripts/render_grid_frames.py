#!/usr/bin/env python3
"""Re-create the Sep 16 protocol-geometry frames, which no longer exist on disk.

The 13,003 PNGs of docs/eval_results/2026-09-16-protocol-geometry/ lived in a
session scratchpad and were gone by 2026-09-22 (the folder is empty). Only
their float scores survive (tables/scores.csv.gz). To score them on the chip
arm they have to be rendered again.

They were produced by render_protocol_grid.sh: mock_streamer.py serving a
40-frame bank per cell (--bank 40, --preset himax_typical, default seed 7)
over CPX raw to cpx_grab.py, which saved every frame for 2 s at 20 fps. CPX raw
is lossless, so the frames on disk were the bank frames. This script calls the
same bank_from_scene() in-process with the same arguments and writes the 40
bank frames per cell with cpx_grab-style names - no sockets, no simulator
flight, just the same MuJoCo render + sensor model.

Whether that really reproduces the Sep 16 pixels is CHECKED, not assumed:
analyze_rescore.py scores these frames on the float arm and compares every
cell against the Sep 16 float table. Nothing in the code path changed between
Sep 16 and Sep 22 (build_scene.py, camera_model.py, mock_streamer.py last
touched Sep 12; the pool scene defs Sep 15).

Scenes: built from the committed people-plural defs with
  build_scene.py --def docs/eval_results/2026-09-15-people-plural/scene_defs/pp15_*.json \
      tools/crazysim_macos/scene_defs/s15_static_offset.json --out <pool> --floor-reflectance 0.0

Usage: trainenv/bin/python render_grid_frames.py <pool_scenes_dir> <out_frames_dir>
"""
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "tools/real_frames"))
import mock_streamer as M  # noqa: E402

POOL, OUT = Path(sys.argv[1]), Path(sys.argv[2])
DISTS = (1.5, 2.0, 2.5, 3.0, 3.5)
BEARINGS = (0, -10, 10, -25, 25)
SUBJECTS = ("124442", "527750", "157365", "356427", "250127", "61747", "161875", "401446",
            "374369", "266409", "280779", "556158", "control")
BANK = 40          # render_protocol_grid.sh: BANK=40
T0 = 1789600000.0  # filename timestamps only; they order frames within a clip


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    t_start, n = time.time(), 0
    for subj in SUBJECTS:
        scene = POOL / ("s15_static_offset" if subj == "control" else f"pp15_{subj}") / "scene.xml"
        if not scene.is_file():
            raise SystemExit(f"missing scene {scene}")
        for d in DISTS:
            for b in BEARINGS:
                bank, _ = M.bank_from_scene(scene, BANK, dist=d, bearing=float(b),
                                            preset="himax_typical")
                for i, g in enumerate(bank, 1):
                    name = (f"d{d:g}_b{b:g}_vis1_subj-{subj}_light-sim_take1_"
                            f"f{i:05d}_t{T0 + n * 0.05:.3f}.png")
                    Image.fromarray(np.asarray(g, np.uint8), "L").save(OUT / name)
                    n += 1
        print(f"  {subj}: done, {n} frames, {time.time() - t_start:.0f} s", flush=True)
    print(f"wrote {n} frames to {OUT}")


if __name__ == "__main__":
    main()
