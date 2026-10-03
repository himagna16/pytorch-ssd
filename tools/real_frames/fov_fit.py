#!/usr/bin/env python3
"""Measure the AI-deck camera's field of view and aim from a SOLO bottle session.

Why: every label this project computes assumes the network's square crop is 70 deg
wide, and nobody has measured it. The lab runbook's bottle FOV (lab_session_runbook.md
section 4.0a: slide a bottle until it leaves the frame) needs a second person watching
a live view. This needs neither: `fov_capture.sh` records an empty room, then the same
room with a bottle standing on taped marks, and this script finds the bottle by
differencing and fits the lens to where it landed.

THE CONVENTIONS (stated because getting one backwards is silent)
----------------------------------------------------------------
y      lateral offset of a mark, metres, POSITIVE = the drone's LEFT, seen from behind
       the drone looking where it looks. This is the room/body +y of
       tools/lighthouse/README.md and pose_to_label.py (Crazyflie body frame: x forward,
       y left, z up).
theta  bearing, NEGATIVE = LEFT: the convention of cpx_grab.py, score_real_frames.py and
       pose_to_label.py.  theta = atan2(-y, D).  So the +0.50 m mark at D = 1.00 m is
       theta = -26.6 deg (left).
x_px   image column, 0 = the image's left edge. If the image is not mirrored, an object
       on the drone's left lands at small x_px, so the fitted focal length comes out
       POSITIVE. A negative one means a mirrored image (or marks taped with left and right
       swapped); the report says so loudly.

WHAT IT DOES, per mark
----------------------
median frame of the clip  minus  (gain x median frame of the empty reference)
  - the gain (median pixel ratio) cancels a small exposure change between clips;
  - |difference| is thresholded at 5 x its robust noise, and the connected blob with the
    most contrast is the object;
  - its horizontal centre is measured ROW BY ROW as a coverage-weighted centroid: each
    row is normalised by that row's own object and background levels, so a background
    that changes behind the object (dark door on one side, bright wardrobe on the other)
    does not drag the centre; the median over rows is the answer;
  - a quality score in [0, 1] = (share of all changed pixels that are this blob)
    x (contrast / noise, saturating at 6) x (share of rows agreeing within 0.75 px)
    x (0.7 if the column-sum peak disagrees with the centre, else 1).
  Flags: NOT FOUND, TOUCHES THE LEFT/RIGHT EDGE (centre biased: not used), TOO BIG
  (a person in view?), low quality. Unusable marks are reported and left out of the fit.

THE FIT
-------
Two pinhole models, both reported; the one with the smaller residual is the headline:
  linear   x_px = cx + f * tan(theta)          (an off-centre lens: principal point cx)
  yaw      x_px = c0 + f * tan(theta - a)      (c0 = image centre; the camera turned by a)
They agree when the aim error is small. A camera turned by a few degrees bends the
linear model's residuals into a U (it is wrong by f * tan(a) * tan(theta)^2, up to ~2.5 px
at 6 deg / 35 deg), which is why the yaw model exists. With one forward distance only
f / D is measured: f inherits the error in FOV_DIST (measure it to the lens front; the
pupil of this tiny lens is a few mm behind it, < 1 % at 1 m).

Reported: focal length in stream px/rad (and at the full 324-px frame), horizontal FOV
of the full stream, of its centre square (122 px of 162: the square the network sees),
the implied FOV of the flight app's 244 x 244 crop of 324 x 244 (ASSUMES the 162 x 122
stream is the full sensor frame read out 2x down, i.e. the HM01B0's QQVGA mode keeps the
whole field; not verified), the vertical FOV (square pixels assumed), the aim (where
theta = 0 lands vs the image centre, and which x-bin a person on the tape line would get),
the residuals, and the comparison with the 70 deg assumption, which lives in:
  tools/real_frames/score_real_frames.py   --crop-hfov default 70.0 (a literal in main())
  tools/lighthouse/pose_to_label.py        CameraSpec.crop_hfov_deg = 70.0,
                                           CameraSpec.crop_vfov_deg = 70.0, --crop-hfov 70.0
  tools/crazysim_macos/camera_model.py     FOCAL_PX_PER_RAD = 122 / tan(35 deg) = 174.23
                                           (px/rad at 324 x 244: the same 70 deg crop)

Usage
-----
  fov_fit.py <session>                    fit a session folder written by fov_capture.sh
  fov_fit.py <session> --check y+0.25     quick check of one mark (used live by the script)
  fov_fit.py --selftest [--keep DIR]      synthesise a session with KNOWN f and aim, fit it,
                                          print recovered vs injected (no hardware)
  fov_fit.py --init <session> --dist 1.0 --offsets "0 0.25 -0.25" ...
                                          write fov_session.json and print the capture
                                          plan (used by fov_capture.sh)
Exit codes: 0 fit done (or check found the object), 1 check: object not usable,
2 bad input, 3 fewer than --min-usable usable marks (4 by default), 4 selftest failed,
5 POOR fit (marks disagree by > 2.5 px RMS at 162 px: wrong marks, drone moved, ...).

Session folder (what fov_capture.sh writes):
  fov_session.json   geometry: distance, offsets, lens height, object size if given
  empty_start/       empty room, before the first mark (the reference)
  y+0.00/ y+0.25/ y-0.25/ ...   one clip per mark (cpx_grab.py frames; the highest
                     take in a folder wins, so a retake simply adds take 2)
  empty_end/         empty room after the last mark (drift check; also a 2nd reference)
  fov_fit.json       written by this script
"""
from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage, optimize

SESSION_FILE = "fov_session.json"
RESULT_FILE = "fov_fit.json"
EMPTY_START, EMPTY_END = "empty_start", "empty_end"
IMG_EXTS = {".png", ".jpg", ".jpeg", ".pgm", ".bmp"}
TAKE_RE = re.compile(r"_take(\d+)_")
MIN_USABLE = 4
MIN_QUALITY = 0.35

# The frame the flight app crops from, and its crop (crazyflie_ssd preprocess:
# 244 x 244 centre of 324 x 244, resized to 128 x 128).
FULL_SENSOR_W, FULL_SENSOR_H = 324, 244
FLIGHT_CROP_W = 244
DECK_STREAM_W = 162            # the WiFi stream on the decks today (162 x 122, ~2 fps)

# What the rest of the repo assumes today.
ASSUMED_CROP_HFOV_DEG = 70.0
SIM_FOCAL_FULL_PX = 122.0 / math.tan(math.radians(35.0))     # camera_model.FOCAL_PX_PER_RAD
ASSUMPTION_SITES = [
    "tools/real_frames/score_real_frames.py: --crop-hfov default 70.0 (a literal in main(), "
    "no named constant)",
    "tools/lighthouse/pose_to_label.py: CameraSpec.crop_hfov_deg = 70.0 and "
    "CameraSpec.crop_vfov_deg = 70.0 (its --crop-hfov also defaults to 70.0)",
    "tools/crazysim_macos/camera_model.py: FOCAL_PX_PER_RAD = 122 / tan(35 deg) = 174.23 "
    "px/rad at 324 x 244 (the same 70 deg crop)",
]
XBIN9_INNER = [-1.0 + 2.0 * i / 9 for i in range(1, 9)]       # score_real_frames.XBIN9_INNER


