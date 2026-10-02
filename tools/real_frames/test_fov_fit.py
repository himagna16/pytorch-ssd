#!/usr/bin/env python3
"""Tests for fov_fit.py on synthetic sessions whose optics are KNOWN.

Each test renders a dorm-like background (bright panels, a dark door, a floor, clutter),
then a dark bottle (7.5 cm across, on an upturned round bin) standing on the taped marks,
through a pinhole camera with a chosen focal length and aim, adds sensor noise and a
per-clip exposure change, writes real PNGs the way cpx_grab.py names them, and runs the
same code fov_capture.sh runs. No hardware, no network, about 10 s.

Tolerances (stated, and why):
  clean placement     f within 0.5 %, aim within 0.1 deg, every centre within 0.25 px.
                      Measured over 20 seeds: f +0.10 % (sd 0.01), aim sd 0.003 deg.
                      The +0.1 % is the 2nd-order perspective bias of the 7.5 cm bottle.
  1 cm placement sd   f within 3.5 %, aim within 1.0 deg. Measured over 20 seeds:
  per mark            f sd 0.8-1.1 % (max 3.2 %), aim sd 0.26 deg; now and then the noise
                      tips the model choice to "linear" (+0.9 deg). This is the real
                      limit: put the bottle on its mark to ~5 mm (then f sd ~0.4 %).

Run:  ~/Downloads/drone/trainenv/bin/python tools/real_frames/test_fov_fit.py
"""
import contextlib
import io
import json
import math
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import fov_fit as F  # noqa: E402


def quiet_fit(d, **kw):
    with contextlib.redirect_stdout(io.StringIO()):
        return F.run_fit(d, **kw)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="test_fov_fit_"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def session(self, name="s", **kw):
        d = self.tmp / name
        truth = F.synth_session(d, **kw)
        return d, truth


class Conventions(Base):
    def test_plus_is_left_and_bearing_negative_left(self):
        # + offset = drone's LEFT (body/room +y); bearing NEGATIVE = left (cpx_grab / scorer)
        self.assertAlmostEqual(F.bearing_deg(0.5, 1.0), -26.565, places=3)
        self.assertAlmostEqual(F.bearing_deg(-0.25, 1.0), 14.036, places=3)
        self.assertEqual(F.bearing_deg(0.0, 1.0), 0.0)
        self.assertEqual(str(F.bearing_deg(0.0, 1.0)), "0.0")          # never "-0.0"
        self.assertEqual(F.mark_dir(0.25), "y+0.25")
        self.assertEqual(F.mark_dir(-0.5), "y-0.50")
        self.assertEqual(F.mark_dir(0.0), "y+0.00")
        self.assertEqual(F.spoken(0.5), "mark plus 0.5, left")
        self.assertEqual(F.spoken(-0.7), "mark minus 0.7, right")
        self.assertEqual(F.spoken(0.0), "the centre mark")
        self.assertEqual(F.inches(1.0), "3 ft 3 3/8 in")       # 1 m = 3 tiles + 3 3/8 in
        self.assertEqual(F.inches(0.25), "9 7/8 in")

    def test_left_mark_lands_left_in_the_image(self):
        d, truth = self.session(f=84.0, heading_deg=0.0, seed=3)
        code, res = quiet_fit(d)
        self.assertEqual(code, 0)
        by = {p["dir"]: p for p in res["positions"]}
        c0 = (162 - 1) / 2.0
        self.assertLess(by["y+0.50"]["x"], c0)        # drone's LEFT -> image left
        self.assertGreater(by["y-0.50"]["x"], c0)
        self.assertFalse(res["camera"]["mirrored"])
        self.assertGreater(res["camera"]["focal_px_per_rad_stream"], 0)

    def test_parse_offsets(self):
        self.assertEqual(F.parse_offsets("0 0.25 -0.25 0.5"), [0.0, 0.25, -0.25, 0.5])
        self.assertEqual(F.parse_offsets("0,0.25,-0.25,0.5"), [0.0, 0.25, -0.25, 0.5])
        with self.assertRaises(ValueError):
            F.parse_offsets("0 0.25 left 0.5")
        with self.assertRaises(ValueError):
            F.parse_offsets("0 0.25 -0.25")                 # < 4 marks cannot be fitted
        with self.assertRaises(ValueError):
            F.parse_offsets("0 0.25 0.25 -0.5")             # duplicate


