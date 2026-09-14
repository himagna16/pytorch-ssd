# Placement sensitivity: same cutout, same RANGE, different absolute x in the room. Plus whole-scene
# measurements at the scenes' DECLARED placement with float / chip / himax.
import json, sys, copy
from pathlib import Path
import numpy as np
SIM = Path("/Users/saimaruvada/Downloads/drone/pytorch_ssd/tools/crazysim_macos"); sys.path.insert(0, str(SIM))
import mujoco, build_scene as bs, camera_model as cm, perception_backends as pb
SCR = Path(sys.argv[1]); SCR.mkdir(parents=True, exist_ok=True)
CKPT = bs.DRONE_ROOT/"pytorch_ssd_unstable/artifacts/successor_qat_ep3_eval.pth"; UNST = bs.DRONE_ROOT/"pytorch_ssd_unstable"; COCO_ROOT = bs.DRONE_ROOT/"pytorch_ssd/data/coco"
coco = bs.load_coco(COCO_ROOT); model, head = bs.load_model(UNST, CKPT); chip = pb.ChipPerception(unstable_root=UNST, ckpt=CKPT)
def luma(rgb): return np.dot(rgb[..., :3],[0.2989,0.5870,0.1140]).astype(np.uint8)
def add_cam(spec):
    c=spec.worldbody.add_camera(); c.name="vcam"; c.fovy=bs.FOVY_DEG; c.pos=[0,0,bs.FLIGHT_HEIGHT]
    c.alt.type=mujoco.mjtOrientation.mjORIENTATION_XYAXES; c.alt.xyaxes=[0,-1,0,0,0,1]
def himax(rgb, seeds, warm):
    f,c=[],[]
    for s in seeds:
        camm=cm.CameraModel("himax_typical",bs.FRAME_W,bs.FRAME_H,seed=s)
        for _ in range(warm): g=camm.apply(rgb,omega=np.zeros(3),dt=0.153)
        g=camm.apply(rgb,omega=np.zeros(3),dt=0.153)
        f.append(round(bs.run_model(model,head,g)["visibility_confidence"],3)); c.append(round(chip(g)["visibility_confidence"],3))
    return f,c
def shoot(m, md, cid, cx, label, do_himax=True):
    m.cam_pos[cid]=[cx,0,bs.FLIGHT_HEIGHT]; mujoco.mj_forward(m,md)
    r=mujoco.Renderer(m,bs.FRAME_H,bs.FRAME_W); r.update_scene(md,camera="vcam"); rgb=r.render(); r.close()
    g=luma(rgb); fc=bs.run_model(model,head,g)["visibility_confidence"]; cc=chip(g)
    line=f"  {label} cam_x={cx:.2f} | float/clean {fc:.3f} | chip/clean {cc['visibility_confidence']:.3f} gate={int(cc['vis_gate'])}"
    if do_himax:
        f2,c2=himax(rgb,[1234,1235],20); f3,c3=himax(rgb,[7,8,9,10,11],30)
        line+=f" | himax 2x/20 float {np.mean(f2):.3f}{f2} chip {np.mean(c2):.3f}{c2} | himax 5x/30 float {np.mean(f3):.3f}{f3} chip {np.mean(c3):.3f}{c3}"
    print(line, flush=True)
def sweep(scene, subj, rng, xs, extra_ranges=()):
    d=json.loads((SIM/"scene_defs"/f"{scene}.json").read_text()); s0=next(s for s in d["subjects"] if s["name"]==subj)
    print(f"\n== PLACEMENT SWEEP {scene}/{subj} at range {rng} m (cutout alone, static, straight ahead)", flush=True)
    for x in xs:
        dd={k:v for k,v in d.items() if k not in ("subjects","occluders","clutter_primitives","preview_cam_x","preview_t_s")}
        dd["scene_id"]=f"p_{scene}_{subj}_{x}"; s1=copy.deepcopy(s0); s1.pop("note",None); s1["pos"]=[x,0.0]; s1["motion"]={"type":"static"}; dd["subjects"]=[s1]
        out,man=bs.build(dd,coco,COCO_ROOT,SCR,["placement.py"],"flat",0.0); assert man["room"]["floor_reflectance"]==0.0
        spec=mujoco.MjSpec.from_file(str(out/"scene.xml")); add_cam(spec); m=spec.compile(); md=mujoco.MjData(m); mujoco.mj_forward(m,md)
        cid=mujoco.mj_name2id(m,mujoco.mjtObj.mjOBJ_CAMERA,"vcam")
        shoot(m,md,cid,x-rng,f"subject_x={x:.2f}")
        for er in extra_ranges: shoot(m,md,cid,x-er,f"subject_x={x:.2f} (range {er})",do_himax=False)
def whole(scene, t, cam_xs):
    d=json.loads((SIM/"scene_defs"/f"{scene}.json").read_text()); out=SIM/"scenes_v2"/scene; man=json.loads((out/"manifest.json").read_text())
    spec=mujoco.MjSpec.from_file(str(out/"scene.xml")); add_cam(spec); m=spec.compile(); md=mujoco.MjData(m); md.time=t
    ap=bs.preview_qpos(m,md,man,t); mujoco.mj_forward(m,md); cid=mujoco.mj_name2id(m,mujoco.mjtObj.mjOBJ_CAMERA,"vcam")
    pos={s["name"]:[round(float(v),2) for v in md.xpos[mujoco.mj_name2id(m,mujoco.mjtObj.mjOBJ_BODY,s["name"])][:2]] for s in d["subjects"]}
    print(f"\n== WHOLE-SCENE {scene} t={t} floor_reflectance={man['room']['floor_reflectance']} subjects_at={pos} scripted={ap}", flush=True)
    for cx in cam_xs: shoot(m,md,cid,cx,f"t={t}")
sweep("s10_near_threshold_person","subj_person_target",1.5,[1.5,2.0,2.5,3.0,3.5,4.0,4.5],extra_ranges=(1.25,))
sweep("s04_dummies_only","subj_dummy_tall",3.0,[3.0,3.5,4.0,4.5,5.0])
whole("s10_near_threshold_person",4.5,[0.0])
whole("s10_near_threshold_person",0.0,[0.0])
whole("s04_dummies_only",0.0,[0.0])
whole("s14_target_substitution",26.0,[0.0])
whole("s14_target_substitution",28.0,[0.0])
chip.close()
