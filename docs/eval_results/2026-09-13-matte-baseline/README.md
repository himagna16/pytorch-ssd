# The complete mirror-free baseline — all 14 cells, matte floor

**What this is.** Every published simulator result before Sep 12 was rendered through a
20% mirror in the MuJoCo groundplane, so the network read each subject plus its
reflection as one taller object. The Sep 13 stability run re-flew seven of the
fourteen acceptance cells on the matte floor. This run flies **the other seven**, and
merges both halves into **one 14-cell scoreboard**. That scoreboard is the first
complete mirror-free picture the team has.

**Nothing here was measured on hardware. Every frame is rendered. Nothing in this
report says anything about a real Crazyflie.**

Flights ran 2026-09-12, 17:02–17:29 CDT (22:02–22:28 UTC), 28 flights in 27 minutes,
on a laptop running nothing but the user's desktop. (The directory is named
`2026-09-13-matte-baseline` per the workstream instruction; `progress.log` and
`flights.jsonl` are the authoritative record of when it ran.)

Companions, none of them modified:
`docs/sim_results/2026-09-11-simv2/` (the mirrored baseline being compared against),
`docs/eval_results/2026-09-12-distance/` (root cause of the mirror),
`docs/eval_results/2026-09-13-stability/` (the other seven matte cells).

---

## 0. TL;DR

| claim | verdict |
|---|---|
| The complete matte baseline exists | **yes** — 14 cells, 56 flights, 4 repeats each, one scoreboard |
| Removing the mirror improves the suite overall | **yes** — 7 PASS / 7 FAIL (mirrored) → **9 PASS / 5 FAIL** (matte) |
| The drone still chases the dog on a matte floor | **largely no.** Drift 2.301/2.666 m → **0.408–0.927 m**; time latched onto the dog 68–78% → **8–19%** |
| …but `F.pets__ships` still fails its gate | **yes** — M6 needs < 0.5 m and three of four flights exceed it (0.574, 0.802, 0.927 m) |
| Something got worse | **yes, and it changed category.** `D.occlusion__proven` PASS → **FAIL** on M9 relatch: 0.47 s → 3.24 s |
| The machine was clean | **yes** — 0/28 upsets, worst \|pitch\| 6.0°, no flight below `sim_wall_ratio` 0.95, no stall outliers |
| This settles champion vs confuser | **no.** Not touched, deliberately. See §7 |

The honest one-line version: *taking the mirror out fixed distance keeping across the
board and mostly stopped the drone chasing the dog — and by letting the drone finally
get close to a person, it exposed a close-range detection weakness that the mirror had
been hiding.*

---

## 1. What was flown, and the discipline it was flown under

The seven cells with no clean data, copied verbatim from `run_acceptance2.sh`'s CORE
matrix:

```
C.empty__ships       s02_control_empty       chip  / himax_typical / 6.5 Hz  35 s
D.occlusion__ships   s07_occlusion_reappear  chip  / himax_typical / 6.5 Hz  60 s
E.furniture__ships   s16_furniture_only      chip  / himax_typical / 6.5 Hz  35 s
F.pets__ships        s03_pets_only           chip  / himax_typical / 6.5 Hz  35 s
C.empty__proven      s02_control_empty       float / clean         / full    35 s
D.occlusion__proven  s07_occlusion_reappear  float / clean         / full    60 s
E.furniture__proven  s16_furniture_only      float / clean         / full    35 s
```

4 repeats each = **28 flights**, all VALID on the first attempt, 27 min wall clock.

### The code was pinned, and the pin held

sha256 of `camera_model.py`, `follow_person.py`, `build_scene.py`, `scoreboard.py`,
`patch_crazysim.py` recorded **before flight 1** and re-checked **after flight 28**.
All five byte-identical (`code_hashes_before.txt`, `code_hashes_after.txt`):

```
66862b05575e270ea73e2dfaf815676ac3e93420cc00c887fc71792d1bf0051d  tools/crazysim_macos/camera_model.py
4a786441f85b431aa61347cd902d797a55d7cb8bb2d77c2fb64ef71abfb68de6  tools/crazysim_macos/follow_person.py
ea639fea1b14abd12426aaaee4941468ff5402412ab1e42bda78adc2fe3bbe64  tools/crazysim_macos/build_scene.py
00a2a950131a3337614b065450b8cb89371b7ab18f256bed24f5769c2917ef33  tools/crazysim_macos/scoreboard.py
20959b177d2706f4f7980c7e760fe162e82a44ba2dd7504ca3b092bc489d0803  tools/crazysim_macos/patch_crazysim.py
```

