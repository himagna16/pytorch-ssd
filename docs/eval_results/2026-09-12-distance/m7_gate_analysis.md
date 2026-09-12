# Is the M7 distance gate reachable? — Sep 12, 2026

An analysis of the M7 distance-keeping gate in `tools/crazysim_macos/scoreboard.py`,
commissioned on the premise that *"the M7 gate demands settling at 1.94 m, the control
law's floor is 2.43 m, therefore the gate cannot be passed by correct code."*

**The premise is wrong, and the real defect is worse.** The 2.43 m floor is real and I
confirm it below, but the gate's tolerance was deliberately sized to absorb it, and one
cell in the very suite that failed — `A.static__proven` — passes both M7 gates, 5 runs
out of 5. What M7 actually suffers from is that both of its gated numbers are dominated
by an **uncommanded forward drift**: 30–55% of the closure in the static cells (depending
on how the follower's command latency is attributed — see §5.2) happened while the follower
was commanding `vx = 0`, and the `A.static__proven` verdict flips from FAIL to PASS purely
on whether the cell is scored at 35 s or at 45 s.

**This document changes nothing.** It is a recommendation for a human decision. No
shared file was edited; the only file written is this one.

---

## 0. Status of every claim

| claim | status |
|---|---|
| The control law cannot *command* closing inside 2.428 m | **confirmed** — arithmetic below, and 0 of 683 flight frames inside 2.428 m read bucket ≤ 1 |
| "2.428 m is the floor of this controller" | **confirmed with a correction** — it is the floor of *commanded* motion on an approach from far; it is not the floor of the *measured* distance, which goes to 2.218 m |
| The M7 gate cannot be passed by a correct controller | **REFUTED** — a perfect head parking at 2.428 m scores 0.486 m against a 0.75 m gate and sits inside the band, with 0.264 m / 0.243 m of headroom |
| No cell passes M7 | **REFUTED** — `A.static__proven` PASSES both M7 gates, 5/5 runs |
| 1.94 m was chosen carelessly | **REFUTED** — `scratchpad/simv2/spec_metrics.md` §3 derives it, derives the 2.43 m parking point, and sets 0.75 m *because of* it |
| `M7_dist_err_settled_mean_m` measures a settled hold | **refuted** — the window opens 14–17 s in with the drone 2.93–3.46 m out and still moving |
| The two M7 gates are independent | **refuted** — on all 22 runs the mean gate reduces to "window mean ≤ 2.692 m", the band gate to "final ≤ 2.671 m" |
| M7's verdict is purely a property of the drone's behaviour | **refuted** — it is also duration-dependent; `A.static__proven`'s cell verdict is FAIL at every truncation ≤ 35 s and PASS at 40 s and 45 s |

**Nothing here was flown, and no hardware was involved.** Every number comes from the
arithmetic of the control law or from the already-published Sep-11 flight logs.

---

## 1. What the gate actually requires

`scoreboard.py:62-64` and `:405-434`, with `H = 1.7`, `CROP_FOV_DEG = 70`:

```
tan(35deg) = 0.700208

--- representable distances: the 4 bucket CENTRES (the only size_values the law ever sees) ---
  centre s=0.125 -> d =   9.711 m   vx = clip(0.8*(0.625-0.125), 0.3) = +0.30 m/s
  centre s=0.375 -> d =   3.237 m   vx = clip(0.8*(0.625-0.375), 0.3) = +0.20 m/s
  centre s=0.625 -> d =   1.942 m   vx = clip(0.8*(0.625-0.625), 0.3) = +0.00 m/s
  centre s=0.875 -> d =   1.387 m   vx = clip(0.8*(0.625-0.875), 0.3) = -0.20 m/s

--- bucket EDGES -> the switching distances ---
  edge  s=0.250 -> d =   4.856 m
  edge  s=0.500 -> d =   2.428 m
  edge  s=0.750 -> d =   1.619 m

--- scoreboard constants ---
  HOLD_K=1.1425  d_hold=1.942 m
  band = [1.619, 2.428] m   width 0.809 m  half-width +/-0.405 m
  band widened 10% = [1.457, 2.671] m   <- M7_final_in_band accepts anything in here
```

Only four size values exist, so only four distances are "representable" in the sense of
the brief: 9.711, 3.237, 1.942 and 1.387 m. But that framing misleads, because the law is
not a quantiser that snaps to those points — it is a **dead-zone controller**. `vx` is
exactly zero across the *whole* of bucket 2, so **every distance in [1.619, 2.428] m is an
equilibrium**. The controller is stable anywhere in a 0.81 m band, and which point in the
band it occupies is decided by how it entered.

The two gated quantities (`scoreboard.py:666-669`):

| gate | definition | threshold |
|---|---|---|
| `M7_dist_err_settled_mean_m` | `mean(abs(d_true[win] - 1.942))` | `<= 0.75` m |
| `M7_final_in_band` | `1.457 <= d_true[-1] <= 2.671` | `== 1.0` |

Both are scored on the **median over the cell's runs**.

---

## 2. The 2.43 m floor: confirmed, with one correction

The suite always starts the drone far away (3.64 m static, ~3.2 m moving) and closes. A
size head with no error flips from bucket 1 to bucket 2 at image fraction 0.500, i.e.
`d = 1.7 / (2 x 0.500 x tan35) = 2.428 m`, and `vx` goes to zero there. The drone
overshoots by at most one frame period of travel — `0.2 m/s / 14 Hz = 0.0143 m` at full
rate, `0.2 / 6.5 = 0.0308 m` at chip speed — so a perfect head parks at 2.397–2.428 m.
**It cannot command its way closer.** That much of the README §4 claim is correct, and the
flight logs back it: pooled over 22 published runs, **0 of 683 tracking frames taken inside
2.428 m read a bucket ≤ 1**, so no under-read ever gave the drone permission to keep closing.

The correction: *"2.428 m is the floor of this controller"* is true of **commanded** motion
only. The measured distance goes well inside it — `A.static__proven` finished at 2.218 m
and 2.230 m on two of five runs. §5 shows how.

Two further notes on the floor:

- It is a floor **of the approach**, not of the law. Started at 1.4 m, the same law backs
  up at 0.2 m/s and parks at the *near* edge, 1.619 m — closer than the 1.942 m target,
  not further. Nothing in the controller prefers 2.428 m; the suite's initial conditions do.
- The spec anticipated it exactly. It is not a discovery.

---

## 3. Why the gate is nonetheless passable — and was passed

Put a perfect head and this control law together and score it:

```
--- what a PERFECT size head + this law does, approaching from far ---
  stops on entry to bucket 2 at d = 2.428 m
  |err| vs d_hold = 0.486 m     M7 mean gate is <= 0.75 m -> PASS  (headroom 0.264 m)
  final in widened band? True                         (headroom 0.243 m to the outer edge)
```

A correct controller passes both gates. The claim that M7 "makes every run fail for a
reason unrelated to the drone behaviour" is false as stated.

And it is not only theory. From `docs/sim_results/2026-09-11-simv2/scoreboard.json`:

```
== A.static__proven verdict PASS
  {"id": "M7_dist_err_settled_mean_m", "value": 0.669, "op": "<=", "threshold": 0.75,
   "result": "PASS", "spread": [0.611, 0.953]}
  {"id": "M7_final_in_band", "value": 1.0, "op": "==", "threshold": 1.0,
   "result": "PASS", "spread": [true, true]}
```

Five runs out of five, in the suite this whole investigation is about. `B.moving__proven`
passes the mean gate too (0.744 vs 0.750 — a 0.006 m margin) and fails only
`M7_final_in_band`, by 0.01–0.04 m: its five finals are 2.657, 2.680, 2.682, 2.710,
2.712 m against a 2.671 m ceiling.

So M7 is not an impossible gate. It is a **tight** gate whose budget is mostly spent
before the drone does anything: 0.486 m of the 0.75 m mean allowance, and 2.428 m of the
2.671 m ceiling, are consumed by the structural offset, leaving ~0.25 m for everything
else — head noise, bearing error, subject motion. That is a fair criticism of M7. It is a
different criticism from the one I was asked to confirm.

### 3.1 The two gates are one gate

On all 22 published person-following runs, `M7_dist_err_settled_mean_m` equals
`M7_size_window_dist_mean_m - 1.942` to within 0.001 m — i.e. **the `abs()` never bites**,
because the drone is never inside 1.942 m during the window:

```
cell/run                           win_dist_mean  M7_mean  win_mean-1.942   final
A.static__proven__r2a1                     2.553    0.611           0.611   2.230
A.static__proven__r5a1                     2.611    0.669           0.669   2.218
B.moving__proven__r5a1                     2.687    0.744           0.745   2.712
A.static__ships__r4a1                      3.413    1.471           1.471   3.345
...  (all 22 rows agree to 0.001 m)
```

So in practice the mean gate says "window mean ≤ 2.692 m" and the band gate says
"final ≤ 2.671 m". The lower band edge (1.457 m) never binds either — the closest any run
finished was 2.218 m. **M7 is a one-sided distance cap wearing the costume of a two-sided
error metric**, and the two gates ask nearly the same question. Whatever is decided, that
duplication should be collapsed or acknowledged.

---

## 4. Where 1.94 m came from

`/private/tmp/.../scratchpad/simv2/spec_metrics.md` §3, "Deriving hold distance in metres
from the size bucket", is the origin. It is not a careless number. The spec derives
`d(s) = H / (2 s tan(phi/2))`, notes that the controller drives
`vx = k_fwd * (0.625 - size_value)` and therefore stops when the decoded size equals the
bucket-2 centre, gets `d_hold = 1.1425 H = 1.94 m`, and then — in the same section —
writes out the entire objection this workstream was convened to raise:

> "The **best possible** steady-state distance error is up to **±0.40 m**. No tuning of
> `k_fwd` improves it; only a finer size head (more buckets, or a scalar size output) would."
>
> "The drone approaches from far away and stops **on entry** to the band, so it parks near
> the **far** edge (~2.43 m, error ~0.49 m), not at the centre. A threshold set near 0.4 m
> would fail a perfectly correct controller."
>
> "Any gate must pass that comfortably. Hence the 0.75 m gate in §4, M7."

That reasoning is carried into the code. `GATE_BASIS["M7_mean"]` in `scoreboard.py:82`:

> "quantisation floor is +-0.40 m and the approach parks near the far edge (~0.49 m);
> 0.75 m is ~1.5x that structural floor, and the verified 2.3 m static baseline scores 0.36 m"

**So neither the target nor the threshold is the thing that is wrong.** The target is a
correctly derived description of what the control law aims at; the threshold was sized
with the 2.43 m parking point explicitly in hand. What is wrong is downstream of both:
the *reporting* ("target 1.94" as the headline in `scoreboard.md`, the sim README,
`EXPERIMENTS.md` and `docs/progress/sai_maruvada.md`) presents 1.94 m as the number the
drone missed, when no one ever expected the drone to reach it. That is a documentation
defect, and the README's §8 item 3 is right to flag it — but it is not a gate defect.

---

## 5. The defect that *is* there: M7 mostly measures an uncommanded drift

This is the finding that should drive the decision, and as far as I can tell it has not
been reported anywhere.

### 5.1 The drone keeps closing with `vx` commanded to zero

Trace of `A.static__proven__r5a1`, 5-second bins. The subject is pinned at (3.500, −1.000)
— verified from `truth.csv`, which shows zero variation in both coordinates:

```
     t win  d mean   bkt hist (0/1/2/3)  vx>0 %  trk%
  15- 20s   3.073       [0, 16, 59, 0]    21.3    100
  20- 25s   2.847        [0, 0, 74, 0]     0.0    100
  25- 30s   2.697        [0, 9, 66, 0]    12.0    100
  30- 35s   2.483        [0, 0, 75, 0]     0.0    100
  35- 40s   2.362        [0, 0, 74, 0]     0.0    100
  40- 45s   2.263        [0, 0, 75, 0]     0.0    100
```

From 30 s to 45 s the bucket reads 2 on every single frame, `vx` is commanded 0.00 on every
single frame — and the distance falls from 2.483 m to 2.263 m. A linear fit over the 426
frames of that run with `cmd_vx == 0` and `bucket == 2` gives **−32.5 mm/s**.

### 5.2 It is systematic, and it is most of the closure

Sum `d[i+1] - d[i]` over every consecutive frame pair where the command was logged as
exactly `vx = 0` and the drone was tracking. Static scene only, so every change in `d` is
the drone moving. **One assumption, flagged by the verifier (see the note under the
table):** the logged `cmd_vx` is the command *computed* at that row, and
`follow_person.py`'s latency FIFO applies it one `applied_lat_ms` later — 12 ms median on
the float cells, 156 ms on the chip cells, which at 6.5 Hz is a full frame period.

```
run (static scene)             total d change  moved while cmd==0  zero-cmd time  mean rate
A.static__proven__r1a1                 -1.126              -0.561          28.5s     -19.7 mm/s
A.static__proven__r2a1                 -1.341              -0.952          28.4s     -33.5 mm/s
A.static__proven__r3a1                 -1.211              -0.729          27.5s     -26.6 mm/s
A.static__proven__r4a1                 -1.119              -0.382          26.3s     -14.5 mm/s
A.static__proven__r5a1                 -1.460              -0.971          28.5s     -34.1 mm/s
A.static__ships__r1a1                  -0.770              -0.287          20.1s     -14.3 mm/s
A.static__ships__r2a1                  -0.432              -0.207           8.8s     -23.5 mm/s
A.static__ships__r3a1                  -0.791              -0.622          20.5s     -30.4 mm/s
A.static__ships__r4a1                  -0.281              +0.022          19.5s      +1.1 mm/s

pooled 9 static runs: total closure -8.53 m, of which -4.69 m (55%) happened while the
follower commanded vx = 0 exactly
mean uncommanded rate -22.5 mm/s over 208 s of zero-command flight
```

**Verifier correction to the headline number.** Re-run attributing each interval to the
command actually *in force* (reconstructed from the `applied_t` / `cmd_vx` columns, and
requiring the applied command to be zero at **both** ends of the interval), the share falls
from 55% to **40%** at −19.1 mm/s over 177 s; requiring in addition that the size head read
bucket 2 at both ends — so that `vx = 0` is the hold command and not the `abs(x) >= 0.5`
branch of `follow_person.py:367` — it falls to **30%** at −16.0 mm/s over 161 s. The honest
statement is **30–55% depending on how the latency window is attributed**, not 55%. The
direction and the order of magnitude survive every attribution: of 15 contiguous stretches
of ≥3 s in which the applied command was zero throughout, 9 close faster than −10 mm/s
(median −22.7 mm/s), 3 are flat, and 3 recede (up to +26 mm/s).

**A large minority of the distance the drone closed, it closed while asking to hold.** This
resolves the §2 correction: nothing in the perception or the control law carried
`A.static__proven` from 2.428 m to 2.218 m — the drift did.

Mean body pitch during the hold correlates with the closure rate across those 9 runs at
r ≈ −0.6 to −0.7 (this document first reported −0.618; the verifier, averaging pitch over
every tracking frame with `cmd_vx == 0`, got −0.725 — the number moves with the averaging
window, which is itself a reason not to lean on it). It is suggestive of a small attitude
bias driving translation, but n = 9 and the mechanism is not established. **Treat the
mechanism as unknown** (§8).

### 5.3 Therefore the M7 verdict depends on how long the cell was flown

Recomputing `M7_final_in_band` as if each run had ended at T seconds:

```
final distance (m) if the follower had stopped at T seconds:
run                                20s     25s     30s     35s     40s     45s
A.static__proven__r1a1           2.98    2.93    2.89    2.86    2.83    2.58*
A.static__proven__r2a1           2.84    2.70    2.48*   2.32*   2.22*   2.23*
A.static__proven__r3a1           3.00    2.89    2.73    2.58*   2.43*   2.42*
A.static__proven__r4a1           2.77    2.50*   2.50*   2.51*   2.51*   2.52*
A.static__proven__r5a1           2.92    2.78    2.57*   2.42*   2.31*   2.22*
A.static__ships__r1a1            3.29    3.05    2.95    3.02    3.10    2.97
A.static__ships__r2a1            3.19    3.07    3.06    3.11    3.06    3.09
A.static__ships__r3a1            3.29    3.16    3.13    2.95    2.81    2.73
A.static__ships__r4a1            3.15    3.35    3.57    3.63    3.43    3.34

* = inside the M7 widened band [1.457, 2.671] m
the cells were flown with duration_s = 45
```

`A.static__proven` — **the only cell that passes M7** — scores 0/5 in band at 20 s, 3/5 at
30 s, and 5/5 at 45 s. Scoring the **whole M7 verdict** (both gates, cell median) at each
truncation:

```
cell                T=20s  T=25s  T=30s  T=35s  T=40s  T=45s
A.static__proven     FAIL   FAIL   FAIL   FAIL   PASS   PASS      <- flips between 35 and 40 s
A.static__ships      FAIL   FAIL   FAIL   FAIL   FAIL   FAIL
B.moving__proven     FAIL   FAIL   FAIL   FAIL   FAIL   FAIL
```

So the precise claim — corrected by the verifier from an earlier, stronger wording — is
that `A.static__proven`'s PASS **requires the full 45 s**: at 35 s or less the same flights
fail. Duration is necessary but not sufficient: `A.static__ships` fails at every
truncation, so run length is not the *only* thing M7 separates on. Had the suite used 35 s,
which would have been just as defensible a choice, the distance section of the Sep-11
report would have had no passing cell at all.

### 5.4 The "settled window" is not settled

`scoreboard.py:406-411` opens the window at the **first** frame where `size_bucket == 2`,
floored at `t0 + 3 s`. Because a single outlier bucket-2 frame fires early in the approach,
the window opens while the drone is still far out and closing:

```
run                              win opens@  d there  win len  moving%
A.static__proven__r5a1               15.41s    3.271    29.6s     4.8%
A.static__proven__r4a1               15.02s    3.283    29.9s    14.3%
A.static__ships__r2a1                16.44s    3.453    28.5s    72.4%
B.moving__delta_camera__r1a1         17.10s    3.060    32.9s     0.2%
B.moving__ships__r2a1                15.09s    3.110    34.8s    27.0%
```

(The `win len` column was ~7 s too long in the first version of this table: the loader had
not dropped the single `event="after-land"` row, which is logged about 7 s after the last
flight row. `scoreboard.py:339` does drop it — `flown = [r for r in rows if r["event"] ==
""]` — so no *gated* number was affected, and the rest of the table is unchanged.)

Across all 22 runs the window opens at 14.06–17.10 s with the drone 2.93–3.46 m out, and
between 0.2% and 72% of its frames still carry a nonzero forward command. So
`M7_dist_err_settled_mean_m` is an **approach average**, and it mixes the approach
trajectory, the stopping point and the drift into one number. Scored on the last 5 s
instead, 11 of 22 runs clear 0.75 m rather than 8 — the difference is not a uniform
inflation, it changes sign between the static and moving scenes, which is exactly what
you would expect of a number that is measuring three things at once.

### 5.5 What M7 is discriminating on today

A duration-free alternative: the true distance at the first of N consecutive tracking
frames reading bucket 2 — i.e. where the control law *stopped asking to close*. Post-hold
drift and run length cannot move it (verifier's wording; an earlier draft said "drift
cannot move it", which is too strong — the statistic is still read off the same drifting
`stateEstimate`, so drift accumulated *during the approach* is still in it).

```
cell                                      N=1              N=3              N=5             N=10
A.static__proven              3.64 [3.63-3.64]  3.34 [3.24-3.40]  3.09 [2.58-3.26]  3.03 [2.58-3.10]
A.static__ships               3.63 [3.63-3.63]  3.57 [3.28-3.63]  3.16 [3.00-3.26]  3.01 [2.92-3.57]
B.moving__proven              3.20 [3.19-3.22]  3.19 [3.13-3.20]  3.08 [3.00-3.13]  3.02 [3.00-3.03]
B.moving__ships               3.22 [3.22-3.23]  3.12 [3.10-3.14]  3.12 [3.10-3.14]  3.15 [3.14-3.17]
B.moving__delta_camera        3.23 [3.23-3.23]  3.21 [3.21-3.21]  3.20 [3.19-3.21]  3.19 [3.18-3.19]
B.moving__delta_backend       3.20 [3.19-3.20]  3.20 [3.19-3.20]  2.99 [2.97-3.00]  2.96 [2.93-3.00]
B.moving__delta_speed         3.18 [3.16-3.20]  3.18 [3.16-3.20]  3.06 [3.05-3.07]  3.06 [3.05-3.07]

perfect-head prediction (any N): 2.428 m
```

Two caveats the verifier added. The last two rows were missing from the first version of
this table; they do not change the picture. And the statistic is **undefined on one run**:
`A.static__ships__r2a1`'s longest streak of consecutive bucket-2 tracking frames is 3, so
it has no value at N = 5 or N = 10 and the `A.static__ships` medians in those columns are
over 3 runs, not 4. That is a defect in the candidate metric, not in the table — a
distance statistic that cannot be computed for a run that flew for 45 s is not yet ready
to be gated, which is why §7 recommends deriving it from re-scored data rather than
adopting it now.

At N = 10, `A.static__proven` (PASS today) stops at 3.03 m and `A.static__ships`
(FAIL today) stops at 3.01 m. **On the quantity M7 claims to be about, the passing cell and
the failing cell are indistinguishable.** The pass/fail split between them comes from how
much zero-command drift time each accumulated: the float/clean cell spends 26–29 s holding
and drifts 0.38–0.97 m inward, the chip cell spends 9–21 s holding (it is at 6.5 Hz with
more bucket-1 frames) and drifts 0.02–0.62 m.

Every configuration stops around 2.96–3.19 m, about 0.6 m beyond the 2.428 m a perfect head
would give. That gap is the README's mirror artefact, and this statistic corroborates it
independently — the README's §3.4 flip analysis puts the float/clean flip at 3.29 m, and
the N = 3 stop point here is 3.34 m.

---

## 6. Options

Costs are given honestly, including the ones that are cheap. **Re-scoring is much cheaper
than re-flying**: `scoreboard.py` computes M7 from `follow_log.csv` + `truth.csv`, both of
which still exist on disk for all 37 runs, so any metric-definition change can be applied
to the Sep-11 data without putting the drone back in the air. See the warning in §7.1.

### Option 1 — Leave M7 exactly as it is

*Cost:* zero. *Invalidates:* nothing.
*Against:* the distance cells stay red for a reason that is roughly half simulator drift,
and the one green cell is green by duration luck. A real distance regression would be
invisible under either. This is the "permanent red" failure mode the brief describes — it
is just not caused by what the brief assumed.

### Option 2 — Re-target the gate from 1.942 m to the reachable 2.428 m

The README §8 item 3 suggests this. Recomputed from the published window means, threshold
left at 0.75 m:

```
cell                       win mean(med) err vs 1.942   now | err vs 2.428 would be
A.static__ships                    3.095        1.153  FAIL |        0.667     PASS
B.moving__ships                    3.167        1.226  FAIL |        0.740     PASS
A.static__proven                   2.611        0.669  PASS |        0.183     PASS
B.moving__proven                   2.687        0.745  PASS |        0.259     PASS
B.moving__delta_backend            2.772        0.831  FAIL |        0.345     PASS
B.moving__delta_camera             3.050        1.108  FAIL |        0.622     PASS
B.moving__delta_speed              2.740        0.798  FAIL |        0.312     PASS
```

The table above is computed as `window mean − 2.428`, whereas the gate is
`mean(|d − 2.428|)`; the two differ only for runs that go inside 2.428 m. Recomputing the
gate exactly from the logs changes one cell materially — `A.static__proven` 0.183 → 0.265 —
and leaves the conclusion intact: **all seven cells still pass.**

*Cost:* a constant in `scoreboard.py` plus a re-score. *Invalidates:* every published M7
number.
**Against, strongly:** it turns all seven distance cells green while nothing about the
drone changed, including the two cells that park at 3.1–3.2 m because of a rendering
artefact this very directory root-caused. Moving the target without re-deriving the
threshold converts a too-strict gate into a vacuous one. If this option is taken, the
threshold must be re-derived at the same time — and it cannot be, honestly, until §5 is
resolved.

### Option 3 — Widen the band or raise the threshold

*Cost:* one constant plus a re-score. *Against:* same objection as Option 2 with less
justification. The 0.75 m threshold already carries a written derivation; replacing it
with a number chosen to make the current runs pass would destroy the one thing M7 has
going for it.

### Option 4 — A finer size head (more buckets)

*Cost:* the largest on the list — retrain, re-quantise, re-export to GAP8, re-validate on
chip, re-fly the suite. It also touches the network, and the champion-vs-confuser choice
is a pending team decision that this must not front-run.

It is also **not a drop-in**, which I do not think has been noticed. `vx` is exactly zero
only when some bucket centre equals the target 0.625:

```
  n centre == 0.625?   hold bucket s-range stop-on-entry    |vx| at the two buckets
                                                            straddling the target
  4              YES       [0.5000,0.7500)        2.428m    dead zone, vx=0 across it
  6               no -- no zero-vx bucket --          --    +0.033 / -0.100 m/s
  8               no -- no zero-vx bucket --          --    +0.050 / -0.050 m/s
 10               no -- no zero-vx bucket --          --    +0.060 / -0.020 m/s
 12              YES       [0.5833,0.6667)        2.081m    dead zone, vx=0 across it
 16               no -- no zero-vx bucket --          --    +0.025 / -0.025 m/s
 20              YES       [0.6000,0.6500)        2.023m    dead zone, vx=0 across it
```

The obvious choice — doubling to 8 buckets — removes the dead zone entirely: no bucket
centre equals 0.625, so the law would never command zero and would hunt around 1.942 m with
a ±0.050 m/s limit cycle. 12 or 20 buckets keep a dead zone but only move the stop-on-entry
point to 2.081 m or 2.023 m, not to 1.942 m; a stop-on-entry law always parks at the far
edge of its hold bucket, so it can never reach the centre. And none of this touches the
drift or the window, which is where the measurement problem actually is.

### Option 5 — Change the control law

Soft size decode (the `x_soft` treatment applied to size), or requiring N consecutive
bucket-2 frames before zeroing `vx`. This is README §8 item 2 and it belongs to
`follow_person.py`'s owner. *Cost:* a re-fly, and a behaviour change six days before the
first hardware session. It would move the stop point toward 1.942 m and make the target
honest. It does **not** address §5: a soft-decoded law that stops at 1.94 m would then
drift *inside* 1.619 m over a long hold and start backing up.

### Option 6 — Declare M7 `characterised`, not gated

`scoreboard.py:616-624` already supports this: `gate(..., kind="characterised", ...)`
yields `result = "REPORT_ONLY"`, and `:801` rolls a cell with any such gate up to
`CHARACTERISED` rather than PASS or FAIL. It is what `M8_char` already does for the
class-F false-follow rate, on the stated grounds that "a pass mark here would be invented".
*Cost:* a `kind` string plus a re-score; no re-fly, no model change, no control change.
*Invalidates:* the M7 PASS/FAIL verdicts, including `A.static__proven`'s PASS.
*Against:* distance keeping is the headline behaviour of the project, and this removes all
automated regression protection over it.

### Option 7 — Characterise now, gate a drift-free quantity later

Option 6 for this release, plus two repairs that are independent of the drift question:
redefine the settled window so it opens on a *sustained* hold rather than the first
bucket-2 frame (§5.4), and drop or rename `M7_size_overread_ratio` (README §5 showed it is
algebraically `d / 1.942`). Then, once someone explains the drift, decide whether to gate
the hold-entry distance of §5.5 — which cannot be moved by drift or by run length — with a
threshold derived from re-scored data rather than guessed.

---

## 7. Recommendation

**Take Option 7.** Concretely, and in this order:

1. **Preserve the raw logs first** (§7.1). Everything below depends on them.
2. **Demote both M7 gates to `kind="characterised"`** for the Sep-11 suite and until the
   drift is explained. Keep computing and publishing the numbers; stop deriving PASS/FAIL
   from them.
3. **Fix the settled-window definition** so it opens on a sustained hold, and re-score.
   This repair stands on its own: the current window is an approach average by anyone's
   definition, independent of what one concludes about the drift.
4. **Drop or rename `M7_size_overread_ratio`**, per README §5.
5. **Do not** re-target 1.942 → 2.428 m, **do not** move the 0.75 m threshold, **do not**
   change the control law or the bucket count *for this reason*. Options 2–5 all answer a
   question that is not the binding one.

**Reasoning.** You cannot set an honest threshold on a quantity that is 30–55% uncommanded
drift and whose verdict moves with `duration_s`. Any threshold chosen today would be
calibrated against a drift whose magnitude nobody has explained and whose transfer to
hardware is unknown. `characterised` is the project's existing, precedented way of saying
"we measure this, we do not yet know what number is right" — the class-F metrics use it for
exactly that reason. Choosing it here is consistent rather than novel.

The narrower reason to reject the alternatives: Option 2 and Option 3 would turn all seven
distance cells green without anything about the drone changing, which is worse than a
permanent red because it is a permanent *green*. Options 4 and 5 are real engineering with
real value — the stop point genuinely is ~0.6 m beyond where a perfect head would put it,
and the README's mirror finding explains most of that — but both cost a re-fly, Option 4
costs a retrain and touches a pending team decision, and neither improves the *measurement*.
Fix the ruler before re-cutting the wood.

**What this costs:** one `kind` string, one window definition, one metric deleted, and a
re-score of logs already on disk. No re-fly. No model change. No change to
`follow_person.py` before the lab session.

**What this invalidates:**

- The `PASS` verdict on `A.static__proven` and the `FAIL` verdicts on the other six
  distance cells, in `scoreboard.json`, `scoreboard.md` and the Sep-11 README.
- The suite's overall pass/fail counts, which will move cells into the `CHARACTERISED`
  bucket.
- The sentence "settles at about 3.0-3.3 m where it should hold 1.94 m" and its copies.
  Line numbers are deliberately omitted: these files are being edited in parallel and the
  numbers in the first version of this document were already stale when it was written.
  Grep for `1\.94` instead. As of the verifier's pass the string occurs in
  `EXPERIMENTS.md` (7 times), `DECISIONS.md` (2), `docs/progress/sai_maruvada.md` (5),
  `docs/hardware/lab_session_runbook.md` (2), `tools/crazysim_macos/README.md` (1, the M7
  row of the metric table), `docs/sim_results/2026-09-11-simv2/README.md` (16) and in this
  directory's own `README.md`. Not every one of those is wrong — the arithmetic ones are
  fine — but every one that presents 1.94 m as the distance the drone *should* have reached
  needs the qualification below. Correcting them belongs to the record workstream, not to
  this document. The change is needed not because the 3.0–3.3 m is wrong, but
  because "should hold 1.94 m" was never something this controller was going to do, and
  because part of the 3.0–3.3 m is a drift that may not exist on hardware.

**What this does not settle:** whether the drone should hold 1.94 m at all. That is a
design question — Option 5, plus possibly Option 4 — and it should be decided on its own
merits by whoever owns `follow_person.py`, after the lab session, not as a side effect of
fixing a metric.

### 7.1 Do this first, regardless of which option is chosen

`docs/sim_results/2026-09-11-simv2/runs/*/` contains only `cell.json`, `metrics.json` and
`summary.json`. **The `follow_log.csv` and `truth.csv` that every option in §6 would need
exist only under `/private/tmp/.../scratchpad/simv2/rev/merged_suite/runs/`** — 37 run
directories, 5.8 MB of CSV inside 33 MB total. That path is a scratch directory. If it is
cleared, every "re-score instead of re-fly" option in this document becomes a re-fly, and
this analysis becomes unreproducible. Copying those two files per run somewhere durable
costs 5.8 MB and should happen before anything else.

---

## 8. What I did not verify

- **Nothing was flown and no hardware was involved.** Every flight number is a re-analysis
  of the already-published Sep-11 logs.
- **I did not run the simulator.** The lock at
  `scratchpad/sim.lock` was held by the re-fly workstream for the whole of this work.
- **I cannot separate physical drift from estimator drift.** `scoreboard.py:386` computes
  `d_true = hypot(tx - px, ty - py)` where `tx, ty` are the subject's MuJoCo ground truth
  from `truth.csv` but `px, py` are `stateEstimate.x/y` — the drone's own estimate.
  `patch_crazysim.py:88-102` logs only bodies matching `CRAZYSIM_TRUTH_PREFIX` (`subj_`),
  so **the drone's true pose is never written to the truth log.** The §5 drift is therefore
  proven for the quantity M7 is scored on, which is what matters for the gate, but I cannot
  say whether the drone physically flew forward or its estimator walked forward. Adding the
  drone body to the truth prefix would settle it in one line — that file is not mine.
  **Verifier's partial evidence, offered as suggestive and not as proof:** the run
  directories keep the follower's own camera frames (`snap_NNNN.png`, one every 30 control
  steps). On `A.static__proven__r5a1`, `snap_0331` (t = 34.6 s, d_est 2.427 m) and
  `snap_0481` (t = 44.6 s, d_est 2.224 m) bracket ten seconds in which `cmd_vx` was 0.00 on
  every frame. If the drone physically approached, the rendered scene must magnify by
  2.427 / 2.224 = 1.091. A coarse grid search for the best (scale, dx, dy) alignment between
  the two frames returns **scale 1.06** (and 1.03 against `snap_0421`, predicted 1.056),
  i.e. the camera really did move closer, by roughly — a little less than — the amount the
  estimator reported. This leans toward *physical* motion rather than estimator walk. It is
  a nearest-neighbour image registration on a yawing camera with a 0.01 grid step and no
  error bars; it is not a substitute for logging the drone's true pose.
