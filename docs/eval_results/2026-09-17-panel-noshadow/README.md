# This rig cannot separate bearing from the card's own shadow

2026-09-17, 01:37. **Aborted after one flight.** No results. The directory exists
because the attempt rules out an approach, and because the reason is a real
property of the simulator that anyone doing scene comparisons here needs to know.

## The question

`2026-09-16-onaxis` measured that moving a subject from 15.9 degrees off axis to
straight ahead takes the drone from following five of twelve people to eight.
That comparison is confounded: the subject panel is an opaque rectangle and the
scene's second light has no sideways component, so the card casts a box shadow
onto the wall 3.4 m behind it, displaced toward the image centre in proportion to
the subject's lateral offset. Off axis the shadow is visible next to the person,
**-30.0 DN on 13 of 13 subjects**. On axis it hides behind the card, **+2.3 DN on
13 of 13**.

So the reported gain is an upper bound. Putting a lower bound on it needs a
version of the scene with no card shadow and nothing else changed.

## Two attempts, both dead

**Attempt 1, `castshadow="false"` on both lights.** 156 flights, recorded in
`2026-09-16-noshadow`. The shadow really was removed, but detection collapsed
everywhere including on axis, and including the control, which fell from 0.991 to
0.048. The cause is `camera_model.py`'s auto-exposure loop, `AE_TARGET_DN = 60.0`.
Every frame in every condition has a mean near 60 because the sensor forces it.
Lightening the room made the loop pull exposure and gain down, and the subject
came back with less contrast, its 5th percentile falling from 22 to 17 DN while
the mean did not move. Not a clean removal, a whole-scene change laundered through
auto-exposure.

**Attempt 2, `castshadow="false"` on the panel geom alone.** The narrow
manipulation, which would have left the room's luminance untouched so
auto-exposure had nothing to react to. It does not exist:

```
ValueError: XML Error: Schema violation: unrecognized attribute: 'castshadow'
Element 'geom', line 34
```

MuJoCo accepts `castshadow` on `<light>` only. There is no per-geom shadow
control. Killed after the first flight rather than burning 156 on a scene that
cannot compile.

## Why this is a dead end here, not just an unlucky night

Three things compose, and each is load-bearing:

1. **The panel must be opaque.** `build_scene.py`'s own manifest records this as a
   renderer limit, not a choice: MuJoCo 3.13 drops the alpha channel when loading
   a PNG, so a cutout cannot be a silhouette. An opaque rectangle casts a
   rectangular shadow.
2. **Shadow casting is per light, not per object.** So the card's shadow cannot be
   removed without removing every shadow in the room.
3. **Auto-exposure couples the room to the subject.** Removing every shadow moves
   scene luminance, and the sensor renormalises the subject along with it.

Any two of those would be workable. All three together mean the card's shadow
cannot be isolated in this simulator as built.

## What this changes

**The bearing effect stays an upper bound.** 0.292 to 0.594 latch, 0.000 to 0.963
median tracking, with no lower bound, and none obtainable from this rig. Anyone
quoting the on-axis result must quote it that way.

**Tomorrow is the clean measurement.** A real camera looking at a real person is
exactly the experiment this rig cannot run, because a real person standing to one
side does not bring a rectangular shadow with them. The capture protocol already
records bearing with every clip and shoots 0, plus and minus 10, and plus and
minus 25 degrees. Those clips answer directly what three simulator suites could
not.

That raises the value of the plus and minus 25 marks considerably. They were worth
capturing before; now they are the only clean data anyone will have on what
bearing costs.

## If someone wants it in simulation anyway

The honest options, in order of cost: extend `build_scene.py` to composite the
cutout as geometry rather than a textured box, so the shadow matches the person
rather than the card; or fix exposure and gain manually in `camera_model.py` so
whole-scene manipulations stop propagating; or move the far wall far enough back
that the shadow leaves the frame, accepting that background depth is then a second
variable. None were attempted, and none should be attempted a few hours before a
hardware session.
