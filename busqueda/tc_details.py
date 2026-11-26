#!/usr/bin/env python3
"""Descarga fichas de tecnocasa.es, con caché por id en tc_details.json."""
import re, json, os, time, hashlib, html
import requests
from concurrent.futures import ThreadPoolExecutor

UA = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36'}
D = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(D, 'tc_details.json')
MAX_AGE = 5 * 86400

NO_POSES = re.compile(r'okupad|(?<!des)(?<!no )ocupad|nuda propiedad|usufruct|sin posesi[oó]n|no se puede visitar|(?<!sin )(?<!libre de )inquilinos?|no se (entrega|vende)[^.,;\n]{0,40}inquilinos?|alquilad[ao]\b|vivienda alquilada|subasta|rentabilidad|para inversores', re.I)
ORI_CTX = re.compile(r'orientaci[oó]n[^.\n]{0,60}', re.I)
AC_TXT = re.compile(r'aire\s+acondicionado|climatizaci[oó]n', re.I)
AC_NEG = re.compile(r'\b(?:sin|no)\s+(?:aire\s+acondicionado|climatizaci[oó]n)|\bno\s+(?:tiene|dispone\s+de|cuenta\s+con)\s+(?:aire\s+acondicionado|climatizaci[oó]n)|\bpreinstalaci[oó]n[^.,;\n]{0,40}(?:aire\s+acondicionado|climatizaci[oó]n)', re.I)
HEAT_RE = re.compile(r'calefacci[oó]n|radiadores|suelo\s+radiante|aerotermia|\bcaldera\b', re.I)
HEAT_NEG = re.compile(r'\b(?:sin|no)\s+(?:calefacci[oó]n|radiadores|suelo\s+radiante)|\bno\s+(?:tiene|dispone\s+de|cuenta\s+con|hay)\s+(?:calefacci[oó]n|radiadores|suelo\s+radiante)|\bpreinstalaci[oó]n\s+(?:de\s+|para\s+)?(?:calefacci[oó]n|radiadores|suelo\s+radiante)', re.I)
INTERIOR = re.compile(r'\b(?:vivienda|piso|casa|estudio|[aá]tico|d[uú]plex|inmueble|apartamento)\s+interior\b|\binterior\b\s+(?:muy\s+)?(?:luminoso|soleado|tranquilo|pero)|orientaci[oó]n\s+interior\b|\b\d+[ªº]?\s*interior\b|\binterior\s+con\s+ascensor\b|\bes\s+interior\b|,\s*interior\b(?!\s+de\b)', re.I)
INT_NEG = re.compile(r'(?:patio|escalera|portal|carpintería|carpinteria|armario|pasillo|vestíbulo|vestibulo|zona|acceso|visitas?)\s+interior|\bno\s+(?:es|sea|parece|es\s+una|es\s+un)\s+interior|(?:acceso|entrada|visitas?|zona)\s+(?:al\s+)?interior\s+del?\s+(?:edificio|portal|inmueble|bloque)|uso\s+interior|interiormente|interiorismo', re.I)
RULE_V = hashlib.md5((NO_POSES.pattern + ORI_CTX.pattern + AC_TXT.pattern + AC_NEG.pattern + HEAT_RE.pattern + HEAT_NEG.pattern + INTERIOR.pattern + INT_NEG.pattern + 'tc3').encode()).hexdigest()[:8]
FLOOR_TXT = re.compile(r'planta\s+baja|\bbajo\b|semis[oó]tano|s[oó]tano', re.I)
ENTRE = re.compile(r'entreplanta|entresuelo', re.I)
PLANTA_N = re.compile(r'planta\s+(\d+)|(\d+)[ªº]\s*planta|(?:primer|segund[ao]|tercer[ao]?|cuart[ao]|quint[ao]|sext[ao]|s[eé]ptim[ao]|octav[ao]|noven[ao]|d[eé]cim[ao])\s+planta', re.I)
ORD = {'primer':1,'segund':2,'tercer':3,'cuart':4,'quint':5,'sext':6,'séptim':7,'septim':7,'octav':8,'noven':9,'décim':10,'decim':10}
ASC_NEG = re.compile(r'\b(?:sin|no)\s+ascensor|\bno\s+(?:tiene|dispone\s+de|cuenta\s+con|hay)\s+ascensor', re.I)

MAP_RE = re.compile(r'&quot;map&quot;:\{&quot;latitude&quot;:([\d.\-]+),&quot;longitude&quot;:([\d.\-]+)')
DESC_RE = re.compile(r'&quot;description&quot;:&quot;(.*?)&quot;(?:,&quot;|,\})', re.S)
LABEL_RE = re.compile(r'&quot;label&quot;:&quot;([^&]+?)&quot;,&quot;valore&quot;:(?:&quot;([^&]*?)&quot;|([\d.]+))\}')

