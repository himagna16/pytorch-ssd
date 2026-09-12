# Why the drone parks 3 m away — Sep 12, 2026

Root-cause of the distance-keeping failure in
`docs/sim_results/2026-09-11-simv2/` (M7 fails on `A.static__ships`,
`B.moving__ships`, `B.moving__delta_backend`, `B.moving__delta_camera`,
`B.moving__delta_speed`).

**The stated cause was "the size head over-reads by 1.6–1.8×". It does not.
The simulator draws the subject 1.5–2.0× too tall, because the MuJoCo floor is a
20% mirror and the network is reading the person plus their reflection as one
object.** The size head reads real people correctly. A second, smaller part of
the gap is structural: the control law cannot reach 1.94 m even with a perfect
size head, so the M7 gate targets a distance the code cannot produce.

Nothing here was flown. **This work wrote only to this directory** — it did not
edit `build_scene.py`, `scoreboard.py`, `camera_model.py` or `follow_person.py`,
and did not rebuild or alter any scene file. (`camera_model.py` does show as
modified in git; that was a parallel task, see §10.) Every number below comes from
a script in `scripts/`, run against the scene files and the checkpoint the suite
itself used, and is reproducible with the command shown.

---

## 0. TL;DR for someone in a hurry

| claim | status |
|---|---|
| The scene panel subtends the wrong visual angle | **refuted** — it is right to ±1 pixel (0.99–1.01×) |
| `scoreboard.py`'s `HOLD_K` / `BAND_K` geometry is wrong | **refuted** — it is the correct pinhole formula |
| The size head over-reads on real images | **refuted** — signed bias −0.007 to −0.015 over the 2635 COCO val images with a person |
| The simulator draws the subject too tall | **confirmed** — 1.53× at 2.4 m rising to 2.01× at 3.8 m |
| Cause of that | **confirmed** — `reflectance="0.2"` on the groundplane material |
| The control law can reach the 1.94 m M7 target | **refuted** — its floor is 2.43 m by construction |
| `M7_size_overread_ratio` measures the size head | **refuted** — it is algebraically `d / 1.942` |

Do **not** retrain or re-tune the size head on the strength of the Sep 11 suite.

> **Read §12 before quoting anything from §6.** A verification pass on Sep 12
> reproduced §§1–6 to the digit and confirmed the two headline findings on the
> *chip* network as well, but it also corrected §5 and §6 and found that the
> §6 replay runs the float model, not the chip model the failing cells flew.

---

## 1. Geometry first: is the scene honest?

The hypothesis that had to be killed first: the subjects are flat 1.7 m cards, and
if a card subtends a different angle than a real 1.7 m person would, the model is
reading the scene wrong rather than the world wrong — which would demand the
opposite fix.

`scripts/geom_probe.py` loads `scenes_v2/s15_static_offset/scene.xml`, puts a
camera on the drone's eye line (z = 0.8, fovy 70, 324×244) pointed straight at the
subject, steps it through known true distances, and measures the panel's pixel
extent with **MuJoCo segmentation rendering** — not a threshold, the renderer's own
per-pixel geom id.

```
/Users/saimaruvada/Downloads/drone/trainenv/bin/python scripts/geom_probe.py
```

```
  d_true  px_top px_bot  px_h  meas_size  geom_size  meas/geom
    1.94      41    193   153     0.6270     0.6257     1.0021
    2.43      57    178   122     0.5000     0.4996     1.0009
    2.70      64    173   110     0.4508     0.4496     1.0027
    3.00      70    168    99     0.4057     0.4046     1.0027
    3.64      79    159    81     0.3320     0.3335     0.9954
```

Over 61 distances from 1.60 m to 4.60 m (`scripts/sweep.py`):

```
rendered / geometry ratio: mean 1.0011  min 0.9872  max 1.0101
```

That spread is ±1 pixel out of 244. **The panel subtends exactly the angle
`scoreboard.py` says a 1.7 m subject should**, and `HOLD_K = 1/(2·0.625·tan35°)`
→ 1.942 m and the band `[1.619, 2.428]` m are all correct arithmetic.

Independent cross-check: a pure-Python pinhole paste
(`scripts/paste_probe.py`, no MuJoCo at all) placing a 1.7 m subject at the same
distances lands on **the same image rows as the renderer** — 57–179 at 2.4 m,
70–168 at 3.0 m, 76–162 at 3.4 m. Two independent implementations agree exactly.

