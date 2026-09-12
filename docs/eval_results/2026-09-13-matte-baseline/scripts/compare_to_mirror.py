#!/usr/bin/env python3
"""Cell-by-cell comparison of the complete 14-cell MATTE baseline against the
mirrored Sep 11 suite (docs/sim_results/2026-09-11-simv2/).

Reads only scoreboard.json on both sides, so the comparison is exactly what
scoreboard.py itself concluded -- no re-derivation, no hand-picked numbers.

Usage: compare_to_mirror.py MERGED_SCOREBOARD_JSON
"""
import json, sys

MIRROR = ("/Users/saimaruvada/Downloads/drone/pytorch_ssd/"
          "docs/sim_results/2026-09-11-simv2/scoreboard.json")


def gates(cell):
    return {g["id"]: g for g in cell["gates"]}


def main():
    matte = {c["cell_id"]: c for c in json.load(open(sys.argv[1]))["cells"]}
    mirror = {c["cell_id"]: c for c in json.load(open(MIRROR))["cells"]}

    order = [c for c in mirror]   # keep the published suite's cell order
    print("=" * 104)
    print("COMPLETE 14-CELL BASELINE:  mirrored (Sep 11, reflectance 0.2)  vs  matte (reflectance 0.0)")
    print("=" * 104)
    print(f"{'cell':<24} {'mirror':<7} {'matte':<7} {'change':<12} "
          f"{'n_mir':>5} {'n_mat':>5}  failed gates (matte)")
    changed = []
    for cid in order:
        a, b = mirror[cid], matte.get(cid)
        if b is None:
            print(f"{cid:<24} {a['verdict']:<7} {'MISSING':<7}")
            continue
        ch = "same"
        if a["verdict"] != b["verdict"]:
            ch = f"{a['verdict']} -> {b['verdict']}"
            changed.append((cid, a["verdict"], b["verdict"]))
        print(f"{cid:<24} {a['verdict']:<7} {b['verdict']:<7} {ch:<12} "
              f"{a['n_valid']:>5} {b['n_valid']:>5}  {','.join(b['failed_gates']) or '-'}")

    pm = sum(1 for c in mirror.values() if c["verdict"] == "PASS")
    pb = sum(1 for c in matte.values() if c["verdict"] == "PASS")
    print()
    print(f"  mirrored: {pm} PASS / {len(mirror) - pm} FAIL")
    print(f"  matte:    {pb} PASS / {len(matte) - pb} FAIL")
    print(f"  verdict changes: {len(changed)}")
    for cid, x, y in changed:
        print(f"    {cid}: {x} -> {y}")

    print()
    print("=" * 104)
    print("EVERY GATE THAT MOVED, PER CELL")
    print("=" * 104)
    for cid in order:
        b = matte.get(cid)
        if b is None:
            continue
        ga, gb = gates(mirror[cid]), gates(b)
        rows = []
        for gid in sorted(set(ga) | set(gb)):
            x, y = ga.get(gid), gb.get(gid)
            if x is None:
                rows.append((gid, "-", y["value"], "-", y["result"], y.get("threshold"), y["op"]))
                continue
            if y is None:
                rows.append((gid, x["value"], "-", x["result"], "-", x.get("threshold"), x["op"]))
                continue
            same_val = x["value"] == y["value"]
            same_res = x["result"] == y["result"]
            if not (same_val and same_res):
                rows.append((gid, x["value"], y["value"], x["result"], y["result"],
                             y.get("threshold"), y["op"]))
        if not rows:
            continue
        print(f"\n--- {cid}   ({mirror[cid]['verdict']} -> {b['verdict']})")
        print(f"    {'gate':<34} {'mirror':>10} {'matte':>10}  {'gate rule':<12} "
              f"{'mir':<12} {'mat':<12}")
        for gid, xv, yv, xr, yr, th, op in rows:
            rule = f"{op} {th}"
            print(f"    {gid:<34} {str(xv):>10} {str(yv):>10}  {rule:<12} {xr:<12} {yr:<12}")


if __name__ == "__main__":
    main()
