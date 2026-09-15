#!/usr/bin/env python3
"""Prove, from the BUILT artefacts rather than from the definitions, that each
new scene differs from its original in the subject texture and nothing else.

Two comparisons per pair:

  1. manifest.json, walked key by key. Differences are classified:
       IDENTITY   the COCO source, the scene id, and free text
       DERIVED    quantities build_scene computes FROM the cutout's own bbox -
                  the panel's width and aspect, and the asset's sha256. A
                  different photograph has a different shape; this is what
                  "a different person" means, not an extra change.
       BUILD      built_at and builder.argv
       UNEXPECTED anything else. Must be empty, or this script exits 1.
  2. scene.xml, line by line, after masking the scene id and the texture file
     name. Must be identical - same room, same lights, same floor material and
     reflectance, same body name, same body pos, same panel half-height, same
     euler, same joint (or absence of one), same everything.

Usage: nemoenv/bin/python verify_scene_equivalence.py <scene_root> <outdir>
"""
import difflib
import json
import re
import sys
from pathlib import Path

SCENES = Path(sys.argv[1])
OUT = Path(sys.argv[2])
PAIRS = [("s15_static_offset", "tp15_static_median"),
         ("s15_static_offset", "tp15_static_p25"),
         ("s01_control_moving", "tp01_moving_median"),
         ("s01_control_moving", "tp01_moving_p25")]

IDENTITY = {
    "scene_id", "title", "purpose",
    "subjects[0].source.img_id", "subjects[0].source.ann_id",
    "subjects[0].source.file_name", "subjects[0].source.bbox_xywh",
    "subjects[0].note", "prediction.outcome", "prediction.rationale",
}
DERIVED = {
    "subjects[0].panel.width_m", "subjects[0].panel.aspect",
    "subjects[0].background.subject_fraction",
    "builder.asset_sha256", "builder.scene_xml_sha256",
}
BUILD = {"built_at", "builder.argv", "builder.scene_def"}
REPORT = []


def P(s=""):
    print(s, flush=True)
    REPORT.append(s)


def flat(o, pre=""):
    if isinstance(o, dict):
        for k, v in o.items():
            yield from flat(v, f"{pre}.{k}" if pre else k)
    elif isinstance(o, list) and o and isinstance(o[0], (dict, list)):
        for n, v in enumerate(o):
            yield from flat(v, f"{pre}[{n}]")
    else:
        yield pre, o


def classify(key):
    for s, name in ((IDENTITY, "IDENTITY"), (DERIVED, "DERIVED"), (BUILD, "BUILD")):
        if key in s or any(key.startswith(k + ".") for k in s):
            return name
    return "UNEXPECTED"


