#!/usr/bin/env python3
"""Tests for mock_streamer.py and for cpx_grab.py reading it.

This is the rehearsal for the real capture session: everything cpx_grab.py will
do against the AI-deck next week, it does here against the mock, including the
failures. Run it before the lab; it takes a few seconds and needs no hardware.

    ~/Downloads/drone/trainenv/bin/python tools/real_frames/test_mock_streamer.py

Nothing here proves anything about a real AI-deck. It proves that cpx_grab.py
parses the wire format Bitcraze's wifi-img-streamer documents, reassembles
frames byte for byte however the bytes are split up, and behaves sanely when the
stream is cut short, disconnects or goes quiet.
"""
import importlib.util
import io
import json
import os
import re
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
GRAB_PY = REPO / "tools" / "crazysim_macos" / "cpx_grab.py"
MOCK_PY = HERE / "mock_streamer.py"

sys.path.insert(0, str(HERE))
import mock_streamer as mock                                    # noqa: E402


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


grab = _load("cpx_grab", GRAB_PY)

# The filename scheme docs/real_frame_capture_protocol.md section 4 promises.
FRAME_RE = re.compile(
    r"^d(?P<d>-?[\d.]+)_b(?P<b>-?[\d.]+)_vis(?P<vis>[01])_subj-(?P<subj>[A-Za-z0-9-]+)"
    r"_light-(?P<light>[A-Za-z0-9-]+)_take(?P<take>\d+)_f(?P<f>\d{5})_t(?P<t>[\d.]+)\.png$")


def one_frame(seed=0, w=48, h=32):
    """A small deterministic frame; small keeps the tests fast."""
    rng = np.random.default_rng(seed)
    return rng.integers(0, 256, size=(h, w), dtype=np.uint8)


class Feeder:
    """Feeds a byte string to a socket a client reads through grab.PacketReader."""

    def __init__(self, blob, piece=None):
        self.a, self.b = socket.socketpair()
        self.blob, self.piece = blob, piece or len(blob)
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        try:
            for off in range(0, len(self.blob), self.piece):
                self.a.sendall(self.blob[off:off + self.piece])
        except OSError:
            pass
        finally:
            self.a.close()

    def reader(self):
        return grab.PacketReader(self.b)

    def close(self):
        for s in (self.a, self.b):
            try:
                s.close()
            except OSError:
                pass


class TestWireFormat(unittest.TestCase):
    """The mock's packets are the ones the protocol describes."""

    def test_packet_framing(self):
        p = mock.cpx_packet(b"hello", function=mock.CPX_F_APP)
        length, route0, route1 = struct.unpack("<HBB", p[:4])
        self.assertEqual(length, 2 + 5)            # len counts route + function
        self.assertEqual(p[4:], b"hello")
        self.assertEqual(route0 & 0x07, mock.CPX_T_WIFI_HOST)
        self.assertEqual((route0 >> 3) & 0x07, mock.CPX_T_GAP8)
        self.assertEqual(route1 & 0x3F, mock.CPX_F_APP)

    def test_last_packet_flag_is_in_the_route_byte(self):
        # Bit 6 of route0. cpx_grab must not mistake it for part of anything.
        p = mock.cpx_packet(b"x", last=True)
        self.assertTrue(p[2] & 0x40)
        func, data = Feeder(p).reader().packet()
        self.assertEqual((func, data), (mock.CPX_F_APP, b"x"))

    def test_image_header_matches_the_streamer_struct(self):
        head = mock.image_header(324, 244, 1, 0, 324 * 244)
        self.assertEqual(len(head), 11)
        self.assertEqual(grab.parse_header(head), (324, 244, 1, 0, 324 * 244))

    def test_parse_header_rejects_a_pixel_chunk_that_starts_with_the_magic_byte(self):
        junk = bytes([mock.IMG_MAGIC]) + bytes(range(10))
        self.assertIsNone(grab.parse_header(junk))


class TestReassembly(unittest.TestCase):
    """One image in, the same bytes out, however the stream is cut up."""

    def _round_trip(self, gray, fmt, **kw):
        w, h, depth, f, payload = mock.encode_frame(gray, fmt)
        packets = mock.image_packets(w, h, depth, f, payload, **kw)
        feed = Feeder(b"".join(packets))
        try:
            got = grab.recv_image(feed.reader(), stats={"short": 0})
        finally:
            feed.close()
        self.assertEqual(got[:4], (w, h, depth, f))
        self.assertEqual(got[4], payload)
        return got

    def test_raw_frame(self):
        g = one_frame()
        got = self._round_trip(g, 0)
        self.assertTrue(np.array_equal(np.asarray(grab.decode(*got)), g))

    def test_jpeg_frame_is_kept_byte_for_byte(self):
        got = self._round_trip(one_frame(1), 1)
        self.assertEqual(got[3], 1)
        Image.open(io.BytesIO(got[4])).load()       # decodes

    def test_chunk_sizes(self):
        for chunk in (12, 13, 101, 1022, 100000):
            with self.subTest(chunk=chunk):
                self._round_trip(one_frame(2), 0, chunk=chunk)

    def test_header_packet_carrying_the_first_pixels(self):
        self._round_trip(one_frame(3), 0, chunk=64, header_with_payload=True)

    def test_trailing_empty_packet(self):
        # 48*32 = 1536 = 3 * 512, so the payload divides exactly and the GAP8
        # sender emits a final zero-length packet.
        self._round_trip(one_frame(4), 0, chunk=512, empty_final=True)

    def test_console_packets_are_ignored(self):
        self._round_trip(one_frame(5), 0, chunk=64, console_noise=True)

    def test_pixel_chunk_starting_with_the_magic_byte(self):
        # 0xBC is pixel value 188, so a chunk of real pixels starts with the
        # image magic every few hundred frames. It must not be read as a header.
        g = np.array(one_frame(6), copy=True)
        idx = mock.bc_payload_index(64)
        g.reshape(-1)[idx] = mock.IMG_MAGIC
        w, h, depth, f, payload = mock.encode_frame(g, 0)
        packets = mock.image_packets(w, h, depth, f, payload, chunk=64)
        self.assertEqual(packets[2][4], mock.IMG_MAGIC)   # 2nd pixel chunk, 1st byte
        feed = Feeder(b"".join(packets))
        try:
            got = grab.recv_image(feed.reader(), stats={"short": 0})
        finally:
            feed.close()
        self.assertEqual(got[4], payload)

    def test_split_across_tcp_writes(self):
        for piece in (1, 3, 7, 4096):
            with self.subTest(tcp_piece=piece):
                g = one_frame(7)
                w, h, depth, f, payload = mock.encode_frame(g, 0)
                blob = b"".join(mock.image_packets(w, h, depth, f, payload, chunk=64))
                feed = Feeder(blob, piece=piece)
                try:
                    got = grab.recv_image(feed.reader(), stats={"short": 0})
                finally:
                    feed.close()
                self.assertEqual(got[4], payload)

    def test_joining_mid_image_resyncs_on_the_next_header(self):
        g1, g2 = one_frame(8), one_frame(9)
        w, h, d, f, p1 = mock.encode_frame(g1, 0)
        _, _, _, _, p2 = mock.encode_frame(g2, 0)
        first = mock.image_packets(w, h, d, f, p1, chunk=64)
        second = mock.image_packets(w, h, d, f, p2, chunk=64)
        blob = b"".join(first[5:] + second)          # start mid-image, no header
        feed = Feeder(blob)
        try:
            got = grab.recv_image(feed.reader(), stats={"short": 0})
        finally:
            feed.close()
        self.assertEqual(got[4], p2)                # the second, whole image


