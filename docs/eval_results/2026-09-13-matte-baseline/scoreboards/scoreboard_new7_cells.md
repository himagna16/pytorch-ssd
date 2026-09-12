# Simulator scoreboard - matte_new7 suite - 12 Sep 2026

**Overall: FAIL.** 2 of 7 checks FAILED (5 passed, 0 measured-only, 0 unusable).
Flights: 28 attempted, 28 valid, 0 invalid, 28 scored (7 cells). Total time: 0 min.

Two setups appear in the table. **ships-as** is what the real drone will be: the chip's own integer network, the realistic camera model, and the chip's 6.5 Hz speed. **proven** is the laptop model on a clean camera at full speed - the setup every September baseline was measured in, so it says whether a problem is new or just the cost of realism.

## What failed

**A dog and a cat, no people - ships-as**  
A dog and a cat, no people: it locked onto an animal/toy 5.5 time(s), tracked it for 14% of the flight and moved 0.69 m. Measured, not graded - this is the number that decides champion vs confuser.  
- `M6_max_horizontal_drift_m` = 0.927, needs < 0.5 (a distractor may capture the track, but it must not fly across the room)

**Person walks behind a partition - proven**  
Person walks behind a partition: it lost the track for up to 4.3 s, and once the person was properly back in view it took 3.24 s to start following again; it correctly waited for 3 fresh frames before steering again. FAILED.  
- `M9_gt_visible_to_relatch_s` = 3.2405, needs <= 1.0 (the spec's own M9 reacquire gate (1.0 s at full rate, 1.5 s at chip speed) applied to the quantity section 4 actually describes: time from the target being continuously visible in ground truth until the track re-latches. Not a new threshold, an existing one finally pointed at the right measurement)

## All checks

| Scene | What it tests | Setup | Tracked | Pointing error | Distance held | False follows | Verdict |
|---|---|---|---|---|---|---|---|
| Empty room | nobody present | ships-as | 0.0% | n/a | n/a | 0 | PASS |
| Person walks behind a partition | person hidden then seen again | ships-as | 64.0% | 4.7 deg avg (28.6 worst) | n/a | 0 | PASS |
| Furniture and boxes, nobody home | inanimate distractor | ships-as | 0.0% | n/a | n/a | 0 | PASS |
| A dog and a cat, no people | animate distractor | ships-as | 13.7% | n/a | n/a | 5.5 | **FAIL** |
| Empty room | nobody present | proven | 0.0% | n/a | n/a | 0 | PASS |
| Person walks behind a partition | person hidden then seen again | proven | 87.0% | 3.3 deg avg (10.2 worst) | n/a | 0 | **FAIL** |
| Furniture and boxes, nobody home | inanimate distractor | proven | 0.0% | n/a | n/a | 0 | PASS |

## What each scene means, in one line

- _ships-as_ - Empty room: correctly ignored everything; it never moved (drift 0.00 m).
- _ships-as_ - Person walks behind a partition: it lost the track for up to 12.3 s, and once the person was properly back in view it took 1.33 s to start following again; it correctly waited for 3 fresh frames before steering again.
- _ships-as_ - Furniture and boxes, nobody home: correctly ignored everything; it never moved (drift 0.00 m).
- _ships-as_ - A dog and a cat, no people: it locked onto an animal/toy 5.5 time(s), tracked it for 14% of the flight and moved 0.69 m. Measured, not graded - this is the number that decides champion vs confuser.
- _proven_ - Empty room: correctly ignored everything; it never moved (drift 0.00 m).
- _proven_ - Person walks behind a partition: it lost the track for up to 4.3 s, and once the person was properly back in view it took 3.24 s to start following again; it correctly waited for 3 fresh frames before steering again. FAILED.
- _proven_ - Furniture and boxes, nobody home: correctly ignored everything; it never moved (drift 0.00 m).

## Measured-only checks

These have no pass mark yet, on purpose - we are collecting the first numbers.

- Dog / teddy false-follow rate (decides champion vs confuser model)
- Steering smoothness (pass mark set from this sweep - spec section 4, M11)
- Every threshold on the realistic camera (no verified baseline yet - spec section 5)

## Provisional numbers observed in this sweep (for calibrating v2.1)

| metric | scene class | median | min | max | provisional threshold |
|---|---|---|---|---|---|
| M9_gt_halfvisible_to_relatch_s | D (ships-as) | 2.108 | 1.871 | 2.35 | <= 1.5 |
| M9_gt_halfvisible_to_relatch_s | D (proven) | 3.2405 | 2.641 | 4.313 | <= 1.0 |

---

Distances: the drone aims to stop where the person fills the middle size bucket. For a 1.7 m person that is 1.94 m, and anything from 1.62 to 2.43 m is the same bucket, so it is all equally correct. Pointing error is the angle between where the drone is facing and where the person actually is, from the simulator's own ground truth.
