/*
 * follow_app.c - Crazyflie out-of-tree app: AI-deck person following (packet v6).
 *
 * Wraps the portable controller in ../../follow_controller.c:
 *   - v6 packets arrive from two sources behind one function (followAppOnPacket):
 *       CPX, function CPX_F_APP, from the GAP8 (real hardware; needs CONFIG_ENABLE_CPX)
 *       the CRTP App Channel (simulation/testing: a host sends the same 28 bytes)
 *   - the controller runs at 100 Hz and its output goes to the commander as a
 *     body-frame velocity + yaw-rate + absolute-height setpoint
 *   - idle until the parameter followapp.enable goes 0 -> 1, so the host can take off first;
 *     it then arms the controller (rule 0 warm-up + a fresh frame) once the estimated
 *     height is at least followapp.armMinZ (0.3 m: it never takes off from the ground by
 *     itself unless armMinZ = 0) and takes over
 *   - it lands on its own when the controller says LAND (rule 1) or when
 *     followapp.enable is cleared, stops the motors, and hands the commander back;
 *     a landing clears followapp.enable, and flying again needs followapp.reset and a
 *     new 0 -> 1 write of enable
 *   - first-flight safety modes, latched when the app arms (README "Staged first flights"):
 *       dryRun  (default 0): everything runs and the setpoints are logged (wYaw, wVx), but the
 *                commander is never called: no motion, no motor stop, no priority
 *       yawOnly (default 0): hold the arming point's x/y (stateEstimate) and the hold height
 *                (modeAbs x/y/z); only the yaw rate comes from the network
 *       geofence (default ON): a box of +-fenceX/+-fenceY around the arming point and
 *                z <= fenceZ; outside it, or with no valid Kalman position estimate
 *                (posVarMax), the app runs its normal landing
 *
 * Commander priority: COMMANDER_PRIORITY_EXTRX (3), above CRTP (2) and the
 * high-level commander (1), so a client that is still streaming setpoints cannot
 * fight the app while it flies. The operator's ways out: followapp.enable = 0
 * (the app lands), or the supervisor's emergency stop, which does not depend on
 * setpoint priority. After landing the app relaxes the priority.
 *
 * Nothing here has flown on hardware. It is tested in CrazySim (SITL firmware).
 */
#include <string.h>
#include <stdint.h>
#include <stdbool.h>

#ifndef CONFIG_PLATFORM_SITL
#include "autoconf.h"
#endif

#include "app.h"

#include "FreeRTOS.h"
#include "task.h"
#include "semphr.h"

#include "app_channel.h"
#include "commander.h"
#include "estimator.h"
#include "stabilizer_types.h"
#include "usec_time.h"
#include "log.h"
#include "param.h"
#include "static_mem.h"

#if !defined(CONFIG_PLATFORM_SITL) && defined(CONFIG_ENABLE_CPX)
#include "cpx.h"
#include "cpx_internal_router.h"
#define FOLLOW_APP_HAVE_CPX 1
#else
#define FOLLOW_APP_HAVE_CPX 0
#endif

#define DEBUG_MODULE "FOLLOW"
#include "debug.h"

#include "../../follow_controller.h"

/* ---- Tuning ---------------------------------------------------------------- */
#define FOLLOW_APP_PERIOD_MS       10      /* controller rate: 100 Hz */
#define FOLLOW_APP_PRIORITY        COMMANDER_PRIORITY_EXTRX
#define FOLLOW_APP_Z_UP_MPS        0.5f    /* height ramp when taking over below the hold height */
#define FOLLOW_APP_Z_DOWN_MPS      0.3f    /* landing descent rate */
#define FOLLOW_APP_LANDED_Z_M      0.05f   /* estimated height counted as "on the ground" */
#define FOLLOW_APP_LAND_HOLD_MS    1000    /* after the ramp reaches 0: wait at most this long for touchdown */
#define FOLLOW_APP_STOP_MS         1000    /* send motor-stop setpoints this long, then relax priority */
#define FOLLOW_APP_RX_STACK        (2 * configMINIMAL_STACK_SIZE)
#define FOLLOW_APP_RX_PRIORITY     CONFIG_APP_PRIORITY

/* followapp.armErr values set by the app itself (0..6 are follow_arm_status_t) */
#define FA_ARMERR_LOW              20      /* enabled, but z estimate below followapp.armMinZ */
#define FA_ARMERR_ENABLE_EDGE      21      /* enable was already 1 at a reset: write 0, then 1 */
#define FA_ARMERR_POS              22      /* fenceOn or yawOnly, and no valid position estimate
                                              (followapp.fence says why: 3, 4 or 5) */
