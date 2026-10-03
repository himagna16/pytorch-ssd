#!/usr/bin/env python3
"""Tests for index_frames.py on a synthetic ~/drone_frames tree built in a temp folder.

    ~/Downloads/drone/trainenv/bin/python -m unittest tools/real_frames/test_index_frames.py

No real frames are read. The tree mimics what grid_capture.sh, camera_check.sh and
tools/lighthouse/record_session.py write: labelled cpx_grab.py names, clip.json files,
run logs with start headers (including a resumed run = a second power-up), unlabelled
check frames, a Lighthouse session, and the folders that must be skipped.
"""
from __future__ import annotations

import csv
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import index_frames as IX  # noqa: E402

W, H = 162, 122
T0 = time.mktime((2026, 1, 1, 12, 0, 0, 0, 0, -1))      # local time, like the run logs
EPS = 2.009823510888964e-4


def date_header(t: float) -> str:
    """What `date` prints (e.g. 'Thu Jan  1 12:00:00 CST 2026'), which the scripts log."""
    return time.strftime("%a %b %e %H:%M:%S %Z %Y", time.localtime(t))


def write_frame(path: Path, value: int, code=None, sat_row: bool = False):
    """A uniform frame. `code` = (conf, x_bin) writes a stub-model instruction into two
    pixels (the scoreboard tests' stub reads them back); `sat_row` puts one row at 191."""
    a = np.full((H, W), value, np.uint8)
    if sat_row:
        a[0, :] = 191
    if code is not None:
        conf, xb = code
        a[H - 1, 0] = int(round(conf * 100))
        a[H - 1, 1] = xb
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(a).save(path)


def write_clip(folder: Path, stem: str, t0: float, values, codes=None, start_no=1, clip_json=True,
               sat_row=False):
    """One cpx_grab.py clip: <stem>_f00001_t<unix>.png ... plus <stem>_clip.json."""
    for i, v in enumerate(values):
        code = codes[i] if codes else None
        write_frame(folder / f"{stem}_f{start_no + i:05d}_t{t0 + 0.5 * i:.3f}.png", v, code, sat_row)
    if clip_json:
        (folder / f"{stem}_clip.json").write_text(json.dumps({
            "labels": stem, "saved": len(values), "stream_fps": 2.12, "formats": [0],
            "sizes": [[W, H]], "bayer": False, "pixel_provenance": ["raw"]}))


