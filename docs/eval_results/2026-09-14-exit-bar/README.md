# Does letting go sooner close the pet gate? `--vis-exit` at 0.45 / 0.55 / 0.65, enter bar fixed at 0.75

Session: 2026-09-14 evening (lock taken 20:05:26Z, first flight 20:08:05Z), repo `pytorch_ssd` at `9d1026c` (clean),
no hardware - the chip network runs under onnxruntime. Written progressively under a 38-minute flying budget;
every number below is pasted from files in this folder.

Read first: `docs/eval_results/2026-09-14-pets-variance/README.md`. Short version of the question it left open:
at the shipped `--vis-enter 0.75`, `F.pets__ships` passes its M6 < 0.5 m drift gate 11 times in 16 (0.688,
CP95 [0.413, 0.890]). Every flight latches onto the dog within 0.8-2.7 s at 0.76-0.83 confidence and nothing
before the latch separates passes from failures; what separates them is whether the latch PERSISTS (latched
time median 2.18 s in failures vs 0.62 s in passes, p = 0.004). The latch is released by the EXIT threshold,
`--vis-exit`, default 0.45, which no sweep has ever moved. This folder moves it.

## 1. How the exit bar was set, and how each flight was confirmed

**`run_acceptance2.sh` cannot pass it.** `grep -n 'vis_exit\|vis-exit' tools/crazysim_macos/run_acceptance2.sh`
returns nothing. The harness builds its follower argument list at line 218 as

```
perl -e 'alarm shift; exec @ARGV' $((dur + 90)) "$P" follow_person.py "${args[@]}"
#   args = --duration <dur> --out <run> [--backend chip] [--rate-hz 6.5 --latency-ms 153]
```

and nothing else, so `follow_person.py` always takes its own defaults (`--vis-enter 0.75`, `--confirm-frames 3`,
`--vis-exit 0.45`, lines 245-247). **Route taken: a per-flight plan-runner**, `scripts/fly_plan_exit.sh`,
following the pattern of `docs/eval_results/2026-09-13-champion-vs-confuser/scripts/fly_plan_models.sh`. Its
`fly()` body is a faithful copy of the harness's own `fly()` - same `cell.json`, same
`run_sim_headless.sh --camera --scene`, same "firmware connected" wait, same `CRAZYSIM_*` environment, same
`perl alarm` wrapper, same teardown - with exactly two changes earlier agents in this repo also made (order
comes from a plan file so arms can be interleaved; load average sampled either side of every flight) plus the
one this experiment needs:

```
args+=(--vis-enter 0.75 --confirm-frames 3 --vis-exit "$vexit")
```

`--vis-enter` and `--confirm-frames` are passed **explicitly at their default values** in all three arms, so the
enter bar is pinned on the command line rather than inherited and the three arms are built identically. For the
0.45 control arm this command line is behaviourally identical to the harness's (it passes exactly what the
defaults would give). Each run's verbatim follower command line is in `runs/*/follow_cmd.txt`.
Nothing under `tools/` was edited; nothing under `docs/` from earlier sessions was touched; nothing was
committed or pushed.

**Per-flight confirmation, and it gates validity.** `follow_person.py` writes `vis_enter` / `vis_exit` /
`confirm_frames` into `summary.json` (line 488). The runner re-reads them after every flight and refuses to
call it VALID unless all three are the ones that row asked for (`runs/*/thresh_check.txt`); a flight that ran
the wrong threshold is not a valid flight however clean its dynamics were. The full audit table is in
`flight_records.md` under "Threshold audit". **Result: every flight recorded `vis_enter 0.75`,
`confirm_frames 3`, and its intended `vis_exit`. No flight recorded anything else.**

**Floor asserted per flight, two ways, before the sim starts**: the `reflectance` attribute of the `scene.xml`
about to be flown and `room.floor_reflectance` in that scene's `manifest.json`. A mismatch aborts the flight
rather than being flown and explained away later. Both values are written into every run directory
(`runs/*/floor_reflectance.txt`, `runs/*/floor_manifest.txt`); **all are 0.0, matte, on both scenes.**

