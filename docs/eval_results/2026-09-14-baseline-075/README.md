# Reference baseline at the shipping configuration: 14 cells, matte floor, vis_enter 0.75 by default

**Nothing here was measured on hardware. Every frame is rendered by the MuJoCo/himax
model; the "chip" network is the champion's `model_id_dory.onnx` run under onnxruntime
1.19.2 in doryenv, not on a GAP8. Nothing in this report says anything about a real
Crazyflie. One session, n = 4 per cell.**

**What this is.** The team ships the champion, and the 96-flight threshold sweep
(`docs/eval_results/2026-09-13-champion-threshold/`) chose a confirmation bar of 0.75
over the 0.70 every earlier baseline was flown at. That change is merged
(`b1a0108`, PR #2): `follow_person.py --vis-enter` now defaults to 0.75 and every
flight writes its effective rule into `summary.json`. This run is the first full
14-cell baseline flown at that shipping default, with **no threshold flag on any
command line**, so the record proves the default and not an argument. It is the
reference for next week's lab session, and it is compared cell by cell against the
0.70 matte baseline (`docs/eval_results/2026-09-13-matte-baseline/`).

Flights ran 2026-09-14, **09:08:45 to 10:06:53 CDT** (14:08:45 to 15:06:53 UTC), 56
flights in 58 minutes, all VALID on the first attempt, on a laptop running the
user's desktop and nothing else of this workstream's. `progress.log`,
`flights_watch.jsonl` and `flights.jsonl` are the authoritative record of when each
flight ran.

---

> **CORRECTION 2026-09-15 — the verdicts below are superseded by a scorer fix.**
> `scoreboard.py` was applying the strict clean-camera gates to any camera that
> was not exactly `himax_typical`, and `M10_uncertain_fraction_present` counts
> frames in the band `[0.45, vis_enter)`, so raising the confirmation bar to 0.75
> widened that band by construction and failed cells whose confidence traces had
> not changed. Both are fixed. Re-scored with the corrected scorer, this suite
> reads **10 PASS / 4 FAIL** rather than 8 / 6: `B.moving__proven`,
> `B.moving__delta_speed` and `B.moving__delta_camera` pass, and
> `B.moving__delta_backend` still fails, on `M1_tracking_fraction` alone. No
> measurement changed — only which lines are gates. The numbers in this document
> are all still correct as measured.

## 0. TL;DR

| claim | verdict |
|---|---|
| A 14-cell baseline at the shipping default exists | **yes** - 56 flights, 4 repeats per cell, one scoreboard, `vis_enter 0.75 / vis_exit 0.45 / confirm_frames 3` recorded in all 56 `summary.json` files, zero flags passed |
| The pet gate holds at 0.75 | **no.** `F.pets__ships` worst-repeat drift **0.734 m** against the 0.5 m gate; **2 of 4 repeats fail** (0.706, 0.734, 0.461, 0.342 m). The sweep's 4-of-4 pass (worst 0.376 m) and the smoke flight's 0.484 m did **not** reproduce, on the same scene, same model, same sensor seeds |
| 0.75 is better than 0.70 on pets | **directionally, yes.** Worst drift 0.927 -> 0.734 m, episodes 5.5 -> 3, time latched 13.7% -> 9.3%. Still FAIL on the same gate |
| The three B.moving cells that failed at 0.70 on M10 pass now | **no, and the brief's prediction was backwards.** M10's band is `[0.45, vis_enter)`; raising the bar widens it. Re-banding the 0.70 traces at 0.75 reproduces this run's numbers to within 0.01: a threshold effect on the gate, not a change in what the drone did (section 5b) |
| `D.occlusion` | `__ships` flipped **PASS -> FAIL** (relatch 1.33 -> 2.75 s, repeats 0.62 to 9.08 s). **Flagged unreliable**: this cell has swung 1.24-1.41 s vs 4.09-9.10 s on the same model before. Reported, not used (section 5c) |
| Verdicts | 0.70: **9 PASS / 5 FAIL** -> 0.75: **8 PASS / 6 FAIL**. One change: `D.occlusion__ships` |
| Something got worse | **yes** (section 6): M10 up on every A/B cell by construction, `A.static__ships` now above M10's *provisional* 0.15 line (0.228), `B.moving__delta_backend` tracking 0.9235 -> 0.917, `D.occlusion__ships` relatch and tracking, full-speed `__proven` cells 0.03-0.06 m further out |
| The machine was clean | **yes** - 0/56 upsets, worst \|pitch\| 6.81 deg, no flight below `sim_wall_ratio` 0.95, 0 torn frames, no stall outliers within speed class |
| The code was pinned and the pin held | **yes** - five sha256 identical before flight 1 and after flight 56; six scenes' `scene.xml` and `manifest.json` likewise |

The honest one-line version: *the shipping default is now measured across the whole
suite and the machine was clean, but the one thing the 0.75 change was adopted for -
passing the 0.5 m pet gate - fails on two of four fresh repeats, and the M10 gate the
team hoped it would relieve is tighter at 0.75 by definition.*

---

## 1. What was flown, and the discipline it was flown under

### The harness, as shipped

`tools/crazysim_macos/run_acceptance2.sh --out <this dir> --repeats 4 --lock <inner>`.
That is the normal CORE matrix (`--list` output in `harness_cmd.txt` / `progress.log`):
14 cells, the `--cameras` cells not added, durations as in the script. The only flag
beyond `--out` and `--repeats` is `--lock`, pointed at
`$SCRATCH/sim.harness.lock` because this workstream holds `$SCRATCH/sim.lock` for its
whole session and the harness's default per-flight lock is the same path; both prior
sessions did the same (`sim_matte.lock`, `sim_thresh.lock`). The harness's per-flight
lock was taken and released 56 times; the session lock was held 08:58:24 to the end.

`follow_person.py` was invoked by the harness with `--duration --out [--backend chip]
[--rate-hz 6.5 --latency-ms 153]` and **nothing else**. The confirmation rule came
from the argparse default at line 245 (`default=0.75`), read before the first flight.
Every one of the 56 `summary.json` files records `vis_enter 0.75, vis_exit 0.45,
confirm_frames 3` (`analysis.txt`, "PER-FLIGHT ASSERTIONS: 0 problem(s)"). A flight
recording anything else would have been a finding; there is none.

> One shell-level false start, recorded in `harness_cmd.txt`: the first launch at
> 14:07:36Z never started the harness (the tool shell is zsh, which does not word-split
> an unquoted command variable; `nohup` reported "No such file or directory"). No
> process, no run directory, no simulator resulted. Relaunched with explicit arguments
> at 14:08:45Z; that is the run.

### What the observer added, without touching the harness

`run_acceptance2.sh` does not sample machine load and does not re-assert the floor
per flight. Rather than copy its `fly()` into a private harness (what the two prior
sessions did), this run keeps the real harness and attaches an observer
(`scripts/watch_flights.py`) that tails `progress.log` with a bounded poll and, at the
moment each `flight N/56` line appears, records the 1/5/15-minute load average and
the floor of the scene about to be flown - `room.floor_reflectance` from its
`manifest.json`, the `reflectance` attribute from its `scene.xml`, and the sha256 of
that `scene.xml` at that instant - then the load again when the harness prints the
verdict. One JSON line per flight: `flights_watch.jsonl`. It cannot abort a flight;
the pre-flight check asserted all six scenes matte before flight 1 and the scene
files are hash-pinned across the run, so the per-flight record is a confirmation
rather than a guard.

### The floor was verified matte, per flight, from the manifest

All 56 records: manifest `0.0`, xml `["0"]`, and exactly six distinct `scene.xml`
hashes for six scenes - identical to `scene_hashes_before.txt` and
`scene_hashes_after.txt`. `analyze.py` re-reads the manifest post hoc from each
`cell.json`'s `scene_dir`: 56/56 still `0.0`. `floor_check_before.txt` and
`floor_check_after.txt` are byte-identical.

### The code was pinned, and the pin held

sha256 of `camera_model.py`, `follow_person.py`, `build_scene.py`, `scoreboard.py`,
`patch_crazysim.py` recorded before flight 1 and after flight 56. All five
byte-identical (`code_hashes_before.txt`, `code_hashes_after.txt`):

```
481c0a9999ff19f5f2745978d3a0076cb63a225af31e19f3c4e561ab269029de  tools/crazysim_macos/camera_model.py
8281df9fcf2c7121e7c44a0e340c3017d6930e62e4e4617e9ecfe081787e2fd5  tools/crazysim_macos/follow_person.py
ea639fea1b14abd12426aaaee4941468ff5402412ab1e42bda78adc2fe3bbe64  tools/crazysim_macos/build_scene.py
0faade4b78ba973f09796570f0f3ec44beb9f36d46fd3e3b020a1189468bbbf9  tools/crazysim_macos/scoreboard.py
20959b177d2706f4f7980c7e760fe162e82a44ba2dd7504ca3b092bc489d0803  tools/crazysim_macos/patch_crazysim.py
```

Against the sweep's pin: `camera_model.py`, `build_scene.py`, `patch_crazysim.py`
identical. `follow_person.py` differs (`4a786441...` -> `8281df9f...`) by exactly the
merged change - the default `0.7 -> 0.75`, the three keys written into
`summary.json`, and comments (`git diff b1a0108^ HEAD`, 17 lines). `scoreboard.py`
differs (`00a2a950...` -> `0faade4b...`) by reading the latch rule from `summary.json`
with a 0.70 fallback - and that is checked, not assumed:

**Re-score check.** Today's `scoreboard.py` was run over a scratch copy of the 56
committed 0.70-baseline runs (`scripts/rescore_check.py`, output `rescore_check.txt`):
**14 cells, 125 gate lines, 56 runs - 0 differences** against the committed
`scoreboard_matte14.json`. The two sides of every comparison below were scored by the
same rules. `perception_backends.py` also changed (`VIS_ENTER_RAW 4216 -> 5467`); that
constant is logged as `vis_gate` and is not used by the follower's latch.

Repo HEAD was `4339b5c` before flight 1 and after flight 56; `git status` outside this
folder was clean at both points; `tools/` untouched throughout.

### The model was verified per flight

All 28 chip flights: one ONNX path (the champion's `model_id_dory.onnx`), one sha1
(`d90555c8462b6dd6c3432d184b427d4d3e653fda`, the same as the 0.70 baseline and the
sweep), one `eps` (`0.0002009823510888964`). All 28 float flights: `backend float`.
Rate and latency requested match every `cell.json`.

### Order was NOT decorrelated from repeat index

The brief asked for the harness's normal matrix, and `run_acceptance2.sh` walks
cells x repeats in nested order: repeat *r* of every cell is the *r*-th flight of that
cell in time, and the 14 cells fly in matrix order (all `__ships` first, then
`__proven`, then the deltas). The 0.70 matte baseline shuffled its plan to break this
confound; this run did not. Any repeat-index trend here can be a time trend, and the
`__proven`/delta cells all flew in the second half of the hour, when the desktop load
was higher (section 2). Chip cells are rate-capped and immune to that; the full-speed
cells are not.

---

## 2. The machine, honestly

Per flight in `flights.jsonl` / `analysis.txt`. Upset definition as in the matte
baseline (over flown rows, `event == ""`: `|pitch| > 30` or `|roll| > 30` or
`z_min < 0.5`); the sweep's `z < 0.25` floor is reported alongside.

```
attempts            56, all VALID first time; wall per flight 51-78 s, median 64 s
attitude upsets     0 / 56 (both definitions); worst |pitch| 6.81 deg, worst |roll| 0.57 deg
z_min               0.793 .. 0.802 m on every flight
sim_wall_ratio      min 0.980  median 0.998  max 1.001; flights below 0.95: 0
torn frames         0; stale-hover events 0
load1 before        min 3.34  median 6.66  max 18.81
step_gap_ms.max     full speed (no cap)   n=28  min  81.5  median 104.8  max 111.6
                    chip speed (153 cap)  n=28  min 158.4  median 161.3  max 178.1
suspect flights     none (class-aware: > 150 ms full, > 200 ms chip, or sim/wall < 0.95)
```

Two things a reader should know:

* **A load spike to 18.8 between flights 32 and 33** (09:41:25 CDT, `B.moving__proven r4`
  ending / `C.empty__proven r1` starting; load1 7.93 -> 18.81 across that one flight,
  back to 7.5 by flight 36). Not this workstream - the harness runs one
  simulator, one follower and one chip-inference sidecar. The two adjacent flights read
  `sim_wall_ratio` 0.997 and 1.000 with step-gap maxima 103.0 and 101.7 ms, so it left
  no mark on the flights it straddled.
* **The full-speed cells ran slower than in the 0.70 baseline.** The headless
  simulator's camera runs at ~15 Hz on a quiet machine and ~12.9 Hz under load. The
  0.70 baseline's full-speed cells processed 14.6-15.2 Hz on 24 of 28 flights; this
  run's processed **12.4-13.8 Hz on 26 of 28** (the two ~15 Hz ones are
  `A.static__proven r1/r2`, the first two full-speed flights, flown when load1 was
  still 3.7-6.6). That is ~15% fewer control
  steps per second on every `__proven`, `delta_camera` and `delta_backend` flight. It
  cannot touch the chip cells (rate-capped at 6.5 Hz; 6.35-6.45 Hz in both sessions),
  but it is a confound on the small movements the full-speed cells show in section 6
  and should be read as such.

Chip-cell step gaps: median 161.3 ms against the baseline's 158.8, with two flights at
174.5 and 178.1 ms (`B.moving__ships r4`, `D.occlusion__ships r2`). Both are under two
chip periods and inside the class cap; neither produced anything unusual in its
metrics. The sweep's worst was 333 ms.

---

## 3. The 14-cell verdict table

Scored by the unmodified `scoreboard.py`, twice: once by the harness at the end of its
run (its standard last step; `scoreboards/scoreboard_075_14_harness.{json,md}`) and
once by hand with a suite label (`scoreboards/scoreboard_075_14.{json,md}`). The two
differ in nothing but the label (`rescore_check.py`: 0 differences).

| # | cell | 0.70 (Sep 12) | **0.75** | change | failed gates at 0.75 |
|---|---|---|---|---|---|
| 1 | `A.static__ships` | PASS | **PASS** | same | - |
| 2 | `B.moving__ships` | PASS | **PASS** | same | - |
| 3 | `C.empty__ships` | PASS | **PASS** | same | - |
| 4 | `D.occlusion__ships` | PASS | **FAIL** | **PASS -> FAIL** | M9_gt_visible_to_relatch_s (flagged, section 5c) |
| 5 | `E.furniture__ships` | PASS | **PASS** | same | - |
| 6 | `F.pets__ships` | FAIL | **FAIL** | same | M6_max_horizontal_drift_m |
| 7 | `A.static__proven` | PASS | **PASS** | same | - |
| 8 | `B.moving__proven` | FAIL | **FAIL** | same | M10_uncertain_fraction_present |
| 9 | `C.empty__proven` | PASS | **PASS** | same | - |
| 10 | `D.occlusion__proven` | FAIL | **FAIL** | same | M9_gt_visible_to_relatch_s (flagged) |
| 11 | `E.furniture__proven` | PASS | **PASS** | same | - |
| 12 | `B.moving__delta_backend` | FAIL | **FAIL** | same | M1_tracking_fraction, M10_uncertain_fraction_present |
| 13 | `B.moving__delta_camera` | PASS | **PASS** | same | - |
| 14 | `B.moving__delta_speed` | FAIL | **FAIL** | same | M10_uncertain_fraction_present |
| | **totals** | **9 PASS / 5 FAIL** | **8 PASS / 6 FAIL** | 1 change | |

Every gate that moved on every cell, with the direction judged by the gate's own
operator: `compare.txt` section 2.

**Read the comparison with this caveat.** Both sides are 4 repeats per cell on a
matte floor with a pinned toolchain and the same scorer, but they are two sessions two
days apart on different machine states (section 2), with the 0.70 side's plan shuffled
and this side's not. No matched-block A/B was flown. Every movement below is
before/after, not a controlled delta, and only the ones that are large against the
cell's own repeat spread should be believed.

---

## 4. The person-free safety cells did not move

`C.empty` and `E.furniture`, both backends: **0 false-follow episodes, 0.0 tracking,
0.000 m drift, on every repeat, at both bars.** The only line that moved on these four
cells is the report-only `M10_conf_max_absent` (peak confidence on a person-free
scene): 0.4985 -> 0.4975, 0.51 -> 0.5095, 0.4355 -> 0.4425, 0.464 -> 0.4895 - noise
around the same value, all 0.26-0.31 below the 0.75 bar. That line's threshold is
`vis_enter`, so it is the one gate the higher bar made *easier*; it is report-only and
has never failed a cell.

---

## 5. The three things the brief asked for

### 5a. `F.pets__ships` - the gate does not hold

`M6_max_horizontal_drift_m`, hard gate `< 0.5 m`, decided on the worst repeat.

| | r1 | r2 | r3 | r4 | worst | median | gate |
|---|---|---|---|---|---|---|---|
| 0.70 matte baseline (Sep 12) | 0.927 | 0.408 | 0.802 | 0.574 | 0.927 | 0.688 | FAIL (3 of 4) |
| sweep 0.75 arm (Sep 13) | 0.162 | 0.309 | 0.289 | 0.376 | 0.376 | 0.299 | PASS (0 of 4) |
| smoke flight, post-merge (Sep 13, `b1a0108`) | 0.484 | | | | 0.484 | | PASS (1 flight) |
| **this run, 0.75 default (Sep 14)** | **0.706** | **0.734** | 0.461 | 0.342 | **0.734** | 0.584 | **FAIL (2 of 4)** |

Four fresh repeats land at **0.342-0.734 m**; two exceed the gate. So across three
sessions at 0.75 the worst repeat has read 0.376, 0.484 and now 0.734 m. The gate is
not reliably held at 0.75; it was held once, in the sweep, and has come in higher every
time since.

Against the 0.70 baseline the change still moves the right way: worst 0.927 -> 0.734,
false-follow episodes 6/4/5/6 -> 3/4/3/3, time latched onto an animal 13.7% -> 9.3%
(median of repeats), longest single-episode drift 0.092 -> 0.043 m, first false
follow later (0.63-1.41 s -> 0.94-1.87 s). Peak confidence on the animals is unchanged
(0.848-0.900 vs 0.825-0.918); the network reads the dog the same way, the higher bar
just lets fewer of those frames through. The remaining drift is, as the matte baseline
found, accumulated over several short latches rather than one chase.

**Why this is not the sweep's result, precisely.** The sensor seed is `1000 + repeat`
in both harnesses, and `camera_model.json` for repeat *r* here is identical to the
sweep's `t075` repeat *r* in every field but the timing ones (`cost`, `state`). Same
scene files (hash-pinned), same ONNX (sha1), same camera model (hash), same latch
rule (verified from the flight). The himax noise draw that the sweep relied on to make
its four arms comparable is the *same draw* this run got - and repeat 1 drifted
0.162 m there and 0.706 m here. What the seed does not pin is the closed loop's timing:
frame arrival phase against the 6.5 Hz limiter, the 153 ms command FIFO, and machine
scheduling. On this cell those dominate. The practical consequence: **four seeded
repeats are not four replicates of the pet behaviour**, and neither the sweep's 4-of-4
pass nor this run's 2-of-4 fail is a tight bound. The brief's "no recall cost" half of
the sweep (`A.static`, `B.moving`) does reproduce here (section 7).

### 5b. The three `B.moving` cells - a threshold effect on the gate, in the wrong direction

The brief describes these cells as having failed at 0.70 "only on M10_conf_max_absent",
and predicted the higher bar would make that gate easier. Two corrections from the
scorer's own code (`scoreboard.py` lines 631-640, 714-724, 748):

1. The gate they failed is **`M10_uncertain_fraction_present`** - the fraction of
   target-in-view frames whose confidence lies in the uncertain band - `<= 0.05` on
   the median repeat, kind `gated`, clean-camera A/B cells only.
   `M10_conf_max_absent` is a `report`-kind line that has never failed any cell.
2. That band is **`[vis_exit, vis_enter)` = `[0.45, 0.75)`** at the new bar. Raising
   the enter bar *widens* it. On an identical confidence trace the fraction can only
   stay or rise, so the higher bar makes this gate **harder**, not easier.

What the scoreboard says:

| cell | M10 at 0.70 (median, per repeat) | **M10 at 0.75** | gate | verdict |
|---|---|---|---|---|
| `B.moving__proven` | 0.0599 (0.050 / 0.084 / 0.051 / 0.069) | **0.0875** (0.075 / 0.096 / 0.097 / 0.079) | <= 0.05 | FAIL -> FAIL |
| `B.moving__delta_speed` | 0.0725 (0.041 / 0.084 / 0.084 / 0.061) | **0.1074** (0.088 / 0.137 / 0.096 / 0.119) | <= 0.05 | FAIL -> FAIL |
| `B.moving__delta_backend` | 0.1071 (0.105 / 0.114 / 0.079 / 0.110) | **0.1703** (0.156 / 0.180 / 0.164 / 0.177) | <= 0.05 | FAIL -> FAIL (also M1 0.9235 -> 0.917, gate >= 0.95) |

**None pass. All three read worse, and the reading is worse by construction.** To
separate the gate from the drone, `scripts/reband_m10.py` calls the scorer's own
`metrics_for_run()` (imported, not edited; it has no side effects) on each flight's
logged trace under *both* bars (`reband_m10.txt`):

| cell | 0.70 flights, own bar | 0.70 flights re-banded at 0.75 | **0.75 flights, own bar** | 0.75 flights re-banded at 0.70 |
|---|---|---|---|---|
| `B.moving__proven` | 0.0599 | 0.0950 | **0.0875** | 0.0559 |
| `B.moving__delta_speed` | 0.0725 | 0.0973 | **0.1074** | 0.0717 |
| `B.moving__delta_backend` | 0.1071 | 0.1542 | **0.1703** | 0.1187 |

Read the last column against the first: this run's traces, scored at the old bar, give
0.0559 / 0.0717 / 0.1187 against the baseline's 0.0599 / 0.0725 / 0.1071 - the same
numbers to within 0.004-0.012. The drone's confidence trace on a swaying person is
what it was; the band moved. Every one of the 24 flights across both sessions rises by
0.02-0.07 when its band edge moves 0.70 -> 0.75, and the medians fail the 0.05 gate at
both bars in every cell. For the record, on the clean-camera cells the 5th-percentile
in-view confidence is 0.55-0.72, so a 0.45-0.75 band catches 5-18% of frames whatever
the follower does.

Two consequences for the lab and for anyone reading these numbers later: a suite
flown at 0.75 will always read a higher M10 than one flown at 0.70 on the same
behaviour, so M10 columns must not be compared across bars without re-banding; and
the `M10_uncertain_fraction_present` failures on these three cells are a property of
where the band sits relative to the champion's clean-camera confidence distribution,
not something the threshold change could have fixed. Whether the 0.05 gate is the
right gate at the new bar is a team question; nothing here answers it.

### 5c. `D.occlusion` - reported, flagged, not used

| cell | 0.70 median (per repeat) | **0.75 median (per repeat)** | gate | verdict |
|---|---|---|---|---|
| `D.occlusion__ships` | 1.329 s (1.247 / 1.412 / 1.411 / 1.240) | **2.750 s (3.603 / 1.897 / 0.620 / 9.076)** | <= 1.5 s | **PASS -> FAIL** |
| `D.occlusion__proven` | 3.240 s (2.641 / 3.507 / 2.974 / 4.313) | **2.182 s (2.501 / 1.796 / 5.428 / 1.863)** | <= 1.0 s | FAIL -> FAIL |

`D.occlusion__ships` is the one verdict that changed in this run. It is not evidence
of anything. The same cell, same model, same configuration, has read 1.24-1.41 s in
one session, 4.09-9.10 s in another, and 0.309-9.563 s across the sweep's shipped-arm
repeats; this session's 0.62-9.08 s sits inside that known spread. The within-cell
spread here (0.62 to 9.08 s) is 6x the movement of the median. `M1_tracking_fraction`
on the cell fell 0.64 -> 0.47 and mean heading error rose 4.65 -> 7.24 deg, both
consistent with a longer outage on some repeats and both equally uninformative for
the same reason. `D.occlusion__proven` moved the other way (better) and is equally not
evidence.

The cell's known scene-geometry problem (partition sized for a 2.9 m stand-off, no
longer occluding from ~1.6 m; azimuth off a flat card) is documented in the matte
baseline and the range sweep and is unchanged. No conclusion in this report rests on
either `D.occlusion` cell.

