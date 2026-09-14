# GAP8 / AI-deck flash runbook

Written 2026-09-12 for the first hardware lab session with MinHyuk Park.
Everything below was run on Sai's Mac (macOS 26.6.2, arm64) **except the steps
marked UNVERIFIED**, which need the real drone.

> # ⛔ STOP — DO NOT FLASH UNTIL THE FRAMES ARE BACKED UP
>
> **Flashing replaces the camera streamer.** The GAP8 runs one application at a
> time, so the moment the champion app lands, MinHyuk's WiFi camera streamer is
> gone — and with it every capture in `docs/real_frame_capture_protocol.md`,
> which is the only thing in the whole session that cannot be done anywhere else.
> Getting the streamer back needs MinHyuk's image (open question 12 in the
> session runbook), not anything in this document.
>
> **This document does not decide when you run it.
> `docs/hardware/lab_session_runbook.md` section 4 does.** There it is step
> **S2, at 1:35**, after the mirror check is scored, the frame bank is recorded,
> and a second copy exists somewhere that is not the capture laptop. If you are
> reading this at the bench before 1:20, you are reading it too early.
>
> **Suggested order once you are cleared to flash: bench image first (§3a, §5),
> confirm `mismatches=0`, then the flight image.** That separates "the model is
> wrong" from "the camera or plumbing is wrong".

**The other three documents in this set** (all exist, all under
`~/Downloads/drone/pytorch_ssd/docs/`):
`hardware/lab_session_runbook.md` — the session plan and running order, which
outranks this document on timing; `real_frame_capture_protocol.md` — capturing
people frames; `hardware/camera_measurement_protocol.md` — measuring the sensor.
Both capture documents need the camera streamer, i.e. they run **before** this one.

---

## 0. The 60-second version

> **⚠ There is no `python` on PATH on this Mac.** `which python` → not found.
> Only `python3` exists, and `python3 -m cfloader` gives
> `ModuleNotFoundError: No module named 'cfloader'`. **Every command below spells
> out `~/Downloads/drone/cfloaderenv/bin/python` on purpose. Do not shorten it,
> and do not copy the shorter line the build script prints at the end** — see the
> boxed warning in §3.

```bash
# build (about 2m20s)
cd ~/Downloads/drone/crazyflie_ssd
bash ./flash_person_follow_aideck.sh

# flash (needs Crazyradio dongle + powered Crazyflie with AI-deck)
~/Downloads/drone/cfloaderenv/bin/python -m cfloader flash \
  ~/Downloads/drone/crazyflie_ssd/BUILD/GAP8_V2/GCC_RISCV_FREERTOS/target.board.devices.flash.img \
  deck-bcAI:gap8-fw -w radio://0/80/2M/E7E7E7E7E7

# verify (watch for lines starting "PFOLLOW:")
~/Downloads/drone/cfloaderenv/bin/python \
  ~/Downloads/drone/aideck-gap8-examples/_prebuilt_champion/cpx_console.py
```

The build step is the only one that needs a particular directory (`cd` is on its
own line above); the flash and verify steps are absolute and run from anywhere.
`cpx_console.py` takes an optional URI and duration —
`... cpx_console.py radio://0/80/2M/E7E7E7E7E7 30` — and defaults to
`radio://0/80/2M/E7E7E7E7E7` for 20 s if you give it neither.

If the build step is broken on the day, prebuilt images are already on disk at
`~/Downloads/drone/aideck-gap8-examples/_prebuilt_champion/` — skip to step 3.
Both were re-checked on 2026-09-12 — `cd` first, the checksum file lists bare
filenames:

```bash
cd ~/Downloads/drone/aideck-gap8-examples/_prebuilt_champion && shasum -a 256 -c SHA256SUMS
# champion_flight.img: OK
# champion_bench.img: OK
```

---

## 1. What was wrong, and what is fixed

**The blocker:** `~/Downloads/drone/aideck-gap8-examples` was not a clone of
anything. It was a hand-made folder containing one subdirectory of DORY output
(`examples/other/dory_examples/`) and nothing else — no `.git`, no remotes, no
`tools/`. The project's flash script needs
`aideck-gap8-examples/tools/build/make-example`, so every flash attempt failed
before it started.

