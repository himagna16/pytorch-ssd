"""Reimplementation of the thesis's quant-native straight-through follow model.

NOTE: David's original plain_follow code is not in the public repo. This file
follows the thesis description (Section 3.4/4.4): each stage is a stride-2
Conv+BN+ReLU downsample followed by a stride-1 refine block — no residual
adds — with the xbin9_size_bucket4 head. Bin/bucket edges are assumed uniform;
confirm against David's originals when available.

Output layout (14 values):
  [0:9]   x_offset bin logits (9 uniform bins over [-1, 1])
  [9:13]  size_proxy bucket logits (4 uniform buckets over [0, 1])
  [13]    visibility_confidence logit
"""

from __future__ import annotations

from typing import Tuple

import torch
import torch.nn as nn

NUM_X_BINS = 9
NUM_SIZE_BUCKETS = 4

# Uniform bin centers: x over [-1, 1], size over [0, 1].
X_BIN_CENTERS = [-1.0 + (2.0 * i + 1.0) / NUM_X_BINS for i in range(NUM_X_BINS)]
SIZE_BUCKET_CENTERS = [(j + 0.5) / NUM_SIZE_BUCKETS for j in range(NUM_SIZE_BUCKETS)]


def x_offset_to_bin(x: torch.Tensor) -> torch.Tensor:
    idx = torch.floor((x.clamp(-1.0, 1.0) + 1.0) * 0.5 * NUM_X_BINS).long()
    return idx.clamp(0, NUM_X_BINS - 1)


def size_to_bucket(size: torch.Tensor) -> torch.Tensor:
    idx = torch.floor(size.clamp(0.0, 1.0) * NUM_SIZE_BUCKETS).long()
    return idx.clamp(0, NUM_SIZE_BUCKETS - 1)


def split_head(predictions: torch.Tensor):
    """Split [B, 14] raw outputs into (x_bin_logits, size_bucket_logits, vis_logit)."""
    return (
        predictions[:, :NUM_X_BINS],
        predictions[:, NUM_X_BINS:NUM_X_BINS + NUM_SIZE_BUCKETS],
        predictions[:, NUM_X_BINS + NUM_SIZE_BUCKETS],
    )


class ConvBNReLU(nn.Sequential):
    def __init__(
        self,
        in_channels: int,
        out_channels: int,
        kernel_size: int = 3,
        stride: int = 1,
        padding: int = 1,
    ) -> None:
        super().__init__(
            nn.Conv2d(
                in_channels,
                out_channels,
                kernel_size=kernel_size,
                stride=stride,
                padding=padding,
                bias=False,
            ),
            nn.BatchNorm2d(out_channels),
            nn.ReLU(inplace=False),
        )


class PlainFollowNet(nn.Module):
    """
    Straight-through follow network with a bin-based head.

    Input:
      - grayscale tensor shaped [B, 1, 128, 128]

    Output:
      - raw linear outputs shaped [B, 14] (see module docstring for layout)
    """

    def __init__(
        self,
        input_channels: int = 1,
        image_size: Tuple[int, int] = (128, 128),
        stem_channels: int = 16,
        stage_channels: Tuple[int, int, int, int] = (24, 32, 64, 80),
    ) -> None:
        super().__init__()
        if input_channels != 1:
            raise ValueError("PlainFollowNet expects true 1-channel grayscale input.")
        if image_size != (128, 128):
            raise ValueError(
                "PlainFollowNet assumes fixed 128x128 input so stage4 ends at 4x4."
            )

        self.input_channels = input_channels
        self.image_size = image_size

        # 128 -> 64
        self.stem = ConvBNReLU(input_channels, stem_channels, stride=2)
        # 64 -> 32
        self.stage1 = nn.Sequential(
            ConvBNReLU(stem_channels, stage_channels[0], stride=2),
            ConvBNReLU(stage_channels[0], stage_channels[0], stride=1),
        )
        # 32 -> 16
        self.stage2 = nn.Sequential(
            ConvBNReLU(stage_channels[0], stage_channels[1], stride=2),
            ConvBNReLU(stage_channels[1], stage_channels[1], stride=1),
        )
        # 16 -> 8
        self.stage3 = nn.Sequential(
            ConvBNReLU(stage_channels[1], stage_channels[2], stride=2),
            ConvBNReLU(stage_channels[2], stage_channels[2], stride=1),
        )
        # 8 -> 4
        self.stage4 = nn.Sequential(
            ConvBNReLU(stage_channels[2], stage_channels[3], stride=2),
            ConvBNReLU(stage_channels[3], stage_channels[3], stride=1),
        )

        self.global_pool = nn.AvgPool2d(kernel_size=4, stride=4, count_include_pad=False)
        self.head = nn.Linear(stage_channels[3], NUM_X_BINS + NUM_SIZE_BUCKETS + 1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = self.stem(x)
        x = self.stage1(x)
        x = self.stage2(x)
        x = self.stage3(x)
        x = self.stage4(x)
        x = self.global_pool(x)
        x = torch.flatten(x, 1)
        return self.head(x)
