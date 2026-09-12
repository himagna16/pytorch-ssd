#!/usr/bin/env python3
"""Inference sidecar for the 'chip' perception backend: serves the GAP8's
integer network (model_id_dory.onnx) over a unix socket, one request per frame.

Why a separate process: the flight code needs cflib + mujoco + torch, which live
in trainenv, and onnxruntime lives only in doryenv. Nothing may be installed, so
the two cannot share an interpreter. perception_backends.ChipPerception starts
this script under the doryenv python, talks to it over a unix socket in the
scratch dir, and stops it at the end of the flight.

Wire protocol, little-endian, one request per camera frame:
  request   16384 bytes = the 128x128 uint8 network input (already preprocessed
            by the caller with the firmware's preprocess.c port, so the staging
            stays in one place and this process stays a pure model runner)
  response  14 int32 (56 B) = the chip's raw output domain, then
            1 float64 (8 B) = this process's own inference time in ms
  a 0-byte read means the client went away and the server exits.

Transport: normally the parent hands us one end of a socketpair on an inherited
fd (--fd), so there is no socket path at all -- macOS caps AF_UNIX paths at ~104
bytes and the scratch directory is longer than that. --socket <path> is kept for
running this server by hand; it binds from the socket's own directory so only the
basename goes into sun_path.

The session is created exactly as the release's own scorer creates it
(ORT_DISABLE_ALL, CPU provider), so the numbers are the release's numbers.
Run under doryenv:
  doryenv/bin/python3 chip_infer_server.py --onnx <model_id_dory.onnx> --socket <path>
"""
import argparse, hashlib, json, os, socket, struct, sys, time
from pathlib import Path

import numpy as np

N_OUT = 14
RESP_FMT = "<14i d"          # 14 int32 + 1 float64 = 64 bytes


def die(msg: str) -> "None":
    """Fail loudly: the caller surfaces this line verbatim."""
    print(f"chip_infer_server: {msg}", file=sys.stderr, flush=True)
    raise SystemExit(2)


def recv_exact(conn, n: int) -> bytes | None:
    """Read exactly n bytes; None if the peer closed cleanly first."""
    buf = bytearray()
    while len(buf) < n:
        chunk = conn.recv(n - len(buf))
        if not chunk:
            return None if not buf else die("client closed mid-request")
        buf += chunk
    return bytes(buf)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--onnx", type=Path, required=True)
    ap.add_argument("--socket", type=Path,
                    help="standalone mode: bind this unix socket path")
    ap.add_argument("--fd", type=int,
                    help="serve on this already-connected socket fd (how perception_backends starts us)")
    ap.add_argument("--threads", type=int, default=2,
                    help="ORT intra-op threads (the release's scorer used 2)")
    a = ap.parse_args()

    if (a.socket is None) == (a.fd is None):
        die("pass exactly one of --fd (normal) or --socket (standalone)")
    if not a.onnx.is_file():
        die(f"ONNX model not found: {a.onnx}")
    try:
        import onnxruntime as ort
    except Exception as e:  # doryenv missing / wrong interpreter
        die(f"onnxruntime is not importable in this interpreter ({sys.executable}): {e}")

    so = ort.SessionOptions()
    so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_DISABLE_ALL
    so.intra_op_num_threads = a.threads
    so.inter_op_num_threads = 1
    sess = ort.InferenceSession(str(a.onnx), so, providers=["CPUExecutionProvider"])
    inp, outp = sess.get_inputs()[0], sess.get_outputs()[0]
    shape = [d if isinstance(d, int) else 1 for d in inp.shape]
    if len(shape) != 4 or shape[0] != 1 or shape[1] != 1:
        die(f"expected a [1,1,H,W] input, got {inp.shape}")
    h, w = int(shape[2]), int(shape[3])
    n_in = h * w
    iname, oname = inp.name, outp.name

    def run(u8: np.ndarray) -> np.ndarray:
        x = u8.astype(np.float32).reshape(1, 1, h, w)
        return np.asarray(sess.run([oname], {iname: x})[0]).reshape(-1)

    warm = run(np.zeros(n_in, np.uint8))
    if warm.size != N_OUT:
        die(f"expected {N_OUT} outputs, got {warm.size}")

    def serve(conn):
        with conn:
            while True:
                req = recv_exact(conn, n_in)
                if req is None:
                    return                         # client closed
                t0 = time.perf_counter()
                out = run(np.frombuffer(req, np.uint8))
                dt_ms = (time.perf_counter() - t0) * 1000.0
                # The GAP8 emits int32; ORT returns the same values as floats.
                vals = np.clip(np.rint(out), -2 ** 31, 2 ** 31 - 1).astype(np.int64)
                conn.sendall(struct.pack(RESP_FMT, *[int(v) for v in vals], dt_ms))

    ready = {"ready": True, "onnx": str(a.onnx),
             "onnx_sha1": hashlib.sha1(a.onnx.read_bytes()).hexdigest(),
             "input_hw": [h, w], "n_out": N_OUT,
             "onnxruntime": ort.__version__, "python": sys.executable,
             "threads": a.threads}

    if a.fd is not None:
        conn = socket.socket(fileno=a.fd)
        print(json.dumps({**ready, "transport": "fd"}), flush=True)
        try:
            serve(conn)
        except KeyboardInterrupt:
            pass
        return

    # Standalone: bind from the socket's directory so only the basename is used.
    sock_path = a.socket
    sock_path.parent.mkdir(parents=True, exist_ok=True)
    os.chdir(sock_path.parent)
    name = sock_path.name
    if os.path.exists(name):
        os.unlink(name)
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(name)
    srv.listen(1)
    print(json.dumps({**ready, "transport": "socket", "socket": str(sock_path)}), flush=True)
    try:
        while True:
            conn, _ = srv.accept()
            serve(conn)
    except KeyboardInterrupt:
        pass
    finally:
        srv.close()
        try:
            os.unlink(name)
        except OSError:
            pass


if __name__ == "__main__":
    main()
