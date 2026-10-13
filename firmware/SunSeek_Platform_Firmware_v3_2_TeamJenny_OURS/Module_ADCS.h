#pragma once

/* SunSeek Platform v2.0 — MODULE LAYER */
#include <Arduino.h>
#include <math.h>
#include "Config_ADCS.h"
#include "Module_IMU.h"
#include "Module_SunSensor.h"
#include "Module_ReactionWheel.h"
#include "Module_Estimator.h"

enum ADCSMode { ADCS_MANUAL, ADCS_AUTO };
enum ADCSReference { ADCS_SUN, ADCS_MAG };

struct ADCSState {
  ADCSMode mode;
  ADCSReference ref;
  float target, kp, kd;
  int bias;

  // Raw sensor-domain errors retained for Engineering telemetry.
  float sunError, magError;

  // Controller-domain values.
  float error, rate, u;

  // Estimation chain.
  float rawReference;
  float filteredReference;
  float estimatedAngle;

  bool valid;
};

static ADCSState _a = {
  ADCS_MANUAL, ADCS_SUN,
  ADCS_DEFAULT_TARGET_DEG, ADCS_DEFAULT_KP, ADCS_DEFAULT_KD,
  RW_DEFAULT_BIAS_PERCENT,
  0, 0, 0, 0, 0,
  0, 0, 0,
  false
};

static unsigned long _aLast = 0;
static float _ctrlSign = ADCS_CONTROL_SIGN;   // v3.2: runtime, ADCS_CONTROL_SIGN,<1|-1>
inline float adcsControlSign(){ return _ctrlSign; }
inline bool adcsSetControlSign(float s){ if(s!=1.0f&&s!=-1.0f)return false; _ctrlSign=s; return true; }

// TEAM JENNY v3.1 — anti-wobble Reaction controller (runtime tunable).
struct ADCSCtrlParams {
  float holdEnterDeg, holdRateDps, holdExitDeg;
  int minCmd, slew;
  float maxRateDps, ki;
  int mode;                 // v3.2: 1 = WHEEL model, 0 = PD (v3.1)
  int maxCmd;               // v3.2: runtime wheel command limit
  float tauDrive, tauCoast; // v3.2: wheel model time constants [s]
};
static const ADCSCtrlParams ADCS_CTRL_DEFAULTS_VALUE = {
  ADCS_HOLD_ENTER_DEG, ADCS_HOLD_RATE_DPS, ADCS_HOLD_EXIT_DEG,
  ADCS_DEFAULT_MIN_CMD, ADCS_DEFAULT_SLEW, ADCS_DEFAULT_MAX_RATE, ADCS_DEFAULT_KI,
  ADCS_DEFAULT_CTRL_MODE, ADCS_DEFAULT_MAX_CMD, ADCS_WHEEL_TAU_DRIVE_S, ADCS_WHEEL_TAU_COAST_S
};
static ADCSCtrlParams _ac = ADCS_CTRL_DEFAULTS_VALUE;
static float _acWheel = 0.0f;     // v3.2: estimated wheel speed in command-% units
static bool _acHold = false;
static float _acInt = 0.0f;       // integral of error [deg*s]
static int _acPrevCmd = 0;        // last wheel command sent by AUTO (for slew limit)
static float _acRateCmd = 0.0f;   // telemetry: rate demand used by the rate-limited PD

