#!/usr/bin/env python3
"""Score follow-app flights flown with the first-flight safety modes (yawOnly, geofence).

    ../../../trainenv/bin/python sim/flight_modes_summary.py <fly_app.sh output dir> <name> [<name> ...] \
        --out docs/sim_results/2026-10-01-flight-modes

Reads <dir>/run_<name>/app_log.csv (the app's firmware log at 50 Hz, written by gap8_emulator.py),
<dir>/run_<name>/summary.json and <dir>/truth_<name>.csv (the person's true position), and writes
summary.json (one entry per flight) and <name>_10hz.csv (a 10 Hz trace) into --out.

Per flight: the arming point and modes the app latched; while the app was ACTIVE, the horizontal
distance from the arming point (drift), the height, the heading error to the person's true
bearing, the commanded yaw rate / forward speed / setpoint kinds; then the landing (reason,
fence status that caused it, time from the LANDING state to DONE, and how far past the fence the
drone went). Times are host seconds from the emulator start. The log blocks are sampled 20 ms
apart and are not simultaneous, so event times are good to about 20 ms.
"""
import argparse
import bisect
import csv
import json
import math
from pathlib import Path

STATES = {0: "IDLE", 1: "WAIT_ARM", 2: "ACTIVE", 3: "LANDING", 4: "DONE"}
LAND = {0: "none", 1: "controller (rule 1)", 2: "operator", 3: "geofence", 4: "position estimate invalid"}
FENCE = {0: "ok", 1: "outside x/y", 2: "above fenceZ", 3: "no Kalman estimate", 4: "non-finite estimate",
         5: "variance above posVarMax"}
SP = {0: "none", 1: "velocity", 2: "position hold", 3: "landing", 4: "motor stop"}


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def wrap180(a):
    return (a + 180.0) % 360.0 - 180.0


def pct(xs, q):
    if not xs:
        return None
    s = sorted(xs)
    k = min(len(s) - 1, max(0, int(round(q / 100.0 * (len(s) - 1)))))
    return s[k]


def r(x, nd=3):
    return None if x is None else round(x, nd)


def load_truth(path):
    """wall time -> person (x, y). truth CSV rows: wall, sim_t, x, y."""
    walls, xy = [], []
    if not path.exists():
        return walls, xy
    for row in csv.reader(open(path)):
        try:
            walls.append(float(row[0]))
            xy.append((float(row[2]), float(row[3])))
        except (ValueError, IndexError):
            continue
    return walls, xy


def person_at(walls, xy, wall):
    if not walls:
        return None
    i = min(max(bisect.bisect_left(walls, wall), 0), len(walls) - 1)
    return xy[i]


