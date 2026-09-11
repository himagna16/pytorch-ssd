"""Firmware nearest-neighbor vs training bilinear preprocessing study. doryenv, CPU only.
Reads repo code read-only; writes only into this directory.
Usage: python study.py infer   -> per_image.npz + frames.u8 (for the C bit-exact check)
       python study.py analyze -> results.json + printed tables
"""
import sys, json, time
from pathlib import Path
import numpy as np, torch, onnxruntime as ort
from PIL import Image
import torchvision.transforms.functional as TF

U = Path("/Users/saimaruvada/Downloads/drone/pytorch_ssd_unstable")
UE = Path("/private/tmp/claude-501/-Users-saimaruvada-Downloads/90541ca8-cca5-4400-9855-79d1dde551f0/scratchpad/unbiased_eval")
sys.path.insert(0, str(U)); sys.path.insert(0, str(U / "export")); sys.path.insert(0, str(UE))
from models.follow_model_factory import build_follow_model_from_checkpoint, load_checkpoint_payload
from utils.transforms import get_val_transforms, _clamp_and_filter_boxes
from utils.coco_follow_regression import compute_follow_target
from utils.follow_task import XBIN9_EDGES, SIZE_BUCKET4_EDGES, _bucketize_visible
from validate_follow_rep16_overlays import AnnotationIndex

OUT = Path(__file__).resolve().parent
ANN = Path("/Users/saimaruvada/Downloads/drone/pytorch_ssd/data/coco/annotations/instances_val2017.json")
CAM_W, CAM_H, NET = 324, 244, 128
CHAMP_CKPT = "/Users/saimaruvada/Downloads/drone/pytorch_ssd_unstable/artifacts/successor_qat_ep3_eval.pth"
CONF_CKPT = "/Users/saimaruvada/Downloads/drone/pytorch_ssd_unstable/artifacts/successor_confuser_ep8.pth"
REL = U / "logs/plain_follow_prod_qat_final"
ONNX = REL / "quant_eval/model_id_dory.onnx"
EPS = float(json.loads((REL / "release_summary.json").read_text())["id_output_eps"]["value"])
VARIANTS = ["bilinear", "nearest", "box2_nearest", "area_box", "bilinear_shift1px"]
torch.set_num_threads(2)

def camera_frame(path, boxes):
    """Emulated 324x244 camera frame: gray, resize-to-COVER 324x244 (PIL bilinear, antialiased = optics-like
    low-pass), center crop 324x244. Boxes follow the same geometry (clamped/filtered with repo helper)."""
    with Image.open(path) as im:
        g = im.convert("L")
    W, H = g.size
    s = max(CAM_W / W, CAM_H / H)
    nw, nh = max(CAM_W, int(round(W * s))), max(CAM_H, int(round(H * s)))
    g = g.resize((nw, nh), Image.BILINEAR)
    left, top = (nw - CAM_W) // 2, (nh - CAM_H) // 2
    g = g.crop((left, top, left + CAM_W, top + CAM_H))
    tgt = {"boxes": boxes.clone(), "labels": torch.ones((boxes.shape[0],), dtype=torch.int64),
           "area": torch.zeros((boxes.shape[0],), dtype=torch.float32),
           "iscrowd": torch.zeros((boxes.shape[0],), dtype=torch.int64)}
    if boxes.numel():
        b = tgt["boxes"]; b[:, [0, 2]] = b[:, [0, 2]] * (nw / W) - left; b[:, [1, 3]] = b[:, [1, 3]] * (nh / H) - top
        tgt = _clamp_and_filter_boxes(tgt, CAM_W, CAM_H)
    return g, tgt

def fw_nearest(cam):  # exact port of crazyflie_ssd/src/preprocess.c (C int division, all operands >= 0)
    h, w = cam.shape; cs = min(w, h); cx = (w - cs) // 2; cy = (h - cs) // 2
    sy = cy + (np.arange(NET) * cs) // NET; sx = cx + (np.arange(NET) * cs) // NET
    return cam[sy[:, None], sx[None, :]]

def fw_box2_nearest(cam):  # proposed C: 2x2 mean at the same nearest index, (sum+2)>>2, edge-clamped
    h, w = cam.shape; cs = min(w, h); cx = (w - cs) // 2; cy = (h - cs) // 2
    sy = cy + (np.arange(NET) * cs) // NET; sx = cx + (np.arange(NET) * cs) // NET
    sy1 = np.minimum(sy + 1, cy + cs - 1); sx1 = np.minimum(sx + 1, cx + cs - 1)
    c = cam.astype(np.uint32)
    s = c[sy[:, None], sx[None, :]] + c[sy[:, None], sx1[None, :]] + c[sy1[:, None], sx[None, :]] + c[sy1[:, None], sx1[None, :]]
    return ((s + 2) >> 2).astype(np.uint8)

def area_box(g):  # true area average of the square crop (PIL BOX)
    w, h = g.size; cs = min(w, h); l, t = (w - cs) // 2, (h - cs) // 2
    return np.asarray(g.crop((l, t, l + cs, t + cs)).resize((NET, NET), Image.BOX), dtype=np.uint8)

