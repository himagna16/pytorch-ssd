#!/usr/bin/env python3
"""Camera sensor realism for the simulated AI-deck camera (Himax HM01B0).

This module degrades CrazySim's pixel-sharp MuJoCo render into something close
to what the real AI-deck sensor produces, so the model flies against realistic
frames in simulation. ``patch_crazysim.py`` installs it next to CrazySim's
``crazysim.py`` and calls it from ``CameraRenderer.maybe_render``, which means
every consumer of the UDP frame stream sees the same pixels: ``follow_person.py``,
``gap8_emulator.py``, ``cpx_grab.py --sim``, ``--save-frames`` and the videos.

Design spec: ``scratchpad/simv2/spec_camera.md``. Section numbers below refer to
it. Everything is vectorised numpy and deterministic from a seed.

Selection is by environment variable so that no existing command line changes:

    CRAZYSIM_SENSOR_PRESET   clean (default) | himax_typical | himax_low_light
                             | himax_color_bayer
    CRAZYSIM_SENSOR_SEED     integer, default 1234
    CRAZYSIM_SENSOR_INFO     path for the preset/seed/cost record (default:
                             camera_model.json next to CRAZYSIM_TRUTH_LOG)
    CRAZYSIM_SENSOR_OVERRIDES  JSON object of parameter overrides (tests/tuning)

**clean is a pass-through, not "all effects zeroed".** With the variable unset,
``from_env()`` returns None and the patched simulator takes its original code
path verbatim, so every verified baseline stays valid with no re-running.

Signal chain (spec section 3), in the order photons actually travel:

    scene radiance (MuJoCo render, treated as linear)
      1. lens distortion k1                       (knob, 0 in all presets)
      2. rolling-shutter shear                    (knob, off in all presets)
      3. optical PSF blur (lens MTF + pixel aperture)
      4. vignetting / relative illumination
      5. motion blur from body angular rate x exposure time
      6. row-wise LED banding (flicker avoidance is OFF on this sensor)
      7. exposure + analog/digital gain from the AE loop -> DN
      8. PRNU (multiplicative fixed-pattern gain)
      9. DSNU (additive fixed-pattern offset, scales with gain)
     10. shot + read noise (one shared Gaussian draw)
     11. dead-pixel clusters
     12. clip to full well, round-half-up, 8-bit
     13. AE loop meters this frame and sets exposure for the next one

Photon-transfer parameters are derived from the module datasheet rather than
guessed (spec 3.1): SNR_max 38.7 dB -> full well 7400 e-; DR 64 dB at 1x ->
read floor 4.7 e-; mapping full well onto 8 bits -> 29 e-/DN at 1x. So

    sigma_shot(S) = sqrt(S * g / 29) DN      sigma_read(g) = 0.162 * g DN

with S the signal in DN and g the total gain. These are formulas, not knobs.

Parameters that are physics or register values are exact. Parameters that are
class estimates carry an UNMEASURED tag that survives into ``describe()`` and
into the JSON record, so a placeholder is never mistaken for a measurement.
"""

from __future__ import annotations

import json
import math
import os
import time
from dataclasses import dataclass, field, asdict, replace

import numpy as np

# --- Sensor constants (register table and datasheet; spec 1.2-1.3) ----------
LINE_PERIOD_S = 31.07e-6      # datasheet line period
MAX_INTG_LINES = 340          # MAX_INTG = 0x0154
POWERON_INTG_LINES = 96       # INTEGRATION = 0x0060
FRAME_LEN_LINES = 534         # FRAME_LEN_LINES = 0x0216 -> 16.59 ms, 60.3 fps
SENSOR_FRAME_S = FRAME_LEN_LINES * LINE_PERIOD_S
AE_TARGET_DN = 60.0           # AE_TARGET_MEAN = 0x3C
AE_CONVERGE_IN_DN = 3.0       # CONVERGE_IN_TH
AE_CONVERGE_OUT_DN = 5.0      # CONVERGE_OUT_TH
AGAIN_STEPS = (1.0, 2.0, 4.0, 8.0)   # MAX_AGAIN_FULL = 0x03 -> 8x
MAX_DGAIN = 3.0               # MAX_DGAIN = 0xC0, read as ~3x (datasheet cap 4x)
E_PER_DN_1X = 29.0            # derived, spec 3.1
READ_NOISE_E = 4.7            # derived, spec 3.1
FULL_WELL_E = 7400.0          # derived, spec 3.1
BANDING_PERIOD_ROWS = 268.0   # (1/120 s) / line period, FS_CTRL = 0x00

