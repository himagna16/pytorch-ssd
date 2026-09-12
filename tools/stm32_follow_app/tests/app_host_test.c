/* Host test of the Crazyflie app's state machine (app/src/follow_app.c) against stub firmware
 * headers (tests/app_stubs/): enable edge, armMinZ, enable cleared on landing, commander
 * priority relaxed on every exit from DONE (safety review 7, finding 4). The controller itself
 * is covered by test_follow_controller.c; this drives followAppStep/followAppOnPacket directly.
 * Build: make app-test */
#include <stdio.h>
#include <string.h>

#include "../app/src/follow_app.c"

static unsigned long g_checks, g_fail;
#define CHECK(c) do { g_checks++; if (!(c)) { g_fail++; printf("FAIL %s:%d: %s\n", __func__, __LINE__, #c); } } while (0)

/* ---- stub state ---- */
static uint64_t g_now;          /* STM32 us clock */
static float g_z;               /* stateEstimate.z */
static int g_prio;              /* commander priority */
static int g_accepted, g_relaxed;
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
  if (priority >= g_prio) { g_sp = *sp; g_prio = priority; g_accepted++; }
}
void commanderRelaxPriority(void) { g_prio = COMMANDER_PRIORITY_LOWEST; g_relaxed++; }
uint64_t usecTimestamp(void) { return g_now; }
logVarId_t logGetVarId(const char *g, const char *n) { (void)g; (void)n; return 1; }
float logGetFloat(logVarId_t id) { (void)id; return g_z; }

/* ---- packets: 15 Hz, 3 ms link, age 2 ---- */
static uint32_t g_fid;
static void wr32(uint8_t *b, uint32_t v) { b[0] = (uint8_t)v; b[1] = (uint8_t)(v >> 8); b[2] = (uint8_t)(v >> 16); b[3] = (uint8_t)(v >> 24); }
static void send_pkt(uint8_t trk)
{
  uint8_t b[28];
  float x = 0.3f, sz = 0.5f;
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
  g_now = 5000000u; g_z = 0.0f; g_prio = 0; g_accepted = g_relaxed = 0; g_fid = 1; g_tick = 0;
  appState = FA_IDLE; pEnable = 0; pReset = 0; pArmMinZ = 0.3f; holdingPriority = false; needEnableEdge = false;
  zCmd = 0.0f;
  ctlMutex = xSemaphoreCreateMutex();
  resetController();
  logIdZ = logGetVarId("stateEstimate", "z");
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

int main(void)
{
  test_arm_min_z_and_edge();
  test_reset_in_done_relaxes();
  test_arm_min_z_zero();
  printf("follow_app host tests: %lu checks, %lu failures\n", g_checks, g_fail);
  return g_fail != 0;
}
