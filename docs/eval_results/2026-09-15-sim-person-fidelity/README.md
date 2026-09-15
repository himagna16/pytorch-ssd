# Does the simulated person predict a real person? Confidence versus apparent size, sim against COCO

**Nothing here was measured on hardware and nothing here flew.** No simulator
process, no control loop, no firmware, no UDP, no GAP8. The sim side is 11 814
offscreen MuJoCo renders built by the repo's own unmodified `build_scene.build()`;
the real side is the 2 693 COCO val2017 photographs that contain a person. The
"chip" network is the champion's `model_id_dory.onnx` run under onnxruntime
1.19.2 in doryenv, not on a GAP8.

**The question, and why it is the dangerous one.** Yesterday's companion study
(`docs/eval_results/2026-09-15-sim-pet-fidelity/`) established that the simulator
OVERSTATES how detectable a rendered *pet* is - the rendered dog reads +0.26 to
+0.52 higher than real dog photographs at matched apparent size and clears the
0.75 bar about 2.9x as often. If flat cards were generically more detectable than
photographs, the same bias would apply to PEOPLE, and there it points the
dangerous way: the simulator reports the drone tracking a person **0.97-0.99** of
the time (`docs/eval_results/2026-09-14-baseline-075/` has seven person cells;
`M1_tracking_fraction` is 0.9905 / 0.992 / 0.996 / 0.982 / 0.996 / 0.979 on six
of them and 0.917 on the seventh, `B.moving__delta_backend`), and if a real person at the same apparent size is
materially less detectable than the card, real-world tracking is worse than every
flight result says and the drone will drop people it is supposed to follow.

This directory measures that. It reuses the pet study's scoring path - literally
the same file on disk, `scripts/champion_arms.py`, loaded through
`scripts/shared_arms.py` - so nothing here can be a preprocessing difference.

---

## 0. TL;DR

| claim | verdict |
|---|---|
| **THE VERDICT** | **The simulator OVERSTATES how detectable a person is - but NOT because cards flatter. Because of which cutout was chosen.** At the sizes the follower actually holds station at (63-100 px128_h), the flown s15/s01 card is at or above the 0.75 confirmation bar on **100.0%** of frames (102 frames, 34 poses) and below the 0.45 exit bar on **0.0%**, on all three networks. Real whole, upright, untruncated people at the same apparent size clear 0.75 on **77.8-80.2%** and fall below 0.45 on **4.9-7.4%** (resolution-matched); with himax on both sides, **68.3-74.9%** and **9.5-12.8%**. Over the whole flown band, size-standardised, the sim is **1.27x to 1.95x** as likely to be above the bar, and its below-exit rate is **0.000 against 0.085-0.227** |
| **The control** (§2) | **Validated on the arm that flies, before any comparison.** The 244-px chain is a no-op on the sim side **by construction** (a rendered frame's centre crop is already 244x244 and PIL's resize to its own size is the identity, so `chip` and `chip_via244` agree on all 11 814 rendered frames - a consistency check, not a test that could have failed), and on the real side it moves the chip arm's above-bar rate by **+0.129 to +0.191** (every CI excludes zero), against **-0.008 to +0.034** on float and **-0.014 to +0.000** on fq. Unmatched, the real chip rate on the whole slice reads 0.505 instead of 0.634, which would have inflated every chip ratio below by a further ~1.25x |
| **(a)** median confidence, sim vs real, per size bin | **Sim higher in 45 of 48 cells** - the three exceptions are all the same cell, whole+upright at 55-80 px (-0.026 / -0.024 / -0.006 on float / fq / chip) - but how much depends entirely on which real set. vs all people **+0.034 to +0.210**, 0 of 12 intervals crossing zero; vs whole+upright **-0.026 to +0.085**, **9 of 12 crossing**; vs whole+upright+isolated +0.015 to +0.435, 8 of 12 crossing; with himax on **both** sides **+0.055 to +0.348**, only **1 of 12 crossing**. Real whole upright people photograph well - median 0.85 to 0.99 across the flown-band bins, rising with size - so on raw photographs there is little headroom left above them to overstate |
| **(b)** fraction at or above 0.75 - whether the follower confirms | **Sim higher in all 48 cells, and not one interval crosses zero.** +0.154 to +0.709. Chip, himax on both sides: +0.600 [+0.434, +0.747] at 25-40 px, +0.243 [+0.078, +0.412] at 40-55, +0.191 [+0.033, +0.337] at 55-80, +0.201 [+0.120, +0.286] at 80-129 |
| **(c)** fraction BELOW the 0.45 exit bar - whether the follower lets go | **This is the number that matters, and the sim shows zero.** `sim_cells_himax` is below 0.45 on **0 of 282** frames in the flown band, on all three arms. Real people at matched size: **7.4-8.8%** (whole+upright), **11.3-14.2%** (whole+upright through himax), **11.9-15.0%** (all people), **18.9-21.6%** (whole+upright+isolated). `d_exit` is negative in **all 48** `sim_cells` cells and its interval excludes zero in 31 of them |
| Is the sim biased toward FALSE ALARMS specifically? | **No - and not toward detectability generally either. It COMPRESSES the confidence scale toward ~0.6.** Rendering 204 real people as cards at their own apparent size and regressing render-minus-photo on the photograph's own score gives slope **-0.792 [-0.941, -0.651]** (chip), fixed point **0.585**. Photographs the network scores below ~0.6 are pushed UP (median **+0.292** for photos in [0.0, 0.3)); photographs above are pulled DOWN (median **-0.302** for photos in [0.9, 1.0]). One mechanism predicts both studies: a dog is a ~0.3 photograph and goes up into a false alarm; a person is a ~0.9 photograph and comes down |
| Then why do the flown person cells read so high? | **Subject selection. The cutout is an outlier.** COCO 19432 / ann 428692 - the cutout **both** person cells name - sits at the **98.5th to 100th percentile** of 266 real people put through the same pipeline at the same range (0.943-0.998 against a cohort median of 0.430-0.769). As a *photograph* the same person is utterly ordinary: **43.8th-54.2nd percentile** of size-matched whole-upright photographs. The rendering did not flatter people; it flattered **this** person |
| The paired test - the same human, photographed and rendered | **Rendering a real person lowers their score** - but the size of that depends on matching the SENSOR stage as well as the resolution stage, and the first edition of this table did not (see §4(d) and the audit note in §8). Chain-matched, 204 people rendered at the range where the card subtends what their own photograph subtends, chip: **-0.169 [-0.237, -0.109]** with neither side through the sensor model, **-0.130 [-0.179, -0.078]** with both sides through it. The unmatched pairing this directory first quoted (render through himax, photograph not) reads -0.209 and is about 1.2-1.6x too large. On the isolated subset (n=59) the matched numbers are **-0.076 [-0.123, -0.032]** clean/clean and **-0.050 [-0.113, +0.018]** himax/himax - **the second crosses zero**, so on isolated people the paired effect is not resolved |
| The sim's own person, both ways, inside the flown band | **+0.002 to +0.012.** The photograph subtends 107.8 px; the flown eye line reaches that at **1.44 m**, so this pair needs no padding at all - which the pet study could not do (its dog capped at 51.9 px against a 120 px photograph). Photo 0.989, render 0.997 on chip/clean. For *this* subject the renderer is very nearly a no-op, which is exactly why it is an outlier |
| What this does NOT establish | **Anything about hardware, and anything about a flight.** Static frames, no motion blur, no follower state machine, no 3-frame confirmation, no hysteresis, no temporal correlation. "Fraction of frames above the bar" is not "fraction of flights that track". And the real side is COCO photographs, which are not himax frames |

