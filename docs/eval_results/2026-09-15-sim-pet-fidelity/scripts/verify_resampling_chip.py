#!/usr/bin/env python3
"""SKEPTIC RE-DERIVATION, 2026-09-14 (second pass over this folder).

Three things this script establishes, all from the folder's own CSVs, none of
them requiring a re-render or a re-score:

1. THE CHIP ARM'S REAL SIDE WAS NOT RESOLUTION-MATCHED TO ITS SIM SIDE.
   `perception_backends.firmware_preprocess` is the C port: nearest-neighbour
   source sampling plus a 2x2 box average, integer arithmetic. It does NOT
   antialias. A rendered frame reaches it as a 244-px crop (stride 244/128 =
   1.9, so the 2x2 block covers nearly every source pixel); a COCO photograph
   reaches it as a 480-640-px crop (stride 3.75+, so the 2x2 block samples
   about a quarter of the pixels and aliases the rest away). Same network, same
   threshold, DIFFERENT input chain - which is the condition mismatch this
   project has already been burned by once.
   The control already exists in the CSVs: `chip_via244` puts the photograph
   through the frame's own chain (crop -> 244 bilinear -> firmware_preprocess)
   first.  On the SIM side chip and chip_via244 are bit-identical, because a
   sim frame is natively a 244 crop - so chip_via244 is the apples-to-apples
   pairing and raw `chip` is not.
   The float and fq arms are unaffected: their preprocessing is PIL BILINEAR,
   which antialiases at any input resolution.

2. THE LATCH BAND IS AN *AND* OF TWO FILTERS, not one band stated two ways.
   README and headline_numbers.txt section C label it "2.0-2.75 m = 22-32
   px128_h". The sim side that produced 0.593/0.611/0.574 is
   `range_m in [2.0, 2.75] AND px128_h in [22, 32]`, which drops the two poses
   at r=2.75, dy=+/-0.25 (px128_h 21.51).  Those are the smallest and lowest-
   scoring poses in the band, so the AND raises the sim's own number.

3. THE CAT "SAME IMAGE BOTH WAYS" PAIR IS UNDETERMINED.
   cat_petlevel has two ranges, 0.25 m and 0.28 m, that BOTH report
   px128_h = 128.0, because the panel overflows the centre crop and the measure
   saturates. analyze.py's tie-break picks 0.28 and analyze_same_image.py's
   picks 0.25, so tables/same_image.tsv and tables/same_image_summary.tsv give
   contradictory numbers for the same row.

Usage: nemoenv/bin/python verify_resampling_chip.py <dir>
"""
import csv
import sys
from pathlib import Path

import numpy as np

D = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parents[1])
BINS = [(8, 15), (15, 25), (25, 40), (40, 55), (55, 80), (80, 129)]
BAR = 0.75
RNG = np.random.default_rng(0)
OUT = []


def P(s=""):
    print(s, flush=True)
    OUT.append(s)


def rd(p):
    return list(csv.DictReader(open(D / "tables" / p)))


def f(r, k):
    return float(r[k])


def key(r):
    return r["img_id"] if "img_id" in r else f"{r['job']}|{r['range_m']}|{r['dy_m']}"


