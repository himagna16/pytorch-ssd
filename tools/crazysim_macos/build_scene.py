#!/usr/bin/env python3
"""Build a CrazySim test scene from a scene definition (scene_defs/*.json).

This is the v2 scene builder. `build_person_scene.py` is left untouched, so
`demo.sh`, `run_acceptance.sh` and the published baselines keep today's
behaviour exactly; everything here is new and opt-in.

A scene definition lists any number of *subjects* (a COCO cutout composited on
the wall colour and hung on a flat panel), plus occluders, primitive clutter, a
lighting variant and a room. Every subject body is named `subj_<something>`,
which is also its key in the simulator's ground-truth log (see
patch_crazysim.py and CRAZYSIM_TRUTH_PREFIX).

Outputs, per scene, under <out>/<scene_id>/:

    scene.xml       MJCF: room + lighting + every subject / occluder / clutter body
    manifest.json   the ground-truth contract (subjects, roles, COCO ids, motion)
    motion.json     only if a subject uses scripted `drift`; read by the patched
                    simulator via CRAZYSIM_SCENE_MOTION
    subj_*.png      one cutout per subject
    preview.png     --preview: contact sheet of what the drone camera sees
    probe.json      --preview: model confidence per preview viewpoint

Motion primitives and how each is actually realised in the simulator:

  static  no joint.
  spring  pure MJCF: an undamped slide joint, stiffness=(2*pi/T)^2 on a 1 kg
          body with tiny inertia, springref=amp. This is the mechanism
          build_person_scene.py already uses and the Sep 10 baselines were
          flown with. p(t) = p0 - amp*cos(2*pi*t/T).
  drift   a free (stiffness 0, damping 0) slide joint that the *patched*
          simulator drives kinematically once per physics step from motion.json
          (patch_crazysim.py, CRAZYSIM_SCENE_MOTION). Constant velocity with a
          start time and end stops. MJCF alone cannot express this: MuJoCo has
          no way to give a joint an initial velocity outside a <keyframe>, and
          keyframes do not survive CrazySim's MjSpec drone attach.

Whichever primitive is used, the manifest's `motion` block is *intent*. The
realised path must be read from the simulator's truth log, never assumed.

Run with the trainenv python (pycocotools, mujoco, PIL, numpy; torch only for
--preview's model probe).

Usage:
    build_scene.py --all [--preview] [--check]
    build_scene.py --def scene_defs/s03_pets_only.json --preview
    build_scene.py --all --check          # verify COCO ids + cutouts, build nothing
"""
import argparse
import hashlib
import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = Path(__file__).resolve().parent
DRONE_ROOT = HERE.parents[2]
DEF_DIR = HERE / "scene_defs"
OUT_DIR = HERE / "scenes_v2"

# --- room, inherited unchanged from build_person_scene.py -------------------
WALL_RGB = (158, 158, 168)          # cutout compositing colour ABOVE the horizon
# CALIBRATED, not measured. The floor as rendered reads (114, 148, 185) and is
# stable with viewpoint (luma 142.0 / 143.2 / 142.7 at 2.5 / 2.0 / 1.5 m), but
# painting that value into the texture does NOT make the panel match the floor:
# the texture is re-lit when the panel is rendered, and a vertical panel shades
# differently from a horizontal floor, so the naive value left a +26 DN step.
# This value is the one whose RENDERED panel matches the RENDERED floor, found
# by sweeping and measuring the edge step on a tall subject (s01 person, mostly
# wall-backed) and a short one (s03 dog, almost entirely floor-backed):
#
#   (114,148,185) -> s01 +25.89 DN, dog +28.01      (the naive value)
#   ( 92,119,149) -> s01  +7.16 DN, dog  +4.25
#   ( 86,111,139) -> s01  +1.66 DN, dog  -2.75      <- chosen
#   ( 80,104,130) -> s01  -3.44 DN, dog  -8.97
#
# The wall-side step is unaffected by this constant (-2.90 to -3.04 DN across
# the whole sweep), which is the control that says the sweep moved only what it
# was supposed to move. Calibrated under the "default" lighting variant.
FLOOR_RGB = (86, 111, 139)
# Reference range at which the floor/wall split is baked into a cutout. The
# split moves only ~0.09 m over the whole operating range, so one reference is
# enough; 2.5 m is roughly where the follower actually holds station.
BG_REF_RANGE_M = 2.5
ROOM = {"far_x": 7.0, "back_x": -3.0, "left_y": 6.0, "right_y": -6.0, "height": 2.0}
DRONE_START = (0.0, 0.0)
FLIGHT_HEIGHT = 0.8

# --- camera / model geometry (see spec_scenes.md 4.2) -----------------------
FRAME_W, FRAME_H = 324, 244
FOVY_DEG = 70.0
FOCAL_PX = (FRAME_H / 2) / math.tan(math.radians(FOVY_DEG / 2))   # 174.23
MODEL_HALF_FOV = math.degrees(math.atan((FRAME_H / 2) / FOCAL_PX))  # 35.0
RAW_HALF_FOV = math.degrees(math.atan((FRAME_W / 2) / FOCAL_PX))    # 42.9

AXIS_VEC = {"x": "1 0 0", "y": "0 1 0", "z": "0 0 1"}
AXIS_IDX = {"x": 0, "y": 1, "z": 2}

ROLES = {"person_target", "person_distractor", "nonperson_distractor", "clutter"}


