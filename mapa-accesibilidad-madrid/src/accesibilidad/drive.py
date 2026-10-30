"""Ámbito por tiempo en coche desde (o hacia) un punto de referencia."""

from __future__ import annotations

import geopandas as gpd
import numpy as np
import shapely

from . import config
from .graph import DriveGraph


def drive_times(dg: DriveGraph, lon: float, lat: float, max_minutes: float, towards: bool = False) -> np.ndarray:
    """Minutos en flujo libre a cada nodo de la red (inf si supera `max_minutes`)."""
    return dg.travel_times(lon, lat, max_minutes * 60, towards=towards) / 60


def station_drive_minutes(dg: DriveGraph, stations: gpd.GeoDataFrame, node_minutes: np.ndarray) -> np.ndarray:
    snap = dg.snap_lonlat(stations.geometry.x.values, stations.geometry.y.values)
    return node_minutes[snap.node]


def drive_area(dg: DriveGraph, node_minutes: np.ndarray, minutes: float, cell_m: float = 400) -> gpd.GeoDataFrame:
    """Polígono aproximado de la zona alcanzable en coche: celdas de una malla con nodos alcanzados."""
    ok = node_minutes <= minutes
    if not ok.any():
        return gpd.GeoDataFrame(geometry=[], crs=config.CRS_METRIC)
    cells = np.unique(np.column_stack([np.floor(dg.x[ok] / cell_m), np.floor(dg.y[ok] / cell_m)]), axis=0)
    boxes = shapely.box(cells[:, 0] * cell_m, cells[:, 1] * cell_m, (cells[:, 0] + 1) * cell_m, (cells[:, 1] + 1) * cell_m)
    poly = shapely.coverage_union_all(boxes)
    poly = poly.buffer(cell_m, quad_segs=2).buffer(-cell_m, quad_segs=2)
    # Sin huecos interiores ni islas diminutas: se busca un contorno legible del ámbito.
    parts = [shapely.Polygon(p.exterior) for p in shapely.get_parts(poly) if p.area >= 4 * cell_m**2]
    poly = shapely.simplify(shapely.union_all(parts), cell_m / 2)
    return gpd.GeoDataFrame({"minutes": [minutes]}, geometry=[poly], crs=config.CRS_METRIC)
