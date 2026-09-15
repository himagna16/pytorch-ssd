# Research Progress Record: Sai Maruvada

**Project:** Autonomous person-following nano-drone (Crazyflie + AI-deck GAP8), UT Austin
**Advisor:** Prof. Aloysius Mok
**Role:** Neural network training and evaluation (Role 1), plus simulator integration
**Period covered:** Aug 24 to Sep 14, 2026
**Last updated:** 2026-09-14

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
| Which model we fly | Sai, with the team | **DECIDED 2026-09-13: the champion.** Taken at the team dinner on the strength of the first head-to-head flight comparison: the confuser fixes the pet problem but cannot follow a person at all (0% tracking on a standing subject), and re-scoring every threshold showed the champion wins at all of them on both accuracy and false alarms. The still-image recall gap understated this badly, because the drone needs three consecutive confident frames to lock on, and a slightly less confident model almost never gets three in a row | None. The follow-on work is making the champion safer, tracked in the row below |
| Making the champion safer around pets | Sai | **Still open. Settings are exhausted, and the first retraining attempt did not beat them.** Both drone thresholds were swept in flight and neither closes the limit. A five-round fine-tune (2026-09-14) appeared to cut per-frame false alarms from 24% to 9-13%, but independent re-checking showed that comparison read the false-alarm rate and the accuracy at two different confidence settings. Held at equal person-finding ability, the fine-tuned rounds are no safer than the model we fly, and simply turning up the model's own confidence dial reproduces almost the whole apparent gain. What the run did establish is a small but consistent accuracy cost. Evidence and the correction: docs/eval_results/2026-09-14-champion-hardneg/ (section 0) | Try a different recipe, not more seeds of this one. The confuser model IS genuinely safer at equal person-finding, so the effect is real and reachable - the question is how to get it without the confuser's recall collapse |
| Repeatable training | Sai | Done Sep 11: --seed option, tested (identical runs) | Use 3+ seeded repeats before reporting |
| Semantic release gates, so this cannot recur | Sai | Done Sep 10 | Run on every release |
| Withdraw chip-validation claims in docs and resume | Sai | Done Sep 10 | None |
| Tested C decoder for the firmware team | Sai | Done Sep 10 | Frontend trio builds against it |
| Simulator demo for Prof. Mok | Sai | Sent Sep 12; Prof. Mok replied "Great progress, team!" and David called the simulation's prediction of the AI-deck behaviour impressive | Live demo slot still unset: he said Tue/Thu after 3:30 pm, I offered after 5 pm - needs one confirming email |
| Flight-controller software (drone side) | Sai | Written and flying in simulation; passes an independent safety review | Bench test on real hardware |
| Progress record for Prof. Mok | Sai | Kept current, this file | Update every session |
| Progress report email for Prof. Mok | Sai | Sent Sep 11 and answered Sep 12. Prof. Mok asked for periodic documentation that can be edited into a final project report | Keep this record current; ask again for the specific registration process for research credit |
| First real AI-deck camera frames, motors off | Sai, MinHyuk | **Lab session next week**: Prof. Mok asked MinHyuk to meet the team with real hardware | Rehearse capture and scoring against a mock streamer before going; run the capture protocol in the lab |
| Simulator: chip latency and saved frames | Sai | Done Sep 12: reviewed and committed | None |
| Realistic simulator (v2) and its acceptance suite | Sai | Done Sep 12: camera-sensor model, chip-in-the-loop perception, 18-scene suite, 10-metric scoreboard; 14 cells x 37 flights flown, evidence in docs/sim_results/2026-09-11-simv2. **One correction Sep 12:** the suite's explanation of the distance failure was wrong and is withdrawn - see the row below and docs/eval_results/2026-09-12-distance | Fix the simulator's reflective floor and the size decode, then re-fly the distance cells (see the distance-keeping row); team uses the pet result to pick champion vs confuser |
| Flashing the champion app onto a real AI-deck | Sai | **Blocked:** the GAP8 build tooling (`aideck-gap8-examples/tools/build/`) is missing on this Mac, so nothing can be flashed yet | Restore the toolchain and write a flash runbook before the lab session |
| Rehearsing the real-frame capture before the lab | Sai | **Done Sep 14.** The whole chain was run the way the lab operator will run it, with the real champion network on realistic rendered frames: the left/right mirror check, the safety test that decides whether the drone would steer the wrong way, gives the correct answer in every direction (pass, mirrored, no data, mislabelled), and each answer was reproduced independently. The real network detects a rendered person at every distance; an earlier 0% result turned out to be crude test drawings, not the model. Seven documentation errors found by typing the commands exactly as written are fixed | Run it once more on the lab laptop the day before; expect the plush-toy clip to register as a false track, which the protocol now says to record |
| Distance keeping in the simulator | Sai | **Fixed, and my published cause was wrong.** The drone held about 3 m where it should hold 1.94 m. I had blamed the network's size head; on Sep 12 I traced it instead to the simulator's floor, which was 20% reflective, so the renderer drew people 1.5-2.0x too tall and the network read the person plus their reflection as one object. The size head reads real photographs correctly. Turning the reflection off and re-flying fixed it in all seven cells (for example 3.18 m to 2.43 m, and 2.42 m to 1.97 m against a 1.94 m target). A first re-fly suggested the fix cost flight stability; a controlled re-run with the code pinned and the two conditions interleaved found 0 upsets in 28 flights against 1 in 28, so that was an artefact of an overloaded laptop. Removing the mirror is free | Done Sep 12: the full 14-cell baseline has been re-flown on the fixed scenes. Next: give the pet case a controlled mirrored arm before it decides the model choice, and find out whether the detector really does lose people at close range. Do **not** retrain the size head |
| Retest "QAT erases confuser gains" | Sai | Done Sep 11: overturned | None |

