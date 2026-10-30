"""Descarga de datos abiertos (GTFS del CRTM y extracto OSM de Geofabrik)."""

from __future__ import annotations

import logging
import shutil
import urllib.request
from pathlib import Path

from . import config

log = logging.getLogger(__name__)
USER_AGENT = "mapa-accesibilidad-madrid/0.1 (uso personal)"


def _download(url: str, dest: Path, force: bool = False) -> Path:
    if dest.exists() and not force:
        log.info("Ya existe %s; no se descarga de nuevo", dest)
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    log.info("Descargando %s -> %s", url, dest)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=300) as resp, open(tmp, "wb") as fh:
        shutil.copyfileobj(resp, fh)
    tmp.replace(dest)
    return dest


def download_osm(force: bool = False) -> Path:
    return _download(config.OSM_PBF_URL, config.OSM_PBF_PATH, force)
