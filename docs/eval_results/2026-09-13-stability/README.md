# Does the matte floor cost flight stability? No — the upsets were an artefact

**Answer: the attitude-upset effect is NOT REAL.** Removing the mirrored floor does
not destabilise the drone. The Sep 12 finding of "9 of 21 matte flights lost
attitude control against 0 of 20 mirrored" does not reproduce under a design that
controls for the three things that contaminated it.

**Nothing here was measured on hardware. Every frame is rendered. Nothing in this
report says anything about a real Crazyflie.**

Flights ran 2026-09-12, 15:07–16:21 CDT, on an otherwise idle-of-agents laptop.
(The directory is named `2026-09-13-stability` per the workstream instruction;
the timestamps in `data/` are the authoritative record of when it ran.)

Companions:
`docs/eval_results/2026-09-12-distance/README.md` (root cause) and
`docs/eval_results/2026-09-12-mirror-refly/README.md` (first attempt — its
distance result stands, its upset result is superseded by this one). Neither was
modified, nor was `docs/sim_results/2026-09-11-simv2/`.

---

## 0. TL;DR

| claim under test | verdict |
|---|---|
| Matte floor causes attitude upsets | **NOT REAL.** 0/28 matte vs 1/28 mirrored. Fisher p = 1.00 |
| The Sep 12 rate (9/21 = 43% on matte) is the true matte rate | **ruled out.** P(0 upsets in 28 \| rate 43%) = 1.6 × 10⁻⁷ |
| The one upset here belongs to the matte arm | **no** — it is a **mirrored** flight |
| Distance improves when the mirror is removed | **reproduced, all 7 cells** (§4) |
| Tracking (M1) degrades on matte | **not reproduced** — the Sep 12 M1 collapse was the upsets, not the floor |
| "Command chattering causes the upsets" (Sep 12 hypothesis) | **not sufficient** — matte flights chatter at up to 5.6 changes/s with zero upsets (§6) |
| A third explanation exists | **yes** — transient scheduler stalls, which `sim_wall_ratio` cannot see (§5) |

The honest one-line version for Prof. Mok: *removing the mirror fixed the
distance error and cost nothing in stability; the stability scare was our laptop,
not our drone.*

---

## 1. What was wrong with the first attempt, and what this run does differently

| contamination | fix here |
|---|---|
| The two arms ran **different code** — `camera_model.py` was edited at 13:37, between the matte suite (ended 13:36) and the mirrored control (started 13:41) | sha256 of `camera_model.py`, `follow_person.py`, `build_scene.py`, `scoreboard.py`, `patch_crazysim.py` recorded **before** flight 1 and re-checked **after** flight 56. **All five byte-identical.** `data/code_hashes_{before,after}.txt` |
| Upsets clustered on **repeat 3**, i.e. on flight order, not on cells | 4 repeats per cell per arm, with the 28 (cell, repeat) pairs **shuffled** so repeat index and chronological position are decorrelated. Realised correlation **exactly 0.000** (§3) |
| All matte flights ran, then all mirrored — so machine drift landed entirely on one arm | **interleaved in matched pairs**: the same cell at the same repeat is flown matte and mirrored back to back, ~60 s apart, with the leading arm **ABBA-counterbalanced** so neither arm is systematically the colder first flight. Both arms have mean chronological position **28.5 of 56** |
| 14 agents on the laptop, 15-min load average 32.9 | this agent was the only one flying; load and `sim_wall_ratio` recorded **before and after every flight**; flights below 0.95 reported separately, never silently averaged |

### The order confound was worse than it looked

`follow_person.py` contains **no RNG at all**. The repeat index reaches the
simulator through exactly one channel — `CRAZYSIM_SENSOR_SEED = 1000 + repeat` —
and that is exported **only when `camera != clean`**.

Four of the seven cells (`A.static__proven`, `B.moving__proven`,
`B.moving__delta_speed`, `B.moving__delta_backend`) are clean-camera cells. For
those, repeat 1, 2 and 3 are **configuration-identical**. So in the Sep 12 suite,
"repeat 3" on those cells could not have meant anything except *the third flight
in time*. The clustering the first attempt spotted was, for the majority of its
cells, a pure order effect by construction. That is why breaking it mattered.

