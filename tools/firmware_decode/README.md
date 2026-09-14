# Firmware decode reference (tested)

A small, dependency-free C decoder for the network's 14-value output, for the
frontend/firmware team. It is the executable version of
`docs/firmware_contract.md`.

- `follow_decode.h` / `follow_decode.c`: x-bin and size-bucket argmax, bin
  centers, and the visibility confirmation rule (count a frame at p >= 0.75,
  start tracking after 3 counting frames in a row, lose the target below
  p < 0.45). The rule matches the simulator follower exactly. The enter bar
  was 0.7 until 2026-09-13; for the champion (`eps_out` 2.009823510888964e-4)
  the baked constants are now `{5467, -998, 3}`, previously `{4216, -998, 3}`
  (`docs/firmware_contract.md`, change note).
- `test_follow_decode.c`: hand-built cases (David's known-good output,
  ties, int32 extremes, the confirmation state machine, threshold math).
- `gen_vectors.py`: random and boundary test vectors whose expected answers
  come from the project's own Python decode (`utils/follow_task.py` on the
  `successor-release` branch) and from a copy of the follower's state update.
- `raw_thresholds.py`: prints the integer thresholds to bake into firmware
  for a given output quantum `eps_out` (defaults `--enter 0.75 --exit 0.45
  --confirm-frames 3`; `--enter 0.7` reproduces the superseded bar).

Run everything (needs a C compiler and `../trainenv`):

```bash
tools/firmware_decode/run_tests.sh
```

Expected last line: `... checks, 0 failures` (14582 checks as of 2026-09-13; the
threshold test pins the champion's `{5467, -998, 3}`). The tests were checked for
strength by mutation: each of 7 deliberate single-line bugs (wrong
comparison, wrong tie rule, missing streak reset, rounding instead of
ceiling, off-by-one confirmation, wrong size offset) makes them fail.

**Important.** Do not take `eps_out` or example tensors from our Aug 28 or
Aug 31 releases. Those integer networks ignore their input (see the Sep 10
correction in `EXPERIMENTS.md`). Use David's known-good tensor and the
synthetic vectors until a release passes the semantic gates.

Thresholds use `ceil`, not `round`: with `r = ceil(logit(p) / eps_out)`,
`v >= r` is exactly `sigmoid(v * eps_out) >= p` for integer `v`, so the chip
and the simulator follower make identical decisions.
