# -*- coding: utf-8 -*-
"""
Genera walk_real.js y walk_minutes.js usando SOLO la caché local en walk_cache/.
No hace ninguna petición de red.

Ejecutar después de que walk_cache/ esté poblada:
    python exportar_walk_real.py

Produce:
  dinamico/walk_real.js    — tiempo andando real (Valhalla) celda→estación
  dinamico/walk_minutes.js — polígono unión por minuto 1-20 para el slider
"""

import json, math, os, sys
from shapely.geometry import shape, Point, mapping
from shapely.ops import unary_union
from shapely.strtree import STRtree

BASE       = os.path.dirname(os.path.abspath(__file__))
OUT_DIR    = os.path.join(BASE, "dinamico")
CACHE_DIR  = os.path.join(BASE, "walk_cache")
TP_JS      = os.path.join(OUT_DIR, "datos_tp.js")
OUT_REAL   = os.path.join(OUT_DIR, "walk_real.js")
OUT_MINS   = os.path.join(OUT_DIR, "walk_minutes.js")
OUT_POLYS  = os.path.join(OUT_DIR, "walk_polys.js")

MAX_WALK = 20

# ── Parámetros de rejilla (idénticos a buildGrid en index.html) ───────────────
LA0, LA1 = 40.196, 40.658
LO0, LO1 = -4.0352, -3.527
STEP      = 0.0035
DLAT      = STEP
DLON      = STEP / math.cos(math.radians(LA0))

lats, lons = [], []
la = LA0
while la < LA1: lats.append(la); la += DLAT
lo = LO0
while lo < LO1: lons.append(lo); lo += DLON
nR, nC = len(lats), len(lons)
print(f"Rejilla: {nR}×{nC} = {nR*nC:,} celdas")

# ── Leer estaciones ───────────────────────────────────────────────────────────
print("Leyendo datos_tp.js…")
with open(TP_JS, encoding="utf-8") as f:
    raw = f.read()
json_str = raw[raw.index("const GRAFO_TP=") + len("const GRAFO_TP="):raw.rindex(";")]
grafo    = json.loads(json_str)
sk_list  = grafo["sk"]
sd_list  = grafo["sd"]
n_sta    = len(sk_list)
print(f"Estaciones: {n_sta}")

# ── Cargar caché ──────────────────────────────────────────────────────────────
def cache_path(sk):
    return os.path.join(CACHE_DIR, sk.replace("/", "_").replace(":", "_") + ".json")

def load_cache(sk):
    cp = cache_path(sk)
    if not os.path.exists(cp):
        return None
    with open(cp, encoding="utf-8") as f:
        raw = json.load(f)
    result = {}
    for ks, geo in raw.items():
        try:
            k = int(float(ks))   # acepta '4' y '4.0'
            g = shape(geo)
            if not g.is_valid:
                g = g.buffer(0)
            result[k] = g
        except Exception:
            pass
    return result if result else None

print("Cargando caché…")
sta_isos  = []   # dict k→Shapely o None por estación
cov_idxs  = []   # índices globales (en sk_list) con isócrona disponible
n_ok = 0

for i, sk in enumerate(sk_list):
    sys.stdout.write(f"\r  [{i+1}/{n_sta}] {sk:<40s}")
    sys.stdout.flush()
    iso = load_cache(sk)
    sta_isos.append(iso)
    if iso:
        n_ok += 1
        cov_idxs.append(i)

print(f"\nEstaciones con datos: {n_ok}/{n_sta}")

# ── STRtree sobre polígono de mayor minuto disponible de cada estación ────────
index_geoms, index_meta = [], []
for si in cov_idxs:
    iso = sta_isos[si]
    # Polígono más grande disponible (mayor minuto)
    best_poly = None
    for k in range(MAX_WALK, 0, -1):
        p = iso.get(k)
        if p and not p.is_empty:
            best_poly = p
            break
    if best_poly:
        index_geoms.append(best_poly)
        index_meta.append(si)

print(f"STRtree: {len(index_geoms)} estaciones")
tree = STRtree(index_geoms)

# ── Calcular walk_real por celda ──────────────────────────────────────────────
print("Calculando tiempos por celda…")
cells_data = []   # [[si, wm, si, wm, ...], ...]  — pares planos

