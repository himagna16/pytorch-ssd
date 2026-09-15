# Design: what does the drone do with PEOPLE, plural

## The question

Every person-tracking number this project has published (0.97-0.99) is a
measurement of one COCO cutout, 19432/428692, which sits at the 99.2nd percentile
of rendered detectability among 266 real people. On 2026-09-15 I flew a median
and a 25th-percentile person and the drone never latched at all, 11 of 12
flights. Two points do not make a curve. This experiment measures the
distribution.

## Subjects: the whole eligible pool, no new selection

The typical-person study pre-registered a two-stage screen and published the
verdict for all 39 mechanically eligible subjects. Exactly 12 carry
`eye_verdict == keep`. I fly ALL 12. No subject is chosen for this experiment,
which removes subject selection from the design entirely.

Index percentiles of the 12, from cohort_ranking.tsv:
28.4, 34.3, 34.6, 37.8, 52.1, 86.8, 87.0, 88.8, 90.3, 92.1, 92.7, 93.9

Plus arm 13: the flown control 19432 at 99.2, which is the published subject and
is the link back to every existing number.

## Cells

13 subjects x 2 scenes x 6 repeats = 156 flights.
Scenes: tp15_static (class A, 45 s) and tp01_moving (class B, 50 s) geometry,
generated from s15_static_offset and s01_control_moving by changing only
`subjects[0].coco`, using the typical-person study's own make_scene_defs.py.

Ships-as for every cell: chip backend, himax_typical camera, 6.5 Hz / 153 ms,
matte floor, shipped 0.75 / 0.45 / 3 latch rule with no flags passed.
Interleaved by subject flight-by-flight and rotated per repeat.

## Primary outcome

M1 tracking fraction per flight. Pre-registered primary analysis: the
subject-level mean M1 against the subject's index percentile, with a
cluster bootstrap over subjects for the interval. Secondary: fraction of
flights that EVER latch, time to first latch, M9 losses, M10 p05.

## Pre-registered predictions

1. Subject-level mean M1 is strongly increasing in index percentile.
2. The 5 subjects below the 55th percentile latch on a minority of flights.
3. The control reproduces its published 0.97-0.99.
4. The pooled median M1 over the 12 screened subjects is far below 0.97.

## Known limitations, stated in advance

- The 12 cluster at 28-52 and 87-94 with nothing between 52 and 87. The curve
  will be two clouds, not a ladder.
- Panel width varies by subject because it follows the cutout's bbox aspect at a
  fixed 1.7 m height. That is a property of which person it is, not an
  independent change, but apparent width is not held constant.
- The control 19432 has wui == 0 and mech_eligible == 0, so it does NOT pass the
  screen its 12 peers passed. It is a reference arm, not a 13th sample.
- Rendered cutouts are harder than real photographs, established 2026-09-15. So
  this measures the simulator's people, and the real answer is bounded, not
  located, by it.
- Static frames established per-frame rates; this adds hysteresis and temporal
  correlation, which is the point, but it means n is flights, not frames.

---

# Amendment, before any result was read

The design above was put to a six-lens critique panel before the suite flew.
It raised 55 objections; each was handed to an independent verifier told to
refute it if it honestly could. Two survived. Both are about the analysis, so
no flight changed. Full transcript of the panel is not committed; the two
surviving objections and what I did about them are recorded here because they
change what this directory is allowed to claim.

## 1. The primary statistic was going to be a lie (fatal)

The original plan was "subject-level mean M1 against the subject's index
percentile, with a cluster bootstrap over subjects." The 12 subjects sit at
28.4-52.1 and 86.8-93.9 with a 34.7-point hole in the middle. The verifier
computed that under the expected outcome a correlation comes out at r = 0.978
with a cluster-bootstrap interval of [0.952, 0.997], and that the interval is
tight only because barely 0.16% of resamples land inside a single cloud. Every
step function with a threshold anywhere in the hole fits the data identically.
A slope would have been published and read as a graded dose-response over
detectability when the data support only "these five fail and those seven pass."

**What changed.** The estimand is now the difference in subject-level latch rate
and mean M1 between the low group and the high group, bootstrapped over
subjects, reported per class. Rank correlations are printed as diagnostics under
a heading that says so, and the identified set is printed beside them rather
than footnoted: no subject was flown between index 52.1 and 86.8, so the shape
and location of the transition are not estimated.

**Prediction 1 is restated** so it can fail. Not "mean M1 is strongly increasing
in index percentile", which any two-cloud result satisfies, but: every subject at
index >= 86.8 has mean M1 above 0.9 and every subject at index <= 52.1 has mean
M1 below 0.1.

**A better covariate, added on the panel's suggestion.** `index_pct` averages
percentiles over ranges 1.5-4.0 m, including rungs these scenes never fly
(static settles near 3.6 m, moving near 3.1 m). The suite now also carries
`conf_flown_range`: mean chip confidence, himax, dy = 0, over the 3.0 and 3.5 m
rungs. It spans 0.297-0.937 across the 12 and is on the same scale as the bars
that decide the outcome, so the unflown gap becomes a mechanical statement
instead of a statement about a rank: the flip lies between 0.653 and 0.833 mean
confidence, and the follower's own 0.75 enter bar sits inside that interval.

## 2. M9 losses reads zero for a flight that never latched (major)

`scoreboard.py:564` builds the loss list only from a 1 -> 0 transition in the
tracking flag, so a flight where the drone ignored the person for the whole
duration scores zero losses, byte-identical to a flight that tracked perfectly.
The precursor study hit this and replaced the metric; this design had listed
M9 losses as a secondary and dropped the replacements.

**What changed.** Per-flight now carries `untracked_time_total_s`,
`frames_above_enter` and `longest_above_enter_run` (against the 3 consecutive
frames the follower needs), all three computed the way
`typical-person/scripts/analyze_typical.py` computes them. M9 losses is reported
only conditional on a latch having happened, with its denominator printed.

## What the panel did not find

The other 53 objections were refuted on inspection. One verifier errored; the
objection it was handed had already been confirmed by another, so nothing was
lost. The panel did not overturn the subject pool, the scene generation, the
ships-as configuration, the interleaving, or the decision to fly the whole
screened pool rather than a selection of it.
