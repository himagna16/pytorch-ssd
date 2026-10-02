#!/usr/bin/env python3
"""Check kill_switch.py against CrazySim (SITL firmware). Never touches hardware: udp:// only.

    ~/Downloads/drone/cfloaderenv/bin/python tools/hardware/kill_switch_sim_check.py \
        --out docs/sim_results/2026-10-01-flight-modes/kill_switch_sitl.json

Each check starts a fresh simulator (the firmware locks after an emergency stop) with
tools/stm32_follow_app/sim/run_sim_follow_app.sh, runs, and shuts it down:

  key       the real CLI in a pseudo-terminal, drone on the ground: wait for the banner and some
            watchdog pings, press SPACE, read the CLI's own "supervisor reports LOCKED", press q;
            then a SECOND connection reads supervisor.info (bit 6 = locked)
  deadman   the real CLI, killed with SIGKILL (it cannot send anything); a second connection
            reads supervisor.info 2 s later: the firmware's watchdog must have locked it by itself
  inflight  one process (as a flight script would embed it): hover at 0.6 m with CRTP hover
            setpoints, KillSwitch on the same link via CflibKillLink.attach(cf), SPACE while the
            script keeps streaming hover setpoints; logs z, motor.m1 and supervisor.info at 50 Hz
  silence   the same hover, but the kill switch's pings simply stop (it died without a word):
            how long after the last ping the firmware's own watchdog stops the motors

Env defaults put the sim beside another one: CRAZYSIM_CONTAINER=crazysim-killsw,
CRAZYSIM_PORT=19970 (cflib udp://127.0.0.1:19870). FOLLOW_APP_IMAGE picks the firmware image.
"""
import argparse
import json
import os
import pty
import select
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
SIM = REPO / "tools" / "stm32_follow_app" / "sim" / "run_sim_follow_app.sh"
sys.path.insert(0, str(HERE))
import kill_switch as K                                         # noqa: E402


