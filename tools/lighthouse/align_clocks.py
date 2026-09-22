#!/usr/bin/env python3
"""Line up the camera-frame clock with the pose-log clock (plan section 3.3c).

Why this exists. Frames come over WiFi from the AI-deck and are timestamped by
the laptop when cpx_grab.py receives them (the `_t<unix time>` in each
filename). Poses come over the Crazyradio and carry the Crazyflie's own log
timestamp (milliseconds since boot) or the laptop's receive time. Two
transports, two clocks, no shared timebase. If the two are off by `dt`
seconds, a subject walking sideways at `v` m/s at range `d` gets a label that
is off by about

    bearing error = atan(v * dt / d)                      (bearing_error_deg below)

which is ZERO when the subject stands still. So a clock error hides on the
static calibration marks and quietly corrupts every moving frame.

The sync event. The subject stands still for at least two seconds, then takes
one quick sidestep, and stands still again. Do this at the START and at the
END of every recording. The step is a sharp change in both streams: in the
beacon's position (pose log) and in where the person is in the image (frames).

What this module does
---------------------
1. `find_onsets` finds each "still, then moving" moment in a 1-D signal.
2. `event_offset` measures, around one such moment, the time shift that best
   lines the frame signal up with the pose signal (maximum correlation over
   a fine grid of shifts, refined to sub-sample). Both signals should be the
   SAME quantity - where the subject is in the image - so that neither has a
   built-in lag the other lacks: on the pose side that is `pose_to_label`'s
   x_norm (or just the beacon's sideways position when the follower sits
   still); on the frame side the network's x output, or any detection-free
   image measure of where the moving thing is.
3. `fit_clock` turns the start and end offsets into a straight line,
   t_pose = a * t_frame + b, so the offset AND the drift between the two
   clocks are measured rather than assumed. drift_ppm = (a - 1) * 1e6.
4. `to_pose_time` / `sample_poses_at_frames` use the line to fetch, for each
   frame, the pose at the same physical instant - refusing (NaN) to bridge a
   pose gap longer than `max_gap_s` instead of inventing a pose.

Tested in test_align_clocks.py against frames served by
tools/real_frames/mock_streamer.py and received by cpx_grab.py, with a
synthetic pose log injected at a known offset and drift.

Command line (two CSVs with columns t,value):

    align_clocks.py --frames frame_signal.csv --poses pose_signal.csv
"""
from __future__ import annotations

import argparse
import csv
import math
from dataclasses import dataclass
from typing import List, Optional, Sequence

import numpy as np


# --------------------------------------------------------------------------
# error model
# --------------------------------------------------------------------------
def bearing_error_deg(offset_s: float, lateral_speed_mps: float, range_m: float) -> float:
    """Bearing error from an uncorrected clock offset, subject moving across
    the line of sight at `lateral_speed_mps`, `range_m` away."""
    return math.degrees(math.atan2(abs(lateral_speed_mps * offset_s), range_m))


def xbin_error(offset_s: float, lateral_speed_mps: float, range_m: float, crop_hfov_deg: float = 70.0) -> float:
    """The same error in x-bin widths (9 bins over the crop), near the image centre."""
    dx = (lateral_speed_mps * abs(offset_s) / range_m) / math.tan(math.radians(crop_hfov_deg) / 2)
    return dx / (2.0 / 9.0)


def max_offset_for(bearing_err_deg: float, lateral_speed_mps: float, range_m: float) -> float:
    """Largest clock offset that keeps the bearing error under `bearing_err_deg`."""
    return range_m * math.tan(math.radians(bearing_err_deg)) / abs(lateral_speed_mps)


# --------------------------------------------------------------------------
# sync events
# --------------------------------------------------------------------------
def _finite(t, v):
    t, v = np.asarray(t, float), np.asarray(v, float)
    ok = np.isfinite(t) & np.isfinite(v)
    order = np.argsort(t[ok])
    return t[ok][order], v[ok][order]


def find_onsets(t: Sequence[float], v: Sequence[float], still_s: float = 1.5, step: float = None,
                noise_k: float = 6.0) -> List[float]:
    """Times where the signal leaves a still period of at least `still_s`.

    "Moving" means differing from the still period's median by more than
    `step` (default: noise_k x the robust noise of the first still period, and
    at least 5% of the signal's full range). Returned in time order; the sync
    protocol puts one near the start and one near the end."""
    t, v = _finite(t, v)
    if len(t) < 5:
        return []
    first = t < t[0] + still_s
    base = v[first]
    mad = float(np.median(np.abs(base - np.median(base)))) * 1.4826
    if step is None:
        step = max(noise_k * mad, 0.05 * float(np.ptp(v)), 1e-9)
    onsets, i, n = [], 0, len(t)
    while i < n:
        # grow a still window from i; its level is the median of its first 0.3 s
        m = max(1, int(np.searchsorted(t, t[i] + 0.3) - i))
        ref = float(np.median(v[i:i + m]))
        j = i
        while j + 1 < n and abs(v[j + 1] - ref) <= step:
            j += 1
        if t[j] - t[i] >= still_s and j + 1 < n:
            # onset = first sample past the step, interpolated back to the crossing
            k = j + 1
            a, b = v[k - 1] - ref, v[k] - ref
            thr = math.copysign(step, b)
            frac = (thr - a) / (b - a) if b != a else 0.0
            onsets.append(float(t[k - 1] + max(0.0, min(1.0, frac)) * (t[k] - t[k - 1])))
        i = j + 1
    return onsets


