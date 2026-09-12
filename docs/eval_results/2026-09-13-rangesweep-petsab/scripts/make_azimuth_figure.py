#!/usr/bin/env python3
"""Render the EXPERIMENT 1 azimuth figure: the same person, the same range,
three viewing azimuths, with the model's own confidence written underneath.

This is what the flat subject card does when the drone works its way round it,
and it is why closing range in s07_occlusion_reappear costs detections.

Usage: make_azimuth_figure.py SCENE_DIR OUT.png [--range 2.25]
"""
import json, math, sys
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw

TOOLS = Path("/Users/saimaruvada/Downloads/drone/pytorch_ssd/tools/crazysim_macos")
DRONE = Path("/Users/saimaruvada/Downloads/drone")
sys.path.insert(0, str(TOOLS))
import perception_backends as pb
import mujoco

REC601 = [0.2989, 0.5870, 0.1140]
W, H, FOVY = 324, 244, 70.0

scene_dir = Path(sys.argv[1]); dest = Path(sys.argv[2])
rng = float(sys.argv[4]) if len(sys.argv) > 4 else 2.25
man = json.loads((scene_dir / "manifest.json").read_text())
sx, sy = [float(v) for v in man["subjects"][0]["motion"]["p0"]]

spec = mujoco.MjSpec.from_file(str(scene_dir / "scene.xml"))
cam = spec.worldbody.add_camera(); cam.name, cam.fovy = "fig_cam", FOVY
cam.alt.type = mujoco.mjtOrientation.mjORIENTATION_XYAXES
cam.alt.xyaxes = [0, -1, 0, 0, 0, 1]
m = spec.compile(); d = mujoco.MjData(m)
r = mujoco.Renderer(m, H, W)
cid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_CAMERA, "fig_cam")
perc = pb.FloatPerception(DRONE / "pytorch_ssd_unstable",
                          DRONE / "pytorch_ssd_unstable/artifacts/successor_qat_ep3_eval.pth")

# One tile is one sample and a single sample can be lucky, so each azimuth is
# scored at all three of the sweep's camera heights and the tile is labelled with
# the MEAN over them.  The displayed frame is the h = 0.80 m one.
tiles = []
for az in (0.0, 35.0, 45.0):
    a = math.radians(az)
    fwd = np.array([math.cos(a), -math.sin(a), 0.0])
    right = np.array([-math.sin(a), -math.cos(a), 0.0])
    R = np.column_stack([right, [0, 0, 1.0], -fwd])
    q = np.empty(4); mujoco.mju_mat2Quat(q, R.flatten())
    confs, shown, bucket = [], None, None
    for h in (0.80, 0.82, 0.84):
        m.cam_pos[cid] = [sx - rng * math.cos(a), sy + rng * math.sin(a), h]
        m.cam_quat[cid] = q
        mujoco.mj_forward(m, d); r.update_scene(d, camera="fig_cam")
        gray = np.dot(r.render()[..., :3], REC601).astype(np.uint8)
        res = perc(gray)
        confs.append(float(res["visibility_confidence"]))
        if shown is None:
            shown, bucket = gray, int(res["size_bucket_index"])
    tiles.append((az, shown, sum(confs) / len(confs), bucket, confs))
perc.close()

sheet = Image.new("RGB", (W * 3, H + 34), (0, 0, 0))
dr = ImageDraw.Draw(sheet)
dr.text((4, 3), f"same person, same {rng:.2f} m range, camera swung around the subject card "
                f"- float model, clean camera, matte floor; conf = mean of 3 camera heights",
        fill=(255, 255, 255))
for i, (az, gray, c, b, cs) in enumerate(tiles):
    sheet.paste(Image.fromarray(gray).convert("RGB"), (i * W, 16))
    dr.text((i * W + 4, H + 19),
            f"azimuth {az:.0f} deg  conf {c:.3f} ({'/'.join('%.2f' % x for x in cs)})  "
            f"bucket {b}  {'LATCHES' if c >= 0.70 else 'BELOW 0.70'}", fill=(255, 255, 255))
sheet.save(dest)
print(f"wrote {dest}: " + "  ".join(f"{az:.0f}d mean conf {c:.3f}" for az, _, c, _, _ in tiles))
