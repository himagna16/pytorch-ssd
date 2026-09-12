#!/usr/bin/env python3
"""Plain-English scorecard for one demo.sh flight.

Usage: demo_scorecard.py <run_dir> <scene> <person_x> <person_y> [--truth truth.csv]
scene: moving | static | empty | freeze. Reads run_dir/summary.json and
run_dir/follow_log.csv (written by follow_person.py). Heading error is the
angle between the drone's heading and the true direction to the person
(from the simulator's truth log when given), averaged after the first 3 s,
the same measure as analyze_follow.py. Prints the card and saves it to
run_dir/scorecard.txt.
"""
import csv, json, math, sys
from pathlib import Path
import numpy as np

a = sys.argv[1:]
run, scene, px0, py0 = Path(a[0]), a[1], float(a[2]), float(a[3])
truth = None
if "--truth" in a:
    p = Path(a[a.index("--truth") + 1])
    if p.exists() and p.stat().st_size > 0:
        truth = np.loadtxt(p, delimiter=",", ndmin=2)

if not (run / "summary.json").exists():
    sys.exit(f"No summary.json in {run}: the follower did not finish. See {run}/follower.log")
S = json.loads((run / "summary.json").read_text())
allrows = list(csv.DictReader(open(run / "follow_log.csv")))
steps = [r for r in allrows if r.get("event", "") == ""]
stale = [r for r in allrows if r.get("event") == "stale-hover"]


def f(r, k):
    try:
        return float(r[k])
    except (KeyError, ValueError, TypeError):
        return float("nan")


def target(r):
    if truth is None:
        return px0, py0
    w = f(r, "wall")
    return float(np.interp(w, truth[:, 0], truth[:, 2])), float(np.interp(w, truth[:, 0], truth[:, 3]))


errs, t_first = [], f(steps[0], "t") if steps else 0.0
for r in steps:
    tx, ty = target(r)
    e = (math.degrees(math.atan2(ty - f(r, "py"), tx - f(r, "px"))) - f(r, "yaw") + 180) % 360 - 180
    if f(r, "t") - t_first > 3.0 and not math.isnan(e):
        errs.append(abs(e))
x0, y0 = (f(steps[0], "px"), f(steps[0], "py")) if steps else (0, 0)
drift = max((math.hypot(f(r, "px") - x0, f(r, "py") - y0) for r in steps), default=0.0)
yaws = [f(r, "yaw") for r in steps if not math.isnan(f(r, "yaw"))]
turned = (max(yaws) - min(yaws)) if yaws else 0.0
tracked = 100.0 * S.get("tracking_fraction", 0.0)
z_land = S.get("z_after_landing")
landed = z_land is not None and z_land <= 0.10
end = S.get("end_reason", "?")
flight_s = (f(steps[-1], "t") - t_first) if steps else 0.0

L = []
title = {"moving": "Person swaying side to side (+-1.2 m)", "static": "Person standing 3.5 m out, 1 m to the right",
         "empty": "Empty room (person is behind the drone)", "freeze": "Camera freezes mid-flight"}[scene]
L.append("=" * 62)
L.append(f" SCORECARD  {title}")
L.append("=" * 62)
L.append(f" Person tracked:          {tracked:5.1f}% of camera frames ({S.get('control_steps', 0)} frames, {flight_s:.0f} s)")
if scene == "empty":
    L.append(f" Drone moved:             {drift * 100:5.1f} cm sideways, turned {turned:.1f} deg")
    peak = max((f(r, "conf") for r in steps), default=float("nan"))
    L.append(f" Highest person score:    {peak:5.2f} (needs 0.70 on 3 frames in a row to start)")
elif errs:
    L.append(f" Average heading error:   {np.mean(errs):5.1f} deg (worst {max(errs):.1f} deg) vs the person's true position")
if scene == "freeze":
    if stale:
        a0, a1 = f(stale[0], "frame_age"), f(stale[-1], "frame_age")
        L.append(f" Camera freeze:           hovered once the newest frame was {a0:.2f} s old,")
        L.append(f"                          landed when it was {max(a1, 3.0) if end == 'stale-land' else a1:.1f} s old")
    else:
        L.append(" Camera freeze:           no stale-frame hover recorded (unexpected)")
L.append(f" Landed OK:               {'yes' if landed else 'NO'} (height after landing {z_land if z_land is not None else '?'} m)")
why = {"duration": "flew the planned time, then landed on its own",
       "stale-land": "camera feed stopped -> hovered -> landed after 3 s (safety rule)"}.get(end, end)
L.append(f" How it ended:            {why}")
if scene in ("moving", "static"):
    ok = tracked >= 90 and errs and np.mean(errs) < 10 and landed and end == "duration"
elif scene == "empty":
    ok = tracked == 0 and drift < 0.10 and landed
else:
    ok = bool(stale) and end == "stale-land" and landed
L.append(f" Verdict:                 {'PASS' if ok else 'CHECK THIS RUN'}")
L.append("=" * 62)
txt = "\n".join(L)
print(txt)
(run / "scorecard.txt").write_text(txt + "\n")
sys.exit(0 if ok else 2)
