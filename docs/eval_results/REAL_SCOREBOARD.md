# Real-frame scoreboard

One row per `tools/real_frames/real_scoreboard.py` run. Definitions:
`docs/datasets/real_test_v1.md` (**PROPOSED, needs Sai's sign-off**). Rows are appended by
the tool; do not edit numbers by hand.

- **hit@0.75±1**: mean over person clips of the share of labelled frames with chip
  confidence >= 0.75 and argmax x-bin within 1 of the label. **exact**: same, exact bin.
  [95% bootstrap over clips]
- **guard**: no empty / clutter / near-black clip has 3 consecutive frames >= 0.75.
- Only `test` rows are test results. `dev` rows are for development and include frames
  that every analysis so far has looked at.

| date | model | onnx sha1 | eps | split | clips (person / guard) | hit@0.75±1 [95% CI] | exact [95% CI] | guard | coverage | notes |
|---|---|---|---|---|---|---|---|---|---|---|
| 2026-10-01 | champion (plain_follow_prod_qat_v3) | d90555c8 | 0.000200982 | dev | 20 / 15 | 36.5 [22.7, 50.6] | 20.9 [11.0, 31.5] | FAIL | NOT met | grid labels provisional (FOV/aim unmeasured); guard fails on 11 clip(s): 11 near-black, 0 lit; 1 short clip(s) excluded; stream 162x122 raw; people: p01; BASELINE; all p01, one room (dorm1); Sep 22+24 captures |
