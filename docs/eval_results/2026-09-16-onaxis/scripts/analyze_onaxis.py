#!/usr/bin/env python3
"""Bearing, held at one range, flown.

Compares three conditions for the same thirteen subjects at the same 3.6401 m:
  OFF AXIS, flown   people-plural's standing suite, person at -15.945 deg, 8 flights
  ON AXIS,  flown   this suite, person at 0.000 deg, 8 flights
  ON AXIS,  rendered  the protocol-geometry grid's confidence at 3.5 m, bearing 0

Usage: nemoenv/bin/python analyze_onaxis.py <onaxis_dir>
"""
import csv
import itertools
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path("/Users/saimaruvada/Downloads/drone/pytorch_ssd")
sys.path.insert(0, str(ROOT / "tools/crazysim_macos"))
import scoreboard as SB                                     # noqa: E402

OUT = Path(sys.argv[1])
PP = ROOT / "docs/eval_results/2026-09-15-people-plural"
GRID = ROOT / "docs/eval_results/2026-09-16-protocol-geometry/tables/reference_table.tsv"
POOL = json.loads((PP / "tables/pool.json").read_text())
IDX = {p["img_id"]: p["index_pct"] for p in POOL["keepers"]}
IDX["control"] = POOL["control"]["index_pct"]


def clopper_pearson(k, n, alpha=0.05):
    import math
    if n == 0:
        return (float("nan"), float("nan"))
    def bcdf(x, a, b):
        if x <= 0: return 0.0
        if x >= 1: return 1.0
        lb = math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)
        front = math.exp(math.log(x) * a + math.log(1 - x) * b - lb) / a
        f, c, d = 1.0, 1.0, 0.0
        for i in range(300):
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
    def binv(pp, a, b):
        lo, hi = 0.0, 1.0
        for _ in range(200):
            mid = (lo + hi) / 2
            if bcdf(mid, a, b) < pp: lo = mid
            else: hi = mid
        return (lo + hi) / 2
    return (0.0 if k == 0 else binv(alpha/2, k, n-k+1),
            1.0 if k == n else binv(1-alpha/2, k+1, n-k))


def read(run_root, prefix):
    out = {}
    for rd in sorted(Path(run_root).iterdir()):
        if not (rd / "summary.json").exists() or not rd.name.startswith(prefix):
            continue
        c, s, r, t, m = SB.load_run(rd)
        if not r or not c:
            continue
        mm, _ = SB.metrics_for_run(c, s, r, t, m)
        who = c["cell_id"].split("__")[1]
        fl = [x for x in r if x.get("event", "") == ""]
        trk = np.array([SB.fnum(x, "tracking") > 0.5 for x in fl])
        tt = np.array([SB.fnum(x, "t") for x in fl])
        dt = np.diff(tt, prepend=tt[0])
        best = 0.0
        for k, g in itertools.groupby(zip(trk, dt), key=lambda z: z[0]):
            if k:
                best = max(best, float(sum(d for _, d in g)))
        conf = np.array([SB.fnum(x, "conf") for x in fl])
        out.setdefault(who, []).append({
            "M1": mm.get("M1_tracking_fraction"), "ever": int(trk.any()),
            "held1": int(best >= 1.0), "conf_mean": float(conf.mean()),
            "frac_bar": float((conf >= 0.75).mean()),
        })
    return out


def main():
    on = read(OUT / "runs", "A.onaxis__")
    off = read(PP / "runs", "A.static__")
    grid = {}
    if GRID.exists():
        for r in csv.DictReader(open(GRID), delimiter="\t"):
            if float(r["dist_m"]) == 3.5 and float(r["bearing_deg"]) == 0.0:
                grid[r["subject"]] = float(r["frac_ge_0.75"])

    subs = sorted(on, key=lambda w: IDX.get(w, 0))
    print(f"{sum(len(v) for v in on.values())} on-axis flights, "
          f"{sum(len(v) for v in off.values())} off-axis flights, same 3.6401 m\n")
    print("=" * 104)
    print("BEARING, HELD AT ONE RANGE, FLOWN.  -15.945 deg against 0.000 deg")
    print("=" * 104)
    print(f"{'subject':>9}{'index':>7}  |{'OFF latch':>10}{'OFF M1':>9}{'OFF conf':>9}"
          f"  |{'ON latch':>9}{'ON M1':>8}{'ON conf':>9}  |{'dM1':>8}{'grid frac':>10}")
    for w in subs:
        o, n = off.get(w, []), on[w]
        om1 = np.mean([x["M1"] for x in o]) if o else float("nan")
        nm1 = np.mean([x["M1"] for x in n])
        print(f"{w:>9}{IDX.get(w,0):>7.1f}  |"
              f"{(sum(x['ever'] for x in o) if o else 0):>7}/{len(o):<2}{om1:>9.3f}"
              f"{(np.mean([x['conf_mean'] for x in o]) if o else float('nan')):>9.3f}  |"
              f"{sum(x['ever'] for x in n):>6}/{len(n):<2}{nm1:>8.3f}"
              f"{np.mean([x['conf_mean'] for x in n]):>9.3f}  |"
              f"{nm1-om1:>+8.3f}{grid.get(w, float('nan')):>10.3f}")

    print()
    print("=" * 104)
    print("POOLED over the twelve screened subjects (control excluded)")
    print("=" * 104)
    for lbl, d in (("off axis, -15.945 deg", off), ("on axis,  0.000 deg", on)):
        fl = [x for w, v in d.items() if w != "control" for x in v]
        if not fl:
            continue
        k = sum(x["ever"] for x in fl)
        lo, hi = clopper_pearson(k, len(fl))
        nsub = sum(1 for w, v in d.items() if w != "control" and any(x["ever"] for x in v))
        print(f"  {lbl}: latched {k}/{len(fl)} = {k/len(fl):.3f} [{lo:.3f}, {hi:.3f}], "
              f"median M1 {np.median([x['M1'] for x in fl]):.3f}, "
              f"subjects acquirable {nsub}/12")

    print()
    print("  per-subject change in mean M1, twelve screened subjects:")
    ds = []
    for w in subs:
        if w == "control" or w not in off:
            continue
        d = np.mean([x["M1"] for x in on[w]]) - np.mean([x["M1"] for x in off[w]])
        ds.append((w, d))
    ups = [d for _, d in ds if d > 0.01]
    downs = [d for _, d in ds if d < -0.01]
    print(f"    better on axis: {len(ups)}   worse: {len(downs)}   unchanged: "
          f"{len(ds)-len(ups)-len(downs)}")
    print(f"    largest gains: " + ", ".join(
        f"{w} {d:+.3f}" for w, d in sorted(ds, key=lambda z: -z[1])[:4]))


if __name__ == "__main__":
    main()
