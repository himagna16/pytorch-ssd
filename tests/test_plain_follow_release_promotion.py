from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
import sys

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR / "export"))
from export.run_plain_follow_release import promote_verified_application


class PlainFollowReleasePromotionTests(unittest.TestCase):
    def test_promotion_preserves_handoff_readme_and_installs_golden_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "generated"
            destination = root / "application"
            expected_output = root / "output.txt"
            (source / "src").mkdir(parents=True)
            (source / "hex").mkdir()
            (source / "src" / "network.c").write_text("generated network\n", encoding="utf-8")
            (source / "src" / "pulp_nn_utils.c").write_text("generated helpers\n", encoding="utf-8")
            (source / "hex" / "inputs.hex").write_text("00\n", encoding="utf-8")
            destination.mkdir()
            (destination / "README.md").write_text("handoff notes\n", encoding="utf-8")
            expected_output.write_text("1 2 3\n", encoding="utf-8")

            promoted = promote_verified_application(
                source,
                destination,
                expected_output,
                validation_manifest={"result": "exact_match"},
            )

            self.assertEqual(destination.resolve(), promoted)
            self.assertEqual("generated network\n", (destination / "src" / "network.c").read_text())
            self.assertEqual("handoff notes\n", (destination / "README.md").read_text())
            self.assertEqual("1 2 3\n", (destination / "validation" / "output.txt").read_text())
            manifest = (destination / "validation" / "manifest.json").read_text()
            self.assertIn('"result": "exact_match"', manifest)
            self.assertIn('"src/network.c"', manifest)


if __name__ == "__main__":
    unittest.main()
