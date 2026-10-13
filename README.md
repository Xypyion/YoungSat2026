# SunSeek — Team Jenny 🛰️

A single-axis training satellite that **turns itself to any target angle with a reaction wheel and takes a photo**.
This repository holds our firmware, our ground station, and the full engineering story of how we found and fixed the "wobble forever" problem.

| | |
|---|---|
| **Satellite computer** | ESP32-S3 (Arduino, ESP32 core 3.x), Bluetooth name `SUNSEEK-Team_Jenny` |
| **Sensors** | GY-89 board: LSM303D magnetometer/accelerometer, L3GD20 gyroscope, BMP180; 2 sun-sensor photodiodes |
| **Actuator** | DC-motor reaction wheel through a TB6612 motor driver |
| **Payload** | AI-Thinker ESP32-CAM (OV2640 + microSD), linked to the satellite by UART, serves photos over its own Wi-Fi |
| **Ground station** | Our Python ground station (`ground_station/`, BLE/USB + simulator + PD tuner) and a browser ground station used for the hardware debug reports |

---

## Result

> **Before:** after turning, the satellite never settled. It rocked back and forth forever, with the wheel slamming between +80 % and −80 %.
> **After (firmware v3.2):** it turns to the real dial angle accurately, holds still, and doesn't wobble. Confirmed on hardware on 2026-10-08.

## The problem and the answer, in one table

| | |
|---|---|
| **Problem** | The satellite kept wiggling after it turned to the target angle. |
| **Real cause** | The **control direction (`ADCS_CONTROL_SIGN`) was reversed** for our compass direction. The wheel pushed the satellite *away* from the target, so it got trapped **180° from the target**, shaking. |
| **How we found it** | A debug report from our own ground station showed target 195° but the satellite at ≈15° (exactly 180° away), with the wheel flipping ±80 every 0.25 s. |
| **Fix** | Reversed the control sign, made it switchable live (`ADCS_CONTROL_SIGN,<1/-1>`), recalibrated the compass, and improved the controller (see below). |

The full story, including the ideas that turned out wrong, is in **[docs/ENGINEERING_LOG.md](docs/ENGINEERING_LOG.md)**.

---

## Repository layout

```
firmware/
  SunSeek_Platform_Firmware_v3_2_TeamJenny_OURS/   <- USE THIS ONE (working, calibrated)
  SunSeek_Platform_Firmware_v3_1_TeamJenny_OURS/   <- our first version (kept for comparison)
  SunSeek_Platform_Firmware_v3_0_7_ORIGINAL_instructors/  <- original firmware we started from
  SunSeek_ESP32CAM_Payload_Firmware_v3_0/          <- camera payload firmware (our fixes inside)
ground_station/       <- our Python ground station (Ground Station Lite)
docs/
  ENGINEERING_LOG.md                  <- what we did, step by step, and why
  TECHNIQUES.md                       <- every technique we used, explained
  COMMANDS.md                         <- all satellite commands (original + ours)
  CALIBRATION.md                      <- compass/gyro calibration procedure + our values
  GROUND_STATION_v1.10_ANALYSIS.md    <- what we found inside the course ground station
  HANDOFF_NOTES.md                    <- working notes
  evidence/                           <- debug report + video frames used in the analysis
tools/                <- small Python tools we wrote for the analysis
```

## What we changed (firmware v3.0.7 → v3.2)

