# -*- coding: utf-8 -*-
"""
Genera hestia/dinamico/datos_tp.js y hestia/dinamico/metro_sombra.js
para la app interactiva de accesibilidad dinamica.

Ejecutar una vez (o cuando cambien los GTFS o el mapa base):
    python exportar_datos_dinamico.py
"""

import csv, io, json, math, os, re, statistics, zipfile

BASE     = os.path.dirname(os.path.abspath(__file__))
GTFS_DIR = os.path.join(BASE, "gtfs")
OUT_DIR  = os.path.join(BASE, "dinamico")
BACKUP   = os.path.join(BASE, "mapa_backup.html")

WALK_KMH         = 4.8
DETOUR           = 1.3
TRANSFER_WALK_MIN = 4.0
ACCESS_MIN       = 3.0
TP_FACTOR        = 0.9
CERC_DATE        = "20261104"
FEEDS = [
    ("metro",        "metro.zip",        {"4_I14"}),
    ("metro_ligero", "metro_ligero.zip", {"10_I14"}),
    ("cercanias",    "cercanias.zip",    None),
]

os.makedirs(OUT_DIR, exist_ok=True)


# ----------------------------------------------------------------- helpers
def h2s(t):
    h, m, s = t.split(":"); return int(h)*3600+int(m)*60+int(s)

def hav(la1, lo1, la2, lo2):
    R = 6371.0
    p1, p2 = math.radians(la1), math.radians(la2)
    dp, dl = p2-p1, math.radians(lo2-lo1)
    a = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2*R*math.asin(math.sqrt(a))

def wmin(la1, lo1, la2, lo2):
    return hav(la1,lo1,la2,lo2) * DETOUR / WALK_KMH * 60.0