---

## 2. Method

Seven cells — the five that failed M7 on Sep 11 plus the two "proven" cells that
share their scenes — copied verbatim from `run_acceptance2.sh`'s CORE matrix:

```
A.static__ships          s15_static_offset  chip  / himax_typical / 6.5 Hz  45 s
B.moving__ships          s01_control_moving chip  / himax_typical / 6.5 Hz  50 s
B.moving__delta_backend  s01_control_moving chip  / clean         / full    50 s
B.moving__delta_camera   s01_control_moving float / himax_typical / full    50 s
B.moving__delta_speed    s01_control_moving float / clean         / 6.5 Hz  50 s
A.static__proven         s15_static_offset  float / clean         / full    45 s
B.moving__proven         s01_control_moving float / clean         / full    50 s
```

7 cells × 2 floors × 4 repeats = **56 flights**, 74 min wall clock.

### The two floors are one attribute apart, verified

Two scene trees were built **outside the repo**, by the same builder, differing
only in the flag:

```
build_scene.py --def scene_defs/{s15_static_offset,s01_control_moving}.json --out <scratch>/scenes_matte
build_scene.py --def ...                                --out <scratch>/scenes_mirror --floor-reflectance 0.2
```

* `diff` of the two `scene.xml` files is **exactly one line** — the groundplane
  `reflectance="0"` vs `reflectance="0.2"`. Nothing else.
* Every `subj_*.png` is **byte-identical** between the trees.
* The matte tree's `scene.xml` is **byte-identical to the repo's live
  `scenes_v2/`**, i.e. to the files the Sep 12 matte suite actually flew.
* `manifest.json` differs (build timestamp and argv). `crazysim.py` never reads
  it — grep confirms the only scene input it takes besides `scene.xml` is
  `CRAZYSIM_SCENE_MOTION`, which is unset for both trees because neither scene
  has a `motion.json`. The moving subject moves via a spring `<joint
  name="sway_subj_person" type="slide">` baked into `scene.xml`, identical in both.

Because the trees are separate directories, **no scene file was ever swapped
under a running suite** — the condition is chosen by which path the flight is
pointed at.

### Nothing under measurement was modified

`run_acceptance2.sh` hardcodes `SCENES="$HERE/scenes_v2"` and walks cells × repeats
in a fixed nested order, so it can neither interleave conditions nor decorrelate
repeat from order. Rather than edit it — it is one of the things being measured —
`scripts/fly_plan.sh` reproduces its `fly()` body verbatim with the scene root as
a parameter, load sampling added, and the order taken from a plan file. The
follower, scorer, checkpoint, ONNX and camera model are the repo's own, unedited.
`scoreboard.py` was run, never touched.

---

## 3. Result: the upsets do not reproduce

Upset definition, identical to the Sep 12 report and stated explicitly: over
flown rows (`event == ""`; the single `after-land` row is excluded because it
records post-landing z and reads ~0.02 on every flight, healthy or not),

```
upset_frames = rows with |pitch| > 30 deg or |roll| > 30 deg
z_min        = min pz
UPSET        = upset_frames > 0  or  z_min < 0.5
```

A healthy flight in this harness holds pz 0.80–0.85 with |pitch| under ~7 deg.

### By condition

```
matte    0/28 =  0%
mirror   1/28 =  4%
contingency [[0,28],[1,27]]   Fisher exact two-sided p = 1.0000
```

Restricted to flights that kept real time (`sim_wall_ratio >= 0.95`):
**matte 0/16, mirror 0/15.**

95% Clopper–Pearson interval for the matte upset rate: **[0.000, 0.123]**.

### Against the Sep 12 claim

```
Sep 13 matte 0/28  vs  Sep 12 matte 9/21     Fisher exact p = 1.4e-04
P(0 upsets in 28 | true rate 9/21 = 42.9%)                 = 1.6e-07
```

The Sep 12 matte rate is excluded. Meanwhile this run's mirrored arm (1/28) is
statistically indistinguishable from the Sep 12 mirrored control (0/20, p = 1.00)
— so the *control* arm reproduced fine. Only the matte arm's upsets vanished,
which is what "artefact" looks like.

### By flight order — the confound the first attempt could not rule out

