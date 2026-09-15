# Partial people: answering MinHyuk on field of view, and interrogating the stratum we skipped

**Nothing here flew, nothing here was rendered, and nothing here touched hardware
or the simulator.** No sim lock was taken. Section 1 is arithmetic on constants
read out of `tools/crazysim_macos/`. Sections 2-5 re-cut confidences that already
exist in `docs/eval_results/2026-09-15-sim-person-fidelity/tables/`, using COCO's
own annotations to split a stratum. **No image was re-scored**, so the two sides
of every comparison below are rows of the same table and travel through the same
resampling chain by construction.

**Provenance, stated exactly.** This directory committed and pushed nothing, and
modified nothing outside itself: `git status` on `tools/`, `docs/sim_results/`
and every existing `docs/eval_results/` directory is clean. HEAD *did* move while
this ran - from `ac698b2` to `d57120c`, four commits landed by a concurrent
session on unrelated YOLO and M10 work - so the honest statement is not "the repo
sat still" but that **`git diff ac698b2..d57120c` touches nothing this directory
reads**: not `tools/`, not `2026-09-15-sim-person-fidelity/`, not
`2026-09-15-sim-pet-fidelity/`, not `2026-09-14-baseline-075/`, not
`2026-09-15-typical-person/`. Every input was byte-identical from first read to
last.

---

## The objection

MinHyuk Park, who runs the drone fleet and has flown this hardware:

> "For real camera Field Of View would be a challenge. You would almost never
> have entire person in the frame."

He is responding to `docs/eval_results/2026-09-15-sim-person-fidelity/`, which
built its conclusions on a `whole_upright` stratum of 204 COCO people and said,
in its own list of limitations, that the `occluded_or_truncated` stratum of
2 488 is *"reported but not interrogated"*. If he is right that a real drone
almost never sees a whole person, then we interrogated the exception and skipped
the operating condition. This directory interrogates it.

---

## 0. TL;DR

| claim | verdict |
|---|---|
| **THE GEOMETRY** | **His concern does not apply to our rig at the ranges it flies, and the margin is not small.** The model sees a 70 deg **square** crop from a **level** camera at 0.8 m. A 1.7 m person's head leaves that crop below **d = (1.7 - 0.8)/tan(35 deg) = 1.285 m**; the feet leave it below 1.143 m. Every flown person cell settles between **1.55 and 2.44 m** (7 cells, means 1.63-2.44), the follower's target is 1.94 m, and the size-bucket decoder stops a closing drone at **2.43 m**. The whole body is inside the crop on **100%** of that band, with **0.26 m** of clearance below the closest repeat ever observed |
| **where it DOES start to apply** | Below **1.285 m** the head goes first, and the body fraction in frame falls roughly as 1/d: **96.5%** at 1.2 m, **82.4%** at 1.0 m, **61.8%** at 0.75 m, **41.2%** at 0.5 m. Nothing in the flown evidence gets there; the follower would have to overshoot its own closest station-keeping distance by 21% |
| **the FOV axis that does bite** | **Bearing, not truncation.** The same 35 deg half-angle applies horizontally, and a subject past it is outside the crop entirely (`scoreboard.MODEL_HALF_FOV_DEG`). `2026-09-15-typical-person`'s own build-time probe scores the control cutout **0.319 at 1.80 m / -33.7 deg** and labels it "outside the crop" - at a range where the whole body still fits vertically. If MinHyuk's concern is going to cost us a track, this is the mechanism, not a cut-off head |
| **THE DETECTION QUESTION, two-way** | The earlier read is **confirmed**. Flown band, resolution-matched (`*_via244`), fraction **below the 0.45 exit bar**: `occluded_or_truncated` **0.124 / 0.148 / 0.158** (chip / float / fq) against `whole_upright` **0.074 / 0.088 / 0.081**. Above the 0.75 bar: **0.697 / 0.674 / 0.659** against **0.765 / 0.787 / 0.787** |
| **BUT THE TWO-WAY SPLIT IS MISLEADING** | **The penalty is entirely TRUNCATION. Occlusion costs nothing measurable.** Size-standardised onto `whole_upright`'s own size mix, chip, `via244`, difference from `whole_upright`: `occl_only` (n=267) **+0.025 [-0.057, +0.113]** above the bar and **+0.002 [-0.052, +0.054]** below the exit bar - **both cross zero, and the point estimate is the wrong sign for a penalty**. `trunc_only` (n=356) **-0.149 [-0.244, -0.060]** and **+0.098 [+0.040, +0.154]**. Pooling them into one "partial" stratum averages a real effect with a null one |
| **THE DRONE-SHAPED SUB-STRATUM** | A drone at close range cuts the **head**, so the closest analogue COCO offers is a person cut by the **top** image edge with no occlusion flag (n=44 in the flown band). Chip, `via244`, size-standardised: **0.454 [0.316, 0.588]** above the bar, **-0.311 [-0.463, -0.160]** against `whole_upright`; **0.182** below the exit bar, **+0.109 [+0.003, +0.227]**. It is the worst sub-stratum here - and it is the one our geometry says the drone does not produce |
| **ANSWER TO THE TEAM'S QUESTION** | **Yes, but less than "partial people" makes it sound, and not for the reason in the objection.** If the drone saw the full COCO partial mix at matched apparent size, the per-frame let-go rate on the chip arm would go from **0.074 to 0.123** (size-standardised, +0.050 [+0.002, +0.097]) - about **1.7x**. If it saw only truncated people, **0.074 to 0.172**, about **2.3x**. If it saw only occluded people, **no change**. Against that, the finding the fidelity study already published - that the simulator shows **0.000** where a whole real person shows **0.074-0.113** - is the larger number, and it is unchanged |
| **What this cannot tell you** | **A photographer's crop is not a drone's crop, and COCO contains no image taken from a drone at 2 m.** COCO's truncated people are truncated because a photographer framed them that way: they are systematically **larger** (median 100.8 px128_h against 68.8 for whole people), closer to the lens, and in busier scenes. The `top_cut` cell is n=44 and confounded on all of those. Nothing here flew, so no per-frame rate becomes a loss-of-track fraction |

