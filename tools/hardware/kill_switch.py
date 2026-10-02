#!/usr/bin/env python3
"""KILL SWITCH for Crazyflie flights. One key stops every motor at once. The drone FALLS.

    ~/Downloads/drone/cfloaderenv/bin/python tools/hardware/kill_switch.py
    ~/Downloads/drone/cfloaderenv/bin/python tools/hardware/kill_switch.py --uri udp://127.0.0.1:19850   # CrazySim

    SPACE or ENTER or Ctrl-C  ->  emergency stop (cflib cf.supervisor.send_emergency_stop())
    radio link lost           ->  emergency stop is attempted, and the drone stops itself (below)

WHAT A STOP IS. The firmware's supervisor cuts the motors immediately and locks the drone. It
does not land. A flying drone drops straight down. The drone stays locked until it is power-cycled.
Use it when continuing to fly is worse than a fall from that height.

DEAD-MAN WATCHDOG. While this program runs it sends cf.supervisor.send_emergency_stop_watchdog()
every 0.1 s. After the first one, the firmware expects one at least every 1.0 s
(DEFAULT_EMERGENCY_STOP_WATCHDOG_TIMEOUT in supervisor.c, crazyflie-firmware 2026.08 and the SITL
firmware alike) and stops the motors by itself when they stop coming: when this program crashes,
is killed, its terminal is closed, the laptop sleeps, or the radio link drops. That also means:
once this program has started, closing it locks the drone, flying or not. Power-cycle the drone
before the next flight.

ONE RADIO, ONE PROGRAM. A Crazyradio can be opened by one program at a time, and Bitcraze does not
support two clients on one Crazyflie. So the kill switch either is the only program talking to the
drone (it can then be the only one: the follow app flies by itself once followapp.enable is set),
or it runs inside the flight script's process on the same link: create a KillSwitch with
CflibKillLink.attach(cf) (see the README, "Kill switch"). A second Crazyradio for this tool alone
has not been tested.

Other keys do nothing (there is no way to quit without stopping: the watchdog would stop the drone
anyway). After a stop: SPACE/ENTER sends the stop again, q or Ctrl-C quits.

Exit codes: 0 stop sent and the supervisor reported "locked"; 1 stop sent, lock not confirmed;
2 not started (no connection, or stdin is not a terminal): nothing was armed, nothing protected.

The logic (KillSwitch) does not import cflib; test_kill_switch.py drives it with a fake link.
"""
import argparse
import os
import signal
import sys
import threading
import time
import warnings
from pathlib import Path

DEFAULT_URI = "radio://0/80/2M/E7E7E7E709"   # the lab drones' stored address (preflight, 2026-09-24)
URI_SCHEMES = ("radio://", "usb://", "udp://")

FIRMWARE_WATCHDOG_TIMEOUT_S = 1.0   # supervisor.c DEFAULT_EMERGENCY_STOP_WATCHDOG_TIMEOUT (2026.08, SITL)
WATCHDOG_PERIOD_S = 0.1             # 10 pings per firmware timeout: 9 radio losses in a row still OK
STOP_REPEATS = 5                    # each stop is sent this many times, STOP_GAP_S apart (lossy radio)
STOP_GAP_S = 0.02
STOP_KEYS = (" ", "\r", "\n")
QUIT_KEYS = ("q", "Q")

# supervisor.info bits (crazyflie-firmware supervisor.c, LOG_GROUP supervisor; cflib supervisor.py)
INFO_BITS = ["can be armed", "armed", "auto-arm", "can fly", "FLYING", "tumbled", "LOCKED", "crashed",
             "HL active", "HL done", "HL disabled", "deck fault"]
BIT_FLYING, BIT_LOCKED = 4, 6


def classify_key(ch):
    """'stop' for the stop keys, 'quit' for q, None for everything else."""
    if ch in STOP_KEYS:
        return "stop"
    if ch in QUIT_KEYS:
        return "quit"
    return None


