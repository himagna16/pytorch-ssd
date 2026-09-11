#!/usr/bin/env python3
"""Score the team's follow model on a folder of LABELLED AI-deck frames.

Frames are named by cpx_grab.py (tools/crazysim_macos/), e.g.
    d2.5_b-15_vis1_subj-p01_light-room_take1_f00012_t1757530000.123.png
    vis0_subj-empty_light-dim_take1_f00007_t1757530100.456.jpg
    d = metres to the target, b = bearing in degrees (NEGATIVE = drone's LEFT),
    vis = 1 target in view / 0 nobody in view. Frames with the same labels
    (everything except f and t) in the same folder form one clip, ordered by
    frame number f. cpx_grab.py restarts f at 1 on every run, so if two
    recordings share labels and folder (re-recorded without --take N+1), the
    frames are split into separate runs by time wherever f starts over.

Preprocessing is identical to follow_person.py: grayscale, center square
crop, resize to 128x128 (bilinear), divide by 255, float PyTorch on CPU.

What it reports (per clip, then grouped by distance, bearing, light, subject):
  vis acc     fraction of frames where (confidence >= 0.5) matches the label
  track%      fraction of frames the follower would be TRACKING (3 frames >= 0.7
              to start, drops below 0.45; same rule as follow_person.py)
  starts      how many times the follower would confirm a new track (on
              vis0 clips every start is a FALSE track: it should be 0)
  bin acc     argmax x-bin == the bin the labelled bearing should land in
              (pinhole: x = tan(bearing)/tan(crop_hfov/2); 9 equal bins over [-1,1])
  +-1 acc     argmax x-bin within one bin of that
  bear err    mean (model bearing from the soft x) - (labelled bearing), degrees
  size        most common size bucket (0..3) vs the bucket expected from the
              distance for a --person-height tall person with the camera at --cam-height
Plus the MIRROR CHECK: every frame with a person clearly on the LEFT
(bearing <= -8 deg) should give argmax x-bin < 4, and on the RIGHT > 4.
Verdicts: PASS, MIRRORED (every side with data is <= 10% correct; also when
only one side was recorded), FAIL (inconsistent), NO DATA (nobody detected).
Anything other than PASS means stop.

Usage:
  trainenv/bin/python pytorch_ssd/tools/real_frames/score_real_frames.py <frames_dir>
      [--ckpt path.pth] [--crop-hfov 70 | --full-hfov DEG] [--csv out.csv] [--json out.json]
"""
import argparse, collections, csv, json, math, re, sys
from pathlib import Path
import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
DRONE_ROOT = HERE.parents[2]
EXTS = {".png", ".jpg", ".jpeg", ".pgm", ".bmp"}
TOKENS = [
    ("dist", re.compile(r"^d(-?\d+(?:\.\d+)?)$"), float),
    ("bearing", re.compile(r"^b(-?\d+(?:\.\d+)?)$"), float),
    ("vis", re.compile(r"^vis([01])$"), int),
    ("subject", re.compile(r"^subj-([A-Za-z0-9-]+)$"), str),
    ("light", re.compile(r"^light-([A-Za-z0-9-]+)$"), str),
    ("take", re.compile(r"^take(\d+)$"), int),
    ("frame", re.compile(r"^f(\d+)$"), int),
    ("time", re.compile(r"^t(\d+(?:\.\d+)?)$"), float),
]
CLIP_KEYS = ("subject", "light", "dist", "bearing", "vis", "take")
# clip key = CLIP_KEYS values + (folder relative to <frames>, run number)


def split_runs(frames):
    """Split one label group into separate recordings: sort by capture time and
    start a new run wherever the frame number fails to increase."""
    frames = sorted(frames, key=lambda r: (r["time"] if r["time"] is not None else -1.0,
                                           r["frame"] if r["frame"] is not None else -1, r["file"]))
    runs, prev = [], None
    for r in frames:
        f = r["frame"]
        if not runs or (f is not None and prev is not None and f <= prev):
            runs.append([])
        runs[-1].append(r)
        prev = f if f is not None else prev
    return runs


