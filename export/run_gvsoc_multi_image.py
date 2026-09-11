#!/usr/bin/env python3
"""Run GVSOC on several extra images for an already generated release app.

Added Sep 10, 2026. The release's single-image GVSOC smoke compares the chip
against a golden produced by the same DORY code, so a DORY bug passes it (this
is how our Aug 28 / Aug 31 releases shipped with every negative weight zeroed).
For each extra image this script checks two things:

  exact     GVSOC final tensor == DORY-graph golden (bit-exact app build check)
  semantic  decoded GVSOC output agrees with ONNX Runtime on model_id_dory.onnx
            (an independent reference): same visibility decision, x-bin and
            size bucket within one

Writes <release>/application_export/gvsoc_multi_image.json, which
check_semantic_release_gates.py reads. Run with the same Python as the release
driver (nemoenv), after run_plain_follow_release.py finished for <release>.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

EXPORT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(EXPORT_DIR))
sys.path.insert(0, str(EXPORT_DIR.parent))

import run_plain_follow_release as rel  # noqa: E402
from hybrid_follow_image_artifacts import stage_image_artifacts  # noqa: E402


def decode(values, vis_thresh):
    xs, vis, size = values[0:9], values[9], values[10:14]
    return {"x_bin": max(range(9), key=lambda i: (xs[i], -i)),
            "size_bucket": max(range(4), key=lambda i: (size[i], -i)),
            "vis_raw": vis}


def semantic_agree(d_chip, d_ort):
    """Visibility sign must match. Position and size are compared only when ONNX
    Runtime says a person is visible: the follower ignores them otherwise, and on
    empty frames the x logits are often near-ties that flip on DORY's small
    rounding differences (same rule as the agreement gate)."""
    if (d_chip["vis_raw"] > 0) != (d_ort["vis_raw"] > 0):
        return False
    if d_ort["vis_raw"] <= 0:
        return True
    return abs(d_chip["x_bin"] - d_ort["x_bin"]) <= 1 and abs(d_chip["size_bucket"] - d_ort["size_bucket"]) <= 1


def rescore(path):
    """Re-evaluate an existing gvsoc_multi_image.json without re-running GVSOC."""
    d = json.loads(Path(path).read_text())
    for r in d["runs"]:
        if len(r.get("gvsoc_values") or []) == 14 and r.get("ort_golden"):
            chip, ort = decode(r["gvsoc_values"], None), decode(r["ort_golden"], None)
            r["semantic_vs_ort"] = {"x_bin_chip": chip["x_bin"], "x_bin_ort": ort["x_bin"],
                                    "size_chip": chip["size_bucket"], "size_ort": ort["size_bucket"],
                                    "vis_raw_chip": chip["vis_raw"], "vis_raw_ort": ort["vis_raw"],
                                    "agree": semantic_agree(chip, ort)}
        print(f"[{r['status']}] {Path(r['image_path']).name}: semantic_vs_ort={r['semantic_vs_ort'] and r['semantic_vs_ort']['agree']}")
    d["rule"] = "visibility sign must match; x-bin and size within one only when ORT says visible"
    Path(path).write_text(json.dumps(d, indent=2))
    return 0 if all(r["status"] == "pass" and r["semantic_vs_ort"] and r["semantic_vs_ort"]["agree"] for r in d["runs"]) else 1


def pick_images(rep16_dir: Path, smoke_image: str | None, n_visible: int, n_negative: int):
    imgs = sorted(p for p in rep16_dir.iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png"))
    imgs = [p for p in imgs if smoke_image is None or p.name != Path(smoke_image).name]
    vis = [p for p in imgs if "visible" in p.stem.lower()]
    neg = [p for p in imgs if "negative" in p.stem.lower()]
    # spread picks across the list instead of taking neighbours
    spread = lambda xs, k: [xs[round(i * (len(xs) - 1) / max(1, k - 1))] for i in range(k)] if xs and k else []
    return spread(vis, n_visible) + spread(neg, n_negative)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("release_dir")
    ap.add_argument("--images", nargs="*", help="explicit images (default: spread over rep16)")
    ap.add_argument("--n-visible", type=int, default=2)
    ap.add_argument("--n-negative", type=int, default=2)
    ap.add_argument("--dory-python", default=str(rel.PROJECT_DIR.parent / "doryenv" / "bin" / "python3"))
    ap.add_argument("--rescore-only", action="store_true",
                    help="re-evaluate an existing gvsoc_multi_image.json without running GVSOC")
    a = ap.parse_args()
    if a.rescore_only:
        return rescore(Path(a.release_dir).resolve() / "application_export" / "gvsoc_multi_image.json")

    release = Path(a.release_dir).resolve()
    summary = json.loads((release / "release_summary.json").read_text())
    smoke = summary.get("gvsoc_smoke") or {}
    art = smoke.get("artifacts") or {}
    app_dir = Path(art["application_dir"])
    dory_onnx = Path(art["dory_onnx"])
    layer_manifest = Path(art["gap8_layer_manifest"])
    vis_thresh = float(summary["deployment_vis_thresh"])
    vis_logit = math.log(vis_thresh / (1 - vis_thresh))
    rep16 = Path(summary["artifacts"]["rep16_dir"])
    images = [Path(p).resolve() for p in a.images] if a.images else pick_images(
        rep16, smoke.get("image_path"), a.n_visible, a.n_negative)

    context = {
        "dory_io_helper": str(rel.DEFAULT_DORY_IO_HELPER),
        "dory_python": a.dory_python,
        "dory_config_template": str(rel.DEFAULT_DORY_CONFIG_TEMPLATE),
        "model_type": "plain_follow",
    }
    root = release / "application_export" / "gvsoc_multi"
    cmd_dir = release / "commands"
    runs = []
    for i, img in enumerate(images):
        work = root / f"{i:02d}_{img.stem}"
        seed = rel.prepare_dory_io_seed(context=context, image_path=img, dory_onnx_path=dory_onnx,
                                        output_dir=work / "dory_seed",
                                        log_path=cmd_dir / f"13_{i:02d}_dory_io_seed.log")
        dory_golden = rel.parse_int_text_file(seed["output_txt"])
        ort_art = stage_image_artifacts(image_path=img, onnx_path=dory_onnx, output_dir=work / "ort",
                                        model_type="plain_follow")
        ort_golden = rel.parse_int_text_file(Path(ort_art.output_txt))
        staged = stage_image_artifacts(image_path=img, onnx_path=dory_onnx, output_dir=work / "staged",
                                       app_dir=app_dir, model_type="plain_follow",
                                       expected_output=dory_golden, expected_output_name=rel.DEFAULT_GVSOC_LABEL,
                                       expected_source=seed["reference_source"])
        final_json = work / "gvsoc_final_tensor.json"
        env = {
            "HOST_REPO_ROOT": str(rel.REPO_DIR), "HOST_APP_DIR": str(app_dir),
            "HOST_VALIDATION_MAIN": str(rel.DEFAULT_VALIDATION_MAIN),
            "HOST_EXPECTED_OUTPUT": str(staged.output_txt), "HOST_INPUT_HEX": str(staged.input_hex),
            "HOST_RUN_LOG_COPY": str(work / "gvsoc_run.log"), "HOST_FINAL_TENSOR_JSON": str(final_json),
            "HOST_TRACE_LAYER_OUTPUTS": "0", "HOST_PATCH_BN_QUANT_INT64": "1",
            "HOST_LAYER_MANIFEST": str(layer_manifest),
            "COMPARE_SCRIPT": str(rel.DEFAULT_GVSOC_COMPARE_SCRIPT), "VERIFY_AFTER_RUN": "1",
            "EXPECTED_TENSOR_LABEL": rel.DEFAULT_GVSOC_LABEL, "EXPECTED_TENSOR_COUNT": "14",
            "RUN_STAGE_DRIFT_DEBUG": "0", "AUTO_REFRESH_APP": "0",  # never let the script regenerate application/
            "MODEL_SENTINEL": str(dory_onnx), "MODEL_MANIFEST": str(art["generated_config"]),
            "PLATFORM": rel.DEFAULT_GVSOC_PLATFORM, "AIDECK_IMAGE": rel.DEFAULT_AIDECK_IMAGE,
        }
        error = None
        try:
            rel.run_logged(["bash", str(rel.DEFAULT_GVSOC_SCRIPT)], log_path=cmd_dir / f"13_{i:02d}_gvsoc.log",
                           cwd=rel.PROJECT_DIR, extra_env=env)
        except Exception as exc:  # a mismatch makes the compare step exit non-zero; record it
            error = str(exc)[:500]
        actual = [int(v) for v in (json.loads(final_json.read_text()).get("values") or [])] if final_json.exists() else []
        d_chip, d_ort = (decode(actual, vis_thresh) if len(actual) == 14 else None), decode(ort_golden, vis_thresh)
        eps_note = "visibility compared by sign of (raw - logit(thresh)/eps) is unavailable; using raw sign agreement"
        semantic = None
        if d_chip:
            semantic = {
                "x_bin_chip": d_chip["x_bin"], "x_bin_ort": d_ort["x_bin"],
                "size_chip": d_chip["size_bucket"], "size_ort": d_ort["size_bucket"],
                "vis_raw_chip": d_chip["vis_raw"], "vis_raw_ort": d_ort["vis_raw"],
                "agree": semantic_agree(d_chip, d_ort),
            }
        runs.append({
            "image_path": str(img),
            "status": "pass" if actual == dory_golden and error is None else "mismatch",
            "exact_vs_dory_golden": actual == dory_golden,
            "gvsoc_values": actual, "dory_golden": dory_golden, "ort_golden": ort_golden,
            "semantic_vs_ort": semantic, "error": error,
        })
        print(f"[{runs[-1]['status']}] {img.name}: semantic_vs_ort={semantic and semantic['agree']}", flush=True)
    out = {"release_dir": str(release), "deployment_vis_thresh": vis_thresh, "note": eps_note,
           "rule": "visibility sign must match; x-bin and size within one only when ORT says visible", "runs": runs}
    path = release / "application_export" / "gvsoc_multi_image.json"
    path.write_text(json.dumps(out, indent=2))
    print("wrote", path)
    ok = all(r["status"] == "pass" and r["semantic_vs_ort"] and r["semantic_vs_ort"]["agree"] for r in runs)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
