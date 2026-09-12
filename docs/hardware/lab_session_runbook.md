# Lab session runbook: first real hardware

**Date:** TBC, next week. **Where:** the lab with the drone fleet.
**Who:** Sai, Grace (Yiming Hao), MinHyuk Park (Texas State, keeps the fleet, wrote the simulator).
**Nothing flies.** Props off, motors off, the whole session.

This is the first time anyone on our side touches real hardware. Time is shared and
short. This document exists so the session runs to a plan instead of being improvised
at the bench. Read section 1 and section 4 on the way there; the rest is reference.

Related documents. **All four exist** — checked by `ls` on 2026-09-12. Paths are
relative to `~/Downloads/drone/pytorch_ssd`.

| What | Where | Status |
|---|---|---|
| Frame capture protocol (marks, labels, consent, scoring) | `docs/real_frame_capture_protocol.md` | exists |
| Flashing the GAP8 app | `docs/hardware/flash_runbook.md` | exists |
| Measuring camera/sensor parameters | `docs/hardware/camera_measurement_protocol.md` | exists |
| Firmware hand-off, bench test, `t_fresh` rules | `docs/firmware_integration/HANDOFF.md` | exists |

**This document is the one that decides the running order.** Where a sibling
document implies a different order — in particular anything in
`flash_runbook.md`, which is written as a standalone build-and-flash guide —
**section 4 of this document wins**: capture first, flash last. Flashing
destroys the camera streamer that all of M1-M4 depend on.

**Where the shell must be.** The three documents grew separately and assume
three different working directories. Every command in *this* document now names
its own directory or uses an absolute path, so it does not matter which one you
are in. If you copy a command out of another document, check its own "run this
from" line first.

---

## 0. The short version

1. Capture real camera frames first. It is the only thing that cannot be done anywhere else.
2. Score the mirror check on the spot, before leaving the room.
3. Flash the champion app **last**, because flashing destroys the camera streamer
   that the capture depends on.
4. Nobody flies. The yaw-sign chain has never been checked on real hardware.
5. Frames go to `~/drone_frames/<date>/` and then the restricted shared drive. Never git.

---

## 1. Goals, in priority order

The ordering rule: **do the things that are impossible without the drone, and defer
everything a laptop can do later.**

### MUST happen (hardware-only, and everything else depends on them)

| # | Goal | Why it is first |
|---|---|---|
| M1 | **Stream check.** Get 5 frames off a real AI-deck onto the laptop, confirm `fmt=0`. | Until this works, nothing else in the session is possible. It is also the first time our capture tool meets a real deck. |
| M2 | **Camera type: mono or Bayer?** | One line of output, but it is a hard blocker for the firmware (HANDOFF risk 7: "if the deck is color, stop"). It also changes every later command in the session (`--bayer`). |
| M3 | **Mirror check, scored in the room.** | Decides whether any steering command we ever send turns the right way. It takes 10 minutes and it is the single highest-consequence bit of information available. If it reports MIRRORED, that fact reshapes the firmware work. |
| M4 | **Priority-1 frame bank, room light.** 3 distances x 5 bearings with one teammate, plus empty room, plus a plush/pet and a poster. | The irreplaceable artifact. It unblocks domain-gap retraining, the sensor measurements, and every future "does it work on real images" question — **and it can be re-scored offline against any model we ever train.** The protocol estimates about 25 minutes per lighting condition; section 4 budgets 40, to absorb repositioning and retakes. |

M4 is the reason the session is worth holding at all. Note what it buys: once the
frames exist, **champion vs confuser can be compared on real data without another lab
visit**, by re-running `score_real_frames.py --ckpt <other>.pth` over the same folder.
Capture once, score many times.

### SHOULD happen if time allows, in this order

| # | Goal | Why it is not a MUST |
|---|---|---|
| S1 | Bottle FOV measurement, then **only sections 4.1 and 4.2** of `docs/hardware/camera_measurement_protocol.md` (dark frame + flat field). See the time-budget box below — the rest of that protocol does not fit today. | Improves the accuracy of the numbers, but the frames from M4 already let most of it be redone offline. |
| S2 | Flash the champion app and run the **bench** test (HANDOFF section 5.2-5.3): tensor `match=1`, `mismatches=0`. Procedure: `docs/hardware/flash_runbook.md`. | This is the first silicon test of the network, and it is valuable — but it **overwrites the camera streamer**, so it can only run after M1-M4 are finished and backed up. |
| S3 | Live-camera app test (HANDOFF 5.5): `pre=`, `hz=`, `xb` walk-in/walk-out. | Depends on S2 succeeding. |
| S4 | The hardware links of the yaw-sign chain (protocol section 3, step 4): rotate the drone by hand on the tripod, watch `stabilizer.yaw` in cfclient, record the firmware version. | Needs a **Crazyradio dongle** (nobody here has one — confirm with MinHyuk). cfclient itself is now installed, in `cfloaderenv` (section 2.1). Only needed before a first flight, which is not this session. |

#### Time budget for S1 — the honest version

`camera_measurement_protocol.md` costs **20 minutes for Tier 1**, **45 for
Tier 1+2**, and 65 for all three tiers. Section 4 of this document has **10
minutes** for S1, and there is nowhere to take more from without cutting M4,
which is the reason the session is being held. So the protocol is **cut to fit**,
deliberately, and this is what that costs:

| If S1 gets | You run | You get | The board is |
|---|---|---|---|
| **10 min (today's plan)** | bottle FOV + protocol 4.1 (dark) + 4.2 (flat) | `dsnu_sigma_dn`, `vignette_a2`, `vignette_a4`, `prnu_sigma`, `dead_px_frac`, `banding_depth`, a gain cross-check, and a coarse HFOV — **6 of the 10 unmeasured parameters** | **not needed** — only a lens cover and a sheet of paper |
| 20 min (protocol Tier 1) | the above + 4.3 slanted edge | adds `psf_sigma_center_px`, `psf_sigma_corner_px` | **needed** (Target A) |
| 45 min (Tier 1+2) | + 5.1 ladder, 5.2 two-distance FOV, 5.3 AE step, 5.4 banding | adds `e_per_dn_1x`, `ae_damping`, an accurate `focal_px_per_rad` | **needed** (Targets A and B) |

**The 10-minute cut needs no targets at all**, which is also why the packing list
in section 3 does not put the session at risk if the board does not get made.
Build the board anyway (section 2.0): it is cheap, and it is the whole difference
between 6 parameters and 10 if the room turns out to be free.

**If the team wants Tier 1+2**, the honest options are (a) book a longer slot,
(b) move S2/S3 — flash and bench — to a second session and give S1 that 22
minutes, or (c) hold a separate camera session, which needs a drone and a room
but no people and no consent. **This is a team decision, not one this document
makes.** Today's plan assumes nobody decided, and takes the 10-minute cut.
| S5 | Second and third lighting conditions (`dim`, `window`), extra subjects `p02`/`p03`. | Pure repetition of M4. Cheap to add if the room is still free. |

### SKIP, explicitly, and say so out loud at the start

- **Any flight, and any propeller.** No Lighthouse setup, no tripods-and-base-stations
  time sink, no hover test, no takeoff. Setting up Lighthouse would eat most of the
  session and produce nothing we can use, because the yaw-sign chain is unverified.
- **Closed-loop person following.** It works in the simulator. Running it on hardware
  needs flight.
- **Debugging the distance-keeping bug** (settles near 3 m instead of 1.94 m). Root-caused
  at a desk on 2026-09-12 — see `docs/eval_results/2026-09-12-distance/README.md`.
  **It is not a size-head problem.** The MuJoCo groundplane material carries
  `reflectance="0.2"`, a 20% mirror, so the simulator draws the subject 1.5-2.0x too
  tall and the network reads the person plus their reflection as one object. The size
  head reads real people correctly (signed bias −0.007 to −0.015 over 2635 COCO val
  images; the chip network is unbiased to within 1%). Separately, the follower control
  law cannot reach 1.94 m at all — its floor is 2.43 m by construction. **Do not
  retrain or re-tune the size head**, and do not spend lab minutes on this.
  M4's frames are still the right way to check the size head against reality later.
- **Champion vs confuser comparison.** That is a pending team decision, and as noted it
  needs no hardware at all once M4 is done.
- **Tuning `k_yaw`, the follower, or any controller gain.**
- **Recording a demo video for Prof. Mok.** The simulator demo already exists.
- **Installing anything.** Joining the deck's WiFi access point takes the laptop off the
  internet. Nothing can be downloaded in the lab. See section 2.

---

## 2. Pre-lab checklist

Finish this **at least 24 hours before**, not the morning of. Every item has a command
whose output you must actually look at.

### 2.0 The one thing that must be BUILT, not bought or downloaded

> ### PRE-LAB BUILD TASK: the 600 x 600 mm matte white board
>
> **Owner: _______________   Due: the day before the lab   Cost: about $5**
>
> Nobody is tasked with this by default, and that is how it gets forgotten.
> **Assign a name and write the date on this line.**
>
> **Do you need it for today's plan?** *No.* Section 1's time-budget box cuts S1
> to protocol 4.1 + 4.2, which need only a lens cover and a sheet of printer
> paper. **Make it anyway** — it is the difference between 6 and 10 measured
> parameters if the room turns out to be free, and it cannot be made in the lab.
>
> **What it is:** one single piece of **matte white** card or board, about
> **600 x 600 mm**, **unprinted**.
>
> **Cheap ways to make one, in order of preference:**
>
> 1. One sheet of **white foam board or poster board** from any art, office or
>    craft shop. A standard 20x30 in (508x762 mm) sheet trimmed square is fine —
>    600 mm is a target, not a tolerance.
> 2. The **blank back of a large poster**, flattened under books overnight.
> 3. A sheet of **flip-chart paper** spray-mounted or taped flat onto cardboard —
>    tape only at the *outside edges*, never across the face.
>
> **Three rules, each for a measured reason** (protocol Appendix A):
>
> - **One piece, no seams.** A seam between two taped-together sheets is a thin
>   dark line, and the fixed-pattern measurement will faithfully record that line
>   as sensor non-uniformity.
> - **Unprinted.** Printer halftone texture is exactly what the PRNU measurement
>   is trying to see.
> - **Matte, not glossy.** Gloss throws a specular highlight of the room's lights
>   straight into the frame.
>
> **While you are at it, also make (5 more minutes, same trip):**
>
> - A piece of **matte black card** big enough to cover half the board — taped
>   over one half, deliberately crooked by about **5°** (a 52 mm offset top to
>   bottom over 600 mm). That turns the board into protocol Target A, the slanted
>   edge. Anything from 2° to 25° works; a perfectly vertical edge cannot be
>   measured at all.
> - A **matte black backdrop** at least 1 m across for protocol 5.1: black poster
>   board, a blackout curtain, or — free — a dark open doorway in the lab.
>
> **If the board does not exist on the day:** say so out loud at 0:00, and run
> only protocol 4.1 + 4.2 in slot S1. That is the plan anyway. Nothing collapses;
> you simply do not get `psf_sigma_center_px` or `e_per_dn_1x` this time.

### 2.1 What is installed on this machine (re-checked by running it, 2026-09-12)

Every line below was produced by running the command shown, on this Mac, today.

**Now present — this section previously said these were missing, and that is out
of date:**

```
$ ~/Downloads/drone/cfloaderenv/bin/python -m cfloader
==============================
 CrazyLoader Flash Utility
==============================
 Usage: .../cfloaderenv/lib/python3.14/site-packages/cfloader/__main__.py <action> ...

$ ~/Downloads/drone/cfloaderenv/bin/python -c "import cfclient; print(cfclient.VERSION)"
2026.8

$ ~/Downloads/drone/cfloaderenv/bin/python -c "from PyQt6 import QtCore; import cfclient.gui; print(QtCore.QT_VERSION_STR)"
6.7.1                                  # the GUI's import chain is intact

$ ls ~/Downloads/drone/cfloaderenv/bin/cfclient ~/Downloads/drone/cfloaderenv/bin/cfloader
(both present, executable)
```

`cfclient` and `cfloader` live **only in `~/Downloads/drone/cfloaderenv`** — a
fifth venv created on 2026-09-12 specifically for this. They are **not** in
`trainenv`, `nemoenv`, `crazysimenv` or `doryenv`, and there is **no `python` on
PATH at all** on this machine (`which python` → not found; only `python3`
exists, and `python3 -m cfloader` gives `No module named cfloader`). So every
cfclient/cfloader command must be spelled with the full venv path. See
`docs/hardware/flash_runbook.md` section 3 — this is the single most likely
copy-paste mistake of the session.

**`cv2` — INSTALLED 2026-09-12, no longer a blocker:**

```
$ ~/Downloads/drone/trainenv/bin/python -c "import cv2, numpy; print(cv2.__version__, numpy.__version__)"
4.9.0 1.24.4
```

It is in `trainenv` only, which is the venv the capture commands use. It was
installed with `--no-deps` and pinned to `opencv-python==4.9.0.80` on purpose:
`trainenv` holds numpy 1.24.4, which the training and export work depends on, and
an unpinned install would have dragged numpy forward. Verified after installing
that numpy is still 1.24.4 and `cflib` still imports. If you ever reinstall it,
use the same two flags. The other four venvs still have no cv2 and do not need it.

**A trap in that fallback, read from the source on 2026-09-12:**
`opencv-viewer.py` has `import cv2` at **line 70**, *after* `client_socket.connect()`
at line 58. So with cv2 missing it connects to the deck first and *then* dies on
the import — it will look like a deck problem when it is a laptop problem. It
also has no connect timeout: pointed at an unreachable deck it blocks for over a
minute before raising `TimeoutError: [Errno 60]`.

**Also verified present, by running it:**

```
cflib 0.1.33 in trainenv, crazysimenv and cfloaderenv (pip show cflib)
libusb symlinked at /opt/homebrew/lib/libusb-1.0.0.dylib -> Cellar/libusb/1.0.30/...
  and pyusb's libusb1 backend loads (<usb.backend.libusb1._LibUSB object ...>)
docker 29.7.2 running; bitcraze/aideck:latest -> sha256:038197df... 13.5 GB
aideck-gap8-examples is a real clone at 5fd95ca with tools/build/{make-example,make,build}
prebuilt images verified: shasum -a 256 -c SHA256SUMS -> both "OK"
checkpoint present: pytorch_ssd_unstable/artifacts/successor_qat_ep3_eval.pth
measure_camera.py selftest -> "24/24 recovered inside tolerance", 17 s wall
```

**One correction to an earlier claim in this section.** `cflib.crtp.scan_interfaces()`
does *not* return `[]` with no dongle. It prints `Cannot find a Crazyradio Dongle`
and then returns `[['udp://127.0.0.1:19850', '']]` — the CrazySim UDP interface. A
non-empty list is **not** evidence that your dongle was found; read the printed
line, not the list length.

### 2.2 Rehearse the whole capture chain at home

Use `tools/real_frames/mock_streamer.py`. It serves the same CPX-over-TCP bytes a real
AI-deck serves, rendered from the simulator scenes through the Himax sensor model, so
`cpx_grab.py` and `score_real_frames.py` cannot tell it from hardware.

**Every command below is absolute — it does not matter what directory you are in.**
(The version of this section before 2026-09-12 used `tools/real_frames/...`, which
only worked from `~/Downloads/drone/pytorch_ssd`.) The mock renders its frame bank
through MuJoCo first, so give it a few seconds and wait for the
`mock AI-deck streaming on tcp://...` banner before starting terminal 2.

**Terminal 1** (person on the drone's LEFT):

```bash
~/Downloads/drone/trainenv/bin/python \
  ~/Downloads/drone/pytorch_ssd/tools/real_frames/mock_streamer.py \
  --port 5151 --scene s15_static_offset --dist 2.5 --bearing -25 --fps 15
```

**Terminal 2:**

```bash
~/Downloads/drone/trainenv/bin/python \
  ~/Downloads/drone/pytorch_ssd/tools/crazysim_macos/cpx_grab.py \
  --host 127.0.0.1 --port 5151 --seconds 6 --every 1 \
  --dist 2.5 --bearing -25 --vis 1 --subject p01 --light room \
  --out ~/drone_rehearsal/mockcheck
```

Then stop the mock (Ctrl-C in terminal 1) and restart it serving the other side:

```bash
~/Downloads/drone/trainenv/bin/python \
  ~/Downloads/drone/pytorch_ssd/tools/real_frames/mock_streamer.py \
  --port 5151 --scene s15_static_offset --dist 2.5 --bearing 25 --fps 15
```

Record the matching clip into the **same** folder — note this is a *different*
`--bearing`, everything else is identical:

```bash
~/Downloads/drone/trainenv/bin/python \
  ~/Downloads/drone/pytorch_ssd/tools/crazysim_macos/cpx_grab.py \
  --host 127.0.0.1 --port 5151 --seconds 6 --every 1 \
  --dist 2.5 --bearing 25 --vis 1 --subject p01 --light room \
  --out ~/drone_rehearsal/mockcheck
```

Then score the folder:

```bash
~/Downloads/drone/trainenv/bin/python \
  ~/Downloads/drone/pytorch_ssd/tools/real_frames/score_real_frames.py \
  ~/drone_rehearsal/mockcheck
```

(Re-using port 5151 for the restart is fine — the mock sets `SO_REUSEADDR`, so it
binds again immediately. Verified 2026-09-12.)

Real output from this rehearsal on 2026-09-12:

```
model successor_qat_ep3_eval.pth | 180 frames in 2 clips | crop HFOV 70.0 deg | ...
clip (subject/light/take)           d     b vis    n  conf visacc track% starts expbin bins seen   binacc   +-1 bearErr
p01/room/take1                    2.5   -25   1   90  0.94   100%    98%      1      1 1:90          100%  100%    +1.3
p01/room/take1                    2.5    25   1   90  0.86   100%    98%      1      7 7:90          100%  100%    -0.7
EMPTY / NO-PERSON clips: 0 clips, 0 frames, confirmed (false) tracks = 0
MIRROR CHECK (person seen, |bearing| >= 8 deg): LEFT frames with bin < 4: 100% of 90;
  RIGHT frames with bin > 4: 100% of 90  -> PASS
```

**Also rehearse the failure**, so nobody has to interpret it for the first time under
time pressure. There is no `--mirror` flag; produce the MIRRORED verdict by **swapping
the labels**: serve `--bearing 25` and record it as `--bearing -25`, then serve
`--bearing -25` and record it as `--bearing 25`. Real output:

```
p01/room/take1                    2.5   -25   1   80  0.86   100%    98%      1      1 7:80      0%    0%   +49.3
p01/room/take1                    2.5    25   1   80  0.94   100%    98%      1      7 1:80      0%    0%   -48.7
MIRROR CHECK ... LEFT frames with bin < 4: 0% of 80; RIGHT frames with bin > 4: 0% of 80
  -> MIRRORED: image looks flipped (left and right swapped)
```

And rehearse an empty clip, which is what a no-person recording should look like
(`--vis 0 --subject empty`, mock `--scene s02_control_empty`):

```
EMPTY / NO-PERSON clips: 1 clips, 100 frames, confirmed (false) tracks = 0,
  frames with conf >= 0.5: 0, max conf 0.44  -> OK
MIRROR CHECK: no detected person frames with |bearing| >= 8 deg
  -> NO DATA (the model saw nobody, or no clip is off-center): stop and report
```

Two things this rehearsal teaches that are not obvious from the protocol:

- **`PASS` is not always a pass.** Scoring a folder that has only one side prints
  `PASS (only LEFT data; record the other side too)`. Both sides must be counted.
- **The JPEG warning fires on every JPEG stream, labelled or not** — including the
  unlabelled `--n 5` stream check, which is the point of that check. It prints once,
  on the first JPEG frame, *above* the `saved` lines, so it scrolls off the top of a
  long capture: `warning: the camera is streaming JPEG. For clips you will score, set
  the streamer to raw (format 0): the on-chip model never sees JPEG artefacts.`
  Still read `fmt=` on the `saved` lines yourself — that is the check that cannot
  scroll away. (Re-verified 2026-09-12 against a format-1 mock, both with and without
  labels; `cpx_grab.py` warns unconditionally at the first `fmt==1` frame.)

**macOS rehearsal trap.** On this Mac, ControlCenter (AirPlay Receiver) already listens on
TCP port 5000. If your mock is not running, `cpx_grab.py --host 127.0.0.1 --port 5000`
still prints `connected to tcp://127.0.0.1:5000` and then sits until
`no data for 10 s; stopping (is the camera streaming?)` — you are talking to AirPlay, not
to your mock. Rehearse on port 5151 or turn AirPlay Receiver off. This does **not** affect
the lab: the real deck is a different host (`192.168.4.1:5000`).

**This trap includes `cpx_grab.py --mock`**, whose whole point is rehearsal: `--mock` is
shorthand for `--host 127.0.0.1 --port 5000`, i.e. exactly the colliding port. `cpx_grab.py`
does detect the case and prints a hint after the timeout —

```
no data for 10 s; stopping (is the camera streaming?)
hint: the connection was accepted but nothing was sent. On macOS, AirPlay Receiver listens
on port 5000 too and answers silently. Start tools/real_frames/mock_streamer.py, or turn
AirPlay Receiver off in System Settings > General > AirDrop & Handoff, or use --port.
```

— but you wait out the full timeout first. The commands in 2.2 use `--port 5151` to avoid
this entirely.

**Reconciling this with `camera_measurement_protocol.md` section 3.0**, which tells
you to run the mock on `--port 5000` and add `--mock` to every capture. **Both are
correct; they fail differently.** Checked by running all of it on 2026-09-12:

- ControlCenter really does hold port 5000: `lsof -nP -iTCP:5000 -sTCP:LISTEN`
  shows `ControlCe ... TCP *:5000 (LISTEN)` on both IPv4 and IPv6, and a bind to
  `0.0.0.0:5000` fails with `[Errno 48] Address already in use`.
- **But `mock_streamer.py` binds `127.0.0.1` by default, not `0.0.0.0`**, and that
  narrower bind succeeds alongside ControlCenter's wildcard one. A connection to
  `127.0.0.1:5000` then goes to the mock, not to AirPlay. Verified end to end:
  `cpx_grab.py --mock --n 5` against a port-5000 mock printed
  `5 saved, 5 received, 0 undecodable, 0 cut short` with every line `fmt=0`.
- The mock even warns you itself, in its startup banner:
  `NOTE: something else was already answering on 127.0.0.1:5000 ... if you stop the
  mock, cpx_grab will connect to that other service and hang.`

So: **the camera protocol's port-5000 rehearsal works, as long as the mock is
started first and stays up.** The only failure is the one above — mock not
running, `--mock` silently reaching AirPlay, 10 s of confusion. Port 5151 sidesteps
that failure and costs one extra flag. Use whichever the document in front of you
says; do not "fix" one to match the other in the middle of a rehearsal.

For reference, a genuinely refused connection on **this** machine looks like this
(the hint text differs for a remote host such as the real deck):

```
could not connect to tcp://127.0.0.1:5051: [Errno 61] Connection refused
Nothing is listening on this machine's port 5051. For a real AI-deck drop --host (it defaults to the deck's access point), for the simulator use --sim, for a rehearsal use --mock.
```

### 2.3 Other pre-lab items

- [ ] Re-read `docs/real_frame_capture_protocol.md` sections 1-4. Print section 2's
      bearing table and section 4's recording table.
- [ ] Print the **log sheet**: columns for clip label, time, subject ID, lighting, notes.
      Also a line each for: camera type (gray / Bayer), full MIRROR CHECK line, firmware
      version, the five yaw-sign chain links, AP SSID, battery serial/notes.
- [ ] Print a **life-size person poster** (protocol priority 1). Roll it, don't fold it.
- [ ] Charge: laptop to 100%, phone (as a stopwatch and second camera for documenting the setup).
- [ ] Free at least **5 GB** on the laptop. The arithmetic, now that the pieces
      agree across the three documents: the WiFi stream runs at **~13 fps**
      (`camera_measurement_protocol.md` 5.3 and its section 9 table), so a 30 s
      clip is about **390 frames**; the capture protocol estimates **~50 KB** per
      real frame; priority 1 in one light is 15 person clips plus ~7 negatives,
      so **22 × 390 × 50 KB ≈ 0.4 GB**. Three lighting conditions and extra
      subjects would still be about **1.5 GB**.

      An earlier version of this line said "roughly 1-2 GB for priority 1 in one
      light", which was about 4x high — it did not divide by the frame rate.
      **5 GB free is still the right ask**: the per-frame size is UNVERIFIED
      (nobody has seen a real frame), the synthetic rehearsal frames compressed to
      about **7 KB** each and real sensor noise compresses far worse, and running
      out of disk mid-capture is unrecoverable while spare gigabytes cost nothing.
- [ ] `git pull --rebase`. **But read the next item before trusting it.**
- [ ] **Confirm the files exist, with `ls` — a `git pull` will not deliver several of
      them.** The two sibling documents now exist (checked 2026-09-12), so the old
      "drop S1/S2 if the document is missing" advice is withdrawn. The *new* problem is
      that the lab-critical files are **untracked**, so they live only on this Mac:

      ```bash
      cd ~/Downloads/drone/pytorch_ssd && git status --porcelain \
        docs/hardware/ tools/real_frames/
      ```

      Real output on 2026-09-12:

      ```
      ?? docs/hardware/
      ?? tools/real_frames/measure_camera.py
      ?? tools/real_frames/mock_streamer.py
      ```

      `??` means untracked. **A `git pull` cannot bring down a file that was never
      committed, and a fresh clone on another laptop would have none of these** — no
      flash runbook, no camera protocol, no mock streamer, no `measure_camera.py`.
      So either **take this Mac to the lab**, or copy those paths across by hand
      (USB stick, AirDrop, scp) and check them with `ls` on the machine you will
      actually use. Getting them committed is version-control work that belongs
      outside the lab prep; just do not assume it happened.

      Then confirm, on the laptop you are taking:

      ```bash
      ls -l ~/Downloads/drone/pytorch_ssd/docs/hardware/flash_runbook.md \
            ~/Downloads/drone/pytorch_ssd/docs/hardware/camera_measurement_protocol.md \
            ~/Downloads/drone/pytorch_ssd/docs/real_frame_capture_protocol.md \
            ~/Downloads/drone/pytorch_ssd/tools/real_frames/mock_streamer.py \
            ~/Downloads/drone/pytorch_ssd/tools/real_frames/measure_camera.py \
            ~/Downloads/drone/pytorch_ssd/tools/real_frames/score_real_frames.py \
            ~/Downloads/drone/pytorch_ssd/tools/crazysim_macos/cpx_grab.py
      ```
- [ ] **Assign the board build task in section 2.0** to a named person, with a date.
      It is the only item on this list that cannot be done in the lab, on the morning
      of, or from a laptop.
- [ ] Prove the camera-measurement analysis runs offline, so S1's output means
      something. Takes about 20 seconds (17 s measured on 2026-09-12):

      ```bash
      ~/Downloads/drone/trainenv/bin/python \
        ~/Downloads/drone/pytorch_ssd/tools/real_frames/measure_camera.py selftest
      ```

      The last line must read `24/24 recovered inside tolerance`.
- [ ] Confirm the checkpoint is on the laptop and the scorer runs offline. Scoring is
      fast: 192 frames took **1.4 s wall** end to end including model load, so scoring
      in the room costs nothing.
- [ ] Send MinHyuk section 7's questions **the day before**, so the answers arrive before
      the session rather than during it.

---

## 3. Packing list

**This list is now the only packing list.** `camera_measurement_protocol.md`
section 2 has its own "What to bring"; everything in it that today's plan needs
has been folded in here. If the two ever disagree again, this one is the one that
got checked against the running order in section 4.

**Withdrawn from this list on 2026-09-12: the grey card and colour checker.**
They were here for `camera_measurement_protocol.md`, and **that protocol uses
neither** — it has no grey-card step anywhere. It cannot: over the WiFi streamer
nothing can read or set a sensor register, so every method in it works by changing
what is *in front of* the camera, and the auto-exposure parks the frame mean at
60 DN regardless of what grey you show it. Leave them at home. What that protocol
actually wants is in section 2.0 (the white board) and in the "Measurement and
marking" list below.

**Electronics**

- [ ] Laptop + charger
- [ ] Crazyradio PA dongle + USB-C adapter (confirm with MinHyuk who brings this)
- [ ] JTAG programmer + 20-to-10-pin adapter, if `flash_runbook.md` calls for it
- [ ] USB cables: micro-USB for the Crazyflie, whatever the deck needs
- [ ] Powered USB hub (dongle + programmer + charger on one laptop is tight)
- [ ] Phone (stopwatch, photos of the setup, hotspot for anything you forgot **before**
      joining the deck's AP)

**Measurement and marking**

- [ ] Tape measure, at least 5 m
- [ ] Painter's tape for floor marks (comes off lab floors; gaffer tape does not always)
- [ ] Marker pen for writing distances/bearings on the tape
- [ ] Protractor or a printed bearing fan, for the ±10° and ±25° lines
- [ ] Camera tripod with a head that can hold the drone with the **lens at 0.8 m** —
      measure to the lens, not the tripod head
- [ ] Small clamp / velcro / elastic to hold the drone on the tripod head
- [ ] Spirit level or a phone level app, so "points level" is true

**Targets — for the people protocol (M1-M4)**

- [ ] Printed life-size person poster
- [ ] Stuffed animal (the `plush` negative)
- [ ] A bottle or similar narrow object, for the coarse FOV edge measurement in S1

**Targets — for the camera protocol (S1)**

Only the first three are needed for today's 10-minute S1. The rest are for
protocol 4.3 / 5.1 / 5.2, which do not fit today (section 1's time-budget box) —
bring them anyway if they exist, in case the room stays free.

- [ ] **Lens cover** for protocol 4.1 — black electrical tape works; a bottle cap
      wrapped in black tape is better. Two layers; any light leak ruins the dark frame.
- [ ] **Plain white printer paper**, unprinted, a few sheets — the 4.2 diffuser.
      It gets taped flat across the lens, 1-2 mm from it.
- [ ] Masking tape and black electrical tape
- [ ] The **600 x 600 mm matte white board** from section 2.0 *(4.3 and 5.1)*
- [ ] **Matte black card** to tape over half the board at ~5° *(4.3)*
- [ ] **Matte black backdrop**, at least 1 m across *(5.1)* — or find a dark open
      doorway in the lab, which is free
- [ ] Phone light-meter app, optional *(6.1, will not happen today)*

**Paper**

- [ ] Printed log sheet (several copies)
- [ ] Printed bearing table from the protocol
- [ ] Printed section 4 of this document (the running order)
- [ ] Pen. Two pens.

**From MinHyuk (confirm in advance — do not assume)**

- [ ] Drone sets with AI-deck, pre-flashed with the patched camera streamer
- [ ] **~3 spare batteries per drone.** The fleet's batteries are aging; this is the
      most likely thing to end the session early.
- [ ] Battery charger(s)
- [ ] Spare propellers (not used today, but a dropped drone is a dropped drone)

---

## 4. Running order

Written for a **2-hour** slot. If the slot is shorter, run the 45-minute collapse in
section 4.3 and stop; do not compress every step proportionally.

> **Section-number collision, because it will bite otherwise.** This document's
> subsections 4.0-4.4 are about the *running order*.
> `camera_measurement_protocol.md` also has sections 4.1, 4.2 and 4.3, and those
> are *measurements* (dark frame, flat field, slanted edge). **Every reference to
> that document below names the file**, e.g. "`camera_measurement_protocol.md`
> 4.1". A bare "4.1" always means this document's own — the 45-minute collapse.
> (Renumbered on 2026-09-12: this document's "If you only get 45 minutes" moved
> from 4.1 to 4.3 to reduce the overlap.)

The sequencing rule: **the irreversible, hardware-only data capture goes first, and the
step that destroys the camera streamer goes last.** The AI-deck's GAP8 runs one
application at a time. Flashing the champion app replaces the camera streamer, so every
frame you will ever want must be on the laptop and backed up before the first flash.

| Time | Step | Done when |
|---|---|---|
| 0:00-0:08 | **Set the plan.** Say out loud: props off, nothing flies, capture first, flash last. Ask MinHyuk the top three questions from section 7 (AP naming, camera type, which drone to use). Pick **one** drone and write its ID on the log sheet. | Everyone agrees the session ends with frames on the laptop. |
| 0:08-0:15 | **Tripod and marks.** Drone on the tripod, **props off**, lens at 0.8 m, level, pointing down a taped centre line. Tape the 1.5 / 2.5 / 3.5 m marks and the ±10° / ±25° fans from the protocol's table. | Someone standing on the 2.5 m / 0° mark is centred in the viewer. |
| 0:15-0:22 | **M1 stream check.** Power the drone, join its WiFi AP, paste the header block from 4.0, then: `grab --n 5 --every 1 --out $D/check`. Read every `saved` line. | 5 files saved, every line shows **`fmt=0`**. |
| 0:22-0:27 | **M2 camera type.** Open one frame. Fine checkerboard texture = colour/Bayer camera. Write "gray" or "colour camera" on the log sheet. If colour, **add `--bayer` to every later `cpx_grab.py` command** — **except the S1 camera-measurement clips at 1:25, which must NEVER have `--bayer`** (it averages each 2x2 cell and destroys the per-pixel structure those measurements are made of; see 4.0a). Tell the firmware team (HANDOFF risk 7). | One word on the log sheet. |
| 0:27-0:40 | **M3 mirror check.** Two 10 s clips into `.../mirror`: teammate at 2.5 m, bearing −25 (drone's LEFT), then 2.5 m, +25. Score **that folder only**, in the room. Write the full MIRROR CHECK line on the log sheet. | The line says `PASS` with **both** LEFT and RIGHT counted. Anything else: see section 5. |
| 0:40-1:10 | **M4 priority-1 capture, room light.** 30 s clips, `--every 1`, protocol section 4 order: teammate `p01` at 3 distances x 5 bearings. Log each clip as you go. | 15 clips recorded, or the time box ends — whichever first. |
| 1:10-1:20 | **M4 negatives.** Empty room (3 walls/corners, `take1..3`, `--vis 0`); plush/pet at 2.5 m `--vis 0`; poster at −25 / 0 / +25 `--vis 1`. | Negatives recorded. These are the clips that catch a drone chasing a dog. |
| 1:20-1:25 | **Back up now.** Copy `~/drone_frames/<date>/` to a second drive or the shared drive **before** anything gets reflashed. Run the scorer over the whole folder and read the EMPTY line and the MIRROR CHECK line. | A second copy exists somewhere that is not this laptop. |
| 1:25-1:35 | **S1 FOV + sensor measurements. Exactly three things, in this order — see 4.0a.** (a) Bottle FOV: slide a bottle sideways at 2.5 m until it just leaves the frame on each side; record `s_left`, `s_right`. (b) `camera_measurement_protocol.md` **4.1** dark frame. (c) that protocol's **4.2** flat field. **Nothing else from that protocol.** No grey card — it has no grey-card step. | `s_left` / `s_right` on the log sheet, and a `dark/` and `flat/` folder on disk. |
| 1:35-1:50 | **S2 flash + bench.** Only now, and only after the 1:20 backup is confirmed — **flashing destroys the camera streamer M1-M4 depend on, and MinHyuk has to put it back.** Follow `docs/hardware/flash_runbook.md` (build: §3 / §6a offline / §6 prebuilt; flash: §4; verify: §5), then HANDOFF section 5.2-5.3. Flash the **bench** image first. Watch the console for `model init OK (champion 14-out, cores=8)`, then for **both** bench lines: `BENCH_TENSOR_I32 ... match=1` and `BENCH iter=... mismatches=0`. Record `infer`, `total`, `period` at CORE=8 and CORE=1. | `match=1` on every logged iteration, `mismatches=0`. Or a clear failure written down. |
| 1:50-1:57 | **S3 live camera**, if S2 passed: reflash the non-bench image, watch `frame= cap= pre= infer= hz= trk= xb=`. Repeat the left/right check reading `xb` directly. Walk in and out; `trk` should go 0→1 about 3 frames after you enter. | `pre=` and `hz=` numbers on the log sheet. |
| 1:57-2:00 | **Pack and hand back.** Ask MinHyuk to reflash the camera streamer if you left the champion app on the deck, or note that it needs doing. Remove tape. Return batteries. | Drone returned in a known state, written down. |

### 4.0 The commands you will actually type (M1-M4)

Copy these onto the printed sheet. `<date>` is today, e.g. `2026-09-19`. Add `--bayer`
to every `cpx_grab.py` line if step M2 says the camera is colour.

**These commands work from any directory** — the `grab` and `score` shell *functions*
below hold absolute paths. Paste the header block once per terminal, and if you open a
second tab, paste it again. (Before 2026-09-12 this block used relative
`tools/...` paths and silently required you to be in `~/Downloads/drone/pytorch_ssd`;
from anywhere else it printed `can't open file '.../tools/crazysim_macos/cpx_grab.py'`.)

**If you are not sure about M2, leave `--bayer` off.** The two mistakes are not
symmetric, and this is the one thing worth knowing about M2 under time pressure:

- **Forgetting `--bayer` on a colour deck costs nothing.** Without it the raw Bayer
  mosaic is written to the PNG losslessly, and the exact `--bayer` image can be
  rebuilt at a desk afterwards. Verified 2026-09-12: applying `cpx_grab.bayer_to_gray`
  offline to a no-`--bayer` capture reproduced the `--bayer` capture **bit for bit**
  (max abs diff 0).
- **Using `--bayer` on a mono deck destroys data.** The conversion averages each 2x2
  cell and upsamples back, and that is irreversible. The frames cannot be recovered.

So `--bayer` is a decision you can safely defer, and M2 is a thing to *write down*,
not a thing to block capture on. Do not spend lab minutes debating it.

```bash
# --- paste this header once per terminal; all paths inside are absolute ---
grab()  { ~/Downloads/drone/trainenv/bin/python \
          ~/Downloads/drone/pytorch_ssd/tools/crazysim_macos/cpx_grab.py "$@"; }
score() { ~/Downloads/drone/trainenv/bin/python \
          ~/Downloads/drone/pytorch_ssd/tools/real_frames/score_real_frames.py "$@"; }
D=~/drone_frames/$(date +%F)
grab --help | head -2          # must print usage, not "command not found"
# --------------------------------------------------------------------------

# M1 stream check - read fmt= on every saved line
grab --n 5 --every 1 --out $D/check

# M3 mirror check - two 10 s clips into the SAME folder, then score that folder only
grab --seconds 10 --every 1 \
     --dist 2.5 --bearing -25 --vis 1 --subject p01 --light room --out $D/mirror
grab --seconds 10 --every 1 \
     --dist 2.5 --bearing 25 --vis 1 --subject p01 --light room --out $D/mirror
score $D/mirror

# M4 one capture clip - vary --dist, --bearing, --subject, --light per the protocol table
grab --seconds 30 --every 1 \
     --dist 2.5 --bearing -25 --vis 1 --subject p01 --light room --out $D

# M4 an empty-room clip
grab --seconds 30 --every 1 \
     --vis 0 --subject empty --light room --out $D
```

> **Why functions and not `G="$P .../cpx_grab.py"`.** A two-word command stuffed
> into a variable works in bash and **fails in zsh**, which does not word-split
> unquoted variables. This Mac's default shell is zsh, and the failure is
> baffling under time pressure — zsh reports the whole thing as one filename:
> `zsh: no such file or directory: /Users/.../bin/python /Users/.../cpx_grab.py`.
> The function form above was run in **both** zsh and bash on 2026-09-12 and works
> in both. `camera_measurement_protocol.md` section 3.0 uses the same trick for
> the same reason.

Defaults worth knowing: with no `--host`, `cpx_grab.py` connects to `192.168.4.1:5000`,
which is the real deck (`REAL_HOST, REAL_PORT = "192.168.4.1", 5000` — cpx_grab.py line
99 as of 2026-09-12; `grep -n REAL_HOST` if the line number has drifted, the file is
under active edit). With no `--out` it writes to `~/drone_frames/<today>/`, and to
`~/drone_frames/rehearsal-<today>/` under `--mock`. A labelled clip refuses to overwrite
an earlier take and tells you the next free `--take` number.

### 4.0a The S1 commands (camera measurement, 10 minutes)

S1 uses a **different session folder** from the people frames, and a different set of
labels. Paste this second header block when you get to 1:25:

```bash
# --- S1 header; same function form as 4.0, works in zsh and bash ---
grab()    { ~/Downloads/drone/trainenv/bin/python \
            ~/Downloads/drone/pytorch_ssd/tools/crazysim_macos/cpx_grab.py "$@"; }
measure() { ~/Downloads/drone/trainenv/bin/python \
            ~/Downloads/drone/pytorch_ssd/tools/real_frames/measure_camera.py "$@"; }
S=~/camera_measure/$(date +%F)
mkdir -p "$S" && echo "session folder: $S"     # must NOT print "session folder: "
# --------------------------------------------------------------------

# (b) 4.1 DARK - lens taped over, two layers, room lights ON. ~25 s.
grab --seconds 25 --every 1 --vis 0 --subject dark --light capped   --out "$S"/dark

# (c) 4.2 FLAT - one sheet of printer paper taped 1-2 mm off the lens,
#     pointed at a bright even wall or the ceiling light. ~20 s each.
grab --seconds 20 --every 1 --vis 0 --subject flat --light diffuser --out "$S"/flat
#     then roll the drone 180 deg about the lens axis and repeat:
grab --seconds 20 --every 1 --vis 0 --subject flat --light diffuser --out "$S"/flat_roll180

# run the analysis BEFORE you pack up - this is the point of doing it in the room
measure "$S"
```

`camera_measurement_protocol.md` section 3.0 defines the same two helpers under
their script names (`cpx_grab.py` / `measure_camera.py`). **Either block is fine —
just do not paste both into one terminal and then lose track of which name you
are calling.** If you are working from that document in the room, use its block
and ignore this one.

Three things that will bite, all of them checked by running them on 2026-09-12:

- **Never pass `--bayer` to an S1 clip**, even if M2 said the deck is colour. It
  averages every 2x2 cell and destroys exactly the per-pixel structure these
  measurements are made of. (`--bayer` on the M1-M4 people clips is fine and
  reversible; here it is neither.)
- **`$S` must be set in the terminal you are typing into.** If it is empty the
  command becomes `--out /dark`, and `cpx_grab.py` connects to the deck *first*
  and only then prints
  `cannot create the output folder /dark: [Errno 30] Read-only file system: '/dark'`.
  The clip is lost. `echo "$S"` before you start.
- **`flat_roll180` is the designated drop** if the clock beats you. Skipping it
  makes the vignetting fit less trustworthy but does not break it, and the report
  says which happened. Dropping 4.1 or 4.2 entirely is not the trade — those two
  are what the whole 10 minutes buys.

### 4.3 If you only get 45 minutes

Run: set the plan (5) → tripod and marks (7) → stream check (5) → camera type (3) →
mirror check and score it (13) → as much priority-1 capture as fits (10) → back up (2).
**Stop there.** Do not start flashing. A session that ends with a scored mirror check
and even half a frame bank is a success; a session that ends with a half-flashed deck
and no frames is not.

### 4.4 If everything goes right and there is time left

In order: second lighting condition (`dim`), then more subjects (`p02`, `p03`), then the
third lighting condition (`window`), then the yaw-sign chain links from S4.

---

## 5. Decision points and fallbacks

Each one: the symptom, what to do, and how long to spend before moving on.

### The deck will not flash

- Do not let this block the session — **M1-M4 do not need flashing at all**, because
  MinHyuk's decks arrive pre-patched with a working camera streamer.
- Move flashing to the end of the session and carry on with capture.
- If `flash_runbook.md`'s route fails, try a second drone before debugging the first.
- **Time box: 15 minutes.** Then write down the exact error and stop. It is debuggable
  at a desk; frames are not.

### No WiFi access point appears

- Confirm the drone is actually powered (battery in, deck LEDs) and give it 20-30 s.
- The stock Bitcraze streamer advertises SSID **"WiFi streaming example"**
  (`wifi-img-streamer.c` line 179). MinHyuk's build may rename it — ask.
- Try a second drone immediately; with 6 working sets there is no reason to fight one.
- macOS sometimes refuses to stay on a network with no internet. Tell it to stay, and
  turn off "auto-join" for other networks for the session.
- If you reach the AP but `cpx_grab.py` cannot connect, fall back to Bitcraze's own
  viewer to prove the stream exists. **Absolute path, and a real python** — there is
  no `python` on PATH on this machine, so the command as it was written here before
  2026-09-12 (`python examples/other/...`) fails with `command not found: python`
  before it does anything:

  ```bash
  ~/Downloads/drone/trainenv/bin/python \
    ~/Downloads/drone/aideck-gap8-examples/examples/other/wifi-img-streamer/opencv-viewer.py \
    -n 192.168.4.1 -p 5000
  ```

  Both of these are real files and **only the first one is the right one**
  (verified by `find` on 2026-09-12):
  `examples/other/wifi-img-streamer/opencv-viewer.py` — use this;
  `examples/image_processing/FaceDetection/opencv-viewer.py` — not this.

  **It needs `cv2`, which is now installed in `trainenv`** (section 2.1), so run
  it with that venv's python. Its `import cv2` sits at line 70,
  *after* the socket connect at line 58, so a missing cv2 looks like a deck fault:
  it will connect, print `Socket connected`, and then die on the import. It also has
  no connect timeout — against an unreachable deck it blocks for over a minute
  before `TimeoutError: [Errno 60]`.

  Use it only to *see* that the stream works. It converts raw frames to colour, so
  do not score its saves — and `--save` writes to `stream_out/raw/` and
  `stream_out/debayer/` relative to your current directory, which must already
  exist or `cv2.imwrite` silently writes nothing.

### The stream is JPEG (`fmt=1`), not raw

- Do not record scoring clips. JPEG artefacts are something the on-chip model never sees.
- Fix: `StreamerMode_t streamerMode = RAW_ENCODING;` — it is already the default at
  `wifi-img-streamer.c:146`, so a JPEG stream means someone changed and reflashed it.
  Ask MinHyuk whether his patched build changed it.
- If it cannot be changed in the room, **still record the priority-1 set** and label the
  folder `JPEG_DO_NOT_SCORE`. Partially useful data beats none; just never quote scores
  from it.

### The mirror check reports MIRRORED

This is not a session failure; it is the session's most valuable result.

- Record it and keep capturing. The frames are still correct; only the interpretation of
  left/right changes, and the scorer can be told about it afterwards.
- Write the **full** MIRROR CHECK line on the log sheet, plus the camera orientation
  register value if MinHyuk knows it (`0x0101 = 3` flips both axes).
- Tell the firmware team the same day: the fix is either the sign in the STM32 controller
  or the orientation register, and **the choice must be written down** (HANDOFF 5.5).
- **Nobody flies until this is resolved and re-verified.**

### The mirror check reports FAIL or NO DATA

- **FAIL** (inconsistent bins) usually means the floor marks or the labels are wrong.
  Check that negative bearing really is the drone's LEFT *as seen from behind the drone*,
  re-tape if needed, and redo with `--take 2`.
- **NO DATA** means the model detected nobody. Check the subject is actually in frame at
  2.5 m, the lens is at 0.8 m and level, and the room is not so dark the frames are black.
- **Time box: 10 minutes and two retakes.** Then record it as unresolved, carry on with
  capture, and diagnose from the frames at a desk.

### Lighthouse is not set up

Fine. It is explicitly out of scope (section 1). If someone starts setting up tripods and
base stations, say that no flight is planned and the time is better spent on capture.

### Batteries die

- Expected: the fleet's batteries are aging. Ask for ~3 spares per drone.
- Swap on the spot and **write the swap in the log**, with the clip that was interrupted.
  A brownout mid-clip can truncate it; redo that clip with `--take 2`.
- Capture is deliberately front-loaded so a battery failure at 1:30 costs the flash test,
  not the frames.
- If all batteries are flat: stop capture, back up, and spend the remaining time on
  section 7's questions and on measuring the physical setup (tripod height, marks, FOV
  by eye) — cheap things that make the *next* session faster.

### The take-collision guard fires

Recording a clip whose labels already exist is refused, on purpose:

```
~/drone_frames/2026-09-12/mirror already has a recording with these labels, take 1 (d2.5_b-25_vis1_subj-p01_light-room_take1).
Use --take 2 for a new recording (delete the old take's files first if you are replacing it), or pick another --out folder.
```

Use `--take 2` and delete the bad take later. Do not rename files by hand; the scorer
reads the labels out of the filenames.

### You are running out of time

Ask, at the 1:10 mark: *have we got a scored mirror check and a backed-up frame bank?*
If yes, everything after that is a bonus and can be abandoned cleanly. If no, drop S1-S3
entirely and finish M3/M4.

---

## 6. Safety and consent

**Props off, no flight.** Remove all four propellers before powering anything on. Motors
stay off. Do not run `follow_person.py` or `flight_check.py`. This applies for the whole
session, including after a successful flash.

**Nobody flies until the yaw-sign chain is re-verified on hardware.** The chain is
`docs/real_frame_capture_protocol.md` section 3, step 4, and it has five links:

1. camera: person on the LEFT → x-bin < 4 → x < 0 (this is the mirror check)
2. follower: `yaw = yaw_sign · k_yaw · x`, with `yaw_sign = −1`
3. cflib version (ours is 0.1.33: MotionCommander passes the rate through, but
   `commander.py` negates it for legacy firmware — you will see a "legacy" warning)
4. Crazyflie firmware version (cfclient → Connect → console)
5. firmware behaviour: in CrazySim a positive yaw-rate command turns LEFT. On real
   hardware, rotate the drone left by hand on the tripod and check whether
   `stabilizer.yaw` increases in cfclient's plotter.

Only link 1 gets checked in this session. Links 4 and 5 need cfclient and a dongle.
**Whoever runs the first real flight re-checks all five, and it is not today.**

**Recording people.** Follow the protocol's section 1:

- Ask each person out loud before recording them. Nobody is recorded who has not agreed.
- Write only an ID on the log sheet (`p01`, `p02`, ...), never a name, and never a name in
  a filename.
- Wait for bystanders to leave the frame, or stop recording. The lab is a shared space.
- Anyone can ask later for their clips to be deleted, and we delete them — including from
  the backup copy.
- **Frames never enter git**, not this repo and not a fork. They are not uploaded to any
  public site or dataset.

**Physical care.** The drone is on a tripod at head height for a seated person. Clamp it
properly, keep cables out of the walkway, and do not leave it unattended on the tripod.

---

## 7. Questions for MinHyuk

Send these the day before. Only the fleet keeper knows the answers, and each one changes
what we do in the room.

**Before the session (these change the packing list or the plan)**

1. How long do we actually have, and is the room booked for that whole time?
2. Which drone should we use, and does it have a known-good AI-deck? Can we keep the same
   one for the whole session so the log sheet means something?
3. **Is the deck's camera the mono Himax or the Bayer colour one?** If any deck in the
   fleet is colour, we need to know which. It is a hard firmware blocker.
4. What is the SSID of the deck's access point in your patched build — still
   "WiFi streaming example", or renamed? If several drones are powered on, do their APs
   have distinct names, and can we power just one at a time?
5. Is there a password on the AP?
6. Who brings the Crazyradio dongle and the JTAG programmer — you or us?
7. How many charged batteries will there be, and is there a charger in the room?

**In the room**

8. Is your patched streamer in raw mode (`RAW_ENCODING`) or JPEG? Any other change from
   Bitcraze's `wifi-img-streamer` we should know about?
9. What is the camera orientation register set to (`0x0101`)? If we find a mirrored image,
   would you rather we fix it in the register or in the controller?
10. What Crazyflie firmware version is on these drones, and is CPX enabled in the build?
11. What frame rate does the streamer actually achieve on a real deck, and does it drop
    frames when the laptop is slow?
12. If we flash our own GAP8 app, how do we get your camera streamer back on the deck
    afterwards — do you have the image, or do we rebuild it?
13. Has anyone in your lab measured this camera's field of view? If so we can skip the
    bottle measurement and spend the time on capture.
14. Any lab rules we should know: who else uses the space, is the Lighthouse rig fragile,
    where do drones get stored?

**Forward-looking**

15. What would you want to see working before you would be comfortable with a first
    tethered flight?
16. When could a second session happen, and what should we have done by then?

---

## 8. After the lab, the same evening

Do this the same day. Details evaporate overnight.

**Data**

1. Copy `~/drone_frames/<date>/` to the team's **restricted shared drive** (members only)
   and post the path in the team chat. Do not post the frames themselves anywhere public.
2. Keep the laptop copy until the shared-drive copy is verified readable.
3. **Never `git add` frames.** Not this repo, not a fork, not "just one example image".
   If a frame needs to appear in a document, crop out identifiable people first and get
   the subject's agreement.

**Scoring**

4. Run the scorer over the whole folder and save the output:

   ```bash
   ~/Downloads/drone/trainenv/bin/python \
     ~/Downloads/drone/pytorch_ssd/tools/real_frames/score_real_frames.py \
     ~/drone_frames/<date> [--full-hfov <measured>] [--ckpt <other>.pth]
   ```

   (The scorer has no `--bayer`; Bayer conversion happens at capture time in
   `cpx_grab.py`, so colour-camera clips are already gray by the time they are scored.)

   It writes `scores.csv` and `scores.json` into the folder. Scoring is fast (192 frames
   took 1.4 s), so re-run it as often as you like.
5. Read, in this order: the **MIRROR CHECK** line, the **EMPTY / NO-PERSON** line
   (confirmed false tracks must be **0**), then `vis acc`, `bin acc`, `bearing err`.
6. If you measured the FOV, re-score with `--full-hfov <deg>`; the default assumes the
   simulator's 70°.

**Writing down**

7. Type the log sheet up while it is fresh. The things that must be recorded verbatim:
   - camera type (gray / Bayer)
   - the **full** MIRROR CHECK line
   - the AP SSID and any password
   - the Crazyflie firmware version
   - bench results if S2 ran: `match=`, `mismatches=`, `infer`, `total`, `period` at
     CORE=8 and CORE=1
   - which yaw-sign chain links were checked and which were not
   - what state each drone was left in (which GAP8 app is on it now)
   - what broke, and what you would bring next time
8. Update `docs/progress/sai_maruvada.md`: the session log and the live tracker rows for
   "First real AI-deck camera frames", "Rehearsing the real-frame capture", and
   "Flashing the champion app onto a real AI-deck".
9. Append any project decision made in the room to `DECISIONS.md`, and any measured
   result to `EXPERIMENTS.md`.
10. Email MinHyuk and Prof. Mok a short summary the same evening: what was captured, the
    mirror-check verdict, what is blocked, and what the next session needs. Short is fine.

**Do not do, the same evening**

- Do not retrain anything on the new frames yet. Look at the scores first; the interesting
  result may be that the model is fine and the geometry is not.
- Do not change the firmware's yaw sign on the strength of one mirror check without the
  team agreeing to it.

---

## Appendix: what in this document is verified, and what is not

**Verified by running it on 2026-09-12** (no hardware involved):

- The full capture chain `mock_streamer.py` → `cpx_grab.py` → `score_real_frames.py`,
  producing `MIRROR CHECK ... -> PASS` over 180 frames in 2 clips, bin accuracy 100%.
- The `MIRRORED` verdict, reproduced by swapping the clip labels.
- The `NO DATA` verdict, and the `EMPTY / NO-PERSON ... confirmed (false) tracks = 0` line.
- The one-sided `PASS (only LEFT data; record the other side too)` wording.
- The JPEG path: `fmt=1` on saved lines, `.jpg` files, and that the explicit warning fires
  on **every** JPEG stream, labelled or not. (An earlier draft of this document said the
  warning fires only for labelled clips. That was wrong and has been corrected — the
  check was re-run on 2026-09-12 both with and without labels, and `cpx_grab.py` warns
  unconditionally at the first `fmt==1` frame.)
- The `--bayer` colour-camera path runs end to end and still scores, **and** that a
  capture taken without `--bayer` reproduces the `--bayer` image bit for bit when the
  conversion is applied offline (max abs diff 0). Forgetting `--bayer` is recoverable;
  wrongly applying it is not.
- The take-collision guard message, and the connection-refused message (the localhost
  variant — `connect_hint()` prints different text for a remote host, so the real deck's
  refusal message will read differently and has not been seen).
- That scoring the whole date folder at once behaves: subfolders are prefixed
  (`mirror:p01/room/take1` vs `.:p01/room/take1`), so the M3 mirror clips and an M4 clip
  carrying identical labels do **not** merge, and the unlabelled `check/` frames are
  skipped with a `note: N image(s) without labels ignored` line rather than crashing.
  This is what makes step 1:20's "run the scorer over the whole folder" safe.
- The macOS ControlCenter/AirPlay collision on TCP port 5000 — and, re-checked on
  2026-09-12, that it does **not** stop the mock: `mock_streamer.py` binds
  `127.0.0.1` rather than `0.0.0.0`, so a port-5000 mock coexists with AirPlay and
  `cpx_grab.py --mock` reaches it (`5 saved, 5 received`). A bind to `0.0.0.0:5000`
  does fail, with `[Errno 48] Address already in use`.
- Scoring throughput: 192 frames in 1.4 s wall, including model load.
- `wifi-img-streamer.c` ships `streamerMode = RAW_ENCODING` (line 146) and SSID
  `"WiFi streaming example"` (line 179).

**Re-checked on 2026-09-12 and CORRECTED — the earlier version of this appendix was
wrong about two of these:**

- ~~"Missing on this machine: cfclient (all three venvs), cfloader, cv2 (all three
  venvs)."~~ **`cfloader` and `cfclient` now exist**, in a fifth venv,
  `~/Downloads/drone/cfloaderenv` (cfclient 2026.8, cflib 0.1.33, PyQt6 6.7.1,
  `cfloader` and `cfclient` executables both present). They are still absent from
  `trainenv`, `nemoenv`, `crazysimenv` and `doryenv`. **`cv2` is still missing —
  from all five venvs, cfloaderenv included.** See section 2.1 for the commands.
- ~~"`cflib.crtp.scan_interfaces()` ... prints 'Cannot find a Crazyradio Dongle' -> []"~~
  It returns **`[['udp://127.0.0.1:19850', '']]`**, not `[]`, in both `trainenv` and
  `cfloaderenv`. The printed warning is the signal; the list is not.
- Also present, re-verified by running: `cflib` 0.1.33 in trainenv/crazysimenv/cfloaderenv,
  libusb + pyusb backend, Docker 29.7.2 with `bitcraze/aideck:latest` at
  `sha256:038197df...`, `aideck-gap8-examples` a real clone at `5fd95ca` with
  `tools/build/`, the two prebuilt images passing `shasum -c SHA256SUMS`, and the
  `successor_qat_ep3_eval.pth` checkpoint.
- `measure_camera.py selftest` → `24/24 recovered inside tolerance` in 17 s wall.
- **The relative-path trap.** `python pytorch_ssd/tools/...` (the form used in
  `real_frame_capture_protocol.md` before this pass) fails two ways on this machine:
  there is no `python` on PATH at all (`command not found: python`), and the relative
  path resolves only from `~/Downloads/drone` — from `~` it gives
  `can't open file '/Users/saimaruvada/pytorch_ssd/tools/crazysim_macos/cpx_grab.py'`.
  Every command in all four documents is now absolute or carries its own `cd`.
- **The zsh word-splitting trap.** `G="$P .../cpx_grab.py"; $G --n 5` works in bash
  and fails in zsh, which is this Mac's shell. The shell-function form used in
  sections 4.0 and 4.0a was run in both shells and works in both.
- **`docs/hardware/`, `tools/real_frames/mock_streamer.py` and
  `tools/real_frames/measure_camera.py` are untracked** (`git status --porcelain`
  shows `??`). A `git pull` will not deliver them to another laptop. Section 2.3.

**UNVERIFIED — needs the real drone:**

- That a real AI-deck's stream is byte-compatible with `cpx_grab.py`. The mock was built
  from the same wire-format specification, not from a captured real stream, so a
  divergence in MinHyuk's patched build would show up only in the lab.
- Real frame rate, dropped-frame behaviour, and whether the AP holds a stable connection
  for a 30 s clip.
- Whether the fleet's camera is mono or Bayer.
- The mirror-check verdict itself. Everything about left/right on real hardware is open.
- Real frame size on disk, and therefore the true storage estimate.
- Every yaw-sign chain link except the follower's own sign convention.
- All of S2/S3: nothing in `HANDOFF.md` section 5 has ever run on silicon.
- The time boxes in section 4. They are estimates built from the protocol's own
  "priority 1 takes about 25 min in one light", not from a timed rehearsal with hardware.
