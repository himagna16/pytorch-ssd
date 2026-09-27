"""--photometric-aug frontnet: PULP-Frontnet's camera augmentation, and nothing else changes.

The default (none) must build exactly the old follow-model pipeline, so every earlier run
reproduces. With frontnet, RandomPhotometricHimax is appended after ToTensorGray and must
keep images in [0, 1], leave labels alone, and do what each of its five effects says.

Usage (nemoenv python, from inside the worktree):
  ../nemoenv/bin/python -m unittest tests.test_photometric_aug -v
"""

from __future__ import annotations

import random
import sys
import unittest
from pathlib import Path
from unittest import mock

import torch
from PIL import Image

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

from utils import transforms as T  # noqa: E402


def _gradient_image(width=200, height=150) -> Image.Image:
    img = Image.new("L", (width, height))
    img.putdata([(x * 255) // (width - 1) for _ in range(height) for x in range(width)])
    return img


def _target():
    return {"boxes": torch.tensor([[20.0, 30.0, 120.0, 140.0]]), "labels": torch.tensor([1])}


class DefaultIsUnchanged(unittest.TestCase):
    def test_default_pipeline_matches_the_old_one(self):
        new = T.get_train_transforms(model_type="plain_follow", image_size=(128, 128))
        self.assertEqual(
            [type(t) for t in new.transforms],
            [T.CenterCropSquare, T.ResizeImage, T.RandomHorizontalFlip, T.ToTensorGray],
        )
        old = T.Compose(
            [T.CenterCropSquare(), T.ResizeImage((128, 128)), T.RandomHorizontalFlip(0.5), T.ToTensorGray(1)]
        )
        for seed in range(6):
            random.seed(seed)
            a, ta = new(_gradient_image(), _target())
            random.seed(seed)
            b, tb = old(_gradient_image(), _target())
            self.assertTrue(torch.equal(a, b))
            self.assertTrue(torch.equal(ta["boxes"], tb["boxes"]))

    def test_val_transforms_never_augment(self):
        val = T.get_val_transforms(model_type="plain_follow")
        self.assertFalse(any(isinstance(t, T.RandomPhotometricHimax) for t in val.transforms))


class FrontnetWiring(unittest.TestCase):
    def test_appended_after_to_tensor(self):
        tr = T.get_train_transforms(model_type="plain_follow", photometric_aug="frontnet")
        self.assertIsInstance(tr.transforms[-2], T.ToTensorGray)
        self.assertIsInstance(tr.transforms[-1], T.RandomPhotometricHimax)

    def test_unknown_or_unwired_choice_raises(self):
        with self.assertRaises(ValueError):
            T.get_train_transforms(model_type="plain_follow", photometric_aug="colorjitter")
        with self.assertRaises(ValueError):
            T.get_train_transforms(model_type="ssd", photometric_aug="frontnet")

    def test_train_py_flag(self):
        import train

        base = ["train.py", "--model-type", "plain_follow"]
        with mock.patch.object(sys, "argv", base):
            self.assertEqual(train.parse_args().photometric_aug, "none")
        with mock.patch.object(sys, "argv", base + ["--photometric-aug", "frontnet"]):
            self.assertEqual(train.parse_args().photometric_aug, "frontnet")

    def test_full_pipeline_range_shape_and_labels(self):
        tr = T.get_train_transforms(model_type="plain_follow", photometric_aug="frontnet")
        random.seed(0)
        for _ in range(200):
            target = _target()
            img, out = tr(_gradient_image(), target)
            self.assertEqual(tuple(img.shape), (1, 128, 128))
            self.assertGreaterEqual(float(img.min()), 0.0)
            self.assertLessEqual(float(img.max()), 1.0)
            self.assertIs(out, target)

    def test_seeded_runs_repeat(self):
        aug = T.RandomPhotometricHimax()
        x = torch.rand(1, 64, 64)
        random.seed(3)
        a = [aug(x.clone(), {})[0] for _ in range(20)]
        random.seed(3)
        b = [aug(x.clone(), {})[0] for _ in range(20)]
        self.assertTrue(all(torch.equal(p, q) for p, q in zip(a, b)))

    def test_about_half_of_each_effect_fires(self):
        aug = T.RandomPhotometricHimax()
        x = torch.full((1, 32, 32), 0.5)
        random.seed(0)
        untouched = sum(torch.equal(aug(x.clone(), {})[0], x) for _ in range(2000))
        # All five effects skipped: 0.5 ** 5 = 3.1%. (Contrast on a flat image is a no-op,
        # so a flat image stays flat whenever brightness, gamma, vignette are all skipped.)
        self.assertGreater(untouched / 2000, 0.08)
        self.assertLess(untouched / 2000, 0.17)


class EachEffect(unittest.TestCase):
    def _only(self, **kw):
        # p=1 with every other range collapsed to its identity value.
        base = dict(
            p=1.0,
            contrast=(1.0, 1.0),
            brightness=(0.0, 0.0),
            gamma=(1.0, 1.0),
            vignette_strength=(0.0, 0.0),
            vignette_radius=(0.0, 0.0),
            blur_sigma_px=1e-6,
        )
        base.update(kw)
        return T.RandomPhotometricHimax(**base)

    def test_p_zero_is_identity(self):
        x = torch.rand(1, 40, 40)
        self.assertTrue(torch.equal(T.RandomPhotometricHimax(p=0.0)(x, {})[0], x))

    def test_contrast_keeps_mean_and_scales_spread(self):
        x = 0.4 + 0.1 * torch.rand(1, 40, 40)
        y = self._only(contrast=(2.0, 2.0))(x, {})[0]
        self.assertAlmostEqual(float(y.mean()), float(x.mean()), places=3)
        self.assertAlmostEqual(float(y.std() / x.std()), 2.0, places=2)

    def test_brightness_is_additive_and_clamped(self):
        x = torch.full((1, 8, 8), 0.9)
        self.assertTrue(torch.allclose(self._only(brightness=(-0.2, -0.2))(x, {})[0], torch.full_like(x, 0.7)))
        self.assertTrue(torch.equal(self._only(brightness=(0.2, 0.2))(x, {})[0], torch.ones_like(x)))

    def test_gamma(self):
        x = torch.full((1, 8, 8), 0.25)
        self.assertTrue(torch.allclose(self._only(gamma=(0.5, 0.5))(x, {})[0], torch.full_like(x, 0.5)))

    def test_vignette_darkens_corners_not_centre(self):
        x = torch.ones(1, 65, 65)
        y = self._only(vignette_strength=(0.4, 0.4), vignette_radius=(0.0, 0.0))(x, {})[0]
        self.assertAlmostEqual(float(y[0, 32, 32]), 1.0, places=6)
        self.assertAlmostEqual(float(y[0, 0, 0]), 0.6, places=5)

    def test_blur_sigma_scales_with_width(self):
        aug = self._only(blur_sigma_px=3.0)
        seen = {}
        real = T.F.gaussian_blur

        def spy(img, kernel_size, sigma):
            seen["sigma"], seen["kernel"] = sigma[0], kernel_size[0]
            return real(img, kernel_size, sigma)

        with mock.patch.object(T.F, "gaussian_blur", side_effect=spy):
            aug(torch.rand(1, 128, 128), {})
        self.assertAlmostEqual(seen["sigma"], 2.4, places=6)
        self.assertEqual(seen["kernel"], 17)


if __name__ == "__main__":
    unittest.main()
