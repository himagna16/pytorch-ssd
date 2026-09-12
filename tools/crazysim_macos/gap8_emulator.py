#!/usr/bin/env python3
"""GAP8 + CPX-link emulator for the STM32 follow app in CrazySim.

The follow app (tools/stm32_follow_app/app, compiled into the SITL firmware by
tools/stm32_follow_app/sim/build_image.sh) runs the flight controller ON THE
FIRMWARE. This script stands in for the AI-deck: it takes the simulated camera
frames (the same UDP stream follow_person.py uses), runs the team model on the
Mac, reproduces what the GAP8 firmware puts on the wire, and sends the 28-byte
v6 packets to the Crazyflie over the CRTP app channel with cflib. The host only
takes off (hover setpoints, CRTP priority), sets followapp.enable = 1, logs,
and at the end clears followapp.enable so the app lands. It never steers.

GAP8 behavior reproduced (branch champion-core8-integration, fix round 6):
  * decoder = tools/firmware_decode/follow_decode.c on the int32 output domain
    (float model output / eps_out, rounded): x-bin and size-bucket argmax;
    p >= 0.7 (raw >= 4216) on 3 frames in a row confirms, p < 0.45 (raw < -998)
    loses the target. --selftest checks this port against the C via ctypes.
  * packet v6 (inc/follow_packet.h): tracking bit 0 = confirmed, bit 1 = this
    frame p >= 0.7; frame_age_20ms = ceil(age / 20 ms) at the transfer, 255 =
    no valid frame / older than 5.08 s; gap8_tx_ms = GAP8 ms clock at the transfer.
  * no-target packets (tracking 0, x_bin = size_bucket = 0xFF, vis_raw =
    INT32_MIN, age of the last good frame) on every 0.5 s camera capture timeout;
    the visibility state is reset then.
  * re-confirmation (src/pipeline.c reconfirm_needed): at decode the visibility
    state is reset if there is no good frame yet, the previous good frame is
    older than 0.4 s, or no packet went out for more than 0.4 s. A frame that is
    itself older than 0.4 s goes out with tracking = 0.
  * one frame at a time, always the newest (--rate-hz caps the rate like the
    chip; --infer-ms pads each frame's processing time to model its latency).
Not reproduced: NINA/SPI waits (a packet is on the bus when it is built) and CPX
TX-queue drops. The link faults below model what the GAP8 cannot see.

Faults (seconds after the app took over, i.e. followapp.state became ACTIVE):
  --freeze-at T [--freeze-for D]  camera frames are ignored (GAP8 capture timeouts)
  --stall-at T --stall-for D      the link holds every packet, then delivers them
                                  in one burst (an ESP32/UART stall)
  --delay-at T --delay-for D --delay-ms L   packets sent in the window arrive L ms
                                  late (FIFO, so later packets queue behind them)
  --drop-at T --drop-for D        packets sent in the window are lost

Clocks: the GAP8 ms clock is the Mac's monotonic clock plus a random 32-bit
offset (so wraps are exercised). The firmware's clock is SITL's FreeRTOS tick
(1 kHz from a wall-clock timer that loses ticks under load, ~0.9x). Rule 0 only
flags packets later than the window's fastest delivery, so a slower firmware
clock makes e smaller, not larger; a held packet still shows up as late.

Outputs in --out: follow_log.csv + summary.json (analyze_follow.py-compatible:
one row per processed frame; rows while the app is ACTIVE have event ""),
app_log.csv (the app's firmware log at 50 Hz with the pose), packets.csv (every
packet: build/delivery time, fields, link fault), and events in summary.json.
Score with analyze_follow_app.py (and analyze_follow.py for heading error).

Run with the trainenv python while the follow-app sim runs with the camera:
    ../stm32_follow_app/sim/run_sim_follow_app.sh --camera --scene "$PWD/scenes/moving/scene_person.xml"
    ../../../trainenv/bin/python gap8_emulator.py --duration 40 --out follow_runs/app_moving
"""
import argparse, csv, heapq, json, math, random, struct, sys, threading, time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from follow_person import DRONE_ROOT, FrameReceiver, Perception  # noqa: E402

# GAP8 constants (app_config.h / inc/follow_packet.h on champion-core8-integration 0623a7d)
EPS_OUT = 2.00982e-4              # champion QAT output quantum (firmware_contract.md)
VIS_ENTER_RAW, VIS_EXIT_RAW, CONFIRM_FRAMES = 4216, -998, 3
AGE_UNIT_US, AGE_SAT = 20000, 255
RECONFIRM_GAP_S = 0.4             # APP_FOLLOW_RECONFIRM_GAP_US
CAPTURE_TIMEOUT_S = 0.5           # APP_CAMERA_CAPTURE_TIMEOUT_US
MAGIC, VERSION, PAYLOAD_LEN = 0xA5, 0x06, 24
INT32_MIN = -2 ** 31
TRK_CONFIRMED, TRK_VISIBLE = 0x01, 0x02
PKT_FMT = "<BBHIffBBBBiI"         # 28 bytes, packed, little-endian

