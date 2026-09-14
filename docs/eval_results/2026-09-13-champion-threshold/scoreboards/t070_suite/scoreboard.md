# Simulator scoreboard - thr_t070 suite - 14 Sep 2026

**Overall: FAIL.** 2 of 6 checks FAILED (4 passed, 0 measured-only, 0 unusable).
Flights: 24 attempted, 24 valid, 0 invalid, 24 scored (6 cells). Total time: 0 min.

Two setups appear in the table. **ships-as** is what the real drone will be: the chip's own integer network, the realistic camera model, and the chip's 6.5 Hz speed. **proven** is the laptop model on a clean camera at full speed - the setup every September baseline was measured in, so it says whether a problem is new or just the cost of realism.

## What failed

**Person walks behind a partition - ships-as**  
Person walks behind a partition: it lost the track for up to 16.7 s, and once the person was properly back in view it took 2.43 s to start following again; it correctly waited for 3 fresh frames before steering again. FAILED.  
- `M9_gt_visible_to_relatch_s` = 2.4275, needs <= 1.5 (the spec's own M9 reacquire gate (1.0 s at full rate, 1.5 s at chip speed) applied to the quantity section 4 actually describes: time from the target being continuously visible in ground truth until the track re-latches. Not a new threshold, an existing one finally pointed at the right measurement)

**A dog and a cat, no people - ships-as**  
A dog and a cat, no people: it locked onto an animal/toy 4.5 time(s), tracked it for 17% of the flight and moved 0.86 m. Measured, not graded - this is the number that decides champion vs confuser.  
- `M6_max_horizontal_drift_m` = 1.369, needs < 0.5 (a distractor may capture the track, but it must not fly across the room)

## All checks

| Scene | What it tests | Setup | Tracked | Pointing error | Distance held | False follows | Verdict |
|---|---|---|---|---|---|---|---|
| Person standing still | person, standing still | ships-as | 97.0% | 3.6 deg avg (6.3 worst) | 2.16 m (1.94-2.37 over 4), target 1.94 | 0 | PASS |
| Person swaying side to side | person, moving | ships-as | 99.2% | 3.1 deg avg (9.9 worst) | 2.43 m (2.36-2.45 over 4), target 1.94 | 0 | PASS |
| Empty room | nobody present | ships-as | 0.0% | n/a | n/a | 0 | PASS |
| Person walks behind a partition | person hidden then seen again | ships-as | 46.2% | 7.9 deg avg (51.1 worst) | n/a | 0 | **FAIL** |
| Furniture and boxes, nobody home | inanimate distractor | ships-as | 0.0% | n/a | n/a | 0 | PASS |
| A dog and a cat, no people | animate distractor | ships-as | 17.1% | n/a | n/a | 4.5 | **FAIL** |

## What each scene means, in one line

- _ships-as_ - Person standing still: followed correctly. It pointed at the person within 3.6 deg avg (6.3 worst) and held station at 2.16 m (1.94-2.37 over 4), target 1.94.
- _ships-as_ - Person swaying side to side: followed correctly. It pointed at the person within 3.1 deg avg (9.9 worst) and held station at 2.43 m (2.36-2.45 over 4), target 1.94.
- _ships-as_ - Empty room: correctly ignored everything; it never moved (drift 0.00 m).
- _ships-as_ - Person walks behind a partition: it lost the track for up to 16.7 s, and once the person was properly back in view it took 2.43 s to start following again; it correctly waited for 3 fresh frames before steering again. FAILED.
- _ships-as_ - Furniture and boxes, nobody home: correctly ignored everything; it never moved (drift 0.00 m).
- _ships-as_ - A dog and a cat, no people: it locked onto an animal/toy 4.5 time(s), tracked it for 17% of the flight and moved 0.86 m. Measured, not graded - this is the number that decides champion vs confuser.

## Measured-only checks

These have no pass mark yet, on purpose - we are collecting the first numbers.

- Dog / teddy false-follow rate (decides champion vs confuser model)
- Steering smoothness (pass mark set from this sweep - spec section 4, M11)
- Every threshold on the realistic camera (no verified baseline yet - spec section 5)

## Provisional numbers observed in this sweep (for calibrating v2.1)

| metric | scene class | median | min | max | provisional threshold |
|---|---|---|---|---|---|
| M1_tracking_fraction | A (ships-as) | 0.97 | 0.919 | 0.991 | >= 0.9 |
| M2_heading_err_mean_deg | A (ships-as) | 3.645 | 2.77 | 4.86 | <= 8.0 |
| M10_uncertain_fraction_present | A (ships-as) | 0.0767 | 0.0612 | 0.2632 | <= 0.15 |
| M11_yaw_reversals_per_min | A (ships-as) | 0.0 | 0.0 | 0.0 | <= 8.0 |
| M11_yaw_saturated_fraction | A (ships-as) | 0.0 | 0.0 | 0.0 | <= 0.25 |
| M1_tracking_fraction | B (ships-as) | 0.992 | 0.991 | 0.992 | >= 0.9 |
| M2_heading_err_mean_deg | B (ships-as) | 3.14 | 2.93 | 3.24 | <= 10.0 |
| M10_uncertain_fraction_present | B (ships-as) | 0.0681 | 0.0484 | 0.0931 | <= 0.15 |
| M11_yaw_reversals_per_min | B (ships-as) | 4.69 | 3.33 | 4.72 | <= 24.0 |
| M11_yaw_saturated_fraction | B (ships-as) | 0.0 | 0.0 | 0.0 | <= 0.25 |
| M9_gt_halfvisible_to_relatch_s | D (ships-as) | 2.745 | 1.417 | 9.563 | <= 1.5 |

---

Distances: the drone aims to stop where the person fills the middle size bucket. For a 1.7 m person that is 1.94 m, and anything from 1.62 to 2.43 m is the same bucket, so it is all equally correct. Pointing error is the angle between where the drone is facing and where the person actually is, from the simulator's own ground truth.
