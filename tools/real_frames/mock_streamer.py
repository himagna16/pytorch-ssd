#!/usr/bin/env python3
"""Fake AI-deck camera stream, so cpx_grab.py can be rehearsed without a drone.

Serves the same bytes a real AI-deck serves: Bitcraze's `wifi-img-streamer`
speaking CPX over TCP. Point cpx_grab.py at it with --host/--port and everything
downstream (filenames, clip JSON, the scorer) behaves exactly as it will in the
lab.

    # terminal 1
    ~/Downloads/drone/trainenv/bin/python tools/real_frames/mock_streamer.py --port 5000
    # terminal 2
    ~/Downloads/drone/trainenv/bin/python tools/crazysim_macos/cpx_grab.py \
        --host 127.0.0.1 --port 5000 --n 5 --every 1 --out /tmp/rehearsal

Wire format (verified against bitcraze/aideck-esp-firmware `main/cpx.h` and
bitcraze/aideck-gap8-examples `examples/other/wifi-img-streamer/`):

    packet   = [len:u16 LE][route0:u8][route1:u8][data]      len = 2 + len(data)
    route0   = destination(bits 0-2) | source(bits 3-5) | lastPacket(bit 6)
    route1   = function(bits 0-5) | version(bits 6-7)        function 5 = CPX_F_APP
    image    = one APP packet holding the 11-byte header
               <BHHBBI> = magic 0xBC, width, height, depth, format, size
               then APP packets of pixel data until `size` bytes have arrived.
    chunking = 1020 bytes of pixels per packet. The GAP8's sendBufferViaCPX()
               sends sizeof(packet->data) at a time, and cpx.h declares that as
               data[MTU - CPX_HEADER_SIZE] = 1022 - 2. (1022 is the whole CPX
               frame including route+function, not the payload.) cpx_grab does
               not care - it reassembles at any chunk size - but the rehearsal
               should carry the same packet count the lab will see.
    JPEG     = NOT one contiguous buffer. The GAP8 streamer calls
               sendBufferViaCPX() three times for a JPEG frame - the JPEG header
               tables, then the entropy-coded data out of the hardware encoder,
               then the 2-byte EOI footer - and the `size` in the image header is
               the sum of the three. So the wire carries THREE short tail chunks
               and THREE lastPacket flags per image, not one of each. This mock
               reproduces that framing by default (--jpeg-one-piece turns it off),
               splitting a real JPEG at its SOS marker and its EOI. The split
               POINT is not claimed to be the GAP8's byte for byte - the GAP8's
               header comes from a fixed table - but the framing SHAPE is, and
               that is what cpx_grab's reassembly has to survive.

Frames come from the simulator scenes in tools/crazysim_macos/scenes_v2 (MuJoCo
render at 324x244, fovy 70, camera 0.8 m up, then the measured Himax sensor
model from camera_model.py), so they look like AI-deck frames rather than test
patterns, and the person really is on the side of the image the --bearing says:
negative bearing = drone's LEFT = person on the left of the image. That makes
the protocol's MIRROR CHECK rehearsable end to end. With --frames it serves
images from a folder instead, and if MuJoCo is missing it falls back to a plain
procedural frame so the mock always starts.

Fault injection (all off by default) reproduces the things that break untested
network code. Use them to rehearse what the operator will see:

    --tcp-chunk 7      write the stream in 7-byte TCP writes (splits CPX
                       packets and even the 4-byte length header)
    --join-mid         first client joins in the middle of a frame, no header
    --console-noise    interleave CPX console packets (function 2) like the GAP8 does
    --short-frame 3    cut frame 3 short, then start the next header (desync)
    --empty-final      send the trailing zero-length packet the GAP8 sends when
                       the image size is an exact multiple of the chunk size
    --bc-payload       force a pixel chunk to start with byte 0xBC (false magic)
    --flip             mirror every frame left-right, so the protocol's MIRROR
                       CHECK fails: see what a back-to-front camera looks like
    --drop-after 4     close the connection after 4 frames (clean disconnect)
    --drop-mid-frame   ...close halfway through frame 5 instead (dirty disconnect)
    --stall-after 4    stop sending after 4 frames but hold the socket open
                       (exercises cpx_grab's --timeout path). Unbounded unless
                       you also pass --stall-seconds; see "--stall-after" below.

REHEARSING THE MIRROR CHECK (protocol section 3.2) - read this before you try it.

    THE --bearing YOU PASS cpx_grab.py IS ONLY A LABEL. It is written into the
    filenames and changes nothing about the pixels. The side the person is
    actually on is decided HERE, by this mock's own --bearing.

So a mirror rehearsal needs the mock to serve two different bearings. Give
--bearing TWICE (or once as a comma list) and the mock builds one frame bank per
bearing and hands them out IN ORDER, one bearing per client connection:

    # terminal 1 - ONE mock, serving the left bank then the right bank
    mock_streamer.py --port 5000 --bearing -25 --bearing 25

    # terminal 2 - first connection gets bearing -25, second gets +25
    cpx_grab.py --mock --seconds 10 --every 1 --dist 2.5 --bearing -25 \
        --vis 1 --subject p01 --light room --out ~/drone_frames/rehearsal/mirror
    cpx_grab.py --mock --seconds 10 --every 1 --dist 2.5 --bearing 25 \
        --vis 1 --subject p01 --light room --out ~/drone_frames/rehearsal/mirror
    score_real_frames.py ~/drone_frames/rehearsal/mirror     # -> MIRROR CHECK PASS

The mock prints "serving bearing X deg" on every connection, so you can check the
clips lined up with the labels before you trust the verdict. Run the clips in the
order you listed the bearings; after the last one it wraps round to the first.

Restarting the mock by hand between clips still works and is equivalent - but
with ONE bearing and TWO clips you get two IDENTICAL clips, one of them labelled
with the wrong side, and the scorer prints a FAIL that means nothing.

Add --flip to rehearse the genuinely failing verdict (-> MIRRORED).

Exit: Ctrl-C, or --once to stop after the first client disconnects.
"""
import argparse
import io
import math
import os
import select
import socket
import struct
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent                      # .../pytorch_ssd
SIM_TOOLS = REPO / "tools" / "crazysim_macos"
SCENES_V2 = SIM_TOOLS / "scenes_v2"

