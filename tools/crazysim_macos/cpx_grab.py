#!/usr/bin/env python3
"""Grab AI-deck camera frames from a real AI-deck (WiFi) or CrazySim's CPX bridge.

Speaks the CPX-over-TCP protocol directly: each wire packet is
[len:u16 LE][route:u8][func:u8][data], len counting route+func+data.
An image is one APP packet carrying an 11-byte header
<BHHBBI = magic 0xBC, width, height, depth, format, size>, then APP
packets of payload until `size` bytes arrive. This matches Bitcraze's
wifi-img-streamer example on the GAP8:
  format 0 = raw 8-bit pixels (grayscale camera; Bayer mosaic on the color camera)
  format 1 = JPEG (decoded here with PIL)

Where to connect:
  real AI-deck : join the AI-deck's WiFi access point, then connect to
                 192.168.4.1:5000 (the defaults)
  simulator    : --sim  (same as --host 127.0.0.1 --port 5050; start the sim
                 with ./run_sim.sh camera first)

Labels (optional) go into every filename so score_real_frames.py can read
them back later without a spreadsheet:
  d<metres>_b<degrees>_vis<0|1>_subj-<who>_light-<name>_take<k>_f<frame#>_t<unix time>.png
Bearing is measured from the drone: NEGATIVE = person on the drone's LEFT,
positive = right, 0 = straight ahead. Omit --dist/--bearing for an empty
scene (use --vis 0).

Raw frames are saved as .png (lossless). JPEG frames are saved byte-for-byte
as .jpg (no re-compression), unless --png or --bayer is given (then the decoded,
Bayer-converted gray image is saved as .png). For clips you plan to SCORE, set
the streamer to raw (format 0): the GAP8 model runs on raw pixels and never
sees JPEG artefacts.

Frames go to --out; the default is sim_frames/ with --sim and
~/drone_frames/<today>/ for a real AI-deck (keep real images outside git).
A labelled clip refuses to overwrite an earlier recording with the same labels;
use --take N+1.

Examples:
  # 30 s clip, teammate p01 at 2.5 m, 15 deg left, normal room light
  python cpx_grab.py --seconds 30 --every 1 --dist 2.5 --bearing -15 --vis 1 \\
      --subject p01 --light room --out ~/drone_frames/2026-09-12
  # empty room
  python cpx_grab.py --seconds 30 --every 1 --vis 0 --subject empty --light room --out ...
  # simulator, old behavior (30 frames, every 5th)
  python cpx_grab.py --sim --n 30
"""
import argparse, io, json, os, re, socket, struct, sys, time
import numpy as np
from PIL import Image

CPX_F_APP, IMG_MAGIC = 5, 0xBC
REAL_HOST, REAL_PORT = "192.168.4.1", 5000
SIM_HOST, SIM_PORT = "127.0.0.1", 5050
NAME_RE = re.compile(r"^[A-Za-z0-9-]+$")


def recv_exact(s, n):
    buf = bytearray()
    while len(buf) < n:
        c = s.recv(n - len(buf))
        if not c:
            raise ConnectionError("peer closed the connection")
        buf.extend(c)
    return bytes(buf)


def recv_packet(s):
    length, route, func = struct.unpack("<HBB", recv_exact(s, 4))
    return func & 0x3F, recv_exact(s, length - 2)


class ClipDeadline(Exception):
    """The --seconds clip length ran out while waiting for / receiving an image."""


MAX_SIDE = 1024  # the AI-deck camera is 324x244; anything above this is not a real header


def parse_header(data):
    """(w, h, depth, fmt, size) if `data` starts with a plausible image header, else None.

    A payload chunk can start with byte 0xBC too (pixel value 188), e.g. when we
    join the stream mid-image, so the fields are sanity-checked before trusting
    `size` (a bogus u32 size would otherwise swallow the stream for ever)."""
    if len(data) < 11 or data[0] != IMG_MAGIC:
        return None
    _, w, h, depth, fmt, size = struct.unpack("<BHHBBI", data[:11])
    if not (0 < w <= MAX_SIDE and 0 < h <= MAX_SIDE):
        return None
    if fmt == 0:  # raw 8-bit: GAP8 sends depth=1 (bytes/px), CrazySim depth=8 (bits/px)
        ok = depth in (1, 8) and size == w * h
    elif fmt == 1:  # JPEG: normally far smaller than raw; allow headroom for tiny frames
        ok = 0 < size <= 2 * w * h + 4096
    else:
        ok = False
    return (w, h, depth, fmt, size) if ok else None


