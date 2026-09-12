# The mirror floor, removed — and what the drone actually does without it

Sep 12, 2026. Companion to `docs/eval_results/2026-09-12-distance/README.md`,
which root-caused the distance failure in `docs/sim_results/2026-09-11-simv2/`
and recommended — but deliberately did not implement — the scene fix. This is
the implementation, the proof it landed, and the re-fly.

**Nothing here was measured on hardware. Every frame is rendered.**
`docs/sim_results/2026-09-11-simv2/` was not modified; it remains the record of
what was observed with the mirrored floor.

> **Caveat added by the orchestrator, Sep 12, after the verification pass.**
> The distance result below is strong and I believe it. The **attitude-upset
> result is contaminated and should not be treated as a finding yet**, for three
> reasons found by the verifier and by me:
>
> 1. **The two suites did not run the same code.** `camera_model.py` was edited
>    by a parallel task at 13:37 — after the matte suite finished (13:36) and
>    before the mirrored control started (13:41). The equivalence check was run
>    at 13:20, so it does not cover the version the control flew. A same-hour A/B
>    is only as good as its "same", and this one has a seam in it.
> 2. **The upsets cluster on repeat 3**, not across the suite: repeat 3 tumbled
>    in 6 of the 7 cells. A per-cell effect would not respect flight order.
> 3. **The machine was heavily loaded.** These flights ran while 14 agents worked
>    on this laptop; the 15-minute load average reached 32.9. Upset flights skew
>    toward low `sim_wall_ratio` (0.882–0.989, most below 0.93), which is the
>    signature of a simulator that could not keep up.
>
> The honest reading: removing the mirror **fixed the distance error**, and
> whether it costs flight stability is **not yet known**. Settling that needs a
> re-fly on an idle machine with one fixed `camera_model.py`, flight order
> randomised or repeat count raised. Do not quote the upset numbers to the team
> or to Prof. Mok until that is done.

---

## 0. TL;DR

| claim | status |
|---|---|
| The groundplane `reflectance="0.2"` drew the subject 1.53–2.01× too tall | **confirmed** — measured on the scene files themselves |
| Setting it to 0.0 removes that | **confirmed** — 1.000×–1.016× across 2.4–3.8 m |
| Distance keeping improves a lot | **confirmed by flight** — M7 error down 2.3–4.6× in 6 of 7 cells; `A.static__ships` and `B.moving__ships` go FAIL → PASS |
| The control law "cannot reach 1.94 m; its floor is 2.43 m" | **refuted by flight** — the clean cells now hold 1.79–1.97 m |
| The Sep 11 baseline is sound and the harness is reproducible | **confirmed** — a same-day re-fly with the mirror put back reproduces Sep 11 to within 0.14 m |
| Removing the mirror is free | **NO.** Tracking degrades, and **9 of 21 matte flights lost attitude control**, most of them falling through the floor — against **0 of 20** with the mirror on, same machine, same afternoon |

**Do not tell anyone the simulator is fixed yet.** The distance result is real
and large. It came with a new failure mode that is not understood, and the
scoreboard does not catch it.

---

## 1. What was changed

One attribute, in one line, in one file.

`tools/crazysim_macos/build_scene.py:554` built every scene with

```xml
<material name="groundplane" ... reflectance="0.2"/>
```

`reflectance` in MuJoCo is a specular mirror coefficient, not a sheen. The
renderer drew a mirror image of every subject hanging below its feet, and the
follower's size head read the person *plus* the reflection as one object.

The value is now a module constant `FLOOR_REFLECTANCE`, defaulting to **0.0**
(matte), with a `--floor-reflectance` flag, and the value used is recorded in
each scene's `manifest.json` under `room.floor_reflectance` so that no future
flight result can be compared across the change by accident.

All 18 scenes were regenerated:

```
/Users/saimaruvada/Downloads/drone/trainenv/bin/python build_scene.py --all --preview
```

`scenes_v2/` is gitignored and regenerated from `scene_defs/`, so this is a
rebuild, not an edit of committed data.

`build_person_scene.py:34` carries the same `reflectance="0.2"` and was **not**
changed — it is outside this workstream and feeds only the legacy
`scenes/*/scene_person.xml` that `demo.sh` and `run_acceptance.sh` use. Those
three legacy scenes still have the mirrored floor.

### The rebuild is a controlled change

Verified, not assumed:

