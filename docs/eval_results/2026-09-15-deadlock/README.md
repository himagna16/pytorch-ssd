# Would a drone that creeps forward fix this? Mostly no.

156 flights, 2026-09-15 into 2026-09-16, all VALID. Simulation only.

`docs/eval_results/2026-09-15-people-plural` found that seven of the twelve
screened people are never acquired on the standing scene, and that the follower
commands neither yaw nor forward velocity until it has latched
(`follow_person.py:371-376`). Across those 208 flights, all 109 latches happened
with the drone still at its start pose, so the drone never closes range on its
own. That suggested an obvious fix: let it creep forward while unsure.

This suite tests that fix before anyone builds it. **It would rescue one of the
seven.**

## The design

The same thirteen people on the same standing scene, with the person moved along
the same bearing so the drone starts 1.6, 2.2 or 2.8 m away instead of 3.64 m.
Range is the only geometric variable: generation asserts both the range and the
bearing, and the bearing is held to better than 0.001 deg. Four repeats per cell,
ships-as, shipped 0.75 / 0.45 / 3 latch rule asserted on every flight. The 3.64 m
column below is the people-plural suite's own static arm, eight repeats.

The harness is people-plural's, unchanged. `fly_deadlock.sh` passes it a
different cell list and output directory, so the lock protocol, validity gate and
re-fly rule are the same code.

## Latch rate against start range

Held at least one second, because `ever_latched` counts a single frame.

| subject | index | 1.6 m | 2.2 m | 2.8 m | 3.64 m |
|---|---|---|---|---|---|
| 124442 | 28.4 | 0/4 | 0/4 | 0/4 | 0/8 |
| 527750 | 34.3 | 0/4 | 0/4 | 0/4 | 0/8 |
| 157365 | 34.6 | **4/4** | 0/4 | 0/4 | 0/8 |
| 356427 | 37.8 | **4/4** | 0/4 | 0/4 | 0/8 |
| 250127 | 52.1 | 0/4 | 0/4 | 0/4 | 0/8 |
| 61747 | 86.8 | 4/4 | 4/4 | 4/4 | 8/8 |
| 161875 | 87.0 | 0/4 | 0/4 | 0/4 | 0/8 |
| 401446 | 88.8 | 4/4 | **4/4** | 0/4 | 1/8 |
| 374369 | 90.3 | **4/4** | **4/4** | **4/4** | 0/8 |
| 266409 | 92.1 | 4/4 | 0/4 | 0/4 | 3/8 |
| 280779 | 92.7 | 4/4 | 4/4 | 4/4 | 8/8 |
| 556158 | 93.9 | 4/4 | 4/4 | 4/4 | 8/8 |
| control | 99.2 | 4/4 | 4/4 | 4/4 | 8/8 |

Pooled over the twelve screened subjects, closer is better and the trend is
clean:

| start range | held >= 1 s |
|---|---|
| 3.64 m | 28/96 = 0.292 [0.203, 0.393] |
| 2.8 m | 16/48 = 0.333 [0.204, 0.484] |
| 2.2 m | 20/48 = 0.417 [0.276, 0.568] |
| 1.6 m | 32/48 = 0.667 [0.516, 0.796] |

## Why that pooled trend is not the answer

**The drone cannot get to 1.6 m.** Over the 116 flights that latched and held,
the range it actually settles at has a median of 2.22 m, a 5th percentile of
1.92 m and a minimum of 1.75 m. That is the forward controller driving the
decoded size bucket to its setpoint, and it is where a creep-forward controller
would arrive too. So the column that matters for the proposed fix is 2.2 m, where
the pooled rate is 0.417, not the 1.6 m column at 0.667.

**Take the seven that fail at 3.64 m one at a time.** That is the population the
fix is for.

- **374369** is acquired at 2.8, 2.2 and 1.6 m. Genuinely range-limited. A
  creep-forward controller would rescue it.
- **401446** is acquired at 2.2 and 1.6 m. It is 1/8 at 3.64 m and 0/4 at 2.8 m,
  so it sits near the edge; creeping to 2.2 m would probably rescue it.
- **157365** and **356427** are acquired only at 1.6 m, below where the drone
  will stop. Creeping forward does not reach them.
- **124442**, **527750**, **250127** and **161875** are never acquired at any
  range tested, including 1.6 m. Their problem is not distance.

So of seven failures: one clear rescue, one likely, two that need closer than the
drone will go, and four that are not a range problem at all.

**161875 is the strangest of these.** Index 87.0, never acquired on the standing
scene at any of the four ranges, and yet acquired on 8 of 8 moving flights in the
other suite. The standing scene puts the person at -15.9 deg and the moving scene
opens at +21.5 deg, so something about pose or bearing rather than range is
deciding it. Nothing here explains that and it should not be guessed at.

## What I checked and did not find

Two subjects look non-monotone in range: 266409 is 4/4 at 1.6 m, 0/4 at 2.2 and
2.8, then 3/8 at 3.64; 401446 is 0/4 at 2.8 but 1/8 at 3.64. The static probe in
the fidelity study also dips at its 2.5 m rung for every subject, so I expected to
confirm a real inversion here. **It does not reach significance.** Two-sided
Fisher on the two cells gives p = 0.491 and p = 1.000, and only 2 of 13 subjects
show any inversion at all. At four flights a cell this suite cannot distinguish a
real dip from noise, so the apparent non-monotonicity is not a finding. Whether
the 2.5 m rung in the static probe is an artefact remains open and would need its
own experiment.

## What this means for the project

The deadlock is real as a mechanism and it is not the explanation for why the
drone ignores ordinary people. Letting the drone creep forward while unsure is
still worth doing, it is cheap, and it converts one and probably two of seven
failures into successes. It is not the fix. Four of the seven are not seeing the
person at 1.6 m, which is a perception problem no control law reaches.

That is worth knowing before anyone spends a week on the controller.

## Limits

Simulation only, rendered cutouts, which are harder than real photographs. Four
flights per cell, so a single cell's rate carries a wide interval; the per-subject
verdicts above rest on clean 0/4 and 4/4 separations rather than on marginal
counts. All three near ranges keep the whole body inside the 70 deg crop, the
head-truncation limit for a 1.7 m person being 1.285 m. The moving scene is not
part of this suite, so the 161875 comparison crosses two scenes that differ in
bearing as well as range.
