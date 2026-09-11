# Firmware contract — the 14-value follow output

> **Status (Sep 10):** write tests against synthetic vectors and David's known-good tensor until our releases pass the new semantic gates.

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
output quantization step — recorded per release in the generated app's
artifacts (`nemo_dory_artifacts.json` / `gap8_layer_manifest.json` in the
release output). A probability threshold p maps to:

`RAW_THRESH(p) = ceil( ln(p / (1-p)) / eps_out )`

Use `ceil`, not `round`: then `v >= RAW_THRESH(p)` is exactly
`sigmoid(v * eps_out) >= p` for integer `v`.

~10% of frames sit near the decision boundary, so a single threshold will
flicker. Use the follower's confirmation rule: declare VISIBLE only after
`v[9] >= RAW_THRESH(0.7)` on 3 consecutive frames; declare LOST when
`v[9] < RAW_THRESH(0.45)`. `RAW_THRESH` needs the final layer's `eps_out`
from a release that passes the semantic gates; the current releases do not.

## Reference decode (C, dependency-free, tested)

The tested implementation lives in `tools/firmware_decode/`
(`follow_decode.h`, `follow_decode.c`). Its tests check it against the
project's Python decode on 2,000 random and boundary vectors and 200
visibility sequences, and against the simulator follower's confirmation
rule. Run `tools/firmware_decode/run_tests.sh`. Use it rather than copying
code from this page. The core looks like this:

```c
/* thresholds from tools/firmware_decode/raw_thresholds.py --eps-out <eps> */
static const follow_vis_cfg_t FOLLOW_VIS_CFG = { ENTER_RAW, EXIT_RAW, 3 };
static follow_vis_state_t vis_state;   /* follow_vis_reset() at boot */

follow_cmd_t cmd;
follow_decode(out /* 14 int32 */, &FOLLOW_VIS_CFG, &vis_state, &cmd);
if (cmd.tracking) { /* steer on cmd.x_center, approach on cmd.size_center */ }
else              { /* hover */ }
```

## Integration notes

- The historical `crazyflie-ssd` wrapper decodes the OLD 3-value head —
  its `ssd_postprocess.c` must be replaced with the logic above.
- Test the controller against mocked 14-value tensors (motors off) before
  any camera-in-the-loop run — the worked example above plus hand-built
  edge cases (all-lost, boundary visibility, extreme bins) make a good
  mock set.
- The model side guarantees this contract is stable; any future head
  change (e.g. a 2-logit visibility) will be announced as a PR + a
  DECISIONS.md entry before anything ships.