def main():
    bad = 0
    for base, new in PAIRS:
        a = json.loads((SCENES / base / "manifest.json").read_text())
        b = json.loads((SCENES / new / "manifest.json").read_text())
        fa, fb = dict(flat(a)), dict(flat(b))
        assert set(fa) == set(fb), (set(fa) ^ set(fb))
        diffs = [(k, fa[k], fb[k]) for k in fa if fa[k] != fb[k]]
        groups = {}
        for k, x, y in diffs:
            groups.setdefault(classify(k), []).append((k, x, y))
        P("=" * 78)
        P(f"{new}   vs   {base}")
        P("=" * 78)
        P(f"manifest keys compared: {len(fa)}   differing: {len(diffs)}")
        for g in ("UNEXPECTED", "DERIVED", "IDENTITY", "BUILD"):
            for k, x, y in groups.get(g, []):
                sx, sy = str(x), str(y)
                if len(sx) > 60 or len(sy) > 60:
                    sx, sy = sx[:57] + "...", sy[:57] + "..."
                P(f"  {g:<10} {k:<42} {sx}  ->  {sy}")
        if not groups.get("UNEXPECTED"):
            P("  UNEXPECTED: none")
        else:
            bad += 1
        P("")
        P("  the keys that MUST be equal, shown as the values they hold in both:")
        for k in ("room.floor_reflectance", "room.flight_height_m", "room.wall_rgb",
                  "room.drone_start", "lighting.variant", "lighting.headlight.diffuse",
                  "lighting.headlight.ambient", "camera.fovy_deg", "camera.focal_px",
                  "subjects[0].name", "subjects[0].role", "subjects[0].panel.height_m",
                  "subjects[0].panel.z_center_m", "subjects[0].panel.euler",
                  "subjects[0].motion.type", "subjects[0].motion.p0",
                  "subjects[0].motion.law", "subjects[0].motion.mechanism",
                  "subjects[0].truth.body", "expected_behaviour.target",
                  "expected_behaviour.verdict", "scripted_motion.env"):
            ks = [x for x in fa if x == k or x.startswith(k + "[")]
            for kk in ks or [k]:
                if kk in fa:
                    ok = fa[kk] == fb[kk]
                    P(f"    {'OK ' if ok else 'BAD'} {kk:<40} {fa[kk]}")
                    bad += 0 if ok else 1
        # gates, in full
        ng = len([k for k in fa if k.startswith("expected_behaviour.gates")])
        same = all(fa[k] == fb[k] for k in fa if k.startswith("expected_behaviour.gates"))
        P(f"    {'OK ' if same else 'BAD'} expected_behaviour.gates ({ng} fields) identical")
        bad += 0 if same else 1
        P("")

        # ---- scene.xml -----------------------------------------------------
        def mask(p, sid, subj):
            t = (SCENES / p / "scene.xml").read_text()
            t = t.replace(sid, "<SCENE_ID>")
            t = re.sub(r'file="[^"]*\.png"', 'file="<SUBJECT_TEXTURE>"', t)
            return t.splitlines()

        la = mask(base, base, None)
        lb = mask(new, new, None)
        d = list(difflib.unified_diff(la, lb, "orig", "new", lineterm="", n=0))
        P(f"  scene.xml, with the scene id and the texture filename masked: "
          f"{len(la)} vs {len(lb)} lines")
        # The ONE difference allowed: the panel geom's half-width (the y component
        # of its `size`), which build_scene computes as height_m/2 * bbox_w/bbox_h.
        # A different photograph is a different shape. Nothing else may move - in
        # particular not the half-height (0.8500), the thickness, the euler, the
        # body pos, or any joint.
        changed = [l for l in d if l[:1] in "+-" and not l.startswith(("---", "+++"))]
        def panel_size_only(lines):
            if len(lines) != 2:
                return False
            a2, b2 = sorted(lines)   # "+" sorts before "-"
            ra = re.search(r'size="([\d.]+) ([\d.]+) ([\d.]+)"', a2)
            rb = re.search(r'size="([\d.]+) ([\d.]+) ([\d.]+)"', b2)
            if not (ra and rb and "_panel" in a2 and "_panel" in b2):
                return False
            if ra.group(1) != rb.group(1) or ra.group(3) != rb.group(3):
                return False      # thickness or half-HEIGHT moved: not allowed
            return (a2[1:].replace(ra.group(0), "") == b2[1:].replace(rb.group(0), ""))
        if d and panel_size_only(changed):
            P("  ONE line differs, and it is the panel's half-WIDTH only:")
            for line in d:
                P("    " + line)
            P("  half-height 0.8500, thickness 0.004, euler, pos, body name, contype and")
            P("  conaffinity are unchanged - this is the cutout's own bbox aspect, i.e.")
            P("  the same thing the manifest reports as DERIVED panel.width_m.")
        elif d:
            P("  DIFFERS in something other than the panel half-width:")
            for line in d:
                P("    " + line)
            bad += 1
        else:
            P("  IDENTICAL - same room, walls, floor material and reflectance, lights,")
            P("  body name, body pos, panel half-sizes, euler, contype/conaffinity, joints.")
        P("")

    P("=" * 78)
    P("RESULT: " + ("EQUIVALENT - the only difference is which person is on the panel"
                    if bad == 0 else f"{bad} PROBLEM(S)"))
    P("=" * 78)
    (OUT / "tables/scene_equivalence.txt").write_text("\n".join(REPORT) + "\n")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
