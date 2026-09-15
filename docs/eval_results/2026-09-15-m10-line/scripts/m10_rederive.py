import sys, json, math
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path.home()/"Downloads/drone/pytorch_ssd/tools/crazysim_macos"))
import scoreboard as SB

ROOT = Path.home()/"Downloads/drone/pytorch_ssd/docs"
BARS = [0.50,0.55,0.60,0.65,0.70,0.75,0.80,0.85,0.90]
rows = []
skipped = {"no_log":0,"no_metrics":0,"err":0,"no_fov":0}

for log in sorted(ROOT.rglob("follow_log.csv")):
    rd = log.parent
    try:
        cell, summary, rr, truth, manifest = SB.load_run(rd)
    except Exception:
        skipped["err"] += 1; continue
    if not rr or not cell:
        skipped["no_log"] += 1; continue
    ve, vx, cf, recorded = SB.latch_rule(summary)
    rec = {"run": str(rd.relative_to(ROOT)),
           "cell": cell.get("id") or cell.get("cell") or "",
           "cls": (cell.get("class") or (cell.get("id") or "?")[:1]),
           "camera": cell.get("camera"), "speed": cell.get("speed"),
           "clean": SB.camera_is_clean(cell, rd),
           "own_bar": ve, "own_exit": vx, "rule_recorded": recorded}
    # sweep the bar; keep exit fixed at the shipped 0.45
    ok = False
    for b in BARS:
        s2 = dict(summary); s2["vis_enter"] = b; s2["vis_exit"] = 0.45; s2["confirm_frames"] = cf
        try:
            m, _ = SB.metrics_for_run(cell, s2, rr, truth, manifest)
        except Exception:
            continue
        if "M10_uncertain_fraction_present" not in m:
            continue
        ok = True
        rec[f"m10_{b:.2f}"] = m["M10_uncertain_fraction_present"]
        if b == BARS[0]:
            rec["p05"] = m.get("M10_conf_p05_present")
            rec["confmean"] = m.get("M10_conf_mean_present")
            rec["M1"] = m.get("M1_tracking_fraction")
            rec["M9_reconf"] = m.get("M9_confirming_frames_used")
            rec["M9_outage"] = m.get("M9_track_outage_s")
            rec["M9_losses"] = len(m.get("M9_track_outage_all_s") or [])
            rec["M11_rev"] = m.get("M11_yaw_reversals_per_min")
            rec["M11_sat"] = m.get("M11_yaw_saturated_fraction")
            rec["M2_mean"] = m.get("M2_heading_err_mean_deg")
    if not ok:
        skipped["no_fov"] += 1; continue
    rows.append(rec)

json.dump(rows, open(sys.argv[1], "w"), indent=1)
print(f"flights with an in-FOV window: {len(rows)}   skipped: {skipped}")
