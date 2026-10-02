"""Metrics for the --preserve-qat-alphas comparison. Plain numpy. Reads <model>.npz from infer_pqa.py.

Per arm (float, qat_fq = the network as QAT trained it, chip_recal, chip_preserve):
  random1000: precision/recall/F1 at 0.5, 0.7, 0.75; empty-scene false alarms
  confuser771: false alarms (pets, mannequins, teddy bears; no person) at 0.45 / 0.5 / 0.7 / 0.75
  matched recall: every arm's threshold dialled to the recall chip_recal has at the
                  shipped 0.75 bar, then false alarms there (project rule: never compare
                  two models at different operating points)
  agreement of each chip arm with qat_fq and with float
Usage: python analyze_pqa.py <model-key> [<model-key> ...]
"""
import json
import math
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
IN = Path("/private/tmp/claude-501/-Users-saimaruvada-Downloads/d61d4b16-675d-4343-bf41-a6a63ecfbbe7/scratchpad/pqa_eval")
Z = 1.959963984540054
BOOT = 2000
SHIPPED_BAR = 0.75


def sig(x):
    return 1.0 / (1.0 + np.exp(-x))


def wilson(k, n):
    if n == 0:
        return {"k": 0, "n": 0, "p": None, "lo": None, "hi": None}
    p = k / n
    d = 1 + Z * Z / n
    c = (p + Z * Z / (2 * n)) / d
    h = Z * math.sqrt(p * (1 - p) / n + Z * Z / (4 * n * n)) / d
    return {"k": int(k), "n": int(n), "p": float(p), "lo": float(max(0, c - h)), "hi": float(min(1, c + h))}


def prf(pred, gt):
    tp = int((pred & gt).sum())
    fp = int((pred & ~gt).sum())
    fn = int((~pred & gt).sum())
    P = tp / (tp + fp) if tp + fp else 0.0
    R = tp / (tp + fn) if tp + fn else 0.0
    return {"tp": tp, "fp": fp, "fn": fn, "precision": P, "recall": R, "f1": (2 * P * R / (P + R) if P + R else 0.0)}


def threshold_for_recall(p_pos, target_recall):
    """Highest threshold t with recall(p >= t) >= target_recall on the positives p_pos."""
    s = np.sort(p_pos)[::-1]
    k = int(math.ceil(target_recall * len(s) - 1e-9))
    k = min(max(k, 1), len(s))
    return float(s[k - 1])


def raw_threshold(p, eps):
    return int(math.ceil(math.log(p / (1 - p)) / eps))


def arms_for(d):
    arms = {"float": d["fp"], "qat_fq": d["qat_fq"]}
    for label in ("recal", "preserve"):
        arms[f"chip_{label}"] = d[f"raw_{label}"] * float(d[f"eps_{label}"])
    return arms


def agreement(pa, pb, xa, xb):
    va, vb = pa >= 0.5, pb >= 0.5

    def tri(p):
        return np.where(p >= 0.7, 2, np.where(p < 0.45, 0, 1))

    ta, tb = tri(pa), tri(pb)
    conf = ta != 1
    hard = ((ta == 2) & (tb == 0)) | ((ta == 0) & (tb == 2))
    both = va & vb
    return {
        "vis_agree_p05": wilson(int((va == vb).sum()), len(pa)),
        "confident_hard_contradictions": wilson(int(hard.sum()), int(conf.sum())),
        "abs_conf_diff_mean": float(np.abs(pa - pb).mean()),
        "xbin_exact_both_visible": wilson(int((xa[both] == xb[both]).sum()), int(both.sum())),
    }


