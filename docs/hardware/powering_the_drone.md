# Powering, charging and connecting the drone

Written 2026-09-17 after the first hands-on session, which cost an afternoon
almost entirely to things nobody had written down. Every runbook in this
directory assumed MinHyuk would be at the bench handling hardware, so none of
them said how to turn the thing on.

## What the hardware is

Confirmed from photographs on 2026-09-17: a Crazyflie 2.x with a **Bitcraze
AI-deck 1.1** mounted on top, marked `FRONT UP`, camera module fitted. Battery is
a Bitcraze **BCB350 1S 300C**, 350 mAh, with a protection circuit. Plus a
**Crazyradio 2.0** USB-A dongle.

AI-deck 1.1 is Rev D or newer, so it carries the GAP8 bootloader and **supports
over-the-air flashing**. That was an open question in `flash_runbook.md` §8 and it
is now closed.

## Powering it on

**There is no power button to find.** The Crazyflie powers up the moment the
battery is connected.

The battery connects through a pair of small white two-pin plugs: one on the
battery's own red and black leads, one on leads coming off the mainboard. They sit
loose when the drone is stored. Push them straight together until they seat.

You can tell a plug is unmated because its two metal contacts are visible in open
slots. Mated, you see no metal.

They are keyed, so if they resist, turn one over rather than forcing it.

LEDs come on immediately. The AI-deck takes another 20 to 30 seconds to boot and
bring up its WiFi.

**The propellers are not the motors.** The motors are the brass cylinders with
wires going to the board and they stay put. The propellers are the grey plastic
blades pushed onto the shafts, they have no wires, and they pull straight up off.
Pinch the plastic hub, not the blades.

## The camera network

The AI-deck raises its own WiFi access point named **`WiFi streaming example`**,
which is the default SSID of Bitcraze's `wifi-img-streamer`. It is open, no
password.

**Its appearance means the deck already has the streamer flashed** and nothing
needs flashing to capture frames. On 2026-09-17 it appeared, so this deck is
ready.

Joining it takes the laptop off the internet, because the deck is an access point
with nothing behind it. The deck is then at `192.168.4.1:5000`, which is what
`cpx_grab.py` defaults to.

macOS will quietly rejoin a known campus network when the deck's signal wavers.
Turn off auto-join for `eduroam` and `utexas-iot` for the session.

## Battery, and the thing that ended the first session

**Roughly five to seven minutes of use with the AI-deck streaming.** 350 mAh does
not go far when the deck is running a camera and a WiFi access point.

A rapid beeping and most of the LEDs going out is the low-voltage alarm. **The
AI-deck browns out before the mainboard does**, so the symptom you notice first is
the WiFi disappearing while a light is still on. That is a flat battery, not a
fault.

Disconnect the battery when you stop. A LiPo left sitting flat degrades.

**Charging: leave the battery connected and plug a micro-USB cable into the
Crazyflie mainboard.** The board charges the pack. There is no separate charger.
Roughly 40 minutes from flat. So the battery is connected for charging and for
flying, and disconnected only for storage.

## Cables you actually need

| what | why | had it on 2026-09-17 |
|---|---|---|
| **micro-USB data cable** | charging the battery, bench power, safe flashing | **no, and it blocked everything** |
| USB-A port or adapter for the Crazyradio | the radio link, and the only way to flash | unresolved, see below |

The micro-USB cable is the single blocking item. Without it you cannot charge,
which caps every session at five minutes, and you cannot power the drone from the
bench, which is what makes flashing safe. Charge-only cables are common; it must
carry data for the bench and flashing uses.

**The Crazyradio is USB-A** and a recent MacBook Pro has USB-C only. On
2026-09-17 a scan reported `Cannot find a Crazyradio Dongle`, and it was never
established whether the dongle was plugged in at all or whether an adapter was
missing. Check this before the next session: a USB-C hub or a USB-A to USB-C
adapter may be needed.

## What needs the radio, and what does not

Capturing camera frames needs **only WiFi**. No radio, no dongle. That is the
valuable half of the work and it is unblocked as soon as the battery is charged.

The radio is needed for flashing the GAP8, for telemetry, and for flight. None of
that is on the critical path for measuring how well the network sees real people.
