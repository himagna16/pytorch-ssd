#!/usr/bin/env python
"""Did this flight actually fly the latch rule its plan row asked for?

WHY THIS EXISTS
---------------
The whole experiment is two command-line flags.  ``follow_person.py`` does NOT
record ``--vis-enter`` or ``--confirm-frames`` into ``summary.json`` (only
``--save-frames`` writes a ``run_args.json``, which this suite does not use), so
there is no self-reported field to trust.  A typo in the harness would silently
produce 96 flights that all flew 0.70, and every "result" would be noise.

So the rule is recovered from the flight log itself rather than from the command
line.  ``follow_log.csv`` records ``conf``, ``streak`` and ``tracking`` on every
processed frame, and the follower's state machine is four lines:

    streak = streak + 1 if conf >= vis_enter else 0
    if vis_state and conf < vis_exit:            vis_state = False
    elif not vis_state and streak >= confirm:    vis_state = True

plus a reset of both on a ``stale-hover`` event.  Replaying that against the
logged ``conf`` column must reproduce the logged ``streak`` and ``tracking``
columns EXACTLY, frame for frame.  It does so only for the rule that actually
ran.

DISCRIMINATING POWER IS ALSO REPORTED, because a check that cannot fail is not a
check.  The replay is run under all four candidate configs.  If several match,
this flight's confidences never entered the band where the configs differ (a
C.empty flight where nothing ever reaches 0.70 is like this), and the flight is
marked AMBIGUOUS rather than being called verified.  A flight is only
THRESH_OK-and-discriminating when the intended config matches and at least one
other candidate does not.

Usage: check_threshold.py RUN_DIR
Prints THRESH_OK ... / THRESH_BAD ... ; exit 0 / 1.
"""
import csv
import json
import os
import sys

CANDIDATES = [
    ("t070",    0.70, 3, 0.45),
    ("t075",    0.75, 3, 0.45),
    ("t080",    0.80, 3, 0.45),
    ("t070cf4", 0.70, 4, 0.45),
]


def load_rows(run):
    with open(os.path.join(run, "follow_log.csv")) as f:
        return list(csv.DictReader(f))


def replay(rows, enter, confirm, exit_):
    """Re-run the follower's latch state machine over the logged conf column.

    Returns (n_compared, n_streak_mismatch, n_tracking_mismatch)."""
    vis, streak = False, 0
    n = smis = tmis = 0
    for r in rows:
        ev = (r.get("event") or "").strip()
        if ev == "stale-hover":
            vis, streak = False, 0
            continue
        if ev:                       # after-land, stale-land, take-off markers
            continue
        try:
            conf = float(r["conf"])
            got_streak = int(float(r["streak"]))
            got_trk = int(float(r["tracking"]))
        except (KeyError, ValueError, TypeError):
            continue
        streak = streak + 1 if conf >= enter else 0
        if vis and conf < exit_:
            vis = False
        elif not vis and streak >= confirm:
            vis = True
        n += 1
        if streak != got_streak:
            smis += 1
        if int(vis) != got_trk:
            tmis += 1
    return n, smis, tmis


def main():
    run = sys.argv[1]
    cell = json.load(open(os.path.join(run, "cell.json")))
    want = (cell["vis_enter"], cell["confirm_frames"], cell["vis_exit"])
    rows = load_rows(run)

    results = {}
    for name, e, c, x in CANDIDATES:
        results[name] = replay(rows, e, c, x)

    wname = cell["config"]
    n, smis, tmis = results[wname]
    if (cell["vis_enter"], cell["confirm_frames"], cell["vis_exit"]) != \
       tuple(d[1:] for d in CANDIDATES if d[0] == wname)[0]:
        print(f"THRESH_BAD cell.json config={wname} disagrees with its own "
              f"vis_enter/confirm_frames/vis_exit {want}")
        sys.exit(1)
    if n == 0:
        print("THRESH_BAD no comparable frames in follow_log.csv")
        sys.exit(1)
    if smis or tmis:
        print(f"THRESH_BAD intended={wname} does NOT reproduce the log: "
              f"{smis}/{n} streak mismatches, {tmis}/{n} tracking mismatches")
        sys.exit(1)

    others = [k for k, (nn, ss, tt) in results.items() if k != wname and ss == 0 and tt == 0]
    disc = len(others) == 0
    print(f"THRESH_OK config={wname} enter={want[0]} confirm={want[1]} exit={want[2]} "
          f"frames={n} discriminating={disc} "
          f"also_consistent_with={','.join(others) if others else 'none'}")
    json.dump({"config": wname, "vis_enter": want[0], "confirm_frames": want[1],
               "vis_exit": want[2], "frames_compared": n,
               "discriminating": disc, "also_consistent_with": others,
               "replay": {k: {"n": v[0], "streak_mismatch": v[1], "tracking_mismatch": v[2]}
                          for k, v in results.items()}},
              open(os.path.join(run, "threshold_check.json"), "w"), indent=2)
    sys.exit(0)


if __name__ == "__main__":
    main()
