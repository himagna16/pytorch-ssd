#!/usr/bin/env python3
"""Enter-bar results per cell and per arm, with the ENTRY-GATE MARGIN in full.

Everything the scoreboard computes is READ from each run's metrics.json (written
by tools/crazysim_macos/scoreboard.py); this script never re-derives M1, M2 or
M7.  What it adds is the set of quantities the scoreboard has no metric for, and
which last night's audit (docs/eval_results/2026-09-15-typical-person) showed are
the ones that actually decide a marginal subject:

  t_first_latch_s          time from the first control step to the first latched
                           step.
  untracked_time_total_s   time not tracking over the WHOLE flight.  The honest
                           "time lost" for a flight that never latched, where
                           M9_track_outage_all_s reads empty because its loop
                           lists only losses that recover.
  run_lengths              THE ENTRY-GATE MARGIN.  The follower latches on
                           `confirm_frames` CONSECUTIVE frames at or above the
                           bar.  A cell whose longest run is 2 and one whose
                           longest run is 0 both read 0.000 tracking and are not
                           the same situation.  So this reports the whole
                           DISTRIBUTION of consecutive above-bar run lengths per
                           flight, not just the maximum.

  Both bars are evaluated on every trace (`margin_at`), so a 0.75 flight can be
  asked what its own frames would have done against 0.70 and vice versa.  THAT
  CROSS-BAR NUMBER IS A COUNTERFACTUAL AND IS ONLY MEANINGFUL BEFORE THE FIRST
  LATCH: once the follower latches it starts moving, and the trace it then sees
  is not the trace the other arm saw.  It is printed as a cross-check on the
  flown arms, never as a substitute for them.

Confidence statistics are taken over frames where the target is inside the
model's +-35 deg crop, exactly as analyze_typical.py did.

Usage: nemoenv/bin/python analyze_enter.py <suite_dir>
"""
import collections
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
ARMS = ["0.70", "0.75"]
BARS = [0.70, 0.75]
SUBJECT = {"control": "COCO 19432, the flown cutout, 99.2nd pct",
           "median": "COCO 250127, 52.1st pct",
           "p25": "COCO 124442, 28.4th pct"}
REPORT = []


def P(s=""):
    print(s, flush=True)
    REPORT.append(s)


def runs_of(mask):
    return [len(list(g)) for k, g in itertools.groupby(mask) if k]


def extra(run_dir):
    cell, summary, rows, truth, manifest = SB.load_run(run_dir)
    flown = [r for r in rows if r.get("event") == ""]
    t = np.array([SB.fnum(r, "t") for r in flown])
    trk = np.array([int(SB.fnum(r, "tracking") or 0) for r in flown])
    conf = np.array([SB.fnum(r, "conf") for r in flown])
    out = {"control_steps": len(flown), "flown_s": round(float(t[-1] - t[0]), 2)}

    latched = np.where(trk == 1)[0]
    out["latched_ever"] = bool(len(latched))
    out["t_first_latch_s"] = round(float(t[latched[0]] - t[0]), 3) if len(latched) else None
    out["first_latch_idx"] = int(latched[0]) if len(latched) else None

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
                    lost += float(t[-1] - t[i])
                i = j + 1
            i += 1
    out["n_losses"] = losses
    out["n_reacquisitions"] = reacq
    out["time_lost_s"] = round(lost, 2)
    out["never_latched"] = not bool(len(latched))
    dt = np.diff(t, prepend=t[0])
    out["untracked_time_total_s"] = round(float(np.sum(dt[trk == 0])), 2)

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
        out["dist_min_m"] = round(float(np.min(np.hypot(tx - px, ty - py))), 3)
    lr = SB.latch_rule(summary)
    enter, exit_ = lr[0], lr[1]
    out["vis_enter"] = enter
    out["vis_exit"] = exit_
    out["confirm_frames"] = lr[2]
    out["latch_rule_recorded"] = lr[3]

    ok = in_fov & ~np.isnan(conf)
    c = conf[ok]
    out["n_frames_in_fov"] = int(len(c))
    out["person_in_view_fraction"] = round(float(np.mean(in_fov)), 4)
    if len(c):
        out["conf_median_in_fov"] = round(float(np.median(c)), 4)
        out["conf_max_in_fov"] = round(float(np.max(c)), 4)
        out["conf_ge_enter"] = round(float(np.mean(c >= enter)), 4)
        out["conf_lt_exit"] = round(float(np.mean(c < exit_)), 4)

    # THE ENTRY-GATE MARGIN, at the flown bar and at the other one.
    # `pre_latch` restricts to the frames before the follower first latched --
    # the only stretch on which a cross-bar counterfactual means anything,
    # because after a latch the drone moves and the view changes.
    cut = out["first_latch_idx"] if out["first_latch_idx"] is not None else len(conf)
    margins = {}
    for bar in BARS:
        ab = conf >= bar
        rl = runs_of(ab)
        pre = runs_of(ab[:cut])
        margins[f"{bar:.2f}"] = {
            "frames_above": int(ab.sum()),
            "longest_run": max(rl) if rl else 0,
            "run_lengths": sorted(rl, reverse=True),
            "run_hist": dict(sorted(collections.Counter(rl).items())),
            "n_runs_ge3": sum(1 for r in rl if r >= 3),
            "pre_latch_longest_run": max(pre) if pre else 0,
            "pre_latch_frames_above": int(ab[:cut].sum()),
            "pre_latch_n_frames": int(cut),
        }
    out["margin_at"] = margins
    m = margins[f"{enter:.2f}"]
    out["frames_above_enter"] = m["frames_above"]
    out["longest_above_enter_run"] = m["longest_run"]
    out["run_lengths_at_enter"] = m["run_lengths"]
    out["run_hist_at_enter"] = m["run_hist"]
    return out


