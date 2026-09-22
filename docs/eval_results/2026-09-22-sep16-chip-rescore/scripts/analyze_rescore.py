#!/usr/bin/env python3
"""Re-read the Sep 16 bearing work on the chip arm, the one the drone flies.

Inputs (all produced by this folder's run_rescore.sh, committed gzipped):
  tables/scores_float.csv[.gz]  score_real_frames.py --backend float on the re-rendered frames
  tables/scores_chip.csv[.gz]   score_real_frames.py --backend chip  on the same frames
  tables/sep17_rescore_chip_rerun.csv.gz
                                the committed Sep 17 rescore_chip.py on the same frames
and, from the repo:
  2026-09-16-protocol-geometry/tables/scores.csv.gz        the Sep 16 float per-frame scores
  2026-09-17-chip-arm-rescore/tables/reference_table_chip.tsv   the Sep 17 "chip" column

Three questions, in order:
  1. Are the re-rendered frames the Sep 16 frames?  (float re-score vs Sep 16, per frame)
  2. Is the Sep 17 "chip" column the chip arm?      (rescore_chip.py re-run vs Sep 17 table,
                                                     then vs score_real_frames --backend chip)
  3. Which Sep 16 conclusions survive on the chip arm?

Usage: trainenv/bin/python analyze_rescore.py [sep17_rerun.csv]
"""
import csv
import gzip
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
D = HERE.parent
EV = D.parent
TAB = D / "tables"
SEP16 = EV / "2026-09-16-protocol-geometry/tables/scores.csv.gz"
SEP16_REF = EV / "2026-09-16-protocol-geometry/tables/reference_table.tsv"
SEP17_REF = EV / "2026-09-17-chip-arm-rescore/tables/reference_table_chip.tsv"
SEP17_RERUN = Path(sys.argv[1]) if len(sys.argv) > 1 else TAB / "sep17_rescore_chip_rerun.csv.gz"


def pick(name):
    """tables/<name>, or its .gz (what is committed)."""
    p = TAB / name
    return p if p.exists() else p.with_name(name + ".gz")


BAR = 0.75
INDEX = {"124442": 28.4, "527750": 34.3, "157365": 34.6, "356427": 37.8, "250127": 52.1,
         "61747": 86.8, "161875": 87.0, "401446": 88.8, "374369": 90.3, "266409": 92.1,
         "280779": 92.7, "556158": 93.9, "control": 99.2}
SUBS = sorted(INDEX, key=INDEX.get)
HARD4 = ("124442", "527750", "157365", "356427")
POSE4 = ("161875", "374369", "266409", "401446")
# flown, chip arm, 3.64 m, 8 flights each (these were always chip; not rescored)
FLOWN_OFF = {"124442": 0.000, "527750": 0.000, "157365": 0.000, "356427": 0.000,
             "250127": 0.000, "61747": 0.722, "161875": 0.000, "401446": 0.106,
             "374369": 0.000, "266409": 0.098, "280779": 0.986, "556158": 0.879,
             "control": 0.991}                      # 2026-09-15-people-plural, off axis
FLOWN_ON = {"124442": 0.000, "527750": 0.000, "157365": 0.000, "356427": 0.000,
            "250127": 0.007, "61747": 0.991, "161875": 0.613, "401446": 0.990,
            "374369": 0.990, "266409": 0.990, "280779": 0.987, "556158": 0.990,
            "control": 0.990}                       # 2026-09-16-onaxis README, on axis
DISTS = (1.5, 2.0, 2.5, 3.0, 3.5)
BEARS = (-25.0, -10.0, 0.0, 10.0, 25.0)

out_lines = []


def say(s=""):
    print(s)
    out_lines.append(s)


def key_of(name):
    """(subject, dist, bearing, frame#) from a cpx_grab filename."""
    toks = Path(name).name[:-4].split("_")
    t = {}
    for tok in toks:
        if tok.startswith("subj-"):
            t["s"] = tok[5:]
        elif tok.startswith("d") and tok[1:2].isdigit():
            t["d"] = float(tok[1:])
        elif tok.startswith("b") and (tok[1:2].isdigit() or tok[1:2] == "-"):
            t["b"] = float(tok[1:])
        elif tok.startswith("f") and tok[1:].isdigit():
            t["f"] = int(tok[1:])
    return t["s"], t["d"], t["b"], t["f"]


def load_scores(path, conf_col="conf"):
    op = gzip.open if str(path).endswith(".gz") else open
    rows = {}
    with op(path, "rt", newline="") as f:
        for r in csv.DictReader(f):
            k = key_of(r["file"])
            rows.setdefault(k, []).append(float(r[conf_col]))
    return rows