#define FA_ARMERR_FENCE            23      /* fenceOn: estimated z above fenceZ, or the hold height
                                              (0.8 m) not below fenceZ */
#define FA_ARMERR_LIMITS           24      /* fenceX/fenceY/fenceZ (fenceOn) or posVarMax (fenceOn or
                                              yawOnly) not a positive finite number */

/* ---- App state (logged as followapp.state) ----------------------------------- */
enum {
  FA_IDLE = 0,      /* followapp.enable = 0: sends nothing; packets still feed the controller */
  FA_WAIT_ARM = 1,  /* enabled, follow_ctl_arm refused (warm-up / no fresh frame): sends nothing */
  FA_ACTIVE = 2,    /* armed: HOVER/FOLLOW setpoints every 10 ms */
  FA_LANDING = 3,   /* descending at FOLLOW_APP_Z_DOWN_MPS */
  FA_DONE = 4       /* landed: motor stop, then priority relaxed; set followapp.reset to re-init */
};

enum { FA_SRC_APPCHANNEL = 0, FA_SRC_CPX = 1 };
#define FA_SRC_MASK_ALL 3u /* followapp.srcMask: bit 0 = app channel, bit 1 = CPX */
enum { FA_LAND_NONE = 0, FA_LAND_CONTROLLER = 1, FA_LAND_OPERATOR = 2, FA_LAND_FENCE = 3, FA_LAND_POS = 4 };

/* Position / geofence status (logged as followapp.fence) */
enum {
  FA_FENCE_OK = 0,        /* valid estimate, and inside the fence (or the fence is not being checked) */
  FA_FENCE_OUT_XY = 1,    /* |x - armX| > fenceX or |y - armY| > fenceY */
  FA_FENCE_OUT_Z = 2,     /* estimated z > fenceZ */
  FA_POS_NO_EST = 3,      /* the estimator is not the Kalman filter, or a log variable is missing */
  FA_POS_NOT_FINITE = 4,  /* x, y, z or a position variance is NaN or infinite */
  FA_POS_UNCERTAIN = 5    /* max(kalman.varX, kalman.varY) > posVarMax: no recent absolute position */
};

/* What the app built on this step (logged as followapp.spKind) */
enum { FA_SP_NONE = 0, FA_SP_VELOCITY = 1, FA_SP_HOLD = 2, FA_SP_LAND = 3, FA_SP_STOP = 4 };

/* followapp.modes bits: this flight's modes, latched when the app armed */
#define FA_MODE_DRYRUN  0x01u
#define FA_MODE_YAWONLY 0x02u
#define FA_MODE_FENCE   0x04u

typedef struct {
  float x, y, z, var;     /* stateEstimate.x/y/z; var = max(kalman.varX, kalman.varY) (m^2) */
} fa_pose_t;

static follow_ctl_t ctl;
static SemaphoreHandle_t ctlMutex;
static logVarId_t logIdZ, logIdX, logIdY, logIdVarX, logIdVarY;
static uint8_t appState = FA_IDLE;
static float zCmd;
static uint32_t landHoldSteps, stopSteps;
static bool holdingPriority;   /* we sent a setpoint at FOLLOW_APP_PRIORITY and have not relaxed it */
static bool needEnableEdge;    /* enable must be seen at 0 before a 1 arms again */

/* This flight's safety modes: copied from the parameters when the app arms, so a parameter
 * write in flight cannot switch the commander off under a flying drone (dryRun 0 -> 1) or
 * move the fence. They take effect at the next arm. */
static bool dryRun, yawOnly, fenceOn;
static float fenceX, fenceY, fenceZ, posVarMax;
static float armX, armY, zHold;  /* arming point and height target (yawOnly holds them) */

/* Parameters */
static uint8_t pEnable = 0;
static uint8_t pReset = 0;
static int8_t pYawSign = -1;
static uint8_t pArmFresh = 1;
static uint8_t pSrcMask = FA_SRC_MASK_ALL;
static float pArmMinZ = 0.3f;
static uint8_t pDryRun = 0;
static uint8_t pYawOnly = 0;
static uint8_t pFenceOn = 1;      /* the one default that changes behaviour: on */
static float pFenceX = 1.0f;      /* m, half-width around the arming point */
static float pFenceY = 1.0f;      /* m */
static float pFenceZ = 1.2f;      /* m, absolute estimated height */
static float pPosVarMax = 0.01f;  /* m^2 (10 cm std); NOT calibrated on hardware: see README M4 */

