#!/usr/bin/env python3
"""Render a demo video of one follower flight from its logs (no screen recording).

Left: the drone's camera frame with the model's view (the square it crops),
the chosen x-bin, a confidence bar with the 0.70 start / 0.45 stop lines,
and the follower's state (FOLLOWING / HOVER / LANDING). Right: a top-down
map with the drone, its heading and camera view, the person's TRUE position
from the simulator's truth log, and both trails.

Needs a run flown with --save-frames and the truth log, e.g.
    ./demo.sh --headless --save-frames --out RUN        (writes RUN/frames, RUN/truth.csv)
    ../../../trainenv/bin/python make_demo_video.py RUN --scene moving --out moving.mp4
Options: --start/--end S (trim, seconds from the first control step),
--fps, --crf. Output: H.264 MP4, 1280x720. Run with the trainenv python;
needs ffmpeg (default /opt/homebrew/bin/ffmpeg or on PATH).
"""
import argparse, csv, glob, json, math, shutil, subprocess, sys
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, Polygon

VIS_ENTER, VIS_EXIT, CONFIRM = 0.7, 0.45, 3      # follow_person.py defaults
HALF_FOV = 35.0                                  # model sees the centre square: fovy 70 deg
TITLES = {"moving": "Person swaying side to side (±1.2 m, 20 s period)",
          "static": "Person standing 3.5 m out, 1 m to the right",
          "empty": "Empty room: the person is behind the drone",
          "freeze": "Camera feed freezes mid-flight (safety test)"}
GREEN, ORANGE, RED, BLUE, GREY = "#1e9e4a", "#e08a00", "#c0392b", "#1f5fa8", "#7f8c8d"


def load(run: Path):
    fr = sorted(glob.glob(str(run / "frames" / "steps_*.npz")))
    if not fr:
        sys.exit(f"No saved frames in {run}/frames: fly with --save-frames")
    parts = [np.load(p) for p in fr]
    st = {k: np.concatenate([p[k] for p in parts]) for k in parts[0].files}
    rows = list(csv.DictReader(open(run / "follow_log.csv")))
    summ = json.loads((run / "summary.json").read_text())
    return st, rows, summ


