# Can the champion's pet problem be fixed with a config change? Closed loop, 96 flights

**Nothing here was measured on hardware. Every frame is rendered, and the "chip"
network runs under onnxruntime on a laptop, not on a GAP8. Nothing in this report
says anything about a real Crazyflie.**

**The decision to ship the champion is not revisited here.** It is taken as given.
The only question asked is whether the champion's one known flaw — chasing pets —
can be removed by changing the follower's latch rule, with no retraining, no
re-export and no new release.

Ran 2026-09-13 19:52 to 21:31 CDT (00:52 to 02:31 UTC), 98 minutes, on a laptop
running nothing but the user's desktop. `progress.log`, `flights.jsonl` and
`analysis.json` are the authoritative record of when each flight ran.

---

## 1. The answer

**Yes. Raise `--vis-enter` from 0.70 to 0.75. It fixes the pet gate and costs
nothing measurable on either person cell.**

| | drift, worst repeat | pet gate (< 0.5 m) | A.static tracking | B.moving tracking |
|---|---|---|---|---|
| **0.70 / 3 frames** (as shipped) | 1.369 m | **FAIL** (4 of 4 repeats fail) | 0.970 | 0.992 |
| **0.75 / 3 frames** ← **recommended** | **0.376 m** | **PASS** (4 of 4 repeats pass) | **0.991** | **0.992** |
| 0.80 / 3 frames | 0.382 m | PASS (4 of 4 repeats pass) | 0.828 | 0.938 |
| 0.70 / 4 frames | 0.586 m | **FAIL** (2 of 4 repeats fail) | 0.986 | 0.977 |

The three things that decide it:

1. **0.75 clears the gate on every repeat**, with drift 0.162 / 0.309 / 0.289 /
   0.376 m against a 0.5 m limit. The shipped 0.70 fails on every repeat
   (0.856 / 1.369 / 0.869 / 0.824 m).
2. **0.75 costs nothing.** Tracking-while-the-person-is-in-view goes 0.970 → 0.991
   on `A.static` (it went *up*) and 0.9919 → 0.9918 on `B.moving`. Time to first
   latch is unchanged at 0.31 s. This is not "2% recall for the fix" — on these
   cells it is no recall at all.
3. **0.80 buys no extra safety and costs real recall.** Its worst-repeat drift
   (0.382 m) is indistinguishable from 0.75's (0.376 m), so the gate margin is the
   same — but `A.static` tracking falls to 0.828 and the drone sometimes fails to
   acquire a standing person for seconds (worst first-latch 7.00 s, versus 0.31 s
   at both 0.70 and 0.75). That is a worse failure than the number suggests.

**The 4-consecutive-frames probe does not work.** `--confirm-frames 4` at 0.70 cuts
pet drift only to 0.586 m worst / 0.490 m median and still fails the gate on 2 of 4
repeats. It costs 0.15 s of latch latency (one extra frame at 6.5 Hz) for a fix
that does not fix. The threshold is the effective knob; the frame count is not.

### What this does NOT claim

Raising the threshold **reduces** pet-chasing; it does not eliminate it. At 0.75
the drone still logs a median of 1.5 false-follow episodes per flight (down from
4.5) and still spends 3.5% of the flight latched onto the dog (down from 17.1%).
It passes the gate because the movement those episodes produce is now small enough,
not because they stopped. **Configuration buys compliance with the gate, not a
model that knows a dog from a person.** The training fix (hard-negative fine-tune)
is still the real fix; this is a cheap mitigation that makes the release shippable
against the current gate.

---

## 2. How the threshold is set — the exact flags

From `tools/crazysim_macos/follow_person.py` (unmodified), lines 238-240:

```python
ap.add_argument("--vis-enter", type=float, default=0.7)
ap.add_argument("--confirm-frames", type=int, default=3)
ap.add_argument("--vis-exit", type=float, default=0.45)
```

and the state machine, lines 359-363:

