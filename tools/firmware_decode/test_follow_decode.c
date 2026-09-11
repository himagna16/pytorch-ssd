/* Tests for follow_decode.c. Hand-built cases always run; pass a vectors file
 * from gen_vectors.py to also check agreement with the Python decode. */
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "follow_decode.h"

static int fails = 0, checks = 0;
#define CHECK(cond, ...) do { checks++; if (!(cond)) { fails++; \
    printf("FAIL line %d: ", __LINE__); printf(__VA_ARGS__); printf("\n"); } } while (0)

static int near(float a, float b) { return a - b < 1e-6f && b - a < 1e-6f; }

static void test_david_tensor(void) {
    const int32_t v[14] = {4632, 13262, 4633, -2422, -3479, -5390, 2962, -1854,
                           -11170, 5303, -7980, 3540, 4466, -43};
    follow_vis_cfg_t cfg = {1000, -300, 3};
    follow_vis_state_t st; follow_cmd_t c;
    follow_vis_reset(&st);
    follow_decode(v, &cfg, &st, &c);
    CHECK(c.x_bin == 1, "x_bin %d", c.x_bin);
    CHECK(near(c.x_center, -1.0f + 3.0f / 9.0f), "x_center %f", c.x_center);
    CHECK(c.size_bucket == 2, "size_bucket %d", c.size_bucket);
    CHECK(near(c.size_center, 0.625f), "size_center %f", c.size_center);
    CHECK(c.vis_raw == 5303, "vis_raw %d", (int)c.vis_raw);
    CHECK(c.tracking == 0, "one frame must not start tracking");
    follow_decode(v, &cfg, &st, &c);
    CHECK(c.tracking == 0, "two frames must not start tracking");
    follow_decode(v, &cfg, &st, &c);
    CHECK(c.tracking == 1, "three frames must start tracking");
}

static void test_ties_and_extremes(void) {
    follow_vis_cfg_t cfg = {1, 0, 3};
    follow_vis_state_t st; follow_cmd_t c;
    int32_t v[14] = {0};
    follow_vis_reset(&st);
    follow_decode(v, &cfg, &st, &c);
    CHECK(c.x_bin == 0 && c.size_bucket == 0, "all-zero ties pick index 0");
    v[3] = 7; v[7] = 7; v[11] = 5; v[13] = 5;
    follow_decode(v, &cfg, &st, &c);
    CHECK(c.x_bin == 3 && c.size_bucket == 1, "ties pick the first max (x %d, size %d)", c.x_bin, c.size_bucket);
    for (int i = 0; i < 14; i++) v[i] = INT32_MIN;
    v[8] = INT32_MAX; v[13] = INT32_MIN + 1;
    follow_decode(v, &cfg, &st, &c);
    CHECK(c.x_bin == 8 && near(c.x_center, 1.0f - 1.0f / 9.0f), "extreme right bin");
    CHECK(c.size_bucket == 3 && near(c.size_center, 0.875f), "largest size bucket");
    CHECK(c.tracking == 0, "INT32_MIN visibility never counts");
}

static int step(follow_vis_state_t *st, const follow_vis_cfg_t *cfg, int32_t vis) {
    int32_t v[14] = {0}; follow_cmd_t c;
    v[FOLLOW_VIS_IDX] = vis;
    follow_decode(v, cfg, st, &c);
    return c.tracking;
}

static void test_state_machine(void) {
    follow_vis_cfg_t cfg = {100, -50, 3};
    follow_vis_state_t st; follow_vis_reset(&st);
    const int32_t seq[] = {100, 100, 99, 100, 100, 100, 0, -50, -51, 100, 100, 100, 500};
    const int want[]    = {0,   0,   0,  0,   0,   1,   1, 1,   0,   0,   0,   1,   1};
    for (unsigned i = 0; i < sizeof seq / sizeof seq[0]; i++)
        CHECK(step(&st, &cfg, seq[i]) == want[i], "state step %u (vis %d)", i, (int)seq[i]);
    for (long i = 0; i < 100000; i++) step(&st, &cfg, 1000);
    CHECK(st.streak <= cfg.confirm_frames, "streak stays capped (%d)", st.streak);
    cfg.confirm_frames = 1; follow_vis_reset(&st);
    CHECK(step(&st, &cfg, 100) == 1, "confirm_frames=1 tracks on the first counting frame");
}