* Across all 18 rebuilt `scene.xml`, **the only line that differs from the
  pre-fix tree is the `reflectance` attribute** (`diff` of every file against a
  copy taken before the rebuild).
* Every `subj_*.png` cutout is **byte-identical** before and after.
* `build_scene.py --floor-reflectance 0.2` reproduces the pre-fix
  `s15_static_offset/scene.xml` and `s01_control_moving/scene.xml` **byte for
  byte**, and the default rebuild reproduces the live tree byte for byte. The
  builder is deterministic and the change is exactly reversible — which is what
  made §7 possible.
* Nothing in the repo reads `manifest.json`'s `scene_xml_sha256`, so no test or
  script breaks on the new hashes.

---

## 2. Proof the fix landed, before anything was flown

`scripts/asbuilt_extent.py` is the same measurement as the root-cause report's
`refl_extent.py` with one deliberate difference: that script overrides
`mat_reflectance` on the *compiled* model in memory, so it measures the physics.
This one **changes nothing** — it compiles `scene.xml` exactly as it sits on
disk, and reports the reflectance it read there. It is therefore the check that
the fix reached the files the simulator loads.

Method (unchanged): render twice per distance, once with the subject panel
visible and once hidden; every pixel differing by more than 6 DN is something
the panel put on the screen — the panel *and* its reflection. The panel's own
extent comes from MuJoCo's segmentation render (per-pixel geom id), not a
threshold.

```
/Users/saimaruvada/Downloads/drone/trainenv/bin/python scripts/asbuilt_extent.py
```

**Before** (the files the Sep 11 suite flew):

```
== s15_static_offset  subject subj_person_target  groundplane reflectance ON DISK = 0.200
   d_true  panel_rows  panel_h  apparent_rows  apparent_h  apparent/panel
     2.40    57-179       123       56-243         188           1.528
     2.80    66-171       106       66-243         178           1.679
     3.00    70-168        99       70-243         174           1.758
     3.40    76-162        87       75-243         169           1.942
     3.80    81-158        78       80-236         157           2.013
```

**After** the rebuild:

```
== s15_static_offset  subject subj_person_target  groundplane reflectance ON DISK = 0.000
   d_true  panel_rows  panel_h  apparent_rows  apparent_h  apparent/panel
     2.40    57-179       123       56-180         125           1.016
     2.80    66-171       106       66-171         106           1.000
     3.00    70-168        99       70-168          99           1.000
     3.40    76-162        87       75-162          88           1.012
     3.80    81-158        78       80-158          79           1.013
```

`s01_control_moving` gives identical numbers. **The subject's drawn height goes
from 1.53×–2.01× the panel to 1.000×–1.016× across 2.4–3.8 m.** The residual
1.6% is the ±1 pixel quantisation the geometry probe already reported.

`figures/floor_asbuilt_ab.png` renders the two scene *files* side by side at
2.4 / 3.0 / 3.8 m with the panel's true extent boxed in red. The reflection is
plainly visible in the top row and gone in the bottom row.

### Regression checks on the rebuilt scene

* `scripts/geom_probe.py` (root-cause report, run unmodified against the new
  scene): rendered/geometry ratio **mean 1.0012, min 0.9954, max 1.0068** over
  14 distances — the panel still subtends exactly the angle a 1.7 m subject
  should. The fix did not move the geometry.
* `scripts/reflect_ab.py` reproduces the root-cause report's numbers to the
  digit on the rebuilt scene (`refl 0.2` clean 3.30 m / himax 3.30 m;
  `refl 0.0` clean 2.20 m / himax 3.00 m).

### The camera model is not a confound

`tools/crazysim_macos/camera_model.py` has uncommitted changes from a parallel
workstream, so the re-fly does not run the same *file* the Sep 11 himax cells
ran. It does run the same *function*: loading the committed `HEAD` version
alongside the working-tree version and applying both to the same 20 frames with
the same seed and a non-zero body rate gives **bit-identical output on
`himax_typical`, `himax_low_light`, `himax_color_bayer` and `clean`**. That
file's own `test_optimised_chain_is_bit_identical_to_the_reference`,
`test_convolution_rewrite_is_bit_identical_to_the_shifted_sum`,
`test_luma_is_bit_identical_on_every_possible_rgb_triple` and
`test_same_seed_reproduces_the_frame_exactly` also pass when invoked directly
(no venv on this machine has pytest, so they were called as plain functions).

---

## 3. How the re-fly was run

