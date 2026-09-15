#!/usr/bin/env python3
"""GEOMETRY: at what range does a 1.7 m person stop fitting in the model's crop?

Every constant is read out of the repo, not typed here:

  CROP_FOV_DEG   tools/crazysim_macos/scoreboard.py  (70.0, the square centre
                 crop of a 244-tall render at fovy=70)
  height         tools/crazysim_macos/follow_person.py --height default (0.8 m),
                 camera level (the follower yaws, it does not pitch)
  TARGET_SIZE    follow_person.py --target-size (0.625, bucket-2 centre)
  SIZE_EDGES     utils/follow_task.py SIZE_BUCKET4_EDGES, via scoreboard.py

The model sees a SQUARE crop, so the vertical half-angle equals the horizontal
half-angle: 35 deg either way, tan = 0.70021.

A person of height PERSON_H standing on the floor, camera on a level optical
axis at CAM_Z, at horizontal range d:

  the crop's vertical extent at that range is  CAM_Z +- d*tan(35 deg)
  the head fits   while  PERSON_H <= CAM_Z + d*tan   ->  d >= (PERSON_H-CAM_Z)/tan
  the feet fit    while  0        >= CAM_Z - d*tan   ->  d >= CAM_Z/tan

so the WHOLE person fits beyond max of those two, and closer than that the
fraction of the body inside the crop falls off as 1/d.

Usage: nemoenv/bin/python geometry_fov.py <outdir>
"""
import csv
import math
import sys
from pathlib import Path

sys.path.insert(0, "/Users/saimaruvada/Downloads/drone/pytorch_ssd/tools/crazysim_macos")
import scoreboard as SB  # noqa: E402

CAM_Z = 0.8          # follow_person.py --height default
PERSON_H = 1.7       # scene_defs person height_m, unchanged across every person cell
TAN = SB.TAN_HALF_FOV
HALF = SB.CROP_FOV_DEG / 2

# the flown evidence, quoted rather than recomputed
HOLD_MEANS = [1.63, 1.74, 1.87, 2.00, 2.19, 2.20, 2.44]   # 2026-09-14-baseline-075 scoreboard.md
HOLD_SPREAD = (1.55, 2.44)
START_RANGES = {"s15 static": 3.64, "s01 moving": 3.11}   # 2026-09-15-typical-person
BAND_NEAR = SB.BAND_K[0] * PERSON_H       # bucket 2/3 boundary
BAND_FAR = SB.BAND_K[1] * PERSON_H        # bucket 1/2 boundary -> the approach floor
TARGET_D = SB.HOLD_K * PERSON_H

OUT = []


def P(s=""):
    print(s, flush=True)
    OUT.append(s)


def visible_fraction(d):
    """Fraction of a PERSON_H body inside the square crop at horizontal range d."""
    if d <= 0:
        return 0.0
    top = min(PERSON_H, CAM_Z + d * TAN)
    bot = max(0.0, CAM_Z - d * TAN)
    return max(0.0, top - bot) / PERSON_H


def px128_h(d):
    """Apparent height in the 128x128 tensor, whole-body only (the study's law)."""
    return 128.0 * PERSON_H / (2.0 * d * TAN)


def px128_visible(d):
    """Apparent height of the VISIBLE part, which is what the network is shown."""
    return min(128.0, px128_h(d))


