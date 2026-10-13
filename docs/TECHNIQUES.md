# Techniques we used

## 1. Systematic code review
- **Line-by-line reading.** We read every firmware file and followed the signal path *sensor → estimator → controller → motor driver → wheel* to check units and signs.
- **Bug list first.** We wrote the list of bugs and suspects before changing anything, and kept the original firmware untouched in its own folder.
- **Every change marked.** Changes go into a **separate, clearly named copy** (`..._TeamSuperTem_OURS`), each marked `TEAM SUPERTEM v3.x` in the code.

## 2. Reverse-engineering the course ground station
The course ground station is a compiled PyInstaller app with no source code. To learn exactly which commands it sends:
1. **Extract the archive.** [`tools/pyinstaller_extract.py`](../tools/pyinstaller_extract.py) finds the PyInstaller cookie (`MEI\x0c\x0b\x0a\x0b\x0e`), reads the table of contents and unpacks the embedded `main` code object.
2. **Make it disassemblable.** We added a Python 3.13 `.pyc` header (magic `F3 0D 0D 0A`).
3. **Disassemble every function.** [`tools/disassemble_py313.py`](../tools/disassemble_py313.py) uses `xdis` to go through every function recursively; that covered 242 functions.
4. **Read the commands it sends.** We read off the command strings, number formats and widget ranges.

What it found is in [GROUND_STATION_v1.10_ANALYSIS.md](GROUND_STATION_v1.10_ANALYSIS.md). It's for compatibility checking only; we don't redistribute the program.

## 3. Using measured hardware data
We designed against our own T01 measurements instead of guessing:

| Measurement | Value | How we used it |
|---|---|---|
| Start-from-rest PWM | +10 % / −11 % | minimum command |
| Keeps-spinning PWM | 3 % | wheel-model "stopped" threshold |
| Time to steady / to stop | ~11 s / ~6 s | wheel-model time constants (3 s / 2 s) |
| Strong vibration above | +45 % / −50 % | power limit 45 % |
| Body rate −294 °/s at Δ20 % | = the gyro's 250 °/s ceiling | gyro range raised to 2000 °/s |

## 4. Wheel-model control
- **Why a model is needed.** With a TB6612 driver, PWM sets wheel *speed* (drive / short-brake), so the push on the body ≈ command − wheel speed. A normal PD assumes command = push.
- **The estimate.** We keep a first-order estimate of wheel speed:
  - driving: `w += (cmd − w)·dt/τ_drive`
  - coasting (0 %): `w −= w·dt/τ_coast`
- **The command.** Each cycle we send **`cmd = w_est + push`**. When holding, push = 0, so the wheel keeps its speed: no kick when entering or leaving hold.

## 5. PD with a hold zone (hysteresis)
- **Control law.** `u = Kp·error − Kd·rate`, with the rate taken straight from the gyro.
- **Entering hold.** Only when |error| < deadband **and** |rate| < rate deadband.
- **Leaving hold.** Only when |error| > hold-exit. This stops chattering at the boundary.

## 6. Sensor fusion (estimator)
- **Filter.** A moving average of the compass heading, using a circular mean so 359° and 1° average to 0°, not 180°.
- **Gyro fusion.** A complementary filter (gyro weight 0.98) fuses that with the integrated gyro. The gyro gives fast, smooth motion; the compass removes drift.

## 7. Calibration
- **Gyro zero.** Gyro bias is averaged for 2 s while still (at every boot and with `GYRO_CAL`).
- **Hard-iron.** The magnetometer hard-iron offset = middle of min/max over two slow flat turns (`MAG_CAL_START/STOP`).
- **Soft-iron.** The X/Y scale is equalized from the min/max ranges.
- **Heading zero.** It's set to the dial with `MAG_SET_HEADING,0`; we verified at ±30° / ±60°.
- **Direction checks.** `SIGN_CHECK` checks gyro vs compass direction; the control sign is checked with `RW,20` (heading must go up).

## 8. Diagnosis from data, not guesses
- **Logs.** The ground station debug report gave the decisive evidence: the satellite was parked 180° from the target with the wheel flipping ±80.
- **Phone video.** Frames extracted with OpenCV (`tools/video_frames.py`, `tools/video_contact_sheet.py`) showed the overshoot and rocking timing.
- **Testing hypotheses.** Each one got a hardware test. Two were wrong (gyro sign, turn-rate limit), and we reverted them.

## 9. Runtime tuning without re-uploading
- **Live settings.** Every new controller parameter has a command (`ADCS_*`), so you can tune from the ground station in seconds.
- **Saved defaults.** Defaults live in `Config_ADCS.h` / `Config_Sensor.h`.

## 10. Safety
- **Wheel stop on state changes.** Leaving AUTO, aborting, finishing a mission and the `STOP` command all stop the wheel.
- **AUTO-only lockouts.** Sign changes and calibration are refused while in AUTO.
- **Thread-safe commands.** Bluetooth commands are queued from the Bluetooth task and run in `loop()`, so they never race with telemetry.