def main():
    sim, real, rh = rd("sim_pets.csv"), rd("real_pets.csv"), rd("real_pets_himax.csv")
    rows_out = []

    P("=" * 78)
    P("0. IS chip_via244 THE RIGHT PAIRING?  On the SIM side it must be a no-op,")
    P("   because a rendered frame is already a 244 crop.")
    P("=" * 78)
    for a in ("float", "fq", "chip"):
        d = np.array([abs(f(r, a) - f(r, a + "_via244")) for r in sim])
        P(f"   sim {a:6s} max |arm - arm_via244| = {d.max():.4f}   (n={len(d)})")
    P("   -> chip_via244 changes nothing on the sim side, so comparing")
    P("      sim chip against real chip_via244 changes only the REAL side's chain.")

    P("")
    P("=" * 78)
    P("1. WHOLE SLICE (n=771), one threshold at a time, raw photo vs same photo")
    P("   through the frame's own resampling chain.")
    P("=" * 78)
    P(f"   {'arm':6s} {'>=0.45 raw':>11s} {'via244':>8s} {'>=0.75 raw':>11s} {'via244':>8s} {'med raw':>8s} {'via244':>8s}")
    for a in ("float", "fq", "chip"):
        v = np.array([f(r, a) for r in real])
        w = np.array([f(r, a + "_via244") for r in real])
        P(f"   {a:6s} {np.mean(v >= .45):11.3f} {np.mean(w >= .45):8.3f} "
          f"{np.mean(v >= .75):11.3f} {np.mean(w >= .75):8.3f} {np.median(v):8.3f} {np.median(w):8.3f}")
    P("   float/fq move by <=0.009 at 0.45 and <=0.007 at 0.75; chip moves by")
    P("   +0.080 at 0.45 and +0.027 at 0.75.  'The resampling chain is not a")
    P("   confound' was verified on float and is FALSE on chip.")

    P("")
    P("=" * 78)
    P("2. DECOMPOSING the raw -> himax change on the 245 dog/cat photographs.")
    P("   real_pets_himax.py already resizes the crop to 244 BEFORE the sensor")
    P("   model, so its arm carries resampling AND sensor. via244 isolates the")
    P("   resampling half.  Fraction >= 0.75 throughout.")
    P("=" * 78)
    dc = [r for r in real if r["subject_cat"] in ("dog", "cat")]
    ids = {r["img_id"] for r in dc}
    hh = [r for r in rh if r["img_id"] in ids]
    P(f"   {'arm':6s} {'raw photo':>10s} {'+resample':>10s} {'+resample+sensor':>17s} "
      f"{'resample part':>14s} {'sensor part':>12s}")
    for a in ("float", "fq", "chip"):
        raw = np.mean(np.array([f(r, a) for r in dc]) >= BAR)
        v24 = np.mean(np.array([f(r, a + "_via244") for r in dc]) >= BAR)
        him = np.mean(np.array([f(r, a) for r in hh]) >= BAR)
        P(f"   {a:6s} {raw:10.3f} {v24:10.3f} {him:17.3f} {v24 - raw:+14.3f} {him - v24:+12.3f}")
        rows_out.append({"section": "2_camera_decomposition", "arm": a, "comparison_set": "dog+cat photos",
                         "metric": "frac>=0.75", "as_published": round(float(raw), 4),
                         "resolution_matched": round(float(v24), 4), "ratio_published": "",
                         "ratio_corrected": "", "note": f"himax(resample+sensor)={him:.3f}"})
    P("   On chip the RESAMPLING moves it +0.049 and the SENSOR -0.020.  README")
    P("   section (b) attributes the whole 0.114 -> 0.143 to the camera model.")

    P("")
    P("=" * 78)
    P("3. SIZE-STANDARDISED ABOVE-BAR RATIO, sim dog (eye line, himax, 1.0-4.0 m)")
    P("   against real photographs reweighted to the sim's own size mix. Cluster")
    P("   bootstrap (a photo is one cluster, a pose is one cluster), 2000 draws,")
    P("   single 0.75 bar on both sides.")
    P("=" * 78)
    G = {"sim": [r for r in sim if r["job"] == "dog_eye" and r["camera"] == "himax"
                 and 1.0 <= f(r, "range_m") <= 4.0],
         "allpets": real,
         "dogs": [r for r in real if r["subject_cat"] == "dog"]}

    def inb(rows, lo, hi):
        return [r for r in rows if lo <= f(r, "px128_h") < hi]

    def std_ci(rg, col, nboot=2000):
        bins = []
        for lo, hi in BINS:
            a, b = inb(G["sim"], lo, hi), inb(G[rg], lo, hi)
            if not a or len({key(r) for r in b}) < 3:
                continue
            bins.append((len(a), b, a))
        ws = sum(w for w, _, _ in bins)

        def one(resample):
            fr = sf = 0.0
            sn = 0
            for w, b, a in bins:
                if resample:
                    ks = sorted({key(r) for r in b}); ib = {k: [r for r in b if key(r) == k] for k in ks}
                    b = [r for k in RNG.choice(ks, len(ks), replace=True) for r in ib[k]]
                    ka = sorted({key(r) for r in a}); ia = {k: [r for r in a if key(r) == k] for k in ka}
                    a = [r for k in RNG.choice(ka, len(ka), replace=True) for r in ia[k]]
                fr += w * np.mean(np.array([f(r, col) for r in b]) >= BAR)
                sf += float(np.sum(np.array([f(r, "chip") for r in a]) >= BAR)); sn += len(a)
            return sf / sn, fr / ws
        s, rf = one(False)
        bt = np.array([(lambda x, y: x / y if y > 0 else np.inf)(*one(True)) for _ in range(nboot)])
        fin = bt[np.isfinite(bt)]
        lo_, hi_ = ((np.percentile(fin, 2.5), np.percentile(fin, 97.5))
                    if len(fin) > 0.5 * nboot else (float("nan"), float("nan")))
        return s, rf, (s / rf if rf > 0 else float("inf")), lo_, hi_

    P(f"   {'real set':9s} {'real chain':12s} {'sim>=bar':>9s} {'real>=bar':>10s} {'ratio':>7s} {'95% CI':>18s}")
    for rg in ("allpets", "dogs"):
        for col in ("chip", "chip_via244"):
            s, rf, ra, lo_, hi_ = std_ci(rg, col)
            P(f"   {rg:9s} {('as published' if col == 'chip' else 'matched 244'):12s} "
              f"{s:9.4f} {rf:10.4f} {ra:7.2f} {('[%.2f, %.2f]' % (lo_, hi_)) if np.isfinite(lo_) else '[undefined]':>18s}")
            rows_out.append({"section": "3_size_standardised_ratio", "arm": "chip",
                             "comparison_set": rg, "metric": "frac>=0.75 ratio",
                             "as_published": round(float(rf), 4) if col == "chip" else "",
                             "resolution_matched": round(float(rf), 4) if col != "chip" else "",
                             "ratio_published": round(float(ra), 2) if col == "chip" and np.isfinite(ra) else ("inf" if col == "chip" else ""),
                             "ratio_corrected": round(float(ra), 2) if col != "chip" else "",
                             "note": f"sim={s:.4f}; CI [{lo_:.2f},{hi_:.2f}]" if np.isfinite(lo_) else f"sim={s:.4f}; CI undefined (real rate 0)"})

    P("")
    P("=" * 78)
    P("4. THE LATCH BAND, and how much its headline depends on how it is cut.")
    P("   All three cuts scored at the SAME 0.75 bar; real side always the same")
    P("   photographs at px128_h in [22, 32].")
    P("=" * 78)
    band = [r for r in sim if r["job"] == "dog_eye" and r["camera"] == "himax"]
    cuts = {
        "range 2.0-2.75 AND px 22-32 (as published)":
            [r for r in band if 2.0 <= f(r, "range_m") <= 2.75 and 22 <= f(r, "px128_h") <= 32],
        "range 2.0-2.75 only": [r for r in band if 2.0 <= f(r, "range_m") <= 2.75],
        "px 22-32 only (pulls in 0.35-0.45 m)": [r for r in band if 22 <= f(r, "px128_h") <= 32],
    }
    rdog = [r for r in real if r["subject_cat"] == "dog" and 22 <= f(r, "px128_h") <= 32]
    rall = [r for r in real if 22 <= f(r, "px128_h") <= 32]
    for lab, s in cuts.items():
        P(f"\n   {lab}:  n={len(s)} frames, {len({(r['range_m'], r['dy_m']) for r in s})} poses")
        for a in ("float", "fq", "chip"):
            v = np.array([f(r, a) for r in s])
            P(f"      {a:6s} sim med {np.median(v):.3f}  >=0.75 {np.mean(v >= BAR):.3f}")
    P(f"\n   real side at px 22-32: dogs n={len(rdog)} photos, all pets n={len(rall)} photos")
    for a in ("float", "fq", "chip"):
        dv = np.array([f(r, a) for r in rdog]); dw = np.array([f(r, a + "_via244") for r in rdog])
        av = np.array([f(r, a) for r in rall]); aw = np.array([f(r, a + "_via244") for r in rall])
        P(f"      {a:6s} dogs raw {np.mean(dv >= BAR):.3f} / matched-244 {np.mean(dw >= BAR):.3f}   "
          f"all pets raw {np.mean(av >= BAR):.3f} / matched-244 {np.mean(aw >= BAR):.3f}")
        rows_out.append({"section": "4_latch_band", "arm": a, "comparison_set": "real pets px22-32",
                         "metric": "frac>=0.75", "as_published": round(float(np.mean(av >= BAR)), 4),
                         "resolution_matched": round(float(np.mean(aw >= BAR)), 4),
                         "ratio_published": "", "ratio_corrected": "",
                         "note": "sim(as published) 0.593/0.611/0.574 by arm"})

    P("")
    P("=" * 78)
    P("5. THE CAT SAME-IMAGE PAIR IS A TIE.  Both cat_petlevel ranges report")
    P("   px128_h = 128.0 because the panel overflows the crop and the measure")
    P("   saturates; they are NOT the same picture.")
    P("=" * 78)
    for rng in ("0.25", "0.28"):
        rr = [r for r in sim if r["job"] == "cat_petlevel" and r["range_m"] == rng]
        c = [r for r in rr if r["camera"] == "clean"][0]
        P(f"\n   cat_petlevel r={rng} m  px128_h {c['px128_h']}  geometric {c['px128_h_geom']}  "
          f"visible_fraction {c['visible_fraction']}  touches_edge {c['touches_frame_edge']}")
        for a in ("float", "fq", "chip"):
            h = np.mean([f(r, a) for r in rr if r["camera"] == "himax"])
            P(f"      {a:6s} clean {f(c, a):.4f}   himax mean {h:.4f}")
    rp = [r for r in real if int(r["img_id"]) == 131938][0]
    P(f"\n   photograph 131938 direct: " + "  ".join(f"{a} {f(rp, a):.4f}" for a in ("float", "fq", "chip")))
    P("   -> d_clean (render - photo) is +0.05..+0.21 with the 0.25 m render")
    P("      (what README and same_image_summary.tsv quote) and -0.26..+0.05")
    P("      with the 0.28 m render (what same_image.tsv quotes). The sign flips")
    P("      on two of three arms. The cat same-image result is undetermined.")
    P("   The DOG pair is not affected: dog_petlevel r=0.5 m has px128_h 119.61")
    P("      against the photo's 119.91, visible_fraction 1.007, touches_edge 0 -")
    P("      a genuine, unambiguous pair.")

    with open(D / "tables/chip_resampling_correction.tsv", "w", newline="") as fh:
        w = csv.DictWriter(fh, delimiter="\t", fieldnames=[
            "section", "arm", "comparison_set", "metric", "as_published",
            "resolution_matched", "ratio_published", "ratio_corrected", "note"])
        w.writeheader()
        w.writerows(rows_out)
    (D / "tables/verify_resampling_chip.txt").write_text("\n".join(OUT) + "\n")
    P("")
    P("wrote tables/chip_resampling_correction.tsv and tables/verify_resampling_chip.txt")


if __name__ == "__main__":
    main()
