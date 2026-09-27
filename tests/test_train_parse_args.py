"""train.parse_args() must work with no arguments (default --model-type hybrid_follow).

The hybrid_follow branch of parse_args() fills in default stage channels from
HYBRID_FOLLOW_BASE_STAGE_CHANNELS; train.py used that name without importing it,
so a bare `python train.py` died with a NameError before training started.

Usage (nemoenv python, from inside pytorch_ssd_unstable):
  ../nemoenv/bin/python -m unittest tests.test_train_parse_args -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

import train  # noqa: E402
from models.hybrid_follow_net import HYBRID_FOLLOW_BASE_STAGE_CHANNELS  # noqa: E402


class ParseArgsDefaultsTest(unittest.TestCase):
    def test_no_arguments(self):
        with mock.patch.object(sys, "argv", ["train.py"]):
            args = train.parse_args()
        self.assertEqual(args.model_type, "hybrid_follow")
        self.assertEqual(args.stage_channels, tuple(HYBRID_FOLLOW_BASE_STAGE_CHANNELS))


if __name__ == "__main__":
    unittest.main()
