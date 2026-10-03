"""Dark-frame guard timelines (crazyflie-ssd branch sai/dark-guard-exposure) on top of the
review6 timing simulator. safety_sim_review6.py is imported unchanged (same packet code via
libfp.so, same link, rule-0 and rule-4 models, same P1-P3 truth checks).

Why: on 2026-09-24 the AI-deck camera delivered near-black frames for whole runs; the champion
scored them at about 0.84 (median 0.83-0.84 in both near-black runs) and the follower locked on them
(docs/eval_results/2026-09-24-grid-capture/README.md). The guard rejects a frame whose 128x128
network input has mean < APP_MIN_FRAME_MEAN and treats it like a capture timeout / pipeline
failure.

GAP8 models
  fw="fix6"  : the fc42eb9 / ff876bd images (no guard). A dark frame is an ordinary frame: the
               network runs and scores it at the scenario's p (default P_NOISE = 0.84).
  fw="fix6g" : fix6 + the guard, as implemented: capture (CAP) + preprocess and statistics (PRE),
               then handle_perception_gap(): visibility state reset, no-target packet (tracking byte
               0) whose age keeps describing the last good frame; the last good frame is unchanged;
               no inference. The firmware also prints 2 console lines per 10 frames (summary + "img"),
               modelled as 2 queued console packets.
Truth: a dark frame is NOT a valid frame (the camera did not see the scene). P1's "last valid frame"
and the review6 p2_ok() skip dark frames (they are relabelled kind="dark" after the run).
New checks
  P4  the STM32 steered while its newest packet came from a dark frame;
  P5  the STM32 steered on frame k although there are not 3 consecutive p >= ENTER non-dark frames
      after the last dark frame before k ("after darkness, a normal frame must not re-lock at once");
  G8  a packet from a dark frame left the GAP8 with any tracking bit set.
Also reported per case: delay from the last valid frame to the first STALE hover (rule 2, t_fresh
older than 0.5 s); delay from the last valid frame whose packet was delivered to the landing (rule 1,
3.0 s); and, at every re-lock after a dark frame, the longest run of consecutive fresh p >= ENTER
non-dark frames since that dark frame (must be >= 3).

Run (needs libfp.so next to safety_sim_review6.py, see HANDOFF.md section 4 "Host checks"):
  python3 safety_sim_dark_guard.py [N_per_timeline=200] [MC_runs=500]
"""
import random
import sys

import safety_sim_review6 as base
from safety_sim_review6 import (CAP, CONFIRM, ENTER, HOVER, INF, LAND, P, STEP, SUMMARY_EVERY,
                                T_ARM, TIMEOUT, TOL_L, US, F0, Link, Rule0, STM,
                                p2_ok, rand_clocks)

P_NOISE = 0.84       # what the champion said about near-black frames (2026-09-24, n = 169)
PRE = 3_000          # preprocess + statistics pass, us (unmeasured; "a few ms" in HANDOFF 5.5)


class Gap8Dark(base.Gap8):
    """The review6 GAP8 model with fw="fix6" (every fix-round-6 behavior: re-confirmation checks,
    v6 tracking byte, com.c finalize and SPI record), plus dark frames; guard=True adds the guard."""
    def __init__(self, *a, guard=False, **k):
        super().__init__(*a, **k)
        assert self.fw == "fix6"
        self.guard = guard
        self.dark_n = 0

    def process(self, c, inf, p):
        n0 = self.camframe
        t = super().process(c, inf, p)
        if self.guard and self.camframe != n0 and self.camframe % SUMMARY_EVERY == 0:
            t = self.console_line(t)          # the guard build's second ("img") line
        return t

    def dark(self, t, p_noise):
        self.dark_n += 1
        if self.guard:
            t2 = self.gap(t + CAP + PRE)      # handle_perception_gap(): reset + no-target packet
            self.frames[-1]["dark"] = True
            self.camframe += 1
            if self.camframe % SUMMARY_EVERY == 0:
                t2 = self.console_line(t2)
                t2 = self.console_line(t2)
            return t2
        n0 = len(self.frames)
        t2 = self.process(t + CAP, INF, p_noise)   # no guard: the network runs on the dark frame
        self.frames[n0]["dark"] = True
        return t2

    def run(self):
        """review6 Gap8.run() plus the "dark" scenario kind."""
        t = 0
        while t < self.t_end:
            kind, arg = self.scen(t)
            if kind == "dark":
                t = self.dark(t, arg); continue
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


