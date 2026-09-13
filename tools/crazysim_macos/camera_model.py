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

Cost (spec 8: 5 ms/frame hard cap)
----------------------------------
Once the motion-blur gate was fixed the blur convolutions started running on
every frame instead of never, and the chain went to 3.50 ms mean / 7.27 ms
worst in flight - over the cap on 6 of 16 runs. The chain below was then
rewritten to run in place against reused buffers, with the dominant loops
changed to walk contiguous memory. Measured on an M4 Pro, 4,000 frames per
preset, both implementations interleaved in one process so they see the same
machine (CPU clock, so another process cannot flatter either one):

    preset              median ms       worst frame ms
    himax_typical       1.90 -> 1.16    4.92 -> 3.00
    himax_low_light     1.96 -> 1.21    5.48 -> 3.29
    himax_color_bayer   1.09 -> 0.93    1.58 -> 1.47

The old chain put a frame over the 5 ms cap on its own, with nothing else
running. The new one has no frame over 5 ms in 12,000.

**The rewrite does not change a single output bit.** The whole of
docs/sim_results/2026-09-11-simv2 was measured on frames this chain produced,
so that is not a nicety: ``test_optimised_chain_is_bit_identical_to_the_reference``
runs an independent, plainly-written implementation of the chain beside this
one, and ``dump_camera_samples.py`` reproduces all 13 published sample PNGs
byte for byte.

Two things worth knowing before touching this file again:

* The **non-Bayer chain runs in float64**, not float32, because step 1's
  ``np.dot(f32_rgb, REC601)`` promotes to the tuple's float64. It is an
  accident, it costs about 0.45 ms/frame, and it is *not* fixed here: making it
  float32 would change every rendered pixel and invalidate the published suite.
  That is a team decision, not a silent optimisation.
* The remaining floor is the Gaussian noise draw, 0.29 ms of the 1.16, and it
  cannot move without changing the random stream.

Two consequences of running in place, both of which bite silently:

* **``apply`` is not reentrant.** The scratch buffers belong to the instance, so
  two concurrent ``apply`` calls on ONE model overwrite each other's pixels. The
  old allocating version was safe under that misuse; this one is not, so ``apply``
  refuses a concurrent call rather than returning a corrupted frame. One
  ``CameraModel`` per camera, called from one thread, is the contract.
* **The scratch pool is bounded** (``_MAX_SCRATCH``) and ``apply`` only accepts
  the frame size the model was built for. Both are deliberate: the fixed-pattern
  fields (PRNU, DSNU, dead pixels, vignette) are per-pixel maps for exactly that
  size, so a differently-shaped frame has no meaning here.
