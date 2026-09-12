#!/usr/bin/env python3
"""Analyse the EXPERIMENT 1 control replay: partition in frame vs not.

Both variants are rendered from the SAME replayed pose, so the pairing removes
every source of pose-replay error.  Anything that differs between the columns is
the partition geom and nothing else.

Usage: analyze_replay.py REPLAY_DIR
"""
import collections
import csv
import statistics as st
import sys
from pathlib import Path

D = Path(sys.argv[1])
rows = list(csv.DictReader(open(D / "replay.csv")))
for r in rows:
    for k in ("t", "px", "py", "range_m", "conf", "flown_conf", "x_value", "flown_x"):
        r[k] = float(r[k])
    for k in ("flown_tracking", "size_bucket", "flown_size_bucket", "sightline_clear"):
        r[k] = int(r[k])

out = []
def P(s=""):
    out.append(s)
    print(s)

pair = collections.defaultdict(dict)
for r in rows:
    pair[(r["run"], r["t"])][r["variant"]] = r
pairs = [v for v in pair.values() if len(v) == 2]

P("=" * 78)
P("EXPERIMENT 1, CONTROL REPLAY - is it the partition in frame, or the range?")
P("=" * 78)
P(f"{len(pairs)} replayed frames from {len(set(r['run'] for r in rows))} "
  f"D.occlusion__proven matte flights, each rendered twice (partition present / absent)")
P("Backend float, camera clean - exactly what __proven flies. Nothing flew here.")
P()

# ---- fidelity of the replay against the flight it is replaying
wp = [v["with_partition"] for v in pairs]
dx = [abs(v["x_value"] - v["flown_x"]) for v in wp]
dc = [abs(v["conf"] - v["flown_conf"]) for v in wp]
same_latch = sum((v["conf"] >= 0.70) == (v["flown_conf"] >= 0.70) for v in wp)
P("Replay fidelity (with_partition vs the flown log, frame by frame):")
P(f"  decoded x bin identical on {100 * sum(d < 1e-9 for d in dx) / len(dx):.1f}% of frames; "
  f"mean |dx| {st.mean(dx):.4f} (one bin is 0.222 wide)")
P(f"  |d conf|  mean {st.mean(dc):.4f}  median {st.median(dc):.4f}  p90 "
  f"{sorted(dc)[int(0.9 * len(dc))]:.4f}")
P(f"  the >=0.70 decision agrees with the flight on {100 * same_latch / len(wp):.1f}% of frames")
P("  (residual is state-estimate error and the camera's 0.03 m body offset; the")
P("   with/without comparison below is PAIRED on the same pose, so none of it leaks in)")
P()

# ---- the headline: paired comparison
P("-" * 78)
P("PAIRED: same pose, partition present vs absent")
P("-" * 78)
P(f"{'range bin':>14} {'n':>5} {'with part.':>11} {'no part.':>10} {'delta':>8} "
  f"{'>=0.70 with':>12} {'>=0.70 without':>15}")
bins = [(0.0, 1.5), (1.5, 2.0), (2.0, 2.5), (2.5, 3.0), (3.0, 3.5), (3.5, 99)]
for lo, hi in bins:
    g = [v for v in pairs if lo <= v["with_partition"]["range_m"] < hi]
    if not g:
        continue
    a = st.mean([v["with_partition"]["conf"] for v in g])
    b = st.mean([v["no_partition"]["conf"] for v in g])
    ea = 100 * sum(v["with_partition"]["conf"] >= 0.70 for v in g) / len(g)
    eb = 100 * sum(v["no_partition"]["conf"] >= 0.70 for v in g) / len(g)
    lbl = f"{lo:.1f}-{hi:.1f} m" if hi < 90 else f">={lo:.1f} m"
    P(f"{lbl:>14} {len(g):5d} {a:11.3f} {b:10.3f} {b - a:+8.3f} {ea:11.1f}% {eb:14.1f}%")
alla = st.mean([v["with_partition"]["conf"] for v in pairs])
allb = st.mean([v["no_partition"]["conf"] for v in pairs])
P(f"{'ALL':>14} {len(pairs):5d} {alla:11.3f} {allb:10.3f} {allb - alla:+8.3f} "
  f"{100 * sum(v['with_partition']['conf'] >= 0.70 for v in pairs) / len(pairs):11.1f}% "
  f"{100 * sum(v['no_partition']['conf'] >= 0.70 for v in pairs) / len(pairs):14.1f}%")
