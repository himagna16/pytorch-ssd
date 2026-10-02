#!/usr/bin/env python3
"""Tests for real_scoreboard.py on a synthetic frames tree, with a stub network.

    ~/Downloads/drone/trainenv/bin/python -m unittest tools/real_frames/test_real_scoreboard.py

The stub reads its answer (confidence, x-bin) from two pixels each frame carries
(test_index_frames.write_frame), so every number below is known in advance. One test runs
the REAL chip arm (score_real_frames.ChipModel) on the same tree, and is skipped with a
note if doryenv or the champion ONNX is missing.
"""
from __future__ import annotations

import csv
import json
import math
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import index_frames as IX  # noqa: E402
import real_scoreboard as RS  # noqa: E402
import score_real_frames as S  # noqa: E402
from test_index_frames import EPS, H, T0, write_clip  # noqa: E402

import perception_backends as PB  # noqa: E402  (on sys.path via score_real_frames)


class Stub:
    """Stands in for score_real_frames.ChipModel: same interface, answers from pixels."""
    eps = EPS
    info = {"onnx": "/nowhere/stub/quant_eval/model_id_dory.onnx", "onnx_sha1": "5705b0000000"}

    def __init__(self):
        self.closed = False
        self.calls = 0

    @staticmethod
    def preprocess(gray):
        return gray

    def __call__(self, batch):
        out = []
        for g in batch:
            self.calls += 1
            conf = min(max(float(g[H - 1, 0]) / 100.0, 0.01), 0.99)
            xb = int(g[H - 1, 1])
            raw = int(round(math.log(conf / (1 - conf)) / self.eps))    # the chip's integer
            out.append({"visibility_confidence": 1 / (1 + math.exp(-raw * self.eps)), "vis_raw": raw,
                        "x_bin_index": float(xb), "x_soft": -1 + (2 * xb + 1) / 9, "size_bucket_index": 1.0})
        return out

    def close(self):
        self.closed = True


def build(root: Path):
    """Synthetic tree. Expected results are in the class docstrings below."""
    run = root / "2026-02-01" / "grid_capture_100000"
    t = T0 + 40 * 86400
    write_clip(run, "d2.44_b-14_vis1_subj-p01_light-room_take1", t + 10, [40] * 6,
               [(.9, 2), (.9, 3), (.9, 5), (.5, 2), (.9, 1), (.76, 2)])                  # A: hit 4/6, exact 2/6
    write_clip(run, "d2.44_b0_vis1_subj-p01_light-room_take1", t + 20, [40] * 5, [(.2, 4)] * 5)   # B: 0
    write_clip(run, "d2.13_b15.9_vis1_subj-p01_light-room_take1", t + 30, [100] * 5, [(.95, 6)] * 5)  # C: 1
    write_clip(run, "d1.52_b-21.8_vis1_subj-p01_light-room_take1", t + 40, [40] * 3, [(.9, 1)] * 3)   # short
    write_clip(run, "vis0_subj-empty_light-room_take1", t + 50, [40] * 5,
               [(.9, 4), (.9, 4), (.2, 4), (.9, 4), (.9, 4)])                            # empty: streak 2
    write_clip(run, "d1.52_b0_vis1_subj-p01_light-room_take1", t + 60, [5] * 5, [(.9, 4)] * 5)   # near-black
    mir = root / "2026-02-01" / "camera_check_110000" / "mirror"
    stem = "d2.44_b-14_vis1_subj-p01_light-room_take1"
    write_clip(mir, stem, t + 100, [40] * 7, [(.9, 6)] + [(.9, 2)] * 6)                    # L: labels.csv
    names = sorted(p.name for p in mir.glob(f"{stem}_f*.png"))
    with open(mir / "labels.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["frame", "x_bin", "size_bucket", "in_fov", "drop_reason", "ignored_extra"])
        w.writerow([names[0], 6, 1, 1, "", "x"])
        w.writerow([names[1], "", "", 0, "", ""])
        w.writerow([names[2], 3, "", 1, "no pose", ""])
    # test split: p02 on another day; its empty clip reaches 3 in a row (lit guard failure)
    r2 = root / "2026-02-02" / "grid_capture_100000"
    write_clip(r2, "d2.44_b14_vis1_subj-p02_light-room_take1", t + 86400, [40] * 5, [(.9, 6)] * 5)
    write_clip(r2, "vis0_subj-empty_light-room_take1", t + 86500, [40] * 5,
               [(.2, 4), (.9, 4), (.9, 4), (.9, 4), (.2, 4)])
    write_clip(r2, "vis0_subj-chair_light-room_take1", t + 86600, [40] * 5, [(.2, 4)] * 5)


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="rsb_test_"))
        cls.root = cls.tmp / "frames"
        build(cls.root)
        cls.splits = cls.tmp / "splits.json"
        cls.splits.write_text(json.dumps({
            "persons": {"p01": {"pool": "train_dev"}, "p02": {"pool": "test"}},
            "train_dev_sessions": {"p01": {"2026-02-01": "dev"}}}))
        cls.index = cls.root / "_index" / "index.csv"
        IX.write_index(IX.build_index(cls.root, IX.load_splits(cls.splits), []), cls.index)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def args(self, split="dev", name="run", extra=()):
        out = self.tmp / name
        return RS.build_parser().parse_args(
            ["--split", split, "--index", str(self.index), "--root", str(self.root),
             "--scoreboard", str(self.tmp / f"{name}_SCOREBOARD.md"), "--json", str(out / "sb.json"),
             "--frames-csv", str(out / "frames.csv"), "--boot", "2000", *extra])


