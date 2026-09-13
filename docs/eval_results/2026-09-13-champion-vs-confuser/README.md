# Champion vs confuser, head to head, in closed loop

**Nothing here was measured on hardware. Every frame is rendered, and the "chip"
network runs under onnxruntime on a laptop, not on a GAP8. Nothing in this report
says anything about a real Crazyflie.**

**This report does not recommend a model.** That is a decision for Sai, Grace and
David. What follows is the evidence and the trade-off in both directions.

---

## 0. The gap this fills

The team must choose between two networks. The per-frame still-image numbers were
already in hand:

| | champion | confuser |
|---|---|---|
| pet/mannequin false alarms | 30.2% | **11.0%** |
| recall at threshold 0.7 | **0.683** | 0.511 |

But **every closed-loop flight ever run used the champion.** The confuser had never
flown. So the team was being asked to weigh a model with flight evidence against a
model with none, which is not a comparison at all.

This session flies both through the same six chip cells, interleaved, in one
sitting: **6 cells x 2 models x 4 repeats = 48 flights, all valid, no re-flies.**

Ran 2026-09-12 18:45 to 19:33 CDT (23:45 to 00:33 UTC), on a laptop running nothing
but the user's desktop. `progress.log`, `flights.jsonl` and `flight_index.csv` are
the authoritative record of when each flight ran.

---

## 1. TL;DR

| claim | verdict |
|---|---|
| The confuser is better on pet false alarms in flight | **yes, decisively.** On `F.pets` false-follow episodes go 3.5 → 0 (median), time latched on the dog 2.355 s → 0.0 s, drift 0.7475 → 0.0 m. Every one of the 4 matched pairs moved the same way |
| The confuser passes the pets drift gate the champion fails | **yes.** M6 worst-repeat drift 0.974 m (FAIL, gate < 0.5) → 0.215 m (PASS) |
| The confuser is worse at following a person | **yes, and far worse than the still-image recall gap suggests.** Tracked-fraction-while-the-person-is-in-view collapses: 0.990 → 0.000 on `A.static`, 0.992 → 0.091 on `B.moving`, 0.500 → 0.042 on `D.occlusion` |
| On `A.static` the confuser ever latched onto the person | **no. Not once, in 4 flights of ~33 s each.** It sat at 3.64 m and never moved |
| This is just the 0.70 latch threshold being unfair to it | **partly on a static person, not at all on a moving one.** Re-scored open-loop at 0.60 (its own selected threshold) it would latch 70.9% on `A.static` but only 21.1% on `B.moving` and 12.4% on `D.occlusion` |
| Comparing each model at its OWN selected threshold | **the champion is better on both axes** — more tracking (0.967 vs 0.168) *and* fewer dog latches (0.130 vs 0.201) |
| The confuser's `D.occlusion` relatch time looks better | **yes, and it is an artifact.** 2.76 s vs 4.87 s — but the champion recovered from all 10 of its losses and the confuser ended 3 of 4 flights with the person still lost. One confuser flight logged *zero* loss episodes because it never latched at all |
| Either model passes the whole suite | **no.** Champion 4 PASS / 2 FAIL; confuser 2 PASS / 3 FAIL / 1 CHARACTERISED |

The honest one-line version: *the confuser does what it was built to do — it stops
chasing the dog, and it stops chasing it completely — but in these scenes it also
stops following people, and on a static person it never starts.*

---

## 2. The discipline

### 2.1 The code was pinned, and the pin held

sha256 of `camera_model.py`, `follow_person.py`, `build_scene.py`, `scoreboard.py`,
`patch_crazysim.py` recorded before the first flight and re-checked after the last.
All five byte-identical (`code_hashes_before.txt`, `code_hashes_after.txt`):

```
66862b05575e270ea73e2dfaf815676ac3e93420cc00c887fc71792d1bf0051d  tools/crazysim_macos/camera_model.py
4a786441f85b431aa61347cd902d797a55d7cb8bb2d77c2fb64ef71abfb68de6  tools/crazysim_macos/follow_person.py
ea639fea1b14abd12426aaaee4941468ff5402412ab1e42bda78adc2fe3bbe64  tools/crazysim_macos/build_scene.py
00a2a950131a3337614b065450b8cb89371b7ab18f256bed24f5769c2917ef33  tools/crazysim_macos/scoreboard.py
20959b177d2706f4f7980c7e760fe162e82a44ba2dd7504ca3b092bc489d0803  tools/crazysim_macos/patch_crazysim.py
```

