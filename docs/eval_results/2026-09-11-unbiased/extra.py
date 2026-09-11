"""Extra stats: pack-vs-random agreement gap (bootstrap), integer-float visibility logit shift, agreement-optimal integer threshold."""
import json, numpy as np
from pathlib import Path
OUT = Path(__file__).parent; rng = np.random.default_rng(7); B = 4000
def sig(x): return 1/(1+np.exp(-x))
res = {}
for m in ["champion", "confuser", "confuser_qathn"]:
    d = np.load(OUT / f"full_{m}.npz", allow_pickle=True); eps = float(d["eps"])
    lf = d["fp"][:, 9]; li = d["raw_rt"][:, 9] * eps
    R = d["tag_random1000"].astype(bool); P = d["tag_pack560"].astype(bool)
    r = {"overlap_random_pack": int((R & P).sum())}
    def agree(mask, full=False):
        a = (lf[mask] >= 0) == (li[mask] >= 0)
        if not full: return a
        xf = d["fp"][mask, :9].argmax(1); xi = d["raw_rt"][mask, :9].argmax(1); sf = d["fp"][mask, 10:14].argmax(1); si = d["raw_rt"][mask, 10:14].argmax(1)
        both = (lf[mask] >= 0) & (li[mask] >= 0)
        return a & (~both | ((xf == xi) & (sf == si)))
    for full in (False, True):
        aR, aP = agree(R, full).astype(float), agree(P, full).astype(float)
        bs = [aP[rng.integers(0, len(aP), len(aP))].mean() - aR[rng.integers(0, len(aR), len(aR))].mean() for _ in range(B)]
        r[("full_decision" if full else "vis@0.5") + "_agree_pack_minus_random"] = {"p": float(aP.mean() - aR.mean()), "lo": float(np.percentile(bs, 2.5)), "hi": float(np.percentile(bs, 97.5))}
    sh = li[R] - lf[R]
    bs = [sh[rng.integers(0, len(sh), len(sh))].mean() for _ in range(B)]
    r["random_vis_logit_shift_int_minus_float"] = {"mean": float(sh.mean()), "lo": float(np.percentile(bs, 2.5)), "hi": float(np.percentile(bs, 97.5)), "median": float(np.median(sh)), "std": float(sh.std())}
    ts = np.linspace(0.40, 0.70, 61); ag = [((sig(lf[R]) >= 0.5) == (sig(li[R]) >= t)).mean() for t in ts]
    k = int(np.argmax(ag)); r["best_int_threshold_vs_float_0.5"] = {"t": float(ts[k]), "agree": float(ag[k]), "agree_at_0.5": float(ag[20])}
    res[m] = r
json.dump(res, open(OUT / "results_extra.json", "w"), indent=1); print(json.dumps(res, indent=1))
