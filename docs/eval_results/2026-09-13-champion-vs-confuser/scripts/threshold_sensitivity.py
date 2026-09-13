#!/usr/bin/env python
"""How much of the confuser's in-flight failure is the 0.70 latch threshold?

WHY THIS EXISTS
  The follower latches at --vis-enter 0.70 after --confirm-frames 3 consecutive
  frames, and it flies BOTH models at that threshold, because that is the
  control loop the drone actually runs. But the two releases did not select
  themselves at the same threshold:

      plain_follow_prod_qat_v3      (champion) checkpoint/quant_eval vis 0.70
      plain_follow_eval576_confuser (confuser) checkpoint/quant_eval vis 0.60

  So the champion flies at exactly its own selection threshold and the confuser
  flies 0.10 above its own. If the confuser's confidence distribution is simply
  shifted down, a fixed 0.70 gate would punish it for calibration rather than
  for blindness, and the flight result would be answering a slightly different
  question than the team thinks.

WHAT THIS IS
  For every flight, the per-frame confidences the network actually produced are
  re-thresholded at a ladder of values, and the follower's OWN latch rule
  (3 consecutive frames >= thr to enter, < vis_exit to leave) is re-applied.
  Reported separately for frames with the person inside the model's field of
  view and frames without.

WHAT THIS IS NOT - AND THIS MATTERS
  **This is open loop.** It re-scores the frames these flights happened to see.
  If the confuser had latched, the drone would have turned, closed distance, and
  seen DIFFERENT frames - very likely better ones, since it would have centred
  and approached the subject. So a latch fraction computed here is NOT a
  prediction of what a 0.60-threshold flight would do. It bounds the question and
  says whether the threshold is worth a real re-fly; it does not answer it.
  Only flying it answers it.

Usage: threshold_sensitivity.py OUT_DIR
"""
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, "/Users/saimaruvada/Downloads/drone/pytorch_ssd/tools/crazysim_macos")
import numpy as np                                          # noqa: E402
import scoreboard as SB                                     # noqa: E402

MODELS = ["champion", "confuser"]
PERSON_CELLS = ["A.static__ships", "B.moving__ships", "D.occlusion__ships"]
DISTRACTOR_CELLS = ["C.empty__ships", "E.furniture__ships", "F.pets__ships"]
LADDER = [0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80]
VIS_EXIT = SB.VIS_EXIT
CONFIRM = SB.CONFIRM_FRAMES


def latch_trace(conf, enter, exit_thr=VIS_EXIT, confirm=CONFIRM):
    """Re-apply the follower's own enter/exit hysteresis to a confidence series."""
    latched = np.zeros(len(conf), bool)
    streak, on = 0, False
    for i, c in enumerate(conf):
        if on:
            if c < exit_thr:
                on, streak = False, 0
        else:
            streak = streak + 1 if c >= enter else 0
            if streak >= confirm:
                on = True
        latched[i] = on
    return latched


def load_conf_and_fov(run_dir):
    cell, summary, rows, truth, manifest = SB.load_run(Path(run_dir))
    flown = [r for r in rows if r.get("event", "") == ""]
    if not flown:
        return None
    conf = np.array([SB.fnum(r, "conf") for r in flown])
    px = np.array([SB.fnum(r, "px") for r in flown])
    py = np.array([SB.fnum(r, "py") for r in flown])
    yaw = np.array([SB.fnum(r, "yaw") for r in flown])
    wall = np.array([SB.fnum(r, "wall") for r in flown])
    sub = SB.target_subject(manifest)
    person_present = sub is not None and sub.get("role") == "person_target"
    in_fov = np.zeros(len(flown), bool)
    if truth is not None and sub is not None:
        body = (sub.get("truth") or {}).get("body", sub["name"])
        bx, by = truth[2].get(body, list(truth[2].values())[0])
        tx = np.interp(wall, truth[0], bx)
        ty = np.interp(wall, truth[0], by)
        bearing = (np.degrees(np.arctan2(ty - py, tx - px)) - yaw + 180) % 360 - 180
        in_fov = person_present & (np.abs(bearing) <= SB.MODEL_HALF_FOV_DEG)
    return conf, in_fov


