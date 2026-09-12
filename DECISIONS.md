# Decision Log

One dated line per decision: what we chose, why, what we rejected.
Newest entries at the top. Never delete entries — supersede them.

- **2026-09-12** — The published cause of the distance failure is WITHDRAWN. The
  Sep 11 suite's "the size head over-reads by 1.6-1.8x" is wrong: the MuJoCo
  groundplane material carries `reflectance="0.2"`, a 20% mirror, so the renderer
  draws subjects 1.5-2.0x too tall and the network reads person-plus-reflection
  as one object. The size head reads real people correctly: mean signed error
  -0.015 over the 2635 COCO val images with a person and -0.007 over the 1475 in
  the follower's own size regime (every subset under-reads), and +0.005 on the
  deployed chip network over a 700-image slice.
  Separately, the follower's control law cannot reach 1.94 m at all - it stops on
  a single argmax bucket-2 frame, whose perfect-head distance is 2.428 m - so the
  M7 gate targeted a distance the code cannot produce. **The Sep 11 M7 results
  characterise a simulator artefact plus an unreachable gate and are not evidence
  about the drone's real distance keeping.** The observed behaviour and every
  verdict are unchanged (still 7 pass / 7 fail); only the explanation is
  withdrawn. Rejected: retraining or re-tuning the size head, which the suite
  appeared to justify and the measurements do not. Evidence:
  `docs/eval_results/2026-09-12-distance/`. OPEN for the team, because each
  belongs to someone else's file and one changes flight behaviour six days before
  the first hardware session: (a) set `reflectance` to 0.0 and rebuild the 18
  scenes, which invalidates every scene on disk and every published simulator
  result including the September baselines; (b) give `size` the soft decode `x`
  already has, or require N consecutive bucket-2 frames before stopping - must be
  flown, not shipped on a desk result; (c) decide whether M7 gates 2.428 m or the
  control law changes, and drop or rename `M7_size_overread_ratio`, which is
  algebraically `d / 1.942` and never measured the size head. None of the three
  had been flown when this entry was written; the predicted effect of the scene
  fix is a render-in-the-loop replay, not a re-fly of the acceptance suite.
  Later the same day: (a) landed in the working tree — `build_scene.py` now defaults to
  `FLOOR_REFLECTANCE = 0.0` and the 18 `scenes_v2` scenes carry `reflectance="0"` — and a
  re-fly is in progress under `docs/eval_results/2026-09-12-mirror-refly/`, still a
  placeholder. So (a) is implemented but UNFLOWN; (b) and (c) remain open.

- **2026-09-12** — Simulator results are reported from a realistic camera and
  the real chip network, not the float model on clean renders. A hard safety
  gate is scored on the numerically **worst** repeat, never the first failing
  one: a printed safety number must not understate what was observed. A cell
  with fewer than two valid flights is INVALID, not passing. Rejected: quoting
  the first failing repeat because it cannot change a verdict — it changes what
  a reader believes the drone did.

- **2026-09-12** — A published evidence folder keeps every flight's record but
  only one representative flight's control log per cell, so it stays a few MB.
  It must therefore be **re-scorable and idempotent**: `scoreboard.py` scores a
  trimmed flight from its stored record, leaves that file untouched, and names
  it on stdout. Rejected: re-deriving every flight from raw logs (it silently
  rewrote 23 good records as invalid and failed every cell), and publishing
  numbers that the folder itself cannot reproduce.

- **2026-09-11** — All three chip candidates (QAT champion, confuser,
  confuser QAT+mining) pass the semantic gates on a 576-image pack and on an
  unbiased 1,000-image check. The confuser is cleared for the chip. OPEN for
  the team: ship the champion (more recall) or a confuser model (about 3x
  fewer false alarms on pets and mannequins). Release decisions use packs of
  500+ images from now on.

- **2026-09-11** — The re-validated QAT champion is the app on
  `successor-release` (all five gates pass). Release summaries decode integer
  outputs with the real output scale; treat any older integer-domain F1 or
  threshold number as invalid. Future QAT fine-tunes of the confuser keep
  hard-negative mining on from epoch 1. Rejected: the old rule "never QAT
  after confuser training", which came from a confounded experiment.

- **2026-09-10** — After the DORY fix, the QAT champion's chip app passes
  all five semantic gates and is the chip candidate again. The confuser
  model is not cleared for the chip: its integer network misses the 90%
  float-agreement bar (88.5%, boundary cases only). Next confuser attempt:
  QAT with hard-negative mining on. Promotion of the champion app waits for
  the output-scale fix so its release summary reports correct numbers.

- **2026-09-10** — DORY must be patched before any code generation
  (`tools/dory_patches/apply.sh`). Root cause of the constant-output chip
  releases: DORY's float-to-uint8 weight cast zeroes negative weights on
  Apple Silicon with NumPy 1.24. Every release must pass
  `export/check_semantic_release_gates.py` before promotion. Rejected:
  moving DORY into an x86 container instead (slower, and it hides the
  undefined cast rather than fixing it).

- **2026-09-10** — Chip releases WITHDRAWN. Both our releases (champion,
  confuser) produce input-independent outputs. Do not flash or fly the
  current `successor-release` app; all chip-validation claims are retracted
  until a release passes semantic gates: distinct outputs across images, no
  layer mostly pinned at its clip limits, integer-vs-float decision agreement
  on 500+ images, and GVSOC exact on several different images. Rejected:
  continuing hardware bring-up on the current app; single-image golden
  checks as proof of correctness.

