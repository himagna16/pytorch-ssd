#!/usr/bin/env python3
"""Build the interleaved flight plan for the stability A/B.

Design goals, in the order they matter:

1. INTERLEAVE the two floor conditions so that machine drift (thermal, background
   load, memory pressure) lands on both arms equally instead of on whichever ran
   second.  The unit of interleaving is a *matched pair*: the same cell at the
   same repeat index is flown once matte and once mirrored, back to back, minutes
   apart.  Pairs are ABBA-counterbalanced -- pair 0 runs (matte, mirror), pair 1
   runs (mirror, matte), and so on -- so neither arm is systematically the
   "first, colder" flight of a pair.  ABBA cancels linear drift to first order,
   which strict MiMiMiMi alternation does not.

2. BREAK THE ORDER CONFOUND.  The first attempt saw upsets cluster on repeat 3,
   which in that suite was always the third flight of a cell.  Here the 28
   (cell, repeat) pairs are shuffled with a fixed seed before being expanded, so
   repeat index and chronological position are decorrelated by construction.
   The realised Spearman correlation is printed and belongs in the writeup.

   This matters because `follow_person.py` contains no RNG: for a clean-camera
   cell the repeat index changes *nothing* in the configuration (the sensor seed
   is only exported when camera != clean).  So for those cells "repeat 3" can
   only ever have meant "the third flight", and the confound is total.

Usage:  make_plan.py OUT.tsv [--repeats 4] [--seed 20260913]
"""
import argparse
import random

# cell_id, scene, class, backend, camera, speed, duration_s
# Copied verbatim from run_acceptance2.sh's CORE matrix (the five M7 cells plus
# the two "proven" cells that share their scenes).  Not imported, because that
# file is a tool this experiment measures and must not touch.
CELLS = [
    ("A.static__ships",         "s15_static_offset", "A", "chip",  "himax_typical", "chip", 45),
    ("B.moving__ships",         "s01_control_moving", "B", "chip",  "himax_typical", "chip", 50),
    ("B.moving__delta_backend", "s01_control_moving", "B", "chip",  "clean",         "full", 50),
    ("B.moving__delta_camera",  "s01_control_moving", "B", "float", "himax_typical", "full", 50),
    ("B.moving__delta_speed",   "s01_control_moving", "B", "float", "clean",         "chip", 50),
    ("A.static__proven",        "s15_static_offset", "A", "float", "clean",         "full", 45),
    ("B.moving__proven",        "s01_control_moving", "B", "float", "clean",         "full", 50),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--repeats", type=int, default=4)
    ap.add_argument("--seed", type=int, default=20260913)
    a = ap.parse_args()

    pairs = [(c, r) for c in CELLS for r in range(1, a.repeats + 1)]
    random.Random(a.seed).shuffle(pairs)

    rows, order = [], 0
    for i, (cell, rep) in enumerate(pairs):
        conds = ("matte", "mirror") if i % 2 == 0 else ("mirror", "matte")
        for cond in conds:
            order += 1
            cid, scene, cls, backend, camera, speed, dur = cell
            rows.append([order, cond, cid, scene, cls, backend, camera, speed, dur, rep, i + 1])

    with open(a.out, "w") as f:
        f.write("#order\tcond\tcell\tscene\tclass\tbackend\tcamera\tspeed\tduration\trepeat\tpair\n")
        for r in rows:
            f.write("\t".join(str(x) for x in r) + "\n")

    n = len(rows)
    print(f"{n} flights: {len(CELLS)} cells x 2 conditions x {a.repeats} repeats")
    for cond in ("matte", "mirror"):
        pos = [r[0] for r in rows if r[1] == cond]
        print(f"  {cond:7s} n={len(pos)}  mean chronological position {sum(pos)/len(pos):.1f}")

    # repeat index vs chronological position, Spearman (ranks are the values here)
    xs = [r[9] for r in rows]
    ys = [r[0] for r in rows]
    mx, my = sum(xs) / n, sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den = (sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys)) ** 0.5
    print(f"  corr(repeat index, chronological position) = {num/den:+.3f}  (want ~0)")
    print(f"  wrote {a.out}")


if __name__ == "__main__":
    main()
