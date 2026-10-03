/* Host test of the Crazyflie app's state machine (app/src/follow_app.c) against stub firmware
 * headers (tests/app_stubs/): enable edge, armMinZ, enable cleared on landing, commander
 * priority relaxed on every exit from DONE (safety review 7, finding 4), and the first-flight
 * safety modes: dryRun never calls the commander, yawOnly holds the latched x/y while the yaw
 * follows the bearing sign, a fence breach lands, an invalid position estimate lands. The
 * controller itself is covered by test_follow_controller.c; this drives
 * followAppStep/followAppOnPacket directly.
 * Build: make app-test */
#include <stdio.h>
#include <string.h>

#include "../app/src/follow_app.c"

static unsigned long g_checks, g_fail;
#define CHECK(c) do { g_checks++; if (!(c)) { g_fail++; printf("FAIL %s:%d: %s\n", __func__, __LINE__, #c); } } while (0)

/* ---- stub state ---- */
static uint64_t g_now;          /* STM32 us clock */
static float g_z;               /* stateEstimate.z */
static float g_x, g_y;          /* stateEstimate.x / y */
static float g_varx, g_vary;    /* kalman.varX / varY */
static StateEstimatorType g_est;
static int g_kalman_log = 1;    /* 0: the firmware has no kalman log group */
static int g_prio;              /* commander priority */
static int g_accepted, g_relaxed, g_calls;
static setpoint_t g_sp;
static int g_mutex;
SemaphoreHandle_t xSemaphoreCreateMutex(void) { return &g_mutex; }
int xSemaphoreTake(SemaphoreHandle_t m, uint32_t w) { (void)w; CHECK(*m == 0); *m = 1; return 1; }
int xSemaphoreGive(SemaphoreHandle_t m) { CHECK(*m == 1); *m = 0; return 1; }
TickType_t xTaskGetTickCount(void) { return (TickType_t)(g_now / 1000u); }
void vTaskDelayUntil(TickType_t *last, TickType_t inc) { *last += inc; }
size_t appchannelReceiveDataPacket(void *buf, size_t len, int t) { (void)buf; (void)len; (void)t; return 0; }
void commanderSetSetpoint(setpoint_t *sp, int priority)
{
  g_calls++;
  if (priority >= g_prio) { g_sp = *sp; g_prio = priority; g_accepted++; }
}
void commanderRelaxPriority(void) { g_prio = COMMANDER_PRIORITY_LOWEST; g_relaxed++; }
uint64_t usecTimestamp(void) { return g_now; }
enum { LID_Z = 1, LID_X, LID_Y, LID_VARX, LID_VARY };
logVarId_t logGetVarId(const char *g, const char *n)
{
  if (strcmp(g, "stateEstimate") == 0) {
    if (strcmp(n, "z") == 0) return LID_Z;
    if (strcmp(n, "x") == 0) return LID_X;
    if (strcmp(n, "y") == 0) return LID_Y;
  }
  if (strcmp(g, "kalman") == 0 && g_kalman_log) {
    if (strcmp(n, "varX") == 0) return LID_VARX;
    if (strcmp(n, "varY") == 0) return LID_VARY;
  }
  return 0xFFFFu;
}
float logGetFloat(logVarId_t id)
{
  switch (id) {
  case LID_Z: return g_z;
  case LID_X: return g_x;
  case LID_Y: return g_y;
  case LID_VARX: return g_varx;
  case LID_VARY: return g_vary;
  default: CHECK(0); return 0.0f;   /* the app must check an id before reading it */
  }
}
StateEstimatorType stateEstimatorGetType(void) { return g_est; }

