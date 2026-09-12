#!/usr/bin/env python3
"""Score simulator-v2 acceptance runs: metrics, thresholds, PASS / FAIL / INVALID.

Design: scratchpad/simv2/spec_metrics.md. This file is the implementation of
that spec's metric catalogue (sections 3-5), file formats (section 7) and
verdict rules (section 8). Nothing here changes an existing tool: it only reads
what follow_person.py, the patched simulator and build_scene.py already write.

    scoreboard.py <suite_dir>            score every run, write scoreboard.{json,md}
    scoreboard.py --check-run <run_dir>  validity only (exit 0 valid, 1 invalid)

A suite directory holds one subdirectory per flight, each containing the
follower's own output plus a cell.json written by run_acceptance2.sh:

    <suite>/runs/<cell_id>__r1a1/{cell.json, follow_log.csv, summary.json, ...}

cell.json says which matrix cell the flight belongs to (scene, scene class,
backend, camera preset, speed profile, repeat) and where its truth log is, so
scoring is completely offline and can be re-run after the fact.

WHAT IS MEASURED, in one paragraph for a reader who has not read the spec.
The drone is supposed to point at the person (M2, in degrees off the true
bearing), keep tracking latched (M1), hold station about 1.9 m away (M7 - that
number is derived in the spec from the camera's 70 deg field of view and the
model's four size buckets, and the buckets are coarse enough that anything from
1.62 to 2.43 m is a correct answer), never start following something that is
not a person (M8), get the person back quickly and legally after losing sight
of them (M9), rarely sit in the confidence band where the decision is decided
by hysteresis alone (M10), and steer smoothly rather than saw about the right
heading (M11). Thresholds and their justifications are in GATE_BASIS below;
every gate carries its basis into the JSON, because a threshold that cannot say
where it came from is a threshold someone will quietly "tidy up" later.
"""
import argparse
import csv
import json
import math
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent

SCHEMA = "crazysim-scoreboard/1"

# --- geometry and control constants (spec section 2, each read out of the code) ---
CROP_FOV_DEG = 70.0                   # square centre crop of a 244-tall render, fovy=70
TAN_HALF_FOV = math.tan(math.radians(CROP_FOV_DEG / 2))     # 0.70021
TARGET_SIZE = 0.625                   # follow_person.py --target-size, bucket-2 centre
SIZE_EDGES = (0.25, 0.5, 0.75)        # utils/follow_task.py SIZE_BUCKET4_EDGES
VIS_ENTER, VIS_EXIT = 0.70, 0.45      # follow_person.py --vis-enter / --vis-exit
CONFIRM_FRAMES = 3
STALE_HOVER_S, STALE_LAND_S = 0.5, 3.0
YAW_MAX_DEG = 40.0
SETTLE_S = 3.0                        # analyze_follow.py convention
MODEL_HALF_FOV_DEG = CROP_FOV_DEG / 2  # a subject outside +-35 deg is not in the model's crop

# d(s) = H / (2 s tan(phi/2)); hold where the decoded size equals the bucket-2 centre
HOLD_K = 1.0 / (2 * TARGET_SIZE * TAN_HALF_FOV)        # 1.1425
BAND_K = (1.0 / (2 * SIZE_EDGES[2] * TAN_HALF_FOV),    # 0.9521 (near edge, bucket 2/3 boundary)
          1.0 / (2 * SIZE_EDGES[1] * TAN_HALF_FOV))    # 1.4281 (far edge, bucket 1/2 boundary)

# --- thresholds (spec section 10). Every entry carries the reasoning. ----------
GATE_BASIS = {
    "V1_sim_wall_ratio": "analyze_follow.py's own rule, unchanged: the sim must keep up with wall time",
    "V1_rate": "analyze_follow.py: achieved processing rate >= 0.9x requested",
    "V1_serial": "analyze_follow.py: a serial chip never starts two frames closer than 1/R",
    "V2_torn": "new: a torn-frame storm means the camera transport failed, not the follower",
    "V2_truth": "new: the truth log must cover the whole follower window or M2/M7 are unscorable",
    "V2_takeoff": "new: the follower must have reached flight height, else nothing was tested",
    "M1": "verified baselines 98.7-99.7% tracked",
    "M2_mean_A": "verified static baseline 1.1 deg mean (3.6x margin)",
    "M2_mean_B": "verified moving baseline 2.7 deg mean (2.2x margin)",
    "M2_max_A": "verified maxima 7.7-7.9 deg (1.6x margin)",
    "M2_max_B": "verified maxima 7.7-7.9 deg (1.8x margin)",
    "M5": "existing scorecard rule: the drone must be on the floor after landing",
    "M6_C": "empty-room baseline: 0% tracked and no motion at all",
    "M6_F": "a distractor may capture the track, but it must not fly across the room",
    "M7_mean": "quantisation floor is +-0.40 m and the approach parks near the far edge (~0.49 m); "
               "0.75 m is ~1.5x that structural floor, and the verified 2.3 m static baseline scores 0.36 m",
    "M7_final": "the hold band is every distance the size head calls bucket 2, widened 10%",
    "M8_zero": "empty-room baseline: 0% tracked, peak confidence 0.64, never near the 0.70x3 rule",
    "M8_char": "30.2% (champion) vs 11.0% (confuser) per-frame false-alarm rate is the open question "
               "these cells exist to measure; a pass mark here would be invented",
    "M9_steer": "the safety rule itself: follow_person.py clears vis_state and streak on any stale hover, "
                "so steering may not resume before 3 fresh confirming frames",
    "M9_land": "landing is only allowed after 3.0 s without a fresh frame",
    "M9_reconfirm": "re-confirmation latency, NOT a reacquire time. first_good is defined as the start of the "
                    "3-frame confirming streak, so this quantity is structurally 2/R plus the wait for the "
                    "first nonzero command; it cannot report how long the drone was actually blind. Kept as a "
                    "regression trip-wire on the command path. The operational number is M9_gt_visible_to_relatch_s",
    "M9_gt_reacquire": "the spec's own M9 reacquire gate (1.0 s at full rate, 1.5 s at chip speed) applied to the "
                       "quantity section 4 actually describes: time from the target being continuously visible in "
                       "ground truth until the track re-latches. Not a new threshold, an existing one finally "
                       "pointed at the right measurement",
    "M9_gt_half": "the same measurement with 'visible' relaxed to half the target's width unobstructed. Half a "
                  "person behind a partition is a genuinely hard detection, so no verified baseline exists for "
                  "this reading and it stays report-only (spec section 5)",
    "M9_outage": "total time the track was lost. Reported for context only and never gated: it includes the "
                 "deliberate occlusion, so a long outage is the scene working, not the drone failing",
    "M9_hover_window": "verified baseline hovers at 0.5 s exactly; the window only extends upward by one control tick",
    "M9_land_window": "verified baseline lands at 3.0 s exactly",
    "M10_clean": "confidence is 0.96-1.0 on essentially every frame with a real person",
    "M10_himax": "degraded frames are expected to push more frames into the band; provisional",
    "M11_A": "a stationary target justifies zero legitimate reversals; 8/min allows one correction every 7 s",
    "M11_B": "the 20 s sway legitimately reverses the true bearing 6 times a minute; 24/min is 4x that",
    "M11_sat": "sustained saturation means rate-limited, not tracking - the signature that precedes oscillation",
    "CAM_RELAX": "no verified baseline exists for the degraded camera, so the relaxed threshold is provisional "
                 "(spec section 5: report-only until calibrated from this sweep)",
    "SPEED_RELAX": "verified chip-speed baselines are 3.1 deg mean and 98.7-99.2% tracked, so the relaxation "
                   "is slightly larger than the measured penalty",
}

