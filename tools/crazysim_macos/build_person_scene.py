#!/usr/bin/env python3
"""Build a CrazySim scene containing a real COCO person on a panel.

Writes <out>/person.png (masked COCO cutout with alpha) and
<out>/scene_person.xml, loadable by crazysim.py via --scene <abs path>.
The panel can sway side to side on an undamped spring (no simulator code
changes): --sway-amp metres, --sway-period seconds.

--preview renders the drone's-eye view (fovy 70, 324x244, like the sim's
fpv_cam) at several distances and runs the team model on each render.

Run with the trainenv python (needs pycocotools, torch, mujoco).
"""
import argparse, math, os, sys
from pathlib import Path
import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
DRONE_ROOT = HERE.parents[2]

SCENE = """<mujoco model="Drone scene with a person">
  <option integrator="RK4" density="1.225" viscosity="1.8e-5" timestep="0.001"/>
  <compiler inertiafromgeom="false" autolimits="true"/>
  <statistic center="1 0 1" extent="3"/>
  <visual>
    <headlight diffuse="0.6 0.6 0.6" ambient="0.5 0.5 0.5" specular="0 0 0"/>
    <global azimuth="0" elevation="-20" ellipsoidinertia="true"/>
  </visual>
  <asset>
    <texture type="skybox" builtin="gradient" rgb1="0.3 0.5 0.7" rgb2="0 0 0" width="512" height="3072"/>
    <texture type="2d" name="groundplane" builtin="checker" mark="edge" rgb1="0.2 0.3 0.4"
             rgb2="0.1 0.2 0.3" markrgb="0.8 0.8 0.8" width="512" height="512"/>
    <material name="groundplane" texture="groundplane" texuniform="true" texrepeat="2 2" reflectance="0.2"/>
    <material name="wall" rgba="0.62 0.62 0.66 1"/>
    <texture type="2d" name="person" file="person.png"/>
    <material name="person" texture="person" rgba="1 1 1 {alpha}"/>
  </asset>
  <worldbody>
    <light pos="0 0 3" dir="0 0 -1" directional="true"/>
    <light pos="-1 0 2" dir="1 0 -0.3" directional="true" diffuse="0.5 0.5 0.5"/>
    <geom name="floor" size="0 0 0.05" type="plane" material="groundplane"/>
    <geom name="wall_far"   type="box" size="0.05 6 2" pos="7 0 2"  material="wall"/>
    <geom name="wall_back"  type="box" size="0.05 6 2" pos="-3 0 2" material="wall"/>
    <geom name="wall_left"  type="box" size="5 0.05 2" pos="2 6 2"  material="wall"/>
    <geom name="wall_right" type="box" size="5 0.05 2" pos="2 -6 2" material="wall"/>
    <body name="person" pos="{px:.4f} {py:.4f} {pz:.4f}">
      {joint}
      <!-- Tiny inertia on purpose: the scene enables MuJoCo's air model
           (density/viscosity), whose drag scales with the box implied by the
           inertia. Large inertia made the sway decay; tiny inertia keeps the
           spring motion close to y0 - amp*cos(2*pi*t/period). -->
      <inertial pos="0 0 0" mass="1" diaginertia="1e-4 1e-4 1e-4"/>
      <geom name="person_panel" type="box" size="0.004 {hw:.4f} {hh:.4f}" euler="{euler}"
            material="person" contype="0" conaffinity="0"/>
    </body>
  </worldbody>
</mujoco>
"""


def make_cutout(coco_root: Path, img_id: int, ann_id: int, out_png: Path, flip: str,
                bg=(158, 158, 168)) -> float:
    """Masked COCO person. With bg (default = the scene's wall color), the
    person is composited onto that color and the panel renders opaque, so it
    blends into the wall behind it. MuJoCo does not blend texture alpha (it
    renders transparent texels black), so bg=None is kept only for testing."""
    from pycocotools.coco import COCO
    c = COCO(str(coco_root / "annotations/instances_val2017.json"))
    info = c.loadImgs(img_id)[0]
    ann = c.loadAnns(ann_id)[0]
    rgb = np.asarray(Image.open(coco_root / "images/val2017" / info["file_name"]).convert("RGB"))
    mask = c.annToMask(ann).astype(np.uint8) * 255
    x, y, w, h = [int(round(v)) for v in ann["bbox"]]
    if bg is not None:
        from PIL import ImageFilter
        m = Image.fromarray(mask).filter(ImageFilter.MinFilter(5))  # erode edge halo
        m = np.asarray(m.filter(ImageFilter.GaussianBlur(1)), np.float32)[..., None] / 255.0
        comp = rgb.astype(np.float32) * m + np.array(bg, np.float32) * (1 - m)
        img = Image.fromarray(comp.astype(np.uint8)[y:y + h, x:x + w], "RGB")
    else:
        img = Image.fromarray(np.dstack([rgb, mask])[y:y + h, x:x + w], "RGBA")
    if "h" in flip:
        img = img.transpose(Image.FLIP_LEFT_RIGHT)
    if "v" in flip:
        img = img.transpose(Image.FLIP_TOP_BOTTOM)
    img = img.resize((max(1, int(img.width * 512 / img.height)), 512), Image.LANCZOS)
    img.save(out_png)
    return img.width / img.height


