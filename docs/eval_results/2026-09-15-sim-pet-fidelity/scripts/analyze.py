#!/usr/bin/env python3
"""THE COMPARISON: champion confidence versus APPARENT SIZE, simulated pet
against real pet photographs, one arm at a time and one threshold at a time.

Everything here is grouped by px128_h - the subject's height in the 128x128
tensor the network sees - because that is the only variable that makes a sim
range and a COCO photograph comparable. Nothing in this file ever compares a
number measured at one threshold against a number measured at another, and
every row carries the side, the network arm, the camera and the size bin it was
measured under.

Inputs  tables/real_pets.csv        771 raw photographs (the confuser slice)
        tables/real_pets_himax.csv  the dog/cat photographs through himax_typical
        tables/sim_pets.csv         1116 rendered frames
Outputs tables/size_response.tsv, tables/matched_gap.tsv, tables/same_image.tsv,
        tables/analysis.txt, figures/*.png

Usage: nemoenv/bin/python analyze.py <dir>
"""
import csv
import sys
from pathlib import Path

import numpy as np

D = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
RNG = np.random.default_rng(0)
BINS = [(8, 15), (15, 25), (25, 40), (40, 55), (55, 80), (80, 129)]
BAR = 0.75          # the shipped confirmation bar (follow_person.py --vis-enter)
ARMS = ["float", "fq", "chip"]
REPORT = []


def P(s=""):
    print(s, flush=True)
    REPORT.append(s)


def rd(p):
    return list(csv.DictReader(open(D / p)))


def stats(v, bar=BAR):
    v = np.asarray(v, float)
    if len(v) == 0:
        return dict(n=0, med=float("nan"), p25=float("nan"), p75=float("nan"),
                    frac=float("nan"), mean=float("nan"))
    return dict(n=len(v), med=float(np.median(v)), p25=float(np.percentile(v, 25)),
                p75=float(np.percentile(v, 75)), frac=float(np.mean(v >= bar)),
                mean=float(v.mean()))


def _clusters(rows):
    """What counts as one independent observation. A real photograph scored
    under 3 himax draws is ONE photograph, not three; a rendered pose scored
    under 3 sensor seeds is ONE pose, not three. Resampling rows instead of
    clusters would make every interval here too narrow."""
    out = []
    for r in rows:
        if "img_id" in r:
            out.append(f"img{r['img_id']}")
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


def boot_diff(ra, rb, arm, stat, n=2000):
    """95% CI of stat(sim) - stat(real), cluster bootstrap on both sides."""
    a, b = vals(ra, arm), vals(rb, arm)
    ca, cb = _clusters(ra), _clusters(rb)
    if len(np.unique(ca)) < 2 or len(np.unique(cb)) < 2:
        return float("nan"), float("nan")
    d = _cboot(a, ca, stat, n) - _cboot(b, cb, stat, n)
    return float(np.percentile(d, 2.5)), float(np.percentile(d, 97.5))


def nclust(rows):
    return len(np.unique(_clusters(rows))) if rows else 0


def sel(rows, **kw):
    out = rows
    for k, v in kw.items():
        out = [r for r in out if r[k] == v] if isinstance(v, str) else [r for r in out if r[k] in v]
    return out


def vals(rows, arm):
    return np.array([float(r[arm]) for r in rows])


def px(rows):
    return np.array([float(r["px128_h"]) for r in rows])


def in_bin(rows, lo, hi):
    return [r for r in rows if lo <= float(r["px128_h"]) < hi]


