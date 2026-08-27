# Collaborator Reproduction Handoff

Updated: 2026-08-26

Use the `unstable` branch. The validated plain-follow deployment baseline starts
at commit `b11e9da9b41224bb73f59407305236888f40951b`; later commits only add the
reproduction material described here.

## Requested Material

### 1. Crazyflie runtime wrapper

The wrapper is a separate public repository:

- <https://github.com/DavidLiu2/crazyflie-ssd>
- known local/published revision: `4a03846`
- runtime configuration: `app_config.h`
- preprocessing: `src/preprocess.c` and `inc/preprocess.h`
- postprocessing: `src/ssd_postprocess.c` and `inc/ssd_postprocess.h`
- generated network: `generated/`

The `crazyflie-ssd` generated tree is the historical live-camera wrapper. The
GVSOC-validated plain-follow network is the `application/` directory in this
repository. Do not assume the historical wrapper's output contract matches the
current 14-value plain-follow contract without adapting it.

### 2. Checkpoints, ONNX references, and golden outputs

Production plain-follow:

- `artifacts/plain_follow_best_follow_score.pth`
- `artifacts/handoff_2026_08/onnx/plain_follow_quant_sim.onnx`
- `artifacts/handoff_2026_08/onnx/plain_follow_dory.onnx`
- `artifacts/handoff_2026_08/golden/plain_follow_output.txt`
- `application/validation/output.txt`
- `application/validation/manifest.json`

Historical hybrid-follow:

- `artifacts/handoff_2026_08/checkpoints/hybrid_follow_best_visibility.pth`
- `artifacts/handoff_2026_08/checkpoints/hybrid_follow_best_follow_score.pth`
- `artifacts/handoff_2026_08/onnx/hybrid_follow_quant_sim.onnx`
- `artifacts/handoff_2026_08/onnx/hybrid_follow_dory.onnx`
- `artifacts/handoff_2026_08/golden/hybrid_follow_output.txt`

`artifacts/handoff_2026_08/MANIFEST.sha256` authenticates the added binary
artifacts. The application-level validation manifest separately authenticates
the promoted plain-follow checkpoint, input, generated sources, Docker image,
and golden output.

### 3. Plain-follow and Dronet-lite-follow model/training code

The requested `xbin9_size_bucket4` implementation is already in this repository:

- `models/quant_native_follow_net.py`: both architectures
- `models/follow_model_factory.py`: model/head construction
- `utils/follow_task.py`: targets, loss, output contract, and decoding
- `train.py`: training entry point
- `run_plain_follow.sh`: production plain-follow release pipeline
- `docs/quant_native_follow/`: model, training, export, and validation notes
- `export/plain_follow/` and `export/dronet_lite_follow/`: checked-in generated
  outputs that are not excluded by `.gitignore`

The deployed output has 14 signed `int32` values: x-bin logits at indices 0-8,
visibility at index 9, and size-bucket logits at indices 10-13.

### 4. DORY configuration template

The template is now repo-local at:

`dory_configs/config_person_ssd.json`

`run_all.sh` defaults to that path and writes the model-specific absolute ONNX
path into the generated runtime config. A sibling `dory_examples` checkout is
no longer needed just to obtain this file. The DORY source checkout itself is
still expected at `../dory` unless `DORY_ROOT` is set.

### 5. Representative and calibration images

These remain outside Git because they are COCO-derived data and because the
repository intentionally ignores `data/`, `logs/`, and `training/`. The private
ZIP supplied with this handoff restores:

- `data/rep_images/`: NEMO calibration images
- `logs/hybrid_follow_val/1_real_image_validation/input_sets/representative16_20260324/`:
  the 16-image diagnostic set
- `training/hybrid_follow/checkpoint_eval_best_follow_score_20260324_152203/`:
  the available checkpoint diagnostic reports and overlays

There are no surviving directories literally named `eval_epoch_*` in the local
tree. The checkpoint-evaluation directory above is the retained equivalent.
COCO itself is not included; download the official 2017 validation images and
annotations and place them under `data/coco/` as documented in the main README.

### 6. Nanocockpit

Nanocockpit is public; use the upstream tree instead of copying its 349 MB Git
checkout into this repository:

- <https://github.com/idsia-robotics/nanocockpit>
- revision used locally: `5065a5e`

## Known-Good NEMO Environment

The originating `nemoenv` is the legacy environment, not the Torch 2.x branch:

- Python `3.8.10`
- PyTorch `1.10.2` (local wheel reports `1.10.2+cu102`)
- Torchvision `0.11.3`
- pytorch-nemo `0.0.8`, repository commit
  `5ea3338ae172f96e996bdf75a5dacdf795282929`
- ONNX `1.17.0`
- ONNX Runtime `1.16.3`
- ONNX Simplifier `0.4.36`
- NumPy `1.24.4`

The dependency pins are in `requirements_nemoenv.txt`. Use Python 3.8 for exact
reproduction. The Python 3.9+/Torch 2.x clauses are a compatibility path, not
the environment that produced the validated deployment. The residual-add
tracer failure seen with Torch 2.4 is therefore outside the known-good stack.

## Known-Good GVSOC Container

The general validation script defaults to `bitcraze/aideck`, but an unqualified
tag can move. The validated plain-follow application records and uses:

`bitcraze/aideck@sha256:038197df9cb86ccf8e6649e93dd0cf23781830e136288523983768918851633e`

The local image ID was
`sha256:9654f385dd600e7af7f56e1d2f3193e5edd52952b4a7c89f07640ccd62a3d58d`
and its image creation timestamp was `2024-05-31T08:13:19Z`. For the validated
release, run `bash run_plain_follow_app_val.sh`; it reads the immutable digest
from `application/validation/manifest.json`. The older `run_val.sh aideck` path
defaults to the mutable tag unless `AIDECK_IMAGE` is set explicitly.

## Fast Verification

No Docker is needed for the integrity gate:

```bash
git switch unstable
python3 tools/verify_plain_follow_handoff.py
```

With Docker/GVSOC:

```bash
bash run_plain_follow_app_val.sh
```

The expected final tensor is 14 values and all nine generated layer checks must
match. See `application/README.md` and `application/validation/manifest.json`
for the exact contract.
