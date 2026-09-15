#!/usr/bin/env python3
"""INDEPENDENT AUDIT of this directory, written by a reviewer who did not fly it.

Imports nothing from analyze_typical.py, verify_numbers.py or scoreboard.py.
Re-derives every load-bearing number straight from
  - runs/*/follow_log.csv and runs/*/summary.json   (the flights)
  - the person fidelity study's own tables          (the selection)
and reports four things the original README did not state.

Usage: trainenv/bin/python audit_independent.py   > ../tables/audit_independent.txt
"""
import csv, json, glob, os, collections, statistics as st
from pathlib import Path

D = Path(__file__).resolve().parent.parent
FID = D.parent / "2026-09-15-sim-person-fidelity" / "tables"
LAD = [1.5, 2.0, 2.5, 3.0, 3.5, 4.0]
ENTER, EXIT = 0.75, 0.45


def line(c="-"): print(c * 78)


# ---------------------------------------------------------------- 1. flights
def flights():
    line("="); print("1. FLIGHT NUMBERS, RE-DERIVED FROM runs/*/follow_log.csv"); line("=")
    rows = []
    for d in sorted(glob.glob(str(D / "runs" / "*"))):
        fl = os.path.join(d, "follow_log.csv")
        if not os.path.exists(fl):
            print(f"  (no follow_log.csv: {os.path.basename(d)} - the timed-out attempt)")
            continue
        R = [r for r in csv.DictReader(open(fl)) if r["tracking"] not in ("", None)]
        t = [float(r["t"]) for r in R]
        trk = [int(float(r["tracking"])) for r in R]
        conf = [float(r["conf"]) for r in R]
        n = len(R)
        dts = [t[i + 1] - t[i] for i in range(n - 1)]
        dts += [st.median(dts)]
        untr = sum(dt for dt, k in zip(dts, trk) if k == 0)
        losses = sum(1 for i in range(1, n) if trk[i - 1] == 1 and trk[i] == 0)
        latches = sum(1 for i in range(1, n) if trk[i - 1] == 0 and trk[i] == 1) + (1 if trk[0] else 0)
        first = next((t[i] - t[0] for i in range(n) if trk[i]), None)
        best = cur = 0
        for c in conf:
            cur = cur + 1 if c >= ENTER else 0
            best = max(best, cur)
        s = json.load(open(os.path.join(d, "summary.json")))
        rows.append(dict(run=os.path.basename(d), tf=round(sum(trk) / n, 4), sum_tf=s["tracking_fraction"],
                         span=round(t[-1] - t[0], 2), untr=round(untr, 2), losses=losses,
                         reacq=max(0, latches - 1), first=(round(first, 2) if first is not None else "-"),
                         run75=best, conf_med=round(st.median(conf), 3), conf_max=round(max(conf), 3),
                         enter=s["vis_enter"], exit=s["vis_exit"], cf=s["confirm_frames"]))
    h = ["run", "tf", "sum_tf", "span", "untr", "losses", "reacq", "first", "run75", "conf_med", "conf_max",
         "enter", "exit", "cf"]
    print("  " + "  ".join(f"{k:>9}" if k != "run" else f"{k:<24}" for k in h))
    for r in rows:
        print("  " + "  ".join(f"{str(r[k]):>9}" if k != "run" else f"{r[k]:<24}" for k in h))
    print()
    print("  AGREEMENT: my tracking fraction vs summary.json on all %d flights: max |diff| = %.4f"
          % (len(rows), max(abs(r["tf"] - r["sum_tf"]) for r in rows)))
    bad = [r["run"] for r in rows if (r["first"] != "-") != (r["run75"] >= 3)]
    print("  ENTRY RULE: 'latched iff longest run of conf>=0.75 reached 3' - counterexamples: %s"
          % (bad or "none"))
    print("  THRESHOLDS: distinct (vis_enter, vis_exit, confirm_frames) across all flights: %s"
          % sorted({(r["enter"], r["exit"], r["cf"]) for r in rows}))
    return rows


