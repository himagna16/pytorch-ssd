# The M10 line does not need re-deriving. It needs replacing.

2026-09-15. Open item from the 0.75 merge: the M10 clean-camera line of 0.05 was
drawn for the band [0.45, 0.70) and the shipped bar is now 0.75, so the scorer
demotes it to reported outside that band. The task was to re-derive it.

I could not re-derive it honestly, and looking at the data I no longer think the
number is the problem. Four things, in the order I found them.

## What I measured

Every committed flight with a `follow_log.csv`, re-scored through
`scoreboard.metrics_for_run` with `vis_enter` swept from 0.50 to 0.90 and
`vis_exit` held at 0.45. Same in-FOV definition as the scorer, because it is the
scorer's own function. 287 flights had an in-FOV window; 85 of those were flown
on a clean camera, 76 of them class A or B. Scripts in `scripts/`, per-flight
numbers in `sweep.json`, tables in `report.txt` and `holdout.txt`.

## 1. The line's stated basis is not true of moving scenes

The gate's basis string reads "confidence is 0.96-1.0 on essentially every frame
with a real person." The 5th percentile of in-FOV confidence, per flight, clean
camera:

| class | n | median p05 | min | max |
|---|---|---|---|---|
| A static | 19 | 0.891 | 0.299 | 0.950 |
| B moving | 57 | 0.697 | 0.287 | 0.947 |

The basis describes the static scenes. On moving scenes the model spends a real
part of every flight between 0.45 and 0.75, and that is the normal case, not a
defect.

## 2. At the band it was drawn for, it already split the classes

Pass rate against 0.05, clean camera:

| class | bar 0.70 | bar 0.75 |
|---|---|---|
| A static | 1.00 | 0.95 |
| B moving | 0.51 | 0.44 |

Every static flight passes. Half the moving flights fail. A line that one class
cannot fail and another passes by coin flip is not one line.

## 3. The quantity drifted 76x across our own suites, on the same scene

Median M10 at bar 0.70, class B, `s01_control_moving` throughout:

| suite | median M10 |
|---|---|
| 2026-09-11 simv2 | 0.001 |
| 2026-09-12 mirror-refly | 0.016 |
| 2026-09-13 stability | 0.032 |
| 2026-09-14 baseline-075 | 0.076 |

Nothing about the model changed across those four. The floor did: reflectance
went 0.2 to 0.0 when I fixed the mirror floor, and the scene got harder. A line
drawn before that fix does not describe the scenes we fly now, whatever band it
is evaluated at.

## 4. The band count travels badly. The band-free statistic travels well.

Derive a line at the 90% coverage point on two suites, test it on the other two.
Both halves use the same two scenes and the same subject, so this varies
run-to-run noise and nothing else.

| statistic | class | line | holdout coverage |
|---|---|---|---|
| M10 band [0.45, 0.75) | A | 0.033 | 0.80 |
| M10 band [0.45, 0.75) | B | 0.151 | 0.71 |
| p05 in-FOV confidence | A | 0.738 | 1.00 |
| p05 in-FOV confidence | B | 0.549 | 1.00 |

A 90% line that covers 71% of held-out flights is not calibrated. The same
flights, described by a statistic that does not reference the latch rule, hold
their line exactly. `M10_conf_p05_present` is already computed and stored on
every run, so this costs nothing to adopt.

## The metric is worth keeping

M10 at each flight's own bar, against outcomes, clean-camera A and B, n = 76,
Spearman:

| outcome | rho |
|---|---|
| M9 track losses (count) | +0.619 |
| M1 tracking fraction | -0.599 |
| M2 heading error mean | +0.532 |
| M9 longest outage (n=28) | +0.527 |
| M11 yaw reversals/min | +0.425 |
| M11 yaw saturated fraction | +0.054 |

So the thing M10 measures does track how badly a flight goes. That argues
against dropping it, and it is also the reason to be careful with it: a hard
scene produces low confidence and poor tracking together, so M10 is largely a
difficulty proxy and overlaps M1 rather than adding an independent check. It
earns its place as a diagnostic, not as a second opinion.

## What I am proposing

1. Gate on `M10_conf_p05_present`, which does not move when the latch rule
   moves, and keep the band fraction as a reported diagnostic.
2. Separate lines for static and moving. One number for both has never been
   meaningful.
3. Do not set the numbers yet.

Point 3 is the real conclusion. All 76 clean-camera A/B flights come from two
scenes, `s01_control_moving` and `s15_static_offset`, and both use the subject I
showed this week sits around the 98th percentile of detectability. Any line I fit
today encodes that subject exactly as the 0.05 line did. The holdout above tests
run-to-run noise and cannot test the thing most likely to be wrong.

The line becomes derivable once the scene suite spans a representative spread of
subjects. Until then the scorer's current behaviour, reporting M10 rather than
enforcing it, is the right behaviour for the right reason, and the reason is
better stated as "no representative baseline exists" than as "the band moved."

## For the open question about report-only lines

This bears on whether a breached report-only line should fail a verdict, which
came up over the Bayer cell passing at 0.855 tracking. On this evidence, no. A
line that half of one class fails at the band it was drawn for, on scenes whose
difficulty moved 76x under a scene fix, is not evidence of a defect when it is
breached. Fixing the line comes first; enforcing it can follow.