def bilinear_shift(g):  # training resize but square crop moved 1 camera px right (natural jitter reference)
    w, h = g.size; cs = min(w, h); l, t = (w - cs) // 2 + 1, (h - cs) // 2
    return np.asarray(TF.resize(TF.crop(g, t, l, cs, cs), [NET, NET]), dtype=np.uint8)

def infer():
    paths = json.loads((UE / "image_sets.json").read_text())["random1000"]
    ann = AnnotationIndex(ANN)
    tf = get_val_transforms(model_type="plain_follow", input_channels=1, image_size=(NET, NET))
    md = load_checkpoint_payload(CHAMP_CKPT, torch.device("cpu")); assert (int(md["height"]), int(md["width"])) == (NET, NET)
    models = {"champion_float": build_follow_model_from_checkpoint(CHAMP_CKPT, torch.device("cpu")).eval(),
              "confuser_float": build_follow_model_from_checkpoint(CONF_CKPT, torch.device("cpu")).eval()}
    so = ort.SessionOptions(); so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_DISABLE_ALL; so.intra_op_num_threads = 2
    sess = ort.InferenceSession(str(ONNX), so, providers=["CPUExecutionProvider"])
    iname, oname = sess.get_inputs()[0].name, sess.get_outputs()[0].name
    frames = np.zeros((len(paths), CAM_H, CAM_W), np.uint8)
    X = {v: np.zeros((len(paths), NET, NET), np.uint8) for v in VARIANTS}
    OUTS = {f"{m}__{v}": np.zeros((len(paths), 14)) for m in list(models) + ["champion_int"] for v in VARIANTS}
    TGT = np.zeros((len(paths), 3), np.float32); TNP = np.zeros(len(paths), bool); maxdiff_tf = 0.0
    t0 = time.time()
    for k, p in enumerate(paths):
        iid = int(Path(p).stem)
        boxes = ann.boxes_for_image(iid); TNP[k] = boxes.shape[0] == 0
        g, tgt = camera_frame(p, boxes)
        cam = np.asarray(g, dtype=np.uint8); frames[k] = cam
        # training-style path = the repo's own val transform applied to the camera frame (also carries the GT boxes)
        t_img, t_tgt = tf(g, tgt)
        ft, _ = compute_follow_target(t_tgt["boxes"], image_height=NET, image_width=NET); TGT[k] = ft.numpy()
        bil = np.round(t_img[0].numpy() * 255.0).astype(np.uint8)
        maxdiff_tf = max(maxdiff_tf, float(np.abs(bil.astype(np.float32) / 255.0 - t_img[0].numpy()).max()))
        X["bilinear"][k] = bil; X["nearest"][k] = fw_nearest(cam); X["box2_nearest"][k] = fw_box2_nearest(cam)
        X["area_box"][k] = area_box(g); X["bilinear_shift1px"][k] = bilinear_shift(g)
        for v in VARIANTS:
            u8 = X[v][k]
            fin = torch.from_numpy(u8.astype(np.float32) / 255.0).view(1, 1, NET, NET)
            with torch.no_grad():
                for m, net in models.items():
                    OUTS[f"{m}__{v}"][k] = net(fin).numpy().reshape(-1)
            OUTS[f"champion_int__{v}"][k] = np.asarray(sess.run([oname], {iname: u8.astype(np.float32).reshape(1, 1, NET, NET)})[0]).reshape(-1) * EPS
        if k % 100 == 0: print(k, round(time.time() - t0, 1), flush=True)
    frames.tofile(OUT / "frames.u8")
    np.savez(OUT / "per_image.npz", paths=np.array(paths), target=TGT, true_no_person=TNP, eps=EPS,
             **{"x_" + v: X[v] for v in VARIANTS}, **{"o_" + k: v for k, v in OUTS.items()})
    print("done", len(paths), "secs", round(time.time() - t0, 1), "max|u8/255 - to_tensor|", maxdiff_tf)

