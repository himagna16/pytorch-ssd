/*
 * follow_controller.c - see follow_controller.h and README.md.
 *
 * Integer microsecond timing throughout (floats only in the control law).
 * Rule numbering follows HANDOFF.md section 3.
 */
#include "follow_controller.h"

#include <string.h>

/* Rule 0 samples are kept relative to an anchor; re-anchor (window reset) if
 * s drifts this far from it, far inside the int32 range. Unreachable in
 * practice (drift is ~0.7 s/hour at 200 ppm; jumps > 10 s already reset). */
#define R0_REBASE_US 600000000L

static uint32_t rd_u16(const uint8_t *b)
{
  return (uint32_t)b[0] | ((uint32_t)b[1] << 8);
}

static uint32_t rd_u32(const uint8_t *b)
{
  return (uint32_t)b[0] | ((uint32_t)b[1] << 8) | ((uint32_t)b[2] << 16) | ((uint32_t)b[3] << 24);
}

static float rd_f32(const uint8_t *b)
{
  const uint32_t u = rd_u32(b);
  float f;

  memcpy(&f, &u, sizeof f); /* IEEE-754 binary32 on both ends */
  return f;
}

static float absf(float v)
{
  return (v < 0.0f) ? -v : v;
}

static float clampf(float v, float lim)
{
  if (v > lim) {
    return lim;
  }
  if (v < -lim) {
    return -lim;
  }
  return v;
}

/* NaN-safe range test: false for NaN and +-inf outside [lo, hi]. */
static int in_range(float v, float lo, float hi)
{
  return (v >= lo) && (v <= hi);
}

void follow_ctl_default_config(follow_config_t *cfg)
{
  if (cfg == NULL) {
    return;
  }
  memset(cfg, 0, sizeof *cfg);
  cfg->hover_us = 500000u;
  cfg->land_us = 3000000u;
  cfg->e_stale_us = 100000u;
  cfg->warmup_us = 2000000u;
  cfg->bucket_us = 1000000u;
  cfg->jump_us = 10000000u;
  cfg->drift_ppm = 200u;
  cfg->confirm_packets = 3u;
  cfg->arm_require_fresh = 1u;
  cfg->yaw_sign = -1.0f;
  cfg->k_yaw_dps = 60.0f;
  cfg->yaw_deadband = 0.08f;
  cfg->yaw_max_dps = 40.0f;
  cfg->k_fwd_mps = 0.8f;
  cfg->target_size = 0.625f;
  cfg->approach_max_abs_x = 0.5f;
  cfg->v_max_mps = 0.3f;
  cfg->height_m = 0.8f;
}

static int config_ok(const follow_config_t *c)
{
  const uint32_t sat_us = (FOLLOW_PKT_AGE_SATURATED - 1u) * FOLLOW_PKT_AGE_UNIT_US; /* 5.08 s */

  if (!(c->yaw_sign == 1.0f || c->yaw_sign == -1.0f)) {
    return 0;
  }
  if (c->hover_us == 0u || c->land_us <= c->hover_us) {
    return 0;
  }
  /* Same margin as the GAP8's compile-time #error: the age byte must not
   * saturate within 1 s of the land threshold. */
  if (c->land_us > sat_us - 1000000u) {
    return 0;
  }
  if (c->e_stale_us == 0u || c->e_stale_us >= c->hover_us) {
    return 0;
  }
  if (c->bucket_us == 0u || c->bucket_us > 6000000u) {
    return 0;
  }
  if (c->warmup_us == 0u || c->warmup_us > c->bucket_us * FOLLOW_R0_BUCKETS) {
    return 0;
  }
  if (c->jump_us == 0u || c->jump_us > 600000000u) {
    return 0;
  }
  if (c->drift_ppm > 10000u) {
    return 0;
  }
  if (c->confirm_packets == 0u || c->arm_require_fresh > 1u) {
    return 0;
  }
  if (!in_range(c->k_yaw_dps, 0.0f, 1000.0f) || !in_range(c->yaw_deadband, 0.0f, 1.0f) ||
      !in_range(c->yaw_max_dps, 0.0f, 180.0f) || !in_range(c->k_fwd_mps, 0.0f, 10.0f) ||
      !in_range(c->target_size, 0.0f, 1.0f) || !in_range(c->approach_max_abs_x, 0.0f, 1.0f) ||
      !in_range(c->v_max_mps, 0.0f, 2.0f) || !in_range(c->height_m, 0.1f, 3.0f)) {
    return 0;
  }
  return 1;
}

