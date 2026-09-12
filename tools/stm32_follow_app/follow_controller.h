/*
 * follow_controller.h - portable STM32-side follow controller for the AI-deck
 * (GAP8) person-following packet v6.
 *
 * Dependency-free C99: no malloc, no OS calls, no math library. The caller owns
 * the state (follow_ctl_t) and injects time as a uint32 microsecond clock that
 * may wrap (all time arithmetic is modular; differences are taken as signed
 * 32-bit, valid for spans under 35.8 minutes).
 *
 * Authoritative spec: pytorch_ssd/docs/firmware_integration/HANDOFF.md section 3
 * (packet v6 layout, STM32 rules 0-4) and docs/champion_integration.md on the
 * champion-core8-integration branch. The rules are implemented exactly as the
 * documented "v6" Python rule model in safety_sim_review6.py applies them; the
 * differences are listed in README.md.
 *
 * Usage (single task, or guard both calls with one mutex):
 *   follow_config_t cfg; follow_ctl_default_config(&cfg);
 *   follow_ctl_t ctl;    follow_ctl_init(&ctl, &cfg);
 *   on every CPX app packet:  follow_ctl_on_packet(&ctl, data, len, now_us, NULL);
 *   when the operator asks to take off: follow_ctl_arm(&ctl, now_us) == FOLLOW_ARM_OK
 *   every control period (10 ms): follow_ctl_step(&ctl, now_us, &out);
 */
#ifndef FOLLOW_CONTROLLER_H
#define FOLLOW_CONTROLLER_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* ---- Packet v6 wire format (28 bytes, little-endian, packed) ------------- */
#define FOLLOW_PKT_LEN            28u
#define FOLLOW_PKT_MAGIC          0xA5u
#define FOLLOW_PKT_VERSION        0x06u
#define FOLLOW_PKT_PAYLOAD_LEN    24u   /* bytes after the payload_len field */
#define FOLLOW_PKT_AGE_UNIT_US    20000u
#define FOLLOW_PKT_AGE_SATURATED  255u  /* older than 5.08 s or no frame since GAP8 boot */

#define FOLLOW_PKT_OFF_MAGIC      0u
#define FOLLOW_PKT_OFF_VERSION    1u
#define FOLLOW_PKT_OFF_PAYLOAD    2u
#define FOLLOW_PKT_OFF_FRAME_ID   4u
#define FOLLOW_PKT_OFF_X          8u
#define FOLLOW_PKT_OFF_SIZE       12u
#define FOLLOW_PKT_OFF_TRACKING   16u
#define FOLLOW_PKT_OFF_X_BIN      17u
#define FOLLOW_PKT_OFF_SIZE_BKT   18u
#define FOLLOW_PKT_OFF_AGE        19u
#define FOLLOW_PKT_OFF_VIS_RAW    20u
#define FOLLOW_PKT_OFF_GAP8_TX_MS 24u

/* Byte 16: bit flags. Test bits; never compare the byte with 1. */
#define FOLLOW_TRK_CONFIRMED      0x01u /* bit 0: confirmed target (rule 3) */
#define FOLLOW_TRK_FRAME_VISIBLE  0x02u /* bit 1: this frame's p >= 0.7 (rule 4) */
#define FOLLOW_TRK_RESERVED_MASK  0xFCu /* bits 2..7: sent as 0 */

/* Rule 0 window: a ring of this many 1-bucket minima (10 x 1 s by default). */
#define FOLLOW_R0_BUCKETS         10u

/* ---- Types ---------------------------------------------------------------- */
typedef enum {
  FOLLOW_MODE_WAIT_WARMUP = 0, /* not armed: stay on the ground, motors off */
  FOLLOW_MODE_HOVER       = 1, /* hold position at target_height_m, zero yaw rate */
  FOLLOW_MODE_FOLLOW      = 2, /* apply yaw_rate_dps and vx_mps at target_height_m */
  FOLLOW_MODE_LAND        = 3  /* latched: land and stop; only follow_ctl_init clears it */
} follow_mode_t;

typedef enum {
  FOLLOW_REASON_NONE = 0,          /* FOLLOW */
  FOLLOW_REASON_NOT_ARMED,         /* WAIT_WARMUP */
  FOLLOW_REASON_LAND_LATCHED,      /* LAND on an earlier step */
  FOLLOW_REASON_LAND_STALE,        /* rule 1: newest valid frame older than land_us */
  FOLLOW_REASON_LAND_NO_FRAME,     /* rule 1: t_fresh = NONE (age 255, or never set) */
  FOLLOW_REASON_HOVER_STALE,       /* rule 2: newest valid frame older than hover_us */
  FOLLOW_REASON_HOVER_NOT_CONFIRMED, /* rule 3: newest packet has bit 0 clear */
  FOLLOW_REASON_HOVER_RULE0,       /* rule 0: newest packet late (e > 0.1 s, or the latency floor
                                      rose > 0.1 s) or warm-up */
  FOLLOW_REASON_HOVER_RECONFIRM    /* rule 4: waiting for 3 fresh bit0+bit1 packets */
} follow_reason_t;

