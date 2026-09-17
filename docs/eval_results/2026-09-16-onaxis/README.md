# Turn the person to face the drone and it follows twice as many of them

104 flights, 2026-09-16, all VALID. Simulation only. One hang on the watchdog,
re-flown and valid, the same 1% rate the other suites saw.

## What changed, and only what changed

`s15_static_offset` puts the person at 3.6401 m and **-15.945 degrees**. These
flights put the same thirteen people at **3.6401 m and 0.000 degrees**. The range
is held to four decimals. Bearing is the only variable, which is the mirror of
`2026-09-15-deadlock`, where bearing was held and range varied.

Everything else is the people-plural suite unchanged: same subjects, same scene,
same ships-as configuration, same shipped 0.75 / 0.45 / 3 latch rule asserted on
every flight, same harness, eight repeats.

## The result

| subject | index | off axis latch | off M1 | on axis latch | on M1 | change |
|---|---|---|---|---|---|---|
| 374369 | 90.3 | 0/8 | 0.000 | **8/8** | **0.990** | **+0.990** |
| 266409 | 92.1 | 3/8 | 0.098 | **8/8** | **0.990** | **+0.892** |
| 401446 | 88.8 | 1/8 | 0.106 | **8/8** | **0.990** | **+0.884** |
| 161875 | 87.0 | 0/8 | 0.000 | **8/8** | 0.613 | +0.613 |
| 61747 | 86.8 | 8/8 | 0.722 | 8/8 | 0.991 | +0.268 |
| 556158 | 93.9 | 8/8 | 0.879 | 8/8 | 0.990 | +0.112 |
| 280779 | 92.7 | 8/8 | 0.986 | 8/8 | 0.987 | +0.001 |
| 250127 | 52.1 | 0/8 | 0.000 | 1/8 | 0.007 | +0.007 |
| 356427 | 37.8 | 0/8 | 0.000 | 0/8 | 0.000 | 0.000 |
| 157365 | 34.6 | 0/8 | 0.000 | 0/8 | 0.000 | 0.000 |
| 527750 | 34.3 | 0/8 | 0.000 | 0/8 | 0.000 | 0.000 |
| 124442 | 28.4 | 0/8 | 0.000 | 0/8 | 0.000 | 0.000 |
| control | 99.2 | 8/8 | 0.991 | 8/8 | 0.990 | -0.000 |

Pooled over the twelve screened subjects:

| | latch rate | median M1 | subjects acquirable |
|---|---|---|---|
| off axis, -15.9 deg | 28/96 = 0.292 [0.203, 0.393] | 0.000 | 5 of 12 |
| on axis, 0.0 deg | 57/96 = 0.594 [0.489, 0.693] | **0.963** | **8 of 12** |

**Six subjects improved. None got worse.** The other six were already at the
ceiling or are genuinely hard.

## What this settles

`2026-09-16-protocol-geometry` measured, on 13,003 rendered frames, that these
subjects clear the confidence bar on axis. That was a claim about confidence, and
confidence is not tracking: the follower has hysteresis, a three-frame
confirmation, and a control law that only moves once it latches. This flies it,
and the confidence gain does convert.

So the headline of `2026-09-15-people-plural`, a 29% standing latch rate with a
median tracking fraction of 0.000, is substantially a property of that scene's
camera pose. At the same range with the person in front of the drone it is 59%
and 0.963.

That number is still what the drone did on that scene. It was never a statement
about what the network can see, and reading it as one was my error.

## The part that does not move

124442, 527750, 157365 and 356427 are at exactly 0.000 in both conditions, and
the rendered grid puts them at exactly 0.000 frames above the bar on axis at
3.5 m too. Four of the twelve are hard in a way no camera pose fixes. That is the
residue of the original finding and it survives intact.

## A nonlinearity worth knowing

The rendered grid's fraction-of-frames-above-the-bar predicts **whether** a
subject can be acquired, but tracking fraction is a much steeper function of it:

| grid frac above bar, on axis 3.5 m | flown M1, on axis |
|---|---|
| 0.450 (250127) | 0.007 |
| 0.950 (161875) | 0.613 |
| 1.000 (four subjects) | 0.990 |

A subject clearing the bar on 45% of frames tracks essentially never. One
clearing it on 95% tracks 61% of the time. Being above the bar most of the time
is not enough, because the exit rule drops the track whenever confidence falls
under 0.45 and re-acquiring costs three more consecutive frames. Anyone reading
the grid as a tracking prediction will overestimate.

## Limits

Rendered cutouts on opaque cards, harder than the photographs they come from, so
this is still a lower bound on real people. Still one pose per condition, just a
better one; the honest conclusion is that the standing scene was a poor choice of
geometry, not that the drone follows people well. Eight repeats of a standing
cell still differ only by sensor noise, as `2026-09-16-one-frozen-pose` records,
so the intervals above are narrower than the independence they assume. Nothing
here was measured on hardware.
