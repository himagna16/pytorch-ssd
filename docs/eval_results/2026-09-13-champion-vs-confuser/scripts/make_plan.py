#!/usr/bin/env python
"""Build the interleaved champion-vs-confuser flight plan.

THE DESIGN, and why each piece is there
---------------------------------------
6 chip ("ships-as") cells x 2 models x 4 repeats = 48 flights, ONE session.

* MATCHED PAIRS.  The same (cell, repeat) is flown by BOTH models back to back,
  ~1-2 min apart.  Machine drift, thermal state and background load therefore
  land on both arms of every comparison equally.  This is the property the
  pets A/B run (2026-09-13-rangesweep-petsab) established as the fix for a
  before/after comparison, reused here.

* ABBA COUNTERBALANCING.  Within a pair one model must go first, and going
  first is not free: the simulator has just been torn down and rebuilt.  The
  first slot alternates ABBA over consecutive pairs (champion, confuser,
  confuser, champion, ...), and the search below additionally requires that
  EVERY CELL gets exactly 2 champion-first and 2 confuser-first pairs, so the
  balance holds within each cell, not only in total.

* REPEAT INDEX DECORRELATED FROM CHRONOLOGICAL POSITION.  If repeat 1 is always
  early and repeat 4 always late, any drift over the session is confounded with
  repeat index and the repeat spread stops being an error bar.  The pair order
  is searched for near-zero Pearson correlation between repeat index and
  position, subject to the constraints above.

Nothing under tools/ is modified.  This only writes a TSV the harness reads.
"""
import itertools
import json
import random
import sys

# The six chip cells, copied verbatim from run_acceptance2.sh's CORE matrix.
# cell_id | scene | class | backend | camera | speed | duration_s
CELLS = [
    ("A.static__ships",    "s15_static_offset",    "A", "chip", "himax_typical", "chip", 45),
    ("B.moving__ships",    "s01_control_moving",   "B", "chip", "himax_typical", "chip", 50),
    ("C.empty__ships",     "s02_control_empty",    "C", "chip", "himax_typical", "chip", 35),
    ("D.occlusion__ships", "s07_occlusion_reappear", "D", "chip", "himax_typical", "chip", 60),
    ("E.furniture__ships", "s16_furniture_only",   "E", "chip", "himax_typical", "chip", 35),
    ("F.pets__ships",      "s03_pets_only",        "F", "chip", "himax_typical", "chip", 35),
]
REPEATS = [1, 2, 3, 4]
MODELS = ["champion", "confuser"]


def pearson(xs, ys):
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = sum((x - mx) ** 2 for x in xs) ** 0.5
    dy = sum((y - my) ** 2 for y in ys) ** 0.5
    return num / (dx * dy) if dx and dy else 0.0


