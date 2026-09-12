#!/usr/bin/env python3
"""Measure the real AI-deck camera from captured frames, and check the numbers
that ``camera_model.py`` currently guesses.

``tools/crazysim_macos/camera_model.py`` carries an ``UNMEASURED`` tuple: ten
parameters taken from the Himax HM01B0 datasheet or from class experience
rather than from our own sensor. This script turns folders of captured frames
into numbers for them. The capture procedures are in
``docs/hardware/camera_measurement_protocol.md`` - read that first; this file is
only the arithmetic.

    measure_camera.py <session_dir> [--json OUT] [--render-mean-dn 165]
    measure_camera.py selftest [--keep DIR] [--quiet]

``selftest`` is the proof that the arithmetic is right: it synthesises every
measurement folder with ``camera_model.py`` itself using KNOWN parameters,
writes real PNGs, runs the very same estimators over them, and prints recovered
vs injected side by side. If a change here breaks an estimator, selftest says
so without anybody going near a drone.

Session layout (every folder optional; what is missing is skipped and said so):

    <session>/
      session.json        operator metadata: distances, target sizes, ROIs
      dark/               lens capped                  -> dark offset, DSNU, read noise, hot px
      flat/               diffuser flat field, roll 0  -> vignetting, PRNU, dead px, noise
      flat_roll180/       same, camera rolled 180 deg  -> cancels illumination gradient
      level_01/ ... level_NN/  bright patch, 3+ levels -> photon transfer: gain, read noise,
                                                          PRNU, DSNU at one gain
      edge/               slanted-edge chart           -> PSF sigma, centre and corners
      fov/                bar target, known pitch      -> focal length px/rad, HFOV, distortion
      ae_step/            lights stepped               -> AE damping
      banding/            flat under room lights       -> LED banding depth and period
      lux_<value>/        one folder per light level   -> total gain vs lux -> scene_light
      blur/               moving bar, known image speed-> effective exposure time

Frames are whatever ``cpx_grab.py`` wrote (``.png`` raw is what you want;
``.jpg`` is accepted but every noise number from JPEG frames is meaningless and
the script says so). Capture sensor-measurement clips WITHOUT ``--bayer``: the
2x2 average destroys exactly the per-pixel structure being measured. A colour
(Bayer) deck is detected from the flat field and its statistics are computed per
CFA phase.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage, optimize

# --- what camera_model.py says today, and what counts as a wild result -------
# (sim value, low, high, unit) - the bounds are "stop and think", not "fail".
EXPECT = {
    "psf_sigma_center_px": (0.65, 0.25, 2.20, "px"),
    "psf_sigma_corner_px": (1.10, 0.30, 3.00, "px"),
    "vignette_a2":         (0.22, -0.05, 0.60, ""),
    "vignette_a4":         (0.10, -0.25, 0.50, ""),
    "prnu_sigma":          (0.008, 0.001, 0.040, "fraction"),
    "dsnu_sigma_dn":       (0.40, 0.02, 3.00, "DN at 1x"),
    "dead_px_frac":        (1e-5, 0.0, 1e-3, "clusters/px"),
    "ae_damping":          (0.25, 0.05, 0.90, "per sensor frame"),
    "banding_depth":       (0.08, 0.0, 0.35, "fraction"),
    "scene_light":         (1.0, 0.005, 3.0, "relative"),
    # derived constants the model treats as exact - worth checking too
    "focal_px_per_rad":    (174.23, 145.0, 205.0, "px/rad"),
    "e_per_dn_1x":         (29.0, 8.0, 90.0, "e-/DN"),
    "read_noise_e":        (4.7, 0.5, 25.0, "e-"),
    "exposure_time_ms":    (4.26, 0.2, 11.0, "ms"),
}

# Sensor constants that the estimators need. Kept as literals (not imported)
# so this script runs on a laptop that only has the captured frames, but they
# are the same numbers camera_model.py uses and selftest checks that.
LINE_PERIOD_S = 31.07e-6
FRAME_LEN_LINES = 534
SENSOR_FRAME_S = FRAME_LEN_LINES * LINE_PERIOD_S      # 16.59 ms, 60.3 fps
MAX_INTG_LINES = 340
AE_TARGET_DN = 60.0
AE_DEADBAND_DN = 5.0
E_PER_DN_1X = 29.0
READ_NOISE_E = 4.7
READ_NOISE_DN_PER_GAIN = READ_NOISE_E / E_PER_DN_1X   # 0.162 DN per unit gain
BANDING_PERIOD_ROWS = 268.0
QUANT_VAR = 1.0 / 12.0                                # 8-bit rounding, DN^2

# Full-resolution frame the protocol assumes. cpx_grab.py --bayer averages every
# 2x2 cell and hands back 162x122, which still analyses cleanly and returns
# quietly wrong per-pixel numbers - so the size is checked and shouted about.
FULL_FRAME_HW = (244, 324)

HP_BOX = 15          # high-pass box size for fixed-pattern noise, px
HP_GAIN = 1.0 - 1.0 / (HP_BOX ** 2)   # variance kept by (I - boxfilter) on iid noise
ESF_BIN = 0.10       # slanted-edge super-resolution bin width, px

IMG_EXT = (".png", ".jpg", ".jpeg", ".bmp", ".pgm")


# =============================================================================
# frame loading
# =============================================================================

def frame_paths(d: Path) -> list[Path]:
    return sorted(p for p in d.iterdir()
                  if p.suffix.lower() in IMG_EXT and not p.name.startswith("."))


def frame_time(p: Path) -> float:
    """Capture time from the name, else the file's mtime.

    cpx_grab.py writes two different shapes: ``..._f00012_t1757530000.123.png``
    for a labelled clip and ``frame_00012_1757530000.123.png`` for an
    unlabelled one. The AE step response is read off these timestamps, so both
    are parsed rather than silently falling back to mtime.
    """
    m = re.search(r"_t(\d{9,}(?:\.\d+)?)", p.name)
    if m:
        return float(m.group(1))
    m = re.search(r"_(\d{9,}(?:\.\d+)?)(?:\.[A-Za-z]+)?$", p.stem + p.suffix)
    if m:
        return float(m.group(1))
    return p.stat().st_mtime


class Clip:
    """One captured folder: frames as float32 (N, H, W) plus timestamps."""

    def __init__(self, d: Path, warmup: int = 0, limit: int | None = None):
        self.dir = d
        paths = frame_paths(d)
        if not paths:
            raise FileNotFoundError(f"no image files in {d}")
        paths.sort(key=frame_time)
        self.jpeg = sum(p.suffix.lower() in (".jpg", ".jpeg") for p in paths) > 0
        if warmup:
            paths = paths[warmup:] or paths[-1:]
        if limit:
            paths = paths[:limit]
        self.paths = paths
        self.t = np.array([frame_time(p) for p in paths], float)
        arrs = []
        for p in paths:
            a = np.asarray(Image.open(p).convert("L"), dtype=np.uint8)
            arrs.append(a)
        shapes = {a.shape for a in arrs}
        if len(shapes) != 1:
            raise ValueError(f"{d}: mixed frame sizes {shapes}")
        self.u8 = np.stack(arrs)
        self.f = self.u8.astype(np.float32)
        self.n, self.h, self.w = self.f.shape

    @property
    def mean_frame(self) -> np.ndarray:
        return self.f.mean(axis=0)

    def fps(self) -> float | None:
        if self.n < 3:
            return None
        dt = np.diff(self.t)
        dt = dt[dt > 0]
        return float(1.0 / np.median(dt)) if dt.size else None

    def __repr__(self):
        return f"<Clip {self.dir.name} n={self.n} {self.w}x{self.h}>"


def open_clip(session: Path, name: str, warmup: int = 0, limit=None) -> Clip | None:
    d = session / name
    if not d.is_dir():
        return None
    try:
        return Clip(d, warmup=warmup, limit=limit)
    except (FileNotFoundError, ValueError) as e:
        print(f"  ! {name}: {e}")
        return None


# =============================================================================
# statistics shared by several measurements
# =============================================================================

def highpass(img: np.ndarray, k: int = HP_BOX) -> np.ndarray:
    """Remove everything smoother than a k x k box: leaves per-pixel structure."""
    return img - ndimage.uniform_filter(img, size=k, mode="nearest")


def temporal_var_map(f: np.ndarray, mask: np.ndarray | None = None,
                     rowwise: bool = True) -> np.ndarray:
    """Per-pixel temporal variance, immune to frame-to-frame and row-wise drift.

    Consecutive differences cancel every fixed pattern exactly. Removing each
    difference's own mean then stops a global brightness wobble - the AE loop
    hunting - from counting as pixel noise:

        d_k = f_{k+1} - f_k - mean(f_{k+1} - f_k)
        var = mean_k(d_k^2) / 2

    Removing each ROW's mean as well is what makes this usable in a real room.
    Mains-driven light plus a rolling shutter puts a row-wise ripple on every
    frame whose phase is random: on the himax_typical preset with banding on,
    that ripple alone took the measured temporal sigma at 60 DN from 1.48 DN to
    3.34 DN, which then implied a gain of 5x instead of 1x and drove the PRNU
    estimate to zero. Row-wise common mode is not pixel noise, so it goes.
    The 1/W of genuine noise that the row mean removes with it is put back.
    """
    d = f[1:] - f[:-1]
    if mask is None:
        mask = np.ones(f.shape[1:], bool)
    glob = d[:, mask].mean(axis=1)
    if not rowwise:
        d -= glob[:, None, None]
        return (d * d).mean(axis=0) / 2.0
    cnt = mask.sum(axis=1).astype(np.float64)              # (H,)
    rsum = (d * mask[None, :, :]).sum(axis=2)              # (N-1, H)
    rmean = rsum / np.maximum(cnt, 1.0)[None, :]
    enough = cnt >= 8
    rmean = np.where(enough[None, :], rmean, glob[:, None])
    d -= rmean[:, :, None]
    v = (d * d).mean(axis=0) / 2.0
    corr = np.where(enough, 1.0 - 1.0 / np.maximum(cnt, 2.0), 1.0)
    return v / corr[:, None]


def robust_sigma(x: np.ndarray) -> float:
    x = np.asarray(x, float).ravel()
    med = np.median(x)
    return float(1.4826 * np.median(np.abs(x - med)))


def rect_mask(shape, rect) -> np.ndarray:
    x, y, w, h = [int(v) for v in rect]
    m = np.zeros(shape, bool)
    m[max(0, y):y + h, max(0, x):x + w] = True
    return m


def inset_mask(shape, margin=12) -> np.ndarray:
    m = np.zeros(shape, bool)
    m[margin:shape[0] - margin, margin:shape[1] - margin] = True
    return m


def central_mask(shape, r_max: float = 0.55) -> np.ndarray:
    """Pixels inside r_max of the corner radius - the low-vignetting middle."""
    h, w = shape
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float64)
    r = np.hypot(xx - (w - 1) / 2.0, yy - (h - 1) / 2.0) / math.hypot((w - 1) / 2.0,
                                                                     (h - 1) / 2.0)
    return r <= r_max


def bright_patch_mask(mean_img: np.ndarray, erode: int = 10) -> np.ndarray:
    """Largest bright connected region, eroded so no border pixel gets in.

    This is what finds the white patch on the black surround in the level
    ladder without the operator having to type coordinates.
    """
    hi, lo = np.percentile(mean_img, 99.0), np.percentile(mean_img, 5.0)
    thr = 0.5 * (hi + lo)
    m = mean_img > thr
    lab, n = ndimage.label(m)
    if n == 0:
        return inset_mask(mean_img.shape)
    sizes = ndimage.sum(m, lab, index=np.arange(1, n + 1))
    m = lab == (1 + int(np.argmax(sizes)))
    e = ndimage.binary_erosion(m, iterations=erode, border_value=0)
    return e if e.sum() > 400 else m


def detect_cfa(flat_mean: np.ndarray) -> dict:
    """Is this a Bayer (colour) deck? Compare the four 2x2 phase means.

    On a mono sensor the four phases differ only by noise (<0.5%). On an RGGB
    mosaic looking at anything but pure grey they differ by tens of percent.
    """
    ph = {}
    for dy in (0, 1):
        for dx in (0, 1):
            ph[(dy, dx)] = float(flat_mean[dy::2, dx::2].mean())
    vals = np.array(list(ph.values()))
    spread = float((vals.max() - vals.min()) / max(vals.mean(), 1e-6))
    return {"phase_means": {f"{k[0]}{k[1]}": round(v, 2) for k, v in ph.items()},
            "phase_spread": round(spread, 4), "bayer": bool(spread > 0.04)}


def fpn_var(mean_img, var_t_map, mask, n_frames, cfa=False) -> float:
    """Spatial variance of the fixed pattern in DN^2, temporal noise removed.

    The mean of N frames still carries temporal noise of var_t/N, and the
    high-pass keeps a known fraction of any iid field, so

        FPN_var = var(highpass(mean)) / HP_GAIN - var_t / N

    Dead pixels are rejected by sigma-clipping at 5 sigma before the variance is
    taken: a single stuck-at-255 pixel in a 60 DN field contributes 195^2 DN^2
    on its own and would swamp a 0.5 DN fixed pattern. Clipping a Gaussian at
    5 sigma throws away 6e-7 of it, so the bias that costs is nothing.

    With a Bayer deck each CFA phase is high-passed on its own subgrid, because
    the mosaic itself is per-pixel structure that is not sensor non-uniformity.
    """
    def one(img, vt, mk):
        hp = highpass(img)
        sel = mk & np.isfinite(hp)
        if sel.sum() < 200:
            return float("nan")
        v = hp[sel]
        for _ in range(3):
            s = robust_sigma(v)
            if s <= 0:
                break
            keep = np.abs(v - np.median(v)) < 5.0 * s
            if keep.all() or keep.sum() < 200:
                break
            v = v[keep]
        return float(np.var(v) / HP_GAIN - np.median(vt[sel]) / n_frames)

    if not cfa:
        return one(mean_img, var_t_map, mask)
    vals = [one(mean_img[dy::2, dx::2], var_t_map[dy::2, dx::2], mask[dy::2, dx::2])
            for dy in (0, 1) for dx in (0, 1)]
    vals = [v for v in vals if np.isfinite(v)]
    return float(np.median(vals)) if vals else float("nan")


def gain_from_noise(signal_dn: float, var_total_dn2: float) -> float:
    """Total gain implied by the temporal noise at a known signal level.

    camera_model's noise law, with S the signal in DN and g the total gain:

        var = S * g / 29 + (0.162 g)^2 + 1/12          (the last term is 8-bit
                                                        rounding, added here)

    which is a quadratic in g. Solving it rather than ignoring the shot term
    matters: in a dark frame with any pedestal at all the shot noise on the
    pedestal is a third of the variance, and dropping it throws the gain out by
    30%.
    """
    v = max(var_total_dn2 - QUANT_VAR, 0.0)
    a = READ_NOISE_DN_PER_GAIN ** 2
    b = max(signal_dn, 0.0) / E_PER_DN_1X
    if v <= 0:
        return 0.0
    return float((-b + math.sqrt(b * b + 4 * a * v)) / (2 * a))


# =============================================================================
# slanted edge -> line spread function width
# =============================================================================

def _edge_line(p: np.ndarray, win: float = 5.0):
    """Sub-pixel straight-line fit to a near-vertical edge in ``p``.

    Getting this right is the whole measurement. The obvious estimator - the
    centroid of |d/dx| along each row - is badly biased, because rectifying the
    noise gives every one of the ~100 flat pixels in the row a small positive
    weight that drags the centroid toward the row's middle. On a 40-frame
    average of a real preset that pulled the fitted tilt from 0.0875 to 0.054
    px/row, which smeared the projected edge by 2.7 px and tripled the measured
    blur. Two changes fix it:

      * the SIGNED derivative, whose noise is zero-mean and cancels;
      * a +-5 px window around the current estimate of the line, so the far
        field cannot contribute at all.

    Coarse start from argmax of the smoothed derivative, then iterate.
    """
    h, w = p.shape
    d = np.diff(p, axis=1)
    x = np.arange(d.shape[1], dtype=float) + 0.5
    sgn = 1.0 if d.sum() >= 0 else -1.0
    ds = sgn * d
    sm = np.apply_along_axis(
        lambda r: np.convolve(r, np.array([0.25, 0.5, 0.25]), "same"), 1, ds)
    pos = x[np.argmax(sm, axis=1)].astype(float)
    rows = np.arange(h, dtype=float)
    b, a = np.polyfit(rows, pos, 1)
    sel = np.ones(h, bool)
    for _ in range(4):
        cen = a + b * rows
        m = np.abs(x[None, :] - cen[:, None]) <= win
        den = (ds * m).sum(axis=1)
        pos_ok = den > 0.25 * max(np.median(den[den > 0]) if (den > 0).any() else 0.0, 1e-9)
        num = (ds * m * x[None, :]).sum(axis=1)
        pos = np.where(pos_ok, num / np.where(den == 0, 1.0, den), cen)
        sel = pos_ok.copy()
        for _ in range(2):
            if sel.sum() < 8:
                break
            b, a = np.polyfit(rows[sel], pos[sel], 1)
            r = pos - (a + b * rows)
            s = robust_sigma(r[sel]) or 1.0
            sel = pos_ok & (np.abs(r) < 3.0 * s)
        if sel.sum() >= 8:
            b, a = np.polyfit(rows[sel], pos[sel], 1)
    if sel.sum() < 8:
        return None
    rms = float(np.sqrt(np.mean((pos[sel] - (a + b * rows[sel])) ** 2)))
    return a, b, rms, int(sel.sum())


def lsf_variance(patch: np.ndarray) -> dict:
    """Second moment of the line spread function of one slanted edge, in px^2.

    Slanted-edge super-resolution, done by hand (there is no OpenCV in trainenv):

      1. decide whether the edge runs mostly vertically or horizontally and work
         across it;
      2. fit the edge to a straight line with ``_edge_line``;
      3. project every pixel onto the edge normal and bin at ESF_BIN px -> a
         super-resolved edge spread function;
      4. difference it -> the line spread function; take its second moment in a
         window re-sized from the width it just measured.

    The two box averages the binning introduces (one from binning, one from the
    difference) each add ESF_BIN^2/12 to the second moment; both are subtracted.
    A perfect step through a blur of variance v comes back as v.

    The LSF is deliberately NOT clamped at zero. Clamping looks tidy and
    rectifies the fixed-pattern noise into a positive pedestal that the x^2
    weighting then multiplies: with the himax_typical PRNU and DSNU that alone
    turned an injected 0.42 px^2 into 1.37.

    ``sigma_gauss_px`` is a second, independent estimate from a least-squares
    erf fit to the ESF. The two agreeing is the sign that the edge is clean;
    the moment is the one reported, because it makes no assumption about the
    shape of a real lens's blur.
    """
    p = np.asarray(patch, np.float64)
    gx = float(np.abs(np.diff(p, axis=1)).mean())
    gy = float(np.abs(np.diff(p, axis=0)).mean())
    transposed = gy > gx
    if transposed:
        p = p.T
    h, w = p.shape
    if w < 16 or h < 16:
        return {"ok": False, "why": "patch too small (need at least 16x16)"}

    line = _edge_line(p)
    if line is None:
        return {"ok": False, "why": "no edge found in the ROI"}
    a, b, line_rms, n_rows = line
    if not (0.005 < abs(b) < 0.7):
        return {"ok": False,
                "why": f"edge tilt {math.degrees(math.atan(b)):.1f} deg is outside "
                       "2-25 deg; a dead-straight or steeply tilted edge cannot be "
                       "super-resolved"}

    yy, xx = np.mgrid[0:h, 0:w].astype(np.float64)
    d = (xx - (a + b * yy)) / math.sqrt(1.0 + b * b)
    lim = min(6.0, 0.45 * w)
    keep = np.abs(d) <= lim
    edges = np.arange(-lim, lim + ESF_BIN, ESF_BIN)
    centres = 0.5 * (edges[:-1] + edges[1:])
    idx = np.digitize(d[keep], edges) - 1
    ok = (idx >= 0) & (idx < len(centres))
    cnt = np.bincount(idx[ok], minlength=len(centres))
    tot = np.bincount(idx[ok], weights=p[keep][ok], minlength=len(centres))
    full = cnt >= 3
    if full.sum() < 20:
        return {"ok": False, "why": "too few samples per bin; use a bigger ROI"}
    esf = np.interp(centres, centres[full], tot[full] / cnt[full])

    lsf = np.diff(esf) / ESF_BIN
    x = 0.5 * (centres[:-1] + centres[1:])
    if lsf.sum() < 0:
        lsf = -lsf
    k = max(3, len(lsf) // 8)
    lsf = lsf - np.median(np.concatenate([lsf[:k], lsf[-k:]]))
    if lsf.sum() <= 0:
        return {"ok": False, "why": "flat edge profile"}

    c = float((lsf * x).sum() / lsf.sum())
    var = float("nan")
    win = 3.0
    for i in range(4):
        s = np.abs(x - c) <= win
        if lsf[s].sum() <= 0:
            break
        c = float((lsf[s] * x[s]).sum() / lsf[s].sum())
        var = float((lsf[s] * (x[s] - c) ** 2).sum() / lsf[s].sum())
        win = min(lim - ESF_BIN, max(2.5, 3.5 * math.sqrt(max(var, 1e-3))))
    var_corr = var - 2.0 * (ESF_BIN ** 2) / 12.0

    # independent cross-check: the best-fit Gaussian edge
    from scipy import special
    lo, hi = float(np.median(esf[:15])), float(np.median(esf[-15:]))
    try:
        sol = optimize.least_squares(
            lambda q: q[0] + q[1] * special.erf((centres - q[2]) / (q[3] * math.sqrt(2))) - esf,
            [0.5 * (lo + hi), 0.5 * (hi - lo), 0.0, 0.7],
            bounds=([-1e4, -1e4, -3.0, 0.05], [1e4, 1e4, 3.0, 6.0]))
        sigma_gauss = float(sol.x[3])
        erf_rms = float(np.sqrt(np.mean(sol.fun ** 2)))
    except Exception:
        sigma_gauss, erf_rms = float("nan"), float("nan")

    return {"ok": True, "var_px2": var_corr, "sigma_px": math.sqrt(max(var_corr, 0.0)),
            "sigma_gauss_px": sigma_gauss, "erf_fit_rms_dn": erf_rms,
            "angle_deg": math.degrees(math.atan(b)), "edge_line_rms_px": line_rms,
            "contrast_dn": float(esf.max() - esf.min()),
            "n_bins": int(full.sum()), "n_rows": n_rows, "transposed": transposed}


def gauss_kernel_var(sigma: float) -> float:
    """Second moment of camera_model._gauss_kernel(sigma) - sampled, not ideal.

    camera_model builds a Gaussian on the integer pixel grid truncated at
    ceil(3*sigma). Below sigma ~0.7 the sampled kernel's variance is far below
    sigma^2 (at 0.3 it is 0.008, not 0.09), so inverting a measured LSF width
    into the parameter to type into the preset has to go through this function,
    not through a square root.
    """
    if sigma <= 0:
        return 0.0
    r = max(1, int(math.ceil(3.0 * sigma)))
    x = np.arange(-r, r + 1, dtype=np.float64)
    k = np.exp(-0.5 * (x / sigma) ** 2)
    k /= k.sum()
    return float((k * x * x).sum())


def sigma_for_kernel_var(target_var: float) -> float:
    """Invert gauss_kernel_var: the preset value that reproduces a measured width."""
    if target_var <= 1e-6:
        return 0.0
    lo, hi = 1e-3, 6.0
    if gauss_kernel_var(hi) < target_var:
        return hi
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        if gauss_kernel_var(mid) < target_var:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


# =============================================================================
# the measurements
# =============================================================================

def measure_dark(clip: Clip) -> dict:
    """Lens-capped frames -> dark offset, DSNU, read noise, and the gain the AE
    ran at while it was dark.

    In the dark the AE cannot reach its 60 DN target, so it winds integration to
    the 340-line ceiling and then gain to the ceiling; camera_model's own AE
    lands on total gain 24x there. That is the only operating point where DSNU
    (0.4 DN at 1x) and read noise (0.162 DN at 1x) rise above the 8-bit
    quantisation floor at all, which is why the dark frame is worth taking.

        var_temporal = (0.162 * g)^2 + 1/12       -> g
        DSNU(1x)     = sqrt(FPN_var) / g
    """
    f, mean = clip.f, clip.mean_frame
    mask = inset_mask(mean.shape, 12)
    vt = temporal_var_map(f, mask)
    var_t = float(np.median(vt[mask]))
    frac0 = float((clip.u8 == 0).mean())
    frac255 = float((clip.u8 == 255).mean())
    out = {"n_frames": clip.n, "mean_dn": round(float(mean[mask].mean()), 3),
           "frac_at_0": round(frac0, 4), "frac_at_255": round(frac255, 6),
           "temporal_sigma_dn": round(math.sqrt(max(var_t, 0)), 3)}

    level = float(mean[mask].mean())
    g = gain_from_noise(level, var_t)
    out["implied_total_gain"] = round(g, 2)
    if frac0 > 0.05:
        out["implied_total_gain_note"] = (
            f"unreliable: {frac0:.0%} of the frame is clipped at 0 DN, which shrinks "
            "the measured temporal variance and so under-reads the gain")
    fv = fpn_var(mean, vt, mask, clip.n)
    out["dsnu_at_this_gain_dn"] = round(math.sqrt(max(fv, 0.0)), 3)
    if frac0 > 0.20:
        out["dsnu_sigma_dn"] = None
        out["note"] = (f"{frac0:.0%} of dark pixels sit at 0 DN: the offset is clipped "
                       "and DSNU cannot be read out of this clip. Report as unmeasured.")
    elif g < 1.5:
        out["dsnu_sigma_dn"] = None
        out["note"] = ("dark temporal noise is at the quantisation floor, so the gain "
                       "the AE ran at is unknown and DSNU cannot be referred to 1x.")
    else:
        out["dsnu_sigma_dn"] = round(math.sqrt(max(fv, 0.0)) / g, 4)
        out["note"] = ("DSNU referred to 1x by dividing by the implied gain; that "
                       "assumes DSNU scales with gain, as camera_model assumes.")
    return out


def measure_flat(clip: Clip, roll180: Clip | None, dark_mean: np.ndarray | None,
                 dsnu_1x: float | None) -> dict:
    """Flat field -> vignetting, PRNU, dead pixels, and the noise at 60 DN.

    Vignetting is fitted as camera_model writes it, 1 - a2 r^2 - a4 r^4 with
    r = 1 at the frame corner, with a free scale because the AE has already
    normalised the level:

        F(r) ~ c0 + c1 r^2 + c2 r^4      a2 = -c1/c0      a4 = -c2/c0
    """
    # The dark frame is NOT subtracted: the AE ran it at its gain ceiling, so its
    # offset belongs to a different operating point and subtracting it would add
    # noise and bias rather than remove a pedestal.
    mean = clip.mean_frame.copy()
    h, w = mean.shape
    cfa = detect_cfa(mean)
    mask = inset_mask((h, w), 12)
    vt = temporal_var_map(clip.f, mask)
    var_t = float(np.median(vt[mask]))
    level = float(np.median(mean[mask]))

    # --- dead pixels ------------------------------------------------------
    # On a Bayer deck the local median has to be taken within each CFA phase:
    # comparing a red photosite against its green neighbours makes every pixel
    # on the sensor look defective (it flagged 8.5% of them before this).
    if cfa["bayer"]:
        med = np.empty_like(mean)
        for dy in (0, 1):
            for dx in (0, 1):
                med[dy::2, dx::2] = ndimage.median_filter(
                    mean[dy::2, dx::2], size=5, mode="nearest")
    else:
        med = ndimage.median_filter(mean, size=5, mode="nearest")
    dev = mean - med
    s = robust_sigma(dev[mask]) or 1.0
    thr = max(8.0 * s, 10.0)
    defect = (np.abs(dev) > thr) & mask
    lab, n_cl = ndimage.label(defect, structure=np.ones((3, 3)))
    n_px = int(defect.sum())
    area = int(mask.sum())          # the border inset is not searched, so the
    dead = {"defect_pixels": n_px, "defect_clusters": int(n_cl),   # rate uses
            "searched_px": area,                                   # what was
            "defect_px_fraction": round(n_px / area, 8),           # searched
            "dead_px_frac": round(n_cl / area, 8),
            "threshold_dn": round(thr, 2),
            "note": ("dead_px_frac is in camera_model's own convention: clusters per "
                     "pixel, since it injects one 2x2 cluster per dead_px_frac*H*W.")}

    # --- vignetting -------------------------------------------------------
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float64)
    r = np.hypot(xx - (w - 1) / 2.0, yy - (h - 1) / 2.0) / math.hypot((w - 1) / 2.0,
                                                                     (h - 1) / 2.0)
    field = mean.copy()
    used_roll = False
    if roll180 is not None and roll180.mean_frame.shape == mean.shape:
        # rolling the camera 180 deg rotates the scene on the sensor but leaves
        # the lens falloff where it is, so averaging cancels odd illumination
        field = 0.5 * (mean + np.rot90(roll180.mean_frame, 2))
        used_roll = True
    if cfa["bayer"]:
        # A mosaic is a huge fixed per-pixel pattern that has nothing to do with
        # the lens. Normalising each CFA phase by its own mean removes it and
        # leaves the shading, at full resolution.
        for dy in (0, 1):
            for dx in (0, 1):
                sub = field[dy::2, dx::2]
                mu = float(np.median(sub[mask[dy::2, dx::2]]))
                if mu > 1e-6:
                    field[dy::2, dx::2] = sub / mu
    fit_ok = mask & ~defect & (field > (0.02 if cfa["bayer"] else 3)) & \
        (field < (20.0 if cfa["bayer"] else 250))
    A = np.stack([np.ones(fit_ok.sum()), r[fit_ok] ** 2, r[fit_ok] ** 4], axis=1)
    coef, *_ = np.linalg.lstsq(A, field[fit_ok], rcond=None)
    c0, c1, c2 = [float(v) for v in coef]
    a2, a4 = -c1 / c0, -c2 / c0
    resid = field[fit_ok] - A @ coef
    vig = {"vignette_a2": round(a2, 4), "vignette_a4": round(a4, 4),
           "fit_rms_relative": round(float(np.sqrt(np.mean(resid ** 2)) / abs(c0)), 5),
           "relative_at_h_edge": round(1 - a2 * (0.799 ** 2) - a4 * (0.799 ** 4), 3),
           "relative_at_corner": round(1 - a2 - a4, 3),
           "roll180_used": used_roll}

    # --- PRNU -------------------------------------------------------------
    prnu_mask = mask & ~ndimage.binary_dilation(defect, iterations=2)
    fv = fpn_var(mean, vt, prnu_mask, clip.n, cfa=cfa["bayer"])
    gain_here = gain_from_noise(level, var_t)
    dsnu_term = (dsnu_1x * max(gain_here, 1.0)) ** 2 if dsnu_1x else 0.0
    prnu = math.sqrt(max(fv - dsnu_term, 0.0)) / max(level, 1e-6)
    noise = {"level_dn": round(level, 2), "temporal_sigma_dn": round(math.sqrt(max(var_t, 0)), 3),
             "implied_total_gain": round(gain_here, 2),
             "shot_slope_k_dn_per_dn": round(max(var_t - QUANT_VAR, 0.0) / max(level, 1e-6), 5),
             "e_per_dn_here": round(max(level, 1e-6) / max(var_t - QUANT_VAR, 1e-6), 2)}
    return {"n_frames": clip.n, "cfa": cfa, "vignetting": vig,
            "prnu_sigma": round(prnu, 5),
            "prnu_fpn_sigma_dn": round(math.sqrt(max(fv, 0.0)), 3),
            "prnu_dsnu_subtracted": bool(dsnu_1x),
            "dead": dead, "noise": noise}


def measure_ladder(clips: list[Clip], session_rois: dict | None) -> dict:
    """Photon transfer + fixed-pattern transfer over several signal levels.

    Each folder is the same flat patch at a different fraction of the frame, so
    the sensor's own auto-exposure - which always drives the frame mean to
    60 DN - parks the patch at a different DN. Over the patch:

        temporal:  var_t(S) = S * g / 29 + (0.162 g)^2 + 1/12
                   slope  -> e-/DN at this gain = 1/slope
                   offset -> read noise, and hence the gain g
        spatial :  var_fpn(S) = prnu^2 * S^2 + (dsnu * g)^2
                   fit against S^2 -> PRNU and DSNU at the same gain

    Doing PRNU and DSNU this way needs no dark frame and no assumption that
    DSNU scales with gain, which is what makes it the primary estimator.
    """
    pts = []
    for c in clips:
        mean = c.mean_frame
        rect = (session_rois or {}).get(c.dir.name)
        mask = rect_mask(mean.shape, rect) if rect else bright_patch_mask(mean)
        mask &= inset_mask(mean.shape, 12)
        if not rect:
            # Keep every level's ROI to the same central part of the frame.
            # Otherwise the big low-level patch reaches into the vignetted
            # corners, where the high-pass leaves more residual than it does
            # in the middle - which lands entirely on the fixed-pattern
            # intercept, i.e. straight onto DSNU.
            mask &= central_mask(mean.shape, 0.55)
        if mask.sum() < 500:
            print(f"  ! {c.dir.name}: patch ROI has only {int(mask.sum())} px, skipped")
            continue
        vt = temporal_var_map(c.f, mask)
        cfa = detect_cfa(mean)["bayer"]
        S = float(np.median(mean[mask]))
        var_t = float(np.median(vt[mask]))
        fv = fpn_var(mean, vt, mask, c.n, cfa=cfa)
        pts.append({"dir": c.dir.name, "n_frames": c.n, "roi_px": int(mask.sum()),
                    "signal_dn": round(S, 2), "var_temporal_dn2": round(var_t, 4),
                    "var_fpn_dn2": round(fv, 4),
                    "saturated_frac": round(float((c.u8[:, mask] >= 254).mean()), 4)})
    out = {"levels": pts}
    if len(pts) < 3:
        out["note"] = "need at least 3 levels for the transfer fits"
        return out

    S = np.array([p["signal_dn"] for p in pts])
    vt = np.array([p["var_temporal_dn2"] for p in pts])
    vf = np.array([p["var_fpn_dn2"] for p in pts])

    # A clipped level carries no photon-transfer information at all (its
    # temporal variance collapses to zero), so it must not enter the fits.
    unsat = np.array([p["saturated_frac"] < 0.01 and p["signal_dn"] < 245 for p in pts])
    out["levels_used"] = [p["dir"] for p, u in zip(pts, unsat) if u]
    out["levels_dropped_saturated"] = [p["dir"] for p, u in zip(pts, unsat) if not u]
    if unsat.sum() < 3:
        out["note"] = (f"only {int(unsat.sum())} unsaturated levels; the transfer fits "
                       "need 3. Re-shoot with the patch covering more of the frame so "
                       "the auto-exposure parks it lower.")
        return out
    S, vt, vf = S[unsat], vt[unsat], vf[unsat]
    coef, cov = np.polyfit(S, vt, 1, cov=True)
    slope, intercept = float(coef[0]), float(coef[1])
    se = float(math.sqrt(max(cov[1, 1], 0.0)))          # 1 sigma on the intercept
    read_var = intercept - QUANT_VAR
    hi_var = intercept + 2 * se - QUANT_VAR
    # At 1x gain the model's own read noise is 0.162 DN = 0.026 DN^2, a third of
    # the 1/12 DN^2 that 8-bit rounding contributes: it is BELOW the
    # quantisation floor and cannot be measured. Saying so, and falling back on
    # g = 1 with an upper bound, is the honest reading of a small intercept -
    # inverting the noise formula through it would give a number with no
    # information in it.
    floor_limited = read_var <= 2 * se or read_var <= 0
    g = 1.0 if floor_limited else math.sqrt(read_var) / READ_NOISE_DN_PER_GAIN
    g_upper = math.sqrt(max(hi_var, 0.0)) / READ_NOISE_DN_PER_GAIN
    out["photon_transfer"] = {
        "slope_dn2_per_dn": round(slope, 5),
        "e_per_dn_at_operating_gain": round(1.0 / slope, 2) if slope > 0 else None,
        "intercept_dn2": round(intercept, 4),
        "intercept_se_dn2": round(se, 4),
        "read_noise_dn": round(math.sqrt(max(read_var, 0.0)), 3),
        "gain_from_read_noise": "below the quantisation floor" if floor_limited
                                else round(g, 2),
        "implied_total_gain": round(g, 2),
        "total_gain_upper_bound": round(g_upper, 2),
        "e_per_dn_1x": round(g / slope, 2) if slope > 0 else None,
        "r2": round(float(_r2(S, vt, slope, intercept)), 4),
        "note": ("intercept minus 1/12 is the read noise. When that is inside the "
                 "fit's own error bar the gain cannot be read from it, so 1x is "
                 "assumed and an upper bound reported - which is sound exactly when "
                 "the room was bright enough that the AE never reached for gain, and "
                 "the small intercept is itself the evidence that it did not."),
    }
    sl2, ic2 = np.polyfit(S ** 2, vf, 1)
    out["fpn_transfer"] = {
        "prnu_sigma": round(math.sqrt(max(float(sl2), 0.0)), 5),
        "dsnu_at_this_gain_dn": round(math.sqrt(max(float(ic2), 0.0)), 3),
        "dsnu_sigma_dn": (round(math.sqrt(max(float(ic2), 0.0)) / g, 4)
                          if np.isfinite(g) and g > 1e-6 else None),
        "r2": round(float(_r2(S ** 2, vf, sl2, ic2)), 4),
        "note": ("dsnu_sigma_dn is the DN at 1x: the fitted DSNU divided by the gain "
                 "above. If that gain was floor-limited to 1x, the two are the same "
                 "number and the result is only as good as 'the room was bright'."),
    }
    return out


def _r2(x, y, slope, intercept) -> float:
    pred = slope * np.asarray(x) + intercept
    ss = np.sum((np.asarray(y) - pred) ** 2)
    tot = np.sum((np.asarray(y) - np.mean(y)) ** 2)
    return 1.0 - ss / tot if tot > 0 else float("nan")


def grid_rois(shape, size: int = 72, nx: int = 5, ny: int = 4, margin: int = 4) -> list:
    """A lattice of candidate ROIs covering the frame, corners included."""
    h, w = shape
    xs = np.linspace(margin, w - size - margin, nx)
    ys = np.linspace(margin, h - size - margin, ny)
    return [[int(x), int(y), size, size] for y in ys for x in xs]


def measure_edges(clips: list[Clip], rois: list | None) -> dict:
    """Slanted-edge chart -> PSF sigma at the frame centre and in the corners.

    With no ROIs given, a 5x4 lattice of 72 px windows is swept and every window
    that actually contains one clean, properly tilted edge is kept. That is what
    lets the operator simply aim the drone - edge through the middle, then edge
    through a corner - without reading pixel coordinates off a screen in a lab
    with a queue behind them. Every ``edge*`` folder is pooled, so the corner
    clips are just more aim points.
    """
    mean = clips[0].mean_frame
    h, w = mean.shape
    auto = not rois
    r_corner = math.hypot((w - 1) / 2.0, (h - 1) / 2.0)
    res = []
    n_scanned = 0
    for clip in clips:
        cmean = clip.mean_frame
        use = rois or grid_rois(cmean.shape)
        for rect in use:
            x, y, rw, rh = [int(v) for v in rect]
            n_scanned += 1
            m = lsf_variance(cmean[y:y + rh, x:x + rw])
            cx, cy = x + rw / 2.0, y + rh / 2.0
            rn = math.hypot(cx - (w - 1) / 2.0, cy - (h - 1) / 2.0) / r_corner
            item = {"clip": clip.dir.name, "roi": [x, y, rw, rh], "r_norm": round(rn, 3)}
            item.update({k: (round(v, 4) if isinstance(v, float) else v)
                         for k, v in m.items()})
            if m.get("ok"):
                # An auto window may straddle two edges or clip one at its border;
                # both show up as a bad straight-line fit or feeble contrast.
                if auto and (m["contrast_dn"] < 25.0 or m["edge_line_rms_px"] > 1.0):
                    continue
                item["preset_sigma_px"] = round(sigma_for_kernel_var(m["var_px2"]), 4)
                item["sigma_lens_only_px"] = round(
                    math.sqrt(max(m["var_px2"] - QUANT_VAR * 1.0, 0.0)), 4)
            elif auto:
                continue                       # a window with no edge is not news
            res.append(item)
    good = [r for r in res if r.get("ok")]
    out = {"n_frames": sum(c.n for c in clips), "clips": [c.dir.name for c in clips],
           "auto_roi": auto, "rois_scanned": n_scanned, "edges": res}
    if good:
        # Pool by radius rather than trusting one window: a lattice scan finds
        # several edges in each band and their median is far steadier than any
        # single one.
        centre = [r for r in good if r["r_norm"] <= 0.30] or [min(good, key=lambda r: r["r_norm"])]
        corner = [r for r in good if r["r_norm"] >= 0.60]
        out["psf_sigma_center_px"] = round(
            float(np.median([r["preset_sigma_px"] for r in centre])), 4)
        out["center_r_norm"] = round(float(np.median([r["r_norm"] for r in centre])), 3)
        out["center_n_edges"] = len(centre)
        out["center_var_px2"] = float(np.median([r["var_px2"] for r in centre]))
        if corner:
            out["psf_sigma_corner_px"] = round(
                float(np.median([r["preset_sigma_px"] for r in corner])), 4)
            out["corner_r_norm"] = round(float(np.median([r["r_norm"] for r in corner])), 3)
            out["corner_n_edges"] = len(corner)
        else:
            out["psf_sigma_corner_px"] = None
            out["corner_note"] = ("no edge found beyond r = 0.60; take another clip "
                                  "with the chart's edge running through a frame "
                                  "corner (folder edge_corner_a/)")
    return out


def measure_fov(clip: Clip, cfg: dict) -> dict:
    """Bar target of known pitch at a known distance -> focal length and HFOV.

    A flat target square to the lens maps linearly under a pinhole, so the
    scale is read straight off a line fit and the departure from that line is
    the lens's distortion (plus any target skew, which is fitted separately so
    the two do not get confused):

        x_j = cx + f * (X_j cos(psi)) / (D + X_j sin(psi)),  X_j = (j - j0) * P
        then  x -> cx + (x - cx) * (1 + k1 * ((x - cx)/r_corner)^2)
        full HFOV = 2 * atan((W/2) / f)
    """
    pitch = cfg.get("edge_pitch_m")
    sep = cfg.get("marks_separation_m")
    dist = cfg.get("distance_m")
    if not dist or not (pitch or sep):
        return {"skipped": "session.json needs fov.distance_m plus either "
                           "fov.marks_separation_m (two tape marks) or "
                           "fov.edge_pitch_m (printed bar sheet)"}
    mean = clip.mean_frame
    h, w = mean.shape
    band = cfg.get("row_band") or [int(h * 0.40), int(h * 0.60)]
    prof = mean[band[0]:band[1], :].mean(axis=0)
    prof = np.convolve(prof, np.array([0.25, 0.5, 0.25]), mode="same")
    g = np.diff(prof)
    amp = np.percentile(np.abs(g), 98)
    thr = max(0.35 * amp, 1.5)
    xs = []
    i = 1
    while i < len(g) - 1:
        if abs(g[i]) >= thr and abs(g[i]) >= abs(g[i - 1]) and abs(g[i]) > abs(g[i + 1]):
            lo, hi = max(0, i - 2), min(len(g), i + 3)
            wgt = np.abs(g[lo:hi])
            if wgt.sum() > 0 and np.all(np.sign(g[lo:hi][wgt > 0.2 * amp]) == np.sign(g[i])):
                xs.append(float((np.arange(lo, hi) * wgt).sum() / wgt.sum()) + 0.5)
                i += 3
                continue
        i += 1
    xs = np.array(sorted(xs))

    # --- two tape marks of known separation --------------------------------
    if sep:
        if len(xs) < 4:
            return {"skipped": f"only {len(xs)} edges found; the two marks should give "
                               "4 (two per strip). Check contrast and framing.",
                    "edges_px": [round(v, 2) for v in xs]}
        gaps = np.diff(xs)
        k = int(np.argmax(gaps)) + 1                 # split at the widest gap
        left, right = xs[:k], xs[k:]
        if len(left) < 2 or len(right) < 2:
            return {"skipped": "could not split the edges into two marks",
                    "edges_px": [round(v, 2) for v in xs]}
        c_l, c_r = float(left.mean()), float(right.mean())
        span = abs(c_r - c_l)
        scale = span / sep
        f = scale * dist
        return {"n_frames": clip.n, "mode": "marks", "n_edges": int(len(xs)),
                "mark_centres_px": [round(c_l, 2), round(c_r, 2)],
                "mark_widths_px": [round(float(left.max() - left.min()), 2),
                                   round(float(right.max() - right.min()), 2)],
                "span_px": round(span, 2), "scale_px_per_m": round(scale, 2),
                "focal_px_per_rad": round(f, 2),
                "full_hfov_deg": round(2 * math.degrees(math.atan((w / 2.0) / f)), 2),
                "full_vfov_deg": round(2 * math.degrees(math.atan((h / 2.0) / f)), 2),
                "distance_m": dist,
                "note": ("single-distance focal length: it inherits whatever error is in "
                         "distance_m, including the unknown offset from the tripod "
                         "reference to the lens's entrance pupil. Add a fov_far/ clip at "
                         "a second distance to cancel that.")}

    # --- printed bar sheet of known pitch ----------------------------------
    if len(xs) < 6:
        return {"skipped": f"only {len(xs)} bar edges found; check framing and contrast",
                "edges_px": [round(v, 2) for v in xs]}
    cx = (w - 1) / 2.0
    j = np.arange(len(xs), dtype=float)
    use_k1 = bool(cfg.get("fit_k1", len(xs) >= 16))

    def model(p):
        f, j0, psi = p[0], p[1], p[2]
        k1 = p[3] if use_k1 else 0.0
        X = (j - j0) * pitch
        xi = f * (X * math.cos(psi)) / (dist + X * math.sin(psi))
        rn = xi / math.hypot((w - 1) / 2.0, (h - 1) / 2.0)
        return cx + xi * (1.0 + k1 * rn ** 2)

    p0 = [abs((xs[-1] - xs[0]) / (len(xs) - 1)) * dist / pitch, len(xs) / 2.0, 0.0]
    if use_k1:
        p0.append(0.0)
    sol = optimize.least_squares(lambda p: model(p) - xs, p0,
                                 bounds=([50, -1e3, -0.6, -2.0][:len(p0)],
                                         [600, 1e3, 0.6, 2.0][:len(p0)]))
    f = float(sol.x[0])
    resid = model(sol.x) - xs
    lin_slope = np.polyfit(j, xs, 1)[0]
    out = {"n_frames": clip.n, "mode": "bars", "n_edges": int(len(xs)),
           "focal_px_per_rad": round(f, 2),
           "scale_px_per_m": round(float(abs(lin_slope) / pitch), 2),
           "distance_m": dist,
           "full_hfov_deg": round(2 * math.degrees(math.atan((w / 2.0) / f)), 2),
           "full_vfov_deg": round(2 * math.degrees(math.atan((h / 2.0) / f)), 2),
           "focal_px_per_rad_linear": round(float(abs(lin_slope) * dist / pitch), 2),
           "target_skew_deg": round(math.degrees(float(sol.x[2])), 2),
           "k1_forward": round(float(sol.x[3]), 4) if use_k1 else None,
           "fit_rms_px": round(float(np.sqrt(np.mean(resid ** 2))), 3),
           "fit_max_px": round(float(np.max(np.abs(resid))), 3),
           "note": ("k1_forward maps ideal -> observed. camera_model's k1 is the "
                    "sampling-side coefficient, approximately its negative.")}
    return out


def measure_ae_step(clip: Clip) -> dict:
    """A step change in scene light -> the AE loop's damping factor.

    camera_model multiplies exposure by (target/measured)^frac once per camera
    frame, with frac = 1 - (1-d)^n over the n sensor frames that elapsed. In log
    terms the residual u = ln(mean / 60) just decays geometrically:

        u_{k+1} = (1 - d)^n u_k       ->      slope of ln|u| vs time = ln(1-d)/16.59 ms
        d = 1 - exp(slope * SENSOR_FRAME_S)

    Only frames outside the +-5 DN converge deadband and away from clipping can
    be used, which on a 10-15 fps WiFi stream is 2-4 frames per step - hence
    several steps, and a wide error bar.
    """
    means = clip.f.reshape(clip.n, -1).mean(axis=1)
    t = clip.t - clip.t[0]
    dt_med = float(np.median(np.diff(t))) if clip.n > 2 else SENSOR_FRAME_S
    n_sensor = max(1, int(round(dt_med / SENSOR_FRAME_S)))
    u = np.log(np.maximum(means, 1.0) / AE_TARGET_DN)
    # The loop latches "converged" once the error is inside CONVERGE_IN (3 DN)
    # and then stops correcting, so a point below that flattens the tail and
    # biases the decay rate low. Stay clear of it: 0.06 in log terms is 3.7 DN.
    U_MIN = 0.06
    steps = []
    # a step is a frame where |u| jumps up; take each such frame as a start
    jumps = np.where((np.abs(u[1:]) > np.abs(u[:-1]) + 0.25) &
                     (np.abs(u[1:]) > 0.25))[0] + 1
    for s in jumps:
        seq_t, seq_u = [], []
        for k in range(s, min(len(u), s + 12)):
            if abs(u[k]) < U_MIN:
                break
            if means[k] >= 250 or means[k] <= 3:
                break            # clipped: the log model does not hold
            if seq_u and abs(u[k]) > abs(seq_u[-1]):
                break            # not decaying any more: next step started
            seq_t.append(t[k]); seq_u.append(u[k])
        if len(seq_u) >= 3:
            sl, ic = np.polyfit(np.array(seq_t) - seq_t[0], np.log(np.abs(seq_u)), 1)
            if sl < 0:
                # per captured frame the residual shrinks by (1-d)^n_sensor, so
                # undo the number of sensor frames that fit in one camera frame
                # instead of assuming one; that removes the rounding bias the
                # model's own round(dt / 16.59 ms) introduces.
                ratio = math.exp(float(sl) * dt_med)
                d = 1.0 - ratio ** (1.0 / n_sensor)
                steps.append({"start_frame": int(s), "n_points": len(seq_u),
                              "u0": round(float(seq_u[0]), 3),
                              "decay_per_s": round(float(sl), 3),
                              "ae_damping": round(d, 4)})
    out = {"n_frames": clip.n, "fps": round(clip.fps() or 0.0, 2),
           "dt_median_s": round(dt_med, 4), "sensor_frames_per_capture": n_sensor,
           "steps_found": len(steps), "steps": steps}
    if steps:
        vals = np.array([s["ae_damping"] for s in steps])
        out["ae_damping"] = round(float(np.median(vals)), 4)
        out["ae_damping_spread"] = round(float(vals.max() - vals.min()), 4)
    else:
        out["note"] = ("no usable step found: make the step bigger (a white card "
                       "swept off the lens is about 10x) and capture at the highest "
                       "frame rate the link gives.")
    return out


def measure_banding(clip: Clip) -> dict:
    """Row banding from mains-driven light -> banding_depth, and its period.

    Flicker avoidance is off on this sensor (FS_CTRL = 0x00), so 120 Hz light
    and the rolling shutter make a row-wise ripple whose phase is random frame
    to frame. Averaging the frames therefore leaves a ripple-free reference; the
    per-frame ratio to it is the ripple:

        rho_k(y) = rowmean_k(y) / mean_k rowmean_k(y) - 1
        fit rho = A cos(2 pi y / P + phi) + c + m y   -> depth = median_k A_k

    The same fit at a period nothing is happening at is reported as a control,
    and a sweep over P says whether the ripple really sits at the predicted
    268 rows.
    """
    rows = clip.f.mean(axis=2)                    # (N, H)
    ref = rows.mean(axis=0)
    ok = ref > 5
    y = np.arange(clip.h, dtype=float)
    rho = rows[:, ok] / ref[ok] - 1.0
    yy = y[ok]

    # project out offset and ramp once, so the period sweep below is a clean
    # periodogram of what is left
    T = np.stack([np.ones_like(yy), yy], axis=1)
    rho_r = rho.T - T @ np.linalg.lstsq(T, rho.T, rcond=None)[0]
    ss_tot = float((rho_r ** 2).sum())

    def amps(period):
        B = np.stack([np.cos(2 * math.pi * yy / period),
                      np.sin(2 * math.pi * yy / period)], axis=1)
        B = B - T @ np.linalg.lstsq(T, B, rcond=None)[0]
        coef, *_ = np.linalg.lstsq(B, rho_r, rcond=None)
        return np.hypot(coef[0], coef[1]), float(((B @ coef) ** 2).sum())

    a_model, _ = amps(BANDING_PERIOD_ROWS)
    a_ctrl, _ = amps(37.0)
    # Only 244 rows are available, so the AMPLITUDE at a long period runs away
    # (a 268-row ripple is fitted by a 600-row one with a bigger amplitude).
    # Sweeping on variance EXPLAINED instead of amplitude has no such bias and
    # peaks where the ripple really is.
    periods = np.arange(60.0, 700.0, 4.0)
    sweep = np.array([amps(p)[1] / max(ss_tot, 1e-30) for p in periods])
    best = float(periods[int(np.argmax(sweep))])
    depth = float(np.median(a_model))
    return {"n_frames": clip.n,
            "banding_depth": round(depth, 4),
            "control_depth_at_37_rows": round(float(np.median(a_ctrl)), 4),
            "best_fit_period_rows": best,
            "variance_explained_at_best": round(float(sweep.max()), 4),
            "variance_explained_at_268": round(
                float(amps(BANDING_PERIOD_ROWS)[1] / max(ss_tot, 1e-30)), 4),
            "predicted_period_rows": BANDING_PERIOD_ROWS,
            "period_note": ("the frame holds only 0.91 of a 268-row cycle, so the "
                            "period is weakly determined; the sweep is a sanity "
                            "check, not a measurement of the mains frequency."),
            "note": ("depth at or below the control value means no banding in this "
                     "room - modern DC-driven LED fixtures do not flicker. That is a "
                     "result, not a failure: set banding_depth = 0 for that room.")}


def measure_lux(entries: list[tuple[float, Clip]], render_mean_dn: float) -> dict:
    """Light level vs the total gain the AE settles at -> the scene_light anchor.

    scene_light is a simulator knob, not a sensor property, so it cannot be
    measured directly. What can be measured is the thing it has to reproduce:
    how much gain the real AE reaches for at a given room brightness. The gain
    follows from the noise, since shot noise in DN grows with gain - see
    ``gain_from_noise`` - and the simulator's own AE gives, for a render whose
    mean is R DN,

        scene_light = 60 / (R * g)          (60 DN is AE_TARGET_MEAN)

    With the default R = 165 DN this is 0.364/g, which puts the himax_low_light
    preset's 0.045 at g = 8.1 - the ~8x the preset is specified by.
    """
    rows = []
    for lux, c in entries:
        mean = c.mean_frame
        mask = inset_mask(mean.shape, 16)
        vt = temporal_var_map(c.f, mask)
        S = float(np.median(mean[mask]))
        var_t = float(np.median(vt[mask]))
        g = gain_from_noise(S, var_t)
        rows.append({"dir": c.dir.name, "lux": lux, "signal_dn": round(S, 2),
                     "temporal_sigma_dn": round(math.sqrt(max(var_t, 0)), 3),
                     "total_gain": round(g, 2),
                     "scene_light": round(AE_TARGET_DN / (render_mean_dn * max(g, 1e-6)), 4)
                     if g > 0 else None})
    return {"render_mean_dn": render_mean_dn, "levels": rows,
            "note": ("phone lux meters are uncalibrated to roughly +-30%; the ratios "
                     "between levels are far more trustworthy than the absolute lux.")}


def measure_blur(clip: Clip, cfg: dict, static_var: float | None) -> dict:
    """A feature moving at a known image speed -> the effective exposure time.

    The moving edge is the static edge smeared by a box of length L px:

        var_moving - var_static = L^2/12          (real sensor: the pixel
                                                   aperture is in both terms)
        t_exp = L / v_image
    """
    v = cfg.get("px_per_s")
    if not v:
        return {"skipped": "session.json needs blur.px_per_s"}
    if static_var is None:
        return {"skipped": "needs a static edge/ folder to subtract"}
    rois = cfg.get("rois")
    mean = clip.mean_frame
    if not rois:
        s = min(mean.shape) // 3
        rois = [[(mean.shape[1] - s) // 2, (mean.shape[0] - s) // 2, s, s]]
    res = []
    for rect in rois:
        x, y, rw, rh = [int(q) for q in rect]
        m = lsf_variance(mean[y:y + rh, x:x + rw])
        if not m.get("ok"):
            res.append({"roi": rect, **m})
            continue
        d = m["var_px2"] - static_var
        L = math.sqrt(max(12.0 * d, 0.0))
        L_box = math.sqrt(max(12.0 * d - 1.0, 0.0))
        res.append({"roi": rect, "var_px2": round(m["var_px2"], 4),
                    "delta_var_px2": round(d, 4),
                    "smear_px": round(L, 3), "smear_px_model_kernel": round(L_box, 3),
                    "exposure_time_ms": round(1e3 * L / v, 3),
                    "exposure_time_ms_model_kernel": round(1e3 * L_box / v, 3)})
    good = [r for r in res if "exposure_time_ms" in r]
    out = {"n_frames": clip.n, "px_per_s": v, "static_var_px2": round(static_var, 4),
           "rois": res,
           "note": ("camera_model's motion kernel already contains the pixel aperture, "
                    "so its own round trip uses the _model_kernel column; a real "
                    "sensor's static edge already carries the aperture, so use the "
                    "plain column for hardware.")}
    if good:
        out["exposure_time_ms"] = round(float(np.median([r["exposure_time_ms"] for r in good])), 3)
        out["exposure_lines"] = round(out["exposure_time_ms"] * 1e-3 / LINE_PERIOD_S, 1)
    return out


# =============================================================================
# session driver
# =============================================================================

def flag(name: str, value) -> str:
    if value is None or not isinstance(value, (int, float)) or name not in EXPECT:
        return ""
    sim, lo, hi, _ = EXPECT[name]
    if not (lo <= value <= hi):
        return "  <-- OUTSIDE the plausible range, check the setup before believing it"
    if sim == 0:
        return ""
    ratio = value / sim if sim else float("inf")
    if ratio > 2.0 or ratio < 0.5:
        return f"  (sim uses {sim:g}: {ratio:.1f}x off)"
    return f"  (sim uses {sim:g})"


def run_session(session: Path, render_mean_dn: float = 165.0,
                warmup: int = 20, quiet: bool = False) -> dict:
    cfg = {}
    sj = session / "session.json"
    cfg_error = None
    if sj.is_file():
        # session.json is hand-typed in a lab, often at speed. A trailing comma
        # must not throw away the dark/flat/edge/banding results, none of which
        # need it: say plainly what is wrong and carry on without it.
        try:
            cfg = json.loads(sj.read_text())
            if not isinstance(cfg, dict):
                cfg, cfg_error = {}, "top level is not a JSON object"
        except (json.JSONDecodeError, OSError) as e:
            cfg, cfg_error = {}, str(e)
    say = (lambda *a: None) if quiet else print

    say(f"\n=== camera measurement: {session} ===")
    if cfg.get("session"):
        say(f"    {cfg.get('session')}   operator: {cfg.get('operator', '?')}")
    if cfg_error:
        say(f"    ! session.json is not valid JSON and was IGNORED: {cfg_error}")
        say( "      Everything that needs a distance or a pitch (fov, blur) is skipped.")
        say( "      Common causes: a trailing comma before } or ], a missing quote,")
        say(f"      smart quotes pasted from a document. Fix {sj} and re-run;")
        say( "      the frames are already captured, so this costs nothing but the re-run.")
    elif not sj.is_file():
        say("    (no session.json: distance/pitch-dependent measurements will be skipped)")

    out = {"session_dir": str(session), "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
           "session_json": cfg, "results": {}, "recommended": {}}
    R = out["results"]
    rec = out["recommended"]

    dark = open_clip(session, "dark", warmup=warmup)
    flat = open_clip(session, "flat", warmup=warmup)
    roll = open_clip(session, "flat_roll180", warmup=warmup)
    band = open_clip(session, "banding", warmup=warmup) or flat
    edges = [c for c in (open_clip(session, d.name, warmup=min(warmup, 5))
                         for d in sorted(session.iterdir())
                         if d.is_dir() and (d.name == "edge" or d.name.startswith("edge_")))
             if c]
    fov = open_clip(session, "fov", warmup=min(warmup, 5))
    fov_far = open_clip(session, "fov_far", warmup=min(warmup, 5))
    aestep = open_clip(session, "ae_step", warmup=0)
    blur = open_clip(session, "blur", warmup=min(warmup, 5))
    ladder = [c for c in (open_clip(session, d.name, warmup=warmup)
                          for d in sorted(session.glob("level_*")) if d.is_dir()) if c]
    lux = []
    for d in sorted(session.glob("lux_*")):
        if d.is_dir():
            m = re.search(r"lux_([0-9.]+)", d.name)
            c = open_clip(session, d.name, warmup=warmup)
            if c and m:
                lux.append((float(m.group(1)), c))

    seen = set()
    seen_size = set()
    for c in [x for x in (dark, flat, roll, band, fov, fov_far, aestep, blur) if x] + \
             edges + ladder + [c for _, c in lux]:
        if c.jpeg and c.dir.name not in seen:
            seen.add(c.dir.name)
            say(f"  ! {c.dir.name}: JPEG frames. Geometry still works; every noise, "
                f"PRNU, DSNU and PSF number from this folder is invalid.")
        if (c.h, c.w) != FULL_FRAME_HW and c.dir.name not in seen_size:
            seen_size.add(c.dir.name)
            half = (c.h * 2, c.w * 2) == FULL_FRAME_HW
            say(f"  ! {c.dir.name}: frames are {c.w}x{c.h}, not "
                f"{FULL_FRAME_HW[1]}x{FULL_FRAME_HW[0]}."
                + ("  That is exactly half size: these look like cpx_grab.py --bayer"
                   " frames, whose 2x2 average destroys the per-pixel structure this"
                   " script measures. RE-SHOOT WITHOUT --bayer."
                   if half else
                   "  PSF, vignetting and focal-length numbers from this folder are"
                   " scaled by the resolution change and should not be pasted into"
                   " camera_model.py."))

    # --- dark -------------------------------------------------------------
    if dark:
        R["dark"] = measure_dark(dark)
        d = R["dark"]
        say(f"\n[dark]  {d['n_frames']} frames")
        say(f"  mean {d['mean_dn']:.2f} DN, {d['frac_at_0']:.1%} of pixels at 0, "
            f"temporal sigma {d['temporal_sigma_dn']:.2f} DN")
        say(f"  implied total gain in the dark : {d['implied_total_gain']}x "
            f"(model's AE ceiling is 24x)")
        say(f"  DSNU at that gain             : {d['dsnu_at_this_gain_dn']} DN")
        say(f"  dsnu_sigma_dn (referred to 1x): {d['dsnu_sigma_dn']}"
            f"{flag('dsnu_sigma_dn', d['dsnu_sigma_dn'])}")
        if d.get("note"):
            say(f"  note: {d['note']}")
        if d["dsnu_sigma_dn"] is not None:
            rec["dsnu_sigma_dn"] = d["dsnu_sigma_dn"]

    # --- flat -------------------------------------------------------------
    if flat:
        R["flat"] = measure_flat(flat, roll, dark.mean_frame if dark else None,
                                 R.get("dark", {}).get("dsnu_sigma_dn"))
        f = R["flat"]
        say(f"\n[flat]  {f['n_frames']} frames, level {f['noise']['level_dn']:.1f} DN"
            f"{'  (BAYER mosaic detected)' if f['cfa']['bayer'] else ''}")
        v = f["vignetting"]
        say(f"  vignette_a2 = {v['vignette_a2']}{flag('vignette_a2', v['vignette_a2'])}")
        say(f"  vignette_a4 = {v['vignette_a4']}{flag('vignette_a4', v['vignette_a4'])}")
        say(f"  relative illumination: {v['relative_at_h_edge']} at the side, "
            f"{v['relative_at_corner']} in the corner (model: 0.82 / 0.68), "
            f"fit rms {v['fit_rms_relative']:.1%} of centre, "
            f"roll180 {'used' if v['roll180_used'] else 'not used'}")
        say(f"  prnu_sigma  = {f['prnu_sigma']}{flag('prnu_sigma', f['prnu_sigma'])}"
            f"   (total FPN {f['prnu_fpn_sigma_dn']} DN"
            f"{', DSNU subtracted' if f['prnu_dsnu_subtracted'] else ', DSNU NOT subtracted'})")
        dd = f["dead"]
        say(f"  defects: {dd['defect_pixels']} px in {dd['defect_clusters']} clusters "
            f"-> dead_px_frac = {dd['dead_px_frac']:g}"
            f"{flag('dead_px_frac', dd['dead_px_frac'])}")
        say(f"  temporal sigma {f['noise']['temporal_sigma_dn']} DN at "
            f"{f['noise']['level_dn']:.0f} DN -> {f['noise']['e_per_dn_here']} e-/DN here")
        rec.update({"vignette_a2": v["vignette_a2"], "vignette_a4": v["vignette_a4"],
                    "dead_px_frac": dd["dead_px_frac"]})
        if not ladder:
            rec["prnu_sigma"] = f["prnu_sigma"]

    # --- level ladder ------------------------------------------------------
    if ladder:
        R["ladder"] = measure_ladder(ladder, (cfg.get("ladder") or {}).get("rois"))
        L = R["ladder"]
        say(f"\n[level ladder]  {len(L['levels'])} levels")
        for p in L["levels"]:
            say(f"  {p['dir']:<10} {p['signal_dn']:7.2f} DN   "
                f"var_t {p['var_temporal_dn2']:7.3f}   var_fpn {p['var_fpn_dn2']:7.3f}   "
                f"{p['roi_px']} px" + ("   SATURATED" if p["saturated_frac"] > 0.01 else ""))
        if "photon_transfer" in L:
            pt, fp = L["photon_transfer"], L["fpn_transfer"]
            say(f"  photon transfer: slope {pt['slope_dn2_per_dn']} DN2/DN "
                f"-> {pt['e_per_dn_at_operating_gain']} e-/DN at the operating gain "
                f"(R2 {pt['r2']})")
            say(f"  read noise {pt['read_noise_dn']} DN -> total gain "
                f"{pt['implied_total_gain']}x -> e_per_dn_1x = {pt['e_per_dn_1x']}"
                f"{flag('e_per_dn_1x', pt['e_per_dn_1x'])}")
            say(f"  fpn transfer: prnu_sigma = {fp['prnu_sigma']}"
                f"{flag('prnu_sigma', fp['prnu_sigma'])}, "
                f"DSNU {fp['dsnu_at_this_gain_dn']} DN at this gain "
                f"-> dsnu_sigma_dn = {fp['dsnu_sigma_dn']} (R2 {fp['r2']})")
            rec["prnu_sigma"] = fp["prnu_sigma"]
            # The dark frame measures DSNU directly at a high gain where it is
            # far above the quantisation floor. The ladder gets it by
            # extrapolating a fit back to zero signal from levels that are all
            # well above zero, so it is the cross-check, not the source.
            if fp["dsnu_sigma_dn"] and "dsnu_sigma_dn" not in rec:
                rec["dsnu_sigma_dn"] = fp["dsnu_sigma_dn"]

    # --- edges -------------------------------------------------------------
    if edges:
        R["edge"] = measure_edges(edges, (cfg.get("edge") or {}).get("rois"))
        e = R["edge"]
        say(f"\n[edge]  {e['n_frames']} frames from {', '.join(e['clips'])}"
            f"{'  (lattice scan of %d windows)' % e['rois_scanned'] if e['auto_roi'] else ''}")
        for it in sorted(e["edges"], key=lambda r: r["r_norm"]):
            if it.get("ok"):
                say(f"  {it['clip']:<14} roi {str(it['roi']):<20} r={it['r_norm']:.2f}  "
                    f"angle {it['angle_deg']:+5.1f} deg  contrast {it['contrast_dn']:4.0f} DN "
                    f" ->  LSF sigma {it['sigma_px']:.3f} px, preset {it['preset_sigma_px']:.3f} "
                    f"(gauss fit {it.get('sigma_gauss_px', float('nan')):.3f})")
            else:
                say(f"  {it['clip']:<14} roi {str(it['roi']):<20} FAILED: {it.get('why')}")
        if e.get("psf_sigma_center_px") is not None:
            say(f"  psf_sigma_center_px = {e['psf_sigma_center_px']}  "
                f"(median of {e['center_n_edges']} edges at r<=0.30)"
                f"{flag('psf_sigma_center_px', e['psf_sigma_center_px'])}")
            rec["psf_sigma_center_px"] = e["psf_sigma_center_px"]
        if e.get("psf_sigma_corner_px") is not None:
            say(f"  psf_sigma_corner_px = {e['psf_sigma_corner_px']}  "
                f"(median of {e['corner_n_edges']} edges at r>={e['corner_r_norm']:.2f})"
                f"{flag('psf_sigma_corner_px', e['psf_sigma_corner_px'])}")
            rec["psf_sigma_corner_px"] = e["psf_sigma_corner_px"]
        elif e.get("corner_note"):
            say(f"  psf_sigma_corner_px: {e['corner_note']}")

    # --- fov ---------------------------------------------------------------
    if fov:
        R["fov"] = measure_fov(fov, cfg.get("fov") or {})
        v = R["fov"]
        say(f"\n[fov]  {fov.dir.name}")
        if v.get("skipped"):
            say(f"  skipped: {v['skipped']}")
        elif v["mode"] == "marks":
            say(f"  {v['n_edges']} edges -> two marks at {v['mark_centres_px']} px, "
                f"span {v['span_px']} px at {v['distance_m']} m")
            say(f"  focal_px_per_rad = {v['focal_px_per_rad']}"
                f"{flag('focal_px_per_rad', v['focal_px_per_rad'])}")
            say(f"  full HFOV {v['full_hfov_deg']} deg, VFOV {v['full_vfov_deg']} deg")
            rec["focal_px_per_rad"] = v["focal_px_per_rad"]
        else:
            say(f"  {v['n_edges']} bar edges, fit rms {v['fit_rms_px']} px "
                f"(max {v['fit_max_px']}), target skew {v['target_skew_deg']} deg")
            say(f"  focal_px_per_rad = {v['focal_px_per_rad']}"
                f"{flag('focal_px_per_rad', v['focal_px_per_rad'])}"
                f"   (plain line fit: {v['focal_px_per_rad_linear']})")
            say(f"  full HFOV {v['full_hfov_deg']} deg, VFOV {v['full_vfov_deg']} deg"
                f"   k1_forward {v['k1_forward']}")
            rec["focal_px_per_rad"] = v["focal_px_per_rad"]

        if fov_far:
            R["fov_far"] = measure_fov(fov_far, cfg.get("fov_far") or {})
            v2 = R["fov_far"]
            if v2.get("skipped"):
                say(f"  fov_far skipped: {v2['skipped']}")
            elif v.get("scale_px_per_m") and v2.get("scale_px_per_m"):
                # The distance the tape measures is to the tripod, not to the
                # lens's entrance pupil, and nobody knows where that sits. Only
                # the DIFFERENCE of the two distances is trustworthy, and it is
                # enough:  1/s = (D + delta)/f  =>  f = (D2 - D1) / (1/s2 - 1/s1),
                # with delta dropping out and falling out as a bonus.
                s1, s2 = v["scale_px_per_m"], v2["scale_px_per_m"]
                d1, d2 = v["distance_m"], v2["distance_m"]
                den = (1.0 / s2) - (1.0 / s1)
                if abs(den) > 1e-9 and abs(d2 - d1) > 0.05:
                    f2 = (d2 - d1) / den
                    delta = f2 / s1 - d1
                    R["fov_two_distance"] = {
                        "focal_px_per_rad": round(f2, 2),
                        "full_hfov_deg": round(
                            2 * math.degrees(math.atan((fov.w / 2.0) / f2)), 2),
                        "entrance_pupil_offset_m": round(delta, 4),
                        "distances_m": [d1, d2],
                        "scales_px_per_m": [s1, s2]}
                    say(f"  two-distance fit ({d1} m and {d2} m, pupil offset cancelled):")
                    say(f"  focal_px_per_rad = {R['fov_two_distance']['focal_px_per_rad']}"
                        f"{flag('focal_px_per_rad', f2)}"
                        f"   full HFOV {R['fov_two_distance']['full_hfov_deg']} deg")
                    say(f"  implied entrance pupil {delta * 1e3:+.0f} mm from where the "
                        f"tape was read; more than about +-30 mm means a measuring "
                        f"mistake, not optics")
                    rec["focal_px_per_rad"] = R["fov_two_distance"]["focal_px_per_rad"]
                else:
                    say("  fov_far: the two distances are too close together to "
                        "separate the pupil offset (need at least 0.05 m apart)")

    # --- ae step ------------------------------------------------------------
    if aestep:
        R["ae_step"] = measure_ae_step(aestep)
        a = R["ae_step"]
        say(f"\n[ae_step]  {a['n_frames']} frames at {a['fps']} fps, "
            f"{a['steps_found']} usable steps")
        for s in a["steps"]:
            say(f"  frame {s['start_frame']:4d}: u0 {s['u0']:+.2f}, {s['n_points']} pts, "
                f"damping {s['ae_damping']:.3f}")
        if a.get("ae_damping") is not None:
            say(f"  ae_damping = {a['ae_damping']} (spread {a['ae_damping_spread']})"
                f"{flag('ae_damping', a['ae_damping'])}")
            rec["ae_damping"] = a["ae_damping"]
        else:
            say(f"  {a.get('note')}")

    # --- banding ------------------------------------------------------------
    if band:
        R["banding"] = measure_banding(band)
        b = R["banding"]
        say(f"\n[banding]  {b['n_frames']} frames from {band.dir.name}/")
        say(f"  depth at the predicted 268-row period: {b['banding_depth']}"
            f"{flag('banding_depth', b['banding_depth'])}")
        say(f"  control fit at 37 rows (noise floor) : {b['control_depth_at_37_rows']}")
        say(f"  strongest period in a 60-700 row sweep: {b['best_fit_period_rows']:.0f} rows "
            f"(explains {b['variance_explained_at_best']:.0%} of the row ripple; "
            f"268 rows explains {b['variance_explained_at_268']:.0%})")
        if b["banding_depth"] > 3 * max(b["control_depth_at_37_rows"], 1e-6):
            rec["banding_depth"] = b["banding_depth"]
        else:
            say("  -> no banding above the noise floor in this room: banding_depth = 0")
            rec["banding_depth"] = 0.0

    # --- lux ladder ---------------------------------------------------------
    if lux:
        R["lux"] = measure_lux(lux, render_mean_dn)
        say(f"\n[lux ladder]  scene_light anchor, render mean {render_mean_dn} DN")
        for r in R["lux"]["levels"]:
            say(f"  {r['lux']:8.0f} lux  {r['signal_dn']:6.1f} DN  sigma "
                f"{r['temporal_sigma_dn']:5.2f} DN  ->  total gain {r['total_gain']:5.2f}x "
                f"->  scene_light {r['scene_light']}")

    # --- blur ---------------------------------------------------------------
    if blur:
        sv = R.get("edge", {}).get("center_var_px2")
        R["blur"] = measure_blur(blur, cfg.get("blur") or {}, sv)
        b = R["blur"]
        say(f"\n[blur]")
        if b.get("skipped"):
            say(f"  skipped: {b['skipped']}")
        else:
            for r in b["rois"]:
                if "smear_px" in r:
                    say(f"  roi {r['roi']}: smear {r['smear_px']} px "
                        f"-> exposure {r['exposure_time_ms']} ms "
                        f"(model-kernel convention {r['exposure_time_ms_model_kernel']} ms)")
            if b.get("exposure_time_ms"):
                say(f"  exposure_time_ms = {b['exposure_time_ms']} "
                    f"({b['exposure_lines']} lines of 340)"
                    f"{flag('exposure_time_ms', b['exposure_time_ms'])}")

    # --- summary ------------------------------------------------------------
    say("\n=== what to change in camera_model.py ===")
    if not rec:
        say("  nothing measured.")
    for k in sorted(rec):
        sim = EXPECT.get(k, (None,))[0]
        say(f"  {k:<22} measured {rec[k]:<12g} sim {sim if sim is not None else '?':<10}"
            f"{flag(k, rec[k])}")
    presetable = {k: v for k, v in rec.items()
                  if k in ("psf_sigma_center_px", "psf_sigma_corner_px", "vignette_a2",
                           "vignette_a4", "prnu_sigma", "dsnu_sigma_dn", "dead_px_frac",
                           "ae_damping", "banding_depth", "focal_px_per_rad")}
    if presetable:
        say("\n  try it in the simulator without editing any file:")
        say("    CRAZYSIM_SENSOR_PRESET=himax_typical \\")
        say(f"    CRAZYSIM_SENSOR_OVERRIDES='{json.dumps(presetable)}' \\")
        say("    ./run_sim_headless.sh --camera --scene scenes/moving/scene_person.xml")
    out["recommended"] = rec
    return out


# =============================================================================
# selftest: synthesise with known parameters, measure, compare
# =============================================================================

TRUTH = dict(psf_sigma_center_px=0.65, psf_sigma_corner_px=0.65,
             vignette_a2=0.22, vignette_a4=0.10,
             prnu_sigma=0.008, dsnu_sigma_dn=0.40, dead_px_frac=2.0e-4,
             ae_damping=0.25, banding_depth=0.08)
SELFTEST_F = 172.0          # px/rad injected into the synthetic bar target
SELFTEST_DIST = 0.35        # m, near clip
SELFTEST_DIST_FAR = 0.70    # m, far clip
SELFTEST_PITCH = 0.020      # m, edge to edge
PUPIL_OFFSET = 0.025        # m, injected: the lens sits 25 mm behind the tape mark


def _import_camera_model():
    here = Path(__file__).resolve()
    sim = here.parents[2] / "tools" / "crazysim_macos"
    if str(sim) not in sys.path:
        sys.path.insert(0, str(sim))
    try:
        import camera_model as cm
        return cm
    except ImportError as e:
        raise SystemExit(f"selftest needs camera_model.py at {sim}: {e}")


def _model(cm, **over):
    p = dict(TRUTH)
    p.update(over)
    return cm.CameraModel("himax_typical", seed=7, overrides=p)


def _save(frames, d: Path, t0=1_700_000_000.0, dt=0.077):
    d.mkdir(parents=True, exist_ok=True)
    for i, a in enumerate(frames):
        Image.fromarray(a, "L").save(d / f"f{i:05d}_t{t0 + i * dt:.3f}.png")


def _uniform(level, h=244, w=324):
    return np.full((h, w), float(level), np.float32)


def _patch_scene(frac, h=244, w=324, bright=0.85, dark=0.04):
    """A bright rectangle covering `frac` of the frame on a dark surround."""
    img = np.full((h, w), dark, np.float32)
    ph, pw = int(round(h * math.sqrt(frac))), int(round(w * math.sqrt(frac)))
    y0, x0 = (h - ph) // 2, (w - pw) // 2
    img[y0:y0 + ph, x0:x0 + pw] = bright
    return img


def _edge_scene(h=244, w=324, slope=0.0875, lo=0.05, hi=0.85):
    """Hard slanted step: pixel is hi where its centre is right of the edge."""
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float64)
    e = (w - 1) / 2.0 + slope * (yy - (h - 1) / 2.0)
    return np.where(xx > e, hi, lo).astype(np.float32)


def _edge_scene_multi(xs=(40.0, 162.0, 284.0), h=244, w=324, slope=0.0875,
                      lo=0.05, hi=0.85):
    """Three slanted edges, so the corner ROIs have something to measure.

    This is the synthetic stand-in for the five-patch chart in the protocol:
    one edge near the middle and one out at r = 0.72 of the corner radius,
    where the lens falloff has already cut the contrast.
    """
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float64)
    n = np.zeros((h, w))
    for x0 in xs:
        n += (xx > x0 + slope * (yy - (h - 1) / 2.0)).astype(np.float64)
    return np.where(n % 2 == 0, lo, hi).astype(np.float32)


def _bar_scene(f_px, dist, pitch, h=244, w=324, lo=0.05, hi=0.85):
    """Bar target of known pitch seen by a pinhole of focal length f_px."""
    x = np.arange(w, dtype=np.float64) - (w - 1) / 2.0
    X = x * dist / f_px                     # metre position on the target plane
    phase = np.floor(X / pitch)
    row = np.where(phase % 2 == 0, hi, lo)
    return np.tile(row.astype(np.float32), (h, 1))


def _run(model, scene_fn, n, omega=None, dt=0.077):
    out = []
    for i in range(n):
        s = scene_fn(i)
        out.append(model.apply(np.clip(s * 255.0, 0, 255).astype(np.uint8),
                               omega=omega, dt=dt))
    return out


def selftest(keep: Path | None = None, quiet: bool = False) -> int:
    cm = _import_camera_model()
    import tempfile
    tmp = Path(keep) if keep else Path(tempfile.mkdtemp(prefix="cammeas_"))
    tmp.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    print(f"selftest: synthesising into {tmp}")

    # sanity: this file's constants must match camera_model's
    assert abs(cm.E_PER_DN_1X - E_PER_DN_1X) < 1e-9
    assert abs(cm.READ_NOISE_E - READ_NOISE_E) < 1e-9
    assert abs(cm.BANDING_PERIOD_ROWS - BANDING_PERIOD_ROWS) < 1e-9
    assert abs(cm.SENSOR_FRAME_S - SENSOR_FRAME_S) < 1e-12
    assert abs(cm.AE_TARGET_DN - AE_TARGET_DN) < 1e-9

    warm = 25
    # dark: the AE runs to its ceiling. A PERFECT cap gives an all-zero frame
    # whose offset is clipped away, so two clips are made: a near-dark one with
    # a small pedestal (what a real capped lens with any light leak or black
    # level looks like, and the one the estimators are checked against), and a
    # perfectly capped one, which the script must REFUSE to read DSNU from.
    m = _model(cm, banding_depth=0.0)
    ped = 30.0 / (255.0 * 24.0)          # ~30 DN once the AE is at its 24x ceiling,
                                         # which is 3x the DSNU spread, so the
                                         # offset is not clipped away at 0
    _save(_run(m, lambda i: np.full((244, 324), ped, np.float32), 100 + warm), tmp / "dark")
    dark_gain = m.total_gain
    m_cap = _model(cm, banding_depth=0.0)
    _save(_run(m_cap, lambda i: np.zeros((244, 324), np.float32), 40 + warm),
          tmp / "dark_fully_capped")

    # flat: diffuser, with a 15% illumination gradient to give roll180 something to cancel
    grad = 1.0 + 0.15 * (np.mgrid[0:244, 0:324][1] / 323.0 - 0.5)
    m = _model(cm)
    _save(_run(m, lambda i: 0.62 * grad, 140 + warm), tmp / "flat")
    flat_gain = m.total_gain
    m = _model(cm)
    _save(_run(m, lambda i: np.rot90(0.62 * grad, 2), 140 + warm), tmp / "flat_roll180")

    # level ladder: the same patch at four sizes, AE does the rest. The
    # fractions are chosen so the patch lands near 63 / 115 / 170 / 220 DN -
    # a wide lever arm with nothing clipped.
    for k, frac in enumerate([0.95, 0.50, 0.32, 0.235], start=1):
        m = _model(cm, banding_depth=0.0)
        sc = _patch_scene(frac)
        _save(_run(m, lambda i, s=sc: s, 90 + warm), tmp / f"level_{k:02d}")

    # slanted edges: centre plus two out near the corners, in one clip, and a
    # second "corner-aimed" clip whose single edge runs through r = 0.72
    m = _model(cm, banding_depth=0.0)
    sc = _edge_scene_multi()
    _save(_run(m, lambda i, s=sc: s, 40 + 5), tmp / "edge")
    m = _model(cm, banding_depth=0.0)
    sc2 = _edge_scene(slope=0.0875)
    _save(_run(m, lambda i, s=sc2: s, 40 + 5), tmp / "edge_corner_a")

    # bar target for the focal length, at two distances. The scenes are
    # rendered at (declared distance + PUPIL_OFFSET), so the single-distance
    # answer is deliberately wrong by that much and the two-distance fit has
    # something real to cancel.
    for tag, d in (("fov", SELFTEST_DIST), ("fov_far", SELFTEST_DIST_FAR)):
        m = _model(cm, banding_depth=0.0)
        sc = _bar_scene(SELFTEST_F, d + PUPIL_OFFSET, SELFTEST_PITCH)
        _save(_run(m, lambda i, s=sc: s, 12 + 5), tmp / tag)

    # AE step response: five up/down steps of 10x, which is what a white card
    # swept off the lens gives, and what the protocol asks the operator for.
    m = _model(cm, banding_depth=0.0)

    def step_scene(i):
        return _uniform((0.62 if (i // 12) % 2 == 0 else 0.062) * 255.0) / 255.0
    _save(_run(m, step_scene, 72, dt=0.077), tmp / "ae_step")

    # banding, on a flat field
    m = _model(cm)
    _save(_run(m, lambda i: _uniform(0.62 * 255) / 255.0, 120 + warm), tmp / "banding")

    # lux ladder: two rooms, bright and dim
    gains = {}
    for tag, light in (("lux_400", 1.0), ("lux_022", 0.045)):
        m = _model(cm, scene_light=light, banding_depth=0.0)
        _save(_run(m, lambda i: _uniform(0.647 * 255) / 255.0, 80 + warm), tmp / tag)
        gains[tag] = m.total_gain

    # motion blur at a pinned exposure and a known body rate
    t_exp = 96 * LINE_PERIOD_S                       # AE is bypassed: power-on lines
    omega_z = 3.0                                     # rad/s
    L_true = omega_z * t_exp * cm.FOCAL_PX_PER_RAD
    v_px_s = omega_z * cm.FOCAL_PX_PER_RAD
    m = _model(cm, banding_depth=0.0, ae_fixed_exposure=0.40)
    sc = _edge_scene()
    _save(_run(m, lambda i, s=sc: s, 40 + 5, omega=np.array([0.0, 0.0, omega_z])),
          tmp / "blur")
    m2 = _model(cm, banding_depth=0.0, ae_fixed_exposure=0.40)
    _save(_run(m2, lambda i, s=sc: s, 40 + 5), tmp / "static_for_blur")

    (tmp / "session.json").write_text(json.dumps({
        "session": "SYNTHETIC selftest - no hardware involved",
        "operator": "measure_camera.py selftest",
        "fov": {"edge_pitch_m": SELFTEST_PITCH, "distance_m": SELFTEST_DIST,
                "fit_k1": False},
        "fov_far": {"edge_pitch_m": SELFTEST_PITCH, "distance_m": SELFTEST_DIST_FAR,
                    "fit_k1": False},
        "_edge_note": "no edge.rois: the lattice scan is what the lab will use",
        "blur": {"px_per_s": v_px_s, "rois": [[92, 82, 140, 80]]},
    }, indent=2))
    print(f"selftest: {sum(1 for _ in tmp.rglob('*.png'))} frames written "
          f"in {time.time() - t0:.1f} s")

    res = run_session(tmp, render_mean_dn=165.0, warmup=warm, quiet=quiet)
    r = res["results"]

    # the static-edge variance the blur step needs (kept in its own folder so the
    # normal session layout is not bent out of shape)
    static = Clip(tmp / "static_for_blur", warmup=5)
    sv = lsf_variance(static.mean_frame[82:162, 92:232])
    bclip = Clip(tmp / "blur", warmup=5)
    bl = measure_blur(bclip, {"px_per_s": v_px_s, "rois": [[92, 82, 140, 80]]},
                      sv["var_px2"] if sv.get("ok") else None)

    rows = []

    def cmp(name, injected, recovered, tol, unit=""):
        ok = (recovered is not None and np.isfinite(recovered) and
              abs(recovered - injected) <= tol * max(abs(injected), 1e-9))
        rows.append((name, injected, recovered, tol, unit, ok))

    kv = gauss_kernel_var(TRUTH["psf_sigma_center_px"])
    cmp("psf_sigma_center_px", TRUTH["psf_sigma_center_px"],
        r.get("edge", {}).get("psf_sigma_center_px"), 0.08, "px")
    cmp("psf_sigma_corner_px", TRUTH["psf_sigma_corner_px"],
        r.get("edge", {}).get("psf_sigma_corner_px"), 0.15, "px")
    cmp("  (as LSF variance)", kv,
        next((e["var_px2"] for e in r.get("edge", {}).get("edges", []) if e.get("ok")), None),
        0.12, "px^2")
    cmp("vignette_a2", TRUTH["vignette_a2"],
        r.get("flat", {}).get("vignetting", {}).get("vignette_a2"), 0.10)
    cmp("vignette_a4", TRUTH["vignette_a4"],
        r.get("flat", {}).get("vignetting", {}).get("vignette_a4"), 0.30)
    cmp("prnu_sigma (ladder)", TRUTH["prnu_sigma"],
        r.get("ladder", {}).get("fpn_transfer", {}).get("prnu_sigma"), 0.20)
    cmp("prnu_sigma (flat)", TRUTH["prnu_sigma"],
        r.get("flat", {}).get("prnu_sigma"), 0.35)
    cmp("dsnu_sigma_dn (ladder)", TRUTH["dsnu_sigma_dn"],
        r.get("ladder", {}).get("fpn_transfer", {}).get("dsnu_sigma_dn"), 0.40, "DN@1x")
    cmp("dsnu_sigma_dn (dark)", TRUTH["dsnu_sigma_dn"],
        r.get("dark", {}).get("dsnu_sigma_dn"), 0.25, "DN@1x")
    cmp("dark total gain", dark_gain, r.get("dark", {}).get("implied_total_gain"), 0.15, "x")
    cmp("dead_px_frac", TRUTH["dead_px_frac"],
        r.get("flat", {}).get("dead", {}).get("dead_px_frac"), 0.25, "clusters/px")
    cmp("ae_damping", TRUTH["ae_damping"], r.get("ae_step", {}).get("ae_damping"), 0.25)
    cmp("banding_depth", TRUTH["banding_depth"],
        r.get("banding", {}).get("banding_depth"), 0.20)
    cmp("banding period", BANDING_PERIOD_ROWS,
        r.get("banding", {}).get("best_fit_period_rows"), 0.25, "rows")
    cmp("focal_px_per_rad (1 dist)", SELFTEST_F * SELFTEST_DIST / (SELFTEST_DIST + PUPIL_OFFSET),
        r.get("fov", {}).get("focal_px_per_rad"), 0.02, "px/rad")
    cmp("focal_px_per_rad (2 dist)", SELFTEST_F,
        r.get("fov_two_distance", {}).get("focal_px_per_rad"), 0.02, "px/rad")
    cmp("entrance pupil offset", PUPIL_OFFSET,
        r.get("fov_two_distance", {}).get("entrance_pupil_offset_m"), 0.20, "m")
    cmp("e_per_dn_1x", E_PER_DN_1X,
        r.get("ladder", {}).get("photon_transfer", {}).get("e_per_dn_1x"), 0.25, "e-/DN")
    cmp("flat total gain", flat_gain,
        r.get("ladder", {}).get("photon_transfer", {}).get("implied_total_gain"), 0.40, "x")
    lux_rows = {row["dir"]: row for row in r.get("lux", {}).get("levels", [])}
    cmp("dim-room total gain", gains["lux_022"],
        lux_rows.get("lux_022", {}).get("total_gain"), 0.15, "x")
    cmp("bright-room total gain", gains["lux_400"],
        lux_rows.get("lux_400", {}).get("total_gain"), 0.15, "x")
    cmp("dim-room scene_light", 0.045,
        lux_rows.get("lux_022", {}).get("scene_light"), 0.20)
    cmp("motion smear L", L_true,
        (bl["rois"][0].get("smear_px_model_kernel") if bl.get("rois") else None), 0.15, "px")

    # the other half of the dark measurement: a perfectly capped lens must be
    # REFUSED, not turned into a confident zero
    capped = measure_dark(Clip(tmp / "dark_fully_capped", warmup=warm))
    rows.append(("capped lens -> refuses DSNU", float("nan"), float("nan"), 0.0, "",
                 capped["dsnu_sigma_dn"] is None and capped["frac_at_0"] > 0.2))

    print("\n=== selftest: injected vs recovered ===")
    print(f"{'quantity':<26}{'injected':>12}{'recovered':>12}{'tol':>8}   result")
    bad = 0
    for name, inj, rec, tol, unit, ok in rows:
        r_s = "None" if rec is None else f"{rec:.5g}"
        print(f"{name:<26}{inj:>12.5g}{r_s:>12}{tol * 100:>7.0f}%   "
              f"{'ok' if ok else 'MISS'} {unit}")
        bad += 0 if ok else 1
    print(f"\n{len(rows) - bad}/{len(rows)} recovered inside tolerance")
    if keep:
        print(f"frames kept in {tmp}")
    else:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
    return 1 if bad else 0


# =============================================================================

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Measure the real AI-deck camera from captured frames.")
    ap.add_argument("session", help="session folder, or the word 'selftest'")
    ap.add_argument("--json", help="write the full result here "
                                   "(default: <session>/camera_measurements.json)")
    ap.add_argument("--render-mean-dn", type=float, default=165.0,
                    help="mean DN of the simulator render the scene_light anchor "
                         "refers to (default 165)")
    ap.add_argument("--warmup", type=int, default=20,
                    help="frames to drop at the start of each clip while the AE settles")
    ap.add_argument("--keep", help="selftest: keep the synthetic frames here")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)

    if a.session == "selftest":
        return selftest(Path(a.keep) if a.keep else None, a.quiet)

    session = Path(a.session).expanduser().resolve()
    if not session.is_dir():
        raise SystemExit(f"no such folder: {session}")
    res = run_session(session, a.render_mean_dn, a.warmup, a.quiet)
    out = Path(a.json) if a.json else session / "camera_measurements.json"
    out.write_text(json.dumps(res, indent=2, default=str))
    if not a.quiet:
        print(f"\nwritten: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
