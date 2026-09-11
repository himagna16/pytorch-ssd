# Champion network in the drone firmware (local integration branch)

For the frontend team (Jade, Koa, Calvin). The AI-deck firmware lives in
David Liu's repo `github.com/DavidLiu2/crazyflie-ssd`, which we do not push
to. The integration is delivered here as a git bundle instead:
`champion-core8-integration.bundle` (15 commits on top of `4a03846`).

Load it into a clone of crazyflie-ssd:

```bash
git clone https://github.com/DavidLiu2/crazyflie-ssd && cd crazyflie-ssd
git fetch /path/to/champion-core8-integration.bundle champion-core8-integration:champion-core8-integration
git checkout champion-core8-integration
```

What the branch does (details and the bench/flash plan: `HANDOFF.md`, and
`docs/champion_integration.md` on the branch):

- replaces the old Aug 27 network with the validated QAT champion, built for
  8 cores with DORY's debug output off (about 23 ms per inference on the
  chip simulator instead of 154 ms);
- decodes the 14-value output with the team's tested C decoder;
- resizes camera frames with a 2x2 average, which matches training
  (nearest neighbor cost 0.050 F1 at the 0.7 threshold);
- sends the flight controller a 28-byte packet (version 6) with the target,
  the age of its frame, and a GAP8 send timestamp;
- resets tracking and sends "no target" whenever perception fails, stalls,
  or packets are delayed.

**Safety status.** Six rounds of fixes, each checked by an independent
reviewer with a timing simulator (`safety_sim/`, logs in
`safety_sim/logs/`). With the flight-controller rules in `HANDOFF.md` §3,
the drone lands about 3.0 s after its last good frame, never steers on a
frame older than 0.5 s, and re-confirms a target with fresh strong frames
after any stale hover, in every simulated failure. The GAP8 side guarantees
landing and fresh-frame steering on its own; covering delays inside the
ESP32 radio needs the flight controller to implement rules 0 and 4.

**Not done yet.** Nothing has run on a real drone. The flight-controller
(STM32) handler that applies the rules is still to be written. The official
flash script needs a helper from `bitcraze/aideck-gap8-examples` that is not
in the repo (`HANDOFF.md` §4 has the direct build command). Check which
camera the deck has before the first camera test (color sensors need one
more change; see `docs/firmware_contract.md`).
