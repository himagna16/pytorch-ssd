# Champion firmware integration: handoff for Jade, Koa, Calvin

Repo: `/Users/saimaruvada/Downloads/drone/crazyflie_ssd` (David Liu's wrapper, origin
`github.com/DavidLiu2/crazyflie-ssd`). Branch: **`champion-core8-integration`**, local
only (not pushed), based on `main` @ `4a03846`. Nothing has been flashed. The branch
has been compiled and linked in the `bitcraze/aideck` image; it has never run on silicon.

## 1. What the firmware does (end-to-end map)

1. **Build.** The top-level `Makefile` (GAP SDK `pmsis_rules.mk`, `PMSIS_OS=freertos`,
   `BOARD_NAME=ai_deck`, `io=uart`) compiles `main.c`, `src/*.c`, `lib/cpx/src/*.c`,
   and `generated/src/*.c` except `generated/src/main.c` (DORY's standalone harness).
   Include paths: `.`, `inc`, `generated`, `generated/inc`, `lib/cpx/inc`. The
   **top-level `vars.mk`** lists the readfs files (`FLASH_FILES` from the
   **top-level `hex/`**), which are packed into the flash image. `generated/Makefile` and
   `generated/vars.mk` are DORY's copies and are *not* used by the firmware build.
   Flags: `CORE` (cluster cores, now 8), `APP_DEBUG` (1), `APP_ENABLE_CPX_APP_PACKET_TX`
   (0), `APP_GENERATED_NETWORK_VERBOSE` (0), `APP_ENABLE_LTO` (0), new `APP_BENCH_FIXED_INPUT` (0).
2. **Boot** (`main.c` -> `src/app_main.c:app_main_task`). `pi_bsp_init`; the FC voltage
   is set to 1.0 V; FC and cluster clocks are both **100 MHz** (`app_config.h`
   `APP_SOC_FC_FREQ_HZ`, `APP_SOC_CL_FREQ_HZ`); CPX init (console + app route GAP8 ->
   STM32); **camera frame buffer 79,056 B in L2 first** (`camera_if_alloc_frame`, before
   the arena, so a large arena cannot starve it); Himax init (QVGA 324x244 gray,
   orientation reg 0x0101 = 3, AEG init); network init (`mem_init`: HyperFlash readfs +
   HyperRAM; `network_initialize`: loads 8 weight files to HyperRAM; then the L2 arena,
   capped at `APP_NET_ARENA_MAX_BYTES` = 196,608 B with 131,072 B tried first (the
   champion peaks at 93,760 B), plus a 56 B output buffer). Bench mode: same order
   without Himax init. L2 heap (`__heapl2ram_size`, current flight build, fix round 5): 427,792 B.
3. **Loop** (single thread, no overlap). Async capture -> `pipeline_process_frame`:
   - `preprocess.c`: center square crop (244x244 from 324x244) + resize to 128x128,
     1 channel. Each output pixel is the rounded mean of the 2x2 camera block starting at
     the old nearest-neighbor source pixel (risk 8). Written to the start of the L2 arena
     (the network's input position with `initial_dir=1`, the same as the GVSOC validation main).
   - `net_runner_run` -> `network_run(arena, arena_bytes, out, 0, 1)`: opens the cluster,
     runs 9 layers on `NUM_CORES` cores, copies 56 bytes to `out`, closes the cluster.
   - `follow_output.c` -> `follow_decode()` (team decoder, verbatim) with thresholds
     {enter 4216, exit -998, confirm 3}.
   - `transport_if_send_follow_result` -> CPX app packet (if enabled).
   - The next capture starts only after the pipeline returns, so the frame rate is
     about `1 / (capture + total)`.
4. **Network output.** 14 x int32 LE: `[0..8]` x-bin logits (left -> right), `[9]`
   visibility logit, `[10..13]` size-bucket logits (small/far -> large/near).
   eps_out = 2.00982e-4. The contract is `pytorch_ssd/docs/firmware_contract.md`.
5. **To the Crazyflie.**
   - CPX console (`PFOLLOW:` lines in the cfclient Console tab): startup lines, errors,
     and with `APP_DEBUG=1` one summary line every 10 frames.
   - CPX app packet v6 (binary, 28 B, GAP8 -> STM32, `CPX_F_APP`), sent every processed frame
     (plus a no-target packet on every capture timeout or pipeline failure) when built with
     `APP_ENABLE_CPX_APP_PACKET_TX=1`. The format and the STM32 safety rules are in section 3.

## 2. What the branch changes (commits on `champion-core8-integration`)

1. `generated/`, `hex/`, `vars.mk`: replaced with the champion DORY app
   (`pytorch_ssd_unstable/application`). Hashes match its `validation/manifest.json`
   (network.c `54bacbae…` before patching, pulp_nn_utils.c `6cb90314…`, inputs.hex `e4546224…`).
   The old Aug 27 residual net (ReluQAddition, 41.46M MACs) is gone. The champion is
   9 layers, 15.78M MACs.
2. `generated/src/network.c`: `unsigned int args[4]` -> `args[5]` (DORY writes `args[4]`).
   `#define VERBOSE 1` and the per-run `print_perf` are now gated on
   `APP_GENERATED_NETWORK_VERBOSE` (default 0). VERBOSE costs about 38 ms/inference.
3. `Makefile`: `CORE ?= 8` (1/2/4/8 cores are bit-exact on GVSOC; about 154 -> 23 ms at 100 MHz).
4. **out_mult alias patch: not needed.** All `BNReluConvolution*.c` already alias
   `out_mult = out_mult_in`, `FullyConnected8.c` never uses `out_mult`, and the harness glob
   (`src/Convolution*.c`) matches no champion file.
5. **int64 BN requant patch: present** (`GAP8_INT64_REQUANT_PATCH`,
   `generated/src/pulp_nn_utils.c:35`).
6. FreeRTOS port shims restored from the old `generated/` (the champion was built on
   PULP-OS): `generated/inc/pulp.h` (-> `pmsis.h`), the `eu_evt_maskWaitAndClr` fallback
   in `mchan.h`, the `ARCHI_MCHAN_DEMUX_ADDR`/`ARCHI_CL_EVT_DMA0` fallbacks in
   `dory_dma.c`, and `printf.h` in `mem.c`/`net_utils.c`. Without them the build fails
   (`pulp.h: No such file`).
7. Decode: `src/follow_decode.c` + `inc/follow_decode.h`, copied **byte-identical** from
   `pytorch_ssd/tools/firmware_decode/` (sha256 `33b817a0…` / `437fa5f0…`). `src/follow_output.c`
   is now a thin wrapper (thresholds + state). The old 3-value decode (1/32768 scale) and
   the unused `ssd_postprocess.c` stub are removed. `APP_NET_OUTPUT_BYTES` went from 12 to 56
   (the old 12 would have been overrun by the 56-byte copy in `network_run`).
8. Transport: CPX app packet v6 (section 3; v5 before fix round 6, v4 before fix round 5, v3 before fix round 3). The console summary line now shows `trk xb x sb size vis age hz`.
9. Bench mode `APP_BENCH_FIXED_INPUT=1` (section 5). In-repo summary: `docs/champion_integration.md`.
10. Review fixes (commits `04c068a`, `48b08a7`, `5b1e986` after `ca7c139`): (a) stale-output guard in `net_runner_run`: the output
    buffer is filled with `INT32_MIN` before `network_run`; if any value is still `INT32_MIN`
    afterwards (e.g. `pi_cluster_open` failed and the generated code returned early), the run
    returns -1 instead of re-decoding the previous frame. (b) On a camera capture timeout or a
    pipeline failure the visibility state is reset and a no-target packet is sent. (c) Packet v3:
    byte 19 is the frame age. (d) L2 arena capped at 196,608 B, 131,072 B tried first; the
    selected arena is logged at info level (visible with `APP_DEBUG=0`).
11. Fix round 3 (commits after `5b1e986`, listed in section 4):
    (a) **Frame age and land rule (safety).** Packet v4 carries the age in 20 ms units, so
    it is exact up to 5.08 s, and 255 means saturated. The GAP8 latches saturation until
    the next valid frame, which also guards the ~71.6 min `pi_time_get_us` wrap. The
    STM32 rule now tracks `t_fresh` explicitly (section 3). The old rule was
    `age = frame_age_10ms * 0.01 + (now - t_rx)`, with 10 ms units saturating at 2.55 s.
    During a continuous pipeline failure, no-target packets refresh `t_rx` every capture
    period, so the drone would have hovered forever. During a camera outage it landed only
    by about a 50 ms margin.
    (b) Arena cap is a Makefile variable, `APP_NET_ARENA_MAX_BYTES ?= 196608`, passed as `-D`.
    (c) The untested cluster-open failure path is documented (risk 14).
    (d) Stale L2 numbers and the boot order in this doc are corrected.
    (e) `preprocess.c` now does the 2x2 box average (risk 8), and a host harness
    `tools/preprocess_host_harness.c` was added.
12. Fix round 4 (commit `6dbd8dc` on top of `e8e4b61`, listed in section 4):
    (a) **Stall then recovery (safety, finding 1).** `pipeline.c` resets the visibility state at
    decode time after any stale gap (> 0.4 s since the newest valid frame, no app packet queued
    for > 0.4 s, or a frame that is itself > 0.4 s old). Tracking then needs 3 fresh frames at
    p >= 0.7 again, in camera mode and in bench mode. The STM32 mirror rule 4 is in section 3.
    (b) **Link latency (safety, finding 2).** The age is stamped immediately before the queue
    attempt. App packets use the new non-blocking `cpxTrySendPacket` / `com_try_write` (`lib/cpx`),
    so at most 2 wait on the GAP8 instead of up to 80. A frame older than 0.4 s is sent with
    `tracking = 0`. The remaining link-latency assumption and the STM32 options are in section 3.
    (c) Console summary and bench lines gained `rcf=` (re-confirmation resets) and
    `txdrop=` (dropped app packets).
    (d) Docs: section 5 step 6 now points to the section 3 rules; the pipeline-failure packet
    period is about 60 ms; the risk 3 free-L2 figure is about 218 KB.
13. Fix round 5 (commit on top of `6dbd8dc`, listed in section 4):
    (a) **Held/queued packet delivered late with a fresh-looking age (safety, finding 1).** The
    com task can hold an app packet (and have one queued behind it) for an unbounded time on
    the NINA handshake. Now `lib/cpx/src/com.c` finalizes every app packet after the handshake
    returns and immediately before the SPI transfer: the wait since the queue attempt is added to
    the age byte (rounded up, saturating at 255), `tracking` is forced to 0 if the wait exceeded
    `APP_PACKET_TX_MAX_WAIT_US` (100 ms), and `gap8_tx_ms` is stamped. Only app packets are
    touched (wire length, CPX route/function/version, magic `0xA5`, version 5). The math is in
    `inc/follow_packet.h` (pure C, host-tested: `docs/firmware_integration/safety_sim/test_follow_packet.c` (round-6 version)).
    (b) **Packet v5 (enabler for STM32 option (a), finding 2).** 28 bytes: the v4 layout plus
    uint32 `gap8_tx_ms` at byte 24, the GAP8 ms clock (FreeRTOS ticks at 1 kHz) at that same
    moment. The STM32 estimates the clock offset as the windowed minimum of `t_rx - gap8_tx_ms`
    and treats excess latency above 0.1 s as stale (section 3, rule 0).
    (c) Docs: risk 3 heap figure from the fix-round-5 flight link map; the 1-core liveness limit
    (section 3 and `app_config.h`, which now rejects `CORE=1` camera builds).

14. Fix round 6 (commit on top of `6c4b119`, listed in section 4):
    (a) **NINA stall right after a queue attempt (safety, finding 1).** A NINA/CPX stall of
    about 0.40-0.46 s that starts just after a queue attempt held packet 1 in the com task
    while packet 2 was queued at the start of the stall. The GAP8's queue-attempt gap stayed
    under 0.4 s, but the STM32 received nothing and entered stale hover. The GAP8 hysteresis
    kept `tracking = 1`, so steering resumed on frames at p in [0.45, 0.7). Now `lib/cpx/src/com.c`
    records, in a critical section in the com task, the finalize time and the frame capture
    time of every app packet it hands to the SPI transfer (`com_app_spi_ages`, exposed as
    `transport_if_spi_ages`). `pipeline.c` also resets the visibility state when no app packet
    reached SPI for 0.4 s or the newest frame actually sent over SPI is older than 0.4 s. The
    existing checks stay. Entries older than 3.0 s are latched off (wrap guard).
    (b) **Packet v6: tracking bit 1 (STM32 enabler, finding 2).** Byte 16 is now bit flags:
    bit 0 = confirmed tracking (unchanged meaning), bit 1 = this frame's visibility confidence
    >= the enter threshold (p >= 0.7; the decoder's per-frame test `v[9] >= 4216`). Rule 4 now
    needs 3 consecutive fresh packets with bit 0 AND bit 1 set, so after a stall the GAP8
    cannot see (inside the ESP32), only p >= 0.7 frames count. Version bumped 5 -> 6 so a v5
    parser that tests `tracking != 0` rejects v6 (no STM32 parser exists yet).
    (c) Docs (finding 3): arm following/take-off only after the rule-0 warm-up; a persistent
    latency step > 0.1 s is stale and lands at 3.0 s (fail-safe, by design); com-task
    preemption between the finalize and the SPI transfer shows up as excess latency (rule 0),
    not in the age byte.

## 3. Message format sent to the Crazyflie (CPX app packet v6)

Route `CPX_T_GAP8 -> CPX_T_STM32`, function `CPX_F_APP`, `dataLength = 28`, packed,
little-endian, floats IEEE-754 binary32. Sent once per processed frame, and as a
no-target packet on each capture timeout or pipeline failure, only when built with
`APP_ENABLE_CPX_APP_PACKET_TX=1` (**off by default**, because an STM32 without a
registered app handler has nowhere to deliver it). **v6 (fix round 6)** = the v5 layout with
byte 16 (`tracking`) as bit flags; bit 1 (this frame's p >= 0.7) is new. **v5 (fix round 5)** =
the v4 layout plus uint32 `gap8_tx_ms` at byte 24, and the age runs to the SPI transfer. v4 put
the frame age in **20 ms** units at byte 19. v3 used 10 ms units, which saturated at 2.55 s,
below the 3.0 s land threshold. v2 had byte 19 reserved. Nothing was deployed with v2 to v5,
and no STM32 parser exists yet. The version byte changed so an older parser rejects v6 (a v5
parser that tests `tracking != 0` would otherwise steer on a bit-1-only packet). The struct and
the bit helpers are in `inc/follow_packet.h`.

| off | size | field | meaning |
|---|---|---|---|
| 0 | 1 | magic | `0xA5` |
| 1 | 1 | version | `0x06` (v1: old x/scale/vis raw triple; v2: byte 19 reserved; v3: 10 ms age; v4: 24 B, age to the queue attempt; v5: `tracking` was 0/1) |
| 2 | 2 | payload_len | `24` |
| 4 | 4 | frame_id | uint32 camera frame counter (bench: iteration) |
| 8 | 4 | x_center | float, x-bin center in [-1, 1], left -> right **of the network image**; 0 in no-target packets |
| 12 | 4 | size_center | float, size-bucket center in [0, 1]; 0 in no-target packets |
| 16 | 1 | tracking | **bit flags**; test bits, never compare the byte with 1; bits 2-7 reserved (0). **Bit 0** = confirmed target (3 consecutive frames at p >= 0.7, kept until p < 0.45); clear = hover (ignore x/size). **Bit 1** = this frame's visibility confidence >= the enter threshold (p >= 0.7; raw `v[9] >= 4216`, the decoder's own per-frame test); used by rule 4. Whole byte 0 in no-target packets, if the frame was older than 0.4 s at the queue attempt, or if the packet waited more than about 100 ms before its SPI transfer |
| 17 | 1 | x_bin | 0..8; `0xFF` = no network result (no-target packet) |
| 18 | 1 | size_bucket | 0..3; `0xFF` = no network result |
| 19 | 1 | frame_age_20ms | age of the newest frame with a valid network output, capture completion -> **the packet's SPI transfer** (stamped at the queue attempt, then grown in `com.c` by any wait before the transfer), 20 ms units rounded up. `0..254` = exact (up to 5.08 s). **`255` = saturated**: older than 5.08 s, or no valid frame since GAP8 boot. Once saturated it stays 255 until the next valid frame |
| 20 | 4 | vis_raw | int32 raw visibility logit (tuning/logging); `INT32_MIN` = no network result |
| 24 | 4 | gap8_tx_ms | uint32 GAP8 millisecond clock (FreeRTOS ticks, 1 kHz, wraps every 49.7 days) at the SPI transfer, the same moment the age refers to. For rule 0 |

STM32 side (your code): register an app handler (crazyflie-firmware
`cpxRegisterAppMessageHandler`), check `magic == 0xA5 && version == 6 && dataLength == 28`,
`memcpy` into the same packed struct, and then e.g. `yaw_rate = K * x_center * sign`
(sign set by the mirror check in step 5.5).

**STM32-side safety rules (required).** These match the simulator follower,
`pytorch_ssd/tools/crazysim_macos/follow_person.py` with `--stale-hover 0.5 --stale-land 3.0`.

Keep `t_fresh`, the STM32-clock time of the newest valid frame. Do **not** compute
the age from the newest packet's arrival time, e.g. `frame_age * unit + (now - t_rx)`:
during a pipeline failure the GAP8 sends a no-target packet every capture +
pipeline period (about 60 ms: a ~30 ms capture, then preprocess/inference until the
failure), and each one would refresh `t_rx`.

**Rule 0, link latency (v5, required).** Per packet, sample `s = t_rx_ms - gap8_tx_ms` in uint32
arithmetic (compare samples only through signed 32-bit differences; both clocks wrap).
- Clock offset `off` = the **minimum of `s` over a sliding window of about 10 s** (e.g. a ring of
  ten 1 s minima). The fastest deliveries set it, so the unknown offset and the healthy latency
  cancel; crystal drift (<= ~200 ppm, 2 ms per 10 s) is negligible against 0.1 s. A minimum is
  robust to any number of late packets (they only raise `s`).
- Excess latency `e = s - off >= 0`. **`e > 0.1 s` => the packet is stale**: it does not refresh
  `t_fresh`, restarts the rule 4 count, and never steers. A packet with age 255 is acted on
  (land) whatever `e` is.
- Warm-up: until the window spans at least 2 s of packets, treat every packet as stale.
  **Following and take-off may only arm after the warm-up** (2 s of packets since boot or since
  a window reset).
- **A persistent latency step > 0.1 s is treated as stale and lands after 3.0 s (fail-safe, by
  design).** Every packet then has `e > 0.1 s` until the 10 s window forgets the old minimum,
  so `t_fresh` stops moving: hover at 0.5 s, land (latched) at 3.0 s. Steps <= 0.1 s are absorbed.
- **Com-task preemption** between the GAP8's finalize (age and `gap8_tx_ms` stamp) and the SPI
  transfer is not in the age byte. It shows up as excess latency `e`, so rule 0 covers it; the
  age byte does not.
- GAP8 reboot (its clock restarts): `s` jumps, so all packets look late (fail-safe) until the
  window forgets the old minimum. Reset the window when `frame_id` goes backwards or `s` jumps by
  more than 10 s; the warm-up then applies again.
- Residual: a latency that stays elevated by <= 0.1 s for a whole window is absorbed into `off`.

On each accepted packet, arriving at `t_rx`:
- `frame_age_20ms == 255`: set `t_fresh = NONE`. **Land immediately** if airborne, and never arm on it.
- `e > 0.1 s`: stale (rule 0); `t_fresh` unchanged.
- otherwise: `t_fresh = t_rx - e - frame_age_20ms * 0.020`.

Every control step (`t_fresh = NONE`, including before the first packet since boot, counts as infinitely old):
1. `now - t_fresh > 3.0` -> **land** (latched; do not re-arm following without an operator action).
2. `now - t_fresh > 0.5` -> **hover**: zero velocity and yaw rate, drop any pending command.
3. `tracking` bit 0 clear -> hover (target not confirmed or lost; `x_center`/`size_center` are not valid).
4. **Re-confirmation after a stale hover (required, fix rounds 4 and 6).** After any control step in
   rule 1 or 2 (including `t_fresh = NONE` and before the first packet since boot), keep
   hovering until **3 consecutive fresh** packets arrive with `tracking` **bit 0 AND bit 1** set,
   `frame_age_20ms * 0.020 <= 0.5` and `e <= 0.1 s` (rule 0). Any other packet (either bit clear,
   older, 255, stale by rule 0) restarts the count. Bit 1 makes the count use only p >= 0.7
   frames: after a stall the GAP8 cannot see (inside the ESP32), the GAP8 hysteresis still reports
   bit 0 on frames at p in [0.45, 0.7), and without bit 1 those would complete the count. This mirrors the reference follower ("after any stale-hover episode,
   re-confirm with 3 fresh frames") and backs up the GAP8's own re-confirmation (below).
5. otherwise steer on `x_center` (yaw) and `size_center` (approach).

**Why the land deadline always holds.**
- `t_fresh` changes only when a packet arrives.
- For every non-saturated packet, `t_rx - age` is no later than the last valid frame's
  capture time plus that packet's link latency `L` (GAP8 SPI transfer -> STM32 arrival),
  because the GAP8 rounds the age up. With rule 0, `t_rx - e - age` leaves only the healthy
  floor latency `L_min` (absorbed in `off`), and packets with `e > 0.1 s` are ignored.
- So `now - t_fresh > 3.0` fires 3.0 s after the last valid frame, plus at most `L` (of the
  last delivered packet) and one control step. That holds with or without further packets:
  - packet silence (GAP8 hang, cluster-open crash, CPX down);
  - a continuous no-target stream (pipeline failure);
  - no-target packets every 0.5 s (camera outage);
  - any mix.
- The age cannot saturate before 5.08 s. A compile-time `#error` in `app_config.h`
  keeps the maximum more than 1 s above the 3.0 s threshold, so saturation never
  hides the deadline. A saturated packet only lands earlier.
- Host simulation (an earlier simulator, superseded by `docs/firmware_integration/safety_sim/safety_sim_review6.py`, 300 randomized runs per pattern,
  0-5 ms CPX delay, 10 ms control step), time from the last valid frame to land:

  | pattern | v4 rule | old v3 rule |
  |---|---|---|
  | pipeline failure every frame | 2.99-3.01 s | never lands (hover forever) |
  | camera outage | 3.00-3.01 s | 3.00-3.01 s |
  | silence | 3.00 s | 3.01 s |
  | mixed lossy | 2.99-3.01 s | up to 4.67 s |
  | failure then silence | 3.00 s | 3.01 s |

  Hover began at 0.50-0.51 s in every case.

The GAP8 sends a **no-target** packet (`tracking = 0`, `x_bin = size_bucket = 0xFF`,
`vis_raw = INT32_MIN`) on every camera capture timeout (0.5 s) and every pipeline
failure. It also resets its visibility state, so tracking must be re-confirmed
(3 frames at p >= 0.7) after any gap. A no-target packet's age still refers to the last
good frame, so `t_fresh` does not move through a gap.

The age is measured on the GAP8 from capture completion to the packet's queue attempt
(fix round 4: stamped immediately before it, no longer at decode). It includes preprocess +
inference (about 25-30 ms at 8 cores if silicon matches GVSOC) plus any wait before
inference. It does not include the link latency `L` from the queue attempt to the STM32,
which is the only way `t_fresh` can be later than the true frame time.

**GAP8 stale-gap re-confirmation (fix round 4, finding 1).** Before fix round 4, a GAP8 stall
followed by recovery fired no gap event, e.g. a blocked console send or a slow `network_run`.
The visibility state stayed `tracking = 1`, and steering resumed after one fresh frame at
p >= 0.45. Now `pipeline.c` checks at decode time (after `network_run`) and resets the visibility
state, so tracking needs 3 fresh frames at p >= 0.7 again, when:
- there is no valid frame yet, or the age is saturated (latched);
- the newest valid frame is older than `APP_FOLLOW_RECONFIRM_GAP_US`. That is 0.4 s,
  100 ms below the STM32 hover threshold, to cover age rounding (<= 20 ms), one control step,
  and link latency;
- in TX builds, no app packet was queued for that long;
- in TX builds (fix round 6), no app packet reached the SPI transfer for that long, or the newest
  frame whose packet reached it is older than that (recorded by the com task at the finalize,
  `com_app_spi_ages`); this catches a NINA stall that starts just after a queue attempt; or
- the frame being decoded is itself older than 0.4 s. That frame is sent with `tracking = 0`.

The console line counts these frames as `rcf=`. At 8 cores normal periods (~60-70 ms) never
trigger it.

**1-core liveness limit (fix round 5).** The check compares against the *previous* valid frame, so
in steady state it spans about one frame period plus one inference: about 0.1 s at 8 cores, but
about 0.35 s at 1 core (period ~190 ms + inference ~154 ms), close to the 0.4 s threshold. Jitter
can then reset the state on most frames, and a 1-core camera build may never confirm a target
(fail-safe hover, but no following). `app_config.h` rejects `CORE=1` camera builds at compile time
(override: `#define APP_ALLOW_1CORE_FOLLOW` in `app_config.h`, only after measuring the period);
1-core **bench** builds, used in step 5.3/5.4, still build. The 8-core default is fine.

**Link latency: what the GAP8 bounds and what remains (fix rounds 4 and 5).**
- App packets never block. `cpxTrySendPacket` queues a packet only if the CPX TX queue
  is empty (`APP_PACKET_TX_MAX_QUEUED = 0`), otherwise drops it (`txdrop=` on the console
  line). Dropping is safe: `t_fresh` only ages without packets.
- `lib/cpx` `TXQ_SIZE` is **80**. With the old `cpxSendPacketBlocking`, a NINA/SPI stall could
  queue up to 80 packets with frozen ages and deliver them late in a burst. Now at most 2 app
  packets wait on the GAP8: 1 queued, plus 1 held by the SPI com task.
- **Fix round 5:** the held packet and the one queued behind it no longer keep a frozen age.
  After the NINA handshake returns and immediately before the SPI transfer, `com.c` adds the
  wait since the queue attempt to the age byte (rounded up, saturating), forces `tracking = 0`
  if the wait exceeded 100 ms (`APP_PACKET_TX_MAX_WAIT_US`; conservative by one age unit, so it
  can fire from 80 ms), and stamps `gap8_tx_ms`. The per-packet reference rides in the packet's
  own `gap8_tx_ms` field until then (inc/follow_packet.h), so queued packets cannot swap
  references. Console packets are never touched.
- A packet whose frame is older than 0.4 s at the queue attempt carries `tracking = 0`.
- After a TX gap longer than 0.4 s, the GAP8 re-requires 3 fresh confirming frames. Since fix
  round 6 it is measured at the queue attempt and at the SPI transfer (what reached the bus).
- Com-task preemption between the finalize and the SPI transfer is not in the age byte; rule 0
  sees it as excess latency.

What the GAP8 cannot see: the ESP32 router queues and the UART to the STM32. Rule 0 bounds
them from `gap8_tx_ms`: a packet more than 0.1 s later than the window's fastest delivery is
stale. A steered frame is then at most 0.5 s + `L_min` + 0.1 s old, and a late packet followed by
a GAP8 hang lands no later than 3.0 s + `L_min` + 0.1 s (+ one control step) after the last valid
frame. `L_min` (healthy latency, a few ms) is unmeasured; measure it on the bench.

Without rule 0 (an STM32 that ignores `gap8_tx_ms`), the partial fallback is: treat an arrival
gap > 0.5 s as a stale-hover episode, and do not let the first 2 packets after it refresh
`t_fresh`. That covers the GAP8 side only; the ESP32 queue depth is unverified.

Full text in `docs/champion_integration.md`, "Link latency".

Host simulation for these fixes: an earlier simulator, superseded by `docs/firmware_integration/safety_sim/safety_sim_review6.py`, log
`sim_out.log`. It is a copy of the independent `fw_safety_sim/safety_sim.py`, which is
unchanged, extended with the TX admission rule, the link model and rule 4. Results are in
section 4.

## 4. Build

The official helper `flash_person_follow_aideck.sh` calls
`aideck-gap8-examples/tools/build/make-example`, which **does not exist** locally
(`/Users/saimaruvada/Downloads/drone/aideck-gap8-examples` contains only
`examples/other/dory_examples`, the GVSOC harness output; it is not a git clone). The
script exits with "Missing build helper". Upstream, the file lives in
`github.com/bitcraze/aideck-gap8-examples` under `tools/build/` (it sources the SDK config
and runs `make` in the given example dir). It is **not pinned anywhere in this project**,
so it was not downloaded. Two fixes, pick one:

- **A (no download):** build directly in the image. This command is **equivalent to the
  verified build, which ran from an in-container copy** of the repo (repo mounted read-only
  at `/src`, copied to `/tmp/<variant>` inside the container, then
  `source /gap_sdk/configs/ai_deck.sh && make clean build image [flags]`; script:
  (local build logs, not in the repo)). The command below builds in place
  and writes `BUILD/` into your checkout; it was not itself run. That it matches what the
  upstream `make-example` wrapper does is **unverified** until the team pins
  `bitcraze/aideck-gap8-examples` at a recorded commit and diffs the wrapper:
  ```bash
  cd /Users/saimaruvada/Downloads/drone/crazyflie_ssd
  git checkout champion-core8-integration
  docker run --rm --name aideck_fw_build_$USER --platform linux/amd64 \
    -v "$PWD:/module" -w /module \
    bitcraze/aideck@sha256:038197df9cb86ccf8e6649e93dd0cf23781830e136288523983768918851633e \
    bash -lc 'source /gap_sdk/configs/ai_deck.sh && make clean build image'
  # bench variant: append APP_BENCH_FIXED_INPUT=1 after "image"
  # with packets:  append APP_ENABLE_CPX_APP_PACKET_TX=1
  ```
  Output: `BUILD/GAP8_V2/GCC_RISCV_FREERTOS/target.board.devices.flash.img`.
  (Use the digest: the local image has no `latest` tag, so plain `bitcraze/aideck` would pull.)
- **B:** clone `bitcraze/aideck-gap8-examples` at a commit the team pins (record the SHA
  in the README), so `aideck-gap8-examples/tools/build/make-example` exists. Then
  `bash ./flash_person_follow_aideck.sh [URI] [make vars]` works unchanged.

Dry-run results before the review fixes (container `aideck_fw_dryrun`, same image digest the GVSOC harness used;
the review-fix rebuild is summarized below the table):

| variant | make flags | result | L2 static | text / data / bss | flash image |
|---|---|---|---|---|---|
| flight | (defaults: CORE=8, VERBOSE off, APP_DEBUG=1) | compiles + links, exit 0 | 95,336 B / 512 KB (18.18%) | 83,048 / 3,696 / 15,200 | 340,896 B (readfs 78,752 B) |
| bench | `APP_BENCH_FIXED_INPUT=1` | compiles + links, exit 0 | 88,864 B / 512 KB (16.95%) | 76,852 / 3,668 / 14,948 | 340,896 B |

Both variants: L1_sram 16 B static (DORY takes a 36,700 B L1 buffer per layer at run time),
FC_tcdm 6,600 B / 16 KB. L2 heap from the link map: `__heapl2ram_size` = 428,952 B.
Logs: (local build logs, not in the repo) (build_*.log, size_*.txt, main_*.map).
The first build attempt failed with `pulp.h: No such file or directory`, which is fixed by change 6 above.
Rebuild after the review fixes (containers `aideck_fw2_fix2`/`aideck_fw2_fix3`, same digest,
repo mounted read-only and copied inside the container; tree = commit `5b1e986`; logs in
(local build logs, not in the repo) and `build_out2_tx/`):

| variant | make flags | result | L2 static | text / data / bss | flash image |
|---|---|---|---|---|---|
| flight | (defaults) | compiles + links, exit 0 | 95,776 B (18.27%) | 83,480 / 3,696 / 15,208 | 340,896 B |
| bench | `APP_BENCH_FIXED_INPUT=1` | compiles + links, exit 0 | 89,232 B (17.02%) | 77,200 / 3,668 / 14,964 | 340,896 B |
| flight + TX | `APP_ENABLE_CPX_APP_PACKET_TX=1` (compiles the v3/no-target sender) | compiles + links, exit 0 | 95,984 B (18.31%) | 83,684 / 3,696 / 15,208 | 340,896 B |

L2 heap (`__heapl2ram_size`) at `5b1e986`: flight 428,504 B, bench 434,032 B. (The 428,952 B
in the first dry-run table above is from before the review fixes; it is historical.) With the 79,056 B frame and a
131,072 B arena, about 218 KB of heap stays free in flight (before FreeRTOS/CPX/driver allocations).
Note: the Makefile builds with `-w`, so warnings are suppressed; "compiles" means no errors.
Head at that rebuild: `5b1e986` (7 commits on top of `4a03846`: the 4 integration commits `e44e846..ca7c139`
plus 3 review-fix commits `04c068a` (stale-output guard + arena cap), `48b08a7` (gap reset,
no-target packet, packet v3 frame age), `5b1e986` (docs)).

**Fix round 3 commits** (on top of `5b1e986`): `44093b3` (preprocess 2x2 box), `910c1aa`
(Makefile `APP_NET_ARENA_MAX_BYTES`), `9f5f07d` (packet v4 + `t_fresh` STM32 rule, safety),
`75872a8` (cluster-open failure path documented), then `e8e4b61` (docs + host harness) =
current branch head.

**Rebuild after fix round 3** (container `aideck_fw3_fix1`, same digest, repo mounted read-only
and copied inside the container per variant; tree = commit `75872a8` code, i.e. the fix-round-3 code
commits; logs in (local build logs, not in the repo)):

| variant | make flags | result | L2 static | text / data / bss | L2 heap | flash image |
|---|---|---|---|---|---|---|
| flight | (defaults) | compiles + links, exit 0 | 95,904 B (18.29%) | 83,608 / 3,696 / 15,208 | 428,376 B | 340,896 B |
| bench | `APP_BENCH_FIXED_INPUT=1` | compiles + links, exit 0 | 89,256 B (17.02%) | 77,220 / 3,668 / 14,964 | 435,032 B | 340,896 B |
| flight + TX | `APP_ENABLE_CPX_APP_PACKET_TX=1` (v4 + no-target sender) | compiles + links, exit 0 | 96,112 B (18.33%) | 83,812 / 3,696 / 15,208 | 428,168 B | 340,896 B |
| flight, arena cap 412000 | `APP_NET_ARENA_MAX_BYTES=412000` | compiles + links, exit 0 | 95,920 B (18.30%) | 83,620 / 3,696 / 15,208 | 428,360 B | 340,896 B |

The make variable reaches the compiler: an `APP_CFLAGS` print in the same image shows
`-DAPP_NET_ARENA_MAX_BYTES=196608` by default and `=412000` with the override
(`build_out3/make_cflags_check.log`). With the 79,056 B frame and a 131,072 B arena, about
218 KB of flight L2 heap stays free (before FreeRTOS/CPX/driver allocations).
Host checks: `src/preprocess.c` (via `tools/preprocess_host_harness.c`) is byte-identical to the
resize study's box2 output on all 1000 frames; an earlier simulator, superseded by `docs/firmware_integration/safety_sim/safety_sim_review6.py` (section 3 table).

**Rebuild after fix round 4** (container `aideck_fw4_build1`, same digest, repo mounted read-only
and copied inside the container per variant; tree = `e8e4b61` + the fix-round-4 working tree,
saved as (local build logs, not in the repo)uncommitted_at_build.diff`, then committed unchanged as `6dbd8dc`; logs
in (local build logs, not in the repo)):

| variant | make flags | result | L2 static | text / data / bss | L2 heap | flash image |
|---|---|---|---|---|---|---|
| flight | (defaults) | compiles + links, exit 0 | 96,312 B (18.37%) | 84,004 / 3,696 / 15,216 | 427,968 B | 340,896 B |
| bench | `APP_BENCH_FIXED_INPUT=1` | compiles + links, exit 0 | 89,584 B (17.09%) | 77,556 / 3,668 / 14,964 | 434,696 B | 340,896 B |
| flight + TX | `APP_ENABLE_CPX_APP_PACKET_TX=1` | compiles + links, exit 0 | 96,872 B (18.48%) | 84,544 / 3,696 / 15,232 | 427,416 B | 340,896 B |

`cpxTrySendPacket`, `com_try_write` and `transport_if_tx_gap_us` are in the flight + TX link
map. With the 79,056 B frame and a 131,072 B arena, 427,968 - 79,056 - 131,072 = **217,840 B
(about 218 KB)** of flight L2 heap stays free (before FreeRTOS/CPX/driver allocations).

**Rebuild after fix round 5** (container `aideck_fw5_build2`, same digest, a snapshot of the
fix-round-5 working tree mounted read-only and copied inside the container per variant; the
snapshot's code equals the fix-round-5 commit (`uncommitted_at_build.diff`, `code_sha256.txt`);
logs in (local build logs, not in the repo)):

| variant | make flags | result | L2 static | text / data / bss | L2 heap | flash image |
|---|---|---|---|---|---|---|
| flight | (defaults) | compiles + links, exit 0 | 96,488 B (18.40%) | 84,180 / 3,696 / 15,216 | 427,792 B | 340,896 B |
| bench | `APP_BENCH_FIXED_INPUT=1` | compiles + links, exit 0 | 89,760 B (17.12%) | 77,732 / 3,668 / 14,964 | 434,520 B | 340,896 B |
| flight + TX | `APP_ENABLE_CPX_APP_PACKET_TX=1` (v5 sender) | compiles + links, exit 0 | 97,088 B (18.52%) | 84,760 / 3,696 / 15,232 | 427,200 B | 340,896 B |

`com_finalize_app_packet` is static and inlined into `com_task`, so it has no map symbol; flight text
grew 176 B over fix round 4 (84,004 B). `cpxTrySendPacket`, `com_try_write`, `transport_if_send_follow_result` are in the
flight + TX link map. With the 79,056 B frame and a 131,072 B arena, 427,792 - 79,056 - 131,072 =
**217,664 B (about 218 KB)** of flight L2 heap stays free (before FreeRTOS/CPX/driver
allocations). Host test of the age/tracking/`gap8_tx_ms` finalization:
`docs/firmware_integration/safety_sim/test_follow_packet.c` (round-6 version) (3,000,000 random cases, 0 failures).

**Rebuild after fix round 6** (container `aideck_fw6_build2`, same digest, a snapshot of the
fix-round-6 working tree mounted read-only and copied inside the container per variant; the
snapshot's code equals the fix-round-6 commit (`uncommitted_at_build.diff`, `code_sha256.txt`);
logs in (local build logs, not in the repo)):

| variant | make flags | result | L2 static | text / data / bss | L2 heap | flash image |
|---|---|---|---|---|---|---|
| flight | (defaults) | compiles + links, exit 0 | 96,640 B (18.43%) | 84,312 / 3,696 / 15,232 | 427,648 B | 340,896 B |
| bench | `APP_BENCH_FIXED_INPUT=1` | compiles + links, exit 0 | 89,912 B (17.15%) | 77,860 / 3,668 / 14,980 | 434,376 B | 340,896 B |
| flight + TX | `APP_ENABLE_CPX_APP_PACKET_TX=1` (v6 sender) | compiles + links, exit 0 | 97,376 B (18.57%) | 85,048 / 3,696 / 15,240 | 426,904 B | 340,896 B |

`com_app_spi_ages`, `transport_if_spi_ages`, `follow_output_frame_visible` and `g_app_spi` are in
the link maps. Flight L2 heap left after the 79,056 B frame and a 131,072 B arena:
427,648 - 79,056 - 131,072 = **217,520 B (about 218 KB)**.

**Fix round 6 checks** (host). `docs/firmware_integration/safety_sim/test_follow_packet.c`: 3,000,000 random cases,
0 failures (fix-round-5 finalize properties with every tracking-byte value, the v6 bit helpers,
exact recovery of the frame capture time `com.c` records). `docs/firmware_integration/safety_sim/safety_sim_review6.py` (final independent simulator)
(log `fix6_check.log`), a copy of the review-5 sim whose GAP8 model adds the SPI-frame
re-confirmation check and the v6 byte (tracking byte through the fix-round-6 C finalize), and
whose "v6" STM32 counts only bit 0 + bit 1 packets in rule 4; 200 runs per row:

| pattern | fix 5 + v5 rules | fix 6 + v5 rules | fix 6 + v6 rules |
|---|---|---|---|
| NINA stall 0.40 / 0.42 / 0.44 / 0.46 s right after a queue attempt | 5 / 64 / 62 / 69 P2 | 0 | 0 |
| ESP32-internal stall 0.6 / 1.0 s | - | 6 / 8 P2 | 0 |
| Monte Carlo mixes incl. NINA + ESP32 outages (500 runs each) | up to 9 P2 | - | 0; land <= 3.009 s after the last valid frame |
| 1.5 s stall, 2.0 s NINA / ESP32 outage (liveness) | - | - | resumes 200/200 after 3 fresh frames |

Fix-round-4 host simulation (an earlier simulator, superseded by `docs/firmware_integration/safety_sim/safety_sim_review6.py`, log `sim_out.log`;
200 randomized runs per row, plus 500 Monte Carlo mixes). Rows compare branch head `e8e4b61`
under the documented v4 rules, fix round 4 under the v4 rules, and fix round 4 with STM32 rule 4.
Column meanings:
- violations: steering resumed after a stale hover without 3 truly fresh frames at p >= 0.7
  (P2), or steering on a frame truly older than 0.5 s (P3);
- land: time from the last valid frame to landing.

| pattern | head, v4 | fix 4, v4 | fix 4, v4 + rule 4 |
|---|---|---|---|
| camera outage / inference fails every frame / GAP8 hang / single failure | 0; land 3.00 s | 0; land 3.00 s | 0; land 3.00 s |
| GAP8 main-loop stall 1.5 s or 0.45 s, then recovery | 200/200 runs resume after 1 fresh frame | 0 | 0 |
| one `network_run` of 0.45 s or 0.8 s | every run violates | 0 | 0 |
| NINA/ESP32 link down 2.0 s, GAP8 running | 472 (steer on a frame up to 2.03 s old) | 854 (up to 2.03 s old; the <= 2 late GAP8 packets) | 0 (max steered age 0.49 s) |
| link down 0.3 s | 0 | 0 | 0 |
| link down 1.0 s / 2.9 s, then GAP8 hang | P3 violations; land 3.84-3.90 / 5.74-5.80 s | same | 0 violations; land 3.84-3.90 / 5.74-5.80 s |
| Monte Carlo mixes (stalls, slow inference, failures, low p) | 780 P2 | 0 | 0 |

The last-but-one row is the remaining link-latency assumption from section 3: a late packet
followed by a hang lands 3.0 s + the link stall after the last valid frame, and only an STM32
latency bound (option a) removes that. The sim does not model ESP32-side buffering.



## 5. Flash and bench test (motors OFF, props off)

1. Props off, Crazyflie on the bench, AI-deck mounted, battery or USB power. Confirm
   the Crazyflie firmware has CPX enabled (standard for AI-deck builds).
2. Build the **bench** image (section 4 with `APP_BENCH_FIXED_INPUT=1`) and flash over radio:
   `python -m cfloader flash BUILD/GAP8_V2/GCC_RISCV_FREERTOS/target.board.devices.flash.img deck-bcAI:gap8-fw -w radio://0/80/2M/E7E7E7E7E7`
   (or over JTAG). Power-cycle the deck.
3. Open cfclient -> Console. Expect `PFOLLOW: app start`, `CPX init OK`,
   `model init OK (champion 14-out, cores=8)`, `BENCH fixed-input mode: file=inputs.hex cores=8 net_verbose=0`, then:
   ```
   PFOLLOW: BENCH_TENSOR_I32 iter=1 5247 5523 2781 -659 -948 -2089 3694 -1952 -8464 -2869 959 5626 1227 -7277 match=1
   PFOLLOW: BENCH iter=1 load=..ms infer=..ms total=..ms period=..ms trk=0 xb=1 sb=1 vis=-2869 pkt=0 mismatches=0
   ```
   **Pass criteria:** the printed tensor equals the GVSOC tensor
   `[5247, 5523, 2781, -659, -948, -2089, 3694, -1952, -8464, -2869, 959, 5626, 1227, -7277]`
   exactly (`match=1`) on every logged iteration, `mismatches=0` after 1000 or more iterations, and
   the decode reads `xb=1 sb=1 vis=-2869 trk=0` (x = -0.667, size = 0.375, not visible; this image
   is a real person the model scores at p = 0.36). The input is `hex/inputs.hex`, the staged
   smoke image of `pytorch_ssd_unstable/logs/plain_follow_prod_qat_final`
   (`input_sets/rep16/01_visible_000000121031.jpg`).
   If `match=0`: rebuild with `CORE=1` and then with `APP_GENERATED_NETWORK_VERBOSE=1`
   (per-layer checksums are printed with printf to the GAP8 UART, or to the terminal with a JTAG `io=host` build, not to the CPX console). The
   first layer whose checksum fails is where silicon diverges from GVSOC. Send that log to Sai.
4. **Measure (bench):** `infer` = `network_run` wall time (includes cluster open/close;
   expect about 23-30 ms at 8 cores/100 MHz if silicon matches GVSOC), `total`, and
   `period` (1/period = bench Hz). Record at CORE=8 and at CORE=1 (about 154 ms expected).
   Optional: with `APP_ENABLE_CPX_APP_PACKET_TX=1` and an STM32 handler, confirm the
   STM32 receives 28-byte v6 packets with `x_center=-0.6667 size_center=0.375 tracking=0` (both bits clear: p = 0.36),
   `frame_age_20ms` about 2, i.e. 21-40 ms (the bench measures age from the start of each
   iteration), and `gap8_tx_ms` rising by about the bench period per packet. Log
   `t_rx_ms - gap8_tx_ms` over 5 min or more: its spread above the minimum is the link jitter
   that rule 0 must tolerate (expect a few ms; it must stay well below 0.1 s). If `gap8_tx_ms`
   instead jumps by about 1000x the period (it then holds the GAP8 us-clock age reference), `com.c`
   did not recognize the app packet and the age is not being finalized: stop and report. **The bench does not exercise `preprocess.c`**: it copies the already
   pre-processed 128x128 `inputs.hex` into the arena. Step 5 covers the camera path.
5. **Live camera (still motors off).** Build the normal image (no bench flag), flash, and watch
   the summary lines every 10 frames:
   `frame= cap= pre= infer= total= hz= trk= xb= x= sb= size= vis= age= drop= camerr= pkt=`.
   - **Camera type first:** determine whether the deck's Himax is gray or color (Bayer).
     The contract's capture-protocol stream check tells you. If it is color, stop: the
     wrapper samples raw Bayer as gray and needs 2x2 averaging before crop/resize (not on this branch).
   - **Mirror check:** hold the drone still. A person stands clearly on the drone's LEFT
     (from the drone's point of view), about 2 m away. Record `xb`, then repeat on the RIGHT.
     Expected with correct orientation: left gives `xb` 0-3 (x < 0), right gives `xb` 5-8 (x > 0).
     If reversed, the image is mirrored relative to training (orientation reg 0x0101 = 3
     flips both axes). Fix the sign in the STM32 controller or change the orientation
     register, and write the choice down. Also check up/down is not flipped: a person
     upside-down in the image scores poorly (low `vis`, `trk` rarely 1).
   - **Preprocess check (live camera).** The bench skips `preprocess.c`, so check it here.
     - Radio only: record `pre=` from the summary line. The 2x2 box does 4 loads per output
       pixel. I estimate a few ms at 100 MHz, but that is not measured. Also check that a
       person centered at 2 m gives `xb` 4 +/- 1 and `trk=1`.
     - Byte-exact check (JTAG): build with `APP_DEBUG=1` and note the boot lines
       `camera frame buffer @ 0x...` and `selected L2 arena @ 0x...`.
       1. Set a breakpoint on `net_runner_run`. The next capture starts only after the
          pipeline returns, so the frame buffer still holds the source frame.
       2. Dump 79,056 B from the frame address to `frame.u8`, and 16,384 B from the arena
          address to `arena.u8`.
       3. On the host, run
          `cc -O2 -I. -Iinc -o preprocess_host tools/preprocess_host_harness.c src/preprocess.c && ./preprocess_host < frame.u8 | cmp - arena.u8`.
          It must print nothing.
       4. Do this for 3 or more frames, including one with a person.
     - Optional: keep 50 or more dumped frames. Run them through the training resize and
       `preprocess.c` on the host to repeat the resize study on real sensor noise (risk 8).
   - Walk-in/walk-out: `trk` goes 0 -> 1 about 3 frames after you enter frame and
     0 when you leave. Near/far: `sb` rises as you approach.
   - **Measure (live):** `cap`, `pre`, `infer`, `total`, `hz` (processed frames/s between
     summary lines), `drop`, `camerr` over 5 min or more. Expected Hz about 1/(cap + total).
6. Only after 3-5 pass: STM32 controller with motors, props on, tethered/low altitude,
   with a kill switch. The STM32 must implement the **section 3 `t_fresh` rules**, not a plain
   packet timeout:
   - land when `now - t_fresh > 3.0 s`, latched;
   - hover when `now - t_fresh > 0.5 s`;
   - hover on `tracking == 0`;
   - after any stale hover, require 3 consecutive fresh packets with `tracking` bit 0 AND bit 1
     set (rule 4) before steering;
   - rule 0: packets with excess latency `e > 0.1 s` are stale; arm following/take-off only after
     the 2 s warm-up.

   Before props-on, bench-test each one by unplugging the deck, holding the camera covered,
   and stalling the link.

## 6. Open risks (none verified on silicon)

1. **PULP-OS vs FreeRTOS.** The champion's bit-exact GVSOC result was built on **PULP-OS**
   (`GCC_RISCV_PULPOS`) with DORY's standalone main. The firmware is **FreeRTOS** + CPX +
   camera. The compute kernels are the same, but the cluster/DMA/RAM driver paths differ, and
   the old README reports earlier GVSOC FreeRTOS runs hanging at `CACHE_ALLOC_BEGIN`. Step 5.3
   is the first real test. A FreeRTOS GVSOC run of the bench image was not attempted
   (CPX needs the NINA/SPI link and may block in simulation).
2. **Cluster DMA on silicon.** The `ARCHI_MCHAN_DEMUX_ADDR 0x00204400` / `ARCHI_CL_EVT_DMA0 8`
   fallbacks are David's shims, unverified on hardware, and apply only if the SDK headers lack
   them. `-DALWAYS_BLOCK_DMA_TRANSFERS` is set. HyperRAM/HyperFlash timing on silicon differs from GVSOC.
3. **L2 budget.** The L2 heap is 427,792 B (current flight link map, fix round 5). The old boot order took the arena (412,000 B) before
   the camera frame (79,056 B), and 491,056 B does not fit, so live mode would have died at
   `camera_if_alloc_frame`. **Fixed on the branch:** the frame is reserved first, and the arena
   is capped at `APP_NET_ARENA_MAX_BYTES` (default 196,608 B), tried smallest first: 131,072 B,
   then 196,608 B. Expected arena: 131,072 B, leaving about 218 KB of L2 heap free
   (427,792 - 79,056 - 131,072 = 217,664 B with the fix-round-5 flight link map, before
   FreeRTOS/CPX/driver allocations). On first boot
   read `selected L2 arena @ ... (N bytes, cap 196608)` (info level, printed even with
   `APP_DEBUG=0`) and, with APP_DEBUG=1, `max contiguous L2 block after ...`. If no candidate
   fits, the log says `L2 arena allocation failed for all candidates <= 196608 bytes`. Raise the
   cap with the Makefile variable to re-enable the larger sizes:
   `make clean build image APP_NET_ARENA_MAX_BYTES=412000` (plain decimal, no `u`). Do **not**
   use `APP_CFLAGS+=-D...` on the make command line: a command-line assignment replaces the
   Makefile's `APP_CFLAGS` (include paths, `-DNUM_CORES`, ...) and the build breaks. This
   variant links: fix round 3 built `APP_NET_ARENA_MAX_BYTES=412000` in the image (exit 0, section 4), and the compile flags showed `-DAPP_NET_ARENA_MAX_BYTES=412000`.
4. **Arena size.** `network_run` gets the first candidate that fits (131,072 B expected). The
   champion's peak per-layer need is 93,760 B (layer 1: in 65,536 + out 24,576 + w 3,648),
   so any candidate is enough. GVSOC ran with 412,000 B, so the bench is the **same input path,
   different arena size**: buffer addresses move relative to GVSOC. The bench `match=1` check
   covers this.
5. **Cluster open/close every inference.** `network_run` opens and closes the cluster each call
   (tens of microseconds to ms). This is included in `infer`. A later optimization is to keep it open.
6. **Power/thermal.** 8 cores at 100 MHz, 1.0 V FC, draw more current than 1 core. Watch the
   Crazyflie battery sag and GAP8 temperature on long bench runs, and re-check flight time.
7. **Color camera.** See 5.5. It is a hard blocker if the deck is color.
8. **Resize vs training (fixed on the branch; confirm on real frames).** The old firmware resize was
   nearest-neighbor, while training used an antialiased bilinear resize.
   - Study (`docs/eval_results/2026-09-11-resize/RESULT.md` (team repo)):
     1000 val2017 frames emulated as 324x244 camera frames, using the champion integer ONNX.
   - Nearest-neighbor **lowered F1 at the 0.7 enter threshold by 0.050 [0.020, 0.079]** and flipped
     **13% of visibility decisions** (at 0.5). It mostly costs recall.
   - The branch's `preprocess.c` now outputs the rounded mean of the 2x2 camera block starting at
     the old nearest source pixel. That is **within noise of the training resize:
     +0.004 [-0.016, +0.024]**, and its pixel disagreement is about a 1-pixel camera shift.
   - The firmware file's host build is byte-identical to the study's Python port on all 1000 frames.
   - Caveats: the camera was idealized (no HM01B0 noise, optics or exposure), and the bench does not
     run `preprocess.c`. Do the live-camera preprocess check in step 5.5.
9. **Visibility threshold choice.** The branch uses the contract's {4216, -998, 3} (p >= 0.70
   enter, < 0.45 exit). The release summary's deployment sweep chose p = 0.55 (raw 999) as its
   best single threshold. The team should decide. It is a one-line change in `app_config.h`.
10. **x sign convention.** Unverified until the mirror check (5.5).
11. **CPX app packets are off by default.** With TX on, app packets no longer block (fix round 4),
    and a packet delayed on the NINA handshake carries that delay in its age (fix round 5).
    `cpxTrySendPacket` drops a packet when the CPX TX queue is not empty. Watch `txdrop=`: it
    should stay near 0 on a healthy link. A steady rise means the link or the console is
    saturating it. Console lines still use the blocking send, so a long NINA stall can still
    stall the main loop once the 80-deep queue fills with console lines. The stale-gap
    re-confirmation handles the recovery. ESP32/UART latency is bounded only if the STM32
    implements rule 0 (section 3).
12. **Console bandwidth.** Summary lines every 10 frames go over CPX -> STM32 -> radio. Build
    with `APP_DEBUG=0` for flight (startup/errors still print).
13. **Decoder tests were not re-run** in this dry run (`run_tests.sh` writes into `pytorch_ssd`).
    The copy is byte-identical, and a host check decoded the smoke tensor and David's tensor as expected.
14. **Cluster-open failure path (untested).** In the generated `network_run_async()`, a
    `pi_cluster_open` failure does a bare `return;` from a function that returns a struct.
    - The caller's token is then uninitialized, and `network_run_wait()` calls
      `pi_cluster_close()` on it.
    - That may hang or crash the GAP8 before the wrapper's poison check (`net_runner_run`) runs.
      The poison check only covers the case where the call returns.
    - The wrapper can't guard this safely without editing generated code, which the branch avoids.
    - The path has never been exercised, and it fails safe only because packets stop. The
      STM32 must land when packets go silent. The `t_fresh` rule (section 3) does this 3.0 s
      after the last valid frame with no further packet, so it is a required part of the
      STM32 code, not an option.
