# The standing scene shows the network one picture, and I read eight flights into it

2026-09-16. No new flights. This re-reads the 208 flights of
`2026-09-15-people-plural` and the 156 of `2026-09-15-deadlock` after trying to
explain one subject, and ends up qualifying the headline of both.

## The question that started it

COCO 161875 sits at detectability index 87.0, near the top of a screened pool of
twelve, and behaves impossibly. Standing scene at 3.64 m: never acquired in eight
flights. Moved to 2.8, 2.2 and 1.6 m: never acquired, four flights each. Moving
scene: acquired on all eight. Not a range problem, and I had left it unexplained.

## 1. The standing scene is one photograph, repeated

On every frame of every standing flight the drone sits at `(0, 0)` with yaw `0`.
It never moves, because it never latches, and it never latches, so it never
moves. That is the frozen-geometry deadlock, already recorded. What I had not
drawn out is the consequence for the experiment:

**A standing cell renders exactly one pose. The only thing that varies between
frames, and between the eight repeats, is sensor noise.**

So "eight flights" of a standing cell is not eight independent trials of whether
the drone follows this person. It is one image, drawn eight times through a noise
model. The confidence intervals in the people-plural README treat the eight as
independent and they are closer to one.

## 2. The failing subjects never touch the bar, not once

| subject | n frames | mean conf | sd | **max** | frames >= 0.75 |
|---|---|---|---|---|---|
| 161875 (index 87.0) | 1683 | 0.613 | 0.044 | **0.737** | **0** |
| 374369 (index 90.3) | 1662 | 0.625 | 0.048 | **0.735** | **0** |
| 280779 (index 92.7) | 1688 | 0.821 | 0.095 | 0.987 | 1357 |

161875 and 374369 do not clear 0.75 on a single frame out of more than sixteen
hundred. Their whole distribution tops out about 0.013 below the bar.

This corrects something I would have said and an investigating agent did say:
that the three-consecutive-frame confirmation is what defeats them. It is not.
At this pose the confirmation rule never gets a chance, because no single frame
qualifies. Lower the bar to 0.70 and 161875 gets one run of 4 in eight flights;
at 0.72 the longest run is 2; at 0.75 there is nothing to confirm.

## 3. The covariate I used was measured at a different pose than I flew

This is the part that implicates the earlier analysis.

`conf_flown_range`, the covariate the people-plural README added on a reviewer's
advice and called "on the same scale as the bars that decide the outcome", comes
from the fidelity study's ladder at **dy = 0**, the subject straight ahead. The
standing scene parks the person at **dy = -1.0 m**, which is -15.9 degrees off
axis. Those are not the same pose, and the difference is large:

| subject | index | probe at dy=0 | flown, off axis | gap |
|---|---|---|---|---|
| 250127 | 52.1 | 0.653 | 0.318 | **+0.336** |
| 374369 | 90.3 | 0.894 | 0.625 | **+0.269** |
| 161875 | 87.0 | 0.879 | 0.613 | **+0.266** |
| 266409 | 92.1 | 0.838 | 0.680 | +0.158 |
| 61747 | 86.8 | 0.899 | 0.746 | +0.153 |
| 401446 | 88.8 | 0.833 | 0.692 | +0.141 |
| 280779 | 92.7 | 0.937 | 0.821 | +0.115 |
| control | 99.2 | 0.957 | 0.850 | +0.107 |
| 556158 | 93.9 | 0.889 | 0.828 | +0.062 |
| 356427 | 37.8 | 0.457 | 0.394 | +0.063 |
| 157365 | 34.6 | 0.448 | 0.404 | +0.043 |
| 124442 | 28.4 | 0.297 | 0.333 | -0.035 |
| 527750 | 34.3 | 0.317 | 0.416 | -0.099 |

Mean gap +0.122. **The three largest gaps belong to the three subjects I called
anomalous.** 161875 and 374369 are the two high-index subjects that never latch,
and 250127 is the one whose index-to-outcome relationship looked worst in the low
group.

So the people-plural finding that "the detectability index does not predict the
outcome" is partly a different statement: I predicted an off-axis flight with an
on-axis measurement, and the off-axis penalty is not uniform across subjects.

## 4. What this does and does not change

**Unchanged.** The flight measurements themselves. 208 flights, all valid, the
control at 0.991 and the screened pool at 0.292 on the standing scene. Those are
what the drone did.

**Changed.** Three things.

1. The standing result is one camera pose, not a survey of poses. Calling it
   "how well the drone follows people" overstates what one frozen pose can say.
2. The anomaly is largely explained. High-index subjects failed because the pose
   they were flown at costs them 0.27 of confidence relative to the probe that
   ranked them, which is enough to put a 0.88 subject under a 0.75 bar.
3. The eight repeats on a standing cell are near-replicates, so intervals
   computed as though they were independent are too narrow.

**Not a 161875 quirk.** 374369 is also 0 of 8 standing and 8 of 8 moving, and
266409, 401446, 356427 and 250127 all jump the same way. Whatever this is, it is
pool-wide.

## 5. What was ruled out, and how

The obvious hypothesis was left/right asymmetry, since the standing scene is at
-15.9 degrees and the moving scene sweeps positive. It is dead:

- The two scenes use a byte-identical panel texture, sha256 `36b49df8...`, and
  their scene files differ in two lines: the body position and the sway joint.
- The cutout is symmetric: mask centroid at 0.507 of panel width, left/right mask
  area ratio 0.903, mean brightness 40.1 left against 41.6 right.
- The model localises it correctly on every failing frame. It reports x_bin 6, the
  correct bin for -15.9 degrees, on all 1683 standing frames and on all three
  deadlock rungs. It knows where the person is. It is short of confidence, not
  lost.
- Matched-position mirror test on the moving flights: negative side 0.605 against
  positive 0.598, difference +0.007 with a bootstrap interval spanning zero.
- Across the pool the side effect runs the other way for nine of ten subjects,
  and 161875 has the smallest magnitude of any subject except the control.

Range was also ruled out: the deadlock rungs hold bearing at exactly -15.945
degrees and vary only range, giving 0.604, 0.506, 0.660 and 0.613 at 1.6, 2.2,
2.8 and 3.64 m. No rung reaches the bar.

## 6. What is still not determined

Whether -15.9 degrees is specifically bad for this subject, or off-axis placement
is bad for everyone. With the drone never yawing, only two poses have ever been
rendered for it, and they differ in sign, magnitude and range at once. The
protocol-geometry grid running tonight renders all thirteen subjects at bearings
0, plus and minus 10, and plus and minus 25, at five distances, which answers
exactly this. That table is the right place to settle it, not this directory.