# ---------------------------------------------------------------------------
# lighting variants
# ---------------------------------------------------------------------------
def lighting_block(variant: str):
    """Return (visual_xml, lights_xml, extra_asset_xml, far_wall_material, manifest)."""
    if variant == "default":
        visual = ('    <headlight diffuse="0.6 0.6 0.6" ambient="0.5 0.5 0.5" specular="0 0 0"/>\n'
                  '    <global azimuth="0" elevation="-20" ellipsoidinertia="true"/>')
        lights = ('    <light pos="0 0 3" dir="0 0 -1" directional="true"/>\n'
                  '    <light pos="-1 0 2" dir="1 0 -0.3" directional="true" diffuse="0.5 0.5 0.5"/>')
        return visual, lights, "", "wall", {
            "variant": "default",
            "headlight": {"diffuse": 0.6, "ambient": 0.5},
            "lights": [{"pos": [0, 0, 3], "dir": [0, 0, -1], "diffuse": 1.0, "directional": True},
                       {"pos": [-1, 0, 2], "dir": [1, 0, -0.3], "diffuse": 0.5, "directional": True}],
            "fidelity_notes": ["matches build_person_scene.py, i.e. the Sep 10 baselines"],
        }
    if variant == "dim":
        # A dim ROOM that still carries tonal structure, not a black frame.
        #
        # This used to be the scene_dark.xml recipe (no headlight, one 0.02
        # fill light). Measured, that rendered at mean 1.15 DN with a max of 2
        # and exactly THREE distinct 8-bit levels in the whole frame, and a
        # subject-vs-background contrast of -0.5 DN. Because the renderer
        # quantises to 8 bits before camera_model.py ever sees the frame, no
        # sensor preset could recover anything from it: himax_typical drove the
        # AE to its 340-line / 8x / 3.00x ceiling and returned amplified
        # quantisation (mean 25 DN), and himax_low_light returned mean 5 DN.
        # It could not test dim-room perception because there was nothing left
        # to perceive.
        #
        # The levels below render at mean ~43 DN with ~89 distinct levels and
        # 0% saturation, so the frame still holds real scene structure, and the
        # dim-room PHYSICS is supplied where it belongs - by the sensor model,
        # which still drives 24x total gain on this scene under himax_low_light.
        visual = ('    <headlight diffuse="0.15 0.15 0.15" ambient="0.12 0.12 0.12" specular="0 0 0"/>\n'
                  '    <rgba haze="0 0 0 0" fog="0 0 0 0"/>\n'
                  '    <global azimuth="0" elevation="-20" ellipsoidinertia="true"/>')
        lights = ('    <light pos="0 0 3" dir="0 0 -1" directional="true" castshadow="false"\n'
                  '           diffuse="0.3 0.3 0.375" specular="0 0 0" ambient="0.08 0.08 0.08"/>')
        return visual, lights, "", "wall", {
            "variant": "dim",
            "headlight": {"diffuse": 0.15, "ambient": 0.12},
            "lights": [{"pos": [0, 0, 3], "dir": [0, 0, -1], "diffuse": 0.3, "directional": True}],
            "measured_render": {"frame_mean_dn": 42.9, "distinct_levels": 89,
                                "saturated_fraction": 0.0,
                                "note": "s01 geometry, drone eye line, camera 2.5 m from the panel"},
            "fidelity_notes": [
                "This is a dim ROOM: the render keeps real tonal structure (~43 DN mean, "
                "~89 distinct levels) and the sensor model supplies the low-light physics "
                "(himax_low_light drives ~24x total gain here).",
                "It is no longer the near-black DARK FRAME test it used to be. The old "
                "levels rendered 3 distinct grey levels and -0.5 DN of subject contrast, "
                "which no auto-exposure can recover; for a sensor-failure test use the "
                "camera-freeze path in run_acceptance.sh instead.",
                "Subject-vs-background contrast is low (~+0.6 DN) because a flat-lit photo "
                "panel is close in tone to the wall behind it; the information the model "
                "gets here is shape and texture, not brightness.",
            ],
        }
    if variant == "backlit":
        # Silhouette: the far wall is made emissive so it reads as a bright
        # window/wall behind the subject, ambient and headlight are cut so the
        # subject's camera-facing side stays dark, and one directional light
        # travelling along -x rims the subject from behind.
        visual = ('    <headlight diffuse="0.15 0.15 0.15" ambient="0.10 0.10 0.10" specular="0 0 0"/>\n'
                  '    <global azimuth="0" elevation="-20" ellipsoidinertia="true"/>')
        lights = ('    <light pos="6.0 0 1.6" dir="-1 0 -0.1" directional="true" diffuse="1.0 1.0 1.0"/>')
        asset = '    <material name="wall_bright" rgba="0.85 0.85 0.88 1" emission="0.85"/>\n'
        return visual, lights, asset, "wall_bright", {
            "variant": "backlit",
            "headlight": {"diffuse": 0.15, "ambient": 0.10},
            "lights": [{"pos": [6.0, 0, 1.6], "dir": [-1, 0, -0.1], "diffuse": 1.0, "directional": True}],
            "far_wall_emission": 0.85,
            "fidelity_notes": [
                "Backlight is modelled as an emissive far wall plus a rim light, not as a "
                "real window luminance; there is no auto-exposure in the simulator, so this "
                "tests contrast handling, not the AE loop's response to a bright background.",
            ],
        }
    raise SystemExit(f"unknown lighting variant {variant!r} (default | dim | backlit)")


# ---------------------------------------------------------------------------
# cutouts
# ---------------------------------------------------------------------------
def load_coco(coco_root: Path):
    from pycocotools.coco import COCO
    return COCO(str(coco_root / "annotations/instances_val2017.json"))


def cutout_stats(coco, img_id: int, ann_id: int):
    """Validate one COCO reference and report what the cutout will contain."""
    out = {"img_id": img_id, "ann_id": ann_id, "ok": False, "problems": []}
    try:
        ann = coco.loadAnns(ann_id)[0]
    except Exception:
        out["problems"].append(f"annotation {ann_id} not in instances_val2017.json")
        return out
    if ann["image_id"] != img_id:
        out["problems"].append(f"annotation {ann_id} belongs to image {ann['image_id']}, not {img_id}")
    info = coco.loadImgs(img_id)[0]
    cats = {c["id"]: c["name"] for c in coco.loadCats(coco.getCatIds())}
    out["category"] = cats.get(ann["category_id"], "?")
    out["file_name"] = info["file_name"]
    out["bbox_xywh"] = [round(float(v), 1) for v in ann["bbox"]]
    x, y, w, h = ann["bbox"]
    if w < 2 or h < 2:
        out["problems"].append(f"degenerate bbox {out['bbox_xywh']}")
    mask = coco.annToMask(ann)
    out["mask_px"] = int(mask.sum())
    if out["mask_px"] <= 0:
        out["problems"].append("segmentation mask is empty")
    # fraction of the crop that is actually subject: a near-zero value means the
    # panel would be almost entirely wall colour.
    xi, yi, wi, hi = [int(round(v)) for v in ann["bbox"]]
    sub = mask[yi:yi + hi, xi:xi + wi]
    out["fill_fraction"] = round(float(sub.mean()), 4) if sub.size else 0.0
    if out["fill_fraction"] < 0.02:
        out["problems"].append(f"cutout is {out['fill_fraction']:.1%} subject: effectively empty")
    out["n_person_anns_in_image"] = len(
        [a for a in coco.loadAnns(coco.getAnnIds(imgIds=img_id)) if a["category_id"] == 1])
    out["aspect"] = round(float(w) / float(h), 4)
    jpg = coco.dataset and True
    out["ok"] = not out["problems"]
    return out


def horizon_split_z(subject_x: float, ref_range_m: float = BG_REF_RANGE_M) -> float:
    """World height at which the background behind a panel changes floor -> wall.

    The drone's eye line is at FLIGHT_HEIGHT. A ray leaving it through a point
    on the panel at height ``z`` keeps going; it lands on the floor before the
    far wall when ``z`` is low enough, and on the far wall when it is not. With
    the camera ``ref_range_m`` in front of a panel at ``subject_x``,

        K   = (far_x - cam_x) / (subject_x - cam_x)
        z*  = FLIGHT_HEIGHT * (1 - 1/K)

    For the control scene (panel at x=3.0, camera 2.5 m back) this gives
    0.492 m, and a render of that scene puts the floor/wall boundary behind the
    panel at 0.475 m - so the formula is honest to ~17 mm.
    """
    cam_x = subject_x - ref_range_m
    denom = subject_x - cam_x
    if denom <= 1e-6:
        return 0.0
    K = (ROOM["far_x"] - cam_x) / denom
    if K <= 1.0:
        return 0.0
    return FLIGHT_HEIGHT * (1.0 - 1.0 / K)