# Sim optics: fovy 70 over 244 rows -> 122/tan(35 deg) px/rad. The real module
# measures 170.7 px/rad, 2.1% away (spec 2); the sim value is the right one to
# use here because these pixels come from the sim's own projection.
FOCAL_PX_PER_RAD = 122.0 / math.tan(math.radians(35.0))

REC601 = (0.2989, 0.5870, 0.1140)

# Parameters that are class estimates rather than measurements (spec 4.1, 11.5).
UNMEASURED = (
    "psf_sigma_center_px", "psf_sigma_corner_px", "vignette_a2", "vignette_a4",
    "prnu_sigma", "dsnu_sigma_dn", "dead_px_frac", "ae_damping",
    "scene_light", "banding_depth",
)


@dataclass
class Params:
    """One preset's parameters. Values are per spec section 4.1."""
    name: str = "clean"
    enabled: bool = False

    # --- scene / exposure ---------------------------------------------------
    # Scene light level relative to the render. The AE anchor is: total
    # exposure factor E = 1 means MAX_INTG lines at unity gain reproduces the
    # render unchanged. So a light-1.0 render with mean 165 DN converges to
    # 165->60 DN at 124/340 lines and 1x gain, leaving 2.7x of integration
    # headroom before the loop must reach for gain.
    scene_light: float = 1.0
    ae_enabled: bool = True
    ae_target_dn: float = AE_TARGET_DN
    ae_damping: float = 0.25          # per sensor frame, from DAMPING_FACTOR
    ae_fixed_exposure: float | None = None   # tests: pin E, skip the loop

    # --- optics -------------------------------------------------------------
    psf_sigma_center_px: float = 0.0
    psf_sigma_corner_px: float = 0.0  # recorded only; constant sigma is used
    vignette_a2: float = 0.0
    vignette_a4: float = 0.0
    k1: float = 0.0                   # radial distortion, off in all presets

    # --- motion -------------------------------------------------------------
    motion_blur: bool = False
    # Skip only smears that are numerically nothing. The kernel is a cheap
    # near-identity at small L, so there is no reason to gate at a half pixel:
    # the follower's own 40 deg/s yaw cap produces just 0.52 px at the in-flight
    # exposure, which the old 0.5 px gate admitted and then discarded.
    motion_blur_min_px: float = 0.01
    focal_px_per_rad: float = FOCAL_PX_PER_RAD
    rolling_shutter: bool = False     # knob; off in all presets (spec 3.8)

    # --- noise --------------------------------------------------------------
    shot_noise: bool = False
    read_noise: bool = False
    prnu_sigma: float = 0.0           # fraction of signal
    dsnu_sigma_dn: float = 0.0        # DN at 1x gain
    dead_px_frac: float = 0.0         # fraction of pixels, as 2x2 clusters
    banding_depth: float = 0.0        # LED row banding modulation

    # --- colour -------------------------------------------------------------
    bayer: bool = False               # RGGB mosaic for the colour deck

    def unmeasured(self) -> list[str]:
        """Which of this preset's active parameters are estimates, not measurements."""
        d = asdict(self)
        return [k for k in UNMEASURED if d.get(k)]