```
flights  1-15 (quartile 1)   0/15 =  0%
flights 16-29 (quartile 2)   1/14 =  7%
flights 30-43 (quartile 3)   0/14 =  0%
flights 44-56 (quartile 4)   0/13 =  0%
```

### By repeat index — linearly decorrelated from order by design (corr = 0.000)

```
repeat 1   1/14 = 7%     mean chronological position 24.4
repeat 2   0/14 = 0%     mean chronological position 37.5
repeat 3   0/14 = 0%     mean chronological position 22.9
repeat 4   0/14 = 0%     mean chronological position 29.2
```

**Repeat 3 — which tumbled in 6 of 7 cells on Sep 12 — tumbled in 0 of 14 here.**
Once repeat 3 no longer means "flown third", it stops being special. That is the
single cleanest piece of evidence that the Sep 12 pattern was an order effect.

### By cell

```
cell                     matte      mirror
A.static__proven         0/4        1/4     <-- the only upset in the experiment
A.static__ships          0/4        0/4
B.moving__delta_backend  0/4        0/4
B.moving__delta_camera   0/4        0/4
B.moving__delta_speed    0/4        0/4
B.moving__proven         0/4        0/4
B.moving__ships          0/4        0/4
```

### Matched pairs

28 complete pairs (same cell, same repeat, flown back to back):

```
matte upset only    0
mirror upset only   1
both                0
neither            27
McNemar exact (1 discordant)  p = 1.0000
```

### The continuous measure agrees, and is stronger than the threshold

A binary 30° gate throws away most of the signal. The per-flight maximum |pitch|:

```
matte    n=28   min 3.8   median 4.7   p90 6.4   max  7.2 deg
mirror   n=28   min 3.6   median 4.8   p90 7.0   max 31.6 deg
Mann-Whitney U two-sided p = 0.712
```

**Across 28 matte flights the worst attitude excursion was 7.2° — a 4× margin to
the 30° envelope.** The distributions are indistinguishable. Minimum z: matte
0.796–0.801 on every one of 28 flights; mirrored 0.744–0.801. No flight in either
arm went near the floor, against eight sub-zero flights on Sep 12 (deepest −2.23 m).

---

## 4. The distance improvement reproduced — in all seven cells

This is the result that was believed, and it survives the better design.

Median held distance (`M7_dist_final_m`), mirrored → matte, interleaved:

| cell | Sep 12 mir → matte | Sep 13 mir → matte | reproduced |
|---|---|---|---|
| `A.static__proven` | 2.269 → 1.790 | 2.423 → **1.971** | yes |
| `A.static__ships` | 2.982 → 2.119 | 2.917 → **2.205** | yes |
| `B.moving__delta_backend` | 2.832 → 2.182 | 2.825 → **2.159** | yes |
| `B.moving__delta_camera` | 2.936 → 2.945 (starved) | 2.958 → **2.319** | **yes — newly clean** |
| `B.moving__delta_speed` | 2.626 → 1.968 | 2.524 → **2.103** | yes |
| `B.moving__proven` | 2.616 → 1.891 | 2.652 → **2.151** | yes |
| `B.moving__ships` | 3.314 → 2.437 | 3.184 → **2.428** | yes |

M7 settled error falls from 0.647–1.159 m (mirrored) to 0.110–0.526 m (matte) —
a 2.2–5.9× improvement, matching Sep 12's 2.3–4.6×.

**`B.moving__delta_camera` improves here.** On Sep 12 it was the one cell that
did not. Here all eight of its flights ran at 12.8–14.8 Hz and it improves like
the rest (2.958 → 2.319 m, error 0.996 → 0.443 m) and passes.

> **Do not read that as "the Sep 12 failure was frame starvation, not himax."**
> An earlier draft said exactly that and the cell's own per-flight data refutes
> it: of its three Sep 12 matte flights, r1a1 ran at 2.60 Hz (final 2.945 m),
> r2a1 at 9.40 Hz (2.504 m), and r3a1 at a perfectly normal **13.49 Hz with the
> *worst* final distance of the three, 3.093 m**. All three were attitude upsets.
> The honest statement is narrower: the Sep 12 flights for this cell are
> uninterpretable, and the himax question is **still open**.

### Tracking did not degrade either