# =============================================================================
# geometry helpers and the session file
# =============================================================================

def bearing_deg(y: float, dist: float) -> float:
    """Repo bearing (NEGATIVE = left) of a mark y metres to the LEFT at dist metres."""
    return math.degrees(math.atan2(-y, dist)) + 0.0     # + 0.0: no "-0.0" for the centre mark


def mark_dir(y: float) -> str:
    """Folder name for the mark at lateral offset y: y+0.25, y-0.50, y+0.00."""
    return f"y{y:+.2f}"


def inches(m: float) -> str:
    """0.5 -> '1 ft 7 5/8 in' (to the nearest 1/8 in), for a tape measure in feet."""
    eighths = int(round(abs(m) / 0.0254 * 8))
    ft, rem = divmod(eighths, 12 * 8)
    whole, frac = divmod(rem, 8)
    fr = {0: "", 1: " 1/8", 2: " 1/4", 3: " 3/8", 4: " 1/2", 5: " 5/8", 6: " 3/4", 7: " 7/8"}[frac]
    s = f"{whole}{fr} in"
    return f"{ft} ft {s}" if ft else s


def spoken(y: float) -> str:
    """What `say` reads out for the mark: 'mark plus 0.5, left'."""
    if abs(y) < 1e-9:
        return "the centre mark"
    return f"mark {'plus' if y > 0 else 'minus'} {abs(y):g}, {'left' if y > 0 else 'right'}"


def described(y: float, dist: float) -> str:
    if abs(y) < 1e-9:
        return f"CENTRE mark, on the tape line, {dist:.2f} m out (bearing 0.0 deg)"
    side = "LEFT" if y > 0 else "RIGHT"
    return (f"{y:+.2f} m = {abs(y):.2f} m ({inches(y)}) to the drone's {side}, {dist:.2f} m out "
            f"(bearing {bearing_deg(y, dist):+.1f} deg)")


def parse_offsets(text: str) -> list[float]:
    out = []
    for tok in re.split(r"[\s,]+", text.strip()):
        if not tok:
            continue
        try:
            out.append(float(tok))
        except ValueError:
            raise ValueError(f"FOV_OFFSETS: {tok!r} is not a number (metres, + = drone's LEFT)")
    if len(out) < MIN_USABLE:
        raise ValueError(f"FOV_OFFSETS: need at least {MIN_USABLE} marks for a fit, got {len(out)}")
    if len({round(v, 3) for v in out}) != len(out):
        raise ValueError("FOV_OFFSETS: the same mark is listed twice")
    return out


def init_session(d: Path, dist: float, offsets: list[float], lens_height: float,
                 obj: str = "bottle", obj_height=None, obj_width=None, stand_height=None,
                 drone: str = "unknown", light: str = "room", mock: bool = False,
                 extra: dict | None = None) -> dict:
    """Write fov_session.json. The ONE place the session schema is defined."""
    if not dist > 0:
        raise ValueError(f"FOV_DIST must be > 0 m (got {dist})")
    worst = max(abs(math.degrees(math.atan2(abs(y), dist))) for y in offsets)
    sess = {
        "tool": "fov_capture.sh", "schema": 1,
        "created": time.strftime("%Y-%m-%d %H:%M:%S"),
        "convention": ("offset_m: lateral offset of the mark, POSITIVE = the drone's LEFT seen from "
                       "behind it (room/body +y, tools/lighthouse/README.md); bearing_deg = "
                       "atan2(-offset, distance), NEGATIVE = LEFT (cpx_grab.py / score_real_frames.py)"),
        "distance_m": dist, "lens_height_m": lens_height,
        "distance_note": "forward distance from the lens to the line of marks, measured along the "
                         "tape line; every mark is on one line perpendicular to it",
        "object": obj, "object_height_m": obj_height, "object_width_m": obj_width,
        "stand_height_m": stand_height,
        "drone": drone, "light": light, "mock": bool(mock),
        "max_bearing_deg": round(worst, 2),
        "empty_dirs": [EMPTY_START, EMPTY_END],
        "positions": [{"index": i + 1, "offset_m": y, "bearing_deg": round(bearing_deg(y, dist), 3),
                       "dir": mark_dir(y)} for i, y in enumerate(offsets)],
    }
    if extra:
        sess.update(extra)
    d.mkdir(parents=True, exist_ok=True)
    (d / SESSION_FILE).write_text(json.dumps(sess, indent=2))
    return sess


def load_session(d: Path) -> dict:
    p = d / SESSION_FILE
    if not p.exists():
        raise FileNotFoundError(f"no {SESSION_FILE} in {d}: is this a fov_capture.sh folder?")
    return json.loads(p.read_text())


# =============================================================================
# frames
# =============================================================================

def clip_files(d: Path):
    """Frames of the HIGHEST take in a folder (a retake adds take 2 next to take 1)."""
    if not d.is_dir():
        return [], None
    takes: dict[int, list[Path]] = {}
    for p in sorted(d.iterdir()):
        if p.suffix.lower() not in IMG_EXTS or p.name.startswith("."):
            continue
        m = TAKE_RE.search(p.name)
        takes.setdefault(int(m.group(1)) if m else 0, []).append(p)
    if not takes:
        return [], None
    t = max(takes)
    return takes[t], t


def load_clip(d: Path) -> dict | None:
    """Median frame (float32) and stats of one clip folder, or None if it has no frames."""
    files, take = clip_files(d)
    arrs = []
    for p in files:
        try:
            with Image.open(p) as im:
                arrs.append(np.asarray(im.convert("L"), np.float32))
        except Exception:
            continue                              # truncated / not an image: skip it
    if not arrs:
        return None
    shape = Counter(a.shape for a in arrs).most_common(1)[0][0]
    arrs = [a for a in arrs if a.shape == shape]
    stack = np.stack(arrs)
    return {"dir": d.name, "take": take, "n": len(arrs), "shape": shape,
            "median": np.median(stack, axis=0).astype(np.float32),
            "mean": float(stack.mean()),
            "jpeg": any(p.suffix.lower() in (".jpg", ".jpeg") for p in files)}


# =============================================================================
# finding the object
# =============================================================================

def _robust_sigma(x: np.ndarray) -> float:
    return 1.4826 * float(np.median(np.abs(x - np.median(x))))


