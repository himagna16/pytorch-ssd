#!/usr/bin/env python3
"""Pieces shared by record_session.py (cfloaderenv), label_session.py and
render_timeline.py (trainenv). Standard library only, so it imports under any of
the project's venvs.

  * the spoken cue schedule for the clock-sync protocol (README "Clocks"),
  * the brightness gate (the 30-60 band grid_capture.sh enforces),
  * the session folder's file names and CSV columns,
  * rate / dropped-sample statistics from Crazyflie log timestamps,
  * the SCRIPTED subject used only by the --mock rehearsal.
"""
from __future__ import annotations

import csv
import math
import os
import re
from typing import Dict, List, Optional, Sequence

# --------------------------------------------------------------------------
# session folder layout
# --------------------------------------------------------------------------
POSES_CSV = {"follower": "poses_follower.csv", "beacon": "poses_beacon.csv"}
META_JSON = "meta.json"
FRAMES_DIR = "frames"
GRAB_LOG = "frames_grab.log"
POSE_COLS = ["x", "y", "z", "roll", "pitch", "yaw"]
POSE_VARS = {"x": "stateEstimate.x", "y": "stateEstimate.y", "z": "stateEstimate.z",
             "roll": "stabilizer.roll", "pitch": "stabilizer.pitch", "yaw": "stabilizer.yaw"}
# Status / quality variables, logged in a second, slower block, only if the drone's TOC
# has them (SITL has no lighthouse group at all). Order = preference when a block is full.
STATUS_WANTED = ["lighthouse.status", "lighthouse.bsActive", "lighthouse.bsReceive",
                 "lighthouse.bsCalVal", "lighthouse.bsGeoVal",
                 "kalman.varPX", "kalman.varPY", "kalman.varPZ",
                 "pm.vbat", "pm.state", "radio.rssi"]
LH_STATUS_WORKING = 2       # lighthouse.status: 2 = base-station data reaches the estimator


def status_col(var: str) -> str:
    """'lighthouse.bsActive' -> 'lighthouse_bsActive' (a CSV-friendly column name)."""
    return var.replace(".", "_")


def pose_csv_header(status_vars: Sequence[str]) -> List[str]:
    """t_cf_ms = the Crazyflie's own log timestamp (ms since its boot), t_laptop = unix time
    the packet reached this laptop. Status columns hold the latest status sample
    (sample-and-hold) and status_t_cf_ms says which sample that was."""
    return (["t_cf_ms", "t_laptop"] + POSE_COLS + [status_col(v) for v in status_vars]
            + ["status_t_cf_ms"])


def read_pose_csv(path) -> Dict[str, list]:
    """Column -> list of floats (NaN for blanks). Pure stdlib, so tests and both venvs can use it."""
    out: Dict[str, list] = {}
    with open(path, newline="") as f:
        r = csv.DictReader(f)
        for name in r.fieldnames or []:
            out[name] = []
        for row in r:
            for k, v in row.items():
                out[k].append(float(v) if v not in ("", None) else float("nan"))
    return out


FRAME_T_RE = re.compile(r"_t?(\d{9,}\.\d+)\.(?:png|jpg|jpeg)$")


def frame_time(name: str) -> Optional[float]:
    """Laptop arrival time from a cpx_grab filename: ..._t<unix>.png (labelled) or
    frame_<n>_<unix>.png (unlabelled)."""
    m = FRAME_T_RE.search(name)
    return float(m.group(1)) if m else None


def frame_number(name: str) -> Optional[int]:
    m = re.search(r"(?:^frame_|_f)(\d+)_", name)
    return int(m.group(1)) if m else None


def list_frames(frames_dir) -> List[tuple]:
    """[(time, number, filename)] sorted by arrival time; files without a time are skipped."""
    out = []
    if not os.path.isdir(frames_dir):
        return out
    for n in os.listdir(frames_dir):
        if n.startswith("._"):
            continue
        t = frame_time(n)
        if t is not None:
            out.append((t, frame_number(n), n))
    out.sort()
    return out


# --------------------------------------------------------------------------
# brightness gate (same band and override as tools/real_frames/grid_capture.sh)
# --------------------------------------------------------------------------
BLACK_BELOW = 15
BAND_LO, BAND_HI = 30, 60


