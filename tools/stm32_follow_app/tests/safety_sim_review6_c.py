"""COPY of docs/firmware_integration/safety_sim/safety_sim_review6.py with an STM32 variant "c6"
that runs the portable C controller (tools/stm32_follow_app/follow_controller.c) through ctypes.

Changes to the copied code (everything else is byte-identical to the original):
  * libfp.so is loaded from tests/build/ (built by `make libs` from the GAP8's committed
    inc/follow_packet.h, vendored in tests/vendor/, via tests/fp_shim.c);
  * stm32() additionally records its per-step mode and per-packet rule-0 result (no logic change);
  * new code below "C CONTROLLER VARIANT": stm32_c(), the "c6" branch in simulate_c(), run_case_c(),
    monte_carlo_c(), forced clock wraps, the __main__ sections, and the GROUND timelines (section
    "groundstep", safety review 7): a link-latency step while the drone waits on the ground, take-off
    later (T_ARM moved), where the documented v6 rule arms on late frames;
  * ENTER (the GAP8 model's enter bar) is 0.75, the bar adopted on 2026-09-13 (the original moved
    with it; see the comment at ENTER). FOLLOW_SIM_ENTER in the environment overrides it, e.g.
    FOLLOW_SIM_ENTER=0.7 reproduces the review6-era bar the committed logs were produced at.
"c6" = the GAP8 "fix6" model + the C controller with its default take-off gate (arm_require_fresh=1);
"c6w" = the same C controller with arm_require_fresh=0 (the Python model's take-off: arm at T_ARM
after the warm-up). Every simulation runs the documented Python "v6" rule, c6 and c6w on the SAME
packet deliveries; "diff" compares v6 vs c6 (runs where c6 took off at T_ARM), "diff_w" v6 vs c6w
(every run), step by step.

Original docstring:
Independent review sim of fix round 6 (commit 0623a7d), copy of fw_review5/safety_sim_review5.py.

NEW in review6
  fw="fix6": fix5 PLUS (a) the com.c SPI record: in the com task, at the finalize (after the NINA
    handshake returned, just before the SPI transfer) the C helper follow_packet_frame_ref_us is
    called on the stage-1 packet (have_frame, capture_end_us = ref - age*20 ms), then the COMMITTED C
    follow_packet_finalize_at_tx; a saturated age after it clears have_frame; the record
    (tx_us, frame_us, have_tx=1, have_frame) OVERWRITES the previous one (last packet sent, exactly as
    com_record_app_spi). The record becomes visible to the app task only at t >= t_fin.
    (b) pipeline reconfirm_needed at decode = the fix4/5 checks OR com_app_spi_ages(3.0 s latch):
    tx_age > 0.4 s or frame_age > 0.4 s (UINT32_MAX = none / saturated / latched), with the C latch:
    tx_age > 3.0 s clears both; frame_age > 3.0 s clears the frame.
    (c) packet v6 tracking byte: bit 0 = confirmed, bit 1 = this frame's p >= ENTER; whole byte 0 if
    the frame is older than 0.4 s at the queue attempt (and in no-target packets); com.c finalize clears
    the whole byte on wait > ~80-100 ms or saturation (real C).
  STM32 "v6": v5 (rule 0 + rule 4) with rule 3 = bit 0 clear -> hover and rule 4 counting only fresh
    packets with bit 0 AND bit 1 set. "v5"/"v4+r4" count bit 0 only (an STM32 that ignores bit 1);
    "v4" has no rule 4 at all (pure GAP8 guarantee for P2).
  New GAP8-level checks: G4 bit1 => frame p >= ENTER (0.75) and frame <= 0.4 s old at the queue attempt;
    G5 reserved bits 2..7 == 0; G6 bit1 after finalize => wait <= 100 ms and true age at SPI <= 0.5 s;
    G7 com.c record frame_us == the frame's capture_end (exact recovery), have_frame=0 for age 255.

Original header (review5):
Independent review sim of fix round 5 (commit 6c4b119) vs fix round 4 (6dbd8dc).
Extended copy of fw_review4/safety_sim_review4.py (integer microseconds, uint32 clocks).

NEW in review5
  fw="fix5": GAP8 as fix4 (non-blocking TX, 0.4 s re-confirm incl. TX gap, age stamped at
    the queue attempt) PLUS the com.c finalization: stage 1 puts ref_us =
    capture_end + age*20 ms (or now_us when no ref) into gap8_tx_ms; stage 2 runs in the
    com task AFTER the NINA handshake returns and BEFORE the SPI transfer, calling the
    COMMITTED C function follow_packet_finalize_at_tx (inc/follow_packet.h, compiled to
    libfp.so and called through ctypes), with the GAP8 us clock and the GAP8 ms tick clock.
    Console packets are untouched (they carry no follow payload in the model).
  STM32 "v5": documented rule 0 (docs/champion_integration.md, HANDOFF s3):
    s = t_rx_ms - gap8_tx_ms (uint32), off = min of s over a ring of ten 1 s minima
    (current packet included), e = s - off; warm-up: every packet stale until the window
    spans 2 s of packets; reset on frame_id backwards or |s - s_prev| > 10 s (re-arms rule 4);
    age 255 -> t_fresh NONE whatever e; e > 100 ms -> stale (t_fresh unchanged, rule-4 count
    restarts, never steers); else t_fresh = t_rx - e - age*20 ms. Rules 1-4 as v4 with
    rule 4 also requiring e <= 0.1 s. STM32 ms clock has its own offset and drift (+-200 ppm).
  GAP8-level checks per transmitted app packet (independent of any STM32 rule):
    G1 age at SPI never fresher than the truth (and exact below saturation)
    G2 wait (queue attempt -> SPI) > 100 ms => tracking 0
    G3 tracking 1 => true frame age at SPI <= 0.5 s (0.4 s attempt bound + 0.1 s wait bound)
Truth properties (as review4):
  P1 land <= last valid frame + 3.0 s + one step + small link delay (TOL_L)
  P2 steering resumes after a stale-hover step only after 3 consecutive fresh p>=ENTER (0.75) frames
  P3 never steer on a frame truly older than 0.5 s (+ step + TOL_L)
"""
import ctypes
import os
import random
from collections import deque

US = 1_000_000
U32 = 1 << 32
UNIT, SAT = 20000, 255
HOVER, LAND, STEP = 500_000, 3_000_000, 10_000
RECONF = 400_000
TX_MAX_WAIT = 100_000
# ENTER is the GAP8 model's enter bar: 0.75 since 2026-09-13 (docs/firmware_contract.md; raw 5467
# for the champion, was 0.7 / 4216), the same value the original safety_sim_review6.py now uses.
# The p values in this simulator are synthetic uniform draws, not the network's. The committed
# review6 logs (docs/firmware_integration/safety_sim/logs, the regression baseline
# summarize_results.py checks against) were produced at 0.7; the py_v6 statistics that check
# compares (land ranges, violations, max steered age, never_landed, runs) came out identical at
# 0.7 and 0.75 on the sim-quick set (22 timelines x 40 runs + MC orig x 100, 2026-09-13).
# FOLLOW_SIM_ENTER=0.7 in the environment reproduces the old bar.
ENTER = float(os.environ.get("FOLLOW_SIM_ENTER", "0.75"))
EXIT, CONFIRM = 0.45, 3
CAP, INF, TIMEOUT = 30_000, 30_000, 500_000
POST = 50            # decode + packet build, us
XFER_HS = 100        # NINA handshake when the link is up
XFER_SPI = 100       # SPI transfers after the finalization
XFER = XFER_HS + XFER_SPI
ESP_MAX = 5_000
TXQ = 80
T_ARM = 3_000_000    # arm after the 2 s rule-0 warm-up (see report: arming during warm-up lands)
QUANT = 2_000        # ms-clock quantization of s (two floors)
TOL_L = ESP_MAX + XFER + QUANT
SUMMARY_EVERY = 10
E_STALE_MS = 100
WIN_BUCKETS = 10
WARM_MS = 2000

