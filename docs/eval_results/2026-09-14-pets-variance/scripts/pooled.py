#!/usr/bin/env python
"""Pooled pass-rate estimate at vis_enter 0.75 across sessions, gate M6 < 0.5 m.
Earlier-session drifts are taken from docs/eval_results/2026-09-14-baseline-075/README.md section 5a
(sweep and this-morning values re-verified from their runs/ metrics.json by analyze_pets.py; the smoke
flight's 0.484 is quoted from that README only - its run directory was not located in this session)."""
import json, sys
from scipy.stats import beta
def cp(k, n, a=0.05):
    lo = 0.0 if k == 0 else beta.ppf(a/2, k, n-k+1); hi = 1.0 if k == n else beta.ppf(1-a/2, k+1, n-k); return lo, hi
GATE = 0.5
earlier = {
  "sweep 0.75 arm (Sep 13, t075__F.pets__ships, seeds 1001-1004)": [0.162, 0.309, 0.289, 0.376],
  "baseline-075 (Sep 14 morning, seeds 1001-1004)": [0.706, 0.734, 0.461, 0.342],
}
smoke = {"smoke flight post-merge (Sep 13, b1a0108, README-quoted only)": [0.484]}
this = [json.loads(l)["M6_drift_m"] for l in open(sys.argv[1])]
def row(label, d):
    k = sum(1 for x in d if x < GATE); n = len(d); lo, hi = cp(k, n)
    return f"| {label} | {n} | {k} | {n-k} | {k/n:.3f} | [{lo:.3f}, {hi:.3f}] | {max(d):.3f} | " + ", ".join(f"{x:.3f}" for x in d) + " |"
print("| session | n | pass | fail | rate | CP 95% | worst | drifts (flown order) |")
print("|---|---|---|---|---|---|---|---|")
for lab, d in earlier.items(): print(row(lab, d))
for lab, d in smoke.items(): print(row(lab, d))
print(row("THIS SESSION (Sep 14 afternoon, seeds 1001-10xx)", this))
e8 = sum(earlier.values(), [])
print(row("pooled: 8 earlier (sweep + morning)", e8))
print(row("pooled: 8 earlier + this session", e8 + this))
print(row("pooled: 9 earlier (incl. smoke) + this session", e8 + sum(smoke.values(), []) + this))