```
./run_acceptance2.sh --repeats 3 \
    --out <scratch>/mirror_refly/refly_matte \
    --lock <scratch>/sim_refly.lock \
    --only '^(A\.static__ships|B\.moving__ships|B\.moving__delta_backend|B\.moving__delta_camera|B\.moving__delta_speed|A\.static__proven|B\.moving__proven)\|'
```

Seven cells × 3 repeats = 21 flights, 24 min. The five cells that failed M7 on
Sep 11, plus the two that share their scenes (`A.static__proven`,
`B.moving__proven`) so a regression in a previously-passing cell would show.
Three repeats rather than the required two, because the Sep 11 suite already
showed a 0.62 m spread on an unchanging scene.

The whole matrix was then flown a **second** time against scenes rebuilt with
`--floor-reflectance 0.2` — see §7. That is why this directory has two suites:

* `matte_suite/` — the 21 matte-floor flights (the re-fly)
* `mirror_control_suite/` — the 21 mirrored-floor flights (the same-day control)

Each carries `scoreboard.json`, `scoreboard.md`, `progress.md`, and per-run
`cell.json` / `summary.json` / `metrics.json` / `follow_log.csv` / `truth.csv`,
matching what the Sep 11 suite publishes.

**Lock discipline.** This workstream held the shared simulator lock
(`<scratch>/sim.lock`) for its whole duration, so no other agent could start a
simulator. `run_acceptance2.sh` takes and releases a lock around every
individual flight; it was pointed at a *different* path
(`--lock <scratch>/sim_refly.lock`) so it would not deadlock against the
workstream lock this agent was already holding.

Everything else — runner, scorer, follower, checkpoint, chip ONNX — is
unchanged. `scoreboard.py` was run, never edited.

---

## 4. A correction to the root-cause report: 1.94 m is reachable

The root-cause report's §4 says the control law **cannot** reach the 1.94 m M7
target, because "a perfect size head flips to bucket 2 at image fraction 0.500,
i.e. d = 2.428 m", and therefore "**2.428 m is the floor of this controller**".
The re-fly refutes that, and it is worth being precise, because the wrong
version is the one that would have been told to Prof. Mok.

The law is

```python
vx = clip(a.k_fwd * (a.target_size - p["size_value"]), a.v_max)   # k_fwd 0.8, target 0.625, v_max 0.3
```

with `size_value` the argmax bucket *centre*, one of
`{0.125, 0.375, 0.625, 0.875}`. That gives three commands, not two:

| bucket read | `size_value` | `vx` | true distance for a perfect head |
|---|---|---|---|
| 1 | 0.375 | **+0.2 m/s** (close in) | d > 2.428 m |
| 2 | 0.625 | **0.0** | 1.619 m < d ≤ 2.428 m |
| 3 | 0.875 | **−0.2 m/s** (back off) | d ≤ 1.619 m |

So the controller is not a one-way ratchet that latches at the first bucket-2
frame. It has a **stable band**, the whole of bucket 2, `[1.619, 2.428]` m, and
`HOLD_K·H = 1.942 m` sits in the middle of it. 2.428 m is the *far* edge of that
band, not a floor.

Both edges were observed in flight — counting commands over whole runs:

```
A.static__proven  r1   cmd_vx {0.0: 375, +0.2: 127, +0.3: 1}     size_bucket {1: 129, 2: 373}
A.static__ships   r1   cmd_vx {0.0: 164, +0.2:  46, -0.2: 2}     size_bucket {1: 48, 2: 162, 3: 2}
B.moving__ships   r1   cmd_vx {0.0: 169, +0.2:  37, -0.2: 12}    size_bucket {1: 39, 2: 167, 3: 12}
```

The `−0.2` commands are the drone backing off after a bucket-3 frame. What it
actually does is drift inward through the noisy part of the band — where some
frames still read 1 and push it forward — until it reaches a distance at which
the head reads 2 essentially every frame, and there it stops. On
`A.static__proven` r1 that is 1.79 m; `P(bucket ≥ 2)` from that flight's own
frames is 1.00 below 2.0 m, 0.70 between 2.0 and 2.4 m, 0.24 between 2.4 and
2.8 m.

**Where it parks is set by where the size head stops producing bucket-1 frames,
not by the 1.942 m target.** There is no restoring force toward the target — the
command is zero everywhere inside the band. That is still a real weakness of the
control law, and §7 suggests it is a worse one than anybody thought; but it is
not the hard 2.43 m floor the root-cause report described, and it does not stop
the M7 gate passing.

