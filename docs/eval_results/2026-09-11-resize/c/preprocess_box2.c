/*
 * preprocess.c (PROPOSED)
 * Responsibility: Crop/resize grayscale camera frame into network input tensor.
 * Change vs original: each output pixel is the rounded mean of the 2x2 camera
 * block starting at the old nearest-neighbor source pixel, instead of that
 * single pixel. 244->128 is a 1.906x downscale, so a 2x2 box is a close,
 * cheap stand-in for the antialiased (area-like) resize used in training.
 */

#include "preprocess.h"

#include <stddef.h>

#include "app_config.h"

#if (APP_NET_INPUT_C != 1) && (APP_NET_INPUT_C != 3)
#error "APP_NET_INPUT_C must be 1 or 3"
#endif

void preprocess_camera_to_net_input(
    const uint8_t *cam_buf,
    int cam_w,
    int cam_h,
    uint8_t *net_in)
{
  int crop_size = (cam_w < cam_h) ? cam_w : cam_h;
  int crop_x = (cam_w - crop_size) / 2;
  int crop_y = (cam_h - crop_size) / 2;
  int crop_x_last = crop_x + crop_size - 1;
  int crop_y_last = crop_y + crop_size - 1;
  int y;
  int x;

  for (y = 0; y < APP_NET_INPUT_H; y++) {
    int src_y = crop_y + ((y * crop_size) / APP_NET_INPUT_H);
    int src_y1 = (src_y < crop_y_last) ? (src_y + 1) : src_y;
    const uint8_t *row0 = cam_buf + (src_y * cam_w);
    const uint8_t *row1 = cam_buf + (src_y1 * cam_w);

    for (x = 0; x < APP_NET_INPUT_W; x++) {
      int src_x = crop_x + ((x * crop_size) / APP_NET_INPUT_W);
      int src_x1 = (src_x < crop_x_last) ? (src_x + 1) : src_x;
      unsigned int sum = (unsigned int)row0[src_x] + (unsigned int)row0[src_x1] +
                         (unsigned int)row1[src_x] + (unsigned int)row1[src_x1];
      uint8_t gray = (uint8_t)((sum + 2u) >> 2);

#if (APP_NET_INPUT_C == 1)
      size_t dst_idx = ((size_t)y * (size_t)APP_NET_INPUT_W) + (size_t)x;
      net_in[dst_idx] = gray;
#else
      size_t dst_idx =
          (((size_t)y * (size_t)APP_NET_INPUT_W) + (size_t)x) * (size_t)APP_NET_INPUT_C;
      net_in[dst_idx + 0u] = gray;
      net_in[dst_idx + 1u] = gray;
      net_in[dst_idx + 2u] = gray;
#endif
    }
  }
}
