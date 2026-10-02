#!/usr/bin/env python3
"""Index every real AI-deck clip under ~/drone_frames: one CSV row per clip.

    ~/Downloads/drone/trainenv/bin/python tools/real_frames/index_frames.py
    ... [--root ~/drone_frames] [--out ~/drone_frames/_index/index.csv]
        [--splits docs/datasets/splits.json] [--run-notes docs/datasets/run_notes.csv]

READ-ONLY over the frames. It opens images, clip.json, meta.json and run logs for
reading and writes exactly two files, index.csv and index_meta.json, into the output
folder. Inside --root it will only write to <root>/_index/; it refuses anything else.
Top-level folders starting with "_" or "." (_rehearsal, _index) are skipped, and so is
any folder named _rehearsal or _index at any depth.

What a clip is (docs/datasets/real_test_v1.md section 1):
  * labelled frames (cpx_grab.py names, e.g. d2.44_b-14_vis1_subj-p01_light-room_take1_
    f00003_t1790300737.5.png): one clip per label stem per folder, split into separate
    runs where the frame number restarts (score_real_frames.split_runs);
  * unlabelled frames (frame_<n>_<unix>.png): one clip per folder, e.g. camera_check's
    check/ folder or a Lighthouse session's frames/ folder;
  * a Lighthouse session (a folder with meta.json and frames/, record_session.py): its
    frames/ folder is the clip; subject, drone and power-up brightness come from meta.json,
    labels from its labels.csv.

Columns (one row per clip):
  clip_id         <folder relative to root>/<clip name>[#run<k>]; what the scoreboard keys on
  session_date, run_folder, run_kind, sub_dir, clip_name, run_no
  kind            person | empty | clutter | unlabelled
                  (vis1 = person; vis0 + subj-empty = empty; vis0 + any other subject =
                  clutter; Lighthouse session of a pNN subject = person)
  subject, person_id, drone, location, light, dist_m, bearing_deg, side, take
  label_source    grid_mark | labels_csv | none
  exp_x, exp_xbin the x-bin the intended mark should give (crop HFOV 70 deg, the existing
                  geometry code in score_real_frames.py); label_note says it is provisional
  n_frames, n_unreadable, first_unix, duration_s
  stream_w, stream_h, stream_format, stream_fps, bayer, pixel_max, sat_level
  bright_mean     mean over frames of the frame's mean pixel value (0-255)
  bright_std      std over frames of the frame mean (stability across the clip)
  contrast_mean   mean over frames of the within-frame pixel std
  frac_saturated  fraction of all pixels at the stream's top code (sat_level: 191 for the
                  162x122 stock stream, measured; else 255)
  frac_near_black fraction of frames with mean < 15
  exposure_regime near_black (< 15) | dim (15 to < 65) | bright (>= 65), from bright_mean
  power_up        <date>/<run>#p<k>: which camera power-up recorded it (from the run log's
                  start headers; a resumed grid is a second power-up)
  powerup_brightness  the pre-flight exposure check of that power-up, if the log has one
  split, split_reason   from splits.json (docs/datasets/real_test_v1.md section 2)
  warnings        anything odd, ';'-separated
"""
from __future__ import annotations

import argparse
import csv
import fnmatch
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
import score_real_frames as S  # noqa: E402  (label parsing, run splitting, the x-bin geometry)