typedef enum {
  FOLLOW_RX_OK = 0,
  FOLLOW_RX_ERR_NULL,          /* NULL controller or data pointer */
  FOLLOW_RX_ERR_LEN,           /* dataLength != 28 */
  FOLLOW_RX_ERR_MAGIC,         /* byte 0 != 0xA5 */
  FOLLOW_RX_ERR_VERSION,       /* byte 1 != 6 */
  FOLLOW_RX_ERR_PAYLOAD_LEN,   /* bytes 2..3 != 24 */
  FOLLOW_RX_ERR_RESERVED_BITS, /* tracking bits 2..7 set (unknown protocol) */
  FOLLOW_RX_ERR_BAD_VALUE      /* bit 0 set but x_center / size_center not finite or out of range */
} follow_rx_status_t;

typedef enum {
  FOLLOW_ARM_OK = 0,            /* armed (or already armed) */
  FOLLOW_ARM_ERR_CONFIG,        /* follow_ctl_init rejected the config */
  FOLLOW_ARM_ERR_LANDED,        /* LAND is latched: re-init needed (operator action) */
  FOLLOW_ARM_ERR_WARMUP,        /* rule 0 window has not spanned warmup_us of packets */
  FOLLOW_ARM_ERR_NO_FRESH_FRAME,/* no valid frame newer than hover_us */
  FOLLOW_ARM_ERR_STALE_PACKET,  /* newest packet stale by rule 0 */
  FOLLOW_ARM_ERR_LATENCY_RISE   /* rule 0 latency floor: the newest packet is > 0.1 s later than the
                                   fastest delivery since the floor reset, although the 10 s window
                                   calls it on time (the link got slower and stayed slower) */
} follow_arm_status_t;

typedef struct {
  /* Safety timing (microseconds). Defaults = HANDOFF.md section 3. */
  uint32_t hover_us;       /* rule 2: 500000 */
  uint32_t land_us;        /* rule 1: 3000000 */
  uint32_t e_stale_us;     /* rule 0 excess-latency limit: 100000 */
  uint32_t warmup_us;      /* rule 0 warm-up before arming: 2000000 */
  uint32_t bucket_us;      /* rule 0 bucket length: 1000000 (window = 10 buckets) */
  uint32_t jump_us;        /* rule 0 window reset when s jumps more than this: 10000000 */
  uint32_t drift_ppm;      /* rule 0 latency floor: clock-drift allowance, ppm of the time since the
                              floor sample: 200 (HANDOFF: crystal drift <= ~200 ppm) */
  uint8_t  confirm_packets;/* rule 4: 3 */
  uint8_t  arm_require_fresh; /* take-off gate. 1 (default): warm-up done AND a valid frame
                                 <= hover_us old AND the newest packet not late by rule 0.
                                 0: warm-up done and the newest packet not age 255 (the Python
                                 rule model's take-off; the drone may then hover or land at once) */

  /* Control law (matches tools/crazysim_macos/follow_person.py defaults). */
  float yaw_sign;          /* +1 or -1, see README "Yaw sign convention"; default -1 */
  float k_yaw_dps;         /* deg/s per unit x_center: 60 */
  float yaw_deadband;      /* |x| below this -> yaw rate 0: 0.08 */
  float yaw_max_dps;       /* |yaw rate| cap: 40 */
  float k_fwd_mps;         /* m/s per unit size error: 0.8 */
  float target_size;       /* size_center to hold: 0.625 */
  float approach_max_abs_x;/* forward speed only when |x| < this: 0.5 */
  float v_max_mps;         /* |vx| cap: 0.3 */
  float height_m;          /* hold height: 0.8 */
} follow_config_t;

/* Decoded packet fields (host byte order). */
typedef struct {
  uint32_t frame_id;
  float    x_center;
  float    size_center;
  uint8_t  tracking;
  uint8_t  x_bin;
  uint8_t  size_bucket;
  uint8_t  frame_age_20ms;
  int32_t  vis_raw;
  uint32_t gap8_tx_ms;
} follow_packet_fields_t;

