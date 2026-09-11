#!/usr/bin/env python3
"""Closed-loop person follower for CrazySim (MuJoCo) using the team's model.

Pipeline: simulated AI-deck frames (UDP from crazysim.py, default port 5200)
-> center square crop -> 128x128 -> team model (float PyTorch, CPU)
-> decode (x bin, size bucket, visibility) with hysteresis
-> body-frame velocity + yaw-rate setpoints via cflib.

Safety rules (MinHyuk's simulator exit criteria):
  * no motion unless a target is confirmed (>= 0.7 for 3 consecutive frames;
    tracking drops below 0.45)
  * target lost -> hover in place
  * frames older than --stale-hover s -> hover; older than --stale-land s -> land
  * speed, yaw-rate, and altitude caps; approach only when roughly centered
  * every control step logged to CSV

Chip emulation (defaults off = unlimited rate, no added delay):
  --rate-hz R      serial chip: after processing a frame at time t, the next
                   frame (always the newest one) is processed no earlier than
                   t + 1/R; frames arriving in between are dropped. No catch-up,
                   so no two processed frames are ever closer than 1/R, like the
                   GAP8 running the model at ~6.5 Hz (one inference at a time)
  --latency-ms L   a command computed from a frame is applied L ms after that
                   frame arrived (FIFO of pending commands), like the chip's
                   ~153 ms inference latency. Stale-frame safety still uses the
                   true age of the newest frame.
  --save-frames D  save every control step (raw frame, raw model outputs,
                   decoded values, pose, timestamps) as compressed .npz batches

Needs the viewer launcher running with the camera enabled:
    ./run_sim_viewer.sh --camera --scene "$PWD/scenes/scene_person.xml"
Run with the trainenv python (torch + cflib).
"""
import argparse, collections, csv, json, math, queue, socket, struct, sys, threading, time
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
DRONE_ROOT = HERE.parents[2]


class FrameReceiver(threading.Thread):
    """Reassembles crazysim.py camera chunks: [seq:u16][total:u16][w:u16][h:u16][data].

    Torn-frame guard: a frame is accepted only if chunks 0..total-1 of that
    frame arrived in order (same total/w/h) since the last seq 0. Anything
    else (a lost, duplicated, or reordered chunk, a new seq 0 before the frame
    finished, a short payload) discards the partial frame and counts it in
    self.torn; chunks are then ignored until the next seq 0. A frame whose
    seq 0 was lost is counted too: while waiting for seq 0, a chunk starts a
    new frame (counted once, rest ignored) if its total/w/h differ from the
    last chunk, or its seq is not above the last seq AND it came > 10 ms after
    the previous chunk (a frame's chunks arrive back to back; frames are
    ~67 ms apart). The time gap keeps a late, reordered chunk of the frame
    just discarded from being counted twice.
    """

    def __init__(self, port: int):
        super().__init__(daemon=True)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 << 20)
        self.sock.bind(("127.0.0.1", port))
        self.sock.settimeout(0.5)
        self.lock = threading.Lock()
        self.frame, self.stamp, self.count = None, 0.0, 0
        self.wall = 0.0   # wall-clock arrival time of the newest frame
        self.torn = 0     # partial frames discarded by the guard

    def run(self):
        parts, hdr = None, None  # parts: chunks of the frame in progress (None = waiting for seq 0)
        # while waiting for seq 0: (seq, total, w, h) of the last chunk seen, used to spot
        # the start of a frame whose seq 0 was lost (seq goes back / header changes)
        last, t_last = (0, 0, 0, 0), 0.0
        while True:
            try:
                pkt, _ = self.sock.recvfrom(65535)
            except socket.timeout:
                continue
            if len(pkt) < 8:
                continue
            seq, total, w, h = struct.unpack("<HHHH", pkt[:8])
            t_pkt = time.monotonic()
            gap, t_last = t_pkt - t_last, t_pkt
            if seq == 0:
                if parts:  # previous frame never finished
                    with self.lock:
                        self.torn += 1
                parts, hdr = [], (total, w, h)
            elif parts is None:
                if (total, w, h) != last[1:] or (seq <= last[0] and gap > 0.010):
                    with self.lock:
                        self.torn += 1   # a new frame whose seq 0 never arrived
                last = (seq, total, w, h)
                continue   # rest of a frame already discarded or missing seq 0; wait for seq 0
            elif (total, w, h) != hdr or seq != len(parts):
                with self.lock:
                    self.torn += 1
                parts, last = None, (seq, total, w, h)
                continue
            parts.append(pkt[8:])
            if len(parts) == total:
                data = b"".join(parts)
                parts, last = None, (seq, total, w, h)
                if total and len(data) >= w * h:
                    img = np.frombuffer(data[: w * h], np.uint8).reshape(h, w).copy()
                    with self.lock:
                        self.frame, self.stamp, self.count = img, time.monotonic(), self.count + 1
                        self.wall = time.time()
                else:
                    with self.lock:
                        self.torn += 1

    def latest(self):
        with self.lock:
            return self.frame, self.stamp, self.count

    def info(self):
        with self.lock:
            return self.wall, self.torn