int follow_ctl_init(follow_ctl_t *ctl, const follow_config_t *cfg)
{
  if (ctl == NULL) {
    return -1;
  }
  memset(ctl, 0, sizeof *ctl);
  if (cfg == NULL) {
    follow_ctl_default_config(&ctl->cfg);
  } else {
    ctl->cfg = *cfg;
  }
  ctl->cfg_ok = (uint8_t)config_ok(&ctl->cfg);
  /* Rule 4 applies from boot: "before the first packet since boot" counts as
   * a stale-hover step. */
  ctl->need_reconfirm = 1u;
  return ctl->cfg_ok ? 0 : -1;
}

follow_rx_status_t follow_ctl_parse(const uint8_t *data, size_t len, follow_packet_fields_t *out)
{
  follow_packet_fields_t f;

  if (data == NULL || out == NULL) {
    return FOLLOW_RX_ERR_NULL;
  }
  if (len != FOLLOW_PKT_LEN) {
    return FOLLOW_RX_ERR_LEN;
  }
  if (data[FOLLOW_PKT_OFF_MAGIC] != FOLLOW_PKT_MAGIC) {
    return FOLLOW_RX_ERR_MAGIC;
  }
  if (data[FOLLOW_PKT_OFF_VERSION] != FOLLOW_PKT_VERSION) {
    return FOLLOW_RX_ERR_VERSION;
  }
  if (rd_u16(data + FOLLOW_PKT_OFF_PAYLOAD) != FOLLOW_PKT_PAYLOAD_LEN) {
    return FOLLOW_RX_ERR_PAYLOAD_LEN;
  }
  if ((data[FOLLOW_PKT_OFF_TRACKING] & FOLLOW_TRK_RESERVED_MASK) != 0u) {
    return FOLLOW_RX_ERR_RESERVED_BITS;
  }
  f.frame_id = rd_u32(data + FOLLOW_PKT_OFF_FRAME_ID);
  f.x_center = rd_f32(data + FOLLOW_PKT_OFF_X);
  f.size_center = rd_f32(data + FOLLOW_PKT_OFF_SIZE);
  f.tracking = data[FOLLOW_PKT_OFF_TRACKING];
  f.x_bin = data[FOLLOW_PKT_OFF_X_BIN];
  f.size_bucket = data[FOLLOW_PKT_OFF_SIZE_BKT];
  f.frame_age_20ms = data[FOLLOW_PKT_OFF_AGE];
  f.vis_raw = (int32_t)rd_u32(data + FOLLOW_PKT_OFF_VIS_RAW);
  f.gap8_tx_ms = rd_u32(data + FOLLOW_PKT_OFF_GAP8_TX_MS);
  /* x/size are only used when bit 0 is set; then they must be sane. */
  if ((f.tracking & FOLLOW_TRK_CONFIRMED) != 0u &&
      (!in_range(f.x_center, -1.0f, 1.0f) || !in_range(f.size_center, 0.0f, 1.0f))) {
    return FOLLOW_RX_ERR_BAD_VALUE;
  }
  *out = f;
  return FOLLOW_RX_OK;
}

/* ---- Rule 0 ---------------------------------------------------------------- */

/* The latency floor is folded forward (its drift allowance added to it) once
 * its sample is this old, so the allowance never needs an elapsed time near the
 * uint32 wrap. */
#define R0_FLOOR_FOLD_US 60000000u

/* ppm * elapsed, in us (elapsed < 2^32 us, ppm <= 10000: fits in 64 bits). */
static uint32_t r0_allowance(uint32_t elapsed_us, uint32_t ppm)
{
  return (uint32_t)(((uint64_t)elapsed_us * ppm) / 1000000u);
}

