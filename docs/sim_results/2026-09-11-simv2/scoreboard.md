# Simulator scoreboard - core-rescore suite - start time not recorded

**Overall: FAIL.** 7 of 14 checks FAILED (7 passed, 0 measured-only, 0 unusable).
Flights: 37 attempted, 36 valid, 1 invalid, 36 scored (14 cells). Total time: not recorded.

Two setups appear in the table. **ships-as** is what the real drone will be: the chip's own integer network, the realistic camera model, and the chip's 6.5 Hz speed. **proven** is the laptop model on a clean camera at full speed - the setup every September baseline was measured in, so it says whether a problem is new or just the cost of realism.

## What failed

**Person standing still - ships-as**  
Person standing still: FAILED on M7_dist_err_settled_mean_m, M7_final_in_band. It pointed at the person within 4.1 deg avg (6.0 worst) and held station at 3.03 m (2.73-3.35 over 4), target 1.94.  
- `M7_dist_err_settled_mean_m` = 1.153, needs <= 0.75 (quantisation floor is +-0.40 m and the approach parks near the far edge (~0.49 m); 0.75 m is ~1.5x that structural floor, and the verified 2.3 m static baseline scores 0.36 m)
- `M7_final_in_band` = 0.0, needs == 1.0 (the hold band is every distance the size head calls bucket 2, widened 10% (band [1.457, 2.671] m))

**Person swaying side to side - ships-as**  
Person swaying side to side: FAILED on M7_dist_err_settled_mean_m, M7_final_in_band. It pointed at the person within 3.2 deg avg (8.0 worst) and held station at 3.33 m (3.30-3.35 over 2), target 1.94.  
- `M7_dist_err_settled_mean_m` = 1.225, needs <= 0.75 (quantisation floor is +-0.40 m and the approach parks near the far edge (~0.49 m); 0.75 m is ~1.5x that structural floor, and the verified 2.3 m static baseline scores 0.36 m)
- `M7_final_in_band` = 0.0, needs == 1.0 (the hold band is every distance the size head calls bucket 2, widened 10% (band [1.457, 2.671] m))

**A dog and a cat, no people - ships-as**  
A dog and a cat, no people: it locked onto an animal/toy 1 time(s), tracked it for 73% of the flight and moved 2.48 m. Measured, not graded - this is the number that decides champion vs confuser.  
- `M6_max_horizontal_drift_m` = 2.666, needs < 0.5 (a distractor may capture the track, but it must not fly across the room)

**Person swaying side to side - proven**  
Person swaying side to side: FAILED on M7_final_in_band. It pointed at the person within 2.8 deg avg (8.6 worst) and held station at 2.68 m (2.66-2.71 over 5), target 1.94.  
- `M7_final_in_band` = 0.0, needs == 1.0 (the hold band is every distance the size head calls bucket 2, widened 10% (band [1.457, 2.671] m))

**Person swaying side to side - chip/clean/full**  
Person swaying side to side: FAILED on M7_dist_err_settled_mean_m, M7_final_in_band. It pointed at the person within 2.9 deg avg (7.6 worst) and held station at 2.81 m (2.79-2.84 over 2), target 1.94.  
- `M7_dist_err_settled_mean_m` = 0.83, needs <= 0.75 (quantisation floor is +-0.40 m and the approach parks near the far edge (~0.49 m); 0.75 m is ~1.5x that structural floor, and the verified 2.3 m static baseline scores 0.36 m)
- `M7_final_in_band` = 0.0, needs == 1.0 (the hold band is every distance the size head calls bucket 2, widened 10% (band [1.457, 2.671] m))

**Person swaying side to side - float/himax_typical/full**  
Person swaying side to side: FAILED on M7_dist_err_settled_mean_m, M7_final_in_band. It pointed at the person within 3.0 deg avg (8.8 worst) and held station at 3.01 m (2.98-3.04 over 2), target 1.94.  
- `M7_dist_err_settled_mean_m` = 1.107, needs <= 0.75 (quantisation floor is +-0.40 m and the approach parks near the far edge (~0.49 m); 0.75 m is ~1.5x that structural floor, and the verified 2.3 m static baseline scores 0.36 m)
- `M7_final_in_band` = 0.0, needs == 1.0 (the hold band is every distance the size head calls bucket 2, widened 10% (band [1.457, 2.671] m))

**Person swaying side to side - float/clean/chip**  
Person swaying side to side: FAILED on M7_dist_err_settled_mean_m, M7_final_in_band. It pointed at the person within 2.9 deg avg (8.9 worst) and held station at 2.78 m (2.75-2.81 over 2), target 1.94.  
- `M7_dist_err_settled_mean_m` = 0.7975, needs <= 0.75 (quantisation floor is +-0.40 m and the approach parks near the far edge (~0.49 m); 0.75 m is ~1.5x that structural floor, and the verified 2.3 m static baseline scores 0.36 m)
- `M7_final_in_band` = 0.0, needs == 1.0 (the hold band is every distance the size head calls bucket 2, widened 10% (band [1.457, 2.671] m))