```python
streak = streak + 1 if conf >= a.vis_enter else 0
if vis_state and conf < a.vis_exit:            vis_state = False
elif not vis_state and streak >= a.confirm_frames:  vis_state = True
```

* `--vis-enter` (default **0.70**) is the enter threshold.
* `--confirm-frames` (default **3**) is the consecutive-frame rule. The streak is
  strict: any single frame below `--vis-enter` resets it to 0.
* `--vis-exit` (default **0.45**) is the leave threshold, and it is an independent
  condition — between 0.45 and `--vis-enter` the state is *held*, which is the
  hysteresis.
* A stale camera feed (`--stale-hover`, 0.5 s) resets **both** `vis_state` and
  `streak`, so steering only resumes after a fresh full confirmation.

All three are plain command-line arguments, already exposed. **No source file was
edited to run this experiment**, and `--vis-exit` was left at 0.45 in every arm —
the leave threshold was not swept, which is a limit of this study, not a finding.

### One scope warning that matters for "free"

`perception_backends.py` carries a **separate, firmware-level** gate:
`VIS_ENTER_RAW = 4216`, applied as `vis_gate = int(raw_i32[9] >= VIS_ENTER_RAW)`.
It is logged but **not** used by the follower's latch — the follower uses the
decoded `visibility_confidence`. So `--vis-enter` is a **host-side** knob. If the
threshold on the real aircraft lives in GAP8 firmware rather than in the host
follower, changing it is a firmware constant change, not a config change, and
"free" would need re-checking against the firmware release process. That was not
in scope here and has not been verified.

---

## 3. The discipline

### 3.1 The code was pinned, and the pin held

sha256 of `camera_model.py`, `follow_person.py`, `build_scene.py`, `scoreboard.py`,
`patch_crazysim.py` recorded before the first flight and re-checked after the last.
**All five byte-identical** (`code_hashes_before.txt`, `code_hashes_after.txt`):

```
481c0a9999ff19f5f2745978d3a0076cb63a225af31e19f3c4e561ab269029de  tools/crazysim_macos/camera_model.py
4a786441f85b431aa61347cd902d797a55d7cb8bb2d77c2fb64ef71abfb68de6  tools/crazysim_macos/follow_person.py
ea639fea1b14abd12426aaaee4941468ff5402412ab1e42bda78adc2fe3bbe64  tools/crazysim_macos/build_scene.py
00a2a950131a3337614b065450b8cb89371b7ab18f256bed24f5769c2917ef33  tools/crazysim_macos/scoreboard.py
20959b177d2706f4f7980c7e760fe162e82a44ba2dd7504ca3b092bc489d0803  tools/crazysim_macos/patch_crazysim.py
```

**Four of the five are the same hashes the champion-vs-confuser session pinned.**
`camera_model.py` differs (it was `66862b05…` then), because commit `94f34b6`
touched it — but that diff is **11 lines, all docstring**, with no changed line
containing code. The sensor model is therefore behaviourally identical to the one
the previous session flew, and the two sessions' numbers are comparable.
`git status tools/` was clean before and after.

**The repo HEAD moved during this session,** from `94f34b6` to `c4d6483`
(`6d96277` "Decision: the team ships the champion", `c4d6483` "Progress record").
Those two commits touch only `DECISIONS.md`, `EXPERIMENTS.md`,
`docs/hardware/lab_session_runbook.md` and `docs/progress/sai_maruvada.md` —
**nothing under `tools/` or `docs/eval_results/`**, which the sha256 pin
independently confirms. They were not made by this workstream. **Nothing in this
directory has been committed or pushed.**

### 3.2 Nothing under measurement was modified

`follow_person.py`, `perception_backends.py`, `build_scene.py`, `camera_model.py`,
`scoreboard.py` and `run_acceptance2.sh` are the repo's own and were **imported and
run, never edited**. The latch rule is selected purely through existing
command-line arguments; no default was changed and nothing was patched at runtime.
Every scene is the repo's own `tools/crazysim_macos/scenes_v2/`, unmodified. No
existing directory under `docs/sim_results/` or `docs/eval_results/` was touched.

