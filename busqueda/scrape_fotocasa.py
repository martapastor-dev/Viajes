#!/usr/bin/env python3
"""Scrape Fotocasa madrid-capital: filtros Marta + zona Hestia."""
import re, json, time, sys, math
import requests, os
from concurrent.futures import ThreadPoolExecutor

UA = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36'}
BASE = 'https://www.fotocasa.es'
PRICE_MAX = 322000               # crudo: 305.882/(1-4.84%) redpiso ≈ 321.438
EFF_PRICE_MAX = 260000/0.85      # 305.882 sobre precio efectivo
PENALTY_HEATING = 10000
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
        ring = poly[0]
        j = len(ring)-1
        for i in range(len(ring)):
            xi, yi = ring[i][0], ring[i][1]
            xj, yj = ring[j][0], ring[j][1]
            if (yi > lat) != (yj > lat) and lon < (xj-xi)*(lat-yi)/(yj-yi)+xi:
                inside = not inside
            j = i
        if inside:
            hole = False
            for h in poly[1:]:
                j = len(h)-1; inn = False
                for i in range(len(h)):
                    xi, yi = h[i][0], h[i][1]
                    xj, yj = h[j][0], h[j][1]
                    if (yi > lat) != (yj > lat) and lon < (xj-xi)*(lat-yi)/(yj-yi)+xi:
                        inn = not inn
                    j = i
                if inn: hole = True; break
            if not hole: return True
    return False

def cell(r, c):
    return zone[r][c] if 0 <= r < nR and 0 <= c < nC else False

def in_zone(lat, lon):
    """punto en zona: celda o sus 8 vecinas válidas (aprox) + dentro isócrona coche"""
    if not in_poly(lat, lon, CAR['geometry']): return False, 0
    r = int((lat-lats[0])/dlat); c = int((lon-lons[0])/dlon)
    for dr in (-1, 0, 1):
        for dc in (-1, 0, 1):
            if cell(r+dr, c+dc):
                # métricas de la celda válida más cercana
                return True, (abs(dr)+abs(dc))
    return False, 0

def zone_info(lat, lon):
    r = round((lat-lats[0])/dlat); c = round((lon-lons[0])/dlon)
    best = None
    for dr in range(-2, 3):
        for dc in range(-2, 3):
            rr, cc = r+dr, c+dc
            if 0 <= rr < nR and 0 <= cc < nC and zone[rr][cc]:
                dd = dr*dr+dc*dc
                if best is None or dd < best[0]:
                    best = (dd, rr, cc)
    if best:
        _, rr, cc = best
        return Z['walk'][rr][cc], Z['tp'][rr][cc], Z['sta'][rr][cc]
    return None

BAD_SUBTYPES = {'GROUND_FLOOR', 'SEMI_BASEMENT', 'BASEMENT', 'GROUND_FLOOR_WITH_GARDEN'}
BAD_WORDS = re.compile(r'\b(okupad|nuda propiedad|usufructo|inquilino|alquilad[ao]\b|ocupad[ao]\b|rentabilidad|inversi[oó]n)\b', re.I)
BAJO_WORDS = re.compile(r'\b(planta baja|bajo\b|semis[oó]tano|s[oó]tano)\b', re.I)
FLOOR_RE = re.compile(r'(\d+)[ªº]?\s*planta|planta\s*(\d+)|en\s+(?:la\s+)?planta\s+(\d+)', re.I)
ATICO = re.compile(r'\b[aá]tico\b', re.I)

def feat(it, key):
    for f in it.get('titleFeatures', []) + it.get('features', []):
        if f['key'] == key: return f['value']
    return None

def floor_from(it):
    """planta: de buildingSubtype/description/ubicacion; None si desconocida"""
    sub = it.get('propertySubtype', '')
    desc = (it.get('description') or '')
    title_loc = (it.get('titleLocation') or '') + ' ' + (it.get('subtitleLocation') or '')
    txt = title_loc + '\n' + desc + ' ' + (it.get('detail', {}).get('es-ES') or '').replace('-', ' ')
    if sub in ('GROUND_FLOOR', 'SEMI_BASEMENT', 'BASEMENT') or 'GroundFloor' in (it.get('buildingSubtype') or ''):
        return 0
    if ATICO.search(txt):
        m = FLOOR_RE.search(txt)
        return int(next(g for g in m.groups() if g)) if m else 9
    m = FLOOR_RE.search(txt)
    if m:
        return int(next(g for g in m.groups() if g))
    if BAJO_WORDS.search(txt):
        return 0
    if 'EXTERIOR' in sub or 'INTERMEDIATE' in sub:
        return None  # planta intermedia desconocida (1+)
    return None

out, seen = [], set()
sess = requests.Session(); sess.headers.update(UA)

def fetch_page(page):
    url = f'{BASE}/es/comprar/viviendas/madrid-capital/todas-las-zonas/l/{page}?maxPrice={int(PRICE_MAX)}&minSurface={SURF_MIN}&sortType=publicationDate&sortOrderDesc=true'
    for attempt in range(3):
        try:
            r = sess.get(url, timeout=30)
            if r.status_code != 200:
                time.sleep(2 * (attempt + 1)); continue
            m = re.search(r'<script type="application/json" id="__initial_props__">(.*?)</script>', r.text, re.S)
            if not m:
                time.sleep(2 * (attempt + 1)); continue
            res = json.loads(m.group(1))['initialSearch']['result']
            return page, res['count'], res.get('resultsV2', {}).get('items') or []
        except Exception as e:
            if attempt == 2: print('err page', page, e)
            time.sleep(2 * (attempt + 1))
    return page, None, []

page = 1
_, count, items = fetch_page(1)
if count is None:
    sys.exit('página 1 de fotocasa falló — no se sobreescribe fc_raw.json')
print('total', count)
npages = math.ceil(count/31)
with ThreadPoolExecutor(max_workers=6) as ex:
    results = [(1, count, items)] + list(ex.map(fetch_page, range(2, npages + 1)))
failed = [p for p, c, _ in results if c is None]
if failed:
    sys.exit(f'páginas fallidas tras reintentos: {failed} — no se sobreescribe fc_raw.json')
pages_items = [its for _, _, its in results]
for items in pages_items:
    for it in items:
        iid = it['id']
        if iid in seen: continue
        seen.add(iid)
        co = (it.get('address') or {}).get('coordinates') or {}
        lat, lon = co.get('lat'), co.get('lng')
        rec = {
            'id': iid, 'price': it.get('rawPrice') or it.get('price'),
            'lat': lat, 'lon': lon,
            'subtype': it.get('propertySubtype'),
            'occupied': it.get('isOccupied'), 'bare': it.get('isBareOwnership'),
            'rented': it.get('isRentedWithTenants'), 'auction': it.get('isAuctioned'),
            'surface': feat(it, 'surface'), 'rooms': feat(it, 'rooms'),
            'heating': feat(it, 'heating'), 'elevator': feat(it, 'elevator'),
            'floorfeat': feat(it, 'floor'),
            'hood': (it.get('address') or {}).get('neighborhood'),
            'dist': (it.get('address') or {}).get('municipality'),
            'ubic': (it.get('address') or {}).get('ubication'),
            'agency': it.get('clientAlias'), 'clientType': it.get('clientType'),
            'url': BASE + (it.get('detail', {}).get('es-ES') or ''),
            'desc': (it.get('description') or ''),
        }
        out.append(rec)

print('listings:', len(out))
json.dump(out, open(os.path.join(D,'fc_raw.json'), 'w'), ensure_ascii=False)
