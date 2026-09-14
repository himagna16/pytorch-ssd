#!/usr/bin/env python
"""Cost-side table for B.moving__ships: what a higher exit bar costs on a real person.

Track losses and re-acquisitions come from the tracking column of follow_log.csv;
heading error and settled distance come from the repo's own scoreboard.py
(runs/*/metrics.json), not from a reimplementation.
"""
import json, csv, sys
from pathlib import Path
import numpy as np

suite = Path(sys.argv[1])
rows = []
for rd in sorted((suite / "runs").glob("x*__B.moving__*")):
    if not (rd / "summary.json").exists():
        continue
    s = json.load(open(rd / "summary.json"))
    c = json.load(open(rd / "cell.json"))
    m = json.load(open(rd / "metrics.json"))["metrics"] if (rd / "metrics.json").exists() else {}
    log = [r for r in csv.DictReader(open(rd / "follow_log.csv")) if r.get("event", "") == ""]
    t = np.array([float(r["t"]) for r in log])
    trk = np.array([float(r["tracking"]) for r in log]) > 0
    conf = np.array([float(r["conf"]) for r in log])
    starts = [i for i in range(1, len(trk)) if trk[i] and not trk[i-1]]
    if len(trk) and trk[0]:
        starts.insert(0, 0)
    eps = []
    for i in starts:
        j = i
        while j + 1 < len(trk) and trk[j+1]:
            j += 1
        eps.append((i, j))
    losses = sum(1 for i, j in eps if j < len(trk) - 1)
    gaps = [float(t[eps[k][0]] - t[eps[k-1][1]]) for k in range(1, len(eps))]
    # trailing gap: if the flight ended untracked, that is a drop that was never recovered
    trailing = float(t[-1] - t[eps[-1][1]]) if eps and eps[-1][1] < len(trk) - 1 else 0.0
    rows.append({
        "run": rd.name, "vis_exit": s["vis_exit"], "vis_enter": s["vis_enter"],
        "confirm_frames": s["confirm_frames"], "repeat": c["repeat"], "seed": c["sensor_seed"],
        "tracking_fraction": s["tracking_fraction"],
        "episodes": len(eps), "losses": losses, "reacquisitions": max(0, len(eps) - 1),
        "gap_s": [round(g, 2) for g in gaps],
        "time_lost_s": round(sum(gaps) + trailing, 2),
        "trailing_lost_s": round(trailing, 2),
        "mean_gap_s": round(float(np.mean(gaps)), 2) if gaps else None,
        "max_gap_s": round(float(np.max(gaps)), 2) if gaps else None,
        "hdg_mean": m.get("M2_heading_err_mean_deg"), "hdg_p90": m.get("M2_heading_err_p90_deg"),
        "hdg_max": m.get("M2_heading_err_max_deg"),
        "dist_err_settled_mean_m": m.get("M7_dist_err_settled_mean_m"),
        "dist_err_settled_max_m": m.get("M7_dist_err_settled_max_m"),
        "dist_final_m": m.get("M7_dist_final_m"), "final_in_band": m.get("M7_final_in_band"),
        "in_band_fraction": m.get("M7_in_band_fraction"),
        "uncertain_present": m.get("M10_uncertain_fraction_present"),
        "mean_conf": round(float(conf.mean()), 3),
        "step_gap_max_ms": (s.get("step_gap_ms") or {}).get("max"),
        "sim_wall_ratio": s.get("sim_wall_ratio"), "processed_hz": s.get("processed_hz"),
    })

json.dump(rows, open(suite / "person.json", "w"), indent=2)
arms = sorted({r["vis_exit"] for r in rows})
L = ["## Cost side: `B.moving__ships` (walking person), 2 repeats per arm\n",
     "Heading error and distance come from the repo's own `scoreboard.py` (`runs/*/metrics.json`).",
     "`time lost` = seconds between the end of one track episode and the start of the next, plus any",
     "trailing untracked tail. Every one of these 6 flights is scored PASS by `scoreboard.py`",
     "(`scoreboards/arm_*/scoreboard.md`).\n",
     "| arm | n | tracking fraction (per flight) | mean | episodes | losses | re-acquires | time lost s | max gap s | hdg err mean deg | hdg err max deg | settled dist err m | final in band |",
     "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
summ = {}
for a in arms:
    g = [r for r in rows if r["vis_exit"] == a]
    tf = [r["tracking_fraction"] for r in g]
    hm = [r["hdg_mean"] for r in g if r["hdg_mean"] is not None]
    hx = [r["hdg_max"] for r in g if r["hdg_max"] is not None]
    de = [r["dist_err_settled_mean_m"] for r in g if r["dist_err_settled_mean_m"] is not None]
    L.append(f"| **{a}** | {len(g)} | {', '.join(f'{x:.4f}' for x in tf)} | {np.mean(tf):.4f} | "
             f"{'/'.join(str(r['episodes']) for r in g)} | {sum(r['losses'] for r in g)} | "
             f"{sum(r['reacquisitions'] for r in g)} | {sum(r['time_lost_s'] for r in g):.2f} | "
             f"{max((r['max_gap_s'] or 0) for r in g):.2f} | "
             f"{np.mean(hm):.2f} | {max(hx):.2f} | {np.mean(de):.3f} | "
             f"{sum(1 for r in g if r['final_in_band'])}/{len(g)} |")
    summ[str(a)] = {"tracking_mean": float(np.mean(tf)), "tracking": tf,
                    "losses": sum(r["losses"] for r in g),
                    "reacq": sum(r["reacquisitions"] for r in g),
                    "time_lost_s": sum(r["time_lost_s"] for r in g),
                    "hdg_mean": float(np.mean(hm)) if hm else None,
                    "hdg_max": max(hx) if hx else None,
                    "dist_err": float(np.mean(de)) if de else None}
L.append("\n### Per-flight\n")
cols = ["run", "vis_exit", "seed", "tracking_fraction", "episodes", "losses", "reacquisitions",
        "gap_s", "time_lost_s", "max_gap_s", "hdg_mean", "hdg_p90", "hdg_max",
        "dist_err_settled_mean_m", "dist_final_m", "final_in_band", "uncertain_present",
        "mean_conf", "step_gap_max_ms", "sim_wall_ratio"]
L.append("| " + " | ".join(cols) + " |")
L.append("|" + "---|" * len(cols))
for r in rows:
    L.append("| " + " | ".join(str(r.get(c)) for c in cols) + " |")
json.dump(summ, open(suite / "person_summary.json", "w"), indent=2)
open(suite / "person.md", "w").write("\n".join(L) + "\n")
print("\n".join(L))