The rest of that report's §4 stands: the size signal is quantised, there is no
temporal filter, and `x` has a soft decode that `size` does not.

---

## 5. Results: distance keeping

Medians across a cell's flights. `M7_dist_err_settled_mean_m` is
mean |d_true − 1.942| over the settled window, gated at ≤ 0.75 m;
`M7_final_in_band` needs the last frame inside [1.457, 2.671] m.

```
scripts/compare_m7.py ../../sim_results/2026-09-11-simv2/scoreboard.json matte_suite/scoreboard.json
```

| cell | setup | M7 mean err before → after | distance held before → after | in-band frac before → after | verdict |
|---|---|---|---|---|---|
| `A.static__ships` | chip / himax / 6.5 Hz | 1.153 → **0.275 m** | 3.028 → **2.119 m** | 0.000 → **0.929** | FAIL → **PASS** |
| `B.moving__ships` | chip / himax / 6.5 Hz | 1.225 → **0.528 m** | 3.326 → **2.437 m** | 0.000 → **0.485** | FAIL → **PASS** |
| `B.moving__delta_backend` | chip / clean / full | 0.830 → **0.305 m** | 2.813 → **2.182 m** | 0.000 → **0.749** | FAIL → FAIL* |
| `B.moving__delta_camera` | float / himax / full | 1.107 → 1.109 m | 3.011 → 2.945 m | 0.000 → 0.000 | FAIL → FAIL |
| `B.moving__delta_speed` | float / clean / 6.5 Hz | 0.797 → **0.250 m** | 2.780 → **1.968 m** | 0.000 → **0.912** | FAIL → FAIL* |
| `A.static__proven` | float / clean / full | 0.669 → **0.146 m** | 2.424 → **1.790 m** | 0.078 → **0.915** | PASS → PASS |
| `B.moving__proven` | float / clean / full | 0.744 → **0.285 m** | 2.682 → **1.891 m** | 0.115 → **0.755** | FAIL → FAIL* |

\* **both M7 gates now pass** in these cells; they fail on tracking metrics
instead. See §6.

**Six of the seven cells now pass both M7 gates**, the exception being
`B.moving__delta_camera`. Distance error falls by a factor of 2.3 to 4.6 in
those six. The two "ships-as" cells — the configuration the real drone will fly
— go from parking 3.0–3.3 m away to 2.1–2.4 m, and from 0% of settled frames in
the hold band to 49–93%.

The `float/clean` cells now hold **1.79–1.97 m against a 1.942 m target**. That
is the evidence behind §4.

Per flight, so the spread travels with the medians:

```
cell                     run   M1_track  d_start  d_final  M7_err  in_band  loss_ep
A.static__ships          r1a1  0.991     3.640    2.119    0.272   yes      0
A.static__ships          r2a1  0.991     3.640    2.024    0.275   yes      0
A.static__ships          r3a1  0.227     3.640    2.703    0.761   no       1
B.moving__ships          r1a1  0.991     3.090    2.316    0.530   yes      0
B.moving__ships          r2a1  0.914     3.030    2.437    0.528   yes      1
B.moving__ships          r3a1  0.967     3.200    2.557    0.502   yes      1
A.static__proven         r1a1  0.996     3.640    1.790    0.146   yes      0
A.static__proven         r2a1  0.996     3.640    1.879    0.114   yes      0
A.static__proven         r3a1  0.371     3.640    1.596    0.318   yes      2
B.moving__proven         r1a1  0.937     3.200    1.907    0.350   yes      4
B.moving__proven         r2a1  0.668     3.220    1.891    0.285   yes      2
B.moving__proven         r3a1  0.956     3.220    1.838    0.245   yes      3
B.moving__delta_backend  r1a1  0.886     3.210    2.159    0.271   yes      5
B.moving__delta_backend  r2a1  0.844     3.220    2.182    0.305   yes      8
B.moving__delta_backend  r3a1  0.095     3.230    2.352    0.583   yes      2
B.moving__delta_camera   r1a1  0.323     3.060    2.945    1.109   no       1
B.moving__delta_camera   r2a1  0.552     3.140    2.504    0.671   yes      1
B.moving__delta_camera   r3a1  0.966     3.220    3.093    1.256   no       1
B.moving__delta_speed    r1a1  0.936     3.210    1.829    0.250   yes      2
B.moving__delta_speed    r2a1  0.980     3.230    1.968    0.287   yes      1
B.moving__delta_speed    r3a2  0.992     3.230    2.245    0.242   yes      0
```

