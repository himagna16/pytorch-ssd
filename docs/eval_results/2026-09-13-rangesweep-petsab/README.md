# Two experiments: the static range sweep, and a controlled mirrored arm for the dog

**Nothing here was measured on hardware. Every frame is rendered. Nothing in this
report says anything about a real Crazyflie.**

Two things the mirror-free baseline (`docs/eval_results/2026-09-13-matte-baseline/`)
listed as *not established*, settled here:

1. **The range sweep.** `D.occlusion__proven` flipped PASS → FAIL on the M9 relatch
   gate (0.47 s → 3.24 s against a 1.0 s gate), and the baseline could not separate
   "the scene stopped posing an occlusion question" from "the detector genuinely
   loses a plainly visible person inside 2.5 m". Its own recommendation §8.3 was a
   static range sweep. That is experiment 1.
2. **A controlled mirrored arm for `F.pets__ships`.** The matte pets numbers that the
   champion-vs-confuser decision will rest on were compared against the Sep 11 suite —
   a different day, a different machine state, 2 repeats. Before/after, not A/B. That
   is experiment 2.

Ran 2026-09-12, 18:02–18:25 CDT (23:02–23:25 UTC), on a laptop running nothing but
the user's desktop. (The directory is named `2026-09-13-rangesweep-petsab` per the
workstream instruction; `progress.log`, `flights.jsonl` and the `*_meta.json` files
are the authoritative record of when it ran.)

Companions, none of them modified: `docs/eval_results/2026-09-13-matte-baseline/`,
`docs/eval_results/2026-09-13-stability/`, `docs/eval_results/2026-09-12-distance/`,
`docs/sim_results/2026-09-11-simv2/`.

---

## 0. TL;DR

| claim | verdict |
|---|---|
| There is a genuine close-range detection falloff on a person | **no.** 1.0–4.0 m, both backends, both cameras, 100% of frames above the 0.70 latch threshold at every range on the acceptance suite's own subject |
| The baseline's 92.5% → 73.6% → 54.0% close-range collapse is real | **no — it is a bug.** Its script joins the follower's clock to the simulator's clock; corrected, the trend **reverses** (92.9% → 86.3% → 71.6%) |
| So what does lose the track? | **viewing azimuth off the flat subject card.** Above ~40° confidence collapses; 79.0% of lost-track frames are at azimuth ≥ 40°, against 5.5% of tracked frames, at the same mean range |
| …and the partition itself contributes | **yes, second-order.** Same pose, partition deleted: +0.041 mean confidence overall, **+0.115 on the frames the flight actually lost** |
| Float and chip networks differ | **not on an easy subject** (0.0–0.5% latch disagreement); **badly on a marginal one** (21.5–27.0%) |
| The himax camera shifts the size buckets | **yes — the 1/2 boundary moves 2.43 m → ~3.1 m.** This is a mechanism for the open "`__ships` cells hold further out" question |
| The matte pets result holds under a controlled A/B | **yes, completely.** Every metric separates with no overlap; drift 2.702 → 0.812 m median, 3.3× |
| `F.pets__ships` on matte passes its gate | **no.** 0 of 4 flights under 0.5 m (0.524, 0.798, 0.826, 0.932). Much less bad, still failing |
| This settles champion vs confuser | **no.** Not touched, deliberately. See §6 |

The honest one-line version: *the close-range detection weakness does not exist — it
was a clock bug on top of a scene whose flat cardboard people stop looking like people
once the drone works its way round them; and the dog result survives a proper A/B
intact, still failing its gate.*

---

## 1. The discipline

### The code was pinned, and the pin held

sha256 of `camera_model.py`, `follow_person.py`, `build_scene.py`, `scoreboard.py`,
`patch_crazysim.py` recorded before anything ran and re-checked after everything
finished. All five byte-identical (`code_hashes_before.txt`, `code_hashes_after.txt`):

```
66862b05575e270ea73e2dfaf815676ac3e93420cc00c887fc71792d1bf0051d  tools/crazysim_macos/camera_model.py
4a786441f85b431aa61347cd902d797a55d7cb8bb2d77c2fb64ef71abfb68de6  tools/crazysim_macos/follow_person.py
ea639fea1b14abd12426aaaee4941468ff5402412ab1e42bda78adc2fe3bbe64  tools/crazysim_macos/build_scene.py
00a2a950131a3337614b065450b8cb89371b7ab18f256bed24f5769c2917ef33  tools/crazysim_macos/scoreboard.py
20959b177d2706f4f7980c7e760fe162e82a44ba2dd7504ca3b092bc489d0803  tools/crazysim_macos/patch_crazysim.py
```

**These are the same five hashes as `2026-09-13-matte-baseline/code_hashes_after.txt`
and `2026-09-13-stability/data/code_hashes_after.txt`**, so everything here was flown
and rendered by byte-identical tooling to both halves of the 14-cell baseline. The repo
sat at `5477d64` throughout and nothing was committed or pushed.

### Nothing under measurement was modified

`build_scene.py`, `follow_person.py`, `camera_model.py`, `perception_backends.py` and
`scoreboard.py` are the repo's own and were **imported and run, never edited**. Every
scene used here was built into scratch by the repo's own unmodified builder.
`tools/crazysim_macos/scenes_v2/` is untouched and still matte.

> **One piece of state I did leave, and then removed.** The first launch of the flight
> harness was given a *relative* output path; the harness `cd`s into
> `tools/crazysim_macos` to run the follower, so the first flight wrote
> `tools/crazysim_macos/flights.jsonl` and one `tools/crazysim_macos/runs/` directory
> there. I killed that launch, moved both to scratch, fixed the harness to absolutise
> its paths, and re-flew all 8 flights from scratch. `git status` on `tools/` is clean
> and the discarded partial flight is in scratch, not in this directory or the record.
> No published result comes from that launch.

---

# EXPERIMENT 1 — THE RANGE SWEEP

## 2.1 Design

