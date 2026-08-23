from __future__ import annotations

import unittest
from pathlib import Path

from tools.patch_gap8_bn_quant_int64 import MARKER, apply_patch_to_text


PROJECT_DIR = Path(__file__).resolve().parents[1]
GENERATED_UTILS = PROJECT_DIR / "export" / "plain_follow" / "application" / "src" / "pulp_nn_utils.c"


class PatchGap8BnQuantInt64Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.original = GENERATED_UTILS.read_text(encoding="utf-8")

    def test_patch_preserves_non_quant_generated_helpers(self) -> None:
        patched = apply_patch_to_text(self.original)

        self.assertIn(MARKER, patched)
        self.assertEqual(
            self.original.count("void pulp_nn_im2col_int8"),
            patched.count("void pulp_nn_im2col_int8"),
        )
        self.assertIn("pulp_nn_compare_and_replace_if_larger_int8", patched)
        self.assertIn("pulp_nn_avg_and_replace_int8", patched)
        self.assertIn("int64_t integer_image_phi", patched)

    def test_patch_is_idempotent(self) -> None:
        patched = apply_patch_to_text(self.original)
        self.assertEqual(patched, apply_patch_to_text(patched))

    def test_corrupted_marked_file_fails_loudly(self) -> None:
        patched = apply_patch_to_text(self.original)
        corrupted = patched.replace("pulp_nn_im2col_int8", "removed_im2col_helper")

        with self.assertRaisesRegex(RuntimeError, "pulp_nn_im2col_int8"):
            apply_patch_to_text(corrupted)


if __name__ == "__main__":
    unittest.main()