APP_STATES = {0: "IDLE", 1: "WAIT_ARM", 2: "ACTIVE", 3: "LANDING", 4: "DONE"}
MODES = {0: "WAIT_WARMUP", 1: "HOVER", 2: "FOLLOW", 3: "LAND"}
REASONS = ["none", "not_armed", "land_latched", "land_stale", "land_no_frame", "hover_stale",
           "hover_not_confirmed", "hover_rule0", "hover_reconfirm"]
ACTIVE, LANDING, DONE = 2, 3, 4


def to_raw_i32(out_f):
    """Float model outputs -> the GAP8's int32 output domain (units of eps_out)."""
    q = np.rint(np.asarray(out_f, np.float64).reshape(-1) / EPS_OUT)
    return [int(v) for v in np.clip(q, -2 ** 31, 2 ** 31 - 1)]


class VisDecoder:
    """Port of tools/firmware_decode/follow_decode.c: follow_decode() + follow_vis_reset()."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.tracking, self.streak = 0, 0

    def decode(self, raw):
        x_bin = int(np.argmax(raw[:9]))          # first index of the maximum, like follow_argmax_i32
        size_bucket = int(np.argmax(raw[10:14]))
        v = int(raw[9])
        if v >= VIS_ENTER_RAW:                   # same order as the C: streak first, then state
            self.streak = min(self.streak + 1, CONFIRM_FRAMES)
        else:
            self.streak = 0
        if self.tracking and v < VIS_EXIT_RAW:
            self.tracking = 0
        elif not self.tracking and self.streak >= CONFIRM_FRAMES:
            self.tracking = 1
        f32 = np.float32
        return {"x_bin": x_bin, "x_center": float(f32(-1.0) + (f32(2.0) * f32(x_bin) + f32(1.0)) / f32(9.0)),
                "size_bucket": size_bucket, "size_center": float((f32(size_bucket) + f32(0.5)) / f32(4.0)),
                "vis_raw": v, "tracking": self.tracking, "visible": int(v >= VIS_ENTER_RAW)}


def age_byte(age_s):
    """transport_if_frame_age: ceil(age / 20 ms); 255 = saturated (older than 5.08 s)."""
    us = max(0, int(age_s * 1e6))
    return min((us + AGE_UNIT_US - 1) // AGE_UNIT_US, AGE_SAT)


def pack_v6(frame_id, x, size, tracking, x_bin, size_bucket, age, vis_raw, gap8_tx_ms):
    return struct.pack(PKT_FMT, MAGIC, VERSION, PAYLOAD_LEN, frame_id & 0xFFFFFFFF, x, size,
                       tracking, x_bin, size_bucket, age, vis_raw, gap8_tx_ms & 0xFFFFFFFF)


class Faults:
    """Fault windows, relative to the moment the app took over (t_active, host monotonic)."""

    def __init__(self, a):
        self.t_active = None
        self.cfg = {}
        for name in ("freeze", "stall", "delay", "drop"):
            at, dur = getattr(a, f"{name}_at"), getattr(a, f"{name}_for")
            if at is not None:
                self.cfg[name] = (at, dur)
        self.delay_s = (a.delay_ms or 0.0) / 1000.0
        # ground latency step: relative to the first packet (t_start), held to the end
        self.t_start = None
        self.gdelay_at = a.ground_delay_at
        self.gdelay_s = (a.ground_delay_ms or 0.0) / 1000.0

    def ground_delay(self, t):
        if self.gdelay_at is None or self.t_start is None or t < self.t_start + self.gdelay_at:
            return 0.0
        return self.gdelay_s

    def window(self, name):
        if name not in self.cfg or self.t_active is None:
            return None
        at, dur = self.cfg[name]
        start = self.t_active + at
        return start, (math.inf if dur is None else start + dur)

    def active(self, name, t):
        w = self.window(name)
        return w is not None and w[0] <= t < w[1]


class Link(threading.Thread):
    """GAP8 SPI -> NINA/ESP32 -> UART -> STM32, played by the CRTP app channel. FIFO."""

    def __init__(self, send, faults):
        super().__init__(daemon=True)
        self.send, self.faults = send, faults
        self.cv = threading.Condition()
        self.q, self.seq, self.last_deliver, self.stop_flag = [], 0, 0.0, False
        self.records = []

    def submit(self, data, rec, t_now):
        with self.cv:
            rec["seq"] = self.seq
            self.seq += 1
            deliver, tag = t_now, ""
            if self.faults.active("drop", t_now):
                rec.update(link="dropped", t_deliver=None)
                self.records.append(rec)
                return
            if self.faults.active("stall", t_now):
                deliver, tag = self.faults.window("stall")[1], "stall"
            if self.faults.active("delay", t_now):
                deliver, tag = t_now + self.faults.delay_s, "delay"
            gd = self.faults.ground_delay(t_now)
            if gd > 0.0:
                deliver, tag = max(deliver, t_now + gd), "gdelay"
            deliver = max(deliver, self.last_deliver)   # FIFO: nothing overtakes a held packet
            if deliver > t_now + 1e-3 and not tag:
                tag = "queued"                           # behind held packets
            self.last_deliver = deliver
            rec["link"] = tag
            heapq.heappush(self.q, (deliver, rec["seq"], data, rec))
            self.cv.notify()

    def run(self):
        while True:
            with self.cv:
                while not self.stop_flag and (not self.q or self.q[0][0] > time.monotonic()):
                    wait = 0.05 if not self.q else min(0.05, max(0.0, self.q[0][0] - time.monotonic()))
                    self.cv.wait(wait)
                if self.stop_flag:
                    return
                _, _, data, rec = heapq.heappop(self.q)
            try:
                self.send(data)
            except Exception as e:  # link down: record it, keep going
                rec["send_error"] = f"{type(e).__name__}: {e}"
            rec["t_deliver"] = time.monotonic()
            self.records.append(rec)

    def stop(self):
        with self.cv:
            self.stop_flag = True
            self.cv.notify()


def post_land_check(cf, tel, setp):
    """Safety review 7, finding 4, on the landed drone (the firmware is locked, so nothing can fly)."""
    got = {}
    cf.param.add_update_callback(group="followapp", name="enable", cb=lambda name, value: got.update(enable=value))
    cf.param.request_param_update("followapp.enable")
    t = time.monotonic()
    while "enable" not in got and time.monotonic() - t < 3.0:
        time.sleep(0.05)
    out = {"enable_read_after_landing": got.get("enable")}
    setp("enable", 1)              # a leftover enable = 1 ...
    setp("reset", 1)               # ... at the reset must not arm
    time.sleep(1.0)
    v = tel.get()
    out["leftover_enable_at_reset"] = {"state": v.get("state"), "armErr": v.get("armErr")}
    setp("enable", 0)
    setp("enable", 1)              # a real 0 -> 1 on the ground: must wait (armMinZ), not take off
    time.sleep(3.0)
    v = tel.get()
    out["enable_edge_on_ground"] = {"state": v.get("state"), "armErr": v.get("armErr"), "pz": v.get("pz"),
                                    "zCmd": v.get("zCmd")}
    setp("enable", 0)
    time.sleep(0.3)
    out["pass"] = (str(out["enable_read_after_landing"]) == "0"
                   and out["leftover_enable_at_reset"] == {"state": 0, "armErr": 21}
                   and out["enable_edge_on_ground"]["state"] == 1 and out["enable_edge_on_ground"]["armErr"] == 20
                   and (out["enable_edge_on_ground"]["pz"] or 0.0) < 0.05)
    print("post-land check:", out, flush=True)
    return out


class Telemetry:
    """Firmware log blocks at 20 ms: pose, and the follow app's log group."""
    BLOCKS = {
        "pose": [("stateEstimate.x", "float"), ("stateEstimate.y", "float"), ("stateEstimate.z", "float"),
                 ("stabilizer.yaw", "float")],
        "fapp": [("followapp.state", "uint8_t"), ("followapp.mode", "uint8_t"), ("followapp.reason", "uint8_t"),
                 ("followapp.yawRate", "float"), ("followapp.vx", "float"), ("followapp.ageMs", "uint16_t"),
                 ("followapp.eMs", "float"), ("followapp.reconf", "uint8_t"), ("followapp.rxStale", "uint16_t")],
        "fapp2": [("followapp.zCmd", "float"), ("followapp.rxApp", "uint16_t"), ("followapp.rxRej", "uint16_t"),
                  ("followapp.armErr", "uint8_t"), ("followapp.landRsn", "uint8_t"), ("followapp.lastRx", "uint8_t"),
                  ("followapp.riseMs", "float")],
    }
    SHORT = {"stateEstimate.x": "px", "stateEstimate.y": "py", "stateEstimate.z": "pz", "stabilizer.yaw": "yaw"}

    def __init__(self, cf, t0, period_ms=20):
        self.lock, self.v, self.rows, self.t0 = threading.Lock(), {}, [], t0
        self.configs = []
        for name, variables in self.BLOCKS.items():
            lc = LogConfig_(name, period_in_ms=period_ms)
            for var, typ in variables:
                lc.add_variable(var, typ)
            lc.data_received_cb.add_callback(self._cb)
            cf.log.add_config(lc)
            self.configs.append(lc)
        for lc in self.configs:
            lc.start()

    def _cb(self, ts, data, lc):
        now = time.monotonic()
        with self.lock:
            for k, val in data.items():
                self.v[self.SHORT.get(k, k.replace("followapp.", ""))] = val
            self.v["fw_ts"] = ts
            if lc.name == "fapp":
                self.rows.append({"t": now - self.t0, "wall": time.time(), **self.v})

    def get(self):
        with self.lock:
            return dict(self.v)

    def state(self):
        with self.lock:
            return self.v.get("state")

    def stop(self):
        for lc in self.configs:
            try:
                lc.stop()
            except Exception:
                pass


