#!/usr/bin/env python
"""Per-flight analysis for the 2026-09-14 exit-bar session.

Reads every runs/x<exit>__<cell>__r<N>a<A> directory, recomputes M6 exactly the
way scoreboard.py does (max horizontal displacement from the first flown row,
over rows with event == ""), pulls the latch episodes out of follow_log.csv's
tracking column, and reports per-arm pass counts with a Clopper-Pearson interval.
For the person cell it reports tracking fraction, track losses / re-acquisitions,
time lost per drop, heading error and settled distance.

Cross-checks M6 against the scorer's metrics.json whenever one exists.
Nothing here edits tools/.

usage: analyze_exit.py <suite_dir> [--load load_samples.log] [--out-prefix P]
"""
import argparse, csv, json, math, sys
from pathlib import Path
import numpy as np

GATE = 0.5  # M6 hard gate, metres


def clopper_pearson(k, n, alpha=0.05):
    from scipy.stats import beta
    if n == 0:
        return (float("nan"), float("nan"))
    lo = 0.0 if k == 0 else float(beta.ppf(alpha / 2, k, n - k + 1))
    hi = 1.0 if k == n else float(beta.ppf(1 - alpha / 2, k + 1, n - k))
    return lo, hi


def load_series(p):
    s = []
    if p and Path(p).exists():
        for line in open(p):
            parts = line.split()
            if len(parts) >= 4:
                hh = parts[0].split(":")
                try:
                    sec = int(hh[0]) * 3600 + int(hh[1]) * 60 + int(hh[2])
                    s.append((sec, float(parts[1].rstrip(","))))
                except (ValueError, IndexError):
                    pass
    return s


def mean_load(series, t0_utc_sec, t1_utc_sec):
    v = [l for (s, l) in series if t0_utc_sec <= s <= t1_utc_sec]
    return round(sum(v) / len(v), 2) if v else None


