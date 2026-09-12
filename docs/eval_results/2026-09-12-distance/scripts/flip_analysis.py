"""Where does the closed loop actually stop, and why?

The follower's law is vx = 0.8*(0.625 - size_value) with size_value quantised to
{0.125,0.375,0.625,0.875}. It closes at 0.2 m/s while the bucket is 1 and stops
DEAD the moment the bucket reads 2. So the parking distance is set entirely by
the distance at which the size head's 1->2 decision flips - nothing else.

A perfect size head flips at image-height fraction 0.500, i.e. 2.428 m for a
1.7 m subject. scoreboard.py's M7 gate targets 1.942 m (the bucket-2 CENTRE),
which this control law cannot reach even with a perfect head.

This measures the real flip point from the flight logs: P(bucket >= 2) against
true distance, pooled over each configuration's frames while tracking.
"""
import csv, math
from pathlib import Path
import numpy as np

SUITE = Path("/Users/saimaruvada/Downloads/drone/pytorch_ssd/docs/sim_results/2026-09-11-simv2/runs")
TAN = math.tan(math.radians(35.0))
H = 1.7
D_PERFECT = H / (2 * 0.5 * TAN)
D_TARGET = H / (2 * 0.625 * TAN)

def f(r, k):
    try:
        return float(r.get(k, ""))
    except Exception:
        return float("nan")

def load(run):
    rows = list(csv.DictReader(open(run / "follow_log.csv")))
    tr = []
    for line in open(run / "truth.csv"):
        if line.startswith("#"):
            continue
        p = line.strip().split(",")
        if len(p) >= 4:
            tr.append((float(p[0]), float(p[2]), float(p[3])))
    tr = np.array(tr)
    wall = np.array([f(r, "wall") for r in rows])
    px = np.array([f(r, "px") for r in rows]); py = np.array([f(r, "py") for r in rows])
    tx = np.interp(wall, tr[:, 0], tr[:, 1]); ty = np.interp(wall, tr[:, 0], tr[:, 2])
    d = np.hypot(tx - px, ty - py)
    out = dict(
        d=d,
        t=np.array([f(r, "t") for r in rows]),
        bkt=np.array([f(r, "size_bucket") for r in rows]),
        trk=np.array([f(r, "tracking") for r in rows]),
        vx=np.array([f(r, "cmd_vx") for r in rows]),
        conf=np.array([f(r, "conf") for r in rows]),
    )
    ok = np.isfinite(out["d"]) & np.isfinite(out["bkt"])
    return {k: v[ok] for k, v in out.items()}

CONFIGS = {
    "float/clean/full  (proven)":      ["A.static__proven__r1a1", "B.moving__proven__r1a1"],
    "float/clean/chipspeed":           ["B.moving__delta_speed__r1a1"],
    "float/himax/full":                ["B.moving__delta_camera__r1a1"],
    "chip/himax/chipspeed (ships-as)": ["A.static__ships__r1a1", "B.moving__ships__r1a1"],
}

print(f"control-law structural stop (perfect size head): {D_PERFECT:.3f} m")
print(f"scoreboard M7 target (bucket-2 centre)         : {D_TARGET:.3f} m   <- unreachable by this law")
print()

for name, runs in CONFIGS.items():
    D, B = [], []
    for r in runs:
        p = SUITE / r
        if not (p / "follow_log.csv").exists():
            continue
        s = load(p)
        sel = s["trk"] > 0
        D.append(s["d"][sel]); B.append(s["bkt"][sel])
    if not D:
        continue
    d = np.concatenate(D); b = np.concatenate(B)
    print(f"=== {name}   n_frames_tracking={d.size}  flights={len(D)} ===")
    print("   dist bin      n   P(bucket>=2)   mean bucket")
    xs, ps = [], []
    for lo in np.arange(1.8, 4.4, 0.2):
        hi = lo + 0.2
        sel = (d >= lo) & (d < hi)
        if sel.sum() >= 5:
            P = float(np.mean(b[sel] >= 2))
            print(f"   {lo:.1f}-{hi:.1f}  {sel.sum():6d}      {P:.3f}        {b[sel].mean():.2f}")
            xs.append(lo + 0.1); ps.append(P)
    xs, ps = np.array(xs), np.array(ps)
    cross = None
    for k in range(len(xs) - 1):
        if ps[k] >= 0.5 > ps[k + 1]:
            cross = xs[k] + (ps[k] - 0.5) * (xs[k + 1] - xs[k]) / (ps[k] - ps[k + 1])
    if cross:
        g = H / (2 * cross * TAN)
        print(f"   --> 50% flip distance {cross:.2f} m  (image-height fraction {g:.3f}; "
              f"nominal edge 0.500 -> boundary over-read {0.5/g:.3f}x)")
        print(f"   --> excess over the {D_PERFECT:.2f} m structural stop: {cross-D_PERFECT:+.2f} m")
    print()
