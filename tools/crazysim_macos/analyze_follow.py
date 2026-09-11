"""Analyze a follow_person.py run against the person's position.

Usage: analyze_follow.py <run_dir> <person_x> <person_y> [--truth truth.csv] [--brief]
--truth: CSV from the patched crazysim.py (wall_time,sim_time,x,y), joined to
the follower log on wall-clock time. Without it, the person is static at
(person_x, person_y).
"""
import csv, json, math, sys
from pathlib import Path
import numpy as np

args = sys.argv[1:]
out, tx0, ty0 = Path(args[0]), float(args[1]), float(args[2])
brief = "--brief" in args
truth = np.loadtxt(args[args.index("--truth") + 1], delimiter=",", ndmin=2) if "--truth" in args else None
summary = json.loads((out / "summary.json").read_text())
rows = [r for r in csv.DictReader(open(out / "follow_log.csv")) if r.get("event", "") == ""]

def f(r, k):
    try: return float(r[k])
    except (KeyError, ValueError, TypeError): return float("nan")

def target(r):
    if truth is None: return tx0, ty0
    w = f(r, "wall")
    return float(np.interp(w, truth[:, 0], truth[:, 2])), float(np.interp(w, truth[:, 0], truth[:, 3]))

recs = []
for r in rows:
    px, py, yaw = f(r, "px"), f(r, "py"), f(r, "yaw")
    txx, tyy = target(r)
    err = (math.degrees(math.atan2(tyy - py, txx - px)) - yaw + 180) % 360 - 180
    recs.append((f(r, "t"), err, math.hypot(txx - px, tyy - py), tyy, r))
t0 = recs[0][0]
settled = [abs(e) for t, e, *_ in recs if t - t0 > 3.0]
x0, y0 = f(rows[0], "px"), f(rows[0], "py")
drift = max(math.hypot(f(r, "px") - x0, f(r, "py") - y0) for r in rows)
print(json.dumps({k: summary[k] for k in ("end_reason", "tracking_fraction", "centered_fraction_while_tracking",
                                           "mean_abs_x_while_tracking", "stale_events", "z_after_landing")}))
keys = ("loop_hz", "rate_hz_requested", "latency_ms_requested", "applied_latency_ms", "sim_wall_ratio",
        "frames_processed", "frames_dropped", "torn_frames")
if any(k in summary for k in keys):
    # Achieved rate from the log itself, unrounded: N processed steps span N-1 intervals.
    # t_proc = when processing of each frame started (what the limiter controls); older logs: t.
    ts = np.array([f(r, "t_proc") if "t_proc" in r else f(r, "t") for r in rows])
    gaps = np.diff(ts)
    achieved = (len(ts) - 1) / (ts[-1] - ts[0]) if len(ts) > 1 and ts[-1] > ts[0] else 0.0
    req = summary.get("rate_hz_requested") or 0.0
    sim_ok = summary.get("sim_wall_ratio", 0) >= 0.8
    # A serial chip running at R Hz can reach at most R (frames arrive on a grid, so a bit
    # less); accept >= 0.9 R. It must also never start a frame sooner than 1/R after the last.
    rate_ok = not req or achieved >= 0.9 * req
    serial_ok = not req or (len(gaps) == 0 or gaps.min() >= 0.95 / req)
    ok = sim_ok and rate_ok and serial_ok
    rate_txt = (f"achieved {achieved:.2f} Hz ({achieved / req:.0%} of {req:g} Hz requested), "
                f"step gap min/median {gaps.min() * 1000:.0f}/{np.median(gaps) * 1000:.0f} ms"
                if req and len(gaps) else f"achieved {achieved:.2f} Hz (no rate cap)")
    print("run: " + json.dumps({k: summary[k] for k in keys if k in summary}))
    print(f"validity: {rate_txt} | sim/wall >= 0.8: {sim_ok}, rate >= 0.9x requested: {rate_ok}, "
          f"no gap < 1/rate: {serial_ok} | valid: {ok}")
if truth is not None:
    print(f"truth log: {len(truth)} samples, person y range {truth[:,3].min():+.2f} .. {truth[:,3].max():+.2f} m, "
          f"covers follower window: {truth[0,0] <= f(rows[0],'wall') and truth[-1,0] >= f(rows[-1],'wall')}")
if settled:
    print(f"ground truth bearing error after 3 s: mean {np.mean(settled):.1f} deg, 90th pct {np.percentile(settled, 90):.1f} deg, max {max(settled):.1f} deg")
print(f"distance to person: start {recs[0][2]:.2f} m, end {recs[-1][2]:.2f} m | max horizontal drift {drift:.2f} m")
if not brief:
    print(f"{'t':>5} {'conf':>5} {'trk':>3} {'x':>6} {'xs':>6} {'yawcmd':>6} | {'yaw':>6} | {'tgt_y':>5} {'b_err':>6}")
    last = -9
    for t, e, d, tyy, r in recs:
        if t - last < 2.0 and r is not rows[-1]: continue
        last = t
        print(f"{t:5.1f} {f(r,'conf'):5.2f} {int(f(r,'tracking')):3d} {f(r,'x'):+6.2f} {f(r,'x_soft'):+6.2f} "
              f"{f(r,'cmd_yaw'):+6.1f} | {f(r,'yaw'):+6.1f} | {tyy:+5.2f} {e:+6.1f}")
