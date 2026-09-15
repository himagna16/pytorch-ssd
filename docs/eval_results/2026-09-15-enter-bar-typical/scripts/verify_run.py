#!/usr/bin/env python3
"""Refuse the run if anything about it is not what the plan asked for.

Four independent checks, all of which must pass before a single number in the
README is allowed to mean anything:

1. THRESHOLD.  For every flight, the plan row's vis_enter must equal the
   vis_enter that follow_person.py RECORDED IN ITS OWN summary.json, and
   vis_exit / confirm_frames must be the shipped 0.45 / 3.  A flight whose
   recorded threshold does not match its plan row is not scored, however clean
   its dynamics were.  This is the check the brief asked for by name.
2. SCENE.  Every flight's scene.xml sha256, recorded by the runner before the
   simulator started, must equal the artefact 2026-09-15-typical-person built.
   No scene was rebuilt here; this proves it.
3. SETUP.  backend/camera/rate/latency/seed/floor identical across the two arms
   of each cell, so the arms differ in the bar and nothing else.
4. PAIRING.  The two arms of a repeat must carry the same sensor seed.

Usage: nemoenv/bin/python verify_run.py <suite_dir> <plan.tsv> [<plan2.tsv> ...]
"""
import csv
import hashlib
import json
import sys
from pathlib import Path

D = Path(sys.argv[1])
PLANS = [Path(p) for p in sys.argv[2:]]
SCENES = Path("/private/tmp/claude-501/-Users-saimaruvada-Downloads"
              "/90541ca8-cca5-4400-9855-79d1dde551f0/scratchpad/typical_scenes")
fails, lines = [], []


def P(s=""):
    print(s, flush=True)
    lines.append(s)


plan = {}
for pf in PLANS:
    with open(pf) as f:
        for row in f:
            if row.startswith("#") or not row.strip():
                continue
            o, venter, cid, scene, cls, backend, camera, speed, dur, rep, block = \
                row.rstrip("\n").split("\t")
            plan[(venter, cid, int(rep))] = dict(
                scene=scene, backend=backend, camera=camera, speed=speed,
                dur=int(dur), block=int(block), order=int(o))

P("=" * 100)
P("1. THRESHOLD: plan row vs the vis_enter follow_person.py recorded in summary.json")
P("=" * 100)
P(f"{'run':<36}{'plan enter':>11}{'rec enter':>11}{'rec exit':>10}{'rec cf':>8}"
  f"{'cell.json':>11}  verdict")
seen = {}
for rd in sorted((D / "runs").glob("*")):
    sp, cp = rd / "summary.json", rd / "cell.json"
    if not sp.exists() or not cp.exists():
        P(f"{rd.name:<36}  NO summary.json/cell.json - not a scored flight")
        continue
    s, c = json.loads(sp.read_text()), json.loads(cp.read_text())
    arm = rd.name.split("__")[0][1:]
    key = (arm, c["cell_id"], c["repeat"])
    want = plan.get(key)
    ok = (want is not None
          and abs(s.get("vis_enter", -1) - float(arm)) < 1e-9
          and abs(c["vis_enter"] - float(arm)) < 1e-9
          and abs(s.get("vis_exit", -1) - 0.45) < 1e-9
          and s.get("confirm_frames") == 3)
    P(f"{rd.name:<36}{arm:>11}{str(s.get('vis_enter')):>11}{str(s.get('vis_exit')):>10}"
      f"{str(s.get('confirm_frames')):>8}{str(c['vis_enter']):>11}  {'OK' if ok else 'MISMATCH'}")
    if not ok:
        fails.append(f"threshold mismatch: {rd.name}")
    seen[key] = rd

missing = [k for k in plan if k not in seen]
P(f"\nplan rows: {len(plan)}   flights found: {len(seen)}   missing: {missing if missing else 'none'}")
if missing:
    fails.append(f"missing flights: {missing}")

