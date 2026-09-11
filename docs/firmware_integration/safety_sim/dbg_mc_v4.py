"""Diagnose the single P2 in MC ext+nina_outages, fix6 + STM32 v4 (no rule 4)."""
import safety_sim_review6 as S
hits = []
orig_p2 = S.p2_ok
def p2(frames, k, ts):
    ok, run = orig_p2(frames, k, ts)
    if not ok:
        hits.append((k, ts, frames))
    return ok, run
S.p2_ok = p2
orig_sim = S.simulate
state = {"n": 0}
def sim(*a, **kw):
    g, link, r, lat = orig_sim(*a, **kw)
    state["n"] += 1
    if hits and "done" not in state:
        state["done"] = True
        k, ts, frames = hits[0]
        print("run", state["n"], "stale step at", ts / 1e6, "outages", [(o[0], o[1]/1e6, o[2]/1e6) for o in link.out])
        print("violations", r["v"][:3])
        for f in frames[max(0, k - 14):k + 2]:
            pk = f["pkt"]
            print(f"  idx={pk['idx']} {f['kind']:3s} c={(f['c'] or 0)/1e6:.3f} d={f['d']/1e6:.3f} p={f['p']} trk={pk['trk']} age={pk['age']} "
                  f"att={pk['t_stamp']/1e6:.3f} fin={pk.get('t_fin',0)/1e6:.3f} rx={pk.get('t_rx',0)/1e6:.3f} drop={pk.get('dropped',False)}")
    return g, link, r, lat
S.simulate = sim
print(S.monte_carlo("fix6", "v4", runs=500, mix="ext", link_out=True))