def panel_background(height_px: int, width_px: int, subject_height_m: float,
                     subject_x: float) -> np.ndarray:
    """The two-tone background a panel is composited onto.

    MuJoCo cannot give the panel real transparency (see BACKGROUND FIDELITY in
    make_cutout), so the flat card is at least painted with what is genuinely
    behind it: wall colour above the horizon, floor colour below. The panel
    spans world z from 0 to ``subject_height_m`` and texture row 0 is its top
    (verified by rendering a marked texture), so

        z(row) = subject_height_m * (1 - row / (height_px - 1))

    A short blend across the boundary avoids trading one hard edge for another.
    """
    z_star = horizon_split_z(subject_x)
    rows = np.arange(height_px, dtype=np.float32)
    z = subject_height_m * (1.0 - rows / max(height_px - 1, 1))
    blend_m = max(subject_height_m * 0.02, 0.01)
    t = np.clip((z_star - z) / blend_m, 0.0, 1.0)[:, None]      # 1 = floor, 0 = wall
    bg = (np.array(WALL_RGB, np.float32)[None, :] * (1.0 - t)
          + np.array(FLOOR_RGB, np.float32)[None, :] * t)
    return np.repeat(bg[:, None, :], width_px, axis=1)


def sample_panel_backgrounds(scene_xml: Path, subjects, n_rows: int = 64):
    """Render the scene and measure what is really behind each subject panel.

    The two-tone model (wall above the horizon, floor below) is only right for
    an on-axis, person-height subject. Measured across the suite it left up to
    +35 DN on the furniture scene and did nothing for the wall side, because the
    background behind a panel is not one tone at all - behind the s15 person it
    runs 125.9 to 255.0 DN, saturating against the over-exposed far wall - and
    because a panel does not shade like the surface behind it.

    So the background is measured instead of modelled, in two steps per subject:

    1. Hide that subject's panel, re-render, and take the median colour of each
       image row across the panel's own column span. That is the background,
       whatever it happens to be: far wall, side wall, floor, or another object.
    2. Divide by ``k``, the panel's own shading factor, measured on the panel in
       the first-pass render: the rows whose texture is known flat ``WALL_RGB``
       are compared against ``WALL_RGB`` itself. ``k`` is genuinely per subject
       (measured 0.886 to 1.387 across the suite - the TV panel sits below 1.0),
       which is exactly why one global constant could not work.

    Returns ``{subject_name: {"profile": (n_rows, 3) top-to-bottom, "k": float}}``.
    Subjects that are not visible from the reference viewpoint are omitted and
    keep the two-tone fallback.
    """
    import mujoco
    spec = mujoco.MjSpec.from_file(str(scene_xml))
    cam = spec.worldbody.add_camera()
    cam.name, cam.fovy = "bg_cam", FOVY_DEG
    cam.alt.type = mujoco.mjtOrientation.mjORIENTATION_XYAXES
    cam.alt.xyaxes = [0, -1, 0, 0, 0, 1]
    m = spec.compile()
    d = mujoco.MjData(m)
    for s_ in subjects:                       # declared position, as --preview uses
        mo = s_.get("motion") or {}
        if mo.get("type") == "spring":
            jid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_JOINT, f"sway_{s_['name']}")
            if jid >= 0:
                d.qpos[m.jnt_qposadr[jid]] = float(mo["amp_m"])
    primary = next((x for x in subjects if x.get("role") == "person_target"), subjects[0])
    cam_x = float(primary["pos"][0]) - BG_REF_RANGE_M
    cid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_CAMERA, "bg_cam")
    m.cam_pos[cid] = [cam_x, 0.0, FLIGHT_HEIGHT]
    mujoco.mj_forward(m, d)

    r = mujoco.Renderer(m, FRAME_H, FRAME_W)
    r.update_scene(d, camera="bg_cam")
    first = r.render().astype(np.float32)
    r.enable_segmentation_rendering()
    r.update_scene(d, camera="bg_cam")
    seg = r.render()[..., 0]
    r.disable_segmentation_rendering()

    lum = np.array([0.2989, 0.5870, 0.1140], np.float32)
    out = {}
    for s_ in subjects:
        name = s_["name"]
        gid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_GEOM, f"{name}_panel")
        if gid < 0:
            continue
        mask = (seg == gid)
        if mask.sum() < 50:
            continue
        rws = np.where(mask.any(1))[0]
        cols = np.where(mask.any(0))[0]
        top, bot = int(rws.min()), int(rws.max())

        # k from the panel's flat-painted rows (wall first, then floor).
        tex = np.asarray(Image.open(scene_xml.parent / f"{name}.png").convert("RGB")).astype(np.float32)
        k = None
        for ref in (WALL_RGB, FLOOR_RGB):
            flat_rows = (np.abs(tex - np.array(ref, np.float32)).sum(2) <= 12)
            sel = [ir for ir in rws
                   if flat_rows[int(np.clip((ir - top) / max(bot - top, 1) * (tex.shape[0] - 1),
                                            0, tex.shape[0] - 1))].mean() > 0.6]
            if len(sel) >= 5:
                panel_lum = float(np.mean([float(first[ir][mask[ir]].mean(0) @ lum) for ir in sel]))
                k = panel_lum / float(np.array(ref, np.float32) @ lum)
                break
        if not k or not (0.2 < k < 5.0):
            k = 1.30                                  # suite median, if unmeasurable

        # background behind this panel, with the panel hidden
        keep = m.geom_rgba[gid].copy()
        m.geom_rgba[gid] = [0, 0, 0, 0]
        mujoco.mj_forward(m, d)
        r.update_scene(d, camera="bg_cam")
        back = r.render().astype(np.float32)
        m.geom_rgba[gid] = keep

        rows = np.array([np.median(back[ir, cols.min():cols.max() + 1], axis=0) for ir in rws])
        src = np.linspace(0.0, 1.0, len(rows))
        dst = np.linspace(0.0, 1.0, n_rows)
        prof = np.stack([np.interp(dst, src, rows[:, c]) for c in range(3)], axis=1)
        out[name] = {"profile": np.clip(prof / k, 0.0, 255.0), "k": round(float(k), 4)}
    return out


