"""Dump the model state train.py actually starts a fine-tune from.

Runs train.py's own init path -- build_model, --init-ckpt load, then
enable_quant_aware_finetune -- writes the resulting model out as a checkpoint
in train.py's own save format, and exits before the first batch. Score the
result with the team's export/sweep_fq_ckpt.py --mode qat and
export/confuser_slice_eval.py to see exactly what step zero measures.

Nothing downstream of enable_quant_aware_finetune changes tensor values (the
freeze helpers only touch requires_grad), so the dump is the step-zero state.

Usage (nemoenv python, from inside pytorch_ssd_unstable):
  ../nemoenv/bin/python qat_init_probe.py --dump /tmp/init.pth -- \
      --model-type plain_follow --follow-head-type xbin9_size_bucket4 \
      --init-ckpt ... --quant-aware-finetune ...     # any train.py arguments
"""

from __future__ import annotations

import sys
from pathlib import Path

import train


def main() -> None:
    argv = sys.argv[1:]
    if "--dump" not in argv or "--" not in argv:
        raise SystemExit(__doc__)
    dump_path = Path(argv[argv.index("--dump") + 1]).expanduser().resolve()
    train_argv = argv[argv.index("--") + 1:]

    original = train.enable_quant_aware_finetune

    def probe(model, train_loader, device, args, **kwargs):
        wrapped = original(model, train_loader, device, args, **kwargs)
        dump_path.parent.mkdir(parents=True, exist_ok=True)
        train.save_checkpoint(dump_path, wrapped, args, 0)
        print(f"[init-probe] wrote step-zero checkpoint: {dump_path}", flush=True)
        raise SystemExit(0)

    train.enable_quant_aware_finetune = probe
    sys.argv = ["train.py"] + train_argv
    train.main()


if __name__ == "__main__":
    main()
