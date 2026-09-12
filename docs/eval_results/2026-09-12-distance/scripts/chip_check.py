"""SKEPTIC CHECK: does the CHIP network (what the failing ships-as cells actually flew)
show the same two things the report verified on the FLOAT network?
  (a) the mirror inflates the size reading
  (b) the size head is unbiased on real COCO images
"""
import math, sys, struct, json
from pathlib import Path
import numpy as np, mujoco, torch
from PIL import Image

SIM = Path("/Users/saimaruvada/Downloads/drone/pytorch_ssd/tools/crazysim_macos")
UNS = Path("/Users/saimaruvada/Downloads/drone/pytorch_ssd_unstable")
sys.path.insert(0, str(SIM)); sys.path.insert(0, str(UNS))
import perception_backends as pb
from perception_backends import firmware_preprocess, ChipPerception, _decode_from_logits

chip = ChipPerception()
print("chip server:", {k: v for k, v in chip.info.items() if k != "onnx"})

def chip_from_netin(net_in_u8):
    chip._sock.sendall(np.ascontiguousarray(net_in_u8, np.uint8).tobytes())
    buf = b""
    while len(buf) < pb.RESP_LEN:
        buf += chip._sock.recv(pb.RESP_LEN - len(buf))
    vals = struct.unpack(pb.RESP_FMT, buf)
    logits = np.array(vals[:pb.N_OUT], np.int64).astype(np.float64) * chip.eps
    return _decode_from_logits(logits), logits

# ---------- float model ----------
from models.follow_model_factory import build_follow_model_from_checkpoint
CK = UNS / "artifacts/successor_qat_ep3_eval.pth"
fm = build_follow_model_from_checkpoint(CK, torch.device("cpu")).eval()
CENT = np.array([0.125, 0.375, 0.625, 0.875])
def float_from_netin(net_in_u8):
    x = torch.from_numpy(net_in_u8.astype(np.float32)/255.0)[None, None]
    with torch.no_grad():
        l = fm(x).reshape(-1).numpy()
    return int(np.argmax(l[10:14])), l

# ================= (a) mirror A/B on the chip net =================
FW, FH, FOVY, EZ = 324, 244, 70.0, 0.8
TAN = math.tan(math.radians(35.0)); H = 1.7
spec = mujoco.MjSpec.from_file(str(SIM/"scenes_v2/s15_static_offset/scene.xml"))
c = spec.worldbody.add_camera(); c.name, c.fovy = "cam", FOVY
c.pos=[0,0,EZ]; c.alt.type=mujoco.mjtOrientation.mjORIENTATION_XYAXES; c.alt.xyaxes=[0,-1,0,0,0,1]
m = spec.compile(); d = mujoco.MjData(m); mujoco.mj_forward(m, d)
cid=mujoco.mj_name2id(m,mujoco.mjtObj.mjOBJ_CAMERA,"cam")
bid=mujoco.mj_name2id(m,mujoco.mjtObj.mjOBJ_BODY,"subj_person_target")
mid=mujoco.mj_name2id(m,mujoco.mjtObj.mjOBJ_MATERIAL,"groundplane")
sx,sy=float(d.xpos[bid][0]),float(d.xpos[bid][1])
r = mujoco.Renderer(m, FH, FW)

print("\n(a) MIRROR A/B, CLEAN CAMERA, chip net (firmware_preprocess) vs float net")
print(f"{'d':>6} {'true_sz':>8} | {'chip r0.2':>9} {'chip r0.0':>9} | {'flt r0.2':>9} {'flt r0.0':>9}")
res = {0.2: [], 0.0: []}
dists = [round(1.8+0.1*i, 2) for i in range(25)]
for dist in dists:
    row = {}
    for refl in (0.2, 0.0):
        m.mat_reflectance[mid] = refl
        m.cam_pos[cid] = [sx-dist, sy, EZ]; mujoco.mj_forward(m, d)
        r.update_scene(d, camera="cam"); rgb = r.render()
        gray = np.dot(rgb[...,:3],[0.2989,0.5870,0.1140]).astype(np.uint8)
        ni = firmware_preprocess(gray)
        cr, _ = chip_from_netin(ni)
        fb, _ = float_from_netin(ni)
        row[refl] = (int(cr["size_bucket_index"]), fb)
        res[refl].append((dist, int(cr["size_bucket_index"]), fb))
    ts = H/(2*dist*TAN)
    print(f"{dist:6.2f} {ts:8.4f} | {row[0.2][0]:9d} {row[0.0][0]:9d} | {row[0.2][1]:9d} {row[0.0][1]:9d}")