def spearman(xs, ys):
    def rank(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            avg = (i + j) / 2.0 + 1
            for k in range(i, j + 1):
                r[order[k]] = avg
            i = j + 1
        return r
    return pearson(rank(xs), rank(ys))


def first_model_for_pair(p):
    """ABBA over the pair index: champion, confuser, confuser, champion, ..."""
    return MODELS[0] if (p % 4) in (0, 3) else MODELS[1]


def cell_balanced(pairs):
    """Each cell must get exactly 2 champion-first and 2 confuser-first pairs."""
    tally = {}
    for p, (cell, _rep) in enumerate(pairs):
        tally.setdefault(cell, []).append(first_model_for_pair(p))
    return all(v.count(MODELS[0]) == 2 for v in tally.values())


def adjacency_penalty(pairs):
    """Prefer plans that do not fly the same cell in consecutive pairs: a scene
    repeated back to back would share whatever transient the machine is in."""
    return sum(1 for a, b in zip(pairs, pairs[1:]) if a[0] == b[0])


def main():
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 20260913
    out_tsv = sys.argv[2]
    out_json = sys.argv[3]

    universe = [(c[0], r) for c in CELLS for r in REPEATS]
    rng = random.Random(seed)

    best, best_key = None, None
    for _ in range(400000):
        cand = universe[:]
        rng.shuffle(cand)
        if not cell_balanced(cand):
            continue
        adj = adjacency_penalty(cand)
        if adj > 0:
            continue
        pos = list(range(len(cand)))
        reps = [r for _c, r in cand]
        key = (abs(pearson(pos, reps)), abs(spearman(pos, reps)))
        if best_key is None or key < best_key:
            best, best_key = cand, key
            if key[0] < 1e-9 and key[1] < 1e-9:
                break

    if best is None:
        raise SystemExit("no plan satisfied the constraints; widen the search")

    byname = {c[0]: c for c in CELLS}
    rows, order = [], 0
    for p, (cell, rep) in enumerate(best):
        first = first_model_for_pair(p)
        seq = [first] + [m for m in MODELS if m != first]
        for model in seq:
            order += 1
            cid, scene, cls, backend, camera, speed, dur = byname[cell]
            rows.append({"order": order, "model": model, "cell": cid, "scene": scene,
                         "scene_class": cls, "backend": backend, "camera": camera,
                         "speed": speed, "duration_s": dur, "repeat": rep,
                         "pair": p + 1, "first_in_pair": int(model == first)})

    with open(out_tsv, "w") as f:
        f.write("# order\tmodel\tcell\tscene\tclass\tbackend\tcamera\tspeed\tdur\trepeat\tpair\n")
        for r in rows:
            f.write("\t".join(str(r[k]) for k in
                    ("order", "model", "cell", "scene", "scene_class", "backend",
                     "camera", "speed", "duration_s", "repeat", "pair")) + "\n")

    # Balance report: everything a reader would want to check by hand.
    pos = [r["order"] for r in rows]
    reps = [r["repeat"] for r in rows]
    pair_pos = list(range(len(best)))
    pair_reps = [r for _c, r in best]
    champ_pos = [r["order"] for r in rows if r["model"] == "champion"]
    conf_pos = [r["order"] for r in rows if r["model"] == "confuser"]

    bal = {
        "seed": seed,
        "n_flights": len(rows),
        "n_pairs": len(best),
        "corr_repeat_vs_flight_order_pearson": round(pearson(pos, reps), 6),
        "corr_repeat_vs_flight_order_spearman": round(spearman(pos, reps), 6),
        "corr_repeat_vs_pair_position_pearson": round(pearson(pair_pos, pair_reps), 6),
        "corr_repeat_vs_pair_position_spearman": round(spearman(pair_pos, pair_reps), 6),
        "mean_flight_order_champion": round(sum(champ_pos) / len(champ_pos), 3),
        "mean_flight_order_confuser": round(sum(conf_pos) / len(conf_pos), 3),
        "champion_first_pairs": sum(1 for p in pair_pos if first_model_for_pair(p) == "champion"),
        "confuser_first_pairs": sum(1 for p in pair_pos if first_model_for_pair(p) == "confuser"),
        "same_cell_adjacent_pairs": adjacency_penalty(best),
        "per_cell_first_slot": {},
        "per_cell_mean_order": {},
    }
    for c in CELLS:
        cid = c[0]
        fp = [first_model_for_pair(p) for p, (cell, _r) in enumerate(best) if cell == cid]
        bal["per_cell_first_slot"][cid] = {"champion_first": fp.count("champion"),
                                           "confuser_first": fp.count("confuser")}
        for m in MODELS:
            o = [r["order"] for r in rows if r["cell"] == cid and r["model"] == m]
            bal["per_cell_mean_order"].setdefault(cid, {})[m] = round(sum(o) / len(o), 2)
    # Repeat index vs order, per model separately.
    for m in MODELS:
        o = [r["order"] for r in rows if r["model"] == m]
        rp = [r["repeat"] for r in rows if r["model"] == m]
        bal[f"corr_repeat_vs_order_{m}"] = round(pearson(o, rp), 6)

    json.dump(bal, open(out_json, "w"), indent=2)
    print(json.dumps(bal, indent=2))


if __name__ == "__main__":
    main()
