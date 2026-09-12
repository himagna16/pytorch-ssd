#!/usr/bin/env python3
"""EXPERIMENT 2 - report the controlled F.pets__ships A/B, per flight and per arm.

Reads only what the suite produced: the run directories, the scored
metrics.json (written by the unmodified scoreboard.py), and flights.jsonl.

Reports, per flight and per arm:
  M6 drift, M1 tracking fraction, time to first latch, total latched time,
  false-follow episode count, the confidence distribution on the dog, and the
  machine record (load before/after, sim_wall_ratio, step_gap_ms.max, attitude
  upsets).

The floor each flight used is taken from that flight's own
`floor_reflectance.txt` / `floor_manifest.txt`, written by the harness from the
scene it was about to fly - not from the plan, and not from the directory name.

Attitude upsets use the stability run's definition verbatim: over flown rows
(event == ""), |pitch| > 30 deg or |roll| > 30 deg or z_min < 0.5.

step_gap_ms.max is read PER SPEED CLASS.  Every flight here is chip speed, whose
153 ms rate cap puts its gap floor at ~154 ms by construction, so these numbers
must not be compared against a full-speed threshold.

Usage: analyze_ab.py OUT_DIR
"""
import csv
import json
import math
import statistics as st
import sys
from pathlib import Path

OUT = Path(sys.argv[1])
VIS_ENTER = 0.70

out = []
def P(s=""):
    out.append(s)
    print(s)


def mannwhitney_u(a, b):
    """Two-sided Mann-Whitney U with a normal approximation and tie correction.
    n=4 vs 4 is tiny; the exact two-sided p for a complete separation is 0.0286
    and that is printed alongside."""
    comb = sorted([(v, 0) for v in a] + [(v, 1) for v in b])
    ranks, i = {}, 0
    rankvals = [0.0] * len(comb)
    while i < len(comb):
        j = i
        while j + 1 < len(comb) and comb[j + 1][0] == comb[i][0]:
            j += 1
        r = (i + j) / 2 + 1
        for k in range(i, j + 1):
            rankvals[k] = r
        i = j + 1
    ra = sum(rv for rv, (_, g) in zip(rankvals, comb) if g == 0)
    na, nb = len(a), len(b)
    ua = ra - na * (na + 1) / 2
    ub = na * nb - ua
    u = min(ua, ub)
    mu = na * nb / 2
    sd = math.sqrt(na * nb * (na + nb + 1) / 12)
    z = 0.0 if sd == 0 else (u - mu) / sd
    p = math.erfc(abs(z) / math.sqrt(2))
    return u, p


def flight_rows(run):
    with open(run / "follow_log.csv") as f:
        return [r for r in csv.DictReader(f)]


def scan(run):
    rows = flight_rows(run)
    flown = [r for r in rows if r["event"] == ""]
    pitch = [abs(float(r["pitch"])) for r in flown if r["pitch"]]
    roll = [abs(float(r["roll"])) for r in flown if r["roll"]]
    pz = [float(r["pz"]) for r in flown if r["pz"]]
    conf = [float(r["conf"]) for r in flown]
    bucket = [int(r["size_bucket"]) for r in flown]
    zmin = min(pz) if pz else float("nan")
    upset = int((max(pitch, default=0) > 30) or (max(roll, default=0) > 30) or (zmin < 0.5))
    return {"n": len(flown), "pitch_max": max(pitch, default=float("nan")),
            "roll_max": max(roll, default=float("nan")), "z_min": zmin,
            "upset": upset, "conf": conf, "bucket": bucket}