### 3.3 The floor was asserted per flight, two ways

Before each flight the harness reads the `reflectance` attribute out of the
`scene.xml` about to be flown *and* `room.floor_reflectance` out of that scene's
`manifest.json`, and aborts the flight if either is not 0.0. Both are written into
the run directory (`floor_reflectance.txt`, `floor_manifest.txt`).

**All 96 flights: xml 0.0, manifest 0.0.** No exceptions, no overrides.

### 3.4 The model was verified per flight

`check_model.py` re-reads `backend_info` out of each flight's own `summary.json` and
refuses to call a flight VALID unless the ONNX path, the `id_output_eps` and the
backend are the champion's. Across all 96 flights: **1 distinct ONNX, 1 distinct
eps, 1 distinct sha1**. This is a single-model experiment and it is checked, not
assumed.

### 3.5 The latch rule was verified per flight — from the flight, not the command line

This is the check the experiment most needed. `follow_person.py` does **not** record
`--vis-enter` or `--confirm-frames` into `summary.json`, so there is no self-reported
field to trust: a harness typo could have flown all 96 flights at 0.70 and every
"result" would have been noise.

So `check_threshold.py` recovers the rule from the flight log instead. It replays
the follower's four-line state machine over the logged `conf` column and requires it
to reproduce the logged `streak` **and** `tracking` columns **exactly, frame for
frame**. It also replays the other three candidate rules and reports whether any of
them also fits, because a check that cannot fail is not a check.

* **96 / 96 flights reproduce their intended rule exactly.**
* **64 are uniquely discriminating** — no other candidate rule fits the log.
* **32 are ambiguous**, and all 32 are `C.empty` (16) and `E.furniture` (16), where
  confidence never crosses 0.70 at all, so all four rules are genuinely identical
  (never latch). That is the correct answer for those cells, not a gap in coverage.
* Distinct `(vis_enter, confirm_frames)` pairs actually flown: `(0.7, 3)`,
  `(0.7, 4)`, `(0.75, 3)`, `(0.8, 3)` — all four arms really happened.

The method was validated first against the previous session's 24 known-0.70
champion flights: the 0.70 replay reproduced all 24 exactly, and was uniquely
discriminating on 16.

---

## 4. The design, and the realised balance

96 flights = **1 model (the champion) × 4 latch rules × 6 chip cells × 4 repeats**,
one sitting, fully interleaved.

| arm | `--vis-enter` | `--confirm-frames` | `--vis-exit` |
|---|---|---|---|
| `t070` | 0.70 | 3 | 0.45 |
| `t075` | 0.75 | 3 | 0.45 |
| `t080` | 0.80 | 3 | 0.45 |
| `t070cf4` | 0.70 | 4 | 0.45 |

Cells are the repo's own CORE matrix rows (`run_acceptance2.sh` lines 72-77),
copied verbatim, all chip backend / chip speed / `himax_typical`:
`A.static` (45 s), `B.moving` (50 s), `C.empty` (35 s), `D.occlusion` (60 s),
`E.furniture` (35 s), `F.pets` (35 s).

* **Matched quadruples.** The same (cell, repeat) is flown by all four rules back
  to back, within a few minutes. Machine drift, thermal state and background load
  land on all four arms of every comparison equally.
* **The camera seed depends only on the repeat index**, so the four arms in a
  matched block see the *same* himax noise draw. Any difference between them is the
  latch rule, not the camera.
* **An exact Latin square on the within-block slot.** Each cell has exactly 4
  blocks and there are exactly 4 rules, so each rule occupies each slot
  (1st/2nd/3rd/4th) **exactly once per cell** and exactly 6 times overall. Going
  first is not free — the simulator has just been rebuilt — and this cancels it
  exactly. This is why the design uses 4 repeats rather than the 3 minimum asked
  for: with 3 repeats the balance could only have been approximate.

