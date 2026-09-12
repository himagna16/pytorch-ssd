#!/usr/bin/env python3
"""Idempotent local patches to CrazySim's crazysim.py for the macOS package.

1. CAM_FRAME_CHUNK 60000 -> 8000. macOS caps UDP datagrams at 9216 bytes
   (net.inet.udp.maxdgram) and crazysim.py silently drops oversize sends,
   so native camera frames never arrived. Receivers reassemble by seq.

2. Ground-truth log (CRAZYSIM_TRUTH_LOG). Every camera frame appends the true
   position of the scene's subject(s), immediately BEFORE that frame renders,
   so a row describes the state of the frame that follows it. Tests use it to
   score following against the target's true position on the same clock as the
   follower.

   CRAZYSIM_TRUTH_PREFIX selects which bodies are logged:

     unset  -> EXACTLY today's behaviour: the single body named 'person',
               four columns "wall_time,sim_time,x,y", no header. demo.sh,
               run_acceptance.sh and every published baseline are unaffected.

     set    -> every body whose name starts with the prefix (the v2 scenes use
               'subj_'), in model order:

                   # bodies: subj_person_target,subj_pet_distractor
                   1757630400.1234,12.3400,3.2000,0.9000,0.8500,2.4000,-1.1000,0.3250

               i.e. one '#' header naming the bodies in column order, then
               wall_time,sim_time, then x,y,z per body. numpy.loadtxt ignores
               '#' lines by default and the first subject's x,y land in columns
               2 and 3, so analyze_follow.py and analyze_follow_app.py read the
               new format unmodified, as "the first subject".

   If the prefix matches no body, that is announced loudly on stdout and the
   log falls back to the body named 'person'. A silently empty truth log
   already caused one scoring bug; it must never be silent again.

3. Scripted scene motion (CRAZYSIM_SCENE_MOTION). Unset -> nothing happens.
   Set to a JSON file (build_scene.py writes one per scene that needs it), it
   kinematically drives named slide joints once per physics step:

       q(t) = clamp(q0 + v * max(0, t - t_start), lo, hi)

   MuJoCo cannot express constant-velocity motion in MJCF alone: a joint's
   initial velocity can only come from a <keyframe>, and keyframes do not
   survive CrazySim's MjSpec drone attach. Driving the joint directly is the
   supported alternative, and because it is kinematic the realised path is
   exact rather than dragged by the scene's air model. It is still the truth
   log, not this file, that scorers must read.

4. Camera sensor model (CRAZYSIM_SENSOR_PRESET). Unset -> the original luma
   line runs verbatim and the pushed bytes are identical to today's, so every
   verified baseline stays valid. Set to a preset name (himax_typical,
   himax_low_light, himax_color_bayer) and each rendered frame is degraded the
   way the real AI-deck Himax sensor would degrade it: auto-exposure to a
   60 DN frame mean, optical blur, vignetting, shot/read/fixed-pattern noise,
   dead pixels, LED row banding, and motion blur derived from the drone's own
   gyro. The model lives in the team repo as camera_model.py and is copied next
   to crazysim.py by this script; crazysim.py imports it as a sibling module.

   Applying it here rather than in each consumer means follow_person.py,
   gap8_emulator.py, cpx_grab.py --sim, --save-frames and the videos all see
   the same pixels, and it is the only place the body angular rate needed for
   motion blur is available. Design: scratchpad/simv2/spec_camera.md.

CrazySim is GPLv3; this script modifies a local copy and is not vendored.
Usage: patch_crazysim.py <path/to/crazysim.py>
"""
import re
import shutil
import sys
from pathlib import Path

# --- 2. truth log ----------------------------------------------------------
ANCHOR_INIT = ("        self._port = cam_port if cam_port is not None "
               "else CAM_FRAME_BASE_PORT + agent_id\n")
ANCHOR_RENDER = "        self._renderer.update_scene(data, camera=self._cam_name)\n"

V1_INIT = (
    "        self._truth_body = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, 'person')\n"
    "        _tl = os.environ.get('CRAZYSIM_TRUTH_LOG')\n"
    "        self._truth = open(_tl, 'a') if (_tl and self._truth_body >= 0) else None\n")
V1_RENDER = (
    "        if self._truth is not None:\n"
    "            _p = data.xpos[self._truth_body]\n"
    "            self._truth.write(f'{time.time():.4f},{data.time:.4f},{_p[0]:.4f},{_p[1]:.4f}\\n')\n"
    "            self._truth.flush()\n")

