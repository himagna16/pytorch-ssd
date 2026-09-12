#!/usr/bin/env python3
"""Unit tests for camera_model.py: does each effect do what spec_camera.md says?

Run with the team python (needs numpy only):

    ../../../trainenv/bin/python test_camera_model.py [-v]

Every test states the number the spec predicts and the tolerance it is checked
to, so a failure says which parameter drifted rather than just "not equal".
No pytest dependency: this is a plain script with a tiny runner.
"""
import math
import sys
import threading
import time
import tracemalloc
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import camera_model as cm

VERBOSE = "-v" in sys.argv
TESTS = []


def test(fn):
    TESTS.append(fn)
    return fn


def note(msg):
    if VERBOSE:
        print(f"      {msg}")


def close(a, b, rel=0.1, what=""):
    if b == 0:
        assert abs(a) <= rel, f"{what}: {a} not within {rel} of 0"
        return
    assert abs(a - b) / abs(b) <= rel, \
        f"{what}: measured {a:.4f} vs predicted {b:.4f} ({abs(a - b) / abs(b):.1%} > {rel:.0%})"


def flat(level_dn, h=244, w=324):
    """A uniform gray frame at the given DN level."""
    return np.full((h, w), level_dn, np.uint8)


def bare(**over):
    """A model with every effect off, so one effect can be switched on alone."""
    base = dict(psf_sigma_center_px=0.0, vignette_a2=0.0, vignette_a4=0.0,
                motion_blur=False, shot_noise=False, read_noise=False,
                prnu_sigma=0.0, dsnu_sigma_dn=0.0, dead_px_frac=0.0,
                banding_depth=0.0, ae_fixed_exposure=1.0, scene_light=1.0)
    base.update(over)
    return cm.CameraModel("himax_typical", seed=99, overrides=base)


# --- 1. the clean contract --------------------------------------------------

@test
def test_clean_is_byte_identical_pass_through():
    """clean must take today's exact code path, not a zeroed model (spec 4.2)."""
    import os
    for var in ("CRAZYSIM_SENSOR_PRESET",):
        os.environ.pop(var, None)
    assert cm.from_env() is None, "unset preset must return None (pass-through)"
    os.environ["CRAZYSIM_SENSOR_PRESET"] = "clean"
    assert cm.from_env() is None, "'clean' must also return None"
    os.environ["CRAZYSIM_SENSOR_PRESET"] = "  "
    assert cm.from_env() is None, "blank preset must return None"
    os.environ.pop("CRAZYSIM_SENSOR_PRESET")

    # Replay the patched simulator's branch and compare bytes with the original.
    rng = np.random.default_rng(0)
    for _ in range(20):
        pixels = rng.integers(0, 256, (244, 324, 3), dtype=np.uint8)
        original = np.dot(pixels[..., :3], [0.2989, 0.5870, 0.1140]).astype(np.uint8)
        sensor = cm.from_env()
        patched = (np.dot(pixels[..., :3], [0.2989, 0.5870, 0.1140]).astype(np.uint8)
                   if sensor is None else sensor.apply(pixels))
        assert patched.tobytes() == original.tobytes(), "clean path changed the bytes"
    note("20 random frames: patched clean path is byte-identical")


@test
def test_bad_preset_and_bad_override_are_rejected():
    for bad in ("himax", "", "HIMAX_TYPICAL"):
        try:
            cm.CameraModel(bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"preset {bad!r} should have been rejected")
    try:
        cm.CameraModel("himax_typical", overrides={"psf_sigma": 1.0})
    except ValueError:
        pass
    else:
        raise AssertionError("unknown override should have been rejected")


# --- 2. noise ---------------------------------------------------------------

@test
def test_shot_and_read_noise_sigma_matches_the_photon_transfer_model():
    """sigma(S) = sqrt(S*g/29 + (0.162*g)^2 + 1/12) DN, measured temporally (spec 3.1)."""
    n_frames = 300
    for gain, rel in ((1.0, 0.10), (8.0, 0.10)):
        m = bare(shot_noise=True, read_noise=True)
        m._again = gain                      # AE is pinned; drive gain directly
        for level in (20, 60, 120, 200):
            src = flat(level)
            stack = np.stack([m.apply(src).astype(np.float32) for _ in range(n_frames)])
            measured = float(stack.std(axis=0).mean())
            S = float(level)                 # exposure factor 1, light 1 -> S = level
            predicted = math.sqrt(S * gain / cm.E_PER_DN_1X
                                  + (cm.READ_NOISE_E * gain / cm.E_PER_DN_1X) ** 2
                                  + 1.0 / 12.0)
            note(f"gain {gain:.0f}x, S={level:3d} DN: measured sigma {measured:.3f}, "
                 f"predicted {predicted:.3f}")
            close(measured, predicted, rel, f"noise sigma at {level} DN, gain {gain}x")


@test
def test_noise_variance_is_linear_in_signal_with_the_derived_slope():
    """The photon transfer curve's slope is 1/29 DN per DN at 1x (spec 9.1)."""
    m = bare(shot_noise=True, read_noise=True)
    levels = np.array([20, 60, 100, 140, 180, 220], float)
    var = []
    for lv in levels:
        stack = np.stack([m.apply(flat(int(lv))).astype(np.float32) for _ in range(300)])
        var.append(float((stack.std(axis=0) ** 2).mean()))
    slope, intercept = np.polyfit(levels, np.array(var), 1)
    note(f"fitted slope {slope:.5f} DN/DN (predicted {1 / cm.E_PER_DN_1X:.5f}), "
         f"intercept {intercept:.4f} DN^2")
    close(slope, 1.0 / cm.E_PER_DN_1X, 0.10, "photon transfer slope")
    assert intercept < 1.0, f"intercept {intercept:.3f} DN^2 should be below 1 DN^2"


@test
def test_fixed_pattern_noise_is_fixed_and_temporal_noise_is_not():
    """PRNU/DSNU must be static per device; two frames must match exactly (spec 3.4)."""
    m = bare(prnu_sigma=0.008, dsnu_sigma_dn=0.4)
    src = flat(120)
    a, b = m.apply(src), m.apply(src)
    assert a.tobytes() == b.tobytes(), "fixed-pattern-only frames should be identical"
    # And the pattern must actually be there.
    plain = bare().apply(src)
    assert not np.array_equal(a, plain), "PRNU/DSNU had no effect"
    note(f"FPN spatial std {float(a.astype(np.float32).std()):.3f} DN at 120 DN "
         f"(PRNU 0.8% -> ~1.0 DN)")


@test
def test_dead_pixels_are_stuck_clusters_at_fixed_places():
    m = bare(dead_px_frac=1e-5)
    src = flat(120)
    a, b = m.apply(src), m.apply(src)
    bad_a = np.argwhere((a == 0) | (a == 255))
    assert np.array_equal(bad_a, np.argwhere((b == 0) | (b == 255))), \
        "dead pixels moved between frames"
    n_clusters = max(1, int(round(244 * 324 * 1e-5)))
    assert len(bad_a) == 4 * n_clusters, \
        f"expected {4 * n_clusters} stuck pixels (2x2 clusters), found {len(bad_a)}"
    note(f"{len(bad_a)} stuck pixels in {n_clusters} 2x2 cluster(s) at {bad_a[0].tolist()}")


# --- 3. optics --------------------------------------------------------------

@test
def test_psf_blur_width_matches_the_preset_sigma():
    """A separable Gaussian PSF of sigma s gives a marginal profile of variance s^2 (spec 3.2)."""
    for sigma in (0.65, 1.15):
        m = bare(psf_sigma_center_px=sigma)
        src = np.zeros((244, 324), np.uint8)
        src[122, 162] = 255
        out = m.apply(src).astype(np.float64)
        prof = out.sum(axis=0)                       # marginal over rows -> 1-D x kernel
        x = np.arange(prof.size)
        mu = (prof * x).sum() / prof.sum()
        measured = math.sqrt((prof * (x - mu) ** 2).sum() / prof.sum())
        note(f"PSF sigma {sigma:.2f} px: measured {measured:.3f} px "
             f"(FWHM {2.355 * measured:.2f} px)")
        close(measured, sigma, 0.12, f"PSF sigma {sigma}")


@test
def test_no_psf_leaves_edges_sharp():
    m = bare(psf_sigma_center_px=0.0)
    src = np.zeros((244, 324), np.uint8)
    src[:, 162:] = 200
    out = m.apply(src)
    assert out[122, 161] == 0 and out[122, 162] == 200, "unblurred edge was softened"


