#!/usr/bin/env python3
"""Tests for pose_to_label.py. Run:

    ~/Downloads/drone/trainenv/bin/python -m unittest tools/lighthouse/test_pose_to_label.py -v

Every sign convention in the module is pinned here by a geometry worked out by
hand, so that changing one breaks a test with a sentence saying which way is
left. The mirror tests at the bottom are the ones that must FAIL LOUDLY if the
yaw sign, the bearing sign or the room frame's handedness is ever flipped.
"""
import csv
import math
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
import pose_to_label as P  # noqa: E402

LEVEL_NO_MOUNT = P.CameraSpec(mount_xyz_body=(0.0, 0.0, 0.0))
H175 = P.SubjectSpec(height_m=1.75)


def head(x, y, height=1.75):
    """Beacon position for a person standing on the floor (z = 0) at (x, y)."""
    return (x, y, height)


class WorkedExample(unittest.TestCase):
    """The README's bench example: subject 2.0 m ahead, 0.5 m to the LEFT,
    1.75 m tall, camera lens 0.8 m up, level, drone facing +x."""

    def setUp(self):
        self.lab = P.pose_to_label(P.Pose(0, 0, 0.8, 0.0), head(2.0, 0.5), H175, LEVEL_NO_MOUNT)

    def test_bearing(self):
        self.assertAlmostEqual(self.lab.bearing_deg, -math.degrees(math.atan2(0.5, 2.0)), places=9)
        self.assertAlmostEqual(self.lab.bearing_deg, -14.036, places=3)

    def test_image_x_and_bin(self):
        self.assertAlmostEqual(self.lab.x_norm, -0.25 / math.tan(math.radians(35)), places=9)   # -0.3570
        self.assertEqual(self.lab.x_bin, 2)

    def test_size(self):
        t = math.tan(math.radians(35))
        want = ((1.75 - 0.8) / 2.0 / t + 0.8 / 2.0 / t) / 2      # = 1.75 / (2 * 2.0 * tan 35)
        self.assertAlmostEqual(self.lab.size_frac, want, places=9)
        self.assertAlmostEqual(self.lab.size_frac, 0.6248, places=4)
        self.assertEqual(self.lab.size_bucket, 2)

    def test_distances(self):
        self.assertAlmostEqual(self.lab.depth_m, 2.0, places=12)
        self.assertAlmostEqual(self.lab.horiz_range_m, math.hypot(2.0, 0.5), places=12)
        self.assertTrue(self.lab.in_fov and self.lab.fully_in_view)


