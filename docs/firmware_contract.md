# Firmware contract — the 14-value follow output

> **Status (Sep 10):** write tests against synthetic vectors and David's known-good tensor until our releases pass the new semantic gates.
>
> **Status (Sep 13):** the QAT champion is the shipped model. The confirmation bar is
> **enter p >= 0.75 on 3 consecutive frames, exit p < 0.45**, which for the champion is
> **`{5467, -998, 3}`** in raw output units (it was `{4216, -998, 3}` at the old 0.70 bar).
> Read the change note below before flashing anything: this was decided on one simulated
> pet scene and has not run on hardware.

For the frontend/firmware team (Jade, Koa, Calvin). This specifies exactly
what the GAP8 network hands you and how to decode it into flight commands.
Source of truth for decode semantics: `utils/follow_task.py` on the
`successor-release` branch (`xbin9_size_bucket4` head) — if this document
and that file ever disagree, the file wins; tell Sai.

## What arrives

Each inference produces **14 int32 values** (the network's final tensor,
in the quantized output domain):

| index | meaning |
|---|---|
| 0–8 | x-position bin logits — 9 uniform bins over [-1, +1] (left → right) |
| 9 | visibility logit |
| 10–13 | size bucket logits — 4 uniform buckets over [0, 1] (small/far → large/near) |

Worked example, from David's validated app (the known-good reference; our own
Aug 28 golden tensor came from a network that ignores its input and must not be
used in tests):
`[4632, 13262, 4633, -2422, -3479, -5390, 2962, -1854, -11170, 5303, -7980, 3540, 4466, -43]`
x argmax = index 1 (left of center), visibility = 5303 (positive logit, so
visible), size argmax = index 12, bucket 2. Decoded command: "person visible,
left of center, mid distance."

## Decode rules

1. **x position**: `x_bin = argmax(v[0..8])`. Bin center in [-1, 1] is
   `center = -1.0 + (2*x_bin + 1) / 9.0`. Steering derives from the center
   (e.g. yaw_rate = K * center); verify the left/right sign convention once
   on hardware before trusting it.
2. **size**: `size_bucket = argmax(v[10..13])`, center `(bucket + 0.5) / 4`.
   Use for forward-speed / hold-distance policy.
3. **visibility**: compare `v[9]` against an integer threshold constant —
   see scaling below. Never treat visibility as a probability on-device;
   it is a raw logit.

Argmax is scale-invariant, so 1 and 2 need no calibration constants.

## Visibility threshold + hysteresis (required)

The raw values are `logit / eps_out` where `eps_out` is the network's
output quantization step. Each release records it in
`quant_eval/summary.json`, at `quant_fidelity.qd_to_id_operator_report.rows`,
in the row whose `module_name` is `output_head` (field `eps_out`, source
`get_output_eps(eps_in)`). It is **not** 1/32768: the export pipeline assumed
that value for decoding, which is wrong for our networks by about 6.5x
(found Sep 10). Values from our export stage, which the fixed re-release
reproduces byte for byte:

| model | eps_out | thresholds {enter, exit, confirm} | bar |
|---|---|---|---|
| **QAT champion — the shipped model** | 2.009823510888964e-4 | **{5467, -998, 3}** | enter p >= 0.75, exit p < 0.45; adopted 2026-09-13 |
| QAT champion, superseded bar | 2.009823510888964e-4 | {4216, -998, 3} | enter p >= 0.70, the bar until 2026-09-13; do not ship |
| confuser model — not chosen, historical | 2.11792e-4 | {4001, -947, 3} | enter p >= 0.70; never re-derived at 0.75 because the model was not selected |

Derivation of the shipped row, using the rule below (the one
`tools/firmware_decode/raw_thresholds.py` and `follow_raw_thresh()` implement):

- enter: `ln(0.75 / 0.25) = ln 3 = 1.0986122887`; `/ eps_out = 5466.2127`; `ceil` = **5467**.
  Check: `sigmoid(5466 * eps_out) = 0.749992 < 0.75` and `sigmoid(5467 * eps_out) = 0.750030 >= 0.75`.