TRUTH_INIT = r"""        # --- crazysim_macos truth log v2 (start) ---
        _pfx = os.environ.get('CRAZYSIM_TRUTH_PREFIX')
        _bodies = []
        if _pfx:
            for _i in range(model.nbody):
                _n = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_BODY, _i)
                if _n and _n.startswith(_pfx):
                    _bodies.append((_i, _n))
            if not _bodies:
                print(f'[crazysim] WARNING: CRAZYSIM_TRUTH_PREFIX={_pfx!r} matched no body in '
                      f'this scene; falling back to the body named person')
        self._truth_multi = bool(_pfx) and bool(_bodies)
        if not _bodies:
            _pb = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, 'person')
            _bodies = [(_pb, 'person')] if _pb >= 0 else []
        self._truth_bodies = _bodies
        self._truth_body = _bodies[0][0] if _bodies else -1
        _tl = os.environ.get('CRAZYSIM_TRUTH_LOG')
        self._truth = open(_tl, 'a') if (_tl and _bodies) else None
        if self._truth is not None:
            print(f'[crazysim] truth log -> {_tl} '
                  f'({"multi" if self._truth_multi else "legacy"}: '
                  f'{",".join(_n for _, _n in _bodies)})')
            if self._truth_multi and self._truth.tell() == 0:
                self._truth.write('# bodies: ' + ','.join(_n for _, _n in _bodies) + '\n')
                self._truth.flush()
        # --- crazysim_macos truth log v2 (end) ---
"""

TRUTH_RENDER = r"""        # --- crazysim_macos truth write v2 (start) ---
        if self._truth is not None:
            if self._truth_multi:
                _v = ''.join(f',{data.xpos[_i][0]:.4f},{data.xpos[_i][1]:.4f},{data.xpos[_i][2]:.4f}'
                             for _i, _n in self._truth_bodies)
                self._truth.write(f'{time.time():.4f},{data.time:.4f}{_v}\n')
            else:
                _p = data.xpos[self._truth_body]
                self._truth.write(f'{time.time():.4f},{data.time:.4f},{_p[0]:.4f},{_p[1]:.4f}\n')
            self._truth.flush()
        # --- crazysim_macos truth write v2 (end) ---
"""

# --- 3. scripted scene motion ---------------------------------------------
ANCHOR_MOTION_DEF = "class CameraRenderer:\n"
ANCHOR_MJ_STEP = "            mujoco.mj_step(self.model, self.data)\n"

MOTION_DEF = r'''# --- crazysim_macos scene motion (start) ---
# Kinematically drive named slide joints so scenes can script constant-velocity
# paths (a person walking out of frame). Off unless CRAZYSIM_SCENE_MOTION points
# at a JSON list of {joint, q0, v, t_start, lo, hi}. Written by build_scene.py.
_SCENE_DRIVES = None


def _crazysim_drive_scene_motion(model, data):
    global _SCENE_DRIVES
    if _SCENE_DRIVES is None:
        import json as _json
        _SCENE_DRIVES = []
        _path = os.environ.get('CRAZYSIM_SCENE_MOTION')
        if _path:
            try:
                _spec = _json.loads(open(_path).read())
            except Exception as _e:
                print(f'[crazysim] scene motion: cannot read {_path}: {_e}')
                _spec = []
            for _e in _spec:
                _jid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, _e['joint'])
                if _jid < 0:
                    print(f'[crazysim] scene motion: WARNING no joint named '
                          f'{_e["joint"]!r}; that subject will not move')
                    continue
                _SCENE_DRIVES.append((int(model.jnt_qposadr[_jid]), int(model.jnt_dofadr[_jid]),
                                      float(_e.get('q0', 0.0)), float(_e.get('v', 0.0)),
                                      float(_e.get('t_start', 0.0)),
                                      _e.get('lo'), _e.get('hi'), _e['joint']))
            if _SCENE_DRIVES:
                print(f'[crazysim] scene motion: driving '
                      f'{", ".join(_d[7] for _d in _SCENE_DRIVES)} from {_path}')
    if not _SCENE_DRIVES:
        return
    _t = data.time
    for _qadr, _dadr, _q0, _v, _t0, _lo, _hi, _nm in _SCENE_DRIVES:
        _q = _q0 + _v * max(0.0, _t - _t0)
        _vel = 0.0 if _t < _t0 else _v
        if _lo is not None and _q <= _lo:
            _q, _vel = _lo, 0.0
        if _hi is not None and _q >= _hi:
            _q, _vel = _hi, 0.0
        data.qpos[_qadr] = _q
        data.qvel[_dadr] = _vel
# --- crazysim_macos scene motion (end) ---


'''

MOTION_CALL = "            _crazysim_drive_scene_motion(self.model, self.data)\n"


# --- 4. camera sensor model -----------------------------------------------
# The gray line below is crazysim.py's own; it must survive verbatim as the
# CRAZYSIM_SENSOR_PRESET-unset branch, so the pushed bytes do not change.
ANCHOR_GRAY = ("        gray = np.dot(pixels[..., :3], "
               "[0.2989, 0.5870, 0.1140]).astype(np.uint8)\n")
