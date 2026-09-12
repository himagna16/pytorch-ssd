"""Per-cell M7 before/after, from two scoreboard.json files.

  before = docs/sim_results/2026-09-11-simv2/scoreboard.json   (mirrored floor)
  after  = this re-fly's scoreboard.json                       (matte floor)

Reports only cells present in BOTH, and prints the two gated M7 quantities
(`M7_dist_err_settled_mean_m` median <= 0.75 and `M7_final_in_band` median == 1)
plus the raw per-flight `M7_dist_final_m` values, because the median of 2-3
flights hides a spread this controller genuinely has.

Usage:
  <trainenv python> compare_m7.py BEFORE.json AFTER.json [--md]
"""
import argparse
import json
from pathlib import Path

CELLS = ["A.static__ships", "B.moving__ships", "B.moving__delta_backend",
         "B.moving__delta_camera", "B.moving__delta_speed",
         "A.static__proven", "B.moving__proven"]


def load(p):
    d = json.loads(Path(p).read_text())
    return {c["cell_id"]: c for c in d["cells"]}, d


def agg(c, k, f="median"):
    a = c["aggregate"].get(k)
    return None if a is None else a.get(f)


def vals(c, k):
    a = c["aggregate"].get(k)
    return [] if a is None else a.get("values", [])


def fmt(v, n=3):
    return "n/a" if v is None else f"{v:.{n}f}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("before")
    ap.add_argument("after")
    ap.add_argument("--md", action="store_true", help="emit a markdown table")
    a = ap.parse_args()
    B, _ = load(a.before)
    A, _ = load(a.after)

    order = [c for c in CELLS if c in B and c in A] + \
            [c for c in sorted(set(B) & set(A)) if c not in CELLS]

    if a.md:
        print("| cell | setup | M7 mean err before | after | M7 final dist before | after "
              "| in-band before | after | verdict before | after |")
        print("|---|---|---|---|---|---|---|---|---|---|")
        for cid in order:
            b, x = B[cid], A[cid]
            print(f"| `{cid}` | {b['backend']}/{b['camera']}/{b['speed']} "
                  f"| {fmt(agg(b, 'M7_dist_err_settled_mean_m'))} m "
                  f"| **{fmt(agg(x, 'M7_dist_err_settled_mean_m'))} m** "
                  f"| {fmt(agg(b, 'M7_dist_final_m'))} m "
                  f"| **{fmt(agg(x, 'M7_dist_final_m'))} m** "
                  f"| {fmt(agg(b, 'M7_in_band_fraction'))} "
                  f"| **{fmt(agg(x, 'M7_in_band_fraction'))}** "
                  f"| {b['verdict']} | **{x['verdict']}** |")
        return

    for cid in order:
        b, x = B[cid], A[cid]
        print(f"=== {cid}   ({b['backend']}/{b['camera']}/{b['speed']}, {b['scene']})")
        print(f"      {'':<34} {'BEFORE (mirror 0.2)':>22}   {'AFTER (matte 0.0)':>22}")
        print(f"      {'verdict':<34} {b['verdict']:>22}   {x['verdict']:>22}")
        print(f"      {'n_valid / n_flights':<34} "
              f"{str(b['n_valid']) + '/' + str(b['n_flights']):>22}   "
              f"{str(x['n_valid']) + '/' + str(x['n_flights']):>22}")
        for k, gate in (("M7_dist_err_settled_mean_m", "  (gate <= 0.75)"),
                        ("M7_dist_final_m", ""),
                        ("M7_in_band_fraction", ""),
                        ("M7_size_overread_ratio", "  (circular, see §5 of the root-cause)"),
                        ("M1_tracking_fraction", ""),
                        ("M6_max_horizontal_drift_m", "")):
            print(f"      {k + gate:<34} {fmt(agg(b, k)):>22}   {fmt(agg(x, k)):>22}")
        print(f"      {'failed gates':<34} {str(b.get('failed_gates')):>22}")
        print(f"      {'':<34} {'':>22}   {str(x.get('failed_gates')):>22}")
        print(f"      per-flight M7_dist_final_m  before {vals(b, 'M7_dist_final_m')}")
        print(f"      per-flight M7_dist_final_m  after  {vals(x, 'M7_dist_final_m')}")
        print(f"      per-flight M7 mean err      before {vals(b, 'M7_dist_err_settled_mean_m')}")
        print(f"      per-flight M7 mean err      after  {vals(x, 'M7_dist_err_settled_mean_m')}")
        print()


if __name__ == "__main__":
    main()