def read_csv(zf, name):
    with zf.open(name) as f:
        return list(csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig")))


# ----------------------------------------------------------------- carga GTFS
print("Cargando GTFS...")
par2sta, stations, edges, wait, rname_raw = {}, {}, [], {}, {}

for tag, zn, svc_want in FEEDS:
    zf = zipfile.ZipFile(os.path.join(GTFS_DIR, zn))
    stops  = read_csv(zf, "stops.txt")
    trips  = read_csv(zf, "trips.txt")
    stimes = read_csv(zf, "stop_times.txt")
    routes = read_csv(zf, "routes.txt")
    cal    = read_csv(zf, "calendar.txt")

    if svc_want is None:
        svc_want = {r["service_id"] for r in cal
                    if r["wednesday"]=="1"
                    and r["start_date"]<=CERC_DATE<=r["end_date"]}

    p2s, sta = {}, {}
    for s in stops:
        sid = s["stop_id"]
        la, lo = float(s["stop_lat"]), float(s["stop_lon"])
        if tag == "cercanias":
            p2s[sid] = f"cer_{sid}"
            sta[f"cer_{sid}"] = (la, lo, s["stop_name"])
        else:
            lt = s.get("location_type","0")
            if lt == "1":
                sta[f"{tag}_{sid}"] = (la, lo, s["stop_name"])
            elif lt == "0":
                parent = s.get("parent_station") or sid
                p2s[sid] = f"{tag}_{parent}"
                if parent == sid:
                    sta[f"{tag}_{parent}"] = (la, lo, s["stop_name"])

    for s in stops:
        if tag != "cercanias" and s.get("location_type","0") == "0":
            parent = s.get("parent_station") or s["stop_id"]
            key = f"{tag}_{parent}"
            if key not in sta:
                sta[key] = (float(s["stop_lat"]), float(s["stop_lon"]), s["stop_name"])

    if tag != "cercanias":
        est_keys = [k for k in sta if k.startswith(f"{tag}_est_")]
        for s in stops:
            if s.get("location_type","0") != "0" or s.get("parent_station"):
                continue
            key = f"{tag}_{s['stop_id']}"
            if key not in sta:
                continue
            la, lo = float(s["stop_lat"]), float(s["stop_lon"])
            best_k, best_d = None, 0.25
            for ek in est_keys:
                ea, eo, _ = sta[ek]
                d = hav(la, lo, ea, eo)
                if d < best_d:
                    best_k, best_d = ek, d
            if best_k:
                p2s[s["stop_id"]] = best_k
                del sta[key]

    rn = {r["route_id"]: (r["route_short_name"] or r["route_id"]).strip() for r in routes}
    rt = {r["route_id"]: r["route_type"] for r in routes}
    trip_route = {t["trip_id"]: t["route_id"] for t in trips if t["service_id"] in svc_want}
    trip_route = {k: v for k, v in trip_route.items() if rt.get(v) != "3"}

    by_trip = {}
    for st in stimes:
        tid = st["trip_id"]
        if tid in trip_route:
            by_trip.setdefault(tid, []).append(
                (int(st["stop_sequence"]), h2s(st["arrival_time"]), st["stop_id"]))

    tag_edges = []
    for tid, seq in by_trip.items():
        seq.sort()
        rk = f"{tag}_{trip_route[tid]}"
        for (s0,t0,p0),(s1,t1,p1) in zip(seq, seq[1:]):
            u, v = p2s.get(p0), p2s.get(p1)
            if u and v and u != v:
                tag_edges.append((u, v, (t1-t0)/60.0, rk))

    tag_wait = {}
    if tag == "metro":
        freqs = read_csv(zf, "frequencies.txt")
        bth = {}
        for fr in freqs:
            tid = fr["trip_id"]
            if tid in trip_route and h2s(fr["start_time"])<=8*3600<h2s(fr["end_time"]):
                bth[tid] = int(fr["headway_secs"])
        per_rt = {}
        for tid, hs in bth.items():
            per_rt.setdefault(f"{tag}_{trip_route[tid]}", []).append(hs)
        for rk, hs in per_rt.items():
            tag_wait[rk] = statistics.median(hs) / 120.0
    else:
        first_dep = {}
        for tid, seq in by_trip.items():
            seq.sort()
            rk = f"{tag}_{trip_route[tid]}"
            first_dep.setdefault(rk, []).append(seq[0][1])
        for rk, deps in first_dep.items():
            deps = sorted(d for d in deps if 7*3600<=d<=10*3600)
            gaps = [b-a for a,b in zip(deps,deps[1:]) if b-a>0]
            head = statistics.median(gaps) if gaps else (900 if tag=="cercanias" else 600)
            tag_wait[rk] = min(head/120.0, 15.0)

    par2sta.update(p2s)
    stations.update(sta)
    edges.extend(tag_edges)
    wait.update(tag_wait)
    rname_raw.update({f"{tag}_{rid}": n for rid, n in rn.items()})
    print(f"  [{tag}] estaciones={len(sta)} aristas={len(tag_edges)}")

# minimizar aristas
best = {}
for u, v, t, rk in edges:
    k = (u, v, rk)
    if k not in best or t < best[k]:
        best[k] = t
edges = [(u, v, t, rk) for (u, v, rk), t in best.items()]
print(f"Aristas unicas: {len(edges)}")

# transferencias entre redes
keys = list(stations)
xfer = []
for i, a in enumerate(keys):
    for b in keys[i+1:]:
        if a.split("_")[0] == b.split("_")[0]:
            continue
        la, loa, _ = stations[a]
        lb, lob, _ = stations[b]
        d = hav(la, loa, lb, lob)
        if d < 0.35:
            w = max(wmin(la, loa, lb, lob), 4.0)
            xfer.append((a, b, w))
            xfer.append((b, a, w))
print(f"Transferencias: {len(xfer)//2}")


# ----------------------------------------------------------------- display name
def dname(rk, rn):
    if rk.startswith("metro_") and not rk.startswith("metro_ligero_") and rn.isdigit():
        return "L" + rn
    return rn


# ----------------------------------------------------------------- exportar datos_tp.js
all_sk = list(stations.keys())
all_rk = sorted(set(e[3] for e in edges) | set(wait.keys()))
sI = {k: i for i, k in enumerate(all_sk)}
rI = {k: i for i, k in enumerate(all_rk)}

grafo = {
    "p": {
        "XFER": TRANSFER_WALK_MIN, "ACC": ACCESS_MIN, "F": TP_FACTOR,
        "SPD": WALK_KMH, "DET": DETOUR, "STEP": 0.0035,
        "LA0": 40.196, "LA1": 40.658, "LO0": -4.0352, "LO1": -3.527
    },
    "sk": all_sk,
    "rk": all_rk,
    "sd": [[round(stations[k][0],5), round(stations[k][1],5), stations[k][2]]
           for k in all_sk],
    "e":  [[sI[u], sI[v], round(t,3), rI[rk]]
           for u, v, t, rk in edges
           if u in sI and v in sI and rk in rI],
    "te": [[sI[a], sI[b], round(w,3)]
           for a, b, w in xfer
           if a in sI and b in sI],
    "w":  [round(wait.get(rk, 3.0), 3) for rk in all_rk],
    "r":  [dname(rk, rname_raw.get(rk, rk.split("_")[-1])) for rk in all_rk],
}

out1 = os.path.join(OUT_DIR, "datos_tp.js")
with open(out1, "w", encoding="utf-8") as f:
    f.write("// Grafo GTFS - generado por exportar_datos_dinamico.py\n")
    f.write("const GRAFO_TP=")
    json.dump(grafo, f, ensure_ascii=False, separators=(",", ":"))
    f.write(";\n")
print(f"\nGuardado datos_tp.js ({os.path.getsize(out1)//1024} KB)")


# ----------------------------------------------------------------- extraer walking buffers
print("\nExtrayendo capas de andando desde mapa_backup.html...")
with open(BACKUP, encoding="utf-8") as f:
    html = f.read()

WALK_FGS = {
    5:  "feature_group_560a04c6eedaf7d6f178d70d4cd1e4b9",
    10: "feature_group_85e59c1a260026d66e154a14a6313322",
    15: "feature_group_8ec6605c90c847eb69c1a84c37d2afaa",
}

sombra = {}
for mins, fg in WALK_FGS.items():
    m = re.search(rf'(geo_json_\w+)\.addTo\({re.escape(fg)}\)', html)
    if not m:
        print(f"  FG no encontrado: {mins} min"); continue
    gj_var = m.group(1)
    pos = html.find(gj_var + "_add(")
    if pos == -1:
        print(f"  _add() no encontrado para {gj_var}"); continue
    brace = html.index("{", pos)
    depth, p2 = 0, brace
    for ch in html[brace:]:
        if ch == "{": depth += 1
        elif ch == "}": depth -= 1
        if depth == 0: break
        p2 += 1
    try:
        sombra[str(mins)] = json.loads(html[brace:p2+1])
        nf = len(sombra[str(mins)].get("features", []))
        print(f"  Andando {mins} min: {nf} features, {(p2-brace)//1024} KB")
    except Exception as e:
        print(f"  Error JSON ({mins} min): {e}")

out2 = os.path.join(OUT_DIR, "metro_sombra.js")
with open(out2, "w", encoding="utf-8") as f:
    f.write("// Isocronas a pie desde accesos de metro - generado por exportar_datos_dinamico.py\n")
    f.write("const METRO_SOMBRA=")
    json.dump(sombra, f, ensure_ascii=False, separators=(",", ":"))
    f.write(";\n")
print(f"Guardado metro_sombra.js ({os.path.getsize(out2)//1024} KB)")


# ----------------------------------------------------------------- generar líneas de metro desde shapes GTFS
print("\nGenerando líneas de metro/cercanías desde shapes GTFS...")

# Colores por defecto por si la ruta no tiene route_color
DEFAULT_COLORS = {
    "cercanias": "#9b59b6",
    "metro_ligero": "#27ae60",
}

# Para cada feed, generar un shape por ruta (dirección 0 únicamente)
line_features = []

for tag, zn, _ in FEEDS:
    zf2 = zipfile.ZipFile(os.path.join(GTFS_DIR, zn))

    # routes → color y nombre
    with zf2.open("routes.txt") as f:
        rts_list = list(csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig")))
    route_info = {}
    for r in rts_list:
        col = r.get("route_color", "").strip()
        col = "#" + col if col and not col.startswith("#") else (col or DEFAULT_COLORS.get(tag, "#888888"))
        route_info[r["route_id"]] = {
            "color": col,
            "name": (r.get("route_short_name") or r["route_id"]).strip(),
            "long_name": r.get("route_long_name", "").strip(),
        }

    # trips → seleccionar un shape_id por (route_id, direction_id=0)
    with zf2.open("trips.txt") as f:
        trips_list = list(csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig")))
    route_shape = {}  # route_id → shape_id (dir 0)
    for t in trips_list:
        rid = t["route_id"]
        if t.get("direction_id", "0") == "0" and rid not in route_shape:
            route_shape[rid] = t["shape_id"]

    # shapes → coordenadas por shape_id
    with zf2.open("shapes.txt") as f:
        shapes_list = list(csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig")))
    shape_pts = {}
    for s in shapes_list:
        sid = s["shape_id"]
        shape_pts.setdefault(sid, []).append((
            int(s["shape_pt_sequence"]),
            float(s["shape_pt_lon"]),
            float(s["shape_pt_lat"])
        ))

    # Construir features GeoJSON
    for rid, info in route_info.items():
        sid = route_shape.get(rid)
        if not sid or sid not in shape_pts:
            continue
        coords = [[lo, la] for _, lo, la in sorted(shape_pts[sid])]
        if len(coords) < 2:
            continue
        line_features.append({
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": coords},
            "properties": {
                "route": info["name"],
                "name": info["long_name"] or info["name"],
                "color": info["color"],
                "tag": tag,
            }
        })

    print(f"  [{tag}] {len([r for r in route_info if r in route_shape])} líneas")

lineas_fc = {"type": "FeatureCollection", "features": line_features}
out3 = os.path.join(OUT_DIR, "metro_lineas.js")
with open(out3, "w", encoding="utf-8") as f:
    f.write("// Geometría de líneas metro/cercanías - generado por exportar_datos_dinamico.py\n")
    f.write("const METRO_LINEAS=")
    json.dump(lineas_fc, f, ensure_ascii=False, separators=(",", ":"))
    f.write(";\n")
print(f"Guardado metro_lineas.js ({os.path.getsize(out3)//1024} KB)")
print("\nListo. Abrir dinamico/index.html en el navegador.")