**The alternative hypothesis is refuted. The geometry is not the defect.**

---

## 2. But the panel is not what gets drawn

The suite's §3.2 check said "the rendered person spans 99.4% of the panel". That
measures the *texture on the card*. It does not measure **what the card puts on
the screen**.

`scripts/refl_extent.py` renders each frame twice — once normally, once with the
subject panel's geom hidden — and takes the vertical extent of every pixel that
differs. That is everything the subject contributes to the image.

```
/Users/saimaruvada/Downloads/drone/trainenv/bin/python scripts/refl_extent.py
```

```
  refl   d_true  panel_rows  panel_h  apparent_h  apparent/true
  0.2     2.40    57-179       123         188          1.528
  0.2     2.80    66-171       106         178          1.679
  0.2     3.00    70-168        99         174          1.758
  0.2     3.40    76-162        87         169          1.943
  0.2     3.80    81-158        78         157          2.013

  0.0     2.40    57-179       123         125          1.016
  0.0     2.80    66-171       106         106          1.000
  0.0     3.00    70-168        99          99          1.000
  0.0     3.40    76-162        87          88          1.011
  0.0     3.80    81-158        78          79          1.013
```

The subject is drawn **1.53× to 2.01× taller than the panel**. The cause is one
attribute, in `build_scene.py` line 554 and `build_person_scene.py` line 34, in all
18 built `scenes_v2/*/scene.xml` and all 3 legacy `scenes/*/scene_person.xml`:

```xml
<material name="groundplane" texture="groundplane" texuniform="true"
          texrepeat="2 2" reflectance="0.2"/>
```

`reflectance="0.2"` makes the floor a specular mirror. The subject stands on it, so
the renderer draws a mirror image of the subject hanging below its feet.
`figures/floor_mirror_ab.png` shows it at 3.0 m, with the true panel extent boxed
in red, for reflectance 0.2 and 0.0, clean and himax.

The numbers follow from geometry with no free parameters. The mirror spans world
z = 0 → −1.7, the panel z = 0 → 1.7, so once the reflection is fully inside the
frame the combined extent is exactly **2×** the panel; closer in, the frame bottom
clips it. The reflection's foot lands on row `122 + 174.23·(0.8+1.7)/d`:

| d | predicted foot row | in frame? | predicted apparent_h | measured |
|---|---|---|---|---|
| 3.8 m | 236.6 | yes (frame is 244 rows) | 2 × 78 = 156 | **157** |
| 2.4 m | 303.4 | no, clipped at 244 | 244 − 57 + 1 = 188 | **188** |

The published over-read of **1.345× (proven) to 1.649× (ships-as)** sits inside the
measured 1.53–2.01× drawing error. The model is not over-reading a 1.7 m subject;
it is correctly reading a subject the renderer drew 1.5–2× too tall.

Confirmed under `MUJOCO_GL=cgl`, the backend `run_sim_headless.sh` uses, with
identical numbers. The flights load these exact files: `cell.json` records
`scene_dir: .../scenes_v2/s15_static_offset`, and `run_acceptance2.sh:169` passes
`--scene "$sdir/scene.xml"`. The drone's own camera is
`fpv_cam pos="0.03 0 0" euler="0 -90 -90" fovy="70"` — body-fixed, forward-facing,
level in hover, i.e. the geometry probed here.

---

## 3. The size head, tested away from the simulator

Two independent tests, neither of which can see a MuJoCo floor.

### 3.1 COCO val2017, 5000 images, exact ground truth

`scripts/coco_size_probe.py` runs the checkpoint through **its own validation
pipeline** (`utils.transforms.get_val_transforms` → `CenterCropSquare` →
128×128) and compares against **the trainer's own label**,
`size = largest_person_box_height / image_height` from
`utils/coco_follow_regression.py`. Nothing is re-derived; both sides are the
project's own code.

```
/Users/saimaruvada/Downloads/drone/trainenv/bin/python scripts/coco_size_probe.py
```

All 5000 val2017 images; 2635 of them contain a person box. Three nested subsets,
because "is it biased" depends on which people you ask about:

