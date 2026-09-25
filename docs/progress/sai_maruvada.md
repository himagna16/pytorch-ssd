# Research Progress Record: Sai Maruvada

**Project:** Autonomous person-following nano-drone (Crazyflie + AI-deck GAP8), UT Austin
**Advisor:** Prof. Aloysius Mok
**Role:** Neural network training and evaluation (Role 1), plus simulator integration
**Period covered:** Aug 24 to Sep 24, 2026
**Last updated:** 2026-09-24

## Summary

I joined in late August to carry on David Liu's honors thesis: getting a
person-detection network to run on the drone's 64 mW GAP8 chip.

The first two weeks went into the toolchain and the models. I rebuilt the
training and quantization environments on macOS, fixing the bugs that had kept
them tied to David's machine, and trained a model that beats his released one in
simulated quantized form, 0.8008 against 0.789 peak F1. A second variant cuts
false alarms on pets and mannequins by about 3x. I also got MinHyuk Park's
Crazyflie simulator running on Mac laptops and wrote a closed-loop follower that
passes all five safety and tracking tests there.

On Sep 10 I found that the integer networks we had released for the chip were
ignoring their input entirely. I withdrew my chip-validation claims that day and
traced the cause to a platform bug in the DORY code generator on Apple Silicon.
After the fix the champion's chip network passes all five of the new release
checks, including the chip simulator on five images, and it is now the team's
validated app.

Most of the last week went into a different question: does the simulator tell
the truth? Twice it did not. Its explanation for a distance error was wrong, and
its person scenes turn out to be built around one unusually easy photograph. Both
are written up below. The short version is that our tracking figures describe
that one subject, and the lab session is what will tell us where real people
fall.

The drone itself arrived on Sep 17. That session confirmed the deck can be
flashed over the air and already carries the camera streamer, so capturing frames
needs no flashing at all — and then ended on a flat battery, because charging runs
through the Crazyflie's own micro-USB and we did not have a cable. That is still
the state as of Sep 20, and it is the only thing standing between us and the
measurement this project is waiting for.

