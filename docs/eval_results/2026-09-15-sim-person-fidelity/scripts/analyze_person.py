#!/usr/bin/env python3
"""THE COMPARISON: champion confidence versus APPARENT SIZE, simulated person
against real person photographs, one arm at a time and ONE THRESHOLD at a time.

Everything is grouped by px128_h - the subject's height in the 128x128 tensor
the network sees - because that is the only variable that makes a sim range and
a COCO photograph comparable. No number here is ever compared against a number
measured at a different threshold, and every row carries the side, the network
arm, the camera, the resampling chain and the size bin it was measured under.

RESAMPLING. The real side is read from its `*_via244` columns on EVERY arm, so
both sides reach the network through the AI-deck frame's own 244-px chain. See
scripts/control_resolution.py, which proves that is a bit-exact no-op on the sim
side and measures what it moves on the real side. The raw-photograph columns are
carried in tables/size_response.tsv for comparison but are not the headline.

Inputs  tables/real_people.csv         2 693 photographs, 3 arms x 2 chains
        tables/real_people_himax.csv   the same photographs through himax_typical
        tables/sim_person.csv          600 frames, the s15 + s01 person cells
        tables/sim_cohort.csv          11 214 frames, 267 real people as cards
                                       (204 of them survive the final stratum)
Outputs tables/size_response.tsv, matched_gap.tsv, size_standardised.tsv,
        paired_render.tsv, camera_decomposition.tsv, exit_bar.tsv,
        same_image.tsv, analysis.txt, figures/*.png

Usage: nemoenv/bin/python analyze_person.py <dir>
"""
import csv
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from shared_arms import relabel  # noqa: E402

D = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
RNG = np.random.default_rng(0)
BINS = [(8, 15), (15, 25), (25, 40), (40, 55), (55, 80), (80, 129)]
BAR = 0.75            # follow_person.py --vis-enter, the confirmation bar
EXIT_BAR = 0.45       # follow_person.py --vis-exit, where the follower lets go
ARMS = ["float", "fq", "chip"]
# A 1.7 m person on the 0.8 m eye line: px128_h = 155.4 / range_m.
FLOWN_LO, FLOWN_HI = 155.36 / 4.0, 155.36 / 1.5      # 38.8 .. 103.6 px
SIM_SOURCE = "19432"
REPORT = []


def P(s=""):
    print(s, flush=True)
    REPORT.append(s)


def rd(p):
    return list(csv.DictReader(open(D / p)))


# ---------------------------------------------------------------- clustering
def _clusters(rows):
    """What counts as ONE independent observation.

    real photograph            -> the image (3 himax draws are one photograph)
    cohort render              -> the SUBJECT (a person contributes many poses
                                  and many ranges; the sampled unit is the
                                  person, not the frame)
    s15/s01 cell render        -> the POSE (job x range x lateral offset; the
                                  sensor seeds of one pose are one observation)
    """
    out = []
    for r in rows:
        if "file_name" in r:
            out.append("img" + r["img_id"])
        elif r.get("job") == "cohort":
            out.append("subj" + r["img_id"])
        else:
            out.append(f"{r['job']}|{r['range_m']}|{r['dy_m']}")
    return np.array(out)


def _cboot(v, c, stat, n):
    v, c = np.asarray(v, float), np.asarray(c)
    keys = np.unique(c)
    idx = {k: np.where(c == k)[0] for k in keys}
    out = np.empty(n)
    for i in range(n):
        pick = RNG.choice(keys, len(keys), replace=True)
        out[i] = stat(v[np.concatenate([idx[k] for k in pick])])
    return out


def boot_diff(ra, rb, arm_a, arm_b, stat, n=2000):
    """95% CI of stat(sim) - stat(real), cluster bootstrap on both sides."""
    a, b = vals(ra, arm_a), vals(rb, arm_b)
    ca, cb = _clusters(ra), _clusters(rb)
    if len(np.unique(ca)) < 2 or len(np.unique(cb)) < 2:
        return float("nan"), float("nan")
    d = _cboot(a, ca, stat, n) - _cboot(b, cb, stat, n)
    return float(np.percentile(d, 2.5)), float(np.percentile(d, 97.5))


