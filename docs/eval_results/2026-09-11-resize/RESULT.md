# Firmware nearest-neighbor vs training bilinear resize: effect on follow decisions

**Bottom line.** The firmware's nearest-neighbor resize measurably changes the model's decisions, and the change hurts accuracy. With nearest instead of the training resize:

- The champion's visibility decision at 0.5 flips on about 13% of frames.
- The decision at the follower's 0.7/0.45 rule changes on about 24%.
- Recall drops: F1@0.7 falls by 0.068 for the float champion and 0.050 for the integer ONNX. The paired-bootstrap 95% CIs exclude 0.

A 2x2 box average at the same source index (one C change, about 10 lines) closes the gap. Its disagreement with the training resize is about the same as moving the camera crop by 1 pixel, which is the per-frame noise floor. Its accuracy is statistically the same as the training resize. **Recommendation: change preprocess.c to the 2x2 box version below.**

## Setup (1000 random val2017 images, seed 20260911, from unbiased_eval/image_sets.json)

- **Camera frame emulation.** COCO RGB → gray (PIL `L`) → resize to *cover* 324x244 → center-crop to 324x244 → uint8.
  - The resize is PIL bilinear with antialiasing, standing in for the optics and sensor low-pass.
  - A person-free aspect distortion would be wrong, so this is a cover resize, not a stretch.
  - GT boxes go through the same scale, shift, clamp and filter steps using the repo's `_clamp_and_filter_boxes`.
  - GT on this set: 526 frames with a person visible, 460 true no-person, 14 where the person is cropped out.
- **Paths from the same 324x244 frame:**
  - **bilinear.** The repo's own `get_val_transforms(plain_follow)`: CenterCropSquare, then torchvision resize (PIL bilinear, antialiased), then to_tensor. Integer input is round(x*255), which is identical to the PIL uint8 output (max diff 0.0).
  - **nearest.** An exact port of `preprocess.c`: `src = crop + (i*244)/128`, with crop_x=40 and crop_y=0. I also compiled the real `crazyflie_ssd/src/preprocess.c` into a host harness. Its output is **byte-identical** to the port on all 1000 frames (`c/bitexact.txt`).
  - **box2_nearest (proposed).** The rounded mean `(sum+2)>>2` of the 2x2 block starting at the nearest source pixel. The compiled C version (`c/preprocess_box2.c`) is also byte-identical to the Python version.
  - **area_box.** A true area average (PIL BOX) of the 244x244 crop.
  - **bilinear_shift1px (reference only).** The training resize with the square crop shifted 1 camera pixel. This is a natural frame-to-frame noise floor.
- **Models:**
  - float champion `successor_qat_ep3_eval.pth`
  - float confuser `successor_confuser_ep8.pth`
  - champion integer ONNX `plain_follow_prod_qat_final/quant_eval/model_id_dory.onnx`, run in ORT with optimizations disabled. logits = raw * eps, eps = 2.009823510888964e-4.
- **Metrics.** Reused from `unbiased_eval/analyze.py`: `agreement_block`, `prf_ci`, Wilson intervals, and a paired bootstrap of 2000 resamples.
  - Tri-state uses ≥0.7 as confident-visible, <0.45 as confident-not-visible, and anything in between as uncertain.
  - "Hard" means the path lands on the opposite confident side.
  - x-bin and size are compared where both paths say visible at 0.5.
  - GT bins come from `follow_task` `XBIN9_EDGES` and `SIZE_BUCKET4_EDGES`.
- **Pixel error vs bilinear (0-255):**

  | path | MAE | RMSE |
  |---|---|---|
  | nearest | 9.10 | 17.0 |
  | box2 | 4.31 | 8.3 |
  | area | 3.10 | 5.7 |
  | 1-px shift (reference) | 4.61 | 9.1 |

## Decision agreement with the training (bilinear) path, n=1000

