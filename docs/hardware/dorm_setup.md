# Running the project from a dorm room

Written 2026-09-22, the day the micro-USB cable arrived. The Sep 20 plan
(`before_the_next_session.md`) assumed one drone, MinHyuk's lab and unknown
Lighthouse hardware. Now Sai has:

| item | status 2026-09-22 |
|---|---|
| Drone 1 (Crazyflie 2.x + AI-deck 1.1, streamer already flashed) | charging |
| Drone 2 | in hand, **decks fitted unknown** |
| micro-USB cable | **one**, in hand. This clears the Sep 17 blocker |
| Two Lighthouse base stations | in hand, **V1 or V2 unknown** |
| Lighthouse **decks** (the boards that go on the drone) | **unknown. The base stations do nothing without them** |
| Crazyradio 2.0 + USB-A to USB-C adapter | dongle yes, adapter unknown |
| Room | a small dorm room. Dimensions not yet measured |

The unknowns are what the first 20 minutes below are for.

---

## 0. What the cable already unlocks, with no radio at all

The micro-USB cable is also a full data link. With a drone plugged into the
laptop, `cflib` connects at `usb://0`. The Crazyradio is not involved. That covers:

- reading which decks are fitted, the firmware version and battery state
  (`tools/hardware/preflight.py`, on branch `sai/hardware-preflight`, read-only:
  it never arms, never writes a parameter);
- the whole Lighthouse setup: setting it up in cfclient, estimating the room
  geometry, and reading the drone's position live;
- charging.

The radio only becomes necessary for a drone that is **not** on the cable. In
this plan that is the Session B beacon on someone's head, and later, flight.

---

## 1. Tonight, about 20 minutes, cable only

1. Plug drone 1 into the laptop with the battery connected. Charging and the
   data link come through the same cable.
2. Run the preflight tool. It reports the decks, firmware and battery, and if a
   Lighthouse deck is present, whether the base stations are being seen.
3. Swap to drone 2 and repeat. This is how we find out what drone 2 carries.
4. Take the photos in section 6.

Stop there. Don't join the deck's WiFi or open cfclient's flight tab yet.

---

## 2. Charging with one cable

- Both drones use the same BCB350 battery (350 mAh), and the batteries swap
  between drones. So one drone can act as the charger for both packs, one after
  the other. It takes about 40 minutes from flat.
- A 350 mAh pack gives **five to seven minutes** with the AI-deck streaming.
  Budget a session as "charged packs × 6 min". Two packs gives roughly 12
  minutes of camera time, which is enough for Session A's core set if the marks
  are taped out before anything is powered.
- **A second micro-USB cable costs about $5 and halves the charging time.** It
  must be a data cable, not charge-only. Buy one.
- Dorm safety: charge only while you are in the room, on a hard surface,
  never overnight. Unplug the battery for storage, because a LiPo left flat
  degrades.

---

## 3. The room: what each session needs in space

### Session A, real-people capture (needs WiFi only)

This is still the project's top open question: where real people's detection
margins sit. It needs no Lighthouse and no flight.

The protocol puts the subject at **1.5, 2.5 and 3.5 m** from the camera, at
0°, ±10° and ±25°. The geometry it needs:

| distance | lateral offset at ±25° | clear line needed from the camera |
|---|---|---|
| 1.5 m | 0.70 m each side | ~2.0 m |
| 2.5 m | 1.17 m each side | ~3.0 m |
| 3.5 m | 1.63 m each side | **~4.0 m**, plus ~3.3 m of width at the far end |

A typical double room is around 3.5 × 4.5 m before furniture. **The 3.5 m row
probably does not fit inside it**, and the room's diagonal is usually
cluttered. Options, best first:

1. Run 1.5 and 2.5 m in the room and 3.5 m in a hallway or study lounge.
   A hallway is also a plainer background, and a plain background is what
   the protocol wants.
2. Run the whole session in a lounge. It is one location and one lighting
   condition, which is cleaner.
3. Drop the 3.5 m row. This is the weakest option: the far distances are
   where the sim says margins are thinnest.

Wherever it runs:

- **Cover every mirror**, including the wardrobe-door mirror. A 20% mirrored
  floor in the simulator made the network read person plus reflection as one
  object. That is the Sep 12 size-head saga. A real mirror in shot is the same
  failure. It also hurts Lighthouse (see below).
- Close the blinds. Direct sun changes the camera's exposure and blinds the
  Lighthouse receivers.
- The subject is **a second person**. Sai runs the laptop. Ask a roommate or
  friend. More than one subject is better, because the question is about
  *people*, not about one person.

### Lighthouse (Session B prep and Session B)

From Bitcraze's Lighthouse guide:

- Mount the base stations **at least 50 cm above the working area**, in
  **two opposite corners**, angled down toward the middle of the room.
- Bitcraze quotes a working volume of about **4 × 4 × 2 m**. The drone must be
  within **6 m** of at least one station. A dorm room is inside that, so size
  is not the problem. Line of sight is.