def main():
    flights = [json.loads(l) for l in (OUT / "flights.jsonl").read_text().splitlines() if l.strip()]
    flights = [f for f in flights if f["verdict"] == "VALID"]
    recs = []
    for f in flights:
        run = Path(f["run_dir"])
        m = json.loads((run / "metrics.json").read_text())["metrics"] \
            if (run / "metrics.json").exists() else {}
        s = json.loads((run / "summary.json").read_text())
        floor_xml = float((run / "floor_reflectance.txt").read_text().strip())
        floor_man = float((run / "floor_manifest.txt").read_text().strip())
        sc = scan(run)
        recs.append({**f, "m": m, "s": s, "sc": sc,
                     "floor_xml": floor_xml, "floor_man": floor_man,
                     "arm": "mirror" if floor_xml > 0 else "matte"})
    recs.sort(key=lambda r: r["order"])

    P("=" * 100)
    P("EXPERIMENT 2 - F.pets__ships ON BOTH FLOORS, ONE SESSION, INTERLEAVED, ABBA")
    P("=" * 100)
    P(f"{len(recs)} VALID flights. Nothing here was measured on hardware; every frame is rendered.")
    P()

    # ---- floor provenance, from each flight's own record
    P("FLOOR PROVENANCE - read per flight from the scene the harness was about to fly")
    P(f"{'ord':>4} {'run':>34} {'scene.xml refl':>15} {'manifest refl':>14} {'arm':>7} {'plan said':>10}")
    bad = 0
    for r in recs:
        agree = (r["arm"] == r["condition"])
        bad += not agree
        P(f"{r['order']:4d} {Path(r['run_dir']).name:>34} {r['floor_xml']:15.2f} "
          f"{r['floor_man']:14.2f} {r['arm']:>7} {r['condition']:>10}"
          f"{'' if agree else '   <-- MISMATCH'}")
    P(f"  mismatches: {bad}")
    P()

    # ---- per flight
    P("PER FLIGHT")
    P(f"{'ord':>4} {'arm':>7} {'rep':>4} {'M6 drift':>9} {'M1 track':>9} {'1st latch':>10} "
      f"{'conf@1st':>9} {'latched s':>10} {'episodes':>9} {'d_start':>8} {'d_end':>7} "
      f"{'drift/ep':>9}")
    for r in recs:
        m = r["m"]
        fl = m.get("M8_t_first_false_follow_s")
        c1 = m.get("M8_conf_at_first_false_follow")
        P(f"{r['order']:4d} {r['arm']:>7} {r['repeat']:4d} "
          f"{m.get('M6_max_horizontal_drift_m', float('nan')):9.3f} "
          f"{m.get('M1_tracking_fraction', float('nan')):9.3f} "
          f"{('%10.2f' % fl) if fl is not None else '      none'} "
          f"{('%9.3f' % c1) if c1 is not None else '        -'} "
          f"{m.get('M8_false_follow_total_s', float('nan')):10.2f} "
          f"{m.get('M8_false_follow_episodes', -1):9d} "
          f"{m.get('dist_start_m', float('nan')):8.2f} "
          f"{m.get('dist_end_m', float('nan')):7.2f} "
          f"{m.get('M8_max_drift_during_episode_m', float('nan')):9.3f}")
    P()

    # ---- per arm
    def arm(a):
        return [r for r in recs if r["arm"] == a]

    P("PER ARM")
    keys = [("M6_max_horizontal_drift_m", "M6 drift (m)", 3),
            ("M1_tracking_fraction", "M1 tracking fraction", 3),
            ("M8_t_first_false_follow_s", "time to first latch (s)", 2),
            ("M8_false_follow_total_s", "total latched (s)", 2),
            ("M8_false_follow_episodes", "false-follow episodes", 0),
            ("M8_conf_at_first_false_follow", "conf at first latch", 3),
            ("M8_max_drift_during_episode_m", "max drift within an episode (m)", 3),
            ("dist_end_m", "range to the dog at the end (m)", 2),
            ("M10_conf_max_absent", "peak confidence on the scene", 3)]
    P(f"{'metric':>34} {'matte (n=%d)' % len(arm('matte')):>34} {'mirror (n=%d)' % len(arm('mirror')):>34}")
    for k, label, dp in keys:
        cells = []
        for a in ("matte", "mirror"):
            v = [r["m"].get(k) for r in arm(a)]
            v = [x for x in v if x is not None]
            if not v:
                cells.append("none")
                continue
            fmt = f"%.{dp}f"
            cells.append(f"{fmt % min(v)}-{fmt % max(v)} (med {fmt % st.median(v)})")
        P(f"{label:>34} {cells[0]:>34} {cells[1]:>34}")
    P()

    P("EFFECT SIZE, matte vs mirrored (the two arms are matched pairs, same session)")
    P(f"{'metric':>34} {'matte med':>10} {'mirror med':>11} {'ratio':>8} {'U':>5} {'p(normal)':>10} {'separated':>10}")
    for k, label, dp in keys:
        va = [r["m"].get(k) for r in arm("matte")]
        vb = [r["m"].get(k) for r in arm("mirror")]
        va = [x for x in va if x is not None]
        vb = [x for x in vb if x is not None]
        if len(va) < 2 or len(vb) < 2:
            continue
        u, p = mannwhitney_u(va, vb)
        sep = (max(va) < min(vb)) or (max(vb) < min(va))
        ma, mb = st.median(va), st.median(vb)
        ratio = (mb / ma) if ma else float("nan")
        P(f"{label:>34} {ma:10.3f} {mb:11.3f} {ratio:8.2f} {u:5.1f} {p:10.3f} "
          f"{'YES' if sep else 'no':>10}")
    P()
    P("With 4 vs 4 the smallest attainable exact two-sided p is 0.0286 (complete")
    P("separation). The normal-approximation p above is only a rough guide; read the")
    P("'separated' column, which says whether the two arms' ranges overlap at all.")
    P()

    # ---- the M6 gate
    P("AGAINST THE M6 GATE (max_horizontal_drift_m < 0.5 m, hard)")
    for a in ("matte", "mirror"):
        v = sorted(r["m"]["M6_max_horizontal_drift_m"] for r in arm(a))
        npass = sum(x < 0.5 for x in v)
        P(f"  {a:6s}: {[round(x, 3) for x in v]}   passes {npass}/{len(v)}   "
          f"scoreboard headline (worst repeat) {max(v):.3f}")
    P()

    # ---- confidence on the dog
    P("CONFIDENCE DISTRIBUTION ON THE SCENE (a dog and a cat; there is no person here)")
    P(f"{'arm':>7} {'frames':>7} {'mean':>6} {'med':>6} {'p90':>6} {'max':>6} "
      f"{'>=0.70':>7} {'>=0.45':>7}   size buckets")
    for a in ("matte", "mirror"):
        conf = [c for r in arm(a) for c in r["sc"]["conf"]]
        buck = [b for r in arm(a) for b in r["sc"]["bucket"]]
        conf_s = sorted(conf)
        bc = {b: buck.count(b) for b in sorted(set(buck))}
        P(f"{a:>7} {len(conf):7d} {st.mean(conf):6.3f} {st.median(conf):6.3f} "
          f"{conf_s[int(0.9 * len(conf_s))]:6.3f} {max(conf):6.3f} "
          f"{100 * sum(c >= 0.70 for c in conf) / len(conf):6.1f}% "
          f"{100 * sum(c >= 0.45 for c in conf) / len(conf):6.1f}%   "
          + "  ".join(f"b{b}x{n}" for b, n in bc.items()))
    P()
    P("Per flight:")
    P(f"{'ord':>4} {'arm':>7} {'frames':>7} {'mean':>6} {'med':>6} {'max':>6} {'>=0.70':>7}   buckets")
    for r in recs:
        c = r["sc"]["conf"]
        bc = {b: r["sc"]["bucket"].count(b) for b in sorted(set(r["sc"]["bucket"]))}
        P(f"{r['order']:4d} {r['arm']:>7} {len(c):7d} {st.mean(c):6.3f} {st.median(c):6.3f} "
          f"{max(c):6.3f} {100 * sum(x >= 0.70 for x in c) / len(c):6.1f}%   "
          + "  ".join(f"b{b}x{n}" for b, n in bc.items()))
    P()

    # ---- machine
    P("THE MACHINE")
    P(f"{'ord':>4} {'arm':>7} {'load1 pre':>10} {'load1 post':>11} {'sim/wall':>9} "
      f"{'Hz':>6} {'gap_max ms':>11} {'|pitch|max':>11} {'|roll|max':>10} {'z_min':>7} {'upset':>6}")
    for r in recs:
        g = r["s"].get("step_gap_ms") or {}
        sc = r["sc"]
        P(f"{r['order']:4d} {r['arm']:>7} {r['load1_before']:10.2f} {r['load1_after']:11.2f} "
          f"{r['s'].get('sim_wall_ratio', float('nan')):9.3f} "
          f"{r['s'].get('processed_hz', float('nan')):6.2f} "
          f"{g.get('max', float('nan')):11.1f} {sc['pitch_max']:11.2f} {sc['roll_max']:10.2f} "
          f"{sc['z_min']:7.3f} {sc['upset']:6d}")
    P()
    gaps = [(r["s"].get("step_gap_ms") or {}).get("max") for r in recs]
    gaps = [g for g in gaps if g is not None]
    swr = [r["s"]["sim_wall_ratio"] for r in recs]
    P(f"attitude upsets: {sum(r['sc']['upset'] for r in recs)} / {len(recs)}   "
      f"worst |pitch| {max(r['sc']['pitch_max'] for r in recs):.2f} deg   "
      f"worst |roll| {max(r['sc']['roll_max'] for r in recs):.2f} deg   "
      f"z_min {min(r['sc']['z_min'] for r in recs):.3f}-{max(r['sc']['z_min'] for r in recs):.3f} m")
    P(f"sim_wall_ratio: min {min(swr):.3f} median {st.median(swr):.3f} max {max(swr):.3f}   "
      f"flights below 0.95: {sum(x < 0.95 for x in swr)} of {len(swr)}")
    P("step_gap_ms.max, CHIP SPEED CLASS ONLY (all 8 flights; the 153 ms rate cap puts")
    P(f"  the floor at ~154 ms by construction): min {min(gaps):.1f}  median "
      f"{st.median(gaps):.1f}  max {max(gaps):.1f} ms")
    for a in ("matte", "mirror"):
        g = [(r["s"].get("step_gap_ms") or {}).get("max") for r in arm(a)]
        g = [x for x in g if x is not None]
        lo = [r["load1_before"] for r in arm(a)]
        P(f"  {a:6s}: gap_max {min(g):.1f}-{max(g):.1f} ms   load1 before "
          f"{min(lo):.2f}-{max(lo):.2f} (mean {st.mean(lo):.2f})")
    P()
    P("Chronological balance actually realised:")
    for a in ("matte", "mirror"):
        pos = [r["order"] for r in arm(a)]
        P(f"  {a:6s} flew at {pos}, mean position {st.mean(pos):.1f} of {len(recs)}")

    (OUT / "ab_analysis.txt").write_text("\n".join(out) + "\n")
    print(f"\nwrote {OUT / 'ab_analysis.txt'}")


if __name__ == "__main__":
    main()
