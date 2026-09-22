#!/usr/bin/env python3
"""Turn two poses into the label the follow network SHOULD output.

Plan: docs/hardware/before_the_next_session.md section 3.3(a). Plain-English
guide: tools/lighthouse/README.md. Validation against simulator truth:
docs/eval_results/2026-09-22-pose-to-label-sim-validation/.

Inputs
------
* the FOLLOWER's pose (the drone with the camera), and
* the SUBJECT BEACON's pose (a second Crazyflie, props off, riding on the
  subject's head),

both in one room-fixed frame. Output: where the subject is relative to the
camera, and the x-bin (0-8) and size bucket (0-3) the network should produce on
the frame taken at that instant, plus an in-field-of-view flag so a subject who
is outside the image is never counted as a network miss.

CONVENTIONS (each one is pinned by a test in test_pose_to_label.py)
------------------------------------------------------------------
Room frame. Right-handed, metres, z up. This is what Lighthouse produces: the
cflib geometry estimator aligns the solution to an ORIGIN sample, a sample on
the +X axis and XY-plane samples, and flips it so the base stations sit above
the floor (cflib docs/functional-areas/lighthouse.md). It is also CrazySim's
MuJoCo world frame.

Follower attitude = the Crazyflie's own logged Euler angles, in DEGREES,
exactly as `stateEstimate.{roll,pitch,yaw}` / `stabilizer.{roll,pitch,yaw}`
report them. Bitcraze's coordinate-system page (body x forward, y left, z up):
  - yaw   positive turns the nose LEFT (counter-clockwise seen from above);
          firmware kalman_core.c: yaw = atan2(2(q1q2+q0q3), q0^2+q1^2-q2^2-q3^2),
          i.e. the ordinary right-hand-rule heading, no sign change;
  - roll  positive drops the RIGHT side (right-hand rule about x);
  - pitch positive RAISES the nose - the one axis that is NOT right-handed:
          kalman_core.c externalises `.pitch = -pitch*RAD_TO_DEG`. This module
          negates it back. Pass the logged number unchanged.
So a real Lighthouse log (stateEstimate.x/y/z + stabilizer.roll/pitch/yaw)
drops into `Pose` with no conversion, and so does CrazySim's follow_log.csv
(px, py, pz, roll, pitch, yaw).

Bearing sign: NEGATIVE = subject to the drone's LEFT, positive = RIGHT, as seen
from behind the drone looking the way it faces. This is the convention of the
capture protocol (docs/real_frame_capture_protocol.md section 2), of
score_real_frames.py and of the network's x axis (x-bin 0 = left edge ..
8 = right edge). WARNING: it is the OPPOSITE sense to the Crazyflie's yaw, and
to the internal `bearing` in tools/crazysim_macos/scoreboard.py, which is
atan2(dy, dx) - yaw (counter-clockwise positive, i.e. LEFT positive). Scoreboard
only ever uses its absolute value, so it never mattered there. Here it does.

Image x. The network sees a centred square crop of the frame (244x244 of
324x244, resized to 128x128). x in [-1, 1] across that crop, positive RIGHT,
from a pinhole model: x = tan(horizontal angle) / tan(crop_hfov / 2), which is
utils/coco_follow_regression.py's `2 * (box_centre_x / width) - 1` for a box
centred on the target. x-bin = 9 equal bins over [-1, 1], bucketed exactly like
training (torch.bucketize, right=False; same edges as score_real_frames.py).

Size. The training label is box_height / image_height of the COCO person box
(utils/coco_follow_regression.py), bucketed into 4 equal buckets over [0, 1].
Here the box runs from the top of the head to the feet, each projected through
the pinhole and clipped to the crop, so

    size = (v_head_top - v_feet) / 2      with v = (up / forward) / tan(crop_vfov / 2)

clipped to [-1, 1] each. For a level camera this is score_real_frames.py's
`expected_size`, and unclipped it is the project's size geometry
`H / (2 d tan 35)` (docs/eval_results/2026-09-12-distance/m7_gate_analysis.md:
bucket edges 0.5 / 0.75 sit at 2.428 m / 1.619 m for a 1.7 m person). Depth
`d` is distance along the optical axis, not straight-line range.

HEAD-TO-TARGET OFFSET (plan section 3.3b; written down here so it is not a
silent bias). The beacon sits on top of the head; the label target is the
centre of the COCO box, which for a standing person is at half their height
(the box runs head-top to feet), i.e. around the hips, NOT the chest. So

    head_top_z = beacon_z - beacon_above_head_m
    feet_z     = head_top_z - height_m
    target_z   = feet_z + target_frac * height_m        (default target_frac 0.5)

with the target directly below the beacon (the head is assumed to be over the
body; a lean moves the head sideways and becomes a label error, see README).
`height_m` is each subject's measured standing height; `beacon_above_head_m` is
the measured height of the beacon's Lighthouse deck above the top of the head.
For a level camera the target's height does not change x or the x-bin at all;
it matters through roll, pitch and camera tilt, and for the in-view flag.

Camera mount. `CameraSpec.mount_xyz_body` is the lens position in the body
frame (CrazySim's fpv_cam: 0.03 m forward, pos="0.03 0 0"); `mount_tilt_deg`
tilts the optical axis up (positive) from body forward. The real AI-deck's
values are NOT measured: see README "What is not known yet".
"""
from __future__ import annotations

