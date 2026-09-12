"""Render-in-the-loop replay of the follower's forward channel.

Not a flight: no physics, no cflib, no yaw error - the drone is assumed to point
straight at the subject and to track commanded velocity instantly. Everything
else is the real thing: the real scene, the real renderer, the real camera model,
the real network, and follow_person.py's actual law

    vx = clip(k_fwd * (target_size - size_value), v_max)

stepped at the real control rate. Its job is to predict where the loop parks, so
the effect of a change can be estimated without re-flying the acceptance suite.
"""
import argparse, math, sys, json
from pathlib import Path
import numpy as np, mujoco
from PIL import Image

SIMDIR = Path("/Users/saimaruvada/Downloads/drone/pytorch_ssd/tools/crazysim_macos")
UNSTABLE = Path("/Users/saimaruvada/Downloads/drone/pytorch_ssd_unstable")
sys.path.insert(0, str(SIMDIR)); sys.path.insert(0, str(UNSTABLE))
import camera_model as cm
from perception_backends import firmware_preprocess

FRAME_W, FRAME_H, FOVY, EYE_Z = 324, 244, 70.0, 0.8
TAN = math.tan(math.radians(35.0))
K_FWD, TARGET, V_MAX = 0.8, 0.625, 0.3
CENTRES = np.array([0.125, 0.375, 0.625, 0.875])

ap = argparse.ArgumentParser()
ap.add_argument("--scene", default="s15_static_offset")
ap.add_argument("--d-start", type=float, default=3.64)
ap.add_argument("--seconds", type=float, default=30.0)
ap.add_argument("--seeds", type=int, default=5)
ap.add_argument("--onnx", default=str(UNSTABLE / "logs/plain_follow_prod_qat_v3/quant_eval/model_id_dory.onnx"))
a = ap.parse_args()

out = SIMDIR / "scenes_v2" / a.scene
man = json.loads((out / "manifest.json").read_text())
sub = [s for s in man["subjects"] if s["role"] == "person_target"][0]
NAME, H = sub["name"], float(sub["panel"]["height_m"])

spec = mujoco.MjSpec.from_file(str(out / "scene.xml"))
c = spec.worldbody.add_camera(); c.name, c.fovy = "cam", FOVY
c.pos=[0,0,EYE_Z]; c.alt.type=mujoco.mjtOrientation.mjORIENTATION_XYAXES; c.alt.xyaxes=[0,-1,0,0,0,1]
m = spec.compile(); d = mujoco.MjData(m); mujoco.mj_forward(m, d)
cid=mujoco.mj_name2id(m,mujoco.mjtObj.mjOBJ_CAMERA,"cam")
bid=mujoco.mj_name2id(m,mujoco.mjtObj.mjOBJ_BODY,NAME)
mid=mujoco.mj_name2id(m,mujoco.mjtObj.mjOBJ_MATERIAL,"groundplane")
sx,sy=float(d.xpos[bid][0]),float(d.xpos[bid][1])
r = mujoco.Renderer(m, FRAME_H, FRAME_W)

import torch
from models.follow_model_factory import build_follow_model_from_checkpoint
CKPT = UNSTABLE / "artifacts/successor_qat_ep3_eval.pth"
head = torch.load(CKPT, map_location="cpu").get("follow_head_type")
fmodel = build_follow_model_from_checkpoint(CKPT, torch.device("cpu")).eval()

def float_logits(gray):
    s=min(gray.shape); y0,x0=(gray.shape[0]-s)//2,(gray.shape[1]-s)//2
    crop=Image.fromarray(gray[y0:y0+s,x0:x0+s]).resize((128,128),Image.BILINEAR)
    x=torch.from_numpy(np.asarray(crop,np.float32)/255.0)[None,None]
    with torch.no_grad(): return fmodel(x).reshape(-1).numpy()

def decode(l, soft):
    sl = l[10:14]
    if not soft:
        return float(CENTRES[int(np.argmax(sl))])
    e = np.exp(sl - sl.max()); p = e / e.sum()
    return float((p * CENTRES).sum())

def run(refl, preset, rate, soft, seed):
    m.mat_reflectance[mid] = refl
    cmod = None if preset == "clean" else cm.CameraModel(preset, FRAME_W, FRAME_H, seed=seed)
    dt = 1.0 / rate
    dist = a.d_start
    traj = []
    for k in range(int(a.seconds * rate)):
        dist = float(np.clip(dist, 0.4, 6.5))
        m.cam_pos[cid] = [sx - dist, sy, EYE_Z]; mujoco.mj_forward(m, d)
        r.update_scene(d, camera="cam"); rgb = r.render()
        gray = (np.dot(rgb[...,:3],[0.2989,0.5870,0.1140]).astype(np.uint8) if cmod is None
                else cmod.apply(rgb, omega=np.zeros(3), dt=dt))
        sv = decode(float_logits(gray), soft)
        vx = float(np.clip(K_FWD * (TARGET - sv), -V_MAX, V_MAX))
        traj.append((dist, sv, vx))
        dist -= vx * dt
    return traj

CASES = [
    ("A  as-shipped        mirror on  clean  argmax", 0.2, "clean", 14.0, False),
    ("B  as-shipped        mirror on  himax  argmax", 0.2, "himax_typical", 6.5, False),
    ("C  fix scene only    mirror OFF clean  argmax", 0.0, "clean", 14.0, False),
    ("D  fix scene only    mirror OFF himax  argmax", 0.0, "himax_typical", 6.5, False),
    ("E  fix decode only   mirror on  clean  soft  ", 0.2, "clean", 14.0, True),
    ("F  fix decode only   mirror on  himax  soft  ", 0.2, "himax_typical", 6.5, True),
    ("G  both fixes        mirror OFF clean  soft  ", 0.0, "clean", 14.0, True),
    ("H  both fixes        mirror OFF himax  soft  ", 0.0, "himax_typical", 6.5, True),
]
print(f"scene {a.scene}  start {a.d_start} m  M7 target 1.942 m  "
      f"perfect-argmax floor 2.428 m  hold band [1.619, 2.428] m")
print(f"law: vx = clip({K_FWD}*({TARGET} - size), {V_MAX});  {a.seconds:.0f} s\n")
print(f"  {'case':46s} {'final d':>8s} {'mean last 5s':>13s} {'|err| vs 1.942':>15s}  in band?")
for name, refl, preset, rate, soft in CASES:
    finals, means = [], []
    for s in range(a.seeds if preset != "clean" else 1):
        t = run(refl, preset, rate, soft, 1234 + s)
        arr = np.array([x[0] for x in t])
        finals.append(arr[-1]); means.append(arr[int(-5*rate):].mean())
    f, mn = float(np.median(finals)), float(np.median(means))
    band = 1.619*0.9 <= f <= 2.428*1.1
    spread = f"  (n={len(finals)}, {min(finals):.2f}-{max(finals):.2f})" if len(finals) > 1 else ""
    print(f"  {name:46s} {f:7.2f}m {mn:12.2f}m {abs(mn-1.942):14.2f}m   "
          f"{'YES' if band else 'no ':3s}{spread}")
