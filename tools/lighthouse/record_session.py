#!/usr/bin/env python3
"""Record one Lighthouse ground-truth session: BOTH drones' poses plus the follower's frames.

    ~/Downloads/drone/cfloaderenv/bin/python tools/lighthouse/record_session.py \
        --seconds 90 --subject p01 --height 1.75 --mount 0.03 0 0

Plan: docs/hardware/before_the_next_session.md section 3; conventions and the clock-sync
protocol: tools/lighthouse/README.md ("Recording a session" has the copy-paste commands).

What it does, unattended (the laptop is on the deck's WiFi, so it has no internet and
nobody needs to touch it once it starts):
  1. checks the camera: which WiFi it is on, the deck's MAC address, and the brightness
     band (30-60, like grid_capture.sh; GRID_ACCEPT_ANY=1 records anyway);
  2. connects to the FOLLOWER (static on its stand, camera) and the BEACON (props off,
     on the subject's head), read-only, and refuses if the beacon still carries an
     AI-deck (its WiFi would have the same name as the follower's);
  3. finds the fastest pose log rate both links deliver through one Crazyradio;
  4. logs stateEstimate.x/y/z + stabilizer.roll/pitch/yaw for each drone, plus every
     Lighthouse status / Kalman variance / battery variable the firmware has, each row
     with BOTH the Crazyflie's timestamp and this laptop's receive time, while
     cpx_grab.py (trainenv) saves the follower's frames;
  5. speaks the sync protocol at the start and the end (stand still, step, stand still);
     CAMERA_CHECK_QUIET=1 mutes it;
  6. stops cleanly at the end, on Ctrl-C, or when a drone's link drops or goes silent,
     and writes poses_follower.csv, poses_beacon.csv, frames/, meta.json.
Then label it, offline: tools/lighthouse/label_session.py <session folder>.

--static logs ONLY the follower for --seconds (default 30), averages its pose, and prints
the pose_to_label.py command for the taped-mark case (README section "static taped-mark").

READ-ONLY, like tools/hardware/preflight.py, whose write guards it installs on both
drones before anything is sent: it never arms, never sends a setpoint, never writes a
parameter or memory. It only reads tables of contents, parameters and log blocks.

--mock rehearses everything with no hardware: CrazySim SITL drones (start them with
`bash tools/lighthouse/run_pair_sim.sh`) and tools/real_frames/mock_streamer.py, which
this tool starts itself. By default the BEACON is SCRIPTED (a software drone with its
own clock, a known boot offset and drift, walking the cue schedule) because a SITL drone
that never flies never moves, and nothing could be synchronised against it. The frames
show the same scripted subject, late by a KNOWN --mock-content-lag. Mock sessions are
written under ~/drone_frames/_rehearsal/, never next to real data.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import math
import os
import random
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
DRONE_ROOT = REPO.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO / "tools" / "hardware"))
import session_common as S  # noqa: E402

TRAINENV_PY = DRONE_ROOT / "trainenv" / "bin" / "python"
GRAB_PY = REPO / "tools" / "crazysim_macos" / "cpx_grab.py"
MOCK_PY = REPO / "tools" / "real_frames" / "mock_streamer.py"
RENDER_PY = HERE / "render_timeline.py"
DEFAULT_GEOMETRY = REPO / "docs" / "hardware" / "lighthouse" / "dorm_lighthouse_2026-09-24.yaml"

FOLLOWER_URI = "radio://0/80/2M/E7E7E7E709"     # drone "09": camera, on the stand
BEACON_URI = "radio://0/80/2M/E7E7E7E705"       # drone "05": props off, on the head
SITL_FOLLOWER_URI = "udp://127.0.0.1:19850"     # run_pair_sim.sh agent 0
SITL_BEACON_URI = "udp://127.0.0.1:19851"       # run_pair_sim.sh agent 1
DECK_HOST, DECK_PORT = "192.168.4.1", 5000
DECK_SSID = "WiFi streaming example"            # aideck-gap8-examples wifi-img-streamer.c line 179

STATUS_PERIOD_MS = 100
LINK_SILENT_S = 2.0          # no pose packet for this long = the link is gone
PRINT_EVERY_S = 10.0
LOW_VBAT = 3.4               # print a warning under this (a 350 mAh pack sags fast)
FIRST_FRAME_TIMEOUT_S = 20.0
PROBE_S = 3.0


class SessionError(Exception):
    """A refusal with a plain-English reason; nothing usable was recorded."""


def now_iso():
    return _dt.datetime.now().isoformat(timespec="seconds")


def quiet():
    return bool(os.environ.get("CAMERA_CHECK_QUIET"))


def speak(text):
    """Spoken cue (macOS `say`, in the background). CAMERA_CHECK_QUIET=1 mutes it."""
    if quiet() or not shutil.which("say"):
        return
    try:
        subprocess.Popen(["say", text], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        pass


def sha256_file(path):
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None


def git_state(repo=REPO):
    def run(*a):
        try:
            return subprocess.run(["git", "-C", str(repo), *a], capture_output=True, text=True,
                                  timeout=10).stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            return ""
    return dict(sha=run("rev-parse", "HEAD") or None, branch=run("rev-parse", "--abbrev-ref", "HEAD") or None,
                dirty=bool(run("status", "--porcelain", "--", "tools/lighthouse")))


def write_json_atomic(path, obj):
    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=1, default=str))
    os.replace(tmp, path)


def default_out(mock, now=None):
    now = now or _dt.datetime.now()
    root = Path.home() / "drone_frames"
    if mock:
        root = root / "_rehearsal"                  # mock runs never land next to real data
    return root / f"{now:%Y-%m-%d}" / f"lh_session_{now:%H%M%S}"


# --------------------------------------------------------------------------
# writing: one CSV per drone, rows as they arrive
# --------------------------------------------------------------------------
class PoseWriter:
    """poses_<role>.csv. One row per pose packet; status columns are the latest status
    sample (sample-and-hold), and status_t_cf_ms says which one. Thread-safe: cflib calls
    the callbacks from its own thread."""

    def __init__(self, path, status_vars):
        self.path = Path(path)
        self.status_vars = list(status_vars)
        self.f = open(self.path, "w", newline="")
        self.f.write(",".join(S.pose_csv_header(self.status_vars)) + "\n")
        self.lock = threading.Lock()
        self.status = {}
        self.status_t = None
        self.t_cf, self.t_laptop = [], []
        self.status_t_cf = []
        self.vbat = []               # (t_laptop, volts)
        self.last_rx = None

    @staticmethod
    def _fmt(v):
        if v is None:
            return ""
        if isinstance(v, float):
            return "" if v != v else repr(round(v, 7))
        return str(v)

    def on_status(self, t_cf_ms, t_laptop, values):
        with self.lock:
            self.status.update(values)
            self.status_t = t_cf_ms
            self.status_t_cf.append(t_cf_ms)
            if "pm.vbat" in values:
                self.vbat.append((t_laptop, float(values["pm.vbat"])))

    def on_pose(self, t_cf_ms, t_laptop, pose):
        with self.lock:
            row = [str(int(t_cf_ms)), f"{t_laptop:.6f}"] + [self._fmt(pose.get(c)) for c in S.POSE_COLS]
            row += [self._fmt(self.status.get(v)) for v in self.status_vars]
            row.append("" if self.status_t is None else str(int(self.status_t)))
            self.f.write(",".join(row) + "\n")
            self.t_cf.append(t_cf_ms)
            self.t_laptop.append(t_laptop)
            self.last_rx = t_laptop

    def flush(self):
        with self.lock:
            if not self.f.closed:
                self.f.flush()

    def close(self):
        with self.lock:
            if not self.f.closed:
                self.f.close()

    def battery(self):
        v = [x for _, x in self.vbat]
        if not v:
            return dict(start=None, end=None, min=None)
        return dict(start=round(v[0], 3), end=round(v[-1], 3), min=round(min(v), 3))


# --------------------------------------------------------------------------
# the drones: real (cflib) and scripted (rehearsal)
# --------------------------------------------------------------------------
class DroneLink:
    """One Crazyflie over cflib, read-only. Wraps tools/hardware/preflight.CflibLink, which
    installs the write guards before connecting and closes without the zero setpoint that
    the guards (correctly) refuse."""

    scripted = False

    def __init__(self, role, uri, connect_timeout=20.0):
        from preflight import CflibLink
        self.role, self.uri = role, uri
        self.link = CflibLink(uri, connect_timeout=connect_timeout,
                              cache_dir=Path.home() / ".cache" / "record_session")
        self.lost = threading.Event()
        self.lost_why = None
        self._logs = []
        self.link_quality = []

    def open(self):
        dt = self.link.open()
        cf = self.link.cf
        cf.connection_lost.add_callback(lambda _u, msg: self._mark_lost(f"connection lost: {msg}"))
        cf.disconnected.add_callback(lambda _u: self._mark_lost("disconnected"))
        try:
            cf.link_statistics.link_quality_updated.add_callback(lambda q: self.link_quality.append(float(q)))
        except AttributeError:
            pass
        self.link.wait_params()
        return dt

    def _mark_lost(self, why):
        if not self.lost.is_set():
            self.lost_why = why
            self.lost.set()

    def info(self):
        L = self.link
        p = L.param_value
        rev = None
        try:
            from preflight import firmware_git_revision
            rev = firmware_git_revision(p("firmware.revision0"), p("firmware.revision1"))
        except Exception:
            pass
        return dict(uri=self.uri, tag=L.platform_query(1), protocol=L.protocol_version(),
                    revision=rev, modified=p("firmware.modified"),
                    deck_lighthouse=p("deck.bcLighthouse4"), deck_aideck=p("deck.bcAI"),
                    write_guards=len(L.guarded))

    def log_toc(self):
        return self.link.log_toc()

    def start_logging(self, pose_period_ms, status_vars, on_pose, on_status, status_period_ms=STATUS_PERIOD_MS):
        from cflib.crazyflie.log import LogConfig
        from preflight import chunk_log_vars
        toc = self.log_toc()
        cf = self.link.cf

        def pose_cb(ts, data, _lc):
            t = time.time()
            on_pose(ts, t, {c: data.get(v) for c, v in S.POSE_VARS.items()})

        def status_cb(ts, data, _lc):
            on_status(ts, time.time(), dict(data))

        blocks = [(f"lh_pose_{self.role}", pose_period_ms, list(S.POSE_VARS.values()), pose_cb)]
        typed = [(v, toc[v.split(".")[0]][v.split(".")[1]]) for v in status_vars]
        for i, blk in enumerate(chunk_log_vars(typed)):
            blocks.append((f"lh_status_{self.role}{i}", status_period_ms, blk, status_cb))
        for name, period, names, cb in blocks:
            lc = LogConfig(name=name, period_in_ms=period)
            for n in names:
                lc.add_variable(n)
            cf.log.add_config(lc)
            if not lc.valid:
                raise SessionError(f"{self.role}: the drone refused log block {names}")
            lc.data_received_cb.add_callback(cb)
            lc.error_cb.add_callback(lambda _lc, msg: self._mark_lost(f"log error: {msg}"))
            lc.start()
            self._logs.append(lc)

    def stop_logging(self):
        for lc in self._logs:
            for fn in (lc.stop, lc.delete):
                try:
                    fn()
                except Exception:
                    pass
        self._logs = []

    def close(self):
        self.link.close()


class ScriptedDrone:
    """REHEARSAL ONLY. A software Crazyflie that emits log packets like DroneLink does,
    from a position function, on its OWN clock: t_cf_ms = (t - t_boot) * 1000 * (1 + drift),
    received `latency` seconds later. Every injected number is written to meta.json so the
    rehearsal can check label_session recovers it. It exercises everything downstream of
    the cflib callback; it says nothing about a real radio."""

    scripted = True

    def __init__(self, role, position_fn, boot_age_s=37.25, drift_ppm=50.0, latency_s=(0.002, 0.008),
                 vbat0=4.10, seed=1):
        self.role, self.uri = role, f"scripted://{role}"
        self.position_fn = position_fn
        self.t_boot = time.time() - boot_age_s
        self.drift = drift_ppm * 1e-6
        self.latency = latency_s
        self.vbat0 = vbat0
        self.rng = random.Random(seed)
        self.lost = threading.Event()
        self.lost_why = None
        self.link_quality = []
        self._stop = threading.Event()
        self._threads = []
        self.injected = dict(boot_age_s=boot_age_s, t_boot_unix=self.t_boot, drift_ppm=drift_ppm,
                             rx_latency_s=list(latency_s))

    def open(self):
        return 0.0

    def info(self):
        return dict(uri=self.uri, tag="scripted", protocol=None, revision=None, modified=None,
                    deck_lighthouse=1, deck_aideck=0, write_guards=0, scripted=self.injected)

    def log_toc(self):
        return {"lighthouse": {"status": "uint8_t", "bsActive": "uint16_t"}, "pm": {"vbat": "float"}}

    def t_cf_ms(self, t):
        return int((t - self.t_boot) * 1000.0 * (1.0 + self.drift))

    def _run(self, period_s, fn):
        nxt = time.time()
        while not self._stop.is_set():
            t_true = time.time()
            fn(t_true)
            nxt += period_s
            delay = nxt - time.time()
            if delay > 0:
                self._stop.wait(delay)
            else:
                nxt = time.time()

    def start_logging(self, pose_period_ms, status_vars, on_pose, on_status, status_period_ms=STATUS_PERIOD_MS):
        self._stop.clear()

        def deliver(t_true, cb, values):
            # the receive time is LATER than the sample time by the simulated radio latency
            cb(self.t_cf_ms(t_true), t_true + self.rng.uniform(*self.latency), values)

        def pose(t_true):
            x, y, z, roll, pitch, yaw = self.position_fn(t_true)
            deliver(t_true, on_pose, dict(x=x, y=y, z=z, roll=roll, pitch=pitch, yaw=yaw))

        def status(t_true):
            vals = {"lighthouse.status": 2, "lighthouse.bsActive": 3,
                    "pm.vbat": round(self.vbat0 - 0.0005 * (t_true - self.t_boot), 3)}
            deliver(t_true, on_status, {k: v for k, v in vals.items() if k in status_vars})

        for period, fn in ((pose_period_ms / 1000.0, pose), (status_period_ms / 1000.0, status)):
            th = threading.Thread(target=self._run, args=(period, fn), daemon=True)
            th.start()
            self._threads.append(th)

    def stop_logging(self):
        self._stop.set()
        for th in self._threads:
            th.join(2.0)
        self._threads = []

    def close(self):
        self.stop_logging()


def pick_status_vars(log_toc, wanted=S.STATUS_WANTED, uri=""):
    """The STATUS_WANTED variables this drone actually has, plus any other lighthouse.bs*
    bitmask (so a renamed or new one is not silently skipped). radio.rssi only on a radio link."""
    out = []
    for v in wanted:
        g, n = v.split(".")
        if n in log_toc.get(g, {}) and not (g == "radio" and not uri.startswith("radio://")):
            out.append(v)
    for n in sorted(log_toc.get("lighthouse", {})):
        v = f"lighthouse.{n}"
        if n.startswith("bs") and v not in out and log_toc["lighthouse"][n].startswith("uint"):
            out.append(v)
    return out


# --------------------------------------------------------------------------
# the camera side: which deck, how bright, the grabber
# --------------------------------------------------------------------------
def wifi_device():
    try:
        out = subprocess.run(["networksetup", "-listallhardwareports"], capture_output=True, text=True,
                             timeout=5).stdout
    except (OSError, subprocess.TimeoutExpired):
        return "en0"
    m = re.search(r"Hardware Port: (?:Wi-Fi|AirPort)\s*\nDevice: (\S+)", out)
    return m.group(1) if m else "en0"


def wifi_ssid():
    """The SSID this Mac is joined to, best effort (recent macOS may redact it without
    location permission, in which case this returns None and the MAC check is what counts)."""
    dev = wifi_device()
    for cmd in (["ipconfig", "getsummary", dev], ["networksetup", "-getairportnetwork", dev]):
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=5).stdout
        except (OSError, subprocess.TimeoutExpired):
            continue
        m = re.search(r"^\s*SSID\s*:\s*(.+?)\s*$", out, re.M) or re.search(r"Current Wi-Fi Network:\s*(.+)$", out, re.M)
        if m and "redacted" not in m.group(1).lower():
            return m.group(1).strip()
    return None


def deck_mac(host=DECK_HOST, port=DECK_PORT):
    """MAC address of whatever answers at the deck's IP: the ESP32's own soft-AP address, so
    it differs between two decks even when their SSIDs are identical. None if unknown."""
    try:
        socket.create_connection((host, port), timeout=2).close()
    except OSError:
        pass
    try:
        out = subprocess.run(["arp", "-n", host], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    m = re.search(r" at ([0-9a-f]{1,2}(?::[0-9a-f]{1,2}){5}) ", out, re.I)
    return ":".join(f"{int(x, 16):02x}" for x in m.group(1).split(":")) if m else None


def norm_mac(s):
    return None if not s else ":".join(f"{int(x, 16):02x}" for x in re.split(r"[:-]", s.strip()))


BRIGHTNESS_CODE = ("import glob,sys,numpy as n;from PIL import Image;"
                   "fs=glob.glob(sys.argv[1]+'/*.png')+glob.glob(sys.argv[1]+'/*.jpg');"
                   "print(f'{n.mean([n.asarray(Image.open(f).convert(\"L\")).mean() for f in fs]):.1f}' if fs else '-1')")


def measure_brightness(host, port, n=5):
    """Mean brightness of n frames from the stream (cpx_grab and numpy run in trainenv)."""
    with tempfile.TemporaryDirectory(prefix="lh_bright_") as tmp:
        r = subprocess.run([str(TRAINENV_PY), str(GRAB_PY), "--host", host, "--port", str(port),
                            "--n", str(n), "--every", "1", "--timeout", "8", "--out", tmp],
                           capture_output=True, text=True, timeout=90)
        if r.returncode != 0 and not os.listdir(tmp):
            return None
        out = subprocess.run([str(TRAINENV_PY), "-c", BRIGHTNESS_CODE, tmp], capture_output=True, text=True,
                             timeout=60).stdout.strip()
    try:
        v = float(out)
    except ValueError:
        return None
    return None if v < 0 else v


def start_grabber(host, port, frames_dir, seconds, log_path):
    """cpx_grab.py in trainenv, unlabelled, every frame, for `seconds`. Frames are named
    frame_<n>_<unix arrival time>.png - the laptop clock label_session aligns on."""
    log = open(log_path, "w")
    proc = subprocess.Popen([str(TRAINENV_PY), "-u", str(GRAB_PY), "--host", host, "--port", str(port),
                             "--seconds", f"{seconds:.1f}", "--every", "1", "--timeout", "10",
                             "--out", str(frames_dir)], stdout=log, stderr=subprocess.STDOUT)
    return proc, log


def stop_process(proc, sig=signal.SIGINT, wait=8.0):
    if proc is None or proc.poll() is not None:
        return None if proc is None else proc.returncode
    try:
        proc.send_signal(sig)
        return proc.wait(wait)
    except subprocess.TimeoutExpired:
        proc.kill()
        return proc.wait(5)


def find_scene(name):
    """A scenes_v2 scene (generated, gitignored): this checkout's, else the main checkout's."""
    p = Path(name).expanduser()
    if p.is_file():
        return p
    for root in (REPO, DRONE_ROOT / "pytorch_ssd"):
        q = root / "tools" / "crazysim_macos" / "scenes_v2" / name / "scene.xml"
        if q.is_file():
            return q
    return None


def start_mock_streamer(a, timeline=None, epoch=None, log_path=None):
    """mock_streamer.py (trainenv) on a free local port; returns (proc, port)."""
    cmd = [str(TRAINENV_PY), "-u", str(MOCK_PY), "--port", "0", "--fps", f"{a.mock_fps:g}"]
    if timeline:
        cmd += ["--timeline", str(timeline), "--epoch", f"{epoch:.6f}", "--content-lag", f"{a.mock_content_lag:g}",
                "--stamp-time"]
    else:
        scene = find_scene(a.mock_scene)
        cmd += ["--scene", str(scene)] if scene else ["--synthetic"]
    log = open(log_path, "w")
    proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT)
    deadline = time.time() + 120
    while time.time() < deadline:
        m = re.search(r"streaming on tcp://[^:]+:(\d+)", Path(log_path).read_text())
        if m:
            return proc, int(m.group(1))
        if proc.poll() is not None:
            raise SessionError("mock_streamer.py exited:\n" + Path(log_path).read_text()[-1500:])
        time.sleep(0.1)
    proc.kill()
    raise SessionError("mock_streamer.py did not start within 120 s")


# --------------------------------------------------------------------------
# the run
# --------------------------------------------------------------------------
def connect(role, uri, scripted_fn=None, mock_cfg=None):
    if scripted_fn is not None:
        d = ScriptedDrone(role, scripted_fn, **(mock_cfg or {}))
    else:
        d = DroneLink(role, uri)
    try:
        dt = d.open()
    except Exception as e:  # noqa: BLE001  (preflight.ConnectError carries the plain-English hint)
        hint = ""
        if uri.startswith("udp://"):
            hint = "\n  Start the simulated pair first:  bash tools/lighthouse/run_pair_sim.sh"
        raise SessionError(f"could not connect to the {role} at {uri}: {e}{hint}")
    print(f"   {role:<8} {d.uri}: connected in {dt:.1f} s")
    return d


def probe_rates(drones, first_period, seconds=PROBE_S, log=print):
    """Log poses on every link at once, fastest period first, until one delivers >= 95% on
    all of them. Returns (chosen period, {period: {role: rate_stats}})."""
    tried = {}
    for period in [p for p in S.POSE_PERIODS_MS if p >= first_period]:
        got = {d.role: [] for d in drones}
        for d in drones:
            d.start_logging(period, [], lambda ts, _t, _v, r=d.role: got[r].append(ts), lambda *a: None)
        time.sleep(seconds)
        for d in drones:
            d.stop_logging()
        tried[period] = {r: S.rate_stats(ts, period) for r, ts in got.items()}
        msg = ", ".join(f"{r} {st['achieved_hz'] or 0:.1f} Hz ({(st['delivery'] or 0) * 100:.0f}%)"
                        for r, st in tried[period].items())
        log(f"   rate probe {1000 / period:5.1f} Hz requested: {msg}")
        if S.pick_period({period: {r: st["delivery"] for r, st in tried[period].items()}}) == period:
            return period, tried
    return S.POSE_PERIODS_MS[-1], tried


FIRST_POSE_TIMEOUT_S = 3.0


def wait_for_poses(writer, timeout):
    """True once `writer` has received at least 5 pose rows (within `timeout` seconds)."""
    end = time.time() + timeout
    while time.time() < end:
        if len(writer.t_cf) >= 5:
            return True
        time.sleep(0.05)
    return len(writer.t_cf) >= 5


def static_summary(cols):
    """Mean pose (circular mean for angles) and spread of a still follower."""
    def finite(v):
        return [x for x in v if x == x]
    out = {}
    for c in ("x", "y", "z", "roll", "pitch"):
        v = finite(cols.get(c, []))
        if v:
            m = sum(v) / len(v)
            out[c] = round(m, 4)
            out[c + "_std"] = round(math.sqrt(sum((x - m) ** 2 for x in v) / len(v)), 4)
    v = finite(cols.get("yaw", []))
    if v:
        s, c = sum(math.sin(math.radians(a)) for a in v), sum(math.cos(math.radians(a)) for a in v)
        out["yaw"] = round(math.degrees(math.atan2(s, c)), 3)
        out["yaw_std"] = round(math.sqrt(sum((((a - out["yaw"]) + 180) % 360 - 180) ** 2 for a in v) / len(v)), 3)
    out["n"] = len(v)
    return out


def build_parser():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--follower-uri", default=None,
                    help=f"default {FOLLOWER_URI} (drone 09); usb://0 runs it on the cable / hub power")
    ap.add_argument("--beacon-uri", default=None, help=f"default {BEACON_URI} (drone 05)")
    ap.add_argument("--seconds", type=float, default=None,
                    help=f"recording length (default 90; >= {S.MIN_SECONDS:g}); with --static, 30")
    ap.add_argument("--subject", default="p01", help="subject label (letters, digits, '-'); never a name")
    ap.add_argument("--height", type=float, default=None, help="subject's measured standing height, m")
    ap.add_argument("--beacon-above-head", type=float, default=0.0,
                    help="height of the beacon's Lighthouse deck above the top of the head, m")
    ap.add_argument("--mount", nargs=3, type=float, default=(0.03, 0.0, 0.0), metavar=("MX", "MY", "MZ"),
                    help="lens position in the follower's body frame, m (MEASURE it; default is the simulator's)")
    ap.add_argument("--static", action="store_true",
                    help="follower only: log its pose for --seconds (30) while it sits still, average it")
    ap.add_argument("--mark", nargs=2, type=float, default=None, metavar=("X", "Y"),
                    help="with --static: the subject's taped mark in the room frame; prints the label")
    ap.add_argument("--pose-hz", type=float, default=100.0, help="fastest pose rate to try (default 100)")
    ap.add_argument("--no-probe", action="store_true", help="skip the rate probe; log at --pose-hz")
    ap.add_argument("--geometry", default=str(DEFAULT_GEOMETRY), help="Lighthouse geometry file on both drones")
    ap.add_argument("--follower-deck-mac", default=None,
                    help="refuse unless the deck at 192.168.4.1 has this MAC (get it with --identify-deck)")
    ap.add_argument("--allow-beacon-aideck", action="store_true",
                    help="record even though the beacon reports an AI-deck (its WiFi has the SAME name)")
    ap.add_argument("--identify-deck", action="store_true",
                    help="print the WiFi name and the MAC of the deck at 192.168.4.1, then exit")
    ap.add_argument("--out", default=None,
                    help="session folder (default ~/drone_frames/<date>/lh_session_<HHMMSS>/; "
                         "--mock: ~/drone_frames/_rehearsal/<date>/...)")
    g = ap.add_argument_group("rehearsal (--mock): no hardware")
    g.add_argument("--mock", action="store_true",
                   help=f"CrazySim SITL ({SITL_FOLLOWER_URI}, {SITL_BEACON_URI}) + mock_streamer.py")
    g.add_argument("--mock-beacon", choices=("scripted", "sitl"), default="scripted",
                   help="scripted (default): a software beacon that walks the cue schedule; "
                        "sitl: the SITL drone, which never moves (plumbing only; nothing to align)")
    g.add_argument("--mock-follower", choices=("sitl", "scripted"), default="sitl",
                   help="scripted: a software follower at (0, 0, 0.8) facing +x; no Docker needed")
    g.add_argument("--mock-follower-yaw", type=float, default=0.0,
                   help="scripted follower's yaw, deg (rehearse the taped-mark case's 30 deg LEFT turn)")
    g.add_argument("--mock-fps", type=float, default=2.0, help="mock frame rate (the real deck sends ~2 fps)")
    g.add_argument("--mock-content-lag", type=float, default=0.15,
                   help="KNOWN injected delay: each mock frame shows the subject this many s earlier")
    g.add_argument("--mock-dist", type=float, default=2.5, help="scripted subject's distance ahead, m")
    g.add_argument("--mock-scene", default="s15_static_offset")
    g.add_argument("--mock-lead", type=float, default=25.0,
                   help="seconds from launch to the scripted clock's zero (setup must finish first)")
    return ap


def main(argv=None):
    ap = build_parser()
    a = ap.parse_args(argv)
    if not re.fullmatch(r"[A-Za-z0-9-]+", a.subject):
        ap.error("--subject may only use letters, digits and '-' (a label like p01, never a name)")
    if a.seconds is None:
        a.seconds = 30.0 if a.static else 90.0
    if not a.static and a.seconds < S.MIN_SECONDS:
        ap.error(f"--seconds must be at least {S.MIN_SECONDS:g}: the start and end sync blocks take 10 s each")
    if not a.static and a.seconds < 60:
        print(f"note: {a.seconds:g} s is short. At the deck's ~2 fps the clock alignment needs walking frames "
              "around both sync steps; the rehearsal was 3.5 ms off at 90 s but 48 ms off at 40 s.")
    if a.mark and not a.static:
        ap.error("--mark is for --static (the taped-mark case)")
    if a.mark and a.height is None:
        ap.error("--mark needs --height (the subject's measured height)")
    if a.follower_uri is None:
        a.follower_uri = SITL_FOLLOWER_URI if a.mock else FOLLOWER_URI
    if a.beacon_uri is None:
        a.beacon_uri = SITL_BEACON_URI if a.mock else BEACON_URI
    if a.identify_deck:
        print(f"WiFi: {wifi_ssid() or 'unknown (macOS may hide it)'}   deck at {DECK_HOST}: MAC {deck_mac() or 'unknown'}")
        print("Run this with ONLY ONE drone powered, once per drone, and write the MACs down.")
        return 0
    try:
        return run(a)
    except SessionError as e:
        print(f"\nREFUSED: {e}")
        return 2


def run(a):
    started = time.time()
    out = Path(a.out).expanduser() if a.out else default_out(a.mock)
    if out.exists() and any(out.iterdir()):
        raise SessionError(f"{out} already exists and is not empty; pick another --out")
    out.mkdir(parents=True, exist_ok=True)
    frames_dir = out / S.FRAMES_DIR
    real = not a.mock
    roles = ["follower"] if a.static else ["follower", "beacon"]
    meta = dict(tool="tools/lighthouse/record_session.py", tool_git=git_state(), created=now_iso(),
                mode="static" if a.static else "session", mock=bool(a.mock), out=str(out),
                uris={r: getattr(a, f"{r}_uri") for r in roles}, subject=a.subject, height_m=a.height,
                beacon_above_head_m=a.beacon_above_head, mount_xyz_body=list(a.mount),
                geometry=dict(path=os.path.relpath(a.geometry, REPO) if str(a.geometry).startswith(str(REPO)) else a.geometry,
                              sha256=sha256_file(a.geometry)),
                label_target=dict(target_frac=0.5, note="label target = feet + 0.5 x height (head - 1/2 height); "
                                  "OPEN team decision, see tools/lighthouse/README.md"),
                seconds_requested=a.seconds, warnings=[], status="started")
    meta_path = out / S.META_JSON
    write_json_atomic(meta_path, meta)
    print(f"== Lighthouse session recorder  ({'MOCK REHEARSAL' if a.mock else 'REAL HARDWARE'}, "
          f"{'static follower' if a.static else 'two drones'})\n   folder: {out}")
    print("   Read-only: nothing here can arm the motors or move either drone.")

    procs, logs, drones, writers = [], [], {}, {}
    stop = dict(why=None)
    stop_evt = threading.Event()

    def request_stop(why):
        if not stop_evt.is_set():
            stop["why"] = why
            stop_evt.set()

    old_int = signal.signal(signal.SIGINT, lambda *_: request_stop("you stopped it (Ctrl-C)"))
    grab = grab_log = None
    host, port = DECK_HOST, DECK_PORT
    epoch = None
    try:
        # ---------------- the camera side
        if not a.static:
            if a.mock:
                timeline = None
                if a.mock_beacon == "scripted":
                    timeline = out / "_mock_timeline.npz"
                    print(f"-- rendering the scripted subject's frames ({a.seconds:g} s at {a.mock_dist:g} m) ...")
                    r = subprocess.run([str(TRAINENV_PY), str(RENDER_PY), "--seconds", f"{a.seconds:g}",
                                        "--dist", f"{a.mock_dist:g}", "--scene", a.mock_scene, "--out", str(timeline)],
                                       capture_output=True, text=True, timeout=600)
                    if r.returncode != 0:
                        raise SessionError("render_timeline.py failed:\n" + (r.stdout + r.stderr)[-1500:])
                    print("   " + r.stdout.strip().splitlines()[-1])
                    epoch = time.time() + a.mock_lead
                mproc, port = start_mock_streamer(a, timeline, epoch, out / "_mock_streamer.log")
                procs.append(mproc)
                host = "127.0.0.1"
                meta["mock_details"] = dict(beacon=a.mock_beacon, follower=a.mock_follower, fps=a.mock_fps,
                                            content_lag_s=a.mock_content_lag if timeline else None,
                                            epoch_unix=epoch, dist_m=a.mock_dist, scene=a.mock_scene,
                                            streamer_port=port,
                                            note="REHEARSAL: no hardware; SITL and/or scripted drones")
                print(f"   mock streamer on tcp://127.0.0.1:{port}  ({a.mock_fps:g} fps)")
            else:
                ssid, mac = wifi_ssid(), deck_mac()
                meta["deck"] = dict(ssid=ssid, mac=mac, expected_mac=norm_mac(a.follower_deck_mac), mac_changes=[])
                print(f"-- camera WiFi: {ssid or 'unknown (macOS hides the name without location access)'}; "
                      f"deck at {DECK_HOST}: MAC {mac or 'unknown'}")
                print(f"   !! BOTH AI-decks call themselves '{DECK_SSID}'. These frames must come from the "
                      "FOLLOWER (09).\n   !! Drone 05's AI-deck must be unplugged or removed (README checklist).")
                if a.follower_deck_mac and mac and norm_mac(a.follower_deck_mac) != mac:
                    raise SessionError(f"the deck at {DECK_HOST} is {mac}, not the follower's "
                                       f"{norm_mac(a.follower_deck_mac)}: the laptop joined the WRONG drone's WiFi")
                if a.follower_deck_mac and not mac:
                    meta["warnings"].append("could not read the deck's MAC; --follower-deck-mac not checked")
            print("-- brightness check (5 frames) ...")
            mean = measure_brightness(host, port)
            gate = S.brightness_gate(mean)
            meta["brightness"] = gate
            write_json_atomic(meta_path, meta)
            print(f"   mean brightness {mean if mean is not None else '-'} (0-255): {gate['why']}")
            if real:
                try:
                    with open(Path.home() / "drone_frames" / "exposure_log.txt", "a") as f:
                        f.write(f"{_dt.datetime.now():%F %T} drone=09 brightness={mean} source=record_session"
                                f"{'' if gate['ok'] else ' rejected'}\n")
                except OSError:
                    pass
            if not gate["ok"]:
                speak("Brightness out of range. Unplug and replug the battery." if (mean or 0) >= S.BLACK_BELOW
                      else "The camera is black. Unplug and replug the battery.")
                raise SessionError(gate["why"] + ". Nothing was recorded.")
            speak("Get to your start mark and stand still.")

        # ---------------- the drones
        print("-- connecting (read-only) ...")
        import_cflib = any(not (a.mock and ((r == "beacon" and a.mock_beacon == "scripted") or
                                            (r == "follower" and a.mock_follower == "scripted"))) for r in roles)
        if import_cflib:
            import cflib.crtp
            cflib.crtp.init_drivers()
        mock_cfg = dict(beacon=dict(boot_age_s=37.25, drift_ppm=50.0, seed=11),
                        follower=dict(boot_age_s=812.5, drift_ppm=-30.0, seed=12))
        t0_box = {}

        def beacon_fn(t):
            t0 = t0_box.get("t0", epoch)
            rel = (t - t0) if t0 is not None else -1.0
            h = (a.height or 1.75) + a.beacon_above_head
            return (a.mock_dist, S.scripted_lateral(rel, a.seconds), h, 0.0, 0.0, 0.0)   # x y z roll pitch yaw

        def follower_fn(_t):
            return (0.0, 0.0, 0.8, 0.0, 0.0, a.mock_follower_yaw)      # x y z roll pitch yaw

        for r in roles:
            uri = getattr(a, f"{r}_uri")
            scripted = None
            if a.mock and r == "beacon" and a.mock_beacon == "scripted":
                scripted = beacon_fn
            if a.mock and r == "follower" and a.mock_follower == "scripted":
                scripted = follower_fn
            drones[r] = connect(r, uri, scripted, mock_cfg[r])
        meta["firmware"] = {r: d.info() for r, d in drones.items()}
        for r, inf in meta["firmware"].items():
            print(f"   {r:<8} firmware {inf['tag']} protocol {inf['protocol']}, Lighthouse deck "
                  f"{inf['deck_lighthouse']}, AI-deck {inf['deck_aideck']}, {inf['write_guards']} write methods locked")
            if str(inf["deck_lighthouse"]) not in ("1",):
                meta["warnings"].append(f"{r}: no Lighthouse deck reported (deck.bcLighthouse4 = {inf['deck_lighthouse']})")
                print(f"   !! {r}: the firmware reports NO Lighthouse deck" + (" (expected in SITL)" if a.mock else ""))
        if "beacon" in drones and str(meta["firmware"]["beacon"]["deck_aideck"]) == "1":
            msg = ("the BEACON reports an AI-deck. Its WiFi has the same name as the follower's, so the laptop "
                   "may be streaming the WRONG camera, and it drains the 350 mAh pack in 5-7 min. Unplug it "
                   "(or pass --allow-beacon-aideck AND --follower-deck-mac)")
            if not a.allow_beacon_aideck:
                raise SessionError(msg)
            meta["warnings"].append("beacon carries an AI-deck (--allow-beacon-aideck)")
            print("   !! " + msg)
        status_vars = {r: pick_status_vars(d.log_toc(), uri=d.uri) for r, d in drones.items()}
        for r, sv in status_vars.items():
            missing = [v for v in ("lighthouse.status", "lighthouse.bsActive") if v not in sv]
            print(f"   {r:<8} status vars: {', '.join(sv) or '(none)'}"
                  + (f"  [absent: {', '.join(missing)}]" if missing else ""))

        # ---------------- rate
        first = max(10, int(round(1000.0 / a.pose_hz / 10.0)) * 10)
        if a.no_probe:
            period, probe = first, {}
        else:
            print(f"-- rate probe: both links at once, {PROBE_S:g} s per rate")
            period, probe = probe_rates(list(drones.values()), first)
        meta["log"] = dict(pose_period_ms=period, pose_hz_requested=round(1000.0 / period, 2),
                           status_period_ms=STATUS_PERIOD_MS, status_vars=status_vars,
                           probe={str(p): v for p, v in probe.items()},
                           shared_radio=len({u.split("/")[2] for u in meta["uris"].values()
                                             if u.startswith("radio://")}) == 1 and len(roles) == 2
                           and all(u.startswith("radio://") for u in meta["uris"].values()))
        print(f"   logging poses every {period} ms ({1000 / period:g} Hz), status every {STATUS_PERIOD_MS} ms")
        write_json_atomic(meta_path, meta)

        # ---------------- record
        for r, d in drones.items():
            writers[r] = PoseWriter(out / S.POSES_CSV[r], status_vars[r])
            d.start_logging(period, status_vars[r], writers[r].on_pose, writers[r].on_status)
        for attempt in (1, 2):
            silent = [r for r in drones if not wait_for_poses(writers[r], FIRST_POSE_TIMEOUT_S)]
            if not silent:
                break
            msg = f"no pose packets from the {', '.join(silent)} {FIRST_POSE_TIMEOUT_S:g} s after logging started"
            meta["warnings"].append(msg + (f" (attempt {attempt})"))
            print(f"   !! {msg}" + ("; restarting its log blocks" if attempt == 1 else ""))
            if attempt == 2:
                raise SessionError(msg + ". Is the drone on and in range? Nothing usable was recorded.")
            for r in silent:
                drones[r].stop_logging()
                drones[r].start_logging(period, status_vars[r], writers[r].on_pose, writers[r].on_status)
        if a.static:
            speak("Hands off the drone.")
            print(f"-- logging the follower for {a.seconds:g} s; do not touch it")
            t0 = time.time()
            schedule = []
        else:
            frames_dir.mkdir(exist_ok=True)
            grab_seconds = a.seconds + 4.0 + ((epoch - time.time()) if epoch else 0.0)
            grab, grab_log = start_grabber(host, port, frames_dir, grab_seconds, out / S.GRAB_LOG)
            procs.append(grab)
            t_wait = time.time() + FIRST_FRAME_TIMEOUT_S + ((epoch - time.time()) if epoch else 0)
            while not S.list_frames(frames_dir) and time.time() < t_wait and not stop_evt.is_set():
                if grab.poll() is not None:
                    break
                time.sleep(0.1)
            got = S.list_frames(frames_dir)
            if not got:
                raise SessionError("no frames arrived from the camera (see frames_grab.log)")
            if epoch is not None:
                if time.time() > epoch - 3.0:
                    raise SessionError(f"setup took longer than --mock-lead {a.mock_lead:g} s; raise it")
                t0 = epoch
            else:
                t0 = got[0][0] + 0.5
            t0_box["t0"] = t0
            schedule = S.cue_schedule(a.seconds)
            print(f"-- recording {a.seconds:g} s. First frame in; cues start "
                  f"{'at the scripted clock zero' if epoch else 'now'}.")
        meta["t0_unix"] = t0
        meta["cues"] = []
        end_t = t0 + a.seconds
        cue_i, last_print, last_mac = 0, time.time(), time.time()
        started_logging = time.time()      # every link has already delivered poses (checked above)
        while not stop_evt.is_set():
            now = time.time()
            while cue_i < len(schedule) and now >= t0 + schedule[cue_i][0]:
                tc, phrase, phase = schedule[cue_i]
                speak(phrase)
                print(f"   [{now - t0:6.1f} s] cue: {phrase}  ({phase})")
                meta["cues"].append(dict(phase=phase, phrase=phrase, planned_t=tc, unix=round(now, 3)))
                cue_i += 1
            if now >= end_t:
                stop["why"] = "completed"
                break
            for r, w in writers.items():
                d = drones[r]
                if d.lost.is_set():
                    request_stop(f"the {r} link dropped ({d.lost_why})")
                elif (w.last_rx or started_logging) < now - LINK_SILENT_S and now - started_logging > LINK_SILENT_S:
                    request_stop(f"the {r} sent nothing for {LINK_SILENT_S:g} s (link lost or battery flat)")
            if grab is not None and grab.poll() is not None and now < end_t - 1.0:
                request_stop(f"the frame grabber stopped early (exit {grab.returncode}; see frames_grab.log)")
            if now - last_print >= PRINT_EVERY_S:
                last_print = now
                parts = []
                for r, w in writers.items():
                    w.flush()
                    b = w.vbat[-1][1] if w.vbat else None
                    parts.append(f"{r} {len(w.t_cf)} poses, {b:.2f} V" if b else f"{r} {len(w.t_cf)} poses")
                    if b is not None and b < LOW_VBAT and f"low battery {r}" not in meta["warnings"]:
                        meta["warnings"].append(f"low battery {r}")
                        print(f"   !! {r} battery {b:.2f} V: it will brown out soon")
                if not a.static:
                    parts.append(f"{len(S.list_frames(frames_dir))} frames")
                print(f"   [{now - t0:6.1f} s] " + " | ".join(parts))
            if real and not a.static and now - last_mac >= PRINT_EVERY_S:
                last_mac = now
                m = deck_mac()
                if m and meta["deck"].get("mac") and m != meta["deck"]["mac"]:
                    meta["deck"]["mac_changes"].append(dict(unix=round(now, 3), mac=m))
                    meta["warnings"].append(f"deck MAC changed to {m} mid-session: the laptop may have roamed "
                                            "to the OTHER drone's WiFi")
                    print(f"   !! the deck at {DECK_HOST} is now {m}: the laptop may have switched decks")
            stop_evt.wait(0.05)
        if stop["why"] != "completed":
            speak("Recording stopped.")
            print(f"!! stopping early: {stop['why']}")
        else:
            speak("Done.")
    finally:
        signal.signal(signal.SIGINT, old_int)
        meta["stopped_because"] = stop["why"] or "error before recording"
        grab_rc = stop_process(grab) if grab is not None else None
        for d in drones.values():
            th = threading.Thread(target=lambda d=d: (d.stop_logging(), d.close()), daemon=True)
            th.start()
            th.join(8.0)
        for w in writers.values():
            w.close()
        for p in procs:
            stop_process(p, signal.SIGTERM, 5.0)
        if grab_log:
            grab_log.close()
        finish_meta(meta, writers, drones, frames_dir, grab_rc, started)
        write_json_atomic(meta_path, meta)
    report_end(a, meta, out, writers)
    return 0 if meta["stopped_because"] == "completed" else 1


def finish_meta(meta, writers, drones, frames_dir, grab_rc, started):
    period = (meta.get("log") or {}).get("pose_period_ms")
    if period:
        meta["log"]["achieved"] = {r: S.rate_stats(w.t_cf, period, w.t_laptop) for r, w in writers.items()}
        meta["log"]["status_achieved"] = {r: S.rate_stats(w.status_t_cf, STATUS_PERIOD_MS) for r, w in writers.items()}
        meta["log"]["link_quality"] = {r: (dict(mean=round(sum(d.link_quality) / len(d.link_quality), 1),
                                                min=round(min(d.link_quality), 1), n=len(d.link_quality))
                                           if d.link_quality else None) for r, d in drones.items()}
    meta["battery_v"] = {r: w.battery() for r, w in writers.items()}
    fr = S.list_frames(frames_dir)
    if meta["mode"] == "session":
        span = (fr[-1][0] - fr[0][0]) if len(fr) > 1 else 0.0
        meta["frames"] = dict(n=len(fr), first_unix=fr[0][0] if fr else None, last_unix=fr[-1][0] if fr else None,
                              fps=round((len(fr) - 1) / span, 3) if span > 0 else None, grab_exit=grab_rc,
                              names="frame_<n>_<unix arrival time>.png (cpx_grab.py, unlabelled)")
    meta["wall_seconds"] = round(time.time() - started, 1)
    meta["status"] = "complete" if meta.get("stopped_because") == "completed" else "partial"


def report_end(a, meta, out, writers):
    print("\n== summary")
    for r, st in (meta.get("log", {}).get("achieved") or {}).items():
        b = meta["battery_v"].get(r, {})
        print(f"   {r:<8} {st['n']} poses, {st['achieved_hz'] or 0:.1f} Hz achieved of {st['requested_hz']:g}, "
              f"{st['missing']} missing (max gap {st['max_gap_ms']} ms); battery {b.get('start')} -> {b.get('end')} V")
    if meta.get("frames"):
        f = meta["frames"]
        print(f"   frames   {f['n']} at {f['fps'] or 0:.2f} fps")
    for w in meta["warnings"]:
        print(f"   !! {w}")
    print(f"   stopped because: {meta['stopped_because']}")
    print(f"   meta: {out / S.META_JSON}")
    if a.static and "follower" in writers:
        cols = S.read_pose_csv(out / S.POSES_CSV["follower"])
        sm = static_summary(cols)
        meta["static_pose"] = sm
        write_json_atomic(out / S.META_JSON, meta)
        if "x" not in sm:
            print("   !! no follower poses: nothing to average")
            return
        print(f"\n== follower, averaged over {sm['n']} samples (std in brackets)")
        print(f"   x {sm['x']:+.3f} ({sm['x_std']:.3f})  y {sm['y']:+.3f} ({sm['y_std']:.3f})  "
              f"z {sm['z']:+.3f} ({sm['z_std']:.3f}) m")
        print(f"   yaw {sm['yaw']:+.2f} ({sm['yaw_std']:.2f})  roll {sm['roll']:+.2f}  pitch {sm['pitch']:+.2f} deg")
        if max(sm["x_std"], sm["y_std"], sm["z_std"]) > 0.02:
            print("   !! position jitter above 2 cm while still: are both base stations seen?")
        f = f"{sm['x']:.3f} {sm['y']:.3f} {sm['z']:.3f} {sm['yaw']:.2f} {sm['roll']:.2f} {sm['pitch']:.2f}"
        mount = " ".join(f"{v:g}" for v in a.mount)
        if a.mark:
            import pose_to_label as P
            h = a.height
            bz = h + a.beacon_above_head
            print(f"\n== label for a subject {h:g} m tall on the mark ({a.mark[0]:g}, {a.mark[1]:g}), "
                  f"feet on the floor (room z = 0):")
            P.main(["--follower", *f.split(), "--beacon", f"{a.mark[0]:g}", f"{a.mark[1]:g}", f"{bz:g}",
                    "--height", f"{h:g}", "--beacon-above-head", f"{a.beacon_above_head:g}", "--mount", *mount.split()])
        else:
            print("\n   pose_to_label command (fill in the mark):")
            print(f"   ~/Downloads/drone/trainenv/bin/python tools/lighthouse/pose_to_label.py --follower {f} "
                  f"--beacon BX BY BZ --height H --mount {mount}")
    elif meta["mode"] == "session":
        print("\n   label it (offline):")
        print(f"   ~/Downloads/drone/trainenv/bin/python {REPO}/tools/lighthouse/label_session.py {out}")


if __name__ == "__main__":
    sys.exit(main())
