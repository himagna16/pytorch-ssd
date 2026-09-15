#!/usr/bin/env python3
"""AUDIT ADDENDUM: the paired render-vs-photo test, with the SENSOR stage matched.

Why this file exists. `analyze_person.py` builds the paired test as

    d = render THROUGH camera_model.himax_typical  -  photograph on *_via244

i.e. the render carries the sensor model and the photograph does not. The
resolution chain is matched (that is what §2 is about) but the SENSOR chain is
not, and §4(f) of the README measures that same sensor stage costing real
photographs 0.03-0.18 of above-bar rate. The project's own rule is that the two
sides must not travel through different chains, so the headline paired number
is measured here all three ways:

    clean  vs *_via244    both sides with NO sensor model      (matched)
    himax  vs himax       both sides THROUGH the sensor model  (matched)
    himax  vs *_via244    what the README quotes               (UNMATCHED)

The photograph's himax arm is read from tables/real_people_himax.csv (3 draws
per photograph, averaged), which `real_people_himax.py` asserts is already
244-matched before the sensor model, so the resolution chain stays matched in
every row.

Writes tables/paired_chain_matched.tsv. Nothing else in the directory changes.

Usage: nemoenv/bin/python audit_paired_chain.py <study_dir>
"""
import csv
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from shared_arms import relabel, BAR, EXIT_BAR  # noqa: E402

RNG = np.random.default_rng(20260915)
ARMS = ("float", "fq", "chip")
SA = {a: a for a in ARMS}                      # sim/render arm column
RA = {a: a + "_via244" for a in ARMS}          # photograph, resolution-matched


def boot(d, stat, n=4000):
    d = np.asarray(d, float)
    if len(d) < 3:
        return float("nan"), float("nan")
    o = np.array([stat(RNG.choice(d, len(d), replace=True)) for _ in range(n)])
    return float(np.percentile(o, 2.5)), float(np.percentile(o, 97.5))


def main():
    D = Path(sys.argv[1])
    rd = lambda p: list(csv.DictReader(open(D / p)))          # noqa: E731
    real = {r["img_id"]: r for r in rd("tables/real_people.csv")}
    coh = relabel(rd("tables/sim_cohort.csv"), real)
    ph = {}
    for r in rd("tables/real_people_himax.csv"):
        ph.setdefault(r["img_id"], []).append(r)

    by = {}
    for r in coh:
        by.setdefault(r["img_id"], []).append(r)

    out = [("pairing", "chain_matched", "arm", "stratum", "n_subjects", "median_d", "d_lo", "d_hi",
            "photo_frac_ge075", "render_frac_ge075", "d_frac", "df_lo", "df_hi",
            "photo_frac_lt045", "render_frac_lt045", "d_exit", "de_lo", "de_hi")]
    rep = []
    for label, cam, pmode, matched in (("clean vs via244", "clean", "via244", "yes"),
                                       ("himax vs himax", "himax", "himax", "yes"),
                                       ("himax vs via244", "himax", "via244", "NO")):
        for stratum in ("whole_upright", "wui"):
            for arm in ARMS:
                ds, pf, rf, pe, re_ = [], [], [], [], []
                for iid, g in by.items():
                    rows = [r for r in g if r["is_r_match"] == "1" and r["camera"] == cam
                            and r["dy_m"] == "0.0" and r[stratum] == "1"]
                    if not rows or iid not in real:
                        continue
                    rv = float(np.mean([float(r[SA[arm]]) for r in rows]))
                    if pmode == "via244":
                        pv = float(real[iid][RA[arm]])
                    else:
                        pv = float(np.mean([float(x[arm]) for x in ph[iid]]))
                    ds.append(rv - pv)
                    rf.append(rv >= BAR); pf.append(pv >= BAR)
                    re_.append(rv < EXIT_BAR); pe.append(pv < EXIT_BAR)
                if len(ds) < 3:
                    continue
                lo, hi = boot(ds, np.median)
                dfr = np.mean(rf) - np.mean(pf)
                dex = np.mean(re_) - np.mean(pe)
                flo, fhi = boot(np.array(rf, float) - np.array(pf, float), np.mean)
                elo, ehi = boot(np.array(re_, float) - np.array(pe, float), np.mean)
                out.append((label, matched, arm, stratum, len(ds), f"{np.median(ds):+.4f}",
                            f"{lo:+.4f}", f"{hi:+.4f}", f"{np.mean(pf):.4f}", f"{np.mean(rf):.4f}",
                            f"{dfr:+.4f}", f"{flo:+.4f}", f"{fhi:+.4f}", f"{np.mean(pe):.4f}",
                            f"{np.mean(re_):.4f}", f"{dex:+.4f}", f"{elo:+.4f}", f"{ehi:+.4f}"))
                if arm == "chip":
                    rep.append(f"  {label:<18}{'matched' if matched=='yes' else 'UNMATCHED':<11}"
                               f"{stratum:<15}n={len(ds):<5}median d {np.median(ds):+.3f} "
                               f"[{lo:+.3f},{hi:+.3f}]   >=0.75 {np.mean(pf):.3f} -> {np.mean(rf):.3f}"
                               f"   <0.45 {np.mean(pe):.3f} -> {np.mean(re_):.3f}")
    print("PAIRED render minus photograph, chip arm, matched apparent size, dy=0:")
    print("\n".join(rep))

    # the compression regression, and how far it is from the independence null
    print("\nCOMPRESSION REGRESSION vs the independence null (chip, whole_upright):")
    for label, cam, pmode in (("himax vs via244 (README)", "himax", "via244"),
                              ("clean vs via244", "clean", "via244"),
                              ("himax vs himax", "himax", "himax")):
        ids, x, y = [], [], []
        for iid, g in by.items():
            rows = [r for r in g if r["is_r_match"] == "1" and r["camera"] == cam
                    and r["dy_m"] == "0.0" and r["whole_upright"] == "1"]
            if not rows or iid not in real:
                continue
            y.append(float(np.mean([float(r["chip"]) for r in rows])))
            x.append(float(real[iid]["chip_via244"]) if pmode == "via244"
                     else float(np.mean([float(v["chip"]) for v in ph[iid]])))
            ids.append(iid)
        x, y = np.array(x), np.array(y)
        sl, ic = np.polyfit(x, y - x, 1)
        byx = np.polyfit(x, y, 1)[0]
        r_ = float(np.corrcoef(x, y)[0, 1])
        perm = [np.polyfit(x, RNG.permutation(y) - x, 1) for _ in range(1000)]
        ps = np.array([p[0] for p in perm]); pfp = np.array([-p[1] / p[0] for p in perm])
        print(f"  {label:<26} n={len(x)} slope_d {sl:+.3f}  fixed_pt {-ic/sl:.3f}   "
              f"beta(render|photo) {byx:+.3f}  r {r_:+.3f}  mean(render) {y.mean():.3f}   "
              f"NULL slope {ps.mean():+.3f} [{np.percentile(ps,2.5):+.3f},{np.percentile(ps,97.5):+.3f}] "
              f"fixed_pt {pfp.mean():.3f}")
    with open(D / "tables/paired_chain_matched.tsv", "w", newline="") as f:
        csv.writer(f, delimiter="\t").writerows(out)
    print("\nwrote", D / "tables/paired_chain_matched.tsv")


if __name__ == "__main__":
    main()