**Fixed on 2026-09-12:** that directory is now a real clone of
`https://github.com/bitcraze/aideck-gap8-examples` at upstream `master`
(commit `5fd95ca`). `tools/build/{make-example,make,build}` are present. The
pre-existing `examples/other/dory_examples/` was preserved and is untracked.

**Also fixed:** the Docker image `bitcraze/aideck` existed locally only by
digest, with no `:latest` tag. The flash script asks for `bitcraze/aideck`,
which would have triggered a **multi-gigabyte download of a possibly different
image** in the lab, silently invalidating the GVSOC validation chain. (The exact
download size was never measured - the pull was never allowed to happen. The
local image is 13.5 GB uncompressed.) The validated digest is
now tagged `bitcraze/aideck:latest` locally.

**Also fixed:** `cfloader` was not installed anywhere on the machine — not in
`trainenv`, `nemoenv`, `crazysimenv`, `doryenv`, or on the system path. Without
it there is no way to flash over the radio at all. A dedicated venv now exists
at `~/Downloads/drone/cfloaderenv` with `cfclient 2026.8` / `cflib 0.1.33`.

---

## 2. What you need in the room

**Hardware**

| Item | Needed for | Notes |
|---|---|---|
| Crazyflie 2.x with AI-deck | everything | |
| **Crazyradio PA dongle** | flashing + console | **Hard requirement.** There is no other way in. |
| Charged battery / USB power | flashing | Deck must stay powered through the whole write |
| Olimex ARM-USB-TINY-H + ARM-JTAG-20-10 | brick recovery only | See §7. Not needed for normal work. |

