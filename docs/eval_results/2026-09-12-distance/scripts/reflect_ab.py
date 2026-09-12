"""Single-variable A/B: the MuJoCo groundplane's reflectance="0.2" mirror.

Everything else identical - same scene, same camera, same distances, same model.
Only mat_reflectance for the floor is changed, in the COMPILED model, in memory.
build_scene.py and the scene XML on disk are not touched.
"""
import math, sys, json
from pathlib import Path
import numpy as np, mujoco
from PIL import Image

SIMDIR = Path("/Users/saimaruvada/Downloads/drone/pytorch_ssd/tools/crazysim_macos")
UNSTABLE = Path("/Users/saimaruvada/Downloads/drone/pytorch_ssd_unstable")
sys.path.insert(0, str(SIMDIR)); sys.path.insert(0, str(UNSTABLE))
import camera_model as cm
FRAME_W, FRAME_H, FOVY, EYE_Z = 324, 244, 70.0, 0.8
TAN = math.tan(math.radians(35.0))
CENTRES = np.array([0.125, 0.375, 0.625, 0.875])

scene = sys.argv[1] if len(sys.argv) > 1 else "s15_static_offset"
out = SIMDIR / "scenes_v2" / scene
man = json.loads((out / "manifest.json").read_text())
sub = [s for s in man["subjects"] if s["role"] == "person_target"][0]
NAME = sub["name"]; H = float(sub["panel"]["height_m"])

spec = mujoco.MjSpec.from_file(str(out / "scene.xml"))
c = spec.worldbody.add_camera(); c.name, c.fovy = "cam", FOVY
c.pos = [0, 0, EYE_Z]; c.alt.type = mujoco.mjtOrientation.mjORIENTATION_XYAXES
c.alt.xyaxes = [0, -1, 0, 0, 0, 1]
m = spec.compile(); d = mujoco.MjData(m); mujoco.mj_forward(m, d)
cid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_CAMERA, "cam")
bid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, NAME)
gid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_GEOM, f"{NAME}_panel")
mid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_MATERIAL, "groundplane")
sx, sy = float(d.xpos[bid][0]), float(d.xpos[bid][1])
print(f"scene {scene}  floor material reflectance as built = {m.mat_reflectance[mid]:.3f}")

import torch
from models.follow_model_factory import build_follow_model_from_checkpoint
CKPT = UNSTABLE / "artifacts/successor_qat_ep3_eval.pth"
head = torch.load(CKPT, map_location="cpu").get("follow_head_type")
model = build_follow_model_from_checkpoint(CKPT, torch.device("cpu")).eval()

def probe(gray):
    s = min(gray.shape); y0, x0 = (gray.shape[0]-s)//2, (gray.shape[1]-s)//2
    crop = Image.fromarray(gray[y0:y0+s, x0:x0+s]).resize((128,128), Image.BILINEAR)
    x = torch.from_numpy(np.asarray(crop, np.float32)/255.0)[None,None]
    with torch.no_grad():
        o = model(x).reshape(-1).numpy()
    l = o[10:14]; e = np.exp(l-l.max()); p = e/e.sum()
    return int(np.argmax(l)), float((p*CENTRES).sum())

dists = np.arange(1.8, 4.21, 0.1)
r = mujoco.Renderer(m, FRAME_H, FRAME_W)
sr = mujoco.Renderer(m, FRAME_H, FRAME_W); sr.enable_segmentation_rendering()
cams = [cm.CameraModel("himax_typical", FRAME_W, FRAME_H, seed=1234+i) for i in range(5)]

res = {}
for refl in (0.2, 0.0):
    m.mat_reflectance[mid] = refl
    rows = []
    for dist in dists:
        m.cam_pos[cid] = [sx-dist, sy, EYE_Z]; mujoco.mj_forward(m, d)
        r.update_scene(d, camera="cam"); rgb = r.render()
        sr.update_scene(d, camera="cam"); seg = sr.render()
        msk = (seg[...,0]==mujoco.mjtObj.mjOBJ_GEOM)&(seg[...,1]==gid)
        rr = np.where(msk.any(axis=1))[0]
        true_s = (int(rr[-1]-rr[0]+1) if rr.size else 0)/FRAME_H
        g = np.dot(rgb[...,:3],[0.2989,0.5870,0.1140]).astype(np.uint8)
        bc, sc = probe(g)
        hb, hs = [], []
        for cmod in cams:
            b2, s2 = probe(cmod.apply(rgb, omega=np.zeros(3), dt=0.153))
            hb.append(b2); hs.append(s2)
        rows.append((dist, true_s, bc, sc, float(np.mean(np.array(hb)>=2)), float(np.mean(hs))))
    res[refl] = rows

print(f"\ntrue 1->2 edge (size 0.500) = {H/(2*0.5*TAN):.3f} m\n")
print("  d_true  true_size | reflect 0.2: clean_bkt soft   himax P>=2 soft | reflect 0.0: clean_bkt soft   himax P>=2 soft")
for i, dist in enumerate(dists):
    a = res[0.2][i]; b = res[0.0][i]
    print(f"  {dist:6.2f}  {a[1]:9.4f} |        {a[2]:d}  {a[3]:.3f}      {a[4]:.2f}   {a[5]:.3f}  |"
          f"         {b[2]:d}  {b[3]:.3f}      {b[4]:.2f}   {b[5]:.3f}")

def outer(rows, key):
    hits = [r[0] for r in rows if (r[2] >= 2 if key == "clean" else r[4] >= 0.5)]
    return max(hits) if hits else None

print()
for refl in (0.2, 0.0):
    for key in ("clean", "himax"):
        o = outer(res[refl], key)
        if o:
            s = [r[1] for r in res[refl] if abs(r[0]-o) < 1e-9][0]
            print(f"  reflectance {refl:.1f}  {key:5s}: outermost bucket>=2 at {o:.2f} m "
                  f"(true size {s:.3f})  over-read {0.5/s:.2f}x  {o-H/(2*0.5*TAN):+.2f} m vs ideal")
        else:
            print(f"  reflectance {refl:.1f}  {key:5s}: never bucket>=2 in 1.8-4.2 m")
