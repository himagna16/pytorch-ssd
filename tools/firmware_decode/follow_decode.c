#include "follow_decode.h"
#include <math.h>

int32_t follow_raw_thresh(double p, double eps_out) {
    return (int32_t)ceil(log(p / (1.0 - p)) / eps_out);
}

void follow_vis_cfg_default(follow_vis_cfg_t *cfg, double eps_out) {
    cfg->enter_raw = follow_raw_thresh(0.75, eps_out);
    cfg->exit_raw = follow_raw_thresh(0.45, eps_out);
    cfg->confirm_frames = 3;
}

void follow_vis_reset(follow_vis_state_t *st) { st->tracking = 0; st->streak = 0; }

int follow_argmax_i32(const int32_t *v, int n) {
    int best = 0;
    for (int i = 1; i < n; i++) if (v[i] > v[best]) best = i;
    return best;
}

void follow_decode(const int32_t out[FOLLOW_N_OUT], const follow_vis_cfg_t *cfg,
                   follow_vis_state_t *st, follow_cmd_t *cmd) {
    cmd->x_bin = follow_argmax_i32(out, FOLLOW_N_XBIN);
    cmd->x_center = -1.0f + (2.0f * (float)cmd->x_bin + 1.0f) / 9.0f;
    cmd->size_bucket = follow_argmax_i32(out + FOLLOW_SIZE_OFF, FOLLOW_N_SIZE);
    cmd->size_center = ((float)cmd->size_bucket + 0.5f) / 4.0f;
    cmd->vis_raw = out[FOLLOW_VIS_IDX];

    /* Same order as the simulator follower: update the streak, then the state.
     * The streak is capped so it cannot overflow on long flights; the cap does
     * not change behavior because only "streak >= confirm_frames" is tested. */
    if (out[FOLLOW_VIS_IDX] >= cfg->enter_raw) {
        if (st->streak < cfg->confirm_frames) st->streak++;
    } else {
        st->streak = 0;
    }
    if (st->tracking && out[FOLLOW_VIS_IDX] < cfg->exit_raw) st->tracking = 0;
    else if (!st->tracking && st->streak >= cfg->confirm_frames) st->tracking = 1;
    cmd->tracking = st->tracking;
}
