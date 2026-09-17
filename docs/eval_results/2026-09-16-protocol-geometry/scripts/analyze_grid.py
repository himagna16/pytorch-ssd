#!/usr/bin/env python3
"""The reference table tomorrow's real capture is compared against.

Reads scores.csv, which score_real_frames.py writes, so every number here is
produced by the same code that will score the real frames. The only difference
between this table and tomorrow's is rendered pixels against real ones.

Usage: nemoenv/bin/python analyze_grid.py <scores.csv> [out_dir]
"""
import csv
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

SRC = Path(sys.argv[1])
OUT = Path(sys.argv[2]) if len(sys.argv) > 2 else SRC.parent
BAR = 0.75
INDEX = {  # detectability index, from the people-plural pool
    "124442": 28.4, "527750": 34.3, "157365": 34.6, "356427": 37.8, "250127": 52.1,
    "61747": 86.8, "161875": 87.0, "401446": 88.8, "374369": 90.3, "266409": 92.1,
    "280779": 92.7, "556158": 93.9, "control": 99.2,
}
# standing-scene flight outcome at 3.64 m, 8 flights each, from people-plural
FLOWN = {
    "124442": 0.000, "527750": 0.000, "157365": 0.000, "356427": 0.000, "250127": 0.000,
    "61747": 0.722, "161875": 0.000, "401446": 0.106, "374369": 0.000, "266409": 0.098,
    "280779": 0.986, "556158": 0.879, "control": 0.991,
}


def load():
    rows = []
    with open(SRC) as f:
        for r in csv.DictReader(f):
            try:
                r["conf"] = float(r["conf"])
                r["dist"] = float(r["dist"])
                r["bearing"] = float(r["bearing"])
            except (TypeError, ValueError):
                continue
            rows.append(r)
    return rows


def frac_above(cs):
    return float(np.mean(np.asarray(cs) >= BAR))