for tag, idx in (("chip", 1), ("float", 2)):
    for refl in (0.2, 0.0):
        hits = [t[0] for t in res[refl] if t[idx] >= 2]
        outer = max(hits) if hits else None
        if outer:
            print(f"  {tag:5s} refl {refl}: outermost bucket>=2 at {outer:.2f} m  over-read {outer/2.428:.2f}x")
        else:
            print(f"  {tag:5s} refl {refl}: never reached bucket 2")

# ================= (b) COCO on the chip net =================
print("\n(b) COCO val2017 subset, SAME 128x128 net input, chip vs float")
from utils.coco_follow_regression import COCOFollowRegressionDataset
from utils.transforms import get_val_transforms
from utils.follow_task import SIZE_BUCKET4_EDGES
ds = COCOFollowRegressionDataset(
    "/Users/saimaruvada/Downloads/drone/pytorch_ssd/data/coco/images/val2017",
    "/Users/saimaruvada/Downloads/drone/pytorch_ssd/data/coco/annotations/instances_val2017.json",
    transforms=get_val_transforms("plain_follow", 1, (128,128)), image_mode="L")
N = int(sys.argv[1]) if len(sys.argv) > 1 else 700
gts, cb, fb_, cs, fs = [], [], [], [], []
for i in range(min(N, len(ds))):
    img, tgt = ds[i]
    t = tgt["follow_target"]
    if float(t[2]) <= 0.5:
        continue
    ni = np.clip(img.numpy()[0]*255.0, 0, 255).round().astype(np.uint8)
    cr, _ = chip_from_netin(ni)
    f, _ = float_from_netin(ni)
    gts.append(float(t[1])); cb.append(int(cr["size_bucket_index"])); fb_.append(f)
    cs.append(float(cr["size_value"])); fs.append(CENT[f])
gts=np.array(gts); cb=np.array(cb); fb_=np.array(fb_); cs=np.array(cs); fs=np.array(fs)
gb = np.clip(np.digitize(gts, SIZE_BUCKET4_EDGES[1:-1], right=False), 0, 3)
print(f"n with person = {gts.size}")
for tag, b, s in (("chip", cb, cs), ("float", fb_, fs)):
    print(f"  {tag:5s} bucket exact {np.mean(b==gb):.4f}  mean signed err {np.mean(s-gts):+.4f}  "
          f"median dec/GT {np.median(s/np.maximum(gts,1e-6)):.4f}")
print(f"  chip==float bucket agreement: {np.mean(cb==fb_):.4f}")
# boundary
for tag, b in (("chip", cb), ("float", fb_)):
    edges = np.arange(0.20, 0.85, 0.05); xs, ps = [], []
    for lo, hi in zip(edges[:-1], edges[1:]):
        sel = (gts>=lo)&(gts<hi)
        if sel.sum() >= 10: xs.append((lo+hi)/2); ps.append(np.mean(b[sel]>=2))
    xs, ps = np.array(xs), np.array(ps); cr_ = None
    for k in range(len(xs)-1):
        if ps[k] < 0.5 <= ps[k+1]:
            cr_ = xs[k] + (0.5-ps[k])*(xs[k+1]-xs[k])/(ps[k+1]-ps[k])
    print(f"  {tag:5s} effective 1->2 boundary true size {cr_ if cr_ else float('nan'):.3f} "
          f"(nominal 0.500)")
chip.close()
