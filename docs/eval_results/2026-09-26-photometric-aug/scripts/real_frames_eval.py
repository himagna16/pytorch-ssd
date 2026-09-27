#!/usr/bin/env python3
"""Pre-registered test 3: the Sep 24 real AI-deck frames, split by how bright the clip came out.

Each frame goes through the firmware's own preprocess (perception_backends.firmware_preprocess,
an exact port of preprocess.c) and then each checkpoint in fake-quant form, by default the
release form (ranges recalibrated as the release pipeline does, see fq_forms.py). The follower's rule (enter 0.75, exit 0.45,
3 frames to confirm) is replayed per clip, in frame order, as score_real_frames.py does.

Clips are grouped by their mean raw brightness (0-255): black < 15, dim 15-60, bright > 60.
Frames stay on the laptop; only numbers are written (DECISIONS.md, 2026-09-22).

As a check on the arm itself, the champion's fake-quant confidence is compared with the chip
arm's confidence in each run folder's existing scores.csv, frame by frame.

Usage (nemoenv python, from pytorch_ssd):
  ../nemoenv/bin/python docs/eval_results/2026-09-26-photometric-aug/scripts/real_frames_eval.py \
      ~/drone_frames/2026-09-24 --out <dir> champion=<ckpt> aug=<ckpt> control=<ckpt>
"""
from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve()
PYSSD = HERE.parents[4]
sys.path.insert(0, str(PYSSD / "export"))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(PYSSD / "tools/real_frames"))
import score_real_frames as S  # noqa: E402  (parse_name, follower_track, PB)

ENTER, EXIT, CONFIRM = 0.75, 0.45, 3


def group_of(brightness: float) -> str:
    return "black" if brightness < 15 else ("dim" if brightness <= 60 else "bright")


def load_frames(root: Path):
    frames = []
    for p in sorted(root.rglob("*.png")):
        lab = S.parse_name(p)
        if lab is None:
            continue
        raw = np.asarray(Image.open(p).convert("L"))
        clip = (str(p.parent.relative_to(root)), lab["subject"], lab["light"], lab["dist"],
                lab["bearing"], lab["vis"], lab["take"])
        frames.append(dict(path=p, run=p.parent.name, clip=clip, vis=lab["vis"], frame=lab["frame"] or 0,
                           dist=lab["dist"], bearing=lab["bearing"], bright=float(raw.mean()),
                           net_in=S.PB.firmware_preprocess(raw)))
    return frames


