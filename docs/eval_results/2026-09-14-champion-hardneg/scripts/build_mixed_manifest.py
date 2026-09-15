"""Build a HALF-SKEW confuser manifest for the champion hard-negative fine-tune.

The Aug 28 confuser manifest (export/confuser_train_manifest.json) keeps all
person images, all confuser negatives, and only 30% of the boring negatives,
leaving a negative pool that is 62% confusers. Eight epochs of that produced
the confuser model, which is 3x safer around pets and cannot follow a person.

The objective here is "champion, but safer around pets". So we keep the same
structure but dilute the skew: all person images (recall data untouched), all
confuser negatives, and enough boring negatives that the negative pool lands
near --target-confuser-share instead of 0.62.

Usage (trainenv python, from inside pytorch_ssd):
  ../trainenv/bin/python docs/eval_results/2026-09-14-champion-hardneg/scripts/build_mixed_manifest.py \
    --ann data/coco/annotations/instances_train2017.json \
    --out <path>.json --target-confuser-share 0.40 --seed 0
"""
import argparse, json, random
from collections import defaultdict
from pathlib import Path

PERSON = {1}
CONFUSERS = {16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 88}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ann", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--target-confuser-share", type=float, default=0.40)
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

    C, B = len(confuser_negs), len(boring_negs)
    s = float(args.target_confuser_share)
    # C / (C + f*B) = s  ->  f = C*(1-s)/(s*B)
    f = min(1.0, C * (1.0 - s) / (s * B))
    rng = random.Random(args.seed)
    kept_boring = rng.sample(boring_negs, int(B * f))

    selected = person_imgs + confuser_negs + kept_boring
    rng.shuffle(selected)
    n_neg = C + len(kept_boring)
    payload = {
        "purpose": ("half-skew confuser negatives for the champion hard-negative "
                    "fine-tune (2026-09-14); person images untouched"),
        "target_count": len(selected),
        "composition": {
            "person_images": len(person_imgs),
            "confuser_negatives": C,
            "boring_negatives_kept": len(kept_boring),
            "boring_negatives_total": B,
            "keep_boring_fraction": round(f, 4),
            "confuser_share_of_negative_pool": round(C / max(n_neg, 1), 4),
        },
        "ordered_samples": [{"image_id": int(i), "selected_rank": r} for r, i in enumerate(selected)],
    }
    Path(args.out).write_text(json.dumps(payload))
    print(f"natural confuser share of negative pool: {C/(C+B):.4f}  (C={C}, B={B})")
    print(f"person imgs kept:   {len(person_imgs)}")
    print(f"confuser negatives: {C}  ({100*C/max(n_neg,1):.1f}% of negative pool)")
    print(f"boring negatives:   {len(kept_boring)} of {B} kept (f={f:.4f})")
    print(f"total selected:     {len(selected)} -> {args.out}")


if __name__ == "__main__":
    main()
