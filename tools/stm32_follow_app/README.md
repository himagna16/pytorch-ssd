# STM32 follow controller (flight-controller side, part 1)

A portable C99 module that turns the AI-deck (GAP8) **packet v6** stream into flight
commands for the Crazyflie's STM32, with the safety rules 0-4 from
`docs/firmware_integration/HANDOFF.md` section 3. It has no dependencies, no malloc
and no OS calls; the caller injects time. Part 2 (an STM32 app in crazyflie-firmware,
flown in CrazySim) wraps it; see [app/README.md](app/README.md).

Nothing here has flown. The module is tested on the host only: C unit tests plus the
independent review6 safety simulator driving the compiled C through ctypes.

| file | what |
|---|---|
| `follow_controller.h/.c` | the controller: parse/validate, rule 0 clock-offset window, rules 1-4, control law |
| `tests/test_follow_controller.c` | C unit tests (30313 checks): parse, validation, layout vs the GAP8 header, wrap, each rule at its boundary, the rule 0 latency floor, rule 4 duplicates, control law |
| `tests/app_host_test.c`, `tests/app_stubs/` | the Crazyflie app's state machine (`app/src/follow_app.c`) on the host against stub firmware headers: enable edge, `armMinZ`, priority relaxed on every exit from DONE (6810 checks) |
| `tests/safety_sim_review6_c.py` | copy of `docs/firmware_integration/safety_sim/safety_sim_review6.py` plus an STM32 variant that calls the C code (`c6`/`c6w`) |
| `tests/ctl_shim.c`, `tests/fp_shim.c` | ctypes shims: the controller, and the GAP8's `inc/follow_packet.h` (the simulator's `libfp`) |
| `tests/vendor/` | `follow_packet.h` copied verbatim from branch `champion-core8-integration` (commit 0623a7d) + the constants it needs from `app_config.h` |
| `tests/run_sim_all.sh`, `tests/summarize_results.py`, `tests/diag_rule0_phase.py` | full simulator run, summary/regression check, rule-0 bucket-phase diagnostic |
| `tests/results/` | output of the full run (`SUMMARY.txt` first) |

## Build and test

```sh
cd tools/stm32_follow_app
make              # cc -std=c99 -Wall -Wextra -Werror -pedantic ...: unit tests, app host test, tests/build/*.so
make sim-quick    # checks + every named timeline (40 runs) + one Monte Carlo mix (100 runs), ~10 s
make sim-full     # what tests/results/ holds: 200 runs per timeline, 500 per Monte Carlo mix,
                  # plus the same with forced clock wraps; ~1 min on 3+ cores, then prints SUMMARY
```

`summarize_results.py` exits 1 if the C controller has a P1/P2/P3 violation where the Python
v6 rule has none, or if the Python v6 numbers stop matching the committed review6 logs.
Needs `cc` and `python3` (standard library only).

## API

```c
follow_config_t cfg;  follow_ctl_default_config(&cfg);    /* HANDOFF defaults, yaw_sign = -1 */
follow_ctl_t ctl;     follow_ctl_init(&ctl, &cfg);         /* also the operator reset after LAND */
follow_ctl_on_packet(&ctl, data, len, t_rx_us, &info);     /* every CPX app packet -> OK or a reject reason */
follow_ctl_arm(&ctl, now_us);                              /* take-off gate -> FOLLOW_ARM_OK or why not */
follow_ctl_step(&ctl, now_us, &out);                       /* every 10 ms -> mode, yaw_rate_dps, vx_mps, target_height_m */
```

- **Time**: a `uint32_t` microsecond clock that may wrap (on the STM32, `(uint32_t)usecTimestamp()`).
  All arithmetic is modular with signed 32-bit differences, valid for spans under 35.8 min; a
  `t_fresh` older than `land_us` is dropped so it can never wrap into looking fresh.
- **Packet checks** (`follow_ctl_parse`): length 28, magic `0xA5`, version 6, payload_len 24, tracking
  bits 2-7 clear, and when bit 0 is set, `x_center` in [-1, 1] and `size_center` in [0, 1] (NaN/inf
  rejected). Fields are decoded byte by byte, little-endian, so the module does not depend on struct
  packing. A rejected packet changes nothing except restarting the rule 4 count.
