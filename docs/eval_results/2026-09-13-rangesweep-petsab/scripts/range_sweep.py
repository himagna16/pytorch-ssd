#!/usr/bin/env python3
"""EXPERIMENT 1 - static range sweep: does the detector lose people at close range?

The Sep 13 matte baseline could not separate two explanations for
`D.occlusion__proven`'s PASS -> FAIL on the M9 relatch gate:

  (a) the drone now closes to ~2 m, past the px > 1.609 m point where the sight
      line clears the partition, so the scene stopped posing an occlusion
      question at all; and
  (b) the detector genuinely loses a plainly visible, frame-filling person
      (above-threshold confidence 92.5% -> 73.6% -> 54.0% across the
      2.5-3.0 / 2.0-2.5 / 1.5-2.0 m bins).

Its range binning was a WITHIN-FLIGHT association: the drone is closest late in
the flight and near the partition, so range was confounded with time and with
the partition.  This script removes the confound the only way it can be
removed - by taking the flight out.

NOTHING HERE FLIES.  There is no simulator, no firmware, no control loop, no
UDP, no Docker.  A MuJoCo offscreen renderer is pointed at a static, unoccluded,
single-person scene from a ladder of exactly-known stand-off distances, and the
perception path is run on the resulting frames.  Range is the only thing that
changes between rows at a fixed yaw/height.  Because no simulator process is
started, this needs no simulator lock (the same property `dump_camera_samples.py`
relies on), though this run held one anyway.

Design
  ranges     1.00 .. 4.00 m in 0.25 m steps (13), true camera-to-subject range
  yaw        -10, -5, 0, +5, +10 deg camera yaw offset.  Yaw moves the subject
             across the frame WITHOUT changing range, so it samples the
             detector's response to off-centre subjects at fixed scale.
  height     0.80 / 0.82 / 0.84 m - the pz band the matte D.occlusion__proven
             flights actually held (0.798-0.844 m, median 0.802).
  subject    two person cutouts: A = COCO 19432/428692 at 1.7 m, the cutout
             D.occlusion__proven and every `person_target` cell uses (the PNG is
             byte-identical to the repo's scenes_v2 copies); B = COCO
             42102/1728930 at 1.75 m, the second cutout in the v2 scene set.
             Two subjects so a falloff cannot be blamed on one image.
  camera     `clean` (REC601 luma of the render - exactly what the unpatched
             simulator pushes, i.e. what the __proven cells fly) and
             `himax_typical` through the repo's own camera_model.py (what the
             __ships cells fly).  The himax model is stochastic, so N draws per
             viewpoint after an AE warm-up; clean is deterministic, 1 draw.
  backend    BOTH: `float` (the laptop checkpoint) and `chip` (the firmware's
             integer preprocessing + model_id_dory.onnx under doryenv) - the
             chip path is the one that flies in the `__ships` cells.

The two backends see BYTE-IDENTICAL frames: each grayscale frame is generated
once and handed to both.  Any difference between the two columns is therefore
the network, never the sensor or the geometry.

Nothing under tools/ is imported by copy - camera_model.py and
perception_backends.py are imported from the repo and used unmodified.

Writes <out>/sweep.csv (one row per frame x backend) and <out>/sweep_meta.json.

Usage:
  range_sweep.py --scene-root <dir> --out <dir> [--draws 3] [--quick]
"""
import argparse
import json
import math
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

TOOLS = Path("/Users/saimaruvada/Downloads/drone/pytorch_ssd/tools/crazysim_macos")
DRONE_ROOT = Path("/Users/saimaruvada/Downloads/drone")
sys.path.insert(0, str(TOOLS))

import camera_model as cm                      # noqa: E402  (repo's own, unmodified)
import perception_backends as pb               # noqa: E402  (repo's own, unmodified)

REC601 = [0.2989, 0.5870, 0.1140]
FRAME_W, FRAME_H = 324, 244                    # crazysim.py CameraRenderer defaults
FOVY_DEG = 70.0                                # drone_models cf2x fpv_cam
TAN_HALF_FOV = math.tan(math.radians(FOVY_DEG / 2))
SIZE_EDGES = (0.25, 0.5, 0.75)                 # utils/follow_task.SIZE_BUCKET4_EDGES
VIS_ENTER, VIS_EXIT = 0.70, 0.45               # follow_person.py defaults
CKPT = DRONE_ROOT / "pytorch_ssd_unstable/artifacts/successor_qat_ep3_eval.pth"
UNSTABLE = DRONE_ROOT / "pytorch_ssd_unstable"


def clean_gray(rgb):
    """Exactly what the unpatched simulator pushes (dump_camera_samples.py)."""
    return np.dot(rgb[..., :3], REC601).astype(np.uint8)


