#!/usr/bin/env python3
"""SIM side, step 1 of 2: RENDER the s03 pets at a ladder of ranges and write
the grayscale frames out. Nothing is scored here except one cross-check.

NOTHING HERE FLIES. No simulator process, no firmware, no control loop, no
UDP - an offscreen MuJoCo render of the repo's own scene, exactly the shape of
docs/eval_results/2026-09-14-scene-notes/probes/single_subject_probe.py, whose
"single" mode this reuses: the one subject named in the scene definition is
built ALONE (same COCO cutout, same height_m, static, straight ahead at y = 0,
no clutter, the scene's own lighting) by the repo's own unmodified
build_scene.build() onto the shipping MATTE floor (reflectance 0.0).

APPARENT SIZE is measured, not assumed: MuJoCo segmentation of the subject's
own panel geom, restricted to the centre square crop the network sees,
converted into the 128x128 input's pixels:

    px128 = (visible panel rows inside the crop) * 128 / 244

which is the same quantity real_pets.py measures from a COCO box.

Frames are written as PNG (uint8 grayscale, 324x244 - the AI-deck frame) so
that sim_score.py can score them with champion_arms.py, the SAME module and
the SAME preprocessing the real photographs go through. `float_bs` in the
output is build_scene.run_model's own answer on the same frame, so that the
scoring script's `float` column can be checked against the repo's own probe
path rather than trusted.

Cameras: `clean` is the REC601 luma of the render (what `__proven` cells fly
and what every scene-note probe quotes); `himax` is camera_model.py's
himax_typical (what the `__ships` cells fly, F.pets__ships included), which is
stochastic - WARMUP frames to settle its AE loop, then SEEDS independent draws.

Usage: trainenv/bin/python sim_render.py <frames_dir> <out_csv>
"""
import copy
import csv
import json
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

DRONE = Path("/Users/saimaruvada/Downloads/drone")
ROOT = DRONE / "pytorch_ssd"
SIMDIR = ROOT / "tools/crazysim_macos"
sys.path.insert(0, str(SIMDIR))
import mujoco                                   # noqa: E402
import build_scene as bs                        # noqa: E402
import camera_model as cm                       # noqa: E402

UNSTABLE = DRONE / "pytorch_ssd_unstable"
CKPT = UNSTABLE / "artifacts/successor_qat_ep3_eval.pth"
DEFS = SIMDIR / "scene_defs"
SCENE = "s03_pets_only"
FLOOR = 0.0
WARMUP, SEEDS = 20, 5
FRAMES = Path(sys.argv[1])
OUT = Path(sys.argv[2])
SCRATCH = Path("/private/tmp/claude-501/-Users-saimaruvada-Downloads/"
               "90541ca8-cca5-4400-9855-79d1dde551f0/scratchpad/simpet_build")

FLIGHT = [1.0, 1.25, 1.5, 1.75, 2.0, 2.25, 2.5, 2.75, 3.0, 3.25, 3.5, 3.75, 4.0]
NEAR = [0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.70, 0.80, 0.90]

