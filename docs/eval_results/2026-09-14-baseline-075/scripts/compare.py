#!/usr/bin/env python3
"""Cell-by-cell comparison: the 0.75 reference baseline (this run) against the
committed 0.70 matte baseline (docs/eval_results/2026-09-13-matte-baseline/
scoreboards/scoreboard_matte14.json).

Reads only the two scoreboard.json files, so every number is what
scoreboard.py itself concluded.  Today's scoreboard.py re-scores the committed
0.70 suite with zero differences (rescore_check.txt), so the two sides were
scored by the same rules.

Sections:
  1. verdict table, 14 cells, baseline order
  2. every gate that moved (value or result), per cell, with a WORSE/BETTER tag
     derived from the gate's own operator
  3. F.pets__ships per repeat: M6 drift against the 0.5 m gate
  4. the three B.moving cells that failed at 0.70 on M10_uncertain_fraction_present
  5. D.occlusion, both cells, M9 relatch per repeat (reported, flagged unreliable)
  6. everything that got worse at 0.75, in one list

Usage: compare.py NEW_SCOREBOARD_JSON [BASE_SCOREBOARD_JSON]
"""
import json
import os
import statistics
import sys

BASE_DEFAULT = ("/Users/saimaruvada/Downloads/drone/pytorch_ssd/docs/eval_results/"
                "2026-09-13-matte-baseline/scoreboards/scoreboard_matte14.json")


def gates(cell):
    return {g["id"]: g for g in cell["gates"]}


def worse(op, old, new):
    """True if new is worse than old under the gate's own operator."""
    if old is None or new is None or not isinstance(old, (int, float)) or not isinstance(new, (int, float)):
        return None
    if op in ("<=", "<"):
        return new > old
    if op in (">=", ">"):
        return new < old
    if op == "==":
        return new != old
    return None


def per_repeat(cell, key):
    rows = sorted(cell["runs"], key=lambda r: r.get("repeat") or 0)
    return [(r.get("repeat"), (r.get("metrics") or {}).get(key)) for r in rows if r.get("valid")]


def fmt(v):
    if isinstance(v, float):
        return f"{v:.4g}"
    return str(v)


