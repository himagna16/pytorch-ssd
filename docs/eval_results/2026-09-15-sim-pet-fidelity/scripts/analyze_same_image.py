#!/usr/bin/env python3
"""What the same-image measurement can and cannot settle.

Reads tables/same_image_ladder.csv (the photograph re-framed to each apparent
size under three paddings), tables/sim_pets.csv (the card rendered at each
apparent size), tables/real_pets.csv and tables/real_pets_himax.csv.

Prints, and writes tables/same_image_summary.tsv + figures/same_image_ladder.png:

  A. the INVENTION-FREE pair - the photograph at a framing that needs no
     invented surround, against the card rendered to the same apparent size;
  B. the padded ladder, with the disagreement between the three paddings shown
     as the error bar it is, so that a reader can see where it stops meaning
     anything;
  C. where each source photograph sits inside the distribution of real
     photographs of its own species at its own apparent size - i.e. whether
     the sim picked an unusually person-like animal.

Usage: nemoenv/bin/python analyze_same_image.py <dir>
"""
import csv
import sys
from pathlib import Path

import numpy as np

D = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
ARMS = ["float", "fq", "chip"]
BAR = 0.75
PADS = ["edge", "symmetric", "flat"]
OUT = []


def P(s=""):
    print(s, flush=True)
    OUT.append(s)


def rd(p):
    return list(csv.DictReader(open(D / p)))