The honest one-line version: *MinHyuk is right about drones in general and wrong
about this drone at these ranges - a 1.7 m person is wholly inside the 70 deg
crop everywhere the follower holds station, with 0.26 m to spare - and when we
interrogate the partial-people stratum anyway, the detection penalty turns out to
be truncation only, worth about +0.05 of let-go rate pooled and +0.10 truncated,
while occlusion costs nothing measurable at matched size.*

---

## 1. GEOMETRY, because the claim is checkable

Every constant is read out of the repo, not asserted
(`scripts/geometry_fov.py` imports `tools/crazysim_macos/scoreboard.py`):

| constant | value | where |
|---|---|---|
| `CROP_FOV_DEG` | 70.0, **square** | `scoreboard.py` (centre crop of a 244-tall render, fovy=70) |
| `TAN_HALF_FOV` | 0.70021 | the same, tan(35 deg) |
| camera height | 0.8 m, optical axis **level** | `follow_person.py --height` default; the follower yaws, it does not pitch |
| person height | 1.7 m | every person `scene_def`, unchanged across all three cutouts |
| `HOLD_K`, `BAND_K` | target 1.942 m, band 1.619-2.428 m | `scoreboard.py`, from `TARGET_SIZE` 0.625 and `SIZE_EDGES` |

Because the crop is square, the vertical half-angle equals the horizontal one:
35 deg either way. At horizontal range *d* the crop spans `0.8 +- 0.70021 d`
vertically at the person's plane, so

* the **head** stays in frame while `1.7 <= 0.8 + 0.70021 d`, i.e. **d >= 1.285 m**
* the **feet** stay in frame while `0 >= 0.8 - 0.70021 d`, i.e. **d >= 1.143 m**

**The head goes first, and it goes at 1.285 m.** Visible fraction of the body
against range (`tables/geometry_fov.tsv`):

| range | 0.50 m | 0.75 m | 1.00 m | 1.20 m | **1.285 m** | 1.55 m | 1.94 m | 2.43 m | 3.64 m |
|---|---|---|---|---|---|---|---|---|---|
| fraction in frame | 0.412 | 0.618 | 0.824 | 0.965 | **1.000** | 1.000 | 1.000 | 1.000 | 1.000 |
| what is cut | head+feet | head+feet | head+feet | head | - | - | - | - | - |
| `px128_h` of the visible part | 128 | 128 | 128 | 128 | 120.9 | 100.2 | 80.1 | 63.9 | 42.7 |