class Gap8(threading.Thread):
    """The GAP8 firmware's per-frame loop: capture -> model -> decode -> v6 packet."""

    def __init__(self, rx, perc, link, faults, tel, a, t0):
        super().__init__(daemon=True)
        self.rx, self.perc, self.link, self.faults, self.tel, self.a, self.t0 = rx, perc, link, faults, tel, a, t0
        self.dec = VisDecoder()
        self.clock_base_ms = a.gap8_clock_start_ms if a.gap8_clock_start_ms is not None else random.getrandbits(32)
        self.t_boot = time.monotonic()
        self.have_good, self.last_good_cap, self.last_tx = False, None, None
        self.frame_id, self.last_count, self.last_capture = 0, -1, time.monotonic()
        self.period = 1.0 / a.rate_hz if a.rate_hz > 0 else 0.0
        self.next_allowed = 0.0
        self.stop_flag = False
        self.rows = []
        self.stats = {"frames_processed": 0, "frames_dropped": 0, "frames_ignored_frozen": 0, "no_target_packets": 0,
                      "reconfirm_resets": 0, "frames_too_old": 0, "frames_bit0": 0}

    def gap8_ms(self, t):
        return (self.clock_base_ms + int((t - self.t_boot) * 1000.0)) & 0xFFFFFFFF

    def rel(self, t):
        return None if t is None else t - self.t0

    def reconfirm_needed(self, now):
        if not self.have_good:
            return True
        if now - self.last_good_cap > RECONFIRM_GAP_S:
            return True
        return self.last_tx is None or now - self.last_tx > RECONFIRM_GAP_S

    def capture_timeout(self, now):
        """app_main.c: capture timed out (0.5 s): no-target packet, visibility state reset."""
        self.last_capture = now
        self.frame_id += 1
        self.dec.reset()
        age = age_byte(now - self.last_good_cap) if self.have_good else AGE_SAT
        if age >= AGE_SAT:
            self.have_good = False   # saturated latch until the next valid frame
        pkt = pack_v6(self.frame_id, 0.0, 0.0, 0, 0xFF, 0xFF, age, INT32_MIN, self.gap8_ms(now))
        self.last_tx = now
        self.stats["no_target_packets"] += 1
        rec = {"kind": "no-target", "t_build": self.rel(now), "frame_id": self.frame_id, "tracking": 0,
               "age": age, "x": 0.0, "size": 0.0, "x_bin": 0xFF, "size_bucket": 0xFF, "vis_raw": INT32_MIN,
               "gap8_tx_ms": self.gap8_ms(now), "cap_t": self.rel(self.last_good_cap) if self.have_good else None,
               "reset": 1, "frame_old": 0}
        self.link.submit(pkt, rec, now)

    def run(self):
        while not self.stop_flag:
            frame, stamp, count = self.rx.latest()
            now = time.monotonic()
            if frame is not None and count != self.last_count and self.faults.active("freeze", now):
                self.stats["frames_ignored_frozen"] += count - self.last_count
                self.last_count = count          # frames during the freeze never reach the GAP8
            new = frame is not None and count != self.last_count and now >= self.next_allowed
            if not new:
                if now - self.last_capture >= CAPTURE_TIMEOUT_S:
                    self.capture_timeout(now)
                time.sleep(0.002)
                continue
            if self.last_count >= 0:
                self.stats["frames_dropped"] += count - self.last_count - 1
            self.last_count, self.last_capture = count, now
            if self.period:
                self.next_allowed = now + self.period
            self.frame_id += 1
            cap = stamp                          # capture completion = the full frame's arrival on the Mac
            t_proc = now
            p = self.perc(frame)
            raw = to_raw_i32(p["raw"])
            if self.a.infer_ms > 0:
                wait = cap + self.a.infer_ms / 1000.0 - time.monotonic()
                if wait > 0:
                    time.sleep(wait)
            now = time.monotonic()
            reset = self.reconfirm_needed(now)
            if reset:
                self.dec.reset()
                self.stats["reconfirm_resets"] += 1
            d = self.dec.decode(raw)
            frame_old = now - cap > RECONFIRM_GAP_S
            if frame_old:                        # pipeline.c: must not count, must not steer
                self.dec.reset()
                d["tracking"] = 0
                self.stats["frames_too_old"] += 1
            t_send = time.monotonic()
            age = age_byte(t_send - cap)
            trk = 0
            if t_send - cap <= RECONFIRM_GAP_S:  # transport_if.c
                trk = (TRK_CONFIRMED if d["tracking"] else 0) | (TRK_VISIBLE if d["visible"] else 0)
            gtx = self.gap8_ms(t_send)
            pkt = pack_v6(self.frame_id, d["x_center"], d["size_center"], trk, d["x_bin"], d["size_bucket"],
                          age, d["vis_raw"], gtx)
            self.last_tx = t_send
            self.have_good, self.last_good_cap = True, cap
            self.stats["frames_processed"] += 1
            self.stats["frames_bit0"] += trk & 1
            rec = {"kind": "frame", "t_build": self.rel(t_send), "frame_id": self.frame_id, "tracking": trk,
                   "age": age, "x": d["x_center"], "size": d["size_center"], "x_bin": d["x_bin"],
                   "size_bucket": d["size_bucket"], "vis_raw": d["vis_raw"], "gap8_tx_ms": gtx,
                   "cap_t": self.rel(cap), "reset": int(reset), "frame_old": int(frame_old),
                   "conf": p["visibility_confidence"], "host_x": p["x_value"]}
            self.link.submit(pkt, rec, t_send)
            v = self.tel.get() if self.tel else {}
            _, torn = self.rx.info()
            self.rows.append({
                "t": self.rel(t_send), "t_proc": self.rel(t_proc), "wall": time.time(), "frame_age": t_send - cap,
                "conf": p["visibility_confidence"], "tracking": trk & 1, "bit1": (trk >> 1) & 1,
                "streak": self.dec.streak, "x": d["x_center"], "x_soft": p["x_soft"], "x_bin": d["x_bin"],
                "size": d["size_center"], "size_bucket": d["size_bucket"], "vis_raw": d["vis_raw"],
                "host_x": p["x_value"], "gap8_reset": int(reset), "frame_id": self.frame_id,
                "cmd_vx": v.get("vx"), "cmd_yaw": v.get("yawRate"), "app_state": v.get("state"),
                "app_mode": v.get("mode"), "app_reason": v.get("reason"), "age_ms": v.get("ageMs"),
                "e_ms": v.get("eMs"), "px": v.get("px"), "py": v.get("py"), "pz": v.get("pz"),
                "yaw": v.get("yaw"), "fw_ts": v.get("fw_ts"), "frame_count": count, "torn_frames": torn})


