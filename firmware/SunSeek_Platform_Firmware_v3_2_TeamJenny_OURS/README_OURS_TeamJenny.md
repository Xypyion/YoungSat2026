# TEAM JENNY — OUR VERSION v3.2

## NEW in v3.2 (2026-10-08): wheel-model controller (the wobble fix)
v3.1 is kept unchanged in its own folder.
- **The driver (TB6612) makes 0 % = coast but any small % = mostly BRAKE.** The PD kept switching between the two, which kicked the satellite. The PD also treated the command as a push, but it is really a wheel *speed*.
- **New default `ADCS_CTRL_MODE,WHEEL`:** it estimates the wheel speed (from the T01 timing: about 11 s to spin up, about 6 s to stop) and commands *wheel speed + push*. When holding, the wheel keeps its speed, so there is no kick.
- **Max wheel command 80 → 45 %** (T01: strong vibration above 45 %). Change it live with `ADCS_MAX_CMD,<%>`.
- **Tune the wheel model live:** `ADCS_WHEEL_TAU,<drive_s>,<coast_s>` (default 3, 2).
- **Old behaviour:** `ADCS_CTRL_MODE,PD`. The log line `TM,ADCS_HOLD,...` now also shows `ADCS_WHEEL_EST`.

---
(v3.1 notes below)


**This is our own firmware.** It is based on the official `SunSeek_Platform_Firmware_v3_0_7`, which is left untouched in its own folder.
On boot the Serial Monitor prints: `SUNSEEK PLATFORM v3.1-TeamJenny (OUR VERSION, based on official v3.0.7)`.

Works with Ground Station v1.10. All official commands and telemetry are unchanged; we only **added** things.
The Momentum strategy is not changed.

## What we changed

### 1. Anti-wobble REACTION controller (`Module_ADCS.h`, `Config_ADCS.h`)
The official v3.0.7 code set the wheel to 0 whenever the error was under 2°. That also switched off the Kd braking, so the satellite coasted through the target, overshot, came back, and kept going forever.

| Feature | What it does | Default | Command |
|---|---|---|---|
| HOLD with hysteresis | Stops the wheel only when the satellite is close (< deadband) **and** slow (< rate deadband). Restarts only when the error grows past hold-exit. Kd keeps braking all the way in. | 2° / 2 °/s / exit 4° | `ADCS_DEADBAND,<deg>` `ADCS_RATE_DEADBAND,<deg/s>` `ADCS_HOLD_EXIT,<deg>` |
| Minimum command | A small non-zero command is raised to the smallest value that really turns the wheel. | 5 % (team T01 value `RW_MIN_START_PERCENT`) | `ADCS_MIN_CMD,<%>` (0 = off) |
| Slew limit | Limits how much the wheel command can change every 20 ms, to stop kicks. | off | `ADCS_SLEW,<%>` |
| Max turn rate | On long turns, cruise at this speed instead of speeding up, so it can stop in time. The same as PD for small turns. | off | `ADCS_MAX_RATE,<deg/s>` |
| Integral | Removes a constant offset (e.g. string twist). | off | `ADCS_KI,<Ki>` |

`ADCS_CTRL_STATUS` shows the current values. `ADCS_CTRL_DEFAULTS` resets them. These settings work in MANUAL and AUTO, but are **lost on reboot**.
With the ADCS stream on, there is a new line: `TM,ADCS_HOLD,<0/1>,ADCS_U,<pd>,ADCS_RATE_CMD,<dps>,ADCS_I,<int>`.

### 2. Magnetometer 6.25 Hz → 50 Hz (`Config_Sensor.h` `MAG_CTRL5_VALUE`)
Before, the heading only updated every 160 ms, so the controller reacted late. Set the value back to `0x64` to get the old behaviour.

### 3. Sign check (new command `SIGN_CHECK`, MANUAL only)
Send it, then turn the satellite **by hand** 45–90° one way within 5 s.
The reply is `TM,SIGN_CHECK,MATCH|MISMATCH|TURN_MORE,...`.
**MISMATCH means the gyro and the heading disagree on direction.** In that case Kd *pushes* instead of brakes, and the satellite wobbles forever no matter how you tune it. The fix is to flip `IMU_BODY_RATE_SIGN` in `Config_Sensor.h`.

### 3b. Gyro direction fixed + gyro range (update 2 — 2026-10-08)
- `IMU_BODY_RATE_SIGN` stays at **+1**. I flipped it to −1 by mistake; `SIGN_CHECK` on hardware (2026-10-08) said MISMATCH with −1 and MATCH with +1. So the gyro direction was never the cause of the wobble.
- `GYRO_REVERSE` flips the gyro live if `SIGN_CHECK` still says MISMATCH. `MAG_REVERSE` now flips the gyro together with the heading, so they always agree.
- Gyro range raised from 250 to **2000 °/s**. A test read about −294 °/s, which is the 250 range's ceiling, so the reading was clipped.
- Minimum wheel command changed from 5 % to **10 %** (T01 measured: start +10 % / −11 %).
- `ADCS_CONTROL_SIGN` stays at +1. That is correct with heading sign −1.

### 4. Bug fixes from the review
- **Mission targets 2, 3, …** Official v3.0.7 never turned to them; it stayed on target 1 and "held" every target there. Fixed in `Module_Mission.h`.
- **MAG pointing no longer needs the sun sensor.** Before, a dark or failed sun sensor kicked AUTO back to MANUAL even when using the magnetometer.
- **MAG targets are wrapped into 0–360.** The Ground Station only offers −90…+90, so `-30` now means 330° instead of an error, and `360` means 0.
- **`CAL_STATUS` shows the live calibration values** (boot gyro zero, `MAG_CAL`, `MAG_SET_HEADING`), plus the heading offset and sign.
- **`EVT,MISSION_READY` is sent once**, not twice.

### Not changed (still open)
- **The Ground Station v1.10 Competition tab sends commands this firmware doesn't know:** `PREPARE`, `START_MISSION`, `MISSION_NAME`, `MISSION_TRANSFER`, `MISSION_TIME_LIMIT`, `MISSION_CLEAR_TARGETS`.

## Test plan (Reaction + Magnetometer)
1. Upload this folder. Keep the satellite still while it boots (gyro zero).
2. `ADCS_MODE,MANUAL`, then `SIGN_CHECK` and turn it by hand. You need `MATCH` before continuing.
3. In Ground Station, use Kp 2.5 / Kd 1.2 as now, and turn the ADCS telemetry stream on. Run to a target 90° away.
4. If it still overshoots, try `ADCS_MAX_RATE,20`, then 15 or 10.
5. If it stops short and creeps, raise `ADCS_MIN_CMD`. Find the real value first in MANUAL: `RW,<n>`, increasing n until the wheel just starts turning.
6. If the wheel kicks harshly, try `ADCS_SLEW,5`.
7. When it's good, write the values into `Config_ADCS.h` so they survive a reboot.