### Against where the follower actually is

`docs/eval_results/2026-09-14-baseline-075/scoreboard.md` reports per-cell mean
station-keeping distances for the seven person cells of **1.63 / 1.74 / 1.87 /
2.00 / 2.19 / 2.20 / 2.44 m**, with a repeat spread of **1.55-2.44 m** against a
1.94 m target. The flown scenes start at **3.64 m** (s15 static) and
**3.11 m** (s01 moving). And the control law cannot ask for closer than
**2.428 m** on its own: the follower decodes size into four buckets and holds
bucket 2, whose far edge `1/(2 x 0.5 x tan35) x 1.7` is 2.428 m, so a drone
closing from outside stops there. The 1.55-1.63 m settles are undershoot inside
the band, not the controller aiming closer.

**So: the whole person is in the crop on 100% of every range the flown evidence
contains, and the nearest observed repeat, 1.55 m, sits 0.26 m outside the
1.285 m limit.** The follower would have to overshoot its own closest observed
station by 21% before the head left the frame.

### Where MinHyuk's concern is right anyway

Two places, and the second is the one I would actually worry about.

1. **Below 1.285 m.** Any scenario that puts the drone closer - a person walking
   into it, an indoor corridor, a smaller flight height, a *taller* person (at
   2.0 m the limit moves out to 1.714 m, which is inside the hold band) - starts
   cutting the head immediately. The limit is `(H - 0.8)/0.70021`, so it scales
   with the subject, and a 1.9 m person is cut below 1.571 m, i.e. **inside** the
   flown repeat spread. The 1.7 m in the scene definition is doing work here.
2. **Bearing, which is the same 35 deg.** A subject more than 35 deg off
   boresight is outside the crop entirely
   (`scoreboard.MODEL_HALF_FOV_DEG`), and that has already been observed:
   `2026-09-15-typical-person`'s build-time probe scores the control cutout
   **0.319** at **1.80 m / -33.7 deg** and annotates it "outside the crop". At
   1.94 m the crop is only 2.72 m wide at the person's plane. A person who
   sidesteps faster than the yaw loop tracks leaves the frame sideways long
   before they leave it vertically.

**Verdict on section 1: the specific mechanism MinHyuk named - not having the
entire person in frame - does not apply to this rig at these ranges. It applies
below 1.285 m, and it scales with subject height.** That said, the rest of this
document takes his premise seriously and asks what would happen if it were true,
because it is true of drones generally and because the stratum was unexamined.

---

## 2. What COCO lets us separate, and what it does not

The fidelity study's `occluded_or_truncated` is everything that is not
`whole_upright` - a bucket holding at least four different failures. COCO's
keypoint flags separate two of them and are ambiguous about a third:

* `v == 2` labelled and visible
* `v == 1` **labelled but not visible** - COCO's own occlusion annotation
* `v == 0` not labelled at all - **ambiguous**: out of frame, or simply not
  annotatable. This is why occlusion here is read from `v == 1` only, which is
  conservative: a person whose occluded joints were left unlabelled does not
  count as occluded.

Truncation is therefore read **geometrically**, not from `v`:

| flag | definition | why |
|---|---|---|
| `edge_trunc` | the box touches the image border (2 px) | the photographer's frame cut them |
| `crop_trunc` | the box is not wholly inside the **centre square crop** | the same operation the firmware performs - the closest thing COCO has to a drone crop |
| `cut_top` | the box touches the **top** border | a drone at close range cuts the **head**, so this is the drone-shaped sub-cut |
| `crop_vis_frac` | fraction of the box **area** surviving the centre crop | the graded version of `crop_trunc` |

Census of all 2 693 (`logs/strata.log`; `occluded_or_truncated` is 2 489 here,
2 488 after dropping the simulator's own source photograph, matching the
fidelity study):

| class | n | % |
|---|---|---|
| `whole_upright` | 204 | 7.6% |
| `trunc_only` (truncated, no occlusion flag) | 814 | 30.2% |
| `occl_only` (occlusion flag, not truncated) | 420 | 15.6% |
| `trunc_and_occl` | 543 | 20.2% |
| `no_keypoints` (COCO annotated none - mostly tiny people, median 11.4 px) | 370 | 13.7% |
| `clean_other` (neither flag; failed only the upright/aspect test) | 342 | 12.7% |

