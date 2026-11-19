#!/usr/bin/env python3
"""Zonas válidas: ≤25' coche a CGS en hora punta, estación ≤12' andando con TP ≤40' a Alonso Martínez."""
import json, math, heapq, requests, os, sys

HOME = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HOME)
from params import load as _pload
P = _pload()

BASE = '/home/ubuntu/repos/Viajes/hestia/dinamico'

def load_js(name, var):
    s = open(f'{BASE}/{name}').read()
    i = s.index(var)
    j = s.index('{', i)
    depth = 0; k = j
    instr = False; esc = False
    while True:
        c = s[k]
        if instr:
            if esc: esc = False
            elif c == '\\': esc = True
            elif c == '"': instr = False
        else:
            if c == '"': instr = True
            elif c == '{': depth += 1
            elif c == '}':
                depth -= 1
                if depth == 0: break
        k += 1
    return json.loads(s[j:k+1])

G = load_js('datos_tp.js', 'GRAFO_TP')
W = load_js('walk_real.js', 'WALK_REAL')
GP, SK, RK, SD, EDGES, XFER, WAIT_ARR, RNAME = (G[k] for k in ('p','sk','rk','sd','e','te','w','r'))

STA = {k: (SD[i][0], SD[i][1], SD[i][2]) for i, k in enumerate(SK)}
WAIT = {RK[i]: WAIT_ARR[i] for i in range(len(RK))}

ADJ = {}
for uI, vI, t, rkI in EDGES:
    ADJ.setdefault(SK[vI], []).append((SK[uI], t, RK[rkI]))
for aI, bI, w in XFER:
    ADJ.setdefault(SK[bI], []).append((SK[aI], w, 'WALK'))

def hav_km(la1, lo1, la2, lo2):
    R = 6371
    dp = math.radians(la2-la1); dl = math.radians(lo2-lo1)
    a = math.sin(dp/2)**2 + math.cos(math.radians(la1))*math.cos(math.radians(la2))*math.sin(dl/2)**2
    return 2*R*math.asin(math.sqrt(min(1, a)))

def walk_min(la1, lo1, la2, lo2):
    return hav_km(la1, lo1, la2, lo2)*GP['DET']/GP['SPD']*60

def computeTP(dlat, dlon):
    dist = {}; pq = []
    for k, (la, lo, _) in STA.items():
        w = walk_min(la, lo, dlat, dlon)
        if w < 60:
            dist[(k, None)] = w
            heapq.heappush(pq, (w, k, None))
    INF = float('inf')
    while pq:
        d, v, rout = heapq.heappop(pq)
        if d > dist.get((v, rout), INF): continue
        for u, t, rk in ADJ.get(v, ()):
            extra = t
            if rout is not None and rk != rout:
                extra += WAIT.get(rout, 3)
                if rk != 'WALK' and rout != 'WALK': extra += GP['XFER']
            nd = d + extra
            if nd < dist.get((u, rk), INF):
                dist[(u, rk)] = nd
                heapq.heappush(pq, (nd, u, rk))
    T = {}
    for (s, rk), d in dist.items():
        t = d if rk is None else d + WAIT.get(rk, 3) + GP['ACC']
        if t < T.get(s, INF): T[s] = t
    return {s: t*GP['F'] for s, t in T.items()}

AM = (40.42772, -3.69594)   # Alonso Martínez
CGS = (40.3930154, -3.8691104)

T = computeTP(*AM)
print(f'estaciones en grafo: {len(T)}; TP Alonso Martínez a sí mismo: {T.get("metro_est_4_57", -1):.1f}')

# grid igual que buildGrid
dlat = GP['STEP']; dlon = GP['STEP']/math.cos(math.radians(GP['LA0']))
lats = []; la = GP['LA0']
while la < GP['LA1']: lats.append(la); la += dlat
lons = []; lo = GP['LO0']
while lo < GP['LO1']: lons.append(lo); lo += dlon
nR, nC = len(lats), len(lons)
assert (nR, nC) == (W['nR'], W['nC']), (nR, nC, W['nR'], W['nC'])

cov = set()
for gi in W.get('cov', []):
    cov.add(SK[gi])

WALK_MAX, TP_MAX = float(P['walk_max']), float(P['tp_max'])
# por celda: mejor estación cumpliendo ambos criterios
valid = [[False]*nC for _ in range(nR)]
bestw = [[float('inf')]*nC for _ in range(nR)]
besttp = [[float('inf')]*nC for _ in range(nR)]
beststa = [[None]*nC for _ in range(nR)]
sk2keys = list(T.keys())
sla = {k: STA[k][0] for k in sk2keys}
slo = {k: STA[k][1] for k in sk2keys}

for r in range(nR):
    lat = lats[r]
    for c in range(nC):
        lon = lons[c]
        ci = r*nC + c
        cands = {}  # sk -> walk min
        for p in range(0, len(W['cells'][ci]), 2):
            cands[SK[W['cells'][ci][p]]] = W['cells'][ci][p+1]
        for k in sk2keys:
            if k in cov or k in cands: continue
            w = walk_min(lat, lon, sla[k], slo[k])
            if w < cands.get(k, 1e9): cands[k] = w
        # caminar directo a AM también cuenta como "estación" si <=12
        dw = walk_min(lat, lon, *AM)
        best = None
        for k, w in cands.items():
            t = T.get(k)
            if t is None: continue
            if w <= WALK_MAX and t <= TP_MAX:
                if best is None or w + t < best[0] + best[1]:
                    best = (w, t, k)
            if w < bestw[r][c]: bestw[r][c] = w
            if t < besttp[r][c] and w <= WALK_MAX:
                pass
        if dw <= WALK_MAX and (best is None or dw < best[0]):
            best = (dw, 0.0, 'DIRECTO')
        if best:
            valid[r][c] = True
            bestw[r][c] = best[0]; besttp[r][c] = best[1]; beststa[r][c] = best[2]

nv = sum(sum(row) for row in valid)
print(f'celdas válidas (walk<={WALK_MAX} y TP<={TP_MAX}): {nv}/{nR*nC}')

# guardar máscara y tiempos
json.dump({'lats': lats, 'lons': lons, 'valid': valid, 'walk': bestw, 'tp': besttp, 'sta': beststa},
          open('/home/ubuntu/zonas_mask.json', 'w'))

# isócrona coche hora punta -> free-flow car_max/1.2
req = round(float(P['car_max'])/1.2, 1)
r = requests.post('https://valhalla1.openstreetmap.de/isochrone', json={
    'locations': [{'lat': CGS[0], 'lon': CGS[1]}], 'costing': 'auto',
    'contours': [{'time': req}], 'polygons': True, 'denoise': 0.2, 'generalize': 80}, timeout=60)
print('valhalla', r.status_code)
feat = r.json()['features'][0]
json.dump(feat, open('/home/ubuntu/coche25.json', 'w'))
print('ok')