class FrameSaver(threading.Thread):
    """Writes control steps to <dir>/steps_NNNN.npz (compressed) in batches, off the control loop."""

    def __init__(self, out: Path, batch: int = 100):
        super().__init__(daemon=True)
        self.out, self.batch = out, batch
        self.out.mkdir(parents=True, exist_ok=True)
        self.q, self.buf, self.n_files, self.n_steps = queue.Queue(), [], 0, 0

    def add(self, step: dict):
        self.buf.append(step)
        self.n_steps += 1
        if len(self.buf) >= self.batch:
            self.q.put(self.buf); self.buf = []

    def run(self):
        while True:
            steps = self.q.get()
            if steps is None:
                return
            arrays = {k: np.stack([st[k] for st in steps]) if isinstance(steps[0][k], np.ndarray)
                      else np.array([np.nan if st[k] is None else st[k] for st in steps], np.float64)
                      for k in steps[0]}
            np.savez_compressed(self.out / f"steps_{self.n_files:04d}.npz", **arrays)
            self.n_files += 1

    def close(self):
        if self.buf:
            self.q.put(self.buf); self.buf = []
        self.q.put(None)
        self.join()


class Perception:
    def __init__(self, unstable_root: Path, ckpt: Path):
        sys.path.insert(0, str(unstable_root))
        import torch
        from models.follow_model_factory import build_follow_model_from_checkpoint
        from utils.follow_task import decode_follow_outputs
        self.torch, self.decode = torch, decode_follow_outputs
        self.head = torch.load(ckpt, map_location="cpu").get("follow_head_type")
        self.model = build_follow_model_from_checkpoint(ckpt, torch.device("cpu")).eval()

    def __call__(self, gray: np.ndarray) -> dict:
        s = min(gray.shape)
        y0, x0 = (gray.shape[0] - s) // 2, (gray.shape[1] - s) // 2
        crop = Image.fromarray(gray[y0:y0 + s, x0:x0 + s]).resize((128, 128), Image.BILINEAR)
        x = self.torch.from_numpy(np.asarray(crop, np.float32) / 255.0)[None, None]
        with self.torch.no_grad():
            out = self.model(x)
            dec = self.decode(out, self.head)
        res = {k: float(v.reshape(-1)[0]) for k, v in dec.items() if self.torch.is_tensor(v)}
        res["raw"] = out.detach().reshape(-1).float().numpy().copy()  # all raw outputs (14 for xbin9+size4)
        # Continuous bearing: probability-weighted mean of the 9 uniform bin
        # centers. The argmax bin only changes every 0.22 in x (~4-5 deg), which
        # leaves the controller blind to small offsets.
        xl = dec.get("x_logits")
        if self.torch.is_tensor(xl) and xl.numel() >= 9:
            prob = self.torch.softmax(xl.reshape(-1)[:9].float(), 0)
            centers = self.torch.tensor([-1.0 + (2 * i + 1) / 9.0 for i in range(9)])
            res["x_soft"] = float((prob * centers).sum())
        else:
            res["x_soft"] = res["x_value"]
        return res


def clip(v, lim):
    return max(-lim, min(lim, v))