# --- CPX constants, from bitcraze/aideck-esp-firmware main/cpx.h -------------
CPX_T_WIFI_HOST, CPX_T_GAP8 = 3, 4
CPX_F_CONSOLE, CPX_F_APP = 2, 5
# aideck-gap8-examples lib/cpx/inc/com.h: MTU 1022; cpx.h: CPX_HEADER_SIZE 2,
# CPXPacket_t.data is data[MTU - CPX_HEADER_SIZE]. sendBufferViaCPX() sends
# sizeof(packet->data) per packet, so the wire carries 1020 pixel bytes.
CPX_MAX_PAYLOAD_SIZE = 1020
IMG_MAGIC = 0xBC
# The AI-deck's Himax HM01B0 at the resolution the streamer uses.
WIDTH, HEIGHT = 324, 244
RAW_DEPTH = 1          # bytes per pixel, what the GAP8 puts in the header
JPEG_DEPTH = 1
DEFAULT_BANK = 24      # distinct rendered frames to cycle (--frames serves all)
DEFAULT_BEARING = -25.0   # degrees; negative = drone's left = left of the image


# --------------------------------------------------------------------------
# CPX framing
# --------------------------------------------------------------------------
def _log(msg):
    print(msg, flush=True)


def cpx_packet(data, function=CPX_F_APP, last=False,
               destination=CPX_T_WIFI_HOST, source=CPX_T_GAP8, version=0):
    """One CPX wire packet: [len:u16][route0][route1][data]."""
    route0 = (destination & 0x07) | ((source & 0x07) << 3) | (0x40 if last else 0)
    route1 = (function & 0x3F) | ((version & 0x03) << 6)
    return struct.pack("<HBB", len(data) + 2, route0, route1) + bytes(data)


def image_header(w, h, depth, fmt, size):
    return struct.pack("<BHHBBI", IMG_MAGIC, w, h, depth, fmt, size)


def bc_payload_index(chunk, header_with_payload=False):
    """Byte offset of the first pixel that lands at the start of a payload chunk.

    Poking IMG_MAGIC there gives a pixel chunk that begins with the magic byte -
    which real grayscale frames do all the time, 0xBC being pixel value 188. The
    poke goes into the frame itself (see build_bank), not into the packets, so
    that --save-bank writes exactly what the wire carries.
    """
    return chunk - 11 if header_with_payload else chunk


