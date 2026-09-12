#!/usr/bin/env python3
"""EXPERIMENT 2 - the flight plan for the controlled F.pets__ships A/B.

One cell, two floors, four repeats, eight flights, one session.

Interleaving.  The two floors are flown as MATCHED PAIRS: the same repeat index
is flown matte and mirrored back to back, ~1 minute apart, so machine drift
lands on both arms equally.  That is the property the whole comparison rests on
and it is why this is an A/B rather than the baseline's before/after.

ABBA counterbalancing.  If the matte arm always led its pair it would always be
the colder first flight of the two.  The leading arm therefore alternates
A B B A over the four pairs, which puts both arms at mean chronological
position 4.5 of 8.

Repeat index decorrelated from order.  For this cell the repeat index is not
cosmetic - the camera is himax_typical, so CRAZYSIM_SENSOR_SEED = 1000 + repeat
really does change the sensor noise draw.  But repeats still arrive in pair
slots, so a naive 1,2,3,4 assignment would make "repeat 4" mean "flown last".
The repeats are assigned to pair slots in the order [3, 1, 4, 2], which is the
assignment whose correlation between repeat index and chronological position is
exactly zero (the four candidate sums -6,-2,+2,+6 cancel).  Chosen before any
flight, from the plan's own structure, using no outcome.

Usage: make_plan_ab.py OUT.tsv
"""
import sys
from pathlib import Path

CELL = "F.pets__ships"
SCENE = "s03_pets_only"
CLS, BACKEND, CAMERA, SPEED, DUR = "F", "chip", "himax_typical", "chip", 35

LEAD = ["matte", "mirror", "mirror", "matte"]      # ABBA over the four pairs
REPEATS = [3, 1, 4, 2]                             # zero order-repeat correlation


def build():
    plan = []
    order = 0
    for slot, (lead, rep) in enumerate(zip(LEAD, REPEATS)):
        second = "mirror" if lead == "matte" else "matte"
        for cond in (lead, second):
            order += 1
            plan.append((order, cond, CELL, SCENE, CLS, BACKEND, CAMERA, SPEED, DUR, rep))
    return plan


def main():
    out = Path(sys.argv[1])
    plan = build()
    lines = ["# order\tcondition\tcell\tscene\tclass\tbackend\tcamera\tspeed\tduration_s\trepeat"]
    for row in plan:
        lines.append("\t".join(str(v) for v in row))
    out.write_text("\n".join(lines) + "\n")

    print(f"wrote {out}  ({len(plan)} flights)")
    print()
    for o, cond, *_rest, rep in plan:
        print(f"  flight {o}  {cond:6s}  repeat {rep}")
    print()
    print("BALANCE CHECKS (properties of the plan, computed before any flight):")
    for cond in ("matte", "mirror"):
        pos = [o for o, c, *_ in plan if c == cond]
        print(f"  {cond:6s} flies at positions {pos}  mean {sum(pos) / len(pos):.1f} of {len(plan)}")
    reps = [r for *_h, r in plan]
    n = len(plan)
    mo, mr = (n + 1) / 2, sum(reps) / n
    cov = sum((o - mo) * (r - mr) for (o, *_x, r) in plan)
    vo = sum((o - mo) ** 2 for o in range(1, n + 1))
    vr = sum((r - mr) ** 2 for r in reps)
    print(f"  corr(order, repeat) = {cov / (vo * vr) ** 0.5:+.3f}")
    pairs = [(plan[i], plan[i + 1]) for i in range(0, n, 2)]
    ok = all(a[1] != b[1] and a[9] == b[9] for a, b in pairs)
    print(f"  every pair is one matte + one mirrored flight at the same repeat: {ok}")
    print(f"  leading arm per pair: {[a[1] for a, _ in pairs]}  (ABBA)")


if __name__ == "__main__":
    main()
