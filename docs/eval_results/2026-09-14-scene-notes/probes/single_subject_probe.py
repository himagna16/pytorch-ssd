#!/usr/bin/env python3
"""Re-measure the per-subject "Probe: a/b/c at 1.5/2.5/3.5 m" claims in
scene_defs/*.json on the MATTE floor (build_scene.py default, reflectance 0.0).

NOTHING HERE FLIES. No simulator process, no firmware, no control loop.

Two probe modes:

  single   the one subject named in the note is built ALONE (same COCO cutout,
           same height, static, straight ahead at y = 0, no clutter, the
           scene's own lighting variant) with build_scene.build(), and an
           offscreen MuJoCo camera on the drone's eye line (x, 0, 0.8) facing
           +x is stepped so the camera-to-subject range takes the values the
           note quotes. This is the shape of the number the notes report
           ("0.482 at 1.5 m"): one subject, one range.
  path     the scene's own scenes_v2/<id>/scene.xml, scripted subjects placed
           at preview_t (build_scene.preview_qpos), camera stepped along the
           eye line - used for s09's own approach path and for frame stats.

Perception, per rendered frame:
  float/clean   exactly build_scene.py --preview's probe: REC601 luma of the
                render -> centre square crop -> 128x128 bilinear -> the champion
                float checkpoint (successor_qat_ep3_eval.pth), i.e. what the
                __proven cells fly.
  chip/clean    perception_backends.ChipPerception: firmware_preprocess +
                model_id_dory.onnx under doryenv - the integer network the
                GAP8 runs. vis_gate is raw[9] >= 5467, i.e. p >= 0.75.
  */himax       the same two nets after camera_model.CameraModel('himax_typical')
                (what the __ships cells fly); stochastic, so WARMUP AE-settle
                frames then SEEDS independent draws, mean and per-draw reported.

Pixel height is measured by MuJoCo segmentation of the subject's panel geom.

Usage: trainenv python single_subject_probe.py <results_dir> <scratch_dir> [job ...]
"""
import copy
import json
import math
import sys
import time
from pathlib import Path

import numpy as np

SIMDIR = Path("/Users/saimaruvada/Downloads/drone/pytorch_ssd/tools/crazysim_macos")
sys.path.insert(0, str(SIMDIR))
import mujoco                                   # noqa: E402
import build_scene as bs                        # noqa: E402
import camera_model as cm                       # noqa: E402
import perception_backends as pb                # noqa: E402

RES = Path(sys.argv[1])
SCRATCH = Path(sys.argv[2])
ONLY = set(sys.argv[3:])
CKPT = bs.DRONE_ROOT / "pytorch_ssd_unstable/artifacts/successor_qat_ep3_eval.pth"
UNSTABLE = bs.DRONE_ROOT / "pytorch_ssd_unstable"
DEFS = SIMDIR / "scene_defs"
SCENES = SIMDIR / "scenes_v2"
WARMUP, SEEDS = 20, 2
FLOOR = 0.0

CLAIM3 = [1.5, 2.5, 3.5]
LADDER = [1.0, 1.25, 1.5, 1.75, 2.0, 2.25, 2.5, 2.75, 3.0, 3.25, 3.5, 4.0]

# (job id, scene, subject, mode, ranges, ranges that get himax draws)
JOBS = [
    ("s10_person", "s10_near_threshold_person", "subj_person_target", "single", LADDER, LADDER),
    ("s09_path", "s09_far_person", "subj_person_target", "path", [6.9, 6.5, 6.0, 5.5, 5.0, 4.5, 4.0], [6.9, 6.5, 6.0, 5.5, 5.0, 4.5, 4.0]),
    # walkin: camera fixed at the origin, the SUBJECT moved by its own drift law
    # (t = t_start + (x0 - r) / v) - the note's "along this scene's own path".
    ("s09_walkin", "s09_far_person", "subj_person_target", "walkin", [6.9, 6.5, 6.0, 5.5, 5.0, 4.5, 4.0], [6.9, 6.5, 6.0, 5.5, 5.0, 4.5, 4.0]),
    ("s12_dim_person", "s12_dim_room", "subj_person", "single", [2.0, 2.5, 3.0, 3.5], [3.0]),
    ("s12_path", "s12_dim_room", "subj_person", "path", [3.0, 2.0, 1.0], [3.0]),
    ("s03_dog", "s03_pets_only", "subj_dog", "single", CLAIM3, CLAIM3),
    ("s03_cat", "s03_pets_only", "subj_cat", "single", CLAIM3, CLAIM3),
    ("s04_dummy_tall", "s04_dummies_only", "subj_dummy_tall", "single", [1.5, 2.0, 2.5, 3.0, 3.5], [2.0, 3.0]),
    ("s04_teddy_low", "s04_dummies_only", "subj_teddy_low", "single", CLAIM3, CLAIM3),
    ("s13_chair", "s13_clutter_room", "subj_clut_chair", "single", CLAIM3, CLAIM3),
    ("s05_person", "s05_person_plus_pet", "subj_person_target", "single", [2.5, 3.0, 3.5], []),
    ("s05_pet", "s05_person_plus_pet", "subj_pet_distractor", "single", [2.5, 3.0, 3.5], []),
    ("s01_person", "s01_control_moving", "subj_person", "single", [2.0, 3.0, 3.5], [3.0]),
    ("s11_backlit_person", "s11_backlit_person", "subj_person", "single", [2.0, 3.0, 3.5], [3.0]),
    ("s11_path", "s11_backlit_person", "subj_person", "path", [3.0, 2.0, 1.0], [3.0]),
    ("s02_path", "s02_control_empty", "subj_person", "path", [2.5, 1.5, 0.5], [2.5]),
]