def decode_info(bits):
    if bits is None:
        return "unknown (no supervisor.info)"
    names = [n for i, n in enumerate(INFO_BITS) if bits >> i & 1]
    return ", ".join(names) if names else "none set"


def is_locked(bits):
    return bits is not None and bool(bits >> BIT_LOCKED & 1)


def check_uri(uri):
    if not uri.startswith(URI_SCHEMES):
        raise ValueError(f"unsupported URI {uri!r}: use radio://..., usb://... or udp://...")
    return uri


class KillSwitch:
    """Watchdog pings and the stop. Thread-safe: tick() runs in its own thread, keys and link-loss
    callbacks arrive from others. `link` needs send_watchdog() and send_stop(); both may raise."""

    def __init__(self, link, clock=time.monotonic, sleep=time.sleep):
        self.link, self.clock, self.sleep = link, clock, sleep
        self.lock = threading.Lock()
        self.armed = False
        self.stopped = False
        self.stop_reason = None
        self.stop_time = None
        self.stop_wall = None
        self.stops_sent = 0
        self.pings = 0
        self.last_ping = None
        self.next_ping = None
        self.link_lost = None
        self.errors = []

    def arm(self):
        """Start the dead-man: the first ping goes out now."""
        with self.lock:
            self.armed = True
            self.next_ping = self.clock()
        self.tick()

    def tick(self):
        """Send a watchdog ping if one is due. Returns True if it sent one."""
        with self.lock:
            if not self.armed or self.stopped:
                return False
            now = self.clock()
            if now < self.next_ping:
                return False
            # keep the cadence (polling lateness does not accumulate); after a stall, restart it
            self.next_ping += WATCHDOG_PERIOD_S
            if self.next_ping <= now:
                self.next_ping = now + WATCHDOG_PERIOD_S
        try:
            self.link.send_watchdog()
        except Exception as e:                      # link down: the drone's own watchdog takes over
            self._error(f"watchdog ping failed: {e}")
            return False
        with self.lock:
            self.pings += 1
            self.last_ping = now
        return True

    def stop(self, reason):
        """Emergency stop, sent STOP_REPEATS times. Callable again (a second press re-sends)."""
        with self.lock:
            first = not self.stopped
            self.stopped = True
            if first:
                self.stop_reason, self.stop_time, self.stop_wall = reason, self.clock(), time.time()
        for i in range(STOP_REPEATS):
            try:
                self.link.send_stop()
                with self.lock:
                    self.stops_sent += 1
            except Exception as e:
                self._error(f"emergency stop send failed: {e}")
            if i + 1 < STOP_REPEATS:
                self.sleep(STOP_GAP_S)
        return first

    def on_key(self, ch):
        """Returns 'stop', 'quit' or None. 'quit' only counts once the motors were stopped."""
        kind = classify_key(ch)
        if kind == "stop":
            self.stop("key " + {" ": "SPACE", "\r": "ENTER", "\n": "ENTER"}[ch])
            return "stop"
        if kind == "quit" and self.stopped:
            return "quit"
        return None

    def on_interrupt(self, what="Ctrl-C"):
        self.stop(what)

    def on_link_lost(self, msg):
        with self.lock:
            self.link_lost = msg
        self.stop(f"link lost ({msg})")         # best effort; the drone's watchdog stops it anyway

    def _error(self, msg):
        with self.lock:
            if len(self.errors) < 50:
                self.errors.append(msg)

    def ping_age(self):
        with self.lock:
            return None if self.last_ping is None else self.clock() - self.last_ping