**These are the same five hashes as `2026-09-13-rangesweep-petsab/code_hashes_after.txt`,
`2026-09-13-matte-baseline/code_hashes_after.txt` and `2026-09-13-stability/data/code_hashes_after.txt`.**
Every flight in this whole series — this one included — shares one toolchain. The
repo sat at `d49dd0b` throughout and nothing was committed or pushed.

### 2.2 Nothing under measurement was modified

`follow_person.py`, `perception_backends.py`, `build_scene.py`, `camera_model.py`,
`scoreboard.py` and `run_acceptance2.sh` are the repo's own and were **imported and
run, never edited**. `git status` on `tools/` is clean. The model is selected through
`follow_person.py`'s existing `--chip-onnx` argument; no ONNX was copied, symlinked
over, or swapped under a running suite, and `DEFAULT_ONNX` was never touched.

Every scene is the repo's own `tools/crazysim_macos/scenes_v2/`, unmodified. (Checked:
`scenes_v2/s03_pets_only/scene.xml` is byte-identical — `40dd318c…` — to the
scratch-built matte scene the pets A/B run flew, so this tree *is* the matte scene set
the earlier experiments used.)

### 2.3 The floor was asserted per flight, two ways

Every cell here is matte. Before each flight the harness reads the `reflectance`
attribute out of the `scene.xml` about to be flown *and* `room.floor_reflectance` out
of that scene's `manifest.json`, and aborts the flight if either is not 0.0. Both are
written into the run directory (`floor_reflectance.txt`, `floor_manifest.txt`).

**All 48 flights: xml 0.0, manifest 0.0.** No exceptions, no overrides.

---

## 3. Which confuser, and why

Six releases under `pytorch_ssd_unstable/logs/` carry a `quant_eval/model_id_dory.onnx`
and could be called "the confuser". They are not interchangeable:

| release | checkpoint | semantic gates | pack | no-person FP | recall | eps |
|---|---|---|---|---|---|---|
| `plain_follow_prod_qat_v3` **(champion, flown by the suite)** | `artifacts/successor_qat_ep3_eval.pth` | PASS | 96 | 0.0893 | 0.6645 | 2.0098e-4 |
| `plain_follow_eval576_qat` | *same ckpt, byte-identical ONNX* | PASS | **608** | 0.0893 | 0.6645 | 2.0098e-4 |
| `plain_follow_prod_confuser_final` | `artifacts/successor_confuser_ep8.pth` | **FAIL** (agreement) | 96 | 0.0516 | 0.5723 | 2.1179e-4 |
| **`plain_follow_eval576_confuser`  ← CHOSEN** | *same ckpt, byte-identical ONNX* | **PASS** | **608** | **0.0516** | **0.5723** | **2.1179e-4** |
| `plain_follow_eval576_confuser_qathn` | `training/successor_confuser_ctrl_qat_hn/…` | PASS | 608 | 0.0919 | 0.6452 | 2.2185e-4 |
| `plain_follow_eval576_confuser_qathn3_ep2` | `training/successor_confuser_qat_hn3/…` | PASS | 608 | 0.0811 | 0.6281 | 2.3846e-4 |
| `plain_follow_confuser_qathn_final` | `training/successor_confuser_ctrl_qat_hn/…` | **FAIL** (agreement) | 96 | — | — | 2.2185e-4 |

Four reasons `plain_follow_eval576_confuser` is the genuine counterpart:

1. **It is on the same production line as the champion.** Both come from
   `pytorch_ssd_unstable/artifacts/` (`successor_qat_ep3_eval.pth` and
   `successor_confuser_ep8.pth`). The `qathn` variants come from a different tree
   (`drone/training/successor_confuser_*_qat_hn*`) and are later experiments.
2. **The pairing is exactly parallel.** `plain_follow_eval576_qat` is the champion's
   own 608-image re-gate, byte-identical ONNX to `plain_follow_prod_qat_v3`. So
   `eval576_qat : eval576_confuser` is the same relationship on both sides.
3. **It is the only candidate whose numbers match what the team means by "the
   confuser".** The brief describes ~3x fewer pet/mannequin false alarms and lower
   recall. `successor_confuser_ep8` is the only one that moves that way
   (0.0893 → 0.0516 FP, 0.6645 → 0.5723 recall). **Both `qathn` variants have
   false-alarm rates at or above the champion's** (0.0919 and 0.0811) — whatever they
   are, they are not the model the team is calling "the confuser".