- **The mechanism of the drift is unknown.** The pitch correlation (r = −0.618, n = 9) is
  suggestive and nothing more. I did not inspect the CrazySim velocity controller or the
  `MotionCommander` setpoint path.
- **Whether the drift transfers to hardware is unknown.** A real Crazyflie holding a zero
  *velocity* setpoint with no external positioning will drift, plausibly more than 22 mm/s.
  If it does, §5 describes real behaviour rather than a simulator artefact — and the
  conclusion for the gate is the same either way, because a metric dominated by open-loop
  drift is not measuring distance keeping.
- **The N-consecutive-frames stop point in §5.5 is a candidate, not a validated metric.**
  I computed it on 22 runs to show that a drift-free statistic exists and that it collapses
  the proven/ships distinction. I have not checked its variance, its behaviour on the
  occlusion or distractor scenes, or what threshold it would deserve.
- **This document was written in parallel with the re-fly workstream and does not use its
  results.** That workstream's `docs/eval_results/2026-09-12-mirror-refly/README.md` §4
  independently reaches the same correction to the "2.428 m is the floor" claim, from the
  command histograms rather than from the arithmetic, and reports a mirror-free flight
  parking at 1.79 m — inside 2.428 m, and closer to 1.942 m than anything in §5.5. I have
  read that section and confirmed it does not contradict anything here, but I have not
  verified its flights, and §6 does not take them into account. Whoever takes the decision
  in §7 should read both.