def analyze(key, rng):
    d = np.load(IN / f"{key}.npz", allow_pickle=True)
    R = d["tag_random1000"].astype(bool)
    C = d["tag_confuser771"].astype(bool)
    gt = d["target"][:, 2] > 0.5
    tnp = d["true_no_person"].astype(bool)
    arms = arms_for(d)
    P = {a: sig(v[:, 9]) for a, v in arms.items()}
    X = {a: v[:, :9].argmax(1) for a, v in arms.items()}
    res = {
        "n_random": int(R.sum()),
        "n_confuser": int(C.sum()),
        "random_gt_visible": int(gt[R].sum()),
        "random_true_no_person": int((R & tnp).sum()),
        "eps": {lab: float(d[f"eps_{lab}"]) for lab in ("recal", "preserve")},
        "onnx_sha1": {lab: str(d[f"onnx_sha1_{lab}"]) for lab in ("recal", "preserve")},
        "release": {lab: str(d[f"release_{lab}"]) for lab in ("recal", "preserve")},
        "firmware_raw_thresholds_enter075_exit045": {
            lab: [raw_threshold(0.75, float(d[f"eps_{lab}"])), raw_threshold(0.45, float(d[f"eps_{lab}"]))]
            for lab in ("recal", "preserve")
        },
        "arms": {},
    }
    for a, p in P.items():
        blk = {}
        for t in (0.5, 0.7, SHIPPED_BAR):
            blk[f"prf@{t}"] = prf(p[R] >= t, gt[R])
            blk[f"empty_scene_fa@{t}"] = wilson(int((p[R & tnp] >= t).sum()), int((R & tnp).sum()))
        for t in (0.45, 0.5, 0.7, SHIPPED_BAR):
            blk[f"confuser_fa@{t}"] = wilson(int((p[C] >= t).sum()), int(C.sum()))
        res["arms"][a] = blk

    # matched recall: reference = chip_recal at the shipped bar
    pos = R & gt
    r_star = prf(P["chip_recal"][R] >= SHIPPED_BAR, gt[R])["recall"]
    matched = {"reference": f"chip_recal recall at {SHIPPED_BAR}", "recall": r_star, "arms": {}}
    for a, p in P.items():
        t = threshold_for_recall(p[pos], r_star)
        matched["arms"][a] = {
            "threshold": t,
            "recall": prf(p[R] >= t, gt[R])["recall"],
            "precision": prf(p[R] >= t, gt[R])["precision"],
            "confuser_fa": wilson(int((p[C] >= t).sum()), int(C.sum())),
            "empty_scene_fa": wilson(int((p[R & tnp] >= t).sum()), int((R & tnp).sum())),
        }
    # paired bootstrap of (preserve - recal) confuser FA at matched recall
    pos_idx = np.flatnonzero(pos)
    c_idx = np.flatnonzero(C)
    diffs = []
    for _ in range(BOOT):
        pi = rng.choice(pos_idx, len(pos_idx))
        ci = rng.choice(c_idx, len(c_idx))
        rs = float((P["chip_recal"][pi] >= SHIPPED_BAR).mean())
        fa = {}
        for a in ("chip_recal", "chip_preserve"):
            t = threshold_for_recall(P[a][pi], rs)
            fa[a] = float((P[a][ci] >= t).mean())
        diffs.append(fa["chip_preserve"] - fa["chip_recal"])
    point = matched["arms"]["chip_preserve"]["confuser_fa"]["p"] - matched["arms"]["chip_recal"]["confuser_fa"]["p"]
    matched["preserve_minus_recal_confuser_fa"] = {
        "p": float(point),
        "lo": float(np.percentile(diffs, 2.5)),
        "hi": float(np.percentile(diffs, 97.5)),
        "method": f"paired bootstrap {BOOT}, recall target re-drawn per replicate",
    }
    # FA curve at a grid of recalls
    curve = []
    for rr in np.arange(0.50, 0.901, 0.05):
        row = {"recall": round(float(rr), 2)}
        for a, p in P.items():
            t = threshold_for_recall(p[pos], rr)
            row[a] = float((p[C] >= t).mean())
        curve.append(row)
    matched["confuser_fa_by_recall"] = curve
    res["matched_recall"] = matched

    # same-threshold paired test on the slice at 0.45 and the shipped bar (McNemar exact)
    from math import comb

    def mcnemar(a_flag, b_flag):
        b = int((a_flag & ~b_flag).sum())
        c = int((~a_flag & b_flag).sum())
        n = b + c
        pval = min(1.0, 2 * sum(comb(n, k) for k in range(0, min(b, c) + 1)) / 2**n) if n else 1.0
        return {"recal_only": b, "preserve_only": c, "p_two_sided": pval}

    res["slice_same_threshold_mcnemar"] = {
        str(t): mcnemar(P["chip_recal"][C] >= t, P["chip_preserve"][C] >= t) for t in (0.45, SHIPPED_BAR)
    }
    # signed visibility-logit bias of each chip arm vs the network QAT trained (random1000)
    bias = {}
    for chip in ("chip_recal", "chip_preserve"):
        dd = arms[chip][R, 9] - arms["qat_fq"][R, 9]
        idx = rng.integers(0, len(dd), (BOOT, len(dd)))
        bs = dd[idx].mean(1)
        bias[chip] = {
            "mean": float(dd.mean()),
            "lo": float(np.percentile(bs, 2.5)),
            "hi": float(np.percentile(bs, 97.5)),
            "median": float(np.median(dd)),
            "vs_float_mean": float((arms[chip][R, 9] - arms["float"][R, 9]).mean()),
        }
    res["chip_minus_qat_vis_logit_random1000"] = bias
    res["agreement_random1000"] = {
        f"{chip}_vs_{ref}": agreement(P[ref][R], P[chip][R], X[ref][R], X[chip][R])
        for chip in ("chip_recal", "chip_preserve")
        for ref in ("qat_fq", "float")
    }
    res["agreement_confuser771"] = {
        f"{chip}_vs_qat_fq": agreement(P["qat_fq"][C], P[chip][C], X["qat_fq"][C], X[chip][C])
        for chip in ("chip_recal", "chip_preserve")
    }
    return res