LogConfig_ = None  # cflib LogConfig, bound in main() after the cflib import


def selftest():
    """Check the decoder port against tools/firmware_decode/follow_decode.c, the packet layout
    against follow_controller.h offsets, and the age rounding. Needs cc."""
    import ctypes, subprocess, tempfile
    src = HERE.parent / "firmware_decode" / "follow_decode.c"
    tmp = Path(tempfile.mkdtemp())
    lib = tmp / "libfd.so"
    subprocess.run(["cc", "-O2", "-shared", "-fPIC", "-I", str(src.parent), "-o", str(lib), str(src), "-lm"],
                   check=True)
    fd = ctypes.CDLL(str(lib))

    class Cfg(ctypes.Structure):
        _fields_ = [("enter_raw", ctypes.c_int32), ("exit_raw", ctypes.c_int32), ("confirm_frames", ctypes.c_int)]

    class St(ctypes.Structure):
        _fields_ = [("tracking", ctypes.c_int), ("streak", ctypes.c_int)]

    class Cmd(ctypes.Structure):
        _fields_ = [("x_bin", ctypes.c_int), ("x_center", ctypes.c_float), ("size_bucket", ctypes.c_int),
                    ("size_center", ctypes.c_float), ("vis_raw", ctypes.c_int32), ("tracking", ctypes.c_int)]

    cfg, st = Cfg(), St()
    fd.follow_vis_cfg_default(ctypes.byref(cfg), ctypes.c_double(EPS_OUT))
    assert (cfg.enter_raw, cfg.exit_raw, cfg.confirm_frames) == (VIS_ENTER_RAW, VIS_EXIT_RAW, CONFIRM_FRAMES), \
        (cfg.enter_raw, cfg.exit_raw, cfg.confirm_frames)
    fd.follow_vis_reset(ctypes.byref(st))
    dec, rng, n = VisDecoder(), np.random.default_rng(7), 0
    for i in range(200000):
        if rng.random() < 0.02:
            fd.follow_vis_reset(ctypes.byref(st))
            dec.reset()
        raw = rng.integers(-30000, 30000, 14)
        if rng.random() < 0.3:
            raw[:9] = rng.integers(-2, 2, 9)      # ties
            raw[10:] = rng.integers(-2, 2, 4)
        raw[9] = rng.choice([VIS_ENTER_RAW - 1, VIS_ENTER_RAW, VIS_EXIT_RAW - 1, VIS_EXIT_RAW,
                             int(rng.integers(-20000, 20000))])
        raw = [int(v) for v in raw]
        cmd = Cmd()
        fd.follow_decode((ctypes.c_int32 * 14)(*raw), ctypes.byref(cfg), ctypes.byref(st), ctypes.byref(cmd))
        d = dec.decode(raw)
        got = (d["x_bin"], d["x_center"], d["size_bucket"], d["size_center"], d["vis_raw"], d["tracking"])
        want = (cmd.x_bin, cmd.x_center, cmd.size_bucket, cmd.size_center, cmd.vis_raw, cmd.tracking)
        assert got == want and dec.streak == st.streak, (i, raw, got, want)
        n += 1
    # packet layout: offsets of follow_controller.h (FOLLOW_PKT_OFF_*)
    assert struct.calcsize(PKT_FMT) == 28
    offs = [struct.calcsize(PKT_FMT[:k + 1]) for k in range(len(PKT_FMT) - 1)]  # prefix sizes
    assert offs == [0, 1, 2, 4, 8, 12, 16, 17, 18, 19, 20, 24], offs
    pk = pack_v6(0x01020304, 0.5, 0.25, 3, 5, 2, 7, -9, 0xFFFFFFFF)
    assert pk[0] == 0xA5 and pk[1] == 6 and pk[2:4] == b"\x18\x00" and pk[4:8] == b"\x04\x03\x02\x01"
    assert pk[16] == 3 and pk[19] == 7 and pk[24:28] == b"\xff\xff\xff\xff"
    for s, want in ((0, 0), (1e-6, 1), (0.02, 1), (0.020001, 2), (5.08, 254), (5.080001, 255), (60, 255)):
        assert age_byte(s) == want, (s, age_byte(s), want)
    print(f"selftest OK: decoder port == follow_decode.c on {n} frames (random streams with resets, ties and "
          f"threshold values); packet layout and age rounding OK")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--uri", default="udp://127.0.0.1:19850")
    ap.add_argument("--frame-port", type=int, default=5200)
    ap.add_argument("--duration", type=float, default=30.0,
                    help="seconds of following after the app takes over; then followapp.enable = 0 (the app lands)")
    ap.add_argument("--height", type=float, default=0.8, help="host take-off height before the app takes over")
    ap.add_argument("--yaw-sign", type=int, choices=(-1, 1), default=None,
                    help="write followapp.yawSign (then followapp.reset) before take-off; default: firmware's (-1)")
    ap.add_argument("--arm-fresh", type=int, choices=(0, 1), default=None,
                    help="write followapp.armFresh (then followapp.reset); default: firmware's (1)")
    ap.add_argument("--rate-hz", type=float, default=0.0, help="GAP8 frame rate cap (0 = every new frame)")
    ap.add_argument("--infer-ms", type=float, default=0.0,
                    help="pad each frame's processing (capture -> packet) to at least this long")
    ap.add_argument("--gap8-clock-start-ms", type=lambda s: int(s, 0), default=None,
                    help="initial GAP8 ms clock (default: random 32-bit)")
    for name, extra in (("freeze", "camera frames ignored"), ("stall", "link holds packets, then bursts"),
                        ("delay", "packets arrive --delay-ms late"), ("drop", "packets lost")):
        ap.add_argument(f"--{name}-at", type=float, default=None, help=f"fault: {extra}; s after the app took over")
        ap.add_argument(f"--{name}-for", type=float, default=None, help="fault duration in s")
    ap.add_argument("--delay-ms", type=float, default=None)
    ap.add_argument("--ground-delay-at", type=float, default=None,
                    help="fault: from this many s after the first packet (before take-off) every packet "
                         "arrives --ground-delay-ms late, to the end (a link that got slower on the ground)")
    ap.add_argument("--ground-delay-ms", type=float, default=None)
    ap.add_argument("--post-land-check", action="store_true",
                    help="after the landing: read followapp.enable (the app clears it when it lands), then check "
                         "that a leftover enable = 1 at a reset does not arm (armErr 21) and that enable 0 -> 1 on "
                         "the ground does not take off (armErr 20, below followapp.armMinZ)")
    ap.add_argument("--enable-after", type=float, default=0.0,
                    help="host hovers until this many s after the first packet before it sets followapp.enable")
    ap.add_argument("--no-fly", action="store_true", help="stream packets and log, never take off or enable the app")
    ap.add_argument("--selftest", action="store_true", help="check the decoder port against follow_decode.c and exit")
    ap.add_argument("--out", type=Path, default=Path("follow_app_run"))
    ap.add_argument("--unstable-root", type=Path, default=DRONE_ROOT / "pytorch_ssd_unstable")
    ap.add_argument("--ckpt", type=Path,
                    default=DRONE_ROOT / "pytorch_ssd_unstable/artifacts/successor_qat_ep3_eval.pth")
    a = ap.parse_args()
    if a.selftest:
        selftest()
        return
    if a.stall_at is not None and a.stall_for is None:
        ap.error("--stall-at needs --stall-for (a stall without an end is --drop-at)")
    if a.delay_at is not None and not a.delay_ms:
        ap.error("--delay-at needs --delay-ms")
    if a.ground_delay_at is not None and not a.ground_delay_ms:
        ap.error("--ground-delay-at needs --ground-delay-ms")
    a.out.mkdir(parents=True, exist_ok=True)

    t0 = time.monotonic()
    rx = FrameReceiver(a.frame_port)
    rx.start()
    perc = Perception(a.unstable_root, a.ckpt)
    while rx.latest()[0] is None:
        if time.monotonic() - t0 > 15:
            sys.exit("No camera frames after 15 s; is the sim running with --camera? Not taking off.")
        time.sleep(0.1)
    print(f"camera frames arriving ({rx.latest()[0].shape[1]}x{rx.latest()[0].shape[0]})", flush=True)

    import logging, warnings
    import cflib.crtp
    from cflib.crazyflie import Crazyflie
    from cflib.crazyflie.log import LogConfig
    from cflib.crazyflie.syncCrazyflie import SyncCrazyflie
    global LogConfig_
    LogConfig_ = LogConfig
    logging.basicConfig(level=logging.ERROR)
    warnings.filterwarnings("ignore", category=DeprecationWarning)
    cflib.crtp.init_drivers()

    rel = lambda: time.monotonic() - t0  # noqa: E731
    events, end_reason = {}, "not started"
    faults = Faults(a)
    tel = link = gap8 = None
    try:
        with SyncCrazyflie(a.uri, cf=Crazyflie(rw_cache=str(a.out / "cache"))) as scf:
            cf = scf.cf

            def setp(name, value):
                cf.param.set_value(f"followapp.{name}", str(value))
                time.sleep(0.1)

            def hover(z):
                cf.commander.send_hover_setpoint(0.0, 0.0, 0.0, z)

            setp("enable", 0)
            if a.yaw_sign is not None:
                setp("yawSign", a.yaw_sign)
            if a.arm_fresh is not None:
                setp("armFresh", a.arm_fresh)
            if a.yaw_sign is not None or a.arm_fresh is not None:
                setp("reset", 1)
            tel = Telemetry(cf, t0)
            link = Link(cf.appchannel.send_packet, faults)
            link.start()
            gap8 = Gap8(rx, perc, link, faults, tel, a, t0)
            gap8.start()
            events["packets_start"] = rel()
            faults.t_start = time.monotonic()
            time.sleep(0.5)
            if a.no_fly:
                time.sleep(a.duration)
                end_reason = "no-fly"
            else:
                # 1. Host take-off with hover setpoints (CRTP priority 2). The app is idle: sends nothing.
                events["takeoff"] = rel()
                t_ramp = time.monotonic()
                while (z := 0.4 * (time.monotonic() - t_ramp)) < a.height:
                    hover(z)
                    time.sleep(0.05)
                t_hold = time.monotonic()
                while time.monotonic() - t_hold < 1.0 or time.monotonic() - faults.t_start < a.enable_after:
                    hover(a.height)
                    time.sleep(0.05)
                # 2. Enable the app. It arms when rule 0's warm-up is done and a fresh frame exists, then
                #    commands at COMMANDER_PRIORITY_EXTRX (3) and our priority-2 setpoints are ignored.
                setp("enable", 1)
                events["enable"] = rel()
                t_en = time.monotonic()
                while tel.state() != ACTIVE and time.monotonic() - t_en < 10.0:
                    hover(a.height)
                    time.sleep(0.05)
                if tel.state() != ACTIVE:
                    v = tel.get()
                    end_reason = f"app never took over (state {v.get('state')}, armErr {v.get('armErr')}); host landed"
                    setp("enable", 0)
                    zz = a.height
                    while zz > 0.0:
                        hover(zz)
                        zz -= 0.3 * 0.05
                        time.sleep(0.05)
                    cf.commander.send_stop_setpoint()
                else:
                    # 3. The app flies. The host stops sending setpoints and only watches.
                    faults.t_active = time.monotonic()
                    events["active"] = rel()
                    print(f"app took over at t={events['active']:.2f} s; following for {a.duration:g} s", flush=True)
                    end_reason = "duration: operator land (followapp.enable = 0)"
                    while time.monotonic() - faults.t_active < a.duration:
                        if tel.state() in (LANDING, DONE):
                            v = tel.get()
                            end_reason = (f"app landed on its own (landRsn {v.get('landRsn')}, "
                                          f"reason {REASONS[v.get('reason', 0)]})")
                            break
                        time.sleep(0.02)
                    if tel.state() == ACTIVE:
                        setp("enable", 0)
                    events["land_requested_or_seen"] = rel()
                    t_l = time.monotonic()
                    while tel.state() != DONE and time.monotonic() - t_l < 12.0:
                        time.sleep(0.02)
                    events["done"] = rel() if tel.state() == DONE else None
                    setp("enable", 0)
                time.sleep(2.0)
                v = tel.get()
                events["after_land"] = {"t": rel(), "pz": v.get("pz"), "px": v.get("px"), "py": v.get("py"),
                                        "state": v.get("state")}
                if a.post_land_check:
                    events["post_land_check"] = post_land_check(cf, tel, setp)
            gap8.stop_flag = True
            gap8.join(timeout=2.0)
            time.sleep(0.2)
            link.stop()
            tel.stop()
    except BaseException as e:
        end_reason = f"error: {type(e).__name__}: {e}"
        raise
    finally:
        write_outputs(a, t0, events, end_reason, faults, tel, link, gap8, rx)