class SignConventions(unittest.TestCase):
    def test_left_is_negative_bearing_and_low_bins(self):
        # Crazyflie body/room frame: y points LEFT. A subject at +y is on the drone's left.
        left = P.pose_to_label(P.Pose(0, 0, 0.8, 0), head(3.0, 1.0))
        right = P.pose_to_label(P.Pose(0, 0, 0.8, 0), head(3.0, -1.0))
        self.assertLess(left.bearing_deg, 0, "subject on the drone's LEFT must give a NEGATIVE bearing")
        self.assertLess(left.x_bin, P.CENTRE_BIN, "LEFT must land in x-bins 0-3")
        self.assertGreater(right.bearing_deg, 0)
        self.assertGreater(right.x_bin, P.CENTRE_BIN)
        self.assertEqual(left.x_bin + right.x_bin, 8, "mirror-image subjects must give mirror-image bins")

    def test_yaw_is_counter_clockwise_positive(self):
        # yaw +90: the nose has turned LEFT and now points along room +y.
        f = P.Pose(0, 0, 0.8, 90.0)
        ahead = P.pose_to_label(f, head(0.0, 3.0))
        self.assertAlmostEqual(ahead.bearing_deg, 0.0, places=9)
        self.assertEqual(ahead.x_bin, 4)
        # Facing +y, the drone's left is room -x.
        left = P.pose_to_label(f, head(-1.0, 3.0))
        self.assertLess(left.bearing_deg, 0)
        self.assertLess(left.x_bin, 4)
        # A subject straight along room +x is now 90 deg to the RIGHT: out of view.
        side = P.pose_to_label(f, head(3.0, 0.0), cam=LEVEL_NO_MOUNT)
        self.assertAlmostEqual(side.bearing_deg, 90.0, places=6)
        self.assertFalse(side.in_fov)

    def test_yaw_matches_scoreboard_bearing_with_opposite_sign(self):
        # scoreboard.py: bearing = atan2(dy, dx) - yaw  (CCW/left positive)
        for yaw in (-170, -45, -3, 0, 12, 90, 179):
            for tx, ty in ((3, 1), (2, -0.4), (-1, 2.5), (0.5, -3)):
                sb = (math.degrees(math.atan2(ty, tx)) - yaw + 180) % 360 - 180
                lab = P.pose_to_label(P.Pose(0, 0, 0.8, yaw), head(tx, ty), cam=LEVEL_NO_MOUNT)
                self.assertAlmostEqual(lab.bearing_deg, -sb, places=9)

    def test_pitch_as_logged_is_nose_up_positive(self):
        # Logged stabilizer.pitch > 0 = nose UP (firmware negates it). With the nose
        # up, a target level with the lens appears BELOW the image centre.
        subj = P.SubjectSpec(height_m=1.6, target_frac=0.5)       # target z = 0.8 = lens height
        lab = P.pose_to_label(P.Pose(0, 0, 0.8, 0, 0, 10.0), head(3.0, 0.0, 1.6), subj, LEVEL_NO_MOUNT)
        self.assertAlmostEqual(lab.elevation_deg, -10.0, places=6)

    def test_roll_right_side_down_moves_high_targets_left(self):
        # Positive roll drops the RIGHT side. The camera rotates clockwise as seen
        # from behind, so a target ABOVE the optical axis moves to the image LEFT.
        subj = P.SubjectSpec(height_m=1.75, target_frac=1.0)       # target = head top, 0.95 m above lens
        lab = P.pose_to_label(P.Pose(0, 0, 0.8, 0, 10.0, 0), head(3.0, 0.0), subj, LEVEL_NO_MOUNT)
        self.assertLess(lab.bearing_deg, 0)
        level = P.pose_to_label(P.Pose(0, 0, 0.8, 0, 0.0, 0), head(3.0, 0.0), subj, LEVEL_NO_MOUNT)
        self.assertAlmostEqual(level.bearing_deg, 0.0, places=9)

    def test_translation_of_the_follower(self):
        a = P.pose_to_label(P.Pose(0, 0, 0.8, 30), head(2.0, 1.0))
        b = P.pose_to_label(P.Pose(5, -7, 0.8, 30), head(7.0, -6.0))
        self.assertAlmostEqual(a.bearing_deg, b.bearing_deg, places=9)
        self.assertEqual(a.x_bin, b.x_bin)


class HeadToTargetOffset(unittest.TestCase):
    def test_default_is_half_height_below_the_head(self):
        s = P.SubjectSpec(height_m=1.75)
        self.assertAlmostEqual(s.target_z(1.75), 0.875)
        self.assertAlmostEqual(s.feet_z(1.75), 0.0)
        self.assertAlmostEqual(s.head_to_target_offset_m(), 0.875)

    def test_beacon_mount_height_is_subtracted(self):
        s = P.SubjectSpec(height_m=1.80, beacon_above_head_m=0.04)
        self.assertAlmostEqual(s.head_top_z(1.84), 1.80)
        self.assertAlmostEqual(s.feet_z(1.84), 0.0)
        self.assertAlmostEqual(s.head_to_target_offset_m(), 0.94)

    def test_target_height_does_not_move_x_on_a_level_camera(self):
        for frac in (0.3, 0.5, 0.8):
            lab = P.pose_to_label(P.Pose(0, 0, 0.8, 0), head(2.5, 0.7), P.SubjectSpec(1.75, 0, frac))
            self.assertAlmostEqual(lab.x_norm, -0.7 / 2.47 / math.tan(math.radians(35)), places=9)


