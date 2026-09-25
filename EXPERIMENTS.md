# Experiment Log

## Sep 24, 2026 (22:15) — Camera exposure is random per power-up, in our flight app too (Sai)

Drone 09, untouched on the chair, room lights, 5 battery power-cycles in 4 minutes:
mean brightness **146 / 76 / 42 / 78 / 74**. Counting the night's runs, the range is
**4-146** for the same scene. The cause is the one-time `PI_CAMERA_CMD_AEG_INIT` plus
per-frame start/stop in the stock streamer, and the same code is in
`crazyflie_ssd/src/camera_if.c`, so real flights would inherit it. Firmware fix
proposed: fixed or continuous exposure, plus a brightness-floor guard. Data
collection now only records inside a 30-60 brightness band (`grid_capture.sh`
pre-flight check). Evidence: `docs/eval_results/2026-09-24-grid-capture/`.

## Sep 24, 2026 (22:00) — A complete grid recorded only noise; the champion locks on noise (Sai)

The first complete 9-position grid on one full battery (`grid_capture_215739`, drone 09)
was **all near-black** (mean 4.1): sensor noise and banding, no scene. The champion
scored every frame ~0.84 and the follower locked (24/26 on the empty room). Together
with run `204144`, that is 169 near-black frames read as a confident person, so a
brightness-floor guard in the firmware is recommended. The earlier "dying battery"
cause is withdrawn (full battery here). Likely cause: the stock streamer sets exposure
once at startup (`PI_CAMERA_CMD_AEG_INIT`) and starts and stops the sensor per frame.
The same room gave brightness 4 / 7 / 40 / 90 across power-ups. Test: repeated
power-cycles with nothing else changed, logged with `exposure_check.sh`. Evidence:
`docs/eval_results/2026-09-24-grid-capture/`.

## Sep 24, 2026 (night) — Dim-grid replication; near-black frames lock; two camera exposure modes (Sai)

- **Clean dim run** (`grid_capture_204502`, brightness 38-41, 7 of 9 positions)
  replicates the 18:31 dim run. Left is strong: 0.83-0.87 median, 15 of 17 locked.
  **Dead centre in front of the dark door is missed again:** 2.44 m 0.54 / 0 locked,
  2.13 m 0.72 / 1 locked. Right is middling. Empty room: 0 locks (peak 0.79). Mirror
  check: both sides mostly correct.
- **Safety:** a near-black run (mean 6.6, dying battery) scored the empty room at 0.83,
  and the follower locked 19 of 21 frames. Proposed: reject near-black frames before
  steering.
- **Exposure:** the same room and lights gave brightness ~40 or ~90 depending on the run.
  In the bright mode, 2.44 m LEFT fell from 0.86-0.90 to 0.29. The cause is unknown
  (drone vs power-up); `exposure_check.sh` is added to find out.

Evidence: `docs/eval_results/2026-09-24-grid-capture/` (night section and per-run
subfolders).

## Sep 24, 2026 — First real-person detection grid (partial): contrast beats position (Sai)

`tools/real_frames/grid_capture.sh`, one subject, dorm, chip arm. The empty clip plus 5
of 9 positions were captured before the battery died. At 2.13 and 2.44 m off-centre
(+-14 to 16 deg): median conf 0.77-0.88, follower locked 71-88%, correct side. Dead
centre at both distances: median 0.52 and 0.66, **locked 0%**, and the model reads the
room's right-side background instead. The frames show the subject against a dark door
at centre and against bright wardrobe panels at the sides. So subject/background
contrast is the likely driver. It is confounded with position in this room; the planned
control is centre with a light sheet over the door. Empty room: 0 false locks (max
0.65). Evidence: `docs/eval_results/2026-09-24-grid-capture/`.
*Update 18:47 (resumed run):* 8 of 9 positions captured, but the resumed clips were **2.3x brighter** (mean 94 vs 40), so there are two lighting conditions. In the bright run, centre at 1.52 m was detected (0.93, locked 14/17), consistent with contrast but confounded with distance and light. 2.13 m RIGHT (bright) was weak (0.54, 0 locked) and is unexplained. Next: a full grid in one sitting at one lighting level.

## Sep 24, 2026 — Lighthouse in the dorm: frame matches the tape, yaw sign confirmed on hardware (Sai)

Two SteamVR 2.0 base stations (channel 1 at the window end, channel 2 at the door end)
on stands, and drone 1 (AI-deck + Lighthouse deck) on USB. The frame: +x toward the
door, the SIDE mark at +y 0.61 m. Geometry wizard, cfclient 2026.8:

| attempt | floor samples | XYZ samples | origin / SIDE error | sample held over the origin |
|---|---|---|---|---|
| 1-2 (FLAWED) | bare tile | bunched at the door end (x 1.1-1.95) | 78-79 mm | read x 1.29, frame displaced |
| 3 | on a book | spread over the room, starting over the origin | 1.2 / 1.0 mm (all rows 0.3-2.0 mm) | read (0.07, -0.03) |

Tape check (`tools/lighthouse/tape_check.py`, read-only), against attempt 3:

- **Bare floor: 4/4 PASS.**
- **Book: 4/4 PASS** after one re-placement. The first book run caught the drone
  sitting 8 cm short of the +x mark.
- Every x, y is within 3 cm on both surfaces.
- **The yaw sign is confirmed on hardware:** a 90-degree left turn read +89.1, +91.4
  and +94.6 deg.
- **Floor reflection is ruled out** as the cause of attempts 1-2. The bunched XYZ
  samples are the remaining explanation. I had first proposed reflection mid-session,
  then withdrew it once the bare-floor run passed. Both are kept in the log.

Geometry: `docs/hardware/lighthouse/dorm_lighthouse_2026-09-24.yaml`. Log and JSONs:
`docs/eval_results/2026-09-24-lighthouse-dorm-setup/`.

## Sep 22, 2026 — First real AI-deck frames: not mirrored; furniture false positive; stream differs from the sim (Sai)

Dorm, drone on a chair with the lens about 0.8 m up, one subject (Sai), marks at
2.44 m and +-14 deg. Chip arm throughout.

- **Run 1:** the network said bin 7 in 41 of 44 frames wherever Sai stood. Probes
  located a **false positive on furniture** in the right third of the frame: blanking
  that region moved the answer to centre with confidence around 0.23, and mirroring the
  frame moved it to bin 1. The follower would have latched on 32% of the LEFT-clip
  frames.
- **Run 2, chairs removed:**
  - The empty room gave **0 false locks** (peak 0.71).
  - Mirror check: on confident frames, 10 of 12 were on the correct side. The scorer's
    FAIL came from the subject leaving the LEFT mark at frame 15.
  - **The camera is not mirrored.**
- **The stream is 162 x 122, pixels 0-191, about 2 fps.** That is not the simulator's
  324 x 244 with a 0-255 range. It is mono: the Bayer phase means are all equal.

Real frames stay on the laptop because they show people; only numbers are committed.
Evidence: `docs/eval_results/2026-09-22-first-real-frames/`.

## Sep 22, 2026 — The scorer defaults to the chip arm; the Sep 17 chip rescore was wrong (Sai)

`tools/real_frames/score_real_frames.py` gains `--backend {float,chip}`, default
**chip** (firmware preprocess + `model_id_dory.onnx`, eps 2.009823510888964e-4
from the release, follower on raw 5467 / -998 / 3), reusing
`perception_backends.ChipPerception`. Branch `sai/score-real-frames-chip-backend`.

| check | result |
|---|---|
| chip scorer vs the simulator's flight path, 51 frames | all 14 int32 outputs identical |
| `--backend float` vs the pre-backend scorer (b1a0108) | CSV byte-identical |
| Sep 17 `rescore_chip.py` | reproduced 51/51 **only** by preprocessing twice: it is not the chip arm |
| Sep 16 grid re-rendered, float arm | 13,000/13,000 frames match Sep 16 to 4 dp |
| real chip minus float, 13,000 frames | **-0.020** mean conf, **-0.043** frac >= 0.75, 45/325 cells move >= 0.25 (Sep 17 said -0.124 / -0.239 / 122) |

Sep 16 conclusions on the chip arm: the pose-four / hard-four split, the bearing
cost shape, the 2.5 m finding, the 3.5 m b0 reference (median 0.975, 4 of 13 at
0.000) and the mirror check survive. The 25-degree left/right asymmetry does not
(+0.059 becomes -0.007). The hard four at 1.5 m weaken to 0.75 / 0.95 / 0.40 / 0.40.
Evidence: `docs/eval_results/2026-09-22-sep16-chip-rescore/`. Rendered frames only.

## Sep 12, 2026 — CORRECTION: the distance failure is a reflective simulator floor, not the size head (Sai)

