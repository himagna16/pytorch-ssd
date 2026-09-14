#!/usr/bin/env python3
"""Generate decode test vectors whose expected answers come from the project's own
Python decode (utils/follow_task.py::decode_follow_outputs on successor-release)
and from the simulator follower's confirmation rule (follow_person.py).

Output format (read by test_follow_decode.c):
  EPS <eps_out>
  V <14 raw ints> <exp_x_bin> <exp_size_bucket> <exp_counts(conf>=ENTER)> <exp_lost(conf<EXIT)>
  S <n> <n raw visibility values> <n expected tracking flags>
"""
import argparse
import math
import random
import sys
from pathlib import Path

import torch

HEAD = "xbin9_size_bucket4"
# The adopted latch rule (2026-09-13). Must equal follow_vis_cfg_default() in follow_decode.c;
# ENTER was 0.7 until 2026-09-13 (docs/firmware_contract.md, change note).
ENTER, EXIT, CONFIRM = 0.75, 0.45, 3


def follower_states(confs):
    """Exact copy of the follower's state update (follow_person.py main loop)."""
    streak, vis, out = 0, False, []
    for conf in confs:
        streak = streak + 1 if conf >= ENTER else 0
        if vis and conf < EXIT:
            vis = False
        elif not vis and streak >= CONFIRM:
            vis = True
        out.append(int(vis))
    return out


def main():
    here = Path(__file__).resolve()
    ap = argparse.ArgumentParser()
    ap.add_argument("--unstable", default=str(here.parents[3] / "pytorch_ssd_unstable"),
                    help="path to the successor-release checkout (has utils/follow_task.py)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--n-vectors", type=int, default=400)
    ap.add_argument("--n-seqs", type=int, default=40)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    sys.path.insert(0, a.unstable)
    from utils.follow_task import decode_follow_outputs  # noqa: E402

    def decode(rows, eps):
        t = torch.tensor(rows, dtype=torch.float64) * eps
        return decode_follow_outputs(t, HEAD)

    # Sanity: David's known-good GVSOC tensor must decode as the contract says.
    david = [4632, 13262, 4633, -2422, -3479, -5390, 2962, -1854, -11170, 5303, -7980, 3540, 4466, -43]
    d = decode([david], 1e-4)
    assert int(d["x_bin_index"][0]) == 1 and int(d["size_bucket_index"][0]) == 2, "contract example drifted"

    rng = random.Random(a.seed)
    lines = []
    for eps in (1e-4, 3.7e-4, 1.0 / 4096, 0.0368, 0.25):
        lines.append(f"EPS {eps!r}")
        t_in, t_out = math.log(ENTER / (1 - ENTER)) / eps, math.log(EXIT / (1 - EXIT)) / eps
        boundary = [int(math.floor(t)) + k for t in (t_in, t_out) for k in (-1, 0, 1, 2)]
        rows = []
        for i in range(a.n_vectors):
            r = [rng.randint(-(1 << 20), 1 << 20) for _ in range(14)]
            if i % 5 == 0:  # inject ties inside the x block and the size block
                j, k = rng.sample(range(9), 2); r[k] = r[j] = max(r[:9])
                j, k = rng.sample(range(10, 14), 2); r[k] = r[j] = max(r[10:14])
            if i < len(boundary):
                r[9] = boundary[i]
            rows.append(r)
        dec = decode(rows, eps)
        conf = dec["visibility_confidence"].tolist()
        for r, xb, sb, c in zip(rows, dec["x_bin_index"].tolist(), dec["size_bucket_index"].tolist(), conf):
            lines.append("V " + " ".join(map(str, r)) + f" {xb} {sb} {int(c >= ENTER)} {int(c < EXIT)}")
        pool = boundary + [int(t_in) * 3, int(t_out) * 3, 0, rng.randint(-(1 << 20), 1 << 20)]
        for _ in range(a.n_seqs):
            n = rng.randint(5, 60)
            seq = [rng.choice(pool) for _ in range(n)]
            vis_rows = [[0] * 9 + [v] + [0] * 4 for v in seq]
            confs = decode(vis_rows, eps)["visibility_confidence"].tolist()
            states = follower_states(confs)
            lines.append(f"S {n} " + " ".join(map(str, seq)) + " " + " ".join(map(str, states)))
    Path(a.out).write_text("\n".join(lines) + "\n")
    print(f"wrote {len(lines)} records to {a.out}")


if __name__ == "__main__":
    main()
