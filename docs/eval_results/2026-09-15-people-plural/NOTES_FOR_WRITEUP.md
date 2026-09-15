# Running notes, to fold into the README when the suite lands

## Panel width: pool.json vs what was actually rendered

`pick_all_eligible.py` derives `panel_w_m` as 1.7 / aspect_hw from
`real_people.csv`. `build_scene.py` derives it from the cutout itself, and the
two disagree by at most 0.63% (largest: 527750, 0.5780 against 0.5744).
`analyze_pool.py` reads the manifest, so every number in the analysis is the
rendered width. Only the free-text note inside each scene definition quotes the
pool.json figure. Worth one sentence in the README; not worth regenerating 24
scene definitions over.

## The width-matched contrast is exact, not approximate

In rendered terms 124442 and 61747 have the SAME panel width, 0.7139 m to four
decimals, while sitting at detectability index 28.4 and 86.8. 266409 is 0.7039,
within 0.010 m of both, at index 92.1. So the "is it the person or the card"
question has a clean natural control that cost no extra flights.

## Confidence against range is not monotone, and every subject dips at 2.5 m

From the fidelity study's own static probe, chip arm, himax, dy = 0:

| subject | 1.5 | 2.0 | 2.5 | 3.0 | 3.5 | 4.0 |
|---|---|---|---|---|---|---|
| 124442 | 0.888 | 0.652 | 0.254 | 0.354 | 0.241 | 0.329 |
| 61747 | 0.954 | 0.897 | 0.739 | 0.916 | 0.883 | 0.806 |
| 556158 | 0.988 | 0.962 | 0.778 | 0.849 | 0.930 | 0.983 |
| control | 0.998 | 0.997 | 0.979 | 0.943 | 0.972 | 0.980 |

Every one of the 13 subjects has its minimum or near-minimum at the 2.5 m rung
and recovers past it. That is a systematic feature of the 2.5 m rung rather than
of any subject, and nothing in this project has explained it. It is not load
bearing for the people-plural result, which is flown at 3.64 m and 3.13 m, but
it should be flagged: a detectability curve that is not monotone in range is
strange, and if it is a resampling artefact at one scale then the ladder that
several studies rest on has a soft rung in the middle of it. Worth its own look.

## The deadlock, stated precisely

- `follow_person.py:374-377`: `vx` is assigned only inside `if vis_state:`;
  the else branch sets `yaw, vx = 0.0, 0.0`.
- The static scene starts the drone at the origin and the person at 3.64 m.
- The five low subjects reach 0.75 only nearer than 1.65-2.02 m.
- So they are never acquired, and the drone never moves, so the range never
  changes. `A.static__124442__r1a1`: first pose (0,0), last pose (0,0),
  dist_start 3.64, dist_end 3.64, tracking 0.000, over the full 45 s.

This is a control-law property, not only a perception property, and the
2026-09-15-deadlock suite is built to separate the two.
