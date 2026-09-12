# Simulator v2 and the first scoreboard — Sep 11–12, 2026

Evidence for the simulator-v2 entry in `EXPERIMENTS.md`. The Sep 10 runs answered
*"does the follower point at the person and not crash?"*. This sweep answers the harder
question the hardware actually cares about: **what will the real drone do, with the real
network, through a realistic camera, at the real frame rate?**

The short version: **pointing and safety survive realism; distance keeping does not.**
The drone holds station 1.3–1.65× further away than the control law is aiming at, in every
configuration including the one every September baseline was measured in. Nobody had noticed,
because until this sweep no metric converted the model's size bucket into metres.

Suite: **14 cells; 37 flights attempted, 36 valid, 1 invalid, 36 scored.**
Verdict: **FAIL** — 7 cells pass, 7 fail.

> **This document has been revised twice.** A *metrics* review (§7) corrected how flights were
> scored and reported. A later *realism* review (§8) corrected the simulator itself — it found
> that the camera's motion blur had never actually done anything, so **all 16 `himax_typical`
> flights were re-flown** and the suite re-scored. No verdict changed. Read §7 and §8 before
> comparing against any earlier copy of this file.

---

## 1. What simulator v2 adds

Four pieces, built by three parallel tasks plus this one. Everything is opt-in: `demo.sh`,
`run_acceptance.sh` and `build_person_scene.py` are byte-unchanged, and `follow_person.py` /
`gap8_emulator.py` only gained flags whose defaults reproduce today exactly.

| Piece | What it gives the simulator |
|---|---|
| **Scene suite** (`build_scene.py`, `scene_defs/`) | 18 scenes from JSON definitions: any number of COCO-cutout subjects with roles (person / pet / teddy / furniture), occluders, clutter, lighting variants. Ground truth extended to **every** subject (`CRAZYSIM_TRUTH_PREFIX`), plus scripted constant-velocity motion (`CRAZYSIM_SCENE_MOTION`), which MJCF alone cannot express. |
| **Chip perception** (`perception_backends.py`, `chip_infer_server.py`) | `--backend chip` runs the firmware's own `preprocess.c` (centre 244×244 crop, 2×2 box to 128×128 uint8) followed by `model_id_dory.onnx`, the chip's integer network, in a `doryenv` sidecar (onnxruntime is not in the flight environment). |
| **Camera realism** (`camera_model.py`) | `CRAZYSIM_SENSOR_PRESET=himax_typical`: auto-exposure to a 60 DN frame mean, optical blur, vignetting, shot/read/fixed-pattern noise, dead pixels, LED banding, and gyro-driven motion blur. `clean` is a byte-identical pass-through. **The motion blur in this sweep's original flights did nothing** — see §8. |
| **This task** (`run_acceptance2.sh`, `scoreboard.py`) | The CORE matrix runner (headless, one flight at a time under the shared lock, validity-checked on landing, re-flown once if invalid) and the scorer that turns flights into PASS / FAIL / INVALID with a plain-English report. |

**Two scenes were added here** because the matrix needs one per class and the 16 built
scenes had no static-person scene and no furniture-only scene:
`s15_static_offset` (class A — same geometry as the legacy `scenes/static_offset`, so the
Sep 10 static baseline applies) and `s16_furniture_only` (class E — s13's chair, couch, plant
and TV with the person removed).

---

## 2. The scoreboard

"**ships-as**" = chip network + realistic camera + 6.5 Hz / 153 ms — what the real drone will be.
"**proven**" = float model + clean camera + full speed — the setup the September baselines were
measured in, so it separates *new breakage* from *the cost of realism*.

Distances are the median across a cell's flights, with the per-flight range beside them. A
single median is what turns "2.81 to 3.78 m" into a confident-sounding "3.30 m", and the whole
document is about a distance, so the spread travels with every one of them.

