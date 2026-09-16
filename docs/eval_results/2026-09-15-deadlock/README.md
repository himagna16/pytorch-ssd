# Would a drone that creeps forward fix this? On the clean evidence, once out of seven.

156 flights, 2026-09-15 into 2026-09-16, all VALID. Simulation only.

`docs/eval_results/2026-09-15-people-plural` found that seven of the twelve
screened people are never acquired on the standing scene, and that the follower
commands neither yaw nor forward velocity until it has latched
(`follow_person.py:371-376`). This suite asks whether letting the drone creep
forward while unsure would fix that, by putting the person at 1.6, 2.2 or 2.8 m
instead of 3.64 m.

**This README is the second version.** The first one reached roughly the right
number by an argument that does not hold, miscounted its own subject list, and
missed a rendering discontinuity in the arm carrying its most striking result.
Fifteen independent agents were asked to refute it and fourteen succeeded. §5
lists what changed.

## 1. The part that is solid

`follow_person.py:371-376` assigns yaw and forward velocity only inside
`if vis_state:`; the else branch zeroes both. Across the 208 flights of the prior
suite and the 156 here, **every latch happened with the drone still at its start
pose**: over the 116 held flights in this suite, the largest difference between
the range at the first latched frame and the start range is 0.000 m. The drone
never closes range on its own before acquiring. That is not in dispute.

The forward law, once latched, is also worth stating correctly. `size_value` is
quantised to bucket centres `(bucket + 0.5) / 4` and `--target-size` defaults to
0.625, exactly the bucket-2 centre. So the error term is identically zero across
the whole bucket-2 band and `k_fwd` never acts inside it. This is bang-bang
control at +-0.2 m/s with a wide dead zone, not a controller seeking a setpoint.
The drone halts at whichever edge of the dead zone it entered through. The
nominal 1.94 m hold is never reached.

## 2. The result, counted by subject

The conclusions are stated per subject ("four are never acquired"), so the
statistic should be too. Number of the twelve screened people acquirable at all,
meaning at least one flight holding the track a second or more:

| start range | subjects acquirable | flights held >= 1 s |
|---|---|---|
| 3.64 m | 5/12 | 28/96 = 0.292 |
| 2.8 m | 4/12 | 16/48 = 0.333 |
| 2.2 m | 5/12 | 20/48 = 0.417 |
| 1.6 m | 8/12 | 32/48 = 0.667 |

**The flight-level column looks monotone and the subject-level one is not.** It
falls from 3.64 to 2.8 m and is flat from 3.64 to 2.2 m. The pooled rise at
2.8 m is three subjects moving: 374369 flips 0.000 to 1.000, while 266409 drops
0.375 to 0.000 and 401446 drops 0.125 to 0.000. One better, two worse, nine
unchanged, sign test p = 1.000.

## 3. The seven failures, one at a time

The seven never acquired at 3.64 m are 124442, 527750, 157365, 356427, 250127,
161875 and 374369.

| subject | 2.8 m | 2.2 m | 1.6 m |
|---|---|---|---|
| 374369 | **4/4** | **4/4** | 4/4 |
| 157365 | 0/4 | 0/4 | 4/4 |
| 356427 | 0/4 | 0/4 | 4/4 |
| 124442 | 0/4 | 0/4 | 0/4 |
| 527750 | 0/4 | 0/4 | 0/4 |
| 250127 | 0/4 | 0/4 | 0/4 |
| 161875 | 0/4 | 0/4 | 0/4 |

In the two arms that are geometrically clean, **exactly one of the seven is
rescued**. The two that look rescued are rescued only in the 1.6 m arm, and that
arm has a problem.

## 4. Why the 1.6 m arm cannot carry a verdict

The room's far wall is 4 m tall at x = 7 m, so from a camera at 0.8 m its top
edge falls at image row 42 of 244. Working out where each arm puts the subject's
head:

| start range | subject spans rows | head above row 42? |
|---|---|---|
| 1.6 m | 24.0 to 209.1 | **yes** |
| 2.2 m | 50.7 to 185.4 | no |
| 2.8 m | 66.0 to 171.8 | no |
| 3.64 m | 78.9 to 160.3 | no |

At 1.6 m and only at 1.6 m the subject's head crosses above the wall into the
skybox. The cutout is an opaque card whose padding is painted the wall colour
(158, 158, 168) precisely so it disappears against the wall, and against the sky
it does not. So the 1.6 m arm changes what the network sees in a way that is not
range, and it is the arm in which two of the three rescues appear.

