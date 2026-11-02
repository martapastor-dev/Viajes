# -*- coding: utf-8 -*-
"""
Calcula isocronas de tiempo en transporte publico (Metro + Metro Ligero +
Cercanias, sin bus, con transbordos) hasta Plaza Santa Barbara 2
(metro Alonso Martinez) e inyecta tres capas azules en mapa.html.

Los tiempos se derivan de los GTFS oficiales del CRTM (gtfs/*.zip):
  - trayecto entre paradas: horario programado (stop_times)
  - espera: mitad del headway de punta de manana (7-10h)
  - transbordo: 4 min a pie entre andenes + espera de la nueva linea
  - acceso inicial a anden: 3 min
Al tiempo de transporte se aplica el factor 0,9 pedido por el usuario.
La parte a pie (celda -> estacion / estacion -> plaza) no se escala.
"""

import csv
import io
import json
import math
import os
import re
import zipfile
import heapq
import statistics

import numpy as np

GTFS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gtfs")
OUT_DIR = os.path.dirname(os.path.abspath(__file__))

WALK_SPEED_KMH = 4.8
DETOUR = 1.3           # factor de desvio respecto a linea recta
TRANSFER_WALK_MIN = 4.0
ACCESS_MIN = 3.0       # entrar a la estacion y llegar al anden
TP_FACTOR = 0.9        # correccion del usuario sobre los tiempos en TP
GRID_STEP_DEG = 0.0035  # ~ 350-390 m en lat; ajustado por cos(lat) en lon
DEST_WALK_MIN = 2.0    # Alonso Martinez -> Plaza Santa Barbara 2
PLAZA = (40.4279, -3.6964)  # Plaza Santa Barbara 2 (junto a Alonso Martinez)

FEEDS = [
    ("metro",        "metro.zip",        {"4_I14"}),            # servicio L-J
    ("metro_ligero", "metro_ligero.zip", {"10_I14"}),           # servicio L-J
    ("cercanias",    "cercanias.zip",    None),                 # se elige dia laborable
]

CERC_DATE = "20261104"  # miercoles dentro de la vigencia del feed


def h2s(t):
    """'HH:MM:SS' -> segundos (acepta horas >24)."""
    h, m, s = t.split(":")
    return int(h) * 3600 + int(m) * 60 + int(s)


def hav(lat1, lon1, lat2, lon2):
    """Distancia haversine en km."""
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def walk_min(lat1, lon1, lat2, lon2):
    return hav(lat1, lon1, lat2, lon2) * DETOUR / WALK_SPEED_KMH * 60.0