def detect(pos: np.ndarray, ref: np.ndarray, sigma_k: float = 5.0,
           min_quality: float = MIN_QUALITY) -> dict:
    """Find the object that is in `pos` but not in `ref`; see the module docstring."""
    H, W = pos.shape
    s = W / float(DECK_STREAM_W)                  # pixel scale vs the 162-wide deck stream
    out = {"found": False, "usable": False, "x": None, "quality": 0.0, "flags": []}
    valid = ref > 4.0
    gain = float(np.median(pos[valid] / ref[valid])) if valid.sum() > 0.25 * valid.size else 1.0
    out["gain"] = round(gain, 4)
    bg = gain * ref
    diff = pos - bg
    d0 = diff - float(np.median(diff))
    sig_px = max(_robust_sigma(d0), 0.5)          # per-pixel noise of the difference
    sm = ndimage.uniform_filter(d0, size=3, mode="nearest")
    sig_sm = max(_robust_sigma(sm), 0.3)
    thr = max(sigma_k * sig_sm, 4.0)
    out.update(noise_dn=round(sig_px, 2), threshold_dn=round(thr, 2))
    mask = ndimage.binary_opening(np.abs(sm) > thr, structure=np.ones((2, 2), bool))
    lab, n = ndimage.label(mask, structure=np.ones((3, 3), bool))
    changed_frac = float(mask.mean())
    out["changed_frac"] = round(changed_frac, 4)
    if n == 0:
        out["flags"].append("NOT FOUND: nothing differs from the empty reference")
        return out
    idx = np.arange(1, n + 1)
    mass = np.asarray(ndimage.sum(np.abs(sm), lab, idx), float)
    area = np.asarray(ndimage.sum(mask, lab, idx), float)
    order = np.argsort(mass)[::-1]
    k = order[0]
    min_area = max(8.0, 15.0 * s * s)
    if area[k] < min_area:
        out["flags"].append(f"NOT FOUND: largest change is only {int(area[k])} px "
                            f"(need {int(min_area)})")
        return out
    blob = lab == idx[k]
    rows = np.where(blob.any(axis=1))[0]
    cols = np.where(blob.any(axis=0))[0]
    c_lo, c_hi, r_lo, r_hi = int(cols.min()), int(cols.max()), int(rows.min()), int(rows.max())
    sgn = 1.0 if float(np.sum(d0[blob])) < 0 else -1.0    # +1: object DARKER than behind it
    mass_frac = float(mass[k] / mass.sum())
    second = float(mass[order[1]] / mass[k]) if n > 1 else 0.0
    out.update(found=True, blob_cols=[c_lo, c_hi], blob_rows=[r_lo, r_hi],
               blob_area=int(area[k]), width_px=c_hi - c_lo + 1, rows_px=r_hi - r_lo + 1,
               darker=bool(sgn > 0), mass_frac=round(mass_frac, 3),
               second_blob_ratio=round(second, 3))

    # --- row-by-row coverage centroid ------------------------------------------------
    cmin = max(3.0 * sig_px, 5.0)
    centres, contrasts, widths, signs, edges, used_rows = [], [], [], [], [], []
    for r in rows:
        bc = np.where(blob[r])[0]
        if bc.size == 0:
            continue
        a, b = max(0, int(bc.min()) - 2), min(W - 1, int(bc.max()) + 2)
        xs = np.arange(a, b + 1, dtype=float)
        bg_r, p_r = bg[r, a:b + 1], pos[r, a:b + 1]
        # sign PER ROW: a dark bottle on a light stand is darker in some rows, lighter in others
        sg = 1.0 if float(np.sum(d0[r, bc])) < 0 else -1.0
        con = sg * (bg_r - p_r)                  # > 0 where the object shows
        inside = bc - a
        kk = max(1, int(round(0.4 * inside.size)))
        core = inside[np.argsort(con[inside])[::-1][:kk]]
        obj_r = float(p_r[core].mean())           # this row's object brightness
        denom = sg * (bg_r - obj_r)               # this row's full-coverage contrast
        if np.any(denom < cmin):                  # the object vanishes against part of the
            continue                              # background in this row: cannot normalise
        cov = np.clip(con / denom, 0.0, 1.0)
        cov[cov < 0.15] = 0.0
        if cov.sum() < 1.0:
            continue
        edges.append(-1 if (a == 0 and cov[0] > 0) else (1 if (b == W - 1 and cov[-1] > 0) else 0))
        used_rows.append(int(r))
        centres.append(float((xs * cov).sum() / cov.sum()))
        contrasts.append(float(np.median(denom[inside])))
        widths.append(float(cov.sum()))
        signs.append(sg)
    blob_at_edge = -1 if c_lo <= 0 else (1 if c_hi >= W - 1 else 0)
    if r_hi >= H - 1:
        out["flags"].append("cut off by the bottom edge (fine for the horizontal centre)")
    too_big = (out["width_px"] > 0.30 * W) or (area[k] > 0.10 * H * W)
    if too_big:
        out["flags"].append("TOO BIG for the object: was a person (or the drone's view) moving? not used")
    if changed_frac > 0.20 or (changed_frac > 0.05 and mass_frac < 0.6):
        out["flags"].append(f"{100 * changed_frac:.0f}% of the image changed: drone bumped, or a "
                            "light switched?")
    if len(centres) < 3:
        if blob_at_edge:
            out["flags"].append(f"TOUCHES THE {'LEFT' if blob_at_edge < 0 else 'RIGHT'} EDGE of the "
                                "image: centre would be biased, not used")
        out["flags"].append(f"only {len(centres)} rows measurable (need 3): object too faint "
                            "against part of its background")
        return out

    # Use the NARROWEST rows only. A wide object's outline is symmetric in ANGLE, not in
    # pixels, so its pixel centre sits outward of its axis by ~ f tan(phi) sec^2(phi) h^2
    # (h = half-width / range): 0.1 px for a 7.5 cm bottle at 1 m and 35 deg, ~1 px for a
    # 24 cm bin under it. Rows wider than the bottle part (a stand, a base) are dropped.
    wd = np.asarray(widths)
    w20 = float(np.percentile(wd, 20))
    keep = wd <= max(1.5 * w20, w20 + 2.0 * s)
    if keep.sum() >= 3:
        centres = list(np.asarray(centres)[keep])
        contrasts = list(np.asarray(contrasts)[keep])
        widths = list(wd[keep])
        signs = list(np.asarray(signs)[keep])
        edges = list(np.asarray(edges)[keep])
        used_rows = list(np.asarray(used_rows)[keep])
    # the edge test is on the rows actually measured: a wide stand reaching the edge does
    # not bias a bottle that is well inside the picture
    edge = int(np.sign(sum(edges))) if any(edges) else 0
    if any(edges):
        side = "LEFT" if (edge < 0 or (edge == 0 and edges[0] < 0)) else "RIGHT"
        out["flags"].append(f"TOUCHES THE {side} EDGE of the image: centre would be biased, not used")
    elif blob_at_edge:
        out["flags"].append("a wider part (a stand?) reaches the edge; the narrow part is measured")
    x = float(np.median(centres))
    agree = float(np.mean(np.abs(np.asarray(centres) - x) <= max(0.75, 0.75 * s)))
    contrast = float(np.median(contrasts))
    snr = contrast / sig_px
    # cross-check: peak of the column profile over the blob's rows
    ur = np.asarray(used_rows)
    prof = np.clip(np.asarray(signs)[:, None] * -d0[ur], 0, None).sum(axis=0)
    prof = np.convolve(prof, [0.25, 0.5, 0.25], mode="same")
    peak = int(np.argmax(prof))
    peak_ok = abs(peak - x) <= max(1.5 * s, float(np.median(widths)) / 2.0)
    q = mass_frac * min(1.0, snr / 6.0) * agree * (1.0 if peak_ok else 0.7)
    out.update(x=round(x, 3), rows_used=len(centres), object_width_px=round(float(np.median(widths)), 2),
               darker=bool(np.mean(signs) > 0), row_agreement=round(agree, 3),
               row_spread_px=round(float(np.std(centres)), 3), contrast_dn=round(contrast, 1),
               snr=round(snr, 1), peak_col=peak, quality=round(q, 3))
    if not peak_ok:
        out["flags"].append(f"column-sum peak ({peak}) disagrees with the centre ({x:.1f})")
    if second > 0.5:
        out["flags"].append(f"a second change elsewhere is {100 * second:.0f}% as strong: "
                            "something else moved?")
    if abs(gain - 1.0) > 0.15:
        out["flags"].append(f"exposure differs from the reference by {100 * (gain - 1):+.0f}% "
                            "(gain-matched, but check)")
    if q < min_quality:
        out["flags"].append(f"low quality {q:.2f} (< {min_quality:.2f}): not used")
    out["usable"] = bool(q >= min_quality and not (any(edges) or too_big))
    return out


