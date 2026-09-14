import sys
p = sys.argv[1]
s = open(p).read()
def rep(old, new, n=1):
    global s
    c = s.count(old)
    assert c == n, (c, old[:80])
    s = s.replace(old, new)

rep('"""Independent review sim of fix round 5 (commit 6c4b119) vs fix round 4 (6dbd8dc).',
'''"""Independent review sim of fix round 6 (commit 0623a7d), copy of fw_review5/safety_sim_review5.py.

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
Independent review sim of fix round 5 (commit 6c4b119) vs fix round 4 (6dbd8dc).''')

rep('''_lib.fp_ref.restype = ctypes.c_uint32
''', '''_lib.fp_ref.restype = ctypes.c_uint32
_lib.fp_frame_ref.argtypes = [ctypes.c_char_p, ctypes.POINTER(ctypes.c_uint32)]
_lib.fp_frame_ref.restype = ctypes.c_int
assert _lib.fp_version() == 6
''')

rep('''    b[0], b[1] = 0xA5, 0x05''', '''    b[0], b[1] = 0xA5, 0x06''')

rep('''def sgn32(x):''', '''def c_frame_ref(age, ref_us):
    """follow_packet_frame_ref_us on a stage-1 packet (C)."""
    b = bytearray(28)
    b[0], b[1] = 0xA5, 0x06
    b[19] = age
    b[24:28] = (ref_us % U32).to_bytes(4, "little")
    out = ctypes.c_uint32(0)
    have = _lib.fp_frame_ref(bytes(b), ctypes.byref(out))
    return have, out.value


def sgn32(x):''')

# Gap8 init: spi record
rep('''        self.ntx = 0
        link.on_tx = self.on_tx''', '''        self.ntx = 0
        self.spi = dict(have_tx=0, have_frame=0, tx_us=0, frame_us=0)   # com.c g_app_spi
        self.spi_pend = []          # records written by the com task at t_fin (in order)
        self.spi_resets = 0
        link.on_tx = self.on_tx''')

# on_tx
rep('''        self.ntx += 1
        if self.fw == "fix5":
            age, trk, gtx = c_finalize(pkt["age"], pkt["trk"], pkt["ref"], self.clk(t_fin), self.ms(t_fin))
            assert gtx == self.ms(t_fin)
            pkt["age"], pkt["trk"], pkt["gtx"] = age, trk, gtx''', '''        self.ntx += 1
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
            self.spi_pend.append((t_fin, self.clk(t_fin), have_frame, frame_us))''')

rep('''            if pkt["trk"] == 1 and true_age > HOVER:
                self.gviol("G3_trk1_older_0.5s", (round(t_fin / US, 3), true_age))
        if pkt["trk"] == 1 and wait > TX_MAX_WAIT:
            self.gviol("G2_trk1_wait>100ms", (round(t_fin / US, 3), wait))''', '''            if (pkt["trk"] & 1) and true_age > HOVER:
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
                self.gviol("G4_bit1_not_fresh_p07", (round(t_fin / US, 3), ev["kind"], ev["p"]))''')

# spi_ages method, placed before gviol
rep('''    def gviol(self, k, info):''', '''    def spi_ages(self, t):
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
    def gviol(self, k, info):''')

# process
rep('''        if self.fw in ("fix4", "fix5"):
            need = ((not self.have_good) or
                    ((self.clk(t_dec) - self.last_good) % U32) > RECONF or
                    self.tx_gap(t_dec) > RECONF)
            if need:
                self.reset(); self.resets += 1''', '''        if self.fw in ("fix4", "fix5", "fix6"):
            need = ((not self.have_good) or
                    ((self.clk(t_dec) - self.last_good) % U32) > RECONF or
                    self.tx_gap(t_dec) > RECONF)
            if self.fw == "fix6" and not need and self.tx_on:
                self.link.advance(t_dec)          # the com task runs concurrently
                sg, sf = self.spi_ages(t_dec)
                if sg > RECONF or sf > RECONF:
                    need = True; self.spi_resets += 1
            if need:
                self.reset(); self.resets += 1''')

rep('''        trk = self.trk
        t_s = t_dec + POST
        if self.fw in ("fix4", "fix5"):
            if (t_s - c) > RECONF:
                self.reset(); trk = 0; self.resets += 1''', '''        trk = self.trk
        t_s = t_dec + POST
        if self.fw == "fix6":
            trk = (1 if trk else 0) | (2 if p >= ENTER else 0)
        if self.fw in ("fix4", "fix5", "fix6"):
            if (t_s - c) > RECONF:
                self.reset(); trk = 0; self.resets += 1''')

# stm32
rep('''def stm32(deliv, frames, t_end, rule4, rule0=None):''', '''def stm32(deliv, frames, t_end, rule4, rule0=None, bit1=False):''')
rep('''                cnt = cnt + 1 if (pkt["trk"] == 1 and pkt["age"] != SAT''', '''                need_bits = 3 if bit1 else 1
                cnt = cnt + 1 if ((pkt["trk"] & need_bits) == need_bits and pkt["age"] != SAT''')
rep('''        elif newest["trk"] == 0:
            mode = "hover"''', '''        elif (newest["trk"] & 1) == 0:
            mode = "hover"''')
rep('''STM = {"v4": (False, False), "v4+r4": (True, False), "v5": (True, True)}''',
    '''STM = {"v4": (False, False, False), "v4+r4": (True, False, False), "v5": (True, True, False),
       "v6": (True, True, True)}''')
rep('''    r4, r0 = STM[stm]
    rule0 = Rule0(drift, s_off) if r0 else None
    r = stm32(link.deliv, g.frames, t_end - 100_000, r4, rule0)''', '''    r4, r0, b1 = STM[stm]
    rule0 = Rule0(drift, s_off) if r0 else None
    r = stm32(link.deliv, g.frames, t_end - 100_000, r4, rule0, b1)''')
open(p, "w").write(s)
print("patched")