def make_cutout(coco, coco_root: Path, img_id: int, ann_id: int, out_png: Path,
                flip: str = "", bg=None, subject_height_m: float = 1.7,
                subject_x: float = 3.0, bg_profile=None) -> float:
    """Masked COCO cutout composited on the background that is actually behind it.

    BACKGROUND FIDELITY - what this does and does not achieve.

    The subject is a photo on a flat rectangular panel, and the whole panel is
    opaque: everything outside the COCO mask is painted background, not
    transparent. That is forced by the renderer, not chosen. MuJoCo 3.13 drops
    the alpha channel when it loads a PNG (``tex_nchannel`` comes back 3 for an
    RGBA file), so a cutout with an alpha mask renders its transparent texels
    as opaque colour; and a mask-shaped mesh is not a way out either - a flat
    silhouette fails to compile ("coplanar vertices, cannot compute convex
    hull") and an extruded one rendered zero pixels. All three routes were
    tried and measured before falling back to this.

    So the card cannot be removed, but it can be made to match its
    surroundings. Instead of one flat wall colour everywhere - which left the
    lower third of every subject as a bright rectangle standing on a dark floor
    - the background is now two-tone: wall above the horizon, floor below, with
    the split derived per subject from the room geometry (``horizon_split_z``).

    The residual, stated rather than hidden: the floor is a checkerboard whose
    luma swings about +/- 24 DN around its mean, so individual squares still
    differ from the flat floor colour, and the split is baked at one reference
    range (it moves ~0.09 m of panel height across the operating range). What
    is fixed is the systematic step; what remains is texture.
    """
    info = coco.loadImgs(img_id)[0]
    ann = coco.loadAnns(ann_id)[0]
    rgb = np.asarray(Image.open(coco_root / "images/val2017" / info["file_name"]).convert("RGB"))
    mask = coco.annToMask(ann).astype(np.uint8) * 255
    x, y, w, h = [int(round(v)) for v in ann["bbox"]]
    m = Image.fromarray(mask).filter(ImageFilter.MinFilter(5))          # erode edge halo
    m = np.asarray(m.filter(ImageFilter.GaussianBlur(1)), np.float32)[..., None] / 255.0
    sub_rgb = rgb.astype(np.float32)[y:y + h, x:x + w]
    sub_m = m[y:y + h, x:x + w]
    if bg is None and bg_profile is None:
        bg = WALL_RGB                      # today's behaviour, and the default
    if bg_profile is not None:
        # Measured background: one colour per panel row, top to bottom, already
        # divided by the panel's own shading factor (see sample_panel_backgrounds).
        prof = np.asarray(bg_profile, np.float32)
        v = np.linspace(0.0, len(prof) - 1.0, sub_rgb.shape[0])
        rows = np.stack([np.interp(v, np.arange(len(prof)), prof[:, c]) for c in range(3)], axis=1)
        back = np.repeat(rows[:, None, :], sub_rgb.shape[1], axis=1)
    elif bg is None:
        back = panel_background(sub_rgb.shape[0], sub_rgb.shape[1], float(subject_height_m),
                                float(subject_x))
    else:
        back = np.broadcast_to(np.array(bg, np.float32), sub_rgb.shape).copy()
    comp = sub_rgb * sub_m + back * (1 - sub_m)
    img = Image.fromarray(comp.astype(np.uint8), "RGB")
    if "h" in flip:
        img = img.transpose(Image.FLIP_LEFT_RIGHT)
    if "v" in flip:
        img = img.transpose(Image.FLIP_TOP_BOTTOM)
    img = img.resize((max(1, int(img.width * 512 / img.height)), 512), Image.LANCZOS)
    out_png.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_png)
    return img.width / img.height


# ---------------------------------------------------------------------------
# XML
# ---------------------------------------------------------------------------
def subject_body_xml(s, aspect, drives):
    """MJCF for one subject panel, plus any entry it needs in motion.json."""
    name = s["name"]
    h = float(s["height_m"])
    w = h * aspect
    px, py = float(s["pos"][0]), float(s["pos"][1])
    pz = float(s.get("z_center_m", h / 2))
    mot = s.get("motion", {"type": "static"})
    mtype = mot.get("type", "static")
    joint = ""
    law = "p(t) = p0 (static)"
    mech = "none"

    if mtype == "static":
        pass
    elif mtype == "spring":
        axis = mot.get("axis", "y")
        amp = float(mot["amp_m"])
        period = float(mot["period_s"])
        k = 1.0 * (2 * math.pi / period) ** 2                    # mass 1 kg
        joint = (f'      <joint name="sway_{name}" type="slide" axis="{AXIS_VEC[axis]}" '
                 f'stiffness="{k:.5f}" springref="{amp:.4f}" damping="0"/>\n')
        # body is offset by -amp so the swing is centred on the declared position
        if axis == "x":
            px -= amp
        elif axis == "y":
            py -= amp
        else:
            pz -= amp
        c = {"x": px, "y": py, "z": pz}[axis] + amp
        law = f"{axis}(t) = {c:.4f} - {amp:.4f}*cos(2*pi*t/{period:g})"
        mech = "mjcf_spring"
    elif mtype == "drift":
        axis = mot.get("axis", "y")
        v = float(mot["v_mps"])
        t0 = float(mot.get("t_start_s", 0.0))
        p0a = {"x": px, "y": py, "z": pz}[axis]
        lo = mot.get("min_m")
        hi = mot.get("max_m")
        joint = (f'      <joint name="drive_{name}" type="slide" axis="{AXIS_VEC[axis]}" '
                 f'stiffness="0" damping="0"/>\n')
        drives.append({
            "joint": f"drive_{name}", "body": name, "axis": axis, "q0": 0.0, "v": v,
            "t_start": t0,
            "lo": None if lo is None else float(lo) - p0a,
            "hi": None if hi is None else float(hi) - p0a,
        })
        rng = ""
        if lo is not None or hi is not None:
            rng = f", clamped to [{lo if lo is not None else '-inf'}, {hi if hi is not None else '+inf'}]"
        law = f"{axis}(t) = {p0a:.4f} + {v:g}*max(0, t - {t0:g}){rng}"
        mech = "patched_sim_kinematic_drive"
    else:
        raise SystemExit(f"{name}: unknown motion type {mtype!r} (static | spring | drift)")

    body = (f'    <body name="{name}" pos="{px:.4f} {py:.4f} {pz:.4f}">\n'
            f'{joint}'
            f'      <!-- Tiny inertia on purpose: the scene enables MuJoCo\'s air model\n'
            f'           (density/viscosity), whose drag scales with the box implied by the\n'
            f'           inertia. Tiny inertia keeps spring motion close to the ideal law. -->\n'
            f'      <inertial pos="0 0 0" mass="1" diaginertia="1e-4 1e-4 1e-4"/>\n'
            f'      <geom name="{name}_panel" type="box" size="0.004 {w / 2:.4f} {h / 2:.4f}" '
            f'euler="{s.get("euler", "0 0 0")}" material="mat_{name}" contype="0" conaffinity="0"/>\n'
            f'    </body>\n')
    motion = {"type": mtype, "axis": mot.get("axis", "y") if mtype != "static" else None,
              "p0": [float(s["pos"][0]), float(s["pos"][1])], "law": law,
              "mechanism": mech}
    motion.update({k: v for k, v in mot.items() if k != "type"})
    return body, motion, {"height_m": h, "width_m": round(w, 4), "aspect": round(aspect, 4),
                          "euler": s.get("euler", "0 0 0"), "flip": s.get("flip", ""),
                          "z_center_m": round(float(s.get("z_center_m", h / 2)), 4)}