// Used together with rwStop(), so the wheel estimate restarts at 0.
inline void adcsCtrlReset(){ _acHold=false; _acInt=0.0f; _acPrevCmd=0; _acRateCmd=0.0f; _acWheel=0.0f; }
// Retarget while the wheel keeps spinning: keep the wheel estimate and last command.
inline void adcsCtrlSoftReset(){ _acHold=false; _acInt=0.0f; _acRateCmd=0.0f; }
inline float adcsCtrlWheelEst(){ return _acWheel; }
inline ADCSCtrlParams adcsCtrlGet(){ return _ac; }
inline bool adcsCtrlHolding(){ return _acHold; }
inline float adcsCtrlIntegral(){ return _acInt; }
inline float adcsCtrlRateCmd(){ return _acRateCmd; }
inline void adcsCtrlDefaults(){
  _ac = ADCS_CTRL_DEFAULTS_VALUE;
  adcsCtrlSoftReset();
}
inline bool adcsSetDeadband(float d){ if(!isfinite(d)||d<0||d>20)return false; _ac.holdEnterDeg=d; if(_ac.holdExitDeg<d)_ac.holdExitDeg=d; return true; }
inline bool adcsSetRateDeadband(float r){ if(!isfinite(r)||r<0||r>50)return false; _ac.holdRateDps=r; return true; }
inline bool adcsSetHoldExit(float d){ if(!isfinite(d)||d<_ac.holdEnterDeg||d>30)return false; _ac.holdExitDeg=d; return true; }
inline bool adcsSetMinCmd(int m){ if(m<0||m>60)return false; _ac.minCmd=m; return true; }
inline bool adcsSetSlew(int s){ if(s<0||s>100)return false; _ac.slew=s; return true; }
inline bool adcsSetMaxRate(float r){ if(!isfinite(r)||r<0||r>180)return false; _ac.maxRateDps=r; return true; }
inline bool adcsSetCtrlMode(int m){ if(m!=0&&m!=1)return false; _ac.mode=m; adcsCtrlSoftReset(); return true; }
inline bool adcsSetMaxCmd(int m){ if(m<5||m>100)return false; _ac.maxCmd=m; return true; }
inline bool adcsSetWheelTau(float d,float c){ if(!isfinite(d)||!isfinite(c)||d<0.1f||d>30||c<0.1f||c>30)return false; _ac.tauDrive=d; _ac.tauCoast=c; return true; }
inline bool adcsSetKi(float k){ if(!isfinite(k)||k<0||k>ADCS_KI_MAX)return false; _ac.ki=k; _acInt=0.0f; return true; }

inline float adcsWrap180(float x){ while(x>180)x-=360; while(x<=-180)x+=360; return x; }
inline const char* adcsModeText(){return _a.mode==ADCS_AUTO?"AUTO":"MANUAL";}
inline const char* adcsRefText(){return _a.ref==ADCS_MAG?"MAG":"SUN";}

inline void adcsBegin(){
  estimatorBegin();
  _aLast=millis();
}

inline ADCSState adcsGet(){return _a;}
inline void adcsManual(){
  // v3.0.4 safety invariant: leaving AUTO must also remove actuator output.
  // This prevents the last Reaction PWM command (or a Momentum maneuver timer)
  // from surviving an AUTO -> MANUAL / ABORT transition.
  rwStop();
  _a.mode=ADCS_MANUAL;
  _a.u=0;
  adcsCtrlReset();
}

inline bool adcsReference(ADCSReference r){
  if(_a.mode==ADCS_AUTO)return false;
  _a.ref=r;
  estimatorSetReference(r==ADCS_MAG ? EST_REF_MAG : EST_REF_SUN);
  return true;
}

// Validate/normalize a target for the current reference. MAG: any finite value is
// wrapped into 0..<360 (v3.1: -30 -> 330, 360 -> 0). SUN: must be -90..+90.
inline bool adcsNormalizeTarget(float t,float &out){
  if(!isfinite(t))return false;
  if(_a.ref==ADCS_SUN){ if(t < -90 || t > 90)return false; out=t; return true; }
  while(t>=360.0f)t-=360.0f; while(t<0.0f)t+=360.0f; out=t; return true;
}
inline bool adcsTarget(float t){
  if(_a.mode==ADCS_AUTO)return false;
  float n; if(!adcsNormalizeTarget(t,n))return false;
  _a.target=n;
  return true;
}
// v3.1: the Mission Manager may move to the next target while AUTO stays on.
inline bool adcsRetargetAuto(float t){
  float n; if(!adcsNormalizeTarget(t,n))return false;
  _a.target=n; adcsCtrlSoftReset();
  // Refresh the error now so nobody reads the old target's error before the next cycle.
  _a.error=(_a.ref==ADCS_MAG)?adcsWrap180(_a.target-_a.estimatedAngle):(_a.target-_a.estimatedAngle);
  return true;
}