**Software (all already installed and checked on Sai's Mac)**

| Item | Where | Verified |
|---|---|---|
| Docker Desktop, daemon running | `docker info` → `29.7.2` | yes, re-checked 2026-09-12 |
| `bitcraze/aideck:latest` → digest `sha256:038197df…` | `docker image ls` (13.5 GB) | yes, re-checked 2026-09-12 |
| `aideck-gap8-examples` with `tools/build/` | `~/Downloads/drone/`, clone at `5fd95ca` | yes, re-checked 2026-09-12 |
| `cfloader` | `~/Downloads/drone/cfloaderenv/bin/` **only** | yes, re-checked 2026-09-12 |
| `cfclient` 2026.8 (console + GUI) | `~/Downloads/drone/cfloaderenv/bin/` **only** | yes; PyQt6 6.7.1 import chain OK |
| libusb (Crazyradio dependency) | `/opt/homebrew/lib/libusb-1.0.dylib` → libusb 1.0.30 | yes, via brew |
| **`cv2` — installed 2026-09-12** | `trainenv` only (4.9.0, pinned, `--no-deps` so numpy stays 1.24.4) | **no.** Needed only by Bitcraze's `opencv-viewer.py`, i.e. by the *capture* fallback, not by flashing |

`cfclient` and `cfloader` live in a **fifth** venv created for this on 2026-09-12,
next to `trainenv` / `nemoenv` / `crazysimenv` / `doryenv`. `lab_session_runbook.md`
§2.1 used to say both were missing machine-wide; that is out of date and has been
corrected there too.

---

## 3. Step 1 — Build

```bash
cd ~/Downloads/drone/crazyflie_ssd
bash ./flash_person_follow_aideck.sh
```

Takes about **2 minutes 20 seconds**. The image is amd64 running under
emulation on Apple Silicon, which is why it is slow. That is normal.

**Success looks like this** — a memory report, then the flash command printed
back to you:

```
Memory region         Used Size  Region Size  %age Used
         FC_tcdm:        6600 B        16 KB     40.28%
 fc_tcdm_aliased:          12 B      16380 B      0.07%
              L2:       96640 B       512 KB     18.43%
         L1_sram:          16 B        64 KB      0.02%
...
Flash image:
  /Users/saimaruvada/Downloads/drone/crazyflie_ssd/BUILD/GAP8_V2/GCC_RISCV_FREERTOS/target.board.devices.flash.img

Flash command:
  python -m cfloader flash "..." deck-bcAI:gap8-fw -w "radio://0/80/2M/E7E7E7E7E7"
```

> # 🚨 THE LAST LINE THE SCRIPT PRINTS IS A TRAP. DO NOT PASTE IT.
>
> The script ends by printing a flash command that begins with a bare **`python`**
> (`flash_person_follow_aideck.sh` line 42, confirmed by reading it). **That
> command cannot work on this Mac.** It is the single most likely way to lose ten
> minutes at the bench, because it looks like the script is handing you the next
> step.
>
> **It fails twice over, both checked by running them on 2026-09-12:**
>
> ```
> $ which python
> python not found                     # no `python` on PATH at all, only python3
>
> $ python -m cfloader flash ...
> zsh: command not found: python
>
> $ python3 -m cfloader flash ...
> /opt/homebrew/opt/python@3.14/bin/python3.14: No module named cfloader
> ```
>
> `cfloader` exists in exactly **one** place on this machine:
> `~/Downloads/drone/cfloaderenv`. It is not in `trainenv`, `nemoenv`,
> `crazysimenv` or `doryenv` — all four re-checked today.
>
> **What to actually run.** Take the image *path* from the script's output; take
> everything else from here:
>
> ```bash
> ~/Downloads/drone/cfloaderenv/bin/python -m cfloader flash \
>   ~/Downloads/drone/crazyflie_ssd/BUILD/GAP8_V2/GCC_RISCV_FREERTOS/target.board.devices.flash.img \
>   deck-bcAI:gap8-fw -w radio://0/80/2M/E7E7E7E7E7
> ```
>
> **The one-line rule for the bench: if a flash command does not start with
> `~/Downloads/drone/cfloaderenv/bin/python`, it is the wrong one.**
>
> (This is a property of this laptop, not a bug in the script — it would be
> correct on a machine where `python` *is* the cfloader venv's interpreter. Do
> not "fix" the script in the lab.)
>
> Same command as §0 and §4. Checked by running both forms on 2026-09-12.

**Check the result is the expected binary:**

```bash
shasum -a 256 ~/Downloads/drone/crazyflie_ssd/BUILD/GAP8_V2/GCC_RISCV_FREERTOS/target.board.devices.flash.img
```

Expected for the flight build at commit `ff876bd` (the 2026-09-13 enter-bar change,
`APP_FOLLOW_VIS_ENTER_RAW` 4216 -> 5467; bundle head `fc42eb9` is a docs-only commit on
top of it and builds the same image):

```
261e20d8b03f091a2c18b0beccf46b3397a90a00ad3180c924d413a6099aeb8b
```

The build is reproducible — the `ff876bd` image was built twice from clean builds with
this identical hash (`docs/firmware_integration/HANDOFF.md`, section 4), and the earlier
`0623a7d` image (`c69e71e76431fa6bec3ea1abd690f3d9440bf3fcd8ca020a1d801795c5a3ef67`,
superseded 2026-09-13; it differs from the new one in exactly the 2 bytes of the enter
threshold) was produced three times in a row from clean builds, and a fourth time from a
separate copy of the source tree. A different hash means the source changed, not that
the build is flaky.

### 3a. Build variants

```bash
# on-hardware self-test build (fixed image, no camera) - see §5
bash ./flash_person_follow_aideck.sh radio://0/80/2M/E7E7E7E7E7 APP_BENCH_FIXED_INPUT=1
# expected sha256: 34c4b3bae3322dd04e555fe30b9b658f6480d4e006356aa683523af88ec4f929  (ff876bd; was 7fa0e8be… at 0623a7d)

# quiet build - startup and errors only, no per-frame spam
bash ./flash_person_follow_aideck.sh radio://0/80/2M/E7E7E7E7E7 APP_DEBUG=0
```

> **Careful:** every variant writes to the *same* output path. Build bench, you
> overwrite flight. Copy the `.img` out before rebuilding, or just use the
> prebuilt copies in `_prebuilt_champion/`.

### 3b. Never run these

The GAP SDK `all` and `flash` make targets **flash over JTAG and overwrite the
GAP8 bootloader**. Lose the bootloader and you lose over-the-air flashing
permanently until someone re-flashes it with a JTAG probe.

```bash
# DO NOT RUN
tools/build/make-example <dir> clean all     # 'all' includes flash_fs -> JTAG
tools/build/make-example <dir> flash
```

Always `clean build image`. The project script already does the right thing.

Evidence this is real, read straight out of the SDK inside the container on
2026-09-12:

```
/gap_sdk/utils/rules/pulp_rules.mk:216   all:: build image flash_fs
/gap_sdk/utils/rules/pulp_rules.mk:255   flash_fs:
        gapy ... run --flash --binary=$(BIN) ...
/gap_sdk/utils/rules/pulp_rules.mk:252   flash:
        gapy ... run --flash --force --binary=$(BIN) ...
```

`--flash` is a real device write, and `make-example` exports
`GAPY_OPENOCD_CABLE=interface/ftdi/olimex-arm-usb-tiny-h.cfg`, so it goes out
over JTAG. `image` (what we use) passes `--image` instead, which only writes a
file. Separately observed: `clean all` on hello-world reached the JTAG stage
and stopped only because no probe was attached.

---

## 4. Step 2 — Flash

Power the Crazyflie, plug in the Crazyradio, then:

```bash
~/Downloads/drone/cfloaderenv/bin/python -m cfloader flash \
  ~/Downloads/drone/crazyflie_ssd/BUILD/GAP8_V2/GCC_RISCV_FREERTOS/target.board.devices.flash.img \
  deck-bcAI:gap8-fw -w radio://0/80/2M/E7E7E7E7E7
```

Change `E7E7E7E7E7` if MinHyuk's drones use different addresses. Ask him for
the URI before you start; guessing wastes lab time.

**How the flash actually travels:** laptop → Crazyradio → nRF51 → STM32 →
ESP32 (NINA WiFi) → GAP8. It is a long chain. This is why it is slower and
more failure-prone than flashing the STM32, and why a flaky radio link shows up
as a mid-transfer stall.

**UNVERIFIED — no drone available.** The run gets as far as the radio layer and
stops with `Cannot find a Crazyradio Dongle`. What a *successful* transfer
prints, and how long it takes, has not been seen.

Be precise about what that does and does not prove:

- **Confirmed by running:** the image file opens. A bad path fails earlier and
  with a different message (`Could not open file ...`), so reaching the radio
  error means the image was read.
- **Confirmed by running:** the target *syntax* parses. `cfloader/__init__.py`
  requires exactly two hyphens in `deck-<target>-<type>`, and
  `deck-bcAI:gap8-fw` satisfies that.
- **NOT confirmed by running:** that `bcAI:gap8` is the correct deck *name*.
  cfloader never validates the name without hardware — a deliberately bogus
  `deck-TOTALLY:bogus-fw` produces byte-identical output to the real command.
  The only evidence for the name is `cflib/bootloader/__init__.py:214`, which
  lists `'bcAI:gap8'` among known decks. That is good evidence, but it was read
  from source, not observed against a deck.

### Failure modes

| What you see | What it means | Do this |
|---|---|---|
| `Cannot find a Crazyradio Dongle` | Dongle not plugged in or not claimed | Reseat it. On macOS no udev rules are needed; libusb is already installed. |
| `Failed to connect to Crazyflie` | Wrong URI, drone off, out of range | Confirm URI with MinHyuk. Power-cycle the drone. |
| `No deck memory found` / deck not listed | STM32 firmware too old, or deck not seated | Update Crazyflie firmware; reseat the deck. |
| Transfer stalls part-way | Radio link quality | Move closer, power-cycle, retry. A failed write is safe — see §7. |
| `Invalid deck target format` | Typo in the target | It is exactly `deck-bcAI:gap8-fw` — one colon, two hyphens. |

---

## 5. Step 3 — Verify the *champion* app is what is running

This is the step people skip and then spend an hour confused. An old app left
on the deck looks identical to a successful flash until you read the console.

Every log line from this app is prefixed **`PFOLLOW:`** and arrives over CPX,
so in the Crazyflie console it appears as `CPX: GAP8: PFOLLOW: ...`.

**Option A — headless (recommended, no GUI):**

```bash
~/Downloads/drone/cfloaderenv/bin/python \
  ~/Downloads/drone/aideck-gap8-examples/_prebuilt_champion/cpx_console.py \
  radio://0/80/2M/E7E7E7E7E7 30
```

**Option B — GUI:** `~/Downloads/drone/cfloaderenv/bin/cfclient`, connect, open
the Console tab.

### What a good boot looks like

Power-cycle the drone after flashing and expect exactly this sequence.

**FLIGHT build** (the default, no `APP_BENCH_FIXED_INPUT`):

```
PFOLLOW: app start
PFOLLOW: CPX init OK
PFOLLOW: camera init OK
PFOLLOW: model init OK (champion 14-out, cores=8)
PFOLLOW: buffers ready
PFOLLOW: entering inference loop
```

**BENCH build** (`APP_BENCH_FIXED_INPUT=1`) — **this is a different, shorter
banner, and you will probably be looking at it first**, because the
recommended lab order is bench-then-flight:

```
PFOLLOW: app start
PFOLLOW: CPX init OK
PFOLLOW: model init OK (champion 14-out, cores=8)
PFOLLOW: BENCH fixed-input mode: file=... cores=8 net_verbose=...
```

Bench mode never calls `camera_if_init()`, so **there is no `camera init OK`
line, no `buffers ready`, and no `entering inference loop`.** Their absence in
bench mode is correct and expected — it does **not** mean the camera is broken
or the flash failed. (Source: `src/app_main.c`, the `#if APP_BENCH_FIXED_INPUT`
block at line 358 runs `run_bench_loop()` and never returns.)

**`cores=8` is the line that matters.** That string is emitted only by the
champion-core8 build. If you see `PFOLLOW:` lines but `cores=1`, `cores=2` or
`cores=4`, you flashed an older or differently-configured build. If you see no
`PFOLLOW:` lines at all, the champion app is not running — some previous app is.

Then, roughly every 10 processed frames (with `APP_DEBUG=1`, the default):

```
PFOLLOW: frame=10 cap=..ms pre=..ms infer=..ms total=..ms hz=.. trk=. xb=. x=+0.062 sb=. size=0.341 vis=.. age=..ms drop=0 camerr=0 pkt=0 rcf=0 txdrop=0
```

> Note: `crazyflie_ssd/docs/hardware-flash-debug.md` shows an older version of
> this line (with `conf=`, `scale=`, `raw=[...]`). The format above is what the
> current source actually prints. Trust this one.

### The strongest possible check: bench mode

Flash the **bench** image (§3a) instead. It ignores the camera, runs the network
on the fixed image baked into flash, and compares the result against the golden
tensor bit-for-bit:

```
PFOLLOW: BENCH_TENSOR_I32 iter=1 5247 5523 2781 ... -7277 match=1
PFOLLOW: BENCH iter=1 load=..ms infer=..ms total=..ms period=..ms trk=0 xb=1 sb=1 vis=-2869 pkt=0 mismatches=0 rcf=0 txdrop=0
```

**There are two bench lines, not one, and you want both.** `match=1` is the
per-iteration tensor comparison; `mismatches=0` is the running count. Earlier
drafts of this section showed only the second and
`docs/firmware_integration/HANDOFF.md` (line 543-548) shows only pieces of each,
which made them look like rival claims about one line. They are not — both
strings come straight out of `crazyflie_ssd/src/app_main.c` (lines 210 and 267).
`lab_session_runbook.md`'s S2 row now lists both as well. Record both.

**`mismatches=0` means the quantized model produced byte-identical output on
real GAP8 silicon to what it produced in GVSOC.** The expected vector hard-coded
in `src/app_main.c` —
`5247, 5523, 2781, -659, -948, -2089, 3694, -1952, -8464, -2869, 959, 5626, 1227, -7277`
— is byte-identical to `expected_output` in
`pytorch_ssd_unstable/application/validation/manifest.json`. I checked.

Suggested lab order: **flash bench first**, confirm `mismatches=0`, then flash
flight. That separates "the model is wrong" from "the camera or plumbing is
wrong", which otherwise costs an hour of guessing.

**UNVERIFIED:** no `PFOLLOW:` line has ever been observed on real hardware. The
strings above are read directly out of the current source, not from a device.

---

## 6. If the build breaks in the lab

Prebuilt, hash-checked images are already on disk:

```
~/Downloads/drone/aideck-gap8-examples/_prebuilt_champion/
  champion_flight.img   261e20d8b03f091a2c18b0beccf46b3397a90a00ad3180c924d413a6099aeb8b
  champion_bench.img    34c4b3bae3322dd04e555fe30b9b658f6480d4e006356aa683523af88ec4f929
  SHA256SUMS
  cpx_console.py
```

Both were built from `crazyflie_ssd` at commit `ff876bd`
("Raise the follower's enter bar to p >= 0.75 (raw 4216 -> 5467)", 2026-09-13). The head of
`docs/firmware_integration/champion-core8-integration.bundle` is `fc42eb9`, a docs-only commit
on top of `ff876bd` that builds the same bytes. The previous images, built from `0623a7d`
("Fix round 6: SPI-based re-confirmation, packet v6 tracking bit 1"), were
`c69e71e7…` (flight) and `7fa0e8be…` (bench); they confirm targets at p >= 0.70 and must not be
flashed for the lab.

Flash them directly — skip Docker entirely:

```bash
cd ~/Downloads/drone/aideck-gap8-examples/_prebuilt_champion
shasum -a 256 -c SHA256SUMS     # confirm they are intact
~/Downloads/drone/cfloaderenv/bin/python -m cfloader flash \
  champion_flight.img deck-bcAI:gap8-fw -w radio://0/80/2M/E7E7E7E7E7
```

### 6a. Building with no internet (VERIFIED 2026-09-12)

**This is the most likely thing to bite you.** `make-example` runs
`pip3 install numpy==1.22.3` under `set -e` *before* it compiles anything. With
no working network inside the container that pip call fails and the build dies
having compiled **zero** files. University wifi with a captive portal counts as
"no network". Proven:

```
$ docker run --rm --network none -v "$PWD:/workspace" -w /workspace \
    bitcraze/aideck aideck-gap8-examples/tools/build/make-example \
    ../crazyflie_ssd clean build image
ERROR: Could not find a version that satisfies the requirement numpy==1.22.3
ERROR: No matching distribution found for numpy==1.22.3
EXIT=1                       # and 0 source files compiled
```

**The fix: that numpy pin is not actually needed.** The container already ships
numpy 1.24.3, and the build works fine with it. Run the same steps as
`make-example` but skip the pip line:

```bash
cd ~/Downloads/drone
docker run --rm -v "$PWD:/workspace" -w /workspace bitcraze/aideck bash -c '
  set -e
  cd /workspace/crazyflie_ssd
  export GAPY_OPENOCD_CABLE=interface/ftdi/olimex-arm-usb-tiny-h.cfg
  source /gap_sdk/configs/ai_deck.sh
  make clean build image'
```

Add `APP_BENCH_FIXED_INPUT=1` to the `make` line for the bench build.

This was run on 2026-09-12 with `--network none` (no network at all). It exited
0 and produced a flash image with sha256
`c69e71e76431fa6bec3ea1abd690f3d9440bf3fcd8ca020a1d801795c5a3ef67` —
**byte-identical to the online build.** (That was the `0623a7d` image; the offline path was
not re-run for `ff876bd`, whose online hash is `261e20d8…` above.) So this is a safe substitute, not a
degraded one.

Order of preference in the lab: normal script → this offline command → the
prebuilt images above.

### Build troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Docker starts a huge download | `:latest` tag missing again | `docker tag bitcraze/aideck@sha256:038197df9cb86ccf8e6649e93dd0cf23781830e136288523983768918851633e bitcraze/aideck:latest` |
| `Missing build helper: .../tools/build/make-example` | The examples clone got wiped again | `cd ~/Downloads/drone/aideck-gap8-examples && git fetch origin && git reset --hard origin/master` |
| `Error: no device found` / `unable to open ftdi device` | You ran an `all` or `flash` target | Re-run with `clean build image`. Harmless — nothing was written. |
| `pip3 install numpy==1.22.3` fails | `make-example` needs internet inside the container | Use the offline build in §6a. Confirmed to work and to produce the identical binary. |
| Build is slow (~2m20s) | amd64 image emulated on Apple Silicon | Normal. Not a fault. |

---

## 7. Recovering a deck that stops responding

**Good news first - but this is documentation, not something anyone here
observed: flashing over the radio is not supposed to be able to brick the
deck.** Per Bitcraze's docs, the GAP8 bootloader hashes the application before
jumping to it. If a transfer is
interrupted or the image is corrupt, the hash check fails and the chip stays in
the bootloader instead of running garbage. So:

1. Power-cycle the drone.
2. Flash again (§4).

That is the whole recovery procedure for a failed over-the-air flash. If a
flash dies half-way, just redo it.

**A truly bricked deck** means the bootloader itself was overwritten — which
only happens if someone ran a JTAG `flash` / `all` target (§3b). Recovery then
requires the Olimex ARM-USB-TINY-H on the GAP8 JTAG header (the **left** one
viewed from the top with the camera facing you; pin 1 is marked on the
underside), re-flashing the bootloader.

> **This cannot be done from Sai's Mac.** Docker on macOS cannot pass USB
> devices through to a container, and the whole GAP8 toolchain only exists
> inside that container. Bitcraze's own docs say USB-in-Docker is Linux-only.
> **If a deck gets bricked, it needs MinHyuk's Linux machine (or a Linux VM
> with USB passthrough) plus the JTAG probe.** Worth confirming before the
> session whether either exists, because there is no workaround on the Mac.