def p5_table(frames):
    """ok[k]: there are 3 consecutive p >= ENTER non-dark "ok" frames after the last dark frame <= k.
    best[k]: longest run of consecutive p >= ENTER non-dark "ok" frames after the last dark frame <= k.
    last_dark[k]: index of the last dark frame <= k (-1 if none)."""
    ok, bests, last_dark = [], [], []
    run, best, ld = 0, 0, -1
    for k, f in enumerate(frames):
        if f.get("dark"):
            run, best, ld = 0, 0, k
        elif f["kind"] == "ok" and f["p"] >= ENTER:
            run += 1
            best = max(best, run)
        else:
            run = 0
        ok.append(best >= CONFIRM)
        bests.append(best)
        last_dark.append(ld)
    return ok, bests, last_dark


def stm32_dark(deliv, frames, t_end, rule4, rule0=None, bit1=False):
    """Copy of safety_sim_review6.stm32(); lines marked DARK are the only changes."""
    t_fresh, landed, land_t = None, False, None
    newest, newest_st0 = None, False
    i, n = 0, len(deliv)
    stale_seen = None
    need, cnt = True, 0
    mode_prev = None
    res = dict(v=[], land_t=None, steer_max=0, resumes=[], p3=0, st0=0,
               trans=[], relock_after_dark=[])                               # DARK
    valid_c = sorted(f["c"] for f in frames if f["kind"] == "ok")          # dark frames relabelled first
    p5, best_run, last_dark = p5_table(frames)                              # DARK
    prev_steer_k = -1                                                       # DARK
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
            if pkt["age"] == base.SAT:
                t_fresh = None
            elif not st0:
                t_fresh = t_rx - e * 1000 - pkt["age"] * base.UNIT
            newest_st0 = st0
            if rule4:
                need_bits = 3 if bit1 else 1
                cnt = cnt + 1 if ((pkt["trk"] & need_bits) == need_bits and pkt["age"] != base.SAT
                                  and pkt["age"] * base.UNIT <= HOVER and not st0) else 0
        if now < T_ARM:
            continue
        stale = t_fresh is None or now - t_fresh > HOVER
        if landed:
            mode = "land"
        elif t_fresh is None or now - t_fresh > LAND:
            landed, land_t, mode = True, now, "land"
        elif stale:
            mode = "hover_stale"                                                # DARK: label only
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
            if newest["ev"].get("dark"):                                       # DARK: P4
                res["v"].append(("P4", now, newest["idx"]))
            if not p5[newest["idx"]]:                                           # DARK: P5
                res["v"].append(("P5", now, newest["idx"]))
        if mode == "steer" and mode_prev != "steer":                            # DARK: re-lock after darkness
            k = newest["idx"]
            if last_dark[k] > prev_steer_k:
                res["relock_after_dark"].append(best_run[k])
            prev_steer_k = k
        if mode == "steer" and mode_prev != "steer" and stale_seen is not None and mode_prev is not None:
            ok, run = p2_ok(frames, newest["idx"], stale_seen)
            res["resumes"].append((now, run))
            if not ok:
                res["v"].append(("P2", now, run))
        if mode != mode_prev:                                                   # DARK
            res["trans"].append((now, mode, lv))
        mode_prev = mode
    res["land_t"] = land_t
    return res


