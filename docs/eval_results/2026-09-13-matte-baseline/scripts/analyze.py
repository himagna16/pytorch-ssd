#!/usr/bin/env python3
"""Machine table + attitude-upset scan for the matte completion suite.

The upset definition is copied verbatim from the Sep 13 stability run so the two
halves of the merged baseline are comparable:

    over FLOWN rows only (event == ""; the single after-land row is excluded
    because it records post-landing z and reads ~0.02 on every flight),
      upset_frames = rows with |pitch| > 30 deg or |roll| > 30 deg
      z_min        = min pz
      UPSET        = upset_frames > 0  or  z_min < 0.5

Usage: analyze.py OUT_DIR
"""
import csv, json, os, statistics, sys


def scan(run):
    up, zmin, pmax, rmax = 0, None, 0.0, 0.0
    with open(os.path.join(run, "follow_log.csv")) as f:
        for r in csv.DictReader(f):
            if r.get("event", "") != "":
                continue
            p, ro, z = abs(float(r["pitch"])), abs(float(r["roll"])), float(r["pz"])
            pmax, rmax = max(pmax, p), max(rmax, ro)
            if p > 30 or ro > 30:
                up += 1
            zmin = z if zmin is None else min(zmin, z)
    return {"upset_frames": up, "z_min": round(zmin, 3),
            "pitch_abs_max": round(pmax, 2), "roll_abs_max": round(rmax, 2),
            "upset": bool(up > 0 or (zmin is not None and zmin < 0.5))}


def main():
    out = sys.argv[1]
    recs = [json.loads(l) for l in open(os.path.join(out, "flights.jsonl"))]
    for r in recs:
        r.update(scan(r["run_dir"]))
    json.dump(recs, open(os.path.join(out, "flights_scanned.json"), "w"), indent=1)

    print("=" * 100)
    print("PER-FLIGHT MACHINE + ATTITUDE RECORD  (all 28 matte flights)")
    print("=" * 100)
    print(f"{'ord':>3} {'cell':<20} {'rep':>3} {'verdict':<7} {'sim/wall':>8} {'Hz':>6} "
          f"{'gap_max':>7} {'ld1_be':>6} {'ld1_af':>6} {'|pitch|':>7} {'|roll|':>6} {'z_min':>6} {'upset':>5}")
    for r in sorted(recs, key=lambda x: x["order"]):
        g = r.get("step_gap_ms") or {}
        gm = g.get("max") if isinstance(g, dict) else g
        print(f"{r['order']:>3} {r['cell']:<20} {r['repeat']:>3} {r['verdict']:<7} "
              f"{r.get('sim_wall_ratio'):>8} {r.get('processed_hz'):>6} {gm:>7} "
              f"{r['load1_before']:>6} {r['load1_after']:>6} "
              f"{r['pitch_abs_max']:>7} {r['roll_abs_max']:>6} {r['z_min']:>6} "
              f"{'YES' if r['upset'] else '-':>5}")

    print()
    print("SUMMARY")
    n = len(recs)
    print(f"  flights                  {n}, all verdicts: "
          f"{ {v: sum(1 for r in recs if r['verdict'] == v) for v in sorted({r['verdict'] for r in recs})} }")
    print(f"  attitude upsets          {sum(r['upset'] for r in recs)}/{n}")
    print(f"  worst |pitch| anywhere   {max(r['pitch_abs_max'] for r in recs):.2f} deg")
    print(f"  worst |roll|  anywhere   {max(r['roll_abs_max'] for r in recs):.2f} deg")
    print(f"  z_min range              {min(r['z_min'] for r in recs):.3f} .. {max(r['z_min'] for r in recs):.3f}")
    sw = [r["sim_wall_ratio"] for r in recs]
    print(f"  sim_wall_ratio           min {min(sw)}  median {statistics.median(sw):.4f}  max {max(sw)}")
    print(f"  flights below 0.95       {sum(1 for v in sw if v < 0.95)}")
    lb = [r["load1_before"] for r in recs]
    print(f"  load1 before             min {min(lb)}  median {statistics.median(lb):.2f}  max {max(lb)}")

    # step gaps must be read PER SPEED CLASS: a chip-speed cell is deliberately
    # rate-capped at 153 ms, so its gap floor is ~154 ms by construction and is
    # not evidence of a scheduler stall.
    print()
    print("  step_gap_ms.max by speed class (the rate cap makes chip cells structurally slow):")
    for speed, want in (("full (no cap)", 0), ("chip (6.5 Hz, 153 ms cap)", 6.5)):
        sub = []
        for r in recs:
            c = json.load(open(os.path.join(r["run_dir"], "cell.json")))
            if (c["rate_hz"] == want):
                g = r.get("step_gap_ms") or {}
                sub.append(g.get("max") if isinstance(g, dict) else g)
        if sub:
            print(f"    {speed:<28} n={len(sub):<3} min {min(sub):7.1f}  median "
                  f"{statistics.median(sub):7.1f}  max {max(sub):7.1f}")
    print()
    print("  SUSPECT FLIGHTS (gap_max far above its class median, or sim_wall_ratio < 0.95):")
    flagged = []
    for r in recs:
        c = json.load(open(os.path.join(r["run_dir"], "cell.json")))
        g = r.get("step_gap_ms") or {}
        gm = g.get("max") if isinstance(g, dict) else g
        cap = 200.0 if c["rate_hz"] else 150.0   # generous, class-aware
        if gm > cap or r["sim_wall_ratio"] < 0.95:
            flagged.append((r["order"], r["cell"], r["repeat"], gm, r["sim_wall_ratio"]))
    if flagged:
        for f in flagged:
            print(f"    flight {f[0]:>2} {f[1]:<20} r{f[2]}  gap_max {f[3]}  sim/wall {f[4]}")
    else:
        print("    none")


if __name__ == "__main__":
    main()