**These five hashes are identical to `2026-09-13-stability/data/code_hashes_after.txt`.**
That is the strongest thing that can be said about the merge: both halves of the
14-cell baseline were flown by byte-identical tooling, so merging them is legitimate
rather than convenient.

> **One provenance note.** The repo was at `cd289d3` when this run was planned, but a
> commit landed at 16:58:33 — four minutes before flight 1 — so these flights actually
> ran at **`b1511c8`** ("Install cv2 for the lab fallback viewer…"). It was not mine; I
> committed nothing. It touches three files, all Markdown under `docs/hardware/`, and
> nothing under `tools/`, `scenes_v2/`, or any evidence directory. The five-file code pin
> above is the binding check and it held across the whole suite, so the result is
> unaffected — but the commit is recorded here rather than left for someone to trip over.

### The floor was verified matte, three ways

1. **Manifest.** `room.floor_reflectance` reads `0.0` in all four scene manifests
   (`s02_control_empty`, `s07_occlusion_reappear`, `s16_furniture_only`,
   `s03_pets_only`), alongside the builder's own note explaining that 0.2 was a mirror.
2. **The MJCF actually flown.** Each `scene.xml` contains exactly **one** `reflectance`
   attribute and it reads `reflectance="0"`. Checked before the first flight and again
   after the last.
3. **Per flight, at flight time.** `fly_plan_matte.sh` greps the reflectance out of the
   scene it is about to fly and **aborts the flight** if it is not 0; the value it read
   is written to `runs/*/floor_reflectance.txt`. All 28 files read `0`.

And visually — `pets_matte_floor_no_reflection.png` is frame 1 of
`F.pets__ships__r1a1`: the dog and cat cards sit on the checkerboard with **no
reflection beneath them**. On the mirrored floor that reflection is what made a 0.65 m
dog read as a person-height object.

### Repeat index was decorrelated from flight order

`follow_person.py` contains no RNG. The repeat index reaches the simulator through one
channel only — `CRAZYSIM_SENSOR_SEED = 1000 + repeat` — and that is exported only when
`camera != clean`. Three of these seven cells (`C/D/E __proven`) are clean-camera cells,
so their four repeats are **configuration-identical** and "repeat 3" could only ever
mean "the third flight in time". The 28 (cell, repeat) pairs were therefore shuffled
before flying.

A plain shuffle does not achieve this by itself: the stability run's own seed gives
Spearman **+0.414** on this 7-cell matrix. So the seed was **selected**, before any
flight and using no outcome, from a scan of 60 000 candidates: the best-ranked seed
meeting all three of |Spearman(order, repeat)| ≤ 0.01, every cell's four flights spread
over ≥ 15 of the 28 slots, and every repeat index's mean position within 2.5 of 14.5.
The selection criteria are properties of the plan, not of any result. Realised
(`plan_balance.txt`):

```
spearman(order, repeat) = -0.010
repeat 1 mean position 17.0   repeat 3 mean position 12.4
repeat 2 mean position 16.1   repeat 4 mean position 12.4
F.pets__ships flew at positions 6, 14, 20, 27 of 28
```

### Nothing under measurement was modified

`scripts/fly_plan_matte.sh` reproduces `run_acceptance2.sh`'s `fly()` body verbatim,
with three deliberate changes: the scene root is a parameter, load average is sampled
around every flight, and the order comes from the plan file. `run_acceptance2.sh`
itself, the follower, the camera model, the checkpoint and the ONNX are the repo's own,
unedited. `scoreboard.py` was **run**, never touched.

---

## 2. The machine, honestly

This run got a much quieter laptop than the stability run did, and it shows.

```
sim_wall_ratio    min 0.984   median 0.996   max 1.000     flights below 0.95: 0 of 28
load1 before      min 5.21    median 7.27    max 10.80
attitude upsets   0 / 28      worst |pitch| 6.00 deg, worst |roll| 0.56 deg
z_min             0.798 .. 0.802 m on every one of 28 flights
```

