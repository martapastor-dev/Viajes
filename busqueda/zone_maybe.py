#!/usr/bin/env python3
"""Recalcula la zona (zonas.py -> intersecta.py -> tp_boadilla.py) solo si
cambiaron walk_max/tp_max/car_max respecto a la última zona generada."""
import json, os, subprocess, sys

HOME = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HOME)
from params import load, effective

LAST = os.path.join(HOME, 'zone_params.json')

p = effective(load())
cur = {k: p[k] for k in ('walk_max', 'tp_max', 'car_max')}
try:
    last = json.load(open(LAST))
except Exception:
    last = None

if last == cur:
    print('zona: sin cambios, se reutiliza')
    sys.exit(0)

print('zona: parámetros cambiados', last, '->', cur, '; recalculando')
for s in ('zonas.py', 'intersecta.py', 'tp_boadilla.py'):
    subprocess.run([sys.executable, os.path.join(HOME, s)], check=True)
json.dump(cur, open(LAST, 'w'))
print('zona recalculada')
