#pragma once
/*
  SunSeek Platform v2.0
  TRAINING LEVEL: INTERMEDIATE
  Learner-adjustable ADCS gains, limits and control timing.
*/
#define ADCS_DEFAULT_KP 2.0f
#define ADCS_DEFAULT_KD 0.5f
#define ADCS_DEFAULT_TARGET_DEG 0.0f
#define ADCS_DEADBAND_DEG 2.0f
#define ADCS_MAX_RW_COMMAND 80
#define ADCS_CONTROL_SIGN 1.0f   // v3.1 note: +1 is right with MAG_HEADING_SIGN -1 (the old -1 fix was for heading sign +1)
#define ADCS_CONTROL_PERIOD_MS 20UL
#define ADCS_TM_PERIOD_MS 250UL
#define ADCS_RATE_DEADBAND_DPS 2.0f  // v3.0 initial training baseline; characterize before freeze
#define ADCS_KP_MAX 20.0f
#define ADCS_KD_MAX 20.0f

/*
  ---------------------------------------------------------------------------
  TEAM JENNY v3.1 (OUR VERSION) — anti-wobble REACTION controller
  ---------------------------------------------------------------------------
  These are only the power-up defaults. Every value can be changed live from the
  Ground Station command box (see README_OURS_TeamJenny.md), no re-upload needed.
  Momentum strategy is NOT affected by anything below.

  Why the official v3.0.7 wobbled forever:
    - inside the 2 deg deadband it set u = 0, which also removed the Kd braking,
      so the spacecraft coasted straight through the target (overshoot);
    - just outside the deadband u = Kp*2 = ~5 %, which may be too weak to move the
      wheel, so nothing happened until the error grew, then it kicked too hard.
*/

// HOLD: the controller rests (wheel 0) only when it is close AND slow.
// It leaves HOLD again only when the error grows past ADCS_HOLD_EXIT_DEG.
#define ADCS_HOLD_ENTER_DEG      ADCS_DEADBAND_DEG       // ADCS_DEADBAND,<deg>
#define ADCS_HOLD_RATE_DPS       ADCS_RATE_DEADBAND_DPS  // ADCS_RATE_DEADBAND,<deg/s>
#define ADCS_HOLD_EXIT_DEG       4.0f                    // ADCS_HOLD_EXIT,<deg>

// Smallest wheel command that actually turns the wheel (static friction).
// 0 = off. T01 measured: start from rest +10 % / -11 %, keeps spinning at 3 %.  ADCS_MIN_CMD,<%>
#define ADCS_DEFAULT_MIN_CMD     10

// Max change of wheel command per 20 ms cycle (smooths kicks). 0 = off.  ADCS_SLEW,<%>
#define ADCS_DEFAULT_SLEW        0

// Max turning speed toward the target (stops big overshoot on long turns). 0 = off.
// Same as normal PD while turning slower than this.                  ADCS_MAX_RATE,<deg/s>
#define ADCS_DEFAULT_MAX_RATE    0.0f

// Integral gain (removes a constant offset, e.g. string twist). 0 = off.  ADCS_KI,<Ki>
#define ADCS_DEFAULT_KI          0.0f
#define ADCS_KI_MAX              5.0f
#define ADCS_I_ZONE_DEG          15.0f   // integrate only when error is smaller than this
#define ADCS_I_LIMIT             30.0f   // max integral contribution to wheel command [%]