class ProjectGeometry(unittest.TestCase):
    """Cross-checks against the geometry the project already uses."""

    def test_bins_match_capture_protocol_marks(self):
        # docs/real_frame_capture_protocol.md: bearings -25/-10/0/+10/+25 land in the
        # middle of x-bins 1, 3, 4, 5, 7.
        for b, want in ((-25, 1), (-10, 3), (0, 4), (10, 5), (25, 7)):
            d = 2.5
            beacon = head(d * math.cos(math.radians(b)), -d * math.sin(math.radians(b)))
            lab = P.pose_to_label(P.Pose(0, 0, 0.8, 0), beacon, cam=LEVEL_NO_MOUNT)
            self.assertAlmostEqual(lab.bearing_deg, b, places=9)
            self.assertEqual(lab.x_bin, want, f"bearing {b}")

    def test_size_bucket_edges_match_the_m7_analysis(self):
        # m7_gate_analysis.md: for a 1.7 m person, size 0.5 at 2.428 m and 0.75 at 1.619 m.
        s = P.SubjectSpec(height_m=1.7)
        lab = lambda d: P.pose_to_label(P.Pose(0, 0, 0.8, 0), head(d, 0, 1.7), s, LEVEL_NO_MOUNT)
        self.assertAlmostEqual(lab(1.7 / (2 * 0.5 * math.tan(math.radians(35)))).size_frac, 0.5, places=9)
        self.assertEqual(lab(2.44).size_bucket, 1)
        self.assertEqual(lab(2.42).size_bucket, 2)
        self.assertEqual(lab(1.63).size_bucket, 2)
        self.assertEqual(lab(1.61).size_bucket, 3)

    def test_agrees_with_score_real_frames(self):
        try:
            sys.path.insert(0, str(REPO / "tools" / "real_frames"))
            import score_real_frames as S
        except Exception as e:              # pragma: no cover - needs numpy + PIL
            self.skipTest(f"score_real_frames not importable: {e}")
        self.assertEqual(tuple(S.XBIN9_INNER), P.XBIN9_INNER)
        self.assertEqual(tuple(S.SIZE4_INNER), P.SIZE4_INNER)
        for d in (1.5, 2.5, 3.5):
            for b in (-25, -10, 0, 10, 25):
                beacon = head(d * math.cos(math.radians(b)), -d * math.sin(math.radians(b)))
                lab = P.pose_to_label(P.Pose(0, 0, 0.8, 0), beacon, H175, LEVEL_NO_MOUNT)
                self.assertAlmostEqual(lab.x_norm, S.expected_x(b, 70.0), places=9)
                self.assertEqual(lab.x_bin, S.x_to_bin(S.expected_x(b, 70.0)))
                # score_real_frames uses straight-line distance where depth belongs;
                # they coincide at b = 0 only.
                if b == 0:
                    self.assertAlmostEqual(lab.size_frac, S.expected_size(d, 1.75, 0.8, 70.0), places=9)

    def test_crop_fov_from_full_fov(self):
        # Sim: fovy 70 over 244 rows -> full HFOV over 324 columns = 2 atan(tan35 * 324/244).
        full = math.degrees(2 * math.atan(math.tan(math.radians(35)) * 324 / 244))
        self.assertAlmostEqual(P.CameraSpec.from_full_hfov(full).crop_hfov_deg, 70.0, places=9)


class FieldOfView(unittest.TestCase):
    def test_behind(self):
        lab = P.pose_to_label(P.Pose(0, 0, 0.8, 0), head(-2.5, 0.0))
        self.assertFalse(lab.in_fov)
        self.assertIsNone(lab.x_bin)
        self.assertIn("behind", lab.why_not)

    def test_edge_of_the_crop(self):
        inside = P.pose_to_label(P.Pose(0, 0, 0.8, 0), head(3.0, -3.0 * math.tan(math.radians(34.5))),
                                 cam=LEVEL_NO_MOUNT)
        outside = P.pose_to_label(P.Pose(0, 0, 0.8, 0), head(3.0, -3.0 * math.tan(math.radians(35.5))),
                                  cam=LEVEL_NO_MOUNT)
        self.assertTrue(inside.in_fov)
        self.assertEqual(inside.x_bin, 8)
        self.assertFalse(outside.in_fov)
        self.assertIn("horizontally", outside.why_not)

    def test_too_close_is_clipped_not_dropped(self):
        lab = P.pose_to_label(P.Pose(0, 0, 0.8, 0), head(0.6, 0.0), H175, LEVEL_NO_MOUNT)
        self.assertTrue(lab.in_fov)
        self.assertFalse(lab.fully_in_view)
        self.assertEqual(lab.size_bucket, 3)


