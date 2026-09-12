"""Open-loop distance sweep: what does the size head say at a KNOWN distance?

No follower, no closed loop. Camera on the drone's eye line, pointed straight at
the subject, stepped through true horizontal distances. At each step:
  - measure the subject panel's true pixel height by MuJoCo segmentation
  - run the float model on the clean frame
  - run the float model on the same frame through the himax_typical sensor model
  - stash the firmware-preprocessed 128x128 input for the chip network (run later
    in nemoenv, which is the only env with onnxruntime)
"""
import argparse, json, math, sys
from pathlib import Path
import numpy as np
import mujoco
from PIL import Image

SIMDIR = Path("/Users/saimaruvada/Downloads/drone/pytorch_ssd/tools/crazysim_macos")
UNSTABLE = Path("/Users/saimaruvada/Downloads/drone/pytorch_ssd_unstable")
sys.path.insert(0, str(SIMDIR))
import camera_model as cm                                                  # noqa: E402
from perception_backends import firmware_preprocess                        # noqa: E402

FRAME_W, FRAME_H, FOVY, EYE_Z = 324, 244, 70.0, 0.8
TAN = math.tan(math.radians(FOVY / 2))

ap = argparse.ArgumentParser()
ap.add_argument("--scene", default="s15_static_offset")
ap.add_argument("--subject", default="subj_person_target")
ap.add_argument("--ckpt", default=str(UNSTABLE / "artifacts/successor_qat_ep3_eval.pth"))
ap.add_argument("--d0", type=float, default=1.60)
ap.add_argument("--d1", type=float, default=4.60)
ap.add_argument("--step", type=float, default=0.05)
ap.add_argument("--seeds", type=int, default=5, help="himax sensor seeds per distance")
ap.add_argument("--out", required=True)
a = ap.parse_args()

out = SIMDIR / "scenes_v2" / a.scene
manifest = json.loads((out / "manifest.json").read_text())
sub = [s for s in manifest["subjects"] if s["name"] == a.subject][0]
H = float(sub["panel"]["height_m"])

spec = mujoco.MjSpec.from_file(str(out / "scene.xml"))
c = spec.worldbody.add_camera()
c.name, c.fovy = "sweep_cam", FOVY
c.pos = [0.0, 0.0, EYE_Z]
c.alt.type = mujoco.mjtOrientation.mjORIENTATION_XYAXES
c.alt.xyaxes = [0, -1, 0, 0, 0, 1]
m = spec.compile()
d = mujoco.MjData(m)
mujoco.mj_forward(m, d)
cid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_CAMERA, "sweep_cam")
bid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, a.subject)
gid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_GEOM, f"{a.subject}_panel")
sx, sy = float(d.xpos[bid][0]), float(d.xpos[bid][1])

rgb_r = mujoco.Renderer(m, FRAME_H, FRAME_W)
seg_r = mujoco.Renderer(m, FRAME_H, FRAME_W); seg_r.enable_segmentation_rendering()

import torch                                                              # noqa: E402
sys.path.insert(0, str(UNSTABLE))
from models.follow_model_factory import build_follow_model_from_checkpoint  # noqa: E402
from utils.follow_task import decode_follow_outputs                         # noqa: E402
head = torch.load(a.ckpt, map_location="cpu").get("follow_head_type")
model = build_follow_model_from_checkpoint(Path(a.ckpt), torch.device("cpu")).eval()

def float_model(gray):
    s = min(gray.shape)
    y0, x0 = (gray.shape[0] - s) // 2, (gray.shape[1] - s) // 2
    crop = Image.fromarray(gray[y0:y0 + s, x0:x0 + s]).resize((128, 128), Image.BILINEAR)
    x = torch.from_numpy(np.asarray(crop, np.float32) / 255.0)[None, None]
    with torch.no_grad():
        dec = decode_follow_outputs(model(x), head)
    return int(dec["size_bucket_index"]), float(dec["visibility_confidence"])

dists = np.arange(a.d0, a.d1 + 1e-9, a.step)
rows = []
chip_inputs, chip_meta = [], []
cams = {s: cm.CameraModel("himax_typical", FRAME_W, FRAME_H, seed=1234 + s) for s in range(a.seeds)}
for dist in dists:
    m.cam_pos[cid] = [sx - dist, sy, EYE_Z]
    mujoco.mj_forward(m, d)
    rgb_r.update_scene(d, camera="sweep_cam"); rgb = rgb_r.render()
    seg_r.update_scene(d, camera="sweep_cam"); seg = seg_r.render()
    mask = (seg[..., 0] == mujoco.mjtObj.mjOBJ_GEOM) & (seg[..., 1] == gid)
    rr = np.where(mask.any(axis=1))[0]
    px_h = int(rr[-1] - rr[0] + 1) if rr.size else 0
    meas = px_h / FRAME_H
    geom = H / (2.0 * dist * TAN)
    gray = np.dot(rgb[..., :3], [0.2989, 0.5870, 0.1140]).astype(np.uint8)
    b_clean, conf_clean = float_model(gray)
    chip_inputs.append(firmware_preprocess(gray)); chip_meta.append((dist, "clean", -1))
    hb, hc = [], []
    for s, camm in cams.items():
        g2 = camm.apply(rgb, omega=np.zeros(3), dt=0.153)
        bb, cc = float_model(g2)
        hb.append(bb); hc.append(cc)
        chip_inputs.append(firmware_preprocess(g2)); chip_meta.append((dist, "himax", s))
    rows.append(dict(d=float(dist), px_h=px_h, meas=meas, geom=geom, ratio=meas / geom,
                     b_clean=b_clean, conf_clean=conf_clean,
                     b_himax=hb, conf_himax=float(np.mean(hc))))

np.savez_compressed(a.out, inputs=np.stack(chip_inputs),
                    meta=np.array([(f"{x[0]:.4f}", x[1], str(x[2])) for x in chip_meta]))
Path(a.out).with_suffix(".json").write_text(json.dumps(rows, indent=1))

print(f"scene {a.scene}  H={H}  render/geometry ratio: "
      f"mean {np.mean([r['ratio'] for r in rows]):.4f} "
      f"min {min(r['ratio'] for r in rows):.4f} max {max(r['ratio'] for r in rows):.4f}")
print()
print("  d_true  true_size  | float+clean bkt | float+himax P(bkt>=2)  buckets")
for r in rows:
    hb = r["b_himax"]
    print(f"  {r['d']:6.2f}  {r['meas']:9.4f}  |     {r['b_clean']}           | "
          f"  {np.mean(np.array(hb) >= 2):.2f}   {hb}")

def flip(getter):
    """largest distance at which the bucket is still >=2 with prob >= 0.5 (scanning outwards)"""
    last = None
    for r in rows:
        if getter(r) >= 0.5:
            last = r["d"]
    return last

print()
print(f"true 1->2 edge (size 0.500)                : {H/(2*0.5*TAN):.3f} m")
print(f"float+clean : last distance calling bkt>=2 : {flip(lambda r: 1.0 if r['b_clean']>=2 else 0.0)}")
print(f"float+himax : last distance calling bkt>=2 : {flip(lambda r: float(np.mean(np.array(r['b_himax'])>=2)))}")
