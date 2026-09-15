#!/usr/bin/env python3
"""Turn 208 flights into the distribution the project has never had.

Every per-flight number comes from scoreboard.metrics_for_run, the scorer the
project already uses, called on each run directory. Nothing is recomputed by
hand.

Usage: nemoenv/bin/python analyze_pool.py <outdir>
"""
import csv
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path("/Users/saimaruvada/Downloads/drone/pytorch_ssd")
sys.path.insert(0, str(ROOT / "tools/crazysim_macos"))
import scoreboard as SB                                     # noqa: E402

OUT = Path(sys.argv[1])
SCR = Path("/private/tmp/claude-501/-Users-saimaruvada-Downloads/"
           "90541ca8-cca5-4400-9855-79d1dde551f0/scratchpad")
POOL = json.loads((OUT / "tables/pool.json").read_text())
RNG = np.random.default_rng(20260915)


def clopper_pearson(k, n, alpha=0.05):
    """exact binomial interval, no scipy"""
    if n == 0:
        return (float("nan"), float("nan"))
    def betainv(p, a, b):
        lo, hi = 0.0, 1.0
        for _ in range(200):
            mid = (lo + hi) / 2
            if betacdf(mid, a, b) < p: lo = mid
            else: hi = mid
        return (lo + hi) / 2
    def betacdf(x, a, b):
        if x <= 0: return 0.0
        if x >= 1: return 1.0
        # regularised incomplete beta by continued fraction
        import math
        lbeta = math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)
        front = math.exp(math.log(x) * a + math.log(1 - x) * b - lbeta) / a
        f, c, d = 1.0, 1.0, 0.0
        for i in range(0, 300):
            m = i // 2
            if i == 0: num = 1.0
            elif i % 2 == 0: num = (m * (b - m) * x) / ((a + 2*m - 1) * (a + 2*m))
            else: num = -((a + m) * (a + b + m) * x) / ((a + 2*m) * (a + 2*m + 1))
            d = 1.0 + num * d
            if abs(d) < 1e-30: d = 1e-30
            d = 1.0 / d
            c = 1.0 + num / c
            if abs(c) < 1e-30: c = 1e-30
            f *= c * d
            if abs(1.0 - c * d) < 1e-12: break
        return front * (f - 1.0)
    lo = 0.0 if k == 0 else betainv(alpha / 2, k, n - k + 1)
    hi = 1.0 if k == n else betainv(1 - alpha / 2, k + 1, n - k)
    return (lo, hi)


