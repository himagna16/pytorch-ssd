#!/usr/bin/env python3
"""Render the protocol's clip set as the mock AI-deck would serve it.

Person (scenes_v2/s15_static_offset, the COCO cutout the acceptance suite
uses) at the capture protocol's own geometry - 1.5 / 2.5 / 3.5 m at bearings
0, +-10, +-25 deg (docs/real_frame_capture_protocol.md section 2) - plus an
empty room (s02_control_empty, three viewpoints) and a dog with no person
(s03_pets_only, dog at 2.5 m / 0 deg, the cat outside the raw frame).

Every frame goes through camera_model.CameraModel("himax_typical") so it looks
like the sensor, not a clean render. The person clips call
mock_streamer.bank_from_scene() directly, i.e. exactly the code path the
runbook's section 2.2 rehearsal uses, so nothing here is a second renderer.

Output: <out>/<clip>/bank_NNN.png, one folder per clip, ready for
    mock_streamer.py --frames <out>/<clip> --port 5151 --once

Run with the trainenv python. Takes the simulator lock before calling.
"""
import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image

REPO = Path(__file__).resolve().parents[3]
SIM_TOOLS = REPO / "tools" / "crazysim_macos"
sys.path.insert(0, str(SIM_TOOLS))
sys.path.insert(0, str(REPO / "tools" / "real_frames"))
import mujoco                     # noqa: E402
import camera_model as cm         # noqa: E402
import mock_streamer as ms        # noqa: E402

W, H, CAM_H = ms.WIDTH, ms.HEIGHT, 0.8
DISTS = (1.5, 2.5, 3.5)
BEARINGS = (0.0, -10.0, 10.0, -25.0, 25.0)


def render_view(scene, poses, n, preset, seed):
    """Frames from explicit camera poses. `poses` = list of (pos, xyaxes)."""
    spec = mujoco.MjSpec.from_file(str(scene))
    cam = spec.worldbody.add_camera()
    cam.name, cam.fovy = "clip_cam", 70.0
    cam.alt.type = mujoco.mjtOrientation.mjORIENTATION_XYAXES
    cam.alt.xyaxes = poses[0][1]
    model = spec.compile()
    data = mujoco.MjData(model)
    renderer = mujoco.Renderer(model, H, W)
    cid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_CAMERA, "clip_cam")
    sensor = cm.CameraModel(preset, W, H, seed=seed)
    rng = np.random.default_rng(seed + 3)
    out = []
    for k in range(n):
        pos, _ = poses[k % len(poses)]
        model.cam_pos[cid] = [pos[0], pos[1], pos[2] + float(rng.normal(0, 0.002))]
        mujoco.mj_forward(model, data)
        renderer.update_scene(data, camera="clip_cam")
        out.append(sensor.apply(renderer.render().copy(), dt=0.1))
    return out


def save(bank, folder):
    folder.mkdir(parents=True, exist_ok=True)
    for k, g in enumerate(bank):
        Image.fromarray(g, "L").save(folder / f"bank_{k:03d}.png")
    return len(bank)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--n", type=int, default=30, help="frames per clip")
    ap.add_argument("--preset", default="himax_typical")
    a = ap.parse_args()
    manifest = {"preset": a.preset, "frames_per_clip": a.n, "clips": {}}

    # --- person: the protocol's 3 x 5 table, via the mock's own renderer ---
    person_scene = ms.resolve_scene("s15_static_offset")
    for d in DISTS:
        for b in BEARINGS:
            name = f"person_d{d:g}_b{b:g}"
            bank, banner = ms.bank_from_scene(person_scene, a.n, dist=d, bearing=b,
                                              preset=a.preset, cam_height=CAM_H,
                                              seed=int(7 + 100 * d + b))
            n = save(bank, a.out / name)
            manifest["clips"][name] = {"scene": "s15_static_offset", "dist_m": d,
                                       "bearing_deg": b, "vis": 1, "n": n, "banner": banner}
            print(f"{name}: {n} frames  ({banner})", flush=True)

    # --- empty room: s02, three viewpoints (the protocol's take1..3) ---------
    empty_scene = ms.resolve_scene("s02_control_empty")
    ahead = [0, -1, 0, 0, 0, 1]                        # look along +x
    yaw = math.radians(30.0)                           # look 30 deg left, into a corner
    left30 = [-math.sin(yaw), -math.cos(yaw), 0, 0, 0, 1]
    empties = {
        "empty_take1": ([([0.0, 0.0, CAM_H], ahead)], "origin, straight down the room"),
        "empty_take2": ([([1.0, 3.0, CAM_H], ahead)], "1 m in, 3 m left, facing the far wall"),
        "empty_take3": ([([2.0, 2.0, CAM_H], left30)], "2 m in, yawed 30 deg left towards the corner"),
    }
    for k, (name, (poses, desc)) in enumerate(empties.items(), 1):
        bank = render_view(empty_scene, poses, a.n, a.preset, seed=200 + k)
        n = save(bank, a.out / name)
        manifest["clips"][name] = {"scene": "s02_control_empty", "vis": 0, "n": n,
                                   "view": desc}
        print(f"{name}: {n} frames  ({desc})", flush=True)

    # --- dog, no person: s03, dog centred at 2.5 m ---------------------------
    pet_scene = ms.resolve_scene("s03_pets_only")
    spec = mujoco.MjSpec.from_file(str(pet_scene))
    m = spec.compile()
    dog = m.body_pos[mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, "subj_dog")]
    cat = m.body_pos[mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, "subj_cat")]
    cam_pos = [float(dog[0]) - 2.5, float(dog[1]), CAM_H]
    cat_bearing = math.degrees(math.atan2(cat[1] - cam_pos[1], cat[0] - cam_pos[0]))
    bank = render_view(pet_scene, [(cam_pos, ahead)], a.n, a.preset, seed=300)
    n = save(bank, a.out / "pet_dog_d2.5_b0")
    manifest["clips"]["pet_dog_d2.5_b0"] = {
        "scene": "s03_pets_only", "vis": 0, "n": n, "dist_m": 2.5, "bearing_deg": 0.0,
        "dog_xy": [float(dog[0]), float(dog[1])], "camera_xy": cam_pos[:2],
        "cat_bearing_deg": round(cat_bearing, 1),
        "note": "cat is outside the 42.9 deg raw half-FOV, so only the dog is in frame"}
    print(f"pet_dog_d2.5_b0: {n} frames  (dog at {dog[:2]}, cat at {cat_bearing:+.1f} deg: out of frame)",
          flush=True)

    (a.out / "render_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"wrote {a.out / 'render_manifest.json'}")


if __name__ == "__main__":
    main()