_HERE = os.path.dirname(os.path.abspath(__file__))
_lib = ctypes.CDLL(os.path.join(_HERE, "build", "libfp.so"))  # c6 copy: built by `make libs`
_lib.fp_finalize.argtypes = [ctypes.c_char_p, ctypes.c_uint32, ctypes.c_uint32]
_lib.fp_ref.argtypes = [ctypes.c_uint32, ctypes.c_uint8]
_lib.fp_ref.restype = ctypes.c_uint32
_lib.fp_frame_ref.argtypes = [ctypes.c_char_p, ctypes.POINTER(ctypes.c_uint32)]
_lib.fp_frame_ref.restype = ctypes.c_int
assert _lib.fp_version() == 6
assert _lib.fp_sizeof() == 28 and _lib.fp_off_age() == 19 and _lib.fp_off_tx() == 24 and _lib.fp_off_trk() == 16


def c_finalize(age, trk, ref_us, now_us, now_ms):
    """Call the committed follow_packet_finalize_at_tx on a real 28-byte packet."""
    b = bytearray(28)
    b[0], b[1] = 0xA5, 0x06
    b[16] = trk
    b[19] = age
    b[24:28] = (ref_us % U32).to_bytes(4, "little")
    buf = ctypes.create_string_buffer(bytes(b), 28)
    _lib.fp_finalize(buf, now_us % U32, now_ms % U32)
    out = buf.raw
    return out[19], out[16], int.from_bytes(out[24:28], "little")


def c_frame_ref(age, ref_us):
    """follow_packet_frame_ref_us on a stage-1 packet (C)."""
    b = bytearray(28)
    b[0], b[1] = 0xA5, 0x06
    b[19] = age
    b[24:28] = (ref_us % U32).to_bytes(4, "little")
    out = ctypes.c_uint32(0)
    have = _lib.fp_frame_ref(bytes(b), ctypes.byref(out))
    return have, out.value


def sgn32(x):
    x %= U32
    return x - U32 if x >= (1 << 31) else x


def frame_age(age_us):
    age_us %= U32
    units = age_us // UNIT + (1 if age_us % UNIT else 0)
    return SAT if units >= SAT else units


class Link:
    def __init__(self, rng, outages=(), console=True):
        self.rng = rng
        self.out = list(outages)   # (kind, t0, t1[, extra])
        self.q = []                # [t_enq, pkt]
        self.free = 0
        self.deliv = []
        self.last_rx = 0
        self.esp_n = {}
        self.console = console
        self.on_tx = None          # GAP8 hook: finalization at the SPI moment
    def nina_up(self, t):
        for o in self.out:
            if o[0] == "nina" and o[1] <= t < o[2]:
                return o[2]
        return t
    def esp_hold(self, t):
        for o in self.out:
            if o[0] == "esp" and o[1] <= t < o[2]:
                return o[2]
        return None
    def extra_lat(self, t):
        return sum(o[3] for o in self.out if o[0] == "lat" and o[1] <= t < o[2])
    def advance(self, t):
        while self.q:
            t_enq, pkt = self.q[0]
            take = max(self.free, t_enq)
            if take > t:
                break
            self.q.pop(0)
            t_fin = self.nina_up(take) + XFER_HS      # handshake returned
            done = t_fin + XFER_SPI
            self.free = done
            if pkt is None:
                continue
            pkt["t_take"], pkt["t_fin"] = take, t_fin
            if self.on_tx is not None:
                self.on_tx(pkt, t_fin)
            hold = self.esp_hold(done)
            if hold is not None:
                self.esp_n[hold] = self.esp_n.get(hold, 0) + 1
                arr = hold + 1000 * self.esp_n[hold]
            else:
                arr = done + int(self.rng.uniform(0, ESP_MAX)) + self.extra_lat(done)
            arr = max(arr, self.last_rx)
            self.last_rx = arr
            self.deliv.append((arr, pkt))
    def count(self, t):
        self.advance(t)
        return len(self.q)
    def enqueue(self, t, pkt):
        self.q.append([t, pkt])
        self.advance(t)
    def space_at(self, t):
        self.advance(t)
        while len(self.q) >= TXQ:
            t_enq, pkt = self.q[0]
            nxt = max(self.free, t_enq)
            t = max(t, nxt)
            self.advance(t)
        return t
    def flush(self):
        self.advance(1 << 62)