def main():
    new = json.load(open(sys.argv[1]))
    base = json.load(open(sys.argv[2] if len(sys.argv) > 2 else BASE_DEFAULT))
    nc = {c["cell_id"]: c for c in new["cells"]}
    bc = {c["cell_id"]: c for c in base["cells"]}
    order = [c["cell_id"] for c in base["cells"]]

    print("=" * 110)
    print("1. VERDICTS  --  0.70 matte baseline (Sep 12, committed)  vs  0.75 reference baseline (this run)")
    print("=" * 110)
    print(f"{'cell':<24} {'0.70':<6} {'0.75':<6} {'change':<14} {'n':>3} {'n':>3}  failed gates 0.70  ->  failed gates 0.75")
    changes = []
    for cid in order:
        a, b = bc[cid], nc.get(cid)
        if b is None:
            print(f"{cid:<24} {a['verdict']:<6} {'MISSING':<6}")
            continue
        ch = "same"
        if a["verdict"] != b["verdict"]:
            ch = f"{a['verdict']} -> {b['verdict']}"
            changes.append((cid, a["verdict"], b["verdict"]))
        print(f"{cid:<24} {a['verdict']:<6} {b['verdict']:<6} {ch:<14} {a['n_valid']:>3} {b['n_valid']:>3}  "
              f"{','.join(a['failed_gates']) or '-'}  ->  {','.join(b['failed_gates']) or '-'}")
    pa = sum(1 for c in bc.values() if c["verdict"] == "PASS")
    pb = sum(1 for c in nc.values() if c["verdict"] == "PASS")
    print()
    print(f"  0.70: {pa} PASS / {len(bc) - pa} FAIL      0.75: {pb} PASS / {len(nc) - pb} FAIL      "
          f"verdict changes: {len(changes)}")
    for cid, x, y in changes:
        print(f"    {cid}: {x} -> {y}")

    print()
    print("=" * 110)
    print("2. EVERY GATE THAT MOVED, PER CELL   (value = the scoreboard's aggregate: worst repeat for hard gates, median otherwise)")
    print("=" * 110)
    worse_list = []
    for cid in order:
        b = nc.get(cid)
        if b is None:
            continue
        ga, gb = gates(bc[cid]), gates(b)
        rows = []
        for gid in sorted(set(ga) | set(gb)):
            x, y = ga.get(gid), gb.get(gid)
            if x is None or y is None:
                rows.append((gid, x and x["value"], y and y["value"], x and x["result"], y and y["result"],
                             (y or x).get("threshold"), (y or x)["op"], "presence"))
                continue
            if x["value"] != y["value"] or x["result"] != y["result"] or x.get("threshold") != y.get("threshold"):
                w = worse(y["op"], x["value"], y["value"])
                tag = "WORSE" if w else ("better" if w is False else "")
                if x["result"] == "PASS" and y["result"] == "FAIL":
                    tag += " PASS->FAIL"
                if x["result"] == "FAIL" and y["result"] == "PASS":
                    tag += " FAIL->PASS"
                if x.get("threshold") != y.get("threshold"):
                    tag += f" (threshold {x.get('threshold')} -> {y.get('threshold')})"
                rows.append((gid, x["value"], y["value"], x["result"], y["result"], y.get("threshold"), y["op"], tag))
                if w:
                    worse_list.append((cid, gid, y["kind"], x["value"], y["value"], y["op"], y.get("threshold"),
                                       x["result"], y["result"]))
        if not rows:
            continue
        print(f"\n--- {cid}   ({bc[cid]['verdict']} -> {b['verdict']})")
        print(f"    {'gate':<34} {'0.70':>10} {'0.75':>10}  {'rule':<12} {'0.70':<12} {'0.75':<12}  note")
        for gid, xv, yv, xr, yr, th, op, tag in rows:
            print(f"    {gid:<34} {fmt(xv):>10} {fmt(yv):>10}  {(op + ' ' + fmt(th)):<12} {str(xr):<12} {str(yr):<12}  {tag}")

    print()
    print("=" * 110)
    print("3. F.pets__ships -- M6 max horizontal drift per repeat, gate < 0.5 m on the WORST repeat")
    print("=" * 110)
    for label, sb in (("0.70 matte baseline", bc), ("0.75 this run", nc)):
        c = sb.get("F.pets__ships")
        if not c:
            continue
        d = per_repeat(c, "M6_max_horizontal_drift_m")
        ep = per_repeat(c, "M8_false_follow_episodes")
        tr = per_repeat(c, "M1_tracking_fraction")
        ff = per_repeat(c, "M8_t_first_false_follow_s")
        cm = per_repeat(c, "M10_conf_max_absent")
        vals = [v for _, v in d if v is not None]
        print(f"  {label:<22} drift per repeat {[(r, v) for r, v in d]}  worst {max(vals):.3f}  "
              f"median {statistics.median(vals):.3f}  gate: {'PASS' if max(vals) < 0.5 else 'FAIL'}")
        print(f"  {'':<22} episodes {[v for _, v in ep]}  tracked {[v for _, v in tr]}  first false-follow s "
              f"{[v for _, v in ff]}  conf max absent {[v for _, v in cm]}")
    print("  reference points: threshold sweep 0.75 arm worst 0.376 m (0.162/0.309/0.289/0.376); post-merge smoke "
          "flight 0.484 m (commit b1a0108)")

    print()
    print("=" * 110)
    print("4. B.moving cells that FAILED at 0.70 only on M10_uncertain_fraction_present (band [vis_exit, vis_enter), <= 0.05 median)")
    print("=" * 110)
    print("  NOTE: the scorer's band is [0.45, vis_enter). At 0.75 the band is WIDER than at 0.70, so on an identical")
    print("  confidence trace the fraction can only stay or rise. See reband_m10.txt for the same traces re-banded.")
    for cid in ("B.moving__proven", "B.moving__delta_speed", "B.moving__delta_backend", "B.moving__ships",
                "B.moving__delta_camera"):
        for label, sb in (("0.70", bc), ("0.75", nc)):
            c = sb.get(cid)
            if not c:
                continue
            g = gates(c).get("M10_uncertain_fraction_present")
            pr = per_repeat(c, "M10_uncertain_fraction_present")
            m1 = gates(c).get("M1_tracking_fraction")
            print(f"  {cid:<24} {label}  M10 median {fmt(g['value']) if g else '-':>7} {g['result'] if g else '':<5} "
                  f"(rule {g['op']} {g['threshold']}, kind {g['kind']})  per repeat {[v for _, v in pr]}   "
                  f"M1 {fmt(m1['value']) if m1 else '-'} {m1['result'] if m1 else ''}   verdict {c['verdict']}")

    print()
    print("=" * 110)
    print("5. D.occlusion -- M9 relatch per repeat (UNRELIABLE across sessions; reported, not used for any conclusion)")
    print("=" * 110)
    for cid in ("D.occlusion__ships", "D.occlusion__proven"):
        for label, sb in (("0.70", bc), ("0.75", nc)):
            c = sb.get(cid)
            if not c:
                continue
            g = gates(c).get("M9_gt_visible_to_relatch_s")
            pr = per_repeat(c, "M9_gt_visible_to_relatch_s")
            tr = per_repeat(c, "M1_tracking_fraction")
            print(f"  {cid:<22} {label}  M9 median {fmt(g['value']) if g else '-':>7} {g['result'] if g else '':<5} "
                  f"(rule {g['op']} {g['threshold']})  per repeat {[v for _, v in pr]}  tracked {[v for _, v in tr]}  "
                  f"verdict {c['verdict']}")

    print()
    print("=" * 110)
    print(f"6. EVERYTHING THAT GOT WORSE AT 0.75 (by the gate's own operator; {len(worse_list)} gate lines)")
    print("=" * 110)
    if not worse_list:
        print("  none")
    for cid, gid, kind, xv, yv, op, th, xr, yr in sorted(worse_list):
        flag = "  <-- verdict-relevant" if (kind in ("hard", "gated") and yr == "FAIL") else ""
        print(f"  {cid:<24} {gid:<34} {kind:<13} {fmt(xv):>9} -> {fmt(yv):<9} (rule {op} {fmt(th)})  {xr} -> {yr}{flag}")


if __name__ == "__main__":
    main()
