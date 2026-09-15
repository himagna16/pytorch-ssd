import json, sys, statistics as st
import numpy as np
rows = json.load(open(sys.argv[1]))
BARS = [0.50,0.55,0.60,0.65,0.70,0.75,0.80,0.85,0.90]

clean = [r for r in rows if r.get("clean")]
deg   = [r for r in rows if not r.get("clean")]
print(f"flights: {len(rows)}   clean camera: {len(clean)}   degraded camera: {len(deg)}\n")

def grp(rs, key):
    d = {}
    for r in rs: d.setdefault(r.get(key) or "?", []).append(r)
    return d

print("=" * 78)
print("1. Does the stated basis hold?  Line's basis: 'confidence is 0.96-1.0 on")
print("   essentially every frame with a real person.'  p05 = 5th pct of in-FOV conf.")
print("=" * 78)
print(f"{'class':<8}{'n':>5}{'p05 med':>10}{'p05 min':>10}{'p05 max':>10}{'conf mean med':>16}")
for cls, rs in sorted(grp(clean, "cls").items()):
    p = [r["p05"] for r in rs if r.get("p05") is not None]
    c = [r["confmean"] for r in rs if r.get("confmean") is not None]
    if not p: continue
    print(f"{cls:<8}{len(p):>5}{st.median(p):>10.3f}{min(p):>10.3f}{max(p):>10.3f}{st.median(c):>16.3f}")

print()
print("=" * 78)
print("2. The mechanical widening: median M10 across the bar (clean camera)")
print("=" * 78)
hdr = f"{'class':<8}{'n':>5}" + "".join(f"{b:>8.2f}" for b in BARS)
print(hdr)
for cls, rs in sorted(grp(clean, "cls").items()):
    vals = []
    for b in BARS:
        v = [r[f"m10_{b:.2f}"] for r in rs if f"m10_{b:.2f}" in r]
        vals.append(st.median(v) if v else float("nan"))
    if not vals or np.isnan(vals[0]): continue
    print(f"{cls:<8}{len(rs):>5}" + "".join(f"{v:>8.3f}" for v in vals))

print()
print("=" * 78)
print("3. Pass rate against the 0.05 line, clean camera, per class and bar")
print("=" * 78)
print(hdr)
for cls, rs in sorted(grp(clean, "cls").items()):
    out = []
    for b in BARS:
        v = [r[f"m10_{b:.2f}"] for r in rs if f"m10_{b:.2f}" in r]
        out.append(sum(1 for x in v if x <= 0.05) / len(v) if v else float("nan"))
    if np.isnan(out[0]): continue
    print(f"{cls:<8}{len(rs):>5}" + "".join(f"{v:>8.2f}" for v in out))

print()
print("=" * 78)
print("4. Does M10 predict anything?  Correlation of M10@own-bar with outcome")
print("   metrics, clean-camera A and B flights (Spearman).")
print("=" * 78)
def spearman(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    ra = np.argsort(np.argsort(a)).astype(float)
    rb = np.argsort(np.argsort(b)).astype(float)
    if ra.std() == 0 or rb.std() == 0: return float("nan")
    return float(np.corrcoef(ra, rb)[0, 1])

ab = [r for r in clean if r.get("cls") in ("A", "B")]
def m10_own(r):
    b = min(BARS, key=lambda x: abs(x - r["own_bar"]))
    return r.get(f"m10_{b:.2f}")
xs = [(r, m10_own(r)) for r in ab]
xs = [(r, v) for r, v in xs if v is not None]
print(f"n = {len(xs)} clean-camera A/B flights")
for label, key in [("M1 tracking fraction", "M1"), ("M2 heading err mean", "M2_mean"),
                   ("M9 track losses (count)", "M9_losses"), ("M9 longest outage s", "M9_outage"),
                   ("M11 yaw reversals/min", "M11_rev"), ("M11 yaw saturated frac", "M11_sat")]:
    pair = [(v, r.get(key)) for r, v in xs if r.get(key) is not None]
    if len(pair) < 10:
        print(f"  {label:<26} n={len(pair):<4} too few"); continue
    rho = spearman([p[0] for p in pair], [p[1] for p in pair])
    print(f"  {label:<26} n={len(pair):<4} rho = {rho:+.3f}")

print()
print("=" * 78)
print("5. Band-invariant alternative: p05 confidence, clean camera A/B")
print("=" * 78)
p = sorted(r["p05"] for r in ab if r.get("p05") is not None)
if p:
    print(f"n = {len(p)}   min {p[0]:.3f}   p05 {np.percentile(p,5):.3f}   median {st.median(p):.3f}   max {p[-1]:.3f}")
    for q in (0.05, 0.10, 0.25):
        print(f"  {int(q*100)}th pct of per-flight p05 = {np.percentile(p, q*100):.3f}")
