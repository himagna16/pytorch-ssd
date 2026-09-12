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
import time
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
    assert flat_rows.ptp() < 0.01, "rows are not flat with banding off"


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
    """Spec 8: 5 ms/frame hard cap, against a ~70 ms camera period."""
    rng = np.random.default_rng(1)
    src = rng.integers(40, 220, (244, 324, 3), dtype=np.uint8)
    omega = np.array([0.0, 0.2, 0.6])
    print()
    for name in ("himax_typical", "himax_low_light", "himax_color_bayer"):
        m = cm.CameraModel(name, seed=1)
        for _ in range(10):
            m.apply(src, omega, 0.077)              # warm up, settle AE
        m._cost_ms.clear()
        for _ in range(60):
            m.apply(src, omega, 0.077)
        c = m.cost_stats()
        print(f"      cost {name:20s} mean {c['mean_ms']:.2f} ms  "
              f"median {c['median_ms']:.2f}  p95 {c['p95_ms']:.2f}  max {c['max_ms']:.2f}")
        assert c["mean_ms"] < 5.0, f"{name} costs {c['mean_ms']:.2f} ms/frame (budget 5 ms)"


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
