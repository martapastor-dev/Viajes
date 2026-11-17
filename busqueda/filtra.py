#!/usr/bin/env python3
import json, re, math, os

PRICE_MAX = 280000  # Pv = anuncio*0.85*(1+comisión) (+10k sin calefacción) ≤ 280.000€
NEGO = 0.9         # precio de compra = valor de mercado del anuncio × 0.85
EURM2_MAX = 3800
SURF_MIN = 70

D = os.path.dirname(os.path.abspath(__file__))
Z = json.load(open(os.path.join(D,'zona_final.json')))
CAR = json.load(open(os.path.join(D,'coche25.json')))
CART = json.load(open(os.path.join(D,'car_times.json')))
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
    return Z['walk'][rr][cc], Z['tp'][rr][cc], Z['sta'][rr][cc], CART.get(f'{rr},{cc}')

FLOOR_MAP = {1: -1, 2: -1, 3: 0, 4: 0.5, 5: 0.5, 6: 1, 7: 2, 8: 3, 9: 4, 10: 5,
             11: 6, 12: 7, 13: 8, 14: 9, 15: 10, 21: 11}
BAD_SUB = {'GROUND_FLOOR', 'SEMI_BASEMENT', 'BASEMENT'}
LOW_RE = re.compile(r'planta\s+baja|\bbajo\b|semis[oó]tano|s[oó]tano', re.I)
NO_POSES = re.compile(r'okupad|(?<!des)(?<!no )ocupad|nuda propiedad|usufruct|sin posesión|no se puede visitar|(?<!sin )(?<!libre de )inquilinos?|no se (entrega|vende)[^.,;\n]{0,40}inquilinos?|alquilad[ao]\b|vivienda alquilada|\b\d+\s*[,%]?\s*(de la )?propiedad|subasta|para inversores|inversi[oó]n\b|rentabilidad', re.I)
FLOOR_TXT = re.compile(r'(primer|segund|tercer|cuart|quint|sext|s[eé]ptim|octav|noven|d[eé]cim)[ao]?\s+planta|planta\s+(\d+)|(\d+)[ªº]\s*planta', re.I)
ORD = {'primer':1,'segund':2,'tercer':3,'cuart':4,'quint':5,'sext':6,'séptim':7,'septim':7,'octav':8,'noven':9,'décim':10,'decim':10}
ENTREPLANTA = re.compile(r'entreplanta|entresuelo', re.I)

ORI_MAP = {1: 'norte', 2: 'noroeste', 3: 'noreste', 4: 'sur', 5: 'sureste',
           6: 'suroeste', 7: 'este', 8: 'oeste'}
ORI_WORD = re.compile(r'\b(noro?este|suro?este|sureste|noreste|norte|sur|este|oeste)\b', re.I)
ORI_CTX = re.compile(r'orientaci[oó]n[^.\n]{0,60}', re.I)
AC_RE = re.compile(r'aire\s+acondicionado|climatizaci[oó]n', re.I)
HEAT_RE = re.compile(r'calefacci[oó]n|radiadores|suelo\s+radiante|aerotermia|\bcaldera\b', re.I)
HEAT_NEG = re.compile(r'\b(?:sin|no)\s+(?:calefacci[oó]n|radiadores|suelo\s+radiante)|\bno\s+(?:tiene|dispone\s+de|cuenta\s+con|hay)\s+(?:calefacci[oó]n|radiadores|suelo\s+radiante)|\bpreinstalaci[oó]n\s+(?:de\s+|para\s+)?(?:calefacci[oó]n|radiadores|suelo\s+radiante)', re.I)
AC_NEG = re.compile(r'\b(?:sin|no)\s+(?:aire\s+acondicionado|climatizaci[oó]n)|\bno\s+(?:tiene|dispone\s+de|cuenta\s+con)\s+(?:aire\s+acondicionado|climatizaci[oó]n)|\bpreinstalaci[oó]n[^.,;\n]{0,40}(?:aire\s+acondicionado|climatizaci[oó]n)', re.I)
INTERIOR = re.compile(r'\b(?:vivienda|piso|casa|estudio|[aá]tico|d[uú]plex|inmueble|apartamento)\s+interior\b|\binterior\b\s+(?:muy\s+)?(?:luminoso|soleado|tranquilo|pero)|orientaci[oó]n\s+interior\b|\b\d+[ªº]?\s*interior\b|\binterior\s+con\s+ascensor\b|\bes\s+interior\b|,\s*interior\b(?!\s+de\b)', re.I)
INT_NEG = re.compile(r'(?:patio|escalera|portal|carpintería|carpinteria|armario|pasillo|vestíbulo|vestibulo|zona|acceso|visitas?)\s+interior|\bno\s+(?:es|sea|parece|es\s+una|es\s+un)\s+interior|(?:acceso|entrada|visitas?|zona)\s+(?:al\s+)?interior\s+del?\s+(?:edificio|portal|inmueble|bloque)|uso\s+interior|interiormente|interiorismo', re.I)