def write_scene(out_dir: Path, aspect: float, a) -> Path:
    height = a.person_height
    width = height * aspect
    if a.sway_amp > 0:
        k = 1.0 * (2 * math.pi / a.sway_period) ** 2  # mass 1 kg
        joint = (f'<joint name="sway" type="slide" axis="0 1 0" stiffness="{k:.5f}" '
                 f'springref="{a.sway_amp:.4f}" damping="0"/>')
        py = a.person_y - a.sway_amp  # swings between person_y - amp and person_y + amp
    else:
        joint, py = "", a.person_y
    xml = SCENE.format(alpha=a.alpha, px=a.person_x, py=py, pz=height / 2, joint=joint,
                       hw=width / 2, hh=height / 2, euler=a.panel_euler)
    path = out_dir / "scene_person.xml"
    path.write_text(xml)
    return path


def preview(scene_xml: Path, a) -> None:
    import mujoco, torch
    sys.path.insert(0, str(a.unstable_root))
    from models.follow_model_factory import build_follow_model_from_checkpoint
    from utils.follow_task import decode_follow_outputs
    head = torch.load(a.ckpt, map_location="cpu").get("follow_head_type")
    model = build_follow_model_from_checkpoint(Path(a.ckpt), torch.device("cpu")).eval()
    spec = mujoco.MjSpec.from_file(str(scene_xml))
    cam = spec.worldbody.add_camera()
    cam.name, cam.fovy = "preview_cam", 70.0
    cam.pos = [0.0, 0.0, a.cam_height]
    # MuJoCo cameras look along -z; image-right = world -y, image-up = world +z.
    cam.alt.type = mujoco.mjtOrientation.mjORIENTATION_XYAXES
    cam.alt.xyaxes = [0, -1, 0, 0, 0, 1]
    m = spec.compile()
    d = mujoco.MjData(m)
    mujoco.mj_forward(m, d)
    r = mujoco.Renderer(m, 244, 324)
    cid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_CAMERA, "preview_cam")
    print(f"preview: person at x={a.person_x} y={a.person_y}, camera height {a.cam_height} m")
    for dist in a.distances:
        m.cam_pos[cid] = [a.person_x - dist, 0.0, a.cam_height]
        mujoco.mj_forward(m, d)
        r.update_scene(d, camera="preview_cam")
        gray = np.dot(r.render()[..., :3], [0.2989, 0.5870, 0.1140]).astype(np.uint8)
        Image.fromarray(gray).save(scene_xml.parent / f"preview_d{dist:.1f}.png")
        s = min(gray.shape)
        y0, x0 = (gray.shape[0] - s) // 2, (gray.shape[1] - s) // 2
        crop = Image.fromarray(gray[y0:y0 + s, x0:x0 + s]).resize((128, 128), Image.BILINEAR)
        x = torch.from_numpy(np.asarray(crop, np.float32) / 255.0)[None, None]
        with torch.no_grad():
            dec = decode_follow_outputs(model(x), head)
        v = {k: float(t.reshape(-1)[0]) for k, t in dec.items() if torch.is_tensor(t)}
        print(f"  dist {dist:.1f} m: person conf {v['visibility_confidence']:.3f} | "
              f"x_bin {int(v['x_bin_index'])} (x={v['x_value']:+.2f}) | size bucket "
              f"{int(v['size_bucket_index'])} (size={v['size_value']:.3f})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--img-id", type=int, required=True)
    ap.add_argument("--ann-id", type=int, required=True)
    ap.add_argument("--coco-root", type=Path, default=DRONE_ROOT / "pytorch_ssd/data/coco")
    ap.add_argument("--out", type=Path, default=HERE / "scenes")
    ap.add_argument("--person-x", type=float, default=2.5)
    ap.add_argument("--person-y", type=float, default=0.0)
    ap.add_argument("--person-height", type=float, default=1.7)
    ap.add_argument("--sway-amp", type=float, default=0.0)
    ap.add_argument("--sway-period", type=float, default=16.0)
    ap.add_argument("--alpha", type=float, default=1.0)
    ap.add_argument("--bg", default="158,158,168", help="composite color (wall color), or 'none'")
    ap.add_argument("--panel-euler", default="0 0 0")
    ap.add_argument("--flip", default="", help="'h' and/or 'v' to flip the cutout")
    ap.add_argument("--preview", action="store_true")
    ap.add_argument("--cam-height", type=float, default=0.8)
    ap.add_argument("--distances", type=float, nargs="+", default=[1.5, 2.0, 2.5, 3.0, 4.0])
    ap.add_argument("--unstable-root", type=Path, default=DRONE_ROOT / "pytorch_ssd_unstable")
    ap.add_argument("--ckpt", type=Path,
                    default=DRONE_ROOT / "pytorch_ssd_unstable/artifacts/successor_qat_ep3_eval.pth")
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    bg = None if a.bg == "none" else tuple(int(v) for v in a.bg.split(","))
    aspect = make_cutout(a.coco_root, a.img_id, a.ann_id, a.out / "person.png", a.flip, bg)
    scene = write_scene(a.out, aspect, a)
    print(f"wrote {scene} (panel {a.person_height:.2f} m tall, aspect {aspect:.2f})")
    if a.preview:
        preview(scene, a)


if __name__ == "__main__":
    main()
