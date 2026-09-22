#!/usr/bin/env python3
"""Tests for align_clocks.py. Run:

    ~/Downloads/drone/trainenv/bin/python -m unittest tools/lighthouse/test_align_clocks.py -v

What is proven here, and what is not
------------------------------------
* A synthetic 5-minute recording (frames at 10 fps with timestamp jitter and 5%
  dropped frames, network-like x noise; poses at 100 Hz with a 0.4 s dropout,
  on a clock with a KNOWN offset and drift) is re-aligned to within
  OFFSET_TOL_S everywhere in the run, over six random seeds.
* The same routine, fed frames that were really served by
  tools/real_frames/mock_streamer.py and really received and timestamped by
  cpx_grab.py over a local TCP socket, recovers an injected offset to within
  MOCK_TOL_S.
* The bearing error that an UNcorrected offset causes on a moving subject is
  computed through pose_to_label and matches atan(v * dt / d).

NOT proven: anything about the real AI-deck WiFi link's latency or jitter, or
the Crazyradio's. Those set the real tolerance and can only be measured in
the lab (README, "What only hardware can settle").
"""
import math
import os
import re
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
import align_clocks as A   # noqa: E402
import pose_to_label as P  # noqa: E402

OFFSET_TOL_S = 0.025       # a quarter of the 10 fps frame period
DRIFT_TOL_PPM = 150.0      # what two sync events 5 minutes apart can resolve at this frame rate
MOCK_TOL_S = 0.035         # half a frame period at the mock's 15 fps

RANGE_M = 2.5
FOLLOWER = P.Pose(0.0, 0.0, 0.8, 0.0)


def lateral(T, dur):
    """Subject's sideways position (m, + = drone's LEFT) at RANGE_M, following the
    sync protocol: still, sidestep, walk about, still, sidestep, still."""
    T = np.asarray(T, float)

    def ramp(t0, d, y0, y1):
        s = np.clip((T - t0) / d, 0, 1)
        return y0 + (y1 - y0) * (1 - np.cos(np.pi * s)) / 2

    walk_end = dur - 6.0
    y = np.where(T < 3.0, 0.0, ramp(3.0, 0.35, 0.0, 0.5))
    walking = (T >= 5.5) & (T < walk_end)
    y = np.where(walking, 0.5 + 0.8 * np.sin(2 * np.pi * (T - 5.5) / 7.0) * np.minimum(1, (T - 5.5) / 2), y)
    # the walk must end back at 0.5 m: fade it out over its last 2 s
    fade = np.clip((walk_end - T) / 2.0, 0, 1)
    y = np.where(walking, 0.5 + (y - 0.5) * fade, y)
    y = np.where(T >= walk_end, np.where(T < dur - 2.5, 0.5, ramp(dur - 2.5, 0.35, 0.5, 0.0)), y)
    return y


def image_x(y):
    return np.array([P.pose_to_label(FOLLOWER, (RANGE_M, float(v), 1.75)).x_norm for v in y])


class ErrorModel(unittest.TestCase):
    def test_formula_numbers(self):
        self.assertAlmostEqual(A.bearing_error_deg(0.1, 1.0, 2.0), math.degrees(math.atan(0.05)), places=12)
        self.assertAlmostEqual(A.bearing_error_deg(0.1, 1.0, 2.0), 2.862, places=3)
        self.assertAlmostEqual(A.max_offset_for(2.862405226, 1.0, 2.0), 0.1, places=6)
        # one x-bin is 2/9 of the crop; at 1 m/s and 2 m, 0.311 s of offset is one whole bin
        self.assertAlmostEqual(A.xbin_error(0.311, 1.0, 2.0), 1.0, delta=0.01)

    def test_uncorrected_offset_through_pose_to_label(self):
        """A subject crossing at v m/s: the label computed from the pose `dt`
        seconds late differs by atan(v dt / d) - and by nothing when v = 0."""
        rows = []
        for v in (0.0, 0.5, 1.0, 1.5):
            for dt in (0.05, 0.1, 0.25, 0.5):
                y_true, y_late = 0.0, -v * dt           # subject walking to the drone's right
                b_true = P.pose_to_label(FOLLOWER, (2.0, y_true, 1.75)).bearing_deg
                b_late = P.pose_to_label(FOLLOWER, (2.0, y_late, 1.75)).bearing_deg
                err = abs(b_late - b_true)
                # pose_to_label measures from the lens 3 cm ahead of the body origin
                want = math.degrees(math.atan2(v * dt, 2.0 - 0.03))
                self.assertAlmostEqual(err, want, places=9)
                self.assertAlmostEqual(err, A.bearing_error_deg(dt, v, 2.0), delta=0.02 * max(err, 1e-9) + 1e-12)
                rows.append((v, dt, err))
        self.assertEqual([e for v, _, e in rows if v == 0.0], [0.0] * 4,
                         "a still subject must show NO error: this is why static marks cannot find a clock offset")