def ideal_size(height_m, rng_m):
    """Fraction of the square crop's height the subject subtends at true range.

    scoreboard.py's own geometry, inverted: d(s) = H / (2 s tan(phi/2)).
    """
    return height_m / (2.0 * rng_m * TAN_HALF_FOV)


def ideal_bucket(s):
    b = 0
    for e in SIZE_EDGES:
        if s >= e:
            b += 1
    return min(b, 3)


def subject_pose(manifest):
    """Name, x, y and panel height of the scene's single subject, from the
    builder's own manifest (motion.p0 is the nominal position; these scenes are
    static so the body never leaves it, and mj_forward at qpos=0 puts it there)."""
    s = manifest["subjects"][0]
    p0 = s["motion"]["p0"]
    return s["name"], float(p0[0]), float(p0[1]), float(s["panel"]["height_m"])


def render_bank(scene_dir: Path, ranges, yaws, heights):
    """RGB renders at every (range, yaw, height). Camera is the flight camera."""
    import mujoco
    scene_xml = scene_dir / "scene.xml"
    manifest = json.loads((scene_dir / "manifest.json").read_text())
    name, sx, sy, sh = subject_pose(manifest)

    spec = mujoco.MjSpec.from_file(str(scene_xml))
    cam = spec.worldbody.add_camera()
    cam.name, cam.fovy = "sweep_cam", FOVY_DEG
    cam.alt.type = mujoco.mjtOrientation.mjORIENTATION_XYAXES
    cam.alt.xyaxes = [0, -1, 0, 0, 0, 1]
    model = spec.compile()
    data = mujoco.MjData(model)
    renderer = mujoco.Renderer(model, FRAME_H, FRAME_W)
    cid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_CAMERA, "sweep_cam")

    out = {}
    for d in ranges:
        for psi in yaws:
            # Camera sits exactly `d` from the subject on the -x side; the yaw
            # offset rotates the VIEW ONLY, so range is untouched by it.
            p = math.radians(psi)
            right = [math.sin(p), -math.cos(p), 0.0]
            up = [0.0, 0.0, 1.0]
            for h in heights:
                model.cam_pos[cid] = [sx - d, sy, h]
                model.cam_mat0[cid] = np.array(
                    [right[0], up[0], -math.cos(p),
                     right[1], up[1], -math.sin(p),
                     right[2], up[2], 0.0], float)
                # cam_mat0 is only the default; set the orientation through the
                # quaternion the renderer actually reads.
                fwd = np.array([math.cos(p), math.sin(p), 0.0])
                zax = -fwd
                xax = np.array(right)
                yax = np.cross(zax, xax)
                R = np.column_stack([xax, yax, zax])
                q = np.empty(4)
                mujoco.mju_mat2Quat(q, R.flatten())
                model.cam_quat[cid] = q
                mujoco.mj_forward(model, data)
                renderer.update_scene(data, camera="sweep_cam")
                out[(round(d, 3), psi, h)] = renderer.render().copy()
    return out, (name, sx, sy, sh)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scene-root", type=Path, required=True)
    ap.add_argument("--scenes", nargs="+", default=["w01_sweep_person_a", "w02_sweep_person_b"])
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--ranges", type=float, nargs="+", default=None)
    ap.add_argument("--yaws", type=float, nargs="+", default=[-10.0, -5.0, 0.0, 5.0, 10.0])
    ap.add_argument("--heights", type=float, nargs="+", default=[0.80, 0.82, 0.84])
    ap.add_argument("--draws", type=int, default=3, help="himax noise draws per viewpoint")
    ap.add_argument("--warmup", type=int, default=30, help="AE settle frames per viewpoint")
    ap.add_argument("--seed", type=int, default=1001, help="camera_model seed (flights use 1000+repeat)")
    ap.add_argument("--cameras", nargs="+", default=["clean", "himax_typical"])
    ap.add_argument("--backends", nargs="+", default=["float", "chip"])
    ap.add_argument("--save-frames-at", type=float, nargs="*", default=[1.5, 2.0, 2.5, 3.0],
                    help="save a PNG of the yaw=0, h=0.80 clean frame at these ranges")
    ap.add_argument("--quick", action="store_true", help="tiny grid, for wiring checks only")
    a = ap.parse_args()

    if a.ranges is None:
        a.ranges = [round(1.0 + 0.25 * i, 2) for i in range(13)]      # 1.00 .. 4.00
    if a.quick:
        a.ranges, a.yaws, a.heights, a.draws, a.warmup = [1.5, 3.0], [0.0], [0.80], 1, 3
        a.scenes = a.scenes[:1]

    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "frames").mkdir(exist_ok=True)
    t_start = time.time()

    percs = {}
    for b in a.backends:
        if b == "float":
            percs[b] = pb.FloatPerception(UNSTABLE, CKPT)
        elif b == "chip":
            percs[b] = pb.ChipPerception(unstable_root=UNSTABLE, ckpt=CKPT)
        else:
            sys.exit(f"unknown backend {b}")
        print(f"[sweep] backend {b} ready: {percs[b].info}")

    cols = ["scene", "subject", "subject_h_m", "range_m", "yaw_deg", "cam_h_m",
            "camera", "draw", "backend", "conf", "vis_logit", "x_value", "x_soft",
            "x_bin", "size_value", "size_bucket", "ideal_size", "ideal_bucket",
            "clipped", "frame_mean_dn", "frame_std_dn", "above_enter", "above_exit",
            "vis_gate"]
    rows = []
    meta = {"ranges": a.ranges, "yaws": a.yaws, "heights": a.heights,
            "draws": a.draws, "warmup": a.warmup, "seed": a.seed,
            "cameras": a.cameras, "backends": a.backends,
            "frame_wh": [FRAME_W, FRAME_H], "fovy_deg": FOVY_DEG,
            "vis_enter": VIS_ENTER, "vis_exit": VIS_EXIT,
            "ckpt": str(CKPT), "scenes": {},
            "backend_info": {b: {k: str(v) for k, v in percs[b].info.items()} for b in percs},
            "host": {"platform": platform.platform(),
                     "load_before": os.getloadavg()}}

    for scene in a.scenes:
        sdir = a.scene_root / scene
        man = json.loads((sdir / "manifest.json").read_text())
        refl = float(man["room"]["floor_reflectance"])
        if refl != 0.0:
            sys.exit(f"{scene}: floor_reflectance is {refl}, not matte - refusing")
        print(f"[sweep] rendering {scene} (floor_reflectance={refl:g}) ...")
        bank, (sname, sx, sy, sh) = render_bank(sdir, a.ranges, a.yaws, a.heights)
        meta["scenes"][scene] = {"subject": sname, "pos": [sx, sy], "height_m": sh,
                                 "floor_reflectance": refl,
                                 "coco": man["subjects"][0]["source"],
                                 "n_renders": len(bank)}
        print(f"[sweep]   {len(bank)} renders; subject {sname} h={sh} at ({sx}, {sy})")

        for cam_name in a.cameras:
            camera = None if cam_name == "clean" else cm.CameraModel(
                cam_name, width=FRAME_W, height=FRAME_H, seed=a.seed)
            n_draw = 1 if camera is None else a.draws
            done = 0
            for (d, psi, h), rgb in bank.items():
                if camera is None:
                    grays = [clean_gray(rgb)]
                else:
                    for _ in range(a.warmup):        # settle the AE loop, as in flight
                        camera.apply(rgb, None, 0.077)
                    grays = [camera.apply(rgb, None, 0.077).copy() for _ in range(n_draw)]
                s_ideal = ideal_size(sh, d)
                clipped = int(s_ideal > 1.0)
                for k, gray in enumerate(grays):
                    fm, fs = float(gray.mean()), float(gray.std())
                    if (cam_name == "clean" and psi == 0.0 and h == a.heights[0]
                            and any(abs(d - r) < 1e-6 for r in (a.save_frames_at or []))):
                        from PIL import Image
                        Image.fromarray(gray).save(
                            a.out / "frames" / f"{scene}_clean_d{d:.2f}.png")
                    for b in a.backends:
                        p = percs[b](gray)
                        conf = float(p["visibility_confidence"])
                        rows.append([
                            scene, sname, sh, d, psi, h, cam_name, k, b,
                            round(conf, 6), round(float(p["visibility_logit"]), 6),
                            round(float(p["x_value"]), 6), round(float(p["x_soft"]), 6),
                            int(p["x_bin_index"]), round(float(p["size_value"]), 6),
                            int(p["size_bucket_index"]), round(s_ideal, 6),
                            ideal_bucket(s_ideal), clipped, round(fm, 2), round(fs, 2),
                            int(conf >= VIS_ENTER), int(conf >= VIS_EXIT),
                            int(p.get("vis_gate", -1)),
                        ])
                done += 1
                if done % 40 == 0:
                    print(f"[sweep]   {scene}/{cam_name}: {done}/{len(bank)} viewpoints")
            print(f"[sweep]   {scene}/{cam_name}: {done} viewpoints done")

    for p in percs.values():
        p.close()

    meta["host"]["load_after"] = os.getloadavg()
    meta["wall_s"] = round(time.time() - t_start, 1)
    meta["n_rows"] = len(rows)

    import csv
    with open(a.out / "sweep.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        w.writerows(rows)
    (a.out / "sweep_meta.json").write_text(json.dumps(meta, indent=2))
    print(f"[sweep] wrote {len(rows)} rows to {a.out}/sweep.csv in {meta['wall_s']:.0f} s")


if __name__ == "__main__":
    main()
