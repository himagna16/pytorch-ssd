#!/usr/bin/env python
"""Seed-paired arm comparison + pooling against the 16-flight 0.45 baseline.

All three arms flew seeds 1001-1006, so each seed gives a matched triple (same
himax noise draw, different exit bar).  This pairs on seed, which removes the
camera-noise term the unpaired arm comparison leaves in.
"""
import json, sys
from pathlib import Path
import numpy as np
from scipy.stats import beta, wilcoxon, mannwhitneyu

GATE = 0.5
suite = Path(sys.argv[1])
recs = [json.loads(l) for l in open(suite / "flight_records.jsonl")]
pets = [r for r in recs if r["cell"].startswith("F.pets") and r["verdict"] == "VALID"]
arms = sorted({r["vis_exit"] for r in pets})

def cp(k, n, alpha=.05):
    lo = 0. if k == 0 else float(beta.ppf(alpha/2, k, n-k+1))
    hi = 1. if k == n else float(beta.ppf(1-alpha/2, k+1, n-k))
    return lo, hi

out = {}
by = {a: {r["seed"]: r for r in pets if r["vis_exit"] == a} for a in arms}
seeds = sorted(set.intersection(*[set(by[a]) for a in arms]))

L = []
L.append("## Seed-paired triples (all three arms flew seeds 1001-1006)\n")
L.append("M6 drift in metres; **bold** = passes the 0.5 m gate. `latched` = total seconds latched.\n")
L.append("| seed | M6 @0.45 | M6 @0.55 | M6 @0.65 | latched @0.45 | @0.55 | @0.65 | eps @0.45/0.55/0.65 | rel.conf med @0.45/0.55/0.65 |")
L.append("|---|---|---|---|---|---|---|---|---|")
for s in seeds:
    row = [by[a][s] for a in arms]
    f = lambda r: (f"**{r['M6_drift_m']:.3f}**" if r["pass_M6"] else f"{r['M6_drift_m']:.3f}")
    med = lambda r: (f"{np.median(r['release_confs']):.3f}" if r["release_confs"] else "-")
    L.append(f"| {s} | " + " | ".join(f(r) for r in row) + " | "
             + " | ".join(f"{r['latched_s']:.2f}" for r in row) + " | "
             + "/".join(str(r["n_episodes"]) for r in row) + " | "
             + "/".join(med(r) for r in row) + " |")
L.append("")

out["paired"] = {}
for a in arms:
    d = [by[a][s]["M6_drift_m"] for s in seeds]
    lat = [by[a][s]["latched_s"] for s in seeds]
    ep = [by[a][s]["n_episodes"] for s in seeds]
    k = sum(1 for x in d if x < GATE)
    lo, hi = cp(k, len(d))
    out["paired"][str(a)] = {"drifts": d, "pass": k, "n": len(d), "rate": k/len(d),
                             "cp95": [lo, hi], "median_drift": float(np.median(d)),
                             "worst": max(d), "latched_median": float(np.median(lat)),
                             "latched_mean": float(np.mean(lat)),
                             "episodes_median": float(np.median(ep))}

L.append("### Paired differences against the 0.45 control, same seed\n")
L.append("| comparison | per-seed delta M6 (m) | median delta | n better | Wilcoxon p |")
L.append("|---|---|---|---|---|")
for a in arms[1:]:
    d0 = np.array([by[arms[0]][s]["M6_drift_m"] for s in seeds])
    d1 = np.array([by[a][s]["M6_drift_m"] for s in seeds])
    dd = d1 - d0
    try:
        p = float(wilcoxon(d1, d0).pvalue)
    except Exception:
        p = float("nan")
    L.append(f"| {a} - 0.45 | {', '.join(f'{x:+.3f}' for x in dd)} | {np.median(dd):+.3f} | "
             f"{int((dd < 0).sum())}/{len(seeds)} lower | {p:.3f} |")
    out.setdefault("paired_delta", {})[str(a)] = {"delta": dd.tolist(),
                                                  "median": float(np.median(dd)),
                                                  "n_lower": int((dd < 0).sum()), "wilcoxon_p": p}
