"""Probe the chip network on the 2026-09-22 dorm camera-check frames (frames stay local).
Usage: trainenv/bin/python probe_chip.py <camera_check folder>   (run from tools/crazysim_macos)"""
import sys, glob, json
import numpy as np
from PIL import Image
sys.path.insert(0, ".")
from perception_backends import ChipPerception
D = sys.argv[1]
chip = ChipPerception()
def run(g):
    r = chip(g); return [int(r["x_bin_index"]), int(r["size_bucket_index"]), round(float(r["visibility_confidence"]), 3)]
def load(f): return np.asarray(Image.open(f).convert("L"))
C = sorted(glob.glob(D + "/check/*.png")); L = sorted(glob.glob(D + "/mirror/d2.44_b-14*.png")); R = sorted(glob.glob(D + "/mirror/d2.44_b14*.png"))
def mask_right(g): g = g.copy(); g[:, 115:] = int(g[:, :115].mean()); return g
def stretch(g): g = g.astype(float); return np.clip((g - g.min()) * 255 / (g.max() - g.min()), 0, 255).astype(np.uint8)
a = np.stack([load(f).astype(float) for f in C + L + R])
out = {
  "frame_stats": {"n": len(a), "shape": list(a.shape[1:]), "min": a.min(), "max": a.max(), "mean": round(a.mean(), 1),
                  "distinct_values": int((np.bincount(a.astype(int).ravel(), minlength=256) > 0).sum()),
                  "bayer_phase_means": [round(a[:, r::2, c::2].mean(), 2) for r in (0, 1) for c in (0, 1)]},
  "check_frames_as_is": [run(load(f)) for f in C],
  "left_clip_as_is": [run(load(f)) for f in L], "right_clip_as_is": [run(load(f)) for f in R],
  "left_clip_right_third_blanked": [run(mask_right(load(f))) for f in L],
  "right_clip_right_third_blanked": [run(mask_right(load(f))) for f in R],
  "left_clip_flipped": [run(load(f)[:, ::-1].copy()) for f in L],
  "left_clip_stretched": [run(stretch(load(f))) for f in L], "right_clip_stretched": [run(stretch(load(f))) for f in R],
}
print(json.dumps(out, indent=1))
