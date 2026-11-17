#!/usr/bin/env python3
"""Merge fc_ok + pisos_ok -> items.json -> casas/index.html"""
import json, re, html, os

HOME = os.path.dirname(os.path.abspath(__file__))
OUT = HOME
names = json.load(open(os.path.join(HOME, 'stop_names.json')))

fc = json.load(open(os.path.join(HOME, 'fc_ok.json')))
pi = json.load(open(os.path.join(HOME, 'pisos_ok.json')))

def close(a, b):
    return abs(a['lat'] - b['lat']) < 0.0006 and abs(a['lon'] - b['lon']) < 0.0008

items = []
for r in fc:
    items.append({'src': 'Fotocasa', 'price': r['price'], 'eff': r['eff'], 'rate': r['rate'],
                  'agency': r.get('agency'), 'm2': r['surface'], 'eurm2': r['eurm2'],
                  'floor': r['floor'], 'elev': r['elev'], 'heat': r['heat'],
                  'hood': r['hood'] or r.get('ubic') or '', 'walk': r['walk'], 'tp': r['tp'], 'car': r.get('car'),
                  'lat': r['lat'], 'lon': r['lon'], 'oris': r.get('oris') or '',
                  'ac': r.get('ac'), 'score': r.get('score'),
                  'sta': names.get(r.get('sta'), r.get('sta')), 'url': r['url'], 'rooms': r.get('rooms')})
for r in pi:
    if any(r['price'] == f['price'] and close(r, f) for f in fc):
        continue
    ag = (r.get('agency') or '')
    rate = 0.0484 if 'redpiso' in ag.lower() else (0.0363 if ag else 0.0)
    eff = round(r.get('eff') or (r['price'] * 0.9 * (1 + rate) + (0 if r['heat'] else 10000) + r['price'] * 0.9 * 0.06))
    items.append({'src': 'Pisos', 'price': r['price'], 'eff': eff, 'rate': rate,
                  'agency': ag or None, 'm2': r['surface'], 'eurm2': r.get('eurm2') or round(r['price'] * 0.9 * (1 + rate) / r['surface']),
                  'floor': r['planta'] if r['planta'] is not None else r.get('floor'),
                  'elev': r['elev'], 'heat': r['heat'], 'hood': r['hood'] or '',
                  'walk': r['walk'], 'tp': r['tp'], 'car': r.get('car'), 'sta': names.get(r.get('sta'), r.get('sta')),
                  'lat': r['lat'], 'lon': r['lon'], 'oris': r.get('oris') or '',
                  'ac': r.get('ac'), 'score': r.get('score'),
                  'url': r['url'], 'rooms': None})

items.sort(key=lambda x: x['eurm2'])
json.dump(items, open(os.path.join(OUT, 'items.json'), 'w'), ensure_ascii=False)

tpl = open(os.path.join(OUT, 'index_template.html')).read()
zone = open(os.path.join(OUT, 'zona_overlay.json')).read().replace('</', '<\\/')
data_js = json.dumps(items, ensure_ascii=False).replace('</', '<\\/')
page = tpl.replace('const D = DATA;', 'const D = ' + data_js + ';')
page = page.replace('const ZONA = ZONE;', 'const ZONA = ' + zone + ';')
page = page.replace('FECHA_ACTUALIZACION', __import__('datetime').datetime.now().strftime('%d/%m/%Y'))
open(os.path.join(OUT, 'index.html'), 'w').write(page)
print(len(items), 'items ->', os.path.join(OUT, 'index.html'))
