# Plan for Fri 2026-10-02 (home all day) and the weekend

Written Thu Oct 1, 9 pm, after a four-day break for midterms. Nothing has changed in the
repo since Sep 27. This is a running order for the day, not a protocol. The protocols it
points to are the ones to follow.

## Tonight (Thu): charge the batteries

The batteries have sat flat since Sep 24. Charging goes through the drone's own micro-USB
port with the battery plugged into the drone, so one cable charges one battery at a time
(about 40 min each from flat, longer from very flat).

1. Look at each battery before charging it. If it is puffy or swollen, do not charge it.
   Set it aside.
2. Drone 09: battery in, cable into any USB-A wall charger (or the hub). The blue LED
   blinks slowly while charging and goes solid when full.
3. When drone 09 is full, move the cable to drone 05 and charge that one. If you only get
   to one tonight, charge drone 05's battery first thing tomorrow while you do step A.
   Drone 09 can run on the cable instead of a battery (see B).
4. A battery left full overnight is fine. A LiPo left fully flat for weeks is what does
   damage, so don't leave them flat after this.

**If you have a second micro-USB cable**, charge both at once. If not, it's still worth
buying one: one cable is the bottleneck for every session with two drones.

## A. Put the base station back and check the geometry (~30 min, morning)

**Why this matters.** The two base stations are what measure position. Each one sweeps
the room with laser planes, and the Lighthouse deck on each drone times those sweeps to
work out where it is, to within a few mm. The saved geometry
(`docs/hardware/lighthouse/dorm_lighthouse_2026-09-24.yaml`, also stored on both drones)
records where each station is and which way it points. Every position the drones report
is computed from that record. If a station sits even a few cm or a few degrees away from
where the record says, every position shifts with it, and nothing on screen tells you.
For the labelling plan that's the worst case: wrong labels that look clean.

1. Stand the moved station back on its taped feet. Also match the **height** of the light
   stand and the **aim** of the ball head. Floor tape fixes the position on the floor but
   not the height or the angle. Station 1 (channel 1) is at the window end (Oaj's corner).
   Station 2 (channel 2) is at the door end, on your side.
2. Plug both stations in at the wall and give them a minute to spin up and go steady.
3. Drone on the hub cable, then the preflight:
   `~/Downloads/drone/cfloaderenv/bin/python tools/hardware/preflight.py`
   Both stations should show as seen.
4. **Tape check, drone 09.** Same as Sep 24: marks A (origin), B (+x, 1 m toward the door),
   C (SIDE), D (origin, turned 90 deg left). Tolerance is 8 cm and 12 deg.
   `~/Downloads/drone/cfloaderenv/bin/python tools/lighthouse/tape_check.py`
   - **4/4 PASS** means the geometry is still good. Don't redo anything.
   - **FAIL** means you redo the geometry wizard in cfclient (about 10 min), then export
     it and import it on drone 05. Lesson from Sep 24: spread the XYZ-space samples across
     the whole floor. Bunching them at one end is what broke attempts 1 and 2.
5. **Tape check, drone 05.** This has been pending since Sep 24. Its result isn't
   optional, because drone 05 is the beacon that every label will come from.

## B. Finish the real-person grid in one sitting (~1 h)

There's still no complete 9-cell grid at a controlled exposure. Sep 24 gave partial grids
in two lighting conditions and one run that was all black frames.

- **Run drone 09 on the hub cable with the battery out**, so it can't die mid-grid (it died
  at clip 6 on Sep 24). Check the stream comes up that way first. If it doesn't, go back to
  a battery.
- `grid_capture.sh` won't record unless the image brightness is inside 30-60. If it
  refuses, power-cycle the drone (unplug, replug) and try again. Exposure is random at
  every power-up, and that's a known firmware issue, not your setup.
- Fixed lights for the whole grid: blinds closed, room lights on, nothing changed partway.
- Then the **door-sheet control.** Hang something light-coloured over the dark door and
  re-record only the CENTRE column. Sep 24 never locked onto you dead centre in front of the
  dark door, but did lock when you were off to the sides against the bright wardrobes. This
  one clip decides whether that was the background contrast or the position.

```
GRID_DRONE=09 GRID_LIGHT=room-lights zsh tools/real_frames/grid_capture.sh
```

The laptop loses internet while it's on the drone's WiFi, so Claude is cut off during the
run. Report the folder name afterwards.

## C. First Lighthouse-labelled recording (~1.5 h, afternoon)

**Needs the recorder tool being built tonight on branch `sai/lighthouse-session-recorder`.**
It records both drones' positions alongside the camera frames, which nothing did before.
Check it has been merged before you start. It has not been run on hardware yet.

1. **Beacon prep, drone 05:** props OFF, motors never armed. Mount it flat on top of a cap
   (velcro or tape). Its AI-deck probably broadcasts the same WiFi name as drone 09's, so
   the laptop could join the wrong camera. The recorder's README will say how to handle it.
   The simplest fix is to unplug drone 05's AI-deck from the stack.
2. **Decide one thing first:** where the label points on your body. The default proposal is
   "half your height below the top of your head", meaning your torso centre. It has been
   waiting for a team OK since Sep 22. Measure your height in socks plus the cap.
3. **Static taped-mark case first** (10 min, `tools/lighthouse/README.md`): stand on marks,
   check the computed x-bin and size match what you'd expect. Then turn drone 09 30 deg to
   its left on the stand and check you move to the RIGHT side of the label. If the labels
   come out mirrored, stop there.
4. Then two or three **short walking recordings**, 3-4 min each (the beacon battery is the
   limit). Each one starts and ends with the sync move: stand still for 2 s, one quick
   sidestep, stand still again. Walk slowly side to side and toward and away from the
   camera, staying in the frame.

The point of today is not a dataset. It's proving that the whole chain (positions to labels,
clock sync, the not-mirrored check) works on real hardware before collecting at scale.

## Weekend

- Label Friday's recordings and score the champion against them. This gives the first real
  accuracy numbers (x-bin and size against true position) instead of just "locked or not".
- If the chain holds, collect more: **other people** (one subject is not a rate; Oaj or a
  friend), other backgrounds, day and night lighting. At ~2 fps, 10 min is about 1,200
  frames.
- Decisions waiting on you (see the plan summary in chat): the chip check of the plain
  fine-tune, the camera-exposure firmware fix, and pinging Grace about
  `--preserve-qat-alphas`.
