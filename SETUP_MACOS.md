# macOS Setup Notes (Apple Silicon)

Working setup as of Aug 26, 2026 (Sai). Mirrors David's sibling-folder layout.
Linux users: follow the original requirements files instead; the deltas below
are macOS-specific.

## Workspace layout

Scripts assume the repo folder is named `pytorch_ssd` (underscore, not the
GitHub hyphen name) and that venvs/repos sit NEXT TO it:

```
drone/                      <- workspace root; run scripts from here
├── pytorch_ssd/            <- this repo (renamed from pytorch-ssd)
├── trainenv/               <- training venv
├── nemoenv/                <- quantization/export venv
├── doryenv/                <- NOT usable on macOS (CUDA pins) — see below
├── dory/                   <- DORY repo clone (not needed until codegen)
└── crazyflie_ssd/          <- runtime wrapper (still needs to come from David)
```

`train.py` resolves data paths from the WORKSPACE ROOT, so pass paths like
`pytorch_ssd/data/coco/...` even when invoking from inside the repo.

## Environment creation (Python 3.11)

```bash
# trainenv — requirements_trainenv.txt pins "+cpu" wheels that only exist on
# Linux; install the plain macOS wheels instead (same versions):
python3.11 -m venv ../trainenv
../trainenv/bin/pip install torch==2.4.1 torchvision==0.19.1 numpy==1.24.4 \
    pillow==10.4.0 pycocotools==2.0.7 tqdm==4.67.1

# nemoenv — requirements file works as-is, BUT pin torch 2.4.1 afterward to
# match doryenv's pin (pip otherwise resolves 2.6):
python3.11 -m venv ../nemoenv
../nemoenv/bin/pip install -r requirements_nemoenv.txt
../nemoenv/bin/pip install torch==2.4.1 torchvision==0.19.1 onnxruntime==1.19.2
```

## Dataset (COCO val2017 to start; train2017 is 19 GB, get it later)

```bash
mkdir -p data/coco/images && cd data/coco
curl -LO http://images.cocodataset.org/zips/val2017.zip
curl -LO http://images.cocodataset.org/annotations/annotations_trainval2017.zip
unzip -q val2017.zip -d images/ && unzip -q annotations_trainval2017.zip
```

## Known macOS issues and fixes

0. **doryenv cannot be built on macOS** — `requirements_doryenv.txt` pins
   `nvidia-*` CUDA packages and old TensorFlow (Linux-only wheels). Run the
   pipeline with `RUN_DORY=0`; DORY codegen + GVSOC need a Linux box or Docker.
2. **`run_all.sh` needs bash ≥ 4** (`${VAR^^}` syntax); macOS ships bash 3.2.
   `brew install bash`, then invoke as `bash run_all.sh ...` (not `./run_all.sh`).
3. **pycocotools in nemoenv**: the prebuilt wheel is compiled against a
   different numpy than the env and dies with "numpy.dtype size changed".
   Fix (also drags numpy to 2.4.x, which NEMO export tolerates fine):
   `pip install cython && pip install --no-cache-dir --no-build-isolation \
    --force-reinstall --no-binary pycocotools pycocotools==2.0.7`
4. **Standalone scripts that call `nemo.transform.quantize_pact` must first
   call `patch_model_to_graph_compat()`** (import from `export_nemo_quant`) —
   NEMO passes kwargs removed from modern torch.onnx internals.
5. **NEMO export crashed at `PACT_IntegerAdd` with torch 2.x**
   (`ValueError: max() arg is an empty sequence`): the nemo-graph tracer fails
   to resolve the residual-add module names, so their `eps_in_list` stays
   empty. Fixed on this branch (`macos-setup`) in `export_nemo_quant.py` by
   seeding empty lists with the uniform input eps just before ONNX export.
   Open question for David: his successful runs likely used the
   Python 3.8 + torch 1.10.2 branch of the requirements, where the tracer
   resolves names natively (repo has cpython-38 .pyc files).

## Verified working (Aug 26, random-init smoke)

```bash
# from the pytorch_ssd folder, nemoenv python:
../nemoenv/bin/python export_nemo_quant.py --model-type hybrid_follow \
  --ckpt export/hybrid_follow/bootstrap_hybrid_follow_random.pth \
  --out export/hybrid_follow/smoke_quant.onnx --height 128 --width 128 \
  --input-channels 1 --stage id --stage-report export/hybrid_follow/smoke_stage.txt \
  --bits 8 --eps-in 0.00392156862745098 --force-cpu
../nemoenv/bin/python -m onnxsim export/hybrid_follow/smoke_quant.onnx \
  export/hybrid_follow/smoke_quant_sim.onnx --skip-optimization
```

Result: `Final exported stage: ID`, simplified ONNX ~1.6 MB.
Training: `train.py --model-type hybrid_follow` runs on CPU (the script only
knows CUDA-or-CPU; MPS support would be a small patch).

## Still missing from the public repo (requested from David)

- `crazyflie_ssd/` runtime wrapper
- trained checkpoints (`*.pth`) and reference ONNX exports
- `plain_follow` / `dronet_lite_follow` model code (xbin9_size_bucket4 head)
- `dory_examples/config_files/config_person_ssd.json` (DORY config template)
- `nanocockpit` reference tree
- rep16 diagnostic image set + calibration image sets