@test
def test_vignetting_profile_matches_the_radial_polynomial():
    """V(r) = 1 - a2 r^2 - a4 r^4, r = 1 at the corner: 0.82 at the edge, 0.68 in the corner."""
    a2, a4 = 0.22, 0.10
    m = bare(vignette_a2=a2, vignette_a4=a4)
    level = 200
    out = m.apply(flat(level)).astype(np.float64)
    h, w = out.shape
    centre = out[h // 2, w // 2]
    corner = out[0, 0]
    edge = out[h // 2, 0]
    r_edge = ((w - 1) / 2.0) / math.hypot((w - 1) / 2.0, (h - 1) / 2.0)
    pred_corner = 1 - a2 - a4
    pred_edge = 1 - a2 * r_edge ** 2 - a4 * r_edge ** 4
    note(f"centre {centre:.0f} DN, edge {edge / centre:.3f} (predicted {pred_edge:.3f}), "
         f"corner {corner / centre:.3f} (predicted {pred_corner:.3f})")
    close(centre, level, 0.01, "vignette centre")
    close(edge / centre, pred_edge, 0.02, "vignette at horizontal edge")
    close(corner / centre, pred_corner, 0.02, "vignette at corner")
    # Monotonic falloff along the centre row.
    row = out[h // 2, w // 2:]
    assert np.all(np.diff(row) <= 0.5), "vignette is not monotonic outward"


# --- 4. motion blur ---------------------------------------------------------

@test
def test_motion_blur_length_scales_with_angular_rate():
    """L = omega * t_exp * focal px; the kernel is a box, variance L^2/12 + 1/12 (spec 3.6)."""
    m = bare(motion_blur=True, psf_sigma_center_px=0.0)
    m._t_lines = float(cm.MAX_INTG_LINES)            # AE ceiling: t_exp = 10.56 ms
    t_exp = m.exposure_time_s
    focal = m.params.focal_px_per_rad
    note(f"t_exp {t_exp * 1e3:.2f} ms, focal {focal:.1f} px/rad")

    src = np.zeros((244, 324), np.uint8)
    src[122, 162] = 255
    recovered = []
    rates = [40.0, 80.0, 160.0, 320.0]               # deg/s
    for deg in rates:
        w = math.radians(deg)
        out = m.apply(src, np.array([0.0, 0.0, w]), 0.077).astype(np.float64)
        prof = out.sum(axis=0)
        x = np.arange(prof.size)
        mu = (prof * x).sum() / prof.sum()
        var = (prof * (x - mu) ** 2).sum() / prof.sum()
        L_pred = w * t_exp * focal
        L_meas = math.sqrt(max(12.0 * (var - 1.0 / 12.0), 0.0))
        note(f"  yaw {deg:5.0f} deg/s: predicted L {L_pred:.2f} px, measured {L_meas:.2f} px")
        recovered.append((L_pred, L_meas))
        close(L_meas, L_pred, 0.15, f"motion blur length at {deg} deg/s")

    # Linear in the rate: doubling the rate must double the blur length.
    for (p0, m0), (p1, m1) in zip(recovered, recovered[1:]):
        close(m1 / m0, 2.0, 0.15, "blur length doubling with rate")


@test
def test_sub_pixel_motion_blur_actually_softens_the_image():
    """The flight-relevant regime is SUB-pixel, and it must not be a no-op.

    Regression test for a silent bug: _box_kernel used to size its support as
    ceil(L), so every smear with 0 < L <= 1 px collapsed to the single tap
    [1.0] - an identity. The 0.5 px gate admitted lengths in (0.5, 1.0] and
    then threw them away. At the exposure the himax flight actually ran
    (137 lines = 4.257 ms) the follower's own 40 deg/s yaw cap is 0.52 px, so
    100% of real motion blur lived in the broken band.
    """
    m = bare(motion_blur=True, psf_sigma_center_px=0.0)
    m._t_lines = 137.0                                # the in-flight exposure
    w = math.radians(40.0)                            # the follower's yaw cap
    L = w * m.exposure_time_s * m.params.focal_px_per_rad
    note(f"L = {L:.3f} px at the 40 deg/s cap and the in-flight 4.257 ms exposure")
    assert L <= 1.0, "this test is meant to exercise the sub-pixel regime"
    assert L > m.params.motion_blur_min_px, "the gate must not discard real sub-pixel smear"

    k = cm._box_kernel(L)
    off = np.arange(len(k)) - (len(k) - 1) / 2.0
    var = float((k * (off - float((k * off).sum())) ** 2).sum())
    note(f"kernel {np.round(k, 4)}  variance {var:.4f} vs L^2/12 = {L * L / 12:.4f}")
    close(var, L * L / 12.0, 0.02, "sub-pixel kernel second moment")
    assert len(k) >= 3 and k.max() < 1.0, f"sub-pixel kernel is degenerate: {k}"

    src = np.zeros((244, 324), np.uint8)
    src[122, 150:163] = 255                            # a hard vertical edge at 162|163
    out = m.apply(src, np.array([0.0, 0.0, w]), 0.077)
    spill = int(out[122, 163])
    note(f"edge pixels after blur: {out[122, 160:166]}  (spill across the edge {spill} DN)")
    assert spill > 0, "sub-pixel yaw left the frame untouched - the blur is a no-op again"
    assert out[122, 162] < 255, "the bright side of the edge should have been pulled down"


@test
def test_box_kernel_is_sane_across_every_regime():
    """One kernel function has to cover 0.05 px to 10 px without degenerating."""
    for L in (0.05, 0.35, 0.52, 0.7, 1.0, 1.12, 1.285, 2.0, 3.0, 5.14, 10.28):
        k = cm._box_kernel(L)
        off = np.arange(len(k)) - (len(k) - 1) / 2.0
        var = float((k * (off - float((k * off).sum())) ** 2).sum())
        note(f"  L {L:6.3f}: {len(k):2d} taps, variance {var:8.4f}, L^2/12 {L * L / 12:8.4f}")
        assert abs(k.sum() - 1.0) < 1e-5, f"L={L}: kernel is not normalised ({k.sum()})"
        assert (k >= 0).all(), f"L={L}: negative tap in {k}"
        assert len(k) % 2 == 1, f"L={L}: kernel must be centred (odd length), got {len(k)}"
        assert var > 0, f"L={L}: kernel is an identity, blur would be a no-op"
        # Enough taps to carry the smear: a 10 px smear cannot live on 3 taps.
        if L > 2.0:
            assert len(k) >= L - 1, f"L={L}: only {len(k)} taps, smear cannot be represented"
        # Never wildly more blur than the smear justifies. The bound allows two
        # pixel apertures: resampling a box onto a coarse grid legitimately
        # overshoots L^2/12 + 1/12 in the mid range (L = 2 px lands on exactly
        # 0.5 against 0.4167), which is binning, not excess blur.
        assert var <= L * L / 12.0 + 1.0 / 6.0 + 0.02, \
            f"L={L}: variance {var:.4f} exceeds L^2/12 plus two pixel apertures"


@test
def test_pitch_rate_blurs_vertically_and_yaw_horizontally():
    m = bare(motion_blur=True, psf_sigma_center_px=0.0)
    m._t_lines = float(cm.MAX_INTG_LINES)
    src = np.zeros((244, 324), np.uint8)
    src[122, 162] = 255
    w = math.radians(200.0)
    yaw = m.apply(src, np.array([0.0, 0.0, w]), 0.077)
    pitch = m.apply(src, np.array([0.0, w, 0.0]), 0.077)
    assert yaw[122].sum() > yaw[:, 162].sum(), "yaw did not smear horizontally"
    assert pitch[:, 162].sum() > pitch[122].sum(), "pitch did not smear vertically"


# --- 5. auto exposure -------------------------------------------------------

@test
def test_ae_drives_the_frame_mean_to_the_target():
    """AE_TARGET_MEAN = 0x3C: the loop must settle the mean at 60 DN (spec 3.5)."""
    for level in (30, 100, 165, 240):
        m = cm.CameraModel("himax_typical", seed=3,
                           overrides=dict(shot_noise=False, read_noise=False,
                                          prnu_sigma=0.0, dsnu_sigma_dn=0.0,
                                          dead_px_frac=0.0, vignette_a2=0.0,
                                          vignette_a4=0.0, psf_sigma_center_px=0.0))
        src = flat(level)
        for _ in range(40):
            out = m.apply(src, None, 0.077)
        err = abs(float(out.mean()) - cm.AE_TARGET_DN)
        note(f"scene {level:3d} DN -> converged mean {out.mean():6.2f} DN, "
             f"{m.state()['exposure_lines']:.0f} lines, {m.state()['analog_gain']:.0f}x")
        assert err <= cm.AE_CONVERGE_OUT_DN, \
            f"scene {level} DN converged to {out.mean():.1f} DN, {err:.1f} DN off target"


@test
def test_ae_lags_a_light_change_instead_of_correcting_instantly():
    """DAMPING_FACTOR = 0x20: a partial correction per sensor frame (~65 ms, spec 3.5)."""
    m = cm.CameraModel("himax_typical", seed=3,
                       overrides=dict(shot_noise=False, read_noise=False,
                                      prnu_sigma=0.0, dsnu_sigma_dn=0.0,
                                      dead_px_frac=0.0, vignette_a2=0.0,
                                      vignette_a4=0.0, psf_sigma_center_px=0.0))
    bright, dim = flat(200), flat(50)
    for _ in range(40):
        m.apply(bright, None, 0.077)
    first = float(m.apply(dim, None, 0.077).mean())    # exposure still set for 'bright'
    assert abs(first - cm.AE_TARGET_DN) > cm.AE_CONVERGE_OUT_DN, \
        f"AE corrected a 4x light drop instantly (mean {first:.1f}); there is no lag"
    means = [float(m.apply(dim, None, 0.077).mean()) for _ in range(6)]
    note(f"after the drop: {first:.1f} DN, then {', '.join(f'{v:.1f}' for v in means)}")
    settle = next((i for i, v in enumerate(means)
                   if abs(v - cm.AE_TARGET_DN) <= cm.AE_CONVERGE_OUT_DN), None)
    assert settle is not None, f"AE never reconverged: {means}"
    note(f"reconverged after {(settle + 2) * 77:.0f} ms of camera frames")


@test
def test_exposure_ceiling_forces_gain_in_the_low_light_preset():
    """himax_low_light must pin integration and reach ~8x TOTAL gain (spec 4.2)."""
    m = cm.CameraModel("himax_low_light", seed=5)
    src = flat(165)                                    # a typical rendered scene mean
    for _ in range(60):
        out = m.apply(src, None, 0.077)
    st = m.state()
    total = st["analog_gain"] * st["digital_gain"]
    note(f"low light: {st['exposure_lines']:.0f} lines (ceiling {cm.MAX_INTG_LINES}), "
         f"analog {st['analog_gain']:.0f}x, digital {st['digital_gain']:.2f}x, "
         f"TOTAL {total:.2f}x, mean {out.mean():.1f} DN")
    assert st["exposure_lines"] == cm.MAX_INTG_LINES, "integration ceiling should bind"
    # Gate on TOTAL gain, not the analog step. The required ratio sits right on
    # _pick_gain's 4x/8x boundary, so the analog/digital split flips with the
    # noise seed - measured 9 of 20 seeds at analog 4x and 11 at 8x on a real
    # s01 render. The split is physically inert here (the noise model uses
    # total_gain for both the shot and read terms), so total gain is the
    # quantity that actually describes the preset.
    close(total, 8.0, 0.15, "himax_low_light total gain")
    assert abs(float(out.mean()) - cm.AE_TARGET_DN) <= cm.AE_CONVERGE_OUT_DN

    # And the noise must be the ~4.3 DN the spec's table predicts at 8x.
    m2 = cm.CameraModel("himax_low_light", seed=5,
                        overrides=dict(psf_sigma_center_px=0.0, vignette_a2=0.0,
                                       vignette_a4=0.0, prnu_sigma=0.0,
                                       dsnu_sigma_dn=0.0, dead_px_frac=0.0,
                                       banding_depth=0.0))
    for _ in range(60):
        m2.apply(src, None, 0.077)
    stack = np.stack([m2.apply(src, None, 0.077).astype(np.float32) for _ in range(200)])
    sigma = float(stack.std(axis=0).mean())
    predicted = math.sqrt(cm.AE_TARGET_DN * 8.0 / cm.E_PER_DN_1X
                          + (cm.READ_NOISE_E * 8.0 / cm.E_PER_DN_1X) ** 2 + 1 / 12.0)
    note(f"low-light temporal sigma {sigma:.2f} DN at the 60 DN target "
         f"(spec predicts {predicted:.2f} DN; himax_typical is ~1.5 DN)")
    close(sigma, predicted, 0.15, "low-light noise sigma")


# --- 6. banding, quantisation, colour --------------------------------------

@test
def test_led_banding_is_row_periodic_and_moves_between_frames():
    """FS_CTRL = 0x00 means no flicker avoidance: ~268-row bands that walk (spec 3.7)."""
    depth = 0.08
    m = bare(banding_depth=depth)
    src = flat(150)
    rows_a = m.apply(src).astype(np.float64).mean(axis=1)
    rows_b = m.apply(src).astype(np.float64).mean(axis=1)
    amp = (rows_a.max() - rows_a.min()) / 2.0 / rows_a.mean()
    note(f"row-profile modulation {amp:.3f} (preset depth {depth}); "
         f"frame-to-frame row RMS change {np.sqrt(((rows_a - rows_b) ** 2).mean()):.2f} DN")
    assert amp > 0.3 * depth, f"banding too weak: {amp:.4f}"
    assert amp <= depth * 1.05, f"banding too strong: {amp:.4f}"
    assert not np.allclose(rows_a, rows_b), "band phase did not move between frames"
    # A frame without banding must be flat across rows.
    flat_rows = bare().apply(src).astype(np.float64).mean(axis=1)
    # np.ptp(x), not x.ptp(): the method was removed in numpy 2.0 and the sim
    # venv (crazysimenv) is on 2.4.6.
    assert np.ptp(flat_rows) < 0.01, "rows are not flat with banding off"


@test
def test_quantisation_is_round_half_up_and_last():
    """8-bit quantisation happens after everything else, round half up (spec 3.9)."""
    m = bare()
    ramp = np.tile(np.linspace(0, 255, 324).astype(np.uint8), (244, 1))
    out = m.apply(ramp)
    expected = np.floor(np.clip(ramp.astype(np.float32) / 255.0 * 255.0, 0, 255) + 0.5).astype(np.uint8)
    assert out.dtype == np.uint8 and out.shape == (244, 324)
    assert np.array_equal(out, expected), "quantiser is not floor(x + 0.5)"
    # Explicit half-way case: 100.5 DN must round to 101.
    half = bare(ae_fixed_exposure=100.5 / 255.0 * (255.0 / 255.0))
    val = half.apply(flat(255))
    note(f"255 DN scaled to 100.5 -> {int(val[0, 0])}")
    assert int(val[0, 0]) == 101, f"round-half-up failed: got {int(val[0, 0])}"


@test
def test_bayer_2x2_average_is_the_fixed_weight_luma():
    """On an RGGB mosaic each 2x2 cell is (R + 2G + B)/4, phase independent (spec 3.10)."""
    m = cm.CameraModel("himax_color_bayer", seed=11,
                       overrides=dict(psf_sigma_center_px=0.0, vignette_a2=0.0,
                                      vignette_a4=0.0, shot_noise=False,
                                      read_noise=False, prnu_sigma=0.0,
                                      dsnu_sigma_dn=0.0, dead_px_frac=0.0,
                                      motion_blur=False, ae_fixed_exposure=1.0))
    r, g, b = 200, 120, 40
    src = np.zeros((244, 324, 3), np.uint8)
    src[..., 0], src[..., 1], src[..., 2] = r, g, b
    out = m.apply(src).astype(np.float64)
    # The mosaic itself: four distinct values in each 2x2 cell.
    assert int(out[0, 0]) == r and int(out[1, 1]) == b
    assert int(out[0, 1]) == g and int(out[1, 0]) == g
    block = out[:244 // 2 * 2, :324 // 2 * 2].reshape(122, 2, 162, 2).mean(axis=(1, 3))
    predicted = (r + 2 * g + b) / 4.0
    note(f"2x2 block average {block.mean():.2f} DN, predicted (R+2G+B)/4 = {predicted:.2f}; "
         f"Rec.601 luma would be {0.2989 * r + 0.5870 * g + 0.1140 * b:.2f}")
    close(float(block.mean()), predicted, 0.01, "Bayer 2x2 luma")
    assert float(block.std()) < 0.01, "2x2 average should be phase independent"


# --- 7. determinism and cost ------------------------------------------------

@test
def test_same_seed_reproduces_the_frame_exactly():
    src = flat(150)
    def run(seed):
        m = cm.CameraModel("himax_low_light", seed=seed)
        return b"".join(m.apply(src, np.array([0.0, 0.1, 0.4]), 0.077).tobytes()
                        for _ in range(8))
    assert run(42) == run(42), "same seed produced different frames"
    assert run(42) != run(43), "different seeds produced identical frames"


@test
def test_per_frame_cost_is_under_the_budget():
    """Spec 8's 5 ms/frame cap at the exposure the AE actually settles on.

    The companion to test_worst_frame_cost_with_motion_blur_on_every_frame,
    which pins the exposure at the integration ceiling instead. Both gate on
    the same statistic and for the same reason: this used to assert the WALL
    mean over 60 frames against a literal 5 ms, and a single descheduled frame
    can put 30+ ms of wall time into that mean on a laptop running a build (the
    worst wall frame measured while writing this was 196 ms, against a 0.93 ms
    median, with the chain unchanged). See that test's docstring for the
    measurements behind the 120-pass budget.
    """
    rng = np.random.default_rng(1)
    src = rng.integers(40, 220, (244, 324, 3), dtype=np.uint8)
    omega = np.array([0.0, 0.2, 0.6])
    print()
    for name in ("himax_typical", "himax_low_light", "himax_color_bayer"):
        m = cm.CameraModel(name, seed=1)
        for _ in range(10):
            m.apply(src, omega, 0.077)              # warm up, settle AE
        (passes, c, unit), nburst = _best_of_bursts(m, src, omega, 60)
        _report(name, passes, c, unit, nburst)
        assert passes < BUDGET_PASSES, (
            f"{name}: {passes:.0f} elementwise passes per frame on the CPU "
            f"clock at the settled exposure, budget {BUDGET_PASSES}")
        # ABSOLUTE BACKSTOP for spec 8's 5 ms/frame cap. The pass count is
        # machine-independent by design, which means it alone can never say
        # whether the chain fits inside 5 ms on THIS machine: 120 passes is
        # ~1.6 ms here but would be ~4.7 ms on a box with a 3x slower
        # elementwise pass, and over 5 ms on a slower one still - and the gate
        # would not notice. So the CPU MEDIAN is also held against the spec
        # number outright. The tail is deliberately not: the worst frame is the
        # statistic contention inflates 3-5x (see the N-sweep above), and that
        # is what made the old gate a false-failure generator. The median is
        # the one that survives - measured 1.20-1.22 ms idle and at worst
        # 1.92 ms with 14 bandwidth-heavy processes on a machine at load
        # average 55, so this has ~2.6x of headroom and is not a flake risk.
        assert c["cpu_median_ms"] < 5.0, (
            f"{name}: median frame costs {c['cpu_median_ms']:.2f} ms of CPU, "
            f"over spec 8 section 8's 5 ms cap. Unlike the pass count this is "
            f"an absolute number, so a slow machine can trip it honestly - "
            f"check cpu_median_ms on a quiet run before blaming the chain.")


@test
def test_describe_records_preset_seed_and_unmeasured_parameters():
    m = cm.CameraModel("himax_typical", seed=77)
    m.apply(flat(165), None, 0.077)
    d = m.describe()
    assert d["preset"] == "himax_typical" and d["seed"] == 77
    for k in ("psf_sigma_center_px", "vignette_a2", "prnu_sigma", "dsnu_sigma_dn"):
        assert k in d["unmeasured"], f"{k} lost its UNMEASURED tag"
    assert d["state"]["exposure_lines"] > 0 and d["cost"]["frames"] == 1
    note(f"UNMEASURED: {', '.join(d['unmeasured'])}")


@test
def test_grayscale_input_and_missing_gyro_are_accepted():
    m = cm.CameraModel("himax_typical", seed=1)
    out = m.apply(flat(150), None, 0.077)
    assert out.shape == (244, 324) and out.dtype == np.uint8


# --- 8. the optimised chain still produces the original bits ----------------
#
# camera_model.apply() runs in place against reused buffers and walks memory in
# the order the hardware likes. That is a 1.6x speed-up and it must be a pure
# speed-up: every number in docs/sim_results/2026-09-11-simv2 was measured on
# frames this chain produced, so a single changed pixel silently invalidates the
# published evidence. The three tests below are the guard rail. They compare
# against an independent, plainly-written implementation kept here on purpose -
# if someone optimises the fast path further, these fail unless the bits match.


def _ref_convolve(img, kernel, axis):
    """The original shifted-sum convolution: pad, then accumulate tap by tap."""
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


def _ref_chain(m, rgb, omega, dt):
    """The whole signal chain, written the obvious allocating way.

    Reads and advances model ``m``'s own state (AE, RNG, frame counter) exactly
    as ``apply`` does, so two models built with the same seed - one driven by
    this, one by ``apply`` - must stay in lockstep frame after frame.
    """
    p = m.params
    if rgb.ndim == 3:
        if p.bayer:
            m_r, m_g, m_b = m._bayer_masks
            f = rgb[..., :3].astype(np.float32)
            L = (f[..., 0] * m_r + f[..., 1] * m_g + f[..., 2] * m_b) / 255.0
        else:
            L = np.dot(rgb[..., :3].astype(np.float32), cm.REC601) / 255.0
    else:
        L = rgb.astype(np.float32) / 255.0
    if m._distort_map is not None:
        L = cm._bilinear_sample(L, m._distort_map[0], m._distort_map[1])
    if p.rolling_shutter and omega is not None:
        shift = float(omega[2]) * (m._row_idx * cm.LINE_PERIOD_S) * p.focal_px_per_rad
        L = cm._bilinear_sample(L, m._col_idx + shift,
                                np.repeat(m._row_idx, m.width, axis=1))
    if m._psf is not None:
        L = _ref_convolve(_ref_convolve(L, m._psf, 1), m._psf, 0)
    if m._has_vignette:
        L = L * m._vignette
    t_exp = m.exposure_time_s
    if p.motion_blur and omega is not None and t_exp > 0:
        lx = abs(float(omega[2])) * t_exp * p.focal_px_per_rad
        ly = abs(float(omega[1])) * t_exp * p.focal_px_per_rad
        if lx > p.motion_blur_min_px:
            L = _ref_convolve(L, cm._box_kernel(lx), 1)
        if ly > p.motion_blur_min_px:
            L = _ref_convolve(L, cm._box_kernel(ly), 0)
    if p.banding_depth > 0:
        phase = float(m._rng.uniform(0.0, 2.0 * math.pi))
        band = 1.0 + p.banding_depth * np.sin(
            2.0 * math.pi * m._row_idx / cm.BANDING_PERIOD_ROWS + phase)
        L = L * band.astype(np.float32)
    g = m.total_gain
    S = L * (255.0 * p.scene_light * m.exposure_factor)
    if m._prnu is not None:
        S = S * m._prnu
    if m._dsnu is not None:
        S = S + m._dsnu * g
    if p.shot_noise or p.read_noise:
        var = np.zeros_like(S)
        if p.shot_noise:
            var += np.maximum(S, 0.0) * g / cm.E_PER_DN_1X
        if p.read_noise:
            var += (cm.READ_NOISE_E * g / cm.E_PER_DN_1X) ** 2
        S = S + m._rng.standard_normal(m._shape).astype(np.float32) * np.sqrt(var)
    if m._dead_idx is not None:
        iy, ix, iv = m._dead_idx
        S[iy, ix] = iv
    out = np.floor(np.clip(S, 0.0, 255.0) + 0.5).astype(np.uint8)
    m._ae_update(float(out.mean()), dt)
    m.frames += 1
    return out


@test
def test_convolution_rewrite_is_bit_identical_to_the_shifted_sum():
    """cm._convolve_axis no longer pads (axis 0) or walks strided views
    (axis 1). Same taps, same order, same bits - on both dtypes the chain uses
    and on the tap counts the PSF and motion-blur kernels actually produce.

    Small frames are in the matrix on purpose. The rewrite's axis-0 slices used
    Python negative indexing to mark where clamped edge rows begin, which is
    correct only while the kernel radius is smaller than the frame height. A
    9-tap Bayer PSF on a 2-row frame made ``slice(0, h - d)`` select rows from
    the far end instead of none, and the shifted sum raised
    "non-broadcastable output operand with shape (1,2)". _ref_convolve pads, so
    it was right all along and is the oracle here."""
    rng = np.random.default_rng(0)
    checked = 0
    shapes = ((244, 324), (7, 9), (3, 2), (2, 2), (1, 7), (7, 1), (1, 1))
    for dtype in (np.float64, np.float32):
        for h, w in shapes:
            for content in ("random", "edge", "flat"):
                if content == "random":
                    img = (rng.random((h, w)) * 0.9).astype(dtype)
                elif content == "edge":
                    img = np.zeros((h, w), dtype); img[:, w // 2:] = 1.0
                else:
                    img = np.full((h, w), 0.37, dtype)
                for taps in (1, 3, 5, 7, 9):
                    for kind in ("gauss", "box", "random", "zero_ends"):
                        if kind == "gauss":
                            k = cm._gauss_kernel(max(taps // 2, 1) / 3.0)
                            if len(k) != taps:
                                continue
                        elif kind == "box":
                            k = cm._box_kernel(taps - 1.0)
                            if len(k) != taps:
                                continue
                        elif kind == "zero_ends":
                            k = np.zeros(taps, np.float32); k[taps // 2] = 1.0
                            if taps >= 3:
                                k[taps // 2 - 1] = k[taps // 2 + 1] = 0.0
                        else:
                            k = rng.random(taps).astype(np.float32); k /= k.sum()
                        for axis in (0, 1):
                            ref = _ref_convolve(img, k, axis)
                            got = cm._convolve_axis(img, k, axis)
                            assert got.dtype == ref.dtype, f"dtype changed: {got.dtype}"
                            assert np.array_equal(got, ref), (
                                f"convolution differs: dtype {np.dtype(dtype).name} "
                                f"{h}x{w} {content} {kind} taps={taps} axis={axis} "
                                f"max |d| {float(np.abs(got - ref).max()):.3e}")
                            checked += img.size
    note(f"{checked:,} elements compared over {len(shapes)} frame sizes, all exact")


@test
def test_luma_is_bit_identical_on_every_possible_rgb_triple():
    """Step 1 uses np.matmul on a float64 copy instead of np.dot on a float32
    one. The input is uint8, so the domain is finite: this enumerates all
    256^3 = 16,777,216 triples, which is a proof rather than a sample.

    It matters because the obvious hand-written form - r*c0 + g*c1 + b*c2 -
    is NOT bit-identical (it differs on 3,665,182 of the 16.7 M triples by one
    ulp). The summation here has to stay the one BLAS does.
    """
    bad = 0
    for r in range(256):
        g, b = np.meshgrid(np.arange(256, dtype=np.uint8),
                           np.arange(256, dtype=np.uint8), indexing="ij")
        rgb = np.ascontiguousarray(np.stack([np.full_like(g, r), g, b], -1))
        ref = np.dot(rgb[..., :3].astype(np.float32), cm.REC601) / 255.0
        buf = np.empty(rgb.shape, np.float64)
        np.copyto(buf, rgb[..., :3], casting="unsafe")
        got = np.matmul(buf, cm.REC601_W, out=np.empty(rgb.shape[:2], np.float64))
        got /= 255.0
        bad += int((got != ref).sum())
    assert bad == 0, f"{bad} of 16,777,216 uint8 triples give a different luma"
    note("all 16,777,216 uint8 triples give bit-identical luma")


@test
def test_optimised_chain_is_bit_identical_to_the_reference():
    """The whole chain, frame after frame, against the plain implementation.

    Covers both input paths (RGB and grayscale), all three shipped presets, the
    body-rate regimes that decide whether motion blur fires, and the knobs that
    are off in the presets but reachable through CRAZYSIM_SENSOR_OVERRIDES.
    """
    rng = np.random.default_rng(0)
    H, W = 244, 324
    srcs = {
        "render": rng.integers(30, 230, (H, W, 3), dtype=np.uint8),
        "edge": np.repeat(np.where(np.arange(W) < W // 2, 0, 255)
                          .astype(np.uint8)[None, :, None], 3, 2).repeat(H, 0),
        "dark": rng.integers(0, 12, (H, W, 3), dtype=np.uint8),
        "hot": rng.integers(240, 256, (H, W, 3), dtype=np.uint8),
        "gray": rng.integers(0, 256, (H, W), dtype=np.uint8),
        "rgba": rng.integers(0, 256, (H, W, 4), dtype=np.uint8),
    }
    oms = {
        "none": [None] * 6,
        "zero": [np.zeros(3)] * 6,
        "flight": list(rng.uniform(-0.7, 0.7, (6, 3))),      # the 40 deg/s cap
        "fast": list(rng.uniform(-5.0, 5.0, (6, 3))),        # wide kernels
    }
    cases = [(p, s, o, None) for p in ("himax_typical", "himax_low_light",
                                       "himax_color_bayer")
             for s in ("render", "edge", "dark", "hot")
             for o in ("flight", "fast")]
    cases += [("himax_typical", "gray", "flight", None),
              ("himax_low_light", "gray", "fast", None),
              ("himax_typical", "rgba", "flight", None),
              ("himax_typical", "render", "none", None),
              ("himax_low_light", "render", "zero", None)]
    for over in ({"rolling_shutter": True}, {"k1": 0.15}, {"banding_depth": 0.2},
                 {"ae_enabled": False}, {"ae_fixed_exposure": 0.4},
                 {"shot_noise": False}, {"read_noise": False},
                 {"shot_noise": False, "read_noise": False},
                 {"psf_sigma_center_px": 0.0}, {"motion_blur": False},
                 {"vignette_a2": 0.0, "vignette_a4": 0.0},
                 {"prnu_sigma": 0.0, "dsnu_sigma_dn": 0.0, "dead_px_frac": 0.0}):
        cases.append(("himax_typical", "render", "flight", over))
    npx = 0
    for preset, sname, oname, over in cases:
        kw = {"seed": 7}
        if over:
            kw["overrides"] = over
        a = cm.CameraModel(preset, **kw)      # driven by the reference
        b = cm.CameraModel(preset, **kw)      # driven by the optimised apply()
        src = srcs[sname]
        for j, o in enumerate(oms[oname]):
            dt = 0.077 if j % 3 else 0.153
            fa = _ref_chain(a, src, o, dt)
            fb = b.apply(src, o, dt)
            assert fa.dtype == fb.dtype == np.uint8 and fa.shape == fb.shape
            if not np.array_equal(fa, fb):
                d = fa.astype(np.int16) - fb.astype(np.int16)
                raise AssertionError(
                    f"{preset}/{sname}/{oname}/{over} frame {j}: "
                    f"{int((d != 0).sum())} of {fa.size} pixels differ, "
                    f"max |d| {int(np.abs(d).max())} DN")
            assert a.state() == b.state(), (
                f"{preset}/{sname}/{oname}/{over} frame {j}: AE state diverged\n"
                f"  reference {a.state()}\n  optimised {b.state()}")
            npx += fa.size
    note(f"{len(cases)} configurations, {npx:,} pixels, all bit-identical")


# --- 9. cost: the September regression, and not failing when the Mac is busy -
#
# Two things have to be true at once. The bench must still catch the regression
# that put 6 of 16 flight runs over spec 8's 5 ms cap - and it must not fail
# when the only thing wrong is that something else on the laptop is running,
# because a bench that cries wolf is a bench people stop reading. The docstrings
# below carry the measurements behind both.

class _Yardstick:
    """One elementwise pass over a 244x324 float64 frame, sampled on demand.

    Lets a budget be stated in passes instead of milliseconds, so it means the
    same thing on a slower laptop, on a different numpy - and, the point of the
    whole exercise, on a BUSIER laptop.

    The unit is a quarter of a four-op mix (scalar multiply, array add, sqrt,
    cast to float32), not a bare scalar multiply. numpy 2.4 made the bare
    multiply 35% faster without making this chain any faster, so a budget
    calibrated on it would drift between trainenv (numpy 1.24, where the tests
    are run) and crazysimenv (numpy 2.4, where the sim runs). Against this mix
    the chain measures the same to within 4% on both.

    Samples are CPU time, matching the statistic they normalise.
    """

    def __init__(self):
        self._a = np.random.random((244, 324))
        self._b = np.empty_like(self._a)
        self._c = np.empty((244, 324), np.float32)
        for _ in range(30):
            self._mix()

    def _mix(self):
        np.multiply(self._a, 1.0000001, out=self._b)
        np.add(self._b, self._a, out=self._b)
        np.sqrt(self._b, out=self._b)
        np.copyto(self._c, self._b, casting="unsafe")

    def sample(self, iters=150):
        """One rep: ms per elementwise pass."""
        t = time.thread_time()
        for _ in range(iters):
            self._mix()
        return (time.thread_time() - t) / iters / 4.0 * 1e3


_YARD = None


def _yardstick():
    global _YARD
    if _YARD is None:
        _YARD = _Yardstick()
    return _YARD


def _elementwise_pass_ms(reps=5):
    """Median of ``reps`` yardstick samples.

    **Median, not min.** ``min`` picks the least-contended sample, which is the
    wrong normaliser for a burst that ran under whatever contention was actually
    there: the numerator would carry the load and the denominator would not, and
    the ratio would drift upward on a busy machine for no reason at all.
    """
    y = _yardstick()
    return float(np.median([y.sample() for _ in range(reps)]))


BUDGET_PASSES = 120       # see test_worst_frame_cost_with_motion_blur_on_every_frame
BURSTS = 4
_SLICES = 5


def _timed_burst(m, src, omega, n):
    """One burst of ``n`` frames -> (passes, cost_stats, unit_ms).

    ``passes`` is the CPU-time median frame divided by one elementwise pass.
    Both halves are CPU time, and the yardstick is sampled BETWEEN SLICES of
    the burst rather than once before or after it, so the denominator is drawn
    from the same stretch of wall-clock time - and therefore the same
    contention - as the numerator. Sampling it only afterwards left the ratio
    swinging 56-115 passes under a 14-process load for a chain that measures
    69-94 idle - 115 against a budget of 120 is not a margin. Interleaved, 24
    measurements under that same load spanned 63-106. The top of the range is
    what matters, and it came down by 9 passes; that is what lets the budget
    stay at 120 instead of being loosened until it catches nothing.
    """
    y = _yardstick()
    m.reset_cost()
    per, done, units = max(1, n // _SLICES), 0, []
    while done < n:
        k = min(per, n - done)
        for _ in range(k):
            m.apply(src, omega, 0.077)
        done += k
        units.append(y.sample())
    c = m.cost_stats()
    unit = float(np.median(units))
    return c["cpu_median_ms"] / unit, c, unit


def _best_of_bursts(m, src, omega, n, bursts=BURSTS, budget=BUDGET_PASSES):
    """Up to ``bursts`` bursts, keeping the cheapest. Stops as soon as one is
    inside ``budget``, so a green run costs exactly one burst."""
    reps = []
    for _ in range(bursts):
        reps.append(_timed_burst(m, src, omega, n))
        if reps[-1][0] < budget:
            break
    return min(reps, key=lambda r: r[0]), len(reps)


def _report(label, passes, c, unit, nburst):
    """Print the whole picture: what is asserted, and what is only observed."""
    print(f"      {label:19s} median {c['cpu_median_ms']:.2f} ms cpu "
          f"({passes:.0f} passes of {unit * 1e3:.2f} us, budget {BUDGET_PASSES})"
          + (f"  [best of {nburst} bursts]" if nburst > 1 else ""))
    print(f"      {'':19s} not asserted: wall median {c['median_ms']:.2f} "
          f"max {c['max_ms']:.2f} | cpu p95 {c['cpu_p95_ms']:.2f} "
          f"max {c['cpu_max_ms']:.2f} | frames over 5 ms: "
          f"{c['cpu_over_5ms_frames']} cpu / {c['wall_over_5ms_frames']} wall"
          + ("  <-- machine was busy; re-run idle to interpret"
             if c["cpu_over_5ms_frames"] or c["wall_over_5ms_frames"] else ""))


@test
def test_worst_frame_cost_with_motion_blur_on_every_frame():
    """Spec 8's per-frame budget, gated on a statistic a busy laptop cannot fake.

    What the old bench (``test_per_frame_cost_is_under_the_budget``) missed:
    it asserted the MEAN over 60 frames at whatever exposure the AE settles on.
    When the motion-blur gate was fixed so the blur convolutions run on every
    frame instead of never, the in-flight cost went 2.23 -> 3.50 ms mean and
    4.19 -> 7.27 ms worst, over the cap on 6 of 16 runs, and that bench still
    reported a comfortable 1.8 ms.

    So this test forces the worst case and asserts its own premise:

    1. Exposure is pinned at the sensor's integration ceiling (340 lines =
       10.56 ms), the longest smear the hardware can produce, and the body rate
       is non-zero on both axes, so both blur convolutions fire on every frame.
    2. ``_box_kernel`` is counted: if a future change quietly stops the blur
       firing, the test fails instead of silently going back to measuring
       nothing - which is exactly how this got missed the first time.

    **What it gates on, and the trade-off that choice makes.**

    The gate is the CPU-time MEDIAN frame, divided by an elementwise pass
    sampled between slices of that same burst, best of up to four bursts.
    Everything else - wall times, p95, the worst frame, the over-5 ms counts -
    is printed and NOT asserted.

    That is a deliberate narrowing, because the previous version's absolute
    ``cpu_max_ms < 5.0`` assertion was a false-failure generator. It was
    introduced on the belief that ``time.thread_time()`` makes the measurement
    contention-proof. It does not: CPU time excludes time the OS spends running
    another process, but cache-miss stall time caused by that process is still
    charged to this thread. Measured here on an M4 Pro, one preset, 300-frame
    bursts, against a background of N bandwidth-heavy processes:

        N   cpu median (ms)   worst frame (ms)   median in passes
        0      1.20-1.22          1.1- 2.2            69- 94
        4      1.40-1.46          1.9- 3.7            74-101
        8      1.45-1.54          3.6- 5.1            80- 98
       14      1.54-1.74          4.0- 7.5            63-106

    Re-measured independently on 2026-09-12 by a verifier under a HEAVIER load
    than the sweep above - the same 14 bandwidth-heavy processes on top of a
    machine already at load average 8, peaking at 55 - 24 burst measurements
    (4 full suite runs) spanned 69-111 passes, all still inside the budget but
    with the top of the range 5 passes higher than the sweep found. Treat 106
    as the top of a quiet-ish N=14 range, not as a ceiling. All 4 runs were
    33/33; the same 4 runs of the OLD cpu_max assertion failed 2 out of 3.

    The median degrades gracefully and stays inside 120 passes throughout; the
    worst frame triples. The old assertion, best-of-3-bursts and all, failed 3
    runs out of 3 under the N=14 load, reporting worst frames of 7.46, 7.51 and
    8.37 ms for a chain that measures 1.1-2.2 ms on the same machine idle. A
    gate that fails when nothing is wrong is worse than no gate, because people
    learn to re-run it until it passes. The whole suite now passes 4 runs out
    of 4 under that same N=14 load, with the worst frames still reported.

    Attempts that did NOT work, so nobody repeats them: normalising each frame
    against a control kernel timed immediately after it (stalls are bursty at
    microsecond scale, so the worst frame still inflated 4x); using the
    yardstick's own spread as a contention detector (1.43x at N=0 against 1.11x
    at N=14 - no separation); ``os.getloadavg()`` (a one-minute average, it read
    7.2 idle and 12.9 under the N=14 storm); comparing wall time against CPU
    time (this load is memory bandwidth, not oversubscription, so the ratio sat
    at 1.00 either way). No in-process signal separated "this model is slow"
    from "this laptop is busy" on the tail, which is why the tail is reported
    rather than asserted.

    **What the narrowing costs, and what pays for it.** A regression that hits
    only a few frames per hundred would no longer trip a timing assertion. The
    regression this test exists to catch was exactly that shape - twenty
    allocated temporaries per frame producing 5-14 ms outliers against a 1.9 ms
    median - so it is not an acceptable blind spot. It is covered instead by
    ``test_apply_reuses_its_buffers_instead_of_allocating_per_frame``, which
    measures allocation directly and deterministically, with no clock involved
    at all. Between them: the allocation test catches the tail cause, the
    median-in-passes test catches a uniform slowdown.

    **Calibration of the 120.** Measured by replacing ``apply`` with
    ``_ref_chain`` - the pre-optimisation allocating implementation - and
    running this very test: it reported 146 passes idle and 133 under the N=14
    load, failing both times. The current chain reads 90-94 idle and 63-111
    loaded (the 111 is the verifier's heavier re-measurement above). 120 sits between, with 13% of headroom above the worst clean
    measurement and 11% below the worst regressed one. That second margin is
    thin under load, on purpose: squeezing it further would start failing clean
    runs, and the allocation test below is the contention-free backstop that
    does not need a margin at all (3403 KiB against a 618 KiB budget).

    For himax_color_bayer the allocating chain is only 84 passes against 70 -
    that preset's chain barely benefits from the rewrite - so the pass budget
    cannot detect a full regression there. Known blind spot; the allocation
    test is what covers the Bayer preset.
    """
    rng = np.random.default_rng(4)
    src = rng.integers(30, 230, (244, 324, 3), dtype=np.uint8)
    print()
    real_box = cm._box_kernel
    for preset in ("himax_typical", "himax_low_light", "himax_color_bayer"):
        m = cm.CameraModel(preset, seed=1, overrides={"ae_enabled": False})
        m._t_lines = float(cm.MAX_INTG_LINES)          # integration ceiling
        # 40 deg/s is the follower's own yaw cap; pitch at half that.
        omega = np.array([0.0, 0.35, 0.70])
        t_exp = m.exposure_time_s
        lx = abs(omega[2]) * t_exp * m.params.focal_px_per_rad
        ly = abs(omega[1]) * t_exp * m.params.focal_px_per_rad
        assert lx > m.params.motion_blur_min_px and ly > m.params.motion_blur_min_px, (
            f"{preset}: the blur gate would skip this frame (lx {lx:.3f}, "
            f"ly {ly:.3f} px) - the worst case is not being exercised")
        for _ in range(40):
            m.apply(src, omega, 0.077)
        calls = []

        def counting_box_kernel(length, _real=real_box):
            k = _real(length)
            calls.append(len(k))
            return k

        n = 300
        cm._box_kernel = counting_box_kernel
        try:
            (passes, c, unit), nburst = _best_of_bursts(m, src, omega, n)
        finally:
            cm._box_kernel = real_box
        assert len(calls) == 2 * n * nburst, (
            f"{preset}: motion blur ran {len(calls)} times in "
            f"{n * nburst} frames, expected {2 * n * nburst} "
            f"(both axes, every frame)")
        _report(f"{preset} {calls[0]}x{calls[1]}", passes, c, unit, nburst)
        assert passes < BUDGET_PASSES, (
            f"{preset}: {passes:.0f} elementwise passes per frame on the CPU "
            f"clock, budget {BUDGET_PASSES}, best of {nburst} burst(s). This "
            f"statistic is normalised against a yardstick sampled between "
            f"slices of the same burst, and it stayed inside 63-111 across two "
            f"independent sessions with up to 14 bandwidth-heavy processes "
            f"competing (load average 8-55), so a busy laptop is an "
            f"unlikely explanation - suspect the chain. The current chain is "
            f"90-94 passes idle (69 for Bayer); the pre-optimisation allocating "
            f"chain measures 133-146 through this same test.")
        # ABSOLUTE BACKSTOP for spec 8's 5 ms/frame cap. The pass count is
        # machine-independent by design, which means it alone can never say
        # whether the chain fits inside 5 ms on THIS machine: 120 passes is
        # ~1.6 ms here but would be ~4.7 ms on a box with a 3x slower
        # elementwise pass, and over 5 ms on a slower one still - and the gate
        # would not notice. So the CPU MEDIAN is also held against the spec
        # number outright. The tail is deliberately not: the worst frame is the
        # statistic contention inflates 3-5x (see the N-sweep above), and that
        # is what made the old gate a false-failure generator. The median is
        # the one that survives - measured 1.20-1.22 ms idle and at worst
        # 1.92 ms with 14 bandwidth-heavy processes on a machine at load
        # average 55, so this has ~2.6x of headroom and is not a flake risk.
        assert c["cpu_median_ms"] < 5.0, (
            f"{preset}: median frame costs {c['cpu_median_ms']:.2f} ms of CPU, "
            f"over spec 8 section 8's 5 ms cap. Unlike the pass count this is "
            f"an absolute number, so a slow machine can trip it honestly - "
            f"check cpu_median_ms on a quiet run before blaming the chain.")


@test
def test_apply_reuses_its_buffers_instead_of_allocating_per_frame():
    """The allocation gate: deterministic, and immune to how busy the Mac is.

    ``apply`` runs in place against per-instance scratch buffers. The whole
    point was that the old version's roughly twenty 316-632 KB temporaries per
    frame - not its arithmetic - produced the 5-14 ms outlier frames against a
    1.9 ms median that put 6 of 16 flight runs over spec 8's cap.

    Timing cannot police that reliably on a shared laptop (see
    ``test_worst_frame_cost_with_motion_blur_on_every_frame``), so this measures
    the cause instead of the symptom: ``tracemalloc``'s high-water mark across
    one ``apply`` call, after warm-up. It involves no clock, so contention,
    thermal state and numpy version cannot move it.

    Measured on an M4 Pro, reproducible to 0.1 KiB across repeats:

        preset              this chain      _ref_chain (allocating)
        himax_typical        206.5 KiB          3402.5 KiB
        himax_low_light      207.3 KiB          3402.5 KiB
        himax_color_bayer    206.2 KiB          2780.4 KiB

    One 244x324 float64 frame buffer is 618 KiB, so the budget below is one
    frame buffer: 3x above what the chain does and 4.5x below the allocating
    version, for every preset including Bayer. The ~206 KiB that is left is
    real and expected - the returned uint8 frame is 77 KiB of it (callers keep
    their frames), and the rest is the fancy-index border fixup inside
    ``_convolve_axis``.
    """
    rng = np.random.default_rng(4)
    src = rng.integers(30, 230, (244, 324, 3), dtype=np.uint8)
    omega = np.array([0.0, 0.35, 0.70])

    def peak_kib(fn, reps=6):
        for _ in range(4):
            fn()
        tracemalloc.start()
        try:
            for _ in range(2):
                fn()                      # let tracemalloc itself settle
            seen = []
            for _ in range(reps):
                tracemalloc.reset_peak()
                before, _ = tracemalloc.get_traced_memory()
                out = fn()
                _, peak = tracemalloc.get_traced_memory()
                seen.append((peak - before) / 1024.0)
                del out
            return max(seen)
        finally:
            tracemalloc.stop()

    for preset in ("himax_typical", "himax_low_light", "himax_color_bayer"):
        m = cm.CameraModel(preset, seed=1, overrides={"ae_enabled": False})
        m._t_lines = float(cm.MAX_INTG_LINES)
        budget = m.width * m.height * 8 / 1024.0        # one float64 frame
        got = peak_kib(lambda: m.apply(src, omega, 0.077))
        r = cm.CameraModel(preset, seed=1, overrides={"ae_enabled": False})
        r._t_lines = float(cm.MAX_INTG_LINES)
        ref = peak_kib(lambda: _ref_chain(r, src, omega, 0.077))
        note(f"{preset:18s} peak {got:7.1f} KiB/frame ({got / budget:.2f} frame "
             f"buffers); allocating reference {ref:7.1f} KiB ({ref / budget:.2f})")
        assert got < budget, (
            f"{preset}: apply() raised the allocation high-water mark by "
            f"{got:.0f} KiB per frame, budget {budget:.0f} KiB (one float64 "
            f"frame). It was 206-207 KiB when this was written. Something in "
            f"the chain started allocating a temporary per frame again - that "
            f"is what produced the 5-14 ms outlier frames the in-place rewrite "
            f"removed. The allocating reference chain measures {ref:.0f} KiB.")
        assert ref > 2 * budget, (
            f"{preset}: the allocating reference chain only peaked at "
            f"{ref:.0f} KiB, so this test no longer has a gap to detect. "
            f"Did _ref_chain stop allocating?")

    # And the pool really is reused: no new keys after warm-up.
    m = cm.CameraModel("himax_typical", seed=1)
    for _ in range(5):
        m.apply(src, omega, 0.077)
    keys = set(m._bufs)
    for _ in range(20):
        m.apply(src, omega, 0.077)
    assert set(m._bufs) == keys, (
        f"the scratch pool kept growing after warm-up: "
        f"{sorted(set(m._bufs) - keys)}")
    note(f"scratch pool steady at {len(keys)} buffers over 25 frames")


# --- 10. the contract around the optimised chain ---------------------------
#
# Running in place bought 1.64x, and it took three things away that the old
# allocating version gave for free: reentrancy, an unbounded-but-harmless
# buffer pool, and tolerance of an odd-sized frame. Each is now an explicit,
# documented contract rather than an accident, so these pin them down.


@test
def test_apply_is_not_reentrant_and_says_so_instead_of_corrupting_the_frame():
    """Two overlapping apply() calls on ONE model share its scratch buffers.

    The old allocating version tolerated this (badly - the AE state and RNG
    stream were still shared - but at least the pixels of each call were its
    own). This one would interleave writes into the same arrays and hand both
    callers a plausible-looking wrong frame. Silent wrong pixels are the worst
    possible failure for a sensor model whose whole job is deciding what the
    network sees, so apply() refuses.
    """
    m = cm.CameraModel("himax_typical", seed=1)
    src = flat(150)

    # (a) genuine reentrancy: call apply() from inside apply(), via the AE hook.
    inner = []
    outer_ae = cm.CameraModel._ae_update

    def reentrant_ae(self, measured_mean, dt):
        try:
            m.apply(src)
        except RuntimeError as e:
            inner.append(str(e))
        return outer_ae(self, measured_mean, dt)

    cm.CameraModel._ae_update = reentrant_ae
    try:
        out = m.apply(src)
    finally:
        cm.CameraModel._ae_update = outer_ae
    assert inner, "a reentrant apply() was allowed through"
    assert "not reentrant" in inner[0], f"unhelpful message: {inner[0]}"
    assert out.shape == (244, 324), "the outer call should still have completed"
    note(f"reentrant call rejected: {inner[0].split('.')[0]}.")

    # (b) the guard is released again, so normal use is unaffected.
    assert m.apply(src).shape == (244, 324), "the guard did not release"

    # (c) a second thread is refused rather than allowed to corrupt pixels.
    blocked, started = [], threading.Event()
    slow = cm.CameraModel("himax_typical", seed=1)
    real_conv = cm._convolve_axis

    def slow_conv(*a, **k):
        started.set()
        time.sleep(0.05)
        return real_conv(*a, **k)

    def contender():
        started.wait(2.0)
        try:
            slow.apply(src)
        except RuntimeError:
            blocked.append(True)

    cm._convolve_axis = slow_conv
    try:
        t = threading.Thread(target=contender)
        t.start()
        slow.apply(src)
        t.join(5.0)
    finally:
        cm._convolve_axis = real_conv
    assert blocked, "a concurrent apply() on the same model was not refused"
    note("concurrent apply() from a second thread refused")

    # (d) two SEPARATE models in two threads are fine - that is the contract.
    outs, err = {}, []
    def worker(i):
        try:
            outs[i] = cm.CameraModel("himax_typical", seed=1).apply(src).tobytes()
        except Exception as e:                                  # noqa: BLE001
            err.append(e)
    ts = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
    [t.start() for t in ts]
    [t.join(10.0) for t in ts]
    assert not err, f"one model per thread should be fine, got {err}"
    assert len(set(outs.values())) == 1, "same seed, same frame, different bytes"


@test
def test_the_scratch_pool_is_bounded():
    """Keyed by (name, shape, dtype), the pool would grow without limit if a
    caller varied the frame size. apply() rejects a foreign size outright, but
    _buf itself is the thing that must not leak, so it is capped and evicts the
    least recently used entry."""
    m = cm.CameraModel("himax_typical", seed=1)
    for h in range(1, 60):                       # 59 distinct shapes
        m._buf("scratch", (h, 8), np.float32)
    assert len(m._bufs) <= cm._MAX_SCRATCH, (
        f"scratch pool grew to {len(m._bufs)} entries for 59 distinct shapes; "
        f"cap is {cm._MAX_SCRATCH}")
    note(f"59 distinct shapes -> pool held at {len(m._bufs)} (cap {cm._MAX_SCRATCH})")

    # Eviction is least-recently-used, and a re-request still returns a correct
    # buffer (contents are never assumed, so a fresh array is as good).
    a = m._buf("scratch", (5, 8), np.float32)
    assert a.shape == (5, 8) and a.dtype == np.float32

    # The shipped path never evicts: one frame size needs about a dozen keys.
    m2 = cm.CameraModel("himax_color_bayer", seed=1)
    rgb = np.full((244, 324, 3), 150, np.uint8)
    for _ in range(10):
        m2.apply(rgb, np.array([0.0, 0.3, 0.7]), 0.077)
    assert len(m2._bufs) < cm._MAX_SCRATCH, (
        f"the shipped Bayer path alone uses {len(m2._bufs)} of "
        f"{cm._MAX_SCRATCH} slots - the cap is too tight")
    note(f"shipped Bayer path uses {len(m2._bufs)} of {cm._MAX_SCRATCH} slots")


@test
def test_a_frame_of_the_wrong_size_is_refused_with_an_explanation():
    """Intended, not a regression: PRNU, DSNU, dead pixels, vignette and the
    distortion map are per-pixel arrays for one frame size, so a different size
    has no correct answer. It used to surface as a raw numpy gufunc message
    about 'core dimension 0'; it must now say what is wrong and what to do."""
    m = cm.CameraModel("himax_typical", seed=1)
    try:
        m.apply(np.zeros((240, 320, 3), np.uint8))
    except ValueError as e:
        msg = str(e)
    else:
        raise AssertionError("a 320x240 frame was accepted by a 324x244 model")
    for want in ("324x244", "320x240", "width=320", "height=240", "per-pixel"):
        assert want in msg, f"error message does not mention {want!r}: {msg}"
    assert "core dimension" not in msg, "still leaking the raw numpy message"
    note(msg.split(". ")[0] + ".")

    for bad, why in ((np.zeros((244, 324, 2), np.uint8), "3 colour channels"),
                     (np.zeros((244,), np.uint8), "dimension"),
                     (np.zeros((2, 244, 324, 3), np.uint8), "dimension")):
        try:
            m.apply(bad)
        except ValueError as e:
            assert why in str(e), f"{bad.shape}: {e}"
        else:
            raise AssertionError(f"{bad.shape} was accepted")

    # The right way round: a model built for the size works.
    ok = cm.CameraModel("himax_typical", width=320, height=240, seed=1)
    assert ok.apply(np.zeros((240, 320, 3), np.uint8)).shape == (240, 320)


@test
def test_one_pixel_frame_dimensions_do_not_crash():
    """Pre-existing bug, both implementations: a model with height == 1 or
    width == 1 died in the dead-pixel cluster init with 'ValueError: high <= 0'
    (dev.integers(0, h - 1) with h == 1), and a 1x1 model also divided by a zero
    corner radius and produced a nan vignette. Nothing in the sim builds such a
    camera, but a unit test or a crop tool reasonably might."""
    for w, h in ((1, 1), (1, 244), (324, 1), (2, 2), (3, 1)):
        for preset in ("himax_typical", "himax_low_light", "himax_color_bayer"):
            m = cm.CameraModel(preset, width=w, height=h, seed=1)
            assert np.isfinite(m._vignette).all(), f"{preset} {w}x{h}: nan vignette"
            out = m.apply(np.full((h, w, 3), 180, np.uint8),
                          np.array([0.0, 0.3, 0.7]), 0.077)
            assert out.shape == (h, w) and out.dtype == np.uint8, \
                f"{preset} {w}x{h}: got {out.shape} {out.dtype}"
            gray = m.apply(np.full((h, w), 180, np.uint8), None, 0.077)
            assert gray.shape == (h, w)
    note("1x1, 1x244, 324x1, 2x2 and 3x1 models build and run on all 3 presets")

    # And the fix did not touch the shipped size: the dead-pixel map for a
    # normal frame is exactly what the unclamped draw produced.
    m = cm.CameraModel("himax_typical", seed=99)
    iy, ix, _ = m._dead_idx
    assert iy.max() <= 243 and ix.max() <= 323 and len(iy) == 4
    dev = np.random.default_rng(99)
    _ = 1.0 + dev.normal(0.0, 0.008, (244, 324))     # replay the device stream
    _ = dev.normal(0.0, 0.4, (244, 324))
    ys = dev.integers(0, 243, 1)
    xs = dev.integers(0, 323, 1)
    assert list(iy) == [ys[0], ys[0], ys[0] + 1, ys[0] + 1], \
        f"the dead-pixel draw moved: {iy} vs cy={ys[0]}"
    assert list(ix) == [xs[0], xs[0] + 1, xs[0], xs[0] + 1], \
        f"the dead-pixel draw moved: {ix} vs cx={xs[0]}"
    note(f"shipped 324x244 dead-pixel cluster unchanged at ({ys[0]}, {xs[0]})")


@test
def test_cost_stats_reports_both_clocks_and_does_not_call_a_count_a_verdict():
    """The flight log's camera_model.json is read by people. ``over_budget_frames``
    said 'the model went over budget' when all it could measure was 'a frame took
    over 5 ms', which on a busy Mac is routinely the machine. The key is now
    named for what it counts, on a named clock, and the median - the statistic
    that survives contention - is exposed alongside it."""
    m = cm.CameraModel("himax_typical", seed=1)
    assert m.cost_stats() == {}, "no frames yet should report nothing"
    for _ in range(12):
        m.apply(flat(165), np.array([0.0, 0.3, 0.7]), 0.077)
    c = m.cost_stats()
    for k in ("frames", "mean_ms", "median_ms", "p95_ms", "max_ms",
              "cpu_mean_ms", "cpu_median_ms", "cpu_p95_ms", "cpu_max_ms",
              "cpu_over_5ms_frames", "wall_over_5ms_frames", "over_5ms_note"):
        assert k in c, f"cost_stats lost {k}"
    assert "over_budget_frames" not in c, \
        "over_budget_frames is back; it reads as a verdict the number cannot support"
    assert c["frames"] == 12
    assert c["cpu_median_ms"] <= c["cpu_max_ms"] + 1e-9
    assert c["cpu_median_ms"] <= c["median_ms"] + 0.5, \
        "cpu median should not exceed the wall median by much"
    assert "verdict" in c["over_5ms_note"]
    # describe() is what lands in the flight log's camera_model.json, so the
    # honest keys have to survive the trip.
    d = m.describe()["cost"]
    assert d["cpu_median_ms"] == c["cpu_median_ms"] and "over_budget_frames" not in d
    note(f"cost keys: {', '.join(k for k in c if k != 'over_5ms_note')}")


def main():
    failed = []
    t0 = time.time()
    for fn in TESTS:
        name = fn.__name__
        try:
            fn()
            print(f"  PASS  {name}")
        except AssertionError as e:
            failed.append(name)
            print(f"  FAIL  {name}\n        {e}")
        except Exception as e:  # noqa: BLE001
            failed.append(name)
            print(f"  ERROR {name}\n        {type(e).__name__}: {e}")
    print(f"\n{len(TESTS) - len(failed)}/{len(TESTS)} passed in {time.time() - t0:.1f} s")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