/* Returns the excess latency e (us, >= 0); fills the rule-0 fields of inf.
 *
 * Two minima of s = t_rx - gap8_tx:
 *   off   = minimum over the 10 s window (HANDOFF rule 0): e = s - off.
 *   floor = lowest s since the floor was last reset, allowed to rise by
 *           drift_ppm of the time since it was set (crystal drift).
 * A packet is stale when e > e_stale_us (a late packet), during the warm-up,
 * or when rise = s - floor > e_stale_us: it is more than 0.1 s later than the
 * fastest delivery since the floor reset, even if the window has forgotten that
 * delivery (a latency step held > 10 s, e.g. while the drone waits on the
 * ground, or two steps of <= 0.1 s each). Without the floor such a step is
 * absorbed after 10 s and the take-off gate would arm on late frames.
 *
 * Resets. frame_id backwards, s jumping by more than jump_us, arrival time
 * going backwards, or s drifting R0_REBASE_US from the anchor: the clocks
 * changed (GAP8 reboot); window AND floor restart. A packet silence longer
 * than the window: only the window restarts (warm-up again); the floor is
 * kept, so a link that came back slower is still caught. */
static uint32_t r0_sample(follow_ctl_t *c, uint32_t t_rx, uint32_t gtx_ms, uint32_t fid, follow_rx_info_t *inf)
{
  follow_rule0_t *r = &c->r0;
  const follow_config_t *cfg = &c->cfg;
  const uint32_t window_us = cfg->bucket_us * FOLLOW_R0_BUCKETS;
  /* s = t_rx - gap8_tx, in us. gap8_tx_ms * 1000 mod 2^32 is continuous across
   * the GAP8 ms wrap (2^32 * 1000 = 0 mod 2^32), so only differences matter. */
  const uint32_t s = t_rx - gtx_ms * 1000u;
  int32_t s_rel;
  int32_t off;
  int32_t rise;
  unsigned i;
  int full = 0;
  int win = 0;

  if (r->have_prev) {
    const int32_t dfid = (int32_t)(fid - r->prev_fid);
    const int32_t ds = (int32_t)(s - r->prev_s);
    const int32_t gap = (int32_t)(t_rx - r->last_rx_us);

    /* GAP8 reboot: frame_id backwards, or s jumps by > 10 s. Also (stricter than
     * the Python model, see README): arrival time going backwards (or a silence
     * past the 35.8 min int32 range), or a silence longer than the window. */
    if (dfid < 0 || ds > (int32_t)cfg->jump_us || ds < -(int32_t)cfg->jump_us || gap < 0) {
      full = 1;
    } else if (gap > (int32_t)window_us) {
      win = 1;
    }
  }
  if (!full && r->have_anchor) {
    s_rel = (int32_t)(s - r->anchor_s);
    if (s_rel > R0_REBASE_US || s_rel < -R0_REBASE_US) {
      full = 1;
    }
  }
  if (full) {
    memset(r, 0, sizeof *r);
    inf->window_reset = 1u;
    inf->floor_reset = 1u;
    c->stats.window_resets++;
  } else if (win) {
    r->have_window = 0u;
    inf->window_reset = 1u;
    c->stats.window_resets++;
  }
  r->have_prev = 1u;
  r->prev_s = s;
  r->prev_fid = fid;
  r->last_rx_us = t_rx;
  if (!r->have_anchor) {
    r->have_anchor = 1u;
    r->anchor_s = s;
    r->floor_rel = 0;
    r->floor_t_us = t_rx;
  }
  s_rel = (int32_t)(s - r->anchor_s);
  if (!r->have_window) {
    memset(r->valid, 0, sizeof r->valid);
    r->have_window = 1u;
    r->start_us = t_rx;
    r->warm_done = 0u;
    r->head = 0u;
    r->bucket_start_us = t_rx - (t_rx % cfg->bucket_us); /* buckets on the caller's 1 s grid */
  }

  /* Advance the ring to the bucket containing t_rx (wrap-safe: relative). */
  {
    const uint32_t d = t_rx - r->bucket_start_us;

    if (d >= cfg->bucket_us) {
      const uint32_t k = d / cfg->bucket_us;

      if (k >= FOLLOW_R0_BUCKETS) {
        memset(r->valid, 0, sizeof r->valid);
      } else {
        for (i = 0u; i < k; i++) {
          r->head = (uint8_t)((r->head + 1u) % FOLLOW_R0_BUCKETS);
          r->valid[r->head] = 0u;
        }
      }
      r->bucket_start_us += k * cfg->bucket_us;
    }
  }
  if (!r->valid[r->head] || s_rel < r->bmin[r->head]) {
    r->bmin[r->head] = s_rel;
    r->valid[r->head] = 1u;
  }
  off = s_rel;
  for (i = 0u; i < FOLLOW_R0_BUCKETS; i++) {
    if (r->valid[i] && r->bmin[i] < off) {
      off = r->bmin[i];
    }
  }
  if (!r->warm_done && (int32_t)(t_rx - r->start_us) >= (int32_t)cfg->warmup_us) {
    r->warm_done = 1u;
  }

  /* Latency floor. The elapsed time is unsigned: floor_t_us is at most one fold
   * period plus one silence (< 35.8 min, else a full reset) before t_rx. */
  {
    const uint32_t el = t_rx - r->floor_t_us;
    int32_t feff = r->floor_rel + (int32_t)r0_allowance(el, cfg->drift_ppm);

    if (s_rel <= feff) {
      r->floor_rel = s_rel;
      r->floor_t_us = t_rx;
      feff = s_rel;
    } else if (el > R0_FLOOR_FOLD_US) {
      r->floor_rel = feff;
      r->floor_t_us = t_rx;
    }
    rise = s_rel - feff;
    if (rise < 0) {
      rise = 0;
    }
  }
  inf->rise_us = (uint32_t)rise;
  inf->rise_stale = (uint8_t)(inf->rise_us > cfg->e_stale_us);
  inf->warmup = (uint8_t)!r->warm_done;
  inf->e_us = (uint32_t)(s_rel - off); /* >= 0: the current sample is in the window */
  /* stale only through the floor (the window alone would call it fresh): the take-off gate's
   * FOLLOW_ARM_ERR_LATENCY_RISE */
  r->rise_stale = (uint8_t)(inf->rise_stale && inf->e_us <= cfg->e_stale_us);
  inf->stale_rule0 = (uint8_t)(inf->e_us > cfg->e_stale_us || !r->warm_done || inf->rise_stale);
  return inf->e_us;
}

