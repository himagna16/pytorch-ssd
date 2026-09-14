#!/usr/bin/env python3
"""Append the 2026-09-14 matte re-measurements to the scene_defs text fields.

TEXT FIELDS ONLY: subject notes, prediction.rationale, purpose. Nothing else in
the JSON is touched; the files round-trip byte-identically through
json.dumps(indent=2) so the diff is exactly the appended text. Old claims are
kept verbatim; the new text is appended after them.

Numbers come from probes/single_subject_probe.txt (single-subject / path /
walk-in probes) and probes/scene_preview_summary.tsv (build_scene.py --preview
whole-scene probe, rebuilt 2026-09-14 on floor_reflectance 0.0). Probe key:
  float/clean = champion float net (successor_qat_ep3_eval.pth) through
                build_scene.py --preview's own preprocessing (what __proven flies)
  chip/clean  = firmware preprocess + model_id_dory.onnx (doryenv)
  */himax     = same nets after camera_model himax_typical, mean of 2 draws
                after 20 AE-settle frames (what __ships flies)
Bars: the notes were written against --vis-enter 0.70; 0.75 ships since 2026-09-13.
"""
import json
from pathlib import Path

DEFS = Path("/Users/saimaruvada/Downloads/drone/pytorch_ssd/tools/crazysim_macos/scene_defs")
TAG = "MATTE 2026-09-14"
KEY = ("[probe key: float/clean = champion float net via build_scene.py --preview preprocessing; "
       "chip = firmware preprocess + model_id_dory.onnx; himax = himax_typical camera, mean of 2 draws; "
       "single-subject probe = this cutout alone, static, straight ahead, camera on the eye line; "
       "full tables in docs/eval_results/2026-09-14-scene-notes]")
BAR = "Bar: these notes were written against --vis-enter 0.70 on the 20%-reflective floor; 0.75 ships since 2026-09-13."