/* Log variables */
static uint8_t lMode, lReason, lArmErr = 0xFF, lReconf, lLandReason, lLastSrc, lLastRx;
static float lYawRate, lVx, lZCmd, lEms, lRiseMs;
static uint16_t lAgeMs = 0xFFFF;
static uint16_t lRxApp, lRxCpx, lRxRej, lRxStale, lRxIgn;
static float lWYaw, lWVx, lPosVar, lArmX, lArmY;
static uint8_t lSpKind, lFence, lFenceHit, lModes;
static uint32_t lSpCount;

STATIC_MEM_TASK_ALLOC(followRx, FOLLOW_APP_RX_STACK);

static void resetController(void)
{
  follow_config_t cfg;

  follow_ctl_default_config(&cfg);
  cfg.yaw_sign = (pYawSign < 0) ? -1.0f : 1.0f;
  cfg.arm_require_fresh = pArmFresh ? 1u : 0u;
  if (follow_ctl_init(&ctl, &cfg) != 0) {
    DEBUG_PRINT("controller config rejected\n");
  }
  lArmErr = 0xFF;
  lLandReason = FA_LAND_NONE;
  lFenceHit = FA_FENCE_OK;
}

static void lookupLogIds(void)
{
  logIdZ = logGetVarId("stateEstimate", "z");
  logIdX = logGetVarId("stateEstimate", "x");
  logIdY = logGetVarId("stateEstimate", "y");
  logIdVarX = logGetVarId("kalman", "varX");   /* position covariance P[X][X], m^2 */
  logIdVarY = logGetVarId("kalman", "varY");
}

static bool finitef(float v)
{
  return (v == v) && v < 3.0e38f && v > -3.0e38f; /* no math library; NaN != NaN */
}

static bool positiveFinite(float v)
{
  return finitef(v) && v > 0.0f;
}

/* The position estimate and whether it can be trusted: the Kalman filter is the estimator
 * (only it estimates x/y from an absolute source such as Lighthouse), every value is finite,
 * and its x/y position variance is at most varLimit. Without measurements the variance grows
 * every prediction step, so a lost or stale position source shows up here. */
static uint8_t readPose(fa_pose_t *p, float zEst, float varLimit)
{
  float vx, vy;

  p->x = 0.0f;
  p->y = 0.0f;
  p->z = zEst;
  p->var = 0.0f;
  if (stateEstimatorGetType() != StateEstimatorTypeKalman || !logVarIdIsValid(logIdZ) ||
      !logVarIdIsValid(logIdX) || !logVarIdIsValid(logIdY) ||
      !logVarIdIsValid(logIdVarX) || !logVarIdIsValid(logIdVarY)) {
    return FA_POS_NO_EST;
  }
  p->x = logGetFloat(logIdX);
  p->y = logGetFloat(logIdY);
  vx = logGetFloat(logIdVarX);
  vy = logGetFloat(logIdVarY);
  if (!finitef(p->x) || !finitef(p->y) || !finitef(p->z) || !finitef(vx) || !finitef(vy)) {
    return FA_POS_NOT_FINITE;
  }
  p->var = (vx > vy) ? vx : vy;
  if (!(p->var <= varLimit)) {         /* also catches a NaN limit */
    return FA_POS_UNCERTAIN;
  }
  return FA_FENCE_OK;
}

static uint8_t fenceCheck(const fa_pose_t *p)
{
  const float dx = p->x - armX;
  const float dy = p->y - armY;

  if (dx > fenceX || dx < -fenceX || dy > fenceY || dy < -fenceY) {
    return FA_FENCE_OUT_XY;
  }
  if (p->z > fenceZ) {
    return FA_FENCE_OUT_Z;
  }
  return FA_FENCE_OK;
}

/* Parameter sanity for the modes that will be latched at arming. */
static bool limitsOk(void)
{
  if ((pFenceOn || pYawOnly) && !positiveFinite(pPosVarMax)) {
    return false;
  }
  if (pFenceOn && !(positiveFinite(pFenceX) && positiveFinite(pFenceY) && positiveFinite(pFenceZ))) {
    return false;
  }
  return true;
}

