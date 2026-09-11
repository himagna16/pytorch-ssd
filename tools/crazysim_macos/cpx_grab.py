#!/usr/bin/env python3
"""Grab AI-deck camera frames from CrazySim's CPX bridge (or a real AI-deck).

Speaks the CPX-over-TCP protocol directly: each wire packet is
[len:u16 LE][route:u8][func:u8][data], len counting route+func+data.
An image is one APP packet carrying an 11-byte header
<BHHBBI = magic 0xBC, width, height, depth, format, size>, then APP
packets of raw 8-bit grayscale pixels until `size` bytes arrive.

Usage: python3 cpx_grab.py [--host 127.0.0.1] [--port 5050] [--n 30] [--every 5] [--out sim_frames]
"""
import argparse, os, socket, struct, time
from PIL import Image

CPX_F_APP, IMG_MAGIC = 5, 0xBC

def recv_exact(s, n):
    buf = bytearray()
    while len(buf) < n:
        c = s.recv(n - len(buf))
        if not c:
            raise ConnectionError("peer closed")
        buf.extend(c)
    return bytes(buf)

def recv_packet(s):
    length, route, func = struct.unpack("<HBB", recv_exact(s, 4))
    return func & 0x3F, recv_exact(s, length - 2)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=5050)
    ap.add_argument("--n", type=int, default=30, help="frames to save")
    ap.add_argument("--every", type=int, default=5, help="save every Nth frame")
    ap.add_argument("--out", default="sim_frames")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    s = socket.create_connection((a.host, a.port), timeout=10)
    print(f"connected to tcp://{a.host}:{a.port}")
    seen = saved = 0
    t0 = time.time()
    while saved < a.n:
        func, data = recv_packet(s)
        if func != CPX_F_APP or len(data) < 11 or data[0] != IMG_MAGIC:
            continue
        _, w, h, depth, fmt, size = struct.unpack("<BHHBBI", data[:11])
        pix = bytearray()
        while len(pix) < size:
            f2, d2 = recv_packet(s)
            if f2 == CPX_F_APP:
                pix.extend(d2)
        seen += 1
        if seen % a.every:
            continue
        path = os.path.join(a.out, f"frame_{seen:05d}_{time.time():.3f}.png")
        Image.frombytes("L", (w, h), bytes(pix[:w * h])).save(path)
        saved += 1
        fps = seen / max(time.time() - t0, 1e-6)
        print(f"saved {path}  ({w}x{h} depth={depth} fmt={fmt}, stream ~{fps:.1f} fps)")
    s.close()

if __name__ == "__main__":
    main()
