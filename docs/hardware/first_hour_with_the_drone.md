# The first hour with a real drone

Written 2026-09-16 early morning, for a drone arriving around 1 pm the same day.

`lab_session_runbook.md` is written for a shared session with Grace and MinHyuk
in MinHyuk's lab, on a clock. If that is what happens, use it and ignore this.
**This document is for the other case: you, a drone, and no time box.** The order
below is chosen so that nothing you do in the first hour can cost you the
session, and so that the one measurement that matters happens before anything
risky.

Props off the whole time. Nothing flies.

## Step 0, added 2026-09-22: run the preflight check first

> Added 2026-09-22, when the micro-USB cable arrived. Everything below this
> section is unchanged. This step answers facts 2 and 3 of "Before you power
> anything" (the radio address and the STM32 firmware version) without guessing.

Battery plugged in so the drone is on, micro-USB cable from the drone to the
Mac, cfclient closed. Then, from `~/Downloads/drone/pytorch_ssd`:

```bash
../cfloaderenv/bin/python tools/hardware/preflight.py
```

There is no `python` on this Mac's PATH, so always type the venv path as above.
The USB cable is enough: it is a full link to the drone, no Crazyradio needed.
The tool tries USB first and the Crazyradio second. To name the link yourself,
add `--uri usb://0` or `--uri radio://0/80/2M/E7E7E7E7E7`.

**It is read-only.** It never arms the motors, sends a setpoint, writes a
parameter or changes the radio address. It reads, listens for five seconds (keep
the drone still), prints a checklist and saves a JSON file to
`~/Downloads/drone/logs/preflight/<date-time>.json`. The last line says where.

**Reading the checklist.** Each line starts with a tag:

| tag | meaning |
|---|---|
| `OK` | fine |
| `WARN` | read the line, it says what to do |
| `FAIL` | fix it before a session. A flat battery is the usual one |
| `INFO` | for the record, nothing to do |
| `SKIP` | not applicable, e.g. the Lighthouse lines when there is no Lighthouse deck |

What to look at, in order:

1. **Link**: which way it connected. If it says `No Crazyflie found`, the line
   under it lists the three usual causes: drone off, a charge-only cable, or
   cfclient still connected.
2. **Firmware**: the version and git revision. Write it down. It is fact 3 above.
3. **Decks**: `yes` or `no` for each deck, the AI-deck and Lighthouse deck always
   listed. A `!` line means a deck is physically on but its driver did not start:
   reseat it and power-cycle.
4. **Battery**: under 3.7 V says "charge before a session". Remember 350 mAh is
   about 5-7 minutes with the AI-deck streaming. While USB is charging, the
   voltage reads high.
5. **Radio**: the channel and address stored on the drone, as a ready-made
   `radio://` URI. That is fact 2 above. **Run it on both drones.** Two drones on
   one Crazyradio need different addresses, and from the second run on the tool
   warns if it has seen another drone with the same one. It never changes the
   address itself; that is done in cfclient.
6. **Lighthouse** (only with a Lighthouse deck): which base station type the
   drone expects, then one line per base station: seen or not, calibrated,
   geometry OK or MISSING, in use. "Geometry missing" means run the geometry
   step in cfclient's Lighthouse tab.
7. **AI-deck**: only confirms the deck's driver started. Camera frames never come
   over this link; they come over the deck's own WiFi at `192.168.4.1:5000`.
8. **UART1 clash** (only with both decks on): evidence for an **unverified**
   theory that our GAP8 apps' serial output (`io=uart`) collides with the
   Lighthouse deck on the Crazyflie's UART1. The tool prints how to test it: one
   run with the GAP8 app running, one with the AI-deck off, then
   `--compare <first run's json>` puts the two side by side.

Exit code 0 means nothing failed, 1 means a `FAIL` line, 2 means it could not
connect.

Tested on 2026-09-22 against the CrazySim simulator (`--uri udp://127.0.0.1:19850`)
and 41 fake-drone tests (`../cfloaderenv/bin/python tools/hardware/test_preflight.py`).
**Not yet run on a real drone.** The simulator's firmware pretends to carry a Flow
deck, a Multi-ranger and LED decks, so do not expect its deck list to match yours.

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
| **3.5 m, bearing -25 and +25** | **now equally important, see below** |
| 2.5 m, bearing 0 | the middle of the useful band |
| 2.5 m, bearing -25 and +25 | the second bearing point, if time allows |
| 1.5 m, bearing 0 | close range; note the whole body barely fits below about 1.3 m |

