#!/usr/bin/env python3
"""Filtra pisos_details.json -> pisos_ok.json aplicando comision y reglas Marta."""
import json, re, os, sys

HOME = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HOME)
from params import load as _pload, effective as _eff, bad_hood_fn, rej_orient, norm, reglas as _reglas, regla_pen_y_drop, util_of

P = _eff(_pload())
PM = P['precio_max']
NEGO = P['nego']
ITP = P['itp']
COM_RED = P['com_redpiso']
COM_AG = P['com_agencia']
EXTRA_CAL = P['extra_sin_cal']
E2 = P['eurm2_max']
BAD_HOOD_FN = bad_hood_fn(P)
REJ_ORI = rej_orient(P)
REGLAS = _reglas(P)
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
    if not best: return (None, None, None, None, None)
    _, rr, cc = best
    return Z['walk'][rr][cc], Z['tp'][rr][cc], Z['sta'][rr][cc], CART.get(f'{rr},{cc}'), Z.get('tpb', [[None]*nC for _ in range(nR)])[rr][cc]

def in_poly(lat, lon, geom):
    polys = geom['coordinates'] if geom['type'] == 'MultiPolygon' else [geom['coordinates']]
    for poly in polys:
        inside = False
        ring = poly[0]; j = len(ring)-1
        for i in range(len(ring)):
            xi, yi = ring[i][0], ring[i][1]
            xj, yj = ring[j][0], ring[j][1]
            if (yi > lat) != (yj > lat) and lon < (xj-xi)*(lat-yi)/(yj-yi)+xi:
                inside = not inside
            j = i
        if inside:
            for h in poly[1:]:
                j = len(h)-1; inn = False
                for i in range(len(h)):
                    xi, yi = h[i][0], h[i][1]
                    xj, yj = h[j][0], h[j][1]
                    if (yi > lat) != (yj > lat) and lon < (xj-xi)*(lat-yi)/(yj-yi)+xi:
                        inn = not inn
                    j = i
                if inn: return False
            return True
    return False

CAR = json.load(open(os.path.join(HOME, 'coche25.json')))

def in_zone(lat, lon):
    if lat is None or lon is None: return False
    if not in_poly(lat, lon, CAR['geometry']): return False
    r = int((lat-lats[0])/dlat); c = int((lon-lons[0])/dlon)
    for dr in (-1, 0, 1):
        for dc in (-1, 0, 1):
            rr, cc = r+dr, c+dc
            if 0 <= rr < nR and 0 <= cc < nC and zone[rr][cc]:
                return True
    return False

d = []
for _f, _src in [('pisos_details.json', 'Pisos'), ('tc_details.json', 'Tecnocasa'), ('hab_details.json', 'Habitaclia'), ('idealista_details.json', 'Idealista')]:
    _p = os.path.join(HOME, _f)
    if os.path.exists(_p):
        for _c in json.load(open(_p)):
            _c['src'] = _src
            d.append(_c)
ORI_WORD = re.compile(r'\b(noro?este|suro?este|sureste|noreste|norte|sur|este|oeste)\b', re.I)
ORI_CTX = re.compile(r'orientaci[oó]n[^.\n]{0,60}', re.I)
AC_RE = re.compile(r'aire\s+acondicionado|climatizaci[oó]n', re.I)
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
    elif not in_zone(c.get('lat'), c.get('lon')): r = 'zona'
    elif P['no_ocupadas'] and c.get('occ'): r = 'ocupada'
    elif P['no_bajos'] and c.get('planta') is not None and c.get('planta') == 0: r = 'bajo'
    elif P['no_interiores'] and c.get('interior'): r = 'interior'
    elif (c.get('pics') or 0) < P['min_fotos']: r = 'fotos'
    elif (c.get('surface') or 0) < P['m2_min'] or (util_of(c.get('desc_head')) or P['util_min']) < P['util_min']: r = 'sup'
    elif REJ_ORI and oris & REJ_ORI: r = 'orient'
    elif BAD_HOOD_FN(c.get('hood')): r = 'barrio'
    elif regla_pen_y_drop(REGLAS, norm(c.get('desc_head') or ''), norm(c.get('hood') or ''))[1]: r = 'regla'
    else:
        ag = (c.get('agency') or '').lower()
        rate = COM_RED if 'redpiso' in ag else (COM_AG if ag else 0.0)
        eff = c['price'] * NEGO * (1 + rate) + (0 if c.get('heat') else EXTRA_CAL) + c['price'] * NEGO * ITP  # Pv + ITP (+extra sin calefacción)
        if eff > PM: r = 'precio-cal'
        elif c['price'] * NEGO * (1 + rate) / c['surface'] > E2: r = 'eurm2'  # €/m² sin calefacción ni ITP
        else:
            fl = c.get('planta') if c.get('planta') is not None else c.get('floor')
            if fl is not None and fl >= P['ascensor_desde'] and not c.get('elev'): r = 'asc'
    if r: rej[r] = rej.get(r, 0) + 1
    else:
        dh_ac = AC_NEG.sub(' ', c.get('desc_head') or '')
        has_ac = bool(c.get('ac')) or bool(AC_RE.search(dh_ac))
        c['ac'] = has_ac
        w, t, s, car, tb = zone_stats(c['lat'], c['lon'])
        c['score'] = 100 - (P['sc_oeste'] if 'oeste' in oris else 0) - (0 if c.get('heat') else P['sc_sin_cal']) - (0 if has_ac else P['sc_sin_aire']) \
            - (P['sc_car_25'] if (car or 0) >= P['car_u1'] else (P['sc_car_20'] if (car or 0) > P['car_u2'] else 0)) \
            - (P['sc_tp_35'] if (t or 0) > P['tp_u'] else 0) \
            - (P['sc_m2_75'] if (c['surface'] or 0) < P['m2_u1'] else (P['sc_m2_80'] if (c['surface'] or 0) < P['m2_u2'] else 0)) - (0 if c.get('elev') else P['sc_sin_asc']) \
            - regla_pen_y_drop(REGLAS, norm(c.get('desc_head') or ''), norm(c.get('hood') or ''))[0]
        c.update({'eff': eff, 'eurm2': round(c['price'] * NEGO * (1 + rate) / c['surface']),
                  'walk': w, 'tp': t, 'sta': s, 'car': car, 'tpb': tb, 'oris': ' '.join(sorted(oris))})
        ok.append(c)
print('rejected:', rej)
print('OK:', len(ok))
json.dump(ok, open(os.path.join(HOME, 'pisos_ok.json'), 'w'), ensure_ascii=False)