def brightness_band(env=None):
    env = os.environ if env is None else env
    return int(env.get("GRID_MIN_BRIGHT", BAND_LO)), int(env.get("GRID_MAX_BRIGHT", BAND_HI))


def brightness_gate(mean: Optional[float], env=None) -> dict:
    """Verdict on the camera's mean brightness (0-255) before recording.

    Exposure is effectively random per power-up (EXPERIMENTS.md 2026-09-24 22:15), so,
    like grid_capture.sh, only record inside one band: 30-60 by default
    (GRID_MIN_BRIGHT / GRID_MAX_BRIGHT change it, GRID_ACCEPT_ANY=1 records anyway).
    A black camera (< 15) is refused even with GRID_ACCEPT_ANY: on 2026-09-24 such
    frames locked the follower on noise. Returns {ok, mean, band, why, override}."""
    env = os.environ if env is None else env
    lo, hi = brightness_band(env)
    accept_any = bool(env.get("GRID_ACCEPT_ANY"))
    if mean is None or (isinstance(mean, float) and math.isnan(mean)) or mean < 0:
        return dict(ok=False, mean=mean, band=[lo, hi], override=accept_any,
                    why="no frames for the brightness check (on the deck's WiFi? battery in for 30 s?)")
    if mean < BLACK_BELOW:
        return dict(ok=False, mean=mean, band=[lo, hi], override=accept_any,
                    why=f"the camera is BLACK (mean {mean:.0f} < {BLACK_BELOW}). Unplug and replug the "
                        "follower's battery, wait 30 s, rejoin the WiFi, run again")
    if lo <= mean <= hi:
        return dict(ok=True, mean=mean, band=[lo, hi], override=False, why="inside the band")
    why = (f"brightness {mean:.0f} is outside the target band {lo}-{hi}. Unplug and replug the "
           "follower's battery, wait 30 s, rejoin the WiFi, run again (usually 1-3 tries)")
    if accept_any:
        return dict(ok=True, mean=mean, band=[lo, hi], override=True,
                    why=why.split(".")[0] + "; recording anyway because GRID_ACCEPT_ANY is set")
    return dict(ok=False, mean=mean, band=[lo, hi], override=False, why=why + " (GRID_ACCEPT_ANY=1 records anyway)")


# --------------------------------------------------------------------------
# log rate statistics
# --------------------------------------------------------------------------
def rate_stats(t_cf_ms: Sequence[float], period_ms: float, t_laptop: Sequence[float] = None) -> dict:
    """What actually arrived, from the Crazyflie's own timestamps.

    achieved_hz  samples per second of Crazyflie time
    missing      samples the firmware should have sent in that span that never arrived
                 (each gap of k periods counts k-1) - the dropped-packet count
    max_gap_ms   the longest hole
    delivery     received / expected
    With laptop receive times, also the receive-latency jitter (p50/p95 of the delay
    above its minimum, a lower bound on how late a pose can reach the laptop)."""
    t = sorted(float(v) for v in t_cf_ms if v == v)
    n = len(t)
    out = dict(n=n, period_ms=period_ms, requested_hz=round(1000.0 / period_ms, 3))
    if n < 2:
        out.update(achieved_hz=None, missing=None, max_gap_ms=None, delivery=None, span_s=0.0)
        return out
    span = t[-1] - t[0]
    gaps = [b - a for a, b in zip(t, t[1:])]
    missing = sum(max(0, int(round(g / period_ms)) - 1) for g in gaps)
    expected = int(round(span / period_ms)) + 1
    out.update(span_s=round(span / 1000.0, 3), achieved_hz=round((n - 1) / (span / 1000.0), 3) if span > 0 else None,
               missing=missing, max_gap_ms=round(max(gaps), 1), delivery=round(n / expected, 4) if expected else None)
    if t_laptop is not None:
        pairs = [(tc / 1000.0, tl - tc / 1000.0) for tl, tc in zip(t_laptop, t_cf_ms) if tl == tl and tc == tc]
        if len(pairs) > 2:
            # remove the clocks' relative drift (straight line) before reading the jitter
            mx = sum(x for x, _ in pairs) / len(pairs)
            my = sum(y for _, y in pairs) / len(pairs)
            sxx = sum((x - mx) ** 2 for x, _ in pairs)
            slope = sum((x - mx) * (y - my) for x, y in pairs) / sxx if sxx > 0 else 0.0
            d = sorted(y - slope * (x - mx) for x, y in pairs)
        else:
            d = sorted(y for _, y in pairs)
        if d:
            base = d[0]
            q = lambda p: d[min(len(d) - 1, int(p * (len(d) - 1)))] - base   # noqa: E731
            out.update(rx_delay_above_min_ms_p50=round(q(0.5) * 1000, 2), rx_delay_above_min_ms_p95=round(q(0.95) * 1000, 2))
    return out


