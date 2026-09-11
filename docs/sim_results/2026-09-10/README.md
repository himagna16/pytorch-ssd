# Simulator person-following results, Sep 10, 2026

Evidence for the Sep 10 entry in `EXPERIMENTS.md`. Each folder holds one
flight: `summary.json` (follower's own summary), `follow_log.csv` (every
control step: model output, commands, drone pose, wall-clock time), and,
where the person was logged, `truth.csv` (the simulator's true person
position: wall_time, sim_time, x, y).

| Folder | Test | Result |
|---|---|---|
| `static/` | person 3.5 m out, 1 m right | true heading error 1.5° average |
| `moving/` | person swaying ±1.2 m, default steering | 2.7° average, 7.7° worst |
| `moving_soft/` | same, smooth steering | 2.9° average, 8.2° worst |
| `empty/` | empty room | never tracked, never moved |
| `stale/` | camera frozen at 20 s | hovered, then landed |

`moving_comparison.png` plots the drone's heading against the true direction
to the person for both moving runs; `static_control.png` does the same for
the static run. Re-score any run with `tools/crazysim_macos/analyze_follow.py`,
or re-fly everything with `tools/crazysim_macos/run_acceptance.sh`.

Camera snapshots are not included because they contain the COCO photo.
