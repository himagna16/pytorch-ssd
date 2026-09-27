import math
import random
from typing import Any, Dict, Optional, Tuple

import torch
import torchvision.transforms.functional as F
from PIL import Image

# "frontnet" = RandomPhotometricHimax with the PULP-Frontnet settings.
# "exposure" = RandomExposureHimax: exposure gain with clipping plus vignetting, no blur.
PHOTOMETRIC_AUG_CHOICES = ("none", "frontnet", "exposure")


def _empty_boxes_like(boxes: torch.Tensor) -> torch.Tensor:
    return boxes.new_zeros((0, 4))


def _boxes_from_target(target: Dict[str, Any]) -> Optional[torch.Tensor]:
    boxes = target.get("boxes")
    if boxes is None:
        return None
    if boxes.numel() == 0:
        return _empty_boxes_like(boxes)
    return boxes


def _filter_target_rows(target: Dict[str, Any], keep: torch.Tensor) -> Dict[str, Any]:
    for key in ("boxes", "labels", "area", "iscrowd"):
        value = target.get(key)
        if torch.is_tensor(value) and value.ndim > 0 and value.shape[0] == keep.shape[0]:
            target[key] = value[keep]
    return target


def _recompute_area(target: Dict[str, Any]) -> Dict[str, Any]:
    boxes = _boxes_from_target(target)
    if boxes is None:
        return target
    if boxes.numel() == 0:
        target["boxes"] = _empty_boxes_like(boxes)
        target["area"] = boxes.new_zeros((0,))
        return target

    widths = (boxes[:, 2] - boxes[:, 0]).clamp_min(0.0)
    heights = (boxes[:, 3] - boxes[:, 1]).clamp_min(0.0)
    target["area"] = widths * heights
    return target


def _clamp_and_filter_boxes(
    target: Dict[str, Any],
    width: int,
    height: int,
) -> Dict[str, Any]:
    boxes = _boxes_from_target(target)
    if boxes is None:
        return target
    if boxes.numel() == 0:
        target["boxes"] = _empty_boxes_like(boxes)
        target["area"] = boxes.new_zeros((0,))
        return target

    boxes = boxes.clone()
    boxes[:, 0::2] = boxes[:, 0::2].clamp(0.0, float(width))
    boxes[:, 1::2] = boxes[:, 1::2].clamp(0.0, float(height))
    keep = (boxes[:, 2] > boxes[:, 0]) & (boxes[:, 3] > boxes[:, 1])
    target["boxes"] = boxes
    target = _filter_target_rows(target, keep)
    return _recompute_area(target)


class Compose:
    def __init__(self, transforms):
        self.transforms = transforms

    def __call__(self, img, target):
        for t in self.transforms:
            img, target = t(img, target)
        return img, target


class CenterCropSquare:
    def __call__(self, img: Image.Image, target: Dict[str, Any]):
        width, height = img.size
        crop_size = min(width, height)
        crop_left = (width - crop_size) // 2
        crop_top = (height - crop_size) // 2

        img = F.crop(img, crop_top, crop_left, crop_size, crop_size)

        boxes = _boxes_from_target(target)
        if boxes is not None and boxes.numel() > 0:
            boxes = boxes.clone()
            boxes[:, [0, 2]] -= float(crop_left)
            boxes[:, [1, 3]] -= float(crop_top)
            target["boxes"] = boxes
            target = _clamp_and_filter_boxes(target, crop_size, crop_size)

        return img, target


class ResizeImage:
    def __init__(self, size: Tuple[int, int]):
        self.size = size

    def __call__(self, img: Image.Image, target: Dict[str, Any]):
        old_width, old_height = img.size
        new_height, new_width = self.size
        img = F.resize(img, [new_height, new_width])

        boxes = _boxes_from_target(target)
        if boxes is not None and boxes.numel() > 0:
            scale_x = float(new_width) / float(old_width)
            scale_y = float(new_height) / float(old_height)
            boxes = boxes.clone()
            boxes[:, [0, 2]] *= scale_x
            boxes[:, [1, 3]] *= scale_y
            target["boxes"] = boxes
            target = _recompute_area(target)

        return img, target