# Plain-English scene names for the markdown table.
SCENE_PLAIN = {
    "s15_static_offset": "Person standing still",
    "s01_control_moving": "Person swaying side to side",
    "s02_control_empty": "Empty room",
    "s07_occlusion_reappear": "Person walks behind a partition",
    "s16_furniture_only": "Furniture and boxes, nobody home",
    "s03_pets_only": "A dog and a cat, no people",
    "s04_dummies_only": "Two teddy bears, no people",
    "s13_clutter_room": "Person among furniture",
    "s14_target_substitution": "Person leaves, a teddy stays",
}
SETUP_PLAIN = {
    ("chip", "himax_typical", "chip"): "ships-as",
    ("float", "clean", "full"): "proven",
}
CLASS_PLAIN = {
    "A": "person, standing still", "B": "person, moving", "C": "nobody present",
    "D": "person hidden then seen again", "E": "inanimate distractor", "F": "animate distractor",
}


# ---------------------------------------------------------------------------
# loading
# ---------------------------------------------------------------------------
def load_truth(path):
    """Read a simulator truth log in either format.

    v2 (CRAZYSIM_TRUTH_PREFIX set): '# bodies: a,b' then wall,sim,(x,y,z per body).
    legacy (prefix unset):          wall,sim,x,y for the body named 'person'.
    Returns (wall[], sim[], {body: (x[], y[])}) or None.
    """
    p = Path(path)
    if not p.exists():
        return None
    names, rows = None, []
    for line in p.read_text().splitlines():
        if line.startswith("#"):
            if "bodies:" in line:
                names = [s.strip() for s in line.split("bodies:", 1)[1].split(",") if s.strip()]
            continue
        parts = line.strip().split(",")
        if len(parts) < 4:
            continue                      # truncated final line: the sim was killed mid-write
        try:
            rows.append([float(v) for v in parts])
        except ValueError:
            continue
    if not rows:
        return None
    ncol = max(len(r) for r in rows)
    rows = [r for r in rows if len(r) == ncol]
    arr = np.asarray(rows, float)
    if names and ncol >= 2 + 3 * len(names):
        bodies = {n: (arr[:, 2 + 3 * i], arr[:, 3 + 3 * i]) for i, n in enumerate(names)}
    else:
        bodies = {"person": (arr[:, 2], arr[:, 3])}
    return arr[:, 0], arr[:, 1], bodies


def fnum(row, key):
    try:
        return float(row[key])
    except (KeyError, ValueError, TypeError):
        return float("nan")


def load_run(run_dir):
    run_dir = Path(run_dir)
    cell = json.loads((run_dir / "cell.json").read_text()) if (run_dir / "cell.json").exists() else {}
    summary = json.loads((run_dir / "summary.json").read_text()) if (run_dir / "summary.json").exists() else {}
    rows = []
    if (run_dir / "follow_log.csv").exists():
        with open(run_dir / "follow_log.csv") as f:
            rows = list(csv.DictReader(f))
    truth = load_truth(cell.get("truth", run_dir / "truth.csv")) if cell.get("truth") else None
    manifest = {}
    sd = cell.get("scene_dir")
    if sd and (Path(sd) / "manifest.json").exists():
        manifest = json.loads((Path(sd) / "manifest.json").read_text())
    return cell, summary, rows, truth, manifest


def target_subject(manifest):
    """The subject M2/M7 are scored against: the declared target, else the first person."""
    subs = manifest.get("subjects", [])
    want = (manifest.get("expected_behaviour") or {}).get("target")
    for s in subs:
        if s["name"] == want:
            return s
    for s in subs:
        if s.get("role") == "person_target":
            return s
    return None


# --- ground-truth visibility (what M9 actually needs) ------------------------
GT_VIS_SAMPLES = 21       # sight lines sampled across the target's width
GT_VIS_CLEAR = 0.9        # "visible": essentially the whole target is in the open
GT_VIS_HALF = 0.5         # "half visible": a genuinely hard detection, report-only


def _seg_hits_box(x0, y0, x1, y1, box):
    """Liang-Barsky: does the segment (x0,y0)-(x1,y1) touch this axis-aligned box?"""
    xmin, xmax, ymin, ymax = box
    dx, dy = x1 - x0, y1 - y0
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, x0 - xmin), (dx, xmax - x0), (-dy, y0 - ymin), (dy, ymax - y0)):
        if p == 0:
            if q < 0:
                return False
        else:
            r = q / p
            if p < 0:
                if r > t1:
                    return False
                if r > t0:
                    t0 = r
            else:
                if r < t0:
                    return False
                if r < t1:
                    t1 = r
    return t0 <= t1


def gt_visible_fraction(manifest, sub, px, py, tx, ty):
    """Fraction of the target's width with a clear line of sight, per frame.

    Occlusion in these scenes is an upright box standing between the drone and a
    flat subject panel, so this reduces to a 2-D problem: sample points across
    the panel's width and count the sight lines that miss every occluder.

    A single centre ray is not enough. It calls a person "visible" while nine
    tenths of them is behind the partition - precisely the frames where the
    model legitimately cannot see them - which is how a reacquire measurement
    ends up anchored on a frame where the target was not really back.

    Assumes the panel's width lies along y (every v2 scene builds it that way:
    `euler="0 0 0"`, half-extents 0.004 in x). Returns None when the scene
    declares no occluders, so the caller leaves the metric unscored instead of
    inventing a value.
    """
    occ = [o for o in (manifest.get("occluders") or []) if o.get("opaque", True)]
    if not occ or tx is None or sub is None:
        return None
    boxes = []
    for o in occ:
        c, h = o.get("center"), o.get("half_extents")
        if c and h:
            boxes.append((c[0] - h[0], c[0] + h[0], c[1] - h[1], c[1] + h[1]))
    if not boxes:
        return None
    half_w = float((sub.get("panel") or {}).get("width_m", 0.6)) / 2.0
    offs = np.linspace(-half_w, half_w, GT_VIS_SAMPLES)
    out = np.empty(len(px))
    for i in range(len(px)):
        clear = sum(1 for o in offs
                    if not any(_seg_hits_box(px[i], py[i], tx[i], ty[i] + o, b) for b in boxes))
        out[i] = clear / GT_VIS_SAMPLES
    return out