def analyze():
    from analyze import agreement_block, prf_ci, prf, wilson, sig, BOOT
    d = np.load(OUT / "per_image.npz", allow_pickle=True)
    tgt = d["target"]; gtv = tgt[:, 2] > 0.5; tnp = d["true_no_person"]
    gx = _bucketize_visible(torch.from_numpy(tgt[:, 0].copy()), XBIN9_EDGES).numpy()
    gs = _bucketize_visible(torch.from_numpy(tgt[:, 1].copy()), SIZE_BUCKET4_EDGES).numpy()
    rng = np.random.default_rng(20260911)
    res = {"n": int(len(tgt)), "gt_visible": int(gtv.sum()), "true_no_person": int(tnp.sum()),
           "person_cropped_out": int((~gtv & ~tnp).sum()), "eps": float(d["eps"]), "pixel": {}, "models": {}}
    ref = d["x_bilinear"].astype(np.float64)
    for v in VARIANTS:
        diff = d["x_" + v].astype(np.float64) - ref
        res["pixel"][v] = {"mae_vs_bilinear": float(np.abs(diff).mean()), "rmse_vs_bilinear": float(np.sqrt((diff ** 2).mean())),
                           "p99_abs": float(np.percentile(np.abs(diff), 99)), "mean_bias": float(diff.mean())}
    for m in ["champion_float", "confuser_float", "champion_int"]:
        o = {v: d[f"o_{m}__{v}"] for v in VARIANTS}
        P = {v: sig(o[v][:, 9]) for v in VARIANTS}; XB = {v: o[v][:, :9].argmax(1) for v in VARIANTS}; SB = {v: o[v][:, 10:14].argmax(1) for v in VARIANTS}
        mr = {"agreement_vs_bilinear": {}, "accuracy": {}, "paired_f1_minus_bilinear": {}}
        for v in VARIANTS[1:]:
            mr["agreement_vs_bilinear"][v] = agreement_block(P["bilinear"], P[v], XB["bilinear"], XB[v], SB["bilinear"], SB[v], rng)
        for v in VARIANTS:
            a = {}
            for t in (0.5, 0.7):
                a[f"prf@{t}"] = prf_ci(P[v] >= t, gtv, rng)
                a[f"no_person_false_alarm@{t}"] = wilson(int((P[v][tnp] >= t).sum()), int(tnp.sum()))
            both = gtv & (P[v] >= 0.5)
            a["xbin_exact_on_gtvis_predvis"] = wilson(int((XB[v][both] == gx[both]).sum()), int(both.sum()))
            a["xbin_within1_on_gtvis_predvis"] = wilson(int((np.abs(XB[v][both] - gx[both]) <= 1).sum()), int(both.sum()))
            a["size_exact_on_gtvis_predvis"] = wilson(int((SB[v][both] == gs[both]).sum()), int(both.sum()))
            a["xbin_exact_on_gtvis"] = wilson(int((XB[v][gtv] == gx[gtv]).sum()), int(gtv.sum()))
            a["size_exact_on_gtvis"] = wilson(int((SB[v][gtv] == gs[gtv]).sum()), int(gtv.sum()))
            mr["accuracy"][v] = a
        for v in VARIANTS[1:]:
            pd = {}
            for t in (0.5, 0.7):
                a_, b_ = P["bilinear"] >= t, P[v] >= t; n = len(gtv); ds = []
                for _ in range(BOOT):
                    i = rng.integers(0, n, n); ds.append(prf(b_[i], gtv[i])[5] - prf(a_[i], gtv[i])[5])
                pd[f"@{t}"] = {"p": float(prf(b_, gtv)[5] - prf(a_, gtv)[5]), "lo": float(np.percentile(ds, 2.5)), "hi": float(np.percentile(ds, 97.5))}
            mr["paired_f1_minus_bilinear"][v] = pd
        res["models"][m] = mr
    json.dump(res, open(OUT / "results.json", "w"), indent=1)
    f = lambda w: f"{100*w['p']:.1f}% ({w['k']}/{w['n']})" if w.get("n") else "n/a"
    print(json.dumps({k: res[k] for k in ("n", "gt_visible", "true_no_person", "person_cropped_out")}))
    for v, px in res["pixel"].items(): print(f"pixel {v:18s} MAE {px['mae_vs_bilinear']:.2f} RMSE {px['rmse_vs_bilinear']:.2f} p99 {px['p99_abs']:.0f} bias {px['mean_bias']:+.2f}")
    for m, mr in res["models"].items():
        print(f"\n=== {m}")
        for v, b in mr["agreement_vs_bilinear"].items():
            print(f" {v:18s} vis@0.5 {f(b['vis_agree_p05'])} tri {f(b['tri_state_agree'])} hard {f(b['contradict_hard_per_image'])} soft {f(b['confident_float_decision_changed_soft'])} "
                  f"x {f(b['xbin_exact_both_vis'])} x1 {f(b['xbin_within1_both_vis'])} size {f(b['size_exact_both_vis'])} full {f(b['full_decision_agree_p05'])} |dp| {b['abs_conf_diff_mean']:.4f}/{b['abs_conf_diff_p95']:.4f}")
        for v, a in mr["accuracy"].items():
            q5, q7 = a["prf@0.5"], a["prf@0.7"]
            print(f" ACC {v:18s} F1@.5 {q5['f1']['p']:.4f} P {q5['precision']['p']:.4f} R {q5['recall']['p']:.4f} | F1@.7 {q7['f1']['p']:.4f} P {q7['precision']['p']:.4f} R {q7['recall']['p']:.4f} "
                  f"| FA@.5 {f(a['no_person_false_alarm@0.5'])} | x {f(a['xbin_exact_on_gtvis_predvis'])} x1 {f(a['xbin_within1_on_gtvis_predvis'])} size {f(a['size_exact_on_gtvis_predvis'])}")
        for v, pd in mr["paired_f1_minus_bilinear"].items():
            print(f" dF1 {v:18s} " + "  ".join(f"{t} {x['p']:+.4f} [{x['lo']:+.4f},{x['hi']:+.4f}]" for t, x in pd.items()))

if __name__ == "__main__":
    {"infer": infer, "analyze": analyze}[sys.argv[1]]()