Median `M1_tracking_fraction`:

| cell | Sep 13 mirror | Sep 13 matte | Sep 12 matte |
|---|---|---|---|
| `B.moving__delta_camera` | 0.996 | **0.996** | 0.552 |
| `B.moving__delta_backend` | 0.996 | **0.923** | 0.844 |
| `B.moving__proven` | 0.996 | **0.988** | 0.937 |
| `B.moving__ships` | 0.992 | **0.986** | 0.967 |

Sep 12 §6 reported that "tracking got worse" on matte and treated it as a cost of
the fix. It was a consequence of the upsets — when the drone tumbles, the camera
stops pointing at the room. With the upsets gone, M1 recovers to 0.92–0.996. A
small residual gap remains on `delta_backend` (0.923 vs 0.996) and is real but
minor.

Suite verdicts over these seven cells: **matte 4 PASS / 3 FAIL, mirrored 3 PASS /
4 FAIL.** Every mirrored failure is `M7_dist_err_settled_mean_m` +
`M7_final_in_band` — distance. Every matte failure is
`M10_uncertain_fraction_present` (plus `M1` on `delta_backend`) — not distance,
not attitude.

---

## 5. A third explanation: transient stalls, which `sim_wall_ratio` cannot see

Nobody has raised this, and it is the most useful thing in this report.

The Sep 12 caveat blamed low `sim_wall_ratio`. It is a **poorly matched**
instrument: it is a flight *average*, while an upset is caused by a moment. A
better-matched one is already in every `summary.json`: `step_gap_ms.max`. It is
better, not clean — the two groups overlap (see the caveat after the table).

```
suite            n   upsets   max_step_gap_ms            sim_wall_ratio
                                median     max            median   min
Sep 12 matte    22      10       168.8    875.7            0.981   0.882
Sep 12 mirror   22       1       146.2    299.9            0.989   0.009
Sep 13 (mine)   56       1       106.2    183.9            0.989   0.876
```

(The Sep 12 rows count all 22 run directories, including failed and INVALID
attempts, which is why the mirrored control shows one flagged flight where its own
report says zero: the flagged run is `B.moving__ships__r3a2`, `sim_wall_ratio`
0.009 and `z_max` 0.65 — a flight that never really flew and was scored INVALID.
The Sep 12 report's "0 upsets in 20 scored-valid" is correct; my scan is just less
selective. The `sim_wall_ratio` min of 0.009 in that row is the same run.)

Within the Sep 12 matte suite the split is clean:

```
             n   max_step_gap_ms median   range        sim_wall_ratio median
UPSET       10        232.9              165 - 876          0.925
no upset    12        160.0              131 - 214          0.990
```

And checking the timing inside each Sep 12 upset flight: in every one of the ten,
**the largest gap occurring earlier in that flight was at least 158 ms** (the ten
values: 158, 162, 165, 187, 196, 198, 221, 457, 531, 605 ms). In four of them the
flight's single largest gap came *before* the first upset frame, so the stall is
not merely a consequence of tumbling.

> **Two honest limits on that 158 ms figure, added after review.** It is *not*
> the gap immediately before the upset — those run 21–456 ms, as low as 21.4 ms.
> And it is **not discriminating**: 11 of the 12 non-upset Sep 12 matte flights
> also contain a gap ≥158 ms, so the threshold is true of 21 of 22 flights in
> that suite (sensitivity 100%, specificity 8%). The upset and non-upset
> distributions overlap in the 165–214 ms band, which holds 3 flights of each;
> the best possible single threshold still misclassifies 3 of 22 (AUC 0.94).
> Treat 158 ms as a lead, not a detector.

**My run never entered that regime.** Across all 56 flights the largest step gap
anywhere was 183.9 ms — below the *median* of the Sep 12 upset flights.

The decisive detail: **25 of my 56 flights ran at `sim_wall_ratio` 0.876–0.926 —
the same band the Sep 12 caveat flagged as suspect — and 24 of those 25 had no
upset at all.** So low average throughput is not what does the damage. A laptop
running 14 agents produces *bursty* contention: occasional half-second stalls that
barely move the average. A laptop running Chrome and a chat app produces steady
mild load that lowers the average without ever stalling. The first attempt had the
first kind; this one had the second.

