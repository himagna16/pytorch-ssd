#!/usr/bin/env python3
"""Left-right flip every frame of a captured folder, keeping the labels.

This is what a back-to-front camera would have produced for the same clips:
same filenames (so the same --dist/--bearing labels), same PNG provenance text
chunks, same clip JSONs, only the pixels mirrored. Scoring the result must say
MIRRORED, or the mirror check cannot see a mirror.

    flip_folder.py <captured> <captured_flipped>
"""
import json
import shutil
import sys
from pathlib import Path

from PIL import Image, PngImagePlugin

src, dst = Path(sys.argv[1]), Path(sys.argv[2])
n_png = n_json = 0
for p in sorted(src.rglob("*")):
    if p.is_dir() or p.name.startswith("."):
        continue
    q = dst / p.relative_to(src)
    q.parent.mkdir(parents=True, exist_ok=True)
    if p.suffix == ".png":
        im = Image.open(p)
        info = PngImagePlugin.PngInfo()
        for k, v in im.text.items():
            info.add_text(k, v)
        info.add_text("flipped_left_right_by", "flip_folder.py (rehearsal of a mirrored camera)")
        im.transpose(Image.FLIP_LEFT_RIGHT).save(q, pnginfo=info)
        n_png += 1
    elif p.name.endswith("_clip.json"):
        d = json.loads(p.read_text())
        d["flipped_left_right_by"] = "flip_folder.py"
        q.write_text(json.dumps(d, indent=2))
        n_json += 1
print(f"flipped {n_png} frames, copied {n_json} clip JSONs -> {dst}")