/* ---- packets: 15 Hz, 3 ms link, age 2 ---- */
static uint32_t g_fid;
static float g_px = 0.3f;       /* x_center of the packets: + = person right of the image centre */
static void wr32(uint8_t *b, uint32_t v) { b[0] = (uint8_t)v; b[1] = (uint8_t)(v >> 8); b[2] = (uint8_t)(v >> 16); b[3] = (uint8_t)(v >> 24); }
static void send_pkt(uint8_t trk)
{
  uint8_t b[28];
  float x = g_px, sz = 0.5f;
  uint32_t u;
  memset(b, 0, sizeof b);
  b[0] = 0xA5; b[1] = 6; b[2] = 24;
  wr32(b + 4, g_fid++);
  memcpy(&u, &x, 4); wr32(b + 8, u);
  memcpy(&u, &sz, 4); wr32(b + 12, u);
  b[16] = trk; b[17] = 4; b[18] = 2; b[19] = 2;
  wr32(b + 24, (uint32_t)((g_now - 3000u) / 1000u) + 123456u);
  followAppOnPacket(b, sizeof b, FA_SRC_APPCHANNEL);
}
/* advance `ms` of time: app step every 10 ms, a packet every 66 ms when `pk` */
static uint32_t g_tick;
static void run(unsigned ms, int pk, uint8_t trk)
{
  unsigned i;
  for (i = 0; i < ms; i++) {
    g_now += 1000u;
    g_tick++;
    if (pk && g_tick % 66u == 0u) send_pkt(trk);
    if (g_tick % 10u == 0u) followAppStep();
  }
}
static void boot(void)
{
  g_now = 5000000u; g_z = 0.0f; g_prio = 0; g_accepted = g_relaxed = g_calls = 0; g_fid = 1; g_tick = 0;
  g_x = g_y = 0.0f; g_varx = g_vary = 1e-4f; g_est = StateEstimatorTypeKalman; g_kalman_log = 1; g_px = 0.3f;
  appState = FA_IDLE; pEnable = 0; pReset = 0; pArmMinZ = 0.3f; holdingPriority = false; needEnableEdge = false;
  zCmd = 0.0f;
  /* safety-mode parameters at their firmware defaults; nothing latched yet */
  pDryRun = 0; pYawOnly = 0; pFenceOn = 1; pFenceX = 1.0f; pFenceY = 1.0f; pFenceZ = 1.2f; pPosVarMax = 0.01f;
  dryRun = yawOnly = fenceOn = false; lSpCount = 0; lModes = 0;
  ctlMutex = xSemaphoreCreateMutex();
  resetController();
  lookupLogIds();
}

/* boot, host take-off to 0.8 m, warm-up, enable: the app takes over on the first step it can.
 * Set the mode parameters between boot() and this. */
static void take_over(void)
{
  g_z = 0.8f;
  run(3000, 1, 3);
  pEnable = 1;
  run(100, 1, 3);
}

static void test_arm_min_z_and_edge(void)
{
  boot();
  run(3000, 1, 3);                              /* warm-up done, on the ground */
  pEnable = 1;
  run(500, 1, 3);
  CHECK(appState == FA_WAIT_ARM && lArmErr == FA_ARMERR_LOW && g_accepted == 0); /* no ground take-off */
  g_z = 0.8f;                                   /* the host took off */
  run(100, 1, 3);
  CHECK(appState == FA_ACTIVE && lArmErr == FOLLOW_ARM_OK && g_prio == COMMANDER_PRIORITY_EXTRX);
  run(1000, 1, 3);
  CHECK(lMode == FOLLOW_MODE_FOLLOW && g_sp.attitudeRate.yaw < 0.0f && g_sp.position.z == 0.8f);

  /* camera lost: rule 1 lands, the app clears enable */
  run(3600, 0, 0);
  CHECK(appState == FA_LANDING && lLandReason == FA_LAND_CONTROLLER && pEnable == 0);
  run(4000, 0, 0);
  CHECK(appState == FA_DONE);
  g_z = 0.0f;
  run(1500, 0, 0);
  CHECK(g_relaxed == 1 && g_prio == COMMANDER_PRIORITY_LOWEST && !holdingPriority);

  /* a leftover enable = 1 at the reset: stays IDLE until enable goes 0 -> 1 */
  pEnable = 1; pReset = 1;
  run(500, 1, 3);
  CHECK(appState == FA_IDLE && lArmErr == FA_ARMERR_ENABLE_EDGE && g_accepted > 0);
  {
    const int acc = g_accepted;
    pEnable = 0; run(20, 1, 3);
    pEnable = 1; run(3000, 1, 3);
    CHECK(appState == FA_WAIT_ARM && lArmErr == FA_ARMERR_LOW && g_accepted == acc); /* on the ground: waits */
  }
  g_z = 0.8f; run(100, 1, 3);
  CHECK(appState == FA_ACTIVE);
}