# ---------------------------------------------------------------------------
# validity (spec section 8 step 1)
# ---------------------------------------------------------------------------
def validity(cell, summary, rows, truth):
    flown = [r for r in rows if r.get("event", "") == ""]
    checks, reasons = {}, []
    swr = summary.get("sim_wall_ratio")
    checks["sim_wall_ratio"] = swr
    if swr is None or swr < 0.8:
        reasons.append(f"sim/wall {swr} < 0.8")
    req = float(cell.get("rate_hz", summary.get("rate_hz_requested") or 0.0) or 0.0)
    achieved, min_gap_ms = 0.0, None
    if len(flown) > 1:
        ts = np.array([fnum(r, "t_proc") if "t_proc" in r else fnum(r, "t") for r in flown])
        span = ts[-1] - ts[0]
        achieved = (len(ts) - 1) / span if span > 0 else 0.0
        gaps = np.diff(ts)
        min_gap_ms = float(gaps.min() * 1000.0) if len(gaps) else None
        if req and achieved < 0.9 * req:
            reasons.append(f"achieved {achieved:.2f} Hz < 0.9 x {req:g} Hz")
        if req and len(gaps) and gaps.min() < 0.95 / req:
            reasons.append(f"step gap {gaps.min()*1000:.0f} ms < 0.95/{req:g} Hz")
    else:
        reasons.append("fewer than 2 control steps")
    checks["achieved_hz"], checks["requested_hz"] = round(achieved, 3), req
    checks["min_step_gap_ms"] = None if min_gap_ms is None else round(min_gap_ms, 1)
    proc = summary.get("frames_processed") or len(flown)
    torn = summary.get("torn_frames") or 0
    checks["torn_fraction"] = round(torn / proc, 4) if proc else None
    if proc and torn / proc > 0.02:
        reasons.append(f"torn frames {torn}/{proc} > 2%")
    zmax = summary.get("z_max")
    checks["z_max"] = zmax
    if not cell.get("no_fly") and (zmax is None or zmax < 0.5):
        reasons.append(f"never reached flight height (z_max={zmax})")
    covers = None
    if truth is not None and flown:
        w = truth[0]
        covers = bool(w[0] <= fnum(flown[0], "wall") and w[-1] >= fnum(flown[-1], "wall"))
        if not covers:
            reasons.append("truth log does not cover the follower window")
    elif cell.get("needs_truth", True):
        # Two very different failures land here: the simulator never wrote a
        # truth log, or the follower never wrote a control log (so there is no
        # window to check the truth log against). Calling the second one a
        # missing truth log sends the next reader to the wrong file - the
        # watchdog-timeout attempt in this sweep has a 94 KB truth.csv and an
        # empty follower.log.
        reasons.append("no truth log" if truth is None else
                       "no follower control log, so the truth log covers nothing")
    checks["truth_covers_window"] = covers
    return (not reasons), checks, reasons