- exit: `ln(0.45 / 0.55) = -0.2006706955`; `/ eps_out = -998.4493`; `ceil` = **-998** (unchanged).
- confirm: 3 consecutive counting frames (unchanged).
- The superseded bar reproduces exactly: `ln(0.7 / 0.3) / eps_out = 4215.78`, `ceil` = 4216.

`tools/firmware_decode/raw_thresholds.py --eps-out 2.009823510888964e-4` prints the
shipped row by default; add `--enter 0.7` to reproduce the superseded one. Use these
only with an app from a release that passes `export/check_semantic_release_gates.py`.
Regenerate them with `raw_thresholds.py --eps-out <eps>` for any new model.

A probability threshold p maps to:

`RAW_THRESH(p) = ceil( ln(p / (1-p)) / eps_out )`

Use `ceil`, not `round`: then `v >= RAW_THRESH(p)` is exactly
`sigmoid(v * eps_out) >= p` for integer `v`.

~10% of frames sit near the decision boundary, so a single threshold will
flicker. Use the follower's confirmation rule: declare VISIBLE only after
`v[9] >= RAW_THRESH(0.75)` on 3 consecutive frames; declare LOST when
`v[9] < RAW_THRESH(0.45)`. `RAW_THRESH` needs the final layer's `eps_out`
from a release that passes the semantic gates. The Aug 28 and Aug 31
releases fail them; the fixed re-release is being validated.

### Change note, 2026-09-13: the enter bar moved from 0.70 to 0.75

**What changed.** Enter `p >= 0.70` became `p >= 0.75`; for the champion that is
raw `4216` -> `5467`. The exit bar (`p < 0.45`, raw `-998`) and the 3-frame rule did
not change. Decision record: `DECISIONS.md` (2026-09-13). Evidence:
`docs/eval_results/2026-09-13-champion-threshold/README.md`.

**Why.** A 96-flight closed-loop sweep in CrazySim (1 model x 4 latch rules x 6 cells
x 4 matched repeats) showed the champion at 0.70 failing the pet-chasing gate on every
repeat (worst horizontal drift 1.369 m against a 0.5 m limit). At 0.75 it passes on
every repeat (worst 0.376 m) with no measurable recall cost on either person cell
(tracked-while-in-view 0.991 on `A.static`, 0.992 on `B.moving`, first latch still
0.31 s). 0.80 also passes the pet gate but drops `A.static` tracking to 0.828 and once
took 7.0 s to acquire a standing person. Keeping 0.70 and asking for 4 consecutive
frames instead of 3 still fails the gate (worst 0.586 m). The threshold is the knob
that works; the frame count is not.

**What this evidence is not.** Be honest about it in the lab:

- **Nothing has run on hardware.** Every frame was rendered by the MuJoCo/himax model
  and the network ran under onnxruntime on a laptop, not on a GAP8. No Crazyflie has
  flown at either bar.
- **One simulated pet scene.** The pet result is `s03_pets_only`, one fixed layout,
  4 repeats. It is not a claim about pets in general; the network's per-frame
  false-alarm rate on pets and mannequins is unchanged by this. At 0.75 the drone still
  latches onto the dog (median 1.5 episodes per flight, 3.5% of the flight); the gate
  passes because the resulting motion is small, not because the false positives
  stopped. The training fix (hard-negative fine-tune) remains the real fix.
- **The exit threshold was not swept.** `--vis-exit` stayed at 0.45 in all 96 flights;
  `-998` is carried over, not re-chosen.
- **Only four latch rules were flown** (0.70/3, 0.75/3, 0.80/3, 0.70/4). 0.75 is the
  best of four points, not an optimum, and its 0.376 m margin is the worst of 4 repeats,
  a weak estimate of the true worst case.
- The sweep changed the host follower's `--vis-enter`; the firmware constant was not
  exercised by it. This document is where the two are tied together.

**Where the bar lives.** All of these must agree, or the simulator and the aircraft
confirm targets at different bars:

| copy | must read |
|---|---|
| this document | `{5467, -998, 3}` / p >= 0.75 |
| `tools/firmware_decode/follow_decode.c` `follow_vis_cfg_default()`, `raw_thresholds.py --enter`, `gen_vectors.py ENTER`, and `test_follow_decode.c` (pins the champion's `{5467, -998, 3}`) | 0.75; moved in this change, tests re-run |
| `tools/stm32_follow_app/` (bit-1 comments; the STM32 sees the bit, never the bar) and its safety simulator's `ENTER` (`tests/safety_sim_review6_c.py`, `FOLLOW_SIM_ENTER` overrides) | 0.75; moved in this change |
| host follower `tools/crazysim_macos/follow_person.py --vis-enter` default | 0.75 |
| `tools/crazysim_macos/gap8_emulator.py` `VIS_ENTER_RAW` and `tools/crazysim_macos/perception_backends.py` `VIS_ENTER_RAW` | 5467 |
| firmware `app_config.h` `APP_FOLLOW_VIS_ENTER_RAW`, and its `src/follow_decode.c` / `inc/follow_decode.h` (verbatim copies of `tools/firmware_decode/`) and the `p >= 0.7` comments in `inc/follow_packet.h`, `src/transport_if.c`, `docs/champion_integration.md` | 5467 / 0.75; re-copy the decoder from `tools/firmware_decode/` |
| `docs/firmware_integration/HANDOFF.md` | 5467 / 0.75 |

Only the first three rows were changed and verified by the workstream that wrote this
note; the rest are moved by the other workstreams of the same PR and by a commit on the
firmware branch. Before the lab, `grep -rn 4216` across both repositories must find
only historical references such as this table, and the GAP8 emulator's self-test
(which asserts the decoder's default equals its own constants) must pass.

## Reference decode (C, dependency-free, tested)

The tested implementation lives in `tools/firmware_decode/`
(`follow_decode.h`, `follow_decode.c`). Its tests check it against the
project's Python decode on 2,000 random and boundary vectors and 200
visibility sequences, and against the simulator follower's confirmation
rule. Run `tools/firmware_decode/run_tests.sh`. Use it rather than copying
code from this page. The core looks like this:

```c
/* thresholds from tools/firmware_decode/raw_thresholds.py --eps-out <eps>;
 * for the champion (eps_out 2.009823510888964e-4) that is: */
static const follow_vis_cfg_t FOLLOW_VIS_CFG = { 5467, -998, 3 };  /* enter p >= 0.75, exit p < 0.45 */
static follow_vis_state_t vis_state;   /* follow_vis_reset() at boot */

follow_cmd_t cmd;
follow_decode(out /* 14 int32 */, &FOLLOW_VIS_CFG, &vis_state, &cmd);
if (cmd.tracking) { /* steer on cmd.x_center, approach on cmd.size_center */ }
else              { /* hover */ }
```

## Integration notes

- The historical `crazyflie-ssd` wrapper decodes the OLD 3-value head —
  its `ssd_postprocess.c` must be replaced with the logic above.
- **Check which camera the AI-deck has before the first camera-in-the-loop
  run (added Sep 10).** Some AI-decks carry a color Himax sensor, whose raw
  frames are a Bayer color mosaic. Bitcraze's own viewer treats raw frames
  that way. The wrapper's `camera_if.c` does no color conversion, and
  `preprocess.c` samples the raw frame as if it were gray, so on a color
  deck the network would see a checkerboard it never trained on. If the
  deck is color, average each 2x2 cell to one gray pixel before the crop
  and resize, the same conversion `cpx_grab.py --bayer` uses for recorded
  frames. The capture protocol's stream check tells you which camera you
  have.
- `preprocess.c` resizes by nearest neighbor while training used bilinear
  resizing. Measure the effect on recorded frames before first flight.
- Test the controller against mocked 14-value tensors (motors off) before
  any camera-in-the-loop run — the worked example above plus hand-built
  edge cases (all-lost, boundary visibility, extreme bins) make a good
  mock set.
- The model side guarantees this contract is stable; any future head
  change (e.g. a 2-logit visibility) will be announced as a PR + a
  DECISIONS.md entry before anything ships.