def infer(ckpt: Path, frames, form: str):
    import torch
    from fq_forms import load_fq
    from utils.follow_task import decode_follow_outputs

    payload = torch.load(ckpt, map_location="cpu")
    mq, how = load_fq(payload, form)
    print(f"  {ckpt.name} [{how}]", flush=True)
    x = np.stack([f["net_in"] for f in frames]).astype(np.float32) / 255.0
    with torch.no_grad():
        out = decode_follow_outputs(mq(torch.from_numpy(x)[:, None]), payload["follow_head_type"])
    return out["visibility_confidence"].numpy(), out["x_bin"].numpy() if "x_bin" in out else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("frames", type=Path)
    ap.add_argument("models", nargs="+", help="label=checkpoint")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--form", choices=("qat", "release"), default="release",
                    help="fake-quant form, see fq_forms.py (default release)")
    ap.add_argument("--unstable-root", type=Path, default=PYSSD.parent / "pytorch_ssd_unstable")
    a = ap.parse_args()
    sys.path.insert(0, str(a.unstable_root.resolve()))
    a.out.mkdir(parents=True, exist_ok=True)

    frames = load_frames(a.frames.expanduser())
    clips = defaultdict(list)
    for i, f in enumerate(frames):
        clips[f["clip"]].append(i)
    for idx in clips.values():
        idx.sort(key=lambda i: frames[i]["frame"])
        cb = float(np.mean([frames[i]["bright"] for i in idx]))
        for i in idx:
            frames[i]["clip_bright"], frames[i]["group"] = cb, group_of(cb)

    labels = []
    for spec in a.models:
        label, _, ck = spec.partition("=")
        labels.append(label)
        conf, _ = infer(Path(ck).expanduser(), frames, a.form)
        for i, c in enumerate(conf):
            frames[i][f"conf_{label}"] = float(c)
        for idx in clips.values():
            _, flags = S.follower_track([frames[i][f"conf_{label}"] for i in idx], ENTER, EXIT, CONFIRM)
            for i, fl in zip(idx, flags):
                frames[i][f"lock_{label}"] = bool(fl)

    lines = []
    say = lambda s="": (print(s), lines.append(s))
    say(f"{len(frames)} frames in {len(clips)} clips from {a.frames}. Fake-quant form: {a.form}, firmware preprocess.")
    say(f"Seen = conf >= {ENTER}. Locked = follower rule (enter {ENTER}, exit {EXIT}, {CONFIRM} frames).\n")

    # Check on the arm: champion fake-quant vs the chip arm's recorded confidence.
    if "champion" in labels:
        pairs = []
        for run in sorted({f["run"] for f in frames}):
            sc = a.frames.expanduser() / run / "scores.csv"
            if not sc.exists():
                sc = PYSSD / "docs/eval_results/2026-09-24-grid-capture" / run / "scores.csv"
            if not sc.exists():
                continue
            chip = {r["file"]: float(r["conf"]) for r in csv.DictReader(open(sc))}
            pairs += [(chip[f["path"].name], f["conf_champion"]) for f in frames
                      if f["run"] == run and f["path"].name in chip]
        if pairs:
            c, q = np.array(pairs).T
            say(f"Arm check, champion fake-quant vs chip arm on {len(pairs)} frames: "
                f"mean diff {np.mean(q - c):+.3f}, mean |diff| {np.mean(abs(q - c)):.3f}, "
                f"corr {np.corrcoef(c, q)[0, 1]:.3f}, same side of 0.75 on {np.mean((c >= ENTER) == (q >= ENTER)):.1%}\n")

    hdr = f"{'group':<7} {'kind':<7} {'clips':>5} {'frames':>6} {'bright':>7} | " + " | ".join(
        f"{l + ' seen/med/lock':>24}" for l in labels)
    say(hdr)
    say("-" * len(hdr))
    for g in ("dim", "bright", "black"):
        for kind, v in (("person", 1), ("empty", 0)):
            sel = [f for f in frames if f["group"] == g and f["vis"] == v]
            if not sel:
                continue
            ncl = len({f["clip"] for f in sel})
            cells = []
            for l in labels:
                cs = np.array([f[f"conf_{l}"] for f in sel])
                cells.append(f"{np.mean(cs >= ENTER):>7.0%} {np.median(cs):>6.2f} "
                             f"{np.mean([f[f'lock_{l}'] for f in sel]):>7.0%}   ")
            say(f"{g:<7} {kind:<7} {ncl:>5} {len(sel):>6} {np.mean([f['bright'] for f in sel]):>7.1f} | "
                + " | ".join(f"{c:>24}" for c in cells))

    say("\nPer clip (median conf, share locked):")
    say(f"{'run':<20} {'dist':>5} {'bear':>6} {'vis':>3} {'bright':>6} {'n':>3} | "
        + " | ".join(f"{l:>14}" for l in labels))
    for key, idx in sorted(clips.items(), key=lambda kv: (kv[0][0], str(kv[0][3]), str(kv[0][4]))):
        f0 = frames[idx[0]]
        cells = [f"{np.median([frames[i][f'conf_{l}'] for i in idx]):.2f} "
                 f"{np.mean([frames[i][f'lock_{l}'] for i in idx]):>4.0%}" for l in labels]
        say(f"{f0['run']:<20} {f0['dist'] if f0['dist'] is not None else '-':>5} "
            f"{f0['bearing'] if f0['bearing'] is not None else '-':>6} {f0['vis']:>3} "
            f"{f0['clip_bright']:>6.1f} {len(idx):>3} | " + " | ".join(f"{c:>14}" for c in cells))

    (a.out / f"real_frames_report_{a.form}.txt").write_text("\n".join(lines) + "\n")
    with open(a.out / f"real_frames_per_frame_{a.form}.csv", "w", newline="") as fh:
        cols = ["run", "file", "vis", "dist", "bearing", "frame", "bright", "clip_bright", "group"] + [
            c for l in labels for c in (f"conf_{l}", f"lock_{l}")]
        w = csv.writer(fh)
        w.writerow(cols)
        for f in frames:
            w.writerow([f["run"], f["path"].name, f["vis"], f["dist"], f["bearing"], f["frame"],
                        round(f["bright"], 2), round(f["clip_bright"], 2), f["group"]]
                       + [v for l in labels for v in (round(f[f"conf_{l}"], 4), int(f[f"lock_{l}"]))])


if __name__ == "__main__":
    main()