Upsets use the stability run's definition verbatim (over flown rows, `event == ""`:
`|pitch| > 30°` or `|roll| > 30°` or `z_min < 0.5`). Zero upsets, and a 5× margin to the
30° envelope. This is consistent with the stability run's 0/28 and adds 28 more matte
flights to that count — **0 upsets in 56 matte flights now**.

### `step_gap_ms.max` must be read per speed class

The stability run flagged `step_gap_ms.max` as the better instrument for transient
stalls, because `sim_wall_ratio` is a flight average while a stall is a moment. It is
the right instrument, but it has a trap that matters here: **a chip-speed cell is
deliberately rate-capped at 153 ms**, so its gap floor is ~154 ms by construction. Ten
of my fourteen cell-instances are chip-speed. Reading their ~159 ms against the
stability run's "158 ms lead" would be comparing a rate cap to a stall.

Split by class:

```
full speed (no cap)      n=12   min  76.6   median  88.9   max 106.8 ms
chip speed (153 ms cap)  n=16   min 158.6   median 158.8   max 163.7 ms
```

Both distributions are tight — the chip cells span 5.1 ms across 16 flights. **No
flight is an outlier within its class, and none is flagged suspect.** For comparison,
the Sep 12 suite that produced the false upset finding had a median max-gap of 168.8 ms
and reached 875.7 ms.

Per-flight load, `sim_wall_ratio`, `step_gap_ms` and attitude for all 28 flights:
`analysis.txt`. Machine state was checked before starting and the suite was not paused;
load never exceeded 10.8.

---

## 3. The complete 14-cell baseline

Built by `scripts/score_merged.sh`, which copies both halves into a scratch suite and
runs the unmodified `scoreboard.py`. Copies, because `scoreboard.py` writes
`metrics.json` into the run directories it scores and the stability run's are committed
evidence. The two halves use disjoint cell ids, so they merge with no renaming.

**Merge fidelity, checked:** all seven stability cells score **byte-identically** inside
the 14-cell suite — same verdict, same failed gates, same value on every gate. Merging
changed nothing about them.

| # | cell | mirrored (Sep 11) | **matte** | change |
|---|---|---|---|---|
| 1 | `A.static__ships` | FAIL | **PASS** | **FAIL → PASS** |
| 2 | `B.moving__ships` | FAIL | **PASS** | **FAIL → PASS** |
| 3 | `C.empty__ships` | PASS | **PASS** | same |
| 4 | `D.occlusion__ships` | PASS | **PASS** | same |
| 5 | `E.furniture__ships` | PASS | **PASS** | same |
| 6 | `F.pets__ships` | FAIL | **FAIL** | same (M6 drift) |
| 7 | `A.static__proven` | PASS | **PASS** | same |
| 8 | `B.moving__proven` | FAIL | **FAIL** | same (M10) |
| 9 | `C.empty__proven` | PASS | **PASS** | same |
| 10 | `D.occlusion__proven` | PASS | **FAIL** | **PASS → FAIL** |
| 11 | `E.furniture__proven` | PASS | **PASS** | same |
| 12 | `B.moving__delta_backend` | FAIL | **FAIL** | same (M1 + M10) |
| 13 | `B.moving__delta_camera` | FAIL | **PASS** | **FAIL → PASS** |
| 14 | `B.moving__delta_speed` | FAIL | **FAIL** | same (M10) |
| | **totals** | **7 PASS / 7 FAIL** | **9 PASS / 5 FAIL** | 4 changes |

Full gate-by-gate diff for every cell: `compare.txt`. Scoreboards:
`scoreboards/scoreboard_matte14.{json,md}` (all 14) and
`scoreboards/scoreboard_new7_cells.{json,md}` (just the seven flown here).

**Read the comparison with this caveat.** The matte side is 4 repeats per cell on a
quiet laptop with a pinned toolchain. The mirrored side is the Sep 11 suite: mostly
**2 repeats**, a different day, a different machine state, and — for the C/D/E/F cells
— no controlled mirrored arm was re-flown here. The stability run *did* fly a matched
mirrored control for its seven cells; mine has none. So for cells 1, 2, 7, 8, 12, 13, 14
the mirror↔matte comparison is controlled; for cells 3, 4, 5, 6, 9, 10, 11 it is a
before/after against uncontrolled history. Every conclusion below is hedged accordingly.

### What moved, by theme