static void test_reset_in_done_relaxes(void)
{
  boot();
  g_z = 0.8f;
  run(3000, 1, 3);
  pEnable = 1;
  run(1000, 1, 3);
  CHECK(appState == FA_ACTIVE);
  pEnable = 0;                                  /* operator landing */
  run(4000, 1, 3);
  g_z = 0.0f;
  run(20, 1, 3);
  CHECK(appState == FA_DONE && g_prio == COMMANDER_PRIORITY_EXTRX && g_relaxed == 0);
  pReset = 1;                                   /* within DONE's 1 s motor-stop phase */
  run(20, 1, 3);
  CHECK(appState == FA_IDLE && g_relaxed == 1 && g_prio == COMMANDER_PRIORITY_LOWEST);
  run(2000, 1, 3);
  CHECK(g_relaxed == 1 && g_prio == COMMANDER_PRIORITY_LOWEST);  /* nothing sent from IDLE */
  /* a reset with nothing held does not call relax (it would hand the HL commander a state) */
  pReset = 1; run(20, 1, 3);
  CHECK(g_relaxed == 1);
}

static void test_arm_min_z_zero(void)
{
  boot();
  pArmMinZ = 0.0f;                              /* documented: autonomous take-off */
  run(3000, 1, 3);
  pEnable = 1;
  run(100, 1, 3);
  CHECK(appState == FA_ACTIVE);
  run(200, 1, 3);
  CHECK(zCmd > 0.05f && zCmd < 0.8f);           /* ramping up from the ground */
}

/* ---- first-flight safety modes ---------------------------------------------------- */

static void test_dry_run_never_commands(void)
{
  boot();
  pDryRun = 1;
  take_over();
  CHECK(appState == FA_ACTIVE && lModes == (FA_MODE_DRYRUN | FA_MODE_FENCE));
  run(1000, 1, 3);
  /* everything ran: the controller follows, the would-be setpoint is logged ... */
  CHECK(lMode == FOLLOW_MODE_FOLLOW && lSpKind == FA_SP_VELOCITY);
  CHECK(lWYaw < -5.0f);                         /* person right of centre: clockwise (yawSign -1) */
  CHECK(lWVx > 0.0f);                           /* size 0.5 < 0.625: the network asks for forward */
  CHECK(lZCmd == 0.8f);
  /* ... and nothing reached the commander */
  CHECK(g_calls == 0 && g_accepted == 0 && g_prio == 0 && lSpCount == 0);
  CHECK(lYawRate == 0.0f && lVx == 0.0f);       /* the "sent" logs stay 0 */

  /* latched: clearing the parameter in flight does not start commanding */
  pDryRun = 0;
  run(500, 1, 3);
  CHECK(g_calls == 0 && (lModes & FA_MODE_DRYRUN));

  /* the fence still runs: carried 1.2 m out (hand-held M4) -> landing, still nothing sent */
  g_x = 1.2f;
  run(20, 1, 3);
  CHECK(appState == FA_LANDING && lLandReason == FA_LAND_FENCE && lFenceHit == FA_FENCE_OUT_XY && pEnable == 0);
  CHECK(lSpKind == FA_SP_LAND && lWYaw == 0.0f && lWVx == 0.0f);
  run(5000, 1, 3);                              /* ramp to 0, 1 s hold (z never drops: hand-held) */
  CHECK(appState == FA_DONE);
  run(2000, 1, 3);                              /* DONE's motor-stop phase is a no-op too */
  CHECK(g_calls == 0 && g_relaxed == 0 && !holdingPriority && lSpCount == 0);

  /* the next flight latches the cleared parameter: it commands */
  pReset = 1; run(3000, 1, 3);                  /* re-init: rule 0 warm-up again */
  pEnable = 1; run(100, 1, 3);
  CHECK(appState == FA_ACTIVE && !(lModes & FA_MODE_DRYRUN) && lArmX == 1.2f); /* new arming point */
  run(200, 1, 3);
  CHECK(g_calls > 0 && g_prio == COMMANDER_PRIORITY_EXTRX && lSpCount == (uint32_t)g_calls);
  CHECK(g_sp.mode.x == modeVelocity && g_sp.attitudeRate.yaw < 0.0f && lYawRate == lWYaw);
}

