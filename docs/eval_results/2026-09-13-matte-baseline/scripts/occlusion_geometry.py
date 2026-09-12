#!/usr/bin/env python3
"""Why D.occlusion__proven went PASS -> FAIL on the matte floor.

The scene's partition is a box centred (2.2, -0.95) with half-extents
(0.05, 0.45), so it spans y in [-1.40, -0.50] at x = 2.20.  The target stands at
(3.5, -1.6).  Whether the partition actually hides the target depends on WHERE
THE DRONE IS: the line of sight from (px, py) to (3.5, -1.6) crosses x = 2.20 at

    y = py + (2.20 - px)/(3.50 - px) * (-1.60 - py)

and the target is occluded only while that y lands inside [-1.40, -0.50].

The matte floor is what moves the drone.  Removing the mirror removes the
apparent-height inflation, so the follower closes in instead of parking short --
and past roughly px = 1.6 m the sight line clears the partition edge entirely.
So the scene stops posing "person hidden, then seen again" and starts posing
"person at the edge of a partition, marginally detectable".

This script prints, for every published flight that has a follow_log, how much
of the drone's lost-track time was spent with an UNOBSTRUCTED sight line, and
what the detector's confidence was doing at the time.

Usage: occlusion_geometry.py MERGED_RUNS_DIR MIRROR_RUNS_DIR
"""
import csv, glob, json, os, statistics, sys

TX, TY = 3.5, -1.6
WX, YLO, YHI = 2.2, -1.4, -0.5


def clears(px, py):
    if px >= WX:
        return True
    f = (WX - px) / (TX - px)
    return not (YLO <= py + f * (TY - py) <= YHI)


def crossover_px():
    """Smallest px (at py = 0) from which the sight line clears the partition."""
    lo, hi = 0.0, WX
    for _ in range(60):
        mid = (lo + hi) / 2
        if clears(mid, 0.0):
            hi = mid
        else:
            lo = mid
    return hi


def summ(pat, label):
    print(f"--- {label}")
    any_ = False
    for d in sorted(glob.glob(pat)):
        log = os.path.join(d, "follow_log.csv")
        if not os.path.exists(log):
            print(f"  {os.path.basename(d):<28} (no follow_log.csv published)")
            continue
        any_ = True
        rows = [r for r in csv.DictReader(open(log)) if r.get("event", "") == ""]
        m = json.load(open(os.path.join(d, "metrics.json")))["metrics"]
        pxs = [float(r["px"]) for r in rows]
        un = [r for r in rows if r["tracking"].lower() not in ("1", "true")]
        nclear = sum(1 for r in un if clears(float(r["px"]), float(r["py"])))
        cu = [float(r["conf"]) for r in un]
        print(f"  {os.path.basename(d):<28} px_max {max(pxs):5.2f}  dist_end {m['dist_end_m']:5.2f}  "
              f"lost {len(un):3d}/{len(rows):3d} rows  sightline CLEAR during loss "
              f"{nclear / max(1, len(un)) * 100:5.1f}%  conf while lost: med "
              f"{statistics.median(cu):.3f} max {max(cu):.3f}")
    if not any_:
        print("  (nothing with a follow_log)")


def main():
    merged, mirror = sys.argv[1], sys.argv[2]
    print(f"partition spans y [{YLO}, {YHI}] at x={WX}; target at ({TX}, {TY})")
    print(f"sight line from py=0 clears the partition edge once px > {crossover_px():.3f} m\n")
    summ(merged + "/D.occlusion__proven__*", "MATTE  D.occlusion__proven")
    summ(mirror + "/D.occlusion__proven__*", "MIRROR D.occlusion__proven (Sep 11)")
    print()
    summ(merged + "/D.occlusion__ships__*", "MATTE  D.occlusion__ships")
    summ(mirror + "/D.occlusion__ships__*", "MIRROR D.occlusion__ships (Sep 11)")


if __name__ == "__main__":
    main()