CAM_START = "        # --- crazysim_macos camera sensor (start) ---\n"
CAM_END = "        # --- crazysim_macos camera sensor (end) ---\n"
CAM_APPLY_START = "        # --- crazysim_macos camera sensor apply (start) ---\n"
CAM_APPLY_END = "        # --- crazysim_macos camera sensor apply (end) ---\n"

CAMERA_INIT = CAM_START + r"""        _gid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_SENSOR, f'cf{agent_id}_gyro')
        self._gyro_adr = int(model.sensor_adr[_gid]) if _gid >= 0 else -1
        try:
            import camera_model as _camera_model
            self._sensor = _camera_model.from_env(width, height)
        except Exception as _e:
            print(f'[crazysim] camera_model unavailable ({_e!r}); frames stay clean')
            self._sensor = None
        if self._sensor is not None and self._gyro_adr < 0:
            print('[crazysim] WARNING: no gyro sensor found; camera motion blur disabled')
""" + CAM_END

CAMERA_APPLY = (CAM_APPLY_START +
                "        if self._sensor is None:\n    " + ANCHOR_GRAY +
                r"""        else:
            _w = (data.sensordata[self._gyro_adr:self._gyro_adr + 3]
                  if self._gyro_adr >= 0 else None)
            gray = self._sensor.apply(pixels, _w, self._frame_period)
""" + CAM_APPLY_END)


def restore_gray(s: str) -> str:
    """Undo a previous sensor-apply insertion, leaving crazysim.py's own line."""
    pat = re.compile(re.escape(CAM_APPLY_START) + r".*?" + re.escape(CAM_APPLY_END),
                     re.S)
    return pat.sub(ANCHOR_GRAY.rstrip("\n") + "\n", s)


def strip_block(s: str, start: str, end: str) -> str:
    """Remove a previously inserted sentinel-delimited block, if present."""
    pat = re.compile(re.escape(start) + r".*?" + re.escape(end) + r"\n*", re.S)
    return pat.sub("", s)


def main():
    p = Path(sys.argv[1])
    s = p.read_text()
    orig = s

    # The sensor model lives in the team repo; crazysim.py imports it as a
    # sibling module. Copy it every run so re-running setup.sh refreshes it.
    src = Path(__file__).resolve().parent / "camera_model.py"
    if src.exists():
        shutil.copy2(src, p.parent / "camera_model.py")
        print(f"installed {p.parent / 'camera_model.py'}")
    else:
        print(f"WARNING: {src} missing; camera presets will be unavailable")

    # 1. UDP chunk size
    s = re.sub(r"^CAM_FRAME_CHUNK = 60000", "CAM_FRAME_CHUNK = 8000", s, flags=re.M)

    # 2. truth log: remove whatever version is there, then insert v2
    s = s.replace(V1_INIT, "").replace(V1_RENDER, "")
    s = strip_block(s, "        # --- crazysim_macos truth log v2 (start) ---",
                    "        # --- crazysim_macos truth log v2 (end) ---")
    s = strip_block(s, "        # --- crazysim_macos truth write v2 (start) ---",
                    "        # --- crazysim_macos truth write v2 (end) ---")
    if ANCHOR_INIT not in s or ANCHOR_RENDER not in s:
        sys.exit("crazysim.py layout changed; truth-log patch not applied")
    s = s.replace(ANCHOR_INIT, ANCHOR_INIT + TRUTH_INIT, 1)
    s = s.replace(ANCHOR_RENDER, TRUTH_RENDER + ANCHOR_RENDER, 1)

    # 3. scripted scene motion
    s = strip_block(s, "# --- crazysim_macos scene motion (start) ---",
                    "# --- crazysim_macos scene motion (end) ---")
    s = s.replace(MOTION_CALL, "")
    if ANCHOR_MOTION_DEF not in s or ANCHOR_MJ_STEP not in s:
        sys.exit("crazysim.py layout changed; scene-motion patch not applied")
    s = s.replace(ANCHOR_MOTION_DEF, MOTION_DEF + ANCHOR_MOTION_DEF, 1)
    s = s.replace(ANCHOR_MJ_STEP, MOTION_CALL + ANCHOR_MJ_STEP, 1)

    # 4. camera sensor model: remove any previous insertion, then re-apply
    s = strip_block(s, CAM_START, CAM_END)
    s = restore_gray(s)
    if ANCHOR_INIT not in s or ANCHOR_GRAY not in s:
        sys.exit("crazysim.py layout changed; camera sensor patch not applied")
    s = s.replace(ANCHOR_INIT, ANCHOR_INIT + CAMERA_INIT, 1)
    s = s.replace(ANCHOR_GRAY, CAMERA_APPLY, 1)

    if s != orig:
        p.write_text(s)
        print(f"patched {p}")
    else:
        print(f"already patched {p}")


if __name__ == "__main__":
    main()
