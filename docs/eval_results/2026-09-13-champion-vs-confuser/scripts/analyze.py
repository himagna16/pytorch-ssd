#!/usr/bin/env python
"""Champion vs confuser: paired analysis of the 48-flight interleaved session.

Imports the repo's own unmodified scoreboard.py and uses ITS metric definitions,
so every number here is the number the acceptance suite would compute. Nothing
under tools/ is written.

Two extra per-flight quantities are derived here because the scoreboard does not
report them and the question needs them:

  * tracked_fraction_when_in_view - M1_tracking_fraction divides by the whole
    flight, which in D.occlusion includes the deliberate occlusion and in
    C/E/F includes time with no person at all. Conditioning on the target
    actually being inside the model's field of view is what "did it hold the
    person" means.
  * longest_unlatched_while_in_view_s - the worst single stretch of being
    unlatched with the person plainly in view. This is the "outright loss"
    number; M9_track_outage_s is close but is keyed on loss episodes that
    recovered before the flight ended.

Both use the scoreboard's own in_fov construction (bearing within the model's
half-FOV of a person_target), recomputed here from the same logs.

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

MODELS = ["champion", "confuser"]
CELLS = ["A.static__ships", "B.moving__ships", "C.empty__ships",
         "D.occlusion__ships", "E.furniture__ships", "F.pets__ships"]
PERSON_CELLS = ["A.static__ships", "B.moving__ships", "D.occlusion__ships"]
DISTRACTOR_CELLS = ["C.empty__ships", "E.furniture__ships", "F.pets__ships"]


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
    """The two conditional-on-visibility numbers, from the scoreboard's own loaders."""
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
        # Longest run of "person in view but not latched", in seconds.
        worst = cur_start = None
        worst_s = 0.0
        for i in range(len(flown)):
            unlatched_in_view = bool(in_fov[i]) and trk[i] == 0
            if unlatched_in_view and cur_start is None:
                cur_start = i
            elif not unlatched_in_view and cur_start is not None:
                span = float(t[i - 1] - t[cur_start])
                if span > worst_s:
                    worst_s, worst = span, (cur_start, i - 1)
                cur_start = None
        if cur_start is not None:
            span = float(t[-1] - t[cur_start])
            if span > worst_s:
                worst_s = span
        out["longest_unlatched_while_in_view_s"] = round(worst_s, 3)
    # Confidence with no person in view: what the distractor (or empty room)
    # elicits from the network.
    if (~in_fov).any():
        out["conf_mean_absent"] = round(float(np.mean(conf[~in_fov])), 4)
        out["conf_p95_absent"] = round(float(np.percentile(conf[~in_fov], 95)), 4)
        out["conf_max_absent"] = round(float(np.max(conf[~in_fov])), 4)
        out["frac_absent_conf_over_latch"] = round(
            float(np.mean(conf[~in_fov] >= SB.VIS_ENTER)), 4)
    return out


def med(vals):
    vals = [v for v in vals if isinstance(v, (int, float)) and not isinstance(v, bool)
            and not (isinstance(v, float) and math.isnan(v))]
    return round(statistics.median(vals), 4) if vals else None


