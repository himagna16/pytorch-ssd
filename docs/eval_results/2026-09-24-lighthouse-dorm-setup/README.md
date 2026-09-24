# Lighthouse setup in the dorm: session log, 2026-09-24

This log was written live, during the session, and is updated as it goes. Hardware:
drone 1 (Crazyflie 2.1, AI-deck + Lighthouse deck stacked) on a micro-USB cable through
the new USB-C hub, a Crazyradio 2.0, and two SteamVR Base Station 2.0 units on light
stands. The room layout sheet is `docs/hardware/dorm_lighthouse_tape.svg` (as built).

## 1. Plug-in check (read-only preflight, `usb://0`)

`preflight_drone1_run1.json` and `preflight_drone1_run2.json`, taken 10 s apart.

| item | result |
|---|---|
| USB | **Crazyradio 2.0 and Crazyflie both enumerate through the hub.** The Sep 17 "Cannot find a Crazyradio" question is closed: the laptop had no USB-A port |
| firmware | 2026.08, git 54f31e243a0b, unmodified, Crazyflie 2.1, protocol 12 |
| decks | AI-deck present, Lighthouse deck (bcLighthouse4) present |
| battery | 4.03 V, charging on the cable |
| radio | stored address **E7E7E7E709** (lab re-addressed, not factory) -> `radio://0/80/2M/E7E7E7E709` |
| Lighthouse | V2 system. BS1 seen and in use; BS2 not seen at that moment; noise 7.5 mm (run 2). The drone still carried **MinHyuk's lab geometry**, which is wrong for this room |
| UART1 theory | comSync 100% in run 2, no symptom. Run 1 read 1397 mm noise / 54% "working" while the drone was being handled right after plug-in. Not a test of the theory (no GAP8-off arm) |

## 2. Room and channels

- Open floor is now **5 x 10 one-foot tiles**. Station 2's tripod took the door-end row.
- Tape was laid **rotated 180 deg** from the plan: +x points toward the **door**. The
  SIDE mark is on the left when facing +x (checked by Sai), so this is still a valid
  right-handed frame (a rotation, not a mirror).
- Channels (cfclient "Set BS channel", one station at a time over micro-USB):
  **channel 1 = window end (Oaj's corner); channel 2 = door end (Sai's side)**. Station
  F469DDEB is channel 2 (it read 2 on first scan, was set to 1 by accident, then back to 2).

## 3. Geometry wizard, attempts 1-2: FLAWED, kept for the record

cfclient 2026.8 "Start Set Up". The three floor samples (origin, +x, SIDE) were taken
with the drone **flat on the bare vinyl-tile floor**.

| sample | attempt 1 | attempt 2 (more XYZ samples) |
|---|---|---|
| origin error | **77.8 mm** | **79.0 mm** |
| x-axis error | 0.8 mm | 4.2 mm |
| xy-plane (SIDE) error | **73.9 mm** | **79.2 mm** |
| xy-plane solved Y (tape says 0.61 m) | **0.78** | **0.77** |
| XYZ-space samples | 9 (+2 ambiguous), x 1.46-1.95 m | 27, all x 1.11-1.94 m |

Decisive test: a sample held over the **ORIGIN X at waist height** read
**x 1.29, y -0.25, z 0.92** (error 2.4 mm). It should read about (0, 0, 0.9). The frame
was displaced by more than a metre in x, while the in-air samples agreed with each other
to a few mm. **So the in-air data was fine and the floor samples were not.**

## 4. Attempt 3: floor samples raised on a book, CLEAN

All samples cleared. The three floor samples were retaken with the drone on the **same
book** each time, placed on each tape mark. Then 16 XYZ-space samples were taken,
starting directly above the origin and spread over both halves of the room.

| sample | x | y | z | error |
|---|---|---|---|---|
| origin | 0.00 | 0.00 | 0.00 | 1.2 mm |
| x-axis | 1.00 | 0.00 | 0.00 | 1.7 mm |
| xy-plane (SIDE) | 0.01 | **0.61** | 0.00 | 1.0 mm |
| first XYZ, held over the origin at waist height | **0.07** | **-0.03** | 0.98 | 0.3 mm |
| 16 XYZ-space samples, range | -0.98 .. 1.02 | -0.60 .. 0.55 | 0.98 .. 1.25 | **0.3-2.0 mm** |

- The SIDE mark reads 0.61 m, exactly 2 tiles.
- The sample over the origin reads the origin.
- The worst sample error fell from 79 mm to 2.0 mm.
- z = 0 now sits at the book's height, not the floor. That does not matter for labels,
  which use x, y and yaw.

## 5. What caused it: floor reflections? **WEAKENED at 11:12, see section 7**

