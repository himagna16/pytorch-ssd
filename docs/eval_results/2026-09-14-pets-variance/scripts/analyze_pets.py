#!/usr/bin/env python
"""Per-flight F.pets__ships analysis for the 2026-09-14 pets-variance session.

Reads each runs/F.pets__ships__r<N>a<A> directory (the VALID attempt per repeat, in
flown order), recomputes M6 exactly the way scoreboard.py does (max horizontal
displacement from the first flown row over rows with event == ""), pulls the latch
episodes from follow_log.csv's tracking column, and adds the timing / load / attitude
columns the brief asked for. If the scorer's metrics.json exists for a run, M6 is
cross-checked against it. Nothing here edits tools/.

usage: analyze_pets.py <suite_dir> [--load load_samples.log] [--json out.jsonl] [--md out.md]
"""
import argparse, csv, json, math, sys
from pathlib import Path
import numpy as np

GATE = 0.5  # M6 hard gate, metres

def read_follow_log(p):
    rows = list(csv.DictReader(open(p)))
    return rows

def read_truth(p):
    # first line: "# bodies: subj_dog,subj_cat"; rows: wall, t, x,y,z per body
    bodies = []
    data = []
    for line in open(p):
        if line.startswith("#"):
            if "bodies:" in line:
                bodies = line.split("bodies:")[1].strip().split(",")
            continue
        parts = line.strip().split(",")
        if len(parts) < 2 + 3 * len(bodies):
            continue
        data.append([float(x) for x in parts])
    a = np.array(data)
    out = {"wall": a[:, 0], "t": a[:, 1]}
    for k, b in enumerate(bodies):
        out[b] = a[:, 2 + 3 * k: 5 + 3 * k]
    return out

def clopper_pearson(k, n, alpha=0.05):
    from scipy.stats import beta
    lo = 0.0 if k == 0 else beta.ppf(alpha / 2, k, n - k + 1)
    hi = 1.0 if k == n else beta.ppf(1 - alpha / 2, k + 1, n - k)
    return lo, hi

def load_samples(p):
    s = []
    if p and Path(p).exists():
        for line in open(p):
            parts = line.split()
            if len(parts) >= 6:
                try:
                    s.append((float(parts[0]), float(parts[3].strip("{}")), float(parts[4]), float(parts[5].strip("{}"))))
                except ValueError:
                    pass
    return s

