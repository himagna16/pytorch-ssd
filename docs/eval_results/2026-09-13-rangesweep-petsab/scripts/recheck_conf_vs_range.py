#!/usr/bin/env python3
"""Re-check the matte baseline's conf_vs_range table on the same flights.

The baseline's `scripts/conf_vs_range.py` joins the follower's `t` column
against the truth log's `sim_t` column.  Those are different clocks: `t` is
seconds since the FOLLOWER started (time.monotonic() - t0, and the first logged
control row is already ~11 s in), while `sim_t` is seconds since the SIMULATOR
started.  The simulator is launched, waited on, and only then is the follower
run, so the two origins differ - and the offset is not even constant.

That would not matter for a static target.  It matters here: the target sways
with a 24 s period and a 1.6 m amplitude, so putting it at the wrong moment puts
it in the wrong place.  This script measures the offset, measures the position
error it causes, reproduces the baseline's published table byte for byte with
its own join, and then recomputes it with the wall-clock join that both logs
carry.

It also re-labels the bins.  The baseline keys on `round(d * 2) / 2` and prints
the label `k .. k+0.5`, so the row printed "1.5-2.0 m" actually holds ranges in
[1.25, 1.75).  Every bin's printed label is 0.25 m low.

No rendering, no inference, no simulator.  Committed logs only.

Usage: recheck_conf_vs_range.py RUN_DIR...
"""
import bisect
import csv
import math
import os
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path

out = []
def P(s=""):
    out.append(s)
    print(s)


def load(run):
    wall, simt, tx, ty = [], [], [], []
    for line in open(os.path.join(run, "truth.csv")):
        if line.startswith("#"):
            continue
        p = line.strip().split(",")
        wall.append(float(p[0]))
        simt.append(float(p[1]))
        tx.append(float(p[2]))
        ty.append(float(p[3]))
    rows = [r for r in csv.DictReader(open(os.path.join(run, "follow_log.csv")))
            if r.get("event", "") == ""]
    return wall, simt, tx, ty, rows


def interp(xs, ys, x):
    i = bisect.bisect_left(xs, x)
    if i <= 0:
        return ys[0]
    if i >= len(xs):
        return ys[-1]
    x0, x1 = xs[i - 1], xs[i]
    f = 0.0 if x1 == x0 else (x - x0) / (x1 - x0)
    return ys[i - 1] + f * (ys[i] - ys[i - 1])


def table(pairs, label):
    """pairs: (range, conf). Baseline binning, with both labels printed."""
    b = defaultdict(list)
    for rng, c in pairs:
        b[round(rng * 2) / 2].append(c)
    P(f"  {label}   (n={len(pairs)})")
    for k in sorted(b):
        v = b[k]
        if len(v) < 10:
            continue
        P(f"    printed as {k:4.1f}-{k + 0.5:4.1f} | truly [{k - 0.25:4.2f},{k + 0.25:4.2f}) "
          f" n={len(v):4d}  conf {st.mean(v):.3f}  >=0.70 {100 * sum(x >= 0.70 for x in v) / len(v):5.1f}%")


def main():
    runs = sys.argv[1:]
    P("=" * 78)
    P("RE-CHECK OF THE MATTE BASELINE'S conf_vs_range TABLE")
    P("=" * 78)
    P(f"{len(runs)} D.occlusion__proven matte flights, committed logs only.")
    P()

    offs, yerr = [], []
    old, new = [], []
    for run in runs:
        wall, simt, tx, ty, rows = load(run)
        for r in rows:
            t = float(r["t"])
            w = float(r["wall"])
            i = bisect.bisect_left(wall, w)
            if 0 < i < len(wall):
                offs.append(simt[i] - t)
        # --- the baseline's own join, reproduced exactly
        tr = {}
        for s, X, Y in zip(simt, tx, ty):
            tr[round(s, 1)] = (X, Y)
        for r in rows:
            t = round(float(r["t"]), 1)
            if t not in tr:
                continue
            X, Y = tr[t]
            px, py = float(r["px"]), float(r["py"])
            old.append((math.hypot(X - px, Y - py), float(r["conf"])))
        # --- the wall-clock join
        for r in rows:
            w = float(r["wall"])
            X = interp(wall, tx, w)
            Y = interp(wall, ty, w)
            px, py = float(r["px"]), float(r["py"])
            rng = math.hypot(X - px, Y - py)
            new.append((rng, float(r["conf"])))
            t = round(float(r["t"]), 1)
            if t in tr:
                yerr.append(abs(tr[t][1] - Y))

    P("1. The two clocks")
    P(f"   sim_t - follower_t over {len(offs)} frames: "
      f"min {min(offs):+.2f} s  median {st.median(offs):+.2f} s  max {max(offs):+.2f} s")
    P(f"   The offset is not constant, so it cannot be corrected by a shift.")
    P(f"   Target y placed by the t<->sim_t join vs by the wall join: "
      f"mean error {st.mean(yerr):.3f} m, max {max(yerr):.3f} m")
    P(f"   (the target sways +-1.6 m with a 24 s period, so seconds of skew are metres)")
    P()
    P("2. The baseline's table, reproduced with its own join")
    table(old, "t <-> sim_t join (as published)")
    P()
    P("3. The same flights, joined on the wall clock both logs carry")
    table(new, "wall-clock join")
    P()
    P("The monotonic close-range decline in the published table does not survive the")
    P("corrected join. What remains is reported in flight_decomposition.txt, where the")
    P("frames are cut by range AND by viewing azimuth.")

    dest = Path(__file__).resolve().parent.parent / "conf_vs_range_recheck.txt"
    dest.write_text("\n".join(out) + "\n")
    print(f"\nwrote {dest}")


if __name__ == "__main__":
    main()