static void test_thresholds(void) {
    follow_vis_cfg_t cfg;
    follow_vis_cfg_default(&cfg, 0.01);
    CHECK(cfg.enter_raw == 85, "enter_raw %d (want ceil(0.8473/0.01)=85)", (int)cfg.enter_raw);
    CHECK(cfg.exit_raw == -20, "exit_raw %d (want ceil(-0.2007/0.01)=-20)", (int)cfg.exit_raw);
    CHECK(cfg.confirm_frames == 3, "confirm_frames %d", cfg.confirm_frames);
}

static int run_file(const char *path) {
    FILE *f = fopen(path, "r");
    if (!f) { printf("cannot open %s\n", path); return 1; }
    char tag[16]; double eps = 0; follow_vis_cfg_t cfg = {0, 0, 3};
    long nv = 0, ns = 0;
    while (fscanf(f, "%15s", tag) == 1) {
        if (!strcmp(tag, "EPS")) {
            if (fscanf(f, "%lf", &eps) != 1) break;
            follow_vis_cfg_default(&cfg, eps);
            printf("eps_out %-10g enter_raw %-8d exit_raw %d\n", eps, (int)cfg.enter_raw, (int)cfg.exit_raw);
        } else if (!strcmp(tag, "V")) {
            int32_t v[14]; int xb, sb, cnt, lost;
            for (int i = 0; i < 14; i++) if (fscanf(f, "%d", &v[i]) != 1) goto bad;
            if (fscanf(f, "%d %d %d %d", &xb, &sb, &cnt, &lost) != 4) goto bad;
            follow_vis_state_t st; follow_cmd_t c; follow_vis_reset(&st);
            follow_decode(v, &cfg, &st, &c);
            CHECK(c.x_bin == xb, "eps %g vector %ld: x_bin C %d vs Python %d", eps, nv, c.x_bin, xb);
            CHECK(c.size_bucket == sb, "eps %g vector %ld: size C %d vs Python %d", eps, nv, c.size_bucket, sb);
            CHECK((v[9] >= cfg.enter_raw) == cnt, "eps %g vector %ld: enter test on vis %d", eps, nv, (int)v[9]);
            CHECK((v[9] < cfg.exit_raw) == lost, "eps %g vector %ld: exit test on vis %d", eps, nv, (int)v[9]);
            nv++;
        } else if (!strcmp(tag, "S")) {
            int n; if (fscanf(f, "%d", &n) != 1 || n <= 0 || n > 10000) goto bad;
            int32_t *vis = malloc(sizeof *vis * n); int *want = malloc(sizeof *want * n);
            for (int i = 0; i < n; i++) if (fscanf(f, "%d", &vis[i]) != 1) { free(vis); free(want); goto bad; }
            for (int i = 0; i < n; i++) if (fscanf(f, "%d", &want[i]) != 1) { free(vis); free(want); goto bad; }
            follow_vis_state_t st; follow_vis_reset(&st);
            for (int i = 0; i < n; i++)
                CHECK(step(&st, &cfg, vis[i]) == want[i], "eps %g sequence %ld step %d", eps, ns, i);
            free(vis); free(want); ns++;
        } else goto bad;
    }
    fclose(f);
    printf("file checks: %ld vectors, %ld sequences\n", nv, ns);
    return (nv > 0 && ns > 0) ? 0 : 1;
bad:
    fclose(f); printf("malformed vectors file near record '%s'\n", tag); return 1;
}

int main(int argc, char **argv) {
    test_david_tensor();
    test_ties_and_extremes();
    test_state_machine();
    test_thresholds();
    int file_err = argc > 1 ? run_file(argv[1]) : 0;
    printf("%d checks, %d failures%s\n", checks, fails, argc > 1 ? "" : " (no vectors file given)");
    return (fails || file_err) ? 1 : 0;
}