# (job, subject, camera mode, subject x, ranges)
#   eye       camera on the drone's eye line, z = 0.8 m, facing +x: the FLOWN
#             geometry. A floor-standing pet sits below the optical axis, so
#             closing in pushes it out of the bottom of the frame - which is
#             real, and caps how large the sim pet can ever appear.
#   petlevel  camera lowered to the subject's own centre height, still
#             horizontal. NOT a flown configuration: it is the instrument that
#             lets the SAME card be rendered at the SAME apparent size as its
#             own source photograph, which is the only way to separate "this
#             dog is unusual" from "the simulator changes what the model sees".
#   *_notes   rebuilds the 2026-09-14 scene-notes probe's own geometry (subject
#             at x = 3.5, its three quoted ranges) as a check that this script
#             reproduces the published per-subject numbers.
# LATERAL OFFSET. The camera is moved off the subject's centre line by dy, at
# the same camera-to-subject RANGE, and keeps its heading (+x) - the s03 drone
# is supposed to ignore the pet, so it does not yaw to centre it, and the dog
# itself sways +/-0.5 m in y. This puts the card off-centre in the frame and
# views it from atan(dy/r) off its normal, which is the flat-card foreshortening
# the range sweep found (docs/eval_results/2026-09-13-rangesweep-petsab). It is
# in here so that the sim spread at a given apparent size is a pose spread and
# not only a sensor-noise spread.
SIDE = [0.0, -0.25, 0.25, -0.5, 0.5]
JOBS = [
    ("dog_eye", "subj_dog", "eye", 4.0, NEAR + FLIGHT, SIDE, 3),
    ("cat_eye", "subj_cat", "eye", 4.0, NEAR + FLIGHT, SIDE, 3),
    ("dog_petlevel", "subj_dog", "petlevel", 4.0, NEAR + FLIGHT, [0.0], 5),
    ("cat_petlevel", "subj_cat", "petlevel", 4.0, [0.25, 0.28] + NEAR + FLIGHT, [0.0], 5),
    ("dog_notes", "subj_dog", "eye", 3.5, [1.5, 2.5, 3.5], [0.0], 5),
    ("cat_notes", "subj_cat", "eye", 3.5, [1.5, 2.5, 3.5], [0.0], 5),
]


def luma(rgb):
    return np.dot(rgb[..., :3], [0.2989, 0.5870, 0.1140]).astype(np.uint8)


def make_cam(spec, z):
    cam = spec.worldbody.add_camera()
    cam.name, cam.fovy = "probe_cam", bs.FOVY_DEG
    cam.pos = [0.0, 0.0, z]
    cam.alt.type = mujoco.mjtOrientation.mjORIENTATION_XYAXES
    cam.alt.xyaxes = [0, -1, 0, 0, 0, 1]