follow_rx_status_t follow_ctl_on_packet(follow_ctl_t *ctl, const uint8_t *data, size_t len,
                                        uint32_t t_rx_us, follow_rx_info_t *info)
{
  follow_rx_info_t local;
  follow_rx_info_t *inf = (info != NULL) ? info : &local;
  follow_packet_fields_t f;
  follow_rx_status_t st;
  uint32_t e;
  int counted;

  memset(inf, 0, sizeof *inf);
  if (ctl == NULL) {
    return FOLLOW_RX_ERR_NULL;
  }
  st = follow_ctl_parse(data, len, &f);
  if (st != FOLLOW_RX_OK) {
    /* "Any other packet restarts the count" (rule 4). Nothing else changes. */
    ctl->reconfirm_count = 0u;
    ctl->stats.rx_rejected++;
    return st;
  }
  ctl->stats.rx_ok++;

  e = r0_sample(ctl, t_rx_us, f.gap8_tx_ms, f.frame_id, inf);
  if (inf->window_reset) {
    ctl->need_reconfirm = 1u;
    ctl->reconfirm_count = 0u;
  }
  if (inf->floor_reset) {
    ctl->have_last_counted = 0u; /* frame_id sequence restarted */
  }
  if (inf->stale_rule0) {
    ctl->stats.rx_stale_rule0++;
  }
  if (inf->rise_stale) {
    ctl->stats.rx_rise_stale++;
  }

  if (f.frame_age_20ms >= FOLLOW_PKT_AGE_SATURATED) {
    /* Acted on whatever e is: t_fresh = NONE -> land now if airborne. */
    ctl->have_fresh = 0u;
    ctl->saturated = 1u;
    inf->saturated = 1u;
    ctl->stats.rx_saturated++;
  } else if (!inf->stale_rule0) {
    ctl->t_fresh_us = t_rx_us - e - (uint32_t)f.frame_age_20ms * FOLLOW_PKT_AGE_UNIT_US;
    ctl->have_fresh = 1u;
    ctl->saturated = 0u;
  }
  ctl->newest = f;
  ctl->have_newest = 1u;
  ctl->newest_stale_rule0 = inf->stale_rule0;

  /* Rule 4 count: bit 0 AND bit 1, age <= hover_us, fresh by rule 0, and a
   * frame_id newer than the last counted packet's: three copies of one packet
   * (link retransmit or replay) are one frame, not three. A duplicate neither
   * counts nor restarts the count. */
  counted = ((f.tracking & (FOLLOW_TRK_CONFIRMED | FOLLOW_TRK_FRAME_VISIBLE)) ==
             (FOLLOW_TRK_CONFIRMED | FOLLOW_TRK_FRAME_VISIBLE)) &&
            f.frame_age_20ms < FOLLOW_PKT_AGE_SATURATED &&
            (uint32_t)f.frame_age_20ms * FOLLOW_PKT_AGE_UNIT_US <= ctl->cfg.hover_us &&
            !inf->stale_rule0;
  if (counted && ctl->have_last_counted && (int32_t)(f.frame_id - ctl->last_counted_fid) <= 0) {
    counted = 0;
    inf->duplicate = 1u;
    ctl->stats.rx_duplicate++;
  } else if (counted) {
    if (ctl->reconfirm_count < 255u) {
      ctl->reconfirm_count++;
    }
    ctl->last_counted_fid = f.frame_id;
    ctl->have_last_counted = 1u;
  } else {
    ctl->reconfirm_count = 0u;
  }
  inf->counted = (uint8_t)counted;
  inf->reconfirm_count = ctl->reconfirm_count;
  return FOLLOW_RX_OK;
}

