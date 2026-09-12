#!/usr/bin/env python3
"""Rehearsal harness for score_real_frames.py: run this BEFORE the lab session.

Why it exists: on session day we get one shot at the mirror check, and a mirror
check that cannot see a mirror is worse than no check at all (every steering
command would turn the wrong way). So every verdict the scorer can print is
produced here on purpose, from frames whose truth we baked in ourselves, plus
the messy folders a real session actually produces (corrupt file, missing
labels, one bearing only, JPEG mixed with raw, nobody in view).

Two layers:

  fast (default)  A stub "model" replaces the CNN: it finds the dark blob in
                  the image and reports where it is. It is not the real network,
                  but it reacts to pixels, so a left-right flipped frame really
                  does come back flipped - which is exactly what the mirror
                  check has to catch. Frames are drawn with PIL at the pixel a
                  pinhole camera would put a person at. No torch, no checkpoint,
                  a few seconds.

  --real          Renders a person with MuJoCo at known distances/bearings
                  (the simulator's own scene and camera) and scores them with
                  the real checkpoint through the real scorer, end to end -
                  upright must come back PASS, the flipped copy MIRRORED.
                  Needs trainenv (mujoco + torch). Measured 31 s at
                  --real-frames 40 (680 frames per pass).

Usage:
    ~/Downloads/drone/trainenv/bin/python pytorch_ssd/tools/real_frames/test_score_real_frames.py
    ~/Downloads/drone/trainenv/bin/python pytorch_ssd/tools/real_frames/test_score_real_frames.py \
        --real --real-frames 40
    ... [--frames N] [--only mirror] [--keep]   # --keep leaves the folders on disk to look at

Exit code 0 = every check passed. Anything else: read the FAIL lines.
NOTE: passing here says the SCORER is sound. It says nothing about the real
camera - only frames from the AI-deck can do that.
"""
import argparse
import contextlib
import csv
import io
import json
import math
import shutil
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import score_real_frames as S  # noqa: E402

DRONE_ROOT = HERE.parents[2]
SIM_SCENE = DRONE_ROOT / "pytorch_ssd/tools/crazysim_macos/scenes/scene_person.xml"

W, H = 324, 244            # AI-deck frame size, as cpx_grab.py saves it
FOVY = 70.0                # simulator camera; the square crop spans this horizontally
FPX = (H / 2) / math.tan(math.radians(FOVY) / 2)   # focal length in pixels
PERSON_H, CAM_H = 1.7, 0.8
T0 = 1757530000.0


# --------------------------------------------------------------------------
# drawing frames whose truth we know
# --------------------------------------------------------------------------
def draw_frame(dist, bearing, person=True, rng=None, flip=False):
    """A 324x244 grayscale frame with a dark person-shaped box where a pinhole
    camera (vertical FOV 70 deg, lens at CAM_H) would actually see one."""
    rng = rng or np.random.default_rng(0)
    img = np.full((H, W), 200.0)
    img += np.linspace(-12, 12, H)[:, None]                   # ceiling/floor gradient
    img[int(H / 2 + FPX * CAM_H / 6.0):] -= 25                # a floor, roughly
    if person:
        cx = W / 2 + FPX * math.tan(math.radians(bearing))
        top = H / 2 - FPX * (PERSON_H - CAM_H) / dist
        bot = H / 2 + FPX * CAM_H / dist
        half = FPX * 0.25 / dist
        x0, x1 = int(round(cx - half)), int(round(cx + half))
        y0, y1 = int(round(top)), int(round(bot))
        x0, x1 = max(0, x0), min(W, x1)
        y0, y1 = max(0, y0), min(H, y1)
        hr = int((y1 - y0) * 0.13)                            # a head, so it is not a bare bar
        img[y0 + hr:y1, x0:x1] = 40
        img[y0:y0 + hr, int(round(cx - half * 0.5)):int(round(cx + half * 0.5))] = 55
    img += rng.normal(0, 3.0, img.shape)
    out = np.clip(img, 0, 255).astype(np.uint8)
    return out[:, ::-1].copy() if flip else out


def clip_name(dist, bearing, vis, subj, light, take, f, t):
    d = f"d{dist:g}_" if dist is not None else ""
    b = f"b{bearing:g}_" if bearing is not None else ""
    return f"{d}{b}vis{vis}_subj-{subj}_light-{light}_take{take}_f{f:05d}_t{t:.3f}.png"


def write_clip(out, dist, bearing, vis, n=6, subj="p01", light="room", take=1,
               person=None, flip=False, seed=0, ext=".png", t0=T0):
    """One clip: n frames with a little jitter, named the way cpx_grab.py names them."""
    out.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    person = vis == 1 if person is None else person
    paths = []
    for i in range(1, n + 1):
        b = (bearing or 0.0) + rng.normal(0, 0.4)
        d = (dist or 2.5) + rng.normal(0, 0.02)
        img = draw_frame(d, b, person=person, rng=rng, flip=flip)
        p = out / clip_name(dist, bearing, vis, subj, light, take, i, t0 + i * 0.1)
        if ext != ".png":
            p = p.with_suffix(ext)
        Image.fromarray(img).save(p)
        paths.append(p)
    return paths


def standard_folder(out, n=6, flip=False, lie=False, person=True, bearings=(0, -10, 10, -25, 25),
                    dists=(1.5, 2.5, 3.5)):
    """A miniature of protocol section 4: 3 distances x 5 bearings + empty clips.
    lie=True draws every person at +25 deg no matter what the label says (the
    'marks/labels are wrong' case)."""
    take = 0
    for d in dists:
        for b in bearings:
            take += 1
            if lie:
                _write_lied(out, d, b, 25.0, n, take, flip)
            else:
                write_clip(out, d, b, 1, n=n, take=take, seed=take, person=person, flip=flip)
    for i in range(1, 3):
        write_clip(out, None, None, 0, n=n, subj="empty", take=i, seed=100 + i, person=False)
    return out


def _write_lied(out, dist, bearing, drawn, n, take, flip):
    rng = np.random.default_rng(take)
    out.mkdir(parents=True, exist_ok=True)
    for i in range(1, n + 1):
        img = draw_frame(dist, drawn + rng.normal(0, 0.4), rng=rng, flip=flip)
        Image.fromarray(img).save(out / clip_name(dist, bearing, 1, "p01", "room", take, i,
                                                  T0 + i * 0.1))


# --------------------------------------------------------------------------
# stub model: a blob finder with the same interface as score_real_frames.Model
# --------------------------------------------------------------------------
class StubModel:
    preprocess = staticmethod(S.Model.preprocess)

    def __init__(self, unstable_root, ckpt):
        self.ckpt = ckpt

    def __call__(self, batch):
        res = []
        for img in batch:
            bg = float(np.percentile(img, 90))
            mask = img < bg - 0.25
            if mask.sum() < 40:
                res.append({"visibility_confidence": 0.03, "x_bin_index": 4, "x_value": 0.0,
                            "x_soft": 0.0, "size_bucket_index": 0, "size_value": 0.0})
                continue
            cols = mask.sum(0).astype(float)
            cx = float((cols * np.arange(img.shape[1])).sum() / cols.sum())
            x = (cx - 63.5) / 64.0
            rows = np.where(mask.any(1))[0]
            hgt = float(rows[-1] - rows[0] + 1) / img.shape[0]
            res.append({"visibility_confidence": 0.97,
                        "x_bin_index": min(8, max(0, S.bucketize(x, S.XBIN9_INNER))),
                        "x_value": x, "x_soft": x,
                        "size_bucket_index": S.size_to_bucket(hgt), "size_value": hgt})
        return res


class BlindModel(StubModel):
    """Sees nobody, ever (the 'model detected nobody' case)."""
    def __call__(self, batch):
        return [{"visibility_confidence": 0.02, "x_bin_index": 4, "x_value": 0.0, "x_soft": 0.0,
                 "size_bucket_index": 0, "size_value": 0.0} for _ in batch]


