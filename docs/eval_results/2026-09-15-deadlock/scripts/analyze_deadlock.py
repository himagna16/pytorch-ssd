#!/usr/bin/env python3
"""Does moving the person closer rescue the subjects the drone ignores?

Reads the 156 deadlock flights plus the 3.64 m static arm from the people-plural
suite, so each subject has four ranges. Per-flight metrics come from
scoreboard.metrics_for_run and from the raw follow_log, the same way
people-plural computes them.

Usage: nemoenv/bin/python analyze_deadlock.py <deadlock_dir>
"""
import csv
import itertools
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path("/Users/saimaruvada/Downloads/drone/pytorch_ssd")
sys.path.insert(0, str(ROOT / "tools/crazysim_macos"))
import scoreboard as SB                                      # noqa: E402

OUT = Path(sys.argv[1])
PLURAL = ROOT / "docs/eval_results/2026-09-15-people-plural"
POOL = json.loads((PLURAL / "tables/pool.json").read_text())
SUBJ = {p["img_id"]: p for p in POOL["keepers"]}
SUBJ["control"] = POOL["control"]


def clopper_pearson(k, n, alpha=0.05):
    """exact binomial interval. Same implementation people-plural verified against
    published values at 0/8, 0/6, 8/8, 1/10 and 5/10; inlined rather than imported
    because analyze_pool.py reads sys.argv at module level."""
    import math
    if n == 0:
        return (float("nan"), float("nan"))
    def betacdf(x, a, b):
        if x <= 0: return 0.0
        if x >= 1: return 1.0
        lbeta = math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)
        front = math.exp(math.log(x) * a + math.log(1 - x) * b - lbeta) / a
        f, c, d = 1.0, 1.0, 0.0
        for i in range(0, 300):
            m_ = i // 2
            if i == 0: num = 1.0
            elif i % 2 == 0: num = (m_ * (b - m_) * x) / ((a + 2*m_ - 1) * (a + 2*m_))
            else: num = -((a + m_) * (a + b + m_) * x) / ((a + 2*m_) * (a + 2*m_ + 1))
            d = 1.0 + num * d
            if abs(d) < 1e-30: d = 1e-30
            d = 1.0 / d
            c = 1.0 + num / c
            if abs(c) < 1e-30: c = 1e-30
            f *= c * d
            if abs(1.0 - c * d) < 1e-12: break
        return front * (f - 1.0)
    def betainv(pp, a, b):
        lo, hi = 0.0, 1.0
        for _ in range(200):
            mid = (lo + hi) / 2
            if betacdf(mid, a, b) < pp: lo = mid
            else: hi = mid
        return (lo + hi) / 2
    lo = 0.0 if k == 0 else betainv(alpha / 2, k, n - k + 1)
    hi = 1.0 if k == n else betainv(1 - alpha / 2, k + 1, n - k)
    return (lo, hi)


def flight(rd, rng_label):
    cell, summary, rows, truth, manifest = SB.load_run(rd)
    if not rows or not cell:
        return None
    m, _ = SB.metrics_for_run(cell, summary, rows, truth, manifest)
    if "error" in m:
        return None
    flown = [r for r in rows if r.get("event", "") == ""]
    trk = np.array([1 if SB.fnum(r, "tracking") > 0.5 else 0 for r in flown])
    conf = np.array([SB.fnum(r, "conf") for r in flown])
    t = np.array([SB.fnum(r, "t") for r in flown])
    dt = np.diff(t, prepend=t[0])
    ve, vx, cf, _ = SB.latch_rule(summary)
    best = 0.0
    for k, g in itertools.groupby(zip(trk, dt), key=lambda z: z[0]):
        if k:
            best = max(best, float(sum(d for _, d in g)))
    who = cell["cell_id"].split("__")[1]
    return {
        "run": rd.name, "subject": who, "range": rng_label,
        "index_pct": SUBJ[who]["index_pct"],
        "M1": m.get("M1_tracking_fraction"),
        "ever": int(trk.any()), "held_1s": int(best >= 1.0), "held_3s": int(best >= 3.0),
        "longest_track_s": round(best, 3),
        "frames_above_enter": int((conf >= ve).sum()),
        "conf_mean": round(float(conf.mean()), 4),
        "dist_start_m": m.get("dist_start_m"), "dist_end_m": m.get("dist_end_m"),
        "vis_enter": ve,
    }


