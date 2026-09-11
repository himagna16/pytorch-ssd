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
