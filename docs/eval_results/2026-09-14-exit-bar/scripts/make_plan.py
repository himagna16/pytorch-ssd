#!/usr/bin/env python
"""Build the interleaved exit-bar plan.

Round-robin by arm in the literal order 0.45, 0.55, 0.65, 0.45, ... so machine
state cannot favour one arm.  The REPEAT INDEX carried by each row is permuted
per arm so that repeat number is decorrelated from chronological position (the
seed is 1000+repeat, so this also decorrelates the camera noise draw from time).
Every arm sees the same set of seeds, i.e. matched camera noise.
"""
import json, sys

ARMS = ["0.45", "0.55", "0.65"]

# per-arm repeat orders (fixed, chosen so rank correlation with time is small)
PETS_REP = {"0.45": [3, 6, 1, 4, 2, 5],
            "0.55": [5, 2, 4, 6, 3, 1],
            "0.65": [1, 4, 6, 2, 5, 3]}
MOVE_REP = {"0.45": [2, 1], "0.55": [1, 2], "0.65": [2, 1]}

rows = []
o = 0
for blk in range(6):
    for arm in ARMS:
        o += 1
        rows.append((o, arm, "F.pets__ships", "s03_pets_only", "F",
                     "chip", "himax_typical", "chip", 35, PETS_REP[arm][blk], blk + 1))
pets_n = o
for blk in range(2):
    for arm in ARMS:
        o += 1
        rows.append((o, arm, "B.moving__ships", "s01_control_moving", "B",
                     "chip", "himax_typical", "chip", 50, MOVE_REP[arm][blk], blk + 1))

out = sys.argv[1]
with open(out, "w") as f:
    f.write("# order\tvis_exit\tcell\tscene\tclass\tbackend\tcamera\tspeed\tdur\trepeat\tblock\n")
    for r in rows:
        f.write("\t".join(str(x) for x in r) + "\n")

# realised balance
def spearman(a, b):
    n = len(a)
    def rank(v):
        s = sorted(range(n), key=lambda i: v[i]); r = [0]*n
        for k, i in enumerate(s): r[i] = k + 1
        return r
    ra, rb = rank(a), rank(b)
    ma, mb = sum(ra)/n, sum(rb)/n
    num = sum((ra[i]-ma)*(rb[i]-mb) for i in range(n))
    da = sum((x-ma)**2 for x in ra) ** .5
    db = sum((x-mb)**2 for x in rb) ** .5
    return num/(da*db) if da and db else 0.0

bal = {"pets": {}, "moving": {}}
for arm in ARMS:
    p = [(r[0], r[9]) for r in rows if r[1] == arm and r[2].startswith("F.pets")]
    m = [(r[0], r[9]) for r in rows if r[1] == arm and r[2].startswith("B.moving")]
    bal["pets"][arm] = {"orders": [x[0] for x in p], "repeats": [x[1] for x in p],
                        "seeds": [1000 + x[1] for x in p],
                        "mean_order": sum(x[0] for x in p)/len(p),
                        "spearman_order_vs_repeat": round(spearman([x[0] for x in p], [x[1] for x in p]), 4)}
    bal["moving"][arm] = {"orders": [x[0] for x in m], "repeats": [x[1] for x in m],
                          "seeds": [1000 + x[1] for x in m],
                          "mean_order": sum(x[0] for x in m)/len(m)}
bal["pets_flights"] = pets_n
bal["total_flights"] = o
json.dump(bal, open(sys.argv[2], "w"), indent=2)
print(json.dumps(bal, indent=2))