/* Age of t_fresh at now. Returns 0 for NONE. t_fresh <= t_rx always, so a
 * negative age means the caller read `now` before a packet it processed first
 * (e.g. a task preempted between reading the clock and taking the mutex): up to
 * hover_us it counts as age 0. A larger negative age can only be a wrapped
 * (> 35.8 min old) t_fresh: treated as NONE. */
static int fresh_age(follow_ctl_t *c, uint32_t now_us, uint32_t *age)
{
  int32_t a;

  if (!c->have_fresh) {
    return 0;
  }
  a = (int32_t)(now_us - c->t_fresh_us);
  if (a < 0) {
    if (a >= -(int32_t)c->cfg.hover_us) {
      *age = 0u;
      return 1;
    }
    c->have_fresh = 0u;
    return 0;
  }
  *age = (uint32_t)a;
  return 1;
}

follow_arm_status_t follow_ctl_arm(follow_ctl_t *ctl, uint32_t now_us)
{
  uint32_t age = 0u;

  if (ctl == NULL || !ctl->cfg_ok) {
    return FOLLOW_ARM_ERR_CONFIG;
  }
  if (ctl->landed) {
    return FOLLOW_ARM_ERR_LANDED;
  }
  if (ctl->armed) {
    return FOLLOW_ARM_OK;
  }
  if (!ctl->r0.have_window || !ctl->r0.warm_done) {
    return FOLLOW_ARM_ERR_WARMUP;
  }
  if (ctl->r0.rise_stale) {
    return FOLLOW_ARM_ERR_LATENCY_RISE; /* both take-off gates: never arm on a slower link */
  }
  if (ctl->cfg.arm_require_fresh) {
    if (!fresh_age(ctl, now_us, &age) || age > ctl->cfg.hover_us) {
      return FOLLOW_ARM_ERR_NO_FRESH_FRAME;
    }
    if (ctl->newest_stale_rule0) {
      return FOLLOW_ARM_ERR_STALE_PACKET;
    }
  } else if (ctl->saturated) {
    return FOLLOW_ARM_ERR_NO_FRESH_FRAME; /* never arm on an age-255 packet */
  }
  ctl->armed = 1u;
  return FOLLOW_ARM_OK;
}