static void test_yaw_only_holds_latched_xy(void)
{
  boot();
  pYawOnly = 1;
  g_x = 0.42f; g_y = -0.17f;                    /* arming point */
  take_over();
  CHECK(appState == FA_ACTIVE && lModes == (FA_MODE_YAWONLY | FA_MODE_FENCE));
  CHECK(lArmX == 0.42f && lArmY == -0.17f);
  run(1000, 1, 3);
  CHECK(lMode == FOLLOW_MODE_FOLLOW && lSpKind == FA_SP_HOLD);
  CHECK(g_sp.mode.x == modeAbs && g_sp.mode.y == modeAbs && g_sp.mode.z == modeAbs);
  CHECK(g_sp.position.x == 0.42f && g_sp.position.y == -0.17f && g_sp.position.z == 0.8f);
  CHECK(!g_sp.velocity_body && g_sp.velocity.x == 0.0f && g_sp.velocity.y == 0.0f);
  CHECK(g_sp.mode.yaw == modeVelocity && g_sp.attitudeRate.yaw < -5.0f); /* person right: clockwise */
  CHECK(lWVx == 0.0f && lVx == 0.0f && lYawRate == g_sp.attitudeRate.yaw);

  /* the drone drifts 0.3 m: the setpoint stays on the latched point, not the current one */
  g_x = 0.72f; g_y = 0.05f;
  run(200, 1, 3);
  CHECK(appState == FA_ACTIVE && g_sp.position.x == 0.42f && g_sp.position.y == -0.17f);

  /* person moves to the left of the image: the yaw rate changes sign, x/y still held */
  g_px = -0.3f;
  run(400, 1, 3);
  CHECK(g_sp.attitudeRate.yaw > 5.0f && g_sp.position.x == 0.42f && g_sp.mode.x == modeAbs);

  /* target lost (bit 0 clear): HOVER, yaw rate 0, still a hold at the latched point */
  run(300, 1, 0);
  CHECK(lMode == FOLLOW_MODE_HOVER && g_sp.attitudeRate.yaw == 0.0f && g_sp.mode.x == modeAbs &&
        g_sp.position.y == -0.17f);

  /* latched: clearing yawOnly in flight changes nothing until the next arm */
  pYawOnly = 0;
  run(500, 1, 3);
  CHECK(lSpKind == FA_SP_HOLD && (lModes & FA_MODE_YAWONLY));

  /* operator landing: the app's normal landing (zero velocity, z ramped down) */
  pEnable = 0;
  run(20, 1, 3);
  CHECK(appState == FA_LANDING && lLandReason == FA_LAND_OPERATOR && lSpKind == FA_SP_LAND);
  CHECK(g_sp.mode.x == modeVelocity && g_sp.velocity.x == 0.0f && g_sp.position.z < 0.8f);
}

