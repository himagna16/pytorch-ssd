# Lighthouse configurations

`dorm_lighthouse_2026-09-24.yaml`: exported from cfclient 2026.8 after the clean geometry
wizard (attempt 3) in Sai's dorm (log: `docs/eval_results/2026-09-24-lighthouse-dorm-setup/`).
Both tape-check runs passed against it: bare floor 4/4, and book 4/4 after one re-placement.

| config index | channel | base station uid | position (x, y, z) m | where |
|---|---|---|---|---|
| 0 | 1 | 1479799290 (0x5833F1FA) | (-1.43, +0.75, 1.77) | window end, Oaj's corner |
| 1 | 2 | 4100578795 (0xF469DDEB) | (+1.45, -0.78, 1.76) | door end, Sai's side |

Frame: origin = the blue ORIGIN tape (z = 0 at the height of the book used for the floor
samples, ~2 cm above the tile); +x toward the door; +y toward the SIDE mark; z up.
Station spacing 3.26 m. `systemType: 2` (V2).

**Using it on another drone** (e.g. drone 2), with no wizard: cfclient -> connect ->
Lighthouse Positioning tab -> **Import configuration** -> this file. Then run
`tools/lighthouse/tape_check.py` on that drone to confirm.

**Only valid while the stands do not move.** The stand feet were taped on the floor on
2026-09-24. If a stand moves, redo the wizard and export a new dated file; do not
overwrite this one.