# Crazyflie log periods are sent in units of 10 ms; these are the rates worth trying, fastest first.
POSE_PERIODS_MS = [10, 20, 30, 40, 50, 100]


def pick_period(probe: Dict[int, Dict[str, float]], need: float = 0.95) -> Optional[int]:
    """Fastest period whose probe delivered >= `need` on EVERY link. probe = {period_ms: {role: delivery}}."""
    for p in sorted(probe):
        if probe[p] and all(v is not None and v >= need for v in probe[p].values()):
            return p
    return None


# --------------------------------------------------------------------------
# the spoken sync protocol
# --------------------------------------------------------------------------
STILL_S = 4.0       # still before the step: align_clocks.find_onsets needs >= 1.5 s
SETTLE_S = 3.0      # still after it
END_S = 10.0        # the end block: still, step, still, done
MIN_SECONDS = 2 * END_S


def cue_schedule(seconds: float) -> List[tuple]:
    """[(t, phrase, phase)], t in seconds after the recording clock starts (the first frame).

    START: still STILL_S, "Step", still SETTLE_S, then "Walk around".
    END:   at seconds-10 "Stand still", seconds-6 "Step", seconds-3 "Stand still", seconds "Done".
    The step is ONE quick sidestep (README "Clocks"); the stillness either side is what
    lets align_clocks find it in both streams."""
    if seconds < MIN_SECONDS:
        raise ValueError(f"--seconds must be at least {MIN_SECONDS:g} (start and end sync blocks)")
    s = [(0.0, "Stand still", "start_still"),
         (STILL_S, "Step", "start_step"),
         (STILL_S + 0.9, "Stand still", "start_settle")]
    free_at = STILL_S + SETTLE_S + 1.0
    end_at = seconds - END_S
    if end_at > free_at + 2.0:
        s.append((free_at, "Walk around", "free"))
    s += [(end_at, "Stand still", "end_still"),
          (end_at + 4.0, "Step", "end_step"),
          (end_at + 4.9, "Stand still", "end_settle"),
          (float(seconds), "Done", "done")]
    return s


def phase_times(schedule) -> Dict[str, float]:
    return {ph: t for t, _, ph in schedule}


# --------------------------------------------------------------------------
# the scripted subject (REHEARSAL ONLY: what a perfectly obedient subject would do)
# --------------------------------------------------------------------------
REACT_S = 0.4        # time from the cue to the subject starting to move
STEP_S = 0.35        # duration of one sidestep
STEP_M = 0.4         # sidestep length; + = toward the follower's LEFT
WALK_AMP_M = 1.0     # free phase: sideways sway around the step position
WALK_PERIOD_S = 7.0


def _ramp(t, t0, d, y0, y1):
    s = min(1.0, max(0.0, (t - t0) / d))
    return y0 + (y1 - y0) * (1 - math.cos(math.pi * s)) / 2


def scripted_lateral(t: float, seconds: float) -> float:
    """Sideways position (m, + = the follower's LEFT) of the scripted rehearsal subject
    at `t` seconds on the recording clock, obeying cue_schedule(seconds)."""
    ph = phase_times(cue_schedule(seconds))
    if t < ph["start_step"] + REACT_S:
        return 0.0
    y = _ramp(t, ph["start_step"] + REACT_S, STEP_S, 0.0, STEP_M)
    if "free" in ph:
        w0, w1 = ph["free"] + REACT_S, ph["end_still"] - 0.5
        if w0 < t < w1:
            u, L = t - w0, w1 - w0
            env = min(1.0, u / 2.0, (L - u) / 2.0)
            y = STEP_M + WALK_AMP_M * math.sin(2 * math.pi * u / WALK_PERIOD_S) * max(0.0, env)
    if t >= ph["end_step"] + REACT_S:
        y = _ramp(t, ph["end_step"] + REACT_S, STEP_S, STEP_M, 0.0)
    return y
