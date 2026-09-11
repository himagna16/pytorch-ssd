"""Review6: P2 race sweep (reproduces fw_review5/p2_nina_race.py, seed 5, 200 runs per length) against
the committed fix-round-6 GAP8 model ("fix6" in safety_sim_review6.py), plus:
  * a triggered variant: the NINA stall starts exactly delta after a queue attempt (delta in 1 us .. 59 ms);
  * an ESP32-internal stall sweep (GAP8 cannot see it; STM32-dependent: v5 vs v6 rule 4).
Scenario: p = 0.95 before the stall, 0.6 (hysteresis zone [0.45, 0.7)) from the stall end on, so any
resume after the stale hover is a P2 violation."""
import random
import sys
import safety_sim_review6 as S


def after(f0, t_sw, p1, p2):
    return lambda t: ("ok", p1 if t < t_sw else p2)


def targeted(L, fw, stm, runs=200, seed=5, kind="nina"):
    rng = random.Random(seed)
    kinds, res, gk = {}, 0, {}
    for _ in range(runs):
        f0 = 10 * S.US + int(rng.uniform(0, 60_000))
        outs = [(kind, f0, f0 + int(L * S.US))]
        g, link, r, lat = S.simulate(after(f0, f0 + int(L * S.US), 0.95, 0.6), 20 * S.US, fw, stm, rng, outs,
                                     **S.rand_clocks(rng))
        for v in r["v"]:
            kinds[v[0]] = kinds.get(v[0], 0) + 1
        for k, c in g.g.items():
            gk[k] = gk.get(k, 0) + c
        res += len([x for x in r["resumes"] if x[0] >= f0])
    return dict(kind=kind, L=L, fw=fw, stm32=stm, runs=runs, resumes=res, violations=kinds, gap8_checks=gk)


class TrigLink(S.Link):
    """NINA stall of length L starting delta after the first app-packet queue attempt at t >= f0."""
    def __init__(self, rng, f0, L, delta):
        super().__init__(rng, ())
        self.f0, self.L, self.delta, self.armed = f0, L, delta, True
        self.t_trig = None
    def enqueue(self, t, pkt):
        # The stall is inserted BEFORE the packet is handed to the com task. delta <= 0: the stall
        # already covers this queue attempt, so this packet is the one the com task holds (the
        # model's "handshake not complete when the stall starts"); delta > 0: this packet goes out,
        # the next one is held.
        if self.armed and pkt is not None and t >= self.f0:
            self.armed = False
            self.t_trig = t
            self.out.append(("nina", t + self.delta, t + self.delta + self.L))
        super().enqueue(t, pkt)


def triggered(L, delta, fw, stm, runs=100, seed=9):
    rng = random.Random(seed)
    kinds, res, gk = {}, 0, {}
    for _ in range(runs):
        f0 = 10 * S.US + int(rng.uniform(0, 60_000))
        clocks = S.rand_clocks(rng)
        link = TrigLink(rng, f0, int(L * S.US), delta)
        st = {"sw": None}
        def scen(t, link=link, st=st):
            if link.t_trig is not None and st["sw"] is None:
                st["sw"] = link.t_trig + delta + int(L * S.US)
            return ("ok", 0.95 if (st["sw"] is None or t < st["sw"]) else 0.6)
        g = S.Gap8(scen, 20 * S.US, link, fw, True, clocks["clk_off"], clocks["ms_off"])
        g.run(); link.flush()
        for t_rx, pkt in link.deliv:
            pkt["t_rx"] = t_rx
        r4, r0, b1 = S.STM[stm]
        rule0 = S.Rule0(clocks["drift"], clocks["s_off"]) if r0 else None
        r = S.stm32(link.deliv, g.frames, 20 * S.US - 100_000, r4, rule0, b1)
        for v in r["v"]:
            kinds[v[0]] = kinds.get(v[0], 0) + 1
        for k, c in g.g.items():
            gk[k] = gk.get(k, 0) + c
        res += len([x for x in r["resumes"] if x[0] >= f0])
    return dict(kind="nina_trig", L=L, delta_us=delta, fw=fw, stm32=stm, runs=runs, resumes=res,
                violations=kinds, gap8_checks=gk)


if __name__ == "__main__":
    sec = sys.argv[1] if len(sys.argv) > 1 else "sweep"
    LS = (0.38, 0.40, 0.42, 0.44, 0.46, 0.48, 0.50, 0.55, 0.60, 1.0)
    COMBOS = (("fix5", "v5"), ("fix6", "v4"), ("fix6", "v4+r4"), ("fix6", "v5"), ("fix6", "v6"))
    if sec == "sweep":
        for L in LS:
            for fw, stm in COMBOS:
                print(targeted(L, fw, stm), flush=True)
    if sec == "trig":
        for L in (0.38, 0.40, 0.42, 0.44, 0.46, 0.50, 0.60):
            for delta in (-59_000, -30_000, -10_000, -1_000, 0, 1_000, 30_000):
                for fw, stm in (("fix5", "v5"), ("fix6", "v4"), ("fix6", "v5")):
                    print(triggered(L, delta, fw, stm), flush=True)
    if sec == "esp":
        for L in (0.3, 0.38, 0.42, 0.46, 0.5, 0.6, 1.0, 2.0):
            for fw, stm in (("fix6", "v5"), ("fix6", "v6")):
                print(targeted(L, fw, stm, seed=6, kind="esp"), flush=True)