void follow_ctl_step(follow_ctl_t *ctl, uint32_t now_us, follow_output_t *out)
{
  uint32_t age = 0u;
  int have;
  int stale;
  const follow_config_t *cfg;

  if (out == NULL) {
    return;
  }
  memset(out, 0, sizeof *out);
  out->mode = FOLLOW_MODE_WAIT_WARMUP;
  out->reason = FOLLOW_REASON_NOT_ARMED;
  out->frame_age_us = 0xFFFFFFFFu;
  if (ctl == NULL) {
    return;
  }
  cfg = &ctl->cfg;
  have = fresh_age(ctl, now_us, &age);
  if (have) {
    out->frame_age_us = age;
  }
  stale = !have || age > cfg->hover_us;

  if (!ctl->armed) {
    /* on the ground: WAIT_WARMUP, zero outputs */
  } else if (ctl->landed) {
    out->mode = FOLLOW_MODE_LAND;
    out->reason = FOLLOW_REASON_LAND_LATCHED;
  } else if (!have || age > cfg->land_us) {                      /* rule 1 */
    ctl->landed = 1u;
    ctl->stats.land_events++;
    out->mode = FOLLOW_MODE_LAND;
    out->reason = have ? FOLLOW_REASON_LAND_STALE : FOLLOW_REASON_LAND_NO_FRAME;
  } else if (stale) {                                             /* rule 2 */
    out->mode = FOLLOW_MODE_HOVER;
    out->reason = FOLLOW_REASON_HOVER_STALE;
  } else if (!ctl->have_newest || (ctl->newest.tracking & FOLLOW_TRK_CONFIRMED) == 0u) { /* rule 3 */
    out->mode = FOLLOW_MODE_HOVER;
    out->reason = FOLLOW_REASON_HOVER_NOT_CONFIRMED;
  } else if (ctl->newest_stale_rule0) {                           /* rule 0: never steer */
    out->mode = FOLLOW_MODE_HOVER;
    out->reason = FOLLOW_REASON_HOVER_RULE0;
  } else if (ctl->need_reconfirm && ctl->reconfirm_count < cfg->confirm_packets) { /* rule 4 */
    out->mode = FOLLOW_MODE_HOVER;
    out->reason = FOLLOW_REASON_HOVER_RECONFIRM;
  } else {
    const float x = ctl->newest.x_center;
    const float ax = absf(x);

    ctl->need_reconfirm = 0u;
    out->mode = FOLLOW_MODE_FOLLOW;
    out->reason = FOLLOW_REASON_NONE;
    out->yaw_rate_dps = (ax < cfg->yaw_deadband) ? 0.0f : clampf(cfg->yaw_sign * cfg->k_yaw_dps * x, cfg->yaw_max_dps);
    out->vx_mps = (ax < cfg->approach_max_abs_x)
                      ? clampf(cfg->k_fwd_mps * (cfg->target_size - ctl->newest.size_center), cfg->v_max_mps)
                      : 0.0f;
  }
  /* Rule 4 trigger: any step in rule 1 or 2 (incl. t_fresh = NONE). */
  if (stale) {
    ctl->need_reconfirm = 1u;
    ctl->reconfirm_count = 0u;
  }
  /* Keep t_fresh far from the 35.8 min wrap: past land_us it means NONE anyway. */
  if (have && age > cfg->land_us) {
    ctl->have_fresh = 0u;
  }
  if (out->mode == FOLLOW_MODE_HOVER || out->mode == FOLLOW_MODE_FOLLOW) {
    out->target_height_m = cfg->height_m;
  }
}

const char *follow_mode_name(follow_mode_t mode)
{
  switch (mode) {
  case FOLLOW_MODE_WAIT_WARMUP: return "WAIT_WARMUP";
  case FOLLOW_MODE_HOVER:       return "HOVER";
  case FOLLOW_MODE_FOLLOW:      return "FOLLOW";
  case FOLLOW_MODE_LAND:        return "LAND";
  default:                      return "?";
  }
}

const char *follow_reason_name(follow_reason_t reason)
{
  switch (reason) {
  case FOLLOW_REASON_NONE:                return "none";
  case FOLLOW_REASON_NOT_ARMED:           return "not_armed";
  case FOLLOW_REASON_LAND_LATCHED:        return "land_latched";
  case FOLLOW_REASON_LAND_STALE:          return "land_stale";
  case FOLLOW_REASON_LAND_NO_FRAME:       return "land_no_frame";
  case FOLLOW_REASON_HOVER_STALE:         return "hover_stale";
  case FOLLOW_REASON_HOVER_NOT_CONFIRMED: return "hover_not_confirmed";
  case FOLLOW_REASON_HOVER_RULE0:         return "hover_rule0";
  case FOLLOW_REASON_HOVER_RECONFIRM:     return "hover_reconfirm";
  default:                                return "?";
  }
}

const char *follow_rx_status_name(follow_rx_status_t status)
{
  switch (status) {
  case FOLLOW_RX_OK:                return "ok";
  case FOLLOW_RX_ERR_NULL:          return "null";
  case FOLLOW_RX_ERR_LEN:           return "bad_len";
  case FOLLOW_RX_ERR_MAGIC:         return "bad_magic";
  case FOLLOW_RX_ERR_VERSION:       return "bad_version";
  case FOLLOW_RX_ERR_PAYLOAD_LEN:   return "bad_payload_len";
  case FOLLOW_RX_ERR_RESERVED_BITS: return "reserved_bits";
  case FOLLOW_RX_ERR_BAD_VALUE:     return "bad_value";
  default:                          return "?";
  }
}
