#!/usr/bin/env python3
"""Drive the operator's capture chain over a rendered clip set, one clip at a time.

For every clip folder under --rendered this does what the operator does at the
bench, with the SAME two commands the runbook prints (absolute paths, trainenv
python), only without the human between them:

    terminal 1:  mock_streamer.py --frames <clip> --port 5151 --once --fps 15
    terminal 2:  cpx_grab.py --host 127.0.0.1 --port 5151 --seconds 2 --every 1
                             --dist D --bearing B --vis V --subject S --light room
                             --take K --out <out>

`--once` makes the mock exit after the client disconnects, so every step is
bounded. Everything both processes print goes to <out>/capture_chain.log and
the exact commands to <out>/commands.txt.
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

PY = Path.home() / "Downloads/drone/trainenv/bin/python"
REPO = Path.home() / "Downloads/drone/pytorch_ssd"
MOCK = REPO / "tools/real_frames/mock_streamer.py"
GRAB = REPO / "tools/crazysim_macos/cpx_grab.py"


def labels_for(name, info):
    """cpx_grab label flags for one rendered clip, per the protocol's table."""
    if name.startswith("person_"):
        return ["--dist", f"{info['dist_m']:g}", "--bearing", f"{info['bearing_deg']:g}",
                "--vis", "1", "--subject", "p01", "--light", "room"]
    if name.startswith("empty_take"):
        return ["--vis", "0", "--subject", "empty", "--light", "room",
                "--take", name[len("empty_take"):]]
    if name.startswith("pet_"):
        # the protocol: plush/pet at 2.5 m, 0 deg, --vis 0 (must NOT be tracked)
        return ["--dist", "2.5", "--bearing", "0", "--vis", "0", "--subject", "pet",
                "--light", "room"]
    raise SystemExit(f"do not know how to label {name}")


def wait_for(path, needle, timeout):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if path.exists() and needle in path.read_text(errors="replace"):
            return True
        time.sleep(0.2)
    return False


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rendered", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--port", type=int, default=5151)
    ap.add_argument("--seconds", type=float, default=2.0)
    ap.add_argument("--fps", type=float, default=15.0)
    ap.add_argument("--only", default=None, help="substring filter on clip names")
    a = ap.parse_args()

    manifest = json.loads((a.rendered / "render_manifest.json").read_text())
    a.out.mkdir(parents=True, exist_ok=True)
    log = open(a.out / "capture_chain.log", "a")
    cmds = open(a.out / "commands.txt", "a")

    def say(s):
        print(s, flush=True)
        log.write(s + "\n")
        log.flush()

    failures = 0
    for name, info in manifest["clips"].items():
        if a.only and a.only not in name:
            continue
        clip_dir = a.rendered / name
        # One subfolder per subject, the way the runbook's date folder ends up
        # (mirror/, check/, ...): the scorer walks subfolders, and it lets the
        # empty-room folder be scored on its own for the NO DATA verdict.
        group = name.split("_")[0].replace("person", "p01")
        mock_cmd = [str(PY), str(MOCK), "--frames", str(clip_dir), "--port", str(a.port),
                    "--once", "--fps", f"{a.fps:g}"]
        grab_cmd = [str(PY), str(GRAB), "--host", "127.0.0.1", "--port", str(a.port),
                    "--seconds", f"{a.seconds:g}", "--every", "1"] + labels_for(name, info) \
                   + ["--out", str(a.out / group)]
        cmds.write("# " + name + "\n" + " ".join(mock_cmd) + " &\n" + " ".join(grab_cmd) + "\n\n")
        cmds.flush()
        say(f"\n=== {name}")
        mock_log = a.out / f".mock_{name}.log"
        with open(mock_log, "w") as ml:
            mock = subprocess.Popen(mock_cmd, stdout=ml, stderr=subprocess.STDOUT)
        try:
            if not wait_for(mock_log, "mock AI-deck streaming", 30):
                say(f"FAIL: mock did not come up in 30 s:\n{mock_log.read_text()}")
                failures += 1
                continue
            say("[terminal 1] " + mock_log.read_text().strip().splitlines()[0])
            say("[terminal 2] $ " + " ".join(grab_cmd[1:]))
            pr = subprocess.run(grab_cmd, capture_output=True, text=True, timeout=60)
            lines = (pr.stdout + pr.stderr).strip().splitlines()
            keep = [l for l in lines if not l.startswith("saved ")] + \
                   [l for l in lines if l.startswith("saved ")][-1:]
            for l in keep:
                say("    " + l)
            if pr.returncode != 0:
                say(f"FAIL: cpx_grab exit code {pr.returncode}")
                failures += 1
        finally:
            try:
                mock.wait(timeout=20)
            except subprocess.TimeoutExpired:
                mock.kill()
                say("WARNING: mock did not exit on its own after the client left; killed")
            mtail = mock_log.read_text().strip().splitlines()[-1:]
            say("[terminal 1] " + (mtail[0] if mtail else "(no output)"))
            mock_log.unlink(missing_ok=True)
    say(f"\ndone: {failures} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
