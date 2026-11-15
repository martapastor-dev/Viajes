#!/usr/bin/env python3
import json, re, math, os

PRICE_MAX = 260000/0.85  # sobre el coste real (anuncio + comisión)          # 305.882,35
EURM2_MAX = 3800
SURF_MIN = 70

D = os.path.dirname(os.path.abspath(__file__))
Z = json.load(open(os.path.join(D,'zona_final.json')))
CAR = json.load(open(os.path.join(D,'coche25.json')))
lats, lons, zone = Z['lats'], Z['lons'], Z['zone']
nR, nC = len(lats), len(lons)
dlat = lats[1]-lats[0]; dlon = lons[1]-lons[0]

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

def zone_stats(lat, lon):
    r = int((lat-lats[0])/dlat); c = int((lon-lons[0])/dlon)
    best = None
    for dr in range(-2, 3):
        for dc in range(-2, 3):
            rr, cc = r+dr, c+dc
            if 0 <= rr < nR and 0 <= cc < nC and zone[rr][cc]:
                dd = dr*dr+dc*dc
                if best is None or dd < best[0]: best = (dd, rr, cc)
    if not best: return None
    _, rr, cc = best
    return Z['walk'][rr][cc], Z['tp'][rr][cc], Z['sta'][rr][cc]

FLOOR_MAP = {1: -1, 2: -1, 3: 0, 4: 0.5, 5: 0.5, 6: 1, 7: 2, 8: 3, 9: 4, 10: 5,
             11: 6, 12: 7, 13: 8, 14: 9, 15: 10, 21: 11}
BAD_SUB = {'GROUND_FLOOR', 'SEMI_BASEMENT', 'BASEMENT'}
LOW_RE = re.compile(r'planta\s+baja|\bbajo\b|semis[oó]tano|s[oó]tano', re.I)
NO_POSES = re.compile(r'okupad|(?<!des)(?<!no )ocupad|nuda propiedad|usufruct|sin posesión|no se puede visitar|(?<!sin )inquilinos?|alquilad[ao]\b|vivienda alquilada|\b\d+\s*[,%]?\s*(de la )?propiedad|subasta|para inversores|inversi[oó]n\b|rentabilidad', re.I)
FLOOR_TXT = re.compile(r'(primer|segund|tercer|cuart|quint|sext|s[eé]ptim|octav|noven|d[eé]cim)[ao]?\s+planta|planta\s+(\d+)|(\d+)[ªº]\s*planta', re.I)
ORD = {'primer':1,'segund':2,'tercer':3,'cuart':4,'quint':5,'sext':6,'séptim':7,'septim':7,'octav':8,'noven':9,'décim':10,'decim':10}
ENTREPLANTA = re.compile(r'entreplanta|entresuelo', re.I)

def floor_of(r):
    f = FLOOR_MAP.get(r['floorfeat'])
    d = r['desc'] or ''
    m = FLOOR_TXT.search(d)
    txt = None
    if m:
        txt = ORD.get(m.group(1).lower()) if m.group(1) else int(m.group(2) or m.group(3))
    if f is not None: return f
    if txt is not None: return txt
    if ENTREPLANTA.search(d): return 0.5
    if r['subtype'] in BAD_SUB or LOW_RE.search(d): return 0
    return None

L = json.load(open(os.path.join(D,'fc_raw.json')))
ok, out = [], []
rejects = {'zona':0,'precio':0,'m2':0,'sup':0,'bajo':0,'ocup':0,'asc':0}
for r in L:
    why = []
    if not in_zone(r['lat'], r['lon']):
        rejects['zona'] += 1; continue
    price = r['price'] or 0
    ag = (r.get('agency') or '').lower()
    if r.get('clientType') != 'professional' and not ag: rate = 0.0
    elif 'redpiso' in ag: rate = 0.0484
    else: rate = 0.0363
    eff = price * (1 + rate)          # coste real: anuncio + comisión que paga Marta
    surf = r['surface']
    if surf is None or surf < SURF_MIN: rejects['sup'] += 1; continue
    eurm2 = eff/surf
    has_heat = r['heating'] == 1
    pmax = PRICE_MAX - (0 if has_heat else 10000)
    if eff > pmax: rejects['precio'] += 1; continue
    if eurm2 > EURM2_MAX: rejects['m2'] += 1; continue
    if r['subtype'] in BAD_SUB: rejects['bajo'] += 1; continue
    fl = floor_of(r)
    if fl is not None and fl < 1: rejects['bajo'] += 1; continue
    if r['occupied'] or r['bare'] or r['rented'] or r['auction'] or NO_POSES.search(r['desc'] or ''):
        rejects['ocup'] += 1; continue
    has_elev = r['elevator'] == 1
    if fl is not None and fl >= 3 and not has_elev:
        rejects['asc'] += 1; continue
    zs = zone_stats(r['lat'], r['lon']) or (None, None, None)
    ok.append({**r, 'eff': round(eff), 'rate': rate, 'eurm2': round(eurm2), 'floor': fl, 'elev': has_elev, 'heat': has_heat,
               'walk': zs[0], 'tp': zs[1], 'sta': zs[2]})

ok.sort(key=lambda x: x['eurm2'])
print('rejects:', rejects)
print('OK:', len(ok))
json.dump(ok, open(os.path.join(D,'fc_ok.json'), 'w'), ensure_ascii=False, indent=1)
for r in ok:
    print(f"{r['price']:>8,.0f}€ {r['surface']:>3}m² {r['eurm2']:>5}€/m² p{r['floor']} asc={int(r['elev'])} cal={int(r['heat'])} w{r['walk'] and round(r['walk'])} tp{r['tp'] and round(r['tp'])} [{r['hood']}] {r['url']}")
