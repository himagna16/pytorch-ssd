#!/usr/bin/env python3
"""Score a gap8_emulator.py flight of the STM32 follow app (tools/stm32_follow_app/app).

Usage: analyze_follow_app.py <run_dir> [--truth truth.csv] [--person X Y] [--json out.json]

Reads summary.json, app_log.csv (the app's firmware log, 50 Hz), packets.csv and
follow_log.csv from the run directory. Times are host-monotonic seconds since the
emulator started (packets: when built / delivered; app log: when received, ~20 ms
after the firmware sampled it). ageMs is the firmware's own now - t_fresh.

Always: modes while the app flew, packet counts, rejected packets, the sign of the
commanded vs measured yaw rate (firmware convention: + = counter-clockwise), and the
true heading error to the person (--truth CSV from the patched crazysim.py, or a
static --person X Y).
Camera freeze: hover and land delays after the last good frame, and the
re-confirmation after the freeze (GAP8 bit 0 needs 3 frames at p >= 0.75, then the
STM32 needs 3 packets with bits 0+1).
Link stall/delay/drop: packets stale by rule 0, when the app stopped steering, and
how many fresh packets it took to resume.
"""
import csv, json, math, sys
from pathlib import Path

import numpy as np

REASONS = ["none", "not_armed", "land_latched", "land_stale", "land_no_frame", "hover_stale",
           "hover_not_confirmed", "hover_rule0", "hover_reconfirm"]
MODES = {0: "WAIT_WARMUP", 1: "HOVER", 2: "FOLLOW", 3: "LAND"}
ACTIVE, LANDING, DONE = 2, 3, 4


def load(path):
    rows = []
    if not path.exists():
        return rows
    for r in csv.DictReader(open(path)):
        out = {}
        for k, v in r.items():
            try:
                out[k] = float(v) if v not in ("", None) else None
            except ValueError:
                out[k] = v
        rows.append(out)
    return rows


def wrap(d):
    return (d + 180.0) % 360.0 - 180.0


