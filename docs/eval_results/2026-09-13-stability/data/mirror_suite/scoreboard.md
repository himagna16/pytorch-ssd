# Simulator scoreboard - stability_mirror suite - 12 Sep 2026

**Overall: FAIL.** 4 of 7 checks FAILED (3 passed, 0 measured-only, 0 unusable).
Flights: 29 attempted, 28 valid, 1 invalid, 28 scored (7 cells). Total time: 0 min.

Two setups appear in the table. **ships-as** is what the real drone will be: the chip's own integer network, the realistic camera model, and the chip's 6.5 Hz speed. **proven** is the laptop model on a clean camera at full speed - the setup every September baseline was measured in, so it says whether a problem is new or just the cost of realism.

## What failed

**Person standing still - ships-as**  
Person standing still: FAILED on M7_dist_err_settled_mean_m, M7_final_in_band. It pointed at the person within 4.1 deg avg (5.8 worst) and held station at 2.92 m (2.79-3.04 over 4), target 1.94.  
- `M7_dist_err_settled_mean_m` = 1.0525, needs <= 0.75 (quantisation floor is +-0.40 m and the approach parks near the far edge (~0.49 m); 0.75 m is ~1.5x that structural floor, and the verified 2.3 m static baseline scores 0.36 m)
- `M7_final_in_band` = 0.0, needs == 1.0 (the hold band is every distance the size head calls bucket 2, widened 10% (band [1.457, 2.671] m))

**Person swaying side to side - ships-as**  
Person swaying side to side: FAILED on M7_dist_err_settled_mean_m, M7_final_in_band. It pointed at the person within 3.2 deg avg (8.7 worst) and held station at 3.18 m (3.12-3.27 over 4), target 1.94.  
- `M7_dist_err_settled_mean_m` = 1.1585, needs <= 0.75 (quantisation floor is +-0.40 m and the approach parks near the far edge (~0.49 m); 0.75 m is ~1.5x that structural floor, and the verified 2.3 m static baseline scores 0.36 m)
- `M7_final_in_band` = 0.0, needs == 1.0 (the hold band is every distance the size head calls bucket 2, widened 10% (band [1.457, 2.671] m))

**Person swaying side to side - chip/clean/full**  
Person swaying side to side: FAILED on M7_dist_err_settled_mean_m, M7_final_in_band. It pointed at the person within 2.8 deg avg (8.1 worst) and held station at 2.82 m (2.74-2.86 over 4), target 1.94.  
- `M7_dist_err_settled_mean_m` = 0.8405, needs <= 0.75 (quantisation floor is +-0.40 m and the approach parks near the far edge (~0.49 m); 0.75 m is ~1.5x that structural floor, and the verified 2.3 m static baseline scores 0.36 m)
- `M7_final_in_band` = 0.0, needs == 1.0 (the hold band is every distance the size head calls bucket 2, widened 10% (band [1.457, 2.671] m))

**Person swaying side to side - float/himax_typical/full**  
Person swaying side to side: FAILED on M7_dist_err_settled_mean_m, M7_final_in_band. It pointed at the person within 2.8 deg avg (9.5 worst) and held station at 2.96 m (2.88-3.17 over 4), target 1.94.  
- `M7_dist_err_settled_mean_m` = 0.996, needs <= 0.75 (quantisation floor is +-0.40 m and the approach parks near the far edge (~0.49 m); 0.75 m is ~1.5x that structural floor, and the verified 2.3 m static baseline scores 0.36 m)
- `M7_final_in_band` = 0.0, needs == 1.0 (the hold band is every distance the size head calls bucket 2, widened 10% (band [1.457, 2.671] m))

## All checks

| Scene | What it tests | Setup | Tracked | Pointing error | Distance held | False follows | Verdict |
|---|---|---|---|---|---|---|---|
| Person standing still | person, standing still | ships-as | 99.1% | 4.1 deg avg (5.8 worst) | 2.92 m (2.79-3.04 over 4), target 1.94 | 0 | **FAIL** |
| Person swaying side to side | person, moving | ships-as | 99.2% | 3.2 deg avg (8.7 worst) | 3.18 m (3.12-3.27 over 4), target 1.94 | 0 | **FAIL** |
| Person standing still | person, standing still | proven | 99.6% | 1.0 deg avg (2.6 worst) | 2.42 m (2.34-2.57 over 4), target 1.94 | 0 | PASS |
| Person swaying side to side | person, moving | proven | 99.7% | 2.8 deg avg (8.8 worst) | 2.65 m (2.38-2.67 over 4), target 1.94 | 0 | PASS |
| Person swaying side to side | person, moving | chip/clean/full | 99.6% | 2.8 deg avg (8.1 worst) | 2.82 m (2.74-2.86 over 4), target 1.94 | 0 | **FAIL** |
| Person swaying side to side | person, moving | float/himax_typical/full | 99.6% | 2.8 deg avg (9.5 worst) | 2.96 m (2.88-3.17 over 4), target 1.94 | 0 | **FAIL** |
| Person swaying side to side | person, moving | float/clean/chip | 99.2% | 2.9 deg avg (8.6 worst) | 2.52 m (2.35-2.77 over 4), target 1.94 | 0 | PASS |

## What each scene means, in one line

