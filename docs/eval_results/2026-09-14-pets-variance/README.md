# F.pets__ships at vis_enter 0.75: the pet gate's real pass rate (16 repeats) + the two never-flown camera presets

Session: 2026-09-14 afternoon (harness launched 17:51:16Z), repo `pytorch_ssd` at `0c64cb0` (clean), no hardware.
Written progressively under a 40-minute wall-clock budget; every number below is pasted from files in this folder.

Read first: `docs/eval_results/2026-09-14-baseline-075/README.md` section 5a. Short version of the question:
four sweep flights at 0.75 read 0.162/0.309/0.289/0.376 m (all pass the 0.5 m M6 gate), a smoke flight 0.484,
and four flights this morning 0.706/0.734/0.461/0.342 (two fail) - same scene, model and sensor seeds.
"Passes the gate" was withdrawn this morning. Nobody knew the pass rate. This folder measures it.

## What was flown, exactly

* Harness: `tools/crazysim_macos/run_acceptance2.sh --out <this dir> --only 'F\.pets' --repeats 16 --lock <scratch>/sim.harness.lock`
  (verbatim launch line with timestamp: `harness_cmd.txt`; harness stdout: `harness_stdout.log`; per-flight log: `progress.log` / `progress.md`).
  The normal harness, cell selected by its own `--only` regex; **no threshold flags** - `follow_person.py` was invoked by the
  harness exactly as for the CORE matrix (`--duration 35 --out <run> --backend chip --rate-hz 6.5 --latency-ms 153`) and took
  its default `vis_enter`. Every `summary.json` records `vis_enter 0.75 / vis_exit 0.45 / confirm_frames 3` (checked by
  `scripts/analyze_pets.py`, see the "vis_enter values seen" line in `pets_table.md`).
* Sensor seed: the harness's own rule, `1000 + repeat`, so seeds 1001-1016. Repeats 1-4 therefore reuse the exact himax
  noise draws of the sweep and of this morning's run (their `camera_model.json` differ from this morning's only in the
  timing fields `cost` and `state`, checked for r1).
* Scene: `scenes_v2/s03_pets_only`, matte floor (`manifest floor_reflectance 0.0`, `scene.xml reflectance="0"`),
  `scene.xml` sha256 `40dd318c25ac...` - identical to the hash recorded in `baseline-075/scene_hashes_before.txt` (`scene_hashes_before.txt`).
  Dog: 0.65 m panel at x=2.6 m, springing along y between -1.3 and -0.3 m with a 26 s period (to the drone's right, bearing
  about -6 to -27 deg from its start heading). Cat: 0.4 m panel, static at (2.2, 0.9) (to the left, about +22 deg).
* Model: chip backend, `model_id_dory.onnx` sha1 `d90555c8462b6dd6c3432d184b427d4d3e653fda` (`model_hash.txt`), same sha1 the
  baseline-075 README records.
* Tool hashes (camera_model.py, follow_person.py, build_scene.py, scoreboard.py, patch_crazysim.py) pinned before and after:
  `code_hashes_before.txt`, `code_hashes_after.txt`. Nothing under `tools/` was edited. Nothing under `docs/` from earlier
  sessions was touched. Nothing was committed or pushed (the brief forbids it).
* Load average was sampled every 5 s for the whole session (`load_samples.log`, started after flight 1 had begun, so
  flight 1 has no load figure). Machine state before/after: `machine_before.txt`, `machine_after.txt`.
* Scoring: the harness ran `scoreboard.py` on this folder when the last flight landed (`scoreboard.json`, `scoreboard.md`,
  per-run `metrics.json`). `scripts/analyze_pets.py` recomputes M6 with the scorer's own rule (max horizontal displacement
  from the first flown row, rows with `event == ""`) and cross-checks it against `metrics.json`; on the baseline-075 pets
  runs it reproduces 0.706/0.734/0.461/0.342 with 0 mismatches.

