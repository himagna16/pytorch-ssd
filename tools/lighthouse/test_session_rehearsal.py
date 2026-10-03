#!/usr/bin/env python3
"""END-TO-END rehearsal of a Lighthouse session, no hardware. Opt-in (about 3 minutes):

    LH_REHEARSAL=1 ~/Downloads/drone/trainenv/bin/python -m unittest tools/lighthouse/test_session_rehearsal.py -v

What runs, for real: the two-drone CrazySim SITL pair (run_pair_sim.sh, Docker image
crazysim-mac:arm64), record_session.py --mock under cfloaderenv (cflib to the SITL
follower, read-only, the rate probe, the CSV/meta writers, cpx_grab.py under trainenv,
the cue clock), mock_streamer.py --timeline serving simulator renders of the scripted
subject at 2 fps (the real deck's rate), late by a KNOWN 0.15 s, and label_session.py
with the CHIP network (model_id_dory.onnx in doryenv).

What is scripted: the BEACON. A SITL drone that never flies never moves, so it cannot
make a sync step; the beacon is a software drone with its own clock (injected boot
offset 37.25 s, +50 ppm drift, 2-8 ms receive latency) walking the cue schedule.

Truth: every served frame is stamped with the instant it shows, so the error of the
recovered frame->pose clock mapping is measured frame by frame, not assumed.
Nothing here says anything about the real radio, the real WiFi or real latency.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
DRONE = REPO.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO / "tools" / "real_frames"))
import session_common as S  # noqa: E402

CF_PY = DRONE / "cfloaderenv" / "bin" / "python"
TRAIN_PY = DRONE / "trainenv" / "bin" / "python"
ONNX = DRONE / "pytorch_ssd_unstable/logs/plain_follow_prod_qat_v3/quant_eval/model_id_dory.onnx"
SECONDS = 90
# align_clocks recovered 25 ms at 10-15 fps. At the deck's ~2 fps, seven 90 s rehearsal runs gave
# -35..+16 ms (rms 18 ms) against the stamped truth, so 25 ms is NOT reliably met here. The README's
# requirement is 70 ms (2 deg for a subject crossing at 1 m/s at 2 m); this asserts 50 ms.
TOL_S = 0.050


def _have_image():
    try:
        return subprocess.run(["docker", "image", "inspect", "crazysim-mac:arm64"], capture_output=True,
                              timeout=30).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


@unittest.skipUnless(os.environ.get("LH_REHEARSAL") == "1", "opt-in: LH_REHEARSAL=1 (needs Docker, ~3 min)")
class Rehearsal(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        for p in (CF_PY, TRAIN_PY, ONNX):
            if not p.exists():
                raise unittest.SkipTest(f"missing {p}")
        if not _have_image():
            raise unittest.SkipTest("Docker image crazysim-mac:arm64 not available")
        cls.tmp = tempfile.mkdtemp(prefix="lh_rehearsal_")
        cls.out = Path(cls.tmp) / "session"
        env = dict(os.environ, CAMERA_CHECK_QUIET="1")
        subprocess.run(["bash", str(HERE / "run_pair_sim.sh")], check=True, capture_output=True, timeout=120)
        try:
            import time
            time.sleep(5)
            cls.rec = subprocess.run([str(CF_PY), str(HERE / "record_session.py"), "--mock", "--seconds", str(SECONDS),
                                      "--height", "1.75", "--mount", "0", "0", "0", "--out", str(cls.out)],
                                     capture_output=True, text=True, timeout=900, env=env)
        finally:
            subprocess.run(["bash", str(HERE / "run_pair_sim.sh"), "stop"], capture_output=True, timeout=60)
        cls.lab = subprocess.run([str(TRAIN_PY), str(HERE / "label_session.py"), str(cls.out)],
                                 capture_output=True, text=True, timeout=900)
        cls.meta = json.loads((cls.out / "meta.json").read_text())
        cls.rep = json.loads((cls.out / "label_summary.json").read_text()) if (cls.out / "label_summary.json").exists() else {}
        print("\n" + cls.rec.stdout[-2500:] + "\n" + cls.lab.stdout[-4000:], file=sys.stderr)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_recording_complete(self):
        self.assertEqual(self.rec.returncode, 0, self.rec.stdout[-3000:] + self.rec.stderr[-2000:])
        m = self.meta
        self.assertEqual(m["stopped_because"], "completed")
        self.assertEqual(m["firmware"]["follower"]["write_guards"] > 0, True, "SITL follower opened read-only")
        for r in ("follower", "beacon"):
            st = m["log"]["achieved"][r]
            self.assertGreater(st["achieved_hz"], 95.0, r)
            self.assertGreater(st["delivery"], 0.98, r)
            self.assertIsNotNone(m["battery_v"][r]["start"])
        self.assertGreater(m["frames"]["n"], 1.5 * SECONDS)
        self.assertEqual([c["phase"] for c in m["cues"]][0], "start_still")
        self.assertEqual([c["phase"] for c in m["cues"]][-1], "done")
        print(f"\n  achieved: " + "; ".join(f"{r} {st['achieved_hz']:.2f} Hz, {st['missing']} missing, "
                                           f"max gap {st['max_gap_ms']} ms" for r, st in m["log"]["achieved"].items()),
              file=sys.stderr)

    def test_labels_pass(self):
        self.assertEqual(self.lab.returncode, 0, self.lab.stdout[-3000:] + self.lab.stderr[-2000:])
        self.assertTrue(self.rep["mirror_check_passed"])
        self.assertGreater(self.rep["xbin_pm1"], 0.9)

    def test_clock_mapping_matches_the_stamped_truth(self):
        import mock_streamer as M
        al = self.rep["alignment"]
        epoch = self.meta["mock_details"]["epoch_unix"]
        fr = S.list_frames(self.out / S.FRAMES_DIR)
        t = np.array([f[0] for f in fr])
        shown = np.array([M.read_stamp(np.asarray(Image.open(self.out / S.FRAMES_DIR / f[2]).convert("L"))) for f in fr])
        truth = epoch + shown                          # the laptop-clock instant each frame shows
        err = al["a"] * t + al["b"] - truth
        print(f"\n  injected content lag {self.meta['mock_details']['content_lag_s']} s; true arrival->instant "
              f"{np.median(truth - t) * 1000:+.1f} ms; recovered {al['offset_mid_s'] * 1000:+.1f} ms; mapping error "
              f"median {np.median(err) * 1000:+.1f} ms, max |.| {np.abs(err).max() * 1000:.1f} ms", file=sys.stderr)
        self.assertLess(abs(np.median(err)), TOL_S)
        self.assertLess(np.abs(err).max(), TOL_S)

    def test_beacon_crazyflie_clock_recovered(self):
        c = self.rep["cf_clock"]["beacon"]
        inj = self.meta["firmware"]["beacon"]["scripted"]
        x = np.linspace(c["x0"], c["x0"] + SECONDS, 7)
        mapped = x + c["c0"] + c["c1"] * (x - c["x0"])
        truth = inj["t_boot_unix"] + x / (1 + inj["drift_ppm"] * 1e-6)
        err = mapped - truth
        print(f"\n  beacon Crazyflie clock -> laptop: error {err.min() * 1000:+.2f}..{err.max() * 1000:+.2f} ms "
              f"(the 2 ms minimum radio latency is expected); drift {-c['drift_ppm']:+.1f} ppm vs injected "
              f"{inj['drift_ppm']:+.1f}", file=sys.stderr)
        self.assertLess(np.abs(err).max(), 0.005)
        self.assertAlmostEqual(-c["drift_ppm"], inj["drift_ppm"], delta=10)


if __name__ == "__main__":
    unittest.main()