def main():
    out_dir = Path(sys.argv[1])
    flights = [json.loads(l) for l in open(out_dir / "flights.jsonl")]

    # One record per (model, cell, repeat): the VALID flight, else the last attempt.
    best = {}
    for f in flights:
        key = (f["model"], f["cell"], f["repeat"])
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

    rep = {"n_flight_records": len(flights), "n_cells": len(CELLS),
           "valid": {m: sum(1 for k, v in per_flight.items()
                            if k[0] == m and v["verdict"] == "VALID") for m in MODELS}}

    # --- realised order / balance, from what ACTUALLY flew -------------------
    ordered = sorted(flights, key=lambda f: f["order"])
    firsts = [f for f in ordered if f["attempt"] == 1]
    pos = [f["order"] for f in firsts]
    reps = [f["repeat"] for f in firsts]
    rep["realised_order"] = {
        "n": len(firsts),
        "corr_repeat_vs_order_pearson": round(pearson(pos, reps), 6),
        "corr_repeat_vs_order_spearman": round(spearman(pos, reps), 6),
        "mean_order_champion": round(statistics.mean(
            [f["order"] for f in firsts if f["model"] == "champion"]), 3),
        "mean_order_confuser": round(statistics.mean(
            [f["order"] for f in firsts if f["model"] == "confuser"]), 3),
        "max_consecutive_same_model": max(
            len(list(g)) for g in __import__("itertools").groupby(
                [f["model"] for f in firsts])) if firsts else 0,
    }
    for m in MODELS:
        p = [f["order"] for f in firsts if f["model"] == m]
        r = [f["repeat"] for f in firsts if f["model"] == m]
        rep["realised_order"][f"corr_repeat_vs_order_{m}"] = round(pearson(p, r), 6)

    # --- health -------------------------------------------------------------
    health = {}
    for m in MODELS:
        fs = [v for k, v in per_flight.items() if k[0] == m and v["verdict"] == "VALID"]
        gaps = [v["step_gap_ms"]["max"] for v in fs if isinstance(v.get("step_gap_ms"), dict)]
        health[m] = {
            "n": len(fs),
            "sim_wall_ratio": {"min": min(v["sim_wall_ratio"] for v in fs),
                               "median": med([v["sim_wall_ratio"] for v in fs]),
                               "max": max(v["sim_wall_ratio"] for v in fs)},
            "step_gap_ms_max": {"min": min(gaps), "median": med(gaps), "max": max(gaps)},
            "load1_before": {"min": min(v["load1_before"] for v in fs),
                             "median": med([v["load1_before"] for v in fs]),
                             "max": max(v["load1_before"] for v in fs)},
            "load1_after": {"min": min(v["load1_after"] for v in fs),
                            "median": med([v["load1_after"] for v in fs]),
                            "max": max(v["load1_after"] for v in fs)},
            "abs_pitch_max_deg": max(v.get("abs_pitch_max_deg", 0) for v in fs),
            "abs_roll_max_deg": max(v.get("abs_roll_max_deg", 0) for v in fs),
            "pz_min_m": min(v.get("pz_min_m", 9) for v in fs),
            "attitude_upset_flights": sum(1 for v in fs if v.get("attitude_upset")),
            "attitude_upset_frames_total": sum(v.get("attitude_upset_frames", 0) for v in fs),
            "below_floor_frames_total": sum(v.get("below_floor_frames", 0) for v in fs),
            "floor_reflectance_values": sorted({v.get("floor_reflectance") for v in fs}),
            "floor_manifest_values": sorted({v.get("floor_reflectance_manifest") for v in fs}),
            "eps_values": sorted({v.get("eps") for v in fs}),
            "onnx_sha1_values": sorted({v.get("onnx_sha1") for v in fs}),
        }
    rep["health"] = health

    # --- per-cell tables ----------------------------------------------------
    FALSE_KEYS = ["M8_false_follow_episodes", "M8_false_follow_total_s",
                  "M8_max_drift_during_episode_m", "M6_max_horizontal_drift_m",
                  "M1_tracking_fraction", "M8_t_first_false_follow_s",
                  "M8_conf_at_first_false_follow", "M10_conf_max_absent"]
    FALSE_EXTRA = ["conf_mean_absent", "conf_p95_absent", "conf_max_absent",
                   "frac_absent_conf_over_latch"]
    TRACK_KEYS = ["M1_tracking_fraction", "M2_heading_err_mean_deg", "M2_heading_err_max_deg",
                  "M7_dist_err_settled_mean_m", "M7_dist_final_m", "M7_in_band_fraction",
                  "M9_loss_episodes", "M9_track_outage_s", "M9_gt_visible_to_relatch_s",
                  "M9_reconfirm_latency_s", "M9_unrecovered_loss",
                  "M10_conf_mean_present", "M10_uncertain_fraction_present"]
    TRACK_EXTRA = ["tracked_fraction_when_in_view", "longest_unlatched_while_in_view_s",
                   "conf_mean_present", "dist_mean_m"]

    tables = {}
    for cid in CELLS:
        keys = FALSE_KEYS if cid in DISTRACTOR_CELLS else TRACK_KEYS
        xkeys = FALSE_EXTRA if cid in DISTRACTOR_CELLS else TRACK_EXTRA
        entry = {"cell": cid, "per_model": {}, "paired": {}}
        for m in MODELS:
            fs = [per_flight[(m, cid, r)] for r in (1, 2, 3, 4)
                  if (m, cid, r) in per_flight and per_flight[(m, cid, r)]["verdict"] == "VALID"]
            col = {"n_valid": len(fs)}
            for k in keys:
                vals = [f["metrics"].get(k) for f in fs]
                vals = [1.0 if v is True else 0.0 if v is False else v for v in vals]
                col[k] = {"values": vals, "median": med(vals)}
            for k in xkeys:
                vals = [f["extra"].get(k) for f in fs]
                col[k] = {"values": vals, "median": med(vals)}
            entry["per_model"][m] = col
        # paired per repeat: confuser minus champion
        for k in list(keys) + list(xkeys):
            deltas = []
            for r in (1, 2, 3, 4):
                a = per_flight.get(("champion", cid, r))
                b = per_flight.get(("confuser", cid, r))
                if not a or not b or a["verdict"] != "VALID" or b["verdict"] != "VALID":
                    continue
                src = "metrics" if k in keys else "extra"
                va, vb = a[src].get(k), b[src].get(k)
                va = 1.0 if va is True else 0.0 if va is False else va
                vb = 1.0 if vb is True else 0.0 if vb is False else vb
                if isinstance(va, (int, float)) and isinstance(vb, (int, float)):
                    deltas.append(round(vb - va, 4))
            if deltas:
                entry["paired"][k] = {"deltas_confuser_minus_champion": deltas,
                                      "median": med(deltas),
                                      "n_pairs": len(deltas),
                                      "sign_consistent": all(d > 0 for d in deltas)
                                                          or all(d < 0 for d in deltas)
                                                          or all(d == 0 for d in deltas)}
        tables[cid] = entry
    rep["cells"] = tables

    json.dump({"report": rep,
               "per_flight": {f"{k[0]}|{k[1]}|r{k[2]}": v for k, v in per_flight.items()}},
              open(out_dir / "analysis.json", "w"), indent=2, default=str)

    # A flat, readable index of every flight in chronological order.
    import csv as _csv
    cols = ["order", "t_start_utc", "model", "cell", "repeat", "attempt", "pair", "verdict",
            "wall_s", "floor_reflectance", "floor_reflectance_manifest", "eps", "onnx_sha1",
            "sim_wall_ratio", "processed_hz", "step_gap_ms_max", "tracking_fraction",
            "load1_before", "load1_after", "abs_pitch_max_deg", "abs_roll_max_deg",
            "pz_min_m", "attitude_upset_frames", "below_floor_frames", "reason"]
    with open(out_dir / "flight_index.csv", "w", newline="") as fh:
        w = _csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for f in ordered:
            row = dict(f)
            g = f.get("step_gap_ms")
            row["step_gap_ms_max"] = g.get("max") if isinstance(g, dict) else g
            w.writerow(row)

    # ---- text report -------------------------------------------------------
    L = []
    A = L.append
    A("CHAMPION vs CONFUSER - 48-flight interleaved session, matte floor, chip cells")
    A("=" * 78)
    A(f"flight records: {rep['n_flight_records']}   valid: {rep['valid']}")
    A("")
    A("-- realised order (from what actually flew, first attempts) --")
    for k, v in rep["realised_order"].items():
        A(f"   {k:38s} {v}")
    A("")
    A("-- health --")
    for m in MODELS:
        h = health[m]
        A(f"   {m}:")
        A(f"      sim_wall_ratio   min {h['sim_wall_ratio']['min']} "
          f"med {h['sim_wall_ratio']['median']} max {h['sim_wall_ratio']['max']}")
        A(f"      step_gap_ms.max  min {h['step_gap_ms_max']['min']} "
          f"med {h['step_gap_ms_max']['median']} max {h['step_gap_ms_max']['max']}")
        A(f"      load1 before     min {h['load1_before']['min']} "
          f"med {h['load1_before']['median']} max {h['load1_before']['max']}")
        A(f"      load1 after      min {h['load1_after']['min']} "
          f"med {h['load1_after']['median']} max {h['load1_after']['max']}")
        A(f"      |pitch|max {h['abs_pitch_max_deg']} deg  |roll|max {h['abs_roll_max_deg']} deg  "
          f"pz_min {h['pz_min_m']} m")
        A(f"      attitude upsets: {h['attitude_upset_flights']} flights, "
          f"{h['attitude_upset_frames_total']} frames; below-floor frames "
          f"{h['below_floor_frames_total']}")
        A(f"      floor xml {h['floor_reflectance_values']} manifest {h['floor_manifest_values']}")
        A(f"      eps {h['eps_values']}  onnx_sha1 {h['onnx_sha1_values']}")
    A("")
    for cid in CELLS:
        e = tables[cid]
        keys = FALSE_KEYS + FALSE_EXTRA if cid in DISTRACTOR_CELLS else TRACK_KEYS + TRACK_EXTRA
        A(f"== {cid} ==".ljust(78, "="))
        hdr = f"   {'metric':38s} {'champion':>28s} {'confuser':>28s}   paired delta"
        A(hdr)
        for k in keys:
            c = e["per_model"]["champion"].get(k, {})
            f_ = e["per_model"]["confuser"].get(k, {})
            pd = e["paired"].get(k, {})
            cs = f"{c.get('median')} {c.get('values')}"
            fs = f"{f_.get('median')} {f_.get('values')}"
            d = pd.get("median")
            flag = ""
            if pd and pd.get("sign_consistent") and d not in (None, 0):
                flag = " *"
            A(f"   {k:38s} {cs:>28s} {fs:>28s}   {d}{flag}")
        A("")
    A("* = every matched pair moved the same way")
    txt = "\n".join(L)
    (out_dir / "analysis.txt").write_text(txt)
    print(txt)


if __name__ == "__main__":
    main()