P()

# ---- restricted to the frames the flight actually lost
lost = [v for v in pairs if v["with_partition"]["flown_tracking"] == 0]
held = [v for v in pairs if v["with_partition"]["flown_tracking"] == 1]
P("-" * 78)
P("THE FRAMES THE FLIGHT ACTUALLY LOST THE TRACK ON")
P("-" * 78)
for name, g in (("lost-track frames", lost), ("tracked frames", held)):
    if not g:
        continue
    a = [v["with_partition"]["conf"] for v in g]
    b = [v["no_partition"]["conf"] for v in g]
    clear = sum(v["with_partition"]["sightline_clear"] for v in g)
    P(f"{name}: n={len(g)}  sight line clear on {100 * clear / len(g):.1f}%")
    P(f"   flown conf          mean {st.mean([v['with_partition']['flown_conf'] for v in g]):.3f}"
      f"   >=0.70 on {100 * sum(v['with_partition']['flown_conf'] >= 0.70 for v in g) / len(g):.1f}%")
    P(f"   replay WITH  part.  mean {st.mean(a):.3f}   >=0.70 on "
      f"{100 * sum(c >= 0.70 for c in a) / len(g):.1f}%")
    P(f"   replay WITHOUT part. mean {st.mean(b):.3f}   >=0.70 on "
      f"{100 * sum(c >= 0.70 for c in b) / len(g):.1f}%")
    P(f"   paired delta (without - with) mean {st.mean([y - x for x, y in zip(a, b)]):+.3f}")
    P()

# ---- per flight
P("-" * 78)
P("PER FLIGHT")
P("-" * 78)
P(f"{'run':>30} {'n':>5} {'with':>7} {'without':>8} {'d':>7} {'lost n':>7} "
  f"{'lost:with':>10} {'lost:without':>13}")
for run in sorted(set(r["run"] for r in rows)):
    g = [v for v in pairs if v["with_partition"]["run"] == run]
    lg = [v for v in g if v["with_partition"]["flown_tracking"] == 0]
    a = st.mean([v["with_partition"]["conf"] for v in g])
    b = st.mean([v["no_partition"]["conf"] for v in g])
    la = st.mean([v["with_partition"]["conf"] for v in lg]) if lg else float("nan")
    lb = st.mean([v["no_partition"]["conf"] for v in lg]) if lg else float("nan")
    P(f"{run:>30} {len(g):5d} {a:7.3f} {b:8.3f} {b - a:+7.3f} {len(lg):7d} "
      f"{la:10.3f} {lb:13.3f}")
P()

# ---- how much of the frame the partition covers, by px
P("-" * 78)
P("WHY: how close the drone gets to the partition")
P("-" * 78)
P("partition face is at x = 2.15 m (box centre 2.2, half-extent 0.05).")
P(f"{'run':>30} {'px max':>7} {'gap to face':>12} {'min range':>10}")
for run in sorted(set(r["run"] for r in rows)):
    g = [v["with_partition"] for v in pairs if v["with_partition"]["run"] == run]
    pxm = max(v["px"] for v in g)
    P(f"{run:>30} {pxm:7.3f} {2.15 - pxm:12.3f} {min(v['range_m'] for v in g):10.3f}")
P()
P("Frames where the drone is within 0.5 m of the partition face:")
near = [v for v in pairs if v["with_partition"]["px"] > 1.65]
if near:
    a = st.mean([v["with_partition"]["conf"] for v in near])
    b = st.mean([v["no_partition"]["conf"] for v in near])
    P(f"  n={len(near)}   with {a:.3f} (>=0.70 on "
      f"{100 * sum(v['with_partition']['conf'] >= 0.70 for v in near) / len(near):.1f}%)"
      f"   without {b:.3f} (>=0.70 on "
      f"{100 * sum(v['no_partition']['conf'] >= 0.70 for v in near) / len(near):.1f}%)"
      f"   delta {b - a:+.3f}")

(D.parent / "replay_analysis.txt").write_text("\n".join(out) + "\n")
print(f"\nwrote {D.parent / 'replay_analysis.txt'}")