for r in range(nR):
    la = lats[r] + DLAT / 2   # centro de la celda
    for c in range(nC):
        lo = lons[c] + DLON / 2
        ci = r * nC + c
        if ci % 1500 == 0:
            sys.stdout.write(f"\r  {ci}/{nR*nC}")
            sys.stdout.flush()

        pt = Point(lo, la)
        hits = tree.query(pt, predicate="within")
        if len(hits) == 0:
            cells_data.append([])
            continue

        sta_times = []
        for h in hits:
            si = index_meta[h]
            iso = sta_isos[si]
            walk_min = None
            for k in range(1, MAX_WALK + 1):
                poly_k = iso.get(k)
                if poly_k is None or poly_k.is_empty:
                    continue
                if poly_k.contains(pt):
                    walk_min = k
                    break
            if walk_min is not None:
                sta_times.append((si, walk_min))

        sta_times.sort(key=lambda x: x[1])
        flat = []
        for si, wm in sta_times[:6]:
            flat.append(si); flat.append(wm)
        cells_data.append(flat)

print(f"\r  {nR*nC}/{nR*nC} OK")

# ── Generar walk_minutes por minuto 1-20 ─────────────────────────────────────
print("Generando walk_minutes (unión por minuto)…")
walk_minutes = {}
for k in range(1, MAX_WALK + 1):
    polys_k = []
    for iso in sta_isos:
        if iso is None:
            continue
        p = iso.get(k)
        if p and not p.is_empty:
            polys_k.append(p)
    if not polys_k:
        print(f"  k={k:2d}: sin datos")
        continue
    union_k = unary_union(polys_k).simplify(0.00025, preserve_topology=True)
    walk_minutes[k] = {
        "type": "FeatureCollection",
        "features": [{"type": "Feature",
                       "geometry": mapping(union_k),
                       "properties": {"minutes": k}}]
    }
    sys.stdout.write(f"\r  k={k:2d} OK")
    sys.stdout.flush()
print()

# ── Escribir walk_real.js ─────────────────────────────────────────────────────
print("Escribiendo walk_real.js…")
obj = {
    "nR": nR, "nC": nC,
    "la0": LA0, "lo0": LO0,
    "dlat": round(DLAT, 8), "dlon": round(DLON, 8),
    "cov": cov_idxs,          # índices globales con datos reales
    "cells": cells_data
}
with open(OUT_REAL, "w", encoding="utf-8") as f:
    f.write("// Tiempos andando reales (Valhalla) por celda - exportar_walk_real.py\n")
    f.write("var WALK_REAL=")
    json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
    f.write(";\n")
print(f"  {os.path.getsize(OUT_REAL)//1024} KB")

# ── Escribir walk_minutes.js ──────────────────────────────────────────────────
print("Escribiendo walk_minutes.js…")
with open(OUT_MINS, "w", encoding="utf-8") as f:
    f.write("// Polígonos peatonales reales por minuto 1-20 - exportar_walk_real.py\n")
    f.write("var WALK_MINUTES=")
    json.dump({str(k): v for k, v in walk_minutes.items()},
              f, ensure_ascii=False, separators=(",", ":"))
    f.write(";\n")
print(f"  {os.path.getsize(OUT_MINS)//1024} KB")

# ── Escribir walk_polys.js (polígonos por estación y minuto) ─────────────────
print("Escribiendo walk_polys.js…")

def _round_coords(x, nd=4):
    if isinstance(x, (int, float)):
        return round(x, nd)
    return [_round_coords(v, nd) for v in x]

SIMP = 0.0004   # ~40 m de tolerancia

# Anillos exteriores orientados CCW: con fillRule:'nonzero' en Leaflet las
# zonas solapadas suman winding>0 y la unión se rellena (no se anula)
try:
    from shapely.geometry.polygon import orient as _orient
    def _ccw(g): return _orient(g, sign=1.0)
except Exception:
    def _ccw(g): return g

polys_obj = {}
for si in cov_idxs:
    iso = sta_isos[si]
    d_si = {}
    for k in range(1, MAX_WALK + 1):
        p = iso.get(k)
        if p is None or p.is_empty:
            continue
        sp = _ccw(p.simplify(SIMP, preserve_topology=True))
        if sp.is_empty:
            continue
        coords = mapping(sp)["coordinates"]
        if sp.geom_type == "Polygon":
            coords = [coords]          # formato MultiPolygon
        d_si[k] = _round_coords(coords, 4)
    if d_si:
        polys_obj[si] = d_si

with open(OUT_POLYS, "w", encoding="utf-8") as f:
    f.write("// Polígonos peatonales por estación y minuto - exportar_walk_real.py\n")
    f.write("var WALK_POLYS=")
    json.dump(polys_obj, f, ensure_ascii=False, separators=(",", ":"))
    f.write(";\n")
print(f"  {os.path.getsize(OUT_POLYS)//1024} KB")
print("\nListo.")