class Recovery(Base):
    def check(self, res, truth, tol_f_pct, tol_h_deg, min_usable=6):
        cam = res["camera"]
        ef = 100.0 * (cam["focal_px_per_rad_stream"] - truth["f"]) / truth["f"]
        eh = cam["camera_heading_deg"] - truth["heading_deg"]
        self.assertLessEqual(abs(ef), tol_f_pct, f"focal off by {ef:+.2f} %")
        self.assertLessEqual(abs(eh), tol_h_deg, f"aim off by {eh:+.2f} deg")
        self.assertGreaterEqual(res["n_usable"], min_usable)

    def test_known_f_and_aim_turned_left(self):
        d, truth = self.session(f=84.0, heading_deg=-6.0, seed=21)
        code, res = quiet_fit(d)
        self.assertEqual(code, 0)
        self.check(res, truth, 0.5, 0.1)
        self.assertEqual(res["fit"]["headline"], "yaw")
        for p in res["positions"]:
            if p["usable"]:
                self.assertLess(abs(p["x"] - truth["columns"][p["dir"]]), 0.25, p["dir"])
        # the tape line lands RIGHT of centre when the camera is turned LEFT
        self.assertGreater(res["camera"]["tape_line_offset_px"], 5.0)
        self.assertEqual(res["camera"]["tape_line_network_xbin"], 5)

    def test_known_f_and_aim_turned_right_narrower_lens(self):
        d, truth = self.session(f=100.0, heading_deg=4.0, seed=22)
        code, res = quiet_fit(d)
        self.assertEqual(code, 0)
        self.check(res, truth, 0.5, 0.1)
        sq = 2 * math.degrees(math.atan(61.0 / 100.0))
        self.assertAlmostEqual(res["camera"]["hfov_centre_square_deg"], sq, delta=0.3)

    def test_off_centre_lens_picks_linear_and_keeps_the_tape_column(self):
        # truth: principal point 8 px right of centre, camera NOT turned
        d, truth = self.session(f=84.0, heading_deg=0.0, pp_px=8.0, seed=23)
        code, res = quiet_fit(d)
        self.assertEqual(code, 0)
        self.assertEqual(res["fit"]["headline"], "linear")
        self.assertLess(abs(res["camera"]["focal_px_per_rad_stream"] - 84.0) / 84.0, 0.005)
        self.assertAlmostEqual(res["camera"]["tape_line_column"], 80.5 + 8.0, delta=0.2)

    def test_placement_noise_within_stated_tolerance(self):
        for seed in (31, 32, 33):
            d, truth = self.session(name=f"p{seed}", f=90.0, heading_deg=3.0, placement_sd=0.01,
                                    gain_jitter=0.04, seed=seed)
            code, res = quiet_fit(d)
            self.assertEqual(code, 0)
            self.check(res, truth, 3.5, 1.0)

    def test_exposure_change_between_clips_is_gain_matched(self):
        d, truth = self.session(f=84.0, heading_deg=-2.0, gain_jitter=0.12, seed=24)
        code, res = quiet_fit(d)
        self.assertEqual(code, 0)
        self.check(res, truth, 0.5, 0.1)
        gains = [p["gain"] for p in res["positions"] if p.get("gain")]
        self.assertGreater(max(gains) - min(gains), 0.05)    # the jitter really was there

    def test_full_size_324_frames(self):
        d, truth = self.session(W=324, H=244, f=170.0, heading_deg=-2.0, seed=25)
        code, res = quiet_fit(d)
        self.assertEqual(code, 0)
        self.check(res, truth, 0.5, 0.1)
        # at full size the stream IS the 324 frame: same focal at "full324"
        self.assertAlmostEqual(res["camera"]["focal_px_per_rad_full324"],
                               res["camera"]["focal_px_per_rad_stream"], delta=0.05)

    def test_flight_crop_assumption_2x_binned(self):
        d, truth = self.session(f=84.0, heading_deg=0.0, seed=26)
        code, res = quiet_fit(d)
        cam = res["camera"]
        # 162 wide = 324 / 2: full-frame focal is twice the stream's, and the flight crop
        # (244 of 324) is the stream's 122-px centre square
        self.assertAlmostEqual(cam["focal_px_per_rad_full324"], 2 * cam["focal_px_per_rad_stream"], delta=0.02)
        self.assertAlmostEqual(cam["hfov_flight_crop_deg"], cam["hfov_centre_square_deg"], delta=0.01)
        self.assertIn("NOT verified", cam["flight_crop_assumption"])