**Realised balance, measured from what actually flew** (`plan_balance.json`,
and re-derived in `analysis.json` → `report.realised_balance`):

| property | value |
|---|---|
| repeat index vs flight order, Pearson | **0.0** |
| repeat index vs flight order, Spearman | **0.0** |
| mean flight order, t070 / t075 / t080 / t070cf4 | **48.5 / 48.5 / 48.5 / 48.5** |
| Latin square exact per cell | **true** |
| same cell in adjacent blocks | **0** |

Repeat index is exactly decorrelated from chronological position, and no arm sits
earlier or later in the session than any other.

### Flight validity

**96 of 96 planned flights are VALID.** One flight (order 12, `t070cf4 A.static r1`)
hung at follower startup on its first attempt — an empty `follower.log`, killed by
the harness's 135 s watchdog — and its automatic retry was clean (61 s, tracking
0.986). Both attempt directories are kept; `split_and_score.sh` links only the
attempt that produced a flight, so each scored suite is exactly 24 runs. That is
the only non-clean event in 97 flight records.

---

## 5. The result on the pet cell

`F.pets__ships`, hard gate **`M6_max_horizontal_drift_m` < 0.5 m**, evaluated on
the worst repeat. Everything else in class F is characterised, not gated.

| arm | drift per repeat (m) | worst | median | gate | false-follow episodes | tracked fraction |
|---|---|---|---|---|---|---|
| **t070** | 0.856 / 1.369 / 0.869 / 0.824 | 1.369 | 0.863 | **FAIL** | 4 / 5 / 5 / 3 (med 4.5) | 0.171 |
| **t075** | 0.162 / 0.309 / 0.289 / 0.376 | **0.376** | 0.299 | **PASS** | 2 / 1 / 2 / 1 (med 1.5) | 0.035 |
| **t080** | 0.260 / 0.214 / 0.382 / 0.113 | **0.382** | 0.237 | **PASS** | 1 / 1 / 1 / 2 (med 1.0) | 0.035 |
| **t070cf4** | 0.586 / 0.401 / 0.399 / 0.579 | 0.586 | 0.490 | **FAIL** | 4 / 2 / 2 / 4 (med 3.0) | 0.073 |

The separation is clean: **0.70 fails on 4 of 4 repeats, 0.75 and 0.80 pass on 4 of
4.** There is no overlap between the two groups — the best 0.70 flight (0.824 m) is
worse than the worst 0.75 flight (0.376 m).

**Matched-block deltas** (same cell, same repeat, same noise seed), which is the
comparison that controls for machine state:

| arm vs t070 | r1 | r2 | r3 | r4 | all same direction |
|---|---|---|---|---|---|
| t075 − t070, drift | −0.694 | −1.060 | −0.580 | −0.448 | **yes** |
| t080 − t070, drift | −0.596 | −1.155 | −0.487 | −0.711 | **yes** |
| t070cf4 − t070, drift | −0.270 | −0.968 | −0.470 | −0.245 | yes, but not enough |

Every one of the 12 matched comparisons moved the same way.

### This reproduces, and slightly overshoots, the known failure

The brief records the champion at 0.70 drifting **0.974 m** with ~3.5 false-follow
episodes. This session's independently flown 0.70 arm gives **1.369 m worst** and
**4.5 median episodes** — same verdict, same direction, but a worse worst case.
`F.pets` therefore carries real session-to-session spread on the 0.70 arm, which is
one more reason the conclusion rests on the matched within-session deltas rather
than on comparing today's 0.75 against last night's 0.70.

---

## 6. The cost on the person cells

### `A.static__ships`