def parse_name(path: Path):
    """Labels from a cpx_grab.py filename, or None if it carries no vis label."""
    lab = {k: None for k, _, _ in TOKENS}
    stem = path.name[: -len(path.suffix)]
    for tok in stem.split("_"):
        for key, rx, cast in TOKENS:
            mt = rx.match(tok)
            if mt and lab[key] is None:
                lab[key] = cast(mt.group(1))
                break
    return lab if lab["vis"] is not None else None


def expected_x(bearing_deg, crop_hfov_deg):
    return math.tan(math.radians(bearing_deg)) / math.tan(math.radians(crop_hfov_deg) / 2)


def bucketize(v, inner_edges):
    """torch.bucketize(v, inner_edges, right=False): number of edges strictly below v."""
    return sum(1 for e in inner_edges if e < v)


XBIN9_INNER = [-1.0 + 2.0 * i / 9 for i in range(1, 9)]   # utils/follow_task.py XBIN9_EDGES[1:-1]
SIZE4_INNER = [0.25, 0.5, 0.75]                          # SIZE_BUCKET4_EDGES[1:-1]


def x_to_bin(x):
    """Training-label bin for x in [-1, 1] (9 equal bins); None if outside the crop."""
    return bucketize(x, XBIN9_INNER) if abs(x) <= 1 else None


def x_to_bearing(x, crop_hfov_deg):
    return math.degrees(math.atan(x * math.tan(math.radians(crop_hfov_deg) / 2)))


def expected_size(dist, person_h, cam_h, crop_vfov_deg):
    """Box height / crop height for a standing person (pinhole, feet on the floor)."""
    t = math.tan(math.radians(crop_vfov_deg) / 2)
    top = min(1.0, (person_h - cam_h) / dist / t)
    bot = min(1.0, cam_h / dist / t)
    return max(0.0, min(1.0, (top + bot) / 2))


def size_to_bucket(s):
    return bucketize(s, SIZE4_INNER)


class Model:
    def __init__(self, unstable_root: Path, ckpt: Path):
        sys.path.insert(0, str(unstable_root))
        import torch
        from models.follow_model_factory import build_follow_model_from_checkpoint
        from utils.follow_task import decode_follow_outputs
        self.torch, self.decode = torch, decode_follow_outputs
        self.head = torch.load(ckpt, map_location="cpu").get("follow_head_type")
        self.model = build_follow_model_from_checkpoint(ckpt, torch.device("cpu")).eval()
        self.centers = torch.tensor([-1.0 + (2 * i + 1) / 9.0 for i in range(9)])

    @staticmethod
    def preprocess(gray: np.ndarray) -> np.ndarray:
        s = min(gray.shape)
        y0, x0 = (gray.shape[0] - s) // 2, (gray.shape[1] - s) // 2
        crop = Image.fromarray(gray[y0:y0 + s, x0:x0 + s]).resize((128, 128), Image.BILINEAR)
        return np.asarray(crop, np.float32) / 255.0

    def __call__(self, batch: np.ndarray) -> list:
        torch = self.torch
        with torch.no_grad():
            out = self.model(torch.from_numpy(batch)[:, None])
            dec = self.decode(out, self.head)
        n = batch.shape[0]
        res = [{} for _ in range(n)]
        for k, v in dec.items():
            if torch.is_tensor(v) and v.shape[0] == n and v.dim() == 1:
                for i in range(n):
                    res[i][k] = float(v[i])
        xl = dec.get("x_logits")
        for i in range(n):
            if torch.is_tensor(xl):
                prob = torch.softmax(xl[i, :9].float(), 0)
                res[i]["x_soft"] = float((prob * self.centers).sum())
            else:
                res[i]["x_soft"] = res[i]["x_value"]
        return res


