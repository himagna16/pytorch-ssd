#!/usr/bin/env python3
"""Label a session recorded by record_session.py: where the subject truly was in every
frame, next to what the network said.

    ~/Downloads/drone/trainenv/bin/python tools/lighthouse/label_session.py <session folder>

Steps (README "Recording a session"; each one reuses the tested piece, none is re-derived):
  1. each drone's Crazyflie clock -> this laptop's clock, from the lower envelope of
     (receive time - Crazyflie time): offset and drift measured, per drone;
  2. the network on every frame: score_real_frames.py's chip arm (firmware preprocess +
     model_id_dory.onnx), cached in network.csv;
  3. align_clocks.align on the start and end sidesteps: frame clock -> pose clock, using
     the network's x for the frames and pose_to_label's image x for the poses;
  4. pose_to_label for every frame, at the pose of the same physical instant;
  5. drops: no pose across a gap, stalled pose stamps, the follower's first pose
     discontinuity, Lighthouse status != working, beacon position jumps;
  6. check_not_mirrored, then labels.csv and a plain-English report.md.

THE LABEL TARGET IS AN OPEN TEAM DECISION. The default is the README's current one:
feet + 0.5 x height, i.e. head - 1/2 subject height (--target-frac 0.5). It does not
move the x-bin for a level camera; it moves size and the in-view flag. Every report says so.

THE CAMERA FOV IS NOT MEASURED on the real AI-deck. The default crop FOV (70 deg) is the
simulator's; pass --crop-hfov / --full-hfov once it is measured.

Exit codes: 0 labels written and the left/right check passed; 1 labels written but the
left/right check did NOT pass (do not use them); 2 bad input; 3 the clocks could not be
aligned (no labels; see report.md).
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO / "tools" / "real_frames"))
import align_clocks as A  # noqa: E402
import pose_to_label as P  # noqa: E402
import session_common as S  # noqa: E402

VIS_THRESHOLD = 0.5          # "the network sees a person" (score_real_frames' vis acc threshold)
ALIGN_MIN_CONF = 0.3         # frames used for the CLOCK alignment only: a weak detection still says where
                             # the subject is (found in the --mock rehearsal: the step position sat at 0.49)
BEACON_JUMP_MPS = 4.0        # faster than a person moves: a Lighthouse re-acquisition jump
BEACON_JUMP_GUARD_S = 0.25
ENVELOPE_WINDOW_S = 2.0
DIST_BINS = [0.0, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 5.0, 99.0]


# --------------------------------------------------------------------------
# clocks
# --------------------------------------------------------------------------
def fit_cf_clock(t_cf_ms, t_laptop, window_s=ENVELOPE_WINDOW_S):
    """Map one drone's Crazyflie clock to the laptop clock.

    delay = t_laptop - t_cf is (clock offset) + (radio latency >= 0). The least-delayed
    packet in each `window_s` window sits closest to the pure offset, so a straight line
    through those minima gives offset + drift, and what remains above it is latency
    jitter. Returns dict(c0, c1, x0, drift_ppm, jitter_ms_p50/p95, n_windows)."""
    x = np.asarray(t_cf_ms, float) / 1000.0
    tl = np.asarray(t_laptop, float)
    ok = np.isfinite(x) & np.isfinite(tl)
    x, tl = x[ok], tl[ok]
    if len(x) < 3:
        raise ValueError("fewer than 3 pose samples: nothing to map")
    d = tl - x
    x0 = float(x[0])
    edges = np.arange(x0, x[-1] + window_s, window_s)
    k = np.clip(np.searchsorted(edges, x, side="right") - 1, 0, None)
    xs, ds = [], []
    for w in np.unique(k):
        sel = np.nonzero(k == w)[0]
        j = sel[np.argmin(d[sel])]
        xs.append(x[j] - x0)
        ds.append(d[j])
    xs, ds = np.array(xs), np.array(ds)
    if len(xs) >= 3 and np.ptp(xs) > 0:
        c1, c0 = np.polyfit(xs, ds, 1)
        for _ in range(2):           # drop windows whose minimum was itself a late packet
            res = ds - (c0 + c1 * xs)
            keep = res <= np.median(res) + 3 * max(1e-4, 1.4826 * np.median(np.abs(res - np.median(res))))
            if keep.sum() >= 3:
                c1, c0 = np.polyfit(xs[keep], ds[keep], 1)
    else:
        c1, c0 = 0.0, float(ds.min())
    above = d - (c0 + c1 * (x - x0))
    return dict(c0=float(c0), c1=float(c1), x0=x0, drift_ppm=float(c1 * 1e6), n_windows=int(len(xs)),
                jitter_ms_p50=float(np.percentile(above, 50) * 1000), jitter_ms_p95=float(np.percentile(above, 95) * 1000))


def cf_to_laptop(fit, t_cf_ms):
    x = np.asarray(t_cf_ms, float) / 1000.0
    return x + fit["c0"] + fit["c1"] * (x - fit["x0"])


# --------------------------------------------------------------------------
# loading
# --------------------------------------------------------------------------
def load_session(folder):
    folder = Path(folder)
    meta = json.loads((folder / S.META_JSON).read_text())
    poses = {}
    for role, name in S.POSES_CSV.items():
        p = folder / name
        if p.exists():
            poses[role] = {k: np.asarray(v, float) for k, v in S.read_pose_csv(p).items()}
    frames = S.list_frames(folder / S.FRAMES_DIR)
    return meta, poses, frames


def unwrap_deg(a):
    return np.degrees(np.unwrap(np.radians(np.asarray(a, float))))


def at_or_before(t_query, t_samples, values):
    """values[i] of the latest sample with t_samples[i] <= t_query (NaN before the first)."""
    t_samples = np.asarray(t_samples, float)
    i = np.searchsorted(t_samples, np.asarray(t_query, float), side="right") - 1
    out = np.full(len(i), np.nan)
    ok = i >= 0
    out[ok] = np.asarray(values, float)[i[ok]]
    return out


# --------------------------------------------------------------------------
# the network
# --------------------------------------------------------------------------
NET_COLS = ["frame", "conf", "x_bin", "x_soft", "size_bucket"]


def run_network(folder, frames, backend="chip", log=print):
    """Network outputs per frame, cached in <folder>/network_<backend>.csv."""
    cache = Path(folder) / f"network_{backend}.csv"
    if cache.exists():
        rows = {r["frame"]: r for r in csv.DictReader(open(cache))}
        if all(n in rows for _, _, n in frames):
            log(f"   network outputs from {cache.name} (cached)")
            return {n: {k: float(rows[n][k]) for k in NET_COLS[1:]} for _, _, n in frames}
    import score_real_frames as SRF
    from PIL import Image
    ns = argparse.Namespace(backend=backend, chip_onnx=SRF.PB.DEFAULT_ONNX, chip_python=SRF.PB.DEFAULT_DORY_PYTHON,
                       ckpt=SRF.DEFAULT_CKPT, unstable_root=SRF.DEFAULT_UNSTABLE)
    model = SRF.load_model(ns)
    out = {}
    try:
        names = [n for _, _, n in frames]
        for i in range(0, len(names), 64):
            chunk = names[i:i + 64]
            batch = np.stack([model.preprocess(np.asarray(Image.open(Path(folder) / S.FRAMES_DIR / n).convert("L")))
                              for n in chunk])
            for n, p in zip(chunk, model(batch)):
                out[n] = dict(conf=float(p["visibility_confidence"]), x_bin=float(p["x_bin_index"]),
                              x_soft=float(p["x_soft"]), size_bucket=float(p["size_bucket_index"]))
    finally:
        model.close()
    with open(cache, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(NET_COLS)
        for n in names:
            w.writerow([n] + [out[n][k] for k in NET_COLS[1:]])
    log(f"   network ({backend}) on {len(out)} frames -> {cache.name}")
    return out


# --------------------------------------------------------------------------
# labelling
# --------------------------------------------------------------------------
def pose_signal(pt, cols, subject, cam):
    """pose_to_label's image x for every pose sample: what the frames should show."""
    out = np.full(len(pt), np.nan)
    for i in range(len(pt)):
        f = P.Pose(cols["fx"][i], cols["fy"][i], cols["fz"][i], cols["fyaw"][i], cols["froll"][i], cols["fpitch"][i])
        if not all(np.isfinite([f.x, f.y, f.z, f.yaw_deg, cols["bx"][i], cols["by"][i], cols["bz"][i]])):
            continue
        lab = P.pose_to_label(f, (cols["bx"][i], cols["by"][i], cols["bz"][i]), subject, cam)
        if lab.x_norm is not None:
            out[i] = lab.x_norm
    return out