def spearman(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    ra = np.argsort(np.argsort(a)).astype(float)
    rb = np.argsort(np.argsort(b)).astype(float)
    if ra.std() == 0 or rb.std() == 0:
        return float("nan")
    return float(np.corrcoef(ra, rb)[0, 1])


def panel_geom(scene):
    m = json.loads((SCR / "pool_scenes" / scene / "manifest.json").read_text())
    s = m["subjects"][0]
    return s["panel"]["width_m"], s["background"]["subject_fraction"]


def main():
    subj = {p["img_id"]: p for p in POOL["keepers"]}
    ctl = POOL["control"]

    flights = []
    for rd in sorted((OUT / "runs").iterdir()):
        if not (rd / "summary.json").exists():
            continue
        cell, summary, rows, truth, manifest = SB.load_run(rd)
        if not rows or not cell:
            continue
        m, _ = SB.metrics_for_run(cell, summary, rows, truth, manifest)
        if "error" in m:
            continue
        cid = cell["cell_id"]
        who = cid.split("__")[1]
        ve, vx, cf, rec = SB.latch_rule(summary)
        w, sf = panel_geom(cell["scene"])
        trk = [1 if SB.fnum(r, "tracking") > 0.5 else 0
               for r in rows if r.get("event", "") == ""]
        t = [SB.fnum(r, "t") for r in rows if r.get("event", "") == ""]
        first = next((tt - t[0] for tt, x in zip(t, trk) if x), None)
        flights.append({
            "run": rd.name, "cell": cid, "subject": who,
            "cls": cell["scene_class"], "scene": cell["scene"],
            "repeat": cell["repeat"], "attempt": cell["attempt"],
            "index_pct": (ctl if who == "control" else subj[who])["index_pct"],
            "panel_w_m": round(w, 4), "subject_fraction": round(sf, 4),
            "M1": m.get("M1_tracking_fraction"),
            "ever_latched": int(any(trk)),
            "time_to_first_latch_s": None if first is None else round(float(first), 2),
            "M9_losses": len(m.get("M9_track_outage_all_s") or []),
            "M10_p05": m.get("M10_conf_p05_present"),
            "M2_mean": m.get("M2_heading_err_mean_deg"),
            "vis_enter": ve, "vis_exit": vx, "confirm_frames": cf,
        })

    if not flights:
        raise SystemExit("no scored flights yet")

    # the shipped rule must actually have flown, on every flight
    bars = {(f["vis_enter"], f["vis_exit"], f["confirm_frames"]) for f in flights}
    assert bars == {(0.75, 0.45, 3)}, f"latch rule was not the shipped one: {bars}"

    with open(OUT / "tables/flights.tsv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(flights[0]), delimiter="\t")
        w.writeheader()
        for f in flights:
            w.writerow(f)

    print(f"{len(flights)} scored flights, latch rule 0.75/0.45/3 on every one\n")

    # ---- per subject, per class -------------------------------------------
    for cls, name in (("A", "STATIC"), ("B", "MOVING")):
        g = [f for f in flights if f["cls"] == cls]
        if not g:
            continue
        print("=" * 92)
        print(f"{name} scenes: per-subject latch rate and tracking fraction")
        print("=" * 92)
        print(f"{'subject':>9}{'index':>7}{'n':>4}{'latched':>9}{'latch rate':>12}"
              f"{'95% CI':>18}{'M1 median':>11}{'M1 mean':>9}")
        order = sorted({f["subject"] for f in g},
                       key=lambda s: [f for f in g if f["subject"] == s][0]["index_pct"])
        for s in order:
            h = [f for f in g if f["subject"] == s]
            k, n = sum(f["ever_latched"] for f in h), len(h)
            lo, hi = clopper_pearson(k, n)
            m1 = [f["M1"] for f in h if f["M1"] is not None]
            tag = "  <- CONTROL" if s == "control" else ""
            print(f"{s:>9}{h[0]['index_pct']:>7.1f}{n:>4}{k:>9}{k/n:>12.3f}"
                  f"{f'[{lo:.3f}, {hi:.3f}]':>18}{np.median(m1):>11.3f}{np.mean(m1):>9.3f}{tag}")
        print()

    # ---- the headline ------------------------------------------------------
    print("=" * 92)
    print("THE HEADLINE: control vs the screened pool")
    print("=" * 92)
    for cls, name in (("A", "static"), ("B", "moving")):
        g = [f for f in flights if f["cls"] == cls]
        if not g:
            continue
        c = [f for f in g if f["subject"] == "control"]
        p = [f for f in g if f["subject"] != "control"]
        if not c or not p:
            continue
        ck, cn = sum(f["ever_latched"] for f in c), len(c)
        pk, pn = sum(f["ever_latched"] for f in p), len(p)
        clo, chi = clopper_pearson(ck, cn)
        plo, phi = clopper_pearson(pk, pn)
        print(f"  {name}: control latched {ck}/{cn} = {ck/cn:.3f} [{clo:.3f}, {chi:.3f}], "
              f"M1 median {np.median([f['M1'] for f in c]):.3f}")
        print(f"  {name:>7}  pool latched {pk}/{pn} = {pk/pn:.3f} [{plo:.3f}, {phi:.3f}], "
              f"M1 median {np.median([f['M1'] for f in p]):.3f}")
    print()

    # ---- subject-level relationship, with the covariates -------------------
    print("=" * 92)
    print("Does detectability predict flight?  Subject-level, pool only (control excluded:")
    print("it did not pass the screen its peers passed, so it is a reference, not a sample).")
    print("=" * 92)
    for cls, name in (("A", "static"), ("B", "moving")):
        g = [f for f in flights if f["cls"] == cls and f["subject"] != "control"]
        if not g:
            continue
        subs = sorted({f["subject"] for f in g})
        idx, lat, m1, wid, sf = [], [], [], [], []
        for s in subs:
            h = [f for f in g if f["subject"] == s]
            idx.append(h[0]["index_pct"])
            lat.append(np.mean([f["ever_latched"] for f in h]))
            m1.append(np.mean([f["M1"] for f in h if f["M1"] is not None]))
            wid.append(h[0]["panel_w_m"])
            sf.append(h[0]["subject_fraction"])
        print(f"  {name}, n = {len(subs)} subjects")
        print(f"    Spearman(index, latch rate)       = {spearman(idx, lat):+.3f}")
        print(f"    Spearman(index, mean M1)          = {spearman(idx, m1):+.3f}")
        print(f"    Spearman(panel width, latch rate) = {spearman(wid, lat):+.3f}   <- covariate")
        print(f"    Spearman(subj fraction, latch)    = {spearman(sf, lat):+.3f}   <- covariate")
        hi = [i for i, v in enumerate(idx) if v >= 60]
        if len(hi) >= 5:
            print(f"    within the HIGH cluster (n={len(hi)}, index "
                  f"{min(idx[i] for i in hi):.1f}-{max(idx[i] for i in hi):.1f}):")
            print(f"      Spearman(index, latch) = {spearman([idx[i] for i in hi], [lat[i] for i in hi]):+.3f}"
                  f"   Spearman(width, latch) = {spearman([wid[i] for i in hi], [lat[i] for i in hi]):+.3f}")
        # cluster bootstrap over subjects for the pooled latch rate
        boot = []
        for _ in range(10000):
            pick = RNG.choice(len(subs), len(subs), replace=True)
            boot.append(np.mean([lat[i] for i in pick]))
        print(f"    pooled subject-level latch rate {np.mean(lat):.3f} "
              f"[{np.percentile(boot, 2.5):.3f}, {np.percentile(boot, 97.5):.3f}] "
              f"(cluster bootstrap over subjects, 10k)")
        print()

    json.dump(flights, open(OUT / "tables/flights.json", "w"), indent=1)
    print(f"wrote tables/flights.tsv and tables/flights.json")


if __name__ == "__main__":
    main()
