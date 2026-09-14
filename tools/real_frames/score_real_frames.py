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
  track%      fraction of frames the follower would be TRACKING (3 frames >= 0.75
              to start, drops below 0.45; same rule and defaults as
              follow_person.py - the enter bar was 0.70 until 2026-09-13)
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

THE CONVENTION IT ASSUMES (printed under every verdict, because getting it
backwards is invisible to this tool): a NEGATIVE bearing label means the person
stood to the drone's LEFT, seen from BEHIND the drone looking the way it faces;
x-bins run 0 = left .. 8 = right. If whoever marked the floor had left and right
backwards AND the camera image is mirrored, the two mistakes cancel and this
check prints a clean PASS. No amount of data fixes that - only reading the marks
back against that sentence does.

Verdicts:
  PASS      every side with data is >= 90% on the correct side
  WEAK      every side is >= 60% but short of 90%: the sides are CONSISTENT, so
            this is a noisy model, not a mirror and not swapped labels
  MIRRORED  every side with data is <= 10% correct, and the model does move its
            bins around (left and right swapped)
  FAIL      the two sides disagree (one reads right, one reads wrong - which a
            mirror cannot do: suspect the marks or the FOV), or both sides are
            mostly wrong without being a clean flip
  NO DATA   the question could not be answered at all: nobody detected; or only
            one target position was recorded; or the model answers with the same
            x-bin whatever the label says (a dead/degenerate head is NOT a
            mirror, and must never be reported as one)
Anything other than PASS means stop. A PASS built on one side only, on fewer
than 10 detected frames, or on JPEG frames prints an extra warning line under
the verdict - read it before believing the PASS. Frames whose labelled bearing
falls outside the model's crop (or past +-90 deg, which the pinhole model cannot
express at all) are left out of the verdict - the person is not in the image the
model sees - and counted in a note under it.

Messy folders are survivable: unreadable/truncated images and macOS ._ sidecars
are skipped with a note, JPEG clips are scored but loudly flagged (the chip runs
on raw), and frames whose filename has no bearing are left out of bin accuracy
and the mirror check instead of being guessed at.

Rehearsed by tools/real_frames/test_score_real_frames.py - run that first.

Usage (absolute paths: this works from ANY directory, which the relative form
in the protocol does not):
  ~/Downloads/drone/trainenv/bin/python \
      ~/Downloads/drone/pytorch_ssd/tools/real_frames/score_real_frames.py <frames_dir> \
      [--ckpt path.pth] [--crop-hfov 70 | --full-hfov DEG] [--csv out.csv] [--json out.json]
