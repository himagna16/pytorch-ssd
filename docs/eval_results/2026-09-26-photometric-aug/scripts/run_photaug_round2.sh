#!/bin/bash
# Sep 26 round 2: EXPO s0, CONTROL s1, EXPO s1, FRONTNET s1. Identical to round 1 but flag/seed.
set -u
cd /Users/saimaruvada/Downloads/drone/pytorch_ssd_photaug
LOG=/Users/saimaruvada/Downloads/drone/training/photaug_runs.log
for spec in expo_s0:exposure:0 control_s1:none:1 expo_s1:exposure:1 aug_s1:frontnet:1; do
  IFS=: read name flag seed <<< "$spec"
  out=/Users/saimaruvada/Downloads/drone/training/photaug_$name
  mkdir -p $out
  echo "=== $name start $(date) commit $(git rev-parse --short HEAD)" | tee -a $LOG
  ../nemoenv/bin/python -u train.py \
    --model-type plain_follow --follow-head-type xbin9_size_bucket4 \
    --init-ckpt /Users/saimaruvada/Downloads/drone/training/CHAMPION_qat_ep3_f1_8008.pth \
    --quant-aware-finetune --qat-bits 8 --qat-calib-batches 16 \
    --photometric-aug $flag --hard-negative-start-epoch 99 \
    --epochs 5 --batch_size 16 --num_workers 2 --lr 2e-5 \
    --seed $seed --max-train-batches 2600 --max-val-batches 25 \
    --output_dir $out > $out/train.log 2>&1
  echo "=== $name exit $? $(date)" | tee -a $LOG
done