That does not prove the 1.6 m rescues are artefacts. It means this suite cannot
tell, and the arm should not be used to decide whether a controller change is
worth building.

## 5. What the first version of this README got wrong

Fourteen of fifteen refutation attempts succeeded.

1. **The floor argument was invalid.** I wrote that the drone "cannot reach
   1.6 m" because latched flights settle at a median of 2.22 m. That number is
   measured entirely after acquisition, on flights governed by the post-latch
   station-keeping law. A creep controller runs in the branch where forward
   velocity is hard-zeroed, so nothing in the size loop constrains where it would
   stop. Its floor is a design choice. The suite's own data contains a drone
   sitting unlatched at 1.52 m for 3.94 seconds with forward velocity commanded
   at exactly zero throughout (`A.r22__401446__r2a1`), which is below the
   "minimum" I quoted.
2. **I described the forward law wrongly** as driving the size bucket to a
   setpoint. It is bang-bang with a dead zone, and 2.22 m is a quantiser
   artefact.
3. **I listed eight subjects and called them seven.** 401446 is not a 3.64 m
   failure; it holds 21.5 s on one of its eight flights there. Removing it takes
   the count from "one clear rescue and one likely" to one.
4. **I called the trend monotone and clean.** At subject level it is not.
5. **I missed the skybox crossing in the 1.6 m arm**, which is the real reason to
   discount that column, and a better one than the floor argument I used.
6. **I under-claimed on the 2.5 m dip.** I wrote that it "would need its own
   experiment". The experiment is already in the repo and covers all thirteen of
   these subjects: `2026-09-15-sim-person-fidelity/tables/sim_cohort.csv` has 534
   renders per rung over 267 subjects, with median confidence 0.643 at 2.0 m,
   0.420 at 2.5 m and 0.532 at 3.0 m. Binarising 200 frames of graded confidence
   into one bit at the 0.75 bar and then reporting that the bit could not resolve
   the dip measured my choice of statistic, not the data.
7. **The bearing guarantee was 0.002 deg, not the 0.001 I asserted.** The
   generator asserts on six-decimal positions that `build_scene.py` then rounds
   to four before writing the XML, so the assertion guarded a number MuJoCo never
   reads. Physically irrelevant, but the stated guarantee was not the enforced
   one, and it is exactly the failure mode the generator's own comment
   anticipated.

## 6. What this means for the project

On the clean arms, moving the person from 3.64 m to 2.2 m rescues one of seven.
Six of the seven are still not acquired at 2.2 m, and four of them are not
acquired even at 1.6 m. **The deadlock is real as a mechanism and it is not the
explanation for why the drone ignores ordinary people.**

A creep-forward controller is still cheap and still worth building, and there is a
second parameter worth changing alongside it. After latching at 1.6 m the decode
reads bucket 3 and the law immediately commands -0.2 m/s; 157365 and 356427 then
lose the track on the way out, at 1.62 to 1.97 m, while 374369 holds because it
stays detectable out to 2.4 m. So a creep without a closer hold buys a latch that
does not survive. Both are parameter changes to the same few lines.

But the honest headline is that this suite does not establish that creeping
forward helps much, because the one arm where it clearly helps is the one arm
that is not clean.

## 7. Limits

Simulation only, rendered cutouts, which are harder than real photographs. Four
flights a cell, so single cells carry wide intervals; the per-subject verdicts
rest on clean 0/4 and 4/4 separations. The 1.6 m arm is confounded as described.
No rung was flown between 1.6 and 2.2 m, so where the transition sits for 157365
and 356427 is unknown. The moving scene is not part of this suite, so the
161875 comparison below crosses two scenes differing in bearing as well as range.

**161875 remains unexplained.** Index 87.0, never acquired on the standing scene
at any of the four ranges, acquired on 8 of 8 moving flights in the other suite.
Not guessed at here.

## One provenance wart

`suite_meta.json` records `"suite": "people_plural"`. That string is hardcoded in
`fly_pool.sh`, which this suite reuses deliberately rather than forking, and
`fly_deadlock.sh` does not override it. The file is otherwise correct and is
distinguished by `cells: 39`, `repeats: 4` and its `started_utc`. Left as written
rather than edited, because editing a recorded artefact to look tidier is worse
than a wrong label with an explanation next to it.
