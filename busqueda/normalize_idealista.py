#!/usr/bin/env python3
"""Normaliza idealista_raw.jsonl (scrape local de Marta) -> idealista_details.json
con el mismo esquema que pisos_details/tc_details/hab_details."""
import json, re, os, time, hashlib, sys

HOME = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(HOME, 'idealista_raw.jsonl')
OUT = os.path.join(HOME, 'idealista_details.json')

NUM = lambda s: int(re.sub(r'\D', '', s or '') or 0) or None

NO_POSES = re.compile(r'okupad|(?<!des)(?<!no )ocupad|nuda propiedad|usufruct|sin posesi[oó]n|no se puede visitar|(?<!sin )(?<!libre de )inquilinos?|no se (entrega|vende)[^.,;\n]{0,40}inquilinos?|alquilad[ao]\b|vivienda alquilada|subasta|rentabilidad|para inversores', re.I)
AC_RE = re.compile(r'aire\s+acondicionado|climatizaci[oó]n', re.I)
AC_NEG = re.compile(r'\b(?:sin|no)\s+(?:aire\s+acondicionado|climatizaci[oó]n)|\bno\s+(?:tiene|dispone\s+de|cuenta\s+con)\s+(?:aire\s+acondicionado|climatizaci[oó]n)|\bpreinstalaci[oó]n[^.,;\n]{0,40}(?:aire\s+acondicionado|climatizaci[oó]n)', re.I)
HEAT_RE = re.compile(r'calefacci[oó]n|radiadores|suelo\s+radiante|aerotermia|\bcaldera\b', re.I)
HEAT_NEG = re.compile(r'\b(?:sin|no)\s+(?:calefacci[oó]n|radiadores|suelo\s+radiante)|\bno\s+(?:tiene|dispone\s+de|cuenta\s+con|hay)\s+(?:calefacci[oó]n|radiadores|suelo\s+radiante)|\bpreinstalaci[oó]n\s+(?:de\s+|para\s+)?(?:calefacci[oó]n|radiadores|suelo\s+radiante)', re.I)
INTERIOR = re.compile(r'\b(?:vivienda|piso|casa|estudio|[aá]tico|d[uú]plex|inmueble|apartamento)\s+interior\b|\binterior\b\s+(?:muy\s+)?(?:luminoso|soleado|tranquilo|pero)|orientaci[oó]n\s+interior\b|\b\d+[ªº]?\s*interior\b|\binterior\s+con\s+ascensor\b|\bes\s+interior\b|,\s*interior\b(?!\s+de\b)', re.I)
INT_NEG = re.compile(r'(?:patio|escalera|portal|carpintería|carpinteria|armario|pasillo|vestíbulo|vestibulo|zona|acceso|visitas?)\s+interior|\bno\s+(?:es|sea|parece|es\s+una|es\s+un)\s+interior|(?:acceso|entrada|visitas?|zona)\s+(?:al\s+)?interior\s+del?\s+(?:edificio|portal|inmueble|bloque)|uso\s+interior|interiormente|interiorismo', re.I)
ASC_NEG = re.compile(r'\b(?:sin|no)\s+ascensor|\bno\s+(?:tiene|dispone\s+de|cuenta\s+con|hay)\s+ascensor', re.I)
RULE_V = hashlib.md5(NO_POSES.pattern.encode() + b'idl1').hexdigest()[:8]
now = time.time()

def fnum(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None

def parse(it):
    feats = ' | '.join(it.get('features') or []) + ' | ' + (it.get('features2') and ' | '.join(it['features2']) or '')
    text = '\n'.join([it.get('title') or '', feats, it.get('desc') or ''])
    low = text.lower()

    c = {'id': re.search(r'(\d{6,})', it['url']).group(1) if re.search(r'(\d{6,})', it['url']) else it['url'],
         'url': it['url'], 'src': 'Idealista', 'ts': now, 'rv': RULE_V}
    if not it.get('title'):
        c['detail_err'] = 'no-title'
        return c

    c['price'] = NUM(it.get('price'))
    m2c = re.search(r'(\d+)\s*m²\s*(?:construidos|de superficie)', low)
    m2u = re.search(r'(\d+)\s*m²\s*(?:útiles|utiles)', low)
    m2 = m2c or re.search(r'(\d+)\s*m²', low)
    c['surface'] = int(m2.group(1)) if m2 else None
    c['rooms'] = (lambda m: int(m.group(1)) if m else None)(re.search(r'(\d+)\s*habitacion', low))
    c['agency'] = it.get('agency') or None
    c['pics'] = it.get('pics') or 0
    c['lat'], c['lon'] = fnum(it.get('lat')), fnum(it.get('lon'))
    c['hood'] = (it.get('ubic') or '').strip() or None
    c['plano'] = bool(it.get('has_plan') or it.get('has_tour'))
    c['desc_head'] = ((it.get('title') or '') + '\n' + (it.get('desc') or ''))[:4000]

    # planta
    c['planta'] = None
    mf = re.search(r'(?:planta|piso)\s+(\d+)[ªº]?|(\d+)[ªº]\s*planta|planta\s+(baja|intermedia|sotano|semisotano)|\b(bajo|entreplanta|[aá]tico)\b', low)
    if mf:
        if mf.group(1): c['planta'] = int(mf.group(1))
        elif mf.group(2): c['planta'] = int(mf.group(2))
        elif mf.group(3):
            v = mf.group(3); c['planta'] = 0 if v in ('baja', 'sotano', 'semisotano') else 1
        elif mf.group(4):
            v = mf.group(4); c['planta'] = 0 if v in ('bajo', 'entreplanta') else 12
    if re.search(r'\b[aá]tico\b', low) and (c['planta'] is None or c['planta'] >= 6):
        c['planta'] = 12

    # ascensor
    if re.search(r'con\s+ascensor|ascensor\s+incluido|hay\s+ascensor|tiene\s+ascensor', low):
        c['elev'] = True
    elif ASC_NEG.search(low):
        c['elev'] = False
    else:
        c['elev'] = None

    c['ac'] = bool(AC_RE.search(AC_NEG.sub(' ', text)))
    c['heat'] = bool(HEAT_RE.search(HEAT_NEG.sub(' ', text)))
    c['occ'] = bool(NO_POSES.search(text))
    c['interior'] = bool(INTERIOR.search(INT_NEG.sub(' ', text)))
    o = re.findall(r'orientaci[oó]n[^.\n]{0,60}', low)
    c['ori'] = ' '.join(re.findall(r'\b(noro?este|suro?este|sureste|noreste|norte|sur|este|oeste)\b', ' '.join(o), re.I))
    return c

raw = [json.loads(l) for l in open(RAW, encoding='utf-8') if l.strip()]
out = [parse(it) for it in raw]
json.dump(out, open(OUT, 'w'), ensure_ascii=False)
print('idealista:', len(out), '| con datos:', sum(1 for c in out if not c.get('detail_err')),
      '| sin coords:', sum(1 for c in out if c.get('lat') is None),
      '| sin precio/sup:', sum(1 for c in out if not c.get('price') or not c.get('surface')))