class PoseIntegrity(unittest.TestCase):
    def test_smooth_turn_passes(self):
        t = [i * 0.07 for i in range(100)]
        yaw = [((40.0 * ti + 180) % 360) - 180 for ti in t]          # 40 deg/s, wraps through +-180
        self.assertIsNone(P.first_pose_discontinuity(t, yaw, [0.0] * 100, [2.0] * 100))

    def test_tumble_and_reset_are_caught(self):
        # The crash signature from the sim logs: roll -110, yaw jumping, then yaw reset to 0.
        t = [0.0, 0.07, 0.14, 0.21, 0.28]
        self.assertEqual(P.first_pose_discontinuity(t, [13.0, 13.8, 57.7, 129.1, 0.0],
                                                    [0.0, 0.1, 0.2, -109.9, 0.0], [0.0] * 5), 2)
        self.assertEqual(P.first_pose_discontinuity(t, [0.0] * 5, [0.0, 0.0, 35.0, 0.0, 0.0], [0.0] * 5), 2)


# --------------------------------------------------------------------------
# The mirror tests. These are the reason this module exists.
# --------------------------------------------------------------------------
def _scene(n=40):
    """A drone that has yawed to several headings, subjects on both sides of it.
    Returns (follower poses, beacons, the bin a correct network outputs).

    The 'network' here is an independent, hand-written pinhole on the protocol's
    convention (negative bearing = left = low bins), NOT pose_to_label, so the
    test does not grade the module against itself."""
    poses, beacons, bins = [], [], []
    for k in range(n):
        yaw = -60 + 120 * k / (n - 1)                  # headings from 60 deg right to 60 deg left
        rel = -25 if k % 2 == 0 else 25                # subject 25 deg left / right of the nose
        d = 2.5
        world_dir = math.radians(yaw - rel)            # CCW heading of the subject from the drone
        poses.append(P.Pose(1.0, -2.0, 0.8, yaw))
        beacons.append((1.0 + d * math.cos(world_dir), -2.0 + d * math.sin(world_dir), 1.75))
        x = math.tan(math.radians(rel)) / math.tan(math.radians(35))
        bins.append(P.bucketize(x, P.XBIN9_INNER))
    return poses, beacons, bins


class MirrorGuard(unittest.TestCase):
    def test_correct_convention_passes(self):
        poses, beacons, bins = _scene()
        labs = [P.pose_to_label(p, b, cam=LEVEL_NO_MOUNT) for p, b in zip(poses, beacons)]
        self.assertEqual([l.x_bin for l in labs], bins)
        P.check_not_mirrored([l.bearing_deg for l in labs], bins, min_n=10)

    def test_flipped_bearing_sign_fails_loudly(self):
        poses, beacons, bins = _scene()
        labs = [P.pose_to_label(p, b, cam=LEVEL_NO_MOUNT) for p, b in zip(poses, beacons)]
        with self.assertRaises(P.MirroredLabelsError) as cm:
            P.check_not_mirrored([-l.bearing_deg for l in labs], bins, min_n=10)
        self.assertIn("MIRRORED", str(cm.exception))

    def test_clockwise_yaw_fails_loudly(self):
        # Someone feeds yaw in as clockwise-positive (e.g. a compass heading).
        poses, beacons, bins = _scene()
        labs = [P.pose_to_label(P.Pose(p.x, p.y, p.z, -p.yaw_deg), b, cam=LEVEL_NO_MOUNT)
                for p, b in zip(poses, beacons)]
        with self.assertRaises(P.MirroredLabelsError):
            P.check_not_mirrored([l.bearing_deg for l in labs], bins, min_n=10)

    def test_left_handed_room_frame_fails_loudly(self):
        # Positions exported with y pointing RIGHT while yaw stays counter-clockwise.
        poses, beacons, bins = _scene()
        labs = [P.pose_to_label(P.Pose(p.x, -p.y, p.z, p.yaw_deg), (b[0], -b[1], b[2]), cam=LEVEL_NO_MOUNT)
                for p, b in zip(poses, beacons)]
        with self.assertRaises(P.MirroredLabelsError):
            P.check_not_mirrored([l.bearing_deg for l in labs], bins, min_n=10)

    def test_one_sided_data_is_refused(self):
        poses, beacons, bins = _scene()
        left = [(P.pose_to_label(p, b).bearing_deg, k) for p, b, k in zip(poses, beacons, bins) if k < 4]
        with self.assertRaises(P.MirroredLabelsError) as cm:
            P.check_not_mirrored([a for a, _ in left], [k for _, k in left], min_n=10)
        self.assertIn("right", str(cm.exception))


