# What can be done before the next hands-on session

Written 2026-09-20, three days after the first hands-on session ended on a flat
battery that we had no way to charge.

`powering_the_drone.md` covers how to turn the thing on and what stopped us on
Sep 17. This document is the other half: everything worth doing **while the drone
sits on the desk**, ordered so that the items which unblock a whole session come
first.

Nothing below needs the drone powered. Two items need parts that have not been
bought, and they are first because they are cheap and they gate everything else.

---

## 1. Buy two parts. That is the blocker.

| Part | Why it matters | Status |
|---|---|---|
| **micro-USB cable, data-capable, not charge-only** | Charges the battery through the Crazyflie's own mainboard. Also gives bench power, which is what makes flashing safe. There is no separate charger | **Not bought. This ended the Sep 17 session after about five minutes** |
| **USB-A to USB-C adapter, or a hub** | The Crazyradio 2.0 is USB-A and the laptop is USB-C only | **Unresolved.** A scan on Sep 17 reported `Cannot find a Crazyradio Dongle`, and it was never established whether the dongle was even plugged in or an adapter was missing |

Charge-only micro-USB cables are extremely common and will silently fail the
bench-power and flashing uses. Check the packaging says data.

**What each part unlocks:**

- The **micro-USB cable** unlocks session length. The battery is a 350 mAh pack
  giving five to seven minutes with the AI-deck streaming, and roughly forty
  minutes to recharge. Without charging, every visit is a five-minute visit.
- The **radio adapter** used to be optional, because capturing camera frames
  needs only the AI-deck's own WiFi. **Under the Lighthouse plan it is no longer
  optional**, because Lighthouse positions come back over the CRTP radio link,
  not over WiFi. See section 3.

---

## 2. Desk work already owed

### 2.1 Give `score_real_frames.py` a backend switch

The highest-priority code task, and it was deliberately deferred.

`tools/real_frames/score_real_frames.py` is hardwired to the **float** PyTorch
model (PIL BILINEAR 244->128, checkpoint `successor_qat_ep3_eval.pth`, lines
194-198 and 277-278). Every flight this project has run, and the GAP8 itself, use
the **chip** arm: `model_id_dory.onnx` plus the firmware's integer 2x2 preprocess.

On 13,003 rendered frames the two disagree by -0.124 in mean confidence and
-0.239 in the fraction of frames above the 0.75 enter bar, with 122 of 325 cells
moving by 0.25 or more. It is not a constant offset, so it cannot be corrected
after the fact.

The fix is `--backend {float,chip}`, defaulting to **chip**. It is a shared tool
under `tools/`, so per the repo's own rules it goes on a branch with a PR. It was
left undone on Sep 17 only because doing it unreviewed hours before a hardware
session is how sessions go wrong. There is no such excuse now.

Until it is done, the workaround in `first_hour_with_the_drone.md` stands: run
both scorers and believe the chip one.

### 2.2 Re-read the Sep 16 bearing work on the chip network

`docs/eval_results/2026-09-16-onaxis/` and `2026-09-16-protocol-geometry/` were
scored through the float arm. The directories are flagged rather than quietly
corrected, because some of their conclusions will not survive. This is a rescore,
not a re-flight: `docs/eval_results/2026-09-17-chip-arm-rescore/scripts/rescore_chip.py`
already does it for any folder of frames in about twenty seconds.

### 2.3 Accept that the bearing question has left the simulator

Two attempts to separate "where the person stands" from "the card's own shadow"
are dead:

- `2026-09-16-noshadow/`, 156 flights. Turning shadows off collapsed detection
  everywhere including the control (0.991 to 0.048), because `camera_model.py`
  holds every frame at `AE_TARGET_DN = 60.0`. Lightening the room made the
  auto-exposure loop pull gain down and the subject came back with less contrast.
- `2026-09-17-panel-noshadow/`, aborted after one flight.

So the 15.9-degrees-off-axis result stays an upper bound with no lower bound, and
**the simulator cannot give it one**. That is now a lab measurement. Worth saying
plainly to the team, because it changes what the lab session is for.

---

## 3. The Lighthouse ground-truth plan

### 3.1 What we are actually changing

The thesis setup uses a Bitcraze **Flow deck** for state estimation: a downward
optical-flow sensor plus a time-of-flight ranger, giving velocity over the floor
and height above it. (Worth checking the paper for the exact revision. The
current Bitcraze part is Flow deck v2; I could not confirm a v4 exists, so do not
quote a version number from memory.)

