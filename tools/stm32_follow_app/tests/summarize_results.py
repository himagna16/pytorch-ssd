"""Summarize tests/results/*.txt from run_sim_all.sh.

For every timeline / Monte Carlo row: P1/P2/P3 violations of the documented Python v6 rule and of
the C controller on identical packet deliveries, land-time ranges, the step-by-step mode diff, and
(for the random-clock sections) whether the Python v6 numbers reproduce the committed review6 logs.
Exit status 1 if the C controller has any violation where the Python v6 rule has none, or if a
Python v6 row does not match the committed log.
"""
import ast
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LOGS = os.path.join(HERE, "..", "..", "..", "docs", "firmware_integration", "safety_sim", "logs")
MIX_NAMES = ["orig", "ext", "orig+nina_outages", "ext+nina_outages", "orig+nina_outages+esp_outages"]


def rows(path):
    out = []
    for line in open(path):
        line = line.strip()
        if line.startswith("{"):
            out.append(ast.literal_eval(line))
    return out


def baseline():
    """Committed review6 v6 rows: timelines by case name, MC by mix name."""
    tl, mc = {}, {}
    p = os.path.join(LOGS, "timelines.log")
    if os.path.exists(p):
        for r in rows(p):
            if r.get("fw") == "fix6" and r.get("stm32") == "v6":
                tl[r["case"]] = r
    for k in range(5):
        p = os.path.join(LOGS, "mc%d.log" % k)
        if os.path.exists(p):
            for r in rows(p):
                if r.get("fw") == "fix6" and r.get("stm32") == "v6":
                    mc[r["mc"]] = r
    return tl, mc


def main(resdir):
    tl_base, mc_base = baseline()
    bad = 0
    lines = []
    hdr = "%-58s %-9s %-16s %-16s %-17s %-17s %-7s %-9s %s" % (
        "case", "clocks", "py_v6 viol", "c6/c6w viol", "py land s", "c6w land s", "maxage", "c6 dl/nv",
        "diff_w py-vs-c6w: mism/non-shift/steps, st0 mism/packets, e_max us | diff py-vs-c6: mism/non-shift/steps")
    for fn in sorted(os.listdir(resdir)):
        if not fn.endswith(".txt") or fn == "checks.txt":
            continue
        for r in rows(os.path.join(resdir, fn)):
            name = r.get("case") or ("MC " + r["mc"])
            py, c, d = r["py_v6"], r["c6"], r["diff"]
            cw, dw = r["c6w"], r["diff_w"]
            note = ""
            for tag, cc in (("c6", c), ("c6w", cw)):
                if cc["violations"] and not py["violations"]:
                    bad += 1; note += "  <-- %s VIOLATES where v6 holds" % tag
                for k in cc["violations"]:
                    if cc["violations"][k] > py["violations"].get(k, 0):
                        note += "  <-- %s: more %s than v6" % (tag, k)
                if cc["rejected"]:
                    note += "  <-- %s: rejected packets" % tag
            if dw["non_shift"]:
                note += "  <-- mode diff"
            if "t_arm_s" in r:   # ground timelines: take-off moved, see safety_sim_review6_c.GROUND
                note += "  [take-off %gs: c6 never armed %d/%d, c6w never armed %d/%d, floor-only stale pkts %d]" % (
                    r["t_arm_s"], c["never_armed_runs"], c["runs"], cw["never_armed_runs"], cw["runs"],
                    c["rise_only_stale_packets"])
            if r["clocks"] == "random":
                ref = tl_base.get(r.get("case")) if "case" in r else mc_base.get(r.get("mc"))
                if ref is not None:
                    same = (tuple(ref["land_after_last_valid_s"] or ()) == tuple(py["land_after_last_valid_s"] or ())
                            and ref["violations"] == py["violations"]
                            and ref["max_true_age_steered_s"] == py["max_true_age_steered_s"]
                            and ref.get("never_landed", ref["runs"] - ref.get("landed", 0)) == py["never_landed"]
                            and ref["runs"] == py["runs"])
                    if not same:
                        bad += 1; note += "  <-- py_v6 differs from committed log"
                    else:
                        note += "  (py_v6 == committed log)"
            lines.append("%-58s %-9s %-16s %-16s %-17s %-17s %-7s %-9s %d/%d/%d, st0 %d, e %d | %d/%d/%d%s" % (
                name[:58], "wrap" if r["clocks"] != "random" else "random", py["violations"] or "{}",
                "%s/%s" % (c["violations"] or "{}", cw["violations"] or "{}"), py["land_after_last_valid_s"],
                cw["land_after_last_valid_s"], max(c["max_true_age_steered_s"], cw["max_true_age_steered_s"]),
                "%d/%d" % (c["arm_delayed_runs"], c["never_armed_runs"]), dw["mism"], dw["non_shift"], dw["steps"],
                dw["st0_mism"], dw["e_maxdiff_us"], d["mism"], d["non_shift"], d["steps"], note))
    print(hdr)
    print("\n".join(lines))
    chk = os.path.join(resdir, "checks.txt")
    if os.path.exists(chk):
        print("\nchecks.txt:\n" + open(chk).read().strip())
    print("\nRESULT:", "FAIL (%d)" % bad if bad else "OK")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "results")))
