"""One row per FLIGHT from a scoreboard.json, not one row per cell.

The scoreboard aggregates a cell by the median, which is the right thing for a
gate and the wrong thing for noticing that one flight in three behaved
completely differently. This prints every flight.

Usage:
  <trainenv python> run_table.py SCOREBOARD.json [--md]
"""
import argparse
import json
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("scoreboard")
    ap.add_argument("--md", action="store_true")
    a = ap.parse_args()
    d = json.loads(Path(a.scoreboard).read_text())

    hdr = ["cell", "run", "valid", "M1_track", "d_start", "d_final", "M7_err",
           "in_band", "loss_ep", "end"]
    rows = []
    for c in d["cells"]:
        for r in c["runs"]:
            m = r["metrics"]
            rows.append([
                c["cell_id"],
                Path(r["run_dir"]).name.split("__")[-1],
                "yes" if r.get("valid") else "NO",
                m.get("M1_tracking_fraction"),
                m.get("dist_start_m"),
                m.get("M7_dist_final_m"),
                m.get("M7_dist_err_settled_mean_m"),
                "yes" if m.get("M7_final_in_band") else "no",
                m.get("M9_loss_episodes"),
                m.get("end_reason"),
            ])

    def s(v):
        return "-" if v is None else (f"{v:.3f}" if isinstance(v, float) else str(v))

    if a.md:
        print("| " + " | ".join(hdr) + " |")
        print("|" + "---|" * len(hdr))
        for r in rows:
            print("| " + " | ".join(s(v) for v in r) + " |")
    else:
        w = [max(len(hdr[i]), max(len(s(r[i])) for r in rows)) for i in range(len(hdr))]
        print("  ".join(h.ljust(w[i]) for i, h in enumerate(hdr)))
        for r in rows:
            print("  ".join(s(v).ljust(w[i]) for i, v in enumerate(r)))


if __name__ == "__main__":
    main()
