#!/usr/bin/env python3
"""Unit tests for record_session.py and session_common.py. No drone, no cflib, no sim.

    ~/Downloads/drone/trainenv/bin/python -m unittest tools/lighthouse/test_record_session.py -v
    ~/Downloads/drone/cfloaderenv/bin/python -m unittest tools/lighthouse/test_record_session.py -v

Covers the brightness gate, the CSV and meta.json the recorder writes, rate / dropped
-sample statistics, the cue schedule and the scripted rehearsal subject, filename
parsing, status-variable selection from a TOC, and one complete --static run against a
scripted follower (the full code path minus cflib). What only hardware can settle - the
real radio's rate, the real Lighthouse variables, the deck's MAC lookup - is not here.
"""
import contextlib
import io
import json
import math
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import record_session as R  # noqa: E402
import session_common as S  # noqa: E402


class BrightnessGate(unittest.TestCase):
    def test_inside_band_records(self):
        for m in (30, 45.5, 60):
            g = S.brightness_gate(m, env={})
            self.assertTrue(g["ok"], m)
            self.assertFalse(g["override"])

    def test_outside_band_refused(self):
        for m in (16, 29.9, 60.1, 146):
            g = S.brightness_gate(m, env={})
            self.assertFalse(g["ok"], m)
            self.assertIn("GRID_ACCEPT_ANY", g["why"])

    def test_override_records_outside_band(self):
        g = S.brightness_gate(90, env={"GRID_ACCEPT_ANY": "1"})
        self.assertTrue(g["ok"])
        self.assertTrue(g["override"])

    def test_black_refused_even_with_override(self):
        g = S.brightness_gate(4.1, env={"GRID_ACCEPT_ANY": "1"})   # the 2026-09-24 all-noise grid
        self.assertFalse(g["ok"])
        self.assertIn("BLACK", g["why"])

    def test_no_frames_refused(self):
        for m in (None, float("nan"), -1):
            self.assertFalse(S.brightness_gate(m, env={})["ok"])

    def test_band_from_env_like_grid_capture(self):
        env = {"GRID_MIN_BRIGHT": "40", "GRID_MAX_BRIGHT": "90"}
        self.assertTrue(S.brightness_gate(85, env=env)["ok"])
        self.assertFalse(S.brightness_gate(35, env=env)["ok"])
        self.assertEqual(S.brightness_gate(85, env=env)["band"], [40, 90])


class RateStats(unittest.TestCase):
    def test_perfect_stream(self):
        t = [1000 + 10 * i for i in range(1001)]
        st = S.rate_stats(t, 10)
        self.assertEqual(st["missing"], 0)
        self.assertAlmostEqual(st["achieved_hz"], 100.0, places=6)
        self.assertEqual(st["delivery"], 1.0)
        self.assertEqual(st["max_gap_ms"], 10)

    def test_dropped_packets_counted(self):
        t = [10 * i for i in range(1000) if not (100 <= i < 150) and i % 97 != 5]
        st = S.rate_stats(t, 10)
        n_drop = 50 + sum(1 for i in range(1000) if i % 97 == 5 and not (100 <= i < 150))
        self.assertEqual(st["missing"], n_drop)
        self.assertEqual(st["max_gap_ms"], 510)
        self.assertLess(st["delivery"], 0.95)

    def test_receive_jitter_ignores_clock_drift(self):
        tc = [10 * i for i in range(3000)]
        tl = [1.79e9 + (x / 1000.0) * (1 + 0.1) + (0.004 if i % 10 == 0 else 0.0) for i, x in enumerate(tc)]
        st = S.rate_stats(tc, 10, tl)     # a 10% clock rate difference (SITL-like) is not jitter
        self.assertLess(st["rx_delay_above_min_ms_p95"], 5.0)

    def test_pick_period(self):
        probe = {10: {"follower": 0.99, "beacon": 0.80}, 20: {"follower": 1.0, "beacon": 0.97}, 50: {"follower": 1, "beacon": 1}}
        self.assertEqual(S.pick_period(probe), 20)
        self.assertIsNone(S.pick_period({10: {"follower": 0.5, "beacon": None}}))


