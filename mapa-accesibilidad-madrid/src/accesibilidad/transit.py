"""Descarga y normalización de las redes del CRTM a estaciones, accesos y líneas.

Fuente: servicios "Datos abiertos: Elementos de la Red de ..." del CRTM (ArcGIS),
que están más actualizados que los GTFS publicados y siguen el mismo esquema para
Metro, Cercanías, Metro Ligero y autobuses.
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
import urllib.parse
import urllib.request

import geopandas as gpd
import pandas as pd
from shapely.ops import linemerge, unary_union

from . import config

log = logging.getLogger(__name__)

DEDUP_DISTANCE_M = 400
LAYER_STATIONS, LAYER_ACCESS, LAYER_SEGMENTS = 0, 1, 4
PAGE_SIZE = 1000


def fetch_layer(service: str, layer: int, force: bool = False) -> gpd.GeoDataFrame:
    """Descarga (con caché en disco) una capa completa de un FeatureServer del CRTM."""
    dest = config.RAW_DIR / f"crtm_{service}_{layer}.geojson"
    if dest.exists() and not force:
        return gpd.read_file(dest)
    features, offset = [], 0
    while True:
        params = {
            "where": "1=1",
            "outFields": "*",
            "outSR": "4326",
            "f": "geojson",
            "resultOffset": offset,
            "resultRecordCount": PAGE_SIZE,
            "orderByFields": "OBJECTID",
        }
        url = f"{config.CRTM_SERVICES_URL}/{service}/FeatureServer/{layer}/query?" + urllib.parse.urlencode(params)
        with urllib.request.urlopen(url, timeout=120) as resp:
            data = json.load(resp)
        page = data.get("features", [])
        features.extend(page)
        if not page or not data.get("properties", {}).get("exceededTransferLimit"):
            break
        offset += len(page)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps({"type": "FeatureCollection", "features": features}))
    log.info("Descargada capa %s/%s (%d elementos)", service, layer, len(features))
    return gpd.read_file(dest)


def normalize_name(name: str) -> str:
    s = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"^(intercambiador de|estacion de)\s+", "", s)
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


_LOWER_WORDS = {"de", "del", "la", "las", "los", "el", "y", "a"}
_ROMAN = re.compile(r"^(?=[ivxlc]+$)c{0,3}(xc|xl|l?x{0,3})(ix|iv|v?i{0,3})$", re.IGNORECASE)


def pretty_name(name: str) -> str:
    name = re.sub(r"\s+", " ", str(name)).strip()
    # El CRTM escribe algunos nombres como "Aguilas, las": se reordenan a "Las Aguilas".
    m = re.match(r"^(.*), (la|las|el|los)$", name, flags=re.IGNORECASE)
    if m:
        return f"{m.group(2).capitalize()} {pretty_name(m.group(1))}"
    if not name.isupper():
        return name
    words = []
    for i, w in enumerate(name.lower().split(" ")):
        if _ROMAN.match(w):
            words.append(w.upper())
        elif i > 0 and w in _LOWER_WORDS:
            words.append(w)
        else:
            words.append("-".join(p[:1].upper() + p[1:] for p in w.split("-")))
    return " ".join(words)


def line_label(network_key: str, raw: str) -> str:
    """Normaliza el código de línea del CRTM: '7a' -> 'L7', 'C-4a' -> 'C4a', '4-1' -> 'ML4'."""
    raw = str(raw).strip()
    if not raw:
        return ""
    if network_key == "metro":
        if raw.upper() == "R":
            return "R"
        return "L" + re.sub(r"(-\d+|[a-zA-Z])$", "", raw)
    if network_key == "cercanias":
        return raw.replace("-", "")
    if network_key == "metro_ligero":
        return "ML" + re.sub(r"-\d+$", "", raw)
    return raw


def line_sort_key(line: str):
    m = re.match(r"([A-Za-z]*)(\d*)(.*)", line)
    prefix, num, rest = m.groups()
    return (prefix, int(num) if num else 0, rest)


def _parse_lines(network_key: str, value) -> list[str]:
    if not isinstance(value, str):
        return []
    labels = {line_label(network_key, p) for p in re.split(r"[,;]", value)}
    return sorted((x for x in labels if x), key=line_sort_key)


def load_network(network_key: str, force: bool = False) -> dict[str, gpd.GeoDataFrame]:
    net = config.TRANSIT_NETWORKS[network_key]
    raw_st = fetch_layer(net.service, LAYER_STATIONS, force)
    raw_acc = fetch_layer(net.service, LAYER_ACCESS, force)
    raw_seg = fetch_layer(net.service, LAYER_SEGMENTS, force)

    raw_st = raw_st[raw_st["DENOMINACION"].notna() & raw_st.geometry.notna()]
    if "FECHAFIN" in raw_st:
        raw_st = raw_st[raw_st["FECHAFIN"].isna()]
    raw_st = raw_st.assign(
        name=raw_st["DENOMINACION"].map(pretty_name),
        lines=[_parse_lines(network_key, v) for v in raw_st["LINEAS"]],
    )
    stations, merge_map = _merge_duplicates(raw_st)
    stations = stations.assign(
        station_id=network_key + ":" + stations["IDESTACION"],
        mode=network_key,
        municipality_code=stations["CODIGOPROVINCIA"].fillna("") + stations["CODIGOMUNICIPIO"].fillna(""),
    )

    acc = raw_acc[raw_acc.geometry.notna()].copy()
    if "FECHAFIN" in acc:
        acc = acc[acc["FECHAFIN"].isna()]
    acc["station_raw"] = acc["IDFESTACION"].map(lambda s: merge_map.get(s, s))
    acc = acc[acc["station_raw"].isin(stations["IDESTACION"])]
    access = gpd.GeoDataFrame(
        {
            "station_id": network_key + ":" + acc["station_raw"],
            "access_id": acc["IDACCESO"].astype(str),
            "name": acc["DENOMINACION"].fillna("Acceso").map(pretty_name),
            "step_free": acc.get("ACCESOMINUSVALIDOS", pd.Series(index=acc.index, dtype=str)).eq("S"),
        },
        geometry=acc.geometry.values,
        crs=config.CRS_WGS84,
    )
    stations["n_accesses"] = stations["station_id"].map(access.groupby("station_id").size()).fillna(0).astype(int)

    lines = _line_geometries(raw_seg, network_key)
    stations["lines"] = [_expand_lines(ls, list(lines["line"])) for ls in stations["lines"]]
    stations = stations[
        ["station_id", "mode", "IDESTACION", "name", "lines", "municipality_code", "n_accesses", "geometry"]
    ].rename(columns={"IDESTACION": "crtm_id"})
    stations["lon"] = stations.geometry.x
    stations["lat"] = stations.geometry.y
    version = str(raw_st["FECHAACTUAL"].dropna().max()) if "FECHAACTUAL" in raw_st else None
    log.info("%s: %d estaciones, %d accesos, %d líneas", network_key, len(stations), len(access), len(lines))
    return {"stations": stations.reset_index(drop=True), "access": access, "lines": lines, "version": version}


def _expand_lines(station_lines: list[str], known: list[str]) -> list[str]:
    """Las estaciones citan 'C4' aunque los trazados sean 'C4a' y 'C4b': se expanden."""
    out = set()
    for line in station_lines:
        if line in known:
            out.add(line)
        else:
            variants = [k for k in known if re.fullmatch(re.escape(line) + r"[a-zA-Z]", k)]
            out.update(variants or [line])
    return sorted(out, key=line_sort_key)


def _merge_duplicates(st: gpd.GeoDataFrame) -> tuple[gpd.GeoDataFrame, dict[str, str]]:
    """Une registros de la misma estación (uno por línea en el CRTM) con mismo nombre y cercanos."""
    metric = st.geometry.to_crs(config.CRS_METRIC)
    keys = st["name"].map(normalize_name)
    merge_map: dict[str, str] = {}
    keep_rows = []
    for _, idx in keys.groupby(keys, sort=False).groups.items():
        remaining = list(idx)
        while remaining:
            first = remaining.pop(0)
            close = [i for i in remaining if metric[i].distance(metric[first]) < DEDUP_DISTANCE_M]
            remaining = [i for i in remaining if i not in close]
            row = st.loc[first].copy()
            lines = set(row["lines"])
            for i in close:
                merge_map[st.at[i, "IDESTACION"]] = row["IDESTACION"]
                lines |= set(st.at[i, "lines"])
            row["lines"] = sorted(lines, key=line_sort_key)
            keep_rows.append(row)
    out = gpd.GeoDataFrame(keep_rows, geometry="geometry", crs=st.crs)
    return out, merge_map


def _line_geometries(seg: gpd.GeoDataFrame, network_key: str) -> gpd.GeoDataFrame:
    seg = seg[seg.geometry.notna()].copy()
    if "FECHAFIN" in seg:
        seg = seg[seg["FECHAFIN"].isna()]
    seg["line"] = seg["NUMEROLINEAUSUARIO"].map(lambda v: line_label(network_key, v))
    seg = seg[seg["line"] != ""].to_crs(config.CRS_METRIC)
    rows = []
    for line, g in seg.groupby("line"):
        merged = linemerge(unary_union(g.geometry.simplify(3).values))
        rows.append({"line": line, "geometry": merged.simplify(5)})
    lines = gpd.GeoDataFrame(rows, geometry="geometry", crs=config.CRS_METRIC).to_crs(config.CRS_WGS84)
    lines["mode"] = network_key
    lines["line_id"] = network_key + ":" + lines["line"]
    lines["color"] = lines["line"].map(config.LINE_COLORS).fillna(config.TRANSIT_NETWORKS[network_key].color)
    return lines.sort_values("line", key=lambda s: s.map(line_sort_key)).reset_index(drop=True)


def build_transit(network_keys: list[str] | None = None, force: bool = False) -> dict:
    keys = network_keys or [n.key for n in config.available_networks()]
    parts = {k: load_network(k, force) for k in keys}
    stations = gpd.GeoDataFrame(pd.concat([p["stations"] for p in parts.values()], ignore_index=True), crs=config.CRS_WGS84)
    access = gpd.GeoDataFrame(pd.concat([p["access"] for p in parts.values()], ignore_index=True), crs=config.CRS_WGS84)
    lines = gpd.GeoDataFrame(pd.concat([p["lines"] for p in parts.values()], ignore_index=True), crs=config.CRS_WGS84)
    return {"stations": stations, "access": access, "lines": lines, "versions": {k: p["version"] for k, p in parts.items()}}