def boot_paired(d_by_subject, stat, n=2000):
    """95% CI of a PAIRED statistic, resampling subjects."""
    d = np.asarray(d_by_subject, float)
    if len(d) < 2:
        return float("nan"), float("nan")
    out = np.array([stat(RNG.choice(d, len(d), replace=True)) for _ in range(n)])
    return float(np.percentile(out, 2.5)), float(np.percentile(out, 97.5))


def nclust(rows):
    return len(np.unique(_clusters(rows))) if rows else 0


def vals(rows, arm):
    return np.array([float(r[arm]) for r in rows], float)


def sel(rows, **kw):
    out = rows
    for k, v in kw.items():
        out = [r for r in out if r[k] == v] if isinstance(v, str) else [r for r in out if r[k] in v]
    return out


def in_bin(rows, lo, hi):
    return [r for r in rows if lo <= float(r["px128_h"]) < hi]


def in_band(rows, lo=FLOWN_LO, hi=FLOWN_HI):
    return [r for r in rows if lo <= float(r["px128_h"]) <= hi]


def med(v):
    return float(np.median(v)) if len(v) else float("nan")


def fge(v):
    return float(np.mean(np.asarray(v, float) >= BAR)) if len(v) else float("nan")


def flt(v):
    return float(np.mean(np.asarray(v, float) < EXIT_BAR)) if len(v) else float("nan")


def stats(v):
    v = np.asarray(v, float)
    if not len(v):
        return dict(n=0, med=np.nan, p25=np.nan, p75=np.nan, frac=np.nan, exit=np.nan)
    return dict(n=len(v), med=float(np.median(v)), p25=float(np.percentile(v, 25)),
                p75=float(np.percentile(v, 75)), frac=fge(v), exit=flt(v))