class Schedule(unittest.TestCase):
    def test_protocol_order_and_stillness(self):
        sch = S.cue_schedule(90)
        ph = S.phase_times(sch)
        self.assertEqual([p for _, _, p in sch], ["start_still", "start_step", "start_settle", "free",
                                                  "end_still", "end_step", "end_settle", "done"])
        self.assertGreaterEqual(ph["start_step"] - ph["start_still"], 2.0)
        self.assertGreaterEqual(ph["end_step"] - ph["end_still"], 2.0)   # README: still >= 2 s
        self.assertEqual(ph["done"], 90)
        self.assertEqual([t for t, _, _ in sch], sorted(t for t, _, _ in sch))

    def test_too_short_refused(self):
        with self.assertRaises(ValueError):
            S.cue_schedule(S.MIN_SECONDS - 1)

    def test_scripted_subject_obeys_cues(self):
        sec = 60.0
        ph = S.phase_times(S.cue_schedule(sec))
        self.assertEqual(S.scripted_lateral(-5, sec), 0.0)
        self.assertEqual(S.scripted_lateral(ph["start_step"], sec), 0.0)              # still reacting
        self.assertAlmostEqual(S.scripted_lateral(ph["start_step"] + 1.0, sec), S.STEP_M)
        self.assertAlmostEqual(S.scripted_lateral(ph["end_still"] + 1.0, sec), S.STEP_M)
        self.assertAlmostEqual(S.scripted_lateral(sec + 1, sec), 0.0)
        walk = [S.scripted_lateral(ph["free"] + 0.1 * k, sec) for k in range(int((ph["end_still"] - ph["free"]) * 10))]
        self.assertLess(min(walk), -0.3)   # crosses to the RIGHT of the line: both sides get frames
        self.assertGreater(max(walk), 1.0)


class Names(unittest.TestCase):
    def test_frame_names(self):
        self.assertEqual(S.frame_time("frame_00012_1790907427.301.png"), 1790907427.301)
        self.assertEqual(S.frame_number("frame_00012_1790907427.301.png"), 12)
        n = "d2.5_b-15_vis1_subj-p01_light-room_take1_f00012_t1757530000.123.png"
        self.assertEqual(S.frame_time(n), 1757530000.123)
        self.assertEqual(S.frame_number(n), 12)
        self.assertIsNone(S.frame_time("scores.csv"))

    def test_default_out_keeps_mock_away_from_real_data(self):
        import datetime as dt
        now = dt.datetime(2026, 10, 2, 14, 5, 9)
        self.assertEqual(R.default_out(True, now), Path.home() / "drone_frames/_rehearsal/2026-10-02/lh_session_140509")
        self.assertEqual(R.default_out(False, now), Path.home() / "drone_frames/2026-10-02/lh_session_140509")

    def test_mac_normalised(self):
        self.assertEqual(R.norm_mac("A4:CF:12:9:B:0C"), "a4:cf:12:09:0b:0c")
        self.assertEqual(R.norm_mac("a4-cf-12-09-0b-0c"), "a4:cf:12:09:0b:0c")