The honest one-line version: *the simulator's person is a 99th-percentile card,
not a typical one - the rendering pipeline actually makes the average real person
HARDER to see, so the 0.97-0.99 tracking fractions are a property of one COCO
cutout rather than of the perception system, and a real person at the same
apparent size sits below the follower's let-go threshold on 7-22% of photographs
where the simulator shows 0%.*

---

## 1. The discipline

Everything was produced by importing the repo's own unmodified tooling. `git
status` on `tools/`, `docs/sim_results/` and every existing `docs/eval_results/`
directory is clean; the repo sat at `06fe09d` throughout, nothing was committed
or pushed, and the only new path is this directory.

**The tooling is byte-identical to the suite that flew the 0.75 baseline**
(`code_hashes.txt` here vs `2026-09-14-baseline-075/code_hashes_after.txt`):

```
ea639fea...  tools/crazysim_macos/build_scene.py      same bytes as the 0.75 baseline
481c0a99...  tools/crazysim_macos/camera_model.py     same bytes as the 0.75 baseline
8281df9f...  tools/crazysim_macos/follow_person.py    same bytes as the 0.75 baseline
ce917647...  tools/crazysim_macos/perception_backends.py
e0d7cbe5...  tools/crazysim_macos/scoreboard.py       differs (the scorer fix); NOT used here
78946a3f...  docs/eval_results/2026-09-15-sim-pet-fidelity/scripts/champion_arms.py
```

**One scoring path, shared with the pet study, not copied.**
`scripts/shared_arms.py` puts the pet study's `champion_arms.py` on the path and
re-exports it. There is one file; its sha256 is printed by every script that runs
and recorded above. A difference between the two studies can be a difference in
subject or in method, never in which network was loaded or how a frame was
preprocessed.

**Two cross-checks that would have failed loudly.**

1. `build_scene.run_model`'s own score is recorded at render time and re-checked
   after the PNG round-trip: **max |float - build_scene.run_model| = 0.00e+00**
   over 600 frames and over 11 214 frames
   (`logs/sim_score_person.log`, `logs/sim_score_cohort.log`).
2. That check **caught a real bug**, which is why it is worth having. The first
   cohort render formatted filenames to two decimals, so a subject whose matched
   range rounded to a ladder value (1.505 vs 1.500) overwrote its own PNG - 30
   frames, 5 subjects. The assertion fired at 0.0643. Filenames went to three
   decimals and the cohort was re-rendered; the re-run reports 0 duplicate
   filenames and 0.00e+00 disagreement. The same patch fixed `is_r_match`, which
   compared a rounded range against an unrounded one and fired on 126 of 11 214
   rows instead of 1 602.

**And one correction to this directory's own inclusion rule, found by looking at
the pictures.** `figures/what_the_net_sees.png` showed a "whole upright person"
whose panel contained a bench and a chicken. COCO 197870's person is 73 px wide
at x = 505 of a 640x425 photograph, whose centre crop runs x = 107-532: the crop
removes most of them. The first rule checked that the box was inside the crop
**vertically** only. Both axes are now required, `whole_upright` fell from 267 to
**204** and `wui` from 77 to **59**, and every number in this document is from
after that fix. The cohort was NOT re-rendered - the stricter stratum is a subset
of what was rendered - but the stratum flags baked into the render CSV are stale
and are re-derived from `tables/real_people.csv` on every read
(`shared_arms.relabel`). 62 rendered subjects are therefore rendered but not
compared.

---

## 2. THE CONTROL, before any comparison

`perception_backends.firmware_preprocess` is the C port of the firmware:
centre square crop, then each of the 128x128 output pixels is the rounded mean of
the 2x2 camera block at the nearest-neighbour source pixel. Integer arithmetic,
**no antialiasing**. So the stride it samples at depends entirely on how big its
input is:

| input | centre crop | stride into `firmware_preprocess` |
|---|---|---|
| a rendered AI-deck frame, 324x244 | 244 px | **1.91** - the 2x2 block covers nearly every source pixel |
| a COCO photograph (median of this slice) | 427 px | **3.34** - the block samples a fifth of the pixels and aliases the rest |
| the same photograph through `*_via244` | 244 px | **1.91** |

`float` and `fq` are immune: their preprocessing is PIL BILINEAR, which
antialiases at any input resolution. That is precisely why validating this
control on `float` licenses nothing about `chip`, and is how the pet study's
headline came to be overstated 2.5x.

**(i) It is a no-op on the sim side - by construction, which is worth saying
plainly.** A rendered frame is 324x244, so its centre crop is already 244x244,
and PIL's `resize` to an image's own size returns the image unchanged (checked
directly: `np.array_equal(a, a.resize((244,244), BILINEAR))` is `True`). The
table below is therefore a consistency check that the sim frames really are
244 px tall and that nothing else crept into the `*_via244` path - it is NOT a
test the control could have failed, and it should not be read as evidence that
the two sides are on the same chain. The evidence for that is (ii), plus the
fact that the stride into `firmware_preprocess` is 1.91 on both sides:

| sim set | n frames | max \|chip − chip_via244\| | frames differing |
|---|---|---|---|
| main (s15 + s01 person cells) | 600 | **0.0000** | **0** |
| cohort (267 real people rendered) | 11 214 | **0.0000** | **0** |
| float and fq, both sets | 11 814 | 0.0000 | 0 |

**(ii) It moves the real side, on the arm that flies.** Fraction at or above
0.75, raw photograph against the frame's own chain, 95% cluster bootstrap:

| real set | n | chip raw | chip via244 | delta | 95% CI |
|---|---|---|---|---|---|
| all people, whole slice | 2693 | 0.505 | **0.634** | **+0.129** | [+0.114, +0.144] |
| all people, flown band 38.8-103.6 px | 1262 | 0.551 | **0.704** | **+0.153** | [+0.129, +0.176] |
| whole_upright | 204 | 0.564 | **0.755** | **+0.191** | [+0.132, +0.255] |
| wui | 59 | 0.407 | **0.593** | **+0.186** | [+0.102, +0.288] |

against **-0.008 to +0.034** on float and **-0.014 to +0.000** on fq. The
below-exit rate moves the same way: chip 0.261 -> 0.157 on the whole slice.

**Which way it cuts.** The control moves the real side UP, so it makes the
simulator's advantage SMALLER: had the chip arm been left unmatched, the real
whole-slice above-bar rate would have read 0.505 rather than 0.634 and every chip
ratio below would have come out about 1.25x larger than it should. Every chip
comparison here uses sim `chip` against real `chip_via244`; the raw columns are
kept in `tables/size_response.tsv` and `tables/control_resolution.tsv`, and raw
`chip` on a 640-px photograph corresponds to nothing the drone can ever see. The
himax real arm resizes to 244 before the sensor model, so it is already matched;
that is asserted in `real_people_himax.py` and comes back 0.0000.

---

## 3. What is being compared

### Apparent size, the one unit both sides share

`px128_h` is the subject's height in the 128x128 tensor the network sees.
Computed by the pet study's arithmetic on the real side (`crop = min(W,H)`, clamp
the COCO box to the crop, scale by `128/crop`) and by MuJoCo segmentation of the
subject's own panel geom inside the centre crop, times `128/244`, on the sim
side. `build_scene.make_cutout` pastes the annotation's own bbox crop onto the
panel, so panel height **is** box height.

**The person is not size-capped, and the pet was.** The pet study's dog, standing
on the floor under a level 0.8 m camera, could never exceed 51.9 px - closing in
pushed it out of the bottom of the frame. A 1.7 m person is centred on that eye
line: `px128_h = 155.4 / range_m`, whole-body-in-frame from 1.29 m out, so the
flown band 1.5-4.0 m is **38.8-103.6 px**, and the sim reaches 120 px at 1.30 m.
Sim and real overlap across the entire flown band and past the real median
(71.4 px). Nothing here needs extrapolation.

### The real side: four sets, stated rather than chosen quietly

2 693 val2017 images have a non-crowd person. The subject is the largest by
clamped height. Because people are plentiful, the slice can afford strata - and
it needs them, since the pet study's largest caveat was that only size was
matched, never pose or context.

| set | n | what it is |
|---|---|---|
| `all_people` | 2692 | every person image (minus the sim's own source). Statistical weight, no pose control |
| `whole_upright` | 204 | **COCO's own occlusion annotation**: both shoulders, hips, knees and ankles labelled `v == 2` (visible - `v == 1` means labelled-but-occluded) plus a visible head keypoint; box not touching the image border; box wholly inside the centre crop in **both** axes; aspect h/w >= 2.0 and shoulder-to-ankle span >= 55% of box height. Whole, unoccluded, untruncated, standing |
| `wui` | 59 | `whole_upright` **and isolated** - exactly one non-crowd person and no crowd region. One whole standing person, alone: the closest real analogue to what the drone follows and to what the simulator renders |
| `occluded_or_truncated` | 2488 | the complement of `whole_upright`, reported as its own stratum rather than discarded, because the drone will meet these too |

The simulator's own source photograph is flagged and **excluded from every
comparison set**, so the sim is never compared against itself. (It would not have
qualified for `whole_upright` anyway: 16% of its width falls outside the centre
crop.)

### The sim side: two jobs, and one that did not exist before

* **`sim_person.csv`, 600 frames** - the flown cells. `s15_static_offset` and
  `s01_control_moving` name the **same** cutout (19432 / 428692, 1.7 m), so both
  are rendered at their own subject x (3.5 and 3.0), since `build_scene` paints
  each panel's background from the geometry behind it and the pet study measured
  up to 0.13 of confidence from panel position alone. Ranges 1.30-5.0 m including
  r = 1.44 (the photograph's own apparent size), lateral offsets 0, ±0.25, ±0.5,
  clean plus 3 himax draws after 20 AE warm-up frames - the pet study's protocol,
  unchanged.
* **`sim_cohort.csv`, 11 214 frames** - **267 real people put through the
  simulator's own cutout pipeline**, at s15's geometry, on the six-point flown
  ladder plus each subject's own matched range. This is the thing the pet study
  could not build with two animals. It turns "only size is matched" into a
  **paired** comparison in which identity, pose, clothing, and apparent size are
  all held fixed and only the simulator varies.

---

## 4. The answers

### (a) At matched apparent size, is the simulated person read more confidently?

**Yes in 45 of 48 cells - the three exceptions are all whole+upright at 55-80 px
- but the size of the effect depends entirely on which real set you accept as
the drone's target.** Sim minus real median confidence,
95% cluster bootstrap (a photograph under 3 himax draws is one photograph; a
rendered pose under 3 sensor seeds is one pose). Chip arm, sim himax, real
resolution-matched:

| real set | 25-40 px | 40-55 px | 55-80 px | 80-129 px |
|---|---|---|---|---|
| all people (n=2692) | +0.174 [+0.104, +0.226] | +0.081 [+0.038, +0.129] | +0.039 [+0.005, +0.082] | +0.034 [+0.027, +0.043] |
| whole+upright (n=204) | +0.001 [-0.050, +0.140] | +0.025 [-0.055, +0.175] | **-0.006** [-0.058, +0.052] | +0.010 [+0.003, +0.017] |
| whole+upright+isolated (n=59) | +0.343 [-0.021, +0.527] | +0.204 [-0.050, +0.515] | +0.251 [+0.022, +0.412] | +0.017 [-0.000, +0.141] |
| whole+upright, **himax both sides** | +0.263 [+0.146, +0.344] | +0.100 [+0.008, +0.174] | +0.078 [-0.004, +0.154] | +0.055 [+0.022, +0.097] |

Across all three arms: vs all people **+0.034 to +0.210** (0 of 12 intervals
cross zero); vs whole+upright **-0.026 to +0.085** (**9 of 12 cross**); vs
whole+upright+isolated +0.015 to +0.435 (8 of 12 cross); himax on both sides
**+0.055 to +0.348** (1 of 12 crosses).

**The honest reading of (a): on median confidence, against unoccluded whole
upright people photographed in daylight, the simulator is barely distinguishable.**
Those photographs sit at a median of 0.85 (25-40 px) to 0.99 (80-129 px), so
there is little headroom left above them. The median is the wrong statistic for this question; the two
thresholds the follower actually uses are (b) and (c), and those separate
cleanly. Full table with float and fq: `tables/matched_gap.tsv` (84 cells).

### (b) Does the fraction above the 0.75 confirmation bar differ?

**Yes: positive in all 48 `sim_cells` cells, and not one interval crosses zero.**
+0.154 to +0.709. Chip arm, himax on both sides:

| bin | sim cells | real whole+upright/himax | d_frac |
|---|---|---|---|
| 25-40 px | 0.933 | 0.333 | **+0.600** [+0.434, +0.747] |
| 40-55 px | 0.942 | 0.699 | **+0.243** [+0.078, +0.412] |
| 55-80 px | 0.917 | 0.726 | **+0.191** [+0.033, +0.337] |
| 80-129 px | 1.000 | 0.799 | **+0.201** [+0.120, +0.286] |

**The hold band** - the sizes the follower actually spends its time at. The
seven person cells of the 0.75 baseline settle between 1.55 and 2.44 m from the
person (`scoreboard.md` "held station at": per-cell means 1.63 / 1.74 / 1.87 /
2.00 / 2.19 / 2.20 / 2.44, repeat range 1.55-2.44, target 1.94). Taking
1.55-2.45 m, that is **63.4-100.2 px128_h** for a 1.7 m person. Cut by SIZE, so
both sides are cut the same way (`tables/hold_band.tsv`; the sim's range-only cut
gives 1.000 too, so unlike the pet study's latch band nothing here turns on
whether the filter is an AND):

| group | arm | n | median | >= 0.75 | < 0.45 |
|---|---|---|---|---|---|
| **sim cells, himax** | float / fq / chip | 102 (34 poses) | 0.991 / 0.992 / 0.978 | **1.000 / 1.000 / 1.000** | **0.000 / 0.000 / 0.000** |
| real whole+upright, via244 | float / fq / chip | 81 | 0.987 / 0.984 / 0.984 | 0.790 / 0.802 / 0.778 | 0.074 / 0.062 / 0.049 |
| real whole+upright, himax | float / fq / chip | 243 | 0.910 / 0.871 / 0.906 | 0.704 / 0.683 / 0.749 | 0.107 / 0.128 / 0.095 |
| real all people, via244 | float / fq / chip | 697 | 0.939 / 0.933 / 0.936 | 0.723 / 0.719 / 0.750 | 0.106 / 0.113 / 0.085 |
| real whole+upright+isolated | float / fq / chip | 21 | 0.878 / 0.855 / 0.731 | 0.524 / 0.524 / 0.476 | 0.190 / 0.143 / 0.143 |

Size-standardised over the whole flown band, so neither side can win on its size
distribution (`tables/size_standardised.tsv`), fraction >= 0.75:

| real set | float | fq | chip | ratio (float / fq / chip) |
|---|---|---|---|---|
| sim cells | 0.979 | 0.979 | 0.943 | - |
| all people | 0.652 | 0.633 | 0.655 | 1.50 / 1.55 / 1.44 |
| whole+upright | 0.773 | 0.762 | 0.732 | **1.27 / 1.28 / 1.29** |
| whole+upright, himax both sides | 0.625 | 0.549 | 0.713 | 1.57 / 1.78 / 1.32 |
| whole+upright+isolated | 0.546 | 0.501 | 0.492 | 1.79 / 1.95 / 1.91 |

The ratios are far smaller than the pet study's 2.9x-8.2x, because a real person
is genuinely easy to detect. The simulator's problem with people is not that it
inflates a hard case - it is that it removes the failures entirely, which is (c).

### (c) The exit bar, and this is the safety-critical one

Below 0.45 the follower clears `vis_state` and lets go; it then needs three fresh
consecutive frames at or above 0.75 before it steers again. So the number that
decides whether a track is *held* is not the fraction above 0.75, it is the
fraction **below 0.45**. Flown band, `tables/exit_bar.tsv`:

| group | n | float | fq | chip |
|---|---|---|---|---|
| **sim cells, himax** | 282 | **0.000** | **0.000** | **0.000** |
| real, all people | 1261 | 0.142 | 0.150 | 0.119 |
| real, whole+upright | 136 | 0.088 | 0.081 | 0.074 |
| real, whole+upright, through himax | 408 | 0.120 | 0.142 | 0.113 |
| real, whole+upright+isolated | 37 | 0.216 | 0.189 | 0.189 |
| real, occluded or truncated | 1125 | 0.148 | 0.158 | 0.124 |
| sim cohort (real people rendered) | 4188 | 0.442 | 0.457 | 0.397 |

**The simulator shows a 0% per-frame risk of a track drop, on 282 frames across
34 distinct poses and 3 sensor seeds, on all three networks. Real people of the
same apparent size sit below the let-go threshold on 7% to 22% of photographs.**
`d_exit` is negative in all 48 `sim_cells` cells of `tables/matched_gap.tsv`, and
its 95% interval excludes zero in 31 of them (the 17 that cross are the small-n
`wui` cells and the largest size bin).

### (d) Is the bias toward FALSE ALARMS specifically, or toward detectability?

**Neither. The renderer compresses the confidence scale toward about 0.6.**

Take the 204 whole-upright people, render each at the range where the card
subtends exactly what that person's own photograph subtends, and regress
render-minus-photo on the photograph's own score (`tables/regression_to_middle.tsv`,
`figures/paired_render_vs_photo.png`):

| stratum | arm | n | slope | 95% CI | r | fixed point |
|---|---|---|---|---|---|---|
| whole_upright | chip | 204 | **-0.792** | [-0.941, -0.651] | -0.603 | **0.585** |
| whole_upright | float | 204 | -0.753 | [-0.903, -0.607] | -0.561 | 0.563 |
| whole_upright | fq | 204 | -0.797 | [-0.932, -0.659] | -0.594 | 0.568 |
| wui | chip | 59 | -0.738 | [-0.950, -0.526] | -0.661 | 0.622 |

and by bucket, chip, `whole_upright`:

| the photograph's own score | n | median render − photo |
|---|---|---|
| [0.0, 0.3) | 10 | **+0.292** |
| [0.3, 0.6) | 17 | +0.073 |
| [0.6, 0.9) | 52 | -0.210 |
| [0.9, 1.0] | 125 | **-0.302** |

**The paired numbers above and in §0 must be read chain-matched.** The paired
test as `analyze_person.py` builds it takes the render THROUGH
`camera_model.himax_typical` and the photograph on `*_via244`, i.e. with no
sensor model - the resolution chain is matched, the sensor chain is not, and
§4(f) below measures that same sensor stage costing real photographs 0.03 to
0.18 of above-bar rate. `scripts/audit_paired_chain.py` re-measures it all three
ways (`tables/paired_chain_matched.tsv`), chip arm:

| pairing | matched? | stratum | n | median d | 95% CI | >=0.75 photo -> render | <0.45 photo -> render |
|---|---|---|---|---|---|---|---|
| clean vs via244 | yes | whole_upright | 204 | **-0.169** | [-0.237, -0.109] | 0.755 -> 0.407 | 0.069 -> 0.255 |
| himax vs himax | yes | whole_upright | 204 | **-0.130** | [-0.179, -0.078] | 0.657 -> 0.373 | 0.127 -> 0.245 |
| himax vs via244 | **NO** | whole_upright | 204 | -0.209 | [-0.256, -0.156] | 0.755 -> 0.373 | 0.069 -> 0.245 |
| clean vs via244 | yes | wui | 59 | **-0.076** | [-0.123, -0.032] | 0.593 -> 0.407 | 0.169 -> 0.220 |
| himax vs himax | yes | wui | 59 | **-0.050** | [-0.113, **+0.018**] | 0.593 -> 0.458 | 0.254 -> 0.288 |
| himax vs via244 | **NO** | wui | 59 | -0.068 | [-0.111, -0.033] | 0.593 -> 0.458 | 0.169 -> 0.288 |

The sign survives matching on `whole_upright` and the CI still excludes zero, so
"rendering the average real person lowers their score" stands - at **-0.13 to
-0.17**, not -0.21. On the isolated `wui` stratum it does **not** survive: with
the sensor model on both sides the interval crosses zero. The regression slope
is unaffected (-0.757 clean/clean, -0.807 himax/himax, -0.792 as quoted), so the
compression finding does not depend on the pairing.

**And the slope has to be read against the right null.** A slope of exactly -1
is what you get when the render score carries NO information about the
photograph's score at all: then `d = y - x` regresses on `x` with slope -1 and
the "fixed point" is simply `mean(y)`. Permuting the render scores across
subjects (1 000 draws) gives slope **-1.003 [-1.162, -0.848]** and fixed point
**0.638**. The observed slope -0.792 [-0.941, -0.651] does exclude -1, so some
signal survives the rendering - but only a little: the regression of render on
photograph is **beta = +0.208**, **r = +0.194**, and the observed fixed point
0.585 is essentially the render distribution's own centre (mean 0.639, median
0.626), which is where the null puts it too. So the honest statement is *the
render mostly destroys whatever made the photograph score what it did and lands
near 0.6 regardless*, of which "compresses the scale toward 0.6" is a
generous-sounding special case. The predictive claim also under-shoots
quantitatively: the fit predicts **+0.226** for a 0.30 photograph, against the
pet study's reported +0.26 to +0.52.

With that caveat, a slope well below zero with a fixed point near 0.6 is still
not a shift, it is a **collapse toward the middle**, and this one mechanism is
consistent with both studies:

* a real dog is a **~0.30** photograph; rendering pushes it **up**, which is the
  pet study's +0.26 to +0.52 and its 2.9x false-alarm inflation;
* a real person is a **~0.92** photograph; rendering pulls it **down**, which is
  this study's cohort at **0.21-0.22** above the bar against **0.73-0.77** for
  the same people's own photographs (size-standardised, flown band).

So the answer to "is the simulator biased toward false alarms specifically" is
**no, but the pet study's headline is not wrong either** - it is a special case.
The bias is toward the middle. It reads as a false alarm on anything the network
would score low, and as a missed detection on anything it would score high. The
pet study happened to test the first half and this one tests the second.

### (e) Then why do the flown person cells read 0.94-1.00?

**Because the cutout is an outlier, and the outlier status is created by the
rendering.** `tables/subject_selection.tsv`, chip, himax, dy = 0:

| range | px128_h | cohort median | cohort >= 0.75 | **COCO 19432** | percentile |
|---|---|---|---|---|---|
| 1.5 m | 103.9 | 0.769 | 0.526 | **0.998** | 99.6% |
| 2.0 m | 78.2 | 0.642 | 0.342 | **0.997** | 100.0% |
| 2.5 m | 62.4 | 0.430 | 0.147 | **0.979** | 100.0% |
| 3.0 m | 51.9 | 0.535 | 0.177 | **0.943** | 98.5% |
| 3.5 m | 44.6 | 0.617 | 0.274 | **0.972** | 98.5% |
| 4.0 m | 38.8 | 0.605 | 0.274 | **0.980** | 98.9% |

The same person **as a photograph**, against 48 whole-upright photographs within
±15% of their apparent size: **0.984 / 0.986 / 0.989**, the **43.8th / 43.8th /
54.2nd percentile**. An entirely ordinary photograph.

And the same image both ways, which for people needs no invented surround at all
because the eye line reaches 107.8 px at **1.44 m**, inside the flown band
(`tables/same_image.tsv`):

| arm | photo | render, clean | d | photo/himax | render/himax | d |
|---|---|---|---|---|---|---|
| float | 0.984 | 0.996 | +0.012 | 0.993 | 0.999 | +0.006 |
| fq | 0.986 | 0.996 | +0.010 | 0.995 | 0.999 | +0.005 |
| chip | 0.989 | 0.997 | +0.008 | 0.997 | 0.999 | +0.002 |

For *this* subject the renderer is almost exactly a no-op - the one case in 204
where the compression does not bite. That is what makes it a 99th-percentile
card. (This is the measurement the pet study wanted and could not have: its dog
capped at 51.9 px against a 120 px photograph, and the three paddings it tried to
bridge the gap disagreed by 0.86.)

### (f) Is it the camera model?

**No.** Split raw photograph -> +244 resample -> +resample+sensor, on the same
photographs, flown band (`tables/camera_decomposition.tsv`), fraction >= 0.75:

| arm | stratum | n | raw | +244 | +244+sensor | resample part | sensor part |
|---|---|---|---|---|---|---|---|
| float | all | 1261 | 0.696 | 0.686 | 0.536 | -0.010 | -0.150 |
| fq | all | 1261 | 0.687 | 0.672 | 0.505 | -0.014 | -0.168 |
| **chip** | all | 1261 | 0.551 | 0.704 | 0.581 | **+0.153** | -0.123 |
| float | whole_upright | 136 | 0.794 | 0.787 | 0.667 | -0.007 | -0.120 |
| fq | whole_upright | 136 | 0.787 | 0.787 | 0.610 | +0.000 | -0.177 |
| **chip** | whole_upright | 136 | 0.610 | 0.765 | 0.735 | **+0.154** | -0.029 |
| chip | wui | 37 | 0.405 | 0.514 | 0.640 | +0.108 | **+0.126** |

The sensor model moves real photographs' above-bar rate DOWN in 8 of the 9
stratum x arm cells, by 0.03 to 0.18 - it makes real people harder, not easier -
and UP in one (chip, `wui`, n = 37). Nothing there is the size of the gap in (b)
or (c), and the same sensor model is applied to the sim side in every number
above. As in the pet study, the resample part on `chip` is the large one and is
exactly what §2's control removes.

---

## 5. Verdict

**The simulator OVERSTATES how detectable a person is, and it does so through
subject selection rather than through the rendering.**

At the apparent sizes the follower holds station at, the flown card clears the
0.75 confirmation bar on **100.0%** of frames and never - 0 of 282 frames across
34 poses, three sensor seeds and three networks - falls below the 0.45 exit bar.
Real people at the same apparent size, through the same resampling chain, clear
0.75 on **47.6-80.2%** and fall below 0.45 on **4.9-19.0%**, depending on which
real stratum and which arm you take as the right analogue (over the wider flown
band, below-exit runs 7.4-21.6%). Size-standardised over the whole flown
band the above-bar ratio is **1.27x to 1.95x**; the below-exit ratio is **0.000
against 0.085-0.227**, which has no finite ratio and is the finding.

The mechanism is not that cards flatter. Rendering the average real person
**lowers** their score (chain-matched paired median **-0.169 [-0.237, -0.109]**
with neither side through the sensor model and **-0.130 [-0.179, -0.078]** with
both sides through it, chip, at matched size; on the isolated subset
**-0.076 [-0.123, -0.032]** and **-0.050 [-0.113, +0.018]**, the latter
crossing zero). What the
renderer does is compress the confidence scale toward ~0.6, slope **-0.792
[-0.941, -0.651]**. The flown cells read high because their one cutout happens to
land at the **98.5th to 100th percentile** of that compression, while being an
ordinary **43.8th-54.2nd percentile** photograph.

### What that means for the published flight results

* **The 0.97-0.99 person tracking fractions are a property of COCO 19432, not of
  the perception system.** `A.static__ships` 0.9905, `B.moving__ships` 0.992,
  `A.static__proven` 0.996, `B.moving__proven` 0.982 - and the three
  `B.moving__delta_*` cells at 0.917-0.996 - are correctly measured; they are
  measurements of the simulator and internally valid. What changes is
  the inference from them to hardware. "The drone tracks a person 99% of the
  time" needs the qualifier "in simulation, against one flat card that renders in
  the top 1-2% of people".
* **Expect track drops on hardware far more often than the flight results
  suggest** - though "the simulator has never shown one" is too strong, and this
  directory said it. `scoreboard.json` records `A.static__ships` as a MEDIAN of
  four repeats, 0.9905, with spread **[0.829, 0.991]**: repeat `r4a1` tracked
  82.9% of the time and is marked `would_pass: false` against the provisional
  0.9 threshold. What this directory measured is narrower and still holds - in
  **282 static frames** the card's confidence never goes below 0.45. The
  follower lets go below 0.45 and needs three fresh frames at 0.75 to resume. The
  simulator supplies a subject whose per-frame probability of being under 0.45 is
  **0.000**; real whole, upright, unoccluded people at the same apparent size are
  under it on **7-14%** of photographs, and isolated ones on **19-22%**. A
  per-frame drop rate anywhere in that range, with a 3-frame re-confirmation,
  will produce visible loss-of-track that no `M1_tracking_fraction` in the
  baseline predicts. **How much** is not measured here: these are static frames
  with no temporal correlation, and consecutive video frames of one person are
  strongly correlated, so per-frame rates do not multiply out into a flight.
  Section 6 says what would measure it.
* **The pet gate story and this one now share a mechanism, which raises the
  priority of both.** The pet study said "stop tuning follower thresholds against
  s03, you are tuning against a card". This says the same about the person cells
  for the opposite reason. A threshold fitted to a simulator whose confidence
  scale is compressed toward 0.6 will be fitted to the wrong spread at both ends:
  too permissive on pets, too forgiving on people.
* **What is cheap and worth doing before the lab session.** (i) Re-render s15 and
  s01 with a cutout nearer the cohort **median** instead of the 99th percentile,
  or better, with several - the harness already takes a scene definition, and
  `sim_render_cohort.py` leaves 204 qualifying candidates with their own scores
  in `tables/sim_cohort.csv`. That alone would move the person cells from "always
  above the bar" to something with failures in it. (ii) Report
  `M1_tracking_fraction` alongside the per-frame fraction below `vis_exit`, which
  the flight logs already contain, so a cell that never approaches the exit bar
  is visibly different from one that hovers at it.

### If someone wants the opposite headline, here is what would have to be true

The gap would have to be (i) a resampling artefact - answered in §2, where the
control is a no-op on the sim side by construction and moves the real side the
*other* way; (ii) the camera model - answered in §4(f), where the sensor moves real
photographs down in 8 of 9 cells and is applied to the sim side too; (iii) an
artefact of which real photographs count as "a person the drone would follow" -
answered by giving four strata, whose above-bar rates at the hold band span
0.48-0.80 and every one of which sits below the sim's 1.000; or (iv) the size
measure - answered by matching both sides in `px128_h`, and by the same-image
pair at 1.44 m, which needs no size modelling at all.

The one place the finding is genuinely weak is (a): on **median confidence**
against raw photographs of whole upright people, the simulator is within noise
(9 of 12 intervals cross zero). Anyone quoting this directory should quote (b)
and (c), not (a).

---

## 6. What this does NOT establish

* **Nothing about hardware.** No frame here came from a camera. The real side is
  COCO photographs, which are not himax frames either; §4(f) models that gap but
  does not measure it.
* **Nothing about a flight.** Static frames only: no motion blur, no follower
  state machine, no 3-frame confirmation, no hysteresis, no temporal correlation
  between frames. "Fraction of frames below the exit bar" is **not** "fraction of
  a flight spent un-tracked", and because consecutive frames of one person are
  highly correlated the per-frame numbers here cannot be turned into a flight
  number by arithmetic. The measurement that would close this is a flight:
  re-run the person cells with a median-scoring cutout and read
  `M1_tracking_fraction` off the harness.
* **Pose and context are matched only in the strata that say so.** The
  `all_people` comparison matches size alone. `whole_upright` and `wui` match
  whole-body visibility, uprightness, truncation and (for `wui`) isolation, using
  COCO's own keypoint visibility flags - but not lighting, clothing, background
  clutter, viewing azimuth, or distance-to-camera in the original photograph. The
  paired cohort matches identity and pose exactly and is the strongest control
  here, but it compares a photograph against a *card of that photograph*, which
  is the thing under test.
* **n is small in the isolated stratum**: 59 photographs, 21 of them in the hold
  band. It is the closest analogue to the drone's scene and it is the noisiest
  set here; `whole_upright` (204) and `all_people` (2692) carry the weight, and
  all three agree in sign on (b) and (c).
* **One subject for the flown cells, and one build per job.** Both person cells
  use the same cutout, so the "sim cells" side is 34 poses of ONE person, not a
  distribution over people. That is the finding, but it also means the sim side's
  spread is a pose-and-sensor spread only.
* **The cohort's height is a fiction for everyone.** Every cohort subject is
  rendered 1.7 m tall, because that is what the scene definition assigns a person
  regardless of who it is. Apparent size is matched; real-world height is not.
* **Frontal cards only, 0-30 deg azimuth**, as in the pet study. The 2026-09-13
  range sweep shows confidence collapses past ~40 deg, which would lower the sim
  side further and strengthen the verdict's direction.
* **The `occluded_or_truncated` stratum is reported but not interrogated.** It is
  2 488 photographs and its rates sit close to `all_people`; nothing here
  separates "occluded" from "truncated" within it.
* **The cohort renders every subject at one scene position** (s15's x = 3.5),
  while the flown-cells job uses both 3.5 and 3.0. The pet study measured up to
  0.13 of confidence from panel position alone, so a single position understates
  the cohort's spread.

---

## 7. Files, and how to re-run

```
scripts/shared_arms.py          loads the PET study's champion_arms.py - one
                                scoring path on disk, not a copy - plus the
                                stratum-relabel join