def build_tree(root: Path) -> dict:
    """The synthetic tree. Returns facts the tests check against."""
    f = {}
    # --- 2026-01-01: p01 (dev). A grid run resumed once (two power-ups).
    run = root / "2026-01-01" / "grid_capture_120000"
    t_resume = T0 + 1800
    write_clip(run, "vis0_subj-empty_light-room_take1", T0 + 60, [40] * 6)
    write_clip(run, "d2.44_b-14_vis1_subj-p01_light-room_take1", T0 + 120, [40] * 6, sat_row=True)
    write_clip(run, "d1.52_b0_vis1_subj-p01_light-room_take1", t_resume + 60, [90] * 6)
    (run / "grid_capture.log").write_text(
        f"== grid capture, {date_header(T0)}  subject p01  light room  drone 09  folder: {run}\n"
        "== camera exposure check: mean brightness 40 (0-255)\n"
        "connected to tcp://192.168.4.1:5000  labels: vis0_subj-empty_light-room_take1\n"
        "connected to tcp://192.168.4.1:5000  labels: d2.44_b-14_vis1_subj-p01_light-room_take1\n"
        "connected to tcp://192.168.4.1:5000  labels: d1.52_b0_vis1_subj-p01_light-room_take1\n"
        "done: 0 saved\n"
        f"== grid capture, {date_header(t_resume)}  subject p01  light room  drone unknown  folder: {run}\n"
        "connected to tcp://192.168.4.1:5000  labels: d1.52_b0_vis1_subj-p01_light-room_take1\n")
    f["grid_run"] = run
    # camera_check: unlabelled check frames + a near-black labelled clip + a re-recorded stem
    cc = root / "2026-01-01" / "camera_check_130000"
    for i in range(3):
        write_frame(cc / "check" / f"frame_{i + 1:05d}_{T0 + 3600 + i:.3f}.png", 60)
    write_clip(cc / "mirror", "d2.44_b14_vis1_subj-p01_light-room_take1", T0 + 3700, [5] * 6)
    stem = "d2.44_b0_vis1_subj-p01_light-room_take1"
    write_clip(cc / "mirror", stem, T0 + 3800, [40] * 3, clip_json=False)
    write_clip(cc / "mirror", stem, T0 + 3900, [40] * 2, clip_json=False)   # f restarts at 1
    (cc / "camera_check.log").write_text(f"== camera check, {date_header(T0 + 3590)}  folder: {cc}\n")

    # --- 2026-01-02: p02 (test): grid, a clutter clip, and a Lighthouse session
    g2 = root / "2026-01-02" / "grid_capture_090000"
    t2 = T0 + 86400
    write_clip(g2, "vis0_subj-empty_light-room_take1", t2 + 10, [40] * 6)
    write_clip(g2, "vis0_subj-chair_light-room_take1", t2 + 20, [40] * 6)
    write_clip(g2, "d2.13_b15.9_vis1_subj-p02_light-room_take1", t2 + 30, [100] * 6)
    lh = root / "2026-01-02" / "lh_session_100000"
    for i in range(6):
        write_frame(lh / "frames" / f"frame_{i + 1:05d}_{t2 + 3600 + 0.5 * i:.3f}.png", 45)
    (lh / "meta.json").write_text(json.dumps({
        "subject": "p02", "uris": {"follower": "radio://0/80/2M/E7E7E7E709", "beacon": "radio://0/80/2M/E7E7E7E705"},
        "brightness": {"ok": True, "mean": 45.0}, "frames": {"n": 6, "fps": 2.0}}))
    with open(lh / "labels.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["frame", "frame_no", "drop_reason", "x_bin", "size_bucket", "in_fov"])
        for i in range(6):
            w.writerow([f"frame_{i + 1:05d}_{t2 + 3600 + 0.5 * i:.3f}.png", i + 1, "", 4, 1, 1])

    # --- 2026-01-03: p01 session NOT in splits.json; plus a run mixing p01 and p02
    g3 = root / "2026-01-03" / "grid_capture_080000"
    t3 = T0 + 2 * 86400
    write_clip(g3, "d2.44_b-14_vis1_subj-p01_light-room_take1", t3, [40] * 6)
    mix = root / "2026-01-03" / "grid_capture_090000"
    write_clip(mix, "vis0_subj-empty_light-room_take1", t3 + 3600, [40] * 6)
    write_clip(mix, "d2.44_b-14_vis1_subj-p01_light-room_take1", t3 + 3700, [40] * 6)
    write_clip(mix, "d2.44_b14_vis1_subj-p02_light-room_take1", t3 + 3800, [40] * 6)

    # --- things that must be skipped
    write_clip(root / "_rehearsal" / "2026-01-01" / "grid_capture_120000",
               "d2.44_b-14_vis1_subj-p01_light-room_take1", T0, [40] * 6)
    write_frame(root / "_index" / "old.png", 40)
    write_frame(root / ".hidden" / "x_vis1_f00001_t1.0.png", 40)
    write_frame(root / "2026-01-01" / "grid_capture_120000" / "._d2.44_b-14_vis1_subj-p01_light-room_take1_f00001_t1.0.png", 40)
    return f


def write_splits(path: Path, runs=None):
    path.write_text(json.dumps({
        "persons": {"p01": {"pool": "train_dev"}, "p02": {"pool": "test"}},
        "train_dev_sessions": {"p01": {"2026-01-01": "dev"}},
        "runs": runs or {}}))


def write_notes(path: Path):
    path.write_text("run,drone,location,notes\n"
                    "2026-01-0*/*,,room1,all synthetic\n"
                    "2026-01-02/*,,room2,second room\n"
                    "2026-01-01/grid_capture_120000,05,,conflicts with the log's 09\n")


def snapshot(root: Path) -> dict:
    out = {}
    for dp, dn, fn in os.walk(root):
        for n in fn:
            p = Path(dp) / n
            st = p.stat()
            out[str(p.relative_to(root))] = (st.st_size, st.st_mtime_ns)
    return out


class IndexTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="idx_test_"))
        cls.root = cls.tmp / "drone_frames"
        cls.facts = build_tree(cls.root)
        cls.splits = cls.tmp / "splits.json"
        write_splits(cls.splits)
        cls.notes = cls.tmp / "run_notes.csv"
        write_notes(cls.notes)
        cls.before = snapshot(cls.root)
        IX.main(["--root", str(cls.root), "--splits", str(cls.splits), "--run-notes", str(cls.notes)])
        cls.out = cls.root / "_index" / "index.csv"
        cls.rows = {r["clip_id"]: r for r in IX.read_index(cls.out)}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def row(self, suffix):
        hits = [r for k, r in self.rows.items() if k.endswith(suffix)]
        self.assertEqual(len(hits), 1, f"{suffix}: {sorted(self.rows)}")
        return hits[0]

    # -- read-only and where it writes
    def test_read_only_except_index(self):
        after = snapshot(self.root)
        new = sorted(set(after) - set(self.before))
        self.assertEqual(new, ["_index/index.csv", "_index/index_meta.json"])
        for k, v in self.before.items():
            self.assertEqual(after[k], v, f"{k} was modified")

    def test_refuses_to_write_inside_root_outside_index(self):
        with self.assertRaises(SystemExit):
            IX.main(["--root", str(self.root), "--splits", str(self.splits),
                     "--out", str(self.root / "2026-01-01" / "index.csv")])
        self.assertFalse((self.root / "2026-01-01" / "index.csv").exists())
        IX.check_out_path(self.root, self.tmp / "elsewhere" / "index.csv")   # outside root: fine

    def test_meta_written(self):
        meta = json.loads((self.root / "_index" / "index_meta.json").read_text())
        self.assertEqual(meta["n_clips"], len(self.rows))
        self.assertEqual(meta["splits_sha1"], IX.sha1_file(self.splits))

    # -- discovery
    def test_skips_rehearsal_index_hidden_and_sidecars(self):
        for k in self.rows:
            self.assertFalse(k.startswith(("_", ".")), k)
        self.assertEqual(sum(1 for k in self.rows if "grid_capture_120000" in k), 3)
        self.assertEqual(int(self.row("120000/d2.44_b-14_vis1_subj-p01_light-room_take1")["n_frames"]), 6)

    def test_clip_count_and_kinds(self):
        self.assertEqual(len(self.rows), 15)
        kinds = {k: r["kind"] for k, r in self.rows.items()}
        self.assertEqual(kinds["2026-01-01/camera_check_130000/check/check"], "unlabelled")
        self.assertEqual(self.row("090000/vis0_subj-chair_light-room_take1")["kind"], "clutter")
        self.assertEqual(self.row("2026-01-02/grid_capture_090000/vis0_subj-empty_light-room_take1")["kind"], "empty")
        self.assertEqual(self.row("lh_session_100000/frames/frames")["kind"], "person")

    def test_restarted_frame_numbers_make_two_clips(self):
        r1 = self.row("mirror/d2.44_b0_vis1_subj-p01_light-room_take1#run1")
        r2 = self.row("mirror/d2.44_b0_vis1_subj-p01_light-room_take1#run2")
        self.assertEqual((int(r1["n_frames"]), int(r2["n_frames"])), (3, 2))
        self.assertIn("shorter than the 5-frame clip minimum", r2["warnings"])

    # -- pixels
    def test_brightness_saturation_regimes(self):
        r = self.row("120000/d2.44_b-14_vis1_subj-p01_light-room_take1")
        self.assertEqual((r["stream_w"], r["stream_h"], r["sat_level"]), ("162", "122", "191"))
        self.assertAlmostEqual(float(r["frac_saturated"]), 1 / H, places=4)
        self.assertEqual(r["pixel_max"], "191")
        self.assertAlmostEqual(float(r["bright_mean"]), (40 * (H - 1) * W + 191 * W) / (H * W), places=2)
        self.assertEqual(r["exposure_regime"], "dim")
        self.assertEqual(self.row("d1.52_b0_vis1_subj-p01_light-room_take1")["exposure_regime"], "bright")
        nb = self.row("mirror/d2.44_b14_vis1_subj-p01_light-room_take1")
        self.assertEqual(nb["exposure_regime"], "near_black")
        self.assertEqual(float(nb["frac_near_black"]), 1.0)
        self.assertIn("near-black", nb["warnings"])
        self.assertEqual(nb["stream_format"], "raw")
        self.assertEqual(float(nb["stream_fps"]), 2.12)

    # -- labels
    def test_grid_label_is_existing_geometry_and_provisional(self):
        import score_real_frames as S
        r = self.row("120000/d2.44_b-14_vis1_subj-p01_light-room_take1")
        self.assertEqual(int(r["exp_xbin"]), S.x_to_bin(S.expected_x(-14.0, 70.0)))
        self.assertEqual(int(r["exp_xbin"]), 2)
        self.assertEqual(r["label_source"], "grid_mark")
        self.assertEqual(r["label_note"], IX.LABEL_NOTE)
        self.assertEqual((r["side"], float(r["dist_m"]), float(r["bearing_deg"])), ("left", 2.44, -14.0))
        self.assertEqual(self.row("d1.52_b0_vis1_subj-p01_light-room_take1")["exp_xbin"], "4")
        self.assertEqual(self.row("lh_session_100000/frames/frames")["label_source"], "labels_csv")
        self.assertEqual(self.row("2026-01-02/grid_capture_090000/vis0_subj-empty_light-room_take1")["exp_xbin"], "")

    # -- power-ups, drone, notes
    def test_power_ups_from_log_headers(self):
        before = self.row("120000/d2.44_b-14_vis1_subj-p01_light-room_take1")
        after = self.row("d1.52_b0_vis1_subj-p01_light-room_take1")
        self.assertEqual(before["power_up"], "2026-01-01/grid_capture_120000#p1")
        self.assertEqual(after["power_up"], "2026-01-01/grid_capture_120000#p2")
        self.assertEqual(float(before["powerup_brightness"]), 40.0)
        self.assertEqual(after["powerup_brightness"], "")

    def test_drone_log_wins_over_notes_and_conflict_is_warned(self):
        before = self.row("120000/d2.44_b-14_vis1_subj-p01_light-room_take1")
        after = self.row("d1.52_b0_vis1_subj-p01_light-room_take1")
        self.assertEqual(before["drone"], "09")
        self.assertIn("in run_notes.csv", before["warnings"])
        self.assertEqual(after["drone"], "05")          # log says 'unknown': the note fills it

    def test_location_from_notes_later_rows_win(self):
        self.assertEqual(self.row("120000/d2.44_b-14_vis1_subj-p01_light-room_take1")["location"], "room1")
        self.assertEqual(self.row("lh_session_100000/frames/frames")["location"], "room2")

    def test_lighthouse_session_meta(self):
        r = self.row("lh_session_100000/frames/frames")
        self.assertEqual((r["subject"], r["person_id"], r["drone"]), ("p02", "p02", "09"))
        self.assertEqual(float(r["powerup_brightness"]), 45.0)
        self.assertEqual(r["power_up"], "2026-01-02/lh_session_100000#p1")

    # -- splits
    def test_splits(self):
        s = {k: r["split"] for k, r in self.rows.items()}
        self.assertEqual(self.row("120000/d2.44_b-14_vis1_subj-p01_light-room_take1")["split"], "dev")
        self.assertEqual(self.row("2026-01-01/grid_capture_120000/vis0_subj-empty_light-room_take1")["split"], "dev")
        self.assertEqual(s["2026-01-01/camera_check_130000/check/check"], "dev")      # inherits from the run
        self.assertEqual(self.row("d2.13_b15.9_vis1_subj-p02_light-room_take1")["split"], "test")
        self.assertEqual(self.row("2026-01-02/grid_capture_090000/vis0_subj-empty_light-room_take1")["split"], "test")
        self.assertEqual(self.row("vis0_subj-chair_light-room_take1")["split"], "test")
        self.assertEqual(self.row("lh_session_100000/frames/frames")["split"], "test")
        unl = self.row("080000/d2.44_b-14_vis1_subj-p01_light-room_take1")
        self.assertEqual(unl["split"], "unassigned")
        self.assertIn("not assigned", unl["split_reason"])
        mixed_empty = self.row("2026-01-03/grid_capture_090000/vis0_subj-empty_light-room_take1")
        self.assertEqual(mixed_empty["split"], "conflict")
        self.assertEqual(self.row("2026-01-03/grid_capture_090000/d2.44_b14_vis1_subj-p02_light-room_take1")["split"],
                         "test")