def _preset_table() -> dict[str, Params]:
    clean = Params(name="clean", enabled=False)

    typical = Params(
        name="himax_typical", enabled=True,
        scene_light=1.0,
        psf_sigma_center_px=0.65, psf_sigma_corner_px=1.10,
        vignette_a2=0.22, vignette_a4=0.10,
        motion_blur=True, shot_noise=True, read_noise=True,
        prnu_sigma=0.008, dsnu_sigma_dn=0.4, dead_px_frac=1e-5,
        banding_depth=0.0,
    )

    # Spec 4.2 wants this preset to sit at the sensor's gain ceiling as a
    # stress point. The spec's stated 0.12 does not get there under the AE
    # anchor above: a typical scene uses only 124/340 lines, so 0.12 (3 stops)
    # is absorbed by integration alone and the loop settles near 2-4x total.
    # 0.045 is used instead, and what it actually delivers is a TOTAL gain of
    # about 8x (integration pinned at the 340-line ceiling, then ~8x of
    # analog x digital), giving the ~4.3 DN noise the spec's own low-light
    # table was computed from.
    #
    # Deliberately stated as total gain, not "the 8x analog step": the split
    # between analog and digital is NOT stable here. The required ratio lands
    # right on _pick_gain's 4x/8x boundary (measured total 7.70-8.06 on a real
    # s01 render), so run-to-run noise flips it - a seed sweep on one fixed
    # scene and viewpoint gave analog 4x on 9 of 20 runs and 8x on 11. That is
    # harmless because the noise model uses total_gain for both the shot and
    # read terms, so the split is physically inert in this implementation, but
    # the preset must not be described as landing on the analog ceiling.
    # Brighter close-range views settle lower still. A chosen stress point,
    # not a measured room: UNMEASURED.
    low_light = replace(
        typical, name="himax_low_light",
        scene_light=0.045,
        banding_depth=0.08,
    )

    # Identical radiometry to himax_typical, plus the RGGB mosaic and +0.5 px
    # of PSF sigma for the halved luma sampling (spec 3.10).
    bayer = replace(
        typical, name="himax_color_bayer",
        bayer=True,
        psf_sigma_center_px=1.15, psf_sigma_corner_px=1.60,
    )

    return {p.name: p for p in (clean, typical, low_light, bayer)}


PRESETS = _preset_table()


# --- small vectorised helpers ----------------------------------------------

def _gauss_kernel(sigma: float) -> np.ndarray:
    r = max(1, int(math.ceil(3.0 * sigma)))
    x = np.arange(-r, r + 1, dtype=np.float32)
    k = np.exp(-0.5 * (x / sigma) ** 2)
    return (k / k.sum()).astype(np.float32)


def _box_kernel(length: float) -> np.ndarray:
    """Motion-blur kernel for a box smear of ``length`` pixels.

    Two regimes, because a smear narrower than one pixel cannot be represented
    by resampling the box onto the pixel grid at all:

    * ``L`` above ~1.1 px: the exact area-overlap kernel. Tap ``o`` gets the
      length of the overlap between the pixel cell ``[o-0.5, o+0.5]`` and the
      smear ``[-L/2, L/2]``. The support runs out to ``|o| <= (L+1)/2`` so a
      non-zero tap is never truncated (the old ``n = ceil(L)`` estimate was too
      small). This kernel's second moment is the smear's ``L^2/12`` *plus* the
      pixel aperture's own ``1/12``, which is why the tests recover the length
      as ``sqrt(12 * (var - 1/12))``.
    * ``L`` below that: area overlap puts every unit of weight in the centre
      tap and returns the identity, i.e. sub-pixel smear would silently do
      nothing at all. Instead the kernel matches the smear's second moment on a
      3-tap stencil, ``[v/2, 1-v, v/2]`` with ``v = L^2/12``. This is the
      standard moment-matched PSF: it tends to the identity as ``L -> 0`` and
      genuinely softens edges in between (a 0.7 px smear gives variance
      0.0408 and moves ~5 DN across a hard edge).

    The regime is picked by comparing second moments, not by a hard branch on
    1.0, so no blur is lost at the crossover (which lands near 1.12 px).
    """
    L = float(length)
    if L <= 0.0:
        return np.ones(1, np.float32)
    n = max(3, 2 * int(math.floor((L + 1.0) / 2.0)) + 1)
    half = L / 2.0
    off = np.arange(n, dtype=np.float32) - (n - 1) / 2.0
    lo = np.maximum(off - 0.5, -half)
    hi = np.minimum(off + 0.5, half)
    k = np.maximum(hi - lo, 0.0).astype(np.float32)
    k = k / k.sum()
    var = float((k * (off - float((k * off).sum())) ** 2).sum())
    target = L * L / 12.0
    # Moment-matching is ONLY for the degenerate sub-pixel regime. A 3-tap
    # stencil cannot carry a second moment above 2/3 (it would need a negative
    # centre tap), and for any smear that wide the area-overlap kernel is both
    # valid and the right shape - binning simply costs it a little variance, so
    # "overlap undershoots L^2/12" must not by itself trigger the fallback.
    if var >= target or target > 2.0 / 3.0:
        return k
    v = target
    return np.array([v / 2.0, 1.0 - v, v / 2.0], np.float32)


