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
    "scene_id", "title", "purpose",
    "subjects[0].coco.img_id", "subjects[0].coco.ann_id", "subjects[0].note",
    "prediction.outcome", "prediction.rationale",
}
BASE_OF = {"pp15": "s15_static_offset", "pp01": "s01_control_moving"}


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
        # the coco edit must actually be the intended one
        if v["subjects"][0]["coco"]["img_id"] == 19432:
            bad.append((f.stem, ["cutout was not changed"]))
    print()
    if bad:
        raise SystemExit("EQUIVALENCE FAILED\n" + "\n".join(f"  {s}: {e}" for s, e in bad))
    print(f"{len(defs)} definitions, {n_checked} differing paths in total, every one on the")
    print("allowed list. Lighting, geometry, motion, gates, target, scene_class and the")
    print("floor are byte-identical to the base scene in every variant.")


if __name__ == "__main__":
    main()
