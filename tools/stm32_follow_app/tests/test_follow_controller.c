/* Unit tests for follow_controller.c (parse, validation, wrap, rules 0-4,
 * control law). Build: make unit  (cc -std=c99 -Wall -Wextra -Werror). */
#include <math.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>

#include "../follow_controller.h"
#include "follow_packet.h" /* the GAP8's own header (tests/vendor), for layout conformance */

static unsigned long g_checks, g_fail;
#define CHECK(c)                                                                 \
  do {                                                                           \
    g_checks++;                                                                  \
    if (!(c)) {                                                                  \
      g_fail++;                                                                  \
      printf("FAIL %s:%d: %s\n", __func__, __LINE__, #c);                        \
    }                                                                            \
  } while (0)
#define CHECK_MODE(o, m, r) \
  do { CHECK((o).mode == (m)); CHECK((o).reason == (r)); } while (0)

#define MS 1000ull
#define SEC 1000000ull

/* ---- packet builder ------------------------------------------------------ */
static void wr32(uint8_t *b, uint32_t v)
{
  b[0] = (uint8_t)v; b[1] = (uint8_t)(v >> 8); b[2] = (uint8_t)(v >> 16); b[3] = (uint8_t)(v >> 24);
}
static void wrf(uint8_t *b, float f)
{
  uint32_t u;
  memcpy(&u, &f, 4);
  wr32(b, u);
}
static void build(uint8_t *b, uint32_t fid, float x, float size, uint8_t trk, uint8_t age, uint32_t gtx_ms)
{
  memset(b, 0, 28);
  b[0] = 0xA5; b[1] = 6; b[2] = 24; b[3] = 0;
  wr32(b + 4, fid);
  wrf(b + 8, x);
  wrf(b + 12, size);
  b[16] = trk;
  b[17] = (trk & 1) ? 4 : 0xFF;
  b[18] = (trk & 1) ? 2 : 0xFF;
  b[19] = age;
  wr32(b + 20, (trk & 1) ? 5000u : 0x80000000u);
  wr32(b + 24, gtx_ms);
}

/* ---- two-clock simulator: true time T (us, 64-bit) -> STM32 us / GAP8 ms -- */
typedef struct {
  follow_ctl_t ctl;
  uint64_t stm_off;   /* STM32 us clock = (uint32)(T + stm_off) */
  uint64_t g_off;     /* GAP8 ms clock = (uint32)((T + g_off) / 1000) */
  int32_t ppm;        /* STM32 clock drift vs true time (ppm), 0 unless a test sets it */
  uint32_t fid;
  follow_output_t o;  /* last step output */
} sim_t;

static uint32_t stm(const sim_t *s, uint64_t T)
{
  return (uint32_t)(T + s->stm_off + (uint64_t)(((int64_t)T * s->ppm) / 1000000));
}
static uint32_t gms(const sim_t *s, uint64_t T) { return (uint32_t)((T + s->g_off) / 1000u); }

static void sim_init(sim_t *s, uint64_t stm_off, uint64_t g_off)
{
  memset(s, 0, sizeof *s);
  s->stm_off = stm_off;
  s->g_off = g_off;
  CHECK(follow_ctl_init(&s->ctl, NULL) == 0);
}

/* A packet leaves the GAP8 at T - lat and arrives at T. */
static follow_rx_status_t sim_rx(sim_t *s, uint64_t T, uint64_t lat, uint8_t trk, uint8_t age, float x, float size,
                                 follow_rx_info_t *inf)
{
  uint8_t b[28];
  build(b, s->fid++, x, size, trk, age, gms(s, T - lat));
  return follow_ctl_on_packet(&s->ctl, b, 28, stm(s, T), inf);
}

static void sim_step(sim_t *s, uint64_t T)
{
  follow_ctl_step(&s->ctl, stm(s, T), &s->o);
}

/* Healthy 15 Hz stream (period 66 ms, 3 ms link, age 2 = 40 ms) on [T0, T1),
 * control steps every 10 ms; arms at T_arm (0 = never). Returns the time. */
static uint64_t run_healthy(sim_t *s, uint64_t T0, uint64_t T1, uint64_t T_arm, uint8_t trk, float x, float size)
{
  uint64_t T;
  for (T = T0; T < T1; T += MS) {
    if ((T - T0) % (66 * MS) == 0) {
      CHECK(sim_rx(s, T, 3 * MS, trk, 2, x, size, NULL) == FOLLOW_RX_OK);
    }
    if (T_arm && T == T_arm) {
      CHECK(follow_ctl_arm(&s->ctl, stm(s, T)) == FOLLOW_ARM_OK);
    }
    if (T % (10 * MS) == 0) {
      sim_step(s, T);
    }
  }
  return T;
}

/* Boot, warm up, arm at 2.5 s, follow; returns with FOLLOW at T = 3.0 s. */
static uint64_t setup_following(sim_t *s, uint64_t stm_off, uint64_t g_off)
{
  uint64_t T;
  sim_init(s, stm_off, g_off);
  T = run_healthy(s, 0, 3 * SEC, 2500 * MS, 3, 0.3f, 0.5f);
  CHECK_MODE(s->o, FOLLOW_MODE_FOLLOW, FOLLOW_REASON_NONE);
  return T;
}

/* ---- tests ----------------------------------------------------------------- */
static void test_parse(void)
{
  uint8_t b[29];
  follow_packet_fields_t f;
  float nanv = (float)NAN;

  build(b, 0x12345678u, -0.25f, 0.625f, 3, 7, 0xCAFEBABEu);
  CHECK(follow_ctl_parse(b, 28, &f) == FOLLOW_RX_OK);
  CHECK(f.frame_id == 0x12345678u && f.x_center == -0.25f && f.size_center == 0.625f);
  CHECK(f.tracking == 3 && f.x_bin == 4 && f.size_bucket == 2 && f.frame_age_20ms == 7);
  CHECK(f.vis_raw == 5000 && f.gap8_tx_ms == 0xCAFEBABEu);
  CHECK(follow_ctl_parse(b, 27, &f) == FOLLOW_RX_ERR_LEN);
  CHECK(follow_ctl_parse(b, 29, &f) == FOLLOW_RX_ERR_LEN);
  CHECK(follow_ctl_parse(NULL, 28, &f) == FOLLOW_RX_ERR_NULL);
  b[0] = 0xA4; CHECK(follow_ctl_parse(b, 28, &f) == FOLLOW_RX_ERR_MAGIC); b[0] = 0xA5;
  b[1] = 5; CHECK(follow_ctl_parse(b, 28, &f) == FOLLOW_RX_ERR_VERSION);
  b[1] = 7; CHECK(follow_ctl_parse(b, 28, &f) == FOLLOW_RX_ERR_VERSION); b[1] = 6;
  b[2] = 20; CHECK(follow_ctl_parse(b, 28, &f) == FOLLOW_RX_ERR_PAYLOAD_LEN); b[2] = 24;
  b[3] = 1; CHECK(follow_ctl_parse(b, 28, &f) == FOLLOW_RX_ERR_PAYLOAD_LEN); b[3] = 0;
  {
    int v;
    for (v = 4; v < 256; v++) {          /* every byte with a reserved bit */
      if (v & 0xFC) {
        b[16] = (uint8_t)v;
        CHECK(follow_ctl_parse(b, 28, &f) == FOLLOW_RX_ERR_RESERVED_BITS);
      }
    }
    b[16] = 3;
  }
  /* no-target packet (v6 whole byte 0), bit-1-only packet: accepted */
  build(b, 1, 0.0f, 0.0f, 0, 255, 0);
  CHECK(follow_ctl_parse(b, 28, &f) == FOLLOW_RX_OK && f.frame_age_20ms == 255 && f.vis_raw == INT32_MIN);
  build(b, 1, 0.0f, 0.0f, 2, 3, 0);
  CHECK(follow_ctl_parse(b, 28, &f) == FOLLOW_RX_OK && f.tracking == 2);
  /* values are validated only when bit 0 says they are used */
  build(b, 1, nanv, 0.5f, 3, 3, 0); CHECK(follow_ctl_parse(b, 28, &f) == FOLLOW_RX_ERR_BAD_VALUE);
  build(b, 1, 0.1f, nanv, 1, 3, 0); CHECK(follow_ctl_parse(b, 28, &f) == FOLLOW_RX_ERR_BAD_VALUE);
  build(b, 1, 1.5f, 0.5f, 1, 3, 0); CHECK(follow_ctl_parse(b, 28, &f) == FOLLOW_RX_ERR_BAD_VALUE);
  build(b, 1, (float)INFINITY, 0.5f, 1, 3, 0); CHECK(follow_ctl_parse(b, 28, &f) == FOLLOW_RX_ERR_BAD_VALUE);
  build(b, 1, 0.1f, -0.1f, 1, 3, 0); CHECK(follow_ctl_parse(b, 28, &f) == FOLLOW_RX_ERR_BAD_VALUE);
  build(b, 1, nanv, nanv, 2, 3, 0); CHECK(follow_ctl_parse(b, 28, &f) == FOLLOW_RX_OK);
  build(b, 1, -1.0f, 1.0f, 1, 3, 0); CHECK(follow_ctl_parse(b, 28, &f) == FOLLOW_RX_OK);
}

/* The wire layout must match the GAP8's packed struct byte for byte. */
static void test_vendor_layout(void)
{
  follow_packet_t p;
  follow_packet_fields_t f;
  uint8_t b[28];
  typedef char size_ok[(sizeof(follow_packet_t) == FOLLOW_PKT_LEN) ? 1 : -1];
  size_ok dummy;
  (void)dummy;

  CHECK(offsetof(follow_packet_t, payload_len) == FOLLOW_PKT_OFF_PAYLOAD);
  CHECK(offsetof(follow_packet_t, frame_id) == FOLLOW_PKT_OFF_FRAME_ID);
  CHECK(offsetof(follow_packet_t, x_center) == FOLLOW_PKT_OFF_X);
  CHECK(offsetof(follow_packet_t, size_center) == FOLLOW_PKT_OFF_SIZE);
  CHECK(offsetof(follow_packet_t, tracking) == FOLLOW_PKT_OFF_TRACKING);
  CHECK(offsetof(follow_packet_t, x_bin) == FOLLOW_PKT_OFF_X_BIN);
  CHECK(offsetof(follow_packet_t, size_bucket) == FOLLOW_PKT_OFF_SIZE_BKT);
  CHECK(offsetof(follow_packet_t, frame_age_20ms) == FOLLOW_PKT_OFF_AGE);
  CHECK(offsetof(follow_packet_t, vis_raw) == FOLLOW_PKT_OFF_VIS_RAW);
  CHECK(offsetof(follow_packet_t, gap8_tx_ms) == FOLLOW_PKT_OFF_GAP8_TX_MS);
  CHECK(APP_PACKET_MAGIC == FOLLOW_PKT_MAGIC && APP_PACKET_VERSION == FOLLOW_PKT_VERSION);
  CHECK(APP_PACKET_AGE_UNIT_US == FOLLOW_PKT_AGE_UNIT_US && APP_PACKET_AGE_SATURATED == FOLLOW_PKT_AGE_SATURATED);
  CHECK(FOLLOW_PACKET_TRK_CONFIRMED == FOLLOW_TRK_CONFIRMED && FOLLOW_PACKET_TRK_FRAME_VISIBLE == FOLLOW_TRK_FRAME_VISIBLE);
  CHECK(FOLLOW_PACKET_TRK_RESERVED_MASK == FOLLOW_TRK_RESERVED_MASK);

  memset(&p, 0, sizeof p);
  p.magic = APP_PACKET_MAGIC; p.version = APP_PACKET_VERSION; p.payload_len = 24;
  p.frame_id = 0xA1B2C3D4u; p.x_center = 0.625f; p.size_center = 0.375f;
  p.tracking = follow_packet_tracking_byte(1, 1); p.x_bin = 7; p.size_bucket = 1;
  p.frame_age_20ms = 3; p.vis_raw = -123456; p.gap8_tx_ms = 0xFFFFFFF0u;
  memcpy(b, &p, 28);                      /* the GAP8 memcpy's the same struct */
  CHECK(follow_ctl_parse(b, 28, &f) == FOLLOW_RX_OK);
  CHECK(f.frame_id == p.frame_id && f.x_center == p.x_center && f.size_center == p.size_center);
  CHECK(f.tracking == 3 && f.x_bin == 7 && f.size_bucket == 1 && f.frame_age_20ms == 3);
  CHECK(f.vis_raw == -123456 && f.gap8_tx_ms == 0xFFFFFFF0u);
  /* bit helpers agree for every legal byte */
  {
    int v;
    for (v = 0; v < 4; v++) {
      p.tracking = (uint8_t)v;
      CHECK(follow_packet_is_confirmed(&p) == ((v & FOLLOW_TRK_CONFIRMED) != 0));
      CHECK(follow_packet_counts_for_reconfirm(&p) == (v == 3));
    }
  }
}

static void test_config(void)
{
  follow_config_t c;
  follow_ctl_t ctl;
  follow_output_t o;

  follow_ctl_default_config(&c);
  CHECK(follow_ctl_init(&ctl, &c) == 0);
  CHECK(c.hover_us == 500000u && c.land_us == 3000000u && c.e_stale_us == 100000u && c.warmup_us == 2000000u);
  CHECK(c.yaw_sign == -1.0f && c.k_yaw_dps == 60.0f && c.yaw_deadband == 0.08f && c.yaw_max_dps == 40.0f);
  CHECK(c.k_fwd_mps == 0.8f && c.target_size == 0.625f && c.v_max_mps == 0.3f && c.height_m == 0.8f);
  CHECK(c.confirm_packets == 3 && c.arm_require_fresh == 1);
  c.arm_require_fresh = 2; CHECK(follow_ctl_init(&ctl, &c) == -1); c.arm_require_fresh = 1;
  c.yaw_sign = 0.5f; CHECK(follow_ctl_init(&ctl, &c) == -1);
  CHECK(follow_ctl_arm(&ctl, 0) == FOLLOW_ARM_ERR_CONFIG);
  follow_ctl_step(&ctl, 0, &o); CHECK(o.mode == FOLLOW_MODE_WAIT_WARMUP && o.target_height_m == 0.0f);
  follow_ctl_default_config(&c); c.land_us = 4100000u; CHECK(follow_ctl_init(&ctl, &c) == -1); /* 5.08 s - 1 s */
  follow_ctl_default_config(&c); c.land_us = 4080000u; CHECK(follow_ctl_init(&ctl, &c) == 0);
  follow_ctl_default_config(&c); c.hover_us = c.land_us; CHECK(follow_ctl_init(&ctl, &c) == -1);
  follow_ctl_default_config(&c); c.v_max_mps = (float)NAN; CHECK(follow_ctl_init(&ctl, &c) == -1);
  follow_ctl_default_config(&c); c.confirm_packets = 0; CHECK(follow_ctl_init(&ctl, &c) == -1);
  follow_ctl_default_config(&c); c.yaw_sign = 1.0f; CHECK(follow_ctl_init(&ctl, &c) == 0);
}

static void test_warmup_and_arm(void)
{
  sim_t s;
  follow_rx_info_t inf;
  uint64_t T;

  sim_init(&s, 0, 0);
  CHECK(follow_ctl_arm(&s.ctl, 0) == FOLLOW_ARM_ERR_WARMUP);   /* no packet yet */
  sim_step(&s, 0);
  CHECK_MODE(s.o, FOLLOW_MODE_WAIT_WARMUP, FOLLOW_REASON_NOT_ARMED);
  CHECK(s.o.target_height_m == 0.0f && s.o.frame_age_us == 0xFFFFFFFFu);
  for (T = 0; T < 2 * SEC; T += 100 * MS) {                    /* 2 s of packets: all stale */
    CHECK(sim_rx(&s, T, 3 * MS, 3, 2, 0.3f, 0.5f, &inf) == FOLLOW_RX_OK);
    CHECK(inf.warmup && inf.stale_rule0 && !inf.counted && inf.e_us == 0);
    CHECK(follow_ctl_arm(&s.ctl, stm(&s, T)) == FOLLOW_ARM_ERR_WARMUP);
  }
  sim_step(&s, T - 50 * MS);
  CHECK(s.o.mode == FOLLOW_MODE_WAIT_WARMUP && s.o.frame_age_us == 0xFFFFFFFFu); /* warm-up never set t_fresh */
  CHECK(sim_rx(&s, T, 3 * MS, 3, 2, 0.3f, 0.5f, &inf) == FOLLOW_RX_OK);            /* exactly 2.0 s */
  CHECK(!inf.warmup && !inf.stale_rule0 && inf.counted && inf.reconfirm_count == 1);
  CHECK(follow_ctl_arm(&s.ctl, stm(&s, T)) == FOLLOW_ARM_OK);
  CHECK(follow_ctl_arm(&s.ctl, stm(&s, T)) == FOLLOW_ARM_OK);                      /* idempotent */
  sim_step(&s, T);
  CHECK_MODE(s.o, FOLLOW_MODE_HOVER, FOLLOW_REASON_HOVER_RECONFIRM);                /* 1 of 3 */
  CHECK(s.o.target_height_m == 0.8f && s.o.frame_age_us == 40000u);
  CHECK(sim_rx(&s, T + 66 * MS, 3 * MS, 3, 2, 0.3f, 0.5f, &inf) == FOLLOW_RX_OK);
  sim_step(&s, T + 70 * MS); CHECK(s.o.reason == FOLLOW_REASON_HOVER_RECONFIRM);
  CHECK(sim_rx(&s, T + 132 * MS, 3 * MS, 3, 2, 0.3f, 0.5f, &inf) == FOLLOW_RX_OK);
  CHECK(inf.reconfirm_count == 3);
  sim_step(&s, T + 140 * MS);
  CHECK_MODE(s.o, FOLLOW_MODE_FOLLOW, FOLLOW_REASON_NONE);

  /* arming needs a fresh frame: warm but the newest valid frame is 0.6 s old */
  sim_init(&s, 0, 0);
  run_healthy(&s, 0, 2200 * MS, 0, 3, 0.3f, 0.5f);
  CHECK(follow_ctl_arm(&s.ctl, stm(&s, 2800 * MS)) == FOLLOW_ARM_ERR_NO_FRESH_FRAME);
  /* never arm on an age-255 packet */
  sim_init(&s, 0, 0);
  run_healthy(&s, 0, 2200 * MS, 0, 3, 0.3f, 0.5f);
  CHECK(sim_rx(&s, 2200 * MS, 3 * MS, 0, 255, 0.0f, 0.0f, &inf) == FOLLOW_RX_OK && inf.saturated);
  CHECK(follow_ctl_arm(&s.ctl, stm(&s, 2200 * MS)) == FOLLOW_ARM_ERR_NO_FRESH_FRAME);
  /* newest packet late by rule 0 */
  sim_init(&s, 0, 0);
  run_healthy(&s, 0, 2200 * MS, 0, 3, 0.3f, 0.5f);
  CHECK(sim_rx(&s, 2210 * MS, 150 * MS, 3, 2, 0.3f, 0.5f, &inf) == FOLLOW_RX_OK && inf.stale_rule0);
  CHECK(follow_ctl_arm(&s.ctl, stm(&s, 2210 * MS)) == FOLLOW_ARM_ERR_STALE_PACKET);

  /* arm_require_fresh = 0 (the Python model's take-off): only warm-up and no age-255 packet */
  {
    follow_config_t c;
    follow_ctl_default_config(&c);
    c.arm_require_fresh = 0;
    sim_init(&s, 0, 0);
    CHECK(follow_ctl_init(&s.ctl, &c) == 0);
    CHECK(follow_ctl_arm(&s.ctl, 0) == FOLLOW_ARM_ERR_WARMUP);
    run_healthy(&s, 0, 2200 * MS, 0, 3, 0.3f, 0.5f);
    CHECK(follow_ctl_arm(&s.ctl, stm(&s, 2800 * MS)) == FOLLOW_ARM_OK);   /* frame 0.6 s old */
    sim_step(&s, 2800 * MS); CHECK_MODE(s.o, FOLLOW_MODE_HOVER, FOLLOW_REASON_HOVER_STALE);
    sim_step(&s, 5300 * MS); CHECK_MODE(s.o, FOLLOW_MODE_LAND, FOLLOW_REASON_LAND_STALE);
    sim_init(&s, 0, 0);
    CHECK(follow_ctl_init(&s.ctl, &c) == 0);
    run_healthy(&s, 0, 2200 * MS, 0, 3, 0.3f, 0.5f);
    CHECK(sim_rx(&s, 2200 * MS, 3 * MS, 0, 255, 0.0f, 0.0f, NULL) == FOLLOW_RX_OK);
    CHECK(follow_ctl_arm(&s.ctl, stm(&s, 2200 * MS)) == FOLLOW_ARM_ERR_NO_FRESH_FRAME);
    CHECK(sim_rx(&s, 2260 * MS, 3 * MS, 3, 2, 0.3f, 0.5f, NULL) == FOLLOW_RX_OK);  /* valid again */
    CHECK(follow_ctl_arm(&s.ctl, stm(&s, 2260 * MS)) == FOLLOW_ARM_OK);
  }
}

/* Rules 1 and 2 at their exact boundaries, and the LAND latch. */
static void test_rule1_rule2_silence(void)
{
  sim_t s;
  uint64_t T = setup_following(&s, 0, 0);
  follow_rx_info_t inf;
  uint64_t t_fresh;

  CHECK(sim_rx(&s, T, 3 * MS, 3, 2, 0.3f, 0.5f, &inf) == FOLLOW_RX_OK && inf.e_us == 0);
  t_fresh = T - 40 * MS;                    /* t_rx - e - age*20 ms */
  sim_step(&s, t_fresh + 500 * MS);           CHECK(s.o.mode == FOLLOW_MODE_FOLLOW);
  sim_step(&s, t_fresh + 500 * MS + 1);       CHECK_MODE(s.o, FOLLOW_MODE_HOVER, FOLLOW_REASON_HOVER_STALE);
  CHECK(s.o.yaw_rate_dps == 0.0f && s.o.vx_mps == 0.0f && s.o.target_height_m == 0.8f);
  sim_step(&s, t_fresh + 3000 * MS);          CHECK_MODE(s.o, FOLLOW_MODE_HOVER, FOLLOW_REASON_HOVER_STALE);
  sim_step(&s, t_fresh + 3000 * MS + 1);      CHECK_MODE(s.o, FOLLOW_MODE_LAND, FOLLOW_REASON_LAND_STALE);
  CHECK(s.o.target_height_m == 0.0f && s.ctl.stats.land_events == 1);
  /* latched: fresh confirmed packets do not bring it back */
  run_healthy(&s, t_fresh + 3100 * MS, t_fresh + 6 * SEC, 0, 3, 0.3f, 0.5f);
  CHECK_MODE(s.o, FOLLOW_MODE_LAND, FOLLOW_REASON_LAND_LATCHED);
  CHECK(follow_ctl_arm(&s.ctl, stm(&s, t_fresh + 6 * SEC)) == FOLLOW_ARM_ERR_LANDED);
  CHECK(s.ctl.stats.land_events == 1);
  CHECK(follow_ctl_init(&s.ctl, NULL) == 0);  /* operator reset */
  sim_step(&s, t_fresh + 6 * SEC); CHECK(s.o.mode == FOLLOW_MODE_WAIT_WARMUP);
}

/* Pipeline failure: no-target packets every 60 ms carry the age of the last
 * good frame; they must not refresh t_fresh (land 3.0 s after the last frame). */
static void test_no_target_stream(void)
{
  sim_t s;
  uint64_t T = setup_following(&s, 0, 0);
  uint64_t cap = T - 30 * MS, t_hover = 0, t_land = 0, t;

  CHECK(sim_rx(&s, T, 3 * MS, 3, 2, 0.3f, 0.5f, NULL) == FOLLOW_RX_OK);
  for (t = T + MS; t < T + 5 * SEC; t += MS) {
    if ((t - T) % (60 * MS) == 0) {
      uint64_t age_us = (t - 3 * MS) - cap;
      uint8_t age = (uint8_t)((age_us + 19999) / 20000 > 255 ? 255 : (age_us + 19999) / 20000);
      CHECK(sim_rx(&s, t, 3 * MS, 0, age, 0.0f, 0.0f, NULL) == FOLLOW_RX_OK);
    }
    if (t % (10 * MS) == 0) {
      sim_step(&s, t);
      if (!t_hover && s.o.reason == FOLLOW_REASON_HOVER_STALE) t_hover = t;
      if (!t_land && s.o.mode == FOLLOW_MODE_LAND) t_land = t;
      if (t >= T + 60 * MS && t < T + 400 * MS) CHECK(s.o.reason == FOLLOW_REASON_HOVER_NOT_CONFIRMED); /* rule 3 first */
    }
  }
  /* the controller's t_fresh is the ceil-rounded capture time (<= 20 ms early) */
  CHECK(t_hover > cap + 480 * MS && t_hover <= cap + 510 * MS);
  CHECK(t_land > cap + 2980 * MS && t_land <= cap + 3010 * MS);
}

static void test_age255_lands_now(void)
{
  sim_t s;
  uint64_t T = setup_following(&s, 0, 0);
  follow_rx_info_t inf;

  CHECK(sim_rx(&s, T, 3 * MS, 0, 255, 0.0f, 0.0f, &inf) == FOLLOW_RX_OK && inf.saturated);
  sim_step(&s, T);
  CHECK_MODE(s.o, FOLLOW_MODE_LAND, FOLLOW_REASON_LAND_NO_FRAME);
  /* also when the 255 packet is late by rule 0 */
  T = setup_following(&s, 0, 0);
  CHECK(sim_rx(&s, T, 400 * MS, 0, 255, 0.0f, 0.0f, &inf) == FOLLOW_RX_OK && inf.saturated && inf.stale_rule0);
  sim_step(&s, T);
  CHECK(s.o.mode == FOLLOW_MODE_LAND);
}

/* Rule 3 tests bit 0, never the byte. */
static void test_rule3_bits(void)
{
  sim_t s;
  uint64_t T = setup_following(&s, 0, 0);

  CHECK(sim_rx(&s, T, 3 * MS, 2, 2, 0.3f, 0.5f, NULL) == FOLLOW_RX_OK);     /* bit 1 only */
  sim_step(&s, T); CHECK_MODE(s.o, FOLLOW_MODE_HOVER, FOLLOW_REASON_HOVER_NOT_CONFIRMED);
  CHECK(s.o.yaw_rate_dps == 0.0f && s.o.vx_mps == 0.0f);
  CHECK(sim_rx(&s, T + 66 * MS, 3 * MS, 1, 2, 0.3f, 0.5f, NULL) == FOLLOW_RX_OK); /* bit 0 only (hysteresis) */
  sim_step(&s, T + 70 * MS); CHECK(s.o.mode == FOLLOW_MODE_FOLLOW);         /* no stale episode: steer */
  CHECK(sim_rx(&s, T + 132 * MS, 3 * MS, 0, 2, 0.0f, 0.0f, NULL) == FOLLOW_RX_OK);
  sim_step(&s, T + 140 * MS); CHECK(s.o.reason == FOLLOW_REASON_HOVER_NOT_CONFIRMED);
  CHECK(sim_rx(&s, T + 198 * MS, 3 * MS, 3, 2, 0.3f, 0.5f, NULL) == FOLLOW_RX_OK);
  sim_step(&s, T + 200 * MS); CHECK(s.o.mode == FOLLOW_MODE_FOLLOW);        /* rule 3 hover is not stale */
}

/* Rule 4: after a stale hover, 3 consecutive fresh bit0+bit1 packets. */
static void test_rule4(void)
{
  sim_t s;
  uint64_t T = setup_following(&s, 0, 0);
  follow_rx_info_t inf;
  uint8_t bad[28];
  int i;

  CHECK(sim_rx(&s, T, 3 * MS, 3, 2, 0.3f, 0.5f, NULL) == FOLLOW_RX_OK);
  T += 600 * MS;                                   /* silence: stale hover */
  sim_step(&s, T); CHECK(s.o.reason == FOLLOW_REASON_HOVER_STALE);
  /* 3, 3, then bit 0 only (hysteresis p in [0.45, 0.7)) -> restart */
  sim_rx(&s, T + 10 * MS, 3 * MS, 3, 2, 0.3f, 0.5f, &inf); CHECK(inf.counted && inf.reconfirm_count == 1);
  sim_step(&s, T + 10 * MS); CHECK_MODE(s.o, FOLLOW_MODE_HOVER, FOLLOW_REASON_HOVER_RECONFIRM);
  sim_rx(&s, T + 20 * MS, 3 * MS, 3, 2, 0.3f, 0.5f, &inf); CHECK(inf.reconfirm_count == 2);
  sim_rx(&s, T + 30 * MS, 3 * MS, 1, 2, 0.3f, 0.5f, &inf); CHECK(!inf.counted && inf.reconfirm_count == 0);
  sim_step(&s, T + 30 * MS); CHECK(s.o.reason == FOLLOW_REASON_HOVER_RECONFIRM); /* bit 0 set, still no */
  /* age 26 units (0.52 s) never counts; age 25 (0.5 s) does */
  sim_rx(&s, T + 40 * MS, 3 * MS, 3, 25, 0.3f, 0.5f, &inf); CHECK(inf.counted && inf.reconfirm_count == 1);
  sim_rx(&s, T + 50 * MS, 3 * MS, 3, 26, 0.3f, 0.5f, &inf); CHECK(!inf.counted && inf.reconfirm_count == 0);
  /* a packet late by rule 0 restarts the count */
  sim_rx(&s, T + 60 * MS, 3 * MS, 3, 2, 0.3f, 0.5f, &inf); CHECK(inf.reconfirm_count == 1);
  sim_rx(&s, T + 70 * MS, 150 * MS, 3, 2, 0.3f, 0.5f, &inf); CHECK(inf.stale_rule0 && inf.reconfirm_count == 0);
  sim_step(&s, T + 70 * MS); CHECK(s.o.reason == FOLLOW_REASON_HOVER_RULE0);
  /* a rejected packet restarts the count */
  sim_rx(&s, T + 80 * MS, 3 * MS, 3, 2, 0.3f, 0.5f, &inf); CHECK(inf.reconfirm_count == 1);
  build(bad, 99, 0.3f, 0.5f, 3, 2, gms(&s, T + 87 * MS)); bad[1] = 5;
  CHECK(follow_ctl_on_packet(&s.ctl, bad, 28, stm(&s, T + 90 * MS), &inf) == FOLLOW_RX_ERR_VERSION);
  CHECK(s.ctl.reconfirm_count == 0);
  for (i = 0; i < 3; i++) {
    sim_rx(&s, T + (100 + 10 * i) * MS, 3 * MS, 3, 2, 0.3f, 0.5f, &inf);
    sim_step(&s, T + (100 + 10 * i) * MS);
    CHECK(s.o.mode == (i < 2 ? FOLLOW_MODE_HOVER : FOLLOW_MODE_FOLLOW));
  }
  /* once following, bit 0 alone keeps steering (the GAP8 hysteresis) */
  sim_rx(&s, T + 140 * MS, 3 * MS, 1, 2, 0.3f, 0.5f, &inf);
  sim_step(&s, T + 140 * MS); CHECK(s.o.mode == FOLLOW_MODE_FOLLOW);
  /* the count must be consecutive packets, and a stale STEP restarts it */
  T += 1 * SEC;
  sim_step(&s, T); CHECK(s.o.reason == FOLLOW_REASON_HOVER_STALE);
  sim_rx(&s, T + 10 * MS, 3 * MS, 3, 24, 0.3f, 0.5f, &inf); CHECK(inf.reconfirm_count == 1); /* 0.48 s old */
  sim_step(&s, T + 60 * MS); CHECK(s.o.reason == FOLLOW_REASON_HOVER_STALE);  /* 0.53 s: stale again */
  CHECK(s.ctl.reconfirm_count == 0);
}

/* Rule 0: late packets, persistent latency steps, window resets. */
static void test_rule0(void)
{
  sim_t s;
  uint64_t T, t, t_hover = 0, t_land = 0, last_fresh;
  follow_rx_info_t inf;

  /* single late packet: flagged, t_fresh unchanged, no steering on it */
  T = setup_following(&s, 0, 0);
  sim_rx(&s, T, 3 * MS, 3, 2, 0.3f, 0.5f, &inf); CHECK(inf.e_us == 0);
  sim_rx(&s, T + 66 * MS, 103 * MS, 3, 2, 0.9f, 0.5f, &inf);
  CHECK(inf.e_us == 100 * MS && !inf.stale_rule0);          /* e == 0.1 s exactly: fresh */
  sim_rx(&s, T + 132 * MS, 104 * MS, 3, 2, 0.9f, 0.5f, &inf);
  CHECK(inf.e_us == 101 * MS && inf.stale_rule0 && !inf.counted);
  sim_step(&s, T + 132 * MS); CHECK_MODE(s.o, FOLLOW_MODE_HOVER, FOLLOW_REASON_HOVER_RULE0);
  CHECK(s.o.frame_age_us == (132 - 66 + 100 + 40) * MS); /* t_fresh from the e = 0.1 s packet */
  sim_rx(&s, T + 198 * MS, 3 * MS, 3, 2, 0.3f, 0.5f, &inf);
  sim_step(&s, T + 198 * MS); CHECK(s.o.mode == FOLLOW_MODE_FOLLOW); /* no stale step: no rule 4 */

  /* latency step of +80 ms held: absorbed, never hovers */
  T = setup_following(&s, 0, 0);
  for (t = T; t < T + 5 * SEC; t += MS) {
    if ((t - T) % (66 * MS) == 0) { sim_rx(&s, t, 83 * MS, 3, 2, 0.3f, 0.5f, &inf); CHECK(!inf.stale_rule0); }
    if (t % (10 * MS) == 0) { sim_step(&s, t); CHECK(s.o.mode == FOLLOW_MODE_FOLLOW); }
  }
  /* persistent step of +150 ms: every packet stale -> hover at 0.5 s, land at 3.0 s */
  T = setup_following(&s, 0, 0);
  sim_rx(&s, T, 3 * MS, 3, 2, 0.3f, 0.5f, NULL);
  last_fresh = T - 40 * MS;
  for (t = T + MS; t < T + 5 * SEC; t += MS) {
    if ((t - T) % (66 * MS) == 0) { sim_rx(&s, t, 153 * MS, 3, 2, 0.3f, 0.5f, &inf); CHECK(inf.stale_rule0); }
    if (t % (10 * MS) == 0) {
      sim_step(&s, t);
      if (t >= T + 66 * MS) CHECK(s.o.mode != FOLLOW_MODE_FOLLOW);
      if (!t_hover && s.o.reason == FOLLOW_REASON_HOVER_STALE) t_hover = t;
      if (!t_land && s.o.mode == FOLLOW_MODE_LAND) t_land = t;
    }
  }
  CHECK(t_hover > last_fresh + 500 * MS && t_hover <= last_fresh + 510 * MS);
  CHECK(t_land > last_fresh + 3000 * MS && t_land <= last_fresh + 3010 * MS);

  /* GAP8 reboot: frame_id goes backwards -> window reset, warm-up, rule 4 */
  T = setup_following(&s, 0, 0);
  s.fid = 0;
  sim_rx(&s, T, 3 * MS, 3, 2, 0.3f, 0.5f, &inf);
  CHECK(inf.window_reset && inf.warmup && inf.stale_rule0 && s.ctl.need_reconfirm);
  sim_step(&s, T); CHECK(s.o.reason == FOLLOW_REASON_HOVER_RULE0);
  t_hover = t_land = 0;
  for (t = T + MS; t < T + 4 * SEC; t += MS) {
    if ((t - T) % (66 * MS) == 0) sim_rx(&s, t, 3 * MS, 3, 2, 0.3f, 0.5f, &inf);
    if (t % (10 * MS) == 0) {
      sim_step(&s, t);
      if (t < T + 2 * SEC) CHECK(s.o.mode == FOLLOW_MODE_HOVER);
      if (!t_hover && s.o.mode == FOLLOW_MODE_FOLLOW) t_hover = t;
      if (s.o.mode == FOLLOW_MODE_LAND) t_land = t;
    }
  }
  CHECK(t_land == 0);                                     /* warm-up 2 s < land 3 s */
  CHECK(t_hover >= T + 2 * SEC + 132 * MS && t_hover < T + 2 * SEC + 200 * MS); /* 3 fresh packets */

  /* GAP8 clock jumps by > 10 s (same frame_id sequence) -> window reset */
  T = setup_following(&s, 0, 0);
  s.g_off += 10500 * MS;
  sim_rx(&s, T, 3 * MS, 3, 2, 0.3f, 0.5f, &inf); CHECK(inf.window_reset && inf.stale_rule0);
  /* a 9 s jump is not a reset: the packets just look late (fail-safe) */
  T = setup_following(&s, 0, 1000 * SEC);
  s.g_off -= 9 * SEC;
  sim_rx(&s, T, 3 * MS, 3, 2, 0.3f, 0.5f, &inf); CHECK(!inf.window_reset && inf.stale_rule0 && inf.e_us == 9 * SEC);
  /* the window forgets an old minimum after 10 buckets (e = 0), but the latency floor does not:
   * still stale, 150 ms minus the 200 ppm drift allowance above the floor */
  T = setup_following(&s, 0, 0);
  for (t = T; t < T + 12 * SEC; t += 66 * MS) sim_rx(&s, t, 153 * MS, 3, 2, 0.3f, 0.5f, &inf);
  CHECK(inf.e_us == 0 && !inf.window_reset && inf.rise_stale && inf.stale_rule0);
  CHECK(inf.rise_us > 146 * MS && inf.rise_us < 148 * MS);
}

/* Rule 0 latency floor (safety review 7, finding 1): a latency step while the drone waits on
 * the ground must never let the take-off gate arm on late frames, whatever the ground silence
 * before it; airborne the same step still lands after 3.0 s. */
static void test_latency_floor(void)
{
  static const uint64_t sil_ms[] = {0, 8000, 9000, 9500, 9900, 10000, 12000, 30000};
  sim_t s;
  follow_rx_info_t inf;
  follow_config_t c;
  uint64_t T, t, t_hover, t_land, last_fresh;
  unsigned k, follow_steps;
  int gate, armed, last_arm, rise_seen;

  for (gate = 1; gate >= 0; gate--) {
    for (k = 0; k < sizeof sil_ms / sizeof sil_ms[0]; k++) {
      const uint64_t T0 = 3 * SEC, T1 = T0 + sil_ms[k] * MS;
      /* the Python-model gate (0) arms on any newest packet during the first 10 s, while e > 0.1 s
       * (it then hovers and lands): try it only once the window has forgotten the healthy minimum */
      const uint64_t t_try = gate ? T1 : T1 + 10500 * MS;

      follow_ctl_default_config(&c);
      c.arm_require_fresh = (uint8_t)gate;
      sim_init(&s, 0, 0);
      CHECK(follow_ctl_init(&s.ctl, &c) == 0);
      run_healthy(&s, 0, T0, 0, 3, 0.3f, 0.5f);          /* on the ground, warm, 3 ms link */
      armed = 0; follow_steps = 0; last_arm = -1; rise_seen = 0;
      for (t = T1; t < T1 + 40 * SEC; t += MS) {
        if ((t - T1) % (66 * MS) == 0) {
          CHECK(sim_rx(&s, t, 1003 * MS, 3, 2, 0.3f, 0.5f, &inf) == FOLLOW_RX_OK);
          CHECK(inf.stale_rule0);                          /* every packet after the step */
          rise_seen |= inf.rise_stale && inf.e_us <= 100 * MS;
        }
        if (t % (10 * MS) == 0) {
          if (t >= t_try) {
            last_arm = (int)follow_ctl_arm(&s.ctl, stm(&s, t));
            armed |= last_arm == FOLLOW_ARM_OK;
          }
          sim_step(&s, t);
          follow_steps += s.o.mode == FOLLOW_MODE_FOLLOW;
        }
      }
      CHECK(!armed && follow_steps == 0);
      CHECK(last_arm == FOLLOW_ARM_ERR_LATENCY_RISE);
      /* the window alone calls it on time; 1 s above the floor minus <= 16 ms drift allowance */
      CHECK(rise_seen && inf.e_us == 0 && inf.rise_us > 980 * MS && inf.rise_us < 1000 * MS);
      if (armed || follow_steps) printf("  silence %llu ms gate %d: armed %d, %u FOLLOW steps\n",
                                        (unsigned long long)sil_ms[k], gate, armed, follow_steps);
    }
  }

  /* the same +1 s step airborne: hover at 0.5 s, land at 3.0 s after the last fresh frame, latched */
  T = setup_following(&s, 0, 0);
  sim_rx(&s, T, 3 * MS, 3, 2, 0.3f, 0.5f, NULL);
  last_fresh = T - 40 * MS;
  t_hover = t_land = 0;
  for (t = T + MS; t < T + 40 * SEC; t += MS) {
    if ((t - T) % (66 * MS) == 0) sim_rx(&s, t, 1003 * MS, 3, 2, 0.3f, 0.5f, &inf);
    if (t % (10 * MS) == 0) {
      sim_step(&s, t);
      CHECK(s.o.mode != FOLLOW_MODE_FOLLOW || t < T + 66 * MS);
      if (!t_hover && s.o.reason == FOLLOW_REASON_HOVER_STALE) t_hover = t;
      if (!t_land && s.o.mode == FOLLOW_MODE_LAND) t_land = t;
    }
  }
  CHECK(t_hover > last_fresh + 500 * MS && t_hover <= last_fresh + 510 * MS);
  CHECK(t_land > last_fresh + 3000 * MS && t_land <= last_fresh + 3010 * MS);
  CHECK(s.o.mode == FOLLOW_MODE_LAND);

  /* two steps of +80 ms, 11 s apart: the first is absorbed (as HANDOFF allows), the second is
   * 160 ms above the floor: stale at once, although e is only 80 ms */
  T = setup_following(&s, 0, 0);
  for (t = T; t < T + 11 * SEC; t += MS) {
    if ((t - T) % (66 * MS) == 0) { sim_rx(&s, t, 83 * MS, 3, 2, 0.3f, 0.5f, &inf); CHECK(!inf.stale_rule0); }
    if (t % (10 * MS) == 0) { sim_step(&s, t); CHECK(s.o.mode == FOLLOW_MODE_FOLLOW); }
  }
  t_land = 0;
  for (t = T + 11 * SEC; t < T + 16 * SEC; t += MS) {
    if ((t - T) % (66 * MS) == 0) {
      sim_rx(&s, t, 163 * MS, 3, 2, 0.3f, 0.5f, &inf);
      CHECK(inf.e_us <= 81 * MS && inf.rise_stale && inf.stale_rule0);
    }
    if (t % (10 * MS) == 0) {
      sim_step(&s, t);
      if (t > T + 11 * SEC + 66 * MS) CHECK(s.o.mode != FOLLOW_MODE_FOLLOW);
      if (!t_land && s.o.mode == FOLLOW_MODE_LAND) t_land = t;
    }
  }
  CHECK(t_land > T + 11 * SEC + 2900 * MS && t_land < T + 11 * SEC + 3100 * MS);

  /* drift allowance: an STM32 clock 190 ppm fast for 20 min never trips the floor; 400 ppm does
   * (200 ppm net, 0.1 s after ~8.3 min) */
  for (k = 0; k < 2; k++) {
    uint64_t t_trip = 0;
    sim_init(&s, 0, 0);
    s.ppm = k ? 400 : 190;
    for (t = 0; t < 20ull * 60 * SEC; t += 66 * MS) {
      sim_rx(&s, t, 3 * MS, 3, 2, 0.3f, 0.5f, &inf);
      if (t > 3 * SEC && inf.stale_rule0 && !t_trip) t_trip = t;
    }
    if (k == 0) {
      CHECK(t_trip == 0 && inf.rise_us < 5 * MS);
    } else {
      CHECK(t_trip > 480 * SEC && t_trip < 520 * SEC && inf.rise_stale && inf.e_us < 5 * MS);
    }
  }

  /* the floor survives a packet silence longer than the window (warm-up again, then refused),
   * but a GAP8 reboot (frame_id backwards) re-learns it: a link that is slow from the GAP8's
   * boot cannot be told from a healthy one (the L_min bench check, HANDOFF section 3) */
  sim_init(&s, 0, 0);
  run_healthy(&s, 0, 3 * SEC, 0, 3, 0.3f, 0.5f);
  sim_rx(&s, 15 * SEC, 1003 * MS, 3, 2, 0.3f, 0.5f, &inf);
  CHECK(inf.window_reset && !inf.floor_reset && inf.warmup && inf.rise_stale);
  run_healthy(&s, 15 * SEC + 66 * MS, 18 * SEC, 0, 3, 0.3f, 0.5f);   /* healthy again: fine */
  CHECK(follow_ctl_arm(&s.ctl, stm(&s, 18 * SEC)) == FOLLOW_ARM_OK);
  sim_init(&s, 0, 0);
  run_healthy(&s, 0, 3 * SEC, 0, 3, 0.3f, 0.5f);
  s.fid = 0;
  sim_rx(&s, 15 * SEC, 1003 * MS, 3, 2, 0.3f, 0.5f, &inf);
  CHECK(inf.window_reset && inf.floor_reset && inf.warmup);
  for (t = 15 * SEC + 66 * MS; t < 17200 * MS; t += 66 * MS) sim_rx(&s, t, 1003 * MS, 3, 2, 0.3f, 0.5f, &inf);
  CHECK(!inf.stale_rule0);
  /* documented residual: arms on the slower link (the frame age byte still bounds the frame) */
  CHECK(follow_ctl_arm(&s.ctl, stm(&s, 17200 * MS)) == FOLLOW_ARM_OK);

  /* config bound */
  follow_ctl_default_config(&c); CHECK(c.drift_ppm == 200u);
  c.drift_ppm = 10001u; CHECK(follow_ctl_init(&s.ctl, &c) == -1);
}

/* Rule 4 counts distinct frames (safety review 7, finding 3): copies of one packet neither count
 * nor restart the count; frame_id wraps. */
static void test_rule4_duplicates(void)
{
  sim_t s;
  uint64_t T;
  follow_rx_info_t inf;
  uint8_t b[28];
  int i;

  /* frame_ids chosen so the two frames that complete the count are 0xFFFFFFFF and 0 */
  sim_init(&s, 0, 0);
  s.fid = 0xFFFFFFFFu - 48u;
  T = run_healthy(&s, 0, 3 * SEC, 2500 * MS, 3, 0.3f, 0.5f);       /* 46 packets */
  CHECK_MODE(s.o, FOLLOW_MODE_FOLLOW, FOLLOW_REASON_NONE);
  sim_rx(&s, T, 3 * MS, 3, 2, 0.3f, 0.5f, NULL);
  T += 600 * MS;
  sim_step(&s, T); CHECK(s.o.reason == FOLLOW_REASON_HOVER_STALE);
  build(b, s.fid++, 0.3f, 0.5f, 3, 2, gms(&s, T + 7 * MS));
  for (i = 0; i < 3; i++) {                        /* one packet delivered three times in 30 ms */
    CHECK(follow_ctl_on_packet(&s.ctl, b, 28, stm(&s, T + (10 + 10 * i) * MS), &inf) == FOLLOW_RX_OK);
    CHECK(inf.counted == (i == 0) && inf.duplicate == (i > 0) && inf.reconfirm_count == 1);
    sim_step(&s, T + (10 + 10 * i) * MS);
    CHECK_MODE(s.o, FOLLOW_MODE_HOVER, FOLLOW_REASON_HOVER_RECONFIRM);
  }
  CHECK(s.ctl.stats.rx_duplicate == 2);
  /* two new frames (frame_id wrapping through 2^32) complete it */
  CHECK(s.fid == 0xFFFFFFFFu);
  sim_rx(&s, T + 50 * MS, 3 * MS, 3, 2, 0.3f, 0.5f, &inf); CHECK(inf.counted && inf.reconfirm_count == 2 && !inf.window_reset);
  sim_step(&s, T + 50 * MS); CHECK(s.o.reason == FOLLOW_REASON_HOVER_RECONFIRM);
  sim_rx(&s, T + 60 * MS, 3 * MS, 3, 2, 0.3f, 0.5f, &inf); CHECK(inf.counted && inf.reconfirm_count == 3 && !inf.window_reset);
  sim_step(&s, T + 60 * MS); CHECK_MODE(s.o, FOLLOW_MODE_FOLLOW, FOLLOW_REASON_NONE);
  /* a copy of the newest packet while following changes nothing */
  build(b, s.fid - 1u, 0.3f, 0.5f, 3, 2, gms(&s, T + 57 * MS));
  CHECK(follow_ctl_on_packet(&s.ctl, b, 28, stm(&s, T + 70 * MS), &inf) == FOLLOW_RX_OK);
  CHECK(inf.duplicate && !inf.window_reset);
  sim_step(&s, T + 70 * MS); CHECK(s.o.mode == FOLLOW_MODE_FOLLOW);
  /* a replay of an OLDER packet looks like a GAP8 reboot to rule 0 (frame_id backwards): window
   * and floor restart, warm-up, rule 4 again. Fail-safe: nothing counts or steers for 2 s */
  build(b, s.fid - 5u, 0.3f, 0.5f, 3, 2, gms(&s, T + 77 * MS));
  CHECK(follow_ctl_on_packet(&s.ctl, b, 28, stm(&s, T + 80 * MS), &inf) == FOLLOW_RX_OK);
  CHECK(inf.window_reset && inf.floor_reset && inf.warmup && inf.stale_rule0 && !inf.counted);
  sim_step(&s, T + 80 * MS); CHECK_MODE(s.o, FOLLOW_MODE_HOVER, FOLLOW_REASON_HOVER_RULE0);
}

/* A step whose `now` was read just before a packet it follows (safety review 7, finding 2):
 * a small negative age is age 0, not NONE (which would latch LAND). */
static void test_negative_age(void)
{
  sim_t s;
  uint64_t T = setup_following(&s, 0, 0);
  follow_rx_info_t inf;

  sim_rx(&s, T, 3 * MS, 3, 0, 0.3f, 0.5f, &inf);          /* age byte 0: t_fresh = t_rx - e */
  CHECK(inf.e_us == 0);
  sim_step(&s, T - 500);                                  /* 0.5 ms before the packet's t_rx */
  CHECK_MODE(s.o, FOLLOW_MODE_FOLLOW, FOLLOW_REASON_NONE);
  CHECK(s.o.frame_age_us == 0u);
  sim_step(&s, T - 500 * MS);                             /* exactly -hover_us: still age 0 */
  CHECK(s.o.mode == FOLLOW_MODE_FOLLOW && s.o.frame_age_us == 0u);
  sim_step(&s, T + 10 * MS); CHECK(s.o.mode == FOLLOW_MODE_FOLLOW && s.o.frame_age_us == 10 * MS);
  T = setup_following(&s, 0, 0);
  sim_rx(&s, T, 3 * MS, 3, 0, 0.3f, 0.5f, &inf);
  sim_step(&s, T - 501 * MS);                             /* beyond: a wrapped t_fresh, NONE */
  CHECK_MODE(s.o, FOLLOW_MODE_LAND, FOLLOW_REASON_LAND_NO_FRAME);
}

/* Both clocks wrap mid-flight: nothing may change. */
static void test_wrap(void)
{
  sim_t s;
  uint64_t T, t;
  follow_rx_info_t inf;
  const uint64_t stm_off = 4294967296ull - 3200 * MS;            /* STM32 us clock wraps at T = 3.2 s */
  const uint64_t g_off = 4294967296ull * 1000ull - 4000 * MS;    /* GAP8 ms clock wraps at T = 4.0 s */

  T = setup_following(&s, stm_off, g_off);
  for (t = T; t < T + 3 * SEC; t += MS) {
    if ((t - T) % (66 * MS) == 0) {
      CHECK(sim_rx(&s, t, 3 * MS, 3, 2, 0.3f, 0.5f, &inf) == FOLLOW_RX_OK);
      CHECK(inf.e_us == 0 && !inf.stale_rule0 && !inf.window_reset);
    }
    if (t % (10 * MS) == 0) { sim_step(&s, t); CHECK_MODE(s.o, FOLLOW_MODE_FOLLOW, FOLLOW_REASON_NONE); }
  }
  CHECK(stm(&s, T) > stm(&s, T + 3 * SEC));                     /* really wrapped */
  CHECK(gms(&s, T) > gms(&s, T + 3 * SEC));
  /* silence across the wrap still hovers at 0.5 s and lands at 3.0 s */
  sim_rx(&s, t, 3 * MS, 3, 2, 0.3f, 0.5f, &inf);
  sim_step(&s, t + 460 * MS); CHECK(s.o.mode == FOLLOW_MODE_FOLLOW);
  sim_step(&s, t + 470 * MS); CHECK(s.o.reason == FOLLOW_REASON_HOVER_STALE);
  sim_step(&s, t + 2960 * MS); CHECK(s.o.mode == FOLLOW_MODE_HOVER);
  sim_step(&s, t + 2970 * MS); CHECK(s.o.mode == FOLLOW_MODE_LAND);

  /* t_fresh far older than the int32 range must never look fresh */
  sim_init(&s, 0, 0);
  run_healthy(&s, 0, 2200 * MS, 0, 3, 0.3f, 0.5f);
  CHECK(follow_ctl_arm(&s.ctl, stm(&s, 2200 * MS + 40ull * 60 * SEC)) == FOLLOW_ARM_ERR_NO_FRESH_FRAME);
  CHECK(follow_ctl_arm(&s.ctl, stm(&s, 2200 * MS + 20ull * 60 * SEC)) == FOLLOW_ARM_ERR_NO_FRESH_FRAME);
  /* a packet after 40 min of silence restarts the window (warm-up again) */
  sim_rx(&s, 2200 * MS + 40ull * 60 * SEC, 3 * MS, 3, 2, 0.3f, 0.5f, &inf);
  CHECK(inf.window_reset && inf.warmup && inf.stale_rule0);
  /* so does a silence longer than the 10 s window */
  sim_init(&s, 0, 0);
  run_healthy(&s, 0, 2200 * MS, 0, 3, 0.3f, 0.5f);
  sim_rx(&s, 2200 * MS + 10500 * MS, 3 * MS, 3, 2, 0.3f, 0.5f, &inf);
  CHECK(inf.window_reset && inf.warmup);
  /* step-driven: once past land_us, t_fresh is dropped (pre-arm) */
  sim_init(&s, 0, 0);
  run_healthy(&s, 0, 2200 * MS, 0, 3, 0.3f, 0.5f);
  sim_step(&s, 2200 * MS + 3100 * MS);
  CHECK(s.ctl.have_fresh == 0 && s.o.mode == FOLLOW_MODE_WAIT_WARMUP);
}

static void follow_with(sim_t *s, uint64_t T, float x, float size)
{
  sim_rx(s, T, 3 * MS, 3, 2, x, size, NULL);
  sim_step(s, T);
  CHECK(s->o.mode == FOLLOW_MODE_FOLLOW);
}

static int feq(float a, float b) { return fabsf(a - b) < 1e-5f; }

static void test_control_law(void)
{
  sim_t s;
  follow_config_t c;
  uint64_t T = setup_following(&s, 0, 0);

  follow_with(&s, T, 0.0f, 0.625f);   CHECK(s.o.yaw_rate_dps == 0.0f && s.o.vx_mps == 0.0f && s.o.target_height_m == 0.8f);
  follow_with(&s, T += 66 * MS, 0.079f, 0.625f); CHECK(s.o.yaw_rate_dps == 0.0f);   /* deadband */
  follow_with(&s, T += 66 * MS, -0.079f, 0.625f); CHECK(s.o.yaw_rate_dps == 0.0f);
  follow_with(&s, T += 66 * MS, 0.3f, 0.625f);  CHECK(feq(s.o.yaw_rate_dps, -18.0f)); /* right -> clockwise */
  follow_with(&s, T += 66 * MS, -0.3f, 0.625f); CHECK(feq(s.o.yaw_rate_dps, 18.0f));
  follow_with(&s, T += 66 * MS, 0.9f, 0.625f);  CHECK(feq(s.o.yaw_rate_dps, -40.0f)); /* cap */
  follow_with(&s, T += 66 * MS, -1.0f, 0.625f); CHECK(feq(s.o.yaw_rate_dps, 40.0f));
  follow_with(&s, T += 66 * MS, 0.3f, 0.375f);  CHECK(feq(s.o.vx_mps, 0.2f));          /* too small: approach */
  follow_with(&s, T += 66 * MS, 0.3f, 0.0f);    CHECK(feq(s.o.vx_mps, 0.3f));          /* cap */
  follow_with(&s, T += 66 * MS, 0.3f, 1.0f);    CHECK(feq(s.o.vx_mps, -0.3f));         /* too close: back off */
  follow_with(&s, T += 66 * MS, 0.49f, 0.0f);   CHECK(feq(s.o.vx_mps, 0.3f));
  follow_with(&s, T += 66 * MS, 0.5f, 0.0f);    CHECK(s.o.vx_mps == 0.0f);             /* |x| >= 0.5: turn only */
  follow_with(&s, T += 66 * MS, -0.7f, 0.0f);   CHECK(s.o.vx_mps == 0.0f && feq(s.o.yaw_rate_dps, 40.0f));

  follow_ctl_default_config(&c);
  c.yaw_sign = 1.0f;
  sim_init(&s, 0, 0);
  CHECK(follow_ctl_init(&s.ctl, &c) == 0);
  T = run_healthy(&s, 0, 3 * SEC, 2500 * MS, 3, 0.3f, 0.5f);
  follow_with(&s, T, 0.3f, 0.625f); CHECK(feq(s.o.yaw_rate_dps, 18.0f));
}

int main(void)
{
  test_parse();
  test_vendor_layout();
  test_config();
  test_warmup_and_arm();
  test_rule1_rule2_silence();
  test_no_target_stream();
  test_age255_lands_now();
  test_rule3_bits();
  test_rule4();
  test_rule0();
  test_latency_floor();
  test_rule4_duplicates();
  test_negative_age();
  test_wrap();
  test_control_law();
  printf("follow_controller unit tests: %lu checks, %lu failures\n", g_checks, g_fail);
  return g_fail != 0;
}