inline bool adcsTune(float kp,float kd,int bias){
  if(kp<0||kp>ADCS_KP_MAX||kd<0||kd>ADCS_KD_MAX||bias<0||bias>100)return false;
  _a.kp=kp;_a.kd=kd;_a.bias=bias;return true;
}

inline bool adcsRead(){
  IMURawSample r;
  IMUProcessedSample p;
  SunSample s;
  // v3.1: a dark / failed sun sensor must not stop MAG pointing.
  bool sunOk=sunSensorRead(s);
  if(!imuReadRaw(r)||!imuProcess(r,p)||(_a.ref==ADCS_SUN&&!sunOk)){
    _a.valid=false;
    return false;
  }

  if(sunOk) _a.sunError = _a.target - s.angleDeg;
  _a.magError = adcsWrap180(_a.target - p.heading);
  _a.rate = p.bodyRate;

  _a.rawReference = (_a.ref==ADCS_MAG) ? p.heading : s.angleDeg;  // SUN branch only reached when sunOk
  EstimatorReference er = (_a.ref==ADCS_MAG) ? EST_REF_MAG : EST_REF_SUN;
  if(!estimatorUpdate(_a.rawReference, _a.rate, er)){
    _a.valid=false;
    return false;
  }

  EstimatorState es = estimatorGet();
  _a.filteredReference = es.filteredReferenceDeg;
  _a.estimatedAngle = es.estimatedAngleDeg;

  // Controller now consumes the estimator output.
  // With LPF=OFF and Fusion=OFF this is equivalent to the verified v0.2 path.
  _a.error = (_a.ref==ADCS_MAG)
    ? adcsWrap180(_a.target - _a.estimatedAngle)
    : (_a.target - _a.estimatedAngle);

  _a.valid=true;
  return true;
}

inline bool adcsAuto(){
  if(!adcsRead())return false;
  if(rwGetMode()==RW_MODE_MOMENTUM && !rwMomentumProfileReady())return false;
  rwStop();
  if(rwGetMode()==RW_MODE_MOMENTUM && !rwApplyProfileBias())return false;
  adcsCtrlReset();
  _a.mode=ADCS_AUTO; _aLast=0; return true;
}

inline void adcsFault(){rwStop();_a.mode=ADCS_MANUAL;_a.u=0;_a.valid=false;adcsCtrlReset();}

