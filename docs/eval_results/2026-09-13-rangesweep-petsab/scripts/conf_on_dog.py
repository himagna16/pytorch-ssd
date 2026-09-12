#!/usr/bin/env python3
"""EXPERIMENT 2 - attribute the confidence to the dog rather than to the scene.

The network has one visibility output for the whole frame, so a raw `conf`
column is "confidence that a person is in this picture", not "confidence on the
dog".  `s03_pets_only` holds two distractors - a 0.65 m dog at (2.6, -0.8) and a
0.4 m cat at (2.2, 0.9) - so a frame can contain either, both or neither.

This splits the flown frames by WHICH subject was inside the model's crop.  The
crop is the centre square of the 324x244 render, i.e. +-35 deg about the
camera's axis (scoreboard.py's MODEL_HALF_FOV_DEG), and the camera axis is the
drone's yaw.  Subject positions come from the simulator's own truth log, joined
to the follower's rows on the WALL CLOCK both files carry.

No rendering, no inference, no simulator: the confidences are the ones the
follower logged.

Usage: conf_on_dog.py OUT_DIR
"""
import bisect
import csv
import json
import math
import statistics as st
import sys
from pathlib import Path

OUT = Path(sys.argv[1])
HALF_FOV = 35.0

out = []
def P(s=""):
    out.append(s)
    print(s)


def load_truth(path):
    """truth.csv: '# bodies: a, b', then wall_ts, sim_t, then x,y,z per body."""
    lines = path.read_text().splitlines()
    names = [n.strip() for n in lines[0].split(":", 1)[1].split(",")]
    ts, pos = [], {n: [] for n in names}
    for line in lines[1:]:
        if not line.strip() or line.startswith("#"):
            continue
        f = [float(v) for v in line.split(",")]
        ts.append(f[0])
        for i, n in enumerate(names):
            pos[n].append((f[2 + 3 * i], f[3 + 3 * i]))
    return names, ts, pos


def at(ts, series, w):
    i = bisect.bisect_left(ts, w)
    if i <= 0:
        return series[0]
    if i >= len(ts):
        return series[-1]
    t0, t1 = ts[i - 1], ts[i]
    f = 0.0 if t1 == t0 else (w - t0) / (t1 - t0)
    a, b = series[i - 1], series[i]
    return (a[0] + f * (b[0] - a[0]), a[1] + f * (b[1] - a[1]))


def bearing(px, py, yaw_deg, tx, ty):
    b = math.degrees(math.atan2(ty - py, tx - px)) - yaw_deg
    while b > 180:
        b -= 360
    while b < -180:
        b += 360
    return b


