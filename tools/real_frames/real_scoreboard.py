#!/usr/bin/env python3
"""Score the CHIP network on one split of the real-frame index, per clip.

    ~/Downloads/drone/trainenv/bin/python tools/real_frames/real_scoreboard.py --split dev \
        [--json out.json] [--frames-csv out.csv] [--notes "..."] [--baseline-json other.json]

Definitions: docs/datasets/real_test_v1.md (PROPOSED). In short:

  headline  hit@0.75±1 = mean over PERSON clips of the fraction of the clip's labelled
            frames with confidence >= 0.75 (chip integer raw >= ceil(logit(0.75)/eps))
            AND |argmax x-bin - label x-bin| <= 1. Each clip counts once.
  exact     the same with |diff| = 0, always printed next to it.
  guard     no EMPTY, CLUTTER or NEAR-BLACK clip reaches 3 consecutive frames >= 0.75
            (the follower's confirm rule). Pass/fail.
  CI        95% percentile bootstrap over clips (10,000 resamples, seed 0); a run-level
            (cluster) bootstrap is reported as a secondary interval.

The network is score_real_frames.ChipModel: the firmware preprocess port and
model_id_dory.onnx through perception_backends.ChipPerception, the same code every
simulator flight and every real-frame score so far has used. Nothing is reimplemented.

Labels: grid clips use the intended mark's x-bin from the existing geometry code
(score_real_frames.expected_x / x_to_bin, crop HFOV 70 deg). Those labels are
PROVISIONAL (FOV/aim unmeasured) and every output says so. A labels.csv in the clip's
folder (or the Lighthouse session folder), or passed with --labels, overrides them frame
by frame (schema: real_test_v1.md section 7; tools/lighthouse/label_session.py writes it).

Outputs: a JSON (everything, per clip), a per-frame CSV (numbers and file names only,
never pixels), and one appended row in docs/eval_results/REAL_SCOREBOARD.md.
Read-only over ~/drone_frames.
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
import math
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
import index_frames as IX  # noqa: E402
import score_real_frames as S  # noqa: E402

DEFAULT_SCOREBOARD = REPO / "docs/eval_results/REAL_SCOREBOARD.md"
ENTER_P = 0.75                # the follower's enter bar (DECISIONS 2026-09-13)
CONFIRM = 3                   # frames in a row to start following
TOL_BINS = 1                  # the ±1 in hit@0.75±1
MIN_FRAMES = 5                # a clip needs this many scoreable frames (real_test_v1.md section 1)
N_BOOT = 10000
GUARD_KINDS = ("empty", "clutter")
SCOREBOARD_HEADER = """# Real-frame scoreboard