## Results and their status

| Result | Status |
|---|---|
| QAT champion beats David's released model, 0.8008 vs 0.789 peak F1 | Verified in simulated quantized (fake-quant) evaluation; reproduced by Grace. Not verified on the chip |
| Confuser model: animal and mannequin false alarms 24% to 8% | Verified in fake-quant evaluation |
| ~~Champion fine-tuned against pets: false alarms 24% to 9-13%, for about half a point of F1~~ | **WITHDRAWN 2026-09-14 on independent re-check.** The two figures were read at different confidence thresholds. At equal person-finding ability the fine-tuned rounds match the model we fly on pet false alarms (gain 0.000-0.001 at its operating point), and the model's own threshold dial reproduces almost all of the apparent cut. The accuracy cost is real; the safety gain is not established. Never verified on the chip |
| Reproduced David's GVSOC chip validation of his own app | Verified |
| Our Aug 28 and Aug 31 chip apps | **Were broken.** The integer network gave one output for all 96 test images: the DORY code generator turned every negative weight into 0 on Apple Silicon, and the old check compared the chip against a reference built from the same corrupted weights |
| Champion chip app after the fix | **Verified:** distinct output for all 96 images; exact on the chip simulator for 5 images, agreeing with an independent runtime; 94.8% visibility agreement with the float model |
| The drone chases a dog in simulation | **Verified in simulation, not on hardware:** on the pet scene it confirmed a dog 0.31 s in at confidence 0.87-0.89, stayed latched 68-78% of the flight and drifted 2.3-2.7 m, against a 0.5 m limit. It survives the chip network and the realistic camera |
| The drone does not hold its distance | **Verified in simulation, cause corrected Sep 12:** with the chip network it settles near 3 m instead of 1.94 m in every configuration tested. Pointing accuracy and the safety rules are unaffected. This row previously read "because the size head over-reads" - **that explanation is withdrawn.** The simulator's groundplane is a 20% mirror, so subjects render 1.5-2.0x too tall; measured against 2,635 real COCO photographs the size head is unbiased (signed error -0.007 to -0.015 float, +0.005 on the chip network we fly). The follower's control law also cannot reach 1.94 m at all - its floor is 2.43 m. **These simulator numbers describe a rendering artefact plus an unreachable target, and are not evidence about how the real drone keeps its distance.** Analysis: docs/eval_results/2026-09-12-distance/ |
| Realism costs, measured one factor at a time | **Verified in simulation:** the realistic camera adds 0.32 m of distance error, the chip network 0.13 m, the chip's slower frame rate 0.10 m |
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

