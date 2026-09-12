"""With the floor mirror OFF, what is left of the himax over-read, and which
sensor effect causes it? One override at a time off the himax_typical preset."""
import math, sys, json
from pathlib import Path
import numpy as np, mujoco
from PIL import Image
SIMDIR = Path("/Users/saimaruvada/Downloads/drone/pytorch_ssd/tools/crazysim_macos")
UNSTABLE = Path("/Users/saimaruvada/Downloads/drone/pytorch_ssd_unstable")
sys.path.insert(0, str(SIMDIR)); sys.path.insert(0, str(UNSTABLE))
import camera_model as cm
FRAME_W, FRAME_H, FOVY, EYE_Z, H = 324, 244, 70.0, 0.8, 1.7
TAN = math.tan(math.radians(35.0))
out = SIMDIR / "scenes_v2/s15_static_offset"
spec = mujoco.MjSpec.from_file(str(out/"scene.xml"))
c = spec.worldbody.add_camera(); c.name, c.fovy = "cam", FOVY
c.pos=[0,0,EYE_Z]; c.alt.type=mujoco.mjtOrientation.mjORIENTATION_XYAXES; c.alt.xyaxes=[0,-1,0,0,0,1]
m = spec.compile(); d = mujoco.MjData(m); mujoco.mj_forward(m,d)
cid=mujoco.mj_name2id(m,mujoco.mjtObj.mjOBJ_CAMERA,"cam")
bid=mujoco.mj_name2id(m,mujoco.mjtObj.mjOBJ_BODY,"subj_person_target")
gid=mujoco.mj_name2id(m,mujoco.mjtObj.mjOBJ_GEOM,"subj_person_target_panel")
mid=mujoco.mj_name2id(m,mujoco.mjtObj.mjOBJ_MATERIAL,"groundplane")
sx,sy=float(d.xpos[bid][0]),float(d.xpos[bid][1])
r=mujoco.Renderer(m,FRAME_H,FRAME_W); sr=mujoco.Renderer(m,FRAME_H,FRAME_W); sr.enable_segmentation_rendering()
import torch
from models.follow_model_factory import build_follow_model_from_checkpoint
CKPT=UNSTABLE/"artifacts/successor_qat_ep3_eval.pth"
head=torch.load(CKPT,map_location="cpu").get("follow_head_type")
model=build_follow_model_from_checkpoint(CKPT,torch.device("cpu")).eval()
def bucket(gray):
    s=min(gray.shape); y0,x0=(gray.shape[0]-s)//2,(gray.shape[1]-s)//2
    crop=Image.fromarray(gray[y0:y0+s,x0:x0+s]).resize((128,128),Image.BILINEAR)
    x=torch.from_numpy(np.asarray(crop,np.float32)/255.0)[None,None]
    with torch.no_grad(): o=model(x).reshape(-1).numpy()
    return int(np.argmax(o[10:14]))
VARIANTS = {
 "clean (no sensor model)": None,
 "himax_typical (all on)": {},
 "  - no optical blur": {"psf_sigma_center_px":0.0,"psf_sigma_corner_px":0.0},
 "  - no AE (fixed mid)": {"ae_enabled":False},
 "  - no noise": {"shot_noise":False,"read_noise":False,"prnu_sigma":0.0,"dsnu_sigma_dn":0.0,"dead_px_frac":0.0},
 "  - no vignette": {"vignette_a2":0.0,"vignette_a4":0.0},
}
dists=np.arange(1.8,4.21,0.1)
m.mat_reflectance[mid]=0.0
print("floor reflectance forced to 0.0 (mirror removed) for every row below")
print(f"true 1->2 edge = {H/(2*0.5*TAN):.3f} m\n")
print(f"  {'variant':26s} {'outermost bkt>=2':>17s} {'true size there':>16s} {'over-read':>10s}")
for name,ov in VARIANTS.items():
    cams=[None] if ov is None else [cm.CameraModel("himax_typical",FRAME_W,FRAME_H,seed=1234+i,overrides=ov) for i in range(5)]
    hits=[]
    for dist in dists:
        m.cam_pos[cid]=[sx-dist,sy,EYE_Z]; mujoco.mj_forward(m,d)
        r.update_scene(d,camera="cam"); rgb=r.render()
        sr.update_scene(d,camera="cam"); seg=sr.render()
        msk=(seg[...,0]==mujoco.mjtObj.mjOBJ_GEOM)&(seg[...,1]==gid); rr=np.where(msk.any(axis=1))[0]
        ts=(int(rr[-1]-rr[0]+1) if rr.size else 0)/FRAME_H
        if ov is None:
            bs=[bucket(np.dot(rgb[...,:3],[0.2989,0.5870,0.1140]).astype(np.uint8))]
        else:
            bs=[bucket(cmod.apply(rgb,omega=np.zeros(3),dt=0.153)) for cmod in cams]
        if np.mean(np.array(bs)>=2)>=0.5: hits.append((dist,ts))
    if hits:
        dd,ts=max(hits,key=lambda z:z[0])
        print(f"  {name:26s} {dd:14.2f} m {ts:16.3f} {0.5/ts:9.2f}x")
    else:
        print(f"  {name:26s} {'never':>17s}")