Within `occluded_or_truncated`: 1 509 truncated in some way (801 by the image
edge, 1 354 by the centre crop, of which 225 cut at the **top**, 270 at the
bottom, 518 at a side), 963 occlusion-flagged, 370 with no keypoints at all.

**MinHyuk's premise, checked against COCO itself:** 56% of COCO's people are
truncated by the image edge or by the centre crop, and only 7.6% are whole,
upright, unoccluded and untruncated. His intuition about photographs in general
is well supported - it just does not describe what our 70 deg crop sees at
1.55-2.44 m.

---

## 3. Matched apparent size, and why a band cut is not enough

`px128_h` is the subject's height in the 128x128 tensor - the one unit that means
the same thing on both sides. The flown band is **38.8-103.6 px** (4.0 m to
1.5 m for a 1.7 m person) and the hold band **63.4-100.2 px** (2.45-1.55 m).

Cutting to a band is not sufficient, because the strata have different size
distributions inside it (`tables/size_profile.tsv`):

| stratum | n | n in flown band | median `px128_h` | median `crop_vis_frac` |
|---|---|---|---|---|
| `whole_upright` | 204 | 136 | 68.8 | 1.000 |
| `occl_or_trunc` | 2488 | 1125 | 71.6 | 0.948 |
| `trunc_only` | 813 | 356 | **100.8** | 0.772 |
| `occl_only` | 420 | 267 | **54.8** | 1.000 |
| `trunc_and_occl` | 543 | 268 | 90.6 | 0.802 |
| `top_cut` | 137 | 44 | **122.8** | 0.751 |

Truncated people are systematically **larger** - a photographer crops in close -
and occluded-only people are systematically **smaller**. A band cut alone would
flatter truncation and penalise occlusion. So every headline number in section 5
is **size-standardised**: each stratum's per-bin rates are re-weighted onto one
reference mix, `whole_upright`'s own distribution inside the flown band
(bins 25-40 / 40-55 / 55-80 / 80-129 px, weights 4 / 31 / 45 / 56). Bins with
fewer than 3 photographs in a stratum are dropped and the remaining weights
renormalised.

**On the two rules this project learned the hard way.** Both sides of every
comparison here are rows of the *same* CSV, so (i) nothing compares 0.75 on one
stratum against 0.45 on another - both bars are reported for every stratum, one
at a time; and (ii) nothing travels through a different resampling chain. The
`*_via244` columns are the fidelity study's already-validated resolution-matched
control, and the himax columns already resize to 244 before the sensor model.
Raw `chip` on a 640-px photograph appears nowhere in this document.

---

## 4. THE TWO-WAY SPLIT: is `occluded_or_truncated` harder than `whole_upright`?

**Yes, and the earlier read is confirmed.** Flown band, band-cut only,
resolution-matched `*_via244` on both sides (`tables/flown_band.tsv`):

| stratum | n | arm | median | >= 0.75 | 95% CI | < 0.45 | 95% CI |
|---|---|---|---|---|---|---|---|
| `whole_upright` | 136 | chip | 0.965 | 0.765 | [0.691, 0.831] | **0.074** | [0.037, 0.118] |
| `whole_upright` | 136 | float | 0.974 | 0.787 | [0.713, 0.860] | **0.088** | [0.044, 0.140] |
| `whole_upright` | 136 | fq | 0.967 | 0.787 | [0.721, 0.853] | **0.081** | [0.037, 0.125] |
| `occluded_or_truncated` | 1125 | chip | 0.907 | 0.697 | [0.671, 0.724] | **0.124** | [0.106, 0.144] |
| `occluded_or_truncated` | 1125 | float | 0.906 | 0.674 | [0.645, 0.701] | **0.148** | [0.128, 0.170] |
| `occluded_or_truncated` | 1125 | fq | 0.900 | 0.659 | [0.628, 0.687] | **0.158** | [0.138, 0.180] |