class StatusVars(unittest.TestCase):
    TOC = {"lighthouse": {"status": "uint8_t", "bsActive": "uint16_t", "bsReceive": "uint16_t",
                          "bsNewThing": "uint16_t", "posRt": "float"},
           "kalman": {"varPX": "float", "varPY": "float", "varPZ": "float"},
           "pm": {"vbat": "float", "state": "int8_t"}, "radio": {"rssi": "uint8_t"}}

    def test_takes_what_exists_and_new_bitmasks(self):
        v = R.pick_status_vars(self.TOC, uri="radio://0/80/2M/E7E7E7E709")
        self.assertEqual(v[:3], ["lighthouse.status", "lighthouse.bsActive", "lighthouse.bsReceive"])
        self.assertIn("lighthouse.bsNewThing", v)           # an unknown bitmask is not silently skipped
        self.assertIn("radio.rssi", v)
        self.assertNotIn("lighthouse.posRt", v)

    def test_sitl_without_lighthouse(self):
        toc = {"kalman": self.TOC["kalman"], "pm": self.TOC["pm"], "radio": self.TOC["radio"]}
        v = R.pick_status_vars(toc, uri="udp://127.0.0.1:19850")
        self.assertFalse(any(x.startswith("lighthouse") for x in v))
        self.assertNotIn("radio.rssi", v)                   # no radio on a UDP / USB link