class CflibKillLink:
    """The only part that touches cflib. open() connects its own Crazyflie; attach(cf) wraps the
    flight script's already-connected one (same process, same radio)."""

    def __init__(self, uri, connect_timeout=15.0, cache_dir=None):
        self.uri = uri
        self.connect_timeout = connect_timeout
        self.cache_dir = cache_dir
        self.cf = None
        self.owned = False
        self.info = None
        self.info_time = None
        self.protocol = None
        self._lc = None
        self._lost_cbs = []

    @classmethod
    def attach(cls, cf, uri=""):
        self = cls(uri)
        self.cf = cf
        self._after_connect()
        return self

    def open(self):
        import cflib.crtp
        from cflib.crazyflie import Crazyflie

        cflib.crtp.init_drivers()
        cache = None
        if self.cache_dir:
            try:
                Path(self.cache_dir).mkdir(parents=True, exist_ok=True)
                cache = str(self.cache_dir)
            except OSError:
                cache = None
        cf = Crazyflie(rw_cache=cache)
        done, err = threading.Event(), {}
        cf.fully_connected.add_callback(lambda uri: done.set())
        cf.connection_failed.add_callback(lambda uri, msg: (err.setdefault("msg", msg), done.set()))
        cf.open_link(self.uri)
        if not done.wait(self.connect_timeout):
            cf.close_link()
            raise ConnectionError(f"no answer from {self.uri} within {self.connect_timeout:.0f} s")
        if "msg" in err:
            raise ConnectionError(f"could not connect to {self.uri}: {err['msg']}")
        self.cf, self.owned = cf, True
        self._after_connect()

    def _after_connect(self):
        # cflib warns on every supervisor call to firmware older than protocol 12 (CrazySim's SITL is 7)
        # and then uses the legacy localization-port packets, which that firmware handles.
        warnings.filterwarnings("ignore", message="The supervisor subsystem requires")
        try:
            self.protocol = self.cf.platform.get_protocol_version()
        except Exception:
            self.protocol = None
        self.cf.connection_lost.add_callback(self._lost)
        self.cf.disconnected.add_callback(lambda uri: self._lost(uri, "disconnected"))
        try:
            from cflib.crazyflie.log import LogConfig
            if self.cf.log.toc.get_element_by_complete_name("supervisor.info") is not None:
                lc = LogConfig("killsw", period_in_ms=100)
                lc.add_variable("supervisor.info", "uint16_t")
                lc.data_received_cb.add_callback(self._on_info)
                self.cf.log.add_config(lc)
                lc.start()
                self._lc = lc
        except Exception:
            self._lc = None

    def _on_info(self, ts, data, lc):
        self.info = int(data["supervisor.info"])
        self.info_time = time.monotonic()

    def _lost(self, uri, msg):
        for cb in list(self._lost_cbs):
            cb(msg)

    def on_lost(self, cb):
        self._lost_cbs.append(cb)

    def send_watchdog(self):
        self.cf.supervisor.send_emergency_stop_watchdog()

    def send_stop(self):
        self.cf.supervisor.send_emergency_stop()

    def supervisor_info(self):
        """(bits, age_s) of the newest supervisor.info sample, or (None, None)."""
        if self.info is None:
            return None, None
        return self.info, time.monotonic() - self.info_time

    def close(self):
        if self._lc is not None:
            try:
                self._lc.stop()
            except Exception:
                pass
        if self.owned and self.cf is not None:
            try:
                self.cf.close_link()   # cflib sends a zero setpoint first: harmless, the motors are stopped
            except Exception:
                pass


# --------------------------------------------------------------------------- terminal

RED, GREEN, YELLOW, BOLD, RESET = "\033[41;97m", "\033[42;30m", "\033[43;30m", "\033[1m", "\033[0m"