# ---------------------------------------------------------------------------
# metrics (spec section 4)
# ---------------------------------------------------------------------------
def metrics_for_run(cell, summary, rows, truth, manifest):
    m, notes = {}, []
    flown = [r for r in rows if r.get("event", "") == ""]
    if not flown:
        return {"error": "no flown rows"}, ["no flown rows"]
    t = np.array([fnum(r, "t") for r in flown])
    t0 = t[0]
    dt = np.diff(t, prepend=t[0])
    conf = np.array([fnum(r, "conf") for r in flown])
    trk = np.array([1 if fnum(r, "tracking") > 0.5 else 0 for r in flown])
    cmd_yaw = np.array([fnum(r, "cmd_yaw") for r in flown])
    cmd_vx = np.array([fnum(r, "cmd_vx") for r in flown])
    px = np.array([fnum(r, "px") for r in flown])
    py = np.array([fnum(r, "py") for r in flown])
    yaw = np.array([fnum(r, "yaw") for r in flown])
    size_bucket = np.array([fnum(r, "size_bucket") for r in flown])
    size_dec = np.array([fnum(r, "size") for r in flown])   # the decoded size value
    wall = np.array([fnum(r, "wall") for r in flown])
    settled = t - t0 > SETTLE_S

    # --- carried-forward metrics ------------------------------------------
    m["M1_tracking_fraction"] = summary.get("tracking_fraction")
    m["M3_centered_fraction_while_tracking"] = summary.get("centered_fraction_while_tracking")
    m["M4_stale_events"] = summary.get("stale_events", 0)
    m["M5_z_after_landing_m"] = summary.get("z_after_landing")
    m["end_reason"] = summary.get("end_reason")
    m["control_steps"] = len(flown)
    m["M6_max_horizontal_drift_m"] = round(
        float(max(math.hypot(a - px[0], b - py[0]) for a, b in zip(px, py))), 3)

    # --- the target's true track, interpolated onto the follower's clock ----
    sub = target_subject(manifest)
    tx = ty = None
    person_present_scene = sub is not None and sub.get("role") == "person_target"
    H = float((sub or {}).get("panel", {}).get("height_m", 1.7))
    m["person_height_m"] = H if person_present_scene else None
    if truth is not None and sub is not None:
        body = (sub.get("truth") or {}).get("body", sub["name"])
        bx, by = truth[2].get(body, list(truth[2].values())[0])
        tx = np.interp(wall, truth[0], bx)
        ty = np.interp(wall, truth[0], by)
    elif truth is not None:
        bx, by = list(truth[2].values())[0]
        tx, ty = np.interp(wall, truth[0], bx), np.interp(wall, truth[0], by)

    in_fov = np.zeros(len(flown), bool)
    if tx is not None:
        bearing = (np.degrees(np.arctan2(ty - py, tx - px)) - yaw + 180) % 360 - 180
        err = np.abs(bearing)
        d_true = np.hypot(tx - px, ty - py)
        in_fov = person_present_scene & (err <= MODEL_HALF_FOV_DEG)
        if person_present_scene and settled.any() and in_fov.any():
            s = err[settled]
            m["M2_heading_err_mean_deg"] = round(float(np.mean(s)), 2)
            m["M2_heading_err_p90_deg"] = round(float(np.percentile(s, 90)), 2)
            m["M2_heading_err_max_deg"] = round(float(np.max(s)), 2)
        elif person_present_scene:
            # e.g. the empty-room control, whose person stands behind the drone so the
            # camera never sees them. The bearing to that person is a real number
            # (about 180 deg) and a meaningless one: reporting it invites someone to
            # quote a "180 degree pointing error" as a failure. Say why instead.
            m["M2_not_applicable"] = ("the scene's person is never inside the camera's "
                                      "field of view, so there is no bearing to score")
        m["dist_start_m"] = round(float(d_true[0]), 2)
        m["dist_end_m"] = round(float(d_true[-1]), 2)

        # --- M7 distance keeping ------------------------------------------
        if person_present_scene:
            d_hold, band = HOLD_K * H, (BAND_K[0] * H, BAND_K[1] * H)
            at_hold = np.where((size_bucket == 2) & trk.astype(bool))[0]
            reached = len(at_hold) > 0
            if reached:
                start = max(t[at_hold[0]], t0 + SETTLE_S)
            else:
                start = max(t[-1] - 10.0, t0)
            win = t >= start
            if win.sum() >= 2:
                e = np.abs(d_true[win] - d_hold)
                m["M7_dist_err_settled_mean_m"] = round(float(np.mean(e)), 3)
                m["M7_dist_err_settled_max_m"] = round(float(np.max(e)), 3)
                m["M7_in_band_fraction"] = round(float(np.mean(
                    (d_true[win] >= band[0]) & (d_true[win] <= band[1]))), 3)
                # How far the size head over-reads, on the SAME window the gate
                # above is scored on. Computed here so the published table is
                # regenerable from the run data instead of typed by hand.
                geom = H / (2.0 * d_true[win] * TAN_HALF_FOV)
                m["M7_size_window_dist_mean_m"] = round(float(np.mean(d_true[win])), 3)
                m["M7_size_geom_mean"] = round(float(np.mean(geom)), 3)
                m["M7_size_decoded_mean"] = round(float(np.mean(size_dec[win])), 3)
                m["M7_size_overread_ratio"] = round(
                    float(np.mean(size_dec[win]) / np.mean(geom)), 3)
            m["M7_dist_final_m"] = round(float(d_true[-1]), 3)
            m["M7_reached_hold"] = bool(reached)
            m["M7_d_hold_target_m"] = round(d_hold, 3)
            m["M7_band_m"] = [round(band[0], 3), round(band[1], 3)]
            wide = (band[0] * 0.9, band[1] * 1.1)
            m["M7_band_wide_m"] = [round(wide[0], 3), round(wide[1], 3)]
            m["M7_final_in_band"] = bool(wide[0] <= d_true[-1] <= wide[1])
    m["person_in_view_fraction"] = round(float(np.mean(in_fov)), 3)

    # --- M8 false follow (any confirmation while no person is in view) ------
    starts = [i for i in range(1, len(trk)) if trk[i] and not trk[i - 1]]
    if trk[0]:
        starts.insert(0, 0)
    episodes = []
    for i in starts:
        j = i
        while j + 1 < len(trk) and trk[j + 1]:
            j += 1
        episodes.append((i, j))
    false_eps = [(i, j) for i, j in episodes if not in_fov[i:j + 1].any()]
    m["M8_false_follow_episodes"] = len(false_eps)
    flown_min = max((t[-1] - t0) / 60.0, 1e-9)
    m["flown_s"] = round(float(t[-1] - t0), 1)
    m["M8_false_follow_per_min"] = round(len(false_eps) / flown_min, 2)
    if false_eps:
        i0 = false_eps[0][0]
        m["M8_t_first_false_follow_s"] = round(float(t[i0] - t0), 2)
        m["M8_censored"] = False
        m["M8_false_follow_total_s"] = round(float(sum(t[j] - t[i] for i, j in false_eps)), 2)
        m["M8_max_drift_during_episode_m"] = round(float(max(
            max(math.hypot(px[k] - px[i], py[k] - py[i]) for k in range(i, j + 1))
            for i, j in false_eps)), 3)
        m["M8_conf_at_first_false_follow"] = round(float(conf[i0]), 3)
    else:
        m["M8_t_first_false_follow_s"] = None
        m["M8_censored"] = True          # never happened: a censored observation, not a zero
        m["M8_false_follow_total_s"] = 0.0
        m["M8_max_drift_during_episode_m"] = 0.0
    m["M8_tracked_episodes_total"] = len(episodes)

    # --- M9 loss / reacquire / re-confirmation ------------------------------
    # Two kinds of loss are scored the same way: the camera froze (stale-hover
    # rows), and the person went out of sight while frames kept arriving
    # (tracking dropped with the person still in the scene).
    stale_rows = [r for r in rows if r.get("event") == "stale-hover"]
    m["M9_stale_hover_rows"] = len(stale_rows)
    losses, i = [], 1
    while i < len(trk):
        if trk[i - 1] and not trk[i]:
            j = i
            while j + 1 < len(trk) and not trk[j + 1]:
                j += 1
            losses.append((i, j))
            i = j + 1
        i += 1
    # Commands are scored at the time they were APPLIED, not computed: with
    # --latency-ms the follower holds a FIFO, so a command computed before the
    # person disappeared can reach the motors after. Scoring the computed value
    # would make this gate tautological (the follower writes 0 whenever tracking
    # is off), and scoring every applied command would fail a correct controller
    # for a command that was already in flight when sight was lost. The rule the
    # spec states is the one scored here: nothing may steer between the person
    # being visible again and the 3rd confirming frame. The in-flight tail is
    # reported separately as M9_late_command_after_loss_ms.
    applied = np.array([fnum(r, "applied_t") for r in flown])
    applied = np.where(np.isnan(applied), t, applied)
    nonzero_cmd = (np.abs(cmd_yaw) > 1e-9) | (np.abs(cmd_vx) > 1e-9)
    vis_frac = gt_visible_fraction(manifest, sub, px, py, tx, ty)

    def visible_suffix_latency(i, k, thr):
        """Time from the target last becoming continuously visible, to relatch.

        Anchoring on the FIRST visible frame of the outage does not work in
        these scenes: the person is still in the open when the track drops and
        only then walks behind the partition, so that anchor is the loss itself
        and the metric just re-reports the outage. The quantity that means "the
        drone was blind with no excuse" is the suffix - the earliest frame after
        which the target stayed visible right up to the moment tracking
        returned.
        """
        q = k
        while q > i and vis_frac[q - 1] >= thr:
            q -= 1
        return float(t[k] - t[q])

    reconfirm, confirm_used, steered_before, late_ms = [], [], False, []
    gt_lat, gt_half_lat, outages = [], [], []
    for i, j in losses:
        if j + 1 >= len(trk):
            continue                      # never recovered before the flight ended
        k = j + 1                         # first frame with tracking latched again
        # the confirming streak that produced it started 'streak' frames earlier
        st = int(fnum(flown[k], "streak")) if not math.isnan(fnum(flown[k], "streak")) else CONFIRM_FRAMES
        first_good = max(i, k - max(st, 1) + 1)
        # the first actually-nonzero steering command after recovery
        nz = [q for q in range(k, len(trk)) if nonzero_cmd[q]]
        if nz:
            reconfirm.append(float(t[nz[0]] - t[first_good]))
        confirm_used.append(int(k - first_good + 1))
        outages.append(float(t[k] - t[i]))
        if vis_frac is not None:
            gt_lat.append(visible_suffix_latency(i, k, GT_VIS_CLEAR))
            gt_half_lat.append(visible_suffix_latency(i, k, GT_VIS_HALF))
        lo, hi = t[first_good], t[k]
        if np.any(nonzero_cmd & (applied >= lo) & (applied < hi)):
            steered_before = True
        tail = applied[nonzero_cmd & (applied >= t[i]) & (applied < lo)]
        if len(tail):
            late_ms.append(float((tail.max() - t[i]) * 1000.0))
    m["M9_loss_episodes"] = len(losses)
    # Renamed from M9_reacquire_s, which it never measured. first_good is the
    # start of the 3-frame confirming streak, so this is 2/R plus the wait for
    # the first nonzero command - a property of the streak definition, not of
    # how long the drone took to find the person again.
    m["M9_reconfirm_latency_s"] = round(max(reconfirm), 3) if reconfirm else None
    m["M9_reconfirm_latency_all_s"] = [round(v, 3) for v in reconfirm]
    # The operational numbers: how long the drone stayed unlatched after the
    # target was genuinely back in view, and how long the track was lost at all.
    m["M9_gt_visible_to_relatch_s"] = round(max(gt_lat), 3) if gt_lat else None
    m["M9_gt_visible_to_relatch_all_s"] = [round(v, 3) for v in gt_lat]
    m["M9_gt_halfvisible_to_relatch_s"] = round(max(gt_half_lat), 3) if gt_half_lat else None
    m["M9_gt_halfvisible_to_relatch_all_s"] = [round(v, 3) for v in gt_half_lat]
    m["M9_track_outage_s"] = round(max(outages), 3) if outages else None
    m["M9_track_outage_all_s"] = [round(v, 3) for v in outages]
    if vis_frac is not None:
        m["M9_gt_visible_fraction_of_flight"] = round(float(np.mean(vis_frac >= GT_VIS_CLEAR)), 3)
    m["M9_late_command_after_loss_ms"] = round(max(late_ms), 1) if late_ms else None
    m["M9_confirming_frames_used"] = max(confirm_used) if confirm_used else None
    m["M9_steered_before_reconfirm"] = bool(steered_before)
    m["M9_unrecovered_loss"] = bool(losses and losses[-1][1] + 1 >= len(trk))
    # Motion commanded while no target was confirmed: the same rule, in metres.
    m["M9_motion_while_unconfirmed_m"] = round(
        float(np.sum(np.abs(cmd_vx[trk == 0]) * dt[trk == 0])), 4)

    # freeze timing, when the run used the camera-freeze test hook
    if stale_rows:
        ts = np.array([fnum(r, "t") for r in stale_rows])
        last_good = t[t < ts[0]]
        if len(last_good):
            m["M9_hover_after_last_good_s"] = round(float(ts[0] - last_good[-1]), 3)
            if summary.get("end_reason") == "stale-land":
                m["M9_land_after_last_good_s"] = round(
                    float(fnum(rows[-1], "t") - last_good[-1]), 3) if rows else None
    m["M9_landed_unexpectedly"] = bool(summary.get("end_reason") == "stale-land"
                                       and not cell.get("freeze_expected"))

    # --- M10 uncertain band -------------------------------------------------
    band_mask = (conf >= VIS_EXIT) & (conf < VIS_ENTER)
    if in_fov.any():
        m["M10_uncertain_fraction_present"] = round(float(np.mean(band_mask[in_fov])), 4)
        m["M10_conf_p05_present"] = round(float(np.percentile(conf[in_fov], 5)), 3)
        m["M10_conf_mean_present"] = round(float(np.mean(conf[in_fov])), 3)
    if (~in_fov).any():
        m["M10_uncertain_fraction_absent"] = round(float(np.mean(band_mask[~in_fov])), 4)
        m["M10_conf_max_absent"] = round(float(np.max(conf[~in_fov])), 3)
    m["M10_uncertain_fraction_all"] = round(float(np.mean(band_mask)), 4)

    # --- M11 command smoothness --------------------------------------------
    def reversals(v):
        nz = v[np.abs(v) > 1e-9]
        return int(np.sum(np.sign(nz[1:]) != np.sign(nz[:-1]))) if len(nz) > 1 else 0
    m["M11_yaw_reversals_per_min"] = round(reversals(cmd_yaw) / flown_min, 2)
    m["M11_vx_reversals_per_min"] = round(reversals(cmd_vx) / flown_min, 2)
    steer = cmd_yaw[trk == 1]
    m["M11_yaw_saturated_fraction"] = round(float(np.mean(np.abs(steer) >= YAW_MAX_DEG - 1e-6)), 4) \
        if len(steer) else 0.0
    m["M11_cmd_yaw_abs_mean"] = round(float(np.mean(np.abs(steer))), 3) if len(steer) else 0.0

    # --- context ------------------------------------------------------------
    m["backend"] = summary.get("backend")
    m["loop_hz"] = summary.get("processed_hz")
    m["frames_dropped"] = summary.get("frames_dropped")
    if "round_trip_ms" in (flown[0] or {}):
        rt = np.array([fnum(r, "round_trip_ms") for r in flown])
        rt = rt[~np.isnan(rt)]
        if len(rt):
            m["chip_round_trip_ms_median"] = round(float(np.median(rt)), 2)
    return m, notes