def jpeg_pieces(payload):
    """Split a JPEG into the three buffers the GAP8 sends one at a time.

    wifi-img-streamer.c does not hand the whole JPEG to CPX in one go. It calls
    sendBufferViaCPX() three times - the JPEG header tables, the entropy-coded
    data the hardware encoder produced, then the EOI footer - and advertises
    their combined length in the image header. Each of those calls ends with its
    own short tail chunk and its own lastPacket flag, so a real JPEG frame has
    three of each. A mock that sends one contiguous buffer never exercises that.

    The split here is at the JPEG's own SOS marker and EOI, which is the same
    BOUNDARY the GAP8's fixed header table ends at, though not necessarily the
    same byte count. Returns a list whose lengths sum to len(payload) exactly;
    empty pieces are dropped, and anything that does not parse as a JPEG comes
    back as a single piece (framing then matches the old contiguous behaviour).
    """
    body = bytes(payload)
    footer = b""
    if body.endswith(b"\xff\xd9"):
        footer, body = body[-2:], body[:-2]
    sos = body.find(b"\xff\xda")
    if sos < 0 or sos + 4 > len(body):
        return [p for p in (body, footer) if p] or [b""]
    end = sos + 2 + int.from_bytes(body[sos + 2:sos + 4], "big")   # past the SOS segment
    if not 0 < end <= len(body):
        return [p for p in (body, footer) if p] or [b""]
    return [p for p in (body[:end], body[end:], footer) if p] or [b""]


def image_packets(w, h, depth, fmt, payload, chunk=CPX_MAX_PAYLOAD_SIZE,
                  header_with_payload=False, empty_final=False,
                  short_bytes=None, console_noise=False, pieces=None):
    """The CPX packets for one image, in order.

    `short_bytes` stops after that many payload bytes (a cut-short frame).
    `empty_final` adds the zero-length packet the GAP8's sendBufferViaCPX()
    emits when a buffer is an exact multiple of the chunk size.
    `pieces` is the list of buffers the streamer sends separately - one
    sendBufferViaCPX() call each, so each gets its own short tail chunk and its
    own lastPacket flag. Default (None) is the single contiguous buffer a raw
    frame is; jpeg_pieces() gives the three a JPEG frame is. The lengths must
    sum to len(payload), which is what the image header advertises.
    """
    out = []
    body = bytes(payload)
    if short_bytes is not None:
        body = body[:short_bytes]
    head = image_header(w, h, depth, fmt, len(payload))
    if pieces is None:
        bufs = [body]
    else:
        # Re-cut the pieces against `body`, so a cut-short frame drops its tail
        # buffers instead of sending bytes the header never promised.
        bufs, left = [], len(body)
        for p in pieces:
            take = min(len(p), left)
            if take:
                bufs.append(bytes(p[:take]))
            left -= take
            if left <= 0:
                break
    sent = 0
    if header_with_payload and bufs:
        first = bufs[0][:chunk - 11]
        bufs[0] = bufs[0][len(first):]
        out.append(cpx_packet(head + first))
        sent = len(first)
    else:
        out.append(cpx_packet(head))
    for buf in bufs:
        off = 0
        while off < len(buf):
            piece = buf[off:off + chunk]
            off += len(piece)
            sent += len(piece)
            # lastPacket marks the end of THIS sendBufferViaCPX() call, not the
            # end of the image. cpx_grab ignores it and counts bytes instead,
            # which is the only thing that works for a three-buffer JPEG.
            last = off >= len(buf) and short_bytes is None
            out.append(cpx_packet(piece, last=last))
            if console_noise and sent % (chunk * 8) == 0:
                out.append(cpx_packet(b"GAP8: fps 10.0\n", function=CPX_F_CONSOLE))
        if empty_final and short_bytes is None and len(buf) and len(buf) % chunk == 0:
            out.append(cpx_packet(b"", last=True))
    return out


def encode_frame(gray, fmt, jpeg_quality=90):
    """(w, h, depth, fmt, payload) for one uint8 (H, W) frame."""
    h, w = gray.shape
    if fmt == 0:
        return w, h, RAW_DEPTH, 0, gray.tobytes()
    buf = io.BytesIO()
    Image.fromarray(gray, "L").save(buf, format="JPEG", quality=jpeg_quality)
    return w, h, JPEG_DEPTH, 1, buf.getvalue()


# --------------------------------------------------------------------------
# Frame banks
# --------------------------------------------------------------------------
def bank_from_dir(path, n=None, width=WIDTH, height=HEIGHT):
    """Grayscale frames from a folder of images, in filename order.

    `n` None (the default for --frames) serves EVERY image in the folder: when
    you are replaying a real clip, silently dropping its tail and looping the
    first few frames would make the re-scored numbers a lie. An explicit --bank
    still caps it, and says so.
    """
    exts = {".png", ".jpg", ".jpeg", ".bmp", ".pgm"}
    files = sorted(p for p in Path(path).rglob("*") if p.suffix.lower() in exts)
    if not files:
        sys.exit(f"no images in {path}")
    if n is not None and len(files) > n:
        _log(f"note: {len(files)} images in {path}, serving only the first {n} "
             f"(--bank {n}); drop --bank to serve all of them")
        files = files[:n]
    out = []
    for p in files:
        im = Image.open(p).convert("L")
        if im.size != (width, height):
            im = im.resize((width, height), Image.BILINEAR)
        out.append(np.asarray(im, np.uint8))
    return out, f"folder {path} ({len(out)} images)"