Static: **no flying, no control loop, no simulator, no firmware, no UDP, no Docker.**
A MuJoCo offscreen renderer is pointed at a static, unoccluded, single-person scene
from a ladder of exactly-known stand-off distances, and the perception path is run on
the frames. Range is the only thing that changes between rows at fixed yaw and height.

```
ranges     1.00 .. 4.00 m in 0.25 m steps (13)
yaw        -10, -5, 0, +5, +10 deg camera yaw offset (moves the subject across the
           frame without changing range)
height     0.80 / 0.82 / 0.84 m  — the pz band the matte D.occlusion__proven flights
           actually held (0.798–0.844 m, median 0.802)
subjects   A = COCO 19432/428692 at 1.7 m — the cutout D.occlusion__proven and every
               person_target cell uses.  The PNG the sweep renders is byte-identical
               (cd71a361…) to the repo's scenes_v2/s07 and scenes_v2/s15 copies.
           B = COCO 42102/1728930 at 1.75 m — the second cutout in the v2 scene set,
               so a falloff cannot be blamed on one image.
cameras    clean (REC601 luma of the render — what the __proven cells fly) and
           himax_typical through the repo's camera_model.py (what __ships fly).
           himax is stochastic: 3 draws per viewpoint after a 30-frame AE warm-up.
backends   BOTH.  float (the laptop checkpoint successor_qat_ep3_eval.pth) and chip
           (the firmware's integer preprocessing + model_id_dory.onnx, sha1
           d90555c8…, run under doryenv with eps 2.009823510888964e-4).
```

**3 120 scored frames in 20 s.** The two backends see **byte-identical frames** — each
grayscale frame is generated once and handed to both — so any difference between the
two columns is the network, never the sensor or the geometry.

`sweep.csv`, `sweep_meta.json`, `sweep_analysis.txt`; builder definitions in
`scripts/scene_defs/`; the floor is asserted matte from each scene's manifest before
any frame is rendered.

## 2.2 Result: there is no close-range falloff

**Person A, the subject the failing cell actually flies.** Percentage of frames at or
above the 0.70 latch threshold, by true range:

| range | clean/float | clean/chip | himax/float | himax/chip |
|---|---|---|---|---|
| 1.00 m | 100% | 100% | 100% | 100% |
| 1.25 m | 100% | 100% | 100% | 100% |
| 1.50 m | 100% | 100% | 100% | 100% |
| 1.75 m | 100% | 100% | 100% | 100% |
| 2.00 m | 100% | 100% | 100% | 100% |
| 2.25 m | 100% | 100% | 100% | 100% |
| 2.50 m | 100% | 100% | 100% | 100% |
| 2.75 m | 100% | 100% | 100% | 100% |
| 3.00 m | 100% | 100% | 100% | 100% |
| 3.25 m | 100% | 100% | 100% | 100% |
| 3.50 m | 100% | 100% | 100% | 100% |
| 3.75 m | 100% | **93.3%** | 100% | 100% |
| 4.00 m | 100% | 100% | 100% | 100% |

**Exactly one of the 1 560 person-A frames falls below the latch threshold (0.611, at
3.75 m, clean camera, chip backend) — and it is at the far end, not the near end.** Mean confidence near is *higher* than far on all four arms:

```
near (<= 2.0 m) vs far (2.5-3.0 m), mean confidence
  clean / float    0.992  vs  0.985     +0.007
  clean / chip     0.987  vs  0.968     +0.019
  himax / float    0.996  vs  0.959     +0.037
  himax / chip     0.994  vs  0.943     +0.051
```

Put beside the number this experiment was commissioned to test — person A, clean
camera, float backend, in the baseline's own three bins:

| bin | baseline (published) | this sweep |
|---|---|---|
| 2.5–3.0 m | 0.911 mean, **92.5%** ≥ 0.70 | 0.987 mean, **100%** |
| 2.0–2.5 m | 0.806 mean, **73.6%** | 0.990 mean, **100%** |
| 1.5–2.0 m | 0.686 mean, **54.0%** | 0.998 mean, **100%** |

**Answer to the question as asked: no. There is no genuine close-range detection
falloff. It does not start anywhere, and it has no severity.**

Yaw offset does not produce one either — pooled over all ranges, every yaw from −10°
to +10° holds 97–100% above threshold on all four arms.

## 2.3 Where the size buckets actually change, against range

`scoreboard.py`'s ideal-head geometry `d(s) = H / (2 s tan(φ/2))` puts the boundaries
for a 1.7 m subject at **4.856 m** (bucket 0/1), **2.428 m** (1/2) and **1.619 m** (2/3).
Measured transitions (modal decoded bucket, 15–45 frames per range point):

| arm | 3→2 | 2→1 | frames matching the ideal bucket |
|---|---|---|---|
| clean / float | between 1.50 and 1.75 m | between 2.25 and 2.50 m | **95.4%** |
| clean / chip | between 1.50 and 1.75 m | between 2.00 and 2.25 m | 90.8% |
| himax / float | between 1.75 and 2.00 m | **between 3.00 and 3.25 m** | 72.1% |
| himax / chip | between 2.00 and 2.25 m | **between 3.00 and 3.25 m** | 64.8% |

On the clean camera the head lands where the geometry says it should. **On the himax
camera the 1/2 boundary moves outward by about 0.7 m, from 2.428 m to ~3.1 m.**

That is a mechanism for something the baseline listed as still open. The follower holds
where the decoded size equals the bucket-2 centre; if himax makes bucket 2 extend out to
~3.1 m, a himax cell will park at ~3 m. Observed in the baseline: `__ships` cells hold
**2.90–3.09 m** while `__proven` cells hold **1.91–2.38 m**. The numbers line up. This is
a consistent explanation, not a proof — I did not re-fly anything to test it.

## 2.4 The two backends

Same frames, so this is purely the network:

| subject | camera | n | mean \|Δconf\| | max \|Δconf\| | latch decision differs | size bucket differs |
|---|---|---|---|---|---|---|
| A | clean | 195 | 0.0177 | 0.1729 | **1 (0.5%)** | 13 (6.7%) |
| A | himax_typical | 585 | 0.0165 | 0.1089 | **0 (0.0%)** | 57 (9.7%) |
| B | clean | 195 | 0.1134 | 0.4901 | **42 (21.5%)** | 59 (30.3%) |
| B | himax_typical | 585 | 0.0914 | 0.4253 | **158 (27.0%)** | 51 (8.7%) |

