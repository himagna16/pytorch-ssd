#!/usr/bin/env python3
"""Prove each generated scene definition differs from its base ONLY in the keys
make_pool_scenes.py claims to edit.

The experiment's whole claim is "only the person changed". This checks it against
the files rather than against the generator's intent: it walks both dicts and
reports every path whose value differs, then fails if any differing path is not
on the allowed list.

Usage: nemoenv/bin/python verify_scene_equivalence.py <outdir>
"""
import json
import sys
from pathlib import Path

ROOT = Path("/Users/saimaruvada/Downloads/drone/pytorch_ssd")
DEFS = ROOT / "tools/crazysim_macos/scene_defs"
OUT = Path(sys.argv[1])

ALLOWED = {
    "subjects[0].pos[0]", "subjects[0].pos[1]", "expected_behaviour.gates",
    "scene_id", "title", "purpose",
    "subjects[0].coco.img_id", "subjects[0].coco.ann_id", "subjects[0].note",
    "prediction.outcome", "prediction.rationale",
}
BASE_OF = {"dl16": "s15_static_offset", "dl22": "s15_static_offset", "dl28": "s15_static_offset"}


def walk(a, b, path=""):
    """every leaf path where a and b differ, plus keys present in one only"""
    out = []
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            p = f"{path}.{k}" if path else k
            if k not in a:
                out.append((p, "<absent in base>", b[k]))
            elif k not in b:
                out.append((p, a[k], "<absent in variant>"))
            else:
                out += walk(a[k], b[k], p)
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            out.append((path, f"<len {len(a)}>", f"<len {len(b)}>"))
        else:
            for i, (x, y) in enumerate(zip(a, b)):
                out += walk(x, y, f"{path}[{i}]")
    elif a != b:
        out.append((path, a, b))
    return out


def main():
    defs = sorted((OUT / "scene_defs").glob("*.json"))
    assert defs, "no generated defs"
    bad, n_checked = [], 0
    print(f"{'variant':<16}{'base':<22}{'diff paths':>11}  all allowed?")
    for f in defs:
        v = json.loads(f.read_text())
        base_id = BASE_OF[f.stem.split("_")[0]]
        b = json.loads((DEFS / f"{base_id}.json").read_text())
        diffs = walk(b, v)
        paths = sorted({p for p, _, _ in diffs})
        extra = [p for p in paths if p not in ALLOWED]
        n_checked += len(paths)
        print(f"{f.stem:<16}{base_id:<22}{len(paths):>11}  {'yes' if not extra else 'NO: ' + ','.join(extra)}")
        if extra:
            bad.append((f.stem, extra))
        # Every variant must change SOMETHING substantive. For the 12 pool
        # subjects that is the cutout; for the control arm it is the position
        # alone, since the control is the published cutout flown nearer.
        is_control = f.stem.endswith("_19432")
        moved = v["subjects"][0]["pos"] != b["subjects"][0]["pos"]
        if is_control:
            if not moved:
                bad.append((f.stem, ["control arm did not move"]))
        elif v["subjects"][0]["coco"]["img_id"] == 19432:
            bad.append((f.stem, ["cutout was not changed"]))
    print()
    if bad:
        raise SystemExit("EQUIVALENCE FAILED\n" + "\n".join(f"  {s}: {e}" for s, e in bad))
    print(f"{len(defs)} definitions, {n_checked} differing paths in total, every one on the")
    print("allowed list: the cutout, the subject's position, the emptied gates, and free")
    print("text. Position is what this experiment varies, so geometry is NOT identical;")
    print("bearing is held to better than 0.001 deg and is asserted at generation time.")
    print("Lighting, motion, height, target, scene_class and the floor are identical.")


if __name__ == "__main__":
    main()
