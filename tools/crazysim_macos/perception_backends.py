#!/usr/bin/env python3
"""Swappable perception for the simulator: one interface, two backends.

Both the host follower (follow_person.py) and the GAP8 emulator
(gap8_emulator.py) call perception in exactly one place. This module is that
place, so a flight can be flown with the laptop's float model or with what the
chip actually computes, and nothing else changes.

    perc = make_perception("chip", unstable_root=..., ckpt=...)
    p = perc(gray_324x244)      # -> dict: the 14 outputs + the decoded values

Backends
  float   Exactly today's follow_person.Perception, imported and used verbatim
          (not a reimplementation), so results stay bit-identical and 'float'
          is the default everywhere. Staging: centre square crop of the frame,
          PIL BILINEAR resize to 128x128, /255, float PyTorch checkpoint.
  chip    What the GAP8 runs:
            1. the firmware's own preprocessing - a port of
               crazyflie_ssd/src/preprocess.c on champion-core8-integration:
               centre 244x244 crop of the 324x244 frame, then each output pixel
               is the rounded mean of the 2x2 camera block at the nearest-
               neighbour source index, giving 128x128 uint8;
            2. the integer network model_id_dory.onnx, whose 14 outputs are the
               chip's raw int32 domain; logits = raw * id_output_eps from that
               release's release_summary.json.
          onnxruntime is not installed in the flight environment, so the model
          runs in chip_infer_server.py under doryenv, reached over one end of an
          inherited socketpair; this class starts and stops that process. The
          socket has no filesystem path, so nothing is left behind and two runs
          can never collide.

Returned dict (same keys both backends, so callers need no branches):
    visibility_confidence, visibility_logit, x_value, x_bin_index,
    size_value, size_bucket_index, x_soft, raw (the 14 outputs as float logits)
The chip backend adds: raw_i32, vis_gate (the firmware's own integer
visibility test, raw[9] >= 4216) and infer_ms.

raw_i32 is onnxruntime's reproduction of the chip's integer output domain, NOT
a bit-exact copy of what the GAP8 computes. ORT evaluates model_id_dory.onnx in
float32 and chip_infer_server.py rounds with np.rint; on the release's own 96
scored images that rounding is safe (no value sits within 0.05 of a .5
boundary, so it can move a result by at most one count) but the rounded values
still differ from the release's DORY hardware-graph numbers on 58 of 96 images,
by up to 290 counts (0.058 in logit units). What survives is the decisions:
visibility gate 96/96, size bucket 96/96, x-bin 95/96. Bit-exact reproduction
of the chip's integers needs the DORY simulator, not onnxruntime.
With shadow="float" it also returns shadow_* keys holding what the float model
would have decided on the same frame, for per-frame agreement logging.
"""
import json, socket, struct, subprocess, sys, time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
DRONE_ROOT = HERE.parents[2]

BACKENDS = ("float", "chip")
DEFAULT_BACKEND = "float"

# The chip's release (champion). eps and the ONNX come from the same directory
# so they can never be mixed across releases.
DEFAULT_RELEASE = DRONE_ROOT / "pytorch_ssd_unstable/logs/plain_follow_prod_qat_v3"
DEFAULT_ONNX = DEFAULT_RELEASE / "quant_eval/model_id_dory.onnx"
DEFAULT_RELEASE_SUMMARY = DEFAULT_RELEASE / "release_summary.json"
DEFAULT_DORY_PYTHON = DRONE_ROOT / "doryenv/bin/python3"

NET_W = NET_H = 128
N_OUT = 14
RESP_FMT = "<14i d"
RESP_LEN = struct.calcsize(RESP_FMT)
# app_config.h on champion-core8-integration, for this model's eps.
VIS_ENTER_RAW = 4216
XBIN9_CENTERS = np.array([-1.0 + (2 * i + 1) / 9.0 for i in range(9)], np.float64)


def firmware_preprocess(gray: np.ndarray) -> np.ndarray:
    """Port of crazyflie_ssd/src/preprocess.c (champion-core8-integration).

    Centre square crop, then each of the 128x128 output pixels is the rounded
    mean of the 2x2 camera block starting at the nearest-neighbour source pixel,
    clamped at the crop's last row/column. Integer arithmetic throughout, so
    this is exact against the C, not an approximation of it.
    """
    if gray.ndim != 2:
        raise ValueError(f"expected a 2-D grayscale frame, got shape {gray.shape}")
    cam_h, cam_w = gray.shape
    crop = min(cam_w, cam_h)
    crop_x, crop_y = (cam_w - crop) // 2, (cam_h - crop) // 2
    crop_x_last, crop_y_last = crop_x + crop - 1, crop_y + crop - 1

    ys = crop_y + (np.arange(NET_H) * crop) // NET_H
    xs = crop_x + (np.arange(NET_W) * crop) // NET_W
    ys1 = np.minimum(ys + 1, crop_y_last)   # C: (src_y < crop_y_last) ? src_y+1 : src_y
    xs1 = np.minimum(xs + 1, crop_x_last)

    g = gray.astype(np.uint32)
    s = (g[np.ix_(ys, xs)] + g[np.ix_(ys, xs1)] +
         g[np.ix_(ys1, xs)] + g[np.ix_(ys1, xs1)])
    return ((s + 2) >> 2).astype(np.uint8)      # C: (uint8_t)((sum + 2u) >> 2)