class ParanoidModel(StubModel):
    """Sees a person in everything (so a false track really is reported)."""
    def __call__(self, batch):
        return [{"visibility_confidence": 0.99, "x_bin_index": 4, "x_value": 0.0, "x_soft": 0.0,
                 "size_bucket_index": 1, "size_value": 0.4} for _ in batch]


# --------------------------------------------------------------------------
# running the scorer in-process
# --------------------------------------------------------------------------
def run_scorer(argv, model_cls=StubModel):
    """Returns (exit_code_or_None, stdout, parsed scores.json or None)."""
    old_model, old_argv = S.Model, sys.argv
    S.Model = model_cls
    buf = io.StringIO()
    code = None
    try:
        sys.argv = ["score_real_frames.py"] + [str(a) for a in argv]
        with contextlib.redirect_stdout(buf):
            S.main()
    except SystemExit as e:
        code = e.code
    finally:
        S.Model, sys.argv = old_model, old_argv
    out = buf.getvalue()
    jf = Path(argv[0]) / "scores.json"
    data = json.loads(jf.read_text()) if jf.exists() else None
    return code, out, data


def mirror_line(out):
    for ln in out.splitlines():
        if ln.startswith("MIRROR CHECK"):
            return ln.strip()
    return "<no MIRROR CHECK line>"


# --------------------------------------------------------------------------
# checks
# --------------------------------------------------------------------------
CHECKS = []


def check(name):
    def deco(fn):
        CHECKS.append((name, fn))
        return fn
    return deco


def need(cond, msg):
    if not cond:
        raise AssertionError(msg)


@check("filename parsing (good, garbled, unlabelled)")
def t_parse(tmp):
    good = S.parse_name(Path("d2.5_b-25_vis1_subj-p01_light-room_take1_f00012_t1757530000.123.png"))
    need(good is not None, "good name did not parse")
    need(good["dist"] == 2.5 and good["bearing"] == -25.0 and good["vis"] == 1, f"bad labels {good}")
    need(good["subject"] == "p01" and good["light"] == "room" and good["take"] == 1, f"bad labels {good}")
    need(good["frame"] == 12 and abs(good["time"] - 1757530000.123) < 1e-3, f"bad f/t {good}")
    garbled = S.parse_name(Path("d2.5_bLEFT_vis1_subj-p01_light-room_take1_f00001_t1.0.png"))
    need(garbled is not None and garbled["bearing"] is None,
         f"garbled bearing should be None, got {garbled}")
    need(S.parse_name(Path("IMG_1234.jpg")) is None, "unlabelled file should be ignored")
    need(S.parse_name(Path("d2.5_b0_subj-p01_take1_f1_t1.0.png")) is None,
         "no vis token -> must be ignored")
    return "good/garbled/unlabelled all handled"


@check("bearing -> x -> bin geometry (hand-checked)")
def t_geometry(tmp):
    # x = tan(bearing)/tan(35 deg); 9 equal bins over [-1, 1]
    table = [(-25, -0.6661, 1), (-10, -0.2519, 3), (-8, -0.2007, 3), (0, 0.0, 4),
             (8, 0.2007, 5), (10, 0.2519, 5), (25, 0.6661, 7)]
    for bear, want_x, want_bin in table:
        x = S.expected_x(bear, 70.0)
        need(abs(x - want_x) < 1e-3, f"expected_x({bear}) = {x:.4f}, hand value {want_x}")
        need(S.x_to_bin(x) == want_bin, f"x_to_bin({x:.3f}) = {S.x_to_bin(x)}, want {want_bin}")
        need(abs(S.x_to_bearing(x, 70.0) - bear) < 1e-6, "x_to_bearing is not the inverse")
    need(S.x_to_bin(S.expected_x(40, 70.0)) is None, "40 deg is outside the crop: bin must be None")
    need(S.expected_x(-25, 70.0) < 0, "NEGATIVE bearing must give NEGATIVE x (drone's LEFT)")
    need(S.x_to_bin(S.expected_x(-25, 70.0)) < 4 < S.x_to_bin(S.expected_x(25, 70.0)),
         "left bin must be below 4 and right above 4")
    return "7 bearings match hand-computed x and bin; left<4<right"


@check("expected size bucket from distance")
def t_size(tmp):
    for dist, want_s, want_b in [(1.5, 0.8093, 3), (2.5, 0.4856, 1), (3.5, 0.3468, 1)]:
        s = S.expected_size(dist, PERSON_H, CAM_H, 70.0)
        need(abs(s - want_s) < 1e-3, f"expected_size({dist}) = {s:.4f}, hand value {want_s}")
        need(S.size_to_bucket(s) == want_b, f"bucket({s:.3f}) = {S.size_to_bucket(s)}, want {want_b}")
    return "1.5/2.5/3.5 m -> 0.81/0.49/0.35 -> buckets 3/1/1"


@check("split_runs splits a re-recorded clip")
def t_split(tmp):
    rows = [{"frame": f, "time": T0 + i, "file": str(i)} for i, f in enumerate([1, 2, 3, 1, 2])]
    runs = S.split_runs(rows)
    need(len(runs) == 2 and [len(r) for r in runs] == [3, 2], f"got runs {[len(r) for r in runs]}")
    return "frame numbers restarting -> 2 runs"


@check("follower_track reproduces the 3-frame confirmation rule")
def t_track(tmp):
    starts, flags = S.follower_track([0.8, 0.8, 0.8, 0.8, 0.1, 0.9, 0.9, 0.9], 0.7, 0.45, 3)
    need(flags == [False, False, True, True, False, False, False, True], f"flags {flags}")
    need(starts == 2, f"starts {starts}, want 2")
    starts, _ = S.follower_track([0.8, 0.8, 0.6, 0.8, 0.8], 0.7, 0.45, 3)
    need(starts == 0, f"two short bursts must not confirm a track, got {starts} starts")
    return "confirm at 3 frames >=0.7, drop below 0.45, re-confirm: 2 starts"


@check("MIRROR CHECK = PASS on a correct folder (+ bins, size, no false tracks)")
def t_pass(tmp):
    d = standard_folder(tmp / "pass", n=ARGS.frames)
    code, out, js = run_scorer([d])
    need(code is None, f"scorer exited: {code}")
    need(js["mirror_check"]["verdict"] == "PASS", f"verdict {js['mirror_check']['verdict']}")
    need("-> PASS" in mirror_line(out), mirror_line(out))
    need(js["mirror_check"]["left_n"] > 0 and js["mirror_check"]["right_n"] > 0,
         f"both sides must be counted: {js['mirror_check']}")
    need(js["overall"]["bin_acc"] == 1.0, f"bin acc {js['overall']['bin_acc']}")
    need(js["overall"]["size_acc"] == 1.0, f"size acc {js['overall']['size_acc']}")
    need(js["overall"]["vis_acc"] == 1.0, f"vis acc {js['overall']['vis_acc']}")
    need(js["empty_false_tracks"] == 0, f"false tracks {js['empty_false_tracks']}")
    need("confirmed (false) tracks = 0" in out and "-> OK" in out, "EMPTY line missing/not OK")
    need(abs(js["overall"]["bear_err"]) < 2.0, f"bearing err {js['overall']['bear_err']}")
    return f"{mirror_line(out)[:96]} | bin acc 100%, 0 false tracks"


@check("MIRROR CHECK = MIRRORED on a left-right flipped copy  <-- the safety one")
def t_mirrored(tmp):
    d = standard_folder(tmp / "mirrored", n=ARGS.frames, flip=True)
    code, out, js = run_scorer([d])
    need(code is None, f"scorer exited: {code}")
    need(js["mirror_check"]["verdict"] == "MIRRORED",
         f"FLIPPED FRAMES REPORTED AS {js['mirror_check']['verdict']} - {mirror_line(out)}")
    need("MIRRORED" in out and "flipped" in out, "printed line does not say MIRRORED/flipped")
    need(js["mirror_check"]["left_ok"] == 0.0 and js["mirror_check"]["right_ok"] == 0.0,
         f"{js['mirror_check']}")
    return mirror_line(out)[:118]


