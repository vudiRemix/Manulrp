#!/usr/bin/env python3
"""Make the Manulcraft pack work on every client 1.19.2 .. 26.x (and Horizon).

usage: fix_pack.py <extracted pack dir>

1. Models: ItemsAdder sprite aliases "ia:N" -> real texture paths.
   Clients without atlas overlays (1.19.2-1.20.1) and Horizon can't resolve ia:N.
   Every atlas that registers ia:N also registers the real path, so modern
   clients see exactly the same sprites.
2. Model element rotations in the 1.21.11+ syntax (x/y/z form, angles other
   than 0/±22.5/±45) -> legacy syntax that every version reads.
3. PNG -> 8-bit RGBA (Horizon can't read palette/RGB/16-bit font sheets).
4. pack.mcmeta: declare support from format 9 (1.19.2).
"""
import json, os, sys, re
from PIL import Image

root = sys.argv[1]
os.chdir(root)
stats = {}
def bump(k, n=1): stats[k] = stats.get(k, 0) + n

def load(p):
    with open(p, encoding='utf-8') as f: return json.load(f)
def dump(p, d):
    with open(p, 'w', encoding='utf-8') as f: json.dump(d, f, ensure_ascii=False, separators=(',', ':'))

layers = ['.'] + sorted(d for d in os.listdir('.') if os.path.isdir(os.path.join(d, 'assets')) and d != 'assets')

# ---------- 1. sprite alias map
alias = {}
atlas_files = []
for L in layers:
    for name in ('blocks.json', 'items.json'):
        p = os.path.join(L, 'assets/minecraft/atlases', name)
        if os.path.exists(p):
            atlas_files.append(p)
            for s in load(p)['sources']:
                if s.get('type') == 'single' and str(s.get('sprite', '')).startswith('ia:'):
                    r = s['resource']
                    if ':' not in r: r = 'minecraft:' + r
                    assert alias.get(s['sprite'], r) == r, s
                    alias[s['sprite']] = r

def tex_exists(res):
    ns, path = res.split(':', 1)
    return any(os.path.exists(os.path.join(L, 'assets', ns, 'textures', path + '.png')) for L in layers)

missing_alias = set()
for L in layers:
    for dp, dn, fn in os.walk(os.path.join(L, 'assets') if L != '.' else 'assets'):
        if '/models' not in dp.replace('\\', '/'): continue
        for f in fn:
            if not f.endswith('.json'): continue
            p = os.path.join(dp, f)
            d = load(p)
            if not isinstance(d, dict): continue
            ch = False
            t = d.get('textures')
            if isinstance(t, dict):
                for k, v in t.items():
                    if isinstance(v, str) and v.startswith('ia:'):
                        if v in alias:
                            t[k] = alias[v]; ch = True; bump('tex refs rewritten')
                        else:
                            missing_alias.add(v)
            # 2. rotations
            for el in d.get('elements') or []:
                r = el.get('rotation')
                if not isinstance(r, dict): continue
                if 'axis' not in r and any(a in r for a in 'xyz'):
                    nz = [(a, r.get(a, 0)) for a in 'xyz' if r.get(a, 0)]
                    assert len(nz) <= 1, (p, r)
                    axis, ang = nz[0] if nz else ('y', 0)
                    el['rotation'] = r = {'angle': ang, 'axis': axis, 'origin': r.get('origin', [8, 8, 8]),
                                          **({'rescale': r['rescale']} if 'rescale' in r else {})}
                    ch = True; bump('rotations xyz->axis')
                a = r.get('angle', 0)
                if a in (90, -90, 180, -180) :
                    # exact: rotate the box itself, drop the rotation
                    ax = r['axis']; o = r['origin']
                    i, j = {'x': (1, 2), 'y': (2, 0), 'z': (0, 1)}[ax]
                    s = 1 if a == 90 else -1
                    def rot(pt, times):
                        pt = list(pt)
                        for _ in range(times):
                            u, v = pt[i] - o[i], pt[j] - o[j]
                            u, v = (-v, u) if s == 1 else (v, -u)
                            pt[i], pt[j] = u + o[i], v + o[j]
                        return pt
                    n = 2 if abs(a) == 180 else 1
                    p1, p2 = rot(el['from'], n), rot(el['to'], n)
                    el['from'] = [round(min(x, y), 5) for x, y in zip(p1, p2)]
                    el['to'] = [round(max(x, y), 5) for x, y in zip(p1, p2)]
                    # face directions move with the box
                    vec = {'east': (1, 0, 0), 'west': (-1, 0, 0), 'up': (0, 1, 0), 'down': (0, -1, 0), 'south': (0, 0, 1), 'north': (0, 0, -1)}
                    inv = {v: k for k, v in vec.items()}
                    faces = el.get('faces', {})
                    nf = {}
                    for fname, fd in faces.items():
                        nv = rot(vec[fname], n) if False else None
                        v = list(vec[fname])
                        for _ in range(n):
                            u, w = v[i], v[j]
                            v[i], v[j] = (-w, u) if s == 1 else (w, -u)
                        nf[inv[tuple(v)]] = fd
                    el['faces'] = nf
                    del el['rotation']
                    ch = True; bump('rotations ±90 baked')
                elif a not in (0, 22.5, -22.5, 45, -45):
                    r['angle'] = min((0, 22.5, -22.5, 45, -45), key=lambda x: abs(x - a))
                    ch = True; bump('rotations snapped')
            if ch: dump(p, d)

# atlases: replace every ia:N alias with its real path (nothing references ia:N any more)
for p in atlas_files + ['assets/minecraft/atlases/blocks.json']:
    if not os.path.exists(p): continue
    d = load(p); src = d['sources']
    dirs = [s['source'].rstrip('/') + '/' for s in src if s.get('type') == 'directory' and 'source' in s]
    norm = lambda r: r if ':' in r else 'minecraft:' + r
    out = []; seen = set()
    for s in src:
        if s.get('type') == 'single':
            if str(s.get('sprite', '')).startswith('ia:'):
                s = {'type': 'single', 'resource': alias[s['sprite']]}
            if not s.get('sprite'):
                r = norm(s['resource'])
                if r in seen or any(r.split(':', 1)[1].startswith(dd) for dd in dirs): continue
                seen.add(r)
        out.append(s)
    if p == 'assets/minecraft/atlases/blocks.json':   # base atlas is what 1.19.3-1.20.1 use
        for r in sorted(set(alias.values())):
            if r not in seen and not any(r.split(':', 1)[1].startswith(dd) for dd in dirs):
                out.append({'type': 'single', 'resource': r}); seen.add(r)
    bump('atlas sources %d->%d' % (len(src), len(out)))
    d['sources'] = out; dump(p, d)

# ---------- 4. pack.mcmeta
mc = load('pack.mcmeta')
pk = mc['pack']
pk['supported_formats'] = [9, 9999]
pk['min_format'] = 9
pk['max_format'] = 9999
existing = [e for e in mc['overlays']['entries'] if os.path.isdir(e['directory'])]
bump('overlay entries dropped (dir missing)', len(mc['overlays']['entries']) - len(existing))
mc['overlays']['entries'] = existing
with open('pack.mcmeta', 'w', encoding='utf-8') as f: json.dump(mc, f, ensure_ascii=False, indent=2)

print(json.dumps(stats, ensure_ascii=False, indent=1))
print('ia ids without mapping:', sorted(missing_alias)[:20], len(missing_alias))
