/* Reference decoder for the 14-value follow output (xbin9_size_bucket4 head).
 * Mirrors utils/follow_task.py::decode_follow_outputs (successor-release) and the
 * simulator follower's confirmation rule (tools/crazysim_macos/follow_person.py).
 * Dependency-free except follow_raw_thresh(), which uses libm and is meant for the
 * host; on the GAP8, bake the thresholds in as constants (see raw_thresholds.py). */
#ifndef FOLLOW_DECODE_H
#define FOLLOW_DECODE_H
#include <stdint.h>

#define FOLLOW_N_OUT    14
#define FOLLOW_N_XBIN    9
#define FOLLOW_VIS_IDX   9
#define FOLLOW_SIZE_OFF 10
#define FOLLOW_N_SIZE    4

typedef struct {
    int32_t enter_raw;     /* a frame counts toward confirmation when v[9] >= enter_raw */
    int32_t exit_raw;      /* while tracking, v[9] < exit_raw means LOST */
    int     confirm_frames;/* consecutive counting frames needed to start tracking */
} follow_vis_cfg_t;

typedef struct { int tracking; int streak; } follow_vis_state_t;

typedef struct {
    int     x_bin;        /* 0..8, left -> right */
    float   x_center;     /* bin center in [-1, 1] */
    int     size_bucket;  /* 0..3, small/far -> large/near */
    float   size_center;  /* bucket center in [0, 1] */
    int32_t vis_raw;      /* raw visibility value v[9] */
    int     tracking;     /* 1 = confirmed target, steer on x/size; 0 = hover */
} follow_cmd_t;

/* Smallest integer r with r * eps_out >= logit(p). With this definition,
 * "v[9] >= follow_raw_thresh(p, eps)" is exactly "sigmoid(v[9]*eps) >= p",
 * and "v[9] < follow_raw_thresh(p, eps)" is exactly "sigmoid(v[9]*eps) < p". */
int32_t follow_raw_thresh(double p, double eps_out);
/* Team rule: count at p >= 0.7, confirm after 3 consecutive frames, lost below 0.45. */
void follow_vis_cfg_default(follow_vis_cfg_t *cfg, double eps_out);
void follow_vis_reset(follow_vis_state_t *st);
/* First index of the maximum (same tie rule as torch.argmax). */
int  follow_argmax_i32(const int32_t *v, int n);
void follow_decode(const int32_t out[FOLLOW_N_OUT], const follow_vis_cfg_t *cfg,
                   follow_vis_state_t *st, follow_cmd_t *cmd);
#endif
