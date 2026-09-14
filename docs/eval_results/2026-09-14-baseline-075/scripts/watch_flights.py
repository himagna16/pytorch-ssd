#!/usr/bin/env python3
"""Per-flight observer for an unmodified run_acceptance2.sh session.

WHY THIS EXISTS
  The brief for this run says: fly the CORE matrix *via run_acceptance2.sh*, its
  normal matrix, with no threshold flags, so the run proves the follower's
  default rather than a harness argument.  run_acceptance2.sh is therefore
  launched exactly as shipped (``--out DIR --repeats 4``) and is not edited.

  That harness does not sample machine load and does not re-assert the floor
  per flight.  The two earlier sessions (matte baseline, threshold sweep) got
  both by copying fly() into their own harness.  This session keeps the real
  harness and adds an OBSERVER instead: this script tails progress.log with a
  bounded poll loop and, the moment a "flight N/56 ..." line appears, records

    * the 1/5/15-minute load average at flight start,
    * the floor of the scene about to be flown, read from that scene's
      manifest.json (room.floor_reflectance) AND from the reflectance attribute
      in its scene.xml, plus the sha256 of that scene.xml at that instant,

  and, when the harness prints its "-> VALID" / "-> INVALID" line, the load
  average at flight end and the wall time.  One JSON line per flight attempt
  goes to OUT/flights_watch.jsonl.  It cannot abort a flight (the harness owns
  the flight), so a non-matte floor would be recorded as a finding, not
  prevented; the pre-flight check in the README asserts all six scenes matte
  before the first flight and the scene files are hash-pinned across the run.

BOUNDED: exits when the harness PID is gone and the log has been quiet for
15 s, when the harness's final "artifacts:" line appears, or after --max-hours.
No tail -f, no watch.

Usage: watch_flights.py OUT_DIR HARNESS_PID SCENES_ROOT [MAX_HOURS]
"""
import datetime
import hashlib
import json
import os
import re
import sys
import time

OUT = sys.argv[1]
PID = int(sys.argv[2])
SCENES = sys.argv[3]
MAX_H = float(sys.argv[4]) if len(sys.argv) > 4 else 4.0

PROGRESS = os.path.join(OUT, "progress.log")
WATCH = os.path.join(OUT, "flights_watch.jsonl")
STATE = os.path.join(OUT, "watch_state.json")

START_RE = re.compile(
    r"^\[(\d\d:\d\d:\d\d)\] flight (\d+)/(\d+)\s+(\S+)\s+repeat (\d+) attempt (\d+)\s+"
    r"\((\S+), (\S+)/(\S+)/(\S+), (\d+)s\)")
END_RE = re.compile(r"^\[(\d\d:\d\d:\d\d)\]\s+-> (VALID|INVALID: .*|flight did not produce a run.*)$")
DONE_RE = re.compile(r"^\[(\d\d:\d\d:\d\d)\] artifacts: ")


def utc():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def pid_alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def floor_of(scene):
    sdir = os.path.join(SCENES, scene)
    rec = {"scene_dir": sdir}
    try:
        man = json.load(open(os.path.join(sdir, "manifest.json")))
        rec["floor_manifest"] = man["room"]["floor_reflectance"]
    except Exception as e:  # noqa: BLE001 - recorded, never raised
        rec["floor_manifest"] = None
        rec["floor_manifest_error"] = repr(e)
    try:
        xml = open(os.path.join(sdir, "scene.xml"), "rb").read()
        m = re.findall(rb'reflectance="([^"]*)"', xml)
        rec["floor_xml"] = [x.decode() for x in m]
        rec["scene_xml_sha256"] = hashlib.sha256(xml).hexdigest()
        rec["scene_xml_mtime_utc"] = datetime.datetime.fromtimestamp(
            os.path.getmtime(os.path.join(sdir, "scene.xml")), datetime.timezone.utc
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception as e:  # noqa: BLE001
        rec["floor_xml"] = None
        rec["floor_xml_error"] = repr(e)
    return rec


def flush(rec):
    with open(WATCH, "a") as f:
        f.write(json.dumps(rec) + "\n")
    print(f"[watch] {rec['order']:>2}/{rec['total']} {rec['cell']:<24} r{rec['repeat']}a{rec['attempt']} "
          f"{rec.get('verdict','?'):<8} wall {rec.get('wall_s','?')}s  "
          f"load1 {rec['load_before'][0]:.2f}->{(rec.get('load_after') or [float('nan')])[0]:.2f}  "
          f"floor man={rec['floor_manifest']} xml={rec['floor_xml']}", flush=True)


def main():
    t0 = time.time()
    pos = 0
    buf = ""
    cur = None
    done = False
    t_last_new = time.time()
    n_events = 0
    print(f"[watch] observing {PROGRESS} for harness pid {PID}; scenes {SCENES}; cap {MAX_H} h", flush=True)
    while time.time() - t0 < MAX_H * 3600:
        alive = pid_alive(PID)
        new = ""
        if os.path.exists(PROGRESS):
            with open(PROGRESS, "r", errors="replace") as f:
                f.seek(pos)
                new = f.read()
                pos = f.tell()
        if new:
            t_last_new = time.time()
            buf += new
            lines = buf.split("\n")
            buf = lines.pop()          # keep any partial trailing line for next poll
            for line in lines:
                m = START_RE.match(line)
                if m:
                    if cur is not None:
                        cur["verdict"] = "NO_END_LINE"
                        cur["t_end_utc"] = utc()
                        flush(cur)
                    la = os.getloadavg()
                    hh, n, tot, cid, rep, att, scene, backend, camera, speed, dur = m.groups()
                    cur = {"order": int(n), "total": int(tot), "cell": cid, "repeat": int(rep),
                           "attempt": int(att), "scene": scene, "backend": backend, "camera": camera,
                           "speed": speed, "duration_s": int(dur), "harness_clock_start": hh,
                           "t_start_utc": utc(), "t_start_epoch": time.time(),
                           "load_before": [round(x, 2) for x in la]}
                    cur.update(floor_of(scene))
                    json.dump(cur, open(STATE, "w"), indent=1)
                    n_events += 1
                    continue
                m = END_RE.match(line)
                if m and cur is not None:
                    la = os.getloadavg()
                    cur["harness_clock_end"] = m.group(1)
                    cur["verdict"] = m.group(2)
                    cur["t_end_utc"] = utc()
                    cur["wall_s"] = round(time.time() - cur.pop("t_start_epoch"), 1)
                    cur["load_after"] = [round(x, 2) for x in la]
                    flush(cur)
                    cur = None
                    n_events += 1
                    continue
                if DONE_RE.match(line):
                    done = True
        if done:
            print("[watch] harness printed its artifacts line; exiting", flush=True)
            break
        if not alive and time.time() - t_last_new > 15:
            print("[watch] harness pid gone and log quiet for 15 s; exiting", flush=True)
            break
        time.sleep(1.0)
    else:
        print(f"[watch] cap of {MAX_H} h reached; exiting", flush=True)
    if cur is not None:
        cur["verdict"] = "WATCHER_EXITED_MID_FLIGHT"
        cur["t_end_utc"] = utc()
        cur.pop("t_start_epoch", None)
        flush(cur)
    print(f"[watch] done: {n_events} events, {time.time() - t0:.0f} s", flush=True)


if __name__ == "__main__":
    main()
