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

1. **Bench image:** look for `match=1` and `mismatches=0`. Write down `infer` and `period`.
2. **Live-camera image:** look for `hz` around 10-15. Walk in and out and check `trk`
   goes 0→1→0, and that left/right are correct.
3. **Cover the lens.** Expect a **false lock**: today's image locks onto dark noise.
   That's the hazard we are documenting. Tonight's firmware branch adds a dark-frame
   guard. That gets flashed on a later day, after you OK it.

Side effect: drone 05 stops being a WiFi camera. That also fixes the problem of two
drones broadcasting the same WiFi name. **Correction to an earlier claim:** the
"restore" image is a 324×244 streamer, not the 162×122 one on the decks now. It still
works, just not identically.

## 4. Lighthouse static check (10 min)

`tools/lighthouse/README.md`, "static taped-mark case": stand on the marks, then turn
the follower 30° left on its stand. You should move to the RIGHT side of the label. One
short walking recording is fine, but only to prove the pipeline (if tonight's recorder
PR is ready). Don't build a dataset yet.

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
