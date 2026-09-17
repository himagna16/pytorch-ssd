#!/usr/bin/env python3
"""Re-score a folder of captured frames on the CHIP arm, the one the drone flies.

WHY THIS EXISTS. tools/real_frames/score_real_frames.py has no backend switch. It
is hardwired to the FLOAT arm: a PIL BILINEAR 244->128 resize and the float
PyTorch checkpoint successor_qat_ep3_eval.pth (score_real_frames.py:194-198,
277-278). Every flight this project has ever run used the CHIP arm instead:
`"backend": "chip"` in all 316 cell.json files across the two flight suites, which
means the int8 export model_id_dory.onnx plus the firmware's integer 2x2-block
preprocess.

Those are different networks with different preprocessing, and on the same frames
they disagree enough to matter: the disagreement is not a constant offset and for
one subject it moves the fraction of frames above the enter bar by 0.4.

So a real capture scored only with score_real_frames.py tells you what a float
PyTorch model would do, not what the drone will do. This script reports the chip
arm on the same frames so both can be read side by side.

It does not modify score_real_frames.py or anything else under tools/.

Usage:
  doryenv/bin/python rescore_chip.py <frames_or_scores.csv> [out.csv]

onnxruntime lives only in doryenv, so this must run under
~/Downloads/drone/doryenv/bin/python.
"""
import csv
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path("/Users/saimaruvada/Downloads/drone/pytorch_ssd")
sys.path.insert(0, str(ROOT / "tools/crazysim_macos"))
from perception_backends import firmware_preprocess, ChipPerception, DEFAULT_ONNX  # noqa: E402

SRC = Path(sys.argv[1])
OUT = Path(sys.argv[2]) if len(sys.argv) > 2 else SRC.parent / "scores_chip.csv"


def frames_from(src):
    """either a folder of *.png, or a scores.csv whose `file` column names them"""
    if src.is_dir():
        return sorted(src.rglob("*.png"))
    rows = list(csv.DictReader(open(src)))
    base = src.parent
    out = []
    for r in rows:
        p = Path(r["file"])
        out.append(p if p.is_absolute() else base / p)
    seen, uniq = set(), []
    for p in out:
        if p not in seen:
            seen.add(p); uniq.append(p)
    return uniq


def main():
    files = frames_from(SRC)
    if not files:
        raise SystemExit(f"no frames found under {SRC}")
    print(f"{len(files)} frames, chip arm: {DEFAULT_ONNX}")
    chip = ChipPerception()
    w = csv.writer(open(OUT, "w", newline=""))
    w.writerow(["file", "conf_chip", "x_bin_chip", "size_bucket_chip"])
    n = 0
    for f in files:
        try:
            g = np.asarray(Image.open(f).convert("L"))
        except Exception:
            continue
        p = chip(firmware_preprocess(g))
        w.writerow([str(f), round(float(p["visibility_confidence"]), 6),
                    int(p["x_bin_index"]), int(p["size_bucket_index"])])
        n += 1
        if n % 1000 == 0:
            print(f"  {n}/{len(files)}", flush=True)
    print(f"wrote {OUT}  ({n} frames)")


if __name__ == "__main__":
    main()