@check("MIRROR CHECK = MIRRORED from the protocol's 2-clip mirror folder, flipped")
def t_mirrored_protocol(tmp):
    """Exactly what section 3.2 records: two 10 s clips at 2.5 m, -25 and +25."""
    for flip in (False, True):
        d = tmp / ("mirror_ok" if not flip else "mirror_flipped")
        write_clip(d, 2.5, -25, 1, n=ARGS.frames, take=1, seed=1, flip=flip)
        write_clip(d, 2.5, 25, 1, n=ARGS.frames, take=2, seed=2, flip=flip)
        code, out, js = run_scorer([d])
        want = "MIRRORED" if flip else "PASS"
        need(js["mirror_check"]["verdict"] == want,
             f"flip={flip}: got {js['mirror_check']['verdict']}, want {want} - {mirror_line(out)}")
        need(js["n_frames"] == 2 * ARGS.frames, f"frame count {js['n_frames']}")
        need("NONE RECORDED" in out, "a folder with no vis0 clip must not look like a clean empty check")
        if ARGS.frames < 10:                 # short clips must not read as a confident verdict
            need("too few to trust" in out, f"no thin-data warning for {ARGS.frames} frames/side")
            need(js["mirror_check"]["thin_sides"] == ["LEFT", "RIGHT"],
                 f"thin_sides {js['mirror_check']['thin_sides']}")
    return "two-clip mirror folder: upright -> PASS, flipped -> MIRRORED (+ thin/empty warnings)"


@check("MIRROR CHECK = FAIL when the marks/labels disagree with the image")
def t_fail(tmp):
    d = standard_folder(tmp / "fail", n=ARGS.frames, lie=True)
    code, out, js = run_scorer([d])
    need(js["mirror_check"]["verdict"] == "FAIL",
         f"got {js['mirror_check']['verdict']} - {mirror_line(out)}")
    need("FAIL" in out, "printed line does not say FAIL")
    return mirror_line(out)[:118]


@check("MIRROR CHECK = NO DATA when the model sees nobody")
def t_nodata(tmp):
    d = standard_folder(tmp / "nodata", n=ARGS.frames)
    code, out, js = run_scorer([d], model_cls=BlindModel)
    need(js["mirror_check"]["verdict"] == "NO DATA",
         f"got {js['mirror_check']['verdict']} - {mirror_line(out)}")
    need("NO DATA" in out and "stop and report" in out, "printed line is not the NO DATA one")
    # ... and the same folder with nothing drawn in it (empty room labelled vis1)
    d2 = standard_folder(tmp / "nodata2", n=ARGS.frames, person=False)
    _, out2, js2 = run_scorer([d2])
    need(js2["mirror_check"]["verdict"] == "NO DATA", f"empty-room frames: {js2['mirror_check']}")
    return "blind model and person-free frames both -> NO DATA"


@check("ONE mark only is NO DATA both ways; one side + a second mark still works")
def t_one_side(tmp):
    """A single clip at a single bearing cannot answer the mirror question.

    Whatever the camera is doing, every frame carries the same target, so a
    working model and a model stuck on that one bin print identical numbers:
    100% (a PASS that a dead model earns just as easily) or 0% (a MIRRORED that
    a dead model earns just as easily). The tool used to print both. It now
    refuses, and says which extra clip to record.
    """
    for nm, flip in (("left_only", False), ("left_only_flipped", True)):
        d = tmp / nm
        write_clip(d, 2.5, -25, 1, n=ARGS.frames, take=1, seed=3, flip=flip)
        code, out, js = run_scorer([d])
        mc = js["mirror_check"]
        need(mc["verdict"] == "NO DATA",
             f"{nm}: one mark cannot support {mc['verdict']} - {mirror_line(out)}")
        need(mc["target_bin_span"] == 0, f"{nm}: target_bin_span {mc['target_bin_span']}")
        need("only one target position" in out, f"{nm}: no reason given - {mirror_line(out)}")
        need("record a clip on the other side" in out.lower(),
             f"{nm}: does not say what to record - {mirror_line(out)}")

    # ... but one SIDE only is still usable when the folder holds a second mark
    # (here a straight-ahead clip): the model then has to prove it moves its bins.
    for nm, flip, want in (("left_plus_centre", False, "PASS"),
                           ("left_plus_centre_flipped", True, "MIRRORED")):
        d = tmp / nm
        write_clip(d, 2.5, -25, 1, n=ARGS.frames, take=1, seed=3, flip=flip)
        write_clip(d, 2.5, 0, 1, n=ARGS.frames, take=2, seed=4, flip=flip)
        code, out, js = run_scorer([d])
        mc = js["mirror_check"]
        need(mc["verdict"] == want, f"{nm}: got {mc['verdict']}, want {want} - {mirror_line(out)}")
        need(mc["right_n"] == 0, f"{nm}: right side should have no frames, got {mc['right_n']}")
        need(mc["one_side_only"] is True, f"{nm}: JSON must flag the one-sided result: {mc}")
        need("only LEFT data" in out, f"{nm}: one-sided verdict must say so: {mirror_line(out)}")
    return "one mark -> NO DATA either way; one side + a b0 clip -> PASS / MIRRORED as before"


@check("a DEAD model is never MIRRORED and never PASS  <-- the safety one")
def t_dead_model(tmp):
    """A model whose output never changes carries no left/right information.

    It scores 0% on a side whose frames all land on the other side - which is
    exactly what a mirrored camera scores - and 100% on a side its stuck bin
    happens to agree with. Reported as either, the team acts on a diagnosis the
    data cannot support: they re-mount the camera, or they fly.
    """
    class Dead(StubModel):
        BIN = 4
        def __call__(self, batch):
            return [{"visibility_confidence": 0.99, "x_bin_index": self.BIN, "x_value": 0.0,
                     "x_soft": 0.0, "size_bucket_index": 1, "size_value": 0.4} for _ in batch]

    folders = {}
    both = tmp / "dead_both"
    write_clip(both, 2.5, -25, 1, n=ARGS.frames, take=1, seed=50)
    write_clip(both, 2.5, 25, 1, n=ARGS.frames, take=2, seed=51)
    folders["both sides"] = both
    for side, bear in (("RIGHT only", 25), ("LEFT only", -25)):
        d = tmp / f"dead_{bear}"
        write_clip(d, 2.5, bear, 1, n=ARGS.frames, take=1, seed=52 + bear)
        write_clip(d, 2.5, 0, 1, n=ARGS.frames, take=2, seed=80 + bear)   # the second mark
        folders[side] = d

    seen = set()
    for where, d in folders.items():
        for b in (0, 3, 4, 5, 8):                       # stuck low, left, centre, right, high
            cls = type(f"Dead{b}", (Dead,), {"BIN": b})
            code, out, js = run_scorer([d], model_cls=cls)
            mc = js["mirror_check"]
            seen.add(mc["verdict"])
            need(mc["verdict"] not in ("PASS", "MIRRORED", "WEAK"),
                 f"{where}, model stuck on bin {b}: verdict {mc['verdict']} - {mirror_line(out)}")
            need(mc["model_dead"] is True, f"{where}, bin {b}: model_dead not set - {mc}")
            need("NOT a mirror" in out, f"{where}, bin {b}: does not say it is not a mirror")
            need("flipped" not in mirror_line(out),
                 f"{where}, bin {b}: still blames a flipped image - {mirror_line(out)}")
    # and a live model on the same folders must still reach a real verdict
    _, _, ok = run_scorer([folders["both sides"]])
    need(ok["mirror_check"]["verdict"] == "PASS",
         f"a working model on the same folder now reports {ok['mirror_check']['verdict']}")
    return f"15 dead-model runs (5 stuck bins x 3 folders) -> {'/'.join(sorted(seen))}, never MIRRORED"