/* Optional per-packet diagnostics from follow_ctl_on_packet. */
typedef struct {
  uint32_t e_us;          /* rule 0 excess latency (0 if rejected) */
  uint8_t  stale_rule0;   /* e > e_stale_us, or warm-up: did not refresh t_fresh, never steers */
  uint8_t  warmup;        /* stale because the window has not spanned warmup_us yet */
  uint8_t  window_reset;  /* frame_id went backwards, s jumped, or long silence */
  uint8_t  floor_reset;   /* the latency floor was re-learned too (frame_id backwards, s jump,
                             arrival time backwards); not on a silence reset */
  uint32_t rise_us;       /* rule 0: s minus the latency floor (+ drift allowance), >= 0; ~e when
                             the link is steady */
  uint8_t  rise_stale;    /* rise_us > e_stale_us: stale (included in stale_rule0) */
  uint8_t  duplicate;     /* would count for rule 4 but frame_id is not newer than the last counted
                             packet's: neither counts nor restarts the count */
  uint8_t  saturated;     /* frame_age_20ms == 255: t_fresh = NONE */
  uint8_t  counted;       /* counted toward the rule 4 re-confirmation */
  uint8_t  reconfirm_count;
} follow_rx_info_t;

typedef struct {
  follow_mode_t   mode;
  follow_reason_t reason;
  float yaw_rate_dps;     /* firmware convention: positive = counter-clockwise seen from above */
  float vx_mps;           /* body frame, positive = forward */
  float target_height_m;  /* height_m in HOVER/FOLLOW, 0 in WAIT_WARMUP/LAND */
  uint32_t frame_age_us;  /* now - t_fresh, UINT32_MAX when NONE */
} follow_output_t;

typedef struct {
  uint8_t  have_anchor, have_window, have_prev, warm_done, head, rise_stale;
  uint32_t anchor_s, prev_s, prev_fid, start_us, last_rx_us, bucket_start_us;
  uint8_t  valid[FOLLOW_R0_BUCKETS];
  int32_t  bmin[FOLLOW_R0_BUCKETS]; /* per-bucket minimum of s - anchor (us) */
  int32_t  floor_rel;               /* latency floor: lowest s - anchor since the floor reset (us) */
  uint32_t floor_t_us;              /* when floor_rel was set (the drift allowance runs from here) */
} follow_rule0_t;

typedef struct {
  uint32_t rx_ok, rx_rejected, rx_stale_rule0, rx_rise_stale, rx_duplicate, rx_saturated, window_resets,
           land_events;
} follow_stats_t;

typedef struct {
  follow_config_t cfg;
  follow_rule0_t  r0;
  uint8_t  cfg_ok;
  uint32_t t_fresh_us;
  uint8_t  have_fresh;      /* 0 = t_fresh NONE (infinitely old) */
  uint8_t  saturated;       /* t_fresh cleared by an age-255 packet */
  uint8_t  armed, landed;
  uint8_t  need_reconfirm;  /* rule 4 */
  uint8_t  reconfirm_count;
  uint8_t  have_last_counted; /* rule 4: frame_id of the last counted packet is valid */
  uint32_t last_counted_fid;
  uint8_t  have_newest, newest_stale_rule0;
  follow_packet_fields_t newest;
  follow_stats_t stats;
} follow_ctl_t;

/* ---- API ------------------------------------------------------------------ */
void follow_ctl_default_config(follow_config_t *cfg);

/* Returns 0 on success, -1 on an invalid config (the controller then stays
 * unarmed forever: every step returns WAIT_WARMUP). Also the operator reset
 * after a latched LAND. */
int follow_ctl_init(follow_ctl_t *ctl, const follow_config_t *cfg);

/* Validates and decodes a raw packet (no state change). */
follow_rx_status_t follow_ctl_parse(const uint8_t *data, size_t len, follow_packet_fields_t *out);

/* Feed one CPX app packet received at t_rx_us (STM32 clock). Rejected packets
 * change nothing except restarting the rule 4 count. info may be NULL. */
follow_rx_status_t follow_ctl_on_packet(follow_ctl_t *ctl, const uint8_t *data, size_t len,
                                        uint32_t t_rx_us, follow_rx_info_t *info);

/* Take-off gate (rule 0 warm-up). Only after FOLLOW_ARM_OK may the app take off. */
follow_arm_status_t follow_ctl_arm(follow_ctl_t *ctl, uint32_t now_us);

/* One control step (call every 10 ms). out must not be NULL. */
void follow_ctl_step(follow_ctl_t *ctl, uint32_t now_us, follow_output_t *out);

const char *follow_mode_name(follow_mode_t mode);
const char *follow_reason_name(follow_reason_t reason);
const char *follow_rx_status_name(follow_rx_status_t status);

#ifdef __cplusplus
}
#endif

#endif /* FOLLOW_CONTROLLER_H */
