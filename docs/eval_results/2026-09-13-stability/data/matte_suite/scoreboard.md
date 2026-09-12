# Simulator scoreboard - stability_matte suite - 12 Sep 2026

**Overall: FAIL.** 3 of 7 checks FAILED (4 passed, 0 measured-only, 0 unusable).
Flights: 28 attempted, 28 valid, 0 invalid, 28 scored (7 cells). Total time: 0 min.

Two setups appear in the table. **ships-as** is what the real drone will be: the chip's own integer network, the realistic camera model, and the chip's 6.5 Hz speed. **proven** is the laptop model on a clean camera at full speed - the setup every September baseline was measured in, so it says whether a problem is new or just the cost of realism.

## What failed

**Person swaying side to side - proven**  
Person swaying side to side: FAILED on M10_uncertain_fraction_present. It pointed at the person within 3.1 deg avg (8.9 worst) and held station at 2.15 m (1.95-2.20 over 4), target 1.94.  
- `M10_uncertain_fraction_present` = 0.0599, needs <= 0.05 (confidence is 0.96-1.0 on essentially every frame with a real person)

**Person swaying side to side - chip/clean/full**  
Person swaying side to side: FAILED on M1_tracking_fraction, M10_uncertain_fraction_present. It pointed at the person within 2.8 deg avg (9.7 worst) and held station at 2.16 m (2.05-2.21 over 4), target 1.94.  
- `M1_tracking_fraction` = 0.9235, needs >= 0.95 (verified baselines 98.7-99.7% tracked)
- `M10_uncertain_fraction_present` = 0.1071, needs <= 0.05 (confidence is 0.96-1.0 on essentially every frame with a real person)

**Person swaying side to side - float/clean/chip**  
Person swaying side to side: FAILED on M10_uncertain_fraction_present. It pointed at the person within 3.0 deg avg (10.9 worst) and held station at 2.10 m (1.83-2.21 over 4), target 1.94.  
- `M10_uncertain_fraction_present` = 0.0725, needs <= 0.05 (confidence is 0.96-1.0 on essentially every frame with a real person)

## All checks

| Scene | What it tests | Setup | Tracked | Pointing error | Distance held | False follows | Verdict |
|---|---|---|---|---|---|---|---|
| Person standing still | person, standing still | ships-as | 99.0% | 3.3 deg avg (4.8 worst) | 2.21 m (1.89-2.32 over 4), target 1.94 | 0 | PASS |
| Person swaying side to side | person, moving | ships-as | 98.6% | 3.3 deg avg (9.5 worst) | 2.43 m (2.18-2.54 over 4), target 1.94 | 0 | PASS |
| Person standing still | person, standing still | proven | 99.6% | 0.9 deg avg (2.8 worst) | 1.97 m (1.67-2.09 over 4), target 1.94 | 0 | PASS |
| Person swaying side to side | person, moving | proven | 98.9% | 3.1 deg avg (8.9 worst) | 2.15 m (1.95-2.20 over 4), target 1.94 | 0 | **FAIL** |
| Person swaying side to side | person, moving | chip/clean/full | 92.3% | 2.8 deg avg (9.7 worst) | 2.16 m (2.05-2.21 over 4), target 1.94 | 0 | **FAIL** |
| Person swaying side to side | person, moving | float/himax_typical/full | 99.6% | 3.2 deg avg (10.5 worst) | 2.32 m (2.13-2.35 over 4), target 1.94 | 0 | PASS |
| Person swaying side to side | person, moving | float/clean/chip | 96.9% | 3.0 deg avg (10.9 worst) | 2.10 m (1.83-2.21 over 4), target 1.94 | 0 | **FAIL** |

## What each scene means, in one line

- _ships-as_ - Person standing still: followed correctly. It pointed at the person within 3.3 deg avg (4.8 worst) and held station at 2.21 m (1.89-2.32 over 4), target 1.94.
- _ships-as_ - Person swaying side to side: followed correctly. It pointed at the person within 3.3 deg avg (9.5 worst) and held station at 2.43 m (2.18-2.54 over 4), target 1.94.
- _proven_ - Person standing still: followed correctly. It pointed at the person within 0.9 deg avg (2.8 worst) and held station at 1.97 m (1.67-2.09 over 4), target 1.94.
- _proven_ - Person swaying side to side: FAILED on M10_uncertain_fraction_present. It pointed at the person within 3.1 deg avg (8.9 worst) and held station at 2.15 m (1.95-2.20 over 4), target 1.94.
- _chip/clean/full_ - Person swaying side to side: FAILED on M1_tracking_fraction, M10_uncertain_fraction_present. It pointed at the person within 2.8 deg avg (9.7 worst) and held station at 2.16 m (2.05-2.21 over 4), target 1.94.
- _float/himax_typical/full_ - Person swaying side to side: followed correctly. It pointed at the person within 3.2 deg avg (10.5 worst) and held station at 2.32 m (2.13-2.35 over 4), target 1.94.
- _float/clean/chip_ - Person swaying side to side: FAILED on M10_uncertain_fraction_present. It pointed at the person within 3.0 deg avg (10.9 worst) and held station at 2.10 m (1.83-2.21 over 4), target 1.94.