## All checks

| Scene | What it tests | Setup | Tracked | Pointing error | Distance held | False follows | Verdict |
|---|---|---|---|---|---|---|---|
| Person standing still | person, standing still | ships-as | 99.0% | 4.1 deg avg (6.0 worst) | 3.03 m (2.73-3.35 over 4), target 1.94 | 0 | **FAIL** |
| Person swaying side to side | person, moving | ships-as | 99.2% | 3.2 deg avg (8.0 worst) | 3.33 m (3.30-3.35 over 2), target 1.94 | 0 | **FAIL** |
| Empty room | nobody present | ships-as | 0.0% | n/a | n/a | 0 | PASS |
| Person walks behind a partition | person hidden then seen again | ships-as | 65.7% | 5.1 deg avg (13.9 worst) | n/a | 0 | PASS |
| Furniture and boxes, nobody home | inanimate distractor | ships-as | 0.0% | n/a | n/a | 0 | PASS |
| A dog and a cat, no people | animate distractor | ships-as | 73.5% | n/a | n/a | 1 | **FAIL** |
| Person standing still | person, standing still | proven | 99.6% | 0.9 deg avg (2.0 worst) | 2.42 m (2.22-2.58 over 5), target 1.94 | 0 | PASS |
| Person swaying side to side | person, moving | proven | 99.7% | 2.8 deg avg (8.6 worst) | 2.68 m (2.66-2.71 over 5), target 1.94 | 0 | **FAIL** |
| Empty room | nobody present | proven | 0.0% | n/a | n/a | 0 | PASS |
| Person walks behind a partition | person hidden then seen again | proven | 77.3% | 3.9 deg avg (11.8 worst) | n/a | 0 | PASS |
| Furniture and boxes, nobody home | inanimate distractor | proven | 0.0% | n/a | n/a | 0 | PASS |
| Person swaying side to side | person, moving | chip/clean/full | 99.4% | 2.9 deg avg (7.6 worst) | 2.81 m (2.79-2.84 over 2), target 1.94 | 0 | **FAIL** |
| Person swaying side to side | person, moving | float/himax_typical/full | 99.6% | 3.0 deg avg (8.8 worst) | 3.01 m (2.98-3.04 over 2), target 1.94 | 0 | **FAIL** |
| Person swaying side to side | person, moving | float/clean/chip | 99.2% | 2.9 deg avg (8.9 worst) | 2.78 m (2.75-2.81 over 2), target 1.94 | 0 | **FAIL** |

## What each scene means, in one line

- _ships-as_ - Person standing still: FAILED on M7_dist_err_settled_mean_m, M7_final_in_band. It pointed at the person within 4.1 deg avg (6.0 worst) and held station at 3.03 m (2.73-3.35 over 4), target 1.94.
- _ships-as_ - Person swaying side to side: FAILED on M7_dist_err_settled_mean_m, M7_final_in_band. It pointed at the person within 3.2 deg avg (8.0 worst) and held station at 3.33 m (3.30-3.35 over 2), target 1.94.
- _ships-as_ - Empty room: correctly ignored everything; it never moved (drift 0.00 m).
- _ships-as_ - Person walks behind a partition: it lost the track for up to 15.9 s, and once the person was properly back in view it took 1.33 s to start following again; it correctly waited for 3 fresh frames before steering again.
- _ships-as_ - Furniture and boxes, nobody home: correctly ignored everything; it never moved (drift 0.00 m).
- _ships-as_ - A dog and a cat, no people: it locked onto an animal/toy 1 time(s), tracked it for 73% of the flight and moved 2.48 m. Measured, not graded - this is the number that decides champion vs confuser.
- _proven_ - Person standing still: followed correctly. It pointed at the person within 0.9 deg avg (2.0 worst) and held station at 2.42 m (2.22-2.58 over 5), target 1.94.
- _proven_ - Person swaying side to side: FAILED on M7_final_in_band. It pointed at the person within 2.8 deg avg (8.6 worst) and held station at 2.68 m (2.66-2.71 over 5), target 1.94.
- _proven_ - Empty room: correctly ignored everything; it never moved (drift 0.00 m).
- _proven_ - Person walks behind a partition: it lost the track for up to 8.5 s, and once the person was properly back in view it took 0.47 s to start following again; it correctly waited for 3 fresh frames before steering again.
- _proven_ - Furniture and boxes, nobody home: correctly ignored everything; it never moved (drift 0.00 m).
- _chip/clean/full_ - Person swaying side to side: FAILED on M7_dist_err_settled_mean_m, M7_final_in_band. It pointed at the person within 2.9 deg avg (7.6 worst) and held station at 2.81 m (2.79-2.84 over 2), target 1.94.
- _float/himax_typical/full_ - Person swaying side to side: FAILED on M7_dist_err_settled_mean_m, M7_final_in_band. It pointed at the person within 3.0 deg avg (8.8 worst) and held station at 3.01 m (2.98-3.04 over 2), target 1.94.
- _float/clean/chip_ - Person swaying side to side: FAILED on M7_dist_err_settled_mean_m, M7_final_in_band. It pointed at the person within 2.9 deg avg (8.9 worst) and held station at 2.78 m (2.75-2.81 over 2), target 1.94.