**Distance keeping, fixed (cells 1, 2, 13).** All three FAIL → PASS changes are the same
story and it is the stability run's result, now visible in the full scoreboard. Across
all seven cells that have an M7 gate, `M7_dist_err_settled_mean_m` falls from a mirrored
**0.669–1.225 m** to a matte **0.110–0.526 m**, and `M7_final_in_band` goes 0.0 → 1.0
everywhere it was failing. The drone stops parking 1.3–1.65× too far away. Held distance
across the five `B.moving` cells is now **2.10–2.43 m** and `A.static__proven` holds
**1.97 m** against a 1.94 m target.

**The person-free control cells are unchanged and slightly safer (cells 3, 5, 9, 11).**
`C.empty` and `E.furniture` still track 0.0%, drift 0.00 m, and log zero false follows on
both floors. Peak confidence on a person-free scene — the number that decides how much
room there is before the 0.70 latch rule fires — **improved** on three of four:

| cell | mirrored | matte |
|---|---|---|
| `C.empty__ships` | 0.5915 | **0.4985** |
| `C.empty__proven` | 0.6405 | **0.5100** |
| `E.furniture__ships` | 0.6165 | **0.4355** |
| `E.furniture__proven` | 0.4265 | 0.4640 (slightly worse, 0.24 below the threshold) |

The Sep 11 report singled out `E.furniture__ships` as "still passing, with less room"
at 0.617. On the matte floor it has 0.265 of margin instead of 0.083. That is the
mirror's fake extra height coming off the furniture too.

---

## 4. `F.pets__ships` — does the drone still chase the dog?

**Short answer: it mostly stops.** The long, confident latch is gone; what remains is a
series of brief flickers that nudge the drone forward under a metre. The M6 gate still
fails, so the cell's verdict is unchanged, but the behaviour behind it is different.

Per flight, matte (4 repeats) against mirrored (the 2 Sep 11 repeats):

| | drift **M6** (m) | tracked **M1** | episodes | first latch (s) | conf at first latch | total latched (s) | drift *within* an episode (m) | range to dog at end (m) |
|---|---|---|---|---|---|---|---|---|
| **mirror** r1 | 2.301 | 68.4% | 1 | 0.31 | 0.705 | 14.44 | 2.082 | 0.80 |
| **mirror** r2 | 2.666 | 78.5% | 1 | 0.31 | 0.874 | 15.86 | 2.502 | 0.44 |
| **matte** r1 | **0.927** | 19.3% | 6 | 1.10 | 0.729 | 3.59 | 0.159 | 2.03 |
| **matte** r2 | **0.408** | 7.9% | 4 | 1.10 | 0.756 | 1.25 | 0.024 | 2.49 |
| **matte** r3 | **0.802** | 18.1% | 5 | 0.63 | 0.804 | 3.45 | 0.215 | 2.16 |
| **matte** r4 | **0.574** | 9.3% | 6 | 1.41 | 0.767 | 1.25 | 0.017 | 2.34 |

(The scoreboard's headline M6 is the **worst** repeat: 2.666 m mirrored, **0.927 m**
matte. All flights start 2.63–2.64 m from the dog.)

Answering the three questions as asked:

**Does it still chase the dog?** Not in the way it did. On the mirror the drone latched
once and stayed latched for the whole flight, closing from 2.64 m to **0.44–0.80 m** —
it crossed the room and ended up on top of the animal. On matte it never closes: it ends
**2.03–2.49 m** away, having moved 0.41–0.93 m from where it started. Time latched onto
the dog falls from 14.4–15.9 s to **1.25–3.59 s**, and time tracking from **68–78% to
8–19%**.

**How fast does it confirm?** Slower and less reliably. First false-follow moves from
**0.31 s on both mirrored flights** to **0.63, 1.10, 1.10, 1.41 s**. Confidence at that
first latch is comparable (0.729–0.804 matte vs 0.705/0.874 mirrored) — when it does
latch, it latches for the same reason; it just takes 2–4× longer to get there and lets go
almost immediately. Note the episode count goes **up**, 1 → 4–6: the matte behaviour is
*more* flickery, just far less consequential per flicker.

**How far does it drift?** **0.408, 0.574, 0.802, 0.927 m**, against **2.301 and 2.666 m**
on the mirror — a 2.9× reduction on the worst repeat. Against the 0.5 m hard gate, one
of four matte flights passes and three fail. So `F.pets__ships` is still a **FAIL**, on
the same gate, with a much smaller violation.

