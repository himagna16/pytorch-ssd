#!/usr/bin/env python3
"""Read-only health check for a Crazyflie: run it the moment a drone is plugged in.

    ~/Downloads/drone/cfloaderenv/bin/python tools/hardware/preflight.py

It connects (USB first, then Crazyradio, or whatever --uri says), reads what the
drone already knows about itself, listens to its telemetry for a few seconds, and
prints a plain-English checklist. The same facts go into a JSON file so two runs
(two drones, or one drone before and after a change) can be compared.

WHAT IT NEVER DOES. It never arms the motors, sends a setpoint, writes a
parameter, writes the EEPROM, reboots anything or changes the radio channel or
address. The only things it sends are the requests every cflib client sends to
read the drone's tables of contents and parameter values, two "what version are
you" questions, and temporary telemetry (log) blocks that live in the drone's RAM
and are deleted again before it disconnects. As a tripwire, every cflib method
that could move or reconfigure the drone is replaced by one that raises before
anything is sent (see install_write_guards).

Checks, in order:
  link        which URI answered, and how long connecting took
  firmware    release tag, git revision, whether it was built from modified source
  decks       every deck the firmware knows about: present or absent
  battery     pm.vbat and pm.state over the sampling window
  radio       channel / speed / address from the drone's EEPROM (read, never written)
  lighthouse  (only with a Lighthouse deck) system type, status, per-base-station
              bitmasks, position noise
  aideck      (only with an AI-deck) what the firmware exposes about it
  uart        (only with BOTH decks) evidence for or against a suspected UART1
              clash between the GAP8 and the Lighthouse FPGA. UNVERIFIED theory.

Exit code: 0 all fine or only warnings, 1 something failed, 2 could not connect.

Needs cflib (the cfloaderenv venv has cflib 0.1.33). The logic below the
CflibLink class does not import cflib, which is what lets the unit tests in
test_preflight.py run everywhere with a fake drone.
"""
import argparse
import datetime as _dt
import json
import os
import statistics
import sys
import threading
import time
from pathlib import Path

# --------------------------------------------------------------------------- constants

DEFAULT_OUT_DIR = Path.home() / "Downloads" / "drone" / "logs" / "preflight"

OK, WARN, FAIL, INFO, SKIP = "OK", "WARN", "FAIL", "INFO", "SKIP"

LOW_BATTERY_V = 3.7          # below this: charge before a session
EMPTY_BATTERY_V = 3.3        # below this: flat, the AI-deck will brown out almost at once
NO_BATTERY_V = 2.5           # below this the reading is not a LiPo at all

# pm.state values, from crazyflie-firmware src/hal/interface/pm.h (PMStates)
PM_STATES = {0: "on battery", 1: "charging", 2: "charged", 3: "LOW POWER", 4: "shutting down"}

# lighthouse.status values, from lighthouse_core.c
LH_STATUS = {
    0: "no base stations received",
    1: "base stations received, but geometry or calibration is missing",
    2: "working: base station data is going to the position estimator",
}
LH_SYSTEM_TYPE = {1: "Lighthouse V1 base stations", 2: "Lighthouse V2 base stations"}

# Friendly names for the deck.* parameters. Anything not listed is printed raw.
DECK_NAMES = {
    "bcAI": "AI-deck (camera, GAP8, WiFi)",
    "bcLighthouse4": "Lighthouse positioning deck",
    "bcFlow": "Flow deck v1",
    "bcFlow2": "Flow deck v2",
    "bcZRanger": "Z-ranger deck v1",
    "bcZRanger2": "Z-ranger deck v2",
    "bcMultiranger": "Multi-ranger deck",
    "bcLoco": "Loco positioning deck",
    "bcDWM1000": "Loco positioning deck (DWM1000 driver)",
    "bcUSD": "Micro SD card deck",
    "bcLedRing": "LED ring deck",
    "bcBuzzer": "Buzzer deck",
    "bcColorLedBot": "Color LED deck (bottom)",
    "bcColorLedTop": "Color LED deck (top)",
    "bcActiveM": "Active marker deck",
    "bcGTGPS": "GPS deck",
    "bcCPPM": "CPPM (RC receiver) deck",
    "bcOA": "Obstacle avoidance deck",
    "bcBigQuad": "BigQuad deck",
    "bcRpm": "RPM deck",
    "bcServo": "Servo deck",
    "bcLoadcell": "Load cell deck",
    "bcACS37800": "Power measurement deck",
    "bcFlapperDeck": "Flapper deck",
    "bcLhTester": "Lighthouse tester deck",
}

# Lighthouse log variables worth sampling, in print order. Only the ones the
# drone's TOC actually has are used; any other lighthouse.bs* variable found in
# the TOC is added too, so a renamed or new bitmask is not silently skipped.
LH_LOG_WANTED = ["status", "bsReceive", "bsActive", "bsAvailable", "bsCalVal",
                 "bsGeoVal", "bsCalCon", "bsCalUd", "comSync", "posRt",
                 "estBs0Rt", "estBs1Rt", "serRt", "frmRt", "cycleRt"]
LH_BITMASKS = ["bsAvailable", "bsReceive", "bsCalVal", "bsGeoVal", "bsActive",
               "bsCalCon", "bsCalUd"]

# Bytes per logged value, keyed by the ctype string cflib's log TOC reports.
LOG_SIZES = {"uint8_t": 1, "int8_t": 1, "uint16_t": 2, "int16_t": 2,
             "uint32_t": 4, "int32_t": 4, "float": 4, "FP16": 2}
LOG_BLOCK_BYTES = 26         # one CRTP log packet carries at most 26 bytes of data

# Crazyradio speeds as stored in the EEPROM config
RADIO_SPEEDS = {0: "250K", 1: "1M", 2: "2M"}
FACTORY_ADDRESS = 0xE7E7E7E7E7

