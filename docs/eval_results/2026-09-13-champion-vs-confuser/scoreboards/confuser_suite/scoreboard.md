# Simulator scoreboard - cvc_confuser suite - 13 Sep 2026

**Overall: FAIL.** 3 of 6 checks FAILED (2 passed, 1 measured-only, 0 unusable).
Flights: 24 attempted, 24 valid, 0 invalid, 24 scored (6 cells). Total time: 0 min.

Two setups appear in the table. **ships-as** is what the real drone will be: the chip's own integer network, the realistic camera model, and the chip's 6.5 Hz speed. **proven** is the laptop model on a clean camera at full speed - the setup every September baseline was measured in, so it says whether a problem is new or just the cost of realism.

## What failed

**Person standing still - ships-as**  
Person standing still: FAILED on M2_heading_err_max_deg, M7_dist_err_settled_mean_m, M7_final_in_band. It pointed at the person within 15.9 deg avg (15.9 worst) and held station at 3.64 m, target 1.94.  
- `M2_heading_err_max_deg` = 15.95, needs <= 12.0 (verified maxima 7.7-7.9 deg (1.6x margin))
- `M7_dist_err_settled_mean_m` = 1.698, needs <= 0.75 (quantisation floor is +-0.40 m and the approach parks near the far edge (~0.49 m); 0.75 m is ~1.5x that structural floor, and the verified 2.3 m static baseline scores 0.36 m)
- `M7_final_in_band` = 0.0, needs == 1.0 (the hold band is every distance the size head calls bucket 2, widened 10% (band [1.457, 2.671] m))

**Person swaying side to side - ships-as**  
Person swaying side to side: FAILED on M2_heading_err_max_deg, M7_dist_err_settled_mean_m. It pointed at the person within 15.9 deg avg (31.2 worst) and held station at 2.60 m (2.52-2.84 over 4), target 1.94.  
- `M2_heading_err_max_deg` = 29.055, needs <= 14.0 (verified maxima 7.7-7.9 deg (1.8x margin))
- `M7_dist_err_settled_mean_m` = 0.8235, needs <= 0.75 (quantisation floor is +-0.40 m and the approach parks near the far edge (~0.49 m); 0.75 m is ~1.5x that structural floor, and the verified 2.3 m static baseline scores 0.36 m)

**Person walks behind a partition - ships-as**  
Person walks behind a partition: it lost the track for up to 21.4 s, and once the person was properly back in view it took 2.76 s to start following again; it correctly waited for 3 fresh frames before steering again. FAILED.  
- `M9_gt_visible_to_relatch_s` = 2.7635, needs <= 1.5 (the spec's own M9 reacquire gate (1.0 s at full rate, 1.5 s at chip speed) applied to the quantity section 4 actually describes: time from the target being continuously visible in ground truth until the track re-latches. Not a new threshold, an existing one finally pointed at the right measurement)

## All checks

| Scene | What it tests | Setup | Tracked | Pointing error | Distance held | False follows | Verdict |
|---|---|---|---|---|---|---|---|
| Person standing still | person, standing still | ships-as | 0.0% | 15.9 deg avg (15.9 worst) | 3.64 m, target 1.94 | 0 | **FAIL** |
| Person swaying side to side | person, moving | ships-as | 9.0% | 15.9 deg avg (31.2 worst) | 2.60 m (2.52-2.84 over 4), target 1.94 | 0 | **FAIL** |
| Empty room | nobody present | ships-as | 0.0% | n/a | n/a | 0 | PASS |
| Person walks behind a partition | person hidden then seen again | ships-as | 4.2% | 16.8 deg avg (31.4 worst) | n/a | 0 | **FAIL** |
| Furniture and boxes, nobody home | inanimate distractor | ships-as | 0.0% | n/a | n/a | 0 | PASS |
| A dog and a cat, no people | animate distractor | ships-as | 0.0% | n/a | n/a | 0 | measured only |

## What each scene means, in one line

- _ships-as_ - Person standing still: FAILED on M2_heading_err_max_deg, M7_dist_err_settled_mean_m, M7_final_in_band. It pointed at the person within 15.9 deg avg (15.9 worst) and held station at 3.64 m, target 1.94.
- _ships-as_ - Person swaying side to side: FAILED on M2_heading_err_max_deg, M7_dist_err_settled_mean_m. It pointed at the person within 15.9 deg avg (31.2 worst) and held station at 2.60 m (2.52-2.84 over 4), target 1.94.
- _ships-as_ - Empty room: correctly ignored everything; it never moved (drift 0.00 m).
- _ships-as_ - Person walks behind a partition: it lost the track for up to 21.4 s, and once the person was properly back in view it took 2.76 s to start following again; it correctly waited for 3 fresh frames before steering again. FAILED.
- _ships-as_ - Furniture and boxes, nobody home: correctly ignored everything; it never moved (drift 0.00 m).
- _ships-as_ - A dog and a cat, no people: never locked on. Measured, not graded.

## Measured-only checks

These have no pass mark yet, on purpose - we are collecting the first numbers.

- Dog / teddy false-follow rate (decides champion vs confuser model)
- Steering smoothness (pass mark set from this sweep - spec section 4, M11)
- Every threshold on the realistic camera (no verified baseline yet - spec section 5)

  - A dog and a cat, no people (ships-as): A dog and a cat, no people: never locked on. Measured, not graded.

## Provisional numbers observed in this sweep (for calibrating v2.1)

| metric | scene class | median | min | max | provisional threshold |
|---|---|---|---|---|---|
| M1_tracking_fraction | A (ships-as) | 0.0 | 0.0 | 0.0 | >= 0.9 |
| M2_heading_err_mean_deg | A (ships-as) | 15.95 | 15.95 | 15.95 | <= 8.0 |
| M10_uncertain_fraction_present | A (ships-as) | 1.0 | 0.9906 | 1.0 | <= 0.15 |
| M11_yaw_reversals_per_min | A (ships-as) | 0.0 | 0.0 | 0.0 | <= 8.0 |
| M11_yaw_saturated_fraction | A (ships-as) | 0.0 | 0.0 | 0.0 | <= 0.25 |
| M1_tracking_fraction | B (ships-as) | 0.0905 | 0.057 | 0.178 | >= 0.9 |
| M2_heading_err_mean_deg | B (ships-as) | 15.905 | 12.39 | 16.39 | <= 10.0 |
| M10_uncertain_fraction_present | B (ships-as) | 0.4656 | 0.4407 | 0.5783 | <= 0.15 |
| M11_yaw_reversals_per_min | B (ships-as) | 2.475 | 0.0 | 3.34 | <= 24.0 |
| M11_yaw_saturated_fraction | B (ships-as) | 0.0833 | 0.0 | 0.1707 | <= 0.25 |
| M9_gt_halfvisible_to_relatch_s | D (ships-as) | 3.8565 | 3.645 | 4.068 | <= 1.5 |

---

Distances: the drone aims to stop where the person fills the middle size bucket. For a 1.7 m person that is 1.94 m, and anything from 1.62 to 2.43 m is the same bucket, so it is all equally correct. Pointing error is the angle between where the drone is facing and where the person actually is, from the simulator's own ground truth.