# ---------------------------------------------------------------------------
# gates (spec section 5)
# ---------------------------------------------------------------------------
def cmp_op(v, op, thr):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    return {"<=": v <= thr, ">=": v >= thr, "<": v < thr, ">": v > thr,
            "==": v == thr, "!=": v != thr}[op]


def gate(gid, kind, value, op, thr, basis, scored_on="run"):
    res = cmp_op(value, op, thr)
    if kind in ("provisional", "report", "characterised"):
        result = "REPORT_ONLY"
    elif res is None:
        result = "NO_DATA"
    else:
        result = "PASS" if res else "FAIL"
    return {"id": gid, "kind": kind, "scored_on": scored_on, "value": value, "op": op,
            "threshold": thr, "result": result, "basis": basis,
            "would_pass": res}


def build_gates(cell, m):
    """The gate list for one cell, with the per-speed and per-camera adjustments."""
    cls = cell["scene_class"]
    chip_speed = cell.get("speed") == "chip"
    himax = cell.get("camera") == "himax_typical"
    g = []
    # every class: the drone must end up on the floor
    g.append(gate("M5_z_after_landing_m", "hard", m.get("M5_z_after_landing_m"), "<=", 0.10,
                  GATE_BASIS["M5"]))

    if cls in ("A", "B"):
        m1_thr = 0.95 - (0.02 if chip_speed else 0.0)
        m2_mean = (4.0 if cls == "A" else 6.0) + (2.0 if chip_speed else 0.0)
        m2_max = 12.0 if cls == "A" else 14.0
        speed_note = "; " + GATE_BASIS["SPEED_RELAX"] if chip_speed else ""
        if himax:
            # relaxed thresholds for the degraded camera have no measured baseline yet
            g.append(gate("M1_tracking_fraction", "provisional", m.get("M1_tracking_fraction"),
                          ">=", 0.90, GATE_BASIS["M1"] + "; " + GATE_BASIS["CAM_RELAX"]))
            g.append(gate("M2_heading_err_mean_deg", "provisional", m.get("M2_heading_err_mean_deg"),
                          "<=", m2_mean + 2.0,
                          GATE_BASIS["M2_mean_" + cls] + speed_note + "; " + GATE_BASIS["CAM_RELAX"]))
            g.append(gate("M10_uncertain_fraction_present", "provisional",
                          m.get("M10_uncertain_fraction_present"), "<=", 0.15,
                          GATE_BASIS["M10_himax"]))
        else:
            g.append(gate("M1_tracking_fraction", "gated", m.get("M1_tracking_fraction"),
                          ">=", m1_thr, GATE_BASIS["M1"] + speed_note, "median"))
            g.append(gate("M2_heading_err_mean_deg", "gated", m.get("M2_heading_err_mean_deg"),
                          "<=", m2_mean, GATE_BASIS["M2_mean_" + cls] + speed_note, "median"))
            g.append(gate("M10_uncertain_fraction_present", "gated",
                          m.get("M10_uncertain_fraction_present"), "<=", 0.05,
                          GATE_BASIS["M10_clean"], "median"))
        g.append(gate("M2_heading_err_max_deg", "gated", m.get("M2_heading_err_max_deg"),
                      "<=", m2_max, GATE_BASIS["M2_max_" + cls], "median"))
        g.append(gate("M7_dist_err_settled_mean_m", "gated", m.get("M7_dist_err_settled_mean_m"),
                      "<=", 0.75, GATE_BASIS["M7_mean"], "median"))
        g.append(gate("M7_final_in_band", "gated", 1.0 if m.get("M7_final_in_band") else 0.0,
                      "==", 1.0, GATE_BASIS["M7_final"] + f" (band {m.get('M7_band_wide_m')} m)", "median"))
        g.append(gate("M9_steered_before_reconfirm", "hard",
                      1.0 if m.get("M9_steered_before_reconfirm") else 0.0, "==", 0.0,
                      GATE_BASIS["M9_steer"]))
        g.append(gate("M11_yaw_reversals_per_min", "provisional", m.get("M11_yaw_reversals_per_min"),
                      "<=", 8.0 if cls == "A" else 24.0, GATE_BASIS["M11_" + cls]))
        g.append(gate("M11_yaw_saturated_fraction", "provisional", m.get("M11_yaw_saturated_fraction"),
                      "<=", 0.25, GATE_BASIS["M11_sat"]))
        g.append(gate("M3_centered_fraction_while_tracking", "report",
                      m.get("M3_centered_fraction_while_tracking"), ">=", 0.0, "reported, not gated"))

    elif cls in ("C", "E"):
        g.append(gate("M8_false_follow_episodes", "hard", m.get("M8_false_follow_episodes"),
                      "==", 0, GATE_BASIS["M8_zero"]))
        g.append(gate("M1_tracking_fraction", "hard", m.get("M1_tracking_fraction"), "==", 0.0,
                      GATE_BASIS["M8_zero"]))
        g.append(gate("M6_max_horizontal_drift_m", "hard", m.get("M6_max_horizontal_drift_m"),
                      "<", 0.10, GATE_BASIS["M6_C"]))
        g.append(gate("M10_conf_max_absent", "report", m.get("M10_conf_max_absent"), "<=", VIS_ENTER,
                      "reported: sitting in the band is tolerable, latching out of it is not"))

    elif cls == "D":
        g.append(gate("M9_steered_before_reconfirm", "hard",
                      1.0 if m.get("M9_steered_before_reconfirm") else 0.0, "==", 0.0,
                      GATE_BASIS["M9_steer"]))
        g.append(gate("M9_landed_unexpectedly", "hard",
                      1.0 if m.get("M9_landed_unexpectedly") else 0.0, "==", 0.0, GATE_BASIS["M9_land"]))
        # The gate that matters: how long the drone stayed unlatched after the
        # target was genuinely visible again. The threshold is the spec's own
        # M9 reacquire number, finally applied to the quantity it describes.
        g.append(gate("M9_gt_visible_to_relatch_s", "gated", m.get("M9_gt_visible_to_relatch_s"),
                      "<=", 1.5 if chip_speed else 1.0, GATE_BASIS["M9_gt_reacquire"], "median"))
        g.append(gate("M9_gt_halfvisible_to_relatch_s", "provisional",
                      m.get("M9_gt_halfvisible_to_relatch_s"), "<=",
                      1.5 if chip_speed else 1.0, GATE_BASIS["M9_gt_half"]))
        g.append(gate("M9_reconfirm_latency_s", "report", m.get("M9_reconfirm_latency_s"), "<=",
                      1.5 if chip_speed else 1.0, GATE_BASIS["M9_reconfirm"], "median"))
        g.append(gate("M9_track_outage_s", "report", m.get("M9_track_outage_s"), ">=", 0.0,
                      GATE_BASIS["M9_outage"]))
        g.append(gate("M9_confirming_frames_used", "report", m.get("M9_confirming_frames_used"),
                      ">=", CONFIRM_FRAMES, "the re-confirmation rule needs 3 fresh frames"))
        g.append(gate("M1_tracking_fraction", "report", m.get("M1_tracking_fraction"), ">=", 0.0,
                      "reported: tracking includes the deliberate occlusion"))
        g.append(gate("M2_heading_err_mean_deg", "report", m.get("M2_heading_err_mean_deg"),
                      "<=", 0.0, "reported: includes frames where the person was hidden"))

    elif cls == "F":
        g.append(gate("M6_max_horizontal_drift_m", "hard", m.get("M6_max_horizontal_drift_m"),
                      "<", 0.5, GATE_BASIS["M6_F"]))
        for k in ("M8_false_follow_episodes", "M8_t_first_false_follow_s",
                  "M8_false_follow_total_s", "M8_max_drift_during_episode_m",
                  "M1_tracking_fraction", "M10_conf_max_absent"):
            g.append(gate(k, "characterised", m.get(k), ">=", 0.0, GATE_BASIS["M8_char"]))
    return g


