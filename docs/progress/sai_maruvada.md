# Research Progress Record: Sai Maruvada

**Project:** Autonomous person-following nano-drone (Crazyflie + AI-deck GAP8), UT Austin
**Advisor:** Prof. Aloysius Mok
**Role:** Neural network training and evaluation (Role 1), plus simulator integration
**Period covered:** Aug 24 to Sep 11, 2026
**Last updated:** 2026-09-11

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
  ignore their input, withdrew my earlier chip-validation claims, and traced
  the cause the same day to a platform bug in the DORY code generator on
  Apple Silicon. After the fix, the QAT champion's chip network passes all
  five new release checks, including the chip simulator on five images, and
  it is now the team's validated chip app.

## Live tracker

| Item | Owner | Status | Next step |
|---|---|---|---|
| Fix the chip integer network, whose output is constant | Grace, Sai | Done Sep 11: champion app promoted, all 5 gates pass | None |
| 8-core chip build | Sai | Verified on the chip simulator: bit-exact, 154 ms to 23 ms per inference; app rebuilt with DORY fixes 0002/0003 | Use in the drone firmware |
| Put the champion network into the drone firmware | Sai, then frontend trio | Done in simulation: local branch compiles; six independently verified safety rounds; delivered as a bundle with a hand-off (docs/firmware_integration/) | Frontend trio writes the flight-controller handler and runs the bench test |
| Output-scale reporting bug in the release pipeline | Sai | Done Sep 11 | None |
| Confuser model on the chip | Sai | Cleared: passes all gates on a 576-image pack and 93-95% agreement on 1,000 random images | Team picks champion vs confuser |
| Confuser with QAT and hard-negative mining (3 epochs) | Sai | Epoch 2 passes the chip gates, but on the chip it matches the plain confuser: the release discards the learned QAT ranges | Implement the preserve-QAT-ranges release option (Grace's design) |
| Repeatable training | Sai | Done Sep 11: --seed option, tested (identical runs) | Use 3+ seeded repeats before reporting |
| Semantic release gates, so this cannot recur | Sai | Done Sep 10 | Run on every release |
| Withdraw chip-validation claims in docs and resume | Sai | Done Sep 10 | None |
| Tested C decoder for the firmware team | Sai | Done Sep 10 | Frontend trio builds against it |
| Simulator demo for Prof. Mok | Sai | Ready: one-command demo, rehearsed 7 times; recorded video can be sent before the live demo | Send the video, then demo live on the day he picks |
| Flight-controller software (drone side) | Sai | Written and flying in simulation; passes an independent safety review | Bench test on real hardware |
| Progress record for Prof. Mok | Sai | Kept current, this file | Update every session |
| Progress report email for Prof. Mok | Sai | Sent Sep 11; Grace reviewed and agreed with her line | Await his reply on the demo slot and research credit |
| First real AI-deck camera frames, motors off | Oaj, frontend trio, MinHyuk | Protocol and scoring tool written; in review | Schedule the capture session |
| Simulator: chip latency and saved frames | Sai | Built and flight-tested; in code review | Commit after review |
| Retest "QAT erases confuser gains" | Sai | Done Sep 11: overturned | None |

## Results and their status

| Result | Status |
|---|---|
| QAT champion beats David's released model, 0.8008 vs 0.789 peak F1 | Verified in simulated quantized (fake-quant) evaluation; reproduced by Grace. Not verified on the chip |
| Confuser model: animal and mannequin false alarms 24% to 8% | Verified in fake-quant evaluation |
| Reproduced David's GVSOC chip validation of his own app | Verified |
| Our Aug 28 and Aug 31 chip apps | **Were broken.** The integer network gave one output for all 96 test images: the DORY code generator turned every negative weight into 0 on Apple Silicon, and the old check compared the chip against a reference built from the same corrupted weights |
| Champion chip app after the fix | **Verified:** distinct output for all 96 images; exact on the chip simulator for 5 images, agreeing with an independent runtime; 94.8% visibility agreement with the float model |
| Confuser chip app after the fix | Runs correctly, but agrees with its float model on only 88.5% of visibility calls (bar 90%), all near the decision boundary |
| Quantized export of our models | Verified healthy: every exported stage gives distinct outputs under an independent runtime |
| Release pipeline runs off David's machine, 5 fixes | Runs; needs the DORY patch on Apple Silicon before it produces valid chip apps |
| Semantic release gates | Verified: both old releases fail all five checks, David's app passes the weights check, and a synthetic healthy release passes all five |
| C decoder for the firmware team | Verified against the Python decode on 14,579 checks; catches all 7 deliberate bugs in a mutation test |
| Follower at the chip's speed, 6.5 Hz with 153 ms delay | Verified in simulation: 3.1 degrees mean heading error vs 2.7 at full speed, no oscillation, empty room still 0 tracking |
| Crazyflie simulator on macOS | Verified |
| Closed-loop person following in simulation, 5 tests | Verified against a simulator ground-truth log. Uses the full-precision model on a laptop, not the chip network |
| "QAT erases the confuser gains" | **Overturned.** One epoch without hard-negative mining, and without QAT, raises pet and mannequin false alarms from 8.3% to 26.3%. QAT with mining keeps them at 12.2% (baseline 23.9%). Mining, not QAT, was the missing piece |
| Integer-network accuracy in release reports | Now correct: the pipeline had decoded chip outputs 6.6x too small. Champion integer F1 0.837 vs 0.815 for the float model |
| Chip networks vs float models, 1,000 random images | **Verified:** 93-96% visibility agreement for all three candidates, about 1 confident contradiction per 1,000 images, no measurable F1 loss. Champion detects more people; confuser models false-alarm about 3x less on pets |
| 8-core chip build | **Verified on the chip simulator:** identical outputs on 5 images; 154 ms to 23 ms per inference with debug output off |

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
- **Debugging the chip network.** Found that our chip networks ignored
  their input, withdrew the affected claims, and traced the cause to a
  platform-specific cast in the DORY code generator. Wrote the patch and
  five permanent release gates that would have caught it.
- **Team infrastructure.** Team fork and workflow, decision log, setup
  runbooks that let Grace and Oaj reproduce results on three operating
  systems, a firmware decode contract with a tested C decoder, and meeting
  reports.

**Methods note.** I developed this work with AI coding assistance, Claude
Code, as the project lead encouraged. I directed the experiments, ran and
checked the results, and made the decisions recorded in DECISIONS.md.

## Team context

- **David Liu:** original thesis, training and release pipeline, handoff
  files.
- **MinHyuk Park:** Crazyflie simulator, drone hardware, AI-deck camera
  firmware.
- **Grace Hao:** quantization lane; reproduced the Aug 28 chip-simulator
  result on an Intel Mac (it used the checked-in app files, so it could not
  catch the DORY bug); caught a missing-checkpoint bug; measured that keeping
  the learned quantization ranges gains only 0.17 F1 points, below her
  materiality bar; requested drone access.
- **Oaj Saini:** reproduced the setup on Linux and reported three setup
  bugs, which I fixed. No longer active on the project as of Sep 11.
- **Jade Chen, Koa, Calvin Ngu:** flight-control and firmware lane, starting
  with the decode contract.

## Session log

Newest first. One entry per working session.

- **2026-09-11 (evening).** Sent Prof. Mok the progress report, with a
  contributions list, a note that my part was built with AI coding tools
  under my direction, a link to this record, and a question about
  undergraduate research credit for next semester. Grace reviewed her line
  and agreed with it. The recorded demo video is ready to send ahead of the
  live demo.
- **2026-09-11 (afternoon).** Built the demo kit: one command runs a full
  demo and prints a plain-English scorecard, rehearsed 7 times across all
  four scenes, with three backup videos rendered from real flight logs and a
  talk track. Wrote the drone-side flight controller that turns the model's
  output into flight commands under our safety rules, in portable C with
  30,313 unit checks, and put it inside the Crazyflie firmware. In
  simulation it follows a person from firmware code with the same accuracy
  as the laptop version (2.7 degrees), refuses to steer on stale frames, and
  lands 3 s after the last good frame. Two independent reviews found and
  closed a real flaw: a link that was already slow before take-off could let
  the drone arm on stale frames.
- **2026-09-11 (midday).** Wrote the progress report email Prof. Mok asked
  for: the project's results, a contributions list, a note that my part was
  built with AI coding tools under my direction, and a link to this record.
  Offered Tuesday or Thursday after 5 pm for the simulator demo.
- **2026-09-11 (late morning).** Finished the firmware integration: six
  rounds of fixes, each checked by an independent reviewer with a timing
  simulator, until no failure the chip controls could make the drone steer
  on stale frames or fail to land. Delivered the branch as a git bundle with
  a hand-off for the frontend team. Tested the epoch-2 QAT confuser on the
  chip: it passes every check but gains nothing, because the release
  discards the ranges learned in QAT.
- **2026-09-11 (morning).** Put the champion network into a local branch of
  the drone firmware and ran six rounds of independent safety review: it
  now rejects failed inferences, resets tracking on camera or pipeline
  failures, and makes the drone land 3 s after the last good frame in every
  simulated failure pattern. Found that the firmware's image resize costs
  recall and replaced it with a 2x2 average that matches training. A 3-epoch
  QAT run with hard-negative mining brought the confuser's false alarms back
  to 8.4% while keeping QAT. Added a tested --seed option after finding large
  run-to-run variance.
- **2026-09-11 (early morning).** Checked chip-vs-float agreement on 1,000
  random images: every candidate passes, so the confuser decision is a
  trade-off, not a quantization failure. Verified an 8-core chip build
  (bit-exact, 6.6x faster) and found two more DORY template bugs: an
  out-of-bounds array write and a debug switch that costs 38 ms per
  inference. Found that the drone firmware still carries an older network
  and started a local integration dry run. Started a 3-epoch QAT confuser run.
- **2026-09-11 (after midnight).** Fixed a second pipeline bug: release reports
  decoded chip outputs with a hard-coded scale 6.6x too small, which made
  integer accuracy read 0.12 instead of 0.84. Re-released both models with
  both fixes; promoted the champion's chip app after it passed every check
  twice and the app's integrity check. Two control runs overturned the old
  "QAT erases the confuser gains" result: missing hard-negative mining was
  the cause. Audited every chip app built on this Mac: only the two old,
  already-withdrawn releases were corrupted.
- **2026-09-10 (evening).** Corrected the records: withdrawal notes in the
  experiment log, meeting reports, and decision log, and a reworded resume
  bullet. Ran a four-way investigation of the chip network. Root cause: the
  DORY code generator casts weights in a way that zeroes negative values
  on Apple Silicon; David's app was built on x86, where it works. Wrote the
  patch, five permanent release gates, a multi-image chip-simulator check,
  and a tested C decoder for the firmware team. Re-released both models: the
  champion passes every gate; the confuser misses the float-agreement bar.
  A control run showed the old "QAT erases the confuser gains" conclusion
  was wrong: training without hard-negative mining erases them. Added the chip's speed and
  delay to the simulated follower; tracking still works. Wrote the
  real-camera capture protocol and scoring tool.
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