def _convolve_axis(img: np.ndarray, kernel: np.ndarray, axis: int) -> np.ndarray:
    """1-D convolution along one axis with edge clamping (shifted-sum, no scipy)."""
    r = len(kernel) // 2
    pad = ((r, r), (0, 0)) if axis == 0 else ((0, 0), (r, r))
    p = np.pad(img, pad, mode="edge")
    out = np.zeros_like(img)
    n = img.shape[axis]
    for i, k in enumerate(kernel):
        if k == 0.0:
            continue
        sl = p[i:i + n, :] if axis == 0 else p[:, i:i + n]
        out += k * sl
    return out


def _bilinear_sample(img: np.ndarray, xs: np.ndarray, ys: np.ndarray) -> np.ndarray:
    """Sample img at float coordinates (clamped to the frame)."""
    h, w = img.shape
    xs = np.clip(xs, 0, w - 1)
    ys = np.clip(ys, 0, h - 1)
    x0 = np.floor(xs).astype(np.int32)
    y0 = np.floor(ys).astype(np.int32)
    x1 = np.minimum(x0 + 1, w - 1)
    y1 = np.minimum(y0 + 1, h - 1)
    fx = (xs - x0).astype(np.float32)
    fy = (ys - y0).astype(np.float32)
    return ((img[y0, x0] * (1 - fx) + img[y0, x1] * fx) * (1 - fy) +
            (img[y1, x0] * (1 - fx) + img[y1, x1] * fx) * fy)


def _pick_gain(ratio: float) -> tuple[float, float]:
    """Split a needed gain into (analog, digital), preferring analog (spec 3.5)."""
    again = 1.0
    for g in AGAIN_STEPS:
        if ratio >= g:
            again = g
    again = min(again, AGAIN_STEPS[-1])
    dgain = float(np.clip(ratio / again, 1.0, MAX_DGAIN))
    return again, dgain


