# Stage 8.5 integrity-gate failure — recovery runbook

**Agent instructions.** Your user hit `plain_follow handoff integrity check
FAILED` at Stage 8.5 of AGENT_SETUP.md. Cause (fixed upstream Aug 29): the
validation manifest previously referenced a checkpoint OUTSIDE the repo, so
the gate could not pass on any machine but the release machine. The current
`successor-release` branch references the checkpoint in-repo
(`artifacts/successor_qat_ep3_eval.pth`). Recovery is just updating and
re-running:

```bash
cd ~/drone/pytorch_ssd_unstable
git remote -v | grep -q himagna16 || git remote add fork https://github.com/himagna16/pytorch-ssd
git fetch fork successor-release
git checkout successor-release
git reset --hard fork/successor-release
PLAIN_FOLLOW_VERIFY_PYTHON=../nemoenv/bin/python3 bash run_plain_follow_app_val.sh
```

(`reset --hard` is safe here: this worktree holds no local work — if your
user has made local changes in it, stash first and say so.)

**VERIFY**: output ends with
`plain_follow handoff integrity check: PASS` and
`PASS: 'final' matches exactly.`

Then append a dated "Independent reproduction (<user>)" entry to
`pytorch_ssd/EXPERIMENTS.md` on `main` with the machine's platform and the
two PASS lines, commit, push — per TEAMWORK.md.

If it still fails after this: capture the full output plus
`git -C ~/drone/pytorch_ssd_unstable log --oneline -1`, do not debug
further, and send both to Sai.