def analyze_run(rd):
    summ = json.load(open(rd / "summary.json"))
    cell = json.load(open(rd / "cell.json"))
    rows = list(csv.DictReader(open(rd / "follow_log.csv")))
    flown = [r for r in rows if r.get("event", "") == ""]
    f = lambda k: np.array([float(r[k]) for r in flown])
    px, py, t = f("px"), f("py"), f("t")
    trk = f("tracking") > 0
    conf = f("conf")
    roll, pitch = np.abs(f("roll")), np.abs(f("pitch"))
    pz = f("pz")

    drift = np.hypot(px - px[0], py - py[0])
    i_max = int(np.argmax(drift))
    m6 = round(float(drift[i_max]), 3)
    t0 = t[0]

    # latch/track episodes
    starts = [i for i in range(1, len(trk)) if trk[i] and not trk[i - 1]]
    if len(trk) and trk[0]:
        starts.insert(0, 0)
    eps = []
    for i in starts:
        j = i
        while j + 1 < len(trk) and trk[j + 1]:
            j += 1
        eps.append((i, j))

    rec = {
        "run": rd.name,
        "cell": cell["cell_id"],
        "vis_enter": summ.get("vis_enter"),
        "vis_exit": summ.get("vis_exit"),
        "confirm_frames": summ.get("confirm_frames"),
        "repeat": cell["repeat"], "seed": cell["sensor_seed"], "order": cell.get("order"),
        "floor": cell.get("floor_reflectance"),
        "floor_manifest": cell.get("floor_reflectance_manifest"),
        "M6_drift_m": m6,
        "pass_M6": bool(m6 < GATE),
        "n_episodes": len(eps),
        "latched_s": round(float(sum(t[j] - t[i] for i, j in eps)), 2),
        "longest_ep_s": round(float(max((t[j] - t[i] for i, j in eps), default=0.0)), 2),
        "t_first_latch_s": round(float(t[eps[0][0]] - t0), 2) if eps else None,
        "conf_first_latch": round(float(conf[eps[0][0]]), 3) if eps else None,
        "tracking_fraction": summ.get("tracking_fraction"),
        "sim_wall_ratio": summ.get("sim_wall_ratio"),
        "processed_hz": summ.get("processed_hz"),
        "step_gap_max_ms": (summ.get("step_gap_ms") or {}).get("max"),
        "step_gap_median_ms": (summ.get("step_gap_ms") or {}).get("median"),
        "stale_events": summ.get("stale_events"),
        "torn_frames": summ.get("torn_frames"),
        "z_max": summ.get("z_max"),
        "end_reason": summ.get("end_reason"),
        "abs_roll_max_deg": round(float(roll.max()), 3),
        "abs_pitch_max_deg": round(float(pitch.max()), 3),
        "pz_min_m": round(float(pz.min()), 3),
        "attitude_upset_frames": int(((roll > 30) | (pitch > 30)).sum()),
        "below_floor_frames": int((pz < 0.25).sum()),
    }
    rec["attitude_upset"] = bool(rec["attitude_upset_frames"] or rec["below_floor_frames"])

    # RELEASE CONFIDENCE: the confidence on the first frame at or after the end of
    # each episode, i.e. the value that fell under vis_exit and dropped the track.
    rel = []
    for i, j in eps:
        if j + 1 < len(conf):
            rel.append(round(float(conf[j + 1]), 3))
    rec["release_confs"] = rel
    rec["release_conf_first"] = rel[0] if rel else None
    rec["release_conf_max"] = max(rel) if rel else None
    # last in-track confidence before each release
    rec["last_in_track_confs"] = [round(float(conf[j]), 3) for i, j in eps]
    # drift accumulated INSIDE the worst single episode
    rec["max_drift_in_episode_m"] = round(float(max(
        (float(np.max(np.hypot(px[i:j + 1] - px[i], py[i:j + 1] - py[i]))) for i, j in eps),
        default=0.0)), 3)

    # ---- person-cell metrics (B.moving) ----
    if cell["cell_id"].startswith("B.moving"):
        # losses = episodes that ENDED before the last frame; reacquisitions = episodes after the first
        n_ep = len(eps)
        ended_early = sum(1 for i, j in eps if j < len(trk) - 1)
        rec["track_losses"] = ended_early
        rec["reacquisitions"] = max(0, n_ep - 1)
        gaps = []
        for k in range(1, n_ep):
            gaps.append(float(t[eps[k][0]] - t[eps[k - 1][1]]))
        rec["gap_s_list"] = [round(g, 2) for g in gaps]
        rec["time_lost_total_s"] = round(float(sum(gaps)), 2)
        rec["time_lost_mean_s"] = round(float(sum(gaps) / len(gaps)), 2) if gaps else None
        rec["time_lost_max_s"] = round(float(max(gaps)), 2) if gaps else None
        rec["untracked_s"] = round(float((~trk).sum() / max(len(trk), 1) * (t[-1] - t[0])), 2)
        # heading error + settled distance from metrics.json when the scorer wrote one
        mp = rd / "metrics.json"
        if mp.exists():
            m = json.load(open(mp))
            for k, v in m.items():
                if "heading" in k or "M2" in k or "M7" in k or "dist" in k or "M1_" in k:
                    rec["scorer_" + k] = v
        # heading error straight from the log, tracked frames only
        if "hdg_err" in (flown[0] if flown else {}):
            he = np.abs(f("hdg_err"))[trk]
        elif "heading_err" in (flown[0] if flown else {}):
            he = np.abs(f("heading_err"))[trk]
        else:
            he = None
        if he is not None and len(he):
            rec["hdg_err_mean_deg"] = round(float(he.mean()), 3)
            rec["hdg_err_max_deg"] = round(float(he.max()), 3)

    # scorer cross-check
    mp = rd / "metrics.json"
    if mp.exists():
        m = json.load(open(mp))
        for k in m:
            if "M6" in k:
                try:
                    rec["scorer_M6"] = float(m[k]["value"] if isinstance(m[k], dict) else m[k])
                except (TypeError, ValueError, KeyError):
                    rec["scorer_M6"] = m[k]
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("suite")
    ap.add_argument("--load", default=None)
    ap.add_argument("--out-prefix", default=None)
    a = ap.parse_args()
    suite = Path(a.suite)
    runs = sorted((suite / "runs").glob("x*__*"))

    # flown order from flights.jsonl
    order = {}
    fj = suite / "flights.jsonl"
    flightrec = {}
    if fj.exists():
        for line in open(fj):
            r = json.loads(line)
            order[Path(r["run_dir"]).name] = r["order"]
            flightrec[Path(r["run_dir"]).name] = r

    recs = []
    for rd in runs:
        if not (rd / "summary.json").exists():
            continue
        try:
            rec = analyze_run(rd)
        except Exception as e:
            print(f"SKIP {rd.name}: {e}", file=sys.stderr)
            continue
        fr = flightrec.get(rd.name, {})
        rec["flown_order"] = fr.get("order", order.get(rd.name))
        rec["verdict"] = fr.get("verdict")
        rec["wall_s"] = fr.get("wall_s")
        rec["load1_before"] = fr.get("load1_before")
        rec["load1_after"] = fr.get("load1_after")
        rec["load1_mean"] = (round((fr["load1_before"] + fr["load1_after"]) / 2, 2)
                             if fr.get("load1_before") is not None else None)
        recs.append(rec)
    recs.sort(key=lambda r: (r["flown_order"] is None, r["flown_order"]))

    pre = a.out_prefix or str(suite / "flight_records")
    with open(pre + ".jsonl", "w") as f:
        for r in recs:
            f.write(json.dumps(r) + "\n")

    lines = []
    pets = [r for r in recs if r["cell"].startswith("F.pets") and r["verdict"] == "VALID"]
    move = [r for r in recs if r["cell"].startswith("B.moving") and r["verdict"] == "VALID"]

    lines.append("## Threshold audit (every VALID flight)\n")
    lines.append("| run | order | planned exit | summary vis_enter | summary vis_exit | confirm_frames | floor xml | floor manifest |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for r in recs:
        lines.append(f"| {r['run']} | {r['flown_order']} | {r['run'].split('__')[0][1:]} | "
                     f"{r['vis_enter']} | {r['vis_exit']} | {r['confirm_frames']} | {r['floor']} | {r['floor_manifest']} |")
    lines.append("")

    for label, group, gate in (("PETS  F.pets__ships", pets, True), ("PERSON  B.moving__ships", move, False)):
        if not group:
            continue
        lines.append(f"\n## {label}\n")
        arms = sorted({r["vis_exit"] for r in group})
        if gate:
            lines.append("| arm (vis_exit) | n | M6 drifts, flown order | pass <0.5 | rate | CP95 | median | worst | latched s (median [min-max]) | eps (median) | t_first (median) | release conf (median [min-max]) |")
            lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|")
            for arm in arms:
                g = [r for r in group if r["vis_exit"] == arm]
                d = [r["M6_drift_m"] for r in g]
                k = sum(1 for x in d if x < GATE); n = len(d)
                lo, hi = clopper_pearson(k, n)
                lat = sorted(r["latched_s"] for r in g)
                epn = sorted(r["n_episodes"] for r in g)
                tf = sorted(r["t_first_latch_s"] for r in g if r["t_first_latch_s"] is not None)
                rel = sorted(x for r in g for x in r["release_confs"])
                med = lambda v: round(float(np.median(v)), 3) if v else None
                lines.append(
                    f"| **{arm}** | {n} | {', '.join(f'{x:.3f}' for x in d)} | {k}/{n} | "
                    f"{k/n:.3f} | [{lo:.3f}, {hi:.3f}] | {med(d)} | {max(d):.3f} | "
                    f"{med(lat)} [{min(lat):.2f}-{max(lat):.2f}] | {med(epn)} | "
                    f"{med(tf) if tf else '-'} | "
                    f"{med(rel) if rel else '-'} [{min(rel):.3f}-{max(rel):.3f}]" if rel else
                    f"| **{arm}** | {n} | {', '.join(f'{x:.3f}' for x in d)} | {k}/{n} | {k/n:.3f} | [{lo:.3f}, {hi:.3f}] | {med(d)} | {max(d):.3f} | {med(lat)} | {med(epn)} | {med(tf)} | - |")
                lines[-1] += " |"
        else:
            lines.append("| arm (vis_exit) | n | tracking fraction (per flight) | mean | losses | re-acquires | time lost total s | time lost max s | hdg err mean deg | hdg err max deg |")
            lines.append("|---|---|---|---|---|---|---|---|---|---|")
            for arm in arms:
                g = [r for r in group if r["vis_exit"] == arm]
                tfr = [r["tracking_fraction"] for r in g]
                lines.append(
                    f"| **{arm}** | {len(g)} | {', '.join(f'{x:.4f}' for x in tfr)} | "
                    f"{sum(tfr)/len(tfr):.4f} | {sum(r['track_losses'] for r in g)} | "
                    f"{sum(r['reacquisitions'] for r in g)} | "
                    f"{sum(r['time_lost_total_s'] for r in g):.2f} | "
                    f"{max((r['time_lost_max_s'] or 0) for r in g):.2f} | "
                    f"{np.mean([r.get('hdg_err_mean_deg') or float('nan') for r in g]):.2f} | "
                    f"{np.nanmax([r.get('hdg_err_max_deg') or float('nan') for r in g]):.2f} |")

    lines.append("\n## Per-flight detail (flown order)\n")
    cols = ["flown_order", "run", "vis_exit", "repeat", "seed", "M6_drift_m", "pass_M6",
            "t_first_latch_s", "conf_first_latch", "latched_s", "n_episodes", "longest_ep_s",
            "max_drift_in_episode_m", "release_conf_first", "release_conf_max",
            "tracking_fraction", "sim_wall_ratio", "processed_hz", "step_gap_max_ms",
            "abs_roll_max_deg", "abs_pitch_max_deg", "attitude_upset", "load1_mean", "wall_s"]
    lines.append("| " + " | ".join(cols) + " |")
    lines.append("|" + "---|" * len(cols))
    for r in recs:
        lines.append("| " + " | ".join(str(r.get(c)) for c in cols) + " |")

    md = "\n".join(lines) + "\n"
    open(pre + ".md", "w").write(md)
    print(md)


if __name__ == "__main__":
    main()