**On the easy subject the chip network is the float network for every decision that
matters.** On the marginal subject they disagree on the latch on a quarter of frames.
The chip path is the one that flies in the `__ships` cells, so this matters: agreement
measured on an easy subject does not transfer to a hard one.

## 2.5 The second subject, which is weak — but not at close range

Person B (COCO 42102) is much weaker overall — mean confidence 0.53–0.73 against
person A's 0.96–0.97 — and it is worth the team knowing that, since `s06_two_people`
and `s10_near_threshold_person` use it. But its shape is **not** a close-range
falloff. Clean/float, % of frames ≥ 0.70:

```
1.00 m 33%   1.75 m  7%   2.50 m 13%   3.25 m 20%   4.00 m 47%
1.25 m 33%   2.00 m  0%   2.75 m  7%   3.50 m 87%
1.50 m  7%   2.25 m 33%   3.00 m  7%   3.75 m 60%
```

A trough in the middle (2.0–3.0 m) with recovery at both ends. Whatever is wrong with
this cutout, it is not range monotonic and it is not what was hypothesised.

## 2.6 Then what does lose the track? Three things, in order of size

### (a) Viewing azimuth — the dominant effect

Every subject in these scenes is a **flat opaque card**; the builder's own manifest
says so ("THIS PANEL IS AN OPAQUE RECTANGULAR CARD"), because MuJoCo 3.13 drops the
alpha channel. Viewed head-on it looks like a person. Viewed 45° off its normal it is
foreshortened to 71% of its width, and the network sees a squashed person.

A third sweep orbits the camera around the subject at **constant range**, aimed at it,
so azimuth moves and range does not (`azimuth/`, `azimuth_analysis.txt`, 1 440 frames,
9.4 s). The model reads `x_value = 0.000` at every azimuth, i.e. the subject is
dead-centre in the crop throughout — this is not a framing effect. Pooled over range:

| azimuth | clean/float | clean/chip | himax/float | himax/chip |
|---|---|---|---|---|
| 0° | 0.989 / 100% | 0.969 / 100% | 0.983 / 100% | 0.969 / 100% |
| 20° | 0.939 / 100% | 0.921 / 94% | 0.921 / 100% | 0.924 / 100% |
| 30° | 0.916 / 100% | 0.859 / 94% | 0.856 / 89% | 0.870 / 94% |
| 35° | 0.907 / 100% | 0.821 / 83% | 0.840 / 100% | 0.830 / 87% |
| **40°** | 0.823 / **94%** | 0.771 / **67%** | 0.731 / **52%** | 0.728 / **65%** |
| **45°** | 0.702 / **50%** | 0.626 / **28%** | 0.582 / **26%** | 0.589 / **11%** |
| 50° | 0.687 / 44% | 0.566 / 22% | 0.461 / 0% | 0.572 / 2% |
| 55° | 0.582 / 28% | 0.397 / 0% | 0.407 / 0% | 0.484 / 0% |

`azimuth_is_what_costs_detections.png` is the picture: the same person at the same
1.50 m, at 0° / 35° / 45°, with the model's own confidence underneath — 0.999, 0.985,
**0.546**.

**`s07_occlusion_reappear` couples azimuth to range by construction.** The target
stands at (3.5, −1.6) and the drone flies along y ≈ 0, so its azimuth off the card
normal is `atan(1.6 / (3.5 − px))`:

```
px = 0.0  ->  24.6 deg        px = 1.5  ->  38.7 deg
px = 1.0  ->  32.6 deg        px = 2.0  ->  46.8 deg
```

Closing the range in that scene *necessarily* swings the camera round the card and
into the collapse band. In the flight logs (`flight_decomposition.txt`, 2 838 flown
frames from the four matte `D.occlusion__proven` flights, cut both ways):

```
                    n     mean conf   >=0.70    mean range
azimuth  0-20    901        0.952      98.3%       2.16 m
azimuth 20-30    773        0.868      91.5%       2.66 m
azimuth 30-40    735        0.811      79.3%       2.27 m
azimuth 40-50    429        0.577      28.7%       2.27 m
```

and the joint cut, which is the decisive one:

```
range \ az        0-20d       20-30d       30-40d       40-50d
1.5-2.0    0.97/ 99%/396  0.92/ 96%/151  0.75/ 62%/90  0.76/ 65%/20
2.0-2.5    0.94/ 97%/350  0.86/ 87%/308  0.82/ 82%/602 0.56/ 27%/403
2.5-3.0    0.95/100%/143  0.89/ 92%/38   0.82/ 84%/43  0.75/ 50%/6
```

Down a column — closer range at fixed azimuth — nothing happens. Across a row — more
azimuth at fixed range — the track dies.

```
lost-track frames (n=371): mean azimuth 41.5 deg, mean range 2.28 m, 79.0% at az >= 40 deg
tracked frames  (n=2467): mean azimuth 23.2 deg, mean range 2.35 m,  5.5% at az >= 40 deg
```

**The two groups have the same mean range and completely different mean azimuth.**

### (b) The partition in frame — real, second-order

The baseline established that on matte, 97–98% of lost-track frames have a *clear
sight line*, and read that as the scene no longer posing its occlusion question. True —
but a clear sight line to the target's centre does not mean the partition is out of the
picture. At px ≈ 2.0 the drone is 0.14–0.24 m short of a 0.1 × 0.9 × 2.2 m box.

`replay/` re-renders all four flights' own geometry twice from each pose — once in the
repo's `scenes_v2/s07_occlusion_reappear`, once in a partition-free twin built by the
same builder from the same definition minus `occluders` (verified: byte-identical
subject PNG, identical body position and sway joint, `scene.xml` diff is the one
missing geom). 2 838 **paired** frames; the pairing removes every source of
pose-replay error.