4. **It passes the semantic gates on the 500+ image pack**, which is the criterion
   the brief names. 608 images, all five gates PASS.

**Two are defensible in the narrow sense**, and it does not matter: `plain_follow_prod_confuser_final`
and `plain_follow_eval576_confuser` have **byte-identical ONNX (`59d8656f…`) and identical
eps**, so they fly the exact same network. I picked the `eval576` one because it is the
release that passed on the large pack.

> **Worth the team's attention:** `plain_follow_prod_confuser_final` *fails* the
> agreement gate (0.8854 against a 0.90 rule) while the byte-identical network
> *passes* it on the 608-image pack (0.9227). Both gate reports carry the warning
> `"only 96 images; the team target is 500+ for release decisions"`. That failure was
> a small-sample artifact, not a property of the model.

**Confuser sha256:** `59d8656fdf0d3cb9035f76e43efc56526ac3a849f83403abb3ecb8ae635b7ed4`
(sha1 `56ed6ee703f8ffd26c4f58fc8bc67df290cee218`, 248 445 B)
**Champion sha256:** `1d6725d72317457d0216fdf2ab431644eb74b3536b446dea81ea2aee72890232`
(sha1 `d90555c8462b6dd6c3432d184b427d4d3e653fda`, 248 447 B)

---

## 4. The eps check — the one that would have silently invalidated everything

`perception_backends.py` reads `id_output_eps` from the `release_summary.json` sitting
next to the ONNX (`onnx.parent.parent / "release_summary.json"`). If it had fallen back
to the champion's default, every "confuser" flight would have been a champion flight in
a different-coloured hat, and nothing in this report would mean anything.

Checked three ways:

1. **Before flying**, both backends instantiated directly and their `info` compared.
2. **Per flight**, from `backend_info` that `follow_person.py` itself writes into
   `summary.json` — the harness refuses to mark a flight VALID unless the ONNX path
   *and* the eps match what that plan row asked for (`scripts/check_model.py`,
   `runs/*/model_check.txt`).
3. **After the fact**, across all 48 runs: exactly one eps and one sha1 per arm.

```
champion   eps 0.0002009823510888964   onnx_sha1 d90555c8462b6dd6c3432d184b427d4d3e653fda   (24/24 flights)
confuser   eps 0.00021179195027798414  onnx_sha1 56ed6ee703f8ffd26c4f58fc8bc67df290cee218   (24/24 flights)
```

**The confuser flew on its own output scale, not the champion's.** The two eps differ
by 5.4%.

---

## 5. The design, and what it realised

```
6 cells x 2 models x 4 repeats = 48 flights, one session, interleaved
A.static__ships     s15_static_offset       45 s
B.moving__ships     s01_control_moving      50 s
C.empty__ships      s02_control_empty       35 s
D.occlusion__ships  s07_occlusion_reappear  60 s
E.furniture__ships  s16_furniture_only      35 s
F.pets__ships       s03_pets_only           35 s
all: chip backend, himax_typical camera, chip speed (6.5 Hz / 153 ms), matte floor
```
Cell definitions copied verbatim from `run_acceptance2.sh`'s CORE matrix.

**Matched pairs.** Each (cell, repeat) is flown by both models back to back — median
**56.5 s apart** (range 51–77 s). Machine drift, thermal state and background load land
on both arms of every comparison equally. Both members of a pair also get the **same
himax noise seed** (`1000 + repeat`), so the sensor draw is not a confound either.

**ABBA counterbalanced.** Which model goes first alternates ABBA across consecutive
pairs, and every cell gets exactly 2 champion-first and 2 confuser-first pairs — so
the "first after a simulator restart" slot is balanced within each cell, not just in
total.

**Repeat index decorrelated from chronological position.** Realised over the 48 flights
that actually flew:

```
corr(repeat, flight order)   Pearson  0.000000    Spearman  0.000000
mean flight order            champion 24.5        confuser  24.5
max consecutive same model   2
same cell in adjacent pairs  0
champion-first / confuser-first pairs   12 / 12
```

Exactly zero, by construction and in the realised order. Per model separately,
Pearson is +0.0135 and −0.0135.

