#!/usr/bin/env python3
"""Re-derive this directory's headline numbers from the RAW flight logs, on an
independent path, and fail if any of them drifted.

`analyze_typical.py` reads each run's `metrics.json` (the scoreboard's output)
and adds three quantities of its own. This script does not import either: it
reads `runs/*/follow_log.csv` and `runs/*/summary.json` with the csv module and
recomputes everything the README quotes. If the two paths disagree, one of them
is wrong and this exits 1.

Usage: nemoenv/bin/python verify_numbers.py <suite_dir>
"""
import csv
import itertools
import json
import statistics
import sys
from pathlib import Path

D = Path(sys.argv[1])
FAILED, CHECKED = [], 0


def ck(name, got, want, tol=1e-9):
    global CHECKED
    CHECKED += 1
    ok = (got == want) if isinstance(want, (str, bool, int)) and not isinstance(want, bool) is False \
        else (abs(got - want) <= tol if isinstance(want, (int, float)) and isinstance(got, (int, float))
              else got == want)
    print(f"  {'OK ' if ok else 'BAD'} {name:<52} got {got!r}  want {want!r}")
    if not ok:
        FAILED.append(name)


def flights():
    out = {}
    for rd in sorted((D / "runs").glob("*")):
        f = rd / "follow_log.csv"
        if not f.exists() or not (rd / "summary.json").exists():
            continue
        cell = json.loads((rd / "cell.json").read_text())
        summary = json.loads((rd / "summary.json").read_text())
        rows = [r for r in csv.DictReader(open(f)) if r["event"] == ""]
        if not rows:
            continue
        t = [float(r["t"]) for r in rows]
        trk = [int(float(r["tracking"])) for r in rows]
        conf = [float(r["conf"]) for r in rows]
        runs_ = [len(list(g)) for k, g in itertools.groupby(c >= 0.75 for c in conf) if k]
        out.setdefault(cell["cell_id"], []).append({
            "name": rd.name,
            "tracking_fraction": summary["tracking_fraction"],
            "trk_frac_recomputed": round(sum(trk) / len(trk), 3),
            "vis_enter": summary["vis_enter"], "vis_exit": summary["vis_exit"],
            "confirm_frames": summary["confirm_frames"],
            "ever_latched": any(trk),
            "untracked_s": round(sum((t[i] - t[i - 1]) for i in range(1, len(t)) if trk[i] == 0)
                                 + (t[0] - t[0]), 2),
            "flown_s": round(t[-1] - t[0], 2),
            "conf_max": round(max(conf), 4), "conf_med": round(statistics.median(conf), 4),
            "frac_ge_075": round(sum(c >= 0.75 for c in conf) / len(conf), 4),
            "frac_lt_045": round(sum(c < 0.45 for c in conf) / len(conf), 4),
            "n_ge_075": sum(c >= 0.75 for c in conf),
            "longest_run_ge_075": max(runs_) if runs_ else 0,
            "steps": len(rows),
        })
    return out


def main():
    F = flights()
    print("=" * 84)
    print("RE-DERIVED FROM runs/*/follow_log.csv, independently of analyze_typical.py")
    print("=" * 84)
    n = sum(len(v) for v in F.values())
    print(f"flights with a usable log: {n}")
    print()

    print("A. the latch rule every flight actually flew")
    ck("all flights vis_enter == 0.75",
       all(f["vis_enter"] == 0.75 for v in F.values() for f in v), True)
    ck("all flights vis_exit == 0.45",
       all(f["vis_exit"] == 0.45 for v in F.values() for f in v), True)
    ck("all flights confirm_frames == 3",
       all(f["confirm_frames"] == 3 for v in F.values() for f in v), True)
    print()

    print("B. summary.json's tracking_fraction equals the log's own tracked fraction")
    worst = max((abs(f["tracking_fraction"] - f["trk_frac_recomputed"])
                 for v in F.values() for f in v), default=0.0)
    ck("max |summary - recomputed| <= 0.001", round(worst, 4) <= 0.001, True)
    print()

    print("C. did each cell ever latch?")
    for cid in sorted(F):
        ever = [f["ever_latched"] for f in F[cid]]
        m1 = [f["tracking_fraction"] for f in F[cid]]
        print(f"  {cid:<22} n={len(F[cid])}  latched in {sum(ever)}/{len(ever)}  "
              f"M1 median {statistics.median(m1):.3f}  range [{min(m1):.3f}, {max(m1):.3f}]")
    for cid in sorted(F):
        if cid.endswith("__control"):
            ck(f"{cid}: every flight latched", all(f["ever_latched"] for f in F[cid]), True)
            ck(f"{cid}: M1 median >= 0.97",
               statistics.median([f["tracking_fraction"] for f in F[cid]]) >= 0.97, True)
        else:
            m1 = [f["tracking_fraction"] for f in F[cid]]
            ck(f"{cid}: M1 median == 0.000", statistics.median(m1) == 0.0, True)
            ck(f"{cid}: M1 max <= 0.013", max(m1) <= 0.013, True)
            ck(f"{cid}: at most 1 of 3 flights latched at all",
               sum(f["ever_latched"] for f in F[cid]) <= 1, True)
    print()

    print("D. the confirmation gate: frames at/above 0.75, and the longest consecutive run")
    for cid in sorted(F):
        for f in sorted(F[cid], key=lambda x: x["name"]):
            print(f"  {f['name']:<30} n>=0.75 {f['n_ge_075']:>4}/{f['steps']:<4} "
                  f"longest run {f['longest_run_ge_075']:>3}   conf max {f['conf_max']:.3f}")
    for cid in sorted(F):
        if not cid.endswith("__control"):
            ck(f"{cid}: longest above-bar run <= 3 on every flight",
               all(f["longest_run_ge_075"] <= 3 for f in F[cid]), True)
            ck(f"{cid}: a flight latched IFF its longest above-bar run reached 3",
               all(f["ever_latched"] == (f["longest_run_ge_075"] >= 3) for f in F[cid]), True)
        else:
            ck(f"{cid}: longest above-bar run >= 20 on every flight",
               all(f["longest_run_ge_075"] >= 20 for f in F[cid]), True)
    print()

    print("E. time not tracking, whole flight")
    for cid in sorted(F):
        ut = [f["untracked_s"] for f in F[cid]]
        fl = [f["flown_s"] for f in F[cid]]
        print(f"  {cid:<22} untracked median {statistics.median(ut):>7.2f} s of "
              f"{statistics.median(fl):>6.2f} s flown  "
              f"({statistics.median(ut) / statistics.median(fl):.3f})")
    print()

    print("=" * 84)
    print(f"{CHECKED - len(FAILED)}/{CHECKED} CHECKS PASSED"
          + ("  ALL VERIFIED" if not FAILED else "   FAILED: " + ", ".join(FAILED)))
    print("=" * 84)
    sys.exit(1 if FAILED else 0)


if __name__ == "__main__":
    main()
