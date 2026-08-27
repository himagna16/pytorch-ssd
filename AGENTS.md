# Project instructions for coding agents

This is a two-person research repo (Sai: training/eval, Grace:
quantization/GAP8 export) on a shared fork. Follow TEAMWORK.md strictly:

1. **Session start**: run `git pull --rebase`, then read `DECISIONS.md`
   and the newest `EXPERIMENTS.md` entry before doing anything else.
2. **Session end**: commit and push everything (`WIP:` prefix if unfinished).
   Never leave local-only commits.
3. Changes to shared contracts (model output layout, losses, dataset
   conventions, file layout) go on a `sai/...` or `grace/...` branch with a
   PR — not straight to `main`.
4. When the user makes a project decision, append it to `DECISIONS.md`.
   Record experiment results in `EXPERIMENTS.md`.
5. Never commit datasets, `*.pth`, or `*.onnx` (gitignored). Never force-push
   `main`. Do not run DORY/GVSOC yet (missing config from David).

Environment setup for a new machine: AGENT_SETUP.md. macOS specifics:
SETUP_MACOS.md. Two venvs sit NEXT to this repo: `../trainenv` (training)
and `../nemoenv` (quantization/export) — use the right one per script.