@check("a merely NOISY model is WEAK, not 'check labels and FOV'")
def t_weak_band(tmp):
    """85% per side is consistent: both sides right more often than not.

    That cannot be a mirror and cannot be swapped marks - it is a noisy network.
    It used to land in FAIL 'left/right bins inconsistent; check labels and FOV',
    which sends a tired operator to re-tape the floor over a model problem.
    """
    class Noisy(StubModel):
        """Every 7th detected frame lands on the wrong side: ~86% correct per side.
        Deterministic on purpose - a random fixture drifts across the 90% PASS line."""
        def __init__(self, *a):
            super().__init__(*a)
            self.seen = 0
        def __call__(self, batch):
            out = StubModel.__call__(self, batch)
            for r in out:
                if r["visibility_confidence"] > 0.5:
                    if self.seen % 7 == 0:
                        r["x_bin_index"] = 8 - r["x_bin_index"]    # this one frame lands wrong
                        r["x_soft"] = -r["x_soft"]
                    self.seen += 1
            return out

    d = tmp / "noisy"
    write_clip(d, 2.5, -25, 1, n=max(35, ARGS.frames), take=1, seed=5)
    write_clip(d, 2.5, 25, 1, n=max(35, ARGS.frames), take=2, seed=6)
    code, out, js = run_scorer([d], model_cls=Noisy)
    mc = js["mirror_check"]
    need(mc["verdict"] == "WEAK", f"verdict {mc['verdict']}, want WEAK - {mirror_line(out)}")
    need(min(mc["left_ok"], mc["right_ok"]) >= 0.6 and min(mc["left_ok"], mc["right_ok"]) < 0.9,
         f"this fixture is meant to sit in the weak band: {mc['left_ok']}, {mc['right_ok']}")
    line = mirror_line(out)
    need("NOT mirrored" in line and "NOT swapped labels" in line,
         f"the WEAK headline must rule out the camera and the marks: {line}")
    need("do NOT go and re-check the floor tape" in out, "WEAK must call off the tape hunt")
    need("check labels and FOV" not in out, "still points the operator at the labels")
    need("do not fly on it" in out, "WEAK must still read as a stop")
    # the operator copies this line onto the log sheet: the verdict has to fit on it
    said = line.split("-> ", 1)[1]
    need(len(said) < 110, f"the verdict has to fit a log sheet, got {len(said)} chars: {said}")
    return f"{mc['left_ok']:.0%}/{mc['right_ok']:.0%} -> WEAK (not a mirror, not the tape, not a PASS)"


@check("sides that genuinely DISAGREE still point at the marks and the FOV")
def t_sides_disagree(tmp):
    """One side reads right and the other reads wrong. A mirror cannot do that,
    a stuck head cannot do that: the marks or the FOV are wrong. This is the one
    case where 'check labels and FOV' is the correct thing to say."""
    class RightSideFlipped(StubModel):
        """Correct for a person on the left, mirrored for a person on the right."""
        def __call__(self, batch):
            out = StubModel.__call__(self, batch)
            for r in out:
                if r["visibility_confidence"] > 0.5 and r["x_bin_index"] > 4:
                    r["x_bin_index"] = 8 - r["x_bin_index"]
                    r["x_soft"] = -r["x_soft"]
            return out

    d = tmp / "disagree"
    write_clip(d, 2.5, -25, 1, n=ARGS.frames, take=1, seed=60)
    write_clip(d, 2.5, 25, 1, n=ARGS.frames, take=2, seed=61)
    write_clip(d, 2.5, 0, 1, n=ARGS.frames, take=3, seed=62)   # so the model is visibly alive
    code, out, js = run_scorer([d], model_cls=RightSideFlipped)
    mc = js["mirror_check"]
    need(mc["verdict"] == "FAIL", f"verdict {mc['verdict']}, want FAIL - {mirror_line(out)}")
    need(mc["left_ok"] == 1.0 and mc["right_ok"] == 0.0, f"fixture drifted: {mc}")
    need("DISAGREE" in out and "floor marks" in out, f"wrong wording: {mirror_line(out)}")
    return "LEFT 100% / RIGHT 0% -> FAIL that names the marks and the FOV"


class CoinFlip(StubModel):
    """Every other detected frame lands on the wrong side: ~50% per side, both sides.
    Deterministic so the fixture cannot drift across a threshold."""
    def __init__(self, *a):
        super().__init__(*a)
        self.seen = 0
    def __call__(self, batch):
        out = StubModel.__call__(self, batch)
        for r in out:
            if r["visibility_confidence"] > 0.5:
                if self.seen % 2 == 0:
                    r["x_bin_index"] = 8 - r["x_bin_index"]
                    r["x_soft"] = -r["x_soft"]
                self.seen += 1
        return out


@check("a folder with ONE side never says 'the two sides disagree'")
def t_one_side_wording(tmp):
    """Found by the verifier, not the implementer. With right_n = 0 there IS no
    second side, yet a single LEFT side near chance printed 'FAIL: the two sides
    DISAGREE - a mirror cannot do that ... so this is not the camera', which is
    false twice over: nothing disagreed, and a mirror is exactly what one noisy
    side cannot rule out. Every one-sided verdict must be honest about that."""
    d = tmp / "oneside_chance"
    write_clip(d, 2.5, -25, 1, n=max(30, ARGS.frames), take=1, seed=71)
    write_clip(d, 2.5, -10, 1, n=max(30, ARGS.frames), take=2, seed=72)
    code, out, js = run_scorer([d], model_cls=CoinFlip)
    mc = js["mirror_check"]
    need(mc["right_n"] == 0 and mc["one_side_only"], f"fixture drifted, wanted one side: {mc}")
    need(0.40 < mc["left_ok"] < 0.60, f"fixture must sit near chance: {mc['left_ok']}")
    need(mc["verdict"] == "FAIL", f"near chance is not flyable: {mirror_line(out)}")
    need("two sides" not in out and "both sides are" not in out,
         f"claims a second side that was never recorded: {mirror_line(out)}")
    need("a mirror is NOT ruled out" in out,
         f"one noisy side cannot exonerate the camera: {mirror_line(out)}")
    need("not the camera" not in out, f"exonerates the camera on one side: {mirror_line(out)}")
    # the other one-sided bands must not invent a second side either
    for frac_name, cls in (("mostly wrong", _biased(0.25)), ("weak", _biased(0.72))):
        _, out2, js2 = run_scorer([d], model_cls=cls)
        need("both sides are" not in out2 and "both sides consistent" not in out2,
             f"one-sided {frac_name} still says 'both sides': {mirror_line(out2)}")
    said = mirror_line(out).split("-> ", 1)[1]
    need(len(said) < 110, f"the verdict has to fit a log sheet, got {len(said)}: {said}")
    return "one LEFT side at ~50% -> FAIL naming that side, mirror not ruled out, no phantom 2nd side"


def _biased(frac):
    """Model correct `frac` of detected frames, deterministically."""
    step = max(2, int(round(1 / max(1e-6, 1 - frac))))
    class B(StubModel):
        def __init__(self, *a):
            super().__init__(*a)
            self.seen = 0
        def __call__(self, batch):
            out = StubModel.__call__(self, batch)
            for r in out:
                if r["visibility_confidence"] > 0.5:
                    if self.seen % step == 0:
                        r["x_bin_index"] = 8 - r["x_bin_index"]
                        r["x_soft"] = -r["x_soft"]
                    self.seen += 1
            return out
    return B


