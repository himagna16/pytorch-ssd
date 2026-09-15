#!/usr/bin/env python3
"""SIM side, the COHORT render: put MANY real people through the simulator's own
cutout-on-a-card pipeline, so that "the card" can be separated from "this one
person".

WHY THIS EXISTS, and why the pet study could not do it. The pet study's single
most important caveat was that only SIZE was matched, never pose or context: a
real dog that subtends 25 px of a photograph is an incidental dog in a cluttered
room, while the card is upright, isolated and front-facing. It had two animals,
so it could not do better.

People are different. `real_people.py`'s `wui` stratum - whole, unoccluded,
untruncated, upright, ISOLATED people, by COCO's own keypoint visibility flags -
is a set of photographs that already look like what the card looks like. Every
one of them can be pushed through `build_scene.make_cutout` exactly as
s15/s01's person was. That gives a PAIRED comparison:

    the same human being, same photograph, same pixels -> as a photograph
                                                       -> as a rendered card

at the same apparent size, with pose, clothing, lighting of the subject, camera
angle and identity held fixed. What is left between the two is the simulator:
the flat card, the painted panel background, the room, MuJoCo's shading, and
the resampling down to the AI-deck frame.

Geometry is s15_static_offset's, unchanged: the person panel is 1.7 m tall (the
height the scene definition assigns a person regardless of who it is), stands at
x = 3.5, y = 0 on the shipping matte floor, camera on the 0.8 m eye line.

RANGES. The six-point flown ladder 1.5-4.0 m, plus each subject's OWN matched
range `r_match = 1.7 * FOCAL_PX * (128/244) / px128_h_photo`, where the card
subtends exactly what that person subtends in their own photograph's centre
crop. That range is inside or just outside the flown band for most of the
stratum, and it is the pairing that needs no size interpolation at all.

Usage: trainenv/bin/python sim_render_cohort.py <frames_dir> <real_csv> <out_csv>
                                                [--stratum wui] [--limit N]
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
SCENE = "s15_static_offset"
SUBJ = "subj_person_target"
HEIGHT_M = 1.7
SUBJECT_X = 3.5
FLOOR = 0.0
WARMUP, SEEDS = 20, 2
LADDER = [1.5, 2.0, 2.5, 3.0, 3.5, 4.0]
SIDE = [0.0, 0.5]
R_MIN, R_MAX = 1.30, 6.0

FRAMES = Path(sys.argv[1])
REAL = Path(sys.argv[2])
OUT = Path(sys.argv[3])
STRATUM = sys.argv[sys.argv.index("--stratum") + 1] if "--stratum" in sys.argv else "wui"
LIMIT = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else None
SCRATCH = Path("/private/tmp/claude-501/-Users-saimaruvada-Downloads/"
               "90541ca8-cca5-4400-9855-79d1dde551f0/scratchpad/simperson_cohort_build")

K = 128.0 / bs.FRAME_H
PX_AT_1M = HEIGHT_M * bs.FOCAL_PX * K            # px128_h at r = 1 m


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
    subs = [r for r in csv.DictReader(open(REAL)) if r[STRATUM] == "1"]
    subs.sort(key=lambda r: int(r["img_id"]))
    if LIMIT:
        subs = subs[:LIMIT]
    print(f"{len(subs)} subjects in stratum '{STRATUM}'  (px128_h at 1 m = {PX_AT_1M:.1f})", flush=True)

    coco = bs.load_coco(ROOT / "data/coco")
    model, head = bs.load_model(UNSTABLE, CKPT)
    d0 = json.loads((DEFS / f"{SCENE}.json").read_text())
    proto = next(s for s in d0["subjects"] if s["name"] == SUBJ)
    rows, failed = [], []
    t0 = time.time()
    for i, sub in enumerate(subs):
        img_id, ann_id = int(sub["img_id"]), int(sub["subject_ann_id"])
        px_photo = float(sub["px128_h"])
        r_match = round(float(np.clip(PX_AT_1M / px_photo, R_MIN, R_MAX)), 3)
        ranges = sorted(set([r_match] + LADDER))
        dd = {k: v for k, v in d0.items()
              if k not in ("subjects", "occluders", "clutter_primitives",
                           "preview_cam_x", "preview_t_s")}
        dd["scene_id"] = f"cohort_{img_id}_{ann_id}"
        s1 = copy.deepcopy(proto)
        s1.pop("note", None)
        s1["coco"] = {"img_id": img_id, "ann_id": ann_id}
        s1["height_m"] = HEIGHT_M
        s1["pos"] = [SUBJECT_X, 0.0]
        s1["motion"] = {"type": "static"}
        dd["subjects"] = [s1]
        try:
            out, manifest = bs.build(dd, coco, ROOT / "data/coco", SCRATCH,
                                     ["sim_render_cohort.py"], "flat", FLOOR)
            assert manifest["room"]["floor_reflectance"] == FLOOR
            spec = mujoco.MjSpec.from_file(str(out / "scene.xml"))
            make_cam(spec, bs.FLIGHT_HEIGHT)
            m = spec.compile()
        except Exception as e:                       # a cutout the renderer refuses
            failed.append({"img_id": img_id, "ann_id": ann_id, "error": repr(e)[:200]})
            print(f"  !! {img_id}/{ann_id} build failed: {repr(e)[:120]}", flush=True)
            continue
        md = mujoco.MjData(m)
        mujoco.mj_forward(m, md)
        cid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_CAMERA, "probe_cam")
        bid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, SUBJ)
        gid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_GEOM, f"{SUBJ}_panel")
        sx = float(md.xpos[bid][0])
        rgb_r = mujoco.Renderer(m, bs.FRAME_H, bs.FRAME_W)
        seg_r = mujoco.Renderer(m, bs.FRAME_H, bs.FRAME_W)
        seg_r.enable_segmentation_rendering()
        c0 = (bs.FRAME_W - bs.FRAME_H) // 2
        for r in ranges:
            for dy in SIDE:
                if abs(dy) >= 0.8 * r:
                    continue
                cx = sx - (r ** 2 - dy ** 2) ** 0.5
                m.cam_pos[cid] = [cx, dy, bs.FLIGHT_HEIGHT]
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
                geom = HEIGHT_M * bs.FOCAL_PX / r * K
                base = {"img_id": img_id, "ann_id": ann_id, "job": "cohort", "scene": SCENE,
                        "stratum": STRATUM,
                        "whole_upright": int(sub["whole_upright"]), "isolated": int(sub["isolated"]),
                        "wui": int(sub["wui"]), "is_sim_source": int(sub["is_sim_source"]),
                        "px128_h_photo": round(px_photo, 2),
                        "r_match_m": r_match,
                        "is_r_match": int(abs(r - r_match) < 1e-9),
                        "height_m": HEIGHT_M, "subject_x": round(sx, 2),
                        "cam_z": round(bs.FLIGHT_HEIGHT, 3),
                        "range_m": round(r, 3), "dy_m": dy,
                        "azimuth_deg": round(np.degrees(np.arctan2(abs(dy), (r ** 2 - dy ** 2) ** 0.5)), 1),
                        "in_flight_band": int(1.5 <= r <= 4.0),
                        "px128_h": round(px_h * K, 2), "px128_w": round(px_w * K, 2),
                        "px128_h_geom": round(geom, 2),
                        "visible_fraction": round(px_h * K / geom, 3) if geom > 0 else 0.0,
                        "touches_frame_edge": int(bool(rr.size) and (rr[0] == 0 or rr[-1] == bs.FRAME_H - 1))}
                g = luma(rgb)
                fn = f"c{img_id}_{ann_id}_r{r:.3f}_y{dy:+.2f}_clean.png"
                Image.fromarray(g, "L").save(FRAMES / fn)
                rows.append({**base, "camera": "clean", "seed": -1, "frame": fn,
                             "float_bs": round(bs.run_model(model, head, g)["visibility_confidence"], 4),
                             "frame_mean_dn": round(float(g.mean()), 2)})
                for s in range(SEEDS):
                    camm = cm.CameraModel("himax_typical", bs.FRAME_W, bs.FRAME_H, seed=1234 + s)
                    for _ in range(WARMUP):
                        g2 = camm.apply(rgb, omega=np.zeros(3), dt=0.153)
                    g2 = camm.apply(rgb, omega=np.zeros(3), dt=0.153)
                    fn = f"c{img_id}_{ann_id}_r{r:.3f}_y{dy:+.2f}_himax{s}.png"
                    Image.fromarray(g2, "L").save(FRAMES / fn)
                    rows.append({**base, "camera": "himax", "seed": 1234 + s, "frame": fn,
                                 "float_bs": round(bs.run_model(model, head, g2)["visibility_confidence"], 4),
                                 "frame_mean_dn": round(float(g2.mean()), 2)})
        rgb_r.close(); seg_r.close()
        if (i + 1) % 10 == 0:
            print(f"  {i + 1}/{len(subs)} subjects, {len(rows)} frames, "
                  f"{time.time() - t0:.0f} s", flush=True)
    with open(OUT, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {OUT} ({len(rows)} frames from "
          f"{len({r['img_id'] for r in rows})} subjects, {time.time() - t0:.0f} s)", flush=True)
    if failed:
        print(f"BUILD FAILURES: {len(failed)}", flush=True)
        for x in failed:
            print("   ", json.dumps(x), flush=True)
        (OUT.parent / "cohort_build_failures.json").write_text(json.dumps(failed, indent=1))


if __name__ == "__main__":
    main()