The Sep 12 simulator entry below reported that the drone settles at about 3.0-3.3 m
instead of 1.94 m **because the size head over-reads by 1.6-1.8x**. The observation is
right; **the cause is wrong and is withdrawn.** Evidence, with a reproduction command
behind every number: `docs/eval_results/2026-09-12-distance/`.

| claim | status |
|---|---|
| the drone settles near 3 m instead of 1.94 m, and those cells FAIL | **unchanged** - still true, still failing |
| the size head over-reads by 1.6-1.8x | **withdrawn** - mean signed error **-0.015** over the 2635 COCO val2017 images with a person, **-0.007** over the 1475 in the follower's own 0.25-0.85 size regime, -0.043 over the intermediate subset: every subset *under*-reads. On a 700-image slice the deployed chip network scores **+0.005**, with its bucket boundary at true size 0.506 against a nominal 0.500. The head is noisy (bucket exact-match 0.45-0.61), not biased |
| the scene geometry is honest ("the person spans 99.4% of the panel") | **true but not the question** - that measures the texture on the card. The card's contribution to the image is 1.53x the panel at 2.4 m rising to 2.01x at 3.8 m |
| cause of that | **the MuJoCo groundplane material carries `reflectance="0.2"`, a 20% mirror**, in `build_scene.py` (the `groundplane` material, line 554 as the suite was flown) and `build_person_scene.py:34`, so the network reads the person plus their reflection as one object. Flip it to 0.0 in the compiled model and the chip network reads 0.99x of ideal |
| the M7 gate's 1.94 m target is reachable | **refuted** - `follow_person.py:367` zeroes forward velocity on a single argmax bucket-2 frame, and a perfect size head flips at 2.428 m. 0.486 m of every M7 error is structural |
| `M7_size_overread_ratio` measures the size head | **refuted** - its window starts at the first bucket-2 frame, so it reduces to `d / 1.942`. Checked against the published `scoreboard.json`: 1.649 vs 1.631, 1.567 vs 1.570, 1.304 vs 1.344 |

**Consequence.** The Sep 11 suite's M7 cells characterise a simulator artefact plus an
unreachable gate. They must not be cited as evidence about the drone's real
distance-keeping ability. **Do not retrain or re-tune the size head on the strength of
them.** Nothing else in the suite is affected: the pet result, the occlusion results,
the pointing errors, the empty-room and furniture results and both earlier reviews all
stand, and no verdict changed (still 7 pass / 7 fail).

**Not fixed, and not this correction's to fix:** setting `reflectance` to 0.0 invalidates
every scene on disk and every published simulator result including the September
baselines (team call); giving `size` the soft decode `x` already has changes flight
behaviour six days before the first hardware session and must be flown; and M7 needs a
decision about whether it gates 2.428 m or the law changes. `scoreboard.py` still names
the metric `M7_size_overread_ratio` and still targets 1.942 m. **None of the three had
been flown when this entry was written**; the predicted effect of the scene fix comes
from a render-in-the-loop replay of the forward channel on the float network, not from
the acceptance suite. A re-fly, if one happens, belongs under `docs/eval_results/`.

**Status update, later the same day:** the scene builder has since set the groundplane matte by default (`FLOOR_REFLECTANCE = 0.0`, with a `--floor-reflectance` flag to reproduce the old scenes) and rebuilt the 18 `scenes_v2` scenes, which now carry `reflectance="0"`. That is item (a) landing, in the working tree, not yet committed. A re-fly is in progress under `docs/eval_results/2026-09-12-mirror-refly/`, whose README is still a placeholder marked "do not cite" — **so item (a) is implemented but its effect on the suite is still UNFLOWN and unverified here.** Items (b) and (c) are untouched.

**Nothing here touched hardware, and nothing was re-flown.** The report's own hardware
expectation - that a real drone stops wherever the first false bucket-2 frame fires,
around 3 m, at a different distance every run, for reasons unrelated to the mirror - is
a desk calculation from COCO statistics and is UNVERIFIED.

## Sep 12, 2026 — A realistic simulator, and what it says about the drone we plan to fly (Sai)

> **Corrected Sep 12 (same day):** the distance finding below is real as an observation but its
> stated cause — "the size head over-reads by 1.6-1.8x" — is **withdrawn**. The cause is a 20%
> reflective MuJoCo groundplane that draws subjects 1.5-2.0x too tall, plus a control law whose
> reachable floor is 2.43 m, so the 1.94 m target was unreachable. The size head reads real
> people correctly. See the correction entry at the top of this log. Every other finding here
> stands.

The simulator used to fly the float model against clean renders. It now models
the camera we actually have and runs the network we actually ship: a Himax
HM01B0 sensor model (auto-exposure to 60 DN, 16.59 ms frame time at 60 fps,
read noise, motion blur), a chip-in-the-loop mode that runs the real DORY int8
network through the chip's own 2x2 preprocessing, and 18 scenes built from JSON
definitions with ground truth for every subject. Scored by ten measurements
with pass/fail limits (`tools/crazysim_macos/scoreboard.py`).

A 14-cell matrix, 37 flights, 36 valid: **7 cells pass, 7 fail.** Full evidence,
including every flight's record, in `docs/sim_results/2026-09-11-simv2/`.

| finding | detail |
|---|---|
| the drone chases a dog | confirmed 0.31 s in at confidence 0.87-0.89, latched 68-78% of the flight, drifted 2.301 m and 2.666 m against a 0.5 m limit; survives the chip network and the realistic camera |
| it does not hold its distance | settles at about 3.0-3.3 m where it should hold 1.94 m, in every chip configuration. **Cause withdrawn Sep 12:** this was published as "the size head over-reads by 1.6-1.8x"; it is a reflective simulator floor plus an unreachable target. See the correction entry |
| realism costs, isolated one factor at a time | realistic camera +0.32 m of distance error, chip network +0.13 m, chip frame rate +0.10 m |
| what survives realism | pointing accuracy and every safety rule |

The pet result is the closed-loop evidence for the champion-vs-confuser choice
(per-frame false alarms: champion 30.2%, confuser 11.0%). That cell is red by
design and must not be quietly disabled.

Known and unfixed, so nobody reads more into this than it supports: on the worst
frames the sensor model costs 7.27 ms against a 5 ms budget (6 of 16 runs);
subjects are still opaque rectangular cards with baked backgrounds (MuJoCo 3.13
drops the alpha channel); nine camera parameters come from the datasheet and
have **never been measured** against a real Himax; scene s09 does not test the
far-person case it was written for. Nothing here has run on hardware.

## Sep 12, 2026 — Three faults in my own scoring tool (Sai)

Found while publishing the suite above, and worth recording because two of them
corrupt evidence rather than just misreport it.

| fault | effect | fix |
|---|---|---|
| hard gates labelled "worst repeat" kept the *first failing* repeat | the pet drift was published as 2.301 m when the worse repeat was 2.666 m; no verdict changed, but the printed safety number understated what was observed | the gate now compares repeats and keeps the numerically worst |
| re-scoring the published evidence folder destroyed it | the folder keeps one representative flight's `follow_log.csv` per cell, by design, to stay about 3 MB; re-scoring rewrote the other 23 flights' records as "fewer than 2 control steps" and dropped every cell to INVALID | a flight with no log but a stored record is scored from that record, left untouched, and named on stdout |
| the folder's `suite_meta.json` named a different sweep | it carried the original core sweep's label and 1895 s duration while holding the merged suite's flights; the board only read `core-rescore` because the label was passed by hand | corrected to the merged suite's own identity, so the folder is self-describing |

The published folder now re-scores to a byte-identical result twice running, and
re-scoring a full suite is unchanged (verified byte-identical against a board
built by the unpatched scorer).

## Sep 11, 2026 — Champion network integrated into the drone firmware (local branch, simulator-verified) (Sai)

The drone firmware (`crazyflie-ssd`) still carried an older Aug 27 network.
A local branch now carries the validated champion with 8 cores, the tested
decoder, a 2x2 camera resize, and a v6 flight-controller packet. It compiles
and links (18.4% of L2). Six fix rounds, each re-checked by an independent
reviewer with a timing simulator, closed these safety gaps:

| gap | fix |
|---|---|
| failed inference decoded as a fresh frame | output poisoned before each run, failures rejected |
| camera or pipeline failure kept tracking on | tracking reset plus a no-target packet |
| frame age capped below the 3 s land rule | 20 ms units (up to 5.08 s), flight controller tracks last fresh time |
| brief stall let steering resume on one frame | re-confirmation after 0.4 s gaps, measured at the radio transfer |
| delayed packets looked fresh | age finalized at the SPI transfer, send timestamp for the flight controller |

