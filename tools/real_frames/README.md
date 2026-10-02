# tools/real_frames: capturing and scoring real AI-deck frames

Everything here runs offline. Joining the deck's WiFi cuts the laptop's internet, so
the capture scripts run unattended, speak their cues (`say`), and finish with a
summary and a folder name. Frames go to `~/drone_frames/<date>/...` and are **never
committed** (DECISIONS.md 2026-09-22). Mock rehearsals go to `~/drone_frames/_rehearsal/`.

| script | what it answers |
|---|---|
| `camera_check.sh` | stream works, left/right not mirrored |
| `empty_check.sh` | false alarms on an empty room |
| `exposure_check.sh` | which brightness this power-up came up at |
| `grid_capture.sh` | detection over a 3 x 3 grid of positions (dorm) |
| `fov_capture.sh` + `fov_fit.py` | **the camera's field of view and aim, solo** |
| `door_control.sh` | **the dark-door question, solo: background vs position** |
| `score_real_frames.py` | scores any labelled folder on the chip (default) or float network |
| `mock_streamer.py` | a fake AI-deck, for rehearsals |

## Solo FOV and door control (Oct 2, 2026)

Both scripts use the same setup as `grid_capture.sh`: the drone on the chair at the
window end, lens about 0.8 m up, facing the door, and the laptop **behind** the drone.
Both use the same brightness gate (30-60, `GRID_ACCEPT_ANY=1` overrides). Each must run
on **one battery and one power-up**, because exposure is fixed at power-up and both
analyses compare clips with each other. Put the battery in only once the props are
ready.

Until the PR is merged, the scripts exist only in the worktree, so set
`R=~/Downloads/drone/wt_solo_capture`. After the merge, use
`R=~/Downloads/drone/pytorch_ssd`. Each script uses the tools of the checkout it lives in.

### 1. Field of view: `fov_capture.sh` (about 4 min)

Tape **one line** across the aisle **1.00 m** from the point under the lens. That is
3 ft 3 3/8 in, or 3 tiles + 3 3/8 in. Put marks on it measured from the centre line
(the middle of column 3): 0, 0.25 m (9 7/8 in), 0.50 m (1 ft 7 5/8 in) and
0.70 m (2 ft 3 1/2 in) on **each** side. Write `+` on the marks on the **drone's
left**, as seen from behind the drone. This is the repo's lateral convention
(room/body +y, `tools/lighthouse/README.md`). Bearings use the opposite sign:
`+0.50 m` is bearing -26.6 deg.

For the object, use a **dark, opaque, matte bottle**, such as a black metal water
bottle or thermos. Don't use a book. A cylinder looks the same from every direction,
so its centre stays on the mark however it is turned. A book's face sits in front
of the mark and turns as you place it, and the book is twice as wide.

At 1 m the floor is just below the bottom of the picture, so only the top of a bottle
standing on the floor shows. The script checks every mark as soon as it is recorded
and says "got it" or "can't see it". If it can't see the bottle at the first mark,
stand it on something **narrow and round**, such as an upturned round bin or a tall
can. Don't use a box. Then press Enter to retake. Centre the bottle on each mark to
about 5 mm: 1 cm of error per mark costs about 1 % in the result.

```zsh
GRID_DRONE=09 zsh $R/tools/real_frames/fov_capture.sh
```

The script records an empty room (bottle behind the drone), then each mark. At each
mark the laptop says which mark. You place the bottle, come back behind the drone and
press Enter. It says "step out of frame", records 3 s, and checks the clip. At the end
it records another empty room, runs the fit and says the measured crop FOV.

The summary is in `fov_fit.txt`, and the numbers are in `fov_fit.json`. It reports:

* the focal length (px/rad);
* the HFOV of the 162-px stream, of its 122-px centre square, and of the flight app's
  244/324 crop (this one **assumes** the stream is the sensor frame 2x binned);
* the aim: where the tape line lands, and the x-bin a person on it would get;
* the residuals;
* the comparison with the 70 deg assumption, and the `--crop-hfov` value to use.

Knobs: `FOV_DIST`, `FOV_OFFSETS`, `FOV_LENS_H`, `FOV_OBJECT`, `FOV_OBJECT_H`,
`FOV_OBJECT_W`, `FOV_STAND_H`, `FOV_SECONDS`, `FOV_PRE`, `FOV_RETAKES`, and
`FOV_WAIT=20` (hands-free: each mark starts by itself after 20 s).

There is no resume: a new battery means a new exposure, so re-run the whole thing.
To re-fit a folder later:

```zsh
~/Downloads/drone/trainenv/bin/python $R/tools/real_frames/fov_fit.py <folder>
```

`fov_fit.py` exit codes:

| code | meaning |
|---|---|
| 0 | the fit is done |
| 3 | fewer than 4 usable marks (with a plain-English reason) |
| 5 | poor fit: the marks disagree, so don't use the numbers |

### 2. Dark-door control: `door_control.sh` (about 4-5 min)

You stand on the **CENTRE X at 7 tiles (2.13 m)**, the grid's existing tape, facing
the drone. The script records these clips, in this order:

1. an empty room with the door bare (10 s);
2. the door bare and a dark top (6 s);
3. the door bare and a light top;
4. the light sheet over the door and a light top;
5. the sheet and a dark top;
6. an empty room with the sheet still up.

That order needs one sheet change and two top changes. Before you power up:

* hang the sheet so that one pull covers the whole door;
* wear the dark top, and have a light top that pulls on over it within reach.

```zsh
GRID_DRONE=09 zsh $R/tools/real_frames/door_control.sh
```

It scores the clips on the chip network and prints a 2 x 2 table. Each cell gives the
median confidence, the frames at or above 0.75, the follower locks and the x-bin.
Under the table come the two empty clips' peak confidences, the differences between
cells, and the per-clip brightness. Reading the table: down a column is the
background's effect, and along a row is the top's effect.

If the battery dies, the script prints a resume command:
`DOOR_DIR=<folder> DOOR_START=<n> zsh $R/tools/real_frames/door_control.sh`. A
resume is a new power-up, so check the brightness lines before pooling the two halves.

### Rehearse without the drone (both done 2026-10-01)

AirPlay Receiver holds port 5000 on this Mac, so use another port. The mock needs the
main checkout, because the sim scenes it renders are gitignored and exist only there.

```zsh
# terminal 1
~/Downloads/drone/trainenv/bin/python ~/Downloads/drone/pytorch_ssd/tools/real_frames/mock_streamer.py --port 5057 --fps 2
# terminal 2  (CAMERA_CHECK_QUIET=1 silences the voice)
CAMERA_CHECK_GRAB_ARGS="--mock --port 5057" zsh $R/tools/real_frames/fov_capture.sh
CAMERA_CHECK_GRAB_ARGS="--mock --port 5057" zsh $R/tools/real_frames/door_control.sh
```

The mock serves a sim person, not a bottle, so `fov_capture.sh` ends with "NOT ENOUGH
MARKS" (exit 3). That is the expected result. The fit itself is proven on synthetic
sessions with known optics:

```zsh
~/Downloads/drone/trainenv/bin/python $R/tools/real_frames/fov_fit.py --selftest
~/Downloads/drone/trainenv/bin/python $R/tools/real_frames/test_fov_fit.py
```