def _decode_from_logits(logits: np.ndarray) -> dict:
    """utils/follow_task.decode_follow_outputs for the xbin9_size_bucket4 head,
    plus follow_person's probability-weighted bearing. argmax takes the first
    maximum, like torch.argmax and follow_argmax_i32."""
    x_logits = logits[:9]
    x_bin = int(np.argmax(x_logits))
    size_bucket = int(np.argmax(logits[10:14]))
    vis_logit = float(logits[9])
    e = np.exp(x_logits - x_logits.max())
    prob = e / e.sum()
    return {
        "visibility_logit": vis_logit,
        "visibility_confidence": float(1.0 / (1.0 + np.exp(-vis_logit))),
        "x_bin_index": float(x_bin),
        "x_value": float(XBIN9_CENTERS[x_bin]),
        "x_soft": float((prob * XBIN9_CENTERS).sum()),
        "size_bucket_index": float(size_bucket),
        "size_value": float((size_bucket + 0.5) / 4.0),
    }


class FloatPerception:
    """Today's perception, unchanged: follow_person.Perception used verbatim."""

    name = "float"

    def __init__(self, unstable_root: Path, ckpt: Path):
        from follow_person import Perception      # deferred: follow_person imports this module
        self._p = Perception(Path(unstable_root), Path(ckpt))
        self.info = {"backend": "float", "ckpt": str(ckpt), "head": self._p.head}

    def __call__(self, gray: np.ndarray) -> dict:
        return self._p(gray)

    def close(self):
        pass