def main():
    real = rd("tables/real_pets.csv")
    realh = rd("tables/real_pets_himax.csv")
    sim = rd("tables/sim_pets.csv")

    groups = {
        "real_raw_allpets": real,
        "real_raw_dog": sel(real, subject_cat="dog"),
        "real_raw_cat": sel(real, subject_cat="cat"),
        "real_himax_dog": sel(realh, subject_cat="dog"),
        "real_himax_cat": sel(realh, subject_cat="cat"),
        # the eye-line groups are restricted to the band the drone actually flies
        "sim_dog_eye_clean": sel(sim, job="dog_eye", camera="clean", in_flight_band="1"),
        "sim_dog_eye_himax": sel(sim, job="dog_eye", camera="himax", in_flight_band="1"),
        "sim_dog_petlevel_clean": sel(sim, job="dog_petlevel", camera="clean"),
        "sim_dog_petlevel_himax": sel(sim, job="dog_petlevel", camera="himax"),
        "sim_cat_eye_clean": sel(sim, job="cat_eye", camera="clean", in_flight_band="1"),
        "sim_cat_eye_himax": sel(sim, job="cat_eye", camera="himax", in_flight_band="1"),
        "sim_cat_petlevel_clean": sel(sim, job="cat_petlevel", camera="clean"),
        "sim_cat_petlevel_himax": sel(sim, job="cat_petlevel", camera="himax"),
    }

    # ---------------------------------------------------------------- 0. sizes
    P("=" * 78)
    P("0. WHAT APPARENT SIZES EACH SIDE ACTUALLY COVERS  (px128_h = subject height")
    P("   in the 128x128 network input; the full input is 128 px)")
    P("=" * 78)
    P(f"{'group':26s} {'n':>5s} {'min':>6s} {'p25':>6s} {'median':>7s} {'p75':>6s} {'max':>6s}")
    for g, rows in groups.items():
        p = px(rows)
        if len(p) == 0:
            continue
        P(f"{g:26s} {len(p):5d} {p.min():6.1f} {np.percentile(p,25):6.1f} "
          f"{np.median(p):7.1f} {np.percentile(p,75):6.1f} {p.max():6.1f}")
    dog_eye = groups["sim_dog_eye_himax"]
    P("")
    P("The flown geometry caps the sim pet's apparent size: the camera flies at "
      "0.8 m\nlooking level, the pet stands on the floor, so closing in pushes it out of "
      "the\nbottom of the frame. Largest px128_h reachable on the eye line: "
      f"dog {px(groups['sim_dog_eye_himax']).max():.1f}, "
      f"cat {px(groups['sim_cat_eye_himax']).max():.1f}.")
    P(f"Real photographs of the same two animals: dog median "
      f"{np.median(px(groups['real_raw_dog'])):.1f}, cat median "
      f"{np.median(px(groups['real_raw_cat'])):.1f} px128_h.")

    # ------------------------------------------------- 1. size response tables
    rows_out = []
    P("")
    P("=" * 78)
    P("1. CONFIDENCE VS APPARENT SIZE, per arm.  med [p25-p75], and the fraction")
    P(f"   at or above the shipped {BAR:.2f} confirmation bar.  n in brackets.")
    P("=" * 78)
    for arm in ARMS:
        P(f"\n--- arm = {arm} " + "-" * 60)
        P(f"{'px128_h bin':>12s} " + " ".join(f"{g.replace('_',' '):>24s}" for g in
                                              ["real_raw_allpets", "real_raw_dog", "sim_dog_eye_himax"]))
        for lo, hi in BINS:
            cells = []
            for g in ["real_raw_allpets", "real_raw_dog", "sim_dog_eye_himax"]:
                s = stats(vals(in_bin(groups[g], lo, hi), arm))
                cells.append(f"{s['med']:.2f}[{s['frac']:.2f}]n={s['n']}" if s["n"] else "-")
            P(f"{lo:5d}-{hi:<6d} " + " ".join(f"{c:>24s}" for c in cells))
        for g, rows in groups.items():
            for lo, hi in BINS:
                s = stats(vals(in_bin(rows, lo, hi), arm))
                rows_out.append({"arm": arm, "group": g, "bin_lo": lo, "bin_hi": hi, **{
                    k: (round(v, 4) if isinstance(v, float) else v) for k, v in s.items()}})
    with open(D / "tables/size_response.tsv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows_out[0].keys()), delimiter="\t")
        w.writeheader()
        w.writerows(rows_out)

    # ------------------------------------------------------- 2. matched gaps
    P("")
    P("=" * 78)
    P("2. THE MATCHED-SIZE GAP.  sim minus real, in the bins where the FLOWN sim")
    P("   geometry and real photographs overlap.  [95% bootstrap CI]")
    P("=" * 78)
    gap_rows = []
    pairs = [("sim_dog_eye_himax", "real_himax_dog", "dog, himax both sides"),
             ("sim_dog_eye_himax", "real_raw_dog", "dog, sim himax vs raw photo"),
             ("sim_dog_eye_clean", "real_raw_dog", "dog, sim clean vs raw photo"),
             ("sim_dog_eye_himax", "real_raw_allpets", "dog vs all pets, sim himax vs raw"),
             ("sim_cat_eye_himax", "real_himax_cat", "cat, himax both sides"),
             ("sim_cat_eye_himax", "real_raw_cat", "cat, sim himax vs raw photo")]
    for arm in ARMS:
        P(f"\n--- arm = {arm} " + "-" * 60)
        for sg, rg, label in pairs:
            P(f"  {label}")
            P(f"  {'bin':>12s} {'n sim':>6s} {'n real':>6s} {'med sim':>8s} {'med real':>9s} "
              f"{'d median':>20s} {'>=bar sim':>10s} {'>=bar real':>11s} {'d frac':>20s}")
            per_bin_med, per_bin_frac = [], []
            for lo, hi in BINS:
                ra, rb = in_bin(groups[sg], lo, hi), in_bin(groups[rg], lo, hi)
                a, b = vals(ra, arm), vals(rb, arm)
                if len(a) == 0 or nclust(rb) < 3:
                    continue
                sa, sb = stats(a), stats(b)
                dm = sa["med"] - sb["med"]
                lo_m, hi_m = boot_diff(ra, rb, arm, np.median)
                df = sa["frac"] - sb["frac"]
                lo_f, hi_f = boot_diff(ra, rb, arm, lambda x: float(np.mean(x >= BAR)))
                per_bin_med.append(dm)
                per_bin_frac.append(df)
                P(f"  {lo:5d}-{hi:<6d} {nclust(ra):6d} {nclust(rb):6d} {sa['med']:8.3f} {sb['med']:9.3f} "
                  f"{dm:+8.3f} [{lo_m:+.3f},{hi_m:+.3f}] {sa['frac']:10.3f} {sb['frac']:11.3f} "
                  f"{df:+8.3f} [{lo_f:+.3f},{hi_f:+.3f}]")
                gap_rows.append({"arm": arm, "sim_group": sg, "real_group": rg,
                                 "bin_lo": lo, "bin_hi": hi,
                                 "n_sim_frames": sa["n"], "n_real_rows": sb["n"],
                                 "n_sim_poses": nclust(ra), "n_real_images": nclust(rb),
                                 "med_sim": round(sa["med"], 4), "med_real": round(sb["med"], 4),
                                 "d_median": round(dm, 4), "d_median_lo": round(lo_m, 4),
                                 "d_median_hi": round(hi_m, 4),
                                 "frac_ge_bar_sim": round(sa["frac"], 4),
                                 "frac_ge_bar_real": round(sb["frac"], 4),
                                 "d_frac": round(df, 4), "d_frac_lo": round(lo_f, 4),
                                 "d_frac_hi": round(hi_f, 4)})
            if per_bin_med:
                P(f"  {'bin-average':>12s} {'':6s} {'':6s} {'':8s} {'':9s} "
                  f"{np.mean(per_bin_med):+8.3f} {'':18s} {'':10s} {'':11s} "
                  f"{np.mean(per_bin_frac):+8.3f}")
    with open(D / "tables/matched_gap.tsv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(gap_rows[0].keys()), delimiter="\t")
        w.writeheader()
        w.writerows(gap_rows)

    # ------------------------- 2b. size-standardised, over the flown band only
    P("")
    P("=" * 78)
    P("2b. SIZE-STANDARDISED over the flown band.  The sim's own apparent-size mix")
    P("    (its frames at 1.0-4.0 m) is used to reweight the real photographs, so")
    P("    the two sides are compared with the SAME size mix and the answer cannot")
    P("    be an artefact of which sizes each side happens to contain.")
    P("=" * 78)
    std_rows = []
    for sg, rg, label in (("sim_dog_eye_himax", "real_himax_dog", "dog vs real dogs, himax both sides"),
                          ("sim_dog_eye_himax", "real_raw_dog", "dog vs real dogs, raw photos"),
                          ("sim_dog_eye_himax", "real_raw_allpets", "dog vs all real pets, raw photos"),
                          ("sim_cat_eye_himax", "real_himax_cat", "cat vs real cats, himax both sides"),
                          ("sim_cat_eye_himax", "real_raw_cat", "cat vs real cats, raw photos")):
        P(f"\n  {label}")
        P(f"  {'arm':6s} {'sim >=bar':>10s} {'real >=bar (std)':>17s} {'ratio':>7s} "
          f"{'sim mean':>9s} {'real mean (std)':>16s} {'bins used':>10s}")
        for arm in ARMS:
            wsum = 0.0
            f_std = m_std = 0.0
            used = []
            for lo, hi in BINS:
                ra, rb = in_bin(groups[sg], lo, hi), in_bin(groups[rg], lo, hi)
                if not ra or nclust(rb) < 3:
                    continue
                w = len(ra)
                b = vals(rb, arm)
                f_std += w * float(np.mean(b >= BAR))
                m_std += w * float(b.mean())
                wsum += w
                used.append(f"{lo}-{hi}")
            if wsum == 0:
                continue
            a = vals(groups[sg], arm)
            # the sim is restricted to the same bins, so the two mixes really do match
            keep = [r for r in groups[sg] if any(int(u.split("-")[0]) <= float(r["px128_h"]) < int(u.split("-")[1]) for u in used)]
            a = vals(keep, arm)
            sf, sm = float(np.mean(a >= BAR)), float(a.mean())
            rf, rm = f_std / wsum, m_std / wsum
            P(f"  {arm:6s} {sf:10.3f} {rf:17.3f} {sf / rf if rf > 0 else float('inf'):7.1f} "
              f"{sm:9.3f} {rm:16.3f} {','.join(used):>10s}")
            std_rows.append({"sim_group": sg, "real_group": rg, "arm": arm,
                             "sim_frac_ge_bar": round(sf, 4), "real_frac_ge_bar_std": round(rf, 4),
                             "ratio": round(sf / rf, 2) if rf > 0 else "inf",
                             "sim_mean": round(sm, 4), "real_mean_std": round(rm, 4),
                             "bins": ";".join(used), "n_sim_frames": len(a)})
    with open(D / "tables/size_standardised.tsv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(std_rows[0].keys()), delimiter="\t")
        w.writeheader()
        w.writerows(std_rows)

    # ------------------------------- 2c. robustness: only fully visible subjects
    P("")
    P("=" * 78)
    P("2c. ROBUSTNESS - subjects that are WHOLLY inside the frame on both sides.")
    P("    A sim pet closer than ~1.15 m is cut off by the bottom of the frame, and")
    P("    a COCO subject can be cut by the centre square crop. Dropping both kinds")
    P("    leaves apparent size meaning the same thing on both sides.")
    P("=" * 78)
    def whole_sim(rows):
        return [r for r in rows if float(r["visible_fraction"]) >= 0.95 and r["touches_frame_edge"] == "0"]
    def whole_real(rows):
        return [r for r in rows if abs(float(r["px128_h"]) - float(r.get("px128_h_nocrop", r["px128_h"]))) < 0.02 * float(r["px128_h"])]
    rr = {k: (whole_sim(v) if k.startswith("sim") else whole_real(v)) for k, v in groups.items()}
    for sg, rg, label in (("sim_dog_eye_himax", "real_raw_dog", "dog, sim himax vs raw photo"),
                          ("sim_dog_eye_himax", "real_raw_allpets", "dog vs all pets, sim himax vs raw")):
        P(f"\n  {label}   (sim frames {len(rr[sg])}/{len(groups[sg])}, "
          f"real images {len(rr[rg])}/{len(groups[rg])} kept)")
        for arm in ARMS:
            line = f"  {arm:6s}"
            for lo, hi in BINS:
                a, b = vals(in_bin(rr[sg], lo, hi), arm), vals(in_bin(rr[rg], lo, hi), arm)
                if len(a) == 0 or nclust(in_bin(rr[rg], lo, hi)) < 3:
                    continue
                line += (f"   [{lo}-{hi}] d_med {np.median(a) - np.median(b):+.3f} "
                         f"d_frac {np.mean(a >= BAR) - np.mean(b >= BAR):+.3f}")
            P(line)

    # ------------------------------------------- 3. the same image both ways
    P("")
    P("=" * 78)
    P("3. THE SAME IMAGE BOTH WAYS.  The sim's dog IS COCO val2017 297830/11206")
    P("   and its cat IS 131938/50735 - both of them members of the 771-image")
    P("   confuser slice.  Rendered at the range that reproduces the photograph's")
    P("   own apparent size (camera lowered to the subject's centre height, the")
    P("   only way to reach that size), against the photograph scored directly.")
    P("=" * 78)
    same = []
    for cocoid, job, want_px in ((297830, "dog_petlevel", 119.91), (131938, "cat_petlevel", 128.0)):
        rp = [r for r in real if int(r["img_id"]) == cocoid][0]
        rh = [r for r in realh if int(r["img_id"]) == cocoid]
        cand = sel(sim, job=job)
        best = min({r["range_m"] for r in cand},
                   key=lambda rr: abs(float(sel(cand, range_m=rr)[0]["px128_h"]) - want_px))
        srows = sel(cand, range_m=best)
        sp = float(srows[0]["px128_h"])
        P(f"\nCOCO {cocoid}  photo px128_h {float(rp['px128_h']):.1f}  vs  "
          f"{job} at range {best} m, px128_h {sp:.1f}")
        P(f"  {'arm':6s} {'photo direct':>13s} {'photo himax(3)':>15s} "
          f"{'sim clean':>10s} {'sim himax(n)':>22s}")
        for arm in ARMS:
            ph = np.array([float(r[arm]) for r in rh])
            sc = [float(r[arm]) for r in sel(srows, camera="clean")]
            sh = np.array([float(r[arm]) for r in sel(srows, camera="himax")])
            P(f"  {arm:6s} {float(rp[arm]):13.3f} {ph.mean():15.3f} "
              f"{sc[0]:10.3f} {sh.mean():10.3f} [{sh.min():.3f}-{sh.max():.3f}] n={len(sh)}")
            same.append({"coco_img_id": cocoid, "arm": arm, "photo_px128_h": float(rp["px128_h"]),
                         "sim_px128_h": sp, "sim_range_m": best,
                         "photo_direct": float(rp[arm]), "photo_himax_mean": round(float(ph.mean()), 4),
                         "sim_clean": sc[0], "sim_himax_mean": round(float(sh.mean()), 4),
                         "sim_himax_min": float(sh.min()), "sim_himax_max": float(sh.max()),
                         "d_himax_sim_minus_photo": round(float(sh.mean() - ph.mean()), 4),
                         "d_clean_sim_minus_photo": round(float(sc[0] - float(rp[arm])), 4)})
    with open(D / "tables/same_image.tsv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(same[0].keys()), delimiter="\t")
        w.writeheader()
        w.writerows(same)

    # ------------------------------- 4. is the sim pet a typical pet of its kind
    P("")
    P("=" * 78)
    P("4. IS THE SIM PET REPRESENTATIVE?  Where the sim frame's confidence falls")
    P("   inside the DISTRIBUTION of real photographs of the same species at the")
    P("   same apparent size (percentile, and the real spread it sits in).")
    P("=" * 78)
    for species, sg, rg in (("dog", "sim_dog_eye_himax", "real_himax_dog"),
                            ("cat", "sim_cat_eye_himax", "real_himax_cat")):
        for arm in ARMS:
            P(f"\n  {species}, arm {arm}, himax on both sides")
            P(f"  {'bin':>12s} {'sim med':>8s} {'real med':>9s} {'real p25-p75':>16s} "
              f"{'sim pct in real':>16s} {'n real':>7s}")
            for lo, hi in BINS:
                a, b = vals(in_bin(groups[sg], lo, hi), arm), vals(in_bin(groups[rg], lo, hi), arm)
                if len(a) == 0 or len(b) < 3:
                    continue
                pct = float(np.mean(b < np.median(a)) * 100)
                P(f"  {lo:5d}-{hi:<6d} {np.median(a):8.3f} {np.median(b):9.3f} "
                  f"{np.percentile(b,25):7.3f}-{np.percentile(b,75):<8.3f} {pct:15.0f}% {len(b):7d}")

    # ----------------------------------------------------------- 5. the figures
    figures(groups, real)

    (D / "tables/analysis.txt").write_text("\n".join(REPORT) + "\n")
    print("wrote", D / "tables/analysis.txt")


def figures(groups, real):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    for species, eye, petl, rraw, rhim in (
            ("dog", "sim_dog_eye_himax", "sim_dog_petlevel_himax", "real_raw_dog", "real_himax_dog"),
            ("cat", "sim_cat_eye_himax", "sim_cat_petlevel_himax", "real_raw_cat", "real_himax_cat")):
        fig, axes = plt.subplots(1, 3, figsize=(16, 5), sharey=True)
        for ax, arm in zip(axes, ARMS):
            ax.scatter(px(groups["real_raw_allpets"]), vals(groups["real_raw_allpets"], arm),
                       s=8, c="#c8c8c8", label="real photo, any pet (n=771)", zorder=1)
            ax.scatter(px(groups[rraw]), vals(groups[rraw], arm), s=22, c="#1f77b4",
                       label=f"real photo, {species} (n={len(groups[rraw])})", zorder=3)
            ax.scatter(px(groups[rhim]), vals(groups[rhim], arm), s=10, c="#7fb3d5", alpha=.5,
                       label=f"real {species} through himax", zorder=2)
            for g, col, lab in ((eye, "#d62728", "sim, flown eye line, himax"),
                                (petl, "#ff7f0e", "sim, pet-level camera, himax")):
                rows = groups[g]
                p, v = px(rows), vals(rows, arm)
                o = np.argsort(p)
                ax.plot(p[o], v[o], ".", ms=4, c=col, alpha=.45, zorder=4)
                # median per range point
                xs = sorted({float(r["px128_h"]) for r in rows})
                ys = [np.median([float(r[arm]) for r in rows if float(r["px128_h"]) == x]) for x in xs]
                ax.plot(xs, ys, "-", c=col, lw=2, label=lab, zorder=5)
            ax.axhline(BAR, color="k", ls="--", lw=1)
            ax.text(2, BAR + .015, f"shipped bar {BAR}", fontsize=8)
            fb = px(groups[eye])
            ax.axvspan(fb.min(), fb.max(), color="#2ca02c", alpha=.07)
            ax.text(fb.min() + 1, .02, "sizes the drone flies", fontsize=7, color="#2ca02c")
            ax.set_xlabel("apparent size px128_h (subject height in the 128-px input)")
            ax.set_title(f"{species} - champion arm: {arm}")
            ax.set_xlim(0, 132); ax.set_ylim(0, 1.02); ax.grid(alpha=.25)
        axes[0].set_ylabel("person-visibility confidence")
        axes[0].legend(fontsize=7, loc="upper left")
        fig.suptitle(f"Simulated {species} vs real {species} photographs at matched apparent size "
                     f"(champion QAT ep3; nothing here flew)", fontsize=11)
        fig.tight_layout()
        fig.savefig(D / f"figures/conf_vs_size_{species}.png", dpi=140)
        plt.close(fig)

    # fraction above the bar, per bin, chip arm (the network F.pets__ships flies)
    fig, axes = plt.subplots(1, 2, figsize=(12.5, 5), sharey=True)
    for ax, (species, sg, rg, rr) in zip(axes, (
            ("dog", "sim_dog_eye_himax", "real_himax_dog", "real_raw_dog"),
            ("cat", "sim_cat_eye_himax", "real_himax_cat", "real_raw_cat"))):
        labels, bars = [], []
        for lo, hi in BINS:
            a = in_bin(groups[sg], lo, hi)
            b = in_bin(groups[rg], lo, hi)
            c = in_bin(groups[rr], lo, hi)
            if not a and nclust(c) < 5:
                continue
            labels.append(f"{lo}-{hi}")
            bars.append((
                (np.mean(vals(a, "chip") >= BAR), nclust(a)) if a else (np.nan, 0),
                (np.mean(vals(b, "chip") >= BAR), nclust(b)) if nclust(b) >= 5 else (np.nan, nclust(b)),
                (np.mean(vals(c, "chip") >= BAR), nclust(c)) if nclust(c) >= 5 else (np.nan, nclust(c))))
        x = np.arange(len(labels))
        cols = ["#d62728", "#7fb3d5", "#1f77b4"]
        names = ["sim, flown eye line, himax", "real photo through himax", "real photo, raw"]
        for j in range(3):
            v = [b[j][0] for b in bars]
            n = [b[j][1] for b in bars]
            ax.bar(x + (j - 1) * .27, v, .25, color=cols[j], label=names[j])
            for xi, vi, ni in zip(x, v, n):
                if not np.isnan(vi):
                    ax.text(xi + (j - 1) * .27, vi + .012, f"{vi:.2f}\nn={ni}", ha="center",
                            fontsize=6.5)
        ax.set_xticks(x); ax.set_xticklabels(labels, fontsize=8)
        ax.set_xlabel("apparent size bin (px128_h)")
        ax.set_title(f"{species}: fraction at or above {BAR}   (n = photographs, or rendered poses)")
        ax.grid(alpha=.25, axis="y")
        ax.set_ylim(0, .78)
    axes[0].set_ylabel(f"fraction >= {BAR}")
    axes[0].legend(fontsize=8)
    fig.suptitle("chip arm (model_id_dory.onnx) - the network the F.pets__ships cell flies. "
                 "Bins with fewer than 5 real photographs are not drawn.", fontsize=10)
    fig.tight_layout()
    fig.savefig(D / "figures/frac_above_bar_chip.png", dpi=140)
    plt.close(fig)
    print("wrote figures")


if __name__ == "__main__":
    main()
