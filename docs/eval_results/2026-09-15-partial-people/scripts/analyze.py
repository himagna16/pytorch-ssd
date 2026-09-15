#!/usr/bin/env python3
"""Is a PARTIAL person harder to detect than a whole one, at matched apparent size?

ONE ARM AND ONE THRESHOLD AT A TIME, and both sides of every comparison are rows
of the SAME table, so the resampling chain is identical by construction:
  * `*_via244` is the fidelity study's resolution-matched control (its section 2)
  * `*_himax`  is real_people_himax.csv, which already resizes to 244 before the
               sensor model, so it is matched too
Nothing here mixes a via244 column with a raw one, and nothing compares 0.75 on
one stratum against 0.45 on another.

MATCHED APPARENT SIZE means two things, both reported:
  (i)  cut both strata to the same px128_h band (the flown band, and the hold band)
  (ii) size-STANDARDISE: re-weight every stratum's per-bin rates to ONE reference
       size mix - `whole_upright`'s own, inside the flown band - so a stratum
       cannot win or lose on its size distribution. (i) alone is not enough:
       truncated people are systematically LARGER in the frame.

Usage: nemoenv/bin/python analyze.py <outdir>
"""
import csv
import sys
from pathlib import Path

import numpy as np

D = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
RNG = np.random.default_rng(0)
BAR, EXIT_BAR = 0.75, 0.45                 # follow_person.py --vis-enter / --vis-exit
FLOWN_LO, FLOWN_HI = 155.36 / 4.0, 155.36 / 1.5        # 38.8 .. 103.6 px
HOLD_LO, HOLD_HI = 155.36 / 2.45, 155.36 / 1.55        # 63.4 .. 100.2 px
BINS = [(25, 40), (40, 55), (55, 80), (80, 129)]       # the fidelity study's bins
ARMS = ["float", "fq", "chip"]
REPORT = []


def P(s=""):
    print(s, flush=True)
    REPORT.append(s)


def fge(v):
    return float(np.mean(np.asarray(v, float) >= BAR)) if len(v) else float("nan")


def flt(v):
    return float(np.mean(np.asarray(v, float) < EXIT_BAR)) if len(v) else float("nan")


def med(v):
    return float(np.median(np.asarray(v, float))) if len(v) else float("nan")


def band(rows, lo=FLOWN_LO, hi=FLOWN_HI):
    return [r for r in rows if lo <= float(r["px128_h"]) <= hi]


def nimg(rows):
    return len(set(r["img_id"] for r in rows))


# ------------------------------------------------------------------ bootstrap
def cboot_rate(rows, col, stat, n=2000):
    """Cluster bootstrap over IMAGES. Three himax draws of one photograph are
    one photograph, which is the fidelity study's own clustering rule."""
    if not rows:
        return float("nan"), float("nan")
    keys = np.array(sorted(set(r["img_id"] for r in rows)))
    idx = {k: [] for k in keys}
    for r in rows:
        idx[r["img_id"]].append(float(r[col]))
    if len(keys) < 2:
        return float("nan"), float("nan")
    arrs = {k: np.array(v, float) for k, v in idx.items()}
    out = np.empty(n)
    for i in range(n):
        pick = RNG.choice(keys, len(keys), replace=True)
        out[i] = stat(np.concatenate([arrs[k] for k in pick]))
    return float(np.percentile(out, 2.5)), float(np.percentile(out, 97.5))


def standardised(rows, col, stat, weights):
    """Re-weight per-bin rates onto the reference size mix."""
    num = den = 0.0
    for (lo, hi), w in weights.items():
        b = [float(r[col]) for r in rows if lo <= float(r["px128_h"]) < hi]
        if len(b) < 3 or w == 0:
            continue
        num += w * stat(b)
        den += w
    return num / den if den else float("nan")


def cboot_std(rows, col, stat, weights, n=2000):
    keys = np.array(sorted(set(r["img_id"] for r in rows)))
    if len(keys) < 2:
        return float("nan"), float("nan")
    by = {k: [] for k in keys}
    for r in rows:
        by[r["img_id"]].append(r)
    out = np.empty(n)
    for i in range(n):
        pick = RNG.choice(keys, len(keys), replace=True)
        rs = [r for k in pick for r in by[k]]
        out[i] = standardised(rs, col, stat, weights)
    return float(np.percentile(out[~np.isnan(out)], 2.5)), \
           float(np.percentile(out[~np.isnan(out)], 97.5))


