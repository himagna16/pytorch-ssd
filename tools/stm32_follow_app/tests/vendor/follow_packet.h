/*
 * follow_packet.h
 * Responsibility: wire layout of the CPX follow packet (GAP8 -> STM32) and the
 * last-moment TX finalization shared by src/transport_if.c (builds the packet)
 * and lib/cpx/src/com.c (finalizes it right before the SPI transfer).
 *
 * Pure C (no PMSIS/FreeRTOS includes) so the finalization and the tracking-byte
 * helpers can be host-tested.
 * The full field documentation and STM32 rules are in src/transport_if.c and
 * docs/champion_integration.md.
 */

#ifndef FOLLOW_PACKET_H
#define FOLLOW_PACKET_H

#include <stdint.h>

#include "app_config.h"

/* Packet v6, 28 bytes, packed, little-endian. Same layout as v5; v6 (fix
 * round 6) turns byte 16 into bit flags (FOLLOW_PACKET_TRK_* below). v5 added
 * bytes 24..27 to the 24-byte v4 layout. */
typedef struct __attribute__((packed)) {
  uint8_t magic;          /*  0: APP_PACKET_MAGIC (0xA5) */
  uint8_t version;        /*  1: APP_PACKET_VERSION (0x06) */
  uint16_t payload_len;   /*  2: 24 = bytes after this field */
  uint32_t frame_id;      /*  4 */
  float x_center;         /*  8 */
  float size_center;      /* 12 */
  uint8_t tracking;       /* 16: bit flags, FOLLOW_PACKET_TRK_* */
  uint8_t x_bin;          /* 17 */
  uint8_t size_bucket;    /* 18 */
  uint8_t frame_age_20ms; /* 19: age at the SPI transfer (see below) */
  int32_t vis_raw;        /* 20 */
  uint32_t gap8_tx_ms;    /* 24: GAP8 ms clock at the SPI transfer (see below) */
} follow_packet_t;

/* Compile-time check of the wire size. */
typedef char follow_packet_size_must_be_28[(sizeof(follow_packet_t) == 28u) ? 1 : -1];

/* Byte 16 (tracking), v6 (fix round 6). Bits 2..7 are reserved and sent as 0.
 * The STM32 must test bits; never compare the byte with 1.
 *   bit 0 CONFIRMED:     the GAP8 visibility state machine is tracking
 *                        (confirmed after 3 consecutive frames at p >= 0.75,
 *                        kept until p < 0.45). Steer only when set (rule 3).
 *   bit 1 FRAME_VISIBLE: THIS frame's visibility confidence is >= the enter
 *                        threshold (p >= 0.75; raw v[9] >= APP_FOLLOW_VIS_ENTER_RAW,
 *                        the decoder's own per-frame comparison). Lets the STM32
 *                        count only p >= 0.75 frames when it re-confirms after a
 *                        stale hover (rule 4: 3 consecutive fresh packets with
 *                        bit 0 AND bit 1 set).
 * Both bits are 0 in no-target packets, when the frame was older than
 * APP_FOLLOW_RECONFIRM_GAP_US at the queue attempt, and when com.c finds the
 * packet waited too long or its age saturated (the whole byte is cleared). */
#define FOLLOW_PACKET_TRK_CONFIRMED     (0x01u)
#define FOLLOW_PACKET_TRK_FRAME_VISIBLE (0x02u)
#define FOLLOW_PACKET_TRK_RESERVED_MASK (0xFCu)

static inline uint8_t follow_packet_tracking_byte(int confirmed, int frame_visible)
{
  return (uint8_t)((confirmed ? FOLLOW_PACKET_TRK_CONFIRMED : 0u) |
                   (frame_visible ? FOLLOW_PACKET_TRK_FRAME_VISIBLE : 0u));
}

/* STM32 rule 3: steer only on packets with bit 0 set. */
static inline int follow_packet_is_confirmed(const follow_packet_t *packet)
{
  return (packet->tracking & FOLLOW_PACKET_TRK_CONFIRMED) != 0u;
}

static inline int follow_packet_frame_visible(const follow_packet_t *packet)
{
  return (packet->tracking & FOLLOW_PACKET_TRK_FRAME_VISIBLE) != 0u;
}

/* STM32 rule 4 bit test: a packet counts toward the 3 re-confirmation packets
 * only with bit 0 AND bit 1 set (and it must also be fresh by rule 0 and have
 * frame_age_20ms * 0.020 <= 0.5 s; those checks are the STM32's). */
