#!/usr/bin/env python3
"""Figures. Every panel names its arm, its camera, its resampling chain and its
threshold in the title, because that is what this project got burned on twice.

  conf_vs_size_person.png   median confidence vs apparent size, each side
  bars_vs_size_chip.png     fraction >= 0.75 and fraction < 0.45 vs size, chip
  paired_render_vs_photo.png  the compression: render minus photo against the
                            photograph's own score, with the simulator's own
                            cutout marked
  what_the_net_sees.png     the actual 128x128 chip inputs, sim and real, at
                            matched apparent size, with their chip confidences

Usage: nemoenv/bin/python make_figures.py <dir> <sim_frames_dir> <cohort_frames_dir>
"""
import csv
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt          # noqa: E402
import numpy as np                       # noqa: E402
from PIL import Image                    # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from shared_arms import IMG_DIR, ROOT, relabel    # noqa: E402
sys.path.insert(0, str(ROOT / "tools/crazysim_macos"))
from perception_backends import firmware_preprocess   # noqa: E402

D = Path(sys.argv[1])
SIMF = Path(sys.argv[2])
COHF = Path(sys.argv[3])
BINS = [(8, 15), (15, 25), (25, 40), (40, 55), (55, 80), (80, 129)]
CTR = [(a + b) / 2 for a, b in BINS]
BAR, EXIT_BAR = 0.75, 0.45
FLOWN_LO, FLOWN_HI = 155.36 / 4.0, 155.36 / 1.5
RA = {"float": "float_via244", "fq": "fq_via244", "chip": "chip_via244"}


def rd(p):
    return list(csv.DictReader(open(D / p)))


def curve(rows, col, fn):
    out = []
    for lo, hi in BINS:
        v = np.array([float(r[col]) for r in rows if lo <= float(r["px128_h"]) < hi], float)
        out.append(fn(v) if len(v) >= 3 else np.nan)
    return np.array(out)


