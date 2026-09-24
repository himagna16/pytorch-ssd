#!/usr/bin/env python3
"""Does the Lighthouse room frame match the tape on the floor? A read-only, guided check.

    ~/Downloads/drone/cfloaderenv/bin/python tools/lighthouse/tape_check.py

Run it right after cfclient's geometry wizard. It walks you through four placements of
the drone on the floor tape (docs/hardware/dorm_lighthouse_tape.svg), listens to the
drone's own position and heading for 3 s at each, and says PASS or FAIL:

  A  on the ORIGIN X, camera facing the window        expect x 0.00, y 0.00, yaw   0
  B  on the +x mark, camera facing the window         expect x 1.00, y 0.00, yaw   0
  C  on the SIDE mark, camera facing the window       expect x 0.00, y +0.61, yaw  0
  D  on the ORIGIN X, turned 90 deg to its LEFT       expect x 0.00, y 0.00, yaw +90

The SIDE mark is 2 tiles from the origin, sideways, in the middle of col 5 (the column
on your LEFT when you stand at the origin facing the window). Crazyflie convention:
x forward, y left, z up, yaw positive when the nose turns LEFT.

Step D is the one that matters most. It is the first check of the yaw sign on real
hardware (tools/lighthouse/README.md): a flipped yaw would make every Lighthouse label
mirrored, which trains a drone to steer away from people.

Read-only like tools/hardware/preflight.py, whose write guards it installs before
connecting: it never arms, sends setpoints, writes parameters or touches the radio
config. It only reads stateEstimate.x/y/z/yaw through a temporary log block.
"""
import argparse
import datetime as _dt
import json
import math
import statistics as st
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "hardware"))

SIDE_Y = 0.6096          # 2 tiles of 12 in
POS_TOL = 0.08           # m: tape and tile placement are good to a few cm
YAW_TOL = 12.0           # deg
NOISE_WARN = 0.02        # m: position std above this while the drone sits still

STEPS = [
    ("A", "Put the drone flat on the ORIGIN X, camera facing the +x MARK.", dict(x=0.0, y=0.0, yaw=0.0)),
    ("B", "Move it onto the +x mark (1.00 m from the origin), camera facing the same way (away from the origin).",
     dict(x=1.0, y=0.0, yaw=0.0)),
    ("C", "Move it onto the SIDE mark (2 tiles to the LEFT of the origin when you face the +x mark), camera facing the +x direction.",
     dict(x=0.0, y=SIDE_Y, yaw=0.0)),
    ("D", "Back on the ORIGIN X, then TURN it 90 deg to its LEFT (camera now faces the SIDE mark).",
     dict(x=0.0, y=0.0, yaw=90.0)),
]


def wrap180(a):
    return (a + 180.0) % 360.0 - 180.0


def circ_mean_deg(angles):
    s = sum(math.sin(math.radians(a)) for a in angles)
    c = sum(math.cos(math.radians(a)) for a in angles)
    return math.degrees(math.atan2(s, c))


def evaluate(step, samples):
    """samples: list of dicts with x, y, z, yaw. Returns a verdict dict (pure; unit-tested)."""
    name, _, exp = step
    if len(samples) < 5:
        return dict(step=name, verdict="NO DATA", why=f"only {len(samples)} samples; is the deck seeing the base stations?")
    m = {k: st.fmean(s[k] for s in samples) for k in ("x", "y", "z")}
    m["yaw"] = circ_mean_deg([s["yaw"] for s in samples])
    noise = max(st.pstdev([s[k] for s in samples]) for k in ("x", "y", "z"))
    errs = dict(x=m["x"] - exp["x"], y=m["y"] - exp["y"], yaw=wrap180(m["yaw"] - exp["yaw"]))
    ok = abs(errs["x"]) <= POS_TOL and abs(errs["y"]) <= POS_TOL and abs(errs["yaw"]) <= YAW_TOL
    why = []
    if not ok:
        if name == "C" and abs(m["y"] + exp["y"]) <= POS_TOL and abs(errs["x"]) <= POS_TOL:
            why.append("y came out NEGATIVE: the room frame is mirrored left-right. Redo the geometry "
                       "wizard, and check the +x mark is toward the window.")
        if name == "D" and abs(wrap180(m["yaw"] + exp["yaw"])) <= YAW_TOL:
            why.append("yaw came out NEGATIVE for a LEFT turn: the yaw sign is backwards. STOP and tell Claude.")
        if name in ("A", "D") and math.hypot(m["x"], m["y"]) > POS_TOL:
            why.append("the origin is not where the tape is: redo the wizard's origin sample on the X.")
        if name == "B" and abs(errs["x"]) > POS_TOL and abs(m["y"]) <= POS_TOL:
            why.append(f"x reads {m['x']:.2f} m for a 1.00 m mark: check the +x tape distance.")
        if name in ("A", "B", "C") and abs(errs["yaw"]) > YAW_TOL and not why:
            why.append("heading is off: point the camera straight at the window, or the wizard's x axis is skewed.")
    if noise > NOISE_WARN:
        why.append(f"position is jittery (std {noise * 100:.1f} cm) while sitting still: check both stations are seen.")
    return dict(step=name, verdict="PASS" if ok else "FAIL", expected=exp,
                measured={k: round(v, 3) for k, v in m.items()}, error={k: round(v, 3) for k, v in errs.items()},
                noise_m=round(noise, 4), n=len(samples), why=why)


