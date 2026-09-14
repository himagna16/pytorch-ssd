# Simulator scoreboard - cameras suite - 14 Sep 2026

**Overall: FAIL.** 2 of 2 checks FAILED (0 passed, 0 measured-only, 0 unusable).
Flights: 4 attempted, 4 valid, 0 invalid, 4 scored (2 cells). Total time: 4 min.

Two setups appear in the table. **ships-as** is what the real drone will be: the chip's own integer network, the realistic camera model, and the chip's 6.5 Hz speed. **proven** is the laptop model on a clean camera at full speed - the setup every September baseline was measured in, so it says whether a problem is new or just the cost of realism.

## What failed

**Person swaying side to side - float/himax_color_bayer/full**  
Person swaying side to side: FAILED on M1_tracking_fraction, M10_uncertain_fraction_present. It pointed at the person within 2.9 deg avg (10.4 worst) and held station at 2.51 m (2.47-2.55 over 2), target 1.94.  
- `M1_tracking_fraction` = 0.8545, needs >= 0.95 (verified baselines 98.7-99.7% tracked)
- `M10_uncertain_fraction_present` = 0.2552, needs <= 0.05 (confidence is 0.96-1.0 on essentially every frame with a real person)

**Person swaying side to side - float/himax_low_light/full**  
Person swaying side to side: FAILED on M10_uncertain_fraction_present. It pointed at the person within 3.2 deg avg (10.0 worst) and held station at 2.18 m (2.17-2.18 over 2), target 1.94.  
- `M10_uncertain_fraction_present` = 0.0842, needs <= 0.05 (confidence is 0.96-1.0 on essentially every frame with a real person)

## All checks

| Scene | What it tests | Setup | Tracked | Pointing error | Distance held | False follows | Verdict |
|---|---|---|---|---|---|---|---|
| Person swaying side to side | person, moving | float/himax_color_bayer/full | 85.5% | 2.9 deg avg (10.4 worst) | 2.51 m (2.47-2.55 over 2), target 1.94 | 0 | **FAIL** |
| Person swaying side to side | person, moving | float/himax_low_light/full | 98.1% | 3.2 deg avg (10.0 worst) | 2.18 m (2.17-2.18 over 2), target 1.94 | 0 | **FAIL** |

## What each scene means, in one line

- _float/himax_color_bayer/full_ - Person swaying side to side: FAILED on M1_tracking_fraction, M10_uncertain_fraction_present. It pointed at the person within 2.9 deg avg (10.4 worst) and held station at 2.51 m (2.47-2.55 over 2), target 1.94.
- _float/himax_low_light/full_ - Person swaying side to side: FAILED on M10_uncertain_fraction_present. It pointed at the person within 3.2 deg avg (10.0 worst) and held station at 2.18 m (2.17-2.18 over 2), target 1.94.

## Measured-only checks

These have no pass mark yet, on purpose - we are collecting the first numbers.

- Dog / teddy false-follow rate (decides champion vs confuser model)
- Steering smoothness (pass mark set from this sweep - spec section 4, M11)
- Every threshold on the realistic camera (no verified baseline yet - spec section 5)

## Provisional numbers observed in this sweep (for calibrating v2.1)

| metric | scene class | median | min | max | provisional threshold |
|---|---|---|---|---|---|
| M11_yaw_reversals_per_min | B (float/himax_color_bayer/full) | 4.685 | 4.68 | 4.69 | <= 24.0 |
| M11_yaw_saturated_fraction | B (float/himax_color_bayer/full) | 0.0 | 0.0 | 0.0 | <= 0.25 |
| M11_yaw_reversals_per_min | B (float/himax_low_light/full) | 4.835 | 4.75 | 4.92 | <= 24.0 |
| M11_yaw_saturated_fraction | B (float/himax_low_light/full) | 0.0 | 0.0 | 0.0 | <= 0.25 |

---

Distances: the drone aims to stop where the person fills the middle size bucket. For a 1.7 m person that is 1.94 m, and anything from 1.62 to 2.43 m is the same bucket, so it is all equally correct. Pointing error is the angle between where the drone is facing and where the person actually is, from the simulator's own ground truth.