That also explains why the Sep 12 mirrored control looked clean: it was not just a
different floor, it was flown in a quieter five minutes (max gap 299.9 ms vs the
matte suite's 875.7 ms, 10/22 flights over 150 ms vs 21/22). The "same machine,
same afternoon" control was not the same machine-state.

**This is an association, not a demonstrated mechanism.** A ≥158 ms gap is
necessary-looking but clearly not sufficient — Sep 12 non-upset flights reached
214 ms. What it establishes is that the two suites differed in stall exposure at
least as much as they differed in floor, which is enough to disqualify the floor
as the explanation.

---

## 6. The Sep 12 chattering hypothesis, tested directly

Sep 12 §7 proposed that the matte floor is dangerous because it lets the drone
reach the bucket-2 band, where the quantised size head makes `vx` chatter between
+0.2, 0 and −0.2 m/s. Counting `cmd_vx` changes per second over whole flights:

```
matte    median 1.95/s   max 5.62/s     0 upsets
mirror   median 1.74/s   max 5.17/s     1 upset (at only 2.60/s)
```

**Both arms chatter, at the same rate**, and the matte arm's worst chatterer
(5.62 changes/s) flew fine while the one upset happened at 2.60/s. Chattering is
real and it is not sufficient to cause an upset.

### But the mirrored floor is not the safe side of the chatter, either

The one upset in this experiment is worth reading closely
(`data/mirror_suite/runs/A.static__proven__r1a1`, t ≈ 22.1–22.9 s):

```
   t     pitch   pz   conf  cmd_vx  bucket
 22.12    -2.4  0.81  0.95   -0.20     3
 22.26   -29.3  0.80  0.60   -0.20     3
 22.38    +7.0  0.78  0.95   +0.20     1
 22.45   +31.6  0.76  0.99   +0.20     1
 22.51   +16.2  0.75  1.00    0.00     2
 22.58    -3.2  0.74  0.95   -0.20     3
 22.72   +16.1  0.75  1.00   +0.20     1
```

Confidence stays 0.60–1.00 throughout and tracking is never lost — this is a
control oscillation, not a perception failure. It crosses 30° by 1.6° and
self-recovers within a second; z never leaves 0.74–0.81. Under a 35° threshold it
would not be counted at all.

Note *which* cell it is. `A.static__proven` on the **mirrored** floor holds a
median **2.423 m** — and the perfect-head bucket 1/2 boundary is **2.428 m**. That
mirrored cell parks the drone almost exactly on a decision boundary, which is the
worst possible place for a quantised head with no temporal filter. The matte floor
parks the same cell at 1.971 m, comfortably inside bucket 2.

So the Sep 12 framing is backwards in an interesting way: the mirror does not
protect the drone from the chatter zone, it can park it *on the edge* of one. The
underlying weakness — a quantised size signal with no temporal filter — belongs to
the control law and is present on both floors. It is worth fixing on its own
merits; it is not an argument against the matte floor.

---

## 7. The machine, honestly

Load average and `sim_wall_ratio` were sampled around all 56 flights.

```
matte    sim/wall min 0.876  median 0.990  max 0.999 | load1 before: median 9.18  max 17.57
mirror   sim/wall min 0.882  median 0.988  max 1.000 | load1 before: median 8.37  max 12.68
```

No agent other than this one was running a simulator; `ps` showed the load was the
user's own desktop (Chrome, the Claude app, Messages, WindowServer, a
Virtualization VM). That load is not controllable from here and it fluctuated
between roughly 3 and 17 over the 74 minutes.

**What I did about it.** The suite was stopped cleanly at a matched-pair boundary
after flight 28 when load reached 12–15, and held for 10 minutes waiting for
quiet. Load did not fall below ~5, because it was the user actively using the
machine, so the suite resumed and the remaining 28 flights were flown and flagged.
The pause is visible in `data/progress.log` as a restart at `start=29`; flight 29's
first, unrecorded partial run was discarded and re-flown whole.

