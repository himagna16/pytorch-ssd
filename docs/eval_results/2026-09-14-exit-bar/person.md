## Cost side: `B.moving__ships` (walking person), 2 repeats per arm

Heading error and distance come from the repo's own `scoreboard.py` (`runs/*/metrics.json`).
`time lost` = seconds between the end of one track episode and the start of the next, plus any
trailing untracked tail. Every one of these 6 flights is scored PASS by `scoreboard.py`
(`scoreboards/arm_*/scoreboard.md`).

| arm | n | tracking fraction (per flight) | mean | episodes | losses | re-acquires | time lost s | max gap s | hdg err mean deg | hdg err max deg | settled dist err m | final in band |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **0.45** | 2 | 0.9920, 0.9910 | 0.9915 | 1/1 | 0 | 0 | 0.00 | 0.00 | 3.38 | 9.14 | 0.538 | 2/2 |
| **0.55** | 2 | 0.9150, 0.9660 | 0.9405 | 2/2 | 2 | 2 | 4.09 | 2.99 | 3.26 | 8.55 | 0.554 | 2/2 |
| **0.65** | 2 | 0.9510, 0.7760 | 0.8635 | 4/3 | 6 | 5 | 10.06 | 0.94 | 3.78 | 9.65 | 0.567 | 2/2 |

### Per-flight

| run | vis_exit | seed | tracking_fraction | episodes | losses | reacquisitions | gap_s | time_lost_s | max_gap_s | hdg_mean | hdg_p90 | hdg_max | dist_err_settled_mean_m | dist_final_m | final_in_band | uncertain_present | mean_conf | step_gap_max_ms | sim_wall_ratio |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| x0.45__B.moving__ships__r1a1 | 0.45 | 1001 | 0.992 | 1 | 0 | 0 | [] | 0.0 | None | 3.35 | 6.95 | 9.14 | 0.539 | 2.396 | True | 0.0921 | 0.874 | 163.8 | 0.995 |
| x0.45__B.moving__ships__r2a1 | 0.45 | 1002 | 0.991 | 1 | 0 | 0 | [] | 0.0 | None | 3.42 | 6.59 | 8.53 | 0.536 | 2.335 | True | 0.1096 | 0.879 | 163.7 | 0.995 |
| x0.55__B.moving__ships__r1a1 | 0.55 | 1001 | 0.915 | 2 | 1 | 1 | [2.99] | 2.99 | 2.99 | 3.24 | 6.45 | 8.47 | 0.547 | 2.48 | True | 0.1102 | 0.864 | 163.9 | 0.997 |
| x0.55__B.moving__ships__r2a1 | 0.55 | 1002 | 0.966 | 2 | 1 | 1 | [1.1] | 1.1 | 1.1 | 3.28 | 6.66 | 8.55 | 0.56 | 2.264 | True | 0.1106 | 0.875 | 163.6 | 0.995 |
| x0.65__B.moving__ships__r1a1 | 0.65 | 1001 | 0.951 | 4 | 3 | 3 | [0.64, 0.63, 0.63] | 1.9 | 0.64 | 3.46 | 7.1 | 9.65 | 0.554 | 2.333 | True | 0.0807 | 0.876 | 217.6 | 0.981 |
| x0.65__B.moving__ships__r2a1 | 0.65 | 1002 | 0.776 | 3 | 3 | 2 | [0.79, 0.94] | 8.16 | 0.94 | 4.1 | 6.99 | 8.8 | 0.579 | 2.598 | True | 0.0948 | 0.85 | 163.7 | 0.995 |