class Onsets(unittest.TestCase):
    def test_clean_step(self):
        t = np.arange(0, 6, 0.01)
        v = np.where(t < 2.0, 0.0, 1.0)
        on = A.find_onsets(t, v)
        self.assertEqual(len(on), 1)
        self.assertAlmostEqual(on[0], 2.0, delta=0.011)

    def test_protocol_gives_first_and_last(self):
        t = np.arange(0, 60, 0.01)
        on = A.find_onsets(t, lateral(t, 60))
        # onsets are only a coarse guess (the threshold is crossed partway up the
        # step); event_offset's correlation does the precise alignment
        self.assertAlmostEqual(on[0], 3.0, delta=0.2)
        self.assertAlmostEqual(on[-1], 57.5, delta=0.2)


def synthetic_run(seed, dur=300.0, offset=3.2168, drift=2000e-6, latency=0.060):
    """Returns frame (t, x), pose (t, x), and truth(t_frame) -> pose time of the same instant."""
    rng = np.random.default_rng(seed)
    T_f = np.arange(0, dur, 0.1) + rng.uniform(-0.01, 0.01, int(round(dur * 10)))
    T_f = T_f[rng.random(len(T_f)) > 0.05]                           # 5% of frames dropped
    t_f = 1789000000.0 + T_f + latency + rng.uniform(0, 0.02, len(T_f))   # laptop unix time on arrival
    x_f = image_x(lateral(T_f, dur)) + rng.normal(0, 0.02, len(T_f))   # network x noise
    T_p = np.arange(0, dur, 0.01)
    T_p = T_p[(T_p < 100.0) | (T_p > 100.4)]                         # a Lighthouse dropout
    t_p = offset + T_p * (1 + drift) + rng.normal(0, 0.0005, len(T_p))   # "ms since boot" clock
    x_p = image_x(lateral(T_p, dur) + rng.normal(0, 0.003, len(T_p)))
    truth = lambda tf: offset + (np.asarray(tf) - 1789000000.0 - latency - 0.01) * (1 + drift)
    return (t_f, x_f), (t_p, x_p), truth


class SyntheticRecovery(unittest.TestCase):
    def _check(self, drift, seeds):
        worst, drifts = 0.0, []
        for s in seeds:
            (tf, xf), (tp, xp), truth = synthetic_run(s, drift=drift)
            fit = A.align(tf, xf, tp, xp)
            self.assertEqual(len(fit.events), 2)
            self.assertTrue(fit.drift_measured)
            err = np.abs(A.to_pose_time(fit, tf) - truth(tf))
            worst = max(worst, float(err.max()))
            drifts.append(fit.drift_ppm)
            self.assertLess(err.max(), OFFSET_TOL_S, f"seed {s}: {fit.summary()}")
            self.assertLess(abs(fit.drift_ppm - drift * 1e6), DRIFT_TOL_PPM, f"seed {s}")
        print(f"\n  synthetic, injected drift {drift * 1e6:.0f} ppm: worst mapping error {worst * 1000:.1f} ms "
              f"over {len(list(seeds))} seeds; recovered drift {', '.join(f'{d:.0f}' for d in drifts)} ppm",
              file=sys.stderr)
        return worst, drifts

    def test_large_injected_drift(self):
        worst, drifts = self._check(2000e-6, range(6))
        self.assertLess(worst, OFFSET_TOL_S)

    def test_realistic_quartz_drift(self):
        self._check(50e-6, range(3))

    def test_uncorrected_offset_would_have_been_large(self):
        (tf, xf), (tp, xp), truth = synthetic_run(0)
        # joining naively on "seconds since each log started" is off by the start
        # difference, here ~ -0.07 s, plus 2000 ppm of drift by the end:
        naive_err = np.abs((tp[0] + (tf - tf[0])) - truth(tf))
        self.assertGreater(naive_err.max(), 0.5)