def build_xml(d, subj_xml, extra_assets, far_wall_mat, visual, lights):
    tex = "".join(
        f'    <texture type="2d" name="tex_{s["name"]}" file="{s["name"]}.png"/>\n'
        f'    <material name="mat_{s["name"]}" texture="tex_{s["name"]}" rgba="1 1 1 1"/>\n'
        for s in d["subjects"])
    occ = "".join(
        f'    <geom name="{o["name"]}" type="box" size="{o["half_extents"][0]:g} '
        f'{o["half_extents"][1]:g} {o["half_extents"][2]:g}" '
        f'pos="{o["center"][0]:g} {o["center"][1]:g} {o["center"][2]:g}" '
        f'material="wall" contype="0" conaffinity="0"/>\n'
        for o in d.get("occluders", []))
    prim = ""
    for c in d.get("clutter_primitives", []):
        size = " ".join(f"{v:g}" for v in c["size"])
        pos = " ".join(f"{v:g}" for v in c["pos"])
        prim += (f'    <geom name="{c["name"]}" type="{c.get("type", "box")}" size="{size}" '
                 f'pos="{pos}" material="{c.get("material", "obstacle")}" '
                 f'contype="0" conaffinity="0"/>\n')
    r = ROOM
    sky = ('0.01 0.01 0.02' if d.get("lighting", "default") == "dim" else '0.3 0.5 0.7')
    return f"""<mujoco model="{d['scene_id']}">
  <!-- Generated by build_scene.py from scene_defs/{d['scene_id']}.json - do not edit by hand. -->
  <option integrator="RK4" density="1.225" viscosity="1.8e-5" timestep="0.001"/>
  <compiler inertiafromgeom="false" autolimits="true"/>
  <statistic center="1 0 1" extent="3"/>
  <visual>
{visual}
  </visual>
  <asset>
    <texture type="skybox" builtin="gradient" rgb1="{sky}" rgb2="0 0 0" width="512" height="3072"/>
    <texture type="2d" name="groundplane" builtin="checker" mark="edge" rgb1="0.2 0.3 0.4"
             rgb2="0.1 0.2 0.3" markrgb="0.8 0.8 0.8" width="512" height="512"/>
    <material name="groundplane" texture="groundplane" texuniform="true" texrepeat="2 2" reflectance="0.2"/>
    <material name="wall" rgba="0.62 0.62 0.66 1"/>
    <material name="pillar" rgba="0.5 0.35 0.25 1"/>
    <material name="obstacle" rgba="0.4 0.5 0.4 1"/>
{extra_assets}{tex}  </asset>
  <worldbody>
{lights}
    <geom name="floor" size="0 0 0.05" type="plane" material="groundplane"/>
    <geom name="wall_far"   type="box" size="0.05 {r['left_y']:g} {r['height']:g}" pos="{r['far_x']:g} 0 {r['height']:g}"  material="{far_wall_mat}"/>
    <geom name="wall_back"  type="box" size="0.05 {r['left_y']:g} {r['height']:g}" pos="{r['back_x']:g} 0 {r['height']:g}" material="wall"/>
    <geom name="wall_left"  type="box" size="5 0.05 {r['height']:g}" pos="2 {r['left_y']:g} {r['height']:g}"  material="wall"/>
    <geom name="wall_right" type="box" size="5 0.05 {r['height']:g}" pos="2 {r['right_y']:g} {r['height']:g}" material="wall"/>
{occ}{prim}{subj_xml}  </worldbody>
</mujoco>
"""


