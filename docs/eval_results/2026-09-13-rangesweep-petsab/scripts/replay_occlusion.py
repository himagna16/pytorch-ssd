#!/usr/bin/env python3
"""EXPERIMENT 1, control arm: re-render the D.occlusion__proven flight statically,
with and without the partition, and see which one reproduces the lost track.

The range sweep says the detector does NOT fall off at close range on an
unoccluded person.  So something else in `s07_occlusion_reappear` produces the
92.5 -> 73.6 -> 54.0% collapse the matte baseline measured.  The obvious
remaining candidate is the partition ITSELF: at px ~ 2.0 m the drone is 0.2 m
short of a 0.1 x 0.9 x 2.2 m box that fills a large part of the frame, even
though the sight line to the target clears its edge.

This replays the flight's own geometry with no flight:

  * drone pose (px, py, pz) and yaw are read frame by frame out of the committed
    `follow_log.csv`;
  * the subject's swaying y is read out of the committed `truth.csv` and pushed
    into the scene's slide joint, so the subject stands exactly where it stood;
  * each pose is rendered TWICE - once in the repo's own
    `scenes_v2/s07_occlusion_reappear`, once in a partition-free twin built by
    the same builder from the same definition minus `occluders` (verified: the
    subject PNG is byte-identical, the body pos and the sway joint are
    identical, and the scene.xml diff is the one missing geom);
  * the float/clean perception path - exactly what `__proven` flies - is run on
    both.

Nothing flies.  No simulator, no firmware, no control loop.

Self-check: the replay's decoded `x_value` is compared against the `x` the
follower logged at that frame.  If the two agree the replayed viewpoint is the
flown viewpoint, and the confidence comparison means something.

Usage: replay_occlusion.py RUN_DIR... --scene-with DIR --scene-without DIR --out DIR
"""
import argparse
import bisect
import csv
import json
import math
import sys
from pathlib import Path

import numpy as np

TOOLS = Path("/Users/saimaruvada/Downloads/drone/pytorch_ssd/tools/crazysim_macos")
DRONE_ROOT = Path("/Users/saimaruvada/Downloads/drone")
sys.path.insert(0, str(TOOLS))
import perception_backends as pb                # noqa: E402

REC601 = [0.2989, 0.5870, 0.1140]
FRAME_W, FRAME_H = 324, 244
FOVY_DEG = 70.0
CKPT = DRONE_ROOT / "pytorch_ssd_unstable/artifacts/successor_qat_ep3_eval.pth"
UNSTABLE = DRONE_ROOT / "pytorch_ssd_unstable"
# s07 geometry, read out of the scene: box centred (2.2, -0.95), half-extents
# (0.05, 0.45).  The sight line from (px, 0) to the target clears the near edge
# once px > 1.609 m (the matte baseline's occlusion_geometry.py).
PART_X, PART_Y0, PART_Y1 = 2.2, -1.40, -0.50


class Scene:
    def __init__(self, scene_dir: Path):
        import mujoco
        self.mj = mujoco
        spec = mujoco.MjSpec.from_file(str(scene_dir / "scene.xml"))
        cam = spec.worldbody.add_camera()
        cam.name, cam.fovy = "replay_cam", FOVY_DEG
        cam.alt.type = mujoco.mjtOrientation.mjORIENTATION_XYAXES
        cam.alt.xyaxes = [0, -1, 0, 0, 0, 1]
        self.model = spec.compile()
        self.data = mujoco.MjData(self.model)
        self.renderer = mujoco.Renderer(self.model, FRAME_H, FRAME_W)
        self.cid = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_CAMERA, "replay_cam")
        self.bid = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_BODY,
                                     "subj_person_target")
        self.body_y = float(self.model.body_pos[self.bid][1])
        jid = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_JOINT,
                                "sway_subj_person_target")
        self.qadr = int(self.model.jnt_qposadr[jid])

    def render(self, px, py, pz, yaw_deg, subj_y, pitch_deg=0.0, roll_deg=0.0,
               pitch_sign=1.0):
        """Camera is rigidly attached to the body: it looks along body +x, with
        image-right = body -y and image-up = body +z.  Body attitude is the
        usual ZYX (yaw, pitch, roll).  `pitch_sign` selects the firmware's sign
        convention for stabilizer.pitch; it is calibrated empirically against
        the flown log, not assumed (see the README)."""
        mujoco = self.mj
        self.data.qpos[self.qadr] = subj_y - self.body_y
        y, p_, r_ = (math.radians(yaw_deg), math.radians(pitch_deg) * pitch_sign,
                     math.radians(roll_deg))
        cz, sz = math.cos(y), math.sin(y)
        cy, sy_ = math.cos(p_), math.sin(p_)
        cx, sx = math.cos(r_), math.sin(r_)
        Rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1.0]])
        Ry = np.array([[cy, 0, sy_], [0, 1.0, 0], [-sy_, 0, cy]])
        Rx = np.array([[1.0, 0, 0], [0, cx, -sx], [0, sx, cx]])
        Rb = Rz @ Ry @ Rx
        right = Rb @ np.array([0.0, -1.0, 0.0])
        up = Rb @ np.array([0.0, 0.0, 1.0])
        zax = -(Rb @ np.array([1.0, 0.0, 0.0]))
        yax = up
        R = np.column_stack([right, yax, zax])
        q = np.empty(4)
        mujoco.mju_mat2Quat(q, R.flatten())
        self.model.cam_quat[self.cid] = q
        self.model.cam_pos[self.cid] = [px, py, pz]
        mujoco.mj_forward(self.model, self.data)
        self.renderer.update_scene(self.data, camera="replay_cam")
        rgb = self.renderer.render()
        return np.dot(rgb[..., :3], REC601).astype(np.uint8)