**Seeds.** The harness's own rule, `CRAZYSIM_SENSOR_SEED = 1000 + repeat`, unchanged. Each arm flies repeats
1-6, so **all three arms see the same six himax noise draws (seeds 1001-1006)** - the arms are matched on camera
noise, and a seed-paired comparison is possible.

## 2. Arms and scenes

| arm | vis_enter | confirm_frames | vis_exit | note |
|---|---|---|---|---|
| control | 0.75 | 3 | **0.45** | today's shipped value |
| mid | 0.75 | 3 | **0.55** | |
| high | 0.75 | 3 | **0.65** | |

* Pets cell `F.pets__ships`, exactly the CORE matrix row (`s03_pets_only`, class F, chip backend,
  `himax_typical`, chip speed 6.5 Hz / 153 ms, 35 s). Scene `scene.xml` sha256
  `40dd318c25ac7942afeee84bca1e1f919a05e389e0532c6d38596237699234f7` - identical to the hash recorded in both
  `pets-variance/scene_hashes_before.txt` and `baseline-075/scene_hashes_before.txt`, so this is the same scene
  those sessions flew.
* Person cell `B.moving__ships`, the CORE row (`s01_control_moving`, class B, chip, `himax_typical`, chip
  speed, 50 s). Scene sha256 `ad1caece08d55feb52a1c5fa7f317ebb4ba343f2e5e06a46225337025d9cec76`, also
  identical to the earlier sessions'. (`scene_hashes_before.txt`.)

## 3. Interleaving actually achieved

`scripts/make_plan.py` -> `plan.tsv`, balance in `plan_balance.json`. Round-robin in the literal order
0.45, 0.55, 0.65, 0.45, ... The repeat index (and therefore the seed) is permuted per arm so repeat number is
decorrelated from chronological position.

| arm | pets flight orders | repeats in that order | seeds | mean order | Spearman(order, repeat) |
|---|---|---|---|---|---|
| 0.45 | 1, 4, 7, 10, 13, 16, 25 | 3, 6, 1, 4, 2, 5, 7 | 1003,1006,1001,1004,1002,1005,1007 | 10.86 | +0.393 |
| 0.55 | 2, 5, 8, 11, 14, 17, 26 | 5, 2, 4, 6, 3, 1, 7 | 1005,1002,1004,1006,1003,1001,1007 | 11.86 | +0.107 |
| 0.65 | 3, 6, 9, 12, 15, 18, 27 | 1, 4, 6, 2, 5, 3, 7 | 1001,1004,1006,1002,1005,1003,1007 | 12.86 | +0.536 |

All seven pets repeats per arm are included above, the r7 block (orders 25-27) included; over the first six
blocks alone the means are 8.5 / 9.5 / 10.5 and the rank correlations +0.029 / -0.429 / +0.257.
Mean flown position differs by exactly one flight between adjacent arms (10.86 / 11.86 / 12.86) - the minimum
possible under a strict round robin, so no arm sits systematically early or late in the session. Rank
correlation between repeat index and chronological position is |rho| <= 0.54 (it cannot be 0 for every arm with
7 points; the control arm is +0.39). The r7 block was flown last, after the two person blocks, and it is the
same repeat/seed in all three arms, so it adds no between-arm order bias.

## 4. What flew

27 flights, **all VALID on the first attempt** (no re-flies). Flying ran 20:08:05Z to 20:33:22Z, 25 min
of the 38-minute budget and inside the 33-minute stop: 52 s per pets flight, 67 s per person flight,
1484 s of flight wall clock in total. Per-flight records:
`flights.jsonl` (written by the runner as each flight lands), `flight_records.jsonl` / `flight_records.md`
(written by `scripts/analyze_exit.py`), `paired.md` / `paired.json` (`scripts/paired.py`).