def aggregate(runs, key):
    vals = [r["metrics"].get(key) for r in runs if isinstance(r["metrics"].get(key), (int, float))]
    if not vals:
        return None
    return {"median": round(float(statistics.median(vals)), 4), "min": min(vals),
            "max": max(vals), "n": len(vals), "values": vals}


def score_cell(cell_id, runs):
    """spec section 8: validity, then hard gates on the worst run, quality on the median."""
    valid = [r for r in runs if r["valid"]]
    c0 = runs[0]["cell"]
    out = {"cell_id": cell_id, "scene": c0["scene"], "scene_class": c0["scene_class"],
           "backend": c0["backend"], "camera": c0["camera"], "speed": c0["speed"],
           "runs": runs, "n_valid": len(valid), "n_flights": len(runs)}
    if len(valid) < 2:
        out["verdict"] = "INVALID"
        out["why"] = (f"only {len(valid)} valid flight(s) after re-flies; the spec needs 2. "
                      "An untested cell is not a passing cell.")
        # An INVALID cell still carries whatever was measured, so the report can
        # say what the one usable flight showed without pretending it is a result.
        out["gates"], out["failed_gates"] = [], []
        out["aggregate"] = {k: aggregate(valid, k) for k in
                            ("M1_tracking_fraction", "M2_heading_err_mean_deg",
                             "M2_heading_err_max_deg", "M7_dist_final_m",
                             "M8_false_follow_episodes", "M9_gt_visible_to_relatch_s",
                             "M9_reconfirm_latency_s", "M9_track_outage_s",
                             "M6_max_horizontal_drift_m")
                            if aggregate(valid, k)}
        return out

    # hard gates: any failing repeat fails the cell (safety is never averaged),
    # and the repeat reported is the numerically worst one, not the first failing
    # one: a printed safety number must not understate what was observed.
    def _worse(cand, cur):
        """Is cand a worse repeat than cur for this gate?"""
        if cur is None:
            return True
        if cur["would_pass"] != cand["would_pass"]:
            return cur["would_pass"]          # any failing repeat beats a passing one
        a, b = cand.get("value"), cur.get("value")
        if a is None or b is None or not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
            return False                      # nothing to compare: keep the first
        op = cur.get("op") or cand.get("op")
        if op in ("<=", "<"):                 # a ceiling: larger is worse
            return a > b
        if op in (">=", ">"):                 # a floor: smaller is worse
            return a < b
        return False

    worst, gates = {}, []
    for r in valid:
        for g in r["gates"]:
            if g["kind"] == "hard":
                cand = dict(g, scored_on="worst repeat")
                if _worse(cand, worst.get(g["id"])):
                    worst[g["id"]] = cand
    gates.extend(worst.values())

    # quality / provisional / characterised gates: scored on the median
    seen = set()
    for r in valid:
        for g in r["gates"]:
            if g["kind"] == "hard" or g["id"] in seen:
                continue
            seen.add(g["id"])
            agg = aggregate(valid, g["id"])
            med = agg["median"] if agg else None
            gg = gate(g["id"], g["kind"], med, g["op"], g["threshold"], g["basis"], "median")
            gg["spread"] = None if agg is None else [agg["min"], agg["max"]]
            gates.append(gg)
    out["gates"] = gates
    fails = [g for g in gates if g["result"] == "FAIL"]
    out["failed_gates"] = [g["id"] for g in fails]
    if fails:
        out["verdict"] = "FAIL"
    elif any(g["kind"] == "characterised" for g in gates):
        out["verdict"] = "CHARACTERISED"
    else:
        out["verdict"] = "PASS"
    out["aggregate"] = {k: aggregate(valid, k) for k in
                        ("M1_tracking_fraction", "M2_heading_err_mean_deg", "M2_heading_err_max_deg",
                         "M7_dist_err_settled_mean_m", "M7_dist_final_m", "M7_in_band_fraction",
                         "M8_false_follow_episodes", "M9_gt_visible_to_relatch_s",
                         "M9_gt_halfvisible_to_relatch_s", "M9_reconfirm_latency_s",
                         "M9_track_outage_s",
                         "M7_size_window_dist_mean_m", "M7_size_geom_mean",
                         "M7_size_decoded_mean", "M7_size_overread_ratio",
                         "M10_uncertain_fraction_present", "M10_conf_max_absent",
                         "M11_yaw_reversals_per_min", "M6_max_horizontal_drift_m")
                        if aggregate(valid, k)}
    return out


# ---------------------------------------------------------------------------
# plain-English verdict lines
# ---------------------------------------------------------------------------
def fmt_deg(agg):
    """Pointing error: the median mean, and the WORST single frame seen in any repeat.

    'worst' used to print the median of the per-flight maxima, which is not a
    worst case at all: with maxima [21.47, 17.92] it printed 19.7 and the 21.47
    that actually happened never appeared anywhere. A maximum is the one
    statistic there is never a reason to average, so take the max of the maxima.
    """
    a = agg.get("M2_heading_err_mean_deg")
    b = agg.get("M2_heading_err_max_deg")
    if not a:
        return "n/a"
    return f"{a['median']:.1f} deg avg" + (f" ({b['max']:.1f} worst)" if b else "")


