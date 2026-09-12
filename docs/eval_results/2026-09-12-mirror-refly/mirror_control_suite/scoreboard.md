# Simulator scoreboard - core suite - 12 Sep 2026

**Overall: FAIL.** 4 of 7 checks FAILED (3 passed, 0 measured-only, 0 unusable).
Flights: 24 attempted, 20 valid, 4 invalid, 21 scored (7 cells). Total time: 29 min.

Two setups appear in the table. **ships-as** is what the real drone will be: the chip's own integer network, the realistic camera model, and the chip's 6.5 Hz speed. **proven** is the laptop model on a clean camera at full speed - the setup every September baseline was measured in, so it says whether a problem is new or just the cost of realism.

## What failed

**Person standing still - ships-as**  
Person standing still: FAILED on M7_dist_err_settled_mean_m, M7_final_in_band. It pointed at the person within 3.2 deg avg (5.1 worst) and held station at 2.98 m (2.87-3.10 over 3), target 1.94.  
- `M7_dist_err_settled_mean_m` = 1.019, needs <= 0.75 (quantisation floor is +-0.40 m and the approach parks near the far edge (~0.49 m); 0.75 m is ~1.5x that structural floor, and the verified 2.3 m static baseline scores 0.36 m)
- `M7_final_in_band` = 0.0, needs == 1.0 (the hold band is every distance the size head calls bucket 2, widened 10% (band [1.457, 2.671] m))

**Person swaying side to side - ships-as**  
Person swaying side to side: FAILED on M7_dist_err_settled_mean_m, M7_final_in_band. It pointed at the person within 3.0 deg avg (8.5 worst) and held station at 3.31 m (3.27-3.35 over 2), target 1.94.  
- `M7_dist_err_settled_mean_m` = 1.201, needs <= 0.75 (quantisation floor is +-0.40 m and the approach parks near the far edge (~0.49 m); 0.75 m is ~1.5x that structural floor, and the verified 2.3 m static baseline scores 0.36 m)
- `M7_final_in_band` = 0.0, needs == 1.0 (the hold band is every distance the size head calls bucket 2, widened 10% (band [1.457, 2.671] m))

**Person swaying side to side - chip/clean/full**  
Person swaying side to side: FAILED on M7_dist_err_settled_mean_m, M7_final_in_band. It pointed at the person within 2.8 deg avg (7.9 worst) and held station at 2.83 m (2.77-2.86 over 3), target 1.94.  
- `M7_dist_err_settled_mean_m` = 0.877, needs <= 0.75 (quantisation floor is +-0.40 m and the approach parks near the far edge (~0.49 m); 0.75 m is ~1.5x that structural floor, and the verified 2.3 m static baseline scores 0.36 m)
- `M7_final_in_band` = 0.0, needs == 1.0 (the hold band is every distance the size head calls bucket 2, widened 10% (band [1.457, 2.671] m))

**Person swaying side to side - float/himax_typical/full**  
Person swaying side to side: FAILED on M7_dist_err_settled_mean_m, M7_final_in_band. It pointed at the person within 2.9 deg avg (8.7 worst) and held station at 2.94 m (2.78-2.97 over 3), target 1.94.  
- `M7_dist_err_settled_mean_m` = 1.073, needs <= 0.75 (quantisation floor is +-0.40 m and the approach parks near the far edge (~0.49 m); 0.75 m is ~1.5x that structural floor, and the verified 2.3 m static baseline scores 0.36 m)
- `M7_final_in_band` = 0.0, needs == 1.0 (the hold band is every distance the size head calls bucket 2, widened 10% (band [1.457, 2.671] m))

## All checks

| Scene | What it tests | Setup | Tracked | Pointing error | Distance held | False follows | Verdict |
|---|---|---|---|---|---|---|---|
| Person standing still | person, standing still | ships-as | 99.1% | 3.2 deg avg (5.1 worst) | 2.98 m (2.87-3.10 over 3), target 1.94 | 0 | **FAIL** |
| Person swaying side to side | person, moving | ships-as | 99.2% | 3.0 deg avg (8.5 worst) | 3.31 m (3.27-3.35 over 2), target 1.94 | 0 | **FAIL** |
| Person standing still | person, standing still | proven | 99.6% | 1.1 deg avg (4.0 worst) | 2.27 m (2.25-2.78 over 3), target 1.94 | 0 | PASS |
| Person swaying side to side | person, moving | proven | 99.6% | 2.8 deg avg (8.6 worst) | 2.62 m (2.60-2.73 over 3), target 1.94 | 0 | PASS |
| Person swaying side to side | person, moving | chip/clean/full | 99.6% | 2.8 deg avg (7.9 worst) | 2.83 m (2.77-2.86 over 3), target 1.94 | 0 | **FAIL** |
| Person swaying side to side | person, moving | float/himax_typical/full | 99.6% | 2.9 deg avg (8.7 worst) | 2.94 m (2.78-2.97 over 3), target 1.94 | 0 | **FAIL** |
| Person swaying side to side | person, moving | float/clean/chip | 99.2% | 3.1 deg avg (9.0 worst) | 2.63 m (2.44-2.76 over 3), target 1.94 | 0 | PASS |

## What each scene means, in one line