UART_THEORY = """\
Why this section exists. Current Crazyflie firmware gives the two decks
different serial ports: the AI-deck driver takes UART2 (that is the ESP32 /
WiFi link, used by CPX) and the Lighthouse deck takes UART1. So the deck
drivers do not clash. BUT our GAP8 programs are built with `io=uart`
(crazyflie_ssd/Makefile line 4, and line 1 of the wifi-img-streamer Makefile
in aideck-gap8-examples), so the GAP8 prints its debug output on its own UART,
and on the AI-deck that UART is wired to the Crazyflie's UART1 - the same line
the Lighthouse deck's FPGA uses to send its sweep data. If both transmit, the
Lighthouse stream could get corrupted.

This is a THEORY, not a verified fault. This tool only collects the evidence:
how often the Lighthouse serial link is in sync (comSync), the position rate
(posRt), which base stations are received, and how noisy the position is.
To test the theory, run preflight twice with the drone sitting still in the
same spot: once with the GAP8 app running (normal power-on) and once with the
AI-deck taken off, then compare the two JSON files:

  preflight.py --gap8 running   -> saves run A
  preflight.py --gap8 no-deck --compare <run A json>

A clear drop in comSync or posRt, or a jump in position noise, only in the
"running" run, supports the theory. No difference argues against it."""


# --------------------------------------------------------------------------- errors

class ConnectError(Exception):
    """Could not open a link. The message is written for a beginner."""


class ReadOnlyViolation(RuntimeError):
    """Raised by the write guards. If you ever see this, the tool has a bug."""


# --------------------------------------------------------------------------- small helpers

def _num(v):
    """cflib hands parameter values back as strings. Return a number or None."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return v
    try:
        f = float(str(v).strip())
    except (TypeError, ValueError):
        return None
    return int(f) if f.is_integer() else f


def bits(mask):
    """Bitmask -> base-station channel numbers. Bit 0 is channel 1."""
    mask = int(mask or 0)
    return [i + 1 for i in range(16) if mask & (1 << i)]


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return statistics.fmean(xs) if xs else None


def _std(xs):
    xs = [x for x in xs if x is not None]
    return statistics.pstdev(xs) if len(xs) >= 2 else None


def _r(x, nd=3):
    return None if x is None else round(x, nd)


def chunk_log_vars(names_with_types, max_bytes=LOG_BLOCK_BYTES):
    """Split log variables into blocks that each fit in one CRTP log packet."""
    blocks, cur, used = [], [], 0
    for name, ctype in names_with_types:
        size = LOG_SIZES.get(ctype, 4)
        if cur and used + size > max_bytes:
            blocks.append(cur)
            cur, used = [], 0
        cur.append(name)
        used += size
    if cur:
        blocks.append(cur)
    return blocks


def firmware_git_revision(rev0, rev1):
    """firmware.revision0 (uint32) + revision1 (uint16) are the first 12 hex
    digits of the git commit the firmware was built from."""
    r0, r1 = _num(rev0), _num(rev1)
    if r0 is None or r1 is None:
        return None
    return f"{int(r0):08x}{int(r1):04x}"


def parse_radio_uri(uri):
    """radio://0/80/2M/E7E7E7E7E7 -> {'channel': 80, 'speed': '2M', 'address': 'E7E7E7E7E7'}"""
    if not uri.startswith("radio://"):
        return None
    parts = uri[len("radio://"):].split("/")
    out = {"dongle": parts[0] if parts else None}
    if len(parts) > 1 and parts[1].isdigit():
        out["channel"] = int(parts[1])
    if len(parts) > 2:
        out["speed"] = parts[2].split("?")[0]
    if len(parts) > 3:
        out["address"] = parts[3].split("?")[0].upper()
    return out


def clean_error(msg, limit=160):
    """cflib error strings can carry a whole traceback. Keep the first sentence."""
    msg = str(msg or "").split("Traceback")[0]
    msg = " ".join(msg.replace("Exception:", ": ").split()).strip(" :")
    return msg if len(msg) <= limit else msg[:limit - 3] + "..."


def explain_connect_error(uri, msg):
    """Turn a cflib error into something a beginner can act on."""
    msg = clean_error(msg)
    m = msg.lower()
    if uri.startswith("usb://"):
        hint = ("Check: (1) the battery is plugged in, so the drone is on; (2) the "
                "micro-USB cable is a DATA cable, not charge-only; (3) cfclient or "
                "another script is not already connected to it (quit it and retry).")
        if "busy" in m or "access" in m or "resource" in m:
            hint = "Another program has the USB device open. Quit cfclient or other scripts and retry. " + hint
        return f"Could not talk to a Crazyflie over USB ({uri}): {msg}. {hint}"
    if uri.startswith("radio://"):
        if "crazyradio" in m or "dongle" in m:
            return (f"No Crazyradio found ({msg}). The Crazyradio is USB-A; a USB-C Mac "
                    "needs an adapter or hub. Or skip the radio: plug the micro-USB cable "
                    "into the drone and run again.")
        return (f"The Crazyradio is there but the drone at {uri} did not answer ({msg}). "
                "Is the drone on? Is the channel/address right? The factory default is "
                "radio://0/80/2M/E7E7E7E7E7 but lab drones are often re-addressed. "
                "Over USB you can read the real address with this tool.")
    if uri.startswith("udp://"):
        return (f"No simulator answered at {uri} ({msg}). Start CrazySim first "
                "(tools/crazysim_macos/run_sim.sh single).")
    return f"Could not connect to {uri}: {msg}"


# --------------------------------------------------------------------------- write guards

# Every cflib entry point that can move the drone, change a setting, or write
# memory. They are replaced on the live Crazyflie object before anything else
# happens. Reading (param values, log blocks, memory reads) is untouched.
GUARDED = {
    "commander": "*",
    "high_level_commander": "*",
    "extpos": "*",
    "loc": "*",
    "appchannel": "*",
    "supervisor": ["send_arming_request", "send_crash_recovery_request",
                   "send_emergency_stop", "send_emergency_stop_watchdog"],
    "platform": ["send_arming_request", "send_crash_recovery_request",
                 "set_continous_wave", "send_user_notification"],
    "param": ["set_value", "set_value_raw", "persistent_store", "persistent_clear"],
    "mem": ["write"],
}


def install_write_guards(cf):
    """Replace every write-capable cflib method on `cf` with one that raises.
    Returns the list of 'object.method' names that were guarded."""
    guarded = []
    for attr, methods in GUARDED.items():
        obj = getattr(cf, attr, None)
        if obj is None:
            continue
        if methods == "*":
            methods = [m for m in dir(obj) if not m.startswith("_")
                       and callable(getattr(obj, m, None))]
        for m in methods:
            if not callable(getattr(obj, m, None)):
                continue

            def _blocked(*a, _name=f"{attr}.{m}", **k):
                raise ReadOnlyViolation(f"preflight is read-only; refused to call {_name}")
            try:
                setattr(obj, m, _blocked)
                guarded.append(f"{attr}.{m}")
            except (AttributeError, TypeError):
                pass
    return guarded