Two details worth not glossing over:

* **The remaining drift is accumulated, not a single approach.** Within any one
  false-follow episode the drone moves **0.017–0.215 m**; the worst flight's 0.927 m is
  the sum over six of them. In `F.pets__ships__r1a1`, 29 of 150 logged frames carry a
  non-zero forward command, clustered into short bursts; the last of them is at
  t = 13.6 s with the drone 0.811 m from its start, after which it coasts a further
  **0.110 m over 9.7 s** with every command at zero. So most of the 0.93 m is genuinely
  commanded travel and about 0.11 m is momentum — not, as an earlier draft of this
  section claimed, mostly coasting. What changed against the mirror is not that the
  drone stopped being commanded forward, but that it is commanded forward in brief
  uncorrelated bursts instead of one continuous 15-second pursuit.
* **The detector's read of the dog changed, which is the mechanism.** Pooled over the
  flown frames:

  | | median conf | max conf | size buckets seen |
  |---|---|---|---|
  | mirror r1a1 | 0.793 | 0.974 | 12 × b0, 119 × b1, 5 × b2 |
  | matte r1–r4 | 0.497–0.543 | 0.825–0.918 | b0 and b1 only, roughly half each |

  On the mirror the dog sat **above** the 0.70 latch threshold most of the time and
  occasionally read as bucket 2 — i.e. as a large, close, person-shaped object. On matte
  its median confidence sits **below** the threshold and it never reaches bucket 2. A
  0.65 m dog plus its reflection was a 1.3 m object; a 0.65 m dog is not.

**This does not choose between champion and confuser, and nothing here should be read as
advocating either.** That is a pending team decision. What this run does is replace the
mirrored numbers the decision would have been made on: the closed-loop consequence of the
champion model's pet false alarms, measured without the mirror, is 4–6 brief latches and
0.41–0.93 m of drift — not one sustained chase across the room. Whether that is
acceptable, and whether the confuser's lower per-frame rate (11.0% vs 30.2%) buys enough
to be worth its cost, is not decided by this data and I am not deciding it.

---

## 5. What got worse — `D.occlusion__proven` changed category

**This is the one result that moved the wrong way, and it flipped a verdict: PASS →
FAIL.**

```
M9_gt_visible_to_relatch_s    mirrored 0.4705 s  ->  matte 3.2405 s   (gate: <= 1.0 s)
```

Per flight, matte: 2.641, 2.974, 3.507, 4.313 s. Mirrored (2 flights): 0.332, 0.609 s.

The gate measures the time from the target being continuously visible in ground truth
until the track re-latches. Three things are true at once and all three belong in the
record:

**(a) The drone is blind *less* on matte, not more.** Total track outage falls from
8.478 / 9.255 s (mirrored, one 8.46–8.48 s blackout each) to 4.63–5.89 s spread over
four to six short losses, and `M1_tracking_fraction` **rises** from 0.764–0.783 to
**0.851–0.890**. Mean pointing error improves, 3.94° → 3.29°. By every aggregate measure
this cell tracks better on the matte floor.

**(b) The blindness moved to a place the gate punishes, because the geometry changed.**
The scene's partition is a box centred (2.2, −0.95) with half-extents (0.05, 0.45), so it
spans y ∈ [−1.40, −0.50] at x = 2.20; the target stands at (3.5, −1.6). Whether the
partition hides anything depends on where the drone is: the sight line from (px, 0) to
the target clears the partition edge once **px > 1.609 m**. Measured
(`occlusion.txt`, `scripts/occlusion_geometry.py`):

| | max px reached | range held at end | sight line CLEAR during lost-track frames | conf while lost (median) |
|---|---|---|---|---|
| mirror `__proven` r1a1 | 1.43 m | 2.86 m | **0.0%** | 0.132 |
| matte `__proven` r1–r4 | 1.91–2.13 m | 1.91–2.38 m | **97.1–98.2%** | 0.424–0.644 |
| matte `__ships` r1–r4 | 1.01–1.36 m | 2.90–3.09 m | 0.0–11.0% | 0.135–0.164 |