class CameraModel:
    """Stateful sensor model. One instance per camera; call ``apply`` per frame.

    State that persists between frames: the AE loop's exposure and gain, the
    frame counter, and the per-frame RNG stream. Fixed-pattern fields (PRNU,
    DSNU, dead pixels, vignette, blur kernels) are built once at construction,
    so the per-frame cost is a handful of vectorised passes.
    """

    def __init__(self, preset: str = "clean", width: int = 324, height: int = 244,
                 seed: int = 1234, overrides: dict | None = None):
        if preset not in PRESETS:
            raise ValueError(f"unknown camera preset {preset!r}; "
                             f"known: {', '.join(PRESETS)}")
        p = PRESETS[preset]
        if overrides:
            unknown = set(overrides) - set(asdict(p))
            if unknown:
                raise ValueError(f"unknown camera parameter(s): {sorted(unknown)}")
            p = replace(p, **overrides)
        self.params = p
        self.preset = p.name
        self.seed = int(seed)
        self.width, self.height = int(width), int(height)
        self.enabled = p.enabled

        # Two independent streams: the "device" (fixed pattern, fixed for the
        # life of this simulated sensor) and the per-frame noise.
        dev = np.random.default_rng(self.seed)
        self._rng = np.random.default_rng(self.seed + 1)

        h, w = self.height, self.width
        self._shape = (h, w)

        # Vignetting: radius normalised so r = 1 at the frame corner. With
        # a2 = 0.22 / a4 = 0.10 that gives 0.82 at the horizontal edge and
        # 0.68 in the corner.
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        dx = (xx - (w - 1) / 2.0)
        dy = (yy - (h - 1) / 2.0)
        r_corner = math.hypot((w - 1) / 2.0, (h - 1) / 2.0)
        r = np.hypot(dx, dy) / r_corner
        self._r = r
        vig = 1.0 - p.vignette_a2 * r ** 2 - p.vignette_a4 * r ** 4
        self._vignette = np.clip(vig, 0.0, 1.0).astype(np.float32)
        self._has_vignette = bool(p.vignette_a2 or p.vignette_a4)

        # Fixed-pattern noise fields.
        self._prnu = (1.0 + dev.normal(0.0, p.prnu_sigma, (h, w))).astype(np.float32) \
            if p.prnu_sigma > 0 else None
        self._dsnu = dev.normal(0.0, p.dsnu_sigma_dn, (h, w)).astype(np.float32) \
            if p.dsnu_sigma_dn > 0 else None

        # Dead pixels: single defects are repaired on-chip (DPC_CTRL = 0x01),
        # so what survives is small clusters. One 2x2 cluster per
        # dead_px_frac * H * W pixels, each stuck hot or cold.
        self._dead_idx = None
        if p.dead_px_frac > 0:
            n_clusters = max(1, int(round(h * w * p.dead_px_frac)))
            ys = dev.integers(0, h - 1, n_clusters)
            xs = dev.integers(0, w - 1, n_clusters)
            vals = np.where(dev.random(n_clusters) < 0.5, 0.0, 255.0).astype(np.float32)
            iy, ix, iv = [], [], []
            for cy, cx, v in zip(ys, xs, vals):
                for oy in (0, 1):
                    for ox in (0, 1):
                        iy.append(cy + oy); ix.append(cx + ox); iv.append(v)
            self._dead_idx = (np.array(iy), np.array(ix), np.array(iv, np.float32))

        # PSF kernel (constant sigma; the corner value is recorded, not used).
        self._psf = _gauss_kernel(p.psf_sigma_center_px) if p.psf_sigma_center_px > 0 else None

        # Bayer RGGB masks. Each 2x2 cell carries one R, two G and one B, so a
        # 2x2 average is a fixed-weight (R + 2G + B)/4 luma regardless of phase.
        self._bayer_masks = None
        if p.bayer:
            m_r = np.zeros((h, w), np.float32); m_g = np.zeros((h, w), np.float32)
            m_b = np.zeros((h, w), np.float32)
            m_r[0::2, 0::2] = 1.0
            m_g[0::2, 1::2] = 1.0; m_g[1::2, 0::2] = 1.0
            m_b[1::2, 1::2] = 1.0
            self._bayer_masks = (m_r, m_g, m_b)

        # Lens distortion map (precomputed; only when k1 != 0).
        self._distort_map = None
        if p.k1:
            cx, cy = (w - 1) / 2.0, (h - 1) / 2.0
            rn = np.hypot(dx, dy) / r_corner
            scale = 1.0 + p.k1 * rn ** 2
            self._distort_map = ((cx + dx * scale).astype(np.float32),
                                 (cy + dy * scale).astype(np.float32))

        self._row_idx = np.arange(h, dtype=np.float32)[:, None]
        self._col_idx = np.arange(w, dtype=np.float32)[None, :]

        # AE state: the sensor powers on at 96 lines and unity gain.
        self._t_lines = float(POWERON_INTG_LINES)
        self._again = 1.0
        self._dgain = 1.0
        self._converged = False

        # Bookkeeping.
        self.frames = 0
        self._cost_ms: list[float] = []
        self._info_path = None
        self._info_every = 100

    # --- exposure ----------------------------------------------------------
    @property
    def exposure_factor(self) -> float:
        """Total multiplicative exposure E. E = 1 is MAX_INTG lines at 1x gain."""
        if self.params.ae_fixed_exposure is not None:
            return float(self.params.ae_fixed_exposure)
        return (self._t_lines / MAX_INTG_LINES) * self._again * self._dgain

    @property
    def total_gain(self) -> float:
        return self._again * self._dgain

    @property
    def exposure_time_s(self) -> float:
        return self._t_lines * LINE_PERIOD_S

    def _ae_update(self, measured_mean: float, dt: float) -> None:
        """One camera frame's worth of AE loop steps (spec 3.5).

        The loop runs at the sensor frame rate (60 fps), applying a damped
        partial correction each time, so a camera frame at 13 Hz sees several
        steps. The CONVERGE_IN/OUT deadband means exposure sits still while the
        scene stays within about 5% of target.
        """
        p = self.params
        if not p.ae_enabled or p.ae_fixed_exposure is not None:
            return
        err = abs(measured_mean - p.ae_target_dn)
        if self._converged and err <= AE_CONVERGE_OUT_DN:
            return
        if err <= AE_CONVERGE_IN_DN:
            self._converged = True
            return
        self._converged = False

        n_steps = max(1, int(round(max(dt, 0.0) / SENSOR_FRAME_S)))
        # n damped steps of factor (1 - damping) residual each.
        frac = 1.0 - (1.0 - p.ae_damping) ** n_steps
        want = p.ae_target_dn / max(measured_mean, 1e-3)
        e_new = self.exposure_factor * (want ** frac)

        # Actuator order: integration time first (whole lines), then analog
        # gain, then digital gain.
        lines = e_new * MAX_INTG_LINES
        self._t_lines = float(np.clip(round(lines), 1, MAX_INTG_LINES))
        leftover = lines / self._t_lines
        self._again, self._dgain = _pick_gain(max(leftover, 1.0))

    # --- the chain ---------------------------------------------------------
    def apply(self, rgb: np.ndarray, omega: np.ndarray | None = None,
              dt: float = 0.05) -> np.ndarray:
        """Degrade one rendered frame. Returns uint8 (H, W), same shape as today.

        ``rgb``   : (H, W, 3) uint8 from mujoco.Renderer.render(), or (H, W)
                    grayscale (tests).
        ``omega`` : body angular rate [wx, wy, wz] rad/s for motion blur.
        ``dt``    : seconds since the previous camera frame (AE loop steps).
        """
        t_start = time.perf_counter()
        p = self.params

        # 1. Scene radiance, linear, one channel per photosite.
        if rgb.ndim == 3:
            if p.bayer:
                m_r, m_g, m_b = self._bayer_masks
                f = rgb[..., :3].astype(np.float32)
                L = (f[..., 0] * m_r + f[..., 1] * m_g + f[..., 2] * m_b) / 255.0
            else:
                L = (np.dot(rgb[..., :3].astype(np.float32), REC601) / 255.0)
        else:
            L = rgb.astype(np.float32) / 255.0

        # 2. Geometry: distortion, then rolling-shutter shear (both off by default).
        if self._distort_map is not None:
            L = _bilinear_sample(L, self._distort_map[0], self._distort_map[1])
        if p.rolling_shutter and omega is not None:
            # Row r is exposed r line-periods after the top row.
            shift = float(omega[2]) * (self._row_idx * LINE_PERIOD_S) * p.focal_px_per_rad
            L = _bilinear_sample(L, self._col_idx + shift,
                                 np.repeat(self._row_idx, self.width, axis=1))

        # 3. Optical PSF: lens MTF convolved with the pixel aperture.
        if self._psf is not None:
            L = _convolve_axis(_convolve_axis(L, self._psf, 1), self._psf, 0)

        # 4. Vignetting / relative illumination.
        if self._has_vignette:
            L = L * self._vignette

        # 5. Motion blur over the exposure, from the drone's own body rate.
        t_exp = self.exposure_time_s
        if p.motion_blur and omega is not None and t_exp > 0:
            # Camera looks along body +X: body yaw (wz) pans horizontally,
            # body pitch (wy) tilts vertically.
            lx = abs(float(omega[2])) * t_exp * p.focal_px_per_rad
            ly = abs(float(omega[1])) * t_exp * p.focal_px_per_rad
            # Sub-pixel smears are the normal case in flight (the follower
            # caps yaw at 40 deg/s = 0.52 px here), so they must not be gated
            # away; _box_kernel stays well behaved all the way down.
            if lx > p.motion_blur_min_px:
                L = _convolve_axis(L, _box_kernel(lx), 1)
            if ly > p.motion_blur_min_px:
                L = _convolve_axis(L, _box_kernel(ly), 0)

        # 6. Row-wise LED banding. Flicker avoidance is off (FS_CTRL = 0x00),
        # so the rolling shutter turns mains-frequency light into moving bands.
        if p.banding_depth > 0:
            phase = float(self._rng.uniform(0.0, 2.0 * math.pi))
            band = 1.0 + p.banding_depth * np.sin(
                2.0 * math.pi * self._row_idx / BANDING_PERIOD_ROWS + phase)
            L = L * band.astype(np.float32)

        # 7. Exposure and gain -> DN.
        g = self.total_gain
        S = L * (255.0 * p.scene_light * self.exposure_factor)

        # 8/9. Fixed-pattern noise: multiplicative gain, then additive offset.
        if self._prnu is not None:
            S = S * self._prnu
        if self._dsnu is not None:
            S = S + self._dsnu * g

        # 10. Shot + read noise in one Gaussian draw. A Gaussian is exact above
        # ~20 e- (the AE target is 1740 e-) and costs a quarter of rng.poisson.
        if p.shot_noise or p.read_noise:
            var = np.zeros_like(S)
            if p.shot_noise:
                var += np.maximum(S, 0.0) * g / E_PER_DN_1X
            if p.read_noise:
                var += (READ_NOISE_E * g / E_PER_DN_1X) ** 2
            S = S + self._rng.standard_normal(self._shape).astype(np.float32) * np.sqrt(var)

        # 11. Dead-pixel clusters (what on-chip DPC does not repair).
        if self._dead_idx is not None:
            iy, ix, iv = self._dead_idx
            S[iy, ix] = iv

        # 12. Clip to full well, round half up, 8 bit. Quantisation happens
        # last, after noise, rather than being inherited from the render.
        out = np.floor(np.clip(S, 0.0, 255.0) + 0.5).astype(np.uint8)

        # 13. The AE loop meters this frame and sets exposure for the next one,
        # which is where the real loop's one-frame lag comes from.
        self._ae_update(float(out.mean()), dt)

        self.frames += 1
        self._cost_ms.append((time.perf_counter() - t_start) * 1000.0)
        if self._info_path and self.frames % self._info_every == 0:
            self._write_info()
        return out

    # --- reporting ---------------------------------------------------------
    def cost_stats(self) -> dict:
        if not self._cost_ms:
            return {}
        a = np.asarray(self._cost_ms)
        return {"frames": int(a.size), "mean_ms": round(float(a.mean()), 3),
                "median_ms": round(float(np.median(a)), 3),
                "p95_ms": round(float(np.percentile(a, 95)), 3),
                "max_ms": round(float(a.max()), 3)}

    def state(self) -> dict:
        return {"exposure_lines": round(self._t_lines, 1),
                "exposure_ms": round(self.exposure_time_s * 1e3, 3),
                "analog_gain": self._again, "digital_gain": round(self._dgain, 3),
                "exposure_factor": round(self.exposure_factor, 5),
                "ae_converged": self._converged}

    def describe(self) -> dict:
        return {"preset": self.preset, "seed": self.seed,
                "width": self.width, "height": self.height,
                "params": asdict(self.params),
                "unmeasured": self.params.unmeasured(),
                "derived": {"e_per_dn_1x": E_PER_DN_1X, "read_noise_e": READ_NOISE_E,
                            "full_well_e": FULL_WELL_E,
                            "focal_px_per_rad": round(self.params.focal_px_per_rad, 2)},
                "state": self.state(), "cost": self.cost_stats()}

    def _write_info(self) -> None:
        try:
            with open(self._info_path, "w") as f:
                json.dump(self.describe(), f, indent=2)
        except OSError:
            pass

    def attach_info_file(self, path) -> None:
        """Record preset, seed, parameters and per-frame cost where a flight log finds them."""
        self._info_path = str(path)
        self._write_info()


