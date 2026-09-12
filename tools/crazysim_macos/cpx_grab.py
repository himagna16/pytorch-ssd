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
  REHEARSAL    : --mock (same as --host 127.0.0.1 --port 5000) talks to
                 tools/real_frames/mock_streamer.py, which serves the same bytes
                 a real AI-deck serves. Use it to practise the whole session
                 without hardware:
                     python tools/real_frames/mock_streamer.py &
                     python cpx_grab.py --mock --n 5 --every 1
                 mock_streamer.py can also inject the things that go wrong on a
                 real link (--join-mid, --short-frame, --drop-after,
                 --stall-after, --image-format 1), so you can see what each
                 failure looks like here before it happens in the lab.

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

PROVENANCE - how to tell raw pixels from decoded-JPEG pixels
------------------------------------------------------------
A .jpg file announces its compression by its extension. A .png does not, and
--png / --bayer DECODE a JPEG frame and write it as .png - so the file extension
alone cannot tell you whether a frame's pixels ever went through JPEG. That
matters because a model score on JPEG-compressed pixels is not valid: the chip
runs on raw sensor pixels and never sees compression artefacts. Deciding it from
the extension gets that wrong exactly when --png or --bayer is used, which is
what the protocol tells the operator to do when the Bayer warning fires.

So every .png this tool writes carries a PNG text chunk recording where its
pixels came from, written at capture time:

    pixel_provenance   "raw"          pixels arrived as CPX format 0 and were
                                      never JPEG-compressed. The ONLY value that
                                      can be valid for scoring - but see
                                      bayer_demosaiced below: it is necessary,
                                      not sufficient.
                       "jpeg-decoded" pixels arrived as CPX format 1 and were
                                      JPEG-DECODED here into this .png
                       "jpeg"         (clip JSON only) the frame was kept as the
                                      camera's own .jpg bytes, not decoded
    cpx_image_format   "0" or "1", the format field the streamer sent
    bayer_demosaiced   "1" if --bayer averaged each 2x2 Bayer cell (and scaled
                                      the result back up), else "0". This is a
                                      LOSSY transform, so a frame with
                                      pixel_provenance "raw" AND
                                      bayer_demosaiced "1" is not the untouched
                                      sensor image either. A downstream tool
                                      deciding whether a frame is scoreable must
                                      test BOTH fields, not pixel_provenance
                                      alone.
    capture_tool       "cpx_grab.py"

Read one back with PIL (`Image.open(p).text["pixel_provenance"]`), or with
`exiftool -PNG:All`. .jpg files carry no chunk - their extension already says it,
and re-writing them would destroy the byte-for-byte copy of what the camera sent.

The clip JSON repeats it for the clip as a whole: "pixel_provenance" (the sorted
set over the saved frames), "provenance_counts" (each value and how many frames),
"raw_frames" and "jpeg_decoded_frames".

A .png with NO pixel_provenance chunk was recorded before this field existed;
it is unknown, not raw. Check the clip JSON's "formats" field, or re-record.

Frames go to --out; the default is sim_frames/ with --sim,
~/drone_frames/rehearsal-<today>/ with --mock, and ~/drone_frames/<today>/ for a
real AI-deck (keep real images outside git).
A labelled clip refuses to overwrite an earlier recording with the same labels;
use --take N+1.

Examples:
  # 30 s clip, teammate p01 at 2.5 m, 15 deg left, normal room light
  python cpx_grab.py --seconds 30 --every 1 --dist 2.5 --bearing -15 --vis 1 \\
      --subject p01 --light room --out ~/drone_frames/2026-09-12
  # empty room
  python cpx_grab.py --seconds 30 --every 1 --vis 0 --subject empty --light room --out ...
  # rehearse the same clip against the mock streamer, no drone needed
  python cpx_grab.py --mock --seconds 30 --every 1 --dist 2.5 --bearing -15 --vis 1 \\
      --subject p01 --light room
  # simulator, old behavior (30 frames, every 5th)
  python cpx_grab.py --sim --n 30