# ---------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------
def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(d, coco, coco_root: Path, out_root: Path, argv, background_mode: str = "flat"):
    out = out_root / d["scene_id"]
    out.mkdir(parents=True, exist_ok=True)
    visual, lights, extra_assets, far_wall_mat, light_manifest = lighting_block(d.get("lighting", "default"))

    subj_xml, drives, subjects = "", [], []
    for s in d["subjects"]:
        if not s["name"].startswith("subj_"):
            raise SystemExit(f"subject {s['name']!r} must start with 'subj_' (truth-log prefix)")
        if s.get("role") not in ROLES:
            raise SystemExit(f"{s['name']}: role must be one of {sorted(ROLES)}")
        png = out / f"{s['name']}.png"
        c = s["coco"]
        aspect = make_cutout(coco, coco_root, c["img_id"], c["ann_id"], png, s.get("flip", ""),
                             subject_height_m=float(s["height_m"]),
                             subject_x=float(s["pos"][0]))
        body, motion, panel = subject_body_xml(s, aspect, drives)
        subj_xml += body
        info = coco.loadImgs(c["img_id"])[0]
        ann = coco.loadAnns(c["ann_id"])[0]
        cats = {x["id"]: x["name"] for x in coco.loadCats(coco.getCatIds())}
        mk = coco.annToMask(ann)
        xi, yi, wi, hi = [int(round(v)) for v in ann["bbox"]]
        sub_mask = mk[yi:yi + hi, xi:xi + wi]
        fill = float(sub_mask.mean()) if sub_mask.size else 0.0
        subjects.append({
            "name": s["name"],
            "role": s["role"],
            "source": {"kind": "coco_val2017", "img_id": c["img_id"], "ann_id": c["ann_id"],
                       "category": cats.get(ann["category_id"], "?"), "file_name": info["file_name"],
                       "bbox_xywh": [round(float(v), 1) for v in ann["bbox"]]},
            "panel": panel,
            "background": {
                "mode": "flat_wall_rgb",
                "wall_rgb": list(WALL_RGB),
                "subject_fraction": round(fill, 4),
                "fidelity_notes": [
                    "THIS PANEL IS AN OPAQUE RECTANGULAR CARD. Everything outside the COCO "
                    "mask is painted flat wall colour, not transparency, so the network sees a "
                    "rectangle as well as a subject. That is a renderer limit, not a choice: "
                    "MuJoCo 3.13 drops the alpha channel when loading a PNG (tex_nchannel "
                    "returns 3 for an RGBA file), a flat mask-shaped mesh fails to compile "
                    "(coplanar vertices), and an extruded one rendered zero pixels.",
                    "The card is visible against the floor. Measured at the drone eye line "
                    "2.5 m out, the edge step is about +40 to +108 DN against the floor and "
                    "-113 to +59 DN against the wall, depending on the subject.",
                    "A background-matching composite was built and measured (--background "
                    "sampled) but is NOT the default: it did not reach the ~5 DN target away "
                    "from people and pets, and it moved detection outputs (s16 furniture "
                    "confidence 0.755 -> 0.957, s01 size bucket 0.625 -> 0.375 at 3.5 m), "
                    "which would silently change the acceptance results it is supposed to "
                    "make more realistic.",
                ],
            },
            "motion": motion,
            "truth": {"source": "sim_truth_log", "body": s["name"],
                      "fallback_static": list(s["pos"]) if motion["type"] == "static" else None},
            "note": s.get("note", ""),
        })

    xml = build_xml(d, subj_xml, extra_assets, far_wall_mat, visual, lights)
    scene_path = out / "scene.xml"
    scene_path.write_text(xml)

    # --- pass 2: measure the background behind each panel and repaint -------
    # Needs a compiled scene, so it cannot happen while the cutouts are first
    # written. The cutouts are rewritten in place; the XML is unchanged, and the
    # manifest's asset_sha256 is computed after this, so it records the final PNG.
    bg_info = {}
    if background_mode == "sampled":
        try:
            bg_info = sample_panel_backgrounds(scene_path, d["subjects"])
        except Exception as e:
            print(f"  (background sampling unavailable: {e!r}; flat background kept)")
            bg_info = {}
    lum = np.array([0.2989, 0.5870, 0.1140], np.float32)
    for s in d["subjects"]:
        got = bg_info.get(s["name"])
        if not got:
            continue
        c = s["coco"]
        make_cutout(coco, coco_root, c["img_id"], c["ann_id"], out / f"{s['name']}.png",
                    s.get("flip", ""), subject_height_m=float(s["height_m"]),
                    subject_x=float(s["pos"][0]), bg_profile=got["profile"])
        L = got["profile"] @ lum
        entry = next(x for x in subjects if x["name"] == s["name"])
        entry["background"] = {
            "mode": "sampled_per_row_measured",
            "shading_factor_k": got["k"],
            "reference_range_m": BG_REF_RANGE_M,
            "texture_luma_dn": {"min": round(float(L.min()), 1),
                                "max": round(float(L.max()), 1),
                                "mean": round(float(L.mean()), 1)},
            "subject_fraction": entry["background"].get("subject_fraction"),
            "fidelity_notes": [
                "THIS PANEL IS AN OPAQUE RECTANGULAR CARD. Everything outside the COCO mask "
                "is painted background, not transparency. MuJoCo 3.13 drops the alpha channel "
                "when loading a PNG (tex_nchannel returns 3 for an RGBA file), and a "
                "mask-shaped mesh is not an alternative (a flat silhouette fails to compile - "
                "coplanar vertices - and an extruded one rendered zero pixels). All three "
                "routes were tried and measured.",
                "The card cannot be removed, so it is camouflaged instead: the background is "
                "MEASURED by hiding this panel, re-rendering, and taking the median colour of "
                "each image row behind it, then dividing by this panel's own shading factor k "
                "(a panel does not shade like the surface behind it, and k is per subject - "
                "0.886 to 1.387 across the suite).",
                "Residual: the background is sampled at one reference range and one viewpoint, "
                "so parallax as the drone closes will reveal some mismatch; fine floor "
                "checkerboard texture is replaced by its per-row median rather than reproduced; "
                "and where the render is saturated behind the panel the match is limited by "
                "what the renderer clipped.",
            ],
        }

    motion_path = out / "motion.json"
    if drives:
        motion_path.write_text(json.dumps(drives, indent=2) + "\n")
    elif motion_path.exists():
        motion_path.unlink()

    # compile it: a scene that does not load is not a scene
    import mujoco
    m = mujoco.MjSpec.from_file(str(scene_path)).compile()
    bodies = [mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_BODY, i) for i in range(m.nbody)]
    missing = [s["name"] for s in subjects if s["name"] not in bodies]
    if missing:
        raise SystemExit(f"{d['scene_id']}: compiled model is missing bodies {missing}")

    manifest = {
        "schema_version": 1,
        "scene_id": d["scene_id"],
        "title": d.get("title", ""),
        "purpose": d.get("purpose", ""),
        "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "builder": {
            "script": "build_scene.py",
            "argv": argv,
            "scene_def": f"scene_defs/{d['scene_id']}.json",
            "coco_root": str(coco_root),
            "scene_xml_sha256": sha256(scene_path),
            "asset_sha256": {f"{s['name']}.png": sha256(out / f"{s['name']}.png") for s in subjects},
        },
        "room": {"template": "person_room_v1", "walls": ROOM, "wall_rgb": list(WALL_RGB),
                 "drone_start": list(DRONE_START), "flight_height_m": FLIGHT_HEIGHT},
        "lighting": light_manifest,
        "camera": {"frame_wh": [FRAME_W, FRAME_H], "fovy_deg": FOVY_DEG,
                   "focal_px": round(FOCAL_PX, 2), "crop": "center 244x244 -> 128x128",
                   "model_half_fov_deg": round(MODEL_HALF_FOV, 1),
                   "raw_half_fov_deg": round(RAW_HALF_FOV, 1),
                   "bearing_from_x": "atan(x * tan(35 deg))"},
        "truth_log": {
            "env": {"CRAZYSIM_TRUTH_LOG": "<path>", "CRAZYSIM_TRUTH_PREFIX": "subj_"},
            "format": "# bodies: <names>  then  wall_time,sim_time,(x,y,z per body)",
            "bodies_in_order": [s["name"] for s in subjects],
        },
        "scripted_motion": {
            "env": {"CRAZYSIM_SCENE_MOTION": "motion.json"} if drives else None,
            "drives": drives,
            "note": ("Scripted drift is driven kinematically by the patched simulator once per "
                     "physics step; spring motion is pure MJCF. Both are intent: score the "
                     "realised path from the truth log." if drives else
                     "No scripted drive; motion is MJCF-only."),
        },
        "subjects": subjects,
        "occluders": [dict(o, opaque=True, type="box") for o in d.get("occluders", [])],
        "clutter_primitives": d.get("clutter_primitives", []),
        "expected_behaviour": d.get("expected_behaviour", {}),
        "prediction": d.get("prediction", {}),
        "limitations": d.get("limitations", []) + [
            "Every subject is a flat photograph on a board: no parallax, no limb "
            "articulation, no self-occlusion, no back-turned appearance change.",
            "Each subject panel is an OPAQUE rectangle, not a silhouette - the renderer "
            "cannot give it real transparency (see subjects[].background.fidelity_notes). "
            "The background is painted to match what is behind the panel, which removes the "
            "systematic edge step but not the card itself."],
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return out, manifest


# ---------------------------------------------------------------------------
# preview
# ---------------------------------------------------------------------------
def _font(size=13):
    for p in ("/System/Library/Fonts/Supplemental/Arial.ttf",
              "/System/Library/Fonts/Helvetica.ttc",
              "/Library/Fonts/Arial.ttf"):
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            continue
    return ImageFont.load_default()


def load_model(unstable_root: Path, ckpt: Path):
    import torch
    sys.path.insert(0, str(unstable_root))
    from models.follow_model_factory import build_follow_model_from_checkpoint
    head = torch.load(ckpt, map_location="cpu").get("follow_head_type")
    model = build_follow_model_from_checkpoint(Path(ckpt), torch.device("cpu")).eval()
    return model, head


def run_model(model, head, gray: np.ndarray):
    """Exactly the follower's path: centre square crop -> 128x128 -> model."""
    import torch
    from utils.follow_task import decode_follow_outputs
    s = min(gray.shape)
    y0, x0 = (gray.shape[0] - s) // 2, (gray.shape[1] - s) // 2
    crop = Image.fromarray(gray[y0:y0 + s, x0:x0 + s]).resize((128, 128), Image.BILINEAR)
    x = torch.from_numpy(np.asarray(crop, np.float32) / 255.0)[None, None]
    with torch.no_grad():
        dec = decode_follow_outputs(model(x), head)
    return {k: float(t.reshape(-1)[0]) for k, t in dec.items() if torch.is_tensor(t)}