@check("both sides near chance is NOT reported as the sides disagreeing")
def t_both_sides_near_chance(tmp):
    """Also found by the verifier. 53%/51% is two sides AGREEING with each other,
    both uninformative - yet it printed 'the two sides DISAGREE ... so this is not
    the camera: check the bearing labels and the floor marks', the same re-tape-the-
    floor misdirection the WEAK band was added to stop, one band lower."""
    d = tmp / "bothchance"
    write_clip(d, 2.5, -25, 1, n=max(30, ARGS.frames), take=1, seed=81)
    write_clip(d, 2.5, 25, 1, n=max(30, ARGS.frames), take=2, seed=82)
    code, out, js = run_scorer([d], model_cls=CoinFlip)
    mc = js["mirror_check"]
    need(mc["left_n"] > 0 and mc["right_n"] > 0, f"wanted two sides: {mc}")
    need(0.40 < mc["left_ok"] < 0.60 and 0.40 < mc["right_ok"] < 0.60,
         f"fixture must sit near chance on both sides: {mc['left_ok']}, {mc['right_ok']}")
    need(mc["verdict"] == "FAIL", f"near chance is not flyable: {mirror_line(out)}")
    need("DISAGREE" not in out, f"sides at 50/50 agree with each other: {mirror_line(out)}")
    need("near chance" in out, f"should name the real problem: {mirror_line(out)}")
    need("do NOT re-tape the floor" in out, "must call off the tape hunt like WEAK does")
    # and the genuine-disagreement case must still survive this new branch
    _, out3, js3 = run_scorer([standard_folder(tmp / "flip3", n=ARGS.frames, flip=True)])
    need(js3["mirror_check"]["verdict"] == "MIRRORED",
         f"a real flip stopped being MIRRORED: {mirror_line(out3)}")
    return f"{mc['left_ok']:.0%}/{mc['right_ok']:.0%} -> FAIL 'near chance', not 'sides disagree'"


@check("the bearing convention is printed under EVERY verdict (double-negative blind spot)")
def t_convention_printed(tmp):
    """The check compares the model against a HUMAN-WRITTEN label. Marks written
    with left/right backwards on a mirrored camera cancel out and print PASS.
    Nothing in the data can catch that, so the assumed convention is printed
    every time and the operator is told the two errors cancel."""
    cases = []
    d = standard_folder(tmp / "conv_pass", n=ARGS.frames)
    cases.append(("PASS", run_scorer([d])))
    d2 = standard_folder(tmp / "conv_mirrored", n=ARGS.frames, flip=True)
    cases.append(("MIRRORED", run_scorer([d2])))
    d3 = standard_folder(tmp / "conv_nodata", n=ARGS.frames)
    cases.append(("NO DATA", run_scorer([d3], model_cls=BlindModel)))
    for want, (code, out, js) in cases:
        need(js["mirror_check"]["verdict"] == want,
             f"fixture drifted: wanted {want}, got {js['mirror_check']['verdict']}")
        need("convention assumed" in out, f"{want}: no convention line printed")
        need("NEGATIVE bearing" in out and "LEFT" in out and "BEHIND the drone" in out,
             f"{want}: convention line does not state the physical convention")
        need("cancel" in out and "prints PASS" in out,
             f"{want}: the double-negative (bad marks + mirrored camera) is not spelled out")
    return "convention + 'two wrongs cancel' printed under PASS, MIRRORED and NO DATA"


@check("empty folder and missing folder fail cleanly")
def t_empty_folder(tmp):
    d = tmp / "empty_folder"
    d.mkdir(parents=True)
    code, out, js = run_scorer([d])
    need(isinstance(code, str) and "no labelled frames" in code, f"exit was {code!r}")
    (d / "notes.txt").write_text("nothing here")
    code, out, js = run_scorer([d])
    need(isinstance(code, str) and "no labelled frames" in code, f"exit was {code!r}")
    missing = tmp / "does_not_exist"
    code, out, js = run_scorer([missing])
    need(isinstance(code, str), f"missing folder must exit with a message, got {code!r}")
    need("does not exist" in code or "no such" in code.lower(),
         f"message should name the missing folder, got {code!r}")
    return f"empty -> '{'no labelled frames'}'; missing -> '{code[:60]}'"


@check("frames with missing or garbled labels are reported, not crashed on")
def t_bad_labels(tmp):
    d = tmp / "bad_labels"
    write_clip(d, 2.5, -25, 1, n=ARGS.frames, take=1, seed=4)
    write_clip(d, 2.5, 25, 1, n=ARGS.frames, take=2, seed=5)
    img = draw_frame(2.5, 0.0)
    Image.fromarray(img).save(d / "IMG_0001.png")                       # no labels at all
    Image.fromarray(img).save(d / "d2.5_bWEST_vis1_subj-p01_light-room_take9_f00001_t1.0.png")
    Image.fromarray(img).save(d / "vis1_subj-p01_light-room_take8_f00001_t2.0.png")  # no d/b
    code, out, js = run_scorer([d])
    need(code is None, f"scorer exited: {code}")
    need("without labels ignored" in out, "unlabelled file was not reported")
    need(js["n_frames"] == 2 * ARGS.frames + 2, f"scored {js['n_frames']} frames")
    need(js["mirror_check"]["verdict"] == "PASS", f"{js['mirror_check']}")
    need("no bearing label" in out, "a vis1 clip with no usable bearing must be called out")
    return "1 unlabelled skipped with a note, 2 bearing-less clips flagged, mirror still PASS"


@check("a corrupt/truncated image does not kill the run")
def t_corrupt(tmp):
    d = tmp / "corrupt"
    paths = write_clip(d, 2.5, -25, 1, n=ARGS.frames, take=1, seed=6)
    write_clip(d, 2.5, 25, 1, n=ARGS.frames, take=2, seed=7)
    good = paths[0].read_bytes()
    (d / "d2.5_b-25_vis1_subj-p01_light-room_take3_f00001_t9.000.png").write_bytes(good[: len(good) // 3])
    (d / "d2.5_b25_vis1_subj-p01_light-room_take3_f00002_t9.100.png").write_bytes(b"not a png at all")
    (d / "._d2.5_b25_vis1_subj-p01_light-room_take4_f00001_t9.200.png").write_bytes(b"\x00\x05\x16\x07")
    code, out, js = run_scorer([d])
    need(code is None, f"scorer exited: {code}")
    need("unreadable" in out.lower(), f"no unreadable-file note in output:\n{out[:400]}")
    need("sidecar" in out.lower(), f"no macOS sidecar note in output:\n{out[:400]}")
    need(js["n_frames"] == 2 * ARGS.frames, f"scored {js['n_frames']}, want {2 * ARGS.frames}")
    need(js["mirror_check"]["verdict"] == "PASS", f"{js['mirror_check']}")
    need(js.get("unreadable_files") == 2, f"unreadable count {js.get('unreadable_files')}")
    need(js.get("sidecar_files") == 1, f"sidecar count {js.get('sidecar_files')}")
    return "2 corrupt frames skipped + 1 macOS ._ sidecar ignored; the rest scored"


@check("a folder mixing RAW (.png) and JPEG (.jpg) clips is called out")
def t_jpeg(tmp):
    d = tmp / "mixed"
    write_clip(d, 2.5, -25, 1, n=ARGS.frames, take=1, seed=8)
    write_clip(d, 2.5, 25, 1, n=ARGS.frames, take=2, seed=9, ext=".jpg")
    code, out, js = run_scorer([d])
    need(code is None, f"scorer exited: {code}")
    need("NOT valid for scoring" in out, f"no JPEG warning:\n{out[:400]}")
    need(js.get("jpeg_frames") == ARGS.frames, f"jpeg count {js.get('jpeg_frames')}")
    need(js["mirror_check"].get("jpeg_frames_used", 0) == ARGS.frames,
         f"JPEG frames in the mirror check must be flagged: {js['mirror_check']}")
    need("of those frames are JPEG" in out, "the mirror verdict must say it leans on JPEG frames")
    return f"{ARGS.frames} JPEG frames flagged (protocol: raw only)"


@check("a colour (Bayer) camera read as gray is caught, and mono frames are not")
def t_bayer(tmp):
    """Protocol section 3.1 asks a human to spot the checkerboard by eye. The
    scorer measures it: the four positions of each 2x2 cell have different
    average brightness on a colour sensor (R, G, G, B) and the same on a mono one."""
    d = tmp / "bayer"
    d.mkdir(parents=True, exist_ok=True)
    for take, bear in ((1, -25), (2, 25)):
        for i in range(1, ARGS.frames + 1):
            img = draw_frame(2.5, bear, rng=np.random.default_rng(30 + i)).astype(np.float32)
            img[0::2, 0::2] *= 0.80          # R site
            img[1::2, 1::2] *= 1.15          # B site   (G sites left alone)
            Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)).save(
                d / clip_name(2.5, bear, 1, "p01", "room", take, i, T0 + i * 0.1))
    code, out, js = run_scorer([d])
    need("Bayer" in out, f"mosaic not caught:\n{out[:400]}")
    need(js["bayer_phase_spread_dn"] > S.BAYER_WARN_DN,
         f"phase spread {js['bayer_phase_spread_dn']:.2f} DN")
    clean = standard_folder(tmp / "mono", n=ARGS.frames)
    _, out2, js2 = run_scorer([clean])
    need("Bayer" not in out2, "false alarm on mono frames")
    need(js2["bayer_phase_spread_dn"] < 1.0, f"mono spread {js2['bayer_phase_spread_dn']:.2f} DN")
    return (f"mosaic {js['bayer_phase_spread_dn']:.0f} DN -> warned; "
            f"mono {js2['bayer_phase_spread_dn']:.2f} DN -> quiet (threshold {S.BAYER_WARN_DN} DN)")