---

## 6. What got worse at 0.75

Every gate line that moved against its own operator is in `compare.txt` section 6 (45
lines). The ones that matter, in order:

1. **`F.pets__ships` still fails the pet gate, on 2 of 4 repeats (0.734 m worst).**
   Not worse than 0.70 - better - but worse than the result the change was adopted on
   (0.376 m), and the cell's status is unchanged: FAIL. Section 5a.
2. **`D.occlusion__ships` PASS -> FAIL** on M9 relatch, 1.329 -> 2.750 s. Flagged
   unreliable; section 5c. Reported here so it is not buried; not built on.
3. **`M10_uncertain_fraction_present` rose on every A and B cell**, by construction
   (section 5b). Where it is gated it still fails (3 cells); where it is provisional it
   now reads: `A.static__ships` **0.101 -> 0.228, above the provisional 0.15 line**
   (report-only today; would fail if that line were ever promoted at this bar);
   `B.moving__ships` 0.0595 -> 0.108 (under 0.15); `B.moving__delta_camera`
   0.0073 -> 0.027; `A.static__proven` 0.0063 -> 0.017 (gated at 0.05, still PASS).
4. **`B.moving__delta_backend` tracking 0.9235 -> 0.917** (gate >= 0.95, FAIL -> FAIL),
   mean heading error 2.80 -> 3.26 deg, held distance error 0.264 -> 0.305 m. This cell
   is the chip network on a clean camera at full speed; it also ran at 12.4 Hz here
   against 14.8-15.2 Hz in the baseline (section 2), which is the most likely source of
   a 0.6-point tracking movement and is not separable from the bar in this data.
