# Youngsat / SunSeek — Handoff Notes

Context for continuing this project in another chat. Last updated 2026-10-08.

## What this is
A single-axis training satellite ("SunSeek") with a reaction wheel, controlled from a Windows ground station over Bluetooth, plus an ESP32-CAM camera payload.

- **Satellite board:** ESP32-S3 Dev Module (Arduino IDE, ESP32 core 3.1.1). Bluetooth name **`SUNSEEK-Team_Jenny`**.
- **Camera:** AI Thinker ESP32-CAM, joined to the satellite by a UART wire. It runs its own Wi-Fi network: **`iLoveJenny`**, password (set in `Config_Payload.h`), address **`192.168.4.1`**.
- **Ground Station:** `MUT_Education_Satellite_Ground_Station_v1.10` (a compiled PyInstaller exe, Python 3.13 + PySide6 + bleak; no source). It runs on a **separate laptop** connected to the camera's Wi-Fi.

## Folders (current = bold)
| Folder | What |
|---|---|
| **`SunSeek_Platform_Firmware_v3_2_TeamJenny_OURS/`** | **OUR NEWEST — WORKS ON HARDWARE (2026-10-08).** v3.1 + wheel-model controller (ADCS_CTRL_MODE,WHEEL), max cmd 45, **ADCS_CONTROL_SIGN -1 (this was the real wobble cause: with +1 it parked 180 deg from target and chattered)**. Live flip: ADCS_CONTROL_SIGN,<1/-1>. |
| `SunSeek_Platform_Firmware_v3_1_TeamJenny_OURS/` | **OUR VERSION (2026-10-08): v3.0.7 + anti-wobble controller + bug fixes. See its `README_OURS_TeamJenny.md`. Compiled OK, not yet tested on hardware.** |
| `SunSeek_Platform_Firmware_v3_0_7/` | Official v3.0.7 (unchanged, fallback) |
| `SunSeek_Platform_Firmware_v3_0/` | Previous version (has the same changes; leftover unfinished sun-sensor calibration code in `Config_Sensor.h` + router) |
| `SunSeek_Platform_Firmware_v2_1/` | Old version |
| **`SunSeek_ESP32CAM_Payload_Firmware_v3_0/`** | **Current camera firmware** |
| `MUT_Education_Satellite_Ground_Station_v1.10/` | Current ground station (exe) |
| `MUT_Education_Satellite_Ground_Station_v1.9/` | Old ground station |
| `SunSeek_GroundStation_Lite/` | Python ground station + PD auto-tuner written in an earlier chat (`run.bat`). Built for v2.1; only tested against its built-in simulator. Not in use. |

## Code layout (satellite firmware)
- `Config_*.h` — settings and calibration (safe to edit)
- `Module_*.h` — subsystems: IMU, sun sensor, reaction wheel, estimator, ADCS (PD controller), mission, payload UART
- `System_*.h` — Bluetooth TT&C (`System_TTC.h`), command router (`System_CommandRouter.h`), telemetry
- Protocol: one ASCII line per message, ending in `\n`. Replies are `ACK,…`, `ERR,…`, `EVT,…`, `TM,KEY,VALUE,…`, `PAYLOAD,…`. The same commands also work over USB Serial at 115200.

## Changes made to satellite firmware v3.0.7
1. **Gyro auto-zero at boot.** It averages the gyro for about 2 s in `setup()`. **Keep the satellite still while it boots.** The command `GYRO_CAL` (or `GYRO_OFFSET`) redoes it, MANUAL mode only. Code: `imuCalibrateGyro()` in `Module_IMU.h`.
2. **Magnetometer calibration commands connected** (the code existed but no command called it): `MAG_CAL_START` / `MAG_CAL_STOP`. The result applies immediately, no upload needed.
3. **New commands:** `MAG_SET_HEADING,<deg>` (make the current direction read `<deg>`) and `MAG_REVERSE` (flip the turning direction while keeping the same zero). The calibration values are runtime variables in `Module_IMU.h`, starting from `Config_Sensor.h`.
4. **Bluetooth disconnect fix (`System_TTC.h`).** Root cause: commands used to run inside the Bluetooth task while `loop()` sent telemetry at the same time, with no lock, which could corrupt memory or block Bluetooth. Now `onWrite()` only puts bytes into a FreeRTOS queue, and `communicationUpdate()` in `loop()` runs the commands. Fixed but **not yet confirmed on hardware.**
5. Team name kept as `Team_Jenny` (v3.0.7 shipped with `Team_DekMUT`).