With the documented flight-controller rules, the simulator shows landing
about 3.0 s after the last good frame, no steering on frames older than
0.5 s, and fresh re-confirmation after every stale hover, across every
named failure timeline and 500-run random mixes. Not run on hardware; the
flight-controller handler is still to be written. Delivered as a git
bundle with a hand-off: `docs/firmware_integration/`.

## Sep 11, 2026 — The epoch-2 QAT confuser passes the chip gates but gains nothing on the chip (Sai)

Released on the 576-image pack (`logs/plain_follow_eval576_confuser_qathn3_ep2`):
all five gates pass (91.1% agreement, 6 confident disagreements). On the
1,000 random images (`docs/eval_results/2026-09-11-unbiased/`), its chip
network scores F1 0.740, recall at 0.7 of 0.500, empty-scene false alarms
3.7% at 0.7 and pet/mannequin false alarms 10.6%. That is about the same as
the plain confuser (0.757, 0.511, 2.8%, 11.0%), and it overturns confident
float calls more often (7 of 874 vs 1 of 875).

Why: the release strips the activation ranges learned in QAT and
recalibrates them. In fake-quant form with its learned ranges, epoch 2 has
a slice rate of 8.4%; on the chip it is 10.6%. The QAT benefit does not
ship. Next step for a model with both strengths: implement Grace's
`--preserve-qat-alphas` release option (sketched in her Aug 31 entry on
`grace/qat-alpha-preserve`) and re-release. Until then the team's choice is
the champion or the plain confuser.

## Sep 11, 2026 — Simulator follower re-confirms targets after any stale-frame hover (Sai)

A safety review of the drone firmware found that a short perception stall
left the target "confirmed", so steering could resume on the first fresh
frame. The simulator follower had the same gap. Now, whenever the stale-hover
rule fires (newest frame older than 0.5 s), `follow_person.py` drops the
target and needs 3 fresh frames at p >= 0.7 before steering again. New test
option: `--simulate-stale-for SECONDS` (a freeze that ends). Verified in
three flights and by an independent log check:

| flight | result |
|---|---|
| moving person, 50 s | 99.6% tracked, 2.9 deg mean / 7.6 max heading error (baseline 2.7 / 6.6) |
| camera frozen at 20 s | hover from 0.52 s frame age, land at 3.0 s, as before |
| camera frozen 1.5 s at 20 s | hover; first two fresh frames ignored even at confidence 1.00; steering resumes on the third |

Caveat: the Mac screen was locked, so the viewer crashed and all three
flights ran with a headless launcher (camera at about 12.9 Hz vs 14.4 Hz),
which likely explains the extra 0.2 deg. The firmware branch got the
matching fix (re-confirmation after 0.4 s gaps, non-blocking app packets).

## Sep 11, 2026 — 3-epoch QAT with hard-negative mining restores the confuser gain (Sai)

Three epochs of QAT from confuser ep8 (lr 2e-5, cosine, confuser manifest,
hard-negative mining from epoch 1), scored in fake-quant form with learned
alphas (`export/confuser_slice_eval.py`, `export/sweep_fq_ckpt.py --mode qat`):

| checkpoint | slice FP @0.45 / @0.55 | peak F1 (threshold) |
|---|---|---|
| confuser ep8 (start, no QAT) | 0.083 / 0.052 | 0.7947 |
| epoch 1 | 0.174 / 0.117 | 0.7954 (0.40) |
| **epoch 2** | **0.084 / 0.047** | **0.7913 (0.30)** |
| epoch 3 | 0.086 / 0.052 | 0.7885 (0.30) |
| QAT champion (reference) | 0.239 / 0.171 | 0.8008 (0.45) |

Epoch 2 matches the original confuser's false-alarm rate while carrying
QAT, at about one F1 point below the champion. The best threshold moved to
0.30, so the model became more conservative. Caveat: one unseeded run.
Epoch 2 is being released on the 576-image pack.

`train.py` now has `--seed` (on `successor-release`): two 40-batch runs
with `--seed 0` gave identical losses and validation numbers; unseeded runs
differ. Use it with 3+ repeats before reporting training results.

## Sep 11, 2026 — The firmware's image resize costs recall; a 2x2 average fixes it (Sai)