- **2026-09-14 (night).** Took the first real swing at the pet problem by
  retraining, now that both drone settings are exhausted. Fine-tuned the model
  we fly for five short rounds, each one teaching it harder on the negatives it
  currently gets wrong, and measured both things that matter after every round:
  how well it still finds people, and how often it mistakes a pet or mannequin
  for one. The false-alarm rate on pets and mannequins fell from 24% to 9% at
  its best, and to 13% in the round I would actually pick. The cost is real but
  small: every one of the five rounds finds slightly fewer people than the model
  we fly, by about half a point of F1. So retraining does move the thing that
  configuration could not move at all, and it does not cost much - but it is a
  trade, not a free win, and the team has to decide whether half a point of
  accuracy is worth a large cut in false alarms. Two honest limits. This is one
  seeded run, and our own rule says three before quoting a training number; the
  best round's 9% bounced back to 13% the very next round, so I do not trust 9%
  yet. And none of this is the chip: the release path throws away exactly the
  calibration this training produces, which is Grace's preserve-QAT-alphas task,
  and I measured that same effect costing part of the gain at the very start of
  the run. Full numbers, commands and caveats in
  docs/eval_results/2026-09-14-champion-hardneg/.

  **Correction, added the same night after an independent re-check.** Every
  individual number above reproduces exactly, but the headline comparison was
  wrong: the false-alarm rate was read at one confidence setting and the
  accuracy at another, and the drone only runs at one. Compared properly - at
  equal person-finding ability - the fine-tuned rounds are no safer around pets
  than the model we already fly, and simply turning the existing model's
  confidence dial up reproduces almost the entire apparent improvement. That
  dial is the lever we had already swept in flight and rejected, so this run did
  not find a new one. The accuracy cost, on the other hand, holds up. The
  genuinely useful findings survive: the data-mix measurement, and the discovery
  that the release path's calibration reset costs part of any gain before
  training even starts. One real lead came out of the re-check: the confuser
  model *is* measurably safer at equal person-finding, so the effect we want is
  real - we just have not found a recipe that captures it without wrecking
  recall. Details in section 0 of
  docs/eval_results/2026-09-14-champion-hardneg/.

- **2026-09-14 (late).** Swept the drone's second threshold, the one that decides
  when it lets go of something it is following. This was the lead from the
  earlier run, and the answer is no: it does not close the pet problem at any
  value tested, and turning it up hurts. At the highest setting the drone dropped
  a walking person six times across two flights, where at the shipped setting it
  never lost them once, because every drop then costs a full re-acquisition. So
  both settings are now exhausted in flight and the remaining fix is retraining
  the model against pets, which depends on Grace's work. The more important
  finding is about our own measurements: the same configuration scored 11 of 16
  in the afternoon and 2 of 7 in the evening, on the same scene with the same
  seeds. This test case drifts between sessions by as much as the effects we are
  chasing, so from now on it is only compared within a single interleaved run,
  and the afternoon's 69% is one session's number rather than the rate. That also
  means I should not have offered it as a rate.

- **2026-09-14 (evening).** Used a spare hour to answer the question I got
  wrong this morning properly. Sixteen fresh pet flights at the shipped
  setting: 11 pass the half-metre limit and 5 fail, a per-flight pass rate of
  about 69% with a wide range, so it is a weighted coin rather than a pass or a
  fail, and every number was re-derived independently from the raw flight logs.
  The useful part is the mechanism. Every flight locks onto the dog within a
  couple of seconds at almost identical confidence; nothing before that moment
  separates the good flights from the bad. What differs is whether the lock lets
  go, and that is controlled by a second threshold, the release bar, that the
  earlier sweep never touched. That is the cheap next experiment. Also gave the
  two camera settings that had never been flown their first verdicts: low light
  is fine, colour Bayer genuinely hurts tracking. Found a quirk in my own scorer
  along the way, which grades any non-standard camera against the strictest
  bar; flagged, not fixed.