def main():
    out = Path(sys.argv[1])
    flights = [json.loads(l) for l in open(out / "flights.jsonl")]
    valid = [f for f in flights if f["verdict"] == "VALID"]

    # Pool frames by (model, cell-group, in-view or not).
    pool = {}
    per_flight = []
    for f in valid:
        got = load_conf_and_fov(f["run_dir"])
        if got is None:
            continue
        conf, in_fov = got
        grp = "person" if f["cell"] in PERSON_CELLS else "distractor"
        rec = {"model": f["model"], "cell": f["cell"], "repeat": f["repeat"], "group": grp}
        for thr in LADDER:
            lat = latch_trace(conf, thr)
            if in_fov.any():
                rec[f"latch_in_view@{thr}"] = round(float(np.mean(lat[in_fov])), 4)
                rec[f"frac_conf_over@{thr}_in_view"] = round(float(np.mean(conf[in_fov] >= thr)), 4)
            if (~in_fov).any():
                rec[f"latch_absent@{thr}"] = round(float(np.mean(lat[~in_fov])), 4)
                rec[f"frac_conf_over@{thr}_absent"] = round(float(np.mean(conf[~in_fov] >= thr)), 4)
        per_flight.append(rec)
        key = (f["model"], grp)
        p = pool.setdefault(key, {"conf_in": [], "conf_out": []})
        p["conf_in"].append(conf[in_fov])
        p["conf_out"].append(conf[~in_fov])

    L = []
    A = L.append
    A("THRESHOLD SENSITIVITY - open-loop re-scoring of the frames these flights saw")
    A("=" * 78)
    A("NOT a prediction of a re-flown suite: if the confuser had latched, the drone")
    A("would have moved and seen different frames. This bounds the question only.")
    A(f"latch rule re-applied: >= thr for {CONFIRM} consecutive frames to enter, "
      f"< {VIS_EXIT} to leave")
    A("")

    A("-- confidence distribution, pooled over flights --")
    A(f"   {'model/group':26s} {'n':>7s} {'mean':>7s} {'p05':>7s} {'p50':>7s} {'p95':>7s} {'max':>7s}")
    for grp in ("person", "distractor"):
        for m in MODELS:
            p = pool.get((m, grp))
            if not p:
                continue
            for lbl, arr in (("person in view", p["conf_in"]), ("no person in view", p["conf_out"])):
                allc = np.concatenate([a for a in arr if len(a)]) if any(len(a) for a in arr) else None
                if allc is None or not len(allc):
                    continue
                A(f"   {m[:4]}/{grp[:6]}/{lbl[:14]:15s} {len(allc):7d} "
                  f"{np.mean(allc):7.3f} {np.percentile(allc,5):7.3f} "
                  f"{np.percentile(allc,50):7.3f} {np.percentile(allc,95):7.3f} "
                  f"{np.max(allc):7.3f}")
    A("")

    A("-- median latched fraction WITH THE PERSON IN VIEW (A/B/D cells) --")
    A("   higher is better; this is the recall axis")
    A(f"   {'thr':>6s} " + " ".join(f"{m:>12s}" for m in MODELS))
    for thr in LADDER:
        cols = []
        for m in MODELS:
            vals = [r[f"latch_in_view@{thr}"] for r in per_flight
                    if r["model"] == m and r["group"] == "person"
                    and f"latch_in_view@{thr}" in r]
            cols.append(f"{statistics.median(vals):12.4f}" if vals else f"{'-':>12s}")
        A(f"   {thr:6.2f} " + " ".join(cols))
    A("")

    A("-- median latched fraction WITH NO PERSON IN VIEW, PER CELL --")
    A("   lower is better; this is the false-alarm axis. Pooling C/E/F hides the")
    A("   result: C and E elicit nothing from either model at any threshold, so a")
    A("   pooled median is 0 for both and says nothing. F.pets is where it lives.")
    for cid in DISTRACTOR_CELLS:
        A(f"   {cid}")
        A(f"   {'thr':>6s} " + " ".join(f"{m:>12s}" for m in MODELS))
        for thr in LADDER:
            cols = []
            for m in MODELS:
                vals = [r[f"latch_absent@{thr}"] for r in per_flight
                        if r["model"] == m and r["cell"] == cid
                        and f"latch_absent@{thr}" in r]
                cols.append(f"{statistics.median(vals):12.4f}" if vals else f"{'-':>12s}")
            A(f"   {thr:6.2f} " + " ".join(cols))
        A("")

    A("-- median latched fraction WITH THE PERSON IN VIEW, PER CELL --")
    for cid in PERSON_CELLS:
        A(f"   {cid}")
        A(f"   {'thr':>6s} " + " ".join(f"{m:>12s}" for m in MODELS))
        for thr in LADDER:
            cols = []
            for m in MODELS:
                vals = [r[f"latch_in_view@{thr}"] for r in per_flight
                        if r["model"] == m and r["cell"] == cid
                        and f"latch_in_view@{thr}" in r]
                cols.append(f"{statistics.median(vals):12.4f}" if vals else f"{'-':>12s}")
            A(f"   {thr:6.2f} " + " ".join(cols))
        A("")

    A("-- the operating points the two releases actually selected --")
    A("   champion selected at 0.70 (checkpoint_vis_thresh / quant_eval_vis_thresh)")
    A("   confuser selected at 0.60")
    A("   the follower flies BOTH at 0.70 (--vis-enter default)")
    A("")
    for grp, lbl, cells in (("person", "person in view", PERSON_CELLS),
                            ("distractor", "no person in view", ["F.pets__ships"])):
        key = "in_view" if grp == "person" else "absent"
        for m, own in (("champion", 0.70), ("confuser", 0.60)):
            v_own = [r[f"latch_{key}@{own}"] for r in per_flight
                     if r["model"] == m and r["cell"] in cells and f"latch_{key}@{own}" in r]
            v_flown = [r[f"latch_{key}@0.7"] for r in per_flight
                       if r["model"] == m and r["cell"] in cells and f"latch_{key}@0.7" in r]
            if v_own and v_flown:
                A(f"   {lbl:18s} {m:9s} at own {own:.2f}: "
                  f"{statistics.median(v_own):.4f}   as flown 0.70: "
                  f"{statistics.median(v_flown):.4f}")
        if grp == "distractor":
            A("   (false-alarm row is F.pets only; C and E are zero everywhere)")
    txt = "\n".join(L)
    (out / "threshold_sensitivity.txt").write_text(txt)
    json.dump(per_flight, open(out / "threshold_sensitivity.json", "w"), indent=2)
    print(txt)


if __name__ == "__main__":
    main()
