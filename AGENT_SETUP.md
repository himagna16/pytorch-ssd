# Agent Setup Runbook — pytorch_ssd backend environment

**For any team member**: paste this whole file (or its raw GitHub URL) to
your coding agent — Claude Code, Codex, or similar — and tell it to follow
it. It sets up the standard team working environment, verified Aug 26–28,
2026 on macOS and mirrored for Linux/WSL. Ask Sai if anything blocks for
more than 15 minutes.

---

**Agent instructions.** You are setting up the model-training and
quantization environment for a Crazyflie nano-drone research project
(UT Austin, Prof. Mok). The codebase trains a person-following CNN in
PyTorch and quantizes it to int8 for a GAP8 microcontroller via
NEMO → ONNX → (later) DORY. Your user owns the quantization/export half
of the project (Role 2).

Work through the stages IN ORDER. Each stage ends with a VERIFY step and
its expected result — do not continue past a failed VERIFY; consult the
error table at the bottom first, and stop and report if it isn't listed.

Ground rules:

- Clone from **Sai's fork, branch `macos-setup`** (not DavidLiu2's repo) —
  the fork carries required fixes: a NEMO/torch-2.x export patch, the
  `plain_follow` model, audit tooling, and these docs.
- Do NOT attempt DORY code generation or GVSOC (`run_all.sh` full pipeline,
  `doryenv`) yet — a required config file is still missing from the repo
  (requested from David). Everything below sets `RUN_DORY=0` territory only.
- Do NOT commit or push datasets, checkpoints (`*.pth`), or ONNX files.
  `.gitignore` already excludes them; keep it that way.
- Ask the user before any system-level install (Homebrew, apt, WSL) — those
  may need their password.

## Stage 0 — Platform gate

Detect the OS and take the matching path through this document:

- **macOS (Apple Silicon or Intel)**: follow the macOS notes. Also read
  `SETUP_MACOS.md` in the repo root once cloned — it is the authority for
  macOS-specific deviations.
- **Linux**: easiest path; the repo's original requirements files mostly
  work as-is. Bonus: a Linux machine can later run the DORY/GVSOC stage
  that macOS cannot — valuable for this user's role.