class Gap8:
    def __init__(self, scen, t_end, link, fw, tx=True, clk_off=0, ms_off=0):
        self.scen, self.t_end, self.link, self.fw, self.tx_on = scen, t_end, link, fw, tx
        self.off = clk_off          # pi_time_get_us offset
        self.ms_off = ms_off        # FreeRTOS tick offset (us units, same crystal)
        self.have_good, self.last_good, self.last_good_c = False, 0, None
        self.trk, self.streak = 0, 0
        self.tx_once, self.last_tx = False, 0
        self.frames = []
        self.drops = 0
        self.resets = 0
        self.camframe = 0
        self.g = {}                 # GAP8-level check violations
        self.g_first = None
        self.ntx = 0
        self.spi = dict(have_tx=0, have_frame=0, tx_us=0, frame_us=0)   # com.c g_app_spi
        self.spi_pend = []          # records written by the com task at t_fin (in order)
        self.spi_resets = 0
        link.on_tx = self.on_tx
    def clk(self, t):
        return (t + self.off) % U32
    def ms(self, t):
        return ((t + self.ms_off) // 1000) % U32
    def reset(self):
        self.trk, self.streak = 0, 0
    def tx_gap(self, t):
        if not self.tx_on:
            return 0
        if not self.tx_once:
            return U32 - 1
        g = (self.clk(t) - self.last_tx) % U32
        if g > LAND:
            self.tx_once = False
            return U32 - 1
        return g
    def spi_ages(self, t):
        """com_app_spi_ages(APP_STM32_STALE_LAND_US) read at t (app task, critical section)."""
        keep = []
        for rec in self.spi_pend:
            if rec[0] <= t:
                _, tx_us, hf, fu = rec
                self.spi.update(tx_us=tx_us, frame_us=fu, have_frame=1 if hf else 0, have_tx=1)
            else:
                keep.append(rec)
        self.spi_pend = keep
        now = self.clk(t)
        sp = self.spi
        tx_age = frame_age_v = U32 - 1
        if sp["have_tx"]:
            tx_age = (now - sp["tx_us"]) % U32
            if tx_age > LAND:
                sp["have_tx"] = 0; sp["have_frame"] = 0; tx_age = U32 - 1
        if sp["have_frame"]:
            frame_age_v = (now - sp["frame_us"]) % U32
            if frame_age_v > LAND:
                sp["have_frame"] = 0; frame_age_v = U32 - 1
        return tx_age, frame_age_v
    def gviol(self, k, info):
        self.g[k] = self.g.get(k, 0) + 1
        if self.g_first is None:
            self.g_first = (k, info)
    def on_tx(self, pkt, t_fin):
        """com.c: after the NINA handshake, before the SPI transfer."""
        self.ntx += 1
        if self.fw == "fix6":
            have_frame, frame_us = c_frame_ref(pkt["age"], pkt["ref"])
            c = pkt["c_ref"]
            if have_frame and (c is None or frame_us != self.clk(c)):
                self.gviol("G7_record_frame_inexact", (round(t_fin / US, 3), frame_us, c))
            if (not have_frame) and pkt["age"] != SAT:
                self.gviol("G7_record_no_frame", (round(t_fin / US, 3), pkt["age"]))
        if self.fw in ("fix5", "fix6"):
            age, trk, gtx = c_finalize(pkt["age"], pkt["trk"], pkt["ref"], self.clk(t_fin), self.ms(t_fin))
            assert gtx == self.ms(t_fin)
            pkt["age"], pkt["trk"], pkt["gtx"] = age, trk, gtx
        if self.fw == "fix6":
            if pkt["age"] >= SAT:
                have_frame = 0
            self.spi_pend.append((t_fin, self.clk(t_fin), have_frame, frame_us))
        # GAP8-level checks (what leaves the GAP8), all firmwares
        wait = t_fin - pkt["t_stamp"]
        c = pkt["c_ref"]
        if c is not None:
            true_age = t_fin - c
            if pkt["age"] != SAT and pkt["age"] * UNIT < true_age:
                self.gviol("G1_fresher", (round(t_fin / US, 3), pkt["age"], true_age))
            elif pkt["age"] != SAT and pkt["age"] != frame_age(true_age) and self.fw in ("fix5", "fix6"):
                self.gviol("G1_inexact", (round(t_fin / US, 3), pkt["age"], true_age))
            if (pkt["trk"] & 1) and true_age > HOVER:
                self.gviol("G3_trk1_older_0.5s", (round(t_fin / US, 3), true_age))
            if (pkt["trk"] & 2) and true_age > HOVER:
                self.gviol("G6_bit1_older_0.5s", (round(t_fin / US, 3), true_age))
        if (pkt["trk"] & 1) and wait > TX_MAX_WAIT:
            self.gviol("G2_trk1_wait>100ms", (round(t_fin / US, 3), wait))
        if (pkt["trk"] & 2) and wait > TX_MAX_WAIT:
            self.gviol("G6_bit1_wait>100ms", (round(t_fin / US, 3), wait))
        if pkt["trk"] & 0xFC:
            self.gviol("G5_reserved_bits", (round(t_fin / US, 3), pkt["trk"]))
        if pkt["trk"] & 2:
            ev = pkt["ev"]
            if ev["kind"] != "ok" or ev["p"] < ENTER or (pkt["t_stamp"] - ev["c"]) > RECONF:
                self.gviol("G4_bit1_not_fresh_p07", (round(t_fin / US, 3), ev["kind"], ev["p"]))
    def send(self, t, pkt):
        if not self.tx_on:
            return t
        if self.fw == "head":
            t2 = self.link.space_at(t)
            self.link.enqueue(t2, pkt)
            return t2
        if self.link.count(t) > 0:
            self.drops += 1
            pkt["dropped"] = True
            return t
        self.link.enqueue(t, pkt)
        self.last_tx, self.tx_once = self.clk(t), True
        return t
    def console_line(self, t):
        if self.tx_on and self.link.console:
            t2 = self.link.space_at(t)
            self.link.enqueue(t2, None)
            return t2
        return t
    def gap(self, t):
        self.reset()
        if self.have_good and frame_age(self.clk(t) - self.last_good) == SAT:
            self.have_good = False
        t_s = t + POST
        age = frame_age(self.clk(t_s) - self.last_good) if self.have_good else SAT
        ref = _lib.fp_ref(self.last_good, age) if self.have_good else self.clk(t_s)
        ev = dict(kind="gap", c=None, d=t, p=None)
        pkt = dict(t_stamp=t_s, trk=0, age=age, ref=ref, ev=ev, idx=len(self.frames), fid=len(self.frames),
                   c_ref=self.last_good_c if self.have_good else None)
        ev["pkt"] = pkt
        self.frames.append(ev)
        return self.send(t_s, pkt)
    def process(self, c, inf, p):
        t_dec = c + inf
        ev = dict(kind="ok", c=c, d=t_dec, p=p)
        if self.fw in ("fix4", "fix5", "fix6"):
            need = ((not self.have_good) or
                    ((self.clk(t_dec) - self.last_good) % U32) > RECONF or
                    self.tx_gap(t_dec) > RECONF)
            if self.fw == "fix6" and not need and self.tx_on:
                self.link.advance(t_dec)          # the com task runs concurrently
                sg, sf = self.spi_ages(t_dec)
                if sg > RECONF or sf > RECONF:
                    need = True; self.spi_resets += 1
            if need:
                self.reset(); self.resets += 1
        self.streak = min(self.streak + 1, CONFIRM) if p >= ENTER else 0
        if self.trk and p < EXIT:
            self.trk = 0
        elif not self.trk and self.streak >= CONFIRM:
            self.trk = 1
        trk = self.trk
        t_s = t_dec + POST
        if self.fw == "fix6":
            trk = (1 if trk else 0) | (2 if p >= ENTER else 0)
        if self.fw in ("fix4", "fix5", "fix6"):
            if (t_s - c) > RECONF:
                self.reset(); trk = 0; self.resets += 1
        age = frame_age(self.clk(t_s) - self.clk(c))
        pkt = dict(t_stamp=t_s, trk=trk, age=age, ref=_lib.fp_ref(self.clk(c), age), ev=ev,
                   idx=len(self.frames), fid=len(self.frames), c_ref=c)
        ev["pkt"] = pkt
        self.frames.append(ev)
        t = self.send(t_s, pkt)
        self.have_good, self.last_good, self.last_good_c = True, self.clk(c), c
        self.camframe += 1
        if self.camframe % SUMMARY_EVERY == 0:
            t = self.console_line(t)
        return t
    def run(self):
        t = 0
        while t < self.t_end:
            kind, arg = self.scen(t)
            if kind == "hang":
                return
            if kind == "stall":
                t += int(arg * US); continue
            if kind == "stall_inflight":
                s, p = arg
                c = t + CAP
                t = self.process(c, max(INF, int(s * US) - CAP + INF), p)
                continue
            if kind == "timeout":
                t = self.gap(t + TIMEOUT + 100); continue
            if kind == "slow":
                inf_s, p = arg
                t = self.process(t + CAP, int(inf_s * US), p); continue
            if kind == "fail":
                t = self.gap(t + CAP + INF); continue
            t = self.process(t + CAP, INF, arg)


class Rule0:
    """Documented STM32 rule 0 (v5)."""
    def __init__(self, drift_ppm=0.0, s_off=0):
        self.drift, self.s_off = drift_ppm * 1e-6, s_off
        self.reset()
        self.resets = 0
    def reset(self):
        self.buckets = deque()      # (bucket_idx, min s_rel)
        self.anchor = None
        self.start_ms = None
        self.prev_s = None
        self.prev_fid = None
    def stm_ms(self, t):
        return int((t * (1 + self.drift) + self.s_off) // 1000) % U32
    def sample(self, t_rx, gtx, fid):
        """Returns (e_ms, stale_by_rule0, window_reset)."""
        now_ms = self.stm_ms(t_rx)
        s = (now_ms - gtx) % U32
        wreset = False
        if self.prev_fid is not None and (fid < self.prev_fid or abs(sgn32(s - self.prev_s)) > 10_000):
            self.reset(); self.resets += 1; wreset = True
        self.prev_s, self.prev_fid = s, fid
        if self.anchor is None:
            self.anchor, self.start_ms = s, now_ms
        s_rel = sgn32(s - self.anchor)
        b = t_rx // US          # 1 s buckets (STM32 local time)
        while self.buckets and self.buckets[0][0] <= b - WIN_BUCKETS:
            self.buckets.popleft()
        if self.buckets and self.buckets[-1][0] == b:
            self.buckets[-1] = (b, min(self.buckets[-1][1], s_rel))
        else:
            self.buckets.append((b, s_rel))
        off = min(m for _, m in self.buckets)
        e = s_rel - off
        warm = sgn32(now_ms - self.start_ms) < WARM_MS
        return e, (e > E_STALE_MS or warm), wreset


def stm32(deliv, frames, t_end, rule4, rule0=None, bit1=False):
    t_fresh, landed, land_t = None, False, None
    newest, newest_st0 = None, False
    i, n = 0, len(deliv)
    stale_seen = None
    need, cnt = True, 0
    mode_prev = None
    res = dict(v=[], land_t=None, steer_max=0, resumes=[], p3=0, st0=0, modes=[], pk=[])  # c6 copy: +modes, pk
    valid_c = sorted(f["c"] for f in frames if f["kind"] == "ok")
    vi, lv = 0, None
    now = 0
    while now < t_end:
        now += STEP
        while vi < len(valid_c) and valid_c[vi] <= now:
            lv = valid_c[vi]; vi += 1
        while i < n and deliv[i][0] <= now:
            t_rx, pkt = deliv[i]; i += 1
            newest = pkt
            st0, e = False, 0
            if rule0 is not None:
                e, st0, wr = rule0.sample(t_rx, pkt["gtx"], pkt["fid"])
                if wr:
                    need, cnt = True, 0
                res["st0"] += st0
                res["pk"].append((e, st0, wr))  # c6 copy: record only
            if pkt["age"] == SAT:
                t_fresh = None
            elif not st0:
                t_fresh = t_rx - e * 1000 - pkt["age"] * UNIT
            newest_st0 = st0
            if rule4:
                need_bits = 3 if bit1 else 1
                cnt = cnt + 1 if ((pkt["trk"] & need_bits) == need_bits and pkt["age"] != SAT and pkt["age"] * UNIT <= HOVER
                                  and not st0) else 0
        if now < T_ARM:
            continue
        stale = t_fresh is None or now - t_fresh > HOVER
        if landed:
            mode = "land"
        elif t_fresh is None or now - t_fresh > LAND:
            landed, land_t, mode = True, now, "land"
        elif stale:
            mode = "hover"
        elif (newest["trk"] & 1) == 0:
            mode = "hover"
        elif newest_st0:
            mode = "hover"
        elif rule4 and need and cnt < CONFIRM:
            mode = "hover"
        else:
            need = False
            mode = "steer"
        if stale:
            stale_seen = now
            if rule4:
                need, cnt = True, 0
        if lv is not None and not landed and now - lv > LAND + TOL_L + STEP:
            res["v"].append(("P1", now, now - lv))
        if mode == "steer":
            age = now - newest["ev"]["c"]
            res["steer_max"] = max(res["steer_max"], age)
            if age > HOVER + STEP + TOL_L:
                res["v"].append(("P3", now, age)); res["p3"] += 1
        if mode == "steer" and mode_prev != "steer" and stale_seen is not None and mode_prev is not None:
            ok, run = p2_ok(frames, newest["idx"], stale_seen)
            res["resumes"].append((now, run))
            if not ok:
                res["v"].append(("P2", now, run))
        res["modes"].append(mode)  # c6 copy: record only
        mode_prev = mode
    res["land_t"] = land_t
    return res


def p2_ok(frames, k, t_stale):
    def fresh_after(f):
        if f["kind"] != "ok":
            return False
        pk = f["pkt"]
        use = pk.get("t_rx") if not pk.get("dropped") else f["d"]
        if use is None:
            use = f["d"]
        return use >= t_stale and (use - f["c"]) <= HOVER + TOL_L
    j = k
    run = 0
    best = 0
    while j >= 0 and fresh_after(frames[j]) and frames[j]["p"] >= EXIT:
        if frames[j]["p"] >= ENTER:
            run += 1
            best = max(best, run)
            if run >= CONFIRM:
                return True, run
        else:
            run = 0
        j -= 1
    return False, best


STM = {"v4": (False, False, False), "v4+r4": (True, False, False), "v5": (True, True, False),
       "v6": (True, True, True)}


def simulate(scen, t_end, fw, stm, rng, outages=(), tx=True, clk_off=0, ms_off=0, drift=0.0, s_off=0):
    link = Link(rng, outages)
    g = Gap8(scen, t_end, link, fw, tx, clk_off, ms_off)
    g.run()
    link.flush()
    for t_rx, pkt in link.deliv:
        pkt["t_rx"] = t_rx
    r4, r0, b1 = STM[stm]
    rule0 = Rule0(drift, s_off) if r0 else None
    r = stm32(link.deliv, g.frames, t_end - 100_000, r4, rule0, b1)
    lat = max((t_rx - p["t_stamp"] for t_rx, p in link.deliv), default=0)
    return g, link, r, lat


def last_valid(frames, t):
    cs = [f["c"] for f in frames if f["kind"] == "ok" and f["c"] <= t]
    return cs[-1] if cs else None


P = 0.95
F0 = 10 * US
def ok(t): return ("ok", P)
def once(f0, first, rest=ok):
    st = {"d": False}
    def f(t):
        if t >= f0 and not st["d"]:
            st["d"] = True; return first
        return rest(t)
    return f
def during(f0, dur, act):
    return lambda t: act if f0 <= t < f0 + dur else ("ok", P)
def hang_after(f0):
    return lambda t: ("hang", None) if t >= f0 else ("ok", P)
def every(f0, per, dur):
    st = {"n": f0 + per}
    def f(t):
        if f0 <= t < f0 + dur:
            if t >= st["n"]:
                st["n"] += per; return ("ok", P)
            return ("fail", None)
        return ("ok", P)
    return f


def rand_clocks(rng):
    return dict(clk_off=rng.randrange(U32), ms_off=rng.randrange(U32) * 1000,
                drift=rng.uniform(-200, 200), s_off=rng.randrange(U32) * 1000)


def run_case(name, mk, runs, t_end_s, fw, stm, outages_rel=(), seed=1):
    rng = random.Random(seed)
    T = int(t_end_s * US)
    lands, viol, resumes, never, steer_max, lats, drops = [], [], [], 0, 0, [], 0
    kinds, gk, gfirst = {}, {}, None
    for _ in range(runs):
        f0 = F0 + int(rng.uniform(0, 60_000))
        outs = [(o[0], f0 + int(o[1] * US), f0 + int(o[2] * US)) + tuple(o[3:]) for o in outages_rel]
        g, link, r, lat = simulate(mk(f0), T, fw, stm, rng, outs, **rand_clocks(rng))
        for v in r["v"]:
            kinds[v[0]] = kinds.get(v[0], 0) + 1
        for k, c in g.g.items():
            gk[k] = gk.get(k, 0) + c
        gfirst = gfirst or g.g_first
        viol += r["v"]
        steer_max = max(steer_max, r["steer_max"])
        lats.append(lat); drops += g.drops
        if r["land_t"] is None:
            never += 1
        else:
            lands.append(r["land_t"] - last_valid(g.frames, r["land_t"]))
        resumes += [x for x in r["resumes"] if x[0] >= f0]
    return dict(case=name, fw=fw, stm32=stm, runs=runs,
                land_after_last_valid_s=(round(min(lands) / US, 3), round(max(lands) / US, 3)) if lands else None,
                never_landed=never, max_link_latency_s=round(max(lats) / US, 3),
                resumes=len(resumes), min_run_at_resume=min((x[1] for x in resumes), default=None),
                max_true_age_steered_s=round(steer_max / US, 3), tx_drops=drops,
                violations=kinds, gap8_checks=gk,
                first=(viol[0][0], round(viol[0][1] / US, 3), round(viol[0][2] / US, 3) if viol[0][0] != "P2" else viol[0][2]) if viol else None,
                g_first=gfirst)


def monte_carlo(fw, stm, runs=500, seed=7, mix="orig", link_out=False, esp_out=False):
    rng = random.Random(seed)
    kinds, gk, lands, steer_max = {}, {}, [], 0
    for k in range(runs):
        segs, t = [], 2.0
        choices = ["ok", "ok", "fail", "timeout", "mixed", "lowp"]
        if mix == "ext":
            choices += ["stall", "slow", "inflight"]
        while t < 40:
            kind = rng.choice(choices)
            d = rng.uniform(0.05, 5.0)
            segs.append((t, t + d, kind)); t += d
        hang_at = rng.choice([None, rng.uniform(5, 40)])
        outs = []
        if link_out:
            for _ in range(rng.randint(1, 4)):
                a = rng.uniform(3, 40); outs.append(("nina", int(a * US), int((a + rng.uniform(0.05, 2.5)) * US)))
        if esp_out:
            for _ in range(rng.randint(1, 3)):
                a = rng.uniform(3, 40); outs.append(("esp", int(a * US), int((a + rng.uniform(0.05, 2.5)) * US)))
        def scen(tt, segs=segs, hang_at=hang_at, r=random.Random(rng.random())):
            ts = tt / US
            if hang_at is not None and ts >= hang_at:
                return ("hang", None)
            for a, b, kind in segs:
                if a <= ts < b:
                    if kind == "ok": return ("ok", r.uniform(0.6, 1.0))
                    if kind == "lowp": return ("ok", r.uniform(0.0, 0.8))
                    if kind == "fail": return ("fail", None)
                    if kind == "timeout": return ("timeout", None)
                    if kind == "stall": return r.choice([("stall", r.uniform(0.1, 2.0)), ("ok", r.uniform(0.6, 1.0))])
                    if kind == "slow": return ("slow", (r.uniform(0.03, 0.8), r.uniform(0.6, 1.0)))
                    if kind == "inflight": return r.choice([("stall_inflight", (r.uniform(0.1, 2.0), r.uniform(0.6, 1.0))), ("ok", r.uniform(0.6, 1.0))])
                    return r.choice([("ok", r.uniform(0.3, 1.0)), ("fail", None), ("timeout", None)])
            return ("ok", 0.95)
        g, link, r, lat = simulate(scen, 45 * US, fw, stm, rng, outs, **rand_clocks(rng))
        for v in r["v"]:
            kinds[v[0]] = kinds.get(v[0], 0) + 1
        for kk, c in g.g.items():
            gk[kk] = gk.get(kk, 0) + c
        steer_max = max(steer_max, r["steer_max"])
        if r["land_t"] is not None:
            lands.append(r["land_t"] - last_valid(g.frames, r["land_t"]))
    return dict(mc=mix + ("+nina_outages" if link_out else "") + ("+esp_outages" if esp_out else ""),
                fw=fw, stm32=stm, runs=runs, landed=len(lands),
                land_after_last_valid_s=(round(min(lands) / US, 3), round(max(lands) / US, 3)) if lands else None,
                max_true_age_steered_s=round(steer_max / US, 3), violations=kinds, gap8_checks=gk)


def finalize_crosscheck(n=300_000, seed=11):
    """Python spec of the finalize vs the compiled C (exactness + wrap)."""
    rng = random.Random(seed)
    bad = 0
    for _ in range(n):
        c = rng.randrange(U32)
        a0 = rng.randrange(0, 150)
        age = frame_age(a0 * 7919 % 400_000)
        ref = _lib.fp_ref(c, age)
        wait = rng.choice([rng.randrange(0, 200_000), rng.randrange(0, 6_000_000), rng.randrange(0, 60_000)])
        t_attempt = (c + rng.randrange(0, 400_001)) % U32
        age = frame_age(t_attempt - c)
        ref = _lib.fp_ref(c, age)
        now = (t_attempt + wait) % U32
        trk0 = rng.randrange(2)
        a, trk, _ = c_finalize(age, trk0, ref, now, 0)
        true_age = (now - c) % U32
        exp = frame_age(true_age)
        if a != exp:
            bad += 1
        if wait > TX_MAX_WAIT and trk == 1:
            bad += 1
        if wait <= 80_000 and trk != trk0 and exp != SAT:
            bad += 1
    return dict(cases=n, failures=bad)


def byte_crosscheck(n=300_000, seed=12):
    """v6: finalize with every tracking byte value; frame-ref recovery (C) is exact."""
    rng = random.Random(seed)
    bad = 0
    for _ in range(n):
        c = rng.randrange(U32)
        t_attempt = (c + rng.randrange(0, 6_000_000)) % U32
        age = frame_age(t_attempt - c)
        ref = _lib.fp_ref(c, age)
        have, fu = c_frame_ref(age, ref)
        if age != SAT and (not have or fu != c):
            bad += 1
        if age == SAT and have:
            bad += 1
        wait = rng.choice([rng.randrange(0, 200_000), rng.randrange(0, 60_000)])
        byte0 = rng.randrange(4)
        a, trk, _ = c_finalize(age, byte0, ref, (t_attempt + wait) % U32, 0)
        if (wait > TX_MAX_WAIT or a == SAT) and trk != 0:
            bad += 1
        if wait <= 80_000 and a != SAT and trk != byte0:
            bad += 1
        if trk not in (0, byte0):
            bad += 1
    for conf in (0, 1, 5):
        for vis in (0, 1, 7):
            exp = (1 if conf else 0) | (2 if vis else 0)
            if _lib.fp_trk_byte(conf, vis) != exp:
                bad += 1
            b = bytearray(28); b[16] = exp
            if _lib.fp_is_confirmed(bytes(b)) != (exp & 1) or _lib.fp_counts(bytes(b)) != (1 if exp == 3 else 0):
                bad += 1
    return dict(cases=n, failures=bad)


TIMELINES = [
    ("(a) camera outage 10 s", lambda f0: during(f0, 10 * US, ("timeout", None)), 30.0, ()),
    ("(b) inference fails every frame 10 s", lambda f0: during(f0, 10 * US, ("fail", None)), 30.0, ()),
    ("(c) GAP8 hangs", hang_after, 30.0, ()),
    ("(d) 1 good frame / 2 s among failures 20 s", lambda f0: every(f0, 2 * US, 20 * US), 35.0, ()),
    ("(d') 1 good frame / 3.5 s among failures 20 s", lambda f0: every(f0, int(3.5 * US), 20 * US), 35.0, ()),
    ("(e) single failed frame", lambda f0: once(f0, ("fail", None)), 30.0, ()),
    ("(x1) GAP8 main-loop stall 1.5 s then recovery", lambda f0: once(f0, ("stall", 1.5)), 30.0, ()),
    ("(x1b) stall 1.5 s with a capture completed during it", lambda f0: once(f0, ("stall_inflight", (1.5, P))), 30.0, ()),
    ("(x2) NINA/CPX stall 2.0 s", lambda f0: ok, 30.0, [("nina", 0.0, 2.0)]),
    ("(x2b) NINA stall 0.5 s", lambda f0: ok, 30.0, [("nina", 0.0, 0.5)]),
    ("(x2c) NINA stall 0.6 s", lambda f0: ok, 30.0, [("nina", 0.0, 0.6)]),
    ("(x2d) NINA stall 0.3 s", lambda f0: ok, 30.0, [("nina", 0.0, 0.3)]),
    ("(x2n) NINA stall 0.09 s (below the 100 ms bound)", lambda f0: ok, 30.0, [("nina", 0.0, 0.09)]),
    ("(x3) NINA stall 1.0 s, GAP8 hangs 0.1 s in", lambda f0: hang_after(f0 + 100_000), 30.0, [("nina", 0.0, 1.0)]),
    ("(x3b) NINA stall 2.0 s, GAP8 hangs 0.1 s in", lambda f0: hang_after(f0 + 100_000), 30.0, [("nina", 0.0, 2.0)]),
    ("(x3c) NINA stall 2.9 s, GAP8 hangs 0.1 s in", lambda f0: hang_after(f0 + 100_000), 30.0, [("nina", 0.0, 2.9)]),
    ("(x2e) ESP32-internal stall 2.0 s (GAP8 sees success)", lambda f0: ok, 30.0, [("esp", 0.0, 2.0)]),
    ("(x2f) ESP32-internal stall 0.3 s", lambda f0: ok, 30.0, [("esp", 0.0, 0.3)]),
    ("(x2g) ESP32-internal stall 0.09 s", lambda f0: ok, 30.0, [("esp", 0.0, 0.09)]),
    ("(x3d) ESP32 stall 1.0 s, GAP8 hangs 0.1 s in", lambda f0: hang_after(f0 + 100_000), 30.0, [("esp", 0.0, 1.0)]),
    ("(x3e) ESP32 stall 2.9 s, GAP8 hangs 0.1 s in", lambda f0: hang_after(f0 + 100_000), 30.0, [("esp", 0.0, 2.9)]),
    ("(x2h) RESIDUAL: +0.3 s ESP32 latency held 15 s, 0.3 s GAP8 stall at 12 s",
     lambda f0: once(f0 + 12 * US, ("stall", 0.3)), 30.0, [("lat", 0.0, 15.0, 300_000)]),
]
BASE = [("fix5", "v5"), ("fix6", "v4"), ("fix6", "v4+r4"), ("fix6", "v5"), ("fix6", "v6")]
MIXES = (("orig", False, False), ("ext", False, False), ("orig", True, False), ("ext", True, False), ("orig", True, True))


# ====================================================================================================
# C CONTROLLER VARIANT (c6)
# ====================================================================================================
import struct

_ctl = ctypes.CDLL(os.path.join(_HERE, "build", "libfollowctl.so"))
_ctl.fcs_create.restype = ctypes.c_void_p
_ctl.fcs_create.argtypes = [ctypes.c_float, ctypes.c_int]
_ctl.fcs_free.argtypes = [ctypes.c_void_p]
_ctl.fcs_on_packet.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint, ctypes.c_uint,
                               ctypes.POINTER(ctypes.c_uint), ctypes.POINTER(ctypes.c_int)]
_ctl.fcs_arm.argtypes = [ctypes.c_void_p, ctypes.c_uint]
_ctl.fcs_step.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.POINTER(ctypes.c_float),
                          ctypes.POINTER(ctypes.c_float), ctypes.POINTER(ctypes.c_float), ctypes.POINTER(ctypes.c_int)]