def simulate_dark(scen, t_end, fw, stm, rng, outages=(), tx=True, clk_off=0, ms_off=0, drift=0.0, s_off=0):
    """fw: "fix6" (fc42eb9, no guard) or "fix6g" (fix6 + the dark-frame guard)."""
    assert fw in ("fix6", "fix6g")
    link = Link(rng, outages)
    g = Gap8Dark(scen, t_end, link, "fix6", tx, clk_off, ms_off, guard=(fw == "fix6g"))
    g.run()
    link.flush()
    for t_rx, pkt in link.deliv:
        pkt["t_rx"] = t_rx
        if pkt["ev"].get("dark") and pkt["trk"] != 0:     # G8, on the finalized tracking byte
            g.gviol("G8_dark_frame_trk", (round(t_rx / US, 3), pkt["trk"]))
    for f in g.frames:                    # truth: a dark frame is not a valid frame
        if f.get("dark"):
            f["kind"] = "dark"
    r4, r0, b1 = STM[stm]
    rule0 = Rule0(drift, s_off) if r0 else None
    r = stm32_dark(link.deliv, g.frames, t_end - 100_000, r4, rule0, b1)
    return g, link, r


def dark_during(f0, dur, p_noise=P_NOISE, p=P):
    return lambda t: ("dark", p_noise) if f0 <= t < f0 + dur else ("ok", p)


def dark_once(f0, p_noise=P_NOISE):
    st = {"d": False}
    def f(t):
        if t >= f0 and not st["d"]:
            st["d"] = True
            return ("dark", p_noise)
        return ("ok", P)
    return f


def dark_every(f0, k, dur, p_noise=P_NOISE):
    """Every k-th camera frame dark for dur seconds (flicker)."""
    st = {"i": 0}
    def f(t):
        if f0 <= t < f0 + dur:
            st["i"] += 1
            return ("dark", p_noise) if st["i"] % k == 0 else ("ok", P)
        return ("ok", P)
    return f


def last_delivered_valid(frames, t):
    """Capture time of the newest valid (non-dark) frame whose packet reached the STM32 by t."""
    cs = [f["c"] for f in frames if f["kind"] == "ok" and f["pkt"].get("t_rx") is not None
          and f["pkt"]["t_rx"] <= t]
    return max(cs) if cs else None


def run_case(name, mk, runs, t_end_s, fw, stm, seed=1):
    rng = random.Random(seed)
    T = int(t_end_s * US)
    kinds, gk = {}, {}
    lands, never, stale_h, resumes, steer_max, darks, relock = [], 0, [], [], 0, 0, []
    for _ in range(runs):
        f0 = F0 + int(rng.uniform(0, 60_000))
        g, link, r = simulate_dark(mk(f0), T, fw, stm, rng, **rand_clocks(rng))
        darks += g.dark_n
        for v in r["v"]:
            kinds[v[0]] = kinds.get(v[0], 0) + 1
        for k, c in g.g.items():
            gk[k] = gk.get(k, 0) + c
        steer_max = max(steer_max, r["steer_max"])
        if r["land_t"] is None:
            never += 1
        else:
            lands.append(r["land_t"] - last_delivered_valid(g.frames, r["land_t"]))
        relock += r["relock_after_dark"]
        for now, mode, lv in r["trans"]:
            if mode == "hover_stale" and now >= f0 and lv is not None:
                stale_h.append(now - lv)
                break
        resumes += [x[1] for x in r["resumes"] if x[0] >= f0]
    rng_s = lambda xs: (round(min(xs) / US, 3), round(max(xs) / US, 3)) if xs else None
    return dict(case=name, fw=fw, stm32=stm, runs=runs, dark_frames=darks,
                first_stale_hover_after_last_valid_s=rng_s(stale_h),
                land_after_last_delivered_valid_s=rng_s(lands), landed=runs - never,
                relocks_after_dark=len(relock),
                min_fresh_run_since_dark_at_relock=min(relock) if relock else None,
                resumes=len(resumes), min_fresh_run_at_resume=min(resumes) if resumes else None,
                max_true_age_steered_s=round(steer_max / US, 3),
                violations=kinds, gap8_checks=gk)


