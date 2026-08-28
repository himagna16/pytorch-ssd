"""Build a train-sample manifest that skews negatives toward person-confusers.

Error analysis (Aug 28) showed the deployed champion's worst false positives
are animate-shaped non-persons: mannequins, dressed teddy bears, cats, dogs,
cows. COCO labels most of these. This tool writes a manifest (David's
`--train-sample-manifest` format) that keeps:

  - ALL images containing a person
  - ALL no-person images containing a confuser category
    (bird/cat/dog/horse/sheep/cow/elephant/bear/zebra/giraffe/teddy bear)
  - a KEEP_FRACTION subset of the remaining boring negatives

so the negative pool the visible-fraction balancer draws from is
confuser-rich, without touching any training code.

Usage (trainenv python, from inside pytorch_ssd):
  ../trainenv/bin/python export/build_confuser_manifest.py \
    --ann data/coco/annotations/instances_train2017.json \
    --out export/confuser_train_manifest.json
"""

import argparse
import json
import random
from collections import defaultdict
from pathlib import Path

PERSON = {1}
CONFUSERS = {16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 88}  # animals + teddy bear


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ann", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--keep-boring-fraction", type=float, default=0.3)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    coco = json.loads(Path(args.ann).read_text())
    cats_by_img = defaultdict(set)
    for a in coco["annotations"]:
        cats_by_img[a["image_id"]].add(a["category_id"])

    person_imgs, confuser_negs, boring_negs = [], [], []
    for img in coco["images"]:
        cats = cats_by_img.get(img["id"], set())
        if cats & PERSON:
            person_imgs.append(img["id"])
        elif cats & CONFUSERS:
            confuser_negs.append(img["id"])
        else:
            boring_negs.append(img["id"])

    rng = random.Random(args.seed)
    kept_boring = rng.sample(boring_negs, int(len(boring_negs) * args.keep_boring_fraction))

    selected = person_imgs + confuser_negs + kept_boring
    rng.shuffle(selected)
    payload = {
        "purpose": "confuser-skewed negatives (see EXPERIMENTS.md Aug 28)",
        "target_count": len(selected),
        "ordered_samples": [
            {"image_id": int(i), "selected_rank": r} for r, i in enumerate(selected)
        ],
    }
    Path(args.out).write_text(json.dumps(payload))
    n_neg = len(confuser_negs) + len(kept_boring)
    print(f"person imgs kept:    {len(person_imgs)}")
    print(f"confuser negatives:  {len(confuser_negs)}  ({100*len(confuser_negs)/max(n_neg,1):.0f}% of negative pool)")
    print(f"boring negatives:    {len(kept_boring)} of {len(boring_negs)} kept")
    print(f"total selected:      {len(selected)}  -> {args.out}")


if __name__ == "__main__":
    main()