- **Tracking byte**: only bits are tested. Bit 0 = confirmed (rule 3), bit 1 = this frame's p >= 0.7 (rule 4).
- **Modes**: `WAIT_WARMUP` (not armed: stay on the ground), `HOVER`, `FOLLOW`, `LAND` (latched until
  `follow_ctl_init`). `out.reason` says which rule decided (`hover_stale`, `hover_reconfirm`, ...).
  `target_height_m` is 0.8 in HOVER/FOLLOW and 0 in WAIT_WARMUP/LAND.

## The rules as implemented

Per packet (arriving at `t_rx`):
- **Rule 0.** `s = t_rx_us - gap8_tx_ms * 1000` (uint32; `gap8_tx_ms * 1000 mod 2^32` stays
  continuous across the GAP8's 49.7-day ms wrap, so only differences matter). Offset = minimum of `s`
  over a ring of ten 1 s bucket minima (current packet included); `e = s - offset`. `e > 0.1 s` means
  the packet is stale: it does not refresh `t_fresh`, restarts the rule 4 count, and a step whose newest
  packet is stale never steers. Warm-up: every packet is stale until the window has spanned 2 s of
  packets, and `follow_ctl_arm` refuses before that. Window reset (then warm-up and rule 4 again) when
  `frame_id` goes backwards or `s` jumps by more than 10 s.
- **Rule 0 latency floor** (safety review 7; stricter than HANDOFF's rule and the Python model).
  `floor` = the lowest `s` since the last clock reset, allowed to rise by `drift_ppm` (200) of the
  time since that sample. A packet with `s - floor > 0.1 s` is stale too (`info.rise_stale`), and
  the take-off gate refuses with `FOLLOW_ARM_ERR_LATENCY_RISE` while the newest packet is stale only
  that way. Why: a latency step that starts while the drone waits on the ground is absorbed by the
  10 s window, and without the floor the gate armed on frames ~1 s late (review harness: +1 s step,
  after ground silences of 0-30 s). The floor survives silences (the window restarts after one longer
  than 10 s; the floor does not) and restarts only on a clock discontinuity (`frame_id` backwards,
  `s` jumping > 10 s, arrival time backwards). It also catches two steps of <= 0.1 s each that add
  up to more. Residuals: a link that is already slow when the GAP8 or STM32 boots sets the floor
  itself (bench-check `L_min`), and a step X is absorbed after (X - 0.1 s) / 200 ppm of unbroken
  slowness (75 min for +1 s).
- Age 255: `t_fresh = NONE` whatever `e` is (the next step lands if airborne).
- Otherwise, if not stale: `t_fresh = t_rx - e - frame_age_20ms * 20 ms`.

Per control step, after arming:
1. `now - t_fresh > 3.0 s` or `t_fresh = NONE` -> **LAND** (latched).
2. `> 0.5 s` -> **HOVER** (zero velocity and yaw rate).
3. newest packet bit 0 clear -> HOVER. Newest packet stale by rule 0 -> HOVER.
4. After any step in rule 1 or 2 (and from boot), HOVER until **3 consecutive** packets arrive with
   bit 0 AND bit 1, age <= 0.5 s, fresh by rule 0, and each with a `frame_id` newer than the last
   counted one. A copy of a counted packet (link retransmit or replay) neither counts nor restarts
   the count (`info.duplicate`); any other packet (including a rejected one) restarts it. A replay of
   an *older* packet looks like a GAP8 reboot to rule 0 (window and floor restart, warm-up).
5. Otherwise **FOLLOW**, with the control law of `tools/crazysim_macos/follow_person.py`:
   `yaw = 0 if |x| < 0.08 else clamp(yaw_sign * 60 * x, ±40 deg/s)`,
   `vx = clamp(0.8 * (0.625 - size), ±0.3 m/s) if |x| < 0.5 else 0`, height 0.8 m.

Take-off gate (`follow_ctl_arm`): the warm-up must be complete, LAND not latched, and the newest
packet not stale through the latency floor (`FOLLOW_ARM_ERR_LATENCY_RISE`). Note that this gate
covers the case after the 10 s window has absorbed a latency step; during the first ~10 s of a step
the packets are already stale through excess latency itself, so the fresh-packet gate refuses. With the
default `arm_require_fresh = 1`, it also needs a valid frame at most 0.5 s old and a newest packet
that is not late. With `0`, it also refuses on an age-255 newest packet: otherwise this is the Python
rule model's take-off, used by the simulator to diff every run.

`now` passed to `follow_ctl_step` should be read after any packet it follows (the app reads the clock
under its mutex). A step whose `now` is up to `hover_us` *earlier* than a processed packet's `t_rx`
sees age 0; before safety review 7 it saw a wrapped age and latched LAND.

### Yaw sign convention

`yaw_rate_dps` uses the **firmware-internal** convention of `setpoint_t.attitudeRate.yaw`: positive =
counter-clockwise seen from above (the direction `stateEstimate.yaw` increases). `x_center > 0` means
the person is right of the image center, so the drone must turn clockwise, which is a negative rate.
Hence `yaw_sign = -1` (config, default).

Host paths flip this sign on the way in: the CRTP generic-commander decoders
(`crtp_commander_generic.c`) set `attitudeRate.yaw = -values->yawrate`, and cflib's `commander.py`
sends `-yawrate` to legacy-protocol firmware (<= 8). So the `--yaw-sign -1` that
`follow_person.py` measured through cflib in CrazySim does not prove the internal sign. An STM32 app
that writes `attitudeRate.yaw` directly bypasses both flips. **Verified in CrazySim in part 2**: with `yaw_sign = -1` the app turned toward a person on
the right (details in `app/README.md`). It must also re-check the
camera mirror (HANDOFF step 5.5) on the real deck, since `x_center` is left-to-right *of the network image*.

## Safety simulator results (tests/results/SUMMARY.txt)

Each simulation runs the review6 GAP8 "fix6" model and link once. It then runs three STM32 models on
the **same** packet deliveries: the documented Python "v6" rule, `c6` (the C controller, default
take-off gate) and `c6w` (the C controller, `arm_require_fresh = 0`). The STM32 clock is the
simulator's (random offset, +-200 ppm drift), in microseconds and wrapping at 2^32 us.

- **Named timelines** (22 × 200 runs) and **Monte Carlo** (5 mixes × 500 runs) with random clocks,
  plus the same with forced clock wraps (the STM32 us, GAP8 ms and GAP8 us clocks all wrap mid-run;
  22 × 200 and 5 × 200 runs):
  **P1, P2 and P3 hold with 0 violations for both C variants in every row**, including the
  `orig+nina_outages+esp_outages` mix where the v4/v5 rules fail. The C land times match the Python
  v6 rule's (for example 2.992-3.002 s after the last valid frame in the camera-outage timeline, and
  at most 3.009 s in every Monte Carlo mix). Maximum true age of a steered frame: 0.497 s.
- **Ground timelines** (`groundstep`, 7 × 200 runs, new in safety review 7): the link gets 1 s
  slower at 5 s while the drone waits on the ground (after a ground silence of 0, 8, 9.9, 12 or 30 s
  in g0-g4; two +0.08 s steps 11 s apart in g5) and takes off at 25-45 s. The documented Python v6
  rule arms and **steers on frames up to 1.095 s old: P3 in all 200 runs of g0-g4**; in g5 it steers
  on frames up to 0.255 s old (160 ms of absorbed latency, inside P3's 0.5 s bound). **The C
  controller (both gates) never arms in any of these runs.** Control (g6, healthy link, take-off at
  25 s): all three models arm and follow, 0 violations.
- `checks`: the simulator's C cross-checks pass (300000 finalize + 300000 byte/frame-ref cases,
  0 failures) against the vendored `follow_packet.h`.
- The Python v6 numbers in this copy reproduce every v6 row of the committed
  `safety_sim/logs/timelines.log` and `mc0-4.log` exactly (checked by `summarize_results.py`).

### Differences between the C controller and the Python rule model

Step-by-step mode diff, Python v6 vs `c6w`, over all 38.2 M compared control steps (338 differ):

1. **One-step shifts (10 ms), 317 steps.** The Python model computes `t_fresh` in true
   time from millisecond-floored clocks. The C model works in microseconds on the drifting STM32
   clock. The two `t_fresh` values differ by under ~1 ms, which sometimes moves a threshold
   crossing to the neighboring 10 ms step (land-time difference: at most ±10 ms).
2. **Threshold quantization of rule 0: 5 runs, 21 steps in total, all conservative.** The Python
   model floors both clocks to whole ms before computing `e`, so a packet with a true `e` of
   100.3-100.8 ms (every case seen) counts as `e = 100 ms` (fresh). The C model sees `e > 100000 us` (stale) and hovers
   where Python steered: MC esp_outages (5 steps), x2e (5 random-clock + 10 forced-wrap), x2f (1).
   Every rule-0 flag mismatch in those runs was within 2 ms of the threshold.
3. **Rule-0 bucket phase: timeline x2h only, no mode difference.** Both keep a 9-10 s history, but the
   Python model buckets by true time and the C model by its own clock's 1 s grid. So the moment the
   window forgets a pre-latency-step minimum differs by less than 1 s, in either direction. In x2h
   (+0.3 s latency held 15 s) that flips about 1500 stale flags, all after the drone has landed. With
   the STM32 clock aligned to true time the flags agree on every packet, and `e` differs by less than
   1 ms (`tests/diag_rule0_phase.py`, `results/diag_rule0_phase.txt`). Elsewhere `e` agrees within 2.4 ms.
4. **Take-off gate (by design).** The Python model flies at a fixed 3.0 s, even inside the rule-0
   warm-up (and then lands at once on `t_fresh = NONE`). The C controller never arms before the warm-up
   (a HANDOFF requirement). By default it also waits for a fresh frame: `c6` took off later than 3.0 s
   in 197-269 of 500 runs per Monte Carlo mix (failure segments start at 2.0 s). Those runs are
   excluded from the `c6` step diff, and their airborne part is still checked for P1-P3. `c6w` differs
   from Python only when the warm-up was not complete at 3.0 s (0-43 runs per mix).
5. **Stricter window resets.** The C model also resets the rule-0 window when arrival time goes
   backwards or packets stop for longer than the 10 s window. Airborne, a silence that long has
   already latched LAND, so this only delays arming on the ground. It never happened in the simulator.
6. **Rejected packets** (bad length/magic/version/payload_len, reserved bits, non-finite x/size) restart the
   rule 4 count and change nothing else. The Python model never produces them (0 in all runs).
7. The rule 4 count is also restarted by stale steps before arming. The Python model does not evaluate
   steps before 3.0 s. No effect was observed, since warm-up packets never count anyway.
8. **Latency floor (safety review 7).** Stricter than the Python model (see "The rules"). In every
   pre-existing timeline and Monte Carlo row the numbers are unchanged (same violations (none), land
   times, mode and rule-0 diffs as before the fix). Packets stale only through the floor occur in
   x2h alone (about 95 per run, all after the drone has landed) and in the ground timelines, where
   they are what keeps the C controller from arming.
9. **Rule 4 counts distinct frames (safety review 7).** The simulator never delivers a packet twice
   (0 duplicates in all runs), so this changes nothing there.
10. **Small negative frame ages (safety review 7)** count as 0 instead of NONE (see the API notes);
    the simulator's steps never precede a packet they follow, so no difference there.

## Using it in the STM32 app (part 2)

Part 2 is in [`app/`](app/README.md): a Crazyflie out-of-tree app that feeds v6 packets from CPX
(real AI deck) or the CRTP app channel (simulator) into this controller, runs it at 100 Hz, and
flies through the commander. It is compiled into CrazySim's SITL firmware (image
`crazysim-mac:follow-app`, built by `sim/build_image.sh`) and flown there against a host GAP8
emulator (`tools/crazysim_macos/gap8_emulator.py`). `app/README.md` has the parameters, logs,
the verified yaw sign, the simulator results, and the steps to build it for a real Crazyflie
(not tested on hardware). The GAP8 must be built with `APP_ENABLE_CPX_APP_PACKET_TX=1`, and the
healthy link latency `L_min` still has to be measured on the bench.