# --------------------------------------------------------------------------- real link (cflib)

class CflibLink:
    """The only part of this file that touches cflib or the drone.

    The fake in test_preflight.py implements the same methods; run_preflight()
    uses nothing else."""

    VERSION_CHANNEL = 1          # platform port, "version" channel: read-only queries
    VERSION_GET_FIRMWARE = 1
    VERSION_GET_DEVICE_TYPE = 2

    def __init__(self, uri, connect_timeout=15.0, cache_dir=None):
        self.uri = uri
        self.connect_timeout = connect_timeout
        self.cache_dir = cache_dir
        self.scf = None
        self.cf = None
        self.guarded = []
        self._active_logs = []

    # -- connection
    def open(self):
        from cflib.crazyflie import Crazyflie
        from cflib.crazyflie.syncCrazyflie import SyncCrazyflie

        cache = None
        if self.cache_dir:
            try:
                Path(self.cache_dir).mkdir(parents=True, exist_ok=True)
                cache = str(self.cache_dir)
            except OSError:
                cache = None
        cf = Crazyflie(rw_cache=cache)
        self.guarded = install_write_guards(cf)
        scf = SyncCrazyflie(self.uri, cf=cf)
        result = {}

        def _open():
            try:
                scf.open_link()
                result["ok"] = True
            except Exception as e:             # cflib raises bare Exception
                result["err"] = str(e) or e.__class__.__name__

        t0 = time.monotonic()
        th = threading.Thread(target=_open, daemon=True)
        th.start()
        try:
            th.join(self.connect_timeout)
        except KeyboardInterrupt:
            try:
                cf.close_link()
            except Exception:
                pass
            raise
        if th.is_alive():
            try:
                cf.close_link()
            except Exception:
                pass
            raise ConnectError(explain_connect_error(
                self.uri, f"no answer within {self.connect_timeout:.0f} s"))
        if "err" in result:
            raise ConnectError(explain_connect_error(self.uri, result["err"]))
        self.scf, self.cf = scf, cf
        return time.monotonic() - t0

    def wait_params(self, timeout=10.0):
        t0 = time.monotonic()
        while time.monotonic() - t0 < timeout:
            if self.scf.is_params_updated():
                return True
            time.sleep(0.05)
        return False

    def close(self):
        for lc in list(self._active_logs):
            self._stop_log(lc)
        if self.scf is not None:
            # cflib's close_link() sends a zero setpoint first; the write guard raised there and the
            # link was never actually closed (found 2026-09-23). A no-op that sends nothing fixes it.
            try:
                self.cf.commander.send_setpoint = lambda *a, **k: None
            except Exception:
                pass
            try:
                self.scf.close_link()
            except Exception:
                pass
        self.scf = self.cf = None

    # -- tables of contents and values
    def param_toc(self):
        return {g: sorted(names) for g, names in self.cf.param.toc.toc.items()}

    def param_value(self, complete_name):
        group, _, name = complete_name.partition(".")
        return self.cf.param.values.get(group, {}).get(name)

    def log_toc(self):
        return {g: {n: el.ctype for n, el in names.items()}
                for g, names in self.cf.log.toc.toc.items()}

    def protocol_version(self):
        try:
            v = self.cf.platform.get_protocol_version()
        except Exception:
            return None
        return None if v is None or v < 0 else v

    def platform_query(self, cmd, timeout=1.5):
        """Ask the firmware for its version tag (cmd 1) or device type (cmd 2).
        cflib 0.1.33 defines the constant for cmd 1 but has no method for it."""
        if cmd not in (self.VERSION_GET_FIRMWARE, self.VERSION_GET_DEVICE_TYPE):
            raise ReadOnlyViolation(f"platform_query only allows read-only version queries, got {cmd}")
        from cflib.crtp.crtpstack import CRTPPacket, CRTPPort
        got, done = {}, threading.Event()

        def _cb(pk):
            data = bytes(pk.data)
            if pk.channel == self.VERSION_CHANNEL and data[:1] == bytes([cmd]):
                got["s"] = data[1:].split(b"\0")[0].decode("utf-8", "replace").strip()
                done.set()

        self.cf.add_port_callback(CRTPPort.PLATFORM, _cb)
        try:
            pk = CRTPPacket()
            pk.set_header(CRTPPort.PLATFORM, self.VERSION_CHANNEL)
            pk.data = (cmd,)
            self.cf.send_packet(pk)
            done.wait(timeout)
        finally:
            self.cf.remove_port_callback(CRTPPort.PLATFORM, _cb)
        return got.get("s") or None

    def read_eeprom(self, timeout=3.0):
        """Radio config from the Crazyflie's I2C EEPROM. Read only: update() reads."""
        from cflib.crazyflie.mem import MemoryElement
        mems = self.cf.mem.get_mems(MemoryElement.TYPE_I2C)
        if not mems:
            return None
        done = threading.Event()
        mems[0].update(lambda _m: done.set())
        if not done.wait(timeout):
            return {"error": "timed out reading the EEPROM"}
        el = dict(getattr(mems[0], "elements", {}) or {})
        if not getattr(mems[0], "valid", True):
            el["error"] = "EEPROM checksum did not match"
        return el

    def read_deck_memories(self, timeout=2.0):
        """Names of deck boards found on the 1-wire bus (each deck carries a tiny
        EEPROM). This sees a deck even if the firmware has no driver for it."""
        from cflib.crazyflie.mem import MemoryElement
        out = []
        for m in self.cf.mem.get_mems(MemoryElement.TYPE_1W):
            done = threading.Event()
            try:
                m.update(lambda _m: done.set())
                done.wait(timeout)
            except Exception:
                pass
            name = getattr(m, "name", None) or getattr(m, "elements", {}).get("Board name")
            out.append({"name": name, "vid": getattr(m, "vid", None), "pid": getattr(m, "pid", None)})
        return out

    # -- telemetry
    def _stop_log(self, lc):
        try:
            lc.stop()
        except Exception:
            pass
        try:
            lc.delete()
        except Exception:
            pass
        if lc in self._active_logs:
            self._active_logs.remove(lc)

    def sample(self, var_types, seconds, period_ms=100):
        """Log the given {name: ctype} variables for `seconds`.
        Returns ({name: [values...]}, [errors])."""
        from cflib.crazyflie.log import LogConfig
        samples = {n: [] for n in var_types}
        errors = []
        lock = threading.Lock()

        def _cb(_ts, data, _lc):
            with lock:
                for k, v in data.items():
                    samples.setdefault(k, []).append(v)

        for i, block in enumerate(chunk_log_vars(list(var_types.items()))):
            lc = LogConfig(name=f"preflight{i}", period_in_ms=period_ms)
            for n in block:
                lc.add_variable(n)
            try:
                self.cf.log.add_config(lc)
                if not lc.valid:
                    errors.append(f"log block {block} not accepted")
                    continue
                lc.data_received_cb.add_callback(_cb)
                lc.error_cb.add_callback(lambda _lc, msg: errors.append(str(msg)))
                lc.start()
                self._active_logs.append(lc)
            except (KeyError, AttributeError) as e:
                errors.append(f"log block {block}: {e}")
        try:
            end = time.monotonic() + seconds
            while time.monotonic() < end:
                time.sleep(0.05)
        finally:
            for lc in list(self._active_logs):
                self._stop_log(lc)
        with lock:
            return {k: list(v) for k, v in samples.items()}, errors