```
=== all images with a person box                     (n=2635) ===
  bucket exact match : 0.6083   mean signed error : -0.0145   median decoded/GT : 0.9613
=== person box >= 25% of frame height                (n=2059) ===
  bucket exact match : 0.5639   mean signed error : -0.0432   median decoded/GT : 0.9274
=== size 0.25-0.85, the follower's actual regime     (n=1475) ===
  bucket exact match : 0.4475   mean signed error : -0.0067   median decoded/GT : 1.0045

  --> effective 1->2 boundary at true size 0.528 (nominal 0.500; over-read 0.947x)
      a 1.7 m person: model calls bucket 2 from 2.30 m (nominal 2.43 m)

  P(pred bucket >= 2) by true size    (the true edge is 0.500)
     0.30-0.35: n=118  P=0.195      0.55-0.60: n=116  P=0.638
     0.35-0.40: n=132  P=0.242      0.60-0.65: n=119  P=0.782
     0.40-0.45: n=108  P=0.287      0.65-0.70: n=118  P=0.805
     0.45-0.50: n=116  P=0.466      0.70-0.75: n=141  P=0.837
     0.50-0.55: n=112  P=0.491      0.75-0.80: n=136  P=0.904
```

On real images the head is **unbiased in the sign that matters** — every subset
under-reads slightly, by 1% to 7%. It is
*noisy* (bucket exact-match 45%), which matters in §4, but it is not biased.

### 3.2 Pasted subjects at exactly known pixel heights

`scripts/paste_probe.py` composites a masked COCO person onto a flat wall at the
exact pixel height and image row the sim would produce for a 1.7 m subject, and
sweeps distance. No renderer, no floor, no room.

```
/Users/saimaruvada/Downloads/drone/trainenv/bin/python scripts/paste_probe.py --n-random 10
```

12 subjects including the suite's own subject, over 1.8–4.2 m. The number reported
is the outermost distance at which the head still calls bucket ≥ 2; the correct
answer is 2.428 m.

```
ann   428692  (the s15/s01 subject, used in 14 of 18 scenes)  2.20 m -> 0.91x
ann  1728930  (the s10 subject)                               never reached bucket 2
ann   421689  2.40 m -> 0.99x        ann  1226757  2.70 m -> 1.11x
ann  1719710  1.90 m -> 0.78x        ann   457916  1.90 m -> 0.78x
ann  2191328  2.20 m -> 0.91x        ann   473855  2.70 m -> 1.11x
ann   213111  2.00 m -> 0.82x        ann   466437  2.30 m -> 0.95x
ann   515072  never reached bucket 2   ann   198884  never reached bucket 2

across the 9 of 12 that reached bucket 2 at all: boundary over-read median 0.91x  min 0.78x  max 1.11x
```

Median 0.91×. **Not 1.6×.** And the suite's own subject — the crouching tennis
player from COCO 19432, cropped at the shins, that 14 of the 18 scenes use — is
itself 0.91×, so this is not a bad-cutout story either.

### 3.3 The same scene with the mirror turned off

`scripts/reflect_ab.py` changes exactly one number — `mat_reflectance` for the
groundplane, in the **compiled** model, in memory. Same scene file on disk, same
camera, same distances, same checkpoint.

```
/Users/saimaruvada/Downloads/drone/trainenv/bin/python scripts/reflect_ab.py
```

```
  reflectance 0.2  clean: outermost bucket>=2 at 3.30 m (true size 0.369)  over-read 1.36x  +0.87 m vs ideal
  reflectance 0.2  himax: outermost bucket>=2 at 3.30 m (true size 0.369)  over-read 1.36x  +0.87 m vs ideal
  reflectance 0.0  clean: outermost bucket>=2 at 2.20 m (true size 0.549)  over-read 0.91x  -0.23 m vs ideal
  reflectance 0.0  himax: outermost bucket>=2 at 3.00 m (true size 0.406)  over-read 1.23x  +0.57 m vs ideal
```

With the mirror off, the rendered scene gives **0.91×** — the same number, to two
decimals, as the flat-background paste of the same subject in §3.2. Two completely
different code paths converge. That is the confirmation.

`figures/network_input_sim_vs_paste.png` shows the 128×128 the network actually
receives, sim / himax / paste, at 2.4, 3.0 and 3.4 m. The reflection is visible to
the naked eye in the left two columns.