class Writers(unittest.TestCase):
    def test_pose_csv_and_status_sample_and_hold(self):
        with tempfile.TemporaryDirectory() as d:
            w = R.PoseWriter(Path(d) / "poses_beacon.csv", ["lighthouse.status", "pm.vbat"])
            pose = dict(x=1.0, y=-0.5, z=1.8, roll=0.1, pitch=-0.2, yaw=30.0)
            w.on_pose(1000, 1.79e9 + 0.003, pose)              # before any status: blank columns
            w.on_status(1005, 1.79e9 + 0.008, {"lighthouse.status": 2, "pm.vbat": 3.91})
            w.on_pose(1010, 1.79e9 + 0.012, dict(pose, x=1.01))
            w.on_status(1105, 1.79e9 + 0.108, {"lighthouse.status": 0})   # Lighthouse lost; vbat holds
            w.on_pose(1110, 1.79e9 + 0.113, dict(pose, x=float("nan")))
            w.close()
            cols = S.read_pose_csv(Path(d) / "poses_beacon.csv")
            self.assertEqual(list(cols), S.pose_csv_header(["lighthouse.status", "pm.vbat"]))
            self.assertEqual(cols["t_cf_ms"], [1000, 1010, 1110])
            self.assertAlmostEqual(cols["t_laptop"][1], 1.79e9 + 0.012, places=5)
            self.assertTrue(math.isnan(cols["lighthouse_status"][0]))
            self.assertEqual(cols["lighthouse_status"][1:], [2, 0])
            self.assertEqual(cols["pm_vbat"][1:], [3.91, 3.91])
            self.assertEqual(cols["status_t_cf_ms"][1:], [1005, 1105])
            self.assertTrue(math.isnan(cols["x"][2]))
            self.assertEqual(w.battery(), dict(start=3.91, end=3.91, min=3.91))

    def test_concurrent_writes_do_not_interleave(self):
        with tempfile.TemporaryDirectory() as d:
            w = R.PoseWriter(Path(d) / "p.csv", ["pm.vbat"])

            def go(k):
                for i in range(500):
                    w.on_pose(k * 100000 + i, 1.0, dict(x=k, y=i, z=0, roll=0, pitch=0, yaw=0))
                    w.on_status(i, 1.0, {"pm.vbat": 4.0})
            th = [threading.Thread(target=go, args=(k,)) for k in range(4)]
            [t.start() for t in th]
            [t.join() for t in th]
            w.close()
            lines = (Path(d) / "p.csv").read_text().splitlines()
            self.assertEqual(len(lines), 1 + 2000)
            self.assertTrue(all(len(l.split(",")) == len(S.pose_csv_header(["pm.vbat"])) for l in lines))

    def test_meta_written_atomically(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "meta.json"
            R.write_json_atomic(p, dict(a=1, t=float("inf")))
            R.write_json_atomic(p, dict(a=2))
            self.assertEqual(json.loads(p.read_text()), dict(a=2))
            self.assertEqual(sorted(os.listdir(d)), ["meta.json"])

    def test_static_summary_circular_yaw(self):
        cols = dict(x=[0.0, 0.002, -0.002], y=[0.5] * 3, z=[0.8] * 3, roll=[0.1] * 3, pitch=[0.0] * 3,
                    yaw=[179.0, -179.0, 180.0])
        sm = R.static_summary(cols)
        self.assertAlmostEqual(abs(sm["yaw"]), 180.0, places=3)   # not 60.0, the arithmetic mean
        self.assertLess(sm["yaw_std"], 1.0)


class StaticRunScripted(unittest.TestCase):
    """The whole --static path (connect, TOC, log blocks, writer, meta, average, the label),
    with a scripted follower standing in for cflib."""

    def test_static_run_writes_session(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "s"
            buf = io.StringIO()
            env = dict(os.environ, CAMERA_CHECK_QUIET="1")
            old = os.environ.copy()
            os.environ.update(env)
            try:
                with contextlib.redirect_stdout(buf):
                    rc = R.main(["--mock", "--mock-follower", "scripted", "--static", "--seconds", "1.5", "--no-probe",
                                 "--mark", "2.0", "0.5", "--height", "1.75", "--mount", "0", "0", "0",
                                 "--subject", "p01", "--out", str(out)])
            finally:
                os.environ.clear()
                os.environ.update(old)
            txt = buf.getvalue()
            self.assertEqual(rc, 0, txt)
            meta = json.loads((out / "meta.json").read_text())
            for k in ("tool_git", "uris", "firmware", "battery_v", "log", "geometry", "subject", "height_m",
                      "mount_xyz_body", "stopped_because", "static_pose", "label_target"):
                self.assertIn(k, meta)
            self.assertEqual(meta["stopped_because"], "completed")
            self.assertEqual(len(meta["geometry"]["sha256"]), 64)
            self.assertTrue(meta["mock"])
            ach = meta["log"]["achieved"]["follower"]
            self.assertGreater(ach["n"], 100)
            self.assertGreater(ach["achieved_hz"], 80)
            cols = S.read_pose_csv(out / "poses_follower.csv")
            self.assertAlmostEqual(sum(cols["z"]) / len(cols["z"]), 0.8)
            self.assertFalse((out / "poses_beacon.csv").exists())
            # the README's worked example: subject 2.0 m ahead, 0.5 m LEFT -> -14.04 deg, x-bin 2
            self.assertIn("bearing   -14.04 deg (LEFT", txt)
            self.assertIn("x-bin     2", txt)

    def test_yawed_step_moves_the_subject_right(self):
        """README: turn the follower 30 deg LEFT -> logged yaw +30 -> +15.96 deg, x-bin 6."""
        with tempfile.TemporaryDirectory() as d:
            buf = io.StringIO()
            os.environ["CAMERA_CHECK_QUIET"] = "1"
            with contextlib.redirect_stdout(buf):
                rc = R.main(["--mock", "--mock-follower", "scripted", "--mock-follower-yaw", "30", "--static",
                             "--seconds", "1", "--no-probe", "--mark", "2.0", "0.5", "--height", "1.75",
                             "--mount", "0", "0", "0", "--out", str(Path(d) / "s")])
            txt = buf.getvalue()
            self.assertEqual(rc, 0, txt)
            self.assertIn("yaw +30.00", txt)
            self.assertIn("bearing   +15.96 deg (RIGHT", txt)
            self.assertIn("x-bin     6", txt)

    def test_refuses_nonempty_out_and_bad_subject(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "x").write_text("real data")
            with contextlib.redirect_stdout(io.StringIO()) as buf:
                rc = R.main(["--mock", "--mock-follower", "scripted", "--static", "--out", d])
            self.assertEqual(rc, 2)
            self.assertIn("not empty", buf.getvalue())
            self.assertEqual(os.listdir(d), ["x"])          # nothing touched
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            R.main(["--mock", "--subject", "Jane Doe"])


if __name__ == "__main__":
    unittest.main()
