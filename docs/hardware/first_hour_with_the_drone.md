# The first hour with a real drone

Written 2026-09-16 early morning, for a drone arriving around 1 pm the same day.

`lab_session_runbook.md` is written for a shared session with Grace and MinHyuk
in MinHyuk's lab, on a clock. If that is what happens, use it and ignore this.
**This document is for the other case: you, a drone, and no time box.** The order
below is chosen so that nothing you do in the first hour can cost you the
session, and so that the one measurement that matters happens before anything
risky.

Props off the whole time. Nothing flies.

## Before you power anything

Three facts decide whether an over-the-air flash is even possible, and none of
them are known yet. Find them out before you plan around flashing.

1. **AI-deck hardware revision.** Over-the-air GAP8 flashing needs the GAP8
   bootloader, pre-flashed only on **AI-deck 1.1 Rev D and newer**. An older deck
   must be flashed over JTAG first, which cannot be done from this Mac.
2. **The Crazyflie URI.** Do not guess it. Default is
   `radio://0/80/2M/E7E7E7E7E7`, but a lab fleet is usually re-addressed.
3. **STM32 and ESP32 firmware versions.** The flash path runs through both. Stale
   firmware makes `deck-bcAI:gap8-fw` unreachable.

If the deck turns out to be pre-Rev-D, the capture work below still works and the
flash work does not. That is fine. The capture is the valuable half.

## Step 1, and do not skip it: get the camera streaming

The streamer is what every measurement depends on. Confirm it is on the deck and
working before you touch anything else.

```bash
~/Downloads/drone/trainenv/bin/python \
  ~/Downloads/drone/pytorch_ssd/tools/crazysim_macos/cpx_grab.py --help
```

Read `fmt=` on every saved line. If the deck arrives with something other than
the streamer on it, §3c of `flash_runbook.md` now has our own built streamer
image and the command to flash it.

## Step 2: the mirror check, before anything else is believed

Two ten-second clips into the same folder, one from each side, then score that
folder. This is the check that decides whether the model's left and right agree
with reality. A mirrored model steers the drone the wrong way on every frame, and
every later measurement is worthless if this fails.

The exact commands are in `lab_session_runbook.md` §4.0, M3. The verdict must
read **PASS**. MIRRORED, FAIL or NO DATA means stop and report, not carry on.

## Step 3: the measurement this whole project is waiting for

Stand at floor marks and record yourself. Camera lens **0.8 m** above the floor,
level, on a tripod or a stack of books, pointing down a taped centre line.

| mark | why |
|---|---|
| **3.5 m, bearing 0** | the one that matters most, closest to the 3.64 m the simulator parks at |
| 2.5 m, bearing 0 | the middle of the useful band |
| 1.5 m, bearing 0 | close range; note the whole body barely fits below about 1.3 m |
| 3.5 m, bearing -25 and +25 | whether bearing costs anything inside the crop |

Thirty seconds a clip is plenty. Label every clip with its distance and bearing,
which `cpx_grab.py` takes as flags, and note the lighting in the folder name.

Then score the folder:

```bash
~/Downloads/drone/trainenv/bin/python \
  ~/Downloads/drone/pytorch_ssd/tools/real_frames/score_real_frames.py \
  ~/drone_frames/2026-09-16
```

**Read `track%` at the 3.5 m mark.** That is the same quantity as the simulator's
tracking fraction, computed by different code on real pixels. The prediction
recorded before any of this exists is in
`docs/hardware/2026-09-16-prediction-before-real-frames.md`: median above 0.80,
nobody at exactly 0.000. If the real number comes back near 0.000, the simulator's
pessimistic result transfers and the network is the blocking problem. If it comes
back near 0.99, our scene builder is what is wrong, not the network.

Either answer is worth the afternoon. One subject is not a sample of humanity, so
record how many people you got and what they were wearing, and do not let a single
clip of one person in one jacket become a project-wide claim.

## Step 4, only after the frames are backed up somewhere else: flash

Copy the frames off the capture laptop first. Then, if you want to flash:

Flash the **bench** image before the flight image. The bench image runs a fixed
picture through the network with no camera, so `mismatches=0` separates "the model
is wrong" from "the camera or the plumbing is wrong". `flash_runbook.md` §3a and
§5.

Flashing replaces the streamer. As of today that is reversible: our own streamer
image is built, reproducible across two clean builds, and kept at
`~/Downloads/drone/handoff_private/aideck_images/wifi-img-streamer.flash.img`.
The flash of it has never been tried on a real deck, so treat the recovery as very
likely rather than certain, and do not flash at all until the frames are off the
laptop.

## What not to do in the first hour

- Do not fly. Props stay off.
- Do not flash before capturing. The capture is the part that cannot be done
  anywhere else.
- Do not paste the flash command the build script prints. It begins with a bare
  `python`, which does not exist on this Mac. `flash_runbook.md` §0 explains it.
- Do not run `follow_person.py` or `flight_check.py` against real hardware.