# --------------------------------------------------------------------------- analysis (pure)

def check(status, summary, **details):
    return {"status": status, "summary": summary, "details": details}


def analyze_firmware(param_toc, get_param, tag, device, protocol):
    fw = param_toc.get("firmware", [])
    rev = firmware_git_revision(get_param("firmware.revision0"), get_param("firmware.revision1")) \
        if "revision0" in fw and "revision1" in fw else None
    modified = _num(get_param("firmware.modified")) if "modified" in fw else None
    cpu = [get_param(f"cpu.id{i}") for i in range(3)] if "id0" in param_toc.get("cpu", []) else None
    serial = None
    if cpu and all(_num(c) is not None for c in cpu):
        serial = "".join(f"{int(_num(c)) & 0xFFFFFFFF:08X}" for c in cpu)
    parts = []
    if tag:
        parts.append(tag)
    if rev:
        parts.append(f"git {rev}")
    if modified is not None:
        parts.append("built from MODIFIED source" if modified else "unmodified")
    if device:
        parts.append(device)
    if protocol is not None:
        parts.append(f"protocol {protocol}")
    details = dict(tag=tag, git_revision=rev, modified=bool(modified) if modified is not None else None,
                   device_type=device, protocol_version=protocol, serial=serial)
    if not parts:
        return check(WARN, "firmware version not readable (old firmware?)", **details)
    summary = ", ".join(parts)
    if serial:
        summary += f"; serial {serial}"
    if modified:
        return check(INFO, summary + ". 'Modified' is normal for a custom build (e.g. our own app); "
                     "it just means this is not a stock Bitcraze release.", **details)
    return check(OK, summary, **details)


def analyze_decks(param_toc, get_param, deck_memories=None):
    """Every deck.bc* parameter the TOC has -> present / absent.
    Also cross-checks the deck boards seen on the 1-wire bus."""
    names = [n for n in param_toc.get("deck", []) if n.startswith("bc")]
    decks = {}
    for n in names:
        v = _num(get_param(f"deck.{n}"))
        decks[n] = None if v is None else bool(v)
    ow = [d.get("name") for d in (deck_memories or []) if d.get("name")]
    notes = []
    for board in ow:
        if board in decks and decks[board] is False:
            notes.append(f"{board} is physically attached (its EEPROM answered) but its driver "
                         f"did not start. Reseat the deck and power-cycle.")
        elif board not in decks:
            notes.append(f"{board} is physically attached but this firmware has no driver for it.")
    present = sorted(n for n, p in decks.items() if p)
    unknown = sorted(n for n, p in decks.items() if p is None)
    details = dict(decks=decks, present=present, boards_on_1wire=ow, notes=notes,
                   firmware_knows=sorted(decks))
    if "deck" not in param_toc:
        return check(WARN, "this firmware exposes no deck.* parameters, so deck detection is not possible",
                     **details)
    if present:
        summary = "present: " + ", ".join(DECK_NAMES.get(n, n) for n in present)
    else:
        summary = "no decks detected"
    if unknown:
        summary += f" (could not read: {', '.join(unknown)})"
    status = WARN if notes else INFO
    return check(status, summary, **details)


def analyze_battery(vbat, state, charge_current=None):
    """vbat: list of volts, state: list of pm.state ints (either may be empty)."""
    v = [x for x in vbat if x is not None]
    if not v:
        return check(WARN, "no battery reading (pm.vbat not in the log TOC or no samples)",
                     vbat_mean=None, vbat_min=None, state=None)
    mean_v, min_v = _mean(v), min(v)
    st_counts = {}
    for s in state:
        st_counts[int(s)] = st_counts.get(int(s), 0) + 1
    st = max(st_counts, key=st_counts.get) if st_counts else None
    st_name = PM_STATES.get(st, f"state {st}") if st is not None else "unknown"
    details = dict(vbat_mean=_r(mean_v), vbat_min=_r(min_v), n=len(v), state=st, state_name=st_name,
                   state_counts=st_counts, charge_current=_r(_mean(charge_current or [])))
    charging = st in (1, 2)
    head = f"{mean_v:.2f} V ({st_name})"
    life = ("A full 350 mAh pack gives only about 5-7 minutes with the AI-deck "
            "streaming, and about 40 minutes to recharge over micro-USB.")
    if mean_v < NO_BATTERY_V:
        return check(WARN, head + ": that is not a LiPo reading. Is the battery connected? "
                     "(On USB the board can run with no battery.)", **details)
    if st == 3 or mean_v < EMPTY_BATTERY_V:
        return check(FAIL, head + ": battery is FLAT. Charge it before doing anything: leave it "
                     "plugged into the drone and connect the micro-USB cable. " + life, **details)
    if mean_v < LOW_BATTERY_V and not charging:
        return check(WARN, head + f": below {LOW_BATTERY_V} V, charge before a session. " + life,
                     **details)
    if charging:
        return check(OK, head + ": the voltage reads higher than the real charge while USB is "
                     "charging it; unplug and re-check if you need the true level. " + life, **details)
    return check(OK, head + ". " + life, **details)