* 18 + 3 pets flights: `F.pets__ships`, 6 (then 7) repeats per arm, interleaved as in section 3.
* 6 person flights: `B.moving__ships`, 2 repeats per arm, interleaved 0.45, 0.55, 0.65, 0.45, 0.55, 0.65.

**Health, all 27 flights** (recomputed from `flight_records.jsonl`): sim_wall_ratio 0.981-0.998; processed
6.323-6.432 Hz against 6.5 requested; `step_gap_ms.max` 158.8-217.6 ms against the ~158 ms chip-class floor
(one person flight at 0.65, seed 1001, reached 217.6 ms - the only value above 170 ms in the session, and that
flight is still VALID and PASS); **0 attitude upsets** - 0 frames with |pitch| or |roll| above 30 deg and 0
frames below the 0.25 m flight floor, across every flight (worst |roll| 0.63 deg, worst |pitch| 7.95 deg, both
normal forward flight); 0 stale events; 0 torn frames; every flight landed. Load average while flying 3.59-6.29
(the machine carried a ~3.4-4.0 background load before the session, `machine_before.txt`). Per-flight values
are in the detail table in `flight_records.md`.

## 5. The answer, plainly

**Raising the exit bar does NOT close the pet gate.** All three arms FAIL `M6_max_horizontal_drift_m` when
scored by the repo's own `scoreboard.py` (`scoreboards/arm_0.45/`, `arm_0.55/`, `arm_0.65/`; worst repeat
0.998 / 0.691 / 0.682 m against the < 0.5 m gate). The pass rate is nominally best at 0.55 (4 of 7 vs 2 of 7
for the control), but **at 7 repeats the Clopper-Pearson intervals overlap almost completely and the
difference is not callable** - and this session's own control arm came in far below the 16-flight 0.45
baseline flown three hours earlier on the same scene with the same seeds, which is the single most important
thing on this page (section 7). **The mechanism does respond exactly as predicted** - the drone lets go
sooner and latched time falls - **but that does not carry the drift under the gate.**

### Pets, `F.pets__ships`, 7 repeats per arm

Full table in `flight_records.md`, seed-paired version in `paired.md`. M6 recomputed by
`scripts/analyze_exit.py` with the scorer's own rule (max horizontal displacement from the first flown row,
rows with `event == ""`); the per-run `metrics.json` written by `scoreboard.py` agrees on every flight.

| arm | M6 drifts in flown order (m) | under 0.5 m | rate | **CP 95%** | median | worst | scorer verdict |
|---|---|---|---|---|---|---|---|
| **0.45** (control) | 0.540, 0.347, 0.560, 0.397, 0.813, 0.814, 0.998 | **2/7** | 0.286 | **[0.037, 0.710]** | 0.560 | 0.998 | **FAIL** |
| **0.55** | 0.529, 0.620, 0.691, 0.323, 0.271, 0.447, 0.382 | **4/7** | 0.571 | **[0.184, 0.901]** | 0.447 | 0.691 | **FAIL** |
| **0.65** | 0.618, 0.452, 0.588, 0.502, 0.425, 0.276, 0.682 | **3/7** | 0.429 | **[0.099, 0.816]** | 0.502 | 0.682 | **FAIL** |

Every interval spans more than half the unit interval and every pair of intervals overlaps over most of its
length. 2/7 vs 4/7 is one flight either side of noise.

### The latch, and what releases it

| arm | latched s, median [min-max] | episodes, median | t to first latch s, median | conf at first latch | **release confidence**, median [min-max] |
|---|---|---|---|---|---|
| 0.45 | 1.25 [0.47-3.31] | 3 | 0.94 | 0.77-0.79 | **0.399** [0.237-0.447] |
| 0.55 | 0.79 [0.15-1.89] | 2 | 1.25 | 0.77-0.79 | **0.454** [0.308-0.532] |
| 0.65 | 0.78 [0.31-1.41] | 3 | 1.26 | 0.77-0.79 | **0.548** [0.427-0.640] |

Three things this confirms:

