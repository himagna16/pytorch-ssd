/* Host stubs of the crazyflie-firmware APIs follow_app.c uses (tests/app_host_test.c only).
 * Every stub header below includes this file. Behavior modeled on src/modules/src/commander.c:
 * commanderSetSetpoint accepts priority >= the current one; commanderRelaxPriority sets LOWEST. */
#ifndef FIRMWARE_STUBS_H
#define FIRMWARE_STUBS_H
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifndef CONFIG_PLATFORM_SITL
#define CONFIG_PLATFORM_SITL 1
#endif
#define CONFIG_APP_PRIORITY 1
#define configMINIMAL_STACK_SIZE 128
#define portMAX_DELAY 0xFFFFFFFFu
#define M2T(ms) (ms)
typedef uint32_t TickType_t;
typedef int *SemaphoreHandle_t;
SemaphoreHandle_t xSemaphoreCreateMutex(void);
int xSemaphoreTake(SemaphoreHandle_t m, uint32_t wait);
int xSemaphoreGive(SemaphoreHandle_t m);
TickType_t xTaskGetTickCount(void);
void vTaskDelayUntil(TickType_t *last, TickType_t inc);
#define STATIC_MEM_TASK_ALLOC(name, stack) static int name##_dummy
#define STATIC_MEM_TASK_CREATE(name, fn, str, arg, prio) ((void)name##_dummy, (void)(fn), (void)(arg))

#define APPCHANNEL_MTU 31
#define APPCHANNEL_WAIT_FOREVER (-1)
size_t appchannelReceiveDataPacket(void *buf, size_t len, int timeout_ms);

typedef enum { modeDisable = 0, modeAbs, modeVelocity } stab_mode_t;
typedef struct {
  uint32_t timestamp;
  struct { float x, y, z; } position;
  struct { float x, y, z; } velocity;
  bool velocity_body;
  struct { float roll, pitch, yaw; } attitudeRate;
  struct { stab_mode_t x, y, z, roll, pitch, yaw; } mode;
} setpoint_t;
#define COMMANDER_PRIORITY_LOWEST 0
#define COMMANDER_PRIORITY_HIGHLEVEL 1
#define COMMANDER_PRIORITY_CRTP 2
#define COMMANDER_PRIORITY_EXTRX 3
void commanderSetSetpoint(setpoint_t *sp, int priority);
void commanderRelaxPriority(void);

uint64_t usecTimestamp(void);
typedef uint16_t logVarId_t;
logVarId_t logGetVarId(const char *group, const char *name);
float logGetFloat(logVarId_t id);
#define PARAM_GROUP_START(g)
#define PARAM_GROUP_STOP(g)
#define PARAM_ADD(t, n, p)
#define LOG_GROUP_START(g)
#define LOG_GROUP_STOP(g)
#define LOG_ADD(t, n, p)
#define DEBUG_PRINT(...) ((void)0)
#endif
