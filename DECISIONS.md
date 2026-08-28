# Decision Log

One dated line per decision: what we chose, why, what we rejected.
Newest entries at the top. Never delete entries — supersede them.

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