def screen(ks, link, uri, color=True):
    """The whole screen as a list of lines."""
    c = (lambda code, s: f"{code}{s}{RESET}") if color else (lambda code, s: s)
    W = 76
    bits, age = link.supervisor_info() if hasattr(link, "supervisor_info") else (None, None)
    L = []
    if not ks.stopped:
        box = [
            "",
            "   KILL SWITCH ARMED",
            "",
            "   SPACE  or  ENTER  or  Ctrl-C   =   STOP ALL MOTORS NOW",
            "",
            "   The drone does NOT land. The motors stop and it FALLS.",
            "   Dead-man: if this program stops or the radio link drops,",
            f"   the drone stops its own motors within {FIRMWARE_WATCHDOG_TIMEOUT_S:.0f} s.",
            "",
        ]
        L += [c(GREEN, f"{s:<{W}}") for s in box]
    else:
        when = time.strftime("%H:%M:%S", time.localtime(ks.stop_wall)) if ks.stop_wall else "?"
        box = [
            "",
            f"   EMERGENCY STOP SENT  {when}  ({ks.stop_reason})",
            "",
            "   Motors stopped. The drone is locked until it is power-cycled.",
            "   SPACE/ENTER = send the stop again     q or Ctrl-C = quit",
            "",
        ]
        L += [c(RED, f"{s:<{W}}") for s in box]
    L.append("")
    proto = f"protocol {link.protocol}" if getattr(link, "protocol", None) is not None else ""
    legacy = " (legacy stop/watchdog packets)" if isinstance(getattr(link, "protocol", None), int) and link.protocol < 12 else ""
    L.append(f" link        {uri}  {proto}{legacy}")
    pa = ks.ping_age()
    L.append(f" watchdog    {ks.pings} pings, last {('%.2f s ago' % pa) if pa is not None else 'never'}"
             f"   (sent every {WATCHDOG_PERIOD_S:.1f} s{'; stopped' if ks.stopped else ''})")
    sup = decode_info(bits)
    if bits is not None and age is not None and age > 1.0:
        sup += f"   [last report {age:.1f} s old]"
    L.append(f" supervisor  {sup}")
    if is_locked(bits):
        L.append(" " + c(BOLD, "supervisor reports LOCKED: the motors are off"))
    if ks.stopped:
        L.append(f" stop        sent {ks.stops_sent} times")
    if ks.link_lost:
        L.append(" " + c(YELLOW, f"LINK LOST ({ks.link_lost}): the drone's watchdog stops it within "
                                 f"{FIRMWARE_WATCHDOG_TIMEOUT_S:.0f} s of the last ping. Watch it."))
    for e in ks.errors[-3:]:
        L.append(f" ! {e}")
    return L


class TerminalKeys:
    """Single keys from a TTY without Enter (cbreak: Ctrl-C still raises KeyboardInterrupt)."""

    def __init__(self, stream=sys.stdin):
        self.stream = stream
        self.fd = stream.fileno()
        self.saved = None

    def __enter__(self):
        import termios
        import tty
        self.saved = termios.tcgetattr(self.fd)
        tty.setcbreak(self.fd)
        # no XON/XOFF: a stray Ctrl-S would otherwise freeze the screen output
        attrs = termios.tcgetattr(self.fd)
        attrs[0] &= ~(termios.IXON | termios.IXOFF)
        termios.tcsetattr(self.fd, termios.TCSANOW, attrs)
        return self

    def __exit__(self, *exc):
        import termios
        if self.saved is not None:
            termios.tcsetattr(self.fd, termios.TCSADRAIN, self.saved)

    def get(self, timeout):
        import select
        r, _, _ = select.select([self.fd], [], [], timeout)
        if not r:
            return None
        ch = os.read(self.fd, 1).decode(errors="replace")
        return ch or None


class Abort(Exception):
    """SIGTERM / SIGHUP (terminal closed): treated like Ctrl-C."""


