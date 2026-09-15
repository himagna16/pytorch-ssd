# Does the shipped 0.75 entry bar cost an ORDINARY person acquisition? Flying 0.70 against 0.75

Session 2026-09-15, repo `pytorch_ssd` at `017f47f` (clean at launch and at the
end). **Simulation only - no hardware, no GAP8, no firmware.** The "chip"
network is `model_id_dory.onnx` under the repo's own `ChipPerception`, the
camera is `camera_model.himax_typical`, and every flight is CrazySim headless on
the matte floor. **36 scored flights** (38 attempted, 2 re-flown), 23:36:57 to
00:20:29 local, 44 minutes, every one behind the shared simulator lock.

**Nothing under `tools/` was edited** - the five tool hashes are pinned before
and after and are identical (§7), and all 22 `scene_defs/*.json` hash
identically before and after. **No scene was built or rebuilt here:** the four
`tp*` variants and the two originals are the artefacts
`docs/eval_results/2026-09-15-typical-person/` built last night, reused in
place, and every flight records the sha256 of the `scene.xml` it actually
loaded (§7). Nothing was committed or pushed.

---

## 0. The question, and why it had to be asked

Two days ago the follower's confirmation bar went from 0.70 to 0.75, propagated
through the host, the contract and the GAP8 firmware, and merged. The cost on
people was measured as nil: tracking stayed at 0.97-0.99.

Last night (`docs/eval_results/2026-09-15-typical-person/`) it emerged that every
one of those person measurements used COCO 19432 - a cutout at roughly the
**98.5th-100th percentile** of rendered detectability - and that with a
median-detectability or 25th-percentile person the drone **never latches at
all**: 11 of 12 flights, tracking fraction 0.000. The binding constraint is the
**entry** gate, three consecutive frames at or above the bar, and two flights
missed latching by a single frame.

So the cost of raising the bar was measured on the one subject for whom the bar
could not possibly matter. **This directory turns the bar back down and reflies
the same cells.**

---

## 1. TL;DR

| claim | verdict |
|---|---|
| **THE HEADLINE** | **Mostly (b), with a real but narrow (a) in one cell of four - and the (a) does not convert into following.** In **three of the four** ordinary-person cells neither bar acquires, because the confidence never comes near either one: longest above-bar run is **0 at both arms**, and the bar would have to fall to **0.32-0.55** to buy a single latch. In **one** cell (`B.moving__median`) the change genuinely bites: **0.70 latches 3/3 flights, 0.75 latches 1/3**. But in that same cell the drone is actually tracking for **2.36 s of 111.9 s flown at 0.70** against **1.90 s of 109.1 s at 0.75** - tracking fraction 0.013 median against 0.000. It latches, yaws, and loses the person within 3-7 frames. |
| **Does 0.75 materially hurt acquisition?** | **It materially hurts the ENTRY GATE in one of four cells and is irrelevant in the other three. It does not materially change whether the drone follows an ordinary person, because it does not follow one at either bar.** |
| **Why only that one cell** | The entry-gate margin expressed as a threshold, `b*` = the highest bar at which a flight's own trace contains 3 consecutive frames. `B.moving__median` has **b* = 0.744 / 0.748 / 0.751** on the three 0.75 flights - the shipped bar sits *inside* that distribution, within 0.006 of all three. The other three cells have **b* = 0.318-0.368** (static median, static p25) and **0.516-0.551** (moving p25): 0.15 to 0.43 below even the 0.70 bar |
| **The control validates the rig at both arms** | `A.static__control` **0.990** (0.70) and **0.990** (0.75) against the published `A.static__ships` 0.9905; `B.moving__control` **0.992** and **0.991** against the published 0.992. All four PASS. The rig still reproduces 0.99 |
| **The entry-gate rule holds again** | Across all **36** flights, **a flight latched if and only if its longest above-bar run reached 3** (`scripts/analyze_enter.py` checks it as a rule). Last night's finding replicates exactly |
| **The extra latches make pointing WORSE, not better** | In `B.moving__median`, heading error max is **25.3 / 24.5 / 30.7 deg at 0.70** against **21.8 / 21.8 / 21.8 at 0.75**. 21.78 deg is the *passive* value - the bearing to a person the drone never turned toward. The momentary latches yaw the drone at a detection it then drops, leaving it pointed further off than if it had never moved |
| **Statistical honesty** | 3 repeats per arm. `B.moving__median` 3/3 vs 1/3 is **Fisher p = 0.400**; pooling the 0.75 arm with last night's three 0.75 flights on the same cell (3/3 vs 2/6) gives **p = 0.167**. Neither is significant. The *mechanistic* evidence - b* within 0.006 of 0.75 on all three flights, and the paired run-length shift - is much stronger than the latch count |
| **Scoreboard verdicts** | control **PASS** at both arms on both cells; all four typical-person cells **FAIL** at both arms, on `M2_heading_err_max_deg`, `M7_dist_err_settled_mean_m` and `M7_final_in_band`. As last night, `M1_tracking_fraction` is *provisional* (report-only) on the himax camera, so the 0.99 -> 0.00 collapse still does not itself fail a gate |
| **What this does NOT establish** | No hardware. Rendered flat cutouts, no parallax or limb articulation. A rendered median person is *harder* than a real one, so these cells bracket the real answer from the pessimistic side. Two subjects, not a distribution. One start geometry (§6) |

