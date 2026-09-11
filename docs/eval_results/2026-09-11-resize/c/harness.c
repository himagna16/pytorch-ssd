/* Runs a preprocess implementation over N 324x244 frames from stdin, writes N 128x128 to stdout. */
#include <stdio.h>
#include <stdlib.h>
#include "preprocess.h"
int main(void) {
  static uint8_t cam[324 * 244], out[128 * 128];
  while (fread(cam, 1, sizeof cam, stdin) == sizeof cam) {
    preprocess_camera_to_net_input(cam, 324, 244, out);
    fwrite(out, 1, sizeof out, stdout);
  }
  return 0;
}
