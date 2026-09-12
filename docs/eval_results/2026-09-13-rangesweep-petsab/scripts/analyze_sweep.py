#!/usr/bin/env python3
"""Analyse the EXPERIMENT 1 static range sweep.

Prints, per (subject x camera x backend):
  * confidence and the visibility decision binned by TRUE range
  * the same three bins the matte baseline's conf_vs_range.txt used, so the
    numbers are directly comparable to the within-flight association
  * decoded size bucket against range, and the measured bucket transitions
    against the ideal-head geometry d(s) = H / (2 s tan(phi/2))
  * backend disagreement, frame by frame (the two backends saw identical frames)

Usage: analyze_sweep.py SWEEP_DIR
"""
import collections
import csv
import json
import math
import statistics as st
import sys
from pathlib import Path

SWEEP = Path(sys.argv[1])
VIS_ENTER, VIS_EXIT = 0.70, 0.45
TAN_HALF = math.tan(math.radians(35.0))
BASELINE_BINS = [(2.5, 3.0), (2.0, 2.5), (1.5, 2.0)]

rows = list(csv.DictReader(open(SWEEP / "sweep.csv")))
for r in rows:
    r["range_m"] = float(r["range_m"])
    r["conf"] = float(r["conf"])
    r["above_enter"] = int(r["above_enter"])
    r["above_exit"] = int(r["above_exit"])
    r["size_bucket"] = int(r["size_bucket"])
    r["ideal_bucket"] = int(r["ideal_bucket"])
    r["ideal_size"] = float(r["ideal_size"])
    r["yaw_deg"] = float(r["yaw_deg"])
    r["clipped"] = int(r["clipped"])

meta = json.loads((SWEEP / "sweep_meta.json").read_text())
subjects = sorted({r["scene"] for r in rows})
cams = sorted({r["camera"] for r in rows})
bks = sorted({r["backend"] for r in rows})

out = []
def P(s=""):
    out.append(s)
    print(s)

P("=" * 78)
P("EXPERIMENT 1 - STATIC RANGE SWEEP")
P("=" * 78)
P(f"rows {len(rows)}   ranges {meta['ranges'][0]}..{meta['ranges'][-1]} m   "
  f"yaws {meta['yaws']}   cam heights {meta['heights']}   himax draws {meta['draws']}")
for s in subjects:
    m = meta["scenes"][s]
    P(f"  {s}: {m['subject']} h={m['height_m']} m  COCO img {m['coco']['img_id']}/"
      f"ann {m['coco']['ann_id']}  floor_reflectance {m['floor_reflectance']:g}")
P(f"vis_enter {VIS_ENTER}  vis_exit {VIS_EXIT}   (follow_person.py defaults; the latch "
  f"also needs {3} consecutive frames)")
P("Nothing here flew. No simulator, no firmware, no control loop.")
P()

# ---------------------------------------------------------------- per-range
for s in subjects:
    for cam in cams:
        for b in bks:
            sel = [r for r in rows if r["scene"] == s and r["camera"] == cam
                   and r["backend"] == b]
            if not sel:
                continue
            P("-" * 78)
            P(f"{s}  camera={cam}  backend={b}   (n={len(sel)})")
            P(f"{'range':>6} {'n':>4} {'mean':>6} {'med':>6} {'min':>6} {'p10':>6} "
              f"{'>=0.70':>7} {'>=0.45':>7} {'ideal_s':>8} {'bucket(mode)':>13} {'ideal_b':>7} clip")
            for d in meta["ranges"]:
                g = [r for r in sel if abs(r["range_m"] - d) < 1e-6]
                if not g:
                    continue
                c = sorted(r["conf"] for r in g)
                bk = collections.Counter(r["size_bucket"] for r in g)
                mode = bk.most_common(1)[0]
                P(f"{d:6.2f} {len(g):4d} {st.mean(c):6.3f} {st.median(c):6.3f} "
                  f"{c[0]:6.3f} {c[max(0, int(0.10 * len(c)) - 1)]:6.3f} "
                  f"{100 * sum(r['above_enter'] for r in g) / len(g):6.1f}% "
                  f"{100 * sum(r['above_exit'] for r in g) / len(g):6.1f}% "
                  f"{g[0]['ideal_size']:8.3f} "
                  f"{mode[0]:>6d} ({100 * mode[1] / len(g):3.0f}%) {g[0]['ideal_bucket']:7d} "
                  f"{'CLIP' if g[0]['clipped'] else ''}")
            # the baseline's own bins
            P("  matte-baseline bins (conf_vs_range.txt used these):")
            for lo, hi in BASELINE_BINS:
                g = [r for r in sel if lo <= r["range_m"] < hi]
                if g:
                    P(f"    range {lo}-{hi} m   n={len(g):4d}  mean conf {st.mean([r['conf'] for r in g]):.3f}"
                      f"   {100 * sum(r['above_enter'] for r in g) / len(g):5.1f}% of frames >= 0.70")
            # monotonicity: is close worse than far?
            near = [r["conf"] for r in sel if r["range_m"] <= 2.0]
            far = [r["conf"] for r in sel if 2.5 <= r["range_m"] <= 3.0]
            if near and far:
                P(f"  near (<=2.0 m) mean {st.mean(near):.3f} vs far (2.5-3.0 m) mean "
                  f"{st.mean(far):.3f}   delta {st.mean(near) - st.mean(far):+.3f}")
            P()