@check("false tracks on a no-person clip are counted and shouted about")
def t_false_tracks(tmp):
    d = tmp / "false_tracks"
    write_clip(d, None, None, 0, n=ARGS.frames, subj="plush", take=1, seed=10, person=False)
    code, out, js = run_scorer([d], model_cls=ParanoidModel)
    need(js["empty_false_tracks"] == 1, f"want 1 false track, got {js['empty_false_tracks']}")
    need("FALSE TRACKS" in out, "a false track must be shouted about")
    _, out2, js2 = run_scorer([d])           # blob finder sees nothing in an empty frame
    need(js2["empty_false_tracks"] == 0, f"clean run got {js2['empty_false_tracks']} false tracks")
    need("-> OK" in out2, "clean empty run should print OK")
    return "1 false track reported for a always-on model, 0 for a quiet one"


@check("scores.csv and scores.json have the documented columns and every frame")
def t_outputs(tmp):
    d = standard_folder(tmp / "outputs", n=ARGS.frames)
    code, out, js = run_scorer([d])
    cols = ["file", "subject", "light", "take", "run", "dist", "bearing", "vis", "frame", "conf",
            "seen", "tracking", "x_bin", "exp_bin", "x_soft", "exp_x", "bear_model", "bear_err",
            "size_bucket", "exp_size_bucket", "size_value", "exp_size"]
    with open(d / "scores.csv", newline="") as f:
        rd = csv.DictReader(f)
        need(rd.fieldnames == cols, f"CSV columns are {rd.fieldnames}")
        rows = list(rd)
    n_expected = ARGS.frames * (15 + 2)
    need(len(rows) == n_expected, f"CSV has {len(rows)} rows, want {n_expected}")
    need(all(r["file"] and r["conf"] for r in rows), "CSV has blank file/conf cells")
    vis1 = [r for r in rows if r["vis"] == "1"]
    need(all(r["exp_bin"] != "" and r["x_bin"] != "" for r in vis1), "vis1 rows missing bins")
    for key in ("ckpt", "frames_dir", "n_frames", "crop_hfov_deg", "overall", "groups", "clips",
                "mirror_check", "empty_false_tracks", "follower", "vis_threshold"):
        need(key in js, f"scores.json is missing '{key}'")
    need(js["n_frames"] == n_expected, f"json n_frames {js['n_frames']}")
    need(len(js["clips"]) == 17, f"{len(js['clips'])} clips in json, want 17")
    need(set(js["groups"]) == {"dist", "bearing", "light", "subject"}, f"groups {list(js['groups'])}")
    need(abs(js["crop_hfov_deg"] - 70.0) < 1e-9, f"crop hfov {js['crop_hfov_deg']}")
    need(all(c["expected_bin"] is not None for c in js["clips"] if c["vis"] == 1),
         "a vis1 clip has no expected bin")
    return f"CSV {len(rows)} rows x {len(cols)} documented columns; JSON keys all present"


@check("--full-hfov changes the crop FOV the way the protocol says")
def t_full_hfov(tmp):
    d = tmp / "hfov"
    write_clip(d, 2.5, -25, 1, n=2, take=1, seed=11)
    write_clip(d, 2.5, 25, 1, n=2, take=2, seed=12)
    code, out, js = run_scorer([d, "--full-hfov", "86"])
    want = math.degrees(2 * math.atan(math.tan(math.radians(86) / 2) * H / W))
    need(abs(js["crop_hfov_deg"] - want) < 1e-6, f"crop hfov {js['crop_hfov_deg']}, want {want}")
    need(abs(want - 70.0) < 2.0, f"86 deg full FOV should give ~70 deg crop, got {want:.1f}")
    return f"--full-hfov 86 on a {W}x{H} frame -> crop {want:.1f} deg"


@check("clips re-recorded without --take are split into runs, not merged")
def t_runs(tmp):
    d = tmp / "runs"
    write_clip(d, 2.5, -25, 1, n=ARGS.frames, take=1, seed=13, t0=T0)
    write_clip(d, 2.5, -25, 1, n=ARGS.frames, take=1, seed=14, t0=T0 + 600)
    write_clip(d, 2.5, 25, 1, n=ARGS.frames, take=1, seed=15)
    code, out, js = run_scorer([d])
    need("separate recordings share the labels" in out, "re-recorded clip was not reported")
    need(len(js["clips"]) == 3, f"{len(js['clips'])} clips, want 3 (2 runs + 1)")
    need({c["run"] for c in js["clips"]} == {1, 2}, f"runs {[c['run'] for c in js['clips']]}")
    return "two recordings with the same labels scored as run1/run2"


@check("a wrong --ckpt or --unstable-root says so instead of a traceback")
def t_bad_ckpt(tmp):
    d = tmp / "ckpt"
    write_clip(d, 2.5, -25, 1, n=2, take=1, seed=19)
    code, out, js = run_scorer([d, "--ckpt", tmp / "nope.pth"])
    need(isinstance(code, str) and "checkpoint not found" in code, f"exit was {code!r}")
    code, out, js = run_scorer([d, "--unstable-root", tmp])
    need(isinstance(code, str) and "model code" in code, f"exit was {code!r}")
    return "missing checkpoint and wrong --unstable-root both exit with a plain message"


@check("a read-only folder still prints the verdict")
def t_readonly(tmp):
    d = tmp / "readonly"
    write_clip(d, 2.5, -25, 1, n=2, take=1, seed=20)
    write_clip(d, 2.5, 25, 1, n=2, take=2, seed=21)
    d.chmod(0o555)
    try:
        code, out, js = run_scorer([d])
    finally:
        d.chmod(0o755)
    need(code is None, f"scorer exited: {code}")
    need("MIRROR CHECK" in out and "-> PASS" in out, "verdict must still be printed")
    need("COULD NOT WRITE" in out, f"the failed write must be reported:\n{out[-300:]}")
    # the documented way out: send the results somewhere writable
    csv_out, json_out = tmp / "ro.csv", tmp / "ro.json"
    d.chmod(0o555)
    try:
        code, out, _ = run_scorer([d, "--csv", csv_out, "--json", json_out])
    finally:
        d.chmod(0o755)
    need(code is None and csv_out.exists() and json_out.exists(),
         f"--csv/--json did not write: rc={code}")
    need(json.loads(json_out.read_text())["mirror_check"]["verdict"] == "PASS", "json is not usable")
    return "verdict printed, failed write reported, --csv/--json recovers"


