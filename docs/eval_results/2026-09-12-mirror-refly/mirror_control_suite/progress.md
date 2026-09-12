# acceptance2 progress (core)

| # | cell | scene | setup | repeat | attempt | result | note |
|---|---|---|---|---|---|---|---|
| 1 | A.static__ships | s15_static_offset | chip/himax_typical/chip | 1 | 1 | VALID | tracked 0.991, sim/wall 0.968, 6.432 Hz, end duration |
| 2 | A.static__ships | s15_static_offset | chip/himax_typical/chip | 2 | 1 | VALID | tracked 0.991, sim/wall 0.98, 6.445 Hz, end duration |
| 3 | A.static__ships | s15_static_offset | chip/himax_typical/chip | 3 | 1 | VALID | tracked 0.991, sim/wall 0.972, 6.441 Hz, end duration |
| 4 | B.moving__ships | s01_control_moving | chip/himax_typical/chip | 1 | 1 | VALID | tracked 0.992, sim/wall 0.971, 6.44 Hz, end duration |
| 5 | B.moving__ships | s01_control_moving | chip/himax_typical/chip | 2 | 1 | VALID | tracked 0.992, sim/wall 0.973, 6.438 Hz, end duration |
| 6 | B.moving__ships | s01_control_moving | chip/himax_typical/chip | 3 | 1 | NO RUN | exit 142 |
| 6 | B.moving__ships | s01_control_moving | chip/himax_typical/chip | 3 | 2 | INVALID | reasons: sim/wall 0.009 < 0.8 |
| 7 | A.static__proven | s15_static_offset | float/clean/full | 1 | 1 | NO RUN | exit 142 |
| 7 | A.static__proven | s15_static_offset | float/clean/full | 1 | 2 | VALID | tracked 0.996, sim/wall 0.981, 15.001 Hz, end duration |
| 8 | A.static__proven | s15_static_offset | float/clean/full | 2 | 1 | VALID | tracked 0.996, sim/wall 0.989, 14.938 Hz, end duration |
| 9 | A.static__proven | s15_static_offset | float/clean/full | 3 | 1 | VALID | tracked 0.996, sim/wall 0.988, 15.015 Hz, end duration |
| 10 | B.moving__proven | s01_control_moving | float/clean/full | 1 | 1 | VALID | tracked 0.996, sim/wall 0.984, 14.914 Hz, end duration |
| 11 | B.moving__proven | s01_control_moving | float/clean/full | 2 | 1 | INVALID | reasons: sim/wall None < 0.8; fewer than 2 control steps; never reached flight height (z_max=None); no follower control  |
| 11 | B.moving__proven | s01_control_moving | float/clean/full | 2 | 2 | VALID | tracked 0.995, sim/wall 0.994, 14.915 Hz, end duration |
| 12 | B.moving__proven | s01_control_moving | float/clean/full | 3 | 1 | VALID | tracked 0.996, sim/wall 0.997, 14.913 Hz, end duration |
| 13 | B.moving__delta_speed | s01_control_moving | float/clean/chip | 1 | 1 | VALID | tracked 0.992, sim/wall 0.997, 6.407 Hz, end duration |
| 14 | B.moving__delta_speed | s01_control_moving | float/clean/chip | 2 | 1 | VALID | tracked 0.992, sim/wall 0.996, 6.412 Hz, end duration |
| 15 | B.moving__delta_speed | s01_control_moving | float/clean/chip | 3 | 1 | VALID | tracked 0.992, sim/wall 0.993, 6.389 Hz, end duration |
| 16 | B.moving__delta_camera | s01_control_moving | float/himax_typical/full | 1 | 1 | VALID | tracked 0.996, sim/wall 0.996, 12.62 Hz, end duration |
| 17 | B.moving__delta_camera | s01_control_moving | float/himax_typical/full | 2 | 1 | VALID | tracked 0.996, sim/wall 0.998, 12.629 Hz, end duration |
| 18 | B.moving__delta_camera | s01_control_moving | float/himax_typical/full | 3 | 1 | VALID | tracked 0.996, sim/wall 0.997, 14.525 Hz, end duration |
| 19 | B.moving__delta_backend | s01_control_moving | chip/clean/full | 1 | 1 | VALID | tracked 0.996, sim/wall 0.988, 14.706 Hz, end duration |
| 20 | B.moving__delta_backend | s01_control_moving | chip/clean/full | 2 | 1 | VALID | tracked 0.996, sim/wall 0.997, 14.739 Hz, end duration |
| 21 | B.moving__delta_backend | s01_control_moving | chip/clean/full | 3 | 1 | VALID | tracked 0.996, sim/wall 0.995, 14.675 Hz, end duration |