The prior guess - "roughly 12-16% against 7-8%" - is right: **12.4-15.8% against
7.4-8.8%**, and the intervals do not overlap on any arm. Size-standardised onto
`whole_upright`'s own size mix (`tables/size_standardised.tsv`), the difference
from `whole_upright` is **+0.050 [+0.002, +0.097]** (chip), +0.058 [+0.006,
+0.107] (float), +0.076 [+0.025, +0.126] (fq) below the exit bar, and
**-0.069 [-0.143, +0.008]** (chip, crosses zero), -0.113 [-0.188, -0.036]
(float), -0.129 [-0.205, -0.053] (fq) above the confirmation bar.

Under the himax sensor model on both sides, every difference is larger and the
chip above-bar interval no longer crosses zero: **-0.173 [-0.246, -0.091]** above
the bar, **+0.072 [+0.014, +0.125]** below the exit bar.

---

## 5. GOING FURTHER: "partial" is not one thing

Size-standardised onto `whole_upright`'s size mix, flown band, **chip** arm,
difference from `whole_upright` (`tables/size_standardised.tsv` carries all three
arms and both chains):

| sub-stratum | n | chain | >= 0.75 | d vs whole | < 0.45 | d vs whole |
|---|---|---|---|---|---|---|
| `whole_upright` (reference) | 136 | via244 | 0.765 | - | 0.074 | - |
| **`occl_only`** (occlusion flag, not truncated) | 267 | via244 | 0.790 | **+0.025 [-0.057, +0.113]** | 0.075 | **+0.002 [-0.052, +0.054]** |
| **`trunc_only`** (truncated, no occlusion flag) | 356 | via244 | 0.616 | **-0.149 [-0.244, -0.060]** | 0.172 | **+0.098 [+0.040, +0.154]** |
| `crop_trunc_only` (cut by the **centre crop**) | 312 | via244 | 0.592 | -0.172 [-0.267, -0.087] | 0.186 | +0.113 [+0.046, +0.176] |
| `edge_trunc_only` (cut by the image **edge**) | 198 | via244 | 0.551 | -0.214 [-0.310, -0.109] | 0.201 | +0.127 [+0.056, +0.198] |
| **`top_cut`** (cut at the **top** edge, no occlusion flag) | 44 | via244 | **0.454** | **-0.311 [-0.463, -0.160]** | **0.182** | **+0.109 [+0.003, +0.227]** |
| `trunc_and_occl` | 268 | via244 | 0.662 | -0.103 [-0.195, -0.012] | 0.151 | +0.078 [+0.015, +0.144] |
| `clean_other` (not upright; seated, lying, odd aspect) | 212 | via244 | 0.821 | +0.057 [-0.021, +0.156] | 0.047 | -0.026 [-0.084, +0.020] |
| `no_keypoints` (COCO annotated none) | 22 | via244 | 0.194 | -0.571 [-0.753, -0.367] | 0.511 | +0.438 [+0.203, +0.663] |

**The penalty in the un-interrogated stratum is truncation, and only truncation.**

* **Occlusion, at matched apparent size, costs nothing measurable on the
  resolution-matched chain.** `occl_only` is +0.025 above the bar and +0.002
  below the exit bar against whole people, and both intervals cross zero on all
  three arms. The point estimate on chip is the *wrong sign for a penalty*. This
  is the single most surprising number here.
* **Truncation costs about 0.15 of above-bar rate and 0.10 of let-go rate**, and
  the effect gets worse the more of the person is missing.
* **Cutting the head off is the worst of them** - `top_cut`, the sub-stratum
  shaped like what a drone at close range would actually do, is -0.311 above the
  bar. n = 44, so the interval is wide, but it excludes zero on both bars.
* `clean_other` - people who failed only the *upright* test, so seated or lying
  or oddly proportioned - is if anything **easier** than whole upright people.
  Pose is not the penalty either.
* `no_keypoints` is a size artefact, not a partiality one: its median apparent
  size over the whole set is 11.4 px and only 22 of 370 reach the flown band.

**One honest qualification, which the himax chain forces.** With the sensor model
applied to both sides, `occl_only` does lose above-bar rate - chip
**-0.128 [-0.218, -0.033]** - while its below-exit difference still crosses zero
(**+0.025 [-0.044, +0.090]**). So "occlusion costs nothing" is a statement about
the clean resolution-matched chain and about the **exit** bar. On the sensor
chain, occlusion costs acquisition but still not demonstrably retention. The
truncation/occlusion *ordering* is unchanged on both chains: `trunc_only` is
worse than `occl_only` on every arm and both chains.