class Refusals(unittest.TestCase):
    def test_no_still_period(self):
        t = np.arange(0, 30, 0.1)
        v = np.sin(t)
        with self.assertRaises(ValueError):
            A.align(t, v, t + 1.0, v)

    def test_streams_that_disagree(self):
        (tf, xf), (tp, xp), _ = synthetic_run(1, dur=60)
        rng = np.random.default_rng(9)
        xp_bad = xp.copy()
        xp_bad[tp > tp[0] + 2.0] = rng.normal(0, 0.3, (tp > tp[0] + 2.0).sum())   # pose log is noise
        with self.assertRaises(ValueError):
            A.align(tf, xf, tp, xp_bad)

    def test_dropout_is_not_bridged(self):
        fit = A.ClockFit(1.0, 0.0, [])
        pt = np.array([0.0, 0.01, 0.02, 0.5, 0.51])
        (v,) = A.sample_poses_at_frames(fit, [0.015, 0.3, 0.505], pt, [[0, 1, 2, 50, 51]])
        self.assertAlmostEqual(v[0], 1.5)
        self.assertTrue(math.isnan(v[1]))
        self.assertAlmostEqual(v[2], 50.5)


MOCK_PY = REPO / "tools" / "real_frames" / "mock_streamer.py"
GRAB_PY = REPO / "tools" / "crazysim_macos" / "cpx_grab.py"


def _bar_frame(k, x, w=324, h=244):
    """A 324x244 frame: a bright vertical bar where the subject is, and the frame
    index written into the first two pixels so dropped frames cannot desync us."""
    img = np.full((h, w), 60, np.uint8)
    col = int(round(w / 2 + x * (h / 2)))            # the model's crop is the central 244 columns
    img[40:220, max(0, col - 6):min(w, col + 6)] = 220
    img[0, 0], img[0, 1] = k // 256, k % 256
    return img