DEFAULT_ROOT = Path.home() / "drone_frames"
DEFAULT_SPLITS = REPO / "docs/datasets/splits.json"
DEFAULT_RUN_NOTES = REPO / "docs/datasets/run_notes.csv"
INDEX_DIRNAME = "_index"
SKIP_NAMES = {"_rehearsal", "_index"}
CROP_HFOV_DEG = 70.0          # the simulator's; the real camera's is unmeasured
NEAR_BLACK_DN = 15.0          # grid_capture.sh / firmware-guard proposal
BRIGHT_DN = 65.0              # dim < 65 <= bright (descriptive; real_test_v1.md section 3)
KNOWN_STREAM_MAX = {(162, 122): 191}   # the stock streamer's 162x122 frames top out at 191 (measured)
LABEL_NOTE = "provisional: FOV/aim unmeasured"
SCOREABLE_SPLITS = ("train", "dev", "test")
PERSON_RE = re.compile(r"^p\d+$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
UNLABELLED_RE = re.compile(r"^frame_(\d+)_(\d+(?:\.\d+)?)$")
STEM_RE = re.compile(r"^(.*?)_f\d+(?:_t\d+(?:\.\d+)?)?$")
RUN_KIND_RE = re.compile(r"^(.*?)_\d{6}$")
LOG_HEADER_RE = re.compile(r"^== [^,]*, (\w{3} \w{3} +\d+ \d{1,2}:\d{2}:\d{2}) \S+ (\d{4})")
LOG_DRONE_RE = re.compile(r"\bdrone (\S+)")
LOG_EXPOSURE_RE = re.compile(r"^== camera exposure check: mean brightness (-?\d+(?:\.\d+)?)")
LOG_LABELS_RE = re.compile(r"labels: (\S+)")

COLUMNS = ["clip_id", "session_date", "run_folder", "run_kind", "sub_dir", "clip_name", "run_no",
           "kind", "subject", "person_id", "drone", "location", "light", "dist_m", "bearing_deg", "side",
           "take", "label_source", "exp_x", "exp_xbin", "label_note", "n_frames", "n_unreadable",
           "first_unix", "duration_s", "stream_w", "stream_h", "stream_format", "stream_fps", "bayer",
           "pixel_max", "sat_level", "bright_mean", "bright_std", "contrast_mean", "frac_saturated",
           "frac_near_black", "exposure_regime", "power_up", "powerup_brightness", "split",
           "split_reason", "warnings"]


# --------------------------------------------------------------------------
# discovery
# --------------------------------------------------------------------------
@dataclass
class Clip:
    clip_id: str
    rel_dir: str                    # folder holding the frames, relative to root ("" = root)
    name: str                       # label stem, or the folder name for unlabelled frames
    run_no: int
    frames: List[dict]              # {"path": Path, "frame": int|None, "time": float|None}, in order
    labels: Optional[dict]          # parse_name() of the first frame, None if unlabelled
    session_dir: Optional[str] = None   # Lighthouse: the session folder (holds meta.json)
    n_runs: int = 1
    extra: dict = field(default_factory=dict)


def _skip_dir(rel_parts) -> bool:
    if not rel_parts:
        return False
    if rel_parts[0].startswith(("_", ".")):
        return True
    return any(p in SKIP_NAMES or p.startswith(".") for p in rel_parts)


def _frame_info(p: Path):
    """(labels or None, frame number, time) for one image file name."""
    stem = p.name[: -len(p.suffix)]
    lab = S.parse_name(p)
    if lab is not None:
        return lab, lab["frame"], lab["time"]
    m = UNLABELLED_RE.match(stem)
    if m:
        return None, int(m.group(1)), float(m.group(2))
    return None, None, None


def discover_clips(root: Path) -> List[Clip]:
    """Every clip under root, in a stable order. Reads names only, never pixels."""
    root = Path(root)
    clips: List[Clip] = []
    for dirpath, dirnames, filenames in os.walk(root):
        d = Path(dirpath)
        rel = d.relative_to(root)
        rel_parts = rel.parts
        if _skip_dir(rel_parts):
            dirnames[:] = []
            continue
        dirnames[:] = sorted(n for n in dirnames if not _skip_dir(rel_parts + (n,)))
        imgs = sorted(d / f for f in filenames
                      if Path(f).suffix.lower() in S.EXTS and not f.startswith("._"))
        if not imgs:
            continue
        groups: Dict[str, list] = {}
        labels_of: Dict[str, Optional[dict]] = {}
        for p in imgs:
            lab, fno, t = _frame_info(p)
            if lab is not None:
                m = STEM_RE.match(p.name[: -len(p.suffix)])
                key = m.group(1) if m else p.stem
            else:
                key = "__unlabelled__"
            groups.setdefault(key, []).append({"path": p, "frame": fno, "time": t, "file": p.name})
            labels_of.setdefault(key, lab)
        rel_dir = "" if str(rel) == "." else rel.as_posix()
        session_dir = None
        if d.name == "frames" and (d.parent / "meta.json").is_file():
            session_dir = d.parent.relative_to(root).as_posix()
        for key in sorted(groups):
            runs = S.split_runs(groups[key])
            name = d.name if key == "__unlabelled__" else key
            for i, run in enumerate(runs, 1):
                cid = f"{rel_dir}/{name}" if rel_dir else name
                if len(runs) > 1:
                    cid += f"#run{i}"
                clips.append(Clip(clip_id=cid, rel_dir=rel_dir, name=name, run_no=i,
                                  frames=[{k: r[k] for k in ("path", "frame", "time")} for r in run],
                                  labels=labels_of[key], session_dir=session_dir, n_runs=len(runs)))
    return clips


# --------------------------------------------------------------------------
# per-run metadata: logs, clip.json, meta.json, run notes
# --------------------------------------------------------------------------
def _parse_header_time(s: str, year: str) -> Optional[float]:
    """'Thu Sep 24 18:46:47' + '2026' in the laptop's local time -> unix seconds."""
    try:
        dt = datetime.strptime(" ".join(s.split()) + " " + year, "%a %b %d %H:%M:%S %Y")
        return time.mktime(dt.timetuple())
    except ValueError:
        return None


def parse_run_logs(run_dir: Path) -> List[dict]:
    """Power-up segments of a run, from every *.log in its folder.

    Each script start header ('== grid capture, <date> ...') opens a segment. A segment
    holds the drone named in the header, the pre-flight exposure check (if logged), and the
    clip labels it recorded. grid_capture.sh appends to the same log when a run is resumed
    with GRID_DIR, and a resume always means a new battery, so a new header = a new power-up.
    """
    segs: List[dict] = []
    if not run_dir.is_dir():
        return segs
    for log in sorted(run_dir.glob("*.log")):
        try:
            text = log.read_text(errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            m = LOG_HEADER_RE.match(line)
            if m:
                dm = LOG_DRONE_RE.search(line)
                drone = dm.group(1) if dm else ""
                segs.append({"start": _parse_header_time(m.group(1), m.group(2)), "log": log.name,
                             "drone": "" if drone in ("unknown", "?") else drone,
                             "exposure": None, "labels": set()})
                continue
            if not segs:
                continue
            m = LOG_EXPOSURE_RE.match(line)
            if m:
                segs[-1]["exposure"] = float(m.group(1))
            m = LOG_LABELS_RE.search(line)
            if m:
                segs[-1]["labels"].add(m.group(1))
    segs.sort(key=lambda s: (s["start"] is None, s["start"] or 0.0))
    for i, s in enumerate(segs, 1):
        s["index"] = i
    return segs


def segment_for(segs: List[dict], first_t: Optional[float], label: Optional[str]) -> Optional[dict]:
    """The power-up a clip was recorded in: the last segment that started before its first
    frame (the header is printed before any frame is grabbed). Falls back to the last segment
    whose log names the clip's labels, then to a single segment."""
    timed = [s for s in segs if s["start"] is not None]
    if first_t is not None and timed:
        before = [s for s in timed if s["start"] <= first_t + 1.0]
        if before:
            return before[-1]
    if label:
        named = [s for s in segs if label in s["labels"]]
        if named:
            return named[-1]
    return segs[0] if len(segs) == 1 else None


def load_run_notes(path: Optional[Path]) -> List[dict]:
    if not path or not Path(path).is_file():
        return []
    with open(path, newline="") as f:
        return [r for r in csv.DictReader(f) if (r.get("run") or "").strip()]


def notes_for(notes: List[dict], run_key: str) -> dict:
    """Merge every run_notes row whose 'run' pattern matches; later rows win, blanks never do."""
    out: dict = {}
    for r in notes:
        if fnmatch.fnmatch(run_key, r["run"].strip()):
            for k, v in r.items():
                if k != "run" and v is not None and str(v).strip():
                    out[k] = str(v).strip()
    return out


def drone_from_uri(uri: str) -> str:
    """'radio://0/80/2M/E7E7E7E709' -> '09' (the team names drones by the last two digits)."""
    m = re.search(r"E7E7E7E7([0-9A-Fa-f]{2})$", uri or "")
    return m.group(1) if m else ""


def _read_json(p: Path) -> Optional[dict]:
    try:
        return json.loads(Path(p).read_text())
    except (OSError, ValueError):
        return None


# --------------------------------------------------------------------------
# splits
# --------------------------------------------------------------------------
def load_splits(path: Optional[Path]) -> dict:
    if not path or not Path(path).is_file():
        return {"persons": {}, "train_dev_sessions": {}, "runs": {}}
    sp = json.loads(Path(path).read_text())
    sp.setdefault("persons", {})
    sp.setdefault("train_dev_sessions", {})
    sp.setdefault("runs", {})
    for pid, p in sp["persons"].items():
        if p.get("pool") not in ("test", "train_dev"):
            raise ValueError(f"splits.json: person {pid} has pool {p.get('pool')!r}; use 'test' or 'train_dev'")
    for pid, sessions in sp["train_dev_sessions"].items():
        if sp["persons"].get(pid, {}).get("pool") == "test":
            raise ValueError(f"splits.json: {pid} is a TEST person but has train_dev_sessions")
        for date, s in sessions.items():
            if s not in ("train", "dev"):
                raise ValueError(f"splits.json: {pid} {date} -> {s!r}; train_dev sessions are 'train' or 'dev'")
    for run, s in sp["runs"].items():
        if s not in SCOREABLE_SPLITS:
            raise ValueError(f"splits.json: run {run} -> {s!r}; use one of {SCOREABLE_SPLITS}")
    return sp


def person_split(sp: dict, pid: str, date: str):
    """(split, reason) for one person on one session date."""
    p = sp["persons"].get(pid)
    if p is None:
        return "unassigned", f"{pid} is not in splits.json"
    if p["pool"] == "test":
        return "test", f"{pid} is a test person"
    s = sp["train_dev_sessions"].get(pid, {}).get(date)
    if s is None:
        return "unassigned", f"{pid} is train_dev but session {date} is not assigned to train or dev"
    return s, f"{pid} session {date} -> {s}"


def assign_split(sp: dict, date: str, run_key: str, person_id: str,
                 run_people: set, session_people: set):
    """(split, reason). split is train/dev/test, or unassigned/conflict (never scored)."""
    override = sp["runs"].get(run_key)
    people = {person_id} if person_id else set(run_people)
    if override is not None:
        for pid in people:
            pool = sp["persons"].get(pid, {}).get("pool")
            if pool == "test" and override != "test":
                return "conflict", f"run override {override} but {pid} is a test person"
            if pool == "train_dev" and override == "test":
                return "conflict", f"run override test but {pid} is train_dev"
        return override, f"runs override in splits.json ({run_key} -> {override})"
    if person_id:
        return person_split(sp, person_id, date)
    for scope, ppl in (("run", run_people), ("session", session_people)):
        if not ppl:
            continue
        got = {person_split(sp, p, date) for p in sorted(ppl)}
        splits = {s for s, _ in got}
        if len(splits) == 1:
            s = splits.pop()
            return s, f"no person in clip; inherits {s} from the {scope}'s people ({', '.join(sorted(ppl))})"
        return "conflict", (f"no person in clip; the {scope}'s people span splits "
                            f"{sorted(splits)}: add a runs override")
    return "unassigned", "no person in clip, run or session: add a runs override in splits.json"


# --------------------------------------------------------------------------
# pixels
# --------------------------------------------------------------------------
def regime(mean: Optional[float]) -> str:
    if mean is None or (isinstance(mean, float) and math.isnan(mean)):
        return ""
    if mean < NEAR_BLACK_DN:
        return "near_black"
    return "dim" if mean < BRIGHT_DN else "bright"


def frame_stats(paths) -> dict:
    """Brightness / saturation statistics over a clip's frames (read-only)."""
    means, stds, sizes, sat_counts, px_total, maxes, unread = [], [], [], [], 0, [], 0
    arrays = []
    for p in paths:
        try:
            with Image.open(p) as im:
                g = np.asarray(im.convert("L"))
        except Exception:
            unread += 1
            continue
        arrays.append(g)
        sizes.append((g.shape[1], g.shape[0]))
    if not arrays:
        return {"n_unreadable": unread, "sizes": set()}
    w, h = max(set(sizes), key=sizes.count)
    sat = KNOWN_STREAM_MAX.get((w, h), 255)
    for g in arrays:
        means.append(float(g.mean()))
        stds.append(float(g.std()))
        sat_counts.append(int((g >= sat).sum()))
        px_total += g.size
        maxes.append(int(g.max()))
    m = np.array(means)
    return {"n_unreadable": unread, "sizes": set(sizes), "w": w, "h": h, "sat_level": sat,
            "pixel_max": max(maxes), "bright_mean": float(m.mean()), "bright_std": float(m.std()),
            "contrast_mean": float(np.mean(stds)), "frac_saturated": sum(sat_counts) / px_total,
            "frac_near_black": float((m < NEAR_BLACK_DN).mean()), "frame_means": means}


# --------------------------------------------------------------------------
# rows
# --------------------------------------------------------------------------
def _fmt(v, nd=4):
    if v is None:
        return ""
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, float):
        return "" if math.isnan(v) else round(v, nd)
    return v


def _kind(clip: Clip, meta: Optional[dict]) -> str:
    lab = clip.labels
    if lab is not None:
        if lab["vis"] == 1:
            return "person"
        return "empty" if (lab.get("subject") or "empty") == "empty" else "clutter"
    if meta and PERSON_RE.match(str(meta.get("subject", ""))):
        return "person"
    return "unlabelled"


def build_index(root: Path, splits: dict, run_notes: List[dict], crop_hfov: float = CROP_HFOV_DEG,
                clips: Optional[List[Clip]] = None) -> List[dict]:
    root = Path(root)
    clips = discover_clips(root) if clips is None else clips
    seg_cache: Dict[str, List[dict]] = {}
    rows = []
    for c in clips:
        parts = c.rel_dir.split("/") if c.rel_dir else []
        date = parts[0] if parts and DATE_RE.match(parts[0]) else ""
        run_folder = parts[1] if len(parts) > 1 and date else (parts[0] if parts and not date else "")
        sub_dir = "/".join(parts[2:]) if date else "/".join(parts[1:])
        run_key = f"{date}/{run_folder}" if date else run_folder
        run_dir = root / date / run_folder if date else root / run_folder
        rk = RUN_KIND_RE.match(run_folder)
        run_kind = rk.group(1) if rk else run_folder
        warn = []
        meta = _read_json(root / c.session_dir / "meta.json") if c.session_dir else None
        lab = c.labels or {}
        kind = _kind(c, meta)
        subject = lab.get("subject") or (meta or {}).get("subject") or ""
        person_id = subject if PERSON_RE.match(subject or "") and kind == "person" else ""

        # stream + pixels
        st = frame_stats([f["path"] for f in c.frames])
        clip_json = _read_json(root / c.rel_dir / f"{c.name}_clip.json") if c.labels else None
        if c.n_runs > 1 and clip_json is not None:
            warn.append(f"{c.n_runs} recordings share this label stem; clip.json describes the last one")
        exts = {f["path"].suffix.lower() for f in c.frames}
        if clip_json and clip_json.get("pixel_provenance"):
            fmt = "+".join(clip_json["pixel_provenance"])
        else:
            fmt = "jpeg" if exts & S.JPEG_EXTS else "raw"
            if exts & S.JPEG_EXTS and exts - S.JPEG_EXTS:
                fmt = "mixed"
        if exts & S.JPEG_EXTS:
            warn.append("JPEG frames: the chip runs on raw; not valid for scoring")
        times = [f["time"] for f in c.frames if f["time"] is not None]
        first_t = min(times) if times else None
        dur = (max(times) - min(times)) if len(times) > 1 else None
        fps = (clip_json or {}).get("stream_fps")
        if fps is None and dur:
            fps = (len(times) - 1) / dur if dur > 0 else None
        if meta and fps is None:
            fps = ((meta.get("frames") or {}).get("fps"))
        if len(st.get("sizes", ())) > 1:
            warn.append(f"frame sizes differ within the clip: {sorted(st['sizes'])}")
        if clip_json and clip_json.get("sizes") and "w" in st:
            js = {tuple(s) for s in clip_json["sizes"]}
            if (st["w"], st["h"]) not in js:
                warn.append(f"frame size {st['w']}x{st['h']} differs from clip.json {sorted(js)}")
        if st.get("n_unreadable"):
            warn.append(f"{st['n_unreadable']} unreadable frame(s)")
        reg = regime(st.get("bright_mean"))
        if reg == "near_black":
            warn.append("near-black: no scene; excluded from the person metric, counted for the guard")

        # power-up, drone
        if run_key not in seg_cache:
            seg_cache[run_key] = parse_run_logs(run_dir) if run_folder else []
        seg = segment_for(seg_cache[run_key], first_t, c.name if c.labels else None)
        drone, pu_bright, power_up = "", None, ""
        if seg is not None:
            drone = seg["drone"]
            pu_bright = seg["exposure"]
            power_up = f"{run_key}#p{seg['index']}"
        if meta:
            drone = drone or drone_from_uri((meta.get("uris") or {}).get("follower", ""))
            b = meta.get("brightness") or {}
            if pu_bright is None and isinstance(b, dict) and b.get("mean") is not None:
                pu_bright = float(b["mean"])
            power_up = power_up or f"{run_key}#p1"
        notes = notes_for(run_notes, run_key)
        if notes.get("drone"):
            if drone and drone != notes["drone"]:
                warn.append(f"drone {drone} in the log but {notes['drone']} in run_notes.csv")
            drone = drone or notes["drone"]

        # label
        bearing, dist = lab.get("bearing"), lab.get("dist")
        exp_x = exp_bin = None
        label_source, label_note = "none", ""
        labels_csv = (root / c.rel_dir / "labels.csv").is_file() or (
            c.session_dir is not None and (root / c.session_dir / "labels.csv").is_file())
        if kind == "person" and bearing is not None:
            exp_x = S.expected_x(bearing, crop_hfov)
            exp_bin = S.x_to_bin(exp_x)
            label_source, label_note = "grid_mark", LABEL_NOTE
            if exp_bin is None:
                warn.append(f"bearing {bearing:g} deg is outside the {crop_hfov:g} deg crop: no x-bin label")
        if labels_csv:
            label_source = "labels_csv"
            label_note = (LABEL_NOTE + "; labels.csv overrides per frame") if exp_bin is not None else ""
        if kind == "person" and label_source == "none":
            warn.append("person clip without a label (no bearing, no labels.csv)")
        side = ""
        if bearing is not None:
            side = "centre" if abs(bearing) < 1.0 else ("left" if bearing < 0 else "right")
        if len(c.frames) < 5:
            warn.append(f"only {len(c.frames)} frame(s): shorter than the 5-frame clip minimum")

        rows.append({
            "clip_id": c.clip_id, "session_date": date, "run_folder": run_folder, "run_kind": run_kind,
            "sub_dir": sub_dir, "clip_name": c.name, "run_no": c.run_no, "kind": kind, "subject": subject,
            "person_id": person_id, "drone": drone, "location": notes.get("location", ""),
            "light": lab.get("light") or "", "dist_m": dist, "bearing_deg": bearing, "side": side,
            "take": lab.get("take"), "label_source": label_source, "exp_x": exp_x, "exp_xbin": exp_bin,
            "label_note": label_note, "n_frames": len(c.frames), "n_unreadable": st.get("n_unreadable", 0),
            "first_unix": first_t, "duration_s": dur, "stream_w": st.get("w"), "stream_h": st.get("h"),
            "stream_format": fmt, "stream_fps": fps, "bayer": (clip_json or {}).get("bayer"),
            "pixel_max": st.get("pixel_max"), "sat_level": st.get("sat_level"),
            "bright_mean": st.get("bright_mean"), "bright_std": st.get("bright_std"),
            "contrast_mean": st.get("contrast_mean"), "frac_saturated": st.get("frac_saturated"),
            "frac_near_black": st.get("frac_near_black"), "exposure_regime": reg, "power_up": power_up,
            "powerup_brightness": pu_bright, "_run_key": run_key, "_warn": warn,
        })

    # splits need every clip's people first (no-person clips inherit from their run/session)
    run_people: Dict[str, set] = {}
    session_people: Dict[str, set] = {}
    for r in rows:
        if r["person_id"]:
            run_people.setdefault(r["_run_key"], set()).add(r["person_id"])
            session_people.setdefault(r["session_date"], set()).add(r["person_id"])
    for r in rows:
        s, why = assign_split(splits, r["session_date"], r["_run_key"], r["person_id"],
                              run_people.get(r["_run_key"], set()),
                              session_people.get(r["session_date"], set()))
        r["split"], r["split_reason"] = s, why
        r["warnings"] = "; ".join(r.pop("_warn"))
        r.pop("_run_key")
    return rows


def write_index(rows: List[dict], out: Path):
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(out.suffix + ".tmp")
    with open(tmp, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        for r in rows:
            w.writerow({k: _fmt(r.get(k)) for k in COLUMNS})
    os.replace(tmp, out)


def read_index(path: Path) -> List[dict]:
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def sha1_file(p: Optional[Path]) -> Optional[str]:
    try:
        return hashlib.sha1(Path(p).read_bytes()).hexdigest()
    except (OSError, TypeError):
        return None


def git_state(repo: Path = REPO) -> dict:
    try:
        sha = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True,
                             text=True, timeout=10).stdout.strip()
        dirty = bool(subprocess.run(["git", "-C", str(repo), "status", "--porcelain", "--untracked-files=no"],
                                    capture_output=True, text=True, timeout=10).stdout.strip())
        return {"sha": sha or None, "dirty": dirty}
    except Exception:
        return {"sha": None, "dirty": None}


def check_out_path(root: Path, out: Path):
    """Inside root, only <root>/_index/ may be written. Raises ValueError otherwise."""
    root_r, out_r = Path(root).resolve(), Path(out).resolve()
    try:
        rel = out_r.relative_to(root_r)
    except ValueError:
        return
    if not rel.parts or rel.parts[0] != INDEX_DIRNAME:
        raise ValueError(f"refusing to write {out} inside {root}: only {root / INDEX_DIRNAME}/ is allowed "
                         f"(the frames folder holds real captured data)")


def summarize(rows: List[dict]) -> str:
    from collections import Counter
    lines = [f"{len(rows)} clips, {sum(int(r['n_frames']) for r in rows)} frames"]
    lines.append("  by kind:   " + ", ".join(f"{k} {v}" for k, v in sorted(Counter(r["kind"] for r in rows).items())))
    lines.append("  by regime: " + ", ".join(f"{k or '-'} {v}" for k, v in
                                           sorted(Counter(r["exposure_regime"] for r in rows).items())))
    lines.append("  by split:  " + ", ".join(f"{k} {v}" for k, v in sorted(Counter(r["split"] for r in rows).items())))
    streams = Counter(f"{r['stream_w']}x{r['stream_h']} {r['stream_format']}" for r in rows)
    lines.append("  streams:   " + ", ".join(f"{k} ({v})" for k, v in sorted(streams.items())))
    nb = [r["clip_id"] for r in rows if r["exposure_regime"] == "near_black"]
    if nb:
        lines.append(f"  near-black clips: {len(nb)}")
    warned = [r for r in rows if r["warnings"]]
    if warned:
        lines.append(f"  clips with warnings: {len(warned)} (see the warnings column)")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, default=DEFAULT_ROOT, help="the frames tree (read-only)")
    ap.add_argument("--out", type=Path, default=None, help="index CSV (default <root>/_index/index.csv)")
    ap.add_argument("--splits", type=Path, default=DEFAULT_SPLITS)
    ap.add_argument("--run-notes", type=Path, default=DEFAULT_RUN_NOTES)
    ap.add_argument("--crop-hfov", type=float, default=CROP_HFOV_DEG,
                    help="crop field of view for the grid labels' expected x-bin (default 70, the simulator's)")
    a = ap.parse_args(argv)
    if not a.root.is_dir():
        sys.exit(f"no frames folder at {a.root}")
    out = a.out or a.root / INDEX_DIRNAME / "index.csv"
    try:
        check_out_path(a.root, out)
    except ValueError as e:
        sys.exit(str(e))
    splits = load_splits(a.splits)
    rows = build_index(a.root, splits, load_run_notes(a.run_notes), a.crop_hfov)
    if not rows:
        sys.exit(f"no frames found under {a.root}")
    write_index(rows, out)
    meta = {"tool": "tools/real_frames/index_frames.py", "generated": datetime.now().isoformat(timespec="seconds"),
            "root": str(a.root), "n_clips": len(rows), "crop_hfov_deg": a.crop_hfov,
            "splits": str(a.splits), "splits_sha1": sha1_file(a.splits),
            "run_notes": str(a.run_notes), "run_notes_sha1": sha1_file(a.run_notes),
            "tool_git": git_state(), "index_sha1": sha1_file(out)}
    (out.parent / "index_meta.json").write_text(json.dumps(meta, indent=1))
    print(summarize(rows))
    print(f"\nindex: {out}")


if __name__ == "__main__":
    main()
