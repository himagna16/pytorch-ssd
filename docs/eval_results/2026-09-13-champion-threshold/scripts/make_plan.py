#!/usr/bin/env python
"""Build the interleaved latch-threshold flight plan.

THE DESIGN, and why each piece is there
---------------------------------------
ONE model (the champion) x 4 latch configurations x 6 chip cells x 4 repeats
= 96 flights, one session.

The four configurations differ ONLY in two command-line flags that
``follow_person.py`` already exposes.  Nothing under ``tools/`` is edited.

    t070     --vis-enter 0.70 --confirm-frames 3   (the champion exactly as shipped)
    t075     --vis-enter 0.75 --confirm-frames 3
    t080     --vis-enter 0.80 --confirm-frames 3
    t070cf4  --vis-enter 0.70 --confirm-frames 4   (the "4 frames instead of 3" probe)

``--vis-exit`` stays at its 0.45 default in every arm.  The leave threshold is
NOT swept here; that is stated as a limit, not hidden.

* MATCHED QUADRUPLES.  The same (cell, repeat) is flown by all FOUR configs back
  to back, within a few minutes.  Machine drift, thermal state and background
  load therefore land on all four arms of every comparison equally.  This is the
  matched-pair discipline the pets A/B run established, widened to four arms.

* A LATIN SQUARE OVER THE WITHIN-BLOCK SLOT.  Inside a block one config must go
  first, and going first is not free: the simulator has just been rebuilt.  Each
  cell has exactly 4 blocks and there are exactly 4 configs, so each config can
  occupy each slot (1st/2nd/3rd/4th) EXACTLY ONCE PER CELL, and therefore exactly
  6 times overall.  This is an exact balance, not an approximate one, and it is
  the reason the design uses 4 repeats rather than the 3 the brief asks as a
  minimum.

* REPEAT INDEX DECORRELATED FROM CHRONOLOGICAL POSITION.  If repeat 1 were always
  early and repeat 4 always late, session drift would be confounded with repeat
  index and the repeat spread would stop being an error bar.  The block order is
  searched for near-zero Pearson and Spearman correlation between repeat index
  and block position, subject to no cell repeating in adjacent blocks.

* SENSOR SEED DEPENDS ONLY ON THE REPEAT INDEX, so the four configs in a matched
  block see the SAME himax noise draw.  Any difference between them is the latch
  rule, not the camera.

Writes a TSV the harness reads plus a balance report.  Reads nothing under tools/.
"""
import json
import random
import sys

# The six chip cells, copied verbatim from run_acceptance2.sh's CORE matrix
# (and identical to the ones the champion-vs-confuser session flew).
# cell_id | scene | class | backend | camera | speed | duration_s
CELLS = [
    ("A.static__ships",    "s15_static_offset",      "A", "chip", "himax_typical", "chip", 45),
    ("B.moving__ships",    "s01_control_moving",     "B", "chip", "himax_typical", "chip", 50),
    ("C.empty__ships",     "s02_control_empty",      "C", "chip", "himax_typical", "chip", 35),
    ("D.occlusion__ships", "s07_occlusion_reappear", "D", "chip", "himax_typical", "chip", 60),
    ("E.furniture__ships", "s16_furniture_only",     "E", "chip", "himax_typical", "chip", 35),
    ("F.pets__ships",      "s03_pets_only",          "F", "chip", "himax_typical", "chip", 35),
]
REPEATS = [1, 2, 3, 4]
# name -> (vis_enter, confirm_frames, vis_exit)
CONFIGS = [
    ("t070",    0.70, 3, 0.45),
    ("t075",    0.75, 3, 0.45),
    ("t080",    0.80, 3, 0.45),
    ("t070cf4", 0.70, 4, 0.45),
]
CONFIG_NAMES = [c[0] for c in CONFIGS]


def pearson(xs, ys):
    n = len(xs)
    if n < 2:
        return 0.0
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


def adjacency_penalty(blocks):
    """Prefer plans that do not fly the same cell in consecutive blocks: a scene
    repeated back to back would share whatever transient the machine is in."""
    return sum(1 for a, b in zip(blocks, blocks[1:]) if a[0] == b[0])