| arm | tracked-while-in-view (per repeat) | median | time to first latch (s) | heading err mean | settled dist err |
|---|---|---|---|---|---|
| t070 | 0.991 / 0.949 / 0.991 / 0.919 | 0.970 | 0.31 / 0.31 / 0.31 / 0.31 | 3.65° | 0.347 m |
| **t075** | 0.991 / 0.959 / 0.991 / 0.991 | **0.991** | 0.31 / 0.32 / 0.31 / 0.31 | 4.32° | 0.334 m |
| t080 | 0.792 / 0.938 / 0.833 / 0.823 | **0.828** | **7.00** / 0.46 / 0.31 / 0.31 | 4.60° | 0.358 m |
| t070cf4 | 0.986 / 0.986 / 0.986 / 0.939 | 0.986 | 0.46 / 0.47 / 0.47 / 0.47 | 4.09° | 0.305 m |

### `B.moving__ships`

| arm | tracked-while-in-view (per repeat) | median | time to first latch (s) | heading err mean | settled dist err |
|---|---|---|---|---|---|
| t070 | 0.991 / 0.992 / 0.992 / 0.992 | 0.992 | 0.31 / 0.32 / 0.31 / 0.31 | 3.14° | 0.525 m |
| **t075** | 0.992 / 0.992 / 0.992 / 0.992 | **0.992** | 0.32 / 0.32 / 0.31 / 0.32 | 3.18° | 0.529 m |
| t080 | 0.885 / 0.992 / 0.819 / 0.992 | **0.938** | **4.41** / 0.31 / **1.08** / 0.31 | 3.35° | 0.522 m |
| t070cf4 | 0.964 / 0.987 / 0.987 / 0.967 | 0.977 | 1.25 / 0.47 / 0.47 / 0.47 | 3.25° | 0.548 m |

Both cells **PASS** their gates in all four arms — the recall cost at 0.80 is real
but not large enough to break a gate. Heading error and settled distance are
essentially flat across all four arms; the threshold does not affect how well the
drone flies *once latched*, only whether and when it latches.

**The important cost at 0.80 is not the average, it is the tail.** The longest
stretch of "person plainly in view, drone not latched" goes:

| arm | A.static | B.moving |
|---|---|---|
| t070 | 0.63 s | 0.15 s |
| **t075** | **0.15 s** | 0.16 s |
| t080 | **5.24 s** | **2.21 s** |
| t070cf4 | 0.31 s | 0.47 s |

At 0.80 the drone spent **5.2 seconds** failing to acquire a stationary person who
was directly in front of it. That is an operational failure a 2%-recall summary
completely hides, and it is the reason this report recommends 0.75 rather than the
lower-false-alarm 0.80.

---

## 7. The other safety cells

`C.empty__ships` and `E.furniture__ships` — hard gates: zero false-follow episodes,
zero tracking fraction, drift < 0.10 m.

**All four arms PASS both cells on all four repeats, with drift exactly 0.000 m,
0 episodes and 0.0000 tracking.** Neither an empty room nor furniture elicits
anything from the champion at any threshold tested — confidence there never reaches
even 0.70. These cells contain no information about the threshold, which is exactly
what the 32 "ambiguous" latch-rule checks in §3.5 record.

---

## 8. `D.occlusion__ships` — FLAGGED, not evidence

