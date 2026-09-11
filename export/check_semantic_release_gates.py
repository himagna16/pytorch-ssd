#!/usr/bin/env python3
"""Semantic release gates for a plain_follow release directory.

Added Sep 10, 2026 after both of our released integer networks were found to
output one constant tensor for every image while the old gates still passed
(the GVSOC check compared one image against a golden produced by the same
broken network). These gates check that the integer network actually looks
at its input:

  1. diversity   - distinct 14-value outputs across the DORY-graph simulator
                   samples (dory_semantic_*/predictions.json)
  2. saturation  - fraction of each hidden layer pinned at its 8-bit ceiling
                   in the golden activations (quant_eval/out_layer*.txt)
  3. agreement   - float vs deployed decisions on the comparison sets
                   (compare_*/comparison_predictions.csv): visibility,
                   x-bin within one bin, size bucket within one bucket
  4. gvsoc       - number of distinct images that passed GVSOC exact match
                   (plus ONNX Runtime agreement for extra images)
  5. weights     - the app's int8 weight files still contain negative values

Standard library only. Exit code 0 = all gates pass, 1 = a gate failed.
Usage: python export/check_semantic_release_gates.py logs/<release_dir> [--json out.json]
"""
import argparse
import csv
import glob
import json
import os
import re
import sys


def load_ints(path):
    with open(path) as f:
        text = f.read()
    body = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    return [int(v) for v in re.findall(r"-?\d+", body)]


def gate_diversity(rel, a):
    rows = []
    for path in sorted(glob.glob(os.path.join(rel, "dory_semantic_*", "predictions.json"))):
        with open(path) as f:
            samples = json.load(f).get("samples", [])
        outs = [tuple(s["raw_output"]) for s in samples if s.get("raw_output")]
        if not outs:
            continue
        distinct = len(set(outs))
        rows.append({"set": os.path.basename(os.path.dirname(path)), "samples": len(outs),
                     "distinct_outputs": distinct, "distinct_fraction": round(distinct / len(outs), 4)})
    total = sum(r["samples"] for r in rows)
    ok = bool(rows) and all(r["distinct_fraction"] >= a.min_distinct_fraction for r in rows)
    return {"gate": "diversity", "pass": ok, "samples": total, "sets": rows,
            "rule": f"every set has distinct outputs on >= {a.min_distinct_fraction:.0%} of samples"}


def gate_saturation(rel, a):
    files = glob.glob(os.path.join(rel, "quant_eval", "out_layer*.txt"))
    files.sort(key=lambda p: int(re.search(r"out_layer(\d+)", p).group(1)))
    rows = []
    for p in files[:-1]:  # the last file is the int32 network output, not an 8-bit activation
        vals = load_ints(p)
        if not vals:
            continue
        rows.append({"layer": os.path.basename(p), "values": len(vals),
                     "at_max": round(sum(v >= a.act_max for v in vals) / len(vals), 4),
                     "at_zero": round(sum(v <= 0 for v in vals) / len(vals), 4),
                     "distinct": len(set(vals))})
    ok = bool(rows) and all(r["at_max"] <= a.max_saturation and r["distinct"] > 1 for r in rows)
    return {"gate": "saturation", "pass": ok, "layers": rows,
            "rule": f"no hidden layer has more than {a.max_saturation:.0%} of values at {a.act_max}, and none is constant"}


def _bin(v, n, lo):
    return max(0, min(n - 1, int((v - lo) * n / (1.0 - lo))))


def gate_agreement(rel, a):
    rows, n_all, vis_ok, x_ok, s_ok, both = [], 0, 0, 0, 0, 0
    for path in sorted(glob.glob(os.path.join(rel, "compare_*", "comparison_predictions.csv"))):
        with open(path) as f:
            recs = list(csv.DictReader(f))
        n_set = len(recs)
        for r in recs:
            n_all += 1
            pre_v, post_v = r["pre_visible"] == "True", r["post_visible"] == "True"
            vis_ok += pre_v == post_v
            if pre_v and post_v:
                both += 1
                x_ok += abs(_bin(float(r["pre_x_value"]), 9, -1.0) - _bin(float(r["post_x_value"]), 9, -1.0)) <= 1
                s_ok += abs(_bin(float(r["pre_size_value"]), 4, 0.0) - _bin(float(r["post_size_value"]), 4, 0.0)) <= 1
        rows.append({"set": os.path.basename(os.path.dirname(path)), "images": n_set})
    res = {"gate": "agreement", "images": n_all, "sets": rows,
           "visibility_agreement": round(vis_ok / n_all, 4) if n_all else None,
           "both_visible": both,
           "x_within_1_bin": round(x_ok / both, 4) if both else None,
           "size_within_1_bucket": round(s_ok / both, 4) if both else None}
    ok = (n_all >= a.min_images and res["visibility_agreement"] is not None
          and res["visibility_agreement"] >= a.min_vis_agreement
          and both > 0 and res["x_within_1_bin"] >= a.min_x_agreement
          and res["size_within_1_bucket"] >= a.min_size_agreement)
    res["pass"] = ok
    res["rule"] = (f">= {a.min_images} images; visibility agreement >= {a.min_vis_agreement:.0%}; "
                   f"x within one bin >= {a.min_x_agreement:.0%} and size within one bucket >= "
                   f"{a.min_size_agreement:.0%} where both say visible")
    if n_all < 500:
        res["warning"] = f"only {n_all} images; the team target is 500+ for release decisions"
    return res


