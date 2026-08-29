# Oaj — evaluation & data lane: task runbook

**Agent instructions.** Your user is Oaj (WSL2/Ubuntu setup complete — your
Linux setup report was received; all three runbook defects you found are now
fixed on `main`, with credit). Follow TEAMWORK.md and AGENTS.md: pull
--rebase first, read DECISIONS.md + the latest EXPERIMENTS.md entries, push
at session end. Work through the tasks in order.

## Task 0 — Housekeeping

1. `git pull --rebase` in `~/drone/pytorch_ssd`.
2. Append one dated line to DECISIONS.md: Oaj takes the evaluation-and-data
   lane. Commit, push.
3. Realign torch to the team pin — your environment currently runs
   torch 2.4.1+cpu (from the requirements fallthrough, now fixed in the
   doc). In BOTH venvs:
   `pip install torch==2.2.2 torchvision==0.17.2 --extra-index-url https://download.pytorch.org/whl/cpu`
   then re-verify Stage 2's model forward still prints `OK (2, 14)`.

## Task 1 — Independent reproduction of the headline numbers

The two contender checkpoints are now IN THE REPO on the release branch —
no external files needed:

```bash
cd ~/drone/pytorch_ssd_unstable
git remote -v | grep -q himagna16 || git remote add fork https://github.com/himagna16/pytorch-ssd
git fetch fork successor-release && git checkout successor-release && git reset --hard fork/successor-release
```

Then, from `~/drone/pytorch_ssd` (each sweep takes 10+ minutes on CPU —
run in the background, do not kill early):

```bash
../nemoenv/bin/python export/sweep_fq_ckpt.py --mode qat   --ckpt ../pytorch_ssd_unstable/artifacts/successor_qat_ep3.pth
../nemoenv/bin/python export/sweep_fq_ckpt.py --mode calib --ckpt ../pytorch_ssd_unstable/artifacts/successor_qat_ep3_eval.pth
../nemoenv/bin/python export/sweep_fq_ckpt.py --mode calib --ckpt ../pytorch_ssd_unstable/artifacts/successor_confuser_ep8.pth
```

Expected peaks: ~0.8008 (champion, qat mode) and ~0.7947 (confuser). Flag
any deviation > 0.005. Append a dated "Independent reproduction (Oaj)"
entry to EXPERIMENTS.md with machine specs and the full threshold tables
(the qat-vs-calib pair on the champion also feeds Grace's alpha study —
note both numbers). Commit, push.

## Task 2 — Evaluation pack system

Formalize our ad-hoc analysis slices into versioned packs under
`export/eval_packs/`:

1. `confuser_negatives_val2017.json` — val2017 images with NO person but
   containing COCO categories {16,17,18,19,20,21,22,23,24,25,88}. Use the
   category logic in `export/build_confuser_manifest.py` as the pattern
   (~771 images expected).
2. `tiny_person_val2017.json` and `large_person_val2017.json` —
   visible-person images split at the size_proxy quartiles documented in
   EXPERIMENTS.md ("error anatomy": tiny <0.28, large >0.82), deriving
   size the same way `utils/coco_follow_regression.py` builds follow
   targets.
3. A shared `export/eval_packs/README.md`: how packs are built, the JSON
   shape (`image_ids` + `purpose`), how to add one.
4. A runner (`export/eval_pack_runner.py`, or extend
   `eval_visibility_threshold.py`) so any pack can be evaluated against any
   checkpoint in one command. Prove it: run the confuser pack against both
   contenders — results should be consistent with the 0.083-vs-0.239 story
   in EXPERIMENTS.md. Log the runs, commit, push.

## Task 3 — Real-camera data plan (document only)

Write `docs/real_camera_data_plan.md` (~2 pages): getting frames off the
AI-deck (Bitcraze's WiFi image-streamer example is the known path), capture
session design (target 500+ frames across people/no-person/pet negatives,
varied lighting), labeling approach (propose auto-label with a modern
detector + human verification of visibility/x/size per the repo's
follow-target definitions), storage conventions under `data/real_camera/`
(split by SESSION, not by frame, to avoid leakage), and a fine-tune recipe
sketch (low LR from the shipped model). Push.

## Constraints

Read-only with respect to `models/` and worktree training code (evaluation
lane). Background anything longer than a few minutes. Ask Oaj before
installing software. End the session with everything pushed and a 5-line
summary: reproduction verdict, packs built, plan status.
