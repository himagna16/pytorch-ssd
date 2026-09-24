# Grid capture, run 1: first real-person detection grid (partial), 2026-09-24 18:31

`tools/real_frames/grid_capture.sh`, run by Sai alone with spoken cues, in his dorm.
Drone 1 (...09) sat on a chair at the window end with the lens about 0.8 m up, facing the
door. One subject (Sai), room lights, chip arm (`model_id_dory.onnx` d90555c8,
eps 2.0098e-4, enter 5467 / lost -998 / confirm 3). The frames stay on Sai's laptop
(`~/drone_frames/2026-09-24/grid_capture_183109/`); only the numbers are here.

**Partial:** the empty clip and 5 of the 9 positions were captured. Clip 6 (2.13 m RIGHT)
received 0 frames after about 5 min of streaming. The connection opened but no frames
came, which matches the AI-deck browning out on a flat battery (it goes before the
mainboard). Clips 6-9, including the whole 1.52 m row, are still to do.

| position | frames | median conf | frames >= 0.75 | follower locked | x-bins seen (expected) |
|---|---|---|---|---|---|
| empty room | 26 | 0.54 (max 0.65) | 0 | **0 / 26** | 7 x26 (-) |
| 2.44 m LEFT (-14.0 deg) | 17 | **0.88** | most | **88%** | 1 x9, 2 x7, 7 x1 (2) |
| 2.44 m CENTRE (0) | 17 | 0.52 | few | **0%** | 7 x16, 4 x1 (4) |
| 2.44 m RIGHT (+14.0 deg) | 17 | **0.87** | most | **88%** | 4 x9, 6 x3, 7 x5 (6) |
| 2.13 m LEFT (-15.9 deg) | 17 | **0.77** | most | **71%** | 2 x13, 7 x3, 1 x1 (2) |
| 2.13 m CENTRE (0) | 17 | 0.66 | some | **0%** | 7 x17 (4) |

(Per-frame values: `scores.csv`; the scorer's own table: `scorer_output.txt`.)

## The finding: background contrast, not position

Off to the sides, Sai is seen strongly and the follower locks on 71-88% of frames. Dead
centre, he is never locked, and the model answers bin 7 (the room's right-side
background pull, which also shows in the empty clip). The frames show why:

- **Centre** puts Sai directly in front of the **dark door**. His dark trousers and hair
  merge into it, and only the white shirt stands out, so there is no person-shaped
  outline.
- **Left and right** put him in front of the **bright wardrobe panels**. His whole
  silhouette (head, torso, legs) contrasts with the background.

So the champion's detection of a real person depends strongly on **subject/background
contrast**. This fits the Sep 22 run 2 frames, where the dim room also gave weak
detections.

**Confound, stated plainly:** in this room, position and background change together
(centre = door). One subject, one outfit, one session, 17 frames per cell. **The clean
test** is to stand at CENTRE with a light sheet or towel hung over the door (same
position, only the background changes), and ideally to repeat LEFT/RIGHT in dark
clothing.

## Other notes

- **The mirror check** printed FAIL ("sides disagree"). That is entirely the two CENTRE
  cells reading bin 7. The off-centre cells are on the correct side: LEFT bins 1-2,
  RIGHT bins 4-7.
- **Empty room:** 0 false locks. Confidence peaked at 0.65, lower than Sep 22's 0.71.
- **The aim is good this time.** The door sits centred in the frame (the Sep 22 run 2
  aim was a few degrees right).

---

## Run 1b (resumed at 18:46, `GRID_START=6`): 8 of 9 positions, BUT A LIGHTING CHANGE

The resume worked: clips 6-8 were added to the same folder and everything was re-scored.
Clip 9 (1.52 m RIGHT) got 0 frames, the same flat-battery signature. The script now
reports this, scores what it has, and prints the resume command, as designed.

**The frames are not one condition.** Mean frame brightness per clip (0-255):

| time | clips | mean brightness |
|---|---|---|
| 18:31-18:34 | empty; 2.44 L/C/R; 2.13 L/C | **38-42 (dim)** |
| 18:47 | 2.13 R; 1.52 L/C | **93-95 (bright)** |

Something between the two runs, such as a light switched on or auto-exposure settling
differently on a fresh battery, raised the brightness about 2.3x. The two groups must
not be pooled.

| position | condition | median conf | locked | x-bin (expected) |
|---|---|---|---|---|
| empty room | dim | 0.56 | **0 / 26** | 7 (-) |
| 2.44 m LEFT | dim | 0.90 | 15 / 17 | 1 (2) |
| 2.44 m CENTRE | dim | 0.51 | **0 / 17** | 7 (4) |
| 2.44 m RIGHT | dim | 0.87 | 15 / 17 | 4 (6) |
| 2.13 m LEFT | dim | 0.81 | 12 / 17 | 2 (2) |
| 2.13 m CENTRE | dim | 0.66 | **0 / 17** | 7 (4) |
| 2.13 m RIGHT | bright | 0.54 | **0 / 17** | 6 (6) |
| 1.52 m LEFT | bright | 0.78 | 14 / 17 | 1 (1) |
| 1.52 m CENTRE | bright | **0.93** | **14 / 17** | 3 (4) |
| 1.52 m RIGHT | - | not captured (battery) | | |

**What survives:**
- **Within the dim run:** off-centre is strongly detected and locked; dead centre, in
  front of the dark door, is never locked. That comparison is within one condition.
- **In the bright run, centre IS detected** at 1.52 m (0.93, locked 14/17). With the door
  lit, Sai's dark trousers and hair contrast against it. This is consistent with the
  contrast explanation, but distance (1.52 vs 2.1-2.4 m) and lighting changed at the
  same time, so it does not prove it.
- **2.13 m RIGHT in the bright run is weak** (0.54, never locked) even though its x-bin is
  right. Simple contrast does not obviously explain this. Sai stands between the lit
  door and the dark loft and ladder region. Unexplained, n = 17.
- **The empty room gave 0 false locks** (peak 0.65, dim run).

**Next:** a complete grid in **one sitting at one lighting level** (room lights on, fresh
battery), then the same grid with a light sheet over the door. Record which lights are
on.