def analyze_radio(uri, eeprom, other_runs=None, this_serial=None):
    """Report the radio config. `other_runs` = [(serial, address_hex, path)] from
    earlier preflight JSONs, used to spot two drones sharing an address."""
    from_uri = parse_radio_uri(uri)
    details = dict(uri=uri, from_uri=from_uri, eeprom=None)
    if eeprom and "error" not in eeprom and eeprom.get("radio_address") is not None:
        addr = f"{int(eeprom['radio_address']):010X}"
        ch = eeprom.get("radio_channel")
        spd = RADIO_SPEEDS.get(eeprom.get("radio_speed"), eeprom.get("radio_speed"))
        details["eeprom"] = dict(channel=ch, speed=spd, address=addr,
                                 pitch_trim=eeprom.get("pitch_trim"), roll_trim=eeprom.get("roll_trim"))
        summary = f"stored config: channel {ch}, {spd}, address {addr} -> radio://0/{ch}/{spd}/{addr}"
        status = OK
        if int(eeprom["radio_address"]) == FACTORY_ADDRESS:
            summary += " (factory default address)"
        clash = [p for s, a, p in (other_runs or [])
                 if a == addr and s and this_serial and s != this_serial]
        details["address_shared_with"] = clash
        if clash:
            status = WARN
            summary += (f". ANOTHER drone (earlier run {Path(clash[0]).name}) has the same address. "
                        "Two drones on one Crazyradio need different addresses; change one in "
                        "cfclient (Connect > Configure 2.x). This tool never changes it.")
        else:
            summary += (". Two drones on one Crazyradio need different addresses; run this on the "
                        "other drone and compare.")
        return check(status, summary, **details)
    if eeprom and "error" in eeprom:
        return check(WARN, f"could not read the radio config: {eeprom['error']}", **details)
    if from_uri:
        return check(INFO, f"connected over radio: channel {from_uri.get('channel')}, "
                     f"{from_uri.get('speed')}, address {from_uri.get('address')} "
                     "(EEPROM config not readable)", **details)
    return check(INFO, "radio config not exposed on this link (no EEPROM memory; normal in the simulator)",
                 **details)


def _bitmask_union(xs):
    m = 0
    for x in xs:
        if x is not None:
            m |= int(x)
    return m


def _last(xs):
    xs = [x for x in xs if x is not None]
    return xs[-1] if xs else None


def lighthouse_stats(samples):
    """Summaries of whatever lighthouse.* and stateEstimate.* samples exist."""
    g = lambda n: samples.get(f"lighthouse.{n}", [])       # noqa: E731
    out = {}
    st = [int(x) for x in g("status")]
    if st:
        out["status_last"] = st[-1]
        out["status_fraction"] = {k: round(st.count(k) / len(st), 3) for k in sorted(set(st))}
        out["status2_fraction"] = round(st.count(2) / len(st), 3)
    for n in LH_BITMASKS:
        xs = g(n)
        if xs:
            out[n] = {"last": bits(_last(xs)), "ever": bits(_bitmask_union(xs))}
    rx = g("bsReceive")
    if rx:
        per_bs = {}
        for b in bits(_bitmask_union(rx)):
            per_bs[b] = round(sum(1 for x in rx if int(x) & (1 << (b - 1))) / len(rx), 3)
        out["receive_fraction_per_bs"] = per_bs
        out["receive_count_mean"] = _r(_mean([len(bits(x)) for x in rx]), 2)
    cs = g("comSync")
    if cs:
        out["comSync_fraction"] = round(sum(1 for x in cs if int(x)) / len(cs), 3)
    for n in ("posRt", "estBs0Rt", "estBs1Rt", "serRt", "frmRt", "cycleRt"):
        xs = g(n)
        if xs:
            out[f"{n}_mean"] = _r(_mean(xs), 1)
    pos = {}
    for ax in "xyz":
        xs = samples.get(f"stateEstimate.{ax}", [])
        if xs:
            pos[ax] = {"mean": _r(_mean(xs), 4), "std_mm": _r((_std(xs) or 0.0) * 1000, 2)}
    if pos:
        out["position"] = pos
        out["position_std_mm_max"] = max(p["std_mm"] for p in pos.values())
    out["n_samples"] = max((len(v) for k, v in samples.items() if k.startswith("lighthouse.")), default=0)
    return out


def describe_base_stations(stats):
    """Plain words per base station channel: seen / calibrated / geometry / in use."""
    def s(n, key="ever"):
        return set(stats.get(n, {}).get(key, []))
    chans = sorted(s("bsAvailable") | s("bsReceive") | s("bsActive") | s("bsCalVal") | s("bsGeoVal"))
    lines = []
    have_geo = "bsGeoVal" in stats
    have_cal = "bsCalVal" in stats
    for b in chans:
        words = []
        seen = b in s("bsReceive")
        words.append("seen" if seen else "NOT seen right now")
        if have_cal:
            words.append("calibrated" if b in s("bsCalVal", "last") else "calibration MISSING")
        if have_geo:
            words.append("geometry OK" if b in s("bsGeoVal", "last") else "geometry MISSING")
        if "bsActive" in stats:
            words.append("in use for position" if b in s("bsActive", "last") else "not used for position")
        frac = stats.get("receive_fraction_per_bs", {}).get(b)
        if frac is not None:
            words.append(f"received in {frac:.0%} of samples")
        lines.append(f"base station {b}: " + ", ".join(words))
    return lines


