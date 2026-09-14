"""Summarise the whole-scene build_scene.py --preview probes (matte rebuild of 2026-09-14)."""
import json, glob, os
rows = []
for f in sorted(glob.glob(os.path.join(os.path.dirname(__file__), 'scene_preview_probes', '*.probe.json'))):
    sid = os.path.basename(f).split('.')[0]
    p = json.load(open(f))
    for e in p['camera_positions']:
        subs = ' '.join('%s@%.2fm%s' % (n[5:], s['range_m'], '' if s['in_model_fov'] else '(OUT)') for n, s in e['subjects'].items())
        rows.append('%s\tt=%.1f\tcam_x=%+.2f\tconf=%.3f\tsize=%.3f\tmean=%.1fDN\t%s' % (
            sid, p['preview_t_s'], e['cam_x'], e['model']['visibility_confidence'], e['model']['size_value'], e['frame_mean_dn'], subs))
open(os.path.join(os.path.dirname(__file__), 'scene_preview_summary.tsv'), 'w').write('\n'.join(rows) + '\n')
print('\n'.join(rows))