Files: `pets_flights.jsonl` (one record per flight, all columns), `pets_table.md` (the table below plus the pass-vs-fail
block), `pooled.md` (cross-session pooling), `scripts/` (`analyze_pets.py`, `pooled.py`, `cell_summary.py`,
`launch_cameras_after_pets.sh`), `scoreboards/` (copies of the scorer output for both jobs), `runs/` (the 16 pets flights),
`cameras/` (Job 2: its own `runs/`, `progress.log`, `scoreboard.*`).
`*.log` files under this folder are gitignored and need `git add -f` (harness_stdout.log, progress.log, load_samples.log,
cameras_waiter.log, runs/*/follower.log, runs/*/sim.log, cameras/**).

## Job 1 - the pet gate's real pass rate at the shipped setting

### The answer, plainly

**0.75 is not a pass at this gate. Per flight it is a weighted coin: 11 of 16 fresh flights drifted less than 0.5 m
(pass rate 0.688, Clopper-Pearson 95% [0.413, 0.890]). Under the harness's own cell rule - worst of 4 repeats - a
4-repeat `F.pets__ships` cell at 0.75 passes about one time in four (0.688^4 = 0.22) and fails the other three.**
The scorer's verdict on this 16-repeat cell: FAIL on `M6_max_horizontal_drift_m` = 1.188 m (worst repeat), gate < 0.5.

All 16 flights VALID on the first attempt (no re-flies), 13 min wall clock, 52 s per flight.

### Per-flight table (flown order = repeat order = seed order)

M6 recomputed by `scripts/analyze_pets.py`; `scorer` is the harness scoreboard's `metrics.json` value (**16 of 16 identical**).
`t_first` = time from the first flown row to the first latch (in this scene every latch is a false follow);
`latched` = total seconds latched; `eps` = latch episodes; `longest ep` = longest single episode; `drift toward` = whether
the net displacement at max drift pointed nearer the dog or the cat (all displacements are 2-7 deg right of the start
heading, i.e. straight ahead and slightly toward the dog side; r13's "cat" label is a 24-vs-24 deg tie, not a cat chase);
`dog y@1st` / `dog vy@1st` = the dog's y and y-velocity at first latch (its 26 s spring is at the same phase, y about -0.32 m,
in every flight, so the dog's approach direction is the same every time); `gap max` = `step_gap_ms.max` from `summary.json`
(chip-class floor ~158 ms); `load1` = mean 1-min load average over the flight from `load_samples.log` (None for r1: the
sampler started 30 s into flight 1). No attitude upsets: |roll| max 0.11-0.48 deg, |pitch| max 3.8-5.2 deg (normal
forward-flight pitch), z_max 0.84-0.85 m, every flight landed (`M5` 0.02 m, PASS), 0 stale events, 0 torn frames.

| rep | seed | vis_enter | M6 m | scorer | gate | t_first s | conf1 | latched s | eps | longest ep | trk frac | drift toward | bearing | dog y@1st | dog vy@1st | yaw@max | roll max | pitch max | sim/wall | Hz | gap max ms | load1 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 1001 | 0.75 | 0.188 | 0.188 | PASS | 2.17 | 0.816 | 0.79 | 2 | 0.63 | 0.048 | dog (off 6) | -6.1 | -0.31 | 0.015 | -5.0 | 0.13 | 4.45 | 0.980 | 6.423 | 158.8 | - |
| 2 | 1002 | 0.75 | 0.348 | 0.348 | PASS | 2.34 | 0.770 | 0.78 | 2 | 0.47 | 0.046 | dog (off 24) | -2.4 | -0.32 | 0.024 | -9.2 | 0.15 | 4.36 | 0.988 | 6.415 | 158.9 | 4.90 |
| 3 | 1003 | 0.75 | 0.231 | 0.231 | PASS | 2.03 | 0.767 | 0.61 | 2 | 0.31 | 0.040 | dog (off 8) | -4.7 | -0.32 | 0.023 | -5.0 | 0.13 | 4.36 | 0.974 | 6.426 | 164.7 | 4.51 |
| 4 | 1004 | 0.75 | 0.409 | 0.409 | PASS | 1.55 | 0.781 | 0.47 | 2 | 0.31 | 0.033 | dog (off 22) | -3.7 | -0.33 | 0.029 | -4.9 | 0.12 | 4.26 | 0.987 | 6.437 | 158.8 | 6.30 |
| 5 | 1005 | 0.75 | **0.684** | 0.684 | **FAIL** | 2.33 | 0.785 | 1.87 | 4 | 0.78 | 0.105 | dog (off 20) | -5.8 | -0.32 | 0.022 | -15.6 | 0.22 | 4.07 | 0.987 | 6.426 | 165.8 | 6.07 |
| 6 | 1006 | 0.75 | **0.613** | 0.613 | **FAIL** | 1.24 | 0.761 | 2.18 | 2 | 1.87 | 0.106 | dog (off 11) | -6.1 | -0.34 | 0.033 | -13.7 | 0.32 | 4.83 | 0.988 | 6.427 | 158.5 | 5.77 |
| 7 | 1007 | 0.75 | **1.188** | 1.188 | **FAIL** | 1.24 | 0.821 | 4.82 | 3 | 3.11 | 0.230 | dog (off 19) | -6.8 | -0.32 | 0.026 | -9.9 | 0.17 | 4.96 | 0.984 | 6.428 | 158.5 | 5.64 |
| 8 | 1008 | 0.75 | 0.220 | 0.220 | PASS | 2.65 | 0.782 | 0.31 | 2 | 0.16 | 0.026 | dog (off 22) | -4.4 | -0.31 | 0.016 | -9.9 | 0.20 | 5.24 | 0.986 | 6.431 | 158.8 | 5.35 |
| 9 | 1009 | 0.75 | 0.295 | 0.295 | PASS | 1.87 | 0.782 | 0.62 | 1 | 0.62 | 0.033 | dog (off 21) | -5.0 | -0.34 | 0.033 | -5.7 | 0.16 | 5.01 | 0.986 | 6.430 | 158.9 | 5.05 |
| 10 | 1010 | 0.75 | 0.276 | 0.276 | PASS | 1.72 | 0.770 | 0.46 | 2 | 0.31 | 0.033 | dog (off 19) | -6.9 | -0.34 | 0.033 | -4.9 | 0.13 | 4.37 | 0.985 | 6.426 | 158.8 | 4.55 |
| 11 | 1011 | 0.75 | **1.121** | 1.121 | **FAIL** | 0.77 | 0.826 | 4.51 | 3 | 2.48 | 0.212 | dog (off 20) | -6.0 | -0.38 | 0.045 | -10.8 | 0.17 | 4.67 | 0.986 | 6.427 | 158.8 | 4.05 |
| 12 | 1012 | 0.75 | 0.484 | 0.484 | PASS | 2.33 | 0.811 | 1.09 | 3 | 0.62 | 0.066 | dog (off 22) | -4.7 | -0.32 | 0.024 | -27.1 | 0.11 | 4.88 | 0.992 | 6.431 | 158.8 | 5.90 |
| 13 | 1013 | 0.75 | **0.506** | 0.506 | **FAIL** | 1.71 | 0.781 | 1.09 | 4 | 0.31 | 0.073 | cat (off 24, tie) | -2.1 | -0.34 | 0.032 | -15.7 | 0.48 | 4.56 | 0.986 | 6.428 | 158.6 | 5.79 |
| 14 | 1014 | 0.75 | 0.322 | 0.322 | PASS | 1.09 | 0.782 | 0.62 | 2 | 0.31 | 0.042 | dog (off 19) | -4.4 | -0.32 | 0.023 | -14.6 | 0.34 | 4.45 | 0.989 | 6.425 | 158.5 | 4.78 |
| 15 | 1015 | 0.75 | 0.346 | 0.346 | PASS | 0.77 | 0.816 | 1.10 | 3 | 0.62 | 0.071 | dog (off 22) | -4.4 | -0.33 | 0.027 | -10.6 | 0.13 | 4.34 | 0.995 | 6.435 | 158.7 | 4.76 |
| 16 | 1016 | 0.75 | 0.376 | 0.376 | PASS | 0.78 | 0.827 | 0.94 | 3 | 0.47 | 0.064 | dog (off 24) | -2.7 | -0.32 | 0.024 | -23.4 | 0.20 | 3.79 | 0.991 | 6.423 | 158.5 | 4.83 |

Drifts in flown order: **0.188, 0.348, 0.231, 0.409, 0.684, 0.613, 1.188, 0.220, 0.295, 0.276, 1.121, 0.484, 0.506, 0.322, 0.346, 0.376**.
Count under 0.5 m: **11 of 16**. Median 0.362, mean 0.475, sd 0.299, worst 1.188 m.

Timing and load, all 16: sim_wall_ratio 0.974-0.995, processed 6.415-6.437 Hz (6.5 requested), step_gap max 158.5-165.8 ms
(median 155.2 everywhere; the two flights above 160 ms, r3 164.7 and r5 165.8, are one pass and one fail), load average
4.05-6.30 while flying (the machine had a ~3.4-4.4 background load before the session started, `machine_before.txt`).

### Do passing and failing flights differ in anything visible?

`pets_table.md` has the full block (median [min-max] per group, Mann-Whitney two-sided p, 11 vs 5 flights - low power, read
p-values as a screen only).

What differs is only the *consequence* of a latch persisting, not anything that precedes it:

| column | pass (11) | fail (5) | p |
|---|---|---|---|
| total latched s | 0.62 [0.31-1.10] | 2.18 [1.09-4.82] | 0.004 |
| tracking fraction | 0.042 [0.026-0.071] | 0.106 [0.073-0.230] | 0.002 |
| longest single episode s | 0.47 [0.16-0.63] | 1.87 [0.31-3.11] | 0.028 |
| max drift inside one episode m | 0.006 [0-0.023] | 0.254 [0.009-0.457] | 0.013 |
| latch episodes | 2 [1-3] | 3 [2-4] | 0.031 |

What does **not** differ:

* **First-latch timing**: pass median 1.87 s [0.77-2.65], fail 1.24 s [0.77-2.33], p = 0.36. The earliest latch (0.77 s) occurs
  in both a fail (r11) and a pass (r15). Confidence at the first latch is the same (0.782 vs 0.785, p = 0.78).
* **Which way the dog was approached**: identical in every flight. The dog sits at its y = -0.3 m turning point at first latch
  (y -0.31 to -0.38, |vy| 0.015-0.045 m/s) because the takeoff-to-latch time is short against its 26 s period; 15 of 16 net
  displacements point at the dog side, the 16th (r13) is a tie. Nobody approached the dog from a different side.
* **Load**: pass 4.87 [4.51-6.30], fail 5.77 [4.05-6.07], p = 0.37. The lowest-load flight of the session (r11, 4.05) is the
  second-worst drift (1.121 m).
* **Step-gap max**: 159 [158-165] vs 159 [158-166], p = 0.45; **sim/wall** 0.987 vs 0.986, p = 0.57; **frames dropped**
  181 vs 184, p = 0.46; **processed Hz** identical.
* **Attitude**: |roll| max 0.13 vs 0.22 deg (p = 0.03 but both are a fraction of a degree - the failing flights fly further, so
  they bank a little more); |pitch| max 4.4 vs 4.7 deg, p = 0.50. No upsets anywhere.
* **Sensor seed**: seeds 1001-1004, the sweep's and this morning's exact noise draws, produced 0.188/0.348/0.231/0.409 here
  (all pass), 0.162/0.309/0.289/0.376 in the sweep (all pass), 0.706/0.734/0.461/0.342 this morning (two fail). Across three
  sessions those four seeds are 10 of 12 passes, the twelve fresh seeds 1005-1016 are 7 of 12. The seed pins the camera noise,
  not the outcome.

Mechanism, as far as the data shows it: every flight latches onto the dog at 0.76-0.83 confidence within 0.8-2.7 s (the
network reads the dog the same way every time). What decides pass/fail is whether that latch, once made, *persists*:
the exit bar is 0.45, so the track only drops when the dog's confidence falls below 0.45, and in the 5 failing flights one
episode lasted 0.8-3.1 s and the drone closed 0.25-0.46 m on the dog inside it, on top of the 0.2-0.4 m of drift that
even the passing flights accumulate through 1-3 short latches. Nothing recorded before the latch - timing, load, seed,
dog phase, first-latch confidence - separates the two groups; the difference is in the frame-to-frame confidence trace
during the latch, which the sensor seed does not pin (the morning README's timing-phase explanation is consistent with this,
but this session did not measure frame phase directly, so it stays a hypothesis).

### Pooled with the earlier 0.75 flights (`pooled.md`, `scripts/pooled.py`)

| session | n | pass | fail | rate | CP 95% | worst |
|---|---|---|---|---|---|---|
| sweep 0.75 arm (Sep 13, `t075__F.pets__ships`, seeds 1001-1004; flown at 0.75 per cell.json; summary.json has no vis_enter field, so the scorer labelled it with its legacy 0.70 fallback (scoreboard.py LEGACY_VIS_ENTER = 0.70), which affects only the M10 label, not M6) | 4 | 4 | 0 | 1.000 | [0.398, 1.000] | 0.376 |
| baseline-075 (Sep 14 morning, seeds 1001-1004) | 4 | 2 | 2 | 0.500 | [0.068, 0.932] | 0.734 |
| smoke flight post-merge (Sep 13, `b1a0108`; quoted from the baseline-075 README, run dir not located here) | 1 | 1 | 0 | - | - | 0.484 |
| **this session (Sep 14 afternoon, seeds 1001-1016)** | **16** | **11** | **5** | **0.688** | **[0.413, 0.890]** | **1.188** |
| pooled: the 8 earlier (sweep + morning) | 8 | 6 | 2 | 0.750 | [0.349, 0.968] | 0.734 |
| pooled: 8 earlier + this session | 24 | 17 | 7 | 0.708 | [0.489, 0.874] | 1.188 |
| pooled: 9 earlier (incl. smoke) + this session | 25 | 18 | 7 | 0.720 | [0.506, 0.879] | 1.188 |

The three sessions are consistent with one per-flight pass probability of about 0.7: the sweep's 4-of-4 has probability
0.7^4 = 0.24 under it, this morning's 2-of-4 has 0.26. Neither was an outlier; both were four draws from a coin that
lands "pass" about 70% of the time. With 24 flights pooled the 95% interval [0.49, 0.87] still does not exclude 0.5 and
excludes anything above 0.87 - so "the gate holds at 0.75" is ruled out, and "it is a coin flip" is not.

## Job 2 - the two never-flown camera presets (`run_acceptance2.sh --cameras`)

Launched automatically the moment the pets harness exited (`scripts/launch_cameras_after_pets.sh`, bounded poll, launch
line in `cameras_launch.txt`, 18:05:06Z, 25 min of budget left). 2 cells x 2 repeats, 4 flights, all VALID first attempt,
4 min. Scored by the harness's own `scoreboard.py` call (`cameras/scoreboard.json`, copy in `scoreboards/`). Same scene as
the reference cell (`s01_control_moving`, sha256 `ad1caece...`, identical to `baseline-075/scene_hashes_before.txt`), float
backend, full speed, vis_enter 0.75 in every summary.json, presets confirmed in each run's `camera_model.json`
(`himax_low_light` seeds 1001/1002, `himax_color_bayer` seeds 1001/1002), person in view 100% of frames in all 4 flights.

| cell | camera | verdict | failed gates | M1 tracking (median; r1 / r2) | M2 heading err mean / max deg | M10 present | M7 dist err | Hz |
|---|---|---|---|---|---|---|---|---|
| `B.moving__delta_lowlight` | himax_low_light | **FAIL** | `M10_uncertain_fraction_present` 0.0842 > 0.05 | 0.981 (0.966 / 0.996) | 3.24 / 9.82 (median of per-flight max; worst single flight 10.02) | 0.0842 | 0.349 | 14.8 |
| `B.moving__delta_bayer` | himax_color_bayer | **FAIL** | `M1_tracking_fraction` 0.8545 < 0.95; `M10_uncertain_fraction_present` 0.2552 > 0.05 | 0.8545 (0.940 / **0.769**) | 2.90 / 9.56 (median of per-flight max; worst single flight 10.37) | 0.2552 | 0.616 | 15.1 |
| `B.moving__delta_camera` (baseline-075, himax_typical, 4 rep) | himax_typical | PASS | none | 0.996 (all four) | 3.30 / 9.29 | 0.0268 | 0.424 | 12.7 |
| `B.moving__proven` (baseline-075, clean, 4 rep) | clean | FAIL | `M10_uncertain_fraction_present` 0.0875 | 0.982 (0.975-0.996) | 3.05 / 8.84 | 0.0875 | 0.283 | 12.9 |

Heading error passes on both new presets (M2 mean <= 6, max <= 14), and is indistinguishable from the typical and clean
cameras. Distance hold passes (M7). Every flight landed, 0 stale events.

**One scorer fact you need before reading the verdicts.** `scoreboard.py` line 696: `himax = cell.get("camera") == "himax_typical"`.
Only that literal preset gets the relaxed camera thresholds (M1 >= 0.9 and M10 <= 0.15, both *provisional*, report-only).
`himax_low_light` and `himax_color_bayer` fall through to the clean-camera *gated* thresholds (M1 >= 0.95, M10 <= 0.05).
So the two new cells were judged more strictly than the himax_typical cell they were designed to be compared with.
This is not edited here; it is reported so the verdicts below are read against the right bar.

* **Low light: FAIL only on `M10_uncertain_fraction_present` (0.0842 vs <= 0.05).** Tracking 0.981 and heading error pass the
  strict gates. Under the himax_typical bar (M10 <= 0.15, M1 >= 0.9) it would have no failed gate at all. The gate it fails is
  the one the *clean* camera also fails on this scene at 0.75 (0.0875, baseline-075) and the one the morning README showed is
  widened by raising vis_enter (band `[0.45, 0.75)`). M10 0.084 sits between typical (0.027) and clean (0.0875). Reading:
  **not a low-light sensor effect on the data here** - the low-light preset (scene_light 0.045, analog gain 8x, 10.6 ms
  exposure, AE converged) tracks and points like the typical camera; the FAIL is the 0.75 threshold's M10 cost plus the
  scorer's camera classification. Not a scene effect either: same scene, person in view 100%, reference cameras track it.
* **Bayer: FAIL on `M1_tracking_fraction` (0.8545; repeats 0.940 and 0.769) and `M10_uncertain_fraction_present` (0.2552).**
  Both fail even the relaxed himax_typical bar (0.9 / 0.15). Same scene, person in view 100% of frames, and the other three
  cameras track it at 0.966-0.996 - so it is **a sensor-model effect, not a scene effect**: the Bayer preset carries a wider
  PSF (1.15 / 1.6 px centre / corner vs 0.65 / 1.1 for typical and low light) plus the colour mosaic, and on those frames the
  network's confidence on a real person falls into the uncertain band a quarter of the time and below vis_exit often enough
  to drop the track (r2 tracked 77%). Heading error while tracking is unaffected (2.9 deg mean). Which of blur vs mosaic is
  responsible is not separable from these 4 flights; that would need a preset with one moved at a time.

Two repeats per cell is what the brief asked for; with r1 0.940 vs r2 0.769 on Bayer, the M1 spread between repeats is large,
so the Bayer *magnitude* is uncertain even though the direction (worse than typical on tracking) is not.

## Budget and housekeeping

* Wall clock: t0 12:50:13 CDT; pets harness 12:51:16-13:05:06 (13 min, 16 flights, 52 s each); cameras 13:05:06-13:09:34
  (4 min); all flying finished at 19 min elapsed, well inside the 35-minute stop.
* `code_hashes_before.txt` == `code_hashes_after.txt` (diff clean) for the five tools; `tools/` untouched.
* Both locks released (`sim.lock` by this session at the end, `sim.harness.lock` by the harness after each flight);
  no `crazysim.py` process, no `crazysim-mac` container, no harness process left running; load sampler stopped
  (224 samples, `load_samples.log`).
* `git status`: only this folder is new/untracked. Nothing committed, nothing pushed, nothing under earlier `docs/` touched.
* Not done / not claimed: the Sep 13 smoke flight's run directory was not located (its 0.484 m is quoted from the
  baseline-075 README); frame-arrival phase against the 6.5 Hz limiter was not measured, so the timing explanation for
  why a latch persists remains the morning README's hypothesis, not a finding of this session; the 16 flights were flown
  back-to-back on one machine state, so any slow drift in machine load over the session is confounded with repeat order
  (fails landed at repeats 5, 6, 7, 11, 13 - not clustered at one end).
