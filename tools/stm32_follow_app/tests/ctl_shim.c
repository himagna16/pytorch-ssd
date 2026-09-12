/* Flat ctypes API over follow_controller.c for tests/safety_sim_review6_c.py.
 * Test-only (uses calloc); the controller itself never allocates. */
#include <stdlib.h>

#include "../follow_controller.h"

void *fcs_create(float yaw_sign, int arm_require_fresh)
{
  follow_config_t cfg;
  follow_ctl_t *c = (follow_ctl_t *)calloc(1, sizeof *c);

  if (c == NULL) {
    return NULL;
  }
  follow_ctl_default_config(&cfg);
  cfg.yaw_sign = yaw_sign;
  cfg.arm_require_fresh = (uint8_t)arm_require_fresh;
  if (follow_ctl_init(c, &cfg) != 0) {
    free(c);
    return NULL;
  }
  return c;
}

void fcs_free(void *c)
{
  free(c);
}

/* flags: 1 stale_rule0, 2 warmup, 4 window_reset, 8 saturated, 16 counted, 32 rise_stale
 * (stale through the latency floor), 64 duplicate, 128 floor_reset */
int fcs_on_packet(void *c, const unsigned char *data, unsigned len, unsigned t_rx_us, unsigned *e_us, int *flags)
{
  follow_rx_info_t inf;
  follow_rx_status_t st = follow_ctl_on_packet((follow_ctl_t *)c, data, len, t_rx_us, &inf);

  *e_us = inf.e_us;
  *flags = (inf.stale_rule0 ? 1 : 0) | (inf.warmup ? 2 : 0) | (inf.window_reset ? 4 : 0) |
           (inf.saturated ? 8 : 0) | (inf.counted ? 16 : 0) | (inf.rise_stale ? 32 : 0) |
           (inf.duplicate ? 64 : 0) | (inf.floor_reset ? 128 : 0);
  return (int)st;
}

int fcs_arm(void *c, unsigned now_us)
{
  return (int)follow_ctl_arm((follow_ctl_t *)c, now_us);
}

int fcs_step(void *c, unsigned now_us, float *yaw, float *vx, float *height, int *reason)
{
  follow_output_t o;

  follow_ctl_step((follow_ctl_t *)c, now_us, &o);
  *yaw = o.yaw_rate_dps;
  *vx = o.vx_mps;
  *height = o.target_height_m;
  *reason = (int)o.reason;
  return (int)o.mode;
}