def bank_procedural(n, width=WIDTH, height=HEIGHT, bearing=-25.0, dist=2.5, seed=7):
    """Fallback when MuJoCo is not importable: a person-shaped blob at `bearing`.

    Not pretty, but it is the right size, the right dynamic range and, most
    importantly, the person is on the correct side of the image.
    """
    rng = np.random.default_rng(seed)
    fx = (height / 2.0) / math.tan(math.radians(35.0))   # fovy 70 over `height` rows
    out = []
    for k in range(n):
        yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
        img = 150.0 - 40.0 * (yy / height)                        # wall, darker floor
        img[yy > height * 0.62] = 95.0 + 25.0 * np.sin(xx[yy > height * 0.62] / 9.0)
        b = math.radians(bearing + 0.4 * math.sin(k / 3.0))
        # negative bearing = drone's left = left of the image
        cx = width / 2.0 + fx * math.tan(b)
        person_h = fx * 1.7 / max(dist, 0.3)
        half_w = person_h / 5.0
        top = height / 2.0 - person_h * 0.45
        m = (np.abs(xx - cx) < half_w) & (yy > top) & (yy < top + person_h)
        img[m] = 55.0
        img += rng.normal(0.0, 3.0, img.shape)
        out.append(np.clip(img, 0, 255).astype(np.uint8))
    return out, f"procedural blob (bearing {bearing:g} deg, no MuJoCo)"


def bank_from_scene(scene, n, dist=2.5, bearing=-25.0, preset="himax_typical",
                    cam_height=0.8, width=WIDTH, height=HEIGHT, seed=7):
    """Render the drone's eye view of a simulator scene, through the sensor model.

    Raises ImportError if MuJoCo / camera_model are not available.
    """
    sys.path.insert(0, str(SIM_TOOLS))
    import mujoco                                     # noqa: E402
    import camera_model as cm                         # noqa: E402

    spec = mujoco.MjSpec.from_file(str(scene))
    cam = spec.worldbody.add_camera()
    cam.name, cam.fovy = "mock_cam", 70.0
    cam.alt.type = mujoco.mjtOrientation.mjORIENTATION_XYAXES
    cam.alt.xyaxes = [0, -1, 0, 0, 0, 1]   # look along +x, image-right = world -y
    model = spec.compile()
    data = mujoco.MjData(model)
    renderer = mujoco.Renderer(model, height, width)
    cid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_CAMERA, "mock_cam")

    # Aim at whichever body looks like the subject, else the scene origin.
    target = None
    for i in range(model.nbody):
        name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_BODY, i) or ""
        if "person" in name or name == "subj_target":
            target = model.body_pos[i].copy()
            break
    if target is None:
        target = np.array([3.0, 0.0, 0.85])

    sensor = cm.CameraModel(preset, width, height, seed=seed)
    rng = np.random.default_rng(seed + 3)
    out = []
    for k in range(n):
        # Small hand-held-tripod jitter so consecutive frames are not identical.
        b = math.radians(bearing) + math.radians(0.5) * math.sin(k / 4.0)
        d = dist + 0.02 * math.sin(k / 6.0)
        model.cam_pos[cid] = [target[0] - d * math.cos(b),
                              target[1] + d * math.sin(b),
                              cam_height + float(rng.normal(0, 0.002))]
        mujoco.mj_forward(model, data)
        renderer.update_scene(data, camera="mock_cam")
        out.append(sensor.apply(renderer.render().copy(), dt=0.1))
    return out, (f"{Path(scene).parent.name} rendered at d={dist:g} m "
                 f"bearing={bearing:g} deg, preset {preset}")


def resolve_scene(name):
    """--scene may be a path or the short name of a scenes_v2 folder."""
    p = Path(name)
    if p.is_file():
        return p
    if (SCENES_V2 / name / "scene.xml").is_file():
        return SCENES_V2 / name / "scene.xml"
    known = sorted(d.name for d in SCENES_V2.glob("*") if (d / "scene.xml").is_file())
    sys.exit(f"no scene {name!r}; known scenes: {', '.join(known) or '(none)'}")


