# acceptance2 progress (core)

| # | cell | scene | setup | repeat | attempt | result | note |
|---|---|---|---|---|---|---|---|
| 1 | A.static__ships | s15_static_offset | chip/himax_typical/chip | 1 | 1 | VALID | tracked 0.991, sim/wall 0.995, 6.426 Hz, end duration |
| 2 | A.static__ships | s15_static_offset | chip/himax_typical/chip | 2 | 1 | VALID | tracked 0.991, sim/wall 0.994, 6.425 Hz, end duration |
| 3 | A.static__ships | s15_static_offset | chip/himax_typical/chip | 3 | 1 | VALID | tracked 0.227, sim/wall 0.954, 6.43 Hz, end duration |
| 4 | B.moving__ships | s01_control_moving | chip/himax_typical/chip | 1 | 1 | VALID | tracked 0.991, sim/wall 0.99, 6.432 Hz, end duration |
| 5 | B.moving__ships | s01_control_moving | chip/himax_typical/chip | 2 | 1 | VALID | tracked 0.914, sim/wall 0.985, 6.424 Hz, end duration |
| 6 | B.moving__ships | s01_control_moving | chip/himax_typical/chip | 3 | 1 | VALID | tracked 0.967, sim/wall 0.989, 6.423 Hz, end duration |
| 7 | A.static__proven | s15_static_offset | float/clean/full | 1 | 1 | VALID | tracked 0.996, sim/wall 0.989, 14.926 Hz, end duration |
| 8 | A.static__proven | s15_static_offset | float/clean/full | 2 | 1 | VALID | tracked 0.996, sim/wall 0.984, 14.75 Hz, end duration |
| 9 | A.static__proven | s15_static_offset | float/clean/full | 3 | 1 | VALID | tracked 0.371, sim/wall 0.905, 13.455 Hz, end duration |
| 10 | B.moving__proven | s01_control_moving | float/clean/full | 1 | 1 | VALID | tracked 0.937, sim/wall 0.928, 13.447 Hz, end duration |
| 11 | B.moving__proven | s01_control_moving | float/clean/full | 2 | 1 | VALID | tracked 0.668, sim/wall 0.976, 14.531 Hz, end duration |
| 12 | B.moving__proven | s01_control_moving | float/clean/full | 3 | 1 | VALID | tracked 0.956, sim/wall 0.917, 13.45 Hz, end duration |
| 13 | B.moving__delta_speed | s01_control_moving | float/clean/chip | 1 | 1 | VALID | tracked 0.936, sim/wall 0.997, 6.364 Hz, end duration |
| 14 | B.moving__delta_speed | s01_control_moving | float/clean/chip | 2 | 1 | VALID | tracked 0.98, sim/wall 0.992, 6.378 Hz, end duration |
| 15 | B.moving__delta_speed | s01_control_moving | float/clean/chip | 3 | 1 | INVALID | reasons: achieved 2.87 Hz < 0.9 x 6.5 Hz |
| 15 | B.moving__delta_speed | s01_control_moving | float/clean/chip | 3 | 2 | VALID | tracked 0.992, sim/wall 0.988, 6.438 Hz, end duration |
| 16 | B.moving__delta_camera | s01_control_moving | float/himax_typical/full | 1 | 1 | VALID | tracked 0.323, sim/wall 0.927, 2.602 Hz, end duration |
| 17 | B.moving__delta_camera | s01_control_moving | float/himax_typical/full | 2 | 1 | VALID | tracked 0.552, sim/wall 0.922, 9.396 Hz, end duration |
| 18 | B.moving__delta_camera | s01_control_moving | float/himax_typical/full | 3 | 1 | VALID | tracked 0.966, sim/wall 0.906, 13.486 Hz, end duration |
| 19 | B.moving__delta_backend | s01_control_moving | chip/clean/full | 1 | 1 | VALID | tracked 0.886, sim/wall 0.997, 14.985 Hz, end duration |
| 20 | B.moving__delta_backend | s01_control_moving | chip/clean/full | 2 | 1 | VALID | tracked 0.844, sim/wall 0.978, 14.917 Hz, end duration |
| 21 | B.moving__delta_backend | s01_control_moving | chip/clean/full | 3 | 1 | VALID | tracked 0.095, sim/wall 0.919, 13.234 Hz, end duration |
