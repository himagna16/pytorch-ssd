# DORY patches (required before any code generation)

Apply to the DORY checkout used for code generation (commit `add0d9c`):

```bash
tools/dory_patches/apply.sh /path/to/dory
```

## 0001: wrap-safe weight casts

**Bug.** DORY writes int8 weights by casting float32 arrays straight to
uint8 (`HW_node.py`, `add_checksum_w_integer`). Casting a negative float to
an unsigned integer is undefined in C. On Apple Silicon with NumPy older
than 1.25 (our `doryenv` has 1.24.3), long arrays saturate to 0 instead of
wrapping, so **every negative weight became 0**. Short arrays still wrap,
which hides the bug in small tests. The only symptom in the logs was
`RuntimeWarning: invalid value encountered in cast`.

**Effect.** With only non-negative weights, activations pinned at 255 by
the third layer, and the network output one constant tensor for every
image. The Python DORY-graph simulator, the goldens, and the GAP8 app all
used the same corrupted weights, so GVSOC "exact match" still passed. This
broke our Aug 28 and Aug 31 releases. David's app was generated on x86,
where the cast happens to wrap.

**Fix.** Round, widen to int64, then wrap to uint8, which gives the
two's-complement bytes on every platform. The patch changes two lines: the
weight cast in `HW_node.py` and the cast where `Parser_HW_to_C.py` writes the
weight `.hex` files. It is the exact patch used in the Sep 10 fix test, where
the fixed DORY simulator gave distinct outputs on every test image and matched
ONNX Runtime's decisions. `Parser_HW_to_C.py` has Windows line endings; apply
with `git apply` (as `apply.sh` does), not by hand-editing.

**Check.** `export/check_semantic_release_gates.py` (on
`successor-release`) now fails any app whose weight files contain no
negative bytes, among other semantic checks.

## 0002: argument array size in the generated network

DORY's shared template `dory/Hardware_targets/PULP/Common/Templates/network.c.t`
(the GAP8 `network_c_template.c` is a symlink to it) declares
`unsigned int args[4]` but writes five entries, one past the end of a stack
array. The GVSOC harness patched the generated file inside its container,
so validation passed while the repo's app kept the bug. The patch sizes the
array 5 (6 without L3).

## 0003: build switch for DORY's debug output

The template hard-codes `#define VERBOSE 1`, which makes every inference run
per-layer checksums on one core plus `printf`: about 38 ms on GAP8, more than
the 8-core network itself (about 23 ms). The patch keeps the default but lets
a flight build add `-DDORY_NO_VERBOSE` to turn it off.
