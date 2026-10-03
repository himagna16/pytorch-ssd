# Dark-door 2x2 control (Oct 3, 2026)

Drone 09, dorm, `tools/real_frames/door_control.sh`, chip network. Sai (p01) stood on the
CENTRE mark (2.13 m, bearing 0), 13 frames per cell, at brightness 32-35 (low end of the
30-60 band). Frames stay local in `~/drone_frames/2026-10-03/door_control_141933`.

| | dark top | light top |
|---|---|---|
| door bare | median 0.54, 0/13 ≥ 0.75, never locked, bin 2 | median 0.61, 0/13, never locked, bin 2 |
| sheet over door | median 0.72, 2/13, never locked, bin 2 | median 0.52, 1/13, never locked, bin 2 |

Empty-room clips (44 frames): 0 false locks, peak 0.69.

**Reading.**
- **Neither the background nor the shirt fixes it.** The model never locks onto a person
  standing dead centre at 2.13 m in this room under any of the four conditions. So the
  Sep 24 "contrast" explanation is not supported. This is a perception or domain-gap
  problem, possibly made worse by the dim exposure.
- **The x-bin reads 2 when it fires, but the correct answer is 4.**
  - The FOV measurement the same day (`2026-10-03-fov`) shows the camera aimed 2.6° right
    with the centre bin correct. So the leftward error is the model's, not the camera's.
  - Sep 24 showed the same one-to-two-bin lean.
- **Caveat:** one person, one session, 13 near-duplicate frames per cell. That is a
  direction, not a proof.
- **Implication:** this supports real-frame fine-tuning (the expert reviews' change #5)
  over more background or contrast work.
