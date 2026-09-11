"""Parity proof on rep16 for the three releases. doryenv. Writes parity_report.json."""
import sys, json, csv, hashlib
from pathlib import Path
import numpy as np, torch
sys.path.insert(0, str(Path(__file__).parent))
import infer as I
from validate_follow_rep16_overlays import AnnotationIndex

def read_txt_vals(p):
    return np.array([float(t) for line in open(p) if not line.startswith("#") for t in line.replace(",", " ").split()])

def main():
    ann = AnnotationIndex(I.ANN)
    rep = {}
    for m, (ckpt, rel) in I.MODELS.items():
        d = np.load(I.OUT / f"parity_{m}.npz", allow_pickle=True)
        paths = [str(p) for p in d["paths"]]; eps = float(d["eps"])
        r = {"eps": eps, "onnx_sha1": str(d["onnx_sha1"])}
        # 1) golden quant_eval input.txt/output.txt (single image; generated with stage-06 staging)
        gin = read_txt_vals(rel / "quant_eval/input.txt"); gout = read_txt_vals(rel / "quant_eval/output.txt")
        from hybrid_follow_image_artifacts import preprocess_image_uint8
        match = None
        for i, p in enumerate(paths):
            rt = preprocess_image_uint8(Path(p), 128, 128, model_type="plain_follow").astype(np.float64)
            if np.array_equal(rt, gin):
                match = i; break
        r["golden_input_equals_runtime_staging_of"] = paths[match] if match is not None else None
        if match is not None:
            r["golden_output_txt"] = gout.tolist(); r["our_ort_rt_raw"] = d["raw_rt"][match].tolist()
            r["golden_output_maxabs_diff_ortrt"] = float(np.abs(d["raw_rt"][match] - gout).max())
        # 2) runtime staging == bundle staged_input; ORT(rt) vs release DORY-sim raw_output
        bundle = json.load(open(rel / "dory_semantic_rep16/input_bundle.json"))
        # NOTE: bundle staged_input is the stage-06 staging; with staging_mode=runtime_preprocess_uint8 the sim ignores it and re-stages from image_path
        r["bundle_staging_mode"] = bundle["staging_mode"]
        bsha = {s["image_path"]: hashlib.sha1(np.asarray(s["staged_input"], dtype=np.uint8).tobytes()).hexdigest() for s in bundle["samples"]}
        import hashlib as _h
        s06sha = [_h.sha1(I.build_eval_inputs(p, ann, (128, 128))[1].numpy().astype(np.uint8).tobytes()).hexdigest() for p in paths]
        r["bundle_staged_input_equals_stage06_staging"] = int(sum(bsha.get(p) == s for p, s in zip(paths, s06sha))), len(paths)
        pred = json.load(open(rel / "dory_semantic_rep16/predictions.json"))
        praw = {s["image_path"]: np.asarray(s["raw_output"], dtype=np.float64) for s in pred["samples"]}
        D = np.array([praw[p] for p in paths])
        diff = np.abs(d["raw_rt"] - D)
        r["ortrt_vs_release_dorysim_raw_maxabs"] = float(diff.max()); r["ortrt_vs_release_dorysim_raw_median"] = float(np.median(diff))
        vis_ort = d["raw_rt"][:, 9] * eps; vis_sim = D[:, 9] * eps
        r["ortrt_vs_dorysim_vis_sign_agree"] = int(((vis_ort >= 0) == (vis_sim >= 0)).sum())
        r["ortrt_vs_dorysim_xbin_agree"] = int((d["raw_rt"][:, :9].argmax(1) == D[:, :9].argmax(1)).sum())
        r["ortrt_vs_dorysim_size_agree"] = int((d["raw_rt"][:, 10:14].argmax(1) == D[:, 10:14].argmax(1)).sum())
        # 3) float confidence vs compare_rep16 pre_visibility_confidence; and post conf (DORY sim) vs our ORT
        rows = {row["image_path"]: row for row in csv.DictReader(open(rel / "compare_rep16/comparison_predictions.csv"))}
        pre = np.array([float(rows[p]["pre_visibility_confidence"]) for p in paths])
        post = np.array([float(rows[p]["post_visibility_confidence"]) for p in paths])
        mine = 1 / (1 + np.exp(-d["fp"][:, 9]))
        r["float_conf_maxabs_vs_release"] = float(np.abs(mine - pre).max())
        r["float_xvalue_agree"] = int(sum(abs(float(I.torch.tensor(0)) + [(-1 + (2 * k + 1) / 9) for k in range(9)][int(d["fp"][i, :9].argmax())] - float(rows[p]["pre_x_value"])) < 1e-5 for i, p in enumerate(paths)))
        r["post_conf_maxabs_ourORTrt_vs_release_dorysim"] = float(np.abs(1 / (1 + np.exp(-vis_ort)) - post).max())
        r["post_conf_maxabs_dorysimraw_vs_csv"] = float(np.abs(1 / (1 + np.exp(-vis_sim)) - post).max())
        # labels vs csv gt
        r["gt_visible_agree"] = int(sum((d["target"][i, 2] > 0.5) == (rows[p]["gt_visible"] == "True") for i, p in enumerate(paths)))
        rep[m] = r
    # fixtest ORT numbers were on logs/plain_follow_prod_qat (non-final); check if identical onnx
    fx = Path("/Users/saimaruvada/Downloads/drone/pytorch_ssd_unstable/logs/plain_follow_prod_qat/quant_eval/model_id_dory.onnx")
    rep["fixtest_prod_qat_onnx_sha1"] = hashlib.sha1(fx.read_bytes()).hexdigest() if fx.exists() else None
    if rep["fixtest_prod_qat_onnx_sha1"] == rep["champion"]["onnx_sha1"]:
        o = json.load(open("/private/tmp/claude-501/-Users-saimaruvada-Downloads/90541ca8-cca5-4400-9855-79d1dde551f0/scratchpad/gate0/fixtest/champ/onnx_stages.json"))
        d = np.load(I.OUT / "parity_champion.npz", allow_pickle=True)
        name2i = {Path(p).name: i for i, p in enumerate(d["paths"])}
        diffs = [float(np.abs(np.array(row["ort_dory_rt"]) - d["raw_rt"][name2i[Path(row["image_path"]).name]]).max())
                 for row in o["rows"] if Path(row["image_path"]).name in name2i]
        rep["fixtest_ort_dory_rt_vs_ours_maxabs"] = (max(diffs) if diffs else None, len(diffs))
    json.dump(rep, open(I.OUT / "parity_report.json", "w"), indent=1)
    print(json.dumps(rep, indent=1))


if __name__ == '__main__':
    main()