- **2026-09-14 (afternoon).** Flew the full 14-case suite at the setting that
  now ships, 56 flights, so the lab has a reference flown at the real
  configuration. It corrected me. Yesterday I reported that the higher
  confirmation bar fixed the pet problem, on the strength of four flights that
  all passed. Four fresh flights at the same setting, same scene, same model,
  same random seeds, gave 0.71, 0.73, 0.46 and 0.34 m against a 0.5 m limit: two
  of four fail. The change stays, because it is better than before on every pet
  measure and costs nothing on people, but "fixed" is withdrawn and recorded as
  such. The lesson is about evidence, not the drone: four repeats were not enough
  to call a pass, and the random seed does not pin what the drone does in the
  loop. A second prediction of mine was also backwards: one scoring gate measures
  the share of frames in the "uncertain" band, and raising the bar widens that
  band by definition, so three cases still fail it for a reason unrelated to the
  drone's behaviour. Flagged for the team as a gate to re-calibrate. Everything
  else held: safety cases clean, no upsets in 56 flights, people tracked as
  before. The real fix for pets is now a training job, which depends on Grace's
  work.

- **2026-09-14 (later).** Rehearsed the lab measurement chain end to end, the
  way the operator will run it next week, with the real champion network on
  realistic rendered frames rather than the stand-in models used until now. The
  left/right mirror check, which decides whether the drone would steer the wrong
  way toward a person, gave the correct verdict in every direction and a second
  agent reproduced each one from a fresh shell. The real network sees a rendered
  person at every distance; an earlier "0% detection" scare was the crude test
  drawings, not the model. The test path that exercises this with the real
  network had never been run before today; it passes 39 of 39. One thing the
  operator must expect: a plush toy or pet registers as a false track at the new
  threshold, and the protocol now says to record it rather than be surprised.
  Typing every command exactly as written turned up seven documentation
  mistakes, fixed. Also paid a debt of my own: two evidence folders scored
  before a metric was renamed no longer reproduced their own numbers; migrated
  the stored records so they do again, values untouched. A full 14-case suite is
  now flying at the shipped 0.75 setting to give the lab a reference flown at
  the configuration that actually ships.

