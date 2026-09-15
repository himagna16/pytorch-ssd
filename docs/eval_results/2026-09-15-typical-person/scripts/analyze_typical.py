#!/usr/bin/env python3
"""Per-subject tracking results, with the flown cutout alongside as the control.

Everything the scoreboard already computes is READ from each run's metrics.json
(written by tools/crazysim_macos/scoreboard.py; this script never re-derives
M1, M2 or M7). Three quantities the scoreboard does not report in the shape this
question needs are computed here from the flight's own follow_log.csv, using
scoreboard.py's own loaders and its own FOV constant:

  t_first_latch_s       time from the first control step to the first step with
                        tracking latched. The scoreboard has no such metric.
  time_lost_s           total time spent unlatched AFTER the first latch,
                        including a final loss that never recovered. The
                        scoreboard's M9_track_outage_all_s lists only losses that
                        DID recover (its loop skips `j + 1 >= len(trk)`), so on a
                        flight that ends un-latched it understates the loss.
  conf_lt_exit /        per-frame confidence against the two thresholds the
  conf_ge_enter         follower actually uses, over the frames where the target
                        is inside the model's +-35 deg crop. This is the closed-
                        loop counterpart of the fidelity study's static rates.

Usage: nemoenv/bin/python analyze_typical.py <suite_dir>
"""
import csv
import itertools
import json
import statistics
import sys
from pathlib import Path

import numpy as np

ROOT = Path("/Users/saimaruvada/Downloads/drone/pytorch_ssd")
sys.path.insert(0, str(ROOT / "tools/crazysim_macos"))
import scoreboard as SB  # noqa: E402

D = Path(sys.argv[1])
SUBJECT = {"control": ("COCO 19432", "the flown cutout, 99.2nd percentile"),
           "median": ("COCO 250127", "52.1st percentile"),
           "p25": ("COCO 124442", "28.4th percentile")}
CELLS = [("A.static", "static, person at 3.5 m / y -1.0"),
         ("B.moving", "moving, 1.2 m sway, 20 s period")]
PUBLISHED = {  # docs/eval_results/2026-09-14-baseline-075/scoreboard.json, ships-as
    "A.static": ("A.static__ships", 0.9905), "B.moving": ("B.moving__ships", 0.992)}
REPORT = []


def P(s=""):
    print(s, flush=True)
    REPORT.append(s)