*Update 11:12: the tape check on the bare floor passed at every mark (section 7), which
argues against reflection as the cause. The text below is the reasoning as it stood at
about 11:00. It is kept, not rewritten.*

Bitcraze's setup guide says to remove reflective surfaces from the Lighthouse volume. The
dorm floor is glossy vinyl tile. With the deck a few cm above it, the base stations'
sweeps can bounce off the floor into the sensors. That fits every observation:

- Only the samples **on the floor** were bad. In-air samples fit within mm, in every attempt.
- Lifting the drone a few inches fixed all three floor samples at once.

**Confound, stated plainly:** attempt 3 changed two things at once. It raised the drone
off the floor, **and** it was a clean restart with XYZ samples spread over the whole room
from the start. Attempts 1-2 had their XYZ samples bunched at the door end. The
reflection explanation fits best, because attempt 2 already had 27 good in-air samples
and the floor samples were still 79 mm off. But this was not a controlled test. The
1-minute test that settles it: in the same session, take one extra sample with the drone
on the bare floor and one on the book at the same mark, and compare their errors.

**The parallel with the simulator.** On Sep 12 the simulator's floor had a 20% mirror
(`reflectance="0.2"`), and the camera read person-plus-reflection as one object. That
cost the distance estimates 1.5-2x. Here a real reflective floor corrupted a different
sensor. The lesson holds on both: **reflective floors are a first-class hazard for this
project**, for the camera and for Lighthouse alike.

## 6. Procedure going forward (also in `docs/hardware/dorm_setup.md`)

- *(11:12: the book is now a precaution, not a proven fix; see section 7.)* Taking the floor
  samples on the same book is harmless, so keep doing it until the book run settles it.
- **Most important:** start the in-air samples right over the origin and spread them
  over the whole room. Bunching them at one end is the leading suspect for attempts 1-2.
- Take the first XYZ sample over the origin and check it reads about (0, 0).
- Spread the in-air samples over both halves of the room. Target every row under 15 mm.
- **The geometry is only valid while the stations do not move.** A bumped stand means
  redoing the wizard.

## Status

- [x] preflight on drone 1
- [x] base station channels
- [x] geometry wizard, clean (attempt 3)
- [ ] export the geometry from cfclient (Lighthouse tab -> Export configuration), so
      drone 2 can import it with no wizard
- [x] `tools/lighthouse/tape_check.py`, run 1 (bare floor): **4 of 4 PASS, yaw sign confirmed** (section 7)
- [ ] tape check run 2 (on the book), to complete the floor-vs-book comparison
- [ ] preflight on drone 2

## 7. Tape check, run 1: drone on the BARE FLOOR, 11:12 (`tape_check_run1_bare_floor.json`)

Read-only `tools/lighthouse/tape_check.py` against the attempt-3 geometry.

| step | placement | measured x, y (m) | yaw (deg) | verdict |
|---|---|---|---|---|
| A | ORIGIN, camera toward +x | +0.01, +0.01 | -4.6 | PASS |
| B | +x mark | +1.00, -0.00 | -2.3 | PASS |
| C | SIDE mark | +0.01, +0.61 | +1.6 | PASS |
| D | ORIGIN, turned 90 deg LEFT | +0.01, +0.01 | **+89.1** | PASS |

z read -0.02 m at every mark: the floor sits about 2 cm below the book-height plane.

**Two results.**

1. **Yaw sign CONFIRMED on real hardware.** A left turn reads +89.1 deg, 0.9 deg from
   the expected +90. Together with the Sep 22 simulator validation (99-100% side
   agreement, PR #6), this closes the yaw-sign chain first flagged on Sep 10. The
   Lighthouse labels will not come out mirrored. The room frame matches the tape to
   about 1 cm in x and y.
2. **The floor-reflection hypothesis is WEAKENED.** With the drone flat on the bare
   tile, the live position at the origin is (0.01, 0.01), not metres off. If floor
   reflections corrupted the sweep angles near the floor, this run should have failed.
   The better-supported explanation for attempts 1-2 is the geometry solve itself. Every
   XYZ sample sat at the door end (x 1.1-1.95 in the bad frame), and the solver picks
   the station positions by clustering mirror-image candidate solutions across samples.
   Bunched samples let it settle on a wrong cluster, and the floor samples then showed
   up as 79 mm misfits. Attempt 3 was a clean restart with samples spread from the
   origin outward. This is still not isolated. The book run (run 2) completes the
   comparison. A wizard attempt on the bare floor with well-spread samples would settle
   it outright.

The Sep 12 simulator-mirror parallel drawn in section 5 is therefore **withdrawn** for
this case, until the book-vs-floor comparison says otherwise.