def build_bank(a, bearing=None):
    n = DEFAULT_BANK if a.bank is None else a.bank
    bearing = a.bearing if bearing is None else bearing
    if a.frames:
        bank, banner = bank_from_dir(a.frames, a.bank)   # None = the whole folder
    elif a.synthetic:
        bank, banner = bank_procedural(n, bearing=bearing, dist=a.dist)
    else:
        scene = resolve_scene(a.scene)
        try:
            bank, banner = bank_from_scene(scene, n, dist=a.dist, bearing=bearing,
                                           preset=a.preset)
        except ImportError as e:
            _log(f"note: cannot render the sim scene ({e}); using the procedural fallback")
            bank, banner = bank_procedural(n, bearing=bearing, dist=a.dist)
    if a.flip:
        # What a camera mounted or read back-to-front looks like. The protocol's
        # MIRROR CHECK exists to catch exactly this, so it is worth being able to
        # see a failing mirror check before the lab rather than during it.
        bank = [np.ascontiguousarray(g[:, ::-1]) for g in bank]
        banner += "  [MIRRORED left-right]"
    if a.bc_payload:
        if a.image_format != 0:
            _log("note: --bc-payload only bites on raw frames (--image-format 0); ignored")
        else:
            idx = bc_payload_index(a.chunk, a.header_with_payload)
            poked = []
            for g in bank:
                g = np.array(g, copy=True)
                if idx < g.size:
                    g.reshape(-1)[idx] = IMG_MAGIC
                poked.append(g)
            bank = poked
            banner += f"  [pixel {idx} forced to 0x{IMG_MAGIC:02X}]"
    return bank, banner


def build_banks(a):
    """One (bearing, bank, banner) per --bearing, in the order they were given.

    Two bearings is what makes the protocol's MIRROR CHECK rehearsable from a
    single mock process: connection 1 gets the first bearing, connection 2 the
    second. With one bearing (the default) this is the old single bank.
    """
    if a.frames and len(a.bearings) > 1:
        sys.exit("--frames serves images from disk, so --bearing cannot change what they "
                 "show; pass --bearing once, or use two folders and two mock runs.")
    out = []
    for b in a.bearings:
        bank, banner = build_bank(a, bearing=b)
        out.append((b, bank, banner))
    return out


# --------------------------------------------------------------------------
# Serving
# --------------------------------------------------------------------------
def hold_socket_open(conn, seconds, log=_log):
    """Stop sending but keep the connection up, the way a wedged GAP8 does.

    Returns the reason it ended. `seconds` None means "until the client goes
    away" - which used to be "for ever, ignoring the client entirely": the old
    code sat in `while True: time.sleep(0.5)`, so it never noticed the client
    disconnecting, --once could never fire and the process had to be killed by
    hand. Anything scripting the failure-mode demos hung there.
    """
    sock = getattr(conn, "sock", conn)
    deadline = None if seconds is None else time.time() + seconds
    while deadline is None or time.time() < deadline:
        wait = 0.25 if deadline is None else max(0.0, min(0.25, deadline - time.time()))
        try:
            readable, _, _ = select.select([sock], [], [], wait)
        except (OSError, ValueError):
            return "the socket closed"
        if readable:
            try:
                if not sock.recv(4096):
                    return "the client disconnected"
            except OSError:
                return "the client disconnected"
    return f"the {seconds:g} s stall ran out"