One row per `tools/real_frames/real_scoreboard.py` run. Definitions:
`docs/datasets/real_test_v1.md` (**PROPOSED, needs Sai's sign-off**). Rows are appended by
the tool; do not edit numbers by hand.

- **hit@0.75±1**: mean over person clips of the share of labelled frames with chip
  confidence >= 0.75 and argmax x-bin within 1 of the label. **exact**: same, exact bin.
  [95% bootstrap over clips]
- **guard**: no empty / clutter / near-black clip has 3 consecutive frames >= 0.75.
- Only `test` rows are test results. `dev` rows are for development and include frames
  that every analysis so far has looked at.

| date | model | onnx sha1 | eps | split | clips (person / guard) | hit@0.75±1 [95% CI] | exact [95% CI] | guard | coverage | notes |
|---|---|---|---|---|---|---|---|---|---|---|
"""


# --------------------------------------------------------------------------
# labels
# --------------------------------------------------------------------------
def read_labels_csv(path: Path) -> List[dict]:
    with open(path, newline="") as f:
        rd = csv.DictReader(f)
        cols = set(rd.fieldnames or [])
        if not {"frame", "x_bin"} <= cols:
            raise ValueError(f"{path}: a labels.csv needs columns 'frame' and 'x_bin' (has {sorted(cols)})")
        rows = []
        for r in rd:
            r = {k: (v.strip() if isinstance(v, str) else v) for k, v in r.items()}
            r["_source"] = str(path)
            rows.append(r)
        return rows


def _int_or_none(v) -> Optional[int]:
    if v is None or str(v).strip() == "":
        return None
    return int(float(v))


def frame_label(grid_bin: Optional[int], ov: Optional[dict]):
    """(label x-bin or None, label size bucket or None, status, source) for one frame.

    status: 'labelled' | 'out_of_view' | 'dropped' | 'unlabelled'."""
    if ov is not None:
        src = "labels_csv"
        if (ov.get("drop_reason") or "").strip():
            return None, None, "dropped", src
        in_fov = _int_or_none(ov.get("in_fov"))
        if in_fov == 0:
            return None, None, "out_of_view", src
        xb = _int_or_none(ov.get("x_bin"))
        sb = _int_or_none(ov.get("size_bucket"))
        if xb is None:
            return None, sb, "unlabelled", src
        if not 0 <= xb <= 8:
            raise ValueError(f"labels.csv {ov.get('_source')}: x_bin {xb} for {ov.get('frame')} is not 0-8")
        return xb, sb, "labelled", src
    if grid_bin is None:
        return None, None, "unlabelled", "none"
    return grid_bin, None, "labelled", "grid_mark"


class LabelBook:
    """frame basename (and optional clip_id) -> labels.csv row."""

    def __init__(self, rows: List[dict]):
        self.by_name: Dict[str, List[dict]] = collections.defaultdict(list)
        for r in rows:
            self.by_name[r["frame"]].append(r)

    def get(self, clip_id: str, name: str) -> Optional[dict]:
        cands = self.by_name.get(name, [])
        if not cands:
            return None
        scoped = [r for r in cands if (r.get("clip_id") or "") == clip_id]
        if scoped:
            cands = scoped
        else:
            cands = [r for r in cands if not (r.get("clip_id") or "")]
        if len(cands) > 1:
            srcs = sorted({r["_source"] for r in cands})
            raise ValueError(f"frame {name} is labelled {len(cands)} times ({', '.join(srcs)}); "
                             f"add a clip_id column")
        return cands[0] if cands else None


def labels_for_clip(root: Path, clip: IX.Clip) -> List[dict]:
    rows = []
    seen = set()
    for d in [root / clip.rel_dir] + ([root / clip.session_dir] if clip.session_dir else []):
        p = d / "labels.csv"
        if p.is_file() and p.resolve() not in seen:
            seen.add(p.resolve())
            rows += read_labels_csv(p)
    return rows


# --------------------------------------------------------------------------
# scoring one clip
# --------------------------------------------------------------------------
def max_streak(flags) -> int:
    best = cur = 0
    for f in flags:
        cur = cur + 1 if f else 0
        best = max(best, cur)
    return best


def load_gray(path: Path) -> Optional[np.ndarray]:
    try:
        with Image.open(path) as im:
            return np.asarray(im.convert("L"))
    except Exception:
        return None


def score_clip(model, clip: IX.Clip, row: dict, book: LabelBook, enter_raw: Optional[int],
               crop_hfov: float, batch: int = 64) -> dict:
    """Run the network on every frame of one clip and score it against its labels."""
    bearing = row.get("bearing_deg")
    bearing = float(bearing) if bearing not in (None, "") else None
    grid_bin = None
    if row["kind"] == "person" and bearing is not None:
        grid_bin = S.x_to_bin(S.expected_x(bearing, crop_hfov))
    frames, imgs, unread = [], [], 0
    for f in clip.frames:
        g = load_gray(f["path"])
        if g is None:
            unread += 1
            continue
        frames.append((f, float(g.mean())))
        imgs.append(model.preprocess(g))
    preds = []
    for i in range(0, len(imgs), batch):
        preds += model(np.stack(imgs[i:i + batch]))
    out_frames = []
    for (f, mean), p in zip(frames, preds):
        conf = float(p["visibility_confidence"])
        if enter_raw is not None and "vis_raw" in p:
            ge = int(p["vis_raw"]) >= enter_raw          # the firmware's own integer test
        else:
            ge = conf >= ENTER_P
        xb = int(p["x_bin_index"]) if p.get("x_bin_index") is not None else \
            max(0, min(8, S.bucketize(p["x_soft"], S.XBIN9_INNER)))
        sb = p.get("size_bucket_index")
        ov = book.get(clip.clip_id, f["path"].name)
        lab, lab_size, status, src = frame_label(grid_bin, ov)
        hit = hit_exact = None
        if status == "labelled":
            hit = bool(ge and abs(xb - lab) <= TOL_BINS)
            hit_exact = bool(ge and xb == lab)
        out_frames.append({"file": f["path"].name, "frame": f["frame"], "time": f["time"],
                           "mean_dn": round(mean, 2), "conf": round(conf, 4),
                           "vis_raw": int(p["vis_raw"]) if "vis_raw" in p else None,
                           "ge_enter": int(ge), "x_bin": xb,
                           "size_bucket": int(sb) if sb is not None else None,
                           "label_xbin": lab, "label_size": lab_size, "label_status": status,
                           "label_source": src, "hit": hit, "hit_exact": hit_exact})
    lab_frames = [r for r in out_frames if r["label_status"] == "labelled"]
    status_counts = collections.Counter(r["label_status"] for r in out_frames)
    size_frames = [r for r in lab_frames if r["label_size"] is not None and r["size_bucket"] is not None]
    return {
        "clip_id": clip.clip_id, "n_frames": len(out_frames), "n_unreadable": unread,
        "n_labelled": len(lab_frames), "label_status": dict(status_counts),
        "label_sources": sorted({r["label_source"] for r in lab_frames}),
        "grid_xbin": grid_bin,
        "hit": float(np.mean([r["hit"] for r in lab_frames])) if lab_frames else None,
        "hit_exact": float(np.mean([r["hit_exact"] for r in lab_frames])) if lab_frames else None,
        "seen": float(np.mean([r["ge_enter"] for r in lab_frames])) if lab_frames else None,
        "size_acc": float(np.mean([r["size_bucket"] == r["label_size"] for r in size_frames])) if size_frames else None,
        "frac_ge_enter": float(np.mean([r["ge_enter"] for r in out_frames])) if out_frames else None,
        "max_streak": max_streak(r["ge_enter"] for r in out_frames),
        "median_conf": float(np.median([r["conf"] for r in out_frames])) if out_frames else None,
        "x_bins": dict(sorted(collections.Counter(r["x_bin"] for r in out_frames).items())),
        "frames": out_frames,
    }


# --------------------------------------------------------------------------
# aggregation
# --------------------------------------------------------------------------
def bootstrap_ci(values, n_boot: int = N_BOOT, seed: int = 0, alpha: float = 0.05):
    v = np.asarray([x for x in values if x is not None], float)
    if len(v) == 0:
        return None, None, None
    if len(v) == 1:
        return float(v[0]), None, None
    rng = np.random.default_rng(seed)
    means = v[rng.integers(0, len(v), size=(n_boot, len(v)))].mean(axis=1)
    return float(v.mean()), float(np.quantile(means, alpha / 2)), float(np.quantile(means, 1 - alpha / 2))


def cluster_bootstrap_ci(values, groups, n_boot: int = N_BOOT, seed: int = 0, alpha: float = 0.05):
    """Resample groups (runs) with replacement, then clips within each drawn group."""
    by = collections.defaultdict(list)
    for v, g in zip(values, groups):
        if v is not None:
            by[g].append(v)
    keys = sorted(by)
    if len(keys) < 2:
        return None, None
    rng = np.random.default_rng(seed)
    arrs = [np.asarray(by[k], float) for k in keys]
    means = np.empty(n_boot)
    for b in range(n_boot):
        pick = rng.integers(0, len(keys), size=len(keys))
        vals = [arrs[k][rng.integers(0, len(arrs[k]), size=len(arrs[k]))] for k in pick]
        means[b] = np.concatenate(vals).mean()
    return float(np.quantile(means, alpha / 2)), float(np.quantile(means, 1 - alpha / 2))


def breakdown(metric_clips: List[dict], field: str, n_boot: int, seed: int) -> Dict[str, dict]:
    g = collections.defaultdict(list)
    for c in metric_clips:
        g[str(c["meta"].get(field) or "-")].append(c)
    out = {}
    for k in sorted(g):
        cs = g[k]
        m, lo, hi = bootstrap_ci([c["hit"] for c in cs], n_boot, seed)
        out[k] = {"n_clips": len(cs), "hit": m, "ci": [lo, hi],
                  "exact": float(np.mean([c["hit_exact"] for c in cs])),
                  "seen": float(np.mean([c["seen"] for c in cs]))}
    return out


def coverage(rows: List[dict]) -> dict:
    """real_test_v1.md section 3, for whatever split was scored."""
    person = [r for r in rows if r["kind"] == "person" and r["exposure_regime"] != "near_black"]
    people = sorted({r["person_id"] for r in person if r["person_id"]})
    locs = sorted({r["location"] for r in rows if r["location"]})
    regimes = sorted({r["exposure_regime"] for r in person if r["exposure_regime"]})
    n_empty = sum(1 for r in rows if r["kind"] == "empty" and r["exposure_regime"] != "near_black")
    n_clutter = sum(1 for r in rows if r["kind"] == "clutter" and r["exposure_regime"] != "near_black")
    sides = collections.defaultdict(set)
    for r in person:
        if r["side"]:
            sides[r["person_id"]].add(r["side"])
    all_sides = all(sides.get(p, set()) >= {"left", "centre", "right"} for p in people) if people else False
    checks = {"people >= 3": len(people) >= 3, "locations >= 2": len(locs) >= 2,
              "both regimes (dim, bright)": {"dim", "bright"} <= set(regimes),
              "empty clips": n_empty > 0, "clutter clips": n_clutter > 0,
              "each person left/centre/right": all_sides}
    return {"people": people, "locations": locs, "regimes": regimes, "empty_clips": n_empty,
            "clutter_clips": n_clutter, "checks": checks, "met": all(checks.values())}


def paired_vs_baseline(metric_clips: List[dict], baseline: dict, n_boot: int, seed: int) -> dict:
    base = {c["clip_id"]: c for c in baseline.get("clips", []) if c.get("role") == "metric"}
    common = [c for c in metric_clips if c["clip_id"] in base and base[c["clip_id"]].get("hit") is not None]
    diffs = [c["hit"] - base[c["clip_id"]]["hit"] for c in common]
    m, lo, hi = bootstrap_ci(diffs, n_boot, seed)
    return {"baseline_model": baseline.get("model", {}).get("name"),
            "baseline_onnx_sha1": baseline.get("model", {}).get("onnx_sha1"),
            "n_common_clips": len(common), "n_clips_only_here": len(metric_clips) - len(common),
            "diff_hit": m, "ci": [lo, hi]}


def tilde(p) -> str:
    """Paths in committed JSON are written relative to the home folder, as the other real-frame JSONs are."""
    s = str(p)
    home = str(Path.home())
    return "~" + s[len(home):] if s == home or s.startswith(home + "/") else s


def pct(v, nd=1):
    return "-" if v is None else f"{100 * v:.{nd}f}"


def ci_str(m, lo, hi):
    if m is None:
        return "-"
    if lo is None:
        return f"{pct(m)}"
    return f"{pct(m)} [{pct(lo)}, {pct(hi)}]"


def append_scoreboard(path: Path, row: dict):
    path = Path(path)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(SCOREBOARD_HEADER)
    line = ("| " + " | ".join(str(row[k]).replace("|", "/") for k in
                              ("date", "model", "sha1", "eps", "split", "clips", "hit", "exact", "guard",
                               "coverage", "notes")) + " |\n")
    with open(path, "a") as f:
        f.write(line)
    return line


# --------------------------------------------------------------------------
# main pipeline (model injectable for tests)
# --------------------------------------------------------------------------
def run(a, model=None) -> dict:
    index_rows = IX.read_index(a.index)
    split_rows = [r for r in index_rows if r["split"] == a.split]
    if not split_rows:
        have = collections.Counter(r["split"] for r in index_rows)
        raise SystemExit(f"no clips with split '{a.split}' in {a.index} (splits present: {dict(have)})")
    scoreable = [r for r in split_rows if r["kind"] in ("person",) + GUARD_KINDS]
    skipped_kind = [r["clip_id"] for r in split_rows if r not in scoreable]

    streams = collections.Counter(f"{r['stream_w']}x{r['stream_h']} {r['stream_format']}" for r in scoreable)
    if len(streams) > 1 and not a.allow_mixed_streams:
        raise SystemExit(f"the {a.split} split mixes stream formats {dict(streams)}; numbers from different "
                         f"streams must not be pooled (real_test_v1.md section 8). Re-index with a narrower "
                         f"split, or pass --allow-mixed-streams and say so in --notes.")

    clips = {c.clip_id: c for c in IX.discover_clips(a.root)}
    stale = [r["clip_id"] for r in scoreable if r["clip_id"] not in clips
             or len(clips[r["clip_id"]].frames) != int(r["n_frames"])]
    if stale:
        raise SystemExit(f"the index is stale for {len(stale)} clip(s) (e.g. {stale[0]}): re-run index_frames.py")

    extra = []
    for p in a.labels or []:
        extra += read_labels_csv(p)

    if model is None:
        model = S.ChipModel(a.chip_onnx, a.chip_python)
    eps = getattr(model, "eps", None)
    enter_raw = S.raw_threshold(ENTER_P, eps) if eps else None
    info = dict(getattr(model, "info", {}) or {})
    onnx_sha1 = info.get("onnx_sha1") or S.sha1_of(a.chip_onnx)
    try:
        results = []
        for r in scoreable:
            c = clips[r["clip_id"]]
            book = LabelBook(labels_for_clip(a.root, c) + extra)
            res = score_clip(model, c, r, book, enter_raw, a.crop_hfov)
            res["meta"] = {k: r.get(k) for k in ("kind", "person_id", "session_date", "run_folder", "power_up",
                                                 "exposure_regime", "bright_mean", "dist_m", "bearing_deg",
                                                 "side", "drone", "location", "light", "stream_w", "stream_h",
                                                 "stream_format", "label_source")}
            results.append(res)
    finally:
        if hasattr(model, "close"):
            model.close()

    # roles: metric (person, lit, enough labelled frames), guard, excluded
    for res in results:
        m = res["meta"]
        if m["exposure_regime"] == "near_black":
            res["role"], res["guard_class"] = "guard", "near_black"
            res["why"] = "near-black clip: no scene; counted for the guard, not the person metric"
        elif m["kind"] in GUARD_KINDS:
            res["role"], res["guard_class"] = "guard", m["kind"]
            res["why"] = ""
        elif res["n_labelled"] >= MIN_FRAMES:
            res["role"], res["why"] = "metric", ""
        else:
            res["role"] = "excluded"
            res["why"] = (f"only {res['n_labelled']} labelled frame(s) (< {MIN_FRAMES}); "
                          f"label status {res['label_status']}")
    metric = [c for c in results if c["role"] == "metric"]
    guard = [c for c in results if c["role"] == "guard"]
    excluded = [c for c in results if c["role"] == "excluded"]

    hit, lo, hi = bootstrap_ci([c["hit"] for c in metric], a.boot, a.seed)
    ex, elo, ehi = bootstrap_ci([c["hit_exact"] for c in metric], a.boot, a.seed)
    seen, slo, shi = bootstrap_ci([c["seen"] for c in metric], a.boot, a.seed)
    clo, chi = cluster_bootstrap_ci([c["hit"] for c in metric],
                                    [c["meta"]["power_up"] or c["meta"]["run_folder"] for c in metric],
                                    a.boot, a.seed)
    guard_fail = [c for c in guard if c["max_streak"] >= CONFIRM]
    guard_pass = not guard_fail
    cov = coverage([r for r in split_rows if r["clip_id"] in {c["clip_id"] for c in results}])
    provisional = any("grid_mark" in c["label_sources"] for c in metric)
    onnx_path = Path(info.get("onnx") or a.chip_onnx)
    model_name = a.model_name or (onnx_path.parents[1].name if len(onnx_path.parents) > 1 else "chip")

    breakdowns = {f: breakdown(metric, f, a.boot, a.seed)
                  for f in ("exposure_regime", "session_date", "run_folder", "side", "dist_m", "drone",
                            "location", "person_id")}
    out = {
        "tool": "tools/real_frames/real_scoreboard.py", "generated": datetime.now().isoformat(timespec="seconds"),
        "status": "definitions PROPOSED (docs/datasets/real_test_v1.md), not signed off",
        "split": a.split, "index": tilde(a.index), "index_sha1": IX.sha1_file(a.index), "root": tilde(a.root),
        "tool_git": IX.git_state(),
        "model": {"name": model_name, "backend": "chip", "onnx": tilde(info.get("onnx", a.chip_onnx)),
                  "onnx_sha1": onnx_sha1, "eps": eps, "enter_raw": enter_raw,
                  "onnxruntime": info.get("onnxruntime")},
        "definitions": {"enter_p": ENTER_P, "tolerance_bins": TOL_BINS, "confirm_frames": CONFIRM,
                        "min_labelled_frames": MIN_FRAMES, "near_black_dn": IX.NEAR_BLACK_DN,
                        "crop_hfov_deg": a.crop_hfov, "bootstrap": {"n": a.boot, "seed": a.seed}},
        "labels_provisional": provisional,
        "label_note": IX.LABEL_NOTE if provisional else "",
        "headline": {"name": "hit@0.75±1", "value": hit, "ci95": [lo, hi], "ci95_run_cluster": [clo, chi],
                     "n_clips": len(metric)},
        "exact_bin": {"value": ex, "ci95": [elo, ehi]},
        "seen_rate": {"value": seen, "ci95": [slo, shi],
                      "note": "diagnostic: share of labelled frames >= 0.75 regardless of x-bin"},
        "guard": {"pass": guard_pass, "n_clips": len(guard),
                  "by_class": dict(collections.Counter(c["guard_class"] for c in guard)),
                  "failing": [{"clip_id": c["clip_id"], "class": c["guard_class"], "max_streak": c["max_streak"],
                               "frac_ge_enter": c["frac_ge_enter"]} for c in guard_fail],
                  "lit_pass": not [c for c in guard_fail if c["guard_class"] != "near_black"]},
        "coverage": cov,
        "breakdowns": breakdowns,
        "excluded": [{"clip_id": c["clip_id"], "why": c["why"]} for c in excluded]
        + [{"clip_id": cid, "why": "unlabelled frames (no vis label, no labels.csv)"} for cid in skipped_kind],
        "clips": [{k: v for k, v in c.items() if k != "frames"} for c in results],
    }
    if a.baseline_json:
        out["vs_baseline"] = paired_vs_baseline(metric, json.loads(Path(a.baseline_json).read_text()),
                                                a.boot, a.seed)

    # --- files
    if a.json:
        Path(a.json).parent.mkdir(parents=True, exist_ok=True)
        Path(a.json).write_text(json.dumps(out, indent=1, default=float))
    if a.frames_csv:
        cols = ["clip_id", "role", "file", "frame", "mean_dn", "conf", "vis_raw", "ge_enter", "x_bin",
                "size_bucket", "label_xbin", "label_size", "label_status", "label_source", "hit", "hit_exact"]
        Path(a.frames_csv).parent.mkdir(parents=True, exist_ok=True)
        with open(a.frames_csv, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            for c in results:
                for fr in c["frames"]:
                    w.writerow({**fr, "clip_id": c["clip_id"], "role": c["role"],
                                "hit": "" if fr["hit"] is None else int(fr["hit"]),
                                "hit_exact": "" if fr["hit_exact"] is None else int(fr["hit_exact"])})

    notes = []
    if provisional:
        notes.append("grid labels provisional (FOV/aim unmeasured)")
    if guard_fail:
        nb = sum(1 for c in guard_fail if c["guard_class"] == "near_black")
        notes.append(f"guard fails on {len(guard_fail)} clip(s): {nb} near-black, {len(guard_fail) - nb} lit")
    if excluded:
        notes.append(f"{len(excluded)} short clip(s) excluded")
    if len(streams) == 1:
        notes.append(f"stream {next(iter(streams))}")
    if cov["people"]:
        notes.append(f"people: {', '.join(cov['people'])}")
    if a.notes:
        notes.append(a.notes)
    row = {"date": datetime.now().strftime("%Y-%m-%d"), "model": model_name, "sha1": (onnx_sha1 or "?")[:8],
           "eps": f"{eps:.6g}" if eps else "-", "split": a.split,
           "clips": f"{len(metric)} / {len(guard)}",
           "hit": ci_str(hit, lo, hi), "exact": ci_str(ex, elo, ehi),
           "guard": "PASS" if guard_pass else "FAIL",
           "coverage": "met" if cov["met"] else "NOT met", "notes": "; ".join(notes)}
    out["scoreboard_row"] = row
    if not a.no_append:
        append_scoreboard(a.scoreboard, row)
    print_report(out, metric, guard, excluded, row)
    return out


def print_report(out, metric, guard, excluded, row):
    h, e = out["headline"], out["exact_bin"]
    print(f"\nREAL SCOREBOARD  split={out['split']}  model={out['model']['name']} "
          f"(onnx sha1 {str(out['model']['onnx_sha1'])[:12]}, eps {out['model']['eps']}, "
          f"enter raw >= {out['model']['enter_raw']})")
    if out["labels_provisional"]:
        print(f"  labels: grid marks, {IX.LABEL_NOTE}")
    print(f"  hit@0.75±1 = {ci_str(h['value'], *h['ci95'])}  over {h['n_clips']} person clips "
          f"(run-cluster CI [{pct(h['ci95_run_cluster'][0])}, {pct(h['ci95_run_cluster'][1])}])")
    print(f"  exact-bin  = {ci_str(e['value'], *e['ci95'])}")
    s = out["seen_rate"]
    print(f"  seen (>=0.75, any bin, diagnostic) = {ci_str(s['value'], *s['ci95'])}")
    g = out["guard"]
    print(f"  GUARD: {'PASS' if g['pass'] else 'FAIL'} over {g['n_clips']} clips {g['by_class']}; "
          f"lit empty/clutter only: {'PASS' if g['lit_pass'] else 'FAIL'}")
    for f in g["failing"]:
        print(f"    FAIL {f['clip_id']} ({f['class']}): {f['max_streak']} in a row >= 0.75")
    print(f"  coverage: {'met' if out['coverage']['met'] else 'NOT met'} "
          + ", ".join(f"{k} {'yes' if v else 'NO'}" for k, v in out["coverage"]["checks"].items()))
    for fld, tbl in out["breakdowns"].items():
        if len(tbl) < 2:
            continue
        print(f"  by {fld}: " + "; ".join(f"{k}: {pct(v['hit'])} (n={v['n_clips']})" for k, v in tbl.items()))
    print(f"\n  {'clip':86s} {'role':8s} {'n':>3s} {'lab':>3s} {'hit':>5s} {'exact':>5s} {'seen':>5s} {'streak':>6s}")
    for c in sorted(metric + guard + excluded, key=lambda c: (c["role"], c["clip_id"])):
        print(f"  {c['clip_id'][:86]:86s} {c['role']:8s} {c['n_frames']:3d} {c['n_labelled']:3d} "
              f"{pct(c['hit'], 0):>5s} {pct(c['hit_exact'], 0):>5s} {pct(c['seen'], 0):>5s} {c['max_streak']:6d}")
    for x in out["excluded"]:
        print(f"  excluded: {x['clip_id']}: {x['why']}")
    if "vs_baseline" in out:
        v = out["vs_baseline"]
        print(f"  vs baseline {v['baseline_model']}: {ci_str(v['diff_hit'], *v['ci'])} points over "
              f"{v['n_common_clips']} common clips")
    print("\n  scoreboard row: | " + " | ".join(str(v) for v in row.values()) + " |")


def build_parser():
    import perception_backends as PB
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--split", required=True, choices=IX.SCOREABLE_SPLITS)
    ap.add_argument("--index", type=Path, default=IX.DEFAULT_ROOT / IX.INDEX_DIRNAME / "index.csv")
    ap.add_argument("--root", type=Path, default=IX.DEFAULT_ROOT)
    ap.add_argument("--chip-onnx", type=Path, default=PB.DEFAULT_ONNX)
    ap.add_argument("--chip-python", type=Path, default=PB.DEFAULT_DORY_PYTHON)
    ap.add_argument("--model-name", default=None,
                    help="name for the scoreboard row (default: the release folder, e.g. plain_follow_prod_qat_v3)")
    ap.add_argument("--labels", type=Path, action="append", help="extra labels.csv (repeatable)")
    ap.add_argument("--crop-hfov", type=float, default=IX.CROP_HFOV_DEG,
                    help="crop field of view for grid labels (default 70, the simulator's; real one unmeasured)")
    ap.add_argument("--boot", type=int, default=N_BOOT)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--json", type=Path, default=None)
    ap.add_argument("--frames-csv", type=Path, default=None)
    ap.add_argument("--scoreboard", type=Path, default=DEFAULT_SCOREBOARD)
    ap.add_argument("--no-append", action="store_true", help="do not append a row to the scoreboard")
    ap.add_argument("--notes", default="")
    ap.add_argument("--baseline-json", type=Path, default=None,
                    help="another scoreboard JSON: paired per-clip difference with a bootstrap CI")
    ap.add_argument("--allow-mixed-streams", action="store_true")
    return ap


def main(argv=None):
    a = build_parser().parse_args(argv)
    if not Path(a.index).is_file():
        sys.exit(f"no index at {a.index}: run tools/real_frames/index_frames.py first")
    run(a)


if __name__ == "__main__":
    main()