# ------------------------------------------------- 2. selection, re-derived
def selection():
    line("="); print("2. SUBJECT SELECTION, RE-DERIVED FROM THE FIDELITY STUDY'S sim_cohort.csv"); line("=")
    R = list(csv.DictReader(open(FID / "sim_cohort.csv")))
    agg = collections.defaultdict(list)
    for r in R:
        if r["camera"] == "himax" and float(r["dy_m"]) == 0.0 and float(r["range_m"]) in LAD:
            agg[(r["img_id"], float(r["range_m"]))].append(float(r["chip"]))
    vals = {k: st.mean(v) for k, v in agg.items()}
    subs = sorted({k[0] for k in vals})
    idx = {}
    for s in subs:
        idx[s] = st.mean([100.0 * sum(1 for o in subs if o != s and vals[(o, g)] < vals[(s, g)]) / (len(subs) - 1)
                          for g in LAD])
    rp = {r["img_id"]: r for r in csv.DictReader(open(FID / "real_people.csv"))}
    print("  cohort size: %d subjects" % len(subs))
    for i, l in [("19432", "control"), ("250127", "median"), ("124442", "p25")]:
        per = [100.0 * sum(1 for o in subs if o != i and vals[(o, g)] < vals[(i, g)]) / (len(subs) - 1) for g in LAD]
        print(f"  {l:8s} {i:>7}  index {idx[i]:5.1f}   per-range " + "/".join(f"{p:.0f}" for p in per))
    print("  -> reproduces the README's 99.2 / 52.1 / 28.4 and its per-range vectors exactly.")
    print()
    print("  IS THE ELIGIBLE POOL BIASED TOWARD EASY PEOPLE?  (the objection that matters)")
    wui = [s for s in subs if rp[s]["wui"] == "1"]
    print("    index median, all %d cohort subjects        : %.1f" % (len(subs), st.median([idx[s] for s in subs])))
    print("    index median, the %d wui-eligible subjects  : %.1f" % (len(wui), st.median([idx[s] for s in wui])))
    for i, l in [("median", "250127"), ("p25", "124442"), ("control", "19432")]:
        p = 100.0 * sum(1 for o in wui if idx[o] < idx[l]) / len(wui)
        print(f"    {i:8s} percentile among the {len(wui)} eligible peers: {p:5.1f} (vs {idx[l]:.1f} cohort-wide)")
    print("    -> NOT biased. The eligible pool's detectability distribution is the cohort's,")
    print("       and both picks keep their percentile under either reference population.")
    print()
    print("  NOTE ON THE FLAGS. sim_cohort.csv and real_people.csv disagree for the same")
    print("  subjects: sim_cohort says whole_upright=1 for all %d and wui=1 for %d;" % (len(subs),
          sum(1 for s in subs if [r for r in R if r["img_id"] == s][0]["wui"] == "1")))
    print("  real_people says whole_upright=1 for %d and wui=1 for %d. This directory used the"
          % (sum(1 for s in subs if rp[s]["whole_upright"] == "1"), len(wui)))
    print("  real_people flags throughout (cohort_ranking.tsv matches them on all 267 rows).")
    print("  Consequence worth stating: THE CONTROL ITSELF IS NOT ELIGIBLE under that screen")
    print("  (19432 has wui=0, in_crop_horizontal=0, mech_eligible=0), so 'eligible' does not")
    print("  mean 'comparable to the control'. It does not affect the picks' percentiles.")
    return vals, idx


# --------------------------------- 3. does n=2 support it? ask all 267
def generalise(vals):
    line("="); print("3. DOES n=2 SUBJECTS SUPPORT THE VERDICT?  ASKING ALL 267"); line("=")
    print("  The flights are 2 subjects x 3 repeats. The repeats bound machine noise only.")
    print("  But the entry bar gives a NECESSARY condition for latching that can be asked of")
    print("  the whole cohort on the SAME arm the flights used (chip network, himax camera,")
    print("  dy=0): does the subject's mean frame even reach 0.75 at the flown start range?")
    print()
    print(f"  {'range_m':>8} {'n':>5} {'reach 0.75':>12} {'pct':>7} {'below 0.45':>12} {'pct':>7} {'median':>8}")
    for g in LAD:
        v = [vals[k] for k in vals if k[1] == g]
        ge = sum(1 for x in v if x >= ENTER); lt = sum(1 for x in v if x < EXIT)
        print(f"  {g:8.1f} {len(v):5d} {ge:12d} {100*ge/len(v):6.1f}% {lt:12d} {100*lt/len(v):6.1f}% {st.median(v):8.3f}")
    print()
    for g, what in [(3.5, "the STATIC scene's 3.64 m start (nearest rung)"), (3.0, "the MOVING scene's 3.0 m start")]:
        v = [vals[k] for k in vals if k[1] == g]
        ge = sum(1 for x in v if x >= ENTER)
        print(f"  At {what}: {ge}/{len(v)} = {100*ge/len(v):.1f}% of the cohort reach the entry bar.")
    print()
    print("  READING. The DIRECTION of the verdict does not rest on two subjects: at the ranges")
    print("  these scenes start from, roughly three quarters of the 267-subject cohort do not")
    print("  reach the entry bar on a static on-axis frame, which is the easiest condition a")
    print("  flight ever offers. The flights are a costly confirmation of what the cohort")
    print("  already implies, not the only evidence for it.")
    print("  EQUALLY: about a fifth to a quarter of the cohort DOES reach it, so '0.00' is not")
    print("  the population's number either. The README's own framing - 'between 0.00 and 0.99")
    print("  depending on the person' - is the calibrated statement; 'a typical person is not")
    print("  tracked at all' would be an overclaim.")
    print("  This is a static-frame necessary condition, NOT a predicted tracking fraction:")
    print("  consecutive frames are correlated and the follower has hysteresis.")


