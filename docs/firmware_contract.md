# Firmware contract — the 14-value follow output

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

Worked example (real validated GVSOC output):
`[132345, 163455, 213690, 249900, 290955, 262650, 229755, 170085, 112455, 374085, 147135, 101745, 108375, 201450]`
→ x argmax = index 4 (center bin), visibility = 374085 (≥ threshold →
visible), size argmax = bucket 3 (close). Decoded command: "person visible,
centered, close."

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

`RAW_THRESH(p) = round( ln(p / (1-p)) / eps_out )`

~10% of frames sit near the decision boundary, so a single threshold will
flicker. Use hysteresis: declare VISIBLE when `v[9] >= RAW_THRESH(0.55)`,
declare LOST when `v[9] < RAW_THRESH(0.45)`, hold previous state in
between. Also require N consecutive LOST frames (suggest N=3 at ~10 Hz)
before triggering loss-of-target behavior (hover/stop per your safety
design — PULP-DroNet used low-pass filtering with alpha=0.7 for the same
reason).

## Reference decode (C, dependency-free)

```c
typedef struct { int x_bin; float x_center; int size_bucket;
                 float size_center; int visible; } follow_cmd_t;

/* Set from the release artifacts for the shipped network: */
static const int32_t VIS_ENTER_RAW = /* RAW_THRESH(0.55) */;
static const int32_t VIS_EXIT_RAW  = /* RAW_THRESH(0.45) */;

static int argmax_i32(const int32_t *v, int n) {
    int best = 0;
    for (int i = 1; i < n; i++) if (v[i] > v[best]) best = i;
    return best;
}

void decode_follow(const int32_t out[14], follow_cmd_t *cmd,
                   int *vis_state /* persistent across frames */) {
    cmd->x_bin       = argmax_i32(out, 9);
    cmd->x_center    = -1.0f + (2.0f * cmd->x_bin + 1.0f) / 9.0f;
    cmd->size_bucket = argmax_i32(out + 10, 4);
    cmd->size_center = (cmd->size_bucket + 0.5f) / 4.0f;
    if (out[9] >= VIS_ENTER_RAW)      *vis_state = 1;
    else if (out[9] < VIS_EXIT_RAW)   *vis_state = 0;
    /* between thresholds: hold previous state */
    cmd->visible = *vis_state;
}
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