**Why this does not damage the result.** 25 flights sit below `sim_wall_ratio`
0.95 and they are listed individually in `data/analysis.txt`. They are also
**paired**: the degraded stretch is flights 19–43, and within it every matte flight
has a mirrored twin flown within ~60 s — pairs (19,20), (21,22), (23,24) …
(41,42), (43,44), the last of which straddles the recovery. Both arms
took the load equally, which is exactly what the interleaving was for. And the
headline holds in the clean subset on its own: **0/16 matte, 0/15 mirrored among
flights with `sim_wall_ratio ≥ 0.95`.**

One flight of 57 attempts did not produce a run: `mirror B.moving__delta_backend
r1a1` — the simulator started and connected, the follower then hung and wrote
nothing before the 140 s watchdog fired (exit 142, SIGALRM). It was re-flown
automatically and passed. Every one of the 56 scored flights is VALID.

---

## 8. What this changes

**Established by this experiment:**

* The matte floor does **not** cause attitude upsets. 0/28 vs 1/28, and 0/16 vs
  0/15 among flights that kept real time. The Sep 12 rate of 9/21 is excluded at
  p = 1.6 × 10⁻⁷.
* The Sep 12 upset pattern was an **order effect plus machine-state difference**,
  not a physical effect of the scene. Repeat 3, which tumbled in 6 of 7 cells
  there, tumbled in 0 of 14 here once it stopped meaning "flown third".
* The distance improvement is **real and reproduces in all seven cells**,
  including `B.moving__delta_camera`, which was compromised on Sep 12.
* The Sep 12 tracking degradation was a **consequence of the upsets**, not a cost
  of the fix.
* The two Sep 12 suites **differed in their exposure to transient stalls**,
  which disqualifies the floor as the explanation for the upsets. `step_gap_ms.max`
  tracks that exposure better than `sim_wall_ratio` does, though the two groups
  still overlap and it is not a detector (§5).

**NOT established — what I did not prove:**

* **Anything about real hardware.** No real camera, no real Crazyflie, no lab.
  This is a simulator argument end to end. The lab session is still the first test
  of any of it.
* **That upsets can never happen on a matte floor.** 28 flights bound the rate at
  ≤ 12.3% (95%), not at zero. A rare instability is not excluded.
* **The mechanism of the Sep 12 upsets.** I show they track stall exposure and do
  not track the floor. I did not deliberately induce stalls and reproduce an upset,
  which is the experiment that would nail it (§9).
* **That the stall threshold is ~158 ms.** That number comes from 10 events in
  someone else's suite; it is a lead, not a calibration.
* **Whether a real indoor floor reflects enough to matter.** Unchanged from the
  root-cause report: `reflectance = 0` is a judgement, not a measurement.
* **The himax residual.** `delta_camera` now behaves, but himax vs clean still
  differs (2.319 m vs 1.971–2.159 m). Still needs real frames.
* **Anything about the champion-vs-confuser model choice.** Not touched; that is a
  pending team decision and no data here bears on it.

---

## 9. Recommendations (not implemented — nothing under measurement was edited)

1. **Retract the Sep 12 upset finding** before it reaches Prof. Mok or the team.
   Its §6, §7 and the "Removing the mirror is not free" line in its §8 should be
   marked superseded by this report. Its distance result stands and is now
   confirmed twice.
2. **`scoreboard.py` still cannot see any of this.** All 21 Sep 12 flights,
   including one that ended inverted 2.2 m under the floor, scored VALID. Three
   gaps, in priority order:
   - `validity()` should reject a flight whose |pitch| or |roll| leaves the
     envelope, or whose z drops below the floor after takeoff;
   - it should fail a flight on `step_gap_ms.max`, not only on the average
     `sim_wall_ratio` — this run shows the average misses the failure mode;
   - it should enforce a frame-rate floor on `full`-speed cells, which declare
     `rate_hz = 0` and are therefore currently exempt (that is how a 2.6 Hz flight
     scored VALID on Sep 12).
   *Owner: `scoreboard.py`. Not this workstream; not edited here.*
3. **Record `step_gap_ms.max` and load in every future suite's scoreboard**, and
   treat a suite whose arms differ in stall exposure as uncontrolled — that is the
   specific defect that produced the false finding.
4. **The soft-size decode is still worth doing**, but for the reason §6 gives, not
   the Sep 12 one: the quantised size head with no temporal filter makes `vx`
   chatter at ~2 changes/s on **both** floors, and the mirrored `A.static__proven`
   cell parks at 2.423 m against a 2.428 m bucket boundary. This is a control-law
   weakness independent of the scene.