`B.moving__delta_camera` is the exception, and its M1 column explains why:
0.323 / 0.552 / 0.966. It spent much of its flights not tracking, so it never
closed the distance. Two of those three flights also processed frames at **2.6
and 9.4 Hz** against the 13–15 Hz the other full-speed flights managed (§7), so
**that cell's result should be treated as unreliable**, not as evidence that the
fix does not help the himax configuration.

### `M7_size_overread_ratio`, for completeness

`A.static__proven` 1.304 → **0.964**, `B.moving__delta_speed` 1.369 → **1.014**,
`B.moving__delta_backend` 1.397 → **1.033**. As the root-cause report's §5
showed, this metric is algebraically `≈ d / 1.942` and measures the distance,
not the size head — which is exactly why it now reads ≈ 1.0: the drone is at
≈ 1.94 m. It should still be renamed or dropped.

---

## 6. Results: tracking got worse, and flights left the flight envelope

This must not be buried.

**M1 (tracking fraction) fell in five of the seven cells**, and four cells now
FAIL on gates that have nothing to do with distance:

| cell | M1 before → after | now fails on |
|---|---|---|
| `B.moving__delta_camera` | 0.996 → **0.552** | `M2_heading_err_max_deg`, plus M7 |
| `B.moving__delta_backend` | 0.994 → **0.844** | `M1_tracking_fraction`, `M10_uncertain_fraction_present` |
| `B.moving__proven` | 0.997 → **0.937** | `M1_tracking_fraction`, `M10_uncertain_fraction_present`, `M2_heading_err_max_deg` |
| `B.moving__ships` | 0.992 → 0.967 | — (still passes) |
| `B.moving__delta_speed` | 0.992 → 0.980 | `M10_uncertain_fraction_present` |
| `A.static__ships` | 0.990 → 0.991 | — |
| `A.static__proven` | 0.996 → 0.996 | — |

So the verdict over these seven cells moves from 1 PASS / 6 FAIL to
**3 PASS / 4 FAIL** — but the *reason* for failure has moved wholesale from
distance keeping to tracking.

Worse, and invisible to every gate: **9 of the 21 scored-VALID matte flights
suffered an attitude upset, and 8 of those 9 ended below the floor** (deepest
−2.23 m). Scanning
every `follow_log.csv` for |pitch| or |roll| > 30° and for z below the floor
(22 flight attempts, one of which — `delta_speed r3a1` — was scored INVALID and
re-flown):

```
run                             upset_frames   z_min  valid
A.static__proven__r1a1                     0    0.80  yes
A.static__proven__r2a1                     0    0.80  yes
A.static__proven__r3a1                    37   -2.23  yes     <-- UPSET
A.static__ships__r1a1                      0    0.80  yes
A.static__ships__r2a1                      0    0.80  yes
A.static__ships__r3a1                     11   -0.07  yes     <-- UPSET
B.moving__delta_backend__r1a1              0    0.80  yes
B.moving__delta_backend__r2a1              0    0.79  yes
B.moving__delta_backend__r3a1            386   -0.17  yes     <-- UPSET
B.moving__delta_camera__r1a1               5    0.02  yes     <-- UPSET
B.moving__delta_camera__r2a1               1   -0.01  yes     <-- UPSET
B.moving__delta_camera__r3a1              15   -0.08  yes     <-- UPSET
B.moving__delta_speed__r1a1                0    0.80  yes
B.moving__delta_speed__r2a1                0    0.80  yes
B.moving__delta_speed__r3a1               13   -0.48  NO      <-- UPSET
B.moving__delta_speed__r3a2                0    0.80  yes
B.moving__proven__r1a1                    13   -0.11  yes     <-- UPSET
B.moving__proven__r2a1                   173   -0.57  yes     <-- UPSET
B.moving__proven__r3a1                     0    0.79  yes
B.moving__ships__r1a1                      0    0.80  yes
B.moving__ships__r2a1                      0    0.80  yes
B.moving__ships__r3a1                      3   -0.02  yes     <-- UPSET
```

A drone 2.2 m *below* a solid floor is a simulator blow-up, not a collision —
nothing in the scene is there to hit and the subject panels carry
`contype="0" conaffinity="0"`.