def luma(rgb):
    return np.dot(rgb[..., :3], [0.2989, 0.5870, 0.1140]).astype(np.uint8)

def make_cam(spec):
    cam = spec.worldbody.add_camera()
    cam.name, cam.fovy = "probe_cam", bs.FOVY_DEG
    cam.pos = [0.0, 0.0, bs.FLIGHT_HEIGHT]
    cam.alt.type = mujoco.mjtOrientation.mjORIENTATION_XYAXES
    cam.alt.xyaxes = [0, -1, 0, 0, 0, 1]

def frame_stats(gray, mask):
    d = {"frame_mean_dn": round(float(gray.mean()), 2),
         "distinct_levels": int(len(np.unique(gray))),
         "saturated_fraction": round(float((gray >= 254).mean()), 4)}
    if mask is not None and mask.any():
        d["subject_mean_dn"] = round(float(gray[mask].mean()), 2)
        d["background_mean_dn"] = round(float(gray[~mask].mean()), 2)
        d["subject_minus_background_dn"] = round(d["subject_mean_dn"] - d["background_mean_dn"], 2)
    return d

t_start = time.time()
coco = bs.load_coco(bs.DRONE_ROOT / "pytorch_ssd/data/coco")
model, head = bs.load_model(UNSTABLE, CKPT)
chip = None
try:
    chip = pb.ChipPerception(unstable_root=UNSTABLE, ckpt=CKPT)
    print("chip backend:", json.dumps(chip.info)[:300], flush=True)
except Exception as e:
    print("chip backend unavailable:", e, flush=True)

RES.mkdir(parents=True, exist_ok=True)
jsonl = open(RES / "single_subject_probe.jsonl", "a")
txt = open(RES / "single_subject_probe.txt", "a")
def P(s=""):
    print(s, flush=True); txt.write(s + "\n"); txt.flush()

P(f"# single_subject_probe.py  {time.strftime('%Y-%m-%d %H:%M:%S')}  ckpt={CKPT.name}  chip={'yes' if chip else 'no'}  floor_reflectance={FLOOR}  warmup={WARMUP} seeds={SEEDS}")