## Measured-only checks

These have no pass mark yet, on purpose - we are collecting the first numbers.

- Dog / teddy false-follow rate (decides champion vs confuser model)
- Steering smoothness (pass mark set from this sweep - spec section 4, M11)
- Every threshold on the realistic camera (no verified baseline yet - spec section 5)

## Provisional numbers observed in this sweep (for calibrating v2.1)

| metric | scene class | median | min | max | provisional threshold |
|---|---|---|---|---|---|
| M1_tracking_fraction | A (ships-as) | 0.99 | 0.99 | 0.99 | >= 0.9 |
| M2_heading_err_mean_deg | A (ships-as) | 4.135 | 3.82 | 5.12 | <= 8.0 |
| M10_uncertain_fraction_present | A (ships-as) | 0.0882 | 0.0145 | 0.2786 | <= 0.15 |
| M11_yaw_reversals_per_min | A (ships-as) | 0.0 | 0.0 | 1.85 | <= 8.0 |
| M11_yaw_saturated_fraction | A (ships-as) | 0.0 | 0.0 | 0.0 | <= 0.25 |
| M1_tracking_fraction | B (ships-as) | 0.992 | 0.992 | 0.992 | >= 0.9 |
| M2_heading_err_mean_deg | B (ships-as) | 3.16 | 2.89 | 3.43 | <= 10.0 |
| M10_uncertain_fraction_present | B (ships-as) | 0.0083 | 0.0 | 0.0165 | <= 0.15 |
| M11_yaw_reversals_per_min | B (ships-as) | 3.18 | 3.17 | 3.19 | <= 24.0 |
| M11_yaw_saturated_fraction | B (ships-as) | 0.0 | 0.0 | 0.0 | <= 0.25 |
| M9_gt_halfvisible_to_relatch_s | D (ships-as) | 2.512 | 2.507 | 2.517 | <= 1.5 |
| M11_yaw_reversals_per_min | A (proven) | 0.0 | 0.0 | 0.0 | <= 8.0 |
| M11_yaw_saturated_fraction | A (proven) | 0.0 | 0.0 | 0.0 | <= 0.25 |
| M11_yaw_reversals_per_min | B (proven) | 4.7 | 4.69 | 4.81 | <= 24.0 |
| M11_yaw_saturated_fraction | B (proven) | 0.0 | 0.0 | 0.0 | <= 0.25 |
| M9_gt_halfvisible_to_relatch_s | D (proven) | 1.1335 | 0.664 | 1.603 | <= 1.0 |
| M11_yaw_reversals_per_min | B (chip/clean/full) | 4.685 | 4.66 | 4.71 | <= 24.0 |
| M11_yaw_saturated_fraction | B (chip/clean/full) | 0.0 | 0.0 | 0.0 | <= 0.25 |
| M1_tracking_fraction | B (float/himax_typical/full) | 0.996 | 0.996 | 0.996 | >= 0.9 |
| M2_heading_err_mean_deg | B (float/himax_typical/full) | 2.985 | 2.94 | 3.03 | <= 8.0 |
| M10_uncertain_fraction_present | B (float/himax_typical/full) | 0.0 | 0.0 | 0.0 | <= 0.15 |
| M11_yaw_reversals_per_min | B (float/himax_typical/full) | 4.18 | 3.34 | 5.02 | <= 24.0 |
| M11_yaw_saturated_fraction | B (float/himax_typical/full) | 0.0 | 0.0 | 0.0 | <= 0.25 |
| M11_yaw_reversals_per_min | B (float/clean/chip) | 4.7 | 4.63 | 4.77 | <= 24.0 |
| M11_yaw_saturated_fraction | B (float/clean/chip) | 0.0 | 0.0 | 0.0 | <= 0.25 |

---

Distances: the drone aims to stop where the person fills the middle size bucket. For a 1.7 m person that is 1.94 m, and anything from 1.62 to 2.43 m is the same bucket, so it is all equally correct. Pointing error is the angle between where the drone is facing and where the person actually is, from the simulator's own ground truth.
