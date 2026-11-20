#!/usr/bin/env python3
"""Scrape habitaclia.com madrid capital: JSON-LD ItemList + fichas."""
import re, json, os, time, hashlib
import requests
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor

UA = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36'}
D = os.path.dirname(os.path.abspath(__file__))
LIST = 'https://www.habitaclia.com/comprar/viviendas/madrid-provincia/madrid-capital/s/{}'
PRICE_MAX = 335000
SURF_MIN = 70
MAXPAGES = 40
CACHE = os.path.join(D, 'hab_details.json')
MAX_AGE = 5 * 86400

NO_POSES = re.compile(r'okupad|(?<!des)(?<!no )ocupad|nuda propiedad|usufruct|sin posesi[oó]n|no se puede visitar|(?<!sin )(?<!libre de )inquilinos?|no se (entrega|vende)[^.,;\n]{0,40}inquilinos?|alquilad[ao]\b|vivienda alquilada|subasta|rentabilidad|para inversores', re.I)
ORI_CTX = re.compile(r'orientaci[oó]n[^.\n]{0,60}', re.I)
AC_TXT = re.compile(r'aire\s+acondicionado|climatizaci[oó]n', re.I)
AC_NEG = re.compile(r'\b(?:sin|no)\s+(?:aire\s+acondicionado|climatizaci[oó]n)|\bno\s+(?:tiene|dispone\s+de|cuenta\s+con)\s+(?:aire\s+acondicionado|climatizaci[oó]n)|\bpreinstalaci[oó]n[^.,;\n]{0,40}(?:aire\s+acondicionado|climatizaci[oó]n)', re.I)
HEAT_RE = re.compile(r'calefacci[oó]n|radiadores|suelo\s+radiante|aerotermia|\bcaldera\b', re.I)
HEAT_NEG = re.compile(r'\b(?:sin|no)\s+(?:calefacci[oó]n|radiadores|suelo\s+radiante)|\bno\s+(?:tiene|dispone\s+de|cuenta\s+con|hay)\s+(?:calefacci[oó]n|radiadores|suelo\s+radiante)|\bpreinstalaci[oó]n\s+(?:de\s+|para\s+)?(?:calefacci[oó]n|radiadores|suelo\s+radiante)', re.I)
INTERIOR = re.compile(r'\b(?:vivienda|piso|casa|estudio|[aá]tico|d[uú]plex|inmueble|apartamento)\s+interior\b|\binterior\b\s+(?:muy\s+)?(?:luminoso|soleado|tranquilo|pero)|orientaci[oó]n\s+interior\b|\b\d+[ªº]?\s*interior\b|\binterior\s+con\s+ascensor\b|\bes\s+interior\b|,\s*interior\b(?!\s+de\b)', re.I)
INT_NEG = re.compile(r'(?:patio|escalera|portal|carpintería|carpinteria|armario|pasillo|vestíbulo|vestibulo|zona|acceso|visitas?)\s+interior|\bno\s+(?:es|sea|parece|es\s+una|es\s+un)\s+interior|(?:acceso|entrada|visitas?|zona)\s+(?:al\s+)?interior\s+del?\s+(?:edificio|portal|inmueble|bloque)|uso\s+interior|interiormente|interiorismo', re.I)
ASC_NEG = re.compile(r'\b(?:sin|no)\s+ascensor|\bno\s+(?:tiene|dispone\s+de|cuenta\s+con|hay)\s+ascensor', re.I)
RULE_V = hashlib.md5((NO_POSES.pattern + 'hab4').encode()).hexdigest()[:8]

sess = requests.Session(); sess.headers.update(UA)
prev = {c['id']: c for c in json.load(open(CACHE))} if os.path.exists(CACHE) else {}
now = time.time()

def ldjsons(t):
    out = []
    for m in re.finditer(r'application/ld\+json[^>]*>(.*?)</script>', t, re.S):
        try: out.append(json.loads(m.group(1)))
        except Exception: pass
    return out

def page(n):
    try:
        url = 'https://www.habitaclia.com/comprar/viviendas/madrid-provincia/madrid-capital/s' if n == 1 else LIST.format(n)
        r = sess.get(url, timeout=30)
        if r.status_code != 200: return n, None
        urls = re.findall(r'href="(/comprar/[^"]+/d)"', r.text)
        return n, ['https://www.habitaclia.com' + u for u in dict.fromkeys(urls)]
    except Exception:
        return n, None

urls, seen, failed = [], set(), []
with ThreadPoolExecutor(max_workers=4) as ex:
    for n, out in ex.map(page, range(1, MAXPAGES + 1)):
        if out is None:
            failed.append(n); continue
        for u in out:
            if u not in seen:
                seen.add(u); urls.append(u)
print('urls:', len(urls), 'failed:', failed)

def jdesc(s):
    s = re.sub(r'\\u([dD][89aAbB][0-9a-fA-F]{2})\\u([dD][c-fC-F][0-9a-fA-F]{2})',
               lambda m: chr(0x10000 + ((int(m.group(1), 16) - 0xD800) << 10) + int(m.group(2), 16) - 0xDC00), s)
    s = re.sub(r'\\u([0-9a-fA-F]{4})', lambda m: chr(int(m.group(1), 16)), s)
    return s.replace('\\n', ' ').replace('\\/', '/').encode('utf-8', 'ignore').decode('utf-8')