**Why this mattered, concretely.** The champion's own `D.occlusion__ships` relatch time
was 1.24–1.41 s in the matte baseline (Sep 12 afternoon) and 4.09–9.10 s in this
session — same model, same cell, same scene file (`git diff` on `scenes_v2/` is empty),
same seeds, same durations. This session's chip flights also ran at ~163.7 ms step gap
against the baseline's ~158.85 ms. **The D cell's absolute numbers do not reproduce
across sessions.** Every champion-vs-confuser number in this report is immune to that,
because both arms flew in the same session ~57 s apart. A before/after comparison
against the baseline would not have been.

---

## 6. Scoreboard verdicts

Scored by the repo's own unmodified `scoreboard.py`, one suite per model (run dirs
symlinked, nothing copied — `scripts/split_and_score.sh`), 4 repeats per cell.

| cell | champion | confuser |
|---|---|---|
| `A.static__ships` | **PASS** | **FAIL** — M2_heading_err_max_deg, M7_dist_err_settled_mean_m, M7_final_in_band |
| `B.moving__ships` | **PASS** | **FAIL** — M2_heading_err_max_deg, M7_dist_err_settled_mean_m |
| `C.empty__ships` | **PASS** | **PASS** |
| `D.occlusion__ships` | **FAIL** — M9_gt_visible_to_relatch_s | **FAIL** — M9_gt_visible_to_relatch_s |
| `E.furniture__ships` | **PASS** | **PASS** |
| `F.pets__ships` | **FAIL** — M6_max_horizontal_drift_m | **CHARACTERISED** — no gate failed |

**Champion 4 PASS / 2 FAIL. Confuser 2 PASS / 3 FAIL / 1 CHARACTERISED.** Neither
passes the suite.

The gate values behind every failure (worst repeat, as the scoreboard scores hard
gates):

```
A.static     M2_heading_err_max_deg       need <= 12.0   champion  4.435 PASS   confuser 15.950 FAIL
             M7_dist_err_settled_mean_m   need <= 0.75   champion  0.397 PASS   confuser  1.698 FAIL
             M7_final_in_band             need == 1.0    champion  1.0   PASS   confuser  0.0   FAIL
B.moving     M2_heading_err_max_deg       need <= 14.0   champion  8.800 PASS   confuser 29.055 FAIL
             M7_dist_err_settled_mean_m   need <= 0.75   champion  0.519 PASS   confuser  0.824 FAIL
D.occlusion  M9_gt_visible_to_relatch_s   need <= 1.5    champion  4.868 FAIL   confuser  2.764 FAIL
F.pets       M6_max_horizontal_drift_m    need <  0.5    champion  0.974 FAIL   confuser  0.215 PASS
```

The champion arm reproduces the matte baseline on five of six cells (A, B, C, E PASS;
F FAIL on M6). It differs on D — see §5.

---

## 7. False-follow behaviour: the confuser's win

Median over 4 repeats, with all four values. `*` marks a metric where **every matched
pair moved the same way**.

### 7.1 `F.pets__ships` — the dog

| metric | champion | confuser | paired delta |
|---|---|---|---|
| false-follow episodes | 3.5 `[4, 5, 3, 2]` | **0.0** `[0, 0, 1, 0]` | −3.0 `*` |
| time latched on the dog (s) | 2.355 `[1.73, 3.00, 2.98, 0.48]` | **0.0** `[0, 0, 0.16, 0]` | −2.275 `*` |
| drift during episode (m) | 0.091 `[0.064, 0.118, 0.158, 0.001]` | **0.0** | −0.091 `*` |
| max horizontal drift (m) | 0.7475 `[0.674, 0.974, 0.821, 0.476]` | **0.0** `[0, 0, 0.215, 0]` | −0.640 `*` |
| tracking fraction | 0.1305 `[0.109, 0.160, 0.152, 0.035]` | **0.0** `[0, 0, 0.014, 0]` | −0.1235 `*` |
| time to first false follow (s) | 0.635 `[0.31, 1.10, 0.79, 0.48]` | 7.1 (one flight only) | +6.31 `*` |
| confidence on the dog, max | 0.8755 `[0.884, 0.909, 0.867, 0.820]` | **0.7485** `[0.737, 0.745, 0.752, 0.766]` | −0.131 `*` |
| confidence on the dog, mean | 0.5577 | **0.5241** | −0.053 `*` |
| frames on the dog above the 0.70 latch | **19.2%** `[14.5, 18.7, 20.0, 19.7]` | **2.49%** `[4.4, 2.2, 2.8, 0.7]` | −16.9 pp `*` |