def gate_gvsoc(rel, a):
    """Distinct images with GVSOC exact match. Extra images come from
    run_gvsoc_multi_image.py, which also checks the chip against ONNX Runtime."""
    images, semantic_fail = set(), []
    path = os.path.join(rel, "release_summary.json")
    if os.path.exists(path):
        with open(path) as f:
            smoke = json.load(f).get("gvsoc_smoke") or {}
        if smoke.get("status") == "pass" and smoke.get("image_path"):
            images.add(os.path.basename(smoke["image_path"]))
    multi = os.path.join(rel, "application_export", "gvsoc_multi_image.json")
    if os.path.exists(multi):
        with open(multi) as f:
            for r in json.load(f).get("runs", []):
                sem = r.get("semantic_vs_ort") or {}
                if r.get("status") == "pass" and sem.get("agree"):
                    images.add(os.path.basename(r["image_path"]))
                else:
                    semantic_fail.append(os.path.basename(r.get("image_path", "?")))
    return {"gate": "gvsoc", "pass": len(images) >= a.min_gvsoc_images and not semantic_fail,
            "passing_images": len(images), "failed_images": semantic_fail,
            "rule": f"GVSOC exact match on >= {a.min_gvsoc_images} different images, and every extra "
                    "image agrees with ONNX Runtime (run_gvsoc_multi_image.py)"}


def gate_weights(rel, a):
    """Signed int8 weights must contain negative values (bytes >= 128). On arm64
    NumPy < 1.25, DORY's float->uint8 cast turned every negative weight into 0."""
    files = sorted(glob.glob(os.path.join(rel, "application_export", "application", "**", "*weights*"), recursive=True))
    rows = []
    for p in files:
        if not os.path.isfile(p):
            continue
        with open(p, "rb") as f:
            data = f.read()
        if p.endswith((".hex", ".bin")) and data:
            rows.append({"file": os.path.basename(p), "bytes": len(data),
                         "high_bytes": round(sum(b >= 128 for b in data) / len(data), 4),
                         "zero_bytes": round(data.count(0) / len(data), 4)})
    ok = bool(rows) and all(r["high_bytes"] >= a.min_negative_weight_bytes for r in rows)
    return {"gate": "weights", "pass": ok, "layers": rows,
            "rule": f"every weight file has >= {a.min_negative_weight_bytes:.0%} bytes >= 128 (negative int8 weights survived)"}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("release_dir")
    ap.add_argument("--json", help="write the full report here")
    ap.add_argument("--min-distinct-fraction", type=float, default=0.9)
    ap.add_argument("--act-max", type=int, default=255)
    ap.add_argument("--max-saturation", type=float, default=0.2)
    ap.add_argument("--min-images", type=int, default=90)
    ap.add_argument("--min-vis-agreement", type=float, default=0.9)
    ap.add_argument("--min-x-agreement", type=float, default=0.85)
    ap.add_argument("--min-size-agreement", type=float, default=0.85)
    ap.add_argument("--min-gvsoc-images", type=int, default=3)
    ap.add_argument("--min-negative-weight-bytes", type=float, default=0.05)
    a = ap.parse_args()
    rel = os.path.abspath(a.release_dir)
    gates = [gate_diversity(rel, a), gate_saturation(rel, a), gate_agreement(rel, a), gate_gvsoc(rel, a),
             gate_weights(rel, a)]
    report = {"release_dir": rel, "pass": all(g["pass"] for g in gates), "gates": gates}
    for g in gates:
        print(f"[{'PASS' if g['pass'] else 'FAIL'}] {g['gate']}: {g['rule']}")
        for k in ("sets", "layers"):
            for row in g.get(k, []):
                print("       ", json.dumps(row))
        extra = {k: v for k, v in g.items() if k not in ("gate", "pass", "rule", "sets", "layers")}
        if extra:
            print("       ", json.dumps(extra))
    print("OVERALL:", "PASS" if report["pass"] else "FAIL")
    if a.json:
        with open(a.json, "w") as f:
            json.dump(report, f, indent=2)
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
