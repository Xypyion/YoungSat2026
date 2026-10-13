# Course ground station v1.10: what it actually sends

The course ground station (`MUT_Education_Satellite_Ground_Station_v1.10.exe`) is a PyInstaller build of a Python 3.13 / PySide6 / bleak app. We extracted and disassembled it ([TECHNIQUES.md §2](TECHNIQUES.md#2-reverse-engineering-the-course-ground-station)) to check that it works with the firmware. The program itself isn't included in this repository.

## Operation tab
**PREPARE** sends:
1. the active estimation profile:
   ```
   ADCS_MODE,MANUAL
   ADCS_REFERENCE,<ref>
   ESTIMATOR_FILTER_ENABLE,ON|OFF
   ESTIMATOR_FILTER_TYPE,…
   ESTIMATOR_MA_WINDOW / ESTIMATOR_FILTER
   ESTIMATOR_FUSION,…
   ESTIMATOR_GYRO_WEIGHT,…
   ```
2. `ADCS_MODE,MANUAL` → `ADCS_REFERENCE,…` → `ADCS_STRATEGY,…`, plus the Momentum profile if Momentum is selected
3. `ADCS_TUNE,<Kp .3f>,<Kd .3f>,<bias>`
4. `SET_TARGET,<first row .1f>`
5. `ADCS_PREPARE`

**RUN** in AUTO repeats MANUAL → reference → strategy → tune → `SET_TARGET` → `ADCS_MODE,AUTO`.
**STOP** sends `ADCS_MODE,MANUAL` and `RW_STOP`.

## Findings
| # | Finding | Effect |
|---|---|---|
| 1 | Target and mission-table spinboxes are limited to −90…+90° | In MAG mode the firmware only accepted 0…359.9, so negative targets were rejected. **Our firmware wraps −30 → 330.** |
| 2 | Targets are formatted with `.1f` | 359.95 becomes `360.0`, which the original firmware rejects (ours wraps it to 0) |
| 3 | Competition tab sends `PREPARE`, `START_MISSION`, `MISSION_NAME`, `MISSION_TRANSFER`, `MISSION_TIME_LIMIT`, `MISSION_CLEAR_TARGETS` | None of these exist in firmware v3.0.7 (it uses `MISSION_PREPARE`, `MISSION_START`, `MISSION_MAX_MIN`, `MISSION_CLEAR`) |
| 4 | A saved estimation profile without a fusion value sends `ESTIMATOR_FUSION,OFF` | Gyro fusion silently switched off, giving more lag |
| 5 | The Operation tab is a plain AUTO hold | Tolerance and hold time don't do anything there |

These findings are part of why we wrote **our own ground station** (see `../ground_station/`), which reads back every setting and saves debug reports.