class Flags(Base):
    def test_edge_touching_marks_are_flagged_and_left_out(self):
        # a long lens: +-0.7 m at 1 m (35 deg) is outside the picture
        d, truth = self.session(f=125.0, heading_deg=0.0, seed=41)
        code, res = quiet_fit(d)
        self.assertEqual(code, 0)
        by = {p["dir"]: p for p in res["positions"]}
        for k in ("y+0.70", "y-0.70"):
            self.assertFalse(by[k]["usable"], k)
        self.assertTrue(any("EDGE" in fl or "NOT FOUND" in fl for fl in by["y-0.70"]["flags"]))
        self.assertLess(abs(res["camera"]["focal_px_per_rad_stream"] - 125.0) / 125.0, 0.005)

    def test_no_object_exits_3_with_plain_message(self):
        d, _ = self.session(no_object=True, seed=42)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code, res = F.run_fit(d)
        self.assertEqual(code, 3)
        self.assertIn("NOT ENOUGH MARKS", buf.getvalue())
        self.assertEqual(res["n_usable"], 0)
        self.assertTrue(json.loads((d / F.RESULT_FILE).read_text())["status"] == "too_few_usable")

    def test_mirrored_image_is_reported(self):
        d, truth = self.session(f=84.0, heading_deg=-3.0, flip=True, seed=43)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code, res = F.run_fit(d)
        self.assertEqual(code, 0)
        self.assertTrue(res["camera"]["mirrored"])
        self.assertIn("MIRRORED", buf.getvalue())
        self.assertLess(abs(res["camera"]["focal_px_per_rad_stream"] - 84.0) / 84.0, 0.005)

    def test_smaller_distractor_does_not_steal_the_object(self):
        d, truth = self.session(f=84.0, heading_deg=0.0, distractor=True, seed=44)
        code, res = quiet_fit(d)
        self.assertEqual(code, 0)
        p = {q["dir"]: q for q in res["positions"]}["y+0.25"]
        self.assertTrue(p["usable"])
        self.assertLess(abs(p["x"] - truth["columns"]["y+0.25"]), 0.25)
        self.assertLess(p["mass_frac"], 0.99)             # it did see the other change

    def test_person_sized_change_is_not_used(self):
        rng = np.random.default_rng(0)
        bg = F.synth_background(162, 122, 0)
        ref = bg + rng.normal(0, 3, bg.shape)
        pos = bg.copy()
        pos[10:115, 60:110] = 15.0                          # someone standing in view
        pos += rng.normal(0, 3, bg.shape)
        r = F.detect(pos.astype(np.float32), ref.astype(np.float32))
        self.assertFalse(r["usable"])
        self.assertTrue(any("TOO BIG" in fl for fl in r["flags"]))

    def test_missing_mark_folder_is_reported_not_fatal(self):
        d, truth = self.session(f=84.0, heading_deg=0.0, seed=45)
        shutil.rmtree(d / "y-0.25")
        code, res = quiet_fit(d)
        self.assertEqual(code, 0)
        p = {q["dir"]: q for q in res["positions"]}["y-0.25"]
        self.assertFalse(p["usable"])
        self.assertIn("NOT CAPTURED", p["flags"][0])

    def test_wrong_mark_is_dropped_as_outlier(self):
        d, truth = self.session(f=84.0, heading_deg=0.0, seed=46)
        # pretend the operator put the bottle on +0.25 when the plan said +0.50:
        # copy the +0.25 clip over the +0.50 folder
        shutil.rmtree(d / "y+0.50")
        shutil.copytree(d / "y+0.25", d / "y+0.50")
        code, res = quiet_fit(d)
        self.assertEqual(code, 0)
        self.assertEqual(res["dropped"], "y+0.50")
        self.assertLess(abs(res["camera"]["focal_px_per_rad_stream"] - 84.0) / 84.0, 0.005)

    def test_highest_take_wins(self):
        d, truth = self.session(f=84.0, heading_deg=0.0, seed=47)
        # take 1 of y+0.25 had no bottle (operator not ready); take 2 is the good one
        good = sorted((d / "y+0.25").glob("*.png"))
        empties = sorted((d / "empty_start").glob("*.png"))
        for k, (g, e) in enumerate(zip(good, empties)):
            shutil.copy(e, d / "y+0.25" / g.name.replace("_take1_", "_take0_"))
            g.rename(d / "y+0.25" / g.name.replace("_take1_", "_take2_"))
        files, take = F.clip_files(d / "y+0.25")
        self.assertEqual(take, 2)
        code, res = quiet_fit(d)
        p = {q["dir"]: q for q in res["positions"]}["y+0.25"]
        self.assertTrue(p["usable"])
        self.assertEqual(p["take"], 2)

    def test_object_in_the_first_empty_clip_falls_back_to_the_second(self):
        # what the rehearsal produced when a stray connection shifted the mock's clips:
        # empty_start holds the bottle on the centre mark
        d, truth = self.session(f=84.0, heading_deg=-6.0, seed=49)
        shutil.rmtree(d / "empty_start")
        shutil.copytree(d / "y+0.00", d / "empty_start")
        for p in (d / "empty_start").glob("*.png"):
            p.rename(p.with_name(p.name.replace("subj-bottle", "subj-empty")))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code, res = F.run_fit(d)
        self.assertIn("two EMPTY clips differ", buf.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(res["fit_quality"], "good")
        self.assertLess(abs(res["camera"]["focal_px_per_rad_stream"] - 84.0) / 84.0, 0.005)
        self.assertTrue(all(p["reference"] == "empty_end" for p in res["positions"] if p.get("usable")))

    def test_marks_in_the_wrong_order_is_a_poor_fit_exit_5(self):
        # the bottle went to the marks in a different order than FOV_OFFSETS says
        d, truth = self.session(f=84.0, heading_deg=0.0, seed=50)
        s = json.loads((d / F.SESSION_FILE).read_text())
        wrong = [0.0, 0.5, -0.5, 0.25, -0.25, 0.7, -0.7]
        for p, y in zip(s["positions"], wrong):
            p["offset_m"], p["bearing_deg"] = y, F.bearing_deg(y, 1.0)
        (d / F.SESSION_FILE).write_text(json.dumps(s))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code, res = F.run_fit(d)
        self.assertEqual(code, 5)
        self.assertEqual(res["fit_quality"], "POOR")
        self.assertIn("POOR FIT", buf.getvalue())
        self.assertNotIn("THE IMAGE IS MIRRORED", buf.getvalue())

    def test_no_empty_reference_is_exit_2(self):
        d, _ = self.session(seed=48)
        shutil.rmtree(d / "empty_start")
        shutil.rmtree(d / "empty_end")
        code, _ = quiet_fit(d)
        self.assertEqual(code, 2)


class Cli(Base):
    PY = sys.executable

    def run_cli(self, *args):
        return subprocess.run([self.PY, str(HERE / "fov_fit.py"), *map(str, args)],
                              capture_output=True, text=True)

    def test_init_writes_session_and_plan(self):
        d = self.tmp / "sess"
        p = self.run_cli(d, "--init", "--dist", "1.0", "--offsets", "0 0.25 -0.25 0.5 -0.5",
                         "--lens-height", "0.8", "--object", "bottle", "--object-height", "0.27")
        self.assertEqual(p.returncode, 0, p.stderr)
        lines = p.stdout.strip().splitlines()
        self.assertEqual(len(lines), 5)
        first = lines[1].split("\t")
        self.assertEqual(first[0], "y+0.25")
        self.assertEqual(first[2], "mark plus 0.25, left")
        self.assertIn("drone's LEFT", first[3])
        s = json.loads((d / F.SESSION_FILE).read_text())
        self.assertEqual(s["distance_m"], 1.0)
        self.assertEqual(s["object_height_m"], 0.27)
        self.assertIsNone(s["object_width_m"])
        self.assertAlmostEqual(s["positions"][3]["bearing_deg"], -26.565, places=3)

    def test_init_rejects_bad_offsets(self):
        p = self.run_cli(self.tmp / "bad", "--init", "--offsets", "0 0.25 x 0.5")
        self.assertEqual(p.returncode, 2)
        self.assertIn("not a number", p.stderr)

    def test_check_exit_codes(self):
        d, _ = self.session(f=84.0, heading_deg=0.0, seed=51)
        ok = self.run_cli(d, "--check", "y+0.25")
        self.assertEqual(ok.returncode, 0, ok.stdout)
        self.assertIn("FOUND at column", ok.stdout)
        d2, _ = self.session(name="none", no_object=True, seed=52)
        bad = self.run_cli(d2, "--check", "y+0.25")
        self.assertEqual(bad.returncode, 1)
        self.assertIn("NOT USABLE", bad.stdout)

    def test_selftest_passes(self):
        p = self.run_cli("--selftest")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("selftest PASSED", p.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
