"""Render prediction overlays for follow models on real COCO images.

Shows the model input as the drone sees it (center-cropped 128x128 grayscale,
upscaled for viewing) with:
  green = ground truth (x position line, size bar, visibility)
  red   = model prediction (decoded x, size, visibility confidence)
A red tile border marks a wrong visibility decision.

Usage (from inside pytorch_ssd, trainenv python):
  ../trainenv/bin/python export/visualize_follow_predictions.py \
    --model-type hybrid_follow \
    --ckpt training/hybrid_follow/hybrid_follow_best_visibility.pth \
    --images-root data/coco/images/val2017 \
    --ann data/coco/annotations/instances_val2017.json \
    --out export/overlays_hybrid.png
"""

import argparse
import sys
from pathlib import Path

import torch
from PIL import Image, ImageDraw

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from models.hybrid_follow_net import HybridFollowNet  # noqa: E402
from models.plain_follow_net import (  # noqa: E402
    NUM_SIZE_BUCKETS,
    NUM_X_BINS,
    SIZE_BUCKET_CENTERS,
    X_BIN_CENTERS,
    PlainFollowNet,
)
from utils.coco_follow_regression import COCOFollowRegressionDataset  # noqa: E402
from utils.transforms import get_val_transforms  # noqa: E402

TILE = 384  # upscaled tile size (128 * 3)


def decode(raw: torch.Tensor, model_type: str):
    if model_type == "plain_follow":
        x = X_BIN_CENTERS[int(raw[:NUM_X_BINS].argmax())]
        size = SIZE_BUCKET_CENTERS[int(raw[NUM_X_BINS:NUM_X_BINS + NUM_SIZE_BUCKETS].argmax())]
        vis_p = torch.sigmoid(raw[NUM_X_BINS + NUM_SIZE_BUCKETS]).item()
    else:
        x = max(-1.0, min(1.0, raw[0].item()))
        size = max(0.0, min(1.0, raw[1].item()))
        vis_p = torch.sigmoid(raw[2]).item()
    return x, size, vis_p


def draw_marks(draw: ImageDraw.ImageDraw, x: float, size: float, color, width: int):
    px = (x + 1.0) * 0.5 * TILE
    bar_h = size * TILE
    draw.line([(px, 0), (px, TILE)], fill=color, width=width)
    draw.line([(px, (TILE - bar_h) / 2), (px, (TILE + bar_h) / 2)], fill=color, width=width * 3)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model-type", default="hybrid_follow",
                    choices=["hybrid_follow", "plain_follow"])
    ap.add_argument("--ckpt", required=True)
    ap.add_argument("--images-root", required=True)
    ap.add_argument("--ann", required=True)
    ap.add_argument("--num-person", type=int, default=6)
    ap.add_argument("--num-noperson", type=int, default=2)
    ap.add_argument("--vis-thresh", type=float, default=0.5)
    ap.add_argument("--out", default="export/overlays.png")
    args = ap.parse_args()

    state = torch.load(args.ckpt, map_location="cpu")
    model_cls = HybridFollowNet if args.model_type == "hybrid_follow" else PlainFollowNet
    model = model_cls(input_channels=1, image_size=(128, 128))
    model.load_state_dict(state["state_dict"])
    model.eval()

    ds = COCOFollowRegressionDataset(
        root=args.images_root,
        ann_file=args.ann,
        transforms=get_val_transforms("hybrid_follow", input_channels=1),
    )

    picked = []
    want_p, want_n = args.num_person, args.num_noperson
    for i in range(len(ds)):
        if want_p <= 0 and want_n <= 0:
            break
        img, target = ds[i]
        visible = float(target["follow_target"][2]) > 0.5
        if visible and want_p > 0:
            picked.append((i, img, target))
            want_p -= 1
        elif not visible and want_n > 0:
            picked.append((i, img, target))
            want_n -= 1

    cols = 4
    rows = (len(picked) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * TILE, rows * TILE), "black")

    with torch.no_grad():
        for k, (i, img, target) in enumerate(picked):
            raw = model(img.unsqueeze(0)).reshape(-1)
            pred_x, pred_size, pred_vis = decode(raw, args.model_type)

            gt = target["follow_target"]
            gt_x, gt_size, gt_vis = float(gt[0]), float(gt[1]), float(gt[2]) > 0.5
            pred_visible = pred_vis >= args.vis_thresh

            tile = Image.fromarray(
                (img[0].numpy() * 255).astype("uint8"), mode="L"
            ).resize((TILE, TILE), Image.NEAREST).convert("RGB")
            d = ImageDraw.Draw(tile)

            if gt_vis:
                draw_marks(d, gt_x, gt_size, (0, 220, 0), 2)
            if pred_visible:
                draw_marks(d, pred_x, pred_size, (255, 60, 60), 2)

            label = (f"#{i}  GT vis={int(gt_vis)}  pred P={pred_vis:.2f}"
                     + (f"  x={pred_x:+.2f} sz={pred_size:.2f}" if pred_visible else "  (no target)"))
            d.rectangle([0, 0, TILE, 22], fill=(0, 0, 0))
            d.text((6, 4), label, fill=(255, 255, 255))
            if pred_visible != gt_vis:
                d.rectangle([0, 0, TILE - 1, TILE - 1], outline=(255, 0, 0), width=5)

            sheet.paste(tile, ((k % cols) * TILE, (k // cols) * TILE))

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path)
    print(f"saved {len(picked)}-image overlay sheet to {out_path}")


if __name__ == "__main__":
    main()
