#!/usr/bin/env python3
"""Turn 208 flights into the distribution the project has never had.

Every per-flight number comes from scoreboard.metrics_for_run, the scorer the
project already uses, called on each run directory. Nothing is recomputed by
hand.

Usage: nemoenv/bin/python analyze_pool.py <outdir>
"""
import csv
import itertools
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
        flown = [r for r in rows if r.get("event", "") == ""]
        trk = np.array([1 if SB.fnum(r, "tracking") > 0.5 else 0 for r in flown])
        t = np.array([SB.fnum(r, "t") for r in flown])
        conf = np.array([SB.fnum(r, "conf") for r in flown])
        dt = np.diff(t, prepend=t[0])
        first = next((tt - t[0] for tt, x in zip(t, trk) if x), None)
        # A flight that NEVER latched has zero M9 losses, byte-identical to a
        # flight that tracked perfectly, because scoreboard.py:564 builds the
        # loss list only from a 1->0 transition. These three do not have that
        # blind spot; the precursor's analyze_typical.py introduced them for
        # exactly this reason.
        untracked_s = float(np.sum(dt[trk == 0]))
        above = conf >= ve
        runs_ = [len(list(g)) for k, g in itertools.groupby(above) if k]
        flights.append({
            "run": rd.name, "cell": cid, "subject": who,
            "cls": cell["scene_class"], "scene": cell["scene"],
            "repeat": cell["repeat"], "attempt": cell["attempt"],
            "index_pct": (ctl if who == "control" else subj[who])["index_pct"],
            "conf_flown_range": (ctl if who == "control" else subj[who])["conf_flown_range"],
            "panel_w_m": round(w, 4), "subject_fraction": round(sf, 4),
            "M1": m.get("M1_tracking_fraction"),
            "ever_latched": int(any(trk)),
            "time_to_first_latch_s": None if first is None else round(float(first), 2),
            "untracked_time_total_s": round(untracked_s, 2),
            "frames_above_enter": int(above.sum()),
            "longest_above_enter_run": max(runs_) if runs_ else 0,
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

    # ---- the estimand: a two-group contrast, NOT a slope --------------------
    # The 12 subjects sit in two clouds, index 28.4-52.1 (n=5) and 86.8-93.9
    # (n=7), with a 34.7-point hole. Every step function with a threshold
    # anywhere in that hole fits the data identically, so a correlation or a
    # slope over the 12 would look like a dose-response curve while measuring
    # only "the two clouds differ". The estimand is the contrast; rank
    # correlations are printed as diagnostics with the identified set beside
    # them, never as the headline.
    LOW_MAX, HIGH_MIN = 52.1, 86.8
    print("=" * 92)
    print("THE ESTIMAND: low group (index <= 52.1, n=5) vs high group (index >= 86.8, n=7)")
    print("Control excluded: it has wui == 0 and would not pass the screen its peers passed.")
    print("=" * 92)
    for cls, name in (("A", "static"), ("B", "moving")):
        g = [f for f in flights if f["cls"] == cls and f["subject"] != "control"]
        if not g:
            continue
        subs = sorted({f["subject"] for f in g})
        rec = {}
        for sname in subs:
            h = [f for f in g if f["subject"] == sname]
            rec[sname] = {
                "index": h[0]["index_pct"], "conf": h[0]["conf_flown_range"],
                "width": h[0]["panel_w_m"], "sf": h[0]["subject_fraction"],
                "latch": float(np.mean([f["ever_latched"] for f in h])),
                "m1": float(np.mean([f["M1"] for f in h if f["M1"] is not None])),
                "untracked": float(np.mean([f["untracked_time_total_s"] for f in h])),
                "longrun": float(np.mean([f["longest_above_enter_run"] for f in h])),
                "n": len(h)}
        lo = [v for v in rec.values() if v["index"] <= LOW_MAX]
        hi = [v for v in rec.values() if v["index"] >= HIGH_MIN]
        if not lo or not hi:
            continue
        for key, lbl in (("latch", "latch rate"), ("m1", "mean M1")):
            dl = np.mean([v[key] for v in lo]); dh = np.mean([v[key] for v in hi])
            boot = []
            for _ in range(20000):
                a = RNG.choice(len(lo), len(lo), replace=True)
                b = RNG.choice(len(hi), len(hi), replace=True)
                boot.append(np.mean([lo[i][key] for i in a]) - np.mean([hi[i][key] for i in b]))
            print(f"  {name:>7} {lbl:<11} low {dl:.3f}  high {dh:.3f}  "
                  f"difference {dl - dh:+.3f} "
                  f"[{np.percentile(boot, 2.5):+.3f}, {np.percentile(boot, 97.5):+.3f}]  "
                  f"(cluster bootstrap over subjects, 20k)")
        print(f"  {name:>7} untracked s  low {np.mean([v['untracked'] for v in lo]):.1f}  "
              f"high {np.mean([v['untracked'] for v in hi]):.1f}     "
              f"longest run >=0.75 (need 3): low {np.mean([v['longrun'] for v in lo]):.1f}  "
              f"high {np.mean([v['longrun'] for v in hi]):.1f}")
        print()

    print("=" * 92)
    print("DIAGNOSTICS ONLY - these are ranks over 12 points in two clouds")
    print("=" * 92)
    print("  No subject was flown with an index between 52.1 and 86.8, so the location and")
    print("  shape of the transition are NOT estimated. Any threshold in that interval fits.")
    print("  In confidence terms the unflown gap is 0.653 to 0.833 mean chip confidence at")
    print("  the flown range; the follower's own 0.75 enter bar lies inside it.")
    for cls, name in (("A", "static"), ("B", "moving")):
        g = [f for f in flights if f["cls"] == cls and f["subject"] != "control"]
        if not g:
            continue
        subs = sorted({f["subject"] for f in g})
        idx, cf, lat, wid, sf = [], [], [], [], []
        for sname in subs:
            h = [f for f in g if f["subject"] == sname]
            idx.append(h[0]["index_pct"]); cf.append(h[0]["conf_flown_range"])
            wid.append(h[0]["panel_w_m"]); sf.append(h[0]["subject_fraction"])
            lat.append(np.mean([f["ever_latched"] for f in h]))
        print(f"  {name}, n = {len(subs)} subjects")
        print(f"    rho(index, latch) {spearman(idx, lat):+.3f}   "
              f"rho(conf@flown, latch) {spearman(cf, lat):+.3f}   "
              f"rho(width, latch) {spearman(wid, lat):+.3f}   "
              f"rho(subj frac, latch) {spearman(sf, lat):+.3f}")
        hicl = [i for i, v in enumerate(idx) if v >= HIGH_MIN]
        if len(hicl) >= 5:
            print(f"    WITHIN the high cloud (n={len(hicl)}, index "
                  f"{min(idx[i] for i in hicl):.1f}-{max(idx[i] for i in hicl):.1f}): "
                  f"rho(index) {spearman([idx[i] for i in hicl], [lat[i] for i in hicl]):+.3f}  "
                  f"rho(width) {spearman([wid[i] for i in hicl], [lat[i] for i in hicl]):+.3f}")
            print("      If width beat index here, the trend would be the card, not the person.")
    print()

    json.dump(flights, open(OUT / "tables/flights.json", "w"), indent=1)
    print(f"wrote tables/flights.tsv and tables/flights.json")


if __name__ == "__main__":
    main()
