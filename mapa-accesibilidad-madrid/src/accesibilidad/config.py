"""Configuración central: rutas, fuentes de datos, redes de transporte y parámetros."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.environ.get("ACCESIBILIDAD_DATA_DIR", PROJECT_ROOT / "data"))
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
CACHE_DIR = DATA_DIR / "cache"

# CRS geográfico de entrada/salida y CRS métrico para cálculos (ETRS89 / UTM 30N).
CRS_WGS84 = "EPSG:4326"
CRS_METRIC = "EPSG:25830"

OSM_PBF_URL = "https://download.geofabrik.de/europe/spain/madrid-latest.osm.pbf"
OSM_PBF_PATH = RAW_DIR / "madrid-latest.osm.pbf"

CRTM_SERVICES_URL = "https://services5.arcgis.com/UxADft6QPcvFyDU1/arcgis/rest/services"
CRTM_LICENSE_URL = "https://www.crtm.es/licencia-de-uso"


@dataclass(frozen=True)
class TransitNetwork:
    """Una red de transporte publicada por el CRTM como servicio "Elementos de la Red".

    Cada servicio tiene las capas 0 = estaciones/paradas, 1 = accesos y 4 = tramos.
    """

    key: str
    label: str
    service: str
    color: str
    line_prefix: str
    enabled_by_default: bool = True
    # EMT e interurbanos usan el mismo esquema de servicio (M6_Red, M8_Red), pero
    # tienen miles de paradas: se activan cambiando available=True (ver README).
    available: bool = True


TRANSIT_NETWORKS: dict[str, TransitNetwork] = {
    n.key: n
    for n in [
        TransitNetwork("metro", "Metro", "M4_Red", "#005aa9", "L"),
        TransitNetwork("cercanias", "Cercanías", "M5_Red", "#d6001c", "C"),
        TransitNetwork("metro_ligero", "Metro Ligero", "M10_Red", "#3a7dda", "ML", enabled_by_default=False),
        TransitNetwork("emt", "EMT (autobús urbano)", "M6_Red", "#1f77b4", "", False, available=False),
        TransitNetwork("interurbanos", "Autobuses interurbanos", "M8_Red", "#2ca02c", "", False, available=False),
    ]
}

# Colores oficiales de línea (los de los GTFS del CRTM).
LINE_COLORS = {
    "L1": "#2DBEF0",
    "L2": "#ED1C24",
    "L3": "#FFD000",
    "L4": "#B65518",
    "L5": "#8FD400",
    "L6": "#98989B",
    "L7": "#EE7518",
    "L8": "#EC82B1",
    "L9": "#A60084",
    "L10": "#005AA9",
    "L11": "#009B3A",
    "L12": "#A49800",
    "R": "#1B3F8B",
    "C1": "#75B6E0",
    "C2": "#00943D",
    "C3": "#952585",
    "C4a": "#2C2A86",
    "C4b": "#2C2A86",
    "C5": "#FECB00",
    "C7": "#E5202A",
    "C8a": "#868584",
    "C8b": "#868584",
    "C9": "#915419",
    "C10": "#BCCF00",
    "ML1": "#3A7DDA",
    "ML2": "#A60084",
    "ML3": "#ED1C24",
    "ML4": "#7DB713",
}


def available_networks() -> list[TransitNetwork]:
    return [n for n in TRANSIT_NETWORKS.values() if n.available]


@dataclass(frozen=True)
class Origin:
    name: str
    lat: float
    lon: float


# Punto de referencia por defecto del ámbito "a X minutos en coche".
DEFAULT_ORIGIN = Origin("Ciudad Financiera Banco Santander (Boadilla del Monte)", 40.3930154, -3.8691104)
DEFAULT_DRIVE_MINUTES = 30


@dataclass(frozen=True)
class Settings:
    walk_times_min: tuple[int, ...] = (5, 10, 15, 20)
    walk_speed_kmh_default: float = 4.8
    walk_speed_kmh_min: float = 3.0
    walk_speed_kmh_max: float = 7.0
    # Ancho del "pasillo" a cada lado de las calles alcanzables al generar polígonos.
    isochrone_buffer_m: float = 35.0
    # Huecos interiores menores que esto (patios de manzana) se rellenan.
    isochrone_fill_holes_m2: float = 40_000.0
    drive_max_minutes: int = 60
    # Las velocidades con maxspeed se reducen como en el perfil de coche de OSRM.
    drive_maxspeed_factor: float = 0.8

    @property
    def max_walk_distance_m(self) -> float:
        return max(self.walk_times_min) / 60 * self.walk_speed_kmh_max * 1000


SETTINGS = Settings()


def ensure_dirs() -> None:
    for d in (RAW_DIR, PROCESSED_DIR, CACHE_DIR):
        d.mkdir(parents=True, exist_ok=True)