def recv_packet_by(s, deadline, sock_timeout):
    """recv_packet, but give up with ClipDeadline once time.time() passes `deadline`."""
    if deadline is None:
        return recv_packet(s)
    left = deadline - time.time()
    if left <= 0:
        raise ClipDeadline()
    s.settimeout(max(0.05, min(sock_timeout, left)))
    try:
        return recv_packet(s)
    except socket.timeout:
        if time.time() >= deadline:
            raise ClipDeadline()
        raise


def recv_image(s, deadline=None, sock_timeout=10.0):
    """Block until one complete image arrives. Returns (w, h, depth, fmt, payload bytes).

    Raises ClipDeadline when `deadline` (unix time) passes first."""
    hdr = None
    while True:
        if hdr is None:
            func, data = recv_packet_by(s, deadline, sock_timeout)
            hdr = parse_header(data) if func == CPX_F_APP else None
            if hdr is None:
                continue  # not a header: keep scanning
            payload = bytearray(data[11:])  # normally empty; tolerate data after the header
        w, h, depth, fmt, size = hdr
        restart = None
        while len(payload) < size:
            f2, d2 = recv_packet_by(s, deadline, sock_timeout)
            if f2 != CPX_F_APP:
                continue
            # Both streamers send the 11-byte header in a packet of its own. One
            # showing up mid-payload means the previous image was cut short.
            if len(d2) == 11 and parse_header(d2):
                restart = parse_header(d2)
                break
            payload.extend(d2)
        if restart is not None:
            hdr, payload = restart, bytearray()
            continue
        return w, h, depth, fmt, bytes(payload[:size])