/* Copy this flight's modes and the arming point (called once, on the arming step). */
static void latchFlight(const fa_pose_t *p)
{
  dryRun = (pDryRun != 0u);
  yawOnly = (pYawOnly != 0u);
  fenceOn = (pFenceOn != 0u);
  fenceX = pFenceX;
  fenceY = pFenceY;
  fenceZ = pFenceZ;
  posVarMax = pPosVarMax;
  armX = p->x;
  armY = p->y;
  zHold = ctl.cfg.height_m;
  lArmX = armX;
  lArmY = armY;
  lModes = (uint8_t)((dryRun ? FA_MODE_DRYRUN : 0u) | (yawOnly ? FA_MODE_YAWONLY : 0u) |
                     (fenceOn ? FA_MODE_FENCE : 0u));
}

/* The one entry point for both packet sources. Called from the CPX task or the
 * app-channel RX task; the arrival time is taken here. */
static void followAppOnPacket(const uint8_t *data, size_t len, uint8_t src)
{
  follow_rx_info_t info;
  follow_rx_status_t st;
  uint32_t now;

  if (src == FA_SRC_CPX) {
    lRxCpx++;
  } else {
    lRxApp++;
  }
  /* Both sources feed ONE controller: interleaving two streams would upset rule 0
   * (frame_id going backwards resets its window). Fly with one source enabled. */
  if ((pSrcMask & (1u << src)) == 0u) {
    lRxIgn++;
    return;
  }
  xSemaphoreTake(ctlMutex, portMAX_DELAY);
  /* Arrival time read under the mutex (safety review 7): a control step that holds the
   * mutex has read its own `now` after this packet's t_rx, never before. */
  now = (uint32_t)usecTimestamp();
  st = follow_ctl_on_packet(&ctl, data, len, now, &info);
  lLastSrc = src;
  lLastRx = (uint8_t)st;
  if (st == FOLLOW_RX_OK) {
    lEms = (float)info.e_us / 1000.0f;
    lRiseMs = (float)info.rise_us / 1000.0f;
    lReconf = info.reconfirm_count;
  }
  lRxRej = (uint16_t)ctl.stats.rx_rejected;
  lRxStale = (uint16_t)ctl.stats.rx_stale_rule0;
  xSemaphoreGive(ctlMutex);
}

#if FOLLOW_APP_HAVE_CPX
static void cpxAppCallback(const CPXPacket_t *cpxRx)
{
  followAppOnPacket(cpxRx->data, cpxRx->dataLength, FA_SRC_CPX);
}
#endif

static void followRxTask(void *param)
{
  uint8_t buf[APPCHANNEL_MTU];

  (void)param;
  for (;;) {
    const size_t n = appchannelReceiveDataPacket(buf, sizeof buf, APPCHANNEL_WAIT_FOREVER);

    if (n > 0u) {
      followAppOnPacket(buf, n, FA_SRC_APPCHANNEL);
    }
  }
}

/* Every setpoint goes through here. In a dryRun flight it is logged (wYaw, wVx, spKind) and
 * dropped: the commander is never called, so the app never moves the motors, never stops
 * them, and never takes the commander's priority. */
static void submitSetpoint(setpoint_t *sp, uint8_t kind)
{
  lSpKind = kind;
  lWYaw = (sp->mode.yaw == modeVelocity) ? sp->attitudeRate.yaw : 0.0f;
  lWVx = (sp->mode.x == modeVelocity) ? sp->velocity.x : 0.0f;
  if (dryRun) {
    return;
  }
  commanderSetSetpoint(sp, FOLLOW_APP_PRIORITY);
  holdingPriority = true;
  lSpCount++;
  lYawRate = lWYaw;
  lVx = lWVx;
}

static void sendMotionSetpoint(float vxBody, float yawRateDps, float z, uint8_t kind)
{
  static setpoint_t sp;

  memset(&sp, 0, sizeof sp);
  sp.mode.x = modeVelocity;
  sp.mode.y = modeVelocity;
  sp.velocity.x = vxBody;
  sp.velocity.y = 0.0f;
  sp.velocity_body = true;
  sp.mode.z = modeAbs;
  sp.position.z = z;
  sp.mode.yaw = modeVelocity;
  sp.attitudeRate.yaw = yawRateDps; /* firmware convention: + = counter-clockwise from above */
  submitSetpoint(&sp, kind);
}

