# Project instructions for coding agents

This is a research repo on a shared fork. Sai owns training/eval and, since
2026-10-01, the quantization/GAP8 export lane too: Grace (who held it) is treated
as off the team (DECISIONS.md 2026-10-01), so nothing waits on her. Follow
TEAMWORK.md strictly:

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
   `main`. DORY/GVSOC run fine now (David's config arrived Aug 27): apply
   `tools/dory_patches/` before any code generation, and run
   `export/check_semantic_release_gates.py` on every release. Release code
   lives on `successor-release` (checkout: `../pytorch_ssd_unstable`); never
   let a validation release promote over `application/`
   (`--skip-application-promotion`).
6. Nothing ever flashes a real drone or pushes `../crazyflie_ssd` (David's
   repo) without Sai's explicit OK in that session.

Environment setup for a new machine: AGENT_SETUP.md. macOS specifics:
SETUP_MACOS.md. Two venvs sit NEXT to this repo: `../trainenv` (training)
and `../nemoenv` (quantization/export) — use the right one per script.