"""

from __future__ import annotations

import json
import math
import os
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field, asdict, replace
from functools import lru_cache

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

# Upper bound on the scratch pool (see CameraModel._buf). One frame needs at
# most eight live buffers; the chain can hold two dtype variants of them (the
# float64 RGB path and the float32 grayscale/Bayer path), so sixteen covers
# every shipped configuration with room to spare and still cannot grow without
# limit if a future caller varies the frame size.
_MAX_SCRATCH = 16

REC601 = (0.2989, 0.5870, 0.1140)
# Same three numbers as a float64 vector. ``np.dot(f32_rgb, REC601)`` and
# ``np.matmul(f64_rgb, REC601_W)`` go to the same BLAS gemv and agree on every
# one of the 256^3 possible uint8 triples (tools/crazysim_macos exhaustive
# check), but the matmul form skips numpy's float32->float64 cast temporary
# and is 3.3x faster.
REC601_W = np.array(REC601, dtype=np.float64)

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


@lru_cache(maxsize=32)
def _edge_cols(w: int, r: int, offsets: tuple) -> tuple:
    """Border columns of a row and, for each kept tap, their clamped sources."""
    cols = np.concatenate([np.arange(r), np.arange(w - r, w)]) if 2 * r < w \
        else np.arange(w)
    xs = np.clip(cols[None, :] + np.asarray(offsets)[:, None], 0, w - 1)
    return cols, xs.ravel()


def _convolve_axis(img: np.ndarray, kernel: np.ndarray, axis: int,
                   out: np.ndarray | None = None,
                   tmp: np.ndarray | None = None) -> np.ndarray:
    """1-D convolution along one axis with edge clamping (shifted-sum, no scipy).

    ``out`` and ``tmp`` are optional caller-owned scratch buffers; passing them
    (what ``CameraModel.apply`` does) makes the call allocation-free.

    The arithmetic is **exactly** what the original shifted-sum did and has to
    stay that way - the published suite's frames depend on it. Every output
    element still accumulates the same taps, in kernel order, at the same
    precision, from the same edge-clamped sources. What changed is only how the
    memory is walked:

    * **axis 0** (vertical): each tap is two contiguous row slices - the rows
      that see real data, and the ones clamped to the first/last row - so the
      ``np.pad`` copy of the whole frame is gone.
    * **axis 1** (horizontal): ``p[:, i:i+w]`` was a strided view, and strided
      numpy loops run about half speed. In the flattened C-contiguous buffer the
      same tap is ``flat[k+d]``, one contiguous slice. Only the ``r`` border
      columns of each row would then pull from the neighbouring row, so those
      ``2*r*h`` elements (976 of 79,056 for the 5-tap PSF) are recomputed
      afterwards with clamped sources, in the same tap order.

    Measured on 244x324 float64: 5-tap horizontal 0.304 -> 0.135 ms, 9-tap
    0.497 -> 0.247 ms; vertical 5-tap 0.157 -> 0.118 ms. Bit-identical on every
    case in ``test_convolution_rewrite_is_bit_identical``.
    """
    h, w = img.shape
    r = len(kernel) // 2
    if not img.flags.c_contiguous:
        img = np.ascontiguousarray(img)
    if out is None or out.shape != img.shape or out.dtype != img.dtype \
            or not out.flags.c_contiguous:
        out = np.empty(img.shape, img.dtype)
    if tmp is None or tmp.shape != img.shape or tmp.dtype != img.dtype \
            or not tmp.flags.c_contiguous:
        tmp = np.empty(img.shape, img.dtype)
    kd = kernel if kernel.dtype == img.dtype else kernel.astype(img.dtype)
    taps = [(i - r, kd[i]) for i in range(len(kernel)) if kernel[i] != 0.0]
    if not taps:                      # every tap exactly zero; kernels never are
        out.fill(0)
        return out

    if axis == 0:
        first = True
        for d, k in taps:
            # ``split`` is where the real source rows stop and the clamped
            # edge rows begin. It is computed with max/min rather than left to
            # Python's negative-index wrap-around: when the kernel radius
            # exceeds the frame height (a 9-tap Bayer PSF on a 2-row frame),
            # ``slice(0, h - d)`` with h - d < 0 silently selected rows from the
            # far end instead of nothing, and the shifted sum then raised
            # "non-broadcastable output operand". For every h >= len(kernel)//2
            # - which is every frame the sim renders - these are the same
            # slices as before, so no pixel moves.
            if d < 0:
                split = min(-d, h)
                parts = ((slice(0, split), img[0:1]),
                         (slice(split, h), img[0:max(h + d, 0)]))
            elif d == 0:
                parts = ((slice(0, h), img),)
            else:
                split = max(h - d, 0)
                parts = ((slice(0, split), img[d:h]),
                         (slice(split, h), img[h - 1:h]))
            for osl, src in parts:
                o = out[osl]
                if first:
                    np.multiply(src, k, out=o)
                else:
                    t = tmp[osl]
                    np.multiply(src, k, out=t)
                    o += t
            first = False
        return out

    n = h * w
    if 2 * r < w:
        fi = img.reshape(-1)
        fo = out.reshape(-1)
        ft = tmp.reshape(-1)
        dst = fo[r:n - r]
        first = True
        for d, k in taps:
            src = fi[r + d:n - r + d]
            if first:
                np.multiply(src, k, out=dst)
                first = False
            else:
                t = ft[r:n - r]
                np.multiply(src, k, out=t)
                dst += t
    if r:
        cols, xs = _edge_cols(w, r, tuple(d for d, _ in taps))
        sub = img[:, xs].reshape(h, len(taps), len(cols))
        acc = sub[:, 0, :] * taps[0][1]
        for j in range(1, len(taps)):
            acc = acc + sub[:, j, :] * taps[j][1]
        out[:, cols] = acc
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
        # A 1x1 frame has zero corner radius; ``or 1.0`` keeps r = 0 there
        # instead of 0/0 = nan. For every h,w with h > 1 or w > 1 the value is
        # unchanged, so no shipped frame size moves by a bit.
        r_corner = math.hypot((w - 1) / 2.0, (h - 1) / 2.0) or 1.0
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
            # ``max(.., 1)``: with h == 1 (or w == 1) the old ``dev.integers(0, 0)``
            # raised "ValueError: high <= 0", so a 1-pixel-tall or 1-pixel-wide
            # model could not be constructed at all with dead pixels on. For every
            # h, w >= 2 the draw is byte-for-byte the one it always was, and so is
            # the clamp below (cy <= h - 2 and oy <= 1 can never exceed h - 1).
            ys = dev.integers(0, max(h - 1, 1), n_clusters)
            xs = dev.integers(0, max(w - 1, 1), n_clusters)
            vals = np.where(dev.random(n_clusters) < 0.5, 0.0, 255.0).astype(np.float32)
            iy, ix, iv = [], [], []
            for cy, cx, v in zip(ys, xs, vals):
                for oy in (0, 1):
                    for ox in (0, 1):
                        iy.append(min(cy + oy, h - 1))
                        ix.append(min(cx + ox, w - 1))
                        iv.append(v)
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

        # Reusable per-frame scratch (spec 8, implementation rule 1 extended to
        # the working buffers as well as the static maps). ``apply`` allocated
        # roughly twenty 316-632 KB temporaries per frame; on a 1000-frame run
        # that churn, not the arithmetic, is what produced 5-14 ms outlier
        # frames against a 1.9 ms median. Buffers are created on first use and
        # keyed by (name, shape, dtype) so the float64 RGB path and the float32
        # grayscale/Bayer paths can coexist on one instance.
        #
        # BOUNDED (_MAX_SCRATCH, least-recently-used eviction). The key includes
        # the shape, so without a bound a caller that varied the frame size would
        # grow this dict - and its arrays - without limit. ``apply`` also rejects
        # any frame that is not this model's size, which keeps the live key set to
        # about a dozen in practice; the cap is the backstop for ``_buf`` itself.
        self._bufs: OrderedDict = OrderedDict()

        # ``apply`` runs in place against those buffers, so two concurrent calls
        # on ONE model would interleave and corrupt each other's pixels. The lock
        # is never waited on: a second caller is a bug, and gets told so.
        self._busy = threading.Lock()

        # Bookkeeping.
        self.frames = 0
        self._cost_ms: list[float] = []
        # CPU time as well as wall clock: on a shared Mac the sim, the renderer
        # and the follower all compete, and a frame that is slow on the wall
        # clock but not on the CPU clock was the machine, not this model. The
        # budget in spec 8 is about our own work, so record both.
        self._cpu_ms: list[float] = []
        self._dsnu_gain = None        # cache for dsnu * gain (gain is piecewise constant)
        self._dsnu_scaled = None
        self._info_path = None
        self._info_every = 100

    # --- scratch buffers ---------------------------------------------------
    def _buf(self, name, shape, dtype):
        """A reused scratch array. Contents are never assumed; always overwritten.

        The pool is capped at ``_MAX_SCRATCH`` entries and evicts the least
        recently used one. Eviction is safe because no step ever reads a buffer
        before writing it: the worst an eviction can cost is one re-allocation,
        never a wrong pixel. In the shipped configuration nothing is ever
        evicted - a fixed frame size needs about a dozen keys.
        """
        # np.dtype(dtype): ``np.float64`` (the type) and ``img.dtype`` (a
        # np.dtype instance) compare equal but hash differently, so the raw
        # argument used to key A/B/T twice and keep two 618 KB copies of each.
        # Normalising is pure bookkeeping - buffers are always written before
        # they are read, and _pingpong still never returns the array it was
        # handed - so no pixel moves; test_optimised_chain_is_bit_identical_to_
        # the_reference covers it.
        key = (name, shape, np.dtype(dtype))
        a = self._bufs.get(key)
        if a is None:
            a = np.empty(shape, dtype)
            self._bufs[key] = a
            if len(self._bufs) > _MAX_SCRATCH:
                self._bufs.popitem(last=False)
        else:
            self._bufs.move_to_end(key)
        return a

    def _pingpong(self, cur, dtype):
        """The scratch buffer that is NOT ``cur`` (convolution cannot alias)."""
        a = self._buf("A", self._shape, dtype)
        return self._buf("B", self._shape, dtype) if cur is a else a

    def _conv(self, img, kernel, axis):
        """Allocation-free ``_convolve_axis`` using this instance's buffers."""
        return _convolve_axis(img, kernel, axis,
                              out=self._pingpong(img, img.dtype),
                              tmp=self._buf("T", self._shape, img.dtype))

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
                    grayscale (tests). H and W must be the height and width this
                    model was constructed with - see ``_check_frame``.
        ``omega`` : body angular rate [wx, wy, wz] rad/s for motion blur.
        ``dt``    : seconds since the previous camera frame (AE loop steps).

        **NOT REENTRANT, and not thread-safe.** Every step runs in place against
        scratch buffers owned by this instance, so two overlapping ``apply`` calls
        on the same model would write over each other's intermediates and hand
        both callers wrong pixels - silently, since the result is still a
        plausible uint8 frame. (The pre-optimisation version allocated its
        temporaries per call and tolerated this.) A second concurrent call
        therefore raises ``RuntimeError`` instead of corrupting the frame. The AE
        loop and the RNG stream are per-instance state as well, so concurrent use
        was never meaningful even before the buffers existed: give each camera its
        own ``CameraModel`` and drive it from one thread.

        The guard is a non-blocking lock and never waits. Measured: the
        uncontended acquire/release pair is 0.096 us, and the whole wrapper
        (lock plus the extra call into ``_apply``) costs 0.59 us against a
        1.208 ms frame - 0.05%.
        """
        if not self._busy.acquire(False):
            raise RuntimeError(
                "CameraModel.apply() is already running on this instance. It is "
                "not reentrant: the per-frame scratch buffers, the AE state and "
                "the RNG stream all belong to the instance, so overlapping calls "
                "would corrupt each other's pixels. Use one CameraModel per "
                "camera and call it from a single thread.")
        try:
            return self._apply(rgb, omega, dt)
        finally:
            self._busy.release()

    def _check_frame(self, rgb: np.ndarray) -> None:
        """Reject a frame this model cannot process, and say why.

        Deliberate, not a regression to paper over: PRNU, DSNU, the dead-pixel
        map, the vignette map and the distortion map are per-pixel arrays built
        at construction for exactly one frame size, and the AE loop's history
        belongs to that sensor. Degrading a differently-sized frame with them is
        meaningless, so it is an error rather than a silent resize. Before the
        in-place rewrite this surfaced as a raw numpy broadcast message (or, for
        a preset with every fixed-pattern field off, as a quietly wrong frame).
        """
        h, w = self.height, self.width
        if rgb.ndim not in (2, 3):
            raise ValueError(
                f"CameraModel.apply() wants a (H, W) grayscale or (H, W, C>=3) "
                f"colour frame; got an array with {rgb.ndim} dimension(s), "
                f"shape {tuple(rgb.shape)}.")
        if rgb.ndim == 3 and rgb.shape[2] < 3:
            raise ValueError(
                f"CameraModel.apply() wants at least 3 colour channels (RGB or "
                f"RGBA); got shape {tuple(rgb.shape)} with {rgb.shape[2]}.")
        if rgb.shape[:2] != self._shape:
            raise ValueError(
                f"CameraModel(preset={self.preset!r}) was built for {w}x{h} "
                f"frames (width x height) and was handed a "
                f"{rgb.shape[1]}x{rgb.shape[0]} one. This is on purpose: the "
                f"PRNU, DSNU, dead-pixel, vignette and distortion maps are "
                f"per-pixel arrays for exactly that size, so there is no correct "
                f"way to apply them to a different frame. Build a second model "
                f"with CameraModel({self.preset!r}, width={rgb.shape[1]}, "
                f"height={rgb.shape[0]}, seed={self.seed}) - or from_env(width, "
                f"height) - for the other size.")

    def _apply(self, rgb: np.ndarray, omega: np.ndarray | None = None,
               dt: float = 0.05) -> np.ndarray:
        """The chain itself. Call ``apply``; this one has no reentrancy guard."""
        self._check_frame(rgb)
        t_start = time.perf_counter()
        c_start = time.thread_time()
        p = self.params

        # Every step below is written in-place against reused buffers. The
        # arithmetic is byte-for-byte what the allocating version did - see
        # test_optimised_chain_is_bit_identical_to_the_reference in
        # test_camera_model.py, which re-derives each step the long way and
        # compares uint8 output and intermediate dtypes.

        # 1. Scene radiance, linear, one channel per photosite.
        if rgb.ndim == 3:
            if p.bayer:
                m_r, m_g, m_b = self._bayer_masks
                f = self._buf("rgb32", rgb.shape[:2] + (3,), np.float32)
                np.copyto(f, rgb[..., :3], casting="unsafe")     # == .astype(np.float32)
                L = self._buf("A", self._shape, np.float32)
                t = self._buf("T", self._shape, np.float32)
                np.multiply(f[..., 0], m_r, out=L)
                np.multiply(f[..., 1], m_g, out=t); L += t
                np.multiply(f[..., 2], m_b, out=t); L += t
                L /= 255.0
            elif rgb.dtype == np.uint8:
                # uint8 -> float64 is exact, so this is the same input the
                # np.dot form gave BLAS after its float32 -> float64 cast.
                b = self._buf("rgb64", rgb.shape[:2] + (3,), np.float64)
                np.copyto(b, rgb[..., :3], casting="unsafe")
                L = np.matmul(b, REC601_W, out=self._buf("A", self._shape, np.float64))
                L /= 255.0
            else:
                # Not the simulator's path (it always renders uint8). Keep the
                # original expression verbatim: for a float input the float32
                # round-trip is not a no-op and must not be skipped.
                L = (np.dot(rgb[..., :3].astype(np.float32), REC601) / 255.0)
        else:
            L = self._buf("A", self._shape, np.float32)
            np.copyto(L, rgb, casting="unsafe")                  # == .astype(np.float32)
            L /= 255.0

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
            L = self._conv(self._conv(L, self._psf, 1), self._psf, 0)

        # 4. Vignetting / relative illumination.
        if self._has_vignette:
            L *= self._vignette

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
                L = self._conv(L, _box_kernel(lx), 1)
            if ly > p.motion_blur_min_px:
                L = self._conv(L, _box_kernel(ly), 0)

        # 6. Row-wise LED banding. Flicker avoidance is off (FS_CTRL = 0x00),
        # so the rolling shutter turns mains-frequency light into moving bands.
        if p.banding_depth > 0:
            phase = float(self._rng.uniform(0.0, 2.0 * math.pi))
            band = 1.0 + p.banding_depth * np.sin(
                2.0 * math.pi * self._row_idx / BANDING_PERIOD_ROWS + phase)
            L *= band.astype(np.float32)

        # 7. Exposure and gain -> DN.
        g = self.total_gain
        S = L
        S *= (255.0 * p.scene_light * self.exposure_factor)

        # 8/9. Fixed-pattern noise: multiplicative gain, then additive offset.
        if self._prnu is not None:
            S *= self._prnu
        if self._dsnu is not None:
            # dsnu * g is a whole-frame multiply the AE loop only invalidates
            # when it moves a gain step, which is rare; cache it.
            if self._dsnu_gain != g:
                self._dsnu_scaled = self._dsnu * g
                self._dsnu_gain = g
            S += self._dsnu_scaled

        # 10. Shot + read noise in one Gaussian draw. A Gaussian is exact above
        # ~20 e- (the AE target is 1740 e-) and costs a quarter of rng.poisson.
        if p.shot_noise or p.read_noise:
            var = self._buf("var", self._shape, S.dtype)
            read_var = (READ_NOISE_E * g / E_PER_DN_1X) ** 2
            if p.shot_noise:
                np.maximum(S, 0.0, out=var)
                var *= g
                var /= E_PER_DN_1X
                if p.read_noise:
                    var += read_var
            else:
                var.fill(read_var)
            np.sqrt(var, out=var)
            nd = self._buf("nd", self._shape, np.float64)
            self._rng.standard_normal(self._shape, out=nd)
            n32 = self._buf("n32", self._shape, np.float32)
            np.copyto(n32, nd, casting="unsafe")                 # == .astype(np.float32)
            var *= n32                                           # == n32 * sqrt(var)
            S += var

        # 11. Dead-pixel clusters (what on-chip DPC does not repair).
        if self._dead_idx is not None:
            iy, ix, iv = self._dead_idx
            S[iy, ix] = iv

        # 12. Clip to full well, round half up, 8 bit. Quantisation happens
        # last, after noise, rather than being inherited from the render.
        # maximum-then-minimum is np.clip's own definition for finite input and
        # runs 1.3x faster in place than np.clip(out=...); S is finite here
        # (every term above is a finite float times a finite float).
        np.maximum(S, 0.0, out=S)
        np.minimum(S, 255.0, out=S)
        S += 0.5
        np.floor(S, out=S)
        out = S.astype(np.uint8)          # a fresh array: callers keep frames

        # 13. The AE loop meters this frame and sets exposure for the next one,
        # which is where the real loop's one-frame lag comes from.
        self._ae_update(float(out.mean()), dt)

        self.frames += 1
        self._cost_ms.append((time.perf_counter() - t_start) * 1000.0)
        self._cpu_ms.append((time.thread_time() - c_start) * 1000.0)
        if self._info_path and self.frames % self._info_every == 0:
            self._write_info()
        return out

    # --- reporting ---------------------------------------------------------
    def cost_stats(self) -> dict:
        """Per-frame cost on both clocks, plus two honestly-named tail counters.

        ``*_ms`` are wall clock. ``cpu_*`` are this thread's CPU time
        (``time.thread_time()``), which excludes time the OS spent *running*
        something else but does NOT exclude the cost that something else imposes
        on us: cache-miss stall time is charged to this thread, so CPU time
        inflates under memory contention just like wall time, only less.

        ``cpu_median_ms`` is the number to judge this model by. Measured on an
        M4 Pro while 0, 4, 8 and 14 bandwidth-heavy processes ran alongside, the
        median frame moved 1.20 -> 1.54 ms (+28%) while the worst frame moved
        1.1 -> 6.7 ms (+500%) - the median degrades gracefully, the tail does not.
        ``test_worst_frame_cost_with_motion_blur_on_every_frame`` therefore gates
        on the median, twice: once in machine-independent elementwise passes,
        which is what catches a regression, and once against spec 8's 5 ms
        outright, which is what says the chain fits the budget on this machine.
        Both live in that file's ``_assert_frame_budget``. Re-measured
        2026-09-12: ``cpu_p95_ms`` is NOT a usable gate either - on a healthy
        chain it ran 0.95-1.74 ms idle but 3.12-5.96 ms under a 14-process
        bandwidth load, breaching 5 ms on 3 of 9 bursts with no code change,
        while the median stayed inside 1.16-1.54 ms throughout.

        **The two ``over_5ms`` counters are observations, not verdicts.** They say
        "this many frames took over 5 ms", on the named clock. They do NOT say the
        model breached spec 8's 5 ms budget: on the same bench, a chain whose worst
        frame is 1.1-2.2 ms on a quiet machine reported 4.0-6.7 ms of CPU (and up
        to 35 ms of wall) with 14 competing processes, with no code change at all.
        They were called ``over_budget_frames``, which read as a verdict; the name
        is now the measurement. To turn a non-zero count into a statement about
        the model, re-measure the same preset on an idle machine, or compare
        ``cpu_median_ms`` against a quiet-machine run - the tail alone cannot tell
        a slow model from a busy laptop, and neither clock can.
        """
        if not self._cost_ms:
            return {}
        a = np.asarray(self._cost_ms)
        d = {"frames": int(a.size), "mean_ms": round(float(a.mean()), 3),
             "median_ms": round(float(np.median(a)), 3),
             "p95_ms": round(float(np.percentile(a, 95)), 3),
             "max_ms": round(float(a.max()), 3),
             "wall_over_5ms_frames": int((a > 5.0).sum())}
        if self._cpu_ms:
            c = np.asarray(self._cpu_ms)
            d["cpu_mean_ms"] = round(float(c.mean()), 3)
            d["cpu_median_ms"] = round(float(np.median(c)), 3)
            d["cpu_p95_ms"] = round(float(np.percentile(c, 95)), 3)
            d["cpu_max_ms"] = round(float(c.max()), 3)
            d["cpu_over_5ms_frames"] = int((c > 5.0).sum())
        d["over_5ms_note"] = ("counts, not verdicts: a busy machine inflates both "
                              "clocks; compare cpu_median_ms with a quiet run "
                              "before calling it a budget breach")
        return d

    def reset_cost(self) -> None:
        """Drop the timing history (used to discard warm-up frames)."""
        self._cost_ms.clear()
        self._cpu_ms.clear()

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