The drone firmware (`crazyflie_ssd/src/preprocess.c`) shrinks the 244x244
camera crop to 128x128 by picking one pixel (nearest neighbor), while
training used a smoothed resize. On 1,000 random val2017 images rendered as
324x244 camera frames (verified independently; the real C file was compiled
and matched the study's port byte for byte):

| champion integer network, F1 at the 0.7 enter threshold | value | vs training resize (95% CI) |
|---|---|---|
| training resize | 0.750 | - |
| firmware nearest neighbor | 0.700 | -0.050 (-0.079 to -0.020) |
| proposed 2x2 block average | 0.753 | +0.004 (-0.016 to +0.024) |

Nearest neighbor flips about 13% of visibility decisions and mostly misses
people at the 0.7 threshold; the float champion and the confuser show the
same pattern. Averaging each 2x2 camera block at the same source position
(about 10 lines of C) brings decisions to the noise level of a one-pixel
camera shift. Caveat: the frames are clean downscaled photos, not real
HM01B0 frames; a short real capture should confirm. Files:
`docs/eval_results/2026-09-11-resize/`. Being applied on the local firmware
integration branch.

## Sep 11, 2026 — All three candidates pass the gates on a 576-image pack (Sai)

Each candidate was re-released with a 576-image evaluation pack (rep16 plus
560 COCO val images; 140 without a visible person) and gated:

| model | visibility agreement, 608 rows | confident disagreements | gates |
|---|---|---|---|
| QAT champion | 95.7% | 1 | 5 / 5 |
| confuser | 92.3% | 3 | 5 / 5 |
| confuser, QAT + mining (1 epoch) | 91.1% | 4 | 5 / 5 |

This agrees with the unbiased 1,000-image check (95.9 / 93.0 / 94.9%). The
confuser's earlier 88.5% came from a 96-image pack and was noise. All three
chip networks are cleared. **Decided 2026-09-13: the champion ships** — the
head-to-head flight comparison found the confuser cannot follow a person at all
(0.000 tracking on a standing subject), which the still-image recall gap of
0.683 vs 0.511 badly understated, because confirmation needs three consecutive
frames above threshold and a slightly less confident model almost never strings
three together. See `docs/eval_results/2026-09-13-champion-vs-confuser/`. Releases: `logs/plain_follow_eval576_*` on `successor-release`.

## Sep 11, 2026 — Unbiased float-vs-chip check on 1,000 random images (Sai)

The 96-image release pack was too small to decide the confuser (one image
is about 1 point). On 1,000 uniformly random val2017 images (details and
files: `docs/eval_results/2026-09-11-unbiased/`), all three candidates follow
their float versions closely:

| | champion | confuser | confuser, QAT + mining |
|---|---|---|---|
| visibility agreement, p = 0.5 | 95.9% | 93.0% | 94.9% |
| chip overturns a confident float call | 1 / 821 | 1 / 875 | 1 / 849 |
| chip false alarms, pets and mannequins | 30.2% | 11.0% | 12.8% |
| chip false alarms, empty scenes at 0.7 | 10.7% | 2.8% | 6.3% |
| chip recall at 0.7 | 0.683 | 0.511 | 0.557 |

Quantization costs no measurable F1 for any model. So the confuser's 88.5%
on the small pack was sampling noise, and the model choice is a trade-off:
the champion detects more people; the confuser models false-alarm about 3x
less on pets. The re-released champion with a 576-image pack also passes all
five gates (95.7% agreement over 608 rows).

The 8-core chip build is bit-exact on 5 images (also at 2 and 4 cores) and
cuts a full inference from 154 ms to 23 ms at 100 MHz, when DORY's debug
output is off; with it on (the current default) 8 cores give 62 ms. Two
DORY template fixes are in `tools/dory_patches/` (0002 array size, 0003
debug switch). Also found: the drone firmware repo still holds an older
network, not the champion; a local integration dry run is in progress.

Update: both template patches are applied and the champion app was rebuilt
and re-promoted (`logs/plain_follow_prod_qat_v3`). The generated
`network.c` now declares `args[5]` at the source, all five gates pass before
and after promotion, the app integrity check passes, and the final tensor
is unchanged.

## Sep 10-11, 2026 — Final releases with the real output scale; confuser controls (Sai)

**Output scale fixed.** The pipeline decoded integer outputs as raw / 32768,
but the network's real output quantum is the output layer's `eps_out`
(champion 2.0098e-4, confuser 2.1179e-4, both 6.6x larger). The fix is on
`successor-release`; exported networks are byte-identical. With it, the
integer-network numbers in release summaries finally mean something:

| champion, expanded pack | before (wrong scale) | after |
|---|---|---|
| integer-network F1 | 0.12 | 0.837 (float 0.815) |
| float-vs-integer visibility agreement | 0.50 | 0.92 |
| selected deployment threshold | 0.45 (tie artifact) | 0.55 |

**Final releases** (`logs/plain_follow_prod_{qat,confuser}_final`): the
champion passes all five gates, was promoted, re-gated after promotion, and
passes the app integrity check. It is the app on `successor-release` now.
The confuser still misses only the float-agreement gate (88.5%, boundary
cases only).

**Confuser controls** (one epoch each from confuser ep8, lr 2e-5, confuser
manifest; scored with `export/confuser_slice_eval.py`, which reproduces the
old numbers exactly):

| run | QAT | hard-negative mining | slice FP @0.45 | peak F1 |
|---|---|---|---|---|
| confuser ep8 (start) | no | yes, epochs 4-8 | 0.083 | 0.7947 |
| Aug 31 gentle QAT | yes | off | 0.223 | - |
| control (i) | no | off | 0.263 | 0.7949 |
| control (ii) | yes | on from epoch 1 | 0.122 | 0.7958 |
| baseline (no confuser training) | - | - | 0.239 | - |

Conclusion: the Aug 28/31 claim "QAT erases the confuser gains" is wrong.
Training without hard-negative mining erases them, with or without QAT.
QAT with mining keeps most of the gain after one epoch (0.122 vs 0.083).

**Repeat-run caveat (Sep 11).** A second run of the same recipe (epoch 1 of
a 3-epoch run; cosine schedule, so the same 2e-5 learning rate in epoch 1)
gave slice FP 0.174 at 0.45 and peak F1 0.7954. That gap is far larger than
sampling noise on 771 images (about +/-0.012), and `train.py` sets no random
seed anywhere (data order, sampler, hard-negative picks, QAT calibration all
vary). Both mining runs stay well below the no-mining runs (0.22-0.26), so
the direction holds, but the size of the effect is uncertain. Before any
training result goes in a report: add a `--seed` option and run at least 3
repeats.
Released control (ii) through the pipeline
(`logs/plain_follow_confuser_qathn_final`): it passes four of five gates and
misses float agreement by one image, 89.6% (86 of 96) against the 90% bar
(calibrated-only confuser: 88.5%). None of the disagreements is confident.
x-bin within one 96%, size within one 98%, integer F1 0.874 on the expanded
pack. With only 96 images (6 without a person), one image moves agreement
about 1 point, so the next step is the planned 500+ image evaluation pack,
not a lower bar. A longer QAT-with-mining run may also close the remaining
gap to 0.083 on the confuser slice.

## Sep 10, 2026 — Both models re-released with the patched DORY (Sai)

Full release pipeline for both models with `tools/dory_patches/` applied,
into new folders (`logs/plain_follow_prod_qat_fixed`,
`logs/plain_follow_prod_confuser_fixed` on `successor-release`; not promoted
yet). No "invalid value encountered in cast" warning in any step. Gates from
`export/check_semantic_release_gates.py`, with GVSOC run on 5 different
images per model by `export/run_gvsoc_multi_image.py`:

| gate | QAT champion | confuser model |
|---|---|---|
| distinct outputs, 96 samples | 96 / 96 (old: 1) | 96 / 96 |
| hidden layers at 255 | at most 0.07% (old: 100%) | pass |
| visibility agreement with float model, p = 0.5 | **94.8%** | **88.5% (fail, bar 90%)** |
| x-bin within one / size within one | 97.0% / 100% | 93.2% / 97.7% |
| GVSOC exact, all agreeing with ONNX Runtime | 5 images | 5 images |
| negative weight bytes | 43-53% (old: 0-1.8%) | pass |
| **overall** | **PASS** | **FAIL** |

GVSOC on the champion: 15,184,257 cycles, checksum OK, 9 of 9 layer checks
exact, final tensor `[5247, 5523, 2781, -659, -948, -2089, 3694, -1952, -8464,
-2869, 959, 5626, 1227, -7277]` (signed and different for every image).

The confuser's 7 disagreeing images are all near the boundary: the float
model gives them 0.32 to 0.51, and none is a confident disagreement. The
confuser was calibrated after training rather than trained with
quantization, so it drifts more than the QAT champion. It stays off the
chip until a QAT version with hard-negative mining passes the gates.

Also: the pipeline decodes integer outputs with a hard-coded 1/32768 scale
(real value about 2.0e-4), so the float-vs-integer F1 and threshold numbers
inside these release summaries are distorted. The gates above do not depend
on that scale. A fix is being tested; the releases will be re-run with it
before promotion.

## Sep 10, 2026 — DORY fix verified end to end in scratch (Sai)

The one-line DORY cast fix (`tools/dory_patches/`) was tested on patched and
unpatched copies of DORY with the release's own unmodified scripts, for our
champion and for David's checkpoint as a control. The unpatched copy
reproduces the broken release exactly. The patched copy gives:

| check (64 unique test images) | champion | David's checkpoint |
|---|---|---|
| distinct outputs, fixed DORY simulator | 64 / 64 (old: 1) | 64 / 64 |
| most-saturated layer, share at 255 | 1.4% (old: 100%) | 0.9% |
| weight bytes >= 128 vs ONNX negative weights | equal on 8/8 tensors (old: 0) | equal on 8/8 |
| decisions vs ONNX Runtime (x-bin / size / visibility) | 98.4 / 100 / 100% | 100 / 100 / 100% |
| decisions vs fake-quant model | 90.6 / 85.9 / 95.3% | 89.1 / 71.9 / 87.5% |

On the labeled images, the fixed integer champion scores F1 0.833 at the 0.7
gate against 0.843 for fake-quant, and its no-person false-alarm rate drops
from 1.0 to the fake-quant level. Only 6 of the 64 images have no person, so
that rate moves in steps of 1/6. GVSOC on the fixed apps is part of the
re-release now running.

Side findings, not causes of the collapse:
- Release summaries report integer F1 around 0.12 because
  `semantic_output('id')` divides by a fixed 32768; the real output quantum
  is about 2.0e-4. With the right scale, 0.7-gate agreement is 95.3%.
- The release driver copies DORY-made goldens over the ONNX Runtime goldens
  (`run_plain_follow_release.py`, `sync_dory_io_seed_into_model_dir`), so the
  "independent" reference was never independent. To fix.
- `clamp_dory_weight_initializers_to_int8` clips 9 champion weights (14 in
  David's) that NEMO leaves outside int8. That clamp explains all of the
  ID-to-DORY gap and costs David's model size-bucket agreement (86% to 70%).
- The output layer's bias stays float and is effectively dropped, and one
  batch-norm constant uses 84% of the int32 range. Worth a later look.

## Sep 10, 2026 — Follower at the chip's speed and delay (Sai)

The simulated follower now emulates the GAP8 chip: one inference at a time
at 6.5 Hz, commands applied 153 ms after their frame. A code review caught
that the first version let the emulated chip catch up on missed frames, so
those runs were discarded and re-flown with a serial limiter and a stricter
validity check. All four re-flights are valid:

| Scene | Tracked | True heading error mean / max |
|---|---|---|
| person swaying ±1.2 m | 99.2% | 3.1° / 7.9° (full speed: 2.7° / 6.6°) |
| same, 220 ms delay | 99.2% | 3.2° / 8.0° |
| person 3.5 m out, 1 m right | 98.7% | 4.8° steady, inside the center bin |
| empty room | 0% | never moved |

No oscillation: the drone's yaw rate changes sign 3.5 times a minute at
chip speed, against 17 at full speed. Replaying the saved empty-room frames
offline gives bit-identical outputs, so the earlier live-versus-offline
difference came from comparing different frames. The empty-room margin is
thin: confidence averages 0.57 and peaks at 0.64, against the 0.7 needed to
start tracking. Evidence: `docs/sim_results/2026-09-10-chip/`. These runs
use the float model; the chip network itself is still being re-released.

## Sep 10, 2026 — CORRECTION: our released chip networks ignore their input (Sai)

Verified Sep 10. For both releases (QAT champion and confuser), the Python
DORY-graph simulator gives **one** distinct 14-value output across all 96
test images (rep16, hard-case, expanded-eval). The release's own golden
activations (ONNX Runtime on `model_id_dory.onnx`) saturate: layer 1 is 94%
at 255, layers 2–7 are 100% at 255 (a single value), and the final outputs
are all positive multiples of 15. The release summaries show a deployment
no-person false-positive rate of 1.0 at every threshold while reporting
"final tensor exact match: True". David's shipped app is a working control:
its output is signed and varies.

What this withdraws: the Aug 28 "CHAMPION DEPLOYED" and Aug 31 "both
contenders flight-ready" claims. The GVSOC exact-match gate compared one
image against a golden produced by the same collapsed network, so it could
not catch this. **0.8008 stands only as a fake-quant (FQ) result**, not an
integer or chip result. The current promoted app on `successor-release` must
not be flashed or flown.

Also found: the "QAT erases the confuser gains" conclusion (Aug 28, Aug 31)
is confounded, because hard-negative mining was off in the one-epoch QAT runs
but on in epochs 4–8 of the confuser run. The chip's preprocessing
(`crazyflie_ssd/src/preprocess.c`) resizes by nearest neighbor while training
uses bilinear. The Sep 10 simulator results are unaffected: they used the
float model.

**Root cause (found Sep 10, same day).** The quantized export is healthy:
every exported ONNX stage gives distinct, unsaturated outputs under ONNX
Runtime, for both our models and for David's checkpoint run through our
pipeline. The bug is in DORY's weight serialization. `HW_node.py`
(`add_checksum_w_integer`) casts float32 weights straight to uint8. On Apple
Silicon with NumPy 1.24 (our `doryenv`), that cast saturates every negative
value to 0 instead of wrapping. So every negative weight became 0 in the
DORY-graph simulator, the goldens, and the GAP8 app alike. The final tensor
is exactly 255 times the sum of the positive output weights plus the bias,
which is why every value is a multiple of 15. Evidence:

| check | result |
|---|---|
| NumPy float32 to uint8, 1000 values of -39 | doryenv: 0; x86 container: 217 (correct) |
| negative bytes in app weight files | ours 0-1.8%; David's (built on x86) 47-53% |
| David's checkpoint through our DORY on this Mac | collapses the same way |
| our ONNX with the cast fixed, in the DORY simulator | distinct outputs, matches ONNX Runtime |

Every release log since Aug 28 carried the only symptom:
`RuntimeWarning: invalid value encountered in cast`. Fix: a wrap-safe cast
(`tools/dory_patches/`), then re-release both models. New permanent gates on
`successor-release` (`export/check_semantic_release_gates.py`): output
diversity, hidden-layer saturation, float-vs-deployed decision agreement,
GVSOC on 3+ images with ONNX Runtime agreement, and negative weights present.
Both old releases fail all five; David's app passes the weights gate.

## Sep 10, 2026 — Autonomous person following in the simulator (Sai)

Grace's gate before telling Prof. Mok or picking up hardware: the drone must
follow a person in simulation with the safety rules working. Everything below
ran on Sai's Mac via `tools/crazysim_macos/` (MuJoCo CrazySim, native viewer,
firmware in the arm64 container).

**Setup.** A real COCO val2017 person (img 19432), masked and composited onto
the wall color, on a 1.7 m panel. Chosen by scoring 38 full-body candidates
from the drone's-eye view: champion confidence 1.00 at every distance
1.5–3.5 m, size bucket stepping 3→2→2→1→1 with distance. Scenes: person
static at (3.5, −1.0); person swaying ±1.2 m on a 20 s undamped spring;
empty (person behind the drone). Follower `follow_person.py`: simulated
AI-deck frames (UDP) → champion model (float, CPU) → decoded bearing and size
→ yaw rate + forward velocity through cflib `MotionCommander` at 0.8 m,
~15 Hz control loop.

**Safety rules** (MinHyuk's simulator exit criteria): track only after
confidence ≥0.7 on 3 consecutive frames, drop below 0.45; hover when the
person is lost; hover on frames older than 0.5 s and land after 3 s; caps
0.3 m/s and 40°/s; approach only when |x| < 0.5.

| Test (final settings) | Result |
|---|---|
| Person 3.5 m out, 1 m right | tracked 99.4% of frames, centered 97.9%; true bearing error mean 1.1° (max 1.9°); closed from 3.64 to 2.28 m; landed at 0.02 m |
| Empty room | tracking 0%, horizontal drift 0.00 m: no motion without a target |
| Camera frozen at t = 20 s | hovered through 108 stale steps, then landed at 0.02 m |
| Person swaying ±1.2 m, 20 s period | tracked 99.7% of frames; true heading error 2.7° average, 5.0° 90th percentile, 7.7° worst (ground-truth log); landed at 0.02 m. Smooth probability-weighted steering (`--soft-x`) was no better (2.9° average, 8.2° worst), so the default stays on the winning bin |

**Bugs and findings on the way**

- macOS caps UDP datagrams at 9216 bytes; the simulator's 60 KB camera
  chunks were dropped silently (it ignores send errors). `patch_crazysim.py`
  sets 8 KB chunks; `setup.sh` applies it.
- cflib 0.1.27's UDP driver calls `sendto()` on a connected socket, which
  macOS rejects (EISCONN). trainenv now carries cflib 0.1.33, installed
  `--no-deps` so numpy stays 1.24.4 for torch 2.2.2.
- Yaw sign: a positive `rate_yaw` setpoint turns LEFT in this SITL; cflib
  negates yaw rate for legacy-protocol firmware. The follower uses −1. This
  must be re-verified on the real drone's firmware.
- MuJoCo renders transparent texture pixels black, so the person is
  composited onto the wall color instead of alpha-cut.
- The scene's air model (density/viscosity) damped the swaying panel from
  ±1.2 m to ±0.3 m within 60 s because its inertia implied a large box. Panel
  inertia is now tiny.
- Empty-room false positives with the original single-frame 0.55 threshold:
  7.8% of frames, and the drone yawed 22°. They were brief (longest streak 4
  frames ≥0.55; one frame ever ≥0.7) while a real person scores ~0.96–1.0
  every frame, so the 3-frame confirmation rule removed them (0% in the final
  run). Offline renders of the same room score ≤0.20 at every heading; the
  live-vs-offline gap is unexplained.
- Scoring a moving target by replaying the scene offline and lining it up on
  the firmware clock gave bogus ~31° errors (time misalignment), while the
  camera showed the person centered. `patch_crazysim.py` now makes the
  simulator log the person's true position on the same clock as the
  follower (`CRAZYSIM_TRUTH_LOG`). Validated on the static case: constant
  truth, 1.5° error, matching the fixed-position score.
- The firmware locks after every landing, so each flight needs a fresh sim;
  `run_follow_demo.sh` handles it.

**Caveat.** Simulated frames are clean renders of a photo on a panel. This
validates the control loop and safety logic, not real-camera accuracy, which
still needs real AI-deck frames.

**Evidence:** `docs/sim_results/2026-09-10/` holds every final run's log,
the simulator's true-position logs, and the charts. Re-fly the whole suite
with `tools/crazysim_macos/run_acceptance.sh`.

## Sep 10, 2026 — CrazySim runs on macOS: no NVIDIA, no Ubuntu (Sai)

MinHyuk's simulator setup requires Ubuntu/WSL2 + NVIDIA, but that
requirement belongs to its Gazebo backend and WSL-specific Docker Compose
mounts. The MuJoCo backend is two processes over UDP: `cf2` (firmware SITL,
C) and `crazysim.py` (MuJoCo, Python). Findings on Sai's Apple Silicon Mac:

- MuJoCo physics, offscreen rendering, the 3D viewer (`mjpython`), and
  `cflib` with its UDP driver all run natively on macOS.
- `cf2` cannot build natively: it links with a GNU linker script
  (`log_param_linker.ld`, `INSERT AFTER .text`) that Apple's ld rejects.
  It builds and runs in a minimal arm64 Ubuntu 22.04 container (0.9 GB;
  no ROS/Gazebo/GPU). Two build fixes: install `pkg-config` +
  `python-is-python3`, and build target `cf2` only (`make all` also builds
  the Gazebo plugin).
- `crazysim.py` binds 127.0.0.1 by default; containerized runs need
  `--host 0.0.0.0` for Docker port publishing.

| Check | Result |
|---|---|
| Tutorial demos 1–3 (connect, params, telemetry) from macOS cflib | pass |
| Takeoff on fresh sim | 0.55 m; supervisor 14 → 30 (armed → flying) |
| Demo 7 fly-and-log | x 0 → 0.66 m, z 0.02 → 0.55 m |
| Speed | ~0.9x real time, headless and native-viewer modes |
| Simulated AI-deck camera over CPX | 324x244 gray, ~13 fps (OSMesa CPU render) |
| Champion model on sim frames | runs; empty scene → person conf 0.047 (correct) |

**Firmware lock after landing:** every landing drives the supervisor to
`Locked` (info 68 = autoArm + isLocked; console "SUP: Locked, reboot
required"), so back-to-back flight scripts fail silently unless the sim
restarts between flights. Not Mac-specific: MinHyuk's back-to-back demo
flow would hit it on Ubuntu too — worth telling him.

Packaged as `tools/crazysim_macos/` (setup.sh, viewer/headless/camera
launchers, camera grabber, flight check, MinHyuk's MIT tutorial).

## Aug 31, 2026 — Gentle-QAT retry fails the same way: stacking result is structural (Sai)

> **Overturned (Sep 11):** hard-negative mining was off in this run. Controls show missing mining, not QAT, erased the gains; see the Sep 10-11 entry.

Pre-registered rule: confuser-slice FP ≤ 0.10 AND peak F1 ≥ 0.795 →
contender. Result of the lr 2e-5 QAT epoch on confuser-ep8: peak F1 0.7947
(flat), **confuser-slice FP 0.223 @0.45** — the safety property eroded from
0.083 most of the way back to the 0.239 baseline despite the 2.5x-gentler
learning rate. Same failure at lr 5e-5 and 2e-5 ⇒ fake-quant training noise
destroys the confuser decision boundaries regardless of step size; the
effect is structural, not a hyperparameter accident.

**The experimental program is closed pre-meeting.** Final state: two
flight-ready contenders (champion 0.8008 / confuser 0.7947 + 3x safer),
both GVSOC-validated. The only remaining path to a have-it-all model is a
joint QAT+confuser run from scratch (team decision, needs a Linux GPU).
Checkpoint archived: training/successor_confuser_qat_gentle/ (not a candidate).

## Aug 31, 2026 — Confuser model GVSOC-validated: both contenders flight-ready (Sai)

> **Superseded Sep 10:** this release shares the constant-output problem; see the Sep 10 correction.

The confuser model (`artifacts/successor_confuser_ep8.pth`) was run through
the full release pipeline WITHOUT promotion (`--skip-application-promotion`,
output `logs/plain_follow_prod_confuser/`): **GVSOC status PASS, exact
final-tensor agreement**
(`[130815, 160650, 210630, 245310, 284070, 260100, 225675, 168300, 110670, 351900, 143565, 100215, 106080, 197115]`
— decodes visible / centered / close on the golden image, consistent with
the champion). Both Sep 2 candidates are therefore silicon-validated;
whichever the team picks, promotion is a single command.

## Aug 31, 2026 — Independent reproduction (Grace)

Grace independently reproduced the promoted QAT champion's silicon-accurate
validation on a second machine: Intel Mac (`x86_64`), macOS 15.7.9. Environment
versions were Python 3.11.16, torch 2.2.2, torchvision 0.17.2 in both
`trainenv` and `nemoenv`. Command, from `pytorch_ssd_unstable` at corrected
`successor-release` commit `59a560e`:

```bash
PLAIN_FOLLOW_VERIFY_PYTHON=../nemoenv/bin/python3 bash run_plain_follow_app_val.sh
```

Exact required results:

```text
plain_follow handoff integrity check: PASS
PASS: 'final' matches exactly.
```

All nine GAP8 layer checks passed, and the 14-value GVSOC tensor matched the
checked-in golden tensor exactly. The first second-machine attempt also caught
a real handoff bug: `*.pth` ignore rules had omitted the checkpoint from commit
`de49ae1`. After the checkpoint was truly added in `59a560e`, the clean recovery
and exact-match validation passed without modifying the deployed
`application/`.

## Aug 28, 2026 — Stacking test: QAT-after-confuser DESTROYS the confuser win (Sai)

> **Overturned (Sep 11):** controls show missing hard-negative mining, not QAT, erased the gains; see the Sep 10-11 entry.

One QAT epoch (lr 5e-5, confuser manifest, on confuser-ep8 weights) fully
regressed the animate-false-alarm fix: confuser-slice FP 0.083 → **0.249**
@0.45 (back to the 0.239 pre-fix baseline) while peak F1 stayed ~0.795.
Clean negative result: the confuser resistance lives in decision-boundary
placement that fake-quant training noise erodes within one epoch, even when
training on the same skewed data. Ordering matters and this order is wrong.

Consequences: (1) the two-model choice stands — QAT champion (0.8008,
deployed) vs confuser ep8 (0.7947, 3x safer) — no have-it-all model exists
yet; (2) if the team wants one, the untested recipe is a SINGLE joint run:
QAT from scratch with the confuser manifest from epoch 1 (est. multi-hour,
deferred); (3) note the confuser model ships through the release path with
standard recalibration anyway, and its deployed-form numbers above already
reflect that — so "lacking QAT" costs it nothing at release time that we
haven't already measured.

Compute campaign closed: nothing running. Checkpoint:
training/successor_confuser_qat/plain_follow_epoch_001.pth (archived, not a candidate).

## Aug 28, 2026 — Confuser fine-tune: 3x fewer animate false alarms (Sai)

The confuser-skewed fine-tune (scratch-ep28 init, 8 epochs, negative pool
62% animate confusers via `--train-sample-manifest`) hit its pre-registered
target. All numbers in deployed (fake-quantized) form, epoch-8 checkpoint:

| metric | champion (QAT ep3) | confuser ep8 |
|---|---|---|
| Confuser-slice FP @0.45 | 0.239 | **0.083** (−65%) |
| Confuser-slice FP @0.55 | 0.171 | **0.052** (−70%) |
| Peak F1 | 0.8008 | 0.7947 |
| Overall no-person FP @ peak-F1 threshold | 0.241 (t=0.30) | 0.224 (t=0.30) |

Verdict: 0.6 points of peak F1 bought a **threefold reduction in the
drone-chases-the-cat rate** — for an indoor person-follower, pets and
mannequin-shaped objects are the dominant operational hazard, so this is
the better OPERATIONAL model even though the QAT champion keeps the
leaderboard crown. Decision on which ships is a team call (Sep 2 agenda):
leaderboard champion vs operational candidate, plus threshold.

Follow-up in flight: 1-epoch QAT chunk on confuser ep8 (per the MPS OOM ops
note) to test whether the quantization-robustness and confuser wins stack.
Checkpoint: `training/successor_confuser/plain_follow_epoch_008.pth`.

## Aug 28, 2026 — QAT2 continuation: no improvement; champion confirmed (Sai)

The quant-aware continuation (init from QAT ep3, lr 7e-5, batch 16) was
OOM-killed by macOS a second time, 71% into epoch 2 — NEMO QAT on MPS leaks
memory progressively; batch size does not save it, only wall-clock (~2.25 h)
changes. Yield: epoch 1 only, deployed-form peak F1 **0.7988** — below the
deployed champion's 0.8008. Prediction on record was ~0.803 (70% to beat);
wrong on direction: epoch 1's in-loop F1 (0.7990 @ 0.50) carried no
threshold-sweep bonus this time (its peak already sat at 0.50), and the OOM
removed any chance for epochs 2-3.

Decision: **champion stands** (QAT ep3, 0.8008, deployed and validated).
QAT2 is closed as plateau confirmation — the accuracy axis is squeezed;
further QAT continuations are a poor trade (CPU-only ~4 h/epoch for an
expected ~+0.1). Ops note for any future QAT round on this machine: run
1-epoch chunks with re-init between runs (fresh process = fresh memory), or
rent a Linux GPU box.

Still in flight: the confuser-negatives fine-tune (different axis — targets
the 24% animal false-alarm slice, not peak F1).

## Aug 28, 2026 (night) — CHAMPION DEPLOYED: full pipeline to silicon-accurate PASS (Sai)

> **Superseded Sep 10:** the promoted integer network ignores its input; see the Sep 10 correction.

The QAT champion (deployed-form F1 0.8008) was pushed through David's entire
release pipeline and is now the repo's promoted, validated GAP8 application —
`run_plain_follow_app_val.sh` (his own entry point, cold start) reports
integrity PASS and a bit-exact 14-value final-tensor match. Branch
`successor-release` on the fork holds the promoted app + all fixes.

The road there (7 pipeline runs, each failing one stage deeper — stage-aware
debugging applied to the pipeline itself):

1. doryenv built on macOS py3.11 with minimal pins (the Linux requirements
   file is unnecessary); +torchvision after run 1.
2. **torch-era ONNX incompatibility (the big one)**: DORY at add0d9c requires
   torch-1.10-style ONNX (numeric tensor names, Cast-chain requant). Fix:
   resurrected David's exact known-good env (py3.8.10 / torch 1.10.2 / nemo
   0.0.8) as a linux/amd64 Docker image (`nemo-legacy-export:py38`) with the
   workspace mounted at its identical host path, wired into the release
   driver via its `--python` seam through `legacy_export_env/legacy_python.sh`.
3. Driver patch: seed ORT-computed golden activations (out_layer*.txt) next
   to the DORY ONNX after quant eval — DORY's HW parser needs them for
   checksums; the legacy flow left them behind implicitly.
4. Portability bug in David's checked-in DORY config: absolute path from his
   WSL machine (`/mnt/c/Users/yxl21/...`). Fixed by pinning config onnx_file
   to the --onnx argument in generate_dory_io_artifacts.py.
5. pulp-nn submodule was at an empty-tree master HEAD; pinned to DORY's
   recorded 9ada4a9.
6. Promoted golden output.txt normalized to bare integers (the integrity
   gate rejects NEMO-style comment headers).

QAT checkpoint handling: David's own `prepare_follow_qat_eval_checkpoint.py`
strips PACT keys; the release path re-quantizes with fresh calibration (16
imgs) — learned alphas do not ship, QAT-shaped weights do. Release metrics
healthy (follow_score 0.354 vs released 0.340). Champion's chip tensor on the
golden image decodes as: visible, centered (x-bin 4), close (size bucket 3).

Every step of the thesis has now been reproduced AND exceeded on team
hardware: better model, same exactness guarantee, pipeline portable off
David's machine for the first time.

## Aug 28, 2026 (evening) — GVSOC validation reproduced: exact final-tensor PASS (Sai)

Installed Docker Desktop (Apple Silicon, Rosetta emulation), pulled David's
pinned image by digest, and ran `run_plain_follow_app_val.sh` on the
`unstable` worktree: integrity gate → container build of the shipped
`application/` → GVSOC simulated-GAP8 execution → tensor compare.

**Result: PASS — exact final-tensor agreement.** All 14 int32 outputs match
the golden file bit-for-bit:
`[4632, 13262, 4633, -2422, -3479, -5390, 2962, -1854, -11170, 5303, -7980, 3540, 4466, -43]`
Decoded per the contract (x-bins 0-8, vis 9, size 10-13): argmax x-bin = 1
(left of center), visibility logit 5303 > 0 (visible), size bucket = 2 —
"person visible, left of center, medium size."

Meaning: every result in the thesis is now independently reproduced on team
hardware, including the runtime endpoint. The Docker/GVSOC lane is proven on
this machine (logs in `pytorch_ssd_unstable/logs/plain_follow_app_validation/`).
Next frontier: push OUR champion (QAT ep3+) through export → DORY codegen →
app regen → this same validation — the step that makes 0.8008 flight-ready.

## Aug 28, 2026 (afternoon) — Error anatomy of the champion; the confuser problem (Sai)

Ran `export/error_analysis_fq.py` on the deployed champion (QAT ep3) over
val2017 @ threshold 0.45: recall 0.822 overall but strongly size-dependent —
**tiny persons 0.649, small 0.806, medium 0.919, large 0.912**. Gallery
inspection shows the misses are mostly tiny background people, partial
slivers, and photos-of-people — LOW operational value for a follow drone
whose target is medium/large in frame (where recall is already 0.91+).
Conclusion: do NOT chase tiny-person recall (would cost input resolution /
GAP8 compute for leaderboard vanity).

The actionable failure is the FALSE POSITIVES: the worst confident false
alarms are **mannequins (P=1.00), dressed teddy bears (0.97-0.98), cats
(0.97), a dog (0.96), cows (0.98)** — animate-shaped non-persons. For a
person-following drone these are the ghost-chase cases (it would follow the
family cat). New metric slice: **FP rate on val2017 confuser negatives
(no-person images containing bird/cat/dog/.../teddy bear, n=771): 0.239 @
0.45, 0.171 @ 0.55.**

Fix queued (runs after QAT2 finishes): retrain with a confuser-skewed
negative pool via David's `--train-sample-manifest` —
`export/build_confuser_manifest.py` keeps all 64k person images + all 17.6k
confuser negatives + 30% of boring negatives (negative pool now 62%
confusers). Success = confuser-FP slice drops materially with overall peak
F1 held. Galleries: `export/error_analysis/`.

## Aug 28, 2026 — QAT run: new deployed-form champion, 0.8008 (Sai)

> **Note Sep 10:** "deployed form" here means fake-quant PyTorch, not the integer chip network.

QAT fine-tune of the F1-record model (scratch ep28) using David's
`--quant-aware-finetune` path: 8-bit PACT training on full train2017,
lr 1e-4. The OS killed the run at epoch 4 (memory pressure — QAT holds
extra model copies; also ~10x slower per step on MPS), but epochs 1-3
checkpointed and epoch 3 was sufficient.

New scoreboard — **deployed form** (fake-quantized, the form that flies),
val2017 peak F1 via `export/sweep_fq_ckpt.py`:

| model | FP form | deployed form | quantization cost |
|---|---|---|---|
| David's released | 0.7910 | 0.7885 | −0.25 |
| Warm-start ep18 | 0.7958 | 0.7958 | **0.00** |
| Scratch ep28 (FP record) | 0.8001 | 0.7946 | −0.55 |
| **QAT ep3 (champion)** | n/a | **0.8008** | gains by construction |

Findings:

1. **QAT ep3 is the overall champion: 0.8008 deployed-form F1**, +1.2 points
   over David's released model in deployed form. Its quantized score even
   exceeds the record model's unquantized 0.8001.
2. **The drift audits predicted the quantization costs exactly**: warm-start
   (16/16 audit) lost 0.00 under quantization; scratch (14/16) lost 0.55;
   David's (15/16) lost 0.25. The rep16 audit is a validated cheap proxy for
   full-set deployed degradation.
3. QAT checkpoints carry learned PACT alphas (load into a `quantize_pact`-
   wrapped model, no calibration needed) — `--mode qat` in the sweep tool.
4. Remaining to call it fully deployable: ONNX/DORY export of the QAT
   model's integer-deployable stage + GVSOC final-tensor check (needs the
   Docker lane), then rep16 overlays for the meeting.

Champion checkpoint (local): `training/successor_qat/plain_follow_epoch_003.pth`.

## Aug 28, 2026 (overnight) — Successor Run 1: David's model beaten (Sai)

Warm-start fine-tune of David's released checkpoint using HIS full recipe
(worktree `successor` branch: flip aug, weighted losses vis2.0/x1.0/size0.3/
res0.5, hard negatives from ep 4, visible-fraction 0.6) on full train2017,
20 epochs, lr 3e-4, batch 32, MPS.

**Result: new project best — peak F1 0.7958 (epoch 18, threshold 0.35) vs
David's released 0.7910.** Robust, not a lucky epoch: every checkpoint from
epoch 15 on beats 0.791 (ep15 .7923, ep16 .7927, ep17 .7942, ep19 .7937,
ep20 .7935). Calibration improved across the curve too: at threshold 0.50
the champion gives F1 0.773 @ FP rate 0.117 vs David's 0.757 @ 0.111, and at
0.55 it's 0.760 @ 0.090 vs his 0.740 @ 0.086 — ~+1.5-2 F1 points at matched
safety everywhere in the useful range.

Champion checkpoint (local): `training/successor_warmstart/plain_follow_epoch_018.pth`.

## Aug 28, 2026 (morning) — Campaign complete: both runs beat David; warm-start dominates

Run 2 (from-scratch, 30 ep, his full recipe) finished. Full standings on
val2017 peak F1, with the FP->FQ drift audit (rep16, his calibration set)
as the deployment gate:

| model | peak F1 | drift: x-bin / size / vis |
|---|---|---|
| David's released (ep 28) | 0.7910 | 15/16 / 16/16 / 16/16 |
| Warm-start ep 18 | 0.7958 | **16/16 / 16/16 / 16/16** |
| **From-scratch ep 28** | **0.8001** | 14/16 / 15/16 / 16/16 |

Findings:

1. **Warm-start ep 18 strictly dominates the released model** — higher F1
   AND a perfect quantization audit (more FQ-robust than the model it was
   initialized from). It is the current deployment candidate.
2. **From-scratch ep 28 is the accuracy record (0.8001)** but pays ~1-2
   audit images of FQ robustness. Its safety curve is the best measured:
   matches David's F1-at-0.50 at FP 0.087 vs his 0.111, reaches FP 0.020.
3. **F1-based checkpoint selection is worth real points**: `follow_score`
   picked scratch ep 25 (0.7947); F1 sweep finds ep 28 (0.8001). Selection
   metric choice alone = +0.5 F1.
4. Next moves: QAT fine-tune (`--quant-aware-finetune`) of scratch ep 28 to
   chase 0.80-with-perfect-audit; int8 export + GVSOC of whichever wins;
   overlays for the meeting.

Checkpoints (local): `training/successor_warmstart/plain_follow_epoch_018.pth`,
`training/successor_scratch/plain_follow_epoch_028.pth`. Runs logged in
`pytorch_ssd/training_successor_{warmstart,scratch}.log`.

## Aug 27, 2026 (night) — David's handoff verified + toolchain convergence (Sai)

David published the full reproduction material (`unstable` branch + private
data ZIP + separate crazyflie-ssd repo). Ingested tonight; `unstable` is
mounted as a sibling worktree (`../pytorch_ssd_unstable`) and preserved on
our fork as branch `david-unstable`. His SHA-256 integrity gate
(`tools/verify_plain_follow_handoff.py`): **PASS**.

**Reimplementation scorecard** (our thesis-text reconstruction vs his originals):

| Aspect | Ours | David's | Verdict |
|---|---|---|---|
| x bins | 9 uniform over [-1,1] | `linspace(-1,1,10)` | identical (centers match to fp32) |
| size buckets | 4 uniform over [0,1] | (0,.25,.5,.75,1) | identical |
| Output layout | x 0-8, size 9-12, vis 13 | **x 0-8, vis 9, size 10-13** | DIFFERENT — his is the deployed int32 contract |
| Backbone | 4 stages to 80ch (185K params) | 3 stages to 48ch, stem-mode variants | different scale, same straight-through idea |
| Loss | equal-weight sum | staged phases w/ active loss weights, x-residual + neg-vis terms | his is richer (DroNet-style weighting we'd flagged as missing) |

**Toolchain convergence test** — his released `plain_follow_best_follow_score.pth`
(epoch 28) through OUR drift audit, calibrated on HIS `data/rep_images`, on HIS
rep16 diagnostic set: x-bin preserved **15/16**, size bucket **16/16**,
visibility **16/16**. The thesis's own deploy-side audit reported 15/16 x-bin —
two independently built toolchains agree on the same artifact. The one flip
(`09_visible_000000436738.jpg`) jumps bin 4→1 (non-adjacent) — the known hard
image. `16_negative_000000006723.jpg` is a standing false positive (vis 0.56 on
a no-person image) in both FP and FQ.

**Head-to-head on val2017 visibility @ threshold 0.5** (same 5,000 images,
each model with its own decode):

| | precision | recall | F1 | no-person FP rate |
|---|---|---|---|---|
| David's released (ep 28, staged loss) | **0.870** | 0.669 | 0.757 | **0.111** |
| Ours full-COCO (ep 10, equal weights) | 0.792 | **0.765** | **0.778** | 0.222 |

Neither dominates: his model is the *safer* one (half the ghost-follow rate,
precision-leaning — consistent with `follow_score` checkpoint selection and
his negative-visibility loss term); ours is more *sensitive* (finds more
people, higher balanced F1). At a fixed default threshold these are different
operating points, not different quality tiers — a fair fight needs a
threshold sweep on both and comparison at matched FP rate — done, below.

**Matched sweeps** (val2017, both models, thresholds 0.30–0.75): peak F1 is
nearly identical — David's 0.791 (t=0.30) vs ours 0.785 (t=0.40) — but
David's curve is better *calibrated*: at any matched no-person FP rate his F1
is ~0.5–1 point higher, and his curve reaches FP rates (0.03–0.09) ours never
touches in range. Verdict: his released checkpoint is the honest baseline to
beat; our 10-epoch equal-weights run lands within ~1 point of a 28-epoch
staged-loss run, so adopting his loss recipe + more epochs should exceed it.
Next experiment: train with David's stack (his train.py + phases) on full
COCO — the "successor run."

**Environment ground truth (from David)**: validated deployment came from
Python 3.8.10 + torch 1.10.2 + pytorch-nemo 0.0.8 @ 5ea3338; torch 2.x is a
compatibility path — explains the residual-add tracer difference we patched.
GVSOC container pinned by digest in `application/validation/manifest.json`.

## Aug 27, 2026 — Full-dataset retrain + definitive drift audits (Sai)

Both models retrained on full COCO train2017 (118,287 images, 10 epochs,
batch 32, MPS ~8 it/s), validated on held-out val2017 — these replace the
Aug 26 bootstrap numbers, which were inflated by train/val leakage.

| | hybrid_follow (scalar) | plain_follow (bin) |
|---|---|---|
| Val visibility F1 | 0.765 (best ep 9) | **0.778** (best ep 10, still improving) |
| No-person FP rate | 0.225 | 0.222 |
| FP->FQ warning breaches | 4/16 images | decoded x-bin 15/16 exact, 16/16 adjacent |
| Size output under FQ | (part of breaches above) | bucket preserved 13/16 |
| Visibility agreement | 16/16 | 16/16 |

**Findings**

1. **plain_follow now beats hybrid_follow on task quality with 45% of the
   parameters** (186K vs 412K) — the "bin head trades accuracy for
   robustness" worry did not materialize at this scale.
2. **The bin-robustness result survives a properly trained model**: x-bin
   predictions now span 5 different bins across the 16 audit images (COCO
   subjects are genuinely center-biased, so bin 4 still dominates) and the
   decoded x command survived quantization on 15/16 exactly, 16/16 within
   one bin. The scalar model breached drift warnings on 4/16.
3. **New observation — coarse buckets are not automatically safe**: the
   4-bucket size output flipped on 3/16 images. Discrete outputs protect
   decisions only when predictions sit away from bucket BOUNDARIES; with
   only 4 wide buckets, boundary-adjacent predictions are common. Candidate
   fixes: more size bins, or boundary-aware training (margin loss), or
   hysteresis on the decoded size as well.
4. Visibility agreed 16/16 for both models this round — consistent with the
   threshold sweep: ~10% of images sit in the flip-risk band, so a 16-image
   sample sometimes contains zero flips. Population-level exposure is the
   right lens, not single audits.

**Artifacts**: `training/{plain,hybrid}_follow_full/` best checkpoints
(local), `export/overlays_{plain,hybrid}_full.png`,
`export/plain_follow/plain_follow_full_quant.onnx`,
`export/hybrid_follow/hybrid_follow_full_quant.onnx`,
`export/plain_follow/full_model_drift_audit.txt`.

## Aug 26, 2026 — Scalar vs bin head under fake quantization (Sai)

**Question**: does the thesis's core claim — bin-based follow heads preserve
decoded commands under quantization better than scalar heads — reproduce on
models we train ourselves?

**Setup**: both models trained 10 epochs on COCO val2017 (5,000 images, used
for train and val — a bootstrap-quality run, not a benchmark), batch 16,
SGD lr 1e-3 cosine, CPU. Drift measured FP -> FQ (8-bit, NEMO fake-quant,
32 real calibration images) with `export/compare_fp_fq_torch.py` on 16 fixed
images (10 person / 6 no-person), thresholds from the thesis: |dx|>0.05,
|dsize|>0.05, |dvisP|>0.10.

| | hybrid_follow (scalar, residual) | plain_follow (bin, straight-through) |
|---|---|---|
| Params / int8 size | 412K / 1.6 MB | 186K / 0.76 MB |
| Val visibility F1 (10 ep) | 0.836 | 0.693 |
| No-person FP rate | 0.166 | ~0.44 |
| NEMO ID export | needed eps_in_list seeding patch (8 residual adds unresolved) | clean — zero patches, zero warnings |
| FP->FQ drift | 6/16 images breach warning thresholds | decoded x-bin 16/16 preserved, size bucket 16/16 |
| Visibility decision agreement | 15/16 (one near-threshold flip) | 15/16 (one near-threshold flip) |

**Findings**

1. **Export cleanliness reproduces exactly.** The residual (hybrid) graph
   needed a custom patch to export at all on torch 2.x; the straight-through
   graph exported with zero special handling. Matches thesis Table 3's
   patch-burden contrast.
2. **Decoded bin commands survive quantization; continuous outputs drift.**
   Matches thesis Table 7 directionally.
3. **Visibility is the fragile output for BOTH heads** — each audit had
   exactly one image flip its visibility decision, both within ~0.03 of the
   0.5 threshold. This is the thesis's asymmetry: x/size decode through
   argmax, visibility still crosses a continuous threshold. Candidate fixes
   to discuss: temporal filtering on-device (PULP-DroNet low-pass, alpha=0.7),
   hysteresis (two thresholds), or a 2-class softmax visibility head.

**Caveats (important)**

- Our plain_follow is UNDERTRAINED and predicts the center x-bin on most
  images; low prediction entropy inflates "16/16 preserved". Retrain on full
  train2017 before quoting this number.
- plain_follow here is a REIMPLEMENTATION from the thesis text (David's
  original is not in the public repo). Bin/bucket edges assumed uniform;
  confirm against his code.
- 10 epochs, val2017-as-train: model quality numbers are not comparable to
  the thesis's.

**Artifacts**: `export/overlays_hybrid.png`, `export/overlays_plain.png`,
`export/hybrid_follow/hybrid_follow_quant_sim.onnx` (1.6 MB),
`export/plain_follow/plain_follow_quant_sim.onnx` (0.76 MB), audit tool
`export/compare_fp_fq_torch.py`, visualizer
`export/visualize_follow_predictions.py`.