- **2026-09-10** — Simulator follow gate PASSED on Sai's Mac (Grace's
  requirement before telling Prof. Mok or picking up drones). The deployed
  champion model flies the simulated Crazyflie autonomously: an offset person
  is acquired and held (true heading error 1.1–1.5°), a person swaying ±1.2 m
  is tracked (2.7° average, 7.7° worst, scored against a logged ground truth),
  an empty room is never tracked and the drone never moves, and a frozen
  camera makes it hover then land. Adopted follower settings: track only after
  confidence ≥0.7 on 3 consecutive frames, drop below 0.45; caps 0.3 m/s and
  40°/s; yaw sign −1 (simulator firmware; re-verify on the real drone).
  Rejected: the single-frame 0.55 threshold, which false-tracked 7.8% of an
  empty room and turned the drone 22°.

- **2026-09-10** — Simulator runs on team Macs: CrazySim's MuJoCo backend
  works on Apple Silicon with the firmware in a small arm64 container
  (`tools/crazysim_macos/`). Every teammate can simulate locally; Oaj's
  WSL2/NVIDIA machine remains the option for the Gazebo backend and GPU
  speed. Rejected: routing all sim work through one teammate's machine.
  Rule: restart the sim between flight scripts (firmware locks on landing).

- **2026-08-27 (late night)** — Successor campaign launched to beat David's
  released model (peak F1 0.791 on val2017 visibility). Two runs chained on
  Sai's Mac using DAVID'S stack on the `successor` worktree branch (his
  train.py + MPS patch, flip aug, weighted losses vis2.0/x1.0/size0.3/res0.5,
  hard negatives from epoch 4, visible-fraction 0.6): RUN 1 = warm-start
  fine-tune of his checkpoint (20 ep, lr 3e-4); RUN 2 = from-scratch (30 ep,
  lr 1e-3). Per-epoch checkpoints kept for post-hoc F1 selection (his
  selection metric was follow_score, not F1 — free gains possible).
  Scoreboard = export/sweep_unstable_ckpt.py. QAT fine-tune (his
  --quant-aware-finetune, discovered tonight) reserved as the deployment-
  robustness follow-up on the winner.
- **2026-08-27 (night)** — The deployed output contract is DAVID'S layout:
  14 values = x-bin logits 0-8, **visibility 9**, size buckets 10-13 (signed
  int32 on device). Our reimplementation used vis-last; firmware and all
  future decode code MUST follow David's ordering. Our `plain_follow_net.py`
  stays as-is as an independent replication artifact — it is NOT the deploy
  lineage.
- **2026-08-27 (night)** — Going forward the canonical model/training stack
  is David's quant-native code (`models/quant_native_follow_net.py`,
  `utils/follow_task.py`, his `train.py`) from the `unstable` branch —
  it is the validated deployment lineage, richer loss, and the released
  checkpoint's home. PROPOSAL pending team discussion with Grace: rebase the
  team mainline onto `unstable` (preserved on our fork as `david-unstable`);
  our fixes/tools get re-applied on top. Do NOT flip the base until Grace's
  setup is stable and she agrees — her environment currently follows main's
  docs.
- **2026-08-27** — Team PyTorch pin = **2.2.2** (+ torchvision 0.17.2) on
  ALL machines. Reason: 2.2.2 is the newest release with Intel-Mac builds
  (Grace's 2020 MacBook), and testing showed zero cost: a 2.4.1-trained
  checkpoint produces bit-identical outputs under 2.2.2, and both model
  families export through NEMO to ID identically (hybrid still needs the
  eps-seeding patch on 2.2.2 — same tracer issue as 2.4). Rejected:
  per-person versions (invites works-on-my-machine drift). Revisit only if
  Grace changes hardware.

- **2026-08-27** — Team home repo = the fork `himagna16/pytorch-ssd`,
  mainline `main`, Grace added as collaborator. Rejected: working directly
  on David's repo (no push access, David slow to respond) and a fresh
  private repo (breaks the PR path back to David, no real privacy need).
  David's pristine code preserved as tag `david-original`.
- **2026-08-27** — Team workflow: trunk-based on `main` with
  pull-rebase/push-every-session ritual; PRs only for shared-contract
  changes; decisions logged here. See TEAMWORK.md.
- **2026-08-26** — plain_follow reimplemented from the thesis text with
  **uniform** x-bin edges (9 over [-1,1]) and size buckets (4 over [0,1])
  — David's originals are not public. Revisit when David shares his code;
  if his edges differ, ours must change to match before any GAP8 deploy.
- **2026-08-26** — Follow-family models train on FULL COCO instances
  annotations (keeps true no-person negatives); use train2017 for training
  and val2017 for validation. Val-only smoke runs are for plumbing checks,
  never for quotable metrics (leakage inflates them, ~+0.06 F1 observed).
- **2026-08-26** — Visibility threshold: NOT yet decided. Sweep shows best
  F1 at 0.45 but lowest ghost-follow risk near 0.60; team + firmware side
  should pick the operating point together. Hysteresis (visible >0.55,
  lost <0.45) proposed for the deployed decode.
- **2026-08-26** — No GPU rental for now: models are tiny; MPS on Sai's
  Mac is ~1.6x CPU and full-COCO 10-epoch runs finish in ~1-2 h. Revisit
  if we start hyperparameter sweeps.
- **2026-08-26** — DORY/GVSOC codegen deferred until David provides the
  DORY config template; macOS also can't build doryenv (Linux/Docker
  needed — likely Grace's lane).
