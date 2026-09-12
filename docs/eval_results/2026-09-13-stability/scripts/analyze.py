#!/usr/bin/env python3
"""Analyse the stability A/B: upsets vs floor condition, vs flight order, vs machine.

Reads OUT_DIR/flights.jsonl (written by fly_plan.sh) and each run's follow_log.csv.

UPSET DEFINITION -- the same one the Sep 12 report used, stated explicitly:
  upset_frames = flown rows with |pitch| > 30 deg or |roll| > 30 deg
  z_min        = min pz over flown rows  (rows with event == "";  the single
                 "after-land" row is excluded, since it records the post-landing
                 z and is ~0.02 on every flight, healthy or not)
  UPSET        = upset_frames > 0  or  z_min < 0.5
A healthy flight in this harness holds pz 0.80-0.85 with |pitch| under ~5 deg.

Usage:  analyze.py OUT_DIR [--swr-floor 0.95]
"""
import argparse
import collections
import csv
import json
import os
import statistics as st

from scipy.stats import fisher_exact


def scan(run_dir):
    """Return (upset_frames, z_min, max_abs_pitch, max_abs_roll, n_flown)."""
    p = os.path.join(run_dir, "follow_log.csv")
    if not os.path.exists(p):
        return None
    up, zmin, mp, mr, n = 0, None, 0.0, 0.0, 0
    with open(p) as f:
        for r in csv.DictReader(f):
            if r.get("event", "") != "":
                continue
            n += 1
            try:
                pi, ro, z = abs(float(r["pitch"])), abs(float(r["roll"])), float(r["pz"])
            except (ValueError, KeyError, TypeError):
                continue
            if pi > 30 or ro > 30:
                up += 1
            zmin = z if zmin is None else min(zmin, z)
            mp, mr = max(mp, pi), max(mr, ro)
    return up, zmin, mp, mr, n


