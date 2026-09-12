"""Explain a follower run: when it was tracking, what confidence it saw, and
what the size head called, binned by true distance.

Written to diagnose the runs in this re-fly that dropped their lock. Reads only
the run's own `follow_log.csv` and `truth.csv`; changes nothing.

Usage:
  <trainenv python> why_lost.py RUN_DIR [RUN_DIR ...]
"""
import csv
import sys
from pathlib import Path

import numpy as np


def load_truth(p: Path):
    """truth.csv: a '# bodies: ...' header, then wall,sim,(x,y,z) per body."""
    names, rows = [], []
    with p.open() as f:
        for line in f:
            if line.startswith("#"):
                if "bodies:" in line:
                    names = line.split("bodies:")[1].split()
                continue
            parts = [float(v) for v in line.strip().split(",") if v != ""]
            if parts:
                rows.append(parts)
    return names, np.array(rows)


def main():
    for rd in sys.argv[1:]:
        rd = Path(rd)
        log = list(csv.DictReader((rd / "follow_log.csv").open()))
        # the follower appends event-only rows (e.g. 'after-land') with most
        # columns blank; they are not control steps, so drop them
        log = [r for r in log if r.get("wall")]
        names, tr = load_truth(rd / "truth.csv")
        if not log:
            print(f"{rd.name}: empty follow_log"); continue
        wall = np.array([float(r["wall"]) for r in log])
        trk = np.array([int(r["tracking"]) for r in log])
        conf = np.array([float(r["conf"]) for r in log])
        size_b = np.array([int(r["size_bucket"]) for r in log])
        px = np.array([float(r["px"]) for r in log])
        py = np.array([float(r["py"]) for r in log])
        pz = np.array([float(r["pz"]) for r in log])

        # first body in the truth log is the target for these scenes
        tw = tr[:, 0]
        bx = np.interp(wall, tw, tr[:, 2])
        by = np.interp(wall, tw, tr[:, 3])
        d = np.hypot(bx - px, by - py)

        print(f"=== {rd.name}   n={len(log)}  tracked_fraction={trk.mean():.3f}")
        print(f"    truth bodies: {names}")
        print(f"    d_true: start {d[0]:.2f} m  min {d.min():.2f} m  final {d[-1]:.2f} m"
              f"   z: max {pz.max():.2f} final {pz[-1]:.2f}")
        # where the lock dropped
        drops = [i for i in range(1, len(trk)) if trk[i - 1] == 1 and trk[i] == 0]
        gains = [i for i in range(1, len(trk)) if trk[i - 1] == 0 and trk[i] == 1]
        print(f"    lock drops at rows {drops[:8]}  regains at {gains[:8]}")
        if drops:
            i = drops[0]
            lo, hi = max(0, i - 4), min(len(log), i + 5)
            print("    around the first drop:")
            print(f"      {'row':>5} {'t':>6} {'d_true':>7} {'conf':>6} {'trk':>4} {'bkt':>4} {'x':>6}")
            for j in range(lo, hi):
                print(f"      {j:>5} {float(log[j]['t']):>6.1f} {d[j]:>7.2f} {conf[j]:>6.3f}"
                      f" {trk[j]:>4} {size_b[j]:>4} {float(log[j]['x']):>6.2f}")
        # confidence vs distance, tracking frames only
        print("    confidence by true distance (all frames):")
        edges = np.arange(1.6, 4.4, 0.4)
        for a, b in zip(edges[:-1], edges[1:]):
            s = (d >= a) & (d < b)
            if s.sum() < 3:
                continue
            print(f"      {a:.1f}-{b:.1f} m  n={s.sum():>4}  conf mean {conf[s].mean():.3f}"
                  f"  P(bucket>=2) {np.mean(size_b[s] >= 2):.2f}  tracked {trk[s].mean():.2f}")
        print()


if __name__ == "__main__":
    main()