def analyze_lighthouse(param_toc, get_param, log_toc, samples, lh_present):
    if not lh_present:
        return check(SKIP, "no Lighthouse deck detected", present=False)
    if "lighthouse" not in log_toc:
        return check(WARN, "Lighthouse deck reported present but the firmware has no lighthouse "
                     "log group, so its status cannot be read", present=True)
    sys_type = _num(get_param("lighthouse.systemType")) if "systemType" in param_toc.get("lighthouse", []) else None
    method = _num(get_param("lighthouse.method")) if "method" in param_toc.get("lighthouse", []) else None
    stats = lighthouse_stats(samples)
    bs_lines = describe_base_stations(stats)
    details = dict(present=True, system_type=sys_type,
                   system_type_name=LH_SYSTEM_TYPE.get(sys_type),
                   method=method, stats=stats, base_stations=bs_lines)
    st = stats.get("status_last")
    head = []
    if sys_type is not None:
        head.append(f"expects {LH_SYSTEM_TYPE.get(sys_type, f'type {sys_type}')}")
    if st is not None:
        head.append(LH_STATUS.get(st, f"status {st}"))
    pos_std = stats.get("position_std_mm_max")
    if pos_std is not None and st == 2:
        head.append(f"position noise {pos_std:.1f} mm (max axis std, drone sitting still)")
    summary = "; ".join(head) or "no lighthouse samples received"
    if st is None:
        return check(WARN, summary, **details)
    if st == 0:
        return check(WARN, summary + ". Are the base stations powered and in view of the deck? "
                     "If they are V1 units, lighthouse.systemType must be 1 (set it in cfclient, "
                     "not here).", **details)
    if st == 1:
        return check(WARN, summary + ". Run the geometry estimation in cfclient's Lighthouse tab "
                     "(or load the lab's saved geometry file).", **details)
    if pos_std is not None and pos_std > 20:
        return check(WARN, summary + ". That is noisy for a drone sitting still.", **details)
    return check(OK, summary, **details)


def analyze_aideck(param_toc, log_toc, ai_present):
    if not ai_present:
        return check(SKIP, "no AI-deck detected", present=False)
    keys = ("cpx", "wifi", "aideck", "gap8", "esp")
    found_params = sorted(f"{g}.{n}" for g, ns in param_toc.items() for n in ns
                          if any(k in g.lower() or k in n.lower() for k in keys) and not
                          (g == "deck" and n == "bcAI"))
    found_logs = sorted(f"{g}.{n}" for g, ns in log_toc.items() for n in ns
                        if any(k in g.lower() or k in n.lower() for k in keys))
    note = ("Camera frames do NOT come over this link: they come over the deck's own WiFi "
            "access point ('WiFi streaming example', then 192.168.4.1:5000), captured with "
            "tools/crazysim_macos/cpx_grab.py. This link only proves the deck's driver started.")
    if found_params or found_logs:
        summary = (f"AI-deck driver running; firmware exposes {len(found_params)} CPX/WiFi-related "
                   f"params and {len(found_logs)} log vars. " + note)
    else:
        summary = ("AI-deck driver running. Stock firmware exposes no WiFi/CPX settings as "
                   "parameters (only deck.bcAI), which is normal. " + note)
    return check(OK, summary, present=True, cpx_wifi_params=found_params, cpx_wifi_logs=found_logs)


def analyze_uart_conflict(ai_present, lh_present, lh_check, gap8_state):
    if not (ai_present and lh_present):
        return check(SKIP, "only relevant when both the AI-deck and the Lighthouse deck are on",
                     applicable=False)
    stats = (lh_check.get("details") or {}).get("stats", {})
    metrics = {
        "gap8_state": gap8_state,
        "status2_fraction": stats.get("status2_fraction"),
        "comSync_fraction": stats.get("comSync_fraction"),
        "posRt_mean_hz": stats.get("posRt_mean"),
        "serRt_mean_hz": stats.get("serRt_mean"),
        "receive_count_mean": stats.get("receive_count_mean"),
        "position_std_mm_max": stats.get("position_std_mm_max"),
    }
    signs = []
    if metrics["comSync_fraction"] is not None and metrics["comSync_fraction"] < 0.95:
        signs.append(f"Lighthouse serial link in sync only {metrics['comSync_fraction']:.0%} of the time")
    if metrics["status2_fraction"] is not None and metrics["status2_fraction"] < 0.9 \
            and (metrics["receive_count_mean"] or 0) > 0:
        signs.append("base stations are received but the system is not steadily at 'working'")
    if metrics["position_std_mm_max"] is not None and metrics["position_std_mm_max"] > 20:
        signs.append(f"position noise {metrics['position_std_mm_max']:.1f} mm while sitting still")
    summary = ("both decks on: collected UART1 evidence (theory UNVERIFIED). "
               + ("Possible symptoms: " + "; ".join(signs) + "." if signs
                  else "No symptoms in this run."))
    return check(WARN if signs else INFO, summary, applicable=True, metrics=metrics,
                 symptoms=signs, theory=UART_THEORY)


# --------------------------------------------------------------------------- orchestration

def pick_log_vars(log_toc, uri, lh_present):
    """{name: ctype} of everything worth sampling that this drone actually has."""
    want = {}

    def add(group, name):
        if name in log_toc.get(group, {}):
            want[f"{group}.{name}"] = log_toc[group][name]

    for n in ("vbat", "state", "batteryLevel", "chargeCurrent"):
        add("pm", n)
    if uri.startswith("radio://"):
        add("radio", "rssi")
    if lh_present:
        lh = log_toc.get("lighthouse", {})
        names = [n for n in LH_LOG_WANTED if n in lh]
        names += sorted(n for n in lh if n.startswith("bs") and n not in names)
        for n in names:
            add("lighthouse", n)
        for ax in "xyz":
            add("stateEstimate", ax)
    return want


def load_other_runs(out_dir, exclude=None):
    """(serial, radio address, path) from earlier preflight JSONs in out_dir."""
    runs = []
    try:
        files = sorted(Path(out_dir).glob("*.json"))
    except OSError:
        return runs
    for p in files:
        if exclude and Path(p) == Path(exclude):
            continue
        try:
            d = json.loads(Path(p).read_text())
            serial = d["checks"]["firmware"]["details"].get("serial")
            eep = d["checks"]["radio"]["details"].get("eeprom") or {}
            if eep.get("address"):
                runs.append((serial, eep["address"], str(p)))
        except Exception:
            continue
    return runs