class DevSplitTest(Base):
    """dev: metric clips A (4/6), B (0), C (1), L (5/5 after labels.csv) -> headline 2/3.
    exact: A 2/6, B 0, C 1, L 1 -> 7/12. Guard: empty (streak 2, pass) + near-black (fail)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.stub = Stub()
        cls.out = RS.run(cls.args(cls, "dev", "dev"), model=cls.stub)
        cls.clips = {c["clip_id"].split("/")[-1] + ("@mirror" if "/mirror/" in c["clip_id"] else ""): c
                     for c in cls.out["clips"]}

    def test_headline_and_exact(self):
        self.assertEqual(self.out["headline"]["n_clips"], 4)
        self.assertAlmostEqual(self.out["headline"]["value"], (4 / 6 + 0 + 1 + 1) / 4)
        self.assertAlmostEqual(self.out["exact_bin"]["value"], (2 / 6 + 0 + 1 + 1) / 4)
        lo, hi = self.out["headline"]["ci95"]
        self.assertLessEqual(lo, self.out["headline"]["value"])
        self.assertGreaterEqual(hi, self.out["headline"]["value"])

    def test_per_clip_values(self):
        a = self.clips["d2.44_b-14_vis1_subj-p01_light-room_take1"]
        self.assertEqual(a["grid_xbin"], 2)
        self.assertAlmostEqual(a["hit"], 4 / 6)
        self.assertAlmostEqual(a["hit_exact"], 2 / 6)
        self.assertEqual(self.clips["d2.13_b15.9_vis1_subj-p01_light-room_take1"]["grid_xbin"], 6)

    def test_labels_csv_overrides_frame_by_frame(self):
        c = self.clips["d2.44_b-14_vis1_subj-p01_light-room_take1@mirror"]
        self.assertEqual(c["label_status"], {"labelled": 5, "out_of_view": 1, "dropped": 1})
        self.assertEqual(c["label_sources"], ["grid_mark", "labels_csv"])
        self.assertEqual(c["hit"], 1.0)
        self.assertEqual(c["role"], "metric")

    def test_short_clip_excluded_and_listed(self):
        short = self.clips["d1.52_b-21.8_vis1_subj-p01_light-room_take1"]
        self.assertEqual(short["role"], "excluded")
        self.assertTrue(any("d1.52_b-21.8" in x["clip_id"] for x in self.out["excluded"]))

    def test_near_black_goes_to_guard_not_metric(self):
        nb = self.clips["d1.52_b0_vis1_subj-p01_light-room_take1"]
        self.assertEqual((nb["role"], nb["guard_class"], nb["max_streak"]), ("guard", "near_black", 5))
        g = self.out["guard"]
        self.assertFalse(g["pass"])
        self.assertTrue(g["lit_pass"])
        self.assertEqual(g["by_class"], {"empty": 1, "near_black": 1})
        self.assertEqual([f["class"] for f in g["failing"]], ["near_black"])
        self.assertEqual(self.clips["vis0_subj-empty_light-room_take1"]["max_streak"], 2)

    def test_breakdowns_and_coverage(self):
        b = self.out["breakdowns"]["exposure_regime"]
        self.assertEqual((b["dim"]["n_clips"], b["bright"]["n_clips"]), (3, 1))
        self.assertAlmostEqual(b["bright"]["hit"], 1.0)
        cov = self.out["coverage"]
        self.assertFalse(cov["met"])
        self.assertEqual(cov["people"], ["p01"])
        self.assertFalse(cov["checks"]["people >= 3"])

    def test_outputs(self):
        sb = (self.tmp / "dev_SCOREBOARD.md").read_text()
        self.assertEqual(sb.count("| date | model |"), 1)
        rows = [ln for ln in sb.splitlines() if ln.startswith("| 20")]
        self.assertEqual(len(rows), 1)
        self.assertIn("| dev | 4 / 2 | 66.7 [", rows[0])
        self.assertIn("| FAIL | NOT met |", rows[0])
        self.assertIn("provisional", rows[0])
        js = json.loads((self.tmp / "dev" / "sb.json").read_text())
        self.assertTrue(js["labels_provisional"])
        self.assertEqual(js["model"]["enter_raw"], S.raw_threshold(0.75, EPS))
        self.assertEqual(js["model"]["name"], "stub")
        with open(self.tmp / "dev" / "frames.csv") as f:
            fr = list(csv.DictReader(f))
        self.assertEqual(len(fr), sum(c["n_frames"] for c in self.out["clips"]))
        self.assertTrue(self.stub.closed)

    def test_paired_baseline_against_itself_is_zero(self):
        out = RS.run(self.args("dev", "dev2", ["--no-append", "--baseline-json",
                                               str(self.tmp / "dev" / "sb.json")]), model=Stub())
        v = out["vs_baseline"]
        self.assertEqual(v["n_common_clips"], 4)
        self.assertEqual(v["diff_hit"], 0.0)


class TestSplitTest(Base):
    def test_test_split_only_and_lit_guard_failure(self):
        out = RS.run(self.args("test", "test", ["--no-append"]), model=Stub())
        ids = [c["clip_id"] for c in out["clips"]]
        self.assertTrue(all(i.startswith("2026-02-02/") for i in ids), ids)
        self.assertEqual(out["headline"]["n_clips"], 1)
        self.assertEqual(out["headline"]["value"], 1.0)
        self.assertEqual(out["headline"]["ci95"], [None, None])      # one clip: no interval
        g = out["guard"]
        self.assertFalse(g["pass"])
        self.assertFalse(g["lit_pass"])
        self.assertEqual(g["by_class"], {"clutter": 1, "empty": 1})
        self.assertEqual(out["coverage"]["clutter_clips"], 1)
        self.assertFalse(out["coverage"]["checks"]["both regimes (dim, bright)"])

    def test_missing_split_exits(self):
        with self.assertRaises(SystemExit):
            RS.run(self.args("train", "train", ["--no-append"]), model=Stub())


class GuardsAgainstBadInputTest(Base):
    def edited_index(self, fn):
        rows = IX.read_index(self.index)
        fn(rows)
        p = self.tmp / "edited_index.csv"
        with open(p, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=IX.COLUMNS)
            w.writeheader()
            w.writerows(rows)
        return p

    def test_stale_index_is_refused(self):
        def bump(rows):
            rows[0]["n_frames"] = str(int(rows[0]["n_frames"]) + 1)
        a = self.args("dev", "stale", ["--no-append"])
        a.index = self.edited_index(bump)
        with self.assertRaises(SystemExit):
            RS.run(a, model=Stub())

    def test_mixed_streams_refused_unless_allowed(self):
        def other_stream(rows):
            for r in rows:
                if r["split"] == "dev" and r["kind"] == "person":
                    r["stream_w"], r["stream_h"] = "324", "244"
                    break
        a = self.args("dev", "mixed", ["--no-append"])
        a.index = self.edited_index(other_stream)
        with self.assertRaises(SystemExit):
            RS.run(a, model=Stub())
        a.allow_mixed_streams = True
        out = RS.run(a, model=Stub())
        self.assertEqual(out["headline"]["n_clips"], 4)

    def test_scoreboard_header_written_once(self):
        a = self.args("dev", "twice")
        RS.run(a, model=Stub())
        RS.run(a, model=Stub())
        sb = a.scoreboard.read_text()
        self.assertEqual(sb.count("| date | model |"), 1)
        self.assertEqual(len([ln for ln in sb.splitlines() if ln.startswith("| 20")]), 2)


class PiecesTest(unittest.TestCase):
    def test_max_streak(self):
        self.assertEqual(RS.max_streak([1, 1, 0, 1, 1, 1, 0]), 3)
        self.assertEqual(RS.max_streak([]), 0)

    def test_frame_label_rules(self):
        self.assertEqual(RS.frame_label(2, None), (2, None, "labelled", "grid_mark"))
        self.assertEqual(RS.frame_label(None, None)[2], "unlabelled")
        self.assertEqual(RS.frame_label(2, {"x_bin": "7", "size_bucket": "2"}), (7, 2, "labelled", "labels_csv"))
        self.assertEqual(RS.frame_label(2, {"x_bin": "7", "in_fov": "0"})[2], "out_of_view")
        self.assertEqual(RS.frame_label(2, {"x_bin": "7", "drop_reason": "gap"})[2], "dropped")
        self.assertEqual(RS.frame_label(2, {"x_bin": ""})[2], "unlabelled")
        with self.assertRaises(ValueError):
            RS.frame_label(2, {"x_bin": "9", "frame": "f.png", "_source": "x"})

    def test_labelbook_needs_clip_id_for_duplicate_names(self):
        rows = [{"frame": "a.png", "x_bin": "1", "_source": "one"}, {"frame": "a.png", "x_bin": "2", "_source": "two"}]
        with self.assertRaises(ValueError):
            RS.LabelBook(rows).get("c1", "a.png")
        rows[1]["clip_id"] = "c2"
        self.assertEqual(RS.LabelBook(rows).get("c2", "a.png")["x_bin"], "2")
        self.assertEqual(RS.LabelBook(rows).get("c1", "a.png")["x_bin"], "1")

    def test_labels_csv_needs_frame_and_x_bin(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            (tmp / "labels.csv").write_text("frame,bearing\na.png,3\n")
            with self.assertRaises(ValueError):
                RS.read_labels_csv(tmp / "labels.csv")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_bootstrap(self):
        v = [0.0, 0.5, 1.0, 0.25]
        m, lo, hi = RS.bootstrap_ci(v, 4000, 0)
        self.assertAlmostEqual(m, np.mean(v))
        self.assertLess(lo, m)
        self.assertGreater(hi, m)
        self.assertEqual(RS.bootstrap_ci(v, 4000, 0), (m, lo, hi))     # seeded: reproducible
        self.assertEqual(RS.bootstrap_ci([0.3], 100, 0), (0.3, None, None))
        self.assertEqual(RS.bootstrap_ci([], 100, 0), (None, None, None))
        self.assertEqual(RS.cluster_bootstrap_ci([1, 2], ["a", "a"]), (None, None))
        clo, chi = RS.cluster_bootstrap_ci(v, ["a", "a", "b", "b"], 2000, 0)
        self.assertLessEqual(clo, chi)

    def test_integer_enter_test(self):
        """The enter bar is the firmware's integer test: a raw 1 below ceil(logit(0.75)/eps) fails."""
        enter = S.raw_threshold(0.75, EPS)
        self.assertEqual(enter, 5467)


@unittest.skipUnless(PB.DEFAULT_ONNX.is_file() and PB.DEFAULT_DORY_PYTHON.is_file(),
                     "chip arm not available (doryenv or the champion ONNX missing)")
class RealChipSmokeTest(Base):
    def test_real_chip_arm_runs_end_to_end(self):
        out = RS.run(self.args("dev", "chip", ["--no-append"]))
        self.assertEqual(out["model"]["onnx_sha1"], S.sha1_of(PB.DEFAULT_ONNX))
        self.assertEqual(out["model"]["enter_raw"], 5467)
        self.assertEqual(out["model"]["name"], "plain_follow_prod_qat_v3")
        self.assertEqual(out["headline"]["n_clips"], 4)
        self.assertIsNotNone(out["headline"]["value"])


if __name__ == "__main__":
    unittest.main()