def from_env(width: int = 324, height: int = 244) -> CameraModel | None:
    """Build the model the environment asks for, or None for today's behaviour.

    Returning None is the contract that keeps ``clean`` byte-identical: the
    caller must take its original code path unchanged, not a zeroed model.
    """
    name = (os.environ.get("CRAZYSIM_SENSOR_PRESET") or "").strip()
    if not name or name == "clean":
        return None
    seed = int(os.environ.get("CRAZYSIM_SENSOR_SEED") or 1234)
    overrides = os.environ.get("CRAZYSIM_SENSOR_OVERRIDES")
    m = CameraModel(name, width=width, height=height, seed=seed,
                    overrides=json.loads(overrides) if overrides else None)

    info = os.environ.get("CRAZYSIM_SENSOR_INFO")
    if not info:
        truth = os.environ.get("CRAZYSIM_TRUTH_LOG")
        if truth:
            info = os.path.join(os.path.dirname(os.path.abspath(truth)),
                                "camera_model.json")
    if info:
        m.attach_info_file(info)

    unm = m.params.unmeasured()
    print(f"[camera_model] preset={m.preset} seed={m.seed} "
          f"{width}x{height} info={info or 'none'}")
    print(f"[camera_model] UNMEASURED parameters in use: {', '.join(unm) or 'none'}")
    return m
