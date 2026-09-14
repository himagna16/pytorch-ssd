#!/usr/bin/env python3
"""Is today's scoreboard.py the same scorer that produced the committed 0.70
baseline?  scoreboard.py changed after that baseline was scored (commit b1a0108
taught it to read the latch rule from summary.json, falling back to 0.70 for
runs that predate the change).  The comparison in this folder is only fair if
the committed 0.70 scoreboard and a fresh re-score of the same 56 runs by
today's scoreboard.py agree exactly.

This diffs two scoreboard.json files at three depths: cell verdicts and failed
gates, every gate line (value / op / threshold / result / kind), and every
per-run metric.  Exit 0 if identical, 1 otherwise.

To reproduce the re-score itself (scoreboard.py writes metrics.json into every
run directory it scores, so the committed runs are COPIED first):

    W=$SCRATCH/rescore070; mkdir -p $W/runs
    cp -R docs/eval_results/2026-09-13-stability/data/matte_suite/runs/* $W/runs/
    cp -R docs/eval_results/2026-09-13-matte-baseline/runs/*            $W/runs/
    echo '{"suite":"core","repeats":4,"cells":14}' > $W/suite_meta.json
    trainenv/bin/python tools/crazysim_macos/scoreboard.py $W --suite matte_baseline_14
    trainenv/bin/python rescore_check.py \
        docs/eval_results/2026-09-13-matte-baseline/scoreboards/scoreboard_matte14.json $W/scoreboard.json

Usage: rescore_check.py COMMITTED_SCOREBOARD RESCORED_SCOREBOARD
"""
import json
import os
import sys


def main():
    a = json.load(open(sys.argv[1]))
    b = json.load(open(sys.argv[2]))
    ca = {c["cell_id"]: c for c in a["cells"]}
    cb = {c["cell_id"]: c for c in b["cells"]}
    print(f"committed: {sys.argv[1]}")
    print(f"re-scored: {sys.argv[2]}")
    print(f"suite verdict committed/re-scored: {a['verdict']} / {b['verdict']}")
    print(f"counts committed/re-scored:        {a['counts']} / {b['counts']}")
    diffs = 0
    for cid in sorted(set(ca) | set(cb)):
        x, y = ca.get(cid), cb.get(cid)
        if x is None or y is None:
            print(f"CELL PRESENCE DIFF {cid}: committed={x is not None} rescored={y is not None}")
            diffs += 1
            continue
        if x["verdict"] != y["verdict"] or x["failed_gates"] != y["failed_gates"] or x["n_valid"] != y["n_valid"]:
            print(f"VERDICT DIFF {cid}: {x['verdict']} {x['failed_gates']} n={x['n_valid']}  vs  "
                  f"{y['verdict']} {y['failed_gates']} n={y['n_valid']}")
            diffs += 1
        gx = {g["id"]: g for g in x["gates"]}
        gy = {g["id"]: g for g in y["gates"]}
        for gid in sorted(set(gx) | set(gy)):
            p, q = gx.get(gid), gy.get(gid)
            if p is None or q is None:
                print(f"GATE PRESENCE DIFF {cid} {gid}: committed={p is not None} rescored={q is not None}")
                diffs += 1
                continue
            for k in ("value", "op", "threshold", "result", "kind"):
                if p.get(k) != q.get(k):
                    print(f"GATE DIFF {cid} {gid} {k}: {p.get(k)} vs {q.get(k)}")
                    diffs += 1
        ra = {os.path.basename(r["run_dir"]): r for r in x["runs"]}
        rb = {os.path.basename(r["run_dir"]): r for r in y["runs"]}
        for rn in sorted(set(ra) | set(rb)):
            if rn not in ra or rn not in rb:
                print(f"RUN PRESENCE DIFF {cid} {rn}")
                diffs += 1
                continue
            ma, mb = ra[rn]["metrics"], rb[rn]["metrics"]
            for k in sorted(set(ma) | set(mb)):
                if ma.get(k) != mb.get(k):
                    print(f"METRIC DIFF {rn} {k}: {ma.get(k)} vs {mb.get(k)}")
                    diffs += 1
    n_runs = sum(len(c["runs"]) for c in a["cells"])
    n_gates = sum(len(c["gates"]) for c in a["cells"])
    print(f"compared {len(ca)} cells, {n_gates} gate lines, {n_runs} runs: {diffs} difference(s)")
    sys.exit(0 if diffs == 0 else 1)


if __name__ == "__main__":
    main()