sess = requests.Session(); sess.headers.update(UA)
cands = json.load(open(os.path.join(D, 'tc_cands.json')))
prev = {c['id']: c for c in json.load(open(CACHE))} if os.path.exists(CACHE) else {}
now = time.time()

def strip_html(s):
    s = html.unescape(s)
    s = re.sub(r'\\u([dD][89aAbB][0-9a-fA-F]{2})\\u([dD][c-fC-F][0-9a-fA-F]{2})',
               lambda m: chr(0x10000 + ((int(m.group(1), 16) - 0xD800) << 10) + int(m.group(2), 16) - 0xDC00), s)
    s = re.sub(r'\\u([0-9a-fA-F]{4})', lambda m: chr(int(m.group(1), 16)), s)
    s = s.replace('\\/', '/').replace('\\n', ' ').replace('\\"', '"')
    s = re.sub(r'<[^>]+>', ' ', s)
    return html.unescape(s).encode('utf-8', 'ignore').decode('utf-8')

def fetch(c):
    try:
        r = sess.get(c['url'], timeout=30)
        if r.status_code != 200:
            c['detail_err'] = r.status_code; return c
        t = r.text
        m = MAP_RE.search(t)
        if m:
            c['lat'], c['lon'] = float(m.group(1)), float(m.group(2))
        planta = None
        for lab, vs, vn in LABEL_RE.findall(t):
            if lab == 'Planta':
                pv = vs or vn
                mm = re.match(r'(\d+)', pv or '')
                if mm: planta = int(mm.group(1))
                elif pv and re.search(r'(?i)bajo|s.tano', pv): planta = 0
                elif pv and re.search(r'(?i)entreplanta|entresuelo', pv): planta = 1
        dm = DESC_RE.search(t)
        desc = strip_html(dm.group(1)) if dm else ''
        if planta is None and desc:
            if FLOOR_TXT.search(desc): planta = 0
            elif ENTRE.search(desc): planta = 1
            else:
                mf = PLANTA_N.search(desc)
                if mf:
                    if mf.group(1): planta = int(mf.group(1))
                    elif mf.group(2): planta = int(mf.group(2))
                    else:
                        mo = re.match(r'(primer|segund|tercer|cuart|quint|sext|s[eé]ptim|octav|noven|d[eé]cim)[ao]?', mf.group(0), re.I)
                        if mo: planta = ORD.get(mo.group(1).lower())
        c['planta'] = planta
        c['desc_head'] = desc[:4000]
        c['occ'] = bool(NO_POSES.search(desc))
        c['heat'] = bool(HEAT_RE.search(HEAT_NEG.sub(' ', desc)))
        c['ac'] = bool(AC_TXT.search(AC_NEG.sub(' ', desc)))
        c['elev'] = bool(re.search(r'ascensor', ASC_NEG.sub(' ', INT_NEG.sub(' ', desc)), re.I)) or None
        c['interior'] = bool(INTERIOR.search(INT_NEG.sub(' ', desc)))
        desc_ori = ' '.join(re.findall(r'(?i)\b(noro?este|suro?este|sureste|noreste|norte|sur|este|oeste)\b',
                                       ' '.join(ORI_CTX.findall(desc))))
        c['ori'] = desc_ori.lower()
        # fotos: count gallery images in detail JSON if available
        c['pics'] = max(c.get('pics') or 0, len(re.findall(r'&quot;gallery_media&quot;', t)))
        c['plano'] = bool(re.search(r'&quot;(?:floor_plans|virtual_tour)&quot;:(?!null)', t))
        c['p3d'] = True
        c.pop('detail_err', None)
        c.update({'ts': now, 'rv': RULE_V})
    except Exception as e:
        c['detail_err'] = str(e)[:80]
    return c

todo = []
for c in cands:
    p = prev.get(c['id'])
    if p and not p.get('detail_err') and p.get('rv') == RULE_V and p.get('ts', 0) > now - MAX_AGE and p.get('price') == c['price'] and 'p3d' in p:
        c.update({k: p[k] for k in ('planta', 'elev', 'heat', 'occ', 'desc_head', 'lat', 'lon', 'ts', 'rv', 'ori', 'ac', 'interior', 'pics', 'plano', 'p3d') if k in p})
    else:
        todo.append(c)

print('cached:', len(cands) - len(todo), 'to fetch:', len(todo))
with ThreadPoolExecutor(max_workers=8) as ex:
    for i, _ in enumerate(ex.map(fetch, todo)):
        if i % 30 == 0: print(i, flush=True)

json.dump(cands, open(CACHE, 'w'), ensure_ascii=False)
print('done', len(cands))