5. **Any future A/B on this laptop should be interleaved in matched pairs.** It
   cost nothing here and it is the reason the degraded stretch did not have to be
   thrown away.
6. **To actually nail the mechanism** (optional): re-fly one matte cell while
   deliberately injecting CPU contention, and see whether upsets appear as
   `step_gap_ms.max` crosses ~200 ms. That is the missing causal step, and it is a
   30-minute experiment.

**For the hardware session.** The Sep 12 warning to stop the flight if the drone
oscillates fore-and-aft as it closes was written on the belief that the matte
floor destabilises it. That belief is withdrawn. Fore-and-aft chatter is still
predicted — it is the quantised size head, it appears on both floors in
simulation, and it stayed within ±7° of level across 28 matte flights. Treat it as
expected behaviour to observe, not a reason to abort. The distance prediction is
unchanged and now better supported: **~1.97–2.16 m with a clean camera, ~2.21–2.43 m
through the himax model, and different every run.** Quote the range.

---

## 10. Reproducing

Run from this directory with
`/Users/saimaruvada/Downloads/drone/trainenv/bin/python` (there is no bare
`python` on PATH).

| script | what it does | runtime |
|---|---|---|
| `scripts/make_plan.py OUT.tsv --repeats 4 --seed 20260932` | builds the interleaved, order-decorrelated plan; prints the balance checks | instant |
| `scripts/fly_plan.sh PLAN OUT MATTE_ROOT MIRROR_ROOT [START]` | flies it, one flight at a time, load sampled around each | ~74 min |
| `scripts/split_and_score.sh OUT` | splits the runs by condition and scores each with the unmodified `scoreboard.py` | ~1 min |
| `scripts/analyze.py OUT` | upsets by condition / order / repeat / cell, matched pairs, Fisher + McNemar, machine table | instant |
| `scripts/compare_conditions.py OUT` | per-cell distance and M1, this run vs Sep 12 | instant |

Scene trees:

```
build_scene.py --def scene_defs/s15_static_offset.json  --out <dir>/scenes_matte
build_scene.py --def scene_defs/s01_control_moving.json --out <dir>/scenes_matte
# and the same two with --out <dir>/scenes_mirror --floor-reflectance 0.2
```

The upset scan as a one-liner over the published logs (note `event == ""`, which
the Sep 12 version did not filter on — it used `wall != ""`; both work on these
logs, but excluding the `after-land` row is what makes `z_min` meaningful):

```bash
for d in data/*_suite/runs/*/; do
  awk -F, -v n="$d" '
    NR==1{for(i=1;i<=NF;i++)h[$i]=i; next}
    $h["event"]==""{p=$h["pitch"];r=$h["roll"];z=$h["pz"];
      if(p<0)p=-p; if(r<0)r=-r; if(p>30||r>30)u++;
      if(zm==""||z+0<zm)zm=z+0}
    END{printf "%-58s upset %4d  z_min %6.2f\n", n, u+0, zm}' "$d/follow_log.csv"
done | sort
```

### What is in `data/`

* `plan.tsv` — the flight plan, with the true chronological order of all 56 flights
* `flights.jsonl` — one record per attempt: order, pair, condition, cell, repeat,
  verdict, timestamps, load average before and after, `sim_wall_ratio`,
  `processed_hz`, `step_gap_ms`
* `flights_scanned.json` — the same, plus the per-flight upset scan
* `matte_suite/`, `mirror_suite/` — per-run `cell.json`, `summary.json`,
  `metrics.json`, `follow_log.csv`, `truth.csv`, plus each arm's `scoreboard.json`
* `analysis.txt`, `distance.txt` — the printed output of the two analysis scripts
* `code_hashes_before.txt`, `code_hashes_after.txt` — the pin, and the proof it held
* `progress.log` — the live flight log, including the pause and resume

Camera snapshots (58 MB of PNGs) were left in scratch and not published.

**State left behind:** none. The two scene trees were built outside the repo;
`tools/crazysim_macos/scenes_v2/` is untouched and still matte. No tool, scene,
or committed result was modified, and nothing was committed or pushed.