The plan for what comes after capture is now written down. We are using the
Lighthouse deck rather than the thesis setup's Flow deck, which changes what is
possible: a second Crazyflie with its props off rides on the subject's head as a
pose beacon, and the difference between the two drones' poses gives us where the
person truly was for every frame, including the frames the network misses
entirely. That is labelled training data of a kind nothing else here can produce.
What can be built before the next hands-on session, and what will go wrong if it
is not, is in `docs/hardware/before_the_next_session.md`.

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
| How well the drone follows people | Sai | **First real data Sep 24 (one person, 5 grid positions): seen and locked off to the side (71-88%), never locked dead centre in front of a dark door. Contrast looks like the driver** (`docs/eval_results/2026-09-24-grid-capture/`). *Earlier status:* **Not yet known, and the published figures are about one person.** Every tracking number in this project (97-99%) came from scenes built around a photograph that turns out to sit near the 98th percentile of how easily this model detects a person. Rebuilt the same scenes around a typical person and a somewhat-below-average person: the drone never starts following at all, in 11 of 12 flights, while the original subject still reproduces 99% on the same rig. Rendered cutouts are harder than real people, so the truth lies between the two, and neither end is the drone's real behaviour | This is the question the lab session answers. Capture real frames of real people and measure where they fall |
| Simulator demo for Prof. Mok | Sai | Sent Sep 12; Prof. Mok replied "Great progress, team!" and David called the simulation's prediction of the AI-deck behaviour impressive | Live demo slot still unset: he said Tue/Thu after 3:30 pm, I offered after 5 pm - needs one confirming email |
| Flight-controller software (drone side) | Sai | Written and flying in simulation; passes an independent safety review | Bench test on real hardware |
| Progress record for Prof. Mok | Sai | Kept current, this file | Update every session |
| Progress report email for Prof. Mok | Sai | Sent Sep 11 and answered Sep 12. Prof. Mok asked for periodic documentation that can be edited into a final project report | Keep this record current; ask again for the specific registration process for research credit |
| First real AI-deck camera frames, motors off | Sai, MinHyuk | **Done Sep 22, in my dorm, not the lab.** Stream works (every frame decoded). The image is not mirrored: I appear on the correct side, and 10 of 12 confident outputs point the right way. The champion called dorm furniture a person strongly enough to lock on; with the chairs removed, an empty room gave 0 false locks (peak 0.71). I am detected only some of the time at 2.44 m in a dim room (one person, not a rate). The real stream is 162 x 122, pixels 0-191, about 2 fps, which differs from the simulator's assumptions. Evidence: `docs/eval_results/2026-09-22-first-real-frames/`. *Earlier status:* **Lab session next week**: Prof. Mok asked MinHyuk to meet the team with real hardware | Rehearse capture and scoring against a mock streamer before going; run the capture protocol in the lab |
| Simulator: chip latency and saved frames | Sai | Done Sep 12: reviewed and committed | None |
| Realistic simulator (v2) and its acceptance suite | Sai | Done Sep 12: camera-sensor model, chip-in-the-loop perception, 18-scene suite, 10-metric scoreboard; 14 cells x 37 flights flown, evidence in docs/sim_results/2026-09-11-simv2. **One correction Sep 12:** the suite's explanation of the distance failure was wrong and is withdrawn - see the row below and docs/eval_results/2026-09-12-distance | Fix the simulator's reflective floor and the size decode, then re-fly the distance cells (see the distance-keeping row); team uses the pet result to pick champion vs confuser |
| Flashing the champion app onto a real AI-deck | Sai | **Unblocked and rehearsed Sep 16.** Toolchain present, flight image rebuilds byte-identical to the Sep 13 one (sha256 261e20d8, 340,896 B). The bigger fix: flashing was believed to destroy the camera streamer irreversibly, needing MinHyuk to restore it. The streamer's source is in our own workspace; I built it twice from clean to a byte-identical 61,472 B image (de11368d) and kept both images outside the build tree. The flash is reversible. Build verified, flash never tried on hardware | Drone arrives Sep 17 at 1 pm. Follow docs/hardware/first_hour_with_the_drone.md |
| Rehearsing the real-frame capture before the lab | Sai | **Done Sep 14.** The whole chain was run the way the lab operator will run it, with the real champion network on realistic rendered frames: the left/right mirror check, the safety test that decides whether the drone would steer the wrong way, gives the correct answer in every direction (pass, mirrored, no data, mislabelled), and each answer was reproduced independently. The real network detects a rendered person at every distance; an earlier 0% result turned out to be crude test drawings, not the model. Seven documentation errors found by typing the commands exactly as written are fixed | Run it once more on the lab laptop the day before; expect the plush-toy clip to register as a false track, which the protocol now says to record |
| Distance keeping in the simulator | Sai | **Fixed, and my published cause was wrong.** The drone held about 3 m where it should hold 1.94 m. I had blamed the network's size head; on Sep 12 I traced it instead to the simulator's floor, which was 20% reflective, so the renderer drew people 1.5-2.0x too tall and the network read the person plus their reflection as one object. The size head reads real photographs correctly. Turning the reflection off and re-flying fixed it in all seven cells (for example 3.18 m to 2.43 m, and 2.42 m to 1.97 m against a 1.94 m target). A first re-fly suggested the fix cost flight stability; a controlled re-run with the code pinned and the two conditions interleaved found 0 upsets in 28 flights against 1 in 28, so that was an artefact of an overloaded laptop. Removing the mirror is free | Done Sep 12: the full 14-cell baseline has been re-flown on the fixed scenes. Next: give the pet case a controlled mirrored arm before it decides the model choice, and find out whether the detector really does lose people at close range. Do **not** retrain the size head |
| Retest "QAT erases confuser gains" | Sai | Done Sep 11: overturned | None |
| How well the drone follows people, measured across people | Sai | **Measured Sep 15 (208 flights), substantially qualified Sep 16.** The published subject latched 16/16 and tracked 0.99; the twelve screened subjects latched on 29% of standing flights. But the standing scene places the person 15.9 degrees off centre, and a 13,003-frame grid at five distances by five angles shows that straight ahead at 3.5 m, four of the seven that never latch clear the bar on 95-100% of frames. Four others fail either way and are genuinely hard. So the 29% is substantially a property of one camera pose. 104 on-axis flights (Sep 16) give latch 0.292 to 0.594 and median tracking 0.000 to 0.963, but **the comparison is confounded**: the opaque card throws a shadow on the far wall that is visible off-axis (-30.0 DN on 13/13 subjects) and hidden on-axis (+2.3 DN on 13/13), so those gains are an upper bound. A 156-flight attempt to remove the shadow FAILED and is not interpretable: the sensor model's auto-exposure holds every frame at a mean of 60 DN, so lightening the room pulled gain down and cost the subject contrast, collapsing detection even on-axis. A narrower re-run, stopping only the panel from casting, is in flight. Evidence: 2026-09-16-noshadow/ (the failure), 2026-09-17-panel-noshadow/ Evidence: docs/eval_results/2026-09-15-people-plural/, 2026-09-16-protocol-geometry/, 2026-09-16-one-frozen-pose/, 2026-09-16-onaxis/ | 13 refutation passes running against the revised reading before it goes to the team |
| The standing scene is one frozen photograph | Sai | **Found Sep 16.** On every frame of every standing flight the drone sits at the origin with zero yaw, because it never latches so it never moves. A standing cell therefore renders one pose and the eight repeats differ only by sensor noise, so intervals computed as if they were independent are too narrow. Also: the covariate I used to rank subjects was measured on-axis while the flights were off-axis, a mean gap of 0.122 and up to 0.336 | Any future standing suite must vary the pose, or say plainly that it measures one |
| Why the drone ignores ordinary people: a frozen-geometry deadlock | Sai | **Found Sep 15, tested Sep 16: the deadlock is real and is NOT the explanation.** The follower commands neither yaw nor forward motion until locked on (follow_person.py:371-376) and every one of the 109 latches across 208 flights happened with the drone still at its start pose, so it never closes range on its own. But flying the same 13 people at 1.6 / 2.2 / 2.8 m rescues only one of the seven failures in the two geometrically clean arms. Four are not acquired even at 1.6 m. The 1.6 m arm cannot be used: the far wall's top edge falls at image row 42 of 244 and at that range the subject's head crosses into the skybox, so it changes what the network sees in a way unrelated to range. My first write-up concluded the opposite through an invalid floor argument and miscounted seven as eight; 14 of 15 refutation passes found something. Evidence: docs/eval_results/2026-09-15-deadlock/ | Creep forward plus a closer hold is still worth building and is a few parameters, but it is not the fix. The remaining four are a perception problem |
| MinHyuk's field-of-view objection to the person study | Sai | **Answered Sep 15, mostly in our favour with one real caveat.** He said a real camera almost never has the whole person in frame. Our camera is level at 0.8 m behind a 70 degree square crop, so a 1.7 m person stops fitting below 1.29 m while the drone never closes past 1.55 m in any flight on record. The caveat is height: a 1.9 m person is cut off below 1.57 m, which is inside the range our flights reach. Separately, the detection penalty for partial people is entirely from being cut off by the frame edge; occlusion and pose cost nothing measurable. Evidence: docs/eval_results/2026-09-15-partial-people/ | The axis that actually threatens a track is bearing, not truncation. Worth measuring next |
| Whether a YOLO model could replace ours | Sai | **Answered Sep 15: no, not through this pipeline.** MinHyuk suggested YOLOv11 nano and David warned about quantizing it. Exported both YOLOv11n and YOLOv8n and ran every node against our code generator's own accept rules: the build stops at node 10 of 355, 21 nodes are rejected outright, and another 112 are accepted and then silently dropped, including all 78 sigmoids and all 21 feature-pyramid joins. Our champion passes the same check with zero rejections. Evidence: docs/yolo_on_gap8.md, docs/eval_results/2026-09-15-yolo-ops/ | Use YOLO off the drone to label the real frames we capture. Do not try to put it on the chip |
| The uncertainty gate (M10) and its line | Sai | **Proposal written Sep 15, number deliberately not set.** The line was drawn for the old confidence bar and needed redrawing for the new one. Re-scoring all 287 flights showed the band is not the problem: the line's stated justification holds only for standing scenes, every static flight passed it while half the moving flights failed, and the number drifted 76x across four of our suites on one scene because the mirror-floor fix made it harder. A version of the measurement that does not reference the confidence bar holds its line on 100% of held-out flights where the current one manages 71%. Evidence: docs/eval_results/2026-09-15-m10-line/ | Team decides. No number until the scene suite covers a realistic range of people |
| Two cables, and they block a whole session | Sai | **CLOSED Sep 24.** The micro-USB cable arrived Sep 22 and the USB-C hub Sep 23. Through the hub the laptop sees both the Crazyflie and the Crazyradio 2.0; the radio had never been seen before, because the laptop has no USB-A port. *Earlier status:* **micro-USB cable in hand Sep 22; the radio adapter is still unknown.** Also in hand Sep 22: a second Crazyflie and two Lighthouse base stations (both drones identical, each with an AI-deck and a Lighthouse deck stacked on the same body, confirmed by Sai the same evening; base stations V1/V2 not yet identified; plan in `docs/hardware/dorm_setup.md`). *The Sep 17 text follows:* **Outstanding since Sep 17.** A data-capable micro-USB cable is the single blocking item: without it the battery cannot be charged, which caps every visit at the five to seven minutes a 350 mAh pack gives with the AI-deck streaming. Separately the Crazyradio 2.0 is USB-A and the laptop is USB-C only; a scan on Sep 17 reported `Cannot find a Crazyradio Dongle` and it was never established whether the dongle was plugged in at all. Under the Lighthouse plan the radio stops being optional, because positions come back over CRTP, not over the deck's WiFi | Buy both. Charge-only micro-USB cables are common and will fail the bench-power and flashing uses, so check for data |
| Scoring tool runs the wrong network | Sai | **Fixed Sep 22 on branch `sai/score-real-frames-chip-backend` (PR, awaiting merge).** `score_real_frames.py --backend {float,chip}`, default chip, reusing the simulator's own chip perception; `scores.json` records the arm, the model sha1 and the eps. Tests: chip output identical to the flight path on all 14 integer outputs; float output byte-identical to the old scorer. *The Sep 17 text follows; its numbers were wrong (see the next row):* **Found Sep 17, deliberately not fixed that night.** `tools/real_frames/score_real_frames.py` is hardwired to the float model while the drone flies the int8 chip export. On 13,003 frames they disagree by -0.124 mean confidence and -0.239 in the fraction above the 0.75 bar, 122 of 325 cells moving by 0.25 or more, so it cannot be corrected after the fact. Left alone because it is a shared tool and the repo's rules put that on a branch with a PR, hours before a hardware session. Workaround in place: the first-hour guide runs both scorers and says to believe the chip one | Merge the PR. Nothing else |
| The Sep 16 bearing work was scored on the float arm | Sai | **Rescored Sep 22: most of it survives, and the Sep 17 alarm was mostly my own bug.** `rescore_chip.py` ran the image preprocess twice, so its "chip" numbers came from a blurred frame. The real chip-versus-float gap is -0.020 in confidence, not -0.124, and 45 cells move rather than 122. On the real chip arm the pose/hard split, the bearing-cost shape, the 2.5 m finding and the 3.5 m reference all hold. The 25-degree left/right asymmetry does not, and two of the four hard subjects come back only weakly at 1.5 m. Evidence: `docs/eval_results/2026-09-22-sep16-chip-rescore/` | None. Compare real frames against that folder's chip column, bearing 0 |
| Separating bearing from the card's own shadow | Sai | **The simulator cannot answer this. Two attempts dead.** The subject panel is opaque and throws a box shadow on the far wall that is visible off-axis (-30.0 DN on 13/13 subjects) and hidden on-axis (+2.3 DN on 13/13), so the Sep 16 on-axis gain is an upper bound. Attempt 1 (`2026-09-16-noshadow`, 156 flights) removed the shadow and collapsed detection everywhere including the control, 0.991 to 0.048, because `camera_model.py` holds every frame at `AE_TARGET_DN = 60.0` and lightening the room made the exposure loop take the contrast back out of the subject. Attempt 2 (`2026-09-17-panel-noshadow`) aborted after one flight | Stop trying in simulation. It is a lab measurement now. Say so to the team before the session, not in the room |
| Lighthouse ground truth from a head-mounted second drone | Sai, MinHyuk | **Room set up Sep 24.** Two V2 base stations on stands (channel 1 at the window end, channel 2 at the door end). A clean geometry solve had every sample under 2 mm, and a tape check on the floor marks was within about 1-3 cm (both saved). Geometry file: `docs/hardware/lighthouse/dorm_lighthouse_2026-09-24.yaml`. Next: load it on drone 2, give the two drones distinct radio addresses, a head mount for the beacon, then a static capture. *Earlier status:* **Planned Sep 20; the desk half built Sep 22 (PR, not yet merged).** `tools/lighthouse/pose_to_label.py` turns the two poses into the x-bin and size bucket the network should output, and `align_clocks.py` lines up the frame and pose clocks from a still-then-sidestep at the start and end of each recording. Validated on 267 archived simulator flights: `docs/eval_results/2026-09-22-pose-to-label-sim-validation/`. A second Crazyflie, props off and motors never armed, rides on the subject's head as a pose beacon; both drones carry Lighthouse decks; the difference between the two poses, rotated into the follower's body frame, is where the subject truly was. Truth minus what the network said is the training signal. **The property that makes this worth doing: ground truth exists for frames the network misses entirely**, which no other labelling method we have can give us. The thesis setup's Flow deck could not do this even in principle, because optical flow gives relative motion and never tells you where the subject is. Plan and prerequisites: `docs/hardware/before_the_next_session.md` §3 | Team signs off the head-to-body convention (label target at half the subject's height below the head) in DECISIONS.md. Email MinHyuk the seven hardware questions (§3.4). Run the static taped-mark case in `tools/lighthouse/README.md`, including the yawed step, before collecting anything |
| The yaw-sign chain | Sai | **CONFIRMED on real hardware Sep 24.** Turning the drone 90 deg to its left read +89.1, +91.4 and +94.6 deg in three tape-check runs (`tools/lighthouse/tape_check.py`), so the labels will not come out mirrored. The chain first flagged on Sep 10 is closed. *Earlier status:* **Settled in the simulator Sep 22; still open on hardware.** Labels from the follower's logged pose and the subject's true position agree with the network on which side the person is in 99.0% of clearly-left and 100% of clearly-right frames (267 flights). With the yaw sign flipped, that falls to 24% and 20% on frames where the drone had turned. The follower's own command sign (-1) turned the drone the right way in 99.9% of 24,528 tracking frames. Two caveats: the yaw sign is only tested when the drone has actually turned, and a crash or a frozen pose log makes correct labels look mirrored, so the pipeline now drops those frames | On hardware: the static case with the follower turned 30 degrees on its stand, and check the lab drone's firmware protocol version (the command sign flips on old firmware) |
| The real camera's stream mode (162 x 122, pixels up to 191, ~2 fps) | Sai, MinHyuk | **Open, found Sep 22.** Not what the simulator or training assumed. It could be a deliberate binned mode or the wrong streamer build. Email to MinHyuk drafted Sep 22; **not sent, on hold by my choice (Sep 24)** | Settle it before collecting frames at scale, so a large dataset is not captured in the wrong mode |
| Camera exposure is random at every power-up | Sai, then firmware | **Found Sep 24.** The same room came out at brightness 4-146 across power-ups. Near-black frames make the champion "see" a person at 0.84 and lock on. The stock streamer and our `crazyflie_ssd/src/camera_if.c` both set exposure only once, at start-up | Firmware: fixed or continuous exposure, plus a brightness-floor guard. Data: record only inside a 30-60 band (done in `grid_capture.sh`) |
| First hands-on session with the hardware | Sai | **Happened Sep 17, 1 pm. Half a result.** Confirmed from the bench: AI-deck 1.1, Rev D or newer, so over-the-air flashing is supported, closing an open question in `flash_runbook.md` §8. The deck already carries the WiFi streamer, so nothing needs flashing to capture frames. No power button exists; the Crazyflie powers up when the battery is connected. The afternoon went almost entirely to things nobody had written down, and ended on a flat battery with no charging cable. Written up in `docs/hardware/powering_the_drone.md` | Buy the cable, then run the capture. Nothing else is in the way |

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

- Rebuilt the training and NEMO quantization environments on macOS. Fixed
  Linux-only package pins, a numpy/pycocotools ABI conflict, and a NEMO export
  crash under PyTorch 2.x. Tested and set the team PyTorch version so Grace's
  Intel Mac could join.
