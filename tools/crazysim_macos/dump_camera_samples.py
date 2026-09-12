#!/usr/bin/env python3
"""Render one scene through every camera preset and write side-by-side samples.

For human review of the sensor model: same frame, same geometry, clean next to
each preset, at several distances, with the measured statistics underneath.

    ../../../trainenv/bin/python dump_camera_samples.py
    ../../../trainenv/bin/python dump_camera_samples.py --scene scenes/moving/scene_person.xml \
        --distances 1.5 2.5 3.5 --out /tmp/camera_samples

Offscreen rendering only: no simulator, no Docker, no UDP, so it needs no
simulator lock. The camera matches the flight camera (324x244, fovy 70) and the
model is warmed up for --warmup frames at each distance so the AE loop has
settled, the way it has in flight.

Writes <out>/contact_sheet.png (the thing to look at), <out>/<preset>_d<N>.png
and <out>/samples.json (per-preset statistics, AE state and per-frame cost).
"""
import argparse
import json
import math
import re
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import camera_model as cm

REC601 = [0.2989, 0.5870, 0.1140]
PRESETS = ["clean", "himax_typical", "himax_low_light", "himax_color_bayer"]


def clean_gray(rgb):
    """Exactly what the unpatched simulator pushes today."""
    return np.dot(rgb[..., :3], REC601).astype(np.uint8)


def person_xy(scene_xml: Path):
    m = re.search(r'<body name="person" pos="([-\d.eE]+) ([-\d.eE]+)', scene_xml.read_text())
    return (float(m.group(1)), float(m.group(2))) if m else (3.0, 0.0)


def render_frames(scene_xml: Path, distances, cam_height, width, height):
    """RGB renders from the drone's eye at each distance (build_person_scene.py's camera)."""
    import mujoco
    spec = mujoco.MjSpec.from_file(str(scene_xml))
    cam = spec.worldbody.add_camera()
    cam.name, cam.fovy = "dump_cam", 70.0
    cam.alt.type = mujoco.mjtOrientation.mjORIENTATION_XYAXES
    cam.alt.xyaxes = [0, -1, 0, 0, 0, 1]     # image-right = world -y, image-up = +z
    model = spec.compile()
    data = mujoco.MjData(model)
    renderer = mujoco.Renderer(model, height, width)
    cid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_CAMERA, "dump_cam")
    px, _ = person_xy(scene_xml)
    out = {}
    for d in distances:
        model.cam_pos[cid] = [px - d, 0.0, cam_height]
        mujoco.mj_forward(model, data)
        renderer.update_scene(data, camera="dump_cam")
        out[d] = renderer.render().copy()
    return out


def stats(gray):
    g = gray.astype(np.float32)
    return {"mean_dn": round(float(g.mean()), 1), "std_dn": round(float(g.std()), 1),
            "p1": int(np.percentile(g, 1)), "p99": int(np.percentile(g, 99)),
            "saturated_pct": round(float((g >= 254).mean() * 100), 1),
            "black_pct": round(float((g <= 1).mean() * 100), 1)}


