/* Minimal stand-in for the GAP8 app_config.h (branch champion-core8-integration,
 * commit ff876bd; these constants are unchanged since 0623a7d), with only the
 * constants inc/follow_packet.h and the tests use. Values copied verbatim; the
 * compile-time checks are the GAP8's. The visibility thresholds
 * (APP_FOLLOW_VIS_*) are deliberately NOT here: the STM32 sees the bit, not the bar. */
#ifndef APP_CONFIG_H
#define APP_CONFIG_H

#define APP_PACKET_MAGIC (0xA5u)
#define APP_PACKET_VERSION (0x06u)
#define APP_PACKET_AGE_UNIT_US (20000u)
#define APP_PACKET_AGE_SATURATED (255u)
#define APP_STM32_STALE_HOVER_US (500000u)
#define APP_STM32_STALE_LAND_US (3000000u)
#if ((APP_PACKET_AGE_SATURATED - 1u) * APP_PACKET_AGE_UNIT_US) <= (APP_STM32_STALE_LAND_US + 1000000u)
#error "packet age must not saturate within 1 s past the STM32 land threshold"
#endif
#define APP_FOLLOW_RECONFIRM_GAP_US (APP_STM32_STALE_HOVER_US - 100000u)
#define APP_PACKET_TX_MAX_QUEUED (0u)
#define APP_PACKET_TX_MAX_WAIT_US (100000u)

#endif /* APP_CONFIG_H */
