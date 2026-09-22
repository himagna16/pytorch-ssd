#!/usr/bin/env python3
"""Validate tools/lighthouse/pose_to_label.py against logged CrazySim flights.

For every archived flight that has a follower control log (follow_log.csv) and a
simulator truth log (truth.csv) for a person target, and for every frame the
follower processed:

  follower pose = the firmware's own state estimate as logged (px, py, pz, roll,
                  pitch, yaw) - the slot a Lighthouse-fed estimate fills on hardware
  beacon        = the subject's TRUE position from truth.csv, lifted to the top of
                  the head (panel centre + height/2), i.e. where a head beacon sits
  join          = truth interpolated at the frame's ARRIVAL wall time
                  (row wall - processing time - frame_age); both files carry the
                  wall clock. Two other joins are scored for comparison, including
                  the one that burned the Sep 13 analysis (follower t vs truth sim_t).

and compares the pose-derived label with (i) scoreboard.py's own truth bearing and
(ii) what the network actually output on that frame. It then runs the mirror
guard with the correct convention and three deliberately wrong ones.

No simulator is started. Reads only files already in docs/.

    ~/Downloads/drone/trainenv/bin/python \
        docs/eval_results/2026-09-22-pose-to-label-sim-validation/scripts/validate_on_sim.py
"""
import collections, csv, glob, json, math, os, sys
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
OUT = HERE.parent
REPO = OUT.parents[2]
sys.path.insert(0, str(REPO / "tools" / "lighthouse"))
sys.path.insert(0, str(REPO / "tools" / "crazysim_macos"))
import pose_to_label as P            # noqa: E402
import scoreboard as SB              # noqa: E402  (load_truth, fnum only)

SCENES_V2 = [REPO / "tools" / "crazysim_macos" / "scenes_v2",
             Path.home() / "Downloads" / "drone" / "pytorch_ssd" / "tools" / "crazysim_macos" / "scenes_v2"]
VIS_CONF = 0.5          # frames the network calls visible (p >= 0.5) are the ones whose x-bin means anything
PRIMARY = ("s01_control_moving", "s15_static_offset", "s07_occlusion_reappear")
EMPTY = "s02_control_empty"
DEFAULT_H = 1.7


def manifest_for(scene):
    for root in SCENES_V2:
        p = root / scene / "manifest.json"
        if p.exists():
            return json.loads(p.read_text())
    return None


def target_of(manifest, truth_bodies):
    """(body name, panel height m, height source)."""
    if manifest:
        sub = SB.target_subject(manifest)
        if sub is None:            # empty-room control: its person stands behind the drone
            sub = next((s for s in manifest.get("subjects", []) if s.get("role", "").startswith("person")), None)
        if sub is not None:
            body = (sub.get("truth") or {}).get("body", sub["name"])
            return body, float(sub.get("panel", {}).get("height_m", DEFAULT_H)), "manifest"
    if len(truth_bodies) == 1 and next(iter(truth_bodies)).startswith("subj_person"):   # never a pet or a chair
        return next(iter(truth_bodies)), DEFAULT_H, "assumed"
    return None, None, None


def load_truth_xyz(path):
    """wall[], sim[], {body: (x[], y[], z[] or None)} - scoreboard.load_truth drops z."""
    names, rows = None, []
    for line in Path(path).read_text().splitlines():
        if line.startswith("#"):
            if "bodies:" in line:
                names = [s.strip() for s in line.split("bodies:", 1)[1].split(",") if s.strip()]
            continue
        parts = line.strip().split(",")
        try:
            rows.append([float(v) for v in parts])
        except ValueError:
            continue
    if not rows:
        return None
    ncol = max(len(r) for r in rows)
    arr = np.asarray([r for r in rows if len(r) == ncol], float)
    if names and ncol >= 2 + 3 * len(names):
        bodies = {n: (arr[:, 2 + 3 * i], arr[:, 3 + 3 * i], arr[:, 4 + 3 * i]) for i, n in enumerate(names)}
    else:
        bodies = {"person": (arr[:, 2], arr[:, 3], None)}
    return arr[:, 0], arr[:, 1], bodies


REFLECTIVE_FOLDERS = ("mirror_control_suite", "/mirror_suite/", "sim_results/2026-09-11-simv2")