On the mirror the drone never got past 1.43 m, so the partition worked as designed and
the loss was a genuine blackout (confidence 0.132). On matte the `__proven` drone closes
to ~2 m — **which is the whole point of the fix** — and from there it can see past the
partition edge. Ground truth then calls the target visible for essentially the entire
outage, so the scorer charges the whole thing to relatch time.
`D.occlusion__ships` does *not* close in that far (himax + 6.5 Hz keeps it at 2.90–3.09 m),
which is exactly why it still passes at 1.329 s.

> **RETRACTED 2026-09-12, the same night, by the static range sweep this section
> asked for: `docs/eval_results/2026-09-13-rangesweep-petsab/`.**
>
> **There is no close-range detection falloff.** A sweep of 1.0–4.0 m in 0.25 m
> steps, 2 subjects, 5 yaw offsets, 3 camera heights, both cameras and *both*
> backends (3,120 frames) found that on the very cutout this cell flies, exactly
> **1 frame in 1,560 falls below the 0.70 latch threshold, and it is at 3.75 m**.
> Mean confidence at ≤2.0 m is *higher* than at 2.5–3.0 m on all four arms.
>
> **The table below is produced by a bug and must not be quoted.** `conf_vs_range.py`
> joins the follower's `t` column to the truth log's `sim_t`; those origins differ by
> up to −19 s and the offset drifts. Since the target sways ±1.6 m with a 24 s period,
> the join misplaces it by 1.25 m on average and 3.12 m at worst. Re-joined on the
> wall clock that both files carry, the trend **reverses**: 92.9% / 86.3% / 71.6%.
> The printed bin labels are also 0.25 m low.
>
> **What actually costs the detections is viewing azimuth off the flat subject card.**
> Confidence is flat out to about 35° and collapses past about 40°. Scene `s07`
> couples azimuth to range by construction (target at 3.5, −1.6 with the drone on
> y≈0, so closing to px 2.0 m means viewing at 46.8°). In the flight logs, 79.0% of
> lost-track frames are at azimuth ≥40° against 5.5% of tracked frames, at the same
> mean range. **Important limit:** a flat card foreshortens to nothing at 45° and a
> real person does not, so this is a scene-fidelity artefact — and equally it is
> *not* evidence that the network is fine on real people at 45°.
>
> Anyone reusing `conf_vs_range.py`, or any other analysis joining `t` to `sim_t`,
> should re-check it. The sight-line geometry in (b) above uses a different join and
> still stands.

**(c) ~~But it is not only a bookkeeping artefact — the detector really does lose a
plainly visible person.~~ WITHDRAWN, see the note above.** `occlusion_proven_lost_track_in_plain_view.png` is frame 241 of
`D.occlusion__proven__r4a1`, mid-outage: the person is unoccluded, upright, centred and
filling most of the frame, and the overlay reads `person 0.56 none | size 2`. Thirty
frames later it reads `0.26 | size 0`. Confidence sits at 0.42–0.64 for seconds without
clearing the 0.70 × 3-frame latch rule. Binned by true range over all four matte flights
(`conf_vs_range.txt`):

```
range 2.5-3.0 m   n=824   mean conf 0.911   92.5% of frames >= 0.70
range 2.0-2.5 m   n=811   mean conf 0.806   73.6%
range 1.5-2.0 m   n=189   mean conf 0.686   54.0%
```

Confidence on this subject falls off monotonically inside 2.5 m. The mirror was keeping
the drone at 2.86–2.92 m, i.e. permanently outside the range band where the network
struggles. **Removing the mirror did not create this weakness; it removed the thing that
was hiding it.**

~~I did not separate (b) from (c).~~ **Resolved the same night.** The static range
sweep this paragraph called for was run, and it removed (c) entirely: there is no
close-range weakness. The relatch failure is (b), the sight line clearing the
partition, plus viewing azimuth off a flat card — not a detector limitation.
See `docs/eval_results/2026-09-13-rangesweep-petsab/`.

### Other things that got worse, none of which changed a verdict

* **`M10_uncertain_fraction_present` rose on every `B.moving` cell** and broke its 0.05
  gate on three of them: `B.moving__proven` 0.0 → 0.0599, `B.moving__delta_backend`
  0.0125 → 0.1071, `B.moving__delta_speed` 0.0 → 0.0725. These are stability-run cells,
  already reported there; they are listed here because in the merged scoreboard they are
  now the *only* reason three cells fail — every distance gate they used to fail now
  passes.
