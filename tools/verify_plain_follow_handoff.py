#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


PROJECT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = PROJECT_DIR / "application" / "validation" / "manifest.json"
REQUIRED_CONTRACT = {
    "model_type": "plain_follow",
    "follow_head_type": "xbin9_size_bucket4",
    "input_shape": [1, 1, 128, 128],
    "output_count": 14,
    "result": "exact_match",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_manifest(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"Handoff manifest must be a JSON object: {path}")
    return payload


def verify_handoff(manifest_path: Path = DEFAULT_MANIFEST) -> list[str]:
    manifest_path = manifest_path.resolve()
    project_dir = manifest_path.parents[2]
    manifest = load_manifest(manifest_path)
    errors: list[str] = []

    for key, expected in REQUIRED_CONTRACT.items():
        actual = manifest.get(key)
        if actual != expected:
            errors.append(f"contract {key!r}: expected {expected!r}, got {actual!r}")

    checkpoint = manifest.get("checkpoint") or {}
    checkpoint_relative = checkpoint.get("bundled_path") or checkpoint.get("path")
    if not checkpoint_relative:
        errors.append("manifest checkpoint path is missing")
    else:
        checkpoint_path = project_dir / str(checkpoint_relative)
        if not checkpoint_path.is_file():
            errors.append(f"checkpoint is missing: {checkpoint_path}")
        else:
            expected_size = checkpoint.get("size_bytes")
            if expected_size is not None and checkpoint_path.stat().st_size != int(expected_size):
                errors.append(
                    f"checkpoint size mismatch: expected {expected_size}, "
                    f"got {checkpoint_path.stat().st_size}"
                )
            expected_hash = str(checkpoint.get("sha256") or "")
            actual_hash = sha256_file(checkpoint_path)
            if actual_hash != expected_hash:
                errors.append(
                    f"checkpoint SHA-256 mismatch: expected {expected_hash}, got {actual_hash}"
                )

    application_dir = manifest_path.parents[1]
    for relative_path, expected_hash in (manifest.get("artifacts") or {}).items():
        artifact_path = application_dir / str(relative_path)
        if not artifact_path.is_file():
            errors.append(f"application artifact is missing: {artifact_path}")
            continue
        actual_hash = sha256_file(artifact_path)
        if actual_hash != expected_hash:
            errors.append(
                f"artifact SHA-256 mismatch for {relative_path}: "
                f"expected {expected_hash}, got {actual_hash}"
            )

    output_path = application_dir / "validation" / "output.txt"
    if output_path.is_file():
        try:
            output_values = [int(token) for token in output_path.read_text(encoding="utf-8").split()]
        except ValueError as error:
            errors.append(f"golden output is not an integer tensor: {error}")
        else:
            expected_values = manifest.get("expected_output")
            if output_values != expected_values:
                errors.append(
                    f"golden output mismatch: manifest has {expected_values!r}, file has {output_values!r}"
                )
            if len(output_values) != int(manifest.get("output_count") or 0):
                errors.append(
                    f"golden output count mismatch: expected {manifest.get('output_count')}, "
                    f"got {len(output_values)}"
                )

    return errors


def main() -> None:
    errors = verify_handoff()
    if errors:
        details = "\n".join(f"- {error}" for error in errors)
        raise SystemExit(f"plain_follow handoff integrity check FAILED:\n{details}")
    print("plain_follow handoff integrity check: PASS")


if __name__ == "__main__":
    main()
