#!/usr/bin/env python3
"""How far would the entry bar have to fall before this flight latched?

The entry-gate margin reported per flight as a run length answers "how many
consecutive frames did it get".  This asks the same question in the units the
team actually turns: FOR EACH FLIGHT, THE HIGHEST BAR AT WHICH ITS OWN TRACE
WOULD HAVE PRODUCED A RUN OF 3.  Call it b*.  A flight that latched at the bar
it flew has b* >= that bar.  A flight that did not has b* < it, and the gap
says whether the bar was nearly enough or nowhere near.

b* is computed by scanning the flight's own confidence trace: for every distinct
confidence value v present, ask whether `conf >= v` contains a run of 3.  The
largest such v is b*.  This is a property of the trace, so for a flight that
never latched it is exact; for one that DID latch it is only exact up to the
first latch, because after that the drone moves and the trace is its own
consequence -- so b* is also reported pre-latch only, which is the comparable
number.

Also runs Fisher's exact test on latch counts per cell, and pools the 0.75 arm
with 2026-09-15-typical-person's 0.75 flights (same scenes, same setup, same
shipped defaults, flown with no flag rather than with the flag at its default
value -- behaviourally the same command line).

Usage: nemoenv/bin/python margin_threshold.py <suite_dir>
"""
import csv
import itertools
import json
import sys
from math import comb
from pathlib import Path

D = Path(sys.argv[1])
LAST = Path("/Users/saimaruvada/Downloads/drone/pytorch_ssd/docs/eval_results"
            "/2026-09-15-typical-person/runs")
OUT = []


def P(s=""):
    print(s, flush=True)
    OUT.append(s)


def trace(rd):
    rows = [r for r in csv.DictReader(open(rd / "follow_log.csv")) if r.get("event") == ""]
    conf = [float(r["conf"]) for r in rows if r["conf"] not in ("", "nan")]
    trk = [int(float(r["tracking"] or 0)) for r in rows]
    first = next((i for i, x in enumerate(trk) if x), None)
    return conf, trk, first


def longest(conf, bar):
    ab = [c >= bar for c in conf]
    rs = [len(list(g)) for k, g in itertools.groupby(ab) if k]
    return max(rs) if rs else 0


def bstar(conf, need=3):
    """Highest bar at which this trace contains a run of `need` frames."""
    best = None
    for v in sorted(set(conf), reverse=True):
        if longest(conf, v) >= need:
            best = v
            break
    return best


def fisher(a, b, c, d):
    """Two-sided Fisher exact on [[a,b],[c,d]]."""
    n = a + b + c + d
    r1, c1 = a + b, a + c

    def p(x):
        return comb(r1, x) * comb(n - r1, c1 - x) / comb(n, c1)
    obs = p(a)
    lo = max(0, c1 - (n - r1))
    hi = min(r1, c1)
    return sum(p(x) for x in range(lo, hi + 1) if p(x) <= obs + 1e-12)


P("=" * 104)
P("ENTRY-GATE MARGIN EXPRESSED AS A THRESHOLD")
P("b* = the highest entry bar at which this flight's own trace contains 3 consecutive frames.")
P("A flight latches iff its flown bar <= b*.  'pre' restricts the trace to before the first latch.")
P("=" * 104)
P(f"{'run':<36}{'flown bar':>10}{'latched':>9}{'b* whole':>10}{'b* pre':>9}"
  f"{'margin vs 0.70':>16}{'margin vs 0.75':>16}")