def orientations(r):
    o = set()
    if r.get('ori'):
        n = ORI_MAP.get(int(r['ori']))
        if n: o.add(n)
    d = r['desc'] or ''
    for m in ORI_CTX.finditer(d):
        o.update(w.lower() for w in ORI_WORD.findall(m.group(0)))
    return o

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
rejects = {'zona':0,'precio':0,'m2':0,'sup':0,'bajo':0,'ocup':0,'asc':0,'orient':0,'interior':0,'fotos':0}
for r in L:
    why = []
    if not in_zone(r['lat'], r['lon']):
        rejects['zona'] += 1; continue
    price = r['price'] or 0
    ag = (r.get('agency') or '').lower()
    if r.get('clientType') != 'professional' and not ag: rate = 0.0
    elif 'redpiso' in ag: rate = 0.0484
    else: rate = 0.0363
    has_heat = r['heating'] == 1 or bool(HEAT_RE.search(HEAT_NEG.sub(' ', r['desc'] or '')))
    eff = price * NEGO * (1 + rate) + (0 if has_heat else 10000) + price * NEGO * 0.06  # Pv: compra negociada + comisión (+10k sin calefacción)
    surf = r['surface']
    if surf is None or surf < SURF_MIN: rejects['sup'] += 1; continue
    eurm2 = price * NEGO * (1 + rate) / surf  # €/m² sobre Pv sin calefacción
    d_ac = AC_NEG.sub(' ', r['desc'] or '')  # quita menciones negadas, conserva las positivas
    has_ac = r.get('ac') == 1 or bool(AC_RE.search(d_ac))
    oris = orientations(r)
    if oris & {'norte', 'noroeste'}: rejects['orient'] += 1; continue
    if INTERIOR.search(INT_NEG.sub(' ', r['desc'] or '')): rejects['interior'] += 1; continue
    if (r.get('pics') or 0) < 2: rejects['fotos'] += 1; continue
    if eff > PRICE_MAX: rejects['precio'] += 1; continue
    if eurm2 > EURM2_MAX: rejects['m2'] += 1; continue
    if r['subtype'] in BAD_SUB: rejects['bajo'] += 1; continue
    fl = floor_of(r)
    if fl is not None and fl < 1: rejects['bajo'] += 1; continue
    if r['occupied'] or r['bare'] or r['rented'] or r['auction'] or NO_POSES.search(r['desc'] or ''):
        rejects['ocup'] += 1; continue
    has_elev = r['elevator'] == 1
    if fl is not None and fl >= 3 and not has_elev:
        rejects['asc'] += 1; continue
    zs = zone_stats(r['lat'], r['lon']) or (None, None, None, None)
    score = 100 - (10 if 'oeste' in oris else 0) - (0 if has_heat else 2) - (0 if has_ac else 5) \
        - (5 if (zs[3] or 0) >= 25 else (2 if (zs[3] or 0) > 20 else 0)) - (5 if (zs[1] or 0) > 35 else 0) \
        - (5 if surf < 75 else (3 if surf < 80 else 0)) - (0 if has_elev else 5)
    ok.append({**r, 'eff': round(eff), 'rate': rate, 'eurm2': round(eurm2), 'floor': fl, 'elev': has_elev, 'heat': has_heat,
               'ac': has_ac, 'score': score,
               'oris': ' '.join(sorted(oris)), 'walk': zs[0], 'tp': zs[1], 'sta': zs[2], 'car': zs[3]})

ok.sort(key=lambda x: x['eurm2'])
print('rejects:', rejects)
print('OK:', len(ok))
json.dump(ok, open(os.path.join(D,'fc_ok.json'), 'w'), ensure_ascii=False, indent=1)
for r in ok:
    print(f"{r['price']:>8,.0f}€ {r['surface']:>3}m² {r['eurm2']:>5}€/m² p{r['floor']} asc={int(r['elev'])} cal={int(r['heat'])} w{r['walk'] and round(r['walk'])} tp{r['tp'] and round(r['tp'])} [{r['hood']}] {r['url']}")
