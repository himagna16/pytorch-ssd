import math, sys, json
from pathlib import Path
import numpy as np, mujoco
from PIL import Image, ImageDraw
SIMDIR = Path("/Users/saimaruvada/Downloads/drone/pytorch_ssd/tools/crazysim_macos")
sys.path.insert(0, str(SIMDIR)); import camera_model as cm
FRAME_W, FRAME_H, FOVY, EYE_Z = 324, 244, 70.0, 0.8
out = SIMDIR / "scenes_v2/s15_static_offset"
spec = mujoco.MjSpec.from_file(str(out / "scene.xml"))
c = spec.worldbody.add_camera(); c.name, c.fovy = "cam", FOVY
c.pos = [0,0,EYE_Z]; c.alt.type = mujoco.mjtOrientation.mjORIENTATION_XYAXES
c.alt.xyaxes = [0,-1,0,0,0,1]
m = spec.compile(); d = mujoco.MjData(m); mujoco.mj_forward(m, d)
cid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_CAMERA, "cam")
bid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, "subj_person_target")
gid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_GEOM, "subj_person_target_panel")
mid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_MATERIAL, "groundplane")
sx, sy = float(d.xpos[bid][0]), float(d.xpos[bid][1])
r = mujoco.Renderer(m, FRAME_H, FRAME_W)
sr = mujoco.Renderer(m, FRAME_H, FRAME_W); sr.enable_segmentation_rendering()
cmod = cm.CameraModel("himax_typical", FRAME_W, FRAME_H, seed=1234)
DIST = 3.0
tiles = []
for refl in (0.2, 0.0):
    m.mat_reflectance[mid] = refl
    m.cam_pos[cid] = [sx-DIST, sy, EYE_Z]; mujoco.mj_forward(m, d)
    r.update_scene(d, camera="cam"); rgb = r.render()
    sr.update_scene(d, camera="cam"); seg = sr.render()
    msk = (seg[...,0]==mujoco.mjtObj.mjOBJ_GEOM)&(seg[...,1]==gid)
    rr = np.where(msk.any(axis=1))[0]
    g = np.dot(rgb[...,:3],[0.2989,0.5870,0.1140]).astype(np.uint8)
    gh = cmod.apply(rgb, omega=np.zeros(3), dt=0.153)
    for nm, gg in (("clean", g), ("himax", gh)):
        im = Image.fromarray(gg).convert("RGB")
        dd = ImageDraw.Draw(im)
        dd.rectangle([40, int(rr[0]), FRAME_W-40, int(rr[-1])], outline=(255,60,60))
        dd.text((4,4), f"reflectance {refl}  {nm}  d={DIST}m  true panel rows {rr[0]}-{rr[-1]}", fill=(255,255,0))
        tiles.append(im)
W, Hh = FRAME_W*2+24, FRAME_H*2+24
sheet = Image.new("RGB",(W,Hh),(20,20,24))
for i,t in enumerate(tiles):
    sheet.paste(t, (8+(i%2)*(FRAME_W+8), 8+(i//2)*(FRAME_H+8)))
sheet.resize((W*2,Hh*2), Image.LANCZOS).save(sys.argv[1])
print("wrote", sys.argv[1])
