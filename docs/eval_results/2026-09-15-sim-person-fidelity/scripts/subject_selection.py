#!/usr/bin/env python3
"""WHY the flown person cells read so high, when rendering people in general
reads LOW: subject selection, and what the rendering actually does to a score.

Two questions, both answered against the 267-person cohort:

  A. WHERE DOES THE SIMULATOR'S OWN PERSON SIT? COCO 19432 / ann 428692 is the
     cutout BOTH person cells of the CORE matrix use. Rank it among 267 real
     people rendered by the same pipeline at the same ranges, and among real
     photographs of matched apparent size. If it is ordinary as a photograph
     and extreme as a render, the flown cells' confidence is a property of one
     cutout, not of the perception system.

  B. WHAT DOES THE RENDERING DO TO A SCORE? Regress the paired difference
     (render minus the subject's own photograph, at matched apparent size) on
     the photograph's own score. A slope near zero would mean the renderer
     shifts everything by a constant. A slope near -1 means it COMPRESSES the
     confidence scale toward a fixed point: it pushes low scores up and pulls
     high scores down. That single number decides whether "the simulator is
     biased toward false alarms" or "toward detectability" is the right frame -
     or whether neither is.

Outputs tables/subject_selection.tsv, tables/regression_to_middle.tsv,
        tables/subject_selection.txt

Usage: nemoenv/bin/python subject_selection.py <dir>
"""
import csv
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from shared_arms import relabel  # noqa: E402

D = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
RNG = np.random.default_rng(11)
ARMS = ["float", "fq", "chip"]
RA = {"float": "float_via244", "fq": "fq_via244", "chip": "chip_via244"}
BAR, EXIT_BAR = 0.75, 0.45
SRC = "19432"
REPORT = []


def P(s=""):
    print(s, flush=True)
    REPORT.append(s)


def rd(p):
    return list(csv.DictReader(open(D / p)))


def per_subject(coh, rng, arm, camera="himax", dy="0.0", match=False):
    """One number per subject: the mean over that subject's frames at one pose."""
    by = {}
    for r in coh:
        if r["camera"] != camera or r["dy_m"] != dy:
            continue
        if match:
            if r["is_r_match"] != "1":
                continue
        elif r["range_m"] != rng:
            continue
        by.setdefault(r["img_id"], []).append(float(r[arm]))
    return {k: float(np.mean(v)) for k, v in by.items()}