def floor_of(run):
    """The mirror-floor bug (reflectance 0.2, fixed 2026-09-12) drew subjects 1.5-2x too tall.
    Which archived flights had it is inferred from the evidence folder they sit in."""
    return "reflective (pre-fix)" if any(k in run for k in REFLECTIVE_FOLDERS) else "matte"


def runs():
    seen = set()
    for f in sorted(glob.glob(str(REPO / "docs" / "**" / "cell.json"), recursive=True)):
        d = Path(f).parent
        if not (d / "follow_log.csv").exists() or not (d / "truth.csv").exists():
            continue
        key = (d / "follow_log.csv").stat().st_size, (d / "truth.csv").read_text()[:200]
        if key in seen:             # the same flight copied into two evidence folders
            continue
        seen.add(key)
        yield d


def label_variant(variant, pose, beacon, subj, cam):
    """The correct convention and three wrong ones, for the mirror guard."""
    if variant == "correct":
        return P.pose_to_label(pose, beacon, subj, cam)
    if variant == "yaw_negated":       # someone reads yaw as clockwise-positive
        return P.pose_to_label(P.Pose(pose.x, pose.y, pose.z, -pose.yaw_deg, pose.roll_deg, pose.pitch_deg),
                               beacon, subj, cam)
    if variant == "y_axis_flipped":    # positions from a y-right (left-handed) frame, yaw still CCW
        return P.pose_to_label(P.Pose(pose.x, -pose.y, pose.z, pose.yaw_deg, pose.roll_deg, pose.pitch_deg),
                               (beacon[0], -beacon[1], beacon[2]), subj, cam)
    if variant == "bearing_sign_flipped":   # left-positive bearing fed into a right-positive x
        lab = P.pose_to_label(pose, beacon, subj, cam)
        if lab.x_norm is not None:
            lab.x_norm = -lab.x_norm
            lab.x_bin = P.x_to_bin(lab.x_norm)
        lab.bearing_deg = -lab.bearing_deg
        return lab
    raise ValueError(variant)


VARIANTS = ("correct", "yaw_negated", "y_axis_flipped", "bearing_sign_flipped")


def analyse_run(d):
    cell = json.loads((d / "cell.json").read_text())
    scene = cell.get("scene", "")
    with open(d / "follow_log.csv") as f:
        rows = [r for r in csv.DictReader(f) if r.get("event", "") == ""]
    tr = load_truth_xyz(d / "truth.csv")
    if not rows or tr is None:
        return None
    tw, ts, bodies = tr
    man = manifest_for(scene)
    body, H, hsrc = target_of(man, bodies)
    if body is None or body not in bodies:
        return None
    bx, by, bz = bodies[body]
    subj = P.SubjectSpec(height_m=H, beacon_above_head_m=0.0, target_frac=0.5)
    cam = P.CameraSpec()                 # CrazySim fpv_cam: crop 70x70 deg, lens 0.03 m forward, level
    g = lambda r, k: SB.fnum(r, k)
    out = []
    for r in rows:
        px, py, pz, yaw = g(r, "px"), g(r, "py"), g(r, "pz"), g(r, "yaw")
        roll, pitch = g(r, "roll"), g(r, "pitch")
        if any(math.isnan(v) for v in (px, py, pz, yaw)):
            continue
        roll = 0.0 if math.isnan(roll) else roll
        pitch = 0.0 if math.isnan(pitch) else pitch
        wall, t, tp, age = g(r, "wall"), g(r, "t"), g(r, "t_proc"), g(r, "frame_age")
        arrival = wall - (t - tp) - (0.0 if math.isnan(age) else age)
        joins = {"arrival_wall": ("wall", arrival), "row_wall": ("wall", wall), "WRONG_t_vs_sim_t": ("sim", t)}
        pose = P.Pose(px, py, pz, yaw, roll, pitch)
        rec = {"scene": scene, "run": str(d.relative_to(REPO)), "camera": cell.get("camera"),
               "backend": cell.get("backend"), "height_src": hsrc, "t": t,
               "conf": g(r, "conf"), "tracking": g(r, "tracking"), "net_bin": int(g(r, "x_bin")),
               "net_x": g(r, "x_soft"), "net_size_bucket": int(g(r, "size_bucket")),
               "cmd_yaw": g(r, "cmd_yaw"), "yaw": yaw, "roll": roll, "pitch": pitch,
               "fw_ts": g(r, "fw_ts") / 1000.0}
        for jn, (clock, tt) in joins.items():
            base = tw if clock == "wall" else ts
            if not base[0] <= tt <= base[-1]:
                rec[jn] = None
                continue
            X, Y = float(np.interp(tt, base, bx)), float(np.interp(tt, base, by))
            Zc = float(np.interp(tt, base, bz)) if bz is not None else H / 2
            beacon = (X, Y, Zc + H / 2)            # panel centre + half height = top of the head
            if jn == "arrival_wall":
                for v in VARIANTS:
                    lab = label_variant(v, pose, beacon, subj, cam)
                    rec[v] = (lab.bearing_deg, lab.x_norm, lab.x_bin, lab.size_bucket, lab.in_fov, lab.size_frac)
                # (i) scoreboard.py's bearing, same join: atan2(dy, dx) - yaw, CCW (left) positive
                sb = (math.degrees(math.atan2(Y - py, X - px)) - yaw + 180) % 360 - 180
                rec["sb_bearing"] = sb
                lvl = P.pose_to_label(P.Pose(px, py, pz, yaw), beacon, subj,
                                      P.CameraSpec(mount_xyz_body=(0.0, 0.0, 0.0)))
                rec["level_nomount_bearing"] = lvl.bearing_deg
            else:
                lab = P.pose_to_label(pose, beacon, subj, cam)
                rec[jn] = (lab.bearing_deg, lab.x_norm, lab.x_bin, lab.size_bucket, lab.in_fov, lab.size_frac)
        rec["correct_arrival"] = rec.get("correct")
        out.append(rec)
    # pose integrity gate: from the first tumble / yaw jump on, the logged pose is not truth
    k = P.first_pose_discontinuity([f["t"] for f in out], [f["yaw"] for f in out],
                                   [f["roll"] for f in out], [f["pitch"] for f in out])
    stale = P.stalled_pose_mask([f["t"] for f in out], [f["fw_ts"] for f in out])
    for i, rec in enumerate(out):
        rec["after_discontinuity"] = k is not None and i >= k
        rec["pose_stale"] = bool(stale[i])
    # control chain: does a +cmd_yaw make logged yaw go UP over the next ~0.5 s?
    for i, rec in enumerate(out):
        j = i
        while j + 1 < len(out) and out[j + 1]["t"] - rec["t"] < 0.5:
            j += 1
        rec["dyaw_next"] = ((out[j]["yaw"] - rec["yaw"] + 180) % 360 - 180) if j > i else None
    return out