5. **The full-speed `__proven` cells park slightly further out**: `A.static__proven`
   M7 settled distance error 0.110 -> 0.173 m and mean heading 0.90 -> 1.30 deg;
   `B.moving__proven` M7 0.246 -> 0.283 m, tracking 0.9885 -> 0.982; `delta_speed` M7
   0.259 -> 0.270 m. All pass with wide margin (gate 0.75 m). Same confound as item 4.
6. **`E.furniture` peak confidence on a person-free scene** 0.464 -> 0.4895
   (`__proven`) and 0.4355 -> 0.4425 (`__ships`). Noise-sized, 0.26+ below the bar,
   zero episodes either way.
7. **Chip-cell step gaps** median 158.8 -> 161.3 ms with two flights at 174.5 / 178.1
   ms; within class, no flight flagged.

Nothing in the C/E safety cells moved. Nothing on the person cells' hard gates
(M2 max, M7 final-in-band, M5 landing, M9 steered-before-reconfirm) changed result.

---

## 7. What got better, for balance

* `F.pets__ships`: worst drift 0.927 -> 0.734 m, episodes 5.5 -> 3, latched time
  13.7% -> 9.3%, per-episode drift 0.092 -> 0.043 m (section 5a).
* The sweep's "no recall cost" reproduces on the ships-as person cells:
  `A.static__ships` tracked 0.990 -> 0.9905, mean heading 3.34 -> 2.99 deg, held
  distance error 0.406 -> 0.397 m; `B.moving__ships` tracked 0.986 -> 0.992, held
  distance 0.526 -> 0.515 m. `B.moving__delta_speed` tracked 0.969 -> 0.979.
