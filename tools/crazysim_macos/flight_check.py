import time, logging
import cflib.crtp
from cflib.crazyflie import Crazyflie
from cflib.crazyflie.syncCrazyflie import SyncCrazyflie
from cflib.crazyflie.log import LogConfig
from cflib.positioning.motion_commander import MotionCommander
logging.basicConfig(level=logging.ERROR)
cflib.crtp.init_drivers()
rows, t0 = [], time.time()
with SyncCrazyflie('udp://127.0.0.1:19850', cf=Crazyflie(rw_cache='./cache')) as scf:
    lc = LogConfig('boot', period_in_ms=20)
    for v, t in [('stateEstimate.z', 'float'), ('supervisor.info', 'uint16_t'),
                 ('stateEstimate.roll', 'float'), ('stateEstimate.pitch', 'float')]:
        lc.add_variable(v, t)
    lc.data_received_cb.add_callback(lambda ts, d, _: rows.append((time.time() - t0, d)))
    scf.cf.log.add_config(lc); lc.start()
    time.sleep(3.0)
    idle = sorted({d['supervisor.info'] for _, d in rows})
    print(f"IDLE (3s, no commands): supervisor.info={idle}, z={rows[-1][1]['stateEstimate.z']:.2f}")
    mark = len(rows)
    with MotionCommander(scf, default_height=0.5):
        time.sleep(3.0)
    time.sleep(1.0); lc.stop()
prev = None
for t, d in rows[mark:]:
    s = d['supervisor.info']
    if s != prev:
        print(f"  t={t:5.2f}s supervisor.info={s:3d} ({s:08b}) z={d['stateEstimate.z']:+.2f} roll={d['stateEstimate.roll']:+6.1f} pitch={d['stateEstimate.pitch']:+6.1f}")
        prev = s
print(f"TAKEOFF: z max={max(d['stateEstimate.z'] for _, d in rows[mark:]):.2f} m")
