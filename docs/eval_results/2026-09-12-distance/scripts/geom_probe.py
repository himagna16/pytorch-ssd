"""Measure what the simulator ACTUALLY renders vs what scoreboard.py's geometry says.

For a range of true horizontal distances, place the camera at the drone eye line
(z=0.8) pointed straight at the subject panel (bearing 0, i.e. the closed-loop
settled case), render 324x244, and use MuJoCo segmentation rendering to get the
exact pixel rows the subject panel occupies.

Compare:
  measured  = panel_pixel_height / 244
  geometry  = H / (2 * d * tan(fovy/2))      <- scoreboard.py's formula
Then run the float follow model on the very same frame.
"""
import math, sys, json, argparse
from pathlib import Path
import numpy as np
import mujoco
from PIL import Image

SIMDIR = Path("/Users/saimaruvada/Downloads/drone/pytorch_ssd/tools/crazysim_macos")
UNSTABLE = Path("/Users/saimaruvada/Downloads/drone/pytorch_ssd_unstable")
CKPT = UNSTABLE / "artifacts/successor_qat_ep3_eval.pth"
FRAME_W, FRAME_H, FOVY = 324, 244, 70.0
TAN_HALF = math.tan(math.radians(FOVY / 2))
EYE_Z = 0.8

ap = argparse.ArgumentParser()
ap.add_argument("--scene", default="s15_static_offset")
ap.add_argument("--subject", default="subj_person_target")
ap.add_argument("--dists", default="1.6,1.8,1.94,2.1,2.3,2.43,2.6,2.7,2.9,3.0,3.2,3.4,3.64,4.0")
ap.add_argument("--bearing-deg", type=float, default=0.0, help="place camera so subject sits at this bearing")
ap.add_argument("--no-model", action="store_true")
ap.add_argument("--save-frames", default="")
a = ap.parse_args()

out = SIMDIR / "scenes_v2" / a.scene
manifest = json.loads((out / "manifest.json").read_text())
sub = [s for s in manifest["subjects"] if s["name"] == a.subject][0]
H = float(sub["panel"]["height_m"])
zc = float(sub["panel"]["z_center_m"])

spec = mujoco.MjSpec.from_file(str(out / "scene.xml"))
cam = spec.worldbody.add_camera()
cam.name, cam.fovy = "probe_cam", FOVY
cam.pos = [0.0, 0.0, EYE_Z]
cam.alt.type = mujoco.mjtOrientation.mjORIENTATION_XYAXES
cam.alt.xyaxes = [0, -1, 0, 0, 0, 1]
m = spec.compile()
d = mujoco.MjData(m)
mujoco.mj_forward(m, d)
cid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_CAMERA, "probe_cam")
bid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, a.subject)
gid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_GEOM, f"{a.subject}_panel")
sx, sy = float(d.xpos[bid][0]), float(d.xpos[bid][1])

rgb_r = mujoco.Renderer(m, FRAME_H, FRAME_W)
seg_r = mujoco.Renderer(m, FRAME_H, FRAME_W)
seg_r.enable_segmentation_rendering()

model = head = None
if not a.no_model:
    import torch
    sys.path.insert(0, str(UNSTABLE))
    from models.follow_model_factory import build_follow_model_from_checkpoint
    from utils.follow_task import decode_follow_outputs
    head = torch.load(CKPT, map_location="cpu").get("follow_head_type")
    model = build_follow_model_from_checkpoint(CKPT, torch.device("cpu")).eval()

def run_model(gray):
    import torch
    s = min(gray.shape)
    y0, x0 = (gray.shape[0] - s) // 2, (gray.shape[1] - s) // 2
    crop = Image.fromarray(gray[y0:y0 + s, x0:x0 + s]).resize((128, 128), Image.BILINEAR)
    x = torch.from_numpy(np.asarray(crop, np.float32) / 255.0)[None, None]
    with torch.no_grad():
        dec = decode_follow_outputs(model(x), head)
    return {k: float(t.reshape(-1)[0]) for k, t in dec.items() if torch.is_tensor(t)}

print(f"scene {a.scene}  subject at ({sx:.3f},{sy:.3f})  panel H={H} z_center={zc}")
print(f"camera eye z={EYE_Z}  fovy={FOVY}  frame {FRAME_W}x{FRAME_H}  bearing={a.bearing_deg} deg")
print()
hdr = ("  d_true  cam_xy               px_top px_bot  px_h  meas_size  geom_size  meas/geom"
       "   crop_h  crop_size  | model_size bkt conf")
print(hdr); print("-" * len(hdr))
rows = []
for dist in [float(v) for v in a.dists.split(",")]:
    # place camera at horizontal distance `dist` from subject, with subject at
    # bearing `a.bearing_deg` in the camera frame. Camera looks along +x.
    b = math.radians(a.bearing_deg)
    cx = sx - dist * math.cos(b)
    cy = sy - dist * math.sin(b)
    m.cam_pos[cid] = [cx, cy, EYE_Z]
    mujoco.mj_forward(m, d)
    rgb_r.update_scene(d, camera="probe_cam")
    rgb = rgb_r.render()
    seg_r.update_scene(d, camera="probe_cam")
    seg = seg_r.render()   # (H,W,2): [...,0]=objtype, [...,1]=objid
    mask = (seg[..., 0] == mujoco.mjtObj.mjOBJ_GEOM) & (seg[..., 1] == gid)
    if not mask.any():
        print(f"  {dist:6.2f}  panel not visible"); continue
    rr = np.where(mask.any(axis=1))[0]
    cc = np.where(mask.any(axis=0))[0]
    px_top, px_bot = int(rr[0]), int(rr[-1])
    px_h = px_bot - px_top + 1
    meas = px_h / FRAME_H
    geom = H / (2.0 * dist * TAN_HALF)
    # what the model's 244x244 centre crop sees (same rows; crop is horizontal only)
    cs = min(FRAME_W, FRAME_H)
    x0c = (FRAME_W - cs) // 2
    mc = mask[:, x0c:x0c + cs]
    crop_h = 0
    if mc.any():
        r2 = np.where(mc.any(axis=1))[0]
        crop_h = int(r2[-1] - r2[0] + 1)
    crop_size = crop_h / cs
    gray = np.dot(rgb[..., :3], [0.2989, 0.5870, 0.1140]).astype(np.uint8)
    mtxt = ""
    mv = None
    if model is not None:
        v = run_model(gray)
        mv = v
        mtxt = f"| {v['size_value']:9.3f} {int(v['size_bucket_index'])}  {v['visibility_confidence']:.3f}"
    print(f"  {dist:6.2f}  ({cx:+.2f},{cy:+.2f})  {px_top:6d} {px_bot:6d} {px_h:5d}"
          f"  {meas:9.4f}  {geom:9.4f}  {meas/geom:9.4f}   {crop_h:6d} {crop_size:10.4f}  {mtxt}")
    rows.append(dict(d=dist, px_h=px_h, meas=meas, geom=geom, ratio=meas/geom,
                     crop_size=crop_size,
                     model_size=None if mv is None else mv['size_value'],
                     bucket=None if mv is None else int(mv['size_bucket_index']),
                     conf=None if mv is None else mv['visibility_confidence']))
    if a.save_frames:
        Image.fromarray(gray).save(Path(a.save_frames) / f"d{dist:.2f}.png")

print()
r = np.array([x["ratio"] for x in rows])
print(f"rendered/geometry ratio: mean {r.mean():.4f}  min {r.min():.4f}  max {r.max():.4f}")
Path(a.save_frames or ".").mkdir(exist_ok=True, parents=True)