**The honest one-line version:** *turning the bar back down to 0.70 rescues
acquisition in exactly one of the four ordinary-person cells, and even there the
drone tracks the person for about two seconds of a thirty-seven second flight -
so the shipped 0.75 has a real and previously invisible cost at the entry gate,
and reverting it would not give the team a working person-follower.*

---

## 2. The answer to the question that was asked

> **At 0.70, does an ordinary person get acquired where they do not at 0.75?**

**In one of four cells, yes. In three of four, no - and the "no" is not close.**

| cell | subject | 0.70 latched | 0.75 latched | outcome |
|---|---|---|---|---|
| `A.static__median` | COCO 250127, 52.1st pct | **0 / 3** | **0 / 3** | **(b)** neither acquires |
| `A.static__p25` | COCO 124442, 28.4th pct | **0 / 3** | **0 / 3** | **(b)** neither acquires |
| `B.moving__p25` | COCO 124442, 28.4th pct | **0 / 3** | **0 / 3** | **(b)** neither acquires |
| `B.moving__median` | COCO 250127, 52.1st pct | **3 / 3** | **1 / 3** | **(a)** 0.70 acquires, 0.75 mostly does not |
| `A.static__control` | COCO 19432, 99.2nd pct | 3 / 3 | 3 / 3 | (c) both, at 0.990 |
| `B.moving__control` | COCO 19432, 99.2nd pct | 3 / 3 | 3 / 3 | (c) both, at 0.992 / 0.991 |

**Quantified, in the units the decision is made in.** The entry-gate margin
expressed as a threshold - `b*`, the highest bar at which a flight's own
confidence trace contains three consecutive frames - says exactly how far the
bar is from mattering:

| cell | b* across its 6 flights | 0.70 | 0.75 | how far the bar would have to fall |
|---|---|---|---|---|
| `A.static__median` | **0.318 - 0.342** | miss by 0.36 | miss by 0.41 | below the **0.45 exit bar** |
| `A.static__p25` | **0.340 - 0.368** | miss by 0.33 | miss by 0.38 | below the **0.45 exit bar** |
| `B.moving__p25` | **0.516 - 0.551** | miss by 0.15 | miss by 0.20 | to ~0.55 |
| `B.moving__median` | **0.702 - 0.814** | **hits** | **straddles** | **the shipped bar sits inside this band** |
| controls | **0.918 - 0.991** | hits | hits | the bar is nowhere near binding |

For the two static cells the bar would have to fall **below the 0.45 exit bar**
before the entry gate opened - at which point "enter" would be below "exit" and
the hysteresis rule would be incoherent. **The entry bar is not the free
parameter that rescues those cells. Nothing in the 0.70-0.75 range is.**

---

## 3. How it was flown