def rate(tbl):
    n, k = len(tbl), sum(tbl)
    return f"{k}/{n}" + (f" = {100.0*k/n:.0f}%" if n else "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--swr-floor", type=float, default=0.95)
    a = ap.parse_args()

    flights = [json.loads(l) for l in open(os.path.join(a.out, "flights.jsonl"))]

    for fl in flights:
        s = scan(fl["run_dir"])
        if s is None:
            fl["upset_frames"], fl["z_min"] = None, None
            continue
        up, zmin, mp, mr, n = s
        fl.update(upset_frames=up, z_min=zmin, max_pitch=mp, max_roll=mr, n_flown=n)
        fl["upset"] = bool(up > 0 or (zmin is not None and zmin < 0.5))
        fl["suspect"] = (fl.get("sim_wall_ratio") or 0) < a.swr_floor

    valid = [f for f in flights if f["verdict"] == "VALID"]

    print("=" * 104)
    print("PER-FLIGHT TABLE (chronological)")
    print("=" * 104)
    print(f"{'ord':>3} {'cond':<7} {'cell':<24} {'rp':>2} {'a':>1} {'verdict':<8} "
          f"{'sim/wall':>8} {'Hz':>6} {'track':>6} {'upsetF':>6} {'z_min':>6} "
          f"{'|pit|':>5} {'ld1b':>5}")
    for f in flights:
        print(f"{f['order']:>3} {f['condition']:<7} {f['cell']:<24} {f['repeat']:>2} "
              f"{f['attempt']:>1} {f['verdict']:<8} "
              f"{(f.get('sim_wall_ratio') or 0):>8.3f} {(f.get('processed_hz') or 0):>6.2f} "
              f"{(f.get('tracking_fraction') or 0):>6.3f} "
              f"{str(f.get('upset_frames')):>6} "
              f"{(f['z_min'] if f.get('z_min') is not None else float('nan')):>6.2f} "
              f"{f.get('max_pitch', 0):>5.1f} {f['load1_before']:>5.2f}"
              + ("   <-- UPSET" if f.get("upset") else "")
              + ("   [SUSPECT sim/wall]" if f.get("suspect") else ""))

    print()
    print("=" * 104)
    print("1. UPSET RATE BY CONDITION  (scored-VALID flights)")
    print("=" * 104)
    by = {c: [f["upset"] for f in valid if f["condition"] == c] for c in ("matte", "mirror")}
    for c in ("matte", "mirror"):
        print(f"  {c:<7} {rate(by[c])}")
    tbl = [[sum(by["matte"]), len(by["matte"]) - sum(by["matte"])],
           [sum(by["mirror"]), len(by["mirror"]) - sum(by["mirror"])]]
    orr, p = fisher_exact(tbl)
    print(f"  contingency [[matte_up, matte_ok],[mirror_up, mirror_ok]] = {tbl}")
    print(f"  Fisher exact two-sided p = {p:.4f}   odds ratio = {orr}")

    print()
    print("  same, restricted to flights with sim/wall >= %.2f:" % a.swr_floor)
    cl = [f for f in valid if not f["suspect"]]
    byc = {c: [f["upset"] for f in cl if f["condition"] == c] for c in ("matte", "mirror")}
    for c in ("matte", "mirror"):
        print(f"    {c:<7} {rate(byc[c])}")
    t2 = [[sum(byc["matte"]), len(byc["matte"]) - sum(byc["matte"])],
          [sum(byc["mirror"]), len(byc["mirror"]) - sum(byc["mirror"])]]
    if all(sum(r) for r in t2):
        print(f"    Fisher exact two-sided p = {fisher_exact(t2)[1]:.4f}")

    print()
    print("=" * 104)
    print("2. UPSET RATE BY FLIGHT ORDER  (the confound the first attempt could not rule out)")
    print("=" * 104)
    q = collections.defaultdict(list)
    qo = collections.defaultdict(list)
    for f in valid:
        k = min(3, (f["order"] - 1) * 4 // len(flights))
        q[k].append(f["upset"])
        qo[k].append(f["order"])
    for k in sorted(q):
        lo, hi = min(qo[k]), max(qo[k])
        print(f"  flights {lo:>2}-{hi:<2} (quartile {k+1})  {rate(q[k])}")
    print()
    print("  by repeat index (decorrelated from order by design; corr = 0.000):")
    r = collections.defaultdict(list)
    for f in valid:
        r[f["repeat"]].append(f["upset"])
    for k in sorted(r):
        pos = [f["order"] for f in valid if f["repeat"] == k]
        print(f"    repeat {k}  {rate(r[k]):<14} mean chronological position {st.mean(pos):.1f}")

    print()
    print("=" * 104)
    print("3. UPSET RATE BY CELL")
    print("=" * 104)
    cells = sorted({f["cell"] for f in valid})
    print(f"  {'cell':<24} {'matte':<14} {'mirror':<14}")
    for c in cells:
        m = [f["upset"] for f in valid if f["cell"] == c and f["condition"] == "matte"]
        mi = [f["upset"] for f in valid if f["cell"] == c and f["condition"] == "mirror"]
        print(f"  {c:<24} {rate(m):<14} {rate(mi):<14}")

    print()
    print("=" * 104)
    print("4. MATCHED PAIRS  (same cell, same repeat, flown back to back)")
    print("=" * 104)
    pairs = collections.defaultdict(dict)
    for f in valid:
        pairs[f["pair"]][f["condition"]] = f
    both = {k: v for k, v in pairs.items() if len(v) == 2}
    mo = sum(1 for v in both.values() if v["matte"]["upset"] and not v["mirror"]["upset"])
    io = sum(1 for v in both.values() if v["mirror"]["upset"] and not v["matte"]["upset"])
    bo = sum(1 for v in both.values() if v["mirror"]["upset"] and v["matte"]["upset"])
    nn = sum(1 for v in both.values() if not v["mirror"]["upset"] and not v["matte"]["upset"])
    print(f"  complete pairs: {len(both)}")
    print(f"    matte upset only : {mo}")
    print(f"    mirror upset only: {io}")
    print(f"    both upset       : {bo}")
    print(f"    neither          : {nn}")
    if mo + io:
        from scipy.stats import binomtest
        print(f"    McNemar exact (discordant {mo+io}): p = "
              f"{binomtest(mo, mo+io, 0.5).pvalue:.4f}")
    else:
        print("    no discordant pairs -> nothing for McNemar to test")

    print()
    print("=" * 104)
    print("5. THE MACHINE")
    print("=" * 104)
    for c in ("matte", "mirror"):
        sw = [f["sim_wall_ratio"] for f in valid if f["condition"] == c and f.get("sim_wall_ratio")]
        ld = [f["load1_before"] for f in valid if f["condition"] == c]
        print(f"  {c:<7} sim/wall min {min(sw):.3f} median {st.median(sw):.3f} max {max(sw):.3f} "
              f"| load1_before median {st.median(ld):.2f} max {max(ld):.2f}")
    susp = [f for f in valid if f["suspect"]]
    print(f"  flights below sim/wall {a.swr_floor}: {len(susp)}")
    for f in susp:
        print(f"    ord {f['order']:>3} {f['condition']:<7} {f['cell']:<24} "
              f"sim/wall {f['sim_wall_ratio']:.3f}  upset={f.get('upset')}")
    ups = [f for f in valid if f.get("upset")]
    if ups:
        swu = ", ".join("%.3f" % f["sim_wall_ratio"] for f in ups if f.get("sim_wall_ratio"))
        print(f"  sim/wall on UPSET flights:  {swu}")
    nup = [f for f in valid if not f.get("upset") and f.get("sim_wall_ratio")]
    if ups and nup:
        print(f"  median sim/wall  upset {st.median([f['sim_wall_ratio'] for f in ups]):.3f}  "
              f"vs no-upset {st.median([f['sim_wall_ratio'] for f in nup]):.3f}")

    print()
    print("=" * 104)
    print("6. INVALID / RETRIED FLIGHTS")
    print("=" * 104)
    bad = [f for f in flights if f["verdict"] != "VALID"]
    print(f"  {len(bad)} of {len(flights)} attempts not VALID")
    for f in bad:
        print(f"    ord {f['order']:>3} {f['condition']:<7} {f['cell']:<24} a{f['attempt']} "
              f"{f['verdict']}: {f['reason'][:90]}")

    json.dump(flights, open(os.path.join(a.out, "flights_scanned.json"), "w"), indent=2)
    print(f"\nwrote {os.path.join(a.out, 'flights_scanned.json')}")


if __name__ == "__main__":
    main()