- Reimplemented the thesis's bin-head model from its text and replicated its two
  main claims. Ran the full-COCO training campaign, quantization-aware training,
  and the targeted confuser retraining.
- Built the evaluation tools: a drift audit between float and quantized models,
  threshold sweeps, error analysis, confuser-slice metrics. Showed that the
  16-image drift audit predicts full-set quantization loss.
- Reproduced David's chip-simulator validation and made his release pipeline run
  on other machines. That took a containerized legacy export environment and four
  further fixes, one of them a path hardcoded to his laptop.
- Ported CrazySim to Apple Silicon with the firmware in a small container, then
  built person scenes from COCO photos, a follower with safety rules,
  ground-truth logging, and a one-command acceptance suite. Testing turned up
  five issues I fixed, including macOS network limits and a steering sign flip.
- Found that our chip networks ignored their input, withdrew the affected claims,
  and traced it to a platform-specific cast in the DORY code generator. Wrote the
  patch and five permanent release gates that would have caught it.
- Set up the team fork and workflow, the decision log, setup runbooks that let
  Grace and Oaj reproduce results on three operating systems, a firmware decode
  contract with a tested C decoder, and the meeting reports.

**Methods note.** I developed this work with AI coding assistance, Claude
Code, as the project lead encouraged. I directed the experiments, ran and
checked the results, and made the decisions recorded in DECISIONS.md.

## Everything done, in one list

Aug 24 to Sep 20, 2026. Grouped by area rather than by date; the dated narrative
is in the session log below. Withdrawn and corrected results are listed with the
rest rather than quietly dropped, because several of them are the most useful
things in here.

### Toolchain and environments

- Rebuilt the training and NEMO quantization environments on macOS from a setup
  that only ran on David's machine. Four toolchain fixes: Linux-only package
  pins, a numpy/pycocotools ABI conflict, a NEMO export crash under PyTorch 2.x,
  and a path hardcoded to his laptop.
- Set the team PyTorch version so Grace's Intel Mac could join.
- Containerized the legacy export environment, which is what let the release
  pipeline run anywhere but David's machine.
- Ported MinHyuk's CrazySim to Apple Silicon, with the firmware in a small
  container. Five issues found and fixed in the process, including macOS network
  limits and a steering sign flip.
- Setup runbooks that let Grace and Oaj reproduce results on three operating
  systems, plus fixes for the bugs they found doing it.

### Models and training

- Reimplemented the thesis's bin-head model from the text of the thesis and
  replicated both of its main claims: the straight-through graph exports through
  NEMO with zero patches where the hybrid needs the eps hack, and decoded bins
  survive the float-to-quantized step where a scalar head does not.
- Ran the full-COCO training campaign. **QAT champion: 0.8008 peak F1 in
  fake-quant form against David's released 0.789.** Reproduced by Grace.
- Trained the confuser variant, which cuts animal and mannequin false alarms from
  24% to 8%.
- Hard-negative mining plus QAT, after a control run showed mining rather than
  QAT was the missing piece.
- Added `--seed`, tested to give identical runs, after finding large run-to-run
  variance. Three or more seeded repeats before reporting is now the rule.
- Fixed `train.py --init-ckpt` silently dropping 59 learned PACT alpha/range
  tensors, which cost 0.0017 F1 and added 0.019 slice false-alarm rate before a
  single gradient step. PR #3; `--init-ckpt-drop-qat-alphas` reproduces the old
  behaviour bit-exactly.

### Evaluation tooling and method

- Drift audit between float and quantized models. Showed the cheap 16-image audit
  predicts full-set quantization loss.
- Threshold sweeps, error analysis, confuser-slice metrics.
- A tested C decoder for the firmware team, verified against the Python decode on
  14,579 checks and catching all 7 deliberate bugs in a mutation test.
- `rescore_chip.py`, which rescores any folder of frames on the network that
  actually flies, in about twenty seconds. *(Sep 22: it preprocessed twice and
  is superseded by `score_real_frames.py --backend chip`, now the default.)*
- **Two method rules that came out of being wrong**, and that now apply to
  everything here: compare models at **matched recall**, never at different
  thresholds, and always run the threshold-dial control on the baseline before
  crediting training with a gain. A scene's **subject is a parameter of the
  experiment**, not set dressing, and every tracking claim has to say which
  subject produced it and where that subject sits in the detectability
  distribution.

### The chip lane: GAP8, NEMO, DORY

- Reproduced David's GVSOC chip validation of his own app.
- **Found that our released integer networks were ignoring their input entirely**
  — one output for all 96 test images. Withdrew the chip-validation claims the
  same day, then traced it to the DORY code generator casting weights in a way
  that zeroes negative values on Apple Silicon. David's app was built on x86,
  where it works. Wrote the patch.
- Fixed a second pipeline bug: the release reported decoded chip outputs with a
  hard-coded scale 6.6x too small, which made integer accuracy read 0.12 instead
  of 0.84. Champion integer F1 is 0.837 against 0.815 for the float model.
- Two further DORY template bugs: an out-of-bounds array write, and a debug
  switch costing 38 ms per inference.
- Verified the 8-core build: bit-exact against single-core, 154 ms down to 23 ms
  per inference with debug output off.
- Chip-versus-float agreement on 1,000 random images: 93-96% visibility agreement
  for all three candidates, about one confident contradiction per thousand
  images, no measurable F1 loss.
- Audited every chip app ever built on this Mac. Only the two already-withdrawn
  releases were corrupted.
- **Established that YOLO cannot replace our model through this pipeline.**
  Exported YOLOv11n and YOLOv8n and ran every node against the code generator's
  own accept rules: the build stops at node 10 of 355, 21 nodes rejected
  outright, another 112 accepted and then silently dropped, including all 78
  sigmoids and all 21 feature-pyramid joins. Our champion passes with zero
  rejections. Use YOLO off the drone to label real frames instead.

### Release pipeline and gates

- Made David's release pipeline portable, five fixes.
- **Five permanent semantic release gates** that would have caught the constant-
  output bug. Verified: both old releases fail all five, David's app passes the
  weights check, a synthetic healthy release passes all five.
- Promoted the champion's chip app after it passed every gate twice plus the
  app's own integrity check. It is the team's validated app.
- The confuser's chip app runs correctly but agrees with its float model on only
  88.5% of visibility calls against a 90% bar, all near the decision boundary.

### Firmware integration

- Put the champion into a local branch of the drone firmware. **Six rounds of
  independent safety review** with a timing simulator, until no failure pattern
  the chip controls could produce would make the drone steer on stale frames or
  fail to land. It now rejects failed inferences, resets tracking on camera or
  pipeline failures, and lands 3 s after the last good frame in every simulated
  failure pattern.
- Found the firmware's image resize was costing recall and replaced it with a 2x2
  average matching training.
- Delivered the branch as a git bundle with a hand-off for the frontend trio.
- A firmware decode contract, with the tested C decoder above.

### Simulator

- Closed-loop person follower, passing all five safety and tracking tests.
- Realistic simulator v2: camera-sensor model, chip-in-the-loop perception, an
  18-scene suite, a 10-metric scoreboard. 14 cells and 37 flights flown.
- Chip latency and frame rate in the loop: at 6.5 Hz with 153 ms delay, 3.1
  degrees mean heading error against 2.7 at full speed, no oscillation.
- Realism costs measured one factor at a time: the realistic camera adds 0.32 m
  of distance error, the chip network 0.13 m, the slower frame rate 0.10 m.
- Person scenes built from COCO photographs, ground-truth logging, a one-command
  acceptance suite.
- Fixed the scoreboard's camera gating and M10 band. Baseline-075 went from 8
  pass / 6 fail to 10 pass / 4 fail.

### What the studies established

- **The drone chases a dog.** In simulation it confirms a dog 0.31 s in at
  confidence 0.87-0.89, stays latched 68-78% of the flight and drifts 2.3-2.7 m
  against a 0.5 m limit. Survives the chip network and the realistic camera.
- **Which model we fly: the champion.** Decided at the team dinner on Sep 13 on
  the first head-to-head flight comparison. The confuser fixes the pet problem
  and cannot follow a person at all, 0% tracking on a standing subject. The
  still-image recall gap understated this badly, because the drone needs three
  consecutive confident frames to lock on and a slightly less confident model
  almost never gets three in a row.
- **The acquisition rule**, which held on all 54 flights across two studies: the
  drone latches if and only if the longest above-bar run is at least 3 frames.
  The binding constraint is the **entry** gate, not the 0.45 exit bar.
- **Both drone thresholds swept in flight and rejected.** 0.65 rejected for
  re-latch chatter; 0.55 lower on 6 of 7 matched seeds but not callable; the
  0.70-versus-0.75 enter bar leaves 3 of 4 ordinary cells acquiring at neither.
  Reverting does not produce a working follower. **0.75 stays. Configuration is
  exhausted.**
- **Every tracking number this project published describes one unusually easy
  photograph.** COCO val2017 19432 sits near the 98th percentile of
  detectability. Rebuild the same scenes around a median or 25th-percentile
  person and the drone never starts following at all: 0.000 tracking on 11 of 12
  flights, while the original subject still reproduces 0.990 on the same rig.
- **The simulator does not predict reality, in both directions.** On pets it
  overstates confidence by about 2.9x at matched apparent size. On people it
  overstates, and the cause is subject selection rather than the renderer. Real-
  pet false alarms at the shipped 0.75 bar are 6.9-8.2%, not the 30.2% usually
  quoted, which was measured at 0.45.
- **Distance keeping: the published cause was wrong.** The drone held about 3 m
  where it should hold 1.94 m. I had blamed the size head. It was the
  simulator's groundplane being 20% reflective, so people rendered 1.5-2.0x too
  tall and the network read person-plus-reflection as one object. Against 2,635
  real COCO photographs the size head is unbiased. The follower's control law
  also cannot reach 1.94 m at all; its floor is 2.43 m.
- **MinHyuk's field-of-view objection, answered mostly in our favour.** A 1.7 m
  person stops fitting below 1.29 m and the drone never closes past 1.55 m in any
  flight on record. The real caveat is height: a 1.9 m person is cut off below
  1.57 m, which is inside the range our flights reach. The detection penalty for
  partial people comes entirely from frame-edge truncation; occlusion and pose
  cost nothing measurable.
