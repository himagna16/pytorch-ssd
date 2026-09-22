# First real AI-deck frames: dorm camera check, 2026-09-22

The first frames this project has ever scored from the real drone camera. It was one
session in Sai's dorm, with one subject (Sai), two 10 s clips and 49 frames. The frames
themselves stay on Sai's laptop (`~/drone_frames/2026-09-22/camera_check_181258/`)
because they show people and this repo is public. This folder holds only numbers.

## Setup

- `tools/real_frames/camera_check.sh`, run by Sai with the laptop on the deck's WiFi
  and no internet. The drone sat on a chair at the window end of the 5 x 11 ft tile
  floor, lens about 0.8 m up, facing the door (`docs/hardware/dorm_camera_check.svg`).
- Marks 8 tiles out (2.44 m), 2 tiles either side (bearing -14 / +14 deg). LEFT clip
  first, then RIGHT. Room lights on, curtains closed.
- Scored on the chip arm (`model_id_dory.onnx` sha1 d90555c8, eps 2.0098e-4, enter
  5467 / lost -998 / confirm 3). The float arm was not used.

## Verdicts

| question | answer | how sure |
|---|---|---|
| Does the stream work? | **Yes.** 49/49 frames decoded, 0 cut short | certain |
| Is the camera image mirrored? | **No, by eye.** Sai is left of image centre in the LEFT clip and right of it in the RIGHT clip (frame 12) | two clips, one subject, judged by eye. The scorer's automatic check could not decide it (next row) |
| Did the scorer's MIRROR CHECK pass? | **FAIL, "NOT a mirror".** The network said x-bin 7 in 41 of 44 clip frames, whichever mark Sai stood on | certain, see the cause below |
| Why bin 7 everywhere? | **A false positive on furniture in the right third of the frame** (loft ladder, office chair, window blinds) | strong: three probes agree, listed below |
| How well is a real person at 2.44 m detected once the distractor is removed? | **Weakly.** Median confidence 0.23-0.24, no frame at or above the 0.75 enter bar | n = 44 frames, one person, one background: a first data point, not a rate |

## The probes (`probe_results.json`, `scripts/probe_chip.py`)

| input | x-bins | median conf | frames >= 0.75 |
|---|---|---|---|
| check frames (Sai at the laptop, right foreground, NOT at the marks) | 7 x5 | 0.68 | 0/5 |
| LEFT clip, as captured | 7 x21, 2 x1 | 0.58 | 3/22 |
| RIGHT clip, as captured | 7 x20, 4, 6 | 0.63 | 7/22 * |
| LEFT clip, right third blanked to the frame mean | 4 x16, 2 x2, 3, 6 x3 | 0.24 | 0/22 |
| RIGHT clip, right third blanked | 4 x18, 3 x2, 5, 6 | 0.23 | 0/22 |
| LEFT clip, mirrored left-right | 1 x22 | 0.90 | 22/22 |
| both clips, contrast stretched to 0-255 | unchanged (bin 7) | 0.53 / 0.64 | 4 / 5 |

\* The last frames of the RIGHT clip contain a real person at the right edge (Sai
walking back to the laptop), and so do the check frames. There, bin 7 / size bucket
3 ("right, very close") is a **correct** answer. In the frames where Sai stood on the
marks and the right side shows only the ladder, the chair and the blinds, the same
answer is a **false positive**. As captured, the follower latched (tracking column in
`scorer_output.txt`) on 32% of LEFT-clip frames and 5% of RIGHT-clip frames.

Reading:
- Blanking the right third moves the answer to centre and drops confidence to about
  0.2. So the right-side region was producing the detection, not Sai.
- Mirroring moves the answer to bin 1. So the x head responds to the image and is not
  stuck.
- Mirroring also *raises* confidence (0.58 to 0.90). That is unexplained, and one clip
  cannot say whether it matters.
- Contrast stretching changes nothing, so the clipped range (next section) is not the
  cause of the false positive.

## The real stream is not what the simulator assumed

| property | simulator / pipeline assumption | this deck, 2026-09-22 |
|---|---|---|
| frame size | 324 x 244 | **162 x 122** (looks 2x2 binned; same field of view not yet verified) |
| pixel range | 0-255 | **0-191**, 128 distinct values |
| rate over WiFi | ~13 fps (sim) | **~2.2 fps** |
| colour | mono (or Bayer, flag exists) | **mono**: the four 2x2 phase means are 90.6 / 90.6 / 89.6 / 89.5, so no mosaic |

The chip preprocess takes a centre square crop of any size, so 162 x 122 is
geometrically handled: the 122 px crop is upsampled to 128. But this is a distribution
shift that no simulator run or training image has seen. Open question for MinHyuk:
which streamer build and camera mode is on this deck, and was it deliberately binned?

## What this does and does not say

- It **does** say the camera is not mirrored (by eye), the model's left/right responds
  to the image, and the champion calls ordinary dorm furniture a person strongly
  enough to latch.
- It does **not** give a detection rate for real people. It is one subject, one
  background, 44 frames, a cluttered room, and an image format the pipeline was not
  built for.
- The weak detection of Sai at 2.44 m is consistent with the Sep 15 simulator
  finding that ordinary people sit near or below the bar
  (`2026-09-15-typical-person/`). It does not confirm it.

## Next

1. Re-run with the right side cleared (office chair out of view, blinds covered), plus
   an **empty-room clip** (`--vis 0`) to measure the furniture false positive directly.
2. Settle the stream format with MinHyuk (162 x 122, max 191) before collecting the
   Session A protocol at scale.
3. Retry the mirror check scoring once the scene has no competing detection.
