#!/usr/bin/env python3
"""Pre-registered tests 1, 2 and 4: clean F1, F1 under an exposure change, pet false alarms.

Every checkpoint is scored in fake-quant form (default --form qat: learned ranges, as
pre-registered; --form release recalibrates as the release pipeline does, see fq_forms.py) on all of COCO val2017, once clean and once
per exposure factor k. The exposure change is applied in linear light and re-quantised:

    pixel -> round(255 * clip(k * (pixel/255)^2.2, 0, 1)^(1/2.2)) / 255

so k=4 blows highlights out to white and k=0.25 crushes shadows, two things the training
augmentation (contrast/brightness/gamma about the image, clamped) never does on purpose.

Per-checkpoint visibility probabilities are saved as <out>/<label>.npz; the report is
recomputed from those, so re-running the report costs nothing.

Usage (nemoenv python, from pytorch_ssd):
  ../nemoenv/bin/python docs/eval_results/2026-09-26-photometric-aug/scripts/exposure_eval.py \
      --out <dir> champion=<ckpt> aug=<ckpt> control=<ckpt> [--report-only] [--compare aug control]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve()
PYSSD = HERE.parents[4]
sys.path.insert(0, str(PYSSD / "export"))
sys.path.insert(0, str(HERE.parent))

KS = (1.0, 0.25, 0.5, 2.0, 4.0)
THRESHOLDS = np.round(np.arange(0.30, 0.751, 0.05), 2)   # sweep_fq_ckpt.py's grid
GAMMA = 2.2


def expose(x_u8: np.ndarray, k: float) -> np.ndarray:
    """uint8 images -> float32 in [0, 1] with the exposure scaled by k in linear light."""
    x = x_u8.astype(np.float32) / 255.0
    if k == 1.0:
        return x
    y = np.clip(k * np.power(x, GAMMA), 0.0, 1.0) ** (1.0 / GAMMA)
    return np.round(y * 255.0).astype(np.float32) / 255.0


def load_val(cache: Path):
    """COCO val2017 through the val transform, as uint8, plus labels. Cached."""
    if cache.exists():
        z = np.load(cache)
        return z["x"], z["vis"], z["nop"], z["conf"]
    import torch
    from confuser_slice_eval import confuser_negatives, ANN, IMG
    from utils.coco_follow_regression import COCOFollowRegressionDataset
    from utils.transforms import get_val_transforms
    from torch.utils.data import DataLoader

    ds = COCOFollowRegressionDataset(root=str(IMG), ann_file=str(ANN),
                                     transforms=get_val_transforms("hybrid_follow", input_channels=1))
    negs = confuser_negatives()
    conf = np.array([int(i) in negs for i in ds.img_ids])
    xs, vis, nop = [], [], []
    for images, targets in DataLoader(ds, batch_size=64, num_workers=0):
        xs.append(np.round(images.numpy()[:, 0] * 255.0).astype(np.uint8))
        vis.append(targets["follow_target"][:, 2].numpy() > 0.5)
        t = targets.get("true_no_person")
        nop.append(t.view(-1).numpy() > 0 if t is not None else np.zeros(images.shape[0], bool))
    x, vis, nop = np.concatenate(xs), np.concatenate(vis), np.concatenate(nop)
    np.savez_compressed(cache, x=x, vis=vis, nop=nop, conf=conf)
    return x, vis, nop, conf


def score(ckpt: Path, x_u8: np.ndarray, form: str) -> dict:
    import torch
    from fq_forms import load_fq
    from utils.follow_task import decode_follow_outputs

    payload = torch.load(ckpt, map_location="cpu")
    mq, how = load_fq(payload, form)
    print(f"  {ckpt} [{how}]", flush=True)
    out = {}
    with torch.no_grad():
        for k in KS:
            xk = expose(x_u8, k)
            probs = []
            for i in range(0, len(xk), 128):
                batch = torch.from_numpy(xk[i:i + 128])[:, None]
                probs.append(decode_follow_outputs(mq(batch), payload["follow_head_type"])
                             ["visibility_confidence"].numpy())
            out[f"k{k}"] = np.concatenate(probs)
            print(f"    k={k}: mean mean-pixel {xk.mean():.3f}", flush=True)
    return out


def f1_at(p, vis, t):
    pred = p >= t
    tp = np.sum(pred & vis); fp = np.sum(pred & ~vis); fn = np.sum(~pred & vis)
    prec = tp / max(tp + fp, 1); rec = tp / max(tp + fn, 1)
    return 2 * prec * rec / max(prec + rec, 1e-9), rec


def peak(p, vis):
    f1s = [f1_at(p, vis, t)[0] for t in THRESHOLDS]
    i = int(np.argmax(f1s))
    return f1s[i], float(THRESHOLDS[i])


def report(runs: dict, vis, nop, conf, compare, n_boot=1000, seed=0):
    lines = []
    say = lambda s="": (print(s), lines.append(s))
    ks = [k for k in KS if k != 1.0]
    say(f"COCO val2017, n={len(vis)} ({int(vis.sum())} person-visible).")
    say("Threshold for the k columns = that model's own clean peak threshold.\n")
    say(f"{'model':<10} {'clean peak F1':>14} {'@t':>5} | " + " ".join(f"{'k=' + str(k):>7}" for k in ks)
        + f" | {'mean k':>7} | {'pets FP@.45':>11} {'@.55':>6}")
    summary = {}
    for label, pr in runs.items():
        clean = pr["k1.0"]
        f1c, t = peak(clean, vis)
        fk = [f1_at(pr[f"k{k}"], vis, t)[0] for k in ks]
        fp45 = float(np.mean(clean[conf] >= 0.45)); fp55 = float(np.mean(clean[conf] >= 0.55))
        summary[label] = dict(clean=f1c, t=t, fk=fk, mean_k=float(np.mean(fk)), fp45=fp45, fp55=fp55)
        say(f"{label:<10} {f1c:>14.4f} {t:>5.2f} | " + " ".join(f"{v:>7.4f}" for v in fk)
            + f" | {np.mean(fk):>7.4f} | {fp45:>11.3f} {fp55:>6.3f}")
    say(f"\nPeak F1 at each k, each model free to pick its best threshold for that k:")
    for label, pr in runs.items():
        say(f"{label:<10} " + " ".join(f"k={k}: {peak(pr[f'k{k}'], vis)[0]:.4f}@{peak(pr[f'k{k}'], vis)[1]:.2f}"
                                          for k in ks))

    if compare:
        a, b = compare
        A, B = runs[a], runs[b]
        ta, tb = summary[a]["t"], summary[b]["t"]
        rng = np.random.default_rng(seed)
        n = len(vis)
        d_clean, d_mean = [], []
        for _ in range(n_boot):
            idx = rng.integers(0, n, n)
            v = vis[idx]
            d_clean.append(peak(A["k1.0"][idx], v)[0] - peak(B["k1.0"][idx], v)[0])
            d_mean.append(np.mean([f1_at(A[f"k{k}"][idx], v, ta)[0] for k in ks])
                          - np.mean([f1_at(B[f"k{k}"][idx], v, tb)[0] for k in ks]))
        lo = lambda d: np.percentile(d, 2.5); hi = lambda d: np.percentile(d, 97.5)
        dc = summary[a]["clean"] - summary[b]["clean"]
        dm = summary[a]["mean_k"] - summary[b]["mean_k"]
        say(f"\n{a} minus {b}, paired bootstrap over images ({n_boot} resamples, 95%):")
        say(f"  Test 1, clean peak F1:      {dc:+.4f}  [{lo(d_clean):+.4f}, {hi(d_clean):+.4f}]  "
            f"HARM if below -0.005 -> {'HARM' if dc < -0.005 else 'no harm'}")
        say(f"  Test 2, mean F1 over k:     {dm:+.4f}  [{lo(d_mean):+.4f}, {hi(d_mean):+.4f}]  "
            f"SUCCESS if above +0.01 -> {'SUCCESS' if dm > 0.01 else 'NOT MET'}")
        # Test 4 at matched recall: the same rule for both models -- the highest threshold at
        # which the model still finds at least the recall a has at 0.45 on clean images.
        _, rec_a = f1_at(A["k1.0"], vis, 0.45)
        grid = np.round(np.linspace(0.05, 0.95, 181), 3)

        def fp_at_recall(p):
            ok = [t for t in grid if f1_at(p, vis, t)[1] >= rec_a]
            t = max(ok) if ok else grid[0]
            return t, float(np.mean(p[conf] >= t))

        (tam, fam), (tbm, fbm) = fp_at_recall(A["k1.0"]), fp_at_recall(B["k1.0"])
        say(f"  Test 4, pets FP @0.45:      {a} {summary[a]['fp45']:.3f} vs {b} {summary[b]['fp45']:.3f}")
        say(f"          at recall >= {rec_a:.3f}:   {a} {fam:.3f} (t={tam:.3f}) vs {b} {fbm:.3f} (t={tbm:.3f})")
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("models", nargs="+", help="label=checkpoint")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--form", choices=("qat", "release"), default="qat",
                    help="fake-quant form, see fq_forms.py (default qat)")
    ap.add_argument("--unstable-root", type=Path, default=PYSSD.parent / "pytorch_ssd_unstable")
    ap.add_argument("--cache", type=Path, default=None, help="val set cache (default <out>/val_u8.npz)")
    ap.add_argument("--report-only", action="store_true")
    ap.add_argument("--compare", nargs=2, default=None)
    ap.add_argument("--limit", type=int, default=None, help="first N images only (smoke tests)")
    a = ap.parse_args()
    sys.path.insert(0, str(a.unstable_root.resolve()))
    a.out.mkdir(parents=True, exist_ok=True)
    x, vis, nop, conf = load_val(a.cache or a.out / "val_u8.npz")
    if a.limit:
        x, vis, nop, conf = x[:a.limit], vis[:a.limit], nop[:a.limit], conf[:a.limit]
    runs = {}
    for spec in a.models:
        label, _, ck = spec.partition("=")
        f = a.out / (f"{label}_{a.form}.npz" if not a.limit else f"{label}_{a.form}_limit{a.limit}.npz")
        if not a.report_only and not f.exists():
            print(f"scoring {label}", flush=True)
            np.savez_compressed(f, ckpt=str(ck), **score(Path(ck).expanduser(), x, a.form))
        z = np.load(f)
        runs[label] = {k: z[k][: len(vis)] for k in z.files if k.startswith("k")}
    print(f"form: {a.form}")
    text = f"Fake-quant form: {a.form} (fq_forms.py)\n" + report(runs, vis, nop, conf, a.compare)
    if not a.limit:
        (a.out / f"report_{a.form}.txt").write_text(text)


if __name__ == "__main__":
    main()