## Measured-only checks

These have no pass mark yet, on purpose - we are collecting the first numbers.

- Dog / teddy false-follow rate (decides champion vs confuser model)
- Steering smoothness (pass mark set from this sweep - spec section 4, M11)
- Every threshold on the realistic camera (no verified baseline yet - spec section 5)

## Provisional numbers observed in this sweep (for calibrating v2.1)

| metric | scene class | median | min | max | provisional threshold |
|---|---|---|---|---|---|
| M1_tracking_fraction | A (ships-as) | 0.99 | 0.43 | 0.991 | >= 0.9 |
| M2_heading_err_mean_deg | A (ships-as) | 3.335 | 1.73 | 4.62 | <= 8.0 |
| M10_uncertain_fraction_present | A (ships-as) | 0.101 | 0.0519 | 0.6473 | <= 0.15 |
| M11_yaw_reversals_per_min | A (ships-as) | 0.0 | 0.0 | 0.0 | <= 8.0 |
| M11_yaw_saturated_fraction | A (ships-as) | 0.0 | 0.0 | 0.0 | <= 0.25 |
| M1_tracking_fraction | B (ships-as) | 0.986 | 0.905 | 0.992 | >= 0.9 |
| M2_heading_err_mean_deg | B (ships-as) | 3.255 | 3.08 | 3.39 | <= 10.0 |
| M10_uncertain_fraction_present | B (ships-as) | 0.0595 | 0.0456 | 0.0823 | <= 0.15 |
| M11_yaw_reversals_per_min | B (ships-as) | 4.77 | 4.74 | 4.79 | <= 24.0 |
| M11_yaw_saturated_fraction | B (ships-as) | 0.0 | 0.0 | 0.0 | <= 0.25 |
| M11_yaw_reversals_per_min | A (proven) | 0.0 | 0.0 | 0.0 | <= 8.0 |
| M11_yaw_saturated_fraction | A (proven) | 0.0 | 0.0 | 0.0 | <= 0.25 |
| M11_yaw_reversals_per_min | B (proven) | 4.72 | 4.64 | 4.85 | <= 24.0 |
| M11_yaw_saturated_fraction | B (proven) | 0.0 | 0.0 | 0.0 | <= 0.25 |
| M11_yaw_reversals_per_min | B (chip/clean/full) | 4.69 | 4.66 | 4.81 | <= 24.0 |
| M11_yaw_saturated_fraction | B (chip/clean/full) | 0.0 | 0.0 | 0.0 | <= 0.25 |
| M1_tracking_fraction | B (float/himax_typical/full) | 0.996 | 0.986 | 0.996 | >= 0.9 |
| M2_heading_err_mean_deg | B (float/himax_typical/full) | 3.16 | 2.99 | 3.45 | <= 8.0 |
| M10_uncertain_fraction_present | B (float/himax_typical/full) | 0.0073 | 0.0036 | 0.0125 | <= 0.15 |
| M11_yaw_reversals_per_min | B (float/himax_typical/full) | 4.725 | 4.69 | 4.8 | <= 24.0 |
| M11_yaw_saturated_fraction | B (float/himax_typical/full) | 0.0 | 0.0 | 0.0 | <= 0.25 |
| M11_yaw_reversals_per_min | B (float/clean/chip) | 4.74 | 4.68 | 4.86 | <= 24.0 |
| M11_yaw_saturated_fraction | B (float/clean/chip) | 0.0 | 0.0 | 0.0 | <= 0.25 |

---

Distances: the drone aims to stop where the person fills the middle size bucket. For a 1.7 m person that is 1.94 m, and anything from 1.62 to 2.43 m is the same bucket, so it is all equally correct. Pointing error is the angle between where the drone is facing and where the person actually is, from the simulator's own ground truth.