def detect_best_ref(pos: np.ndarray, refs: list[tuple[str, np.ndarray]], **kw) -> dict:
    """Detect against each empty reference (start, end) and keep the cleaner result, so a
    scene change half-way through (a chair nudged) costs half the marks at most."""
    best = None
    for name, ref in refs:
        if ref.shape != pos.shape:
            continue
        r = detect(pos, ref, **kw)
        r["reference"] = name
        key = (r["usable"], r["found"], r["quality"])
        if best is None or key > (best["usable"], best["found"], best["quality"]):
            best = r
    if best is None:
        best = {"found": False, "usable": False, "x": None, "quality": 0.0, "reference": None,
                "flags": ["frame size differs from the empty reference"]}
    return best


# =============================================================================
# the fit
# =============================================================================

def fit_linear(theta: np.ndarray, x: np.ndarray) -> dict:
    """x = cx + f * tan(theta), ordinary least squares."""
    A = np.column_stack([np.ones_like(theta), np.tan(theta)])
    sol, *_ = np.linalg.lstsq(A, x, rcond=None)
    r = x - A @ sol
    dof = max(len(x) - 2, 1)
    s2 = float(r @ r) / dof
    cov = s2 * np.linalg.inv(A.T @ A)
    return {"model": "linear", "cx": float(sol[0]), "f": float(sol[1]),
            "se_cx": math.sqrt(cov[0, 0]), "se_f": math.sqrt(cov[1, 1]),
            "resid": r, "rss": float(r @ r), "rms": float(np.sqrt(np.mean(r ** 2)))}


def fit_yaw(theta: np.ndarray, x: np.ndarray, c0: float, f0: float, a0: float) -> dict | None:
    """x = c0 + f * tan(theta - a): principal point at the image centre, camera turned by a."""
    def res(p):
        return c0 + p[0] * np.tan(theta - p[1]) - x
    try:
        sol = optimize.least_squares(res, [f0, a0], bounds=([-2e3, -0.6], [2e3, 0.6]))
    except Exception:
        return None
    r = -sol.fun
    dof = max(len(x) - 2, 1)
    s2 = float(r @ r) / dof
    try:
        cov = s2 * np.linalg.inv(sol.jac.T @ sol.jac)
    except np.linalg.LinAlgError:
        return None
    f, a = float(sol.x[0]), float(sol.x[1])
    return {"model": "yaw", "f": f, "a": a, "se_f": math.sqrt(abs(cov[0, 0])),
            "se_a": math.sqrt(abs(cov[1, 1])), "cx": c0 + f * math.tan(-a),
            "resid": r, "rss": float(r @ r), "rms": float(np.sqrt(np.mean(r ** 2)))}


def fit_both(theta: np.ndarray, x: np.ndarray, c0: float) -> tuple[dict, dict | None]:
    lin = fit_linear(theta, x)
    a0 = -math.atan((lin["cx"] - c0) / lin["f"]) if lin["f"] else 0.0
    yaw = fit_yaw(theta, x, c0, lin["f"], a0)
    return lin, yaw


def pick(lin: dict, yaw: dict | None) -> dict:
    """The headline model. YAW unless LINEAR fits clearly better (residual sum of squares
    under half): a drone set on a chair by eye is turned a few degrees far more often than
    a lens is off-centre by as much, and with ~1 cm of placement noise per mark a plain
    "smaller residual wins" flips between the two at random. f agrees either way (~1 %);
    the aim's interpretation is what differs."""
    if yaw is None:
        return lin
    return lin if lin["rss"] < 0.5 * yaw["rss"] else yaw


def predict(fit: dict, theta: float, c0: float) -> float:
    if fit["model"] == "yaw":
        return c0 + fit["f"] * math.tan(theta - fit["a"])
    return fit["cx"] + fit["f"] * math.tan(theta)


def x_bin(xn: float):
    if abs(xn) > 1:
        return None
    return sum(1 for e in XBIN9_INNER if e < xn)


def camera_numbers(best: dict, W: int, H: int) -> dict:
    """Everything derived from the headline fit."""
    f = best["f"]
    fa = abs(f)
    c0 = (W - 1) / 2.0
    hfov = lambda half_px: 2 * math.degrees(math.atan(half_px / fa))   # noqa: E731
    se = best["se_f"]
    dhfov = lambda half_px: 2 * math.degrees(half_px / (fa * fa + half_px * half_px)) * se  # noqa: E731
    scale = FULL_SENSOR_W / float(W)               # stream px -> full-frame px (assumption)
    crop_half = FLIGHT_CROP_W / 2.0 / scale
    # where theta = 0 (the tape line) lands, and where the image centre looks
    x0 = best["cx"]
    if best["model"] == "yaw":
        heading = math.degrees(best["a"])
        to_bearing = lambda xp: math.degrees(best["a"] + math.atan((xp - c0) / f))   # noqa: E731
    else:
        heading = math.degrees(math.atan((c0 - x0) / f))
        to_bearing = lambda xp: math.degrees(math.atan((xp - x0) / f))              # noqa: E731
    sq_half = min(W, H) / 2.0
    tape_xn = (x0 - c0) / sq_half                  # tape line in the network's [-1, 1]
    crop_hfov = hfov(crop_half)
    return {
        "focal_px_per_rad_stream": round(fa, 3), "focal_se": round(se, 3),
        "focal_px_per_rad_full324": round(fa * scale, 2),
        "sim_focal_px_per_rad_full324": round(SIM_FOCAL_FULL_PX, 2),
        "mirrored": bool(f < 0),
        "hfov_full_stream_deg": round(hfov(W / 2.0), 2), "hfov_full_stream_se": round(dhfov(W / 2.0), 2),
        "hfov_centre_square_deg": round(hfov(sq_half), 2), "hfov_centre_square_se": round(dhfov(sq_half), 2),
        "hfov_flight_crop_deg": round(crop_hfov, 2),
        "flight_crop_assumption": (f"the {W}x{H} stream is the full {FULL_SENSOR_W}x{FULL_SENSOR_H} "
                                   f"sensor frame scaled by {1 / scale:g} (HM01B0 QQVGA = 2x down, "
                                   "same field of view); NOT verified"),
        "hfov_flight_crop_if_stream_were_unscaled_crop_deg": round(hfov(FLIGHT_CROP_W / 2.0), 2),
        "vfov_stream_deg": round(hfov(H / 2.0), 2),
        "tape_line_column": round(x0, 2), "image_centre_column": c0,
        "tape_line_offset_px": round(x0 - c0, 2),
        "camera_heading_deg": round(heading, 2),
        "heading_meaning": "bearing the image centre looks at; NEGATIVE = the camera points LEFT of the tape line",
        "tape_line_network_x": round(tape_xn, 3), "tape_line_network_xbin": x_bin(tape_xn),
        "span_left_edge_deg": round(to_bearing(-0.5), 2), "span_right_edge_deg": round(to_bearing(W - 0.5), 2),
        "vs_70": {
            "assumed_crop_hfov_deg": ASSUMED_CROP_HFOV_DEG,
            "measured_crop_hfov_deg": round(crop_hfov, 2),
            "difference_deg": round(crop_hfov - ASSUMED_CROP_HFOV_DEG, 2),
            "where_70_is_assumed": ASSUMPTION_SITES,
            "bearing_to_xbin": [
                {"bearing_deg": b,
                 "xbin_at_70": x_bin(math.tan(math.radians(b)) / math.tan(math.radians(35.0))),
                 "xbin_measured": x_bin(math.tan(math.radians(b)) / math.tan(math.radians(crop_hfov / 2)))}
                for b in (5, 10, 14, 16, 20, 25, 30)],
        },
    }