```
                              with partition    partition deleted     paired delta
all frames (n=2838)           0.837 / 81.3%       0.878 / 89.3%          +0.041
frames the flight LOST (371)  0.627 / 40.7%       0.742 / 62.8%          +0.115
frames the flight held (2467) 0.868 / 87.4%       0.898 / 93.3%          +0.030
```

So the partition costs a real **+0.115 mean confidence and 22 percentage points of
above-threshold frames on exactly the frames that failed the gate** — smaller than the
azimuth effect, but not nothing, and it is largest precisely where it hurts.

Replay fidelity against the flight it replays: the decoded x bin is identical on 68.1%
of frames (mean \|Δx\| 0.071, one bin is 0.222 wide), median \|Δconf\| 0.072, and the
≥ 0.70 decision agrees on 79.8% of frames. The residual is state-estimate error and
the camera's 0.03 m body offset. Attitude was left out of the replay: \|pitch\| never
exceeded 4.32° and \|roll\| 0.43° on these flights, and including them under a ZYX
convention did not improve the match (median \|Δconf\| 0.077 and 0.103 for the two
sign conventions, against 0.072 for yaw only), so yaw-only is what is reported.

### (c) The published range table is computed against a mismatched clock

This one needs stating plainly because it is the number that motivated the experiment.

`2026-09-13-matte-baseline/scripts/conf_vs_range.py` joins the follower's `t` column
against the truth log's `sim_t` column. **These are different clocks.** `t` is seconds
since the *follower* started — its first logged control row is already ~11 s in —
while `sim_t` is seconds since the *simulator* started, and the simulator is launched
and waited on before the follower runs. Measured over the same 2 838 frames
(`conf_vs_range_recheck.txt`):

```
sim_t - follower_t :  min -19.03 s   median -6.84 s   max -0.08 s
```

The offset is not even constant, so it cannot be corrected by a shift. That would not
matter for a static target. This target **sways ±1.6 m with a 24 s period**, so seconds
of skew are metres of position error:

```
target y placed by the t<->sim_t join vs by the wall join: mean error 1.251 m, max 3.122 m
```

Both files carry a wall clock. Re-joined on it, the same flights give:

| bin (true range) | published (t ↔ sim_t join) | corrected (wall-clock join) |
|---|---|---|
| [1.25, 1.75) m | 0.686 mean, **54.0%** ≥ 0.70 | 0.919 mean, **92.9%** |
| [1.75, 2.25) m | 0.806 mean, **73.6%** | 0.880 mean, **86.3%** |
| [2.25, 2.75) m | 0.911 mean, **92.5%** | 0.780 mean, **71.6%** |

**The monotonic close-range decline does not survive the corrected join — it reverses.**

A second, smaller thing in the same script: it keys bins on `round(d * 2) / 2` and
prints the label `k … k+0.5`, so the row printed "1.5-2.0 m" actually holds ranges in
[1.25, 1.75). Every printed bin label in `conf_vs_range.txt` is 0.25 m low. That is
cosmetic next to the clock, but it is in the published table.

None of this touches the baseline's other findings. Its geometry analysis
(`occlusion_geometry.py`) uses truth positions directly and is unaffected; the sight-line
result stands, and so does everything in §§1–4 and 6 of that report. What changes is
§5(c) — "the detector really does lose a plainly visible person" is **not supported**,
and the range binning that supported it should be withdrawn.

## 2.7 The answer

**No falloff. The occlusion scene stopped testing occlusion, and separately it started
testing something it was never meant to test — whether the network can recognise a
cardboard person seen from 45° off-axis.** The 3.24 s relatch is mostly (a) azimuth
past ~40°, with (b) the partition in frame worth a further ~0.115 of confidence on the
failing frames, and the evidence that made it look like range was (c) a clock-join bug.

What that means for the drone the team intends to fly is deliberately limited. A flat
card foreshortens to nothing at 45°; **a real person does not.** So this is a scene-fidelity
limit, not a demonstrated weakness of the network on real people — and it is *not*
evidence that the network is fine on real people at 45° either. See §6.

---

# EXPERIMENT 2 — A CONTROLLED MIRRORED ARM FOR THE DOG

## 3.1 Design

One cell, two floors, four repeats, **eight flights, one session, interleaved**.

```
F.pets__ships | s03_pets_only | F | chip | himax_typical | chip (6.5 Hz / 153 ms) | 35 s
```
copied verbatim from `run_acceptance2.sh`'s CORE matrix.

**Matched pairs.** The same repeat index is flown matte and mirrored back to back,
~51 s apart, so machine drift lands on both arms equally. That is the property the
comparison rests on and it is what makes this an A/B rather than a before/after.

**ABBA counterbalanced.** The leading arm alternates A B B A over the four pairs, so
neither arm is systematically the colder first flight. Realised: both arms at mean
chronological position **4.5 of 8** (matte at 1, 4, 6, 7; mirror at 2, 3, 5, 8).

**Repeat decorrelated from order.** For this cell repeat is not cosmetic — the camera
is `himax_typical`, so `CRAZYSIM_SENSOR_SEED = 1000 + repeat` really does change the
noise draw. Repeats were assigned to pair slots in the order **[3, 1, 4, 2]**, the
assignment whose correlation between repeat index and chronological position is
**exactly 0.000**. Chosen from the plan's own structure before any flight, using no
outcome. `plan.tsv`, `plan_balance.txt`.

**The two floors are one attribute apart, verified.** Both trees were built **outside
the repo** by the same unmodified builder, differing only in the flag:

```
build_scene.py --def scene_defs/s03_pets_only.json --out <scratch>/scenes_matte
build_scene.py --def scene_defs/s03_pets_only.json --out <scratch>/scenes_mirror --floor-reflectance 0.2
```

* `diff` of the two `scene.xml` files is **exactly one line** — `reflectance="0"` vs
  `reflectance="0.2"`. Each file contains exactly one `reflectance` attribute.
* `subj_dog.png` and `subj_cat.png` are **byte-identical** between the two trees *and*
  to the repo's `scenes_v2/s03_pets_only` copies.
