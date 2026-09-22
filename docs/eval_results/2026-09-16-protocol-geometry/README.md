# Where the person stands in the frame is doing more work than who the person is

> **2026-09-22: RESCORED ON THE CHIP ARM. Read `../2026-09-22-sep16-chip-rescore/`.**
> Most of this page survives on the chip arm: the pose/hard split, the bearing-cost
> shape, the 2.5 m finding, the 3.5 m reference and the mirror check. The 25-degree
> left/right asymmetry does not (+0.059 becomes -0.007). The "second correction"
> below is itself wrong in size: its chip numbers came from a script that ran the
> preprocess twice. The real gap to float is -0.020 mean confidence, not -0.124.

2026-09-16. 13,003 frames, 325 clips, 13 subjects at 5 distances and 5 bearings,
rendered and scored through the same chain tomorrow's real capture will use:
mock streamer, `cpx_grab.py`, `score_real_frames.py`. Built as the reference
table the real frames get compared against, and it changed what the flight
suites mean on the way.

> # SECOND CORRECTION, 2026-09-17: EVERY NUMBER HERE IS THE WRONG NETWORK
>
> `score_real_frames.py` is hardwired to the float arm and has no backend switch,
> while every flight this project has run uses the chip arm. All 13,003 frames
> below were scored float. On the same frames the chip arm gives mean confidence
> 0.5826 against 0.7065 and a fraction above the bar of 0.2989 against 0.5383, and
> 122 of 325 cells move by 0.25 or more, some from 1.000 to 0.000.
>
> **Read `docs/eval_results/2026-09-17-chip-arm-rescore/` instead.** It carries
> both arms for every cell. The subject conclusions, the bearing table and the
> 2.5 m discussion below all need re-reading against the chip column.
>
> # CORRECTION, 2026-09-16
>
> **The bearing comparison in §2 is confounded and the confound scales with
> bearing.** The subject panel is an opaque rectangle and the scene's second light
> is `dir="1 0 -0.3"` with no sideways component, so the card casts a box shadow
> onto the far wall 3.4 m behind it. The shadow keeps the subject's lateral offset
> but lands at greater depth, so it appears displaced toward the image centre in
> proportion to how far off-centre the person stands. At bearing 0 it hides behind
> the card; at every other bearing it does not.
>
> Measured in the flight snapshots: at 0 degrees a fixed wall strip reads +2.3 DN
> against a reference on 13 of 13 subjects; at -15.9 degrees it reads -30.0 DN on
> 13 of 13. So the off-axis frames carry a hard-edged dark block next to the
> subject and the on-axis frames do not.
>
> **The bearing-0 column stands. Every off-axis number in §2 is an upper bound on
> the cost of bearing, because part of what it measures is the card's own shadow.**
> A real person standing to one side does not bring a rectangular shadow with them.
>
> This matters for the capture tomorrow: compare real frames against the bearing-0
> column, not against the off-axis ones.
>
> Found by an adversarial verifier. Details and the other corrections are in
> `docs/eval_results/2026-09-16-onaxis/README.md`.

## 1. The headline

The standing scene parks the person 1.0 m to the side, which is 15.9 degrees off
axis. Put the same thirteen subjects straight ahead instead and four of the seven
that never latch in flight become near perfect.

Fraction of frames at or above the 0.75 enter bar, **bearing 0**, against what
each subject actually did in flight at the off-axis pose:

| subject | index | flown M1, off axis | on axis 3.5 m | on axis 3.0 m |
|---|---|---|---|---|
| 161875 | 87.0 | **0.000** | **0.950** | 0.850 |
| 374369 | 90.3 | **0.000** | **1.000** | 1.000 |
| 266409 | 92.1 | 0.098 | **1.000** | 0.975 |
| 401446 | 88.8 | 0.106 | **1.000** | 0.975 |
| 61747 | 86.8 | 0.722 | 0.975 | 0.475 |
| 556158 | 93.9 | 0.879 | 1.000 | 1.000 |
| 280779 | 92.7 | 0.986 | 1.000 | 1.000 |
| control | 99.2 | 0.991 | 1.000 | 1.000 |
| 250127 | 52.1 | 0.000 | 0.450 | 0.550 |
| 356427 | 37.8 | 0.000 | **0.000** | 0.000 |
| 157365 | 34.6 | 0.000 | **0.000** | 0.000 |
| 527750 | 34.3 | 0.000 | **0.000** | 0.000 |
| 124442 | 28.4 | 0.000 | **0.000** | 0.000 |

