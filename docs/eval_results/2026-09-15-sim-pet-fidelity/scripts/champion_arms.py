#!/usr/bin/env python3
"""The champion, in the three forms this project runs it in, behind ONE call.

Both sides of this comparison - rendered frames and real photographs - are
scored by importing this module, so a difference between them can never be a
difference in preprocessing or in which network was loaded.

Arms (all are the champion, "QAT ep3"):
  float   artifacts/successor_qat_ep3_eval.pth, plain float PyTorch. This is
          what follow_person.py --backend float and build_scene.py --preview
          run, i.e. the network behind every `__proven` cell and every scene
          note probe.
  fq      artifacts/successor_qat_ep3.pth transformed by nemo.quantize_pact to
          8 bits with its LEARNED alphas - the fake-quant "deployed form".
          This is the network the published confuser-slice figure
          (0.239 @0.45 / 0.171 @0.55, n=771) was measured on; reproduced
          exactly by export/confuser_slice_eval.py in this session.
  chip    logs/plain_follow_prod_qat_v3/quant_eval/model_id_dory.onnx under
          onnxruntime in doryenv, reached through
          tools/crazysim_macos/perception_backends.ChipPerception - the integer
          network the `__ships` cells fly, including F.pets__ships.

Input convention: ONE uint8 grayscale array, whatever its size - the sensor
image. Every arm then does its own documented preprocessing:
  float/fq  centre square crop -> 128x128 PIL BILINEAR -> /255
            (utils/transforms.CenterCropSquare + ResizeImage, and
             build_scene.run_model, which are the same two operations)
  chip      perception_backends.firmware_preprocess: centre square crop, then
            each output pixel the rounded mean of a 2x2 camera block
  *_via244  the same, after first resampling the centre crop to 244x244. A
            rendered frame is 324x244, so its crop is resampled 244 -> 128; a
            COCO photo's crop is typically 480-640 px. This arm puts a photo
            through the frame's own resampling chain, so that a resolution
            difference cannot be mistaken for a sim/real difference.
"""
from pathlib import Path
import sys
from copy import deepcopy

import numpy as np
import torch
from PIL import Image

DRONE = Path("/Users/saimaruvada/Downloads/drone")
ROOT = DRONE / "pytorch_ssd"
UNSTABLE = DRONE / "pytorch_ssd_unstable"
SIMDIR = ROOT / "tools/crazysim_macos"
CKPT_FLOAT = UNSTABLE / "artifacts/successor_qat_ep3_eval.pth"
CKPT_QAT = UNSTABLE / "artifacts/successor_qat_ep3.pth"

for p in (str(UNSTABLE), str(ROOT / "export"), str(SIMDIR)):
    if p not in sys.path:
        sys.path.insert(0, p)


def to_input(gray: np.ndarray, via: int | None = None) -> torch.Tensor:
    """Centre square crop -> 128x128 bilinear -> [0,1] tensor, from a uint8 2-D array."""
    img = Image.fromarray(np.ascontiguousarray(gray), "L")
    w, h = img.size
    s = min(w, h)
    left, top = (w - s) // 2, (h - s) // 2
    img = img.crop((left, top, left + s, top + s))
    if via is not None:
        img = img.resize((via, via), Image.BILINEAR)
    img = img.resize((128, 128), Image.BILINEAR)
    return torch.from_numpy(np.asarray(img, np.float32) / 255.0)[None, None]


def _crop244(gray: np.ndarray) -> np.ndarray:
    img = Image.fromarray(np.ascontiguousarray(gray), "L")
    w, h = img.size
    s = min(w, h)
    left, top = (w - s) // 2, (h - s) // 2
    return np.asarray(img.crop((left, top, left + s, top + s)).resize((244, 244), Image.BILINEAR),
                      np.uint8)


class Arms:
    def __init__(self, want=("float", "fq", "chip")):
        from models.follow_model_factory import build_follow_model, follow_model_kwargs_from_metadata
        from utils.follow_task import decode_follow_outputs
        self._decode = decode_follow_outputs
        self.want = tuple(want)
        self.info = {}

        pf = torch.load(CKPT_FLOAT, map_location="cpu")
        self.head = pf["follow_head_type"]
        self.fm = build_follow_model(**follow_model_kwargs_from_metadata(pf)).eval()
        self.fm.load_state_dict(pf["state_dict"])
        self.info["float"] = {"ckpt": str(CKPT_FLOAT), "head": self.head}

        self.qm = None
        if "fq" in self.want:
            import nemo
            from sweep_fq_ckpt import patch_model_to_graph_compat
            pq = torch.load(CKPT_QAT, map_location="cpu")
            assert pq["follow_head_type"] == self.head
            assert any("W_alpha" in k for k in pq["state_dict"]), "expected learned PACT alphas"
            m = build_follow_model(**follow_model_kwargs_from_metadata(pq)).eval()
            patch_model_to_graph_compat()
            mq = nemo.transform.quantize_pact(deepcopy(m), dummy_input=torch.randn(1, 1, 128, 128)).eval()
            mq.change_precision(bits=8, scale_weights=True, scale_activations=True)
            mq.load_state_dict(pq["state_dict"], strict=False)
            self.qm = mq
            self.info["fq"] = {"ckpt": str(CKPT_QAT), "how": "learned QAT alphas, 8 bit"}

        self.chip = None
        if "chip" in self.want:
            import perception_backends as pb
            self.chip = pb.ChipPerception()
            self.info["chip"] = dict(self.chip.info)

    def _t(self, model, x):
        with torch.no_grad():
            d = self._decode(model(x), self.head)
        return {"conf": float(d["visibility_confidence"].reshape(-1)[0]),
                "size_bucket": int(d["size_bucket_index"].reshape(-1)[0]),
                "x_value": float(d["x_value"].reshape(-1)[0])}

    def __call__(self, gray: np.ndarray) -> dict:
        out = {}
        x128 = to_input(gray)
        x244 = to_input(gray, via=244)
        r = self._t(self.fm, x128)
        out["float"] = r["conf"]; out["float_size_bucket"] = r["size_bucket"]
        out["float_via244"] = self._t(self.fm, x244)["conf"]
        if self.qm is not None:
            out["fq"] = self._t(self.qm, x128)["conf"]
            out["fq_via244"] = self._t(self.qm, x244)["conf"]
        if self.chip is not None:
            c = self.chip(gray)
            out["chip"] = float(c["visibility_confidence"])
            out["chip_size_bucket"] = int(c["size_bucket_index"])
            c2 = self.chip(_crop244(gray))
            out["chip_via244"] = float(c2["visibility_confidence"])
        return out

    def close(self):
        if self.chip is not None:
            self.chip.close()