### The hold band, 63.4-100.2 px (1.55-2.45 m)

Where the follower actually lives (`tables/hold_band.tsv`, chip, via244):
`whole_upright` 0.778 above / 0.049 below (n=81); `occl_only` **0.872 / 0.017**
(n=117); `trunc_only` 0.638 / 0.133 (n=218); `top_cut` 0.478 / 0.087 (n=23).
Same ordering, and occluded people are again not the problem.

---

## 6. DETECTABILITY AS A FUNCTION OF HOW MUCH OF THE BODY IS IN FRAME

`crop_vis_frac` is the fraction of the annotated box **area** that survives the
centre square crop - a purely geometric measure of "how much of them the network
is shown", produced by the same crop the firmware performs. Flown band, chip arm
(`tables/visible_fraction.tsv`):

| fraction in frame | n | median `px128_h` | via244: >= 0.75 | via244: < 0.45 | himax: >= 0.75 | himax: < 0.45 |
|---|---|---|---|---|---|---|
| **1.00** (whole) | 709 | 67.9 | **0.772** [0.739, 0.803] | **0.073** [0.055, 0.092] | 0.640 | 0.135 |
| 0.90-1.00 | 89 | 86.7 | 0.708 [0.618, 0.798] | 0.101 [0.045, 0.169] | 0.596 | 0.131 |
| 0.75-0.90 | 166 | 82.7 | 0.693 [0.620, 0.759] | 0.139 [0.090, 0.199] | 0.598 | 0.169 |
| 0.50-0.75 | 150 | 78.6 | 0.607 [0.527, 0.687] | 0.180 [0.120, 0.240] | 0.496 | 0.224 |
| **< 0.50** | 147 | 61.4 | **0.490** [0.408, 0.571] | **0.265** [0.197, 0.340] | 0.356 | 0.367 |

Monotone on both bars and both chains. Losing half the body costs **0.28** of
above-bar rate and **triples** the per-frame let-go rate (0.073 -> 0.265).

The keypoint grading (`kp_vis_frac`, fraction of the 17 keypoints marked visible)
agrees in direction but saturates above ~0.4 - 0.726 / 0.778 / 0.770 above the
bar for the 0.4-0.6, 0.6-0.8 and 0.8-1.0 bins - which is expected, because
`kp_vis_frac` mixes truncation with occlusion and section 5 says only one of them
matters.

### Composing the two halves, which is the only forecast this directory supports

Section 1 gives visible fraction against range for our geometry; this section
gives detectability against visible fraction. Composing them says what it would
cost **if** the drone were flown closer than the control law asks for:

| range | visible fraction (section 1) | falls in bin | chip/via244 >= 0.75 | chip/via244 < 0.45 |
|---|---|---|---|---|
| **>= 1.285 m (everywhere it flies)** | 1.000 | 1.00 | **0.772** | **0.073** |
| 1.20 m | 0.965 | 0.90-1.00 | 0.708 | 0.101 |
| 1.00 m | 0.824 | 0.75-0.90 | 0.693 | 0.139 |
| 0.75 m | 0.618 | 0.50-0.75 | 0.607 | 0.180 |
| 0.50 m | 0.412 | < 0.50 | 0.490 | 0.265 |

**This is a composition of two measurements, not a measurement.** It assumes a
COCO person with 62% of their body in frame is as detectable as a drone view of a
person with 62% of their body in frame, which section 8 says is exactly the
assumption COCO cannot support. Read it as an order of magnitude, and note that
the first row - the only one our geometry actually reaches - is the whole-person
row.

---

## 7. THE ANSWER THE TEAM ASKED FOR

**If a real drone mostly saw partial people, would our detection problem be worse
than the whole-person numbers suggest, and by how much?**

Yes, but by less than "partial people" makes it sound, and not by the mechanism
in the objection. Chip arm, resolution-matched, size-standardised, per-frame
fraction below the 0.45 exit bar:

| what the drone sees | below-exit rate | vs whole people |
|---|---|---|
| whole upright people (what the fidelity study measured) | **0.074** | - |
| the full COCO partial mix | **0.123** | +0.050 [+0.002, +0.097], ~1.7x |
| occluded people only | 0.075 | +0.002 [-0.052, +0.054], **no change** |
| truncated people only | **0.172** | +0.098 [+0.040, +0.154], ~2.3x |
| people with their head cut off | 0.182 | +0.109 [+0.003, +0.227], ~2.5x |
| people with under half their body in frame | 0.265 | ~3.6x (band-cut, not standardised) |

**And the three things that follow.**

1. **MinHyuk's concern does not translate into a detection penalty for this rig,
   because the geometry does not produce the condition.** At 1.55-2.44 m the
   whole 1.7 m person is in the crop, and the truncation penalty - the only part
   of the partial-people effect that is real - therefore never applies. That is
   worth saying plainly rather than hedging.
2. **It would translate if any of three things changed**, and all three are
   cheap to hit: a subject taller than ~1.9 m (cut below 1.571 m, inside the
   flown repeat spread), a lower flight height, or a person who walks into the
   drone faster than the control law backs away. The limit is
   `(person_height - 0.8) / 0.70021` and nothing enforces it.
3. **The bigger number is still the one the fidelity study published.** The
   simulator shows a **0.000** per-frame let-go rate where a whole, upright,
   unoccluded real person at the same apparent size shows **0.074-0.113**. The
   partial-people effect adds at most another **+0.05 to +0.10** on top of that
   and only under conditions our geometry avoids. If the team has one thing to
   fix before the lab session, it is still the 99th-percentile cutout, not the
   field of view.

**The one thing the objection does get right about our rig is bearing, not
truncation** (section 1). The crop is 2.72 m wide at 1.94 m, and
`2026-09-15-typical-person`'s own probe already recorded the control cutout
dropping to 0.319 at -33.7 deg. That is the FOV failure this hardware will
actually meet, and nothing in this directory or the fidelity study measures it.

---

## 8. WHAT THIS DOES NOT PROVE

* **A photographer's crop is not a drone's crop, and this is the central
  limitation.** COCO's truncated people are truncated because a human chose that
  framing. They are systematically **larger** (median 100.8 px128_h against 68.8
  for whole people), photographed closer, and more often in cluttered scenes - so
  the `trunc_only` penalty may be partly a scene-complexity penalty wearing a
  truncation label. Size standardisation removes the apparent-size confound and
  nothing else.
* **COCO contains no image taken from a drone at 2 m.** No 0.8 m level eye line,
  no himax sensor, no rotor-induced motion blur, no flight-rate temporal
  structure. The himax columns model the sensor stage; they do not measure it.
* **`top_cut` is n = 44 in the flown band** and is the most confounded cell here:
  its median apparent size is 122.8 px, far above every other stratum, so these
  are people photographed very close. It is the best analogue COCO offers to a
  drone cutting off a head, and it is not a good one.
* **The composition in section 6 is not a measurement of anything.** It chains a
  geometric calculation onto a photographic one and assumes the two "visible
  fractions" mean the same thing.
* **COCO's `v == 0` is ambiguous** - out of frame, or not annotatable - so
  occlusion is read from `v == 1` only. That makes `occl_only` a *conservative*
  occlusion stratum: a person whose occluded joints were simply left unlabelled
  lands in `no_keypoints` or `clean_other` instead. If that mislabelling is
  common, the "occlusion is free" finding is weaker than it looks.
* **`occl_only` is free on the clean chain and not on the sensor chain** (section
  5). Anyone quoting "occlusion costs nothing" must say which chain and which
  bar.
* **Nothing flew.** These are static photographs. No motion blur, no follower
  state machine, no 3-frame confirmation, no hysteresis, no temporal correlation.
  A per-frame rate is not a loss-of-track fraction, and because consecutive
  frames of one person are strongly correlated it cannot be turned into one by
  arithmetic. The fidelity study said this and it is still true.
* **The geometry assumes a level camera and a person standing on the same floor
  plane.** Both hold in the simulator by construction. On hardware, pitch during
  acceleration tilts the optical axis and would move the 1.285 m limit; that is
  not modelled here.
* **Nothing here re-scored an image**, which is the source of this directory's
  main strength (no chain mismatch is possible) and of its main weakness (it
  inherits every property of the fidelity study's scoring, including that its
  real side is 640-px photographs resampled to 244, not himax frames).