Two groups, and they are not the groups the flight data suggested.

**Four subjects are genuinely hard.** 124442, 527750, 157365 and 356427 fail on
axis too, at every range past 2.0 m. Nothing about pose rescues them. At 1.5 m
they all come back, which is the range effect, but the drone does not go there.

**Four subjects were failing on pose, not on difficulty.** 161875, 374369, 266409
and 401446 are at or near 1.000 on axis and at or near 0.000 in flight. The
flown scene's 15.9 degree offset is the whole difference.

So the people-plural headline, a 29% standing latch rate over twelve screened
people, is substantially a measurement of one unlucky camera pose. That number is
still what the drone did on that scene. It is not what the network can see.

## 2. What bearing costs, measured

Mean confidence pooled over subjects:

| distance | -25 deg | -10 deg | 0 | +10 deg | +25 deg |
|---|---|---|---|---|---|
| 1.5 m | 0.843 | 0.905 | 0.915 | 0.899 | 0.850 |
| 2.0 m | 0.830 | 0.811 | 0.820 | 0.792 | 0.774 |
| 2.5 m | 0.653 | 0.688 | 0.689 | 0.598 | 0.524 |
| 3.0 m | 0.586 | 0.657 | 0.705 | 0.632 | 0.405 |
| 3.5 m | 0.429 | 0.686 | 0.759 | 0.720 | 0.496 |

Bearing is nearly free up close and expensive far away. At 1.5 m, 25 degrees off
axis costs about 0.07. At 3.5 m it costs 0.26 to 0.33. The flown standing scene
sits at -15.9 degrees and 3.64 m, in the worst corner of this table.

**A small left/right asymmetry exists and it runs the wrong way for the obvious
story.** Pooled, the negative side beats the positive by 0.021 at 10 degrees and
0.059 at 25. The flown scene is on the negative side, the better one, and it
still fails. So asymmetry is real, small, and cannot be the explanation.

## 3. The 2.5 m dip, which I expected to confirm and did not

The fidelity study's static probe dips at its 2.5 m rung for every subject, which
was the prior. This grid does not reproduce it cleanly.

Pooled over all subjects and bearings the profile is 0.882, 0.805, 0.630, 0.597,
0.618 at 1.5, 2.0, 2.5, 3.0 and 3.5 m. **The interior minimum is at 3.0 m, not
2.5.** At bearing 0, eight of thirteen subjects are below both their neighbours
at 2.5 m, which is suggestive and is not the clean universal dip the earlier
ladder showed.

Two measurements of nominally the same thing disagree. This one has 2,600 frames
a rung; I am not going to adjudicate it here, and the honest statement is that the
range profile is not smooth between 2.0 and 3.5 m and nobody has explained why.
It matters for tomorrow because the capture protocol puts a mark at 2.5 m.

## 4. What to expect from a real person tomorrow

At 3.5 m, bearing 0, the rendered subjects give a fraction above the bar with
median 0.975 and four of thirteen at exactly 0.000. So the reference is bimodal:
most rendered people are nearly always above the bar on axis, and a hard quarter
are never above it.

If a real person comes back near 1.000, they behave like the nine. If near 0.000,
like the four. The prediction recorded before any real frame exists is in
`docs/hardware/2026-09-16-prediction-before-real-frames.md` and stands unchanged:
median above 0.80, nobody at exactly 0.000.

Worth capturing the plus and minus 25 degree marks properly, because this table
says that is where the cost is, and at 3.5 m it is a third of the confidence
budget.

## 5. Limits

Rendered cutouts on opaque cards, which the fidelity study established are harder
than the photographs they come from, so this is a lower bound on real people.
Forty frames a cell, each a distinct render with its own sensor-noise draw, which
is 2,600 frames a distance pooled. The mock streamer serves the same scene
geometry the simulator flies, so this inherits every property of that scene except
the person's position. Nothing here flew, so no per-frame rate becomes a
loss-of-track fraction. The mirror check passes on 7,827 off-centre frames, bin
accuracy 98 to 100 percent, so the pipeline is reading left and right correctly.
