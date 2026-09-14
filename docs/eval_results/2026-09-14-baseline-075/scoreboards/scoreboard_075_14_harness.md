# Simulator scoreboard - core suite - 14 Sep 2026

**Overall: FAIL.** 6 of 14 checks FAILED (8 passed, 0 measured-only, 0 unusable).
Flights: 56 attempted, 56 valid, 0 invalid, 56 scored (14 cells). Total time: 58 min.

Two setups appear in the table. **ships-as** is what the real drone will be: the chip's own integer network, the realistic camera model, and the chip's 6.5 Hz speed. **proven** is the laptop model on a clean camera at full speed - the setup every September baseline was measured in, so it says whether a problem is new or just the cost of realism.

## What failed

**Person walks behind a partition - ships-as**  
Person walks behind a partition: it lost the track for up to 16.4 s, and once the person was properly back in view it took 2.75 s to start following again; it correctly waited for 3 fresh frames before steering again. FAILED.  
- `M9_gt_visible_to_relatch_s` = 2.75, needs <= 1.5 (the spec's own M9 reacquire gate (1.0 s at full rate, 1.5 s at chip speed) applied to the quantity section 4 actually describes: time from the target being continuously visible in ground truth until the track re-latches. Not a new threshold, an existing one finally pointed at the right measurement)

**A dog and a cat, no people - ships-as**  
A dog and a cat, no people: it locked onto an animal/toy 3 time(s), tracked it for 9% of the flight and moved 0.58 m. Measured, not graded - this is the number that decides champion vs confuser.  
- `M6_max_horizontal_drift_m` = 0.734, needs < 0.5 (a distractor may capture the track, but it must not fly across the room)

**Person swaying side to side - proven**  
Person swaying side to side: FAILED on M10_uncertain_fraction_present. It pointed at the person within 3.0 deg avg (9.2 worst) and held station at 1.87 m (1.72-1.99 over 4), target 1.94.  
- `M10_uncertain_fraction_present` = 0.0875, needs <= 0.05 (confidence is 0.96-1.0 on essentially every frame with a real person)

**Person walks behind a partition - proven**  
Person walks behind a partition: it lost the track for up to 5.4 s, and once the person was properly back in view it took 2.18 s to start following again; it correctly waited for 3 fresh frames before steering again. FAILED.  
- `M9_gt_visible_to_relatch_s` = 2.182, needs <= 1.0 (the spec's own M9 reacquire gate (1.0 s at full rate, 1.5 s at chip speed) applied to the quantity section 4 actually describes: time from the target being continuously visible in ground truth until the track re-latches. Not a new threshold, an existing one finally pointed at the right measurement)

**Person swaying side to side - chip/clean/full**  
Person swaying side to side: FAILED on M1_tracking_fraction, M10_uncertain_fraction_present. It pointed at the person within 3.3 deg avg (8.3 worst) and held station at 2.00 m (1.88-2.11 over 4), target 1.94.  
- `M1_tracking_fraction` = 0.917, needs >= 0.95 (verified baselines 98.7-99.7% tracked)
- `M10_uncertain_fraction_present` = 0.1703, needs <= 0.05 (confidence is 0.96-1.0 on essentially every frame with a real person)

**Person swaying side to side - float/clean/chip**  
Person swaying side to side: FAILED on M10_uncertain_fraction_present. It pointed at the person within 3.2 deg avg (10.8 worst) and held station at 1.74 m (1.69-1.87 over 4), target 1.94.  
- `M10_uncertain_fraction_present` = 0.1074, needs <= 0.05 (confidence is 0.96-1.0 on essentially every frame with a real person)

## All checks

| Scene | What it tests | Setup | Tracked | Pointing error | Distance held | False follows | Verdict |
|---|---|---|---|---|---|---|---|
| Person standing still | person, standing still | ships-as | 99.1% | 3.0 deg avg (4.8 worst) | 2.19 m (2.06-2.24 over 4), target 1.94 | 0 | PASS |
| Person swaying side to side | person, moving | ships-as | 99.2% | 3.3 deg avg (9.9 worst) | 2.44 m (2.35-2.44 over 4), target 1.94 | 0 | PASS |
| Empty room | nobody present | ships-as | 0.0% | n/a | n/a | 0 | PASS |
| Person walks behind a partition | person hidden then seen again | ships-as | 47.2% | 7.2 deg avg (55.4 worst) | n/a | 0 | **FAIL** |
| Furniture and boxes, nobody home | inanimate distractor | ships-as | 0.0% | n/a | n/a | 0 | PASS |
| A dog and a cat, no people | animate distractor | ships-as | 9.2% | n/a | n/a | 3 | **FAIL** |
| Person standing still | person, standing still | proven | 99.6% | 1.3 deg avg (1.8 worst) | 1.63 m (1.55-1.93 over 4), target 1.94 | 0 | PASS |
| Person swaying side to side | person, moving | proven | 98.2% | 3.0 deg avg (9.2 worst) | 1.87 m (1.72-1.99 over 4), target 1.94 | 0 | **FAIL** |
| Empty room | nobody present | proven | 0.0% | n/a | n/a | 0 | PASS |
| Person walks behind a partition | person hidden then seen again | proven | 87.8% | 3.3 deg avg (10.5 worst) | n/a | 0 | **FAIL** |
| Furniture and boxes, nobody home | inanimate distractor | proven | 0.0% | n/a | n/a | 0 | PASS |
| Person swaying side to side | person, moving | chip/clean/full | 91.7% | 3.3 deg avg (8.3 worst) | 2.00 m (1.88-2.11 over 4), target 1.94 | 0 | **FAIL** |
| Person swaying side to side | person, moving | float/himax_typical/full | 99.6% | 3.3 deg avg (9.3 worst) | 2.20 m (2.17-2.27 over 4), target 1.94 | 0 | PASS |
| Person swaying side to side | person, moving | float/clean/chip | 97.9% | 3.2 deg avg (10.8 worst) | 1.74 m (1.69-1.87 over 4), target 1.94 | 0 | **FAIL** |

## What each scene means, in one line

- _ships-as_ - Person standing still: followed correctly. It pointed at the person within 3.0 deg avg (4.8 worst) and held station at 2.19 m (2.06-2.24 over 4), target 1.94.
- _ships-as_ - Person swaying side to side: followed correctly. It pointed at the person within 3.3 deg avg (9.9 worst) and held station at 2.44 m (2.35-2.44 over 4), target 1.94.
- _ships-as_ - Empty room: correctly ignored everything; it never moved (drift 0.00 m).
- _ships-as_ - Person walks behind a partition: it lost the track for up to 16.4 s, and once the person was properly back in view it took 2.75 s to start following again; it correctly waited for 3 fresh frames before steering again. FAILED.
- _ships-as_ - Furniture and boxes, nobody home: correctly ignored everything; it never moved (drift 0.00 m).
- _ships-as_ - A dog and a cat, no people: it locked onto an animal/toy 3 time(s), tracked it for 9% of the flight and moved 0.58 m. Measured, not graded - this is the number that decides champion vs confuser.
- _proven_ - Person standing still: followed correctly. It pointed at the person within 1.3 deg avg (1.8 worst) and held station at 1.63 m (1.55-1.93 over 4), target 1.94.
- _proven_ - Person swaying side to side: FAILED on M10_uncertain_fraction_present. It pointed at the person within 3.0 deg avg (9.2 worst) and held station at 1.87 m (1.72-1.99 over 4), target 1.94.
- _proven_ - Empty room: correctly ignored everything; it never moved (drift 0.00 m).
- _proven_ - Person walks behind a partition: it lost the track for up to 5.4 s, and once the person was properly back in view it took 2.18 s to start following again; it correctly waited for 3 fresh frames before steering again. FAILED.
- _proven_ - Furniture and boxes, nobody home: correctly ignored everything; it never moved (drift 0.00 m).
- _chip/clean/full_ - Person swaying side to side: FAILED on M1_tracking_fraction, M10_uncertain_fraction_present. It pointed at the person within 3.3 deg avg (8.3 worst) and held station at 2.00 m (1.88-2.11 over 4), target 1.94.
- _float/himax_typical/full_ - Person swaying side to side: followed correctly. It pointed at the person within 3.3 deg avg (9.3 worst) and held station at 2.20 m (2.17-2.27 over 4), target 1.94.
- _float/clean/chip_ - Person swaying side to side: FAILED on M10_uncertain_fraction_present. It pointed at the person within 3.2 deg avg (10.8 worst) and held station at 1.74 m (1.69-1.87 over 4), target 1.94.

## Measured-only checks

These have no pass mark yet, on purpose - we are collecting the first numbers.

- Dog / teddy false-follow rate (decides champion vs confuser model)
- Steering smoothness (pass mark set from this sweep - spec section 4, M11)
- Every threshold on the realistic camera (no verified baseline yet - spec section 5)

## Provisional numbers observed in this sweep (for calibrating v2.1)

| metric | scene class | median | min | max | provisional threshold |
|---|---|---|---|---|---|
| M1_tracking_fraction | A (ships-as) | 0.9905 | 0.829 | 0.991 | >= 0.9 |
| M2_heading_err_mean_deg | A (ships-as) | 2.985 | 2.71 | 3.35 | <= 8.0 |
| M10_uncertain_fraction_present | A (ships-as) | 0.2278 | 0.1509 | 0.3519 | <= 0.15 |
| M11_yaw_reversals_per_min | A (ships-as) | 0.0 | 0.0 | 0.0 | <= 8.0 |
| M11_yaw_saturated_fraction | A (ships-as) | 0.0 | 0.0 | 0.0 | <= 0.25 |
| M1_tracking_fraction | B (ships-as) | 0.992 | 0.975 | 0.992 | >= 0.9 |
| M2_heading_err_mean_deg | B (ships-as) | 3.32 | 3.13 | 3.39 | <= 10.0 |
| M10_uncertain_fraction_present | B (ships-as) | 0.1079 | 0.0816 | 0.1538 | <= 0.15 |
| M11_yaw_reversals_per_min | B (ships-as) | 4.74 | 4.72 | 4.76 | <= 24.0 |
| M11_yaw_saturated_fraction | B (ships-as) | 0.0 | 0.0 | 0.0 | <= 0.25 |
| M9_gt_halfvisible_to_relatch_s | D (ships-as) | 3.0605 | 0.62 | 9.076 | <= 1.5 |
| M11_yaw_reversals_per_min | A (proven) | 0.0 | 0.0 | 0.0 | <= 8.0 |
| M11_yaw_saturated_fraction | A (proven) | 0.0 | 0.0 | 0.0 | <= 0.25 |
| M11_yaw_reversals_per_min | B (proven) | 4.785 | 4.73 | 4.91 | <= 24.0 |
| M11_yaw_saturated_fraction | B (proven) | 0.0 | 0.0 | 0.0 | <= 0.25 |
| M9_gt_halfvisible_to_relatch_s | D (proven) | 2.182 | 1.796 | 5.428 | <= 1.0 |
| M11_yaw_reversals_per_min | B (chip/clean/full) | 4.85 | 4.73 | 4.93 | <= 24.0 |
| M11_yaw_saturated_fraction | B (chip/clean/full) | 0.0 | 0.0 | 0.0 | <= 0.25 |
| M1_tracking_fraction | B (float/himax_typical/full) | 0.996 | 0.996 | 0.996 | >= 0.9 |
| M2_heading_err_mean_deg | B (float/himax_typical/full) | 3.3 | 3.17 | 3.32 | <= 8.0 |
| M10_uncertain_fraction_present | B (float/himax_typical/full) | 0.0268 | 0.0211 | 0.029 | <= 0.15 |
| M11_yaw_reversals_per_min | B (float/himax_typical/full) | 4.865 | 4.76 | 4.99 | <= 24.0 |
| M11_yaw_saturated_fraction | B (float/himax_typical/full) | 0.0 | 0.0 | 0.0 | <= 0.25 |
| M11_yaw_reversals_per_min | B (float/clean/chip) | 4.82 | 4.79 | 4.93 | <= 24.0 |
| M11_yaw_saturated_fraction | B (float/clean/chip) | 0.0 | 0.0 | 0.0 | <= 0.25 |

---

Distances: the drone aims to stop where the person fills the middle size bucket. For a 1.7 m person that is 1.94 m, and anything from 1.62 to 2.43 m is the same bucket, so it is all equally correct. Pointing error is the angle between where the drone is facing and where the person actually is, from the simulator's own ground truth.