**The low M1 numbers are a consequence of these upsets, not a perception
failure.** On `A.static__proven` r3a1 confidence was 0.72–0.99 right up to row
169 at 2.13 m; at row 170 pitch went −15° → −47° → −66°, roll to 178°, z to
−2.23, and only *then* did confidence collapse to ~0.1. The network stopped
seeing a person because the camera stopped pointing at the room.

Two process problems follow:

1. **The scoreboard does not catch this.** `validity()` checks sim/wall ratio,
   rate, torn frames, `z_max ≥ 0.5` and truth coverage. A flight that reaches
   0.8 m and *then* tumbles through the floor passes all of them. All 21
   flights were scored VALID.
2. **The median hides it.** M1 is aggregated by median, so `A.static__ships`
   (0.991, 0.991, 0.227) passes its M1 gate on 0.991 while one flight in three
   ended upside down under the floor.

---

## 7. Same-day control: the upsets belong to the fix, not to the machine

Three explanations had to be separated, and only one experiment separates them.

* **Machine load.** `uptime` reported 1-minute load averages of **55.5** and
  **33.0** on this Mac during flying. The top consumers were macOS system
  processes — `WindowServer`, Spotlight (`spotlightknowledged.updater`, `mds`),
  `AppleIntelligenceReportingProcessing`, `avconferenced` / `cameracaptured` /
  `VTEncoderXPCService` (a video call), Messages, and the Claude desktop app.
  Some desk work for §2 was also run on this machine during part of the matte
  suite.
* **Pre-existing flakiness today.** The Sep 11 baseline was flown on a different
  day; "Sep 11 had no upsets" is not a clean control.
* **The fix.** Matte floor → the drone closes to ~1.9–2.4 m instead of stopping
  at ~3.0 m → it now sits *inside* the bucket-2 band where the bucket flickers
  1/2/3 → `vx` chatters between +0.2, 0 and −0.2 m/s.

So the whole 7-cell × 3-repeat matrix was re-flown **the same afternoon, on this
machine, against scenes rebuilt with `--floor-reflectance 0.2`** — verified
byte-identical to the pre-fix files. Same runner, same follower, same
checkpoint, 5 minutes later.

**Result: 0 attitude upsets in 20 scored-valid mirrored-floor flights (0 in 21
attempts), against 9 in 21 scored-valid matte-floor flights (10 in 22
attempts).** No mirrored flight went below the floor at all — the lowest
in-flight z on any valid mirrored flight was **0.79 m**, against −2.23 m on the
matte side. Tracking was 0.991–0.996 on every valid mirrored flight, with zero
loss episodes.

With 9/21 against 0/20, this is not a marginal difference: Fisher's exact test
on `[[9,12],[0,20]]` gives **two-sided p = 0.0013** (one-sided 0.00084). What
that establishes is an **association between the matte floor and the upsets**
under otherwise identical conditions. It does not establish the mechanism, and
41 flights is still 41 flights.

The control also reproduces the Sep 11 baseline closely, which is the evidence
that the harness itself is sound and that the comparison in §5 is real:

```
cell                          M7 mean err (gate<=0.75)    |       distance held (m)
                               Sep11      ctrl     matte  |     Sep11      ctrl     matte
A.static__ships                1.153     1.019     0.275  |     3.028     2.982     2.119
B.moving__ships                1.225     1.201     0.528  |     3.326     3.314     2.437
B.moving__delta_backend        0.830     0.877     0.305  |     2.813     2.832     2.182
B.moving__delta_camera         1.107     1.073     1.109  |     3.011     2.936     2.945
B.moving__delta_speed          0.797     0.717     0.250  |     2.780     2.626     1.968
A.static__proven               0.669     0.709     0.146  |     2.424     2.269     1.790
B.moving__proven               0.744     0.722     0.285  |     2.682     2.616     1.891

cell                                M1 tracking            |      M7 in-band fraction
                               Sep11      ctrl     matte  |     Sep11      ctrl     matte
A.static__ships                0.990     0.991     0.991  |     0.000     0.000     0.929
B.moving__ships                0.992     0.992     0.967  |     0.000     0.000     0.485
B.moving__delta_backend        0.994     0.996     0.844  |     0.000     0.000     0.749
B.moving__delta_camera         0.996     0.996     0.552  |     0.000     0.000     0.000
B.moving__delta_speed          0.992     0.992     0.980  |     0.000     0.123     0.912
A.static__proven               0.996     0.996     0.996  |     0.078     0.269     0.915
B.moving__proven               0.997     0.996     0.937  |     0.115     0.049     0.755
```