def snapshot(gray, p, vis, cmd, path):
    img = Image.fromarray(gray).convert("RGB").resize((648, 488), Image.NEAREST)
    d = ImageDraw.Draw(img)
    s = min(gray.shape) * 2
    x0 = (648 - s) // 2
    d.rectangle([x0, 0, x0 + s - 1, 487], outline=(90, 90, 255))  # model's crop
    if vis:
        cx = x0 + (p["x_value"] + 1) / 2 * s
        d.line([cx, 0, cx, 487], fill=(255, 60, 60), width=3)
    d.rectangle([0, 0, 648, 20], fill=(0, 0, 0))
    d.text((6, 4), f"person {p['visibility_confidence']:.2f} {'TRACK' if vis else 'none'} | "
                   f"x {p['x_value']:+.2f} size {int(p['size_bucket_index'])} | "
                   f"vx {cmd[0]:+.2f} m/s yaw {cmd[1]:+.0f} deg/s", fill=(255, 255, 255))
    img.save(path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--uri", default="udp://127.0.0.1:19850")
    ap.add_argument("--frame-port", type=int, default=5200)
    ap.add_argument("--duration", type=float, default=40.0, help="seconds of following before landing")
    ap.add_argument("--height", type=float, default=0.8)
    ap.add_argument("--target-size", type=float, default=0.625, help="size_value to hold (bucket center)")
    ap.add_argument("--k-yaw", type=float, default=60.0, help="deg/s per unit x offset")
    # Measured in CrazySim (Sep 10): a positive rate_yaw setpoint INCREASES
    # stateEstimate yaw (counter-clockwise = left), despite cflib naming
    # +rate "turn right". cflib negates yawrate when it detects legacy-protocol
    # firmware (see commander.py), so the effective sign depends on the
    # firmware version. Person right of center (x > 0) needs a right turn, so
    # -1 here. Re-verify on the real drone's firmware before trusting it.
    ap.add_argument("--yaw-sign", type=float, default=-1.0)
    ap.add_argument("--k-fwd", type=float, default=0.8, help="m/s per unit size error")
    ap.add_argument("--v-max", type=float, default=0.3)
    ap.add_argument("--yaw-max", type=float, default=40.0)
    ap.add_argument("--deadband", type=float, default=0.08)
    # Target confirmation (measured Sep 10): in an empty sim room the champion
    # model produced brief false detections, never above 0.55 for more than 4
    # frames in a row and only once above 0.7. A real person scores ~0.96-1.0
    # every frame. So tracking starts only after --confirm-frames consecutive
    # frames >= --vis-enter, and stops below --vis-exit.
    ap.add_argument("--vis-enter", type=float, default=0.7)
    ap.add_argument("--confirm-frames", type=int, default=3)
    ap.add_argument("--vis-exit", type=float, default=0.45)
    ap.add_argument("--stale-hover", type=float, default=0.5)
    ap.add_argument("--stale-land", type=float, default=3.0)
    ap.add_argument("--no-fly", action="store_true", help="perception only, never take off")
    ap.add_argument("--soft-x", action="store_true",
                    help="steer on the probability-weighted bearing instead of the argmax bin")
    ap.add_argument("--simulate-stale-at", type=float, default=None,
                    help="test hook: ignore camera frames after this many seconds (stale-frame safety test)")
    ap.add_argument("--rate-hz", type=float, default=0.0,
                    help="process at most this many new frames per second, drop the rest (0 = every new frame; "
                         "the GAP8 runs the model at ~6.5 Hz)")
    ap.add_argument("--latency-ms", type=float, default=0.0,
                    help="apply each command this long after its frame arrived (0 = immediately; chip ~153 ms)")
    ap.add_argument("--save-frames", type=Path, default=None,
                    help="directory: save every control step (raw frame, raw outputs, decoded values, pose, "
                         "timestamps) as compressed npz batches")
    ap.add_argument("--out", type=Path, default=Path("follow_run"))
    ap.add_argument("--unstable-root", type=Path, default=DRONE_ROOT / "pytorch_ssd_unstable")
    ap.add_argument("--ckpt", type=Path,
                    default=DRONE_ROOT / "pytorch_ssd_unstable/artifacts/successor_qat_ep3_eval.pth")
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)

    rx = FrameReceiver(a.frame_port)
    rx.start()
    saver = None
    if a.save_frames:
        saver = FrameSaver(a.save_frames)
        saver.start()
        (a.save_frames / "run_args.json").write_text(json.dumps({k: str(v) for k, v in vars(a).items()}, indent=2))
    perc = Perception(a.unstable_root, a.ckpt)
    t_wait = time.monotonic()
    while rx.latest()[0] is None:
        if time.monotonic() - t_wait > 15:
            sys.exit("No camera frames after 15 s; is the sim running with --camera? Not taking off.")
        time.sleep(0.1)
    print(f"camera frames arriving ({rx.latest()[0].shape[1]}x{rx.latest()[0].shape[0]})")

    import logging
    import cflib.crtp
    from cflib.crazyflie import Crazyflie
    from cflib.crazyflie.log import LogConfig
    from cflib.crazyflie.syncCrazyflie import SyncCrazyflie
    from cflib.positioning.motion_commander import MotionCommander
    logging.basicConfig(level=logging.ERROR)
    cflib.crtp.init_drivers()

    pose = {}
    rows, end_reason = [], "duration"
    vis_state, last_count, cmd, streak = False, -1, (0.0, 0.0), 0
    period = 1.0 / a.rate_hz if a.rate_hz > 0 else 0.0
    next_allowed = 0.0                   # serial chip: earliest time the next frame may be processed
    pending = collections.deque()        # latency FIFO: (apply_at, vx, yaw, row, frame_stamp)
    stats = {"processed": 0, "dropped": 0}
    t0 = time.monotonic()
    try:
        with SyncCrazyflie(a.uri, cf=Crazyflie(rw_cache=str(a.out / "cache"))) as scf:
            lc = LogConfig("pose", period_in_ms=50)
            for v in ("stateEstimate.x", "stateEstimate.y", "stateEstimate.z",
                      "stabilizer.roll", "stabilizer.pitch", "stabilizer.yaw"):
                lc.add_variable(v, "float")
            def on_pose(ts, d, _):
                pose.update(d)
                pose["fw_ts"] = ts  # firmware ms since boot (lockstep with sim time)
            lc.data_received_cb.add_callback(on_pose)
            scf.cf.log.add_config(lc)
            lc.start()

            def apply_due(mc, now):
                """Latency FIFO: send every pending command whose time has come (the newest one wins)."""
                nonlocal cmd
                while pending and pending[0][0] <= now:
                    _, vx, yaw, row, fstamp = pending.popleft()
                    cmd = (vx, yaw)
                    if mc:
                        mc.start_linear_motion(vx, 0.0, 0.0, yaw)
                    row["applied_t"] = now - t0
                    row["applied_lat_ms"] = (now - fstamp) * 1000.0

            def control_step(mc):
                nonlocal vis_state, last_count, cmd, streak, next_allowed
                frame, stamp, count = rx.latest()
                now = time.monotonic()
                # test hook: pretend the feed froze. Frames arriving after the freeze are never
                # processed; only the age used by the stale-frame safety is clamped.
                frozen = a.simulate_stale_at is not None and now - t0 > a.simulate_stale_at
                if frozen:
                    stamp = min(stamp, t0 + a.simulate_stale_at)
                age = now - stamp  # true age of the NEWEST frame (not of the command being applied)
                if age > a.stale_land:
                    pending.clear()
                    return "stale-land"
                if age > a.stale_hover:
                    pending.clear()  # never apply a delayed command once the feed is stale
                    cmd = (0.0, 0.0)
                    if mc: mc.start_linear_motion(0.0, 0.0, 0.0, 0.0)
                    rows.append({"t": now - t0, "frame_age": age, "event": "stale-hover"})
                    return None
                apply_due(mc, now)
                if count == last_count or frozen:
                    return None
                if period:
                    if now < next_allowed:
                        return None  # chip still busy: this frame is dropped unless a newer one replaces it
                    next_allowed = now + period  # busy for one full period after starting; no catch-up
                if last_count >= 0:
                    stats["dropped"] += count - last_count - 1
                stats["processed"] += 1
                last_count = count
                p = perc(frame)
                conf = p["visibility_confidence"]
                streak = streak + 1 if conf >= a.vis_enter else 0
                if vis_state and conf < a.vis_exit:
                    vis_state = False
                elif not vis_state and streak >= a.confirm_frames:
                    vis_state = True
                if vis_state:
                    x = p["x_soft"] if a.soft_x else p["x_value"]
                    yaw = 0.0 if abs(x) < a.deadband else clip(a.yaw_sign * a.k_yaw * x, a.yaw_max)
                    vx = clip(a.k_fwd * (a.target_size - p["size_value"]), a.v_max) if abs(x) < 0.5 else 0.0
                else:
                    yaw, vx = 0.0, 0.0
                t = time.monotonic() - t0
                fwall, torn = rx.info()
                row = {"t": t, "t_proc": now - t0, "wall": time.time(), "frame_age": age, "event": "", "conf": conf,
                       "tracking": int(vis_state),
                       "x": p["x_value"], "x_soft": p["x_soft"], "x_bin": int(p["x_bin_index"]),
                       "size": p["size_value"], "size_bucket": int(p["size_bucket_index"]),
                       "cmd_vx": vx, "cmd_yaw": yaw,
                       "px": pose.get("stateEstimate.x"), "py": pose.get("stateEstimate.y"),
                       "pz": pose.get("stateEstimate.z"), "yaw": pose.get("stabilizer.yaw"),
                       "roll": pose.get("stabilizer.roll"), "pitch": pose.get("stabilizer.pitch"),
                       "fw_ts": pose.get("fw_ts"), "frame_count": count, "torn_frames": torn}
                rows.append(row)
                if a.latency_ms > 0:
                    # stamp is the frame's real arrival time here (frozen frames returned above)
                    pending.append((stamp + a.latency_ms / 1000.0, vx, yaw, row, stamp))
                    apply_due(mc, time.monotonic())  # already overdue if inference took longer than L
                else:
                    cmd = (vx, yaw)
                    if mc:
                        mc.start_linear_motion(vx, 0.0, 0.0, yaw)
                    row["applied_t"] = time.monotonic() - t0
                    row["applied_lat_ms"] = (time.monotonic() - stamp) * 1000.0
                if saver:
                    saver.add({"frame": frame, "raw": p["raw"].astype(np.float32),
                               "t": t, "wall": row["wall"], "fw_ts": row["fw_ts"], "frame_count": count,
                               "frame_wall": fwall, "frame_age": age, "torn_frames": torn,
                               "conf": conf, "vis_logit": p.get("visibility_logit"), "tracking": int(vis_state),
                               "x": p["x_value"], "x_soft": p["x_soft"], "x_bin": p["x_bin_index"],
                               "size": p["size_value"], "size_bucket": p["size_bucket_index"],
                               "cmd_vx": vx, "cmd_yaw": yaw,
                               "px": row["px"], "py": row["py"], "pz": row["pz"],
                               "roll": row["roll"], "pitch": row["pitch"], "yaw": row["yaw"]})
                if len(rows) % 30 == 1:
                    snapshot(frame, p, vis_state, (vx, yaw), a.out / f"snap_{len(rows):04d}.png")
                return None

            def tick_sleep():
                # 20 ms poll as before; wake earlier when a delayed command falls due
                d = 0.02
                now = time.monotonic()
                if pending:
                    d = min(d, max(0.001, pending[0][0] - now))
                if period and next_allowed > now:
                    d = min(d, max(0.001, next_allowed - now))  # take the newest frame as soon as the chip is free
                time.sleep(d)

            if a.no_fly:
                while time.monotonic() - t0 < a.duration:
                    if control_step(None):
                        end_reason = "stale-land"; break
                    tick_sleep()
            else:
                with MotionCommander(scf, default_height=a.height) as mc:
                    time.sleep(2.0)  # settle at hover height
                    while time.monotonic() - t0 < a.duration:
                        r = control_step(mc)
                        if r:
                            end_reason = r; break
                        tick_sleep()
                    mc.start_linear_motion(0.0, 0.0, 0.0, 0.0)
                    time.sleep(1.0)
                time.sleep(2.0)  # MotionCommander has landed; let the estimate settle
                rows.append({"t": time.monotonic() - t0, "event": "after-land",
                             "pz": pose.get("stateEstimate.z"), "px": pose.get("stateEstimate.x"),
                             "py": pose.get("stateEstimate.y"), "fw_ts": pose.get("fw_ts")})
            lc.stop()
    except BaseException as e:  # link loss, Ctrl-C, model error: still save what was flown
        end_reason = f"error: {type(e).__name__}: {e}"
        raise
    finally:
        if saver:
            saver.close()
        keys = sorted({k for r in rows for k in r})
        with open(a.out / "follow_log.csv", "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=keys)
            w.writeheader(); w.writerows(rows)
        steps = [r for r in rows if r.get("event") == ""]
        tracked = [r for r in steps if r["tracking"]]
        zs = [r["pz"] for r in steps if r.get("pz") is not None]
        yaws = [r["yaw"] for r in steps if r.get("yaw") is not None]
        summary = {
            "end_reason": end_reason, "control_steps": len(steps),
            # N steps span N-1 intervals; loop_hz is rounded for display, processed_hz is not
            # (measured on t_proc = when processing of the frame started, which the limiter controls)
            "loop_hz": round((len(steps) - 1) / max(steps[-1]["t_proc"] - steps[0]["t_proc"], 1e-6), 1) if len(steps) > 1 else 0,
            "processed_hz": round((len(steps) - 1) / max(steps[-1]["t_proc"] - steps[0]["t_proc"], 1e-6), 3) if len(steps) > 1 else 0,
            "tracking_fraction": round(len(tracked) / max(len(steps), 1), 3),
            "mean_abs_x_while_tracking": round(float(np.mean([abs(r["x"]) for r in tracked])), 3) if tracked else None,
            "centered_fraction_while_tracking": round(float(np.mean([abs(r["x"]) < 0.25 for r in tracked])), 3) if tracked else None,
            "z_max": round(max(zs), 2) if zs else None,
            "yaw_range_deg": [round(min(yaws), 1), round(max(yaws), 1)] if yaws else None,
            "final_pose": {k: round(v, 2) for k, v in (steps[-1] if steps else {}).items()
                           if k in ("px", "py", "pz", "yaw") and v is not None},
            "stale_events": sum(1 for r in rows if r.get("event") == "stale-hover"),
            "z_after_landing": next((round(r["pz"], 2) for r in rows
                                     if r.get("event") == "after-land" and r.get("pz") is not None), None),
            "rate_hz_requested": a.rate_hz, "latency_ms_requested": a.latency_ms,
            "frames_processed": stats["processed"], "frames_dropped": stats["dropped"],
            "torn_frames": rx.info()[1],
        }
        gaps = np.diff([r["t_proc"] for r in steps]) * 1000.0  # between processing starts
        if len(gaps):
            summary["step_gap_ms"] = {"min": round(float(gaps.min()), 1), "median": round(float(np.median(gaps)), 1),
                                      "max": round(float(gaps.max()), 1)}
        lat = [r["applied_lat_ms"] for r in steps if r.get("applied_lat_ms") is not None]
        if lat:
            summary["applied_latency_ms"] = {"mean": round(float(np.mean(lat)), 1),
                                             "p90": round(float(np.percentile(lat, 90)), 1),
                                             "max": round(float(max(lat)), 1)}
        fw = [(r["fw_ts"], r["wall"]) for r in steps if r.get("fw_ts") is not None]
        if len(fw) > 1 and fw[-1][1] > fw[0][1]:
            # Validity (analyze_follow.py): sim keeps up with wall time (>= 0.8), processed rate
            # >= 0.9 x --rate-hz, and no two processed frames closer than 1/rate (serial chip)
            summary["sim_wall_ratio"] = round((fw[-1][0] - fw[0][0]) / 1000.0 / (fw[-1][1] - fw[0][1]), 3)
        if saver:
            summary["saved_steps"] = saver.n_steps
            summary["saved_files"] = saver.n_files
        (a.out / "summary.json").write_text(json.dumps(summary, indent=2))
        print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