We are using the **Lighthouse positioning deck** with Vive base stations instead.

This is not a like-for-like swap, and the difference is the entire point:

- A Flow deck gives **relative** motion. It cannot tell you where anything is in
  the room, and it cannot tell you where the *subject* is at all.
- Lighthouse gives **absolute pose** in a room-fixed frame, for every drone
  carrying a deck.

That second property is what makes the two-drone scheme possible. A Flow deck
setup could not produce ground truth for this even in principle.

### 3.2 The scheme, stated precisely

A second Crazyflie, **props off, motors never armed**, carrying a Lighthouse deck,
rides on the subject's head. It flies nothing. It is a powered pose beacon that
logs its position.

The follower drone carries its own Lighthouse deck and logs its own pose.

The difference between the two poses, rotated into the follower's body frame, is
**where the subject truly was relative to the camera at that instant**. The
network's output on the matching frame is **where the network thought the subject
was**. Truth minus measurement is the training signal.

**The part of this that is better than it sounds:** ground truth exists for
frames where the network *misses entirely*. Every other method we have for
labelling real frames depends on something detecting the person. This one does
not. Misses and false negatives get correct labels, and those are exactly the
frames the open fine-tuning problem needs.

**The part that is worse than it sounds:** see 3.5.

### 3.3 What to build now, with no hardware

Four things, in this order. All of them are desk work and all of them can be
tested against the simulator, where the true poses are already known exactly.

**(a) The pose-to-label pipeline.** Take two poses, subtract, rotate into the
follower's body frame, project through the camera, and emit the x-bin and
size-bucket the network actually predicts. Then compare against what the network
said.

Build this against CrazySim first. The simulator already logs exact ground truth
for both the drone and the subject, so you can check the pipeline against a known
answer before a single real frame exists. Lighthouse logs then drop into the same
input slot.

This is also where the **yaw-sign chain finally gets verified**. That chain being
unverified is the stated reason `lab_session_runbook.md` scoped Lighthouse out
entirely. A sign error here does not produce an obvious failure; it produces a
confidently mirrored label set, which is the worst possible outcome, because it
would train the drone to steer away from people. The existing left/right mirror
check in the capture protocol is the right shape of test and should be extended
to cover this.

**(b) Decide the ground-truth convention, in writing, before collecting anything.**
A drone sitting on someone's head is not where the network's bounding box is
centred. The network was trained on COCO person boxes, which are centred roughly
on the torso. The offset between "top of head" and "box centre" is a real
quantity, it varies with the person's height, and if it is not defined
deliberately it becomes a systematic bias baked into every label.

Pick one and write it down: most likely head position minus a fixed vertical
offset derived from the subject's measured height. Record each subject's height.

**(c) Time synchronisation.** Frames arrive over WiFi from the AI-deck at
`192.168.4.1:5000`. Poses arrive over the CRTP radio link through the Crazyradio.
Two transports, two clocks, and no shared timebase.

An offset here turns into a bearing error that **grows with how fast the subject
is moving**, which means it will look fine on the static marks and silently
corrupt the moving data. Design for it now:

- Decide on a sync event visible in both streams. A sharp motion onset works: the
  subject stands still, then steps sideways on a cue. The step shows up as a
  discontinuity in the Lighthouse trace and as motion in the frames.
- Do it at the start *and end* of every capture run, so clock drift is measurable
  rather than assumed.
- Test the whole alignment routine against `tools/real_frames/mock_streamer.py`,
  which already exists from the dry run, with a synthetic pose log injected at a
  known offset. The test should recover the offset you injected.

**(d) Camera field of view.** You cannot convert a pose difference into a pixel
position without it. `tools/real_frames/measure_camera.py` exists for this, and
the capture protocol has a bottle-measurement fallback.

But ask MinHyuk first: question 13 on the lab-session list is whether anyone in
his lab has already measured this camera's FOV. If they have, that is bench time
saved and a number that does not depend on our measurement being right.

### 3.4 Questions for MinHyuk, by email, now

These decide whether the plan is even runnable, and none of them need anyone to
be in the same room:

1. Is there a **second Crazyflie** available, and can it be dedicated to this?
2. **How many Lighthouse decks?** The scheme needs two.
3. **Base stations: how many, and V1 or V2?** This changes what the deck can do
   and how the room gets calibrated.