# =============================================================================
# running a session
# =============================================================================

def _refs(d: Path):
    refs = []
    for name in (EMPTY_START, EMPTY_END):
        c = load_clip(d / name)
        if c is not None:
            refs.append((name, c))
    return refs


def run_check(d: Path, pos_dir: str, quiet: bool = False) -> int:
    """One mark, right after it was recorded: is the object visible and usable?"""
    refs = _refs(d)
    if not refs:
        print(f"CHECK {pos_dir}: no empty reference clip in {d} yet")
        return 2
    c = load_clip(d / pos_dir)
    if c is None:
        print(f"CHECK {pos_dir}: NO FRAMES in {d / pos_dir}")
        return 1
    r = detect_best_ref(c["median"], [(n, rc["median"]) for n, rc in refs])
    if r["usable"]:
        print(f"CHECK {pos_dir}: FOUND at column {r['x']:.1f} of {c['shape'][1]}, quality "
              f"{r['quality']:.2f}, {r['object_width_px']:.0f} px wide, {r['rows_used']} rows measured, "
              f"{abs(r['contrast_dn']):.0f} DN {'darker' if r['darker'] else 'lighter'} than behind it "
              f"({c['n']} frames)")
        for fl in r["flags"]:
            print(f"   note: {fl}")
        return 0
    why = "; ".join(r["flags"]) or "not usable"
    print(f"CHECK {pos_dir}: NOT USABLE ({c['n']} frames): {why}")
    if r.get("found") and r.get("darker") is not None and not quiet:
        print("   tip: if the background behind the mark is dark, a dark object barely shows; "
              "wrap it in white paper, or raise it so the lighter wall is behind it")
    return 1