| model | path | vis agree @0.5 | 0.7/0.45 tri-state agree | hard flips | x-bin exact / ±1 | size exact | all agree (vis+x+size) |
|---|---|---|---|---|---|---|---|
| champion float | **nearest** | 87.1% | 77.0% | 31 | 77.3% / 89.4% | 78.3% | 71.0% |
| | box2 | 93.0% | 85.3% | 4 | 86.6% / 93.8% | 85.7% | 81.4% |
| | area | 93.6% | 86.7% | 1 | 89.1% / 94.2% | 88.9% | 84.2% |
| | 1-px shift (floor) | 93.0% | 87.8% | 1 | 87.0% / 95.1% | 88.5% | 82.7% |
| champion INT ONNX | **nearest** | 87.1% | 75.2% | 28 | 78.0% / 90.3% | 81.3% | 71.0% |
| | box2 | 91.4% | 84.0% | 2 | 86.6% / 95.1% | 88.0% | 79.8% |
| | area | 93.4% | 84.8% | 1 | 87.5% / 93.8% | 91.0% | 83.5% |
| | 1-px shift (floor) | 93.9% | 87.0% | 0 | 86.2% / 94.9% | 91.4% | 83.4% |
| confuser float | **nearest** | 88.6% | 80.9% | 27 | 75.6% / 89.2% | 78.7% | 77.0% |
| | box2 | 93.6% | 88.4% | 4 | 85.7% / 95.1% | 88.8% | 85.8% |
| | area | 93.8% | 88.9% | 3 | 86.9% / 93.3% | 92.1% | 87.3% |
| | 1-px shift (floor) | 94.8% | 88.9% | 4 | 86.4% / 94.5% | 90.0% | 87.4% |

**Confident decisions that change** (the float path is confident, and the tested path leaves that confident band):

| model | nearest | box2 | area | 1-px shift |
|---|---|---|---|---|
| champion float | 15.8% | 9.2% | 8.0% | 6.8% |
| champion INT | 17.3% | 10.6% | 9.4% | 6.9% |

## Accuracy vs ground truth (visibility P/R/F1; person GT visible = 526/1000)

| model | path | F1@0.5 | R@0.5 | F1@0.7 | P@0.7 | R@0.7 | ΔF1@0.5 vs bilinear [95% CI] | ΔF1@0.7 vs bilinear [95% CI] | no-person FA@0.5 |
|---|---|---|---|---|---|---|---|---|---|
| champion float | bilinear | 0.802 | 0.785 | 0.749 | 0.910 | 0.637 | – | – | 19.3% |
| | **nearest** | 0.765 | 0.713 | 0.682 | 0.898 | 0.549 | **−0.037 [−0.061, −0.014]** | **−0.068 [−0.097, −0.040]** | 17.0% |
| | box2 | 0.793 | 0.778 | 0.748 | 0.912 | 0.633 | −0.009 [−0.026, +0.007] | −0.002 [−0.024, +0.018] | 20.9% |
| | area | 0.797 | 0.776 | 0.742 | 0.907 | 0.627 | −0.005 [−0.022, +0.010] | −0.008 [−0.028, +0.012] | 19.3% |
| champion INT | bilinear | 0.799 | 0.802 | 0.750 | 0.882 | 0.652 | – | – | 22.4% |
| | **nearest** | 0.773 | 0.759 | 0.700 | 0.879 | 0.582 | **−0.025 [−0.048, −0.005]** | **−0.050 [−0.079, −0.020]** | 22.2% |
| | box2 | 0.791 | 0.800 | 0.753 | 0.895 | 0.650 | −0.008 [−0.026, +0.009] | +0.004 [−0.016, +0.024] | 25.0% |
| | area | 0.802 | 0.812 | 0.752 | 0.891 | 0.650 | +0.003 [−0.012, +0.018] | +0.002 [−0.018, +0.024] | 23.7% |
| confuser float | bilinear | 0.732 | 0.614 | 0.628 | 0.965 | 0.466 | – | – | 7.0% |
| | **nearest** | 0.683 | 0.557 | 0.588 | 0.957 | 0.424 | **−0.049 [−0.077, −0.023]** | **−0.041 [−0.073, −0.008]** | 8.3% |
| | box2 | 0.742 | 0.629 | 0.647 | 0.962 | 0.487 | +0.010 [−0.010, +0.030] | +0.018 [−0.005, +0.041] | 7.4% |
| | area | 0.723 | 0.610 | 0.634 | 0.961 | 0.473 | −0.010 [−0.029, +0.012] | +0.006 [−0.018, +0.029] | 8.7% |