static void test_yaw_only_needs_position(void)
{
  boot();
  pYawOnly = 1; pFenceOn = 0;                   /* yawOnly alone still needs x/y */
  g_est = StateEstimatorTypeComplementary;
  take_over();
  CHECK(appState == FA_WAIT_ARM && lArmErr == FA_ARMERR_POS && lFence == FA_POS_NO_EST && g_calls == 0);
  g_est = StateEstimatorTypeKalman; g_varx = 0.5f;
  run(100, 1, 3);
  CHECK(appState == FA_WAIT_ARM && lArmErr == FA_ARMERR_POS && lFence == FA_POS_UNCERTAIN && lPosVar == 0.5f);
  g_varx = 1e-4f;
  run(100, 1, 3);
  CHECK(appState == FA_ACTIVE && lModes == FA_MODE_YAWONLY);
  /* estimate goes bad in flight: lands although the fence is off */
  g_x = 0.0f / 0.0f;
  run(20, 1, 3);
  CHECK(appState == FA_LANDING && lLandReason == FA_LAND_POS && lFenceHit == FA_POS_NOT_FINITE);
  CHECK(g_sp.mode.x == modeVelocity && g_sp.velocity.x == 0.0f);  /* the landing does not use x/y */
}

static void fence_flight(float x0, float y0)
{
  boot();
  g_x = x0; g_y = y0;
  take_over();
  CHECK(appState == FA_ACTIVE && lModes == FA_MODE_FENCE && lArmX == x0 && lArmY == y0);
  run(500, 1, 3);
  CHECK(lMode == FOLLOW_MODE_FOLLOW && lFence == FA_FENCE_OK);
}

static void test_fence_breach_lands(void)
{
  /* x: 0.99 m from the arming point is inside, 1.01 m is out */
  fence_flight(0.2f, 0.1f);
  g_x = 0.2f + 0.99f;
  run(200, 1, 3);
  CHECK(appState == FA_ACTIVE && lFence == FA_FENCE_OK);
  /* a parameter write in flight does not move the fence (latched) */
  pFenceX = 0.1f;
  run(100, 1, 3);
  CHECK(appState == FA_ACTIVE);
  g_x = 0.2f + 1.01f;
  run(10, 1, 3);
  CHECK(appState == FA_LANDING && lLandReason == FA_LAND_FENCE && lFenceHit == FA_FENCE_OUT_XY && pEnable == 0);
  CHECK(lSpKind == FA_SP_LAND && g_sp.mode.x == modeVelocity && g_sp.velocity.x == 0.0f &&
        g_sp.attitudeRate.yaw == 0.0f && g_sp.mode.z == modeAbs && g_sp.position.z < 0.8f);
  {
    const float z1 = g_sp.position.z;
    run(1000, 1, 3);
    CHECK(appState == FA_LANDING && g_sp.position.z < z1 - 0.25f);   /* descending at 0.3 m/s */
  }
  g_z = 0.0f;
  run(3000, 1, 3);
  CHECK(appState == FA_DONE && g_relaxed == 1 && g_prio == COMMANDER_PRIORITY_LOWEST);

  /* y, on the negative side */
  fence_flight(0.0f, 0.0f);
  g_y = -1.05f;
  run(10, 1, 3);
  CHECK(appState == FA_LANDING && lLandReason == FA_LAND_FENCE && lFenceHit == FA_FENCE_OUT_XY);

  /* ceiling */
  fence_flight(0.0f, 0.0f);
  g_z = 1.25f;
  run(10, 1, 3);
  CHECK(appState == FA_LANDING && lLandReason == FA_LAND_FENCE && lFenceHit == FA_FENCE_OUT_Z);

  /* fenceOn = 0 keeps the old behaviour: 5 m away and no estimate at all, still following */
  boot();
  pFenceOn = 0;
  g_est = StateEstimatorTypeComplementary;
  take_over();
  CHECK(appState == FA_ACTIVE && lModes == 0);
  g_x = 5.0f; g_z = 2.0f;
  run(500, 1, 3);
  CHECK(appState == FA_ACTIVE && lMode == FOLLOW_MODE_FOLLOW && lSpKind == FA_SP_VELOCITY);
}