This cell does not reproduce across sessions under identical configuration (the
champion's own relatch was 1.24-1.41 s in one session and 4.09-9.10 s in another).
It is reported for completeness and **is not used to support any conclusion.**

| arm | relatch median | all four relatch times (s) | tracked-in-view |
|---|---|---|---|
| t070 | 2.43 | 3.754 / 9.563 / 1.101 / 0.309 | 0.521 |
| t075 | 4.02 | 3.462 / 4.581 / 3.258 / 9.639 | 0.481 |
| t080 | 5.65 | 7.094 / 1.579 / 5.482 / 5.809 | 0.466 |
| t070cf4 | 3.78 | 3.918 / 1.420 / — / 3.780 | 0.513 |

The within-arm spread (0.309 s to 9.563 s in the *shipped* arm alone) is larger than
any between-arm difference, so this data cannot separate the arms. **D fails its
gate in all four arms, including the shipped 0.70**, which is a pre-existing
condition of this cell and not something a threshold change caused.

---

## 9. How wrong was the open-loop lead?

This is the question the brief asked to settle, and it is worth recording precisely,
because the answer is "wrong in both directions".

Open-loop = the arm's latch rule replayed over **this session's own** 0.70 frames.
Closed-loop = the same rule actually flown, same cell, same repeat, same noise seed.

| | false alarms on `F.pets` | | recall on `A.static` | |
|---|---|---|---|---|
| | open-loop | **closed-loop** | open-loop | **closed-loop** |
| 0.75 | 0.0735 | **0.0351** | 0.9698 | **0.9906** |
| 0.80 | 0.0102 | **0.0354** | 0.9507 | **0.8279** |
| 0.70 / 4 frames | 0.0967 | **0.0732** | 0.9624 | **0.9857** |

* At **0.75** open-loop was *pessimistic* on both axes: the real thing latched onto
  the dog half as often as predicted and tracked people better than predicted.
* At **0.80** open-loop was *optimistic* on both axes at once, and materially so:
  it predicted pet latching would nearly vanish (0.0102) when in flight it was
  **3.5× worse** (0.0354), and it predicted a ~2% recall cost when the real cost on
  `A.static` was **12.3 points** (0.951 → 0.828).

So the brief's instinct was right. **The open-loop re-scoring would have led the
team to pick 0.80** — the threshold it scored as "false alarms → 0.0000 for about 2%
recall". In closed loop 0.80 is the worse of the two passing options: same gate
margin as 0.75, and a multi-second acquisition failure on a standing person. The
closed-loop flight was necessary to get this right, and it changed the answer.

### A discrepancy in the numbers quoted to this workstream

The task brief quoted this table as the open-loop lead:

```
threshold   tracking a person   false alarms
  0.70          0.9904             0.0176
  0.75          0.9904             0.0070
  0.80          0.9729             0.0000
```

**Those false-alarm figures do not appear in the cited file.**
`docs/eval_results/2026-09-13-champion-vs-confuser/threshold_sensitivity.txt`
actually reports, for the champion's median latched fraction on `F.pets`:
**0.1302 at 0.70, 0.0439 at 0.75, 0.0138 at 0.80** — an order of magnitude higher,
and *not* zero at 0.80. I could not reproduce `0.0176 / 0.0070 / 0.0000` from any
series in `threshold_sensitivity.json` either. `DECISIONS.md`'s "0.80 costs about 2%
recall for zero [false alarms]" carries the same optimism. Whoever writes up the
next round should re-derive that table rather than re-quote it. It does not change
this report's conclusion — the closed-loop flights supersede it either way — but it
was pointing at 0.80, and 0.80 is the wrong answer.

---

## 10. Machine health

Recorded per flight in `flights.jsonl`.

| | min | median | max |
|---|---|---|---|
| load average (1 min), before flight | 2.07 | 3.38 | 6.67 |
| `sim_wall_ratio` | 0.982 | 0.998 | — |
| `step_gap_ms.max` (chip class) | — | 163.7 | 333.3 |

**Attitude upsets: 0 of 96 flights.** Worst `|pitch|` 9.08°, worst `|roll|` 0.68°,
minimum `pz` 0.789 m — all far inside the ±30° and 0.25 m floor criteria. This
extends the zero-upset record to 150+ matte flights. **Torn frames across the whole
session: 0.**

Health is even across arms, so no arm was favoured by machine state:

| arm | median load1 | median sim/wall | min sim/wall | worst step gap | median Hz | upsets |
|---|---|---|---|---|---|---|
| t070 | 3.56 | 0.998 | 0.989 | 333.3 ms | 6.362 | 0 |
| t075 | 3.45 | 0.998 | 0.994 | 181.2 ms | 6.361 | 0 |
| t080 | 3.23 | 0.998 | 0.982 | 183.9 ms | 6.367 | 0 |
| t070cf4 | 3.35 | 0.998 | 0.992 | 163.9 ms | 6.364 | 0 |

The single 333.3 ms step gap (one flight, t070 arm) is about two chip periods and is
the worst in the session; every other arm's worst is under 184 ms. It did not
produce an upset or an invalid flight.

---

## 11. What this does not prove

* **No hardware.** Every frame is rendered by the MuJoCo/himax model and the "chip"
  network runs under onnxruntime, not on a GAP8. Nothing here transfers to a real
  Crazyflie without a hardware check.
* **The threshold may not live where this experiment changed it.** `--vis-enter` is
  a host-side follower argument. `perception_backends.py` shows a separate firmware
  gate (`VIS_ENTER_RAW = 4216`) which this sweep did **not** touch. Whether "raise
  it to 0.75" is genuinely free depends on which of the two the shipped aircraft
  uses, and that was not established here.
* **One scene per condition.** `F.pets` is `s03_pets_only`, a single pet scene with
  a fixed layout. "The pet gate passes at 0.75" means *this* scene, 4 repeats. It
  is not a claim about pets in general, and the per-frame 30.2% false-alarm rate on
  pets and mannequins is a property of the network that this change does not touch.
* **The leave threshold was not swept.** `--vis-exit` stayed at 0.45 in all 96
  flights. A joint (enter, exit) sweep might do better than either alone.
* **Only four latch rules.** Nothing between 0.70 and 0.75, or between 0.75 and
  0.80, was flown; 0.75 is the best of four tested points, not an optimum.
* **`D.occlusion` is uninformative here**, by its own documented instability, and
  fails in all four arms including the shipped one.
* **Four repeats is a small worst-case sample.** The gate is decided on the worst
  repeat, and the worst of 4 is a weak estimator of the true worst case. 0.75's
  margin (0.376 m against 0.5 m) is real but not large; a longer campaign could
  find a worse repeat.
* **This says nothing about the champion-vs-confuser decision**, which was taken
  before this session and is not revisited.

---

## 12. Files, and what needs force-adding

```
README.md                      this file
plan.tsv                       the 96-flight plan, as generated
plan_balance.json              the pre-flight balance proof
flights.jsonl                  97 flight records: verdicts, health, load, attitude
progress.log                   the session's own chronological log        [*.log - needs -f]
analysis.json / analysis.txt   per-flight metrics, per-arm table, matched deltas
openloop_vs_closedloop.json/.txt   §9
verdicts.txt                   the per-cell verdict matrix across the four arms
code_hashes_before.txt         sha256 pin, before the first flight
code_hashes_after.txt          sha256 pin, after the last flight (identical)
scripts/                       make_plan.py, fly_plan_thresholds.sh, check_model.py,
                               check_threshold.py, analyze.py, split_and_score.sh,
                               openloop_vs_closedloop.py
scoreboards/{t070,t075,t080,t070cf4}_suite/   one scored suite per arm (24 runs each)
runs/<config>__<cell>__r<N>a<M>/              97 run directories
```

**Nothing here has been committed or pushed.** When someone does commit it:

* These need `git add -f`, because `.gitignore` line 11 is `*.log`:
  * `progress.log`
  * `runs/*/follower.log` (97 files)
  * `runs/*/sim.log` (97 files)
* **Do not force-add `runs/*/snap_*.png`.** They are ignored deliberately
  (`.gitignore` line 24, added 2026-09-12 after a blanket `git add -f` swept 330
  snapshots into a results commit). The metrics, logs and truth are the evidence;
  the pictures are not.
* `scripts/__pycache__/` is ignored and should stay ignored.
* Everything else (`*.json`, `*.csv`, `*.txt`, `*.tsv`, `README.md`) adds normally.
* The `scoreboards/*/runs/*` entries are **relative symlinks** into `../../../runs/`,
  so they survive a clone or a move.