### 3.4 The published flight logs say the same thing

`scripts/flip_analysis.py` asks the question of the **Sep 11 flights themselves**
— no rendering, no probe — by binning every tracking frame by true distance and
taking the distance at which `P(size_bucket ≥ 2)` crosses 0.5. It was written for
this report but its output was never quoted; it is added here because it is the
only flight-grounded number in the package.

```
/Users/saimaruvada/Downloads/drone/trainenv/bin/python scripts/flip_analysis.py
```

```
=== float/clean/full  (proven)   n_frames_tracking=1076  flights=2 ===
   --> 50% flip distance 3.29 m  (image fraction 0.369; over-read 1.355x)
=== chip/himax/chipspeed (ships-as)   n_frames_tracking=435  flights=2 ===
   --> 50% flip distance 3.61 m  (image fraction 0.336; over-read 1.487x)
```

The float/clean flights flip at **3.29 m**. `reflect_ab.py` with the mirror on,
clean camera, predicts **3.30 m** (§3.3). A desk probe and two real simulator
flights land within 0.01 m of each other, which is the strongest single piece of
evidence here that the probe is measuring the same thing the flights did.

---

## 4. The second defect: the control law cannot reach 1.94 m

`follow_person.py:367`

```python
vx = clip(a.k_fwd * (a.target_size - p["size_value"]), a.v_max) if abs(x) < 0.5 else 0.0
#    k_fwd 0.8, target_size 0.625, v_max 0.3  (argparse defaults, lines 220/229/230)
#    the abs(x) < 0.5 guard only stops forward motion when the subject is far off-centre
```

`size_value` is the **argmax** bucket centre, one of `{0.125, 0.375, 0.625, 0.875}`,
from the current frame only. There is no temporal filter. So the law is bang-bang:
0.2 m/s closing while the bucket reads 1, and **0.00 m/s the instant a single frame
reads 2**.

A *perfect* size head flips to bucket 2 at image fraction 0.500, i.e.

```
d = 1.7 / (2 · 0.500 · tan 35°) = 2.428 m
```