def monte_carlo(fw, stm, runs=500, seed=7):
    """review6 'orig' segment mix plus dark bursts and dark flicker (noise p 0.6-1.0)."""
    rng = random.Random(seed)
    kinds, gk, lands, steer_max, relock = {}, {}, [], 0, []
    for _ in range(runs):
        segs, t = [], 2.0
        choices = ["ok", "ok", "fail", "timeout", "mixed", "lowp", "dark", "dark", "flicker"]
        while t < 40:
            kind = rng.choice(choices)
            d = rng.uniform(0.05, 5.0)
            segs.append((t, t + d, kind)); t += d
        hang_at = rng.choice([None, rng.uniform(5, 40)])

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
                    if kind == "dark": return ("dark", r.uniform(0.6, 1.0))
                    if kind == "flicker": return r.choice([("dark", r.uniform(0.6, 1.0)), ("ok", r.uniform(0.6, 1.0))])
                    return r.choice([("ok", r.uniform(0.3, 1.0)), ("fail", None), ("timeout", None)])
            return ("ok", 0.95)
        g, link, r = simulate_dark(scen, 45 * US, fw, stm, rng, **rand_clocks(rng))
        for v in r["v"]:
            kinds[v[0]] = kinds.get(v[0], 0) + 1
        for kk, c in g.g.items():
            gk[kk] = gk.get(kk, 0) + c
        steer_max = max(steer_max, r["steer_max"])
        relock += r["relock_after_dark"]
        if r["land_t"] is not None:
            lands.append(r["land_t"] - last_delivered_valid(g.frames, r["land_t"]))
    return dict(mc="orig+dark+flicker", fw=fw, stm32=stm, runs=runs, landed=len(lands),
                land_after_last_delivered_valid_s=(round(min(lands) / US, 3), round(max(lands) / US, 3)) if lands else None,
                relocks_after_dark=len(relock), min_fresh_run_since_dark_at_relock=min(relock) if relock else None,
                max_true_age_steered_s=round(steer_max / US, 3), violations=kinds, gap8_checks=gk)


TIMELINES = [
    ("(k1) lens covered 10 s, then a person at p 0.95", lambda f0: dark_during(f0, 10 * US), 30.0),
    ("(k2) dark burst 0.3 s while following", lambda f0: dark_during(f0, int(0.3 * US)), 30.0),
    ("(k3) dark burst 1.0 s", lambda f0: dark_during(f0, 1 * US), 30.0),
    ("(k4) dark burst 2.9 s", lambda f0: dark_during(f0, int(2.9 * US)), 30.0),
    ("(k5) dark burst 3.5 s", lambda f0: dark_during(f0, int(3.5 * US)), 30.0),
    ("(k6) single dark frame while following", dark_once, 30.0),
    ("(k7) every 3rd frame dark for 10 s", lambda f0: dark_every(f0, 3, 10 * US), 30.0),
    ("(k8) every 4th frame dark for 10 s", lambda f0: dark_every(f0, 4, 10 * US), 30.0),
    ("(k9) lens covered 10 s, network says p 0.95 on the dark frames",
     lambda f0: dark_during(f0, 10 * US, p_noise=0.95), 30.0),
]
BASE_D = [("fix6", "v6"), ("fix6g", "v4"), ("fix6g", "v6")]

if __name__ == "__main__":
    N = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    MCN = int(sys.argv[2]) if len(sys.argv) > 2 else 500
    print(f"ENTER={ENTER} P_NOISE={P_NOISE} PRE_us={PRE} runs/timeline={N} mc_runs={MCN}", flush=True)
    for name, mk, te in TIMELINES:
        for fw, stm in BASE_D:
            print(run_case(name, mk, N, te, fw, stm), flush=True)
    for fw, stm in BASE_D:
        print(monte_carlo(fw, stm, runs=MCN), flush=True)