The champion latches the dog within **0.31–1.10 s** of every flight starting, in all
four repeats, and drifts up to **0.974 m** across the room chasing it. The confuser
latched once, in one of four flights, at 7.1 s, for 0.16 s, moving 0.215 m.

Note the mechanism: the confuser's confidence on the dog still crosses 0.70 on 2.49%
of frames. What stops it is the follower's 3-consecutive-frame confirmation rule — it
gets isolated frames over threshold, never three in a row.

### 7.2 `C.empty__ships` and `E.furniture__ships` — nothing to chase

**Both models: zero false-follow episodes, zero drift, zero tracking, in all 8 flights
each.** No difference in behaviour. There is still a difference in margin:

| | champion | confuser | delta |
|---|---|---|---|
| `C.empty` mean confidence, empty room | 0.4547 | 0.2953 | −0.160 `*` |
| `C.empty` max confidence | 0.4937 | 0.3443 | −0.158 `*` |
| `E.furniture` mean confidence | 0.3666 | 0.2164 | −0.150 `*` |
| `E.furniture` max confidence | 0.4567 | 0.2802 | −0.183 `*` |

Neither model comes anywhere near the 0.70 latch in either scene — the champion's worst
is 0.497. The confuser carries ~0.16 more margin, which is real but currently unused.

---

## 8. Tracking a person: the confuser's loss

| | | champion | confuser | paired delta |
|---|---|---|---|---|
| **A.static** | tracked fraction while in view | 0.9902 | **0.0000** | −0.9902 `*` |
| | pointing error, mean (deg) | 3.61 | 15.95 | +12.34 `*` |
| | pointing error, max (deg) | 4.435 | 15.95 | +11.5 `*` |
| | distance error, settled (m) | 0.397 | 1.698 | +1.301 `*` |
| | final distance (m) | 2.286 | 3.640 | +1.354 `*` |
| | fraction in the distance band | 0.7685 | 0.0000 | −0.7685 `*` |
| | longest unlatched, person in view (s) | 0.157 | **33.26** | +32.5 `*` |
| | confidence on the person | 0.818 | 0.586 | −0.230 `*` |
| **B.moving** | tracked fraction while in view | 0.9915 | **0.0906** | −0.8715 `*` |
| | pointing error, mean (deg) | 3.375 | 15.905 | +12.5 `*` |
| | pointing error, max (deg) | 8.80 | 29.055 | +20.2 `*` |
| | distance error, settled (m) | 0.519 | 0.8235 | +0.329 `*` |
| | flights ending with the person lost | **0 of 4** | **4 of 4** | `*` |
| | longest unlatched, person in view (s) | 0.155 | **19.55** | +18.8 `*` |
| | confidence on the person | 0.878 | 0.533 | −0.333 `*` |
| **D.occlusion** | tracked fraction while in view | 0.5002 | **0.0415** | −0.4656 `*` |
| | pointing error, mean (deg) | 6.77 | 16.83 | +10.2 `*` |
| | flights ending with the person lost | **0 of 4** | **3 of 4** | |
| | longest unlatched, person in view (s) | 15.48 | **26.43** | +11.1 `*` |
| | confidence on the person | 0.580 | 0.378 | −0.207 `*` |

**On `A.static` the confuser never latched onto the person — not once, in four flights
of roughly 33 s each.** Its pointing error of 15.95° and distance of 3.64 m are
identical to three decimals across all four flights because the drone never moved: those
are the geometry of the spawn point, not a control result.

### 8.1 The relatch number that looks better and is not

`D.occlusion`'s gate metric, M9_gt_visible_to_relatch_s, reads **champion 4.868 s,
confuser 2.764 s**. Taken at face value the confuser reacquires faster. The per-flight
record says otherwise:

```
champion  r1  3 losses, relatched [5.491, 0.469, 1.745]   ended latched   tracked 53.1% of in-view frames
champion  r2  2 losses, relatched [9.101, 0.937]          ended latched   tracked 46.9%
champion  r3  3 losses, relatched [3.624, 1.409, 4.244]   ended latched   tracked 45.3%
champion  r4  2 losses, relatched [4.091, 0.943]          ended latched   tracked 56.1%
confuser  r1  3 losses, relatched [2.546, 1.401]          ENDED LOST      tracked  5.3%
confuser  r2  2 losses, relatched [2.981]                 ENDED LOST      tracked  7.3%
confuser  r3  0 losses, relatched []                      never latched   tracked  0.0%
confuser  r4  1 loss,   relatched []                      ENDED LOST      tracked  3.1%
```