def main():
    rows = []
    for rd in sorted((OUT / "runs").iterdir()):
        if not (rd / "summary.json").exists():
            continue
        lbl = {"r16": "1.6", "r22": "2.2", "r28": "2.8"}[rd.name.split("__")[0].split(".")[1]]
        f = flight(rd, lbl)
        if f:
            rows.append(f)
    # the 3.64 m arm is the people-plural static suite
    for rd in sorted((PLURAL / "runs").iterdir()):
        if not rd.name.startswith("A.static__") or not (rd / "summary.json").exists():
            continue
        f = flight(rd, "3.64")
        if f:
            rows.append(f)

    assert {r["vis_enter"] for r in rows} == {0.75}, "latch rule was not the shipped one"
    with open(OUT / "tables/flights.tsv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]), delimiter="\t")
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print(f"{len(rows)} flights ({sum(1 for r in rows if r['range'] != '3.64')} deadlock "
          f"+ {sum(1 for r in rows if r['range'] == '3.64')} from people-plural at 3.64 m)\n")

    RANGES = ["1.6", "2.2", "2.8", "3.64"]
    subs = sorted({r["subject"] for r in rows}, key=lambda s: SUBJ[s]["index_pct"])

    print("=" * 96)
    print("LATCH RATE AGAINST START RANGE.  ever / held>=1s / held>=3s, out of 8 (3.64 m) or 4")
    print("=" * 96)
    print(f"{'subject':>9}{'index':>7}" + "".join(f"{r+' m':>18}" for r in RANGES))
    for s in subs:
        cells = []
        for rg in RANGES:
            h = [r for r in rows if r["subject"] == s and r["range"] == rg]
            if not h:
                cells.append(f"{'-':>18}")
                continue
            cells.append(f"{sum(x['ever'] for x in h)}/{sum(x['held_1s'] for x in h)}/"
                         f"{sum(x['held_3s'] for x in h)} of {len(h)}".rjust(18))
        tag = "  <- control" if s == "control" else ""
        print(f"{s:>9}{SUBJ[s]['index_pct']:>7.1f}" + "".join(cells) + tag)

    print()
    print("=" * 96)
    print("THE TEST: the seven subjects that NEVER latched at 3.64 m on the static scene")
    print("=" * 96)
    never = [s for s in subs
             if not any(r["ever"] for r in rows if r["subject"] == s and r["range"] == "3.64")]
    print(f"  {len(never)} such subjects: {', '.join(never)}")
    print(f"  {'subject':>9}{'index':>7}" + "".join(f"{r+' m':>12}" for r in RANGES)
          + "   rescued?")
    for s in never:
        cells, rescued = [], None
        for rg in RANGES:
            h = [r for r in rows if r["subject"] == s and r["range"] == rg]
            k = sum(x["held_1s"] for x in h)
            cells.append(f"{k}/{len(h)}".rjust(12))
            if rg != "3.64" and k > 0 and rescued is None:
                rescued = rg
        print(f"  {s:>9}{SUBJ[s]['index_pct']:>7.1f}" + "".join(cells)
              + f"   {'yes, at ' + rescued + ' m' if rescued else 'NO at any range'}")

    print()
    print("=" * 96)
    print("WOULD CREEPING FORWARD ACTUALLY HELP?  The follower cannot close past its own")
    print("size-decoder floor, so a rescue that needs 1.6 m is not a rescue the drone can")
    print("reach. Final range on flights that latched and held >= 1 s:")
    print("=" * 96)
    held = [r for r in rows if r["held_1s"] and r["dist_end_m"] is not None]
    for rg in RANGES:
        h = [r["dist_end_m"] for r in held if r["range"] == rg]
        if h:
            print(f"  start {rg:>4} m: n={len(h):>3}  final range median {np.median(h):.2f} m  "
                  f"min {min(h):.2f}  max {max(h):.2f}")
    print()
    pooled = {}
    for rg in RANGES:
        h = [r for r in rows if r["range"] == rg and r["subject"] != "control"]
        k1 = sum(r["held_1s"] for r in h)
        lo, hi = clopper_pearson(k1, len(h))
        pooled[rg] = (k1, len(h), lo, hi)
        print(f"  pooled over the 12 screened, start {rg:>4} m: held>=1s "
              f"{k1}/{len(h)} = {k1/len(h):.3f} [{lo:.3f}, {hi:.3f}]")
    json.dump(rows, open(OUT / "tables/flights.json", "w"), indent=1)
    print("\nwrote tables/flights.tsv and tables/flights.json")


if __name__ == "__main__":
    main()
