#!/usr/bin/env python
"""Latch-threshold sweep: paired analysis of the 96-flight interleaved session.

Imports the repo's own unmodified scoreboard.py and uses ITS metric definitions,
so every number here is the number the acceptance suite would compute. Nothing
under tools/ is written.

THREE extra per-flight quantities are derived here because the scoreboard does
not report them and the question needs them:

  * tracked_fraction_when_in_view - M1_tracking_fraction divides by the whole
    flight, which in D.occlusion includes the deliberate occlusion and in
    C/E/F includes time with no person at all. Conditioning on the target
    actually being inside the model's field of view is what "did it hold the
    person" means. (Same construction as the champion-vs-confuser run.)
  * longest_unlatched_while_in_view_s - the worst single stretch of being
    unlatched with the person plainly in view.
  * t_first_latch_s - seconds from the first processed frame to the FIRST
    tracking episode of the flight. This is "time to first latch", which the
    brief asks for and the scoreboard has no metric for. It is CENSORED when a
    flight never latches, so it is never averaged over flights that never
    latched; n_latched is reported beside it every time.

A NOTE ON THE SCOREBOARD'S OWN CONSTANTS, because it matters for reading this:
scoreboard.py carries module constants VIS_ENTER=0.70, VIS_EXIT=0.45,
CONFIRM_FRAMES=3. The gates that decide this experiment - M6 drift, M8
false-follow episodes, M1 tracking fraction - are all computed from the LOGGED
`tracking` column, so they follow whatever rule the flight actually flew and are
correct for every arm. The constants are used only by cosmetic REPORT lines
(M10_conf_max_absent's comparand, the confidence-band diagnostic, and one D
report line), which therefore still say "0.70" even in the 0.75 and 0.80 arms.
That is a labelling quirk of the report text, not an error in the numbers here.

Usage: analyze.py OUT_DIR
"""
import json
import math
import statistics
import sys
from pathlib import Path

sys.path.insert(0, "/Users/saimaruvada/Downloads/drone/pytorch_ssd/tools/crazysim_macos")
import numpy as np                                          # noqa: E402
import scoreboard as SB                                     # noqa: E402  (imported, never edited)

CONFIGS = ["t070", "t075", "t080", "t070cf4"]
CONFIG_LABEL = {"t070": "0.70 / 3 frames  (as shipped)",
                "t075": "0.75 / 3 frames",
                "t080": "0.80 / 3 frames",
                "t070cf4": "0.70 / 4 frames"}
CELLS = ["A.static__ships", "B.moving__ships", "C.empty__ships",
         "D.occlusion__ships", "E.furniture__ships", "F.pets__ships"]
PERSON_CELLS = ["A.static__ships", "B.moving__ships", "D.occlusion__ships"]
DISTRACTOR_CELLS = ["C.empty__ships", "E.furniture__ships", "F.pets__ships"]
UNRELIABLE_CELLS = ["D.occlusion__ships"]      # does not reproduce across sessions


def pearson(xs, ys):
    n = len(xs)
    if n < 2:
        return float("nan")
    mx, my = sum(xs) / n, sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = sum((x - mx) ** 2 for x in xs) ** 0.5
    dy = sum((y - my) ** 2 for y in ys) ** 0.5
    return num / (dx * dy) if dx and dy else 0.0


