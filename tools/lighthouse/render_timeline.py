#!/usr/bin/env python3
"""REHEARSAL ONLY: render what the follower's camera would see of the scripted subject,
as a time line that tools/real_frames/mock_streamer.py --timeline serves by wall clock.

    ~/Downloads/drone/trainenv/bin/python tools/lighthouse/render_timeline.py \
        --seconds 40 --dist 2.5 --out /tmp/timeline.npz

The subject follows session_common.scripted_lateral (still, sidestep, walk, still,
sidestep, still - exactly what the spoken cues ask for), at `--dist` metres in front of
a level camera 0.8 m up, rendered from a simulator person scene through the Himax
sensor model (the same render path as mock_streamer's scene banks). The follower is
taken to sit at the room origin facing +x, so the subject is at room (dist, y).

Output .npz: frames (M, h, w) uint8 - one per distinct sideways position (5 mm
steps); t (N,) content times in seconds on the recording clock; idx (N,) which frame
shows the subject at t; y (M,) the sideways position of each frame (+ = LEFT); plus
info (a JSON string). Nothing here is evidence about real hardware.
"""
import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
DRONE_ROOT = REPO.parent
sys.path.insert(0, str(HERE))
import session_common as S  # noqa: E402

SIM_TOOLS = REPO / "tools" / "crazysim_macos"
SCENE_DIRS = [SIM_TOOLS / "scenes_v2", DRONE_ROOT / "pytorch_ssd" / "tools" / "crazysim_macos" / "scenes_v2"]
CAM_H = 0.8
REAL_STREAM = (162, 122)   # what the AI-deck actually sent on 2026-09-22 (EXPERIMENTS.md)


def resolve_scene(name):
    p = Path(name).expanduser()
    if p.is_file():
        return p
    for d in SCENE_DIRS:
        if (d / name / "scene.xml").is_file():
            return d / name / "scene.xml"
    sys.exit(f"no scene {name!r} in {', '.join(map(str, SCENE_DIRS))} (they are generated, not in git)")


class Renderer:
    """A level camera, fovy 70, looking along +x at the scene's person from `dist` metres,
    shifted sideways so the person appears at the scripted offset."""

    def __init__(self, scene, preset="himax_typical", size=REAL_STREAM, seed=7):
        w, h = size
        sys.path.insert(0, str(SIM_TOOLS))
        import mujoco
        import camera_model as cm
        self.mj = mujoco
        spec = mujoco.MjSpec.from_file(str(scene))
        cam = spec.worldbody.add_camera()
        cam.name, cam.fovy = "lh_cam", 70.0
        cam.alt.type = mujoco.mjtOrientation.mjORIENTATION_XYAXES
        cam.alt.xyaxes = [0, -1, 0, 0, 0, 1]          # look along +x, image right = world -y
        self.model = spec.compile()
        self.data = mujoco.MjData(self.model)
        self.r = mujoco.Renderer(self.model, h, w)
        self.cid = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_CAMERA, "lh_cam")
        self.target = None
        for i in range(self.model.nbody):
            nm = mujoco.mj_id2name(self.model, mujoco.mjtObj.mjOBJ_BODY, i) or ""
            if "person" in nm or nm == "subj_target":
                self.target = self.model.body_pos[i].copy()
                break
        if self.target is None:
            sys.exit(f"{scene}: no body named *person* or subj_target")
        self.sensor = cm.CameraModel(preset, w, h, seed=seed)

    def render(self, y_left, dist):
        # subject y_left to the camera's LEFT  <=>  camera y_left to the subject's RIGHT (-y)
        self.model.cam_pos[self.cid] = [self.target[0] - dist, self.target[1] - y_left, CAM_H]
        self.mj.mj_forward(self.model, self.data)
        self.r.update_scene(self.data, camera="lh_cam")
        return self.sensor.apply(self.r.render().copy(), dt=0.1)


def build(seconds, dist, scene, hz=100.0, y_res=0.005, lead=60.0, preset="himax_typical", size=REAL_STREAM):
    t = np.arange(-lead, seconds + 5.0, 1.0 / hz)
    y = np.array([S.scripted_lateral(float(v), seconds) for v in t])
    q = np.round(y / y_res).astype(np.int64)
    keys, idx = np.unique(q, return_inverse=True)
    rend = Renderer(scene, preset=preset, size=size)
    frames = np.stack([rend.render(float(k * y_res), dist) for k in keys]).astype(np.uint8)
    info = dict(seconds=seconds, dist=dist, scene=str(scene), preset=preset, hz=hz, y_res=y_res, size=list(size),
                cam_height=CAM_H, crop_hfov_deg=70.0,
                note="REHEARSAL: scripted subject rendered in the simulator; not hardware evidence")
    return dict(t=t, idx=idx.astype(np.int32), frames=frames, y=keys * y_res, info=json.dumps(info))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seconds", type=float, required=True, help="the session length record_session will use")
    ap.add_argument("--dist", type=float, default=2.5, help="subject distance ahead of the camera, m")
    ap.add_argument("--scene", default="s15_static_offset")
    ap.add_argument("--preset", default="himax_typical")
    ap.add_argument("--size", default="162x122", help="WxH; default the real AI-deck stream (162x122)")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    w, h = (int(v) for v in a.size.lower().split("x"))
    d = build(a.seconds, a.dist, resolve_scene(a.scene), preset=a.preset, size=(w, h))
    np.savez_compressed(a.out, **d)
    print(f"wrote {a.out}: {len(d['frames'])} distinct frames, {len(d['t'])} timeline samples, "
          f"y {d['y'].min():+.2f}..{d['y'].max():+.2f} m at {a.dist} m; mean brightness "
          f"{d['frames'].mean():.1f}")


if __name__ == "__main__":
    main()
