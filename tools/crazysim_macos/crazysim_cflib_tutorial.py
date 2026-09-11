# Adapted from the cflib tutorial in MinHyuk Park's Crazyflie_Simulator_Container
# README (MIT License, Copyright (c) 2026 MinHyuk Park).
# Change: default URI uses 127.0.0.1, which is what works from macOS.
#!/usr/bin/env python3
"""
cflib tutorial for CrazySim
===========================

Each demo is standalone and runs against a simulated Crazyflie over the
UDP link that CrazySim's cflib fork provides.

Usage:
    python3 crazysim_cflib_tutorial.py list
    python3 crazysim_cflib_tutorial.py 1
    python3 crazysim_cflib_tutorial.py 4 --uri udp://0.0.0.0:19851

Start with demo 1 and 2 (no motors). Demos 4 onward will actually fly
the drone in Gazebo, so make sure you have space in your world file.
"""

import argparse
import logging
import sys
import time

import cflib.crtp
from cflib.crazyflie import Crazyflie
from cflib.crazyflie.log import LogConfig
from cflib.crazyflie.syncCrazyflie import SyncCrazyflie
from cflib.crazyflie.syncLogger import SyncLogger
from cflib.positioning.motion_commander import MotionCommander
from cflib.positioning.position_hl_commander import PositionHlCommander

DEFAULT_URI = 'udp://127.0.0.1:19850'

# cflib is chatty at DEBUG; ERROR keeps the tutorial output readable.
logging.basicConfig(level=logging.ERROR)


# ---------------------------------------------------------------------------
# 1. Connecting
# ---------------------------------------------------------------------------

def demo_connect(uri):
    """Open a link, print what's on the other end, close cleanly.

    init_drivers() registers every CRTP backend, including the udpdriver
    that CrazySim's fork adds. Without it the udp:// scheme is unknown.
    """
    print('Scanning for interfaces...')
    for iface in cflib.crtp.scan_interfaces():
        print('  found:', iface[0])

    print(f'\nConnecting to {uri}')
    with SyncCrazyflie(uri, cf=Crazyflie(rw_cache='./cache')) as scf:
        print('Connected.')
        print('  firmware :', scf.cf.param.get_value('firmware.revision0'))
        print('  log vars :', len(scf.cf.log.toc.toc))
        print('  params   :', len(scf.cf.param.values))
    print('Disconnected.')


# ---------------------------------------------------------------------------
# 2. Parameters
# ---------------------------------------------------------------------------

def demo_params(uri):
    """Read and write parameters.

    Params are the drone's settings: estimator choice, controller gains,
    flight-mode flags. They're grouped as 'group.name'.
    """
    with SyncCrazyflie(uri, cf=Crazyflie(rw_cache='./cache')) as scf:
        cf = scf.cf

        for name in ('stabilizer.estimator',
                     'stabilizer.controller',
                     'commander.enHighLevel'):
            print(f'{name:28s} = {cf.param.get_value(name)}')

        # Writes are async; the drone acks and cflib updates its cache.
        print('\nEnabling high-level commander...')
        cf.param.set_value('commander.enHighLevel', '1')
        time.sleep(0.2)
        print('commander.enHighLevel        =',
              cf.param.get_value('commander.enHighLevel'))

        # Browse the TOC when you're hunting for a param name.
        names = sorted(f'{group}.{name}'
                       for group, entries in cf.param.toc.toc.items()
                       for name in entries)
        print(f'\n{len(names)} params available; first 15:')
        for full in names[:15]:
            print('  ', full)


# ---------------------------------------------------------------------------
# 3. Logging
# ---------------------------------------------------------------------------

def demo_logging_sync(uri):
    """Pull telemetry synchronously — simplest way to read state.

    A LogConfig is a block of variables the drone streams back at a fixed
    period. Max 26 bytes per block, so watch your variable count.
    """
    lg = LogConfig(name='Position', period_in_ms=100)
    lg.add_variable('stateEstimate.x', 'float')
    lg.add_variable('stateEstimate.y', 'float')
    lg.add_variable('stateEstimate.z', 'float')
    lg.add_variable('stabilizer.yaw', 'float')

    with SyncCrazyflie(uri, cf=Crazyflie(rw_cache='./cache')) as scf:
        print('Streaming pose for 5 seconds...')
        with SyncLogger(scf, lg) as logger:
            start = time.time()
            for timestamp, data, logconf in logger:
                print(f'  x={data["stateEstimate.x"]:+.2f} '
                      f'y={data["stateEstimate.y"]:+.2f} '
                      f'z={data["stateEstimate.z"]:+.2f} '
                      f'yaw={data["stabilizer.yaw"]:+.1f}')
                if time.time() - start > 5:
                    break


def demo_logging_async(uri):
    """Same data via callbacks — what you want inside a larger program.

    The callback fires on cflib's link thread, so keep it short and don't
    block in it.
    """
    def on_data(timestamp, data, logconf):
        print(f'  [{timestamp:>8}] vx={data["stateEstimate.vx"]:+.2f} '
              f'vy={data["stateEstimate.vy"]:+.2f} '
              f'vz={data["stateEstimate.vz"]:+.2f}')

    def on_error(logconf, msg):
        print('Log error:', msg)

    lg = LogConfig(name='Velocity', period_in_ms=200)
    lg.add_variable('stateEstimate.vx', 'float')
    lg.add_variable('stateEstimate.vy', 'float')
    lg.add_variable('stateEstimate.vz', 'float')

    with SyncCrazyflie(uri, cf=Crazyflie(rw_cache='./cache')) as scf:
        scf.cf.log.add_config(lg)
        lg.data_received_cb.add_callback(on_data)
        lg.error_cb.add_callback(on_error)

        lg.start()
        print('Logging asynchronously for 5 seconds...')
        time.sleep(5)
        lg.stop()