def main():
    FRAMES.mkdir(parents=True, exist_ok=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    coco = bs.load_coco(ROOT / "data/coco")
    model, head = bs.load_model(UNSTABLE, CKPT)
    d = json.loads((DEFS / f"{SCENE}.json").read_text())
    rows = []
    t0 = time.time()
    for tag, subj, mode, sub_x, ranges, sides, seeds in JOBS:
        s0 = next(s for s in d["subjects"] if s["name"] == subj)
        h = float(s0["height_m"])
        cam_z = bs.FLIGHT_HEIGHT if mode == "eye" else h / 2.0
        dd = {k: v for k, v in d.items()
              if k not in ("subjects", "occluders", "clutter_primitives", "preview_cam_x", "preview_t_s")}
        dd["scene_id"] = f"simpet_{tag}"
        s1 = copy.deepcopy(s0)
        s1.pop("note", None)
        s1["pos"] = [sub_x, 0.0]
        s1["motion"] = {"type": "static"}
        dd["subjects"] = [s1]
        out, manifest = bs.build(dd, coco, ROOT / "data/coco", SCRATCH, ["sim_render.py"], "flat", FLOOR)
        assert manifest["room"]["floor_reflectance"] == FLOOR, manifest["room"]["floor_reflectance"]
        spec = mujoco.MjSpec.from_file(str(out / "scene.xml"))
        make_cam(spec, cam_z)
        m = spec.compile()
        md = mujoco.MjData(m)
        mujoco.mj_forward(m, md)
        cid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_CAMERA, "probe_cam")
        bid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, subj)
        gid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_GEOM, f"{subj}_panel")
        sx = float(md.xpos[bid][0])
        rgb_r = mujoco.Renderer(m, bs.FRAME_H, bs.FRAME_W)
        seg_r = mujoco.Renderer(m, bs.FRAME_H, bs.FRAME_W)
        seg_r.enable_segmentation_rendering()
        c0 = (bs.FRAME_W - bs.FRAME_H) // 2          # the centre square crop the net sees
        print(f"== {tag} {subj} h={h} coco {s0['coco']['img_id']}/{s0['coco']['ann_id']} "
              f"mode={mode} cam_z={cam_z:.3f} subject_x={sx:.2f} {len(ranges)} ranges", flush=True)
        for r in ranges:
          for dy in sides:
              if abs(dy) >= 0.8 * r:          # would be an absurd viewing angle
                  continue
              cx = sx - (r ** 2 - dy ** 2) ** 0.5
              m.cam_pos[cid] = [cx, dy, cam_z]
              mujoco.mj_forward(m, md)
              rgb_r.update_scene(md, camera="probe_cam")
              rgb = rgb_r.render()
              seg_r.update_scene(md, camera="probe_cam")
              seg = seg_r.render()
              mask = (seg[..., 0] == mujoco.mjtObj.mjOBJ_GEOM) & (seg[..., 1] == gid)
              mcrop = mask[:, c0:c0 + bs.FRAME_H]
              rr = np.where(mcrop.any(axis=1))[0]
              cc = np.where(mcrop.any(axis=0))[0]
              px_h = int(rr[-1] - rr[0] + 1) if rr.size else 0
              px_w = int(cc[-1] - cc[0] + 1) if cc.size else 0
              k = 128.0 / bs.FRAME_H
              geom = h * bs.FOCAL_PX / r * k
              base = {"job": tag, "subject": subj.replace("subj_", ""), "mode": mode,
                      "coco_img_id": s0["coco"]["img_id"], "coco_ann_id": s0["coco"]["ann_id"],
                      "height_m": h, "subject_x": round(sx, 2), "cam_z": round(cam_z, 3),
                      "range_m": r, "dy_m": dy, "azimuth_deg": round(np.degrees(np.arctan2(abs(dy), (r ** 2 - dy ** 2) ** 0.5)), 1),
                      "in_flight_band": int(1.0 <= r <= 4.0),
                      "px128_h": round(px_h * k, 2), "px128_w": round(px_w * k, 2),
                      "px128_h_geom": round(geom, 2),
                      "visible_fraction": round(px_h * k / geom, 3) if geom > 0 else 0.0,
                      "touches_frame_edge": int(bool(rr.size) and (rr[0] == 0 or rr[-1] == bs.FRAME_H - 1))}
              g = luma(rgb)
              fn = f"{tag}_r{r:.2f}_y{dy:+.2f}_clean.png"
              Image.fromarray(g, "L").save(FRAMES / fn)
              rows.append({**base, "camera": "clean", "seed": -1, "frame": fn,
                           "float_bs": round(bs.run_model(model, head, g)["visibility_confidence"], 4),
                           "frame_mean_dn": round(float(g.mean()), 2),
                           "subject_mean_dn": round(float(g[mask].mean()), 2) if mask.any() else -1.0})
              for s in range(seeds):
                  camm = cm.CameraModel("himax_typical", bs.FRAME_W, bs.FRAME_H, seed=1234 + s)
                  for _ in range(WARMUP):
                      g2 = camm.apply(rgb, omega=np.zeros(3), dt=0.153)
                  g2 = camm.apply(rgb, omega=np.zeros(3), dt=0.153)
                  fn = f"{tag}_r{r:.2f}_y{dy:+.2f}_himax{s}.png"
                  Image.fromarray(g2, "L").save(FRAMES / fn)
                  rows.append({**base, "camera": "himax", "seed": 1234 + s, "frame": fn,
                               "float_bs": round(bs.run_model(model, head, g2)["visibility_confidence"], 4),
                               "frame_mean_dn": round(float(g2.mean()), 2),
                               "subject_mean_dn": round(float(g2[mask].mean()), 2) if mask.any() else -1.0})
              print(f"   r={r:5.2f} dy={dy:+.2f} px128 {base['px128_h']:6.1f} (geom {base['px128_h_geom']:6.1f}, "
                    f"vis {base['visible_fraction']:.2f})  float/clean {rows[-seeds - 1]['float_bs']:.3f}  "
                    f"float/himax {np.mean([x['float_bs'] for x in rows[-seeds:]]):.3f}", flush=True)
    with open(OUT, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {OUT} ({len(rows)} frames, {time.time() - t0:.0f} s)", flush=True)


if __name__ == "__main__":
    main()