def fetch(u):
    c = {'id': u.rsplit('/', 2)[-2] if u.endswith('/d') else u, 'url': u, 'src': 'Habitaclia'}
    try:
        r = sess.get(u, timeout=30)
        if r.status_code != 200:
            c['detail_err'] = r.status_code; return c
        apt = next((j for j in ldjsons(r.text) if 'Apartment' in (j.get('@type') or [])), None)
        if not apt:
            c['detail_err'] = 'no-ldjson'; return c
        off = apt.get('offers') or {}
        c['price'] = off.get('price')
        c['agency'] = ((off.get('seller') or {}).get('name'))
        c['surface'] = (apt.get('floorSize') or {}).get('value')
        c['rooms'] = apt.get('numberOfRooms')
        c['pics'] = len(apt.get('image') or [])
        hood = None
        m = re.search(r'\\"displayZoneLine\\":\\"(.*?)\\"(?=[,}])', r.text)
        if m:
            hood = jdesc(m.group(1))
            nb = re.search(r'\\"type\\":\\"neighbourhood\\",\\"value\\":\\"(.*?)\\"', r.text)
            if nb and jdesc(nb.group(1)).lower() not in hood.lower():
                hood += ' ' + jdesc(nb.group(1))
        c['hood'] = hood or (apt.get('address') or {}).get('addressLocality')
        descr = re.findall(r'\\"description\\":\\"(.*?)\\"(?=[,}])', r.text)
        if not descr:
            descr = re.findall(r'"description":"((?:\\.|[^"\\])*)"', r.text)
        full = jdesc(max(descr, key=len)) if descr else (apt.get('description') or '')
        desc = (apt.get('name') or '') + '\n' + full
        c['desc_head'] = desc[:4000]
        m = re.search(r'"coordinates":\{"latitude":([\d.\-]+),"longitude":([\d.\-]+)', r.text.replace('\\"', '"'))
        if m: c['lat'], c['lon'] = float(m.group(1)), float(m.group(2))
        ams = {a.get('name') for a in (apt.get('amenityFeature') or []) if a.get('value')}
        c['elev'] = ('Ascensor' in ams) or bool(re.search(r'ascensor', ASC_NEG.sub(' ', desc), re.I)) or None
        c['ac'] = ('Aire acondicionado' in ams) or bool(AC_TXT.search(AC_NEG.sub(' ', desc)))
        c['heat'] = bool(HEAT_RE.search(HEAT_NEG.sub(' ', desc)))
        c['occ'] = bool(NO_POSES.search(desc))
        c['interior'] = ('Interior' in ams) or bool(INTERIOR.search(INT_NEG.sub(' ', desc)))
        c['planta'] = None
        fl = re.search(r'(?i)\bplanta\s+(\d+)|(\d+)[ªº]\s*planta|planta\s+(baja|intermedia)', desc)
        if fl:
            g = fl.group(1) or fl.group(2)
            c['planta'] = int(g) if g else (0 if fl.group(3).lower() == 'baja' else 2)
        if c['planta'] is None and re.search(r'(?i)\b[áa]tico\b', apt.get('name') or ''): c['planta'] = 12
        desc_ori = ' '.join(re.findall(r'(?i)\b(noro?este|suro?este|sureste|noreste|norte|sur|este|oeste)\b',
                                       ' '.join(ORI_CTX.findall(desc))))
        c['ori'] = desc_ori.lower()
        c.pop('detail_err', None)
        c.update({'ts': now, 'rv': RULE_V})
    except Exception as e:
        c['detail_err'] = str(e)[:80]
    return c

todo = []
for u in urls:
    cid = u.rsplit('/', 2)[-2]
    p = prev.get(cid)
    if p and not p.get('detail_err') and p.get('rv') == RULE_V and p.get('ts', 0) > now - MAX_AGE:
        continue
    todo.append(u)
res = {}
for u in urls:
    cid = u.rsplit('/', 2)[-2]
    p = prev.get(cid)
    if p and not p.get('detail_err') and p.get('rv') == RULE_V and p.get('ts', 0) > now - MAX_AGE:
        res[u] = p
print('cached:', len(res), 'to fetch:', len(urls) - len(res))
todo = [u for u in urls if u not in res]
with ThreadPoolExecutor(max_workers=8) as ex:
    for u, c in zip(todo, ex.map(fetch, todo)):
        cid = u.rsplit('/', 2)[-2]
        if c.get('detail_err') and prev.get(cid) and not prev[cid].get('detail_err'):
            res[u] = prev[cid]
        else:
            res[u] = c
if failed:
    live = {u.rsplit('/', 2)[-2] for u in urls}
    for cid, c in prev.items():
        if cid not in live and c.get('url') not in res:
            res[c['url']] = c
    print('cache por paginas fallidas:', len(res))
out = list(res.values())
out = [c for c in out if c.get('price') and c.get('surface') and c['price'] <= PRICE_MAX and (c['surface'] or 0) >= SURF_MIN]
json.dump(out, open(CACHE, 'w'), ensure_ascii=False)
print('done', len(out))