`scripts/fly_plan_enter.sh`, with `scripts/make_plan.py` generating the order.
`run_acceptance2.sh` could not be used: it has no way to pass a detection
threshold to `follow_person.py` (its argument list is `--duration/--out/
--backend/--rate-hz/--latency-ms` and nothing else), and its CORE matrix is
hard-coded so it cannot name the `tp*` scenes at all. Rather than edit the
harness, the runner's `fly()` is a faithful copy of
`docs/eval_results/2026-09-14-exit-bar/scripts/fly_plan_exit.sh`, which is
itself a copy of the harness's own `fly()`. **Diffed against it, the only
changes are: which threshold is the parameter, the run-directory prefix, the log
labels, and one added line recording the scene's sha256.** The
`follow_person.py` invocation, simulator launch, environment
(`CRAZYSIM_TRUTH_LOG` / `_TRUTH_PREFIX` / `_SCENE_MOTION` / `_SENSOR_PRESET` /
`_SENSOR_SEED` / `_SENSOR_INFO`), `cell.json` keys, `perl alarm` watchdog,
teardown, and `scoreboard.py --check-run` gate with one re-fly on INVALID are
byte-identical.

**Arms.** `--vis-enter 0.70` and `--vis-enter 0.75`. **Both arms also pass
`--vis-exit 0.45` and `--confirm-frames 3` explicitly, at their default values**,
so the two command lines are constructed identically and differ in one number.
For the 0.75 arm this is behaviourally identical to the shipped default, which
is what makes it comparable to last night's no-flag flights.

**Setup: ships-as on every cell** - chip backend, `himax_typical`, 6.5 Hz /
153 ms. Durations are the matrix's own: 45 s static, 50 s moving.

**Pairing.** The sensor seed is the harness's own `1000 + repeat`, which depends
only on the repeat index, so **the two arms of a repeat see the same himax noise
draw**. `scripts/verify_run.py` confirms per pair that the camera's identity
block (`preset`, `seed`, `width`, `height`, `params`, `unmeasured`, `derived`)
is identical, and that all 13 setup fields match.

**Order.** The arms are interleaved flight by flight, which arm goes first
alternates, and the cell order rotates each repeat, so neither arm is
systematically early or late (`plan_block1.tsv`).

---

## 4. Results

Read from `tables/per_cell_arm.tsv`, `tables/per_flight.tsv`,
`tables/margin_threshold.txt` and the two per-arm `scoreboards/`. Confidence
statistics are over frames where the target is inside the model's +-35 deg crop,
which is **every frame of every flight** - nothing here is a field-of-view
artefact.

### 4.1 Tracking fraction and acquisition, per cell and arm

| cell | arm | M1 median [min, max] | latched | t to first latch | losses | re-acq | time not tracking | heading mean (max) |
|---|---|---|---|---|---|---|---|---|
| `A.static__control` | 0.70 | **0.990** [0.971, 0.991] | 3/3 | 0.31 s | 1 | 1 | 0.16 s | 3.59 (5.89) |
| `A.static__control` | 0.75 | **0.990** [0.990, 0.991] | 3/3 | 0.31 s | 0 | 0 | 0.15 s | 3.82 (4.40) |
| `A.static__median` | 0.70 | **0.000** [0.000, 0.000] | **0/3** | never | 0 | 0 | **32.48 s (100%)** | *15.95 (15.95)* |
| `A.static__median` | 0.75 | **0.000** [0.000, 0.000] | **0/3** | never | 0 | 0 | **32.75 s (100%)** | *15.95 (15.95)* |
| `A.static__p25` | 0.70 | **0.000** [0.000, 0.000] | **0/3** | never | 0 | 0 | **31.38 s (100%)** | *15.95 (15.95)* |
| `A.static__p25` | 0.75 | **0.000** [0.000, 0.000] | **0/3** | never | 0 | 0 | **32.27 s (100%)** | *15.95 (15.95)* |
| `B.moving__control` | 0.70 | **0.992** [0.991, 0.992] | 3/3 | 0.31 s | 0 | 0 | 0.16 s | 3.32 (9.17) |
| `B.moving__control` | 0.75 | **0.991** [0.975, 0.992] | 3/3 | 0.32 s | 0 | 0 | 0.16 s | 3.29 (10.57) |
| `B.moving__median` | **0.70** | **0.013** [0.013, 0.038] | **3/3** | **8.50 s** | 4 | 1 | 37.05 s (98%) | 15.14 (**30.73**) |
| `B.moving__median` | **0.75** | **0.000** [0.000, 0.052] | **1/3** | 25.13 s | 2 | 1 | 36.09 s (98%) | 14.11 (21.78) |
| `B.moving__p25` | 0.70 | **0.000** [0.000, 0.000] | **0/3** | never | 0 | 0 | **35.69 s (100%)** | *14.08 (21.78)* |
| `B.moving__p25` | 0.75 | **0.000** [0.000, 0.000] | **0/3** | never | 0 | 0 | **37.21 s (100%)** | *14.26 (21.78)* |