1. **The knob does what it says.** Release confidence - the confidence on the first frame after a track drops -
   rises with the bar, 0.399 -> 0.454 -> 0.548, each sitting just under its own threshold. The drone really is
   letting go sooner and at a higher confidence.
2. **Latched time falls, as the mechanism predicted.** Median 1.25 -> 0.79 -> 0.78 s. Paired on seed
   (`paired.md`): 0.55 is lower in 4 of 7 seeds (median -0.77 s), 0.65 in 5 of 7 (median -0.94 s).
3. **The latch itself is untouched.** Time to first latch (0.94-1.26 s) and the confidence at which the dog is
   first acquired (0.77-0.79) are the same in all three arms - as they must be, since the enter bar never moved.
   This reproduces the earlier session's finding on fresh flights.

### Seed-paired, the comparison with the camera noise removed

All three arms flew seeds 1001-1007, so each seed gives a matched triple.

| comparison | per-seed delta M6 (m) | median | seeds improved | Wilcoxon p |
|---|---|---|---|---|
| 0.55 - 0.45 | -0.113, -0.193, -0.269, **+0.294**, -0.285, -0.024, -0.616 | **-0.193** | **6/7** | 0.219 |
| 0.65 - 0.45 | **+0.058**, -0.311, -0.264, **+0.055**, -0.389, **+0.241**, -0.316 | **-0.264** | 4/7 | 0.219 |

This is the strongest thing in the session's favour: at 0.55 the drift is lower on 6 of 7 matched seeds and the
worst case drops from 0.998 m to 0.691 m. It is still **not significant** - with 7 pairs the smallest p the
Wilcoxon test can return is 0.016, and 0.219 is nowhere near it - and it does not put any flight's worst case
under the gate.

**Where 0.65 goes wrong, visibly: chatter.** On seeds 1001 and 1006 raising the bar to 0.65 took the episode
count from 2 to 6 and 2 to 5, and on exactly those seeds the drift got *worse* (0.560 -> 0.618, 0.347 -> 0.588).
Seed 1007 is the clearest: 7 episodes at 0.65. Dropping the dog sooner does not help if the drone immediately
re-acquires it - the enter bar is still 0.75, so each re-latch costs another confirm-and-chase cycle. That is the
predicted failure mode for this knob and it is already visible at 0.65 in the pet scene, before any person is
involved.

## 6. What it costs on people - `B.moving__ships`, 2 repeats per arm

Full table in `person.md` / `person.json`. Heading error and distance come from the repo's own
`scoreboard.py` (`runs/*/metrics.json`), not from a reimplementation. This is the clearest signal of the
session, and it is monotone.

| arm | tracking fraction (per flight) | mean | track losses | re-acquisitions | **time lost to drops (s)** | hdg err mean / max deg | settled dist err m | final in band |
|---|---|---|---|---|---|---|---|---|
| **0.45** | 0.9920, 0.9910 | **0.9915** | **0** | **0** | **0.00** | 3.38 / 9.14 | 0.538 | 2/2 |
| **0.55** | 0.9150, 0.9660 | **0.9405** | **2** | **2** | **4.09** | 3.26 / 8.55 | 0.554 | 2/2 |
| **0.65** | 0.9510, 0.7760 | **0.8635** | **6** | **5** | **10.06** | 3.78 / 9.65 | 0.567 | 2/2 |

**The cost is real and it rises steeply.** At the shipped 0.45 the drone holds the walking person in a single
unbroken track for the whole 50 s flight, twice, with zero drops. At 0.55 it drops him once per flight. At 0.65
it drops him three times per flight and loses 10 s of tracking across two flights - one flight
(seed 1002) tracked only 77.6% of its duration, and its 8.16 s of lost time includes a tail it never recovered.

**What it does not cost: pointing and distance.** Heading error while tracking is flat across the arms
(mean 3.3-3.8 deg, max 8.5-9.7 deg, all inside the M2 gates) and station-keeping is unchanged (settled distance
error 0.538-0.567 m, final distance in band in 6 of 6 flights). So the damage is confined to *holding* the
track, which is exactly the knob's job; when the drone has the person, it flies him just as well.

