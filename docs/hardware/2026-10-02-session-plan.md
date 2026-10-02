# Fri Oct 2: the plan (read before bed)

Rewritten Thu Oct 1, 11 pm, after two expert reviews (an ML/data lens and a
systems/flight lens). Both reached the same verdict. **The model is not the
bottleneck. Two things are: the camera image, and the fact that nothing has run on
the drone's chip yet.** So tomorrow is about camera facts and, if you say yes, the
chip. It is not about collecting a dataset.

## Tonight (5 min)

- **Charge the batteries.** One cable means one at a time, about 40 min each. Drone 09
  first, then move the cable to drone 05. Skip any battery that looks puffy.
- In the morning, confirm "full" with the preflight (`pm.vbat` about 4.15 V or more at
  rest), not just the LED.
- Leave the base stations unplugged until morning.

## 1. Base stations (30 min, first thing)

1. Put the moved stand back on its tape. **Also match its height and the ball-head
   angle.** Tape fixes the floor spot only. Then take a photo of each stand so
   next time is easy.
2. Plug both stations in at the wall and wait 1 minute.
3. Drone 09 on the hub cable:
   `~/Downloads/drone/cfloaderenv/bin/python tools/hardware/preflight.py`
   Both stations should show as seen.
4. Run the tape check on drone 09:
   `~/Downloads/drone/cfloaderenv/bin/python tools/lighthouse/tape_check.py`
   - **4/4 PASS:** done, the geometry is still good.
   - **FAIL:** redo the cfclient geometry wizard (about 10 min). **Spread the XYZ samples
     across the whole floor.** Bunching them at one end is what broke Sep 24. Then export
     the geometry and import it on drone 05.
5. Run the same tape check on drone 05. It has been pending since Sep 24.

## 2. Camera facts (45 min). These unblock all future data.

1. **Field of view and aim, with the 2-minute bottle test.** Stand a bottle 2.0 m in
   front of the lens. Slide it sideways until it just leaves the frame, then write down
   how far left it went and how far right. Commands are in
   `lab_session_runbook.md` §4.0a (a).
   - Every label we compute assumes a 70° view nobody has measured.
   - The camera also looks aimed about 6° left of the tape line.
2. **The dark-door question, as 4 clips of 6 s** at the CENTRE mark (2.13 m):
   {door bare, light sheet over the door} × {dark shirt, light shirt}. This settles
   contrast versus position.
3. **An empty-room clip at the start and at the end.**
4. **Skip finishing the 9-cell grid.** The WiFi stream (162×122, about 2 fps) is not
   the image the flight app uses (324×244, about 15 fps), so more grid frames answer
   the wrong question.

## 3. Put the model on the chip (about 1 h, only if you say yes in the morning)

Use **drone 05's AI-deck only**, and leave drone 09 untouched. Flashing goes over the
radio, so your laptop keeps its internet and I can help live. Steps are in
`docs/hardware/flash_runbook.md`, and the images are already built.

1. **Bench image** (the known one, `_prebuilt_champion/champion_bench.img`): look for
   `match=1` and `mismatches=0`. Write down `infer` and `period`.
2. **Flight image with tonight's dark-frame guard**
   (`_prebuilt_dark_guard/`, flight sha `ce9fa7b9…`, PR #12):
   - look for `hz` around 10-15;
   - walk in and out and check `trk` goes 0→1→0, and that left/right are correct.
3. **Five power-ups** (unplug and replug the battery, don't touch the drone). Each
   time, write down the `exposure …` line and three `mean=` values. This is the first
   look at exposure from inside the chip.
4. **Cover the lens** with a cap or tape for 10 s.
   - Expect `dark=` counting up and `trk=0`.
   - **`trk=1` must never appear.**
   - Write down the covered `mean=`. It tells us whether the guard's floor of 12 is
     right. Full procedure: HANDOFF §5.6 in PR #12.

Side effect: drone 05 stops being a WiFi camera. That also fixes the problem of two
drones broadcasting the same WiFi name. **Correction to an earlier claim:** the
"restore" image is a 324×244 streamer, not the 162×122 one on the decks now. It still
works, just not identically.

## 4. Lighthouse static check (10 min)

`tools/lighthouse/README.md`, "static taped-mark case": stand on the marks, then turn
the follower 30° left on its stand. You should move to the RIGHT side of the label.
This needs only drone 09; the README shows where to type your position by hand.

**Optional: one walking recording to prove the pipeline.** It uses the new recorder
(PR #9, not merged yet). Don't build a dataset yet. Before you start:

- **Unplug drone 05's AI-deck from its stack,** after step 3 if you did it. Both decks
  broadcast the same WiFi name, and the recorder refuses if the beacon has a deck.
- Run `--identify-deck` once, with only drone 09 powered.
- Make the recording at least 60 s long.
- Walk side to side, clearly left and right of centre, 1.5-3.5 m away.
- Measure your height and the beacon's height above your head.

The commands are in the PR's `tools/lighthouse/README.md`, "Recording a session". Until
the PR is merged, use `R=~/Downloads/drone/wt_lh_recorder`.

**End of day:** run the tape check again.

## Decisions only you can make (tell me in the morning)

1. **Flash drone 05 tomorrow?** (step 3)
2. **The image path:** do we train on frames from the flight app's own camera path, or
   switch the flight app to the stream's format? Both reviewers say decide this
   **before** collecting data at scale.
3. **The real test set rules** (a proposal is coming tonight):
   - people in the test set never appear in training;
   - you are training/dev only;
   - 2-3 friends, about 15 min each, are the test set.
4. **Where we're allowed to fly** (ask Prof. Mok). "Nothing flies in the dorm" stands
   until then.

## Buy

- 4+ batteries.
- An external 1S charger.
- A second micro-USB **data** cable.
- Prop guards.

## Stop doing (both reviewers)

- Simulator studies of perception.
- Pet false-alarm work.
- COCO-only training tweaks.
- Training for exposure: fix it in the camera firmware instead.