def main():
    real_all_rows = rd("tables/real_people.csv")
    by_img = {r["img_id"]: r for r in real_all_rows}
    real = [r for r in real_all_rows if r["is_sim_source"] != "1"]
    realh = [r for r in rd("tables/real_people_himax.csv") if r["is_sim_source"] != "1"]
    simc = rd("tables/sim_person.csv")
    # Stratum flags come from the real table, never from the render CSV's own
    # (stale) copy - see shared_arms.relabel.
    coh = [r for r in relabel(rd("tables/sim_cohort.csv"), by_img)
           if r["is_sim_source"] != "1"]

    # The real side is read resolution-matched on every arm. The himax real arm
    # is natively 244, so its plain column already is the matched one.
    RA = {"float": "float_via244", "fq": "fq_via244", "chip": "chip_via244"}
    HA = {"float": "float", "fq": "fq", "chip": "chip"}
    SA = {"float": "float", "fq": "fq", "chip": "chip"}

    groups_real = {
        "real_all": real,
        "real_whole_upright": [r for r in real if r["whole_upright"] == "1"],
        "real_wui": [r for r in real if r["wui"] == "1"],
        "real_occluded_or_truncated": [r for r in real if r["whole_upright"] != "1"],
    }
    groups_realh = {
        "realhimax_all": realh,
        "realhimax_whole_upright": [r for r in realh if r["whole_upright"] == "1"],
        "realhimax_wui": [r for r in realh if r["wui"] == "1"],
    }
    groups_sim = {
        "sim_cells_himax": sel(simc, camera="himax"),
        "sim_cells_clean": sel(simc, camera="clean"),
        # The cohort group is restricted to the CURRENT whole_upright stratum,
        # so that "267 people rendered" and "the real whole_upright photographs"
        # are the same people. 62 of the 266 rendered subjects fell out when the
        # centre-crop rule was tightened; they are rendered but not compared.
        "sim_cohort_himax": [r for r in coh if r["camera"] == "himax" and r["whole_upright"] == "1"],
        "sim_cohort_clean": [r for r in coh if r["camera"] == "clean" and r["whole_upright"] == "1"],
        "sim_cohort_wui_himax": [r for r in coh if r["camera"] == "himax" and r["wui"] == "1"],
    }

    P("=" * 78)
    P("0. WHAT IS IN EACH SET")
    P("=" * 78)
    P(f"{'group':<32}{'rows':>8}{'clusters':>10}{'px128_h min..med..max':>30}")
    for name, g in list(groups_real.items()) + list(groups_realh.items()) + list(groups_sim.items()):
        p = np.array([float(r["px128_h"]) for r in g]) if g else np.array([np.nan])
        P(f"{name:<32}{len(g):>8}{nclust(g):>10}"
          f"{f'{p.min():.1f} .. {np.median(p):.1f} .. {p.max():.1f}':>30}")
    P("")
    P(f"The flown band for a 1.7 m person on the 0.8 m eye line is "
      f"{FLOWN_LO:.1f}-{FLOWN_HI:.1f} px128_h (4.0 m .. 1.5 m).")
    P("Unlike the pet study, the sim person is NOT size-capped: it reaches 120 px")
    P("at 1.30 m, past the whole real distribution's median, so sim and real")
    P("overlap over the whole flown band and beyond.")
    P("")

    # ------------------------------------------------------- 1. size response
    P("=" * 78)
    P("1. CONFIDENCE VERSUS APPARENT SIZE   median [frac >= 0.75] (frac < 0.45)  n")
    P("=" * 78)
    tsv = [("group", "arm", "chain", "bin_lo", "bin_hi", "n", "n_clusters", "median",
            "p25", "p75", "frac_ge_075", "frac_lt_045")]
    for arm in ARMS:
        P(f"--- {arm} arm, real side via244, sim side himax " + "-" * 24)
        P(f"{'px128_h':<12}" + "".join(f"{k:>26}" for k in
                                       ("real all", "real whole_upright", "real wui", "SIM cells", "SIM cohort")))
        for lo, hi in BINS:
            cells = []
            for name, g, col in (("real_all", groups_real["real_all"], RA[arm]),
                                 ("real_whole_upright", groups_real["real_whole_upright"], RA[arm]),
                                 ("real_wui", groups_real["real_wui"], RA[arm]),
                                 ("sim_cells_himax", groups_sim["sim_cells_himax"], SA[arm]),
                                 ("sim_cohort_himax", groups_sim["sim_cohort_himax"], SA[arm])):
                sub = in_bin(g, lo, hi)
                s = stats(vals(sub, col)) if sub else stats([])
                cells.append(f"{s['med']:.2f} [{s['frac']:.2f}] ({s['exit']:.2f}) n={s['n']}"
                             if s["n"] else "-")
                tsv.append((name, arm, "via244" if "real" in name else "native",
                            lo, hi, s["n"], nclust(sub),
                            f"{s['med']:.4f}", f"{s['p25']:.4f}", f"{s['p75']:.4f}",
                            f"{s['frac']:.4f}", f"{s['exit']:.4f}"))
            P(f"{f'{lo}-{hi}':<12}" + "".join(f"{c:>26}" for c in cells))
        P("")
    # also record the raw-photograph chain, and the himax real arm
    for arm in ARMS:
        for name, g, col, chain in (("real_all", groups_real["real_all"], arm, "raw"),
                                    ("real_whole_upright", groups_real["real_whole_upright"], arm, "raw"),
                                    ("real_wui", groups_real["real_wui"], arm, "raw"),
                                    ("realhimax_all", groups_realh["realhimax_all"], HA[arm], "himax244"),
                                    ("realhimax_whole_upright", groups_realh["realhimax_whole_upright"], HA[arm], "himax244"),
                                    ("realhimax_wui", groups_realh["realhimax_wui"], HA[arm], "himax244"),
                                    ("real_occluded_or_truncated", groups_real["real_occluded_or_truncated"], RA[arm], "via244"),
                                    ("sim_cells_clean", groups_sim["sim_cells_clean"], SA[arm], "native"),
                                    ("sim_cohort_clean", groups_sim["sim_cohort_clean"], SA[arm], "native"),
                                    ("sim_cohort_wui_himax", groups_sim["sim_cohort_wui_himax"], SA[arm], "native")):
            for lo, hi in BINS:
                sub = in_bin(g, lo, hi)
                s = stats(vals(sub, col)) if sub else stats([])
                tsv.append((name, arm, chain, lo, hi, s["n"], nclust(sub),
                            f"{s['med']:.4f}", f"{s['p25']:.4f}", f"{s['p75']:.4f}",
                            f"{s['frac']:.4f}", f"{s['exit']:.4f}"))
    with open(D / "tables/size_response.tsv", "w", newline="") as f:
        csv.writer(f, delimiter="\t").writerows(tsv)

    # --------------------------------------------- 2. matched-size gap + CIs
    P("=" * 78)
    P("2. MATCHED-SIZE GAP: sim minus real, 95% cluster bootstrap")
    P("=" * 78)
    P("d_median  sim median confidence minus real median confidence")
    P("d_frac    sim fraction >= 0.75 minus real fraction >= 0.75  (the follow bar)")
    P("d_exit    sim fraction  < 0.45 minus real fraction  < 0.45  (the let-go bar)")
    P("A NEGATIVE d_frac or a POSITIVE d_exit means the simulator UNDERSTATES how")
    P("hard a real person is to hold - the dangerous direction.")
    P("")
    gap = [("sim_group", "real_group", "arm", "bin_lo", "bin_hi", "n_sim", "nc_sim",
            "n_real", "nc_real", "sim_median", "real_median", "d_median", "dm_lo", "dm_hi",
            "sim_frac", "real_frac", "d_frac", "df_lo", "df_hi",
            "sim_exit", "real_exit", "d_exit", "de_lo", "de_hi")]
    PAIRS = [
        ("sim_cells_himax", "real_all", RA),
        ("sim_cells_himax", "real_whole_upright", RA),
        ("sim_cells_himax", "real_wui", RA),
        ("sim_cells_himax", "realhimax_whole_upright", HA),
        ("sim_cohort_himax", "real_whole_upright", RA),
        ("sim_cohort_wui_himax", "real_wui", RA),
        ("sim_cohort_himax", "realhimax_whole_upright", HA),
    ]
    allg = {**groups_real, **groups_realh, **groups_sim}
    for sname, rname, colmap in PAIRS:
        P(f"--- {sname}  vs  {rname} " + "-" * max(0, 40 - len(sname) - len(rname)))
        P(f"{'arm':<7}{'bin':<10}{'n sim/real':<14}{'d_median':>26}{'d_frac':>26}{'d_exit':>26}")
        for arm in ARMS:
            for lo, hi in BINS:
                sa, rb = in_bin(allg[sname], lo, hi), in_bin(allg[rname], lo, hi)
                if len(sa) < 3 or len(rb) < 3:
                    continue
                scol, rcol = SA[arm], colmap[arm]
                sv, rv = vals(sa, scol), vals(rb, rcol)
                dm, df, de = med(sv) - med(rv), fge(sv) - fge(rv), flt(sv) - flt(rv)
                mlo, mhi = boot_diff(sa, rb, scol, rcol, np.median)
                flo, fhi = boot_diff(sa, rb, scol, rcol, fge)
                elo, ehi = boot_diff(sa, rb, scol, rcol, flt)
                P(f"{arm:<7}{f'{lo}-{hi}':<10}{f'{len(sa)}/{len(rb)}':<14}"
                  f"{f'{dm:+.3f} [{mlo:+.3f},{mhi:+.3f}]':>26}"
                  f"{f'{df:+.3f} [{flo:+.3f},{fhi:+.3f}]':>26}"
                  f"{f'{de:+.3f} [{elo:+.3f},{ehi:+.3f}]':>26}")
                gap.append((sname, rname, arm, lo, hi, len(sa), nclust(sa), len(rb), nclust(rb),
                            f"{med(sv):.4f}", f"{med(rv):.4f}", f"{dm:+.4f}", f"{mlo:+.4f}", f"{mhi:+.4f}",
                            f"{fge(sv):.4f}", f"{fge(rv):.4f}", f"{df:+.4f}", f"{flo:+.4f}", f"{fhi:+.4f}",
                            f"{flt(sv):.4f}", f"{flt(rv):.4f}", f"{de:+.4f}", f"{elo:+.4f}", f"{ehi:+.4f}"))
        P("")
    with open(D / "tables/matched_gap.tsv", "w", newline="") as f:
        csv.writer(f, delimiter="\t").writerows(gap)

    # --------------------------------------------------- 3. PAIRED rendering
    P("=" * 78)
    P("3. THE PAIRED TEST: the SAME person, as a photograph and as a card")
    P("=" * 78)
    P(f"{len(groups_real['real_whole_upright'])} whole/upright/untruncated people (of 267 rendered; "
      f"the rest fell out when the")
    P("centre-crop rule was tightened), each rendered at the range where the")
    P("card subtends exactly what that person subtends in their own photograph's")
    P("centre crop (`is_r_match`). Identity, pose, clothing and apparent size are")
    P("held fixed; what is left is the simulator. Paired difference, render minus")
    P("photograph, bootstrap over SUBJECTS.")
    P("")
    photo_by = {r["img_id"]: r for r in real}
    pr = [("arm", "camera", "stratum", "n_subjects", "median_d", "d_lo", "d_hi",
           "photo_frac_ge075", "render_frac_ge075", "d_frac", "df_lo", "df_hi",
           "photo_frac_lt045", "render_frac_lt045", "d_exit", "de_lo", "de_hi",
           "n_render_higher", "median_px_photo", "median_px_render")]
    for cam in ("himax", "clean"):
        for stratum in ("whole_upright", "wui"):
            for arm in ARMS:
                ds, pf, rf, pe, re_, pxp, pxr = [], [], [], [], [], [], []
                for iid, g in _by(coh, "img_id"):
                    rows = [r for r in g if r["is_r_match"] == "1" and r["camera"] == cam
                            and r["dy_m"] == "0.0" and r[stratum] == "1"]
                    if not rows or iid not in photo_by:
                        continue
                    rv = float(np.mean(vals(rows, SA[arm])))
                    pv = float(photo_by[iid][RA[arm]])
                    ds.append(rv - pv)
                    rf.append(rv >= BAR); pf.append(pv >= BAR)
                    re_.append(rv < EXIT_BAR); pe.append(pv < EXIT_BAR)
                    pxp.append(float(photo_by[iid]["px128_h"]))
                    pxr.append(float(np.mean([float(r["px128_h"]) for r in rows])))
                if len(ds) < 3:
                    continue
                lo, hi = boot_paired(ds, np.median)
                dfrac = np.mean(rf) - np.mean(pf)
                dex = np.mean(re_) - np.mean(pe)
                flo, fhi = boot_paired(np.array(rf, float) - np.array(pf, float), np.mean)
                elo, ehi = boot_paired(np.array(re_, float) - np.array(pe, float), np.mean)
                pr.append((arm, cam, stratum, len(ds), f"{np.median(ds):+.4f}", f"{lo:+.4f}", f"{hi:+.4f}",
                           f"{np.mean(pf):.4f}", f"{np.mean(rf):.4f}", f"{dfrac:+.4f}", f"{flo:+.4f}", f"{fhi:+.4f}",
                           f"{np.mean(pe):.4f}", f"{np.mean(re_):.4f}", f"{dex:+.4f}", f"{elo:+.4f}", f"{ehi:+.4f}",
                           int(np.sum(np.array(ds) > 0)), f"{np.median(pxp):.1f}", f"{np.median(pxr):.1f}"))
                if cam == "himax":
                    P(f"{arm:<6}{stratum:<15}n={len(ds):<5}"
                      f"median d {np.median(ds):+.3f} [{lo:+.3f},{hi:+.3f}]   "
                      f">=0.75 photo {np.mean(pf):.3f} -> render {np.mean(rf):.3f} "
                      f"({dfrac:+.3f} [{flo:+.3f},{fhi:+.3f}])   "
                      f"<0.45 {np.mean(pe):.3f} -> {np.mean(re_):.3f} ({dex:+.3f})")
        P("")
    with open(D / "tables/paired_render.tsv", "w", newline="") as f:
        csv.writer(f, delimiter="\t").writerows(pr)

    # ------------------------------------------------ 4. size standardisation
    P("=" * 78)
    P("4. SIZE-STANDARDISED OVER THE FLOWN BAND")
    P("=" * 78)
    P("The sim's own size mix is applied to the real photographs, so neither side")
    P("can win on its size distribution. Flown band only "
      f"({FLOWN_LO:.1f}-{FLOWN_HI:.1f} px).")
    P("")
    ss = [("sim_group", "real_group", "arm", "metric", "sim", "real_standardised",
           "ratio", "bins", "n_sim_frames", "n_real_photos")]
    P(f"{'sim':<24}{'real':<28}{'arm':<7}{'sim>=.75':>10}{'real>=.75':>11}{'ratio':>8}"
      f"{'sim<.45':>9}{'real<.45':>10}{'ratio':>8}")
    for sname in ("sim_cells_himax", "sim_cohort_himax", "sim_cohort_wui_himax"):
        for rname, colmap in (("real_all", RA), ("real_whole_upright", RA),
                              ("real_wui", RA), ("realhimax_whole_upright", HA)):
            for arm in ARMS:
                S = in_band(allg[sname])
                R = in_band(allg[rname])
                wsum = fsum = esum = rfsum = resum = 0.0
                used, nreal = [], 0
                for lo, hi in BINS:
                    sb, rb = in_bin(S, lo, hi), in_bin(R, lo, hi)
                    if len(sb) < 3 or len(rb) < 3:
                        continue
                    w = len(sb)
                    wsum += w
                    fsum += w * fge(vals(sb, SA[arm])); esum += w * flt(vals(sb, SA[arm]))
                    rfsum += w * fge(vals(rb, colmap[arm])); resum += w * flt(vals(rb, colmap[arm]))
                    used.append(f"{lo}-{hi}"); nreal += len(rb)
                if wsum == 0:
                    continue
                sf, rfr = fsum / wsum, rfsum / wsum
                se, ree = esum / wsum, resum / wsum
                ratio_f = sf / rfr if rfr > 0 else float("inf")
                ratio_e = se / ree if ree > 0 else float("inf")
                P(f"{sname:<24}{rname:<28}{arm:<7}{sf:>10.3f}{rfr:>11.3f}{ratio_f:>8.2f}"
                  f"{se:>9.3f}{ree:>10.3f}{ratio_e:>8.2f}")
                ss.append((sname, rname, arm, "frac_ge_0.75", f"{sf:.4f}", f"{rfr:.4f}",
                           f"{ratio_f:.3f}", ";".join(used), int(wsum), nreal))
                ss.append((sname, rname, arm, "frac_lt_0.45", f"{se:.4f}", f"{ree:.4f}",
                           f"{ratio_e:.3f}", ";".join(used), int(wsum), nreal))
        P("")
    with open(D / "tables/size_standardised.tsv", "w", newline="") as f:
        csv.writer(f, delimiter="\t").writerows(ss)

    # -------------------------------------------------- 4b. the hold band
    P("=" * 78)
    P("4b. THE HOLD BAND - the sizes the follower actually spends its time at")
    P("=" * 78)
    P("The four person cells of the 0.75 baseline settle at 1.55-2.45 m from the")
    P("person (`M7_dist_err_settled`, target 1.94 m; per-cell means 1.63 / 1.74 /")
    P("1.87 / 2.00 / 2.19 / 2.44, repeat range 1.55-2.44). For a 1.7 m person that")
    P("is px128_h 63.4-100.2.")
    P("")
    P("The pet study's correction 0a.3: an AND of a range filter and a size filter")
    P("is not one band named twice. Both cuts are given. The SIZE cut is the one")
    P("that is matched to the real side; the range cut is the sim's own geometry.")
    P("")
    HOLD_LO, HOLD_HI = 155.36 / 2.45, 155.36 / 1.55
    hb = [("group", "cut", "arm", "n", "n_clusters", "median", "frac_ge_075", "frac_lt_045")]
    P(f"{'group':<30}{'cut':<22}{'arm':<7}{'n':>6}{'median':>9}{'>=0.75':>9}{'<0.45':>8}")
    for name, g, colmap in (("real_all", groups_real["real_all"], RA),
                            ("real_whole_upright", groups_real["real_whole_upright"], RA),
                            ("real_wui", groups_real["real_wui"], RA),
                            ("realhimax_whole_upright", groups_realh["realhimax_whole_upright"], HA),
                            ("sim_cells_himax", groups_sim["sim_cells_himax"], SA),
                            ("sim_cohort_himax", groups_sim["sim_cohort_himax"], SA)):
        cuts = [("size 63.4-100.2 px", in_band(g, HOLD_LO, HOLD_HI))]
        if "sim" in name:
            cuts.append(("range 1.55-2.45 m", [r for r in g if 1.55 <= float(r["range_m"]) <= 2.45]))
            cuts.append(("range AND size", [r for r in g if 1.55 <= float(r["range_m"]) <= 2.45
                                            and HOLD_LO <= float(r["px128_h"]) <= HOLD_HI]))
        for cut, sub in cuts:
            if len(sub) < 3:
                continue
            for arm in ARMS:
                v = vals(sub, colmap[arm])
                P(f"{name:<30}{cut:<22}{arm:<7}{len(sub):>6}{med(v):>9.3f}{fge(v):>9.3f}{flt(v):>8.3f}")
                hb.append((name, cut, arm, len(sub), nclust(sub),
                           f"{med(v):.4f}", f"{fge(v):.4f}", f"{flt(v):.4f}"))
        P("")
    with open(D / "tables/hold_band.tsv", "w", newline="") as f:
        csv.writer(f, delimiter="\t").writerows(hb)

    # --------------------------------------------- 5. camera decomposition
    P("=" * 78)
    P("5. IS IT THE CAMERA MODEL? raw photo -> +244 resample -> +resample+sensor")
    P("=" * 78)
    P("The pet study's correction 0a.2: the himax real arm resizes to 244 BEFORE")
    P("the sensor model, so it carries resampling AND sensor. Split, on the same")
    P("photographs, flown band only.")
    P("")
    cd = [("arm", "stratum", "metric", "raw", "plus_244", "plus_244_sensor",
           "resample_part", "sensor_part", "n_photos")]
    himax_by = {}
    for r in realh:
        himax_by.setdefault(r["img_id"], []).append(r)
    P(f"{'arm':<7}{'stratum':<16}{'metric':<14}{'raw':>8}{'+244':>8}{'+244+sens':>11}"
      f"{'resample':>10}{'sensor':>9}{'n':>6}")
    for arm in ARMS:
        for stratum, keep in (("all", lambda r: True),
                              ("whole_upright", lambda r: r["whole_upright"] == "1"),
                              ("wui", lambda r: r["wui"] == "1")):
            base = [r for r in in_band(real) if keep(r)]
            ids = {r["img_id"] for r in base}
            hh = [r for r in in_band(realh) if r["img_id"] in ids]
            if len(base) < 5 or len(hh) < 5:
                continue
            for metric, fn in (("frac_ge_0.75", fge), ("frac_lt_0.45", flt), ("median", med)):
                a = fn(vals(base, arm))
                b = fn(vals(base, RA[arm]))
                c = fn(vals(hh, HA[arm]))
                P(f"{arm:<7}{stratum:<16}{metric:<14}{a:>8.3f}{b:>8.3f}{c:>11.3f}"
                  f"{b - a:>+10.3f}{c - b:>+9.3f}{len(base):>6}")
                cd.append((arm, stratum, metric, f"{a:.4f}", f"{b:.4f}", f"{c:.4f}",
                           f"{b - a:+.4f}", f"{c - b:+.4f}", len(base)))
        P("")
    with open(D / "tables/camera_decomposition.tsv", "w", newline="") as f:
        csv.writer(f, delimiter="\t").writerows(cd)

    # --------------------------------------------------- 6. the exit bar
    P("=" * 78)
    P("6. THE EXIT BAR: how often each side falls below 0.45")
    P("=" * 78)
    P("Below 0.45 the follower drops the track. This is the number that decides")
    P("whether the drone lets go of someone it was following.")
    P("")
    eb = [("group", "arm", "band", "n", "n_clusters", "frac_lt_045", "median")]
    P(f"{'group':<30}{'arm':<7}{'n':>7}{'frac < 0.45':>13}{'median':>9}")
    for name, g, colmap in (("real_all", groups_real["real_all"], RA),
                            ("real_whole_upright", groups_real["real_whole_upright"], RA),
                            ("real_wui", groups_real["real_wui"], RA),
                            ("real_occluded_or_truncated", groups_real["real_occluded_or_truncated"], RA),
                            ("realhimax_whole_upright", groups_realh["realhimax_whole_upright"], HA),
                            ("sim_cells_himax", groups_sim["sim_cells_himax"], SA),
                            ("sim_cohort_himax", groups_sim["sim_cohort_himax"], SA),
                            ("sim_cohort_wui_himax", groups_sim["sim_cohort_wui_himax"], SA)):
        b = in_band(g)
        for arm in ARMS:
            v = vals(b, colmap[arm])
            P(f"{name:<30}{arm:<7}{len(b):>7}{flt(v):>13.3f}{med(v):>9.3f}")
            eb.append((name, arm, f"{FLOWN_LO:.1f}-{FLOWN_HI:.1f}", len(b), nclust(b),
                       f"{flt(v):.4f}", f"{med(v):.4f}"))
        P("")
    with open(D / "tables/exit_bar.tsv", "w", newline="") as f:
        csv.writer(f, delimiter="\t").writerows(eb)

    # ------------------------------------------------- 7. the same image
    P("=" * 78)
    P("7. THE SIM'S OWN PERSON, BOTH WAYS (COCO 19432 / ann 428692)")
    P("=" * 78)
    src = [r for r in rd("tables/real_people.csv") if r["is_sim_source"] == "1"][0]
    P(f"the photograph subtends px128_h = {src['px128_h']} in its own centre crop;")
    P("the flown eye line reaches that size at r = 1.44 m, INSIDE the band the")
    P("drone flies - so this pair needs no padding and no invented surround, which")
    P("is exactly what the pet study could not do for its dog (51.9 px cap).")
    P("")
    si = [("arm", "camera", "range_m", "dy_m", "px128_h_render", "px128_h_photo",
           "photo", "render", "d")]
    P(f"{'arm':<7}{'camera':<8}{'photo':>9}{'render':>9}{'d':>9}   (render at r=1.44, dy=0)")
    for cam in ("clean", "himax"):
        for arm in ARMS:
            rr = [r for r in simc if r["camera"] == cam and r["range_m"] == "1.44"
                  and r["dy_m"] == "0.0" and r["job"] == "person_s15"]
            if not rr:
                continue
            rv = float(np.mean(vals(rr, SA[arm])))
            pv = float(src[RA[arm]]) if cam == "clean" else None
            if cam == "himax":
                hh = [r for r in rd("tables/real_people_himax.csv") if r["is_sim_source"] == "1"]
                pv = float(np.mean(vals(hh, HA[arm]))) if hh else float("nan")
            P(f"{arm:<7}{cam:<8}{pv:>9.3f}{rv:>9.3f}{rv - pv:>+9.3f}")
            si.append((arm, cam, 1.44, 0.0, rr[0]["px128_h"], src["px128_h"],
                       f"{pv:.4f}", f"{rv:.4f}", f"{rv - pv:+.4f}"))
        P("")
    with open(D / "tables/same_image.tsv", "w", newline="") as f:
        csv.writer(f, delimiter="\t").writerows(si)

    (D / "tables/analysis.txt").write_text("\n".join(REPORT) + "\n")
    P("wrote tables/*.tsv and tables/analysis.txt")


def _by(rows, key):
    out = {}
    for r in rows:
        out.setdefault(r[key], []).append(r)
    return sorted(out.items())


if __name__ == "__main__":
    main()