def main():
    lad = rd("tables/same_image_ladder.csv")
    sim = rd("tables/sim_pets.csv")
    real = rd("tables/real_pets.csv")
    realh = rd("tables/real_pets_himax.csv")
    rows_out = []

    P("=" * 78)
    P("A. THE INVENTION-FREE PAIR.  The photograph at a framing that needs no")
    P("   invented surround, against the SAME cutout rendered by the simulator to")
    P("   the same apparent size.  This is the only same-image comparison in this")
    P("   directory that is free of a modelling choice - and it lands at 120 px,")
    P("   far outside the 15-52 px the drone actually flies.")
    P("=" * 78)
    for species, iid, job in (("dog", 297830, "dog_petlevel"), ("cat", 131938, "cat_petlevel")):
        rp = [r for r in real if int(r["img_id"]) == iid][0]
        rh = [r for r in realh if int(r["img_id"]) == iid]
        want = float(rp["px128_h"])
        cand = sorted({(abs(float(r["px128_h"]) - want), r["range_m"], float(r["px128_h"]))
                       for r in sim if r["job"] == job})
        _, rng, spx = cand[0]
        srow = [r for r in sim if r["job"] == job and r["range_m"] == rng]
        P(f"\n  {species}: photo COCO {iid} at its own centre crop, px128_h {want:.1f}")
        P(f"     vs  {job} at {rng} m, px128_h {spx:.1f}")
        P(f"     {'arm':6s} {'photo':>8s} {'render clean':>13s} {'d':>7s} | "
          f"{'photo+himax':>12s} {'render himax':>13s} {'d':>7s}")
        for arm in ARMS:
            pd_ = float(rp[arm])
            ph = float(np.mean([float(r[arm]) for r in rh]))
            sc = float([r[arm] for r in srow if r["camera"] == "clean"][0])
            sh = np.array([float(r[arm]) for r in srow if r["camera"] == "himax"])
            P(f"     {arm:6s} {pd_:8.3f} {sc:13.3f} {sc - pd_:+7.3f} | "
              f"{ph:12.3f} {sh.mean():13.3f} {sh.mean() - ph:+7.3f}")
            rows_out.append({"block": "A_invention_free", "species": species, "coco_img_id": iid,
                             "px128_h": round(want, 1), "arm": arm, "pad_mode": "none",
                             "photo": pd_, "photo_himax": round(ph, 4), "render_clean": sc,
                             "render_himax": round(float(sh.mean()), 4),
                             "d_clean": round(sc - pd_, 4), "d_himax": round(float(sh.mean() - ph), 4)})

    P("")
    P("=" * 78)
    P("B. THE PADDED LADDER, and why it cannot be used to answer the question.")
    P("   To put the photographed dog at a FLOWN apparent size the photograph must")
    P("   be given a surround it does not contain. Three fillings, same picture,")
    P("   same size, same network:")
    P("=" * 78)
    for species in ("dog", "cat"):
        P(f"\n  {species}, arm fq, photograph through himax (mean of 3 draws)")
        P(f"  {'target px128':>13s} {'canvas/photo':>13s} " +
          " ".join(f"{m:>10s}" for m in PADS) + f" {'spread':>8s}   {'rendered card':>14s}")
        for t in sorted({int(r["target_px128"]) for r in lad}):
            rows = [r for r in lad if r["species"] == species and int(r["target_px128"]) == t]
            if not rows:
                continue
            side = int(rows[0]["canvas_side"])
            vs = [float(np.mean([float(r["fq"]) for r in rows
                                 if r["pad_mode"] == m and r["camera"] == "himax"])) for m in PADS]
            job = f"{species}_petlevel"
            c = [float(r["fq"]) for r in sim if r["job"] == job and r["camera"] == "himax"
                 and abs(float(r["px128_h"]) - t) <= 0.08 * t]
            if not c:
                c = [float(r["fq"]) for r in sim if r["job"] == f"{species}_eye"
                     and r["camera"] == "himax" and r["in_flight_band"] == "1"
                     and abs(float(r["px128_h"]) - t) <= 0.08 * t]
                job = f"{species}_eye"
            P(f"  {t:13d} {side / 640.0:12.1f}x " + " ".join(f"{v:10.3f}" for v in vs) +
              f" {max(vs) - min(vs):8.3f}   " +
              (f"{np.median(c):8.3f} ({job.split('_')[1]})" if c else f"{'-':>14s}"))
            for m, v in zip(PADS, vs):
                rows_out.append({"block": "B_padded", "species": species, "coco_img_id": rows[0]["coco_img_id"],
                                 "px128_h": t, "arm": "fq", "pad_mode": m, "photo": "",
                                 "photo_himax": round(v, 4), "render_clean": "",
                                 "render_himax": round(float(np.median(c)), 4) if c else "",
                                 "d_clean": "", "d_himax": round(float(np.median(c)) - v, 4) if c else ""})
    P("")
    P("  The three fillings are the same photograph of the same dog at the same")
    P("  apparent size through the same network. Where they disagree by more than")
    P("  the effect being measured, the padded ladder is measuring the padding.")

    P("")
    P("=" * 78)
    P("C. IS THE SIM'S CHOICE OF ANIMAL UNUSUAL?  Each source photograph against")
    P("   the distribution of real photographs of the SAME species within +/-15%")
    P("   of its own apparent size (raw photographs, no camera model).")
    P("=" * 78)
    for species, iid in (("dog", 297830), ("cat", 131938)):
        rp = [r for r in real if int(r["img_id"]) == iid][0]
        want = float(rp["px128_h"])
        peers = [r for r in real if r["subject_cat"] == species and int(r["img_id"]) != iid
                 and abs(float(r["px128_h"]) - want) <= 0.15 * want]
        P(f"\n  {species} COCO {iid}, px128_h {want:.1f}; {len(peers)} other real {species} "
          f"photographs within +/-15% of that size")
        P(f"  {'arm':6s} {'this photo':>11s} {'peer median':>12s} {'peer p25-p75':>16s} "
          f"{'percentile':>11s} {'peers >= bar':>13s}")
        for arm in ARMS:
            v = float(rp[arm])
            b = np.array([float(r[arm]) for r in peers])
            P(f"  {arm:6s} {v:11.3f} {np.median(b):12.3f} "
              f"{np.percentile(b,25):7.3f}-{np.percentile(b,75):<8.3f} "
              f"{np.mean(b < v) * 100:10.0f}% {np.mean(b >= BAR):13.3f}")
            rows_out.append({"block": "C_peer", "species": species, "coco_img_id": iid,
                             "px128_h": round(want, 1), "arm": arm, "pad_mode": "",
                             "photo": v, "photo_himax": "", "render_clean": "",
                             "render_himax": "", "d_clean": "",
                             "d_himax": round(float(np.mean(b < v) * 100), 1)})

    with open(D / "tables/same_image_summary.tsv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows_out[0].keys()), delimiter="\t")
        w.writeheader()
        w.writerows(rows_out)
    (D / "tables/same_image_analysis.txt").write_text("\n".join(OUT) + "\n")

    figure(lad, sim)


def figure(lad, sim):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 2, figsize=(13, 5), sharey=True)
    for ax, species in zip(axes, ("dog", "cat")):
        ts = sorted({int(r["target_px128"]) for r in lad})
        lo, hi, mid = [], [], []
        for t in ts:
            vs = [float(np.mean([float(r["fq"]) for r in lad if r["species"] == species
                                 and int(r["target_px128"]) == t and r["pad_mode"] == m
                                 and r["camera"] == "himax"])) for m in PADS]
            lo.append(min(vs)); hi.append(max(vs)); mid.append(float(np.median(vs)))
        ax.fill_between(ts, lo, hi, color="#1f77b4", alpha=.25,
                        label="same photo, re-framed (band = the 3 paddings)")
        ax.plot(ts, mid, "o-", c="#1f77b4", ms=4)
        for job, col, lab in ((f"{species}_eye", "#d62728", "same cutout rendered, flown eye line"),
                              (f"{species}_petlevel", "#ff7f0e", "same cutout rendered, pet-level camera")):
            rows = [r for r in sim if r["job"] == job and r["camera"] == "himax"
                    and (job.endswith("petlevel") or r["in_flight_band"] == "1")]
            xs = sorted({float(r["px128_h"]) for r in rows})
            ys = [np.median([float(r["fq"]) for r in rows if float(r["px128_h"]) == x]) for x in xs]
            ax.plot(xs, ys, "s-", c=col, ms=3, lw=1.6, label=lab)
        ax.axhline(BAR, color="k", ls="--", lw=1)
        ax.axvspan(15, 52 if species == "dog" else 32, color="#2ca02c", alpha=.08)
        ax.text(16, 0.02, "sizes the drone actually flies", fontsize=8, color="#2ca02c")
        ax.set_xlabel("apparent size px128_h")
        ax.set_title(f"{species}: COCO {297830 if species == 'dog' else 131938}, both ways (fq arm, himax)")
        ax.grid(alpha=.25); ax.set_ylim(0, 1.02)
    axes[0].set_ylabel("person-visibility confidence")
    axes[0].legend(fontsize=7, loc="upper left")
    fig.suptitle("The same COCO image, rendered by the simulator and re-framed as a photograph. "
                 "The blue band is the padding disagreement, not a measurement error.", fontsize=10)
    fig.tight_layout()
    fig.savefig(D / "figures/same_image_ladder.png", dpi=140)
    print("wrote figures/same_image_ladder.png")


if __name__ == "__main__":
    main()
