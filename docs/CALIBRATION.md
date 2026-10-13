# Calibration procedure

Do this **in the room where you will run**. Building steel and wiring change the magnetic field a lot (our X offset moved by more than 1500 counts between rooms).

Put the satellite on the angle dial and connect the ground station. Type the commands in its command box.

1. Enter manual mode:
   ```
   ADCS_MODE,MANUAL
   ```
2. **Gyro zero.** Keep the satellite completely still, then send:
   ```
   GYRO_CAL
   ```
   Wait for `EVT,CAL,GYRO,COMPLETE`.
3. **Magnetometer.**
   ```
   MAG_CAL_START
   ```
   Turn the satellite **2 full circles, slowly and flat**, then:
   ```
   MAG_CAL_STOP
   ```
4. **Zero.** Put the pointer exactly on dial **0**, then:
   ```
   MAG_SET_HEADING,0
   ```
5. **Check.** Put the pointer on +30, −30, +60, −60 and send `MAG_RAW` at each:

   | Dial | `MAG_HEADING` should read |
   |---|---|
   | −60 | 300 |
   | −30 | 330 |
   | 0 | 0 |
   | +30 | 30 |
   | +60 | 60 |

   If +30 reads about 330, the direction is reversed. Send `MAG_REVERSE`, then **`ADCS_CONTROL_SIGN`** with the opposite value, then repeat step 4.
6. **Save.** Send `CAL_STATUS` and copy the values into `Config_Sensor.h`:
   - `MAG_OFFSET_X/Y/Z`
   - `MAG_SCALE_X/Y`, with `MAG_SCALE_Z` left at **1.0**
   - `MAG_HEADING_OFFSET_DEG` and `MAG_HEADING_SIGN`
   - `IMU_BODY_RATE_SIGN`

   Set `ADCS_CONTROL_SIGN` in `Config_ADCS.h` too, then upload.
7. **Test.** Set target 30 in AUTO and check the pointer stops at 30.

## Values in the firmware now (v3.2)

```
MAG_OFFSET_X 125.50   MAG_OFFSET_Y -1507.50   MAG_OFFSET_Z 354.00
MAG_SCALE_X 0.7316    MAG_SCALE_Y 0.6812      MAG_SCALE_Z 1.0
MAG_HEADING_SIGN 1.0  MAG_HEADING_OFFSET_DEG 176.11
IMU_BODY_RATE_SIGN -1.0      ADCS_CONTROL_SIGN 1.0
```
Check: 0 → 0.5°, +30 → 31.5°, −30 → −31.0°.

## The sign rule
The compass direction and the control sign work as a pair.

| Compass sign | Control sign | Result |
|---|---|---|
| −1 | +1 | ❌ trapped 180° from target, chattering |
| −1 | −1 | ✅ |
| +1 | +1 | ✅ (current) |

**Quick control-sign test:** in MANUAL, send `RW,20` and watch the heading for about 1 s, then send `RW_STOP`. The heading should go **up** right away. If it goes down, flip `ADCS_CONTROL_SIGN`.