C_MODE = {0: "wait", 1: "hover", 2: "steer", 3: "land"}
# follow_reason_t values that mean "a control step in rule 1 or 2" (the Python model's `stale`)
C_STALE_REASONS = {2, 3, 4, 5}   # LAND_LATCHED, LAND_STALE, LAND_NO_FRAME, HOVER_STALE


def pkt_bytes(pkt):
    """The 28-byte v6 packet the GAP8 model's packet dict stands for (x/size do not affect safety)."""
    trk = pkt["trk"]
    conf = trk & 1
    b = struct.pack("<BBHIffBBBBiI", 0xA5, 6, 24, pkt["fid"] % U32, 0.3 if conf else 0.0, 0.5 if conf else 0.0,
                    trk, 4 if conf else 0xFF, 2 if conf else 0xFF, pkt["age"], 5000 if conf else -(1 << 31),
                    pkt["gtx"] % U32)
    assert len(b) == 28
    return b


def stm32_c(deliv, frames, t_end, drift_ppm=0.0, s_off=0, arm_fresh=1):
    """Same truth evaluation as stm32(); the mode comes from the C controller. The STM32 clock
    is the one Rule0 models (drift, offset), but in microseconds and wrapping at 2^32 us."""
    d = drift_ppm * 1e-6
    def clk(t):
        return int(t * (1 + d) + s_off) % U32
    h = _ctl.fcs_create(-1.0, arm_fresh)
    assert h
    e_us, fl, rs = ctypes.c_uint(), ctypes.c_int(), ctypes.c_int()
    yw, vx, hh = ctypes.c_float(), ctypes.c_float(), ctypes.c_float()
    landed, land_t, armed = False, None, False
    newest = None
    i, n = 0, len(deliv)
    stale_seen = None
    mode_prev = None
    res = dict(v=[], land_t=None, steer_max=0, resumes=[], p3=0, st0=0, modes=[], pk=[], arm_refused=0, rejected=0,
               armed_at=None, landed_at_arm=False, rise_only=0, dup=0)
    valid_c = sorted(f["c"] for f in frames if f["kind"] == "ok")
    vi, lv = 0, None
    now = 0
    try:
        while now < t_end:
            now += STEP
            while vi < len(valid_c) and valid_c[vi] <= now:
                lv = valid_c[vi]; vi += 1
            while i < n and deliv[i][0] <= now:
                t_rx, pkt = deliv[i]; i += 1
                st = _ctl.fcs_on_packet(h, pkt_bytes(pkt), 28, clk(t_rx), ctypes.byref(e_us), ctypes.byref(fl))
                if st != 0:
                    res["rejected"] += 1
                    continue
                newest = pkt
                st0 = bool(fl.value & 1)
                res["st0"] += st0
                # stale only through the latency floor (the 10 s window alone would call it on time)
                res["rise_only"] += bool(fl.value & 32) and e_us.value <= E_STALE_MS * 1000
                res["dup"] += bool(fl.value & 64)
                res["pk"].append((e_us.value, st0, bool(fl.value & 4)))
            if now >= T_ARM and not armed:
                armed = _ctl.fcs_arm(h, clk(now)) == 0
                if not armed:
                    res["arm_refused"] += 1
            m = _ctl.fcs_step(h, clk(now), ctypes.byref(yw), ctypes.byref(vx), ctypes.byref(hh), ctypes.byref(rs))
            if now < T_ARM:
                continue
            mode = C_MODE[m]
            if mode == "wait":
                # take-off refused (no fresh frame yet, see README): still on the ground, so the
                # airborne properties do not apply yet; the operator retries every step
                res["modes"].append(mode)
                continue
            if res["armed_at"] is None:
                res["armed_at"] = now
                # armed straight into LAND (frame already > 3 s old): it never flew
                res["landed_at_arm"] = mode == "land"
            if mode == "land" and not landed:
                landed, land_t = True, now
            stale = rs.value in C_STALE_REASONS
            if stale:
                stale_seen = now
            if mode == "steer":
                # packets carry x = 0.3, size = 0.5: yaw = -1 * 60 * 0.3, vx = 0.8 * (0.625 - 0.5)
                assert abs(yw.value + 18.0) < 1e-3 and abs(vx.value - 0.1) < 1e-4 and abs(hh.value - 0.8) < 1e-6
            # ---- truth checks: identical to stm32() ----
            if lv is not None and not landed and now - lv > LAND + TOL_L + STEP:
                res["v"].append(("P1", now, now - lv))
            if mode == "steer":
                age = now - newest["ev"]["c"]
                res["steer_max"] = max(res["steer_max"], age)
                if age > HOVER + STEP + TOL_L:
                    res["v"].append(("P3", now, age)); res["p3"] += 1
            if mode == "steer" and mode_prev != "steer" and stale_seen is not None and mode_prev is not None:
                ok, run = p2_ok(frames, newest["idx"], stale_seen)
                res["resumes"].append((now, run))
                if not ok:
                    res["v"].append(("P2", now, run))
            res["modes"].append(mode)
            mode_prev = mode
    finally:
        _ctl.fcs_free(h)
    res["land_t"] = land_t
    return res