def send_stream(conn, bank, a, log=_log):
    """Stream frames to one connected client. Returns the number of frames sent."""
    period = 1.0 / a.fps if a.fps > 0 else 0.0
    sent = 0
    i = 0
    joined = not a.join_mid
    t_next = time.time()
    while a.count is None or sent < a.count:
        gray = bank[i % len(bank)]
        i += 1
        n = sent + 1                            # 1-based frame number, for the flags
        w, h, depth, fmt, payload = encode_frame(gray, a.image_format, a.jpeg_quality)

        # A JPEG frame leaves the GAP8 as three separate sendBufferViaCPX()
        # calls (header tables / entropy data / EOI), not one contiguous buffer.
        pieces = None
        if fmt == 1 and not a.jpeg_one_piece:
            pieces = jpeg_pieces(payload)

        short = None
        if a.short_frame == n:
            short = len(payload) // 2
        packets = image_packets(
            w, h, depth, fmt, payload, chunk=a.chunk,
            header_with_payload=a.header_with_payload, empty_final=a.empty_final,
            short_bytes=short, console_noise=a.console_noise, pieces=pieces)

        if not joined:
            # Join mid-image: drop the header and the first half of the chunks.
            packets = packets[1 + len(packets) // 2:]
            joined = True
            log(f"  frame {n}: joined mid-image ({len(packets)} chunks, no header)")

        blob = b"".join(packets)
        if a.drop_after is not None and n > a.drop_after:
            if a.drop_mid_frame:
                cut = len(blob) // 2
                conn.sendall(blob[:cut])
                log(f"  frame {n}: closing mid-frame after {cut} bytes")
            else:
                log(f"  closing after {sent} frames")
            return sent
        conn.sendall(blob)
        sent += 1
        note = ""
        if short is not None:
            note = f"  (CUT SHORT at {short}/{len(payload)} bytes)"
        if pieces is not None:
            note += f"  (JPEG in {len(pieces)} buffers: "
            note += "+".join(str(len(p)) for p in pieces) + ")"
        log(f"  frame {n}: {w}x{h} fmt={fmt} {len(payload)} B in "
            f"{len(packets)} packets{note}")
        if a.stall_after is not None and sent >= a.stall_after:
            how_long = ("until the client disconnects" if a.stall_seconds is None
                        else f"for {a.stall_seconds:g} s")
            log(f"  stalling after {sent} frames; holding the socket open {how_long} "
                f"(--stall-seconds bounds it; Ctrl-C always stops it)")
            log(f"  stall over: {hold_socket_open(conn, a.stall_seconds, log)}; closing")
            return sent
        t_next += period
        delay = t_next - time.time()
        if delay > 0:
            time.sleep(delay)
        else:
            t_next = time.time()
    log(f"  sent {sent} frames; closing")
    return sent


def send_stream_chopped(conn, bank, a, log=_log):
    """send_stream, but every write is at most --tcp-chunk bytes.

    Splits CPX packets across TCP segments, including the 4-byte length header,
    which is what a real WiFi link does and what a naive socket reader gets
    wrong.
    """
    size = a.tcp_chunk

    class Chopper:
        sock = conn        # so hold_socket_open() can still watch the real socket

        def sendall(self, blob):
            for off in range(0, len(blob), size):
                conn.sendall(blob[off:off + size])

    return send_stream(Chopper(), bank, a, log=log)


def someone_else_listening(host, port):
    """True if something already answers on this address.

    macOS' AirPlay Receiver (ControlCenter) listens on TCP *:5000 - the same
    port the AI-deck uses. Binding 127.0.0.1:5000 still works and local
    connections still reach this mock, but the moment the mock is not running,
    cpx_grab connects to AirPlay instead and just sits there until its timeout.
    Worth saying out loud before anyone spends ten minutes on it.
    """
    try:
        with socket.create_connection((host, port), timeout=0.4):
            return True
    except OSError:
        return False


def serve(a, banks, banner=None, on_bound=None, log=_log):
    """Accept clients and stream to them.

    `banks` is the list build_banks() returns - (bearing, frames, banner) - and
    each client connection is served the next one, so a two-bearing mock can
    rehearse the mirror check without being restarted. A bare (bank, banner)
    pair is still accepted, which is what a single-bearing caller passes.
    """
    if banner is not None:                       # serve(a, bank, banner) - one bank
        bearings = getattr(a, "bearings", None) or [getattr(a, "bearing", DEFAULT_BEARING)]
        banks = [(bearings[0], banks, banner)]
    clash = someone_else_listening("127.0.0.1" if a.host == "0.0.0.0" else a.host, a.port)
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        srv.bind((a.host, a.port))
    except OSError as e:
        extra = ""
        if a.port == 5000 and sys.platform == "darwin":
            extra = ("\n  On macOS, AirPlay Receiver holds port 5000: turn it off in "
                     "System Settings > General > AirDrop & Handoff, or use --port 5001 "
                     "and pass the same --port to cpx_grab.")
        sys.exit(f"cannot listen on {a.host}:{a.port}: {e}{extra}")
    srv.listen(1)
    port = srv.getsockname()[1]
    log(f"mock AI-deck streaming on tcp://{a.host}:{port}")
    if len(banks) == 1:
        log(f"  frames: {banks[0][2]}")
    else:
        log(f"  frames: {len(banks)} banks, ONE PER CONNECTION, in this order "
            f"(then wrapping round):")
        for k, (b, _, bnr) in enumerate(banks, 1):
            log(f"    connection {k}: bearing {b:g} deg - {bnr}")
        log("    give cpx_grab.py the MATCHING --bearing label on each run, in this "
            "same order.")
        # The cursor advances on every accept(), so ANY connection consumes a
        # bearing - including a grab the operator Ctrl-C'd because the subject
        # was not in place yet. Restarting that grab gets the NEXT bearing, and
        # the clip is then labelled with the wrong side without a word of
        # complaint: exactly the mislabelled-mirror-clip failure this option
        # exists to prevent. Say so up front, and name the next bearing after
        # every connection below, so a desync is visible rather than silent.
        log("    NOTE: every connection takes the next bearing, even one you abort. "
            "If you\n          stop a grab and start it again, it gets the NEXT "
            "bearing, not the same\n          one - restart this mock to go back to "
            "the top of the list.")
    jpeg_note = ""
    if a.image_format == 1:
        jpeg_note = ("  one buffer (--jpeg-one-piece)" if a.jpeg_one_piece
                     else "  header+entropy+footer, as the GAP8 sends it")
    log(f"  format: {'raw (format 0)' if a.image_format == 0 else 'JPEG (format 1)'}"
        f"  {a.fps:g} fps  chunk {a.chunk} B{jpeg_note}")
    faults = [n for n, v in (("flip", a.flip),
                             ("join-mid", a.join_mid), ("console-noise", a.console_noise),
                             ("empty-final", a.empty_final), ("bc-payload", a.bc_payload),
                             ("header-with-payload", a.header_with_payload),
                             ("drop-mid-frame", a.drop_mid_frame)) if v]
    for n, v in (("short-frame", a.short_frame), ("drop-after", a.drop_after),
                 ("stall-after", a.stall_after), ("stall-seconds", a.stall_seconds),
                 ("tcp-chunk", a.tcp_chunk), ("count", a.count)):
        if v is not None:
            faults.append(f"{n}={v}")
    log(f"  faults: {', '.join(faults) if faults else 'none'}")
    if a.stall_after is not None and a.stall_seconds is None:
        log(f"  NOTE: --stall-after {a.stall_after} with no --stall-seconds holds the "
            "socket open until the client\n        disconnects, then closes it. If the "
            "client never disconnects either, this process\n        waits for ever and "
            "must be stopped with Ctrl-C"
            + (" - --once cannot fire before then." if a.once else ".")
            + "\n        Pass --stall-seconds N for a stall that ends on its own.")
    if clash:
        log(f"  NOTE: something else was already answering on {a.host}:{a.port}"
            + ("  (on macOS, port 5000 is AirPlay Receiver)" if a.port == 5000 else "")
            + f"\n        This mock binds {a.host} directly, so cpx_grab still reaches it"
              " while this process is up -\n        but if you stop the mock, cpx_grab will"
              " connect to that other service and hang.")
    if on_bound:
        on_bound(port)
    try:
        nth = 0
        while True:
            conn, peer = srv.accept()
            bearing, bank, _ = banks[nth % len(banks)]
            nth += 1
            log(f"client {peer[0]}:{peer[1]} connected"
                + (f"  -  connection {nth}, serving bearing {bearing:g} deg"
                   if len(banks) > 1 else ""))
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            try:
                if a.tcp_chunk:
                    send_stream_chopped(conn, bank, a, log=log)
                else:
                    send_stream(conn, bank, a, log=log)
            except (BrokenPipeError, ConnectionResetError):
                log("client went away")
            finally:
                conn.close()
            if a.once:
                return
            if len(banks) > 1:
                log(f"  next connection gets bearing {banks[nth % len(banks)][0]:g} deg "
                    f"(connection {nth + 1})")
    except KeyboardInterrupt:
        log("stopped by user")
    finally:
        srv.close()


def build_parser():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="127.0.0.1", help="bind address (default 127.0.0.1)")
    ap.add_argument("--port", type=int, default=5000,
                    help="bind port (default 5000, the AI-deck's; 0 = pick a free one)")
    ap.add_argument("--fps", type=float, default=10.0, help="frames per second (default 10)")
    ap.add_argument("--count", type=int, default=None,
                    help="stop after this many frames (default: stream for ever)")
    ap.add_argument("--once", action="store_true", help="exit after the first client disconnects")

    g = ap.add_argument_group("what the frames look like")
    g.add_argument("--scene", default="s15_static_offset",
                   help="scenes_v2 folder name or a path to a MuJoCo scene.xml")
    g.add_argument("--frames", default=None, help="serve images from this folder instead")
    g.add_argument("--synthetic", action="store_true",
                   help="skip MuJoCo; serve a procedural person-shaped frame")
    g.add_argument("--bank", type=int, default=None,
                   help=f"how many distinct frames to cycle (default {DEFAULT_BANK}; "
                        "with --frames the default is every image in the folder)")
    g.add_argument("--dist", type=float, default=2.5, help="metres from camera to person")
    g.add_argument("--bearing", action="append", default=None, metavar="DEG",
                   help="degrees; NEGATIVE = drone's left = person on the image's left "
                        f"(default {DEFAULT_BEARING:g}). GIVE IT TWICE - e.g. "
                        "'--bearing -25 --bearing 25' - and the mock builds one frame "
                        "bank per bearing and serves the NEXT one to each client "
                        "connection, which is what makes the protocol's MIRROR CHECK "
                        "rehearsable from a single mock. The --bearing you pass "
                        "cpx_grab.py is only a filename LABEL and does not change the "
                        "pixels, so with one bearing and two clips you get two "
                        "identical clips and a meaningless FAIL.")
    g.add_argument("--preset", default="himax_typical",
                   help="camera_model preset: clean, himax_typical, himax_low_light, "
                        "himax_color_bayer")
    g.add_argument("--flip", action="store_true",
                   help="mirror every frame left-right, as a back-to-front camera would: "
                        "use it to see a FAILING mirror check before the lab")
    g.add_argument("--save-bank", default=None, help="also write the frames here as .png")

    g = ap.add_argument_group("wire format")
    g.add_argument("--image-format", type=int, choices=(0, 1), default=0,
                   help="0 = raw 8-bit (default, what we score), 1 = JPEG")
    g.add_argument("--jpeg-quality", type=int, default=90, help="quality for --image-format 1")
    g.add_argument("--jpeg-one-piece", action="store_true",
                   help="send a JPEG frame as ONE contiguous buffer. The default is the "
                        "GAP8's three separate sendBufferViaCPX() calls (header tables, "
                        "entropy data, EOI footer), which put three short tail chunks and "
                        "three lastPacket flags on the wire instead of one of each")
    g.add_argument("--chunk", type=int, default=CPX_MAX_PAYLOAD_SIZE,
                   help=f"CPX payload bytes per packet (default {CPX_MAX_PAYLOAD_SIZE})")
    g.add_argument("--header-with-payload", action="store_true",
                   help="pack the first pixels into the header packet")
    g.add_argument("--empty-final", action="store_true",
                   help="send the trailing zero-length packet when size %% chunk == 0")

    g = ap.add_argument_group("fault injection (rehearse what goes wrong)")
    g.add_argument("--tcp-chunk", type=int, default=None,
                   help="write the stream in N-byte TCP writes (splits CPX packets)")
    g.add_argument("--join-mid", action="store_true",
                   help="first client joins mid-image, with no header")
    g.add_argument("--console-noise", action="store_true",
                   help="interleave CPX console packets (function 2)")
    g.add_argument("--short-frame", type=int, default=None,
                   help="cut frame N short, then start the next header")
    g.add_argument("--bc-payload", action="store_true",
                   help="make a pixel chunk start with the magic byte 0xBC")
    g.add_argument("--drop-after", type=int, default=None,
                   help="close the connection after N frames")
    g.add_argument("--drop-mid-frame", action="store_true",
                   help="with --drop-after N, close halfway through frame N+1")
    g.add_argument("--stall-after", type=int, default=None,
                   help="stop sending after N frames but hold the socket open (ends when "
                        "the client disconnects, or after --stall-seconds)")
    g.add_argument("--stall-seconds", type=float, default=None, metavar="S",
                   help="bound a --stall-after stall to S seconds, then close the "
                        "connection normally. Without it the stall lasts until the client "
                        "goes away, so --once cannot fire while a client just sits there "
                        "and a script driving the failure-mode demos waits for ever")
    return ap