def main():
    D = Path(sys.argv[1])
    P("=" * 78)
    P("GEOMETRY OF THE MODEL'S CROP - is MinHyuk's FOV objection true of OUR rig?")
    P("=" * 78)
    P(f"  CROP_FOV_DEG      {SB.CROP_FOV_DEG}   (scoreboard.py, square crop)")
    P(f"  half-angle        {HALF} deg, tan = {TAN:.5f}  (BOTH axes: the crop is square)")
    P(f"  camera height     {CAM_Z} m  (follow_person.py --height default), optical axis LEVEL")
    P(f"  person height     {PERSON_H} m  (scene_defs, every person cell)")
    P("")
    d_head = (PERSON_H - CAM_Z) / TAN
    d_feet = CAM_Z / TAN
    d_whole = max(d_head, d_feet)
    P(f"  head leaves the crop below   d = ({PERSON_H} - {CAM_Z}) / {TAN:.5f} = {d_head:.3f} m")
    P(f"  feet leave the crop below    d = {CAM_Z} / {TAN:.5f} = {d_feet:.3f} m")
    P(f"  => WHOLE PERSON FITS FOR d >= {d_whole:.3f} m, and the head goes first")
    P("")
    P("Visible fraction and apparent size against range:")
    P(f"{'range m':>9}{'vis frac':>10}{'what is cut':>26}{'px128_h vis':>13}{'note':>34}")
    rows = [("range_m", "visible_fraction", "cut", "px128_h_whole", "px128_h_visible", "note")]
    ladder = [0.5, 0.75, 1.0, 1.2, 1.285, 1.5, 1.62, 1.8, 1.94, 2.2, 2.43, 2.7, 3.0, 3.11,
              3.64, 4.0, 5.0]
    for d in ladder:
        vf = visible_fraction(d)
        top_cut = PERSON_H > CAM_Z + d * TAN
        bot_cut = 0.0 < CAM_Z - d * TAN
        cut = "head" if top_cut and not bot_cut else ("head+feet" if top_cut and bot_cut
                                                      else ("feet" if bot_cut else "-"))
        note = ""
        if abs(d - d_whole) < 0.01:
            note = "<- whole person just fits"
        elif abs(d - TARGET_D) < 0.01:
            note = "<- follower's target"
        elif abs(d - BAND_FAR) < 0.01:
            note = "<- approach floor (bucket 1/2)"
        elif abs(d - BAND_NEAR) < 0.01:
            note = "<- near edge of hold band"
        elif abs(d - 3.64) < 0.01:
            note = "<- s15 start range"
        elif abs(d - 3.11) < 0.01:
            note = "<- s01 start range"
        elif HOLD_SPREAD[0] <= d <= HOLD_SPREAD[1]:
            note = "   (inside the flown hold spread)"
        P(f"{d:>9.2f}{vf:>10.3f}{cut:>26}{px128_visible(d):>13.1f}{note:>34}")
        rows.append((f"{d:.3f}", f"{vf:.4f}", cut, f"{px128_h(d):.2f}",
                     f"{px128_visible(d):.2f}", note.strip(" <-")))
    with open(D / "tables/geometry_fov.tsv", "w", newline="") as f:
        csv.writer(f, delimiter="\t").writerows(rows)
    P("")
    P("Where the follower actually is:")
    P(f"  flown hold means (7 person cells, 2026-09-14-baseline-075): "
      f"{' / '.join(f'{v:.2f}' for v in HOLD_MEANS)} m")
    P(f"  repeat spread {HOLD_SPREAD[0]:.2f}-{HOLD_SPREAD[1]:.2f} m; target {TARGET_D:.3f} m "
      f"(HOLD_K x {PERSON_H})")
    P(f"  size-bucket hold band {BAND_NEAR:.3f}-{BAND_FAR:.3f} m: a person anywhere in it decodes")
    P(f"    to bucket 2, so a drone closing from far away STOPS at {BAND_FAR:.3f} m - "
      f"that is the closest")
    P("    the control law ever needs to get, and the flown cells confirm it "
      "(nearest mean 1.63 m).")
    for k, v in START_RANGES.items():
        P(f"  start range {k}: {v:.2f} m, visible fraction {visible_fraction(v):.3f}")
    P("")
    P(f"  MARGIN: the closest the flown cells ever settled is {min(HOLD_SPREAD):.2f} m, against a "
      f"whole-body limit of {d_whole:.3f} m.")
    P(f"  That is {min(HOLD_SPREAD) - d_whole:.2f} m of clearance, i.e. the follower would have to "
      f"overshoot by {100*(min(HOLD_SPREAD)/d_whole - 1):.0f}%")
    P("  of its own closest observed station-keeping distance before the head leaves the crop.")
    P("")
    P("The OTHER axis, which is the one that does bite: BEARING.")
    P(f"  a subject more than {HALF:.0f} deg off boresight is outside the crop entirely "
      f"(scoreboard.MODEL_HALF_FOV_DEG).")
    P("  At range d the crop's half-width on the floor is d*tan = 0.700*d:")
    for d in (1.285, 1.62, 1.94, 2.43, 3.64):
        P(f"    d = {d:.2f} m -> the crop spans +-{d*TAN:.2f} m laterally "
          f"({2*d*TAN:.2f} m wide) at the person's plane")
    P("  2026-09-15-typical-person's own build-time probe has the control cutout at "
      "0.319 at")
    P("  1.80 m / -33.7 deg and calls it 'outside the crop' - that is a BEARING loss, not a")
    P("  vertical-truncation loss, and it happens at a range where the whole body still fits.")
    (D / "tables/geometry_fov.txt").write_text("\n".join(OUT) + "\n")
    P("")
    P(f"wrote {D/'tables/geometry_fov.tsv'} and geometry_fov.txt")
    (D / "tables/geometry_fov.txt").write_text("\n".join(OUT) + "\n")


if __name__ == "__main__":
    main()
