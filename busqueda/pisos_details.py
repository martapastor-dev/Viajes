#!/usr/bin/env python3
"""Descarga fichas de pisos.com en paralelo, con caché por id en pisos_details.json."""
import re, json, os, time, hashlib
import requests
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor

UA = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36'}
D = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(D, 'pisos_details.json')
MAX_AGE = 5 * 86400          # refrescar si la ficha tiene >5 días

NO_POSES = re.compile(r'okupad|(?<!des)(?<!no )ocupad|nuda propiedad|usufruct|sin posesi[oó]n|no se puede visitar|(?<!sin )(?<!libre de )inquilinos?|no se (entrega|vende)[^.,;\n]{0,40}inquilinos?|alquilad[ao]\b|vivienda alquilada|subasta|rentabilidad|para inversores', re.I)
ORI_CTX = re.compile(r'orientaci[oó]n[^.\n]{0,60}', re.I)
AC_TXT = re.compile(r'icon-aire|\baire\s+acondicionado\b', re.I)
AC_NEG = re.compile(r'\b(?:sin|no)\s+aire\s+acondicionado|\bno\s+(?:tiene|dispone\s+de|cuenta\s+con)\s+aire\s+acondicionado|\bpreinstalaci[oó]n[^.,;\n]{0,40}aire\s+acondicionado', re.I)
HEAT_RE = re.compile(r'calefacci[oó]n|radiadores|suelo\s+radiante|aerotermia|\bcaldera\b', re.I)
HEAT_NEG = re.compile(r'\b(?:sin|no)\s+(?:calefacci[oó]n|radiadores|suelo\s+radiante)|\bno\s+(?:tiene|dispone\s+de|cuenta\s+con|hay)\s+(?:calefacci[oó]n|radiadores|suelo\s+radiante)|\bpreinstalaci[oó]n\s+(?:de\s+|para\s+)?(?:calefacci[oó]n|radiadores|suelo\s+radiante)', re.I)
INTERIOR = re.compile(r'\b(?:vivienda|piso|casa|estudio|[aá]tico|d[uú]plex|inmueble|apartamento)\s+interior\b|\binterior\b\s+(?:muy\s+)?(?:luminoso|soleado|tranquilo|pero)|orientaci[oó]n\s+interior\b|\b\d+[ªº]?\s*interior\b|\binterior\s+con\s+ascensor\b|\bes\s+interior\b|,\s*interior\b(?!\s+de\b)', re.I)
INT_NEG = re.compile(r'(?:patio|escalera|portal|carpintería|carpinteria|armario|pasillo|vestíbulo|vestibulo|zona|acceso|visitas?)\s+interior|\bno\s+(?:es|sea|parece|es\s+una|es\s+un)\s+interior|(?:acceso|entrada|visitas?|zona)\s+(?:al\s+)?interior\s+del?\s+(?:edificio|portal|inmueble|bloque)|uso\s+interior|interiormente|interiorismo', re.I)
RULE_V = hashlib.md5((NO_POSES.pattern + ORI_CTX.pattern + AC_TXT.pattern + AC_NEG.pattern + HEAT_RE.pattern + HEAT_NEG.pattern + INTERIOR.pattern + INT_NEG.pattern + 'sub3').encode()).hexdigest()[:8]  # invalida la caché si cambian las reglas

sess = requests.Session(); sess.headers.update(UA)
cands = json.load(open(os.path.join(D, 'pisos_cands.json')))
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
            if 'Aire' in label: c['ac'] = True
            if 'Orientaci' in label and val:
                c['ori'] = val.get_text(strip=True)
        if asc is None:
            asc = 'ascensor' in (soup.find('span', id='vtmExtraVars') or {}).get('data-var', '') \
                  or 'icon-ascensor' in r.text
        if cal is None:
            cal = bool(re.search(r'icon-calefacci|>Calefacci.n<', r.text))
        if not c.get('ac'):
            c['ac'] = bool(AC_TXT.search(AC_NEG.sub(' ', r.text)))
        ag = soup.find('a', href=re.compile(r'/inmobiliaria-[^/]+/?$'))
        c['agency'] = ag.get_text(strip=True) if ag else c.get('agency')
        desc_el = soup.select_one('.js-description') or soup.select_one('.description__text') or soup.select_one('.ad-detail__description')
        desc = desc_el.get_text('\n', strip=True) if desc_el else ''
        bad_occ = bool(NO_POSES.search(desc)) or bool(NO_POSES.search(soup.title.string or ''))
        c.pop('detail_err', None)
        c.setdefault('ori', '')
        desc_ori = ' '.join(re.findall(r'(?i)\b(noro?este|suro?este|sureste|noreste|norte|sur|este|oeste)\b',
                                       ' '.join(ORI_CTX.findall(desc))))
        if desc_ori and not c['ori']: c['ori'] = desc_ori.lower()
        if not cal:
            cal = bool(HEAT_RE.search(HEAT_NEG.sub(' ', desc)))
        c['interior'] = bool(INTERIOR.search(INT_NEG.sub(' ', desc)))
        pids = set()
        for img in soup.select('.media-thumbnail img, .carousel__main-photo img'):
            pm = re.search(r'_([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})',
                           img.get('src') or img.get('data-src') or '')
            if pm: pids.add(pm.group(1))
        c['pics'] = len(pids) or len(soup.select('.media-thumbnail'))
        c['plano'] = 'media-types-menu__button--floorplans' in r.text
        c.update({'planta': planta, 'elev': asc, 'heat': cal, 'occ': bad_occ,
                  'desc_head': desc[:4000], 'ts': now, 'rv': RULE_V})
    except Exception as e:
        c['detail_err'] = str(e)[:80]
    return c

todo = []
for c in cands:
    p = prev.get(c['id'])
    if p and not p.get('detail_err') and p.get('rv') == RULE_V and p.get('ts', 0) > now - MAX_AGE and p.get('price') == c['price']:
        if 'ori' in p and 'ac' in p and 'plano' in p:
            c.update({k: p[k] for k in ('planta', 'elev', 'heat', 'occ', 'desc_head', 'agency', 'ts', 'rv', 'ori', 'ac', 'interior', 'pics', 'plano') if k in p})
        else:
            todo.append(c)  # la ficha en caché es anterior al campo 'ori'
    else:
        todo.append(c)

print('cached:', len(cands) - len(todo), 'to fetch:', len(todo))
with ThreadPoolExecutor(max_workers=8) as ex:
    for i, _ in enumerate(ex.map(fetch, todo)):
        if i % 30 == 0: print(i, flush=True)

json.dump(cands, open(CACHE, 'w'), ensure_ascii=False)
print('done', len(cands))