- **I did not re-verify the README's mirror finding.** §5.5 happens to corroborate it
  (3.34 m stop point vs its 3.29 m flip distance) but that was not the aim and it is not an
  independent replication.
- **I changed no code and re-ran no published result.** Every `scoreboard.py` behaviour
  quoted here is read from the source or reproduced from `scoreboard.json`.

---

## 9. Reproducing

Everything above comes from the published Sep-11 logs and needs no simulator. The scripts
were written in the session scratchpad, which is ephemeral, so the two load-bearing ones
are inlined here. Both take no arguments and run in a few seconds under
`/Users/saimaruvada/Downloads/drone/trainenv/bin/python`. Neither writes anything.

`SUITE` below must point at run directories containing `follow_log.csv` and `truth.csv` —
today only the scratchpad copy qualifies (§7.1).

### 9.1 The drift measurement (§5.2)

```python
"""55% of the closure happened while the follower commanded vx = 0 exactly."""
import csv
from pathlib import Path
import numpy as np

SUITE = Path("/private/tmp/claude-501/-Users-saimaruvada-Downloads/"
             "90541ca8-cca5-4400-9855-79d1dde551f0/scratchpad/simv2/rev/merged_suite/runs")

def f(r, k):
    try:    return float(r.get(k, ""))
    except Exception: return float("nan")

T = []
for run in sorted(SUITE.glob("A.static__*")):
    rows = list(csv.DictReader(open(run / "follow_log.csv")))
    tr = [l.strip().split(",") for l in open(run / "truth.csv") if not l.startswith("#")]
    P = np.array([[float(v) for v in r[:4]] for r in tr if len(r) >= 4])
    assert P[:, 2].ptp() < 1e-6 and P[:, 3].ptp() < 1e-6, "subject is not static"
    t  = np.array([f(r, "t")  for r in rows])
    px = np.array([f(r, "px") for r in rows]); py = np.array([f(r, "py") for r in rows])
    d  = np.hypot(P[0, 2] - px, P[0, 3] - py)
    vx = np.array([f(r, "cmd_vx") for r in rows])
    trk = np.array([f(r, "tracking") for r in rows]).astype(bool)
    ok = np.isfinite(d) & np.isfinite(t) & trk
    # intervals during which the command in force was exactly zero
    pair = ok[:-1] & ok[1:] & (vx[:-1] == 0.0) & (np.diff(t) < 1.0)
    moved = float(np.sum(np.diff(d)[pair])); span = float(np.sum(np.diff(t)[pair]))
    i = np.where(ok)[0]
    print(f"{run.name:30s} total {d[i[-1]] - d[i[0]]:+.3f} m   "
          f"while cmd==0 {moved:+.3f} m over {span:.1f}s = {1000 * moved / span:+.1f} mm/s")
    T.append((d[i[-1]] - d[i[0]], moved, span))
T = np.array(T)
print(f"pooled: {100 * T[:, 1].sum() / T[:, 0].sum():.0f}% of the closure was uncommanded, "
      f"at {1000 * T[:, 1].sum() / T[:, 2].sum():+.1f} mm/s")
```