EDITS = {
    "s01_control_moving": [
        (("prediction", "rationale"),
         f" {TAG}: no probe-number claims here; the '2.7 deg / 99.6%' baseline in purpose is a Sep 10 flight on the "
         f"mirrored floor and is NOT re-derived here (matte flights live in docs/eval_results/2026-09-13-matte-baseline "
         f"and 2026-09-14-baseline-075). Static matte probe of this person: whole-scene preview 0.980/1.000/0.996 at "
         f"3.0/2.0/1.0 m; single-subject float/clean 1.000/0.992/0.975 at 2.0/3.0/3.5 m, chip/clean 0.998/0.973/0.946, "
         f"himax at 3.0 m 0.964 float / 0.943 chip - above the 0.75 bar everywhere. {BAR} {KEY}"),
    ],
    "s02_control_empty": [
        (("prediction", "rationale"),
         f" {TAG}: 'peak confidence <= 0.64 at chip speed' is a mirrored-floor FLIGHT number, not re-flown here. "
         f"Static matte preview with nothing in view (subject behind the drone): float/clean 0.303/0.340/0.423 at "
         f"cam x 0/1/2 m - below both the old 0.70 and the shipped 0.75 bar. {BAR} {KEY}"),
    ],
    "s03_pets_only": [
        (("subjects", "subj_dog", "note"),
         f" {TAG}: was 0.999/0.995/0.976 at 1.5/2.5/3.5 m on the mirrored floor (0.70 bar). Matte single-subject: "
         f"float/clean 0.926/0.869/0.526, chip/clean 0.781/0.660/0.536, float/himax 0.797/0.820/0.363, "
         f"chip/himax 0.697/0.780/0.454. Above the 0.75 bar at 1.5-2.5 m on float/clean, below it at 3.5 m on every "
         f"probe. Whole-scene preview at the drone start (dog 2.72 m, cat 2.38 m, both in view): 0.656. {BAR} {KEY}"),
        (("subjects", "subj_cat", "note"),
         f" {TAG}: was 0.944/0.971/0.751 at 1.5/2.5/3.5 m (mirrored floor, 0.70 bar). Matte single-subject: "
         f"float/clean 0.390/0.687/0.300, chip/clean 0.527/0.501/0.246, float/himax 0.454/0.317/0.309, "
         f"chip/himax 0.517/0.392/0.382 - below both bars at every probed range. {BAR}"),
        (("prediction", "rationale"),
         f" {TAG}: 'renders at 0.976-0.999' was measured on the mirrored floor; matte the dog reads 0.53-0.93 by range "
         f"(see subject note), so 'clears the bar almost immediately' is no longer supported by the static probe at the "
         f"dog's 2.7 m start range (0.656 whole-scene). The flight-level finding stands on its own evidence: "
         f"docs/eval_results/2026-09-14-baseline-075 (2 of 4 fresh repeats at 0.75 exceed the pet gate). Premise "
         f"(never chase an animal) holds; the pre-registered 'fails' is weaker than this rationale implies. {BAR}"),
    ],
    "s04_dummies_only": [
        (("subjects", "subj_dummy_tall", "note"),
         f" {TAG}: was 0.692 at 2.0 m, 0.964 at 3.0 m (mirrored floor, 0.70 bar). Matte single-subject float/clean "
         f"0.461 at 2.0 m, 0.730 at 3.0 m (ladder 1.5/2.0/2.5/3.0/3.5 m: 0.298/0.461/0.163/0.730/0.563); chip/clean "
         f"0.549 / 0.749; float/himax 0.250 / 0.332; chip/himax 0.380 / 0.545. At its scene placement (3.0 m) it is now "
         f"BELOW the 0.75 bar on every probe (it would have cleared the old 0.70 on float/clean and chip/clean only). "
         f"Whole-scene preview at the drone start: 0.589. {BAR} {KEY}"),
        (("subjects", "subj_teddy_low", "note"),
         f" {TAG}: was 0.419/0.748/0.683 at 1.5/2.5/3.5 m (mirrored floor). Matte single-subject float/clean "
         f"0.213/0.279/0.309, chip/clean 0.257/0.193/0.243, float/himax 0.343/0.180/0.325, chip/himax "
         f"0.368/0.214/0.393. PREMISE BROKEN for this subject: it no longer reaches the [0.45, 0.75) boundary band at any "
         f"probed range on any probe, so 'should chatter around the boundary' will not happen. Recommendation (not "
         f"made): if a boundary-band dummy is wanted, this cutout cannot supply it; the tall dummy at 3.0 m (0.730 "
         f"float/clean, just under 0.75) is the nearest boundary-band object in the scene. {BAR}"),
        (("prediction", "rationale"),
         f" {TAG}: 'T1 renders 0.964 at 3.0 m' -> 0.730 float/clean (0.749 chip, 0.33-0.55 himax), i.e. below the 0.75 "
         f"bar; 'T2 chatters around the boundary' -> T2 is 0.18-0.39 everywhere. The static probe no longer supports the "
         f"pre-registered 'fails'; treat it as contested until re-flown on the matte floor. Outcome left as registered. {BAR}"),
    ],
    "s05_person_plus_pet": [
        (("prediction", "rationale"),
         f" {TAG}: 'both subjects clear 0.9' was a mirrored-floor statement. Matte single-subject float/clean at "
         f"2.5/3.0/3.5 m: person 0.995/0.992/0.975 (chip 0.957/0.973/0.946) - yes; pet (same dog cutout as s03) "
         f"0.868/0.652/0.528 (chip 0.662/0.659/0.551) - no: under 0.9 everywhere and under the 0.75 bar beyond 2.5 m. "
         f"Whole-scene preview at the drone start (person 3.32 m, pet 2.73 m): 0.968. The scene's question still stands "
         f"but the pet is a weaker competitor on the matte floor. {BAR} {KEY}"),
    ],
    "s06_two_people": [
        (("prediction", "rationale"),
         f" {TAG}: no numeric claims. Matte whole-scene preview 0.961/0.916/0.927 at cam x 0/1/2 m (both people in view "
         f"at 3.6 m and 2.7 m; both outside the model FOV at cam x 2). {BAR} {KEY}"),
    ],
    "s06b_two_people_one_leaves": [
        (("prediction", "rationale"),
         f" {TAG}: no numeric claims. Matte whole-scene preview 0.928/0.923/0.950 at cam x 0/1/2 m. {BAR} {KEY}"),
    ],
    "s07_occlusion_reappear": [
        (("prediction", "rationale"),
         f" {TAG}: no numeric claims. Matte whole-scene preview (t = 6 s, person at 3.5 m) 0.940/0.985/0.999 at cam x "
         f"0/1/2 m. The partition geometry is unchanged. {BAR} {KEY}"),
    ],
    "s08_exit_and_return": [
        (("subjects", "subj_person_target", "note"),
         f" {TAG}: the FOV bound 2.0*tan35 = 1.40 m is arithmetic and does not depend on the floor - holds. Matte "
         f"whole-scene preview at t = 20 s: 0.999/0.973/0.974 at 2.0/1.5/1.0 m. {BAR} {KEY}"),
    ],
    "s08b_exit_and_return_mirror": [
        (("prediction", "rationale"),
         f" {TAG}: no numeric claims (mirror of s08's 1.40 m FOV arithmetic, which holds). Matte whole-scene preview at "
         f"t = 20 s: 0.967/0.968/0.837 at 2.0/1.5/1.0 m. {BAR} {KEY}"),
    ],
    "s09_far_person": [
        (("subjects", "subj_person_target", "note"),
         f" {TAG} re-measurement (the note above was already matte, dated 2026-09-12, but written against the 0.70 bar). "
         f"Walk-in probe = camera fixed at the origin, the subject moved by its own drift joint to each x (the flown "
         f"mechanism): 6.9 m 43 px 0.701 | 6.5 m 45 px 0.654 | 6.0 m 49 px 0.731 | 5.5 m 54 px 0.866 | 5.0 m 59 px "
         f"0.952 | 4.5 m 66 px 0.868 | 4.0 m 74 px 0.956 (float/clean; px by MuJoCo segmentation). 6.9 and 6.5 m "
         f"reproduce the 09-12 numbers exactly; the interior points differ from the 09-12 list (0.853/0.906/0.959/0.925/"
         f"0.933) by up to 0.12 because that list re-placed the card at each x, re-baking its background, whereas the "
         f"drift joint carries the x = 6.9 card. Same walk-in on the other paths: chip/clean 0.801/0.768/0.693/0.890/"
         f"0.941/0.864/0.958; float/himax 0.786/0.806/0.859/0.919/0.963/0.952/0.983; chip/himax 0.744/0.780/0.872/"
         f"0.906/0.953/0.955/0.978. Against the shipped 0.75 bar: the 6.9 m static opening is BELOW the bar on "
         f"float/clean (0.701) rather than 'exactly on' it, but ABOVE it on chip/clean (0.801) and on both himax paths "
         f"(0.79 / 0.74), so which path is flown decides whether the opening confirms; 'confirm no later than ~6.0 m "
         f"(0.853)' is not supported on the walk-in path (6.0 m reads 0.731 float/clean, 0.693 chip/clean, below 0.75); "
         f"'solid by 5.5 m' holds (0.866-0.919 on every probe). The structural limitation stands: 43-44 px is the "
         f"smallest this room can draw the person. {BAR} {KEY}"),
        (("prediction", "rationale"),
         f" {TAG}: the '0.701 ... exactly on the enter threshold' figure reproduces, but the bar is now 0.75, so on the "
         f"float/clean path the opening sits 0.05 below it; chip/clean reads 0.801 at 6.9 m (above). 'No later than "
         f"~6.0 m (0.853)' -> 0.731 on the walk-in path; 'solid by 5.5 m (0.906)' -> 0.866, still above the bar. See the "
         f"subject note. {BAR}"),
    ],
    "s10_near_threshold_person": [
        (("subjects", "subj_person_target", "note"),
         f" {TAG}: was 0.482 at 1.5 m, 0.844 at 2.5 m, 0.994 at 3.5 m on the mirrored floor (0.70 bar). Matte "
         f"single-subject at 1.5/2.5/3.5 m: float/clean 0.628/0.496/0.938, chip/clean 0.616/0.206/0.830, float/himax "
         f"0.735/0.770/0.790, chip/himax 0.750/0.504/0.758 (himax draws at 1.5 m: float 0.729,0.741; chip 0.774,0.726). "
         f"Full float/clean ladder 1.00-4.00 m: 1.00 0.555 | 1.25 0.479 | 1.50 0.628 | 1.75 0.223 | 2.00 0.378 | "
         f"2.25 0.667 | 2.50 0.496 | 2.75 0.763 | 3.00 0.346 | 3.25 0.923 | 3.50 0.938 | 4.00 0.790 - NOT monotone in "
         f"range. Whole-scene preview with the subject at its declared (1.5, 0) at t = T/4: 0.461 at 1.5 m, 0.498 at "
         f"1.2 m, 0.691 at 0.9 m. The 0.778 that a 2026-09-14 verifier reported for the matte build was NOT reproduced "
         f"by any of these probes; the closest is a single chip/himax draw of 0.774 at 1.5 m. PREMISE BROKEN (not "
         f"robust): 'below the enter threshold' holds on the clean paths at 1.5 m (0.63 / 0.62 vs 0.75) but the shipped "
         f"camera puts the same view ON the bar (0.735 float, 0.750 chip, single draws to 0.774) and at 2.0-2.75 m "
         f"himax float reads 0.70-0.77, so a __ships flight can confirm and the 'hover' verdict is not safe; and because "
         f"confidence is not monotone in range, 'approach until you lose them' has no clean crossing. Recommendation "
         f"(NOT made): if the scene must hold a person just below the 0.75 bar on every probe, 1.25 m is the only "
         f"ladder point where all four probes agree (0.479 / 0.256 / 0.519 / 0.491); if it must hold one just above, "
         f"3.25 m (0.923 / 0.776 / 0.792 / 0.808). Re-fly under both cameras before choosing. {BAR} {KEY}"),
        (("prediction", "rationale"),
         f" {TAG}: the subject is no longer reliably below the bar (see subject note: 0.63 clean, 0.74-0.75 himax at "
         f"1.5 m against 0.75), and confidence is not monotone with range, so 'falls through 0.45' may never happen "
         f"cleanly. Premise broken; outcome left as registered pending a matte re-fly. {BAR}"),
    ],
    "s11_backlit_person": [
        (("prediction", "rationale"),
         f" {TAG}: no numeric claims before; the static delta against s01 is now measured. Matte whole-scene preview "
         f"(backlit): 0.381 / 0.717 / 0.984 at 3.0 / 2.0 / 1.0 m versus s01 (default light, same geometry) 0.980 / "
         f"1.000 / 0.996. Single-subject float/clean 0.653/0.480/0.260 at 2.0/3.0/3.5 m, chip/clean 0.684/0.394/0.228, "
         f"himax at 3.0 m 0.361 float / 0.318 chip; silhouette contrast about -75 to -100 DN. At the declared 3.0 m the "
         f"backlit person is below BOTH bars on every probe. {BAR} {KEY}"),
    ],
    "s12_dim_room": [
        (("purpose",),
         f" {TAG}: '~89 distinct levels' holds (89 at every probed range). '~43 DN mean' is the 1.0 m tile (43.4 DN); "
         f"the frame reads 38.5 DN at 2.0 m and 34.6 DN at the declared 3.0 m. {BAR}"),
        (("prediction", "rationale"),
         f" {TAG}: 'subject-vs-background contrast only about +0.6 DN' was measured at the closest tile; matte "
         f"2026-09-14 by segmentation: -0.3 DN at 1.0 m, +5.6 DN at 2.0 m, +9.4 DN at 3.0 m (the panel sits at 43.5 DN "
         f"while the background darkens with range). Static probe, dim light: float/clean 0.961/0.998/0.995 at "
         f"3.0/2.0/1.0 m, chip/clean 0.940/0.998/0.987 (0.75 gate passes at all three), himax at 3.0 m 0.990 float / "
         f"0.979 chip; single-subject float/clean 0.939-0.998 over 2.0-3.5 m. The static probe is comfortably above the "
         f"0.75 bar; the prediction stays 'unknown' only because the scene is unflown and not in the CORE matrix "
         f"(carried caveat: the dark-frame version was retired, see limitations). {BAR} {KEY}"),
    ],
    "s13_clutter_room": [
        (("subjects", "subj_clut_chair", "note"),
         f" {TAG}: was 0.888/0.413/0.674 at 1.5/2.5/3.5 m (mirrored floor, 0.70 bar). Matte single-subject float/clean "
         f"0.643/0.263/0.338, chip/clean 0.611/0.232/0.319, float/himax 0.480/0.228/0.255, chip/himax 0.599/0.223/0.394 "
         f"- below both bars at every probed range on every probe, so 'will sometimes cross the enter threshold' is no "
         f"longer supported by the static probe. In the built scene the chair is outside the model FOV from all three "
         f"preview positions. {BAR} {KEY}"),
        (("prediction", "rationale"),
         f" {TAG}: 'chair measured 0.413-0.888' -> 0.263-0.643 float/clean (max 0.643 at 1.5 m). The chair is no longer "
         f"near-threshold; the basin-capture gate is still meaningful but is not stressed by this object. Whole-scene "
         f"preview at the drone start (person 3.62 m): 0.988. {BAR}"),
    ],
    "s14_target_substitution": [
        (("subjects", "subj_dummy_tall", "note"),
         f" {TAG}: was 0.964 at 3.0 m (mirrored floor, 0.70 bar). Matte single-subject at 3.0 m: 0.730 float/clean, "
         f"0.749 chip/clean, 0.332 float/himax, 0.545 chip/himax - BELOW the shipped 0.75 bar on every probe (it would "
         f"have cleared the old 0.70 on the clean paths). Whole-scene preview at t = 23 s with the person still in view: "
         f"0.886 at the drone start. {BAR} {KEY}"),
        (("subjects", "subj_person_target", "note"),
         f" {TAG}: the FOV bound 3.2*tan35 = 2.24 m is arithmetic and does not depend on the floor - holds."),
        (("prediction", "rationale"),
         f" {TAG}: 'T1 renders 0.964, so ... three consecutive frames above 0.7' -> T1 reads 0.730 float/clean at 3.0 m "
         f"against a 0.75 bar, so the static probe no longer supports 'fails by construction'; whether the track "
         f"transfers is now contested. The documentation purpose (substitution latency, no identity in the architecture) "
         f"is unchanged. Outcome left as registered; recommend re-registering after a matte flight. {BAR}"),
    ],
    "s15_static_offset": [
        (("subjects", "subj_person_target", "note"),
         f" {TAG}: geometry unchanged. The '1.1 deg / closed to 2.3 m' baseline in purpose is a Sep 10 flight on the "
         f"mirrored floor and is NOT re-derived here. Matte whole-scene preview: 0.906 at 3.64 m, 0.845 at 2.69 m "
         f"(cam x 2 puts the person outside the model FOV: 0.319). Same person cutout as s01, whose single-subject matte "
         f"numbers (1.000/0.992/0.975 at 2.0/3.0/3.5 m float/clean) apply. {BAR} {KEY}"),
    ],
    "s16_furniture_only": [
        (("subjects", "subj_clut_chair", "note"),
         f" {TAG}: was 0.888/0.413/0.674 (mirrored floor, 0.70 bar). Matte single-subject float/clean 0.643/0.263/0.338 "
         f"at 1.5/2.5/3.5 m, chip/clean 0.611/0.232/0.319, float/himax 0.480/0.228/0.255, chip/himax 0.599/0.223/0.394 "
         f"- below both bars everywhere, so this is no longer 'the one object that can cross the enter threshold'. "
         f"Whole-scene preview (chair outside the model FOV at all three cams): 0.525/0.126/0.351. {BAR} {KEY}"),
        (("prediction", "rationale"),
         f" {TAG}: 'probed at 0.888 from close range ... could clear 0.70 three frames running' -> 0.643 at 1.5 m "
         f"float/clean (0.611 chip), below the 0.75 bar; the named risk is weaker on the matte floor. The zero-false-"
         f"follow purpose is unchanged. {BAR}"),
    ],
}


def apply(sid, edits):
    p = DEFS / f"{sid}.json"
    raw = p.read_text()
    d = json.loads(raw)
    assert json.dumps(d, indent=2, ensure_ascii=False) + "\n" == raw, f"{sid}: not round-trip safe"
    for path, text in edits:
        if path[0] == "subjects":
            s = next(x for x in d["subjects"] if x["name"] == path[1])
            s[path[2]] = s.get(path[2], "") + text if s.get(path[2]) else text.lstrip()
        elif len(path) == 2:
            d[path[0]][path[1]] = d[path[0]][path[1]] + text
        else:
            d[path[0]] = d[path[0]] + text
    p.write_text(json.dumps(d, indent=2, ensure_ascii=False) + "\n")
    return len(edits)


if __name__ == "__main__":
    import sys
    only = set(sys.argv[1:])
    n = 0
    for sid, edits in EDITS.items():
        if only and sid not in only:
            continue
        n += apply(sid, edits)
        print(f"{sid}: {len(edits)} text field(s) updated")
    print(f"{n} text fields updated across {len(EDITS)} scenes")
