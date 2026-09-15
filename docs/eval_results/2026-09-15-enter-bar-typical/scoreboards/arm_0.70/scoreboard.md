# Simulator scoreboard - enter-bar arm 0.70 suite - 15 Sep 2026

**Overall: FAIL.** 4 of 6 checks FAILED (2 passed, 0 measured-only, 0 unusable).
Flights: 20 attempted, 18 valid, 2 invalid, 18 scored (6 cells). Total time: 0 min.

Two setups appear in the table. **ships-as** is what the real drone will be: the chip's own integer network, the realistic camera model, and the chip's 6.5 Hz speed. **proven** is the laptop model on a clean camera at full speed - the setup every September baseline was measured in, so it says whether a problem is new or just the cost of realism.

## What failed

**tp15_static_median - ships-as**  
tp15_static_median: FAILED on M2_heading_err_max_deg, M7_dist_err_settled_mean_m, M7_final_in_band. It pointed at the person within 15.9 deg avg (15.9 worst) and held station at 3.64 m, target 1.94.  
- `M2_heading_err_max_deg` = 15.95, needs <= 12.0 (verified maxima 7.7-7.9 deg (1.6x margin))
- `M7_dist_err_settled_mean_m` = 1.698, needs <= 0.75 (quantisation floor is +-0.40 m and the approach parks near the far edge (~0.49 m); 0.75 m is ~1.5x that structural floor, and the verified 2.3 m static baseline scores 0.36 m)
- `M7_final_in_band` = 0.0, needs == 1.0 (the hold band is every distance the size head calls bucket 2, widened 10% (band [1.457, 2.671] m))

**tp15_static_p25 - ships-as**  
tp15_static_p25: FAILED on M2_heading_err_max_deg, M7_dist_err_settled_mean_m, M7_final_in_band. It pointed at the person within 15.9 deg avg (15.9 worst) and held station at 3.64 m, target 1.94.  
- `M2_heading_err_max_deg` = 15.95, needs <= 12.0 (verified maxima 7.7-7.9 deg (1.6x margin))
- `M7_dist_err_settled_mean_m` = 1.698, needs <= 0.75 (quantisation floor is +-0.40 m and the approach parks near the far edge (~0.49 m); 0.75 m is ~1.5x that structural floor, and the verified 2.3 m static baseline scores 0.36 m)
- `M7_final_in_band` = 0.0, needs == 1.0 (the hold band is every distance the size head calls bucket 2, widened 10% (band [1.457, 2.671] m))

**tp01_moving_median - ships-as**  
tp01_moving_median: FAILED on M2_heading_err_max_deg, M7_dist_err_settled_mean_m, M7_final_in_band. It pointed at the person within 15.1 deg avg (30.7 worst) and held station at 2.76 m (2.65-3.03 over 3), target 1.94.  
- `M2_heading_err_max_deg` = 25.29, needs <= 14.0 (verified maxima 7.7-7.9 deg (1.8x margin))
- `M7_dist_err_settled_mean_m` = 0.859, needs <= 0.75 (quantisation floor is +-0.40 m and the approach parks near the far edge (~0.49 m); 0.75 m is ~1.5x that structural floor, and the verified 2.3 m static baseline scores 0.36 m)
- `M7_final_in_band` = 0.0, needs == 1.0 (the hold band is every distance the size head calls bucket 2, widened 10% (band [1.457, 2.671] m))

**tp01_moving_p25 - ships-as**  
tp01_moving_p25: FAILED on M2_heading_err_max_deg, M7_dist_err_settled_mean_m, M7_final_in_band. It pointed at the person within 14.1 deg avg (21.8 worst) and held station at 3.14 m, target 1.94.  
- `M2_heading_err_max_deg` = 21.78, needs <= 14.0 (verified maxima 7.7-7.9 deg (1.8x margin))
- `M7_dist_err_settled_mean_m` = 1.222, needs <= 0.75 (quantisation floor is +-0.40 m and the approach parks near the far edge (~0.49 m); 0.75 m is ~1.5x that structural floor, and the verified 2.3 m static baseline scores 0.36 m)
- `M7_final_in_band` = 0.0, needs == 1.0 (the hold band is every distance the size head calls bucket 2, widened 10% (band [1.457, 2.671] m))

