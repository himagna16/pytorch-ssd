#!/usr/bin/env python3
"""Cross-tabulate the FLOWN D.occlusion__proven confidence by range AND azimuth.

The static sweeps show confidence is flat in range and collapses past ~40 deg of
viewing azimuth off the subject card's normal.  `s07_occlusion_reappear` couples
the two, because the target stands at (3.5, -1.6) and the drone flies along
y ~ 0.  This script takes the committed flight logs and truth logs - no
rendering, no inference, no simulator - and cuts the flown confidence both ways,
so the coupling can be seen in the flight's own numbers.

Usage: decompose_flight.py RUN_DIR...
"""
import bisect
import collections
import csv
import math
import statistics as st
import sys
from pathlib import Path

TX = 3.5                       # target x in s07_occlusion_reappear


def load_truth(path):
    ts, ys = [], []
    for line in path.read_text().splitlines():
        if line.startswith("#") or not line.strip():
            continue
        f = line.split(",")
        ts.append(float(f[0]))
        ys.append(float(f[3]))
    return ts, ys


def y_at(ts, ys, w):
    i = bisect.bisect_left(ts, w)
    if i <= 0:
        return ys[0]
    if i >= len(ts):
        return ys[-1]
    t0, t1 = ts[i - 1], ts[i]
    f = 0.0 if t1 == t0 else (w - t0) / (t1 - t0)
    return ys[i - 1] + f * (ys[i] - ys[i - 1])


out = []
def P(s=""):
    out.append(s)
    print(s)


def main():
    runs = [Path(p) for p in sys.argv[1:]]
    recs = []
    for run in runs:
        ts, ys = load_truth(run / "truth.csv")
        for r in csv.DictReader(open(run / "follow_log.csv")):
            if r["event"] != "":
                continue
            try:
                px, py = float(r["px"]), float(r["py"])
                conf, trk = float(r["conf"]), int(r["tracking"])
                w = float(r["wall"])
            except (ValueError, KeyError):
                continue
            sy = y_at(ts, ys, w)
            rng = math.hypot(TX - px, sy - py)
            az = math.degrees(math.atan2(abs(py - sy), max(TX - px, 1e-6)))
            recs.append({"run": run.name, "range": rng, "az": az, "conf": conf,
                         "trk": trk, "px": px})

    P("=" * 78)
    P("THE FLOWN D.occlusion__proven FRAMES, CUT BY RANGE AND BY AZIMUTH")
    P("=" * 78)
    P(f"{len(recs)} flown frames from {len(runs)} flights. No rendering, no inference here -")
    P("these are the confidences the follower itself logged.")
    P()
    P(f"range   {min(r['range'] for r in recs):.2f} .. {max(r['range'] for r in recs):.2f} m"
      f"      azimuth {min(r['az'] for r in recs):.1f} .. {max(r['az'] for r in recs):.1f} deg")
    xs = [r["range"] for r in recs]
    zs = [r["az"] for r in recs]
    mx, mz = st.mean(xs), st.mean(zs)
    cov = sum((x - mx) * (z - mz) for x, z in zip(xs, zs))
    rr = cov / math.sqrt(sum((x - mx) ** 2 for x in xs) * sum((z - mz) ** 2 for z in zs))
    P(f"correlation(range, azimuth) over the flown frames = {rr:+.3f}"
      f"   <- this is the confound")
    P()

    rbins = [(1.5, 2.0), (2.0, 2.5), (2.5, 3.0), (3.0, 3.5), (3.5, 9.9)]
    zbins = [(0, 20), (20, 30), (30, 40), (40, 50), (50, 90)]

    P("MARGINAL BY RANGE (what the matte baseline reported):")
    P(f"{'range':>12} {'n':>6} {'mean conf':>10} {'>=0.70':>8} {'mean az':>8}")
    for lo, hi in rbins:
        g = [r for r in recs if lo <= r["range"] < hi]
        if g:
            P(f"{lo:5.1f}-{hi:4.1f} {len(g):6d} {st.mean([r['conf'] for r in g]):10.3f} "
              f"{100 * sum(r['conf'] >= 0.70 for r in g) / len(g):7.1f}% "
              f"{st.mean([r['az'] for r in g]):8.1f}")
    P()
    P("MARGINAL BY AZIMUTH:")
    P(f"{'azimuth':>12} {'n':>6} {'mean conf':>10} {'>=0.70':>8} {'mean range':>11}")
    for lo, hi in zbins:
        g = [r for r in recs if lo <= r["az"] < hi]
        if g:
            P(f"{lo:5.0f}-{hi:4.0f} {len(g):6d} {st.mean([r['conf'] for r in g]):10.3f} "
              f"{100 * sum(r['conf'] >= 0.70 for r in g) / len(g):7.1f}% "
              f"{st.mean([r['range'] for r in g]):11.2f}")
    P()
    P("JOINT - mean conf / % >= 0.70 / n  (blank = the flight never visited that cell)")
    P(('%12s ' % 'range \ az') + " ".join(f"{f'{lo}-{hi}d':>18}" for lo, hi in zbins))
    for rlo, rhi in rbins:
        cells = []
        for zlo, zhi in zbins:
            g = [r for r in recs if rlo <= r["range"] < rhi and zlo <= r["az"] < zhi]
            cells.append("" if len(g) < 5 else
                         f"{st.mean([r['conf'] for r in g]):.2f}/"
                         f"{100 * sum(r['conf'] >= 0.70 for r in g) / len(g):3.0f}%/{len(g)}")
        P(f"{rlo:5.1f}-{rhi:4.1f} " + " ".join(f"{c:>18}" for c in cells))
    P()
    P("Read the rows: at a FIXED azimuth band, moving down a column (closer range)")
    P("does not cost confidence. Read the columns: at a FIXED range band, moving")
    P("right (more azimuth) does.")
    P()
    lost = [r for r in recs if r["trk"] == 0]
    if lost:
        P(f"Lost-track frames (n={lost.__len__()}): mean azimuth "
          f"{st.mean([r['az'] for r in lost]):.1f} deg, mean range "
          f"{st.mean([r['range'] for r in lost]):.2f} m, "
          f"{100 * sum(r['az'] >= 40 for r in lost) / len(lost):.1f}% of them at azimuth >= 40 deg")
        held = [r for r in recs if r["trk"] == 1]
        P(f"Tracked frames    (n={len(held)}): mean azimuth "
          f"{st.mean([r['az'] for r in held]):.1f} deg, mean range "
          f"{st.mean([r['range'] for r in held]):.2f} m, "
          f"{100 * sum(r['az'] >= 40 for r in held) / len(held):.1f}% at azimuth >= 40 deg")
    P()
    P("Per flight, the azimuth the drone worked itself round to:")
    P(f"{'run':>30} {'px max':>7} {'az max':>7} {'az at px_max':>13}")
    for run in sorted(set(r["run"] for r in recs)):
        g = [r for r in recs if r["run"] == run]
        pm = max(g, key=lambda r: r["px"])
        P(f"{run:>30} {pm['px']:7.3f} {max(r['az'] for r in g):7.1f} {pm['az']:13.1f}")

    dest = Path(__file__).resolve().parent.parent / "flight_decomposition.txt"
    dest.write_text("\n".join(out) + "\n")
    print(f"\nwrote {dest}")


if __name__ == "__main__":
    main()
