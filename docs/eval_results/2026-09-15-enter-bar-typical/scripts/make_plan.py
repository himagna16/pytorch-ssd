#!/usr/bin/env python3
"""Build the interleaved enter-bar flight plan.

Two arms, --vis-enter 0.70 and 0.75, everything else at the shipped defaults
(--vis-exit 0.45, --confirm-frames 3).  The arms are interleaved FLIGHT BY
FLIGHT and which arm goes first alternates, so neither arm is systematically
early or late and machine state cannot favour one.  The cell order rotates each
repeat for the same reason.

The sensor seed is the harness's own 1000 + repeat, which depends only on the
repeat index, so THE TWO ARMS OF A REPEAT SEE THE SAME HIMAX NOISE DRAW.  That
makes each (cell, repeat) a paired comparison in which the only difference is
the number on the entry gate.

Usage: make_plan.py BLOCK OUT.tsv      (BLOCK is 1 = typical person, 2 = control)
"""
import sys

TYPICAL = [("A.static__median", "tp15_static_median", "A", 45),
           ("A.static__p25",    "tp15_static_p25",    "A", 45),
           ("B.moving__median", "tp01_moving_median", "B", 50),
           ("B.moving__p25",    "tp01_moving_p25",    "B", 50)]
CONTROL = [("A.static__control", "s15_static_offset",  "A", 45),
           ("B.moving__control", "s01_control_moving", "B", 50)]
ARMS = ["0.70", "0.75"]
REPEATS = 3

block = int(sys.argv[1])
cells = TYPICAL if block == 1 else CONTROL
rows, ordn, pair = [], 0, 0
for rep in range(1, REPEATS + 1):
    rot = cells[(rep - 1) % len(cells):] + cells[:(rep - 1) % len(cells)]
    for cid, scene, cls, dur in rot:
        arms = ARMS if pair % 2 == 0 else ARMS[::-1]
        pair += 1
        for a in arms:
            ordn += 1
            rows.append((ordn, a, cid, scene, cls, "chip", "himax_typical",
                         "chip", dur, rep, block))

with open(sys.argv[2], "w") as f:
    f.write("# order\tvis_enter\tcell\tscene\tclass\tbackend\tcamera\tspeed\tdur\trepeat\tblock\n")
    for r in rows:
        f.write("\t".join(str(x) for x in r) + "\n")
print(f"block {block}: {len(rows)} flights")
for r in rows:
    print("\t".join(str(x) for x in r))