"""
import argparse, io, json, os, re, socket, struct, sys, time
import numpy as np
from PIL import Image, PngImagePlugin

CPX_F_APP, IMG_MAGIC = 5, 0xBC
REAL_HOST, REAL_PORT = "192.168.4.1", 5000
SIM_HOST, SIM_PORT = "127.0.0.1", 5050
MOCK_HOST, MOCK_PORT = "127.0.0.1", 5000   # tools/real_frames/mock_streamer.py
LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1")
NAME_RE = re.compile(r"^[A-Za-z0-9-]+$")
MAX_SHORT_FRAME_PRINTS = 5   # then just count them, so a bad link cannot spam


class ClipDeadline(Exception):
    """The --seconds clip length ran out while waiting for / receiving an image."""


class WriteFailed(Exception):
    """Saving a frame failed (disk full, folder removed, permissions)."""


class PacketReader:
    """Buffered reader for the CPX wire protocol.

    Holds whatever has arrived in an internal buffer, so a socket timeout in the
    middle of a packet does not throw the received bytes away: the next call
    carries on where this one stopped. Reading exactly 4 bytes and then exactly
    `length - 2` bytes (what this tool used to do) loses everything it is
    holding whenever recv times out, and the stream is then silently one
    fragment out of step for the rest of the session.
    """

    def __init__(self, sock):
        self.sock = sock
        self.buf = bytearray()

    def _fill_to(self, n):
        while len(self.buf) < n:
            chunk = self.sock.recv(max(4096, n - len(self.buf)))
            if not chunk:
                raise ConnectionError("peer closed the connection")
            self.buf.extend(chunk)

    def packet(self):
        """(function, data) for the next CPX packet. Blocks until it is complete."""
        self._fill_to(4)
        length, _route, func = struct.unpack("<HBB", self.buf[:4])
        if length < 2:
            # len counts route+func, so anything under 2 means we are reading
            # something that is not a CPX stream (wrong port, wrong firmware).
            raise ConnectionError(f"not a CPX stream: packet length field {length} (< 2)")
        end = 4 + length - 2
        self._fill_to(end)
        data = bytes(self.buf[4:end])
        del self.buf[:end]
        return func & 0x3F, data


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


def recv_packet_by(r, deadline, sock_timeout):
    """r.packet(), but give up with ClipDeadline once time.time() passes `deadline`."""
    if deadline is None:
        return r.packet()
    left = deadline - time.time()
    if left <= 0:
        raise ClipDeadline()
    r.sock.settimeout(max(0.05, min(sock_timeout, left)))
    try:
        return r.packet()
    except socket.timeout:
        if time.time() >= deadline:
            raise ClipDeadline()
        raise


def recv_image(r, deadline=None, sock_timeout=10.0, stats=None):
    """Block until one complete image arrives. Returns (w, h, depth, fmt, payload bytes).

    Raises ClipDeadline when `deadline` (unix time) passes first.
    Counts images that arrived cut short in stats["short"] (see note below)."""
    hdr, payload = None, bytearray()
    while True:
        if hdr is None:
            func, data = recv_packet_by(r, deadline, sock_timeout)
            hdr = parse_header(data) if func == CPX_F_APP else None
            if hdr is None:
                continue  # not a header: keep scanning
            payload = bytearray(data[11:])  # normally empty; tolerate data after the header
        w, h, depth, fmt, size = hdr
        restart = None
        while len(payload) < size:
            f2, d2 = recv_packet_by(r, deadline, sock_timeout)
            if f2 != CPX_F_APP:
                continue
            # A new image header showing up mid-payload means the image we are
            # filling was cut short (a chunk the streamer never sent, or the
            # GAP8 restarting its stream). Drop the partial image: splicing the
            # head of one frame onto the tail of the next makes a picture that
            # is half one scene and half another, and nothing downstream - not
            # the scorer, not a human skimming the folder - can tell.
            # Any packet is checked, not only an 11-byte one: the GAP8 sends the
            # header alone, but a header packet that carries its first pixels
            # would otherwise be appended as payload. False positives need ~11
            # specific bytes of pixel data to line up, which parse_header's
            # sanity checks make vanishingly unlikely.
            nxt = parse_header(d2)
            if nxt is not None:
                restart = (nxt, bytearray(d2[11:]))
                break
            payload.extend(d2)
        if restart is not None:
            if stats is not None:
                stats["short"] += 1
                if stats["short"] <= MAX_SHORT_FRAME_PRINTS:
                    print(f"warning: frame cut short ({len(payload)}/{size} bytes "
                          f"arrived); dropped, not saved")
                    if stats["short"] == MAX_SHORT_FRAME_PRINTS:
                        print("warning: further cut-short frames will be counted, "
                              "not printed")
            hdr, payload = restart
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


PROVENANCE_RAW = "raw"              # CPX format 0: never JPEG-compressed (--bayer
                                    # can still have averaged the 2x2 cells; that is
                                    # recorded separately in bayer_demosaiced)
PROVENANCE_JPEG = "jpeg"            # CPX format 1 kept as the camera's own .jpg bytes
PROVENANCE_JPEG_PNG = "jpeg-decoded"   # CPX format 1 DECODED into a .png - the blind spot
SCOREABLE_PROVENANCE = PROVENANCE_RAW  # anything else has been through compression.
                                       # Necessary, not sufficient: also check the
                                       # bayer_demosaiced chunk / the clip JSON "bayer".


def pixel_provenance(fmt, decoded):
    """What happened to the pixels of the file about to be written.

    `decoded` is True when the frame is being written as a decoded image rather
    than as the bytes that came off the wire. The whole point of recording this
    is that a .png saved by --png/--bayer from a JPEG frame looks exactly like a
    raw capture to anything reading filenames.
    """
    if fmt == 0:
        return PROVENANCE_RAW
    if fmt == 1:
        return PROVENANCE_JPEG_PNG if decoded else PROVENANCE_JPEG
    return f"format{fmt}-decoded" if decoded else f"format{fmt}"


def png_provenance(fmt, bayer):
    """The PNG text chunk to stamp into a saved frame. See the module docstring."""
    info = PngImagePlugin.PngInfo()
    info.add_text("pixel_provenance", pixel_provenance(fmt, decoded=True))
    info.add_text("cpx_image_format", str(fmt))
    info.add_text("bayer_demosaiced", "1" if bayer else "0")
    info.add_text("capture_tool", "cpx_grab.py")
    return info


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
    if a.sim and a.mock:
        ap.error("--sim (CrazySim bridge) and --mock (mock_streamer.py) are different "
                 "things to connect to; pick one")


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


def where_to_connect(a):
    """(host, port) from --host/--port/--sim/--mock."""
    if a.host is not None:
        host = a.host
    elif a.sim:
        host = SIM_HOST
    elif a.mock:
        host = MOCK_HOST
    else:
        host = REAL_HOST
    if a.port is not None:
        port = a.port
    elif a.mock:
        port = MOCK_PORT
    elif a.sim or host in LOCAL_HOSTS:
        port = SIM_PORT
    else:
        port = REAL_PORT
    return host, port


def connect_hint(a, host, port):
    """What to try when the connection fails, for this host/port."""
    if a.mock or (host in LOCAL_HOSTS and port == MOCK_PORT):
        return ("Is the mock streamer running?  "
                f"python tools/real_frames/mock_streamer.py --port {port}")
    if port == SIM_PORT:
        return "Is the simulator running in camera mode (./run_sim.sh camera)?"
    if host in LOCAL_HOSTS:
        return (f"Nothing is listening on this machine's port {port}. For a real AI-deck "
                "drop --host (it defaults to the deck's access point), for the simulator "
                "use --sim, for a rehearsal use --mock.")
    return ("Is this computer joined to the AI-deck's WiFi network, and is the drone "
            "powered on? For the simulator use --sim, to rehearse without hardware use --mock.")


def default_out(a, host):
    if a.mock:
        return os.path.join("~", "drone_frames", "rehearsal-" + time.strftime("%Y-%m-%d"))
    if a.sim or host in LOCAL_HOSTS:
        return "sim_frames"
    return os.path.join("~", "drone_frames", time.strftime("%Y-%m-%d"))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default=None, help=f"default {REAL_HOST} (the AI-deck access point)")
    ap.add_argument("--port", type=int, default=None,
                    help=f"default {REAL_PORT} on real hardware, {SIM_PORT} when --host is 127.0.0.1/localhost")
    ap.add_argument("--sim", action="store_true", help=f"simulator: --host {SIM_HOST} --port {SIM_PORT}")
    ap.add_argument("--mock", action="store_true",
                    help=f"rehearsal without hardware: --host {MOCK_HOST} --port {MOCK_PORT}, "
                         "where tools/real_frames/mock_streamer.py serves fake AI-deck frames")
    ap.add_argument("--n", type=int, default=None,
                    help="frames to save (default 30, or unlimited when --seconds is given)")
    ap.add_argument("--seconds", type=float, default=None, help="stop after this many seconds (clip length)")
    ap.add_argument("--every", type=int, default=5, help="save every Nth frame (1 = all)")
    ap.add_argument("--out", default=None,
                    help="output folder (default: sim_frames with --sim, "
                         "~/drone_frames/rehearsal-<today> with --mock, else ~/drone_frames/<today>)")
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

    host, port = where_to_connect(a)
    n_max = a.n if a.n is not None else (None if a.seconds else 30)

    if a.out is None:
        a.out = default_out(a, host)
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
        sys.exit(f"could not connect to tcp://{host}:{port}: {e}\n{connect_hint(a, host, port)}")
    s_reader = PacketReader(s)
    print(f"connected to tcp://{host}:{port}" + (f"  labels: {stem}" if stem else ""))

    # Only after connecting: no empty folders from failed attempts.
    out_existed = os.path.isdir(a.out)
    try:
        os.makedirs(a.out, exist_ok=True)
    except OSError as e:
        s.close()
        sys.exit(f"cannot create the output folder {a.out}: {e}\n"
                 "Pick a folder you can write to, e.g. --out ~/drone_frames/<date>")
    print(f"saving to {os.path.abspath(a.out)}")

    seen = saved = bad = 0
    stats = {"short": 0}
    formats, sizes = set(), set()
    provenances = {}                 # pixel_provenance -> how many frames saved
    warned_jpeg = warned_jpeg_png = False
    stop_reason = "reached the requested number of frames"
    t0 = t_last = time.time()
    deadline = t0 + a.seconds if a.seconds is not None else None
    try:
        while n_max is None or saved < n_max:
            w, h, depth, fmt, payload = recv_image(s_reader, deadline, a.timeout, stats)
            seen += 1
            t_last = time.time()
            if fmt == 1 and not warned_jpeg:
                # Not only for labelled clips: the protocol's first bench check
                # is an unlabelled --n 5 run, and catching a JPEG-flashed deck
                # there is the whole point of that check.
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
            prov = pixel_provenance(fmt, decoded=not keep_jpeg)
            if prov == PROVENANCE_JPEG_PNG and not warned_jpeg_png:
                # The trap this guards: --png/--bayer decode a JPEG frame and
                # write it as .png, so the compression is invisible to anything
                # that judges a frame by its extension - which is how the scorer
                # decides. Say it here, where it can still be fixed by reflashing.
                warned_jpeg_png = True
                print("WARNING: these frames arrived as JPEG and are being written as .png "
                      f"(--{'bayer' if a.bayer else 'png'}).\n"
                      "         Their pixels have been through JPEG compression, so they are "
                      "NOT valid for scoring,\n"
                      "         and the .png extension does not show it. Each file records "
                      "pixel_provenance=\n"
                      f"         \"{PROVENANCE_JPEG_PNG}\" in a PNG text chunk; check it "
                      "before you trust any score.\n"
                      "         To get scoreable frames: set the streamer to raw (format 0) "
                      "and re-record.")
            try:
                if keep_jpeg:
                    with open(path, "wb") as f:
                        f.write(payload)  # exact bytes from the camera
                else:
                    img.save(path, pnginfo=png_provenance(fmt, a.bayer))
            except OSError as e:
                raise WriteFailed(f"cannot write {path}: {e}")
            provenances[prov] = provenances.get(prov, 0) + 1
            saved += 1
            fps = seen / max(time.time() - t0, 1e-6)
            print(f"saved {path}  ({w}x{h} depth={depth} fmt={fmt}, stream ~{fps:.1f} fps)")
    except ClipDeadline:
        stop_reason = "the --seconds clip length ran out"
    except socket.timeout:
        stop_reason = f"no data for {a.timeout:g} s"
        print(f"no data for {a.timeout:g} s; stopping (is the camera streaming?)")
        if seen == 0 and host in LOCAL_HOSTS and port == MOCK_PORT:
            # macOS' AirPlay Receiver (ControlCenter) also listens on TCP 5000
            # and accepts connections without ever sending anything, so a dead
            # mock looks like a live camera that has gone quiet.
            print("hint: the connection was accepted but nothing was sent. On macOS, "
                  "AirPlay Receiver listens on port 5000 too and answers silently. "
                  "Start tools/real_frames/mock_streamer.py, or turn AirPlay Receiver "
                  "off in System Settings > General > AirDrop & Handoff, or use --port.")
    except ConnectionError as e:
        stop_reason = f"the connection dropped ({e})"
        print(f"connection lost: {e}")
    except KeyboardInterrupt:
        stop_reason = "you stopped it (Ctrl-C)"
        print("stopped by user")
    except WriteFailed as e:
        stop_reason = f"a frame could not be written ({e})"
        print(f"stopping: {e}")
    finally:
        s.close()
    wall = time.time() - t0
    print(f"done: {saved} saved, {seen} received, {bad} undecodable, "
          f"{stats['short']} cut short, {wall:.1f} s, ~{seen / max(wall, 1e-6):.1f} fps")
    # Say it plainly when the clip is not what was asked for. A short clip that
    # nobody notices is a clip that gets scored as if it were complete.
    if n_max is not None and saved < n_max:
        print(f"WARNING: asked for {n_max} frames, got {saved} - {stop_reason}.")
    elif a.seconds is not None and wall < a.seconds - 0.5:
        print(f"WARNING: asked for a {a.seconds:g} s clip, got {wall:.1f} s - {stop_reason}.")
    quiet = time.time() - t_last
    if a.seconds is not None and seen and quiet > max(2.0, 0.2 * a.seconds):
        # A clip that runs its full length but goes silent halfway is still a
        # bad clip; without this it just looks like a low frame rate.
        print(f"WARNING: nothing arrived for the last {quiet:.1f} s of this "
              f"{a.seconds:g} s clip - {saved} frames in total. Check the link "
              "before recording the rest.")
    if stats["short"]:
        print(f"WARNING: {stats['short']} frame(s) arrived cut short and were dropped. "
              "A few is a flaky link; a lot means the deck or the WiFi is struggling.")
    not_raw = sum(n for p, n in provenances.items() if p != SCOREABLE_PROVENANCE)
    if not_raw:
        kinds = ", ".join(f"{p} x{n}" for p, n in sorted(provenances.items())
                          if p != SCOREABLE_PROVENANCE)
        print(f"WARNING: {not_raw} of the {saved} saved frames are not raw pixels ({kinds}).\n"
              "         The chip runs the model on raw pixels, so these are not valid for "
              "scoring, whatever\n         their file extension says. Each .png records its "
              "pixel_provenance in a PNG text chunk.")
    if stem and saved:
        meta = {"labels": stem, "host": host, "port": port, "saved": saved, "received": seen,
                "undecodable": bad, "short": stats["short"], "seconds": round(wall, 2),
                "stream_fps": round(seen / max(wall, 1e-6), 2),
                "every": a.every, "formats": sorted(formats), "sizes": sorted(sizes), "bayer": a.bayer,
                # Provenance of the saved pixels. "formats" above is the wire format
                # of every frame RECEIVED; these describe the frames actually WRITTEN,
                # which is what a downstream tool has to reason about.
                "pixel_provenance": sorted(provenances),
                "provenance_counts": dict(sorted(provenances.items())),
                "raw_frames": provenances.get(PROVENANCE_RAW, 0),
                "jpeg_decoded_frames": provenances.get(PROVENANCE_JPEG_PNG, 0),
                "stopped_because": stop_reason, "mock": bool(a.mock),
                "started_unix": round(t0, 3)}
        try:
            with open(os.path.join(a.out, f"{stem}_clip.json"), "w") as f:
                json.dump(meta, f, indent=2)
        except OSError as e:
            print(f"warning: could not write the clip JSON: {e}")
    if saved == 0:
        if not out_existed:
            try:
                os.rmdir(a.out)   # only removes it if it is still empty
            except OSError:
                pass
        sys.exit(1)


if __name__ == "__main__":
    main()
