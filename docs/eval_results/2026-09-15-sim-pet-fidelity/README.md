# Does the simulated pet predict a real pet? Confidence versus apparent size, sim against COCO

**Nothing here was measured on hardware and nothing here flew.** No simulator
process, no control loop, no firmware, no UDP, no GAP8. The sim side is 1 116
offscreen MuJoCo renders of the repo's own `s03_pets_only` subjects; the real
side is the 771 COCO val2017 photographs of `export/confuser_slice_eval.py`'s own
confuser slice. The "chip" network is the champion's `model_id_dory.onnx` run
under onnxruntime 1.19.2 in doryenv, not on a GAP8.

**The question.** The champion chases the s03 dog in the simulator and drifts
past the 0.5 m pet gate on 2 of 4 fresh repeats at the shipping bar
(`docs/eval_results/2026-09-14-baseline-075/`). Neither follower threshold nor a
hard-negative fine-tune closed it. Before more days go into the pet problem:
does the SIMULATED dog predict a REAL dog at all?

---

## 0a. CORRECTIONS (skeptic re-derivation, second pass, 2026-09-14)

This folder was re-derived independently before being trusted. **What
reproduced exactly** (details in section 1a): the 771-image slice, image for
image (symmetric difference 0); every `px128_h` on the real side recomputed
from the raw annotations (max difference 0.005 px); the whole-slice float
figures 0.270/0.175/0.082 through the repo's *own* val-transform dataset path
rather than `champion_arms`' hand-rolled crop (max difference 5.0e-05 on all
771); all 1 116 rendered frames re-scored through that same independent path
(max difference 5.0e-05); and every matched-size median gap in
`tables/matched_gap.tsv`.

**Five things did not survive, and are corrected below and in the body.**
Regenerate all of them with
`nemoenv/bin/python scripts/verify_resampling_chip.py .` ->
`tables/verify_resampling_chip.txt`, `tables/chip_resampling_correction.tsv`.

