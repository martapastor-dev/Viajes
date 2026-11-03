"""Capa de seguridad: incidencia delictiva por distrito/barrio (Madrid capital) y por municipio de la corona.

Fuentes oficiales:
- Madrid capital: NO existe estadística de delitos por barrio ni por distrito en el portal de datos
  abiertos. El Ayuntamiento publica las actuaciones de la Policía Municipal (personas detenidas e
  investigadas/imputadas) por distrito y mes. Se usa como PROXY de la actividad delictiva: cada barrio
  toma el valor de su distrito. No es un conteo de denuncias por tipo de delito.
- Corona: "Hechos conocidos de infracciones penales por tipología penal" del Ministerio del Interior
  (datos abiertos de la Comunidad de Madrid) por municipio; solo municipios de más de 20.000 habitantes.
  Se usan los años completos de `config.SEGURIDAD_YEARS` (los tres más recientes).

Índice: para cada territorio se suman los hechos de las familias relevantes (patrimonio = hurtos y
robos, violencia = robos con violencia/lesiones/homicidios, drogas) en los años cubiertos, se pasa a
tasa por cada 1.000 habitantes y año y se combina en un índice 0-100 con normalización por percentil
DENTRO de cada fuente (capital entre distritos, corona entre municipios), porque las dos fuentes miden
cosas distintas (actuaciones policiales vs. hechos conocidos). El popup muestra el desglose por familia.
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

from . import config

log = logging.getLogger("accesibilidad.seguridad")

# --------------------------------------------------------------------------- fuentes de datos

# Ministerio del Interior (vía datos abiertos de la Comunidad de Madrid): tipologías por municipio >20.000 hab.
CORONA_CSV_URL = (
    "https://datos.comunidad.madrid/dataset/2c852cf6-2c61-41f3-8d94-c87edad8b18b/resource/"
    "1fb7f93a-d9f1-4269-8487-a2a7acb5dd25/download/"
    "hechos-conocidos-de-infracciones-penales-por-tipologia-en-municipios-mayores-de-20.000-habitante.csv"
)
# Padrón municipal (Comunidad de Madrid): última cifra oficial por municipio y sexo.
POB_MUNIS_CSV_URL = (
    "https://datos.comunidad.madrid/dataset/bf0b4159-21f8-42fa-835c-d0dc6bc5fadf/resource/"
    "bc69f395-1f96-4fc2-a115-025c55b905ad/download/poblacion-empadronada-por-sexo.-municipios.csv"
)
# Ayuntamiento de Madrid: población por distrito y barrio (fecha más reciente publicada).
POB_BARRIO_CSV_URL = (
    "https://datos.madrid.es/dataset/300557-0-poblacion-distrito-barrio/resource/"
    "300557-0-poblacion-distrito-barrio-csv/download/300557-0-poblacion-distrito-barrio-csv.csv"
)
# Límites administrativos oficiales de barrios y distritos (Geoportal del Ayuntamiento de Madrid).
BARRIOS_TOPOJSON_URL = (
    "https://geoportal.madrid.es/fsdescargas/IDEAM_WBGEOPORTAL/LIMITES_ADMINISTRATIVOS/Barrios/TopoJSON/Barrios.json"
)
# Estadísticas policiales mensuales del Ayuntamiento (personas detenidas/imputadas por distrito).
AYTO_STATS_BASE = "https://datos.madrid.es"
AYTO_STATS_DATASET = "212616-0-policia-estadisticas"
AYTO_STATS_DOWNLOADS = f"{AYTO_STATS_BASE}/dataset/{AYTO_STATS_DATASET}/downloads"

MONTHS_ES = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}

# Familias de delito de la corona -> categoría del índice (subcadenas del concepto oficial).
CORONA_CATEGORIES: dict[str, tuple[str, ...]] = {
    "patrimonio": ("hurtos de", "robos con fuerza en domicilios, establecimientos", "robos con fuerza en domicilios de"),
    "violencia": (
        "robos con violencia",
        "lesiones y riña",
        "homicidios dolosos y asesinatos consumados",
        "homicidios dolosos y asesinatos en grado",
    ),
    "drogas": ("tráfico de drogas",),
    "sexual": ("agresión sexual con penetración", "del resto delitos contra la libertad"),
}
# Encabezados normalizados de la hoja SEGURIDAD del Excel mensual -> campo interno.
CAPITAL_SHEET = "SEGURIDAD"
CAPITAL_HEADER_ROW = 2  # fila 0-based con los encabezados de categorías
CAPITAL_FIRST_DATA_ROW = 3
CAPITAL_COLS = {
    "personas": "RELACIONADAS CON LAS PERSONAS",
    "patrimonio": "RELACIONADAS CON EL PATRIMONIO",
    "armas": "POR TENENCIA DE ARMAS",
    "tenencia_drogas": "POR TENENCIA DE DROGAS",
    "consumo_drogas": "POR CONSUMO DE DROGAS",
}
INDEX_CATEGORIES = ("patrimonio", "violencia", "drogas")
INDEX_WEIGHTS = {"patrimonio": 0.45, "violencia": 0.35, "drogas": 0.20}

RAW_SEG_DIR = config.RAW_DIR / "seguridad"
GEOMS_FILE = "seguridad_geometries.geojson"
META_FILE = "seguridad_meta.json"
CAPITAL_SKIP = {"SIN DISTRITO ASIGNADO", "TOTAL"}

# Nombres de municipio que difieren entre fuentes (clave normalizada -> clave normalizada alternativa).
MUNI_ALIASES = {"ROZAS DE MADRID": "LAS ROZAS DE MADRID"}

# Columnas de la tabla final (métricas por territorio) y del GeoDataFrame de salida.
METRIC_COLS = [
    "population",
    "years",
    "index",
    "count_pat",
    "count_viol",
    "count_drug",
    "count_other",
    "rate_pat",
    "rate_viol",
    "rate_drug",
]
POP_COL = "pob_barrio"


# --------------------------------------------------------------------------- utilidades


def norm_name(s: str) -> str:
    """Mayúsculas sin acentos ni signos: 'Fuencarral-El Pardo' -> 'FUENCARRAL EL PARDO'."""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).upper()
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9]+", " ", s)).strip()


def _article_key(s: str) -> str:
    return " ".join(t for t in norm_name(s).split() if t not in {"EL", "LA", "LOS", "LAS"})


def match_name(name: str, index: pd.Index | set[str]) -> str | None:
    """Clave normalizada de `name` dentro de `index`; si no, comparación ignorando artículos sueltos."""
    key = MUNI_ALIASES.get(norm_name(name), norm_name(name))
    keys = set(index)
    if key in keys:
        return key
    hit = {c for c in keys if _article_key(c) == _article_key(key)}
    return hit.pop() if len(hit) == 1 else None


def _num(value) -> float:
    try:
        return float(str(value).strip().replace(".", "").replace(",", ".") or 0)
    except ValueError:
        return 0.0


def _http_get(url: str, dest: Path, force: bool = False) -> Path:
    if dest.exists() and not force:
        return dest
    import urllib.request

    log.info("Descargando %s", url)
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "mapa-accesibilidad-madrid/0.1"})
    with urllib.request.urlopen(req, timeout=180) as resp, open(dest, "wb") as fh:
        fh.write(resp.read())
    return dest


# --------------------------------------------------------------------------- descarga


def _ayto_month_urls(force: bool = False) -> dict[str, str]:
    """Mapa 'YYYY-MM' -> URL de descarga del Excel mensual (resuelve la página de descargas del CKAN)."""
    import urllib.request

    d = RAW_SEG_DIR
    page = d / "_ayto_downloads.html"
    pkg = d / "_ayto_package.json"
    targets = (
        (page, AYTO_STATS_DOWNLOADS),
        (pkg, f"{AYTO_STATS_BASE}/api/3/action/package_show?id={AYTO_STATS_DATASET}"),
    )
    for path, url in targets:
        if force or not path.exists():
            req = urllib.request.Request(url, headers={"User-Agent": "mapa-accesibilidad-madrid/0.1"})
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(urllib.request.urlopen(req, timeout=120).read())
    resources = {r["id"]: r for r in json.loads(pkg.read_text())["result"]["resources"]}
    urls = {}
    for rid, title in re.findall(
        r'<a[^>]*href="/dataset/\d+-\d+-[^"]+/resource/([^"/]+)"[^>]*title="([^"]+)"',
        page.read_text(encoding="utf-8", errors="replace"),
    ):
        m = re.match(r"Actuaciones Policía Municipal\.\s*([A-Za-záéíóúñ]+)\s+(\d{4})\.?$", title.strip())
        if not m:
            continue
        year, month = int(m.group(2)), MONTHS_ES[m.group(1).lower()]
        if year not in config.SEGURIDAD_YEARS:
            continue
        res = resources.get(rid)
        if res and res.get("url"):
            urls[f"{year}-{month:02d}"] = res["url"]
    return urls


def ensure_downloads(force: bool = False) -> dict[str, Path]:
    """Descarga (si falta) todos los ficheros de seguridad en RAW_DIR/seguridad y devuelve sus rutas."""
    d = RAW_SEG_DIR
    files = {
        "corona": _http_get(CORONA_CSV_URL, d / "corona_penal_municipios.csv", force),
        "pob_munis": _http_get(POB_MUNIS_CSV_URL, d / "poblacion_municipios.csv", force),
        "pob_barrio": _http_get(POB_BARRIO_CSV_URL, d / "poblacion_distrito_barrio.csv", force),
        "barrios": _http_get(BARRIOS_TOPOJSON_URL, d / "barrios_topojson.json", force),
    }
    ayto_dir = d / "ayto_mensual"
    ayto_dir.mkdir(parents=True, exist_ok=True)
    for key, url in _ayto_month_urls(force=force).items():
        path = ayto_dir / f"{key}.xlsx"
        _http_get(url, path, force)
        files[f"ayto_{key}"] = path
    expected = {f"{y}-{m:02d}" for y in config.SEGURIDAD_YEARS for m in range(1, 13)}
    missing = sorted(expected - {k[5:] for k in files if k.startswith("ayto_")})
    if missing:
        log.warning("Meses del ayuntamiento no resueltos: %s", missing)
    return files


# --------------------------------------------------------------------------- parsers


def parse_corona(path: Path) -> pd.DataFrame:
    """Hechos conocidos por municipio y familia de delito, sumados en los años de `SEGURIDAD_YEARS`."""
    rows = pd.read_csv(path, sep=";", encoding="latin-1", dtype=str).fillna("")
    rows = rows[rows["Año"].isin({str(y) for y in config.SEGURIDAD_YEARS})]
    years = sorted({int(y) for y in rows["Año"]})
    all_needles = "|".join(n for v in CORONA_CATEGORIES.values() for n in v)
    out = []
    for muni, grp in rows.groupby("Municipio"):
        rec = {"municipio_raw": muni.strip(), "years": ",".join(str(y) for y in years)}
        is_total = grp["Concepto"].str.startswith("Total hechos")
        for cat, needles in CORONA_CATEGORIES.items():
            mask = grp["Concepto"].str.contains("|".join(needles), regex=True) & ~is_total
            rec[f"count_{cat}"] = grp.loc[mask, "Valor"].map(_num).sum()
        rest = grp[~grp["Concepto"].str.contains(all_needles + "|Total hechos", regex=True) & ~is_total]
        rec["count_otro"] = rest["Valor"].map(_num).sum()
        out.append(rec)
    return pd.DataFrame(out)


def _read_ayto_month(path: Path) -> pd.DataFrame | None:
    """Hoja SEGURIDAD de un Excel mensual -> (distrito, personas, patrimonio, armas, tenencia, consumo)."""
    import openpyxl

    try:
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    except Exception as exc:  # noqa: BLE001 - un mes corrupto no debe tumbar la capa
        log.warning("No se pudo leer %s: %s", path, exc)
        return None
    if CAPITAL_SHEET not in wb.sheetnames:
        wb.close()
        return None
    ws = wb[CAPITAL_SHEET]
    rows = list(ws.iter_rows(values_only=True))
    wb.close()
    header = [norm_name(str(c)) for c in rows[CAPITAL_HEADER_ROW][1:6]]
    cols = [k for k, v in CAPITAL_COLS.items() if v in header]
    recs = []
    for r in rows[CAPITAL_FIRST_DATA_ROW:]:
        if not r or not r[0]:
            continue
        name = str(r[0]).strip().upper()
        if name in CAPITAL_SKIP:
            continue
        values = r[1:6]
        rec = {"distrito_raw": name}
        ok = True
        for col in cols:
            pos = header.index(CAPITAL_COLS[col])
            try:
                rec[col] = float(values[pos])
            except (TypeError, ValueError, IndexError):
                ok = False
                break
        if ok:
            recs.append(rec)
    return pd.DataFrame(recs) if recs else None


def parse_capital(paths: list[Path]) -> pd.DataFrame:
    """Suma de las actuaciones policiales mensuales por distrito en los años de `SEGURIDAD_YEARS`."""
    frames = []
    months = set()
    for p in paths:
        df = _read_ayto_month(p)
        if df is None or df.empty:
            continue
        months.add(p.stem)
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    all_df = pd.concat(frames, ignore_index=True)
    agg = all_df.groupby("distrito_raw")[list(CAPITAL_COLS)].sum().reset_index()
    agg["months"] = len(frames)
    agg["years"] = ",".join(sorted({m[:4] for m in months}))
    return agg


def load_populations() -> tuple[pd.Series, pd.DataFrame]:
    """Población más reciente: (serie por municipio de la corona, tabla distrito/barrio de Madrid)."""
    d = RAW_SEG_DIR
    munis = pd.read_csv(d / "poblacion_municipios.csv", sep=";", encoding="latin-1", dtype=str).fillna("")
    latest = munis["Año"].max()
    munis = munis[(munis["Año"] == latest) & (munis["Tipo territorio"] == "Municipios") & (munis["Sexo"] == "Total")]
    muni_pop = munis.set_index("Territorio")["Valor"].map(_num)
    muni_pop.index = muni_pop.index.map(norm_name)
    muni_pop = muni_pop.groupby(level=0).sum()

    barrios = pd.read_csv(d / "poblacion_distrito_barrio.csv", sep=";", encoding="utf-8-sig", dtype=str).fillna("")
    latest_f = sorted(barrios["fecha"])[-1]
    barrios = barrios[barrios["fecha"] == latest_f].copy()
    barrios["pob"] = barrios["num_personas"].str.replace(".", "", regex=False).map(_num)
    barrios["distrito_key"] = barrios["distrito"].map(norm_name)
    barrios["bar_key"] = barrios["cod_barrio"].str.replace(".", "", regex=False).astype(int)
    return muni_pop, barrios


def barrio_population_lookup(pob_barrios: pd.DataFrame) -> pd.Series:
    """Población por barrio indexada por (código distrito*10 + número de barrio), como en el TopoJSON."""
    pob = pob_barrios.copy()
    pob["bar_key"] = pob["bar_key"].astype(int)
    pob["full_key"] = (pob["bar_key"] // 10) * 10 + (pob["bar_key"] % 10)
    return pob.groupby("full_key")["pob"].sum()


# --------------------------------------------------------------------------- tabla de métricas


def _capital_rows(agg: pd.DataFrame, pob_barrios: pd.DataFrame) -> list[dict]:
    dist_pop = pob_barrios.groupby("distrito_key")["pob"].sum()
    n_years = agg["months"].max() / 12
    rows = []
    for _, r in agg.iterrows():
        key = norm_name(r["distrito_raw"])
        pop = float(dist_pop.get(key, np.nan))
        rec = {
            "source": "capital",
            "kind": "distrito",
            "name": str(r["distrito_raw"]).title(),
            "district": str(r["distrito_raw"]).title(),
            "municipality": "Madrid",
            "population": pop,
            "years": r["years"],
            "count_pat": float(r["patrimonio"]),
            "count_viol": float(r["personas"]),
            "count_drug": float(r["tenencia_drogas"]) + float(r["consumo_drogas"]),
            "count_other": float(r["armas"]),
        }
        for cat, col in (("pat", "count_pat"), ("viol", "count_viol"), ("drug", "count_drug")):
            rec[f"rate_{cat}"] = rec[col] / n_years / pop * 1000 if pop and pop > 0 else np.nan
        rows.append(rec)
    return rows


def _corona_rows(corona: pd.DataFrame, muni_pop: pd.Series, boundary_names: dict[str, str]) -> list[dict]:
    rows = []
    for _, r in corona.iterrows():
        raw = str(r["municipio_raw"]).strip()
        if norm_name(raw) == "MADRID":
            continue  # la capital se cubre con el proxy por distrito
        key = match_name(raw, boundary_names.keys())
        if key is None:
            log.warning("Municipio de la corona sin límite municipal: %s", raw)
            continue
        pop_key = match_name(raw, muni_pop.index)
        pop = float(muni_pop.loc[pop_key]) if pop_key else np.nan
        years = [y for y in str(r.get("years", "")).split(",") if y]
        n_years = len(years) or len(config.SEGURIDAD_YEARS)
        rec = {
            "source": "corona",
            "kind": "municipio",
            "name": boundary_names[key],
            "name_key": key,
            "district": None,
            "municipality": boundary_names[key],
            "population": pop,
            "years": r.get("years", ""),
            "count_pat": float(r.get("count_patrimonio", 0) or 0),
            "count_viol": float(r.get("count_violencia", 0) or 0),
            "count_drug": float(r.get("count_drogas", 0) or 0),
            "count_other": float(r.get("count_otro", 0) or 0) + float(r.get("count_sexual", 0) or 0),
        }
        for cat, col in (("pat", "count_pat"), ("viol", "count_viol"), ("drug", "count_drug")):
            rec[f"rate_{cat}"] = rec[col] / n_years / pop * 1000 if pop and pop > 0 else np.nan
        rows.append(rec)
    return rows


def _missing_corona_rows(boundaries: gpd.GeoDataFrame, table: pd.DataFrame) -> list[dict]:
    """Municipios sin estadística oficial (típicamente <20.000 habitantes)."""
    have = set(table.loc[table["source"] == "corona", "name_key"])
    rows = []
    for name in boundaries["name"]:
        key = norm_name(name)
        if key in have:
            continue
        rows.append(
            {
                "source": "corona",
                "kind": "municipio",
                "name": name,
                "name_key": key,
                "district": None,
                "municipality": name,
                "population": np.nan,
                "years": "",
                "count_pat": np.nan,
                "count_viol": np.nan,
                "count_drug": np.nan,
                "count_other": np.nan,
                "rate_pat": np.nan,
                "rate_viol": np.nan,
                "rate_drug": np.nan,
                "index": np.nan,
            }
        )
    return rows


def _rank_index(df: pd.DataFrame) -> pd.Series:
    """Percentil 0-100 por categoría dentro de cada fuente, combinado con pesos. NaN sin datos."""
    out = pd.Series(np.nan, index=df.index, dtype=float)
    for _, sub in df.groupby("source"):
        ok = sub["population"].notna() & (sub["population"] > 0)
        if not ok.any():
            continue
        acc = pd.Series(0.0, index=sub.index)
        for cat, weight in (
            ("pat", INDEX_WEIGHTS["patrimonio"]),
            ("viol", INDEX_WEIGHTS["violencia"]),
            ("drug", INDEX_WEIGHTS["drogas"]),
        ):
            vals = sub.loc[ok, f"rate_{cat}"]
            if len(vals) == 0:
                continue
            acc.loc[ok] += vals.rank(pct=True) * 100 * weight
        out.loc[sub.index] = (acc / sum(INDEX_WEIGHTS.values())).where(ok)
    return out


def build_table(boundary_names: dict[str, str] | None = None) -> pd.DataFrame:
    """Tabla de métricas por territorio: distritos de Madrid + municipios de la corona con datos."""
    files = ensure_downloads()
    corona = parse_corona(files["corona"])
    muni_pop, pob_barrios = load_populations()
    capital = parse_capital([p for k, p in files.items() if k.startswith("ayto_")])
    if boundary_names is None:
        boundary_names = {}
    rows = _capital_rows(capital, pob_barrios) + _corona_rows(corona, muni_pop, boundary_names)
    table = pd.DataFrame(rows)
    table["index"] = _rank_index(table)
    return table


# --------------------------------------------------------------------------- geometrías y salida


def build_geometries(table: pd.DataFrame | None = None) -> gpd.GeoDataFrame:
    """Une las métricas con las geometrías: barrios oficiales (capital) y municipios (corona).

    Devuelve un GeoDataFrame en EPSG:4326 con una fila por barrio/municipio, con las métricas de su
    distrito (capital) o municipio (corona) en columnas. Los municipios sin datos quedan con index NaN.
    """
    bounds = gpd.read_file(config.PROCESSED_DIR / "boundaries.geojson")
    boundary_names = {norm_name(n): n for n in bounds.loc[bounds["admin_level"] == 8, "name"]}
    if table is None:
        table = build_table(boundary_names)
    table = table.copy()
    table["name_key"] = table["name"].map(norm_name)

    # --- Madrid capital: barrios oficiales; cada barrio toma las métricas de su distrito
    cap = table[table["source"] == "capital"]
    cap_by_key = cap.set_index(cap["name_key"])
    barrios = gpd.read_file(RAW_SEG_DIR / "barrios_topojson.json", engine="pyogrio")
    if barrios.crs is None:
        barrios = barrios.set_crs(config.CRS_WGS84)
    barrios = barrios.to_crs(config.CRS_WGS84)
    barrios = barrios.rename(columns={"NOMBRE": "barrio", "NOMDIS": "distrito_raw"})
    barrios["name_key"] = barrios["distrito_raw"].map(norm_name)
    miss = ~barrios["name_key"].isin(cap_by_key.index)
    if miss.any():
        log.warning("Distritos sin métricas para barrios: %s", sorted(set(barrios.loc[miss, "distrito_raw"])))
    join_cols = [c for c in METRIC_COLS if c in table.columns]
    gdf_cap = barrios.merge(cap_by_key[join_cols], left_on="name_key", right_index=True, how="left")
    gdf_cap["district"] = gdf_cap["distrito_raw"]  # nombre oficial del distrito
    gdf_cap["municipality"] = "Madrid"
    gdf_cap["kind"] = "barrio"
    gdf_cap["source"] = "capital"
    # Población del propio barrio (solo informativa; las tasas usan la del distrito).
    _, pob_barrios = load_populations()
    look = barrio_population_lookup(pob_barrios)
    gdf_cap["bar_key"] = gdf_cap["COD_BAR"].astype(int)  # distrito*10 + nº de barrio
    gdf_cap[POP_COL] = gdf_cap["bar_key"].map(look)

    # --- Corona: municipios; se añaden filas "sin datos" para los que no tienen estadística
    cor = pd.concat(
        [table[table["source"] == "corona"], pd.DataFrame(_missing_corona_rows(bounds[bounds["admin_level"] == 8], table))],
        ignore_index=True,
    )
    cor_by_key = cor.set_index(cor["name_key"])
    munis = bounds[bounds["admin_level"] == 8].to_crs(config.CRS_WGS84).copy()
    munis["name_key"] = munis["name"].map(norm_name)
    gdf_cor = munis.merge(
        cor_by_key[METRIC_COLS + ["kind", "district", "municipality", "source"]],
        left_on="name_key",
        right_index=True,
        how="inner",
    )
    gdf_cor = gdf_cor.rename(columns={"name": "geom_name"})
    gdf_cor["kind"] = "municipio"
    gdf_cor["source"] = "corona"
    gdf_cor[POP_COL] = np.nan

    frame_cap = gdf_cap[
        ["kind", "source", "district", "municipality", POP_COL] + [c for c in METRIC_COLS if c in gdf_cap.columns]
    ].copy()
    frame_cap["barrio"] = gdf_cap["barrio"]
    frame_cor = gdf_cor[
        ["kind", "source", "district", "municipality", POP_COL] + [c for c in METRIC_COLS if c in gdf_cor.columns]
    ].copy()
    frame_cor["barrio"] = gdf_cor["geom_name"]

    out = pd.concat(
        [gpd.GeoDataFrame(frame_cap, geometry=gdf_cap.geometry), gpd.GeoDataFrame(frame_cor, geometry=gdf_cor.geometry)],
        ignore_index=True,
    )
    out = gpd.GeoDataFrame(out, geometry="geometry", crs=config.CRS_WGS84)
    out["geometry"] = out.to_crs(config.CRS_METRIC).geometry.simplify(8).to_crs(config.CRS_WGS84)
    return out


def processed_paths() -> tuple[Path, Path]:
    return config.PROCESSED_DIR / GEOMS_FILE, config.PROCESSED_DIR / META_FILE


def build(force: bool = False) -> gpd.GeoDataFrame:
    """Construye (o reutiliza) la capa de seguridad procesada en data/processed."""
    geoms_path, meta_path = processed_paths()
    if geoms_path.exists() and not force:
        meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
        if meta.get("years") == config.SEGURIDAD_YEARS:
            return gpd.read_file(geoms_path)
    gdf = build_geometries()
    meta = {
        "years": config.SEGURIDAD_YEARS,
        "sources": [
            "Ayuntamiento de Madrid: actuaciones policiales por distrito (proxy)",
            "Ministerio del Interior vía Comunidad de Madrid: hechos conocidos por tipología",
        ],
        "built": pd.Timestamp.now().isoformat(timespec="seconds"),
    }
    gdf.to_file(geoms_path, driver="GeoJSON")
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2))
    return gdf
