#!/usr/bin/env python3
"""Minutos en TP a la Ciudad Financiera (CGS) por celda: misma mecánica que zonas.py."""
import json, math, heapq

BASE = '/home/ubuntu/repos/Viajes/hestia/dinamico'

def load_js(name, var):
    s = open(f'{BASE}/{name}').read()
    i = s.index(var); j = s.index('{', i)
    depth = 0; k = j; instr = False; esc = False
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
GP, SK, RK, SD, EDGES, XFER, WAIT_ARR = (G[k] for k in ('p','sk','rk','sd','e','te','w'))
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

CGS = (40.3930154, -3.8691104)
TB = computeTP(*CGS)
print('estaciones alcanzables a Ciudad Financiera:', len(TB))

Z = json.load(open('/home/ubuntu/zona_final.json'))
lats, lons = Z['lats'], Z['lons']
nR, nC = len(lats), len(lons)
dlat = lats[1]-lats[0]; dlon = lons[1]-lons[0]

cov = set()
for gi in W.get('cov', []):
    cov.add(SK[gi])
sk2keys = list(TB.keys())
sla = {k: STA[k][0] for k in sk2keys}
slo = {k: STA[k][1] for k in sk2keys}
WALK_MAX = 12.0

tpb = [[None]*nC for _ in range(nR)]
for r in range(nR):
    lat = lats[r]
    for c in range(nC):
        lon = lons[c]
        if not Z['zone'][r][c]: continue
        ci = r*nC + c
        cands = {}
        for p in range(0, len(W['cells'][ci]), 2):
            cands[SK[W['cells'][ci][p]]] = W['cells'][ci][p+1]
        for k in sk2keys:
            if k in cov or k in cands: continue
            w = walk_min(lat, lon, sla[k], slo[k])
            if w < cands.get(k, 1e9): cands[k] = w
        best = None
        for k, w in cands.items():
            if w > WALK_MAX: continue
            t = TB.get(k)
            if t is None: continue
            if best is None or t < best: best = t
        tpb[r][c] = best

Z['tpb'] = tpb
json.dump(Z, open('/home/ubuntu/zona_final.json', 'w'))
vals = [v for row in tpb for v in row if v is not None]
print('celdas con TP a CGS:', len(vals), 'min', round(min(vals)), 'max', round(max(vals)))