* The matte tree's `scene.xml` is **byte-identical to the repo's live `scenes_v2/`**.
* Neither scene has a `motion.json`; the dog's sway is a spring joint baked into
  `scene.xml`, identical in both.
* Because the trees are separate directories, **no scene file was ever swapped under a
  running suite** — the floor is chosen by which path the flight is pointed at.

**Per flight, at flight time**, the harness reads the reflectance out of the
`scene.xml` it is about to fly *and* `room.floor_reflectance` out of that scene's
manifest, aborts if either disagrees with the plan, and writes both into the run
directory. All 8 flights: **0 mismatches**.

`floor_check_matte_r1.png` and `floor_check_mirror_r1.png` are frame 1 of the matched
pair `r1`. Same dog, same cat, same first-frame confidence 0.76 — and a reflection
under both animals in one and not the other.

**Nothing under measurement was modified.** `scripts/fly_plan_ab.sh` reproduces
`run_acceptance2.sh`'s `fly()` body with the same three deliberate changes the
stability run and the matte baseline made (scene root is a parameter, load sampled
around each flight, order from the plan file). `scoreboard.py` was run, never touched,
and scored each arm in its own symlinked suite so the shared cell id cannot average
the arms together.

**8 flights, 18:15:20–18:22:14 CDT, 6 minutes, all VALID on the first attempt.**

## 3.2 Per flight

| ord | arm | rep | M6 drift (m) | M1 track | 1st latch (s) | conf@1st | latched (s) | episodes | d_start | d_end | drift/episode |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | matte | 3 | **0.826** | 0.120 | 0.93 | 0.703 | 2.33 | 4 | 2.63 | 2.10 | 0.146 |
| 2 | mirror | 3 | **2.744** | 0.682 | 0.31 | 0.783 | 16.43 | 1 | 2.63 | 0.32 | 2.541 |
| 3 | mirror | 1 | **2.347** | 0.571 | 0.31 | 0.904 | 13.67 | 1 | 2.63 | 0.71 | 2.072 |
| 4 | matte | 1 | **0.798** | 0.140 | 0.77 | 0.760 | 2.17 | 8 | 2.63 | 2.12 | 0.023 |
| 5 | mirror | 4 | **2.659** | 0.641 | 0.30 | 0.825 | 15.45 | 1 | 2.63 | 0.45 | 2.478 |
| 6 | matte | 4 | **0.524** | 0.080 | 1.09 | 0.754 | 1.55 | 2 | 2.62 | 2.49 | 0.146 |
| 7 | matte | 2 | **0.932** | 0.173 | 1.40 | 0.755 | 3.27 | 6 | 2.63 | 2.04 | 0.087 |
| 8 | mirror | 2 | **2.925** | 0.707 | 0.31 | 0.808 | 17.06 | 1 | 2.63 | 0.18 | 2.599 |

## 3.3 Per arm, and the effect size

| metric | matte (n=4) | mirror (n=4) | median ratio | arms overlap? |
|---|---|---|---|---|
| **M6 drift (m)** | 0.524–0.932 (med 0.812) | 2.347–2.925 (med 2.702) | **3.33×** | **no** |
| **M1 tracking fraction** | 0.080–0.173 (med 0.130) | 0.571–0.707 (med 0.661) | **5.09×** | **no** |
| **time to first latch (s)** | 0.77–1.40 (med 1.01) | 0.30–0.31 (med 0.31) | 0.31× | **no** |
| **total latched (s)** | 1.55–3.27 (med 2.25) | 13.67–17.06 (med 15.94) | **7.08×** | **no** |
| **false-follow episodes** | 2–8 (med 5) | 1–1 (med 1) | 0.20× | **no** |
| conf at first latch | 0.703–0.760 (med 0.754) | 0.783–0.904 (med 0.817) | 1.08× | **no** |
| max drift within an episode (m) | 0.023–0.146 (med 0.116) | 2.072–2.599 (med 2.510) | **21.5×** | **no** |
| range to the dog at the end (m) | 2.04–2.49 (med 2.11) | 0.18–0.71 (med 0.385) | 0.18× | **no** |
| peak confidence on the scene | 0.816–0.925 (med 0.857) | 0.965–0.983 (med 0.978) | 1.14× | **no** |

**Every single metric separates completely — the two arms' ranges do not overlap
anywhere.** With 4 vs 4 the smallest attainable exact two-sided p is 0.0286, and every
one of these achieves it. The normal-approximation Mann–Whitney p is 0.021 throughout
and should be read as "as separated as 4 vs 4 can be", not as a precise p-value.

The behavioural picture is the baseline's, now controlled: on the mirror the drone
latches once within 0.31 s and stays latched for ~16 s, crossing the room to end
**0.18–0.71 m** from the animal. On matte it takes 0.77–1.40 s to latch at all, lets go
almost immediately, flickers 2–8 times, and ends **2.04–2.49 m** away, having moved
0.52–0.93 m.

### Against the M6 gate — the honest part

```
M6_max_horizontal_drift_m < 0.5 m (hard gate)
  matte : 0.524, 0.798, 0.826, 0.932   passes 0 of 4   scoreboard headline 0.932
  mirror: 2.347, 2.659, 2.744, 2.925   passes 0 of 4   scoreboard headline 2.925
```

Both arms **FAIL**, on the same gate. The suite verdict for this cell is FAIL on both
floors (`scoreboards/{matte,mirror}_suite/`).

Note this is **worse than the baseline reported**: the baseline had one of four matte
flights under the gate (0.408 m); this controlled arm has **none**, its best being
0.524 m. Four more repeats is not many, but the two sets together now give eight matte
flights of which **one** passes. The finding is *"much less bad, still failing"*, and
the controlled arm makes the "still failing" part firmer, not softer.

## 3.4 The confidence distribution on the dog

The network emits one visibility output per frame, so a raw `conf` column is
"confidence that a person is in this picture", not "confidence on the dog". Frames were
split by which subject lay inside the model's ±35° crop, using the simulator's own
truth log joined on the **wall clock** (`dog_confidence.txt`).

**Whole scene, all flown frames:**