class ChipPerception:
    """The firmware's preprocessing + the chip's integer network."""

    name = "chip"

    def __init__(self, onnx: Path = DEFAULT_ONNX, release_summary: Path | None = None,
                 dory_python: Path = DEFAULT_DORY_PYTHON,
                 shadow: str | None = None, unstable_root: Path | None = None,
                 ckpt: Path | None = None, start_timeout: float = 120.0):
        onnx = Path(onnx)
        dory_python = Path(dory_python)
        summary = Path(release_summary) if release_summary else onnx.parent.parent / "release_summary.json"
        if not onnx.is_file():
            raise RuntimeError(
                f"chip backend: ONNX model not found at {onnx}. This is the chip's network from the "
                f"release; without it the chip backend cannot run. Check the release directory.")
        if not dory_python.is_file():
            raise RuntimeError(
                f"chip backend: doryenv python not found at {dory_python}. onnxruntime lives only in "
                f"doryenv and nothing may be installed, so the chip backend needs it. "
                f"Pass --chip-python to point at it.")
        if not summary.is_file():
            raise RuntimeError(
                f"chip backend: release_summary.json not found at {summary}; it carries id_output_eps, "
                f"the output quantum that turns the chip's integers into logits.")
        try:
            self.eps = float(json.loads(summary.read_text())["id_output_eps"]["value"])
        except Exception as e:
            raise RuntimeError(f"chip backend: could not read id_output_eps from {summary}: {e}") from e

        # One end of a socketpair goes to the child on an inherited fd: no path,
        # so no 104-byte AF_UNIX limit and nothing to clean up.
        self._sock, child = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        server = HERE / "chip_infer_server.py"
        self._proc = subprocess.Popen(
            [str(dory_python), str(server), "--onnx", str(onnx), "--fd", str(child.fileno())],
            pass_fds=(child.fileno(),),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        child.close()
        self.server_info = self._await_ready(start_timeout)

        self._shadow = None
        if shadow == "float":
            if unstable_root is None or ckpt is None:
                raise RuntimeError("chip backend: shadow='float' needs unstable_root and ckpt")
            self._shadow = FloatPerception(unstable_root, ckpt)
        self.info = {"backend": "chip", "onnx": str(onnx), "eps": self.eps,
                     "shadow": shadow or "none", **self.server_info}

    def _await_ready(self, timeout: float) -> dict:
        """Wait for the server's ready line. stdout is drained on a thread so a
        server that hangs while loading times out instead of blocking forever."""
        import queue, threading
        q: "queue.Queue[str | None]" = queue.Queue()

        def pump():
            for line in self._proc.stdout:
                q.put(line)
            q.put(None)

        threading.Thread(target=pump, daemon=True).start()
        deadline = time.monotonic() + timeout
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                self.close()
                raise RuntimeError(
                    f"chip backend: the inference server did not become ready within {timeout:.0f} s.")
            try:
                line = q.get(timeout=min(left, 1.0))
            except queue.Empty:
                if self._proc.poll() is not None:
                    break
                continue
            if line is None:
                break
            line = line.strip()
            if not line:
                continue
            try:
                info = json.loads(line)
            except json.JSONDecodeError:
                continue
            if info.get("ready"):
                return info
        err = (self._proc.stderr.read() or "").strip()
        raise RuntimeError(
            f"chip backend: the inference server exited with code {self._proc.returncode} "
            f"before it was ready.\n{err}")

    def __call__(self, gray: np.ndarray) -> dict:
        net_in = firmware_preprocess(gray)
        t0 = time.perf_counter()
        try:
            self._sock.sendall(net_in.tobytes())
            buf = b""
            while len(buf) < RESP_LEN:
                chunk = self._sock.recv(RESP_LEN - len(buf))
                if not chunk:
                    raise ConnectionError("inference server closed the socket")
                buf += chunk
        except (OSError, ConnectionError) as e:
            err = ""
            if self._proc.poll() is not None:
                err = (self._proc.stderr.read() or "").strip()
            raise RuntimeError(f"chip backend: inference request failed ({e}). {err}") from e
        vals = struct.unpack(RESP_FMT, buf)
        raw_i32 = np.array(vals[:N_OUT], np.int64)
        logits = raw_i32.astype(np.float64) * self.eps

        res = _decode_from_logits(logits)
        res["raw"] = logits.astype(np.float32)          # the 14 outputs, as logits
        # ORT's float32 result rounded to the chip's integer domain - exact to a
        # rounding step, but not bit-identical to the DORY sim (see module docstring).
        res["raw_i32"] = raw_i32
        res["vis_gate"] = int(raw_i32[9] >= VIS_ENTER_RAW)
        res["infer_ms"] = float(vals[N_OUT])
        res["round_trip_ms"] = (time.perf_counter() - t0) * 1000.0
        if self._shadow is not None:
            s = self._shadow(gray)
            res.update({
                "shadow_conf": s["visibility_confidence"], "shadow_x_value": s["x_value"],
                "shadow_x_soft": s["x_soft"], "shadow_x_bin_index": s["x_bin_index"],
                "shadow_size_value": s["size_value"], "shadow_size_bucket_index": s["size_bucket_index"],
            })
        return res

    def close(self):
        for closer in (getattr(self, "_sock", None),):
            try:
                closer.close()
            except Exception:
                pass
        p = getattr(self, "_proc", None)
        if p is not None and p.poll() is None:
            p.terminate()
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()
        shadow = getattr(self, "_shadow", None)
        if shadow is not None:
            shadow.close()


def add_backend_args(ap, *, shadow: bool = True):
    """Opt-in flags. Every default reproduces today's behaviour exactly."""
    ap.add_argument("--backend", choices=BACKENDS, default=DEFAULT_BACKEND,
                    help="perception: 'float' (default, today's laptop model) or 'chip' "
                         "(the firmware's preprocessing + the chip's integer network)")
    ap.add_argument("--chip-onnx", type=Path, default=DEFAULT_ONNX,
                    help="chip backend: the integer network (default: the champion release)")
    ap.add_argument("--chip-python", type=Path, default=DEFAULT_DORY_PYTHON,
                    help="chip backend: python with onnxruntime (doryenv)")
    if shadow:
        ap.add_argument("--shadow", choices=("none", "float"), default="none",
                        help="also run this backend on every frame and log what it would have "
                             "decided (evidence only; it never steers)")


def make_perception(a=None, *, backend=None, unstable_root=None, ckpt=None, **kw):
    """Build the perception a run asked for. Pass the parsed args namespace, or
    the pieces by keyword. backend='float' returns today's Perception verbatim."""
    if a is not None:
        backend = backend or getattr(a, "backend", DEFAULT_BACKEND)
        unstable_root = unstable_root or getattr(a, "unstable_root", None)
        ckpt = ckpt or getattr(a, "ckpt", None)
        kw.setdefault("onnx", getattr(a, "chip_onnx", DEFAULT_ONNX))
        kw.setdefault("dory_python", getattr(a, "chip_python", DEFAULT_DORY_PYTHON))
        shadow = getattr(a, "shadow", "none")
        kw.setdefault("shadow", None if shadow in (None, "none") else shadow)
    backend = backend or DEFAULT_BACKEND
    if backend == "float":
        return FloatPerception(unstable_root, ckpt)
    if backend == "chip":
        return ChipPerception(unstable_root=unstable_root, ckpt=ckpt, **kw)
    raise ValueError(f"unknown backend {backend!r}; choose from {BACKENDS}")
