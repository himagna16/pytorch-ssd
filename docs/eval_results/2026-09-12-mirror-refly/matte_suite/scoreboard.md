# Simulator scoreboard - core suite - 12 Sep 2026

**Overall: FAIL.** 4 of 7 checks FAILED (3 passed, 0 measured-only, 0 unusable).
Flights: 22 attempted, 21 valid, 1 invalid, 21 scored (7 cells). Total time: 24 min.

Two setups appear in the table. **ships-as** is what the real drone will be: the chip's own integer network, the realistic camera model, and the chip's 6.5 Hz speed. **proven** is the laptop model on a clean camera at full speed - the setup every September baseline was measured in, so it says whether a problem is new or just the cost of realism.

## What failed

**Person swaying side to side - proven**  
Person swaying side to side: FAILED on M1_tracking_fraction, M10_uncertain_fraction_present, M2_heading_err_max_deg. It pointed at the person within 3.8 deg avg (179.9 worst) and held station at 1.89 m (1.84-1.91 over 3), target 1.94.  
- `M1_tracking_fraction` = 0.937, needs >= 0.95 (verified baselines 98.7-99.7% tracked)
- `M10_uncertain_fraction_present` = 0.072, needs <= 0.05 (confidence is 0.96-1.0 on essentially every frame with a real person)
- `M2_heading_err_max_deg` = 67.76, needs <= 14.0 (verified maxima 7.7-7.9 deg (1.8x margin))

**Person swaying side to side - chip/clean/full**  
Person swaying side to side: FAILED on M1_tracking_fraction, M10_uncertain_fraction_present. It pointed at the person within 3.5 deg avg (179.5 worst) and held station at 2.18 m (2.16-2.35 over 3), target 1.94.  
- `M1_tracking_fraction` = 0.844, needs >= 0.95 (verified baselines 98.7-99.7% tracked)
- `M10_uncertain_fraction_present` = 0.1278, needs <= 0.05 (confidence is 0.96-1.0 on essentially every frame with a real person)

**Person swaying side to side - float/himax_typical/full**  
Person swaying side to side: FAILED on M2_heading_err_max_deg, M7_dist_err_settled_mean_m, M7_final_in_band. It pointed at the person within 23.8 deg avg (142.5 worst) and held station at 2.94 m (2.50-3.09 over 3), target 1.94.  
- `M2_heading_err_max_deg` = 127.86, needs <= 14.0 (verified maxima 7.7-7.9 deg (1.8x margin))
- `M7_dist_err_settled_mean_m` = 1.109, needs <= 0.75 (quantisation floor is +-0.40 m and the approach parks near the far edge (~0.49 m); 0.75 m is ~1.5x that structural floor, and the verified 2.3 m static baseline scores 0.36 m)
- `M7_final_in_band` = 0.0, needs == 1.0 (the hold band is every distance the size head calls bucket 2, widened 10% (band [1.457, 2.671] m))

**Person swaying side to side - float/clean/chip**  
Person swaying side to side: FAILED on M10_uncertain_fraction_present. It pointed at the person within 3.2 deg avg (10.8 worst) and held station at 1.97 m (1.83-2.25 over 3), target 1.94.  
- `M10_uncertain_fraction_present` = 0.0569, needs <= 0.05 (confidence is 0.96-1.0 on essentially every frame with a real person)

## All checks

| Scene | What it tests | Setup | Tracked | Pointing error | Distance held | False follows | Verdict |
|---|---|---|---|---|---|---|---|
| Person standing still | person, standing still | ships-as | 99.1% | 3.1 deg avg (146.8 worst) | 2.12 m (2.02-2.70 over 3), target 1.94 | 0 | PASS |
| Person swaying side to side | person, moving | ships-as | 96.7% | 3.6 deg avg (44.8 worst) | 2.44 m (2.32-2.56 over 3), target 1.94 | 0 | PASS |
| Person standing still | person, standing still | proven | 99.6% | 1.8 deg avg (174.1 worst) | 1.79 m (1.60-1.88 over 3), target 1.94 | 0 | PASS |
| Person swaying side to side | person, moving | proven | 93.7% | 3.8 deg avg (179.9 worst) | 1.89 m (1.84-1.91 over 3), target 1.94 | 0 | **FAIL** |
| Person swaying side to side | person, moving | chip/clean/full | 84.4% | 3.5 deg avg (179.5 worst) | 2.18 m (2.16-2.35 over 3), target 1.94 | 0 | **FAIL** |
| Person swaying side to side | person, moving | float/himax_typical/full | 55.2% | 23.8 deg avg (142.5 worst) | 2.94 m (2.50-3.09 over 3), target 1.94 | 0 | **FAIL** |
| Person swaying side to side | person, moving | float/clean/chip | 98.0% | 3.2 deg avg (10.8 worst) | 1.97 m (1.83-2.25 over 3), target 1.94 | 0 | **FAIL** |

## What each scene means, in one line

