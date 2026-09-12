"""How much taller does the mirror make the subject look?

Render twice at each distance: with the subject panel, and with it hidden.
Every pixel that differs is a pixel the panel contributes - the panel itself AND
its reflection in the floor. The vertical extent of that difference is the
apparent subject height the network is actually shown.
"""
import math, sys
from pathlib import Path
import numpy as np, mujoco
SIMDIR = Path("/Users/saimaruvada/Downloads/drone/pytorch_ssd/tools/crazysim_macos")
FRAME_W, FRAME_H, FOVY, EYE_Z = 324, 244, 70.0, 0.8
TAN = math.tan(math.radians(35.0)); H = 1.7
out = SIMDIR / "scenes_v2/s15_static_offset"
spec = mujoco.MjSpec.from_file(str(out / "scene.xml"))
c = spec.worldbody.add_camera(); c.name, c.fovy = "cam", FOVY
c.pos=[0,0,EYE_Z]; c.alt.type=mujoco.mjtOrientation.mjORIENTATION_XYAXES; c.alt.xyaxes=[0,-1,0,0,0,1]
m = spec.compile(); d = mujoco.MjData(m); mujoco.mj_forward(m, d)
cid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_CAMERA, "cam")
bid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, "subj_person_target")
gid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_GEOM, "subj_person_target_panel")
mid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_MATERIAL, "groundplane")
sx, sy = float(d.xpos[bid][0]), float(d.xpos[bid][1])
r = mujoco.Renderer(m, FRAME_H, FRAME_W)
sr = mujoco.Renderer(m, FRAME_H, FRAME_W); sr.enable_segmentation_rendering()
rgba0 = m.geom_rgba[gid].copy()

print("  refl   d_true  panel_rows  panel_h  apparent_h  apparent/true  implied over-read")
for refl in (0.2, 0.0):
    m.mat_reflectance[mid] = refl
    for dist in (2.4, 2.8, 3.0, 3.4, 3.8):
        m.cam_pos[cid] = [sx-dist, sy, EYE_Z]; mujoco.mj_forward(m, d)
        m.geom_rgba[gid] = rgba0
        r.update_scene(d, camera="cam"); a = r.render().astype(np.int16)
        sr.update_scene(d, camera="cam"); seg = sr.render()
        msk = (seg[...,0]==mujoco.mjtObj.mjOBJ_GEOM)&(seg[...,1]==gid)
        rr = np.where(msk.any(axis=1))[0]
        m.geom_rgba[gid] = [0,0,0,0]
        r.update_scene(d, camera="cam"); b = r.render().astype(np.int16)
        diff = np.abs(a-b).max(axis=2) > 6          # 6 DN: above renderer dither
        dr = np.where(diff.any(axis=1))[0]
        ph = int(rr[-1]-rr[0]+1); ah = int(dr[-1]-dr[0]+1)
        print(f"  {refl:.1f}  {dist:7.2f}   {rr[0]:3d}-{rr[-1]:3d}     {ph:5d}      {ah:6d}"
              f"       {ah/ph:8.3f}       {ah/ph:8.3f}x")
    print()
m.geom_rgba[gid] = rgba0