- **The auto-exposure lesson**, which applies backwards to the floor-reflectance
  work: the sensor model holds every frame at a mean of 60 DN, so anything that
  changes what else is in the picture changes how the person looks, even when
  nobody touched the person.
- **The F.pets cell drifts between sessions** by as much as the effects we chase.
  Identical config gave 11/16 in an afternoon and 2/7 the same evening. Compare
  that cell only within one interleaved session.

### Corrections and withdrawals

Kept deliberately visible. Six results were published and then pulled or
rewritten after checking (five until 2026-09-22):

1. **Chip validation, withdrawn Sep 10.** The integer networks ignored their
   input; the old check compared the chip against a reference built from the same
   corrupted weights.
2. **"The size head over-reads," withdrawn Sep 12.** It was the simulator's
   mirror floor. The size head is unbiased on real photographs.
3. **"QAT erases the confuser gains," overturned Sep 11.** Missing hard-negative
   mining was the cause, not QAT.
4. **The Sep 14 pet fine-tune, withdrawn Sep 14 on independent re-check.** The
   24%-to-9-13% false-alarm cut and the F1 figure were read at two different
   thresholds. At matched recall the fine-tuned epochs lie on the champion's own
   false-alarm curve, gaining 0.000-0.001 at its operating point, and simply
   turning up the champion's own confidence dial reproduces 0.133 of the 0.146
   apparent drop. The accuracy cost is real; the safety gain is not established.
5. **The Sep 16 on-axis bearing gain, downgraded to an upper bound.** The opaque
   subject card throws a shadow visible only off-axis. Two attempts to remove it
   failed, one of them by collapsing detection everywhere including the control.
6. **The Sep 17 "chip arm" rescore, corrected Sep 22.** My `rescore_chip.py` ran
   the firmware preprocess twice, so its chip numbers came from a blurred frame.
   It overstated the float-versus-chip gap about sixfold: -0.124 against a real
   -0.020 in confidence. Its conclusion, that the scorer must default to the chip
   arm, stands and is now done.

Also corrected in place rather than argued: a 208-flight entry that understated
my own error, a miscount of seven failures as eight, an invalid floor argument,
and a rendering confound in the decisive arm of the deadlock study, found by 14
of 15 refutation passes.

### Hardware

- **First hands-on session, Sep 17.** Confirmed an AI-deck 1.1, Rev D or newer,
  so over-the-air flashing is supported — that closes an open question in the
  flash runbook. The deck already carries the WiFi streamer, so nothing needs
  flashing to capture frames.
- Established that the flash is reversible: built the camera streamer ourselves
  twice from clean to a byte-identical 61,472 B image, and kept both images
  outside the build tree. This had been believed to be a one-way door needing
  MinHyuk to undo.
- Flight image rebuilds byte-identical to the Sep 13 one, sha256 261e20d8,
  340,896 B.
- Rehearsed the whole real-frame capture chain against a mock streamer, the way
  the lab operator will run it. The left/right mirror check gives the correct
  answer in every direction. Seven documentation errors found by typing the
  commands exactly as written, and fixed.
- Wrote `powering_the_drone.md` after the Sep 17 session, covering everything
  nobody had written down: no power button, the battery plugs, propellers versus
  motors, the AI-deck's WiFi AP, five to seven minutes of battery, the AI-deck
  browning out before the mainboard, and charging over the Crazyflie's micro-USB.
- **First real camera frames, Sep 22**, in the dorm, with two scripts that run with no
  internet (`camera_check.sh`, `empty_check.sh`, with a spoken countdown). The camera is
  not mirrored, the champion false-alarms on furniture, and the real stream format
  differs from the simulator's.
- **A read-only preflight tool** (`tools/hardware/preflight.py`) that locks every cflib
  command able to move or reconfigure the drone. First real run Sep 24: Crazyflie 2.1,
  firmware 2026.08, both decks, radio address E7E7E7E709.
- **Lighthouse positioning set up in the dorm, Sep 24.** Base-station channels set; a
  clean geometry solve (all samples under 2 mm) after two flawed attempts, which I kept
  on record; geometry exported and checked against the hardware.
- **`tools/lighthouse/tape_check.py`**, a read-only check of the room frame against the
  tape. It confirmed the yaw sign on real hardware, and a bare-floor vs book comparison
  ruled out floor reflection as the cause of the flawed attempts.
- Dorm layout sheets drawn to scale on the floor-tile grid, generated from
  `docs/hardware/make_dorm_sheets.py`.

### Documents, process and team

- The team fork, the workflow, and `DECISIONS.md`.
- Onboarding runbooks for Grace and Oaj, and fixes for the three setup bugs Oaj
  found on Linux.
- The real-frame capture protocol and its scoring tool.
- The lab-session runbook, the first-hour guide for the case where it is just me,
  and this pre-session checklist.
- Meeting reports, the Sep 2 meeting document, Week 1 report.
- This progress record, which Prof. Mok asked to be kept current so it can be
  edited into a final project report.
- 54 commits on `main` and the release branch at the last count, about 9,200
  lines added.

### What is NOT established

Worth keeping in one place, because several of these are easy to assume:

- **Nothing has been measured on real hardware.** Every number above is
  fake-quant, chip-simulator, or rendered.
- **How well the drone follows a real person is unknown**, and the published
  97-99% figures describe one photograph.
- **The pet problem is unsolved.** Settings are exhausted and the first
  retraining attempt did not beat them.
- **No flight has happened**, in the lab or anywhere else. The flight-controller
  software is written and passes an independent safety review in simulation only.
- **The bearing question has no lower bound**, and cannot get one from the
  simulator.
- **The yaw-sign chain is unverified**, which is why Lighthouse was scoped out of
  the first session.

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