4. **Is the base-station geometry already calibrated and saved**, or do we do that
   from scratch? If it is saved, get the file.
5. Is there a **second Crazyradio**? One dongle time-shares between two drones.
   Whether that is good enough at our logging rate is worth knowing before the
   session rather than during it.
6. What **addresses/channels** are the lab's drones on? Two Crazyflies on one
   radio need distinct addresses, and lab fleets are usually re-addressed away
   from the default `radio://0/80/2M/E7E7E7E7E7`.
7. How fragile is the Lighthouse rig, and who else uses the space?

### 3.5 What will bite, and the cheap way to find out early

**Run the static calibration case first, before any data collection.** Subject
stands on a taped floor mark, drone sits on a taped mark, both measured with a
tape measure. Capture thirty seconds. The pipeline's answer must match the tape
measure.

This is worth doing because it catches every one of the failures below at a cost
of ten minutes, and because **it needs no second drone at all** — the follower's
own Lighthouse pose plus a taped subject position is enough. If the second deck
or the second Crazyflie does not materialise, the static case still runs, and the
capture protocol's marks are already laid out for it.

Failures it catches:

- A mirrored or rotated frame convention (3.3a).
- The head-versus-torso offset being wrong (3.3b).
- A constant time offset, which shows up as a bearing error that is zero when
  nothing moves and non-zero when the subject walks. Only detectable if you have
  a static case to compare against.
- Lighthouse line-of-sight gaps. The deck's receivers face up, so a head mount is
  actually a good position, but the *follower* drone's deck also needs to see
  base stations, and a person standing between it and a base station will occlude
  it. Expect dropouts and decide now whether a dropped pose invalidates the
  frame or gets interpolated. Log the dropouts either way.

One more, which is not a bug but a limitation: this rig gives ground truth for
**where the subject is**, not for **whether the subject is detectable**. It tells
you the network missed; it does not tell you why. That is fine — it is what we
need — but it should not be oversold to the team as more than it is.

---

## 4. Do not let any of section 3 delay the capture session

The top open question in this project is still the one in the progress record:
**where do real people's detection margins sit?** Every tracking figure we have
published describes one unusually easy COCO photograph, and on a
median-detectability rendered subject the drone never starts following at all in
11 of 12 flights.

Answering that needs **WiFi only**. No radio, no Lighthouse, no base stations, no
second drone, no flight. It needs a charged battery, which needs a cable that
costs a few dollars.

Treat these as two separate sessions:

- **Session A, capture.** Unblocked by the micro-USB cable alone. Answers the
  project's top question.
- **Session B, the Lighthouse rig.** Needs hardware we do not yet know we have,
  and produces labelled training data.

Session B is the more exciting one and Session A is the one that is actually due.

---

## 5. Work that never needed hardware at all

Still open, still doable this week:

- **A better pet-safety recipe.** Settings are exhausted: both drone thresholds
  were swept in flight and rejected, and the Sep 14 fine-tune did not beat them
  once it was compared honestly. But the confuser model *is* genuinely safer at
  matched recall, by -0.014 to -0.026 at every recall level, so the effect is real
  and reachable. The target is a recipe that captures that curve-level gain
  without the confuser's recall collapse. **More seeds of the Sep 14 recipe are
  wasted effort.**
- **The standing rule that came out of that run**, and which applies to anything
  done here from now on: never compare two models at different thresholds.
  Compare at **matched recall**, and always run the threshold-dial control on the
  baseline before crediting training with anything.
- **The M10 uncertainty gate.** Proposal written, number deliberately unset,
  waiting on a scene suite that covers a realistic range of people.
- **The Bayer camera anomaly.** `scoreboard.py` now passes the Bayer camera while
  it tracks at 0.855, because M1 is report-only on `himax_typical`. That is an
  open team decision, not a bug to fix alone.

---

## 6. Admin, which keeps slipping

- **Prof. Mok's live demo slot is still unset.** He offered Tuesday or Thursday
  after 3:30 pm; I offered after 5 pm. This needs exactly one confirming email
  and has needed it since Sep 12.
- **Research credit registration.** He asked for periodic documentation that can
  be edited into a final report, which is what `docs/progress/sai_maruvada.md` is
  for. The registration process itself was asked about once and never answered.
  Ask again.
- **Tell the team the bearing question has moved to the lab** (section 2.3).
  It changes what Session A is for, and it is the kind of thing that should not
  first be said out loud in the room.