*Italic heading entries are not performance numbers.* With no latch the drone
never yaws and never advances, so "heading error" is the constant bearing to the
person it is ignoring. 15.95 deg (static) and 21.78 deg (moving max) are the
**passive** values.

**Read the `B.moving__median` heading row carefully, because it is the one place
0.70 changes behaviour and it changes it for the worse.** At 0.75 the max is
21.78 deg on all three flights - the passive value. At 0.70 it is 25.29, 24.50
and 30.73 deg. The extra latches make the drone yaw toward a detection it then
drops, and it ends up pointed *further* from the person than if it had never
latched at all.

### 4.2 THE ENTRY-GATE MARGIN - run-length distributions, not just the maximum

The follower needs three consecutive frames at or above the bar. A cell with a
longest run of 2 and one with 0 both read 0.000 tracking and are **not** the same
situation. Full distributions, per flight, at the bar that flight actually flew:

| flight | frames >= bar | **run-length histogram** | longest | latched |
|---|---|---|---|---|
| `e0.70__A.static__median__r1a1` | 0 | *(none)* | **0** | no |
| `e0.70__A.static__median__r2a1` | 0 | *(none)* | **0** | no |
| `e0.70__A.static__median__r3a2` | 0 | *(none)* | **0** | no |
| `e0.75__A.static__median__r1a1` | 0 | *(none)* | **0** | no |
| `e0.75__A.static__median__r2a1` | 0 | *(none)* | **0** | no |
| `e0.75__A.static__median__r3a1` | 0 | *(none)* | **0** | no |
| `e0.70__A.static__p25__r1a1` | 0 | *(none)* | **0** | no |
| `e0.70__A.static__p25__r2a1` | 0 | *(none)* | **0** | no |
| `e0.70__A.static__p25__r3a1` | 0 | *(none)* | **0** | no |
| `e0.75__A.static__p25__r1a1` | 0 | *(none)* | **0** | no |
| `e0.75__A.static__p25__r2a1` | 0 | *(none)* | **0** | no |
| `e0.75__A.static__p25__r3a1` | 0 | *(none)* | **0** | no |
| `e0.70__B.moving__p25__r1a1` | 0 | *(none)* | **0** | no |
| `e0.70__B.moving__p25__r2a1` | 0 | *(none)* | **0** | no |
| `e0.70__B.moving__p25__r3a1` | 0 | *(none)* | **0** | no |
| `e0.75__B.moving__p25__r1a1` | 0 | *(none)* | **0** | no |
| `e0.75__B.moving__p25__r2a1` | 0 | *(none)* | **0** | no |
| `e0.75__B.moving__p25__r3a1` | 0 | *(none)* | **0** | no |
| **`e0.70__B.moving__median__r1a1`** | 30 | `1x19  2x4  3x1` | **3** | **yes, 8.50 s** |
| **`e0.70__B.moving__median__r2a1`** | 30 | `1x20  2x1  3x1  5x1` | **5** | **yes, 7.83 s** |
| **`e0.70__B.moving__median__r3a1`** | 27 | `1x18  2x3  3x1` | **3** | **yes, 13.51 s** |
| **`e0.75__B.moving__median__r1a1`** | 16 | `1x14  2x1` | **2** | **no** |
| **`e0.75__B.moving__median__r2a1`** | 27 | `1x21  3x2` | **3** | **yes, 25.13 s** |
| **`e0.75__B.moving__median__r3a1`** | 16 | `1x14  2x1` | **2** | **no** |
| `e0.70__A.static__control__r1a1` | 185 | `1x6 2x2 4x2 5x1 9x1 18x1 35x1 100x1` | **100** | yes, 0.31 s |
| `e0.75__A.static__control__r2a1` | 180 | `1x3 2x1 4x2 7x1 17x1 143x1` | **143** | yes, 0.31 s |
| `e0.70__B.moving__control__r1a1` | 223 | `... 21x1 25x1 84x1` | **84** | yes, 0.31 s |
| `e0.75__B.moving__control__r1a1` | 224 | `... 19x1 46x1 94x1` | **94** | yes, 0.94 s |