/* yawOnly: hold the world-frame point (x, y, z) and turn at yawRateDps. Same fields the
 * position controller reads for cflib's send_position_setpoint, except the yaw: modeAbs x/y/z
 * (setpoint_t.position, world frame) and modeVelocity yaw (attitudeRate.yaw), both in
 * stabilizer_types.h of crazyflie-firmware 2026.08 and of the SITL firmware; the PID position
 * controller (position_controller_pid.c) runs a position loop on each modeAbs axis and the
 * attitude loop integrates attitudeRate.yaw when mode.yaw == modeVelocity (controller_pid.c). */
static void sendHoldSetpoint(float x, float y, float z, float yawRateDps)
{
  static setpoint_t sp;

  memset(&sp, 0, sizeof sp);
  sp.mode.x = modeAbs;
  sp.mode.y = modeAbs;
  sp.mode.z = modeAbs;
  sp.position.x = x;
  sp.position.y = y;
  sp.position.z = z;
  sp.velocity_body = false;
  sp.mode.yaw = modeVelocity;
  sp.attitudeRate.yaw = yawRateDps;
  submitSetpoint(&sp, FA_SP_HOLD);
}

static void sendStopSetpoint(void)
{
  static setpoint_t sp;

  memset(&sp, 0, sizeof sp); /* every mode disabled, thrust 0: motors off */
  submitSetpoint(&sp, FA_SP_STOP);
}

/* Hand the commander back (this firmware's commanderGetSetpoint never lowers the
 * priority by itself: without this, CRTP setpoints stay ignored). */
static void relaxPriority(void)
{
  if (holdingPriority) {
    commanderRelaxPriority();
    holdingPriority = false;
  }
}

static float clampf(float v, float lo, float hi)
{
  return (v < lo) ? lo : ((v > hi) ? hi : v);
}

static const char *landReasonName(uint8_t why)
{
  switch (why) {
  case FA_LAND_CONTROLLER: return "controller";
  case FA_LAND_OPERATOR:   return "operator";
  case FA_LAND_FENCE:      return "geofence";
  case FA_LAND_POS:        return "position estimate";
  default:                 return "none";
  }
}

static void startLanding(uint8_t why)
{
  appState = FA_LANDING;
  lLandReason = why;
  landHoldSteps = 0;
  pEnable = 0; /* flying again needs followapp.reset and a new enable write (0 -> 1) */
  DEBUG_PRINT("landing (%s)\n", landReasonName(why));
}