def cells(frames):
    by = defaultdict(list)
    for (s, d, b, _f), cs in frames.items():
        by[(s, d, b)].extend(cs)
    return by


def frac(cs):
    return float(np.mean(np.asarray(cs) >= BAR))


def load_ref(path, mcol, fcol):
    out = {}
    with open(path, newline="") as f:
        for r in csv.DictReader(f, delimiter="\t"):
            out[(r["subject"], float(r["dist_m"]), float(r["bearing_deg"]))] = (
                float(r[mcol]), float(r[fcol]), int(r.get("n_frames") or r.get("n")))
    return out


def main():
    f16 = load_scores(SEP16)
    flo = load_scores(pick("scores_float.csv"))
    chp = load_scores(pick("scores_chip.csv"))
    s17 = load_scores(SEP17_RERUN, conf_col="conf_chip")
    C16, CF, CC, C17 = cells(f16), cells(flo), cells(chp), cells(s17)
    ref16 = load_ref(SEP16_REF, "mean_conf", "frac_ge_0.75")
    ref17 = load_ref(SEP17_REF, "mean_conf_chip", "frac_chip")

    # chip confidences are discrete (sigmoid of raw * eps); a CSV value printed as
    # 0.7500 could be raw 5466 (below the bar). Make sure none sits there.
    amb = sum(1 for cs in chp.values() for c in cs if round(c, 4) in (0.75, 0.45))
    say("=" * 96)
    say("1. ARE THE RE-RENDERED FRAMES THE SEP 16 FRAMES?  (float arm, both sides)")
    say("=" * 96)
    same = [k for k in f16 if k in flo]
    exact = sum(1 for k in same if f16[k][0] == flo[k][0])
    say(f"Sep 16 per-frame rows {sum(len(v) for v in f16.values())}, re-rendered {sum(len(v) for v in flo.values())}")
    say(f"frames matched by (subject, dist, bearing, frame#): {len(same)}; "
        f"float conf identical to 4 dp: {exact} of {len(same)}")
    cell_exact = sum(1 for c in ref16 if c in CF and round(float(np.mean(CF[c])), 4) == ref16[c][0]
                     and round(frac(CF[c]), 4) == ref16[c][1])
    n41 = [c for c in ref16 if ref16[c][2] != 40]
    say(f"cells whose Sep 16 mean conf AND frac>=0.75 reproduce exactly: {cell_exact} of {len(ref16)}")
    say(f"cells Sep 16 captured with 41 frames (one repeated by the grab): {len(n41)} "
        f"{[f'{s} d{d:g} b{b:g}' for s, d, b in n41]}")
    worst = max(abs(float(np.mean(CF[c])) - ref16[c][0]) for c in ref16)
    say(f"largest per-cell mean-conf difference: {worst:.4f}")
    agg16 = np.mean([c for v in f16.values() for c in v])
    aggF = np.mean([c for v in flo.values() for c in v])
    say(f"aggregate float mean conf: Sep 16 {agg16:.4f}, re-rendered {aggF:.4f}")

    say()
    say("=" * 96)
    say("2. IS THE SEP 17 'CHIP' COLUMN THE CHIP ARM?")
    say("=" * 96)
    c17_exact = sum(1 for c in ref17 if c in C17 and round(float(np.mean(C17[c])), 4) == ref17[c][0]
                    and round(frac(C17[c]), 4) == ref17[c][1])
    say(f"committed rescore_chip.py re-run on the re-rendered frames reproduces the Sep 17 table "
        f"(mean AND frac, 4 dp) on {c17_exact} of {len(ref17)} cells")
    same17 = [k for k in s17 if k in chp]
    eq = sum(1 for k in same17 if round(s17[k][0], 4) == round(chp[k][0], 4))
    say(f"rescore_chip.py vs score_real_frames --backend chip, same frames: identical conf on "
        f"{eq} of {len(same17)} frames")
    say("reason: rescore_chip.py calls ChipPerception(firmware_preprocess(g)) and ChipPerception")
    say("        preprocesses AGAIN, so its network input is a 2x2-blurred copy of what the chip sees")
    say("        (reproduced frame-for-frame in tools/real_frames/test_score_real_frames.py)")
    say(f"boundary check: chip frames whose 4-dp conf is exactly 0.7500 or 0.4500: {amb}")

    all_f = [c for v in flo.values() for c in v]
    all_c = [c for v in chp.values() for c in v]
    all_17 = [c for v in s17.values() for c in v]
    say()
    say(f"{'AGGREGATE, 13,000 frames':34s}{'float':>10}{'Sep17 chip':>12}{'chip (real)':>13}")
    say(f"{'mean confidence':34s}{np.mean(all_f):>10.4f}{np.mean(all_17):>12.4f}{np.mean(all_c):>13.4f}")
    say(f"{'fraction of frames >= 0.75':34s}{frac(all_f):>10.4f}{frac(all_17):>12.4f}{frac(all_c):>13.4f}")
    say(f"chip minus float: mean conf {np.mean(all_c) - np.mean(all_f):+.4f}, "
        f"frac {frac(all_c) - frac(all_f):+.4f}   (Sep 17 claimed -0.1238 / -0.2394)")
    mv = [c for c in CF if abs(frac(CC[c]) - frac(CF[c])) >= 0.25]
    mv17 = [c for c in CF if abs(frac(C17[c]) - frac(CF[c])) >= 0.25]
    say(f"cells moving by >= 0.25 in frac, float -> chip: {len(mv)} of {len(CF)} "
        f"(Sep 17 method on the same frames: {len(mv17)}; Sep 17 claimed 122)")
    big = sorted(CF, key=lambda c: frac(CC[c]) - frac(CF[c]))
    say("  largest falls float -> chip:")
    for c in big[:6]:
        say(f"    {c[0]:>8} d{c[1]:.1f} b{c[2]:+.0f}   {frac(CF[c]):.3f} -> {frac(CC[c]):.3f}")
    say("  largest rises:")
    for c in big[-4:][::-1]:
        say(f"    {c[0]:>8} d{c[1]:.1f} b{c[2]:+.0f}   {frac(CF[c]):.3f} -> {frac(CC[c]):.3f}")

    # ---------------------------------------------------------------- 3
    say()
    say("=" * 96)
    say("3. THE SEP 16 CONCLUSIONS, ON THE CHIP ARM")
    say("=" * 96)
    say("3a. Headline: fraction of frames >= 0.75 at bearing 0 (float -> chip), with flown M1")
    say(f"{'subject':>8}{'index':>6}{'flown off':>10}{'flown on':>9}" +
        "".join(f"{f'{d:g} m':>15}" for d in DISTS))
    for s in SUBS:
        row = f"{s:>8}{INDEX[s]:>6.1f}{FLOWN_OFF[s]:>10.3f}{FLOWN_ON[s]:>9.3f}"
        for d in DISTS:
            c = (s, d, 0.0)
            row += f"{frac(CF[c]):>7.3f}>{frac(CC[c]):<7.3f}"
        say(row)
    for label, grp in (("genuinely hard four", HARD4), ("'failing on pose' four", POSE4)):
        say(f"  {label}: chip frac at b0, 3.5 m = "
            + ", ".join(f"{s} {frac(CC[(s, 3.5, 0.0)]):.3f}" for s in grp)
            + " | 1.5 m = " + ", ".join(f"{frac(CC[(s, 1.5, 0.0)]):.3f}" for s in grp))
    hard_past2 = all(frac(CC[(s, d, 0.0)]) == 0.0 for s in HARD4 for d in (2.5, 3.0, 3.5))
    say(f"  hard four at exactly 0.000 at every b0 range past 2.0 m on chip: {hard_past2}")

    say()
    say("3b. Mean confidence pooled over the 13 subjects, by distance x bearing (chip; float in brackets)")
    say(f"{'dist':>6}" + "".join(f"{f'b{b:+.0f}':>17}" for b in BEARS))
    pooled = {}
    for d in DISTS:
        row = f"{d:>6.1f}"
        for b in BEARS:
            cc = [x for s in SUBS for x in CC[(s, d, b)]]
            ff = [x for s in SUBS for x in CF[(s, d, b)]]
            pooled[(d, b)] = (float(np.mean(cc)), float(np.mean(ff)))
            row += f"{pooled[(d, b)][0]:>9.3f} [{pooled[(d, b)][1]:.3f}]"
        say(row)
    for d in (1.5, 3.5):
        for arm, i in (("chip", 0), ("float", 1)):
            c0 = pooled[(d, 0.0)][i]
            costs = [c0 - pooled[(d, b)][i] for b in (-25.0, 25.0)]
            say(f"  {arm:5s} cost of +-25 deg at {d} m: {costs[0]:+.3f} (left) {costs[1]:+.3f} (right)")

    say()
    say("3c. Left/right asymmetry, pooled (negative bearing minus positive)")
    for mag in (10.0, 25.0):
        for arm, CX in (("chip", CC), ("float", CF)):
            neg = [x for c, v in CX.items() if c[2] == -mag for x in v]
            pos = [x for c, v in CX.items() if c[2] == mag for x in v]
            say(f"  +-{mag:g} deg {arm:5s}: left {np.mean(neg):.3f} right {np.mean(pos):.3f} "
                f"diff {np.mean(neg) - np.mean(pos):+.3f}")

    say()
    say("3d. The 2.5 m rung: pooled mean conf by distance (all subjects, all bearings)")
    for arm, CX in (("chip", CC), ("float", CF)):
        prof = {d: float(np.mean([x for c, v in CX.items() if c[1] == d for x in v])) for d in DISTS}
        mins = [d for d in DISTS[1:-1]
                if prof[d] < prof[DISTS[DISTS.index(d) - 1]] and prof[d] < prof[DISTS[DISTS.index(d) + 1]]]
        n_dip = sum(1 for s in SUBS
                    if np.mean(CX[(s, 2.5, 0.0)]) < np.mean(CX[(s, 2.0, 0.0)])
                    and np.mean(CX[(s, 2.5, 0.0)]) < np.mean(CX[(s, 3.0, 0.0)]))
        say(f"  {arm:5s}: " + ", ".join(f"{d:g} m {prof[d]:.3f}" for d in DISTS)
            + f" | interior minima {mins or 'none'} | subjects dipping at 2.5 m (b0): {n_dip} of 13")

    say()
    say("3e. 'What a real person must beat': 3.5 m, bearing 0, frac >= 0.75 across subjects")
    for arm, CX in (("chip", CC), ("float", CF)):
        vals = [frac(CX[(s, 3.5, 0.0)]) for s in SUBS]
        say(f"  {arm:5s}: min {min(vals):.3f} median {np.median(vals):.3f} max {max(vals):.3f}, "
            f"at exactly 0.000: {sum(v == 0 for v in vals)} of 13, at >= 0.9: {sum(v >= 0.9 for v in vals)}")

    say()
    say("3f. On-axis flights (chip, flown) against the grid at 3.5 m, bearing 0")
    say(f"{'subject':>8}{'flown on M1':>12}{'grid float':>12}{'grid chip':>11}")
    for s in SUBS:
        say(f"{s:>8}{FLOWN_ON[s]:>12.3f}{frac(CF[(s, 3.5, 0.0)]):>12.3f}{frac(CC[(s, 3.5, 0.0)]):>11.3f}")
    # does the grid rank-predict the flights better on the arm that flew?
    fl = np.array([FLOWN_ON[s] for s in SUBS])
    for arm, CX in (("float", CF), ("chip", CC)):
        g = np.array([frac(CX[(s, 3.5, 0.0)]) for s in SUBS])
        say(f"  {arm:5s} grid vs flown on-axis M1: mean |grid - flown| {np.mean(np.abs(g - fl)):.3f}, "
            f"max {np.max(np.abs(g - fl)):.3f} ({SUBS[int(np.argmax(np.abs(g - fl)))]})")
    say()
    say("3g. Off-axis flights (people-plural, -15.9 deg, 3.64 m) against the grid, 3.5 m")
    say("    (the grid has no -15.9 deg column; -10 and -25 bracket it)")
    say(f"{'subject':>8}{'flown off':>10}{'chip b-10':>10}{'chip b-25':>10}{'chip b0':>9}")
    for s in SUBS:
        say(f"{s:>8}{FLOWN_OFF[s]:>10.3f}{frac(CC[(s, 3.5, -10.0)]):>10.3f}"
            f"{frac(CC[(s, 3.5, -25.0)]):>10.3f}{frac(CC[(s, 3.5, 0.0)]):>9.3f}")

    # ---------------------------------------------------------------- tsv
    with open(TAB / "cells_three_arms.tsv", "w", newline="") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(["subject", "index_pct", "dist_m", "bearing_deg", "n",
                    "mean_conf_float_sep16", "frac_float_sep16",
                    "mean_conf_float_rerender", "frac_float_rerender",
                    "mean_conf_sep17_tsv", "frac_sep17_tsv",
                    "mean_conf_sep17_rerun", "frac_sep17_rerun",
                    "mean_conf_chip", "frac_chip"])
        for c in sorted(CF, key=lambda c: (INDEX[c[0]], c[1], c[2])):
            r16, r17 = ref16[c], ref17[c]
            w.writerow([c[0], INDEX[c[0]], c[1], c[2], len(CC[c]), r16[0], r16[1],
                        round(float(np.mean(CF[c])), 4), round(frac(CF[c]), 4),
                        r17[0], r17[1],
                        round(float(np.mean(C17[c])), 4), round(frac(C17[c]), 4),
                        round(float(np.mean(CC[c])), 4), round(frac(CC[c]), 4)])
    (TAB / "analysis.txt").write_text("\n".join(out_lines) + "\n")
    print(f"\nwrote {TAB / 'analysis.txt'} and {TAB / 'cells_three_arms.tsv'}")


if __name__ == "__main__":
    main()