@unittest.skipUnless(MOCK_PY.exists() and GRAB_PY.exists(), "mock streamer / cpx_grab not present")
class MockStreamerRecovery(unittest.TestCase):
    """Frames served by the real mock_streamer.py, received and timestamped by the real
    cpx_grab.py (its `_t<unix time>` filename stamp is exactly what the lab will have)."""

    FPS = 15.0
    DUR = 13.0
    OFFSET = 37.25           # pose clock reads 37.25 s at the moment frame 0 was sent ("ms since boot")
    DRIFT = 0.0              # 13 s cannot resolve quartz drift; the synthetic test covers drift

    @classmethod
    def setUpClass(cls):
        from PIL import Image
        cls.tmp = tempfile.TemporaryDirectory()
        src, out = Path(cls.tmp.name) / "src", Path(cls.tmp.name) / "grab"
        src.mkdir()
        n = int(cls.DUR * cls.FPS)
        T = np.arange(n) / cls.FPS
        xs = image_x(lateral(T, cls.DUR))
        for k in range(n):
            Image.fromarray(_bar_frame(k, xs[k])).save(src / f"f{k:05d}.png")
        log = open(Path(cls.tmp.name) / "mock.log", "w+")
        proc = subprocess.Popen([sys.executable, str(MOCK_PY), "--port", "0", "--frames", str(src),
                                 "--fps", str(cls.FPS), "--once"], stdout=log, stderr=subprocess.STDOUT)
        try:
            port, deadline = None, time.time() + 60
            while port is None and time.time() < deadline:
                m = re.search(r"streaming on tcp://[^:]+:(\d+)", Path(log.name).read_text())
                if m:
                    port = int(m.group(1))
                elif proc.poll() is not None:
                    raise RuntimeError(Path(log.name).read_text())
                else:
                    time.sleep(0.05)
            r = subprocess.run([sys.executable, str(GRAB_PY), "--host", "127.0.0.1", "--port", str(port),
                                "--out", str(out), "--n", str(n), "--every", "1"],
                               capture_output=True, text=True, timeout=120)
            if r.returncode != 0:
                raise RuntimeError(r.stdout + r.stderr)
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
            log.close()
        cls.k, cls.t, cls.x = [], [], []
        for p in sorted(out.rglob("*.png")):
            m = re.search(r"_(\d{9,}\.\d+)\.png$", p.name) or re.search(r"_t(\d+\.\d+)\.png$", p.name)
            g = np.asarray(Image.open(p).convert("L"), np.int32)
            k = int(g[0, 0]) * 256 + int(g[0, 1])
            cols = np.nonzero(g[120] > 140)[0]
            cls.k.append(k)
            cls.t.append(float(m.group(1)))
            cls.x.append(((cols.mean() - g.shape[1] / 2) / (g.shape[0] / 2)) if len(cols) else np.nan)
        cls.k, cls.t, cls.x = np.array(cls.k), np.array(cls.t), np.array(cls.x)
        # When was frame k SENT? The mock sends on a fixed schedule t_send0 + k/fps; the
        # least-delayed arrivals pin t_send0 (5th percentile, robust to one stalled write).
        cls.t_send0 = float(np.percentile(cls.t - cls.k / cls.FPS, 5))
        # The pose log: the same subject, sampled at 100 Hz on its own clock.
        T_p = np.arange(0, cls.DUR, 0.01)
        cls.pose_t = cls.OFFSET + T_p * (1 + cls.DRIFT)
        cls.pose_x = image_x(lateral(T_p, cls.DUR))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_frames_really_came_through_the_stream(self):
        self.assertGreater(len(self.k), 0.9 * self.DUR * self.FPS)
        lag = self.t - self.k / self.FPS - self.t_send0
        # arrival jitter of the real socket path, reported rather than assumed
        print(f"\n  mock stream: {len(self.k)} of {int(self.DUR * self.FPS)} frames received; arrival lag "
              f"after the send schedule median {np.median(lag) * 1000:.1f} ms, p95 {np.percentile(lag, 95) * 1000:.1f} ms, "
              f"max {lag.max() * 1000:.1f} ms", file=sys.stderr)
        self.assertLess(np.percentile(lag, 95), 0.1, f"arrival lag p95 {np.percentile(lag, 95):.3f} s")

    def test_injected_offset_is_recovered(self):
        fit = A.align(self.t, self.x, self.pose_t, self.pose_x, context_s=6.0)
        self.assertFalse(fit.drift_measured, "13 s is too short to measure drift; the fit must say so")
        truth = self.OFFSET + (self.t - self.t_send0) * (1 + self.DRIFT)   # pose time of what each frame shows
        err = A.to_pose_time(fit, self.t) - truth
        print(f"\n  mock stream: {fit.summary()}\n  mapping error over all frames: median "
              f"{np.median(err) * 1000:+.1f} ms, max |.| {np.abs(err).max() * 1000:.1f} ms", file=sys.stderr)
        self.assertLess(np.abs(np.median(err)), MOCK_TOL_S, fit.summary())
        # and the fitted line, at the two events, matches the truth there
        for e in fit.events:
            e_truth = self.OFFSET + (e.t_frame - self.t_send0) - e.t_frame
            self.assertLess(abs(e.offset_s - e_truth), MOCK_TOL_S, fit.summary())


if __name__ == "__main__":
    unittest.main()