| Scene | What it tests | Setup | Tracked | Pointing error | Distance held (target 1.94) | False follows | Verdict |
|---|---|---|---|---|---|---|---|
| Person standing still | person, still | ships-as | 99.0% | 4.1° avg (6.0 worst) | 3.03 m (2.73–3.35, n=4) | 0 | **FAIL** |
| Person swaying | person, moving | ships-as | 99.2% | 3.2° avg (8.0 worst) | 3.33 m (3.30–3.35, n=2) | 0 | **FAIL** |
| Empty room | nobody present | ships-as | 0.0% | n/a | n/a | 0 | PASS |
| Person behind a partition | hidden then seen again | ships-as | 65.7% | 5.1° avg (13.9 worst) | n/a | 0 | PASS |
| Furniture and boxes | inanimate distractor | ships-as | 0.0% | n/a | n/a | 0 | PASS |
| A dog and a cat | animate distractor | ships-as | 73.5% | n/a | moved 2.48 m | 1 | **FAIL** |
| Person standing still | person, still | proven | 99.6% | 0.9° avg (2.0 worst) | 2.42 m (2.22–2.58, n=5) | 0 | PASS |
| Person swaying | person, moving | proven | 99.7% | 2.8° avg (8.6 worst) | 2.68 m (2.66–2.71, n=5) | 0 | **FAIL** |
| Empty room | nobody present | proven | 0.0% | n/a | n/a | 0 | PASS |
| Person behind a partition | hidden then seen again | proven | 77.4% | 3.9° avg (11.8 worst) | n/a | 0 | PASS |
| Furniture and boxes | inanimate distractor | proven | 0.0% | n/a | n/a | 0 | PASS |
| Person swaying | one factor: chip network | chip/clean/full | 99.4% | 2.9° avg (7.6 worst) | 2.81 m (2.79–2.84, n=2) | 0 | **FAIL** |
| Person swaying | one factor: realistic camera | float/himax/full | 99.6% | 3.0° avg (8.8 worst) | 3.01 m (2.98–3.04, n=2) | 0 | **FAIL** |
| Person swaying | one factor: chip speed | float/clean/chip | 99.2% | 2.9° avg (8.9 worst) | 2.78 m (2.75–2.81, n=2) | 0 | **FAIL** |

"Worst" is the largest single-frame pointing error in **any** repeat of that cell, not the
median of the per-flight maxima. A maximum is the one statistic there is never a reason to
average.

Full machine record in `scoreboard.json` (every flight, every gate, the *basis* string saying
where each threshold came from, and a per-attempt ledger); the same table for a non-expert in
`scoreboard.md`.

---

## 3. Findings

### 3.1 The drone parks too far away — and it is the size head, not the controller

**6 of the 7 failures are this one problem.** The follower drives
`vx = k_fwd * (0.625 − size_value)` and stops closing the instant the decoded size reaches the
middle bucket. For a 1.7 m person that bucket *should* mean 1.62–2.43 m (target 1.94 m). In
flight the model reports the middle bucket much further out, so the drone stops early — and by
its own logic it is behaving perfectly.

How far out, measured as *decoded size ÷ the size the geometry implies*. Every column below is
computed by `scoreboard.py` over the **M7 settled window** — the same window the distance gate
is scored on — and lands in `scoreboard.json` as `M7_size_*`, so the table regenerates from the
run data rather than being typed by hand:

| configuration | mean distance | geometry says | model decoded | over-read ratio | final distance |
|---|---|---|---|---|---|
| float / clean / full (proven) | 2.687 m | 0.454 | 0.610 | **1.345×** (1.318–1.352) | 2.682 m |
| chip / clean / full | 2.773 m | 0.439 | 0.614 | 1.397× (1.394–1.400) | 2.813 m |
| float / himax / full | 3.050 m | 0.399 | 0.624 | 1.568× (1.557–1.578) | 3.012 m |
| chip / himax / chip speed (ships-as) | 3.168 m | 0.384 | 0.633 | **1.649×** (1.627–1.670) | 3.326 m |

Each cell is the median across that cell's flights of a per-flight mean; the bracketed range is
the per-flight spread of the ratio. The ordering is monotone and holds under every averaging
window tried (last 5 s and last 10 s give 1.31–1.75×), so the finding does not depend on the
window — but the numbers above are the ones the scorer computes, and they are the ones to quote.

Four independent checks say this is real perception behaviour, not a harness artefact:

1. **It is not the controller.** `cmd_vx` is exactly 0.00 while the drone sits at 3.4–3.8 m with
   `size_bucket = 2`, tracking latched and heading error 5°. It believes it has arrived.
2. **It is not the scene.** The panel is a box of half-height 0.8500 (= 1.700 m, matching the
   manifest), and the rendered person spans 99.4% of it (1.690 m of 1.700 m). The geometry
   behind the distance target is honest to 0.6%.
3. **It is not the closed loop.** `build_scene.py --preview` probes the float model on a clean
   render with no simulator and no follower: at 2.69 m from a 1.7 m person, geometry says size
   0.451 (bucket 1) and the model returns 0.625 (bucket 2). The bias is visible in one still frame.
4. **It is not new.** The *proven* configuration over-reads by 1.345×. The September baseline's
   "closed to 2.3 m" was never the 1.94 m the control law aims at.

The two `himax` rows moved slightly when those flights were re-flown on the fixed camera model
(§8): 1.504 → 1.568× and 1.632 → 1.649×. The ordering, and the conclusion, are unchanged.

**What this means for hardware.** In the configuration that will actually fly, expect the drone
to hold station somewhere in the range **2.7–3.4 m**, not 2 m. The honest statement is a range,
not a point: the static ships-as cell was re-flown four times and finished at 3.35, 3.08, 2.90 and
2.73 m — a 0.62 m spread on an unchanging scene. For a person-following nano-drone indoors even
the near end of that range is the difference between "following me" and "watching me from across
the room". The fix is in the size head (more buckets, or a scalar size output), not in `k_fwd` —
the quantisation floor alone is ±0.40 m.

