"""Extracción de la red viaria y de límites municipales desde un extracto OSM (.pbf).

Se leen las vías una sola vez con pyosmium y se guardan como tablas compactas de
nodos y aristas. Los filtros reproducen los tipos de red "walk" y "drive" de OSMnx
para que el resultado sea equivalente al que se obtendría vía Overpass.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import geopandas as gpd
import numpy as np
import osmium
import pandas as pd
import shapely.wkb
from pyproj import Transformer

from . import config

log = logging.getLogger(__name__)

# Filtros equivalentes a osmnx._overpass._get_network_filter (OSMnx 2.0).
# Overpass aplica `["k"!~"regex"]` como búsqueda de subcadena sin anclar.
_COMMON_EXCLUDE = {"area": "yes", "access": "private"}
WALK_EXCLUDE = {
    **_COMMON_EXCLUDE,
    "highway": (
        "abandoned|bus_guideway|construction|cycleway|motor|no|planned|platform|proposed|raceway|razed|rest_area|services"
    ),
    "foot": "no",
    "service": "private",
    "sidewalk": "separate",
    "sidewalk:both": "separate",
    "sidewalk:left": "separate",
    "sidewalk:right": "separate",
}
DRIVE_EXCLUDE = {
    **_COMMON_EXCLUDE,
    "highway": (
        "abandoned|bridleway|bus_guideway|construction|corridor|cycleway|elevator|escalator|footway|no|path|"
        "pedestrian|planned|platform|proposed|raceway|razed|rest_area|service|services|steps|track"
    ),
    "motor_vehicle": "no",
    "motorcar": "no",
    "service": "alley|driveway|emergency_access|parking|parking_aisle|private",
}
_WALK_RE = {k: re.compile(v) for k, v in WALK_EXCLUDE.items()}
_DRIVE_RE = {k: re.compile(v) for k, v in DRIVE_EXCLUDE.items()}

# Velocidades por defecto (km/h) del perfil de coche de OSRM cuando no hay maxspeed.
DRIVE_DEFAULT_SPEED = {
    "motorway": 90,
    "motorway_link": 45,
    "trunk": 85,
    "trunk_link": 40,
    "primary": 65,
    "primary_link": 30,
    "secondary": 55,
    "secondary_link": 25,
    "tertiary": 40,
    "tertiary_link": 20,
    "unclassified": 25,
    "residential": 25,
    "living_street": 10,
    "road": 25,
    "busway": 25,
}
MAXSPEED_ZONES = {
    "ES:urban": 50,
    "ES:rural": 90,
    "ES:motorway": 120,
    "ES:trunk": 100,
    "ES:living_street": 20,
    "ES:zone30": 30,
    "ES:zone20": 20,
    "walk": 10,
}

ONEWAY_FORWARD = {"yes", "true", "1"}
ONEWAY_BACKWARD = {"-1", "reverse"}


def _passes(tags: dict[str, str], exclude: dict[str, re.Pattern]) -> bool:
    return not any(k in tags and rx.search(tags[k]) for k, rx in exclude.items())


def parse_maxspeed(value: str | None) -> float | None:
    if not value:
        return None
    value = value.split(";")[0].strip()
    if value in MAXSPEED_ZONES:
        return float(MAXSPEED_ZONES[value])
    m = re.match(r"^(\d+(?:\.\d+)?)\s*(mph)?$", value)
    if not m:
        return None
    speed = float(m.group(1))
    return speed * 1.609 if m.group(2) else speed


def drive_speed_kmh(tags: dict[str, str], maxspeed_factor: float) -> float:
    maxspeed = parse_maxspeed(tags.get("maxspeed"))
    if maxspeed:
        return max(5.0, maxspeed * maxspeed_factor)
    return float(DRIVE_DEFAULT_SPEED.get(tags.get("highway", ""), 25))


# Clases de vía para el perfil de tráfico (ver config.TrafficProfile).
ROAD_M30, ROAD_M40, ROAD_M50, ROAD_HIGHWAY, ROAD_ARTERIAL, ROAD_LOCAL = range(1, 7)
_RING_REFS = {"M-30": ROAD_M30, "M-40": ROAD_M40, "M-50": ROAD_M50}


def road_class(tags: dict[str, str]) -> int:
    highway = tags.get("highway", "")
    refs = {r.strip() for r in tags.get("ref", "").split(";")}
    for ref, cls in _RING_REFS.items():
        if ref in refs:
            return cls
    if highway.startswith(("motorway", "trunk")):
        return ROAD_HIGHWAY
    if highway.startswith(("primary", "secondary")):
        return ROAD_ARTERIAL
    return ROAD_LOCAL


def drive_direction(tags: dict[str, str]) -> int:
    """1 = solo sentido de digitalización, -1 = solo inverso, 0 = doble sentido."""
    oneway = tags.get("oneway", "")
    if oneway in ONEWAY_FORWARD:
        return 1
    if oneway in ONEWAY_BACKWARD:
        return -1
    if oneway == "no":
        return 0
    if tags.get("junction") in {"roundabout", "circular"} or tags.get("highway") == "motorway":
        return 1
    return 0


def extract_networks(pbf: Path, out_dir: Path, maxspeed_factor: float | None = None) -> dict[str, Path]:
    """Lee el .pbf y escribe nodes.parquet, walk_edges.parquet y drive_edges.parquet."""
    maxspeed_factor = config.SETTINGS.drive_maxspeed_factor if maxspeed_factor is None else maxspeed_factor
    node_index: dict[int, int] = {}
    lons: list[float] = []
    lats: list[float] = []
    walk_u, walk_v = [], []
    drv_u, drv_v, drv_speed, drv_cls = [], [], [], []

    def idx(n) -> int:
        i = node_index.get(n.ref)
        if i is None:
            i = node_index[n.ref] = len(lons)
            lons.append(n.lon)
            lats.append(n.lat)
        return i

    fp = (
        osmium.FileProcessor(str(pbf), osmium.osm.NODE | osmium.osm.WAY)
        .with_locations()
        .with_filter(osmium.filter.EntityFilter(osmium.osm.WAY))
        .with_filter(osmium.filter.KeyFilter("highway"))
    )
    for way in fp:
        tags = dict(way.tags)
        walk = _passes(tags, _WALK_RE)
        drive = _passes(tags, _DRIVE_RE)
        if not (walk or drive):
            continue
        try:
            ids = [idx(n) for n in way.nodes]
        except osmium.InvalidLocationError:
            continue
        pairs = [(a, b) for a, b in zip(ids[:-1], ids[1:], strict=True) if a != b]
        if not pairs:
            continue
        if walk:
            walk_u.extend(a for a, _ in pairs)
            walk_v.extend(b for _, b in pairs)
        if drive:
            speed = drive_speed_kmh(tags, maxspeed_factor)
            direction = drive_direction(tags)
            cls = road_class(tags)
            for a, b in pairs:
                if direction >= 0:
                    drv_u.append(a)
                    drv_v.append(b)
                    drv_speed.append(speed)
                    drv_cls.append(cls)
                if direction <= 0:
                    drv_u.append(b)
                    drv_v.append(a)
                    drv_speed.append(speed)
                    drv_cls.append(cls)

    to_metric = Transformer.from_crs(config.CRS_WGS84, config.CRS_METRIC, always_xy=True)
    x, y = to_metric.transform(np.asarray(lons), np.asarray(lats))
    nodes = pd.DataFrame({"osmid": np.fromiter(node_index.keys(), dtype=np.int64, count=len(node_index)), "x": x, "y": y})

    def edges(u, v) -> pd.DataFrame:
        u = np.asarray(u, dtype=np.int32)
        v = np.asarray(v, dtype=np.int32)
        length = np.hypot(x[u] - x[v], y[u] - y[v]).astype(np.float32)
        return pd.DataFrame({"u": u, "v": v, "length": length})

    walk_edges = edges(walk_u, walk_v).drop_duplicates(["u", "v"])
    drive_edges = edges(drv_u, drv_v)
    drive_edges["speed_kmh"] = np.asarray(drv_speed, dtype=np.float32)
    drive_edges["road_class"] = np.asarray(drv_cls, dtype=np.int8)
    drive_edges = drive_edges.drop_duplicates(["u", "v"])

    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "nodes": out_dir / "nodes.parquet",
        "walk_edges": out_dir / "walk_edges.parquet",
        "drive_edges": out_dir / "drive_edges.parquet",
    }
    nodes.to_parquet(paths["nodes"])
    walk_edges.to_parquet(paths["walk_edges"])
    drive_edges.to_parquet(paths["drive_edges"])
    log.info("Red OSM: %d nodos, %d aristas a pie, %d aristas en coche", len(nodes), len(walk_edges), len(drive_edges))
    return paths


def extract_boundaries(pbf: Path, out_path: Path) -> gpd.GeoDataFrame:
    """Extrae municipios (admin_level=8) y la Comunidad de Madrid (admin_level=4)."""
    wkb = osmium.geom.WKBFactory()
    rows = []
    fp = osmium.FileProcessor(str(pbf)).with_areas(osmium.filter.TagFilter(("boundary", "administrative")))
    for obj in fp:
        if not obj.is_area() or obj.tags.get("boundary") != "administrative":
            continue
        level = obj.tags.get("admin_level")
        if level not in {"4", "8"}:
            continue
        try:
            geom = shapely.wkb.loads(wkb.create_multipolygon(obj), hex=True)
        except Exception:  # noqa: BLE001 - polígonos rotos en el extracto
            continue
        rows.append(
            {
                "name": obj.tags.get("name"),
                "admin_level": int(level),
                "ine_code": obj.tags.get("ine:municipio"),
                "geometry": geom,
            }
        )
    gdf = gpd.GeoDataFrame(rows, geometry="geometry", crs=config.CRS_WGS84)
    # El polígono de la Comunidad suele quedar incompleto en el extracto: se reconstruye
    # uniendo los municipios con código INE de la provincia 28.
    munis = gdf[(gdf.admin_level == 8) & gdf.ine_code.fillna("").str.startswith("28")]
    region = gpd.GeoDataFrame(
        [{"name": "Comunidad de Madrid", "admin_level": 4, "ine_code": "28", "geometry": munis.geometry.union_all().buffer(0)}],
        geometry="geometry",
        crs=config.CRS_WGS84,
    )
    gdf = pd.concat([region, munis], ignore_index=True)
    gdf = gdf.sort_values(["admin_level", "name"]).reset_index(drop=True)
    gdf.to_file(out_path, driver="GeoJSON")
    log.info("Límites: %d municipios", int((gdf.admin_level == 8).sum()))
    return gdf


PLACE_KINDS = ("suburb", "quarter", "neighbourhood")


def extract_places(pbf: Path, out_path: Path) -> gpd.GeoDataFrame:
    """Extrae los nombres de barrios (nodos place=suburb/quarter/neighbourhood) para etiquetar el mapa."""
    rows = []
    tag_filter = osmium.filter.TagFilter(*(("place", k) for k in PLACE_KINDS))
    fp = osmium.FileProcessor(str(pbf), osmium.osm.NODE).with_filter(tag_filter)
    for n in fp:
        name = n.tags.get("name")
        if name:
            rows.append({"name": name, "place": n.tags.get("place"), "lon": n.location.lon, "lat": n.location.lat})
    df = pd.DataFrame(rows, columns=["name", "place", "lon", "lat"])
    gdf = gpd.GeoDataFrame(df[["name", "place"]], geometry=gpd.points_from_xy(df.lon, df.lat), crs=config.CRS_WGS84)
    gdf.to_parquet(out_path)
    log.info("Barrios: %d nombres", len(gdf))
    return gdf
