# Engineering log: from "wobbles forever" to accurate pointing

This is the honest record of what we did, in order. It includes the hypotheses that were **wrong**, because finding out what is *not* the cause was part of the work.

---

## 0. Starting point (2026-10-08)

- Firmware: the instructors' SunSeek Platform v3.0.7, already patched in an earlier session:
  - gyro auto-zero at boot
  - magnetometer calibration commands
  - a Bluetooth command-queue fix
- Mode: **REACTION** wheel strategy, **MAGNETOMETER** reference, Kp 2.5, Kd 1.2.
- Symptom: it reaches the target side, overshoots, comes back, then **wobbles forever**.

## 1. Full code review (firmware + course ground station)

We read every firmware file line by line. The course ground station v1.10 has no source code (it's a compiled PyInstaller `.exe`), so we wrote tools to extract and disassemble its Python 3.13 bytecode (see [TECHNIQUES.md](TECHNIQUES.md#2-reverse-engineering-the-course-ground-station)).

**Firmware bugs found:**

| # | Bug | Where |
|---|---|---|
| 1 | Multi-target missions never turn to target 2+ (`adcsTarget()` refuses changes in AUTO, and the mission only calls it when not in AUTO) | `Module_Mission.h` |
| 2 | Magnetometer pointing drops out of AUTO if the sun sensor reads dark (sun read failure = whole ADCS read failure) | `Module_ADCS.h adcsRead()` |
| 3 | `CAL_STATUS` prints compile-time constants, not the live calibration | `System_Telemetry.h` |
| 4 | `EVT,MISSION_READY` sent twice | router + `loop()` |

**Ground station v1.10 problems found:**

| # | Problem |
|---|---|
| 5 | The Competition tab sends `PREPARE`, `START_MISSION`, `MISSION_NAME`, `MISSION_TRANSFER`, `MISSION_TIME_LIMIT`, `MISSION_CLEAR_TARGETS`; the firmware only knows `MISSION_PREPARE`, `MISSION_START`, `MISSION_MAX_MIN`, `MISSION_CLEAR` |
| 6 | Target boxes only allow −90…+90°, but magnetometer targets must be 0…359.9 |
| 7 | Targets are rounded with `.1f`, so 359.95 becomes `360.0`, which the firmware rejects |

## 2. First wobble theories → firmware v3.1

Things we saw in the code that *could* cause wobble:

- **Deadband kills braking.** Inside ±2° the controller set `u = 0`, which also removed `Kd × rate`. The satellite coasts through the target.
- **Stiction.** Just outside the deadband `u = 2.5 × 2 = 5 %`, which is below the 10 % the wheel needs to start (T01). Nothing happens until the error grows, then it kicks.
- **Slow magnetometer.** It updates at 6.25 Hz while the controller runs at 50 Hz.

v3.1 changes:
- a hold zone with hysteresis (Kd active all the way in)
- minimum command
- optional slew / max-rate / integral
- magnetometer at 50 Hz
- `SIGN_CHECK` command
- the four bug fixes
- MAG target wrapping (−30 → 330)

**Result: "a tad better".** It still wobbled.

## 3. Wrong turn #1: gyro direction

Our records showed the compass direction had been flipped with `MAG_REVERSE` while the gyro direction had not. We concluded they disagreed and flipped the gyro sign.
**Hardware said otherwise:** `SIGN_CHECK` reported **MISMATCH** with our flip and **MATCH** after flipping back. The gyro was never the problem. We reverted it.

Lesson: confirm with a measurement before changing a sign.

## 4. Wrong turn #2: turn-rate limit

`ADCS_MAX_RATE,20` made it **worse**. The satellite turns much faster than 20 °/s, so the limiter braked hard all the time. We turned it off.

## 5. Video analysis

We extracted frames from a phone video (4 frames per second, see `tools/video_*.py` and `docs/evidence/`).
- **0–3.5 s:** an overshoot and swing-back.
- **5–10 s:** continuous small rocking, about once every 1–2 s.

The camera was handheld, so the angle couldn't be measured.

## 6. Physics review → firmware v3.2 (wheel-model controller)

We re-read the motor path against our T01 wheel measurements:

| T01 measurement | Value |
|---|---|
| Wheel starts from rest at | +10 % / −11 % |
| Wheel keeps spinning down to | 3 % |
| Time to steady speed / to stop | ~11 s / ~6 s |
| Strong vibration above | +45 % / −50 % |

Findings:
1. **TB6612 driver.** 0 % = both inputs LOW = **coast**, but any small % = drive for that fraction of the time and **short-brake** the rest. Small commands behave very differently from 0.
2. **PWM sets wheel speed, not torque.** The push on the body ≈ (command − current wheel speed).
3. **`ADCS_MAX_RW_COMMAND` 80 %** was above the vibration limit.

v3.2 adds:
- the **wheel-model controller**: command = estimated wheel speed + PD push. Holding keeps the wheel speed steady, so there is no kick.
- a 45 % power limit
- a live control-sign switch

## 7. The real cause: control sign (found from our own ground station's debug report)

A debug report from our own web ground station (`docs/evidence/gs_debug_report_2026-10-08-14-09-59.txt`) showed:

```
target 195   err  178.59  rw  80
target 195   err -176.64  rw -80
target 195   err  177.17  rw  80      ... for 30 seconds
```

- **The satellite was parked at ≈15°, exactly 180° from the target.** The wheel flipped between +80 and −80 every quarter second.
- **With the wrong control sign, 180° from the target becomes a trap.** The controller pushes *away* from the target. The far side becomes the stable point, and the wheel chatters there forever. With the correct sign that point is unstable.
- **Direct proof (t = 65.3 s).** The error was −93° (it needed to turn negative). The wheel got −80, and the heading went **up** 288 → 349 → 25.
- **The satellite wasn't running our firmware at that moment.** The STATUS reply had no `TM,ADCS_CTRL` line, and it reported `CONTROL_SIGN,1.0`.

**Fix:** `ADCS_CONTROL_SIGN -1` (and made it switchable live).
**Result: confirmed on hardware.** It points accurately with no wobble.

| | Compass sign | Control sign | Result |
|---|---|---|---|
| Before | −1 | **+1** | ❌ trapped 180° away, chattering |
| Fix | −1 | **−1** | ✅ works |
| After recalibration (`MAG_REVERSE`) | +1 | **+1** | ✅ works |

The two signs must **match**. If you flip the compass with `MAG_REVERSE`, flip the control sign too.

## 8. Calibration in the competition room

| Run | Offsets X / Y / Z | Heading zero | ±30° check |
|---|---|---|---|
| 1 (after the fix) | −325 / −1695 / 230.5 | 324.51 | −60 read −51.5 (8° short on the negative side) |
| 2 (new room) | −1483 / −1720 / 259 | 316.64 | +28.6 / −27.6 |
| 3 | 84 / −1483 / 482 | 181.84 | +28.9 / −27.3 |
| 4 | 115.5 / −1509.5 / 447 | 176.62 | +28.3 / −29.2 |
| 5 | 55.5 / −1481 / 434 (535 samples) | 177.46 | +30.9 / −27.4 |
| **6 (in firmware now)** | **125.5 / −1507.5 / 354** | **176.11** | **0 → 0.5, +30 → 31.5, −30 → −31.0** |

- The X offset moving from −325 to over +100 between rooms shows how much building steel and wiring bend the field. **Always recalibrate where you'll run.**
- The Z scale is stored as 1.0: the measured value (5–8) is meaningless when the satellite is only turned flat, and Z doesn't affect heading.

## 9. Open items

- **Possible ~10° overshoot past the target** in the direction of travel (target −30 → −40, target 0 → +10), seen once after recalibration.
  - Suspects: the spinning wheel's motor disturbing the compass, or the controller stopping late.
  - Tests: compare `MAG_RAW` with `RW,20` / `RW,-20` while holding the satellite still, and try `ADCS_CTRL_MODE,PD`.
  - A "stop early" lead correction was tried and reverted before it was uploaded.
- **The Competition tab of course GS v1.10 still doesn't match the firmware's mission commands.**