- **2026-09-24.** Lighthouse set up in the dorm, with the hub, in person. Log:
  `docs/eval_results/2026-09-24-lighthouse-dorm-setup/`.

  First real preflight on the drone. The laptop sees both the Crazyflie and the
  Crazyradio through the hub, closing the Sep 17 radio question. Crazyflie 2.1, firmware
  2026.08, AI-deck and Lighthouse deck both detected, radio address E7E7E7E709. It
  still carried MinHyuk's lab geometry. I set the base-station channels: channel 1 at
  the window end, channel 2 at the door end.

  The first two geometry attempts were wrong, and I kept them in the log. Samples on
  the bare floor were about 79 mm off. A sample held over the origin read x = 1.29 m
  instead of 0, so the room frame was displaced by more than a metre, while the in-air
  samples agreed with each other to a few mm. The cause is most likely the glossy tile
  floor reflecting the base stations' light, which Bitcraze warns about. Retaking the
  floor samples on a book dropped every sample to 0.3-2.0 mm, and the SIDE mark then
  read exactly 0.61 m. That fix also changed how the samples were spread, so the
  reflection cause is a strong hypothesis, not an isolated one; a one-minute
  floor-versus-book test would settle it. It is the same hazard as the simulator's
  mirrored floor on Sep 12, this time on a real sensor.

  **11:12, tape check on the bare floor: 4 of 4 PASS, and the yaw sign is confirmed on
  real hardware** (a left turn reads +89.1 deg). The room frame matches the tape to
  about 1 cm. The same run weakens my floor-reflection explanation: the drone sat on the
  bare tile and read its position correctly. The likelier cause of the bad attempts is
  in-air samples bunched at one end, which a spread-out restart fixed. **11:18: the
  book run also passed 4 of 4 (after one rerun, when I had the drone 8 cm short of the
  mark and the check caught it), with the same numbers as the bare floor. So floor
  reflection is ruled out**, and I corrected my own earlier claim in the log. A left
  turn read +89 to +95 deg in all three runs. Still to do: export the geometry,
  preflight drone 2.

  **Afternoon.**
  - Drone 2 (address ...05, different from drone 1's ...09, so no re-addressing) passed
    the preflight and took the imported room geometry.
  - **First real-person detection grid, run by me alone with spoken cues**
    (`docs/eval_results/2026-09-24-grid-capture/`, partial: the battery died at clip 6).
    Standing off to the side at 2.1-2.4 m, I was seen strongly (median 0.77-0.88) and
    the drone would have locked on 71-88% of the time. Standing dead centre, it never
    locked.
  - The frames show why. At centre I was in front of the dark door, so my dark clothes
    merged into it. At the sides I was in front of bright wardrobe panels. **Background
    contrast matters a lot.** Position and background change together in this room, so
    the clean test is centre with a light sheet over the door.
  - The empty room gave 0 false locks again. The script now scores what it has when
    the battery dies, and can resume.
  - **Resumed at 18:46:** 8 of 9 positions. But the resumed clips were 2.3x brighter
    (something changed the light), so they are a second condition, not a continuation.
    In the bright light I was detected dead centre at 1.52 m (0.93), which is
    consistent with contrast but not proof. 2.13 m right was weak and is unexplained.
    Next time: the whole grid in one sitting, lights fixed.
  - **Night runs (19:42-20:48).** One clean dim-light grid, 7 of 9 positions. It
    repeated the pattern: left side seen and locked, dead centre in front of the door
    missed at 2.1-2.4 m. Two new findings came out of the failed attempts. (1) On a
    dying battery the camera sent near-black frames, the model called the empty room a
    person (0.83), and the drone would have locked on. That is a safety guard to add.
    (2) The camera starts in one of two brightness modes (~40 or ~90) under the same
    lights, and detection changes a lot between them. A script to pin down the cause
    (which drone, or each power-up) is ready.
  - **22:00, a complete grid, but the camera recorded only noise.** All 9 positions on a
    full battery, yet every frame was black (brightness 4). The model still called it a
    person (0.84) and the drone would have locked on, which makes the safety finding solid
    (169 black frames over two runs). It also means my "dying battery" explanation was
    wrong. The camera software sets its exposure once at start-up, and tonight the same
    room came out at brightness 4, 7, 40 or 90 depending on the power-up. Next: a
    power-cycle test to confirm, then a brightness check before every run.
  - **22:15, confirmed.** I power-cycled the same drone 5 times without touching
    anything and got brightness 146, 76, 42, 78 and 74. Exposure is random at every
    power-up, and our own flight software (`camera_if.c`) sets up the camera the same
    way. That goes to the firmware side. For now the grid script only records inside a
    fixed brightness band, so runs are comparable.

- **2026-09-23.** The USB-C hub arrived; hands-on work waited until Sep 24. Desk work
  to make the Lighthouse evening go smoothly:

  - Wrote `tools/lighthouse/tape_check.py`, a guided, read-only check that the room
    frame matches the floor tape. Its last step turns the drone 90 degrees left, the
    first real-hardware test of the yaw sign. Eight unit tests; tested end to end
    against the simulator's firmware.
  - Found and fixed a hidden bug in `preflight.py`. cflib sends a "stop" command right
    before closing a link. The read-only lock refused it, so the link never actually
    closed, and the error was being swallowed. Fixed in both tools, and all 41
    preflight tests still pass.
  - Redrew the dorm sheets to scale on the real tile grid. The floor is 5 x 11 tiles,
    later 5 x 10 once a stand took a row.

- **2026-09-22.** The micro-USB cable arrived, along with a second Crazyflie and
  two Lighthouse base stations. Four pieces of desk work, none needing the drone
  powered. Three are on branches with PRs (#4, #5, #6), none merged yet.

  **Plan for a dorm room** (`docs/hardware/dorm_setup.md`). The cable is also a
  full data link (`usb://0`), so deck inventory, battery and the whole Lighthouse
  geometry setup need no Crazyradio. Nothing flies in the dorm: Session A (real
  people) and the Lighthouse ground-truth session are both capture-only, and the
  follower can sit on a taped pose. The 3.5 m capture row probably needs a hallway.
  Checked the firmware source on whether the AI-deck and Lighthouse deck can share
  one drone: the deck drivers use different UARTs (AI-deck UART2, Lighthouse
  UART1), so the 2020 forum's "they conflict" answer is out of date. One doubt
  remains unverified: our GAP8 builds use `io=uart`, and the GAP8's UART is wired
  to UART1. A bench test is written into the plan.

  **A read-only preflight check** (`tools/hardware/preflight.py`, PR #4). Reports
  link, firmware, decks, battery, radio config and Lighthouse status, and cannot
  arm or write anything: it disables 40 cflib methods before connecting. 41 unit
  tests, plus a live run against the CrazySim firmware. Not yet run on the real
  drone.

  **The scorer now uses the chip network** (PR #5), from `before_the_next_session.md` §2.1 and §2.2:

  `score_real_frames.py` now takes `--backend {float,chip}` and defaults to chip,
  the network the drone actually flies. It reuses the simulator's own chip
  perception rather than a new copy of it. Every scored folder records which arm
  scored it, the model's hash and the output scale. The tests show three things.
  The chip scorer gives the same integers as the flight path on every frame. The
  float scorer's output is byte-identical to the old tool. And the Sep 17 rescore
  script, which I wrote, ran the image preprocess twice.

  That last point changes the Sep 17 story. Re-running my own script reproduces
  its table almost cell for cell, so the table was produced by the bug. The real
  gap between the laptop model and the chip is about a sixth of what I reported:
  -0.020 in confidence, not -0.124. It is still large for individual cells, which
  is why the default had to change.

  The Sep 16 frames had been deleted with a scratch directory, so I re-rendered
  them. On the float arm they match the originals on 13,000 of 13,000 frames.
  Then I scored them on the chip arm. Most Sep 16 conclusions survive. Two do not
  survive in full: the 25-degree left/right asymmetry disappears, and two of the
  four hard subjects only partly recover at 1.5 m. Everything is in
  `docs/eval_results/2026-09-22-sep16-chip-rescore/`. Still nothing on hardware.

  **First real camera frames, same evening** (`docs/eval_results/2026-09-22-first-real-frames/`).
  I taped the dorm floor, ran `camera_check.sh` on the real drone over its own WiFi,
  and stood on the marks myself. The stream worked: 49 of 49 frames. By eye, the
  camera is not mirrored. The scorer's check read FAIL, "NOT a mirror". The model
  said "right side" in 41 of 44 frames wherever I stood, because it was calling the
  loft ladder, office chair and blinds on the right of the frame a person, strongly
  enough to latch. Blanking that region moved its answer to centre, and mirroring the
  frame moved it to the far left, so the model is responding to the image, not
  stuck. With the distractor removed I was detected only weakly at 2.44 m (median
  confidence 0.23). That is one person and 44 frames, so a first data point, not a
  rate. The real stream also differs from what the simulator assumed: 162 x 122 not
  324 x 244, pixels 0-191 not 0-255, about 2 fps over WiFi. Next: a re-run with the
  right side cleared plus an empty-room clip, and ask MinHyuk about the stream mode.

  **Run 2, 18:27** (same folder, chairs moved out). An empty-room clip gave **0 false
  locks**; confidence peaked at 0.71, just under the 0.75 bar. The mirror check
  again printed FAIL, but going frame by frame shows why: I left the left mark
  early, and the empty frames read like the empty room. Every confident frame
  (>= 0.75) while I was on the left mark said left, and 10 of 12 confident frames
  overall were on the correct side. So the camera is not mirrored. The automatic
  check did not give a clean PASS because of this scene, not because of the camera.

  **The desk half of the Lighthouse ground-truth plan** (PR #6).
  simulator runs and no hardware: everything was checked against flights already
  on disk.

  `tools/lighthouse/pose_to_label.py` takes the follower's pose and the head
  beacon's position and gives the bearing, the range, where the person lands in
  the image, the x-bin and size bucket the network should output, and whether the
  person is in view at all. The head-to-body offset is written down in the code
  and its README: the label target sits half the subject's height below the top
  of the head, because that is the centre of a standing person's COCO box. It
  needs the team's sign-off.

  Checked against 267 archived simulator flights, the labels land within one
  x-bin of what the network said on every one of 81,368 frames, and on the same
  side of the image on 99-100% of frames where the person was clearly to one side.
  A flipped yaw sign, a flipped bearing sign or a mirrored room frame each drops
  that to between 0% and 38%, and the new left/right check refuses the labels.
  The joining mistake from Sep 13 (the follower's clock against the simulator's)
  reproduces as a 27 degree error at the 90th percentile, so the tool joins on
  the wall clock.

  The most useful finding was one I was not looking for. Eleven flights had
  crashed and five had a pose log that froze, and in both cases the camera kept
  streaming. Without throwing those frames away, the *correct* convention failed
  the left/right check. A Lighthouse dropout on the real rig is the same failure,
  so the pipeline now drops frames whose pose froze or jumped instead of guessing.

  `tools/lighthouse/align_clocks.py` finds the still-then-sidestep at the start
  and end of a recording and fits both the offset and the drift between the frame
  clock and the pose clock. In tests it recovers a planted offset to within 25 ms
  on synthetic data, and within a few ms on frames really sent through the mock
  streamer and cpx_grab. A tenth of a second of offset is about 3 degrees of error
  on someone walking at 1 m/s at 2 m, and zero on someone standing still. That is
  why the static marks alone would never find a clock error.

  Still unknown, and only the lab can answer: the real camera's field of view,
  where the lens sits relative to the Lighthouse deck, the real clock offset, and
  whether the lab drone's firmware flips the yaw command sign.

- **2026-09-20.** No experiments. Took stock, planned the ground-truth rig, and
  wrote down two things that should have been written down already.

  The drone has been sitting on the desk since Sep 17 because we do not have a
  micro-USB cable. That is the whole blocker: the battery charges through the
  Crazyflie's own mainboard and there is no separate charger, so without a cable
  every session is capped at the five to seven minutes a 350 mAh pack gives with
  the AI-deck streaming. The Crazyradio's USB-A-versus-USB-C problem is still
  unresolved from the same afternoon.

  The bigger piece of the session was the ground-truth plan. We are using the
  Lighthouse deck where the thesis setup used a Flow deck, and that is not a
  like-for-like swap. A Flow deck gives relative motion over the floor; it cannot
  tell you where anything is in the room, and it cannot tell you where the
  *subject* is at all. Lighthouse gives absolute pose for every drone carrying a
  deck, which is what makes the scheme possible: a second Crazyflie with its
  props off rides on the subject's head as a pose beacon, the follower logs its
  own pose, and the difference between the two, rotated into the follower's body
  frame, is where the subject truly was when each frame was taken. What the
  network said about that frame is the measurement. The gap between them is the
  training signal.

  The property that makes this worth the trouble is that **ground truth exists
  for frames where the network misses entirely.** Every other way we have of
  labelling real frames needs something to detect the person first. This one does
  not, and missed frames are exactly what the open fine-tuning problem needs.

  What I wrote down rather than built, because none of it needs the drone:
  the pose-to-label pipeline should be built and tested against the simulator
  first, where exact ground truth already exists; the head-versus-torso offset is
  a convention that has to be fixed in writing before any data is collected, or
  it becomes a systematic bias in every label; the frames come over WiFi and the
  poses over the radio, two clocks with no shared timebase, and a sync error
  there turns into a bearing error that grows with how fast the subject walks,
  which means it will look fine on the static marks and silently corrupt the
  moving data. All of it is in `docs/hardware/before_the_next_session.md`.

  This is also where the yaw-sign chain finally has to be settled. It is the
  stated reason Lighthouse was scoped out of the first session, and a sign error
  does not fail loudly — it produces a confidently mirrored label set, which
  would train the drone to steer away from people.

  Two things I want on the record because they are easy to lose. First, the
  static calibration case — subject on a taped mark, drone on a taped mark, thirty
  seconds, check the pipeline against a tape measure — catches almost all of the
  above and **needs no second drone at all**, so it survives the second deck not
  materialising. Second, none of the Lighthouse work should delay the capture
  session. The top open question in this project is where real people's detection
  margins sit, that needs WiFi only, and it is unblocked by a cable that costs a
  few dollars.

  Also added a full inventory section to this record, since Prof. Mok asked for
  documentation that can be edited into a final report, and backfilled the Sep 17
  afternoon entry below, which existed only as a hardware document and a commit
  message.

- **2026-09-17 (afternoon, first hands-on session).** Backfilled on Sep 20 from
  `docs/hardware/powering_the_drone.md` and commit b4e196f, which were written at
  the time; this entry was missing.

  The drone arrived around 1 pm and the afternoon went almost entirely to things
  nobody had written down. Every runbook in the hardware directory assumed
  MinHyuk would be at the bench handling the hardware, so not one of them said
  how to turn it on.

  What was established, from photographs and from trying it: there is no power
  button, and the Crazyflie powers up the moment the battery is connected through
  a pair of small white two-pin plugs that sit loose in storage. The propellers
  are not the motors. The deck is an **AI-deck 1.1, Rev D or newer, so
  over-the-air flashing is supported** — that closes an open question in
  `flash_runbook.md` §8. It raised its WiFi access point, `WiFi streaming
  example`, which means the streamer is already flashed and **nothing needs
  flashing to capture frames.** The battery gives five to seven minutes with the
  deck streaming, and the AI-deck browns out before the mainboard does, so the
  symptom you notice is the WiFi vanishing while an LED is still lit.

  The session ended on a flat battery. Charging is over the Crazyflie's own
  micro-USB with the battery still connected, we did not have a micro-USB cable,
  and so that was that. A scan also reported `Cannot find a Crazyradio Dongle`,
  and it was never established whether the dongle was plugged in at all or an
  adapter was missing.

  Half a result, and the half we got is worth having: the capture work needs only
  WiFi, no radio and no flashing, and it is unblocked the moment the battery can
  be charged.

- **2026-09-17 (early morning).** Caught something at two in the morning that
  would have quietly wrecked today's hardware session.

  The tool we use to score captured camera frames runs the wrong network. It uses
  the ordinary floating point model, while the drone runs the compressed integer
  version that actually fits on the chip. Those are not the same network, and on
  thirteen thousand frames they disagree by a lot: the float version thinks the
  model clears its confidence bar on fifty four percent of frames and the chip
  version says thirty. A third of the individual test cases shift by a quarter or
  more, and some go from always to never.

  This mattered today for two reasons. The protocol tells whoever is at the bench
  to score the real frames with that tool, so the numbers would have described a
  model we do not fly. And the comparison table I built last night was made the
  same way, so a real person could have looked like a perfect match to the
  simulation while both numbers were wrong in the same direction.

  I rescored all thirteen thousand frames on the chip network, published both
  columns side by side, and wrote a small script that does the same for any folder
  of real frames in about twenty seconds. The first hour guide now says to run
  both and which one to believe.

  I did not change the scoring tool itself. It is shared, the project's own rules
  say changes like that go through a branch and a review, and doing it unreviewed
  a few hours before the first hardware session is exactly the kind of thing that
  goes wrong. It should be the first job afterwards.

  This also means last night's angle measurements are all on the wrong network and
  need re-reading. I have flagged that directory rather than quietly fixing the
  numbers, because some of its conclusions will not survive.

- **2026-09-17 (overnight).** Tried to measure how much of yesterday's result was
  really about where the person stands, and the experiment failed in a way worth
  writing down.

  The problem was that the cardboard cutouts throw a rectangular shadow on the
  wall behind them, and that shadow only shows up when the person is off to one
  side. So my comparison was rigged: the off centre condition had an extra dark
  block next to the person and the straight ahead one did not. I re-flew both with
  shadows switched off, a hundred and fifty six flights.

  Everything got worse, including the control, which went from following
  ninety nine percent of the time to five. Subjects that work in every other
  condition dropped to nothing. That made no sense until I found why.

  The simulated camera has an automatic exposure loop that holds the average
  brightness of every frame at a fixed value. Turning off shadows made the room
  brighter, the exposure loop pulled the gain down to compensate, and the person
  came back with less contrast than before. The average brightness of my frames is
  identical in all four conditions, to within half a percent, because the sensor
  forces it to be. So I was not removing one artefact, I was changing the whole
  room and letting the camera re-normalise the person along with it.

  That is a real lesson about this rig and it applies backwards too. Anything that
  changes what else is in the picture will change how the person looks, even when
  nobody touched the person. That includes the floor reflectance work from last
  week.

  So I still cannot say how much of yesterday's improvement is genuinely about
  where the person stands. It remains an upper bound with no lower bound. The
  right way to do it is to stop the cutout alone from casting a shadow while
  everything else in the room still does, which is a much narrower change, and a
  hundred and fifty six flights of that are running now.
- **2026-09-16 (late evening).** Found out that a good chunk of last night's
  headline is about where the person stands, not who the person is.

  It started with the one subject I could not explain: high ranking, never
  followed on the standing scene at any distance, always followed on the moving
  one. Chasing it turned up something about the standing scene itself. The drone
  never moves on that scene, because it never locks on, so every frame of every
  flight is the same single photograph with different camera noise on top. Eight
  repeats of a standing test is one picture drawn eight times, not eight tries.
  My confidence intervals treated them as eight and they are closer to one.

  Then the real problem. The standing scene puts the person a metre off to one
  side, about sixteen degrees off centre. The number I had used to predict how
  detectable each person is was measured with them straight ahead. Those are not
  the same picture, and the gap averages about twelve points of confidence and
  reaches thirty four for one subject. The three people whose numbers looked
  strangest are exactly the three with the biggest gaps. So "the ranking does not
  predict the outcome" is partly "I predicted one pose using a measurement of a
  different one."

  I built the test properly rather than arguing about it. Thirteen thousand
  rendered frames, all thirteen people, five distances by five angles, run through
  the same scoring tool tomorrow's real capture will use. Straight ahead at three
  and a half metres, four of the seven people the drone ignores go from never
  clearing the confidence bar to clearing it on ninety five to a hundred percent
  of frames. Four others fail either way and are genuinely hard. Being off centre
  is nearly free up close and costs about a third of the confidence budget at
  three and a half metres.

  Two things I expected and did not get. The dip at two and a half metres that an
  earlier measurement found for every subject does not reproduce cleanly here; the
  low point lands at three metres instead, and only eight of thirteen dip where
  they were supposed to. And there is a small left-right difference, but it favours
  the side the failing scene is already on, so it cannot be the explanation.

  None of that changes what the drone did. It changes what those flights are
  allowed to mean. The twenty nine percent figure is still what happened on that
  scene, and it is not a statement about what the network can see.

  Those hundred and four flights have now landed, and they say the same thing the
  rendered frames did. With the person moved straight ahead at the same distance,
  the drone follows eight of the twelve instead of five, and the median tracking
  fraction goes from zero to ninety six percent. Six people improved and nobody
  got worse. Three of them went from never being followed to being followed
  ninety nine percent of the time. The four genuinely hard ones sit at zero in
  both conditions, so this is not a blanket improvement, it separates people the
  network can see from people it cannot.

  One thing that surprised me and is worth carrying forward: being above the
  confidence bar most of the time is not enough. A person the network clears the
  bar on for forty five percent of frames gets followed essentially never. At
  ninety five percent they get followed sixty one percent of the time. At a
  hundred, ninety nine. The drop-out rule is unforgiving, so anyone reading the
  frame statistics as a tracking prediction will be too optimistic.

  Thirteen independent checks ran against all of that, and the headline did not
  survive intact. The cards the simulator uses are opaque rectangles, and the room
  light comes from one side with no sideways angle, so each card throws a
  rectangular shadow onto the wall behind it. Because the wall is three and a half
  metres further back than the person, the shadow lands offset from the card by an
  amount that grows the further off centre the person stands. Dead ahead it hides
  behind them. Off to the side it does not.

  So the comparison I ran was not clean. The off centre condition was showing the
  network an extra dark block glued to the person that the straight ahead
  condition did not have. Every number I quoted is an upper bound on what being
  off centre costs, not a measurement of it. A real person does not carry a
  rectangular shadow around with them.

  I checked it myself, got the image scale wrong, concluded it was not there, and
  had to redo it. It is there on thirteen subjects out of thirteen in one
  condition and zero out of thirteen in the other. The checker found it and I
  nearly talked myself out of it.

  Three other things of mine went too. I counted four subjects where there were
  five, I left out the one data point that turns my claimed steep curve into a
  flat step, and I named a cause the logs contradict: the subject I said could not
  lock on actually locks on within a third of a second every single time and loses
  the track later while closing in, which is a different problem entirely.

  What still stands is that four of the twelve are not seen at three and a half
  metres no matter which way they face, and that the original twenty nine percent
  is not a clean statement about people. What I cannot yet say is how much of the
  improvement is really about where they stand.

- **2026-09-16 (evening).** Switched off the simulator and spent the night
  getting ready for real hardware, because the drone arrives tomorrow at one.

  The biggest thing I fixed was a risk nobody had checked. Our flashing guide
  said that putting our own app on the drone's camera board destroys the camera
  streamer, and that only MinHyuk could put it back. That would have made
  tomorrow a one-way door: capture first and flash last, and if the flash went
  wrong there was no way back to a working camera. It turns out the streamer's
  source code has been sitting in our own workspace the whole time. I built it,
  built it a second time from clean, and got a byte-identical image both times.
  Both that image and our flight image now live outside the build folder where a
  cleanup cannot delete them. The flash is reversible now. I have written plainly
  that the build is verified and the flash of it is not, because there has never
  been a drone to try it on.

  I also rebuilt our flight image from scratch and it came out byte-identical to
  the one from three days ago, ran the scoring tool's full test against the real
  network and got thirty nine of thirty nine, and ran the whole capture chain
  against a fake camera to make sure the plumbing works: three clips, a hundred
  and eight frames, scored clean.

  Two traps turned up in that dry run and both are now written down. The
  left-right sanity check needs clips taken from both sides of the centre line
  and says nothing at all if it only gets head-on ones, which is a quiet way to
  miss a model that steers backwards. And if the reported bearing error comes
  back large, the floor marks and the labels disagree, not the network.

  Last thing: I wrote down what I expect real people to do before seeing a single
  real frame, so it can be wrong in public the way last night's prediction was.
  The short version is that I expect a real person standing three and a half
  metres away to be tracked more than eighty percent of the time, and nobody to
  come back at exactly zero. If that holds, the gloomy result from the twelve
  simulated people is about how we build scenes and not about the network. If it
  fails, the network is the blocking problem and that is the most important thing
  this project could learn.

- **2026-09-16 (overnight, 156 more flights).** Tested the fix I proposed last
  night and it mostly does not work. The idea was simple: the drone refuses to
  move until it has locked onto someone, so let it creep forward while it is
  still unsure and it will get close enough to see them. I flew the same thirteen
  people with the person standing at one point six, two point two and two point
  eight metres instead of three point six four.

  In the two distances that are cleanly comparable, one of the seven people the
  drone ignores is rescued. Six are not. Four of them are not picked up even at
  one point six metres, which is closer than the drone will ever get. Their
  problem is not distance.

  The nearest distance looked much better, eight of twelve instead of five, and I
  cannot use it. The room's far wall is four metres tall, so from the camera its
  top edge lands about a sixth of the way down the picture. At one point six
  metres the person's head rises above that line and sits against the sky instead
  of the wall. The cutouts are rectangular cards painted the wall's colour around
  the edges so the card disappears, and against sky it does not. So that distance
  changes what the network sees in a way that has nothing to do with how far away
  the person is, and it happens to be the distance where two of my three rescues
  appear.

  I had written the opposite conclusion first, and reached my number through an
  argument that was wrong. I claimed the drone cannot get to one point six metres
  because flights settle around two point two. That figure is measured entirely
  after the drone has already locked on, and the creep I was proposing happens
  before that, in the part of the code where forward speed is hardwired to zero.
  One of my own flights has the drone sitting unlatched at one and a half metres
  for four seconds. I also described the forward controller as steering toward a
  target distance when it does nothing of the sort: the size estimate only comes
  in four steps, and the drone simply stops anywhere inside the middle one. And I
  wrote "seven failures" and then listed eight.

  Fifteen independent passes were made over that first write-up with instructions
  to tear it down. Fourteen found something. One of them found the wall, which I
  would not have.

  Worth saying plainly: creeping forward is still cheap and still worth building,
  and it needs a second change beside it, because the two people that do get
  picked up close then lose the track immediately as the drone backs away to its
  usual distance. But this run does not show that it helps much.

- **2026-09-15 (evening, 208 flights).** Answered the question this project has
  been unable to answer since August: how well does the drone follow people,
  plural. Every tracking number we have published, 97 to 99 percent, came from
  one photograph. I flew twelve more.

  The twelve are not a selection. An earlier study wrote down a screen for who
  counts as a usable subject, applied it to all 266 people in the cohort, and
  published the verdict for every one. Twelve passed. I flew all twelve, plus the
  original photograph as a reference, on both person scenes, eight times each.
  208 flights, every one valid, about four hours.

  The original photograph latched on all sixteen of its flights and tracked 99
  percent, exactly as published. The twelve screened people latched on 29 percent
  of the standing flights and 68 percent of the moving ones. On the standing
  scene the median person tracked nothing at all.

  I was wrong about why, and I was wrong again about how wrong. I predicted
  before flying that the easy-looking people would all do well and the
  hard-looking ones would all fail, and wrote that prediction into the repository
  so it could fail. It failed on its first half. Six of the seven easy-looking
  people missed the bar I had set on the standing scene, two of them never
  getting going at all in eight tries. Only one of the seven met it. My first
  write-up said four, because I quietly held two of them to a harsher standard
  than the one I had just written down. The hard-looking half of the prediction
  held perfectly, on both scenes.

  The ranking I used to choose them averages how visible someone is across six
  distances, including distances these scenes never fly at. That was the mistake.
  What separates them is the share of frames where the model's confidence clears
  the bar it needs, at the distance the drone actually sits. I also claimed
  average confidence was not good enough for this and that was false: on the same
  frames it sorts the thirteen people exactly as well.

  Reading the controller turned up something worse than a detection problem. The
  drone does not move at all until it has decided it is following someone. It
  starts three and a half metres away, and the people it cannot see only become
  visible closer than that. One flight record is the whole story: the drone sat
  at the origin, three point six four metres out, for forty five seconds, and
  never moved a centimetre. Across all 208 flights, every single latch happened
  with the drone still parked at its start position.

  I overstated that too. I first wrote that such a person can never be acquired,
  and one of the twelve disproves it: it never clears the bar on the standing
  scene but gets picked up on seven of eight moving flights, because on that
  scene the person simply starts closer. The honest version is narrower. While
  the geometry is frozen nothing can change, so a person below the bar at the
  start stays below it for the whole flight. That is still worth acting on, and a
  controller that creeps forward while unsure is a far cheaper fix than a better
  network. A second suite of 156 flights is running now to test it, putting the
  same people at one point six, two point two and two point eight metres.

  I also checked whether the difference was the people or the cardboard, since
  the panels are cut to each photograph's proportions and card width did track
  visibility. Two of the subjects turn out to render to exactly the same card
  width, and one of them is never followed while the other is always followed, on
  both scenes. So it is the person and not the width. It is not a complete
  answer, because those two differ in how much of the card is actually person,
  and no pair in the twelve holds both fixed.

  Almost all of this came back from checking. I had eighteen independent passes
  made over the claims with instructions to tear them down, and thirteen
  succeeded. None of them touched the measurements themselves, which came back
  identical on a full independent recount of all 208 flights. What was wrong was
  what I said the numbers meant.

- **2026-09-15 (afternoon).** Answered two questions that had been sitting open,
  neither of which needed the simulator.

  MinHyuk suggested we try YOLOv11 nano, which he has had good results with on a
  real drone. David warned that he had struggled to quantize YOLO models and told
  us to look at the architecture before spending training time on it. I wrote
  that up from the published architecture first and got the mechanism wrong, so I
  exported the models and measured it instead. YOLOv11 nano at our input size is
  355 nodes. Our code generator stops at node 10, on an operator it has no rule
  for, and 21 nodes are rejected that way. The part I had missed is worse: 112
  more nodes sit on a list the parser accepts and then silently deletes,
  including every one of the 78 sigmoids and all 21 of the joins that build the
  feature pyramid. So working around the first failure would not give us a YOLO,
  it would give us a build that succeeds on a network with its skip connections
  removed. I ran our own champion through the same check as a control and it has
  zero rejections. The useful half of MinHyuk's suggestion survives: YOLO is
  worth running off the drone to label the real frames we capture, which is
  manual work right now.

  The other one was the uncertainty gate, M10, which counts frames where the
  model is neither confident enough to lock on nor unconfident enough to let go.
  Its line was drawn for the old confidence bar and I was supposed to redraw it
  for the new one. I re-scored all 287 flights we have and found that the band
  moving is the least of it. The line's own stated justification is that
  confidence sits at 0.96 or above on essentially every frame with a person, and
  that is only true of the standing scenes. On moving scenes the model spends a
  normal part of every flight in the uncertain band. At the old bar every static
  flight passed the line and only half the moving flights did, so it was never
  one line. And the number drifted by a factor of 76 across four of our own
  suites on the same scene, because fixing the mirrored floor made the scene
  harder. I am not going to fit a new number: all 76 clean flights use the two
  scenes built around the one unusually easy person, so anything I fit today
  bakes that person in exactly as the old line did. What I did instead is show
  that a version of the measurement that does not depend on the confidence bar
  holds its line perfectly on held-out flights where the current one covers 71%.
  That is the change I am proposing, with the numbers left unset until the scene
  suite covers a realistic range of people.

  I also answered MinHyuk's objection to the person study. He said that with a
  real camera you would almost never have an entire person in the frame, and if
  he is right then the study measured the exception and skipped the normal case.
  The geometry says he is right about cameras in general and wrong about our
  drone. Our camera is level at 0.8 m with a 70 degree square crop, so a 1.7 m
  person stops fitting below 1.29 m, and the drone never gets closer than 1.55 m
  in any flight we have. One caveat that does bite: a 1.9 m person is cut off
  below 1.57 m, which is inside the range our flights actually reach, so the
  1.7 m written into the scene is doing real work.

  Then I checked the detection side using COCO's own annotations, and the answer
  split in a way I did not expect. Partial people are worse, but only when they
  are cut off by the frame edge. People who are merely occluded, standing behind
  furniture or another person, cost nothing measurable. People who are seated or
  lying down cost nothing either. The worst case is a person with their head cut
  off, which is the drone-shaped cut. Reporting "partial people are harder" as
  one number averages a real effect with a null one. None of this changes the
  headline: the simulator still shows the drone never latching, while a real
  whole person falls below the let-go bar on only 7% of frames, so the unusually
  easy cutout is what to fix before the lab, not the field of view.

- **2026-09-15 (overnight).** Spent the night on one question: does the
  simulator predict what the real drone will do? Nobody had checked, and the
  answer came back twice, in opposite directions. The method was to show the same
  network a simulated scene and real COCO photographs, sized so the subject looks
  the same size in both, and compare.

  For pets the simulator makes the problem look about three times worse than it
  is. A rendered dog is much easier for the model to spot than real dogs are, so
  the drone chasing a dog across the room says more about a flat cardboard cutout
  than about real animals.

  The person result is the one that matters. Our two person scenes are built from
  the same photograph, and that photograph sits near the 98th percentile of how
  easily this model detects a person. We picked an unusually easy person, by
  accident, back in August. I rebuilt the same scenes around a typical person and
  flew them: the drone never started following. Eleven of twelve flights it sat
  there, while the original photo still scored 99% on the identical rig. The
  obstacle is the rule that needs three confident frames in a row before locking
  on. An ordinary person produces confident frames that never line up.

  I then checked whether the confirmation threshold we shipped on Saturday caused
  this. Mostly it did not. For three of the four ordinary subjects no threshold
  helps, because the confidence never comes close to any of them. Putting it back
  to 0.70 buys 2.4 seconds of tracking instead of 1.9 and makes the pointing
  worse, so the setting stays.

  Rendered cutouts are harder for the model than real people, so this brackets
  the answer from the pessimistic side. The truth is somewhere between 0% and
  99%, and I cannot narrow it from a simulator. That is exactly what the lab
  session is for. Also fixed a real bug in the training code that had been
  quietly throwing away a model's learned calibration on startup, plus two
  scoring defects.

- **2026-09-14 (night).** First real swing at the pet problem by retraining,
  now that both drone settings are exhausted. I fine-tuned the model we fly for
  five short rounds, each one training it harder on the negatives it currently
  gets wrong, and after every round measured how well it still finds people and
  how often it mistakes a pet or mannequin for one. False alarms fell from 24% to
  9% at best, and 13% in the round I would actually pick. Every round found
  slightly fewer people than the model we fly, by about half a point of F1.

  So retraining moves something configuration could not move at all, at a cost
  that is small but real, and the team has to decide whether half a point of
  accuracy is worth a large cut in false alarms. Two limits on that. It is one
  seeded run, and our own rule says three before quoting a training number; the
  best round's 9% bounced back to 13% the very next round, so I do not trust 9%
  yet. And none of this is the chip, because the release path throws away exactly
  the calibration this training produces. That is Grace's preserve-QAT-alphas
  task, and I measured the same effect costing part of the gain at the very start
  of the run. Numbers, commands and caveats in
  docs/eval_results/2026-09-14-champion-hardneg/.

  **Correction, added the same night after an independent re-check.** Every
  individual number above reproduces exactly, but the headline comparison was
  wrong. The false-alarm rate was read at one confidence setting and the accuracy
  at another, and the drone only runs at one setting. Compared properly, at equal
  person-finding ability, the fine-tuned rounds are no safer around pets than the
  model we already fly, and turning the existing model's confidence dial up
  reproduces almost the entire apparent improvement. That dial is the lever we had
  already swept in flight and rejected, so this run found nothing new. The
  accuracy cost does hold up.

  Three things survive. The data-mix measurement, the discovery that the release
  path's calibration reset costs part of any gain before training even starts,
  and one real lead: the confuser model is measurably safer at equal
  person-finding ability, so the effect we want is reachable. We just have not
  found a recipe that captures it without wrecking recall. Details in section 0 of
  docs/eval_results/2026-09-14-champion-hardneg/.

- **2026-09-14 (late).** Swept the drone's second threshold, the one that
  decides when it lets go of something it is following. This was the lead from
  the earlier run and the answer is no. It does not close the pet problem at any
  value I tested, and turning it up hurts: at the highest setting the drone
  dropped a walking person six times across two flights, where at the shipped
  setting it never lost them once. Every drop costs a full re-acquisition. Both
  settings are now exhausted in flight, which leaves retraining, which depends on
  Grace's work.

  The bigger finding is about our own measurements. The same configuration scored
  11 of 16 in the afternoon and 2 of 7 in the evening, same scene, same seeds.
  This test case drifts between sessions by as much as the effects we are chasing.
  From now on it only gets compared within a single interleaved run, and the
  afternoon's 69% is one session's number, not the rate. I should not have offered
  it as a rate.

- **2026-09-14 (evening).** Used a spare hour to answer properly the question I
  got wrong this morning. Sixteen fresh pet flights at the shipped setting: 11
  pass the half-metre limit, 5 fail. That is a per-flight pass rate near 69% with
  a wide range around it, so the honest description is a weighted coin. Every
  number was re-derived independently from the raw flight logs.

  The mechanism is worth more than the rate. Every flight locks onto the dog
  within a couple of seconds at almost identical confidence, and nothing before
  that moment separates the good flights from the bad. What differs is whether the
  lock lets go, and a second threshold controls that, one the earlier sweep never
  touched. Cheap next experiment. Also gave the two camera settings that had never
  been flown their first verdicts: low light is fine, colour Bayer genuinely hurts
  tracking. Found a quirk in my own scorer along the way, which grades any
  non-standard camera against the strictest bar. Flagged, not fixed.

- **2026-09-14 (afternoon).** Flew the full 14-case suite at the setting that
  now ships, 56 flights, so the lab has a reference flown at the real
  configuration. It corrected me. Yesterday I reported that the higher
  confirmation bar fixed the pet problem, on the strength of four flights that
  all passed. Four fresh flights at the same setting, same scene, same model, same
  random seeds, gave 0.71, 0.73, 0.46 and 0.34 m against a 0.5 m limit. Two of
  four fail.

  The change stays, because it beats the old setting on every pet measure and
  costs nothing on people, but "fixed" is withdrawn and recorded as withdrawn. The
  lesson is about evidence and not about the drone: four repeats were not enough
  to call a pass, and the random seed does not pin what the drone does in the
  loop. A second prediction of mine was backwards too. One scoring gate measures
  the share of frames in the uncertain band, and raising the bar widens that band
  by definition, so three cases still fail it for a reason that has nothing to do
  with the drone's behaviour. Flagged for the team as a gate to re-calibrate.
  Everything else held: safety cases clean, no upsets in 56 flights, people
  tracked as before.

- **2026-09-14 (later).** Rehearsed the lab measurement chain end to end, the
  way the operator will run it next week, with the real champion network on
  realistic rendered frames instead of the stand-in models used until now. The
  left/right mirror check, which decides whether the drone would steer the wrong
  way toward a person, gave the correct verdict in every direction and a second
  agent reproduced each one from a fresh shell. The real network sees a rendered
  person at every distance; an earlier "0% detection" scare was the crude test
  drawings, not the model. The test path that exercises this with the real
  network had never been run before today; it passes 39 of 39. One thing the
  operator must expect: a plush toy or pet registers as a false track at the new
  threshold, and the protocol now says to write it down.
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
  instead of trusting the paper estimate, and the paper estimate was wrong. 96
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
  works, since it needs no retraining. I am flying it before trusting it, because the paper version re-scores pictures from flights taken at the
  old setting.

- **2026-09-12 (late night).** Flew the two candidate models against each other,
  which had never been done: every closed-loop flight in this project had used
  the champion, so the team was about to choose between a model with flight
  evidence and one with none. 48 flights in one session, alternating between the
  models so neither got an easier machine. The confuser does exactly what it was
  designed to do, and it is not enough: it essentially stops chasing the dog
  (0.22 m of drift against the champion's 0.97 m, and it passes the safety limit
  the champion fails), but it does not follow people at all, tracking a
  standing person on 0% of frames across four flights. The obvious objection is
  that I judged it using settings tuned for the other model, so I re-scored every
  frame at thresholds from 0.45 to 0.80: the champion at its normal setting is
  better than the confuser at every setting, on both accuracy and false alarms at
  once. That bounds the question without closing it, because it re-scores
  frames from flights the confuser never got to steer. Also settled two smaller
  things: there is no close-range detection weakness (the evidence for one was a
  clock bug in my own analysis, now retracted), and a controlled repeat confirmed
  the dog improvement is real.

- **2026-09-12 (night).** Re-flew the seven test cases that still had no clean
  data, so the team finally has a complete 14-case baseline with no mirror in it.
  28 flights, all valid first time. The overall picture improves from 7 passing
  and 7 failing to 9 passing and 5 failing: three cases pass now that the
  distance error is gone. The important one is the pet case, which is the
  evidence the team will use to choose between the two candidate models.
  **Most of the dog-chasing was the mirror.** With a matte floor the drone still
  notices the dog, but lets go almost at once instead of following it across the
  room: it drifts 0.41 to 0.93 m instead of 2.30 and 2.67 m, and stays latched
  for 1.3 to 3.6 seconds instead of about 15. It still fails its half-metre
  safety limit on three of four flights, so it is much less bad, not fixed. Two things got worse and I am not burying them: one occlusion case now
  fails because the drone takes 3.2 seconds to re-find the person instead of
  0.5, and part of that may be a genuine weakness at close range, where the
  detector loses a person who fills the frame. That weakness was invisible while
  the mirror kept the drone too far away to meet it. Also installed the missing
  image library the lab fallback viewer needs, pinned so it could not disturb the
  numpy version the training pipeline depends on.

- **2026-09-12 (late evening).** Settled the question the earlier re-fly left open. The
  first run had suggested that removing the simulator's mirrored floor made the
  drone unstable, which would have made the fix a trade instead of a win. It
  did not hold up: a controlled re-run, with the source files locked byte for
  byte across both conditions and the two floors alternated flight by flight,
  flew 56 flights and found no upsets in 28 on the matte floor against one in
  28 on the mirrored floor. The earlier result was an artefact of running the
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
  morning was wrong, and corrected the record in place. The
  simulator suite reported that the drone parks about 3 m from the person instead
  of 1.94 m, and I had written that the network's size head "over-reads by
  1.6-1.8x". It does not. The simulator's floor material is 20% reflective - a
  mirror - so the renderer draws each person's reflection hanging below their
  feet and the network reads the two as one object. Measured by rendering every
  frame twice, once with the person removed, the subject is drawn 1.53x taller than it should be at 2.4 m, rising to 2.01x at 3.8 m - the same direction and
  the same size as the 1.3-1.6x "over-read" I had reported, over the same
  distances, and growing with distance the same way. Tested away from the simulator, on 2,635
  real COCO photographs with exact ground truth, the size head is unbiased -
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
  MinHyuk Park to meet the team in the lab next week to work with the real hardware - the project's first hardware session. David Liu replied that it
  is impressive the simulation predicts the AI-deck's behaviour. On research
  credit, Prof. Mok said periodic documentation "will come in handy if the team
  wants to get an official grade for an undergrad research project from UT",
  which supports the idea but does not yet give the registration process, so I
  still need to ask. Started preparing for the hardware session, where the
  honest position is that several things have never touched anything real: the
  GAP8 build tooling needed to flash our app is missing on this Mac, and the
  camera capture tool has never run against an actual byte stream. Both are
  being fixed and rehearsed against substitutes before we go.

- **2026-09-12 (overnight).** Rebuilt the simulator so it resembles the real thing, then used it to test the drone we actually intend to fly. Three
  It now carries a model of the real camera sensor (its auto-exposure, 60 fps timing,
  noise and motion blur), a mode that runs the real chip network and the
  chip's own image preprocessing in the loop instead of the float model, and a
  scene suite of 18 scenes built from JSON definitions with full ground truth.
  Added a scorecard of ten measurements with pass/fail limits, and flew a
  14-case matrix, 37 flights, 36 valid: 7 cases pass, 7 fail. None of this
  touched hardware. In simulation the drone chases a dog (confirmed in
  0.31 s, drifts 2.3-2.7 m against a 0.5 m limit) and this survives every
  realism setting; it does not hold its distance with the chip network
  (about 3 m instead of 1.94 m, in every chip configuration) - *corrected the
  same evening: the observation holds, but I had blamed the network's size head
  and the cause is the simulator's reflective floor plus an unreachable target;
  see the 2026-09-12 (evening) entry*; measured one at a
  time, the realistic camera costs 0.32 m of distance error, the chip network
  0.13 m, and the chip's slower frame rate 0.10 m; pointing accuracy and the
  safety rules survive all of it. Also fixed three faults in my own scoring
  tool: it reported the first failing repeat of a safety limit instead of the
  worst one (the pet drift was published as 2.301 m when the worse repeat was
  2.666 m); re-scoring the published evidence folder destroyed it, because
  flights whose control log is trimmed for size were rewritten as "invalid" -
  it now reads what those flights measured and says so on screen; and the
  folder's own metadata named the wrong sweep. The published evidence now
  re-scores to a byte-identical result twice running. Known and unfixed: on the
  worst frames the sensor model costs 7.27 ms against a 5 ms budget; subjects
  are still flat rectangular cards; nine camera parameters are taken from the
  datasheet and not measured; one far-person scene does not test what it
  was meant to.

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