def main():
    flights = [json.loads(l) for l in (OUT / "flights.jsonl").read_text().splitlines() if l.strip()]
    flights = [f for f in flights if f["verdict"] == "VALID"]
    per_arm = {"matte": {}, "mirror": {}}
    rows_out = []

    for f in flights:
        run = Path(f["run_dir"])
        arm = "mirror" if float((run / "floor_reflectance.txt").read_text().strip()) > 0 else "matte"
        names, ts, pos = load_truth(run / "truth.csv")
        dog = next(n for n in names if "dog" in n)
        cat = next(n for n in names if "cat" in n)
        buckets = {"dog only": [], "cat only": [], "both": [], "neither": []}
        for r in csv.DictReader(open(run / "follow_log.csv")):
            if r["event"] != "":
                continue
            try:
                px, py, yaw = float(r["px"]), float(r["py"]), float(r["yaw"])
                w, c = float(r["wall"]), float(r["conf"])
            except (ValueError, KeyError):
                continue
            dx, dy = at(ts, pos[dog], w)
            cx, cy = at(ts, pos[cat], w)
            din = abs(bearing(px, py, yaw, dx, dy)) <= HALF_FOV
            cin = abs(bearing(px, py, yaw, cx, cy)) <= HALF_FOV
            key = ("both" if din and cin else "dog only" if din
                   else "cat only" if cin else "neither")
            rng = math.hypot(dx - px, dy - py)
            buckets[key].append((c, rng, int(r["size_bucket"])))
        rows_out.append((f["order"], arm, run.name, buckets))
        for k, v in buckets.items():
            per_arm[arm].setdefault(k, []).extend(v)

    P("=" * 92)
    P("EXPERIMENT 2 - CONFIDENCE ATTRIBUTED TO WHAT WAS ACTUALLY IN THE MODEL'S CROP")
    P("=" * 92)
    P("The model emits one visibility output per frame, so frames are split by which")
    P(f"subject lay within +-{HALF_FOV:.0f} deg of the camera axis (the square centre crop).")
    P("Subject positions come from the simulator's truth log, joined on the wall clock.")
    P()
    P(f"{'arm':>7} {'in crop':>10} {'frames':>7} {'mean':>6} {'med':>6} {'p90':>6} {'max':>6} "
      f"{'>=0.70':>7} {'>=0.45':>7} {'mean range to dog':>18}")
    for arm in ("matte", "mirror"):
        for k in ("dog only", "both", "cat only", "neither"):
            v = per_arm[arm].get(k, [])
            if not v:
                P(f"{arm:>7} {k:>10} {0:7d}")
                continue
            c = sorted(x[0] for x in v)
            P(f"{arm:>7} {k:>10} {len(v):7d} {st.mean(c):6.3f} {st.median(c):6.3f} "
              f"{c[min(len(c) - 1, int(0.9 * len(c)))]:6.3f} {c[-1]:6.3f} "
              f"{100 * sum(x >= 0.70 for x in c) / len(c):6.1f}% "
              f"{100 * sum(x >= 0.45 for x in c) / len(c):6.1f}% "
              f"{st.mean([x[1] for x in v]):18.2f}")
    P()
    P("THE DOG ALONE, per flight (frames where the dog was in the crop and the cat was not)")
    P(f"{'ord':>4} {'arm':>7} {'run':>34} {'frames':>7} {'mean':>6} {'med':>6} {'max':>6} {'>=0.70':>7}")
    for order, arm, name, b in sorted(rows_out):
        v = b["dog only"]
        if not v:
            P(f"{order:4d} {arm:>7} {name:>34} {0:7d}")
            continue
        c = [x[0] for x in v]
        P(f"{order:4d} {arm:>7} {name:>34} {len(v):7d} {st.mean(c):6.3f} {st.median(c):6.3f} "
          f"{max(c):6.3f} {100 * sum(x >= 0.70 for x in c) / len(c):6.1f}%")
    P()
    P("Size bucket the head assigned while the dog alone was in the crop:")
    for arm in ("matte", "mirror"):
        v = per_arm[arm].get("dog only", [])
        if not v:
            continue
        bc = {}
        for _, _, b in v:
            bc[b] = bc.get(b, 0) + 1
        P(f"  {arm:6s}  " + "  ".join(f"bucket {b}: {n} ({100 * n / len(v):.1f}%)"
                                      for b, n in sorted(bc.items())))
    P()
    P("RANGE-MATCHED. The mirrored drone CLOSES on the dog, so its dog-only frames are")
    P("taken from much nearer (mean 1.00 m vs 2.18 m) and part of its higher confidence")
    P("is simply that it is closer. Binning the dog-only frames by true range to the dog")
    P("removes that, and leaves only what the floor did:")
    P(f"{'range to dog':>14} {'matte n':>8} {'matte mean':>11} {'matte >=.70':>12} "
      f"{'mirror n':>9} {'mirror mean':>12} {'mirror >=.70':>13} {'delta mean':>11}")
    for lo, hi in ((0.0, 1.0), (1.0, 1.5), (1.5, 2.0), (2.0, 2.5), (2.5, 3.0)):
        cells = {}
        for arm in ("matte", "mirror"):
            v = [x for x in per_arm[arm].get("dog only", []) if lo <= x[1] < hi]
            cells[arm] = v
        if len(cells["matte"]) < 10 and len(cells["mirror"]) < 10:
            continue
        def f(v):
            if len(v) < 10:
                return (len(v), float("nan"), float("nan"))
            c = [x[0] for x in v]
            return (len(v), st.mean(c), 100 * sum(x >= 0.70 for x in c) / len(c))
        na, ma, pa = f(cells["matte"])
        nb, mb, pb = f(cells["mirror"])
        P(f"{lo:6.1f}-{hi:4.1f} m {na:8d} {ma:11.3f} {pa:11.1f}% "
          f"{nb:9d} {mb:12.3f} {pb:12.1f}% {mb - ma:11.3f}")
    ov = [(lo, hi) for lo, hi in ((1.5, 2.0), (2.0, 2.5), (2.5, 3.0))]
    poola = [x for lo, hi in ov for x in per_arm["matte"].get("dog only", []) if lo <= x[1] < hi]
    poolb = [x for lo, hi in ov for x in per_arm["mirror"].get("dog only", []) if lo <= x[1] < hi]
    if len(poola) >= 10 and len(poolb) >= 10:
        ca = [x[0] for x in poola]
        cb = [x[0] for x in poolb]
        P(f"  pooled over the 1.5-3.0 m band both arms actually visit: "
          f"matte n={len(ca)} mean {st.mean(ca):.3f} ({100 * sum(x >= 0.70 for x in ca) / len(ca):.1f}% >= 0.70)"
          f"   mirror n={len(cb)} mean {st.mean(cb):.3f} "
          f"({100 * sum(x >= 0.70 for x in cb) / len(cb):.1f}% >= 0.70)")
    P()
    P("A 0.65 m dog at ~2.5 m should read bucket 0 on the ideal head")
    P("(d(s) = H / (2 s tan(phi/2)) puts 0.65 m at bucket 0/1 only inside 1.86 m).")
    P("Bucket 1 and above means the head is reading it as a taller object than it is.")

    (OUT / "dog_confidence.txt").write_text("\n".join(out) + "\n")
    print(f"\nwrote {OUT / 'dog_confidence.txt'}")


if __name__ == "__main__":
    main()