def label(img, text, w):
    bar = Image.new("RGB", (w, 15), (0, 0, 0))
    ImageDraw.Draw(bar).text((3, 2), text, fill=(255, 255, 255))
    out = Image.new("RGB", (w, img.height + 15), (0, 0, 0))
    out.paste(bar, (0, 0))
    out.paste(img, (0, 15))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scene", type=Path, default=HERE / "scenes/moving/scene_person.xml")
    ap.add_argument("--distances", type=float, nargs="+", default=[1.5, 2.5, 3.5])
    ap.add_argument("--out", type=Path,
                    default=Path("/private/tmp/claude-501/-Users-saimaruvada-Downloads/"
                                 "90541ca8-cca5-4400-9855-79d1dde551f0/scratchpad/simv2/"
                                 "camera_samples"))
    ap.add_argument("--seed", type=int, default=1234)
    ap.add_argument("--warmup", type=int, default=30, help="frames to settle the AE loop")
    ap.add_argument("--cam-height", type=float, default=0.8)
    ap.add_argument("--width", type=int, default=324)
    ap.add_argument("--height", type=int, default=244)
    ap.add_argument("--yaw-rate", type=float, default=0.0,
                    help="body yaw rate [deg/s] for motion blur (0 = still)")
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)

    if not a.scene.exists():
        sys.exit(f"No scene at {a.scene}. Build one with build_person_scene.py (see README).")
    print(f"rendering {a.scene} at {a.distances} m ({a.width}x{a.height}, fovy 70)")
    frames = render_frames(a.scene, a.distances, a.cam_height, a.width, a.height)
    omega = np.array([0.0, 0.0, math.radians(a.yaw_rate)]) if a.yaw_rate else None

    report, tiles = {}, {}
    for preset in PRESETS:
        report[preset] = {}
        model = None
        if preset != "clean":
            model = cm.CameraModel(preset, width=a.width, height=a.height, seed=a.seed)
        for d, rgb in frames.items():
            if model is None:
                gray, cost, state = clean_gray(rgb), None, None
            else:
                for _ in range(a.warmup):          # let the AE loop settle
                    model.apply(rgb, omega, 0.077)
                model._cost_ms.clear()
                t0 = time.perf_counter()
                for _ in range(20):
                    gray = model.apply(rgb, omega, 0.077)
                cost = (time.perf_counter() - t0) / 20 * 1000.0
                state = model.state()
            Image.fromarray(gray).save(a.out / f"{preset}_d{d:.1f}.png")
            tiles[(preset, d)] = gray
            report[preset][f"d{d:.1f}"] = {
                **stats(gray),
                "cost_ms_per_frame": round(cost, 3) if cost is not None else 0.0,
                "ae": state,
            }
        if model is not None:
            report[preset]["params"] = {"seed": model.seed,
                                        "unmeasured": model.params.unmeasured()}

    # Contact sheet: one row per distance, one column per preset.
    w, h = a.width, a.height
    sheet = Image.new("RGB", (w * len(PRESETS), (h + 15) * len(a.distances) + 18), (0, 0, 0))
    ImageDraw.Draw(sheet).text(
        (4, 4), f"{a.scene.parent.name} scene | seed {a.seed} | "
                f"yaw {a.yaw_rate:g} deg/s | rows = distance, columns = preset",
        fill=(255, 255, 255))
    for r, d in enumerate(a.distances):
        for c, preset in enumerate(PRESETS):
            st = report[preset][f"d{d:.1f}"]
            tile = label(Image.fromarray(tiles[(preset, d)]).convert("RGB"),
                         f"{preset}  d={d:.1f}m  mean {st['mean_dn']:.0f} DN  "
                         f"sat {st['saturated_pct']:.0f}%", w)
            sheet.paste(tile, (c * w, 18 + r * (h + 15)))
    sheet.save(a.out / "contact_sheet.png")

    (a.out / "samples.json").write_text(json.dumps(
        {"scene": str(a.scene), "distances": a.distances, "seed": a.seed,
         "yaw_rate_deg_s": a.yaw_rate, "presets": report}, indent=2))

    print(f"\n{'preset':22s} {'dist':>5} {'mean':>6} {'std':>6} {'p99':>5} "
          f"{'sat%':>5} {'ms/frame':>9}  AE")
    for preset in PRESETS:
        for d in a.distances:
            s = report[preset][f"d{d:.1f}"]
            ae = s["ae"]
            ae_txt = (f"{ae['exposure_lines']:.0f} lines, {ae['analog_gain']:.0f}x analog, "
                      f"{ae['digital_gain']:.2f}x digital" if ae else "-")
            print(f"{preset:22s} {d:5.1f} {s['mean_dn']:6.1f} {s['std_dn']:6.1f} "
                  f"{s['p99']:5d} {s['saturated_pct']:5.1f} {s['cost_ms_per_frame']:9.3f}  {ae_txt}")
    print(f"\nwrote {a.out}/contact_sheet.png and {len(PRESETS) * len(a.distances)} frames")


if __name__ == "__main__":
    main()