def write_outputs(a, t0, events, end_reason, faults, tel, link, gap8, rx):
    def write_csv(path, rows):
        keys = []
        for r in rows:
            for k in r:
                if k not in keys:
                    keys.append(k)
        with open(path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=keys)
            w.writeheader()
            w.writerows(rows)

    app_rows = tel.rows if tel else []
    frame_rows = gap8.rows if gap8 else []
    for r in frame_rows:   # analyze_follow.py scores rows with event "": the app is flying on them
        r["event"] = "" if r.get("app_state") == ACTIVE else f"app-{APP_STATES.get(r.get('app_state'), 'none')}"
    al = events.get("after_land")
    if al:
        frame_rows.append({"t": al["t"], "event": "after-land", "pz": al["pz"], "px": al["px"], "py": al["py"]})
    write_csv(a.out / "follow_log.csv", frame_rows)
    write_csv(a.out / "app_log.csv", app_rows)
    pk = sorted(link.records, key=lambda r: r["seq"]) if link else []
    for r in pk:
        if r.get("t_deliver") is not None:
            r["t_deliver"] -= t0
    write_csv(a.out / "packets.csv", pk)

    steps = [r for r in frame_rows if r.get("event") == ""]
    tracked = [r for r in steps if r["tracking"]]
    act = [r for r in app_rows if r.get("state") == ACTIVE]
    mode_frac = {MODES[m]: round(sum(1 for r in act if r.get("mode") == m) / max(len(act), 1), 3) for m in MODES}
    reasons = [r.get("reason") for r in app_rows]
    stale_events = sum(1 for i in range(1, len(reasons)) if reasons[i] == 5 and reasons[i - 1] != 5)
    fw = [(r["fw_ts"], r["wall"]) for r in app_rows if r.get("fw_ts") is not None]
    gaps = np.diff([r["t_proc"] for r in steps]) * 1000.0 if len(steps) > 1 else np.array([])
    wins = {}
    for name in ("freeze", "stall", "delay", "drop"):
        w = faults.window(name) if faults else None
        if w:
            wins[name] = [w[0] - t0, None if math.isinf(w[1]) else w[1] - t0]
    last = app_rows[-1] if app_rows else {}
    summary = {
        "end_reason": end_reason, "control_steps": len(steps),
        "loop_hz": round((len(steps) - 1) / max(steps[-1]["t_proc"] - steps[0]["t_proc"], 1e-6), 1) if len(steps) > 1 else 0,
        "tracking_fraction": round(len(tracked) / max(len(steps), 1), 3),
        "mean_abs_x_while_tracking": round(float(np.mean([abs(r["x"]) for r in tracked])), 3) if tracked else None,
        "centered_fraction_while_tracking": round(float(np.mean([abs(r["x"]) < 0.25 for r in tracked])), 3) if tracked else None,
        "stale_events": stale_events,
        "z_after_landing": round(al["pz"], 2) if al and al.get("pz") is not None else None,
        "rate_hz_requested": a.rate_hz, "infer_ms_requested": a.infer_ms,
        "frames_processed": gap8.stats["frames_processed"] if gap8 else 0,
        "frames_dropped": gap8.stats["frames_dropped"] if gap8 else 0,
        "torn_frames": rx.info()[1],
        "step_gap_ms": {"min": round(float(gaps.min()), 1), "median": round(float(np.median(gaps)), 1),
                        "max": round(float(gaps.max()), 1)} if len(gaps) else None,
        "sim_wall_ratio": round((fw[-1][0] - fw[0][0]) / 1000.0 / (fw[-1][1] - fw[0][1]), 3)
        if len(fw) > 1 and fw[-1][1] > fw[0][1] else None,
        "app_mode_fraction_while_active": mode_frac,
        "app_max_abs_yaw_rate_dps": round(max((abs(r.get("yawRate") or 0.0) for r in act), default=0.0), 2),
        "app_max_abs_vx_mps": round(max((abs(r.get("vx") or 0.0) for r in act), default=0.0), 3),
        "app_final": {k: last.get(k) for k in ("state", "mode", "reason", "rxApp", "rxRej", "rxStale", "landRsn",
                                                "armErr")},
        "packets": {"built": len(pk), "delivered": sum(1 for r in pk if r.get("t_deliver") is not None),
                    "dropped_by_fault": sum(1 for r in pk if r.get("link") == "dropped"),
                    "held_by_fault": sum(1 for r in pk if r.get("link") in ("stall", "delay", "queued")),
                    "send_errors": sum(1 for r in pk if r.get("send_error"))},
        "gap8": dict(gap8.stats, clock_start_ms=gap8.clock_base_ms) if gap8 else None,
        "fault_windows": wins, "events": events, "args": {k: str(v) for k, v in vars(a).items()},
    }
    (a.out / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps({k: summary[k] for k in ("end_reason", "control_steps", "tracking_fraction", "stale_events",
                                              "z_after_landing", "sim_wall_ratio", "app_mode_fraction_while_active",
                                              "app_final", "packets")}, indent=2))


if __name__ == "__main__":
    main()