def run_fit(d: Path, min_usable: int = MIN_USABLE, json_out: Path | None = None,
            quiet: bool = False) -> tuple[int, dict]:
    """Fit a session folder. Returns (exit code, result dict)."""
    say = (lambda *a, **k: None) if quiet else print
    try:
        sess = load_session(d)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        say(f"FOV FIT: cannot read the session: {e}")
        return 2, {}
    dist = float(sess["distance_m"])
    refs = _refs(d)
    if not refs:
        say(f"FOV FIT: no empty reference clip ({EMPTY_START}/ or {EMPTY_END}/) with frames in {d}.\n"
            "Without a picture of the room WITHOUT the object there is nothing to subtract. "
            "Re-run fov_capture.sh.")
        return 2, {}
    ref0 = refs[0][1]
    H, W = ref0["shape"]
    c0 = (W - 1) / 2.0
    say(f"== FOV FIT  {d}")
    say(f"   frames {W} x {H}; marks {dist:.2f} m out on one line, lens {sess.get('lens_height_m')} m up; "
        f"object: {sess.get('object')}")
    say("   convention: + offset = the drone's LEFT (seen from behind it); bearing = atan2(-offset, D), "
        "NEGATIVE = LEFT")
    for n, rc in refs:
        say(f"   reference {n}: {rc['n']} frames (take {rc['take']}), mean brightness {rc['mean']:.1f}")
    if any(rc["jpeg"] for _, rc in refs):
        say("   note: JPEG frames. Fine for finding a bottle, not for scoring.")
    drift = None
    if len(refs) == 2 and refs[0][1]["shape"] == refs[1][1]["shape"]:
        dr = detect(refs[1][1]["median"], refs[0][1]["median"])
        drift = {"gain": dr["gain"], "changed_frac": dr["changed_frac"], "found": dr["found"],
                 "area": dr.get("blob_area")}
        msg = (f"exposure {100 * (dr['gain'] - 1):+.1f}%, " +
               (f"a {dr.get('blob_area')} px change at columns {dr.get('blob_cols')}"
                if dr["found"] else "no localised change"))
        say(f"   empty_end vs empty_start (drift over the session): {msg}")
        if dr["found"] and dr.get("blob_area", 0) >= max(8.0, 15.0 * (W / DECK_STREAM_W) ** 2):
            say("!! the two EMPTY clips differ in one place: something in view moved, or the object (or "
                "you) was in view during one of them. Each mark uses whichever empty clip is cleaner; "
                "read the fit quality below before trusting it.")

    rows = []
    for p in sess["positions"]:
        c = load_clip(d / p["dir"])
        rec = {"dir": p["dir"], "offset_m": p["offset_m"], "bearing_deg": p["bearing_deg"]}
        if c is None:
            rec.update(found=False, usable=False, x=None, quality=0.0, n_frames=0,
                       flags=["NOT CAPTURED: no frames in this folder"])
        else:
            r = detect_best_ref(c["median"], [(n, rc["median"]) for n, rc in refs])
            rec.update(r)
            rec.update(n_frames=c["n"], take=c["take"], mean_brightness=round(c["mean"], 1))
        rows.append(rec)

    bri = [rc["mean"] for _, rc in refs] + [r["mean_brightness"] for r in rows if r.get("mean_brightness")]
    if bri:
        say(f"   brightness per clip: {min(bri):.1f} to {max(bri):.1f} (0-255)" +
            ("  !! more than 30% apart: the exposure changed during the run (gain-matched; check the fit)"
             if min(bri) > 0 and max(bri) / min(bri) > 1.3 else ""))
        if min(bri) < 15:
            say("!! NEAR-BLACK clips (mean < 15): the camera is not exposing properly; do not trust this run.")
    say("")
    say(f"   {'mark':>8} {'bearing':>8} {'frames':>6} {'column':>8} {'quality':>8}  notes")
    for rec in rows:
        col = f"{rec['x']:.2f}" if rec.get("x") is not None else "-"
        q = f"{rec['quality']:.2f}" if rec.get("found") else "-"
        use = "" if rec["usable"] else "NOT USED: "
        notes = "; ".join(rec.get("flags", [])) if (not rec["usable"] or rec.get("flags")) else ""
        say(f"   {rec['offset_m']:+7.2f}m {rec['bearing_deg']:+7.1f}d {rec.get('n_frames', 0):>6} "
            f"{col:>8} {q:>8}  {use if notes else ''}{notes}")

    use = [r for r in rows if r["usable"]]
    result = {"session": str(d), "frame_w": W, "frame_h": H, "distance_m": dist,
              "positions": rows, "drift": drift, "n_usable": len(use)}
    if len(use) < min_usable:
        say("")
        say(f"FOV FIT: NOT ENOUGH MARKS. Only {len(use)} of {len(rows)} marks gave a clear, usable "
            f"object position; the fit needs at least {min_usable}.")
        say("   What to do: look at the notes above. 'NOT FOUND' usually means the object is too "
            "close in brightness to what is behind it (try a darker or lighter object, or raise it "
            "so the wall is behind it) or it is below the bottom of the picture (raise it). "
            "'TOUCHES THE EDGE' means that mark is outside the picture: fine, the others carry the "
            "fit. Then record the session again (about 3 minutes).")
        result["status"] = "too_few_usable"
        _write(json_out or d / RESULT_FILE, result)
        return 3, result

    theta = np.radians([r["bearing_deg"] for r in use])
    xs = np.array([r["x"] for r in use], float)
    lin, yaw = fit_both(theta, xs, c0)
    best = pick(lin, yaw)

    # one round of LEAVE-ONE-OUT outlier rejection: a bottle put on the wrong mark should
    # not bend the lens. Each mark is predicted from a fit of the OTHERS (a bad mark pulls a
    # fit that includes it towards itself, so its own residual understates how bad it is).
    dropped = None
    if len(use) >= min_usable + 1:
        worst = None
        for j in range(len(use)):
            th_o, x_o = np.delete(theta, j), np.delete(xs, j)
            lo, yo = fit_both(th_o, x_o, c0)
            m = pick(lo, yo)
            pred = predict(m, theta[j], c0)
            gap = abs(xs[j] - pred)
            if worst is None or gap > worst[1]:
                worst = (j, gap, m["rms"])
        j, gap, rms_o = worst
        lim = max(2.0 * W / DECK_STREAM_W, 6.0 * rms_o)
        if gap > lim:
            dropped = use[j]
            dropped["usable"] = False
            dropped.setdefault("flags", []).append(
                f"OUTLIER: {gap:.1f} px from where the other marks put it (was the object on this mark?)")
            use = [r for k, r in enumerate(use) if k != j]
            theta = np.delete(theta, j)
            xs = np.delete(xs, j)
            lin, yaw = fit_both(theta, xs, c0)
            best = pick(lin, yaw)

    for r, res in zip(use, best["resid"]):
        r["residual_px"] = round(float(res), 3)
    cam = camera_numbers(best, W, H)
    other = lin if best is yaw else yaw
    say("")
    if dropped is not None:
        say(f"   dropped {dropped['dir']} as an outlier: {dropped['flags'][-1]}")
    say(f"   usable marks: {len(use)} of {len(rows)}")
    say("")
    s_px = W / float(DECK_STREAM_W)
    rms = best["rms"]
    quality = "good" if rms <= 1.5 * s_px else ("fair" if rms <= 2.5 * s_px else "POOR")
    say(f"== RESULT ({best['model']} model; residual RMS {rms:.2f} px, "
        f"max {np.max(np.abs(best['resid'])):.2f} px: fit quality {quality})")
    if quality == "POOR":
        say(f"!! POOR FIT: the marks disagree with any one lens by {rms:.1f} px RMS (careful placement gives")
        say(f"!! under {1.5 * s_px:.1f}). Something is off: the object on the wrong marks (+ = the drone's LEFT),")
        say("!! a FOV_OFFSETS list that does not match the tape, the drone moved, or an empty clip that")
        say("!! contains the object. Do NOT use the numbers below; fix it and run again.")
    if cam["mirrored"] and quality != "POOR":
        say("!! THE IMAGE IS MIRRORED: the object on the drone's LEFT appeared on the RIGHT of the image")
        say("!! (or the marks were taped with left and right swapped: + must be the drone's LEFT,")
        say("!! seen from BEHIND the drone). The FOV numbers below still hold; the side does not.")
    sc = W / float(FULL_SENSOR_W)
    say(f"   focal length          {cam['focal_px_per_rad_stream']:.1f} +- {cam['focal_se']:.1f} px/rad in "
        f"this {W}-px stream (= {cam['focal_px_per_rad_full324']:.1f} at 324 px; the simulator "
        f"assumes {SIM_FOCAL_FULL_PX:.2f})")
    say(f"   full stream HFOV      {cam['hfov_full_stream_deg']:.1f} +- {cam['hfov_full_stream_se']:.1f} deg "
        f"({W} px wide)")
    say(f"   centre square HFOV    {cam['hfov_centre_square_deg']:.1f} +- {cam['hfov_centre_square_se']:.1f} deg "
        f"({min(W, H)} px: the square this stream's network input is cut from)")
    say(f"   flight-app crop HFOV  {cam['hfov_flight_crop_deg']:.1f} deg (244 of 324 px = "
        f"{FLIGHT_CROP_W * sc:g} of {W} here)")
    say(f"                         ASSUMES {cam['flight_crop_assumption']}")
    say(f"                         (if the stream were an UNSCALED crop instead, the flight crop would "
        f"be {cam['hfov_flight_crop_if_stream_were_unscaled_crop_deg']:.1f} deg)")
    say(f"   vertical FOV          {cam['vfov_stream_deg']:.1f} deg ({H} rows, square pixels assumed)")
    hd = cam["camera_heading_deg"]
    side = "LEFT" if hd < 0 else "RIGHT"
    say(f"   aim                   straight down the tape line lands at column {cam['tape_line_column']:.1f}, "
        f"{abs(cam['tape_line_offset_px']):.1f} px {'RIGHT' if cam['tape_line_offset_px'] > 0 else 'LEFT'} "
        f"of the image centre ({c0:.1f})")
    if best["model"] == "yaw":
        say(f"                         = the camera is turned {abs(hd):.1f} deg {side} of the tape line")
    else:
        say(f"                         = as if turned {abs(hd):.1f} deg {side}; the linear model fits clearly "
            f"better, which points to an off-centre lens rather than a turned camera")
    xb = cam["tape_line_network_xbin"]
    say(f"                         a person ON the tape line sits at network x = "
        f"{cam['tape_line_network_x']:+.2f}, x-bin {xb if xb is not None else 'off-image'} "
        f"(the centre bin is 4)")
    say(f"   the picture spans     {abs(cam['span_left_edge_deg']):.1f} deg "
        f"{'left' if cam['span_left_edge_deg'] < 0 else 'right'} to "
        f"{abs(cam['span_right_edge_deg']):.1f} deg "
        f"{'right' if cam['span_right_edge_deg'] > 0 else 'left'} of the tape line")
    say(f"   residuals (px)        " + "  ".join(f"{r['offset_m']:+.2f}m:{r['residual_px']:+.2f}" for r in use))
    if other is not None:
        extra = (f", aim {math.degrees(other['a']):+.1f} deg" if other["model"] == "yaw"
                 else f", tape line at column {other['cx']:.1f}")
        say(f"   other model ({other['model']}): f {abs(other['f']):.1f} px/rad{extra}, RMS {other['rms']:.2f} px")
    v = cam["vs_70"]
    say("")
    say(f"== VS THE 70 deg ASSUMPTION: the crop is {v['measured_crop_hfov_deg']:.1f} deg, "
        f"{v['difference_deg']:+.1f} deg vs 70")
    for site in ASSUMPTION_SITES:
        say(f"   {site}")
    say("   bearing -> x-bin   " + "  ".join(
        f"{t['bearing_deg']}d: {t['xbin_at_70']}->{t['xbin_measured']}" for t in v["bearing_to_xbin"]) +
        "   (at 70 -> measured; positive bearings, right of centre)")
    say(f"   to label with it:  score_real_frames.py <frames> --crop-hfov {v['measured_crop_hfov_deg']:.1f}"
        f"   |   pose_to_label.py ... --crop-hfov {v['measured_crop_hfov_deg']:.1f}")
    say("   (one forward distance: f carries the error in FOV_DIST; 1 cm at 1 m = 1 %)")

    result.update(status="ok" if quality != "POOR" else "poor_fit", fit_quality=quality,
                  n_usable=len(use), dropped=dropped["dir"] if dropped else None,
                  fit={"headline": best["model"],
                       "linear": _fitjson(lin), "yaw": _fitjson(yaw)},
                  camera=cam)
    _write(json_out or d / RESULT_FILE, result)
    say(f"\n   written: {json_out or d / RESULT_FILE}")
    return (5 if quality == "POOR" else 0), result