### 3.2 The cost of realism stacks, roughly additively, and the camera dominates

One factor moved at a time off the proven baseline, median final distance on the moving scene.
The baseline is the same 5-flight median the scoreboard reports for `B.moving__proven`, so every
row below is on the same footing:

| configuration | final distance | cost vs proven |
|---|---|---|
| float / clean / full (baseline, n=5) | 2.682 m | — |
| + chip speed (6.5 Hz, 153 ms) | 2.781 m | +0.099 m |
| + chip network | 2.813 m | +0.131 m |
| + realistic camera | 3.012 m | **+0.330 m** |
| all three (ships-as) | 3.326 m | +0.644 m |

Sum of the individual costs is **+0.560 m against +0.644 m measured — about 13% apart**, with the
combination costing more than its parts. Close enough to call the factors roughly additive and to
say the camera dominates; not close enough to call it additive "within 4%", which an earlier draft
did by comparing against a stale 2-repeat baseline of 2.668 m.

**Pointing error is untouched by all of it**: 2.77° proven → 2.87° (speed) → 2.91° (network) →
2.99° (camera) → 3.16° (all three). Realism costs distance, not heading.

### 3.3 The drone chases a dog, and the chip network does not save it

On the pet scene the follower confirmed a **dog** 0.31 s into the flight at confidence 0.87–0.89,
stayed latched **68%–78%** of the flight, and flew **2.3–2.7 m** across the room toward it.
This was already known as a 30.2% *per-frame* false-alarm rate; it is now a flight behaviour, and
it survives the chip network and the realistic camera unchanged — the re-fly on the fixed camera
model (§8) made it slightly worse, not better.

*One note on the number the scoreboard prints for this cell.* The two repeats drifted
2.301 m and 2.666 m, and `scoreboard.md` reports the **worse** of the two (2.666 m). An earlier
board printed 2.301 m: the scorer labelled every hard gate "worst repeat" but in fact kept the
*first failing* repeat. It never changed a verdict — any failing repeat fails the cell, and both
fail here — but it understated the magnitude, so the selection now compares the repeats and keeps
the numerically worst. It was the only hard gate in the suite where the two disagreed.

Per the spec, class-F false-follow counts are **characterised, never gated** — inventing a pass
mark there would be dishonest. But class F also carries one hard gate, "it must not fly across
the room even if it latches" (drift < 0.5 m), and 2.4 m fails it. **That cell is red by design
and must not be quietly disabled**: it is the closed-loop evidence for the champion-vs-confuser
model decision (champion 30.2% vs confuser 11.0% per frame).

### 3.4 Occlusion: the safety rule holds, but the old reacquire number measured nothing

The safety rule held on every flight: the drone **never once steered before re-confirming**, and
always waited exactly 3 fresh frames.

The reacquire timing needed rebuilding. The metric previously published as `M9_reacquire_s`
measured the interval from the *start of the confirming streak* to the first non-zero command.
That start is defined as `k − streak + 1` with `streak` always 3, so the quantity is structurally
two frame periods plus a control tick — across the four occlusion flights its nine episodes
measured 1.70 to 4.03 frame periods. It could only have exceeded its 1.0 s / 1.5 s gate through a
command-path bug, and it never described how long the drone was actually blind. It is now named
**`M9_reconfirm_latency_s`**, is report-only, and its gate basis says what it is.

Three metrics replace it, all computed from the simulator's ground truth against the scene's
declared occluder geometry (a line-of-sight test sampling 21 points across the target's width —
a single centre ray calls a person "visible" while nine tenths of them is behind the partition):

| measurement | proven | ships-as | gate |
|---|---|---|---|
| `M9_track_outage_s` — how long the track was lost at all | 8.47 s (8.46–8.48) | 15.8 s (15.7–15.9) | never gated |
| `M9_gt_visible_to_relatch_s` — blind time after the person was **fully** back in view | 0.47 s (0.33–0.61) | 1.33 s (1.25–1.41) | ≤ 1.0 / 1.5 s — **PASS** |
| `M9_gt_halfvisible_to_relatch_s` — the same, counting from **half** the body clear | 1.13 s (0.66–1.60) | 2.51 s (2.51–2.52) | report-only — *would fail* |
| `M9_reconfirm_latency_s` — the old quantity, renamed | 0.17 s (0.13–0.21) | 0.32 s (0.32–0.32) | report-only |

**Read this cell carefully; its verdict is sensitive to a definition we chose.** Gated on
"fully clear of the partition", both occlusion cells pass. Gated on "half the body clear", both
would fail. We gate the fully-clear reading because that is the only one where the target is
unambiguously visible and the drone has no excuse — half a person behind a partition is a
genuinely hard detection, and no verified baseline exists for it. The half-visible number is
reported alongside, and in the v2.1 calibration table, precisely so the choice is visible rather
than buried. The threshold itself is not invented: it is the spec's own §4 M9 reacquire gate,
finally applied to the quantity §4 describes.

