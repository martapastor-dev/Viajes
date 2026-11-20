#!/usr/bin/env python3
"""Scrape tecnocasa.es madrid list pages: JSON embebido en :estate de cada estate-card."""
import re, json, html, time, sys
import requests
from concurrent.futures import ThreadPoolExecutor

UA = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36'}
LIST = 'https://www.tecnocasa.es/venta/piso/comunidad-de-madrid/madrid/madrid.html/pag-{}'
PRICE_MAX = 335000
SURF_MIN = 70
MAXPAGES = 80
D = __import__('os').path.dirname(__import__('os').path.abspath(__file__))

sess = requests.Session(); sess.headers.update(UA)
BLOB = re.compile(r':estate="(\{.*?\})"\s+:highlight', re.S)

def page(n):
    try:
        r = sess.get(LIST.format(n), timeout=30)
        if r.status_code != 200:
            return n, []
        out = []
        for raw in BLOB.findall(r.text):
            try:
                j = json.loads(html.unescape(raw))
            except Exception:
                continue
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
        return n, out
    except Exception:
        return n, None

cands, seen, failed = [], set(), []
with ThreadPoolExecutor(max_workers=6) as ex:
    for n, out in ex.map(page, range(1, MAXPAGES + 1)):
        if out is None:
            failed.append(n); continue
        if not out and n > 1:
            continue
        for c in out:
            if c['id'] in seen: continue
            seen.add(c['id']); cands.append(c)
        if n > 60:
            pass
# una segunda pasada por si alguna página falló
for n in list(failed):
    _, out = page(n)
    if out:
        for c in out:
            if c['id'] not in seen:
                seen.add(c['id']); cands.append(c)
        failed.remove(n)

print('cands:', len(cands), 'failed:', failed)
if failed and os.path.exists(D + '/tc_cands.json'):
    prev = {c['id']: c for c in json.load(open(D + '/tc_cands.json'))}
    for cid, c in prev.items():
        if cid not in seen:
            seen.add(cid); cands.append(c)
    print('cands con cache por paginas fallidas:', len(cands))
json.dump(cands, open(D + '/tc_cands.json', 'w'), ensure_ascii=False)
