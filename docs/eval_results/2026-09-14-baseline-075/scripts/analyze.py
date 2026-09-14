#!/usr/bin/env python3
"""Per-flight record for the 0.75 reference baseline: machine health, attitude,
and the per-flight assertions the brief asks for.

For every attempt run_acceptance2.sh made (from flights_watch.jsonl, written by
watch_flights.py while the harness ran) this joins:

  * what the observer saw at flight time: load average before/after, wall
    time, the floor read from the scene manifest and scene.xml at that instant;
  * what the flight itself recorded in summary.json: sim_wall_ratio,
    processed_hz, step_gap_ms, frames, torn frames, end reason, and - the point
    of this run - the latch rule it flew (vis_enter / vis_exit / confirm_frames)
    and the backend_info (onnx path, eps, sha1) for chip flights;
  * an attitude scan of follow_log.csv over flown rows (event == ""):
    |pitch|, |roll| maxima, z_min, upset frames (> 30 deg), below-floor frames.
    Two floor criteria are reported because the two runs being compared used
    different ones: z_min < 0.5 m (matte baseline, analyze.py) and
    z < 0.25 m (threshold sweep, fly_plan_thresholds.sh).  Both are listed.
  * the validity check, re-run with scoreboard.py --check-run and written to
    <run>/check.txt (the harness prints it into progress.log but keeps no file).

Then it asserts, per flight, and prints every failure:
    vis_enter == 0.75, vis_exit == 0.45, confirm_frames == 3   (from summary.json)
    floor: manifest 0.0 and xml "0" at flight time; cell.json's scene_dir
           manifest still 0.0 after the fact
    backend and rate/latency match the cell (chip -> summary.backend == chip,
           champion onnx path, one sha1 across the suite)

Writes OUT/flights.jsonl, OUT/analysis.json, prints the table (redirect to
OUT/analysis.txt).  step_gap_ms.max is summarised PER SPEED CLASS: chip cells
are rate-capped at 153 ms so their floor is ~158 ms by construction.

Usage: analyze.py OUT_DIR
"""
import csv
import json
import os
import statistics
import subprocess
import sys

HERE = "/Users/saimaruvada/Downloads/drone/pytorch_ssd/tools/crazysim_macos"
P = "/Users/saimaruvada/Downloads/drone/trainenv/bin/python"
CHAMPION_ONNX = ("/Users/saimaruvada/Downloads/drone/pytorch_ssd_unstable/logs/"
                 "plain_follow_prod_qat_v3/quant_eval/model_id_dory.onnx")
WANT_ENTER, WANT_EXIT, WANT_CF = 0.75, 0.45, 3


def scan_attitude(run):
    p = os.path.join(run, "follow_log.csv")
    if not os.path.exists(p):
        return {"att_rows": 0}
    pmax = rmax = 0.0
    zmin = None
    ups = below25 = n = 0
    with open(p) as f:
        for r in csv.DictReader(f):
            if (r.get("event") or "") != "":
                continue
            try:
                pi, ro, z = abs(float(r["pitch"])), abs(float(r["roll"])), float(r["pz"])
            except (KeyError, ValueError, TypeError):
                continue
            n += 1
            pmax, rmax = max(pmax, pi), max(rmax, ro)
            zmin = z if zmin is None else min(zmin, z)
            if pi > 30.0 or ro > 30.0:
                ups += 1
            if z < 0.25:
                below25 += 1
    return {"att_rows": n, "pitch_abs_max": round(pmax, 3), "roll_abs_max": round(rmax, 3),
            "z_min": None if zmin is None else round(zmin, 3),
            "upset_frames_30deg": ups, "below_0p25m_frames": below25,
            "upset_matte_def": bool(ups > 0 or (zmin is not None and zmin < 0.5)),
            "upset_sweep_def": bool(ups > 0 or below25 > 0)}


def check_run(run):
    r = subprocess.run([P, os.path.join(HERE, "scoreboard.py"), "--check-run", run],
                       capture_output=True, text=True)
    txt = (r.stdout + r.stderr).strip()
    open(os.path.join(run, "check.txt"), "w").write(txt + "\n")
    return txt.splitlines()[0][:7].strip() if txt else "NOCHECK", txt


