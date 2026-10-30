"""Etapa 3: importación de viviendas y su accesibilidad a estaciones."""

from __future__ import annotations

import io
import json
import logging
import re
import unicodedata
from collections.abc import Callable

import geopandas as gpd
import numpy as np
import pandas as pd

from . import config
from .graph import WalkGraph
from .isochrones import ReachIndex

log = logging.getLogger(__name__)

COLUMN_ALIASES = {
    "lat": ["lat", "latitud", "latitude", "y"],
    "lon": ["lon", "lng", "long", "longitud", "longitude", "x"],
    "precio": ["precio", "price", "importe", "precio eur", "precio euros"],
    "superficie": ["superficie", "m2", "metros", "metros cuadrados", "superficie m2", "size", "area"],
    "direccion": ["direccion", "address", "ubicacion", "calle"],
    "titulo": ["titulo", "title", "nombre", "descripcion", "anuncio"],
    "url": ["url", "enlace", "link"],
}

# Pesos por defecto del indicador experimental (no validado).
DEFAULT_WEIGHTS = {"proximidad": 0.4, "n_estaciones": 0.2, "n_lineas": 0.25, "metro_y_cercanias": 0.15}
CAP_STATIONS = 4
CAP_LINES = 6


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def read_listings(data: bytes, filename: str) -> pd.DataFrame:
    """Lee un CSV (separador , o ;) o un Excel y renombra las columnas reconocidas."""
    if filename.lower().endswith((".xlsx", ".xls")):
        df = pd.read_excel(io.BytesIO(data))
    else:
        text = data.decode("utf-8-sig", errors="replace")
        sep = ";" if text.splitlines()[0].count(";") > text.splitlines()[0].count(",") else ","
        df = pd.read_csv(io.StringIO(text), sep=sep, decimal="," if sep == ";" else ".")
    rename = {}
    normalized = {_norm(c): c for c in df.columns}
    for target, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            if alias in normalized and normalized[alias] not in rename:
                rename[normalized[alias]] = target
                break
    df = df.rename(columns=rename)
    for col in ("lat", "lon", "precio", "superficie"):
        if col in df:
            df[col] = pd.to_numeric(
                df[col].astype(str).str.replace(r"[^\d,.\-]", "", regex=True).str.replace(",", ".", regex=False), errors="coerce"
            )
    return df


def geocode_missing(df: pd.DataFrame, progress: Callable[[int, int], None] | None = None) -> pd.DataFrame:
    """Geocodifica con Nominatim (1 petición/s, con caché en disco) las filas sin coordenadas."""
    from geopy.extra.rate_limiter import RateLimiter
    from geopy.geocoders import Nominatim

    df = df.copy()
    for col in ("lat", "lon"):
        if col not in df:
            df[col] = np.nan
    if "direccion" not in df:
        return df
    cache_path = config.CACHE_DIR / "geocode.json"
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    geocoder = RateLimiter(Nominatim(user_agent="mapa-accesibilidad-madrid").geocode, min_delay_seconds=1.1)
    todo = df.index[df["lat"].isna() & df["direccion"].notna()]
    for i, idx in enumerate(todo):
        address = str(df.at[idx, "direccion"])
        if address not in cache:
            loc = geocoder(f"{address}, Comunidad de Madrid, España", country_codes="es")
            cache[address] = [loc.latitude, loc.longitude] if loc else None
        if cache[address]:
            df.at[idx, "lat"], df.at[idx, "lon"] = cache[address]
        if progress:
            progress(i + 1, len(todo))
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(cache, ensure_ascii=False))
    return df


