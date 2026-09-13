#!/usr/bin/env python
"""Side-by-side scoreboard verdicts and failed gates, champion vs confuser.

Reads the two scoreboard.json files written by the repo's unmodified
scoreboard.py (one per model, built by split_and_score.sh) and prints the
verdict per cell for each model together with the gates each one fails, and
the gate values behind them. No thresholds are re-derived here: everything is
read back out of the scoreboard's own output.

Usage: compare_verdicts.py OUT_DIR
"""
import json
import sys
from pathlib import Path

MODELS = ["champion", "confuser"]
CELLS = ["A.static__ships", "B.moving__ships", "C.empty__ships",
         "D.occlusion__ships", "E.furniture__ships", "F.pets__ships"]


def main():
    out = Path(sys.argv[1])
    sb = {}
    for m in MODELS:
        p = out / "scoreboards" / f"{m}_suite" / "scoreboard.json"
        j = json.load(open(p))
        cells = j["cells"] if isinstance(j["cells"], list) else list(j["cells"].values())
        sb[m] = {"suite": j, "cells": {c["cell_id"]: c for c in cells}}

    L = []
    A = L.append
    A("SCOREBOARD VERDICTS - champion vs confuser, same six chip cells, matte floor")
    A("=" * 78)
    for m in MODELS:
        s = sb[m]["suite"]
        A(f"   {m:10s} suite verdict {s.get('verdict')}   counts {s.get('counts')}   "
          f"flights {s.get('flight_counts')}")
    A("")
    A(f"   {'cell':22s} {'champion':>10s} {'confuser':>10s}   gates failed")
    A("   " + "-" * 72)
    rows = {}
    for cid in CELLS:
        cc, fc = sb["champion"]["cells"].get(cid), sb["confuser"]["cells"].get(cid)
        cv = cc.get("verdict") if cc else "MISSING"
        fv = fc.get("verdict") if fc else "MISSING"
        cg = ",".join(cc.get("failed_gates") or []) or "-" if cc else "-"
        fg = ",".join(fc.get("failed_gates") or []) or "-" if fc else "-"
        rows[cid] = {"champion": {"verdict": cv, "failed": cc.get("failed_gates") if cc else []},
                     "confuser": {"verdict": fv, "failed": fc.get("failed_gates") if fc else []}}
        A(f"   {cid:22s} {cv:>10s} {fv:>10s}   champion: {cg}")
        A(f"   {'':22s} {'':>10s} {'':>10s}   confuser: {fg}")
    A("")

    # The numbers behind every gate that either model failed, side by side.
    A("GATE VALUES, for every gate at least one model failed")
    A("=" * 78)
    for cid in CELLS:
        cc, fc = sb["champion"]["cells"].get(cid), sb["confuser"]["cells"].get(cid)
        if not cc or not fc:
            continue
        cg = {g["id"]: g for g in cc.get("gates", [])}
        fg = {g["id"]: g for g in fc.get("gates", [])}
        interesting = [gid for gid in cg
                       if (cg[gid].get("result") == "FAIL" or fg.get(gid, {}).get("result") == "FAIL")]
        if not interesting:
            A(f"   {cid}: no gate failed for either model")
            continue
        A(f"   {cid}")
        for gid in interesting:
            a, b = cg.get(gid, {}), fg.get(gid, {})
            A(f"      {gid:34s} need {a.get('op')} {a.get('threshold')}   "
              f"champion {a.get('value')} {a.get('result')}   "
              f"confuser {b.get('value')} {b.get('result')}")
        A("")

    # Characterised (non-gating) metrics on F, which is the cell whose whole
    # point is characterisation rather than pass/fail.
    A("CHARACTERISED (non-gating) METRICS ON F.pets__ships")
    A("=" * 78)
    cc, fc = sb["champion"]["cells"].get("F.pets__ships"), sb["confuser"]["cells"].get("F.pets__ships")
    if cc and fc:
        cg = {g["id"]: g for g in cc.get("gates", [])}
        fg = {g["id"]: g for g in fc.get("gates", [])}
        for gid in cg:
            if cg[gid].get("kind") == "characterised":
                A(f"   {gid:34s} champion {cg[gid].get('value')}   confuser {fg.get(gid, {}).get('value')}")
    txt = "\n".join(L)
    (out / "verdicts.txt").write_text(txt)
    json.dump(rows, open(out / "verdicts.json", "w"), indent=2)
    print(txt)


if __name__ == "__main__":
    main()
