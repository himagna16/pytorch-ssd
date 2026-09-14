# Independent re-measure (verifier). Same physical setup as the notes: named cutout alone, static,
# straight ahead, camera on the eye line (x,0,0.8) facing +x; champion float via bs.run_model.
import json, sys, copy, time
from pathlib import Path
import numpy as np
SIM = Path("/Users/saimaruvada/Downloads/drone/pytorch_ssd/tools/crazysim_macos")
sys.path.insert(0, str(SIM))
import mujoco, build_scene as bs, camera_model as cm, perception_backends as pb
SCR = Path(sys.argv[1]); SCR.mkdir(parents=True, exist_ok=True)
CKPT = bs.DRONE_ROOT / "pytorch_ssd_unstable/artifacts/successor_qat_ep3_eval.pth"
UNST = bs.DRONE_ROOT / "pytorch_ssd_unstable"
COCO_ROOT = bs.DRONE_ROOT / "pytorch_ssd/data/coco"
print("ckpt", CKPT, CKPT.exists(), flush=True)
coco = bs.load_coco(COCO_ROOT)
model, head = bs.load_model(UNST, CKPT)
try:
    chip = pb.ChipPerception(unstable_root=UNST, ckpt=CKPT); print("chip ok", str(chip.info)[:200], flush=True)
except Exception as e:
    chip = None; print("chip unavailable:", e, flush=True)

def luma(rgb): return np.dot(rgb[..., :3], [0.2989, 0.5870, 0.1140]).astype(np.uint8)

def add_cam(spec):
    c = spec.worldbody.add_camera(); c.name="vcam"; c.fovy=bs.FOVY_DEG; c.pos=[0,0,bs.FLIGHT_HEIGHT]
    c.alt.type = mujoco.mjtOrientation.mjORIENTATION_XYAXES; c.alt.xyaxes=[0,-1,0,0,0,1]

def himax(rgb, seeds, warm):
    f, c = [], []
    for s in seeds:
        camm = cm.CameraModel("himax_typical", bs.FRAME_W, bs.FRAME_H, seed=s)
        for _ in range(warm): g = camm.apply(rgb, omega=np.zeros(3), dt=0.153)
        g = camm.apply(rgb, omega=np.zeros(3), dt=0.153)
        f.append(round(bs.run_model(model, head, g)["visibility_confidence"], 3))
        if chip: c.append(round(chip(g)["visibility_confidence"], 3))
    return f, c

def measure(m, md, cid, gid, ranges, sx, sy, himax_at, walk=None, manifest=None, subj=None, x0=None):
    for r in ranges:
        if walk:
            t = walk["t_start"] + (x0 - r) / abs(walk["v"]); md.time = t
            bs.preview_qpos(m, md, manifest, t); mujoco.mj_forward(m, md)
            bid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, subj)
            sx, sy = float(md.xpos[bid][0]), float(md.xpos[bid][1]); cx = 0.0
        else:
            cx = sx - r
        m.cam_pos[cid] = [cx, 0, bs.FLIGHT_HEIGHT]; mujoco.mj_forward(m, md)
        rr = mujoco.Renderer(m, bs.FRAME_H, bs.FRAME_W); rr.update_scene(md, camera="vcam"); rgb = rr.render()
        sr = mujoco.Renderer(m, bs.FRAME_H, bs.FRAME_W); sr.enable_segmentation_rendering(); sr.update_scene(md, camera="vcam"); seg = sr.render()
        mask = (seg[...,0]==mujoco.mjtObj.mjOBJ_GEOM) & (seg[...,1]==gid)
        rows = np.where(mask.any(axis=1))[0]; px = int(rows[-1]-rows[0]+1) if rows.size else 0
        g = luma(rgb); fc = bs.run_model(model, head, g)["visibility_confidence"]
        cc = chip(g) if chip else None
        st = {"mean_dn": round(float(g.mean()),1), "levels": int(len(np.unique(g)))}
        if mask.any(): st["subj_minus_bg_dn"] = round(float(g[mask].mean()-g[~mask].mean()),1)
        line = f"  r={r:4.2f} subj@({sx:.2f},{sy:.2f}) cam_x={cx:.2f} px={px:3d} | float/clean {fc:.3f}"
        if cc: line += f" | chip/clean {cc['visibility_confidence']:.3f} gate={int(cc['vis_gate'])}"
        if r in himax_at:
            f2,c2 = himax(rgb,[1234,1235],20); f3,c3 = himax(rgb,[7,8,9],30)
            line += f" | himax(agent cfg 2x/20 seeds1234,1235) float {np.mean(f2):.3f}{f2} chip {np.mean(c2) if c2 else float('nan'):.3f}{c2} | himax(3x/30 seeds7-9) float {np.mean(f3):.3f}{f3} chip {np.mean(c3) if c3 else float('nan'):.3f}{c3}"
        line += f" | {st}"
        print(line, flush=True)
        rr.close(); sr.close()

