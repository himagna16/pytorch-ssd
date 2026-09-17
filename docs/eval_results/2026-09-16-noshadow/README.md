# A failed experiment: you cannot remove the shadow without moving everything else

156 flights, 2026-09-16 into 2026-09-17, all VALID, no hangs. **The result is not
interpretable and should not be quoted.** This directory exists so the attempt is
on the record and nobody repeats it the same way.

## What I was trying to do

`2026-09-16-onaxis` reported that moving a subject from 15.9 degrees off axis to
straight ahead takes the drone from following five of twelve people to eight, and
the median tracking fraction from 0.000 to 0.963. An adversarial verifier then
showed that comparison is confounded: the subject panel is an opaque rectangle
and the scene's second light has no sideways component, so the card throws a box
shadow onto the wall 3.4 m behind it. The shadow keeps the subject's lateral
offset but lands at greater depth, so it appears displaced toward the image
centre in proportion to how far off centre the person stands. At 0 degrees it
hides behind the card. Off axis it does not.

That is real, and I confirmed it: a fixed wall strip reads **-30.0 DN off axis on
13 of 13 subjects and +2.3 DN on axis on 13 of 13**.

So the off-axis arm was artificially hard, and the reported gain is an upper
bound. This suite was meant to put a lower bound on it by re-flying both arms
with `castshadow="false"` on both lights, leaving geometry and light positions
untouched.

## What happened instead

| | latch rate | median M1 | acquirable |
|---|---|---|---|
| shadows on, off axis | 28/96 = 0.292 | 0.000 | 5 of 12 |
| shadows on, on axis | 57/96 = 0.594 | 0.963 | 8 of 12 |
| **shadows off, off axis** | **0/72 = 0.000** | 0.000 | 0 of 12 |
| **shadows off, on axis** | **13/72 = 0.181** | 0.000 | 3 of 12 |

Turning shadows off made everything worse, including the control, which goes from
0.991 to 0.048 on the off-axis scene. Subjects that work in every other condition,
like 280779 and 374369, drop to 0.000.

## Why it is not a finding

The shadow really was removed. The strip that read -33.1 DN reads +1.7 DN with
`castshadow="false"`, so the manipulation did what it said.

But detection also collapsed **on axis**, where there was no visible shadow to
remove. That is the tell.

`camera_model.py` runs an auto-exposure loop with `AE_TARGET_DN = 60.0`. Every
frame in every condition has a mean near 60 by construction: 60.2 and 60.0 with
shadows, 60.0 and 59.7 without. **The sensor renormalises whatever the renderer
gives it.** Removing shadows lightens the scene's darker surfaces, the AE loop
pulls exposure and gain down to hold the mean at 60, and the subject comes back
with less contrast: the 5th percentile of the frame goes from 22 to 17 DN while
the mean does not move.

So `castshadow="false"` is not a clean removal of one artefact. It is a change to
the whole scene's luminance distribution, which auto-exposure then propagates into
the subject. The comparison measures the shadow plus the exposure response, and
those cannot be separated from these flights.

## What this leaves standing, and what it does not

**Standing.** The shadow confound itself, which is measured directly in pixels and
does not depend on this suite. The off-axis arm of every earlier comparison carries
a hard-edged dark block next to the subject and the on-axis arm does not.

**Not standing.** Any statement about how much of the on-axis gain is really
bearing. The 0.292 to 0.594 gain remains an **upper bound with no lower bound**.
This suite was meant to supply the lower bound and it cannot.

**A general lesson for this rig, which is the useful part.** Auto-exposure means
scene-wide luminance is coupled to subject contrast. Any manipulation that changes
what else is in the frame will change how the subject renders, even when the
subject itself is untouched. That applies to the floor reflectance work, the
lighting variants, and anything else that alters the room. It should be stated in
any future scene comparison.

## What would actually work

Three options, none of them tried:

1. Hold the AE state fixed across arms, if the sensor model allows a manual
   exposure and gain, so the renderer change cannot propagate.
2. Compare at matched AE output rather than matched scene, by rendering both arms
   and selecting frames whose exposure and gain settled at the same values.
3. Remove the shadow at the source by making the panel cast no shadow while other
   geometry still does, which MuJoCo supports per-geom rather than per-light. That
   is the narrow manipulation I should have made, and it is the one to try next.

Option 3 is the right one and is a small change to `build_scene.py`, which is why
it is written down here rather than done tonight against a shared tool a few
hours before a hardware session.