## Current calibration (in `SunSeek_Platform_Firmware_v3_0_7/Config_Sensor.h`)
```
MAG_OFFSET_X -215.50   MAG_OFFSET_Y -1259.00   MAG_OFFSET_Z -619.50
MAG_SCALE_X  1.0461    MAG_SCALE_Y  0.9578     MAG_SCALE_Z  1.0
MAG_HEADING_SIGN        -1.0
MAG_HEADING_OFFSET_DEG  327.27   (calibrated 0° reference 247.27 + 90° − 10° added by user; set in v3_1_TeamJenny_OURS)
GYRO_BIAS_*  0.0  (not needed — gyro zeroes itself at boot)
IMU_BODY_RATE_AXIS Z, SIGN +1
```
Notes:
- Only the X and Y scale matter for heading. I set them as `avg(hx,hy)/hx` and `avg(hx,hy)/hy`. The firmware's own Z scale is unreliable, because Z barely changes when it's turned level, so I set Z to 1.0.
- To flip the direction while keeping 0° in place: SIGN → −SIGN and OFFSET → 360 − OFFSET.
- The heading changes with location (steel and wiring in the building). **Recalibrate in the room where it will be used.**
- ADCS gains are still the defaults: Kp 2.0, Kd 0.5, deadband 2°, max wheel 80, `ADCS_CONTROL_SIGN` 1.0. **Not tuned yet.**

## Calibration procedure (send in the Ground Station command box)
1. `ADCS_MODE,MANUAL`
2. `GYRO_CAL` (keep it still)
3. `MAG_CAL_START`, turn it 2 slow full circles while level, then `MAG_CAL_STOP`
4. Point it at the desired 0°, then `MAG_SET_HEADING,0`
5. If clockwise makes the heading go down: `MAG_REVERSE` once, then `MAG_SET_HEADING,0` again
6. Copy `TM,CAL_MAG_MINMAX`, `TM,CAL_MAG_OFFSET` and the **last** `TM,MAG_HEADING_OFFSET_DEG` into `Config_Sensor.h`

## Pointing (absolute targets — original firmware design)
```
ADCS_MODE,MANUAL
ADCS_REFERENCE,MAG          (SUN only allows −90…+90)
ADCS_STRATEGY,REACTION      (recommended over MOMENTUM)
ADCS_TUNE,<Kp>,<Kd>,<bias>
SET_TARGET,<0..359.9>       (360 is rejected; targets only change in MANUAL)
ADCS_MODE,AUTO
STOP                        (emergency)
```
Sensor checks: `SUN_RAW`, `MAG_RAW`, `GYRO_RAW`, `TM_STREAM,<SUN|MAG|GYRO|ADCS>,ON|OFF`, `SENSOR_STATUS`, `IMU_STATUS`.

## Changes made to camera firmware (`SunSeek_ESP32CAM_Payload_Firmware_v3_0/`)
1. **SD card:** it now tries to mount the card again on `STATUS` and `CAPTURE`. Capture errors give the reason: `ERR,CAPTURE_FAILED,STORAGE_NO_CARD_OR_NOT_FAT32 | STORAGE_MOUNT_FAILED | CAMERA_NOT_READY | WRITE_FAILED`. The card must be FAT32 and 32 GB or smaller.
2. **Stream no longer blocks other requests:** `/stream` runs in its own task (`httpd_req_async_handler_begin`), so `/image` and `/status` keep answering while it streams.
3. **Web server stack raised from 4096 to 12288**, and the image buffer moved to the heap. The old 4 KB stack crashed when serving `/image`.
4. **New photo viewer page at `http://192.168.4.1/`**: take a photo, live view, photo list, newer/older, download. Plus a new **`/capture`** endpoint. Note: the camera does not URL-decode, so the page sends `?name=/IMG_xxxx.JPG` with a literal `/`.
5. **Live stream is OFF by default** (`PAYLOAD_STREAM_DEFAULT_ON 0`). Turn it on with `PAYLOAD_STREAM_START`.