def _corr_at(frame_t, frame_v, pose_t, pose_v, lag):
    pv = np.interp(frame_t + lag, pose_t, pose_v, left=np.nan, right=np.nan)
    ok = np.isfinite(pv)
    if ok.sum() < 5:
        return -np.inf
    a, b = frame_v[ok] - frame_v[ok].mean(), pv[ok] - pv[ok].mean()
    den = math.sqrt(float((a * a).sum() * (b * b).sum()))
    return float((a * b).sum() / den) if den > 0 else -np.inf


@dataclass
class Event:
    t_frame: float        # frame-clock time the offset applies to (motion-weighted centre of the window)
    offset_s: float       # t_pose - t_frame at the event
    peak_corr: float      # correlation at the best shift (1.0 = identical shape)
    n_frames: int


def event_offset(frame_t, frame_v, pose_t, pose_v, t_frame_event: float, guess_offset: float,
                 before_s: float = 1.0, after_s: float = 2.0, search_s: float = 0.5,
                 step_s: float = 0.001) -> Event:
    """Shift that best aligns the frame signal to the pose signal around one event.

    Correlates the frames in [event - before_s, event + after_s] with the pose
    signal shifted by guess_offset +- search_s, on a `step_s` grid, then refines
    the peak with a parabola."""
    ft, fv = _finite(frame_t, frame_v)
    pt, pv = _finite(pose_t, pose_v)
    w = (ft >= t_frame_event - before_s) & (ft <= t_frame_event + after_s)
    ft, fv = ft[w], fv[w]
    lags = np.arange(guess_offset - search_s, guess_offset + search_s + step_s / 2, step_s)
    c = np.array([_corr_at(ft, fv, pt, pv, L) for L in lags])
    k = int(np.argmax(c))
    best = float(lags[k])
    if 0 < k < len(c) - 1 and np.all(np.isfinite(c[k - 1:k + 2])):
        y0, y1, y2 = c[k - 1], c[k], c[k + 1]
        den = y0 - 2 * y1 + y2
        if den < 0:
            best += 0.5 * (y0 - y2) / den * step_s
    # Under drift the offset changes across the window, and what was measured is its
    # value where the signal moves - so report it at the motion-weighted mean time.
    wgt = np.abs(np.gradient(fv, ft)) if len(ft) > 2 else np.ones_like(ft)
    t_at = float(np.sum(wgt * ft) / np.sum(wgt)) if np.sum(wgt) > 0 else float(t_frame_event)
    return Event(t_frame=t_at, offset_s=best, peak_corr=float(c[k]), n_frames=int(len(ft)))


@dataclass
class ClockFit:
    a: float              # t_pose = a * t_frame + b
    b: float
    events: list
    drift_measured: bool = True

    @property
    def drift_ppm(self) -> float:
        return (self.a - 1.0) * 1e6

    def offset_at(self, t_frame: float) -> float:
        return self.a * t_frame + self.b - t_frame

    def summary(self) -> str:
        ev = "; ".join(f"event at frame time {e.t_frame:.3f}: offset {e.offset_s:+.4f} s (corr {e.peak_corr:.3f}, "
                       f"{e.n_frames} frames)" for e in self.events)
        drift = (f"drift {self.drift_ppm:+.1f} ppm" if self.drift_measured else
                 "drift NOT measured (events too close together; offset-only fit)")
        return f"t_pose = {self.a:.9f} * t_frame {self.b:+.4f}  ({drift}) | {ev}"


MIN_DRIFT_SPAN_S = 60.0   # below this, jitter dominates any drift estimate


def fit_clock(events: Sequence[Event], min_drift_span_s: float = MIN_DRIFT_SPAN_S) -> ClockFit:
    """Offset and drift from two or more events (least squares). With one event,
    or events closer than `min_drift_span_s`, fit the offset only and say so."""
    if not events:
        raise ValueError("no sync events: record a still-then-sidestep at the start and the end")
    tf = np.array([e.t_frame for e in events])
    tp = tf + np.array([e.offset_s for e in events])
    if len(events) == 1 or np.ptp(tf) < min_drift_span_s:
        return ClockFit(1.0, float(np.mean(tp - tf)), list(events), drift_measured=False)
    ref = float(tf[0])                   # centre: unix-time abscissas are ~1.8e9
    a, c = np.polyfit(tf - ref, tp - ref, 1)
    return ClockFit(float(a), float(c + ref - a * ref), list(events))