def analyze(
    homes: pd.DataFrame,
    wg: WalkGraph,
    reach: ReachIndex,
    stations: gpd.GeoDataFrame,
    budget_m: float,
    speed_kmh: float,
    weights: dict[str, float] | None = None,
) -> tuple[gpd.GeoDataFrame, pd.DataFrame]:
    """Calcula, para cada vivienda, las estaciones accesibles andando dentro de `budget_m`.

    La distancia es simétrica: se reutiliza el alcance precalculado desde cada estación
    y se le suma la distancia de la vivienda a su nodo de calle más cercano.
    Devuelve (viviendas con resumen, tabla vivienda-estación).
    """
    homes = homes[homes["lat"].notna() & homes["lon"].notna()].reset_index(drop=True)
    gdf = gpd.GeoDataFrame(homes, geometry=gpd.points_from_xy(homes["lon"], homes["lat"]), crs=config.CRS_WGS84)
    if "precio" in gdf and "superficie" in gdf:
        gdf["eur_m2"] = gdf["precio"] / gdf["superficie"].replace(0, np.nan)
    st = stations.set_index("station_id")
    snap = wg.snap_lonlat(gdf["lon"].values, gdf["lat"].values)
    m_per_min = speed_kmh * 1000 / 60
    pair_rows = []
    for i, (node, off) in enumerate(zip(snap.node, snap.distance_m)):
        found = reach.stations_at_node(int(node))
        found = found[found["station_id"].isin(st.index)]
        found["dist"] = found["dist"] + off
        found = found[found["dist"] <= budget_m]
        for sid, d in zip(found["station_id"], found["dist"]):
            pair_rows.append({"vivienda": i, "station_id": sid, "metros": float(d), "minutos": float(d / m_per_min)})
    pairs = pd.DataFrame(pair_rows, columns=["vivienda", "station_id", "metros", "minutos"])
    if not pairs.empty:
        pairs["estacion"] = pairs["station_id"].map(st["name"])
        pairs["red"] = pairs["station_id"].map(st["mode"]).map(lambda k: config.TRANSIT_NETWORKS[k].label)
        pairs["lineas"] = pairs["station_id"].map(st["lines"]).map(", ".join)
        pairs = pairs.sort_values(["vivienda", "minutos"])

    summary = []
    for i in range(len(gdf)):
        p = pairs[pairs["vivienda"] == i]
        if p.empty:
            summary.append({"n_estaciones": 0, "min_a_estacion": np.nan, "estacion_mas_cercana": "", "lineas": "", "redes": ""})
            continue
        lines = sorted({ln for sid in p["station_id"] for ln in st.at[sid, "lines"]})
        summary.append(
            {
                "n_estaciones": len(p),
                "min_a_estacion": p["minutos"].iloc[0],
                "estacion_mas_cercana": p["estacion"].iloc[0],
                "lineas": ", ".join(lines),
                "redes": ", ".join(sorted(set(p["red"]))),
            }
        )
    gdf = pd.concat([gdf, pd.DataFrame(summary)], axis=1)
    gdf["indicador_experimental"] = experimental_score(gdf, budget_m / m_per_min, weights)
    return gpd.GeoDataFrame(gdf, geometry="geometry", crs=config.CRS_WGS84), pairs


def experimental_score(summary: pd.DataFrame, max_minutes: float, weights: dict[str, float] | None = None) -> pd.Series:
    """Indicador 0-100 orientativo. Fórmula y pesos provisionales: NO es una medida validada."""
    w = {**DEFAULT_WEIGHTS, **(weights or {})}
    total = sum(w.values()) or 1.0
    n_lines = summary["lineas"].map(lambda s: len([x for x in s.split(", ") if x]))
    comps = {
        "proximidad": (1 - summary["min_a_estacion"] / max_minutes).clip(0, 1).fillna(0),
        "n_estaciones": (summary["n_estaciones"] / CAP_STATIONS).clip(0, 1),
        "n_lineas": (n_lines / CAP_LINES).clip(0, 1),
        "metro_y_cercanias": summary["redes"].map(lambda s: sum(k in s for k in ("Metro", "Cercanías")) / 2),
    }
    return (100 * sum(w[k] * comps[k] for k in comps) / total).round(1)