def fmt(w):
    return f"{w['p']:.3f} [{w['lo']:.3f},{w['hi']:.3f}] ({w['k']}/{w['n']})"


def main():
    rng = np.random.default_rng(20261001)
    out = {}
    for key in sys.argv[1:]:
        r = analyze(key, rng)
        out[key] = r
        print(f"\n===== {key}  eps recal {r['eps']['recal']:.6g} preserve {r['eps']['preserve']:.6g}  "
              f"raw thresholds {r['firmware_raw_thresholds_enter075_exit045']}")
        print(f"{'arm':14s} {'F1@0.5':>7s} {'R@0.75':>7s} {'emptyFA@.75':>12s} {'sliceFA@.45':>28s} {'sliceFA@.75':>28s}")
        for a, b in r["arms"].items():
            print(f"{a:14s} {b['prf@0.5']['f1']:7.3f} {b['prf@0.75']['recall']:7.3f} {b['empty_scene_fa@0.75']['p']:12.3f} "
                  f"{fmt(b['confuser_fa@0.45']):>28s} {fmt(b['confuser_fa@0.75']):>28s}")
        m = r["matched_recall"]
        print(f"matched recall {m['recall']:.3f} ({m['reference']}):")
        for a, b in m["arms"].items():
            print(f"  {a:14s} thr {b['threshold']:.3f} slice FA {fmt(b['confuser_fa'])} empty FA {fmt(b['empty_scene_fa'])} prec {b['precision']:.3f}")
        dd = m["preserve_minus_recal_confuser_fa"]
        print(f"  preserve - recal slice FA at matched recall: {dd['p']:+.4f} [{dd['lo']:+.4f},{dd['hi']:+.4f}]")
        print("  slice FA by recall:", " ".join(
            f"{row['recall']:.2f}:{row['chip_recal']:.3f}/{row['chip_preserve']:.3f}/{row['qat_fq']:.3f}" for row in m["confuser_fa_by_recall"]))
        print("  same-threshold McNemar on slice:", r["slice_same_threshold_mcnemar"])
        for chip, b in r["chip_minus_qat_vis_logit_random1000"].items():
            print(f"  {chip:14s} chip - QAT vis logit mean {b['mean']:+.3f} [{b['lo']:+.3f},{b['hi']:+.3f}] (vs float {b['vs_float_mean']:+.3f})")
        for k, v in r["agreement_random1000"].items():
            print(f"  {k:28s} vis agree {fmt(v['vis_agree_p05'])} hard contra {v['confident_hard_contradictions']['k']}/{v['confident_hard_contradictions']['n']} "
                  f"|dconf| {v['abs_conf_diff_mean']:.4f} xbin {fmt(v['xbin_exact_both_visible'])}")
    (HERE.parent / "results.json").write_text(json.dumps(out, indent=1) + "\n")


if __name__ == "__main__":
    main()
