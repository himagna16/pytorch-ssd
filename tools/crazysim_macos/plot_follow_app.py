#!/usr/bin/env python3
"""Chart a gap8_emulator.py flight of the follow app: heading vs the true bearing to the
person, the app's mode, the frame age / rule-0 excess latency it saw, and the height.

Usage: plot_follow_app.py <run_dir> [--truth truth.csv] [--out chart.png] [--title TEXT]
Times are seconds after the app took over. Shaded: injected fault windows.
"""
import csv, json, math, sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

args = sys.argv[1:]
run = Path(args[0])
truth = np.loadtxt(args[args.index("--truth") + 1], delimiter=",", ndmin=2) if "--truth" in args else None
out = Path(args[args.index("--out") + 1]) if "--out" in args else run / "app_flight.png"
title = args[args.index("--title") + 1] if "--title" in args else run.name
summ = json.loads((run / "summary.json").read_text())
t_act = summ["events"]["active"]
rows = []
for r in csv.DictReader(open(run / "app_log.csv")):
    try:
        rows.append({k: float(v) for k, v in r.items() if v not in ("", None)})
    except ValueError:
        continue
rows = [r for r in rows if r.get("state", 0) >= 2]          # ACTIVE, LANDING, DONE
t = np.array([r["t"] - t_act for r in rows])
col = lambda k: np.array([r.get(k, np.nan) for r in rows])  # noqa: E731
yaw, px, py = col("yaw"), col("px"), col("py")

fig, ax = plt.subplots(4, 1, figsize=(9, 8.5), sharex=True,
                       gridspec_kw={"height_ratios": [3, 1, 2, 1.4]})
if truth is not None:
    tx = np.interp(col("wall"), truth[:, 0], truth[:, 2])
    ty = np.interp(col("wall"), truth[:, 0], truth[:, 3])
    bearing = np.degrees(np.arctan2(ty - py, tx - px))
    ax[0].plot(t, bearing, color="#888", lw=2, label="true bearing to the person")
ax[0].plot(t, yaw, color="#1f5fbf", lw=1.4, label="drone heading (stabilizer.yaw)")
ax[0].set_ylabel("deg")
ax[0].legend(loc="upper right", fontsize=8)

mode = col("mode")
state = col("state")
colors = {1: "#f0b429", 2: "#2e9e5b", 3: "#c0392b"}
names = {1: "HOVER", 2: "FOLLOW", 3: "LAND"}
m = np.where(state >= 3, 3, mode)
for k, c in colors.items():
    ax[1].fill_between(t, 0, 1, where=(m == k), color=c, step="post", label=names[k], lw=0)
ax[1].set_yticks([])
ax[1].set_ylabel("mode")
ax[1].legend(loc="upper right", fontsize=8, ncol=3)

age = col("ageMs")
age = np.where(age >= 65535, np.nan, age)
ax[2].plot(t, age, color="#6a3d9a", lw=1.2, label="ageMs = now - t_fresh (firmware)")
ax[2].plot(t, col("eMs"), color="#e67e22", lw=1.2, label="eMs = rule 0 excess latency of newest packet")
for y, lab in ((500, "hover 0.5 s"), (3000, "land 3.0 s")):
    ax[2].axhline(y, color="#999", ls="--", lw=0.8)
    ax[2].text(t[0], y, " " + lab, va="bottom", fontsize=7, color="#666")
ax[2].set_ylabel("ms")
ax[2].set_yscale("symlog", linthresh=100)
ax[2].legend(loc="upper right", fontsize=8)

ax[3].plot(t, col("pz"), color="#1f5fbf", lw=1.2, label="z estimate")
ax[3].plot(t, col("zCmd"), color="#888", lw=1, ls="--", label="z command")
ax[3].set_ylabel("m")
ax[3].set_xlabel("s after the app took over")
ax[3].legend(loc="upper right", fontsize=8)

for name, w in summ.get("fault_windows", {}).items():
    s0 = w[0] - t_act
    s1 = (w[1] - t_act) if w[1] is not None else t[-1]
    for a in ax:
        a.axvspan(s0, s1, color="#d62728", alpha=0.08)
    ax[0].text(s0, ax[0].get_ylim()[1], f" {name}", va="top", fontsize=8, color="#d62728")
fig.suptitle(title, fontsize=11)
fig.tight_layout()
fig.savefig(out, dpi=110)
print(f"wrote {out}")