# ---------------------------------------------------------------------------
# 4. Flying: MotionCommander (relative moves)
# ---------------------------------------------------------------------------

def reset_estimator(scf):
    """Zero the Kalman filter and wait for it to settle.

    Do this before every flight. The estimator's position drifts to
    wherever it last thought it was, and takeoff from a bad estimate
    produces a very confused drone.
    """
    cf = scf.cf
    cf.param.set_value('kalman.resetEstimation', '1')
    time.sleep(0.1)
    cf.param.set_value('kalman.resetEstimation', '0')
    time.sleep(2.0)


def demo_motion_commander(uri):
    """Relative movement — think 'forward 0.5m', not 'go to (1,2)'.

    MotionCommander takes off on __enter__ and lands on __exit__, so the
    with-block guarantees the drone comes down even if something raises.
    """
    with SyncCrazyflie(uri, cf=Crazyflie(rw_cache='./cache')) as scf:
        reset_estimator(scf)

        with MotionCommander(scf, default_height=0.5) as mc:
            print('Took off to 0.5 m')
            time.sleep(2)

            print('Forward 0.5 m');    mc.forward(0.5); time.sleep(1)
            print('Left 0.5 m');       mc.left(0.5);    time.sleep(1)
            print('Back 0.5 m');       mc.back(0.5);    time.sleep(1)
            print('Right 0.5 m');      mc.right(0.5);   time.sleep(1)

            print('Turning 360 deg');  mc.turn_left(360)
            time.sleep(1)

            print('Up to 1.0 m');      mc.up(0.5);      time.sleep(2)
            print('Landing')
        # Landed and disarmed here.


# ---------------------------------------------------------------------------
# 5. Flying: PositionHlCommander (absolute waypoints)
# ---------------------------------------------------------------------------

def demo_position_commander(uri):
    """Absolute waypoints in the world frame — closer to how you'd fly
    a real trajectory. Requires commander.enHighLevel = 1.
    """
    with SyncCrazyflie(uri, cf=Crazyflie(rw_cache='./cache')) as scf:
        scf.cf.param.set_value('commander.enHighLevel', '1')
        reset_estimator(scf)

        with PositionHlCommander(
                scf,
                x=0.0, y=0.0, z=0.0,
                default_velocity=0.4,
                default_height=0.6) as pc:

            square = [(0.5, 0.0), (0.5, 0.5), (0.0, 0.5), (0.0, 0.0)]
            for x, y in square:
                print(f'Going to ({x}, {y}, 0.6)')
                pc.go_to(x, y, 0.6)
                time.sleep(0.5)

            print('Climbing to 1.0 m')
            pc.go_to(0.0, 0.0, 1.0)
            time.sleep(1)
            print('Landing')


# ---------------------------------------------------------------------------
# 6. Flying + logging together
# ---------------------------------------------------------------------------

def demo_fly_and_log(uri):
    """Run a flight while recording the trajectory, then dump a summary.

    This is the shape of most real experiments: command, record, analyze.
    """
    samples = []

    def on_data(timestamp, data, logconf):
        samples.append((timestamp,
                        data['stateEstimate.x'],
                        data['stateEstimate.y'],
                        data['stateEstimate.z']))

    lg = LogConfig(name='Traj', period_in_ms=50)
    for v in ('stateEstimate.x', 'stateEstimate.y', 'stateEstimate.z'):
        lg.add_variable(v, 'float')

    with SyncCrazyflie(uri, cf=Crazyflie(rw_cache='./cache')) as scf:
        scf.cf.log.add_config(lg)
        lg.data_received_cb.add_callback(on_data)
        lg.start()

        reset_estimator(scf)
        with MotionCommander(scf, default_height=0.5) as mc:
            time.sleep(2)
            mc.forward(0.8)
            time.sleep(1)
            mc.back(0.8)
            time.sleep(1)

        lg.stop()

    print(f'\nCaptured {len(samples)} samples')
    if samples:
        xs = [s[1] for s in samples]
        zs = [s[3] for s in samples]
        print(f'  x range: {min(xs):+.2f} to {max(xs):+.2f} m')
        print(f'  z range: {min(zs):+.2f} to {max(zs):+.2f} m')

        with open('trajectory.csv', 'w') as f:
            f.write('timestamp,x,y,z\n')
            for row in samples:
                f.write(','.join(str(c) for c in row) + '\n')
        print('  wrote trajectory.csv')


# ---------------------------------------------------------------------------

DEMOS = {
    1: ('connect',            demo_connect),
    2: ('params',             demo_params),
    3: ('logging (sync)',     demo_logging_sync),
    4: ('logging (async)',    demo_logging_async),
    5: ('motion commander',   demo_motion_commander),
    6: ('position commander', demo_position_commander),
    7: ('fly and log',        demo_fly_and_log),
}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('demo', help='demo number, or "list"')
    ap.add_argument('--uri', default=DEFAULT_URI,
                    help=f'CRTP URI (default: {DEFAULT_URI})')
    args = ap.parse_args()

    if args.demo == 'list':
        for n, (name, _) in DEMOS.items():
            print(f'  {n}. {name}')
        return 0

    try:
        n = int(args.demo)
        name, fn = DEMOS[n]
    except (ValueError, KeyError):
        print(f'Unknown demo: {args.demo!r} (try "list")', file=sys.stderr)
        return 1

    cflib.crtp.init_drivers()
    print(f'=== Demo {n}: {name} ===\n')
    fn(args.uri)
    return 0


if __name__ == '__main__':
    sys.exit(main())