class Sim:
    def __init__(self, port, container, image, log):
        self.port, self.container, self.image, self.log = port, container, image, log
        self.p = None

    def __enter__(self):
        env = dict(os.environ, CRAZYSIM_PORT=str(self.port), CRAZYSIM_CONTAINER=self.container,
                   FOLLOW_APP_IMAGE=self.image)
        self.f = open(self.log, "w")
        self.p = subprocess.Popen([str(SIM)], env=env, stdout=self.f, stderr=subprocess.STDOUT,
                                  start_new_session=True)
        t0 = time.monotonic()
        while time.monotonic() - t0 < 60:
            if "firmware connected" in Path(self.log).read_text():
                time.sleep(2.0)
                return self
            if self.p.poll() is not None:
                break
            time.sleep(0.5)
        self.__exit__()
        raise RuntimeError(f"simulator did not come up; see {self.log}")

    def console(self):
        r = subprocess.run(["docker", "exec", self.container, "cat", "sitl_make/build/0/out.log"],
                           capture_output=True, text=True)
        return r.stdout

    def __exit__(self, *exc):
        if self.p and self.p.poll() is None:
            try:
                os.killpg(self.p.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        subprocess.run(["pkill", "-f", f"crazysim.py.*--port {self.port}"], capture_output=True)
        subprocess.run(["docker", "rm", "-f", self.container], capture_output=True)
        time.sleep(1.0)
        self.f.close()


def connect(uri):
    import warnings
    warnings.filterwarnings("ignore", category=DeprecationWarning)
    import cflib.crtp
    from cflib.crazyflie import Crazyflie
    from cflib.crazyflie.syncCrazyflie import SyncCrazyflie
    cflib.crtp.init_drivers()
    scf = SyncCrazyflie(uri, cf=Crazyflie(rw_cache=None))
    scf.open_link()
    return scf


def read_info(uri, seconds=1.0):
    """A fresh connection's view of supervisor.info (the CLI is gone by then)."""
    from cflib.crazyflie.log import LogConfig
    scf = connect(uri)
    got = []
    lc = LogConfig("chk", period_in_ms=50)
    lc.add_variable("supervisor.info", "uint16_t")
    lc.data_received_cb.add_callback(lambda ts, d, c: got.append(int(d["supervisor.info"])))
    scf.cf.log.add_config(lc)
    lc.start()
    time.sleep(seconds)
    lc.stop()
    scf.cf.commander.send_setpoint = lambda *a, **k: None   # close_link would send a zero setpoint
    scf.close_link()
    return got[-1] if got else None


class Pty:
    """The real CLI in a pseudo-terminal (so it sees a TTY and puts it in cbreak mode)."""

    def __init__(self, uri):
        self.master, slave = pty.openpty()
        self.p = subprocess.Popen([sys.executable, str(HERE / "kill_switch.py"), "--uri", uri, "--no-color"],
                                  stdin=slave, stdout=slave, stderr=slave, start_new_session=True)
        os.close(slave)
        self.buf = ""

    def read_until(self, text, timeout):
        t0 = time.monotonic()
        while time.monotonic() - t0 < timeout:
            if text in self.buf:
                return True
            r, _, _ = select.select([self.master], [], [], 0.1)
            if r:
                try:
                    self.buf += os.read(self.master, 65536).decode(errors="replace")
                except OSError:
                    break
        return text in self.buf

    def send(self, s):
        os.write(self.master, s.encode())

    def wait_exit(self, timeout):
        """Keep draining the terminal while waiting: a full pty buffer would block the CLI's redraw."""
        t0 = time.monotonic()
        while time.monotonic() - t0 < timeout:
            if self.p.poll() is not None:
                return self.p.returncode
            self.read_until("\0", 0.1)
        self.p.kill()
        return None

    def last_screen(self):
        parts = self.buf.split("\033[H\033[2J")
        return parts[-1] if parts else self.buf


def pings_in(screen):
    for line in screen.splitlines():
        if line.strip().startswith("watchdog"):
            try:
                return int(line.split()[1])
            except (IndexError, ValueError):
                return None
    return None


def check_key(uri, sim):
    cli = Pty(uri)
    ok_banner = cli.read_until("KILL SWITCH ARMED", 30)
    time.sleep(2.0)                                  # let the watchdog run
    cli.read_until("\0", 0.3)
    armed_screen = cli.last_screen()
    t_press = time.monotonic()
    cli.send(" ")
    locked_seen = cli.read_until("supervisor reports LOCKED", 5)
    t_locked = time.monotonic() - t_press if locked_seen else None
    stopped_screen = cli.last_screen()
    cli.send("q")
    code = cli.wait_exit(10)
    info = read_info(uri)
    return {
        "banner_shown": ok_banner,
        "pings_before_press": pings_in(armed_screen),
        "cli_saw_locked_after_s": round(t_locked, 2) if t_locked is not None else None,
        "cli_exit_code": code,
        "second_connection_supervisor_info": info,
        "second_connection_decoded": K.decode_info(info),
        "locked": K.is_locked(info),
        "firmware_console_tail": [l for l in sim.console().splitlines() if "SUP" in l or "ock" in l][-5:],
        "armed_screen": armed_screen.strip().splitlines(),
        "stopped_screen": stopped_screen.strip().splitlines(),
    }


def check_deadman(uri, sim):
    before = None
    cli = Pty(uri)
    ok = cli.read_until("KILL SWITCH ARMED", 30)
    time.sleep(2.0)
    cli.read_until("\0", 0.3)
    pings = pings_in(cli.last_screen())
    for line in cli.last_screen().splitlines():
        if line.strip().startswith("supervisor"):
            before = line.strip()
    t_kill = time.monotonic()
    cli.p.send_signal(signal.SIGKILL)                # no chance to send a stop
    cli.p.wait(5)
    time.sleep(2.0)
    info = read_info(uri)
    console = sim.console().splitlines()
    return {
        "banner_shown": ok, "pings_before_kill": pings, "supervisor_line_before_kill": before,
        "seconds_after_kill_when_read": round(time.monotonic() - t_kill, 1),
        "second_connection_supervisor_info": info, "second_connection_decoded": K.decode_info(info),
        "locked": K.is_locked(info),
        "firmware_console_tail": [l for l in console if "SUP" in l or "ock" in l or "fly" in l][-6:],
    }


def check_inflight(uri, sim, trace_csv, mode="key"):
    """mode "key": SPACE while hovering. mode "silence": the pings just stop (the kill switch died
    without sending anything) while the script keeps commanding the hover."""
    from cflib.crazyflie.log import LogConfig
    scf = connect(uri)
    cf = scf.cf
    rows, lock = [], threading.Lock()
    state = {"phase": "takeoff"}
    lc = LogConfig("trace", period_in_ms=20)
    lc.add_variable("stateEstimate.z", "float")
    lc.add_variable("supervisor.info", "uint16_t")
    if cf.log.toc.get_element_by_complete_name("motor.m1") is not None:
        lc.add_variable("motor.m1")
    t0 = time.monotonic()

    def cb(ts, d, c):
        with lock:
            rows.append({"t": round(time.monotonic() - t0, 3), "phase": state["phase"],
                         "z": round(d["stateEstimate.z"], 4), "info": int(d["supervisor.info"]),
                         "m1": d.get("motor.m1")})
    lc.data_received_cb.add_callback(cb)
    cf.log.add_config(lc)
    lc.start()
    z = 0.0
    while z < 0.6:                                   # take off with hover setpoints
        z = min(0.6, z + 0.02)
        cf.commander.send_hover_setpoint(0, 0, 0, z)
        time.sleep(0.05)
    for _ in range(40):
        cf.commander.send_hover_setpoint(0, 0, 0, 0.6)
        time.sleep(0.05)
    state["phase"] = "hover+killswitch"
    link = K.CflibKillLink.attach(cf, uri)
    ks = K.KillSwitch(link)
    ks.arm()
    stop = threading.Event()

    def pinger():
        while not stop.is_set():
            ks.tick()
            stop.wait(0.02)
    threading.Thread(target=pinger, daemon=True).start()
    for _ in range(20):
        cf.commander.send_hover_setpoint(0, 0, 0, 0.6)
        time.sleep(0.05)
    with lock:
        z_before = rows[-1]["z"]
    state["phase"] = "stop" if mode == "key" else "pings stop"
    if mode == "key":
        t_stop = time.monotonic() - t0
        ks.on_key(" ")                               # SPACE
    else:
        stop.set()                                   # the kill switch "dies": no more pings, no stop
        time.sleep(0.05)
        t_stop = ks.last_ping - t0                   # time of the last ping that went out
    for _ in range(40 if mode == "key" else 60):     # the "flight script" keeps commanding a hover
        cf.commander.send_hover_setpoint(0, 0, 0, 0.6)
        time.sleep(0.05)
    stop.set()
    lc.stop()
    cf.commander.send_setpoint = lambda *a, **k: None
    scf.close_link()
    after = [r for r in rows if r["t"] >= t_stop]
    first_locked = next((r for r in after if K.is_locked(r["info"])), None)
    first_floor = next((r for r in after if r["z"] < 0.05), None)
    m1_zero = next((r for r in after if r["m1"] == 0), None)
    with open(trace_csv, "w") as f:
        f.write("t,phase,z,supervisor_info,motor_m1\n")
        for r in rows:
            f.write(f"{r['t']},{r['phase']},{r['z']},{r['info']},{'' if r['m1'] is None else r['m1']}\n")
    return {
        "hover_z_before_stop": z_before, "pings_before_stop": ks.pings, "stops_sent": ks.stops_sent,
        "t_stop": round(t_stop, 3),
        "locked_logged_after_s": round(first_locked["t"] - t_stop, 3) if first_locked else None,
        "motor_m1_zero_after_s": round(m1_zero["t"] - t_stop, 3) if m1_zero else None,
        "z_below_5cm_after_s": round(first_floor["t"] - t_stop, 3) if first_floor else None,
        "z_end": rows[-1]["z"] if rows else None, "info_end": K.decode_info(rows[-1]["info"]) if rows else None,
        "mode": mode, "t_stop_is": "SPACE pressed" if mode == "key" else "last watchdog ping sent",
        "hover_setpoints_kept_streaming_after_stop_s": 2.0 if mode == "key" else 3.0,
        "firmware_console_tail": [l for l in sim.console().splitlines() if "SUP" in l or "ock" in l][-5:],
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--checks", default="key,deadman,inflight,silence")
    ap.add_argument("--port", type=int, default=int(os.environ.get("CRAZYSIM_PORT", 19970)))
    ap.add_argument("--container", default=os.environ.get("CRAZYSIM_CONTAINER", "crazysim-killsw"))
    ap.add_argument("--image", default=os.environ.get("FOLLOW_APP_IMAGE", "crazysim-mac:follow-app-safety"))
    ap.add_argument("--logdir", type=Path, default=Path.home() / "Downloads" / "drone" / "logs" / "kill_switch_sitl")
    a = ap.parse_args()
    uri = f"udp://127.0.0.1:{a.port - 100}"
    a.logdir.mkdir(parents=True, exist_ok=True)
    res = json.loads(a.out.read_text()) if a.out.exists() else {}
    res.update({"uri": uri, "image": a.image, "cflib_protocol_note":
           "SITL firmware reports CRTP protocol 7, so cflib sends the legacy localization-port stop/watchdog "
           "packets; firmware 2026.08 (protocol 12) gets the supervisor-port ones, which SITL cannot test"})
    for name in a.checks.split(","):
        with Sim(a.port, a.container, a.image, a.logdir / f"sim_{name}.log") as sim:
            if name == "key":
                res[name] = check_key(uri, sim)
            elif name == "deadman":
                res[name] = check_deadman(uri, sim)
            elif name == "inflight":
                res[name] = check_inflight(uri, sim, a.out.with_name("kill_switch_inflight_50hz.csv"))
            elif name == "silence":
                res[name] = check_inflight(uri, sim, a.out.with_name("kill_switch_silence_50hz.csv"),
                                           mode="silence")
        print(name, json.dumps({k: v for k, v in res[name].items() if "screen" not in k}, indent=1), flush=True)
    a.out.write_text(json.dumps(res, indent=2) + "\n")


if __name__ == "__main__":
    main()