**1. The chip arm's two sides were not resolution-matched.** This is the one
that moves a headline. `perception_backends.firmware_preprocess` is the C port:
nearest-neighbour source sampling plus a 2x2 box average, integer arithmetic,
**no antialiasing**. A rendered frame reaches it as a 244-px crop (stride
244/128 = 1.9, so the 2x2 block covers nearly every source pixel). A COCO
photograph reaches it as a 480-640-px crop (stride 3.75+, so the block samples
about a quarter of the pixels and aliases the rest away). Same network, same
0.75 bar, **different input chain** - the same class of error as comparing two
thresholds. `float` and `fq` are unaffected, because their preprocessing is PIL
BILINEAR, which antialiases at any input resolution; that is why validating the
control on `float` alone ("the resampling chain is not a confound: 0.270 ->
0.261") licensed nothing about `chip`.

The control was already in the CSVs and was not propagated: `chip_via244` puts
the photograph through the frame's own chain first. On the **sim** side `chip`
and `chip_via244` are bit-identical (max difference 0.0000 over all 1 116
frames), because a rendered frame is natively a 244 crop - so pairing sim
`chip` with real `chip_via244` changes only the real side's chain, and is the
apples-to-apples pairing. Raw `chip` on a 640-px photograph corresponds to
nothing the drone can ever see.

| chip arm, fraction >= 0.75 | as published | resolution-matched |
|---|---|---|
| whole slice, n=771 | 0.069 | **0.096** |
| real pets at drone-visible sizes 14.7-51.9 px, n=193 | 0.041 | **0.104** |
| real dogs at 14.7-51.9 px, n=17 | 0.000 | **0.176** |
| real pets in the latch band 22-32 px, n=54 | 0.074 | **0.148** |
| real dogs in the latch band, n=6 | 0.000 | **0.167** |
| size-standardised vs all pets -> ratio | 0.039 -> **7.21x** | 0.097 -> **2.90x**, 95% CI [1.70, 5.42] |
| size-standardised vs dogs only -> ratio | 0.000 -> **infinity** | 0.206 -> **2.48x**, 95% CI [1.08, 13.06] |

So `"chip: 28.2% of rendered frames vs 3.9% of real pets"` is **28.2% vs 9.7%**,
and `"real dogs at that size never clear it (0.511 against 0.000)"` is **0.511
against 0.206** - real dogs of that apparent size clear the bar about a fifth of
the time on the chip arm once it sees them at the resolution it flies at. The
sim still overstates on chip; it overstates by ~2.5-2.9x, not by 7.2x or by
infinity.

**2. Section (b)'s camera-model decomposition is wrong on chip.** "Putting the
245 dog and cat photographs through `himax_typical` moves their rate above the
bar by ... chip 0.114 -> 0.143 ... What the sim adds is the card and the room,
not the sensor." But `real_pets_himax.py` resizes the crop to 244 **before** the
sensor model, so that arm carries resampling *and* sensor. Split:

| arm | raw photo | + 244 resample | + resample + sensor | resample part | sensor part |
|---|---|---|---|---|---|
| float | 0.147 | 0.131 | 0.105 | -0.016 | -0.026 |
| fq | 0.118 | 0.114 | 0.086 | -0.004 | -0.029 |
| **chip** | 0.114 | **0.163** | 0.143 | **+0.049** | -0.020 |

On chip the sensor moves it *down* 0.020 and the resampling moves it *up* 0.049.
The conclusion ("the camera model is not the explanation for the gap") survives
on all three arms; the arithmetic behind it did not.

**3. The latch band is an AND of two filters, not one band stated two ways.**
"2.0-2.75 m = 22-32 px128_h" reads as an identity. The sim side that produced
57.4% is `range_m in [2.0, 2.75]` **and** `px128_h in [22, 32]`, which drops the
two poses at r=2.75, dy=+/-0.25 (px128_h 21.51) - the smallest and lowest-scoring
poses in the band. Same 0.75 bar, same real side, three ways of cutting the sim:

| sim cut | n frames / poses | float | fq | chip |
|---|---|---|---|---|
| range 2.0-2.75 **and** px 22-32 (as published) | 54 / 18 | 0.593 | 0.611 | **0.574** |
| range 2.0-2.75 only | 60 / 20 | 0.533 | 0.567 | 0.517 |
| px 22-32 only | 66 / 22 | 0.485 | 0.500 | 0.470 |

Matching on size is the right thing to do and the real side is cut the same way,
so the published row is defensible - but 57.4% is the top of a 47-57% range, and
the label should say the filter is an AND. Note also that n=54 is 18 clusters,
not 54 independent observations.

**4. The spread is wider than "all three networks, both cameras, both
comparison sets" suggests, and one of the misses is the decision-relevant cell.**
Every one of the 30 dog cells in `tables/matched_gap.tsv` has a positive point
estimate (`d_median` from +0.073 to +0.522), which is genuine and is the main
reason to believe the verdict. But of the 24 primary cells (`sim_dog_eye_himax`),
**4 of 24 `d_median` intervals and 8 of 24 `d_frac` intervals cross zero**:

| cell | `d_median` | `d_frac` |
|---|---|---|
| **chip, 25-40 px, himax both sides** | +0.223 **[-0.074, +0.503]** | +0.214 **[-0.196, +0.580]** |
| float, 25-40 px, vs raw dogs | +0.269 [+0.005, +0.355] | +0.400 **[-0.011, +0.759]** |
| float / fq / chip, 8-15 and 15-25 px, vs all pets | 3 of 6 cross | 6 of 6 cross |

The first row is the flown arm, at the flown size, with the camera model on both
sides - the closest single cell to the actual decision - and there the
overstatement is **not** established on its own. What carries the finding is the
40-55 px bin (every interval excludes zero on every arm and every comparison
set), the 771-pet comparison set at 25-55 px, and the consistency of the sign
across all 30 cells. "Direction is the same on all three networks, both cameras,
both comparison sets" is true of the point estimates and should not be read as
true of the intervals. Below 25 px the two sides are not distinguishable at all,
which is consistent with the sim's own response curve only rising past ~20 px.

**5. The cat "same image both ways" row is undetermined, and this folder states
it two contradictory ways.** `cat_petlevel` reports `px128_h = 128.0` at **both**
0.25 m and 0.28 m, because the panel overflows the centre crop and the measure
saturates - they are not the same picture (`visible_fraction` 0.875 vs 0.980).
`analyze.py`'s tie-break takes 0.28 m, `analyze_same_image.py`'s takes 0.25 m, so
`tables/same_image.tsv` and `tables/same_image_summary.tsv` disagree on the same
row:

| cat 131938, clean, render minus photo | float | fq | chip |
|---|---|---|---|
| 0.25 m render (`same_image_summary.tsv`, quoted in the body) | +0.066 | +0.054 | +0.212 |
| 0.28 m render (`same_image.tsv`) | -0.263 | -0.272 | +0.045 |

The sign flips on two of three arms. **The cat same-image comparison should be
read as undetermined**, not as "clean +0.05 to +0.21". The *dog* pair is not
affected and remains the folder's best single measurement: `dog_petlevel` at
0.50 m gives `px128_h` 119.61 against the photograph's 119.91, with
`visible_fraction` 1.007 and `touches_frame_edge` 0 - one unambiguous pair.

**What did NOT change.** The verdict `SIM_OVERSTATES` stands for the dog: the
sign is the same in every one of the 24 dog cells, the float and fq
size-standardised ratios are untouched by all of the above (3.95x / 4.36x vs all
pets; 3.10x / 5.57x vs dogs), the median gaps are untouched, the published
confuser figure still reproduces exactly, and the "stop tuning follower
thresholds against s03" implication is unaffected. What changed is the size of
the claim on the arm that flies, and the confidence with which "real dogs never
clear it" can be said - they do, about one photograph in five.

---

## 0. TL;DR

| claim | verdict |
|---|---|
| Sim and real can be compared at all | **yes, but only over 15-52 px of apparent size.** Both sides are measured in the same unit - the subject's height in the 128x128 network input (`px128_h`) - and the flown camera geometry caps the sim dog at **51.9 px** while real pet photographs run to 128 px (dog median **80.7**) |
| **(a)** At matched apparent size, is the sim dog detected more confidently than real dogs? | **Yes, by a lot, and the gap grows with size.** In the 25-40 px bin, sim minus real median confidence is **+0.34 [+0.04, +0.43]** (fq arm, sim himax vs raw dog photo); in 40-55 px, **+0.52 [+0.09, +0.71]**. Against all 771 real pets rather than the 93 dogs: **+0.46 [+0.39, +0.57]** and **+0.51 [+0.43, +0.65]** |
| **(b)** Does the fraction above the shipped 0.75 bar differ at matched size? | **Yes, but by less than first written - see CORRECTIONS.** In the dog's latch band (`range 2.0-2.75 m` AND `px128_h 22-32`), the sim dog is at or above 0.75 on **57.4%** of frames (chip, himax); real dog photographs at the same size on **16.7%** (1/6) and real pets of any species on **14.8%** (8/54), both put through the frame's own 244-px resampling chain so the chip arm sees them the way it sees a render. Size-standardised over the whole flown band, **3.0x to 4.7x** (chip **2.9x**, 95% CI [1.7, 5.4]) |
| **(c)** Is the sim dog representative of real dogs, or one unusually detectable animal? | **Both, and the rendering is the larger half.** As a photograph, COCO 297830 sits at the **74th percentile** of real dogs at its own size (fq) - more person-like than typical, not an outlier. As a *render* at flown sizes its median frame sits at the **86th-100th percentile** of that same distribution on float and fq, **71st-90th** on chip |
| **(d)** The s03 cat | **The sim understates it, mildly.** The rendered cat never reaches 0.75 anywhere in the flown band (0 of 195 frames, all three arms), while real cat photographs at the same apparent sizes clear it on **6.2%** of images (1 of 16) raw and 0-16.7% of draws through himax. The scene note "below the bar everywhere" is right about the sim and slightly pessimistic about reality |
| **VERDICT** | **The simulator OVERSTATES the pet false-follow problem.** For the dog, at matched apparent size, by **+0.22 to +0.52 in median confidence** and by a factor of **2.5x to 8.2x in the rate above the confirmation bar**, depending on which arm and which comparison set - the sign is positive in **all 30** dog cells of `tables/matched_gap.tsv` but the interval excludes zero in only 20 of the 24 primary cells for the median and 16 of 24 for the above-bar fraction, the chip arm at 25-40 px with himax on both sides being among the misses (see CORRECTIONS 4) |
| Is the published real-image 30% figure in doubt? | **No.** `fq` reproduces it exactly: **0.239 @0.45, 0.171 @0.55, n=771**. What is in doubt is the simulator's rendering of it |
| What the gap does NOT separate | **pose and context.** Only SIZE is matched. The card is upright, isolated, front-facing against a plain wall; real dogs at 25-48 px are mostly incidental, cluttered, often lying down (`figures/what_the_net_sees.png`). An upright isolated real dog at 2 m is not in COCO at that apparent size, so it was not measured. The nearest handle: real dogs at 80-129 px - isolated, deliberately framed portraits - still clear the bar on only **17-21%** of photographs |
| Does the "same image both ways" settle it? | **Only outside the flight band, and only for the dog.** The sim's dog IS COCO 297830, so the identical picture was measured both ways - at the photograph's own framing (120 px), where the render reads **0.17-0.30 LOWER** than the photograph. Inside the flown band the photograph has to be given a surround it does not contain, and the three fillings tried disagree by up to **0.86**, which is larger than the effect: reported, not used. The **cat** pair is undetermined - both candidate renders report the saturated `px128_h = 128.0` and they disagree in sign (section 0a.5) |

The honest one-line version: *at the sizes the drone actually sees it, the
cardboard dog is a better person than the real dogs COCO has at that size -
roughly 2.5 to 8 times more likely to clear the bar that makes the drone chase,
the wide range being real and driven by which network arm and which comparison
set you pick - so the s03 flight results measure the rendering at least as much
as a perception defect, and tuning the follower against them is tuning against
a card.*

---

## 1. The discipline: what was pinned, and what reproduced

Everything below was produced by importing the repo's own unmodified tooling.
`git status` on `tools/`, `docs/sim_results/` and the existing `docs/eval_results/`
directories is clean; the repo sat at `ee601f8` throughout, nothing was committed
or pushed, and the only new path is this directory.

**The tooling is byte-identical to the suite that flew the 0.75 baseline**
(`code_hashes.txt` here vs `2026-09-14-baseline-075/code_hashes_after.txt`):

```
ea639fea...  tools/crazysim_macos/build_scene.py      same bytes as the 0.75 baseline
481c0a99...  tools/crazysim_macos/camera_model.py     same bytes as the 0.75 baseline
8281df9f...  tools/crazysim_macos/follow_person.py    same bytes as the 0.75 baseline
ce917647...  tools/crazysim_macos/perception_backends.py
e0d7cbe5...  tools/crazysim_macos/scoreboard.py       differs (the ee601f8 scorer fix); NOT used here
```

Three independent reproductions, each of which would have invalidated this
directory had it failed:

1. **The published real-image figure, exactly.** `export/confuser_slice_eval.py`
   on `artifacts/successor_qat_ep3.pth` prints
   `0.239 @0.45, 0.171 @0.55 (n=771)` - the EXPERIMENTS.md number to three
   decimals (`logs/confuser_repro_qat_ep3.log`). My own real-side script,
   written independently, gives the same 0.239 / 0.171 on the same 771 images
   (`logs/real_pets.log`). *Note for the record:* the same script on
   `successor_qat_ep3_eval.pth` - the float export the simulator runs - gives
   **0.258 / 0.184** under rep-image calibration, so the two artefacts are not
   interchangeable and both are reported separately throughout.
2. **The published scene notes, exactly.** Rebuilding the 2026-09-14 probe's own
   geometry (subject at x = 3.5 m) reproduces the dog's
   `float/clean 0.926 / 0.869 / 0.526` at 1.5 / 2.5 / 3.5 m and the cat's
   `0.390 / 0.687 / 0.299` - the scene-def note says 0.926/0.869/0.526 and
   0.390/0.687/0.300 (`tables/sim_pets.csv`, jobs `dog_notes` / `cat_notes`).
3. **The scoring path is the repo's own.** Every rendered frame was scored twice
   - once by `build_scene.run_model` at render time, once by this directory's
   `champion_arms.py` after a PNG round-trip. Maximum disagreement over 1 116
   frames: **0.00e+00** (`logs/sim_score.log`).

One sensitivity found while doing this, worth recording: **the same card at the
same range scores differently depending on where it stands in the room.** With
the dog panel at x = 4.0 m instead of the notes' 3.5 m, float/clean at
1.5 / 2.5 / 3.5 m becomes 0.885 / 0.740 / 0.607 rather than 0.926 / 0.869 / 0.526
- up to 0.13 - because `build_scene` paints each panel's background from the
geometry behind it. Every sim number here therefore comes from one build per
subject, stated in the tables.

---

### 1a. Independent re-derivation (second pass, 2026-09-14)

Re-derived from scratch, not by re-running this folder's own scripts:

| what | how | result |
|---|---|---|
| the 771-image slice | rebuilt from `instances_val2017.json` alone: val2017 images with no `category_id` 1 and at least one of {16..25, 88} | **n = 771, symmetric difference 0** against `tables/real_pets.csv`. 5 000 val2017 images, 48 with no annotations, 0 confuser images whose every confuser annotation is `iscrowd` - the slice is not an arbitrary choice, it is the only set those two predicates admit |
| every real `px128_h` | recomputed from the raw bboxes: `crop = min(W,H)`, clamp the box to the crop, scale by `128/crop` | max difference **0.005 px** over 771; **0** subject-annotation mismatches. Bin counts reproduce exactly: 193 pets at 14.7-51.9 px, 79 at 25-40, 91 at 40-55; 93 dogs, 17 / 7 / 10 |
| is `px128_h` the SAME quantity on both sides? | traced `build_scene.make_cutout`: the panel texture is the annotation bbox crop `rgb[y:y+h, x:x+w]` and the panel spans world z from 0 to `height_m`, so the segmented panel height **is** the animal's bbox height. Cross-checked the segmentation against pure geometry `h * FOCAL_PX / r * 128/244` | seg/geom ratio median **0.994-1.005** on every job. Both sides are the subject's bbox height in units of the 128-px input. **No apples-to-oranges in the size measure** |
| the real-side scores | re-scored all 771 through the repo's *own* val-transform dataset path (`COCOFollowRegressionDataset` + `get_val_transforms`), not `champion_arms`' hand-rolled PIL crop | max difference **5.0e-05**; whole-slice float 0.270 / 0.175 / 0.082 reproduced digit for digit |
| the sim-side scores | re-scored all 1 116 written PNGs through `utils.transforms.CenterCropSquare` + `ResizeImage` | max difference **5.0e-05** |
| the matched-size gaps | recomputed the 25-40 and 40-55 px medians | +0.269 / +0.338 / +0.257 and +0.508 / +0.522 / +0.521 - exact |
| the latch band | reproduced 0.783/0.593, 0.794/0.611, 0.766/0.574 | exact, but **only** under `range AND size` (section 0a.3) |
| `chip` vs `chip_via244` on the sim | | **bit-identical**, max difference 0.0000 over 1 116 frames - which is what makes `chip_via244` the right real-side pairing (section 0a.1) |

`tables/headline_numbers.txt` has no generating script in `scripts/`; its
sections C and E carry the uncorrected chip figures. `tables/verify_resampling_chip.txt`
supersedes them for the chip arm.

---

## 2. Apparent size, and why everything is grouped by it

A sim range and a COCO photograph are only comparable at the same subtended
size. Both sides go through the same two operations - centre square crop, then
resize to 128x128 (`utils/transforms.CenterCropSquare` + `ResizeImage`, which is
also exactly `build_scene.run_model`) - so the subject's height in that 128-px
input is a quantity both sides have:

* **real**: the COCO box, clamped by the centre crop, scaled by `128 / crop`.
  An image's subject is its largest confuser-category annotation.
* **sim**: MuJoCo segmentation of the subject's own panel geom, restricted to
  the centre square crop, times `128 / 244`. Measured per frame, not assumed;
  it agrees with the ideal geometry `h * f / r` to 1-3% wherever the subject is
  wholly in frame (`visible_fraction` column).

Both sides are the same thing for the same reason: `build_scene.make_cutout`
pastes the COCO annotation's own bounding-box crop onto the panel, so panel
height *is* box height.

### The first finding is geometric, and it is not small

The drone flies at 0.8 m with a level camera. A pet stands on the floor. Closing
in therefore pushes the pet out of the **bottom** of the frame instead of
filling it:

| | max px128_h reachable on the eye line | at what range | real photographs of that species |
|---|---|---|---|
| dog (0.65 m) | **51.9 px** | ~1.0-1.25 m | median **80.7**, p75 106.6, max 128 |
| cat (0.40 m) | **32.0 px** | ~1.25 m | median **78.9**, p75 98.2, max 128 |

**The published 0.239 confuser figure is dominated by subjects larger than
anything this drone can see.** Restricted to the sizes a 0.65 m dog can occupy
in this camera (14.7-51.9 px), the real slice's false-alarm rate is
`>=0.45: 0.275, >=0.75: 0.083` (fq, n=193) - close to the whole-slice number,
because the real rate is nearly flat in size (section 3). So the headline real
figure survives the restriction; it is the *sim* that does not behave like it.

---

## 3. Confidence versus apparent size

Median confidence [fraction at or above the shipped **0.75** bar], fq arm, raw
photographs on the real side and himax frames on the sim side (`tables/size_response.tsv`,
`tables/analysis.txt` section 1; the same table exists for float and chip):

| px128_h | real, any pet (n=771) | real, dog (n=93) | **sim dog, flown eye line** |
|---|---|---|---|
| 8-15 | 0.25 [0.07] n=30 | - (n=2) | 0.38 [0.00] n=15 |
| 15-25 | 0.30 [0.07] n=41 | - (n=2) | 0.48 [0.07] n=90 |
| 25-40 | 0.34 [0.10] n=79 | 0.46 [0.14] n=7 | **0.80 [0.72] n=54** |
| 40-55 | 0.28 [0.08] n=91 | 0.27 [0.10] n=10 | **0.79 [0.67] n=36** |
| 55-80 | 0.27 [0.06] n=166 | 0.38 [0.17] n=24 | out of reach |
| 80-129 | 0.25 [0.08] n=348 | 0.34 [0.17] n=47 | out of reach |

Real pets are **flat** in apparent size: median 0.25-0.34 and 6-17% above the
bar at every size from 8 px to 128 px. The rendered dog is not: it rises from
0.38 at 15 px to ~0.80 at 25-55 px, with two thirds of its frames above the bar
there.

Figures: `figures/conf_vs_size_dog.png`, `figures/conf_vs_size_cat.png`
(three arms each), `figures/frac_above_bar_chip.png`, and
`figures/what_the_net_sees.png` - the actual 128x128 inputs, three rendered and
five real, all at 24-48 px128_h, with their fq confidences. Look at that one
before reading section 4; it shows both the effect and its main confound.

---

## 4. The answers

### (a) At matched apparent size, is the simulated dog detected more confidently?

**Yes.** `tables/matched_gap.tsv`, `tables/analysis.txt` section 2. Sim minus
real median confidence, 95% cluster bootstrap (a photograph under 3 himax draws
is one photograph; a rendered pose under 3 sensor seeds is one pose):

| arm | comparison | 25-40 px | 40-55 px |
|---|---|---|---|
| float | sim himax vs raw dog photo | +0.27 [+0.01, +0.36] | +0.51 [+0.16, +0.70] |
| fq | sim himax vs raw dog photo | +0.34 [+0.04, +0.43] | +0.52 [+0.09, +0.71] |
| chip | sim himax vs raw dog photo | +0.26 [+0.12, +0.47] | +0.52 [+0.30, +0.67] |
| fq | sim himax vs dog photo through himax | +0.34 [+0.20, +0.65] | +0.51 [+0.19, +0.64] |
| fq | sim himax vs **all 771 real pets**, raw | +0.46 [+0.39, +0.57] | +0.51 [+0.43, +0.65] |

n per bin: 18 and 12 rendered poses against 7 and 10 real dog photographs, or 79
and 91 real pet photographs. The intervals are cluster bootstraps, so the real
side's n is photographs and not photograph-draws.

The gap is **+0.26 to +0.52 in median confidence**, it is not a point estimate,
and it is in the same direction on all three networks, both cameras, and against
both the 93-dog and the 771-pet comparison set. Restricting both sides to
subjects wholly inside the frame (section 2c of `analysis.txt`) leaves it
unchanged: **+0.26 to +0.55** against real dogs.

### (b) Does the fraction above the 0.75 confirmation bar differ at matched size?

**Yes, and this is the number that makes the drone chase.** In the band the
flown cell actually latches in - 2.0-2.75 m, which is 22-32 px128_h
(`tables/headline_numbers.txt` section C):

| arm | sim dog, eye line, himax | real dog photo, raw | real dog photo, himax | real pet, any species, raw |
|---|---|---|---|---|
| float | 0.783 med, **59.3%** >= 0.75 (n=54) | 0.512, 33.3% (n=6) | 0.439, 16.7% (n=6 imgs) | 0.291, 11.1% (n=54) |
| fq | 0.794 med, **61.1%** (n=54) | 0.446, 16.7% (n=6) | 0.392, 16.7% | 0.327, 9.3% (n=54) |
| **chip** (what `F.pets__ships` flies) | 0.766 med, **57.4%** (n=54) | 0.497, ~~0.0%~~ **16.7%** (n=6) | 0.440, 33.3% | 0.271, ~~7.4%~~ **14.8%** (n=54) |

> **TWO CORRECTIONS to this table - see sections 0a.1 and 0a.3.** (i) The chip
> row's raw-photo columns were not resolution-matched; they are re-quoted
> through the frame's own 244-px chain. float and fq are unaffected. (ii) "2.0-
> 2.75 m = 22-32 px128_h" is an **AND** of two filters, not one band named twice:
> it drops the two poses at r=2.75, dy=+/-0.25 (21.51 px). Cutting the sim by
> range alone gives 0.533 / 0.567 / 0.517 and by size alone 0.485 / 0.500 /
> 0.470, so 57.4% is the top of a 47-57% range. n=54 is **18 pose clusters**.

Size-standardised over the whole flown band - the sim's own size mix applied to
the real photographs, so neither side can win on its size distribution
(`tables/size_standardised.tsv`):

| arm | sim dog >= 0.75 | real pets >= 0.75, same size mix | ratio |
|---|---|---|---|
| float | 0.318 | 0.080 | **4.0x** |
| fq | 0.354 | 0.081 | **4.4x** |
| chip | 0.282 | ~~0.039~~ **0.097** | ~~7.2x~~ **2.9x** [1.7, 5.4] |

Against real *dogs* only - which restricts the standardisation to the two bins
that contain enough dog photographs, 25-55 px, so the sim's own rate there is
higher (0.656 / 0.700 / 0.511): **3.1x**, **5.6x**, and for chip ~~"real dogs at
that size never clear it" (0.511 against 0.000)~~ **0.511 against 0.206 = 2.5x
[1.1, 13.1]**.

> **CORRECTED - see section 0a.1.** The chip rows above were struck because
> their two sides were not resolution-matched: `firmware_preprocess` does not
> antialias, so it sees a 244-px render almost fully sampled and a 640-px
> photograph aliased. The real side is re-quoted through the frame's own 244-px
> chain (`chip_via244`), which is a no-op on the sim side. The float and fq rows
> are unaffected and stand as published. The full standardised table including
> the himax-on-both-sides rows (where chip is **2.42x**) is
> `tables/size_standardised.tsv`; the corrected chip rows with cluster-bootstrap
> intervals are `tables/chip_resampling_correction.tsv`.

**The camera model is not the explanation.** Putting the 245 real dog and cat
photographs through the same `himax_typical` model moves their rate above the
bar by float 0.147 -> 0.105, fq 0.118 -> 0.086, chip 0.114 -> 0.143 - down on two
arms, up on one, never by anything like a factor of 4. What the sim adds is the
card and the room, not the sensor.

> **CORRECTED - see section 0a.2.** That arm resizes the crop to 244 *before*
> the sensor model, so it carries resampling and sensor together. Split out, the
> sensor alone moves the rate by -0.026 / -0.029 / **-0.020** and the resampling
> alone by -0.016 / -0.004 / **+0.049**. The conclusion survives on all three
> arms - the sensor never moves it by anything like a factor of 4 - but on chip
> the +0.029 net was resampling, not the camera.

### (c) Is the sim dog representative of real dogs, or one unusually detectable animal?

**It is a somewhat-above-average dog photographed, and an extreme dog rendered.**

* As a photograph, COCO 297830 scores 0.523 / 0.552 / 0.783 (float / fq / chip)
  against 31 other real dog photographs within +/-15% of its own apparent size,
  whose median is 0.279 / 0.306 / 0.376. That puts it at the **74th / 74th /
  81st percentile** - more person-like than a typical dog photo, comfortably
  inside the distribution, not an outlier (`tables/same_image_analysis.txt` C).
* As a render at flown sizes, its median frame sits at the **86th percentile**
  (25-40 px) and the **100th percentile** (40-55 px) of real dogs at matched
  size on the float and fq arms, 71st and 90th on chip
  (`tables/analysis.txt` section 4).

So roughly: pick a more-detectable-than-average dog, then render it, and the
rendering moves it from the 74th percentile of real dogs to the 86th-100th.

### (d) The cat

**The simulator understates this one.** The rendered cat never reaches 0.75
anywhere in the flown band - 0 of 195 frames on every arm, median 0.34-0.41 -
while real cat photographs over the cat's own flown size range (8.9-32.0 px)
clear the bar on **6.2%** of photographs raw (1 of 16, the same on all three
arms) and on 0-16.7% of draws through himax. At matched size the cat's median
gap is +0.02 to +0.20 in the sim's favour, but its fraction-above-bar gap is
**zero or negative in every bin on every arm** (0.000 to -0.250), because the
sim cat never crosses.

The scene note's new claim - "the cat sits below the bar everywhere" - is
correct about the simulator. It is not a statement about real cats: one of the
16 real cat photographs at the sizes this drone would see a cat is above the
bar, and so are 4 of 109 real pet photographs of any species at those sizes.

---

## 5. The same image, both ways - what it settles and what it cannot

The simulator's dog is **COCO val2017 297830 / annotation 11206** and its cat is
**131938 / 50735**. Both are members of the 771-image confuser slice, so the
identical picture can be scored as a photograph and rendered as a card.

**The invention-free pair** (`tables/same_image_analysis.txt` A). The photograph
at its own centre crop subtends 119.9 px; the card rendered with the camera
lowered to the dog's own centre height at 0.50 m subtends 119.6 px:

| arm | photo | render, clean | d | photo through himax | render, himax | d |
|---|---|---|---|---|---|---|
| float | 0.523 | 0.415 | **-0.108** | 0.404 | 0.237 | **-0.167** |
| fq | 0.552 | 0.380 | **-0.172** | 0.387 | 0.200 | **-0.187** |
| chip | 0.783 | 0.590 | **-0.194** | 0.543 | 0.246 | **-0.297** |

At the one apparent size where the comparison needs no modelling choice, the
simulator makes this dog **less** detectable, not more. That size - 120 px - is
2.3x larger than anything the drone can see, and it is on the far side of the
sim's own response peak. It does not contradict section 4; it bounds it. The
renderer is not a blanket "makes everything more person-like" transform.

This dog pair is unambiguous and is the strongest single measurement in the
folder: `dog_petlevel` at 0.50 m gives 119.61 px against the photograph's 119.91,
with `visible_fraction` 1.007 and `touches_frame_edge` 0.

> **THE CAT HALF OF THIS PAIR IS NOT - see section 0a.5.** `cat_petlevel`
> reports `px128_h = 128.0` at **both** 0.25 m and 0.28 m, because the panel
> overflows the centre crop and the measure saturates; the two renders are
> different pictures (`visible_fraction` 0.875 vs 0.980) and the tie is broken
> one way in `analyze.py` and the other in `analyze_same_image.py`, so
> `tables/same_image.tsv` and `tables/same_image_summary.tsv` contradict each
> other on that row. Render-minus-photo, clean, is **+0.07 / +0.05 / +0.21**
> with the 0.25 m render and **-0.26 / -0.27 / +0.05** with the 0.28 m one. The
> sign flips on two of three arms: **the cat same-image comparison is
> undetermined** and should not be quoted in either direction. The cat verdict
> in section 0(d) does not depend on it - it rests on the 195-frame flown band,
> where the rendered cat never reaches 0.75 on any arm.

**Why it cannot be pushed into the flight band.** To put the photographed dog at
25 px the photograph must be given about 4x the field of view it contains. Three
fillings were tried - border replicate, mirror, and flat border-median. At
25 px they give fq/himax **0.117, 0.910, 0.774**: a spread of **0.79**, against
an effect of ~0.35. At 15 px the spread is **0.86**. The padded ladder is
measuring the padding, and is reported (`figures/same_image_ladder.png`,
`tables/same_image_ladder.csv`) only so nobody repeats it. Where padding is
light - 80-120 px, canvas 1.0-1.2x the photo - the three agree to 0.007-0.031,
and there the render is +0.25 at 80 px, +0.05 at 100 px and -0.17 at 120 px
against the photograph: still outside the flown band, and no longer one-signed.

**So the matched-size evidence inside the flown band rests on other real dogs,
not on this one** - 17 real dog photographs and 193 real pet photographs at
14.7-51.9 px. That is section 4, and it is the part the verdict rests on.

---

## 6. Verdict

**The simulator OVERSTATES the pet false-follow problem.**

At matched apparent size, over the band the drone actually flies, the rendered
s03 dog is above the shipped 0.75 confirmation bar **2.5x to 8.2x** as often as
real pet photographs of the same subtended size - chip arm, resolution-matched:
28.2% of rendered frames against 9.7% of real pets (**2.9x**, 95% CI [1.7, 5.4]);
float and fq against all pets, 4.0x and 4.4x; against real dogs only, 3.1x, 5.6x
and 2.5x - and its median confidence is **+0.22 to +0.52** higher. The direction
is positive in all 30 dog cells of `tables/matched_gap.tsv`, on all three forms
of the champion and on both cameras, survives restricting both sides to
fully-visible subjects, and survives standardising the size mix.

**The spread is real and the verdict rests on the pattern, not on one cell.**
Of the 24 primary cells, 4 median intervals and 8 above-bar intervals cross
zero - including the single most decision-relevant one, chip at 25-40 px with
himax on both sides: `d_median` +0.223 [-0.074, +0.503], `d_frac` +0.214
[-0.196, +0.580]. The 40-55 px bin (where nothing crosses zero on any arm) and
the 771-pet comparison set carry the weight; the 25-40 px chip cell on its own
establishes nothing, and below 25 px the two sides are indistinguishable. See
section 0a.4.

### What that means for the flight results already published

* **`F.pets__ships` failing its 0.5 m gate is not, by itself, evidence that this
  drone would chase a real dog.** The flown cell's latch confidences
  (0.76-0.83 on the chip network at 2.0-2.5 m - which this directory reproduces
  statically: 0.766 median in that band) are a property of a flat COCO cutout on
  a card, not of dogs. Real dogs at that apparent size read 0.44-0.50 and clear
  the bar on 1 of 6 photographs on chip (resolution-matched; the "0 of 6" first
  written here was the unmatched chain - section 0a.1), 2 of 6 on float and 1 of
  6 on fq.
* **The 2 of 4 repeats over the gate, the threshold sweep, the exit-bar sweep and
  the hard-negative fine-tune all remain correctly measured** - they are
  measurements of the simulator, and they are internally valid. What changes is
  the inference from them to hardware. Anything of the form "the drone chases
  pets a third of the time" needs the qualifier "in simulation, against a card";
  "and would chase a real dog about as often" is not supported, and is
  contradicted by a factor of 2.5-8 depending on arm and comparison set.
* **The published real-image false-alarm evidence is untouched and is still the
  reason to care.** 0.239 @0.45 / 0.171 @0.55 on n=771 reproduced exactly here,
  and at drone-visible sizes (14.7-51.9 px, n=193) real pets are above the 0.75
  bar on **8.3%** of photographs on fq, 9.8% on float and **10.4%** on chip
  (resolution-matched; 4.1% unmatched - section 0a.1). About one real pet
  photograph in ten clearing the confirmation bar is a real defect. It is just
  not a 57%-of-frames defect.
* **Where the effort should go.** Further tuning of follower thresholds against
  the s03 cell is tuning against a card: the sim's own response curve peaks at
  25-55 px and real pets have no such peak, so a threshold fitted to the sim
  will not transfer. Two things would be worth days: (i) a subject
  representation that is not a flat frontal card - the same criticism the
  2026-09-13 range sweep already made about azimuth - and (ii) re-deriving the
  pet risk from the real-image slice restricted to drone-visible apparent sizes,
  which is cheap and already half-done in `tables/real_pets.csv`.

### The one comparison that is NOT size-matched, and why it is worth having anyway

`figures/what_the_net_sees.png` makes the main confound visible: a real dog that
subtends only 25-48 px of a photograph is usually an incidental dog - curled in
a bed, behind furniture, across a cluttered room - because that is how a dog
ends up small in a photograph. The rendered card is upright, isolated,
front-facing and against a plain wall. So the matched-size gap in section 4
contains both the rendering AND that difference in pose and context, and this
directory cannot separate them (see section 7).

The nearest available handle on it: real dog photographs at 80-129 px are mostly
the opposite kind of picture - isolated, upright, deliberately framed portraits,
the closest real analogue to what the card is. **They clear the 0.75 bar on
17-21% of photographs** (float 0.21, fq 0.17, chip 0.19; n=47, median 0.32-0.41).
The rendered card clears it on 50-72% of frames at its own sizes. That is a
comparison at DIFFERENT apparent sizes and is not part of the verdict - but the
best-posed, best-lit, biggest real dogs in the slice still fall well short of
the card.

### If someone wants the opposite headline, here is what would have to be true

The gap would have to be an artefact of (i) the 6-10 real dog photographs per
bin - answered by the 771-pet comparison, same direction, tighter CIs; (ii) the
camera model - answered in 4(b), it moves real photographs' rate above the bar by at most 0.042, in both directions; (iii) the
resampling chain - answered by the `*_via244` columns, which move the real slice
by 0.01 on float/fq; or (iv) the size measure - answered by section 2c, which
restricts both sides to wholly-visible subjects and changes nothing.

---

## 7. What this does NOT establish

* **Nothing about hardware.** No frame here came from a camera. The real side is
  COCO photographs, which are not himax frames either; section 4(b) models that
  gap but does not measure it.
* **n on the real dog side is small at flight-band sizes**: 7 photographs in
  25-40 px, 10 in 40-55 px, 17 in the whole 14.7-51.9 px band. The 771-pet
  comparison carries the statistical weight; the dog-only comparison carries the
  species match. They agree.
* **One build per subject, one scene.** Section 1 shows a same-subject,
  same-range swing of up to 0.13 from panel position alone. The sim side here is
  not a distribution over scenes.
* **Static frames only.** No motion blur from flight, no follower state machine,
  no 3-frame confirmation logic. "Fraction of frames above the bar" is not the
  same as "fraction of flights that confirm"; the 3-frame rule makes confirmation
  harder than a single frame, and sustained latching harder still.
* **The sim's pose sampling is favourable to the sim** in one way and not in
  another: frontal card views at 0-30 deg azimuth only (the 2026-09-13 sweep
  shows confidence collapses past ~40 deg, which would lower the sim numbers),
  but also perfectly centred, unoccluded and static.
* **Pose and context are NOT matched, only size is - and this is the most
  important caveat in this document.** The rendered card is upright, isolated,
  front-facing, unoccluded, against a plain wall. The real dog photographs at
  the same apparent size are mostly incidental dogs in cluttered rooms, often
  lying down or partly hidden, because that is how a dog comes to occupy 25 px
  of a photograph (`figures/what_the_net_sees.png`). The gap in section 4
  therefore belongs to the whole difference - card, room, lighting, isolation,
  pose - and this directory does not apportion it among those. An upright,
  isolated, front-facing REAL dog 2 m from the camera is not in COCO at that
  apparent size, so it was not measured and is not ruled out as scoring higher
  than the photographs in that band. What section 6's unmatched check shows is
  that the best-posed real dogs in the slice, at a larger size, still clear the
  bar 2.4-4.2x less often than the card does.
* **Only two animals.** The s03 dog and the s03 cat. `s04`'s mannequins and
  teddy bears are untouched, and the teddy bear is the confuser class the error
  analysis called out as the most confidently mis-detected.

---

## 8. Files, and how to re-run

```
scripts/champion_arms.py      the champion in its three forms behind one call; BOTH
                              sides import this, so preprocessing cannot drift
scripts/real_pets.py          real side: the 771-image slice, apparent size, 3 arms
scripts/real_pets_himax.py    real side through camera_model.himax_typical
scripts/sim_render.py         sim side, step 1: render + measure apparent size (trainenv)
scripts/sim_score.py          sim side, step 2: score the frames with champion_arms
scripts/same_image_ladder.py  the same COCO image re-framed to each apparent size
scripts/analyze.py            the comparison, tables and figures
scripts/analyze_same_image.py the same-image analysis and its padding sensitivity

tables/real_pets.csv          771 rows: size, category, and 6 confidence columns
tables/real_pets_himax.csv    735 rows: 245 dog/cat photographs x 3 sensor draws
tables/sim_pets_render.csv    1 116 rendered frames: geometry + build_scene's own score
tables/sim_pets.csv           the same frames scored by all three arms
tables/sim_by_range.tsv       the sim ladder by range, the shape a flight sees
tables/same_image_ladder.csv  the re-framed photograph, 3 paddings x 12 sizes x 2 cameras
tables/size_response.tsv      confidence vs size, every group x arm x bin
tables/matched_gap.tsv        sim minus real, with cluster-bootstrap intervals
tables/size_standardised.tsv  the flown band with the size mix held equal
tables/same_image_summary.tsv the same-image blocks A/B/C as data
tables/analysis.txt           the full printed analysis
tables/same_image_analysis.txt  the full printed same-image analysis
tables/headline_numbers.txt   the numbers quoted in this README
code_hashes.txt               sha256 of the sim tooling as imported
figures/conf_vs_size_dog.png, conf_vs_size_cat.png, frac_above_bar_chip.png,
figures/same_image_ladder.png, what_the_net_sees.png
logs/*.log                    run logs (see the note below)
```

Re-run, in order (absolute paths; `$D` is this directory):

```
../nemoenv/bin/python  $D/scripts/real_pets.py        $D/tables/real_pets.csv
../nemoenv/bin/python  $D/scripts/real_pets_himax.py  $D/tables/real_pets_himax.csv
# take the simulator lock before this one:
../trainenv/bin/python $D/scripts/sim_render.py  <frames_dir> $D/tables/sim_pets_render.csv
../nemoenv/bin/python  $D/scripts/sim_score.py   <frames_dir> $D/tables/sim_pets_render.csv \
                                                 $D/tables/sim_pets.csv
../nemoenv/bin/python  $D/scripts/same_image_ladder.py $D/tables/same_image_ladder.csv
../nemoenv/bin/python  $D/scripts/analyze.py            $D
../nemoenv/bin/python  $D/scripts/analyze_same_image.py $D
```

The 1 116 rendered PNG frames are in scratch, not here: the repo's own rule is
that evidence folders keep the metrics, not the pictures
(`.gitignore`, the 2026-09-12 note). `sim_pets_render.csv` carries each frame's
filename, geometry and score, so re-rendering reproduces them.

**`logs/` needs `git add -f`.** `.gitignore` has a bare `*.log`, so every file
under `logs/` here is ignored by default:

```
git add -f docs/eval_results/2026-09-15-sim-pet-fidelity/logs/*.log
```

Nothing else in this directory is ignored (`tables/` is `tables`, not `data`, so
the anchored `/data/` rule does not apply, and no `*.pth`, `*.onnx`, `cache/` or
`snap_*.png` is written here).
