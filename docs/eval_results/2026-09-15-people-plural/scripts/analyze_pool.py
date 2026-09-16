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


def _rank(x):
    """midrank, so ties get the same rank.

    The first version of this used argsort(argsort(x)), which hands tied values
    distinct ranks in whatever order the caller happened to iterate. Latch rate
    is mostly ties here (7 of 12 static subjects at exactly 0.000, 7 of 12 moving
    at exactly 1.000), so every rho it printed depended on subject ordering, and
    rho(subject fraction, latch) even changed sign under a different ordering.
    """
    x = np.asarray(x, float)
    order = np.argsort(x, kind="mergesort")
    r = np.empty(len(x), float)
    r[order] = np.arange(len(x), dtype=float)
    # average the ranks within each tie group
    i = 0
    xs = x[order]
    while i < len(xs):
        j = i
        while j + 1 < len(xs) and xs[j + 1] == xs[i]:
            j += 1
        if j > i:
            r[order[i:j + 1]] = np.mean(np.arange(i, j + 1, dtype=float))
        i = j + 1
    return r


def spearman(a, b):
    """tie-corrected, and nan when either side is constant.

    A constant outcome has no rank order, so a correlation against it is not
    small, it is undefined. The earlier version returned a number: all seven
    moving high-cloud subjects latch at exactly 1.000, and it printed
    rho(width) = +0.607 against rho(index) = -0.071 on that constant vector,
    which read as evidence for precisely the confound it was meant to rule out.
    """
    a, b = np.asarray(a, float), np.asarray(b, float)
    if a.std() == 0 or b.std() == 0:
        return float("nan")
    ra, rb = _rank(a), _rank(b)
    if ra.std() == 0 or rb.std() == 0:
        return float("nan")
    return float(np.corrcoef(ra, rb)[0, 1])


def fmt_rho(v):
    return "  undefined" if np.isnan(v) else f"{v:+.3f}".rjust(10)



def _m2_tracked(cell, summary, rows, truth, manifest):
    """mean |bearing error| over settled frames where the follower was tracking."""
    flown = [r for r in rows if r.get("event", "") == ""]
    sub = SB.target_subject(manifest)
    if not flown or truth is None or sub is None:
        return None
    t = np.array([SB.fnum(r, "t") for r in flown])
    wall = np.array([SB.fnum(r, "wall") for r in flown])
    px = np.array([SB.fnum(r, "px") for r in flown])
    py = np.array([SB.fnum(r, "py") for r in flown])
    yaw = np.array([SB.fnum(r, "yaw") for r in flown])
    trk = np.array([SB.fnum(r, "tracking") > 0.5 for r in flown])
    body = (sub.get("truth") or {}).get("body", sub["name"])
    bx, by = truth[2][body] if body in truth[2] else list(truth[2].values())[0]
    tx, ty = np.interp(wall, truth[0], bx), np.interp(wall, truth[0], by)
    brg = (np.degrees(np.arctan2(ty - py, tx - px)) - yaw + 180) % 360 - 180
    sel = trk & ((t - t[0]) > SB.SETTLE_S)
    return round(float(np.mean(np.abs(brg[sel]))), 2) if sel.any() else None


