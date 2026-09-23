"""Unit tests for tape_check.evaluate (no drone, no cflib).  Run: python tools/lighthouse/test_tape_check.py"""
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tape_check as T  # noqa: E402


def fake(x, y, yaw, z=0.02, jitter=0.004, n=60, seed=0):
    r = random.Random(seed)
    return [dict(x=x + r.gauss(0, jitter), y=y + r.gauss(0, jitter), z=z + r.gauss(0, jitter),
                 yaw=yaw + r.gauss(0, 0.5)) for _ in range(n)]


A, B, C, D = T.STEPS


class TapeCheck(unittest.TestCase):
    def test_all_correct_pass(self):
        for step, s in ((A, fake(0, 0, 0)), (B, fake(1.0, 0, 0)), (C, fake(0, T.SIDE_Y, 0)), (D, fake(0, 0, 90))):
            self.assertEqual(T.evaluate(step, s)["verdict"], "PASS", step[0])

    def test_small_placement_error_still_passes(self):
        self.assertEqual(T.evaluate(B, fake(1.05, -0.04, 6))["verdict"], "PASS")

    def test_mirrored_room_frame_named(self):
        v = T.evaluate(C, fake(0, -T.SIDE_Y, 0))
        self.assertEqual(v["verdict"], "FAIL")
        self.assertIn("mirrored", " ".join(v["why"]))

    def test_yaw_sign_backwards_named(self):
        v = T.evaluate(D, fake(0, 0, -90))
        self.assertEqual(v["verdict"], "FAIL")
        self.assertIn("yaw sign is backwards", " ".join(v["why"]))

    def test_yaw_wraps_around_180(self):
        # facing the window but reported as 359 deg must still be 0
        self.assertEqual(T.evaluate(A, fake(0, 0, 359.0))["verdict"], "PASS")
        self.assertEqual(T.evaluate(A, fake(0, 0, -179.5) + fake(0, 0, 179.5, seed=1))["verdict"], "FAIL")

    def test_wrong_origin_named(self):
        v = T.evaluate(A, fake(0.4, 0.3, 0))
        self.assertIn("origin", " ".join(v["why"]))

    def test_jitter_warned(self):
        v = T.evaluate(A, fake(0, 0, 0, jitter=0.05))
        self.assertIn("jittery", " ".join(v["why"]))

    def test_too_few_samples(self):
        self.assertEqual(T.evaluate(A, fake(0, 0, 0, n=3))["verdict"], "NO DATA")


if __name__ == "__main__":
    unittest.main(verbosity=1)
