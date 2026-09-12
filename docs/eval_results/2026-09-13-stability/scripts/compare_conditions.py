#!/usr/bin/env python3
"""Per-cell matte vs mirrored comparison of the distance metrics, plus the
Sep 11 baseline and the Sep 12 first attempt for reference.

Usage: compare_conditions.py OUT_DIR
"""
import json
import statistics as st
import sys

REF = "/Users/saimaruvada/Downloads/drone/pytorch_ssd/docs/eval_results/2026-09-12-mirror-refly"


def cells(path):
    d = json.load(open(path))
    return {c["cell_id"]: c for c in d["cells"]}


def med(cell, key):
    v = [r["metrics"].get(key) for r in cell["runs"]
         if r["valid"] and isinstance(r["metrics"].get(key), (int, float))]
    return st.median(v) if v else float("nan")


def main():
    out = sys.argv[1]
    mm = cells(f"{out}/matte_suite/scoreboard.json")
    mi = cells(f"{out}/mirror_suite/scoreboard.json")
    om = cells(f"{REF}/matte_suite/scoreboard.json")
    oc = cells(f"{REF}/mirror_control_suite/scoreboard.json")

    print("MEDIAN DISTANCE HELD (M7_dist_final_m) and M7 SETTLED ERROR, metres")
    print("Sep13 = this experiment (4 repeats/arm).  Sep12 = the first attempt (3 repeats/arm).\n")
    print(f"{'cell':<24} | {'distance held (m)':^33} | {'M7 settled err (m)':^33}")
    print(f"{'':<24} | {'Sep13 mir':>10} {'Sep13 mat':>10} {'Sep12 mat':>10} | "
          f"{'Sep13 mir':>10} {'Sep13 mat':>10} {'Sep12 mat':>10}")
    print("-" * 100)
    for cid in sorted(mm):
        print(f"{cid:<24} | {med(mi[cid],'M7_dist_final_m'):>10.3f} "
              f"{med(mm[cid],'M7_dist_final_m'):>10.3f} "
              f"{med(om[cid],'M7_dist_final_m'):>10.3f} | "
              f"{med(mi[cid],'M7_dist_err_settled_mean_m'):>10.3f} "
              f"{med(mm[cid],'M7_dist_err_settled_mean_m'):>10.3f} "
              f"{med(om[cid],'M7_dist_err_settled_mean_m'):>10.3f}")

    print("\n\nDOES THE MIRROR -> MATTE DISTANCE IMPROVEMENT REPRODUCE?")
    print("Sep12 quoted mirrored -> matte held distance.  Sep13 is the same comparison, interleaved.\n")
    print(f"{'cell':<24} {'Sep12 mir->mat':>22} {'Sep13 mir->mat':>22} {'reproduced?':>13}")
    print("-" * 84)
    for cid in sorted(mm):
        o_mi, o_mm = med(oc[cid], "M7_dist_final_m"), med(om[cid], "M7_dist_final_m")
        n_mi, n_mm = med(mi[cid], "M7_dist_final_m"), med(mm[cid], "M7_dist_final_m")
        o_d, n_d = o_mm - o_mi, n_mm - n_mi
        same = "yes" if (o_d < -0.1 and n_d < -0.1) else ("no" if o_d < -0.1 else "n/a")
        print(f"{cid:<24} {o_mi:>8.3f} -> {o_mm:<8.3f} {n_mi:>8.3f} -> {n_mm:<8.3f} {same:>13}")

    print("\n\nM1 TRACKING FRACTION (median over valid flights)")
    print(f"{'cell':<24} {'Sep13 mirror':>13} {'Sep13 matte':>13} {'Sep12 matte':>13}")
    print("-" * 66)
    for cid in sorted(mm):
        print(f"{cid:<24} {med(mi[cid],'M1_tracking_fraction'):>13.3f} "
              f"{med(mm[cid],'M1_tracking_fraction'):>13.3f} "
              f"{med(om[cid],'M1_tracking_fraction'):>13.3f}")


if __name__ == "__main__":
    main()