- **2026-09-14.** Merged the threshold change (pull request #2 on the team fork)
  after checking it: the new bar is live in every copy of the rule, and the
  mirrored branch is in step. Wrote to Grace with three things: the team's
  choice of the champion; that the confuser release which failed a gate on the
  96-image pack passes on the 608-image pack, so that failure was small-sample
  noise and not her model; and that the firmware contract row her export work
  targets has changed. Her preserve-QAT-alphas work is now the next thing that
  unblocks, since it is what would let a future fine-tune of the champion keep
  its gains through release. Still nothing on real hardware; the lab session
  with MinHyuk is next week.

- **2026-09-13 (evening).** Flew the cheap fix for the champion's pet problem
  rather than trusting the paper estimate, and the paper estimate was wrong. 96
  flights compared four confirmation rules in one session. Raising the confidence
  the drone needs before it locks on, from 0.70 to 0.75, makes the pet case pass
  its safety limit on all four flights with no measurable loss on people. The
  estimate had favoured 0.80; in flight that costs 12 points of accuracy on a
  standing person, and in one flight the drone spent five seconds failing to
  notice a person directly in front of it. Requiring four frames instead of
  three does not work either. Also caught and corrected a mistake of my own: the
  false-alarm figures I had written into the decision log were a pooled average
  across three scenes, two of which are zero, not the pet scene itself. The same
  threshold lives in several places, including the firmware that runs on the
  drone, and all of them are being changed together on a branch so the
  simulator and the real drone cannot end up confirming targets at different
  bars.

- **2026-09-13.** The team met over dinner (David and the other members; Prof.
  Mok was not there) and **chose the champion model.** The deciding evidence was
  last night's head-to-head flights: the safer model fixes the pet problem and
  will not follow a person at all, which the still-picture numbers had badly
  understated. My recommendation going in was the same, on the argument that it
  is easier to make an accurate model safer than to make a safe model accurate,
  and the flight data supports it. That settles the question and immediately
  promotes the champion's habit of chasing pets to the project's biggest
  remaining problem. I started on the cheapest possible fix straight away:
  the drone only locks onto something after three confident frames in a row, and
  raising the confidence needed looks, on paper, as though it removes the pet
  false alarms for almost no loss of accuracy. That costs nothing to ship if it
  works, since it needs no retraining. It is being flown now rather than taken on
  trust, because the paper version re-scores pictures from flights taken at the
  old setting.

- **2026-09-12 (late night).** Flew the two candidate models against each other,
  which had never been done: every closed-loop flight in this project had used
  the champion, so the team was about to choose between a model with flight
  evidence and one with none. 48 flights in one session, alternating between the
  models so neither got an easier machine. The confuser does exactly what it was
  designed to do, and it is not enough: it essentially stops chasing the dog
  (0.22 m of drift against the champion's 0.97 m, and it passes the safety limit
  the champion fails), but it **does not follow people at all**, tracking a
  standing person on 0% of frames across four flights. The obvious objection is
  that I judged it using settings tuned for the other model, so I re-scored every
  frame at thresholds from 0.45 to 0.80: the champion at its normal setting is
  better than the confuser at every setting, on both accuracy and false alarms at
  once. That bounds the question rather than closing it, because it re-scores
  frames from flights the confuser never got to steer. Also settled two smaller
  things: there is no close-range detection weakness (the evidence for one was a
  clock bug in my own analysis, now retracted), and a controlled repeat confirmed
  the dog improvement is real.

- **2026-09-12 (night).** Re-flew the seven test cases that still had no clean
  data, so the team finally has a complete 14-case baseline with no mirror in it.
  28 flights, all valid first time. The overall picture improves from 7 passing
  and 7 failing to **9 passing and 5 failing**: three cases pass now that the
  distance error is gone. The important one is the pet case, which is the
  evidence the team will use to choose between the two candidate models.
  **Most of the dog-chasing was the mirror.** With a matte floor the drone still
  notices the dog, but lets go almost at once instead of following it across the
  room: it drifts 0.41 to 0.93 m instead of 2.30 and 2.67 m, and stays latched
  for 1.3 to 3.6 seconds instead of about 15. It still fails its half-metre
  safety limit on three of four flights, so this is much less bad rather than
  fixed. Two things got worse and I am not burying them: one occlusion case now
  fails because the drone takes 3.2 seconds to re-find the person instead of
  0.5, and part of that may be a genuine weakness at close range, where the
  detector loses a person who fills the frame. That weakness was invisible while
  the mirror kept the drone too far away to meet it. Also installed the missing
  image library the lab fallback viewer needs, pinned so it could not disturb the
  numpy version the training pipeline depends on.

- **2026-09-12 (late evening).** Settled the question the earlier re-fly left open. The
  first run had suggested that removing the simulator's mirrored floor made the
  drone unstable, which would have made the fix a trade rather than a win. It
  did not hold up: a controlled re-run, with the source files locked byte for
  byte across both conditions and the two floors alternated flight by flight,
  flew 56 flights and found **no upsets in 28 on the matte floor against one in
  28 on the mirrored floor**. The earlier result was an artefact of running the
  experiment on a laptop that had fourteen other jobs on it. The distance
  improvement reproduced in all seven cases. Along the way the run turned up a
  measurement lesson worth keeping: the number we had been using to judge whether
  a flight was trustworthy is an average over the whole flight, and an upset is a
  single moment, so a laptop that stalls in short bursts can ruin a flight without
  that average moving at all. Also corrected two places where my own reports
  claimed more than the data supported, and fixed a rule in the repository's
  ignore file that had been hiding a 356-file evidence folder from version
  control, so the numbers now ship with the flights behind them.

- **2026-09-12 (evening).** Found that the headline explanation I published this
  morning was wrong, and corrected the record rather than quietly editing it. The
  simulator suite reported that the drone parks about 3 m from the person instead
  of 1.94 m, and I had written that the network's size head "over-reads by
  1.6-1.8x". It does not. The simulator's floor material is 20% reflective - a
  mirror - so the renderer draws each person's reflection hanging below their
  feet and the network reads the two as one object. Measured by rendering every
  frame twice, once with the person removed, the subject is drawn **1.53x taller
  than it should be at 2.4 m, rising to 2.01x at 3.8 m** - the same direction and
  the same size as the 1.3-1.6x "over-read" I had reported, over the same
  distances, and growing with distance the same way. Tested away from the simulator, on 2,635
  real COCO photographs with exact ground truth, the size head is **unbiased** -
  if anything it under-reads, never over-reads, and the integer network we
  actually fly puts its bucket boundary at 0.506 where the true answer is 0.500,
  about 1% out. Turning the mirror off in memory, changing nothing else, makes
  the flown network read the distance essentially exactly right. A second,
  separate problem: the follower stops closing the instant one frame reports the
  middle size bucket, and a perfect network would report it at 2.43 m, so the
  1.94 m target the scorecard gates on **was never reachable** - about 0.49 m of
  the reported error is built into the control law. And the "over-read ratio"
  column I published turns out to be arithmetic on the distance column, not an
  independent measurement. So the distance cells measure a rendering artefact
  plus an unreachable target, and I have withdrawn them as evidence about the
  real drone. What I changed: correction notes in the published evidence README
  (its §9), the experiment log, the decision log and this record; I did not
  delete anything. What I deliberately did **not** change: the simulator scenes,
  the scorer and the follower. Turning the floor reflection off invalidates every
  published simulator result including the September baselines, and softening the
  size decode changes flight behaviour six days before our first hardware
  session; both are team calls and neither has been flown. Nothing here touched
  hardware. For the lab session this makes the known-distance camera clips more
  valuable, not less: they are the direct test of whether the size head is
  accurate on real frames, and if the room has a shiny floor we should record
  that and, if we can, capture one set on a matte surface too.

- **2026-09-12 (afternoon).** Sent Prof. Mok the progress report and a recording
  of the simulator demo. He replied "Great progress, team!" and is asking
  MinHyuk Park to meet the team in the lab **next week to work with the real
  hardware** - the project's first hardware session. David Liu replied that it
  is impressive the simulation predicts the AI-deck's behaviour. On research
  credit, Prof. Mok said periodic documentation "will come in handy if the team
  wants to get an official grade for an undergrad research project from UT",
  which supports the idea but does not yet give the registration process, so I
  still need to ask. Started preparing for the hardware session, where the
  honest position is that several things have never touched anything real: the
  GAP8 build tooling needed to flash our app is **missing** on this Mac, and the
  camera capture tool has never run against an actual byte stream. Both are
  being fixed and rehearsed against substitutes before we go.

- **2026-09-12 (overnight).** Rebuilt the simulator to be realistic instead of
  convenient, then used it to test the drone we actually intend to fly. Three
  parts: a model of the real camera sensor (its auto-exposure, 60 fps timing,
  noise and motion blur), a mode that runs the **real chip network** and the
  chip's own image preprocessing in the loop rather than the float model, and a
  scene suite of 18 scenes built from JSON definitions with full ground truth.
  Added a scorecard of ten measurements with pass/fail limits, and flew a
  14-case matrix, 37 flights, 36 valid: **7 cases pass, 7 fail.** Findings, all
  in simulation and none on hardware: the drone **chases a dog** (confirmed in
  0.31 s, drifts 2.3-2.7 m against a 0.5 m limit) and this survives every
  realism setting; it **does not hold its distance** with the chip network
  (about 3 m instead of 1.94 m, in every chip configuration) - *corrected the
  same evening: the observation holds, but I had blamed the network's size head
  and the cause is the simulator's reflective floor plus an unreachable target;
  see the 2026-09-12 (evening) entry*; measured one at a
  time, the realistic camera costs 0.32 m of distance error, the chip network
  0.13 m, and the chip's slower frame rate 0.10 m; pointing accuracy and the
  safety rules survive all of it. Also fixed three faults in my own scoring
  tool: it reported the first failing repeat of a safety limit rather than the
  worst one (the pet drift was published as 2.301 m when the worse repeat was
  2.666 m); re-scoring the published evidence folder **destroyed** it, because
  flights whose control log is trimmed for size were rewritten as "invalid" -
  it now reads what those flights measured and says so on screen; and the
  folder's own metadata named the wrong sweep. The published evidence now
  re-scores to a byte-identical result twice running. Known and unfixed: on the
  worst frames the sensor model costs 7.27 ms against a 5 ms budget; subjects
  are still flat rectangular cards; nine camera parameters are taken from the
  datasheet and **not measured**; one far-person scene does not test what it
  was meant to.

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