*Spec correction, corrected:* an earlier draft said the structural floor is `2/R` rather than the
spec's `3/R` and that "the measurements match `2/R` to the millisecond". They do not. At 6.5 Hz
`2/R` is 0.311 s while the measured median is 0.318 s; at ~15 Hz `2/R` is 0.133 s against 0.171 s.
`2/R` is a property of how the confirming streak is defined, not a measurement of the drone, and
the sentence claiming a match has been removed rather than restated.

### 3.5 What else survived realism

- **Empty room**: 0% tracked, zero drift, peak confidence 0.571–0.589 — **no frame ever reached
  the 0.70 latch threshold**, on the ships-as configuration. Exactly matches the Sep 10 baseline.
- **Furniture and boxes** (new scene): 0% tracked, zero drift, peak confidence 0.601–0.632 after
  the re-fly (0.586–0.601 before). It passes — but the margin is thin and got thinner; what is
  holding is the "3 consecutive frames" rule, not the raw confidence.

### 3.6 Three honest caveats about the scoreboard itself

**The M7 threshold is stricter than its own justification.** The 0.75 m gate is justified in the
spec by "the verified 2.3 m static baseline scores 0.36 m" — but 0.36 m is a *final-distance*
error, while the gate is applied to a *settled-window mean*. Those differ:

| cell | settled-window mean (gated) | final-distance error (the basis quantity) |
|---|---|---|
| static, proven | 0.669 → pass | 0.484 → pass |
| moving, proven | 0.744 → pass | 0.742 → pass |
| static, ships-as | 1.110 → FAIL | 1.051 → FAIL |

Every ships-as cell fails on both quantities, so the headline finding does not depend on this.
But whoever owns the spec should decide which quantity M7 gates and make the basis string match it.

**`A.static__proven` is a coin flip, and it is now scored on every flight of it.** The cell has
five valid flights, with settled-window means of 0.611, 0.658, 0.669, 0.782 and 0.953 m against a
0.75 m gate. The median is 0.669 → **PASS**. Three of those five sit below the gate and two above,
and the five values span 0.611–0.953 *around* the threshold, so this verdict would flip on a
different sample of three. Read it as "borderline", not "passing".