def run(ks, link, uri, keys, out=sys.stdout, color=True, redraw_s=0.2, confirm_s=2.0, clear=True):
    """The interactive loop. Returns the exit code.

    Three threads, so nothing can hold up the stop key: the pinger sends the watchdog, the drawer
    redraws the screen (a terminal that stops reading blocks only the drawer), and this thread
    only reads keys and acts on them."""
    stop_flag = threading.Event()
    out_lock = threading.Lock()

    def draw():
        text = ("\033[H\033[2J" if clear else "") + "\n".join(screen(ks, link, uri, color)) + "\n"
        with out_lock:
            out.write(text)
            out.flush()

    def pinger():
        while not stop_flag.is_set():
            ks.tick()
            stop_flag.wait(0.02)

    first_drawn = threading.Event()

    def drawer():
        while True:
            try:
                draw()
            except Exception:
                pass
            first_drawn.set()
            if stop_flag.wait(max(redraw_s, 0.01)):
                return

    ks.arm()
    threading.Thread(target=pinger, daemon=True).start()
    dth = threading.Thread(target=drawer, daemon=True)
    dth.start()
    first_drawn.wait(0.5)                    # never longer: a stuck terminal must not delay the keys
    quitting = False
    try:
        while True:
            try:
                ch = keys.get(0.05)
                if ch is not None and ks.on_key(ch) == "quit":
                    quitting = True
                    break
            except (KeyboardInterrupt, Abort) as e:
                if ks.stopped:
                    break                    # Ctrl-C after a stop: quit
                ks.on_interrupt("Ctrl-C" if isinstance(e, KeyboardInterrupt) else "terminal closed / SIGTERM")
                break
    finally:
        stop_flag.set()
        if not ks.stopped:                   # any other way out (an exception) also stops the drone
            ks.stop("kill switch exiting")
    dth.join(0.5)
    if dth.is_alive():                       # the terminal is not taking output: skip the final screen
        return 0 if is_locked(link.supervisor_info()[0] if hasattr(link, "supervisor_info") else None) else 1
    # wait briefly for the supervisor to confirm the lock
    t0 = time.monotonic()
    while not quitting and time.monotonic() - t0 < confirm_s:
        bits, _ = link.supervisor_info() if hasattr(link, "supervisor_info") else (None, None)
        if is_locked(bits):
            break
        time.sleep(0.05)
    draw()
    bits, _ = link.supervisor_info() if hasattr(link, "supervisor_info") else (None, None)
    return 0 if is_locked(bits) else 1


def main(argv=None, make_link=None, keys=None, out=sys.stdout):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("--uri", default=DEFAULT_URI,
                    help=f"radio://, usb:// or udp:// (default {DEFAULT_URI}; CrazySim: udp://127.0.0.1:19850)")
    ap.add_argument("--connect-timeout", type=float, default=15.0)
    ap.add_argument("--no-color", action="store_true")
    a = ap.parse_args(argv)
    try:
        uri = check_uri(a.uri)
    except ValueError as e:
        ap.error(str(e))
    if keys is None and not sys.stdin.isatty():
        out.write("stdin is not a terminal: run this in a terminal window so SPACE works. Nothing was armed.\n")
        return 2
    out.write(f"Connecting to {uri} ... (nothing is armed until connected)\n")
    out.flush()
    link = make_link(uri) if make_link else CflibKillLink(
        uri, connect_timeout=a.connect_timeout,
        cache_dir=Path.home() / "Downloads" / "drone" / "logs" / "cflib_cache")
    try:
        link.open()
    except Exception as e:
        out.write(f"\nCOULD NOT CONNECT: {e}\nNothing was armed. This program is NOT protecting the drone.\n")
        return 2
    ks = KillSwitch(link)
    if hasattr(link, "on_lost"):
        link.on_lost(ks.on_link_lost)

    def _abort(signum, frame):
        raise Abort()

    old = {}
    for sig in (signal.SIGTERM, signal.SIGHUP):
        try:
            old[sig] = signal.signal(sig, _abort)
        except (ValueError, OSError):        # not the main thread (tests)
            pass
    try:
        if keys is not None:
            return run(ks, link, uri, keys, out=out, color=not a.no_color, clear=False)
        with TerminalKeys() as tk:
            return run(ks, link, uri, tk, out=out, color=not a.no_color)
    finally:
        for sig, h in old.items():
            signal.signal(sig, h)
        link.close()


if __name__ == "__main__":
    sys.exit(main())