* `D.occlusion__proven` relatch 3.24 -> 2.18 s and tracking 0.870 -> 0.879 - listed
  for completeness and worth exactly as much as 5c says.

---

## 8. What this establishes, and what it does not

**Established:**

* A complete 14-cell baseline at the shipping default: 56 flights, 4 repeats per
  cell, `vis_enter 0.75` recorded by every flight, no threshold flags, pinned code,
  matte floor confirmed per flight from the manifest, one scoreboard. **8 PASS / 6
  FAIL.** This is the reference for the lab session.
* The scorer is the same scorer: today's `scoreboard.py` reproduces the committed
  0.70 scoreboard exactly, so the two baselines are directly comparable at the
  gate level.
* The pet gate is **not** reliably held at 0.75: 2 of 4 fresh repeats fail, worst
  0.734 m, on the same scene, model and sensor seeds the sweep passed with.
* The `M10_uncertain_fraction_present` failures are a band-placement effect and
  cannot have been relieved by raising the bar; re-banding proves the traces did not
  change.
* Flight stability is fine: 0 upsets in 56 more matte flights (over 200 across the
  matte sessions now), 0 torn frames, no stalls within class.

**NOT established:**

* **Anything about real hardware.** No real camera, no real Crazyflie, no lab. Every
  frame is rendered; the chip network runs under onnxruntime on a laptop.
