#!/usr/bin/env python3
"""Build the flight plan for the matte-floor completion suite.

The seven cells here are the ones the Sep 13 stability A/B did NOT fly, so they
still have no clean (matte-floor) data.  Only one condition is flown -- matte --
because the mirrored numbers already exist in docs/sim_results/2026-09-11-simv2/
and re-flying them would not be comparable anyway (that suite ran 2 repeats on a
different day and a different machine state).

Design carried over from the stability run:

  BREAK THE ORDER CONFOUND.  Three of these seven cells are clean-camera cells
  (C/D/E __proven), and follow_person.py has no RNG: the repeat index reaches
  the simulator only through CRAZYSIM_SENSOR_SEED, which is exported only when
  camera != clean.  So for those cells repeat 1..4 are configuration-identical
  and "repeat 3" could only ever mean "the third flight in time".  The 28
  (cell, repeat) pairs are therefore shuffled with a fixed seed so that repeat
  index and chronological position are decorrelated by construction.  The
  realised Spearman correlation is printed and belongs in the writeup.

Usage:  make_plan.py OUT.tsv [--repeats 4] [--seed 20260913]
"""
import argparse
import random

# cell_id, scene, class, backend, camera, speed, duration_s
# Copied verbatim from run_acceptance2.sh's CORE matrix (the seven cells the
# stability run did not cover).  Not imported: that file is a tool under
# measurement and must not be touched.
CELLS = [
    ("C.empty__ships",      "s02_control_empty",      "C", "chip",  "himax_typical", "chip", 35),
    ("D.occlusion__ships",  "s07_occlusion_reappear", "D", "chip",  "himax_typical", "chip", 60),
    ("E.furniture__ships",  "s16_furniture_only",     "E", "chip",  "himax_typical", "chip", 35),
    ("F.pets__ships",       "s03_pets_only",          "F", "chip",  "himax_typical", "chip", 35),
    ("C.empty__proven",     "s02_control_empty",      "C", "float", "clean",         "full", 35),
    ("D.occlusion__proven", "s07_occlusion_reappear", "D", "float", "clean",         "full", 60),
    ("E.furniture__proven", "s16_furniture_only",     "E", "float", "clean",         "full", 35),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--repeats", type=int, default=4)
    ap.add_argument("--seed", type=int, default=20297947)
    a = ap.parse_args()

    pairs = [(c, r) for c in CELLS for r in range(1, a.repeats + 1)]
    random.Random(a.seed).shuffle(pairs)

    rows = []
    for i, (cell, rep) in enumerate(pairs):
        cid, scene, cls, backend, camera, speed, dur = cell
        rows.append((i + 1, cid, scene, cls, backend, camera, speed, dur, rep))

    with open(a.out, "w") as f:
        f.write("# order\tcell\tscene\tclass\tbackend\tcamera\tspeed\tduration_s\trepeat\n")
        for r in rows:
            f.write("\t".join(str(x) for x in r) + "\n")

    # ---- balance checks, printed for the writeup -------------------------
    print(f"wrote {len(rows)} flights to {a.out}")

    def spearman(xs, ys):
        def rank(v):
            s = sorted(range(len(v)), key=lambda i: v[i])
            r = [0.0] * len(v)
            for pos, i in enumerate(s):
                r[i] = pos + 1.0
            return r
        rx, ry = rank(xs), rank(ys)
        n = len(xs)
        mx, my = sum(rx) / n, sum(ry) / n
        num = sum((rx[i] - mx) * (ry[i] - my) for i in range(n))
        dx = sum((rx[i] - mx) ** 2 for i in range(n)) ** 0.5
        dy = sum((ry[i] - my) ** 2 for i in range(n)) ** 0.5
        return num / (dx * dy) if dx and dy else 0.0

    orders = [r[0] for r in rows]
    reps = [r[8] for r in rows]
    print(f"spearman(order, repeat) = {spearman(orders, reps):+.3f}  (want ~0)")
    for rep in sorted(set(reps)):
        pos = [o for o, rr in zip(orders, reps) if rr == rep]
        print(f"  repeat {rep}: mean chronological position {sum(pos)/len(pos):5.1f} of {len(rows)}")
    for cid in sorted({r[1] for r in rows}):
        pos = [r[0] for r in rows if r[1] == cid]
        print(f"  {cid:<22} positions {sorted(pos)}")
    print(f"total flight seconds (excl. sim startup): {sum(r[7] for r in rows)}")


if __name__ == "__main__":
    main()
