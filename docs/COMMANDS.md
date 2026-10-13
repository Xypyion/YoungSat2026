# Satellite commands

One ASCII line per command, ending in `\n`. They work over Bluetooth (ground station) and USB Serial (115200).
Replies: `ACK,…` · `ERR,…` · `EVT,…` · `TM,KEY,VALUE,…` · `PAYLOAD,…`

## Basic
| Command | What it does |
|---|---|
| `PING` | replies `PONG` |
| `STATUS` | full status (our firmware also sends `TM,ADCS_CTRL,…`) |
| `STOP` | **emergency stop**: MANUAL, wheel off |
| `RW_STOP` | wheel off |
| `HELP` | list commands |

## Pointing
| Command | What it does |
|---|---|
| `ADCS_MODE,MANUAL` / `ADCS_MODE,AUTO` | controller off / on |
| `ADCS_REFERENCE,MAG` / `SUN` | magnetometer or sun sensor (MANUAL only) |
| `ADCS_STRATEGY,REACTION` / `MOMENTUM` | wheel strategy (MANUAL only) |
| `ADCS_TUNE,<Kp>,<Kd>,<bias>` | gains, e.g. `ADCS_TUNE,2.5,1.2,40` |
| `SET_TARGET,<deg>` | MAG: any value, wrapped to 0–360 (−30 = 330); SUN: −90…90 |

## Team Jenny controller commands (v3.1 / v3.2)
These work in MANUAL or AUTO unless noted, and are **lost on reboot**. Put final values in `Config_ADCS.h` to keep them.

| Command | Default | What it does |
|---|---|---|
| `ADCS_CONTROL_SIGN,<1\|-1>` | +1 | control direction (MANUAL only). Must match the compass direction |
| `ADCS_CTRL_MODE,WHEEL` / `PD` | WHEEL | wheel-model controller / plain PD |
| `ADCS_MAX_CMD,<%>` | 45 | wheel power limit |
| `ADCS_MIN_CMD,<%>` | 10 | smallest command that turns the wheel (0 = off) |
| `ADCS_DEADBAND,<deg>` | 2 | hold when closer than this… |
| `ADCS_RATE_DEADBAND,<deg/s>` | 2 | …and slower than this |
| `ADCS_HOLD_EXIT,<deg>` | 4 | leave hold when the error grows past this |
| `ADCS_SLEW,<%>` | 0 (off) | max command change per 20 ms |
| `ADCS_MAX_RATE,<deg/s>` | 0 (off) | cap on the turn-speed demand |
| `ADCS_KI,<Ki>` | 0 (off) | integral gain |
| `ADCS_WHEEL_TAU,<drive_s>,<coast_s>` | 3, 2 | wheel-model time constants |
| `ADCS_CTRL_STATUS` / `ADCS_CTRL_DEFAULTS` | | show / reset the values above |

## Sensors & calibration
| Command | What it does |
|---|---|
| `GYRO_CAL` | re-zero the gyro (keep still, MANUAL only) |
| `MAG_CAL_START` / `MAG_CAL_STOP` | collect min/max during 2 slow flat circles, apply the result |
| `MAG_SET_HEADING,<deg>` | make the current direction read `<deg>` |
| `MAG_REVERSE` | flip the heading direction (also flips the gyro). **Flip `ADCS_CONTROL_SIGN` too!** |
| `GYRO_REVERSE` | flip only the gyro direction |
| `SIGN_CHECK` | turn by hand for 5 s; replies MATCH / MISMATCH (gyro vs compass) |
| `CAL_STATUS` | all calibration values in use |
| `MAG_RAW`, `GYRO_RAW`, `SUN_RAW` | one reading |
| `ESTIMATOR_STATUS` | filter / fusion settings |
| `TM_STREAM,<SUN\|MAG\|GYRO\|ADCS>,ON\|OFF` | continuous telemetry |

## Wheel (MANUAL)
| Command | What it does |
|---|---|
| `RW,<-100..100>` | Reaction: set the wheel command |
| `MAN_SEQ_ADD,<cmd>,<ms>` / `MAN_SEQ_RUN` / `MAN_SEQ_STOP` / `MAN_SEQ_CLEAR` | timed wheel sequence |
| `RW_BIAS,<%>`, `RW_CMD,<delta>,<assist>,<ms>`, `MOM_PROFILE_*` | Momentum-strategy tools |

## Mission
`MISSION_TARGET,<angle>,<tol>,<hold_s>[,CAPTURE]` · `MISSION_MAX_MIN,<min>` · `MISSION_PREPARE` · `MISSION_START` · `MISSION_ABORT` · `MISSION_RESET` · `MISSION_CLEAR` · `MISSION_STATUS`

## Camera payload
`PAYLOAD_PING` · `PAYLOAD_STATUS` · `CAPTURE` · `PAYLOAD_IMAGE_COUNT` · `PAYLOAD_LAST_IMAGE` · `PAYLOAD_STREAM_START` / `STOP` / `STATUS`
Camera web: `http://192.168.4.1/` (viewer) · `/status` · `/images` · `/image?name=/IMG_0001.JPG` · `/stream` · `/capture`

## New telemetry (ADCS stream)
`TM,ADCS_HOLD,<0|1>,ADCS_U,<pd>,ADCS_RATE_CMD,<dps>,ADCS_I,<int>,ADCS_WHEEL_EST,<%>`