def summarise(frames, key="correct", conf=VIS_CONF):
    """Network vs pose-derived label on frames the network calls visible and the poses put in view."""
    sel = [f for f in frames if f.get(key) and f[key][4] and f["conf"] >= conf]
    if not sel:
        return {"n": 0}
    pb = np.array([f[key][2] for f in sel]); nb = np.array([f["net_bin"] for f in sel])
    px_ = np.array([f[key][1] for f in sel]); nx = np.array([f["net_x"] for f in sel])
    pbear = np.array([f[key][0] for f in sel])
    nbear = np.degrees(np.arctan(nx * math.tan(math.radians(35.0))))
    ps = np.array([f[key][3] for f in sel]); ns = np.array([f["net_size_bucket"] for f in sel])
    return {"n": len(sel), "bin_exact": float(np.mean(pb == nb)), "bin_pm1": float(np.mean(np.abs(pb - nb) <= 1)),
            "x_err_mean": float(np.mean(nx - px_)), "bearing_err_mean_deg": float(np.mean(nbear - pbear)),
            "bearing_abs_err_median_deg": float(np.median(np.abs(nbear - pbear))),
            "bearing_abs_err_p90_deg": float(np.percentile(np.abs(nbear - pbear), 90)),
            "x_corr": float(np.corrcoef(px_, nx)[0, 1]) if np.std(px_) > 0 and np.std(nx) > 0 else None,
            "size_exact": float(np.mean(ps == ns)), "size_pm1": float(np.mean(np.abs(ps - ns) <= 1)),
            "size_signed_mean": float(np.mean(ns - ps))}


def mirror(frames, key):
    sel = [f for f in frames if f.get(key) and f[key][4] and f["conf"] >= VIS_CONF]
    bears = [f[key][0] for f in sel]
    bins = [f["net_bin"] for f in sel]
    sa = P.side_agreement(bears, bins)
    try:
        P.check_not_mirrored(bears, bins)
        verdict = "PASS"
    except P.MirroredLabelsError as e:
        verdict = "RAISED: " + str(e)
    return {"left_n": sa["left"][0], "left_agree": sa["left"][1], "right_n": sa["right"][0],
            "right_agree": sa["right"][1], "guard": verdict}