static void test_invalid_position_lands(void)
{
  /* variance above posVarMax (Lighthouse lost: the Kalman variance grows) */
  fence_flight(0.0f, 0.0f);
  g_varx = 0.02f;
  run(10, 1, 3);
  CHECK(appState == FA_LANDING && lLandReason == FA_LAND_POS && lFenceHit == FA_POS_UNCERTAIN);
  /* the estimator switched away from Kalman */
  fence_flight(0.0f, 0.0f);
  g_est = StateEstimatorTypeComplementary;
  run(10, 1, 3);
  CHECK(appState == FA_LANDING && lLandReason == FA_LAND_POS && lFenceHit == FA_POS_NO_EST);
  /* non-finite values */
  fence_flight(0.0f, 0.0f);
  g_y = 1.0f / 0.0f;
  run(10, 1, 3);
  CHECK(appState == FA_LANDING && lLandReason == FA_LAND_POS && lFenceHit == FA_POS_NOT_FINITE);
  fence_flight(0.0f, 0.0f);
  g_vary = 0.0f / 0.0f;
  run(10, 1, 3);
  CHECK(appState == FA_LANDING && lLandReason == FA_LAND_POS && lFenceHit == FA_POS_NOT_FINITE);

  /* arming is refused without a valid estimate, and the host keeps control (nothing sent) */
  boot();
  g_varx = 0.03f;
  take_over();
  CHECK(appState == FA_WAIT_ARM && lArmErr == FA_ARMERR_POS && lFence == FA_POS_UNCERTAIN && g_calls == 0);
  g_varx = 1e-4f;
  run(100, 1, 3);
  CHECK(appState == FA_ACTIVE);
  /* a firmware without the kalman log group */
  boot();
  g_kalman_log = 0;
  lookupLogIds();
  take_over();
  CHECK(appState == FA_WAIT_ARM && lArmErr == FA_ARMERR_POS && lFence == FA_POS_NO_EST && g_calls == 0);
}

static void test_fence_arm_checks(void)
{
  /* above the ceiling when enabled */
  boot();
  g_z = 1.3f; run(3000, 1, 3); pEnable = 1; run(100, 1, 3);
  CHECK(appState == FA_WAIT_ARM && lArmErr == FA_ARMERR_FENCE && g_calls == 0);
  /* ceiling not above the 0.8 m hold height */
  boot();
  pFenceZ = 0.8f;
  take_over();
  CHECK(appState == FA_WAIT_ARM && lArmErr == FA_ARMERR_FENCE);
  /* bad numbers */
  boot();
  pFenceX = 0.0f / 0.0f;
  take_over();
  CHECK(appState == FA_WAIT_ARM && lArmErr == FA_ARMERR_LIMITS && g_calls == 0);
  pFenceX = -1.0f; run(50, 1, 3);
  CHECK(lArmErr == FA_ARMERR_LIMITS);
  pFenceX = 1.0f; pPosVarMax = 0.0f; run(50, 1, 3);
  CHECK(lArmErr == FA_ARMERR_LIMITS);
  pPosVarMax = 0.01f; run(50, 1, 3);
  CHECK(appState == FA_ACTIVE);
  /* yawOnly alone still checks posVarMax; the fence numbers are not used then */
  boot();
  pFenceOn = 0; pYawOnly = 1; pFenceX = -1.0f; pPosVarMax = 1.0f / 0.0f;
  take_over();
  CHECK(appState == FA_WAIT_ARM && lArmErr == FA_ARMERR_LIMITS);
  pPosVarMax = 0.01f; run(50, 1, 3);
  CHECK(appState == FA_ACTIVE && lModes == FA_MODE_YAWONLY);
}

int main(void)
{
  test_arm_min_z_and_edge();
  test_reset_in_done_relaxes();
  test_arm_min_z_zero();
  test_dry_run_never_commands();
  test_yaw_only_holds_latched_xy();
  test_yaw_only_needs_position();
  test_fence_breach_lands();
  test_invalid_position_lands();
  test_fence_arm_checks();
  printf("follow_app host tests: %lu checks, %lu failures\n", g_checks, g_fail);
  return g_fail != 0;
}