- **No mirrors or shiny surfaces** in the volume, and no direct sunlight.
- Each station needs its **own wall power**. USB is only needed during setup.
  So "opposite corners" really means "opposite corners that each have an
  outlet or reach an extension cord".
- The stations have spinning parts. Mount them solidly: on top of a wardrobe
  or shelf, on a cheap light stand, or on a 1/4"-20 camera clamp. Don't mount
  them with tape. A station that wobbles gives a position that wobbles.
- **V2 stations** each need a unique channel (1 to 4), set in cfclient's base
  station tool with one station at a time plugged in over USB. **V1 stations**
  use a mode button on the back instead. Which one we have decides the steps.
  That is why a photo is needed.
- Geometry estimation, in cfclient over the USB cable: place the drone at the
  chosen origin, then 1 m along +x, then several spots on the floor, then hold
  it still in the air. The LED goes green when it is done. **Tape the origin
  and the +x mark on the floor and leave them there**, so the frame can be
  re-established on any later day.

### Flight

**Nothing in this plan flies in the dorm.** Session A and Session B are both
capture sessions. For Session B, the follower drone can sit on a stand at a
taped pose while the beacon walks. Closed-loop following needs about 2 m of
standoff plus room to manoeuvre, a clear floor and a net or a lot of space.
That belongs in MinHyuk's lab, after Session A says whether the drone sees real
people at all. (In simulation it latched onto a median- or lower-detectability person in only
1 of 12 flights. Flying before that question is answered would mostly test
the frame, not the model.)

A short Lighthouse hover in a cleared corner could come later, to prove the
positioning. It is optional and does not come first.

---

## 4. A hardware conflict to check, not assume

Can one drone carry both the AI-deck and a Lighthouse deck? The 2020 Bitcraze
forum answer was **no**: both used the Crazyflie's UART1. That answer is out of
date. In the current firmware:

- the AI-deck driver declares **UART2** plus IO_1 and IO_4
  (`crazyflie-firmware/src/deck/drivers/src/aideck.c`);
- the Lighthouse driver declares **UART1** and no GPIO (`lighthouse.c`).

Our follow packet goes GAP8 → ESP32 (SPI) → STM32 over CPX, which uses UART2.
It never touches UART1 (`crazyflie_ssd/src/transport_if.c`). So, at the level
of the deck drivers, there is **no conflict**. Bitcraze's stacking advice is:
Lighthouse deck on top, so the sensors see the sky; AI-deck between it and the
body, or underneath.

**The remaining doubt, unverified:** our GAP8 builds use `io=uart`
(`crazyflie_ssd/Makefile` line 4, and the stock `wifi-img-streamer` Makefile
line 1). On the AI-deck, the GAP8's UART is wired to the Crazyflie's UART1 pins,
which are the same lines the Lighthouse deck transmits on. If the GAP8 holds
its TX line driven, the Lighthouse data could be corrupted. How to test:
preflight on the stacked drone, then compare Lighthouse receive rate and
position noise with the GAP8 app running against the GAP8 held in reset. If it
bites, the fix is on our side: build the GAP8 app with `io=host` or route its
logs over CPX. No hardware change.

The Session B follower is the only drone that needs both decks. The beacon needs
only a Lighthouse deck. With a static follower, even the follower can skip the
Lighthouse deck: its pose is the taped mark.

---

## 5. Session order

| # | session | needs | where | answers |
|---|---|---|---|---|
| 0 | inventory (section 1) | cable | desk | what we actually have |
| A | real-people capture (`first_hour_with_the_drone.md`, `camera_measurement_protocol.md`) | charged packs, WiFi, a second person, tape measure | dorm + hallway/lounge | **where real detection margins sit**, the top open question |
| B0 | Lighthouse install + geometry + static taped-mark check (`before_the_next_session.md` §3.5) | Lighthouse deck(s), stations mounted, cable | dorm | is Lighthouse truth correct to the tape measure? |
| B | two-drone ground truth | 2 Lighthouse decks, radio + adapter, distinct radio addresses, head mount for the beacon | dorm or lounge | labels for frames the network misses |
| F | flight | MinHyuk's lab | lab | closed loop on hardware |

**Session A does not wait for anything in B.** That is the Sep 20 sequencing
rule, and it still holds.

---

## 6. Photos that decide the next steps

1. **The room.** One photo from each of two opposite corners. Also the rough
   dimensions (a tape measure, or count floor tiles or paces), where the
   outlets are, and any mirrors or windows.
2. **The Lighthouse base stations.** Front, back and any label, plus
   everything that came in the box (power adapters, mounts). This tells V1
   from V2.
3. **Drone 2 from above and the side**, plus any small boards in anti-static
   bags. A Lighthouse deck is a small square board with four small sensors
   on its top face.
4. **The Crazyradio** and whatever USB-C adapter or hub is around.