def main():
    out = sys.argv[1]
    watch = [json.loads(l) for l in open(os.path.join(out, "flights_watch.jsonl")) if l.strip()]
    recs, problems = [], []
    for w in sorted(watch, key=lambda x: (x["order"], x["attempt"])):
        run = os.path.join(out, "runs", f"{w['cell']}__r{w['repeat']}a{w['attempt']}")
        rec = dict(w)
        rec["run_dir"] = run
        rec["has_summary"] = os.path.exists(os.path.join(run, "summary.json"))
        tag = f"{w['cell']} r{w['repeat']}a{w['attempt']} (order {w['order']})"
        # --- floor, at flight time (observer) and after the fact (cell.json) ---
        if w.get("floor_manifest") != 0.0:
            problems.append(f"{tag}: manifest floor at flight time = {w.get('floor_manifest')!r}, wanted 0.0")
        if w.get("floor_xml") != ["0"]:
            problems.append(f"{tag}: scene.xml reflectance at flight time = {w.get('floor_xml')!r}, wanted ['0']")
        cj = os.path.join(run, "cell.json")
        if os.path.exists(cj):
            cell = json.load(open(cj))
            rec["cell_json"] = {k: cell.get(k) for k in ("scene", "backend", "camera", "speed", "rate_hz",
                                                          "latency_ms", "sensor_seed", "scene_dir")}
            try:
                man = json.load(open(os.path.join(cell["scene_dir"], "manifest.json")))
                rec["floor_manifest_posthoc"] = man["room"]["floor_reflectance"]
            except Exception as e:  # noqa: BLE001
                rec["floor_manifest_posthoc"] = None
                problems.append(f"{tag}: could not read manifest post hoc: {e!r}")
            if rec.get("floor_manifest_posthoc") != 0.0:
                problems.append(f"{tag}: post-hoc manifest floor = {rec.get('floor_manifest_posthoc')!r}")
            if cell.get("scene") != w["scene"]:
                problems.append(f"{tag}: cell.json scene {cell.get('scene')} != harness line {w['scene']}")
        else:
            cell = {}
            problems.append(f"{tag}: no cell.json")
        # --- what the flight recorded ---
        if rec["has_summary"]:
            s = json.load(open(os.path.join(run, "summary.json")))
            for k in ("sim_wall_ratio", "processed_hz", "loop_hz", "tracking_fraction", "frames_processed",
                      "frames_dropped", "torn_frames", "z_max", "end_reason", "step_gap_ms",
                      "rate_hz_requested", "latency_ms_requested", "backend",
                      "vis_enter", "vis_exit", "confirm_frames", "stale_events", "applied_latency_ms"):
                rec[k] = s.get(k)
            bi = s.get("backend_info") or {}
            rec["backend_info"] = {k: bi.get(k) for k in ("backend", "onnx", "eps", "onnx_sha1", "ckpt",
                                                          "onnxruntime", "python", "threads")}
            # the assertion this run exists for
            if s.get("vis_enter") != WANT_ENTER:
                problems.append(f"{tag}: summary.json vis_enter = {s.get('vis_enter')!r}, wanted {WANT_ENTER}")
            if s.get("vis_exit") != WANT_EXIT:
                problems.append(f"{tag}: summary.json vis_exit = {s.get('vis_exit')!r}, wanted {WANT_EXIT}")
            if s.get("confirm_frames") != WANT_CF:
                problems.append(f"{tag}: summary.json confirm_frames = {s.get('confirm_frames')!r}, wanted {WANT_CF}")
            # backend / speed match the cell
            if cell:
                if cell.get("backend") == "chip":
                    if s.get("backend") != "chip":
                        problems.append(f"{tag}: cell wants chip backend, summary says {s.get('backend')!r}")
                    if bi.get("onnx") != CHAMPION_ONNX:
                        problems.append(f"{tag}: onnx = {bi.get('onnx')!r}, wanted the champion's")
                else:
                    if s.get("backend") != "float":
                        problems.append(f"{tag}: cell wants float backend, summary says {s.get('backend')!r}")
                if float(s.get("rate_hz_requested") or 0) != float(cell.get("rate_hz") or 0):
                    problems.append(f"{tag}: rate_hz_requested {s.get('rate_hz_requested')} != cell {cell.get('rate_hz')}")
                if float(s.get("latency_ms_requested") or 0) != float(cell.get("latency_ms") or 0):
                    problems.append(f"{tag}: latency_ms_requested {s.get('latency_ms_requested')} != cell {cell.get('latency_ms')}")
            rec.update(scan_attitude(run))
            rec["check_verdict"], rec["check_text"] = check_run(run)
        recs.append(rec)

    json.dump(recs, open(os.path.join(out, "analysis.json"), "w"), indent=1)
    with open(os.path.join(out, "flights.jsonl"), "w") as f:
        for r in recs:
            f.write(json.dumps({k: v for k, v in r.items() if k != "check_text"}) + "\n")

    valid = [r for r in recs if r.get("verdict") == "VALID" and r.get("has_summary")]
    print("=" * 118)
    print(f"PER-FLIGHT RECORD  ({len(recs)} attempts, {len(valid)} VALID)  -- 0.75 reference baseline, "
          f"run_acceptance2.sh CORE matrix, 4 repeats")
    print("=" * 118)
    print(f"{'ord':>3} {'cell':<24} {'rep':>3} {'att':>3} {'verdict':<8} {'floor':>5} {'enter':>5} "
          f"{'sim/wall':>8} {'Hz':>6} {'gap_max':>7} {'ld1_be':>6} {'ld1_af':>6} {'|pitch|':>7} "
          f"{'|roll|':>6} {'z_min':>6} {'upset':>5} {'wall':>5}")
    for r in recs:
        g = r.get("step_gap_ms") or {}
        gm = g.get("max") if isinstance(g, dict) else g
        print(f"{r['order']:>3} {r['cell']:<24} {r['repeat']:>3} {r['attempt']:>3} {str(r.get('verdict'))[:8]:<8} "
              f"{str(r.get('floor_manifest')):>5} {str(r.get('vis_enter')):>5} "
              f"{str(r.get('sim_wall_ratio')):>8} {str(r.get('processed_hz')):>6} {str(gm):>7} "
              f"{r['load_before'][0]:>6} {(r.get('load_after') or ['-'])[0]:>6} "
              f"{str(r.get('pitch_abs_max')):>7} {str(r.get('roll_abs_max')):>6} {str(r.get('z_min')):>6} "
              f"{('YES' if r.get('upset_matte_def') else '-'):>5} {str(r.get('wall_s')):>5}")

    print()
    print("SUMMARY")
    n = len(valid)
    print(f"  attempts {len(recs)}; verdicts: "
          f"{ {v: sum(1 for r in recs if r.get('verdict') == v) for v in sorted({str(r.get('verdict')) for r in recs})} }")
    if valid:
        ve = sorted({r.get("vis_enter") for r in valid}, key=str)
        vx = sorted({r.get("vis_exit") for r in valid}, key=str)
        cf = sorted({r.get("confirm_frames") for r in valid}, key=str)
        print(f"  latch rule recorded in summary.json   vis_enter {ve}  vis_exit {vx}  confirm_frames {cf}  "
              f"(n = {n}; flights recording vis_enter == 0.75: {sum(1 for r in valid if r.get('vis_enter') == 0.75)})")
        print(f"  floor at flight time                  manifest {sorted({str(r.get('floor_manifest')) for r in valid})}  "
              f"xml {sorted({str(r.get('floor_xml')) for r in valid})}; distinct scene.xml hashes seen "
              f"{len({(r['scene'], r.get('scene_xml_sha256')) for r in valid})} for {len({r['scene'] for r in valid})} scenes")
        chip = [r for r in valid if r.get("backend") == "chip"]
        print(f"  chip flights                          {len(chip)}; distinct onnx "
              f"{sorted({str(r['backend_info'].get('onnx')) for r in chip})}; distinct sha1 "
              f"{sorted({str(r['backend_info'].get('onnx_sha1')) for r in chip})}; distinct eps "
              f"{sorted({str(r['backend_info'].get('eps')) for r in chip})}")
        print(f"  attitude upsets (matte def: >30 deg or z_min<0.5)   {sum(r['upset_matte_def'] for r in valid)}/{n}")
        print(f"  attitude upsets (sweep def: >30 deg or z<0.25)      {sum(r['upset_sweep_def'] for r in valid)}/{n}")
        print(f"  worst |pitch| {max(r['pitch_abs_max'] for r in valid):.2f} deg   worst |roll| "
              f"{max(r['roll_abs_max'] for r in valid):.2f} deg   z_min {min(r['z_min'] for r in valid):.3f} .. "
              f"{max(r['z_min'] for r in valid):.3f} m")
        sw = [r["sim_wall_ratio"] for r in valid if r.get("sim_wall_ratio") is not None]
        print(f"  sim_wall_ratio      min {min(sw)}  median {statistics.median(sw):.4f}  max {max(sw)}   "
              f"below 0.95: {sum(1 for v in sw if v < 0.95)}")
        lb = [r["load_before"][0] for r in valid]
        la = [r["load_after"][0] for r in valid if r.get("load_after")]
        print(f"  load1 before        min {min(lb)}  median {statistics.median(lb):.2f}  max {max(lb)}")
        print(f"  load1 after         min {min(la)}  median {statistics.median(la):.2f}  max {max(la)}")
        print(f"  torn frames total   {sum(r.get('torn_frames') or 0 for r in valid)}   stale-hover events total "
              f"{sum(r.get('stale_events') or 0 for r in valid)}")
        print(f"  wall per flight     min {min(r['wall_s'] for r in valid)}  median "
              f"{statistics.median(r['wall_s'] for r in valid):.0f}  max {max(r['wall_s'] for r in valid)} s")
        print()
        print("  step_gap_ms.max by speed class (chip cells are rate-capped at 153 ms; ~158 ms is the cap, not a stall):")
        for label, want in (("full speed (no cap)", 0.0), ("chip speed (6.5 Hz / 153 ms)", 6.5)):
            sub = [((r.get("step_gap_ms") or {}).get("max")) for r in valid
                   if float(r.get("rate_hz_requested") or 0) == want]
            sub = [x for x in sub if x is not None]
            if sub:
                print(f"    {label:<30} n={len(sub):<3} min {min(sub):7.1f}  median {statistics.median(sub):7.1f}  "
                      f"max {max(sub):7.1f}")
        print()
        print("  SUSPECT FLIGHTS (gap_max > 150 ms full / > 200 ms chip, or sim_wall_ratio < 0.95):")
        flagged = []
        for r in valid:
            gm = (r.get("step_gap_ms") or {}).get("max")
            cap = 200.0 if float(r.get("rate_hz_requested") or 0) else 150.0
            if (gm is not None and gm > cap) or (r.get("sim_wall_ratio") or 1) < 0.95:
                flagged.append(r)
        for r in flagged:
            print(f"    order {r['order']:>2} {r['cell']:<24} r{r['repeat']}  gap_max {(r.get('step_gap_ms') or {}).get('max')}  "
                  f"sim/wall {r.get('sim_wall_ratio')}  load1 {r['load_before'][0]}->{(r.get('load_after') or ['-'])[0]}")
        if not flagged:
            print("    none")
    print()
    print(f"PER-FLIGHT ASSERTIONS: {len(problems)} problem(s)")
    for p in problems:
        print("  !! " + p)
    if not problems:
        print("  every attempt: floor matte at flight time and post hoc, vis_enter 0.75 / vis_exit 0.45 / "
              "confirm_frames 3 recorded in summary.json, backend and speed match the cell")


if __name__ == "__main__":
    main()