def read_csv(zf, name):
    with zf.open(name) as f:
        return list(csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig")))


def load_feed(tag, zipname, services_wanted):
    """
    Devuelve:
      par2sta: dict stop_id -> station_key
      stations: dict station_key -> (lat, lon, name)
      edges: list (sta_u, sta_v, travel_min, route_key)
      wait: dict route_key -> minutos de espera media
      route_names: dict route_key -> nombre corto
    """
    zf = zipfile.ZipFile(os.path.join(GTFS_DIR, zipname))
    stops = read_csv(zf, "stops.txt")
    trips = read_csv(zf, "trips.txt")
    stimes = read_csv(zf, "stop_times.txt")
    routes = read_csv(zf, "routes.txt")
    cal = read_csv(zf, "calendar.txt")

    if services_wanted is None:
        services_wanted = {
            r["service_id"] for r in cal
            if r["wednesday"] == "1"
            and r["start_date"] <= CERC_DATE <= r["end_date"]
        }
        print(f"  [{tag}] servicios {CERC_DATE}: {sorted(services_wanted)}")

    par2sta, stations = {}, {}
    for s in stops:
        sid = s["stop_id"]
        lat, lon = float(s["stop_lat"]), float(s["stop_lon"])
        if tag == "cercanias":
            par2sta[sid] = f"cer_{sid}"
            stations[f"cer_{sid}"] = (lat, lon, s["stop_name"])
        else:
            lt = s.get("location_type", "0")
            if lt == "1":
                stations[f"{tag}_{sid}"] = (lat, lon, s["stop_name"])
            elif lt == "0":
                parent = s.get("parent_station") or sid
                par2sta[sid] = f"{tag}_{parent}"
                if parent == sid:
                    stations[f"{tag}_{parent}"] = (lat, lon, s["stop_name"])
    # estaciones sin entrada explicita (parent de pars sin est_)
    for s in stops:
        if tag != "cercanias" and s.get("location_type", "0") == "0":
            parent = s.get("parent_station") or s["stop_id"]
            key = f"{tag}_{parent}"
            if key not in stations:
                stations[key] = (float(s["stop_lat"]), float(s["stop_lon"]),
                                 s["stop_name"])
    # pars sin parent_station -> asignar a la est 'est_' mas cercana (<250 m)
    if tag != "cercanias":
        est_keys = [k for k in stations
                    if k.startswith(f"{tag}_est_")]
        remapped = 0
        for s in stops:
            if s.get("location_type", "0") != "0" or s.get("parent_station"):
                continue
            key = f"{tag}_{s['stop_id']}"
            if key not in stations:
                continue
            la, lo = float(s["stop_lat"]), float(s["stop_lon"])
            best_k, best_d = None, 0.25
            for ek in est_keys:
                ea, eo, _ = stations[ek]
                d = hav(la, lo, ea, eo)
                if d < best_d:
                    best_k, best_d = ek, d
            if best_k:
                par2sta[s["stop_id"]] = best_k
                del stations[key]
                remapped += 1
        print(f"  [{tag}] pars sin parent reasignados: {remapped}")

    rname = {r["route_id"]: (r["route_short_name"] or r["route_id"]).strip()
             for r in routes}
    rtype = {r["route_id"]: r["route_type"] for r in routes}
    trip_route = {t["trip_id"]: t["route_id"] for t in trips
                  if t["service_id"] in services_wanted}
    # descartar trips de otros servicios; excluir route_type bus (3)
    trip_route = {k: v for k, v in trip_route.items()
                  if rtype.get(v) != "3"}

    by_trip = {}
    for st in stimes:
        tid = st["trip_id"]
        if tid in trip_route:
            by_trip.setdefault(tid, []).append(
                (int(st["stop_sequence"]), h2s(st["arrival_time"]),
                 st["stop_id"]))

    edges = []
    for tid, seq in by_trip.items():
        seq.sort()
        rk = f"{tag}_{trip_route[tid]}"
        for (s0, t0, p0), (s1, t1, p1) in zip(seq, seq[1:]):
            u, v = par2sta.get(p0), par2sta.get(p1)
            if u is None or v is None or u == v:
                continue
            edges.append((u, v, (t1 - t0) / 60.0, rk))

    # espera media = headway_punta/2
    wait = {}
    if tag == "metro":
        freqs = read_csv(zf, "frequencies.txt")
        by_trip_head = {}
        for fr in freqs:
            tid = fr["trip_id"]
            if tid in trip_route:
                if h2s(fr["start_time"]) <= 8 * 3600 < h2s(fr["end_time"]):
                    by_trip_head[tid] = int(fr["headway_secs"])
        per_route = {}
        for tid, hsec in by_trip_head.items():
            per_route.setdefault(f"{tag}_{trip_route[tid]}", []).append(hsec)
        for rk, hs in per_route.items():
            wait[rk] = statistics.median(hs) / 120.0
    else:
        # headway por ruta: intervalo medio entre salidas del 1er stop, 7-10h
        first_dep = {}
        for tid, seq in by_trip.items():
            seq.sort()
            rk = f"{tag}_{trip_route[tid]}"
            first_dep.setdefault(rk, []).append(seq[0][1])
        for rk, deps in first_dep.items():
            deps = sorted(d for d in deps if 7 * 3600 <= d <= 10 * 3600)
            gaps = [b - a for a, b in zip(deps, deps[1:]) if b - a > 0]
            if gaps:
                head = statistics.median(gaps)
            else:
                head = 900 if tag == "cercanias" else 600
            wait[rk] = min(head / 120.0, 15.0)

    print(f"  [{tag}] estaciones={len(stations)} edges={len(edges)} "
          f"rutas={len(wait)}")
    return par2sta, stations, edges, wait, \
        {f"{tag}_{rid}": n for rid, n in rname.items()}


# ---------------------------------------------------------------- carga
print("Cargando GTFS...")
par2sta, stations, edges, wait, rname = {}, {}, [], {}, {}
for tag, zn, sv in FEEDS:
    p, s, e, w, rn = load_feed(tag, zn, sv)
    par2sta.update(p)
    stations.update(s)
    edges.extend(e)
    wait.update(w)
    rname.update(rn)

# minimizar travel por (u,v,rk) para aligerar el grafo
best = {}
for u, v, t, rk in edges:
    k = (u, v, rk)
    if k not in best or t < best[k]:
        best[k] = t
edges = [(u, v, t, rk) for (u, v, rk), t in best.items()]
print(f"Edges unicos: {len(edges)}")

# ------------------------------------------------- transbordos entre redes
# enlaces a pie entre estaciones de feeds distintos a < 350 m
keys = list(stations)
transfer_edges = []
for i, a in enumerate(keys):
    for b in keys[i + 1:]:
        if a.split("_")[0] == b.split("_")[0]:
            continue
        la, loa, _ = stations[a]
        lb, lob, _ = stations[b]
        d = hav(la, loa, lb, lob)
        if d < 0.35:
            w = max(walk_min(la, loa, lb, lob), 4.0)
            transfer_edges.append((a, b, w))
            transfer_edges.append((b, a, w))
print(f"Enlaces a pie entre redes: {len(transfer_edges) // 2}")

# ------------------------------------------------- grafo y Dijkstra inverso
adj = {}
for u, v, t, rk in edges:
    adj.setdefault(v, []).append((u, t, rk))   # grafo invertido
for a, b, w in transfer_edges:
    adj.setdefault(b, []).append((a, w, "WALK"))

AM_STAS = [k for k, (la, lo, n) in stations.items()
           if n.upper() == "ALONSO MARTINEZ"]
print(f"Estaciones destino: {AM_STAS}")

# estado = (estacion, ruta saliente forward); coste al retroceder:
# travel(edge) + [route(edge) != state.route ? wait[state.route] + pen : 0]
# si state.route is None (destino) -> solo travel. WALK no paga transbordo.
INF = float("inf")
dist = {}
pred = {}   # (u, rk) -> (v, rout): estado del que se relajó la arista u->v con ruta rk
pq = []
for s in AM_STAS:
    dist[(s, None)] = 0.0
    heapq.heappush(pq, (0.0, s, None))

while pq:
    d, v, rout = heapq.heappop(pq)
    if d > dist.get((v, rout), INF):
        continue
    for u, t, rk in adj.get(v, []):
        extra = t
        if rout is not None and rk != rout:
            extra += wait.get(rout, 3.0)
            if rk != "WALK" and rout != "WALK":
                extra += TRANSFER_WALK_MIN
        nd = d + extra
        key = (u, rk)
        if nd < dist.get(key, INF):
            dist[key] = nd
            pred[key] = (v, rout)
            heapq.heappush(pq, (nd, u, rk))

# tiempo estacion -> destino: embarque inicial paga espera + acceso
T = {}
best_state = {}   # station -> rk que da el minimo T
for (s, rk), d in dist.items():
    if rk is None:
        t = d
    else:
        t = d + wait.get(rk, 3.0) + ACCESS_MIN
    if s not in T or t < T[s]:
        T[s] = t
        best_state[s] = rk

# aplicar factor 0,9 al tramo en TP
T = {s: t * TP_FACTOR for s, t in T.items()}


# ---------------------------------------------------------------- helpers de ruta
def rline(rk):
    """Nombre de linea legible: 'L4', 'ML1', 'C8b', 'a pie'."""
    rn = rname.get(rk, "")
    if rk == "WALK":
        return "a pie"
    if rk.startswith("metro_") and not rk.startswith("metro_ligero_") and rn.isdigit():
        return "L" + rn
    return rn or rk.split("_")[-1]


def get_path(sta):
    """Reconstruye el camino (sta, rk)... desde sta hasta Alonso Martinez."""
    rk = best_state.get(sta)
    if rk is None:
        return []
    path = [(sta, rk)]
    visited = {(sta, rk)}
    state = (sta, rk)
    for _ in range(40):
        state = pred.get(state)
        if state is None or state in visited:
            break
        visited.add(state)
        path.append(state)
        if state[1] is None:
            break
    return path


def describe_route(sta):
    """Genera texto de instrucciones: 'Toma L4 · cambia en Sol a L5 → Alonso Martínez'."""
    path = get_path(sta)
    if not path:
        return "Estás en Alonso Martínez"
    am_set = set(AM_STAS)

    segments = []          # (rk, from_sta, to_sta)
    seg_start = path[0][0]
    seg_route = path[0][1]
    for s2, rk2 in path[1:]:
        if rk2 != seg_route:
            if seg_route is not None:
                segments.append((seg_route, seg_start, s2))
            seg_start = s2
            seg_route = rk2
            if rk2 is None:
                break
    else:
        if seg_route is not None:
            segments.append((seg_route, seg_start, path[-1][0]))

    if not segments:
        return "Estás en Alonso Martínez"

    def sname(k):
        if k in am_set:
            return "Alonso Martínez"
        raw = stations.get(k, ("", "", k))[2]
        # Normalizar MAYUSCULAS a Title Case
        if raw == raw.upper() and len(raw) > 2:
            raw = raw.title()
        return raw

    parts = []
    for i, (rk, from_s, to_s) in enumerate(segments):
        ln = rline(rk)
        if rk == "WALK":
            parts.append(f"camina a {sname(to_s)}")
        elif i == 0:
            parts.append(f"Toma {ln}")
        else:
            parts.append(f"cambia en {sname(from_s)} a {ln}")
    return " · ".join(parts) + " → Alonso Martínez"

# llegada a pie a la plaza: min(T[s]+DEST_WALK, min_s' T[s']+walk(s',plaza))
plat, plon = PLAZA
D = {}
for s in stations:
    la, lo, _ = stations[s]
    D[s] = min(T.get(s, INF) + DEST_WALK_MIN,
               min(T.get(s2, INF) + walk_min(la, lo, plat, plon)
                   for s2 in stations))

print("\nEjemplos estacion -> Alonso Martinez (min, tras x0,9):")
for probe in ["SOL", "NUEVOS MINISTERIOS", "CHAMART", "MONCLOA",
              "ATOCHA", "BOADILLA", "ALPEDRETE", "ATOCHA"]:
    for s, (la, lo, n) in stations.items():
        if probe in n.upper():
            print(f"  {s:28s} {n:32s} {D[s]:6.1f}")

# ---------------------------------------------------------------- rejilla
lat0, lat1 = 40.196, 40.658
lon0, lon1 = -4.0352, -3.5270
lats = np.arange(lat0, lat1, GRID_STEP_DEG)
lons = np.arange(lon0, lon1, GRID_STEP_DEG / math.cos(math.radians(40.43)))
LA, LO = np.meshgrid(lats, lons, indexing="ij")  # (rows, cols)

sla = np.array([stations[s][0] for s in stations], dtype=np.float32)
slo = np.array([stations[s][1] for s in stations], dtype=np.float32)
sD = np.array([D.get(s, 120.0) for s in stations], dtype=np.float32)
skeys = list(stations)

times = np.full(LA.shape, 120.0, dtype=np.float32)
R = 6371.0
for i in range(0, len(skeys), 64):
    dlat = np.deg2rad(LA[:, :, None] - sla[i:i + 64])
    dlon = np.deg2rad(LO[:, :, None] - slo[i:i + 64])
    a = np.sin(dlat / 2) ** 2 + np.cos(np.deg2rad(LA[:, :, None])) \
        * np.cos(np.deg2rad(sla[i:i + 64])) * np.sin(dlon / 2) ** 2
    dist_km = 2 * R * np.arcsin(np.sqrt(a))
    twalk = dist_km * DETOUR / WALK_SPEED_KMH * 60.0
    times = np.minimum(times, (twalk + sD[i:i + 64]).min(axis=2))

# opcion ir andando directamente a la plaza
dlat = np.deg2rad(LA - plat)
dlon = np.deg2rad(LO - plon)
a = np.sin(dlat / 2) ** 2 + np.cos(np.deg2rad(LA)) \
    * math.cos(math.radians(plat)) * np.sin(dlon / 2) ** 2
direct = 2 * R * np.arcsin(np.sqrt(a)) * DETOUR / WALK_SPEED_KMH * 60.0
times = np.minimum(times, direct)

print(f"\nRejilla {times.shape}, %<=30: {(times <= 30).mean() * 100:.1f}%"
      f"  <=40: {(times <= 40).mean() * 100:.1f}%"
      f"  <=50: {(times <= 50).mean() * 100:.1f}%")

# ---------------------------------------------------------------- contornos
from skimage import measure
from shapely.geometry import Polygon, MultiPolygon, mapping
from shapely.ops import unary_union


def band_poly(level):
    """Poligono del area times<=level como MultiPolygon GeoJSON-ish."""
    cs = measure.find_contours(times.astype(float), level)
    polys = []
    dlat_step = lats[1] - lats[0]
    dlon_step = lons[1] - lons[0]
    for c in cs:
        if len(c) < 4:
            continue
        lonlat = [(lon0 + col * dlon_step, lat0 + row * dlat_step)
                  for row, col in c]
        try:
            polys.append(Polygon(lonlat))
        except Exception:
            pass
    if not polys:
        return None
    u = unary_union(polys)
    if u.geom_type == "Polygon":
        u = MultiPolygon([u])
    # rellenar agujeros y simplificar
    cleaned = []
    for p in u.geoms:
        q = Polygon(p.exterior).simplify(0.0006, preserve_topology=True)
        if q.area > 1e-5:
            cleaned.append(q)
    return MultiPolygon(cleaned) if len(cleaned) > 1 else cleaned[0]


bands = {}
for lvl in (30, 40, 50):
    geom = band_poly(lvl)
    bands[lvl] = geom
    n = len(geom.geoms) if geom and geom.geom_type == "MultiPolygon" else 1
    print(f"Banda <={lvl}: {'ok' if geom else 'VACIA'} polys={n}")

fc = {}
for lvl, geom in bands.items():
    fc[lvl] = {
        "type": "FeatureCollection",
        "features": [{"type": "Feature",
                      "properties": {"level": lvl},
                      "geometry": mapping(geom)}],
    }

with open(os.path.join(OUT_DIR, "isocronas_tp.json"), "w",
          encoding="utf-8") as f:
    json.dump({"30": fc[30], "40": fc[40], "50": fc[50],
               "T": {k: round(v, 2) for k, v in T.items()}}, f)
print("\nGuardado isocronas_tp.json")

# ---------------------------------------------------------------- accesos por coordenada
# Para cada parada GTFS visible en el mapa (accesos + andenes + estaciones cercanias)
# generamos un lookup (lat4_lon4 -> {t, r, n}) para los popups del mapa.
print("\nGenerando accesos_tp.json...")
acc_lookup = {}   # "lat4_lon4" -> {t, r, n}

for tag, zipname, _ in FEEDS:
    zf2 = zipfile.ZipFile(os.path.join(GTFS_DIR, zipname))
    stops2 = read_csv(zf2, "stops.txt")
    for s in stops2:
        lt = s.get("location_type", "0")
        if tag == "cercanias":
            if lt not in ("0", ""):
                continue
            sta_key = f"cer_{s['stop_id']}"
        else:
            if lt not in ("0", "1", "2"):
                continue
            if lt == "1":
                sta_key = f"{tag}_{s['stop_id']}"
            else:
                parent = s.get("parent_station") or s["stop_id"]
                sta_key = f"{tag}_{parent}"

        if sta_key not in T:
            continue

        la, lo = float(s["stop_lat"]), float(s["stop_lon"])
        tm = round(T[sta_key], 1)
        route_txt = describe_route(sta_key)

        # clave con 4 decimales (~11 m precision) y también con 5 como alternativa
        key4 = f"{la:.4f}_{lo:.4f}"
        key5 = f"{la:.5f}_{lo:.5f}"
        entry = {"t": tm, "r": route_txt, "n": s["stop_name"]}
        acc_lookup[key4] = entry
        acc_lookup[key5] = entry

print(f"  Entradas en lookup: {len(acc_lookup)}")
with open(os.path.join(OUT_DIR, "accesos_tp.json"), "w", encoding="utf-8") as f:
    json.dump(acc_lookup, f, ensure_ascii=False, separators=(",", ":"))
print("Guardado accesos_tp.json")