def common_timeline(poses, clock):
    """Beacon sample times (laptop clock) and every column on them; follower interpolated."""
    b, f = poses["beacon"], poses["follower"]
    tb = cf_to_laptop(clock["beacon"], b["t_cf_ms"])
    tf = cf_to_laptop(clock["follower"], f["t_cf_ms"])
    ob, of = np.argsort(tb), np.argsort(tf)
    tb, tf = tb[ob], tf[of]
    cols = dict(bx=b["x"][ob], by=b["y"][ob], bz=b["z"][ob])
    for c, src in (("fx", "x"), ("fy", "y"), ("fz", "z"), ("froll", "roll"), ("fpitch", "pitch")):
        cols[c] = np.interp(tb, tf, f[src][of], left=np.nan, right=np.nan)
    cols["fyaw"] = (np.interp(tb, tf, unwrap_deg(f["yaw"][of]), left=np.nan, right=np.nan) + 180.0) % 360.0 - 180.0
    return tb, cols, tf, of


def drop_reasons(frame_tp, poses, clock, tb, tf, of, sampled, period_s):
    """Per frame, '' if usable, else why not. frame_tp = each frame's instant on the pose clock."""
    n = len(frame_tp)
    why = [""] * n

    def mark(mask, reason):
        for i in np.nonzero(mask)[0]:
            if not why[i]:
                why[i] = reason

    mark(~np.all(np.isfinite(np.vstack(sampled)), axis=0), "no_pose")
    # stalled: the pose's OWN stamp (Crazyflie seconds) stopped advancing
    for role, ts in (("beacon", tb), ("follower", tf)):
        src = poses[role]
        order = np.argsort(cf_to_laptop(clock[role], src["t_cf_ms"]))
        stamp = at_or_before(frame_tp, ts, src["t_cf_ms"][order] / 1000.0)
        stamp = np.where(np.isfinite(stamp), stamp, -1.0)
        mark(np.array(P.stalled_pose_mask(frame_tp, stamp, max(P.MAX_POSE_STALL_S, 5 * period_s))), f"{role}_pose_stalled")
    f = poses["follower"]
    k = P.first_pose_discontinuity(list(tf), list(f["yaw"][of]), list(f["roll"][of]), list(f["pitch"][of]))
    if k is not None:
        mark(frame_tp >= tf[k], "after_follower_discontinuity")
    for role, ts in (("follower", tf), ("beacon", tb)):
        src = poses[role]
        order = of if role == "follower" else np.argsort(cf_to_laptop(clock[role], src["t_cf_ms"]))
        col = S.status_col("lighthouse.status")
        if col in src and np.isfinite(src[col]).any():
            st = at_or_before(frame_tp, ts, src[col][order])
            mark(np.isfinite(st) & (st != S.LH_STATUS_WORKING), f"{role}_lighthouse_not_working")
    b = poses["beacon"]
    ob = np.argsort(cf_to_laptop(clock["beacon"], b["t_cf_ms"]))
    if len(tb) > 1:
        v = np.hypot(np.diff(b["x"][ob]), np.diff(b["y"][ob])) / np.maximum(np.diff(tb), 1e-3)
        jumps = tb[1:][v > BEACON_JUMP_MPS]
        if len(jumps):
            near = np.min(np.abs(frame_tp[:, None] - jumps[None, :]), axis=1) <= BEACON_JUMP_GUARD_S
            mark(near, "beacon_jump")
    return why