This matters because an earlier draft of this document scored the cell **FAIL** on a subset. A
standalone 3-repeat re-fly of the cell had been flown and had scored PASS (0.658, 0.669, 0.782);
only its third flight was carried into the published suite, where it joined two earlier flights
(0.953, 0.611) to give a median of 0.782 → FAIL. The two passing flights were valid, were flown
under identical configuration, and were not mentioned. All five are now in `runs/` and all five
are scored. The same undisclosed discard applied to `B.moving__proven`, which is also now scored
on five flights (that cell's verdict does not change).

**Run-to-run spread is the dominant uncertainty, and single flights cannot settle anything here.**
The static ships-as cell was flown twice, finished at 3.78 and 2.81 m, and its uncertain-band
fraction was 0.028 on one repeat and 0.249 on the other — the same scene, a different camera-noise
seed. Two further repeats were flown after this review; the four finals are 3.78, 3.08, 2.90, 2.81
and the median moved from 3.30 m to 2.99 m. One caveat on those four: `run_acceptance2.sh` derives
the camera seed as `1000 + repeat`, so repeats 3 and 4 reused the seeds of repeats 1 and 2. They
are two seed pairs, not four independent draws of camera noise.

---

## 4. Calibrating the provisional gates (for v2.1)

M11 (smoothness), every relaxed threshold for the degraded camera, and the new half-visible
reacquire reading are **report-only** in this release, because no measured baseline exists — the
spec's own rule forbids gating on a guessed number. This sweep produces the first observations;
the rule is `threshold = max(provisional, 2 × observed median)`:

| metric | class | observed median | range | provisional | v2.1 gate |
|---|---|---|---|---|---|
| yaw reversals /min | A (static) | 0.0 | 0.0–1.85 | ≤ 8 | ≤ 8 (unchanged) |
| yaw reversals /min | B (moving) | 4.70 | 3.17–4.81 | ≤ 24 | ≤ 24 (unchanged) |
| yaw saturated fraction | A and B | 0.0 | 0.0–0.0 | ≤ 0.25 | ≤ 0.25 (unchanged) |
| uncertain fraction, himax | A | 0.088 | 0.015–0.279 | ≤ 0.15 | needs more repeats — the spread still straddles the threshold |
| `M9_gt_halfvisible_to_relatch_s` | D (proven) | 1.13 | 0.66–1.60 | ≤ 1.0 | decide the visibility definition first (§3.4) |
| `M9_gt_halfvisible_to_relatch_s` | D (ships-as) | 2.51 | 2.51–2.52 | ≤ 1.5 | as above |

The steering is far smoother than the provisional marks assumed: a median of **zero** yaw
reversals on a static target and 3.2–4.7/min on the swaying one, against a legitimate 6/min from
the scene's own 20 s sway period. No saturation anywhere.

---

## 5. What is still NOT simulated

- Every subject is a **flat photograph on an opaque rectangular board**: no parallax, no limb
  articulation, no self-occlusion, no change of appearance when a person turns around. The board
  itself is visible — everything outside the COCO mask is painted wall colour, and the edge step
  against the floor measures **+39 to +108 DN**, so the network is partly keying on a
  high-contrast rectangle. This cannot be fixed with transparency: MuJoCo 3.13 drops the alpha
  channel at load (`tex_nchannel` = 3 for an RGBA PNG), a flat mask-shaped mesh fails to compile,
  and an extruded one renders nothing. A background-matching composite exists
  (`build_scene.py --background sampled`) but is **off by default** because it changes what the
  network reports rather than only how the scene looks — see §8.
- The renderer has **no auto-exposure** and renders scenes over-exposed (23–32% of pixels clipped
  at 254; 25.8% on the control scene). The sensor model does its auto-exposure on an
  already-clipped image, so highlight detail the real Himax would resolve is flat grey here.
  Measured over the formerly-clipped region the vignette-corrected spatial sigma is 2.32 DN
  against 1.80 DN for shot + read + quantisation noise alone — 1.29×, i.e. essentially just
  noise. **"0.0% saturated after the sensor model" is therefore not evidence the exposure gap is
  closed**; it says only that nothing clips once the frame has been rescaled.
- **Nine camera parameters are UNMEASURED placeholders** (PSF sigma centre/corner, vignette
  a2/a4, PRNU, DSNU, dead-pixel fraction, AE damping, scene_light). They carry the tag into every
  `camera_model.json`.
- Rolling shutter and lens distortion are implemented but **off** in every preset.
- Whether the AI-deck is **mono or Bayer is still unknown**.
- No wind, turbulence, propeller wash, battery sag, or radio dropouts.
- The **firmware-in-the-loop path** (`gap8_emulator.py` + the STM32 follow app) is not in CORE;
  CORE flies the host follower only.
- The architecture has **no target identity**, so a person leaving and a teddy remaining is
  unrecoverable by construction (scene `s14`, not in CORE).
- Ground-truth visibility (§3.4) is a **2-D line-of-sight test** against declared occluder boxes.
  It knows nothing about what the renderer actually drew, so it is a geometric proxy, not a
  measurement of what the camera saw.
- Every camera number is a **model, not a measurement** — the real Himax has never been
  photographed through this pipeline.

---

## 6. Files here, and how to reproduce

```
scoreboard.json / scoreboard.md   the machine record and the readable report
progress.log / progress.md        the live log the sweep wrote as it flew, plus a table of
                                  the flights merged in after the first scoring pass
suite_meta.json                   suite, timing, model paths
runs/<cell>__r<N>a<A>/            per flight: cell.json (what it was), summary.json,
                                  metrics.json (every metric + gate), camera_model.json;
                                  one representative flight per cell also keeps
                                  follow_log.csv (every control step) and truth.csv
moving_ships_vs_proven.png        heading vs the true bearing, ships-as against proven
static_ships_vs_proven.png        the same for the static scene
```

**Re-scoring this folder.** `scoreboard.py docs/sim_results/2026-09-11-simv2` rebuilds
`scoreboard.json` and `scoreboard.md` from what is here and reproduces the verdicts above. The
representative flights are re-derived from their `follow_log.csv`; the flights whose log was
trimmed are scored from their own `metrics.json`, which the scorer leaves untouched and names on
stdout. Re-deriving *every* flight from raw logs needs the untrimmed suite, not this folder.

**The flight ledger.** 37 flights were attempted, 36 were valid, 1 was invalid, and 36 are
scored — every valid flight of every cell. `runs/` holds all 37 attempt directories. The counts
differ from a cell count because a cell is scored on the best attempt of each of its repeats:
14 cells, but 2 to 5 repeats each.

The one invalid attempt is `B.moving__delta_backend__r1a1` (flight 27 of the original sweep). It
hit the runner's watchdog (`exit 142`) and **produced no follower control log** — an earlier draft
said it "produced no run", which is wrong: the directory holds a 94 KB `truth.csv`, a `sim.log`
showing the firmware connected, an empty `follower.log`, and a `metrics.json` marked
`valid: false` with its reasons. The runner's retry-once logic re-flew it as `r1a2`, which came
back valid and is the flight that was scored. No invalid attempt is counted as a pass anywhere:
a cell with fewer than two valid flights is INVALID by construction.

**How this suite is assembled** (it is labelled `core-rescore`, and `scoreboard.json` says so).
It is not one sweep but two sources, merged deliberately:

- The seven **`clean`-camera cells** are the original flights, reused unchanged — 21 attempt
  directories, including the four tie-break flights (`A.static__proven__r4a1`/`r5a1`,
  `B.moving__proven__r4a1`/`r5a1`) that the metrics review restored. They are reused because the
  camera fixes provably cannot reach them (§8.3), and the merged re-score reproduces their
  published verdicts and counts exactly.
- The seven **`himax_typical` cells** are the 16 flights re-flown after the realism review (§8):
  7 cells × 2 repeats, plus two extra `A.static__ships` repeats so that cell keeps the four
  flights its headline hold distance is quoted from.

Merging two sources needs care the naive way would get wrong: both number their repeats from
`r1`, and the scorer lets a later attempt *supersede* an earlier one with the same repeat number.
Copied naively, the tie-break flights would have silently replaced the originals — which is
exactly the subset-scoring bug the metrics review had to fix on `A.static__proven`. Flights are
therefore de-duplicated by content and renumbered past the repeats already present, and the
resulting clean-cell verdicts were checked against the published ones before the himax half was
added.

**No camera imagery is included.** Every subject in the v2 scenes is a COCO cutout, so scene
previews and follower snapshots are COCO-derived; this follows the Sep 10 results README
("camera snapshots are not included because they contain the COCO photo") and the reason
`scenes_v2/` is gitignored. Regenerate previews locally in one command:

```bash
cd tools/crazysim_macos
../../../trainenv/bin/python build_scene.py --all --preview     # contact sheets per scene
```

To re-fly only the cells the camera model can affect (what §8 did):

```bash
./run_acceptance2.sh --only '(__ships|delta_camera)' --repeats 2 --out DIR
```

Re-fly or re-score:

```bash
./run_acceptance2.sh --list                 # the matrix, fly nothing
./run_acceptance2.sh                        # 14 cells x 2 repeats, ~35 min
./run_acceptance2.sh --only 'A\.static__ships' --repeats 2 --out DIR   # more repeats of one cell
../../../trainenv/bin/python scoreboard.py <out_dir>     # re-score offline, any time
../../../trainenv/bin/python analyze_follow.py runs/<cell>/ <px> <py> --truth runs/<cell>/truth.csv
```

---

## 7. What the metrics review changed

Seven findings were applied. Three changed a published number or a verdict; four changed how a
number is reported. Nothing about the simulator, the follower, the scenes or the camera model was
touched, so **no existing flight needed re-flying** — every change is in scoring and reporting,
and all 37 flights were re-scored from their original logs.

| # | Finding | What changed |
|---|---|---|
| 1 | `A.static__proven` was scored on a subset that discarded two valid passing flights | **Verdict FAIL → PASS.** Cell now scored on all 5 valid flights (median 0.669 ≤ 0.75). The discard is disclosed in §3.6, along with the fact that the cell is a coin flip either way. |
| 2 | `M9_reacquire_s` could not measure reacquisition; its gate was unfailable | Renamed to `M9_reconfirm_latency_s` (report-only). Three ground-truth metrics added, one of them gated (§3.4). The "2/R to the millisecond" claim and "got the person back 0.47 s after seeing them again" are removed. |
| 3 | The flight ledger understated what was flown | `scoreboard.py` now reports attempts flown / valid / invalid / scored separately, with a per-attempt record in the JSON. §6 rewritten; "produced no run" corrected. |
| 4 | The §3.1 size table was not reproducible from the run data | The four columns are now computed by `scoreboard.py` over the M7 settled window and stored as `M7_size_*`. Table regenerated; ratios moved from 1.31–1.73× to 1.345–1.632×. |
| 5 | The §3.2 additivity table used a stale 2-repeat baseline | Recomputed against the 5-flight median (2.682 m). "Additive within 4%" → **about 9%**. |
| 6 | "Worst" pointing error printed the median of per-flight maxima | Now prints the true maximum. Occlusion ships-as 19.7° → **21.5°**; static ships-as 5.2° → 5.7°; moving ships-as 8.7° → 9.2°. |
| 7 | A single headline hold distance hid a 0.97 m spread | Every distance now carries its per-flight range, and two more `A.static__ships` repeats were flown. Median **3.30 m → 2.99 m**; the hardware prediction is now a range. |

A control confirms finding 1 is about the data, not the code: re-scoring the *original,
unmerged* flight set with the *new* scorer still yields 6 pass / 8 fail with
`A.static__proven` FAIL. Only adding the discarded flights moves it.

---

## 8. What the realism review changed (Sep 12)

A second review looked at the simulator itself rather than the scoring: *is the realism real?*
Seven findings, all applied. Two were code defects that made a shipped capability a no-op or
mis-stated what a preset does; four were overclaims in the documentation; one was a missing
provenance field. The scenes are **byte-identical** to the ones every flight above was flown on
(all 31 cutout PNGs verified by sha256), so nothing in §2–§4 is invalidated except where §8.3
says so.

### 8.1 The defects

| # | Finding | What it was | What it is now |
|---|---|---|---|
| 1 | **Motion blur was a silent no-op** (high) | `_box_kernel` sized its support as `ceil(L)`, so every smear of 0 < L ≤ 1 px collapsed to the single tap `[1.0]` — an exact identity — and the 0.5 px gate admitted `(0.5, 1.0]` only to throw it away. This was **100% of real flight blur**: at the exposure the control flight ran (137 lines = 4.257 ms) the follower's own 40 °/s yaw cap is **0.52 px**, and commanded yaw over that flight gives mean 0.06 px / max 0.35 px — **0.0% of frames ever reached the old gate**. The unit test that "verified" it used the 10.56 ms AE-ceiling exposure (L = 1.28–10.28 px), i.e. exclusively the regime where the kernel worked. | Below ~1.12 px the kernel moment-matches the smear (L = 0.7 → variance `L²/12` = 0.0408, the review's own target; it moves ~5 DN across a hard edge). Above it, the exact area-overlap box with a support wide enough that no tap is truncated. Gate 0.5 → 0.01 px. `test_sub_pixel_motion_blur_actually_softens_the_image` replaces the test that asserted the no-op, and `test_box_kernel_is_sane_across_every_regime` pins 0.05–10 px. 23/23 camera tests pass. |
| 6 | **Emulator flights recorded no backend** (med) | `gap8_emulator.py`'s summary carried only the *requested* flags, so a chip-in-the-loop run held no record of which ONNX (sha1) or output quantum the sidecar actually loaded — on the one path that is actually chip-in-the-loop. | `backend` and `backend_info` added, matching what `follow_person.py` already wrote. **Correction to the review:** it said "`perc` is already in scope; this is a two-line change." It is not — `perc` lives in `main()` while the summary is built in `write_outputs()`, so it had to be threaded through. Applied literally, the suggested edit raises `NameError` at the end of every emulator flight. `--selftest` still passes (decoder == `follow_decode.c` on 200 000 frames). |