for jid, scene, subj, mode, ranges, himax_ranges in JOBS:
    if ONLY and jid not in ONLY:
        continue
    d = json.loads((DEFS / f"{scene}.json").read_text())
    s0 = next(s for s in d["subjects"] if s["name"] == subj)
    if mode == "single":
        rmax = max(ranges)
        dd = {k: v for k, v in d.items() if k not in ("subjects", "occluders", "clutter_primitives", "preview_cam_x", "preview_t_s")}
        dd["scene_id"] = f"probe_{jid}"
        s1 = copy.deepcopy(s0); s1.pop("note", None)
        s1["pos"] = [rmax, 0.0]; s1["motion"] = {"type": "static"}
        dd["subjects"] = [s1]
        out, manifest = bs.build(dd, coco, bs.DRONE_ROOT / "pytorch_ssd/data/coco", SCRATCH, ["single_subject_probe.py"], "flat", FLOOR)
        t_s = 0.0
        sx0 = rmax
    else:
        out = SCENES / scene
        manifest = json.loads((out / "manifest.json").read_text())
        t_s = bs.default_preview_t(manifest, d)
        sx0 = None
    assert manifest["room"]["floor_reflectance"] == FLOOR, manifest["room"]["floor_reflectance"]
    spec = mujoco.MjSpec.from_file(str(out / "scene.xml"))
    make_cam(spec)
    m = spec.compile(); md = mujoco.MjData(m); md.time = t_s
    applied = bs.preview_qpos(m, md, manifest, t_s)
    mujoco.mj_forward(m, md)
    cid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_CAMERA, "probe_cam")
    bid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, subj)
    gid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_GEOM, f"{subj}_panel")
    sx, sy = float(md.xpos[bid][0]), float(md.xpos[bid][1])
    rgb_r = mujoco.Renderer(m, bs.FRAME_H, bs.FRAME_W)
    seg_r = mujoco.Renderer(m, bs.FRAME_H, bs.FRAME_W); seg_r.enable_segmentation_rendering()
    P(f"\n== {jid}: scene {scene} subject {subj} h={s0['height_m']} m coco {s0['coco']['img_id']}/{s0['coco']['ann_id']} mode={mode} lighting={d.get('lighting','default')} t={t_s} subject_at=({sx:.2f},{sy:.2f}) scripted={applied}")
    P(f"   range  px_h  | float/clean  chip/clean gate | float/himax(mean; draws)  chip/himax(mean; draws) | frame stats")
    for r in ranges:
        if mode == "walkin":
            drv = next(x for x in manifest["scripted_motion"]["drives"] if x["joint"] == f"drive_{subj}")
            x0 = float(s0["pos"][0])
            t_s = float(drv["t_start"]) + (x0 - r) / abs(float(drv["v"]))
            md.time = t_s
            applied = bs.preview_qpos(m, md, manifest, t_s)
            mujoco.mj_forward(m, md)
            sx, sy = float(md.xpos[bid][0]), float(md.xpos[bid][1])
            cx = 0.0
            P(f"   [walkin t={t_s:.2f} s subject_at=({sx:.3f},{sy:.3f}) {applied}]")
        else:
            cx = sx - r
        m.cam_pos[cid] = [cx, 0.0, bs.FLIGHT_HEIGHT]
        mujoco.mj_forward(m, md)
        rgb_r.update_scene(md, camera="probe_cam"); rgb = rgb_r.render()
        seg_r.update_scene(md, camera="probe_cam"); seg = seg_r.render()
        mask = (seg[..., 0] == mujoco.mjtObj.mjOBJ_GEOM) & (seg[..., 1] == gid)
        rr = np.where(mask.any(axis=1))[0]
        px_h = int(rr[-1] - rr[0] + 1) if rr.size else 0
        gray = luma(rgb)
        fc = bs.run_model(model, head, gray)
        row = {"job": jid, "scene": scene, "subject": subj, "mode": mode, "range_m": r, "cam_x": round(cx, 3),
               "subject_xy": [round(sx, 3), round(sy, 3)], "px_h": px_h, "preview_t_s": t_s,
               "float_clean": {k: round(v, 4) for k, v in fc.items()},
               "stats": frame_stats(gray, mask)}
        line = f"   {r:5.2f}  {px_h:4d}  | {fc['visibility_confidence']:.3f} sz{int(fc['size_bucket_index'])}"
        if chip is not None:
            cc = chip(gray)
            row["chip_clean"] = {"visibility_confidence": round(cc["visibility_confidence"], 4), "vis_gate_0.75": int(cc["vis_gate"]), "size_bucket_index": int(cc["size_bucket_index"])}
            line += f"      {cc['visibility_confidence']:.3f}  {int(cc['vis_gate'])}   "
        else:
            line += "      n/a          "
        if r in himax_ranges:
            hf, hc = [], []
            for k in range(SEEDS):
                camm = cm.CameraModel("himax_typical", bs.FRAME_W, bs.FRAME_H, seed=1234 + k)
                for _ in range(WARMUP):
                    g2 = camm.apply(rgb, omega=np.zeros(3), dt=0.153)
                g2 = camm.apply(rgb, omega=np.zeros(3), dt=0.153)
                hf.append(round(bs.run_model(model, head, g2)["visibility_confidence"], 4))
                if chip is not None:
                    hc.append(round(chip(g2)["visibility_confidence"], 4))
            row["float_himax"] = {"mean": round(float(np.mean(hf)), 4), "draws": hf}
            line += f" | {np.mean(hf):.3f} {hf}"
            if hc:
                row["chip_himax"] = {"mean": round(float(np.mean(hc)), 4), "draws": hc, "gate_0.75_fraction": round(float(np.mean(np.array(hc) >= 0.75)), 2)}
                line += f"  {np.mean(hc):.3f} {hc}"
        else:
            line += " |"
        line += f" | {row['stats']}"
        P(line)
        jsonl.write(json.dumps(row) + "\n"); jsonl.flush()
    P(f"   ({time.time() - t_start:.0f} s elapsed)")

if chip is not None:
    chip.close()
P(f"# done {time.strftime('%H:%M:%S')}")
