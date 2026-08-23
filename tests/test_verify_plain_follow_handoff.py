from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from tools.verify_plain_follow_handoff import verify_handoff


class VerifyPlainFollowHandoffTests(unittest.TestCase):
    def test_valid_handoff_passes_and_tampering_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            application = root / "application"
            validation = application / "validation"
            artifacts = root / "artifacts"
            (application / "src").mkdir(parents=True)
            validation.mkdir()
            artifacts.mkdir()

            network = application / "src" / "network.c"
            network.write_text("network\n", encoding="utf-8")
            output = validation / "output.txt"
            expected_output = list(range(14))
            output.write_text(" ".join(str(value) for value in expected_output) + "\n", encoding="utf-8")
            checkpoint = artifacts / "model.pth"
            checkpoint.write_bytes(b"checkpoint")

            manifest = {
                "model_type": "plain_follow",
                "follow_head_type": "xbin9_size_bucket4",
                "input_shape": [1, 1, 128, 128],
                "output_count": 14,
                "result": "exact_match",
                "checkpoint": {
                    "bundled_path": "artifacts/model.pth",
                    "size_bytes": checkpoint.stat().st_size,
                    "sha256": hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
                },
                "artifacts": {
                    "src/network.c": hashlib.sha256(network.read_bytes()).hexdigest(),
                    "validation/output.txt": hashlib.sha256(output.read_bytes()).hexdigest(),
                },
                "expected_output": expected_output,
            }
            manifest_path = validation / "manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            self.assertEqual([], verify_handoff(manifest_path))

            network.write_text("tampered\n", encoding="utf-8")
            self.assertTrue(any("artifact SHA-256 mismatch" in error for error in verify_handoff(manifest_path)))


if __name__ == "__main__":
    unittest.main()