| arm | frames | mean | median | p90 | max | ≥0.70 | ≥0.45 | size buckets seen |
|---|---|---|---|---|---|---|---|---|
| matte | 621 | 0.527 | 0.512 | 0.755 | 0.925 | **18.2%** | 61.5% | b0 ×334, b1 ×287 |
| mirror | 626 | 0.668 | 0.670 | 0.909 | 0.983 | **45.7%** | 85.0% | b0 ×169, b1 ×444, **b2 ×13** |

**The dog alone in the crop:**

| arm | frames | mean | median | p90 | max | ≥0.70 | mean range to dog |
|---|---|---|---|---|---|---|---|
| matte | 391 | 0.473 | 0.438 | 0.701 | 0.854 | **10.2%** | 2.18 m |
| mirror | 531 | 0.660 | 0.658 | 0.920 | 0.983 | **43.9%** | 1.00 m |

**Range-matched**, because the mirrored drone closes on the dog and part of its higher
confidence is simply being nearer. Restricted to the 1.5–3.0 m band both arms visit:

```
matte  n=391  mean 0.473  (10.2% >= 0.70)
mirror n=126  mean 0.824  (78.6% >= 0.70)
```

**At the same range the mirrored dog reads 0.35 higher.** So the effect is the mirror,
not the geometry it produces.

The size head is the mechanism, exactly as the baseline said. A 0.65 m dog should read
bucket 0 beyond 1.86 m on the ideal head. While the dog alone was in the crop:

```
matte   bucket 0: 59.6%   bucket 1: 40.4%
mirror  bucket 0: 28.1%   bucket 1: 69.5%   bucket 2: 2.4%
```

On the mirror the dog reads as a bucket-1-or-2 object — person-height — most of the
time. On matte it reads bucket 0 most of the time and **never reaches bucket 2**.

## 3.5 Does the matte result hold?

**Yes.** Every number the baseline reported for this cell reproduces, and the mirrored
side it was compared against turns out to have been sound too:

| | baseline matte (Sep 12) | **this matte arm** | baseline mirror (Sep 11, n=2) | **this mirror arm** |
|---|---|---|---|---|
| M6 drift (m) | 0.408–0.927 | **0.524–0.932** | 2.301, 2.666 | **2.347–2.925** |
| M1 tracking | 0.079–0.193 | **0.080–0.173** | 0.684, 0.785 | **0.571–0.707** |
| first latch (s) | 0.63–1.41 | **0.77–1.40** | 0.31, 0.31 | **0.30–0.31** |
| total latched (s) | 1.25–3.59 | **1.55–3.27** | 14.44, 15.86 | **13.67–17.06** |
| episodes | 4–6 | **2–8** | 1, 1 | **1, 1, 1, 1** |
| range to dog at end (m) | 2.03–2.49 | **2.04–2.49** | 0.44, 0.80 | **0.18–0.71** |

So the baseline's before/after comparison was not distorted by the day, the machine or
the two-repeat mirrored sample. **The controlled A/B reaches the same conclusion with
the same magnitudes.** That is worth knowing on its own: it means the uncontrolled
mirror↔matte comparisons for the other six cells in that report (3, 4, 5, 9, 10, 11)
are more trustworthy than their caveat allowed — though this tests only one of them.

**This does not choose between champion and confuser, and nothing here should be read
as advocating either.** That is a pending team decision. What this run does is give the
closed-loop pet false-alarm numbers a controlled arm so the decision is not resting on
a before/after. Whether 0.52–0.93 m of drift and 2–8 brief latches is acceptable, and
whether the confuser's lower per-frame rate is worth its cost, is not decided by this
data and I am not deciding it.

---

## 4. The machine, honestly

### Experiment 1 needed no simulator

The sweeps and the replay start no simulator process — offscreen rendering only, the
property `dump_camera_samples.py` already relies on. The workstream lock was held
anyway, for the whole session.

```
range sweep    3120 rows in  20.0 s   load1 8.05 before -> 9.50 after
azimuth sweep  1440 rows in   9.4 s   load1 7.24 before
replay         5676 rows (2838 pairs), 4 flights x 2 scene variants
```

### Experiment 2, per flight

| ord | arm | load1 pre | load1 post | sim/wall | Hz | gap_max ms | \|pitch\|max | \|roll\|max | z_min | upset |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | matte | 5.50 | 9.40 | 0.985 | 6.44 | 158.9 | 5.38 | 0.33 | 0.800 | 0 |
| 2 | mirror | 9.40 | 8.62 | 0.980 | 6.45 | 158.8 | 4.22 | 0.44 | 0.801 | 0 |
| 3 | mirror | 8.62 | 8.18 | 0.984 | 6.43 | 161.0 | 4.36 | 0.41 | 0.801 | 0 |
| 4 | matte | 8.18 | 7.80 | 0.981 | 6.44 | 158.9 | 4.92 | 0.20 | 0.801 | 0 |
| 5 | mirror | 7.80 | 6.71 | 0.995 | 6.41 | **178.9** | 4.30 | 0.42 | 0.800 | 0 |
| 6 | matte | 6.50 | 8.79 | 0.973 | 6.43 | 158.8 | **12.34** | 0.58 | 0.795 | 0 |
| 7 | matte | 8.79 | 8.74 | 0.984 | 6.42 | 158.6 | 4.46 | 0.50 | 0.800 | 0 |
| 8 | mirror | 8.74 | 5.63 | 0.983 | 6.44 | 158.6 | 4.84 | 0.68 | 0.801 | 0 |

Upsets use the stability run's definition verbatim (over flown rows, `event == ""`:
`|pitch| > 30°` or `|roll| > 30°` or `z_min < 0.5`).

```
attitude upsets   0 / 8       worst |pitch| 12.34 deg   worst |roll| 0.68 deg
z_min             0.795 .. 0.801 m on every flight
sim_wall_ratio    min 0.973   median 0.984   max 0.995     flights below 0.95: 0 of 8
load1 before      matte 5.50-8.79 (mean 7.24)   mirror 7.80-9.40 (mean 8.64)
```

