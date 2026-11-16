#!/usr/bin/env python3
"""Filtra pisos_details.json -> pisos_ok.json aplicando comision y reglas Marta."""
import json, re, os

PM = 260000 / 0.85          # 305.882 efectivo
E2 = 3800
D = os.path.dirname(os.path.abspath(__file__))
Z = json.load(open(os.path.join(D,'zona_final.json')))
lats, lons, zone = Z['lats'], Z['lons'], Z['zone']
nR, nC = len(lats), len(lons)
dlat = lats[1]-lats[0]; dlon = lons[1]-lons[0]

def zone_stats(lat, lon):
    r = int((lat-lats[0])/dlat); c = int((lon-lons[0])/dlon)
    best = None
    for dr in range(-2, 3):
        for dc in range(-2, 3):
            rr, cc = r+dr, c+dc
            if 0 <= rr < nR and 0 <= cc < nC and zone[rr][cc]:
                dd = dr*dr+dc*dc
                if best is None or dd < best[0]: best = (dd, rr, cc)
    if not best: return (None, None, None)
    _, rr, cc = best
    return Z['walk'][rr][cc], Z['tp'][rr][cc], Z['sta'][rr][cc]

d = json.load(open(os.path.join(D,'pisos_details.json')))
ORI_WORD = re.compile(r'\b(noro?este|suro?este|sureste|noreste|norte|sur|este|oeste)\b', re.I)
ORI_CTX = re.compile(r'orientaci[oó]n[^.\n]{0,60}', re.I)

def orientations(c):
    o = set(w.lower() for w in ORI_WORD.findall(c.get('ori') or ''))
    for m in ORI_CTX.finditer(c.get('desc_head') or ''):
        o.update(w.lower() for w in ORI_WORD.findall(m.group(0)))
    return o

rej, ok = {}, []
for c in d:
    r = None
    oris = orientations(c)
    if c.get('detail_err'): r = 'err'
    elif c.get('occ'): r = 'ocupada'
    elif c['planta'] is not None and c['planta'] == 0: r = 'bajo'
    elif oris & {'norte', 'noroeste'}: r = 'orient'
    else:
        ag = (c.get('agency') or '').lower()
        rate = 0.0484 if 'redpiso' in ag else (0.0363 if ag else 0.0)
        eff = c['price'] * (1 + rate)   # coste real: anuncio + comisión
        lim = PM - (0 if c.get('heat') else 10000) - (10000 if 'oeste' in oris else 0)
        if eff > lim: r = 'precio-cal'
        elif eff / c['surface'] > E2: r = 'eurm2'
        else:
            fl = c['planta'] if c['planta'] is not None else c.get('floor')
            if fl is not None and fl >= 3 and not c.get('elev'): r = 'asc'
    if r: rej[r] = rej.get(r, 0) + 1
    else:
        w, t, s = zone_stats(c['lat'], c['lon'])
        c.update({'walk': w, 'tp': t, 'sta': s, 'oris': ' '.join(sorted(oris))})
        ok.append(c)
print('rejected:', rej)
print('OK:', len(ok))
json.dump(ok, open(os.path.join(D,'pisos_ok.json'), 'w'), ensure_ascii=False)