def main():
    real_rows = rd("tables/real_people.csv")
    by_img = {r["img_id"]: r for r in real_rows}
    real = [r for r in real_rows if r["is_sim_source"] != "1"]
    simc = [r for r in rd("tables/sim_person.csv") if r["camera"] == "himax"]
    coh = [r for r in relabel(rd("tables/sim_cohort.csv"), by_img)
           if r["camera"] == "himax" and r["is_sim_source"] != "1"
           and r["whole_upright"] == "1"]
    rw = [r for r in real if r["whole_upright"] == "1"]
    rwui = [r for r in real if r["wui"] == "1"]

    n_coh = len({r["img_id"] for r in coh})
    SETS = [(f"real, all people (n={len(real)})", real, RA, "tab:blue", "-"),
            (f"real, whole+upright (n={len(rw)})", rw, RA, "tab:cyan", "-"),
            (f"real, whole+upright+isolated (n={len(rwui)})", rwui, RA, "tab:green", "--"),
            ("SIM: the flown s15/s01 cutout", simc, {k: k for k in RA}, "tab:red", "-"),
            (f"SIM: {n_coh} real people rendered", coh, {k: k for k in RA}, "tab:orange", "-")]

    # ---- 1. median confidence vs size ------------------------------------
    fig, axes = plt.subplots(1, 3, figsize=(16.5, 5.2), sharey=True)
    for ax, arm in zip(axes, ("float", "fq", "chip")):
        for lab, rows, cm, c, ls in SETS:
            ax.plot(CTR, curve(rows, cm[arm], np.median), ls, marker="o", color=c, label=lab)
        ax.axhline(BAR, color="k", lw=1.0, ls=":")
        ax.axhline(EXIT_BAR, color="0.45", lw=1.0, ls=":")
        ax.axvspan(FLOWN_LO, FLOWN_HI, color="0.9", zorder=0)
        ax.set_xlabel("apparent size px128_h (subject height in the 128x128 input)")
        ax.set_title(f"{arm} arm - sim himax vs real via244\n"
                     f"dotted: 0.75 enter, 0.45 exit; grey band = flown 1.5-4.0 m")
        ax.set_ylim(0, 1.03); ax.grid(alpha=0.3)
    axes[0].set_ylabel("median visibility confidence")
    axes[0].legend(fontsize=8, loc="lower right")
    fig.suptitle("Median confidence vs apparent size: simulated person against real COCO people "
                 "(one threshold, one resampling chain)", fontsize=12)
    fig.tight_layout()
    fig.savefig(D / "figures/conf_vs_size_person.png", dpi=130)
    plt.close(fig)

    # ---- 2. the two bars, chip arm ---------------------------------------
    fig, axes = plt.subplots(1, 2, figsize=(13, 5.2))
    for ax, (fn, name, thr) in zip(axes, ((lambda v: float(np.mean(v >= BAR)),
                                           "fraction at or above 0.75 (the follow bar)", BAR),
                                          (lambda v: float(np.mean(v < EXIT_BAR)),
                                           "fraction below 0.45 (the let-go bar)", EXIT_BAR))):
        for lab, rows, cm, c, ls in SETS:
            ax.plot(CTR, curve(rows, cm["chip"], fn), ls, marker="o", color=c, label=lab)
        ax.axvspan(FLOWN_LO, FLOWN_HI, color="0.9", zorder=0)
        ax.set_xlabel("apparent size px128_h")
        ax.set_ylabel(name)
        ax.set_title(f"chip arm (model_id_dory.onnx), threshold {thr}")
        ax.set_ylim(-0.02, 1.02); ax.grid(alpha=0.3)
    axes[0].legend(fontsize=8, loc="upper left")
    fig.suptitle("The two numbers the follower acts on, chip arm, resolution-matched", fontsize=12)
    fig.tight_layout()
    fig.savefig(D / "figures/bars_vs_size_chip.png", dpi=130)
    plt.close(fig)

    # ---- 3. the compression ----------------------------------------------
    photo = {r["img_id"]: r for r in rd("tables/real_people.csv")}
    allcoh = [r for r in relabel(rd("tables/sim_cohort.csv"), photo)
              if r["camera"] == "himax"]
    fig, axes = plt.subplots(1, 2, figsize=(13, 5.6))
    for ax, stratum in zip(axes, ("whole_upright", "wui")):
        by = {}
        for r in allcoh:
            if r["is_r_match"] == "1" and r["dy_m"] == "0.0" and r[stratum] == "1":
                by.setdefault(r["img_id"], []).append(float(r["chip"]))
        ids = sorted(by)
        x = np.array([float(photo[i]["chip_via244"]) for i in ids])
        y = np.array([np.mean(by[i]) for i in ids])
        ax.scatter(x, y, s=16, alpha=0.55, color="tab:orange",
                   label=f"{len(ids)} real people, rendered")
        # The simulator's own cutout is plotted even when it is not in the
        # stratum: 16% of its width falls outside the centre crop, so it is not
        # "wholly in crop" - but it is the subject the flights actually use.
        src = [r for r in allcoh if r["is_sim_source"] == "1"
               and r["is_r_match"] == "1" and r["dy_m"] == "0.0"]
        if src:
            sx = float(photo["19432"]["chip_via244"])
            sy = float(np.mean([float(r["chip"]) for r in src]))
            ax.scatter([sx], [sy], s=170, marker="*", color="tab:red", zorder=5,
                       label="COCO 19432 - the cutout s15/s01 fly")
        ax.plot([0, 1], [0, 1], "k-", lw=1, label="render = photograph")
        sl, ic = np.polyfit(x, y - x, 1)
        xx = np.linspace(0, 1, 50)
        ax.plot(xx, xx + sl * xx + ic, "b--", lw=1.4,
                label=f"fit: slope {1 + sl:+.2f}, fixed point {-ic / sl:.2f}")
        ax.axhline(BAR, color="k", lw=0.8, ls=":"); ax.axvline(BAR, color="k", lw=0.8, ls=":")
        ax.axhline(EXIT_BAR, color="0.45", lw=0.8, ls=":")
        ax.axvline(EXIT_BAR, color="0.45", lw=0.8, ls=":")
        ax.set_xlabel("the person's own PHOTOGRAPH, chip via244")
        ax.set_ylabel("the same person RENDERED as a card, chip himax")
        ax.set_title(f"{stratum}, n={len(ids)}, at matched apparent size")
        ax.set_xlim(0, 1.02); ax.set_ylim(0, 1.02); ax.grid(alpha=0.3)
        ax.legend(fontsize=8, loc="lower right")
    fig.suptitle("The simulator COMPRESSES the confidence scale toward ~0.6 - it does not "
                 "make everything more person-like", fontsize=12)
    fig.tight_layout()
    fig.savefig(D / "figures/paired_render_vs_photo.png", dpi=130)
    plt.close(fig)

    # ---- 4. what the net sees --------------------------------------------
    picks = []
    s = [r for r in simc if r["job"] == "person_s15" and r["dy_m"] == "0.0"
         and 55 <= float(r["px128_h"]) < 80]
    if s:
        picks.append(("SIM s15/s01 cutout\n(the flown card)", SIMF / s[0]["frame"], s[0]))
    cl = sorted([r for r in coh if r["dy_m"] == "0.0" and 55 <= float(r["px128_h"]) < 80],
                key=lambda r: float(r["chip"]))
    for lab, r in (("SIM cohort, low", cl[len(cl) // 10]), ("SIM cohort, median", cl[len(cl) // 2]),
                   ("SIM cohort, high", cl[-len(cl) // 10])):
        picks.append((f"{lab}\n(a real person, rendered)", COHF / r["frame"], r))
    rr = sorted([r for r in rw if 55 <= float(r["px128_h"]) < 80],
                key=lambda r: float(r["chip_via244"]))
    for lab, r in (("REAL photo, low", rr[len(rr) // 10]), ("REAL photo, median", rr[len(rr) // 2]),
                   ("REAL photo, high", rr[-len(rr) // 10])):
        picks.append((f"{lab}\n(whole upright person)", IMG_DIR / r["file_name"], r))

    fig, axes = plt.subplots(1, len(picks), figsize=(2.15 * len(picks), 3.2))
    for ax, (lab, path, r) in zip(axes, picks):
        g = np.asarray(Image.open(path).convert("L"), np.uint8)
        if "file_name" in r:                 # a photograph: the frame's own 244 chain first
            img = Image.fromarray(g, "L")
            w, h = img.size
            sq = min(w, h)
            img = img.crop(((w - sq) // 2, (h - sq) // 2, (w - sq) // 2 + sq, (h - sq) // 2 + sq))
            g = np.asarray(img.resize((244, 244), Image.BILINEAR), np.uint8)
            conf = float(r["chip_via244"]); chain = "via244"
        else:
            conf = float(r["chip"]); chain = "native 244"
        ax.imshow(firmware_preprocess(g), cmap="gray", vmin=0, vmax=255)
        ax.set_title(f"{lab}\npx128_h {float(r['px128_h']):.0f}  chip {conf:.2f}\n({chain})",
                     fontsize=7.5)
        ax.axis("off")
    fig.suptitle("What the chip actually sees, all at 55-80 px128_h, all through "
                 "firmware_preprocess - chip confidence under each", fontsize=11)
    fig.tight_layout()
    fig.savefig(D / "figures/what_the_net_sees.png", dpi=140)
    plt.close(fig)
    print("wrote 4 figures to", D / "figures")


if __name__ == "__main__":
    main()
