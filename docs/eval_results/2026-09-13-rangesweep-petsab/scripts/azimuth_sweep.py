#!/usr/bin/env python3
"""EXPERIMENT 1, third arm: confidence against VIEWING AZIMUTH at fixed range.

Why this arm exists.  Every subject in these scenes is a flat opaque card - the
builder says so in its own manifest ("THIS PANEL IS AN OPAQUE RECTANGULAR
CARD"), because MuJoCo 3.13 drops the alpha channel.  The card stands in the
y-z plane and faces -x.  Viewed from straight ahead it looks like a person;
viewed from 45 deg off its normal it is foreshortened to 71% of its width, and
the drone sees a squashed person.

In `s07_occlusion_reappear` that is coupled to range by construction.  The
target stands at (3.5, -1.6); the drone flies along y ~ 0.  So its azimuth off
the card normal is atan(1.6 / (3.5 - px)):

    px = 0.0  ->  24.6 deg        px = 1.5  ->  38.7 deg
    px = 1.0  ->  32.6 deg        px = 2.0  ->  46.8 deg

Closing the range in that scene NECESSARILY swings the camera around the card.
Any within-flight binning of confidence against range therefore measures
azimuth as well, and cannot separate the two.  This script separates them: the
camera orbits the subject at CONSTANT range and is aimed at it, so azimuth
moves and range does not.

Nothing here flies.  No simulator, no firmware, no control loop.

Usage: azimuth_sweep.py --scene-root DIR --out DIR
"""
import argparse
import collections
import csv
import json
import math
import os
import statistics as st
import sys
import time
from pathlib import Path

import numpy as np

TOOLS = Path("/Users/saimaruvada/Downloads/drone/pytorch_ssd/tools/crazysim_macos")
DRONE_ROOT = Path("/Users/saimaruvada/Downloads/drone")
sys.path.insert(0, str(TOOLS))
import camera_model as cm                        # noqa: E402
import perception_backends as pb                 # noqa: E402

REC601 = [0.2989, 0.5870, 0.1140]
FRAME_W, FRAME_H = 324, 244
FOVY_DEG = 70.0
VIS_ENTER = 0.70
CKPT = DRONE_ROOT / "pytorch_ssd_unstable/artifacts/successor_qat_ep3_eval.pth"
UNSTABLE = DRONE_ROOT / "pytorch_ssd_unstable"