def diff_models(rp, rc):
    """Step-by-step mode diff (after arming) and per-packet rule-0 diff, Python v6 vs C."""
    a, b = rp["modes"], rc["modes"]
    comparable = rc["armed_at"] == T_ARM
    n = min(len(a), len(b)) if comparable else 0
    mism = [k for k in range(n) if a[k] != b[k]]
    shift = [k for k in mism if (k > 0 and b[k] == a[k - 1]) or (k + 1 < n and b[k] == a[k + 1])]
    pa, pb = rp["pk"], rc["pk"]
    st0 = [k for k in range(min(len(pa), len(pb))) if pa[k][1] != pb[k][1]]
    wr = sum(1 for k in range(min(len(pa), len(pb))) if pa[k][2] != pb[k][2])
    ediff = max((abs(pb[k][0] - pa[k][0] * 1000) for k in range(min(len(pa), len(pb)))), default=0)
    return dict(comparable=comparable, steps=n, len_equal=len(a) == len(b) and len(pa) == len(pb), mism=len(mism),
                non_shift=len(mism) - len(shift),
                first=(mism[0], a[mism[0]], b[mism[0]]) if mism else None,
                st0_mism=len(st0), wreset_mism=wr, e_maxdiff_us=ediff,
                land_dt=None if not comparable else (None if (rp["land_t"] is None) == (rc["land_t"] is None) and rp["land_t"] is None
                         else (rc["land_t"] - rp["land_t"]) if (rp["land_t"] is not None and rc["land_t"] is not None)
                         else "one_side"))