How nearest hurts: it mostly costs **recall**, meaning people are missed, especially at the 0.7 enter threshold. Precision barely moves. x-bin and size accuracy vs GT do not change meaningfully on any path (x exact about 44-48%, ±1 about 75-80%, size about 66-72% for all paths). Those differences are within the Wilson intervals, which are about ±5 percentage points at n≈400.

For the champion INT, box2's no-person false-alarm rate at 0.5 is 25.0% (115/460) vs 22.4% (103/460) for bilinear. That is 12 more frames, inside the noise; the ΔF1 CIs include 0. The 3-frame confirm at 0.7 is what gates flight.

## Recommendation and exact C change

Use the 2x2 box. It gets the gap to the 1-pixel-jitter noise floor. A true area resize is only marginally better (pixel RMSE 5.7 vs 8.3). It is not better on decisions, and it needs non-integer footprints (weights over 1.906 px). The 2x2 box needs 4 loads, 3 adds and a shift per output pixel, 16384 times per frame. That cost is my estimate, not a measurement on the GAP8. At this 1.906x scale it never reads outside the 244x244 crop. The edge clamps are only for generality.

The full proposed file is `c/preprocess_box2.c`, and `preprocess_box2.diff` is the diff against the current firmware file. Replace the body of `preprocess_camera_to_net_input` with:

```c
  int crop_size = (cam_w < cam_h) ? cam_w : cam_h;
  int crop_x = (cam_w - crop_size) / 2;
  int crop_y = (cam_h - crop_size) / 2;
  int crop_x_last = crop_x + crop_size - 1;
  int crop_y_last = crop_y + crop_size - 1;
  int y;
  int x;

  for (y = 0; y < APP_NET_INPUT_H; y++) {
    int src_y = crop_y + ((y * crop_size) / APP_NET_INPUT_H);
    int src_y1 = (src_y < crop_y_last) ? (src_y + 1) : src_y;
    const uint8_t *row0 = cam_buf + (src_y * cam_w);
    const uint8_t *row1 = cam_buf + (src_y1 * cam_w);

    for (x = 0; x < APP_NET_INPUT_W; x++) {
      int src_x = crop_x + ((x * crop_size) / APP_NET_INPUT_W);
      int src_x1 = (src_x < crop_x_last) ? (src_x + 1) : src_x;
      unsigned int sum = (unsigned int)row0[src_x] + (unsigned int)row0[src_x1] +
                         (unsigned int)row1[src_x] + (unsigned int)row1[src_x1];
      uint8_t gray = (uint8_t)((sum + 2u) >> 2);
      /* ... unchanged dst_idx / net_in writes for C==1 and C==3 ... */
    }
  }
```

Before flashing, re-run the GVSOC/DORY smoke on a camera frame through the new preprocess. Also update any host-side "firmware-preprocess" emulation so it matches the new version.

## Caveats

- **The camera is idealized.** The emulated frame is a clean antialiased downscale of a JPEG photo. The real HM01B0 adds sensor noise, its own optics blur and exposure effects. My reasoning, not measured here: sensor noise should make plain nearest worse still, because it averages nothing, while the 2x2 box averages 4 samples (about 2x noise reduction). I didn't test with real camera frames. A short capture of about 50 frames, run through both paths, would confirm this.
- **Scope.** This is 1000 single frames, with no temporal hysteresis. Only the champion INT was run in ONNX. I ran the confuser as float only, as requested.

## Files

- `study.py`: `infer` builds the frames, the 5 preprocessing variants and runs 3 model paths. `analyze` computes the metrics.
- `per_image.npz`: all 128x128 inputs, logits and targets.
- `frames.u8`: the 1000 emulated 324x244 frames.
- `results.json` and `analyze.log`: full numbers with CIs.
- `c/`: the harness, the stub headers, the proposed `preprocess_box2.c`, and the bit-exact proof `bitexact.txt`.