def conf_and_range(rd):
    """(conf, d_true) per flown frame, computed the way scoreboard.py:445-464 does.

    d_true is the distance from the DRONE (px, py in the follower log) to the
    TARGET, whose track comes from the truth log interpolated onto the
    follower's wall clock. An earlier version of this script used hypot(px, py),
    which is the drone's distance from the origin, and found no frames in band.
    """
    cell, summary, rows, truth, manifest = SB.load_run(rd)
    flown = [r for r in rows if r.get("event", "") == ""]
    if not flown or truth is None:
        return None, None
    sub = SB.target_subject(manifest)
    if sub is None:
        return None, None
    wall = np.array([SB.fnum(r, "wall") for r in flown])
    px = np.array([SB.fnum(r, "px") for r in flown])
    py = np.array([SB.fnum(r, "py") for r in flown])
    conf = np.array([SB.fnum(r, "conf") for r in flown])
    body = (sub.get("truth") or {}).get("body", sub["name"])
    if body in truth[2]:
        bx, by = truth[2][body]
    else:
        bx, by = list(truth[2].values())[0]
    tx = np.interp(wall, truth[0], bx)
    ty = np.interp(wall, truth[0], by)
    return conf, np.hypot(tx - px, ty - py)


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
        # ever_latched is int(any(trk)), so a single frame of tracking counts as
        # a latch. Seven of the latched flights hold the track for under a
        # second and one is a single frame. Record how long the longest episode
        # actually lasted so a flicker is not reported as following someone.
        ep, best = 0.0, 0.0
        for k, g in itertools.groupby(zip(trk, dt), key=lambda z: z[0]):
            if k:
                ep = float(sum(d for _, d in g))
                best = max(best, ep)
        longest_track_s = best
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
            "longest_track_episode_s": round(longest_track_s, 3),
            "held_1s": int(longest_track_s >= 1.0),
            "held_3s": int(longest_track_s >= 3.0),
            "frames_above_enter": int(above.sum()),
            "longest_above_enter_run": max(runs_) if runs_ else 0,
            "M9_losses": len(m.get("M9_track_outage_all_s") or []),
            "M10_p05": m.get("M10_conf_p05_present"),
            # scoreboard's M2 averages over every settled frame, tracking or
            # not, so on a flight that never latched it is a geometry constant
            # (12.9-16.0 deg) and says nothing about pointing. Recompute it on
            # settled AND tracking frames, which is the question "is the drone
            # aimed at the person".
            "M2_mean_all_settled": m.get("M2_heading_err_mean_deg"),
            "M2_mean_tracked": _m2_tracked(cell, summary, rows, truth, manifest),
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
        print(f"{'subject':>9}{'index':>7}{'n':>4}{'ever':>6}{'>=1s':>6}{'>=3s':>6}"
              f"{'ever rate':>11}{'95% CI (ever)':>18}{'M1 median':>11}{'M1 mean':>9}")
        order = sorted({f["subject"] for f in g},
                       key=lambda s: [f for f in g if f["subject"] == s][0]["index_pct"])
        for s in order:
            h = [f for f in g if f["subject"] == s]
            k, n = sum(f["ever_latched"] for f in h), len(h)
            k1 = sum(f["held_1s"] for f in h)
            k3 = sum(f["held_3s"] for f in h)
            lo, hi = clopper_pearson(k, n)
            m1 = [f["M1"] for f in h if f["M1"] is not None]
            tag = "  <- CONTROL" if s == "control" else ""
            print(f"{s:>9}{h[0]['index_pct']:>7.1f}{n:>4}{k:>6}{k1:>6}{k3:>6}{k/n:>11.3f}"
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
        print(f"    rho(index, latch){fmt_rho(spearman(idx, lat))}   "
              f"rho(conf@flown){fmt_rho(spearman(cf, lat))}   "
              f"rho(width){fmt_rho(spearman(wid, lat))}   "
              f"rho(subj frac){fmt_rho(spearman(sf, lat))}")
        hicl = [i for i, v in enumerate(idx) if v >= HIGH_MIN]
        if len(hicl) >= 5:
            hl = [lat[i] for i in hicl]
            print(f"    WITHIN the high cloud (n={len(hicl)}, index "
                  f"{min(idx[i] for i in hicl):.1f}-{max(idx[i] for i in hicl):.1f}): "
                  f"rho(index){fmt_rho(spearman([idx[i] for i in hicl], hl))}  "
                  f"rho(width){fmt_rho(spearman([wid[i] for i in hicl], hl))}")
            if float(np.std(hl)) == 0:
                print(f"      Both undefined: every subject in this cloud latches at "
                      f"exactly {hl[0]:.3f}, so there is no rank order to correlate against.")
    print()

    # ---- are the latches real? ------------------------------------------
    # M1 is the follower's own latch bit. Nothing in it checks that the thing it
    # latched onto is the person. scoreboard's M2 cannot answer that either,
    # because it averages over every settled frame whether tracking or not, so on
    # a flight that never latched it is a geometry constant and says nothing.
    print("=" * 92)
    print("ARE THE LATCHES REAL?  bearing error on settled AND tracking frames only")
    print("=" * 92)
    for cls, name in (("A", "static"), ("B", "moving")):
        g = [f for f in flights if f["cls"] == cls and f["ever_latched"]]
        if not g:
            continue
        v = [f["M2_mean_tracked"] for f in g if f["M2_mean_tracked"] is not None]
        out = [x for x in v if x > SB.MODEL_HALF_FOV_DEG]
        print(f"  {name}: {len(g)} latched flights, mean of flight means "
              f"{np.mean(v):.2f} deg, worst {max(v):.2f} deg")
        print(f"    flights whose tracked-frame mean bearing falls outside the "
              f"+-{SB.MODEL_HALF_FOV_DEG:g} deg crop: {len(out)}")
    print("  For comparison, the same column over NEVER-latched flights is a constant of")
    print("  the geometry, because the drone never yawed:")
    for cls, name in (("A", "static"), ("B", "moving")):
        g = [f["M2_mean_all_settled"] for f in flights
             if f["cls"] == cls and not f["ever_latched"] and f["M2_mean_all_settled"] is not None]
        if g:
            print(f"    {name}: n={len(g)}, range {min(g):.2f}-{max(g):.2f} deg "
                  f"(scoreboard's M2, all settled frames)")
    print()

    # ---- width-matched contrast -------------------------------------------
    # Panel width correlates with the index, so "only the person changed" is not
    # strictly true. The first version of this section printed one greedily
    # chosen trio and called the confound dead. That was wrong twice over: the
    # trio was picked by dict insertion order out of two tied candidates, and
    # its only informative subject was simultaneously the widest AND the highest
    # index, so it had an effective n of 1 and a permutation p of 0.333. Report
    # every tied group, and lead with the exact-width pair instead.
    print("=" * 92)
    print("WIDTH-MATCHED CONTRAST")
    print("=" * 92)
    sub_of = {}
    for f in flights:
        if f["subject"] == "control":
            continue
        sub_of.setdefault((f["cls"], f["subject"]), []).append(f)
    def cell(cls, name):
        h = sub_of[(cls, name)]
        return (h[0]["panel_w_m"], h[0]["index_pct"], h[0]["subject_fraction"],
                float(np.mean([x["ever_latched"] for x in h])),
                float(np.mean([x["held_1s"] for x in h])),
                float(np.mean([x["M1"] for x in h if x["M1"] is not None])), len(h))
    names = sorted({k[1] for k in sub_of})
    # the exact match
    print("  EXACT width match. These two render to the same panel width to four")
    print("  decimals, and sit at opposite ends of the detectability index:")
    print(f"    {'subject':>9}{'width':>9}{'subjfrac':>10}{'index':>8}{'class':>8}"
          f"{'ever':>7}{'>=1s':>7}{'mean M1':>10}")
    for nm in ("124442", "61747"):
        for cls, cn in (("A", "static"), ("B", "moving")):
            w, i, sf, ev, h1, m1, n = cell(cls, nm)
            print(f"    {nm:>9}{w:>9.4f}{sf:>10.4f}{i:>8.1f}{cn:>8}{ev:>7.3f}{h1:>7.3f}{m1:>10.3f}")
    print("    Same card, same rendered width, 0.000 against 1.000 on both scenes.")
    print("    Their subject fractions differ (0.4038 vs 0.4861), so this pair holds")
    print("    width exactly but does NOT hold fill fraction. No pair in this pool holds")
    print("    both.")
    print()
    print("  Every group of >=3 subjects matched to within 0.010 m, not just the first:")
    groups, seen = [], set()
    for nm in names:
        w0 = cell("A", nm)[0]
        grp = tuple(sorted(x for x in names if abs(cell("A", x)[0] - w0) <= 0.010))
        if len(grp) >= 3 and grp not in seen:
            seen.add(grp); groups.append(grp)
    for grp in groups:
        sp = max(cell("A", x)[0] for x in grp) - min(cell("A", x)[0] for x in grp)
        print(f"    width spread {sp:.4f} m:")
        for nm in sorted(grp, key=lambda x: cell("A", x)[1]):
            w, i, sf, ev, h1, m1, n = cell("A", nm)
            wm, im, sfm, evm, h1m, m1m, nm_ = cell("B", nm)
            print(f"      {nm:>9} width {w:.4f}  subjfrac {sf:.4f}  index {i:>5.1f}   "
                  f"static ever {ev:.3f}  moving ever {evm:.3f}")
        outs = [cell("A", x)[3] for x in grp]
        if len(set(outs)) == 1:
            print(f"      -> every subject in this group has the same static outcome "
                  f"({outs[0]:.3f}); uninformative about width.")
        else:
            # exact permutation p for the observed index/outcome agreement
            import itertools as _it
            idxs = [cell("A", x)[1] for x in grp]
            obs = spearman(idxs, outs)
            perms = [spearman(idxs, list(q)) for q in _it.permutations(outs)]
            pv = float(np.mean([1 for q in perms if not np.isnan(q) and q >= obs]) /
                       max(len([q for q in perms if not np.isnan(q)]), 1))
            print(f"      -> rho(index, static ever) = {obs:+.3f}, exact permutation "
                  f"p = {pv:.3f} on n = {len(grp)}. That is the floor for this many")
            print(f"         subjects, so this group cannot on its own rule width out.")
    print()

    # ---- range-matched confidence: avoid the collider ----------------------
    # A latching drone closes to ~2.5 m; a non-latching one sits at its start
    # range. Comparing per-frame confidence over whole flights therefore
    # compares different geometry, chosen by the outcome. Restrict to the start
    # range window every arm occupies.
    print("=" * 92)
    print("CONFIDENCE, RANGE-MATCHED (the whole-flight version is a collider:")
    print("a drone that latches closes in, so it sees the person larger BECAUSE it latched)")
    print("=" * 92)
    for cls, name, band in (("A", "static", (3.3, 3.9)), ("B", "moving", (2.9, 3.4))):
        g = [f for f in flights if f["cls"] == cls]
        if not g:
            continue
        print(f"  {name}, frames with true range in [{band[0]}, {band[1]}] m")
        print(f"    {'subject':>9}{'index':>8}{'n frames':>10}{'mean conf':>11}{'p05':>8}"
              f"{'frac >=0.75':>13}")
        for sname in sorted({f['subject'] for f in g},
                            key=lambda s: [f for f in g if f['subject'] == s][0]['index_pct']):
            cc = []
            for f in [x for x in g if x["subject"] == sname]:
                conf, d = conf_and_range(OUT / "runs" / f["run"])
                if conf is None:
                    continue
                sel = (d >= band[0]) & (d <= band[1])
                cc.extend(conf[sel].tolist())
            if len(cc) < 20:
                print(f"    {sname:>9}{'':>8}{len(cc):>10}   too few frames in band")
                continue
            cc = np.array(cc)
            idx_ = [f for f in g if f['subject'] == sname][0]['index_pct']
            print(f"    {sname:>9}{idx_:>8.1f}{len(cc):>10}{cc.mean():>11.3f}"
                  f"{np.percentile(cc, 5):>8.3f}{float(np.mean(cc >= 0.75)):>13.3f}")
        print()

    json.dump(flights, open(OUT / "tables/flights.json", "w"), indent=1)
    print(f"wrote tables/flights.tsv and tables/flights.json")


if __name__ == "__main__":
    main()