*(the remaining control flights are in `tables/per_flight.tsv`; all six have
longest runs of 67-143)*

**The three shapes, and they are qualitatively different situations:**

1. **Nothing at all** (both static cells, moving p25, both arms): **zero** frames
   above either bar. There is no histogram. These are not near-misses - the
   whole trace lives 0.15 to 0.43 below the bar.
2. **Scattered but never three in a row** (`B.moving__median` at 0.75, r1 and
   r3): **16 frames above the bar and a longest run of 2.** Sixteen good frames
   buy nothing if no three of them are adjacent. These are the near-misses.
3. **Just barely three in a row** (`B.moving__median` at 0.70, all three, and at
   0.75, r2): runs of exactly 3 (twice), 5 (once) and 3 (once), out of 27-30
   above-bar frames.

Lowering the bar to 0.70 raises the above-bar frame count in that cell, paired
by repeat (0.75 -> 0.70): **r1 16 -> 30, r2 27 -> 30, r3 16 -> 27**, and that is
enough to push the longest run from 2 to 3 in r1 and r3. **That is the entire
mechanism of the effect.** Note r2 already had a run of 3 at 0.75 and latched
there, so the extra frames bought it nothing.

### 4.3 The rule replicates

`scripts/analyze_enter.py` checks it across all **36** flights:

```
THE RULE: a flight latches if and only if its longest above-bar run reaches confirm_frames (3).
  checked 36 flights: HOLDS on all of them
```

### 4.4 What the extra latches actually buy

The `B.moving__median` cell is the only place the bar changes anything, so it is
worth saying precisely what changes. Latch segments, as `(start s, duration s,
frames)`:

| flight | M1 | segments | **total time actually tracking** |
|---|---|---|---|
| `e0.70__B.moving__median__r1a1` | 0.013 | `(8.50, 0.32, 3)` | **0.47 s** of 37.5 s |
| `e0.70__B.moving__median__r2a1` | 0.038 | `(7.83, 0.78, 6)`, `(32.32, 0.32, 3)` | **1.41 s** of 36.9 s |
| `e0.70__B.moving__median__r3a1` | 0.013 | `(13.51, 0.32, 3)` | **0.48 s** of 37.5 s |
| `e0.75__B.moving__median__r1a1` | 0.000 | *(none)* | **0.00 s** of 37.2 s |
| `e0.75__B.moving__median__r2a1` | 0.052 | `(25.13, 0.64, 5)`, `(26.55, 0.94, 7)` | **1.90 s** of 35.8 s |
| `e0.75__B.moving__median__r3a1` | 0.000 | *(none)* | **0.00 s** of 36.1 s |

**Arm totals: 2.36 s tracked out of 111.9 s flown at 0.70 (2.1%), against 1.90 s
out of 109.1 s at 0.75 (1.7%).** Half a second of extra tracking across nearly
two minutes of flying. The drone latches for three to seven frames, yaws, drops
below the 0.45 exit bar, and does not get the track back.

**So the answer to "does 0.70 acquire where 0.75 does not" is yes for the entry
gate and no for the mission.** The `M1` medians differ by 0.013; the single
best flight in the whole cell is a **0.75** flight (0.052).

### 4.5 Statistics, stated so nobody has to guess

Three repeats per arm cannot carry a latch-count claim on their own:

| cell | 0.70 | 0.75 | Fisher exact (two-sided) |
|---|---|---|---|
| `B.moving__median` | 3/3 | 1/3 | **p = 0.400** |
| `B.moving__median`, 0.75 pooled with last night's three flights | 3/3 | 2/6 | **p = 0.167** |
| all three other typical cells | 0/3 | 0/3 | p = 1.000 |

Neither reaches significance. **The mechanistic evidence is much stronger than
the count**, and it is what the conclusion rests on: `b*` is 0.744, 0.748 and
0.751 on the three 0.75 flights - all three within 0.006 of the shipped bar -
while the same subject's b* sits at or above 0.702 on all three 0.70 flights.
The bar was moved across this subject's acquisition threshold. That is a
statement about where a number sits on a measured distribution, not a
difference of proportions.