### 9.2 The duration dependence (§5.3)

```python
"""A.static__proven scores 0/5 in band at 20 s and 5/5 at 45 s."""
import csv
from pathlib import Path
import numpy as np

SUITE = Path("/private/tmp/claude-501/-Users-saimaruvada-Downloads/"
             "90541ca8-cca5-4400-9855-79d1dde551f0/scratchpad/simv2/rev/merged_suite/runs")
WIDE = (1.619 * 0.9, 2.428 * 1.1)          # scoreboard.py M7_band_wide_m

def f(r, k):
    try:    return float(r.get(k, ""))
    except Exception: return float("nan")

for run in sorted(SUITE.glob("A.static__*")):
    rows = list(csv.DictReader(open(run / "follow_log.csv")))
    tr = [l.strip().split(",") for l in open(run / "truth.csv") if not l.startswith("#")]
    P = np.array([[float(v) for v in r[:4]] for r in tr if len(r) >= 4])
    t  = np.array([f(r, "t")  for r in rows])
    px = np.array([f(r, "px") for r in rows]); py = np.array([f(r, "py") for r in rows])
    d  = np.hypot(P[0, 2] - px, P[0, 3] - py)
    ok = np.isfinite(d) & np.isfinite(t); t, d = t[ok], d[ok]
    out = []
    for T in (20, 25, 30, 35, 40, 45):
        m = t <= T
        v = d[m][-1] if m.sum() else float("nan")
        out.append(f"{v:5.2f}{'*' if WIDE[0] <= v <= WIDE[1] else ' '}")
    print(f"{run.name:30s} " + " ".join(out))
print("* = would pass M7_final_in_band.  cells were flown with duration_s = 45")
```

