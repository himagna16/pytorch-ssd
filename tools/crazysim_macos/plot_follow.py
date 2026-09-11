"""Plot drone heading vs the person's true direction for truth-logged runs.

Usage: plot_follow.py out.png <label> <run_dir> <truth.csv> [<label> <run_dir> <truth.csv> ...]
"""
import csv, math, sys
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

out = sys.argv[1]
triples = [sys.argv[i:i + 3] for i in range(2, len(sys.argv), 3)]
fig, axes = plt.subplots(len(triples), 1, figsize=(10, 3.2 * len(triples)), sharex=True, squeeze=False)
for ax, (label, run, truth_csv) in zip(axes[:, 0], triples):
    truth = np.loadtxt(truth_csv, delimiter=",", ndmin=2)
    rows = [r for r in csv.DictReader(open(f"{run}/follow_log.csv")) if r.get("event", "") == ""]
    t0 = float(rows[0]["t"])
    t = np.array([float(r["t"]) - t0 for r in rows])
    px, py = np.array([float(r["px"]) for r in rows]), np.array([float(r["py"]) for r in rows])
    yaw = np.array([float(r["yaw"]) for r in rows])
    wall = np.array([float(r["wall"]) for r in rows])
    tx, ty = np.interp(wall, truth[:, 0], truth[:, 2]), np.interp(wall, truth[:, 0], truth[:, 3])
    bearing = np.degrees(np.arctan2(ty - py, tx - px))
    err = (bearing - yaw + 180) % 360 - 180
    settled = np.abs(err[t > 3.0])
    ax.plot(t, bearing, color="#c0392b", lw=2.2, label="direction to the person (truth)")
    ax.plot(t, yaw, color="#2c3e50", lw=1.6, label="drone heading")
    ax.set_ylabel("degrees")
    ax.set_title(f"{label}: heading error after 3 s = {settled.mean():.1f}° average, "
                 f"{np.percentile(settled, 90):.1f}° 90th percentile", fontsize=10, loc="left")
    ax.grid(alpha=0.3)
    ax.legend(loc="upper right", fontsize=8)
axes[-1, 0].set_xlabel("seconds since first control step")
fig.tight_layout()
fig.savefig(out, dpi=130)
print("saved", out)