@check("subfolders (one per capture folder) are scored together")
def t_subdirs(tmp):
    d = tmp / "nested"
    write_clip(d / "mirror", 2.5, -25, 1, n=ARGS.frames, take=1, seed=16)
    write_clip(d / "mirror", 2.5, 25, 1, n=ARGS.frames, take=1, seed=17)
    write_clip(d / "p01", 1.5, 0, 1, n=ARGS.frames, take=1, seed=18)
    code, out, js = run_scorer([d])
    need(js["n_frames"] == 3 * ARGS.frames, f"{js['n_frames']} frames")
    need(len(js["clips"]) == 3, f"{len(js['clips'])} clips")
    need(js["mirror_check"]["verdict"] == "PASS", f"{js['mirror_check']}")
    need((d / "scores.csv").exists(), "scores.csv not written at the top of the tree")
    return "3 clips across 2 subfolders, one scores.csv at the top"


@check("the QAT training checkpoint is refused with advice, not a state_dict dump")
def t_qat_ckpt(tmp):
    # artifacts/ holds successor_qat_ep3.pth (training copy, quantization
    # observers attached) next to successor_qat_ep3_eval.pth. Picking the wrong
    # one of that pair must not produce a 60-key traceback.
    bad = DRONE_ROOT / "pytorch_ssd_unstable/artifacts/successor_qat_ep3.pth"
    if not bad.exists():
        return "skipped: successor_qat_ep3.pth not on this machine"
    d = standard_folder(tmp / "qat", n=2)
    cmd = [sys.executable, str(HERE / "score_real_frames.py"), str(d), "--ckpt", str(bad)]
    pr = subprocess.run(cmd, capture_output=True, text=True)
    blob = pr.stdout + pr.stderr
    need(pr.returncode != 0, "loading the training checkpoint should fail")
    need("Traceback" not in blob, f"still dumps a traceback:\n{blob[:400]}")
    need("W_alpha" not in blob, "still dumps the state_dict keys")
    need("_eval" in blob, "does not point at the eval copy")
    need(len(blob.strip().splitlines()) <= 8, f"{len(blob.strip().splitlines())} lines is too many")
    return f"{len(blob.strip().splitlines())} plain lines, names the _eval copy, no traceback"


@check("a bearing outside the crop is excluded, not voted with")
def t_outside_crop(tmp):
    # b45 is beyond the 70 deg crop edge: the person is NOT in the image the
    # model sees, so those frames must not vote in the mirror verdict.
    d = tmp / "outside"
    write_clip(d, 2.5, -25, 1, n=ARGS.frames, take=1, seed=40)
    write_clip(d, 2.5, 45, 1, n=ARGS.frames, take=2, seed=41)
    code, out, js = run_scorer([d])
    mc = js["mirror_check"]
    need(mc["right_n"] == 0, f"right_n {mc['right_n']}: out-of-crop frames leaked into the check")
    need(mc["outside_crop_n"] == ARGS.frames,
         f"outside_crop_n {mc['outside_crop_n']}, want {ARGS.frames}")
    need("beyond the 70 deg crop edge" in out, "no note about the excluded frames")
    # Once b45 is out, only ONE usable mark is left, so the honest verdict is
    # NO DATA - never a FAIL or MIRRORED driven by frames the model cannot see.
    need(mc["verdict"] == "NO DATA", f"verdict {mc['verdict']} on one usable mark")
    need("only one target position" in out, f"wrong reason: {mirror_line(out)}")
    # With a real second mark present, b45 is still excluded and the verdict stands.
    d2 = tmp / "outside_plus_right"
    write_clip(d2, 2.5, -25, 1, n=ARGS.frames, take=1, seed=40)
    write_clip(d2, 2.5, 25, 1, n=ARGS.frames, take=2, seed=44)
    write_clip(d2, 2.5, 45, 1, n=ARGS.frames, take=3, seed=41)
    _, out2, js2 = run_scorer([d2])
    mc2 = js2["mirror_check"]
    need(mc2["verdict"] == "PASS", f"verdict {mc2['verdict']}, want PASS (b45 must be excluded)")
    need(mc2["right_n"] == ARGS.frames,
         f"right_n {mc2['right_n']}: b45 leaked in or b25 was dropped")
    need(mc2["outside_crop_n"] == ARGS.frames, f"outside_crop_n {mc2['outside_crop_n']}")
    return f"b45 excluded and reported both times; one mark left -> NO DATA, b-25/b25 -> PASS"


@check("a bearing label past +-90 deg cannot vote (tan() wraps round)")
def t_bearing_wrap(tmp):
    # b170 means "170 deg to the RIGHT", i.e. behind the drone. tan(170 deg) is a
    # small NEGATIVE number, so the pinhole maths used to hand back x = -0.25 and
    # a confident expected bin 3 - a LEFT-of-centre target on a frame labelled
    # right. That frame then voted in the mirror check and produced a FAIL.
    need(S.expected_x(170, 70.0) is None, "b170 must have no image position")
    need(S.expected_x(-95, 70.0) is None, "b-95 must have no image position")
    need(S.x_to_bin(S.expected_x(170, 70.0)) is None, "x_to_bin(None) must stay None")
    need(S.expected_x(89, 70.0) is not None, "89 deg is still in front of the camera")
    d = tmp / "wrap"
    write_clip(d, 2.5, -25, 1, n=ARGS.frames, take=1, seed=45)
    write_clip(d, 2.5, 25, 1, n=ARGS.frames, take=2, seed=46)
    write_clip(d, 2.5, 170, 1, n=ARGS.frames, take=3, seed=47)
    code, out, js = run_scorer([d])
    mc = js["mirror_check"]
    need(mc["right_n"] == ARGS.frames,
         f"right_n {mc['right_n']}: the b170 frames voted on the RIGHT side")
    need(mc["outside_crop_n"] == ARGS.frames, f"outside_crop_n {mc['outside_crop_n']}: b170 not excluded")
    need(mc["verdict"] == "PASS", f"verdict {mc['verdict']}: b170 dragged the verdict - {mirror_line(out)}")
    return f"b170/b-95 have no expected bin; {ARGS.frames} b170 frames excluded, verdict stays PASS"


@check("--mirror-min-bearing 0 is refused (a b0 frame is on neither side)")
def t_min_bearing_zero(tmp):
    # At 0 a b0 frame satisfies both "<= -0" and ">= 0", so it is counted on BOTH
    # sides and its centre bin scores wrong on both - dragging a clean folder
    # towards MIRRORED.
    d = tmp / "minbear"
    write_clip(d, 2.5, -25, 1, n=2, take=1, seed=48)
    code, out, js = run_scorer([d, "--mirror-min-bearing", "0"])
    need(isinstance(code, str) and "greater than 0" in code, f"exit was {code!r}")
    return "refused with a one-line reason instead of counting b0 on both sides"