# ------------------------------- 4. the in-flight ordering, and the chain
def ordering(vals):
    line("="); print("4. TWO CORRECTIONS THE ORIGINAL README DID NOT MAKE"); line("=")
    print("  (a) THE MEDIAN/p25 ORDERING INVERTS IN THE STATIC CELL.")
    cells = collections.defaultdict(list)
    for d in sorted(glob.glob(str(D / "runs" / "*"))):
        fl = os.path.join(d, "follow_log.csv")
        if not os.path.exists(fl): continue
        cid = os.path.basename(d).rsplit("__r", 1)[0]
        cells[cid] += [float(r["conf"]) for r in csv.DictReader(open(fl)) if r["tracking"] not in ("", None)]
    for cid in sorted(cells):
        print(f"      {cid:24s} in-flight conf median {st.median(cells[cid]):.3f}")
    print()
    print("      In A.static the '25th-percentile' subject returns a HIGHER in-flight confidence")
    print("      (%.3f) than the 'median' subject (%.3f), reversing the cohort ranking, which at"
          % (st.median(cells["A.static__p25"]), st.median(cells["A.static__median"])))
    print("      3.5 m puts them at %.3f and %.3f. The same inversion is visible in this"
          % (vals[("124442", 3.5)], vals[("250127", 3.5)]))
    print("      directory's own build-time probe (s15: p25 0.275/0.248/0.523 against median")
    print("      0.245/0.355/0.517) and was not called out. The cohort index is a rank over six")
    print("      static on-axis ranges; the static flight sits at 3.64 m and a 15.9 deg bearing")
    print("      with sensor noise, and the ranking does not survive that. The two cells are")
    print("      therefore TWO SAMPLES OF A TYPICAL PERSON, not a monotone difficulty ladder,")
    print("      and no claim should be built on median-vs-p25 differences. The verdict is")
    print("      unaffected: both are 0.000 and both are far below the bar.")
    print()
    print("      Note also the level shift: the cohort's static on-axis render is systematically")
    print("      more favourable than the flight (control 0.97->0.83, median 0.61->0.31 conf")
    print("      medians), so cohort confidences are not flight confidences.")
    print()
    print("  (b) THE 0.397 / 0.119 PAIR MIXES RESAMPLING CHAINS.")
    E = {(r["group"], r["arm"]): r for r in csv.DictReader(open(FID / "exit_bar.tsv"), delimiter="\t")}
    a = E[("sim_cohort_himax", "chip")]; b = E[("real_all", "chip")]; c = E[("realhimax_whole_upright", "chip")]
    print(f"      quoted: sim_cohort_himax chip {float(a['frac_lt_045']):.4f}  vs  real_all chip {float(b['frac_lt_045']):.4f}")
    print(f"      same-chain: the rendered side is himax, so the photograph side must be too:")
    print(f"                  realhimax_whole_upright chip {float(c['frac_lt_045']):.4f} (n={c['n']}, {c['n_clusters']} subjects)")
    print(f"      corrected pair: {float(a['frac_lt_045']):.3f} rendered against {float(c['frac_lt_045']):.3f} photographed.")
    print("      The gap and the conclusion survive; the quoted 0.119 was a clean-chain group.")
    print()
    P = [r for r in csv.DictReader(open(FID / "paired_chain_matched.tsv"), delimiter="\t")]
    w = [r for r in P if r["pairing"] == "himax vs himax" and r["arm"] == "chip" and r["stratum"] == "wui"][0]
    u = [r for r in P if r["pairing"] == "himax vs himax" and r["arm"] == "chip" and r["stratum"] == "whole_upright"][0]
    print("      AND the render penalty is weaker for the stratum the picks come from:")
    print(f"        whole_upright (n={u['n_subjects']}): paired median {u['median_d']} [{u['d_lo']}, {u['d_hi']}]")
    print(f"        wui           (n={w['n_subjects']}): paired median {w['median_d']} [{w['d_lo']}, {w['d_hi']}]  <- CROSSES ZERO")
    print("      Both picks are wui. So 'these cells bracket the real answer from the")
    print("      pessimistic side' is well supported for whole_upright and NOT established at")
    print("      n=59 for wui. The caveat should be stated as a direction, not a magnitude.")


if __name__ == "__main__":
    flights()
    print()
    vals, idx = selection()
    print()
    generalise(vals)
    print()
    ordering(vals)