def follower_track(confs, enter, exit_, confirm):
    """Replays follow_person.py's confirmation rule over one clip. Returns (starts, tracking flags)."""
    tracking, streak, starts, flags = False, 0, 0, []
    for c in confs:
        streak = streak + 1 if c >= enter else 0
        if tracking and c < exit_:
            tracking = False
        elif not tracking and streak >= confirm:
            tracking, starts = True, starts + 1
        flags.append(tracking)
    return starts, flags


def fmt(v, spec="{:.2f}", na="-"):
    return na if v is None or (isinstance(v, float) and math.isnan(v)) else spec.format(v)


def summarize(rows):
    """Aggregate a list of per-frame rows (all from vis1 or vis0 or mixed)."""
    n = len(rows)
    out = {"n": n, "vis_acc": np.mean([r["vis_ok"] for r in rows]) if n else None,
           "mean_conf": np.mean([r["conf"] for r in rows]) if n else None,
           "track_frac": np.mean([r["tracking"] for r in rows]) if n else None}
    b = [r for r in rows if r["vis"] == 1 and r["exp_bin"] is not None]
    out["bin_n"] = len(b)
    out["bin_acc"] = np.mean([r["x_bin"] == r["exp_bin"] for r in b]) if b else None
    out["bin_acc1"] = np.mean([abs(r["x_bin"] - r["exp_bin"]) <= 1 for r in b]) if b else None
    out["bear_err"] = np.mean([r["bear_err"] for r in b]) if b else None
    out["bear_abs_err"] = np.mean([abs(r["bear_err"]) for r in b]) if b else None
    s = [r for r in rows if r["vis"] == 1 and r["exp_size_bucket"] is not None]
    out["size_acc"] = np.mean([r["size_bucket"] == r["exp_size_bucket"] for r in s]) if s else None
    out["size_acc1"] = np.mean([abs(r["size_bucket"] - r["exp_size_bucket"]) <= 1 for r in s]) if s else None
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("frames", type=Path, help="folder of labelled frames (searched recursively)")
    ap.add_argument("--unstable-root", type=Path, default=DRONE_ROOT / "pytorch_ssd_unstable")
    ap.add_argument("--ckpt", type=Path,
                    default=DRONE_ROOT / "pytorch_ssd_unstable/artifacts/successor_qat_ep3_eval.pth")
    fov = ap.add_mutually_exclusive_group()
    fov.add_argument("--crop-hfov", type=float, default=None,
                     help="horizontal field of view of the model's square crop, degrees (default 70)")
    fov.add_argument("--full-hfov", type=float, default=None,
                     help="measured horizontal FOV of the FULL image; the crop FOV is derived from it")
    ap.add_argument("--person-height", type=float, default=1.7, help="metres, for the expected size bucket")
    ap.add_argument("--cam-height", type=float, default=0.8, help="camera height above the floor, metres")
    ap.add_argument("--vis-threshold", type=float, default=0.5, help="confidence counted as 'person seen'")
    ap.add_argument("--vis-enter", type=float, default=0.7)
    ap.add_argument("--vis-exit", type=float, default=0.45)
    ap.add_argument("--confirm-frames", type=int, default=3)
    ap.add_argument("--mirror-min-bearing", type=float, default=8.0,
                    help="only frames at least this many degrees off-center count in the mirror check")
    ap.add_argument("--batch", type=int, default=64)
    ap.add_argument("--csv", type=Path, default=None, help="per-frame results (default <frames>/scores.csv)")
    ap.add_argument("--json", type=Path, default=None, help="summary JSON (default <frames>/scores.json)")
    a = ap.parse_args()

    files = sorted(p for p in a.frames.rglob("*") if p.suffix.lower() in EXTS)
    labelled = [(p, parse_name(p)) for p in files]
    skipped = [p for p, l in labelled if l is None]
    labelled = [(p, l) for p, l in labelled if l is not None]
    if not labelled:
        sys.exit(f"no labelled frames (names need a vis0/vis1 token) under {a.frames}")
    if skipped:
        print(f"note: {len(skipped)} image(s) without labels ignored, e.g. {skipped[0].name}")

    # The model sees a square crop of the full-width frame. With a pinhole
    # lens the crop's horizontal FOV follows from the full FOV and the aspect.
    if a.full_hfov is not None:
        w, h = Image.open(labelled[0][0]).size
        crop_hfov = math.degrees(2 * math.atan(math.tan(math.radians(a.full_hfov) / 2) * min(w, h) / w))
    else:
        crop_hfov = a.crop_hfov if a.crop_hfov is not None else 70.0

    model = Model(a.unstable_root, a.ckpt)
    rows = []
    for i in range(0, len(labelled), a.batch):
        chunk = labelled[i:i + a.batch]
        batch = np.stack([model.preprocess(np.asarray(Image.open(p).convert("L"))) for p, _ in chunk])
        for (p, lab), pred in zip(chunk, model(batch)):
            rows.append({"file": str(p.relative_to(a.frames)), "dir": str(p.parent.relative_to(a.frames)),
                         **lab, "pred": pred})

    groups_by_label = collections.defaultdict(list)
    for r in rows:
        groups_by_label[tuple(r[k] for k in CLIP_KEYS) + (r["dir"],)].append(r)
    clips = {}
    for gkey, grp in groups_by_label.items():
        runs = split_runs(grp)
        if len(runs) > 1:
            print(f"note: {len(runs)} separate recordings share the labels {gkey[:-1]} in folder "
                  f"'{gkey[-1]}' (frame numbers restart); scored as runs 1..{len(runs)}. "
                  f"Use --take N+1 when re-recording.")
        for i, run in enumerate(runs, 1):
            for r in run:
                r["run"] = i
            clips[gkey + (i,)] = run
    for key, cr in clips.items():
        cr.sort(key=lambda r: (r["frame"] if r["frame"] is not None else -1, r["time"] or 0.0, r["file"]))
        starts, flags = follower_track([r["pred"]["visibility_confidence"] for r in cr],
                                       a.vis_enter, a.vis_exit, a.confirm_frames)
        for r, f in zip(cr, flags):
            p = r["pred"]
            r["conf"] = p["visibility_confidence"]
            r["seen"] = int(r["conf"] >= a.vis_threshold)
            r["vis_ok"] = int(r["seen"] == r["vis"])
            r["tracking"] = int(f)
            r["x_bin"] = int(p.get("x_bin_index", -1))
            r["x_soft"] = p["x_soft"]
            r["size_bucket"] = int(p.get("size_bucket_index", -1))
            r["size_value"] = p.get("size_value")
            has_b = r["vis"] == 1 and r["bearing"] is not None
            ex = expected_x(r["bearing"], crop_hfov) if has_b else None
            r["exp_x"] = ex
            r["exp_bin"] = x_to_bin(ex) if ex is not None else None
            r["bear_model"] = x_to_bearing(r["x_soft"], crop_hfov)
            r["bear_err"] = r["bear_model"] - r["bearing"] if r["exp_bin"] is not None else None
            es = (expected_size(r["dist"], a.person_height, a.cam_height, crop_hfov)
                  if r["vis"] == 1 and r["dist"] else None)
            r["exp_size"] = es
            r["exp_size_bucket"] = size_to_bucket(es) if es is not None else None
        cr[0]["_starts"] = starts

    # ---- per-clip table
    print(f"\nmodel {a.ckpt.name} | {len(rows)} frames in {len(clips)} clips | crop HFOV {crop_hfov:.1f} deg | "
          f"expected size assumes a {a.person_height:g} m person, camera at {a.cam_height:g} m")
    hdr = (f"{'clip (subject/light/take)':32s} {'d':>4s} {'b':>5s} {'vis':>3s} {'n':>4s} {'conf':>5s} "
           f"{'visacc':>6s} {'track%':>6s} {'starts':>6s} {'expbin':>6s} {'bins seen':18s} {'binacc':>6s} "
           f"{'+-1':>5s} {'bearErr':>7s} {'size':>9s}")
    print(hdr)
    print("-" * len(hdr))
    clip_summ = []
    def sort_key(k):
        return (k[4], k[0] or "", k[1] or "", k[2] or 0, k[3] or 0, k[5] or 0, k[6], k[7])
    many_dirs = len({k[6] for k in clips}) > 1
    for key in sorted(clips, key=sort_key):
        cr = clips[key]
        subj, light, dist, bear, vis, take, cdir, run = key
        s = summarize(cr)
        bins = collections.Counter(r["x_bin"] for r in cr)
        sizes = collections.Counter(r["size_bucket"] for r in cr)
        size_mode = sizes.most_common(1)[0][0]
        exp_b = cr[0]["exp_bin"] if vis == 1 else None
        exp_s = cr[0]["exp_size_bucket"]
        name = f"{subj or '?'}/{light or '?'}/take{take or 1}"
        if run > 1 or len([k for k in clips if k[:7] == key[:7]]) > 1:
            name += f"/run{run}"
        if many_dirs:
            name = f"{cdir}:{name}"
        bins_str = " ".join(f"{b}:{c}" for b, c in sorted(bins.items()))
        print(f"{name[:32]:32s} {fmt(dist, '{:g}'):>4s} {fmt(bear, '{:g}'):>5s} {vis:>3d} {len(cr):>4d} "
              f"{s['mean_conf']:5.2f} {s['vis_acc']:6.0%} {s['track_frac']:6.0%} {cr[0]['_starts']:>6d} "
              f"{fmt(exp_b, '{}'):>6s} {bins_str[:18]:18s} {fmt(s['bin_acc'], '{:.0%}'):>6s} "
              f"{fmt(s['bin_acc1'], '{:.0%}'):>5s} {fmt(s['bear_err'], '{:+.1f}'):>7s} "
              f"{size_mode:>4d}/{fmt(exp_s, '{}'):<4s}")
        if vis == 1 and bear is not None and exp_b is None:
            print(f"{'':32s}   ^ bearing {bear:g} deg is outside the model's {crop_hfov:.0f} deg crop: no x-bin target")
        clip_summ.append({"subject": subj, "light": light, "dist": dist, "bearing": bear, "vis": vis,
                          "take": take, "dir": cdir, "run": run, "starts": cr[0]["_starts"], "expected_bin": exp_b,
                          "expected_size_bucket": exp_s, "size_bucket_mode": size_mode,
                          "bins": dict(sorted(bins.items())), **{k: (None if v is None else float(v))
                                                                   for k, v in s.items()}})

    # ---- grouped summaries (person clips only for bin/size; all clips for vis)
    groups = {}
    for field in ("dist", "bearing", "light", "subject"):
        print(f"\nby {field}:")
        g = collections.defaultdict(list)
        for r in rows:
            if field in ("dist", "bearing") and r["vis"] != 1:
                continue
            g[r[field]].append(r)
        groups[field] = {}
        for val in sorted(g, key=lambda v: (v is None, v)):
            s = summarize(g[val])
            groups[field][str(val)] = {k: (None if v is None else float(v)) for k, v in s.items()}
            print(f"  {str(val):>14s}: n={s['n']:4d}  vis acc {fmt(s['vis_acc'], '{:.0%}'):>5s}  "
                  f"track {fmt(s['track_frac'], '{:.0%}'):>5s}  bin acc {fmt(s['bin_acc'], '{:.0%}'):>5s} "
                  f"(+-1 {fmt(s['bin_acc1'], '{:.0%}'):>5s})  bearing err {fmt(s['bear_err'], '{:+.1f}'):>5s} "
                  f"(|err| {fmt(s['bear_abs_err'], '{:.1f}')})  size acc {fmt(s['size_acc'], '{:.0%}'):>5s} "
                  f"(+-1 {fmt(s['size_acc1'], '{:.0%}')})")

    # ---- empty scenes: false tracks
    empty = [c for c in clip_summ if c["vis"] == 0]
    false_starts = sum(c["starts"] for c in empty)
    empty_frames = [r for r in rows if r["vis"] == 0]
    print(f"\nEMPTY / NO-PERSON clips: {len(empty)} clips, {len(empty_frames)} frames, "
          f"confirmed (false) tracks = {false_starts}"
          + (f", frames with conf >= {a.vis_threshold}: {sum(r['seen'] for r in empty_frames)}, "
             f"max conf {max(r['conf'] for r in empty_frames):.2f}" if empty_frames else "")
          + ("  -> OK" if empty and false_starts == 0 else "  -> FALSE TRACKS: the drone would move" if empty else ""))

    # ---- mirror check
    m = a.mirror_min_bearing
    left = [r for r in rows if r["vis"] == 1 and r["bearing"] is not None and r["bearing"] <= -m and r["seen"]]
    right = [r for r in rows if r["vis"] == 1 and r["bearing"] is not None and r["bearing"] >= m and r["seen"]]
    mirror = {"left_n": len(left), "right_n": len(right),
              "left_ok": float(np.mean([r["x_bin"] < 4 for r in left])) if left else None,
              "right_ok": float(np.mean([r["x_bin"] > 4 for r in right])) if right else None}
    if left or right:
        present = [v for v in (mirror["left_ok"], mirror["right_ok"]) if v is not None]
        ok = all(v >= 0.9 for v in present)
        flipped = all(v <= 0.1 for v in present)  # one side alone counts: a flip is the likely cause
        one_side = "" if len(present) == 2 else f" (only {'LEFT' if left else 'RIGHT'} data; record the other side too)"
        if ok:
            verdict, mirror["verdict"] = "PASS" + one_side, "PASS"
        elif flipped:
            verdict = "MIRRORED: image looks flipped (left and right swapped)" + one_side
            mirror["verdict"] = "MIRRORED"
        else:
            verdict = "FAIL: left/right bins inconsistent; check labels and FOV"
            mirror["verdict"] = "FAIL"
        mirror["one_side_only"] = len(present) == 1
        print(f"MIRROR CHECK (person seen, |bearing| >= {m:g} deg): LEFT frames with bin < 4: "
              f"{fmt(mirror['left_ok'], '{:.0%}')} of {len(left)}; RIGHT frames with bin > 4: "
              f"{fmt(mirror['right_ok'], '{:.0%}')} of {len(right)}  -> {verdict}")
    else:
        mirror["verdict"] = "NO DATA"
        print(f"MIRROR CHECK: no detected person frames with |bearing| >= {m:g} deg  -> NO DATA "
              f"(the model saw nobody, or no clip is off-center): stop and report")

    csv_path = a.csv or a.frames / "scores.csv"
    cols = ["file", "subject", "light", "take", "run", "dist", "bearing", "vis", "frame", "conf", "seen", "tracking",
            "x_bin", "exp_bin", "x_soft", "exp_x", "bear_model", "bear_err", "size_bucket", "exp_size_bucket",
            "size_value", "exp_size"]
    with open(csv_path, "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        wr.writeheader()
        for r in rows:
            wr.writerow({k: (f"{r[k]:.4f}" if isinstance(r[k], float) else r[k]) for k in cols})
    json_path = a.json or a.frames / "scores.json"
    json_path.write_text(json.dumps({
        "ckpt": str(a.ckpt), "frames_dir": str(a.frames), "n_frames": len(rows), "crop_hfov_deg": crop_hfov,
        "vis_threshold": a.vis_threshold, "follower": {"enter": a.vis_enter, "exit": a.vis_exit,
                                                       "confirm_frames": a.confirm_frames},
        "overall": {k: (None if v is None else float(v)) for k, v in summarize(rows).items()},
        "empty_false_tracks": false_starts, "mirror_check": mirror, "groups": groups, "clips": clip_summ,
    }, indent=2))
    print(f"\nper-frame CSV: {csv_path}\nsummary JSON:  {json_path}")


if __name__ == "__main__":
    main()