def dist_bin(d):
    for lo, hi in zip(DIST_BINS, DIST_BINS[1:]):
        if lo <= d < hi:
            return f"{lo:g}-{hi:g} m" if hi < 50 else f">= {lo:g} m"
    return "?"


def pct(a, b):
    return f"{100.0 * a / b:.0f}%" if b else "-"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("session", type=Path, help="folder written by record_session.py")
    ap.add_argument("--backend", choices=("chip", "float"), default="chip", help="default chip (what the drone runs)")
    ap.add_argument("--target-frac", type=float, default=0.5,
                    help="label target height above the feet as a fraction of height. 0.5 = head - 1/2 height "
                         "(README default; OPEN team decision)")
    ap.add_argument("--height", type=float, default=None, help="subject height, m (default: from meta.json)")
    ap.add_argument("--beacon-above-head", type=float, default=None, help="default: from meta.json")
    ap.add_argument("--mount", nargs=3, type=float, default=None, metavar=("MX", "MY", "MZ"),
                    help="lens in the follower body frame (default: from meta.json)")
    fov = ap.add_mutually_exclusive_group()
    fov.add_argument("--crop-hfov", type=float, default=None, help="the network crop's FOV (default 70, the simulator's)")
    fov.add_argument("--full-hfov", type=float, default=None, help="the full frame's measured horizontal FOV")
    ap.add_argument("--offset-s", type=float, default=None,
                    help="skip the sync-step alignment and use this frame->pose clock offset (s). Only for "
                         "sessions where nobody moved (alignment is impossible there and the offset harmless)")
    ap.add_argument("--context-s", type=float, default=20.0, help="align_clocks context around each sync event")
    ap.add_argument("--align-min-conf", type=float, default=ALIGN_MIN_CONF,
                    help="frames at or above this confidence feed the clock alignment (labels still use 0.5)")
    a = ap.parse_args(argv)

    folder = a.session.expanduser()
    if not (folder / S.META_JSON).exists():
        print(f"not a session folder (no meta.json): {folder}")
        return 2
    meta, poses, frames = load_session(folder)
    if "beacon" not in poses or "follower" not in poses:
        print("this session has no beacon log (a --static run?): nothing to label")
        return 2
    if len(frames) < 10:
        print(f"only {len(frames)} frames in {folder / S.FRAMES_DIR}: nothing to label")
        return 2
    height = a.height if a.height is not None else meta.get("height_m")
    if height is None:
        print("no subject height: pass --height (it was not given to record_session.py)")
        return 2
    above = a.beacon_above_head if a.beacon_above_head is not None else meta.get("beacon_above_head_m", 0.0)
    mount = tuple(a.mount) if a.mount else tuple(meta.get("mount_xyz_body", (0.03, 0.0, 0.0)))
    if a.full_hfov is not None:
        cam = P.CameraSpec.from_full_hfov(a.full_hfov, mount_xyz_body=mount)
    else:
        h = a.crop_hfov or 70.0
        cam = P.CameraSpec(crop_hfov_deg=h, crop_vfov_deg=h, mount_xyz_body=mount)
    subject = P.SubjectSpec(height_m=height, beacon_above_head_m=above, target_frac=a.target_frac)
    period_s = (meta.get("log") or {}).get("pose_period_ms", 10) / 1000.0
    rep = {"session": str(folder), "frames": len(frames)}
    lines = []
    say = lambda s="": lines.append(s)   # noqa: E731

    print(f"== labelling {folder}")
    # 1. Crazyflie clocks -> laptop
    clock = {r: fit_cf_clock(poses[r]["t_cf_ms"], poses[r]["t_laptop"]) for r in ("follower", "beacon")}
    rep["cf_clock"] = clock
    tb, cols, tf, of = common_timeline(poses, clock)
    # 2. the network
    net = run_network(folder, frames, a.backend)
    ft = np.array([t for t, _, _ in frames])
    names = [n for _, _, n in frames]
    conf = np.array([net[n]["conf"] for n in names])
    fx = np.array([net[n]["x_soft"] if net[n]["conf"] >= a.align_min_conf else np.nan for n in names])
    frame_period = float(np.median(np.diff(ft))) if len(ft) > 1 else 0.1
    # The coarse onsets of the two streams can disagree by up to about one frame period (the step
    # falls between two frames); at the deck's ~2 fps that is more than align's default +-0.5 s search.
    search_s = max(0.5, 3.0 * frame_period)
    # 3. align
    px = pose_signal(tb, cols, subject, cam)
    fit, align_err = None, None
    if a.offset_s is not None:
        fit = A.ClockFit(1.0, float(a.offset_s), [], drift_measured=False)
    else:
        try:
            fit = A.align(ft, fx, tb, px, context_s=a.context_s, search_s=search_s)
        except ValueError as e:
            align_err = str(e)
    rep["alignment"] = (dict(error=align_err) if fit is None else
                        dict(a=fit.a, b=fit.b, drift_measured=fit.drift_measured, manual=a.offset_s is not None,
                             offset_at_events_s=[e.offset_s for e in fit.events],
                             event_t_frame=[e.t_frame for e in fit.events],
                             event_corr=[e.peak_corr for e in fit.events], summary=fit.summary(),
                             offset_mid_s=fit.offset_at(float(np.median(ft)))))

    header(say, meta, folder, subject, cam, a)
    clocks_section(say, clock, meta)
    if fit is None:
        say("## Frame clock -> pose clock: FAILED")
        say()
        say(f"align_clocks refused: {align_err}")
        say()
        say("No labels were written. A sidestep must be visible in BOTH streams: the subject stands still "
            ">= 2 s, steps once, stands still again, at the start AND the end, inside the network's view. "
            "If nobody moved on purpose (a static session), re-run with --offset-s 0 and read the caveat.")
        write_report(folder, lines, rep)
        print(f"!! clock alignment failed: {align_err}\n   report: {folder / 'report.md'}")
        return 3
    say("## Frame clock -> pose clock")
    say()
    if a.offset_s is not None:
        say(f"MANUAL offset {a.offset_s:+.3f} s (--offset-s). Not measured. Labels of a MOVING subject are off "
            f"by atan(speed x error / distance).")
    else:
        for e in fit.events:
            say(f"* sync event at frame time {e.t_frame:.2f}: offset {e.offset_s * 1000:+.1f} ms "
                f"(correlation {e.peak_corr:.3f}, {e.n_frames} frames)")
        say(f"* {'drift ' + format(fit.drift_ppm, '+.0f') + ' ppm' if fit.drift_measured else 'drift NOT measured (events < 60 s apart): offset only'}")
        if len(fit.events) == 2 and not fit.drift_measured:
            spread = abs(fit.events[1].offset_s - fit.events[0].offset_s) * 1000
            say(f"* the start and end events agree to {spread:.0f} ms; the offset used is their mean, so its "
                f"error is probably under ~{max(spread / 2, 5):.0f} ms (rehearsal at 2 fps: 30 ms apart, 3.5 ms off the truth)")
        elif len(fit.events) == 1:
            say("* only ONE sync event was found: no cross-check of the offset. Re-record with both sync blocks.")
        off = abs(fit.offset_at(float(np.median(ft))))
        say(f"* a frame reaches the laptop {off * 1000:.0f} ms after the instant it shows (camera + WiFi latency). "
            f"Uncorrected, that would be {A.bearing_error_deg(off, 1.0, 2.0):.1f} deg of label error for a subject "
            f"crossing at 1 m/s at 2 m.")
    say()

    # 4. poses at frames, labels
    tq = A.to_pose_time(fit, ft)
    sampled = A.sample_poses_at_frames(fit, ft, tb, [cols[k] for k in ("bx", "by", "bz", "fx", "fy", "fz", "fyaw", "froll", "fpitch")],
                                       max_gap_s=max(0.1, 3 * period_s))
    bx, by, bz, ffx, ffy, ffz, fyaw, froll, fpitch = sampled
    why = drop_reasons(tq, poses, clock, tb, tf, of, sampled, period_s)
    rows = []
    for i, n in enumerate(names):
        r = dict(frame=n, frame_no=frames[i][1], t=f"{ft[i]:.3f}", t_pose=f"{tq[i]:.3f}", drop_reason=why[i],
                 net_conf=round(conf[i], 4), net_x_bin=int(net[n]["x_bin"]), net_x_soft=round(net[n]["x_soft"], 4),
                 net_size_bucket=int(net[n]["size_bucket"]), net_vis=int(conf[i] >= VIS_THRESHOLD))
        lab = None
        if not why[i]:
            lab = P.pose_to_label(P.Pose(ffx[i], ffy[i], ffz[i], fyaw[i], froll[i], fpitch[i]), (bx[i], by[i], bz[i]),
                                  subject, cam)
        r.update(bearing_deg=_r(lab and lab.bearing_deg, 3), depth_m=_r(lab and lab.depth_m, 3),
                 range_m=_r(lab and lab.range_m, 3), x_norm=_r(lab and lab.x_norm, 4),
                 x_bin="" if lab is None or lab.x_bin is None else lab.x_bin,
                 size_frac=_r(lab and lab.size_frac, 4),
                 size_bucket="" if lab is None or lab.size_bucket is None else lab.size_bucket,
                 in_fov="" if lab is None else int(lab.in_fov), why_not_in_view="" if lab is None else lab.why_not,
                 follower_x=_r(ffx[i], 4), follower_y=_r(ffy[i], 4), follower_z=_r(ffz[i], 4), follower_yaw=_r(fyaw[i], 2),
                 beacon_x=_r(bx[i], 4), beacon_y=_r(by[i], 4), beacon_z=_r(bz[i], 4))
        rows.append((r, lab))
    with open(folder / "labels.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0][0].keys()))
        w.writeheader()
        for r, _ in rows:
            w.writerow(r)

    # 5. summary
    usable = [(r, l) for r, l in rows if l is not None]
    inview = [(r, l) for r, l in usable if l.in_fov]
    seen = [(r, l) for r, l in inview if r["net_vis"]]
    drops = {}
    for r, _ in rows:
        if r["drop_reason"]:
            drops[r["drop_reason"]] = drops.get(r["drop_reason"], 0) + 1
    say("## Frames")
    say()
    say(f"* {len(rows)} frames; **{len(usable)} labelled**, {len(rows) - len(usable)} dropped"
        + (": " + ", ".join(f"{k} {v}" for k, v in sorted(drops.items(), key=lambda kv: -kv[1])) if drops else ""))
    say(f"* {len(inview)} with the subject inside the network's crop ({len(usable) - len(inview)} outside it: "
        "a miss there is not a network error)")
    say(f"* the network sees a person (confidence >= {VIS_THRESHOLD}) on **{len(seen)} of {len(inview)}** "
        f"in-view frames ({pct(len(seen), len(inview))}); the other {len(inview) - len(seen)} are labelled misses")
    say()
    say("## Left / right")
    say()
    mirror_ok = False
    try:
        sa = P.check_not_mirrored([l.bearing_deg for _, l in seen], [r["net_x_bin"] for r, _ in seen])
        mirror_ok = True
        say(f"**PASS.** Clearly-left frames: {sa['left'][0]} at {sa['left'][1]:.0%} agreement; clearly-right: "
            f"{sa['right'][0]} at {sa['right'][1]:.0%}.")
    except P.MirroredLabelsError as e:
        sa = P.side_agreement([l.bearing_deg for _, l in seen], [r["net_x_bin"] for r, _ in seen])
        say(f"**DID NOT PASS - do not use these labels.** {e}")
    rep["side_agreement"] = sa
    rep["mirror_check_passed"] = mirror_ok
    say()
    say("## x-bin and size, on frames where the network sees the person")
    say()
    if seen:
        ex = sum(int(r["net_x_bin"]) == l.x_bin for r, l in seen)
        pm = sum(abs(int(r["net_x_bin"]) - l.x_bin) <= 1 for r, l in seen)
        sz = sum(int(r["net_size_bucket"]) == l.size_bucket for r, l in seen)
        err = [math.degrees(math.atan(r["net_x_soft"] * math.tan(math.radians(cam.crop_hfov_deg) / 2))) - l.bearing_deg
               for r, l in seen]
        say(f"* x-bin exact **{pct(ex, len(seen))}**, within one bin {pct(pm, len(seen))} ({len(seen)} frames)")
        say(f"* bearing from the network's soft x minus the label: mean {np.mean(err):+.1f} deg, "
            f"median |.| {np.median(np.abs(err)):.1f} deg")
        say(f"* size bucket agrees on {pct(sz, len(seen))} (depends on the OPEN label-target choice and the "
            "unmeasured FOV)")
        rep.update(xbin_exact=ex / len(seen), xbin_pm1=pm / len(seen), size_agree=sz / len(seen),
                   bearing_err_mean_deg=float(np.mean(err)))
    else:
        say("* the network saw nobody on any in-view frame")
    say()
    say("## By distance (depth along the camera axis)")
    say()
    say("| distance | in view | seen | median confidence | x-bin exact (seen) |")
    say("|---|---|---|---|---|")
    groups = {}
    for r, l in inview:
        groups.setdefault(dist_bin(l.depth_m), []).append((r, l))
    for k in sorted(groups, key=lambda s: float(s.split("-")[0].replace(">= ", "").split(" ")[0])):
        g = groups[k]
        gs = [(r, l) for r, l in g if r["net_vis"]]
        say(f"| {k} | {len(g)} | {pct(len(gs), len(g))} | {np.median([r['net_conf'] for r, _ in g]):.2f} | "
            f"{pct(sum(int(r['net_x_bin']) == l.x_bin for r, l in gs), len(gs))} |")
    say()
    rep.update(labelled=len(usable), dropped=drops, in_view=len(inview), seen=len(seen))
    write_report(folder, lines, rep)
    print("\n".join(lines))
    print(f"\n   labels: {folder / 'labels.csv'}\n   report: {folder / 'report.md'}")
    return 0 if mirror_ok else 1


def _r(v, nd):
    if v is None:
        return ""
    v = float(v)
    return "" if not math.isfinite(v) else round(v, nd)


def header(say, meta, folder, subject, cam, a):
    say(f"# Lighthouse session labels: {folder.name}")
    say()
    if meta.get("mock"):
        say("> **REHEARSAL (--mock): no hardware.** SITL and/or scripted drones and simulator frames. "
            "Nothing here is evidence about the real drones, radio or WiFi.")
        say()
    say(f"> **Label target = feet + {subject.target_frac:g} x height** (= head - {1 - subject.target_frac:g} x "
        f"subject height{', the README default' if subject.target_frac == 0.5 else ''}). This is still an "
        "**OPEN team decision** (README, 'Where the label points'); it changes size and the in-view flag, "
        "not the x-bin of a level camera.")
    say()
    say(f"Subject {meta.get('subject')}, {subject.height_m:g} m tall, beacon {subject.beacon_above_head_m:g} m above "
        f"the head. Camera crop FOV {cam.crop_hfov_deg:.1f} deg "
        f"({'measured, passed in' if (a.crop_hfov or a.full_hfov) else 'the SIMULATOR value: the real camera is NOT measured'}), "
        f"lens at {tuple(cam.mount_xyz_body)} m in the body frame.")
    lg = meta.get("log") or {}
    ach = lg.get("achieved") or {}
    if ach:
        say("Pose logging: " + "; ".join(f"{r} {st.get('achieved_hz') or 0:.1f} Hz of {st.get('requested_hz')} requested, "
                                         f"{st.get('missing')} samples missing" for r, st in ach.items())
            + f". Frames: {(meta.get('frames') or {}).get('n')} at {(meta.get('frames') or {}).get('fps')} fps.")
    say()


def clocks_section(say, clock, meta):
    say("## Crazyflie clocks -> laptop clock")
    say()
    for r, c in clock.items():
        say(f"* {r}: laptop = cf + {c['c0']:.3f} s, drift {c['drift_ppm']:+.0f} ppm; packets arrive "
            f"{c['jitter_ms_p50']:.1f} ms (median) / {c['jitter_ms_p95']:.1f} ms (95th pct) after the fastest one")
    if meta.get("mock"):
        say("* (SITL clocks run at simulation speed, so a large SITL drift is expected and is not a clock fault.)")
    say()


def write_report(folder, lines, rep):
    (folder / "report.md").write_text("\n".join(lines) + "\n")
    (folder / "label_summary.json").write_text(json.dumps(rep, indent=1, default=float))


if __name__ == "__main__":
    sys.exit(main())