def main():
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 20260913
    out_tsv = sys.argv[2]
    out_json = sys.argv[3]

    universe = [(c[0], r) for c in CELLS for r in REPEATS]   # 24 blocks
    rng = random.Random(seed)

    best, best_key = None, None
    for _ in range(400000):
        cand = universe[:]
        rng.shuffle(cand)
        if adjacency_penalty(cand) > 0:
            continue
        pos = list(range(len(cand)))
        reps = [r for _c, r in cand]
        key = (abs(pearson(pos, reps)), abs(spearman(pos, reps)))
        if best_key is None or key < best_key:
            best, best_key = cand, key
            if key[0] < 1e-9 and key[1] < 1e-9:
                break
    if best is None:
        raise SystemExit("no block order satisfied the constraints; widen the search")

    # THE LATIN SQUARE.  Within each cell, number its 4 blocks 0..3 in the order
    # they will be flown, and rotate the config list by that number.  Cell c's
    # k-th block therefore flies CONFIG_NAMES rotated by (k + cell_offset), which
    # gives every config every slot exactly once per cell.  The per-cell offset
    # is varied so the session does not open with four blocks that all start on
    # the same config.
    cell_offset = {c[0]: i for i, c in enumerate(CELLS)}
    seen = {}
    byname = {c[0]: c for c in CELLS}
    cfg = {c[0]: c for c in CONFIGS}

    rows, order = [], 0
    for b, (cell, rep) in enumerate(best):
        k = seen.get(cell, 0)
        seen[cell] = k + 1
        rot = (k + cell_offset[cell]) % len(CONFIG_NAMES)
        seq = CONFIG_NAMES[rot:] + CONFIG_NAMES[:rot]
        cid, scene, cls, backend, camera, speed, dur = byname[cell]
        for slot, name in enumerate(seq, start=1):
            order += 1
            _n, enter, cframes, exit_ = cfg[name]
            rows.append({"order": order, "config": name, "cell": cid, "scene": scene,
                         "scene_class": cls, "backend": backend, "camera": camera,
                         "speed": speed, "duration_s": dur, "repeat": rep,
                         "block": b + 1, "slot": slot,
                         "vis_enter": enter, "confirm_frames": cframes, "vis_exit": exit_})

    cols = ("order", "config", "cell", "scene", "scene_class", "backend", "camera",
            "speed", "duration_s", "repeat", "block", "slot",
            "vis_enter", "confirm_frames", "vis_exit")
    with open(out_tsv, "w") as f:
        f.write("# " + "\t".join(cols) + "\n")
        for r in rows:
            f.write("\t".join(str(r[k]) for k in cols) + "\n")

    # ---- balance report: everything a reader would want to check by hand ----
    pos = [r["order"] for r in rows]
    reps = [r["repeat"] for r in rows]
    blk_pos = list(range(len(best)))
    blk_reps = [r for _c, r in best]

    bal = {
        "seed": seed,
        "n_flights": len(rows),
        "n_blocks": len(best),
        "configs": {c[0]: {"vis_enter": c[1], "confirm_frames": c[2], "vis_exit": c[3]}
                    for c in CONFIGS},
        "corr_repeat_vs_flight_order_pearson": round(pearson(pos, reps), 6),
        "corr_repeat_vs_flight_order_spearman": round(spearman(pos, reps), 6),
        "corr_repeat_vs_block_position_pearson": round(pearson(blk_pos, blk_reps), 6),
        "corr_repeat_vs_block_position_spearman": round(spearman(blk_pos, blk_reps), 6),
        "same_cell_adjacent_blocks": adjacency_penalty(best),
        "mean_flight_order": {},
        "slot_counts_overall": {},
        "slot_counts_per_cell": {},
        "corr_repeat_vs_order_per_config": {},
    }
    for name in CONFIG_NAMES:
        o = [r["order"] for r in rows if r["config"] == name]
        rp = [r["repeat"] for r in rows if r["config"] == name]
        bal["mean_flight_order"][name] = round(sum(o) / len(o), 3)
        bal["corr_repeat_vs_order_per_config"][name] = round(pearson(o, rp), 6)
        sc = {}
        for s in (1, 2, 3, 4):
            sc[s] = sum(1 for r in rows if r["config"] == name and r["slot"] == s)
        bal["slot_counts_overall"][name] = sc
    for c in CELLS:
        cid = c[0]
        d = {}
        for name in CONFIG_NAMES:
            d[name] = sorted(r["slot"] for r in rows if r["cell"] == cid and r["config"] == name)
        bal["slot_counts_per_cell"][cid] = d
    # Hard self-checks: if the Latin square is not exact, say so loudly.
    bal["latin_square_exact_per_cell"] = all(
        sorted(v) == [1, 2, 3, 4] for d in bal["slot_counts_per_cell"].values() for v in d.values())
    bal["slot_balance_exact_overall"] = all(
        set(sc.values()) == {6} for sc in bal["slot_counts_overall"].values())

    json.dump(bal, open(out_json, "w"), indent=2)
    print(json.dumps(bal, indent=2))


if __name__ == "__main__":
    main()
