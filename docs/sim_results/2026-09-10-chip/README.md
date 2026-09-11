# Follower at the chip's speed (Sep 10, 2026)

Flights on the CrazySim MuJoCo simulator with the float champion model,
emulating the GAP8 chip: one inference at a time at 6.5 Hz, and each
command applied 153 ms after its frame arrived (220 ms for the bound run).
Every run passed the validity check in `analyze_follow.py`: simulator at
0.97x real time or better, 6.43 Hz achieved, processing starts at least
154 ms apart.

| Run | Scene | Tracked | True heading error mean / 90th pct / max | Notes |
|---|---|---|---|---|
| b2_moving_chip | person sways ±1.2 m | 99.2% | 3.1 / 5.5 / 7.9° | full-speed baseline 2.7 / 4.9 / 6.6° |
| g_moving_chip220 | same, 220 ms delay | 99.2% | 3.2 / 5.9 / 8.0° | bound for capture-time delay |
| c2_static_chip | person 3.5 m out, 1 m right | 98.7% | 4.8 / 5.0 / 5.0° | settles inside the center x-bin, about ±4.5° wide |
| d2_empty_chip | empty room | 0% | not applicable | never moved; peak confidence 0.637, below the 0.7 needed |

Steering does not oscillate at chip speed: the drone's yaw rate changes
sign 3.5 times a minute, against 17 at full speed. Reproduce the scores:

```bash
../trainenv/bin/python tools/crazysim_macos/analyze_follow.py <run_dir> 3.0 0.0 --truth <run_dir>/truth.csv
```

`osc.py <name>` expects `run_<name>/` and `truth_<name>.csv` side by side.
Saved camera frames are kept outside git.
