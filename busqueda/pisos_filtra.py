#!/usr/bin/env python3
"""Filtra pisos_details.json -> pisos_ok.json aplicando comision y reglas Marta."""
import json, re, os

HOME = os.path.dirname(os.path.abspath(__file__))

PM = 280000               # Pv = anuncio*0.85*(1+comisión) (+10k sin calefacción) ≤ 280.000€
NEGO = 0.9               # precio de compra = valor de mercado del anuncio × 0.85
E2 = 3800
Z = json.load(open(os.path.join(HOME, 'zona_final.json')))
CART = json.load(open(os.path.join(HOME, 'car_times.json')))
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
    if not best: return (None, None, None, None)
    _, rr, cc = best
    return Z['walk'][rr][cc], Z['tp'][rr][cc], Z['sta'][rr][cc], CART.get(f'{rr},{cc}')

d = json.load(open(os.path.join(HOME, 'pisos_details.json')))
ORI_WORD = re.compile(r'\b(noro?este|suro?este|sureste|noreste|norte|sur|este|oeste)\b', re.I)
ORI_CTX = re.compile(r'orientaci[oó]n[^.\n]{0,60}', re.I)
AC_RE = re.compile(r'aire\s+acondicionado|climatizaci[oó]n', re.I)
BAD_HOOD = re.compile(r'villaverde|usera|orcasitas|orcasur|san ferm[ií]n|almendrales|moscard[oó]|zof[ií]o|pradolongo|los [aá]ngeles|san andr[eé]s|butarque|los rosales|san crist[oó]bal', re.I)
AC_NEG = re.compile(r'\b(?:sin|no)\s+(?:aire\s+acondicionado|climatizaci[oó]n)|\bno\s+(?:tiene|dispone\s+de|cuenta\s+con)\s+(?:aire\s+acondicionado|climatizaci[oó]n)|\bpreinstalaci[oó]n[^.,;\n]{0,40}(?:aire\s+acondicionado|climatizaci[oó]n)', re.I)

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
    elif c.get('interior'): r = 'interior'
    elif (c.get('pics') or 0) < 2: r = 'fotos'
    elif oris & {'norte', 'noroeste'}: r = 'orient'
    elif BAD_HOOD.search(c.get('hood') or ''): r = 'barrio'
    else:
        ag = (c.get('agency') or '').lower()
        rate = 0.0484 if 'redpiso' in ag else (0.0363 if ag else 0.0)
        eff = c['price'] * NEGO * (1 + rate) + (0 if c.get('heat') else 10000) + c['price'] * NEGO * 0.06  # Pv +10k sin calefacción
        if eff > PM: r = 'precio-cal'
        elif c['price'] * NEGO * (1 + rate) / c['surface'] > E2: r = 'eurm2'  # €/m² sin calefacción
        else:
            fl = c['planta'] if c['planta'] is not None else c.get('floor')
            if fl is not None and fl >= 3 and not c.get('elev'): r = 'asc'
    if r: rej[r] = rej.get(r, 0) + 1
    else:
        dh_ac = AC_NEG.sub(' ', c.get('desc_head') or '')
        has_ac = bool(c.get('ac')) or bool(AC_RE.search(dh_ac))
        c['ac'] = has_ac
        w, t, s, car = zone_stats(c['lat'], c['lon'])
        c['score'] = 100 - (10 if 'oeste' in oris else 0) - (0 if c.get('heat') else 2) - (0 if has_ac else 5) \
            - (5 if (car or 0) >= 25 else (2 if (car or 0) > 20 else 0)) - (5 if (t or 0) > 35 else 0) \
            - (5 if (c['surface'] or 0) < 75 else (3 if (c['surface'] or 0) < 80 else 0)) - (0 if c.get('elev') else 5)
        c.update({'eff': eff, 'eurm2': round(c['price'] * NEGO * (1 + rate) / c['surface']),
                  'walk': w, 'tp': t, 'sta': s, 'car': car, 'oris': ' '.join(sorted(oris))})
        ok.append(c)
print('rejected:', rej)
print('OK:', len(ok))
json.dump(ok, open(os.path.join(HOME, 'pisos_ok.json'), 'w'), ensure_ascii=False)
