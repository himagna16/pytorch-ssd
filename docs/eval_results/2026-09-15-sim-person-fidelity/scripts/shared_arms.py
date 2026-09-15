#!/usr/bin/env python3
"""ONE scoring path for both fidelity studies.

This file deliberately contains no scoring code. It puts the 2026-09-15 PET
study's `scripts/champion_arms.py` on the path and re-exports it, so that the
person study and the pet study are not "the same method" by inspection - they
are literally the same bytes, loaded from one file on disk. `code_hashes.txt`
in this directory records that file's sha256.

Everything the pet study's module documents applies verbatim:

  float     artifacts/successor_qat_ep3_eval.pth, plain float PyTorch
  fq        artifacts/successor_qat_ep3.pth under nemo.quantize_pact, 8 bit
  chip      model_id_dory.onnx under onnxruntime in doryenv, reached through
            tools/crazysim_macos/perception_backends.ChipPerception
  *_via244  the same arm after first resampling the centre crop to 244x244 -
            THE RESOLUTION-MATCHED CONTROL. `firmware_preprocess` does not
            antialias, so it samples a 244-px render at stride 1.9 and a
            640-px photograph at stride 3.75+. Pairing sim `chip` with real
            `chip_via244` is the apples-to-apples pairing; see
            scripts/control_resolution.py, which proves the no-op on the sim
            side and measures the move on the real side.
"""
import hashlib
import sys
from pathlib import Path

ROOT = Path("/Users/saimaruvada/Downloads/drone/pytorch_ssd")
PET = ROOT / "docs/eval_results/2026-09-15-sim-pet-fidelity/scripts"
CHAMPION_ARMS = PET / "champion_arms.py"

if not CHAMPION_ARMS.is_file():
    raise RuntimeError(f"the pet study's scorer is not where it should be: {CHAMPION_ARMS}")
CHAMPION_ARMS_SHA256 = hashlib.sha256(CHAMPION_ARMS.read_bytes()).hexdigest()

if str(PET) not in sys.path:
    sys.path.insert(0, str(PET))

from champion_arms import Arms, to_input, _crop244  # noqa: E402,F401
from champion_arms import ROOT as CHAMPION_ROOT     # noqa: E402

assert CHAMPION_ROOT == ROOT, (CHAMPION_ROOT, ROOT)

COCO_ROOT = ROOT / "data/coco"
IMG_DIR = COCO_ROOT / "images/val2017"
INSTANCES = COCO_ROOT / "annotations/instances_val2017.json"
KEYPOINTS = COCO_ROOT / "annotations/person_keypoints_val2017.json"

BAR = 0.75          # follow_person.py --vis-enter default, the confirmation bar
EXIT_BAR = 0.45     # follow_person.py --vis-exit default, where the follower lets go

# The simulator's person cutout, used by BOTH person cells of the CORE matrix
# (s15_static_offset and s01_control_moving name the same coco img/ann).
SIM_SOURCE_IMG_ID = 19432
SIM_SOURCE_ANN_ID = 428692

STRATUM_FLAGS = ("whole_upright", "isolated", "wui", "is_sim_source")


def relabel(cohort_rows, real_by_img):
    """Re-derive every cohort frame's stratum flags from real_people.csv.

    The cohort was RENDERED from one edition of the inclusion rule and the rule
    was then tightened (the centre crop cuts horizontally as well as vertically;
    COCO 197870's "whole upright person" is 73 px wide at x 505 of a 640x425
    photograph whose centre crop ends at 532, so the network is shown a bench).
    The render is a superset of any later, stricter stratum, so nothing has to
    be re-rendered - but the flags baked into the render CSV are stale, and
    every analysis must take them from the real table instead. Frames whose
    subject is no longer in any stratum keep their flags at 0 and simply drop
    out of the stratified comparisons.
    """
    out = []
    for r in cohort_rows:
        src = real_by_img.get(r["img_id"])
        if src is None:
            continue
        out.append({**r, **{k: src[k] for k in STRATUM_FLAGS}})
    return out