* **A controlled 0.70 vs 0.75 comparison.** This is one session at 0.75 against a
  different session at 0.70, on a busier machine, with the full-speed cells running
  ~15% slower and the flight order not shuffled. The sweep's matched-block deltas
  remain the only controlled measure of the bar itself; this run measures where the
  shipping configuration lands, not what the bar changed.
* **A bound on the pet behaviour.** n = 4, worst-of-4, and the seed does not pin the
  outcome (0.162 vs 0.706 m on the same seed across sessions). The true worst case at
  0.75 is somewhere at or above 0.734 m and this data cannot say where.
* **Why the sweep's `F.pets` result did not reproduce.** Timing is the candidate
  (section 5a); it was not isolated. Machine load during those four flights was low
  (load1 3.4-5.0, `sim_wall_ratio` 0.983-0.995), so load is not the obvious answer.
* **Anything from `D.occlusion`**, either cell.
* **Whether the 12.9 vs 15 Hz full-speed frame rate explains the small `__proven`
  movements.** Plausible, unmeasured.
* **Whether 0.75 is the right bar.** This run does not revisit the decision; it
  reports that the gate it was adopted to pass is failing at n = 4.

---

## 9. Files, and what needs force-adding

```
README.md                          this file
harness_cmd.txt                    the exact launch line(s), including the false start
suite_meta.json, progress.log, progress.md   the harness's own records   [progress.log: *.log, needs -f]
harness_stdout.log                 the harness's stdout (log lines + scoring output)    [needs -f]
watch_stdout.log                   the observer's stdout                                 [needs -f]
flights_watch.jsonl                observer record per flight: load before/after, floor at flight time, scene.xml sha256
flights.jsonl / analysis.json / analysis.txt   the joined per-flight record and its table (scripts/analyze.py)
compare.txt                        14-cell comparison against the 0.70 baseline (scripts/compare.py)
reband_m10.txt / reband_m10.json   the M10 band re-scoring (scripts/reband_m10.py)
rescore_check.txt                  today's scorer vs the committed 0.70 scoreboard: 0 differences
code_hashes_{before,after}.txt     the five-file pin, identical
scene_hashes_{before,after}.txt    the six scenes' scene.xml + manifest.json, identical
floor_check_{before,after}.txt     manifest + xml reflectance for all six scenes, identical
machine_{before,after}.txt         load, HEAD, processes, locks at the two ends
scoreboard.{json,md}               the labelled scoreboard.py run (same content as scoreboards/scoreboard_075_14.*)
scoreboards/scoreboard_075_14.{json,md}          the labelled run
scoreboards/scoreboard_075_14_harness.{json,md}  the harness's own scoring at the end of the suite (identical modulo label)
scoreboards/scoreboard_rerun_stdout.txt
scripts/                           watch_flights.py, analyze.py, compare.py, reband_m10.py, rescore_check.py
runs/<cell>__r<N>a1/               56 run directories: cell.json, summary.json, follow_log.csv, truth.csv,
                                   metrics.json, check.txt, camera_model.json (himax cells),
                                   follower.log, sim.log   [both *.log, need -f]
```

