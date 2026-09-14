# Simulator demo for Prof. Mok: talk track

Tuesday or Thursday after 5 pm. About 3 minutes. One command runs everything.
The flight takes about 75 seconds from Enter to scorecard.

## Before he arrives (10 minutes early)

- [ ] **Mac screen unlocked.** Set it not to sleep: System Settings, Lock Screen,
      "Turn display off" set to Never for today. The 3D window crashes if the screen locks.
- [ ] **Docker Desktop open**, whale icon in the menu bar, "Engine running".
- [ ] **Terminal open** in the simulator folder:
      ```bash
      cd ~/Downloads/drone/pytorch_ssd/tools/crazysim_macos
      ```
- [ ] **Practice run once, sitting at the Mac:** `./demo.sh`. The 3D window opens only
      when you are logged in at the Mac's own screen with the display awake.
      It should end with `Verdict: PASS`. Leave the terminal ready.
- [ ] **Backup video ready.** Open `~/Downloads/drone/demo/follow_moving_person.mp4`
      in QuickTime, paused on the first frame, in a second window.
- [ ] Plug in the charger. A laptop on battery can run the simulator slower.

A normal scorecard (rehearsal, Sep 11) looks like this:

```
 SCORECARD  Person swaying side to side (+-1.2 m)
 Person tracked:           99.6% of camera frames (570 frames, 38 s)
 Average heading error:     2.7 deg (worst 8.4 deg) vs the person's true position
 Landed OK:               yes (height after landing 0.02 m)
 How it ended:            flew the planned time, then landed on its own
 Verdict:                 PASS
```

The numbers move a little from run to run: about 99% tracked, 2.5 to 3
degrees on average, 7 to 9 degrees worst. That is normal.

## The talk (about 3 minutes)

**0:00, before pressing Enter (20 s).**
> "This is our person-following nano-drone, running in a simulator on my
> laptop. The drone is a Crazyflie with an AI-deck: a camera and a 64 milliwatt
> chip that runs our neural network. The network looks at each camera frame and
> answers three things: is there a person, where are they left to right, and
> how big are they. The drone turns toward the person and moves closer."

Type `./demo.sh` and press Enter.

**0:20, the terminal says "Starting the simulator" (15 s).** A 3D window opens.
> "This is MinHyuk's simulator, CrazySim. The drone runs the real Crazyflie
> firmware, compiled for a PC. The physics and the camera are simulated. Our
> model runs on the laptop, reads the simulated camera, and steers through the
> same radio library we would use on the real drone. The person is a real photo
> from the COCO dataset, one of the validation images the model never trained
> on, on a panel that sways left and right."

**0:35, the drone takes off and hovers.**
> "It does not move until it is sure. It needs three frames in a row at
> confidence 0.75 or higher before it starts following."

**0:45, the drone turns to follow (about 40 s).** You can drag in the window to rotate the view.
> "Now it is following. The person moves 1.2 meters each way. The drone turns
> to keep them centered, and only moves forward when they are roughly
> centered. Speed is capped at 0.3 meters per second and turning at 40 degrees
> per second. If it loses the person, it hovers in place."

**1:35, it lands and the scorecard prints.** Read it out:
> "It tracked the person in about 99% of frames. The heading error, measured
> against where the simulator says the person really is, was about 3 degrees
> on average. It landed cleanly."

**1:45, optional second run (about 50 s):** `./demo.sh --scene freeze`
> "This one tests a safety rule. It follows for a few seconds, then I freeze
> the camera feed on purpose. When the newest frame is more than half a second old, the drone
> hovers. After 3 seconds without a fresh frame, it lands."

If time is short, skip it and say the freeze and empty-room tests are in the results.

**2:30, close (30 s).**
> "To be clear about what this shows: it tests the control loop and the safety
> rules, with the full-precision model on the laptop. It has not flown on the
> real drone yet. The network is now integrated in a local branch of the drone
> firmware. The next steps are real camera frames from the AI-deck with the
> motors off, and a bench test once the flight-controller code is written."

## Key numbers (all verified; sources: EXPERIMENTS.md, docs/progress/sai_maruvada.md)

| What | Number |
|---|---|
| Person swaying ±1.2 m | tracked 99.7% of frames; heading error 2.7° average, 7.7° worst |
| Person standing 3.5 m out, 1 m right | tracked 99.4%; 1.1° average; closed from 3.64 m to 2.28 m |
| Empty room | tracked 0%; did not move (0.00 m) |
| Camera frozen mid-flight | hovered when the newest frame was 0.52 s old; landed at 3.0 s |
| At the chip's speed (6.5 per second, 153 ms delay) | tracked 99.2%; 3.1° average (vs 2.7° at full speed) |
| Our model vs David's released model | peak F1 0.8008 vs 0.789 (simulated quantized form) |
| Chip network vs full-precision model, 1,000 random images | 93-96% agree on "person or not" |
| 8-core chip build (chip simulator) | 154 ms to 23 ms per inference (debug output off; 62 ms with the current default) |

