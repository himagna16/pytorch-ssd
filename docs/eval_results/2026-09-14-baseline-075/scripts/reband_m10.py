#!/usr/bin/env python3
"""Separate the threshold effect from the behaviour on the M10 uncertain-band gate.

scoreboard.py's M10_uncertain_fraction_present is the fraction of target-in-view
frames whose confidence lies in [vis_exit, vis_enter).  The band's upper edge is
the latch bar the flight recorded, so moving the bar from 0.70 to 0.75 changes
the GATE, not just the flight.  To say which part of any 0.70 -> 0.75 movement
on this gate is bookkeeping and which part is the drone, this script re-runs
scoreboard.py's own metrics_for_run() -- imported, not edited; it has no side
effects -- on each flight's logged trace under BOTH bars:

    for every 0.70 baseline flight: its own value (bar 0.70) and the value the
        same trace would score at bar 0.75;
    for every 0.75 flight of this run: its own value (bar 0.75) and the value the
        same trace would score at bar 0.70.

The bar is changed by handing metrics_for_run() a copy of summary.json with the
latch keys set (a legacy summary has none, so the scorer falls back to 0.70).
Nothing on disk is modified; metrics.json is not rewritten.

Usage: reband_m10.py BASE_RUNS_DIR NEW_RUNS_DIR [cell-id-regex]
"""
import copy
import json
import os
import re
import statistics
import sys

sys.path.insert(0, "/Users/saimaruvada/Downloads/drone/pytorch_ssd/tools/crazysim_macos")
import scoreboard as SB  # noqa: E402  (imported and called, never edited)

KEYS = ("M10_uncertain_fraction_present", "M10_conf_p05_present", "M10_conf_mean_present",
        "M10_uncertain_fraction_absent", "M10_conf_max_absent", "M1_tracking_fraction")


def score_at(run_dir, enter, exit_, cf):
    cell, summary, rows, truth, manifest = SB.load_run(run_dir)
    s = copy.deepcopy(summary)
    s["vis_enter"], s["vis_exit"], s["confirm_frames"] = enter, exit_, cf
    m, _notes = SB.metrics_for_run(cell, s, rows, truth, manifest)
    return cell, {k: m.get(k) for k in KEYS}


def main():
    base, new = sys.argv[1], sys.argv[2]
    pat = re.compile(sys.argv[3]) if len(sys.argv) > 3 else re.compile(r"^B\.moving")
    out = {"base": {}, "new": {}}
    for label, root, own in (("base", base, 0.70), ("new", new, 0.75)):
        for d in sorted(os.listdir(root)):
            cid = d.split("__r")[0]
            if not pat.search(cid):
                continue
            rd = os.path.join(root, d)
            if not os.path.exists(os.path.join(rd, "summary.json")):
                continue
            try:
                _cell, at70 = score_at(rd, 0.70, 0.45, 3)
                _cell, at75 = score_at(rd, 0.75, 0.45, 3)
            except Exception as e:  # noqa: BLE001
                print(f"  {label} {d}: could not score: {e!r}")
                continue
            # sanity: the flight's own bar must reproduce the committed/official value
            own_m = json.load(open(os.path.join(rd, "metrics.json")))["metrics"] if os.path.exists(
                os.path.join(rd, "metrics.json")) else {}
            official = own_m.get("M10_uncertain_fraction_present")
            mine = (at70 if own == 0.70 else at75)["M10_uncertain_fraction_present"]
            out[label].setdefault(cid, []).append(
                {"run": d, "at_0.70": at70, "at_0.75": at75, "official_M10_present": official,
                 "own_bar_reproduces_official": (official is None or official == mine)})

    for label, title in (("base", "0.70 MATTE BASELINE flights (own bar 0.70) re-banded at 0.75"),
                         ("new", "0.75 REFERENCE flights (own bar 0.75) re-banded at 0.70")):
        print("=" * 112)
        print(title)
        print("=" * 112)
        print(f"{'cell':<24} {'run':<32} {'M10 @0.70':>9} {'M10 @0.75':>9} {'delta':>7}  {'official':>8} {'repro':>5}  "
              f"{'p05conf':>7} {'M1':>6}")
        for cid in sorted(out[label]):
            v70, v75 = [], []
            for r in out[label][cid]:
                a, b = r["at_0.70"]["M10_uncertain_fraction_present"], r["at_0.75"]["M10_uncertain_fraction_present"]
                v70.append(a); v75.append(b)
                print(f"{cid:<24} {r['run']:<32} {a:>9.4f} {b:>9.4f} {b - a:>+7.4f}  {str(r['official_M10_present']):>8} "
                      f"{'ok' if r['own_bar_reproduces_official'] else 'NO':>5}  "
                      f"{str(r['at_0.75']['M10_conf_p05_present']):>7} {str(r['at_0.75']['M1_tracking_fraction']):>6}")
            print(f"{'':<24} {'MEDIAN':<32} {statistics.median(v70):>9.4f} {statistics.median(v75):>9.4f} "
                  f"{statistics.median(v75) - statistics.median(v70):>+7.4f}   gate <= 0.05 (clean-camera B cells): "
                  f"@0.70 {'PASS' if statistics.median(v70) <= 0.05 else 'FAIL'}  @0.75 "
                  f"{'PASS' if statistics.median(v75) <= 0.05 else 'FAIL'}")
        print()
    json.dump(out, open(os.path.join(os.path.dirname(os.path.abspath(new)), "reband_m10.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