**Nothing here has been committed or pushed.** When someone does commit it:

* These need `git add -f`, because `.gitignore` carries `*.log`:
  `progress.log`, `harness_stdout.log`, `watch_stdout.log`, `runs/*/follower.log`
  (56), `runs/*/sim.log` (56).
* **Do not force-add `runs/*/snap_*.png`** (626 files, 26 MB) or `runs/*/cache/`
  (56 dirs, 6.8 MB). They are ignored by rule (`.gitignore`: `cache/`, `snap_*.png`)
  and are not evidence.
* Everything else (`*.json`, `*.csv`, `*.txt`, `*.md`, `*.jsonl`, `scripts/*.py`)
  adds normally. Total tracked size ~18 MB.
* This folder contains no directory named `data`.

`cell.json` paths are absolute and point into this folder, so re-scoring in place
works: `trainenv/bin/python tools/crazysim_macos/scoreboard.py docs/eval_results/2026-09-14-baseline-075`.

**State left behind: none.** `tools/` untouched (hash-pinned), `scenes_v2/` untouched
(hash-pinned), no existing folder under `docs/sim_results/` or `docs/eval_results/`
modified; the 0.70 baseline was re-scored on a scratch copy. The session lock
`$SCRATCH/sim.lock` was taken at 08:58:24 CDT before any read of the tools and
released after this README was written; the harness's inner lock was released by the
harness. The 0.75 flights' `vis_enter` is in every `summary.json`; nothing was
patched at runtime.

---

## 10. Reproducing

All with `/Users/saimaruvada/Downloads/drone/trainenv/bin/python` (no bare `python`
on PATH), from the repo root unless noted.

| step | command | time |
|---|---|---|
| fly | `cd tools/crazysim_macos && ./run_acceptance2.sh --out OUT --repeats 4 --lock $SCRATCH/sim.harness.lock` | 58 min |
| observe (start right after, with the harness PID) | `scripts/watch_flights.py OUT <pid> tools/crazysim_macos/scenes_v2 4` | runs alongside |
| per-flight record + assertions | `scripts/analyze.py OUT > OUT/analysis.txt` | 1 min |
| score (the harness already did this once) | `tools/crazysim_macos/scoreboard.py OUT --suite baseline_075_14` | 1 min |
| compare to 0.70 | `scripts/compare.py OUT/scoreboards/scoreboard_075_14.json > OUT/compare.txt` | instant |
| M10 re-band | `scripts/reband_m10.py <copy of 0.70 runs> OUT/runs > OUT/reband_m10.txt` | 30 s |
| scorer identity check | see the docstring of `scripts/rescore_check.py` | 1 min |
