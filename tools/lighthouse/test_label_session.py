#!/usr/bin/env python3
"""Tests for label_session.py on synthetic session folders (no drone, no network, no sim).

    ~/Downloads/drone/trainenv/bin/python -m unittest tools/lighthouse/test_label_session.py -v

A session is synthesised exactly as record_session.py writes one - poses_*.csv through
the real PoseWriter, meta.json, frames/ named like cpx_grab's - with two Crazyflie clocks
of KNOWN offset, drift and radio latency, and frames at the deck's ~2 fps that arrive a
KNOWN `LAG` after the instant they show. The network is replaced by its cached outputs
(network_chip.csv): the image x of the true subject position, squashed and noisy like
the chip's, so no ONNX/doryenv is needed. The end-to-end rehearsal against CrazySim and
mock_streamer (real network) is test_session_rehearsal.py.
"""
import contextlib
import csv
import io
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import label_session as L  # noqa: E402
import pose_to_label as P  # noqa: E402
import record_session as R  # noqa: E402
import session_common as S  # noqa: E402

LAG = 0.20              # frame arrives this long after the instant it shows
DIST = 2.5
H = 1.75
T0 = 1.79e9 + 1000.0
CAM = P.CameraSpec(mount_xyz_body=(0.0, 0.0, 0.0))
TOL_S = 0.025


