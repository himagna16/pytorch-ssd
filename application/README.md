# Active plain_follow GAP8 application

This is the handoff-ready DORY application for the current `plain_follow`
model (`1 x 128 x 128` grayscale input, 14-value quantized follow head).

The application was generated from the cleaned DORY graph produced by the
canonical plain-follow release flow, patched with the required int64 GAP8
requantization helpers, and validated in GVSOC against the nonzero golden
tensor in `validation/output.txt`.

`validation/manifest.json` records the checkpoint, key artifact hashes, Docker
image digest, and GVSOC result used for this handoff build. The exact checkpoint
is bundled at `../artifacts/plain_follow_best_follow_score.pth`.

From `pytorch_ssd`, rebuild and validate the shipped app with:

```bash
bash ./run_plain_follow_app_val.sh
```

`src/main.c` is DORY's generated standalone harness. The validation command
temporarily substitutes `aideck_val_main_plain_follow.c` in the Docker copy;
it does not modify this source directory.

To regenerate and promote a new active app after changing the model, run the
full production wrapper:

```bash
bash ./run_plain_follow.sh --output-dir logs/plain_follow_prod --overwrite
```

Promotion occurs only after the generated app passes the GVSOC tensor gate.
The production checkpoint is included, but COCO and the local validation-image
packs remain intentionally ignored by Git. Reacquire those datasets before a
full export regeneration; they are not required to build and run this shipped
generated application.
