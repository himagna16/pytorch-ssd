# pytorch_ssd

This repository contains the model-development, quantization, DORY codegen,
and GAP8 validation path for the DroneRS person-following model.

## Handoff Status

The active deployment model is `plain_follow`, not the older SSD or
`hybrid_follow` experiments:

- input: true grayscale `1 x 128 x 128`
- model: `plain_follow`
- head: `xbin9_size_bucket4`
- output: 14 signed integer values
- active generated GAP8 app: `application/`
- canonical release command: `bash ./run_plain_follow.sh`
- shipped-app validation command: `bash ./run_plain_follow_app_val.sh`

The active app in this handoff change includes the required int64 BN/requant runtime fix.
On 2026-08-22 it was rebuilt in the AI-Deck Docker environment and passed
GVSOC with an exact nonzero final tensor match:

```text
4632 13262 4633 -2422 -3479 -5390 2962 -1854 -11170 5303 -7980 3540 4466 -43
```

All nine generated layers also have an exact layer-by-layer match against the
DORY-semantic golden tensors. GVSOC validates the generated network with a
staged image; it does not prove that the separate live-camera Crazyflie shell
is complete.

## Validate The Shipped Application

Docker must be available. From this directory run:

```bash
bash ./run_plain_follow_app_val.sh
```

The wrapper first verifies the bundled checkpoint, generated sources, input,
and golden-output hashes. It then builds `application/` for `platform=gvsoc`,
substitutes the plain-follow validation main only in the Docker copy, runs
inference, and compares the final 14-value tensor with
`application/validation/output.txt`. It uses the pinned AI-Deck image digest
from the validation manifest and removes the one-shot validation container on
exit. Set `KEEP_VALIDATION_CONTAINER=1` to retain a newly created container.

For an integrity-only check that does not require Docker:

```bash
python3 tools/verify_plain_follow_handoff.py
```

## Regenerate A Release

The dedicated production flow is:

```bash
bash ./run_plain_follow.sh \
  --output-dir logs/plain_follow_prod \
  --overwrite
```

It performs calibration-set construction, float validation, NEMO export,
DORY cleanup and semantic validation, app generation, the int64 GAP8 runtime
patch, layer/final-tensor GVSOC checks, and release-summary generation. After
GVSOC passes, it promotes the verified generated app to `application/`.

For a faster development smoke run:

```bash
bash ./run_plain_follow.sh \
  --output-dir logs/plain_follow_prod_smoke \
  --calib-target-count 4 \
  --calib-max-images 32 \
  --expanded-pack-extra-count 1 \
  --expanded-pack-max-images 32 \
  --overwrite
```

Use `--skip-application-promotion` if a validation run should not replace the
active app. `--skip-gvsoc` also prevents promotion because a simulated runtime
pass is the release gate.

## Source Map

- `docs/collaborator_handoff_2026_08.md`: reproduction inventory, external
  repository links, environment pins, and private-data bundle layout.
- `artifacts/plain_follow_best_follow_score.pth`: bundled handoff checkpoint
  and default checkpoint used by the release flow.
- `training/plain_follow/plain_follow_best_follow_score.pth`: ignored local
  training copy of the same checkpoint on the originating machine.
- `models/quant_native_follow_net.py`: deployed model architecture.
- `utils/follow_task.py`: output contract, loss, and decode logic.
- `nemo/`: NEMO quantization/export implementation.
- `export/run_plain_follow_release.py`: canonical production driver.
- `export/dory_semantic_follow_inference.py`: deployment-semantics simulator.
- `tools/patch_gap8_bn_quant_int64.py`: generated runtime overflow fix.
- `tools/run_aideck_val_impl.sh`: Docker/GVSOC build and tensor gate.
- `application/`: active generated GAP8 source and weights.
- `docs/quant_native_follow/`: design and validation notes.
- `docs/hybrid_follow_gap8/`: historical hybrid-follow investigation.
- `run_all.sh` and `run_val.sh`: older/general entry points, primarily useful
  for the historical hybrid-follow path.

## Handoff Caveats

Git intentionally ignores `training/`, `data/`, and `logs/`. This handoff
explicitly includes the small production checkpoint under `artifacts/`, plus
the generated app and its golden tensor. A clone can therefore integrity-check,
build, and simulate the shipped application without recovering files from the
originating machine. Full regeneration still requires COCO val2017 and the
representative/hard-case image sets described by the release command; those
datasets and verbose release logs are not committed. The checkpoint hash, key
generated-app hashes, Docker image digest, and GVSOC result are recorded in
`application/validation/manifest.json`.

The sibling `crazyflie_ssd` repository is a different layer of the system. Its
camera/runtime shell still documents incomplete postprocessing and an older
output contract. Treat the GVSOC-validated app here as the working generated
network artifact; live-camera/flight integration remains separate work.
