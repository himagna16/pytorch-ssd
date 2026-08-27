# Team Workflow — Sai & Grace (backend)

Home repo: **github.com/himagna16/pytorch-ssd** (fork of DavidLiu2/pytorch-ssd).
Mainline branch: **`main`**. David's untouched original is preserved as the
tag `david-original` and upstream remains `DavidLiu2/pytorch-ssd`.

The two rules that matter most:

1. **Never start work on a stale copy. Never end a session unpushed.**
2. **Every real decision gets a line in `DECISIONS.md`.**

Everything else below is detail.

## The session ritual (humans AND coding agents)

**Start of every work session:**

```bash
git pull --rebase
```

Then read (or have your agent read) `DECISIONS.md` and the newest entry in
`EXPERIMENTS.md` — that's how you catch anything your partner changed or
decided since your last session.

**End of every work session:**

```bash
git add -A && git commit -m "<what and why>" && git push
```

Committed-but-unpushed work is invisible to your partner and WILL cause
conflicts. Push even half-done work at session end — a pushed
work-in-progress beats an invisible one. Mark it `WIP:` in the commit
message if it doesn't run yet.

## When to commit straight to main vs. open a PR

**Straight to `main`** (the default for this team): docs, experiment logs,
new tools, training runs, bugfixes, work inside your own role's files.
Commit small and push immediately.

**Branch + pull request** when the change touches the OTHER person's work
or a shared contract — the model's output format (the 14-value head),
loss functions, dataset conventions, file layout, or anything you two
disagree about or haven't discussed. Name the branch `sai/<topic>` or
`grace/<topic>`, push it, open a PR, and let the other person read it
before merging. The PR description is part of the decision record — say
WHY, not just what.

Rule of thumb: if your partner would be surprised to `git pull` and find
it, it should have been a PR.

## DECISIONS.md — the team memory

Any time we choose between approaches ("uniform bin edges until David
confirms his", "threshold 0.60 over 0.45", "skip GPU rental for now"),
add one dated line to `DECISIONS.md`: the decision, the why, and what we
rejected. This is the file that stops "wait, why did we do it this way?"
three weeks from now. Agents: read it at session start; append to it when
the user makes a call; never delete old entries (strike through and add a
new line if a decision is reversed).

## Conflicts

If `git pull --rebase` reports a conflict: your agent can usually resolve
it (both of you mostly touch different files). If the conflict is in a
file you both changed on purpose, that's not a git problem — it's a
missing conversation. Message each other on Discord, agree, then resolve.

Never use `git push --force` on `main`. No exceptions. (Force-pushing your
own `sai/...` / `grace/...` topic branch is fine.)

## What never gets committed

Datasets (`data/`), checkpoints (`*.pth`), ONNX files, venvs — all already
gitignored. Results are shared as numbers/tables in `EXPERIMENTS.md`, and
each person regenerates artifacts locally. If a specific checkpoint must
be shared, use a Drive link in Discord, not git.

## Sending work back to David

When something is polished and general (the NEMO torch-2.x fix, the MPS
patch, plain_follow), we open a pull request from this fork to
`DavidLiu2/pytorch-ssd` so David can review and absorb it. That's a
deliberate, occasional act — day-to-day work just lands on our `main`.

## Cheat sheet

```bash
git pull --rebase                     # session start
git add -A && git commit -m "..."     # commit small, commit often
git push                              # session end, always
git checkout -b sai/some-topic        # only for shared-contract changes
gh pr create --fill                   # open the PR for review
```