---

## 8. Open questions to settle with MinHyuk, ideally before the session

1. **Crazyflie URI(s)** for the drones you'll use. Don't guess in the room.
2. **AI-deck hardware revision.** Over-the-air GAP8 flashing needs the GAP8
   bootloader, which is pre-flashed only on **AI-deck 1.1 Rev D and newer**.
   An older deck must have its bootloader flashed over JTAG first — which,
   per §7, is not possible on the Mac.
3. **Crazyflie STM32 + ESP32 (NINA) firmware versions.** The OTA path runs
   through both. If the STM32 firmware predates deck-memory support, or the
   ESP firmware is stale, `deck-bcAI:gap8-fw` will not be reachable.
4. **Is there a Linux machine with the Olimex probe available?** This is the
   only brick-recovery path, and the only way to flash a pre-Rev-D deck.
5. **Does anyone already have a working AI-deck to compare against?** Knowing
   what a healthy console looks like on their fleet is worth a lot.

---

## 9. Honest status

**Verified by running it here:**

- The examples repo is restored; `tools/build/make-example` exists and executes.
- The GAP8 toolchain works: the upstream `hello_world_gap8` example compiles,
  links, and produces a 49,184-byte flash image.
- **The champion app compiles and links cleanly** into a RISC-V ELF and a
  340,896-byte flash image. Memory fits comfortably: L2 at 18.43% of 512 KB,
  FC_tcdm at 40.28% of 16 KB.