**Pointing control (the wobble)**
- **Control sign switchable live** (`ADCS_CONTROL_SIGN,<1|-1>`), set correctly for our compass direction.
- **Wheel-model controller** (`ADCS_CTRL_MODE,WHEEL`, default). The TB6612 makes PWM a *wheel speed* request (drive / short-brake), so the push on the body ≈ command − wheel speed. We estimate the wheel speed (no sensor; time constants from our T01 measurements) and command *estimated wheel speed + PD push*. The old PD mode is still there (`ADCS_CTRL_MODE,PD`).
- **Hold zone with hysteresis.** The original set the wheel to 0 inside ±2°, which also switched off the Kd braking, so the satellite coasted through the target. Now Kd brakes all the way in, and the controller rests only when close **and** slow.
- **Wheel power limit 80 % → 45 %** (T01 test: strong vibration above +45 % / −50 %).
- **Minimum wheel command 10 %** (T01: the wheel needs +10 % / −11 % to start).
- Optional, tunable live: slew limit, max turn rate, integral term, wheel time constants.

**Sensors**
- **Magnetometer 6.25 Hz → 50 Hz** (heading lagged up to 160 ms behind the 50 Hz control loop).
- **Gyro range 250 → 2000 °/s** (a test read −294 °/s, the ceiling of the 250 °/s range, so the reading was clipped).
- **Gyro auto-zero at boot**, plus `GYRO_CAL`.
- **Live magnetometer calibration** (`MAG_CAL_START/STOP`, `MAG_SET_HEADING`, `MAG_REVERSE`, which flips the gyro too so they always agree).
- **`SIGN_CHECK`**: turn the satellite by hand, and it reports whether the gyro and the compass agree on direction.

**Bug fixes found by reading the code**
- **Missions with several targets** never turned to target 2+. The target couldn't change in AUTO.
- **Magnetometer pointing** dropped out of AUTO when the sun sensor read dark.
- **Negative magnetometer targets** are wrapped into 0–360 (−30 → 330), so the −60…+60 competition range works.
- **`CAL_STATUS`** now reports the values actually in use.
- **`EVT,MISSION_READY`** is sent once instead of twice.
- **Bluetooth:** commands are queued from the Bluetooth task and run in `loop()`, so they no longer race with telemetry.

**Camera payload**
- **SD card re-mount and clear capture errors.** It tries to mount the card again on `STATUS`/`CAPTURE`, and capture failures say why.
- **Stream in its own task.** The live stream no longer blocks `/image` or `/status`.
- **Bigger web-server stack.** 4 KB → 12 KB; the old size crashed when serving `/image`.
- **Built-in photo viewer** at `http://192.168.4.1/`, plus a new `/capture` endpoint.

## Quick start

1. **Wire it.** Satellite GPIO41 → camera U0R, GPIO42 ← camera U0T, common GND. Take the ESP32-CAM off its USB programmer board.
2. **Upload the camera firmware.** In `SunSeek_ESP32CAM_Payload_Firmware_v3_0/Config_Payload.h`, set your own Wi-Fi password, then upload with board **AI Thinker ESP32-CAM**.
3. **Upload the satellite firmware.** Upload `firmware/SunSeek_Platform_Firmware_v3_2_TeamJenny_OURS` with board **ESP32S3 Dev Module**, and keep the satellite still while it boots (gyro auto-zero).
4. **Calibrate in the room where you'll run.** Connect the ground station and follow [docs/CALIBRATION.md](docs/CALIBRATION.md).
5. **Point it.**
   ```
   ADCS_MODE,MANUAL
   ADCS_REFERENCE,MAG
   ADCS_STRATEGY,REACTION
   ADCS_TUNE,2.5,1.2,40
   SET_TARGET,30
   ADCS_MODE,AUTO
   ```
   `STOP` is the emergency stop.

Compile check from the command line:
```
arduino-cli compile --fqbn esp32:esp32:esp32s3 firmware/SunSeek_Platform_Firmware_v3_2_TeamJenny_OURS
arduino-cli compile --fqbn esp32:esp32:esp32cam firmware/SunSeek_ESP32CAM_Payload_Firmware_v3_0
```

## Credits

The original SunSeek platform firmware (v3.0.7), the camera firmware base and the course ground station come from the course instructors (MUT Education Satellite program). Everything marked **TEAM JENNY / OURS** in the code, plus the docs and tools here, is our team's work.