inline void adcsUpdate(){
  unsigned long n=millis(); if(n-_aLast<ADCS_CONTROL_PERIOD_MS)return; _aLast=n;
  if(!adcsRead()){ if(_a.mode==ADCS_AUTO)adcsFault(); else _a.valid=false; return; }
  if(_a.mode!=ADCS_AUTO)return;

  if(rwGetMode()==RW_MODE_REACTION){
    // ---- TEAM JENNY v3.1 anti-wobble Reaction controller ----
    const float dt=ADCS_CONTROL_PERIOD_MS*0.001f;
    float ae=fabsf(_a.error);

    // HOLD with hysteresis: rest only when close AND slow; leave only when clearly off.
    if(!_acHold && ae<_ac.holdEnterDeg && fabsf(_a.rate)<_ac.holdRateDps) _acHold=true;
    else if(_acHold && ae>_ac.holdExitDeg) _acHold=false;

    float u=0.0f;
    if(!_acHold){
      // PD is active all the way to the target, so Kd keeps braking through it.
      if(_ac.maxRateDps>0.0f && _a.kd>0.0f){
        // Rate-limited PD: identical to Kp*e - Kd*rate until the turn speed
        // demand exceeds maxRate, then it cruises at maxRate instead of speeding up.
        _acRateCmd=constrain((_a.kp/_a.kd)*_a.error,-_ac.maxRateDps,_ac.maxRateDps);
        u=_a.kd*(_acRateCmd-_a.rate);
      } else {
        _acRateCmd=0.0f;
        u=_a.kp*_a.error-_a.kd*_a.rate;
      }
      if(_ac.ki>0.0f){
        if(ae<ADCS_I_ZONE_DEG) _acInt+=_a.error*dt;
        float iMax=ADCS_I_LIMIT/_ac.ki;
        _acInt=constrain(_acInt,-iMax,iMax);
        u+=_ac.ki*_acInt;
      }
    }
    _a.u=u;

    const float lim=(float)_ac.maxCmd;
    int c;
    if(_ac.mode==1){
      // v3.2 WHEEL mode: command = estimated wheel speed + push. Holding (u = 0) keeps
      // the wheel at its current speed, so entering/leaving HOLD gives no kick.
      float push=_ctrlSign*u;
      float cf=constrain(_acWheel+push,-lim,lim);
      // Stiction only matters when the wheel is (almost) stopped.
      if(!_acHold && _ac.minCmd>0 && fabsf(_acWheel)<ADCS_WHEEL_STABLE_PCT && fabsf(push)>=0.5f && fabsf(cf)<_ac.minCmd)
        cf=(push>0)?(float)_ac.minCmd:-(float)_ac.minCmd;
      c=(int)roundf(cf);
      if(_ac.slew>0) c=constrain(c,_acPrevCmd-_ac.slew,_acPrevCmd+_ac.slew);
      // Wheel speed model: drive/brake pulls the wheel toward the command; 0 % = coast.
      if(c!=0) _acWheel+=((float)c-_acWheel)*dt/_ac.tauDrive;
      else     _acWheel-=_acWheel*dt/_ac.tauCoast;
    } else {
      // v3.1 PD mode (kept for comparison).
      float cf=constrain(_ctrlSign*u,-lim,lim);
      c=(int)roundf(cf);
      // Stiction: a non-zero demand smaller than minCmd would not turn the wheel at all.
      if(!_acHold && _ac.minCmd>0 && fabsf(cf)>=0.5f && abs(c)<_ac.minCmd) c=(cf>0)?_ac.minCmd:-_ac.minCmd;
      // Slew limit: avoid sudden wheel kicks.
      if(_ac.slew>0) c=constrain(c,_acPrevCmd-_ac.slew,_acPrevCmd+_ac.slew);
    }
    _acPrevCmd=c;
    rwSetReactionCommand(c); return;
  }

  float u=0; if(fabsf(_a.error)>=ADCS_DEADBAND_DEG)u=_a.kp*_a.error-_a.kd*_a.rate; _a.u=u;

  // v3.0 profile-based Momentum AUTO.
  // The PD output is a CONTROL DEMAND; the strategy layer chooses a characterized maneuver.
  if(!rwMomentumProfileReady()){adcsFault();return;}
  if(rwIsMomentumBusy())return; // never restart an assist/recovery every 20 ms
  // Each characterized maneuver begins from nominal BIAS. After a maneuver,
  // recover first; do not stack repeated Assist pulses from a non-bias target.
  if(rwGetState()==RW_MOMENTUM_CONTROL_TARGET){rwStartRecovery();return;}

  MomentumProfile mp=rwMomentumProfileGet();
  float demand=_ctrlSign*u;
  float positionDemand=_ctrlSign*_a.error;
  bool settled=(fabsf(_a.error)<ADCS_DEADBAND_DEG && fabsf(_a.rate)<ADCS_RATE_DEADBAND_DPS);

  // v3.0.4 Momentum reversal guard.
  // PD remains the control-demand gate, but the ANGLE ERROR determines which
  // side of the target the spacecraft is on.  A large D term may oppose the
  // current motion before the target is crossed; that is a damping request,
  // not permission to fire the opposite characterized Assist pulse.
  // Opposite Assist is therefore allowed only after the angle error itself
  // crosses the target (positionDemand changes sign).  Otherwise recover/hold
  // at nominal bias and reassess on the next control cycle.
  if(settled || fabsf(demand)<mp.trigger){ rwStartRecovery(); return; }
  if(positionDemand>=ADCS_DEADBAND_DEG && demand>=mp.trigger){ rwStartProfileCW(); return; }
  if(positionDemand<=-ADCS_DEADBAND_DEG && demand<=-mp.trigger){ rwStartProfileCCW(); return; }
  rwStartRecovery();
}