L.append("")

L.append("### Latched time (the mechanism the exit bar acts on), paired\n")
L.append("| comparison | per-seed delta latched (s) | median delta | n lower | Wilcoxon p |")
L.append("|---|---|---|---|---|")
for a in arms[1:]:
    d0 = np.array([by[arms[0]][s]["latched_s"] for s in seeds])
    d1 = np.array([by[a][s]["latched_s"] for s in seeds])
    dd = d1 - d0
    try:
        p = float(wilcoxon(d1, d0).pvalue)
    except Exception:
        p = float("nan")
    L.append(f"| {a} - 0.45 | {', '.join(f'{x:+.2f}' for x in dd)} | {np.median(dd):+.2f} | "
             f"{int((dd < 0).sum())}/{len(seeds)} | {p:.3f} |")
    out.setdefault("latched_delta", {})[str(a)] = {"delta": dd.tolist(),
                                                   "median": float(np.median(dd)),
                                                   "n_lower": int((dd < 0).sum()), "wilcoxon_p": p}
L.append("")

# ---- baseline comparison ----
BASE = [0.188,0.348,0.231,0.409,0.684,0.613,1.188,0.220,0.295,0.276,1.121,0.484,0.506,0.322,0.346,0.376]
bk = sum(1 for x in BASE if x < GATE); bn = len(BASE)
blo, bhi = cp(bk, bn)
L.append("## Against the 0.45 baseline from the earlier session (same scene, same enter bar)\n")
L.append("| session | arm | n | pass | rate | CP95 | median M6 | worst M6 |")
L.append("|---|---|---|---|---|---|---|---|")
L.append(f"| pets-variance (Sep 14 **afternoon**, 17:51-18:05Z) | 0.45 | {bn} | {bk} | {bk/bn:.3f} | "
         f"[{blo:.3f}, {bhi:.3f}] | {np.median(BASE):.3f} | {max(BASE):.3f} |")
for a in arms:
    g = out["paired"][str(a)]
    L.append(f"| exit-bar (Sep 14 **evening**, this folder, 20:08-20:24Z) | {a} | {g['n']} | {g['pass']} | "
             f"{g['rate']:.3f} | [{g['cp95'][0]:.3f}, {g['cp95'][1]:.3f}] | {g['median_drift']:.3f} | {g['worst']:.3f} |")
L.append("")
# control vs baseline test
c = [by[arms[0]][s]["M6_drift_m"] for s in seeds]
try:
    pmw = float(mannwhitneyu(c, BASE, alternative="two-sided").pvalue)
except Exception:
    pmw = float("nan")
out["control_vs_baseline_mannwhitney_p"] = pmw
out["baseline"] = {"n": bn, "pass": bk, "rate": bk/bn, "cp95": [blo, bhi],
                   "median": float(np.median(BASE)), "worst": max(BASE)}
L.append(f"Control-arm drifts vs the afternoon baseline drifts, Mann-Whitney two-sided: **p = {pmw:.3f}** "
         f"({len(seeds)} vs 16 flights).\n")

# seeds 1001-1006 subset of the baseline, matched noise draws
BASE6 = BASE[:6]
L.append(f"The afternoon session's own seeds 1001-1006 (its repeats 1-6) were "
         f"{', '.join(f'{x:.3f}' for x in BASE6)} - {sum(1 for x in BASE6 if x<GATE)}/6 under the gate.\n")
out["baseline_seeds_1001_1006"] = {"drifts": BASE6, "pass": sum(1 for x in BASE6 if x < GATE)}

open(suite / "paired.md", "w").write("\n".join(L) + "\n")
json.dump(out, open(suite / "paired.json", "w"), indent=2)
print("\n".join(L))