def make_session(folder, seconds=90.0, flip=False, static_subject=False, lh_dropout=None, beacon_gap=None,
                 beacon_jump_at=None, seed=0):
    rng = np.random.default_rng(seed)
    folder = Path(folder)
    (folder / S.FRAMES_DIR).mkdir(parents=True)
    y_of = (lambda t: 0.0) if static_subject else (lambda t: S.scripted_lateral(t - T0, seconds))
    clocks = dict(follower=dict(boot=T0 - 812.5, drift=-30e-6), beacon=dict(boot=T0 - 37.25, drift=80e-6))
    for role in ("follower", "beacon"):
        sv = ["lighthouse.status", "pm.vbat"]
        w = R.PoseWriter(folder / S.POSES_CSV[role], sv)
        c = clocks[role]
        for k, t in enumerate(np.arange(T0 - 10.0, T0 + seconds + 3.0, 0.01)):
            if role == "beacon" and beacon_gap and beacon_gap[0] <= t - T0 < beacon_gap[1]:
                continue
            tcf = int((t - c["boot"]) * 1000 * (1 + c["drift"]))
            rx = t + rng.uniform(0.002, 0.008) + (0.05 if rng.random() < 0.01 else 0.0)
            if k % 10 == 0:
                lost = role == "beacon" and lh_dropout and lh_dropout[0] <= t - T0 < lh_dropout[1]
                w.on_status(tcf, rx, {"lighthouse.status": 0 if lost else 2, "pm.vbat": 3.9})
            if role == "follower":
                pose = dict(x=0.0, y=0.0, z=0.8, roll=0.2, pitch=-0.1, yaw=0.0)
            else:
                y = y_of(t) + (0.5 if beacon_jump_at and abs(t - T0 - beacon_jump_at) < 0.03 else 0.0)
                pose = dict(x=DIST, y=y, z=H, roll=5.0, pitch=3.0, yaw=40.0)
            w.on_pose(tcf, rx, pose)
        w.close()
    rows = []
    for k, ts in enumerate(np.arange(T0 - 8.0, T0 + seconds + 1.0, 0.5)):
        arr = ts + LAG + rng.uniform(0.0, 0.03)
        inst = arr - LAG
        lab = P.pose_to_label(P.Pose(0, 0, 0.8, 0), (DIST, y_of(inst), H), cam=CAM)
        x = 0.85 * lab.x_norm + rng.normal(0, 0.02)          # the chip reads toward the centre, noisily
        x = -x if flip else x
        name = f"frame_{k + 1:05d}_{arr:.3f}.png"
        (folder / S.FRAMES_DIR / name).write_bytes(b"")
        rows.append([name, 0.9, P.x_to_bin(max(-1, min(1, x))), x, 2])
    with open(folder / "network_chip.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(L.NET_COLS)
        w.writerows(rows)
    meta = dict(mode="session", mock=False, subject="p01", height_m=H, beacon_above_head_m=0.0,
                mount_xyz_body=[0, 0, 0], log=dict(pose_period_ms=10), t0_unix=T0)
    (folder / S.META_JSON).write_text(json.dumps(meta))
    return clocks


def read_rows(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def run(folder, *extra):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = L.main([str(folder), *extra])
    return rc, buf.getvalue()


class CfClock(unittest.TestCase):
    def test_offset_and_drift_from_lower_envelope(self):
        rng = np.random.default_rng(3)
        t = np.arange(0, 120, 0.01) + 1.79e9
        boot, drift = 1.79e9 - 500.0, 120e-6
        tcf = ((t - boot) * 1000 * (1 + drift)).astype(np.int64)
        rx = t + 0.002 + rng.exponential(0.004, len(t)) + (rng.random(len(t)) < 0.02) * 0.2
        fit = L.fit_cf_clock(tcf, rx)
        err = L.cf_to_laptop(fit, tcf) - t
        self.assertLess(np.abs(np.median(err) - 0.002), 0.002, "maps to the sample instant + the minimum latency")
        self.assertLess(np.abs(err).max(), 0.006)
        self.assertAlmostEqual(fit["drift_ppm"], -drift * 1e6, delta=15)


class LabelSession(unittest.TestCase):
    def test_recovers_injected_lag_and_labels(self):
        with tempfile.TemporaryDirectory() as d:
            clocks = make_session(d)
            rc, out = run(d)
            self.assertEqual(rc, 0, out)
            rep = json.loads((Path(d) / "label_summary.json").read_text())
            al = rep["alignment"]
            self.assertEqual(len(al["offset_at_events_s"]), 2)
            # frame arrival -> the instant shown is -LAG (plus the ~15 ms mean arrival jitter); the
            # pose clock is the beacon's, mapped to the laptop with its ~2 ms minimum latency
            truth = -(LAG + 0.015) + 0.002
            self.assertLess(abs(al["offset_mid_s"] - truth), TOL_S, al["summary"])
            for r, c in clocks.items():
                self.assertAlmostEqual(rep["cf_clock"][r]["drift_ppm"], -c["drift"] * 1e6, delta=20)
            rows = read_rows(Path(d) / "labels.csv")
            self.assertEqual(len(rows), len(S.list_frames(Path(d) / S.FRAMES_DIR)))
            used = [r for r in rows if not r["drop_reason"]]
            self.assertGreater(len(used), 0.95 * len(rows))
            agree = np.mean([abs(int(r["net_x_bin"]) - int(r["x_bin"])) <= 1 for r in used])
            self.assertGreater(agree, 0.95)
            self.assertTrue(rep["mirror_check_passed"])
            md = (Path(d) / "report.md").read_text()
            self.assertIn("OPEN team decision", md)
            self.assertIn("NOT measured", md)                        # the FOV caveat
            self.assertIn("PASS", md)

    def test_label_target_flag_never_moves_the_xbin(self):
        with tempfile.TemporaryDirectory() as d:
            make_session(d)
            run(d)
            a = read_rows(Path(d) / "labels.csv")
            run(d, "--target-frac", "0.6")
            b = read_rows(Path(d) / "labels.csv")
            self.assertEqual([r["x_bin"] for r in a], [r["x_bin"] for r in b])
            self.assertIn("feet + 0.6 x height", (Path(d) / "report.md").read_text())

    def test_mirrored_network_refused(self):
        with tempfile.TemporaryDirectory() as d:
            make_session(d, flip=True)
            rc, out = run(d)
            # a mirrored image anti-correlates, so either the clocks refuse or the side check does
            self.assertIn(rc, (1, 3), out)
            self.assertNotEqual(rc, 0)

    def test_no_sync_motion_refused_then_manual_offset(self):
        with tempfile.TemporaryDirectory() as d:
            make_session(d, static_subject=True)
            rc, out = run(d)
            self.assertEqual(rc, 3, out)
            self.assertFalse((Path(d) / "labels.csv").exists())
            self.assertIn("FAILED", (Path(d) / "report.md").read_text())
            rc, out = run(d, "--offset-s", "-0.2")
            self.assertTrue((Path(d) / "labels.csv").exists())
            self.assertIn("MANUAL offset", (Path(d) / "report.md").read_text())

    def test_drop_reasons(self):
        with tempfile.TemporaryDirectory() as d:
            make_session(d, lh_dropout=(40.0, 45.0), beacon_gap=(60.0, 61.5), beacon_jump_at=30.0)
            rc, out = run(d)
            rows = read_rows(Path(d) / "labels.csv")
            why = {}
            for r in rows:
                rel = float(r["t_pose"]) - T0
                why.setdefault(r["drop_reason"], []).append(rel)
            self.assertIn("beacon_lighthouse_not_working", why, out)
            self.assertTrue(all(39.8 <= t <= 45.3 for t in why["beacon_lighthouse_not_working"]))
            self.assertGreaterEqual(len(why["beacon_lighthouse_not_working"]), 8)
            self.assertIn("no_pose", why)                              # the 1.5 s radio gap is not bridged
            self.assertTrue(any(59.9 <= t <= 61.6 for t in why["no_pose"]))
            self.assertIn("beacon_jump", why)
            self.assertTrue(all(abs(t - 30.0) < 0.4 for t in why["beacon_jump"]))
            md = (Path(d) / "report.md").read_text()
            self.assertIn("beacon_lighthouse_not_working", md)

    def test_bad_inputs(self):
        with tempfile.TemporaryDirectory() as d:
            rc, out = run(d)
            self.assertEqual(rc, 2)
            self.assertIn("no meta.json", out)


if __name__ == "__main__":
    unittest.main()
