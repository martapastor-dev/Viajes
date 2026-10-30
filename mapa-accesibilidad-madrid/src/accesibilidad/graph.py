"""Grafos a pie y en coche sobre las tablas de nodos/aristas, con búsquedas de caminos mínimos."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

import numpy as np
import pandas as pd
from pyproj import Transformer
from scipy import sparse
from scipy.sparse.csgraph import connected_components, dijkstra
from scipy.spatial import cKDTree

from . import config

log = logging.getLogger(__name__)
_TO_METRIC = Transformer.from_crs(config.CRS_WGS84, config.CRS_METRIC, always_xy=True)


def to_metric(lon, lat) -> tuple[np.ndarray, np.ndarray]:
    x, y = _TO_METRIC.transform(np.asarray(lon, dtype=float), np.asarray(lat, dtype=float))
    return np.atleast_1d(x), np.atleast_1d(y)


@dataclass
class Snap:
    node: np.ndarray
    distance_m: np.ndarray


class _BaseGraph:
    def __init__(self, nodes: pd.DataFrame, u: np.ndarray, v: np.ndarray, weight: np.ndarray, directed: bool):
        self.x = nodes["x"].to_numpy()
        self.y = nodes["y"].to_numpy()
        self.n = len(nodes)
        self.u = u
        self.v = v
        self.weight = weight
        self.directed = directed

    @cached_property
    def csr(self) -> sparse.csr_matrix:
        m = sparse.coo_matrix((self.weight, (self.u, self.v)), shape=(self.n, self.n)).tocsr()
        if not self.directed:
            m = m.maximum(m.T).tocsr()
        return m

    @cached_property
    def _main_nodes(self) -> np.ndarray:
        """Nodos del componente conexo principal (evita encajar puntos en islas aisladas)."""
        conn = "strong" if self.directed else "weak"
        _, labels = connected_components(self.csr, directed=self.directed, connection=conn)
        used = np.zeros(self.n, dtype=bool)
        used[self.u] = True
        used[self.v] = True
        counts = np.bincount(labels[used])
        return np.flatnonzero(used & (labels == counts.argmax()))

    @cached_property
    def _tree(self) -> cKDTree:
        return cKDTree(np.column_stack([self.x[self._main_nodes], self.y[self._main_nodes]]))

    def snap_xy(self, x, y) -> Snap:
        dist, i = self._tree.query(np.column_stack([np.atleast_1d(x), np.atleast_1d(y)]))
        return Snap(self._main_nodes[i], dist)

    def snap_lonlat(self, lon, lat) -> Snap:
        return self.snap_xy(*to_metric(lon, lat))


class WalkGraph(_BaseGraph):
    """Red peatonal no dirigida; el peso es la longitud en metros."""

    def __init__(self, nodes: pd.DataFrame, edges: pd.DataFrame):
        super().__init__(nodes, edges["u"].to_numpy(), edges["v"].to_numpy(), edges["length"].to_numpy(np.float64), False)
        self._mid_x = (self.x[self.u] + self.x[self.v]) / 2
        self._mid_y = (self.y[self.u] + self.y[self.v]) / 2

    def reach_from(self, src_x, src_y, max_dist: float) -> tuple[np.ndarray, np.ndarray]:
        """Distancia por la red desde uno o varios puntos de origen (p. ej. los accesos de una estación).

        Cada origen se une a su nodo más cercano con una arista de su distancia de encaje.
        Devuelve (nodos, distancias) para los nodos alcanzables a <= max_dist metros.
        """
        snap = self.snap_xy(src_x, src_y)
        cx, cy = np.mean(np.atleast_1d(src_x)), np.mean(np.atleast_1d(src_y))
        spread = float(np.max(np.hypot(self.x[snap.node] - cx, self.y[snap.node] - cy)))
        r = max_dist + spread + 200
        mask = (np.abs(self._mid_x - cx) <= r) & (np.abs(self._mid_y - cy) <= r)
        eu, ev, ew = self.u[mask], self.v[mask], self.weight[mask]
        local, inv = np.unique(np.concatenate([eu, ev, snap.node]), return_inverse=True)
        m = len(local)
        lu, lv = inv[: len(eu)], inv[len(eu) : 2 * len(eu)]
        ls = inv[2 * len(eu) :]
        # Nodo virtual (índice m) conectado a cada origen; aristas en ambos sentidos.
        rows = np.concatenate([lu, lv, np.full(len(ls), m)])
        cols = np.concatenate([lv, lu, ls])
        w = np.concatenate([ew, ew, snap.distance_m + 1e-3])
        g = sparse.csr_matrix((w, (rows, cols)), shape=(m + 1, m + 1))
        dist = dijkstra(g, directed=True, indices=m, limit=max_dist)
        ok = np.isfinite(dist[:m])
        return local[ok].astype(np.int32), dist[:m][ok].astype(np.float32)


class DriveGraph(_BaseGraph):
    """Red viaria dirigida; el peso es el tiempo en segundos."""

    def __init__(self, nodes: pd.DataFrame, edges: pd.DataFrame):
        seconds = edges["length"].to_numpy(np.float64) / (edges["speed_kmh"].to_numpy(np.float64) / 3.6)
        super().__init__(nodes, edges["u"].to_numpy(), edges["v"].to_numpy(), seconds, True)

    def travel_times(self, lon: float, lat: float, max_seconds: float, towards: bool = False) -> np.ndarray:
        """Tiempo (s) desde el punto a cada nodo, o desde cada nodo hasta el punto si towards=True."""
        snap = self.snap_lonlat(lon, lat)
        g = self.csr.T.tocsr() if towards else self.csr
        return dijkstra(g, directed=True, indices=int(snap.node[0]), limit=max_seconds)


def load_nodes(processed_dir: Path = config.PROCESSED_DIR) -> pd.DataFrame:
    return pd.read_parquet(processed_dir / "nodes.parquet")


def load_walk_graph(processed_dir: Path = config.PROCESSED_DIR, nodes: pd.DataFrame | None = None) -> WalkGraph:
    nodes = load_nodes(processed_dir) if nodes is None else nodes
    return WalkGraph(nodes, pd.read_parquet(processed_dir / "walk_edges.parquet"))


def load_drive_graph(processed_dir: Path = config.PROCESSED_DIR, nodes: pd.DataFrame | None = None) -> DriveGraph:
    nodes = load_nodes(processed_dir) if nodes is None else nodes
    return DriveGraph(nodes, pd.read_parquet(processed_dir / "drive_edges.parquet"))
