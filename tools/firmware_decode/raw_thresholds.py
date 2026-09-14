#!/usr/bin/env python3
"""Print the integer visibility thresholds to bake into the GAP8 firmware.

eps_out is the final layer's output quantum from a release that PASSES the
semantic gates (not the Aug 28 / Aug 31 releases, which ignore their input).

Defaults are the adopted latch rule (2026-09-13, DECISIONS.md): enter at p >= 0.75 on
3 consecutive frames, exit at p < 0.45. For the champion (--eps-out
2.009823510888964e-4) that prints {5467, -998, 3}; the superseded bar, --enter 0.7,
prints {4216, -998, 3}.
"""
import argparse
import math

ap = argparse.ArgumentParser()
ap.add_argument("--eps-out", type=float, required=True)
ap.add_argument("--enter", type=float, default=0.75)  # 0.7 until 2026-09-13; see docs/firmware_contract.md
ap.add_argument("--exit", type=float, default=0.45)
ap.add_argument("--confirm-frames", type=int, default=3)
a = ap.parse_args()
thr = lambda p: math.ceil(math.log(p / (1 - p)) / a.eps_out)  # same rule as follow_raw_thresh()
print(f"/* eps_out = {a.eps_out!r}; enter p >= {a.enter} x{a.confirm_frames}, lost p < {a.exit} */")
print(f"static const follow_vis_cfg_t FOLLOW_VIS_CFG = {{ {thr(a.enter)}, {thr(a.exit)}, {a.confirm_frames} }};")