def single(scene, subj, ranges, himax_at=()):
    d = json.loads((SIM/"scene_defs"/f"{scene}.json").read_text())
    s0 = next(s for s in d["subjects"] if s["name"]==subj)
    dd = {k:v for k,v in d.items() if k not in ("subjects","occluders","clutter_primitives","preview_cam_x","preview_t_s")}
    dd["scene_id"] = f"v_{scene}_{subj}"
    s1 = copy.deepcopy(s0); s1.pop("note",None); s1["pos"]=[max(ranges),0.0]; s1["motion"]={"type":"static"}
    dd["subjects"]=[s1]
    out, man = bs.build(dd, coco, COCO_ROOT, SCR, ["verify_probe.py"], "flat", 0.0)
    print(f"\n== SINGLE {scene}/{subj} h={s0['height_m']} coco={s0['coco']} lighting={d.get('lighting','default')} manifest.floor_reflectance={man['room']['floor_reflectance']}", flush=True)
    spec = mujoco.MjSpec.from_file(str(out/"scene.xml")); add_cam(spec); m=spec.compile(); md=mujoco.MjData(m); mujoco.mj_forward(m,md)
    cid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_CAMERA, "vcam"); gid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_GEOM, f"{subj}_panel")
    bid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, subj)
    measure(m, md, cid, gid, ranges, float(md.xpos[bid][0]), float(md.xpos[bid][1]), himax_at)

def scene_path(scene, subj, ranges, himax_at=(), walkin=False):
    d = json.loads((SIM/"scene_defs"/f"{scene}.json").read_text()); s0 = next(s for s in d["subjects"] if s["name"]==subj)
    out = SIM/"scenes_v2"/scene; man = json.loads((out/"manifest.json").read_text())
    print(f"\n== {'WALKIN' if walkin else 'PATH'} {scene}/{subj} manifest.floor_reflectance={man['room']['floor_reflectance']} built_at={man.get('built_at')}", flush=True)
    spec = mujoco.MjSpec.from_file(str(out/"scene.xml")); add_cam(spec); m=spec.compile(); md=mujoco.MjData(m)
    t = bs.default_preview_t(man, d); md.time=t; bs.preview_qpos(m, md, man, t); mujoco.mj_forward(m,md)
    cid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_CAMERA, "vcam"); gid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_GEOM, f"{subj}_panel")
    bid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, subj)
    walk=None
    if walkin:
        drv = next(x for x in man["scripted_motion"]["drives"] if x["joint"]==f"drive_{subj}")
        walk={"t_start":float(drv["t_start"]),"v":float(drv["v"])}; print("  drive:", drv, flush=True)
    measure(m, md, cid, gid, ranges, float(md.xpos[bid][0]), float(md.xpos[bid][1]), himax_at, walk, man, subj, float(s0["pos"][0]))

t0=time.time()
single("s10_near_threshold_person","subj_person_target",[1.25,1.5,1.75,2.5,3.0,3.25,3.5],himax_at=(1.25,1.5,3.25))
single("s04_dummies_only","subj_dummy_tall",[2.0,3.0],himax_at=(3.0,))
single("s04_dummies_only","subj_teddy_low",[1.5,2.5,3.5],himax_at=(2.5,))
single("s03_pets_only","subj_dog",[1.5,2.5,3.5])
single("s03_pets_only","subj_cat",[1.5,2.5,3.5])
single("s13_clutter_room","subj_clut_chair",[1.5,2.5,3.5])
single("s05_person_plus_pet","subj_pet_distractor",[2.5,3.0,3.5])
scene_path("s09_far_person","subj_person_target",[6.9,6.5,6.0,5.5],himax_at=(6.9,),walkin=True)
scene_path("s12_dim_room","subj_person",[3.0,2.0,1.0])
if chip: chip.close()
print(f"done in {time.time()-t0:.0f}s")