def fmt(v, spec="{:.3f}"):
    return "-" if v is None else spec.format(v)


def main():
    all_frames, per_run = [], []
    for d in runs():
        fr = analyse_run(d)
        if fr:
            all_frames.extend(fr)
            per_run.append((d, fr))
    scenes = collections.Counter(fr[0]["scene"] for _, fr in per_run)
    res = {"n_flights": len(per_run), "n_frames": len(all_frames), "flights_by_scene": dict(scenes)}
    # Everything below is scored on GATED frames (before any pose discontinuity) unless
    # labelled "ungated"; the ungated mirror result is kept so the effect is visible.
    ungated = all_frames
    cut = [fr for _, fr in per_run if any(f["after_discontinuity"] for f in fr)]
    stl = [fr for _, fr in per_run if any(f["pose_stale"] for f in fr)]
    res["integrity_gate"] = {
        "flights_with_discontinuity": len(cut),
        "frames_after_discontinuity": sum(1 for f in all_frames if f["after_discontinuity"]),
        "discontinuity_by_scene": dict(collections.Counter(fr[0]["scene"] for fr in cut)),
        "flights_with_stale_pose": len(stl),
        "frames_stale_pose": sum(1 for f in all_frames if f["pose_stale"]),
        "frames_excluded_total": sum(1 for f in all_frames if f["after_discontinuity"] or f["pose_stale"]),
        "rule": f"from the first |roll| or |pitch| > {P.MAX_TILT_DEG} deg or yaw step > "
                f"{P.MAX_YAW_RATE_DPS} deg/s on; plus any frame whose pose stamp (fw_ts) has not "
                f"advanced for > {P.MAX_POSE_STALL_S} s",
    }
    all_frames = [f for f in all_frames if not (f["after_discontinuity"] or f["pose_stale"])]
    res["n_frames_gated"] = len(all_frames)

    groups = collections.OrderedDict()
    groups["primary (s01 moving, s15 offset, s07 occlusion; manifest heights)"] = \
        [f for f in all_frames if f["scene"] in PRIMARY]
    for sc in PRIMARY:
        groups[f"  {sc}"] = [f for f in all_frames if f["scene"] == sc]
    for cam in ("clean", "himax_typical"):
        groups[f"  primary, camera={cam}"] = [f for f in all_frames if f["scene"] in PRIMARY and f["camera"] == cam]
    for fl in ("matte", "reflective (pre-fix)"):
        groups[f"  primary, floor={fl}"] = [f for f in all_frames if f["scene"] in PRIMARY and floor_of(f["run"]) == fl]
    groups["secondary (other person scenes; height ASSUMED 1.7 m, size not meaningful)"] = \
        [f for f in all_frames if f["scene"] not in PRIMARY and f["height_src"] == "assumed"]
    res["network_vs_pose_label"] = {k: summarise(v) for k, v in groups.items()}
    res["network_vs_pose_label_conf_ge_0.75"] = {k: summarise(v, conf=0.75) for k, v in groups.items()}
    res["n_flights_by_group"] = {k: len({f["run"] for f in v}) for k, v in groups.items()}

    # (i) against scoreboard.py's bearing
    sbd = [f for f in all_frames if f.get("sb_bearing") is not None and f.get("correct")
           and abs(f["sb_bearing"]) < 90]
    d_level = np.array([f["level_nomount_bearing"] + f["sb_bearing"] for f in sbd])
    d_full = np.array([f["correct"][0] + f["sb_bearing"] for f in sbd])
    res["vs_scoreboard_bearing"] = {
        "n": len(sbd),
        "identity": "pose_to_label bearing == -scoreboard bearing (opposite sign conventions)",
        "level_no_mount_max_abs_diff_deg": float(np.max(np.abs(d_level))),
        "full_model_abs_diff_median_deg": float(np.median(np.abs(d_full))),
        "full_model_abs_diff_p99_deg": float(np.percentile(np.abs(d_full), 99)),
        "full_model_abs_diff_max_deg": float(np.max(np.abs(d_full))),
        "same_sign_frac_if_NOT_negated": float(np.mean(np.sign([f["correct"][0] for f in sbd if abs(f["sb_bearing"]) > 1])
                                                       == np.sign([f["sb_bearing"] for f in sbd if abs(f["sb_bearing"]) > 1]))),
    }

    # joins
    prim = groups["primary (s01 moving, s15 offset, s07 occlusion; manifest heights)"]
    res["joins_primary"] = {j: summarise(prim, j) for j in ("correct_arrival", "row_wall", "WRONG_t_vs_sim_t")}
    mov = [f for f in all_frames if f["scene"] == "s01_control_moving"]
    res["joins_s01_moving"] = {j: summarise(mov, j) for j in ("correct_arrival", "row_wall", "WRONG_t_vs_sim_t")}

    # mirror guard, correct and wrong conventions
    res["mirror_primary"] = {v: mirror(prim, v) for v in VARIANTS}
    res["mirror_primary_UNGATED"] = {v: mirror([f for f in ungated if f["scene"] in PRIMARY], v)
                                     for v in ("correct",)}
    res["mirror_all_person_scenes"] = {v: mirror([f for f in all_frames if f["scene"] != EMPTY], v)
                                       for v in VARIANTS}
    res["summary_wrong_conventions_primary"] = {v: summarise(prim, v) for v in VARIANTS}

    # pre-turn frames: drone has not yawed yet (|yaw| < 1 deg), so no yaw sign is involved.
    pre = [f for f in prim if abs(f["yaw"]) < 1.0]
    res["mirror_primary_yaw_below_1deg"] = mirror(pre, "correct")
    turned = [f for f in prim if abs(f["yaw"]) >= 5.0]
    res["mirror_primary_yaw_at_least_5deg"] = {v: mirror(turned, v) for v in ("correct", "yaw_negated")}
    res["summary_primary_yaw_at_least_5deg"] = {v: summarise(turned, v) for v in ("correct", "yaw_negated")}

    # control chain, tracking frames only
    trk = [f for f in prim if f["tracking"] > 0.5 and f["correct"] and f["correct"][4]]
    left = [f for f in trk if f["correct"][0] <= -P.MIRROR_MIN_DEG]
    right = [f for f in trk if f["correct"][0] >= P.MIRROR_MIN_DEG]
    def frac(fs, fn):
        v = [fn(f) for f in fs if fn(f) is not None]
        return (len(v), float(np.mean(v)) if v else None)
    cy = [(f["cmd_yaw"], f["dyaw_next"]) for f in trk if f["cmd_yaw"] != 0 and f["dyaw_next"] is not None]
    res["control_chain_tracking_frames"] = {
        "left_frames_net_bin_lt4": frac(left, lambda f: f["net_bin"] < 4),
        "left_frames_cmd_yaw_positive": frac(left, lambda f: f["cmd_yaw"] > 0 if f["cmd_yaw"] != 0 else None),
        "left_frames_yaw_increases_next_0.5s": frac(left, lambda f: (f["dyaw_next"] > 0) if f["dyaw_next"] else None),
        "right_frames_net_bin_gt4": frac(right, lambda f: f["net_bin"] > 4),
        "right_frames_cmd_yaw_negative": frac(right, lambda f: f["cmd_yaw"] < 0 if f["cmd_yaw"] != 0 else None),
        "right_frames_yaw_decreases_next_0.5s": frac(right, lambda f: (f["dyaw_next"] < 0) if f["dyaw_next"] else None),
        "sign_agreement_cmd_yaw_vs_dyaw_next": (len(cy), float(np.mean([np.sign(a) == np.sign(b) for a, b in cy])) if cy else None),
    }

    # in-FOV flag: the empty-room control's person stands behind the drone
    emp = [f for f in all_frames if f["scene"] == EMPTY and f.get("correct")]
    res["fov_flag_empty_room"] = {
        "n_frames": len(emp), "n_flights": len({f["run"] for f in emp}),
        "flagged_in_fov": int(sum(1 for f in emp if f["correct"][4])),
        "abs_bearing_min_deg": float(min(abs(f["correct"][0]) for f in emp)) if emp else None,
        "net_conf_ge_0.5_frames": int(sum(1 for f in emp if f["conf"] >= 0.5)),
    }
    allp = [f for f in all_frames if f["scene"] != EMPTY and f.get("correct")]
    oof = [f for f in allp if not f["correct"][4]]
    res["fov_flag_person_scenes"] = {"n_frames": len(allp), "out_of_fov": len(oof),
                                     "out_of_fov_net_conf_ge_0.5": sum(1 for f in oof if f["conf"] >= 0.5)}

    (OUT / "results.json").write_text(json.dumps(res, indent=1, default=str))
    with open(OUT / "flights.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["run", "scene", "camera", "backend", "frames", "vis_in_fov_frames", "bin_exact", "bin_pm1",
                    "bearing_err_mean_deg"])
        for d, fr in per_run:
            s = summarise(fr)
            w.writerow([str(d.relative_to(REPO)), fr[0]["scene"], fr[0]["camera"], fr[0]["backend"], len(fr),
                        s["n"], fmt(s.get("bin_exact")), fmt(s.get("bin_pm1")),
                        fmt(s.get("bearing_err_mean_deg"), "{:+.2f}")])

    # ---- print ----
    print(f"{res['n_flights']} flights, {res['n_frames']} processed frames: {dict(scenes)}\n")
    print("network vs pose-derived label (frames with net conf >= 0.5 AND in view per poses)")
    for k, s in res["network_vs_pose_label"].items():
        if s["n"]:
            print(f"  {k:72s} n={s['n']:6d} flights={res['n_flights_by_group'][k]:3d} bin {s['bin_exact']:.3f} "
                  f"+-1 {s['bin_pm1']:.3f} | bearing err mean {s['bearing_err_mean_deg']:+.2f} "
                  f"med|.| {s['bearing_abs_err_median_deg']:.2f} p90 {s['bearing_abs_err_p90_deg']:.2f} | "
                  f"x corr {fmt(s['x_corr'])} | size {s['size_exact']:.3f} (+-1 {s['size_pm1']:.3f}, "
                  f"net-pose {s['size_signed_mean']:+.2f})")
    print("same, frames with net conf >= 0.75 (the follower's enter bar):")
    for k, s in res["network_vs_pose_label_conf_ge_0.75"].items():
        if s["n"]:
            print(f"  {k:72s} n={s['n']:6d} bin {s['bin_exact']:.3f} +-1 {s['bin_pm1']:.3f} | bearing err mean "
                  f"{s['bearing_err_mean_deg']:+.2f} med|.| {s['bearing_abs_err_median_deg']:.2f} | size {s['size_exact']:.3f}")
    print("\nvs scoreboard.py bearing:", json.dumps(res["vs_scoreboard_bearing"], indent=1))
    print("\njoins (primary):")
    for j, s in res["joins_primary"].items():
        print(f"  {j:18s} n={s['n']} bin {s['bin_exact']:.3f} +-1 {s['bin_pm1']:.3f} "
              f"med|bearing err| {s['bearing_abs_err_median_deg']:.2f} p90 {s['bearing_abs_err_p90_deg']:.2f}")
    print("joins (s01 moving only):")
    for j, s in res["joins_s01_moving"].items():
        print(f"  {j:18s} n={s['n']} bin {s['bin_exact']:.3f} +-1 {s['bin_pm1']:.3f} "
              f"med|bearing err| {s['bearing_abs_err_median_deg']:.2f} p90 {s['bearing_abs_err_p90_deg']:.2f}")
    print("\nintegrity gate:", res["integrity_gate"])
    print("UNGATED mirror (primary, correct):", res["mirror_primary_UNGATED"]["correct"])
    print("\nmirror guard (primary):")
    for v, m in res["mirror_primary"].items():
        print(f"  {v:22s} left {m['left_n']:5d} {fmt(m['left_agree'])}  right {m['right_n']:5d} "
              f"{fmt(m['right_agree'])}  -> {m['guard'][:110]}")
    print("mirror guard (all person scenes):")
    for v, m in res["mirror_all_person_scenes"].items():
        print(f"  {v:22s} left {m['left_n']:5d} {fmt(m['left_agree'])}  right {m['right_n']:5d} "
              f"{fmt(m['right_agree'])}  -> {m['guard'][:110]}")
    print("pre-turn (|yaw|<1):", res["mirror_primary_yaw_below_1deg"])
    print("turned (|yaw|>=5):", json.dumps(res["mirror_primary_yaw_at_least_5deg"], indent=1))
    print("turned summary:", json.dumps(res["summary_primary_yaw_at_least_5deg"], indent=1))
    print("\ncontrol chain:", json.dumps(res["control_chain_tracking_frames"], indent=1))
    print("\nFOV flag, empty room:", res["fov_flag_empty_room"])
    print("FOV flag, person scenes:", res["fov_flag_person_scenes"])


if __name__ == "__main__":
    main()
