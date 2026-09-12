"""Diagnostic: why the C controller's rule-0 stale flags can differ from the Python model's in
timeline (x2h) (+0.3 s ESP32 latency held 15 s), while the modes never differ.

Both keep the clock offset as the minimum over a ring of ten 1 s buckets, but the Python model
buckets by TRUE time (t_rx // 1 s) and the C controller by the STM32 clock's 1 s grid (the only
clock it has). With a random STM32 clock phase, the moment the window forgets the pre-step minimum
differs by < 1 s (either direction), so a few packets near that moment are stale in one model and
fresh in the other. With the STM32 clock aligned to true time (drift 0, offset 0) the decisions
agree on every packet and e differs by < 1 ms (ms quantization of the Python model).
Usage: python3 diag_rule0_phase.py [runs]
"""
import random
import sys

import safety_sim_review6_c as S

runs = int(sys.argv[1]) if len(sys.argv) > 1 else 20
name, mk, te, outs = S.TIMELINES[21]
print(name)
for mode in ("random clocks", "aligned clocks"):
    rng = random.Random(1)
    tot = dict(runs=runs, st0_mism=0, e_maxdiff_us=0, mode_mism=0)
    for _ in range(runs):
        f0 = S.F0 + int(rng.uniform(0, 60_000))
        o = [(x[0], f0 + int(x[1] * S.US), f0 + int(x[2] * S.US)) + tuple(x[3:]) for x in outs]
        c = S.rand_clocks(rng)
        if mode == "aligned clocks":
            c["drift"], c["s_off"] = 0.0, 0
        g, link, rp, rc, rw, lat = S.simulate_c(mk(f0), int(te * S.US), rng, o, **c)
        d = S.diff_models(rp, rw)
        tot["st0_mism"] += d["st0_mism"]
        tot["e_maxdiff_us"] = max(tot["e_maxdiff_us"], d["e_maxdiff_us"])
        tot["mode_mism"] += d["mism"]
    print(" ", mode, tot)
