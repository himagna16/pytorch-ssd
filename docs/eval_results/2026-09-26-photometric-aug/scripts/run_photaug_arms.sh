#!/bin/bash
# Sep 26 photometric-augmentation experiment: AUG then CONTROL, identical except one flag.
set -u
cd /Users/saimaruvada/Downloads/drone/pytorch_ssd_photaug
for arm in aug control; do
  if [ $arm = aug ]; then flag=frontnet; else flag=none; fi
  out=/Users/saimaruvada/Downloads/drone/training/photaug_$arm
  mkdir -p $out
  echo "=== $arm start $(date)" | tee -a /Users/saimaruvada/Downloads/drone/training/photaug_runs.log
  ../nemoenv/bin/python -u train.py \
    --model-type plain_follow --follow-head-type xbin9_size_bucket4 \
    --init-ckpt /Users/saimaruvada/Downloads/drone/training/CHAMPION_qat_ep3_f1_8008.pth \
    --quant-aware-finetune --qat-bits 8 --qat-calib-batches 16 \
    --photometric-aug $flag --hard-negative-start-epoch 99 \
    --epochs 5 --batch_size 16 --num_workers 2 --lr 2e-5 \
    --seed 0 --max-train-batches 2600 --max-val-batches 25 \
    --output_dir $out > $out/train.log 2>&1
  echo "=== $arm exit $? $(date)" | tee -a /Users/saimaruvada/Downloads/drone/training/photaug_runs.log
done
