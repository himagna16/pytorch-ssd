# 2026-09-14 - scene notes re-measured on the matte floor

Every note in `tools/crazysim_macos/scene_defs/*.json` was written against the
20 %-reflective floor (before 2026-09-12) and the 0.70 enter bar (before
2026-09-13). This pass re-measures every quantitative or threshold-relative
claim on the matte floor (`room.floor_reflectance = 0.0`) against the 0.75 bar
that ships, and appends the result to each scene's text fields. **Nothing but
text changed**: geometry, subjects, motion, lighting, gates and pre-registered
outcomes are byte-identical to `HEAD` (checked structurally, see "How the edits
were made"). Nothing here was flown; every number is a static offscreen render.

## Floor confirmation

`build_scene.py --all --preview` was run at 2026-09-14 16:06 UTC
(`probes/build_all_preview.log`, 18 x `floor reflectance 0`). Every rebuilt
manifest carries `room.floor_reflectance = 0.0`
(`probes/manifest_floor_reflectance.tsv`, read from `scenes_v2/*/manifest.json`).
The single-subject probe asserts the same value on every temp scene it builds.

## Probes (what the numbers in the table are)

| label | what it is | which flight cell it corresponds to |
|---|---|---|
| float/clean | REC601 luma of the render -> centre 244x244 crop -> 128x128 bilinear -> champion float net `successor_qat_ep3_eval.pth`. Identical code path to `build_scene.py --preview`'s probe (`bs.run_model`). | `__proven` |
| chip/clean | `perception_backends.ChipPerception`: firmware `preprocess.c` port + `model_id_dory.onnx` (plain_follow_prod_qat_v3) under doryenv. `gate` = raw[9] >= 5467, i.e. p >= 0.75. | chip path |
| float/himax, chip/himax | same two nets after `camera_model.CameraModel("himax_typical")`, 20 AE-settle frames then 2 independent draws (mean; draws in the .txt) | `__ships` |
| single-subject | the named cutout ALONE (same COCO ids, same `height_m`), static, straight ahead at y = 0, the scene's own lighting, camera on the eye line (x, 0, 0.8) facing +x, stepped so camera-to-subject range takes the quoted values. This is the shape of the numbers the notes quote ("0.482 at 1.5 m"). | - |
| whole-scene preview | `build_scene.py --preview` on the real scene (all subjects, clutter, occluders) at its own `preview_cam_x` and `preview_t` | - |
| walk-in (s09) | real scene, camera at the origin, the subject moved to each x by its own drift joint (the flown mechanism) | - |

Pixel heights are MuJoCo segmentation of the subject's panel geom.
Scripts and raw outputs: `probes/single_subject_probe.py` -> `.txt` / `.jsonl`;
`probes/scene_preview_summary.py` -> `.tsv`; `probes/scene_preview_probes/*.probe.json`.
The `s02_path` block in `single_subject_probe.txt` is INVALID (the camera was
placed behind the back wall) and is not used anywhere; s02 uses the whole-scene
preview instead.

Bars: **0.70** = `--vis-enter` when the notes were written; **0.75** = shipped
since 2026-09-13 (`follow_person.py`, GAP8 raw 5467).

## The table

Old values are as written in the note (mirrored floor, 0.70 bar) unless marked.
Matte values are float/clean unless labelled. Verdict: **holds** (claim still
true against the shipped bar), **corrected** (number or bar-relation changed;
note updated, old value kept), **premise broken** (the scene no longer poses
the question its purpose states), **flight claim** (a flown number that a
static probe cannot re-derive; flagged in the note, not re-flown).

| scene | claim (where) | old value | matte 2026-09-14 | bar assumed | verdict |
|---|---|---|---|---|---|
| s01_control_moving | 2.7 deg mean / 99.6 % tracked (purpose) | Sep 10 flight, mirrored floor | not re-flown; static: preview 0.980/1.000/0.996 at 3/2/1 m; single 1.000/0.992/0.975 at 2/3/3.5 m (chip 0.998/0.973/0.946; himax @3 m 0.964/0.943) | 0.70 -> 0.75 | flight claim; static holds |
| s02_control_empty | "peak confidence <= 0.64 at chip speed" (rationale) | flight, mirrored floor | not re-flown; preview with nothing in view 0.303/0.340/0.423 | 0.70 -> 0.75 | flight claim; static holds |
| s03_pets_only | dog 0.999/0.995/0.976 at 1.5/2.5/3.5 m (note) | mirrored | 0.926/0.869/0.526; chip 0.781/0.660/0.536; himax 0.797/0.820/0.363; chip-himax 0.697/0.780/0.454 | 0.70 -> 0.75 | corrected |
| s03_pets_only | cat 0.944/0.971/0.751 (note) | mirrored | 0.390/0.687/0.300; chip 0.527/0.501/0.246; himax 0.454/0.317/0.309 | 0.70 -> 0.75 | corrected (below both bars everywhere) |
| s03_pets_only | "dog renders 0.976-0.999, clears 0.7 almost immediately" (rationale) | mirrored | whole-scene at start (dog 2.72 m + cat) 0.656; dog by range 0.53-0.93 | 0.70 -> 0.75 | corrected; scene purpose holds (flight evidence: 2026-09-14-baseline-075) |
| s04_dummies_only | T1 0.692 at 2.0 m, 0.964 at 3.0 m (note, rationale) | mirrored | 0.461 / 0.730 (chip 0.549 / 0.749; himax 0.250 / 0.332; chip-himax 0.380 / 0.545); preview at start 0.589 | 0.70 -> 0.75 | corrected: T1 now BELOW the 0.75 bar at its 3.0 m placement; pre-registered "fails" unsupported by the static probe |
| s04_dummies_only | T2 0.419/0.748/0.683 "straddles [0.45, 0.70)" (note) | mirrored | 0.213/0.279/0.309; chip 0.257/0.193/0.243; himax 0.343/0.180/0.325 | 0.70 -> 0.75 | **premise broken** (never reaches the band) |
| s05_person_plus_pet | "both subjects clear 0.9" (rationale) | mirrored | person 0.995/0.992/0.975 at 2.5/3/3.5 m; pet 0.868/0.652/0.528 (chip 0.662/0.659/0.551); preview at start 0.968 | 0.70 -> 0.75 | corrected (pet does not clear 0.9; under 0.75 beyond 2.5 m) |
| s06_two_people | none | - | preview 0.961/0.916/0.927 | - | unchanged |
| s06b_two_people_one_leaves | none | - | preview 0.928/0.923/0.950 | - | unchanged |
| s07_occlusion_reappear | none | - | preview 0.940/0.985/0.999 | - | unchanged |
| s08_exit_and_return | FOV bound 2.0*tan35 = 1.40 m (note) | arithmetic | arithmetic; preview t=20 s 0.999/0.973/0.974 | - | holds |
| s08b_exit_and_return_mirror | none (mirror of s08) | - | preview t=20 s 0.967/0.968/0.837 | - | unchanged |
| s09_far_person | path 6.9/6.5/6.0/5.5/5.0/4.5/4.0 m = 0.701/0.654/0.853/0.906/0.959/0.925/0.933 at 44/47/51/55/60/66/74 px (note, 2026-09-12 matte) | matte 09-12, 0.70 bar | walk-in 0.701/0.654/0.731/0.866/0.952/0.868/0.956 at 43/45/49/54/59/66/74 px; chip 0.801/0.768/0.693/0.890/0.941/0.864/0.958; himax 0.786/0.806/0.859/0.919/0.963/0.952/0.983; chip-himax 0.744/0.780/0.872/0.906/0.953/0.955/0.978 | 0.70 -> 0.75 | corrected (6.9/6.5 reproduce exactly; interior up to 0.12 off; bar moved) |
| s09_far_person | "0.701 sits exactly on the enter threshold" (rationale) | 0.70 bar | 0.701 float/clean = 0.05 BELOW 0.75; chip/clean 0.801 and himax 0.74-0.79 = ABOVE | 0.75 | corrected (path-dependent) |
| s09_far_person | "confirm no later than ~6.0 m (0.853); solid by 5.5 m (0.906)" | 0.70 bar | 6.0 m = 0.731 float / 0.693 chip (below 0.75); 5.5 m = 0.866-0.919 (above) | 0.75 | 6.0 m corrected; 5.5 m holds |
| s09_far_person | 44 px structural floor; not flown; t_start on sim clock (limitations) | - | 43 px at 6.9 m by segmentation; still unflown | - | holds (carried) |
| s10_near_threshold_person | 0.482 / 0.844 / 0.994 at 1.5 / 2.5 / 3.5 m "below the enter threshold" (note) | mirrored, 0.70 | 0.628 / 0.496 / 0.938; chip 0.616/0.206/0.830; himax 0.735/0.770/0.790; chip-himax 0.750/0.504/0.758 (draws at 1.5 m: 0.774, 0.726); whole-scene at declared pos 0.461; ladder 1.0-4.0 m non-monotone (0.555 0.479 0.628 0.223 0.378 0.667 0.496 0.763 0.346 0.923 0.938 0.790) | 0.70 -> 0.75 | **premise broken** (not robust: below on clean, on the bar under himax; no monotone crossing) |
| s10_near_threshold_person | verifier's "0.778 on the matte build" (task brief) | - | NOT reproduced by any probe here; nearest is one chip/himax draw of 0.774 at 1.5 m | 0.75 | unverified |
| s11_backlit_person | none (delta vs s01) | - | preview 0.381/0.717/0.984 at 3/2/1 m vs s01 0.980/1.000/0.996; single 0.653/0.480/0.260 at 2/3/3.5 m, chip 0.684/0.394/0.228; himax @3 m 0.361/0.318 | 0.75 | unchanged premise; delta now recorded (below both bars at 3.0 m) |
| s12_dim_room | "~43 DN mean, ~89 distinct levels" (purpose) | matte? undated | 89 levels at every range (holds); mean 43.4 DN at 1.0 m, 38.5 at 2.0 m, 34.6 at 3.0 m | - | corrected (43 is the 1 m tile) |
| s12_dim_room | "subject-vs-background contrast ~ +0.6 DN" (rationale) | undated | -0.3 DN at 1.0 m, +5.6 at 2.0 m, +9.4 at 3.0 m (segmentation) | - | corrected |
| s12_dim_room | prediction "unknown" | - | static: 0.961/0.998/0.995 at 3/2/1 m, chip gate passes at all, himax @3 m 0.990/0.979 | 0.75 | holds (unknown only because unflown; caveats carried) |
| s13_clutter_room | chair 0.888/0.413/0.674 "will sometimes cross the enter threshold" (note, rationale) | mirrored, 0.70 | 0.643/0.263/0.338; chip 0.611/0.232/0.319; himax 0.480/0.228/0.255; chip-himax 0.599/0.223/0.394 | 0.70 -> 0.75 | corrected; "near-threshold" premise weakened (chair max 0.643) |
| s14_target_substitution | T1 0.964 at 3.0 m -> "three frames above 0.7, fails by construction" (note, rationale) | mirrored, 0.70 | 0.730 (chip 0.749; himax 0.332; chip-himax 0.545): below 0.75; preview t=23 s 0.886 with the person still in view | 0.70 -> 0.75 | corrected; "fails by construction" unsupported (now contested) |
| s14_target_substitution | FOV bound 3.2*tan35 = 2.24 m (note) | arithmetic | arithmetic | - | holds |
| s15_static_offset | 1.1 deg mean, closed to 2.3 m (purpose, rationale) | Sep 10 flight, mirrored | not re-flown; preview 0.906 at 3.64 m, 0.845 at 2.69 m (0.319 when out of FOV) | 0.70 -> 0.75 | flight claim; static holds |
| s16_furniture_only | chair 0.888/0.413/0.674, "could clear 0.70 three frames running from ~1.5 m" (note, rationale) | mirrored, 0.70 | 0.643 at 1.5 m (chip 0.611); preview 0.525/0.126/0.351 (chair outside model FOV) | 0.70 -> 0.75 | corrected; risk premise weakened |

## Premises that no longer hold on the matte floor (recommendations only - nothing changed)

**s10_near_threshold_person.** The note said a person at 1.5 m reads 0.482,
below the bar. Matte, the same view reads 0.628 float/clean and 0.616
chip/clean (below 0.75) but 0.735 float/himax and 0.750 chip/himax (on the
bar; single draws to 0.774), and himax float reads 0.70-0.77 across
2.0-2.75 m. A `__ships` flight of this scene can therefore confirm, so the
pre-registered `hover` verdict is not safe, and the float/clean ladder is not
monotone in range (0.223 at 1.75 m, 0.763 at 2.75 m, 0.346 at 3.0 m, 0.923 at
3.25 m), so "approach until you lose them" has no clean crossing. The 0.778
the task brief attributes to a verifier did not reproduce here. Recommendation:
decide which camera the scene is for, then place the subject where all four
probes agree - 1.25 m is the only ladder point where all four are below the
bar (0.479 / 0.256 / 0.519 / 0.491), 3.25 m the cleanest "just above"
(0.923 / 0.776 / 0.792 / 0.808) - and re-fly under both cameras before
trusting either. Not changed.

**s04_dummies_only (teddy_low).** "Straddles the [0.45, 0.70) band" -> 0.18-0.39
on every probe at every range. This cutout cannot supply a boundary-band
dummy; the tall dummy at 3.0 m (0.730 float/clean, just under 0.75) is the
nearest boundary object left in the scene. The scene's zero-false-follow
purpose still holds; the "T2 chatters" rationale does not.

**s04 (T1) / s14 (same cutout).** T1 at 3.0 m fell from 0.964 to 0.730
float/clean (0.33-0.55 under himax), i.e. from comfortably above the old 0.70
to just under the shipped 0.75. The s04 "fails" and s14 "fails by
construction" pre-registrations are no longer supported by the static probe.
Recommendation: re-fly both on the matte floor and re-register; outcomes were
left as written.

**s09_far_person** keeps its premise (acquisition range, structural 43-44 px
floor) but the bar move changes the story: the static opening (0.701
float/clean) is now below the bar on the `__proven` path and above it on the
chip (0.801) and himax (0.74-0.79) paths. "Confirm no later than 6.0 m" is
not supported on the walk-in path (0.731). Known caveats (never flown, not in
CORE, t_start on the simulator clock, 45 s cell) are already in its
limitations and were left in place.

**s13 / s16 (chair)** and **s03 (cat)** are not "near threshold" any more
(chair max 0.643, cat max 0.687, both float/clean at one range only; below 0.75
on every probe). The scenes remain valid gates; the rationale that named them
as the risk is stale and now says so.

## What was NOT verified

* No flights. Every flown number in the notes (s01, s02, s15 baselines; the
  s03 pet-gate behaviour) is flagged as a mirrored-floor flight claim, not
  re-derived. Matte flight evidence lives in `2026-09-13-matte-baseline` and
  `2026-09-14-baseline-075`, which this pass did not re-analyse.
* The verifier's 0.778 for s10. It is not in any committed report I could grep
  and none of the probes here produced it.
* himax numbers are 2 draws after 20 settle frames, not the 3 draws / 30
  frames of `2026-09-13-rangesweep-petsab`; treat them as +-0.03.
* The s09 interior-path discrepancy (0.853 vs 0.731 at 6.0 m) is explained
  as "re-placed card vs drift-carried card" from the note's own limitation
  text; that mechanism was not isolated here.

## How the edits were made

`apply_notes.py` appends a dated `MATTE 2026-09-14: ...` sentence to the text
field that carries each claim (subject `note`, `prediction.rationale`, or
`purpose`), keeping the old sentence verbatim. Files round-trip byte-identically
through `json.dumps(indent=2)`, so `git diff` is exactly the appended text
(18 files, 29 lines changed, 29 text fields). A structural check
(`HEAD` vs working tree with the three text fields stripped) reports 0
non-text differences, and `build_scene.py --all --check` resolves. Not
committed.

Simulator lock: taken at 11:05 CDT, released at the end of this pass.

## Verification pass (2026-09-14, second agent, independent re-measure)

Scripts and raw output in `probes/verifier/` (`verify_probe.py/.out`,
`placement.py/.out`, `reco.py/.out`, `structcheck.py`, `verbatim.py`). Same
champion checkpoint, same `bs.run_model` preprocessing, same chip backend, same
`himax_typical` camera; probes written from scratch, not by re-running
`single_subject_probe.py`. `build_scene.py --def <s> --preview` was re-run for
s06, s08b, s10, s16. Lock held 11:17-11:3x CDT; offscreen renders only.

**Confirmed.** `HEAD` vs working tree with note/rationale/purpose stripped:
0 non-text differences in all 18 files; 29 text fields changed and in every one
the old text is the verbatim prefix of the new. All 18 `scenes_v2/*/manifest.json`
read `room.floor_reflectance = 0.0` (read directly, not from the tsv).
`build_scene.py --all --check`: OK. JSON round-trips byte-identically. Chip
ran on all 68 rows of `single_subject_probe.jsonl`. Reproduced to +-0.005:
s09 walk-in 0.701/0.654/0.731/0.866 at 6.9/6.5/6.0/5.5 m (chip 0.801/0.768/
0.693/0.890; himax at 6.9 m 0.786 with the agent's seeds, 0.772 with 3 fresh
draws); s12 34.6/38.5/43.4 DN, 89 levels, +9.4/+5.6/-0.3 DN, conf 0.961/0.998/
0.995; s03 dog 0.926/0.868/0.528, cat 0.390/0.687/0.303; s13 chair 0.643/0.263/
0.341; s04 teddy 0.213/0.278/0.313; s05 pet 0.868/0.651/0.528; previews s06
0.961/0.916/0.927, s08b 0.967/0.968/0.837, s16 0.525/0.126/0.351, s10 whole-scene
0.461/0.498/0.691.

**Refuted / corrected (notes amended with a dated `VERIFIER 2026-09-14:` sentence;
old text kept).**

1. *"The verifier's 0.778 did NOT reproduce on any probe."* It does: s10's own
   `scene.xml` at t = 0, subject at its spring extreme (1.5, -0.30), camera at
   the origin, reads **0.778 float/clean, 0.774 chip/clean (gate 1)**, 0.798
   float/himax, 0.810 chip/himax. This pass only sampled t = T/4 (y = 0, 0.461).
   Over one 18 s sway cycle float/clean runs 0.187-0.778 and float/himax
   0.50-0.94 (`reco.out`), so the declared motion alone carries the person
   through the bar on every path. The s10 premise-broken verdict stands and is
   stronger than stated.
2. *Single-subject numbers are placement-dependent.* Same cutout, same 1.5 m
   range, subject at x = 1.5/2.0/2.5/3.0/3.5/4.0/4.5: float/clean 0.461/0.346/
   0.319/0.376/0.450/0.628/0.634 (`placement.out`). The headline s10 "0.628 at
   1.5 m" is the x = 4.0 placement (the ladder parks the cutout at its maximum
   range and walks the camera back); at the scene's declared placement it is
   0.461 float/clean, 0.269 chip/clean, **0.788 float/himax** (5 draws
   0.781-0.794, i.e. above the bar, not "on" it), 0.650 chip/himax. Likewise the
   s04/s14 tall dummy "0.730 at 3.0 m" is the x = 3.5 placement; at its declared
   x = 3.0 it reads 0.560 float/clean, 0.462 chip, 0.449 float/himax, 0.520
   chip/himax (sweep x = 3.0..5.0: 0.560/0.729/0.583/0.655/0.681). The
   agent's numbers are real renders but they are not the scenes' numbers, and
   "just under 0.75" for the dummy is wrong by 0.19-0.30.
3. *s10 recommendation numbers.* Built as recommended (subject at x, camera at
   the origin): 1.25 m = 0.445 / 0.263 / 0.726 (draws 0.700-0.748) / 0.707 -
   still below 0.75 on all four but by 0.02 on himax float; 3.25 m = 0.797 /
   0.537 / 0.861 / 0.767 - **not** above the bar on chip/clean. The quoted
   (0.479/0.256/0.519/0.491) and (0.923/0.776/0.792/0.808) only hold with the
   cutout at x = 4.0. Recommendation direction (pick the camera, re-fly) is
   fine; the specific placements need re-choosing with the camera at the origin.
4. *s14.* In the built scene after the person leaves the FOV (t = 26 and 28 s)
   the dummy reads 0.498 float / 0.434 chip / 0.577 float-himax / 0.517
   chip-himax: the static probe points away from substitution, not "just under"
   it. Conclusion ("fails by construction" unsupported, contested) unchanged.

**Unchanged from the pass above:** everything flagged as a flight claim stays
un-flown; himax numbers here use 5 draws / 30 settle frames (agent: 2 / 20);
the two agree within 0.03 except where noted.