- The project's own `flash_person_follow_aideck.sh` now runs end to end,
  unmodified, and leaves `crazyflie_ssd` git-clean.
- Builds are reproducible — identical sha256 across four separate builds.
- `cfloader` is installed and runs; the exact flash command parses the target
  *syntax* and opens the image, failing only at the missing dongle. The deck
  *name* `bcAI:gap8` is corroborated only by cflib source (§4).
- **An offline build path exists and is verified** (§6a): with `--network none`
  and the numpy pin skipped, the build exits 0 and produces the byte-identical
  image. Conversely, the stock `make-example` **cannot build without internet** —
  it dies at pip before compiling anything.
- The `all`/`flash` JTAG footgun is confirmed from the SDK's own makefiles, not
  just from an error message (§3b).
- The two prebuilt images really are what they claim: `champion_flight.img`
  contains `camera init OK` and no bench string; `champion_bench.img` contains
  `BENCH fixed-input mode` and no `camera init OK`.
- The bench golden vector in the firmware matches the GVSOC manifest exactly.

**Not verified — needs the drone:**

- That anything at all can be written to a real AI-deck.
- That the flashed app boots, that the camera initialises, or that any
  `PFOLLOW:` line ever appears.
- That `mismatches=0` on real silicon. GVSOC agreement does not guarantee it.
- Timing numbers. The ~23 ms `network_run` figure in the Makefile comment is a
  GVSOC estimate, not a measurement from hardware.
- Everything in §7 about recovery. Written from Bitcraze's documentation and
  from reading the source, never exercised.
