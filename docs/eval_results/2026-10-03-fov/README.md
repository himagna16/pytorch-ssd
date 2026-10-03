# Camera field of view and aim, measured (Oct 3, 2026)

Drone 09, dorm. A bottle on 7 taped marks 1.00 m from the lens, captured with
`tools/real_frames/fov_capture.sh` and fitted with `fov_fit.py`. Frames stay local, in
`~/drone_frames/2026-10-03/fov_capture_140520`; only the numbers are committed.

- **Usable marks:** 4 of 7 (0, ±0.25 m, +0.5 m). The fit is good: residual RMS 1.4 px,
  max 2.0 px.
  - The −0.5 m and both ±0.7 m marks failed. The bottle hit the frame edge, or other
    things changed in view.
  - So the fit spans bearings −26.6° to +14°.
- **Focal length:** 79.3 ± 3.7 px/rad at 162 px wide, which is 158.6 at 324 px. The
  simulator assumes 174.23.
- **Network crop (122 of 162 px): 75.1 ± 2.6° horizontal field of view,** against 70°
  assumed everywhere:
  - `score_real_frames.py` `--crop-hfov`;
  - `pose_to_label.py` `CameraSpec`;
  - `camera_model.py`.

  This assumes the stream is the full sensor frame scaled down 2×, which is not verified.
- **Aim:** the camera is turned 2.6° RIGHT of the tape line. A person on the line reads
  x = −0.06, x-bin 4, which is the correct centre bin. So aim does not explain the
  one-bin-left lean seen in the Sep 24 grid labels.
- **Effect on labels:** at most 1 bin, near 14° and 30° bearing.
- **Single forward distance:** an error in the 1.00 m distance carries straight into f.
  1 cm of distance error is 1% of f.

Next: re-score the real frames with `--crop-hfov 75.1`. Decide whether to change the
70° default once the stream-vs-sensor scaling is confirmed.