## If something goes wrong: fallback plan

Stay calm and switch to the backup video. Say:
> "The simulator is picky about the laptop's display, so I rendered this flight
> from its logs earlier. Same run, same scorecard."

| Problem | What to do |
|---|---|
| "The Mac screen is locked" / the 3D window closes | Play the backup video, or run `./demo.sh --headless` (no window, still prints the scorecard) |
| "The 3D viewer cannot open a window right now" | Move the mouse or press a key to wake the display, unlock, retry once. Still failing: `./demo.sh --headless` or the video |
| "already running" | `./demo.sh --stop`, then `./demo.sh` again |
| "Docker is not running" | Open Docker Desktop, wait for "Engine running" (~30 s), retry |
| Anything else, or it hangs | Press Ctrl-C (it shuts everything down), then play the video |

Videos, in `~/Downloads/drone/demo/` (also in `docs/demo/` in the repo):

- `follow_moving_person.mp4` (about 45 s): the main demo. Left: what the
  drone's camera sees, where the model thinks the person is, and its
  confidence. Right: a map from above with the drone and the person's true
  position.
- `camera_freeze.mp4` (about 19 s): the camera freezes, the drone hovers, then lands.
- `empty_room.mp4` (about 21 s): nobody there, and the drone stays put.

## Likely questions, with short honest answers

**Why simulation first?**
The drone is small and breaks easily, and some failures you cannot safely
stage on hardware, like the camera freezing mid-flight. In simulation I can
repeat each test and score it against the person's true position. The team's
rule (Grace's gate) is that the follower passes these checks in simulation
before we touch hardware. The safety rules are MinHyuk's simulator exit criteria.

**Is this running on the real drone yet?**
No. This is the simulator, and the model here is the full-precision version
on my laptop. The chip version is in a local branch of the drone firmware.
It compiles and passed six safety review rounds in a timing simulator, but
it has not flown. The flight-controller team writes the last piece, then we
bench test.

**What was the chip bug?**
On Sep 10 I found that the network we had built for the chip gave the same
answer for every image. A tool that converts the network for the chip (DORY)
turned every negative weight into zero, but only on Apple Silicon Macs.
David built his on an Intel machine, so his worked. Our old check compared
the chip against a reference built from the same broken weights, so it
passed. I withdrew the claims that day, fixed the conversion, and added five
permanent checks. The fixed champion network passes all of them.

**How close is the chip version to what we see here?**
On 1,000 random images, the chip network and the full-precision model agree
93-96% of the time on whether a person is there. I also slowed the
simulated follower to the chip's speed, 6.5 frames per second with a 153 ms
delay. It still tracked 99.2% of frames, with 3.1 degrees average error.

**How realistic is the simulated camera?**
Not very. The camera sees a clean render of a photo on a panel. So this tests
the control loop and the safety rules, not how well the model sees in real
light. Real AI-deck frames are the next step; the capture protocol is written.

**What stops it from chasing something that isn't a person?**
It needs three frames in a row at 0.75 confidence before it moves (the bar
was 0.70 until 2026-09-13; `follow_person.py` now defaults to 0.75). In the
empty room it never started. Honestly the margin is thin there: the highest
score was 0.64, against the 0.7 it needed when that flight ran (0.75 now).

**What's next?**
Real camera frames from the AI-deck with the motors off, the
flight-controller code and a bench test, and re-checking the turning
direction on the real firmware. The simulator needed the steering sign
flipped, and the real drone might differ.

**How much of this did you write yourself?**
I built it with an AI coding assistant, Claude Code, as the project
encouraged. I chose the experiments, ran them, checked the results, and made
the decisions. They are written down in DECISIONS.md and the progress record.

## For reference

- One command: `tools/crazysim_macos/demo.sh` (`--help` lists options:
  `--scene moving|static|empty|freeze`, `--headless`, `--stop`).
- Each run's logs go to `tools/crazysim_macos/follow_runs/demo_<scene>_<time>/`
  (`scorecard.txt`, `analysis.txt`, `follower.log`).
- Re-make the videos: fly with `./demo.sh --headless --save-frames --out RUN`,
  then `../../../trainenv/bin/python make_demo_video.py RUN --scene moving --out video.mp4`
  (`follow_moving_person.mp4` adds `--start 1`, which trims the first second).