def main():
    args = sys.argv[1:]
    run = Path(args[0])
    truth = np.loadtxt(args[args.index("--truth") + 1], delimiter=",", ndmin=2) if "--truth" in args else None
    person = (float(args[args.index("--person") + 1]), float(args[args.index("--person") + 2])) \
        if "--person" in args else None
    summ = json.loads((run / "summary.json").read_text())
    app = load(run / "app_log.csv")
    pk = load(run / "packets.csv")
    ev = summ.get("events", {})
    res = {"run": str(run), "end_reason": summ["end_reason"]}
    t_act = ev.get("active")
    act = [r for r in app if r["state"] == ACTIVE]
    if not act:
        res["error"] = "the app never flew (no ACTIVE samples)"
        print(json.dumps(res, indent=2))
        return
    t_end = act[-1]["t"]
    res["active_s"] = round(t_end - act[0]["t"], 2)
    res["mode_fraction_while_active"] = summ["app_mode_fraction_while_active"]
    res["reasons_while_active"] = {REASONS[int(k)]: round(sum(1 for r in act if r["reason"] == k) / len(act), 3)
                                   for k in sorted({r["reason"] for r in act})}
    fin = summ["app_final"]
    delivered = [p for p in pk if p.get("t_deliver") is not None]
    res["packets"] = {**summ["packets"], "app_rxApp": fin.get("rxApp"), "app_rxRej": fin.get("rxRej"),
                      "app_rxStale_total": fin.get("rxStale")}
    res["max_abs_yaw_rate_cmd_dps"] = summ["app_max_abs_yaw_rate_dps"]
    res["max_abs_vx_cmd_mps"] = summ["app_max_abs_vx_mps"]
    xy = [(r["px"], r["py"]) for r in act if r.get("px") is not None]
    res["max_horizontal_drift_m"] = round(max(math.hypot(x - xy[0][0], y - xy[0][1]) for x, y in xy), 3)
    yaws = [r["yaw"] for r in act if r.get("yaw") is not None]
    res["yaw_range_deg"] = [round(min(yaws), 1), round(max(yaws), 1)]
    zs = [r["pz"] for r in act if r.get("pz") is not None]
    res["z_while_active_m"] = [round(min(zs), 2), round(max(zs), 2)]
    res["z_after_landing_m"] = summ.get("z_after_landing")
    res["sim_wall_ratio"] = summ.get("sim_wall_ratio")

    # Yaw convention: measured yaw rate (0.2 s ahead) vs the commanded one, FOLLOW samples only.
    agree, n, ratio = 0, 0, []
    for i, r in enumerate(act):
        if r["mode"] != 2 or abs(r["yawRate"] or 0.0) < 5.0:
            continue
        j = next((k for k in range(i + 1, len(act)) if act[k]["t"] - r["t"] >= 0.2), None)
        if j is None:
            break
        meas = wrap(act[j]["yaw"] - r["yaw"]) / (act[j]["t"] - r["t"])
        n += 1
        agree += int(np.sign(meas) == np.sign(r["yawRate"]))
        ratio.append(meas / r["yawRate"])
    res["yaw_convention"] = {"follow_samples_with_yaw_cmd": n,
                             "measured_rate_same_sign_as_cmd": round(agree / n, 3) if n else None,
                             "median_measured_over_cmd": round(float(np.median(ratio)), 2) if ratio else None}

    # Heading error to the person (true position), while active, after the first 3 s.
    def target(r):
        if truth is not None:
            return (float(np.interp(r["wall"], truth[:, 0], truth[:, 2])),
                    float(np.interp(r["wall"], truth[:, 0], truth[:, 3])))
        return person
    if truth is not None or person is not None:
        errs = [(r["t"], wrap(math.degrees(math.atan2(target(r)[1] - r["py"], target(r)[0] - r["px"])) - r["yaw"]))
                for r in act if r.get("yaw") is not None]
        settled = [abs(e) for t, e in errs if t - act[0]["t"] > 3.0]
        e0 = errs[0][1]
        e5 = [abs(e) for t, e in errs if 4.5 < t - act[0]["t"] < 5.5]
        res["heading_error_deg"] = {
            "at_takeover": round(e0, 1), "mean_abs_4.5_5.5s": round(float(np.mean(e5)), 1) if e5 else None,
            "turned_toward_person": (bool(e5 and np.mean(e5) < abs(e0)) if 5 < abs(e0) < 90
                                     else "n/a (started aligned, or the person is behind the camera)"),
            "settled_mean": round(float(np.mean(settled)), 1) if settled else None,
            "settled_p90": round(float(np.percentile(settled, 90)), 1) if settled else None,
            "settled_max": round(float(max(settled)), 1) if settled else None}

    wins = summ.get("fault_windows", {})
    if "freeze" in wins:
        fs, fe = wins["freeze"]
        good = [p for p in pk if p["kind"] == "frame" and p["t_build"] < fs]
        last_good = max(p["cap_t"] for p in good)
        f = {"window_s": [round(fs - t_act, 2), None if fe is None else round(fe - t_act, 2)],
             "last_good_frame_t": round(last_good - t_act, 3)}
        after = [r for r in app if r["t"] > fs]
        hov = next((r for r in after if r["reason"] == 5), None)
        land = next((r for r in after if r["state"] in (LANDING, DONE)), None)
        pre_land = None
        if land:
            pre_land = max((r for r in app if r["t"] < land["t"]), key=lambda r: r["t"], default=None)
        if hov:
            f["hover_after_last_good_s"] = round(hov["t"] - last_good, 3)
            f["hover_ageMs_fw"] = hov["ageMs"]
            f["steered_after_freeze_before_hover"] = any(r["mode"] == 2 and fs + 0.6 < r["t"] < hov["t"] for r in app)
        if land:
            rsn = max((r.get("landRsn") or 0) for r in app if r["t"] >= land["t"])
            f["landed_by"] = {1: "controller (rule 1)", 2: "operator (followapp.enable = 0)"}.get(int(rsn), "?")
            f["land_after_last_good_s"] = round(land["t"] - last_good, 3)
            f["reason_before_land"] = REASONS[int(pre_land["reason"])] if pre_land else None
            f["ageMs_fw_last_sample_before_land"] = pre_land["ageMs"] if pre_land else None
            f["ageMs_fw_first_landing_sample"] = land["ageMs"]
        nt = [p for p in pk if p["kind"] == "no-target" and p["t_build"] >= fs and (fe is None or p["t_build"] < fe)]
        f["no_target_packets_during_freeze"] = len(nt)
        f["no_target_spacing_s"] = [round(b["t_build"] - a_["t_build"], 3) for a_, b in zip(nt, nt[1:])][:6]
        if fe is not None and (not land or land["t"] > fe):
            post = [p for p in pk if p["kind"] == "frame" and p["t_build"] >= fe]
            resume = next((r for r in app if r["t"] > fe and r["mode"] == 2), None)
            f["frames_after_freeze_bits"] = [int(p["tracking"]) for p in post[:8]]
            f["first_bit0_frame_index"] = next((i + 1 for i, p in enumerate(post) if int(p["tracking"]) & 1), None)
            if resume:
                before = [p for p in post if p["t_deliver"] is not None and p["t_deliver"] <= resume["t"]]
                f["resume_follow_after_freeze_end_s"] = round(resume["t"] - fe, 3)
                f["frames_delivered_before_resume"] = len(before)
                f["bit01_packets_before_resume"] = sum(1 for p in before if int(p["tracking"]) == 3)
            # a steering sample between the freeze end and the 3rd bit0+bit1 packet would be a rule 4 violation
            third = [p for p in post if int(p["tracking"]) == 3][2:3]
            if third:
                f["steered_before_3rd_bit01_packet"] = any(
                    r["mode"] == 2 and fs + 0.6 < r["t"] < third[0]["t_deliver"] for r in app)
        res["camera_freeze"] = f

    for name in ("stall", "delay", "drop"):
        if name not in wins:
            continue
        ws, we = wins[name]
        late = [p for p in pk if p.get("link") in ("stall", "delay", "queued")]
        dropped = [p for p in pk if p.get("link") == "dropped"]
        g = {"window_s": [round(ws - t_act, 2), round(we - t_act, 2)], "packets_held": len(late),
             "packets_dropped": len(dropped)}
        if late:
            lat = [p["t_deliver"] - p["t_build"] for p in late]
            g["held_packet_latency_s"] = [round(min(lat), 3), round(max(lat), 3)]
            last_late = max(p["t_deliver"] for p in late)
            g["burst_delivered_t"] = [round(min(p["t_deliver"] for p in late) - t_act, 3), round(last_late - t_act, 3)]
        else:
            last_late = we
        before = [r for r in app if r["t"] < ws]
        stale0 = before[-1]["rxStale"] if before else 0
        post = [r for r in app if r["t"] > last_late + 0.3]
        g["rule0_stale_packets_counted"] = int((post[0]["rxStale"] if post else fin.get("rxStale")) - stale0)
        g["max_eMs_logged"] = round(max((r["eMs"] or 0.0) for r in app if ws <= r["t"] <= last_late + 0.3), 1)
        last_ok = max((p["t_deliver"] for p in delivered if p["t_deliver"] < ws), default=None)
        stop = next((r for r in app if r["t"] > ws and r["mode"] != 2), None)
        if stop:
            g["stopped_steering_after_window_start_s"] = round(stop["t"] - ws, 3)
            g["stop_reason"] = REASONS[int(stop["reason"])]
            if last_ok is not None:
                g["stop_after_last_ontime_packet_s"] = round(stop["t"] - last_ok, 3)
        g["reasons_in_window"] = sorted({REASONS[int(r["reason"])] for r in app if ws <= r["t"] <= last_late + 0.2})
        resume = next((r for r in app if r["t"] > last_late and r["mode"] == 2), None)
        g["steered_between_window_start_and_burst_end"] = any(
            r["mode"] == 2 for r in app if ws + 0.5 < r["t"] <= last_late + 0.05)
        # held packets that were fresh anyway on arrival (built within 0.1 s of delivery)
        g["held_packets_fresh_on_arrival"] = sum(1 for p in late if p["t_deliver"] - p["t_build"] <= 0.1)
        if resume:
            fresh = [p for p in delivered if last_late < p["t_deliver"] <= resume["t"] and not p.get("link")]
            g["resume_follow_after_burst_s"] = round(resume["t"] - last_late, 3)
            g["fresh_packets_before_resume"] = len(fresh)
            g["fresh_bit01_packets_before_resume"] = sum(1 for p in fresh if int(p["tracking"]) == 3)
        land = next((r for r in app if r["t"] > ws and r["state"] in (LANDING, DONE)), None)
        g["landed"] = bool(land and land["t"] < t_end + 0.5 and "operator" not in summ["end_reason"]
                           and "duration" not in summ["end_reason"])
        res[f"link_{name}"] = g

    print(json.dumps(res, indent=2))
    if "--json" in args:
        Path(args[args.index("--json") + 1]).write_text(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