def analyze_run(rd, loads):
    summ = json.load(open(rd / "summary.json"))
    cell = json.load(open(rd / "cell.json"))
    rows = read_follow_log(rd / "follow_log.csv")
    flown = [r for r in rows if r.get("event", "") == ""]
    px = np.array([float(r["px"]) for r in flown]); py = np.array([float(r["py"]) for r in flown])
    t = np.array([float(r["t"]) for r in flown]); wall = np.array([float(r["wall"]) for r in flown])
    trk = np.array([int(float(r["tracking"])) for r in flown]) > 0
    conf = np.array([float(r["conf"]) for r in flown])
    yaw = np.array([float(r["yaw"]) for r in flown])
    roll = np.array([float(r["roll"]) for r in flown]); pitch = np.array([float(r["pitch"]) for r in flown])
    cmd_yaw = np.array([float(r["cmd_yaw"]) for r in flown]); cmd_vx = np.array([float(r["cmd_vx"]) for r in flown])
    xbox = np.array([float(r["x"]) for r in flown])
    drift = np.hypot(px - px[0], py - py[0])
    i_max = int(np.argmax(drift))
    m6 = round(float(drift[i_max]), 3)
    t0 = t[0]

    # latch episodes (scoreboard M8 logic; the pets scene has no person so every episode is false)
    starts = [i for i in range(1, len(trk)) if trk[i] and not trk[i - 1]]
    if trk[0]:
        starts.insert(0, 0)
    eps = []
    for i in starts:
        j = i
        while j + 1 < len(trk) and trk[j + 1]:
            j += 1
        eps.append((i, j))
    n_eps = len(eps)
    t_first = round(float(t[eps[0][0]] - t0), 2) if eps else None
    conf_first = round(float(conf[eps[0][0]]), 3) if eps else None
    x_first = round(float(xbox[eps[0][0]]), 3) if eps else None
    cmdyaw_first = round(float(cmd_yaw[eps[0][0]]), 2) if eps else None
    latched_s = round(float(sum(t[j] - t[i] for i, j in eps)), 2)
    longest_ep_s = round(float(max((t[j] - t[i] for i, j in eps), default=0.0)), 2)
    # drift accumulated within episodes vs. between
    ep_drift = round(float(max((max(np.hypot(px[i:j + 1] - px[i], py[i:j + 1] - py[i])) for i, j in eps), default=0.0)), 3)

    # approach direction: net displacement bearing at max-drift, vs bearing to dog / cat
    dx, dy = float(px[i_max] - px[0]), float(py[i_max] - py[0])
    disp_bearing = round(math.degrees(math.atan2(dy, dx)), 1) if drift[i_max] > 0.02 else None
    toward = None; dog_xy = cat_xy = None; dog_y_first = dog_vy_first = dog_y_max = None
    tp = rd / "truth.csv"
    if tp.exists():
        try:
            tr = read_truth(tp)
            dog = tr.get("subj_dog"); cat = tr.get("subj_cat")
            if dog is not None:
                k = int(np.argmin(np.abs(tr["wall"] - wall[i_max])))
                dog_xy = [round(float(dog[k, 0]), 2), round(float(dog[k, 1]), 2)]
                cat_xy = [round(float(cat[k, 0]), 2), round(float(cat[k, 1]), 2)] if cat is not None else None
                dog_y_max = round(float(dog[k, 1]), 2)
                if eps:
                    kf = int(np.argmin(np.abs(tr["wall"] - wall[eps[0][0]])))
                    dog_y_first = round(float(dog[kf, 1]), 2)
                    k2 = min(kf + 5, len(tr["wall"]) - 1); k1 = max(kf - 5, 0)
                    dvy = float(dog[k2, 1] - dog[k1, 1]) / max(float(tr["wall"][k2] - tr["wall"][k1]), 1e-6)
                    dog_vy_first = round(dvy, 3)
                if disp_bearing is not None:
                    b_dog = math.degrees(math.atan2(dog_xy[1] - py[0], dog_xy[0] - px[0]))
                    b_cat = math.degrees(math.atan2(cat_xy[1] - py[0], cat_xy[0] - px[0])) if cat_xy else None
                    d_dog = abs((disp_bearing - b_dog + 180) % 360 - 180)
                    d_cat = abs((disp_bearing - b_cat + 180) % 360 - 180) if b_cat is not None else 999
                    toward = "dog" if d_dog < d_cat else "cat"
                    toward += f" (off {min(d_dog, d_cat):.0f} deg)"
        except Exception as e:  # truth parsing must never kill the table
            toward = f"truth-parse-error: {e}"

    # load average over the flight's wall window
    la = [s for s in loads if wall[0] - 5 <= s[0] <= wall[-1] + 5]
    load1 = round(float(np.mean([s[1] for s in la])), 2) if la else None
    load1_max = round(float(np.max([s[1] for s in la])), 2) if la else None

    m6_scorer = None
    mp = rd / "metrics.json"
    if mp.exists():
        try:
            m6_scorer = json.load(open(mp))["metrics"].get("M6_max_horizontal_drift_m")
        except Exception:
            pass

    sg = summ.get("step_gap_ms") or {}
    return {
        "run": rd.name, "repeat": cell["repeat"], "attempt": cell["attempt"], "sensor_seed": cell["sensor_seed"],
        "vis_enter": summ.get("vis_enter"), "vis_exit": summ.get("vis_exit"), "confirm_frames": summ.get("confirm_frames"),
        "M6_drift_m": m6, "M6_scorer": m6_scorer, "pass": m6 < GATE,
        "t_first_latch_s": t_first, "conf_first_latch": conf_first, "x_first_latch": x_first, "cmd_yaw_first_latch": cmdyaw_first,
        "latched_s": latched_s, "episodes": n_eps, "longest_episode_s": longest_ep_s, "max_drift_within_episode_m": ep_drift,
        "tracking_fraction": summ.get("tracking_fraction"), "flown_s": round(float(t[-1] - t0), 1),
        "drift_bearing_deg": disp_bearing, "drift_toward": toward, "dog_xy_at_max": dog_xy, "cat_xy_at_max": cat_xy,
        "t_max_drift_s": round(float(t[i_max] - t0), 2),
        "dog_y_first_latch": dog_y_first, "dog_vy_first_latch": dog_vy_first, "dog_y_at_max_drift": dog_y_max,
        "yaw_at_max_drift_deg": round(float(yaw[i_max]), 1), "yaw_range_deg": summ.get("yaw_range_deg"),
        "roll_abs_max_deg": round(float(np.max(np.abs(roll))), 2), "pitch_abs_max_deg": round(float(np.max(np.abs(pitch))), 2),
        "z_max": summ.get("z_max"), "z_after_landing": summ.get("z_after_landing"), "end_reason": summ.get("end_reason"),
        "sim_wall_ratio": summ.get("sim_wall_ratio"), "processed_hz": summ.get("processed_hz"),
        "step_gap_ms_max": sg.get("max"), "step_gap_ms_median": sg.get("median"), "step_gap_ms_min": sg.get("min"),
        "frames_processed": summ.get("frames_processed"), "frames_dropped": summ.get("frames_dropped"),
        "stale_events": summ.get("stale_events"), "load1_mean": load1, "load1_max": load1_max,
        "wall_start": float(wall[0]), "wall_end": float(wall[-1]),
    }

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("suite_dir", type=Path)
    ap.add_argument("--load", default=None)
    ap.add_argument("--json", default=None)
    ap.add_argument("--md", default=None)
    ap.add_argument("--cell", default="F.pets__ships")
    a = ap.parse_args()
    loads = load_samples(a.load)
    runs = sorted((a.suite_dir / "runs").glob(f"{a.cell}__r*a*"), key=lambda p: (int(p.name.split("__r")[1].split("a")[0]), int(p.name.split("a")[-1])))
    by_rep = {}
    for rd in runs:
        if not (rd / "summary.json").exists():
            continue
        chk = (rd / "check.txt").read_text().split("\n")[0] if (rd / "check.txt").exists() else ""
        if chk and not chk.startswith("VALID"):
            continue
        rec = analyze_run(rd, loads)
        by_rep[rec["repeat"]] = rec  # later attempt (re-fly) supersedes
    recs = [by_rep[k] for k in sorted(by_rep)]
    if a.json:
        with open(a.json, "w") as f:
            for r in recs:
                f.write(json.dumps(r) + "\n")
    hdr = ["rep", "seed", "vis_enter", "M6 m", "scorer", "gate", "t_first s", "conf1", "x1", "cmdyaw1", "latched s", "eps", "longest ep", "trk frac",
           "drift toward", "bearing", "dog y@1st", "dog vy@1st", "yaw@max", "|roll|max", "|pitch|max", "zmax", "sim/wall", "Hz", "gap max ms", "load1"]
    lines = ["| " + " | ".join(hdr) + " |", "|" + "---|" * len(hdr)]
    for r in recs:
        lines.append("| " + " | ".join(str(x) for x in [
            r["repeat"], r["sensor_seed"], r["vis_enter"], f'{r["M6_drift_m"]:.3f}', r["M6_scorer"], "PASS" if r["pass"] else "FAIL",
            r["t_first_latch_s"], r["conf_first_latch"], r["x_first_latch"], r["cmd_yaw_first_latch"], r["latched_s"], r["episodes"], r["longest_episode_s"],
            r["tracking_fraction"], r["drift_toward"], r["drift_bearing_deg"], r["dog_y_first_latch"], r["dog_vy_first_latch"], r["yaw_at_max_drift_deg"], r["roll_abs_max_deg"], r["pitch_abs_max_deg"],
            r["z_max"], r["sim_wall_ratio"], r["processed_hz"], r["step_gap_ms_max"], r["load1_mean"]]) + " |")
    n = len(recs); k = sum(1 for r in recs if r["pass"])
    lines.append("")
    if n:
        lo, hi = clopper_pearson(k, n)
        d = [r["M6_drift_m"] for r in recs]
        lines.append(f"flights={n} pass(<{GATE} m)={k} fail={n-k} pass_rate={k/n:.3f} Clopper-Pearson 95% = [{lo:.3f}, {hi:.3f}]")
        lines.append(f"M6 drift: min {min(d):.3f} median {float(np.median(d)):.3f} max {max(d):.3f} mean {float(np.mean(d)):.3f} sd {float(np.std(d, ddof=1)) if n>1 else 0:.3f}")
        lines.append("drifts in flown order: " + ", ".join(f"{x:.3f}" for x in d))
        bad = [r for r in recs if r["M6_scorer"] is not None and abs(r["M6_scorer"] - r["M6_drift_m"]) > 1e-6]
        lines.append(f"scorer cross-check: {sum(1 for r in recs if r['M6_scorer'] is not None)} runs had metrics.json, {len(bad)} mismatches")
        ve = sorted(set(str(r["vis_enter"]) for r in recs))
        lines.append(f"vis_enter values seen in summary.json: {ve}")
        # pass-vs-fail comparison on everything numeric we recorded
        P_ = [r for r in recs if r["pass"]]; F_ = [r for r in recs if not r["pass"]]
        if P_ and F_:
            from scipy.stats import mannwhitneyu
            lines.append("")
            lines.append(f"pass ({len(P_)}) vs fail ({len(F_)}) flights, median [min-max], Mann-Whitney two-sided p:")
            lines.append("| column | pass median [min-max] | fail median [min-max] | p |")
            lines.append("|---|---|---|---|")
            for col in ["t_first_latch_s", "conf_first_latch", "latched_s", "episodes", "longest_episode_s", "max_drift_within_episode_m",
                        "tracking_fraction", "t_max_drift_s", "drift_bearing_deg", "dog_y_first_latch", "dog_vy_first_latch", "dog_y_at_max_drift", "yaw_at_max_drift_deg", "roll_abs_max_deg", "pitch_abs_max_deg",
                        "sim_wall_ratio", "processed_hz", "step_gap_ms_max", "step_gap_ms_median", "frames_dropped", "load1_mean", "load1_max", "sensor_seed"]:
                a_ = [r[col] for r in P_ if r[col] is not None]; b_ = [r[col] for r in F_ if r[col] is not None]
                if not a_ or not b_: continue
                try: pv = f"{mannwhitneyu(a_, b_, alternative='two-sided').pvalue:.3f}"
                except Exception: pv = "n/a"
                lines.append(f"| {col} | {float(np.median(a_)):.3g} [{min(a_):.3g}-{max(a_):.3g}] | {float(np.median(b_)):.3g} [{min(b_):.3g}-{max(b_):.3g}] | {pv} |")
            tw = lambda rs: {k: sum(1 for r in rs if (r["drift_toward"] or "").startswith(k)) for k in ("dog", "cat")}
            lines.append(f"drift direction, pass: {tw(P_)}  fail: {tw(F_)}")
    txt = "\n".join(lines)
    print(txt)
    if a.md:
        Path(a.md).write_text(txt + "\n")

if __name__ == "__main__":
    main()