scripts/real_people.py          real side: the 2 693-image slice, apparent size,
                                the four strata, 3 arms x 2 resampling chains
scripts/real_people_himax.py    real side through camera_model.himax_typical
scripts/sim_render_person.py    sim side: the s15 + s01 person cells (trainenv)
scripts/sim_render_cohort.py    sim side: 267 real people as cards (trainenv)
scripts/sim_score_person.py     scores any rendered set with shared_arms
scripts/control_resolution.py   THE CONTROL - run it first
scripts/analyze_person.py       the comparison, tables, the verdict's numbers
scripts/subject_selection.py    the outlier rank and the compression regression
scripts/make_figures.py         the four figures
scripts/audit_paired_chain.py   AUDIT ADDENDUM: the paired test with the
                                sensor stage matched on both sides, three ways
scripts/verify_readme_numbers.py  re-derives every number quoted in this README
                                from the tables and fails on any that drifted:
                                295 scalar claims, 8 structural ones

tables/real_people.csv          2 693 rows: size, strata flags, 6 confidence cols
tables/real_people_himax.csv    8 079 rows: 2 693 photographs x 3 sensor draws
tables/sim_person_render.csv    600 frames: geometry + build_scene's own score
tables/sim_person.csv           the same frames scored by all three arms
tables/sim_cohort_render.csv    11 214 frames: 267 subjects x 7 ranges x 2 offsets
tables/sim_cohort.csv           the same frames scored by all three arms
tables/control_resolution.tsv   the control, both halves, with CIs
tables/size_response.tsv        confidence vs size, every group x arm x chain x bin
tables/matched_gap.tsv          sim minus real, 84 cells, cluster-bootstrap CIs
tables/hold_band.tsv            the 63-100 px band, three cuts
tables/size_standardised.tsv    the flown band with the size mix held equal
tables/exit_bar.tsv             the 0.45 crossing rate, every group
tables/paired_render.tsv        the same human photographed and rendered
tables/paired_chain_matched.tsv the same, with the sensor chain matched too
tables/camera_decomposition.tsv raw -> +244 -> +244+sensor
tables/subject_selection.tsv    where COCO 19432 ranks, rendered and photographed
tables/regression_to_middle.tsv the compression slope and its buckets
tables/same_image.tsv           the sim's own person both ways at 1.44 m
tables/analysis.txt             the full printed analysis
tables/control_resolution.txt   the full printed control
tables/subject_selection.txt    the full printed subject/compression analysis
code_hashes.txt                 sha256 of the tooling as imported
figures/conf_vs_size_person.png, bars_vs_size_chip.png,
figures/paired_render_vs_photo.png, what_the_net_sees.png
logs/*.log                      run logs (see the note below)
```

Re-run, in order (absolute paths; `$D` is this directory, `$F` a scratch dir):

```
../nemoenv/bin/python  $D/scripts/real_people.py       $D/tables/real_people.csv
../nemoenv/bin/python  $D/scripts/real_people_himax.py $D/tables/real_people.csv \
                                                       $D/tables/real_people_himax.csv \
                                                       --stratum all_people
# take the simulator lock before these two:
../trainenv/bin/python $D/scripts/sim_render_person.py $F/frames  $D/tables/sim_person_render.csv
../trainenv/bin/python $D/scripts/sim_render_cohort.py $F/cohort  $D/tables/real_people.csv \
                                                       $D/tables/sim_cohort_render.csv \
                                                       --stratum whole_upright
# release the lock; the rest is CPU only:
../nemoenv/bin/python  $D/scripts/sim_score_person.py  $F/frames $D/tables/sim_person_render.csv \
                                                       $D/tables/sim_person.csv
../nemoenv/bin/python  $D/scripts/sim_score_person.py  $F/cohort $D/tables/sim_cohort_render.csv \
                                                       $D/tables/sim_cohort.csv
../nemoenv/bin/python  $D/scripts/control_resolution.py $D      # FIRST, before any comparison
../nemoenv/bin/python  $D/scripts/analyze_person.py     $D
../nemoenv/bin/python  $D/scripts/subject_selection.py  $D
../nemoenv/bin/python  $D/scripts/make_figures.py       $D $F/frames $F/cohort
../nemoenv/bin/python  $D/scripts/verify_readme_numbers.py $D   # must print ALL CLAIMS VERIFIED
```

Wall clock on this laptop: real side 4 min, himax arm 3.5 min, the two renders
21 s and 7 min (lock held), scoring 3 s and 75 s, analysis and figures under a
minute.

Note that `sim_render_cohort.py --stratum whole_upright` re-derives its subject
list from `real_people.csv`, so re-running `real_people.py` after a rule change
changes which subjects get rendered. The analysis does not depend on that: it
re-labels whatever was rendered from the current real table
(`shared_arms.relabel`).

The 11 814 rendered PNG frames are in scratch, not here: the repo's own rule is
that evidence folders keep the metrics, not the pictures (`.gitignore`, the
2026-09-12 note). Both render CSVs carry each frame's filename, geometry and
score, so re-rendering reproduces them.

**`logs/` needs `git add -f`.** `.gitignore` ignores the whole directory at
line 9 (`logs/`, which is what `git check-ignore -v` reports here) as well as
`*.log` at line 11, so all **11** files under `logs/` are ignored by default. A
forced add still stages them - `git add -n -f` lists all eleven:

```
git add -f docs/eval_results/2026-09-15-sim-person-fidelity/logs/*.log
```

They are `real_people.log`, `real_people_himax.log`, `sim_render_person.log`,
`sim_render_cohort.log`, `sim_score_person.log`, `sim_score_cohort.log`,
`control_resolution.log`, `analyze_person.log`, `subject_selection.log`,
`make_figures.log` and `verify_readme_numbers.log`. Nothing else in this directory is ignored: `git status
--ignored` lists only `logs/` (and a `__pycache__/`, removed). `tables/` is
`tables`, not `data`, so the anchored `/data/` rule at line 4 does not apply, and
no `*.pth`, `*.onnx`, `cache/` or `snap_*.png` is written here. A plain
`git add` on this directory stages 37 files; the 11 logs need the `-f`.

---

## 8. Audit note - what an independent re-measurement changed (2026-09-14)

Everything below was re-derived from scratch, not read out of this directory's
own tables, in `/private/tmp/.../scratchpad/audit/`. Nothing was committed.

**Reproduced exactly, independently:**

* The real-image selection. Re-implemented from `instances_val2017.json` +
  `person_keypoints_val2017.json` without importing `real_people.py`:
  **2 693 / 204 / 59 / 2 489** (the last is 2 488 once the sim source is
  dropped), and **0 row mismatches** against `tables/real_people.csv` on
  subject annotation id, `px128_h`, `whole_upright` and `wui`.
* The scores. Re-scoring 40 random photographs and all 600 person-cell frames
  through a freshly loaded `Arms` reproduces the CSVs to **max |mine - csv| =
  5e-05** on all six columns (the tables are rounded to 4 dp).
* **The control, on the chip arm.** Re-measured with an independent bootstrap:
  chip **+0.129 [+0.114, +0.144]** whole slice, **+0.153 [+0.130, +0.176]**
  flown band, **+0.191 [+0.127, +0.255]** `whole_upright`, **+0.186
  [+0.102, +0.288]** `wui`; float -0.008 to +0.034, fq -0.014 to +0.000;
  below-exit 0.261 -> 0.157 on chip. Every figure in §2 stands, and the
  direction (it shrinks the sim's advantage) stands.
* The exit bar. Sim cells through himax: **0 frames below 0.45** out of 300 in
  the flown band on all three arms (min score 0.668 on chip). Real:
  0.142/0.150/0.119 all people, 0.088/0.081/0.074 `whole_upright`,
  0.216/0.189/0.189 `wui`, 0.120/0.142/0.113 `whole_upright` through himax.
* The interval structure: `d_median` positive in 45 of 48 with 18 crossing zero;
  `d_frac` positive in all 48 with **0** crossing, range +0.154 to +0.709;
  `d_exit` negative in all 48 with 31 excluding zero. `verify_readme_numbers.py`
  passes 295/295 scalar and 8/8 structural claims, and the three tool hashes
  match `tools/crazysim_macos/` on disk.
* The outlier. COCO 19432 ranks **96.1-100th** percentile of the cohort at every
  range, on every arm, under both `clean` and `himax` - and **43.8 / 43.8 /
  54.2nd** percentile as a photograph. The headline (subject selection, not
  rendering) is the best-supported claim in this directory.

**Corrected here:**

1. **The paired test travelled through different sensor chains.** Render through
   `himax_typical`, photograph not. Matched, the headline moves from -0.209 to
   **-0.169** (neither side) or **-0.130** (both sides), and on `wui` the
   himax/himax interval **crosses zero**. §0, §4(d) and §5 now quote the matched
   numbers; `scripts/audit_paired_chain.py` and
   `tables/paired_chain_matched.tsv` are new.
2. **The sim-side "bit-exact no-op" was a tautology presented as a test.** PIL's
   resize to an image's own size is the identity and a rendered crop is already
   244 px, so the check could not have failed. §0 and §2 now say so.
3. **"Track drops the simulator has never shown" is contradicted by the
   simulator's own flight logs.** `A.static__ships` is a median of four repeats
   with spread [0.829, 0.991]; repeat `r4a1` tracked 82.9% and fails the
   provisional M1 gate. The static-frame finding (0 of 282 frames below the exit
   bar) is unaffected; the sweeping sentence in §5 was.
4. **The compression slope needs its null.** Permuting render scores across
   subjects gives slope -1.003 and fixed point 0.638; the observed -0.792 /
   0.585 sits between that and zero, on beta = +0.208 and r = +0.194. The effect
   is real but is closer to "the render discards the photograph's signal" than
   to a tidy compression, and its cross-study prediction (+0.226 for a 0.30
   photograph) under-shoots the pet study's +0.26 to +0.52. §4(d) now states it.

**Left standing, with their existing caveats:** the (b) and (c) separations, the
hold-band table, the size-standardised ratios, and the verdict
`SIM_OVERSTATES_PEOPLE`. Two limits worth repeating at the top of any
presentation: the sim side's below-exit CI is degenerate because **n = 1
subject**, so `[0.000, 0.000]` is a within-subject interval and says nothing
about people in general; and a randomly chosen rendered person is *worse* than
their own photograph (cohort below-exit 0.397 against real 0.119), so the
simulator only "deletes the failures" for the cutout that was picked.