* **`B.moving__delta_backend` tracking fell** 0.9935 → 0.9235, breaching its 0.95 gate.
* **`E.furniture__proven` peak confidence rose slightly**, 0.4265 → 0.4640. Still far
  from the 0.70 latch threshold; the only one of the four person-free cells to move the
  wrong way.
* **One `D.occlusion__ships` flight reached 28.59° worst pointing error**, against
  13.81/13.87° on the two mirrored flights. The other three matte flights sit at
  12.12/13.57/15.19°, right where the mirror did. With only two mirrored repeats I
  cannot say the mirror never did this; treat it as one outlier in four, not a shift.
* **`F.pets__ships` false-follow *episodes* rose** 1 → 4–6, as covered in §4. More
  flickers, far less drift per flicker.

---

## 6. Reproducing

Run from this directory with `/Users/saimaruvada/Downloads/drone/trainenv/bin/python`
(there is no bare `python` on PATH).

| script | what it does | runtime |
|---|---|---|
| `scripts/make_plan.py OUT.tsv --repeats 4` | builds the order-decorrelated plan; prints the balance checks | instant |
| `scripts/fly_plan_matte.sh PLAN OUT SCENE_ROOT [START]` | flies it one flight at a time, load sampled around each, floor re-asserted per flight | ~27 min |
| `scripts/analyze.py OUT` | upset scan, machine table, per-speed-class step-gap summary | instant |
| `scripts/score_merged.sh WORK` | merges both matte halves into one suite and scores it with the unmodified `scoreboard.py` | ~1 min |
| `scripts/compare_to_mirror.py SCOREBOARD.json` | the 14-cell verdict table and every gate that moved | instant |
| `scripts/occlusion_geometry.py MERGED_RUNS MIRROR_RUNS` | sight-line geometry behind the `D.occlusion__proven` flip | instant |
| `scripts/conf_vs_range.py RUN_DIR...` | confidence binned by true range to the target | instant |

The floor check as a one-liner:

```bash
cd /Users/saimaruvada/Downloads/drone/pytorch_ssd/tools/crazysim_macos
for s in s02_control_empty s07_occlusion_reappear s16_furniture_only s03_pets_only; do
  printf '%-24s manifest=%s  xml=%s\n' "$s" \
    "$(/Users/saimaruvada/Downloads/drone/trainenv/bin/python -c \
        "import json;print(json.load(open('scenes_v2/$s/manifest.json'))['room']['floor_reflectance'])")" \
    "$(grep -o 'reflectance=\"[^\"]*\"' scenes_v2/$s/scene.xml)"
done
```

### What is in here

* `plan.tsv`, `plan_balance.txt` — the flight plan and its realised balance checks
* `flights.jsonl` — one record per flight: order, cell, repeat, verdict, timestamps, load
  before and after, `sim_wall_ratio`, `processed_hz`, `step_gap_ms`
* `flights_scanned.json` — the same, plus the per-flight attitude/upset scan
* `runs/` — 28 run directories: `cell.json`, `check.txt`, `follow_log.csv`,
  `metrics.json`, `summary.json`, `truth.csv`, `camera_model.json`, and
  `floor_reflectance.txt` (the value the harness read from the scene it flew)
* `scoreboards/` — the 7-cell and the complete 14-cell scoreboards, JSON and Markdown
* `analysis.txt`, `compare.txt`, `occlusion.txt`, `conf_vs_range.txt` — printed output of
  the analysis scripts
* `code_hashes_before.txt`, `code_hashes_after.txt` — the pin, and the proof it held
* `progress.log` — the live flight log
* two PNGs — the matte floor with no reflection under the pets, and the moment
  `D.occlusion__proven` loses a person standing in plain view

Camera snapshots (the other ~700 frames) were left in scratch and not published.

**State left behind: none.** `tools/crazysim_macos/scenes_v2/` is untouched and still
matte. No tool, scene, or committed result was modified; the merged suite was scored on
copies; nothing was committed or pushed. The workstream lock was taken before the first
flight and released at the end.

---

## 7. What this establishes, and what it does not

**Established:**

* A **complete 14-cell matte baseline now exists**: 56 flights, 4 repeats per cell, one
  scoreboard, both halves flown by byte-identical tooling. **9 PASS / 5 FAIL**, against
  the mirrored suite's 7/7.
