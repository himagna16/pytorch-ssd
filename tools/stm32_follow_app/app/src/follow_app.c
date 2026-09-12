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
enum { FA_LAND_NONE = 0, FA_LAND_CONTROLLER = 1, FA_LAND_OPERATOR = 2 };

static follow_ctl_t ctl;
static SemaphoreHandle_t ctlMutex;
static logVarId_t logIdZ;
static uint8_t appState = FA_IDLE;
static float zCmd;
static uint32_t landHoldSteps, stopSteps;
static bool holdingPriority;   /* we sent a setpoint at FOLLOW_APP_PRIORITY and have not relaxed it */
static bool needEnableEdge;    /* enable must be seen at 0 before a 1 arms again */

/* Parameters */
static uint8_t pEnable = 0;
static uint8_t pReset = 0;
static int8_t pYawSign = -1;
static uint8_t pArmFresh = 1;
static uint8_t pSrcMask = FA_SRC_MASK_ALL;
static float pArmMinZ = 0.3f;

/* Log variables */
static uint8_t lMode, lReason, lArmErr = 0xFF, lReconf, lLandReason, lLastSrc, lLastRx;
static float lYawRate, lVx, lZCmd, lEms, lRiseMs;
static uint16_t lAgeMs = 0xFFFF;
static uint16_t lRxApp, lRxCpx, lRxRej, lRxStale, lRxIgn;

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

static void sendMotionSetpoint(float vxBody, float yawRateDps, float z)
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
  commanderSetSetpoint(&sp, FOLLOW_APP_PRIORITY);
  holdingPriority = true;
}

static void sendStopSetpoint(void)
{
  static setpoint_t sp;

  memset(&sp, 0, sizeof sp); /* every mode disabled, thrust 0: motors off */
  commanderSetSetpoint(&sp, FOLLOW_APP_PRIORITY);
  holdingPriority = true;
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

static void startLanding(uint8_t why)
{
  appState = FA_LANDING;
  lLandReason = why;
  landHoldSteps = 0;
  pEnable = 0; /* flying again needs followapp.reset and a new enable write (0 -> 1) */
  DEBUG_PRINT("landing (%s)\n", why == FA_LAND_CONTROLLER ? "controller" : "operator");
}

static void followAppStep(void)
{
  const float dt = (float)FOLLOW_APP_PERIOD_MS / 1000.0f;
  const float zEst = logGetFloat(logIdZ);
  follow_output_t out;
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
    } else {
      const follow_arm_status_t a = follow_ctl_arm(&ctl, now);

      lArmErr = (uint8_t)a;
      if (a == FOLLOW_ARM_OK) {
        appState = FA_ACTIVE;
        zCmd = clampf(zEst, 0.0f, ctl.cfg.height_m);
        DEBUG_PRINT("armed, taking over at z=%.2f\n", (double)zCmd);
      }
    }
  }
  follow_ctl_step(&ctl, now, &out); /* every step, also for logging and rule bookkeeping */
  xSemaphoreGive(ctlMutex);

  lMode = (uint8_t)out.mode;
  lReason = (uint8_t)out.reason;
  lAgeMs = (out.frame_age_us == 0xFFFFFFFFu || out.frame_age_us / 1000u > 65534u)
               ? (uint16_t)0xFFFF : (uint16_t)(out.frame_age_us / 1000u);
  lYawRate = 0.0f;
  lVx = 0.0f;

  switch (appState) {
  case FA_ACTIVE:
    if (!pEnable) {
      startLanding(FA_LAND_OPERATOR);
    } else if (out.mode == FOLLOW_MODE_LAND) {
      startLanding(FA_LAND_CONTROLLER);
    } else {
      /* HOVER or FOLLOW: ramp up to the hold height (smooth if the host hovered lower). */
      if (zCmd < out.target_height_m) {
        zCmd = clampf(zCmd + FOLLOW_APP_Z_UP_MPS * dt, 0.0f, out.target_height_m);
      } else {
        zCmd = out.target_height_m;
      }
      lYawRate = out.yaw_rate_dps;
      lVx = out.vx_mps;
      sendMotionSetpoint(out.vx_mps, out.yaw_rate_dps, zCmd);
      break;
    }
    /* fall through: start descending on this step */
  case FA_LANDING:
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
      sendMotionSetpoint(0.0f, 0.0f, zCmd);
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
  logIdZ = logGetVarId("stateEstimate", "z");
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
 * armMinZ; 21 = enable must go 0 -> 1 after a reset) */
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
/** @brief why it landed: 0 none, 1 controller (rule 1), 2 operator */
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
LOG_GROUP_STOP(followapp)