def extra(run_dir):
    """t_first_latch, losses, time lost, and the two threshold rates."""
    cell, summary, rows, truth, manifest = SB.load_run(run_dir)
    flown = [r for r in rows if r.get("event") == ""]
    t = np.array([SB.fnum(r, "t") for r in flown])
    trk = np.array([int(SB.fnum(r, "tracking") or 0) for r in flown])
    conf = np.array([SB.fnum(r, "conf") for r in flown])
    out = {"control_steps": len(flown), "flown_s": round(float(t[-1] - t[0]), 2)}

    latched = np.where(trk == 1)[0]
    out["latched_ever"] = bool(len(latched))
    out["t_first_latch_s"] = round(float(t[latched[0]] - t[0]), 3) if len(latched) else None

    # losses after the first latch
    losses, reacq, lost = 0, 0, 0.0
    if len(latched):
        i = latched[0] + 1
        while i < len(trk):
            if trk[i - 1] and not trk[i]:
                j = i
                while j + 1 < len(trk) and not trk[j + 1]:
                    j += 1
                losses += 1
                if j + 1 < len(trk):
                    reacq += 1
                    lost += float(t[j + 1] - t[i])
                else:
                    lost += float(t[-1] - t[i])       # never recovered: to end of flight
                i = j + 1
            i += 1
        span = float(t[-1] - t[latched[0]])
        out["untracked_fraction_after_latch"] = round(lost / span, 4) if span > 0 else None
    out["n_losses"] = losses
    out["n_reacquisitions"] = reacq
    out["time_lost_s"] = round(lost, 2)
    out["never_latched"] = not bool(len(latched))
    # Time not tracking over the WHOLE flight, which is the only "time lost"
    # number that means anything when the track never latched in the first
    # place: then it is the entire flight, while `time_lost_s` above is 0
    # because there was never a track to lose.
    dt = np.diff(t, prepend=t[0])
    out["untracked_time_total_s"] = round(float(np.sum(dt[trk == 0])), 2)

    # confidence against the two bars, while the target is inside the model crop
    sub = SB.target_subject(manifest)
    px = np.array([SB.fnum(r, "px") for r in flown])
    py = np.array([SB.fnum(r, "py") for r in flown])
    yaw = np.array([SB.fnum(r, "yaw") for r in flown])
    wall = np.array([SB.fnum(r, "wall") for r in flown])
    in_fov = np.ones(len(flown), bool)
    if truth is not None and sub is not None:
        body = (sub.get("truth") or {}).get("body", sub["name"])
        bx, by = truth[2].get(body, list(truth[2].values())[0])
        tx, ty = np.interp(wall, truth[0], bx), np.interp(wall, truth[0], by)
        bearing = (np.degrees(np.arctan2(ty - py, tx - px)) - yaw + 180) % 360 - 180
        in_fov = np.abs(bearing) <= SB.MODEL_HALF_FOV_DEG
        out["dist_mean_m"] = round(float(np.mean(np.hypot(tx - px, ty - py))), 3)
    lr = SB.latch_rule(summary)
    enter, exit_ = lr[0], lr[1]
    c = conf[in_fov & ~np.isnan(conf)]
    out["n_frames_in_fov"] = int(len(c))
    out["person_in_view_fraction"] = round(float(np.mean(in_fov)), 4)
    if len(c):
        out["conf_median_in_fov"] = round(float(np.median(c)), 4)
        out["conf_max_in_fov"] = round(float(np.max(c)), 4)
        out["conf_ge_enter"] = round(float(np.mean(c >= enter)), 4)
        out["conf_lt_exit"] = round(float(np.mean(c < exit_)), 4)
    # THE confirmation-gate number: the follower needs `confirm_frames`
    # CONSECUTIVE frames at or above the enter bar. A per-frame rate cannot say
    # whether they ever arrive together, which is the whole reason the fidelity
    # study could not answer this question and this flight can.
    ab = conf >= enter
    runs_ = [len(list(g)) for k, g in itertools.groupby(ab) if k]
    out["frames_above_enter"] = int(ab.sum())
    out["longest_above_enter_run"] = max(runs_) if runs_ else 0
    out["confirm_frames_needed"] = lr[2]
    out["vis_enter"] = enter
    out["vis_exit"] = exit_
    out["confirm_frames"] = lr[2]
    out["latch_rule_recorded"] = lr[3]
    return out


def med(v):
    return round(float(statistics.median(v)), 4) if v else None