- _ships-as_ - Person standing still: followed correctly. It pointed at the person within 3.1 deg avg (146.8 worst) and held station at 2.12 m (2.02-2.70 over 3), target 1.94.
- _ships-as_ - Person swaying side to side: followed correctly. It pointed at the person within 3.6 deg avg (44.8 worst) and held station at 2.44 m (2.32-2.56 over 3), target 1.94.
- _proven_ - Person standing still: followed correctly. It pointed at the person within 1.8 deg avg (174.1 worst) and held station at 1.79 m (1.60-1.88 over 3), target 1.94.
- _proven_ - Person swaying side to side: FAILED on M1_tracking_fraction, M10_uncertain_fraction_present, M2_heading_err_max_deg. It pointed at the person within 3.8 deg avg (179.9 worst) and held station at 1.89 m (1.84-1.91 over 3), target 1.94.
- _chip/clean/full_ - Person swaying side to side: FAILED on M1_tracking_fraction, M10_uncertain_fraction_present. It pointed at the person within 3.5 deg avg (179.5 worst) and held station at 2.18 m (2.16-2.35 over 3), target 1.94.
- _float/himax_typical/full_ - Person swaying side to side: FAILED on M2_heading_err_max_deg, M7_dist_err_settled_mean_m, M7_final_in_band. It pointed at the person within 23.8 deg avg (142.5 worst) and held station at 2.94 m (2.50-3.09 over 3), target 1.94.
- _float/clean/chip_ - Person swaying side to side: FAILED on M10_uncertain_fraction_present. It pointed at the person within 3.2 deg avg (10.8 worst) and held station at 1.97 m (1.83-2.25 over 3), target 1.94.

## Measured-only checks

These have no pass mark yet, on purpose - we are collecting the first numbers.

- Dog / teddy false-follow rate (decides champion vs confuser model)
- Steering smoothness (pass mark set from this sweep - spec section 4, M11)
- Every threshold on the realistic camera (no verified baseline yet - spec section 5)

## Provisional numbers observed in this sweep (for calibrating v2.1)

| metric | scene class | median | min | max | provisional threshold |
|---|---|---|---|---|---|
| M1_tracking_fraction | A (ships-as) | 0.991 | 0.227 | 0.991 | >= 0.9 |
| M2_heading_err_mean_deg | A (ships-as) | 3.06 | 2.66 | 35.1 | <= 8.0 |
| M10_uncertain_fraction_present | A (ships-as) | 0.0896 | 0.0744 | 0.3621 | <= 0.15 |
| M11_yaw_reversals_per_min | A (ships-as) | 0.0 | 0.0 | 0.0 | <= 8.0 |
| M11_yaw_saturated_fraction | A (ships-as) | 0.0 | 0.0 | 0.0 | <= 0.25 |
| M1_tracking_fraction | B (ships-as) | 0.967 | 0.914 | 0.991 | >= 0.9 |
| M2_heading_err_mean_deg | B (ships-as) | 3.6 | 3.32 | 3.78 | <= 10.0 |
| M10_uncertain_fraction_present | B (ships-as) | 0.0505 | 0.0458 | 0.1095 | <= 0.15 |
| M11_yaw_reversals_per_min | B (ships-as) | 5.34 | 4.82 | 5.53 | <= 24.0 |
| M11_yaw_saturated_fraction | B (ships-as) | 0.0 | 0.0 | 0.0 | <= 0.25 |
| M11_yaw_reversals_per_min | A (proven) | 0.0 | 0.0 | 1.78 | <= 8.0 |
| M11_yaw_saturated_fraction | A (proven) | 0.0 | 0.0 | 0.0 | <= 0.25 |
| M11_yaw_reversals_per_min | B (proven) | 4.68 | 3.1 | 8.02 | <= 24.0 |
| M11_yaw_saturated_fraction | B (proven) | 0.0 | 0.0 | 0.0 | <= 0.25 |
| M11_yaw_reversals_per_min | B (chip/clean/full) | 4.67 | 1.58 | 4.67 | <= 24.0 |
| M11_yaw_saturated_fraction | B (chip/clean/full) | 0.0 | 0.0 | 0.0 | <= 0.25 |
| M1_tracking_fraction | B (float/himax_typical/full) | 0.552 | 0.323 | 0.966 | >= 0.9 |
| M2_heading_err_mean_deg | B (float/himax_typical/full) | 23.82 | 13.7 | 31.69 | <= 8.0 |
| M10_uncertain_fraction_present | B (float/himax_typical/full) | 0.0258 | 0.0083 | 0.0345 | <= 0.15 |
| M11_yaw_reversals_per_min | B (float/himax_typical/full) | 3.29 | 0.0 | 4.91 | <= 24.0 |
| M11_yaw_saturated_fraction | B (float/himax_typical/full) | 0.0 | 0.0 | 0.0731 | <= 0.25 |
| M11_yaw_reversals_per_min | B (float/clean/chip) | 4.69 | 4.69 | 5.23 | <= 24.0 |
| M11_yaw_saturated_fraction | B (float/clean/chip) | 0.0 | 0.0 | 0.0 | <= 0.25 |

---

Distances: the drone aims to stop where the person fills the middle size bucket. For a 1.7 m person that is 1.94 m, and anything from 1.62 to 2.43 m is the same bucket, so it is all equally correct. Pointing error is the angle between where the drone is facing and where the person actually is, from the simulator's own ground truth.