## All checks

| Scene | What it tests | Setup | Tracked | Pointing error | Distance held | False follows | Verdict |
|---|---|---|---|---|---|---|---|
| Person standing still | person, standing still | ships-as | 99.0% | 3.6 deg avg (5.9 worst) | 2.19 m (2.12-2.40 over 3), target 1.94 | 0 | PASS |
| tp15_static_median | person, standing still | ships-as | 0.0% | 15.9 deg avg (15.9 worst) | 3.64 m, target 1.94 | 0 | **FAIL** |
| tp15_static_p25 | person, standing still | ships-as | 0.0% | 15.9 deg avg (15.9 worst) | 3.64 m, target 1.94 | 0 | **FAIL** |
| Person swaying side to side | person, moving | ships-as | 99.2% | 3.3 deg avg (9.2 worst) | 2.37 m (2.23-2.42 over 3), target 1.94 | 0 | PASS |
| tp01_moving_median | person, moving | ships-as | 1.3% | 15.1 deg avg (30.7 worst) | 2.76 m (2.65-3.03 over 3), target 1.94 | 0 | **FAIL** |
| tp01_moving_p25 | person, moving | ships-as | 0.0% | 14.1 deg avg (21.8 worst) | 3.14 m, target 1.94 | 0 | **FAIL** |

## What each scene means, in one line

- _ships-as_ - Person standing still: followed correctly. It pointed at the person within 3.6 deg avg (5.9 worst) and held station at 2.19 m (2.12-2.40 over 3), target 1.94.
- _ships-as_ - tp15_static_median: FAILED on M2_heading_err_max_deg, M7_dist_err_settled_mean_m, M7_final_in_band. It pointed at the person within 15.9 deg avg (15.9 worst) and held station at 3.64 m, target 1.94.
- _ships-as_ - tp15_static_p25: FAILED on M2_heading_err_max_deg, M7_dist_err_settled_mean_m, M7_final_in_band. It pointed at the person within 15.9 deg avg (15.9 worst) and held station at 3.64 m, target 1.94.
- _ships-as_ - Person swaying side to side: followed correctly. It pointed at the person within 3.3 deg avg (9.2 worst) and held station at 2.37 m (2.23-2.42 over 3), target 1.94.
- _ships-as_ - tp01_moving_median: FAILED on M2_heading_err_max_deg, M7_dist_err_settled_mean_m, M7_final_in_band. It pointed at the person within 15.1 deg avg (30.7 worst) and held station at 2.76 m (2.65-3.03 over 3), target 1.94.
- _ships-as_ - tp01_moving_p25: FAILED on M2_heading_err_max_deg, M7_dist_err_settled_mean_m, M7_final_in_band. It pointed at the person within 14.1 deg avg (21.8 worst) and held station at 3.14 m, target 1.94.

## Measured-only checks

These have no pass mark yet, on purpose - we are collecting the first numbers.

- Dog / teddy false-follow rate (decides champion vs confuser model)
- Steering smoothness (pass mark set from this sweep - spec section 4, M11)
- Every threshold on the realistic camera (no verified baseline yet - spec section 5)

## Provisional numbers observed in this sweep (for calibrating v2.1)