> **The off-centre marks were promoted on 2026-09-17 and are now the most valuable
> thing in the session.** Three simulator suites tried to measure what bearing
> costs and none of them could, because the simulated person is an opaque
> rectangular card that throws a rectangular shadow on the wall behind it, and
> that shadow only appears when the person is off centre. MuJoCo will not let us
> switch it off for the card alone, and switching it off for the whole room moves
> the scene brightness, which the sensor's auto-exposure then pushes back into the
> subject. See `docs/eval_results/2026-09-17-panel-noshadow/`.
>
> A real person standing to one side does not bring a rectangular shadow with
> them. **These clips are the only clean measurement of the bearing cost that
> anyone will have.** Shoot them carefully, and shoot them before you get tired.

Thirty seconds a clip is plenty. Label every clip with its distance and bearing,
which `cpx_grab.py` takes as flags, and note the lighting in the folder name.

Then score the folder. **You must run BOTH commands.** The first gives the mirror
check, the bins and the labels. The second gives the confidence the drone actually
sees.

```bash
# 1. the usual scorer: mirror check, bin accuracy, labels, track%
~/Downloads/drone/trainenv/bin/python \
  ~/Downloads/drone/pytorch_ssd/tools/real_frames/score_real_frames.py \
  ~/drone_frames/2026-09-17

# 2. the chip arm, which is the network that flies. Seconds to run.
~/Downloads/drone/doryenv/bin/python \
  ~/Downloads/drone/pytorch_ssd/docs/eval_results/2026-09-17-chip-arm-rescore/scripts/rescore_chip.py \
  ~/drone_frames/2026-09-17
```

> # ⚠ THE FIRST COMMAND ALONE WILL MISLEAD YOU
>
> `score_real_frames.py` has no backend switch and is hardwired to the **float**
> PyTorch model. Every flight this project has run, and the GAP8 itself, uses the
> **chip** model: the int8 export plus the firmware's integer preprocessing.
>
> On 13,003 rendered frames the two disagree by **-0.124 in mean confidence and
> -0.239 in the fraction of frames above the 0.75 bar**, with 122 of 325 cells
> moving by 0.25 or more and some going from 1.000 to 0.000. It is not a constant
> offset, so it cannot be subtracted off afterwards.
>
> Read the chip numbers when you want to know what the drone will do. Read the
> float numbers only for the mirror check and the bin and bearing diagnostics,
> which do not depend on the arm.
>
> Compare against the chip column of
> `docs/eval_results/2026-09-17-chip-arm-rescore/tables/reference_table_chip.tsv`,
> **not** the float table from 2026-09-16. Found at 02:20 the same morning; see
> that directory for the full story.

**A second caution, superseded by the one above but still true.** The rendered comparison in
`docs/eval_results/2026-09-16-protocol-geometry/tables/reference_table.tsv` is the
right shape but is approximate at the margin. For at least one subject it reads
0.450 where the simulator at the same nominal geometry gives 0.007, which is being
investigated. Treat a real number landing in the middle of the table's range as
uninformative, and read the extremes: near 1.000 or near 0.000 mean something,
0.4 does not yet.

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

## Two things a dry run on 2026-09-16 turned up

The whole chain was run against the mock streamer the night before, capturing
three labelled clips and scoring the folder. It works. Two traps showed up that
are worth knowing at the bench.

**The mirror check needs clips from BOTH sides, and silently reports NO DATA if
it does not have them.** Every clip in the dry run was labelled bearing 0, and
the check printed `no detected person frames with |bearing| >= 8 deg -> NO DATA`.
If you capture only head-on, you will not find out that the model's left and
right are wrong. Shoot the two off-centre clips early, not last.

**A large `bearing err` means your floor marks and your labels disagree.** The
dry run labelled its clips b0 while the mock streamer was rendering a subject at
-25 degrees, and the scorer reported `bearing err -23.2`. That is the scorer
working: it compares what you wrote on the clip against what it sees. If a real
capture comes back with a bearing error of that size, do not reach for the model.
Check the tape measure and the labels first.

The dry run's other columns behaved as designed: `vis acc 100%`, `track 94%`,
and `size acc +-1 100%`, on 108 frames across three clips.

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

## What was verified the night before, and what was not

Run on 2026-09-16, the evening before the drone arrives:

| thing | result |
|---|---|
| champion flight image rebuilds | byte-identical to the 2026-09-13 image, sha256 `261e20d8...`, 340,896 B |
| camera streamer builds from our own source | yes, 61,472 B, two clean builds byte-identical, sha256 `de11368d...` |
| both images kept outside the build tree | `handoff_private/aideck_images/` with `SHA256SUMS.txt` |
| scorer against the real checkpoint | 39/39 checks pass, mirror PASS on upright and MIRRORED on the flipped copy, bin acc 96%, 0 false tracks, n=680 |
| capture chain, mock streamer to scored folder | 3 clips, 108 frames, scored clean |

**Not verified, and cannot be until there is a deck in the room:** flashing
anything to real hardware, the streamer image actually running on a deck, the
deck's revision, the real URI, and the STM32 and ESP32 firmware versions. Every
build step is reproducible. No flash step has ever touched hardware.