import argparse
import math
from dataclasses import dataclass, asdict
from typing import Optional, Sequence

XBIN9_INNER = tuple(-1.0 + 2.0 * i / 9 for i in range(1, 9))   # utils/follow_task.py XBIN9_EDGES[1:-1]
SIZE4_INNER = (0.25, 0.5, 0.75)                               # SIZE_BUCKET4_EDGES[1:-1]
CENTRE_BIN = 4


def bucketize(v: float, inner_edges: Sequence[float]) -> int:
    """torch.bucketize(v, inner_edges, right=False): number of edges strictly below v."""
    return sum(1 for e in inner_edges if e < v)


def x_to_bin(x: Optional[float]) -> Optional[int]:
    """Training-label x-bin for image x in [-1, 1]; None outside the crop."""
    if x is None or not -1.0 <= x <= 1.0:
        return None
    return bucketize(x, XBIN9_INNER)


def size_to_bucket(s: float) -> int:
    return bucketize(s, SIZE4_INNER)


def bin_centre(b: int) -> float:
    """Centre of x-bin b in [-1, 1] (docs/firmware_contract.md decode rule 1)."""
    return -1.0 + (2 * b + 1) / 9.0


# --------------------------------------------------------------------------
# inputs
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Pose:
    """A Crazyflie pose in the room frame. Angles in DEGREES, Crazyflie sign
    convention (yaw CCW-positive, roll right-side-down positive, pitch
    nose-UP positive as logged). Pass logged values unchanged."""
    x: float
    y: float
    z: float
    yaw_deg: float = 0.0
    roll_deg: float = 0.0
    pitch_deg: float = 0.0


@dataclass(frozen=True)
class CameraSpec:
    """The image the network sees, and where the lens sits on the drone.

    Defaults are CrazySim's camera (fovy 70 over 244 rows, square pixels, so the
    244x244 centre crop is 70 x 70 deg; lens 0.03 m ahead of the body origin,
    level). For the real AI-deck, replace crop_hfov/vfov with the measured
    values (tools/real_frames/measure_camera.py) and measure the mount.
    """
    crop_hfov_deg: float = 70.0
    crop_vfov_deg: float = 70.0
    image_width_px: int = 128           # network input width; px column is reported in these units
    mount_xyz_body: tuple = (0.03, 0.0, 0.0)
    mount_tilt_deg: float = 0.0         # optical axis above body forward, degrees

    @staticmethod
    def from_full_hfov(full_hfov_deg: float, frame_w: int = 324, frame_h: int = 244, **kw) -> "CameraSpec":
        """Crop FOV from the FULL frame's measured horizontal FOV (pinhole, square pixels)."""
        t = math.tan(math.radians(full_hfov_deg) / 2) * min(frame_w, frame_h) / frame_w
        crop = math.degrees(2 * math.atan(t))
        return CameraSpec(crop_hfov_deg=crop, crop_vfov_deg=crop, **kw)