rows = []
for rd in sorted((D / "runs").glob("e*")):
    if not (rd / "metrics.json").exists():
        continue
    if not json.loads((rd / "metrics.json").read_text()).get("valid"):
        continue
    c = json.loads((rd / "cell.json").read_text())
    conf, trk, first = trace(rd)
    bw = bstar(conf)
    bp = bstar(conf[:first] if first is not None else conf)
    bar = c["vis_enter"]
    m70 = (bw - 0.70) if bw is not None else None
    m75 = (bw - 0.75) if bw is not None else None
    P(f"{rd.name:<36}{bar:>10.2f}{str(bool(any(trk))):>9}"
      f"{(f'{bw:.3f}' if bw is not None else 'none'):>10}"
      f"{(f'{bp:.3f}' if bp is not None else 'none'):>9}"
      f"{(f'{m70:+.3f}' if m70 is not None else 'n/a'):>16}"
      f"{(f'{m75:+.3f}' if m75 is not None else 'n/a'):>16}")
    rows.append((c["cell_id"], f"{bar:.2f}", c["repeat"], bool(any(trk)), bw, bp))

P("")
P("=" * 104)
P("PER CELL: how far the bar would have to fall to buy a latch (worst..best of 3 flights)")
P("=" * 104)
P(f"{'cell':<22}{'arm':>6}{'latched':>9}{'b* min':>9}{'b* max':>9}   reading")
for cid in sorted({r[0] for r in rows}):
    for arm in ("0.70", "0.75"):
        rs = [r for r in rows if r[0] == cid and r[1] == arm]
        if not rs:
            continue
        bs = [r[4] for r in rs if r[4] is not None]
        nl = sum(1 for r in rs if r[3])
        if not bs:
            note = "NO bar >0 in this trace ever gives 3 in a row"
        else:
            note = (f"a bar at/below {max(bs):.3f} latches at least one flight; "
                    f"at/below {min(bs):.3f} latches all three")
        P(f"{cid:<22}{arm:>6}{str(nl)+'/'+str(len(rs)):>9}"
          f"{(f'{min(bs):.3f}' if bs else '-'):>9}{(f'{max(bs):.3f}' if bs else '-'):>9}   {note}")

P("")
P("=" * 104)
P("LATCH COUNTS, and Fisher's exact test (two-sided).  n=3 per arm is small; the p-values are")
P("reported so nobody has to guess, not because 3 vs 3 could reach significance.")
P("=" * 104)
for cid in sorted({r[0] for r in rows}):
    a = [r for r in rows if r[0] == cid and r[1] == "0.70"]
    b = [r for r in rows if r[0] == cid and r[1] == "0.75"]
    la, lb = sum(1 for r in a if r[3]), sum(1 for r in b if r[3])
    p = fisher(la, len(a) - la, lb, len(b) - lb)
    P(f"  {cid:<22} 0.70: {la}/{len(a)} latched   0.75: {lb}/{len(b)} latched   Fisher p = {p:.3f}")

# pool tonight's 0.75 with last night's 0.75 flights on the same cells
P("")
P("  Pooling tonight's 0.75 arm with 2026-09-15-typical-person's 0.75 flights")
P("  (same scenes, same ships-as setup, shipped defaults; last night passed no flag,")
P("   tonight passes the flag at its default value - the same command line behaviourally):")
for cid in sorted({r[0] for r in rows}):
    if "control" in cid:
        continue
    a = [r for r in rows if r[0] == cid and r[1] == "0.70"]
    b = [r for r in rows if r[0] == cid and r[1] == "0.75"]
    la, na = sum(1 for r in a if r[3]), len(a)
    lb, nb = sum(1 for r in b if r[3]), len(b)
    for rd in sorted(LAST.glob(f"{cid}__*")):
        mp = rd / "metrics.json"
        if not mp.exists() or not json.loads(mp.read_text()).get("valid"):
            continue
        _, trk, _ = trace(rd)
        lb += 1 if any(trk) else 0
        nb += 1
    p = fisher(la, na - la, lb, nb - lb)
    P(f"  {cid:<22} 0.70: {la}/{na}   0.75 pooled: {lb}/{nb}   Fisher p = {p:.3f}")

P("=" * 104)
(D / "tables/margin_threshold.txt").write_text("\n".join(OUT) + "\n")