**Zero upsets, a 2.4× margin to the 30° envelope. This adds 4 more matte flights to the
running count: 0 upsets in 60 matte flights across three runs.**

Two things I am not going to smooth over:

* **Flight 6 (matte) reached 12.34° worst pitch**, against 4.2–5.4° on the other seven.
  That is 2× the rest of this suite and 2× the matte baseline's worst (6.00°). It is
  still 2.4× inside the 30° gate, z never left 0.795 m, and the flight scored VALID with
  the *smallest* drift of its arm (0.524 m) — but it is an outlier within this suite and
  it is one flight, so I am not calling it anything.
* **Flight 5 (mirror) reached a 178.9 ms max step gap**, against 158.6–161.0 ms on the
  other seven. It is below the stability run's 183.9 ms worst over 56 flights and well
  below the 232.9 ms median of the Sep 12 upset flights, and that flight had the *best*
  `sim_wall_ratio` of the eight (0.995) and no upset. Recorded, not flagged.

### `step_gap_ms.max` must be read per speed class

**All eight flights here are chip speed.** The 153 ms chip rate cap puts their gap floor
at ~154 ms by construction, so these numbers must not be compared against the stability
run's 158 ms full-speed lead — that would be comparing a rate cap to a stall.

```
chip speed (153 ms cap)  n=8  min 158.6  median 158.9  max 178.9 ms
  matte  158.6 - 158.9 ms
  mirror 158.6 - 178.9 ms
```

There is no full-speed class in this suite to report.

---

## 5. Reproducing

Run with `/Users/saimaruvada/Downloads/drone/trainenv/bin/python` (there is no bare
`python` on PATH). The chip backend additionally needs
`/Users/saimaruvada/Downloads/drone/doryenv/bin/python3`, which the scripts start
themselves.

| script | what it does | runtime |
|---|---|---|
| `scripts/range_sweep.py --scene-root R --out D` | the static range sweep, both backends, both cameras | 20 s |
| `scripts/analyze_sweep.py D` | per-range tables, bucket transitions, backend disagreement | instant |
| `scripts/azimuth_sweep.py --scene-root R --out D` | confidence vs viewing azimuth at fixed range | 9 s |
| `scripts/replay_occlusion.py RUNS… --scene-with A --scene-without B --out D` | paired re-render of the flown geometry, partition present/absent | ~2 min |
| `scripts/analyze_replay.py D` | the paired partition comparison | instant |
| `scripts/decompose_flight.py RUNS…` | the flown frames cut by range **and** azimuth | instant |
| `scripts/recheck_conf_vs_range.py RUNS…` | the clock-join check and the corrected table | instant |
| `scripts/make_azimuth_figure.py SCENE OUT.png --range R` | the three-tile azimuth figure | instant |
| `scripts/make_plan_ab.py OUT.tsv` | the ABBA plan and its balance checks | instant |
| `scripts/fly_plan_ab.sh PLAN OUT MATTE_ROOT MIRROR_ROOT [START]` | the 8 flights, floor asserted per flight | 6 min |
| `scripts/split_and_score_ab.sh OUT` | one symlinked suite per arm, scored by the unmodified `scoreboard.py` | ~20 s |
| `scripts/analyze_ab.py OUT` | per-flight, per-arm, effect size, machine table | instant |
| `scripts/conf_on_dog.py OUT` | confidence attributed to what was in the crop | instant |