"""
import argparse, collections, csv, json, math, re, sys
from pathlib import Path
import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
DRONE_ROOT = HERE.parents[2]
EXTS = {".png", ".jpg", ".jpeg", ".pgm", ".bmp"}
JPEG_EXTS = {".jpg", ".jpeg"}
MIRROR_THIN_N = 10        # fewer detected frames than this on a side: say so, do not trust it
BAYER_WARN_DN = 3.0       # 2x2 phase spread above this = a colour sensor read as gray
MIRROR_PASS_FRAC = 0.90   # every side at least this correct -> PASS
MIRROR_WEAK_FRAC = 0.60   # every side at least this correct -> WEAK (consistent, just noisy)
MIRROR_FLIP_FRAC = 0.10   # every side at most this correct -> MIRRORED
CENTRE_COLLAPSE_FRAC = 0.5   # this share of frames in the centre bin = not localising
MIRROR_CONTRAST_BINS = 2  # the labels must ask for x-bins at least this far apart before
                          # "the model always answers the same bin" means anything
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
    """Image x in [-1, 1] for a labelled bearing, or None if the label cannot mean one.

    tan() wraps at +-90 deg: a mislabelled b170 would otherwise come back as
    x = -0.25, i.e. a confident "the person is left of centre" for a frame whose
    label says the person is 170 deg to the RIGHT. Anything at or past +-90 deg is
    behind the camera plane and has no image position at all, so say so instead.
    """
    if not -90.0 < bearing_deg < 90.0:
        return None
    return math.tan(math.radians(bearing_deg)) / math.tan(math.radians(crop_hfov_deg) / 2)


def bucketize(v, inner_edges):
    """torch.bucketize(v, inner_edges, right=False): number of edges strictly below v."""
    return sum(1 for e in inner_edges if e < v)


XBIN9_INNER = [-1.0 + 2.0 * i / 9 for i in range(1, 9)]   # utils/follow_task.py XBIN9_EDGES[1:-1]
SIZE4_INNER = [0.25, 0.5, 0.75]                          # SIZE_BUCKET4_EDGES[1:-1]


def x_to_bin(x):
    """Training-label bin for x in [-1, 1] (9 equal bins); None if outside the crop.

    None in gives None out, so an unusable bearing stays unusable all the way
    through instead of turning into a bin number somewhere downstream.
    """
    if x is None:
        return None
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


def bayer_phase_spread(gray):
    """Mean brightness gap between the four pixel positions of each 2x2 cell, in DN.

    A mono sensor gives well under 1 (measured 0.2 on our sim frames). A colour
    (Bayer) sensor read as plain gray gives tens of DN, because the four
    positions are R, G, G and B (measured 20 on a near-gray scene, 41 on a
    colourful one). cpx_grab.py --bayer averages each cell and brings it to 0.
    """
    g = np.asarray(gray, np.float32)
    h, w = (g.shape[0] // 2) * 2, (g.shape[1] // 2) * 2
    if h < 2 or w < 2:
        return 0.0
    q = g[:h, :w].reshape(h // 2, 2, w // 2, 2)
    mu = [float(q[:, i, :, j].mean()) for i in (0, 1) for j in (0, 1)]
    return max(mu) - min(mu)


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
    # the follower's shipped rule (follow_person.py --vis-enter 0.75 since 2026-09-13)
    ap.add_argument("--vis-enter", type=float, default=0.75)
    ap.add_argument("--vis-exit", type=float, default=0.45)
    ap.add_argument("--confirm-frames", type=int, default=3)
    ap.add_argument("--mirror-min-bearing", type=float, default=8.0,
                    help="only frames at least this many degrees off-center count in the mirror check")
    ap.add_argument("--batch", type=int, default=64)
    ap.add_argument("--csv", type=Path, default=None, help="per-frame results (default <frames>/scores.csv)")
    ap.add_argument("--json", type=Path, default=None, help="summary JSON (default <frames>/scores.json)")
    a = ap.parse_args()

    if not a.frames.is_dir():
        sys.exit(f"frames folder does not exist: {a.frames}" if not a.frames.exists()
                 else f"not a folder: {a.frames}")
    if a.mirror_min_bearing <= 0:
        # At 0 a frame labelled b0 satisfies both "bearing <= -0" and "bearing >= 0",
        # so it is counted on BOTH sides and its centre bin 4 is scored wrong on both:
        # a straight-ahead clip would drag the verdict towards MIRRORED for nothing.
        sys.exit(f"--mirror-min-bearing must be greater than 0 (got {a.mirror_min_bearing:g}); "
                 f"frames at 0 deg are on neither side and cannot answer a left/right question")
    if not a.ckpt.exists():
        sys.exit(f"checkpoint not found: {a.ckpt}\n"
                 f"pass --ckpt <file>; the ones we have are in {a.unstable_root / 'artifacts'}")
    if not (a.unstable_root / "models/follow_model_factory.py").exists():
        sys.exit(f"--unstable-root does not hold the model code: {a.unstable_root}")
    all_imgs = sorted(p for p in a.frames.rglob("*") if p.suffix.lower() in EXTS)
    # macOS writes ._name sidecars next to real files on FAT/exFAT sticks and in
    # some zips. They look like images and are not. Ignore them, but say so.
    sidecars = [p for p in all_imgs if p.name.startswith("._")]
    files = [p for p in all_imgs if not p.name.startswith("._")]
    labelled = [(p, parse_name(p)) for p in files]
    skipped = [p for p, l in labelled if l is None]
    labelled = [(p, l) for p, l in labelled if l is not None]
    if not labelled:
        sys.exit(f"no labelled frames (names need a vis0/vis1 token) under {a.frames}")
    if skipped:
        print(f"note: {len(skipped)} image(s) without labels ignored, e.g. {skipped[0].name}")
    if sidecars:
        print(f"note: {len(sidecars)} macOS sidecar file(s) (._*) ignored, e.g. {sidecars[0].name}")
    jpegs = [p for p, _ in labelled if p.suffix.lower() in JPEG_EXTS]
    if jpegs:
        print(f"WARNING: {len(jpegs)} of {len(labelled)} labelled frames are JPEG "
              f"(e.g. {jpegs[0].name}).\n"
              f"         The chip runs the model on RAW frames; JPEG adds compression artefacts it\n"
              f"         never sees, so JPEG clips are NOT valid for scoring (capture protocol\n"
              f"         section 2). Set the streamer to raw (format 0), reflash, and re-record.")

    def load_gray(path):
        """Frame as a 2-D uint8 array, or None if the file is unreadable."""
        try:
            with Image.open(path) as im:
                return np.asarray(im.convert("L"))
        except Exception as exc:                      # truncated, empty, or not an image
            unreadable.append((path, exc))
            return None

    unreadable = []
    # The model sees a square crop of the full-width frame. With a pinhole
    # lens the crop's horizontal FOV follows from the full FOV and the aspect.
    if a.full_hfov is not None:
        size = None
        for p, _ in labelled:
            try:
                with Image.open(p) as im:
                    size = im.size
                break
            except Exception:
                continue
        if size is None:
            sys.exit(f"--full-hfov needs the frame size, but no image under {a.frames} could be read")
        w, h = size
        crop_hfov = math.degrees(2 * math.atan(math.tan(math.radians(a.full_hfov) / 2) * min(w, h) / w))
    else:
        crop_hfov = a.crop_hfov if a.crop_hfov is not None else 70.0

    try:
        model = Model(a.unstable_root, a.ckpt)
    except Exception as exc:                      # wrong artifact for this code path
        # artifacts/ holds both training and eval copies of the same run, e.g.
        # successor_qat_ep3.pth (quantization observers attached, will NOT load)
        # and successor_qat_ep3_eval.pth (will). Do not make the reader parse a
        # 60-key state_dict dump to work that out.
        txt = str(exc)
        msg = [f"could not load the checkpoint {a.ckpt.name}:",
               f"  {type(exc).__name__}: {txt.splitlines()[0][:160]}"]
        if "W_alpha" in txt or "Unexpected key" in txt:
            msg.append("  Those extra keys are quantization-aware-training observers: this is the")
            msg.append("  TRAINING copy, which the plain follow model cannot load.")
        alt = a.ckpt.with_name(a.ckpt.stem + "_eval" + a.ckpt.suffix)
        if alt.exists():
            msg.append(f"  Use the eval copy instead:  --ckpt {alt}")
        pool = sorted(q.name for q in (a.unstable_root / "artifacts").glob("*.pth"))
        if pool:
            msg.append(f"  Checkpoints in {a.unstable_root / 'artifacts'}: {', '.join(pool)}")
        sys.exit("\n".join(msg))
    rows, bayer = [], []
    every = max(1, len(labelled) // 24)      # a sample is enough for the Bayer check
    for i in range(0, len(labelled), a.batch):
        chunk, imgs = [], []
        for j, (p, lab) in enumerate(labelled[i:i + a.batch], i):
            gray = load_gray(p)
            if gray is None:
                continue
            if j % every == 0:
                bayer.append(bayer_phase_spread(gray))
            imgs.append(model.preprocess(gray))
            chunk.append((p, lab))
        if not imgs:
            continue
        for (p, lab), pred in zip(chunk, model(np.stack(imgs))):
            rows.append({"file": str(p.relative_to(a.frames)), "dir": str(p.parent.relative_to(a.frames)),
                         **lab, "pred": pred})
    if unreadable:
        print(f"note: {len(unreadable)} image(s) unreadable and skipped, e.g. "
              f"{unreadable[0][0].name} ({type(unreadable[0][1]).__name__})")
    if not rows:
        sys.exit(f"every labelled image under {a.frames} was unreadable ({len(unreadable)} files)")
    bayer_dn = float(np.median(bayer)) if bayer else 0.0
    if bayer_dn > BAYER_WARN_DN:
        print(f"WARNING: these frames look like a COLOUR (Bayer) camera read as plain gray: the four\n"
              f"         pixel positions of each 2x2 cell differ by {bayer_dn:.0f} DN (a mono sensor\n"
              f"         gives under 1). The model never sees that pattern, so the scores below are\n"
              f"         not meaningful. Re-record with cpx_grab.py --bayer (protocol section 3.1).")

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
            r["x_soft"] = p["x_soft"]
            # Heads without a bin classifier (legacy / lcr3_residual) report a
            # position, not a bin: bucket it the same way the training labels are.
            xb = p.get("x_bin_index")
            r["x_bin"] = int(xb) if xb is not None else max(0, min(8, bucketize(r["x_soft"], XBIN9_INNER)))
            r["size_value"] = p.get("size_value")
            sb = p.get("size_bucket_index")
            r["size_bucket"] = (int(sb) if sb is not None else
                                size_to_bucket(r["size_value"]) if r["size_value"] is not None else -1)
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
        elif vis == 1 and bear is None:
            print(f"{'':32s}   ^ no bearing label in these filenames: not counted in bin accuracy "
                  f"or the MIRROR CHECK")
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
          + ("  -> OK" if empty and false_starts == 0 else "  -> FALSE TRACKS: the drone would move"
             if empty else "  -> NONE RECORDED: this says nothing yet. Record the empty room and the "
                           "stuffed animal (vis0)."))

    # ---- mirror check
    m = a.mirror_min_bearing
    def mirror_side(sign):
        # exp_bin is None when the labelled bearing falls outside the model's crop:
        # the person is then not in the image the model sees, so "which side is
        # the person on" has no answer and the frame must not sway the verdict.
        return [r for r in rows if r["vis"] == 1 and r["seen"] and r["x_bin"] >= 0
                and r["bearing"] is not None and r["exp_bin"] is not None
                and (r["bearing"] <= -m if sign < 0 else r["bearing"] >= m)]
    left, right = mirror_side(-1), mirror_side(+1)
    # Not filtered by "seen": a mark beyond the crop edge is unusable for this
    # check whether or not the model thought it saw something there, and the
    # human needs to know the mark itself was bad.
    outside = [r for r in rows if r["vis"] == 1 and r["bearing"] is not None
               and r["exp_bin"] is None and abs(r["bearing"]) >= m]
    jpeg_used = sum(1 for r in left + right if r["file"].lower().endswith(tuple(JPEG_EXTS)))

    # Does the model's x-bin RESPOND to where the person actually is? A head that
    # is stuck - dead, untrained, the wrong checkpoint - answers the same bin for
    # every target, and that produces EXACTLY the same left/right percentages as a
    # mirrored camera (0% on a side whose frames all land on the other side) or,
    # on one-sided data, a clean 100% PASS. Measured over every usable frame in the
    # folder, not just the off-centre ones, so a b0 clip still counts as evidence.
    usable = [r for r in rows if r["vis"] == 1 and r["seen"] and r["x_bin"] >= 0
              and r["exp_bin"] is not None]
    targets = collections.defaultdict(collections.Counter)
    for r in usable:
        targets[r["exp_bin"]][r["x_bin"]] += 1
    target_span = (max(targets) - min(targets)) if targets else 0
    modes = {t: c.most_common(1)[0][0] for t, c in targets.items()}
    same_answer = len(set(modes.values())) == 1 if modes else False
    # Needs at least two targets far enough apart that one answer for both cannot
    # be a merely coarse model: adjacent target bins legitimately blur together.
    x_stuck = same_answer and len(targets) >= 2 and target_span >= MIRROR_CONTRAST_BINS
    stuck_bin = modes[min(modes)] if x_stuck else None
    # One bin for every label has TWO causes, and they need different words:
    #   - the whole model is dead/wrong (nothing in its output moves, ever), or
    #   - the model is alive and the SCENE never changed: the person stood in the
    #     same place for every clip while the labels claimed otherwise.
    # Anything else in the output moving (the size head tracking distance, the
    # confidence moving) says the network is running, so "dead model" is wrong.
    alive = [nm for nm, vals in (("x-bin", {r["x_bin"] for r in usable}),
                                 ("size bucket", {r["size_bucket"] for r in usable}),
                                 ("confidence", {round(r["conf"], 2) for r in usable}))
             if len(vals) > 1]
    model_dead = x_stuck and not alive

    mirror = {"left_n": len(left), "right_n": len(right),
              "left_ok": float(np.mean([r["x_bin"] < 4 for r in left])) if left else None,
              "right_ok": float(np.mean([r["x_bin"] > 4 for r in right])) if right else None,
              "one_side_only": False, "thin_sides": [], "jpeg_frames_used": jpeg_used,
              "outside_crop_n": len(outside), "centre_bin_frac": None,
              "target_bins": sorted(targets), "target_bin_span": target_span,
              "x_bin_stuck": bool(x_stuck), "stuck_bin": stuck_bin,
              "model_dead": bool(model_dead), "outputs_that_vary": alive,
              "reason": "no detected person frames off-center", "verdict": "NO DATA"}
    notes = []
    if not (left or right):
        head = (f"MIRROR CHECK: no detected person frames with |bearing| >= {m:g} deg  -> NO DATA "
                f"(the model saw nobody, or no clip is off-center): stop and report")
        if outside:
            notes.append(f"{len(outside)} off-center frame(s) were labelled beyond the "
                         f"{crop_hfov:.0f} deg crop edge (or past +-90 deg) and could not be used. "
                         f"Re-record them closer to straight ahead, or pass the measured --full-hfov.")
    else:
        centre = sum(1 for r in left + right if r["x_bin"] == 4)
        mirror["centre_bin_frac"] = centre / len(left + right)
        present = [v for v in (mirror["left_ok"], mirror["right_ok"]) if v is not None]
        lo, hi = min(present), max(present)
        mirror["one_side_only"] = len(present) == 1
        one_side = ("" if len(present) == 2 else
                    f" (only {'LEFT' if left else 'RIGHT'} data; record the other side too)")
        # Wording only: several verdicts below talk about "both sides". On a folder
        # with one side that is simply false, and a false sentence in a verdict is
        # the whole defect class this check exists to avoid.
        sides_are = "both sides are" if len(present) == 2 else "the one side recorded is"
        sides_noun = "both sides" if len(present) == 2 else "the one side recorded"
        # Each branch sets a SHORT verdict (the operator copies this line onto the log
        # sheet, so it has to fit on one) and pushes the reasoning into a note under it.
        where = " (the CENTRE bin)" if stuck_bin == 4 else ""
        if model_dead:
            # THE defect this guard exists for: never call a dead model a mirror.
            verdict = "NO DATA: the model returns identical output for every frame - NOT a mirror"
            mirror["verdict"] = "NO DATA"
            mirror["reason"] = "the model returns identical output for every frame"
            notes.append(f"every frame came back the same: x-bin {stuck_bin}{where} for EVERY "
                         f"labelled position (target bins {sorted(targets)}), one size bucket, one "
                         f"confidence. Nothing in this model's output moves, so these frames carry "
                         f"no left/right information at all - the percentages above are what a dead "
                         f"head scores, not what a mirror scores. Check --ckpt and --crop-hfov "
                         f"before anyone touches the camera.")
        elif x_stuck:
            # Alive (size or confidence moves) but one x-bin for every label. Cannot
            # be a mirror; is either a stuck x head or a scene that never changed.
            verdict = f"FAIL: x-bin {stuck_bin}{where} for every labelled position - NOT a mirror"
            mirror["verdict"] = "FAIL"
            mirror["reason"] = "one x-bin for every label: stuck x head, or the labels are wrong"
            notes.append(f"the x head answers bin {stuck_bin} for every target bin "
                         f"{sorted(targets)} while its {' and '.join(alive)} still move(s), so the "
                         f"network is running. Two things do this and neither is a mirror: the "
                         f"person actually stood in the same spot for every clip and the bearing "
                         f"labels / floor marks are wrong, or the x head alone is stuck. Check a "
                         f"frame against its label first, then --ckpt.")
        elif target_span < MIRROR_CONTRAST_BINS:
            # One mark, one answer: a working model and a model stuck on that one
            # bin are indistinguishable here, so neither PASS nor MIRRORED is honest.
            verdict = "NO DATA: only one target position recorded - cannot tell a mirror from a stuck head"
            mirror["verdict"] = "NO DATA"
            mirror["reason"] = "only one target position recorded: no left/right contrast"
            notes.append(f"every usable frame here has the same target (bin(s) {sorted(targets)}), "
                         f"so a model that works and a model stuck on that one bin print identical "
                         f"numbers - in BOTH directions: 100% would not be a real PASS and 0% would "
                         f"not be a real MIRRORED. Record a clip on the other side (or at any "
                         f"second bearing, a straight-ahead one will do) and re-run.")
        elif lo >= MIRROR_PASS_FRAC:
            verdict, mirror["verdict"] = "PASS" + one_side, "PASS"
            mirror["reason"] = f"every side >= {MIRROR_PASS_FRAC:.0%} on the correct side"
        elif hi <= MIRROR_FLIP_FRAC and mirror["centre_bin_frac"] < CENTRE_COLLAPSE_FRAC:
            verdict = "MIRRORED: image looks flipped (left and right swapped)" + one_side
            mirror["verdict"] = "MIRRORED"
            mirror["reason"] = f"every side <= {MIRROR_FLIP_FRAC:.0%} correct, bins not collapsed"
        elif hi <= MIRROR_FLIP_FRAC:
            verdict = (f"NO DATA: {mirror['centre_bin_frac']:.0%} of these frames are in the CENTRE "
                       f"bin 4 - NOT a mirror")
            mirror["verdict"] = "NO DATA"
            mirror["reason"] = "predictions collapsed into the centre bin"
            notes.append("a model that puts its frames in the centre bin scores 0% on both sides "
                         "exactly like a flipped image does, but it is not localising left/right "
                         "at all. Check the checkpoint and the crop FOV before blaming the camera.")
        elif lo >= MIRROR_WEAK_FRAC:
            # Defect this branch exists for: 85/85 used to land in FAIL "check labels
            # and FOV", sending a tired operator to re-tape the floor over a noisy net.
            # "both sides" is a lie on a one-sided folder, so say which it is.
            verdict = (f"WEAK: {sides_are} mostly CORRECT but under {MIRROR_PASS_FRAC:.0%} - "
                       f"NOT mirrored, NOT swapped labels")
            mirror["verdict"] = "WEAK"
            mirror["reason"] = (f"{sides_noun} consistent (>= {MIRROR_WEAK_FRAC:.0%}) but under "
                                f"{MIRROR_PASS_FRAC:.0%}")
            notes.append(f"{sides_are} agreeing with the labels most of the time, which rules out a "
                         f"mirror and rules out swapped marks - a flip or a swap would push a side "
                         f"BELOW half, not to {lo:.0%}. This reads as a noisy model, not a "
                         f"wiring or labelling fault: do NOT go and re-check the floor tape. Record "
                         f"longer clips and re-run; if it stays here, write these numbers down and "
                         f"report them. It is still not a PASS: do not fly on it.")
        elif hi <= 1.0 - MIRROR_WEAK_FRAC:
            verdict = f"FAIL: {sides_are} mostly WRONG but not cleanly swapped"
            mirror["verdict"] = "FAIL"
            mirror["reason"] = f"{sides_noun} mostly wrong, not a clean flip"
            notes.append("a mirrored image seen through a noisy model looks like this, and so does "
                         "a model that barely localises - these numbers do not separate the two. "
                         "Record longer clips on both sides and re-run before concluding anything "
                         "about the camera.")
        elif mirror["one_side_only"]:
            # Reaching here with one side means that side sits between the WEAK floor
            # and its mirror image - i.e. near chance. "The two sides disagree" is not
            # a statement this folder can make, and neither is "so it is not the
            # camera": with one side there is nothing a mirror would have contradicted.
            have, missing = ("LEFT", "RIGHT") if left else ("RIGHT", "LEFT")
            verdict = (f"FAIL: the only side recorded ({have}) is near chance - "
                       f"a mirror is NOT ruled out")
            mirror["verdict"] = "FAIL"
            mirror["reason"] = "single side near chance: cannot separate a mirror from a noisy model"
            notes.append(f"{lo:.0%} on the one side recorded is close to a coin flip, and there is "
                         f"no second side to check it against. A mirrored camera, a merely noisy "
                         f"model and backwards floor marks all print this number, so nothing here "
                         f"rules any of them out. Record a clip on the drone's {missing} as well "
                         f"and re-run before concluding anything about the camera.")
        elif lo > 1.0 - MIRROR_WEAK_FRAC and hi < MIRROR_WEAK_FRAC:
            # Both sides landed near a coin flip, i.e. they AGREE with each other.
            # Calling that "the two sides disagree" and sending the operator to the
            # floor tape is the same wrong-diagnosis bug as the 88/88 WEAK case.
            verdict = "FAIL: both sides near chance - the model is not localising left/right"
            mirror["verdict"] = "FAIL"
            mirror["reason"] = "both sides near chance: sides agree with each other, neither informs"
            notes.append(f"{lo:.0%} and {hi:.0%} are both close to a coin flip, so the two sides "
                         f"AGREE with each other - this is not one side contradicting the other. A "
                         f"mirror drives both sides LOW and correct wiring drives both HIGH; "
                         f"sitting at about half on both is neither, and a noisy mirrored camera "
                         f"prints it too. These numbers do not separate the camera from a model "
                         f"that is barely localising, so do NOT re-tape the floor on the strength "
                         f"of them: check --ckpt and the crop FOV, record longer clips, re-run.")
        else:
            verdict = "FAIL: the two sides DISAGREE - a mirror cannot do that"
            mirror["verdict"] = "FAIL"
            mirror["reason"] = "the two sides disagree"
            notes.append("one side reads correctly and the other does not. A mirrored image gets "
                         "BOTH sides wrong and a correct one gets both right, so this is not the "
                         "camera: check the bearing labels and the floor marks (is b negative on "
                         "the drone's LEFT?) and the crop FOV / --full-hfov.")
        mirror["thin_sides"] = [nm for nm, s in (("LEFT", left), ("RIGHT", right))
                                if 0 < len(s) < MIRROR_THIN_N]
        head = (f"MIRROR CHECK (person seen, |bearing| >= {m:g} deg): LEFT frames with bin < 4: "
                f"{fmt(mirror['left_ok'], '{:.0%}')} of {len(left)}; RIGHT frames with bin > 4: "
                f"{fmt(mirror['right_ok'], '{:.0%}')} of {len(right)}  -> {verdict}")
        if mirror["thin_sides"]:
            notes.append("only " + " and ".join(f"{len(s)} {nm}" for nm, s in
                                                (("LEFT", left), ("RIGHT", right))
                                                if nm in mirror["thin_sides"])
                         + " frame(s) with the person detected: too few to trust. "
                           "Record a longer clip.")
        if jpeg_used:
            notes.append(f"{jpeg_used} of those frames are JPEG, which the model is not run on in "
                         f"flight: re-record them as raw before trusting this verdict.")
        if outside:
            notes.append(f"{len(outside)} further frame(s) are labelled beyond the {crop_hfov:.0f} "
                         f"deg crop edge (or past +-90 deg, which is not an image position at "
                         f"all), so the person is outside the image the model sees: left out of "
                         f"this verdict. Re-record those marks closer to straight ahead.")
        if (mirror["verdict"] != "PASS" and mirror["centre_bin_frac"] >= CENTRE_COLLAPSE_FRAC
                and not model_dead and not x_stuck
                and mirror["reason"] != "predictions collapsed into the centre bin"):
            notes.append(f"{mirror['centre_bin_frac']:.0%} of the frames in this check sit in the "
                         f"centre bin 4, so the model is barely localising: weigh that before "
                         f"reading anything about the camera into the numbers above.")
    print(head)
    for n in notes:
        print(f"  ^ {n}")
    # DOUBLE-NEGATIVE BLIND SPOT (defect 5): this check compares the model against a
    # HUMAN-WRITTEN label. Two mistakes that cancel print a clean PASS, and no amount
    # of data can see that. Printed under every verdict, PASS included.
    print("  convention assumed: a NEGATIVE bearing (b-25) = the person stood to the drone's "
          "LEFT, seen from BEHIND the drone looking the way it faces; x-bins run 0=left..8=right.")
    print("  If the floor marks were written with left/right backwards AND the camera image is "
          "mirrored, the two cancel and this check prints PASS. Read the marks back against the "
          "line above before believing one.")

    csv_path = a.csv or a.frames / "scores.csv"
    cols = ["file", "subject", "light", "take", "run", "dist", "bearing", "vis", "frame", "conf", "seen", "tracking",
            "x_bin", "exp_bin", "x_soft", "exp_x", "bear_model", "bear_err", "size_bucket", "exp_size_bucket",
            "size_value", "exp_size"]
    json_path = a.json or a.frames / "scores.json"
    try:
        with open(csv_path, "w", newline="") as f:
            wr = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
            wr.writeheader()
            for r in rows:
                wr.writerow({k: (f"{r[k]:.4f}" if isinstance(r[k], float) else r[k]) for k in cols})
        json_path.write_text(json.dumps({
            "ckpt": str(a.ckpt), "frames_dir": str(a.frames), "n_frames": len(rows), "crop_hfov_deg": crop_hfov,
            "vis_threshold": a.vis_threshold, "follower": {"enter": a.vis_enter, "exit": a.vis_exit,
                                                           "confirm_frames": a.confirm_frames},
            "jpeg_frames": len(jpegs), "unreadable_files": len(unreadable),
            "bayer_phase_spread_dn": bayer_dn,
            "unlabelled_files": len(skipped), "sidecar_files": len(sidecars),
            "overall": {k: (None if v is None else float(v)) for k, v in summarize(rows).items()},
            "empty_false_tracks": false_starts, "mirror_check": mirror, "groups": groups, "clips": clip_summ,
        }, indent=2))
    except OSError as exc:
        print(f"\nCOULD NOT WRITE RESULTS ({exc}).\nThe numbers above still stand. "
              f"Re-run with --csv/--json pointing somewhere writable.")
        return
    print(f"\nper-frame CSV: {csv_path}\nsummary JSON:  {json_path}")


if __name__ == "__main__":
    main()