def load_truth(path: Path):
    ts, ys = [], []
    for line in path.read_text().splitlines():
        if line.startswith("#") or not line.strip():
            continue
        f = line.split(",")
        ts.append(float(f[0]))
        ys.append(float(f[3]))
    return ts, ys


def truth_y_at(ts, ys, wall):
    i = bisect.bisect_left(ts, wall)
    if i <= 0:
        return ys[0]
    if i >= len(ts):
        return ys[-1]
    t0, t1 = ts[i - 1], ts[i]
    w = 0.0 if t1 == t0 else (wall - t0) / (t1 - t0)
    return ys[i - 1] + w * (ys[i] - ys[i - 1])


def sightline_clear(px, py, ty, tx=3.5):
    """True if the segment drone->target misses the partition span at x=PART_X."""
    if px >= PART_X or tx <= PART_X:
        return True
    w = (PART_X - px) / (tx - px)
    y = py + w * (ty - py)
    return not (PART_Y0 <= y <= PART_Y1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", type=Path, nargs="+")
    ap.add_argument("--scene-with", type=Path, required=True)
    ap.add_argument("--scene-without", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--stride", type=int, default=1)
    ap.add_argument("--pitch-sign", type=float, default=1.0,
                    help="sign convention for stabilizer.pitch (calibrated, see README)")
    ap.add_argument("--no-attitude", action="store_true",
                    help="replay with yaw only, ignoring pitch and roll")
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)

    scenes = {"with_partition": Scene(a.scene_with),
              "no_partition": Scene(a.scene_without)}
    perc = pb.FloatPerception(UNSTABLE, CKPT)     # __proven flies float + clean
    print(f"[replay] float backend ready; scenes: {list(scenes)}")

    cols = ["run", "t", "px", "py", "pz", "yaw_deg", "subj_y", "range_m",
            "pitch_deg", "roll_deg", "flown_conf", "flown_x", "flown_tracking", "flown_size_bucket",
            "variant", "conf", "x_value", "size_bucket", "sightline_clear"]
    rows = []
    for run in a.runs:
        ts, ys = load_truth(run / "truth.csv")
        log = [r for r in csv.DictReader(open(run / "follow_log.csv")) if r["event"] == ""]
        log = log[::a.stride]
        for r in log:
            try:
                px, py, pz = float(r["px"]), float(r["py"]), float(r["pz"])
                yaw = float(r["yaw"])
                pitch = 0.0 if a.no_attitude else float(r["pitch"])
                roll = 0.0 if a.no_attitude else float(r["roll"])
                wall = float(r["wall"])
            except (ValueError, KeyError):
                continue
            sy = truth_y_at(ts, ys, wall)
            rng = math.hypot(3.5 - px, sy - py)
            clear = int(sightline_clear(px, py, sy))
            for vname, sc in scenes.items():
                gray = sc.render(px, py, pz, yaw, sy, pitch, roll, a.pitch_sign)
                p = perc(gray)
                rows.append([run.name, round(float(r["t"]), 3), round(px, 4), round(py, 4),
                             round(pz, 4), round(yaw, 3), round(sy, 4), round(rng, 4),
                             round(pitch, 3), round(roll, 3),
                             round(float(r["conf"]), 6), round(float(r["x"]), 6),
                             int(r["tracking"]), int(r["size_bucket"]), vname,
                             round(float(p["visibility_confidence"]), 6),
                             round(float(p["x_value"]), 6), int(p["size_bucket_index"]),
                             clear])
        print(f"[replay] {run.name}: {len(log)} frames x {len(scenes)} variants")

    perc.close()
    with open(a.out / "replay.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        w.writerows(rows)
    (a.out / "replay_meta.json").write_text(json.dumps(
        {"runs": [str(r) for r in a.runs], "scene_with": str(a.scene_with),
         "scene_without": str(a.scene_without), "stride": a.stride,
         "backend": "float", "camera": "clean", "n_rows": len(rows),
         "pitch_sign": a.pitch_sign, "no_attitude": bool(a.no_attitude)}, indent=2))
    print(f"[replay] wrote {len(rows)} rows to {a.out}/replay.csv")


if __name__ == "__main__":
    main()