class RandomHorizontalFlip:
    def __init__(self, p=0.5):
        self.p = p

    def __call__(self, img: Image.Image, target: Dict[str, Any]):
        if random.random() < self.p:
            img = F.hflip(img)
            width, _ = img.size
            boxes = _boxes_from_target(target)
            if boxes is not None and boxes.numel() > 0:
                boxes = boxes.clone()
                boxes[:, [0, 2]] = float(width) - boxes[:, [2, 0]]
                target["boxes"] = boxes
        return img, target


class ToTensorGray:
    """
    Convert a PIL image to a grayscale tensor.

    By default returns true single-channel tensors shaped [1, H, W].
    """

    def __init__(self, output_channels: int = 1):
        if output_channels not in (1, 3):
            raise ValueError("output_channels must be 1 or 3")
        self.output_channels = output_channels

    def __call__(self, img: Image.Image, target: Dict[str, Any]):
        img_gray = img.convert("L")
        img_t = F.to_tensor(img_gray)
        if self.output_channels == 3:
            img_t = img_t.repeat(3, 1, 1)
        return img_t, target


class RandomPhotometricHimax:
    """
    Photometric and optical augmentation for the AI-deck's Himax HM01B0 camera.

    Follows PULP-Frontnet (Palossi et al. 2021, arXiv 2103.10873, Sec. IV-B), which flies
    the same camera. Each effect is applied independently with probability p, in the
    paper's order, to a [C, H, W] tensor in [0, 1]:

      contrast    multiplicative factor in [0.7, 2.0], about the image mean
                  (the paper's stated reason: erratic auto-exposure)
      brightness  additive shift in [-0.2, 0.2]
      gamma       exponent in [0.4, 2.0]
      vignetting  radial darkening with random radius and strength
      blur        Gaussian, sigma 3 px at the paper's 160 px input width,
                  scaled to this image's width

    The paper gives no numbers for vignetting, so the ranges here are ours: at their
    extremes they bracket camera_model.py's Himax preset (corner gain about 0.68).
    Runs after ToTensorGray; labels are untouched.
    """

    def __init__(
        self,
        p: float = 0.5,
        contrast: Tuple[float, float] = (0.7, 2.0),
        brightness: Tuple[float, float] = (-0.2, 0.2),
        gamma: Tuple[float, float] = (0.4, 2.0),
        vignette_strength: Tuple[float, float] = (0.1, 0.6),
        vignette_radius: Tuple[float, float] = (0.0, 0.6),
        blur_sigma_px: float = 3.0,
        blur_reference_width: int = 160,
    ):
        self.p = p
        self.contrast = contrast
        self.brightness = brightness
        self.gamma = gamma
        self.vignette_strength = vignette_strength
        self.vignette_radius = vignette_radius
        self.blur_sigma_px = blur_sigma_px
        self.blur_reference_width = blur_reference_width

    @staticmethod
    def _vignette(img: torch.Tensor, strength: float, radius: float) -> torch.Tensor:
        _, height, width = img.shape
        ys = torch.linspace(-1.0, 1.0, height, dtype=img.dtype).view(-1, 1)
        xs = torch.linspace(-1.0, 1.0, width, dtype=img.dtype).view(1, -1)
        # Radius normalised so the image corner sits at 1.
        r = torch.sqrt(xs * xs + ys * ys) / (2.0 ** 0.5)
        falloff = ((r - radius) / (1.0 - radius)).clamp(0.0, 1.0)
        return img * (1.0 - strength * falloff * falloff)

    def __call__(self, img: torch.Tensor, target: Dict[str, Any]):
        if random.random() < self.p:
            img = F.adjust_contrast(img, random.uniform(*self.contrast))
        if random.random() < self.p:
            img = (img + random.uniform(*self.brightness)).clamp(0.0, 1.0)
        if random.random() < self.p:
            img = F.adjust_gamma(img, random.uniform(*self.gamma))
        if random.random() < self.p:
            img = self._vignette(
                img,
                random.uniform(*self.vignette_strength),
                random.uniform(*self.vignette_radius),
            ).clamp(0.0, 1.0)
        if random.random() < self.p:
            sigma = self.blur_sigma_px * img.shape[-1] / float(self.blur_reference_width)
            kernel = 2 * int(math.ceil(3.0 * sigma)) + 1
            img = F.gaussian_blur(img, [kernel, kernel], [sigma, sigma])
        return img, target



