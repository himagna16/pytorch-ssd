#!/usr/bin/env python3
"""THE CONTROL, and it runs BEFORE any comparison.

THE CONFOUND. `perception_backends.firmware_preprocess` is the C port of the
firmware's preprocessing: centre square crop, then each of the 128x128 output
pixels is the rounded mean of the 2x2 camera block starting at the
nearest-neighbour source pixel. Integer arithmetic, NO ANTIALIASING. So the
stride at which it samples its input depends entirely on how big that input is:

    a rendered frame  324x244 -> crop 244 -> stride 244/128 = 1.91
                      the 2x2 block covers nearly every source pixel
    a COCO photograph 640x480 -> crop 480 -> stride 480/128 = 3.75
                      the block samples about a quarter of the pixels and
                      aliases the rest away

Same network, same bar, DIFFERENT INPUT CHAIN. That is the same class of error
as comparing two thresholds, and in the pet study it inflated a headline by
2.5x before verification caught it. `float` and `fq` are immune because their
preprocessing is PIL BILINEAR, which antialiases at any input resolution - and
that is exactly why validating this control on `float` alone licenses nothing.

THE CONTROL. `*_via244` resamples the centre crop to 244x244 before the arm's
own preprocessing, putting a photograph through the frame's own chain. It is
correct only if BOTH of these hold, and this script tests both:

  (i)  ON THE SIM SIDE IT IS A NO-OP. A rendered frame is natively a 244 crop,
       so `chip` and `chip_via244` must be bit-identical. If they were not, the
       control would be perturbing one side while correcting the other.
  (ii) ON THE REAL SIDE, ON THE CHIP ARM, IT MOVES THINGS. If it did not, there
       would be no confound to correct and the whole control would be theatre.
       This is the check the pet study skipped: it validated on float, where
       PIL's filtering hides the effect.

Outputs tables/control_resolution.tsv and tables/control_resolution.txt.

Usage: nemoenv/bin/python control_resolution.py <dir>
"""
import csv
import sys
from pathlib import Path

import numpy as np

D = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
BAR, EXIT_BAR = 0.75, 0.45
RNG = np.random.default_rng(7)
REPORT = []


def P(s=""):
    print(s, flush=True)
    REPORT.append(s)


def rd(p):
    return list(csv.DictReader(open(D / p)))


def frac(v, op, t):
    v = np.asarray(v, float)
    return float(np.mean(v >= t)) if op == ">=" else float(np.mean(v < t))


def boot_pair_ci(a, b, keys, stat, n=2000):
    """CI of stat(b) - stat(a) for two columns of the SAME rows, resampled by
    cluster (one photograph is one cluster however many draws it has)."""
    a, b, keys = np.asarray(a, float), np.asarray(b, float), np.asarray(keys)
    uk = np.unique(keys)
    idx = {k: np.where(keys == k)[0] for k in uk}
    out = np.empty(n)
    for i in range(n):
        pick = RNG.choice(uk, len(uk), replace=True)
        sel = np.concatenate([idx[k] for k in pick])
        out[i] = stat(b[sel]) - stat(a[sel])
    return float(np.percentile(out, 2.5)), float(np.percentile(out, 97.5))