- **Windows**: do NOT attempt native setup (the toolchain's pinned wheels
  and NEMO tooling are not Windows-compatible). Install **WSL2 with
  Ubuntu 22.04+** (needs the user's consent and a reboot), then follow the
  Linux path inside WSL for everything below.

Also verify: **Python 3.11** available (`python3.11 --version`), `git`,
`curl`, `unzip`, ~25 GB free disk (5 GB minimum if deferring the full
training set).

## Stage 1 — Workspace layout and clone

The scripts assume the repo folder is named `pytorch_ssd` (underscore) and
that virtualenvs sit NEXT TO it, all under a workspace root:

```
drone/                  <- workspace root
├── pytorch_ssd/        <- the repo, RENAMED from pytorch-ssd
├── trainenv/           <- created in Stage 2
└── nemoenv/            <- created in Stage 5
```

```bash
mkdir -p ~/drone && cd ~/drone
git clone https://github.com/himagna16/pytorch-ssd pytorch_ssd   # default branch = main
cd pytorch_ssd
```

**VERIFY**: `git log --oneline -3` shows recent commits mentioning
plain_follow / experiment log; `ls` shows `AGENT_SETUP.md`, `SETUP_MACOS.md`,
`EXPERIMENTS.md`, `models/plain_follow_net.py`.

## Stage 2 — Training environment

macOS (the repo's pins are Linux-only `+cpu` wheels; install plain wheels):

```bash
python3.11 -m venv ../trainenv
../trainenv/bin/pip install torch==2.2.2 torchvision==0.17.2 numpy==1.24.4 \
    pillow==10.4.0 pycocotools==2.0.7 tqdm==4.67.1
```

Linux/WSL:

```bash
python3.11 -m venv ../trainenv
../trainenv/bin/pip install -r requirements_trainenv.txt || \
../trainenv/bin/pip install torch==2.2.2 torchvision==0.17.2 numpy==1.24.4 \
    pillow==10.4.0 pycocotools==2.0.7 tqdm==4.67.1
```

**VERIFY** (from inside `pytorch_ssd/`):

```bash
../trainenv/bin/python -c "
import torch
from models.plain_follow_net import PlainFollowNet
m = PlainFollowNet(); out = m(torch.randn(2,1,128,128))
print('OK', tuple(out.shape), 'device_backends:', torch.cuda.is_available(), torch.backends.mps.is_available())"
```

Expected: `OK (2, 14) ...` — a 14-value output per image
(9 x-position bins + 4 size buckets + 1 visibility logit).

## Stage 3 — Dataset (start small: val2017, ~1 GB)

```bash
mkdir -p data/coco/images && cd data/coco
curl -LO http://images.cocodataset.org/zips/val2017.zip
curl -LO http://images.cocodataset.org/annotations/annotations_trainval2017.zip
unzip -q val2017.zip -d images/ && unzip -q annotations_trainval2017.zip
rm val2017.zip annotations_trainval2017.zip && cd ../..
```

The full training set (`train2017.zip`, 19 GB) is only needed for real
training runs — defer it unless the user asks.

**VERIFY**:

```bash
../trainenv/bin/python -c "
from utils.coco_follow_regression import COCOFollowRegressionDataset
from utils.transforms import get_val_transforms
ds = COCOFollowRegressionDataset(root='data/coco/images/val2017',
    ann_file='data/coco/annotations/instances_val2017.json',
    transforms=get_val_transforms('hybrid_follow', input_channels=1))
img, t = ds[0]; print('OK', len(ds), tuple(img.shape), t['follow_target'])"
```

Expected: `OK 5000 (1, 128, 128) tensor([...])`.

## Stage 4 — Smoke training run (~3–6 min)

From the **workspace root** (`~/drone`) — the script resolves data paths
from there:

```bash
cd ~/drone/pytorch_ssd
../trainenv/bin/python train.py --model-type plain_follow \
  --data_root pytorch_ssd/data/coco/images/val2017 \
  --train_ann pytorch_ssd/data/coco/annotations/instances_val2017.json \
  --val_root pytorch_ssd/data/coco/images/val2017 \
  --val_ann pytorch_ssd/data/coco/annotations/instances_val2017.json \
  --epochs 1 --batch_size 16 --num_workers 4 --output_dir training/smoke_test
```

**VERIFY**: prints `Training device: ...` (mps on Apple Silicon, cuda with
an NVIDIA GPU, else cpu), a progress bar reaching 313/313, a
`Val visibility @ 0.50:` line (F1 anywhere in 0.2–0.6 is normal for 1
epoch), and `Saved checkpoint ...`. This smoke run trains and validates on
the same 5k images — fine for plumbing verification, meaningless as a
quality number.

## Stage 5 — Quantization environment (NEMO)

```bash
cd ~/drone/pytorch_ssd
python3.11 -m venv ../nemoenv
../nemoenv/bin/pip install -r requirements_nemoenv.txt
../nemoenv/bin/pip install torch==2.2.2 torchvision==0.17.2 onnxruntime==1.19.2
```

macOS only — pycocotools in this env ships a wheel built against the wrong
numpy and dies with "numpy.dtype size changed"; preempt it:

```bash
../nemoenv/bin/pip install cython numpy==1.26.4
../nemoenv/bin/pip install --no-cache-dir --no-build-isolation \
    --force-reinstall --no-deps --no-binary pycocotools pycocotools==2.0.7
```

(`numpy==1.26.4` and `--no-deps` are load-bearing: without them the rebuild
pulls numpy 2.x, and torch 2.2.2 fails to import under numpy 2.)

**VERIFY**: quantize and export a random-weight model end to end:

```bash
mkdir -p export/plain_follow
../nemoenv/bin/python -c "
import torch; from models.plain_follow_net import PlainFollowNet
torch.save({'model_type':'plain_follow','height':128,'width':128,
 'input_channels':1,'state_dict':PlainFollowNet().state_dict()},
 'export/plain_follow/bootstrap_random.pth'); print('bootstrap written')"
../nemoenv/bin/python export_nemo_quant.py --model-type plain_follow \
  --ckpt export/plain_follow/bootstrap_random.pth \
  --out export/plain_follow/smoke_quant.onnx --height 128 --width 128 \
  --input-channels 1 --stage id \
  --stage-report export/plain_follow/smoke_stage.txt \
  --bits 8 --eps-in 0.00392156862745098 --force-cpu
```

Expected: `Fused 9 Conv-BN groups`, `Final exported stage: ID (requested:
ID)`, `Done.` — with NO warnings about `eps_in_list` (plain_follow has no
residual adds; if you export `--model-type hybrid_follow` instead, ONE
warning about seeding 8 add-modules is EXPECTED and correct — that is the
fork's compatibility patch working, not an error).

## Stage 6 — Drift audit (the project's core measurement)

This compares the normal (FP) and fake-quantized (FQ) model on real images
— the "semantic drift" measurement the whole thesis is about:

```bash
../nemoenv/bin/python export/compare_fp_fq_torch.py \
  --model-type plain_follow \
  --ckpt training/smoke_test/plain_follow_best_visibility.pth \
  --images-root data/coco/images/val2017 \
  --ann data/coco/annotations/instances_val2017.json \
  --num-person 10 --num-noperson 6 --calib-batches 32
```

**VERIFY**: a 16-row table plus a summary block reporting `decoded x-bin
preserved exactly: N/16`, size bucket and visibility agreement, and logit
MAE. Any N values are fine on a 1-epoch model — a printed table means the
entire quantization measurement path works.

**Setup is complete at this point.** Report to the user: platform, device
(cpu/mps/cuda), and the Stage 4/6 outputs.

## Stage 7 — Current-work context (David's handoff, Aug 27+)

David (the project's originator) published his full reproduction material on
the upstream `unstable` branch; it is preserved on this fork as
`david-unstable` and is where the CANONICAL model/training code now lives
(`models/quant_native_follow_net.py`, `utils/follow_task.py`, his `train.py`).
Mount it as a sibling worktree — several `export/*_unstable_*.py` tools
expect it at `../pytorch_ssd_unstable`:

```bash
cd ~/drone/pytorch_ssd
git fetch fork david-unstable 2>/dev/null || git fetch origin david-unstable
git worktree add ../pytorch_ssd_unstable david-unstable
ln -s ../../pytorch_ssd/data/coco ../pytorch_ssd_unstable/data/coco
```

**VERIFY**: `../trainenv/bin/python ../pytorch_ssd_unstable/tools/verify_plain_follow_handoff.py`
run from inside `../pytorch_ssd_unstable` prints
`plain_follow handoff integrity check: PASS`.

Two facts every new member must know (details in DECISIONS.md):

- The deployed 14-value output contract is x-bin logits 0-8, **visibility 9**,
  size buckets 10-13. This repo's `models/plain_follow_net.py` is an earlier
  independent replication with a DIFFERENT (vis-last) layout — it is a study
  artifact, not the deploy lineage.
- A private data ZIP (rep16 diagnostic images, `data/rep_images` calibration
  set) is NOT in git — ask Sai for `DroneRS_private_data_handoff_2026-08-26.zip`
  and unzip it at the worktree root. Env setup and training do NOT need it;
  the cross-audit tools do.

## After setup — Role 2 on-ramp (do only if the user asks)

1. Read `EXPERIMENTS.md` (current results) and `docs/hybrid_follow_gap8/`
   (the deployment patch history — Role 2's inheritance).
2. The next Role-2 frontier is DORY code generation + GVSOC simulation.
   It needs: a Linux environment (native/WSL/Docker), the DORY repo, and a
   config template David has not yet shared. On Linux/WSL you may install
   Docker and pull the AI-deck build image in preparation, but do not
   attempt codegen until the config arrives.
3. Useful background: NEMO stages are FP → FQ → QD → ID (float →
   fake-quantized → quantized-deployable → integer-deployable). The repo's
   export goes checkpoint → NEMO ID → ONNX → onnxsim.

## Error table

| Symptom | Cause → fix |
|---|---|
| `pip` finds no `torch==2.4.1+cpu` | Linux-only pin on macOS → install plain `torch==2.4.1` (Stage 2 macOS block) |
| `numpy.dtype size changed` importing pycocotools | wheel/numpy mismatch → rebuild pycocotools from source (Stage 5 macOS block) |
| torch fails to import after pycocotools rebuild (log mentions NumPy 2) | rebuild upgraded numpy to 2.x → `pip install numpy==1.26.4`, redo the rebuild with `--no-deps` |
| `run_all.sh` syntax error near `^^` | macOS bash 3.2 → `brew install bash`, run `bash run_all.sh` (but full run_all needs DORY — avoid for now) |
| `ValueError: max() arg is an empty sequence` in NEMO export | you are NOT on the fork's `macos-setup` branch → re-clone per Stage 1 |
| `stage1.0.add is not a module name` warnings then seeding message | expected on hybrid_follow exports; not an error |
| `command not found: timeout` (macOS) | GNU coreutils absent → don't use `timeout`; run commands plainly |
| DataLoader crashes / OOM | reduce `--num_workers` to 2 or 0, `--batch_size` to 8 |
| SSL errors downloading COCO | retry with `curl -LO --retry 5`; the mirrors are plain HTTP |
| MPS op-not-supported error during training | run with env `PYTORCH_ENABLE_MPS_FALLBACK=1` and report which op |

## Success checklist

- [ ] Stage 2: model forward pass prints `OK (2, 14)`
- [ ] Stage 3: dataset prints `OK 5000 (1, 128, 128)`
- [ ] Stage 4: 1-epoch training completes, checkpoint saved
- [ ] Stage 5: `Final exported stage: ID` on the bootstrap export
- [ ] Stage 6: drift audit prints the 16-image table and summary
