# Flash card: put the model on drone 05's chip (Oct 2)

**Only with Sai's OK.** Drone 05 only. Props off; motors are never armed in any step.

This flashes over the radio, so the laptop keeps its internet. Paste each block as it
is. Every command names drone 05's address on purpose: the runbook's examples use the
factory address `E7E7E7E7E7`, which matches neither of our drones.

## 0. Make it impossible to flash the wrong drone

- **Take drone 09's battery out and unplug it from USB.** A drone with no power cannot
  be flashed.
- Put a charged battery in **drone 05**, and plug the Crazyradio into the hub.

```bash
LOG=~/drone_frames/2026-10-02/chip_logs; mkdir -p $LOG
~/Downloads/drone/cfloaderenv/bin/python -c "import cflib.crtp as c; c.init_drivers(); print('05:', c.scan_interfaces(0xE7E7E7E705)); print('09:', c.scan_interfaces(0xE7E7E7E709))"
```

**Expect:**
- `05: [['radio://0/80/2M/E7E7E7E705', ...]]` (the channel may differ from 80; if it
  does, use the URI it prints everywhere below);
- `09: []`.

If 09 shows up, its battery is still in. Stop.

```bash
U=radio://0/80/2M/E7E7E7E705     # change only if the scan printed a different URI
cd ~/Downloads/drone/aideck-gap8-examples/_prebuilt_champion && shasum -a 256 -c SHA256SUMS
cd ~/Downloads/drone/aideck-gap8-examples/_prebuilt_dark_guard && shasum -a 256 -c SHA256SUMS
```

All lines should say `OK`.

## 1. Bench image: is the chip computing the right answer?

```bash
~/Downloads/drone/cfloaderenv/bin/python -m cfloader flash \
  ~/Downloads/drone/aideck-gap8-examples/_prebuilt_champion/champion_bench.img \
  deck-bcAI:gap8-fw -w $U 2>&1 | tee $LOG/01_flash_bench.txt
```

Unplug the battery, plug it back in, then:

```bash
~/Downloads/drone/cfloaderenv/bin/python \
  ~/Downloads/drone/aideck-gap8-examples/_prebuilt_champion/cpx_console.py $U 30 | tee $LOG/02_bench_console.txt
```

**Pass:**
- `model init OK (champion 14-out, cores=8)`;
- `BENCH_TENSOR_I32 ... match=1`;
- `BENCH iter=... mismatches=0`.

That means the real chip computes byte-for-byte what the simulator did. Write down
`infer=` and `period=`.

**If it fails:**
- No `PFOLLOW:` lines: the old app is still running. Re-flash.
- `mismatches>0`: stop and save the log. That's a real finding.

## 2. Flight image with the dark-frame guard

```bash
~/Downloads/drone/cfloaderenv/bin/python -m cfloader flash \
  ~/Downloads/drone/aideck-gap8-examples/_prebuilt_dark_guard/dark_guard_flight.img \
  deck-bcAI:gap8-fw -w $U 2>&1 | tee $LOG/03_flash_flight.txt
```

Power-cycle the drone. Then sit 2 m in front of it, centred:

```bash
~/Downloads/drone/cfloaderenv/bin/python \
  ~/Downloads/drone/aideck-gap8-examples/_prebuilt_champion/cpx_console.py $U 60 | tee $LOG/04_flight_console.txt
```

**Pass:**
- `camera init OK`;
- `frame=` lines with `hz=` around 10-15;
- `img` lines with `mean=` and `dark=0`;
- `exposure frame=10 ...` once.

Then walk out of view and back. `trk` goes 0 → 1 → 0. Stand on the drone's LEFT: `xb`
should be low (0-3). On its RIGHT: high (5-8).

## 3. Five power-ups: exposure seen from inside the chip

Don't touch the drone. Five times: unplug the battery, replug, then run the console for
20 s:

```bash
for i in 1 2 3 4 5; do read "?Replug drone 05's battery, then press Enter ($i/5) "; ~/Downloads/drone/cfloaderenv/bin/python ~/Downloads/drone/aideck-gap8-examples/_prebuilt_champion/cpx_console.py $U 20 | tee $LOG/05_powerup_$i.txt; done
```

## 4. Cover the lens

Use a cap or tape, not a hand shadow. Cover for 10 s or more, during a 30 s console
run:

```bash
~/Downloads/drone/cfloaderenv/bin/python ~/Downloads/drone/aideck-gap8-examples/_prebuilt_champion/cpx_console.py $U 30 | tee $LOG/06_cover_lens.txt
```

**Pass:**
- `dark=` counts up;
- `trk=0`;
- `age=` climbs past 500 ms and then 3000 ms;
- **`trk=1` never appears while covered.**

After you uncover, `trk` returns to 1 only after 3 or more frames.

The covered `mean=` values tell us whether the guard's floor of 12 is right. The tuning
rule is in HANDOFF §5.6 (PR #12).

## Then

Tell me the folder `~/drone_frames/2026-10-02/chip_logs`. I'll write it up, and tune the
floor if needed.

Drone 05's AI-deck now runs the model instead of the WiFi camera. That's fine: it is
the Lighthouse beacon, and for the walking recording its deck gets unplugged anyway.

**To put a camera streamer back later:**

```bash
~/Downloads/drone/cfloaderenv/bin/python -m cfloader flash \
  ~/Downloads/drone/handoff_private/aideck_images/wifi-img-streamer.flash.img \
  deck-bcAI:gap8-fw -w $U
```

That gives a 324×244 streamer, **not** the 162×122 one the deck had. It still works;
the brightness bands need re-measuring.