- _ships-as_ - Person standing still: FAILED on M7_dist_err_settled_mean_m, M7_final_in_band. It pointed at the person within 3.2 deg avg (5.1 worst) and held station at 2.98 m (2.87-3.10 over 3), target 1.94.
- _ships-as_ - Person swaying side to side: FAILED on M7_dist_err_settled_mean_m, M7_final_in_band. It pointed at the person within 3.0 deg avg (8.5 worst) and held station at 3.31 m (3.27-3.35 over 2), target 1.94.
- _proven_ - Person standing still: followed correctly. It pointed at the person within 1.1 deg avg (4.0 worst) and held station at 2.27 m (2.25-2.78 over 3), target 1.94.
- _proven_ - Person swaying side to side: followed correctly. It pointed at the person within 2.8 deg avg (8.6 worst) and held station at 2.62 m (2.60-2.73 over 3), target 1.94.
- _chip/clean/full_ - Person swaying side to side: FAILED on M7_dist_err_settled_mean_m, M7_final_in_band. It pointed at the person within 2.8 deg avg (7.9 worst) and held station at 2.83 m (2.77-2.86 over 3), target 1.94.
- _float/himax_typical/full_ - Person swaying side to side: FAILED on M7_dist_err_settled_mean_m, M7_final_in_band. It pointed at the person within 2.9 deg avg (8.7 worst) and held station at 2.94 m (2.78-2.97 over 3), target 1.94.
- _float/clean/chip_ - Person swaying side to side: followed correctly. It pointed at the person within 3.1 deg avg (9.0 worst) and held station at 2.63 m (2.44-2.76 over 3), target 1.94.

## Measured-only checks

These have no pass mark yet, on purpose - we are collecting the first numbers.

- Dog / teddy false-follow rate (decides champion vs confuser model)
- Steering smoothness (pass mark set from this sweep - spec section 4, M11)
- Every threshold on the realistic camera (no verified baseline yet - spec section 5)

## Provisional numbers observed in this sweep (for calibrating v2.1)

| metric | scene class | median | min | max | provisional threshold |
|---|---|---|---|---|---|
| M1_tracking_fraction | A (ships-as) | 0.991 | 0.991 | 0.991 | >= 0.9 |
| M2_heading_err_mean_deg | A (ships-as) | 3.22 | 1.48 | 4.24 | <= 8.0 |
| M10_uncertain_fraction_present | A (ships-as) | 0.1376 | 0.0367 | 0.1481 | <= 0.15 |
| M11_yaw_reversals_per_min | A (ships-as) | 0.0 | 0.0 | 0.0 | <= 8.0 |
| M11_yaw_saturated_fraction | A (ships-as) | 0.0 | 0.0 | 0.0 | <= 0.25 |
| M1_tracking_fraction | B (ships-as) | 0.992 | 0.992 | 0.992 | >= 0.9 |
| M2_heading_err_mean_deg | B (ships-as) | 3.035 | 3.02 | 3.05 | <= 10.0 |
| M10_uncertain_fraction_present | B (ships-as) | 0.0 | 0.0 | 0.0 | <= 0.15 |
| M11_yaw_reversals_per_min | B (ships-as) | 4.635 | 4.62 | 4.65 | <= 24.0 |
| M11_yaw_saturated_fraction | B (ships-as) | 0.0 | 0.0 | 0.0 | <= 0.25 |
| M11_yaw_reversals_per_min | A (proven) | 0.0 | 0.0 | 0.0 | <= 8.0 |
| M11_yaw_saturated_fraction | A (proven) | 0.0 | 0.0 | 0.0 | <= 0.25 |
| M11_yaw_reversals_per_min | B (proven) | 4.79 | 4.17 | 4.87 | <= 24.0 |
| M11_yaw_saturated_fraction | B (proven) | 0.0 | 0.0 | 0.0 | <= 0.25 |
| M11_yaw_reversals_per_min | B (chip/clean/full) | 4.71 | 4.68 | 4.71 | <= 24.0 |
| M11_yaw_saturated_fraction | B (chip/clean/full) | 0.0 | 0.0 | 0.0 | <= 0.25 |
| M1_tracking_fraction | B (float/himax_typical/full) | 0.996 | 0.996 | 0.996 | >= 0.9 |
| M2_heading_err_mean_deg | B (float/himax_typical/full) | 2.87 | 2.68 | 3.0 | <= 8.0 |
| M10_uncertain_fraction_present | B (float/himax_typical/full) | 0.0 | 0.0 | 0.0056 | <= 0.15 |
| M11_yaw_reversals_per_min | B (float/himax_typical/full) | 4.73 | 4.72 | 4.9 | <= 24.0 |
| M11_yaw_saturated_fraction | B (float/himax_typical/full) | 0.0 | 0.0 | 0.0 | <= 0.25 |
| M11_yaw_reversals_per_min | B (float/clean/chip) | 4.79 | 4.68 | 4.83 | <= 24.0 |
| M11_yaw_saturated_fraction | B (float/clean/chip) | 0.0 | 0.0 | 0.0 | <= 0.25 |

---

Distances: the drone aims to stop where the person fills the middle size bucket. For a 1.7 m person that is 1.94 m, and anything from 1.62 to 2.43 m is the same bucket, so it is all equally correct. Pointing error is the angle between where the drone is facing and where the person actually is, from the simulator's own ground truth.
