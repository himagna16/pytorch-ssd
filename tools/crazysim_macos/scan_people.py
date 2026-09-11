#!/usr/bin/env python3
"""Pick the COCO person the team model detects most reliably in the simulator.

Scores every full-body, single-person COCO val2017 image (person at least 75%
of image height, height/width >= 2.2, not cut off by the frame) from the
drone's-eye view at several distances, using the same wall-color compositing
as build_person_scene.py. Prints the best candidates by worst-case confidence.
Sep 10 result: img 19432 / ann 428692, confidence 1.00 at every distance.

Run with the trainenv python (pycocotools, torch, mujoco).
"""
import argparse, sys
from pathlib import Path
import numpy as np
import torch, mujoco
from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build_person_scene as b  # noqa: E402


class SceneArgs:
    person_height, sway_amp, sway_period, person_x, person_y = 1.7, 0.0, 16.0, 2.5, 0.0
    alpha, panel_euler = 1.0, "0 0 0"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--coco-root", type=Path, default=b.DRONE_ROOT / "pytorch_ssd/data/coco")
    ap.add_argument("--unstable-root", type=Path, default=b.DRONE_ROOT / "pytorch_ssd_unstable")
    ap.add_argument("--ckpt", type=Path,
                    default=b.DRONE_ROOT / "pytorch_ssd_unstable/artifacts/successor_qat_ep3_eval.pth")
    ap.add_argument("--out", type=Path, default=HERE / "scan_out")
    ap.add_argument("--distances", type=float, nargs="+", default=[1.5, 2.0, 2.5, 3.0, 3.5])
    ap.add_argument("--top", type=int, default=8)
    a = ap.parse_args()

    sys.path.insert(0, str(a.unstable_root))
    from models.follow_model_factory import build_follow_model_from_checkpoint
    from utils.follow_task import decode_follow_outputs
    from pycocotools.coco import COCO
    head = torch.load(a.ckpt, map_location="cpu").get("follow_head_type")
    model = build_follow_model_from_checkpoint(a.ckpt, torch.device("cpu")).eval()

    c = COCO(str(a.coco_root / "annotations/instances_val2017.json"))
    cands = []
    for img_id in c.getImgIds(catIds=[1]):
        anns = c.loadAnns(c.getAnnIds(imgIds=img_id, iscrowd=False))
        people = [x for x in anns if x["category_id"] == 1]
        if len(people) != 1:
            continue
        ann, im = people[0], c.loadImgs(img_id)[0]
        x, y, w, h = ann["bbox"]
        if h < 0.75 * im["height"] or h / max(w, 1) < 2.2:
            continue
        if x < 5 or y < 5 or x + w > im["width"] - 5 or y + h > im["height"] - 5:
            continue
        cands.append((img_id, ann["id"]))
    print(f"{len(cands)} full-body single-person candidates")

    a.out.mkdir(parents=True, exist_ok=True)
    res = []
    for img_id, ann_id in cands:
        d = a.out / str(img_id)
        d.mkdir(exist_ok=True)
        aspect = b.make_cutout(a.coco_root, img_id, ann_id, d / "person.png", "")
        scene = b.write_scene(d, aspect, SceneArgs())
        spec = mujoco.MjSpec.from_file(str(scene))
        cam = spec.worldbody.add_camera()
        cam.name, cam.fovy, cam.pos = "pc", 70.0, [0, 0, 0.8]
        cam.alt.type = mujoco.mjtOrientation.mjORIENTATION_XYAXES
        cam.alt.xyaxes = [0, -1, 0, 0, 0, 1]
        m = spec.compile()
        dd = mujoco.MjData(m)
        r = mujoco.Renderer(m, 244, 324)
        cid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_CAMERA, "pc")
        confs, sizes = [], []
        for dist in a.distances:
            m.cam_pos[cid] = [SceneArgs.person_x - dist, 0, 0.8]
            mujoco.mj_forward(m, dd)
            r.update_scene(dd, camera="pc")
            gray = np.dot(r.render()[..., :3], [0.2989, 0.5870, 0.1140]).astype(np.uint8)
            s = min(gray.shape)
            y0, x0 = (gray.shape[0] - s) // 2, (gray.shape[1] - s) // 2
            crop = Image.fromarray(gray[y0:y0 + s, x0:x0 + s]).resize((128, 128), Image.BILINEAR)
            with torch.no_grad():
                dec = decode_follow_outputs(
                    model(torch.from_numpy(np.asarray(crop, np.float32) / 255.0)[None, None]), head)
            confs.append(float(dec["visibility_confidence"].reshape(-1)[0]))
            sizes.append(int(dec["size_bucket_index"].reshape(-1)[0]))
        r.close()
        mono = all(sizes[i] >= sizes[i + 1] for i in range(len(sizes) - 1))
        res.append((min(confs), float(np.mean(confs)), img_id, ann_id, confs, sizes, mono))
    res.sort(key=lambda t: (-t[0], -t[1]))
    for t in res[: a.top]:
        print(f"  min conf {t[0]:.2f} mean {t[1]:.2f} | img {t[2]} ann {t[3]} | "
              f"confs {[round(v, 2) for v in t[4]]} | size buckets {t[5]} monotonic={t[6]}")


if __name__ == "__main__":
    main()
