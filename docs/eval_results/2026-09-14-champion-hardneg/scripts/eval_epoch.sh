#!/bin/bash
# Evaluate one checkpoint on both axes with the team's own tools.
#   axis 1: deployed-form (fake-quant, learned QAT alphas) peak F1 on val2017
#   axis 2: pet/mannequin false-alarm rate on the 771-image confuser slice
# Usage: eval_epoch.sh <ckpt.pth> <outdir>
set -euo pipefail
CKPT="$1"; OUT="$2"
NEMO=/Users/saimaruvada/Downloads/drone/nemoenv/bin/python
cd /Users/saimaruvada/Downloads/drone/pytorch_ssd
NAME=$(basename "$CKPT" .pth)
$NEMO export/sweep_fq_ckpt.py --mode qat --ckpt "$CKPT"       > "$OUT/${NAME}_f1.log"    2>&1
$NEMO export/confuser_slice_eval.py "$CKPT"                   > "$OUT/${NAME}_slice.log" 2>&1
echo "== $NAME =="
grep "DEPLOYED-FORM peak F1" "$OUT/${NAME}_f1.log"
grep "confuser-slice FP" "$OUT/${NAME}_slice.log"
