# Float vs chip network on 1,000 random images (Sep 11, 2026)

Unbiased check of how closely each model's integer (chip) network follows
its float version. 1,000 COCO val2017 images drawn uniformly with seed
20260911 (`image_sets.json`), plus all 771 "confuser" images (animals or
teddy bears, no person). Integer outputs come from ONNX Runtime on each
release's `model_id_dory.onnx`, which the patched DORY and the chip match
within about 300 raw units. Preprocessing matches the release bit for bit
(`parity_report.json`). An independent verifier re-derived the headline
numbers.

| | champion | confuser | confuser, QAT + mining |
|---|---|---|---|
| visibility agreement, p = 0.5 (95% CI) | 95.9% (94.5-97.0) | 93.0% (91.3-94.4) | 94.9% (93.4-96.1) |
| chip overturns a confident float decision | 1 / 821 | 1 / 875 | 1 / 849 |
| chip F1 at 0.5 (float F1 is statistically equal) | 0.812 | 0.757 | 0.772 |
| chip recall at 0.7 | 0.683 | 0.511 | 0.557 |
| chip false alarms on empty scenes at 0.7 | 10.7% | 2.8% | 6.3% |
| chip false alarms on pets and mannequins at 0.45 | 30.2% | 11.0% | 12.8% |

All three clear the 90% agreement bar; quantization costs no measurable
accuracy. The chip's visibility logit runs about 0.13-0.19 higher than the
float one, so an integer threshold 0.02-0.05 above the float one restores
agreement. The real choice is detection versus false alarms: the champion
finds more people; the confuser models false-alarm far less.

The release pipeline's evaluation pack is geometry-selected and not harder
on visibility for these models, but it lowers full-decision agreement
(x-bin and size) by 6-10 points.

Files: `infer.py` (inference), `analyze.py` and `extra.py` (metrics),
`parity_check.py`, `results.json`, `results_extra.json`, per-image CSVs.


## Added later: QAT confuser, epoch 2 of a 3-epoch run with hard-negative mining

`infer_ep2.py` and `analyze_4.py` add a fourth model; all four are in
`results_4.json` and `per_image4_*.csv`.

| chip network, 1,000 random images | champion | confuser | QAT confuser, 1 epoch | QAT confuser, epoch 2 |
|---|---|---|---|---|
| visibility agreement with float, p = 0.5 | 95.9% | 93.0% | 94.9% | 92.9% |
| overturns a confident float call | 1 / 821 | 1 / 875 | 1 / 849 | 7 / 874 |
| F1 at 0.5 | 0.811 | 0.757 | 0.772 | 0.740 |
| recall at 0.7 | 0.683 | 0.511 | 0.557 | 0.500 |
| false alarms, empty scenes, at 0.7 | 10.7% | 2.8% | 6.3% | 3.7% |
| false alarms, pets and mannequins, at 0.45 | 30.2% | 11.0% | 12.8% | 10.6% |

On the chip, epoch 2 behaves like the plain confuser: the release strips the
activation ranges learned in QAT and recalibrates, so its fake-quant slice
rate of 8.4% becomes 10.6% on the chip.