def preview_qpos(m, d, manifest, t):
    """Put every scripted subject where its own declared law says it is at time t.

    Without this the preview renders at t = 0, where a spring subject sits at
    its swing extreme (p0 - amp) rather than at the position the scene
    definition declares - which made s01's closest tile look empty.
    """
    import mujoco
    applied = []
    for s in manifest["subjects"]:
        mo = s["motion"]
        if mo["type"] == "spring":
            jn = f"sway_{s['name']}"
            amp, per = float(mo["amp_m"]), float(mo["period_s"])
            q = amp * (1.0 - math.cos(2 * math.pi * t / per))
        elif mo["type"] == "drift":
            jn = f"drive_{s['name']}"
            drv = next((x for x in manifest["scripted_motion"]["drives"] if x["joint"] == jn), None)
            if drv is None:
                continue
            q = float(drv["v"]) * max(0.0, t - float(drv["t_start"]))
            if drv["lo"] is not None:
                q = max(q, float(drv["lo"]))
            if drv["hi"] is not None:
                q = min(q, float(drv["hi"]))
        else:
            continue
        jid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_JOINT, jn)
        if jid < 0:
            continue
        d.qpos[m.jnt_qposadr[jid]] = q
        applied.append({"subject": s["name"], "joint": jn, "q_m": round(q, 4)})
    return applied


def default_preview_t(manifest, d):
    """A time at which the scene shows what it is about: a quarter period puts a
    spring subject at its declared centre. Overridable per scene."""
    if d.get("preview_t_s") is not None:
        return float(d["preview_t_s"])
    for s in manifest["subjects"]:
        if s["motion"]["type"] == "spring":
            return float(s["motion"]["period_s"]) / 4.0
    return 0.0


def preview(out: Path, manifest, cam_xs, t_s, a):
    import mujoco
    scene_xml = out / "scene.xml"
    spec = mujoco.MjSpec.from_file(str(scene_xml))
    cam = spec.worldbody.add_camera()
    cam.name, cam.fovy = "preview_cam", FOVY_DEG
    cam.pos = [0.0, 0.0, FLIGHT_HEIGHT]
    # MuJoCo cameras look along -z; image-right = world -y, image-up = world +z.
    cam.alt.type = mujoco.mjtOrientation.mjORIENTATION_XYAXES
    cam.alt.xyaxes = [0, -1, 0, 0, 0, 1]
    m = spec.compile()
    d = mujoco.MjData(m)
    d.time = t_s
    applied = preview_qpos(m, d, manifest, t_s)
    mujoco.mj_forward(m, d)
    r = mujoco.Renderer(m, FRAME_H, FRAME_W)
    cid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_CAMERA, "preview_cam")

    model = head = None
    if not a.no_model:
        try:
            model, head = load_model(a.unstable_root, a.ckpt)
        except Exception as e:
            print(f"  (model probe unavailable: {e})")

    targets = [s for s in manifest["subjects"]
               if s["role"] in ("person_target", "person_distractor")] or manifest["subjects"]
    tiles, probe = [], {"model": Path(a.ckpt).name if model else None,
                        "preview_t_s": t_s,
                        "scripted_qpos_applied": applied,
                        "subject_positions_from": "mj_forward at preview_t_s (not the manifest's p0)",
                        "camera_positions": [], "note":
                        "Offline renders from the drone's eye line (y=0, z=0.8, facing +x) with "
                        "every scripted subject placed at its declared law's value at preview_t_s. "
                        "Scene-drift detector: a rebuilt scene that renders differently changes these."}
    for cx in cam_xs:
        m.cam_pos[cid] = [cx, 0.0, FLIGHT_HEIGHT]
        mujoco.mj_forward(m, d)
        r.update_scene(d, camera="preview_cam")
        gray = np.dot(r.render()[..., :3], [0.2989, 0.5870, 0.1140]).astype(np.uint8)
        entry = {"cam_x": cx, "frame_mean_dn": round(float(gray.mean()), 1),
                 "frame_saturated_fraction": round(float((gray >= 254).mean()), 4), "subjects": {}}
        for s in manifest["subjects"]:
            bid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, s["name"])
            sx, sy = float(d.xpos[bid][0]), float(d.xpos[bid][1])
            rng = math.hypot(sx - cx, sy)
            bearing = math.degrees(math.atan2(sy, sx - cx))
            halfw = math.degrees(math.atan((s["panel"]["width_m"] / 2) / max(rng, 1e-6)))
            entry["subjects"][s["name"]] = {
                "pos_xy": [round(sx, 3), round(sy, 3)],
                "range_m": round(rng, 2), "bearing_deg": round(bearing, 1),
                "half_width_deg": round(halfw, 1),
                "in_model_fov": bool(abs(bearing) + halfw <= MODEL_HALF_FOV)}
        if model is not None:
            v = run_model(model, head, gray)
            entry["model"] = {"visibility_confidence": round(v["visibility_confidence"], 3),
                              "x_bin_index": int(v["x_bin_index"]), "x_value": round(v["x_value"], 3),
                              "size_bucket_index": int(v["size_bucket_index"]),
                              "size_value": round(v["size_value"], 3)}
        probe["camera_positions"].append(entry)
        tiles.append((cx, gray, entry))

    (out / "probe.json").write_text(json.dumps(probe, indent=2) + "\n")

    # contact sheet
    f, fsmall = _font(14), _font(12)
    pad, cap, top = 8, 44 + 13 * len(manifest["subjects"]), 44
    cols = len(tiles)
    W = pad + cols * (FRAME_W + pad)
    H = top + FRAME_H + cap + pad
    sheet = Image.new("RGB", (W, H), (24, 24, 28))
    dr = ImageDraw.Draw(sheet)
    dr.text((pad, 8), f"{manifest['scene_id']}  -  {manifest.get('title', '')}", (245, 245, 245), font=f)
    dr.text((pad, 25), f"lighting {manifest['lighting']['variant']}  |  "
                       f"verdict {manifest['expected_behaviour'].get('verdict', '?')}  |  "
                       f"predicted {manifest['prediction'].get('outcome', '?')}  |  "
                       f"t = {t_s:.1f} s  |  "
                       f"box = centre 244x244 crop the model actually sees (+/-35 deg)",
            (170, 170, 180), font=fsmall)
    for i, (cx, gray, entry) in enumerate(tiles):
        x0 = pad + i * (FRAME_W + pad)
        im = Image.fromarray(gray).convert("RGB")
        dd = ImageDraw.Draw(im)
        c0 = (FRAME_W - FRAME_H) // 2
        dd.rectangle([c0, 0, c0 + FRAME_H - 1, FRAME_H - 1], outline=(255, 200, 0))
        sheet.paste(im, (x0, top))
        mtxt = ""
        if "model" in entry:
            mm = entry["model"]
            mtxt = (f"conf {mm['visibility_confidence']:.3f}  x {mm['x_value']:+.2f} "
                    f"(bin {mm['x_bin_index']})  size {mm['size_value']:.3f}")
        dr.text((x0, top + FRAME_H + 4), f"camera x = {cx:+.2f} m   mean {entry['frame_mean_dn']:.0f} DN",
                (225, 225, 225), font=fsmall)
        dr.text((x0, top + FRAME_H + 19), mtxt or "(no model probe)",
                (120, 220, 140) if mtxt else (150, 150, 150), font=fsmall)
        for j, (nm, sub) in enumerate(entry["subjects"].items()):
            inf = "in FOV " if sub["in_model_fov"] else "OUT    "
            dr.text((x0, top + FRAME_H + 36 + 13 * j),
                    f"{inf} {nm[5:]:<16s} {sub['range_m']:>5.2f} m  {sub['bearing_deg']:+6.1f} deg",
                    (200, 200, 210) if sub["in_model_fov"] else (200, 130, 130), font=fsmall)
    sheet.save(out / "preview.png")
    return probe