MAX_PLAUSIBLE_DRIFT = 0.01    # 10,000 ppm; quartz clocks are ~10-100 ppm


def align(frame_t, frame_v, pose_t, pose_v, still_s: float = 1.5, min_corr: float = 0.9,
          context_s: float = 20.0, min_drift_span_s: float = MIN_DRIFT_SPAN_S, **kw) -> ClockFit:
    """Full routine: find the first and last sync events in each stream, pair
    them, measure each offset by correlation, fit offset + drift. Each offset is
    measured over the sync step plus up to `context_s` seconds of whatever motion
    follows the start event / precedes the end event (0 = the step alone).

    Raises ValueError (with the reason) rather than returning a fit it cannot
    stand behind: fewer than one onset in either stream, onsets that do not
    pair up, or a correlation peak below `min_corr`."""
    fo = find_onsets(frame_t, frame_v, still_s=still_s)
    po = find_onsets(pose_t, pose_v, still_s=still_s)
    if not fo or not po:
        raise ValueError(f"sync events not found (frames: {len(fo)}, poses: {len(po)} onsets). "
                         f"The subject must stand still >= {still_s} s, then sidestep.")
    pairs = [(fo[0], po[0])]
    if len(fo) > 1 and len(po) > 1:
        pairs.append((fo[-1], po[-1]))
    events = []
    for n, (f_on, p_on) in enumerate(pairs):
        # the start event also uses the motion AFTER it, the end event the motion BEFORE it:
        # a sidestep spans only a few frames, walking adds many more edges to align on
        win = dict(before_s=1.0, after_s=context_s) if n == 0 else dict(before_s=context_s, after_s=1.0)
        win.update(kw)
        ev = event_offset(frame_t, frame_v, pose_t, pose_v, f_on, p_on - f_on, **win)
        if ev.peak_corr < min_corr:
            raise ValueError(f"sync event at frame time {f_on:.2f}: best correlation {ev.peak_corr:.3f} < "
                             f"{min_corr}; the two streams do not show the same motion there")
        events.append(ev)
    if len(events) == 2:
        d_off = events[1].offset_s - events[0].offset_s
        span = events[1].t_frame - events[0].t_frame
        if span <= 0 or abs(d_off) / span > MAX_PLAUSIBLE_DRIFT:
            raise ValueError(f"start and end offsets differ by {d_off:+.3f} s over {span:.1f} s: more than "
                             f"any clock drift ({MAX_PLAUSIBLE_DRIFT * 1e6:.0f} ppm); the onsets are "
                             "probably paired wrongly")
    return fit_clock(events, min_drift_span_s)


def to_pose_time(fit: ClockFit, t_frame):
    return fit.a * np.asarray(t_frame, float) + fit.b


def sample_poses_at_frames(fit: ClockFit, frame_t, pose_t, pose_cols, max_gap_s: float = 0.1):
    """For each frame, each pose column linearly interpolated at the frame's
    instant on the pose clock. NaN where the nearest pose samples either side
    are more than `max_gap_s` apart (a dropout) or outside the log."""
    pose_t = np.asarray(pose_t, float)
    tq = to_pose_time(fit, frame_t)
    idx = np.searchsorted(pose_t, tq)
    ok = (idx > 0) & (idx < len(pose_t))
    gap = np.full(len(tq), np.inf)
    gap[ok] = pose_t[idx[ok]] - pose_t[idx[ok] - 1]
    ok &= gap <= max_gap_s
    out = []
    for col in pose_cols:
        v = np.interp(tq, pose_t, np.asarray(col, float))
        v[~ok] = np.nan
        out.append(v)
    return out


# --------------------------------------------------------------------------
def _read(path):
    t, v = [], []
    with open(path) as f:
        for r in csv.DictReader(f):
            t.append(float(r["t"]))
            v.append(float(r["value"]) if r["value"] not in ("", "nan") else float("nan"))
    return np.array(t), np.array(v)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Estimate frame-clock -> pose-clock offset and drift.")
    ap.add_argument("--frames", required=True, help="CSV t,value: frame timestamps and the subject's image x")
    ap.add_argument("--poses", required=True, help="CSV t,value: pose timestamps and the same quantity from poses")
    ap.add_argument("--still", type=float, default=1.5, help="seconds of stillness before each sync step")
    a = ap.parse_args(argv)
    fit = align(*_read(a.frames), *_read(a.poses), still_s=a.still)
    print(fit.summary())
    for v, d in ((0.5, 2.0), (1.0, 2.0), (1.5, 3.0)):
        off = abs(fit.offset_at(fit.events[0].t_frame))
        print(f"  uncorrected, a subject crossing at {v} m/s at {d} m would be off by "
              f"{bearing_error_deg(off, v, d):.2f} deg ({xbin_error(off, v, d):.2f} x-bins)")


if __name__ == "__main__":
    main()