static void followAppStep(void)
{
  const float dt = (float)FOLLOW_APP_PERIOD_MS / 1000.0f;
  const float zEst = logGetFloat(logIdZ);
  follow_output_t out;
  fa_pose_t pose;
  uint8_t posSt, fenceSt;
  uint32_t now;

  if (pReset) {
    pReset = 0;
    if (appState == FA_IDLE || appState == FA_WAIT_ARM || appState == FA_DONE) {
      xSemaphoreTake(ctlMutex, portMAX_DELAY);
      resetController();
      xSemaphoreGive(ctlMutex);
      relaxPriority();                 /* also when reset during DONE's motor-stop phase */
      appState = FA_IDLE;
      needEnableEdge = (pEnable != 0u); /* a leftover enable = 1 must not re-arm */
    }
  }
  if (!pEnable) {
    needEnableEdge = false;
  }
  /* Before arming the limit is the parameter; from the arming step on, this flight's copy. */
  posSt = readPose(&pose, zEst, (appState == FA_IDLE || appState == FA_WAIT_ARM) ? pPosVarMax : posVarMax);

  xSemaphoreTake(ctlMutex, portMAX_DELAY);
  /* Read under the mutex (safety review 7): never earlier than the t_rx of a packet the
   * controller has already processed, so t_fresh is never in this step's future. */
  now = (uint32_t)usecTimestamp();
  if (appState == FA_IDLE && pEnable) {
    if (needEnableEdge) {
      lArmErr = FA_ARMERR_ENABLE_EDGE;
    } else {
      appState = FA_WAIT_ARM;
    }
  }
  if (appState == FA_WAIT_ARM) {
    if (!pEnable) {
      appState = FA_IDLE;
    } else if (pArmMinZ > 0.0f && zEst < pArmMinZ) {
      lArmErr = FA_ARMERR_LOW;         /* no autonomous take-off from the ground */
    } else if (!limitsOk()) {
      lArmErr = FA_ARMERR_LIMITS;
    } else if ((pFenceOn || pYawOnly) && posSt != FA_FENCE_OK) {
      lArmErr = FA_ARMERR_POS;         /* the fence and yawOnly both need x/y */
    } else if (pFenceOn && (pose.z > pFenceZ || !(ctl.cfg.height_m < pFenceZ))) {
      lArmErr = FA_ARMERR_FENCE;       /* would breach the fence at once */
    } else {
      const follow_arm_status_t a = follow_ctl_arm(&ctl, now);

      lArmErr = (uint8_t)a;
      if (a == FOLLOW_ARM_OK) {
        appState = FA_ACTIVE;
        zCmd = clampf(zEst, 0.0f, ctl.cfg.height_m);
        latchFlight(&pose);
        DEBUG_PRINT("armed, taking over at z=%.2f (dryRun %d, yawOnly %d, fence %d at x=%.2f y=%.2f)\n",
                    (double)zCmd, (int)dryRun, (int)yawOnly, (int)fenceOn, (double)armX, (double)armY);
      }
    }
  }
  follow_ctl_step(&ctl, now, &out); /* every step, also for logging and rule bookkeeping */
  xSemaphoreGive(ctlMutex);

  /* The box is checked from the arming step on (it is relative to the arming point). */
  fenceSt = posSt;
  if (posSt == FA_FENCE_OK && fenceOn &&
      (appState == FA_ACTIVE || appState == FA_LANDING || appState == FA_DONE)) {
    fenceSt = fenceCheck(&pose);
  }
  lFence = fenceSt;
  lPosVar = pose.var;

  lMode = (uint8_t)out.mode;
  lReason = (uint8_t)out.reason;
  lAgeMs = (out.frame_age_us == 0xFFFFFFFFu || out.frame_age_us / 1000u > 65534u)
               ? (uint16_t)0xFFFF : (uint16_t)(out.frame_age_us / 1000u);
  lYawRate = 0.0f;
  lVx = 0.0f;
  lWYaw = 0.0f;
  lWVx = 0.0f;
  lSpKind = FA_SP_NONE;

  switch (appState) {
  case FA_ACTIVE:
    if (!pEnable) {
      startLanding(FA_LAND_OPERATOR);
    } else if (out.mode == FOLLOW_MODE_LAND) {
      startLanding(FA_LAND_CONTROLLER);
    } else if ((fenceOn || yawOnly) && posSt != FA_FENCE_OK) {
      lFenceHit = posSt;
      startLanding(FA_LAND_POS);       /* no trustworthy x/y: neither the fence nor the hold works */
    } else if (fenceOn && fenceSt != FA_FENCE_OK) {
      lFenceHit = fenceSt;
      startLanding(FA_LAND_FENCE);
    } else {
      /* HOVER or FOLLOW: ramp up to the hold height (smooth if the host hovered lower). */
      const float zTarget = yawOnly ? zHold : out.target_height_m;

      if (zCmd < zTarget) {
        zCmd = clampf(zCmd + FOLLOW_APP_Z_UP_MPS * dt, 0.0f, zTarget);
      } else {
        zCmd = zTarget;
      }
      if (yawOnly) {
        sendHoldSetpoint(armX, armY, zCmd, out.yaw_rate_dps); /* the network's vx is not used */
      } else {
        sendMotionSetpoint(out.vx_mps, out.yaw_rate_dps, zCmd, FA_SP_VELOCITY);
      }
      break;
    }
    /* fall through: start descending on this step */
  case FA_LANDING:
    /* The same landing for every reason and mode: zero body velocity, height ramped down.
     * It does not use x/y, so it also works when the position estimate is the problem. */
    zCmd = clampf(zCmd - FOLLOW_APP_Z_DOWN_MPS * dt, 0.0f, 3.0f);
    if (zCmd <= 0.0f) {
      landHoldSteps++;
    }
    if (zCmd <= 0.0f && (zEst < FOLLOW_APP_LANDED_Z_M ||
                         landHoldSteps * FOLLOW_APP_PERIOD_MS >= FOLLOW_APP_LAND_HOLD_MS)) {
      appState = FA_DONE;
      stopSteps = 0;
      sendStopSetpoint();
      DEBUG_PRINT("landed\n");
    } else {
      sendMotionSetpoint(0.0f, 0.0f, zCmd, FA_SP_LAND);
    }
    break;
  case FA_DONE:
    if (stopSteps * FOLLOW_APP_PERIOD_MS < FOLLOW_APP_STOP_MS) {
      stopSteps++;
      sendStopSetpoint();
      if (stopSteps * FOLLOW_APP_PERIOD_MS >= FOLLOW_APP_STOP_MS) {
        relaxPriority(); /* the client may command again (motors stay off until it does) */
      }
    }
    break;
  default:
    break; /* FA_IDLE, FA_WAIT_ARM: send nothing */
  }
  lZCmd = zCmd;
}