def bayer_to_gray(img):
    """Color AI-deck: average each 2x2 Bayer cell, then scale back to full size."""
    h, w = img.shape
    h2, w2 = h // 2 * 2, w // 2 * 2
    cells = img[:h2, :w2].astype(np.float32).reshape(h2 // 2, 2, w2 // 2, 2).mean(axis=(1, 3))
    return np.asarray(Image.fromarray(cells.astype(np.uint8)).resize((w, h), Image.BILINEAR))


def decode(w, h, depth, fmt, payload, bayer=False):
    """Return a PIL grayscale image, or raise ValueError with a readable reason."""
    if fmt == 0:
        # The GAP8 streamer sends depth=1 (bytes per pixel); CrazySim's bridge
        # sends depth=8 (bits per pixel). Both mean 8-bit pixels.
        if depth not in (1, 8):
            raise ValueError(f"raw frame with depth={depth}; only 8-bit pixels are supported")
        if len(payload) < w * h:
            raise ValueError(f"raw frame too short: {len(payload)} bytes for {w}x{h}")
        img = np.frombuffer(payload[:w * h], np.uint8).reshape(h, w)
        if bayer:
            img = bayer_to_gray(img)
        return Image.fromarray(img, "L")
    if fmt == 1:
        try:
            im = Image.open(io.BytesIO(payload))
            im.load()
        except Exception as e:  # truncated or corrupt JPEG
            raise ValueError(f"JPEG decode failed ({len(payload)} bytes): {e}")
        im = im.convert("L")
        if bayer:  # color camera streaming JPEG: the JPEG holds the gray Bayer mosaic
            im = Image.fromarray(bayer_to_gray(np.asarray(im)), "L")
        return im
    raise ValueError(f"unknown image format {fmt}")


def label_stem(a):
    """Filename prefix from the --dist/--bearing/--vis/--subject/--light/--take options ('' if none)."""
    parts = []
    if a.dist is not None:
        parts.append(f"d{a.dist:g}")
    if a.bearing is not None:
        parts.append(f"b{a.bearing:g}")
    if a.vis is not None:
        parts.append(f"vis{a.vis}")
    if a.subject:
        parts.append(f"subj-{a.subject}")
    if a.light:
        parts.append(f"light-{a.light}")
    if parts:
        parts.append(f"take{a.take}")
    return "_".join(parts)


def check_numbers(ap, a):
    if a.every < 1:
        ap.error(f"--every must be >= 1 (got {a.every})")
    if a.n is not None and a.n < 1:
        ap.error(f"--n must be >= 1 (got {a.n})")
    if a.seconds is not None and not a.seconds > 0:
        ap.error(f"--seconds must be > 0 (got {a.seconds:g})")
    if not a.timeout > 0:
        ap.error(f"--timeout must be > 0 (got {a.timeout:g})")
    if a.take < 1:
        ap.error(f"--take must be >= 1 (got {a.take})")


def existing_takes(out, stem):
    """Take numbers already recorded in `out` for these labels (take token swapped out)."""
    if not os.path.isdir(out):
        return set()
    base = re.escape(stem[: stem.rindex("_take")])
    rx = re.compile(rf"^{base}_take(\d+)_(?:f\d+_t[\d.]+\.(?:png|jpg)|clip\.json)$")
    return {int(m.group(1)) for m in map(rx.match, os.listdir(out)) if m}


def check_labels(ap, a):
    for name in ("subject", "light"):
        v = getattr(a, name)
        if v and not NAME_RE.match(v):
            ap.error(f"--{name} may only use letters, digits and '-' (got {v!r})")
    labelled = any(v is not None for v in (a.dist, a.bearing, a.vis)) or a.subject or a.light
    if labelled and a.vis is None:
        ap.error("labelled clips need --vis 1 (person/target in view) or --vis 0 (nobody in view)")
    if a.vis == 1 and (a.dist is None or a.bearing is None):
        ap.error("--vis 1 needs both --dist (metres) and --bearing (degrees, negative = left)")
    if a.vis == 0 and (a.dist is not None or a.bearing is not None):
        print("note: --vis 0 with a distance/bearing; they are saved but scoring treats the clip as empty")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default=None, help=f"default {REAL_HOST} (the AI-deck access point)")
    ap.add_argument("--port", type=int, default=None,
                    help=f"default {REAL_PORT} on real hardware, {SIM_PORT} when --host is 127.0.0.1/localhost")
    ap.add_argument("--sim", action="store_true", help=f"simulator: --host {SIM_HOST} --port {SIM_PORT}")
    ap.add_argument("--n", type=int, default=None,
                    help="frames to save (default 30, or unlimited when --seconds is given)")
    ap.add_argument("--seconds", type=float, default=None, help="stop after this many seconds (clip length)")
    ap.add_argument("--every", type=int, default=5, help="save every Nth frame (1 = all)")
    ap.add_argument("--out", default=None,
                    help="output folder (default: sim_frames with --sim, else ~/drone_frames/<today>)")
    ap.add_argument("--png", action="store_true", help="save JPEG frames as decoded grayscale .png too")
    ap.add_argument("--bayer", action="store_true",
                    help="frames come from the COLOR camera (Bayer mosaic): convert to gray "
                         "(JPEG frames are then saved as .png)")
    ap.add_argument("--timeout", type=float, default=10.0, help="socket timeout, seconds")
    g = ap.add_argument_group("labels (written into filenames)")
    g.add_argument("--dist", type=float, default=None, help="metres from the camera to the target")
    g.add_argument("--bearing", type=float, default=None,
                   help="degrees from straight ahead; NEGATIVE = drone's left, positive = right")
    g.add_argument("--vis", type=int, choices=(0, 1), default=None, help="1 = target in view, 0 = empty")
    g.add_argument("--subject", default="", help="who/what: p01, p02, plush, poster, empty ...")
    g.add_argument("--light", default="", help="lighting condition: room, dim, window ...")
    g.add_argument("--take", type=int, default=1, help="repeat number for the same configuration")
    a = ap.parse_args()
    check_numbers(ap, a)
    check_labels(ap, a)

    host = SIM_HOST if a.sim and a.host is None else (a.host or REAL_HOST)
    if a.port is not None:
        port = a.port
    elif a.sim or host in ("127.0.0.1", "localhost", "::1"):
        port = SIM_PORT
    else:
        port = REAL_PORT
    n_max = a.n if a.n is not None else (None if a.seconds else 30)

    if a.out is None:
        sim_like = a.sim or host in ("127.0.0.1", "localhost", "::1")
        a.out = "sim_frames" if sim_like else os.path.join("~", "drone_frames", time.strftime("%Y-%m-%d"))
    a.out = os.path.expanduser(a.out)
    stem = label_stem(a)
    if stem:
        takes = existing_takes(a.out, stem)
        if a.take in takes:
            sys.exit(f"{a.out} already has a recording with these labels, take {a.take} ({stem}).\n"
                     f"Use --take {max(takes) + 1} for a new recording (delete the old take's files first "
                     f"if you are replacing it), or pick another --out folder.")
    try:
        s = socket.create_connection((host, port), timeout=a.timeout)
    except OSError as e:
        hint = ("Is the simulator running in camera mode (./run_sim.sh camera)?" if port == SIM_PORT else
                "Is this computer joined to the AI-deck's WiFi network, and is the drone powered on? "
                "For the simulator use --sim.")
        sys.exit(f"could not connect to tcp://{host}:{port}: {e}\n{hint}")
    print(f"connected to tcp://{host}:{port}" + (f"  labels: {stem}" if stem else ""))

    os.makedirs(a.out, exist_ok=True)  # only after connecting: no empty folders from failed attempts
    print(f"saving to {os.path.abspath(a.out)}")

    seen = saved = bad = 0
    formats, sizes = set(), set()
    warned_jpeg = False
    t0 = time.time()
    deadline = t0 + a.seconds if a.seconds is not None else None
    try:
        while n_max is None or saved < n_max:
            w, h, depth, fmt, payload = recv_image(s, deadline, a.timeout)
            seen += 1
            if fmt == 1 and stem and not warned_jpeg:
                warned_jpeg = True
                print("warning: the camera is streaming JPEG. For clips you will score, set the streamer "
                      "to raw (format 0): the on-chip model never sees JPEG artefacts.")
            if seen % a.every:
                continue
            try:
                img = decode(w, h, depth, fmt, payload, a.bayer)
            except ValueError as e:
                bad += 1
                print(f"skipped frame {seen}: {e}")
                continue
            formats.add(fmt)
            sizes.add(img.size)
            base = f"{stem}_f{seen:05d}_t{time.time():.3f}" if stem else f"frame_{seen:05d}_{time.time():.3f}"
            keep_jpeg = fmt == 1 and not (a.png or a.bayer)
            path = os.path.join(a.out, base + (".jpg" if keep_jpeg else ".png"))
            if keep_jpeg:
                with open(path, "wb") as f:
                    f.write(payload)  # exact bytes from the camera
            else:
                img.save(path)
            saved += 1
            fps = seen / max(time.time() - t0, 1e-6)
            print(f"saved {path}  ({w}x{h} depth={depth} fmt={fmt}, stream ~{fps:.1f} fps)")
    except ClipDeadline:
        pass  # --seconds reached
    except socket.timeout:
        print(f"no data for {a.timeout:g} s; stopping (is the camera streaming?)")
    except ConnectionError as e:
        print(f"connection lost: {e}")
    except KeyboardInterrupt:
        print("stopped by user")
    finally:
        s.close()
    wall = time.time() - t0
    print(f"done: {saved} saved, {seen} received, {bad} undecodable, {wall:.1f} s, "
          f"~{seen / max(wall, 1e-6):.1f} fps")
    if stem and saved:
        meta = {"labels": stem, "host": host, "port": port, "saved": saved, "received": seen,
                "undecodable": bad, "seconds": round(wall, 2), "stream_fps": round(seen / max(wall, 1e-6), 2),
                "every": a.every, "formats": sorted(formats), "sizes": sorted(sizes), "bayer": a.bayer,
                "started_unix": round(t0, 3)}
        with open(os.path.join(a.out, f"{stem}_clip.json"), "w") as f:
            json.dump(meta, f, indent=2)
    if saved == 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