def main():
    rows = load()
    print(f"{len(rows)} scored frames from {SRC}\n")
    dists = sorted({r["dist"] for r in rows})
    bears = sorted({r["bearing"] for r in rows})
    subs = sorted({r["subject"] for r in rows}, key=lambda s: INDEX.get(s, 0))

    by = defaultdict(list)
    for r in rows:
        by[(r["subject"], r["dist"], r["bearing"])].append(r["conf"])

    # ---- the table tomorrow is compared against ---------------------------
    print("=" * 100)
    print("REFERENCE TABLE: fraction of frames at or above the 0.75 enter bar, bearing 0")
    print("The follower needs 3 consecutive frames above the bar to start following.")
    print("=" * 100)
    hdr = f"{'subject':>9}{'index':>7}{'flown M1':>10}"
    print(hdr + "".join(f"{str(d)+' m':>10}" for d in dists))
    for s in subs:
        cells = []
        for d in dists:
            c = by.get((s, d, 0.0))
            cells.append(f"{frac_above(c):>10.3f}" if c else f"{'-':>10}")
        fl = FLOWN.get(s)
        print(f"{s:>9}{INDEX.get(s, float('nan')):>7.1f}"
              f"{(f'{fl:.3f}' if fl is not None else '-'):>10}" + "".join(cells))

    print()
    print("=" * 100)
    print("MEAN CONFIDENCE, bearing 0")
    print("=" * 100)
    print(f"{'subject':>9}{'index':>7}" + "".join(f"{str(d)+' m':>10}" for d in dists))
    for s in subs:
        cells = []
        for d in dists:
            c = by.get((s, d, 0.0))
            cells.append(f"{np.mean(c):>10.3f}" if c else f"{'-':>10}")
        print(f"{s:>9}{INDEX.get(s, float('nan')):>7.1f}" + "".join(cells))

    # ---- the 2.5 m rung ----------------------------------------------------
    print()
    print("=" * 100)
    print("IS THE 2.5 m RUNG A DIP?  pooled over all subjects and bearings")
    print("=" * 100)
    print(f"{'dist':>8}{'n':>8}{'mean conf':>12}{'median':>10}{'frac>=0.75':>12}")
    prof = {}
    for d in dists:
        c = [r["conf"] for r in rows if r["dist"] == d]
        prof[d] = c
        print(f"{d:>8.2f}{len(c):>8}{np.mean(c):>12.3f}{np.median(c):>10.3f}{frac_above(c):>12.3f}")
    inner = [d for d in dists if min(dists) < d < max(dists)]
    print()
    dips = 0
    for d in inner:
        lo = dists[dists.index(d) - 1]
        hi = dists[dists.index(d) + 1]
        if np.mean(prof[d]) < np.mean(prof[lo]) and np.mean(prof[d]) < np.mean(prof[hi]):
            print(f"  {d} m is a local MINIMUM: {np.mean(prof[lo]):.3f} -> "
                  f"{np.mean(prof[d]):.3f} -> {np.mean(prof[hi]):.3f}")
            dips += 1
    if not dips:
        print("  no interior distance is a local minimum in pooled mean confidence")

    print()
    print("  per subject, is 2.5 m below BOTH its neighbours? (bearing 0)")
    n_dip = 0
    for s in subs:
        got = {d: by.get((s, d, 0.0)) for d in (2.0, 2.5, 3.0)}
        if not all(got.values()):
            continue
        m = {d: float(np.mean(v)) for d, v in got.items()}
        is_dip = m[2.5] < m[2.0] and m[2.5] < m[3.0]
        n_dip += is_dip
        print(f"    {s:>9}  2.0 {m[2.0]:.3f}  2.5 {m[2.5]:.3f}  3.0 {m[3.0]:.3f}   "
              f"{'DIP' if is_dip else ''}")
    print(f"    -> {n_dip} of {len(subs)} subjects dip at 2.5 m")

    # ---- bearing ------------------------------------------------------------
    print()
    print("=" * 100)
    print("DOES BEARING COST ANYTHING INSIDE THE CROP?  pooled, per distance")
    print("=" * 100)
    print(f"{'dist':>8}" + "".join(f"{('b' + str(int(b))):>11}" for b in bears))
    for d in dists:
        cells = []
        for b in bears:
            c = [r["conf"] for r in rows if r["dist"] == d and r["bearing"] == b]
            cells.append(f"{np.mean(c):>11.3f}" if c else f"{'-':>11}")
        print(f"{d:>8.2f}" + "".join(cells))
    print()
    print("  left/right asymmetry (negative bearings minus positive, same magnitude):")
    for mag in sorted({abs(b) for b in bears if b != 0}):
        neg = [r["conf"] for r in rows if r["bearing"] == -mag]
        pos = [r["conf"] for r in rows if r["bearing"] == mag]
        if neg and pos:
            print(f"    +-{mag:g} deg: left {np.mean(neg):.3f}  right {np.mean(pos):.3f}  "
                  f"difference {np.mean(neg) - np.mean(pos):+.3f}")

    # ---- what to expect tomorrow -------------------------------------------
    print()
    print("=" * 100)
    print("WHAT A REAL PERSON AT 3.5 m, BEARING 0, WOULD HAVE TO BEAT")
    print("=" * 100)
    at = [(s, frac_above(by[(s, 3.5, 0.0)])) for s in subs if (s, 3.5, 0.0) in by]
    if at:
        vals = [v for _, v in at]
        print(f"  simulated subjects, fraction of frames above the bar at 3.5 m:")
        print(f"    min {min(vals):.3f}   median {np.median(vals):.3f}   max {max(vals):.3f}")
        print(f"    subjects at exactly 0.000: {sum(1 for v in vals if v == 0)} of {len(vals)}")
        print()
        print("  A real person who clears the bar on a similar fraction of frames behaves")
        print("  like the rendered cohort. One who clears it far more often does not, and")
        print("  that gap is the rendered-cutout penalty measured directly.")

    with open(OUT / "reference_table.tsv", "w", newline="") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(["subject", "index_pct", "flown_M1_3.64m", "dist_m", "bearing_deg",
                    "n_frames", "mean_conf", "frac_ge_0.75"])
        for (s, d, b), c in sorted(by.items()):
            w.writerow([s, INDEX.get(s, ""), FLOWN.get(s, ""), d, b, len(c),
                        round(float(np.mean(c)), 4), round(frac_above(c), 4)])
    print(f"\nwrote {OUT / 'reference_table.tsv'}")


if __name__ == "__main__":
    main()