# ----------------------------------------------------- bucket transitions
P("=" * 78)
P("SIZE BUCKET TRANSITIONS AGAINST RANGE")
P("=" * 78)
P("ideal-head geometry, scoreboard.py's own d(s) = H / (2 s tan(phi/2)):")
for s in subjects:
    h = meta["scenes"][s]["height_m"]
    P(f"  {s} (H={h} m): bucket 0/1 at {h / (2 * 0.25 * TAN_HALF):.3f} m, "
      f"1/2 at {h / (2 * 0.50 * TAN_HALF):.3f} m, 2/3 at {h / (2 * 0.75 * TAN_HALF):.3f} m")
P()
for s in subjects:
    for cam in cams:
        for b in bks:
            sel = [r for r in rows if r["scene"] == s and r["camera"] == cam
                   and r["backend"] == b]
            if not sel:
                continue
            line, prev = [], None
            for d in meta["ranges"]:
                g = [r for r in sel if abs(r["range_m"] - d) < 1e-6]
                if not g:
                    continue
                mode = collections.Counter(r["size_bucket"] for r in g).most_common(1)[0][0]
                if prev is not None and mode != prev:
                    line.append(f"{prev}->{mode} between {d - 0.25:.2f} and {d:.2f} m")
                prev = mode
            agree = sum(r["size_bucket"] == r["ideal_bucket"] for r in sel) / len(sel)
            P(f"{s:22s} {cam:14s} {b:6s}  {' | '.join(line) if line else 'no transition'}"
              f"   (matches ideal bucket on {100 * agree:.1f}% of frames)")
P()

# ------------------------------------------------------ backend agreement
P("=" * 78)
P("BACKEND DISAGREEMENT  (both backends saw byte-identical frames)")
P("=" * 78)
idx = collections.defaultdict(dict)
for r in rows:
    k = (r["scene"], r["camera"], r["range_m"], r["yaw_deg"], r["cam_h_m"], r["draw"])
    idx[k][r["backend"]] = r
P(f"{'subject':22s} {'camera':14s} {'n':>5} {'mean|dconf|':>11} {'max|dconf|':>10} "
  f"{'latch disagree':>14} {'bucket disagree':>15}")
for s in subjects:
    for cam in cams:
        pairs = [v for k, v in idx.items() if k[0] == s and k[1] == cam
                 and "float" in v and "chip" in v]
        if not pairs:
            continue
        dc = [abs(v["float"]["conf"] - v["chip"]["conf"]) for v in pairs]
        ld = sum(v["float"]["above_enter"] != v["chip"]["above_enter"] for v in pairs)
        bd = sum(v["float"]["size_bucket"] != v["chip"]["size_bucket"] for v in pairs)
        P(f"{s:22s} {cam:14s} {len(pairs):5d} {st.mean(dc):11.4f} {max(dc):10.4f} "
          f"{ld:6d} ({100 * ld / len(pairs):4.1f}%) {bd:6d} ({100 * bd / len(pairs):4.1f}%)")
P()
P("Per-range latch disagreement (float says >=0.70, chip does not, or the reverse):")
for s in subjects:
    for cam in cams:
        row = []
        for d in meta["ranges"]:
            pairs = [v for k, v in idx.items() if k[0] == s and k[1] == cam
                     and abs(k[2] - d) < 1e-6 and "float" in v and "chip" in v]
            if pairs:
                ld = sum(v["float"]["above_enter"] != v["chip"]["above_enter"] for v in pairs)
                row.append(f"{d:.2f}:{ld}/{len(pairs)}")
        P(f"  {s:22s} {cam:14s} " + "  ".join(row))
P()

# ----------------------------------------------------------- yaw effect
P("=" * 78)
P("YAW OFFSET (range held fixed; yaw only moves the subject across the frame)")
P("=" * 78)
for s in subjects:
    for cam in cams:
        for b in bks:
            sel = [r for r in rows if r["scene"] == s and r["camera"] == cam and r["backend"] == b]
            if not sel:
                continue
            parts = []
            for y in meta["yaws"]:
                g = [r for r in sel if abs(r["yaw_deg"] - y) < 1e-6]
                if g:
                    parts.append(f"{y:+.0f}d {st.mean([r['conf'] for r in g]):.3f}"
                                 f"/{100 * sum(r['above_enter'] for r in g) / len(g):.0f}%")
            P(f"{s:22s} {cam:14s} {b:6s}  " + "  ".join(parts))
P()
P("(each cell is mean conf / % of frames >= 0.70, pooled over all ranges)")

(SWEEP.parent / "sweep_analysis.txt").write_text("\n".join(out) + "\n")
print(f"\nwrote {SWEEP.parent / 'sweep_analysis.txt'}")
