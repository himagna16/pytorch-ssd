"""Metrics for the unbiased float-vs-integer eval. Plain numpy. Reads full_<model>.npz, writes results.json + per-image CSVs."""
import json, csv
from pathlib import Path
import numpy as np

OUT = Path(__file__).parent
MODELS = ["champion", "confuser", "confuser_qathn"]
FLOAT_CONFUSER_REF = {"champion": 0.239, "confuser": 0.083, "confuser_qathn": 0.122}
Z = 1.959963984540054
BOOT = 2000

def sig(x): return 1.0 / (1.0 + np.exp(-x))

def wilson(k, n):
    if n == 0: return {"k": 0, "n": 0, "p": None, "lo": None, "hi": None}
    p = k / n; d = 1 + Z * Z / n
    c = (p + Z * Z / (2 * n)) / d; h = Z * np.sqrt(p * (1 - p) / n + Z * Z / (4 * n * n)) / d
    return {"k": int(k), "n": int(n), "p": float(p), "lo": float(max(0, c - h)), "hi": float(min(1, c + h))}

def prf(pred, gt):
    tp = int((pred & gt).sum()); fp = int((pred & ~gt).sum()); fn = int((~pred & gt).sum())
    P = tp / (tp + fp) if tp + fp else 0.0; R = tp / (tp + fn) if tp + fn else 0.0
    return tp, fp, fn, P, R, (2 * P * R / (P + R) if P + R else 0.0)

def prf_ci(pred, gt, rng):
    tp, fp, fn, P, R, F = prf(pred, gt)
    n = len(pred); fs = []
    for _ in range(BOOT):
        i = rng.integers(0, n, n); fs.append(prf(pred[i], gt[i])[5])
    lo, hi = np.percentile(fs, [2.5, 97.5])
    return {"tp": tp, "fp": fp, "fn": fn, "precision": wilson(tp, tp + fp), "recall": wilson(tp, tp + fn),
            "f1": {"p": float(F), "lo": float(lo), "hi": float(hi), "method": f"bootstrap{BOOT}"}}

def agreement_block(pf, pi, xf, xi, sf, si, rng):
    """pf/pi confidences, x/s argmax indices."""
    n = len(pf); out = {"n": int(n)}
    vf, vi = pf >= 0.5, pi >= 0.5
    out["vis_agree_p05"] = wilson(int((vf == vi).sum()), n)
    out["vis_disagree_p05_float_vis_int_not"] = int((vf & ~vi).sum()); out["vis_disagree_p05_float_not_int_vis"] = int((~vf & vi).sum())
    # follower thresholds: >=0.7 confident visible, <0.45 confident not-visible, else uncertain
    def tri(p): return np.where(p >= 0.7, 2, np.where(p < 0.45, 0, 1))
    tf, ti = tri(pf), tri(pi)
    out["tri_state_agree"] = wilson(int((tf == ti).sum()), n)
    cv = tf == 2; cn = tf == 0
    out["float_confident_visible"] = int(cv.sum()); out["float_confident_not_visible"] = int(cn.sum()); out["float_uncertain"] = int((tf == 1).sum())
    # hard contradiction: integer lands on the opposite confident side
    out["contradict_confident_visible_hard(int<0.45)"] = wilson(int((cv & (ti == 0)).sum()), int(cv.sum()))
    out["contradict_confident_not_visible_hard(int>=0.7)"] = wilson(int((cn & (ti == 2)).sum()), int(cn.sum()))
    conf = cv | cn
    out["contradict_any_confident_hard"] = wilson(int(((cv & (ti == 0)) | (cn & (ti == 2))).sum()), int(conf.sum()))
    # soft: integer leaves the confident band (conf vis -> <0.7, conf not-vis -> >=0.45), i.e. action changes
    out["confident_float_decision_changed_soft"] = wilson(int(((cv & (ti != 2)) | (cn & (ti != 0))).sum()), int(conf.sum()))
    out["contradict_hard_per_image"] = wilson(int(((cv & (ti == 0)) | (cn & (ti == 2))).sum()), n)
    both = vf & vi
    out["both_visible_p05"] = int(both.sum())
    out["xbin_exact_both_vis"] = wilson(int((xf[both] == xi[both]).sum()), int(both.sum()))
    out["xbin_within1_both_vis"] = wilson(int((np.abs(xf[both] - xi[both]) <= 1).sum()), int(both.sum()))
    out["size_exact_both_vis"] = wilson(int((sf[both] == si[both]).sum()), int(both.sum()))
    out["size_within1_both_vis"] = wilson(int((np.abs(sf[both] - si[both]) <= 1).sum()), int(both.sum()))
    # all-three decision agreement (vis at 0.5, and if both visible, exact xbin & size)
    ok = (vf == vi) & (~both | ((xf == xi) & (sf == si)))
    out["full_decision_agree_p05"] = wilson(int(ok.sum()), n)
    d = np.abs(pf - pi)
    out["abs_conf_diff_mean"] = float(d.mean()); out["abs_conf_diff_p95"] = float(np.percentile(d, 95)); out["abs_conf_diff_max"] = float(d.max())
    return out