def run_preflight(link, seconds=5.0, period_ms=100, gap8_state="unknown", other_runs=None,
                  log=print, report=None):
    """Everything after the link is open. `link` is a CflibLink or a test fake.
    Results are written into `report` as they are found, so a Ctrl-C part way
    through still leaves the finished checks in the JSON."""
    if report is None:
        report = {}
    report.setdefault("checks", {})
    report.setdefault("errors", [])
    C = report["checks"]

    if hasattr(link, "wait_params") and not link.wait_params():
        report["errors"].append("not all parameter values arrived before the timeout")
    ptoc, ltoc = link.param_toc(), link.log_toc()
    get = link.param_value

    def safe(fn, *a, default=None):
        try:
            return fn(*a)
        except Exception as e:
            report["errors"].append(f"{getattr(fn, '__name__', fn)}: {e}")
            return default

    log("  reading firmware version ...")
    tag = safe(link.platform_query, 1)
    device = safe(link.platform_query, 2)
    C["firmware"] = analyze_firmware(ptoc, get, tag, device, safe(link.protocol_version))

    log("  reading decks ...")
    mems = safe(link.read_deck_memories, default=[]) if hasattr(link, "read_deck_memories") else []
    C["decks"] = analyze_decks(ptoc, get, mems)
    decks = C["decks"]["details"]["decks"]
    ai, lh = bool(decks.get("bcAI")), bool(decks.get("bcLighthouse4"))

    log("  reading radio config (read only) ...")
    eeprom = safe(link.read_eeprom)
    C["radio"] = analyze_radio(link.uri, eeprom, other_runs, C["firmware"]["details"].get("serial"))

    want = pick_log_vars(ltoc, link.uri, lh)
    log(f"  listening to {len(want)} telemetry values for {seconds:g} s (keep the drone still) ...")
    samples, errs = ({}, [])
    if want:
        res = safe(link.sample, want, seconds, period_ms, default=({}, ["sampling failed"]))
        samples, errs = res
    report["errors"].extend(errs)

    C["battery"] = analyze_battery(samples.get("pm.vbat", []), samples.get("pm.state", []),
                                   samples.get("pm.chargeCurrent"))
    C["lighthouse"] = analyze_lighthouse(ptoc, get, ltoc, samples, lh)
    C["aideck"] = analyze_aideck(ptoc, ltoc, ai)
    C["uart_conflict"] = analyze_uart_conflict(ai, lh, C["lighthouse"], gap8_state)
    report["sampled"] = {k: len(v) for k, v in samples.items()}
    report["toc"] = {"param_groups": sorted(ptoc), "log_groups": sorted(ltoc),
                     "deck_params": ptoc.get("deck", []),
                     "lighthouse_log": sorted(ltoc.get("lighthouse", {}))}
    return report


ORDER = ["link", "firmware", "decks", "battery", "radio", "lighthouse", "aideck", "uart_conflict"]
LABELS = {"link": "Link", "firmware": "Firmware", "decks": "Decks", "battery": "Battery",
          "radio": "Radio", "lighthouse": "Lighthouse", "aideck": "AI-deck",
          "uart_conflict": "UART1 clash"}


def overall(report):
    sts = [c["status"] for c in report["checks"].values()]
    if FAIL in sts:
        return FAIL
    if WARN in sts:
        return WARN
    return OK


def render_report(report, compare=None):
    """The checklist Sai reads."""
    import textwrap
    L = []
    L.append("")
    L.append(f"Crazyflie preflight  {report.get('started', '')}")
    L.append("Read-only: nothing on the drone was changed.")
    L.append("")
    for key in ORDER:
        c = report["checks"].get(key)
        if not c:
            continue
        tag = f"[{c['status']:^4}]"
        head = f"{tag} {LABELS[key]:<11} "
        body = textwrap.wrap(c["summary"], width=100 - len(head)) or [""]
        L.append(head + body[0])
        L.extend(" " * len(head) + b for b in body[1:])
        if key == "decks":
            for n in c["details"].get("firmware_knows", []):
                p = c["details"]["decks"][n]
                mark = "yes" if p else ("?" if p is None else "no")
                if n in ("bcAI", "bcLighthouse4", "bcFlow2") or p:
                    L.append(" " * len(head) + f"  {mark:>3}  {DECK_NAMES.get(n, n)} (deck.{n})")
            for note in c["details"].get("notes", []):
                L.append(" " * len(head) + "  ! " + note)
        if key == "lighthouse":
            for line in c["details"].get("base_stations", []):
                L.append(" " * len(head) + "  - " + line)
    L.append("")
    legend = "OK = fine   WARN = read the line   FAIL = fix before a session   INFO = for the record   SKIP = not applicable"
    L.append(legend)
    uc = report["checks"].get("uart_conflict", {})
    if uc.get("details", {}).get("applicable"):
        L.append("")
        L.append("-" * 78)
        L.append("UART1 check (AI-deck + Lighthouse deck both on)")
        L.append("-" * 78)
        for k, v in uc["details"]["metrics"].items():
            L.append(f"  {k:<22} {v}")
        L.append("")
        L.extend("  " + s for s in UART_THEORY.splitlines())
    if compare is not None:
        L.append("")
        L.append("-" * 78)
        L.append(f"Compared with {compare.get('_path', 'the earlier run')}")
        L.append("-" * 78)
        L.extend(render_compare(report, compare))
    if report.get("errors"):
        L.append("")
        L.append("Things that could not be read (not fatal):")
        L.extend(f"  - {e}" for e in report["errors"])
    L.append("")
    return "\n".join(L)


def _metrics_for_compare(r):
    ch = r.get("checks", {})
    lh = (ch.get("lighthouse", {}).get("details") or {}).get("stats", {})
    bat = ch.get("battery", {}).get("details") or {}
    uc = (ch.get("uart_conflict", {}).get("details") or {}).get("metrics", {})
    return {
        "gap8_state": r.get("gap8_state"),
        "decks present": ",".join(ch.get("decks", {}).get("details", {}).get("present", [])),
        "battery V": bat.get("vbat_mean"),
        "lighthouse status (last)": lh.get("status_last"),
        "fraction at status 2": lh.get("status2_fraction"),
        "comSync fraction": lh.get("comSync_fraction"),
        "posRt mean (Hz)": lh.get("posRt_mean"),
        "base stations received (mean)": lh.get("receive_count_mean"),
        "position std, max axis (mm)": lh.get("position_std_mm_max"),
        "uart symptoms": len((ch.get("uart_conflict", {}).get("details") or {}).get("symptoms", []))
        if uc else None,
    }


def render_compare(now, before):
    a, b = _metrics_for_compare(before), _metrics_for_compare(now)
    out = [f"  {'':<32} {'earlier':>14} {'this run':>14}"]
    for k in a:
        out.append(f"  {k:<32} {str(a[k]):>14} {str(b[k]):>14}")
    return out