def _fitjson(fit):
    if fit is None:
        return None
    o = {k: (round(v, 4) if isinstance(v, float) else v) for k, v in fit.items() if k != "resid"}
    o["resid"] = [round(float(v), 3) for v in fit["resid"]]
    if "a" in fit:
        o["a_deg"] = round(math.degrees(fit["a"]), 3)
    return o


def _write(path: Path, obj):
    def conv(o):
        if isinstance(o, (np.integer,)):
            return int(o)
        if isinstance(o, (np.floating,)):
            return float(o)
        if isinstance(o, np.ndarray):
            return o.tolist()
        if isinstance(o, (np.bool_,)):
            return bool(o)
        raise TypeError(type(o))
    try:
        Path(path).write_text(json.dumps(obj, indent=2, default=conv))
    except OSError as e:
        print(f"warning: could not write {path}: {e}")


# =============================================================================
# synthetic sessions (selftest and unit tests)
# =============================================================================

def synth_background(W: int, H: int, seed: int = 0) -> np.ndarray:
    """A dorm-like far wall: bright panels on the sides, a DARK door in the middle (the
    background that made the grid's centre cells fail), a floor, and some clutter."""
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    img = 78.0 + 6.0 * np.sin(xx / 7.0)                       # wardrobe panels
    door = (np.abs(xx - W * 0.53) < W * 0.11) & (yy < H * 0.70)
    img[door] = 24.0
    img[yy >= H * 0.70] = 46.0 + 8.0 * np.sin(xx[yy >= H * 0.70] / 3.3 + yy[yy >= H * 0.70] / 5.0)
    for _ in range(6):                                        # clutter
        cx, cy = rng.uniform(0, W), rng.uniform(0, H)
        w, h = rng.uniform(3, 12) * W / 162, rng.uniform(3, 12) * H / 122
        img[(np.abs(xx - cx) < w) & (np.abs(yy - cy) < h)] = rng.uniform(20, 120)
    return img


def _overlap(lo: np.ndarray, hi: np.ndarray, a: float, b: float) -> np.ndarray:
    return np.clip(np.minimum(hi, b) - np.maximum(lo, a), 0.0, None)


def render_cylinder(img: np.ndarray, f: float, heading_deg: float, pp_px: float, dist: float,
                    y: float, radius: float, z_lo: float, z_hi: float, lens_h: float,
                    level: float) -> float:
    """Composite a vertical cylinder (a bottle) standing at (dist forward, y LEFT) into img,
    exact area coverage per pixel. Returns the TRUE image column of its axis.

    Camera: pinhole, square pixels, principal point at the image centre + pp_px, optical
    axis turned to bearing heading_deg (repo sign: negative = left), level."""
    H, W = img.shape
    c0, r0 = (W - 1) / 2.0 + pp_px, (H - 1) / 2.0
    a = math.radians(heading_deg)
    theta = math.atan2(-y, dist)                    # repo bearing of the axis
    phi = theta - a                                 # angle off the optical axis
    rng_ = math.hypot(dist, y)
    half = math.asin(min(0.999, radius / rng_))
    xl, xr = c0 + f * math.tan(phi - half), c0 + f * math.tan(phi + half)
    depth = rng_ * math.cos(phi)
    vt, vb = r0 + f * (lens_h - z_hi) / depth, r0 + f * (lens_h - z_lo) / depth
    cols = np.arange(W, dtype=float)
    rows = np.arange(H, dtype=float)
    ch = _overlap(cols - 0.5, cols + 0.5, xl, xr)
    cv = _overlap(rows - 0.5, rows + 0.5, vt, vb)
    c = np.clip(np.outer(cv, ch), 0.0, 1.0)
    img *= (1.0 - c)
    img += level * c
    return c0 + f * math.tan(phi)


def synth_session(d: Path, W: int = 162, H: int = 122, f: float = 84.0, heading_deg: float = -6.0,
                  pp_px: float = 0.0, dist: float = 1.0,
                  offsets=(0.0, 0.25, -0.25, 0.5, -0.5, 0.7, -0.7), lens_h: float = 0.8,
                  radius: float = 0.0375, z_lo: float = 0.40, z_hi: float = 0.65,
                  level: float = 14.0, stand: bool = True, noise: float = 3.0, n_frames: int = 6,
                  gain_jitter: float = 0.04, placement_sd: float = 0.0, flip: bool = False,
                  distractor: bool = False, no_object: bool = False, seed: int = 1) -> dict:
    """Write a whole fov_capture.sh-style session with KNOWN optics. Returns the truth."""
    rng = np.random.default_rng(seed)
    bg = synth_background(W, H, seed)
    init_session(d, dist, list(offsets), lens_h, obj="bottle", obj_height=z_hi - z_lo,
                 obj_width=2 * radius, stand_height=z_lo, drone="synthetic", light="synthetic",
                 extra={"synthetic": {"f": f, "heading_deg": heading_deg, "pp_px": pp_px,
                                      "noise": noise, "seed": seed}})
    t0 = 1_790_000_000.0
    truth = {"f": f, "heading_deg": heading_deg, "pp_px": pp_px, "columns": {}}

    def write_clip(folder: str, scene: np.ndarray, subj: str):
        nonlocal t0
        out = d / folder
        out.mkdir(parents=True, exist_ok=True)
        g = 1.0 + rng.uniform(-gain_jitter, gain_jitter)
        for k in range(n_frames):
            fr = g * scene + rng.normal(0.0, noise, scene.shape)
            fr = np.clip(np.round(fr), 0, 255).astype(np.uint8)
            if flip:
                fr = np.ascontiguousarray(fr[:, ::-1])
            t0 += 0.5
            Image.fromarray(fr, "L").save(
                out / f"vis0_subj-{subj}_light-synthetic_take1_f{k + 1:05d}_t{t0:.3f}.png")

    write_clip(EMPTY_START, bg, "empty")
    for y in offsets:
        scene = bg.copy()
        yt = y + (rng.normal(0.0, placement_sd) if placement_sd else 0.0)
        if not no_object:
            if stand:     # an upturned ROUND bin under the bottle (a cylinder: no bias)
                render_cylinder(scene, f, heading_deg, pp_px, dist, yt, 0.12, 0.0, z_lo, lens_h, 104.0)
            xc = render_cylinder(scene, f, heading_deg, pp_px, dist, yt, radius, z_lo, z_hi, lens_h, level)
            truth["columns"][mark_dir(y)] = (W - 1 - xc) if flip else xc
        if distractor and abs(y - 0.25) < 1e-9:   # something else moved, smaller than the object
            scene[int(H * 0.15):int(H * 0.15) + 4, int(W * 0.85):int(W * 0.85) + 5] += 40.0
        write_clip(mark_dir(y), scene, "bottle")
    write_clip(EMPTY_END, bg, "empty")
    return truth


