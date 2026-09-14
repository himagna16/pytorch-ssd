# Simulator scoreboard - core suite - 14 Sep 2026

**Overall: FAIL.** 1 of 2 checks FAILED (1 passed, 0 measured-only, 0 unusable).
Flights: 27 attempted, 27 valid, 0 invalid, 9 scored (2 cells). Total time: 0 min.

Valid flights flown but not scored (superseded within their repeat): `x0.55__B.moving__ships__r1a1`, `x0.55__B.moving__ships__r2a1`, `x0.65__B.moving__ships__r1a1`, `x0.65__B.moving__ships__r2a1`, `x0.55__F.pets__ships__r1a1`, `x0.55__F.pets__ships__r2a1`, `x0.55__F.pets__ships__r3a1`, `x0.55__F.pets__ships__r4a1`, `x0.55__F.pets__ships__r5a1`, `x0.55__F.pets__ships__r6a1`, `x0.55__F.pets__ships__r7a1`, `x0.65__F.pets__ships__r1a1`, `x0.65__F.pets__ships__r2a1`, `x0.65__F.pets__ships__r3a1`, `x0.65__F.pets__ships__r4a1`, `x0.65__F.pets__ships__r5a1`, `x0.65__F.pets__ships__r6a1`, `x0.65__F.pets__ships__r7a1`.

Two setups appear in the table. **ships-as** is what the real drone will be: the chip's own integer network, the realistic camera model, and the chip's 6.5 Hz speed. **proven** is the laptop model on a clean camera at full speed - the setup every September baseline was measured in, so it says whether a problem is new or just the cost of realism.

## What failed

**A dog and a cat, no people - ships-as**  
A dog and a cat, no people: it locked onto an animal/toy 3 time(s), tracked it for 8% of the flight and moved 0.56 m. Measured, not graded - this is the number that decides champion vs confuser.  
- `M6_max_horizontal_drift_m` = 0.998, needs < 0.5 (a distractor may capture the track, but it must not fly across the room)

## All checks

| Scene | What it tests | Setup | Tracked | Pointing error | Distance held | False follows | Verdict |
|---|---|---|---|---|---|---|---|
| Person swaying side to side | person, moving | ships-as | 99.2% | 3.4 deg avg (9.1 worst) | 2.37 m (2.33-2.40 over 2), target 1.94 | 0 | PASS |
| A dog and a cat, no people | animate distractor | ships-as | 7.5% | n/a | n/a | 3 | **FAIL** |

## What each scene means, in one line

- _ships-as_ - Person swaying side to side: followed correctly. It pointed at the person within 3.4 deg avg (9.1 worst) and held station at 2.37 m (2.33-2.40 over 2), target 1.94.
- _ships-as_ - A dog and a cat, no people: it locked onto an animal/toy 3 time(s), tracked it for 8% of the flight and moved 0.56 m. Measured, not graded - this is the number that decides champion vs confuser.

## Measured-only checks

These have no pass mark yet, on purpose - we are collecting the first numbers.

- Dog / teddy false-follow rate (decides champion vs confuser model)
- Steering smoothness (pass mark set from this sweep - spec section 4, M11)
- Every threshold on the realistic camera (no verified baseline yet - spec section 5)

## Provisional numbers observed in this sweep (for calibrating v2.1)

| metric | scene class | median | min | max | provisional threshold |
|---|---|---|---|---|---|
| M1_tracking_fraction | B (ships-as) | 0.9915 | 0.991 | 0.992 | >= 0.9 |
| M2_heading_err_mean_deg | B (ships-as) | 3.385 | 3.35 | 3.42 | <= 10.0 |
| M10_uncertain_fraction_present | B (ships-as) | 0.1008 | 0.0921 | 0.1096 | <= 0.15 |
| M11_yaw_reversals_per_min | B (ships-as) | 3.29 | 3.21 | 3.37 | <= 24.0 |
| M11_yaw_saturated_fraction | B (ships-as) | 0.0 | 0.0 | 0.0 | <= 0.25 |

---

Distances: the drone aims to stop where the person fills the middle size bucket. For a 1.7 m person that is 1.94 m, and anything from 1.62 to 2.43 m is the same bucket, so it is all equally correct. Pointing error is the angle between where the drone is facing and where the person actually is, from the simulator's own ground truth.
