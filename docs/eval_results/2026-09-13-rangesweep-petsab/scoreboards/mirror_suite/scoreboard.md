# Simulator scoreboard - petsab_mirror suite - 12 Sep 2026

**Overall: FAIL.** 1 of 1 checks FAILED (0 passed, 0 measured-only, 0 unusable).
Flights: 4 attempted, 4 valid, 0 invalid, 4 scored (1 cells). Total time: 0 min.

Two setups appear in the table. **ships-as** is what the real drone will be: the chip's own integer network, the realistic camera model, and the chip's 6.5 Hz speed. **proven** is the laptop model on a clean camera at full speed - the setup every September baseline was measured in, so it says whether a problem is new or just the cost of realism.

## What failed

**A dog and a cat, no people - ships-as**  
A dog and a cat, no people: it locked onto an animal/toy 1 time(s), tracked it for 66% of the flight and moved 2.70 m. Measured, not graded - this is the number that decides champion vs confuser.  
- `M6_max_horizontal_drift_m` = 2.925, needs < 0.5 (a distractor may capture the track, but it must not fly across the room)

## All checks

| Scene | What it tests | Setup | Tracked | Pointing error | Distance held | False follows | Verdict |
|---|---|---|---|---|---|---|---|
| A dog and a cat, no people | animate distractor | ships-as | 66.1% | n/a | n/a | 1 | **FAIL** |

## What each scene means, in one line

- _ships-as_ - A dog and a cat, no people: it locked onto an animal/toy 1 time(s), tracked it for 66% of the flight and moved 2.70 m. Measured, not graded - this is the number that decides champion vs confuser.

## Measured-only checks

These have no pass mark yet, on purpose - we are collecting the first numbers.

- Dog / teddy false-follow rate (decides champion vs confuser model)
- Steering smoothness (pass mark set from this sweep - spec section 4, M11)
- Every threshold on the realistic camera (no verified baseline yet - spec section 5)

## Provisional numbers observed in this sweep (for calibrating v2.1)

| metric | scene class | median | min | max | provisional threshold |
|---|---|---|---|---|---|

---

Distances: the drone aims to stop where the person fills the middle size bucket. For a 1.7 m person that is 1.94 m, and anything from 1.62 to 2.43 m is the same bucket, so it is all equally correct. Pointing error is the angle between where the drone is facing and where the person actually is, from the simulator's own ground truth.
