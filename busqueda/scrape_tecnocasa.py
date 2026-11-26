#!/usr/bin/env python3
"""Scrape tecnocasa.es list pages (params.MUNICIPIOS): JSON embebido en :estate de cada estate-card."""
import re, json, html, time, sys, os
import requests
from concurrent.futures import ThreadPoolExecutor

UA = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36'}
LIST = 'https://www.tecnocasa.es/venta/piso/comunidad-de-madrid/{}.html/pag-{}'
_P = __import__('params').effective(__import__('params').load())
SURF_MIN = _P.get('m2_min', 70)
PRICE_MAX = int(_P['precio_max'] / _P['nego'])  # cota bruta del anuncio
MAXPAGES = 80
D = __import__('os').path.dirname(__import__('os').path.abspath(__file__))

sess = requests.Session(); sess.headers.update(UA)
BLOB = re.compile(r':estate="(\{.*?\})"\s+:highlight', re.S)

def page(slug, n):
    try:
        r = sess.get(LIST.format(slug, n), timeout=30)
        if r.status_code != 200:
            return [], []
        out, keys = [], []
        for raw in BLOB.findall(r.text):
            try:
                j = json.loads(html.unescape(raw))
            except Exception:
                continue
            keys.append(str(j.get('id')))
            mp = re.search(r'([\d.]+)', j.get('price') or '')
            ms = re.search(r'([\d.]+)', j.get('surface') or '')
            if not mp or not ms:
                continue
            price = int(mp.group(1).replace('.', ''))
            surf = int(ms.group(1).replace('.', ''))
            if price > PRICE_MAX or surf < SURF_MIN:
                continue
            hood = (j.get('subtitle') or '').split(',')[-1].strip()
            out.append({'id': str(j.get('id')), 'price': price, 'surface': surf,
                        'url': j.get('detail_url'), 'hood': hood,
                        'agency': 'Tecnocasa', 'pics': len(j.get('images') or []),
                        'rooms': j.get('rooms'), 'src': 'Tecnocasa'})
        return out, keys
    except Exception:
        return None

cands, seen, failed = [], set(), []
for mun in __import__('params').MUNICIPIOS:
    slug = mun['tecnocasa']
    for n, out in __import__('params').pages_until_repeat(lambda p: page(slug, p), MAXPAGES, 6):
        if out is None:
            failed.append((slug, n)); continue
        for c in out:
            if c['id'] in seen: continue
            seen.add(c['id']); cands.append(c)
# una segunda pasada por si alguna página falló
for slug, n in list(failed):
    r = page(slug, n)
    out = r and r[0]
    if out:
        for c in out:
            if c['id'] not in seen:
                seen.add(c['id']); cands.append(c)
        failed.remove((slug, n))

print('cands:', len(cands), 'failed:', failed)
if failed and os.path.exists(D + '/tc_cands.json'):
    prev = {c['id']: c for c in json.load(open(D + '/tc_cands.json'))}
    for cid, c in prev.items():
        if cid not in seen:
            seen.add(cid); cands.append(c)
    print('cands con cache por paginas fallidas:', len(cands))
json.dump(cands, open(D + '/tc_cands.json', 'w'), ensure_ascii=False)