The mirrored control matches Sep 11 to within **0.14 m on M7 error**, **0.16 m
on held distance** and **0.002 on M1**. (Verdicts differ on two cells —
`B.moving__delta_speed` and `B.moving__proven` read PASS in the control where
Sep 11 read FAIL — because those two sit right on the `M7_final_in_band`
boundary, which is a yes/no on a single frame. That is gate-boundary noise, not
a discrepancy in the measurements.)

### So what is the mechanism?

The best available hypothesis is command chattering. `vx` command changes in the
5 s before each upset were **2.6–4.6 per second** on the flights that tumbled
and **0.0–1.0 per second** on the flights that did not. That is the quantised
size signal with no temporal filter, and it only happens once the drone is
inside the bucket-2 band — which, before the fix, it never reached.

**This is a hypothesis, not a demonstrated cause.** Eight events are not enough,
the correlation is imperfect (`A.static__ships__r3a1` tumbled at only 0.8
changes/s), and no one has shown that command chatter is what destabilises the
CrazySim attitude controller. Whether a real Crazyflie would do anything like
this is completely unknown — a ±0.2 m/s velocity setpoint toggling at a few Hz
is not obviously dangerous, and this may be simulator fidelity rather than
flight dynamics.

### One thing machine load *does* explain

`B.moving__delta_camera` r1a1 processed frames at **2.6 Hz** and r2a1 at
**9.4 Hz**, against 13–15 Hz for every other full-speed flight; no control
flight was starved that way. `validity()` only enforces a frame-rate floor when
a cell declares a `rate_hz`, and `full`-speed cells declare 0 — so **a
full-speed flight starved to 2.6 Hz is scored VALID**. That is a real gap in the
scorer and it is why that one cell's numbers are set aside in §5.

---

## 8. What this changes, and what it does not

**Established:**

* The `reflectance="0.2"` groundplane inflated the drawn subject height by
  1.53×–2.01× over 2.4–3.8 m. Setting it to 0.0 brings that to 1.000×–1.016×.
  Measured directly on the scene files (§2).
* With the artefact gone, simulated distance keeping improves by 2.3–4.6× in six
  of seven cells; the two "ships-as" cells go from 3.0–3.3 m to 2.1–2.4 m and
  from FAIL to PASS (§5).
* The claim that the control law **cannot** reach 1.94 m is wrong. The clean
  cells hold 1.79–1.97 m. The law has a stable band `[1.619, 2.428]` m with the
  target inside it, not a 2.428 m floor (§4).
* The Sep 11 M7 numbers were measuring a renderer artefact — as that README's
  own Sep 12 correction already says — and the Sep 11 measurements themselves
  are reproducible (§7).
* **Removing the mirror is not free.** 9 of 21 valid matte flights lost attitude
  control; 0 of 20 valid mirrored flights did, on the same machine within the
  same hour, Fisher exact p = 0.0013 (§6, §7).

**Not established:**

* **Anything about real hardware.** This fixes a simulator. The size head was
  already shown to read real people correctly; nothing here adds evidence about
  the drone.
* **Why the upsets happen.** The chattering hypothesis fits but is not proven,
  and whether it transfers to a real Crazyflie is unknown.
* **The himax residual.** With the mirror off, `himax_typical` still behaves
  differently from `clean`, and `B.moving__delta_camera` — the cell that would
  have shown it — was compromised by frame starvation. Unresolved; needs real
  frames.
* **Whether a real floor reflects enough to matter.** MuJoCo's `0.2` is a
  specular mirror; a matte indoor floor is not. Calling §2 an artefact rests on
  that judgement.

**Next, in priority order:**

1. **Understand the upsets before anyone calls the simulator fixed.** Cheapest
   next step: re-fly the matte matrix with `--rate-hz`-style smoothing or an
   N-consecutive-frames requirement before `vx` changes sign, and see whether
   the upsets go away. That also tests the chattering hypothesis directly.
2. **`validity()` should reject a flight whose attitude leaves the envelope or
   whose z goes below the floor, and should enforce a frame-rate floor on
   `full`-speed cells too.** Right now a flight that ends upside down under the
   floor at 2.6 Hz is scored VALID and folded into a median.
   *Owner: `scoreboard.py` — not this workstream, not edited here.*