**Read the PASS verdicts carefully.** `scoreboard.py` marks `B.moving__ships` PASS in all three arms, including
0.65. That is not evidence of no cost: on the `himax_typical` camera `M1_tracking_fraction` is **provisional /
measured-only, not gated** (`scoreboard.py` lines 707-716 give only the literal `himax_typical` preset the
relaxed report-only thresholds). The 0.65 arm's median tracking fraction, 0.8635, is **below its own provisional
threshold of 0.9**, and the arm's scoreboard says so in its "Provisional numbers observed" table. The gated
bar this cell would otherwise face is M1 >= 0.93 (`scoreboard.py` line 703: 0.95 relaxed by 0.02 for chip
speed, and this cell's speed is `chip`), and under it the 0.65 arm would fail while the 0.55 arm (0.9405)
would still pass. The PASS is an artefact of which
thresholds are currently armed, not a finding that people are unaffected.

With 2 repeats per arm the *magnitude* of the cost is uncertain (0.65's two flights are 0.951 and 0.776, a wide
spread). The *direction* is not: losses go 0, 2, 6 and time lost 0.00, 4.09, 10.06 s with no overlap between arms.

## 7. The thing that most limits this session: the control arm moved

| session | arm | n | pass | rate | CP 95% | median M6 | worst M6 |
|---|---|---|---|---|---|---|---|
| **pets-variance** (Sep 14 **afternoon**, 17:51-18:05Z) | 0.45 | 16 | 11 | 0.688 | [0.413, 0.890] | 0.362 | 1.188 |
| **exit-bar** (Sep 14 **evening**, this folder, 20:08-20:33Z) | 0.45 | 7 | 2 | **0.286** | [0.037, 0.710] | 0.560 | 0.998 |
| exit-bar (this folder) | 0.55 | 7 | 4 | 0.571 | [0.184, 0.901] | 0.447 | 0.691 |
| exit-bar (this folder) | 0.65 | 7 | 3 | 0.429 | [0.099, 0.816] | 0.502 | 0.682 |

The control arm is **the same configuration as the afternoon baseline in every respect this repo records** -
same scene (`scene.xml` sha256 `40dd318c25ac...`, asserted identical), same matte floor, same cell, same
`vis_enter 0.75 / vis_exit 0.45 / confirm_frames 3`, same chip backend, same camera preset, same seed rule. On
the six shared seeds 1001-1006 the afternoon run got 0.188, 0.348, 0.231, 0.409, 0.684, 0.613 (4 of 6 under the
gate); this evening the same six seeds gave 0.560, 0.813, 0.540, 0.397, 0.814, 0.347 (2 of 6). Mann-Whitney on
the two sets of control drifts: **p = 0.089** (7 vs 16 flights) - not significant, but the point estimate
halved.

**So the sensor seed does not pin the outcome even when nothing else changes**, which the afternoon session
suspected and this session demonstrates directly by re-flying its exact configuration and its exact seeds.
Whatever varies between sessions (the afternoon README's unmeasured frame-arrival phase against the 6.5 Hz
limiter is the standing hypothesis; this session did not measure it either) is comparable in size to the effect
being hunted. That is why the within-session paired comparison in section 5 is the one to trust, and why a
6-or-7-repeat arm cannot settle this question.

## 8. Verdict

* **Does raising the exit bar close the pet gate? No.** 0.55 and 0.65 both still FAIL `M6 < 0.5 m`, with worst
  repeats of 0.691 m and 0.682 m. Neither is close.
* **Is there an improvement worth chasing? Possibly, at 0.55, and it is not callable at this sample size.**
  Nominal pass rate 4/7 vs 2/7, CP95 [0.184, 0.901] vs [0.037, 0.710] - overlapping over most of their length;
  paired on seed, 6 of 7 seeds improved with median -0.193 m, Wilcoxon p = 0.219; worst case 0.998 -> 0.691 m.
  **The interval is too wide to call at 7 repeats. This is not a winner; it is a direction.**
* **0.65 is worse than 0.55 on the pets and much worse on people.** More pet drift than 0.55 (3/7 vs 4/7,
  median 0.502 vs 0.447), visible re-latch chatter, and a person-tracking fraction of 0.8635 that breaches even
  its own provisional bar.
* **The fix is not free.** The brief's premise was that moving this knob costs nothing. It costs the person
  track: 0 drops at 0.45, 2 at 0.55, 6 at 0.65 across matched flights, 0 -> 4.09 -> 10.06 s of tracking lost.
* **The mechanism the afternoon session identified is confirmed and is not sufficient.** The exit bar does
  shorten latches (release confidence 0.399 -> 0.454 -> 0.548, latched time 1.25 -> 0.79 -> 0.78 s), and the
  drift still does not clear the gate. Shortening the latch is not the same as preventing the chase.

**Recommendation.** Do not ship a change to `--vis-exit` on this evidence. If the exit bar is pursued, the next
run should be **0.45 vs 0.55 only, both arms in the same session, 20+ repeats each** (at ~52 s per flight that
is ~35 min for 40 flights), because section 7 shows a between-session shift as large as the effect, and
sections 5-6 show 0.65 is already paying a person cost without buying pet performance. A knob that cannot close
the gate on its own may still be worth combining with the enter bar, but that is a two-factor experiment nobody
has run.

## 9. Housekeeping

* **Tool hashes pinned before the first flight and after the last**, five files as the brief required:
  `code_hashes_before.txt`, `code_hashes_after.txt` - **identical, diff clean** (verified below). Nothing under
  `tools/` was edited.
* Scene hashes asserted before flying (`scene_hashes_before.txt`): `s03_pets_only/scene.xml`
  `40dd318c25ac7942afeee84bca1e1f919a05e389e0532c6d38596237699234f7`, `s01_control_moving/scene.xml`
  `ad1caece08d55feb52a1c5fa7f317ebb4ba343f2e5e06a46225337025d9cec76` - both identical to the hashes recorded in
  the afternoon and morning sessions.
* Matte floor confirmed per flight from the manifest AND the scene.xml, before the sim started, all 27 flights:
  `runs/*/floor_reflectance.txt` and `runs/*/floor_manifest.txt`, all `0.0`.
* Nothing under `docs/` from earlier sessions was modified. Nothing was committed or pushed.
* Locks: the workstream lock `sim.lock` was taken at 20:05:26Z and released at the end; the per-flight lock
  `sim_exit.lock` (a different path, so it cannot deadlock against the workstream lock) was taken and dropped
  around every flight. No `crazysim.py` process and no `crazysim-mac` container left running (`machine_after.txt`).
* **`.log` files in this folder need `git add -f`** past the `*.log` ignore rule:
  `progress.log`, `load_samples.log`, `runner_stdout.log`, `runner_extra.log`, `scoreboard_stdout.log`,
  `runs/*/follower.log`, `runs/*/sim.log`, `scoreboards/arm_*/scoreboard_stdout.log`.
  (`scoreboards/arm_*/runs/*` are symlinks into `runs/`, created only so the scorer could be run per arm;
  they carry no data of their own.)

### Not done, not claimed

* **7 repeats per arm cannot resolve a pass-rate difference of this size.** No arm comparison here is
  statistically significant, and the report does not claim one is.
* The person cost rests on **2 flights per arm**; direction is clear, magnitude is not.
* **Frame-arrival phase against the 6.5 Hz limiter was not measured**, so why the control arm shifted between
  the afternoon and evening sessions remains the afternoon README's hypothesis, not a finding of this session.
* Only three exit values were tried, all with `vis_enter` fixed at 0.75. Nothing here says what the exit bar
  does at a different enter bar, and no two-factor sweep was run.
* The pets arms were flown interleaved, but all 27 flights sit inside one ~25-minute window on one machine
  state; a slow drift in machine load over the session is shared by all arms (that is what the interleave buys)
  but is not eliminated.