void appMain(void)
{
  TickType_t last;

  ctlMutex = xSemaphoreCreateMutex();
  resetController();
  lookupLogIds();
  STATIC_MEM_TASK_CREATE(followRx, followRxTask, "FOLLOWRX", NULL, FOLLOW_APP_RX_PRIORITY);
#if FOLLOW_APP_HAVE_CPX
  cpxRegisterAppMessageHandler(cpxAppCallback);
  DEBUG_PRINT("follow app up: CPX + app channel, waiting for followapp.enable\n");
#else
  DEBUG_PRINT("follow app up: app channel only, waiting for followapp.enable\n");
#endif

  last = xTaskGetTickCount();
  for (;;) {
    vTaskDelayUntil(&last, M2T(FOLLOW_APP_PERIOD_MS));
    followAppStep();
  }
}

/**
 * Person-following app (AI-deck packet v6). Set enable to 1 after take-off.
 */
PARAM_GROUP_START(followapp)
/** @brief 0 -> 1 = arm and fly on the controller's output; 0 while flying = land.
 * Cleared by the app when it lands. */
PARAM_ADD(PARAM_UINT8, enable, &pEnable)
/** @brief write 1 to re-initialize the controller (not while flying); then write enable 0 -> 1 */
PARAM_ADD(PARAM_UINT8, reset, &pReset)
/** @brief arm only at or above this estimated height (m); 0 = also from the ground, which means an
 * autonomous take-off to 0.8 m and a hover even without a confirmed target */
PARAM_ADD(PARAM_FLOAT, armMinZ, &pArmMinZ)
/** @brief yaw sign (-1 or 1), applied at boot and on reset */
PARAM_ADD(PARAM_INT8, yawSign, &pYawSign)
/** @brief take-off gate needs a fresh frame (1, default) or only the warm-up (0); applied on reset */
PARAM_ADD(PARAM_UINT8, armFresh, &pArmFresh)
/** @brief packet sources fed to the controller: bit 0 app channel (CRTP), bit 1 CPX (AI deck); default 3.
 * Use 2 (CPX only) for flights with the AI deck, so a stray app-channel packet cannot interleave. */
PARAM_ADD(PARAM_UINT8, srcMask, &pSrcMask)
/** @brief 1 = dry run: run everything and log the setpoints (wYaw, wVx, spKind) but never call the
 * commander (no motion, no motor stop, no priority). Latched when the app arms. For props-off,
 * hand-held checks (M4) or with the host flying. */
PARAM_ADD(PARAM_UINT8, dryRun, &pDryRun)
/** @brief 1 = yaw only: hold the arming point's x/y and the hold height (position setpoint), take only
 * the yaw rate from the network. Needs a valid Kalman position estimate. Latched when the app arms. */
PARAM_ADD(PARAM_UINT8, yawOnly, &pYawOnly)
/** @brief geofence (default 1 = on): outside +-fenceX/+-fenceY around the arming point or above fenceZ,
 * or without a valid position estimate, the app lands. Latched when the app arms. */
PARAM_ADD(PARAM_UINT8, fenceOn, &pFenceOn)
/** @brief fence half-width in x around the arming point (m), default 1.0 */
PARAM_ADD(PARAM_FLOAT, fenceX, &pFenceX)
/** @brief fence half-width in y around the arming point (m), default 1.0 */
PARAM_ADD(PARAM_FLOAT, fenceY, &pFenceY)
/** @brief fence ceiling: maximum estimated height (m), default 1.2; must be above the 0.8 m hold height */
PARAM_ADD(PARAM_FLOAT, fenceZ, &pFenceZ)
/** @brief largest kalman.varX / varY (m^2) counted as a valid position estimate, default 0.01 (10 cm std).
 * Not calibrated on hardware: read followapp.posVar during the M4 dry run */
PARAM_ADD(PARAM_FLOAT, posVarMax, &pPosVarMax)
PARAM_GROUP_STOP(followapp)

/**
 * Person-following app state.
 */