### 8.2 The overclaims

| # | Claim | Measured reality |
|---|---|---|
| 3 | "`camera_model.py` closes the exposure gap" | It closes half. AE fixes the frame mean and the noise regime; it cannot recover the **25.8%** of pixels the renderer clips at ≥ 254. Over the formerly-clipped region the vignette-corrected spatial sigma is 2.32 DN vs 1.80 DN for noise alone — 1.29×, essentially just noise. "0.0% saturated" is evidence only that nothing clips *after rescaling*. |
| 4 | `himax_low_light` "drives analog gain to 8×" | It usually does not. On real renders across 20 seeds it settled on analog **4× nine times and 8× eleven**, total gain 7.70–8.06× throughout, because the required ratio sits exactly on `_pick_gain`'s 4×/8× boundary. The split is physically inert (the noise model uses *total* gain for both shot and read terms), so the preset is now specified by **~8× total gain and ~4.3 DN noise** — what it actually delivers — and the test gates total gain, not the analog step. |
| 2 | Cutouts "blend into the wall behind" | They do not: each subject is an **opaque rectangular card**, and the edge step measures **+39 to +108 DN against the floor**. Real transparency is impossible here — MuJoCo 3.13 drops the alpha channel at load (`tex_nchannel` = 3 for an RGBA PNG), a flat mask-shaped mesh fails to compile ("coplanar vertices"), and an extruded one rendered zero pixels; all three were tried and measured. A background-matching composite was built, calibrated and measured (`build_scene.py --background sampled`): it reaches 2.8–11.7 DN on people and pets but never the ~5 DN target elsewhere, and makes furniture worse (couch wall −74 → −95 DN). It is **opt-in and unflown**, because it changes what the network reports rather than only how the scene looks — see §8.4. |
| 5 | `s12_dim_room` tests a dim room | It tested nothing. The render was mean 1.15 DN, max 2, **three distinct grey levels** in the whole frame, subject contrast −0.4 DN; because the renderer quantises to 8 bits first, `himax_typical` could only amplify quantisation (mean 25 DN at the 340-line/8×/3.00× ceiling) and `himax_low_light` returned mean 5 DN. Its lighting now renders at **mean 40.7 DN with 89 distinct levels**, 0% saturated, and the dim-room physics comes from the sensor preset (`himax_low_light` still drives ~24× total gain). Its old caveat — "the simulator has no auto-exposure" — was obsolete: the simulator models AE now. Not in CORE; unflown. |
| 7 | `raw_i32` is "the chip's exact integer outputs" | It is onnxruntime's reproduction of the chip's integer domain — exact to a rounding step, but not bit-identical to the DORY simulator: on the release's own 96 images the rounded values differ on **58 of 96**, by up to 290 counts (0.058 in logit units). The decisions survive (visibility gate 96/96, size 96/96, x-bin 95/96). Bit-exact reproduction needs the DORY sim, not ORT. Docstring and inline comment corrected; no code change. |