| metric | scene class | median | min | max | provisional threshold |
|---|---|---|---|---|---|
| M1_tracking_fraction | A (ships-as) | 0.99 | 0.971 | 0.991 | >= 0.9 |
| M2_heading_err_mean_deg | A (ships-as) | 3.59 | 3.47 | 4.49 | <= 8.0 |
| M10_uncertain_fraction_present | A (ships-as) | 0.1194 | 0.1171 | 0.1274 | <= 0.15 |
| M11_yaw_reversals_per_min | A (ships-as) | 0.0 | 0.0 | 1.87 | <= 8.0 |
| M11_yaw_saturated_fraction | A (ships-as) | 0.0 | 0.0 | 0.0 | <= 0.25 |
| M1_tracking_fraction | A (ships-as) | 0.0 | 0.0 | 0.0 | >= 0.9 |
| M2_heading_err_mean_deg | A (ships-as) | 15.95 | 15.95 | 15.95 | <= 8.0 |
| M10_uncertain_fraction_present | A (ships-as) | 0.0 | 0.0 | 0.0 | <= 0.15 |
| M11_yaw_reversals_per_min | A (ships-as) | 0.0 | 0.0 | 0.0 | <= 8.0 |
| M11_yaw_saturated_fraction | A (ships-as) | 0.0 | 0.0 | 0.0 | <= 0.25 |
| M1_tracking_fraction | A (ships-as) | 0.0 | 0.0 | 0.0 | >= 0.9 |
| M2_heading_err_mean_deg | A (ships-as) | 15.95 | 15.95 | 15.95 | <= 8.0 |
| M10_uncertain_fraction_present | A (ships-as) | 0.0 | 0.0 | 0.0 | <= 0.15 |
| M11_yaw_reversals_per_min | A (ships-as) | 0.0 | 0.0 | 0.0 | <= 8.0 |
| M11_yaw_saturated_fraction | A (ships-as) | 0.0 | 0.0 | 0.0 | <= 0.25 |
| M1_tracking_fraction | B (ships-as) | 0.992 | 0.991 | 0.992 | >= 0.9 |
| M2_heading_err_mean_deg | B (ships-as) | 3.32 | 3.19 | 3.53 | <= 10.0 |
| M10_uncertain_fraction_present | B (ships-as) | 0.0705 | 0.0598 | 0.0747 | <= 0.15 |
| M11_yaw_reversals_per_min | B (ships-as) | 3.28 | 3.18 | 4.78 | <= 24.0 |
| M11_yaw_saturated_fraction | B (ships-as) | 0.0 | 0.0 | 0.0 | <= 0.25 |
| M1_tracking_fraction | B (ships-as) | 0.013 | 0.013 | 0.038 | >= 0.9 |
| M2_heading_err_mean_deg | B (ships-as) | 15.14 | 14.02 | 15.64 | <= 10.0 |
| M10_uncertain_fraction_present | B (ships-as) | 0.5167 | 0.5042 | 0.6083 | <= 0.15 |
| M11_yaw_reversals_per_min | B (ships-as) | 0.0 | 0.0 | 0.0 | <= 24.0 |
| M11_yaw_saturated_fraction | B (ships-as) | 0.0 | 0.0 | 0.3333 | <= 0.25 |
| M1_tracking_fraction | B (ships-as) | 0.0 | 0.0 | 0.0 | >= 0.9 |
| M2_heading_err_mean_deg | B (ships-as) | 14.08 | 14.07 | 14.28 | <= 10.0 |
| M10_uncertain_fraction_present | B (ships-as) | 0.2105 | 0.1471 | 0.2257 | <= 0.15 |
| M11_yaw_reversals_per_min | B (ships-as) | 0.0 | 0.0 | 0.0 | <= 24.0 |
| M11_yaw_saturated_fraction | B (ships-as) | 0.0 | 0.0 | 0.0 | <= 0.25 |

---

Distances: the drone aims to stop where the person fills the middle size bucket. For a 1.7 m person that is 1.94 m, and anything from 1.62 to 2.43 m is the same bucket, so it is all equally correct. Pointing error is the angle between where the drone is facing and where the person actually is, from the simulator's own ground truth.