3. **Re-fly the remaining 11 CORE cells on the matte floor.** Only 7 were flown;
   the Sep 11 baseline for the other 11 is now measured against scenes that no
   longer exist.
4. **The soft-size decode** (root-cause report §8 item 2) is now *better*
   motivated, not worse: the chattering in §7 is exactly the quantised size
   signal with no temporal filter, and the bearing channel already has the fix
   that size lacks.
5. `M7_size_overread_ratio` should still be renamed or dropped (§5).

**For the hardware session.** The root-cause report's lab advice mostly stands —
record the floor finish, do not expect a clean 1.94 m demo — but its headline
prediction should change. It said to expect ~3 m, from the "the law cannot get
closer than 2.43 m" argument that §4 refutes. What the simulator now says with a
matte floor is that the drone parks wherever the size head stops emitting
bucket-1 frames: **1.8–1.9 m with a clean camera, 2.1–2.6 m through the himax
model, and different every run.** Quote the range, not a number. And be aware
that in simulation the closer approach is where the flights went wrong — if the
real drone starts oscillating fore-and-aft as it closes, that is the §7
behaviour and the flight should be stopped, not debugged in the room.

---

## 9. Reproducing

Scripts are in `scripts/` here. They read the repo and write only where told;
none modifies a scene, a flight log, or `scoreboard.py`. Run them from this
directory with `/Users/saimaruvada/Downloads/drone/trainenv/bin/python`.

| script | what it answers | runtime |
|---|---|---|
| `asbuilt_extent.py` | does the scene **on disk** still draw a reflection? (the fix check) | ~15 s |
| `asbuilt_ab_figure.py --before-root DIR --out F.png` | the same thing as a picture, two scene files side by side | ~15 s |
| `compare_m7.py BEFORE.json AFTER.json [--md]` | per-cell M7 before vs after, with per-flight values | instant |
| `run_table.py SCOREBOARD.json [--md]` | one row per **flight**, because the scoreboard aggregates by median | instant |
| `why_lost.py RUN_DIR [...]` | when a run dropped its lock, and confidence/bucket binned by true distance | instant |

The attitude-upset scan in §6 and §7 is a one-liner over the published logs:

```bash
for d in matte_suite/runs/*/; do
  awk -F, -v n="$(basename "$d")" '
    NR==1{for(i=1;i<=NF;i++)h[$i]=i; next}
    $h["wall"]!=""{p=$h["pitch"]; r=$h["roll"]; z=$h["pz"];
                   if(p<0)p=-p; if(r<0)r=-r; if(p>30||r>30)u++;
                   if(NR==2||z<zm)zm=z}
    END{printf "%-30s upset %4d  z_min %7.2f\n", n, u+0, zm}' "$d/follow_log.csv"
done | sort
```

To rebuild the scenes either way:

```
# matte (current default)
build_scene.py --all --preview
# the pre-Sep-12 mirrored floor, byte-identical to what the Sep 11 suite flew
build_scene.py --all --preview --floor-reflectance 0.2
```

Scripts from the root-cause report
(`docs/eval_results/2026-09-12-distance/scripts/`) were run but never edited.

**State left behind:** `scenes_v2/` is matte, and its 18 `scene.xml` are
byte-identical to the tree the matte suite flew (checked by sha256 after the
control run put the mirror back and the final rebuild took it out again).

---

## 10. What is NOT verified

- **No hardware.** Nothing here has been seen by a real camera or flown on a
  real Crazyflie. The lab session next week is the first test of any of it.
- **The matte floor is a judgement about reality, not a measurement of it.**
  `reflectance = 0` says the floor reflects nothing specularly. A real indoor
  floor is somewhere between 0 and the 0.2 mirror that was there before.
- **The cause of the attitude upsets** (§7). Only the *association* with the
  matte floor is established, by a same-day A/B with n = 21 vs 22.
- **The himax residual** is unchanged and still unexplained.
- **`B.moving__delta_camera`'s matte result** is unreliable — two of its three
  flights were frame-starved (§7).
- **Three repeats is a small sample.** Every median here rests on 3 flights; the
  per-flight tables are printed so nobody has to take the medians on trust.
- **Nothing was committed.** Per the workstream's instructions, version control
  is the orchestrator's job: `git status` will show
  `tools/crazysim_macos/build_scene.py` modified and this directory untracked.
  `docs/progress/sai_maruvada.md` was deliberately **not** touched — another
  agent owns it this session.