### 8.3 Why only some cells were re-flown

Finding 1 changes `himax_typical` frames, so **every himax cell was re-flown**: the six ships-as
cells plus `B.moving__delta_camera`, two repeats each, headless and one at a time under the shared
lock.

The seven `clean`-camera cells were **not** re-flown, and that is a provable statement rather than
a judgement call: with `CRAZYSIM_SENSOR_PRESET` unset, `from_env()` returns `None` and the patched
simulator takes its original luma line verbatim — verified directly (unset, empty and `clean` all
return `None`) and pinned by `test_clean_is_byte_identical_pass_through`. The kernel fix cannot
reach those frames. Their flights are reused unchanged, and the merged suite reproduces their
published verdicts and flight counts exactly (`A.static__proven` PASS on 5 valid flights,
`B.moving__proven` FAIL on 5, and the rest as before).

### 8.4 Why the scene fix is off by default

The background-matching composite is the one fix in this round that was built, measured and then
**deliberately not shipped as the default**. It improves the edge step where it was calibrated,
but it also moves the network's own outputs: on the furniture scene — which exists precisely to
confirm the drone ignores inanimate objects — confidence rose from **0.755 to 0.957** against a
0.70 latch threshold, and on the control scene the size bucket moved **0.625 → 0.375** at 3.5 m,
which feeds the forward-velocity law and therefore the headline hold-distance metric. Turning it
on would quietly change the acceptance results it is supposed to make more realistic. It ships as
`--background sampled`, unflown, with the residual recorded per subject in each scene's
`manifest.json` under `subjects[].background.fidelity_notes`.