SIM_FLIGHT = REPO / "docs/eval_results/2026-09-13-champion-threshold/runs/t080__D.occlusion__ships__r4a1"


@unittest.skipUnless((SIM_FLIGHT / "follow_log.csv").exists(), "archived sim flight not present")
class MirrorOnARealSimFlight(unittest.TestCase):
    """One archived CrazySim flight (s07: champion chip network, himax camera; subject
    swaying +-1.6 m at 3.5 m behind an occluder, drone following and turning both ways).
    Poses: the firmware's logged estimate; subject: simulator truth joined on the wall
    clock; 'network': what the network actually output on each frame."""

    @classmethod
    def setUpClass(cls):
        truth = []
        for line in (SIM_FLIGHT / "truth.csv").read_text().splitlines():
            if not line.startswith("#"):
                truth.append([float(v) for v in line.split(",")])
        tw = [r[0] for r in truth]

        def interp(t, col):
            import bisect
            i = min(max(bisect.bisect_left(tw, t), 1), len(tw) - 1)
            a, b = truth[i - 1], truth[i]
            w = (t - a[0]) / (b[0] - a[0]) if b[0] > a[0] else 0.0
            return a[col] + w * (b[col] - a[col])

        cls.rows = []
        with open(SIM_FLIGHT / "follow_log.csv") as f:
            log = [r for r in csv.DictReader(f) if not r["event"]]
        fl = lambda k: [float(r[k]) for r in log]
        cut = P.first_pose_discontinuity(fl("t"), fl("yaw"), fl("roll"), fl("pitch"))
        stale = P.stalled_pose_mask(fl("t"), [v / 1000 for v in fl("fw_ts")])
        cls.n_gated = (len(log) - cut if cut is not None else 0) + sum(stale)
        for i, r in enumerate(log):
            if (cut is not None and i >= cut) or stale[i] or float(r["conf"]) < 0.5:
                continue
            wall = float(r["wall"]) - (float(r["t"]) - float(r["t_proc"])) - float(r["frame_age"])
            pose = P.Pose(float(r["px"]), float(r["py"]), float(r["pz"]), float(r["yaw"]),
                          float(r["roll"]), float(r["pitch"]))
            beacon = (interp(wall, 2), interp(wall, 3), interp(wall, 4) + 0.85)   # panel centre + H/2
            cls.rows.append((pose, beacon, int(r["x_bin"])))

    def _labels(self, flip_yaw=False):
        subj = P.SubjectSpec(height_m=1.7)
        out = []
        for pose, beacon, _ in self.rows:
            if flip_yaw:
                pose = P.Pose(pose.x, pose.y, pose.z, -pose.yaw_deg, pose.roll_deg, pose.pitch_deg)
            out.append(P.pose_to_label(pose, beacon, subj))
        return out

    def test_the_flight_is_clean(self):
        self.assertEqual(self.n_gated, 0)
        self.assertGreater(len(self.rows), 100)

    def test_correct_convention_passes_on_sim_data(self):
        labs = self._labels()
        sa = P.check_not_mirrored([l.bearing_deg for l in labs], [k for *_, k in self.rows])
        self.assertGreaterEqual(min(sa["left"][1], sa["right"][1]), 0.9)

    def test_flipped_yaw_fails_on_sim_data(self):
        labs = self._labels(flip_yaw=True)
        with self.assertRaises(P.MirroredLabelsError):
            P.check_not_mirrored([l.bearing_deg for l in labs], [k for *_, k in self.rows])

    def test_flipped_bearing_is_called_mirrored_on_sim_data(self):
        labs = self._labels()
        with self.assertRaises(P.MirroredLabelsError) as cm:
            P.check_not_mirrored([-l.bearing_deg for l in labs], [k for *_, k in self.rows])
        self.assertIn("MIRRORED", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
