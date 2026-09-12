"""As-BUILT subject-extent probe: does the scene ON DISK still draw a mirror?

This is the same measurement as
`docs/eval_results/2026-09-12-distance/scripts/refl_extent.py`, with one
deliberate difference: that script overrides `mat_reflectance` on the compiled
model in memory (0.2 and 0.0), so it measures the *physics*, not the file.
This one changes NOTHING - it compiles the scene.xml exactly as it sits on disk
and reports what the renderer draws. It is therefore the check that the
groundplane fix actually landed in the built scenes.

Method, unchanged from refl_extent.py: render each frame twice, once with the
subject panel geom visible and once with it hidden (rgba alpha 0). Every pixel
that differs by more than 6 DN is a pixel the panel contributes - the panel AND
anything the renderer draws because of it, i.e. its reflection. The vertical
extent of that difference is the apparent subject height the network is shown.
`panel_h` comes from MuJoCo's own segmentation render (per-pixel geom id), not
a threshold.

  apparent/panel == 1.00  -> matte floor, the network sees only the subject
  apparent/panel >  1.00  -> the floor is drawing a reflection

Usage:
  <trainenv python> asbuilt_extent.py [--scene s15_static_offset] [--json OUT]
"""
import argparse
import json
import math
from pathlib import Path

import numpy as np
import mujoco

SIMDIR = Path("/Users/saimaruvada/Downloads/drone/pytorch_ssd/tools/crazysim_macos")
FRAME_W, FRAME_H, FOVY, EYE_Z = 324, 244, 70.0, 0.8
DISTS = (2.4, 2.8, 3.0, 3.4, 3.8)


def probe(scene_id: str, dists=DISTS):
    out = SIMDIR / "scenes_v2" / scene_id
    manifest = json.loads((out / "manifest.json").read_text())
    target = next(s for s in manifest["subjects"] if s["role"] == "person_target")
    name = target["name"]

    spec = mujoco.MjSpec.from_file(str(out / "scene.xml"))
    c = spec.worldbody.add_camera()
    c.name, c.fovy = "cam", FOVY
    c.pos = [0, 0, EYE_Z]
    c.alt.type = mujoco.mjtOrientation.mjORIENTATION_XYAXES
    c.alt.xyaxes = [0, -1, 0, 0, 0, 1]
    m = spec.compile()
    d = mujoco.MjData(m)
    mujoco.mj_forward(m, d)

    cid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_CAMERA, "cam")
    bid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, name)
    gid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_GEOM, f"{name}_panel")
    mid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_MATERIAL, "groundplane")
    refl_on_disk = float(m.mat_reflectance[mid])       # read, never written

    sx, sy = float(d.xpos[bid][0]), float(d.xpos[bid][1])
    r = mujoco.Renderer(m, FRAME_H, FRAME_W)
    sr = mujoco.Renderer(m, FRAME_H, FRAME_W)
    sr.enable_segmentation_rendering()
    rgba0 = m.geom_rgba[gid].copy()

    rows = []
    for dist in dists:
        m.cam_pos[cid] = [sx - dist, sy, EYE_Z]
        mujoco.mj_forward(m, d)
        m.geom_rgba[gid] = rgba0
        r.update_scene(d, camera="cam")
        a = r.render().astype(np.int16)
        sr.update_scene(d, camera="cam")
        seg = sr.render()
        msk = (seg[..., 0] == mujoco.mjtObj.mjOBJ_GEOM) & (seg[..., 1] == gid)
        rr = np.where(msk.any(axis=1))[0]
        m.geom_rgba[gid] = [0, 0, 0, 0]
        r.update_scene(d, camera="cam")
        b = r.render().astype(np.int16)
        diff = np.abs(a - b).max(axis=2) > 6
        dd = np.where(diff.any(axis=1))[0]
        ph = int(rr[-1] - rr[0] + 1)
        ah = int(dd[-1] - dd[0] + 1)
        rows.append({"d_true": dist, "panel_top": int(rr[0]), "panel_bot": int(rr[-1]),
                     "panel_h": ph, "apparent_top": int(dd[0]), "apparent_bot": int(dd[-1]),
                     "apparent_h": ah, "ratio": round(ah / ph, 4)})
    m.geom_rgba[gid] = rgba0
    return {"scene": scene_id, "subject": name,
            "groundplane_reflectance_on_disk": refl_on_disk, "rows": rows}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scene", nargs="+", default=["s15_static_offset", "s01_control_moving"])
    ap.add_argument("--json", type=Path, default=None)
    a = ap.parse_args()
    allres = []
    for s in a.scene:
        res = probe(s)
        allres.append(res)
        print(f"== {res['scene']}  subject {res['subject']}  "
              f"groundplane reflectance ON DISK = {res['groundplane_reflectance_on_disk']:.3f}")
        print("   d_true  panel_rows  panel_h  apparent_rows  apparent_h  apparent/panel")
        for r in res["rows"]:
            print(f"   {r['d_true']:6.2f}   {r['panel_top']:3d}-{r['panel_bot']:3d}"
                  f"     {r['panel_h']:5d}      {r['apparent_top']:3d}-{r['apparent_bot']:3d}"
                  f"       {r['apparent_h']:5d}        {r['ratio']:8.3f}")
        print()
    if a.json:
        a.json.write_text(json.dumps(allres, indent=2) + "\n")
        print(f"wrote {a.json}")


if __name__ == "__main__":
    main()