def selftest(keep: Path | None = None, quiet: bool = False) -> int:
    """Synthesise a 162x122 session with known f and aim, fit it, compare. 0 = pass."""
    cases = [
        # name, kwargs, tolerances (f %, heading deg)
        ("deck stream 162x122, camera turned 6 deg LEFT, bottle on a round bin",
         dict(W=162, H=122, f=84.0, heading_deg=-6.0, seed=11), (1.0, 0.25)),
        # 1 cm (sd) of bottle placement error per mark is the real limit: over 20 seeds it
        # gives f sd 0.8-1.1 % (max 3.2 %) and aim sd 0.26 deg; tolerance ~3-4 sd. This seed
        # is an unlucky draw (noise tips the model choice to "linear": aim +0.86 deg); it is
        # kept, not swapped for a luckier one.
        ("same, aimed 3 deg RIGHT, +-4% exposure jitter, 1 cm placement error per mark",
         dict(W=162, H=122, f=90.0, heading_deg=3.0, placement_sd=0.01, gain_jitter=0.04, seed=12),
         (3.5, 1.0)),
        ("full-size 324x244 frames (the mock streamer / restored streamer size)",
         dict(W=324, H=244, f=170.0, heading_deg=-2.0, noise=3.0, seed=13), (1.0, 0.25)),
    ]
    root = Path(keep) if keep else Path(tempfile.mkdtemp(prefix="fov_selftest_"))
    ok_all = True
    print("== fov_fit selftest: synthetic sessions with KNOWN focal length and aim")
    for i, (name, kw, (tol_f, tol_h)) in enumerate(cases, 1):
        d = root / f"case{i}"
        if d.exists():
            shutil.rmtree(d)
        truth = synth_session(d, **kw)
        code, res = run_fit(d, quiet=True)
        if code != 0:
            print(f"   case {i}: FIT FAILED (exit {code}) - {name}")
            ok_all = False
            continue
        cam = res["camera"]
        ef = 100.0 * (cam["focal_px_per_rad_stream"] - truth["f"]) / truth["f"]
        eh = cam["camera_heading_deg"] - truth["heading_deg"]
        W, H = kw["W"], kw["H"]
        true_sq = 2 * math.degrees(math.atan(min(W, H) / 2.0 / truth["f"]))
        col_err = [abs(p["x"] - truth["columns"][p["dir"]]) for p in res["positions"] if p.get("usable")]
        ok = abs(ef) <= tol_f and abs(eh) <= tol_h and res["n_usable"] >= 6
        ok_all &= ok
        print(f"   case {i}: {'PASS' if ok else 'FAIL'}  {name}")
        print(f"      focal   injected {truth['f']:7.2f}  recovered {cam['focal_px_per_rad_stream']:7.2f} "
              f"px/rad  ({ef:+.2f} %, tolerance {tol_f} %)")
        print(f"      aim     injected {truth['heading_deg']:+7.2f}  recovered {cam['camera_heading_deg']:+7.2f} "
              f"deg     ({eh:+.2f} deg, tolerance {tol_h} deg)")
        print(f"      square  injected {true_sq:7.2f}  recovered {cam['hfov_centre_square_deg']:7.2f} deg HFOV; "
              f"model {res['fit']['headline']}; {res['n_usable']}/{len(res['positions'])} marks usable; "
              f"centre error max {max(col_err):.2f} px")
    print(f"== selftest {'PASSED' if ok_all else 'FAILED'}" + (f" (frames kept in {root})" if keep else ""))
    if not keep:
        shutil.rmtree(root, ignore_errors=True)
    return 0 if ok_all else 4


# =============================================================================
# CLI
# =============================================================================

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("session", nargs="?", type=Path, help="session folder written by fov_capture.sh")
    ap.add_argument("--selftest", action="store_true", help="synthesise sessions with known optics and fit them")
    ap.add_argument("--keep", type=Path, default=None, help="selftest: keep the synthetic frames here")
    ap.add_argument("--check", metavar="MARK_DIR", default=None,
                    help="check ONE mark's clip (e.g. y+0.25) against the empty reference")
    ap.add_argument("--min-usable", type=int, default=MIN_USABLE)
    ap.add_argument("--json", type=Path, default=None, help=f"result file (default <session>/{RESULT_FILE})")
    g = ap.add_argument_group("--init (used by fov_capture.sh)")
    g.add_argument("--init", action="store_true", help="write fov_session.json and print the plan")
    g.add_argument("--dist", type=float, default=1.0)
    g.add_argument("--offsets", default="0 0.25 -0.25 0.5 -0.5 0.7 -0.7")
    g.add_argument("--lens-height", type=float, default=0.8)
    g.add_argument("--object", default="bottle")
    g.add_argument("--object-height", type=float, default=None)
    g.add_argument("--object-width", type=float, default=None)
    g.add_argument("--stand-height", type=float, default=None)
    g.add_argument("--drone", default="unknown")
    g.add_argument("--light", default="room")
    g.add_argument("--mock", action="store_true")
    a = ap.parse_args(argv)

    if a.selftest:
        return selftest(a.keep)
    if a.session is None:
        ap.error("give a session folder (or --selftest)")
    if a.init:
        try:
            offs = parse_offsets(a.offsets)
            sess = init_session(a.session, a.dist, offs, a.lens_height, a.object, a.object_height,
                                a.object_width, a.stand_height, a.drone, a.light, a.mock)
        except ValueError as e:
            print(f"FOV setup error: {e}", file=sys.stderr)
            return 2
        # one tab-separated line per mark, for the shell: dir, offset, spoken, printed
        for p in sess["positions"]:
            print(f"{p['dir']}\t{p['offset_m']:+.2f}\t{spoken(p['offset_m'])}\t"
                  f"{described(p['offset_m'], a.dist)}")
        return 0
    if not a.session.is_dir():
        print(f"no such folder: {a.session}")
        return 2
    if a.check:
        return run_check(a.session, a.check)
    code, _ = run_fit(a.session, a.min_usable, a.json)
    return code


if __name__ == "__main__":
    sys.exit(main())