The champion generated **10 relatch events across 4 flights and recovered from every
one**. The confuser generated **3 events across 4 flights and ended 3 of 4 with the
person still lost**. And `confuser r3` contributes the best-looking loss count in the
whole table — **zero loss episodes** — because it never acquired the person at all, so
there was nothing to lose.

**A metric conditioned on recovering cannot be read as "recovers faster" when the
denominator is what changed.** Both models fail this gate; the reasons are opposite.

---

## 9. Is this just the 0.70 latch threshold?

The follower latches at `--vis-enter 0.70` after 3 consecutive frames, and it flies both
models there, because that is the control loop the drone runs. But the two releases did
not select themselves at the same operating point:

```
plain_follow_prod_qat_v3      (champion)  checkpoint_vis_thresh = quant_eval_vis_thresh = 0.70
plain_follow_eval576_confuser (confuser)  checkpoint_vis_thresh = quant_eval_vis_thresh = 0.60
```

So the champion flies at exactly its own threshold and the confuser flies 0.10 above its
own. That asymmetry needs quantifying, so the per-frame confidences these flights
actually produced were re-scored at a ladder of thresholds with the follower's own
latch rule re-applied (`scripts/threshold_sensitivity.py`).

**This is open loop and it is not a prediction.** If the confuser had latched, the drone
would have turned, closed distance and seen *different* — very likely better — frames.
This bounds the question; it does not answer it.

Median latched fraction with the person in view:

| thr | A.static champ | A.static conf | B.moving champ | B.moving conf | D.occl champ | D.occl conf |
|---|---|---|---|---|---|---|
| 0.45 | 0.9902 | **0.9904** | 0.9915 | 0.3724 | 0.6459 | 0.2096 |
| 0.50 | 0.9902 | **0.9904** | 0.9915 | 0.3208 | 0.6377 | 0.1799 |
| 0.55 | 0.9902 | 0.9739 | 0.9915 | 0.2705 | 0.5929 | 0.1468 |
| **0.60** | 0.9902 | 0.7089 | 0.9915 | 0.2107 | 0.5607 | 0.1242 |
| 0.65 | 0.9902 | 0.0000 | 0.9915 | 0.1679 | 0.5262 | 0.0633 |
| **0.70** | 0.9902 | 0.0000 | 0.9915 | 0.0906 | 0.5002 | 0.0415 |

Median latched fraction on the dog (`F.pets`; C and E are 0.0000 for both models at
every threshold):

| thr | champion | confuser |
|---|---|---|
| 0.45 | 0.5156 | 0.5965 |
| 0.50 | 0.4717 | 0.5056 |
| 0.55 | 0.4344 | 0.3674 |
| **0.60** | 0.3832 | 0.2010 |
| 0.65 | 0.2947 | 0.1034 |
| **0.70** | 0.1302 | **0.0000** |

Three things fall out:

1. **On a static person the threshold explains a lot.** The confuser's confidence sits
   in a narrow band: it would latch 99% of the time at 0.50, 71% at 0.60, and 0% at
   0.65. The 0.70 gate lands just above its distribution.
2. **On a moving or occluded person the threshold explains almost nothing.** Even at
   0.45 — below the follower's *exit* threshold — the confuser reaches only 0.372 on
   `B.moving` and 0.210 on `D.occlusion`, against the champion's 0.992 and 0.646.
3. **At each model's own selected threshold, the champion is better on both axes:**

```
                            champion @ 0.70      confuser @ 0.60
person in view (A/B/D)          0.9670               0.1681
latched on the dog (F.pets)     0.1302               0.2010
```

That is the one framing under which there is no trade at all. Under the
same-threshold framing that these flights actually used, there is a real trade: the
confuser gives up 0.925 of tracking to remove 0.130 of dog-latching.

---

## 10. Flight health

Recorded per flight in `flights.jsonl` and `flight_index.csv`.

