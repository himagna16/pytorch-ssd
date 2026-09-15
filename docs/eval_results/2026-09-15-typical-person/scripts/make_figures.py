#!/usr/bin/env python3
"""Two figures.

  subjects.png    the three cutouts side by side, as the COCO crop that
                  build_scene.make_cutout pastes onto the panel, labelled with
                  the rendered percentile and the photograph's own score.
  traces.png      per-flight confidence against time for repeat 1 of every cell,
                  with the 0.75 confirmation bar and the 0.45 exit bar drawn and
                  the latched/unlatched state shaded. This is the picture of why
                  a per-frame rate is not a flight result: hysteresis.

Usage: nemoenv/bin/python make_figures.py <suite_dir>
"""
import csv
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

ROOT = Path("/Users/saimaruvada/Downloads/drone/pytorch_ssd")
sys.path.insert(0, str(ROOT / "tools/crazysim_macos"))
import scoreboard as SB  # noqa: E402

D = Path(sys.argv[1])
IMG = ROOT / "data/coco/images/val2017"
FID = ROOT / "docs/eval_results/2026-09-15-sim-person-fidelity"
COL = {"control": "#3366cc", "median": "#e69f00", "p25": "#cc3311"}
EN = {"control": "control: COCO 19432", "median": "median: COCO 250127",
      "p25": "p25: COCO 124442"}


def subjects_fig():
    picks = json.loads((D / "tables/subject_picks.json").read_text())["picks"]
    real = {r["img_id"]: r for r in csv.DictReader(open(FID / "tables/real_people.csv"))}
    keys = [("control_19432", "control"), ("median", "median"), ("p25", "p25")]
    fig, axes = plt.subplots(1, 3, figsize=(9, 5.2))
    for ax, (pk, ck) in zip(axes, keys):
        p = picks[pk]
        r = real[p["img_id"]]
        b = json.loads(r["subject_bbox"])
        im = Image.open(IMG / r["file_name"]).convert("RGB")
        ax.imshow(im.crop((int(b[0]), int(b[1]), int(b[0] + b[2]), int(b[1] + b[3]))))
        ax.set_xticks([]); ax.set_yticks([])
        for s in ax.spines.values():
            s.set_color(COL[ck]); s.set_linewidth(3)
        ax.set_title(f"{EN[ck]}\nrendered {p['index_pct']}th pct of 266\n"
                     f"photograph {p['photo_chip_via244']} "
                     f"({p['photo_pct_sizematched']}th pct)", fontsize=9)
    fig.suptitle("The three cutouts. Same scene, same 1.7 m, same position, same motion.",
                 fontsize=11)
    fig.tight_layout()
    fig.savefig(D / "figures/subjects.png", dpi=130)
    print("wrote figures/subjects.png")


def traces_fig():
    cells = [("A.static", "static (s15 geometry)"), ("B.moving", "moving (s01 geometry)")]
    fig, axes = plt.subplots(2, 3, figsize=(15, 6.4), sharey=True)
    for row, (cell, cen) in enumerate(cells):
        for col, key in enumerate(("control", "median", "p25")):
            ax = axes[row][col]
            rd = D / "runs" / f"{cell}__{key}__r1a1"
            if not (rd / "follow_log.csv").exists():
                rd = D / "runs" / f"{cell}__{key}__r1a2"
            if not (rd / "follow_log.csv").exists():
                ax.set_title(f"{cen}\n{EN[key]} - no flight"); continue
            _, summary, rows, _, _ = SB.load_run(rd)
            flown = [r for r in rows if r.get("event") == ""]
            t = np.array([SB.fnum(r, "t") for r in flown])
            t = t - t[0]
            conf = np.array([SB.fnum(r, "conf") for r in flown])
            trk = np.array([int(SB.fnum(r, "tracking") or 0) for r in flown])
            enter, ex = SB.latch_rule(summary)[0], SB.latch_rule(summary)[1]
            ax.fill_between(t, 0, 1, where=(trk == 0), color="#dddddd", step="post",
                            transform=ax.get_xaxis_transform(), label="not latched")
            ax.plot(t, conf, lw=0.9, color=COL[key])
            ax.axhline(enter, color="#117733", lw=1, ls="--")
            ax.axhline(ex, color="#882255", lw=1, ls="--")
            ax.set_ylim(0, 1.02); ax.set_xlim(0, t[-1])
            ax.set_title(f"{cen}\n{EN[key]}  tracked {summary['tracking_fraction']:.3f}",
                         fontsize=9)
            if col == 0:
                ax.set_ylabel("chip confidence")
            if row == 1:
                ax.set_xlabel("s")
    axes[0][0].text(0.5, 0.78, "0.75 confirm", color="#117733", fontsize=7)
    axes[0][0].text(0.5, 0.36, "0.45 let go", color="#882255", fontsize=7)
    fig.suptitle("Repeat 1 of each cell. Grey = the follower is NOT latched. "
                 "Dashed: the shipped 0.75 / 0.45 rule.", fontsize=11)
    fig.tight_layout()
    fig.savefig(D / "figures/traces.png", dpi=130)
    print("wrote figures/traces.png")


if __name__ == "__main__":
    (D / "figures").mkdir(exist_ok=True)
    subjects_fig()
    traces_fig()