def wrap_clocks(rng, t_wrap_lo, t_wrap_hi):
    """rand_clocks(), then offsets chosen so the STM32 us clock, the GAP8 ms clock and the GAP8 us
    clock all wrap inside [t_wrap_lo, t_wrap_hi] (true time, us)."""
    c = rand_clocks(rng)
    d = c["drift"] * 1e-6
    t1, t2, t3 = (int(rng.uniform(t_wrap_lo, t_wrap_hi)) for _ in range(3))
    c["s_off"] = (-int(t1 * (1 + d))) % U32          # STM32 us clock == 0 (mod 2^32) at t1
    c["ms_off"] = U32 * 1000 - t2                      # GAP8 ms tick wraps at t2
    c["clk_off"] = (U32 - t3) % U32                    # GAP8 us clock wraps at t3
    return c


def simulate_c(scen, t_end, rng, outages=(), clk_off=0, ms_off=0, drift=0.0, s_off=0):
    """fix6 GAP8 + link once; then the Python v6 rule and the C controller on the same deliveries."""
    link = Link(rng, outages)
    g = Gap8(scen, t_end, link, "fix6", True, clk_off, ms_off)
    g.run()
    link.flush()
    for t_rx, pkt in link.deliv:
        pkt["t_rx"] = t_rx
    rp = stm32(link.deliv, g.frames, t_end - 100_000, True, Rule0(drift, s_off), True)
    rc = stm32_c(link.deliv, g.frames, t_end - 100_000, drift, s_off, arm_fresh=1)   # default take-off gate
    rw = stm32_c(link.deliv, g.frames, t_end - 100_000, drift, s_off, arm_fresh=0)   # Python-model take-off
    lat = max((t_rx - p["t_stamp"] for t_rx, p in link.deliv), default=0)
    return g, link, rp, rc, rw, lat