Camera web routes: `/`, `/status`, `/images`, `/image?name=/IMG_0001.JPG`, `/stream`, `/capture`.

## Open issues / next steps
- **Ground Station v1.10 can't preview or download photos.** Its log showed `ACK,CAPTURE` but never `PAYLOAD,EVENT,CAPTURE_STARTED` or `PAYLOAD,IMAGE_READY`, so **the UART link between the satellite and the camera isn't working.** Check:
  - The ESP32-CAM must be **off its USB programmer board**, because it shares the serial pins.
  - Wiring must be crossed: satellite GPIO41 TX → camera U0R/GPIO3, satellite GPIO42 RX ← camera U0T/GPIO1, plus a common GND.
  - Test: `PAYLOAD_PING` should reply `PAYLOAD,PONG,CAMERA`.
  - Ground Station live view also needs its own **DATA LINK CONNECT** button pressed. Joining the Wi-Fi in Windows isn't enough.
  - Workaround: the camera's page at `http://192.168.4.1` does everything.
- **Bluetooth disconnect fix needs a hardware check.** Keep the USB Serial Monitor open. If `SUNSEEK PLATFORM` reprints at a disconnect, it's still crashing.
- **PD gains not tuned.** Try Reaction, start gentle (`ADCS_TUNE,0.5,0,40`), then raise Kd to remove wobble. Watch `POINTING_ERROR`; if it grows, flip `ADCS_CONTROL_SIGN`.
- **Competition tab compatibility:** with v2.1 + GS v1.9, the Competition tab's commands didn't match the firmware (`PREPARE` / `START_MISSION` / `MISSION_TIME_LIMIT` / `MISSION_CLEAR_TARGETS` versus the firmware's `MISSION_*`). **Not yet checked for v3.0.7 + GS v1.10.**
- **Optional idea:** make capture wait until the turn rate is under about 2°/s, for sharper photos. Not implemented.
- Satellite flash is about 84% used (v3.0.7).

## How to compile from the command line (used to verify changes)
```
"C:/Program Files/Arduino IDE/resources/app/lib/backend/resources/arduino-cli.exe" compile --fqbn esp32:esp32:esp32s3 --build-path <tmp> SunSeek_Platform_Firmware_v3_0_7
"C:/Program Files/Arduino IDE/resources/app/lib/backend/resources/arduino-cli.exe" compile --fqbn esp32:esp32:esp32cam --build-path <tmp> SunSeek_ESP32CAM_Payload_Firmware_v3_0
```
The old `Documents\Arduino\libraries\ESP32_BLE_Arduino` library was moved to `Documents\Arduino\libraries_disabled\` because it broke compiling against ESP32 core 3.x.

## 2026-10-08 night — WORKING
- Satellite runs `SunSeek_Platform_Firmware_v3_2_TeamJenny_OURS` with the calibration saved in its Config files (MAG_REVERSE done; heading sign +1, gyro sign -1, control sign +1).
- We confirmed: points to real dial angles very accurately, no wobble.
- Heading check (dial -> reading): -60 -> 308.5 (8.5 deg off), -30 -> 333.9, 0 -> 1.1, +30 -> 31.3, +60 -> 60.6. Only the -60 side is a few degrees off.
- Recalibrate (MAG_CAL + MAG_SET_HEADING) in the competition room, then copy the CAL_STATUS values into Config_Sensor.h.