def main():
    res = {"notes": {}}
    rng = np.random.default_rng(20260911)
    for m in MODELS:
        d = np.load(OUT / f"full_{m}.npz", allow_pickle=True)
        eps = float(d["eps"]); fp = d["fp"]
        chans = {"runtime_staging(primary)": d["raw_rt"] * eps, "stage06_staging(sensitivity)": d["raw_06"] * eps}
        tgt = d["target"]; gt = tgt[:, 2] > 0.5; tnp = d["true_no_person"].astype(bool)
        R = d["tag_random1000"].astype(bool); C = d["tag_confuser771"].astype(bool); P = d["tag_pack560"].astype(bool)
        pf = sig(fp[:, 9]); xf = fp[:, :9].argmax(1); sf = fp[:, 10:14].argmax(1)
        mr = {"eps": eps, "n_random": int(R.sum()), "n_confuser": int(C.sum()), "n_pack": int(P.sum()),
              "random_gt_visible": int(gt[R].sum()), "random_true_no_person": int(tnp[R].sum()),
              "random_person_cropped_out": int((~gt & ~tnp)[R].sum())}
        for cname, li in chans.items():
            pi = sig(li[:, 9]); xi = li[:, :9].argmax(1); si = li[:, 10:14].argmax(1)
            blk = {}
            blk["agreement_random1000"] = agreement_block(pf[R], pi[R], xf[R], xi[R], sf[R], si[R], rng)
            blk["agreement_pack560"] = agreement_block(pf[P], pi[P], xf[P], xi[P], sf[P], si[P], rng)
            if cname.startswith("runtime"):
                blk["agreement_confuser771"] = agreement_block(pf[C], pi[C], xf[C], xi[C], sf[C], si[C], rng)
                acc = {}
                for who, p in (("float", pf), ("integer", pi)):
                    a = {}
                    for t in (0.5, 0.7):
                        a[f"prf@{t}"] = prf_ci(p[R] >= t, gt[R], rng)
                        a[f"no_person_false_alarm@{t}"] = wilson(int((p[R & tnp] >= t).sum()), int((R & tnp).sum()))
                    a["no_person_false_alarm@0.45"] = wilson(int((p[R & tnp] >= 0.45).sum()), int((R & tnp).sum()))
                    a["confuser771_fp@0.45(>=)"] = wilson(int((p[C] >= 0.45).sum()), int(C.sum()))
                    a["confuser771_fp@0.5(>=)"] = wilson(int((p[C] >= 0.5).sum()), int(C.sum()))
                    a["confuser771_fp@0.7(>=)"] = wilson(int((p[C] >= 0.7).sum()), int(C.sum()))
                    acc[who] = a
                acc["float_confuser_reference"] = FLOAT_CONFUSER_REF[m]
                # paired bootstrap of F1 difference (integer - float) on random1000
                diffs = {}
                for t in (0.5, 0.7):
                    g = gt[R]; a_, b_ = pf[R] >= t, pi[R] >= t; n = len(g); ds = []
                    for _ in range(BOOT):
                        i = rng.integers(0, n, n); ds.append(prf(b_[i], g[i])[5] - prf(a_[i], g[i])[5])
                    diffs[f"f1_int_minus_float@{t}"] = {"p": float(prf(b_, g)[5] - prf(a_, g)[5]), "lo": float(np.percentile(ds, 2.5)), "hi": float(np.percentile(ds, 97.5))}
                acc["paired"] = diffs
                blk["accuracy_random1000"] = acc
                # boundary mechanism: disagreement vs float margin on random set
                lf = fp[R, 9]; dis = (pf[R] >= 0.5) != (pi[R] >= 0.5)
                bins = [0, 0.1, 0.25, 0.5, 1.0, 2.0, np.inf]; strat = []
                for lo, hi in zip(bins[:-1], bins[1:]):
                    s = (np.abs(lf) >= lo) & (np.abs(lf) < hi)
                    strat.append({"float_|logit|": f"[{lo},{hi})", "n": int(s.sum()), "disagree": int(dis[s].sum())})
                blk["random_disagreement_by_float_margin"] = strat
                lfp = fp[P, 9]
                blk["pack_float_margin_hist"] = [{"float_|logit|": f"[{lo},{hi})", "n": int(((np.abs(lfp) >= lo) & (np.abs(lfp) < hi)).sum())} for lo, hi in zip(bins[:-1], bins[1:])]
                # DORY-vs-ORT tolerance: images whose integer vis logit is within 300 raw units of 0 (a DORY deviation could flip p=0.5)
                blk["random_int_vis_within_300raw_of_boundary"] = int((np.abs(d["raw_rt"][R, 9]) <= 300).sum())
                blk["random_int_vis_within_300raw_of_0.7"] = int((np.abs(d["raw_rt"][R, 9] * eps - np.log(0.7 / 0.3)) <= 300 * eps).sum())
                blk["random_int_vis_within_300raw_of_0.45"] = int((np.abs(d["raw_rt"][R, 9] * eps - np.log(0.45 / 0.55)) <= 300 * eps).sum())
                # per-image CSV
                with open(OUT / f"per_image_{m}.csv", "w", newline="") as f:
                    w = csv.writer(f)
                    w.writerow(["image_path", "in_random1000", "in_confuser771", "in_pack560", "gt_visible", "gt_x", "gt_size", "true_no_person",
                                "float_conf", "int_conf", "int_conf_stage06", "float_xbin", "int_xbin", "float_size", "int_size", "int_raw_vis"])
                    pi06 = sig(chans["stage06_staging(sensitivity)"][:, 9])
                    for k in range(len(pf)):
                        w.writerow([str(d["paths"][k]), int(R[k]), int(C[k]), int(P[k]), int(gt[k]), f"{tgt[k,0]:.4f}", f"{tgt[k,1]:.4f}", int(tnp[k]),
                                    f"{pf[k]:.6f}", f"{pi[k]:.6f}", f"{pi06[k]:.6f}", int(xf[k]), int(xi[k]), int(sf[k]), int(si[k]), int(round(d["raw_rt"][k, 9]))])
            mr[cname] = blk
        res[m] = mr
    json.dump(res, open(OUT / "results.json", "w"), indent=1)

    def fmt(w): return f"{w['p']:.4f} [{w['lo']:.4f},{w['hi']:.4f}] ({w['k']}/{w['n']})" if w.get("n") else "n/a"
    def fmtf(w): return f"{w['p']:.4f} [{w['lo']:.4f},{w['hi']:.4f}]"
    for m in MODELS:
        b = res[m]["runtime_staging(primary)"]; s = res[m]["stage06_staging(sensitivity)"]
        print(f"\n===== {m}  eps={res[m]['eps']}  random: gt_vis={res[m]['random_gt_visible']} tnp={res[m]['random_true_no_person']} cropped_out={res[m]['random_person_cropped_out']}")
        for lab, blk in (("RANDOM1000", b["agreement_random1000"]), ("PACK560", b["agreement_pack560"]), ("CONFUSER771", b["agreement_confuser771"]), ("RANDOM1000 stage06-staging", s["agreement_random1000"]), ("PACK560 stage06-staging", s["agreement_pack560"])):
            print(f" [{lab}] vis_agree@0.5 {fmt(blk['vis_agree_p05'])}  (F-vis/I-not {blk['vis_disagree_p05_float_vis_int_not']}, F-not/I-vis {blk['vis_disagree_p05_float_not_int_vis']})")
            print(f"   tri-state agree {fmt(blk['tri_state_agree'])}; float confV={blk['float_confident_visible']} confN={blk['float_confident_not_visible']} unc={blk['float_uncertain']}")
            print(f"   hard contradict confV {fmt(blk['contradict_confident_visible_hard(int<0.45)'])}; confN {fmt(blk['contradict_confident_not_visible_hard(int>=0.7)'])}; any {fmt(blk['contradict_any_confident_hard'])}; soft-change {fmt(blk['confident_float_decision_changed_soft'])}")
            print(f"   both-vis {blk['both_visible_p05']}: xbin exact {fmt(blk['xbin_exact_both_vis'])} within1 {fmt(blk['xbin_within1_both_vis'])}; size exact {fmt(blk['size_exact_both_vis'])} within1 {fmt(blk['size_within1_both_vis'])}")
            print(f"   full decision agree {fmt(blk['full_decision_agree_p05'])}; |dconf| mean {blk['abs_conf_diff_mean']:.4f} p95 {blk['abs_conf_diff_p95']:.4f} max {blk['abs_conf_diff_max']:.4f}")
        a = b["accuracy_random1000"]
        for who in ("float", "integer"):
            x = a[who]
            for t in (0.5, 0.7):
                q = x[f"prf@{t}"]
                print(f"  {who:7s}@{t}: P {fmt(q['precision'])} R {fmt(q['recall'])} F1 {fmtf(q['f1'])}  noperson-FA {fmt(x[f'no_person_false_alarm@{t}'])}")
            print(f"  {who:7s} confuser771 FP@0.45 {fmt(x['confuser771_fp@0.45(>=)'])}  @0.5 {fmt(x['confuser771_fp@0.5(>=)'])} @0.7 {fmt(x['confuser771_fp@0.7(>=)'])}  noperson-FA@0.45 {fmt(x['no_person_false_alarm@0.45'])}")
        print(f"  float confuser ref {a['float_confuser_reference']}; paired F1 int-float {a['paired']}")
        print(f"  random disagreement by float margin: {b['random_disagreement_by_float_margin']}")
        print(f"  pack float margin hist: {b['pack_float_margin_hist']}")
        print(f"  random int vis within 300 raw of 0.5/0.7/0.45: {b['random_int_vis_within_300raw_of_boundary']}/{b['random_int_vis_within_300raw_of_0.7']}/{b['random_int_vis_within_300raw_of_0.45']}")

if __name__ == "__main__":
    main()