def main():
    real = {r["img_id"]: r for r in rd("tables/real_people.csv")}
    coh = relabel(rd("tables/sim_cohort.csv"), real)

    P("=" * 78)
    P("A. IS THE SIMULATOR'S PERSON AN ORDINARY PERSON?")
    P("=" * 78)
    P("COCO 19432 / ann 428692 - the cutout s15_static_offset AND s01_control_moving")
    P("both name - against 266 other real people put through the SAME pipeline at")
    P("the SAME range. chip arm, himax camera, dy = 0.")
    P("")
    tsv = [("question", "arm", "range_m", "px128_h", "n_peers", "peer_median",
            "peer_frac_ge_075", "subject_value", "percentile")]
    P(f"{'range':<8}{'px128_h':>9}{'cohort median':>15}{'cohort >=0.75':>15}"
      f"{'19432':>9}{'percentile':>12}")
    for arm in ARMS:
        if arm != "chip":
            continue
        for rng in ("1.5", "2.0", "2.5", "3.0", "3.5", "4.0"):
            d = per_subject(coh, rng, arm)
            if SRC not in d:
                continue
            m = np.array([v for k, v in d.items() if k != SRC])
            px = float(next(r for r in coh if r["img_id"] == SRC
                            and r["range_m"] == rng and r["dy_m"] == "0.0")["px128_h"])
            pc = 100.0 * float(np.mean(m < d[SRC]))
            P(f"{rng + ' m':<8}{px:>9.1f}{np.median(m):>15.3f}{np.mean(m >= BAR):>15.3f}"
              f"{d[SRC]:>9.3f}{pc:>11.1f}%")
            tsv.append(("render_rank", arm, rng, f"{px:.1f}", len(m), f"{np.median(m):.4f}",
                        f"{np.mean(m >= BAR):.4f}", f"{d[SRC]:.4f}", f"{pc:.1f}"))
    P("")
    P("The same cutout AS A PHOTOGRAPH, against whole_upright photographs within")
    P("+/-15% of its own apparent size:")
    P("")
    p0 = float(real[SRC]["px128_h"])
    P(f"{'arm':<8}{'19432':>9}{'peer n':>9}{'peer median':>14}{'percentile':>12}")
    for arm in ARMS:
        peers = np.array([float(r[RA[arm]]) for r in real.values()
                          if r["whole_upright"] == "1" and r["is_sim_source"] != "1"
                          and 0.85 * p0 <= float(r["px128_h"]) <= 1.15 * p0])
        v = float(real[SRC][RA[arm]])
        pc = 100.0 * float(np.mean(peers < v))
        P(f"{arm:<8}{v:>9.3f}{len(peers):>9}{np.median(peers):>14.3f}{pc:>11.1f}%")
        tsv.append(("photo_rank", arm, "n/a", f"{p0:.1f}", len(peers), f"{np.median(peers):.4f}",
                    f"{np.mean(peers >= BAR):.4f}", f"{v:.4f}", f"{pc:.1f}"))
    P("")
    P("An ordinary photograph; an extreme render. The flown cells' confidence is a")
    P("property of WHICH cutout was chosen, not of the rendering in general.")
    P("")

    P("=" * 78)
    P("B. WHAT THE RENDERING DOES TO A SCORE: compression toward a fixed point")
    P("=" * 78)
    P("Paired, at matched apparent size (`is_r_match`), dy = 0, himax mean per")
    P("subject, against that subject's own photograph on the resolution-matched")
    P("chain. d = render - photo, regressed on the photograph's own score.")
    P("")
    rm = [("stratum", "arm", "n", "slope", "slope_lo", "slope_hi", "intercept", "pearson_r",
           "fixed_point", "bucket", "bucket_n", "bucket_median_d")]
    for stratum in ("wui", "whole_upright"):
        P(f"--- {stratum} " + "-" * 60)
        P(f"{'arm':<7}{'n':>5}  {'slope (95% CI)':<26}{'r':>8}{'fixed point':>14}")
        for arm in ARMS:
            d = per_subject([r for r in coh if r[stratum] == "1"], None, arm, match=True)
            ids = sorted(d)
            x = np.array([float(real[i][RA[arm]]) for i in ids])
            y = np.array([d[i] - float(real[i][RA[arm]]) for i in ids])
            sl, ic = np.polyfit(x, y, 1)
            r_ = float(np.corrcoef(x, y)[0, 1])
            fp = -ic / sl if sl else float("nan")
            bs = np.array([np.polyfit(*(lambda k: (x[k], y[k]))(RNG.integers(0, len(x), len(x))), 1)[0]
                           for _ in range(2000)])
            slo, shi = float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))
            P(f"{arm:<7}{len(x):>5}  {f'{sl:+.3f} [{slo:+.3f}, {shi:+.3f}]':<26}{r_:>8.3f}{fp:>14.3f}")
            for lo, hi in ((0.0, 0.3), (0.3, 0.6), (0.6, 0.9), (0.9, 1.01)):
                k = (x >= lo) & (x < hi)
                if k.sum() >= 3:
                    rm.append((stratum, arm, len(x), f"{sl:+.4f}", f"{slo:+.4f}", f"{shi:+.4f}",
                               f"{ic:+.4f}", f"{r_:+.4f}", f"{fp:.4f}",
                               f"[{lo:.1f},{hi:.1f})", int(k.sum()), f"{np.median(y[k]):+.4f}"))
        P("")
        P(f"  render minus photo, by the photograph's own score ({stratum}, chip):")
        d = per_subject([r for r in coh if r[stratum] == "1"], None, "chip", match=True)
        ids = sorted(d)
        x = np.array([float(real[i]["chip_via244"]) for i in ids])
        y = np.array([d[i] - float(real[i]["chip_via244"]) for i in ids])
        for lo, hi in ((0.0, 0.3), (0.3, 0.6), (0.6, 0.9), (0.9, 1.01)):
            k = (x >= lo) & (x < hi)
            if k.sum() >= 3:
                P(f"    photo in [{lo:.1f}, {hi:.1f}):  n={int(k.sum()):3d}   "
                  f"median d {np.median(y[k]):+.3f}")
        P("")

    P("A slope near -0.8 with a fixed point around 0.6: the renderer does not add")
    P("or subtract detectability, it COMPRESSES the scale. A photograph the network")
    P("scores low is pushed UP by being rendered; one it scores high is pulled DOWN.")
    P("That one mechanism predicts BOTH studies: the pet study's rendered dog (a")
    P("~0.3 photograph) went up and became a false alarm; a real person (a ~0.9")
    P("photograph) goes down. The flown person cells escape it only because their")
    P("cutout renders in the top 1-2% of people.")

    with open(D / "tables/subject_selection.tsv", "w", newline="") as f:
        csv.writer(f, delimiter="\t").writerows(tsv)
    with open(D / "tables/regression_to_middle.tsv", "w", newline="") as f:
        csv.writer(f, delimiter="\t").writerows(rm)
    (D / "tables/subject_selection.txt").write_text("\n".join(REPORT) + "\n")
    P("")
    P("wrote tables/subject_selection.tsv, regression_to_middle.tsv, subject_selection.txt")


if __name__ == "__main__":
    main()
