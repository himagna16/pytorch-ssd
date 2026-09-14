/* Host test of inc/follow_packet.h (fix round 6, packet v6). Extends the fix
 * round 5 test: brute-force checks the two-stage stamping against the exact
 * definition with every tracking-byte value, plus the v6 bit helpers and the
 * capture-reference recovery com.c records for the GAP8 re-confirmation. */
#include <stdio.h>
#include <stddef.h>
#include <string.h>
#include <stdlib.h>
#include "follow_packet.h"
static uint8_t ceil_units(uint64_t age_us){uint64_t u=(age_us+APP_PACKET_AGE_UNIT_US-1)/APP_PACKET_AGE_UNIT_US;return u>=255?255:(uint8_t)u;}
#define CHECK(c) do{ if(!(c)){ fail++; if(fail<10) printf("FAIL line %d: %s\n", __LINE__, #c);} }while(0)
int main(void){
  unsigned long n=0,fail=0; srand(1);
  _Static_assert(sizeof(follow_packet_t)==28,"size");
  _Static_assert(offsetof(follow_packet_t,tracking)==16,"trk@16");
  _Static_assert(offsetof(follow_packet_t,frame_age_20ms)==19,"age@19");
  _Static_assert(offsetof(follow_packet_t,vis_raw)==20,"vis@20");
  _Static_assert(offsetof(follow_packet_t,gap8_tx_ms)==24,"tx@24");
  _Static_assert(APP_PACKET_VERSION==6,"v6");
  _Static_assert(FOLLOW_PACKET_TRK_CONFIRMED==1u && FOLLOW_PACKET_TRK_FRAME_VISIBLE==2u,"bits");
  _Static_assert((FOLLOW_PACKET_TRK_RESERVED_MASK & 3u)==0u && (FOLLOW_PACKET_TRK_RESERVED_MASK|3u)==0xFFu,"mask");
  /* tracking byte helpers, all 4 combinations */
  for(int c=0;c<2;c++) for(int v=0;v<2;v++){
    follow_packet_t p; memset(&p,0,sizeof p);
    p.tracking=follow_packet_tracking_byte(c,v);
    CHECK(p.tracking==(uint8_t)(c|(v<<1)));
    CHECK((p.tracking & FOLLOW_PACKET_TRK_RESERVED_MASK)==0);
    CHECK(follow_packet_is_confirmed(&p)==c);
    CHECK(follow_packet_frame_visible(&p)==v);
    CHECK(follow_packet_counts_for_reconfirm(&p)==(c&&v));
  }
  /* nonzero non-1 inputs are normalized */
  { follow_packet_t p; memset(&p,0,sizeof p); p.tracking=follow_packet_tracking_byte(7,-3); CHECK(p.tracking==3); }
  for(int it=0;it<3000000;it++){
    uint32_t cap=(uint32_t)rand()*2654435761u;           /* includes us-clock wrap */
    uint32_t age_enq=(uint32_t)(rand()%6000000);          /* 0..6 s at queue attempt */
    uint32_t wait=(it%3==0)?(uint32_t)(rand()%300):(uint32_t)(rand()%(it%7==0?8000000:200000));
    uint8_t trk_in=(uint8_t)(rand()&3);                   /* v6: all bit combinations */
    follow_packet_t p; memset(&p,0,sizeof p);
    p.magic=0xA5;p.version=APP_PACKET_VERSION;p.tracking=trk_in;
    p.frame_age_20ms=ceil_units(age_enq);
    if (age_enq > APP_FOLLOW_RECONFIRM_GAP_US) p.tracking=0;  /* transport rule: both bits */
    uint8_t trk_enq=p.tracking;
    p.gap8_tx_ms=follow_packet_age_ref_us(cap,p.frame_age_20ms);
    /* fix round 6: capture reference recovered before finalize */
    uint32_t cap_rec=0xDEADBEEFu;
    int have=follow_packet_frame_ref_us(&p,&cap_rec);
    if(p.frame_age_20ms<255){ CHECK(have==1); CHECK(cap_rec==cap); }
    else { CHECK(have==0); CHECK(cap_rec==0xDEADBEEFu); }
    uint32_t now=cap+age_enq+wait;
    follow_packet_finalize_at_tx(&p,now,12345u);
    uint8_t exp=ceil_units((uint64_t)age_enq+wait);
    n++;
    if(p.frame_age_20ms!=255 && exp==255){fail++;}
    else if(p.frame_age_20ms<exp){fail++; if(fail<5)printf("FRESHER age_enq=%u wait=%u got=%u exp=%u\n",age_enq,wait,p.frame_age_20ms,exp);}
    else if(ceil_units(age_enq)<255 && p.frame_age_20ms!=exp){fail++; if(fail<5)printf("NOT EXACT age_enq=%u wait=%u got=%u exp=%u\n",age_enq,wait,p.frame_age_20ms,exp);}
    if(wait>APP_PACKET_TX_MAX_WAIT_US && p.tracking){fail++; if(fail<5)printf("TRK after wait=%u\n",wait);}
    if(wait<=APP_PACKET_TX_MAX_WAIT_US-APP_PACKET_AGE_UNIT_US && p.frame_age_20ms<255 && p.tracking!=trk_enq){fail++; if(fail<5)printf("TRK changed early wait=%u\n",wait);}
    if(p.tracking!=0 && p.tracking!=trk_enq){fail++;}      /* finalize only keeps or clears the whole byte */
    if(p.frame_age_20ms==255 && p.tracking){fail++;}
    if(p.gap8_tx_ms!=12345u){fail++;}
    if(p.magic!=0xA5||p.x_bin!=0||p.vis_raw!=0){fail++;}
  }
  /* saturated input stays saturated, tracking 0 (both bits) */
  follow_packet_t q; memset(&q,0,sizeof q); q.frame_age_20ms=255; q.tracking=3; q.gap8_tx_ms=5;
  { uint32_t c=1; CHECK(follow_packet_frame_ref_us(&q,&c)==0); }
  follow_packet_finalize_at_tx(&q,0,7); CHECK(q.frame_age_20ms==255 && q.tracking==0 && q.gap8_tx_ms==7);
  /* healthy: no wait -> unchanged, both bits kept */
  follow_packet_t h; memset(&h,0,sizeof h); h.frame_age_20ms=2; h.tracking=3; h.gap8_tx_ms=follow_packet_age_ref_us(1000,2);
  { uint32_t c=0; CHECK(follow_packet_frame_ref_us(&h,&c)==1 && c==1000u); }
  follow_packet_finalize_at_tx(&h,1000+25000+300,9); CHECK(h.frame_age_20ms==2 && h.tracking==3);
  /* hysteresis frame (confirmed, p < 0.75, the enter bar since 2026-09-13) must not count for rule 4 */
  follow_packet_t y; memset(&y,0,sizeof y); y.tracking=follow_packet_tracking_byte(1,0);
  CHECK(follow_packet_is_confirmed(&y) && !follow_packet_counts_for_reconfirm(&y));
  printf("cases=%lu failures=%lu\n",n,fail); return fail!=0;
}
