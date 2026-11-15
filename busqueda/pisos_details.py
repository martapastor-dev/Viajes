#!/usr/bin/env python3
"""Descarga fichas de pisos.com en paralelo, con caché por id en pisos_details.json."""
import re, json, os, time
import requests
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor

UA = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36'}
D = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(D, 'pisos_details.json')
MAX_AGE = 5 * 86400          # refrescar si la ficha tiene >5 días

NO_POSES = re.compile(r'okupad|ocupad|nuda propiedad|usufruct|sin posesi[oó]n|no se puede visitar|con inquilino|inquilinos|alquilad[ao]\b|vivienda alquilada|pleno dominio|subasta|rentabilidad|para inversores', re.I)

sess = requests.Session(); sess.headers.update(UA)
cands = json.load(open(os.path.join(D,'pisos_cands.json')))
prev = {c['id']: c for c in json.load(open(CACHE))} if os.path.exists(CACHE) else {}
now = time.time()

def fetch(c):
    try:
        r = sess.get(c['url'], timeout=30)
        if r.status_code != 200:
            c['detail_err'] = r.status_code; return c
        soup = BeautifulSoup(r.text, 'html.parser')
        planta = None; asc = None; cal = None
        for f in soup.select('.features__feature'):
            lab = f.select_one('.features__label')
            val = f.select_one('.features__value')
            label = lab.get_text(strip=True) if lab else ''
            if 'Planta' in label and val:
                pv = val.get_text(strip=True)
                m = re.match(r'(\d+)', pv)
                if m: planta = int(m.group(1))
                elif re.search(r'(?i)bajo|s.tano', pv): planta = 0
                elif re.search(r'(?i)entreplanta|entresuelo', pv): planta = 1
            if 'Ascensor' in label: asc = True
            if 'Calefacci' in label: cal = True
        if asc is None:
            asc = 'ascensor' in (soup.find('span', id='vtmExtraVars') or {}).get('data-var', '') \
                  or 'icon-ascensor' in r.text
        if cal is None:
            cal = bool(re.search(r'icon-calefacci|>Calefacci.n<', r.text))
        ag = soup.find('a', href=re.compile(r'/inmobiliaria-[^/]+/?$'))
        c['agency'] = ag.get_text(strip=True) if ag else c.get('agency')
        desc_el = soup.select_one('.description__text') or soup.select_one('.ad-detail__description')
        desc = desc_el.get_text('\n', strip=True) if desc_el else ''
        bad_occ = bool(NO_POSES.search(desc)) or bool(NO_POSES.search(soup.title.string or ''))
        c.pop('detail_err', None)
        c.update({'planta': planta, 'elev': asc, 'heat': cal, 'occ': bad_occ,
                  'desc_head': desc[:400], 'ts': now})
    except Exception as e:
        c['detail_err'] = str(e)[:80]
    return c

todo = []
for c in cands:
    p = prev.get(c['id'])
    if p and not p.get('detail_err') and p.get('ts', 0) > now - MAX_AGE and p.get('price') == c['price']:
        c.update(p)
    else:
        todo.append(c)

print('cached:', len(cands) - len(todo), 'to fetch:', len(todo))
with ThreadPoolExecutor(max_workers=8) as ex:
    for i, _ in enumerate(ex.map(fetch, todo)):
        if i % 30 == 0: print(i, flush=True)

json.dump(cands, open(CACHE, 'w'), ensure_ascii=False)
print('done', len(cands))