class TestCutShortFrames(unittest.TestCase):
    """Regression tests for the bug that spliced two half-frames together."""

    def _cut_short(self, **kw):
        g1, g2 = one_frame(10), one_frame(11)
        w, h, d, f, p1 = mock.encode_frame(g1, 0)
        _, _, _, _, p2 = mock.encode_frame(g2, 0)
        cut = mock.image_packets(w, h, d, f, p1, short_bytes=len(p1) // 2, **kw)
        whole = mock.image_packets(w, h, d, f, p2, **kw)
        feed = Feeder(b"".join(cut + whole))
        stats = {"short": 0}
        try:
            got = grab.recv_image(feed.reader(), stats=stats)
        finally:
            feed.close()
        return got, stats, p1, p2

    def test_header_alone_after_a_cut_short_frame(self):
        got, stats, p1, p2 = self._cut_short(chunk=64)
        self.assertEqual(got[4], p2)
        self.assertNotEqual(got[4], p1)
        self.assertEqual(stats["short"], 1)

    def test_header_with_payload_after_a_cut_short_frame(self):
        # This is the case that used to produce a frame that was half one image
        # and half the next, with nothing reported.
        got, stats, p1, p2 = self._cut_short(chunk=64, header_with_payload=True)
        self.assertEqual(got[4], p2)
        self.assertEqual(stats["short"], 1)

    def test_two_cut_short_frames_in_a_row(self):
        g = [one_frame(12 + i) for i in range(3)]
        enc = [mock.encode_frame(x, 0) for x in g]
        blob = b""
        for i, (w, h, d, f, p) in enumerate(enc):
            short = len(p) // 3 if i < 2 else None
            blob += b"".join(mock.image_packets(w, h, d, f, p, chunk=64, short_bytes=short))
        feed = Feeder(blob)
        stats = {"short": 0}
        try:
            got = grab.recv_image(feed.reader(), stats=stats)
        finally:
            feed.close()
        self.assertEqual(got[4], enc[2][4])
        self.assertEqual(stats["short"], 2)


class TestSocketFailures(unittest.TestCase):

    def test_disconnect_mid_frame_raises_connection_error(self):
        w, h, d, f, p = mock.encode_frame(one_frame(20), 0)
        blob = b"".join(mock.image_packets(w, h, d, f, p, chunk=64))
        feed = Feeder(blob[:len(blob) // 2])
        try:
            with self.assertRaises(ConnectionError):
                grab.recv_image(feed.reader(), stats={"short": 0})
        finally:
            feed.close()

    def test_reader_keeps_its_buffer_across_a_timeout(self):
        # The old reader asked for exactly 4 bytes and then exactly len-2 bytes,
        # and dropped whatever it was holding when recv timed out. Feed half a
        # packet, let the read time out, then feed the rest: the packet must
        # still come back whole.
        a, b = socket.socketpair()
        try:
            packet = mock.cpx_packet(b"abcdefghij")
            b.settimeout(0.2)
            r = grab.PacketReader(b)
            a.sendall(packet[:6])
            with self.assertRaises(socket.timeout):
                r.packet()
            a.sendall(packet[6:])
            func, data = r.packet()
            self.assertEqual((func, data), (mock.CPX_F_APP, b"abcdefghij"))
        finally:
            a.close()
            b.close()

    def test_not_a_cpx_stream(self):
        feed = Feeder(struct.pack("<HBB", 0, 0, 0) + b"garbage")
        try:
            with self.assertRaises(ConnectionError):
                grab.recv_image(feed.reader(), stats={"short": 0})
        finally:
            feed.close()


# --------------------------------------------------------------------------
# End to end: the real cpx_grab.py process against the real mock process.
# --------------------------------------------------------------------------
class MockProcess:
    """Starts mock_streamer.py on a free port and waits until it is listening."""

    def __init__(self, *args):
        self.log = tempfile.NamedTemporaryFile("w+", suffix=".log", delete=False)
        self.proc = subprocess.Popen(
            [sys.executable, str(MOCK_PY), "--port", "0", "--synthetic", "--bank", "4",
             *map(str, args)],
            stdout=self.log, stderr=subprocess.STDOUT)
        self.port = None
        deadline = time.time() + 30
        while time.time() < deadline:
            text = Path(self.log.name).read_text()
            m = re.search(r"streaming on tcp://[^:]+:(\d+)", text)
            if m:
                self.port = int(m.group(1))
                return
            if self.proc.poll() is not None:
                raise RuntimeError(f"mock died:\n{text}")
            time.sleep(0.05)
        raise RuntimeError(f"mock never started:\n{Path(self.log.name).read_text()}")

    def text(self):
        return Path(self.log.name).read_text()

    def stop(self):
        self.proc.terminate()
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        self.log.close()
        os.unlink(self.log.name)


def run_grab(port, out, *args):
    r = subprocess.run(
        [sys.executable, str(GRAB_PY), "--host", "127.0.0.1", "--port", str(port),
         "--out", str(out), *map(str, args)],
        capture_output=True, text=True, timeout=120)
    return r


def start_grab(port, out, *args):
    """cpx_grab.py as a live process, so a test can signal it mid-clip."""
    return subprocess.Popen(
        [sys.executable, str(GRAB_PY), "--host", "127.0.0.1", "--port", str(port),
         "--out", str(out), *map(str, args)],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)


def wait_for_frames(out, n, timeout=30):
    """Block until `out` holds at least n image files. Returns how many it has."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        have = len(list(Path(out).glob("*.png"))) + len(list(Path(out).glob("*.jpg")))
        if have >= n:
            return have
        time.sleep(0.05)
    raise AssertionError(f"only {len(list(Path(out).glob('*')))} files in {out} after "
                         f"{timeout} s, wanted {n}")


def flat_frames(folder, n, w=324, h=244):
    """n images whose every pixel is a value unique to that image.

    Frame k is flat grey k*8, so a test can say exactly which frames it got
    back and in what order by reading one pixel.
    """
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    for k in range(n):
        Image.fromarray(np.full((h, w), (k * 8) % 256, np.uint8), "L").save(
            folder / f"src_{k:03d}.png")
    return folder


def grey_of(path):
    return int(np.asarray(Image.open(path).convert("L"))[0, 0])


class TestEndToEnd(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name) / "clips"

    def tearDown(self):
        self.tmp.cleanup()

    def test_labelled_clip_names_and_json(self):
        m = MockProcess("--count", 8, "--fps", 40)
        try:
            r = run_grab(m.port, self.out, "--n", 5, "--every", 1, "--dist", 2.5,
                         "--bearing", -25, "--vis", 1, "--subject", "p01",
                         "--light", "room")
        finally:
            m.stop()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("fmt=0", r.stdout)                       # raw, per the protocol
        pngs = sorted(p.name for p in self.out.glob("*.png"))
        self.assertEqual(len(pngs), 5)
        for name in pngs:
            m2 = FRAME_RE.match(name)
            self.assertIsNotNone(m2, f"filename does not follow the protocol: {name}")
            self.assertEqual(m2.group("d"), "2.5")
            self.assertEqual(m2.group("b"), "-25")
            self.assertEqual(m2.group("subj"), "p01")
            self.assertEqual(m2.group("take"), "1")
        meta = json.loads((self.out / "d2.5_b-25_vis1_subj-p01_light-room_take1_clip.json").read_text())
        self.assertEqual(meta["saved"], 5)
        self.assertEqual(meta["formats"], [0])
        self.assertEqual(meta["sizes"], [[324, 244]])
        self.assertEqual(meta["short"], 0)

    def test_take_collision_is_refused(self):
        labels = ["--dist", 2.5, "--bearing", -25, "--vis", 1,
                  "--subject", "p01", "--light", "room"]
        m = MockProcess("--fps", 40)
        try:
            first = run_grab(m.port, self.out, "--n", 2, "--every", 1, *labels)
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            again = run_grab(m.port, self.out, "--n", 2, "--every", 1, *labels)
            take2 = run_grab(m.port, self.out, "--n", 2, "--every", 1, "--take", 2, *labels)
        finally:
            m.stop()
        self.assertEqual(again.returncode, 1)
        self.assertIn("already has a recording", again.stdout + again.stderr)
        self.assertIn("--take 2", again.stdout + again.stderr)
        self.assertEqual(take2.returncode, 0, take2.stdout + take2.stderr)
        self.assertEqual(len(list(self.out.glob("*_take2_f*.png"))), 2)

    def test_jpeg_warning_on_an_unlabelled_bench_check(self):
        # docs/real_frame_capture_protocol.md section 3.1 runs cpx_grab with no
        # labels; a JPEG-flashed deck has to be caught right there.
        m = MockProcess("--count", 4, "--fps", 40, "--image-format", 1)
        try:
            r = run_grab(m.port, self.out, "--n", 3, "--every", 1)
        finally:
            m.stop()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("streaming JPEG", r.stdout)
        self.assertIn("fmt=1", r.stdout)
        self.assertEqual(len(list(self.out.glob("*.jpg"))), 3)

    def test_disconnect_mid_capture_keeps_what_it_got(self):
        m = MockProcess("--fps", 40, "--drop-after", 3, "--drop-mid-frame")
        try:
            r = run_grab(m.port, self.out, "--n", 20, "--every", 1, "--vis", 0,
                         "--subject", "empty", "--light", "room")
        finally:
            m.stop()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("connection lost", r.stdout)
        self.assertIn("WARNING: asked for 20 frames, got 3", r.stdout)
        self.assertEqual(len(list(self.out.glob("*.png"))), 3)
        meta = json.loads(next(self.out.glob("*_clip.json")).read_text())
        self.assertEqual(meta["saved"], 3)
        self.assertIn("connection dropped", meta["stopped_because"])

    def test_stalled_stream_stops_on_the_timeout(self):
        m = MockProcess("--fps", 40, "--stall-after", 2)
        try:
            t0 = time.time()
            r = run_grab(m.port, self.out, "--n", 10, "--every", 1, "--timeout", 2)
            wall = time.time() - t0
        finally:
            m.stop()
        self.assertIn("no data for 2 s", r.stdout)
        self.assertLess(wall, 20, "the timeout did not stop it promptly")
        self.assertEqual(len(list(self.out.glob("*.png"))), 2)

    def test_seconds_clip_ends_on_time_even_with_a_long_timeout(self):
        m = MockProcess("--fps", 40, "--stall-after", 2)
        try:
            t0 = time.time()
            r = run_grab(m.port, self.out, "--seconds", 2, "--every", 1, "--timeout", 60)
            wall = time.time() - t0
        finally:
            m.stop()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertLess(wall, 10, "the --seconds deadline did not cut the socket timeout short")
        self.assertGreaterEqual(wall, 1.8)

    def test_cut_short_frames_are_reported_not_saved(self):
        m = MockProcess("--count", 8, "--fps", 40, "--short-frame", 2)
        try:
            r = run_grab(m.port, self.out, "--n", 4, "--every", 1)
        finally:
            m.stop()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("cut short", r.stdout)
        self.assertIn("1 cut short", r.stdout)
        self.assertEqual(len(list(self.out.glob("*.png"))), 4)

    def test_frames_survive_a_hostile_link_byte_for_byte(self):
        """Every saved frame must equal a frame the mock sent, exactly."""
        bank = Path(self.tmp.name) / "bank"
        m = MockProcess("--count", 10, "--fps", 40, "--tcp-chunk", 5, "--chunk", 37,
                        "--console-noise", "--bc-payload", "--join-mid",
                        "--save-bank", str(bank))
        try:
            r = run_grab(m.port, self.out, "--n", 4, "--every", 1)
        finally:
            m.stop()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        sent = [np.asarray(Image.open(p).convert("L")) for p in sorted(bank.glob("*.png"))]
        saved = sorted(self.out.glob("*.png"))
        self.assertEqual(len(saved), 4)
        for p in saved:
            got = np.asarray(Image.open(p).convert("L"))
            self.assertTrue(any(np.array_equal(got, s) for s in sent),
                            f"{p.name} is not byte-identical to any frame the mock sent")

    def test_nothing_listening(self):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        r = run_grab(port, self.out, "--n", 1)
        self.assertEqual(r.returncode, 1)
        self.assertIn("could not connect", r.stdout + r.stderr)
        self.assertFalse(self.out.exists(), "a failed connection must not leave a folder")


# --------------------------------------------------------------------------
# DEFECT 1: the JPEG-in-PNG blind spot.
#
# Anything that decides "is this frame raw?" from the file extension is wrong
# exactly when --png/--bayer is used, because those DECODE a JPEG frame and save
# it as .png. That is not a hypothetical: it is what the capture protocol tells
# the operator to do the moment the Bayer warning fires. Model scores on
# JPEG-compressed pixels are not valid - the chip never sees compression
# artefacts - so the provenance has to be recorded at capture time, in the file.
# --------------------------------------------------------------------------
class TestPixelProvenance(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name) / "clips"

    def tearDown(self):
        self.tmp.cleanup()

    LABELS = ["--dist", 2.5, "--bearing", -25, "--vis", 1,
              "--subject", "p01", "--light", "room"]

    def _clip_json(self):
        return json.loads(next(self.out.glob("*_clip.json")).read_text())

    def _chunks(self, path):
        return Image.open(path).text

    def test_raw_frames_are_stamped_raw(self):
        m = MockProcess("--count", 6, "--fps", 40)
        try:
            r = run_grab(m.port, self.out, "--n", 3, "--every", 1, *self.LABELS)
        finally:
            m.stop()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        for p in self.out.glob("*.png"):
            self.assertEqual(self._chunks(p)["pixel_provenance"], "raw", p.name)
            self.assertEqual(self._chunks(p)["cpx_image_format"], "0")
            self.assertEqual(self._chunks(p)["bayer_demosaiced"], "0")
        meta = self._clip_json()
        self.assertEqual(meta["pixel_provenance"], ["raw"])
        self.assertEqual(meta["raw_frames"], 3)
        self.assertEqual(meta["jpeg_decoded_frames"], 0)
        self.assertNotIn("not raw pixels", r.stdout)

    def test_jpeg_decoded_into_png_is_stamped_and_shouted_about(self):
        """--png on a JPEG stream: a .png whose pixels went through JPEG."""
        m = MockProcess("--count", 6, "--fps", 40, "--image-format", 1)
        try:
            r = run_grab(m.port, self.out, "--n", 3, "--every", 1, "--png", *self.LABELS)
        finally:
            m.stop()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        pngs = sorted(self.out.glob("*.png"))
        self.assertEqual(len(pngs), 3, "the frames were saved as .png, not .jpg")
        for p in pngs:
            # The extension says nothing. The file itself has to say it.
            self.assertEqual(p.suffix, ".png")
            self.assertEqual(self._chunks(p)["pixel_provenance"], "jpeg-decoded", p.name)
            self.assertEqual(self._chunks(p)["cpx_image_format"], "1")
        meta = self._clip_json()
        self.assertEqual(meta["pixel_provenance"], ["jpeg-decoded"])
        self.assertEqual(meta["jpeg_decoded_frames"], 3)
        self.assertEqual(meta["raw_frames"], 0)
        self.assertIn("NOT valid for scoring", r.stdout)
        self.assertIn("not raw pixels", r.stdout)

    def test_bayer_on_a_jpeg_stream_is_the_protocols_own_instruction(self):
        """The exact path the protocol drives an operator into on a colour deck."""
        m = MockProcess("--count", 6, "--fps", 40, "--image-format", 1)
        try:
            r = run_grab(m.port, self.out, "--n", 2, "--every", 1, "--bayer", *self.LABELS)
        finally:
            m.stop()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        for p in self.out.glob("*.png"):
            c = self._chunks(p)
            self.assertEqual(c["pixel_provenance"], "jpeg-decoded")
            self.assertEqual(c["bayer_demosaiced"], "1")
        self.assertEqual(self._clip_json()["jpeg_decoded_frames"], 2)
        self.assertIn("--bayer", r.stdout)

    def test_jpeg_kept_as_jpg_is_recorded_as_jpeg_not_jpeg_decoded(self):
        """No --png: the .jpg keeps the camera's own bytes and is labelled so."""
        m = MockProcess("--count", 6, "--fps", 40, "--image-format", 1)
        try:
            r = run_grab(m.port, self.out, "--n", 2, "--every", 1, *self.LABELS)
        finally:
            m.stop()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(len(list(self.out.glob("*.jpg"))), 2)
        self.assertEqual(len(list(self.out.glob("*.png"))), 0)
        meta = self._clip_json()
        self.assertEqual(meta["pixel_provenance"], ["jpeg"])
        self.assertEqual(meta["jpeg_decoded_frames"], 0, "a .jpg was not decoded")
        self.assertEqual(meta["raw_frames"], 0)

    def test_provenance_tells_the_two_apart_when_the_extension_cannot(self):
        """The blind spot itself: two .png clips, only the chunk separates them."""
        raw_out = Path(self.tmp.name) / "raw"
        m = MockProcess("--count", 6, "--fps", 40)
        try:
            run_grab(m.port, raw_out, "--n", 2, "--every", 1, *self.LABELS)
        finally:
            m.stop()
        m = MockProcess("--count", 6, "--fps", 40, "--image-format", 1)
        try:
            run_grab(m.port, self.out, "--n", 2, "--every", 1, "--png", *self.LABELS)
        finally:
            m.stop()
        a = sorted(raw_out.glob("*.png"))[0]
        b = sorted(self.out.glob("*.png"))[0]
        self.assertEqual(a.suffix, b.suffix)                   # extensions agree...
        self.assertNotEqual(self._chunks(a)["pixel_provenance"],
                            self._chunks(b)["pixel_provenance"])   # ...provenance does not
        self.assertEqual(self._chunks(a)["pixel_provenance"], grab.SCOREABLE_PROVENANCE)

    def test_the_stamp_does_not_touch_the_pixels(self):
        """A text chunk must not change a single pixel of the capture."""
        bank = Path(self.tmp.name) / "bank"
        m = MockProcess("--count", 6, "--fps", 40, "--save-bank", str(bank))
        try:
            r = run_grab(m.port, self.out, "--n", 3, "--every", 1)
        finally:
            m.stop()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        sent = [np.asarray(Image.open(p).convert("L")) for p in sorted(bank.glob("*.png"))]
        for p in sorted(self.out.glob("*.png")):
            got = np.asarray(Image.open(p).convert("L"))
            self.assertTrue(any(np.array_equal(got, s) for s in sent), p.name)


# --------------------------------------------------------------------------
# DEFECT 2: the mirror rehearsal has to serve two different bearings.
# One mock serving one bearing gives two IDENTICAL clips, one of them labelled
# with the wrong side, and a scorer verdict that means nothing.
# --------------------------------------------------------------------------
class TestTwoBearingRehearsal(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name) / "mirror"

    def tearDown(self):
        self.tmp.cleanup()

    @staticmethod
    def _darkest_column(path):
        """Where the (dark) person blob is. The procedural bank puts it at --bearing."""
        return int(np.argmin(np.asarray(Image.open(path).convert("L")).mean(axis=0)))

    def _clip(self, port, bearing):
        r = run_grab(port, self.out, "--n", 2, "--every", 1, "--dist", 2.5,
                     "--bearing", bearing, "--vis", 1, "--subject", "p01",
                     "--light", "room")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return sorted(self.out.glob(f"d2.5_b{bearing:g}_*.png"))

    def test_one_mock_serves_both_bearings_one_per_connection(self):
        m = MockProcess("--fps", 40, "--bearing", -25, "--bearing", 25)
        try:
            left = self._clip(m.port, -25)
            right = self._clip(m.port, 25)
            log = m.text()
        finally:
            m.stop()
        self.assertEqual((len(left), len(right)), (2, 2))
        self.assertIn("serving bearing -25 deg", log)
        self.assertIn("serving bearing 25 deg", log)
        a = np.asarray(Image.open(left[0]).convert("L"))
        b = np.asarray(Image.open(right[0]).convert("L"))
        self.assertFalse(np.array_equal(a, b),
                         "both clips are identical - the mirror rehearsal proves nothing")
        mid = a.shape[1] / 2
        self.assertLess(self._darkest_column(left[0]), mid,
                        "the b-25 clip must really have the person on the image's LEFT")
        self.assertGreater(self._darkest_column(right[0]), mid,
                           "the b+25 clip must really have the person on the image's RIGHT")

    def test_one_bearing_and_two_clips_is_the_trap_being_guarded_against(self):
        """Documents the old behaviour, so nobody 'simplifies' the fix away."""
        m = MockProcess("--fps", 40, "--bearing", -25)
        try:
            left, right = self._clip(m.port, -25), self._clip(m.port, 25)
        finally:
            m.stop()
        a = np.asarray(Image.open(left[0]).convert("L"))
        b = np.asarray(Image.open(right[0]).convert("L"))
        self.assertTrue(np.array_equal(a, b))     # same pixels, opposite labels
        self.assertLess(self._darkest_column(right[0]), a.shape[1] / 2,
                        "the clip LABELLED +25 still has the person on the left")

    def test_bearings_wrap_round_after_the_last_one(self):
        m = MockProcess("--fps", 40, "--bearing", -25, "--bearing", 25)
        try:
            first = self._clip(m.port, -25)
            self._clip(m.port, 25)
            third = run_grab(m.port, self.out, "--n", 2, "--every", 1, "--dist", 2.5,
                             "--bearing", -25, "--vis", 1, "--subject", "p01",
                             "--light", "room", "--take", 2)
            self.assertEqual(third.returncode, 0, third.stdout + third.stderr)
            third_files = sorted(self.out.glob("d2.5_b-25_*take2_*.png"))
        finally:
            m.stop()
        self.assertTrue(np.array_equal(
            np.asarray(Image.open(first[0]).convert("L")),
            np.asarray(Image.open(third_files[0]).convert("L"))),
            "connection 3 should be back to the first bearing")

    def test_comma_separated_bearings_parse_too(self):
        ap = mock.build_parser()
        self.assertEqual(mock.parse_bearings(ap, ["-25", "25"]), [-25.0, 25.0])
        self.assertEqual(mock.parse_bearings(ap, ["-25,25"]), [-25.0, 25.0])
        self.assertEqual(mock.parse_bearings(ap, None), [mock.DEFAULT_BEARING])

    def test_frames_folder_with_two_bearings_is_refused_not_silently_wrong(self):
        """--frames images come off disk; --bearing cannot change what they show."""
        src = flat_frames(Path(self.tmp.name) / "src", 3)
        r = subprocess.run(
            [sys.executable, str(MOCK_PY), "--port", "0", "--frames", str(src),
             "--bearing", "-25", "--bearing", "25"],
            capture_output=True, text=True, timeout=60)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("--bearing cannot change", r.stdout + r.stderr)


# --------------------------------------------------------------------------
# DEFECT 3: --frames must serve the WHOLE folder.
# It used to truncate the folder to --bank (default 24) and then loop, so a
# replayed clip silently became "the first 24 frames, over and over" and any
# number computed from it was a lie. Every other test passes --bank explicitly,
# which is exactly the case the bug did NOT show up in.
# --------------------------------------------------------------------------
class TestFramesFolderIsServedWhole(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name) / "clips"

    def tearDown(self):
        self.tmp.cleanup()

    def _serve(self, src, n_grab, *extra):
        """Start a mock on `src` WITHOUT --bank, grab n_grab frames."""
        log = tempfile.NamedTemporaryFile("w+", suffix=".log", delete=False)
        proc = subprocess.Popen(
            [sys.executable, str(MOCK_PY), "--port", "0", "--frames", str(src),
             "--fps", "60", "--once", *map(str, extra)],
            stdout=log, stderr=subprocess.STDOUT)
        try:
            port = None
            deadline = time.time() + 60
            while time.time() < deadline and port is None:
                m = re.search(r"streaming on tcp://[^:]+:(\d+)", Path(log.name).read_text())
                if m:
                    port = int(m.group(1))
                elif proc.poll() is not None:
                    raise RuntimeError(Path(log.name).read_text())
                else:
                    time.sleep(0.05)
            r = run_grab(port, self.out, "--n", n_grab, "--every", 1)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            return [grey_of(p) for p in sorted(self.out.glob("*.png"))], \
                Path(log.name).read_text()
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
            log.close()
            os.unlink(log.name)

    def test_a_folder_bigger_than_the_default_bank_is_not_truncated(self):
        # 30 > DEFAULT_BANK (24): the old code served frames 0..23 and then
        # looped back to frame 0, so greys 24..29 never arrived at all.
        n = mock.DEFAULT_BANK + 6
        src = flat_frames(Path(self.tmp.name) / "src", n)
        greys, log = self._serve(src, n)
        self.assertEqual(greys, [(k * 8) % 256 for k in range(n)],
                         "the folder was truncated or re-ordered")
        self.assertEqual(len(set(greys)), n, "some frames were served twice, others never")
        self.assertIn(f"({n} images)", log)
        self.assertNotIn("serving only the first", log)

    def test_it_loops_only_after_the_whole_folder_has_been_served(self):
        n = mock.DEFAULT_BANK + 6
        src = flat_frames(Path(self.tmp.name) / "src", n)
        greys, _ = self._serve(src, n + 3)
        self.assertEqual(greys[:n], [(k * 8) % 256 for k in range(n)])
        self.assertEqual(greys[n:], [0, 8, 16], "the wrap-round should restart at frame 0")

    def test_an_explicit_bank_still_caps_the_folder_and_says_so(self):
        src = flat_frames(Path(self.tmp.name) / "src", 10)
        greys, log = self._serve(src, 6, "--bank", 4)
        self.assertEqual(greys, [0, 8, 16, 24, 0, 8])
        self.assertIn("serving only the first 4", log)
        self.assertIn("drop --bank", log)

    def test_bank_larger_than_the_folder_serves_what_is_there(self):
        src = flat_frames(Path(self.tmp.name) / "src", 3)
        greys, log = self._serve(src, 5, "--bank", 50)
        self.assertEqual(greys, [0, 8, 16, 0, 8])
        self.assertNotIn("serving only the first", log)


# --------------------------------------------------------------------------
# DEFECT 4: Ctrl-C mid-clip. The operator WILL do this in the lab - it is how
# the runbook says to stop a clip early. Nothing protected the path.
# --------------------------------------------------------------------------
class TestSigintMidClip(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name) / "clips"

    def tearDown(self):
        self.tmp.cleanup()

    def _interrupt_after(self, n_frames, *grab_args):
        m = MockProcess("--fps", 25)
        try:
            p = start_grab(m.port, self.out, "--n", 500, "--every", 1, *grab_args)
            try:
                wait_for_frames(self.out, n_frames)
                time.sleep(0.1)
                p.send_signal(signal.SIGINT)
                stdout, _ = p.communicate(timeout=30)
            finally:
                if p.poll() is None:
                    p.kill()
                    p.communicate()
        finally:
            m.stop()
        return p.returncode, stdout

    def test_ctrl_c_keeps_the_frames_and_exits_cleanly(self):
        rc, stdout = self._interrupt_after(
            3, "--dist", 2.5, "--bearing", -25, "--vis", 1,
            "--subject", "p01", "--light", "room")
        self.assertEqual(rc, 0, f"Ctrl-C should not be a failure exit:\n{stdout}")
        self.assertIn("stopped by user", stdout)
        kept = sorted(self.out.glob("*.png"))
        self.assertGreaterEqual(len(kept), 3, stdout)
        # The first three were on disk before the signal was sent, so they are
        # complete; a later one may have been caught mid-write, which is fine.
        for p in kept[:3]:
            Image.open(p).load()       # a whole, readable image, not a stub

    def test_ctrl_c_still_writes_the_clip_json_and_says_why_it_stopped(self):
        """Without the JSON, an interrupted clip is indistinguishable from a full one."""
        rc, stdout = self._interrupt_after(
            3, "--dist", 2.5, "--bearing", -25, "--vis", 1,
            "--subject", "p01", "--light", "room")
        self.assertEqual(rc, 0, stdout)
        meta = json.loads(next(self.out.glob("*_clip.json")).read_text())
        self.assertIn("Ctrl-C", meta["stopped_because"])
        self.assertGreaterEqual(meta["saved"], 3)
        self.assertLessEqual(meta["saved"], len(list(self.out.glob("*.png"))))
        self.assertEqual(meta["pixel_provenance"], ["raw"])
        self.assertIn("WARNING: asked for 500 frames", stdout)

    def test_ctrl_c_before_any_frame_exits_1_and_leaves_no_folder(self):
        """A clip with nothing in it must not look like a successful recording."""
        m = MockProcess("--fps", 40, "--stall-after", 1, "--stall-seconds", 30)
        try:
            p = start_grab(m.port, self.out, "--n", 500, "--every", 5000,
                           "--timeout", 60)
            time.sleep(2.0)                       # connected, nothing saved yet
            p.send_signal(signal.SIGINT)
            stdout, _ = p.communicate(timeout=30)
        finally:
            if p.poll() is None:
                p.kill()
                p.communicate()
            m.stop()
        self.assertEqual(p.returncode, 1, stdout)
        self.assertIn("stopped by user", stdout)
        self.assertFalse(self.out.exists(),
                         "an empty interrupted clip must not leave a folder behind")


# --------------------------------------------------------------------------
# DEFECT 5: --stall-after used to park in `while True: time.sleep(0.5)`. It
# never noticed the client leaving, so --once could not fire and anything
# scripting the failure-mode demos hung until someone killed it by hand.
# --------------------------------------------------------------------------
class TestStallIsBounded(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name) / "clips"

    def tearDown(self):
        self.tmp.cleanup()

    @staticmethod
    def _wait_exit(proc, timeout):
        deadline = time.time() + timeout
        while proc.poll() is None and time.time() < deadline:
            time.sleep(0.1)
        return proc.poll()

    def test_once_exits_after_a_stall_when_the_client_gives_up(self):
        m = MockProcess("--fps", 40, "--stall-after", 2, "--once")
        try:
            r = run_grab(m.port, self.out, "--n", 10, "--every", 1, "--timeout", 2)
            self.assertIn("no data for 2 s", r.stdout)
            self.assertIsNotNone(
                self._wait_exit(m.proc, 25),
                "the mock is still parked in the stall after the client disconnected; "
                "--once never fires and a script driving this demo hangs")
            self.assertIn("the client disconnected", m.text())
        finally:
            m.stop()

    def test_stall_seconds_ends_the_stall_even_if_the_client_never_leaves(self):
        m = MockProcess("--fps", 40, "--stall-after", 1, "--stall-seconds", 2, "--once")
        try:
            s = socket.create_connection(("127.0.0.1", m.port), timeout=30)
            t0 = time.time()
            s.settimeout(30)
            try:
                while s.recv(65536):               # read until the mock closes on us
                    pass
            finally:
                s.close()
            waited = time.time() - t0
            self.assertGreaterEqual(waited, 1.5, "the stall ended too early")
            self.assertLess(waited, 20, "the stall never ended on its own")
            self.assertIsNotNone(self._wait_exit(m.proc, 25),
                                 "--once did not fire after a bounded stall")
            self.assertIn("stall ran out", m.text())
        finally:
            m.stop()

    def test_stall_seconds_without_stall_after_is_refused(self):
        r = subprocess.run([sys.executable, str(MOCK_PY), "--port", "0", "--synthetic",
                            "--bank", "2", "--stall-seconds", "1"],
                           capture_output=True, text=True, timeout=60)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("--stall-after", r.stdout + r.stderr)

    def test_an_unbounded_stall_is_announced_up_front(self):
        m = MockProcess("--fps", 40, "--stall-after", 1, "--once")
        try:
            # The banner MockProcess waits for is printed before this note, so
            # give the rest of the banner a moment to land.
            deadline = time.time() + 20
            while "--once cannot fire" not in m.text() and time.time() < deadline:
                time.sleep(0.05)
            self.assertIn("--stall-seconds", m.text())
            self.assertIn("--once cannot fire", m.text())
        finally:
            m.stop()


# --------------------------------------------------------------------------
# DEFECT 6: a JPEG frame does not leave the GAP8 as one contiguous buffer.
# wifi-img-streamer calls sendBufferViaCPX() three times (header tables /
# entropy data / EOI footer) whose lengths sum to the advertised size, so the
# wire carries three short tail chunks and three lastPacket flags per image.
# Reassembly has to be driven by the byte count, never by the lastPacket flag.
# --------------------------------------------------------------------------
class TestJpegThreePieceFraming(unittest.TestCase):

    def _jpeg(self, seed=30, w=324, h=244):
        g = one_frame(seed, w=w, h=h)
        return g, mock.encode_frame(g, 1)

    def test_the_three_pieces_sum_to_the_advertised_size(self):
        _, (w, h, d, f, payload) = self._jpeg()
        pieces = mock.jpeg_pieces(payload)
        self.assertEqual(len(pieces), 3, [len(p) for p in pieces])
        self.assertEqual(sum(len(p) for p in pieces), len(payload))
        self.assertEqual(b"".join(pieces), payload)
        self.assertTrue(pieces[0].startswith(b"\xff\xd8"))      # SOI + tables
        self.assertIn(b"\xff\xda", pieces[0])                   # ends at the SOS segment
        self.assertEqual(pieces[2], b"\xff\xd9")                # EOI footer alone

    def test_the_wire_carries_three_short_tails_and_three_last_flags(self):
        _, (w, h, d, f, payload) = self._jpeg()
        pieces = mock.jpeg_pieces(payload)
        chunk = 1020
        three = mock.image_packets(w, h, d, f, payload, chunk=chunk, pieces=pieces)
        one = mock.image_packets(w, h, d, f, payload, chunk=chunk)
        lasts = [i for i, p in enumerate(three) if p[2] & 0x40]
        self.assertEqual(len(lasts), 3, "one lastPacket per sendBufferViaCPX() call")
        self.assertEqual(len([i for i, p in enumerate(one) if p[2] & 0x40]), 1)
        tails = [len(p) - 4 for p in three[1:] if len(p) - 4 not in (chunk,)]
        self.assertEqual(len(tails), 3, f"expected three short tail chunks, got {tails}")
        self.assertGreater(len(three), len(one), "three buffers cost extra packets")

    def test_cpx_grab_reassembles_the_three_pieces_byte_for_byte(self):
        _, (w, h, d, f, payload) = self._jpeg()
        packets = mock.image_packets(w, h, d, f, payload, chunk=1020,
                                     pieces=mock.jpeg_pieces(payload))
        feed = Feeder(b"".join(packets))
        try:
            got = grab.recv_image(feed.reader(), stats={"short": 0})
        finally:
            feed.close()
        self.assertEqual(got[:4], (w, h, d, f))
        self.assertEqual(got[4], payload)
        Image.open(io.BytesIO(got[4])).load()

    def test_three_piece_framing_survives_a_hostile_tcp_split(self):
        _, (w, h, d, f, payload) = self._jpeg(31)
        for chunk in (12, 37, 1020):
            for piece in (1, 7):
                with self.subTest(chunk=chunk, tcp_piece=piece):
                    blob = b"".join(mock.image_packets(
                        w, h, d, f, payload, chunk=chunk,
                        pieces=mock.jpeg_pieces(payload)))
                    feed = Feeder(blob, piece=piece)
                    try:
                        got = grab.recv_image(feed.reader(), stats={"short": 0})
                    finally:
                        feed.close()
                    self.assertEqual(got[4], payload)

    def test_a_cut_short_three_piece_frame_is_dropped_not_spliced(self):
        _, (w, h, d, f, p1) = self._jpeg(32)
        _, (_, _, _, _, p2) = self._jpeg(33)
        cut = mock.image_packets(w, h, d, f, p1, chunk=1020, short_bytes=len(p1) // 2,
                                 pieces=mock.jpeg_pieces(p1))
        whole = mock.image_packets(w, h, d, f, p2, chunk=1020,
                                   pieces=mock.jpeg_pieces(p2))
        feed = Feeder(b"".join(cut + whole))
        stats = {"short": 0}
        try:
            got = grab.recv_image(feed.reader(), stats=stats)
        finally:
            feed.close()
        self.assertEqual(got[4], p2)
        self.assertEqual(stats["short"], 1)

    def test_not_a_jpeg_falls_back_to_a_single_piece(self):
        self.assertEqual(mock.jpeg_pieces(b"no markers here"), [b"no markers here"])
        self.assertEqual(b"".join(mock.jpeg_pieces(b"\xff\xd8\xff\xd9")), b"\xff\xd8\xff\xd9")

    def test_end_to_end_three_piece_jpeg_reaches_disk_intact(self):
        tmp = tempfile.TemporaryDirectory()
        try:
            out = Path(tmp.name) / "clips"
            m = MockProcess("--count", 6, "--fps", 30, "--image-format", 1,
                            "--tcp-chunk", 5, "--chunk", 37)
            try:
                r = run_grab(m.port, out, "--n", 3, "--every", 1)
                log = m.text()
            finally:
                m.stop()
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("JPEG in 3 buffers", log)
            jpgs = sorted(out.glob("*.jpg"))
            self.assertEqual(len(jpgs), 3)
            for p in jpgs:
                raw = p.read_bytes()
                self.assertTrue(raw.startswith(b"\xff\xd8"), p.name)
                self.assertTrue(raw.endswith(b"\xff\xd9"),
                                f"{p.name} lost its EOI - the footer buffer went missing")
                Image.open(p).load()
        finally:
            tmp.cleanup()

    def test_jpeg_one_piece_restores_the_contiguous_framing(self):
        tmp = tempfile.TemporaryDirectory()
        try:
            out = Path(tmp.name) / "clips"
            m = MockProcess("--count", 4, "--fps", 30, "--image-format", 1,
                            "--jpeg-one-piece")
            try:
                r = run_grab(m.port, out, "--n", 2, "--every", 1)
                log = m.text()
            finally:
                m.stop()
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertNotIn("JPEG in 3 buffers", log)
            self.assertIn("one buffer", log)
            self.assertEqual(len(list(out.glob("*.jpg"))), 2)
        finally:
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main(verbosity=2)