| | champion (24) | confuser (24) |
|---|---|---|
| sim_wall_ratio | 0.996 / **0.998** / 1.001 | 0.992 / **0.998** / 1.000 |
| step_gap_ms.max | 163.4 / **163.8** / 183.9 | 163.5 / **163.8** / 178.1 |
| load1 before | 3.95 / **4.68** / 5.75 | 3.99 / **4.75** / 5.57 |
| load1 after | 3.95 / **4.65** / 5.51 | 3.99 / **4.72** / 6.01 |
| \|pitch\| max | 9.651° | 4.895° |
| \|roll\| max | 0.680° | 0.414° |
| pz min | 0.798 m | 0.799 m |
| **attitude upsets** | **0 flights, 0 frames** | **0 flights, 0 frames** |
| below flight floor | 0 frames | 0 frames |

(min / median / max.) No flight anywhere near the |pitch| or |roll| > 30° upset
criterion, and none dropped below the 0.25 m flight floor — the minimum altitude across
all 48 flights was 0.798 m against an 0.80 m hold. Loads are matched between arms, as
the interleaving intends.

Step gaps sit at ~163.8 ms rather than the ~158 ms the 153 ms rate cap implies — about
5 ms of extra per-step jitter compared with the matte baseline's 158.85 ms, on the same
hardware. **It is identical between the two arms** (163.8 median both), so it cannot
bias the comparison, but it is the most likely explanation for the D-cell shift in §5.

**48 of 48 flights VALID on the first attempt. Zero re-flies.**

---

## 11. What this does not prove

* **Nothing here touches hardware.** Every frame is rendered by MuJoCo; the "chip"
  network runs under onnxruntime 1.19.2 in `doryenv`, not on a GAP8. No claim here
  transfers to a real Crazyflie without hardware work.
* **The subjects are flat opaque cards.** MuJoCo 3.13 drops the alpha channel, so every
  person, dog and mannequin in these scenes is a rectangular panel. The rangesweep
  experiment established that such a card foreshortens to nothing past ~40° of viewing
  azimuth, and that this is what drives the `D.occlusion` failures for *both* models.
  **A real person does not foreshorten like that.** So the recall numbers here are a
  property of this scene set as much as of the networks, and the confuser's collapse on
  `B.moving` and `D.occlusion` is not established as a property it would show on real
  people.
* **The threshold question is bounded, not answered.** §9 is an open-loop re-scoring of
  frames captured under a control loop that did not latch. A confuser flown at
  `--vis-enter 0.60` would see a different trajectory and different frames. **If the
  team wants the confuser evaluated at its own operating point, that needs a real
  re-fly**, which this session did not do.
* **Six cells, not fourteen.** Only the chip ("ships-as") cells were flown. The
  `__proven` and `delta_*` cells were not, so nothing here says how the confuser behaves
  on the float backend or the clean camera.
* **One dog, one room, one mannequin set.** `F.pets` is `s03_pets_only` with one dog and
  one cat cutout. The 3.5 → 0 episode result is about these distractors, not about pets
  in general. The still-image pack is the broader evidence there, and it is not mine.
* **`D.occlusion` does not reproduce across sessions.** The champion's own relatch time
  was 1.24–1.41 s in the matte baseline and 4.09–9.10 s here under identical
  configuration. The *within-session* comparison is sound; the absolute D numbers are
  not portable.
* **No statistical test was run.** n=4 matched pairs per cell. Where a comparison is
  called consistent, that means all four pairs moved the same way — it is not a p-value.
* **Recall was not measured the way the still-image pack measures it.** "Tracked
  fraction while the person is in view" is a closed-loop quantity that folds in the
  3-frame confirmation rule, the hysteresis, and the trajectory. It is not per-frame
  recall and the two should not be quoted interchangeably.

---

## 12. The trade, stated both ways

**Not a recommendation. This is the decision Sai, Grace and David are making.**

At the threshold the drone actually flies today (0.70, both models):

* The confuser **eliminates** dog-chasing: 3.5 → 0 false-follow episodes, 2.355 s → 0 s
  latched, 0.974 m → 0.215 m worst-case drift. It converts the one cell the champion
  fails on drift into a cell that fails no gate.
* The confuser **gives up person-following almost entirely** in these scenes: 0.990 →
  0.000 tracked-while-in-view on a static person, 0.992 → 0.091 on a moving one, and it
  ends 4 of 4 moving-person flights and 3 of 4 occlusion flights with the person lost.