def med(v):
    return round(float(statistics.median(v)), 4) if v else None


def main():
    runs = {}
    for rd in sorted((D / "runs").glob("*")):
        if not (rd / "metrics.json").exists():
            continue
        rec = json.loads((rd / "metrics.json").read_text())
        if not rec.get("valid"):
            P(f"  SKIPPED (scoreboard says INVALID): {rd.name}")
            continue
        cellj = json.loads((rd / "cell.json").read_text())
        arm = f"{cellj['vis_enter']:.2f}"
        e = extra(rd)
        # refuse to score a flight whose RECORDED threshold is not the planned one
        if abs(e["vis_enter"] - cellj["vis_enter"]) > 1e-9 \
           or abs(e["vis_exit"] - 0.45) > 1e-9 or e["confirm_frames"] != 3:
            P(f"  REFUSED (recorded threshold != plan row): {rd.name} "
              f"recorded enter={e['vis_enter']} exit={e['vis_exit']} cf={e['confirm_frames']} "
              f"plan enter={cellj['vis_enter']}")
            continue
        cid = rec["cell"]["cell_id"]
        runs.setdefault((cid, arm), []).append(
            {**rec, "extra": e, "name": rd.name, "repeat": cellj["repeat"]})

    cells = sorted({k[0] for k in runs})
    rows_tsv, flight_tsv = [], []

    P("=" * 110)
    P("ENTRY-GATE MARGIN AND ACQUISITION, 0.70 vs 0.75, everything else shipped (exit 0.45, confirm 3)")
    P("=" * 110)

    for cid in cells:
        subj = cid.split("__")[1]
        P("")
        P(f"### {cid}   subject: {SUBJECT.get(subj, subj)}")
        P("")
        P(f"  {'arm':<7}{'n':>3}{'M1 med':>9}{'M1 min':>8}{'M1 max':>8}{'latched':>9}"
          f"{'t_latch':>9}{'loss':>6}{'reacq':>7}{'lost s':>8}{'untrk s':>9}"
          f"{'hdg mean':>10}{'hdg max':>9}{'dist end':>9}{'longest':>9}")
        for arm in ARMS:
            rs = runs.get((cid, arm), [])
            if not rs:
                P(f"  {arm:<7}{0:>3}   (no valid flights)")
                continue
            m1 = [r["metrics"]["M1_tracking_fraction"] for r in rs]
            nl = sum(1 for r in rs if r["extra"]["latched_ever"])
            lat = [r["extra"]["t_first_latch_s"] for r in rs if r["extra"]["t_first_latch_s"] is not None]
            hm = [r["metrics"].get("M2_heading_err_mean_deg") for r in rs]
            hx = [r["metrics"].get("M2_heading_err_max_deg") for r in rs]
            hm = [x for x in hm if x is not None]; hx = [x for x in hx if x is not None]
            df = [r["metrics"].get("M7_final_dist_m") for r in rs]
            df = [x for x in df if x is not None]
            lg = [r["extra"]["longest_above_enter_run"] for r in rs]
            P(f"  {arm:<7}{len(rs):>3}{med(m1):>9.3f}{min(m1):>8.3f}{max(m1):>8.3f}"
              f"{str(nl)+'/'+str(len(rs)):>9}"
              f"{(med(lat) if lat else float('nan')):>9.2f}"
              f"{sum(r['extra']['n_losses'] for r in rs):>6}"
              f"{sum(r['extra']['n_reacquisitions'] for r in rs):>7}"
              f"{med([r['extra']['time_lost_s'] for r in rs]):>8.2f}"
              f"{med([r['extra']['untracked_time_total_s'] for r in rs]):>9.2f}"
              f"{(med(hm) if hm else float('nan')):>10.2f}"
              f"{(max(hx) if hx else float('nan')):>9.2f}"
              f"{(med(df) if df else float('nan')):>9.2f}"
              f"{max(lg):>9}")
            rows_tsv.append((cid, subj, arm, len(rs), med(m1), min(m1), max(m1), nl,
                             med(lat) if lat else None,
                             sum(r["extra"]["n_losses"] for r in rs),
                             sum(r["extra"]["n_reacquisitions"] for r in rs),
                             med([r["extra"]["time_lost_s"] for r in rs]),
                             med([r["extra"]["untracked_time_total_s"] for r in rs]),
                             med(hm) if hm else None, max(hx) if hx else None,
                             med(df) if df else None,
                             med([r["extra"].get("conf_median_in_fov") for r in rs]),
                             max(r["extra"].get("conf_max_in_fov", 0) for r in rs),
                             med([r["extra"].get("conf_ge_enter") for r in rs]),
                             sum(r["extra"]["frames_above_enter"] for r in rs),
                             max(lg), min(lg),
                             min(r["extra"]["person_in_view_fraction"] for r in rs)))

        P("")
        P("  ENTRY-GATE MARGIN, per flight.  run lengths = every run of CONSECUTIVE frames")
        P("  at or above the FLOWN bar; the follower needs 3.  '(cf @other)' is the same trace")
        P("  scored against the other arm's bar, PRE-LATCH ONLY, as a counterfactual cross-check.")
        P("")
        P(f"    {'run':<34}{'M1':>7}{'n frm':>7}{'conf med':>9}{'conf max':>9}"
          f"{'n>=bar':>7}{'longest':>8}{'#runs>=3':>9}  {'run-length histogram':<28}{'cf @other':>10}")
        for arm in ARMS:
            for r in sorted(runs.get((cid, arm), []), key=lambda x: x["name"]):
                e = r["extra"]; m = r["metrics"]
                other = "0.70" if arm == "0.75" else "0.75"
                om = e["margin_at"][other]
                hist = " ".join(f"{k}x{v}" for k, v in e["run_hist_at_enter"].items()) or "-"
                P(f"    {r['name']:<34}{m['M1_tracking_fraction']:>7.3f}"
                  f"{e['n_frames_in_fov']:>7}"
                  f"{e.get('conf_median_in_fov', float('nan')):>9.3f}"
                  f"{e.get('conf_max_in_fov', float('nan')):>9.3f}"
                  f"{e['frames_above_enter']:>7}{e['longest_above_enter_run']:>8}"
                  f"{e['margin_at'][arm]['n_runs_ge3']:>9}  {hist:<28}"
                  f"{om['pre_latch_longest_run']:>10}")
                flight_tsv.append((cid, subj, arm, r["repeat"], r["name"],
                                   m["M1_tracking_fraction"], e["latched_ever"],
                                   e["t_first_latch_s"], e["n_losses"], e["n_reacquisitions"],
                                   e["time_lost_s"], e["untracked_time_total_s"],
                                   e["flown_s"], e["control_steps"], e["n_frames_in_fov"],
                                   e.get("conf_median_in_fov"), e.get("conf_max_in_fov"),
                                   e.get("conf_ge_enter"), e.get("conf_lt_exit"),
                                   e["frames_above_enter"], e["longest_above_enter_run"],
                                   e["margin_at"][arm]["n_runs_ge3"],
                                   json.dumps(e["run_hist_at_enter"]),
                                   json.dumps(e["run_lengths_at_enter"][:12]),
                                   om["pre_latch_longest_run"], om["pre_latch_frames_above"],
                                   m.get("M2_heading_err_mean_deg"), m.get("M2_heading_err_max_deg"),
                                   m.get("M7_final_dist_m"), e.get("dist_mean_m"), e.get("dist_min_m"),
                                   e["person_in_view_fraction"], e["vis_enter"], e["vis_exit"],
                                   e["confirm_frames"], e["latch_rule_recorded"]))

        # paired, same repeat = same himax noise draw
        P("")
        P("  PAIRED by repeat (same sensor seed, so the only difference is the bar):")
        for rep in (1, 2, 3):
            a = [r for r in runs.get((cid, "0.70"), []) if r["repeat"] == rep]
            b = [r for r in runs.get((cid, "0.75"), []) if r["repeat"] == rep]
            if not a or not b:
                continue
            a, b = a[0], b[0]
            P(f"    r{rep} seed {1000+rep}:  0.70 -> M1 {a['metrics']['M1_tracking_fraction']:.3f} "
              f"longest {a['extra']['longest_above_enter_run']} "
              f"latch {a['extra']['t_first_latch_s']}   |   "
              f"0.75 -> M1 {b['metrics']['M1_tracking_fraction']:.3f} "
              f"longest {b['extra']['longest_above_enter_run']} "
              f"latch {b['extra']['t_first_latch_s']}")

    # the rule last night's audit proposed, retested here
    P("")
    P("=" * 110)
    P("THE RULE: a flight latches if and only if its longest above-bar run reaches confirm_frames (3).")
    bad = []
    for (cid, arm), rs in sorted(runs.items()):
        for r in rs:
            e = r["extra"]
            if bool(e["longest_above_enter_run"] >= 3) != bool(e["latched_ever"]):
                bad.append((r["name"], e["longest_above_enter_run"], e["latched_ever"]))
    n = sum(len(v) for v in runs.values())
    P(f"  checked {n} flights: {'HOLDS on all of them' if not bad else 'VIOLATED by ' + str(bad)}")
    P("=" * 110)

    with open(D / "tables/per_cell_arm.tsv", "w") as f:
        f.write("\t".join(["cell", "subject", "arm", "n", "M1_med", "M1_min", "M1_max",
                           "n_latched", "t_first_latch_med_s", "losses", "reacq",
                           "time_lost_med_s", "untracked_total_med_s",
                           "hdg_mean_med_deg", "hdg_max_deg", "final_dist_med_m",
                           "conf_med", "conf_max", "frac_ge_bar_med", "frames_above_bar_total",
                           "longest_run_max", "longest_run_min", "in_view_frac_min"]) + "\n")
        for r in rows_tsv:
            f.write("\t".join("" if x is None else str(x) for x in r) + "\n")
    with open(D / "tables/per_flight.tsv", "w") as f:
        f.write("\t".join(["cell", "subject", "arm", "repeat", "run", "M1", "latched",
                           "t_first_latch_s", "losses", "reacq", "time_lost_s",
                           "untracked_total_s", "flown_s", "control_steps", "n_frames_in_fov",
                           "conf_med", "conf_max", "frac_ge_bar", "frac_lt_exit",
                           "frames_above_bar", "longest_run", "n_runs_ge3",
                           "run_hist", "run_lengths", "cf_other_bar_prelatch_longest",
                           "cf_other_bar_prelatch_frames", "M2_hdg_mean", "M2_hdg_max",
                           "M7_final_dist_m", "dist_mean_m", "dist_min_m",
                           "in_view_frac", "rec_vis_enter", "rec_vis_exit",
                           "rec_confirm_frames", "latch_rule_recorded"]) + "\n")
        for r in flight_tsv:
            f.write("\t".join("" if x is None else str(x) for x in r) + "\n")
    (D / "tables/analysis.txt").write_text("\n".join(REPORT) + "\n")
    P("")
    P(f"wrote {D}/tables/per_cell_arm.tsv, per_flight.tsv, analysis.txt")


main()