class RandomExposureHimax:
    """
    Exposure jitter the way the AI-deck camera actually gets it wrong, plus vignetting.

    Written after the PULP-Frontnet preset hurt us (docs/eval_results/2026-09-26-photometric-aug).
    The Sep 24 frames showed auto-exposure landing on a different gain at each power-up, which
    scales light and blows out highlights; contrast about the mean never clips. So, each with
    probability p, on a [C, H, W] tensor in [0, 1]:

      exposure    gain k, log-uniform in [k_min, k_max], applied in linear light
                  (gamma 2.2), clipped at white, re-quantised to 8 bits
      vignetting  as RandomPhotometricHimax

    No blur: blurring small COCO people away while the label still says "person" is the
    likeliest reason the frontnet preset lost recall.
    """

    def __init__(
        self,
        p: float = 0.5,
        k_range: Tuple[float, float] = (0.25, 4.0),
        vignette_strength: Tuple[float, float] = (0.1, 0.6),
        vignette_radius: Tuple[float, float] = (0.0, 0.6),
        display_gamma: float = 2.2,
    ):
        self.p = p
        self.k_range = k_range
        self.vignette_strength = vignette_strength
        self.vignette_radius = vignette_radius
        self.display_gamma = display_gamma

    def __call__(self, img: torch.Tensor, target: Dict[str, Any]):
        if random.random() < self.p:
            k = math.exp(random.uniform(math.log(self.k_range[0]), math.log(self.k_range[1])))
            linear = img.clamp(0.0, 1.0) ** self.display_gamma
            img = (k * linear).clamp(0.0, 1.0) ** (1.0 / self.display_gamma)
            img = torch.round(img * 255.0) / 255.0
        if random.random() < self.p:
            img = RandomPhotometricHimax._vignette(
                img,
                random.uniform(*self.vignette_strength),
                random.uniform(*self.vignette_radius),
            ).clamp(0.0, 1.0)
        return img, target


def get_train_transforms(
    model_type: str = "ssd",
    input_channels: int = 1,
    image_size: Tuple[int, int] = (128, 128),
    photometric_aug: str = "none",
):
    if photometric_aug not in PHOTOMETRIC_AUG_CHOICES:
        raise ValueError(f"photometric_aug must be one of {PHOTOMETRIC_AUG_CHOICES}")
    if model_type in {"hybrid_follow", "plain_follow", "plain_follow_bin", "plain_follow_v2", "plain_follow_tiny", "dronet_lite_follow"}:
        if input_channels != 1:
            raise ValueError(f"{model_type} path requires input_channels=1.")
        flip_prob = 0.5
        if model_type == "dronet_lite_follow":
            # Keep dronet-lite augmentation milder so the visibility gate settles
            # before the residual path starts chasing harder x offsets.
            flip_prob = 0.25
        steps = [
            CenterCropSquare(),
            ResizeImage(image_size),
            RandomHorizontalFlip(flip_prob),
            ToTensorGray(output_channels=1),
        ]
        if photometric_aug == "frontnet":
            steps.append(RandomPhotometricHimax())
        elif photometric_aug == "exposure":
            steps.append(RandomExposureHimax())
        return Compose(steps)

    if photometric_aug != "none":
        raise ValueError("photometric_aug is only wired for the follow models.")

    return Compose(
        [
            RandomHorizontalFlip(0.5),
            ToTensorGray(output_channels=input_channels),
        ]
    )


def get_val_transforms(
    model_type: str = "ssd",
    input_channels: int = 1,
    image_size: Tuple[int, int] = (128, 128),
):
    if model_type in {"hybrid_follow", "plain_follow", "plain_follow_bin", "plain_follow_v2", "plain_follow_tiny", "dronet_lite_follow"}:
        if input_channels != 1:
            raise ValueError(f"{model_type} path requires input_channels=1.")
        return Compose(
            [
                CenterCropSquare(),
                ResizeImage(image_size),
                ToTensorGray(output_channels=1),
            ]
        )

    return Compose(
        [
            ToTensorGray(output_channels=input_channels),
        ]
    )