P("")
P("=" * 100)
P("2. SCENE: sha256 of the scene.xml each flight actually loaded, vs the artefact on disk")
P("=" * 100)
onfile = {}
for sd in sorted(SCENES.glob("*/scene.xml")):
    onfile[sd.parent.name] = hashlib.sha256(sd.read_bytes()).hexdigest()
for name, h in onfile.items():
    P(f"  {name:<22}{h[:32]}")
badscene = []
for key, rd in sorted(seen.items()):
    p = rd / "scene_xml_sha256.txt"
    c = json.loads((rd / "cell.json").read_text())
    if not p.exists():
        badscene.append(rd.name); continue
    if p.read_text().strip() != onfile.get(c["scene"]):
        badscene.append(rd.name)
P(f"\n  every flight's recorded scene hash matches its scene on disk: "
  f"{'YES, all ' + str(len(seen)) if not badscene else 'NO -> ' + str(badscene)}")
if badscene:
    fails.append(f"scene hash mismatch: {badscene}")

P("")
P("=" * 100)
P("3+4. SETUP AND PAIRING: the two arms of a cell/repeat differ in the bar and nothing else")
P("=" * 100)
FIELDS = ["scene", "scene_class", "backend", "camera", "speed", "rate_hz",
          "latency_ms", "duration_s", "sensor_seed", "floor_reflectance",
          "floor_reflectance_manifest", "vis_exit", "confirm_frames"]
cells = sorted({(k[1], k[2]) for k in seen})
for cid, rep in cells:
    a, b = seen.get(("0.70", cid, rep)), seen.get(("0.75", cid, rep))
    if not a or not b:
        P(f"  {cid} r{rep}: only one arm present - cannot pair")
        fails.append(f"unpaired: {cid} r{rep}")
        continue
    ca = json.loads((a / "cell.json").read_text())
    cb = json.loads((b / "cell.json").read_text())
    diff = [f for f in FIELDS if ca.get(f) != cb.get(f)]
    P(f"  {cid:<22} r{rep}  seed {ca['sensor_seed']}  "
      f"{'IDENTICAL on all ' + str(len(FIELDS)) + ' setup fields' if not diff else 'DIFFERS: ' + str(diff)}")
    if diff:
        fails.append(f"setup differs between arms: {cid} r{rep} {diff}")
    # camera_model.json: the camera's IDENTITY must match (same preset, same
    # seed, same parameter block -> the same noise draw).  Two of its keys are
    # deliberately NOT identity and are reported, not gated:
    #   cost  - this run's own inference timing statistics;
    #   state - the auto-exposure state AT THE END of the flight, which depends
    #           on where the drone ended up.  It differs exactly when the two
    #           arms flew different trajectories, i.e. it is a CONSEQUENCE of
    #           the bar, not a confound on it.  (Below: it is identical on every
    #           cell where neither arm latched, and differs only where one did.)
    ID = ["preset", "seed", "width", "height", "params", "unmeasured", "derived"]
    ma, mb = a / "camera_model.json", b / "camera_model.json"
    if ma.exists() and mb.exists():
        ja, jb = json.loads(ma.read_text()), json.loads(mb.read_text())
        idiff = [k for k in ID if ja.get(k) != jb.get(k)]
        info = [k for k in ("state", "cost") if ja.get(k) != jb.get(k)]
        P(f"      camera identity ({len(ID)} fields): "
          f"{'IDENTICAL' if not idiff else 'DIFFERS ' + str(idiff)}"
          f"   non-identity keys differing: {info if info else 'none'}")
        if idiff:
            fails.append(f"camera identity differs: {cid} r{rep} {idiff}")

P("")
P("=" * 100)
P("VERDICT: " + ("ALL CHECKS PASS" if not fails else f"{len(fails)} FAILURES"))
for f in fails:
    P("  FAIL " + f)
P("=" * 100)
(D / "tables/verify_run.txt").write_text("\n".join(lines) + "\n")
sys.exit(1 if fails else 0)
