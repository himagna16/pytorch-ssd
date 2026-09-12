#!/usr/bin/env python3
"""Is the new D.occlusion__proven track loss a RANGE effect?

The matte floor lets the follower close from ~2.9 m to ~1.9-2.4 m.  The M9
relatch gate then fails.  This bins every logged frame of that cell by the true
drone-to-target range and reports the detector's confidence in each bin, pooled
over flights.  If confidence falls off at short range, the same subject that was
comfortably detected at 2.9 m becomes marginal at 2.0 m, and the cell's new
failure is a close-range detection weakness the mirror was hiding by keeping the
drone too far away to reach it.

truth.csv is: wall_ts, sim_t, x, y, z  (header line names the bodies).

Usage: conf_vs_range.py RUN_DIR [RUN_DIR ...]
"""
import csv, os, statistics, sys
from collections import defaultdict


def rows_of(d):
    tr = {}
    for line in open(os.path.join(d, "truth.csv")):
        if line.startswith("#"):
            continue
        p = line.strip().split(",")
        try:
            tr[round(float(p[1]), 1)] = (float(p[2]), float(p[3]))
        except (IndexError, ValueError):
            pass
    out = []
    with open(os.path.join(d, "follow_log.csv")) as f:
        for r in csv.DictReader(f):
            if r.get("event", "") != "":
                continue
            t = round(float(r["t"]), 1)
            if t not in tr:
                continue
            tx, ty = tr[t]
            px, py = float(r["px"]), float(r["py"])
            out.append((((tx - px) ** 2 + (ty - py) ** 2) ** 0.5,
                        float(r["conf"]),
                        r["tracking"].lower() in ("1", "true")))
    return out


def report(runs, label):
    allr = []
    for d in runs:
        if os.path.exists(os.path.join(d, "follow_log.csv")):
            allr += rows_of(d)
    print(f"{label}  (pooled rows: {len(allr)})")
    if not allr:
        print("   no data")
        return
    b = defaultdict(list)
    for d_, c, _ in allr:
        b[round(d_ * 2) / 2].append(c)
    for k in sorted(b):
        v = b[k]
        if len(v) < 10:
            continue
        print(f"   range {k:4.1f}-{k + 0.5:4.1f} m  n={len(v):4d}  "
              f"conf mean {statistics.mean(v):.3f}  median {statistics.median(v):.3f}  "
              f"frac >= 0.70 latch threshold {sum(1 for x in v if x >= 0.70) / len(v) * 100:5.1f}%")


if __name__ == "__main__":
    report(sys.argv[1:], "confidence vs true range to target")