def score(run_dir, truth_path, fence_x=1.0, fence_y=1.0):
    rows = list(csv.DictReader(open(run_dir / "app_log.csv")))
    summ = json.loads((run_dir / "summary.json").read_text())
    walls, pxy = load_truth(truth_path)
    for row in rows:
        for k in list(row):
            row[k] = num(row[k]) if k not in () else row[k]
    st = [int(row["state"]) if row.get("state") is not None else -1 for row in rows]
    act = [row for row, s in zip(rows, st) if s == 2]
    out = {"end_reason": summ.get("end_reason"), "sim_wall_ratio": summ.get("sim_wall_ratio"),
           "app_params": summ.get("events", {}).get("app_params", {}),
           "crazysim_extra": None}
    last = rows[-1] if rows else {}
    out["final"] = {"state": STATES.get(int(last.get("state") or 0)), "armErr": last.get("armErr"),
                    "fence": FENCE.get(int(last["fence"])) if last.get("fence") is not None else None}
    if not act:
        out["active"] = None
        pv = [row["posVar"] for row in rows if row.get("posVar") is not None]
        out["posVar_whole_flight"] = {"min": min(pv), "max": max(pv)} if pv else None
        return out, rows
    ax, ay = act[-1].get("armX"), act[-1].get("armY")
    t0, t1 = act[0]["t"], act[-1]["t"]
    drift = [math.hypot(row["px"] - ax, row["py"] - ay) for row in act]
    settled = [row for row in act if row["t"] >= t0 + 1.0]
    herr = []
    for row in act:
        p = person_at(walls, pxy, row["wall"])
        if p is None:
            continue
        bearing = math.degrees(math.atan2(p[1] - row["py"], p[0] - row["px"]))
        herr.append((row["t"], wrap180(row["yaw"] - bearing), bearing))
    late = [abs(e) for t, e, _ in herr if t >= t0 + 5.0]
    turning = [row for row in act if abs(row.get("yawRate") or 0.0) > 1.0]
    kinds = {}
    for row in act:
        k = SP.get(int(row["spKind"])) if row.get("spKind") is not None else None
        kinds[k] = kinds.get(k, 0) + 1
    out["active"] = {
        "t_start": r(t0, 2), "t_end": r(t1, 2), "duration_s": r(t1 - t0, 2),
        "arm_point": {"x": r(ax, 4), "y": r(ay, 4)},
        "modes": int(act[-1]["modes"]) if act[-1].get("modes") is not None else None,
        "drift_from_arm_point_m": {"mean": r(sum(drift) / len(drift), 4), "p95": r(pct(drift, 95), 4),
                                   "max": r(max(drift), 4), "final": r(drift[-1], 4)},
        "x_range_m": [r(min(row["px"] for row in act), 3), r(max(row["px"] for row in act), 3)],
        "y_range_m": [r(min(row["py"] for row in act), 3), r(max(row["py"] for row in act), 3)],
        "z_after_1s_m": {"mean": r(sum(row["pz"] for row in settled) / len(settled), 3),
                         "min": r(min(row["pz"] for row in settled), 3),
                         "max": r(max(row["pz"] for row in settled), 3)} if settled else None,
        "heading_error_deg": {
            "at_take_over": r(herr[0][1], 1) if herr else None,
            "person_bearing_at_take_over": r(herr[0][2], 1) if herr else None,
            "yaw_at_take_over": r(act[0]["yaw"], 1),
            "mean_abs_after_5s": r(sum(late) / len(late), 2) if late else None,
            "max_abs_after_5s": r(max(late), 2) if late else None,
        },
        "yaw_rate_cmd_dps": {"first": r(act[0].get("yawRate"), 2),
                             "max_abs": r(max(abs(row.get("yawRate") or 0.0) for row in act), 2)},
        # commanded turn toward the person: sign(yaw rate) == sign(bearing - yaw) while turning
        "turn_toward_person_fraction": r(
            sum(1 for row, (_, e, _) in zip(act, herr) if abs(row.get("yawRate") or 0.0) > 1.0
                and (row["yawRate"] > 0) == (e < 0)) / len(turning), 3) if turning and herr else None,
        "max_abs_vx_sent_mps": r(max(abs(row.get("vx") or 0.0) for row in act), 3),
        "max_abs_wVx_mps": r(max(abs(row.get("wVx") or 0.0) for row in act), 3),
        "setpoint_kinds_logged": kinds,
        "posVar_m2": {"min": act and min(row["posVar"] for row in act), "max": max(row["posVar"] for row in act)},
    }
    land = [row for row, s in zip(rows, st) if s == 3]
    done = [row for row, s in zip(rows, st) if s == 4]
    if land:
        lr = int(last.get("landRsn") or 0)
        fh = int(last.get("fenceHit") or 0)
        out["landing"] = {
            "reason": LAND.get(lr), "fence_hit": FENCE.get(fh) if lr in (3, 4) else None,
            "t_landing_state": r(land[0]["t"], 3),
            "pose_at_landing_state": {"x": r(land[0]["px"], 3), "y": r(land[0]["py"], 3), "z": r(land[0]["pz"], 3)},
            "t_done": r(done[0]["t"], 3) if done else None,
            "landing_to_done_s": r(done[0]["t"] - land[0]["t"], 2) if done else None,
            "z_at_done": r(done[0]["pz"], 3) if done else None,
            "z_after_landing": summ.get("z_after_landing"),
        }
        if lr == 3:
            after = [row for row in rows if row["t"] >= land[0]["t"]]
            dx = [abs(row["px"] - ax) for row in rows if row["t"] >= t0]
            first_out = next((row for row in rows if row["t"] >= t0 and
                              (abs(row["px"] - ax) > fence_x or abs(row["py"] - ay) > fence_y)), None)
            out["landing"]["fence"] = {
                "first_logged_sample_outside": r(first_out["t"], 3) if first_out else None,
                "logged_x_at_landing_state": r(land[0]["px"] - ax, 4),
                "max_abs_dx_from_arm_point": r(max(dx), 4),
                "max_overshoot_past_fence_m": r(max(abs(row["px"] - ax) for row in after) - fence_x, 4),
            }
    return out, rows


def write_trace(path, rows, walls, pxy):
    keys = ["t", "state", "px", "py", "pz", "yaw", "bearing", "yawRate", "wYaw", "vx", "wVx", "zCmd", "spKind",
            "fence", "posVar", "landRsn"]
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(keys)
        next_t = None
        for row in rows:
            if row.get("t") is None:
                continue
            if next_t is not None and row["t"] < next_t:
                continue
            next_t = row["t"] + 0.1
            p = person_at(walls, pxy, row["wall"]) if row.get("wall") else None
            b = math.degrees(math.atan2(p[1] - row["py"], p[0] - row["px"])) if p and row.get("px") is not None else None
            vals = []
            for k in keys:
                v = b if k == "bearing" else row.get(k)
                if v is None:
                    vals.append("")
                elif k in ("state", "spKind", "fence", "landRsn"):
                    vals.append(int(v))
                elif k == "posVar":
                    vals.append(f"{v:.3g}")
                else:
                    vals.append(round(v, 4))
            w.writerow(vals)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("flight_dir", type=Path)
    ap.add_argument("names", nargs="+")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--extra", action="append", default=[], metavar="NAME=FLAGS",
                    help="record the crazysim.py flags a flight used (CRAZYSIM_EXTRA), e.g. noabs=--flowdeck")
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    extra = dict(kv.split("=", 1) for kv in a.extra)
    res = {}
    for n in a.names:
        run = a.flight_dir / f"run_{n}"
        truth = a.flight_dir / f"truth_{n}.csv"
        s, rows = score(run, truth)
        s["crazysim_extra"] = extra.get(n, "")
        res[n] = s
        walls, pxy = load_truth(truth)
        write_trace(a.out / f"{n}_10hz.csv", rows, walls, pxy)
    (a.out / "summary.json").write_text(json.dumps(res, indent=2) + "\n")
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
