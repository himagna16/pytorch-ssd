# Research Progress Record: Sai Maruvada

**Project:** Autonomous person-following nano-drone (Crazyflie + AI-deck GAP8), UT Austin
**Advisor:** Prof. Aloysius Mok
**Role:** Neural network training and evaluation (Role 1), plus simulator integration
**Period covered:** Aug 24 to Sep 10, 2026
**Last updated:** 2026-09-10

## Summary

I joined the team in late August to continue David Liu's honors thesis on
running a person-detection neural network on the drone's 64 mW GAP8
processor. In the first three weeks I:

- rebuilt the full training and quantization toolchain on macOS and fixed
  the bugs that kept it from running outside David's machine;
- trained models that beat David's released model in simulated quantized
  form (peak F1 0.8008 vs 0.789), and a variant that cuts false alarms on
  pets and mannequins by 3x;
- got MinHyuk Park's Crazyflie simulator running on Mac laptops and built a
  closed-loop person follower that passes all five safety and tracking
  tests in simulation;
- found, on Sep 10, that the integer networks we released for the chip
  ignore their input. That withdraws my earlier chip-validation claims, and
  fixing it is now the top priority.

## Live tracker

| Item | Owner | Status | Next step |
|---|---|---|---|
| Fix the chip integer network, whose output is constant | Grace, Sai | Open, top priority | Test each saved ONNX export stage on a laptop and compare with David's working release |
| Withdraw chip-validation claims in docs and resume | Sai | Open | Correct EXPERIMENTS.md, SEP2_MEETING.md, WEEK1_REPORT.md, and resume bullet |
| Simulator demo for Prof. Mok | Sai | To schedule | He offered Tuesday or Thursday after 3:30 pm |
| Progress record for Prof. Mok | Sai | v1 done, this file | Update every session |
| First real AI-deck camera frames, motors off | Oaj, frontend trio, MinHyuk | Planned | Write capture protocol, run session |
| Simulator: chip latency and saved frames | Sai | Planned | Add latency injection and frame saving to the follower |
| Retest "QAT erases confuser gains" | Sai | Planned | Two one-epoch runs with hard-negative mining controlled |

## Results and their status

| Result | Status |
|---|---|
| QAT champion beats David's released model, 0.8008 vs 0.789 peak F1 | Verified in simulated quantized (fake-quant) evaluation; reproduced by Grace. Not verified on the chip |
| Confuser model: animal and mannequin false alarms 24% to 8% | Verified in fake-quant evaluation |
| Reproduced David's GVSOC chip validation of his own app | Verified |
| Our champion and confuser chip apps | **Broken.** The integer network gives one output for all 96 test images; layers 2 to 7 saturate. The earlier "bit-exact" pass compared one image against a reference from the same broken network |
| Release pipeline runs off David's machine, 5 fixes | Runs, but produced the broken networks; root cause under investigation |
| Crazyflie simulator on macOS | Verified |
| Closed-loop person following in simulation, 5 tests | Verified against a simulator ground-truth log. Uses the full-precision model on a laptop, not the chip network |
| "QAT erases the confuser gains" | Confounded: hard-negative mining was off in those runs. Retest planned |

## My contributions

Measured from the team repository: 54 commits of mine across `main` and the
release branch since David's handoff, about 9,200 lines added on `main`.
Repository counts miss teammates' work done outside the repo, listed under
Team context.

- **Toolchain.** Rebuilt training and NEMO quantization environments on
  macOS; fixed Linux-only package pins, a numpy/pycocotools ABI conflict, and
  a NEMO export crash under PyTorch 2.x. Tested and set the team PyTorch
  version so Grace's Intel Mac could join.
- **Models and training.** Reimplemented the thesis's bin-head model from
  its text and replicated its two main claims. Ran the full-COCO training
  campaign, quantization-aware training, and the targeted confuser
  retraining.
- **Evaluation tools.** Drift audit between float and quantized models,
  threshold sweeps, error analysis, confuser-slice metrics. Showed the
  16-image drift audit predicts full-set quantization loss.
- **Deployment pipeline.** Reproduced David's chip-simulator validation and
  made his release pipeline run on other machines: a containerized legacy
  export environment plus four further fixes, including a hardcoded path
  from his machine.
- **Simulator and closed loop.** Ported CrazySim to Apple Silicon, with the
  firmware in a small container. Built person scenes from COCO photos, a
  follower with safety rules, ground-truth logging, and a one-command
  acceptance suite. Fixed five issues found in testing, including macOS
  network limits and a steering sign flip.
- **Team infrastructure.** Team fork and workflow, decision log, setup
  runbooks that let Grace and Oaj reproduce results on three operating
  systems, a firmware decode contract, and meeting reports.

**Methods note.** I developed this work with AI coding assistance, Claude
Code, as the project lead encouraged. I directed the experiments, ran and
checked the results, and made the decisions recorded in DECISIONS.md.

## Team context

- **David Liu:** original thesis, training and release pipeline, handoff
  files.
- **MinHyuk Park:** Crazyflie simulator, drone hardware, AI-deck camera
  firmware.
- **Grace Hao:** quantization lane; independently reproduced the chip
  validation on an Intel Mac; caught a missing-checkpoint bug; running the
  learned-quantization-parameter study; requested drone access.
- **Oaj Saini:** reproduced the setup on Linux and reported three setup
  bugs, which I fixed.
- **Jade Chen, Koa, Calvin Ngu:** flight-control and firmware lane, starting
  with the decode contract.

## Session log

Newest first. One entry per working session.

- **2026-09-10.** Ported the simulator to macOS. Built the closed-loop
  person follower and passed all five tests in simulation. Emailed Prof. Mok
  the results; he asked for a demo, Tuesday or Thursday after 3:30 pm, and
  for this progress record. A planning review then showed the released chip
  networks ignore their input; I verified it and withdrew the chip-
  validation claims. Started this record.
- **2026-09-05.** Simulator walkthrough with MinHyuk. Wrote the simulator
  setup runbook for Oaj.
- **2026-08-29 to 09-01.** Onboarding runbooks for Grace and Oaj and fixes
  for the bugs they found. Sep 2 meeting document, Week 1 report, firmware
  decode contract.
- **2026-08-31.** Ran the confuser model through the release pipeline, now
  known to share the constant-output problem. Tested quantization-aware
  training on the confuser model; that conclusion is now confounded.
- **2026-08-28.** Successor training campaign: QAT champion 0.8008 in
  fake-quant form. Error analysis led to the confuser model. Reproduced
  David's chip validation and made the release pipeline portable.
- **2026-08-27.** Verified David's handoff files. Retrained both models on
  full COCO. Set up the team fork, workflow, and decision log.
- **2026-08-26.** Built the macOS environments with four toolchain fixes.
  First training runs, drift-audit tool, thesis replication. Requested
  missing files from David.
- **2026-08-24.** Joined the team; chose neural network training and
  evaluation.
