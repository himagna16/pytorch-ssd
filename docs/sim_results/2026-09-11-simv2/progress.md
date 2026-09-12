# acceptance2 progress (core)

| # | cell | scene | setup | repeat | attempt | result | note |
|---|---|---|---|---|---|---|---|
| 1 | A.static__ships | s15_static_offset | chip/himax_typical/chip | 1 | 1 | VALID | tracked 0.991, sim/wall 0.993, 6.419 Hz, end duration |
| 2 | A.static__ships | s15_static_offset | chip/himax_typical/chip | 2 | 1 | VALID | tracked 0.991, sim/wall 0.989, 6.432 Hz, end duration |
| 3 | B.moving__ships | s01_control_moving | chip/himax_typical/chip | 1 | 1 | VALID | tracked 0.992, sim/wall 0.98, 6.427 Hz, end duration |
| 4 | B.moving__ships | s01_control_moving | chip/himax_typical/chip | 2 | 1 | VALID | tracked 0.992, sim/wall 0.982, 6.436 Hz, end duration |
| 5 | C.empty__ships | s02_control_empty | chip/himax_typical/chip | 1 | 1 | VALID | tracked 0.0, sim/wall 0.986, 6.425 Hz, end duration |
| 6 | C.empty__ships | s02_control_empty | chip/himax_typical/chip | 2 | 1 | VALID | tracked 0.0, sim/wall 0.98, 6.431 Hz, end duration |
| 7 | D.occlusion__ships | s07_occlusion_reappear | chip/himax_typical/chip | 1 | 1 | VALID | tracked 0.566, sim/wall 0.984, 6.44 Hz, end duration |
| 8 | D.occlusion__ships | s07_occlusion_reappear | chip/himax_typical/chip | 2 | 1 | VALID | tracked 0.629, sim/wall 0.967, 6.435 Hz, end duration |
| 9 | E.furniture__ships | s16_furniture_only | chip/himax_typical/chip | 1 | 1 | VALID | tracked 0.0, sim/wall 0.978, 6.43 Hz, end duration |
| 10 | E.furniture__ships | s16_furniture_only | chip/himax_typical/chip | 2 | 1 | VALID | tracked 0.0, sim/wall 0.977, 6.427 Hz, end duration |
| 11 | F.pets__ships | s03_pets_only | chip/himax_typical/chip | 1 | 1 | VALID | tracked 0.635, sim/wall 0.974, 6.435 Hz, end duration |
| 12 | F.pets__ships | s03_pets_only | chip/himax_typical/chip | 2 | 1 | VALID | tracked 0.599, sim/wall 0.968, 6.439 Hz, end duration |
| 13 | A.static__proven | s15_static_offset | float/clean/full | 1 | 1 | VALID | tracked 0.996, sim/wall 0.993, 15.01 Hz, end duration |
| 14 | A.static__proven | s15_static_offset | float/clean/full | 2 | 1 | VALID | tracked 0.996, sim/wall 0.987, 15.014 Hz, end duration |
| 15 | B.moving__proven | s01_control_moving | float/clean/full | 1 | 1 | VALID | tracked 0.997, sim/wall 0.993, 14.997 Hz, end duration |
| 16 | B.moving__proven | s01_control_moving | float/clean/full | 2 | 1 | VALID | tracked 0.996, sim/wall 0.977, 14.99 Hz, end duration |
| 17 | C.empty__proven | s02_control_empty | float/clean/full | 1 | 1 | VALID | tracked 0.0, sim/wall 0.989, 14.991 Hz, end duration |
| 18 | C.empty__proven | s02_control_empty | float/clean/full | 2 | 1 | VALID | tracked 0.0, sim/wall 0.981, 14.89 Hz, end duration |
| 19 | D.occlusion__proven | s07_occlusion_reappear | float/clean/full | 1 | 1 | VALID | tracked 0.764, sim/wall 0.979, 15.001 Hz, end duration |
| 20 | D.occlusion__proven | s07_occlusion_reappear | float/clean/full | 2 | 1 | VALID | tracked 0.783, sim/wall 0.989, 15.01 Hz, end duration |
| 21 | E.furniture__proven | s16_furniture_only | float/clean/full | 1 | 1 | VALID | tracked 0.0, sim/wall 0.975, 15.017 Hz, end duration |
| 22 | E.furniture__proven | s16_furniture_only | float/clean/full | 2 | 1 | VALID | tracked 0.0, sim/wall 0.99, 14.864 Hz, end duration |
| 23 | B.moving__delta_speed | s01_control_moving | float/clean/chip | 1 | 1 | VALID | tracked 0.992, sim/wall 0.989, 6.429 Hz, end duration |
| 24 | B.moving__delta_speed | s01_control_moving | float/clean/chip | 2 | 1 | VALID | tracked 0.992, sim/wall 0.977, 6.436 Hz, end duration |
| 25 | B.moving__delta_camera | s01_control_moving | float/himax_typical/full | 1 | 1 | VALID | tracked 0.997, sim/wall 0.992, 14.797 Hz, end duration |
| 26 | B.moving__delta_camera | s01_control_moving | float/himax_typical/full | 2 | 1 | VALID | tracked 0.996, sim/wall 0.988, 14.702 Hz, end duration |
| 27 | B.moving__delta_backend | s01_control_moving | chip/clean/full | 1 | 1 | NO RUN | exit 142 |
| 27 | B.moving__delta_backend | s01_control_moving | chip/clean/full | 1 | 2 | VALID | tracked 0.991, sim/wall 0.99, 14.56 Hz, end duration |
| 28 | B.moving__delta_backend | s01_control_moving | chip/clean/full | 2 | 1 | VALID | tracked 0.996, sim/wall 0.992, 14.587 Hz, end duration |

## Flights merged into this suite after the first scoring pass

The rows above are the original CORE sweep. This suite directory additionally
contains flights that were flown for the same cells but were not in that sweep's
scored set. They are merged here so every cell is scored on every valid flight of
it, rather than on whichever subset happened to be copied.

| run dir | origin | why |
|---|---|---|
| `A.static__proven__r4a1` | core_r3 tie-break suite, repeat 1 | flown, valid, previously discarded |
| `A.static__proven__r5a1` | core_r3 tie-break suite, repeat 2 | flown, valid, previously discarded |
| `B.moving__proven__r4a1` | core_r3 tie-break suite, repeat 1 | flown, valid, previously discarded |
| `B.moving__proven__r5a1` | core_r3 tie-break suite, repeat 2 | flown, valid, previously discarded |
| `A.static__ships__r3a1` | flown 12 Sep 00:22 after review | two flights cannot support a headline hold distance |
| `A.static__ships__r4a1` | flown 12 Sep 00:23 after review | as above |

`A.static__proven__r3a1` and `B.moving__proven__r3a1` were already present in the
original sweep and are byte-identical copies of the core_r3 suite's repeat-3
flights, which is why core_r3's repeats 1 and 2 are the only ones added here.

Sensor-seed caveat: run_acceptance2.sh derives the camera seed as 1000 + repeat,
so `A.static__ships` r3/r4 reuse the seeds of r1/r2 (1001, 1002). The four flights
are two seed pairs, not four independent camera-noise draws.