def main():
    sim_main = rd("tables/sim_person.csv")
    sim_coh = rd("tables/sim_cohort.csv")
    real = rd("tables/real_people.csv")

    P("=" * 78)
    P("CONTROL (i): IS THE 244 CHAIN A NO-OP ON THE SIM SIDE?")
    P("=" * 78)
    P("A rendered AI-deck frame is 324x244, so its centre crop is natively 244 px.")
    P("Resampling it to 244 before firmware_preprocess must change nothing at all.")
    P("")
    P(f"{'sim set':<34}{'n frames':>10}{'max |chip - chip_via244|':>28}{'n differing':>13}")
    allok = True
    for name, rows in (("main (s15 + s01 person cells)", sim_main),
                       ("cohort (267 rendered people)", sim_coh)):
        d = np.array([abs(float(r["chip"]) - float(r["chip_via244"])) for r in rows])
        P(f"{name:<34}{len(rows):>10}{d.max():>28.4f}{int((d > 0).sum()):>13}")
        allok &= (d.max() == 0.0)
    for arm in ("float", "fq"):
        d = np.array([abs(float(r[arm]) - float(r[f"{arm}_via244"]))
                      for r in sim_main + sim_coh])
        P(f"{'  (' + arm + ', both sim sets)':<34}{len(sim_main) + len(sim_coh):>10}"
          f"{d.max():>28.4f}{int((d > 0).sum()):>13}")
    P("")
    P(f"VERDICT (i): {'PASS - bit-identical on the chip arm over every rendered frame.' if allok else 'FAIL - the control is not a no-op on the sim side.'}")
    P("             (float/fq move by a hair because PIL BILINEAR 244->128 is not")
    P("              the identity map even when the input is already 244; the chip")
    P("              arm, the one that flies, is exactly unchanged.)")
    P("")

    P("=" * 78)
    P("CONTROL (ii): DOES IT MOVE THE REAL SIDE, ON THE *CHIP* ARM?")
    P("=" * 78)
    P("The pet study validated this on `float` only, where PIL's antialiasing hides")
    P("the effect, and the headline was overstated 2.5x as a result. Chip first.")
    P("")
    band = [r for r in real if 38.8 <= float(r["px128_h"]) <= 103.6]
    sets = (("all people, whole slice", real),
            ("all people, flown band 38.8-103.6 px", band),
            ("whole_upright", [r for r in real if r["whole_upright"] == "1"]),
            ("wui (whole+upright+isolated)", [r for r in real if r["wui"] == "1"]))
    tsv = [("arm", "real_set", "n", "metric", "raw", "via244", "delta", "ci_lo", "ci_hi")]
    for arm in ("chip", "float", "fq"):
        P(f"--- {arm} arm " + "-" * 60)
        P(f"{'real set':<40}{'n':>6}{'>=0.75 raw':>12}{'>=0.75 via244':>15}{'delta':>9}{'95% CI':>20}")
        for nm, rows in sets:
            a = [float(r[arm]) for r in rows]
            b = [float(r[f"{arm}_via244"]) for r in rows]
            keys = [r["img_id"] for r in rows]
            for metric, stat in (("frac_ge_0.75", lambda v: float(np.mean(v >= BAR))),
                                 ("frac_lt_0.45", lambda v: float(np.mean(v < EXIT_BAR))),
                                 ("median", lambda v: float(np.median(v)))):
                fa, fb = stat(np.array(a)), stat(np.array(b))
                lo, hi = boot_pair_ci(a, b, keys, stat)
                tsv.append((arm, nm, len(rows), metric, f"{fa:.4f}", f"{fb:.4f}",
                            f"{fb - fa:+.4f}", f"{lo:+.4f}", f"{hi:+.4f}"))
                if metric == "frac_ge_0.75":
                    P(f"{nm:<40}{len(rows):>6}{fa:>12.3f}{fb:>15.3f}{fb - fa:>+9.3f}"
                      f"   [{lo:+.3f}, {hi:+.3f}]")
        P("")

    P("=" * 78)
    P("WHY: the stride firmware_preprocess actually samples at")
    P("=" * 78)
    crops = np.array([int(r["crop"]) for r in real], float)
    P(f"real photographs: centre crop {crops.min():.0f}-{crops.max():.0f} px, "
      f"median {np.median(crops):.0f}  ->  stride {np.median(crops) / 128:.2f}")
    P(f"rendered frames : centre crop 244 px                 ->  stride {244 / 128:.2f}")
    P(f"real via244     : centre crop resampled to 244 px    ->  stride {244 / 128:.2f}")
    P("")
    P("So sim `chip` pairs with real `chip_via244`, and raw `chip` on a 640-px")
    P("photograph corresponds to nothing the drone can ever see. Every chip number")
    P("in this directory's comparisons uses chip_via244 on the real side.")

    with open(D / "tables/control_resolution.tsv", "w", newline="") as f:
        csv.writer(f, delimiter="\t").writerows(tsv)
    (D / "tables/control_resolution.txt").write_text("\n".join(REPORT) + "\n")
    P("")
    P("wrote tables/control_resolution.tsv, tables/control_resolution.txt")


if __name__ == "__main__":
    main()