def discover_uris(scan=None):
    """Auto mode: USB first, then Crazyradio. (UDP/simulator only with --uri.)"""
    if scan is None:
        import cflib.crtp
        scan = cflib.crtp.scan_interfaces
    found = []
    try:
        found = [u[0] for u in scan()]
    except Exception:
        found = []
    usb = sorted(u for u in found if u.startswith("usb://"))
    radio = sorted(u for u in found if u.startswith("radio://"))
    return usb + radio


def connect_first(uris, make_link, log=print):
    """Try each URI in order; return (link, seconds, attempts)."""
    attempts = []
    for uri in uris:
        link = make_link(uri)
        log(f"  trying {uri} ...")
        try:
            secs = link.open()
            attempts.append({"uri": uri, "ok": True, "seconds": round(secs, 2)})
            return link, secs, attempts
        except ConnectError as e:
            attempts.append({"uri": uri, "ok": False, "error": str(e)})
            log(f"    {e}")
    return None, None, attempts


def default_out_path(now=None):
    now = now or _dt.datetime.now()
    return DEFAULT_OUT_DIR / f"{now.strftime('%Y%m%d-%H%M%S')}.json"


def save_json(report, path):
    path = Path(path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(report, indent=2, default=str))
    os.replace(tmp, path)
    return path


def main(argv=None, make_link=None, scan=None, out=sys.stdout):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--uri", help="connect to exactly this URI, e.g. usb://0, "
                    "radio://0/80/2M/E7E7E7E7E7, udp://127.0.0.1:19850 (simulator). "
                    "Default: scan USB first, then the Crazyradio.")
    ap.add_argument("--out", help=f"where to save the JSON (default {DEFAULT_OUT_DIR}/<time>.json)")
    ap.add_argument("--seconds", type=float, default=5.0, help="how long to listen to telemetry (default 5)")
    ap.add_argument("--period-ms", type=int, default=100, help="telemetry sample period (default 100 ms)")
    ap.add_argument("--connect-timeout", type=float, default=15.0, help="seconds to wait per URI (default 15)")
    ap.add_argument("--gap8", default="unknown", choices=["unknown", "running", "stopped", "no-deck"],
                    help="label for the UART1 comparison: is the GAP8 app running during this run?")
    ap.add_argument("--compare", help="an earlier preflight JSON to compare this run against")
    a = ap.parse_args(argv)

    def log(msg):
        print(msg, file=out, flush=True)

    started = _dt.datetime.now()
    out_path = Path(a.out).expanduser() if a.out else default_out_path(started)
    report = {"tool": "tools/hardware/preflight.py", "format": 1,
              "started": started.isoformat(timespec="seconds"), "read_only": True,
              "args": vars(a), "gap8_state": a.gap8, "checks": {}, "errors": []}
    compare = None
    if a.compare:
        try:
            compare = json.loads(Path(a.compare).expanduser().read_text())
            compare["_path"] = a.compare
        except Exception as e:
            log(f"(could not read --compare file: {e})")

    if make_link is None:
        cache = DEFAULT_OUT_DIR / "toc_cache"

        def make_link(uri):
            return CflibLink(uri, connect_timeout=a.connect_timeout, cache_dir=cache)

        try:
            import cflib.crtp
        except ImportError:
            log("cflib is not installed in this Python. Use the cfloaderenv venv:\n"
                "  ~/Downloads/drone/cfloaderenv/bin/python tools/hardware/preflight.py")
            return 2
        # cflib logs link errors as warnings with full tracebacks; the checklist
        # already explains them in plain words, so keep them off the screen.
        import logging
        logging.getLogger("cflib").addHandler(logging.NullHandler())
        logging.getLogger("cflib").propagate = False
        cflib.crtp.init_drivers()

    link = None
    code = 0
    try:
        log("Crazyflie preflight (read-only)")
        if a.uri:
            uris = [a.uri]
        else:
            log("  scanning USB, then the Crazyradio ...")
            uris = discover_uris(scan)
            if not uris:
                msg = ("No Crazyflie found. Over USB: battery plugged in (the drone is on), a DATA "
                       "micro-USB cable, and cfclient closed. Over radio: the Crazyradio needs a "
                       "USB-A adapter on this Mac, and the scan only finds the default address "
                       "E7E7E7E7E7; for a re-addressed drone pass --uri radio://0/<ch>/2M/<address>.")
                report["checks"]["link"] = check(FAIL, msg, attempts=[])
                report["overall"] = FAIL
                log(render_report(report))
                return 2
        link, secs, attempts = connect_first(uris, make_link, log)
        if link is None:
            report["checks"]["link"] = check(FAIL, attempts[-1]["error"] if attempts else "no URI",
                                             attempts=attempts)
            report["overall"] = FAIL
            log(render_report(report))
            return 2
        how = {"usb": "USB cable", "radio": "Crazyradio", "udp": "simulator (UDP)"}.get(
            link.uri.split(":")[0], link.uri.split(":")[0])
        report["checks"]["link"] = check(OK, f"{link.uri} via {how}, connected in {secs:.1f} s",
                                         uri=link.uri, connect_seconds=round(secs, 2),
                                         attempts=attempts,
                                         write_guards=len(getattr(link, "guarded", []) or []))
        other = load_other_runs(out_path.parent, exclude=out_path)
        run_preflight(link, a.seconds, a.period_ms, a.gap8, other, log, report=report)
        report["overall"] = overall(report)
        log(render_report(report, compare))
        code = 1 if report["overall"] == FAIL else 0
    except KeyboardInterrupt:
        report["interrupted"] = True
        report["overall"] = "INTERRUPTED"
        log("\nStopped with Ctrl-C. Telemetry blocks are being removed and the link closed; "
            "nothing on the drone was changed.")
        code = 130
    finally:
        if link is not None:
            try:
                link.close()
            except Exception:
                pass
        report["finished"] = _dt.datetime.now().isoformat(timespec="seconds")
        try:
            p = save_json(report, out_path)
            log(f"Saved: {p}")
        except OSError as e:
            log(f"Could not save the JSON to {out_path}: {e}")
    return code


if __name__ == "__main__":
    sys.exit(main())
