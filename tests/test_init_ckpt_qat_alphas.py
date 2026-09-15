"""--init-ckpt from a QAT checkpoint must keep the checkpoint's learned PACT ranges.

Loading a QAT checkpoint into the unwrapped model drops every PACT range tensor
("unexpected keys"), and enable_quant_aware_finetune() then re-derives activation
ranges from --qat-calib-batches of training data, so the fine-tune starts from a
model that is not the one named by --init-ckpt. These tests pin the restore, and
pin that a non-QAT --init-ckpt is untouched by it.

Usage (nemoenv python, from inside pytorch_ssd_unstable):
  ../nemoenv/bin/python -m unittest tests.test_init_ckpt_qat_alphas -v
"""

from __future__ import annotations

import argparse
import sys
import unittest
from pathlib import Path

import torch

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

import train  # noqa: E402
from models.follow_model_factory import build_follow_model  # noqa: E402

DRONE = PROJECT_DIR.parent
QAT_CKPT = DRONE / "training/CHAMPION_qat_ep3_f1_8008.pth"
FP_CKPT = DRONE / "training/successor_confuser_ctrl_fp_nohn/plain_follow_epoch_001.pth"

PLAIN_FOLLOW_KWARGS = dict(
    model_type="plain_follow",
    input_channels=1,
    image_size=(128, 128),
    follow_head_type="xbin9_size_bucket4",
    stem_channels=16,
    stage_channels=(24, 32, 48),
    stem_mode="conv_bn_relu",
)


def qat_args(**overrides) -> argparse.Namespace:
    args = argparse.Namespace(
        model_type="plain_follow",
        follow_head_type="xbin9_size_bucket4",
        input_channels=1,
        height=128,
        width=128,
        quant_aware_finetune=True,
        qat_bits=8,
        qat_calib_batches=1,
        qat_train_activation_modules=None,
        init_ckpt_drop_qat_alphas=False,
    )
    for key, value in overrides.items():
        setattr(args, key, value)
    return args


def one_batch_loader():
    torch.manual_seed(0)
    return [(torch.randn(2, 1, 128, 128), {})]


class InitCheckpointQatAlphaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        for path in (QAT_CKPT, FP_CKPT):
            if not path.is_file():
                raise unittest.SkipTest(f"checkpoint not available: {path}")

    def test_qat_checkpoint_reports_its_dropped_pact_tensors(self) -> None:
        model = build_follow_model(**PLAIN_FOLLOW_KWARGS)
        _payload, pact_state = train.load_init_checkpoint(
            model, QAT_CKPT, torch.device("cpu")
        )
        self.assertEqual(59, len(pact_state))
        self.assertIn("stem.relu.alpha", pact_state)

    def test_every_dropped_key_is_recognised_as_pact_state(self) -> None:
        # PACT_STATE_SUFFIXES must cover everything quantize_pact() adds, or the
        # restore silently reinstates only part of the checkpoint's ranges. The
        # suffixes also match BatchNorm's running stats, so this only holds
        # because the selection is restricted to keys the float model rejected.
        model = build_follow_model(**PLAIN_FOLLOW_KWARGS)
        payload = torch.load(QAT_CKPT, map_location="cpu")
        state_dict = train.checkpoint_state_dict(payload)
        _missing, unexpected = model.load_state_dict(state_dict, strict=False)
        pact_state = train.dropped_pact_state(state_dict, unexpected)
        self.assertEqual(sorted(unexpected), sorted(pact_state))

    def test_non_qat_checkpoint_reports_nothing_to_restore(self) -> None:
        model = build_follow_model(**PLAIN_FOLLOW_KWARGS)
        _payload, pact_state = train.load_init_checkpoint(
            model, FP_CKPT, torch.device("cpu")
        )
        self.assertEqual({}, pact_state)

    def test_finetune_starts_from_the_checkpoints_own_ranges(self) -> None:
        model = build_follow_model(**PLAIN_FOLLOW_KWARGS)
        _payload, pact_state = train.load_init_checkpoint(
            model, QAT_CKPT, torch.device("cpu")
        )
        model_q = train.enable_quant_aware_finetune(
            model, one_batch_loader(), torch.device("cpu"), qat_args(),
            init_pact_state=pact_state,
        )
        restored = model_q.state_dict()
        for key, value in pact_state.items():
            self.assertIn(key, restored)
            self.assertTrue(torch.equal(value, restored[key].cpu()), msg=key)

    def test_drop_flag_reproduces_the_calibrated_ranges(self) -> None:
        model = build_follow_model(**PLAIN_FOLLOW_KWARGS)
        _payload, pact_state = train.load_init_checkpoint(
            model, QAT_CKPT, torch.device("cpu")
        )
        model_q = train.enable_quant_aware_finetune(
            model, one_batch_loader(), torch.device("cpu"),
            qat_args(init_ckpt_drop_qat_alphas=True),
            init_pact_state=pact_state,
        )
        calibrated = model_q.state_dict()
        differing = [
            key for key, value in pact_state.items()
            if not torch.equal(value, calibrated[key].cpu())
        ]
        self.assertTrue(differing, "the drop path must not restore the checkpoint's ranges")


if __name__ == "__main__":
    unittest.main()