**2.428 m is the floor of this controller.** The M7 gate targets `HOLD_K·H` = 1.942 m,
the bucket-2 *centre*, which a proportional law fed a quantised signal reaches only
by luck. 0.486 m of the reported error is unreachable by construction, independent
of the model. `GATE_BASIS["M7_mean"]` half-knows this ("the approach parks near the
far edge (~0.49 m)") and sets the threshold at 0.75 m, but the headline number
throughout the suite is still "target 1.94".

Two things make it worse than the floor:

1. **The head is noisy, and bang-bang samples the tail.** From §3.1, at a true size
   of 0.35–0.40 (≈3.3 m) the head still calls bucket ≥ 2 on **24%** of real frames.
   Closing 0.97 m at 0.2 m/s takes ~4.9 s — about 68 frames at 14 Hz. The chance of
   getting through without one false bucket-2 frame is `0.76^68 ≈ 4·10⁻⁹`. The
   drone therefore parks wherever the first outlier fires, not where the head's
   average says. This is exactly the 0.62 m spread on an unchanging scene that the
   suite noticed (3.35, 3.08, 2.90, 2.73 m on `A.static__ships`).
2. **The bearing channel already has the fix; size does not.** `follow_person.py`
   computes `x_soft`, the probability-weighted mean of the 9 x-bin centres,
   with the comment *"the argmax bin only changes every 0.22 in x … which leaves the
   controller blind to small offsets."* The identical argument applies to a
   4-bucket size, and nothing analogous exists for it.

---

## 5. The published over-read metric is circular

`scoreboard.py:406` *starts* the settled window at the first frame where
`size_bucket == 2` (`at_hold = np.where((size_bucket == 2) & trk)[0]`, then
`win = t >= start`), then line 425 reports `M7_size_decoded_mean` over that
window and line 427 divides it by the geometric size. Because the drone stops
moving once it reads bucket 2, almost every frame in that window is a bucket-2
frame, so the numerator sits near 0.625 *because of how the window was chosen*.
Across the 30 person-following runs in `scoreboard.json` that carry the metric
(26 reached hold, 4 did not):

```
decoded size: mean 0.5307 over all 30
              0.589-0.639 on 22 of the 26 that reached hold
              0.476-0.496 on the other 4        (partial holds)
              0.125        on the 4 that never reached hold
```

so `M7_size_overread_ratio ≈ 0.625 / geom ≈ d / 1.942`. Checked row by row:

```
 dist_mean    geom  decoded   ratio | 0.625/geom  d/1.942
     2.687   0.454    0.610   1.345 |      1.377    1.384
     3.030   0.401    0.624   1.557 |      1.559    1.560
     3.182   0.382    0.639   1.670 |      1.636    1.639
     3.413   0.356    0.617   1.731 |      1.766    1.757
```

The "over-read ratio" table in the suite README is a restatement of the distance
table, not independent evidence about the size head. It should be dropped or
renamed; as it stands it made one measurement look like two.

---

## 6. What each cause is worth

`scripts/loop_replay.py` replays the follower's forward channel against live
renders: start at 3.64 m, render the current view, run the network, apply the real
law, integrate, repeat at the real control rate. It is **not a flight** — yaw is
assumed perfect and velocity instantaneous — and the network is the **float**
checkpoint with a PIL bilinear resize, *not* the chip ONNX plus
`firmware_preprocess` that the ships-as cells flew. See the two corrections
below the table.

```
/Users/saimaruvada/Downloads/drone/trainenv/bin/python scripts/loop_replay.py
```

```
  case                                            final d  mean last 5s  |err| vs 1.942  in band?
  A  as-shipped        mirror on  clean  argmax     3.37m         3.37m           1.43m   no
  B  as-shipped        mirror on  himax  argmax     3.21m         3.21m           1.27m   no   (n=5, 3.21-3.21)
  C  fix scene only    mirror OFF clean  argmax     2.24m         2.24m           0.30m   YES
  D  fix scene only    mirror OFF himax  argmax     2.72m         2.72m           0.77m   no   (n=5)
  E  fix decode only   mirror on  clean  soft       2.23m         2.23m           0.28m   YES
  F  fix decode only   mirror on  himax  soft       3.03m         3.03m           1.09m   no   (n=5, 2.99-3.04)
  G  both fixes        mirror OFF clean  soft       2.06m         2.06m           0.12m   YES
  H  both fixes        mirror OFF himax  soft       2.15m         2.17m           0.22m   YES  (n=5, 2.14-2.19)
```

**Corrected during verification (Sep 12).** The first version of this section
compared case B against **3.326 m**, which is `B.moving__ships` — a *different
scene* (`s01_control_moving`, a walking subject). `loop_replay.py` renders
`s15_static_offset`, so the cells it should be read against are the two that use
that scene:

| replay case | matching suite cell | cell config | measured `M7_dist_final_m` (median) | replay | replay − measured |
|---|---|---|---|---|---|
| A (clean, argmax, 14 Hz) | `A.static__proven` | float / clean / full | **2.424 m** (n=5, 2.218–2.580) | 3.37 m | **+0.95 m** |
| B (himax, argmax, 6.5 Hz) | `A.static__ships` | chip / himax / chip-speed | **3.028 m** (n=4, 2.729–3.345) | 3.21 m | **+0.18 m** |

So the replay tracks the himax/ships-as cell to 0.18 m and over-predicts the
clean cell by 0.95 m — with perfect yaw the loop stops at the first bucket-2
outlier, where a real flight's bearing error delays it. **Treat every replay
number as an upper bound**, the clean ones especially.

**Second correction: the replay does not run the network the ships-as cells
flew.** `A.static__ships` and `B.moving__ships` use `--backend chip` (the
DORY-quantised ONNX behind `perception_backends.ChipPerception`, fed by
`firmware_preprocess`). `loop_replay.py` runs the **float PyTorch checkpoint**
with a PIL bilinear resize; it imports `firmware_preprocess` and defines
`--onnx` but uses neither. The agreement in the table above is therefore between
two different networks, and cases C–H predict what the *float* loop would do.
See §12 for the chip network measured directly.

Because the effects are not additive, read the 2 × 2 rather than a budget:

| | mirror on (as shipped) | mirror off |
|---|---|---|
| **clean camera, argmax** | 3.37 m | 2.24 m |
| **himax camera, argmax** | 3.21 m | 2.72 m |
| **himax camera, soft size** | 3.03 m | **2.15 m** |

With the mirror on, the camera preset barely matters — the artefact dominates and
masks everything else, which is why the suite's "cost of realism stacks additively"
table (§3.2 of the sim README) is measuring mostly one thing.

### The himax residual is real and still open

With the mirror off, the himax preset still moves the flip from 2.20 m to 3.00 m
(`scripts/himax_split.py`, one override at a time):

```
  clean (no sensor model)              2.20 m   0.91x
  himax_typical (all on)               3.00 m   1.23x
    - no optical blur                  2.70 m   1.11x
    - no AE (fixed mid)                3.10 m   1.27x
    - no noise                         3.00 m   1.23x
    - no vignette                      3.00 m   1.23x
```

About 40% of it is the 0.65 px optical blur; the rest is not attributable to any
single effect. **Whether this transfers to a real Himax is unverified** — it needs
real frames at known distance, which is a lab-session measurement, not a desk one.
Note also that the scene renders at 167–182 DN mean with 24–30% of pixels
saturated, so the AE is being asked to expose an already-clipped image; that is a
separate realism question for whoever owns the scene builder.

---

## 7. Verdict

**A combination, in these proportions, against the 1.384 m M7 error of the
ships-as cell:**

| cause | worth | real on hardware? |
|---|---|---|
| **Simulator: floor mirror draws the subject 1.5–2× too tall** | ~0.5 m (himax) to ~1.1 m (clean) | **No.** Artefact. |
| **Decode/controller: argmax + bang-bang, quantisation floor 2.43 m** | 0.486 m floor, plus the outlier-latching that puts it further out | **Yes.** Transfers unchanged. |
| **Camera model residual (mostly optical blur)** | ~0.5–0.8 m | **Unknown.** Needs real frames. |
| **The size head over-reading** | ~0 — it reads real people to within 5% | n/a |

---

## 8. Recommendation — and why nothing was implemented

Both fixes are provable at the desk and both belong to someone else's file, and one
of them changes flight behaviour six days before the first hardware session. Per
the standing instruction that re-flying the suite is expensive and ambiguity means
stop, **no shared file was edited.** In priority order:

1. **Set the groundplane `reflectance` to 0.0** in `build_scene.py:554` and
   `build_person_scene.py:34`, rebuild the 18 scenes, re-fly the five failing
   distance cells. *Owner: scene builder.* This invalidates every scene on disk and
   every published simulator result including the September baselines, which is a
   team call, not a unilateral one. Expected result is case C/D above: clean passes
   M7, himax gets close.
2. **Give size the soft decode that `x` already has** — a `--soft-size` flag
   computing `Σ softmax(size_logits)·{0.125,0.375,0.625,0.875}`, defaulting off so
   today reproduces byte-for-byte — or, if a control change is unacceptable before
   the lab, require N consecutive bucket-2 frames before zeroing `vx`.
   *Owner: `follow_person.py`.* Do not ship this untested: it must be flown.
3. **Fix the M7 report.** Either gate against 2.428 m, which is what this control
   law can achieve, or change the law. And drop or rename
   `M7_size_overread_ratio` (§5) — it cannot measure what it claims to.
4. **Do not retrain the size head** on the strength of the Sep 11 suite. §3 says
   there is nothing to fix there.

### For the lab session

`tools/real_frames/score_real_frames.py` already computes an expected size bucket
from a known distance (`expected_size(dist, person_h, cam_h, crop_vfov_deg)`, which
is the same pinhole formula plus frame-edge clipping). The capture protocol's
known-distance clips are therefore **the direct hardware test of this report.**

- Expect the size bucket to come out roughly right — around COCO-level accuracy,
  not 1.6× high. If it comes out 1.6× high on real frames, this report is wrong and
  the size head is the problem after all.
- **Note the floor.** A polished or wet-look lab floor will produce a real version
  of the artefact in §2. If the room has a shiny floor, record that on the log
  sheet, and if a matte surface is available, capture one set on each.
- Do not fly a distance-holding demo expecting 1.94 m. Even fixed, this control law
  parks at ~2.1–2.4 m.
- **The number to actually expect on hardware is ~3 m, and the mirror has nothing
  to do with it.** This is the §4 result restated for the room, because it is the
  one that transfers. On real images the head calls bucket ≥ 2 on **24%** of
  frames at a true size of 0.35–0.40 (a 1.7 m person at ≈3.2–3.4 m, §3.1). The law
  zeroes `vx` on a *single* such frame. Closing the 0.9 m from 3.3 m to 2.43 m at
  0.2 m/s takes ~4.4 s ≈ 28 frames at the chip's 6.5 Hz, so the chance of getting
  there without one false bucket-2 frame is `0.76^28 ≈ 4·10⁻⁴`. **Expect the real
  drone to stop wherever the first outlier fires — around 3 m — and to stop at a
  different distance every run.** That is not a bug to debug in the room; write
  down where it stopped and move on.
- `score_real_frames.py` loads the **float** checkpoint
  (`build_follow_model_from_checkpoint`), while the drone flies the chip network.
  §12 measured both networks on COCO and they agree to ~1% (86% bucket agreement),
  so the float score is a fair proxy. It has **no `--backend` flag** — do not go
  looking for one in the room. Scoring real clips on the chip network would mean
  driving `perception_backends.ChipPerception` the way `scripts/chip_check.py`
  does, which is a desk job for afterwards, not a lab job.

---

## 9. What is NOT verified

- **No hardware was involved.** Every frame here is rendered. Nothing in this
  report has been seen by a real camera.
- **No flight was run.** §6 is a render-in-the-loop replay with idealised yaw and
  instantaneous velocity tracking. It reproduces the ships-as cell to 0.12 m and
  the clean cell to 0.69 m; the clean-config numbers are an upper bound.
- **The predicted effect of both fixes is a replay, not a re-fly.** Cases C–H must
  be confirmed by the acceptance suite before anyone quotes them.
- **The himax residual (§6) may be a camera-model artefact rather than a real
  sensor effect.** Unresolved without real frames at known distance.
- **Whether a real floor reflects enough to matter is unknown.** MuJoCo's
  `reflectance="0.2"` is a specular mirror; a matte indoor floor is not. That is
  the assumption behind calling §2 an artefact, and it is an assumption.

## 10. A note on `camera_model.py`

`tools/crazysim_macos/camera_model.py` was edited by a parallel task at 12:11 on
Sep 12, in the middle of this work. Every himax result in this report
(§3.3, §6) was **re-run against the post-edit file and is unchanged** — the
reflectance A/B, the sensor-effect split and all eight replay cases reproduce to
the digit. The load-bearing findings (§1 geometry, §2 the mirror, §3.1 COCO,
§3.2 the paste probe) do not touch that file at all. If it changes again, re-run
`scripts/reflect_ab.py`, `scripts/himax_split.py` and `scripts/loop_replay.py`
before quoting the himax columns.

No file outside this directory was modified by this work.

## 11. Reproducing

All scripts are in `scripts/`, all use
`/Users/saimaruvada/Downloads/drone/trainenv/bin/python`, none write outside this
directory or the scratchpad, and none modify the scene files — `reflect_ab.py`,
`refl_extent.py` and `loop_replay.py` change `mat_reflectance` on the *compiled*
model in memory only.

Run them from **this directory** (`docs/eval_results/2026-09-12-distance/`) — the
paths inside the scripts are absolute, but the `scripts/...` in each command is
not. Three of them take a required argument; without it you get an argparse error
or an `IndexError` traceback, not a useful message. `$SCRATCH` below is any
writable directory you pick.

| script | run it as | answers | runtime |
|---|---|---|---|
| `geom_probe.py` | `… python scripts/geom_probe.py` | does the renderer draw a 1.7 m subject at the right angle? | ~20 s |
| `sweep.py` | `… python scripts/sweep.py --out $SCRATCH/sweep` **(`--out` required)** | open-loop bucket vs known distance, clean + himax, saves chip inputs | ~4 min |
| `refl_extent.py` | `… python scripts/refl_extent.py` | how much taller does the mirror make the subject look? | ~10 s |
| `reflect_ab.py` | `… python scripts/reflect_ab.py` | one-variable A/B on the floor reflectance | ~3 min |
| `himax_split.py` | `… python scripts/himax_split.py` | which sensor effect is left once the mirror is off | ~6 min |
| `coco_size_probe.py` | `… python scripts/coco_size_probe.py` | is the size head biased on real images? | ~8 min |
| `paste_probe.py` | `… python scripts/paste_probe.py --n-random 10` | is it biased with no renderer involved at all? | ~2 min |
| `loop_replay.py` | `… python scripts/loop_replay.py` | where would the *float* loop park, per fix combination? | ~15 min |
| `flip_analysis.py` | `… python scripts/flip_analysis.py` | the same question asked of the published flight logs | ~5 s |
| `dump_refl.py` | `… python scripts/dump_refl.py $SCRATCH/refl.png` **(output path required)** | figure 1 | ~10 s |
| `dump_cmp.py` | `… python scripts/dump_cmp.py $SCRATCH/cmp` **(output dir required)** | figure 2 | ~30 s |

where `…` is `/Users/saimaruvada/Downloads/drone/trainenv/bin/python`.

---

## 12. Independent verification pass — Sep 12, on the CHIP network

Written by a second agent re-running this report, not by its author. Everything
in §§1–6 above was re-executed from scratch and **reproduced to the digit**
(`geom_probe`, `refl_extent`, `reflect_ab`, `paste_probe`, `himax_split`,
`coco_size_probe`, `loop_replay`, `sweep`). Three corrections were folded in
above (§4 code quote, §5 window definition and counts, §6 comparison cells and
the float/chip mismatch). One gap was closed:

**Every model result in §§1–6 is the float PyTorch checkpoint.** The two cells
that fail M7 worst — `A.static__ships`, `B.moving__ships` — fly `--backend chip`,
the DORY-quantised ONNX fed by `firmware_preprocess`. Nothing above had measured
that network. `scripts/chip_check.py` does, by driving
`perception_backends.ChipPerception` directly.

```
/Users/saimaruvada/Downloads/drone/trainenv/bin/python scripts/chip_check.py 700
```

(Needs `doryenv` — it spawns `chip_infer_server.py` under
`/Users/saimaruvada/Downloads/drone/doryenv/bin/python3`, because onnxruntime
lives only there. ~6 min.)

**(a) The mirror A/B, on the chip network, clean camera, firmware preprocessing:**

```
  chip  refl 0.2: outermost bucket>=2 at 3.10 m  over-read 1.28x
  chip  refl 0.0: outermost bucket>=2 at 2.40 m  over-read 0.99x
  float refl 0.2: outermost bucket>=2 at 2.80 m  over-read 1.15x
  float refl 0.0: outermost bucket>=2 at 2.20 m  over-read 0.91x
```

Same direction, same size. Turning the mirror off moves the chip network's flip
from 3.10 m to 2.40 m — 0.99× of the 2.428 m ideal, i.e. **the chip network with
no mirror reads the distance essentially exactly right.** §2's conclusion holds
on the network that actually flew.

**(b) The size head on real COCO images, chip vs float, same 128×128 input**
(first 700 val2017 images, 364 with a person):

```
  chip  bucket exact 0.5907  mean signed err +0.0054  median dec/GT 0.9845
  float bucket exact 0.6126  mean signed err -0.0345  median dec/GT 0.9214
  chip==float bucket agreement: 0.8599
  chip  effective 1->2 boundary true size 0.506 (nominal 0.500)
  float effective 1->2 boundary true size 0.544 (nominal 0.500)
```

**The chip size head is unbiased on real images to within 1%.** §3's central
claim — do not retrain or re-tune the size head — is confirmed on the deployed
network, more cleanly than on the float one.

### What the verification pass still doubts

- **`outermost bucket ≥ 2` is a fragile statistic.** It is a maximum over a
  noisy, non-monotonic curve. In §3.3's own table the himax/refl-0.0 row reads
  `P=0.00` at 2.90 m, `P=0.60` at 3.00 m, `P=0.00` at 3.10 m — the "3.00 m"
  answer is one seed-majority away from being 2.70 m. The float column changes
  from 2.80 m to 3.30 m purely by swapping PIL-bilinear preprocessing for
  `firmware_preprocess` (compare §3.3 against §12a). **The ±0.3 m of quoted
  precision on every `outermost` number is not real**, and §6's "about 40% of
  the himax residual is optical blur" (3.00 → 2.70 m) rests on exactly one such
  step. Treat the himax split as a direction, not a budget.
- **The replay is not a flight and now not the right network either** (§6).
  Cases C–H remain predictions.
- **Nothing here has been near hardware.** Unchanged from §9.