def spearman(xs, ys):
    def rank(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            avg = (i + j) / 2.0 + 1
            for k in range(i, j + 1):
                r[order[k]] = avg
            i = j + 1
        return r
    return pearson(rank(xs), rank(ys))


def extra_metrics(run_dir):
    """The conditional-on-visibility numbers, from the scoreboard's own loaders."""
    cell, summary, rows, truth, manifest = SB.load_run(Path(run_dir))
    flown = [r for r in rows if r.get("event", "") == ""]
    out = {}
    if not flown:
        return out
    t = np.array([SB.fnum(r, "t") for r in flown])
    conf = np.array([SB.fnum(r, "conf") for r in flown])
    trk = np.array([1 if SB.fnum(r, "tracking") > 0.5 else 0 for r in flown])
    px = np.array([SB.fnum(r, "px") for r in flown])
    py = np.array([SB.fnum(r, "py") for r in flown])
    yaw = np.array([SB.fnum(r, "yaw") for r in flown])
    wall = np.array([SB.fnum(r, "wall") for r in flown])

    # --- time to first latch (censored when it never happens) ---------------
    first = None
    for i in range(len(trk)):
        if trk[i] and (i == 0 or not trk[i - 1]):
            first = i
            break
    out["ever_latched"] = first is not None
    out["t_first_latch_s"] = round(float(t[first] - t[0]), 3) if first is not None else None

    sub = SB.target_subject(manifest)
    person_present = sub is not None and sub.get("role") == "person_target"
    in_fov = np.zeros(len(flown), bool)
    if truth is not None and sub is not None:
        body = (sub.get("truth") or {}).get("body", sub["name"])
        bx, by = truth[2].get(body, list(truth[2].values())[0])
        tx = np.interp(wall, truth[0], bx)
        ty = np.interp(wall, truth[0], by)
        bearing = (np.degrees(np.arctan2(ty - py, tx - px)) - yaw + 180) % 360 - 180
        in_fov = person_present & (np.abs(bearing) <= SB.MODEL_HALF_FOV_DEG)
        if person_present:
            d = np.hypot(tx - px, ty - py)
            out["dist_mean_m"] = round(float(np.mean(d)), 3)

    out["person_present_in_scene"] = bool(person_present)
    out["in_view_frames"] = int(in_fov.sum())
    if in_fov.any():
        out["tracked_fraction_when_in_view"] = round(float(np.mean(trk[in_fov])), 4)
        out["conf_mean_present"] = round(float(np.mean(conf[in_fov])), 4)
        # first latch measured only from when the person was first in view
        iv = np.flatnonzero(in_fov)
        f2 = None
        for i in range(iv[0], len(trk)):
            if trk[i] and (i == 0 or not trk[i - 1]):
                f2 = i
                break
        out["t_first_latch_after_in_view_s"] = (
            round(float(t[f2] - t[iv[0]]), 3) if f2 is not None else None)
        # Longest run of "person in view but not latched", in seconds.
        cur_start = None
        worst_s = 0.0
        for i in range(len(flown)):
            unlatched_in_view = bool(in_fov[i]) and trk[i] == 0
            if unlatched_in_view and cur_start is None:
                cur_start = i
            elif not unlatched_in_view and cur_start is not None:
                span = float(t[i - 1] - t[cur_start])
                worst_s = max(worst_s, span)
                cur_start = None
        if cur_start is not None:
            worst_s = max(worst_s, float(t[-1] - t[cur_start]))
        out["longest_unlatched_while_in_view_s"] = round(worst_s, 3)
    # Confidence with no person in view: what the distractor (or empty room)
    # elicits from the network.
    if (~in_fov).any():
        out["conf_mean_absent"] = round(float(np.mean(conf[~in_fov])), 4)
        out["conf_p95_absent"] = round(float(np.percentile(conf[~in_fov], 95)), 4)
        out["conf_max_absent"] = round(float(np.max(conf[~in_fov])), 4)
    return out


def _nums(vals):
    return [v for v in vals
            if isinstance(v, (int, float)) and not isinstance(v, bool)
            and not (isinstance(v, float) and math.isnan(v))]


def med(vals):
    v = _nums(vals)
    return round(statistics.median(v), 4) if v else None


def mx(vals):
    v = _nums(vals)
    return round(max(v), 4) if v else None


def mn(vals):
    v = _nums(vals)
    return round(min(v), 4) if v else None


def main():
    out_dir = Path(sys.argv[1])
    flights = [json.loads(l) for l in open(out_dir / "flights.jsonl")]

    # One record per (config, cell, repeat): the VALID flight, else the last attempt.
    best = {}
    for f in flights:
        key = (f["config"], f["cell"], f["repeat"])
        cur = best.get(key)
        if cur is None or (f["verdict"] == "VALID" and cur["verdict"] != "VALID") \
           or (f["verdict"] == cur["verdict"] and f["attempt"] > cur["attempt"]):
            best[key] = f

    per_flight = {}
    for key, f in best.items():
        rec = dict(f)
        if f["verdict"] == "VALID":
            cell, summary, rows, truth, manifest = SB.load_run(Path(f["run_dir"]))
            m, _notes = SB.metrics_for_run(cell, summary, rows, truth, manifest)
            rec["metrics"] = m
            rec["extra"] = extra_metrics(f["run_dir"])
        else:
            rec["metrics"], rec["extra"] = {}, {}
        per_flight[key] = rec

    rep = {
        "n_flight_records": len(flights),
        "n_configs": len(CONFIGS), "n_cells": len(CELLS),
        "valid_per_config": {c: sum(1 for k, v in per_flight.items()
                                    if k[0] == c and v["verdict"] == "VALID")
                             for c in CONFIGS},
    }

    # --- realised order / balance, from what ACTUALLY flew -------------------
    ordered = sorted(flights, key=lambda f: f["order"])
    firsts = [f for f in ordered if f["attempt"] == 1]
    pos = [f["order"] for f in firsts]
    reps = [f["repeat"] for f in firsts]
    rb = {"n_first_attempt_flights": len(firsts),
          "corr_repeat_vs_order_pearson": round(pearson(pos, reps), 6),
          "corr_repeat_vs_order_spearman": round(spearman(pos, reps), 6),
          "mean_order_per_config": {}, "slot_counts_per_config": {},
          "slot_counts_per_cell": {}}
    for c in CONFIGS:
        o = [f["order"] for f in firsts if f["config"] == c]
        rb["mean_order_per_config"][c] = round(sum(o) / len(o), 3) if o else None
        rb["slot_counts_per_config"][c] = {
            s: sum(1 for f in firsts if f["config"] == c and f["slot"] == s)
            for s in (1, 2, 3, 4)}
    for cid in CELLS:
        rb["slot_counts_per_cell"][cid] = {
            c: sorted(f["slot"] for f in firsts if f["cell"] == cid and f["config"] == c)
            for c in CONFIGS}
    rb["latin_square_exact_per_cell"] = all(
        sorted(v) == [1, 2, 3, 4]
        for d in rb["slot_counts_per_cell"].values() for v in d.values())
    rep["realised_balance"] = rb

    # --- the floor, the model and the latch rule, asserted per flight --------
    floors = sorted({(f.get("floor_reflectance"), f.get("floor_reflectance_manifest"))
                     for f in flights})
    rep["floor_check"] = {"distinct_pairs_xml_manifest": [list(p) for p in floors],
                          "all_matte": floors == [(0.0, 0.0)]}
    rep["model_check"] = {
        "distinct_onnx": sorted({f.get("onnx") for f in flights if f.get("onnx")}),
        "distinct_eps": sorted({f.get("eps") for f in flights if f.get("eps") is not None}),
        "distinct_sha1": sorted({f.get("onnx_sha1") for f in flights if f.get("onnx_sha1")}),
    }
    rep["threshold_check"] = {
        "flights_with_replay_verified": sum(1 for f in flights
                                            if f.get("thresh_discriminating") is not None),
        "discriminating": sum(1 for f in flights if f.get("thresh_discriminating") is True),
        "ambiguous": sum(1 for f in flights if f.get("thresh_discriminating") is False),
        "ambiguous_by_cell": {},
        "flown_pairs": sorted({(f.get("vis_enter"), f.get("confirm_frames"))
                               for f in flights if f.get("vis_enter") is not None}),
    }
    for cid in CELLS:
        n = sum(1 for f in flights if f["cell"] == cid and f.get("thresh_discriminating") is False)
        if n:
            rep["threshold_check"]["ambiguous_by_cell"][cid] = n
    rep["threshold_check"]["flown_pairs"] = [list(p) for p in rep["threshold_check"]["flown_pairs"]]

    # --- machine health ------------------------------------------------------
    def gapmax(f):
        g = f.get("step_gap_ms")
        return g.get("max") if isinstance(g, dict) else g
    rep["health"] = {
        "load1_before": {"min": mn([f["load1_before"] for f in flights]),
                         "median": med([f["load1_before"] for f in flights]),
                         "max": mx([f["load1_before"] for f in flights])},
        "load1_after": {"min": mn([f["load1_after"] for f in flights]),
                        "median": med([f["load1_after"] for f in flights]),
                        "max": mx([f["load1_after"] for f in flights])},
        "sim_wall_ratio": {"min": mn([f.get("sim_wall_ratio") for f in flights]),
                           "median": med([f.get("sim_wall_ratio") for f in flights]),
                           "max": mx([f.get("sim_wall_ratio") for f in flights])},
        "step_gap_ms_max": {"min": mn([gapmax(f) for f in flights]),
                            "median": med([gapmax(f) for f in flights]),
                            "max": mx([gapmax(f) for f in flights])},
        "attitude_upset_flights": [f["run_dir"] for f in flights if f.get("attitude_upset")],
        "n_attitude_upset_flights": sum(1 for f in flights if f.get("attitude_upset")),
        "abs_pitch_max_deg": mx([f.get("abs_pitch_max_deg") for f in flights]),
        "abs_roll_max_deg": mx([f.get("abs_roll_max_deg") for f in flights]),
        "pz_min_m": mn([f.get("pz_min_m") for f in flights]),
        "torn_frames_total": sum(f.get("torn_frames") or 0 for f in flights),
    }
    # per-config health, so a slow arm cannot masquerade as a better one
    rep["health_per_config"] = {}
    for c in CONFIGS:
        ff = [f for f in flights if f["config"] == c]
        rep["health_per_config"][c] = {
            "n": len(ff),
            "load1_before_median": med([f["load1_before"] for f in ff]),
            "sim_wall_ratio_median": med([f.get("sim_wall_ratio") for f in ff]),
            "sim_wall_ratio_min": mn([f.get("sim_wall_ratio") for f in ff]),
            "step_gap_ms_max_max": mx([gapmax(f) for f in ff]),
            "processed_hz_median": med([f.get("processed_hz") for f in ff]),
            "n_attitude_upset": sum(1 for f in ff if f.get("attitude_upset")),
        }

    # --- the per (config, cell) table ----------------------------------------
    KEYS_METRIC = ["M6_max_horizontal_drift_m", "M1_tracking_fraction",
                   "M8_false_follow_episodes", "M8_false_follow_per_min",
                   "M8_false_follow_total_s", "M8_max_drift_during_episode_m",
                   "M2_heading_err_mean_deg", "M2_heading_err_max_deg",
                   "M7_dist_err_settled_mean_m", "M7_dist_err_settled_max_m",
                   "M7_dist_final_m", "M9_gt_visible_to_relatch_s",
                   "M9_loss_episodes", "M9_unrecovered_loss",
                   "M10_conf_max_absent", "M11_yaw_reversals_per_min"]
    KEYS_EXTRA = ["tracked_fraction_when_in_view", "t_first_latch_s",
                  "t_first_latch_after_in_view_s", "longest_unlatched_while_in_view_s",
                  "conf_mean_present", "conf_max_absent", "dist_mean_m"]

    table = {}
    for c in CONFIGS:
        for cid in CELLS:
            runs = [per_flight[k] for k in per_flight
                    if k[0] == c and k[1] == cid and per_flight[k]["verdict"] == "VALID"]
            runs.sort(key=lambda r: r["repeat"])
            e = {"config": c, "cell": cid, "n_valid": len(runs),
                 "repeats": [r["repeat"] for r in runs]}
            for k in KEYS_METRIC:
                v = [r["metrics"].get(k) for r in runs]
                e[k] = {"median": med(v), "min": mn(v), "max": mx(v),
                        "all": [r["metrics"].get(k) for r in runs]}
            for k in KEYS_EXTRA:
                v = [r["extra"].get(k) for r in runs]
                e[k] = {"median": med(v), "min": mn(v), "max": mx(v),
                        "all": [r["extra"].get(k) for r in runs]}
            e["n_ever_latched"] = sum(1 for r in runs if r["extra"].get("ever_latched"))
            # THE GATE.  F is a hard drift gate at 0.5 m; C/E are hard at 0.10 m
            # plus zero false-follow episodes and zero tracking.
            cls = cid.split(".")[0]
            gates = {}
            if cls == "F":
                w = mx([r["metrics"].get("M6_max_horizontal_drift_m") for r in runs])
                gates["M6_drift_lt_0.5_worst_repeat"] = {
                    "worst": w, "limit": 0.5, "pass": (w is not None and w < 0.5)}
            elif cls in ("C", "E"):
                w = mx([r["metrics"].get("M6_max_horizontal_drift_m") for r in runs])
                ep = mx([r["metrics"].get("M8_false_follow_episodes") for r in runs])
                tf = mx([r["metrics"].get("M1_tracking_fraction") for r in runs])
                gates["M6_drift_lt_0.10_worst_repeat"] = {
                    "worst": w, "limit": 0.10, "pass": (w is not None and w < 0.10)}
                gates["M8_episodes_eq_0_worst_repeat"] = {
                    "worst": ep, "limit": 0, "pass": (ep == 0)}
                gates["M1_tracking_eq_0_worst_repeat"] = {
                    "worst": tf, "limit": 0.0, "pass": (tf == 0.0)}
            elif cls == "D":
                v = med([r["metrics"].get("M9_gt_visible_to_relatch_s") for r in runs])
                gates["M9_relatch_le_1.5_median"] = {
                    "median": v, "limit": 1.5, "pass": (v is not None and v <= 1.5),
                    "CAVEAT": "D does not reproduce across sessions; treat as unreliable"}
            e["gates"] = gates
            table[f"{c}|{cid}"] = e
    rep["table"] = table

    # --- matched-block deltas against the shipped 0.70/3 arm -----------------
    deltas = {}
    for c in CONFIGS:
        if c == "t070":
            continue
        for cid in CELLS:
            rows_ = []
            for r in (1, 2, 3, 4):
                a = per_flight.get(("t070", cid, r))
                b = per_flight.get((c, cid, r))
                if not a or not b or a["verdict"] != "VALID" or b["verdict"] != "VALID":
                    continue
                d = {"repeat": r}
                for k in ("M6_max_horizontal_drift_m", "M1_tracking_fraction",
                          "M8_false_follow_episodes"):
                    va, vb = a["metrics"].get(k), b["metrics"].get(k)
                    d[k] = None if va is None or vb is None else round(vb - va, 4)
                for k in ("tracked_fraction_when_in_view", "t_first_latch_s"):
                    va, vb = a["extra"].get(k), b["extra"].get(k)
                    d[k] = None if va is None or vb is None else round(vb - va, 4)
                rows_.append(d)
            deltas[f"{c}_minus_t070|{cid}"] = {
                "n_pairs": len(rows_), "per_repeat": rows_,
                "median": {k: med([x[k] for x in rows_])
                           for k in ("M6_max_horizontal_drift_m", "M1_tracking_fraction",
                                     "M8_false_follow_episodes",
                                     "tracked_fraction_when_in_view", "t_first_latch_s")},
                "all_same_sign_drift": (
                    len({(x["M6_max_horizontal_drift_m"] or 0) > 0 for x in rows_}) == 1
                    if rows_ else None),
            }
    rep["matched_block_deltas"] = deltas

    json.dump({"report": rep,
               "per_flight": {f"{k[0]}|{k[1]}|r{k[2]}": v for k, v in per_flight.items()}},
              open(out_dir / "analysis.json", "w"), indent=2, default=str)

    # ------------------------------- text -----------------------------------
    L = []
    P = L.append
    P("LATCH-THRESHOLD SWEEP - closed loop, one model (the champion), four latch rules")
    P("=" * 86)
    P("")
    P("Nothing here was measured on hardware. Every frame is rendered and the 'chip'")
    P("network runs under onnxruntime on a laptop, not on a GAP8.")
    P("")
    P("-- validity --")
    P(f"   flight records: {rep['n_flight_records']}")
    for c in CONFIGS:
        P(f"   {c:8s} valid flights: {rep['valid_per_config'][c]} / {len(CELLS) * 4}")
    P(f"   floor all matte (xml and manifest 0.0): {rep['floor_check']['all_matte']}")
    P(f"   distinct ONNX flown: {len(rep['model_check']['distinct_onnx'])}  "
      f"distinct eps: {len(rep['model_check']['distinct_eps'])}")
    tc = rep["threshold_check"]
    P(f"   latch rule replay-verified on {tc['flights_with_replay_verified']} flights; "
      f"{tc['discriminating']} discriminating, {tc['ambiguous']} ambiguous")
    P(f"   ambiguous by cell (nothing ever crossed the band there): {tc['ambiguous_by_cell']}")
    P(f"   distinct (vis_enter, confirm_frames) actually flown: {tc['flown_pairs']}")
    P("")
    P("-- realised balance --")
    rbb = rep["realised_balance"]
    P(f"   repeat vs flight order: pearson {rbb['corr_repeat_vs_order_pearson']}  "
      f"spearman {rbb['corr_repeat_vs_order_spearman']}")
    P(f"   mean flight order per config: {rbb['mean_order_per_config']}")
    P(f"   Latin square exact per cell (each config in each slot once): "
      f"{rbb['latin_square_exact_per_cell']}")
    P("")
    P("-- machine health --")
    h = rep["health"]
    P(f"   load1 before: min {h['load1_before']['min']} median {h['load1_before']['median']} "
      f"max {h['load1_before']['max']}")
    P(f"   sim_wall_ratio: min {h['sim_wall_ratio']['min']} median {h['sim_wall_ratio']['median']}")
    P(f"   step_gap_ms.max: median {h['step_gap_ms_max']['median']} worst {h['step_gap_ms_max']['max']}")
    P(f"   attitude upsets: {h['n_attitude_upset_flights']} flights "
      f"(|pitch| max {h['abs_pitch_max_deg']} deg, |roll| max {h['abs_roll_max_deg']} deg, "
      f"pz min {h['pz_min_m']} m)")
    P(f"   torn frames, whole session: {h['torn_frames_total']}")
    P("")

    def fmt(v, nd=3):
        return "   -  " if v is None else f"{v:.{nd}f}"

    P("=" * 86)
    P("THE PET GATE - F.pets__ships, hard gate M6 drift < 0.5 m on the worst repeat")
    P("=" * 86)
    P(f"   {'config':9s} {'worst drift':>11s} {'median':>8s} {'gate':>6s} "
      f"{'ff eps med':>10s} {'ff eps all':>14s} {'track med':>9s}")
    for c in CONFIGS:
        e = table[f"{c}|F.pets__ships"]
        g = e["gates"]["M6_drift_lt_0.5_worst_repeat"]
        P(f"   {c:9s} {fmt(g['worst']):>11s} {fmt(e['M6_max_horizontal_drift_m']['median']):>8s} "
          f"{'PASS' if g['pass'] else 'FAIL':>6s} "
          f"{fmt(e['M8_false_follow_episodes']['median'], 2):>10s} "
          f"{str(e['M8_false_follow_episodes']['all']):>14s} "
          f"{fmt(e['M1_tracking_fraction']['median']):>9s}")
    P("")
    P("=" * 86)
    P("THE COST - A.static and B.moving (recall axis)")
    P("=" * 86)
    for cid in ("A.static__ships", "B.moving__ships"):
        P(f"  {cid}")
        P(f"   {'config':9s} {'trk|in-view':>11s} {'M1 track':>9s} {'t1st latch':>10s} "
          f"{'n latched':>9s} {'hdg err':>8s} {'settled d':>9s} {'drift':>7s}")
        for c in CONFIGS:
            e = table[f"{c}|{cid}"]
            P(f"   {c:9s} {fmt(e['tracked_fraction_when_in_view']['median'], 4):>11s} "
              f"{fmt(e['M1_tracking_fraction']['median'], 4):>9s} "
              f"{fmt(e['t_first_latch_s']['median'], 2):>10s} "
              f"{e['n_ever_latched']}/{e['n_valid']:<7} "
              f"{fmt(e['M2_heading_err_mean_deg']['median'], 2):>8s} "
              f"{fmt(e['M7_dist_err_settled_mean_m']['median']):>9s} "
              f"{fmt(e['M6_max_horizontal_drift_m']['median']):>7s}")
        P("")
    P("=" * 86)
    P("THE OTHER SAFETY CELLS - C.empty and E.furniture (hard: 0 episodes, 0 tracking, drift < 0.10)")
    P("=" * 86)
    for cid in ("C.empty__ships", "E.furniture__ships"):
        P(f"  {cid}")
        for c in CONFIGS:
            e = table[f"{c}|{cid}"]
            g = e["gates"]
            allp = all(v["pass"] for v in g.values())
            P(f"   {c:9s} drift worst {fmt(g['M6_drift_lt_0.10_worst_repeat']['worst']):>7s}  "
              f"episodes worst {g['M8_episodes_eq_0_worst_repeat']['worst']}  "
              f"tracking worst {fmt(g['M1_tracking_eq_0_worst_repeat']['worst'], 4)}  "
              f"-> {'PASS' if allp else 'FAIL'}")
        P("")
    P("=" * 86)
    P("D.occlusion__ships - FLAGGED UNRELIABLE, reported but not treated as evidence")
    P("=" * 86)
    P("   This cell did not reproduce across sessions under identical config (the")
    P("   champion's own relatch was 1.24-1.41 s in one session and 4.09-9.10 s in")
    P("   another). Read the spread, not the point estimate.")
    P(f"   {'config':9s} {'relatch med':>11s} {'all relatch':>34s} {'trk|in-view':>11s} {'unrecov':>7s}")
    for c in CONFIGS:
        e = table[f"{c}|D.occlusion__ships"]
        P(f"   {c:9s} {fmt(e['M9_gt_visible_to_relatch_s']['median']):>11s} "
          f"{str(e['M9_gt_visible_to_relatch_s']['all']):>34s} "
          f"{fmt(e['tracked_fraction_when_in_view']['median'], 4):>11s} "
          f"{str(e['M9_unrecovered_loss']['all']):>7s}")
    P("")
    P("=" * 86)
    P("MATCHED-BLOCK DELTAS vs the shipped 0.70/3 arm (same cell, same repeat, same noise draw)")
    P("=" * 86)
    for c in CONFIGS:
        if c == "t070":
            continue
        P(f"  {c} minus t070")
        for cid in CELLS:
            d = deltas[f"{c}_minus_t070|{cid}"]
            m = d["median"]
            P(f"   {cid:20s} n={d['n_pairs']}  d_drift {fmt(m['M6_max_horizontal_drift_m']):>7s}  "
              f"d_ffeps {fmt(m['M8_false_follow_episodes'], 2):>6s}  "
              f"d_trk|inview {fmt(m['tracked_fraction_when_in_view'], 4):>8s}  "
              f"d_t1stlatch {fmt(m['t_first_latch_s'], 2):>7s}")
        P("")
    txt = "\n".join(L)
    (out_dir / "analysis.txt").write_text(txt + "\n")
    print(txt)


if __name__ == "__main__":
    main()