def fmt(v):
    m, e = v["measured"], v["error"]
    return (f"   measured x {m['x']:+.2f} m  y {m['y']:+.2f} m  z {m['z']:+.2f} m  yaw {m['yaw']:+6.1f} deg"
            f"   (off by x {e['x']:+.2f}, y {e['y']:+.2f}, yaw {e['yaw']:+.1f})")


def connect_and_sample(uri, seconds):
    """Generator-style helper: returns (scf, sample_fn). Only this touches cflib."""
    import cflib.crtp
    from cflib.crazyflie import Crazyflie
    from cflib.crazyflie.log import LogConfig
    from cflib.crazyflie.syncCrazyflie import SyncCrazyflie
    from cflib.crazyflie.syncLogger import SyncLogger
    from preflight import install_write_guards

    cflib.crtp.init_drivers()
    cf = Crazyflie(rw_cache=str(Path.home() / ".cache" / "tape_check"))
    guarded = install_write_guards(cf)
    scf = SyncCrazyflie(uri, cf=cf)
    scf.open_link()

    def sample():
        lc = LogConfig(name="tape", period_in_ms=50)
        for v in ("x", "y", "z", "yaw"):
            lc.add_variable(f"stateEstimate.{v}", "float")
        out, t_end = [], time.time() + seconds
        with SyncLogger(scf, lc) as logger:
            for _, data, _ in logger:
                out.append({k.split(".")[1]: float(v) for k, v in data.items()})
                if time.time() >= t_end:
                    break
        return out
    return scf, sample, len(guarded)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--uri", default="usb://0", help="default usb://0 (the cable); e.g. radio://0/80/2M/E7E7E7E7E7")
    ap.add_argument("--seconds", type=float, default=3.0)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    print(f"== Lighthouse tape check, {a.uri}. Read-only: nothing here can move the drone.")
    try:
        scf, sample, n_guard = connect_and_sample(a.uri, a.seconds)
    except Exception as e:  # noqa: BLE001
        print(f"FAIL: could not connect to {a.uri}: {str(e)[:200]}")
        print("   Is the drone on the cable with the battery in, and is cfclient DISCONNECTED?")
        return 2
    print(f"   connected ({n_guard} write methods locked)\n")
    results = []
    try:
        for step in STEPS:
            print(f"-- {step[0]}. {step[1]}")
            input("   Hands off, then press Enter to measure... ")
            v = evaluate(step, sample())
            results.append(v)
            if v["verdict"] == "NO DATA":
                print(f"   NO DATA: {v['why']}")
            else:
                print(fmt(v))
                print(f"   {v['verdict']}")
            for w in v.get("why", []):
                if v["verdict"] != "NO DATA":
                    print(f"   ! {w}")
            print()
    finally:
        # cflib's close_link() sends a zero setpoint before closing; the write guard would raise
        # there and leave the link open. Make it a no-op that sends nothing, then close cleanly.
        scf.cf.commander.send_setpoint = lambda *a, **k: None
        scf.close_link()

    passed = sum(r["verdict"] == "PASS" for r in results)
    print(f"== {passed} of {len(results)} PASS")
    if passed == len(STEPS):
        print("   The Lighthouse frame matches the tape, and a LEFT turn reads as positive yaw.")
        print("   Yaw sign CONFIRMED on real hardware.")
    else:
        print("   Not all PASS. Send Claude this output before collecting anything.")
    out = Path(a.out) if a.out else (Path.home() / "Downloads" / "drone" / "logs" / "tape_check" /
                                     f"{_dt.datetime.now():%Y-%m-%dT%H%M%S}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(dict(uri=a.uri, when=_dt.datetime.now().isoformat(), results=results), indent=1))
    print(f"   saved {out}")
    return 0 if passed == len(STEPS) else 1


if __name__ == "__main__":
    sys.exit(main())