- _ships-as_ - Person standing still: FAILED on M7_dist_err_settled_mean_m, M7_final_in_band. It pointed at the person within 4.1 deg avg (5.8 worst) and held station at 2.92 m (2.79-3.04 over 4), target 1.94.
- _ships-as_ - Person swaying side to side: FAILED on M7_dist_err_settled_mean_m, M7_final_in_band. It pointed at the person within 3.2 deg avg (8.7 worst) and held station at 3.18 m (3.12-3.27 over 4), target 1.94.
- _proven_ - Person standing still: followed correctly. It pointed at the person within 1.0 deg avg (2.6 worst) and held station at 2.42 m (2.34-2.57 over 4), target 1.94.
- _proven_ - Person swaying side to side: followed correctly. It pointed at the person within 2.8 deg avg (8.8 worst) and held station at 2.65 m (2.38-2.67 over 4), target 1.94.
- _chip/clean/full_ - Person swaying side to side: FAILED on M7_dist_err_settled_mean_m, M7_final_in_band. It pointed at the person within 2.8 deg avg (8.1 worst) and held station at 2.82 m (2.74-2.86 over 4), target 1.94.
- _float/himax_typical/full_ - Person swaying side to side: FAILED on M7_dist_err_settled_mean_m, M7_final_in_band. It pointed at the person within 2.8 deg avg (9.5 worst) and held station at 2.96 m (2.88-3.17 over 4), target 1.94.
- _float/clean/chip_ - Person swaying side to side: followed correctly. It pointed at the person within 2.9 deg avg (8.6 worst) and held station at 2.52 m (2.35-2.77 over 4), target 1.94.

## Measured-only checks

These have no pass mark yet, on purpose - we are collecting the first numbers.

- Dog / teddy false-follow rate (decides champion vs confuser model)
- Steering smoothness (pass mark set from this sweep - spec section 4, M11)
- Every threshold on the realistic camera (no verified baseline yet - spec section 5)

## Provisional numbers observed in this sweep (for calibrating v2.1)

| metric | scene class | median | min | max | provisional threshold |
|---|---|---|---|---|---|
| M1_tracking_fraction | A (ships-as) | 0.9905 | 0.99 | 0.991 | >= 0.9 |
| M2_heading_err_mean_deg | A (ships-as) | 4.07 | 3.22 | 4.74 | <= 8.0 |
| M10_uncertain_fraction_present | A (ships-as) | 0.049 | 0.0 | 0.1981 | <= 0.15 |
| M11_yaw_reversals_per_min | A (ships-as) | 0.0 | 0.0 | 1.83 | <= 8.0 |
| M11_yaw_saturated_fraction | A (ships-as) | 0.0 | 0.0 | 0.0 | <= 0.25 |
| M1_tracking_fraction | B (ships-as) | 0.992 | 0.992 | 0.992 | >= 0.9 |
| M2_heading_err_mean_deg | B (ships-as) | 3.195 | 3.1 | 3.4 | <= 10.0 |
| M10_uncertain_fraction_present | B (ships-as) | 0.0041 | 0.0 | 0.0202 | <= 0.15 |
| M11_yaw_reversals_per_min | B (ships-as) | 4.71 | 4.7 | 4.8 | <= 24.0 |
| M11_yaw_saturated_fraction | B (ships-as) | 0.0 | 0.0 | 0.0 | <= 0.25 |
| M11_yaw_reversals_per_min | A (proven) | 0.0 | 0.0 | 0.0 | <= 8.0 |
| M11_yaw_saturated_fraction | A (proven) | 0.0 | 0.0 | 0.0 | <= 0.25 |
| M11_yaw_reversals_per_min | B (proven) | 4.735 | 4.67 | 4.83 | <= 24.0 |
| M11_yaw_saturated_fraction | B (proven) | 0.0 | 0.0 | 0.0 | <= 0.25 |
| M11_yaw_reversals_per_min | B (chip/clean/full) | 4.755 | 4.64 | 4.8 | <= 24.0 |
| M11_yaw_saturated_fraction | B (chip/clean/full) | 0.0 | 0.0 | 0.0 | <= 0.25 |
| M1_tracking_fraction | B (float/himax_typical/full) | 0.996 | 0.996 | 0.996 | >= 0.9 |
| M2_heading_err_mean_deg | B (float/himax_typical/full) | 2.765 | 2.6 | 2.88 | <= 8.0 |
| M10_uncertain_fraction_present | B (float/himax_typical/full) | 0.0 | 0.0 | 0.0 | <= 0.15 |
| M11_yaw_reversals_per_min | B (float/himax_typical/full) | 4.77 | 4.71 | 4.83 | <= 24.0 |
| M11_yaw_saturated_fraction | B (float/himax_typical/full) | 0.0 | 0.0 | 0.0 | <= 0.25 |
| M11_yaw_reversals_per_min | B (float/clean/chip) | 4.735 | 4.7 | 4.8 | <= 24.0 |
| M11_yaw_saturated_fraction | B (float/clean/chip) | 0.0 | 0.0 | 0.0 | <= 0.25 |

---

Distances: the drone aims to stop where the person fills the middle size bucket. For a 1.7 m person that is 1.94 m, and anything from 1.62 to 2.43 m is the same bucket, so it is all equally correct. Pointing error is the angle between where the drone is facing and where the person actually is, from the simulator's own ground truth.
