"""Two fake-quant forms of a checkpoint.

qat      learned QAT ranges, as training ended (export/sweep_fq_ckpt.py --mode qat).
release  ranges dropped and recalibrated on 32 rep_images, which is what the release
         pipeline does before the chip export. On the Sep 24 real frames the champion in
         this form tracks the chip arm at corr 0.989 (mean -0.051, same side of 0.75 on 87%),
         against corr 0.973 (mean -0.066, 70%) for the qat form.
"""
from confuser_slice_eval import fq_model
from models.follow_model_factory import build_follow_model, follow_model_kwargs_from_metadata

FORMS = ("qat", "release")


def load_fq(payload, form):
    if form == "release":
        keep = set(build_follow_model(**follow_model_kwargs_from_metadata(payload)).state_dict())
        payload = dict(payload, state_dict={k: v for k, v in payload["state_dict"].items() if k in keep})
    return fq_model(payload)