def parse_bearings(ap, values):
    """--bearing, repeated and/or comma-separated, in the order given.

    Repeating the option is the form to document: argparse takes '--bearing -25'
    (it recognises a lone negative number) but chokes on '--bearing -25,25',
    where the comma stops it looking like one. '--bearing=-25,25' works.
    """
    if not values:
        return [DEFAULT_BEARING]
    out = []
    for v in values:
        for part in str(v).split(","):
            part = part.strip()
            if not part:
                continue
            try:
                out.append(float(part))
            except ValueError:
                ap.error(f"--bearing wants degrees, got {part!r}. Repeat the option for "
                         "several bearings: --bearing -25 --bearing 25")
    if not out:
        ap.error("--bearing was given with no value")
    return out


def main(argv=None):
    ap = build_parser()
    a = ap.parse_args(argv)
    if a.chunk < 12:
        sys.exit("--chunk must be at least 12 (the image header is 11 bytes)")
    if a.bank is not None and a.bank < 1:
        sys.exit("--bank must be >= 1")
    if a.stall_seconds is not None and a.stall_after is None:
        sys.exit("--stall-seconds bounds a --stall-after stall; pass --stall-after N too")
    if a.stall_seconds is not None and a.stall_seconds < 0:
        sys.exit("--stall-seconds must be >= 0")
    a.bearings = parse_bearings(ap, a.bearing)
    a.bearing = a.bearings[0]        # what the single-bank helpers still read
    banks = build_banks(a)
    if a.save_bank:
        os.makedirs(a.save_bank, exist_ok=True)
        total = 0
        for bearing, bank, _ in banks:
            # One bearing keeps the old flat names; several would collide, so
            # they carry the bearing they were rendered at.
            tag = "" if len(banks) == 1 else f"b{bearing:g}_"
            for k, g in enumerate(bank):
                Image.fromarray(g, "L").save(
                    os.path.join(a.save_bank, f"bank_{tag}{k:03d}.png"))
                total += 1
        print(f"wrote {total} frames to {a.save_bank}")
    serve(a, banks)


if __name__ == "__main__":
    main()