Building the scenes (all into scratch; the repo's `scenes_v2/` is never written):

```bash
cd /Users/saimaruvada/Downloads/drone/pytorch_ssd/tools/crazysim_macos
P=/Users/saimaruvada/Downloads/drone/trainenv/bin/python
D=<this dir>/scripts/scene_defs
$P build_scene.py --def $D/w01_sweep_person_a.json $D/w02_sweep_person_b.json \
                  $D/w03_s07_no_partition.json --out $S/scenes_sweep --no-model
$P build_scene.py --def scene_defs/s03_pets_only.json --out $S/scenes_matte  --no-model
$P build_scene.py --def scene_defs/s03_pets_only.json --out $S/scenes_mirror --no-model \
                  --floor-reflectance 0.2
```

The one-attribute check:

```bash
diff $S/scenes_matte/s03_pets_only/scene.xml $S/scenes_mirror/s03_pets_only/scene.xml
diff $S/scenes_matte/s03_pets_only/scene.xml scenes_v2/s03_pets_only/scene.xml   # empty
```

### What is in here

* `plan.tsv`, `plan_balance.txt` — the A/B flight plan and its realised balance checks
* `flights.jsonl`, `progress.log` — one record per flight: order, condition, verdict,
  timestamps, load before and after, `sim_wall_ratio`, `processed_hz`, `step_gap_ms`,
  and the floor reflectance the harness read
* `runs/` — 8 run directories: `cell.json`, `check.txt`, `follow_log.csv`,
  `metrics.json`, `summary.json`, `truth.csv`, `camera_model.json`,
  `floor_reflectance.txt` and `floor_manifest.txt`
* `scoreboards/{matte,mirror}_suite/` — one scoreboard per arm, run dirs symlinked
* `sweep/` — `sweep.csv` (3 120 rows), `sweep_meta.json`, 8 sample frames
* `azimuth/` — `azimuth.csv` (1 440 rows), `azimuth_meta.json`
* `replay/` — `replay.csv` (5 676 rows = 2 838 paired frames), `replay_meta.json`
* `sweep_analysis.txt`, `azimuth_analysis.txt`, `replay_analysis.txt`,
  `flight_decomposition.txt`, `conf_vs_range_recheck.txt`, `ab_analysis.txt`,
  `dog_confidence.txt` — printed output of the analysis scripts
* `code_hashes_before.txt`, `code_hashes_after.txt` — the pin, and the proof it held
* `scripts/scene_defs/` — the three scene definitions this run added (all built into
  scratch; none added to the repo's `scene_defs/`)
* three PNGs — the azimuth figure, and the matched matte/mirrored floor-check pair

**State left behind: none.** `tools/crazysim_macos/` is clean and `scenes_v2/` is
untouched and still matte. No tool, scene or committed result was modified. The
follower's per-flight camera snapshots and the chip cache directories were moved to
scratch rather than published, as the matte baseline did. Nothing was committed or
pushed — `CLAUDE.md`'s session-end commit rule was overridden by this workstream's
explicit instruction not to; the directory is untracked and ready for whoever does
commit it.

---

## 6. What this establishes, and what it does not

**Established:**

* **There is no close-range detection falloff on a person.** 1.0–4.0 m, two subjects,
  two cameras, two backends, five yaw offsets, three camera heights, 3 120 scored
  frames. On the acceptance suite's own cutout, **100% of frames clear the 0.70 latch
  threshold at every range on every arm** except one frame at 3.75 m. Mean confidence
  near is higher than far.
* **The baseline's close-range evidence is a clock-join artefact.** Its
  `conf_vs_range.py` joins the follower's clock to the simulator's clock; the offset
  runs to −19 s and drifts, and the target sways ±1.6 m with a 24 s period, so the
  target is misplaced by 1.25 m on average. Corrected, the trend reverses.
* **The real driver is viewing azimuth off the flat subject card.** Confidence is flat
  to ~35° and collapses past ~40°. 79.0% of `D.occlusion__proven`'s lost-track frames
  are at azimuth ≥ 40°, against 5.5% of tracked frames, at the same mean range.
* **The partition in frame is a real second-order effect**: paired on the same pose,
  deleting it is worth **+0.115 mean confidence and +22 pp above-threshold on the
  frames the flight actually lost**.
* **Size bucket transitions sit where the ideal head says on the clean camera** (95.4%
  agreement, 2/3 boundary 1.50–1.75 m vs ideal 1.619, 1/2 boundary 2.25–2.50 m vs ideal
  2.428) and **move outward by ~0.7 m on the himax camera** (1/2 boundary at ~3.1 m).
* **Float and chip agree on every latch decision for an easy subject** (0.0–0.5%
  disagreement) **and diverge sharply on a marginal one** (21.5–27.0%).
* **The matte pets result holds under a controlled, interleaved, ABBA A/B.** All nine
  reported metrics separate completely with no overlap between arms; drift 2.702 →
  0.812 m median, 3.33×; time latched 15.94 → 2.25 s, 7.08×.
* **`F.pets__ships` still fails M6 on the matte floor — on 4 of 4 controlled flights.**
* **Flight stability is fine.** 0 upsets in 8 more flights; 0 in 60 matte flights across
  three runs.

**NOT established — what I did not prove:**

* **Anything about real hardware.** No real camera, no real Crazyflie, no lab. Every
  frame here is rendered. The lab session is still the first test of any of it.
* **That a real person is detected at 45° azimuth.** The collapse I measured is on a
  flat card, which foreshortens to nothing; a real person does not. It is a scene
  fidelity limit. But it is equally **not** evidence that the network handles real
  people at 45°, and the training set's view-angle coverage is not something I looked
  at. **Undetermined, and it needs real frames.**
* **Why the himax camera moves the size buckets outward.** I measured that it does and
  that the magnitude matches the `__ships` cells' hold distance. I did not find the
  mechanism, and I did not re-fly anything to confirm the link.
* **Whether person B's mid-range trough is real or an artefact of that one cutout.**
  Two subjects is two subjects. `s06_two_people` and `s10_near_threshold_person` use
  that cutout and may be reading a weak subject as a model property.
* **Whether the azimuth threshold is ~40° for any other subject.** I swept azimuth on
  person A only.
* **That 4 repeats bound the pets behaviour.** Matte drift spans 0.524–0.932 m across
  four flights. The two matte sets together give 8 flights of which 1 passes the gate,
  which is better than 4 but still not a tight interval.
* **Whether `F.pets__ships`'s remaining drift is commanded travel or momentum.** The
  baseline flagged this and I did not split it either; within-episode drift is
  0.023–0.146 m here, so most of the 0.52–0.93 m is still accumulated across episodes.
* **Anything about the champion-vs-confuser choice.** Deliberately untouched. This run
  gives that decision a controlled arm; it does not make the decision, and no
  recommendation either way should be read into it.
* **Whether `D.occlusion__proven` would pass a fixed scene.** I did not re-fly it. The
  replay says the partition costs 0.115 of confidence on the failing frames; it does
  not say what the M9 relatch time would be with a partition that actually occludes.

---

## 7. Recommendations (not implemented — nothing under measurement was edited)

1. **Withdraw `conf_vs_range.txt` and §5(c) of the matte baseline.** The table is
   computed against a mismatched clock and the close-range claim it supports does not
   survive correction. `recheck_conf_vs_range.py` reproduces the published numbers and
   the corrected ones side by side. Everything else in that report stands, including its
   sight-line geometry, which uses truth positions directly.
2. **Audit every other analysis that joins `follow_log.t` to `truth.csv`'s `sim_t`.**
   The two logs also carry a shared wall clock, which is the correct key. This one bug
   produced a finding that looked like a hardware-relevant model weakness.
3. **Fix `s07_occlusion_reappear`'s geometry, and fix it for azimuth as well as for
   occlusion.** Moving the target to y ≈ 0 and putting the partition on the approach
   axis would let the cell test occlusion without also testing 47° card foreshortening.
   Owner: `scene_defs/s07_occlusion_reappear.json`; not edited here.
4. **Treat the flat-card subject as a known scene limit and write it into the scene
   contract.** Any cell where the drone's path swings more than ~35° off a subject's
   card normal is measuring the card, not the model. Several scenes place subjects well
   off the approach axis (`s15` at y=−1.0, `s13` at y=+0.4, `s05` at y=+0.9).
5. **Check the himax size-bucket shift against the `__ships` hold-distance residual.**
   The 1/2 boundary moving 2.43 → ~3.1 m predicts the 2.90–3.09 m hold. If that is the
   mechanism it is a calibration issue, not a camera-realism issue.
6. **Re-measure float↔chip agreement on marginal subjects before shipping.** 0%
   disagreement on an easy person and 27% on a hard one is the kind of gap that makes
   an offline agreement number misleading.
