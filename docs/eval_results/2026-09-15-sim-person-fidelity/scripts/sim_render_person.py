#!/usr/bin/env python3
"""SIM side, step 1 of 2: RENDER the person cutout the flown CORE cells use, at
a ladder of ranges across the band the drone flies, and write the frames out.

NOTHING HERE FLIES. No simulator process, no firmware, no control loop, no UDP,
no GAP8 - an offscreen MuJoCo render of the repo's own scene, the same shape as
the pet study's `sim_render.py` (itself the shape of the 2026-09-14 scene-notes
probe): the one subject named in the scene definition is built ALONE by the
repo's own unmodified build_scene.build(), static, straight ahead at y = 0, on
the shipping MATTE floor (reflectance 0.0), with the scene's own lighting.

WHICH SUBJECT. `s15_static_offset` and `s01_control_moving` - the two person
cells of the CORE matrix - name the SAME COCO cutout: img 19432 / ann 428692,
height 1.7 m. They differ only in where the person stands, and build_scene
paints each panel's background from the geometry behind it, so panel position
is a real source of spread (the pet study measured up to 0.13 of confidence
from it). Both positions are therefore rendered as separate jobs:

    person_s15   subject x = 3.5   (s15_static_offset's own x)
    person_s01   subject x = 3.0   (s01_control_moving's own x)

APPARENT SIZE is measured, not assumed, by the same code path the pet study
used: MuJoCo segmentation of the subject's own panel geom, restricted to the
centre square crop the network sees, times 128/244. For a 1.7 m person on the
0.8 m eye line the whole body is inside the vertical field only beyond
r ~ 1.29 m; below that the render is truncated and `visible_fraction` falls
away from 1, which is recorded per frame.

RANGES. The flown band is ~1.5-4.0 m. `SAME_SIZE` adds r = 1.44 m, where the
rendered card subtends the same 107.8 px128_h as its OWN source photograph's
centre crop - so the same picture can be compared both ways INSIDE the flown
band, with no padding invented. (The pet study could not do this: its dog
capped at 51.9 px against the photograph's 120 px.)

LATERAL OFFSET, as in the pet study: the camera is moved off the subject's
centre line by dy at the same camera-to-subject RANGE and keeps its heading, so
the card lands off-centre and is seen atan(dy/r) off its normal. s15's person
stands at y = -1.0 while the drone starts at y = 0, so an off-axis view is what
that cell actually presents.

Cameras: `clean` is the REC601 luma of the render (what the `__proven` cells
fly); `himax` is camera_model.himax_typical (what `__ships` flies), which is
stochastic - WARMUP frames to settle its AE loop, then SEEDS independent draws.
Both WARMUP and the draw protocol are the pet study's, unchanged.

Usage: trainenv/bin/python sim_render_person.py <frames_dir> <out_csv>
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
FLOOR = 0.0
WARMUP, SEEDS = 20, 3
FRAMES = Path(sys.argv[1])
OUT = Path(sys.argv[2])
SCRATCH = Path("/private/tmp/claude-501/-Users-saimaruvada-Downloads/"
               "90541ca8-cca5-4400-9855-79d1dde551f0/scratchpad/simperson_build")

FLIGHT = [1.5, 1.75, 2.0, 2.25, 2.5, 2.75, 3.0, 3.25, 3.5, 3.75, 4.0]
SAME_SIZE = [1.44]                      # the photograph's own apparent size
EDGES = [1.30, 4.5, 5.0]                # just outside the flown band, for shape
SIDE = [0.0, -0.25, 0.25, -0.5, 0.5]

# (job, scene, subject name, camera mode, subject x, ranges, lateral offsets, seeds)
JOBS = [
    ("person_s15", "s15_static_offset", "subj_person_target", "eye", 3.5,
     sorted(set(EDGES + SAME_SIZE + FLIGHT)), SIDE, SEEDS),
    ("person_s01", "s01_control_moving", "subj_person", "eye", 3.0,
     sorted(set(EDGES + SAME_SIZE + FLIGHT)), SIDE, SEEDS),
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
    rows = []
    t0 = time.time()
    for tag, scene, subj, mode, sub_x, ranges, sides, seeds in JOBS:
        d = json.loads((DEFS / f"{scene}.json").read_text())
        s0 = next(s for s in d["subjects"] if s["name"] == subj)
        h = float(s0["height_m"])
        cam_z = bs.FLIGHT_HEIGHT if mode == "eye" else h / 2.0
        dd = {k: v for k, v in d.items()
              if k not in ("subjects", "occluders", "clutter_primitives",
                           "preview_cam_x", "preview_t_s")}
        dd["scene_id"] = f"simperson_{tag}"
        s1 = copy.deepcopy(s0)
        s1.pop("note", None)
        s1["pos"] = [sub_x, 0.0]
        s1["motion"] = {"type": "static"}
        dd["subjects"] = [s1]
        out, manifest = bs.build(dd, coco, ROOT / "data/coco", SCRATCH,
                                 ["sim_render_person.py"], "flat", FLOOR)
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
        print(f"== {tag} [{scene}] {subj} h={h} coco {s0['coco']['img_id']}/{s0['coco']['ann_id']} "
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
                base = {"job": tag, "scene": scene, "subject": "person", "mode": mode,
                        "coco_img_id": s0["coco"]["img_id"], "coco_ann_id": s0["coco"]["ann_id"],
                        "height_m": h, "subject_x": round(sx, 2), "cam_z": round(cam_z, 3),
                        "range_m": r, "dy_m": dy,
                        "azimuth_deg": round(np.degrees(np.arctan2(abs(dy), (r ** 2 - dy ** 2) ** 0.5)), 1),
                        "in_flight_band": int(1.5 <= r <= 4.0),
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
                print(f"   r={r:5.2f} dy={dy:+.2f} px128 {base['px128_h']:6.1f} "
                      f"(geom {base['px128_h_geom']:6.1f}, vis {base['visible_fraction']:.2f})  "
                      f"float/clean {rows[-seeds - 1]['float_bs']:.3f}  "
                      f"float/himax {np.mean([x['float_bs'] for x in rows[-seeds:]]):.3f}", flush=True)
    with open(OUT, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {OUT} ({len(rows)} frames, {time.time() - t0:.0f} s)", flush=True)


if __name__ == "__main__":
    main()
