#!/usr/bin/env python
"""Print verdict / failed gates / tracking / heading error per cell from a scoreboard.json (read-only)."""
import json, sys
sb = json.load(open(sys.argv[1]))
want = sys.argv[2:]
cells = sb["cells"]
items = cells.items() if isinstance(cells, dict) else [(c.get("cell_id"), c) for c in cells]
for cid, c in items:
    if want and cid not in want:
        continue
    print(f"=== {cid}  ({c.get('backend')}/{c.get('camera')}/{c.get('speed')})  verdict={c.get('verdict')}")
    keys = [k for k in c.keys() if k != "runs"]
    print("   cell keys:", keys)
    for k in ("failed_gates", "failed", "gates_failed", "reason"):
        if k in c: print("  ", k, "=", json.dumps(c[k])[:600])
    for g in c.get("gates", []) or []:
        if g.get("result") not in ("PASS", None) or want:
            print("   gate", g.get("id"), g.get("kind"), "value", g.get("value"), g.get("op"), g.get("threshold"), "->", g.get("result"))
    for r in c.get("runs", []):
        m = r.get("metrics", {})
        hk = [k for k in m if "heading" in k.lower() or k.startswith("M2")]
        print(f"   r{r.get('repeat')} valid={r.get('valid')} M1={m.get('M1_tracking_fraction')} " + " ".join(f"{k}={m.get(k)}" for k in hk) + f" M6={m.get('M6_max_horizontal_drift_m')} M10p={m.get('M10_uncertain_fraction_present')} hz={m.get('loop_hz')}")
