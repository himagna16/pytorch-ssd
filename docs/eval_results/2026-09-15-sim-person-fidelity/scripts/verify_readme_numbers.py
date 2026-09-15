#!/usr/bin/env python3
"""Re-derive every number quoted in README.md from the tables, and fail loudly on
any that has drifted.

This exists because the project has twice shipped a headline that the tables did
not support. The claims below are typed in by hand FROM the README, not read out
of it, so that a table regenerated with different data makes this script fail
rather than silently agreeing with itself. 295 scalar claims plus 8 structural
ones (sign counts and interval-crossing counts).

Usage: nemoenv/bin/python verify_readme_numbers.py <dir>
Exit status 0 if every claim matches, 1 otherwise.
"""
import csv
import sys
from pathlib import Path

D = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
OK, BAD = [], []


def rdt(p):
    return list(csv.DictReader(open(D / p), delimiter="\t"))


def chk(name, claimed, actual, tol=0.0011):
    (OK if abs(claimed - actual) <= tol else BAD).append(
        f"{name}: README {claimed} vs table {actual:.4f}")


def main():
    gap = [r for r in rdt("tables/matched_gap.tsv") if r["sim_group"] == "sim_cells_himax"]

    def cell(rn, arm, lo):
        return [x for x in gap if x["real_group"] == rn and x["arm"] == arm
                and x["bin_lo"] == str(lo)][0]

    # ---- 4(a) the chip d_median table -----------------------------------
    for rn, vals in (("real_all", [(25, 0.174), (40, 0.081), (55, 0.039), (80, 0.034)]),
                     ("real_whole_upright", [(25, 0.001), (40, 0.025), (55, -0.006), (80, 0.010)]),
                     ("real_wui", [(25, 0.343), (40, 0.204), (55, 0.251), (80, 0.017)]),
                     ("realhimax_whole_upright", [(25, 0.263), (40, 0.100), (55, 0.078), (80, 0.055)])):
        for lo, v in vals:
            chk(f"(a) {rn} chip {lo}", v, float(cell(rn, "chip", lo)["d_median"]))

    # ---- 4(b) the chip d_frac table, himax both sides --------------------
    for lo, sim, real, d in ((25, 0.933, 0.333, 0.600), (40, 0.942, 0.699, 0.243),
                             (55, 0.917, 0.726, 0.191), (80, 1.000, 0.799, 0.201)):
        r = cell("realhimax_whole_upright", "chip", lo)
        chk(f"(b) {lo} sim", sim, float(r["sim_frac"]))
        chk(f"(b) {lo} real", real, float(r["real_frac"]))
        chk(f"(b) {lo} d", d, float(r["d_frac"]))

    # ---- 4(b) the hold band ---------------------------------------------
    hb = {(r["group"], r["arm"]): r for r in rdt("tables/hold_band.tsv")
          if r["cut"] == "size 63.4-100.2 px"}
    for grp, arm, med, ge, lt in (
            ("sim_cells_himax", "float", 0.991, 1.000, 0.000),
            ("sim_cells_himax", "fq", 0.992, 1.000, 0.000),
            ("sim_cells_himax", "chip", 0.978, 1.000, 0.000),
            ("real_whole_upright", "float", 0.987, 0.790, 0.074),
            ("real_whole_upright", "fq", 0.984, 0.802, 0.062),
            ("real_whole_upright", "chip", 0.984, 0.778, 0.049),
            ("realhimax_whole_upright", "float", 0.910, 0.704, 0.107),
            ("realhimax_whole_upright", "fq", 0.871, 0.683, 0.128),
            ("realhimax_whole_upright", "chip", 0.906, 0.749, 0.095),
            ("real_all", "float", 0.939, 0.723, 0.106),
            ("real_all", "fq", 0.933, 0.719, 0.113),
            ("real_all", "chip", 0.936, 0.750, 0.085),
            ("real_wui", "float", 0.878, 0.524, 0.190),
            ("real_wui", "fq", 0.855, 0.524, 0.143),
            ("real_wui", "chip", 0.731, 0.476, 0.143)):
        r = hb[(grp, arm)]
        chk(f"hold {grp} {arm} med", med, float(r["median"]))
        chk(f"hold {grp} {arm} ge", ge, float(r["frac_ge_075"]))
        chk(f"hold {grp} {arm} lt", lt, float(r["frac_lt_045"]))
    chk("hold sim n", 102, float(hb[("sim_cells_himax", "chip")]["n"]), tol=0.5)
    chk("hold sim clusters", 34, float(hb[("sim_cells_himax", "chip")]["n_clusters"]), tol=0.5)

    # ---- 4(b) size standardisation ---------------------------------------
    ss = {(r["real_group"], r["arm"]): r for r in rdt("tables/size_standardised.tsv")
          if r["sim_group"] == "sim_cells_himax" and r["metric"] == "frac_ge_0.75"}
    for rn, f_, q, c, rf, rq, rc in (
            ("real_all", 0.652, 0.633, 0.655, 1.50, 1.55, 1.44),
            ("real_whole_upright", 0.773, 0.762, 0.732, 1.27, 1.28, 1.29),
            ("realhimax_whole_upright", 0.625, 0.549, 0.713, 1.57, 1.78, 1.32),
            ("real_wui", 0.546, 0.501, 0.492, 1.79, 1.95, 1.91)):
        for arm, v, rv in (("float", f_, rf), ("fq", q, rq), ("chip", c, rc)):
            chk(f"std {rn} {arm}", v, float(ss[(rn, arm)]["real_standardised"]))
            chk(f"std {rn} {arm} ratio", rv, float(ss[(rn, arm)]["ratio"]), tol=0.006)
    for arm, v in (("float", 0.979), ("fq", 0.979), ("chip", 0.943)):
        chk(f"std sim {arm}", v, float(ss[("real_all", arm)]["sim"]))

    # ---- 4(c) the exit bar ------------------------------------------------
    eb = {(r["group"], r["arm"]): r for r in rdt("tables/exit_bar.tsv")}
    for grp, f_, q, c, n in (("sim_cells_himax", 0.000, 0.000, 0.000, 282),
                             ("real_all", 0.142, 0.150, 0.119, 1261),
                             ("real_whole_upright", 0.088, 0.081, 0.074, 136),
                             ("realhimax_whole_upright", 0.120, 0.142, 0.113, 408),
                             ("real_wui", 0.216, 0.189, 0.189, 37),
                             ("real_occluded_or_truncated", 0.148, 0.158, 0.124, 1125),
                             ("sim_cohort_himax", 0.442, 0.457, 0.397, 4188)):
        for arm, v in (("float", f_), ("fq", q), ("chip", c)):
            chk(f"exit {grp} {arm}", v, float(eb[(grp, arm)]["frac_lt_045"]))
        chk(f"exit {grp} n", n, float(eb[(grp, "chip")]["n"]), tol=0.5)

    # ---- 4(d) the compression --------------------------------------------
    rm = {(r["stratum"], r["arm"]): r for r in rdt("tables/regression_to_middle.tsv")}
    for st, arm, sl, lo, hi, rr, fp in (
            ("whole_upright", "chip", -0.792, -0.941, -0.651, -0.603, 0.585),
            ("whole_upright", "float", -0.753, -0.903, -0.607, -0.561, 0.563),
            ("whole_upright", "fq", -0.797, -0.932, -0.659, -0.594, 0.568),
            ("wui", "chip", -0.738, -0.950, -0.526, -0.661, 0.622)):
        r = rm[(st, arm)]
        for lbl, v, k in (("slope", sl, "slope"), ("lo", lo, "slope_lo"), ("hi", hi, "slope_hi"),
                          ("r", rr, "pearson_r"), ("fp", fp, "fixed_point")):
            chk(f"reg {st} {arm} {lbl}", v, float(r[k]))
    buckets = {(r["stratum"], r["arm"], r["bucket"]): r for r in rdt("tables/regression_to_middle.tsv")}
    for b, n, d in (("[0.0,0.3)", 10, 0.292), ("[0.3,0.6)", 17, 0.073),
                    ("[0.6,0.9)", 52, -0.210), ("[0.9,1.0)", 125, -0.302)):
        r = buckets[("whole_upright", "chip", b)]
        chk(f"bucket {b} n", n, float(r["bucket_n"]), tol=0.5)
        chk(f"bucket {b} d", d, float(r["bucket_median_d"]))

    # ---- the paired test --------------------------------------------------
    pr = {(r["arm"], r["stratum"]): r for r in rdt("tables/paired_render.tsv")
          if r["camera"] == "himax"}
    for arm, st, md, lo, hi, pg, rg, pl, rl in (
            ("chip", "whole_upright", -0.209, -0.255, -0.156, 0.755, 0.373, 0.069, 0.245),
            ("chip", "wui", -0.068, -0.127, -0.033, 0.593, 0.458, 0.170, 0.288)):
        r = pr[(arm, st)]
        for lbl, v, k in (("med", md, "median_d"), ("lo", lo, "d_lo"), ("hi", hi, "d_hi"),
                          ("photo_ge", pg, "photo_frac_ge075"), ("render_ge", rg, "render_frac_ge075"),
                          ("photo_lt", pl, "photo_frac_lt045"), ("render_lt", rl, "render_frac_lt045")):
            chk(f"paired {arm} {st} {lbl}", v, float(r[k]))

    # ---- 4(e) subject selection -------------------------------------------
    sub = rdt("tables/subject_selection.tsv")
    for rng, px, cm, cf, v, pc in (("1.5", 103.9, 0.769, 0.526, 0.998, 99.6),
                                   ("2.0", 78.2, 0.642, 0.342, 0.997, 100.0),
                                   ("2.5", 62.4, 0.430, 0.147, 0.979, 100.0),
                                   ("3.0", 51.9, 0.535, 0.177, 0.943, 98.5),
                                   ("3.5", 44.6, 0.617, 0.274, 0.972, 98.5),
                                   ("4.0", 38.8, 0.605, 0.274, 0.980, 98.9)):
        r = [x for x in sub if x["question"] == "render_rank" and x["range_m"] == rng][0]
        chk(f"sel {rng} px", px, float(r["px128_h"]), tol=0.06)
        chk(f"sel {rng} med", cm, float(r["peer_median"]))
        chk(f"sel {rng} ge", cf, float(r["peer_frac_ge_075"]))
        chk(f"sel {rng} v", v, float(r["subject_value"]))
        chk(f"sel {rng} pc", pc, float(r["percentile"]), tol=0.06)
    for arm, v, pc, pm in (("float", 0.984, 43.8, 0.993), ("fq", 0.986, 43.8, 0.993),
                           ("chip", 0.989, 54.2, 0.987)):
        r = [x for x in sub if x["question"] == "photo_rank" and x["arm"] == arm][0]
        chk(f"photorank {arm}", v, float(r["subject_value"]))
        chk(f"photorank {arm} pc", pc, float(r["percentile"]), tol=0.06)
        chk(f"photorank {arm} peermed", pm, float(r["peer_median"]))

    # ---- 4(e) the same image both ways -------------------------------------
    si = {(r["arm"], r["camera"]): r for r in rdt("tables/same_image.tsv")}
    for arm, cam, ph, re_, d in (("float", "clean", 0.984, 0.996, 0.012),
                                 ("fq", "clean", 0.986, 0.996, 0.010),
                                 ("chip", "clean", 0.989, 0.997, 0.008),
                                 ("float", "himax", 0.993, 0.999, 0.006),
                                 ("fq", "himax", 0.995, 0.999, 0.005),
                                 ("chip", "himax", 0.997, 0.999, 0.002)):
        r = si[(arm, cam)]
        chk(f"same {arm} {cam} photo", ph, float(r["photo"]))
        chk(f"same {arm} {cam} render", re_, float(r["render"]))
        chk(f"same {arm} {cam} d", d, float(r["d"]))

    # ---- 4(f) the camera decomposition -------------------------------------
    cd = {(r["arm"], r["stratum"]): r for r in rdt("tables/camera_decomposition.tsv")
          if r["metric"] == "frac_ge_0.75"}
    for arm, st, raw, p244, ps, rp, sp, n in (
            ("float", "all", 0.696, 0.686, 0.536, -0.010, -0.150, 1261),
            ("fq", "all", 0.687, 0.672, 0.505, -0.014, -0.168, 1261),
            ("chip", "all", 0.551, 0.704, 0.581, 0.153, -0.123, 1261),
            ("float", "whole_upright", 0.794, 0.787, 0.667, -0.007, -0.120, 136),
            ("fq", "whole_upright", 0.787, 0.787, 0.610, 0.000, -0.177, 136),
            ("chip", "whole_upright", 0.610, 0.765, 0.735, 0.154, -0.029, 136),
            ("chip", "wui", 0.405, 0.514, 0.640, 0.108, 0.126, 37)):
        r = cd[(arm, st)]
        for lbl, v, k in (("raw", raw, "raw"), ("+244", p244, "plus_244"),
                          ("+sens", ps, "plus_244_sensor"), ("resamp", rp, "resample_part"),
                          ("sensor", sp, "sensor_part")):
            chk(f"cam {arm} {st} {lbl}", v, float(r[k]))
        chk(f"cam {arm} {st} n", n, float(r["n_photos"]), tol=0.5)

    # ---- 2 the control ------------------------------------------------------
    ctl = {(r["arm"], r["real_set"], r["metric"]): r for r in rdt("tables/control_resolution.tsv")}
    for rs, n, raw, via, d, lo, hi in (
            ("all people, whole slice", 2693, 0.505, 0.634, 0.129, 0.114, 0.144),
            ("all people, flown band 38.8-103.6 px", 1262, 0.551, 0.704, 0.153, 0.129, 0.176),
            ("whole_upright", 204, 0.564, 0.755, 0.191, 0.132, 0.255),
            ("wui (whole+upright+isolated)", 59, 0.407, 0.593, 0.186, 0.102, 0.288)):
        r = ctl[("chip", rs, "frac_ge_0.75")]
        for lbl, v, k in (("raw", raw, "raw"), ("via", via, "via244"), ("d", d, "delta"),
                          ("lo", lo, "ci_lo"), ("hi", hi, "ci_hi")):
            chk(f"ctl {rs} {lbl}", v, float(r[k]))
        chk(f"ctl {rs} n", n, float(r["n"]), tol=0.5)

    # ---- structural claims --------------------------------------------------
    struct = []
    dm = [float(r["d_median"]) for r in gap]
    df = [float(r["d_frac"]) for r in gap]
    de = [float(r["d_exit"]) for r in gap]
    struct.append(("48 sim_cells cells", len(gap) == 48, len(gap)))
    struct.append(("84 matched_gap cells", len(rdt("tables/matched_gap.tsv")) == 84,
                   len(rdt("tables/matched_gap.tsv"))))
    struct.append(("d_median positive in 45 of 48", sum(1 for x in dm if x > 0) == 45,
                   sum(1 for x in dm if x > 0)))
    struct.append(("d_frac positive in all 48", all(x > 0 for x in df), min(df)))
    struct.append(("no d_frac interval crosses zero",
                   sum(1 for r in gap if float(r["df_lo"]) <= 0 <= float(r["df_hi"])) == 0,
                   sum(1 for r in gap if float(r["df_lo"]) <= 0 <= float(r["df_hi"]))))
    struct.append(("d_exit negative in all 48", all(x < 0 for x in de), max(de)))
    struct.append(("d_exit interval excludes zero in 31",
                   48 - sum(1 for r in gap if float(r["de_lo"]) <= 0 <= float(r["de_hi"])) == 31,
                   48 - sum(1 for r in gap if float(r["de_lo"]) <= 0 <= float(r["de_hi"]))))
    struct.append(("d_frac range +0.154 .. +0.709",
                   abs(min(df) - 0.154) < 0.0011 and abs(max(df) - 0.709) < 0.0011,
                   (round(min(df), 4), round(max(df), 4))))

    print(f"CHECKED {len(OK) + len(BAD)} scalar claims: PASS {len(OK)}, FAIL {len(BAD)}")
    for b in BAD:
        print("   !!", b)
    print(f"CHECKED {len(struct)} structural claims:")
    nbad = 0
    for name, good, got in struct:
        print(f"   {'ok ' if good else '!! '}{name}   (got {got})")
        nbad += 0 if good else 1
    if BAD or nbad:
        print("FAILED")
        return 1
    print("ALL CLAIMS VERIFIED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
