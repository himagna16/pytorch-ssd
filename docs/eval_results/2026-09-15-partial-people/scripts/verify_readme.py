#!/usr/bin/env python3
"""Re-derive every number the README quotes from the tables, and fail on drift."""
import csv, math, sys
from pathlib import Path
D = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
FAILS, N = [], 0

def T(p):
    return list(csv.DictReader(open(D / p), delimiter="\t"))

def chk(name, got, want, tol=None):
    """Compare at the precision the README actually quotes: the table value is
    rounded to the number of decimals in `want` before comparing, so a 3 dp quote
    is checked against the 4 dp table exactly as a reader would read it."""
    global N
    N += 1
    if got is None:
        FAILS.append(f"  {name}: no table value"); return
    if tol is not None:
        ok = math.isclose(float(got), want, abs_tol=tol)
    else:
        # The tables are stored at 4 dp, so re-rounding them to the README's 3 dp
        # would double-round. Instead require the quote to be within half a unit
        # of the quoted precision of the stored value (5.05e-4 for a 3 dp quote),
        # which is exactly "this quote is a correct rounding of that table cell".
        dp = len(str(want).split(".")[1]) if "." in str(want) else 0
        ok = abs(float(got) - want) <= 0.5 * 10 ** (-dp) + 1e-9
    if not ok:
        FAILS.append(f"  {name}: README says {want}, table says {got}")

SS = {(r["stratum"], r["chain"], r["arm"]): r for r in T("tables/size_standardised.tsv")}
FB = {(r["stratum"], r["chain"], r["arm"]): r for r in T("tables/flown_band.tsv")}
HB = {(r["stratum"], r["chain"], r["arm"]): r for r in T("tables/hold_band.tsv")}
VF = {(r["grading"], r["bin_lo"], r["chain"], r["arm"]): r for r in T("tables/visible_fraction.tsv")}
GE = {r["range_m"]: r for r in T("tables/geometry_fov.tsv")}

# --- section 1, geometry
for rng, vf in (("1.285", 1.0), ("1.200", 0.965), ("1.000", 0.824),
                ("0.750", 0.618), ("0.500", 0.412), ("2.430", 1.0), ("3.640", 1.0)):
    chk(f"geom vis_frac @{rng}", GE[rng]["visible_fraction"], vf, 1e-3)
chk("geom px128 @1.50 (flown-band top)", GE["1.500"]["px128_h_visible"], 103.59, 0.02)
chk("geom px128 @2.43", GE["2.430"]["px128_h_visible"], 63.9, 0.05)

# --- section 4, flown band, band-cut
for arm, ge, lt in (("chip", 0.765, 0.074), ("float", 0.787, 0.088), ("fq", 0.787, 0.081)):
    chk(f"FB whole_upright via244 {arm} >=.75", FB[("whole_upright","via244",arm)]["frac_ge_0.75"], ge)
    chk(f"FB whole_upright via244 {arm} <.45", FB[("whole_upright","via244",arm)]["frac_lt_0.45"], lt)
for arm, ge, lt in (("chip", 0.697, 0.124), ("float", 0.674, 0.148), ("fq", 0.659, 0.158)):
    chk(f"FB occl_or_trunc via244 {arm} >=.75", FB[("occl_or_trunc","via244",arm)]["frac_ge_0.75"], ge)
    chk(f"FB occl_or_trunc via244 {arm} <.45", FB[("occl_or_trunc","via244",arm)]["frac_lt_0.45"], lt)