**And the knife edge cuts both ways:** `e0.70__B.moving__median__r3a1` has
b* = 0.702. That flight latched with **0.002** to spare. This cell is marginal
at *both* bars and would be expected to flip flights on re-running - which is
exactly what comparing to last night shows (last night's 0.75 flights latched
r3; tonight's latched r2).

---

## 5. What the team should take to the lab

1. **The shipped 0.75 has a real acquisition cost that was invisible on the easy
   subject, and it is confined to subjects whose b* lands in 0.70-0.75.** One of
   our two ordinary-person subjects, on one of two scenes, is such a subject.
   That is a genuine finding and the team should know it before the lab.
2. **Reverting to 0.70 would not buy a working follower.** It converts 0.000
   tracking into 0.013. In three of four ordinary-person cells it changes
   nothing whatsoever. Anyone proposing the revert as a fix for last night's
   collapse should see §4.4 first.
3. **For two of the four cells the entry bar cannot be the fix at any value**,
   because b* (0.318-0.368) is below the 0.45 **exit** bar. A bar low enough to
   acquire them would be below the bar that decides when to let go.
4. **A momentary latch is worse than none for pointing.** §4.1: heading max goes
   from a passive 21.78 deg to 30.73 deg. If the lab protocol scores pointing,
   a half-second latch will make the number worse, not better.
5. **Report the entry-gate margin as b*, not just as a run length.** "Longest run
   was 2" does not tell you whether the bar was 0.006 away or 0.43 away. b*
   does, in the units of the knob, and it costs one pass over the trace
   (`scripts/margin_threshold.py`).
6. **The scoreboard still does not fail a cell for not tracking on the himax
   camera** (`M1_tracking_fraction` is provisional there). Unchanged from last
   night, and still worth a decision before the session.

---

## 6. What this does NOT establish

* **Nothing about hardware.** No frame here came from a camera. No GAP8, no
  firmware, no UDP. This is CrazySim + `himax_typical` + `model_id_dory.onnx`
  under onnxruntime. **The firmware and contract still ship 0.75 and nothing
  here was changed.**
* **These are rendered flat cutouts.** Every subject is an opaque rectangle with
  a photograph on it: no parallax, no limb articulation, no change of appearance
  when the person turns. Every flight result in this repo carries that limit.
* **A rendered median person is harder than a real one.** The fidelity study
  measured the renderer pulling scores down, and last night's audit narrowed
  that to a well-supported *direction* with an *unestablished magnitude* for the
  `wui` stratum both picks come from (himax-vs-himax paired median **-0.0496
  [-0.1132, +0.0178]**, a CI crossing zero, n=59). So these cells bracket the
  real answer from the pessimistic side **as a sign, not a size**. A real median
  person might have a b* above 0.75, in which case the shipped bar costs nothing
  for them; or between 0.70 and 0.75, in which case it costs them acquisition.
  **This experiment cannot tell you which, and the difference is the whole
  question.**
* **Two subjects, not a distribution.** Three repeats bound machine noise, not
  person-to-person spread. Last night's cohort table is the distribution: at the
  static start range 74/267 subjects clear 0.75 on a static on-axis frame, and
  at the moving start 48/267 - so roughly a fifth to a quarter of the cohort
  clears the bar, and 0.00 is not the population's number any more than 0.99 is.
* **This is one start geometry, deliberately unchanged.** s15 starts the drone
  3.64 m out on a 15.9 deg bearing; s01 starts it 3.0 m out on axis. The
  follower only closes distance while latched, so a subject that cannot clear
  the bar at the start range never gets the closer, easier view - the failure is
  self-sealing. A scene that started closer would give a different answer, and
  last night's §4.5 probe says the median subject clears 0.75 only inside about
  1 m even on the float model with a clean camera.
* **The 0.70 arm's b* is contaminated after its first latch.** Once the follower
  latches the drone moves, so the trace it then sees is a consequence of the
  arm. b* is reported whole-trace and pre-latch (`tables/margin_threshold.txt`);
  the pre-latch column is the comparable one, and the §2 band quotes the 0.75
  arm's values for that reason.
* **`B.moving__median` is marginal at both bars and will flip flights on
  re-running.** It did between last night and tonight. Do not read "3/3 vs 1/3"
  as a stable ratio; read b* = 0.744-0.751 against a bar of 0.75.
* **Nothing here was committed or pushed**, and no existing scene definition,
  `docs/sim_results/`, or earlier `docs/eval_results/` directory was touched.

---

## 7. Housekeeping

* **Tool hashes pinned before the first flight and after the last,
  `code_hashes_before.txt` / `code_hashes_after.txt`, identical, diff clean**,
  and identical to the five in last night's `code_hashes_after.txt`:

```
ea639fea...  tools/crazysim_macos/build_scene.py
481c0a99...  tools/crazysim_macos/camera_model.py
8281df9f...  tools/crazysim_macos/follow_person.py
ce917647...  tools/crazysim_macos/perception_backends.py
e0d7cbe5...  tools/crazysim_macos/scoreboard.py
```

* **All 22 `tools/crazysim_macos/scene_defs/*.json` hash identically before and
  after.** No scene definition was created, edited or rebuilt.
* **Every flight records the sha256 of the `scene.xml` it loaded**
  (`runs/*/scene_xml_sha256.txt`), and all 36 match the artefacts last night
  built:

```
s01_control_moving  ad1caece08d55feb...   tp01_moving_median  34ac32aadb981f3c...
s15_static_offset   8e597e6ae29b0886...   tp01_moving_p25     d1cae90e2d1efb21...
                                          tp15_static_median  f1106a68b91b0428...
                                          tp15_static_p25     2a75dbbaac1a4021...
```

  The two control hashes are the ones last night verified byte-identical to the
  published `scenes_v2/` artefacts.

* **`scripts/verify_run.py` is the gate, and it exits non-zero if anything
  fails.** It passed: 36/36 flights carry the `vis_enter` their plan row asked
  for *as recorded by `follow_person.py` in its own `summary.json`*, with
  `vis_exit` 0.45 and `confirm_frames` 3; 36/36 scene hashes match; all 13 setup
  fields and all 7 camera-identity fields are identical between the two arms of
  every pair. Output in `tables/verify_run.txt`. **No flight was scored whose
  recorded threshold did not match its plan row** - none needed to be excluded.
* **Flight record: 38 attempts, 36 scored, 2 re-flies.** Attempt 1 of
  `e0.70__A.static__median` r3 and of `e0.70__A.static__control` r3 each hit the
  runner's inherited `perl alarm` watchdog at `duration + 90` s with an empty
  `follower.log` and no `summary.json` (the simulator started and reported
  "firmware connected"; the follower then produced nothing). The harness's own
  one-re-fly rule flew each again and `__r3a2` is VALID in both cases and is the
  flight scored. Both failed attempts are kept in `runs/`, appear in
  `flights.jsonl` with verdict `NORUN`, and are excluded by `scoreboard.py`'s own
  validity filter. Last night had the same failure once.
* **Per-arm scoring.** `scoreboard.py` groups by `cell_id`, and both arms share
  one, so scoring in a single pass would average the arms together. As in
  `2026-09-14-exit-bar`, each arm has its own directory whose `runs/` are
  **symlinks** into the real `runs/` (`scripts/score_arms.sh`). Nothing is
  copied and nothing moves.
* **`*.log` files need `git add -f`** - `.gitignore` has both `logs/` and
  `*.log`. There are **86**: `logs/*.log` (7), `progress.log`, and
  `runs/*/follower.log` + `runs/*/sim.log` (76), plus
  `scoreboards/arm_*/scoreboard_stdout.log` (2). Following the repo's documented
  policy and last night's precedent, **`cache/` and `snap_*.png` are left
  ignored** (351 files) - the gitignore comment records that a blanket
  `git add -f` swept 96 cache files and 330 snapshots into a results commit on
  2026-09-12. Directory is 31 MB with them, far less without.

### Layout

```
README.md                     this file
plan_block1.tsv               the 24 typical-person flights, interleaved
plan_block2.tsv               the 12 control flights
flights.jsonl                 one record per attempt, including the 2 NORUNs
progress.log                  runner log
harness_cmd.txt               the exact command
machine_before.txt / _after.txt
code_hashes_before.txt / _after.txt
runs/e{0.70,0.75}__<cell>__r<rep>a<att>/     38 run dirs
scoreboards/arm_0.70/, arm_0.75/             per-arm scoreboard.json + .md
scripts/  fly_plan_enter.sh, make_plan.py, score_arms.sh,
          analyze_enter.py, margin_threshold.py, verify_run.py
tables/   per_cell_arm.tsv, per_flight.tsv, analysis.txt,
          margin_threshold.txt, verify_run.txt
logs/     harness + script stdout
```