* **Removing the mirror fixes distance keeping** in every cell that measures it — three
  cells flip FAIL → PASS on M7 and nothing regresses on distance.
* **The dog chase largely stops.** Drift 2.301/2.666 m → 0.408–0.927 m; time latched
  68–78% → 8–19%; final range to the dog 0.44/0.80 m → 2.03–2.49 m. `F.pets__ships` still
  fails M6 on three of four flights.
* **The person-free controls are unchanged and mostly have more margin** on the latch
  threshold.
* **Flight stability is fine.** 0 upsets in 28 more matte flights; 0 in 56 matte flights
  across both runs.
* **Closing the distance exposes a close-range detection weakness** in
  `D.occlusion__proven`, which flips PASS → FAIL on the M9 relatch gate.

**NOT established — what I did not prove:**

* **Anything about real hardware.** No real camera, no real Crazyflie, no lab. Every
  frame here is rendered. The lab session is still the first test of any of it.
* **A controlled mirror↔matte comparison for these seven cells.** I flew the matte arm
  only. The mirrored side is the Sep 11 suite — different day, different machine state,
  mostly 2 repeats. The stability run's seven cells *do* have a matched mirrored control;
  mine do not. Differences on cells 3, 4, 5, 6, 9, 10, 11 are before/after, not A/B.
* **Why `D.occlusion__proven` fails.** I showed the geometry changed (97–98% of lost-track
  frames now have a clear sight line, against 0% on the mirror) *and* that confidence
  falls off inside 2.5 m *and* that the person is visibly unoccluded in the failing
  frames. I did not separate the scene-geometry effect from the range effect. **Which
  dominates is undetermined.** A static range sweep on an unoccluded scene would settle
  it and takes minutes.
* **Whether `F.pets__ships`'s remaining 0.93 m is a real chase.** Within-episode drift is
  0.017–0.215 m and the drone keeps coasting with zero command, so M6 is partly measuring
  momentum. I did not separate commanded travel from coast.
* **That 4 repeats bound the pets behaviour.** Drift spans 0.408–0.927 m across four
  flights — a 2.3× spread. One of four passes the gate. More repeats would tighten it.
* **Anything about the champion-vs-confuser choice.** Deliberately untouched. This run
  replaces the mirrored closed-loop numbers that choice would have rested on; it does not
  make the choice, and no recommendation either way should be read into it.
* **That `reflectance = 0` is right.** Unchanged from the root-cause report: 0 is a
  judgement about real indoor floors, not a measurement.
* **The himax residual.** `__ships` cells still hold further out than `__proven` ones.
  Still needs real frames.

---

## 8. Recommendations (not implemented — nothing under measurement was edited)

1. **Treat `scoreboards/scoreboard_matte14.json` as the baseline** and stop quoting the
   Sep 11 numbers. The Sep 11 README already carries a correction banner; it should now
   also point here for the replacement figures.
2. **Fix the `D.occlusion__reappear` scene before reading its FAIL as a detector
   regression.** The partition was sized for a drone parked at ~2.9 m and no longer
   occludes anything from ~1.6 m. Widening it, or moving the target, would restore the
   question the cell was built to ask. *Then* re-fly, and whatever still fails is real.
   Owner: `scene_defs/s07_occlusion_reappear.json`; not edited here.
3. **Run the static range sweep.** Bin detection confidence against range on one
   unoccluded scene with the drone commanded to fixed stand-offs. It is the missing
   control for §5 and it is minutes of compute. If confidence really does collapse inside
   2.5 m, that is a finding about the shipping model that matters far more than one
   scene's verdict — and it is invisible in any suite where the mirror kept the drone far
   away.
4. **Re-fly `F.pets__ships` with more repeats before the champion/confuser meeting.**
   Four flights give 0.408–0.927 m against a 0.5 m gate; the decision deserves a tighter
   interval than "one of four passes". Split commanded travel from coasting while you are
   there.
5. **Read `step_gap_ms.max` per speed class in future suites.** The 153 ms chip rate cap
   puts every chip-speed flight above the stability run's 158 ms threshold by
   construction. Recorded here as two separate distributions for that reason.
6. **The `M10_uncertain_fraction_present` regression on the `B.moving` cells is now the
   sole remaining cause of three of the five failures.** Everything else about those
   cells passes. It is the highest-value next thing to look at in the suite.