LOG_GROUP_START(followapp)
/** @brief app state: 0 idle, 1 wait arm, 2 active, 3 landing, 4 done */
LOG_ADD(LOG_UINT8, state, &appState)
/** @brief controller mode: 0 WAIT_WARMUP, 1 HOVER, 2 FOLLOW, 3 LAND */
LOG_ADD(LOG_UINT8, mode, &lMode)
/** @brief follow_reason_t of the last step */
LOG_ADD(LOG_UINT8, reason, &lReason)
/** @brief last follow_ctl_arm result (255 = not tried; 6 = link latency rose > 0.1 s; 20 = below
 * armMinZ; 21 = enable must go 0 -> 1 after a reset; 22 = no valid position estimate (fenceOn or
 * yawOnly); 23 = z above fenceZ, or the hold height not below it; 24 = fence/posVarMax params invalid) */
LOG_ADD(LOG_UINT8, armErr, &lArmErr)
/** @brief commanded yaw rate (deg/s, + = counter-clockwise) */
LOG_ADD(LOG_FLOAT, yawRate, &lYawRate)
/** @brief commanded body-frame forward velocity (m/s) */
LOG_ADD(LOG_FLOAT, vx, &lVx)
/** @brief commanded height (m) */
LOG_ADD(LOG_FLOAT, zCmd, &lZCmd)
/** @brief now - t_fresh (ms), 65535 = none */
LOG_ADD(LOG_UINT16, ageMs, &lAgeMs)
/** @brief rule 0 excess latency e of the newest accepted packet (ms) */
LOG_ADD(LOG_FLOAT, eMs, &lEms)
/** @brief newest accepted packet's latency above the rule 0 latency floor (ms; stale above 100) */
LOG_ADD(LOG_FLOAT, riseMs, &lRiseMs)
/** @brief rule 4 re-confirmation count after the newest packet */
LOG_ADD(LOG_UINT8, reconf, &lReconf)
/** @brief why it landed: 0 none, 1 controller (rule 1), 2 operator, 3 geofence, 4 position estimate invalid */
LOG_ADD(LOG_UINT8, landRsn, &lLandReason)
/** @brief packets from the app channel */
LOG_ADD(LOG_UINT16, rxApp, &lRxApp)
/** @brief packets from CPX */
LOG_ADD(LOG_UINT16, rxCpx, &lRxCpx)
/** @brief packets ignored because followapp.srcMask disables their source */
LOG_ADD(LOG_UINT16, rxIgn, &lRxIgn)
/** @brief rejected packets */
LOG_ADD(LOG_UINT16, rxRej, &lRxRej)
/** @brief packets stale by rule 0 (incl. warm-up) */
LOG_ADD(LOG_UINT16, rxStale, &lRxStale)
/** @brief follow_rx_status_t of the newest packet */
LOG_ADD(LOG_UINT8, lastRx, &lLastRx)
/** @brief yaw rate of the setpoint built this step (deg/s), sent or not (dryRun) */
LOG_ADD(LOG_FLOAT, wYaw, &lWYaw)
/** @brief body vx of the setpoint built this step (m/s), sent or not; 0 in yawOnly (position hold) */
LOG_ADD(LOG_FLOAT, wVx, &lWVx)
/** @brief setpoint built this step: 0 none, 1 velocity (follow), 2 position hold (yawOnly), 3 landing, 4 motor stop */
LOG_ADD(LOG_UINT8, spKind, &lSpKind)
/** @brief setpoints actually sent to the commander since boot (stays 0 in a dryRun flight) */
LOG_ADD(LOG_UINT32, nSp, &lSpCount)
/** @brief this flight's modes (latched at arming): bit 0 dryRun, bit 1 yawOnly, bit 2 fence */
LOG_ADD(LOG_UINT8, modes, &lModes)
/** @brief position / fence status: 0 ok, 1 outside x/y, 2 above fenceZ, 3 no Kalman estimate,
 * 4 non-finite estimate, 5 variance above posVarMax */
LOG_ADD(LOG_UINT8, fence, &lFence)
/** @brief the fence status that caused a fence (3) or position (4) landing, else 0 */
LOG_ADD(LOG_UINT8, fenceHit, &lFenceHit)
/** @brief max(kalman.varX, kalman.varY) (m^2), for calibrating posVarMax */
LOG_ADD(LOG_FLOAT, posVar, &lPosVar)
/** @brief arming point x (m), the fence centre and the yawOnly hold point */
LOG_ADD(LOG_FLOAT, armX, &lArmX)
/** @brief arming point y (m) */
LOG_ADD(LOG_FLOAT, armY, &lArmY)
LOG_GROUP_STOP(followapp)