def main():
    import mujoco
    ap = argparse.ArgumentParser()
    ap.add_argument("--scene-root", type=Path, required=True)
    ap.add_argument("--scene", default="w01_sweep_person_a")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--ranges", type=float, nargs="+",
                    default=[1.5, 2.0, 2.25, 2.5, 3.0, 3.5])
    ap.add_argument("--azimuths", type=float, nargs="+",
                    default=[0, 10, 20, 25, 30, 35, 40, 45, 50, 55])
    ap.add_argument("--heights", type=float, nargs="+", default=[0.80, 0.82, 0.84])
    ap.add_argument("--cameras", nargs="+", default=["clean", "himax_typical"])
    ap.add_argument("--backends", nargs="+", default=["float", "chip"])
    ap.add_argument("--draws", type=int, default=3)
    ap.add_argument("--warmup", type=int, default=30)
    ap.add_argument("--seed", type=int, default=1001)
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    sdir = a.scene_root / a.scene
    man = json.loads((sdir / "manifest.json").read_text())
    subj = man["subjects"][0]
    sx, sy = [float(v) for v in subj["motion"]["p0"]]
    sh = float(subj["panel"]["height_m"])
    refl = float(man["room"]["floor_reflectance"])
    if refl != 0.0:
        sys.exit(f"{a.scene}: floor_reflectance {refl}, not matte - refusing")

    spec = mujoco.MjSpec.from_file(str(sdir / "scene.xml"))
    cam = spec.worldbody.add_camera()
    cam.name, cam.fovy = "az_cam", FOVY_DEG
    cam.alt.type = mujoco.mjtOrientation.mjORIENTATION_XYAXES
    cam.alt.xyaxes = [0, -1, 0, 0, 0, 1]
    model = spec.compile()
    data = mujoco.MjData(model)
    renderer = mujoco.Renderer(model, FRAME_H, FRAME_W)
    cid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_CAMERA, "az_cam")

    bank = {}
    for d in a.ranges:
        for az in a.azimuths:
            r = math.radians(az)
            # Camera orbits the card at constant range d and looks straight at it.
            cx, cy = sx - d * math.cos(r), sy + d * math.sin(r)
            fwd = np.array([math.cos(r), -math.sin(r), 0.0])   # camera -> subject
            right = np.array([-math.sin(r), -math.cos(r), 0.0])
            up = np.array([0.0, 0.0, 1.0])
            R = np.column_stack([right, up, -fwd])
            q = np.empty(4)
            mujoco.mju_mat2Quat(q, R.flatten())
            for h in a.heights:
                model.cam_pos[cid] = [cx, cy, h]
                model.cam_quat[cid] = q
                mujoco.mj_forward(model, data)
                renderer.update_scene(data, camera="az_cam")
                bank[(d, az, h)] = renderer.render().copy()
    print(f"[az] {len(bank)} renders of {a.scene} (subject {sh} m at {sx},{sy})")

    percs = {}
    for b in a.backends:
        percs[b] = (pb.FloatPerception(UNSTABLE, CKPT) if b == "float"
                    else pb.ChipPerception(unstable_root=UNSTABLE, ckpt=CKPT))

    cols = ["scene", "range_m", "azimuth_deg", "cam_h_m", "camera", "draw",
            "backend", "conf", "x_value", "size_bucket", "above_enter"]
    rows = []
    for cam_name in a.cameras:
        camera = None if cam_name == "clean" else cm.CameraModel(
            cam_name, width=FRAME_W, height=FRAME_H, seed=a.seed)
        for (d, az, h), rgb in bank.items():
            if camera is None:
                grays = [np.dot(rgb[..., :3], REC601).astype(np.uint8)]
            else:
                for _ in range(a.warmup):
                    camera.apply(rgb, None, 0.077)
                grays = [camera.apply(rgb, None, 0.077).copy() for _ in range(a.draws)]
            for k, gray in enumerate(grays):
                for b in a.backends:
                    p = percs[b](gray)
                    c = float(p["visibility_confidence"])
                    rows.append([a.scene, d, az, h, cam_name, k, b, round(c, 6),
                                 round(float(p["x_value"]), 6),
                                 int(p["size_bucket_index"]), int(c >= VIS_ENTER)])
        print(f"[az]   {cam_name} done")
    for p in percs.values():
        p.close()

    with open(a.out / "azimuth.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        w.writerows(rows)
    (a.out / "azimuth_meta.json").write_text(json.dumps(
        {"scene": a.scene, "subject_h_m": sh, "subject_pos": [sx, sy],
         "floor_reflectance": refl, "ranges": a.ranges, "azimuths": a.azimuths,
         "heights": a.heights, "cameras": a.cameras, "backends": a.backends,
         "draws": a.draws, "seed": a.seed, "n_rows": len(rows),
         "wall_s": round(time.time() - t0, 1),
         "load": os.getloadavg()}, indent=2))

    # ------------------------------------------------------------- report
    out = []
    def P(s=""):
        out.append(s)
        print(s)

    P("=" * 78)
    P("EXPERIMENT 1, THIRD ARM - CONFIDENCE vs VIEWING AZIMUTH AT FIXED RANGE")
    P("=" * 78)
    P(f"scene {a.scene}  subject {sh} m at ({sx}, {sy})  floor_reflectance {refl:g}")
    P(f"{len(rows)} rows.  Azimuth is the angle between the line of sight and the")
    P("card's normal.  Range is held constant along each row. Nothing flew.")
    P()
    P("s07_occlusion_reappear couples the two: target (3.5, -1.6), drone on y~0, so")
    P("  px 0.0 -> az 24.6 deg | px 1.0 -> 32.6 | px 1.5 -> 38.7 | px 2.0 -> 46.8 deg")
    P()
    for cam_name in a.cameras:
        for b in a.backends:
            P("-" * 78)
            P(f"camera={cam_name}  backend={b}   (mean conf / % of frames >= 0.70)")
            hdr = "range\\az " + " ".join(f"{az:>11.0f}" for az in a.azimuths)
            P(hdr)
            for d in a.ranges:
                cells = []
                for az in a.azimuths:
                    g = [r for r in rows if r[1] == d and r[2] == az
                         and r[4] == cam_name and r[6] == b]
                    if g:
                        cells.append(f"{st.mean([r[7] for r in g]):.3f}/"
                                     f"{100 * sum(r[10] for r in g) / len(g):3.0f}%")
                    else:
                        cells.append(" " * 11)
                P(f"{d:7.2f}  " + " ".join(f"{c:>11}" for c in cells))
            P()
    P("Pooled over range, by azimuth:")
    for cam_name in a.cameras:
        for b in a.backends:
            parts = []
            for az in a.azimuths:
                g = [r for r in rows if r[2] == az and r[4] == cam_name and r[6] == b]
                if g:
                    parts.append(f"{az:.0f}d {st.mean([r[7] for r in g]):.3f}/"
                                 f"{100 * sum(r[10] for r in g) / len(g):.0f}%")
            P(f"  {cam_name:14s} {b:6s} " + "  ".join(parts))
    (a.out.parent / "azimuth_analysis.txt").write_text("\n".join(out) + "\n")
    print(f"\nwrote {a.out}/azimuth.csv and {a.out.parent / 'azimuth_analysis.txt'}")


if __name__ == "__main__":
    main()
