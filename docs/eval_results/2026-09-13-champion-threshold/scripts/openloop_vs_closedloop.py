#!/usr/bin/env python
"""How wrong was the open-loop lead?

THE POINT
---------
The hypothesis that sent this session flying came from open-loop re-scoring:
take the frames a 0.70 flight actually saw, re-apply the latch rule at 0.75 and
0.80, and read off the latched fraction. That is a bound, not a prediction,
because at a higher threshold the drone latches later, moves differently, and
therefore sees DIFFERENT frames.

This session flew the higher thresholds for real. So the size of that error can
now be measured instead of argued about:

  * open-loop  : replay the 0.75 / 0.80 latch rule over the conf series recorded
                 by THIS session's own t070 flights (the same trick the previous
                 session used, applied to the same cells and repeats).
  * closed-loop: the latched fraction the real t075 / t080 flight produced in the
                 SAME cell and the SAME repeat - same scene, same camera seed.

The two differ only in whether the drone was allowed to act on the new rule.

Usage: openloop_vs_closedloop.py OUT_DIR
"""
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, "/Users/saimaruvada/Downloads/drone/pytorch_ssd/tools/crazysim_macos")
import numpy as np                                          # noqa: E402
import scoreboard as SB                                     # noqa: E402

ARMS = {"t075": (0.75, 3, 0.45), "t080": (0.80, 3, 0.45), "t070cf4": (0.70, 4, 0.45)}
CELLS = ["A.static__ships", "B.moving__ships", "C.empty__ships",
         "D.occlusion__ships", "E.furniture__ships", "F.pets__ships"]


def series(run_dir):
    """conf / tracking / in_fov for one flight, on its processed frames."""
    cell, summary, rows, truth, manifest = SB.load_run(Path(run_dir))
    flown = [r for r in rows if r.get("event", "") == ""]
    conf = np.array([SB.fnum(r, "conf") for r in flown])
    trk = np.array([1 if SB.fnum(r, "tracking") > 0.5 else 0 for r in flown])
    px = np.array([SB.fnum(r, "px") for r in flown])
    py = np.array([SB.fnum(r, "py") for r in flown])
    yaw = np.array([SB.fnum(r, "yaw") for r in flown])
    wall = np.array([SB.fnum(r, "wall") for r in flown])
    sub = SB.target_subject(manifest)
    person = sub is not None and sub.get("role") == "person_target"
    in_fov = np.zeros(len(flown), bool)
    if truth is not None and sub is not None:
        body = (sub.get("truth") or {}).get("body", sub["name"])
        bx, by = truth[2].get(body, list(truth[2].values())[0])
        tx = np.interp(wall, truth[0], bx)
        ty = np.interp(wall, truth[0], by)
        bearing = (np.degrees(np.arctan2(ty - py, tx - px)) - yaw + 180) % 360 - 180
        in_fov = person & (np.abs(bearing) <= SB.MODEL_HALF_FOV_DEG)
    return conf, trk, in_fov


def replay_latched(conf, enter, confirm, exit_):
    """The follower's state machine, re-run over a recorded conf series."""
    vis, streak = False, 0
    out = np.zeros(len(conf), int)
    for i, c in enumerate(conf):
        streak = streak + 1 if c >= enter else 0
        if vis and c < exit_:
            vis = False
        elif not vis and streak >= confirm:
            vis = True
        out[i] = int(vis)
    return out


def frac(mask, sel):
    return float(np.mean(mask[sel])) if sel.any() else None


def med(v):
    v = [x for x in v if x is not None]
    return round(statistics.median(v), 4) if v else None


def main():
    out_dir = Path(sys.argv[1])
    flights = [json.loads(l) for l in open(out_dir / "flights.jsonl")]
    valid = {(f["config"], f["cell"], f["repeat"]): f
             for f in flights if f["verdict"] == "VALID"}

    rows = []
    for arm, (enter, confirm, exit_) in ARMS.items():
        for cid in CELLS:
            for rep in (1, 2, 3, 4):
                base = valid.get(("t070", cid, rep))
                real = valid.get((arm, cid, rep))
                if not base or not real:
                    continue
                bconf, btrk, bin_fov = series(base["run_dir"])
                rconf, rtrk, rin_fov = series(real["run_dir"])
                # open loop: the new rule replayed over the 0.70 flight's frames
                opred = replay_latched(bconf, enter, confirm, exit_)
                rows.append({
                    "arm": arm, "cell": cid, "repeat": rep,
                    "openloop_latched_absent": frac(opred, ~bin_fov),
                    "closedloop_latched_absent": frac(rtrk, ~rin_fov),
                    "openloop_latched_in_view": frac(opred, bin_fov),
                    "closedloop_latched_in_view": frac(rtrk, rin_fov),
                    "t070_latched_absent": frac(btrk, ~bin_fov),
                    "t070_latched_in_view": frac(btrk, bin_fov),
                })

    agg = {}
    for arm in ARMS:
        for cid in CELLS:
            sel = [r for r in rows if r["arm"] == arm and r["cell"] == cid]
            if not sel:
                continue
            agg[f"{arm}|{cid}"] = {
                "n": len(sel),
                "openloop_absent_med": med([r["openloop_latched_absent"] for r in sel]),
                "closedloop_absent_med": med([r["closedloop_latched_absent"] for r in sel]),
                "openloop_in_view_med": med([r["openloop_latched_in_view"] for r in sel]),
                "closedloop_in_view_med": med([r["closedloop_latched_in_view"] for r in sel]),
            }
    json.dump({"per_flight": rows, "aggregate": agg},
              open(out_dir / "openloop_vs_closedloop.json", "w"), indent=2)

    L = []
    P = L.append
    P("OPEN LOOP vs CLOSED LOOP - how much the re-scoring lead missed by")
    P("=" * 84)
    P("")
    P("open-loop  = the arm's latch rule replayed over THIS session's own t070 frames")
    P("closed-loop= the same rule actually flown, same cell, same repeat, same noise seed")
    P("'absent'   = fraction of no-person frames latched (the false-alarm axis)")
    P("'in view'  = fraction of person-in-view frames latched (the recall axis)")
    P("")
    for arm in ARMS:
        P(f"-- {arm} --")
        P(f"   {'cell':22s} {'n':>2s} {'open absent':>11s} {'closed absent':>13s} "
          f"{'open inview':>11s} {'closed inview':>13s}")
        for cid in CELLS:
            a = agg.get(f"{arm}|{cid}")
            if not a:
                continue
            def f(v):
                return "   -   " if v is None else f"{v:.4f}"
            P(f"   {cid:22s} {a['n']:>2d} {f(a['openloop_absent_med']):>11s} "
              f"{f(a['closedloop_absent_med']):>13s} {f(a['openloop_in_view_med']):>11s} "
              f"{f(a['closedloop_in_view_med']):>13s}")
        P("")
    txt = "\n".join(L)
    (out_dir / "openloop_vs_closedloop.txt").write_text(txt + "\n")
    print(txt)


if __name__ == "__main__":
    main()
