"""Independent review sim of fix round 6 (commit 0623a7d), copy of fw_review5/safety_sim_review5.py.

2026-09-13: ENTER raised 0.7 -> 0.75 to match the shipped firmware bar (crazyflie_ssd app_config.h
  APP_FOLLOW_VIS_ENTER_RAW 5467 = ceil(logit(0.75)/eps_out); decision and evidence in pytorch_ssd
  docs/eval_results/2026-09-13-champion-threshold/README.md, simulation only, no hardware run).
  Everything under logs/ was produced with ENTER = 0.7 and has NOT been re-run at 0.75. The
  properties P1-P3 and the G-checks are stated relative to ENTER, and the scripted scenarios use
  p = 0.95 (above both bars) and p = 0.6 (inside the hysteresis zone of both), or random draws.

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
ENTER, EXIT, CONFIRM = 0.75, 0.45, 3   # enter raised 0.7 -> 0.75 on 2026-09-13; logs/ were produced at 0.7
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

_lib = ctypes.CDLL(os.path.join(os.path.dirname(os.path.abspath(__file__)), "libfp.so"))
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
    res = dict(v=[], land_t=None, steer_max=0, resumes=[], p3=0, st0=0)
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
    if sec in ("all", "timelines"):
        for name, mk, te, outs in TIMELINES:
            for fw, stm in BASE:
                print(run_case(name, mk, N, te, fw, stm, outs), flush=True)
    if sec.startswith("mc"):
        k = int(sec[2:])
        mix, lo, eo = MIXES[k]
        for fw, stm in BASE:
            print(monte_carlo(fw, stm, runs=MCN, mix=mix, link_out=lo, esp_out=eo), flush=True)