### 8.5 What the re-fly measured

All 16 `himax_typical` flights were re-flown on the fixed camera model: 14 in the CORE matrix
(7 cells × 2 repeats) plus 2 extra `A.static__ships` repeats, so that cell keeps the 4 flights it
was scored on before. **Every flight was valid** (sim/wall 0.997–1.000, requested rate achieved,
no torn frames), and the merged suite carries the same ledger as before — 37 attempted, 36 valid,
1 invalid, 36 scored.

**No verdict changed. The suite is still FAIL, 7 pass / 7 fail, with the same cells failing on the
same gates.** That is the headline: the blur fix is real, but it is small, because at the
exposure these flights actually ran the smear is 0.06–0.35 px — sub-pixel, exactly where the old
kernel was silently discarding it.

| cell | verdict | what moved |
|---|---|---|
| `A.static__ships` | FAIL → FAIL | M7 1.109 → 1.153 m; final 2.99 → 3.03 m; uncertain fraction 0.171 → 0.088 |
| `B.moving__ships` | FAIL → FAIL | M7 1.200 → 1.225 m; worst pointing 8.7° → 8.0° |
| `C.empty__ships` | PASS → PASS | nothing measurable (0% tracked, zero drift, both before and after) |
| `D.occlusion__ships` | PASS → PASS | **improved**: tracked 59.8 → 65.7%, worst pointing 21.5° → 13.9°, uncertain fraction 0.123 → 0.070; but blind time after the person is fully clear rose 1.24 → 1.33 s |
| `E.furniture__ships` | PASS → PASS | peak confidence on a person-free scene 0.594 → 0.617, against a 0.70 latch threshold — still passing, with less room |
| `F.pets__ships` | FAIL → FAIL | **worse**: it tracked the dog 61.7 → 73.5% of the flight and drifted 2.35 → 2.48 m |
| `B.moving__delta_camera` | FAIL → FAIL | M7 1.000 → 1.107 m; mean pointing 2.68 → 2.99° |

Two of those are worth not glossing over. `F.pets__ships` — the scene that measures whether the
champion model chases animals — got **worse**, and `E.furniture__ships` lost margin on the one
threshold that keeps it passing. Neither is a large move and both cells have only two repeats, so
the honest reading is "within run-to-run spread, and in the unhelpful direction", not "the fix
made detection worse". `D.occlusion__ships` moved the other way by more. What none of them do is
change a verdict.

**The fix costs more than it used to, and now breaches its own budget.** Because the blur
convolutions run on every frame instead of never, the sensor model went from **2.23 ms/frame mean
(4.19 ms worst)** to **3.50 ms mean with a worst single frame of 7.27 ms — and 6 of the 16 runs
had a worst frame above the spec's 5 ms cap**. The unit-test bench does not see this: in
isolation it measures 1.8 ms, and in flight the follower and the model share the Mac. Nothing
downstream broke — every flight was valid and the sim kept real time, which is what the cap
exists to protect — but a budget is a budget, and this is the one thing in this round that got
worse and was not fixed. The measured remedy, not yet applied: skip the convolution when the
kernel's side tap falls below ~0.0005, which at the observed in-flight rates skips 64.5% of
frames while forgoing at most ~0.26 DN, well under the quantisation floor.