# ---------------------------------------------------------------------------
def check(defs, coco, coco_root: Path):
    """Verify every referenced COCO id exists and every cutout is non-empty."""
    bad = 0
    for d in defs:
        names = [s["name"] for s in d["subjects"]]
        head = f"{d['scene_id']}"
        problems = []
        if len(set(names)) != len(names):
            problems.append("duplicate subject names")
        for s in d["subjects"]:
            if not s["name"].startswith("subj_"):
                problems.append(f"{s['name']}: name must start with 'subj_'")
            if s.get("role") not in ROLES:
                problems.append(f"{s['name']}: bad role {s.get('role')!r}")
            st = cutout_stats(coco, s["coco"]["img_id"], s["coco"]["ann_id"])
            tag = "ok " if st["ok"] else "BAD"
            extra = ""
            if s["role"] in ("person_target", "person_distractor") and st.get("category") != "person":
                problems.append(f"{s['name']}: role {s['role']} but COCO category is {st.get('category')}")
            if s["role"] == "nonperson_distractor":
                if st.get("category") == "person":
                    problems.append(f"{s['name']}: nonperson_distractor points at a person annotation")
                if st.get("n_person_anns_in_image", 0) > 0:
                    extra = f"  WARNING: source image contains {st['n_person_anns_in_image']} person ann(s)"
            print(f"  [{tag}] {head}/{s['name']:<24s} img{st['img_id']}/ann{st['ann_id']} "
                  f"cat={st.get('category', '?'):<12s} mask={st.get('mask_px', 0):>7d}px "
                  f"fill={st.get('fill_fraction', 0):.0%} aspect={st.get('aspect', 0):.2f}{extra}")
            problems += [f"{s['name']}: {p}" for p in st["problems"]]
            x, y = s["pos"][0], s["pos"][1]
            if not (ROOM["back_x"] < x < ROOM["far_x"] and ROOM["right_y"] < y < ROOM["left_y"]):
                problems.append(f"{s['name']}: position ({x}, {y}) is outside the room")
        for p in problems:
            print(f"  [FAIL] {head}: {p}")
        bad += len(problems)
    return bad


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--def", dest="defs", type=Path, nargs="*", default=[],
                    help="scene definition JSON file(s)")
    ap.add_argument("--all", action="store_true", help="every scene_defs/*.json")
    ap.add_argument("--def-dir", type=Path, default=DEF_DIR)
    ap.add_argument("--out", type=Path, default=OUT_DIR)
    ap.add_argument("--coco-root", type=Path, default=DRONE_ROOT / "pytorch_ssd/data/coco")
    ap.add_argument("--check", action="store_true",
                    help="verify COCO ids and cutouts; build nothing")
    ap.add_argument("--preview", action="store_true",
                    help="render the drone's view from a few distances into preview.png")
    ap.add_argument("--cam-x", type=float, nargs="+", default=None,
                    help="preview camera x positions (default: the scene's own)")
    ap.add_argument("--preview-t", type=float, default=None,
                    help="sim time to place scripted subjects at for --preview "
                         "(default: the scene's preview_t_s, else a quarter spring period, "
                         "which puts a swaying subject at its declared position)")
    ap.add_argument("--background", choices=("flat", "sampled"), default="flat",
                    help="panel background. 'flat' (default) is today's behaviour: one wall "
                         "colour, byte-identical cutouts, so the published baselines stay "
                         "valid. 'sampled' measures what is really behind each panel and "
                         "paints that instead - better edge match on people and pets, but it "
                         "changes what the network reports, so it is opt-in and unflown.")
    ap.add_argument("--no-model", action="store_true", help="skip the model probe in --preview")
    ap.add_argument("--unstable-root", type=Path, default=DRONE_ROOT / "pytorch_ssd_unstable")
    ap.add_argument("--ckpt", type=Path,
                    default=DRONE_ROOT / "pytorch_ssd_unstable/artifacts/successor_qat_ep3_eval.pth")
    a = ap.parse_args()

    paths = list(a.defs)
    if a.all:
        paths = sorted(a.def_dir.glob("*.json"))
    if not paths:
        raise SystemExit("nothing to do: pass --def <file> or --all")
    defs = []
    for p in paths:
        d = json.loads(Path(p).read_text())
        d.setdefault("scene_id", Path(p).stem)
        defs.append(d)

    coco = load_coco(a.coco_root)

    if a.check:
        print(f"== checking {len(defs)} scene definition(s)")
        bad = check(defs, coco, a.coco_root)
        print(f"== {'OK: everything resolves' if not bad else f'{bad} PROBLEM(S)'}")
        raise SystemExit(1 if bad else 0)

    argv = sys.argv[1:]
    for d in defs:
        out, manifest = build(d, coco, a.coco_root, a.out, argv, a.background)
        n = len(manifest["subjects"])
        drives = manifest["scripted_motion"]["drives"]
        print(f"built {out}  ({n} subject(s), lighting {manifest['lighting']['variant']}"
              f"{', ' + str(len(drives)) + ' scripted drive(s)' if drives else ''})")
        if a.preview:
            cam_xs = a.cam_x or d.get("preview_cam_x") or [0.0, 1.0, 2.0]
            t_s = a.preview_t if a.preview_t is not None else default_preview_t(manifest, d)
            p = preview(out, manifest, cam_xs, t_s, a)
            print(f"  preview at t = {t_s:.1f} s")
            for e in p["camera_positions"]:
                mm = e.get("model", {})
                print(f"  cam x {e['cam_x']:+.2f}: mean {e['frame_mean_dn']:>5.1f} DN  "
                      f"conf {mm.get('visibility_confidence', float('nan')):.3f}  "
                      f"x {mm.get('x_value', float('nan')):+.2f}  "
                      f"size {mm.get('size_value', float('nan')):.3f}")


if __name__ == "__main__":
    main()
