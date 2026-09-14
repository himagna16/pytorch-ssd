#!/usr/bin/env python
"""Did this flight actually run the network its plan row asked for?

The whole experiment rests on the chip backend having picked up the confuser's
ONNX *and the confuser's output scale* (id_output_eps, read from the
release_summary.json next to the ONNX).  If it silently fell back to the
champion's default, every "confuser" flight would be a champion flight wearing
a different name.  So it is checked per flight from what the follower itself
recorded, not assumed from what the command line said.

Usage: check_model.py RUN_DIR
Prints MODEL_OK, or MODEL_BAD <reasons>.  Exit 0 / 1.
"""
import json
import os
import sys


def main():
    run = sys.argv[1]
    cell = json.load(open(os.path.join(run, "cell.json")))
    s = json.load(open(os.path.join(run, "summary.json")))
    bi = s.get("backend_info") or {}
    bad = []
    if bi.get("onnx") != cell["chip_onnx"]:
        bad.append(f"onnx={bi.get('onnx')} wanted={cell['chip_onnx']}")
    if bi.get("eps") != cell["expected_eps"]:
        bad.append(f"eps={bi.get('eps')!r} wanted={cell['expected_eps']!r}")
    if s.get("backend") != "chip":
        bad.append(f"backend={s.get('backend')!r} wanted='chip'")
    if bad:
        print("MODEL_BAD " + "; ".join(bad))
        sys.exit(1)
    print(f"MODEL_OK onnx={bi.get('onnx')} eps={bi.get('eps')!r} sha1={bi.get('onnx_sha1')}")
    sys.exit(0)


if __name__ == "__main__":
    main()