@dataclass(frozen=True)
class SubjectSpec:
    """How the beacon relates to the person. See the module docstring."""
    height_m: float = 1.75
    beacon_above_head_m: float = 0.0
    target_frac: float = 0.5            # label target height as a fraction of height_m above the feet

    def head_top_z(self, beacon_z: float) -> float:
        return beacon_z - self.beacon_above_head_m

    def feet_z(self, beacon_z: float) -> float:
        return self.head_top_z(beacon_z) - self.height_m

    def target_z(self, beacon_z: float) -> float:
        return self.feet_z(beacon_z) + self.target_frac * self.height_m

    def head_to_target_offset_m(self) -> float:
        """How far below the beacon the label target sits."""
        return self.beacon_above_head_m + (1.0 - self.target_frac) * self.height_m


# --------------------------------------------------------------------------
# geometry
# --------------------------------------------------------------------------
def _matmul(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


def _mat_t_vec(m, v):
    """m^T v."""
    return [sum(m[k][i] * v[k] for k in range(3)) for i in range(3)]


def body_to_world(pose: Pose):
    """Rotation matrix R_wb (columns = body x/y/z axes in the room frame).

    R = Rz(yaw) Ry(theta) Rx(roll), the ZYX order the firmware's quaternion-to-
    Euler conversion uses, with theta = -logged_pitch because the firmware
    negates pitch on the way out (kalman_core.c)."""
    ps, th, ph = math.radians(pose.yaw_deg), -math.radians(pose.pitch_deg), math.radians(pose.roll_deg)
    cz, sz, cy, sy, cx, sx = math.cos(ps), math.sin(ps), math.cos(th), math.sin(th), math.cos(ph), math.sin(ph)
    rz = [[cz, -sz, 0.0], [sz, cz, 0.0], [0.0, 0.0, 1.0]]
    ry = [[cy, 0.0, sy], [0.0, 1.0, 0.0], [-sy, 0.0, cy]]
    rx = [[1.0, 0.0, 0.0], [0.0, cx, -sx], [0.0, sx, cx]]
    return _matmul(rz, _matmul(ry, rx))


def world_to_body(follower: Pose, point_xyz) -> list:
    """A room-frame point expressed in the follower's body frame (x fwd, y left, z up)."""
    d = [point_xyz[0] - follower.x, point_xyz[1] - follower.y, point_xyz[2] - follower.z]
    return _mat_t_vec(body_to_world(follower), d)


def body_to_camera(v_body, cam: CameraSpec) -> list:
    """Body-frame vector -> camera frame (forward, left, up) from the lens."""
    m = cam.mount_xyz_body
    d = [v_body[0] - m[0], v_body[1] - m[1], v_body[2] - m[2]]
    t = math.radians(cam.mount_tilt_deg)
    # optical axis tilted up by t: forward_c = (cos t, 0, sin t), up_c = (-sin t, 0, cos t)
    fwd = d[0] * math.cos(t) + d[2] * math.sin(t)
    up = -d[0] * math.sin(t) + d[2] * math.cos(t)
    return [fwd, d[1], up]


@dataclass
class Label:
    # where the target is
    rel_body: tuple               # target in the follower body frame (x fwd, y left, z up), m
    rel_cam: tuple                # target in the camera frame (forward, left, up) from the lens, m
    bearing_deg: float            # horizontal angle in the camera; NEGATIVE = drone's LEFT
    elevation_deg: float          # positive = above the optical axis
    range_m: float                # straight-line lens -> target
    horiz_range_m: float          # body-horizontal distance body-origin -> target
    depth_m: float                # distance along the optical axis (what size scales with)
    # what the network should say
    x_norm: Optional[float]       # image x of the target in the crop, [-1, 1] = left..right edge
    px: Optional[float]           # same, in crop pixels (0 = left edge, image_width_px = right edge)
    x_bin: Optional[int]          # 0..8, None if outside the crop horizontally
    size_frac: Optional[float]    # box height / crop height after clipping to the crop
    size_bucket: Optional[int]    # 0..3
    in_fov: bool                  # target centre inside the crop AND some of the body vertically in it
    fully_in_view: bool           # in_fov and head-top and feet both inside the crop
    why_not: str = ""             # empty when in_fov; otherwise the reason

    def as_dict(self):
        return asdict(self)


def pose_to_label(follower: Pose, beacon_xyz, subject: SubjectSpec = SubjectSpec(),
                  cam: CameraSpec = CameraSpec()) -> Label:
    """The label for one frame. `beacon_xyz` is the head beacon's room-frame position."""
    bx, by, bz = float(beacon_xyz[0]), float(beacon_xyz[1]), float(beacon_xyz[2])
    tb = world_to_body(follower, (bx, by, subject.target_z(bz)))
    head_b = world_to_body(follower, (bx, by, subject.head_top_z(bz)))
    feet_b = world_to_body(follower, (bx, by, subject.feet_z(bz)))
    fwd, left, up = body_to_camera(tb, cam)
    th, tv = math.tan(math.radians(cam.crop_hfov_deg) / 2), math.tan(math.radians(cam.crop_vfov_deg) / 2)

    bearing = math.degrees(math.atan2(-left, fwd))
    elevation = math.degrees(math.atan2(up, math.hypot(fwd, left)))
    rng = math.sqrt(fwd * fwd + left * left + up * up)
    hr = math.hypot(tb[0], tb[1])

    x = px = xb = size = sb = None
    in_fov = fully = False
    why = ""
    if fwd <= 1e-9:
        why = "behind the camera"
    else:
        x = (-left / fwd) / th
        px = (x + 1.0) / 2.0 * cam.image_width_px
        hc, fc = body_to_camera(head_b, cam), body_to_camera(feet_b, cam)
        if hc[0] <= 1e-9 or fc[0] <= 1e-9:
            why = "part of the body is behind the camera plane (too close)"
        else:
            v_top = (hc[2] / hc[0]) / tv
            v_bot = (fc[2] / fc[0]) / tv
            if abs(x) > 1.0:
                why = "outside the crop horizontally"
            elif v_bot >= 1.0 or v_top <= -1.0:
                why = "outside the crop vertically"
            else:
                in_fov = True
                xb = x_to_bin(x)
                size = (max(-1.0, min(1.0, v_top)) - max(-1.0, min(1.0, v_bot))) / 2.0
                size = max(0.0, min(1.0, size))
                sb = size_to_bucket(size)
                fully = v_top <= 1.0 and v_bot >= -1.0
    return Label(rel_body=tuple(tb), rel_cam=(fwd, left, up), bearing_deg=bearing,
                 elevation_deg=elevation, range_m=rng, horiz_range_m=hr, depth_m=fwd,
                 x_norm=x, px=px, x_bin=xb, size_frac=size, size_bucket=sb,
                 in_fov=in_fov, fully_in_view=fully, why_not=why)


# --------------------------------------------------------------------------
# pose integrity: when the follower's pose stops being truth
# --------------------------------------------------------------------------
MAX_YAW_RATE_DPS = 120.0   # 3x the follower's 40 deg/s yaw cap: faster than this is not flight
MAX_TILT_DEG = 30.0        # a following drone at <= 0.3 m/s never tilts this far


def first_pose_discontinuity(t, yaw_deg, roll_deg, pitch_deg,
                             max_yaw_rate_dps=MAX_YAW_RATE_DPS, max_tilt_deg=MAX_TILT_DEG):
    """Index of the first sample from which the follower's logged pose can no
    longer be trusted as ground truth, or None.

    Found in the simulator logs (validation README): after a crash the firmware
    estimate tumbles (roll -110 deg, yaw jumping 60 deg between samples) and is
    then RESET to yaw 0.000 while the camera, lying on the floor, keeps
    streaming. Every label computed after that point is confidently wrong, and
    looks exactly like a mirrored label set. So: the first sample with a tilt
    past `max_tilt_deg`, or a yaw step faster than `max_yaw_rate_dps`, ends the
    usable part of the log. On hardware the same gate catches Lighthouse
    re-acquisition jumps; interpolating across such a gap is not safe."""
    for i in range(len(t)):
        if abs(roll_deg[i]) > max_tilt_deg or abs(pitch_deg[i]) > max_tilt_deg:
            return i
        if i > 0:
            dt = t[i] - t[i - 1]
            dy = (yaw_deg[i] - yaw_deg[i - 1] + 180.0) % 360.0 - 180.0
            if dt > 0 and abs(dy) / dt > max_yaw_rate_dps:
                return i
    return None


MAX_POSE_STALL_S = 0.5


def stalled_pose_mask(frame_t, pose_stamp_s, max_stall_s=MAX_POSE_STALL_S):
    """True for frames whose pose has stopped updating.

    `pose_stamp_s` is the pose sample's OWN timestamp (the Crazyflie log packet
    timestamp, in seconds) as carried alongside each frame; `frame_t` is the
    frame clock. A frame is stale when its pose stamp has not advanced for more
    than `max_stall_s` of frame time. Found in the simulator logs: a flight whose
    firmware stalled kept streaming frames for 38 s with the pose frozen at one
    value, and every label from it was wrong. On hardware this is a radio or
    Lighthouse dropout, and the frame gets no label (plan section 3.5: log
    dropouts, never silently interpolate across them)."""
    out, last_change_t, last_stamp = [], None, None
    for t, s in zip(frame_t, pose_stamp_s):
        if last_stamp is None or s != last_stamp:
            last_stamp, last_change_t = s, t
        out.append(t - last_change_t > max_stall_s)
    return out


# --------------------------------------------------------------------------
# the mirror guard
# --------------------------------------------------------------------------
class MirroredLabelsError(AssertionError):
    """Raised when pose-derived labels and the network disagree about LEFT vs RIGHT."""


MIRROR_MIN_DEG = 8.0     # score_real_frames.py's mirror check uses +-8 deg too
MIRROR_PASS = 0.90
MIRROR_MIN_N = 10


def side_agreement(pred_bearings, net_bins, min_deg=MIRROR_MIN_DEG):
    """For frames the POSES put clearly left (bearing <= -min_deg) or right
    (>= +min_deg), the fraction where the network's x-bin is on the same side
    of the centre bin. Returns {'left': (n, frac), 'right': (n, frac)}."""
    out = {}
    for side, sel, ok in (("left", lambda b: b <= -min_deg, lambda k: k < CENTRE_BIN),
                          ("right", lambda b: b >= min_deg, lambda k: k > CENTRE_BIN)):
        hits = [ok(k) for b, k in zip(pred_bearings, net_bins) if b is not None and k is not None and sel(b)]
        out[side] = (len(hits), (sum(hits) / len(hits)) if hits else None)
    return out


def check_not_mirrored(pred_bearings, net_bins, min_deg=MIRROR_MIN_DEG, need=MIRROR_PASS, min_n=MIRROR_MIN_N):
    """Raise MirroredLabelsError unless BOTH sides have >= min_n frames and each
    side agrees >= `need`. A one-sided data set is refused rather than passed:
    a mirror cannot be ruled out from one side alone when the labels might be
    systematically offset. Returns the side_agreement dict on success."""
    sa = side_agreement(pred_bearings, net_bins, min_deg)
    problems = []
    for side in ("left", "right"):
        n, f = sa[side]
        if n < min_n:
            problems.append(f"only {n} frames with the subject clearly on the {side} (need {min_n})")
        elif f < need:
            problems.append(f"{side}: network agrees on {f:.1%} of {n} frames (need {need:.0%})")
    if problems:
        lf, rf = sa["left"][1], sa["right"][1]
        flipped = lf is not None and rf is not None and lf <= 1 - need and rf <= 1 - need
        head = ("LABELS ARE MIRRORED: the poses say left where the network sees right on both sides. "
                "Check the yaw sign, the bearing sign and the room-frame handedness before using ANY label."
                if flipped else "LEFT/RIGHT CHECK DID NOT PASS")
        raise MirroredLabelsError(head + "; " + "; ".join(problems))
    return sa


# --------------------------------------------------------------------------
# CLI: one label from numbers typed at the bench
# --------------------------------------------------------------------------
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--follower", nargs="+", type=float, required=True, metavar="V",
                    help="x y z yaw_deg [roll_deg pitch_deg], Crazyflie log convention")
    ap.add_argument("--beacon", nargs=3, type=float, required=True, metavar=("X", "Y", "Z"),
                    help="head beacon position (room frame, m)")
    ap.add_argument("--height", type=float, default=1.75, help="subject's standing height, m")
    ap.add_argument("--beacon-above-head", type=float, default=0.0, help="beacon deck above top of head, m")
    ap.add_argument("--target-frac", type=float, default=0.5)
    ap.add_argument("--crop-hfov", type=float, default=70.0)
    ap.add_argument("--crop-vfov", type=float, default=None, help="default: same as --crop-hfov")
    ap.add_argument("--mount", nargs=3, type=float, default=(0.03, 0.0, 0.0), metavar=("X", "Y", "Z"))
    ap.add_argument("--tilt", type=float, default=0.0)
    a = ap.parse_args(argv)
    if len(a.follower) not in (4, 6):
        ap.error("--follower takes 4 (x y z yaw) or 6 (x y z yaw roll pitch) numbers")
    f = Pose(*a.follower)
    cam = CameraSpec(crop_hfov_deg=a.crop_hfov, crop_vfov_deg=a.crop_vfov or a.crop_hfov,
                     mount_xyz_body=tuple(a.mount), mount_tilt_deg=a.tilt)
    lab = pose_to_label(f, a.beacon, SubjectSpec(a.height, a.beacon_above_head, a.target_frac), cam)
    side = "LEFT" if lab.bearing_deg < 0 else "RIGHT" if lab.bearing_deg > 0 else "dead ahead"
    print(f"bearing   {lab.bearing_deg:+.2f} deg ({side}; negative = drone's left)")
    print(f"range     {lab.range_m:.3f} m (lens to target), depth {lab.depth_m:.3f} m")
    if lab.in_fov:
        print(f"image x   {lab.x_norm:+.4f}  (crop pixel {lab.px:.1f} of {cam.image_width_px})")
        edge = min(abs(lab.x_norm - e) for e in XBIN9_INNER)
        print(f"x-bin     {lab.x_bin}  (0 = left .. 8 = right; {edge:.3f} from the nearest bin edge)")
        print(f"size      {lab.size_frac:.4f} -> bucket {lab.size_bucket}"
              f"{'' if lab.fully_in_view else '  (body clipped by the crop)'}")
    else:
        print(f"NOT IN VIEW: {lab.why_not} - a network miss here is not a network error")


if __name__ == "__main__":
    main()