---

## 9. Files, and how to re-run

```
scripts/geometry_fov.py   section 1: the crop geometry, importing scoreboard.py
                          for every constant. No data, no model, no simulator.
scripts/strata.py         joins COCO instances + person_keypoints onto the
                          fidelity study's real_people.csv and real_people_himax.csv
                          and derives the truncation / occlusion sub-strata.
                          NOTHING IS RE-SCORED.
scripts/analyze.py        sections 3-6: band cuts, size standardisation onto
                          whole_upright's own size mix, cluster-bootstrap CIs
                          (2 000 draws, cluster = photograph)
scripts/verify_readme.py  re-derives every number this README quotes from the
                          tables and fails on any that drifted: 145 claims

tables/geometry_fov.tsv        visible fraction and px128_h against range
tables/geometry_fov.txt        the full printed geometry
tables/strata.csv              2 693 rows: the new flags joined to the existing
                               confidences (via244 columns included)
tables/strata_himax.csv        8 079 rows: the same flags on the 3-draw himax table
tables/size_profile.tsv        why a band cut is not enough (per-stratum size mix)
tables/flown_band.tsv          38.8-103.6 px, band-cut only, both bars, both chains
tables/size_standardised.tsv   THE HEADLINE: every stratum at whole_upright's size
                               mix, with differences and CIs
tables/hold_band.tsv           63.4-100.2 px (1.55-2.45 m)
tables/visible_fraction.tsv    detectability graded by crop_vis_frac and kp_vis_frac
tables/analysis.txt            the full printed analysis
logs/*.log                     run logs (see the note below)
```

Re-run, in order (absolute paths; `$D` is this directory). None of this needs the
simulator lock, a GPU, or more than 3 minutes of CPU:

```
/Users/saimaruvada/Downloads/drone/nemoenv/bin/python $D/scripts/geometry_fov.py $D
/Users/saimaruvada/Downloads/drone/nemoenv/bin/python $D/scripts/strata.py       $D
/Users/saimaruvada/Downloads/drone/nemoenv/bin/python $D/scripts/analyze.py      $D
/Users/saimaruvada/Downloads/drone/nemoenv/bin/python $D/scripts/verify_readme.py $D  # must print ALL CLAIMS VERIFIED
```

Wall clock on this laptop: geometry instant, strata 6 s (it parses the two COCO
annotation JSONs), analysis about 4 minutes (the bootstrap in section 3 resamples
both sides of every difference).

**`logs/` needs `git add -f`.** `.gitignore` ignores `logs/` at line 9 and
`*.log` at line 11, so all four files under `logs/` are ignored by default:

```
git add -f docs/eval_results/2026-09-15-partial-people/logs/*.log
```

They are `geometry_fov.log`, `strata.log`, `analyze.log` and
`verify_readme.log`. Nothing else in this
directory is ignored - `tables/` is `tables`, not `data`, so the anchored
`/data/` rule at line 4 does not apply, and no `*.pth`, `*.onnx` or `__pycache__`
is written here.

---

## 10. Cross-checks against the study this one re-cuts

Because nothing was re-scored, several numbers here must reproduce the fidelity
study's own tables exactly, and they do:

| quantity | fidelity study | here |
|---|---|---|
| `occluded_or_truncated`, n | 2 488 | 2 489 before dropping the sim source, 2 488 after |
| `whole_upright`, n | 204 | 204 |
| flown-band `whole_upright` < 0.45, float/fq/chip | 0.088 / 0.081 / 0.074 | 0.088 / 0.081 / 0.074 |
| flown-band `occluded_or_truncated` < 0.45 | 0.148 / 0.158 / 0.124 | 0.148 / 0.158 / 0.124 |
| hold-band `whole_upright` himax, chip | 0.749 >= 0.75, 0.095 < 0.45 | 0.749, 0.095 |

Those are the same rows read through a different script, so they are a check that
the join did not corrupt anything - not independent evidence.

`scripts/verify_readme.py` re-derives all **145** numbers this README quotes from
the tables and prints `ALL CLAIMS VERIFIED`. It checks that each quote is a
correct rounding of the stored 4 dp value; it does not re-check the statistics.