class Acc:
    def __init__(self):
        self.lands, self.kinds, self.resumes, self.never, self.steer_max = [], {}, [], 0, 0
        self.arm_refused = self.rejected = self.arm_delayed = self.never_armed = self.landed_at_arm = 0
        self.rise_only = self.dup = 0
    def add(self, g, r, f0):
        for v in r["v"]:
            self.kinds[v[0]] = self.kinds.get(v[0], 0) + 1
        self.steer_max = max(self.steer_max, r["steer_max"])
        if r["land_t"] is None:
            self.never += 1
        elif r.get("landed_at_arm"):
            self.landed_at_arm += 1     # no flight: not a landing after a lost target
        else:
            self.lands.append(r["land_t"] - last_valid(g.frames, r["land_t"]))
        self.resumes += [x for x in r["resumes"] if x[0] >= f0]
        self.arm_refused += r.get("arm_refused", 0)
        if "armed_at" in r:
            if r["armed_at"] is None:
                self.never_armed += 1
            elif r["armed_at"] > T_ARM:
                self.arm_delayed += 1
        self.rejected += r.get("rejected", 0)
        self.rise_only += r.get("rise_only", 0)
        self.dup += r.get("dup", 0)
    def out(self, runs):
        return dict(runs=runs,
                    land_after_last_valid_s=(round(min(self.lands) / US, 3), round(max(self.lands) / US, 3)) if self.lands else None,
                    never_landed=self.never, resumes=len(self.resumes),
                    min_run_at_resume=min((x[1] for x in self.resumes), default=None),
                    max_true_age_steered_s=round(self.steer_max / US, 3), violations=self.kinds,
                    arm_refused_steps=self.arm_refused, arm_delayed_runs=self.arm_delayed,
                    never_armed_runs=self.never_armed, landed_at_arm_runs=self.landed_at_arm, rejected=self.rejected,
                    rise_only_stale_packets=self.rise_only, duplicate_packets=self.dup)


class Diff:
    def __init__(self):
        self.d = dict(runs=0, runs_arm_delayed=0, steps=0, mism=0, non_shift=0, runs_with_mism=0, st0_mism=0, wreset_mism=0,
                      e_maxdiff_us=0, land_dt_us=[], first=None, len_mismatch=0)
    def add(self, rp, rc):
        x = diff_models(rp, rc)
        d = self.d
        d["runs"] += 1; d["runs_arm_delayed"] += not x["comparable"]; d["steps"] += x["steps"]; d["mism"] += x["mism"]; d["non_shift"] += x["non_shift"]
        d["runs_with_mism"] += x["mism"] > 0; d["st0_mism"] += x["st0_mism"]; d["wreset_mism"] += x["wreset_mism"]
        d["e_maxdiff_us"] = max(d["e_maxdiff_us"], x["e_maxdiff_us"]); d["len_mismatch"] += not x["len_equal"]
        if x["land_dt"] is not None:
            d["land_dt_us"].append(x["land_dt"])
        if d["first"] is None and x["first"] is not None:
            d["first"] = x["first"]
    def out(self):
        d = dict(self.d)
        ld = [v for v in d["land_dt_us"] if v != "one_side"]
        d["land_dt_us"] = dict(n=len(d["land_dt_us"]), one_side=d["land_dt_us"].count("one_side"),
                               min=min(ld, default=None), max=max(ld, default=None))
        return d


def run_case_c(name, mk, runs, t_end_s, outages_rel=(), seed=1, wrap=False):
    """run_case() for fix6 with the Python v6 rule and the C controller on identical deliveries.
    With wrap=False the rng sequence (and so every scenario) equals run_case(..., "fix6", "v6")."""
    rng = random.Random(seed)
    T = int(t_end_s * US)
    ap, ac, df, aw, dw = Acc(), Acc(), Diff(), Acc(), Diff()
    for _ in range(runs):
        f0 = F0 + int(rng.uniform(0, 60_000))
        outs = [(o[0], f0 + int(o[1] * US), f0 + int(o[2] * US)) + tuple(o[3:]) for o in outages_rel]
        clocks = wrap_clocks(rng, f0 - 2 * US, f0 + 4 * US) if wrap else rand_clocks(rng)
        g, link, rp, rc, rw, lat = simulate_c(mk(f0), T, rng, outs, **clocks)
        ap.add(g, rp, f0); ac.add(g, rc, f0); df.add(rp, rc); aw.add(g, rw, f0); dw.add(rp, rw)
    return dict(case=name, clocks="forced wraps" if wrap else "random", py_v6=ap.out(runs), c6=ac.out(runs), diff=df.out(),
                c6w=aw.out(runs), diff_w=dw.out())