* Cost/benefit in latch-fraction terms: **−0.925 of person tracking for −0.130 of dog
  latching.**

At each model's own release-selected threshold (champion 0.70, confuser 0.60):

* The champion is better on **both** axes — 0.967 vs 0.168 person tracking, and 0.130 vs
  0.201 dog latching.

Two things the team may want before deciding, neither of which this session did:

1. **Fly the confuser at `--vis-enter 0.60`**, its own selected threshold. §9 says this
   would recover most of `A.static` and little of `B.moving`, but open-loop re-scoring
   cannot settle it.
2. **Ask whether these cardboard subjects can answer the recall question at all.** The
   rangesweep experiment already showed the scene set stops posing a fair person-detection
   question past ~40° azimuth. The false-alarm result does not depend on that; the recall
   result does.

---

## 13. Files

```
README.md                     this report
plan.tsv                      the 48-flight plan, in flown order
plan_balance.json             counterbalancing and correlation report for the plan
flights.jsonl                 one record per flight: verdict, loads, timing, eps, sha1, attitude
flight_index.csv              the same, flat and readable, in chronological order
progress.log                  the harness's own running log        [*.log - force-added]
analysis.txt / .json          per-cell, per-model, paired analysis
verdicts.txt / .json          scoreboard verdicts and gate values side by side
threshold_sensitivity.txt/.json   the open-loop threshold ladder of section 9
code_hashes_before.txt        the five pinned files, before the first flight
code_hashes_after.txt         the same five, after the last
runs/<model>__<cell>__r<N>a<A>/
    cell.json                 what this flight was asked to do, incl. chip_onnx + expected_eps
    summary.json              the follower's own summary, incl. backend_info (onnx, eps, sha1)
    metrics.json              the scoreboard's metrics for this flight
    follow_log.csv            per-control-step log
    truth.csv                 simulator ground truth for the scene bodies
    check.txt                 scoreboard validity check
    model_check.txt           the per-flight model/eps assertion
    floor_reflectance.txt     the reflectance read out of the flown scene.xml
    floor_manifest.txt        the reflectance read out of the flown manifest.json
    camera_model.json         the himax draw used
    sim.log, follower.log     [*.log - force-added]
    (snap_*.png exist on disk but are NOT tracked - see the note below)
scoreboards/champion_suite/   scoreboard.json/.txt, runs symlinked
scoreboards/confuser_suite/   scoreboard.json/.txt, runs symlinked
scripts/                      everything that produced the above
```

**Render caches and snapshot frames are not tracked**, here or in any other
evidence folder in this repo (simv2, mirror-refly, stability, matte-baseline and
rangesweep all carry zero of each). They are working files, not evidence: the
analysis reads the CSVs and JSON, never the pictures. 26 MB of them entered the
repo briefly through an over-broad `git add -f` and were untracked again;
`cache/` and `snap_*.png` are now in `.gitignore` with the reason. The snapshots
remain on disk for whoever ran the flights. Figures that a reader actually needs
belong at the top level of a results folder and are tracked normally.

**Two deliberate trims**, applied after all analysis was complete and re-verified by
re-running every script afterwards (outputs regenerate identically):

* `runs/*/cache/` removed — cflib parameter-TOC caches, a build artifact of the
  Crazyflie library, identical across runs and read by nothing (5.8 MB).
* `snap_*.png` kept only for **repeat 1 of each model x cell** (12 of 48 flights, 83
  images), so every condition keeps a visual record while the folder stays near the
  size of its companions (247 images removed, 21 MB → 5 MB). Directory is now 17 MB.

### Log files the committing step must force-add

A `*.log` ignore rule exists in `.gitignore` (line 11), so **97 files here are
currently ignored** and will be silently skipped by a plain `git add`:

```
progress.log                     1 file
runs/*/sim.log                  48 files
runs/*/follower.log             48 files
```

They need `git add -f`. This is the same rule that hid run logs in the two previous
publishes (`bb43796`, `d49dd0b`).

---

## 14. Companions, none of them modified

`docs/eval_results/2026-09-13-rangesweep-petsab/` (the azimuth mechanism and the pets
A/B), `docs/eval_results/2026-09-13-matte-baseline/` (the champion's 14-cell matte
baseline), `docs/eval_results/2026-09-13-stability/`, `docs/eval_results/2026-09-12-distance/`,
`docs/sim_results/2026-09-11-simv2/` (the original champion acceptance suite).