@check("a centre-stuck model is NO DATA, not a bogus 'image looks flipped'")
def t_centre_bias(tmp):
    # ParanoidModel puts every frame in bin 4 and never changes anything else.
    # Both sides then score 0%, which looks like a flip but is a model that is
    # not localising at all. Calling that MIRRORED sends the team to re-check
    # the camera for nothing.
    d = tmp / "centre"
    write_clip(d, 2.5, -25, 1, n=ARGS.frames, take=1, seed=42)
    write_clip(d, 2.5, 25, 1, n=ARGS.frames, take=2, seed=43)
    code, out, js = run_scorer([d], model_cls=ParanoidModel)
    mc = js["mirror_check"]
    need(mc["verdict"] == "NO DATA", f"verdict {mc['verdict']}, want NO DATA")
    need(mc["centre_bin_frac"] == 1.0, f"centre_bin_frac {mc['centre_bin_frac']}, want 1.0")
    need(mc["model_dead"] is True, f"model_dead not set: {mc}")
    need("CENTRE" in out and "NOT a mirror" in out, "the reason is not spelled out")
    need("looks flipped" not in mirror_line(out), "still blames a flipped image")
    # and a genuinely flipped image must STILL be called MIRRORED
    d2 = standard_folder(tmp / "still_mirrored", n=ARGS.frames, flip=True)
    code, out2, js2 = run_scorer([d2])
    need(js2["mirror_check"]["verdict"] == "MIRRORED",
         f"a real flip now reports {js2['mirror_check']['verdict']}")
    return "centre-stuck model -> NO DATA with the reason; a real flip still -> MIRRORED"


# --------------------------------------------------------------------------
# --real: MuJoCo renders + the real checkpoint, end to end
# --------------------------------------------------------------------------
def render_real_dataset(out, n, dists=(1.5, 2.5, 3.5), bearings=(0, -10, 10, -25, 25), flip=False):
    """Render a person with the simulator's own scene/camera at known marks."""
    import mujoco
    spec = mujoco.MjSpec.from_file(str(SIM_SCENE))
    cam = spec.worldbody.add_camera()
    cam.name, cam.fovy = "score_cam", FOVY
    cam.alt.type = mujoco.mjtOrientation.mjORIENTATION_XYAXES
    cam.alt.xyaxes = [0, -1, 0, 0, 0, 1]          # image-right = world -y, image-up = +z
    model = spec.compile()
    data = mujoco.MjData(model)
    renderer = mujoco.Renderer(model, H, W)
    cid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_CAMERA, "score_cam")
    bid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, "person")
    model.cam_pos[cid] = [0.0, 0.0, CAM_H]
    rng = np.random.default_rng(7)
    out.mkdir(parents=True, exist_ok=True)

    def shot(d, b):
        rb = math.radians(b)
        # protocol: NEGATIVE bearing = the drone's LEFT. The camera looks along +x
        # with image-right = -y, so the drone's left is +y.
        model.body_pos[bid] = [d * math.cos(rb), -d * math.sin(rb), 0.85]
        q = np.zeros(4)
        mujoco.mju_axisAngle2Quat(q, np.array([0.0, 0.0, 1.0]), -rb)   # panel faces the camera
        model.body_quat[bid] = q
        mujoco.mj_forward(model, data)
        renderer.update_scene(data, camera="score_cam")
        rgb = renderer.render().copy()
        g = np.dot(rgb[..., :3], [0.2989, 0.5870, 0.1140])
        g = np.clip(g + rng.normal(0, 2.0, g.shape), 0, 255).astype(np.uint8)
        return g[:, ::-1].copy() if flip else g

    take = 0
    for d in dists:
        for b in bearings:
            take += 1
            for i in range(1, n + 1):
                img = shot(d + rng.normal(0, 0.02), b + rng.normal(0, 0.5))
                Image.fromarray(img).save(
                    out / clip_name(d, b, 1, "p01", "room", take, i, T0 + take * 60 + i * 0.1))
    for i in range(1, 3):                                  # empty room: person pushed out of sight
        model.body_pos[bid] = [0.0, 0.0, -20.0]
        for f in range(1, n + 1):
            mujoco.mj_forward(model, data)
            renderer.update_scene(data, camera="score_cam")
            g = np.dot(renderer.render().copy()[..., :3], [0.2989, 0.5870, 0.1140])
            g = np.clip(g + rng.normal(0, 2.0, g.shape), 0, 255).astype(np.uint8)
            Image.fromarray(g[:, ::-1].copy() if flip else g).save(
                out / clip_name(None, None, 0, "empty", "room", i, f, T0 + 5000 + i * 60 + f * 0.1))
    return out


def real_checks(tmp, n):
    """Same folder twice: upright must be PASS, flipped must be MIRRORED."""
    results = []
    ckpt = DRONE_ROOT / "pytorch_ssd_unstable/artifacts/successor_qat_ep3_eval.pth"
    if not ckpt.exists():
        return [("real model: checkpoint present", False, f"missing {ckpt}")]
    results.append(("real model: checkpoint present", True, f"{ckpt} ({ckpt.stat().st_size} bytes)"))
    for flip, want in ((False, "PASS"), (True, "MIRRORED")):
        name = f"real MuJoCo render + real checkpoint -> {want}"
        try:
            d = render_real_dataset(tmp / ("real_flip" if flip else "real"), n, flip=flip)
            code, out, js = run_scorer([d], model_cls=S.Model)
            got = js["mirror_check"]["verdict"]
            ok = got == want
            detail = mirror_line(out)[:150]
            if not flip:
                ok = ok and js["empty_false_tracks"] == 0 and "Bayer" not in out
                detail += (f" | bin acc {js['overall']['bin_acc']:.0%} "
                           f"(+-1 {js['overall']['bin_acc1']:.0%}), "
                           f"bearing err {js['overall']['bear_err']:+.1f} deg, "
                           f"false tracks {js['empty_false_tracks']}, n={js['n_frames']}, "
                           f"bayer {js['bayer_phase_spread_dn']:.2f} DN")
            results.append((name, ok, detail))
            if not flip:                      # the command the protocol tells you to type
                cmd = [sys.executable, str(HERE / "score_real_frames.py"), str(d)]
                pr = subprocess.run(cmd, capture_output=True, text=True)
                line = [l for l in pr.stdout.splitlines() if l.startswith("MIRROR CHECK")]
                results.append(("protocol command line runs and prints a verdict",
                                pr.returncode == 0 and bool(line) and "-> PASS" in line[0],
                                f"rc={pr.returncode} | {(line or ['<none>'])[0][:110]}"))
        except Exception:
            results.append((name, False, traceback.format_exc().splitlines()[-1]))
    return results


# --------------------------------------------------------------------------
def main():
    global ARGS
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--real", action="store_true",
                    help="also render with MuJoCo and score with the real checkpoint (slow)")
    ap.add_argument("--frames", type=int, default=6, help="frames per synthetic clip")
    ap.add_argument("--real-frames", type=int, default=6, help="frames per rendered clip (--real)")
    ap.add_argument("--keep", action="store_true", help="keep the generated folders")
    ap.add_argument("--only", default=None, help="substring: run only matching checks")
    ARGS = ap.parse_args()

    tmp = Path(tempfile.mkdtemp(prefix="score_rehearsal_"))
    results = []
    try:
        for name, fn in CHECKS:
            if ARGS.only and ARGS.only.lower() not in name.lower():
                continue
            try:
                results.append((name, True, fn(tmp)))
            except Exception as e:
                tb = traceback.format_exc()
                detail = f"{type(e).__name__}: {e}" if isinstance(e, AssertionError) else \
                    tb.strip().splitlines()[-1]
                results.append((name, False, detail))
                if not isinstance(e, AssertionError):
                    print(tb)
        if ARGS.real:
            results += real_checks(tmp, ARGS.real_frames)
    finally:
        if ARGS.keep:
            print(f"\ngenerated folders kept in {tmp}")
        else:
            shutil.rmtree(tmp, ignore_errors=True)

    print()
    bad = 0
    for name, ok, detail in results:
        bad += not ok
        print(f"[{'PASS' if ok else 'FAIL'}] {name}\n        {detail}")
    print(f"\n{len(results) - bad}/{len(results)} checks passed"
          + ("" if ARGS.real else "   (add --real for the MuJoCo + real-checkpoint run)"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