# --- section 5, size-standardised, chip/via244
for strat, f75, d75, dlo, dhi, e45, de, elo, ehi in [
    ("whole_upright",   0.765, 0.000,  0.000, 0.000, 0.074, 0.000,  0.000, 0.000),
    ("occl_only",       0.790, 0.025, -0.057, 0.113, 0.075, 0.002, -0.052, 0.054),
    ("trunc_only",      0.616,-0.149, -0.244,-0.060, 0.172, 0.098,  0.040, 0.154),
    ("crop_trunc_only", 0.592,-0.172, -0.267,-0.087, 0.186, 0.113,  0.046, 0.176),
    ("edge_trunc_only", 0.551,-0.214, -0.310,-0.109, 0.201, 0.127,  0.056, 0.198),
    ("top_cut",         0.454,-0.311, -0.463,-0.160, 0.182, 0.109,  0.003, 0.227),
    ("trunc_and_occl",  0.662,-0.103, -0.195,-0.012, 0.151, 0.078,  0.015, 0.144),
    ("clean_other",     0.821, 0.057, -0.021, 0.156, 0.047,-0.026, -0.084, 0.020),
    ("no_keypoints",    0.194,-0.571, -0.753,-0.367, 0.511, 0.438,  0.203, 0.663),
    ("occl_or_trunc",   0.696,-0.069, -0.143, 0.008, 0.123, 0.050,  0.002, 0.097)]:
    r = SS[(strat, "via244", "chip")]
    chk(f"SS {strat} >=.75", r["std_frac_ge_0.75"], f75)
    chk(f"SS {strat} d75", r["d_vs_whole_upright"], d75)
    chk(f"SS {strat} d75 lo", r["d_ge_lo"], dlo); chk(f"SS {strat} d75 hi", r["d_ge_hi"], dhi)
    chk(f"SS {strat} <.45", r["std_frac_lt_0.45"], e45)
    chk(f"SS {strat} dexit", r["d_exit_vs_whole_upright"], de)
    chk(f"SS {strat} dexit lo", r["d_lt_lo"], elo); chk(f"SS {strat} dexit hi", r["d_lt_hi"], ehi)
# the other two arms quoted for occl_or_trunc
for arm, d75, e in (("float", -0.113, 0.058), ("fq", -0.129, 0.076)):
    r = SS[("occl_or_trunc", "via244", arm)]
    chk(f"SS occl_or_trunc {arm} d75", r["d_vs_whole_upright"], d75)
    chk(f"SS occl_or_trunc {arm} dexit", r["d_exit_vs_whole_upright"], e)
# himax quotes
for strat, d75, de in (("occl_or_trunc", -0.173, 0.072), ("occl_only", -0.128, 0.025)):
    r = SS[(strat, "himax", "chip")]
    chk(f"SS-himax {strat} d75", r["d_vs_whole_upright"], d75)
    chk(f"SS-himax {strat} dexit", r["d_exit_vs_whole_upright"], de)

# --- hold band quotes
for strat, ge, lt in (("whole_upright", 0.778, 0.049), ("occl_only", 0.872, 0.017),
                      ("trunc_only", 0.638, 0.133), ("top_cut", 0.478, 0.087)):
    chk(f"HB {strat} >=.75", HB[(strat,"via244","chip")]["frac_ge_0.75"], ge)
    chk(f"HB {strat} <.45", HB[(strat,"via244","chip")]["frac_lt_0.45"], lt)
chk("HB whole_upright himax chip >=.75", HB[("whole_upright","himax","chip")]["frac_ge_0.75"], 0.749)
chk("HB whole_upright himax chip <.45", HB[("whole_upright","himax","chip")]["frac_lt_0.45"], 0.095)

# --- section 6, visible fraction, chip
for lo, ge, lt, gh, lh in (("0.999", 0.772, 0.073, 0.640, 0.135),
                           ("0.900", 0.708, 0.101, 0.596, 0.131),
                           ("0.750", 0.693, 0.139, 0.598, 0.169),
                           ("0.500", 0.607, 0.180, 0.496, 0.224),
                           ("0.000", 0.490, 0.265, 0.356, 0.367)):
    chk(f"VF {lo} via244 ge75", VF[("crop_vis_frac",lo,"via244","chip")]["frac_ge_0.75"], ge)
    chk(f"VF {lo} via244 <.45", VF[("crop_vis_frac",lo,"via244","chip")]["frac_lt_0.45"], lt)
    chk(f"VF {lo} himax >=.75", VF[("crop_vis_frac",lo,"himax","chip")]["frac_ge_0.75"], gh)
    chk(f"VF {lo} himax <.45", VF[("crop_vis_frac",lo,"himax","chip")]["frac_lt_0.45"], lh)

# --- derived arithmetic the README states
chk("ratio pooled", 0.123/0.074, 1.66, 0.01)
chk("ratio trunc", 0.172/0.074, 2.32, 0.01)
chk("head limit 1.7 m", (1.7-0.8)/0.70021, 1.285, 1e-3)
chk("head limit 1.9 m", (1.9-0.8)/0.70021, 1.571, 1e-3)
chk("head limit 2.0 m", (2.0-0.8)/0.70021, 1.714, 1e-3)
chk("crop width at 1.94 m", 2*1.94*0.70021, 2.72, 5e-3)

print(f"{N - len(FAILS)}/{N} claims verified")
if FAILS:
    print("FAILED:"); print("\n".join(FAILS)); sys.exit(1)
print("ALL CLAIMS VERIFIED")
