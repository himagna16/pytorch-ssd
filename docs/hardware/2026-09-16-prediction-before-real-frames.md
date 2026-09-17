# What I think real people will do, written before we have a single real frame

2026-09-16, early morning. The drone arrives around 1 pm. This is a prediction
recorded before the data exists so that it can be wrong in public. The
people-plural suite's prediction failed on its high half and that failure was the
most useful thing in the write-up, so the same discipline applies here.

## The question this settles

Every person-tracking number this project has published, 0.97 to 0.99, came from
one photograph that sits at the 99th percentile of how easily this model detects
a person. Flying twelve screened people instead gave a 29% latch rate on the
standing scene, with seven of the twelve never acquired at all.

Both of those are the *simulator's* people: rendered cutouts pasted on opaque
cards. `docs/eval_results/2026-09-15-sim-person-fidelity` established that
rendered cutouts are systematically harder than the photographs they came from.
So the two results bracket the truth without locating it. **A real camera looking
at a real person is the measurement that locates it, and that is tomorrow.**

## What gets measured

`docs/real_frame_capture_protocol.md` puts the camera on a tripod at 0.8 m, level,
and the subject on floor marks at 1.5, 2.5 and 3.5 m. The 3.5 m mark is the one
that matters: the standing scene the twelve were flown on parks the drone at
3.64 m, so 3.5 m is the closest real analogue we will have.

`tools/real_frames/score_real_frames.py` already replays the shipped
0.75 / 0.45 / 3 confirmation rule over each clip and reports `track%`, the
fraction of frames the follower would be tracking. That is the same quantity as
the simulator's M1, computed by different code on different pixels. No new
tooling is needed.

## The reference points, from the simulator

Static scene, chip network, himax camera, 3.64 m, eight flights each:

| | tracking fraction |
|---|---|
| the published cutout (99th percentile) | 0.991 |
| 280779, the one screened subject that works | 0.986 |
| 556158 | 0.879 |
| 61747 | 0.722 |
| 266409, 401446 | 0.098, 0.106 |
| seven of twelve, including 161875 and 374369 | 0.000 |

## The prediction

**Primary, falsifiable.** At the 3.5 m mark, in good light, with the whole body
in frame, the median real person will give `track%` **above 0.80**, and no real
person will give exactly 0.000.

**Secondary.** Real people will sit closer to the published cutout than to the
median screened subject. Concretely, I expect at least 3 of every 4 real subjects
above 0.50 at 3.5 m.

**Why.** The only reason to expect otherwise is if the rendered-cutout penalty is
small, and the fidelity study says it is not small. Every failure mode the twelve
suffer from is a property of a flat opaque card: a wall-coloured rectangle around
the subject, a single upsampled crop of a photograph, no parallax, no real
texture. A real person in a real room has none of those.

**What would falsify it.** Any of: the median real person below 0.80; any real
person at exactly 0.000 in good light with the whole body in frame; fewer than 3
in 4 above 0.50.

## What each outcome means, decided in advance

- **Median above 0.80.** The pessimistic simulator result does not transfer. The
  drone follows ordinary people, and the 29% figure is an artefact of how we build
  scenes. The action is to fix the scene builder, not the network, and to stop
  quoting the twelve-subject number as a statement about reality.
- **Median between 0.30 and 0.80.** Real people sit between the two brackets. The
  action is to re-derive the acceptance gates on the real distribution and to
  treat the simulator as a lower bound only.
- **Median below 0.30, or any clean 0.000.** The pessimistic result transfers and
  the drone genuinely will not follow a typical person at 3.5 m. That makes the
  network the blocking problem, not the scene builder and not the control law,
  and it is the single most important thing this project could learn.

## Three things that would invalidate the comparison

1. **Light.** The twelve were flown under one simulated lighting condition. Shoot
   the priority-1 set under the room's normal light and note it. A dim room
   confounds the comparison with the thing being measured.
2. **Bearing.** The standing scene puts the person at -15.9 degrees; the capture
   protocol uses 0 and plus or minus 10 and 25. Compare like with like, or at
   minimum record the bearing with every clip, which the protocol already does.
3. **Whole body in frame.** At 1.5 m a 1.7 m person is close to the truncation
   limit of 1.285 m and the geometry starts to bite. The 3.5 m mark is clean;
   do not read the 1.5 m mark as the same measurement.

## A note on who is in the frame

Whoever is available tomorrow is not a random sample of humanity, and with a
small number of subjects this measures those people rather than people in
general. Record how many subjects and what they were wearing. A single subject in
a high-contrast jacket is not an answer to this question, and neither is four
people who all look similar.
