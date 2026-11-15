#!/usr/bin/env python3
"""Scrape pisos.com madrid_capital list pages en paralelo; keep zone+price+size candidates."""
import re, json
import requests, os
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor

UA = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36'}
BASE = 'https://www.pisos.com'
LIST = BASE + '/venta/pisos-madrid_capital_zona_urbana/{}/'
PRICE_MAX = 322000   # crudo; el efectivo se filtra despues con comision
SURF_MIN = 70
MAXPAGES = 320

D = os.path.dirname(os.path.abspath(__file__))
Z = json.load(open(os.path.join(D,'zona_final.json')))
CAR = json.load(open(os.path.join(D,'coche25.json')))
lats, lons, zone = Z['lats'], Z['lons'], Z['zone']
nR, nC = len(lats), len(lons)
dlat = lats[1] - lats[0]; dlon = lons[1] - lons[0]

def in_poly(lat, lon, geom):
    polys = geom['coordinates'] if geom['type'] == 'MultiPolygon' else [geom['coordinates']]
    for poly in polys:
        inside = False
        ring = poly[0]; j = len(ring) - 1
        for i in range(len(ring)):
            xi, yi = ring[i][0], ring[i][1]
            xj, yj = ring[j][0], ring[j][1]
            if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi) + xi:
                inside = not inside
            j = i
        if inside:
            for h in poly[1:]:
                j = len(h) - 1; inn = False
                for i in range(len(h)):
                    xi, yi = h[i][0], h[i][1]
                    xj, yj = h[j][0], h[j][1]
                    if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi) + xi:
                        inn = not inn
                    j = i
                if inn: return False
            return True
    return False

def in_zone(lat, lon):
    if lat is None or lon is None: return False
    if not in_poly(lat, lon, CAR['geometry']): return False
    r = int((lat - lats[0]) / dlat); c = int((lon - lons[0]) / dlon)
    for dr in (-1, 0, 1):
        for dc in (-1, 0, 1):
            rr, cc = r + dr, c + dc
            if 0 <= rr < nR and 0 <= cc < nC and zone[rr][cc]:
                return True
    return False

sess = requests.Session(); sess.headers.update(UA)

def fetch_page(page):
    try:
        r = sess.get(LIST.format(page), timeout=30)
        if r.status_code != 200: return page, []
        soup = BeautifulSoup(r.text, 'html.parser')
        cards = soup.select('div.ad-preview')
        geo = {}
        for l in soup.find_all('script', type='application/ld+json'):
            try:
                j = json.loads(l.string or l.get_text())
                g = j.get('geo') or {}
                if g.get('latitude'):
                    geo[j['@id']] = (float(str(g['latitude']).replace(',', '.')),
                                     float(str(g['longitude']).replace(',', '.')))
            except Exception:
                pass
        out = []
        for c in cards:
            iid = c.get('id', '')
            link = BASE + (c.get('data-lnk-href') or '')
            mpr = re.search(r'([\d.]+)\s*€', c.select_one('.ad-preview__price').get_text() if c.select_one('.ad-preview__price') else '')
            price = int(mpr.group(1).replace('.', '')) if mpr else None
            chars = [e.get_text(strip=True) for e in c.select('.ad-preview__char')]
            surf = None; floor = None
            for ch in chars:
                m2 = re.match(r'([\d.]+)\s*m²', ch)
                mf = re.match(r'(\d+)[ªº]\s*planta', ch)
                if m2: surf = int(m2.group(1).replace('.', ''))
                if mf: floor = int(mf.group(1))
                if re.match(r'(?i)bajo|s[oó]tano|entreplanta', ch): floor = 0
            hood = (c.select_one('.ad-preview__subtitle') or c.select_one('.p-sm'))
            hood = hood.get_text(strip=True) if hood else ''
            latlon = geo.get(iid)
            if price is None or surf is None: continue
            if price > PRICE_MAX or surf < SURF_MIN: continue
            if floor is not None and floor < 1: continue
            if not latlon or not in_zone(*latlon): continue
            ag = c.select_one('a[href*="inmobiliaria-"]')
            out.append({'id': iid, 'price': price, 'surface': surf, 'floor': floor,
                        'lat': latlon[0], 'lon': latlon[1], 'url': link, 'hood': hood,
                        'agency': ag.get_text(strip=True) if ag else None})
        return page, out
    except Exception:
        return page, []

cands = []
seen = set()
with ThreadPoolExecutor(max_workers=8) as ex:
    for page, items in ex.map(fetch_page, range(1, MAXPAGES + 1)):
        for c in items:
            if c['id'] in seen: continue
            seen.add(c['id']); cands.append(c)
        if page % 40 == 0:
            print(f'page {page}, candidates {len(cands)}', flush=True)

print('list candidates:', len(cands))
json.dump(cands, open(os.path.join(D,'pisos_cands.json'), 'w'), ensure_ascii=False)
