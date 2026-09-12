"""A/B contact sheet: the scene file as it was on disk BEFORE vs AFTER the fix.

This renders two *files*, not one file with an in-memory override:
  before = a copy of the pre-fix scenes_v2 tree (reflectance 0.2)
  after  = the live scenes_v2 tree             (reflectance 0.0)

so what you see is what the flights loaded. The red box is the panel's true
pixel extent from MuJoCo's segmentation render; everything drawn outside it is
the artefact.

Usage:
  <trainenv python> asbuilt_ab_figure.py --before-root DIR --out OUT.png
"""
import argparse
from pathlib import Path

import numpy as np
import mujoco
from PIL import Image, ImageDraw, ImageFont

SIMDIR = Path("/Users/saimaruvada/Downloads/drone/pytorch_ssd/tools/crazysim_macos")
FRAME_W, FRAME_H, FOVY, EYE_Z = 324, 244, 70.0, 0.8
DISTS = (2.4, 3.0, 3.8)


def _font(sz=13):
    for p in ("/System/Library/Fonts/Supplemental/Arial.ttf",
              "/System/Library/Fonts/Helvetica.ttc"):
        try:
            return ImageFont.truetype(p, sz)
        except Exception:
            pass
    return ImageFont.load_default()


def render(scene_xml: Path, subject: str, dists=DISTS):
    spec = mujoco.MjSpec.from_file(str(scene_xml))
    c = spec.worldbody.add_camera()
    c.name, c.fovy = "cam", FOVY
    c.pos = [0, 0, EYE_Z]
    c.alt.type = mujoco.mjtOrientation.mjORIENTATION_XYAXES
    c.alt.xyaxes = [0, -1, 0, 0, 0, 1]
    m = spec.compile()
    d = mujoco.MjData(m)
    mujoco.mj_forward(m, d)
    cid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_CAMERA, "cam")
    bid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, subject)
    gid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_GEOM, f"{subject}_panel")
    mid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_MATERIAL, "groundplane")
    refl = float(m.mat_reflectance[mid])
    sx, sy = float(d.xpos[bid][0]), float(d.xpos[bid][1])
    r = mujoco.Renderer(m, FRAME_H, FRAME_W)
    sr = mujoco.Renderer(m, FRAME_H, FRAME_W)
    sr.enable_segmentation_rendering()
    tiles = []
    for dist in dists:
        m.cam_pos[cid] = [sx - dist, sy, EYE_Z]
        mujoco.mj_forward(m, d)
        r.update_scene(d, camera="cam")
        rgb = r.render()
        sr.update_scene(d, camera="cam")
        seg = sr.render()
        msk = (seg[..., 0] == mujoco.mjtObj.mjOBJ_GEOM) & (seg[..., 1] == gid)
        rr = np.where(msk.any(axis=1))[0]
        cc = np.where(msk.any(axis=0))[0]
        gray = np.dot(rgb[..., :3], [0.2989, 0.5870, 0.1140]).astype(np.uint8)
        tiles.append((dist, gray, (int(cc[0]), int(rr[0]), int(cc[-1]), int(rr[-1]))))
    return refl, tiles


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--before-root", type=Path, required=True,
                    help="a copy of the pre-fix scenes_v2 tree")
    ap.add_argument("--scene", default="s15_static_offset")
    ap.add_argument("--subject", default="subj_person_target")
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()

    rows = []
    for label, root in (("BEFORE", a.before_root), ("AFTER", SIMDIR / "scenes_v2")):
        refl, tiles = render(Path(root) / a.scene / "scene.xml", a.subject)
        rows.append((f"{label}  groundplane reflectance = {refl:g}"
                     f"{'  (specular mirror)' if refl else '  (matte)'}", tiles))

    f, fs = _font(15), _font(12)
    pad, top, cap = 8, 46, 22
    W = pad + len(DISTS) * (FRAME_W + pad)
    H = pad + len(rows) * (top + FRAME_H + cap + pad)
    sheet = Image.new("RGB", (W, H), (22, 22, 26))
    dr = ImageDraw.Draw(sheet)
    for i, (label, tiles) in enumerate(rows):
        y = pad + i * (top + FRAME_H + cap + pad)
        dr.text((pad, y + 4), label, (245, 245, 245), font=f)
        dr.text((pad, y + 24), f"{a.scene} / {a.subject}   drone eye line z={EYE_Z} m, fovy {FOVY}"
                               "   red box = the panel's true extent (segmentation render)",
                (165, 165, 178), font=fs)
        for j, (dist, gray, box) in enumerate(tiles):
            im = Image.fromarray(gray).convert("RGB")
            ImageDraw.Draw(im).rectangle(list(box), outline=(255, 60, 60))
            x = pad + j * (FRAME_W + pad)
            sheet.paste(im, (x, y + top))
            dr.text((x, y + top + FRAME_H + 4), f"{dist:.1f} m", (225, 225, 225), font=fs)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(a.out)
    print(f"wrote {a.out}  ({W}x{H})")


if __name__ == "__main__":
    main()
