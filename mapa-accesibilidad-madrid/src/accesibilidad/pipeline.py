"""Proceso de preparación de datos (se ejecuta una vez y cuando se quieran actualizar).

python -m accesibilidad.pipeline            # prepara solo lo que falte
python -m accesibilidad.pipeline --force    # vuelve a descargar y recalcular todo
"""

from __future__ import annotations

import argparse
import json
import logging
import time

import geopandas as gpd
import pandas as pd

from . import config, download, drive, graph, isochrones, osm, transit

log = logging.getLogger("accesibilidad")

STATIONS_FILE = "stations.parquet"
ACCESS_FILE = "access.parquet"
LINES_FILE = "lines.parquet"
BOUNDARIES_FILE = "boundaries.geojson"
META_FILE = "meta.json"
# Estaciones fuera de la Comunidad (Cercanías llega a Ávila, Segovia...) solo se procesan si están cerca.
REGION_MARGIN_M = 1000


def processed(name: str):
    return config.PROCESSED_DIR / name


def step_transit(force: bool) -> None:
    if processed(STATIONS_FILE).exists() and not force:
        return
    data = transit.build_transit(force=force)
    data["stations"].to_parquet(processed(STATIONS_FILE))
    data["access"].to_parquet(processed(ACCESS_FILE))
    data["lines"].to_parquet(processed(LINES_FILE))
    _update_meta(crtm_versions=data["versions"])


def step_osm(force: bool) -> None:
    pbf = download.download_osm(force=force)
    if not processed("walk_edges.parquet").exists() or force:
        osm.extract_networks(pbf, config.PROCESSED_DIR)
        _update_meta(osm_extract_mtime=time.strftime("%Y-%m-%d", time.localtime(pbf.stat().st_mtime)))
    if not processed(BOUNDARIES_FILE).exists() or force:
        osm.extract_boundaries(pbf, processed(BOUNDARIES_FILE))


def step_assign_municipalities() -> gpd.GeoDataFrame:
    stations = gpd.read_parquet(processed(STATIONS_FILE))
    bounds = gpd.read_file(processed(BOUNDARIES_FILE))
    munis = bounds[bounds.admin_level == 8][["name", "geometry"]].rename(columns={"name": "municipality"})
    region = bounds[bounds.admin_level == 4].to_crs(config.CRS_METRIC).geometry.union_all()
    stations = stations.drop(columns=[c for c in ("municipality", "in_region") if c in stations])
    stations = gpd.sjoin(stations, munis, how="left", predicate="within").drop(columns="index_right")
    stations = stations[~stations.index.duplicated()]
    stations["in_region"] = stations.to_crs(config.CRS_METRIC).geometry.distance(region) <= REGION_MARGIN_M
    stations.to_parquet(processed(STATIONS_FILE))
    return stations


def step_reach(force: bool) -> None:
    path = processed(isochrones.REACH_FILE)
    if path.exists() and not force:
        return
    stations = gpd.read_parquet(processed(STATIONS_FILE))
    stations = stations[stations["in_region"]]
    access = gpd.read_parquet(processed(ACCESS_FILE))
    wg = graph.load_walk_graph()
    max_dist = config.SETTINGS.max_walk_distance_m
    log.info("Calculando alcance a pie de %d estaciones (hasta %.0f m)...", len(stations), max_dist)
    reach = isochrones.compute_reach(wg, stations, access, max_dist)
    reach.to_parquet(path)
    # Las isócronas cacheadas dependen del alcance: se invalidan.
    for f in (config.CACHE_DIR / "isochrones").glob("*.parquet"):
        f.unlink()


def step_precompute_default(minutes=(5, 10, 15)) -> None:
    """Precalcula las isócronas del ámbito por defecto a la velocidad por defecto."""
    stations = gpd.read_parquet(processed(STATIONS_FILE))
    nodes = graph.load_nodes()
    dg = graph.load_drive_graph(nodes=nodes)
    o = config.DEFAULT_ORIGIN
    node_min = drive.drive_times(dg, o.lon, o.lat, config.DEFAULT_DRIVE_MINUTES)
    stations["drive_min"] = drive.station_drive_minutes(dg, stations, node_min)
    sel = stations[(stations["drive_min"] <= config.DEFAULT_DRIVE_MINUTES) & stations["mode"].isin(["metro", "cercanias"])]
    wg = graph.load_walk_graph(nodes=nodes)
    builder = isochrones.IsochroneBuilder(wg, isochrones.ReachIndex.load(processed(isochrones.REACH_FILE)))
    for m in minutes:
        log.info("Isócronas de %d min para %d estaciones del ámbito por defecto...", m, len(sel))
        builder.get(sel["station_id"], isochrones.walk_budget_m(m, config.SETTINGS.walk_speed_kmh_default))


def _update_meta(**kwargs) -> None:
    path = processed(META_FILE)
    meta = json.loads(path.read_text()) if path.exists() else {}
    meta.update(kwargs)
    meta["updated"] = time.strftime("%Y-%m-%d %H:%M")
    path.write_text(json.dumps(meta, ensure_ascii=False, indent=2))


def load_meta() -> dict:
    path = processed(META_FILE)
    return json.loads(path.read_text()) if path.exists() else {}


def is_ready() -> bool:
    return all(
        processed(f).exists()
        for f in (STATIONS_FILE, ACCESS_FILE, LINES_FILE, BOUNDARIES_FILE, isochrones.REACH_FILE, "nodes.parquet")
    )


def run(force: bool = False, precompute: bool = True) -> None:
    config.ensure_dirs()
    t0 = time.time()
    step_transit(force)
    step_osm(force)
    step_assign_municipalities()
    step_reach(force)
    if precompute:
        step_precompute_default()
    log.info("Datos listos en %s (%.0f s)", config.PROCESSED_DIR, time.time() - t0)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--force", action="store_true", help="vuelve a descargar y recalcular todo")
    parser.add_argument("--no-precompute", action="store_true", help="no precalcula isócronas por defecto")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    pd.options.mode.copy_on_write = True
    run(force=args.force, precompute=not args.no_precompute)


if __name__ == "__main__":
    main()
