import csv, math, sys, numpy as np
def load(run, truth):
    r = [x for x in csv.DictReader(open(f"{run}/follow_log.csv")) if x["event"] == ""]
    T = np.loadtxt(truth, delimiter=",", ndmin=2)
    w = np.array([float(x["wall"]) for x in r]); t = np.array([float(x["t"]) for x in r])
    px = np.array([float(x["px"]) for x in r]); py = np.array([float(x["py"]) for x in r])
    yaw = np.array([float(x["yaw"]) for x in r]); cy = np.array([float(x["cmd_yaw"]) for x in r])
    tx = np.interp(w, T[:, 0], T[:, 2]); ty = np.interp(w, T[:, 0], T[:, 3])
    brg = np.degrees(np.arctan2(ty - py, tx - px))
    m = t - t[0] > 3.0
    return w[m], yaw[m], brg[m], cy[m], t[m]
for name in sys.argv[1:]:
    run, truth = f"run_{name}", f"truth_{name}.csv"
    w, yaw, brg, cy, t = load(run, truth)
    span = (t[-1] - t[0]) / 60
    nz = np.sign(cy[cy != 0]); rev = int(np.sum(nz[1:] != nz[:-1]))
    # yaw-rate reversals of the actual drone on a uniform 20 Hz grid (smoothed 0.25 s)
    g = np.arange(w[0], w[-1], 0.05); yg = np.interp(g, w, np.unwrap(np.radians(yaw)))
    rate = np.convolve(np.gradient(yg, 0.05), np.ones(5) / 5, "same"); rs = np.sign(rate[np.abs(np.degrees(rate)) > 2])
    yrev = int(np.sum(rs[1:] != rs[:-1]))
    bg = np.interp(g, w, brg); yd = np.degrees(yg)
    lags = np.arange(0, 41) * 0.05
    errs = [np.mean(np.abs(yd[k:] - bg[:len(bg) - k])) if k else np.mean(np.abs(yd - bg)) for k in range(41)]
    best = lags[int(np.argmin(errs))]
    print(f"{run}: yaw-cmd sign reversals {rev/span:.1f}/min, drone yaw-rate reversals {yrev/span:.1f}/min, "
          f"nonzero-cmd frac {np.mean(cy != 0):.2f}, yaw lag behind true bearing (best-fit) {best*1000:.0f} ms")
