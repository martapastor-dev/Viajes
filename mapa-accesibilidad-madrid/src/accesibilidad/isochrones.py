"""Alcance por la red peatonal desde cada estación e isócronas derivadas.

1. `compute_reach` hace un Dijkstra por estación (desde todos sus accesos) hasta la
   distancia máxima configurable y guarda la distancia a cada nodo alcanzado.
2. `IsochroneBuilder` convierte ese alcance en polígonos para cualquier presupuesto
   de distancia (tiempo × velocidad) sin volver a recorrer la red, y los cachea.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from shapely.geometry import MultiPolygon, Polygon

from . import config
from .graph import WalkGraph, to_metric

log = logging.getLogger(__name__)

REACH_FILE = "walk_reach.parquet"


def walk_budget_m(minutes: float, speed_kmh: float) -> float:
    return minutes / 60 * speed_kmh * 1000


def station_sources(stations: gpd.GeoDataFrame, access: gpd.GeoDataFrame) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    """Puntos de partida de cada estación en CRS métrico: sus accesos o, si no tiene, el punto de la estación."""
    acc_by_station = {k: g for k, g in access.groupby("station_id")}
    out = {}
    for sid, geom in zip(stations["station_id"], stations.geometry):
        g = acc_by_station.get(sid)
        if g is not None and len(g):
            out[sid] = to_metric(g.geometry.x.values, g.geometry.y.values)
        else:
            out[sid] = to_metric([geom.x], [geom.y])
    return out


def compute_reach(
    wg: WalkGraph,
    stations: gpd.GeoDataFrame,
    access: gpd.GeoDataFrame,
    max_dist_m: float,
    progress: Callable[[int, int], None] | None = None,
) -> pd.DataFrame:
    sources = station_sources(stations, access)
    parts = []
    for i, (sid, (x, y)) in enumerate(sources.items()):
        nodes, dist = wg.reach_from(x, y, max_dist_m)
        parts.append(pd.DataFrame({"station_id": sid, "node": nodes, "dist": dist}))
        if progress:
            progress(i + 1, len(sources))
    reach = pd.concat(parts, ignore_index=True)
    reach["station_id"] = reach["station_id"].astype("category")
    reach.attrs["max_dist_m"] = max_dist_m
    return reach


class ReachIndex:
    """Acceso rápido al alcance precalculado, por estación y por nodo."""

    def __init__(self, reach: pd.DataFrame):
        reach = reach.sort_values(["station_id", "dist"], kind="stable")
        self.station_ids = reach["station_id"].astype(str).to_numpy()
        self.nodes = reach["node"].to_numpy(np.int32)
        self.dist = reach["dist"].to_numpy(np.float32)
        starts = np.flatnonzero(np.r_[True, self.station_ids[1:] != self.station_ids[:-1]])
        ends = np.r_[starts[1:], len(self.station_ids)]
        self._slices = {self.station_ids[s]: (s, e) for s, e in zip(starts, ends)}
        self._by_node = np.argsort(self.nodes, kind="stable")
        self._nodes_sorted = self.nodes[self._by_node]
        self.max_dist_m = float(self.dist.max()) if len(self.dist) else 0.0

    @classmethod
    def load(cls, path: Path) -> ReachIndex:
        return cls(pd.read_parquet(path))

    def has(self, station_id: str) -> bool:
        return station_id in self._slices

    def for_station(self, station_id: str) -> tuple[np.ndarray, np.ndarray]:
        s, e = self._slices.get(station_id, (0, 0))
        return self.nodes[s:e], self.dist[s:e]

    def stations_at_node(self, node: int) -> pd.DataFrame:
        lo, hi = np.searchsorted(self._nodes_sorted, [node, node + 1])
        idx = self._by_node[lo:hi]
        return pd.DataFrame({"station_id": self.station_ids[idx], "dist": self.dist[idx]})


def _fill_small_holes(geom, min_hole_area: float):
    def fix(p: Polygon) -> Polygon:
        return Polygon(p.exterior, [r for r in p.interiors if Polygon(r).area >= min_hole_area])

    if geom.is_empty:
        return geom
    if isinstance(geom, Polygon):
        return fix(geom)
    return MultiPolygon([fix(p) for p in geom.geoms])


def reach_polygon(
    wg: WalkGraph,
    nodes: np.ndarray,
    dist: np.ndarray,
    budget_m: float,
    buffer_m: float = config.SETTINGS.isochrone_buffer_m,
    fill_holes_m2: float = config.SETTINGS.isochrone_fill_holes_m2,
):
    """Polígono (CRS métrico) de las calles alcanzables con `budget_m` metros, incluidos tramos parciales."""
    sel = dist <= budget_m
    if not sel.any():
        return Polygon()
    d = np.full(wg.n, np.inf, dtype=np.float64)
    d[nodes[sel]] = dist[sel]
    du, dv = d[wg.u], d[wg.v]
    cand = np.isfinite(du) | np.isfinite(dv)
    u, v, length = wg.u[cand], wg.v[cand], wg.weight[cand]
    du, dv = du[cand], dv[cand]
    a = np.clip(budget_m - du, 0, length)  # metros recorribles desde u
    b = np.clip(budget_m - dv, 0, length)  # metros recorribles desde v
    full = a + b >= length
    p_u = np.column_stack([wg.x[u], wg.y[u]])
    p_v = np.column_stack([wg.x[v], wg.y[v]])
    with np.errstate(divide="ignore", invalid="ignore"):
        frac_a = np.where(length > 0, a / length, 1.0)[:, None]
        frac_b = np.where(length > 0, b / length, 1.0)[:, None]
    segs = [np.stack([p_u[full], p_v[full]], axis=1)]
    pa = ~full & (a > 1)
    segs.append(np.stack([p_u[pa], p_u[pa] + (p_v[pa] - p_u[pa]) * frac_a[pa]], axis=1))
    pb = ~full & (b > 1)
    segs.append(np.stack([p_v[pb], p_v[pb] + (p_u[pb] - p_v[pb]) * frac_b[pb]], axis=1))
    coords = np.concatenate(segs)
    if not len(coords):
        return Polygon()
    # Buffer por segmento + unión es mucho más rápido que el buffer de un MultiLineString.
    poly = shapely.union_all(shapely.buffer(shapely.linestrings(coords), buffer_m, quad_segs=2))
    poly = _fill_small_holes(poly, fill_holes_m2)
    return shapely.simplify(poly, 5).buffer(0)


class IsochroneBuilder:
    """Genera y cachea en disco isócronas por estación para un presupuesto en metros."""

    def __init__(self, wg: WalkGraph, reach: ReachIndex, cache_dir: Path = config.CACHE_DIR / "isochrones"):
        self.wg = wg
        self.reach = reach
        self.cache_dir = cache_dir
        self._mem: dict[int, dict[str, object]] = {}

    @staticmethod
    def _key(budget_m: float) -> int:
        return int(round(budget_m / 10.0) * 10)

    def _path(self, key: int) -> Path:
        return self.cache_dir / f"walk_{key}m.parquet"

    def _load(self, key: int) -> dict[str, object]:
        if key not in self._mem:
            path = self._path(key)
            if path.exists():
                df = gpd.read_parquet(path)
                self._mem[key] = dict(zip(df["station_id"], df.geometry))
            else:
                self._mem[key] = {}
        return self._mem[key]

    def get(
        self, station_ids: Iterable[str], budget_m: float, progress: Callable[[int, int], None] | None = None
    ) -> gpd.GeoDataFrame:
        if budget_m > self.reach.max_dist_m + 1:
            raise ValueError(f"El presupuesto ({budget_m:.0f} m) supera el alcance precalculado ({self.reach.max_dist_m:.0f} m).")
        key = self._key(budget_m)
        store = self._load(key)
        ids = [s for s in station_ids if self.reach.has(s)]
        missing = [s for s in ids if s not in store]
        # Shapely libera el GIL en las operaciones geométricas: los hilos aprovechan varios núcleos.
        with ThreadPoolExecutor(max_workers=min(8, os.cpu_count() or 1)) as pool:
            futures = {pool.submit(reach_polygon, self.wg, *self.reach.for_station(s), key): s for s in missing}
            for i, fut in enumerate(as_completed(futures)):
                store[futures[fut]] = fut.result()
                if progress:
                    progress(i + 1, len(missing))
        if missing:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            gpd.GeoDataFrame({"station_id": list(store)}, geometry=list(store.values()), crs=config.CRS_METRIC).to_parquet(
                self._path(key)
            )
        return gpd.GeoDataFrame({"station_id": ids, "budget_m": key}, geometry=[store[s] for s in ids], crs=config.CRS_METRIC)


def circles(stations: gpd.GeoDataFrame, radius_m: float) -> gpd.GeoDataFrame:
    """Círculos de radio fijo (alternativa simple a las isócronas, para comparar)."""
    metric = stations.to_crs(config.CRS_METRIC)
    return gpd.GeoDataFrame(
        {"station_id": metric["station_id"].values, "budget_m": radius_m},
        geometry=metric.geometry.buffer(radius_m, quad_segs=16).values,
        crs=config.CRS_METRIC,
    )


def overlap_zones(polys: gpd.GeoDataFrame, min_count: int = 2) -> gpd.GeoDataFrame:
    """Zonas cubiertas por al menos `min_count` áreas de estaciones distintas, con el número de estaciones."""
    geoms = [g for g in polys.geometry if g is not None and not g.is_empty]
    if len(geoms) < min_count:
        return gpd.GeoDataFrame({"n_stations": []}, geometry=[], crs=polys.crs)
    boundaries = shapely.union_all([shapely.boundary(g) for g in geoms])
    faces = list(shapely.get_parts(shapely.polygonize([boundaries])))
    if not faces:
        return gpd.GeoDataFrame({"n_stations": []}, geometry=[], crs=polys.crs)
    pts = shapely.point_on_surface(faces)
    tree = shapely.STRtree(geoms)
    face_idx, _ = tree.query(pts, predicate="within")
    counts = np.bincount(face_idx, minlength=len(faces))
    gdf = gpd.GeoDataFrame({"n_stations": counts}, geometry=faces, crs=polys.crs)
    gdf = gdf[gdf["n_stations"] >= min_count]
    gdf["n_stations"] = np.minimum(gdf["n_stations"], 4)
    return gdf.dissolve("n_stations", as_index=False)