def monte_carlo_c(runs=500, seed=7, mix="orig", link_out=False, esp_out=False, wrap=False):
    """monte_carlo() for fix6: Python v6 vs C on identical deliveries (same rng use as monte_carlo)."""
    rng = random.Random(seed)
    ap, ac, df, aw, dw = Acc(), Acc(), Diff(), Acc(), Diff()
    for k in range(runs):
        segs, t = [], 2.0
        choices = ["ok", "ok", "fail", "timeout", "mixed", "lowp"]
        if mix == "ext":
            choices += ["stall", "slow", "inflight"]
        while t < 40:
            kind = rng.choice(choices)
            dd = rng.uniform(0.05, 5.0)
            segs.append((t, t + dd, kind)); t += dd
        hang_at = rng.choice([None, rng.uniform(5, 40)])
        outs = []
        if link_out:
            for _ in range(rng.randint(1, 4)):
                a = rng.uniform(3, 40); outs.append(("nina", int(a * US), int((a + rng.uniform(0.05, 2.5)) * US)))
        if esp_out:
            for _ in range(rng.randint(1, 3)):
                a = rng.uniform(3, 40); outs.append(("esp", int(a * US), int((a + rng.uniform(0.05, 2.5)) * US)))
        def scen(tt, segs=segs, hang_at=hang_at, r=random.Random(rng.random())):
            ts = tt / US
            if hang_at is not None and ts >= hang_at:
                return ("hang", None)
            for a, b, kind in segs:
                if a <= ts < b:
                    if kind == "ok": return ("ok", r.uniform(0.6, 1.0))
                    if kind == "lowp": return ("ok", r.uniform(0.0, 0.8))
                    if kind == "fail": return ("fail", None)
                    if kind == "timeout": return ("timeout", None)
                    if kind == "stall": return r.choice([("stall", r.uniform(0.1, 2.0)), ("ok", r.uniform(0.6, 1.0))])
                    if kind == "slow": return ("slow", (r.uniform(0.03, 0.8), r.uniform(0.6, 1.0)))
                    if kind == "inflight": return r.choice([("stall_inflight", (r.uniform(0.1, 2.0), r.uniform(0.6, 1.0))), ("ok", r.uniform(0.6, 1.0))])
                    return r.choice([("ok", r.uniform(0.3, 1.0)), ("fail", None), ("timeout", None)])
            return ("ok", 0.95)
        clocks = wrap_clocks(rng, 4 * US, 40 * US) if wrap else rand_clocks(rng)
        g, link, rp, rc, rw, lat = simulate_c(scen, 45 * US, rng, outs, **clocks)
        ap.add(g, rp, 0); ac.add(g, rc, 0); df.add(rp, rc); aw.add(g, rw, 0); dw.add(rp, rw)
    return dict(mc=mix + ("+nina_outages" if link_out else "") + ("+esp_outages" if esp_out else ""),
                clocks="forced wraps" if wrap else "random", py_v6=ap.out(runs), c6=ac.out(runs), diff=df.out(),
                c6w=aw.out(runs), diff_w=dw.out())


# GROUND timelines (safety review 7, finding 1). The link gets slower while the drone waits on the
# ground and it takes off later (T_ARM moved from 3 s). The documented v6 rule absorbs the step once
# its 10 s window forgets the healthy minimum and then steers on late frames (P3); the C controller's
# latency floor refuses to arm (c6 and c6w: never_armed_runs == runs). (g5) is the control: a healthy
# link, take-off at 25 s, where every model must arm and follow.
# (name, scenario, t_end_s, outages relative to f0 (= 10 s + jitter), T_ARM in s)
LAT1 = ("lat", -5.0, 200.0, 1_000_000)          # +1 s from t = 5 s to the end
GROUND = [
    ("(g0) +1 s link latency from 5 s, on the ground; take-off at 25 s", lambda f0: ok, 40.0, [LAT1], 25.0),
    ("(g1) ground silence 8 s (NINA down 5-13 s), link +1 s after it; take-off at 25 s", lambda f0: ok, 40.0,
     [("nina", -5.0, 3.0), LAT1], 25.0),
    ("(g2) ground silence 9.9 s, link +1 s after it; take-off at 25 s", lambda f0: ok, 40.0,
     [("nina", -5.0, 4.9), LAT1], 25.0),
    ("(g3) ground silence 12 s, link +1 s after it; take-off at 25 s", lambda f0: ok, 40.0,
     [("nina", -5.0, 7.0), LAT1], 25.0),
    ("(g4) ground silence 30 s, link +1 s after it; take-off at 45 s", lambda f0: ok, 60.0,
     [("nina", -5.0, 25.0), LAT1], 45.0),
    ("(g5) +0.08 s at 5 s and again at 16 s (absorbed one by one); take-off at 30 s", lambda f0: ok, 45.0,
     [("lat", -5.0, 200.0, 80_000), ("lat", 6.0, 200.0, 80_000)], 30.0),
    ("(g6) CONTROL: healthy link; take-off at 25 s", lambda f0: ok, 40.0, [], 25.0),
]


def run_ground(n):
    global T_ARM
    saved = T_ARM
    try:
        for name, mk, te, outs, t_arm in GROUND:
            T_ARM = int(t_arm * US)
            r = run_case_c(name, mk, n, te, outs)
            r["t_arm_s"] = t_arm
            print(r, flush=True)
    finally:
        T_ARM = saved


if __name__ == "__main__":
    import sys
    sec = sys.argv[1] if len(sys.argv) > 1 else "all"
    N = int(sys.argv[2]) if len(sys.argv) > 2 else 200
    MCN = int(sys.argv[3]) if len(sys.argv) > 3 else 500
    if sec in ("all", "checks"):
        print("finalize crosscheck (C vs spec):", finalize_crosscheck(), flush=True)
        print("v6 byte / frame-ref crosscheck (C vs spec):", byte_crosscheck(), flush=True)
        assert frame_age(0) == 0 and frame_age(1) == 1 and frame_age(20000) == 1 and frame_age(20001) == 2
        assert frame_age(3_000_000) == 150 and frame_age(5_080_000) == 254 and frame_age(5_080_001) == 255
        print("encoding asserts OK")
    if sec in ("all", "timelines", "wraptimelines"):
        for name, mk, te, outs in TIMELINES:
            print(run_case_c(name, mk, N, te, outs, wrap=(sec == "wraptimelines")), flush=True)
    if sec.startswith("mc") or sec.startswith("wrapmc"):
        wrap = sec.startswith("wrap")
        k = int(sec[len("wrapmc" if wrap else "mc"):])
        mix, lo, eo = MIXES[k]
        print(monte_carlo_c(runs=MCN, mix=mix, link_out=lo, esp_out=eo, wrap=wrap), flush=True)
    if sec == "groundstep":
        run_ground(N)
    if sec == "orig":   # the original sections, unchanged (Python rule models only)
        for name, mk, te, outs in TIMELINES:
            for fw, stm in BASE:
                print(run_case(name, mk, N, te, fw, stm, outs), flush=True)