### 9.3 Everything else

| result | where it comes from |
|---|---|
| §1 arithmetic | `scoreboard.py:52-64` and `follow_person.py:220/229/230/367`, evaluated directly |
| §2 "0 of 683 frames" | same log loader as 9.1, counting `tracking & d < 2.428 & size_bucket <= 1` |
| §3 gate records | `docs/sim_results/2026-09-11-simv2/scoreboard.json`, `cells[].gates[]` |
| §3.1 the two gates coincide | `scoreboard.json`, comparing `M7_dist_err_settled_mean_m` with `M7_size_window_dist_mean_m - 1.942` per run |
| §4 origin of 1.94 m | `scratchpad/simv2/spec_metrics.md` §3; `scoreboard.py:82` `GATE_BASIS["M7_mean"]` |
| §5.4 window contents | replicate `scoreboard.py:406-411` on the logs: `start = max(t[first bucket-2 frame], t[0] + 3.0)` |
| §5.5 stop point | first of N consecutive tracking frames with `size_bucket == 2`, N in {1,3,5,10} |
| §6 Option 2 table | `scoreboard.json` window means, re-scored against 2.428 m |
| §6 Option 4 table | `(k + 0.5)/n == 0.625` for n buckets, and `d = 1.7/(2 s tan35)` |