def main():
    sb = json.loads((D / "scoreboard.json").read_text())
    by_cell = {c["cell_id"]: c for c in sb["cells"]}

    runs = {}
    for rd in sorted((D / "runs").glob("*")):
        if not (rd / "metrics.json").exists():
            continue
        rec = json.loads((rd / "metrics.json").read_text())
        if not rec.get("valid"):
            continue
        cid = rec["cell"]["cell_id"]
        runs.setdefault(cid, []).append({**rec, "extra": extra(rd), "name": rd.name})

    P("=" * 96)
    P("WHAT THE DRONE DOES WITH A TYPICAL PERSON")
    P("=" * 96)
    P(f"suite {sb['suite']}  started {sb['started_utc']}  {sb['duration_s'] // 60} min")
    P(f"flights: {sb['flight_counts']}")
    P("")

    # ---- the latch rule, asserted, not assumed ----------------------------
    P("THE BAR THAT FLEW (asserted on every flight, not assumed):")
    bad = 0
    for cid in sorted(runs):
        for r in runs[cid]:
            e = r["extra"]
            ok = (e["vis_enter"] == 0.75 and e["vis_exit"] == 0.45
                  and e["confirm_frames"] == 3 and e["latch_rule_recorded"])
            bad += 0 if ok else 1
            if not ok:
                P(f"  !! {r['name']}: vis_enter {e['vis_enter']} vis_exit {e['vis_exit']} "
                  f"confirm {e['confirm_frames']} recorded={e['latch_rule_recorded']}")
    n = sum(len(v) for v in runs.values())
    P(f"  {n - bad} of {n} flights recorded vis_enter 0.75 / vis_exit 0.45 / confirm 3 "
      f"in their own summary.json" + ("  <-- ALL" if bad == 0 else "  <-- MISMATCHES ABOVE"))
    P("")

    tsv = [("cell", "subject", "n_valid", "M1_median", "M1_min", "M1_max",
            "t_first_latch_median_s", "n_losses_total", "n_reacq_total",
            "time_lost_median_s", "time_lost_total_s", "untracked_time_median_s",
            "untracked_time_total_s", "n_never_latched", "untracked_frac_after_latch_median",
            "heading_mean_median_deg", "heading_max_deg", "dist_settled_err_median_m",
            "dist_final_median_m", "dist_mean_median_m", "conf_median_in_fov",
            "conf_ge_075_median", "conf_lt_045_median", "conf_max_max",
            "frames_above_bar_total", "longest_above_bar_run_max",
            "person_in_view_fraction_min", "verdict", "failed_gates")]

    for cell, cell_en in CELLS:
        P("=" * 96)
        P(f"{cell}   ({cell_en})")
        P("=" * 96)
        pub_cell, pub_val = PUBLISHED[cell]
        P(f"published comparator: {pub_cell} of docs/eval_results/2026-09-14-baseline-075, "
          f"M1 median {pub_val} over 4 repeats")
        P("")
        P(f"{'subject':<10}{'M1 tracked':>22}{'latch s':>9}{'losses':>8}{'re-acq':>8}"
          f"{'lost after':>12}{'untracked s':>13}{'head mean':>11}{'head max':>10}{'dist end':>10}{'verdict':>16}")
        P("  (latch s = nan means the track never latched at all: there was nothing to lose)")
        for key in ("control", "median", "p25"):
            cid = f"{cell}__{key}"
            rs = runs.get(cid, [])
            if not rs:
                P(f"{key:<10}  no valid flights")
                continue
            m1 = [r["metrics"]["M1_tracking_fraction"] for r in rs]
            lat = [r["extra"]["t_first_latch_s"] for r in rs if r["extra"]["t_first_latch_s"] is not None]
            nl = [r["extra"]["n_losses"] for r in rs]
            nr = [r["extra"]["n_reacquisitions"] for r in rs]
            tl = [r["extra"]["time_lost_s"] for r in rs]
            uf = [r["extra"]["untracked_fraction_after_latch"] for r in rs
                  if r["extra"].get("untracked_fraction_after_latch") is not None]
            hm = [r["metrics"].get("M2_heading_err_mean_deg") for r in rs
                  if r["metrics"].get("M2_heading_err_mean_deg") is not None]
            hx = [r["metrics"].get("M2_heading_err_max_deg") for r in rs
                  if r["metrics"].get("M2_heading_err_max_deg") is not None]
            de = [r["metrics"].get("M7_dist_err_settled_mean_m") for r in rs
                  if r["metrics"].get("M7_dist_err_settled_mean_m") is not None]
            df = [r["metrics"].get("M7_dist_final_m") for r in rs
                  if r["metrics"].get("M7_dist_final_m") is not None]
            dm = [r["extra"].get("dist_mean_m") for r in rs if r["extra"].get("dist_mean_m")]
            cmd_ = [r["extra"].get("conf_median_in_fov") for r in rs if r["extra"].get("conf_median_in_fov") is not None]
            cge = [r["extra"].get("conf_ge_enter") for r in rs if r["extra"].get("conf_ge_enter") is not None]
            clt = [r["extra"].get("conf_lt_exit") for r in rs if r["extra"].get("conf_lt_exit") is not None]
            cellrec = by_cell.get(cid, {})
            v = cellrec.get("verdict", "?")
            fg = ",".join(cellrec.get("failed_gates", []))
            ut = [r["extra"]["untracked_time_total_s"] for r in rs]
            P(f"{key:<10}{med(m1):>10.3f} [{min(m1):.3f},{max(m1):.3f}]"
              f"{(med(lat) if lat else float('nan')):>9.2f}{sum(nl):>8}{sum(nr):>8}"
              f"{med(tl):>12.2f}{med(ut):>13.2f}"
              f"{(med(hm) if hm else float('nan')):>11.2f}"
              f"{(max(hx) if hx else float('nan')):>10.2f}"
              f"{(med(df) if df else float('nan')):>10.2f}{v:>16}")
            tsv.append((cell, key, len(rs), med(m1), min(m1), max(m1),
                        med(lat), sum(nl), sum(nr), med(tl), round(sum(tl), 2),
                        med(ut), round(sum(ut), 2),
                        sum(1 for r in rs if r["extra"]["never_latched"]), med(uf),
                        med(hm), max(hx) if hx else None, med(de), med(df), med(dm),
                        med(cmd_), med(cge), med(clt),
                        max(r["extra"].get("conf_max_in_fov", 0) for r in rs),
                        sum(r["extra"]["frames_above_enter"] for r in rs),
                        max(r["extra"]["longest_above_enter_run"] for r in rs),
                        min(r["extra"]["person_in_view_fraction"] for r in rs),
                        v, fg))
        P("")
        P("  per-flight detail:")
        P(f"    {'run':<28}{'M1':>7}{'latch':>7}{'loss':>6}{'reacq':>7}{'lost s':>8}"
          f"{'conf med':>10}{'conf max':>10}{'>=0.75':>8}{'<0.45':>8}"
          f"{'n>=bar':>8}{'longest':>9}{'steps':>7}{'end':>12}")
        for key in ("control", "median", "p25"):
            for r in sorted(runs.get(f"{cell}__{key}", []), key=lambda x: x["name"]):
                e, m = r["extra"], r["metrics"]
                P(f"    {r['name']:<28}{m['M1_tracking_fraction']:>7.3f}"
                  f"{(e['t_first_latch_s'] if e['t_first_latch_s'] is not None else float('nan')):>7.2f}"
                  f"{e['n_losses']:>6}{e['n_reacquisitions']:>7}{e['time_lost_s']:>8.2f}"
                  f"{e.get('conf_median_in_fov', float('nan')):>10.3f}"
                  f"{e.get('conf_max_in_fov', float('nan')):>10.3f}"
                  f"{e.get('conf_ge_enter', float('nan')):>8.3f}"
                  f"{e.get('conf_lt_exit', float('nan')):>8.3f}"
                  f"{e['frames_above_enter']:>8}{e['longest_above_enter_run']:>9}"
                  f"{e['control_steps']:>7}{str(m.get('end_reason'))[:11]:>12}")
        P("")

    with open(D / "tables/per_subject.tsv", "w", newline="") as f:
        csv.writer(f, delimiter="\t").writerows(tsv)
    per_flight = [("run", "cell", "subject", "repeat", *sorted(
        set().union(*[set(r["extra"]) for v in runs.values() for r in v])))]
    for cid in sorted(runs):
        for r in sorted(runs[cid], key=lambda x: x["name"]):
            cell, key = cid.rsplit("__", 1)
            per_flight.append((r["name"], cell, key, r["cell"]["repeat"],
                               *[r["extra"].get(k) for k in per_flight[0][4:]]))
    with open(D / "tables/per_flight.tsv", "w", newline="") as f:
        csv.writer(f, delimiter="\t").writerows(per_flight)
    (D / "tables/analysis.txt").write_text("\n".join(REPORT) + "\n")
    P("wrote tables/per_subject.tsv, tables/per_flight.tsv, tables/analysis.txt")


if __name__ == "__main__":
    main()
