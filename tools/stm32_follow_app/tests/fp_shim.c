/* libfp: ctypes exports of the GAP8's inc/follow_packet.h (vendored verbatim in
 * tests/vendor/, branch champion-core8-integration commit 0623a7d), as used by
 * the review6 safety simulator (_lib.fp_* in safety_sim_review6*.py). The
 * original shim was not committed with the simulator; this one exposes the same
 * functions, each a one-line call into the committed header. */
#include <stddef.h>
#include <string.h>

#include "follow_packet.h"

int fp_version(void) { return (int)APP_PACKET_VERSION; }
int fp_sizeof(void) { return (int)sizeof(follow_packet_t); }
int fp_off_age(void) { return (int)offsetof(follow_packet_t, frame_age_20ms); }
int fp_off_tx(void) { return (int)offsetof(follow_packet_t, gap8_tx_ms); }
int fp_off_trk(void) { return (int)offsetof(follow_packet_t, tracking); }

void fp_finalize(char *buf, uint32_t now_us, uint32_t now_ms)
{
  follow_packet_t p;

  memcpy(&p, buf, sizeof p);
  follow_packet_finalize_at_tx(&p, now_us, now_ms);
  memcpy(buf, &p, sizeof p);
}

uint32_t fp_ref(uint32_t capture_end_us, uint8_t age)
{
  return follow_packet_age_ref_us(capture_end_us, age);
}

int fp_frame_ref(const char *buf, uint32_t *capture_end_us)
{
  follow_packet_t p;

  memcpy(&p, buf, sizeof p);
  return follow_packet_frame_ref_us(&p, capture_end_us);
}

int fp_trk_byte(int confirmed, int visible) { return (int)follow_packet_tracking_byte(confirmed, visible); }

int fp_is_confirmed(const char *buf)
{
  follow_packet_t p;

  memcpy(&p, buf, sizeof p);
  return follow_packet_is_confirmed(&p);
}

int fp_counts(const char *buf)
{
  follow_packet_t p;

  memcpy(&p, buf, sizeof p);
  return follow_packet_counts_for_reconfirm(&p);
}