def fnum(r, k):
    try:
        return float(r[k])
    except (KeyError, ValueError, TypeError):
        return float("nan")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run", type=Path)
    ap.add_argument("--scene", default="moving", choices=list(TITLES))
    ap.add_argument("--truth", type=Path, default=None, help="default: <run>/truth.csv")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--start", type=float, default=0.0)
    ap.add_argument("--end", type=float, default=None)
    ap.add_argument("--fps", type=int, default=15)
    ap.add_argument("--crf", type=int, default=24)
    a = ap.parse_args()

    st, rows, summ = load(a.run)
    truth = np.loadtxt(a.truth or a.run / "truth.csv", delimiter=",", ndmin=2)
    n = len(st["t"])
    t = st["t"]
    wall_off = float(np.median(st["wall"] - t))          # t -> wall clock
    stale = [(fnum(r, "t"), fnum(r, "frame_age")) for r in rows if r.get("event") == "stale-hover"]
    after = next((r for r in rows if r.get("event") == "after-land"), None)
    t_end_ctrl = max([t[-1]] + [s[0] for s in stale])
    # follow_person.py sleeps 2.0 s after MotionCommander has landed, then logs "after-land"
    t_landed = fnum(after, "t") - 2.0 if after else t_end_ctrl + 4.0
    streak = np.zeros(n, int)
    for i in range(n):
        streak[i] = (streak[i - 1] + 1 if i else 1) if st["conf"][i] >= VIS_ENTER else 0

    t0 = t[0] + a.start
    t1 = t_landed + 2.5 if a.end is None else t[0] + a.end
    times = np.arange(t0, t1, 1.0 / a.fps)

    def person_at(tt):
        w = tt + wall_off
        return float(np.interp(w, truth[:, 0], truth[:, 2])), float(np.interp(w, truth[:, 0], truth[:, 3]))

    # map coordinates: forward (+x) is up, left (+y) is left, like the camera
    def uv(x, y):
        return -np.asarray(y), np.asarray(x)

    ptrail = np.array([person_at(tt) for tt in np.linspace(t[0], t_landed, 400)])
    yr = np.radians(st["yaw"])
    fu, fv = uv(st["px"] + 1.6 * np.cos(yr), st["py"] + 1.6 * np.sin(yr))   # keep the camera wedge in view
    allu = np.concatenate([uv(st["px"], st["py"])[0], uv(ptrail[:, 0], ptrail[:, 1])[0], fu])
    allv = np.concatenate([uv(st["px"], st["py"])[1], uv(ptrail[:, 0], ptrail[:, 1])[1], fv])
    cu, cv = (allu.min() + allu.max()) / 2, (allv.min() + allv.max()) / 2
    half = max(allu.max() - allu.min(), (allv.max() - allv.min()) * 0.9) / 2 + 0.8

    W, H = 1280, 720
    fig = plt.figure(figsize=(W / 100, H / 100), dpi=100, facecolor="white")
    fig.text(0.02, 0.955, "Crazyflie person follower in simulation", fontsize=17, weight="bold")
    fig.text(0.02, 0.918, TITLES[a.scene], fontsize=12, color="#333")
    clock = fig.text(0.98, 0.955, "", fontsize=13, ha="right", family="monospace")
    fig.text(0.02, 0.02, "CrazySim (MuJoCo) on a Mac. Rendered from the flight logs. Model: team champion, "
             "full precision on the laptop (not yet the chip). Takeoff not shown.", fontsize=9, color="#555")

    # --- camera panel
    axc = fig.add_axes([0.02, 0.30, 0.47, 0.56])
    img = axc.imshow(st["frame"][0], cmap="gray", vmin=0, vmax=255, extent=(0, 324, 244, 0))
    axc.set_xticks([]); axc.set_yticks([])
    axc.add_patch(Rectangle((40, 0), 244, 244, fill=False, ec="#6a8cff", lw=1.5, ls="--"))
    axc.text(44, 240, "dashed square = what the model sees", color="white", fontsize=8, va="bottom",
             bbox=dict(fc=(0.2, 0.3, 0.8, 0.6), ec="none", pad=2))
    band = axc.add_patch(Rectangle((0, 0), 244 / 9, 244, color=GREEN, alpha=0.25, lw=0))
    mark, = axc.plot([0, 0], [0, 244], color=GREEN, lw=3)
    frozen_txt = axc.text(162, 122, "", color="white", fontsize=22, weight="bold", ha="center", va="center",
                          bbox=dict(fc=(0, 0, 0, 0.55), ec="none"))
    axc.text(4, 4, "drone camera (simulated AI-deck, 324x244 gray)", color="white", fontsize=8, va="top",
             bbox=dict(fc=(0, 0, 0, 0.5), ec="none", pad=2))
    state_txt = fig.text(0.02, 0.872, "", fontsize=15, weight="bold", color="white",
                         bbox=dict(fc=GREEN, ec="none", boxstyle="round,pad=0.3"))
    state_sub = fig.text(0.20, 0.876, "", fontsize=11.5, color="#222")

    # --- confidence bar
    axb = fig.add_axes([0.02, 0.19, 0.47, 0.05])
    axb.set_xlim(0, 1); axb.set_ylim(0, 1); axb.set_yticks([])
    axb.set_xticks([0, 0.25, 0.5, 0.75, 1.0]); axb.tick_params(labelsize=8)
    bar = axb.add_patch(Rectangle((0, 0.1), 0, 0.8, color=GREEN))
    axb.axvline(VIS_ENTER, color="k", lw=2); axb.axvline(VIS_EXIT, color="k", lw=1.5, ls="--")
    axb.text(VIS_ENTER, 1.08, "0.70 start (3 frames in a row)", fontsize=8, ha="center", va="bottom")
    axb.text(VIS_EXIT, 1.08, "0.45 stop", fontsize=8, ha="center", va="bottom")
    axb.set_xlabel("model's person confidence", fontsize=9, labelpad=1)
    conf_txt = fig.text(0.02, 0.265, "", fontsize=11, family="monospace")
    cmd_txt = fig.text(0.02, 0.085, "", fontsize=11, family="monospace")

    # --- map panel
    axm = fig.add_axes([0.55, 0.07, 0.43, 0.80])
    axm.set_xlim(cu - half, cu + half); axm.set_ylim(cv - half * 0.93, cv + half * 0.93)
    axm.set_aspect("equal"); axm.grid(alpha=0.3); axm.tick_params(labelsize=8)
    axm.set_xlabel("metres  (left ←   → right, as seen at takeoff)", fontsize=9)
    axm.set_ylabel("metres forward", fontsize=9)
    axm.set_title("Top-down map (true positions from the simulator)", fontsize=10, loc="left")
    pu, pv = uv(ptrail[:, 0], ptrail[:, 1])
    axm.plot(pu, pv, color=RED, alpha=0.18, lw=6, solid_capstyle="round")
    ptr, = axm.plot([], [], color=RED, lw=1.2, alpha=0.6)
    dtr, = axm.plot([], [], color=BLUE, lw=1.8)
    los, = axm.plot([], [], color=GREY, lw=1, ls=":")
    fov = axm.add_patch(Polygon([[0, 0]] * 3, closed=True, color=BLUE, alpha=0.12, lw=0))
    arrow = axm.add_patch(Polygon([[0, 0]] * 3, closed=True, color=BLUE))
    pers, = axm.plot([], [], "o", ms=16, color=RED, mec="white", mew=2)
    axm.plot([], [], "o", color=RED, label="person (true position)")
    axm.plot([], [], color=BLUE, lw=6, label="drone, heading, camera view")
    axm.legend(loc="lower left", fontsize=8, framealpha=0.9)
    info = axm.text(0.02, 0.98, "", transform=axm.transAxes, fontsize=10, va="top", family="monospace",
                    bbox=dict(fc="white", ec="#ccc", alpha=0.9))
    card = fig.text(0.765, 0.50, "", fontsize=11, ha="center", va="center", multialignment="left",
                    family="monospace", bbox=dict(fc="white", ec="#333", alpha=0.96, boxstyle="round,pad=0.7"))
    import re, textwrap
    CARD_W = 52          # keep the card inside the 1280 px frame (monospace, fontsize 11)

    def wrap_card(line, width=CARD_W):
        """Wrap one scorecard line, continuations hanging under its value column."""
        if len(line) <= width:
            return [line]
        m = re.match(r"^([^:]*:\s*)(.*)$", line)
        if m and len(m.group(1)) <= 26:
            head, rest, ind = m.group(1), m.group(2), " " * len(m.group(1))
        else:
            head, rest, ind = "", line, "   "
        body = textwrap.wrap(rest, width=max(width - len(ind), 20)) or [""]
        return [head + body[0]] + [ind + b for b in body[1:]]

    raw = (a.run / "scorecard.txt").read_text().splitlines() if (a.run / "scorecard.txt").exists() else []
    scorecard = []
    for l in raw:
        if not l.strip() or l.strip().startswith("="):
            continue
        cont = len(l) - len(l.lstrip()) > 10      # a wrapped value line from demo_scorecard.py
        c = re.sub(r":\s+", ": ", re.sub(r"\s+vs the person.s true position", "", l.strip()))
        scorecard.extend(wrap_card(("   " + c) if cont else c))

    ff = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
    a.out.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen([ff, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
                             "-s", f"{W}x{H}", "-r", str(a.fps), "-i", "-", "-c:v", "libx264",
                             "-preset", "medium", "-crf", str(a.crf), "-pix_fmt", "yuv420p",
                             "-movflags", "+faststart", str(a.out)], stdin=subprocess.PIPE)
    for tt in times:
        i = int(np.searchsorted(t, tt, side="right")) - 1
        i = max(i, 0)
        s_row = next((s for s in reversed(stale) if s[0] <= tt and s[0] > t[i]), None)
        conf, trk, xb = st["conf"][i], int(st["tracking"][i]), int(st["x_bin"][i])
        vx, yawc = st["cmd_vx"][i], st["cmd_yaw"][i]
        if tt >= t_landed:
            state, col, sub = "LANDED", GREY, f"height {fnum(after, 'pz'):.2f} m after landing" if after else ""
        elif tt > t_end_ctrl + 0.05:
            state, col = "LANDING", ORANGE
            sub = ("no fresh camera frame for 3 s → safety rule: land" if summ.get("end_reason") == "stale-land"
                   else "planned flight time over → landing")
        elif s_row is not None:
            age = s_row[1] + (tt - s_row[0])
            state, col, sub = "HOVER", ORANGE, f"camera frozen: newest frame {min(age, 3.0):.1f} s old (land at 3.0 s)"
        elif trk:
            state, col = "FOLLOWING", GREEN
            sub = "person confirmed: turning toward them" + (", moving closer" if vx > 0.01 else "")
        else:
            state, col = "HOVER", ORANGE
            sub = (f"checking a possible person: {min(streak[i], CONFIRM)}/{CONFIRM} frames ≥ 0.70"
                   if streak[i] else "no person confirmed: holding still")
        frozen = state in ("HOVER", "LANDING", "LANDED") and (s_row is not None or tt > t_end_ctrl + 0.05) \
            and summ.get("end_reason") == "stale-land"
        state_txt.set_text(f" {state} "); state_txt.get_bbox_patch().set_facecolor(col)
        state_sub.set_text(sub)
        clock.set_text(f"t = {tt - t[0]:5.1f} s")
        img.set_data(st["frame"][i])
        img.set_alpha(0.55 if frozen or tt > t_end_ctrl + 0.05 else 1.0)
        frozen_txt.set_text("CAMERA FROZEN" if frozen else "")
        bx = 40 + xb * 244 / 9
        band.set_x(bx); mark.set_xdata([bx + 122 / 9] * 2)
        shown = conf >= VIS_EXIT and tt <= t_end_ctrl + 0.05 and s_row is None
        band.set_visible(shown); mark.set_visible(shown)
        band.set_color(GREEN if trk else ORANGE); mark.set_color(GREEN if trk else ORANGE)
        live = tt <= t_end_ctrl + 0.05 and s_row is None
        bar.set_width(conf if live else 0); bar.set_color(GREEN if conf >= VIS_ENTER else (ORANGE if conf >= VIS_EXIT else RED))
        conf_txt.set_text(f"person confidence {conf:4.2f}   x-bin {xb + 1}/9   size bucket {int(st['size_bucket'][i])}"
                          if live else "no new frames processed")
        turn = "hold" if abs(yawc) < 0.5 else f"{abs(yawc):4.1f} deg/s {'left' if yawc > 0 else 'right'}"
        cmd_txt.set_text(f"command: turn {turn} | forward {vx:4.2f} m/s" if live else
                         "command: stop (0 m/s, 0 deg/s)")
        # map
        x, y, yaw = st["px"][i], st["py"][i], math.radians(st["yaw"][i])
        du, dv = uv(x, y)
        dtr.set_data(*uv(st["px"][:i + 1], st["py"][:i + 1]))
        tx, ty = person_at(min(tt, t_landed))
        qu, qv = uv(tx, ty)
        pers.set_data([qu], [qv])
        sel = np.linspace(t[0], min(tt, t_landed), 120)
        pp = np.array([person_at(s) for s in sel])
        ptr.set_data(*uv(pp[:, 0], pp[:, 1]))
        los.set_data([du, qu], [dv, qv])
        def dirv(ang, r):
            return uv(x + r * math.cos(ang), y + r * math.sin(ang))
        L = 1.6
        fov.set_xy([[du, dv], dirv(yaw + math.radians(HALF_FOV), L), dirv(yaw - math.radians(HALF_FOV), L)])
        tip = dirv(yaw, 0.45); l = dirv(yaw + 2.5, 0.22); r = dirv(yaw - 2.5, 0.22)
        arrow.set_xy([tip, l, [du, dv], r])
        err = (math.degrees(math.atan2(ty - y, tx - x)) - st["yaw"][i] + 180) % 360 - 180
        head = "person is behind the drone" if a.scene == "empty" else f"heading error {abs(err):5.1f} deg"
        # Past the last control step the drone's pose stops updating while the person keeps
        # moving, so a heading error computed from it would climb and read as lost tracking.
        # also not live during a stale-frame hover: the pose stops updating while the
        # person keeps moving, so a heading error computed from it would climb misleadingly
        live_map = tt <= t_end_ctrl + 0.05 and s_row is None
        lines = ([head] if live_map else []) + [f"distance     {math.hypot(tx - x, ty - y):5.2f} m"]
        lines.append(f"height       {st['pz'][i]:5.2f} m" if live_map else "drone pose: last logged")
        info.set_text("\n".join(lines))
        card.set_text("\n".join(scorecard) if (tt >= t_landed and scorecard) else "")
        card.set_visible(bool(tt >= t_landed and scorecard))
        fig.canvas.draw()
        buf = np.asarray(fig.canvas.buffer_rgba())[:, :, :3]
        proc.stdin.write(np.ascontiguousarray(buf).tobytes())
    proc.stdin.close()
    if proc.wait() != 0:
        sys.exit("ffmpeg failed")
    print(f"wrote {a.out} ({len(times)} frames, {len(times) / a.fps:.1f} s, "
          f"{a.out.stat().st_size / 1e6:.2f} MB)")


if __name__ == "__main__":
    main()