def fmt_dist(cell):
    """Median hold distance, with the per-flight range beside it.

    A single median is what turns "2.81 to 3.78 m across two flights" into a
    confident-sounding "3.30 m", which is the number a hardware prediction then
    gets built on. The range travels with it.
    """
    a = cell["aggregate"].get("M7_dist_final_m")
    if not a:
        return "n/a"
    r = cell["runs"][0]["metrics"]
    tgt = r.get("M7_d_hold_target_m")
    s = f"{a['median']:.2f} m"
    if a["n"] > 1 and a["max"] - a["min"] > 0.005:
        s += f" ({a['min']:.2f}-{a['max']:.2f} over {a['n']})"
    return s + (f", target {tgt:.2f}" if tgt else "")


def plain_verdict(cell):
    cls, v = cell["scene_class"], cell["verdict"]
    agg = cell["aggregate"]
    m = cell["runs"][0]["metrics"]
    scene = SCENE_PLAIN.get(cell["scene"], cell["scene"])
    if v == "INVALID":
        return f"{scene}: not enough usable flights to say anything."
    if cls in ("A", "B"):
        base = (f"It pointed at the person within {fmt_deg(agg)} and held station at "
                f"{fmt_dist(cell)}.")
        if v == "FAIL":
            bad = ", ".join(cell["failed_gates"])
            return f"{scene}: FAILED on {bad}. " + base
        return f"{scene}: followed correctly. " + base
    if cls in ("C", "E"):
        eps = agg.get("M8_false_follow_episodes", {}).get("median", 0)
        drift = agg.get("M6_max_horizontal_drift_m", {}).get("median", 0)
        if v == "FAIL":
            return (f"{scene}: FAILED - it started following something that is not a person "
                    f"({eps:g} time(s)) and moved {drift:.2f} m.")
        return f"{scene}: correctly ignored everything; it never moved (drift {drift:.2f} m)."
    if cls == "D":
        ra = agg.get("M9_gt_visible_to_relatch_s")
        out = agg.get("M9_track_outage_s")
        steer = m.get("M9_steered_before_reconfirm")
        s = (f"{scene}: " +
             (f"it lost the track for up to {out['max']:.1f} s, and once the person was "
              f"properly back in view it took {ra['median']:.2f} s to start following again"
              if ra and out else
              "it never lost sight of the person, so there was nothing to reacquire"))
        s += ("; it correctly waited for 3 fresh frames before steering again."
              if not steer else "; IT STEERED BEFORE RE-CONFIRMING, which is the safety rule broken.")
        return s + (" FAILED." if cell["verdict"] == "FAIL" else "")
    if cls == "F":
        eps = agg.get("M8_false_follow_episodes", {}).get("median", 0)
        trk = agg.get("M1_tracking_fraction", {}).get("median", 0)
        drift = agg.get("M6_max_horizontal_drift_m", {}).get("median", 0)
        if eps:
            return (f"{scene}: it locked onto an animal/toy {eps:g} time(s), tracked it for "
                    f"{trk:.0%} of the flight and moved {drift:.2f} m. Measured, not graded - "
                    f"this is the number that decides champion vs confuser.")
        return f"{scene}: never locked on. Measured, not graded."
    return f"{scene}: {v}"


# ---------------------------------------------------------------------------
# markdown
# ---------------------------------------------------------------------------
def setup_name(cell):
    key = (cell["backend"], cell["camera"], cell["speed"])
    if key in SETUP_PLAIN:
        return SETUP_PLAIN[key]
    return f"{cell['backend']}/{cell['camera']}/{cell['speed']}"


def write_markdown(sb, path):
    counts = sb["counts"]
    L = []
    L.append(f"# Simulator scoreboard - {sb['suite']} suite - "
             f"{datetime.fromisoformat(sb['started_utc'].rstrip('Z')).strftime('%d %b %Y')}")
    L.append("")
    total = sum(counts.values())
    L.append(f"**Overall: {sb['verdict']}.** {counts['fail']} of {total} checks FAILED "
             f"({counts['pass']} passed, {counts['characterised']} measured-only, "
             f"{counts['invalid']} unusable).")
    fc = sb.get("flight_counts") or {}
    # Attempts flown and cells scored are different numbers, and reporting only
    # the second hides both the invalid attempts and any flight that was flown
    # but not scored. Say all of it.
    L.append(f"Flights: {fc.get('attempted', 0)} attempted, {fc.get('valid', 0)} valid, "
             f"{fc.get('invalid', 0)} invalid, {fc.get('scored', 0)} scored "
             f"({len(sb['cells'])} cells). Total time: {sb['duration_s']/60:.0f} min.")
    unscored = [a for c in sb["cells"] for a in c.get("attempts", [])
                if a.get("valid") and not a.get("scored")]
    if unscored:
        L.append("")
        L.append("Valid flights flown but not scored (superseded within their repeat): "
                 + ", ".join(f"`{a['run']}`" for a in unscored) + ".")
    L.append("")
    L.append("Two setups appear in the table. **ships-as** is what the real drone will be: the "
             "chip's own integer network, the realistic camera model, and the chip's 6.5 Hz speed. "
             "**proven** is the laptop model on a clean camera at full speed - the setup every "
             "September baseline was measured in, so it says whether a problem is new or just the "
             "cost of realism.")
    L.append("")

    fails = [c for c in sb["cells"] if c["verdict"] == "FAIL"]
    if fails:
        L.append("## What failed")
        L.append("")
        for c in fails:
            L.append(f"**{SCENE_PLAIN.get(c['scene'], c['scene'])} - {setup_name(c)}**  ")
            L.append(plain_verdict(c) + "  ")
            for g in c["gates"]:
                if g["result"] == "FAIL":
                    L.append(f"- `{g['id']}` = {g['value']}, needs {g['op']} {g['threshold']} "
                             f"({g['basis']})")
            L.append("")
    else:
        L.append("## What failed")
        L.append("")
        L.append("Nothing. Every gated check passed.")
        L.append("")

    L.append("## All checks")
    L.append("")
    L.append("| Scene | What it tests | Setup | Tracked | Pointing error | Distance held | "
             "False follows | Verdict |")
    L.append("|---|---|---|---|---|---|---|---|")
    for c in sb["cells"]:
        agg = c["aggregate"]
        trk = agg.get("M1_tracking_fraction")
        eps = agg.get("M8_false_follow_episodes")
        dist = fmt_dist(c) if c["scene_class"] in ("A", "B") else "n/a"
        point = fmt_deg(agg) if c["scene_class"] in ("A", "B", "D") else "n/a"
        verdict = {"PASS": "PASS", "FAIL": "**FAIL**", "CHARACTERISED": "measured only",
                   "INVALID": "**unusable**"}[c["verdict"]]
        trk_txt = f"{trk['median']:.1%}" if trk else "n/a"
        eps_txt = ("%g" % eps["median"]) if eps else "n/a"
        L.append(f"| {SCENE_PLAIN.get(c['scene'], c['scene'])} "
                 f"| {CLASS_PLAIN[c['scene_class']]} "
                 f"| {setup_name(c)} "
                 f"| {trk_txt} | {point} | {dist} | {eps_txt} | {verdict} |")
    L.append("")

    L.append("## What each scene means, in one line")
    L.append("")
    for c in sb["cells"]:
        L.append(f"- _{setup_name(c)}_ - {plain_verdict(c)}")
    L.append("")

    meas = [c for c in sb["cells"] if c["verdict"] == "CHARACTERISED"]
    L.append("## Measured-only checks")
    L.append("")
    L.append("These have no pass mark yet, on purpose - we are collecting the first numbers.")
    L.append("")
    L.append("- Dog / teddy false-follow rate (decides champion vs confuser model)")
    L.append("- Steering smoothness (pass mark set from this sweep - spec section 4, M11)")
    L.append("- Every threshold on the realistic camera (no verified baseline yet - spec section 5)")
    if meas:
        L.append("")
        for c in meas:
            L.append(f"  - {SCENE_PLAIN.get(c['scene'], c['scene'])} ({setup_name(c)}): "
                     + plain_verdict(c))
    L.append("")

    L.append("## Provisional numbers observed in this sweep (for calibrating v2.1)")
    L.append("")
    L.append("| metric | scene class | median | min | max | provisional threshold |")
    L.append("|---|---|---|---|---|---|")
    for c in sb["cells"]:
        for g in c["gates"]:
            if g["kind"] == "provisional" and g["value"] is not None:
                sp = g.get("spread") or [g["value"], g["value"]]
                L.append(f"| {g['id']} | {c['scene_class']} ({setup_name(c)}) | {g['value']} "
                         f"| {sp[0]} | {sp[1]} | {g['op']} {g['threshold']} |")
    L.append("")
    L.append("---")
    L.append("")
    L.append(f"Distances: the drone aims to stop where the person fills the middle size bucket. "
             f"For a 1.7 m person that is {HOLD_K*1.7:.2f} m, and anything from "
             f"{BAND_K[0]*1.7:.2f} to {BAND_K[1]*1.7:.2f} m is the same bucket, so it is all "
             f"equally correct. Pointing error is the angle between where the drone is facing and "
             f"where the person actually is, from the simulator's own ground truth.")
    Path(path).write_text("\n".join(L) + "\n")


# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("suite_dir", nargs="?", type=Path)
    ap.add_argument("--check-run", type=Path, help="print validity for one run dir and exit")
    ap.add_argument("--suite", default=None, help="suite label for the report")
    a = ap.parse_args()

    if a.check_run:
        cell, summary, rows, truth, manifest = load_run(a.check_run)
        ok, checks, reasons = validity(cell, summary, rows, truth)
        print(("VALID   " if ok else "INVALID ") + json.dumps(checks))
        if reasons:
            print("reasons: " + "; ".join(reasons))
        sys.exit(0 if ok else 1)

    if not a.suite_dir:
        ap.error("suite_dir is required unless --check-run is given")
    suite = Path(a.suite_dir)
    run_dirs = sorted(p.parent for p in suite.glob("runs/*/cell.json"))
    if not run_dirs:
        raise SystemExit(f"no runs with cell.json under {suite}/runs/")

    cells, reused = {}, []
    for rd in run_dirs:
        cell, summary, rows, truth, manifest = load_run(rd)
        # A published evidence folder keeps every flight's metrics.json but only a
        # representative flight's follow_log.csv, to stay a few MB instead of tens
        # (docs/sim_results/.../README.md). Re-deriving a trimmed flight from a log
        # that is not there would rewrite a good record as "fewer than 2 control
        # steps" and drop its cell to INVALID - scoring the evidence would destroy
        # it. So a flight that measured something and kept no log is scored from
        # what it stored, and its file is left alone. A flight that genuinely
        # failed (no log AND nothing measured, like a watchdog timeout) still gets
        # scored as invalid, which is what its own record says anyway.
        stored = {}
        if not rows and (rd / "metrics.json").exists():
            try:
                stored = json.loads((rd / "metrics.json").read_text())
            except json.JSONDecodeError:
                stored = {}
        if stored.get("valid") and stored.get("metrics"):
            rec = dict(stored, run_dir=str(rd))
            reused.append(rd.name)
        else:
            ok, checks, reasons = validity(cell, summary, rows, truth)
            m, notes = ({}, []) if not rows else metrics_for_run(cell, summary, rows, truth, manifest)
            gates = build_gates(cell, m) if ok and m and "error" not in m else []
            rec = {"run_dir": str(rd), "cell": cell, "valid": bool(ok), "validity": checks,
                   "invalid_reasons": reasons, "metrics": m, "gates": gates,
                   "repeat": cell.get("repeat"), "attempt": cell.get("attempt")}
            (rd / "metrics.json").write_text(json.dumps(rec, indent=2, default=str))
        cells.setdefault(cell["cell_id"], []).append(rec)
    if reused:
        print(f"note: {len(reused)} flight(s) kept no follow_log.csv and were scored from their "
              f"stored metrics.json, which was left unchanged: {', '.join(sorted(reused))}")

    scored = []
    for cid, runs in cells.items():
        # a re-flown flight supersedes the invalid attempt it replaced, but every
        # attempt stays in the record so nothing is quietly dropped
        best = {}
        for r in runs:
            k = r["repeat"]
            if k not in best or (r["valid"] and not best[k]["valid"]) or \
               (r["valid"] == best[k]["valid"] and (r["attempt"] or 0) > (best[k]["attempt"] or 0)):
                best[k] = r
        sc = score_cell(cid, list(best.values()))
        # Attempts flown is not the same number as flights scored. Keep both, and
        # keep a per-attempt record, so an invalid attempt or a flight superseded
        # within its repeat can never quietly vanish from the ledger.
        kept = {id(r) for r in best.values()}
        sc["n_attempts"] = len(runs)
        sc["n_attempts_valid"] = sum(1 for r in runs if r["valid"])
        sc["n_attempts_invalid"] = sum(1 for r in runs if not r["valid"])
        sc["attempts"] = [{"run": Path(r["run_dir"]).name, "repeat": r["repeat"],
                           "attempt": r["attempt"], "valid": r["valid"],
                           "scored": id(r) in kept,
                           "invalid_reasons": r["invalid_reasons"]} for r in runs]
        scored.append(sc)
    order = {"A": 0, "B": 1, "C": 2, "D": 3, "E": 4, "F": 5}
    scored.sort(key=lambda c: (0 if setup_name(c) == "ships-as" else 1 if setup_name(c) == "proven" else 2,
                               order.get(c["scene_class"], 9)))

    flight_counts = {"attempted": sum(c["n_attempts"] for c in scored),
                     "valid": sum(c["n_attempts_valid"] for c in scored),
                     "invalid": sum(c["n_attempts_invalid"] for c in scored),
                     "scored": sum(len(c["runs"]) for c in scored)}

    counts = {"pass": 0, "fail": 0, "invalid": 0, "characterised": 0}
    for c in scored:
        counts[c["verdict"].lower()] += 1
    verdict = "INVALID" if counts["invalid"] else ("FAIL" if counts["fail"] else "PASS")

    meta = {}
    mp = suite / "suite_meta.json"
    if mp.exists():
        meta = json.loads(mp.read_text())
    sb = {"schema": SCHEMA, "suite": a.suite or meta.get("suite", "core"),
          "started_utc": meta.get("started_utc",
                                  datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")),
          "duration_s": meta.get("duration_s", 0), "verdict": verdict, "counts": counts,
          "flight_counts": flight_counts,
          "model": meta.get("model", {}), "cells": scored,
          "context": {"derived": {"person_height_m": 1.7, "d_hold_m": round(HOLD_K * 1.7, 3),
                                  "hold_band_m": [round(BAND_K[0] * 1.7, 3), round(BAND_K[1] * 1.7, 3)],
                                  "crop_fov_deg": CROP_FOV_DEG},
                      "spec": "scratchpad/simv2/spec_metrics.md"}}
    (suite / "scoreboard.json").write_text(json.dumps(sb, indent=2, default=str))
    write_markdown(sb, suite / "scoreboard.md")
    print(f"{suite/'scoreboard.json'}\n{suite/'scoreboard.md'}")
    print(f"suite verdict: {verdict}  {counts}")
    for c in scored:
        print(f"  {c['verdict']:<14s} {c['cell_id']}"
              + (f"   failed: {','.join(c['failed_gates'])}" if c.get("failed_gates") else ""))


if __name__ == "__main__":
    main()