def cboot_std_diff(ra, rb, col, stat, weights, n=2000):
    """95% CI of standardised(a) - standardised(b), both cluster-bootstrapped."""
    def draw(rows):
        keys = np.array(sorted(set(r["img_id"] for r in rows)))
        by = {k: [] for k in keys}
        for r in rows:
            by[r["img_id"]].append(r)
        o = np.empty(n)
        for i in range(n):
            pick = RNG.choice(keys, len(keys), replace=True)
            o[i] = standardised([r for k in pick for r in by[k]], col, stat, weights)
        return o
    if len(set(r["img_id"] for r in ra)) < 2 or len(set(r["img_id"] for r in rb)) < 2:
        return float("nan"), float("nan")
    d = draw(ra) - draw(rb)
    d = d[~np.isnan(d)]
    return float(np.percentile(d, 2.5)), float(np.percentile(d, 97.5))


def main():
    real = [r for r in csv.DictReader(open(D / "tables/strata.csv"))
            if not int(r["is_sim_source"])]
    him = [r for r in csv.DictReader(open(D / "tables/strata_himax.csv"))
           if not int(r["is_sim_source"])]

    def groups(rows):
        return {
            "whole_upright":  [r for r in rows if r["cls"] == "whole_upright"],
            "occl_or_trunc":  [r for r in rows if r["cls"] != "whole_upright"],
            "trunc_only":     [r for r in rows if r["cls"] == "trunc_only"],
            "occl_only":      [r for r in rows if r["cls"] == "occl_only"],
            "trunc_and_occl": [r for r in rows if r["cls"] == "trunc_and_occl"],
            "no_keypoints":   [r for r in rows if r["cls"] == "no_keypoints"],
            "clean_other":    [r for r in rows if r["cls"] == "clean_other"],
            # the drone-shaped sub-cut: cut by the CENTRE CROP, which is the same
            # operation the firmware performs, with no occlusion flag
            "crop_trunc_only": [r for r in rows if r["cls"] == "trunc_only"
                                and int(r["crop_trunc"])],
            "edge_trunc_only": [r for r in rows if r["cls"] == "trunc_only"
                                and int(r["edge_trunc"])],
            "top_cut":        [r for r in rows if int(r["cut_top"]) and not int(r["occl_kp"])],
        }

    G, GH = groups(real), groups(him)
    ORDER = ["whole_upright", "occl_or_trunc", "trunc_only", "crop_trunc_only",
             "edge_trunc_only", "top_cut", "occl_only", "trunc_and_occl",
             "no_keypoints", "clean_other"]

    # reference size mix: whole_upright inside the flown band
    ref = band(G["whole_upright"])
    W = {}
    for lo, hi in BINS:
        W[(lo, hi)] = sum(1 for r in ref if lo <= float(r["px128_h"]) < hi)
    P("=" * 96)
    P("0. THE REFERENCE SIZE MIX - every standardised number below is reported AT THIS MIX")
    P("=" * 96)
    P(f"  whole_upright inside the flown band ({FLOWN_LO:.1f}-{FLOWN_HI:.1f} px128_h), n = {len(ref)}")
    for k, v in W.items():
        P(f"    {k[0]:>3}-{k[1]:<3} px : weight {v}")
    P("  Bins with fewer than 3 photographs in a stratum are dropped from that")
    P("  stratum's standardised rate, and the surviving weights are renormalised.")
    P("")

    # ------------------------------------------------- 1. the raw size profile
    P("=" * 96)
    P("1. WHY THE BAND CUT IS NOT ENOUGH ON ITS OWN - the strata are different sizes")
    P("=" * 96)
    P(f"{'stratum':<18}{'n all':>8}{'n flown':>9}{'med px128_h':>13}{'p25':>8}{'p75':>8}"
      f"{'med crop_vis_frac':>20}")
    sp = [("stratum", "n_all", "n_flown_band", "med_px128_h", "p25_px128_h", "p75_px128_h",
           "med_crop_vis_frac", "frac_crop_trunc", "frac_edge_trunc", "frac_occl_kp")]
    for g in ORDER:
        rows = G[g]
        if not rows:
            continue
        b = band(rows)
        h = np.array([float(r["px128_h"]) for r in rows])
        cv = np.array([float(r["crop_vis_frac"]) for r in rows])
        P(f"{g:<18}{len(rows):>8}{len(b):>9}{np.median(h):>13.1f}"
          f"{np.percentile(h,25):>8.1f}{np.percentile(h,75):>8.1f}{np.median(cv):>20.3f}")
        sp.append((g, len(rows), len(b), f"{np.median(h):.2f}",
                   f"{np.percentile(h,25):.2f}", f"{np.percentile(h,75):.2f}",
                   f"{np.median(cv):.4f}",
                   f"{np.mean([int(r['crop_trunc']) for r in rows]):.4f}",
                   f"{np.mean([int(r['edge_trunc']) for r in rows]):.4f}",
                   f"{np.mean([int(r['occl_kp']) for r in rows]):.4f}"))
    with open(D / "tables/size_profile.tsv", "w", newline="") as f:
        csv.writer(f, delimiter="\t").writerows(sp)
    P("")
    P("  Truncated people are BIGGER in the frame - a photographer crops in close.")
    P("  So a raw band cut still leaves the strata unmatched; section 3 fixes that.")
    P("")

    # --------------------------------- 2. the flown band, unstandardised, raw n
    P("=" * 96)
    P("2. THE FLOWN BAND, band-cut only (38.8-103.6 px128_h). Resolution-matched chain.")
    P("=" * 96)
    tb = [("stratum", "chain", "arm", "n_photos", "n_rows", "median", "frac_ge_0.75",
           "ge_lo", "ge_hi", "frac_lt_0.45", "lt_lo", "lt_hi")]
    for chain, store, suffix in (("via244", G, "_via244"), ("himax", GH, "_via244")):
        P(f"  --- chain = {chain} " + "-" * 70)
        P(f"{'stratum':<18}{'arm':<7}{'n':>6}{'median':>9}"
          f"{'>=0.75':>9}{'95% CI':>18}{'<0.45':>9}{'95% CI':>18}")
        for g in ORDER:
            rows = band(store.get(g, []))
            if len(rows) < 5:
                continue
            for arm in ARMS:
                col = arm + suffix
                v = np.array([float(r[col]) for r in rows])
                f1, f1c = fge(v), cboot_rate(rows, col, fge)
                f2, f2c = flt(v), cboot_rate(rows, col, flt)
                P(f"{g:<18}{arm:<7}{nimg(rows):>6}{med(v):>9.3f}"
                  f"{f1:>9.3f}  [{f1c[0]:.3f},{f1c[1]:.3f}]"
                  f"{f2:>9.3f}  [{f2c[0]:.3f},{f2c[1]:.3f}]")
                tb.append((g, chain, arm, nimg(rows), len(rows), f"{med(v):.4f}",
                           f"{f1:.4f}", f"{f1c[0]:.4f}", f"{f1c[1]:.4f}",
                           f"{f2:.4f}", f"{f2c[0]:.4f}", f"{f2c[1]:.4f}"))
        P("")
    with open(D / "tables/flown_band.tsv", "w", newline="") as f:
        csv.writer(f, delimiter="\t").writerows(tb)

    # ------------------------------------------ 3. SIZE-STANDARDISED, the headline
    P("=" * 96)
    P("3. SIZE-STANDARDISED ONTO whole_upright'S OWN SIZE MIX - the headline comparison")
    P("=" * 96)
    P("  Every stratum re-weighted to the same px128_h mix, so 'at matched apparent")
    P("  size' is true by construction and not just by a band cut.")
    P("")
    ss = [("stratum", "chain", "arm", "n_photos", "std_frac_ge_0.75", "ge_lo", "ge_hi",
           "d_vs_whole_upright", "d_ge_lo", "d_ge_hi",
           "std_frac_lt_0.45", "lt_lo", "lt_hi",
           "d_exit_vs_whole_upright", "d_lt_lo", "d_lt_hi")]
    for chain, store, suffix in (("via244", G, "_via244"), ("himax", GH, "_via244")):
        P(f"  --- chain = {chain} " + "-" * 70)
        P(f"{'stratum':<18}{'arm':<7}{'n':>6}{'>=.75':>8}{'95% CI':>17}"
          f"{'d vs WU':>10}{'95% CI':>17}{'<.45':>8}{'95% CI':>17}"
          f"{'d vs WU':>10}{'95% CI':>17}")
        base = band(store["whole_upright"])
        for g in ORDER:
            rows = band(store.get(g, []))
            if len(rows) < 5:
                continue
            for arm in ARMS:
                col = arm + suffix
                a1 = standardised(rows, col, fge, W)
                a1c = cboot_std(rows, col, fge, W)
                a2 = standardised(rows, col, flt, W)
                a2c = cboot_std(rows, col, flt, W)
                if g == "whole_upright":
                    d1 = d2 = 0.0
                    d1c = d2c = (0.0, 0.0)
                else:
                    d1 = a1 - standardised(base, col, fge, W)
                    d1c = cboot_std_diff(rows, base, col, fge, W)
                    d2 = a2 - standardised(base, col, flt, W)
                    d2c = cboot_std_diff(rows, base, col, flt, W)
                P(f"{g:<18}{arm:<7}{nimg(rows):>6}{a1:>8.3f} [{a1c[0]:>6.3f},{a1c[1]:>6.3f}]"
                  f"{d1:>10.3f} [{d1c[0]:>6.3f},{d1c[1]:>6.3f}]"
                  f"{a2:>8.3f} [{a2c[0]:>6.3f},{a2c[1]:>6.3f}]"
                  f"{d2:>10.3f} [{d2c[0]:>6.3f},{d2c[1]:>6.3f}]")
                ss.append((g, chain, arm, nimg(rows), f"{a1:.4f}", f"{a1c[0]:.4f}",
                           f"{a1c[1]:.4f}", f"{d1:.4f}", f"{d1c[0]:.4f}", f"{d1c[1]:.4f}",
                           f"{a2:.4f}", f"{a2c[0]:.4f}", f"{a2c[1]:.4f}",
                           f"{d2:.4f}", f"{d2c[0]:.4f}", f"{d2c[1]:.4f}"))
        P("")
    with open(D / "tables/size_standardised.tsv", "w", newline="") as f:
        csv.writer(f, delimiter="\t").writerows(ss)

    # ------------------------------------------------------- 4. the hold band
    P("=" * 96)
    P(f"4. THE HOLD BAND ({HOLD_LO:.1f}-{HOLD_HI:.1f} px128_h = 1.55-2.45 m), band-cut only")
    P("=" * 96)
    hb = [("stratum", "chain", "arm", "n_photos", "n_rows", "median",
           "frac_ge_0.75", "ge_lo", "ge_hi", "frac_lt_0.45", "lt_lo", "lt_hi")]
    for chain, store, suffix in (("via244", G, "_via244"), ("himax", GH, "_via244")):
        P(f"  --- chain = {chain} " + "-" * 70)
        P(f"{'stratum':<18}{'arm':<7}{'n':>6}{'median':>9}{'>=0.75':>9}{'95% CI':>18}"
          f"{'<0.45':>9}{'95% CI':>18}")
        for g in ORDER:
            rows = band(store.get(g, []), HOLD_LO, HOLD_HI)
            if len(rows) < 5:
                continue
            for arm in ARMS:
                col = arm + suffix
                v = np.array([float(r[col]) for r in rows])
                f1c, f2c = cboot_rate(rows, col, fge), cboot_rate(rows, col, flt)
                P(f"{g:<18}{arm:<7}{nimg(rows):>6}{med(v):>9.3f}{fge(v):>9.3f}"
                  f"  [{f1c[0]:.3f},{f1c[1]:.3f}]{flt(v):>9.3f}  [{f2c[0]:.3f},{f2c[1]:.3f}]")
                hb.append((g, chain, arm, nimg(rows), len(rows), f"{med(v):.4f}",
                           f"{fge(v):.4f}", f"{f1c[0]:.4f}", f"{f1c[1]:.4f}",
                           f"{flt(v):.4f}", f"{f2c[0]:.4f}", f"{f2c[1]:.4f}"))
        P("")
    with open(D / "tables/hold_band.tsv", "w", newline="") as f:
        csv.writer(f, delimiter="\t").writerows(hb)

    # ------------------------- 5. detectability vs HOW MUCH of the body is in frame
    P("=" * 96)
    P("5. DETECTABILITY AS A FUNCTION OF HOW MUCH OF THE PERSON IS IN FRAME")
    P("=" * 96)
    P("  Two gradings, because COCO supports two different questions:")
    P("   crop_vis_frac  fraction of the bbox AREA surviving the CENTRE CROP - a")
    P("                  geometric cut by the same operation the firmware performs,")
    P("                  and the closest analogue here to a drone crop")
    P("   kp_vis_frac    fraction of the 17 keypoints marked v==2 (visible) - this")
    P("                  mixes truncation and occlusion and cannot separate them")
    P("  Flown band, chip arm, both chains. NOT size-standardised inside the grade")
    P("  bins (n does not allow it); the median px128_h of each bin is printed so a")
    P("  size confound is visible rather than hidden.")
    P("")
    gr = [("grading", "bin_lo", "bin_hi", "chain", "arm", "n_photos", "n_rows",
           "med_px128_h", "median", "frac_ge_0.75", "ge_lo", "ge_hi",
           "frac_lt_0.45", "lt_lo", "lt_hi")]
    for grading, edges in (("crop_vis_frac", [(0.0, 0.5), (0.5, 0.75), (0.75, 0.9),
                                              (0.9, 0.999), (0.999, 1.001)]),
                           ("kp_vis_frac", [(0.0, 0.2), (0.2, 0.4), (0.4, 0.6),
                                            (0.6, 0.8), (0.8, 1.001)])):
        for chain, store, suffix in (("via244", G, "_via244"), ("himax", GH, "_via244")):
            P(f"  --- {grading}, chain = {chain} " + "-" * 50)
            P(f"{'bin':<16}{'arm':<7}{'n':>6}{'med px':>9}{'median':>9}"
              f"{'>=0.75':>9}{'95% CI':>18}{'<0.45':>9}{'95% CI':>18}")
            allr = band([r for g in ORDER if g in ("whole_upright", "occl_or_trunc")
                         for r in store[g]])
            for lo, hi in edges:
                rows = [r for r in allr if lo <= float(r[grading]) < hi]
                if len(rows) < 5:
                    continue
                pxm = np.median([float(r["px128_h"]) for r in rows])
                for arm in ARMS:
                    col = arm + suffix
                    v = np.array([float(r[col]) for r in rows])
                    f1c, f2c = cboot_rate(rows, col, fge), cboot_rate(rows, col, flt)
                    lbl = f"{lo:.2f}-{hi:.2f}" if hi < 1.0 else f"{lo:.2f}-1.00"
                    P(f"{lbl:<16}{arm:<7}{nimg(rows):>6}{pxm:>9.1f}{med(v):>9.3f}"
                      f"{fge(v):>9.3f}  [{f1c[0]:.3f},{f1c[1]:.3f}]"
                      f"{flt(v):>9.3f}  [{f2c[0]:.3f},{f2c[1]:.3f}]")
                    gr.append((grading, f"{lo:.3f}", f"{hi:.3f}", chain, arm,
                               nimg(rows), len(rows), f"{pxm:.2f}", f"{med(v):.4f}",
                               f"{fge(v):.4f}", f"{f1c[0]:.4f}", f"{f1c[1]:.4f}",
                               f"{flt(v):.4f}", f"{f2c[0]:.4f}", f"{f2c[1]:.4f}"))
            P("")
    with open(D / "tables/visible_fraction.tsv", "w", newline="") as f:
        csv.writer(f, delimiter="\t").writerows(gr)

    (D / "tables/analysis.txt").write_text("\n".join(REPORT) + "\n")
    P(f"wrote tables/{{size_profile,flown_band,size_standardised,hold_band,"
      f"visible_fraction}}.tsv and analysis.txt")
    (D / "tables/analysis.txt").write_text("\n".join(REPORT) + "\n")


if __name__ == "__main__":
    main()
