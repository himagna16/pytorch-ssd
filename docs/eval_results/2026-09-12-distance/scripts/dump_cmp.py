"""Side-by-side: the MuJoCo render vs the flat-background paste at the same
distance, both as the 128x128 the network actually sees."""
import math, sys, json
from pathlib import Path
import numpy as np, mujoco
from PIL import Image, ImageFilter

SIMDIR = Path("/Users/saimaruvada/Downloads/drone/pytorch_ssd/tools/crazysim_macos")
COCO_ROOT = Path("/Users/saimaruvada/Downloads/drone/pytorch_ssd/data/coco")
sys.path.insert(0, str(SIMDIR))
import camera_model as cm
FRAME_W, FRAME_H, FOVY, EYE_Z, H = 324, 244, 70.0, 0.8, 1.7
FOCAL = (FRAME_H / 2) / math.tan(math.radians(35.0))
WALL = (158, 158, 168)
OUT = Path(sys.argv[1]); OUT.mkdir(parents=True, exist_ok=True)
DISTS = [2.4, 3.0, 3.4]

out = SIMDIR / "scenes_v2/s15_static_offset"
spec = mujoco.MjSpec.from_file(str(out / "scene.xml"))
c = spec.worldbody.add_camera(); c.name, c.fovy = "cam", FOVY
c.pos = [0, 0, EYE_Z]; c.alt.type = mujoco.mjtOrientation.mjORIENTATION_XYAXES
c.alt.xyaxes = [0, -1, 0, 0, 0, 1]
m = spec.compile(); d = mujoco.MjData(m); mujoco.mj_forward(m, d)
cid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_CAMERA, "cam")
bid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, "subj_person_target")
gid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_GEOM, "subj_person_target_panel")
sx, sy = float(d.xpos[bid][0]), float(d.xpos[bid][1])
r = mujoco.Renderer(m, FRAME_H, FRAME_W)
sr = mujoco.Renderer(m, FRAME_H, FRAME_W); sr.enable_segmentation_rendering()

from pycocotools.coco import COCO
coco = COCO(str(COCO_ROOT / "annotations/instances_val2017.json"))
ann = coco.loadAnns(428692)[0]; info = coco.loadImgs(ann["image_id"])[0]
rgbimg = np.asarray(Image.open(COCO_ROOT / "images/val2017" / info["file_name"]).convert("RGB"))
mask = coco.annToMask(ann).astype(np.uint8) * 255
bx, by, bw, bh = [int(round(v)) for v in ann["bbox"]]
mm = Image.fromarray(mask).filter(ImageFilter.MinFilter(5))
mm = np.asarray(mm.filter(ImageFilter.GaussianBlur(1)), np.float32)[..., None] / 255.0
sub = rgbimg.astype(np.float32)[by:by+bh, bx:bx+bw]; sm = mm[by:by+bh, bx:bx+bw]
comp = (sub * sm + np.array(WALL, np.float32) * (1 - sm)).astype(np.uint8)
card = Image.fromarray(comp, "RGB")

cammod = cm.CameraModel("himax_typical", FRAME_W, FRAME_H, seed=1234)

def net_input(gray):
    s = min(gray.shape); y0, x0 = (gray.shape[0]-s)//2, (gray.shape[1]-s)//2
    return np.asarray(Image.fromarray(gray[y0:y0+s, x0:x0+s]).resize((128,128), Image.BILINEAR))

tiles = []
for dist in DISTS:
    m.cam_pos[cid] = [sx - dist, sy, EYE_Z]; mujoco.mj_forward(m, d)
    r.update_scene(d, camera="cam"); rgb = r.render()
    sr.update_scene(d, camera="cam"); seg = sr.render()
    msk = (seg[...,0]==mujoco.mjtObj.mjOBJ_GEOM)&(seg[...,1]==gid)
    rr = np.where(msk.any(axis=1))[0]
    g_sim = np.dot(rgb[...,:3],[0.2989,0.5870,0.1140]).astype(np.uint8)
    g_hmx = cammod.apply(rgb, omega=np.zeros(3), dt=0.153)
    px_h = int(round(FOCAL*H/dist)); px_w = max(1,int(round(px_h*card.width/card.height)))
    top = int(round(FRAME_H/2 - FOCAL*(H-EYE_Z)/dist))
    fr = Image.new("RGB",(FRAME_W,FRAME_H),WALL)
    fr.paste(card.resize((px_w,px_h), Image.LANCZOS), ((FRAME_W-px_w)//2, top))
    g_pst = np.asarray(fr.convert("L"))
    print(f"d={dist}: sim panel rows {rr[0]}-{rr[-1]} (h={rr[-1]-rr[0]+1})  paste rows {top}-{top+px_h-1} (h={px_h})")
    print(f"    frame mean DN: sim {g_sim.mean():6.1f} (sat {100*(g_sim>=254).mean():.1f}%)   "
          f"himax {g_hmx.mean():6.1f} (sat {100*(g_hmx>=254).mean():.1f}%)   paste {g_pst.mean():6.1f}")
    for nm, g in [("sim", g_sim), ("himax", g_hmx), ("paste", g_pst)]:
        tiles.append((f"{nm} d={dist}", net_input(g)))

W = 8 + len(tiles)//3 * 136
sheet = Image.new("L", (3*136+8, (len(tiles)//3)*136+8), 30)
for i,(nm,t) in enumerate(tiles):
    col, row = i % 3, i // 3
    sheet.paste(Image.fromarray(t), (8+col*136, 8+row*136))
sheet.resize((sheet.width*2, sheet.height*2), Image.NEAREST).save(OUT/"cmp.png")
print(f"\nwrote {OUT/'cmp.png'}  (columns: sim | himax | paste ; rows: {DISTS})")
