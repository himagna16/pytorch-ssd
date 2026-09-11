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

Needs the viewer launcher running with the camera enabled:
    ./run_sim_viewer.sh --camera --scene "$PWD/scenes/scene_person.xml"
Run with the trainenv python (torch + cflib).
"""
import argparse, csv, json, math, socket, struct, sys, threading, time
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
DRONE_ROOT = HERE.parents[2]


class FrameReceiver(threading.Thread):
    """Reassembles crazysim.py camera chunks: [seq:u16][total:u16][w:u16][h:u16][data]."""

    def __init__(self, port: int):
        super().__init__(daemon=True)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 << 20)
        self.sock.bind(("127.0.0.1", port))
        self.sock.settimeout(0.5)
        self.lock = threading.Lock()
        self.frame, self.stamp, self.count = None, 0.0, 0

    def run(self):
        chunks = {}
        while True:
            try:
                pkt, _ = self.sock.recvfrom(65535)
            except socket.timeout:
                continue
            seq, total, w, h = struct.unpack("<HHHH", pkt[:8])
            if seq == 0:
                chunks = {}
            chunks[seq] = pkt[8:]
            if len(chunks) == total and all(i in chunks for i in range(total)):
                data = b"".join(chunks[i] for i in range(total))
                chunks = {}
                if len(data) >= w * h:
                    img = np.frombuffer(data[: w * h], np.uint8).reshape(h, w).copy()
                    with self.lock:
                        self.frame, self.stamp, self.count = img, time.monotonic(), self.count + 1

    def latest(self):
        with self.lock:
            return self.frame, self.stamp, self.count


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
            dec = self.decode(self.model(x), self.head)
        res = {k: float(v.reshape(-1)[0]) for k, v in dec.items() if self.torch.is_tensor(v)}
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
    ap.add_argument("--out", type=Path, default=Path("follow_run"))
    ap.add_argument("--unstable-root", type=Path, default=DRONE_ROOT / "pytorch_ssd_unstable")
    ap.add_argument("--ckpt", type=Path,
                    default=DRONE_ROOT / "pytorch_ssd_unstable/artifacts/successor_qat_ep3_eval.pth")
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)

    rx = FrameReceiver(a.frame_port)
    rx.start()
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
    t0 = time.monotonic()
    with SyncCrazyflie(a.uri, cf=Crazyflie(rw_cache=str(a.out / "cache"))) as scf:
        lc = LogConfig("pose", period_in_ms=50)
        for v in ("stateEstimate.x", "stateEstimate.y", "stateEstimate.z", "stabilizer.yaw"):
            lc.add_variable(v, "float")
        def on_pose(ts, d, _):
            pose.update(d)
            pose["fw_ts"] = ts  # firmware ms since boot (lockstep with sim time)
        lc.data_received_cb.add_callback(on_pose)
        scf.cf.log.add_config(lc)
        lc.start()

        def control_step(mc):
            nonlocal vis_state, last_count, cmd, streak
            frame, stamp, count = rx.latest()
            if a.simulate_stale_at is not None and time.monotonic() - t0 > a.simulate_stale_at:
                stamp = min(stamp, t0 + a.simulate_stale_at)  # pretend the feed froze
            age = time.monotonic() - stamp
            if age > a.stale_land:
                return "stale-land"
            if age > a.stale_hover:
                cmd = (0.0, 0.0)
                if mc: mc.start_linear_motion(0.0, 0.0, 0.0, 0.0)
                rows.append({"t": time.monotonic() - t0, "frame_age": age, "event": "stale-hover"})
                return None
            if count == last_count:
                return None
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
            cmd = (vx, yaw)
            if mc:
                mc.start_linear_motion(vx, 0.0, 0.0, yaw)
            t = time.monotonic() - t0
            rows.append({"t": t, "wall": time.time(), "frame_age": age, "event": "", "conf": conf,
                         "tracking": int(vis_state),
                         "x": p["x_value"], "x_soft": p["x_soft"], "x_bin": int(p["x_bin_index"]),
                         "size": p["size_value"], "size_bucket": int(p["size_bucket_index"]),
                         "cmd_vx": vx, "cmd_yaw": yaw,
                         "px": pose.get("stateEstimate.x"), "py": pose.get("stateEstimate.y"),
                         "pz": pose.get("stateEstimate.z"), "yaw": pose.get("stabilizer.yaw"),
                         "fw_ts": pose.get("fw_ts")})
            if len(rows) % 30 == 1:
                snapshot(frame, p, vis_state, cmd, a.out / f"snap_{len(rows):04d}.png")
            return None

        if a.no_fly:
            while time.monotonic() - t0 < a.duration:
                if control_step(None):
                    end_reason = "stale-land"; break
                time.sleep(0.02)
        else:
            with MotionCommander(scf, default_height=a.height) as mc:
                time.sleep(2.0)  # settle at hover height
                while time.monotonic() - t0 < a.duration:
                    r = control_step(mc)
                    if r:
                        end_reason = r; break
                    time.sleep(0.02)
                mc.start_linear_motion(0.0, 0.0, 0.0, 0.0)
                time.sleep(1.0)
            time.sleep(2.0)  # MotionCommander has landed; let the estimate settle
            rows.append({"t": time.monotonic() - t0, "event": "after-land",
                         "pz": pose.get("stateEstimate.z"), "px": pose.get("stateEstimate.x"),
                         "py": pose.get("stateEstimate.y"), "fw_ts": pose.get("fw_ts")})
        lc.stop()

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
        "loop_hz": round(len(steps) / max(steps[-1]["t"] - steps[0]["t"], 1e-6), 1) if len(steps) > 1 else 0,
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
    }
    (a.out / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