static inline int follow_packet_counts_for_reconfirm(const follow_packet_t *packet)
{
  const uint8_t both = (uint8_t)(FOLLOW_PACKET_TRK_CONFIRMED | FOLLOW_PACKET_TRK_FRAME_VISIBLE);

  return (packet->tracking & both) == both;
}

/* Two-stage stamping (fix round 5).
 *
 * Stage 1, transport_if.c, immediately before the non-blocking queue attempt:
 * frame_age_20ms = ceil(age / 20 ms) as before, and gap8_tx_ms temporarily
 * holds the AGE REFERENCE: ref_us = capture_end_us + frame_age_20ms * 20 ms
 * (GAP8 us clock, pi_time_get_us()). ref_us is the queue-attempt time plus the
 * age round-up slack (< 20 ms), i.e. the moment at which the stamped age
 * becomes exact.
 *
 * Stage 2, com.c, after the NINA handshake returns and immediately before the
 * SPI transfer of the payload, for app packets only:
 *   late_us = now_us - ref_us  (signed, wrap-safe for |late| < 35.8 min)
 *   late_us > 0 -> frame_age_20ms += ceil(late_us / 20 ms), saturating at 255
 *   so the age becomes ceil((now_us - capture_end_us) / 20 ms): the age at the
 *   SPI transfer, still rounded up, never fresher than it is.
 *   tracking = 0 (both bits) if the packet may have waited more than
 *   APP_PACKET_TX_MAX_WAIT_US since its queue attempt (wait = late_us + slack,
 *   slack < 20 ms, so the test is late_us > MAX_WAIT - 20 ms: conservative),
 *   or if the age is saturated.
 *   gap8_tx_ms = now_ms (the GAP8 ms clock, FreeRTOS ticks at 1 kHz, uint32,
 *   wraps every 49.7 days), replacing the reference.
 * A healthy packet (late_us <= 0) keeps its age and tracking byte unchanged.
 *
 * A stall longer than 35.8 min would wrap late_us; by then the STM32 has
 * landed (latched) on the 3.0 s rule, and rule 4 plus the GAP8 TX-gap
 * re-confirmation block steering on the at most 2 late packets. */
static inline uint32_t follow_packet_age_ref_us(uint32_t capture_end_us, uint8_t frame_age_20ms)
{
  return capture_end_us + (uint32_t)frame_age_20ms * (uint32_t)APP_PACKET_AGE_UNIT_US;
}

/* Fix round 6. Valid only BEFORE follow_packet_finalize_at_tx (gap8_tx_ms still
 * holds the stage-1 reference): recovers capture_end_us of the frame the packet
 * describes, exactly (mod 2^32), as ref_us - frame_age_20ms * 20 ms. Returns 0
 * (no frame) when the age is saturated: no valid frame since boot, or older
 * than 5.08 s. com.c records it for the GAP8 re-confirmation check. */
static inline int follow_packet_frame_ref_us(const follow_packet_t *packet, uint32_t *capture_end_us)
{
  if (packet->frame_age_20ms >= (uint8_t)APP_PACKET_AGE_SATURATED) {
    return 0;
  }
  *capture_end_us = packet->gap8_tx_ms - (uint32_t)packet->frame_age_20ms * (uint32_t)APP_PACKET_AGE_UNIT_US;
  return 1;
}

static inline void follow_packet_finalize_at_tx(follow_packet_t *packet, uint32_t now_us, uint32_t now_ms)
{
  uint32_t ref_us = packet->gap8_tx_ms;
  int32_t late_us = (int32_t)(now_us - ref_us);

  if (packet->frame_age_20ms >= (uint8_t)APP_PACKET_AGE_SATURATED) {
    packet->tracking = 0u;
  } else if (late_us > 0) {
    uint32_t add = ((uint32_t)late_us + (uint32_t)APP_PACKET_AGE_UNIT_US - 1u) / (uint32_t)APP_PACKET_AGE_UNIT_US;
    uint32_t age = (uint32_t)packet->frame_age_20ms + add; /* add <= 107,375: no overflow */

    packet->frame_age_20ms = (uint8_t)((age >= (uint32_t)APP_PACKET_AGE_SATURATED) ? APP_PACKET_AGE_SATURATED : age);
    if ((uint32_t)late_us > ((uint32_t)APP_PACKET_TX_MAX_WAIT_US - (uint32_t)APP_PACKET_AGE_UNIT_US) ||
        packet->frame_age_20ms >= (uint8_t)APP_PACKET_AGE_SATURATED) {
      packet->tracking = 0u;
    }
  }
  packet->gap8_tx_ms = now_ms;
}

#endif /* FOLLOW_PACKET_H */
