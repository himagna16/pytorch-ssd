# Generates the two dorm tape sheets to scale on Sai's 5 x 11 tile (1 ft) grid.
F = 38                      # px per foot (one tile)
X0, Y0 = 190, 110           # top-left of the tile rectangle (door end at top)
W, L = 5, 10                # tiles wide, tiles long (was 11; the door-end row went to station 1's stand, 2026-09-24)
YW = Y0 + L * F             # window-end edge (bottom)
def ycol(k): return YW - k * F          # joint k feet from the window edge
def xmid(c): return X0 + c * F - F / 2  # middle of column c (1 = drone's left = page left)

HEAD = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 640" width="1000" height="640" font-family="Helvetica, Arial, sans-serif" font-size="13">
<title>{title}</title><rect width="1000" height="640" fill="#fff"/>
<defs>
<marker id="r" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#c0392b"/></marker>
<marker id="g" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#1d8a4a"/></marker>
<marker id="b" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#1f5fbf"/></marker>
<pattern id="h" width="7" height="7" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="7" stroke="#d8c29c" stroke-width="2"/></pattern>
</defs>
<text x="24" y="32" font-size="20" font-weight="bold" fill="{color}">{h1}</text>
<text x="24" y="54" fill="#555">{h2}</text>
'''

def room():
    o = []
    # beds alongside the open rectangle, ~7 ft from the window end (approximate)
    o.append(f'<rect x="{X0-88}" y="{ycol(7)}" width="84" height="{7*F}" fill="url(#h)" stroke="#b8975f" stroke-width="2"/>')
    o.append(f'<rect x="{X0+W*F+4}" y="{ycol(7)}" width="84" height="{7*F}" fill="url(#h)" stroke="#b8975f" stroke-width="2"/>')
    for x in (X0-46, X0+W*F+46):
        o.append(f'<text x="{x}" y="{ycol(3.6)}" text-anchor="middle" fill="#8a6a35" font-size="11">bed</text>')
        o.append(f'<text x="{x}" y="{ycol(3.6)+14}" text-anchor="middle" fill="#8a6a35" font-size="11">~7 ft</text>')
    # tile grid
    o.append(f'<rect x="{X0}" y="{Y0}" width="{W*F}" height="{L*F}" fill="#f7f7f4" stroke="#333" stroke-width="3"/>')
    for c in range(1, W):
        o.append(f'<line x1="{X0+c*F}" y1="{Y0}" x2="{X0+c*F}" y2="{YW}" stroke="#d6d6cf"/>')
    for r in range(1, L):
        o.append(f'<line x1="{X0}" y1="{Y0+r*F}" x2="{X0+W*F}" y2="{Y0+r*F}" stroke="#d6d6cf"/>')
    # row numbers (from the window) and column numbers
    for k in range(1, L+1):
        o.append(f'<text x="{X0+W*F+112}" y="{ycol(k)+F/2+4}" text-anchor="middle" fill="#999" font-size="10">row {k}</text>')
    for c in range(1, W+1):
        o.append(f'<text x="{xmid(c)}" y="{YW+16}" text-anchor="middle" fill="#999" font-size="10">col {c}</text>')
    o.append(f'<line x1="{X0-20}" y1="{YW+4}" x2="{X0+W*F+20}" y2="{YW+4}" stroke="#6fb3e0" stroke-width="7"/>')
    o.append(f'<text x="{X0+W*F/2}" y="{YW+36}" text-anchor="middle" font-weight="bold" fill="#2a7ab0">WINDOW END (curtains closed)</text>')
    o.append(f'<text x="{X0+W*F/2}" y="{Y0-10}" text-anchor="middle" font-weight="bold" fill="#333">DOOR END</text>')
    o.append(f'<text x="{X0-10}" y="{YW+82}" fill="#888" font-size="11">Each square = one 1 ft floor tile. 5 wide x 10 long, to scale. Beds approximate.</text>')
    return '\n'.join(o)

def X(x, y, color, s=8, w=4):
    return f'<g stroke="{color}" stroke-width="{w}"><line x1="{x-s}" y1="{y-s}" x2="{x+s}" y2="{y+s}"/><line x1="{x+s}" y1="{y-s}" x2="{x-s}" y2="{y+s}"/></g>'

def steps(lines, x=580, y=96):
    o, yy = [f'<g transform="translate({x},{y})">'], 0
    for kind, t in lines:
        if kind == 'gap': yy += 14; continue
        style = {'h': 'font-size="15" font-weight="bold" fill="#222"', 'g': 'font-weight="bold" fill="#1d8a4a"',
                 'b': 'font-weight="bold" fill="#1f5fbf"', 'o': 'font-weight="bold" fill="#8a4a00"',
                 'r': 'font-weight="bold" fill="#c0392b"', 't': 'fill="#333"', 's': 'fill="#888" font-size="11"', 'code': ''}[kind]
        if kind == 'code':
            o.append(f'<rect x="0" y="{yy-15}" width="405" height="23" rx="4" fill="#f2f2f2" stroke="#ccc"/>')
            o.append(f'<text x="7" y="{yy+1}" font-family="Menlo, monospace" font-size="11" fill="#222">{t}</text>')
        else:
            o.append(f'<text x="0" y="{yy}" {style}>{t}</text>')
        yy += 18
    o.append('</g>')
    return '\n'.join(o)

# ---------- tonight ----------
cx, lens_y, mark_y = xmid(3), ycol(1), ycol(9)
xl, xr = xmid(1), xmid(5)
t = [HEAD.format(title="Tonight: camera + mirror check, tile layout", color="#1d8a4a",
                 h1="TONIGHT: tape ONLY the 3 green X's (count tiles)",
                 h2="Seen from BEHIND the drone looking at the door, so the drone's left = the page's left."), room()]
# chair + drone
t.append(f'<rect x="{cx-22}" y="{ycol(1)-4}" width="44" height="{F+2}" rx="6" fill="#e3c79b" stroke="#a07a45" stroke-width="2"/>')
t.append(f'<rect x="{cx-15}" y="{lens_y-2}" width="30" height="20" rx="4" fill="#1d8a4a"/>')
t.append(f'<text x="{cx}" y="{lens_y+12}" text-anchor="middle" fill="#fff" font-size="9" font-weight="bold">drone</text>')
t.append(f'<line x1="{cx}" y1="{lens_y-3}" x2="{cx}" y2="{lens_y-26}" stroke="#1d8a4a" stroke-width="3" marker-end="url(#g)"/>')
t.append(f'<text x="{cx+26}" y="{lens_y+14}" fill="#1d8a4a" font-size="11" font-weight="bold">①</text>')
# distance arrow
t.append(f'<line x1="{cx+10}" y1="{lens_y-30}" x2="{cx+10}" y2="{mark_y+12}" stroke="#c0392b" stroke-width="1.5" marker-start="url(#r)" marker-end="url(#r)"/>')
t.append(f'<rect x="{cx+14}" y="{ycol(5)-14}" width="78" height="34" fill="#fff" opacity="0.95"/>')
t.append(f'<text x="{cx+18}" y="{ycol(5)}" fill="#c0392b" font-weight="bold">8 tiles</text>')
t.append(f'<text x="{cx+18}" y="{ycol(5)+14}" fill="#c0392b" font-size="11">= 8 ft (2.44 m)</text>')
# sideways arrows
t.append(f'<line x1="{cx-10}" y1="{mark_y+18}" x2="{xl+10}" y2="{mark_y+18}" stroke="#c0392b" stroke-width="1.5" marker-start="url(#r)" marker-end="url(#r)"/>')
t.append(f'<line x1="{cx+10}" y1="{mark_y+18}" x2="{xr-10}" y2="{mark_y+18}" stroke="#c0392b" stroke-width="1.5" marker-start="url(#r)" marker-end="url(#r)"/>')
t.append(f'<text x="{(cx+xl)/2}" y="{mark_y+34}" text-anchor="middle" fill="#c0392b" font-size="11" font-weight="bold">2 tiles</text>')
t.append(f'<text x="{(cx+xr)/2}" y="{mark_y+34}" text-anchor="middle" fill="#c0392b" font-size="11" font-weight="bold">2 tiles</text>')
t.append(f'<rect x="{X0-4}" y="{mark_y-20}" width="{W*F+8}" height="40" fill="#fff6b3" stroke="#e0b400" stroke-width="2" rx="6"/>')
t.append(f'<text x="{X0-10}" y="{mark_y+5}" text-anchor="end" fill="#b08600" font-weight="bold" font-size="13">TAPE HERE →</text>')
t.append(f'<text x="{X0-10}" y="{mark_y+21}" text-anchor="end" fill="#b08600" font-size="11">9 tiles from window</text>')
for x, lab in ((cx, "② CENTER"), (xl, "③ LEFT"), (xr, "④ RIGHT")):
    t.append(X(x, mark_y, "#1d8a4a", s=11, w=5))
    t.append(f'<text x="{x}" y="{mark_y-27}" text-anchor="middle" fill="#1d8a4a" font-weight="bold" font-size="12">{lab}</text>')
t.append(f'<text x="{xl}" y="{mark_y-43}" text-anchor="middle" fill="#555" font-size="11" font-weight="bold">clip 1</text>')
t.append(f'<text x="{xr}" y="{mark_y-43}" text-anchor="middle" fill="#555" font-size="11" font-weight="bold">clip 2</text>')
t.append(steps([
    ('h', 'Step by step, counting tiles'),
    ('g', '① Drone'), ('t', 'Chair at the window end, in the MIDDLE column (col 3).'),
    ('t', 'Drone on books on the seat, lens ~2 ft 7½ in off the floor,'),
    ('t', 'lens right above the joint between row 1 and row 2,'),
    ('t', 'camera pointing straight at the door. NO tape for the drone.'), ('gap', ''),
    ('g', '② CENTER (tape #1)'), ('t', 'Count 9 tiles from the window wall toward the door'),
    ('t', '(= 8 tiles past the lens). On the line where tile 9 ends,'),
    ('t', 'middle of col 3. Tape an X.'), ('gap', ''),
    ('g', '③ LEFT  ④ RIGHT (tapes #2 and #3)'), ('t', 'Same line, 2 tiles sideways: middle of col 1 (LEFT)'),
    ('t', 'and middle of col 5 (RIGHT). Tape an X on each.'),
    ('t', 'LEFT = your left when you stand behind the drone.'),
    ('t', 'Move chairs / the basket if they are in the way.'), ('gap', ''),
    ('g', 'Run it'), ('t', 'Battery in, wait 30 s, join WiFi "WiFi streaming example":'),
    ('code', 'zsh ~/Downloads/drone/pytorch_ssd/tools/real_frames/camera_check.sh'),
    ('t', 'Enter → walk to ③ LEFT during the countdown → face the drone,'),
    ('t', 'stand still 10 s. Then the same on ④ RIGHT.'), ('gap', ''),
    ('r', 'Done when it prints MIRROR CHECK … PASS.'),
    ('t', 'Rejoin normal WiFi and send Claude the folder name.'), ('gap', ''),
    ('s', 'Lighthouse tape is a different sheet (dorm_lighthouse_tape.svg).'),
]))
t.append('</svg>')

# ---------- Lighthouse night, AS BUILT 2026-09-24 ----------
# Sai taped the frame rotated 180 deg from the first plan: +x points toward the DOOR, and the
# SIDE mark is on the left when facing +x (verified by Sai), which from above is col 1.
# Channels as set: channel 1 = window end (Oaj's corner), channel 2 = door end (Sai's side).
oy, xy = ycol(5.0), ycol(5.0 + 3.28125)
sy_x = xmid(1)
u = [HEAD.format(title="Lighthouse setup as built: stations, blue tape, wizard + tape check", color="#1f5fbf",
                 h1="LIGHTHOUSE, AS YOU SET IT UP (5 x 10 floor)",
                 h2="Door end at the top, window end at the bottom. +x points toward the DOOR."), room()]
ch2 = (X0 + W*F + 60, Y0 - 30); ch1 = (X0 - 60, YW + 22)
u.append(f'<line x1="{ch2[0]}" y1="{ch2[1]}" x2="{cx+6}" y2="{oy-6}" stroke="#e07b00" stroke-width="1.5" stroke-dasharray="6 4"/>')
u.append(f'<line x1="{ch1[0]}" y1="{ch1[1]}" x2="{cx-6}" y2="{oy+6}" stroke="#e07b00" stroke-width="1.5" stroke-dasharray="6 4"/>')
for (x, y), n in ((ch2, 2), (ch1, 1)):
    u.append(f'<circle cx="{x}" cy="{y}" r="16" fill="#e07b00" stroke="#8a4a00" stroke-width="2"/><text x="{x}" y="{y+6}" text-anchor="middle" fill="#fff" font-weight="bold" font-size="15">{n}</text>')
u.append(f'<text x="{ch2[0]-22}" y="{ch2[1]+5}" text-anchor="end" fill="#8a4a00" font-weight="bold" font-size="12">Channel 2: door end, your side ✓</text>')
u.append(f'<text x="40" y="{ch1[1]+42}" fill="#8a4a00" font-weight="bold" font-size="12">Channel 1: window end, Oaj\'s corner ✓</text>')
u.append(f'<rect x="{X0-4}" y="{oy-20}" width="{W*F+8}" height="40" fill="#e8f0ff" stroke="#1f5fbf" stroke-width="1.5" rx="6" opacity="0.9"/>')
u.append(X(cx, oy, "#1f5fbf", s=10, w=5))
u.append(f'<text x="{cx}" y="{oy+36}" text-anchor="middle" fill="#1f5fbf" font-weight="bold">① ORIGIN</text>')
u.append(X(sy_x, oy, "#1f5fbf", s=10, w=5))
u.append(f'<text x="{sy_x}" y="{oy+36}" text-anchor="middle" fill="#1f5fbf" font-weight="bold">③ SIDE</text>')
u.append(f'<line x1="{sy_x+12}" y1="{oy-12}" x2="{cx-12}" y2="{oy-12}" stroke="#c0392b" stroke-width="1.5" marker-start="url(#r)" marker-end="url(#r)"/>')
u.append(f'<text x="{(cx+sy_x)/2}" y="{oy-18}" text-anchor="middle" fill="#c0392b" font-size="11" font-weight="bold">2 tiles</text>')
u.append(f'<line x1="{cx}" y1="{oy-22}" x2="{cx}" y2="{xy+6}" stroke="#1f5fbf" stroke-width="2.5" marker-end="url(#b)"/>')
u.append(f'<line x1="{cx-14}" y1="{xy}" x2="{cx+14}" y2="{xy}" stroke="#1f5fbf" stroke-width="5"/>')
u.append(f'<text x="{cx+18}" y="{xy+5}" fill="#1f5fbf" font-weight="bold">② +x</text>')
u.append(f'<text x="{cx+18}" y="{ycol(6.9)}" fill="#1f5fbf" font-weight="bold" font-size="12">1.00 m</text>')
u.append(f'<text x="{cx+18}" y="{ycol(6.9)+14}" fill="#1f5fbf" font-size="11">(3 tiles + 3⅜ in)</text>')
u.append(f'<text x="{sy_x}" y="{oy+52}" text-anchor="middle" fill="#555" font-size="10">left of +x</text>')
u.append(steps([
    ('h', 'Done so far ✓'),
    ('t', '✓ tape  ✓ channels (1 window end, 2 door end)  ✓ stands'), ('gap', ''),
    ('b', 'NEXT: room setup wizard (cfclient)'),
    ('t', 'Drone on the cable, battery in. cfclient: pick usb://0 → Connect.'),
    ('t', 'Lighthouse Positioning tab → "Start Set Up". For each step'),
    ('t', 'put the drone down, hands off, click "Start measurement":'),
    ('t', '  Origin sample   → drone on ① ORIGIN'),
    ('t', '  X-axis sample   → drone on ② +x'),
    ('t', '  XY-plane sample → drone on ③ SIDE'),
    ('t', '  XYZ-space (3-5) → hold it ~waist high over the floor,'),
    ('t', '     twist left-right quickly, hold still, "Sample position".'),
    ('t', '     Spread them out: near ①, near each end, near ③.'),
    ('t', 'Wait for "Uploaded". Then Disconnect in cfclient.'), ('gap', ''),
    ('b', 'THEN: tape check (Terminal)'),
    ('code', '../cfloaderenv/bin/python tools/lighthouse/tape_check.py'),
    ('t', 'A on ①, B on ②, C on ③, D on ① turned 90° LEFT'),
    ('t', '(camera then faces ③). Camera faces +x for A, B, C.'),
    ('r', 'All 4 PASS = room frame right + yaw sign confirmed.'), ('gap', ''),
    ('s', 'Run from ~/Downloads/drone/pytorch_ssd. cfclient must be disconnected first.'),
]))
u.append('</svg>')

# ---------- grid capture (2026-09-24) ----------
g = [HEAD.format(title="Grid capture: 9 marks + empty room, tile layout", color="#1d8a4a",
                 h1="GRID CAPTURE: 9 green marks (3 rows x 3), you are the subject",
                 h2="Seen from BEHIND the drone looking at the door: the drone's left = the page's left."), room()]
# faded Lighthouse tape for orientation (already on the floor)
for (x, y, lab) in ((cx, ycol(5.0), "blue ORIGIN"), (xmid(1), ycol(5.0), "blue SIDE")):
    g.append(X(x, y, "#9db8e8", s=7, w=3))
g.append(f'<line x1="{cx-12}" y1="{ycol(8.28125)}" x2="{cx+12}" y2="{ycol(8.28125)}" stroke="#9db8e8" stroke-width="4"/>')
g.append(f'<text x="{X0+W*F+8}" y="{ycol(5.0)+4}" fill="#8aa6d8" font-size="10">blue = Lighthouse tape</text>')
g.append(f'<text x="{X0+W*F+8}" y="{ycol(5.0)+16}" fill="#8aa6d8" font-size="10">(leave it, ignore it)</text>')
# drone
g.append(f'<rect x="{cx-22}" y="{ycol(1)-4}" width="44" height="{F+2}" rx="6" fill="#e3c79b" stroke="#a07a45" stroke-width="2"/>')
g.append(f'<rect x="{cx-15}" y="{lens_y-2}" width="30" height="20" rx="4" fill="#1d8a4a"/>')
g.append(f'<text x="{cx}" y="{lens_y+12}" text-anchor="middle" fill="#fff" font-size="9" font-weight="bold">drone</text>')
g.append(f'<line x1="{cx}" y1="{lens_y-3}" x2="{cx}" y2="{lens_y-26}" stroke="#1d8a4a" stroke-width="3" marker-end="url(#g)"/>')
rows_ = ((8, "8 tiles  2.44 m", True), (7, "7 tiles  2.13 m", False), (5, "5 tiles  1.52 m", False))
for tiles, lab, old in rows_:
    y = ycol(1 + tiles)
    g.append(f'<rect x="{X0-4}" y="{y-16}" width="{W*F+8}" height="32" fill="#eaf7ee" stroke="#1d8a4a" stroke-width="1" rx="5" opacity="0.8"/>')
    for x in (xmid(1), cx, xmid(5)):
        g.append(X(x, y, "#1d8a4a", s=9, w=4 if not old else 3))
    g.append(f'<text x="{X0-10}" y="{y+4}" text-anchor="end" fill="#1d8a4a" font-weight="bold" font-size="12">{lab}</text>')
    g.append(f'<text x="{X0-10}" y="{y+17}" text-anchor="end" fill="#888" font-size="10">{"already taped" if old else "NEW tape: 3 X"}</text>')
g.append(f'<text x="{xmid(1)}" y="{ycol(9)-22}" text-anchor="middle" fill="#1d8a4a" font-weight="bold" font-size="11">LEFT</text>')
g.append(f'<text x="{cx}" y="{ycol(9)-22}" text-anchor="middle" fill="#1d8a4a" font-weight="bold" font-size="11">CENTRE</text>')
g.append(f'<text x="{xmid(5)}" y="{ycol(9)-22}" text-anchor="middle" fill="#1d8a4a" font-weight="bold" font-size="11">RIGHT</text>')
g.append(steps([
    ('h', 'Set up (10 min)'),
    ('g', 'Drone'), ('t', 'Same as the camera check: chair at the window end, middle column,'),
    ('t', 'lens ~2 ft 7½ in up, above the row 1 / row 2 line, facing the door.'), ('gap', ''),
    ('g', 'Tape: 6 NEW green X (3 are already there)'),
    ('t', 'Count tiles from the LENS toward the door. Each X goes on the'),
    ('t', 'tile line, in the MIDDLE of col 1, col 3 and col 5:'),
    ('t', '  5 tiles out  = the line where row 6 ends'),
    ('t', '  7 tiles out  = the line where row 8 ends'),
    ('t', '  8 tiles out  = already taped (row 9 line)'),
    ('t', 'The 7-tile CENTRE X sits ~3 in from the blue +x tape. Fine.'), ('gap', ''),
    ('g', 'Run it (drone battery in, WiFi "WiFi streaming example")'),
    ('code', 'zsh ~/Downloads/drone/pytorch_ssd/tools/real_frames/grid_capture.sh'),
    ('t', 'Clip 0: empty room, stay behind the drone.'),
    ('t', 'Clips 1-9: far row first (8, then 7, then 5 tiles), L / C / R.'),
    ('t', 'The laptop SAYS where to go and counts down. Face the drone,'),
    ('t', 'stand still until it says "Done". ~5 min on one battery.'), ('gap', ''),
    ('r', 'Then rejoin normal WiFi and send Claude the table it prints.'),
]))
g.append('</svg>')

import sys
out = sys.argv[1]
open(f'{out}/dorm_camera_check.svg', 'w').write('\n'.join(t))
open(f'{out}/dorm_lighthouse_tape.svg', 'w').write('\n'.join(u))
open(f'{out}/dorm_grid_capture.svg', 'w').write('\n'.join(g))
print("written; lens y", lens_y, "marks y", mark_y, "L/C/R x", xl, cx, xr, "origin y", oy, "+x y", xy)
