#!/usr/bin/env python3
"""Idempotent local patches to CrazySim's crazysim.py for the macOS package.

1. CAM_FRAME_CHUNK 60000 -> 8000. macOS caps UDP datagrams at 9216 bytes
   (net.inet.udp.maxdgram) and crazysim.py silently drops oversize sends,
   so native camera frames never arrived. Receivers reassemble by seq.
2. Optional ground-truth log. If CRAZYSIM_TRUTH_LOG is set and the scene has
   a body named 'person', every camera frame appends
   "wall_time,sim_time,x,y" for that body. Tests use it to score following
   against the target's true position on the same clock as the follower.

CrazySim is GPLv3; this script modifies a local copy and is not vendored.
Usage: patch_crazysim.py <path/to/crazysim.py>
"""
import re, sys
from pathlib import Path

p = Path(sys.argv[1])
s = p.read_text()
orig = s
s = re.sub(r"^CAM_FRAME_CHUNK = 60000", "CAM_FRAME_CHUNK = 8000", s, flags=re.M)
if "CRAZYSIM_TRUTH_LOG" not in s:
    anchor_init = "        self._port = cam_port if cam_port is not None else CAM_FRAME_BASE_PORT + agent_id\n"
    add_init = anchor_init + (
        "        self._truth_body = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, 'person')\n"
        "        _tl = os.environ.get('CRAZYSIM_TRUTH_LOG')\n"
        "        self._truth = open(_tl, 'a') if (_tl and self._truth_body >= 0) else None\n")
    anchor_render = "        self._renderer.update_scene(data, camera=self._cam_name)\n"
    add_render = (
        "        if self._truth is not None:\n"
        "            _p = data.xpos[self._truth_body]\n"
        "            self._truth.write(f'{time.time():.4f},{data.time:.4f},{_p[0]:.4f},{_p[1]:.4f}\\n')\n"
        "            self._truth.flush()\n") + anchor_render
    if anchor_init not in s or anchor_render not in s:
        sys.exit("crazysim.py layout changed; truth-log patch not applied")
    s = s.replace(anchor_init, add_init, 1).replace(anchor_render, add_render, 1)
if s != orig:
    p.write_text(s)
    print(f"patched {p}")
else:
    print(f"already patched {p}")
