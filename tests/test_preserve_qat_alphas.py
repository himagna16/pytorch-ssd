"""--preserve-qat-alphas: the release keeps the PACT ranges learned in QAT.

The checkpoint tests need the local training runs (not in git) and skip without
them. Run from the project root:

    ../nemoenv/bin/python -m unittest tests.test_preserve_qat_alphas -v
"""
from __future__ import annotations

import argparse
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

import torch

PROJECT_DIR = Path(__file__).resolve().parents[1]
for extra in (PROJECT_DIR, PROJECT_DIR / "export", PROJECT_DIR / "nemo"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

import nemo  # noqa: E402

from export.evaluate_quant_native_follow import (  # noqa: E402
    apply_learned_qat_state,
    build_quantized_models,
    compare_range_snapshots,
    load_learned_qat_state,
    pact_range_snapshot,
)
from export.run_plain_follow_release import (  # noqa: E402
    checkpoint_qat_only_keys,
    quantization_ranges_record,
)
from export_nemo_quant_core import patch_model_to_graph_compat  # noqa: E402
from models.follow_model_factory import (  # noqa: E402
    build_follow_model,
    build_follow_model_from_checkpoint,
    follow_model_kwargs_from_metadata,
)

TRAINING_DIR = PROJECT_DIR.parent / "training"
CONFUSER_QAT = TRAINING_DIR / "successor_confuser_qat_hn3" / "plain_follow_epoch_002.pth"
CONFUSER_FLOAT = TRAINING_DIR / "successor_confuser_qat_hn3" / "plain_follow_epoch_002_eval.pth"
CHAMPION_QAT = TRAINING_DIR / "successor_qat" / "plain_follow_epoch_003.pth"
REP16_DIR = (
    PROJECT_DIR / "logs" / "hybrid_follow_val" / "1_real_image_validation" / "input_sets" / "representative16_20260324"
)
HAVE_CKPTS = all(path.is_file() for path in (CONFUSER_QAT, CONFUSER_FLOAT, CHAMPION_QAT))
patch_model_to_graph_compat()  # NEMO's graph tracer needs this shim on torch 2.x


class RangeSnapshotTests(unittest.TestCase):
    def test_compare_flags_only_changed_ranges(self) -> None:
        reference = {"a": {"alpha": 1.5}, "b": {"W_alpha": 0.25, "W_beta": 0.5}}
        self.assertEqual(compare_range_snapshots(reference, deepcopy(reference)), [])
        changed = deepcopy(reference)
        changed["b"]["W_beta"] = 0.5000001
        rows = compare_range_snapshots(reference, changed)
        self.assertEqual([(row["module"], row["param"]) for row in rows], [("b", "W_beta")])
        rows = compare_range_snapshots(reference, {"a": {"alpha": 1.5}})
        self.assertEqual({(row["module"], row["param"]) for row in rows}, {("b", "W_alpha"), ("b", "W_beta")})

    def test_ranges_record_refuses_a_policy_mismatch(self) -> None:
        summary = {"calibration": {"alpha_policy": "calibrated"}}
        record = quantization_ranges_record(summary, preserve_qat_alphas=False, float_ckpt_path=Path("x.pth"))
        self.assertEqual(record["alpha_policy"], "calibrated")
        with self.assertRaises(RuntimeError):
            quantization_ranges_record(summary, preserve_qat_alphas=True, float_ckpt_path=Path("x.pth"))
        # A summary written before this option existed has no alpha_policy: it was calibrated.
        self.assertEqual(
            quantization_ranges_record({}, preserve_qat_alphas=False, float_ckpt_path=Path("x.pth"))["alpha_policy"],
            "calibrated",
        )


@unittest.skipUnless(HAVE_CKPTS, "local QAT training checkpoints not present")
class CheckpointProvenanceTests(unittest.TestCase):
    def test_qat_only_keys_tell_full_from_stripped(self) -> None:
        full = torch.load(CONFUSER_QAT, map_location="cpu")
        stripped = torch.load(CONFUSER_FLOAT, map_location="cpu")
        keys = checkpoint_qat_only_keys(full)
        self.assertEqual(len(keys), 59)
        self.assertEqual(sum(key.endswith(".alpha") and not key.endswith("W_alpha") and not key.endswith("x_alpha") for key in keys), 7)
        self.assertEqual(checkpoint_qat_only_keys(stripped), [])

    def test_loads_matching_pair_and_counts_keys(self) -> None:
        model_fp = build_follow_model_from_checkpoint(CONFUSER_FLOAT, torch.device("cpu")).eval()
        state, report = load_learned_qat_state(CONFUSER_QAT, model_fp, float_ckpt_path=CONFUSER_FLOAT)
        self.assertTrue(report["float_keys_bit_identical"])
        self.assertEqual(report["qat_only_key_count"], 59)
        self.assertEqual(report["qat_only_key_suffix_counts"]["alpha"], 7)
        self.assertEqual(len(report["qat_checkpoint_sha256"]), 64)
        self.assertIn("stem.relu.alpha", state)

    def test_refuses_ranges_from_a_different_checkpoint(self) -> None:
        model_fp = build_follow_model_from_checkpoint(CONFUSER_FLOAT, torch.device("cpu")).eval()
        with self.assertRaisesRegex(RuntimeError, "disagree on"):
            load_learned_qat_state(CHAMPION_QAT, model_fp, float_ckpt_path=CONFUSER_FLOAT)

    def test_refuses_a_stripped_checkpoint_as_the_qat_source(self) -> None:
        model_fp = build_follow_model_from_checkpoint(CONFUSER_FLOAT, torch.device("cpu")).eval()
        with self.assertRaisesRegex(RuntimeError, "not a QAT checkpoint"):
            load_learned_qat_state(CONFUSER_FLOAT, model_fp, float_ckpt_path=CONFUSER_FLOAT)

    def test_strict_load_rejects_a_different_graph(self) -> None:
        model_fp = build_follow_model_from_checkpoint(CONFUSER_FLOAT, torch.device("cpu")).eval()
        state, _ = load_learned_qat_state(CONFUSER_QAT, model_fp, float_ckpt_path=CONFUSER_FLOAT)
        model_q = nemo.transform.quantize_pact(deepcopy(model_fp), dummy_input=torch.randn(1, 1, 128, 128))
        model_q.change_precision(bits=8, scale_weights=True, scale_activations=True)
        broken = dict(state)
        broken["not_a_layer.alpha"] = torch.ones(1)
        with self.assertRaisesRegex(RuntimeError, "does not match the wrapped model"):
            apply_learned_qat_state(model_q, broken)


@unittest.skipUnless(HAVE_CKPTS and REP16_DIR.is_dir(), "checkpoints or rep16 images not present")
class PreservedFakeQuantMatchesTrainingTests(unittest.TestCase):
    """The preserved FQ model must BE the network QAT trained, output for output."""

    @classmethod
    def setUpClass(cls) -> None:
        payload = torch.load(CONFUSER_QAT, map_location="cpu")
        metadata = torch.load(CONFUSER_FLOAT, map_location="cpu")
        args = argparse.Namespace(
            calib_dir=str(REP16_DIR),
            calib_manifest=None,
            calib_batches=2,
            calib_seed=0,
            eps_in=1.0 / 255.0,
            bits=8,
            stem_activation_module="auto",
            stem_activation_policy="none",
            stem_activation_percentile=99.9,
            id_explicit_eps_dict=False,
            id_local_scale_module=None,
            id_local_scale_factor=None,
            preserve_qat_alphas=True,
            qat_ckpt=str(CONFUSER_QAT),
        )
        cls.models = build_quantized_models(CONFUSER_FLOAT, args, metadata)
        # Reference: how sweep_fq_ckpt.py --mode qat rebuilds the trained network.
        reference = build_follow_model(**follow_model_kwargs_from_metadata(payload)).eval()
        reference = nemo.transform.quantize_pact(reference, dummy_input=torch.randn(1, 1, 128, 128)).eval()
        reference.change_precision(bits=8, scale_weights=True, scale_activations=True)
        reference.load_state_dict(payload["state_dict"], strict=True)
        cls.reference = reference.eval()
        torch.manual_seed(0)
        cls.inputs = torch.round(torch.rand(8, 1, 128, 128) * 255.0) / 255.0

    def test_fq_outputs_equal_the_trained_qat_network(self) -> None:
        _, model_fq, _, _, context = self.models
        with torch.no_grad():
            self.assertTrue(torch.equal(model_fq(self.inputs), self.reference(self.inputs)))
        self.assertEqual(context["alpha_policy"], "learned_qat")

    def test_report_records_learned_and_calibrated_ranges(self) -> None:
        context = self.models[4]
        report = context["qat_alpha_preservation"]
        self.assertTrue(report["fq_ranges_match_checkpoint"])
        self.assertEqual(report["qd_stage_activation_alpha_changes"], [])
        ranges = report["ranges"]["stem.relu"]
        self.assertNotEqual(ranges["learned"]["alpha"], ranges["calibrated"]["alpha"])

    def test_id_stage_carries_the_learned_output_range(self) -> None:
        # The integer network's output quantum is set by the last activation's range, so the
        # learned stage3.refine alpha (not a recalibrated one) must reach the ID stage.
        from export.evaluate_quant_native_follow import resolve_plain_follow_id_output_eps

        _, model_fq, _, model_id, _ = self.models
        learned_alpha = pact_range_snapshot(model_fq)["stage3.refine.relu"]["alpha"]
        report = resolve_plain_follow_id_output_eps(model_id, input_eps=1.0 / 255.0)
        self.assertAlmostEqual(float(report["eps_in"]), learned_alpha / 255.0, places=6)

if __name__ == "__main__":
    unittest.main()