class SplitRulesTest(unittest.TestCase):
    def sp(self, runs=None):
        return {"persons": {"p01": {"pool": "train_dev"}, "p02": {"pool": "test"}},
                "train_dev_sessions": {"p01": {"d1": "train"}}, "runs": runs or {}}

    def test_person_rules(self):
        self.assertEqual(IX.person_split(self.sp(), "p01", "d1")[0], "train")
        self.assertEqual(IX.person_split(self.sp(), "p01", "d2")[0], "unassigned")
        self.assertEqual(IX.person_split(self.sp(), "p02", "d9")[0], "test")
        self.assertEqual(IX.person_split(self.sp(), "p07", "d1")[0], "unassigned")

    def test_run_override(self):
        sp = self.sp({"d2/run": "dev"})
        self.assertEqual(IX.assign_split(sp, "d2", "d2/run", "", set(), set())[0], "dev")
        self.assertEqual(IX.assign_split(sp, "d2", "d2/run", "p01", {"p01"}, {"p01"})[0], "dev")
        sp = self.sp({"d2/run": "test"})
        self.assertEqual(IX.assign_split(sp, "d2", "d2/run", "p01", {"p01"}, set())[0], "conflict")
        sp = self.sp({"d2/run": "dev"})
        self.assertEqual(IX.assign_split(sp, "d2", "d2/run", "p02", {"p02"}, set())[0], "conflict")

    def test_no_person_inheritance(self):
        sp = self.sp()
        self.assertEqual(IX.assign_split(sp, "d1", "d1/r", "", set(), {"p01"})[0], "train")   # from the session
        self.assertEqual(IX.assign_split(sp, "d1", "d1/r", "", {"p02"}, {"p01", "p02"})[0], "test")   # run first
        self.assertEqual(IX.assign_split(sp, "d1", "d1/r", "", set(), set())[0], "unassigned")
        self.assertEqual(IX.assign_split(sp, "d1", "d1/r", "", {"p01", "p02"}, set())[0], "conflict")

    def test_bad_splits_files_are_refused(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            for bad in ({"persons": {"p01": {"pool": "both"}}},
                        {"persons": {"p02": {"pool": "test"}}, "train_dev_sessions": {"p02": {"d": "dev"}}},
                        {"persons": {"p01": {"pool": "train_dev"}}, "train_dev_sessions": {"p01": {"d": "test"}}},
                        {"runs": {"d/r": "maybe"}}):
                p = tmp / "s.json"
                p.write_text(json.dumps(bad))
                with self.assertRaises(ValueError, msg=str(bad)):
                    IX.load_splits(p)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_repo_splits_file_is_valid_and_p01_is_never_test(self):
        sp = IX.load_splits(IX.DEFAULT_SPLITS)
        self.assertEqual(sp["persons"]["p01"]["pool"], "train_dev")
        for date in sp["train_dev_sessions"].get("p01", {}):
            self.assertNotEqual(IX.person_split(sp, "p01", date)[0], "test")


class SmallPiecesTest(unittest.TestCase):
    def test_regime_bands(self):
        self.assertEqual([IX.regime(v) for v in (4.0, 14.99, 15.0, 64.9, 65.0, 146.0)],
                         ["near_black", "near_black", "dim", "dim", "bright", "bright"])

    def test_drone_from_uri(self):
        self.assertEqual(IX.drone_from_uri("radio://0/80/2M/E7E7E7E705"), "05")
        self.assertEqual(IX.drone_from_uri("usb://0"), "")

    def test_header_time_handles_date_padding(self):
        t = time.mktime((2026, 10, 1, 9, 5, 7, 0, 0, -1))
        m = IX.LOG_HEADER_RE.match(f"== grid capture, {date_header(t)}  subject p01")
        self.assertIsNotNone(m)
        self.assertAlmostEqual(IX._parse_header_time(m.group(1), m.group(2)), t, delta=1)


if __name__ == "__main__":
    unittest.main()
