"""Exporta la página estática del mapa (mapa-metro.html) con los ajustes por defecto de la app.

Uso:  ./.venv/bin/python scripts/exportar_mapa_html.py [salida.html]
"""

from __future__ import annotations

import argparse

import geopandas as gpd
import pandas as pd
import shapely

from accesibilidad import config, drive, graph, isochrones, mapping, pipeline, seguridad

TIMES = [5, 10, 15]
SPEED = config.SETTINGS.walk_speed_kmh_default
DRIVE_LIMIT = config.DEFAULT_DRIVE_MINUTES


def _clip(polys: gpd.GeoDataFrame, zone) -> gpd.GeoDataFrame:
    clipped = polys.to_crs(config.CRS_METRIC).assign(geometry=lambda d: d.geometry.intersection(zone))
    return clipped[~clipped.geometry.is_empty].to_crs(polys.crs)


def _rush_graph(origin) -> graph.DriveGraph:
    nodes = graph.load_nodes()
    edges = pd.read_parquet(pipeline.processed("drive_edges.parquet"))
    factors = drive.rush_hour_factors(edges, nodes, config.RUSH_HOUR, (origin.lon, origin.lat))
    return graph.DriveGraph(nodes, edges.assign(speed_kmh=edges["speed_kmh"] / factors))


def main(out: str) -> None:
    stations_all = gpd.read_parquet(pipeline.processed(pipeline.STATIONS_FILE))
    access = gpd.read_parquet(pipeline.processed(pipeline.ACCESS_FILE))
    lines = gpd.read_parquet(pipeline.processed(pipeline.LINES_FILE))
    places_path = pipeline.processed(pipeline.PLACES_FILE)
    places = gpd.read_parquet(places_path) if places_path.exists() else None

    networks = [n for n in config.available_networks() if n.enabled_by_default]
    selected_modes = [n.key for n in networks]
    origin = config.DEFAULT_ORIGIN
    towards, factor = True, 1.0

    excluded_munis = [n for n in config.DEFAULT_EXCLUDED_MUNICIPALITIES]
    excluded_stations = [n for n in config.DEFAULT_EXCLUDED_STATIONS]

    stations = stations_all[
        stations_all["mode"].isin(selected_modes)
        & stations_all["in_region"]
        & ~stations_all["municipality"].isin(excluded_munis)
        & ~stations_all["name"].isin(excluded_stations)
    ].copy()

    dg = _rush_graph(origin)
    node_min = drive.drive_times(dg, origin.lon, origin.lat, config.SETTINGS.drive_max_minutes, towards)
    extra = config.RUSH_HOUR.fixed_minutes
    dmin = pd.Series(drive.station_drive_minutes(dg, stations, node_min) + extra, index=stations["station_id"].values)
    stations["drive_min"] = stations["station_id"].map(dmin) * factor
    stations = stations[stations["drive_min"] <= DRIVE_LIMIT].sort_values(["mode", "name"]).reset_index(drop=True)

    def _area(minutes: float):
        budget = minutes / factor - extra
        area = drive.drive_area(dg, node_min, budget)
        return gpd.GeoDataFrame(geometry=[area.geometry.iloc[0]], crs=config.CRS_METRIC) if len(area) else None

    scope_gdf = _area(DRIVE_LIMIT)
    bands = {b: _area(b) for b in config.DEFAULT_DRIVE_BANDS if b <= DRIVE_LIMIT}
    bands = {b: g for b, g in bands.items() if g is not None}

    # Áreas andando (isócronas reales), recortadas al ámbito en coche.
    nodes = graph.load_nodes()
    wg = graph.load_walk_graph(nodes=nodes)
    wg.snap_xy(0, 0)
    reach = isochrones.ReachIndex.load(pipeline.processed(isochrones.REACH_FILE))
    builder = isochrones.IsochroneBuilder(wg, reach)
    polys = {}
    for m in TIMES:
        polys[m] = builder.get(stations["station_id"], isochrones.walk_budget_m(m, SPEED))
    clip_zone = scope_gdf.to_crs(config.CRS_METRIC).geometry.union_all() if scope_gdf is not None else None
    if clip_zone is not None:
        polys = {m: _clip(p, clip_zone) for m, p in polys.items()}

    # Capa de seguridad recortada a las zonas accesibles.
    security_gdf = None
    seg = seguridad.build()
    if seg is not None and not seg.empty:
        parts = [g for g in list(bands.values()) + list(polys.values()) if g is not None and len(g)]
        zone = shapely.union_all([g.to_crs(config.CRS_METRIC).geometry.union_all() for g in parts])
        clipped = seg.to_crs(config.CRS_METRIC).assign(geometry=lambda d: d.geometry.intersection(zone))
        clipped = clipped[(~clipped.geometry.is_empty) & (clipped.geometry.area > 5_000)]
        security_gdf = clipped.to_crs(config.CRS_WGS84)

    lines_shown = lines[lines["mode"].isin(selected_modes)]
    acc = access[access["station_id"].isin(stations["station_id"])]

    b = stations.total_bounds
    center = ((b[1] + b[3]) / 2, (b[0] + b[2]) / 2)
    m = mapping.base_map(center=center, zoom=11)
    if not bands:
        mapping.add_scope(m, scope_gdf, "CGS")
    else:
        mapping.add_drive_bands(m, bands, "CGS")
    if places is not None and scope_gdf is not None:
        zone = scope_gdf.to_crs(config.CRS_WGS84).geometry.union_all()
        mapping.add_neighbourhoods(m, places[places.within(zone)])
    mapping.add_lines(m, lines_shown)
    mapping.add_isochrones(m, polys, stations, individual=len(stations) <= 80, label="Andando")
    mapping.add_security(m, security_gdf)
    mapping.add_stations(m, stations, acc)
    mapping.add_origin(m, origin.lat, origin.lon, origin.name)
    mapping.add_legend(m, list(polys), show_overlaps=False)
    if security_gdf is not None:
        mapping.add_security_legend(m)
    mapping.finish(m)
    m.fit_bounds([[b[1], b[0]], [b[3], b[2]]])
    m.save(out)
    n_sec = len(security_gdf) if security_gdf is not None else 0
    print(f"Mapa guardado en {out} ({len(stations)} estaciones, {n_sec} zonas de seguridad)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("out", nargs="?", default="mapa-metro.html")
    args = parser.parse_args()
    main(args.out)
